"""Scope-guided teacher discovery -> native admission -> graph edit training.

This bounded training-set control is not an arena evaluation or autoencoder
reconstruction experiment. Reports/checkpoints are generated directly to files.
"""
from __future__ import annotations

import argparse
from functools import partial
import json
from pathlib import Path

from .proof_replay import collect_replay_pairs, digest, replay_candidate
from .proof_state import capture_source
from .scoped_proposals import propose_scoped

SCHEMA = "jevops-scoped-training-control/v1"


def control_rows():
    """Inspected training/regression motifs, not blind canaries or holdouts."""
    specs = [
        ("copy", "(p : Prop) (h : p) : p", "have a := h\n  have b := a\n  exact b"),
        ("application", "(p q : Prop) (f : p → q) (h : p) : q", "apply f\n  exact h"),
        ("dependent", "(p : Nat → Prop) (n : Nat) (f : ∀ x, p x) : p n",
         "have a := f n\n  have b := a\n  exact b"),
        ("implicit", "(p : Nat → Prop) (n : Nat) (f : ∀ {x}, p x) : p n",
         "have a : p n := f\n  have b := a\n  exact b"),
    ]
    return [{"id": kind, "split": "train", "family": "scoped_" + kind,
             "source": f"theorem scoped_train_{kind} {header} := by\n  {body}\n"}
            for kind, header, body in specs]


def run_training(rows, *, capture_fn, replay_fn, compile_fn, environment_sha256,
                 epochs=40, seed=17, max_compiles=48, max_proposals=2):
    """Only admitted training pairs seed the existing graph edit-policy fitter.

    Non-training rows are forwarded only for split/ID exclusion; their source
    and target contents are never read. Failure to admit every training teacher
    stops before any fit. This control has no checkpoint-promotion authority.
    """
    from .graph_refinement import CompilerBudget, fit_training
    from .graph_policy import GraphEditPolicy, graph_context
    from .structural_training import collect_structural_pairs

    if (type(epochs) is not int or not 1 <= epochs <= 200 or type(seed) is not int or not 0 <= seed < 2**32
            or type(max_proposals) is not int or not 1 <= max_proposals <= 16):
        raise ValueError("invalid training budget")
    if not isinstance(rows, list) or not 2 <= sum(r["split"] == "train" for r in rows) <= 8:
        raise ValueError("requires two to eight training rows")
    compiler = CompilerBudget(compile_fn, max_compiles)
    diagnostics = []

    def propose(source, capture):
        r = propose_scoped(source, capture, environment_sha256=environment_sha256, limit=max_proposals)
        diagnostics.append(r)
        return r["proposals"]

    teachers = collect_replay_pairs(rows, capture_fn=capture_fn, replay_fn=replay_fn,
        compile_fn=compiler, environment_sha256=environment_sha256, proposal_fn=propose,
        max_proposals=max_proposals)
    result = {"schema": SCHEMA, "ok": False, "scope": "inspected_training_control_not_generalization",
              "teacher_discovery": teachers, "proposal_diagnostics": diagnostics,
              "checkpoint_promoted": False, "official_score": None, "evaluation_accessed": False,
              "decoder_type_safe_by_construction": False, "reconstruction_trained": False,
              "neural_cellular_automaton_trained": False, "model_trained": False,
              "compile_attempts": compiler.attempts}
    if not teachers["ok"]:
        return {**result, "reason": "teacher_admission"}
    families = {r["id"]: r.get("family", "scoped_local") for r in rows if r["split"] == "train"}
    training = [{"id": p["id"], "split": "train", "family": families[p["id"]],
                 "source": p["text"], "target": p["target_text"]} for p in teachers["pairs"]]
    fit = fit_training(compiler, environment_sha256=environment_sha256, rows=training,
                       epochs=epochs, seed=seed, max_compiles=max_compiles)
    result["fit"] = fit
    if not fit["ok"]:
        return {**result, "reason": "training_admission"}
    model = GraphEditPolicy.from_dict(fit["checkpoints"][fit["selected"]])
    frozen = digest(model.to_dict())
    predictions = {}
    for r in training:
        context = graph_context(r["source"], compiler(r["source"]), environment_sha256=environment_sha256)
        predictions[r["id"]] = model.predict(r["source"], context)
    # Check the raw chosen output, with no teacher substitution or solver rescue.
    check = collect_structural_pairs([{k: v for k, v in r.items() if k != "target"} for r in training],
        {key: value["source"] for key, value in predictions.items()}, compile_fn=compiler,
        environment_sha256=environment_sha256)
    if digest(model.to_dict()) != frozen:
        raise ValueError("checking mutated the frozen model")
    stats = fit["statistics"][fit["selected"]]
    loss_gates = {k: stats["after"][k] <= stats["before"][k] + 1e-9
                  for k in ("cross_entropy", "expected_cosine_loss")}
    return {**result, "ok": check["ok"] and all(loss_gates.values()),
            "model_trained": True, "selected": fit["selected"], "loss_gates": loss_gates,
            "raw_training_predictions": predictions, "raw_training_check": check,
            "raw_training_verified_saved_tokens": sum(p["source_tokens"] - p["target_tokens"] for p in check["pairs"]),
            "loss_scope": "training_edit_choice_CE_and_expected_IR_operation_cosine_not_reconstruction"}


