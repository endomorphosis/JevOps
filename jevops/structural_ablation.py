"""Bounded, matched lexical versus source-DAG edit-head experiment.

This is an isolated research runner, not the outer router or an arena scorer.
The fixed graph encoder is lossy; only its sparse readout is learned. All raw
predictions are independently checked and failures are never repaired/replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import time

from . import autoencoder as ae
from .autoencoder_training import (AutoencoderConfig, LeanIRAutoencoder, canary_gate,
                                   coerce_training_example, learning_rate_for_step)
from .expr_dag import CODEC
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .rewrite_distillation import _validate_rows
from .solver_feedback import source_digest
from .structural_policy import FEATURE_SCHEMA, StructuralEditPolicy, digest, source_context
from .structural_training import _checked_export, _envelope, collect_structural_pairs

SCHEMA = "jevops-structural-edit-ablation/v1"


def control_rows(seed: int = 20260922):
    """Same applicable lexical edit; rfl works only for the reflexive goal.

    Identity controls are not claims of optimality; other shortening tactics
    exist. Splits rename this same family, not unseen mathematics.
    """
    out = []
    for split in ("train", "validation", "canary", "holdout"):
        rng = random.Random(17 if split == "train" else f"{seed}:{split}")
        for reflexive in (True, False):
            n = rng.randrange(10**8)
            x, y, h, a, b, c = [f"{v}_{n}" for v in ("x", "y", "h", "a", "b", "c")]
            goal = f"{x} = {x if reflexive else y}"
            name = f"graph_{split}_{n}"
            prefix = f"theorem {name} ({x} {y} : Nat) ({h} : {goal}) : {goal} := by\n"
            source = prefix + f"  have {a} := {h}\n  have {b} := {a}\n  have {c} := {b}\n  exact {c}\n"
            out.append({"id": name, "split": split, "family": "reflexivity_control", "source": source,
                        "target": prefix + "  rfl\n" if reflexive else source})
    return out


def run_ablation(compile_fn, *, environment_sha256: str, rows=None, epochs: int = 80, max_compiles: int = 64):
    if type(epochs) is not int or not 1 <= epochs <= 200 or type(max_compiles) is not int or not 1 <= max_compiles <= 256:
        raise ValueError("invalid structural experiment budget")
    rows = list(control_rows() if rows is None else rows)
    _validate_rows(rows)
    if len(rows) > 32 or {r["split"] for r in rows} != {"train", "validation", "canary", "holdout"}:
        raise ValueError("bounded train/validation/canary/holdout splits required")
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

    manifest = [{k: v for k, v in row.items() if k != "target"} for row in rows]
    training = [r for r in rows if r["split"] == "train"]
    development = [r for r in rows if r["split"] != "holdout"]
    pairs = collect_structural_pairs(manifest, {r["id"]: r["target"] for r in training},
                                     compile_fn=compile_one, environment_sha256=environment_sha256)
    if not pairs["ok"]:
        return {"schema": SCHEMA, "ok": False, "reason": "structural_teacher_gate", "training_pairs": pairs,
                "compile_attempts": attempts, "checkpoint_promoted": False}
    def context(source):
        if source not in contexts:
            contexts[source] = source_context(source, compile_one(source), environment_sha256=environment_sha256)
        return contexts[source]

    cfg = AutoencoderConfig(train_rewrite_policy=True, freeze_reconstruction_heads=True,
                            learning_rate=.15, warmup_steps=0, decay_steps=1000, rewrite_max_edits=1)
    autoencoder = LeanIRAutoencoder(config=cfg)
    examples = [coerce_training_example({"id": r["id"], "text": r["source"], "target_ir": ae.encode_lean_ir(r["target"])})
                for r in training]
    grammar = autoencoder.prepare_rewrite_training(examples)
    reconstruction = autoencoder.to_dict()
    toolchain = context(training[0]["source"]).toolchain
    models = {name: StructuralEditPolicy(autoencoder.state["rewrite_templates"], environment_sha256=environment_sha256,
                                         toolchain=toolchain, structural=structural)
              for name, structural in (("lexical", False), ("structural", True))}
    for row in training:
        for model in models.values():
            if model.objective(row["source"], row["target"], context(row["source"])) is None:
                raise ValueError("unreachable one-step training target")
    events.append({"event": "grammar_frozen", "train_ids": [r["id"] for r in training]})
    codec_sha = hashlib.sha256(CODEC.read_bytes()).hexdigest()

    def assess(source, candidate):
        try:
            declaration = _envelope(source, candidate)
            a, _ = _checked_export(compile_one(source), source, declaration, environment_sha256, codec_sha, 50_000)
            b, wire = _checked_export(compile_one(candidate), candidate, declaration, environment_sha256, codec_sha, 50_000)
            same = (tuple((wire["lean_version"], wire["lean_githash"])) == toolchain
                    and a["type"] == b["type"] and a["export"]["level_parameters"] == b["export"]["level_parameters"]
                    and set(b["export"]["axioms"]) <= set(a["export"]["axioms"]))
            nonregression = same and all(b["proof"][k] <= a["proof"][k]
                                         for k in ("unique_expression_nodes", "expanded_expression_nodes"))
            return {"verified": same, "expression_nonregression": nonregression,
                    "source_proof": a["proof"], "prediction_proof": b["proof"]}
        except (ValueError, TypeError, KeyError) as exc:
            return {"verified": False, "expression_nonregression": None, "reason": str(exc)[:240]}

    def evaluate(selected, *, ablations=False):
        snapshots = {k: m.to_dict() for k, m in models.items()}
        outputs = []
        for row in selected:
            source, ctx = row["source"], context(row["source"])
            ctx.validate(source, environment_sha256, toolchain)
            # Commit predictions using source-only context before reading target.
            predictions = {name: m.predict(source, ctx) for name, m in models.items()}
            if ablations:
                predictions.update({name: models["structural"].predict(source, ctx, ablation=name)
                                    for name in ("drop_graph", "zero_weights")})
            target = row["target"]
            if not isinstance(target, str) or len(target.encode()) > 65_536:
                raise ValueError("invalid or oversized evaluation target")
            teacher_check = assess(source, target)
            ex = coerce_training_example({"text": source, "target_ir": ae.encode_lean_ir(target)})
            operation_ce = autoencoder._sequence_loss(ex)  # Explicitly frozen diagnostic.
            for name, prediction in predictions.items():
                head = models.get(name, models["structural"])
                measured_head = StructuralEditPolicy.from_dict(head.to_dict())
                if name == "drop_graph":
                    measured_head.weights = {k: v for k, v in head.weights.items() if "|dag:" not in k}
                elif name == "zero_weights":
                    measured_head.weights = {}
                loss = measured_head.objective(source, target, ctx) if teacher_check["expression_nonregression"] is True else None
                checked = assess(source, prediction["source"])
                source_tokens, tokens = proof_source_tokens(source), proof_source_tokens(prediction["source"])
                outputs.append({"id": row["id"], "split": row["split"], "arm": name,
                                "prediction": prediction, "check": checked, "teacher_check": teacher_check,
                                "source_tokens": source_tokens, "prediction_tokens": tokens,
                                "verified_shortening": checked["verified"] and checked["expression_nonregression"] is True and tokens < source_tokens,
                                "operation_cross_entropy": operation_ce,
                                "loss": {k: v for k, v in loss.items() if k != "gradient"} if loss else None})
        assert snapshots == {k: m.to_dict() for k, m in models.items()}, "evaluation changed weights"
        result = {}
        for split in dict.fromkeys(r["split"] for r in selected):
            result[split] = {}
            for name in dict.fromkeys(r["arm"] for r in outputs):
                group = [r for r in outputs if r["split"] == split and r["arm"] == name]
                losses = [r["loss"] for r in group if r["loss"] is not None]
                result[split][name] = {"sample_count": len(group), "rewrite_sample_count": len(losses),
                    "cross_entropy": sum(r["operation_cross_entropy"] for r in group)/len(group),
                    "rewrite_cross_entropy": sum(r["cross_entropy"] for r in losses)/len(losses) if losses else None,
                    "rewrite_expected_cosine_loss": sum(r["expected_cosine_loss"] for r in losses)/len(losses) if losses else None,
                    "verifier_success_rate": sum(r["check"]["verified"] for r in group)/len(group),
                    "verifier_evaluated_count": len(group),
                    "nonregressing_count": sum(r["check"]["expression_nonregression"] is True for r in group),
                    "verified_shortening": sum(r["verified_shortening"] for r in group),
                    "verified_saved_tokens": sum(r["source_tokens"]-r["prediction_tokens"] for r in group if r["verified_shortening"]),
                    "rows": group}
        return result

    before = evaluate(development)
    history = []
    events.append({"event": "training", "epochs": epochs})
    for epoch in range(epochs):
        for row in training:
            for model in models.values():
                model.train_step(row["source"], row["target"], context(row["source"]), split="train",
                                 learning_rate=learning_rate_for_step(cfg, model.steps))
        if epoch in {0, epochs//2, epochs-1}:
            history.append({"epoch": epoch+1, "losses": {name: [
                {k: v for k, v in m.objective(r["source"], r["target"], context(r["source"])).items() if k != "gradient"}
                for r in training] for name, m in models.items()}})
    checkpoints = {name: m.to_dict() for name, m in models.items()}
    events.append({"event": "checkpoint_frozen", "sha256": digest(checkpoints)})
    after = evaluate(development, ablations=True)
    events.append({"event": "final_holdout"})
    holdout = evaluate([r for r in rows if r["split"] == "holdout"], ablations=True)
    assert checkpoints == {name: m.to_dict() for name, m in models.items()}
    assert reconstruction == autoencoder.to_dict()
    gates = {split: canary_gate(before[split]["structural"], after[split]["structural"])
             for split in ("validation", "canary")}
    final = holdout["holdout"]
    gates["holdout"] = canary_gate(final["zero_weights"], final["structural"])
    measured = all(g["rewrite_sample_count"] == g["sample_count"] and
                   g["nonregressing_count"] == g["sample_count"] for g in [
                       *(after[s]["structural"] for s in after), final["structural"]])
    return {"schema": SCHEMA, "ok": measured and all(g["accepted"] for g in gates.values()),
            "scope": "same_family_reflexivity_control_not_arena_or_unseen_mathematics", "feature_schema": FEATURE_SCHEMA,
            "epochs": epochs, "manifest": rows, "manifest_sha256": digest(rows), "grammar": grammar,
            "training_pairs": pairs, "before": before, "after": after, "holdout": holdout, "gates": gates,
            "checkpoints": checkpoints, "checkpoints_sha256": digest(checkpoints), "history": history,
            "config": cfg.to_dict(), "frozen_autoencoder": reconstruction,
            "reconstruction_heads_unchanged": True, "graph_encoder_trained": False, "graph_readout_trained": True,
            "contexts": {source_digest(s): c.receipt() for s, c in contexts.items()}, "compile_attempts": attempts,
            "compile_calls": len(attempts), "events": events, "holdout_accessed_after_freeze": True,
            "tuning_allowed_after_holdout": False, "tokenizer_id": TOKENIZER_ID,
            "structural_holdout_saved_tokens_advantage": final["structural"]["verified_saved_tokens"]-final["lexical"]["verified_saved_tokens"],
            "semantic_family_decontamination": False, "dependency_closure_verified": False,
            "checkpoint_promoted": False, "arena_data_used": False, "official_score": None}


def render_summary(run):
    """Small deterministic report; the encoder/readout distinction stays explicit."""
    if run.get("schema") != SCHEMA or run.get("checkpoints_sha256") != digest(run["checkpoints"]) or run.get("manifest_sha256") != digest(run["manifest"]):
        raise ValueError("invalid structural experiment receipt")
    lines = ["# Source-DAG edit-head experiment", "", "Generated by `jevops.structural_ablation`; saved receipts, not a fresh verification.",
             "Same-family reflexivity controls; no arena score or unseen-family generalization claim.", "",
             "| Holdout arm | Valid / total | Shortened | Verified saved tokens | Edit CE | Expected cosine loss |",
             "| --- | --- | --- | --- | --- | --- |"]
    for arm in ("lexical", "structural", "drop_graph", "zero_weights"):
        data = run["holdout"]["holdout"][arm]
        ce, cosine = data["rewrite_cross_entropy"], data["rewrite_expected_cosine_loss"]
        ce_text = f"{ce:.6g}" if ce is not None else "unavailable"
        cosine_text = f"{cosine:.6g}" if cosine is not None else "unavailable"
        lines.append(f"| {arm} | {sum(r['check']['verified'] for r in data['rows'])}/{data['sample_count']} | "
                     f"{data['verified_shortening']} | {data['verified_saved_tokens']} | "
                     f"{ce_text} | {cosine_text} |")
    lines += ["", f"Epochs: {run['epochs']}. Compilation calls (cached within this run): {run['compile_calls']}.",
              f"Structural gates: {json.dumps(run['gates'], sort_keys=True)}.",
              "CE/cosine train the sparse readout; graph neighborhoods are fixed features, not a trained GNN.",
              "Operation/reconstruction parameters stay frozen; every arm uses one edit and the same train-only grammar.",
              "Dropping graph weights and zeroing all weights are diagnostics, not independently trained baselines.",
              "Identity controls do not assert global minimality. Final holdouts are renamed members of the same family.",
              "Native kernel checks are relative to the supplied environment; full dependency closure is not authenticated.",
              "No LLM/provider or NCA is used; no checkpoint is promoted.", ""]
    return "\n".join(lines)


def main(argv=None):
    from .router_tuning import _lean_compiler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("output directory exists; choose a new destination")
    result = run_ablation(_lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake, kernel_only=True,
                                         export_dags=True, environment_sha256=args.environment_sha256, timeout=45),
                           environment_sha256=args.environment_sha256, epochs=args.epochs)
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
