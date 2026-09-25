"""Isolated graph-learning control experiment; no arena promotion or LLM calls.

Matched source rows, train-only edit grammar, update count and learning-rate
schedule. Neural capacity differs from sparse capacity and is reported. Default
evaluation rows are renamed controls, NOT independent structural-family holdouts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from .autoencoder_training import AutoencoderConfig, learning_rate_for_step
from .expr_dag import CODEC
from .graph_policy import GraphEditPolicy, graph_context, metrics
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .rewrite_distillation import _validate_rows
from .rewrite_policy import body_of, mine_template
from .solver_feedback import source_digest
from .structural_ablation import control_rows
from .structural_policy import StructuralEditPolicy, digest, source_context
from .structural_training import _checked_export, _envelope, collect_structural_pairs

SCHEMA = "jevops-trained-graph-experiment/v1"


def run_experiment(compile_fn, *, environment_sha256, rows=None, epochs=80, seed=17, max_compiles=64):
    if type(epochs) is not int or not 1 <= epochs <= 200 or type(max_compiles) is not int or not 1 <= max_compiles <= 256:
        raise ValueError("invalid graph experiment budget")
    rows = list(control_rows() if rows is None else rows)
    _validate_rows(rows)
    if len(rows) > 32 or {r["split"] for r in rows} != {"train", "validation", "canary", "holdout"}:
        raise ValueError("bounded train/validation/canary/holdout splits required")
    for row in rows:
        if not isinstance(row["source"], str) or len(row["source"].encode()) > 65_536:
            raise ValueError("invalid source budget")
    cache, attempts, events, contexts = {}, [], [], {}
    def compile_one(source):
        if source not in cache:
            if len(attempts) >= max_compiles:
                raise ValueError("compile budget exhausted")
            started = time.monotonic()
            try:
                receipt = compile_fn(source)
            except Exception as exc:
                receipt = {"theorem_ok": False, "reason": type(exc).__name__}
            cache[source] = receipt
            attempts.append({"source": source, "source_sha256": source_digest(source), "receipt": receipt,
                             "wall_seconds": time.monotonic()-started})
        return cache[source]

    train = [r for r in rows if r["split"] == "train"]
    pairs = collect_structural_pairs([{k: v for k, v in r.items() if k != "target"} for r in rows],
                                     {r["id"]: r["target"] for r in train}, compile_fn=compile_one,
                                     environment_sha256=environment_sha256)
    if not pairs["ok"]:
        return {"schema": SCHEMA, "ok": False, "reason": "structural_teacher_gate", "training_pairs": pairs,
                "compile_attempts": attempts, "checkpoint_promoted": False}
    bank = {}
    for pair in pairs["pairs"]:
        template = mine_template(pair["text"], body_of(pair["target_text"])[1])
        if template is None:
            raise ValueError("unsupported one-step teacher")
        bank[template["id"]] = template
    templates = [bank[k] for k in sorted(bank)]
    def context(source, neural=False):
        key = (source, neural)
        if key not in contexts:
            factory = graph_context if neural else source_context
            contexts[key] = factory(source, compile_one(source), environment_sha256=environment_sha256)
        return contexts[key]
    toolchain = context(train[0]["source"]).toolchain
    config = dict(environment_sha256=environment_sha256, toolchain=toolchain)
    models = {"lexical": StructuralEditPolicy(templates, structural=False, **config),
              "fixed_graph": StructuralEditPolicy(templates, structural=True, **config),
              "learned_graph": GraphEditPolicy(templates, seed=seed, **config),
              "frozen_encoder": GraphEditPolicy(templates, seed=seed, freeze_encoder=True, **config),
              "node_bag": GraphEditPolicy(templates, seed=seed, rounds=0, **config)}
    def ctx(model, source):
        return context(source, isinstance(model, GraphEditPolicy))
    def objective(model, source, target):
        loss = model.objective(source, target, ctx(model, source))
        if loss is None:
            raise ValueError("unreachable one-step teacher")
        return metrics({k: v for k, v in loss.items() if k != "gradient"})
    initial = {name: model.to_dict() for name, model in models.items()}
    before = {name: [objective(model, r["source"], r["target"]) for r in train] for name, model in models.items()}
    events.append({"event": "grammar_frozen", "train_ids": [r["id"] for r in train], "grammar_sha256": digest(templates)})
    cfg = AutoencoderConfig(learning_rate=.15, warmup_steps=0, decay_steps=1000)
    history = []
    events.append({"event": "training", "epochs": epochs})
    for epoch in range(epochs):
        for row in train:
            for model in models.values():
                model.train_step(row["source"], row["target"], ctx(model, row["source"]), split="train",
                                 learning_rate=learning_rate_for_step(cfg, model.steps))
        if epoch in {0, epochs//2, epochs-1}:
            history.append({"epoch": epoch+1, "losses": {
                name: [objective(model, r["source"], r["target"]) for r in train] for name, model in models.items()}})
    checkpoints = {name: model.to_dict() for name, model in models.items()}
    events.append({"event": "checkpoint_frozen", "sha256": digest(checkpoints)})
    codec_sha = hashlib.sha256(CODEC.read_bytes()).hexdigest()

    def assess(source, candidate):
        try:
            declaration = _envelope(source, candidate)
            a, _ = _checked_export(compile_one(source), source, declaration, environment_sha256, codec_sha, 4096)
            b, wire = _checked_export(compile_one(candidate), candidate, declaration, environment_sha256, codec_sha, 4096)
            same = ((wire["lean_version"], wire["lean_githash"]) == toolchain
                    and a["type"] == b["type"] and a["export"]["level_parameters"] == b["export"]["level_parameters"]
                    and set(b["export"]["axioms"]) <= set(a["export"]["axioms"]))
            nonregression = same and all(b["proof"][k] <= a["proof"][k]
                                         for k in ("unique_expression_nodes", "expanded_expression_nodes"))
            return {"verified": same, "expression_nonregression": nonregression,
                    "source_proof": a["proof"], "prediction_proof": b["proof"]}
        except (ValueError, TypeError, KeyError) as exc:
            return {"verified": False, "expression_nonregression": None, "reason": str(exc)[:240]}

    output = []
    for split in ("train", "validation", "canary", "holdout"):
        events.append({"event": "final_holdout" if split == "holdout" else "evaluation", "split": split})
        for row in (r for r in rows if r["split"] == split):
            source = row["source"]
            predictions = {name: model.predict(source, ctx(model, source)) for name, model in models.items()}
            predictions.update({name: models["learned_graph"].predict(source, context(source, True), ablation=name)
                                for name in ("drop_graph", "zero_weights")})
            # Labels become available only after committing all raw predictions.
            target = row["target"]
            if not isinstance(target, str) or len(target.encode()) > 65_536:
                raise ValueError("invalid evaluation target")
            teacher_check = assess(source, target)
            for arm, prediction in predictions.items():
                loss = None
                if arm in models and teacher_check["expression_nonregression"] is True:
                    try:
                        loss = objective(models[arm], source, target)
                    except ValueError:
                        pass  # Unsupported evaluation labels remain unmeasured.
                checked = assess(source, prediction["source"])
                a, b = proof_source_tokens(source), proof_source_tokens(prediction["source"])
                shortening = checked["verified"] and checked["expression_nonregression"] is True and b < a
                output.append({"id": row["id"], "split": split, "arm": arm, "prediction": prediction,
                               "check": checked, "teacher_check": teacher_check, "loss": loss,
                               "source_tokens": a, "prediction_tokens": b, "verified_shortening": shortening})
    assert checkpoints == {name: model.to_dict() for name, model in models.items()}, "evaluation changed weights"
    summaries = {}
    for split in ("train", "validation", "canary", "holdout"):
        summaries[split] = {}
        for arm in (*models, "drop_graph", "zero_weights"):
            group = [r for r in output if r["split"] == split and r["arm"] == arm]
            losses = [r["loss"] for r in group if r["loss"] is not None]
            summaries[split][arm] = {"sample_count": len(group), "loss_sample_count": len(losses),
                "valid_count": sum(r["check"]["verified"] for r in group),
                "nonregressing_count": sum(r["check"]["expression_nonregression"] is True for r in group),
                "verified_shortening_count": sum(r["verified_shortening"] for r in group),
                "verified_saved_tokens": sum(r["source_tokens"]-r["prediction_tokens"] for r in group if r["verified_shortening"]),
                "cross_entropy": sum(r["cross_entropy"] for r in losses)/len(losses) if losses else None,
                "expected_cosine_loss": sum(r["expected_cosine_loss"] for r in losses)/len(losses) if losses else None}
    gates = {split: all(summaries[split]["learned_graph"][key] == summaries[split]["learned_graph"]["sample_count"]
                       for key in ("valid_count", "nonregressing_count", "loss_sample_count")) for split in summaries}
    encoder_changed = any(v != initial["learned_graph"]["weights"][k]
                          for k, v in checkpoints["learned_graph"]["weights"].items() if k.startswith("encoder."))
    frozen_unchanged = all(v == initial["frozen_encoder"]["weights"][k]
                           for k, v in checkpoints["frozen_encoder"]["weights"].items() if k.startswith("encoder."))
    return {"schema": SCHEMA, "ok": all(gates.values()) and encoder_changed and frozen_unchanged,
            "scope": "bounded_control_experiment_not_arena_or_independent_family_holdout", "gates": gates,
            "epochs": epochs, "seed": seed, "manifest": rows, "manifest_sha256": digest(rows), "training_pairs": pairs,
            "initial_checkpoints_sha256": digest(initial), "before_training": before, "history": history,
            "checkpoints": checkpoints, "checkpoints_sha256": digest(checkpoints), "events": events,
            "results": output, "summary": summaries, "compile_attempts": attempts, "compile_calls": len(attempts),
            "tokenizer_id": TOKENIZER_ID, "torch_version": str(torch.__version__), "torch_threads": torch.get_num_threads(),
            "graph_encoder_changed": encoder_changed, "frozen_encoder_unchanged": frozen_unchanged,
            "neural_parameter_counts": {k: sum(p.numel() for p in m.parameters()) for k, m in models.items()
                                         if isinstance(m, GraphEditPolicy)},
            "reconstruction_heads_updated": False, "trained_lossless_autoencoder": False,
            "holdout_accessed_after_freeze": True, "tuning_allowed_after_holdout": False,
            "semantic_family_decontamination": False, "dependency_closure_verified": False,
            "jev_feedback_used": False, "nca_trained": False, "checkpoint_promoted": False,
            "arena_data_used": False, "official_score": None}


def render_summary(run):
    if (run.get("schema") != SCHEMA or run.get("checkpoints_sha256") != digest(run["checkpoints"])
            or run.get("manifest_sha256") != digest(run["manifest"])):
        raise ValueError("invalid graph experiment receipt")
    lines = ["# Trainable DAG edit-policy control experiment", "",
             "Generated from saved receipts, not fresh proof authority. Same-family renamed controls, not an arena score.", "",
             "| Holdout arm | Valid / total | Verified saved tokens | Edit CE | Expected cosine loss |",
             "| --- | --- | --- | --- | --- |"]
    for name, data in run["summary"]["holdout"].items():
        fmt = lambda v: "unmeasured" if v is None else f"{v:.6g}"
        lines.append(f"| {name} | {data['valid_count']}/{data['sample_count']} | {data['verified_saved_tokens']} | "
                     f"{fmt(data['cross_entropy'])} | {fmt(data['expected_cosine_loss'])} |")
    lines += ["", f"Epochs: {run['epochs']}; native compile calls (deduplicated within run): {run['compile_calls']}.",
              f"Encoder changed: {run['graph_encoder_changed']}; frozen control unchanged: {run['frozen_encoder_unchanged']}.",
              "Cosine measures tactic-operation bags, not proof equivalence. All arms use the same train-only copy grammar.",
              "Neural/sparse parameter counts differ. Drop-graph/zero-weight arms are diagnostics, not trained baselines.",
              "The decoder is lexical, not type-safe by construction; raw outputs are checked without repair.",
              "No lossless neural reconstruction, novel-family generalization, JeV/NCA training, or arena promotion claim.", ""]
    return "\n".join(lines)


def main(argv=None):
    from .router_tuning import _lean_compiler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists() or not 1 <= args.threads <= 32:
        parser.error("choose a new output directory and 1..32 CPU threads")
    torch.set_num_threads(args.threads)
    result = run_experiment(_lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake,
                                          kernel_only=True, export_dags=True,
                                          environment_sha256=args.environment_sha256, timeout=45),
                            environment_sha256=args.environment_sha256, epochs=args.epochs, seed=args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "run.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
    if "checkpoints" in result:
        with (args.output_dir / "summary.md").open("x") as stream:
            stream.write(render_summary(result))
    print(json.dumps({"ok": result["ok"], "output_dir": str(args.output_dir), "reason": result.get("reason")}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