def measurement(result):
    """Small derived receipt; full evidence stays in experiment.json."""
    teachers = result["teacher_discovery"]
    out = {k: result[k] for k in ("schema", "ok", "scope", "model_trained", "checkpoint_promoted",
                                  "evaluation_accessed", "official_score")}
    out.update(experiment_sha256=digest(result), training_pairs=len(teachers["pairs"]),
               teacher_source_tokens=sum(p["source_tokens"] for p in teachers["pairs"]),
               teacher_target_tokens=sum(p["target_tokens"] for p in teachers["pairs"]),
               replay_calls=len(teachers["attempts"]), native_compile_calls=len(result["compile_attempts"]),
               selected=result.get("selected"), raw_training_verified_saved_tokens=result.get("raw_training_verified_saved_tokens"))
    if "selected" in result:
        stats = result["fit"]["statistics"][result["selected"]]
        out.update(epochs=result["fit"]["epochs"], updates=stats["updates"], encoder_changed=stats["encoder_changed"],
                   loss_scope=result["loss_scope"], loss_gates=result["loss_gates"],
                   raw_verified_training_pairs=len(result["raw_training_check"]["pairs"]),
                   losses={phase: {k: stats[phase][k] for k in ("cross_entropy", "expected_cosine_loss", "correct_count")}
                           for phase in ("before", "after")})
    else:
        out["reason"] = result["reason"]
    return out


def write_reports(result, output_dir):
    """Exclusive new directory; never replace previous evidence/checkpoints."""
    output_dir = Path(output_dir)
    record = measurement(result)
    summary = ["# Scoped local-term training control", "", f"Outcome: {'passed' if result['ok'] else 'failed'}.", "",
        f"Admitted training pairs: {record['training_pairs']}; teacher source tokens "
        f"{record['teacher_source_tokens']} -> {record['teacher_target_tokens']}.",
        f"Native compile calls: {record['native_compile_calls']}; replay calls: {record['replay_calls']}.", ""]
    if result.get("model_trained"):
        a, b = record["losses"]["before"], record["losses"]["after"]
        summary.extend([f"Selected: {record['selected']} ({record['updates']} updates).",
            f"Training edit-choice CE: {a['cross_entropy']:.8f} -> {b['cross_entropy']:.8f}.",
            f"Training expected IR-operation cosine loss: {a['expected_cosine_loss']:.8f} -> {b['expected_cosine_loss']:.8f}.",
            f"Raw model outputs passing strict native shortening/cost checks: {record['raw_verified_training_pairs']}/{record['training_pairs']}.",
            f"Raw training verified token savings: {record['raw_training_verified_saved_tokens']}.", ""])
    else:
        summary.extend([f"Stopped before training: {record['reason']}.", ""])
    summary.extend(["Inspected training/regression cases only; no validation, canary, holdout or arena claim.",
        "These are edit-policy losses, not text reconstruction or semantic-equivalence metrics.",
        "The graph edit encoder is trained; no NCA or reconstruction head is trained here.",
        "The learned decoder is not type-safe by construction. Every output still requires Lean.",
        "No checkpoint promotion, global-minimality claim or official score.", ""])
    artifacts = {"experiment.json": json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
                 "measurement.json": json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n",
                 "summary.md": "\n".join(summary)}
    output_dir.mkdir(parents=True, exist_ok=False)
    for filename, contents in artifacts.items():
        with (output_dir / filename).open("x", encoding="utf-8") as stream:
            stream.write(contents)
    return {"ok": result["ok"], "output_dir": str(output_dir), "training_pairs": record["training_pairs"],
            "selected": record["selected"], "checkpoint_promoted": False}


def main(argv=None):
    from .router_tuning import _lean_compiler
    import torch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True, help="caller-owned dependency environment fingerprint")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists() or args.output_dir.is_symlink():
        parser.error("choose a new output directory")
    torch.set_num_threads(1)
    opts = dict(project_root=args.project_root.resolve(), use_lake=args.lake, environment_sha256=args.environment_sha256)
    result = run_training(control_rows(), capture_fn=partial(capture_source, **opts),
        replay_fn=partial(replay_candidate, **opts),
        compile_fn=_lean_compiler(**opts, kernel_only=True, export_dags=True),
        environment_sha256=args.environment_sha256, epochs=args.epochs, seed=args.seed)
    print(json.dumps(write_reports(result, args.output_dir), sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
