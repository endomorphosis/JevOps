"""Frozen scoped-training transfer controls with a matched one-choice baseline.

No training, template mining, proposal repair or checkpoint promotion. All arms
commit their outputs before evaluation labels are read. Native compiler callbacks
remain trusted; hashes bind receipts, not transitive dependency authenticity.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import textwrap

import torch

from .graph_composition import CheckedCompiler
from .graph_policy import GraphEditPolicy, candidate_loss, metrics
from .graph_refinement import FIT_SCHEMA, acceptance_gates, shape_digest
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .rewrite_policy import body_of, choices
from .structural_policy import StructuralEditPolicy, digest
from .structural_training import _envelope

SCHEMA = "jevops-scoped-frozen-evaluation/v1"
ARMS = ("learned", "fixed_graph", "token_length")
SPLITS = ("validation", "canary", "holdout")
PROTOCOL = {"grammar": "identical_training_mined_templates", "max_edits": 1,
            "raw_candidate_checks_per_arm_per_source": 1, "alternate_candidate_search": False,
            "symbolic_logits": "negative_proof_source_tokens", "symbolic_temperature": 1.0,
            "loss_label_smoothing": .02, "loss_scope": "edit_choice_CE_and_expected_IR_operation_cosine",
            "source_length_growth_rejected": True,
            "source_checks": "shared_fresh_native_DAG", "reference_checks": "separate_not_inference",
            "compiler_cache": "per_run_identical_source_deduplication",
            "compute_matched": False, "verification_budget_matched": True}


def transfer_rows(seed=20260923):
    """Seeded identifiers, deliberately different layouts, shared rewrite motifs.

    Hand-designed transfer controls, not semantically independent math families.
    Call after checkpoint freeze. Repeated runs are inspected regression probes.
    """
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("invalid transfer seed")
    specs = [
        ("validation", "introduced_copy", "(p q : Prop) (hq : q) : p → p",
         "intro h\nhave a := h\nhave b := a\nexact b", "intro h\nexact h"),
        ("validation", "higher_order_application", "(p q : Prop) (f : (p → p) → q) (g : p → p) : q",
         "apply f\nexact g", "exact f g"),
        ("canary", "polymorphic_dependent", "(α : Type) (p : α → Prop) (x : α) (f : ∀ y, p y) : p x",
         "have a := f x\nhave b := a\nexact b", "exact f x"),
        ("canary", "introduced_implicit", "(p : Bool → Prop) (f : ∀ {n}, p n) : ∀ n, p n",
         "intro n\nhave a : p n := f\nhave b := a\nexact b", "intro n\nexact @f n"),
        ("holdout", "prefixed_dependent", "(p : Nat → Prop) (n : Nat) (f : ∀ x, p x) : Bool → p n",
         "intro flag\nhave a := f n\nhave b := a\nexact b", "intro flag\nexact f n"),
        ("holdout", "preserve_transitivity", "(a b c : Nat) (h : a = b) (k : b = c) : a = c",
         "exact Eq.trans h k", "exact Eq.trans h k"),
    ]
    out = []
    # Rename identifiers together in the header/body/reference, not only theorem names.
    from .rewrite_policy import IDENT
    for split, family, header, before, after in specs:
        nonce = random.Random(f"{seed}:{split}:{family}").randrange(10**8)
        rename = {n: f"{n}_{nonce}" for n in "p q h hq f g n a b c x y flag k α".split()}
        render = lambda s: IDENT.sub(lambda m: rename.get(m[0], m[0]), s)
        prefix = f"theorem scoped_eval_{family}_{nonce} {render(header)} := by\n"
        out.append({"id": f"{family}_{nonce}", "family": family, "split": split,
                    "source": prefix + textwrap.indent(render(before), "  ") + "\n",
                    "target": prefix + textwrap.indent(render(after), "  ") + "\n"})
    return out


def frozen_models(fit):
    """Verify selection/grammar binding before any evaluation content access."""
    if (not isinstance(fit, dict) or fit.get("schema") != FIT_SCHEMA or fit.get("ok") is not True
            or fit.get("evaluation_accessed") is not False
            or fit.get("freeze_sha256") != digest({k: v for k, v in fit.items() if k != "freeze_sha256"})):
        raise ValueError("invalid frozen training receipt")
    models = {"learned": GraphEditPolicy.from_dict(fit["checkpoints"][fit["selected"]]),
              "fixed_graph": StructuralEditPolicy.from_dict(fit["checkpoints"]["fixed_graph"])}
    a, b = models.values()
    if (a.templates != b.templates or a.environment != b.environment or a.toolchain != b.toolchain
            or a.environment != fit["environment_sha256"]):
        raise ValueError("unmatched grammar, environment or toolchain")
    return models


def _render(source, body):
    return body_of(source)[0] + "\n" + textwrap.indent(body, "  ") + "\n"


def length_proposal(source, rows):
    """Single shortest syntactic choice; identity wins ties. No compiler calls."""
    candidates = [source if i == 0 else _render(source, row["body"]) for i, row in enumerate(rows)]
    logits = torch.tensor([-proof_source_tokens(s) for s in candidates], dtype=torch.float64)
    index = int(logits.argmax())
    return {"source": candidates[index], "choice": index, "choice_count": len(rows),
            "teacher_used": False, "solver_used": False, "probability": float(logits.softmax(0)[index])}, logits


def _manifest(fit, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("invalid evaluation manifest size")
    ids, families, texts = set(), {}, set()
    train_ids = {r["id"] for r in fit["training_rows"]}
    train_texts = {" ".join(r[k].split()) for r in fit["training_rows"] for k in ("source", "target")}
    for row in rows:
        if (not isinstance(row, dict) or row.get("split") not in SPLITS
                or any(not isinstance(row.get(k), str) or not 1 <= len(row[k]) <= 256 for k in ("id", "family"))
                or row["id"] in ids | train_ids or row["family"] in fit["training_families"]
                or not isinstance(row.get("source"), str) or not 1 <= len(row["source"].encode()) <= 65_536):
            raise ValueError("invalid/overlapping evaluation identity or family")
        key = " ".join(row["source"].split())
        if key in texts | train_texts:
            raise ValueError("duplicate training/evaluation source")
        if row["family"] in families and families[row["family"]] != row["split"]:
            raise ValueError("family crosses evaluation splits")
        ids.add(row["id"]); texts.add(key); families[row["family"]] = row["split"]
    if {r["split"] for r in rows} != set(SPLITS):
        raise ValueError("all three evaluation splits required")


def _failure(reason):
    return {"verified": False, "expression_nonregression": False, "strict_shortening": False, "reason": reason}


def _summarize(rows):
    losses = [r["loss"] for r in rows if r["loss"] is not None]
    return {"sample_count": len(rows), "loss_sample_count": len(losses),
            "valid_count": sum(r["check"]["verified"] is True for r in rows),
            "nonregressing_count": sum(r["check"]["expression_nonregression"] is True for r in rows),
            "length_nonregressing_count": sum(r["prediction_tokens"] is not None
                                               and r["prediction_tokens"] <= r["source_tokens"] for r in rows),
            "verified_saved_tokens": sum(r["verified_saved_tokens"] for r in rows),
            "source_tokens": sum(r["source_tokens"] for r in rows),
            "raw_prediction_tokens": (sum(r["prediction_tokens"] for r in rows)
                                      if all(r["prediction_tokens"] is not None for r in rows) else None),
            **{k: sum(r[k] for r in losses)/len(losses) if losses else None
               for k in ("cross_entropy", "expected_cosine_loss")}}


def evaluate_frozen(fit, rows, compile_fn, *, max_compiles=None):
    models = frozen_models(fit)
    _manifest(fit, rows)
    required = (len(ARMS) + 2) * len(rows)  # Original, one candidate/arm, separate reference.
    if max_compiles is None:
        max_compiles = required
    if type(max_compiles) is not int or not required <= max_compiles <= 256:
        raise ValueError("compile budget must cover every arm and reference without order bias")
    a = models["learned"]
    checker = CheckedCompiler(compile_fn, environment_sha256=a.environment, toolchain=a.toolchain,
                              max_compiles=max_compiles)
    snapshots = {k: digest(m.to_dict()) for k, m in models.items()}
    fit_sha = digest(fit)
    seen = {k: {s[k] for s in fit["training_shapes"]} for k in ("proof", "type")}
    for wire in fit["training_pairs"]["graphs"].values():
        for k, v in shape_digest(wire).items():
            seen[k].add(v)  # Include admitted target shapes, not just training sources.
    prepared = []
    for row in rows:
        source = row["source"]
        entry = {"row": row, "shape": None, "predictions": {}, "contexts": {}, "error": None}
        prepared.append(entry)
        try:
            state = checker.state(source)
            shape = shape_digest(state["wire"])
        except (ValueError, TypeError, KeyError) as exc:
            entry["error"] = str(exc)[:240]
            continue  # Keep this row in every denominator, with missing losses.
        if any(shape[k] in seen[k] for k in seen):
            raise ValueError("renamed or structural training/evaluation type/proof overlap")
        for k in seen:
            seen[k].add(shape[k])
        entry["shape"] = shape
        grammar = entry["grammar"] = choices(source, a.templates)
        for arm, model in models.items():
            try:
                ctx = entry["contexts"][arm] = checker.context(model, source)
                entry["predictions"][arm] = model.predict(source, ctx)
            except (ValueError, TypeError, KeyError) as exc:
                entry["predictions"][arm] = {"error": str(exc)[:240]}
        entry["predictions"]["token_length"], entry["length_logits"] = length_proposal(source, grammar)
    # No target access occurred above: ALL arms on ALL rows are now committed.
    results = []
    for entry in prepared:
        row, source = entry["row"], entry["row"]["source"]
        try:
            target = row["target"]
        except KeyError:
            target = None
        try:
            if entry["error"]:
                raise ValueError(entry["error"])
            if not isinstance(target, str) or not 1 <= len(target.encode()) <= 65_536:
                raise ValueError("missing or invalid evaluation reference")
            teacher_check = checker.edge(source, target)
            if proof_source_tokens(target) > proof_source_tokens(source):
                raise ValueError("reference length regression")
        except (ValueError, TypeError, KeyError) as exc:
            teacher_check = _failure(str(exc)[:240])
        for arm in ARMS:
            prediction = entry["predictions"].get(arm, {"error": entry["error"]})
            raw, loss, loss_error = prediction.get("source"), None, None
            try:
                if not isinstance(raw, str) or not 1 <= len(raw.encode()) <= 65_536:
                    raise ValueError(prediction.get("error", "invalid raw candidate"))
                _envelope(source, raw)
                index = prediction.get("choice")
                if (type(index) is not int or not 0 <= index < len(entry["grammar"])
                        or body_of(raw)[1] != entry["grammar"][index]["body"]):
                    raise ValueError("prediction outside frozen grammar")
                checked = checker.edge(source, raw)
            except (ValueError, TypeError, KeyError) as exc:
                checked = _failure(str(exc)[:240])
            if teacher_check["expression_nonregression"] is True:
                try:
                    objective = (candidate_loss(entry["length_logits"], entry["grammar"], body_of(target)[1])
                                 if arm == "token_length" else models[arm].objective(source, target, entry["contexts"][arm]))
                    if objective is None:
                        raise ValueError("unreachable one-step reference")
                    loss = metrics({k: v for k, v in objective.items() if k != "gradient"})
                    if not all(math.isfinite(loss[k]) for k in ("total", "cross_entropy", "expected_cosine_loss")):
                        raise ValueError("nonfinite loss")
                except (ValueError, TypeError, KeyError) as exc:
                    loss, loss_error = None, str(exc)[:240]
            source_tokens = proof_source_tokens(source)
            raw_tokens = proof_source_tokens(raw) if isinstance(raw, str) else None
            saved = (source_tokens - raw_tokens if checked["expression_nonregression"] is True
                     and raw_tokens < source_tokens else 0)
            results.append({"id": row["id"], "split": row["split"], "family": row["family"], "arm": arm,
                "shape": entry["shape"], "prediction": prediction, "check": checked, "teacher_check": teacher_check,
                "source_tokens": source_tokens, "prediction_tokens": raw_tokens, "verified_saved_tokens": saved,
                "loss": loss, "loss_error": loss_error})
    if digest(fit) != fit_sha or any(digest(m.to_dict()) != snapshots[k] for k, m in models.items()):
        raise ValueError("evaluation mutated frozen training/model state")
    summary = {arm: _summarize([r for r in results if r["arm"] == arm]) for arm in ARMS}
    by_split = {split: {arm: _summarize([r for r in results if r["arm"] == arm and r["split"] == split])
                       for arm in ARMS} for split in SPLITS}
    comparisons = {base: acceptance_gates(summary["learned"], summary[base]) for base in ARMS[1:]}
    split_gates = {split: {base: acceptance_gates(stats["learned"], stats[base]) for base in ARMS[1:]}
                   for split, stats in by_split.items()}
    gates = {"all_arms_complete_validity_cost_and_loss": all(
        s["sample_count"] == s["valid_count"] == s["nonregressing_count"] == s["loss_sample_count"] for s in summary.values()),
        "all_arms_source_length_nonregression": all(s["length_nonregressing_count"] == s["sample_count"] for s in summary.values()),
        "all_comparisons_pass": all(all(g.values()) for g in comparisons.values()),
        "all_splits_pass": all(all(g.values()) for arms in split_gates.values() for g in arms.values())}
    result = {"schema": SCHEMA, "ok": all(gates.values()), "freeze_sha256": fit["freeze_sha256"],
              "selected": fit["selected"], "protocol": dict(PROTOCOL), "rows": rows, "manifest_sha256": digest(rows),
              "results": results, "summary": summary, "by_split": by_split, "gates": gates,
              "comparisons": comparisons, "split_gates": split_gates, "model_sha256": snapshots,
              "models_unchanged": True, "compile_attempts": checker.compiler.attempts,
              "source_shape_coverage": sum(e["shape"] is not None for e in prepared),
              "source_type_shapes_disjoint": all(e["shape"] is not None for e in prepared),
              "scope": "hand_designed_layout_transfer_shared_rewrite_motifs",
              "semantic_family_decontamination": False, "tokenizer_id": TOKENIZER_ID,
              "checkpoint_promoted": False, "official_score": None}
    result["receipt_sha256"] = digest(result)
    return result


def measurement(fit, evaluation):
    frozen_models(fit)
    if (evaluation.get("schema") != SCHEMA or evaluation.get("freeze_sha256") != fit["freeze_sha256"]
            or evaluation.get("receipt_sha256") != digest({k: v for k, v in evaluation.items() if k != "receipt_sha256"})):
        raise ValueError("mismatched evaluation receipts")
    return {k: evaluation[k] for k in ("schema", "ok", "freeze_sha256", "receipt_sha256", "manifest_sha256", "selected",
        "scope", "protocol", "summary", "by_split", "gates", "comparisons", "split_gates", "models_unchanged",
        "source_type_shapes_disjoint", "semantic_family_decontamination", "checkpoint_promoted", "official_score")} | {
            "native_compile_calls": len(evaluation["compile_attempts"])}


def write_reports(fit, evaluation, output_dir, *, include_evidence=True):
    """Derive reports in code; never print receipts or overwrite existing files."""
    record = measurement(fit, evaluation)
    fmt = lambda v: "unmeasured" if v is None else f"{v:.8g}"
    lines = ["# Frozen scoped-training transfer control", "",
        f"Outcome: {'passed' if evaluation['ok'] else 'failed'}; checkpoint unchanged; no promotion.", "",
        "Same frozen grammar and one raw candidate check per arm/source; not wall-time or training-compute matched.",
        "Token-length logits = negative source tokens, temperature 1; loss smoothing 0.02 fixed before evaluation.", "",
        "| Arm | Valid / cases | Cost-safe | Loss coverage | Verified saved tokens | Edit CE | Expected cosine loss |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for arm in ARMS:
        s = record["summary"][arm]
        lines.append(f"| {arm} | {s['valid_count']}/{s['sample_count']} | {s['nonregressing_count']} | "
                     f"{s['loss_sample_count']} | {s['verified_saved_tokens']} | {fmt(s['cross_entropy'])} | {fmt(s['expected_cosine_loss'])} |")
    lines.extend(["", "Failed comparison gates:"])
    failures = [f"- {split}/{base}: {', '.join(k for k, v in gate.items() if not v)}"
                for split, arms in {"aggregate": record["comparisons"], **record["split_gates"]}.items()
                for base, gate in arms.items() if not all(gate.values())]
    lines.extend(["", *(failures or ["None."]), "",
        "Failed global gates: " + (", ".join(k for k, v in record["gates"].items() if not v) or "none") + ".", "",
        f"Native compiler calls (deduplicated): {record['native_compile_calls']}.",
        "All raw predictions were committed before labels. Missing/invalid/unreachable labels fail coverage, not identity labels.",
        "Named validation/canary/holdout partitions are shared-motif transfer controls, not decontaminated mathematical families.",
        "CE/cosine are edit-policy diagnostics, not reconstruction loss or semantic equivalence.",
        "No training, repair, reference retuning, checkpoint promotion or arena score.", ""])
    artifacts = {"measurement.json": json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n",
                 "summary.md": "\n".join(lines)}
    if include_evidence:
        artifacts["evaluation.json"] = json.dumps(evaluation, sort_keys=True, indent=2, allow_nan=False) + "\n"
    output_dir = Path(output_dir)
    for filename in artifacts:
        path = output_dir / filename
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"report exists: {path}")
    if output_dir.is_symlink():
        raise ValueError("report directory cannot be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, contents in artifacts.items():
        with (output_dir / filename).open("x", encoding="utf-8") as stream:
            stream.write(contents)
    return {"ok": evaluation["ok"], "output_dir": str(output_dir), "checkpoint_promoted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--report-from", type=Path, help="regenerate only compact reports from an existing evaluation.json; no Lean calls")
    args = parser.parse_args(argv)
    if args.output_dir.exists() or args.output_dir.is_symlink():
        parser.error("choose a new output directory")
    training = json.loads((args.training_dir / "experiment.json").read_text())
    training_record = json.loads((args.training_dir / "measurement.json").read_text())
    if training_record["experiment_sha256"] != digest(training):
        parser.error("training artifact hash mismatch")
    fit = training["fit"]
    frozen_models(fit)
    if fit["environment_sha256"] != args.environment_sha256:
        parser.error("training/evaluation environment mismatch")
    if args.report_from is not None:
        evaluation = json.loads(args.report_from.read_text())
        print(json.dumps(write_reports(fit, evaluation, args.output_dir, include_evidence=False), sort_keys=True))
        return 0  # Rendering success is distinct from a passing evaluation.
    rows = transfer_rows(args.seed)  # Only after binding the frozen fit.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "protocol.json").open("x") as stream:
        json.dump({"freeze_sha256": fit["freeze_sha256"], "training_sha256": digest(training),
                   "manifest_sha256": digest(rows), "rows": rows, "protocol": PROTOCOL, "seed": args.seed},
                  stream, sort_keys=True, indent=2, allow_nan=False)
    from .router_tuning import _lean_compiler
    torch.set_num_threads(1)
    compiler = _lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake, kernel_only=True,
                              export_dags=True, environment_sha256=args.environment_sha256)
    try:
        evaluation = evaluate_frozen(fit, rows, compiler)
    except (ValueError, TypeError, KeyError) as exc:
        failure = {"ok": False, "reason": str(exc)[:240], "checkpoint_promoted": False}
        with (args.output_dir / "failure.json").open("x") as stream:
            json.dump(failure, stream, sort_keys=True, indent=2)
        print(json.dumps({**failure, "output_dir": str(args.output_dir)}))
        return 1
    print(json.dumps(write_reports(fit, evaluation, args.output_dir), sort_keys=True))
    return 0 if evaluation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
