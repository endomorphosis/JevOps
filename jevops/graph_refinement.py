"""Train-only graph diagnostics/selection followed by a frozen transfer probe.

The fit API cannot receive evaluation rows. The evaluation API receives immutable
checkpoint data, not an optimizer. New goal layouts are a transfer smoke test,
not an independent mathematical benchmark or permission to promote a model.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import time

import torch

from .autoencoder_training import AutoencoderConfig, learning_rate_for_step
from .expr_dag import CODEC
from .graph_policy import GraphEditPolicy, graph_context, graph_tensors, metrics
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .rewrite_distillation import _validate_rows
from .rewrite_policy import body_of, mine_template
from .structural_ablation import control_rows
from .structural_policy import StructuralEditPolicy, digest, source_context
from .structural_training import _checked_export, _envelope, collect_structural_pairs

FIT_SCHEMA = "jevops-training-only-graph-refinement/v1"
EVAL_SCHEMA = "jevops-frozen-graph-transfer/v1"


def acceptance_gates(chosen, baseline):
    """Missing metrics or partial coverage fail, even if savings look favorable."""
    count = chosen["sample_count"]
    gates = {"complete_validity": count > 0 and chosen["valid_count"] == count,
             "complete_cost_and_loss_coverage": count > 0 and chosen["nonregressing_count"] == chosen["loss_sample_count"] == count,
             "baseline_complete_loss_coverage": baseline["sample_count"] == baseline["loss_sample_count"] == count,
             "baseline_savings_nonregression": chosen["verified_saved_tokens"] >= baseline["verified_saved_tokens"]}
    for metric in ("cross_entropy", "expected_cosine_loss"):
        a, b = chosen[metric], baseline[metric]
        gates[metric + "_nonregression"] = (type(a) in (int, float) and type(b) in (int, float)
                                            and math.isfinite(a) and math.isfinite(b) and a <= b + 1e-9)
    return gates


class CompilerBudget:
    def __init__(self, compile_fn, limit):
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("invalid compile budget")
        self.compile_fn, self.limit = compile_fn, limit
        self.cache, self.attempts = {}, []

    def __call__(self, source):
        if source not in self.cache:
            if len(self.attempts) >= self.limit:
                raise ValueError("compile budget exhausted")
            started = time.monotonic()
            try:
                receipt = self.compile_fn(source)
            except Exception as exc:
                receipt = {"theorem_ok": False, "reason": type(exc).__name__}
            self.cache[source] = receipt
            self.attempts.append({"source": source, "receipt": receipt, "wall_seconds": time.monotonic()-started})
        return self.cache[source]


def shape_digest(wire):
    """Closed-expression structural identity ignoring binder names/metadata.

    This rejects renamed overlap, not arbitrary equivalent mathematics. It is
    neither a kernel certificate nor a learned feature. Do not use it as truth.
    """
    levels = []
    for row in wire["levels"]:
        levels.append(digest([row[0], [levels[int(j)] for j in row[1:]]
                              if row[0] in {"succ", "max", "imax"} else row[1:]]))
    from .structural_policy import POSITIONS
    nodes = []
    for raw in wire["expressions"]:
        row = copy.deepcopy(raw)
        if row[0] == "mdata":
            nodes.append(nodes[int(row[2])])
            continue
        if row[0] in {"lam", "forall", "let"}:
            row[1] = []
        for p in POSITIONS.get(row[0], ()):
            row[p] = nodes[int(row[p])]
        if row[0] == "sort":
            row[1] = levels[int(row[1])]
        elif row[0] == "const":
            row[2] = [levels[int(i)] for i in row[2]]
        nodes.append(digest(row))
    # Declared type as well as full source proof must be unseen.
    return {"proof": nodes[int(wire["roots"][0])], "type": nodes[int(wire["roots"][1])]}


def layer_diagnostics(model, rows, contexts):
    with torch.no_grad():
        stages = [model.encoder.pooled_stages(graph_tensors(
            ctx.wire(row["source"], model.environment, model.toolchain))) for row, ctx in zip(rows, contexts)]
        return [{"radius": radius, "norms": [float(v[radius].norm()) for v in stages],
                 "pair_distances": [{"left": i, "right": j,
                     "l2": float((stages[i][radius]-stages[j][radius]).norm()),
                     "relative_l2": float((stages[i][radius]-stages[j][radius]).norm() / stages[i][radius].norm().clamp_min(1e-12))}
                    for i in range(len(stages)) for j in range(i+1, len(stages))]}
                for radius in range(model.rounds+1)]


def fit_training(compile_fn, *, environment_sha256, rows=None, epochs=80, seed=17, max_compiles=32):
    """Admit teachers, compare a fixed small grid, select using train loss only.

    Same 80 passes/example by default. Batch arms average before clipping and do
    one update/pass; online arms do one update/example. LR decay is indexed by
    examples consumed, not optimizer updates. These budgets are explicitly not
    matched update counts. Learning-rate candidates are fixed, never eval-tuned.
    """
    if type(epochs) is not int or not 1 <= epochs <= 200:
        raise ValueError("invalid epoch budget")
    rows = list([r for r in control_rows() if r["split"] == "train"] if rows is None else rows)
    # Reject eval rows before reading a target or invoking the compiler.
    if not 2 <= len(rows) <= 16 or any(not isinstance(r, dict) or r.get("split") != "train" for r in rows):
        raise ValueError("refinement accepts training rows only")
    _validate_rows(rows)
    if any(not isinstance(r.get("family"), str) or not r["family"] or len(r["family"]) > 128 for r in rows):
        raise ValueError("training family identity required")
    compiler = CompilerBudget(compile_fn, max_compiles)
    pairs = collect_structural_pairs([{k: v for k, v in r.items() if k != "target"} for r in rows],
                                     {r["id"]: r["target"] for r in rows}, compile_fn=compiler,
                                     environment_sha256=environment_sha256)
    if not pairs["ok"]:
        return {"schema": FIT_SCHEMA, "ok": False, "reason": "teacher_admission", "training_pairs": pairs,
                "compile_attempts": compiler.attempts, "checkpoint_promoted": False}
    bank = {}
    for pair in pairs["pairs"]:
        template = mine_template(pair["text"], body_of(pair["target_text"])[1])
        if template is None:
            raise ValueError("unreachable teacher grammar")
        bank[template["id"]] = template
    templates = [bank[k] for k in sorted(bank)]
    contexts = [graph_context(r["source"], compiler(r["source"]), environment_sha256=environment_sha256) for r in rows]
    fixed_contexts = [source_context(r["source"], compiler(r["source"]), environment_sha256=environment_sha256) for r in rows]
    config = dict(environment_sha256=environment_sha256, toolchain=contexts[0].toolchain)
    models, configurations = {}, {}
    for pooling in ("last", "multiscale"):
        for update in ("online", "batch"):
            for lr in (.05, .15, .25):
                arm = f"{pooling}_{update}_{lr}"
                models[arm] = GraphEditPolicy(templates, seed=seed, pooling=pooling, **config)
                configurations[arm] = {"pooling": pooling, "update": update, "learning_rate": lr, "selectable": True}
    for name, kwargs in (("frozen_multiscale", {"pooling": "multiscale", "freeze_encoder": True}),
                         ("node_bag", {"rounds": 0})):
        models[name] = GraphEditPolicy(templates, seed=seed, **kwargs, **config)
        configurations[name] = {"update": "batch", "learning_rate": .15, "selectable": False}
    models["fixed_graph"] = StructuralEditPolicy(templates, structural=True, **config)
    configurations["fixed_graph"] = {"update": "online", "learning_rate": .15, "selectable": False}
    batch = [{"source": r["source"], "target": r["target"], "split": "train", "context": c} for r, c in zip(rows, contexts)]
    initial_diagnostics = layer_diagnostics(models["last_online_0.15"], rows, contexts)
    initial_encoders = {name: digest({k: v for k, v in model.to_dict()["weights"].items() if k.startswith("encoder.")})
                        for name, model in models.items() if isinstance(model, GraphEditPolicy)}
    def losses(model):
        ctxs = contexts if isinstance(model, GraphEditPolicy) else fixed_contexts
        out = []
        for r, c in zip(rows, ctxs):
            raw = model.objective(r["source"], r["target"], c)
            if raw is None:
                raise ValueError("unreachable training teacher")
            loss = metrics({k: v for k, v in raw.items() if k != "gradient"})
            out.append({"id": r["id"], "loss": loss,
                        "choice": model.predict(r["source"], c)["choice"], "correct": model.predict(r["source"], c)["choice"] == loss["label"]})
        return {"rows": out, "correct_count": sum(r["correct"] for r in out),
                **{key: sum(r["loss"][key] for r in out)/len(out) for key in ("total", "cross_entropy", "expected_cosine_loss")}}
    for model in models.values():
        losses(model)  # Validate all teachers before the first update.
    stats = {}
    for name, model in models.items():
        options = configurations[name]
        cfg = AutoencoderConfig(learning_rate=options["learning_rate"], warmup_steps=0, decay_steps=1000)
        before = losses(model)
        for epoch in range(epochs):
            if options["update"] == "batch":
                model.train_batch(batch, split="train", learning_rate=learning_rate_for_step(cfg, epoch*len(rows)))
            else:
                ctxs = contexts if isinstance(model, GraphEditPolicy) else fixed_contexts
                for r, c in zip(rows, ctxs):
                    model.train_step(r["source"], r["target"], c, split="train", learning_rate=learning_rate_for_step(cfg, model.steps))
        stats[name] = {"before": before, "after": losses(model), "updates": model.steps,
                       "examples_seen": epochs*len(rows), "config": options}
        if isinstance(model, GraphEditPolicy):
            stats[name]["encoder_changed"] = initial_encoders[name] != digest({
                k: v for k, v in model.to_dict()["weights"].items() if k.startswith("encoder.")})
            stats[name]["parameters"] = sum(p.numel() for p in model.parameters())
    selected = min((name for name in models if configurations[name]["selectable"]),
                   key=lambda name: (-stats[name]["after"]["correct_count"], stats[name]["after"]["total"], name))
    result = {"schema": FIT_SCHEMA, "ok": True, "environment_sha256": environment_sha256,
              "epochs": epochs, "seed": seed, "training_rows": rows, "training_pairs": pairs,
              "training_shapes": [shape_digest(c.wire(r["source"], environment_sha256, c.toolchain)) for r, c in zip(rows, contexts)],
              "training_families": sorted({r["family"] for r in rows}), "selected": selected,
              "selection_basis": "training_correct_count_then_mean_CE_plus_cosine_only",
              "statistics": stats, "initial_layer_diagnostics": initial_diagnostics,
              "final_layer_diagnostics": layer_diagnostics(models[selected], rows, contexts),
              "checkpoints": {name: m.to_dict() for name, m in models.items()},
              "compile_attempts": compiler.attempts, "torch_version": str(torch.__version__),
              "checkpoint_promoted": False, "evaluation_accessed": False}
    result["freeze_sha256"] = digest(result)
    return result


def transfer_rows(seed=20260923):
    """New goal layouts; the alias/rfl task is still shared with training.

    Generated only after freeze by the CLI. Hand-designed family labels and
    name-insensitive type hashes do not prove mathematical decontamination.
    """
    rng = random.Random(seed)
    rows = []
    families = (("validation", "constructor_congruence"), ("canary", "function_application"),
                ("holdout", "product_projection"), ("holdout", "list_constructor"))
    for split, family in families:
        for reflexive in (True, False):
            n = rng.randrange(10**8)
            x, y, f, h, a, b, c = [f"{v}_{n}" for v in ("x", "y", "f", "h", "a", "b", "c")]
            right = x if reflexive else y
            binders = f"({x} {y} : Nat)"
            if family == "constructor_congruence":
                goal = f"Nat.succ {x} = Nat.succ {right}"
            elif family == "function_application":
                binders = f"({f} : Nat → Nat) " + binders
                goal = f"{f} {x} = {f} {right}"
            elif family == "product_projection":
                goal = f"({x}, {y}).1 = {right}"
            else:
                goal = f"[{x}] = [{right}]"
            name = f"transfer_{split}_{family}_{n}"
            prefix = f"theorem {name} {binders} ({h} : {goal}) : {goal} := by\n"
            source = prefix + f"  have {a} := {h}\n  have {b} := {a}\n  have {c} := {b}\n  exact {c}\n"
            rows.append({"id": name, "split": split, "family": family, "source": source,
                         "target": prefix + "  rfl\n" if reflexive else source})
    return rows


def evaluate_frozen(fit, rows, compile_fn, *, max_compiles=64):
    if (not isinstance(fit, dict) or fit.get("schema") != FIT_SCHEMA or fit.get("ok") is not True
            or fit.get("freeze_sha256") != digest({k: v for k, v in fit.items() if k != "freeze_sha256"})):
        raise ValueError("invalid frozen training receipt")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("invalid transfer manifest")
    ids, families, sources = set(), set(), set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("split") not in {"validation", "canary", "holdout"}
                or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids
                or not isinstance(row.get("source"), str) or len(row["source"].encode()) > 65_536
                or not isinstance(row.get("family"), str) or not row["family"]):
            raise ValueError("invalid or repeated evaluation row")
        if row["family"] in fit["training_families"] or row["source"] in sources:
            raise ValueError("training/evaluation family overlap")
        ids.add(row["id"]); sources.add(row["source"]); families.add(row["family"])
    if {r["split"] for r in rows} != {"validation", "canary", "holdout"}:
        raise ValueError("all transfer splits required")
    for family in families:
        if len({r["split"] for r in rows if r["family"] == family}) != 1:
            raise ValueError("family crosses evaluation splits")
    names = list(dict.fromkeys([fit["selected"], "last_online_0.15", "fixed_graph", "frozen_multiscale", "node_bag"]))
    models = {name: (StructuralEditPolicy if name == "fixed_graph" else GraphEditPolicy).from_dict(fit["checkpoints"][name])
              for name in names}
    compiler = CompilerBudget(compile_fn, max_compiles)
    environment = fit["environment_sha256"]
    codec_sha = hashlib.sha256(CODEC.read_bytes()).hexdigest()
    toolchain = models[fit["selected"]].toolchain
    seen_shapes = {k: {s[k] for s in fit["training_shapes"]} for k in ("proof", "type")}
    output = []
    def check(source, target):
        try:
            declaration = _envelope(source, target)
            reports, wires = [], []
            for text in (source, target):
                report, wire = _checked_export(compiler(text), text, declaration, environment, codec_sha, 4096)
                reports.append(report); wires.append(wire)
            a, b = reports
            same = (all((w["lean_version"], w["lean_githash"]) == toolchain for w in wires)
                    and a["type"] == b["type"] and a["export"]["level_parameters"] == b["export"]["level_parameters"]
                    and set(b["export"]["axioms"]) <= set(a["export"]["axioms"]))
            nonregression = same and all(b["proof"][k] <= a["proof"][k] for k in ("unique_expression_nodes", "expanded_expression_nodes"))
            return {"verified": same, "expression_nonregression": nonregression,
                    "source_proof": a["proof"], "prediction_proof": b["proof"]}
        except (ValueError, TypeError, KeyError) as exc:
            return {"verified": False, "expression_nonregression": None, "reason": str(exc)[:240]}
    for row in rows:
        source = row["source"]
        receipt = compiler(source)
        ctx = graph_context(source, receipt, environment_sha256=environment)
        ctx_fixed = source_context(source, receipt, environment_sha256=environment)
        shape = shape_digest(ctx.wire(source, environment, toolchain))
        if any(shape[k] in seen_shapes[k] for k in seen_shapes):
            raise ValueError("renamed or structural type/proof overlap")
        for k in seen_shapes:
            seen_shapes[k].add(shape[k])
        predictions = {name: model.predict(source, ctx_fixed if name == "fixed_graph" else ctx) for name, model in models.items()}
        target = row["target"]  # All arms have committed their raw predictions.
        if not isinstance(target, str) or len(target.encode()) > 65_536:
            raise ValueError("invalid transfer target")
        teacher_check = check(source, target)
        for name, prediction in predictions.items():
            checked = check(source, prediction["source"])
            a, b = proof_source_tokens(source), proof_source_tokens(prediction["source"])
            loss = None
            if teacher_check["expression_nonregression"] is True:
                try:
                    value = models[name].objective(source, target, ctx_fixed if name == "fixed_graph" else ctx)
                    if value is not None:
                        loss = metrics({k: v for k, v in value.items() if k != "gradient"})
                except ValueError:
                    pass
            output.append({"id": row["id"], "split": row["split"], "family": row["family"], "shape": shape,
                           "arm": name, "prediction": prediction, "check": checked, "teacher_check": teacher_check,
                           "loss": loss, "source_tokens": a, "prediction_tokens": b,
                           "verified_saved_tokens": a-b if checked["expression_nonregression"] is True and b < a else 0})
    unchanged = all(model.to_dict() == fit["checkpoints"][name] for name, model in models.items())
    if not unchanged:
        raise ValueError("evaluation modified a frozen model")
    def summarize(group):
        losses = [r["loss"] for r in group if r["loss"] is not None]
        return {"sample_count": len(group), "loss_sample_count": len(losses),
                "valid_count": sum(r["check"]["verified"] for r in group),
                "nonregressing_count": sum(r["check"]["expression_nonregression"] is True for r in group),
                "verified_saved_tokens": sum(r["verified_saved_tokens"] for r in group),
                **{key: sum(loss[key] for loss in losses)/len(losses) if losses else None
                   for key in ("cross_entropy", "expected_cosine_loss")}}
    summary = {name: summarize([r for r in output if r["arm"] == name]) for name in names}
    by_split = {split: {name: summarize([r for r in output if r["arm"] == name and r["split"] == split])
                       for name in names} for split in ("validation", "canary", "holdout")}
    gates = acceptance_gates(summary[fit["selected"]], summary["fixed_graph"])
    split_gates = {split: acceptance_gates(stats[fit["selected"]], stats["fixed_graph"]) for split, stats in by_split.items()}
    gates["all_splits_pass"] = all(all(g.values()) for g in split_gates.values())
    result = {"schema": EVAL_SCHEMA, "ok": all(gates.values()), "gates": gates,
              "freeze_sha256": fit["freeze_sha256"], "selected": fit["selected"], "rows": rows,
              "results": output, "summary": summary, "by_split": by_split, "split_gates": split_gates,
              "compile_attempts": compiler.attempts,
              "models_unchanged": unchanged, "family_labels_disjoint": True, "source_type_shapes_disjoint": True,
              "semantic_family_decontamination": False, "scope": "new_goal_layouts_training_mined_edit_grammar",
              "tokenizer_id": TOKENIZER_ID, "checkpoint_promoted": False, "official_score": None}
    result["receipt_sha256"] = digest(result)
    return result


def render_summary(fit, evaluation):
    if (fit.get("freeze_sha256") != digest({k: v for k, v in fit.items() if k != "freeze_sha256"})
            or evaluation.get("receipt_sha256") != digest({k: v for k, v in evaluation.items() if k != "receipt_sha256"})
            or evaluation.get("freeze_sha256") != fit.get("freeze_sha256")):
        raise ValueError("mismatched refinement receipts")
    lines = ["# Training-only graph refinement and frozen transfer", "",
             "Generated from receipts, not fresh verification or an arena result.", "",
             f"Selected solely on training data: `{fit['selected']}`. Epochs: {fit['epochs']}.",
             "Same examples/pass; batch averages before clipping and has fewer optimizer updates than online.", "",
             "| Transfer arm | Valid / total | Verified saved tokens | Edit CE | Expected cosine loss |",
             "| --- | --- | --- | --- | --- |"]
    for name, data in evaluation["summary"].items():
        fmt = lambda v: "unmeasured" if v is None else f"{v:.6g}"
        lines.append(f"| {name} | {data['valid_count']}/{data['sample_count']} | {data['verified_saved_tokens']} | "
                     f"{fmt(data['cross_entropy'])} | {fmt(data['expected_cosine_loss'])} |")
    lines += ["", "| Split | Selected / fixed saved tokens | Selected / fixed CE | Selected / fixed cosine loss |",
              "| --- | --- | --- | --- |"]
    for split, arms in evaluation["by_split"].items():
        selected, fixed = arms[fit["selected"]], arms["fixed_graph"]
        lines.append(f"| {split} | {selected['verified_saved_tokens']} / {fixed['verified_saved_tokens']} | "
                     f"{fmt(selected['cross_entropy'])} / {fmt(fixed['cross_entropy'])} | "
                     f"{fmt(selected['expected_cosine_loss'])} / {fmt(fixed['expected_cosine_loss'])} |")
    lines += ["", f"Gates: `{json.dumps(evaluation['gates'], sort_keys=True)}`.",
              "Fresh goal layouts with disjoint family labels and name-insensitive type/proof hashes; shared training rewrite motifs.",
              "Not mathematical-family decontamination. No eval tuning, repaired predictions, or checkpoint promotion.", ""]
    return "\n".join(lines)


def main(argv=None):
    from .router_tuning import _lean_compiler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--transfer-seed", type=int, default=20260923)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("choose a new output directory")
    torch.set_num_threads(1)
    compiler = _lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake, timeout=45,
                              kernel_only=True, export_dags=True, environment_sha256=args.environment_sha256)
    fit = fit_training(compiler, environment_sha256=args.environment_sha256, epochs=args.epochs, seed=args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "training.json").open("x") as stream:
        json.dump(fit, stream, sort_keys=True, indent=2, allow_nan=False)
    if not fit["ok"]:
        print(json.dumps({"ok": False, "reason": fit["reason"], "output_dir": str(args.output_dir)}))
        return 1
    # Persist selection/checkpoints BEFORE even generating evaluation cases.
    evaluation = evaluate_frozen(fit, transfer_rows(args.transfer_seed), compiler)
    with (args.output_dir / "evaluation.json").open("x") as stream:
        json.dump(evaluation, stream, sort_keys=True, indent=2, allow_nan=False)
    with (args.output_dir / "summary.md").open("x") as stream:
        stream.write(render_summary(fit, evaluation))
    print(json.dumps({"ok": evaluation["ok"], "selected": fit["selected"], "output_dir": str(args.output_dir)}))
    return 0 if evaluation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
