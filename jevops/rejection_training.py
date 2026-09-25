"""Matched training-only control for learning to reject shorter invalid edits.

Keep CE/cosine unchanged, compare a fixed native-rejection penalty with zero
penalty, and preserve complete candidate evidence. Not an arena/holdout runner.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch

from .autoencoder_training import AutoencoderConfig, learning_rate_for_step
from .candidate_audit import BAD, audit_candidates, audited_loss, render_choices
from .graph_composition import CheckedCompiler
from .graph_policy import GraphEditPolicy, candidate_loss, metrics
from .graph_refinement import CompilerBudget, FIT_SCHEMA, shape_digest
from .proof_tokens import proof_source_tokens
from .rewrite_policy import body_of, mine_template
from .scoped_training import control_rows
from .structural_policy import StructuralEditPolicy, digest
from .structural_training import collect_structural_pairs

SCHEMA = "jevops-native-rejection-training/v1"
ARM_WEIGHTS = {"ce_cosine": 0.0, "ce_cosine_rejection": .25}


def training_rows():
    """Old training motifs plus balanced reflexive/nonreflexive training pairs.

    No evaluation corpus is imported or relabeled. The literal reference is
    only a proposal until native admission; rfl is not a universal rewrite.
    """
    rows = control_rows()
    targets = {"copy": "exact h", "application": "exact f h", "dependent": "exact f n", "implicit": "exact @f n"}
    for r in rows:
        r["target"] = body_of(r["source"])[0] + "\n  " + targets[r["id"]] + "\n"
    for domain in ("Nat", "Bool"):
        for reflexive in (True, False):
            tag = f"{domain.lower()}_{'refl' if reflexive else 'nonrefl'}"
            right = "n" if reflexive else "m"
            prefix = f"theorem reject_train_{tag} (n m : {domain}) (h : n = {right}) : n = {right} := by\n"
            rows.append({"id": tag, "split": "train", "family": "rejection_" + tag,
                "source": prefix + "  have a := h\n  have b := a\n  exact b\n",
                "target": prefix + ("  rfl\n" if reflexive else "  exact h\n")})
    return rows


def run_training(rows, compile_fn, *, environment_sha256, epochs=80, seed=17, max_compiles=128, learning_rate=.25):
    """Fresh admission/auditing before any gradient; no evaluation access."""
    if (not isinstance(rows, list) or not 2 <= len(rows) <= 16
            or any(not isinstance(r, dict) or r.get("split") != "train" for r in rows)):
        raise ValueError("rejection training requires training rows only")
    if (type(epochs) is not int or not 1 <= epochs <= 200 or type(seed) is not int or not 0 <= seed < 2**32):
        raise ValueError("invalid training budget")
    if type(learning_rate) not in (int, float) or not math.isfinite(learning_rate) or not 0 < learning_rate <= .25:
        raise ValueError("invalid learning rate")
    if any(not isinstance(r.get("family"), str) or not 1 <= len(r["family"]) <= 128 for r in rows):
        raise ValueError("training family identity required")
    compiler = CompilerBudget(compile_fn, max_compiles)
    admission = collect_structural_pairs([{k: v for k, v in r.items() if k != "target"} for r in rows],
        {r["id"]: r["target"] for r in rows}, compile_fn=compiler, environment_sha256=environment_sha256)
    result = {"schema": SCHEMA, "ok": False, "model_trained": False, "evaluation_accessed": False,
              "checkpoint_promoted": False, "official_score": None, "training_admission": admission,
              "compile_attempts": compiler.attempts, "scope": "training_discrimination_control_not_generalization",
              "reconstruction_trained": False, "neural_cellular_automaton_trained": False}
    if not admission["ok"] or len(admission["pairs"]) != len(rows):
        return {**result, "reason": "positive_teacher_admission"}
    bank = {}
    for pair in admission["pairs"]:
        rule = mine_template(pair["text"], body_of(pair["target_text"])[1])
        if rule is None:
            return {**result, "reason": "unreachable_teacher_grammar"}
        bank[rule["id"]] = rule
    templates = [bank[k] for k in sorted(bank)]
    wire = next(iter(admission["graphs"].values()))
    toolchain = (wire["lean_version"], wire["lean_githash"])
    checker = CheckedCompiler(compiler, environment_sha256=environment_sha256, toolchain=toolchain, max_compiles=max_compiles)
    audits = audit_candidates(rows, templates, checker)
    result["candidate_audit"] = audits
    if not audits["ok"]:
        return {**result, "reason": "incomplete_candidate_audit_or_nonminimal_teacher"}
    config = dict(environment_sha256=environment_sha256, toolchain=toolchain)
    models = {name: GraphEditPolicy(templates, seed=seed, pooling="multiscale", **config) for name in ARM_WEIGHTS}
    models["fixed_graph"] = StructuralEditPolicy(templates, structural=True, **config)
    initial = {k: m.to_dict() for k, m in models.items()}
    if initial["ce_cosine"] != initial["ce_cosine_rejection"]:
        raise ValueError("unmatched initial weights")
    contexts = {arm: [checker.context(model, r["source"]) for r in rows] for arm, model in models.items()}

    def measure(model, arm):
        outcomes = []
        for i, (row, audit) in enumerate(zip(rows, audits["rows"])):
            source, target = row["source"], row["target"]
            rendered = render_choices(source, templates)
            if model is None:
                logits = torch.tensor([-e["tokens"] for e in audit["entries"]], dtype=torch.float64)
                prediction = {"choice": int(logits.argmax())}
                raw = candidate_loss(logits, [c for c, _ in rendered], body_of(target)[1])
                mass = sum(float(logits.softmax(0)[j]) for j, e in enumerate(audit["entries"]) if e["status"] in BAD)
                raw = {**raw, "supervised_total": raw["total"], "rejected_probability_mass": mass}
            else:
                ctx = contexts[arm][i]
                prediction = model.predict(source, ctx)
                if isinstance(model, GraphEditPolicy):
                    raw = audited_loss(model, source, target, ctx, audit, split="train", rejection_weight=ARM_WEIGHTS[arm])
                else:
                    from .rewrite_policy import probabilities
                    raw = model.objective(source, target, ctx)
                    p = probabilities(model.weights, model.rows(source, ctx))
                    raw = {**raw, "supervised_total": raw["total"],
                           "rejected_probability_mass": sum(p[j] for j, e in enumerate(audit["entries"]) if e["status"] in BAD)}
                index = prediction["choice"]
                if (type(index) is not int or not 0 <= index < len(rendered)
                        or body_of(prediction["source"])[1] != rendered[index][0]["body"]):
                    raise ValueError("prediction outside audited grammar")
            loss = metrics({k: v for k, v in raw.items() if k != "gradient"})
            entry = audit["entries"][prediction["choice"]]
            valid = entry["status"] in {"accepted", "identity"}
            outcomes.append({"id": row["id"], "choice": prediction["choice"], "label": audit["label"],
                "correct": prediction["choice"] == audit["label"], "acceptable": valid,
                "status": entry["status"], "loss": loss, "source_tokens": audit["entries"][0]["tokens"],
                "prediction_tokens": entry["tokens"], "verified_saved_tokens":
                audit["entries"][0]["tokens"]-entry["tokens"] if valid else 0})
        return {"rows": outcomes, "sample_count": len(outcomes), "correct_count": sum(r["correct"] for r in outcomes),
                "acceptable_count": sum(r["acceptable"] for r in outcomes),
                "verified_saved_tokens": sum(r["verified_saved_tokens"] for r in outcomes),
                **{k: sum(r["loss"][k] for r in outcomes)/len(outcomes) for k in (
                    "cross_entropy", "expected_cosine_loss", "supervised_total", "rejected_probability_mass")}}

    stats = {}
    cfg = AutoencoderConfig(learning_rate=learning_rate, warmup_steps=0, decay_steps=1000)
    for arm, model in models.items():
        with torch.no_grad():
            before = measure(model, arm)
        for _ in range(epochs):
            for row, context, audit in zip(rows, contexts[arm], audits["rows"]):
                lr = learning_rate_for_step(cfg, model.steps)
                if isinstance(model, GraphEditPolicy):
                    loss = audited_loss(model, row["source"], row["target"], context, audit,
                                        split="train", rejection_weight=ARM_WEIGHTS[arm])
                    model._apply_loss(loss, lr)
                else:
                    model.train_step(row["source"], row["target"], context, split="train", learning_rate=lr)
        with torch.no_grad():
            after = measure(model, arm)
        stats[arm] = {"before": before, "after": after, "updates": model.steps, "examples_seen": epochs*len(rows),
                      "rejection_weight": ARM_WEIGHTS.get(arm, 0.0)}
        if isinstance(model, GraphEditPolicy):
            encoder = lambda state: {k: v for k, v in state["weights"].items() if k.startswith("encoder.")}
            stats[arm]["encoder_changed"] = digest(encoder(initial[arm])) != digest(encoder(model.to_dict()))
    selected = min(ARM_WEIGHTS, key=lambda arm: (-stats[arm]["after"]["acceptable_count"],
        -stats[arm]["after"]["correct_count"], stats[arm]["after"]["supervised_total"], arm))
    # Rank by the same supervised metric, not totals with different penalties.
    fit = {"schema": FIT_SCHEMA, "ok": True, "environment_sha256": environment_sha256,
           "training_rows": rows, "training_pairs": admission, "training_families": sorted({r["family"] for r in rows}),
           "training_shapes": [shape_digest(checker.state(r["source"])["wire"]) for r in rows],
           "epochs": epochs, "seed": seed, "statistics": stats, "selected": selected,
           "selection_basis": "training_acceptable_then_correct_then_CE_plus_cosine_no_auxiliary_term",
           "checkpoints": {k: m.to_dict() for k, m in models.items()}, "candidate_audit_sha256": digest(audits),
           "matched_initial_graph_weights": True, "learning_rate": learning_rate, "torch_version": str(torch.__version__),
           "compile_attempts": compiler.attempts, "checkpoint_promoted": False, "evaluation_accessed": False}
    fit["freeze_sha256"] = digest(fit)
    best = stats[selected]
    gates = {"all_raw_training_choices_acceptable": best["after"]["acceptable_count"] == len(rows),
             "all_training_labels_selected": best["after"]["correct_count"] == len(rows),
             **{k+"_nonregression": best["after"][k] <= best["before"][k] + 1e-9
                for k in ("cross_entropy", "expected_cosine_loss")}}
    with torch.no_grad():
        length = measure(None, "token_length")
    return {**result, "ok": all(gates.values()), "gates": gates, "model_trained": True, "fit": fit,
            "token_length": length, "selected": selected, "protocol": {
                "epochs": epochs, "seed": seed, "rejection_weights": dict(ARM_WEIGHTS), "initial_weights_matched": True,
                "learning_rate": learning_rate, "training_only": True, "label_smoothing": .02, "cosine_weight": .35,
                "unknown_failures_are_negatives": False, "teacher_fallback_at_prediction": False}}


def measurement(result):
    record = {k: result[k] for k in ("schema", "ok", "model_trained", "evaluation_accessed", "checkpoint_promoted", "official_score", "scope")}
    record.update(experiment_sha256=digest(result), native_compile_calls=len(result["compile_attempts"]),
                  admitted_pairs=len(result["training_admission"]["pairs"]))
    if "candidate_audit" in result:
        from collections import Counter
        record["audit_statuses"] = dict(Counter(e["status"] for a in result["candidate_audit"]["rows"] for e in a["entries"]))
        record["headroom"] = [{"id": a["id"], **a["headroom"]} for a in result["candidate_audit"]["rows"]]
    if result["model_trained"]:
        fit = result["fit"]
        if fit["freeze_sha256"] != digest({k: v for k, v in fit.items() if k != "freeze_sha256"}):
            raise ValueError("changed frozen training receipt")
        record.update(selected=result["selected"], freeze_sha256=fit["freeze_sha256"], protocol=result["protocol"], gates=result["gates"],
                      statistics={arm: {**s, "before": {k: v for k, v in s["before"].items() if k != "rows"},
                                            "after": {k: v for k, v in s["after"].items() if k != "rows"}}
                                  for arm, s in fit["statistics"].items()},
                      token_length={k: v for k, v in result["token_length"].items() if k != "rows"})
    else:
        record["reason"] = result["reason"]
    return record


def write_reports(result, output_dir, *, compact_only=False):
    record = measurement(result)
    lines = ["# Native-rejection training control", "", f"Training gates: {'passed' if result['ok'] else 'failed'}.",
             "Training data only; no holdout, arena score or promotion.", "",
             f"Admitted teachers: {record['admitted_pairs']}; native compiler calls: {record['native_compile_calls']}."]
    if result["model_trained"]:
        lines.extend(["", "| Arm | Acceptable / cases | Correct | Verified saved tokens | CE | Expected cosine loss | Rejected probability mass |",
                      "| --- | --- | --- | --- | --- | --- | --- |"])
        arms = {**{k: v["after"] for k, v in record["statistics"].items()}, "token_length": record["token_length"]}
        for arm, s in arms.items():
            lines.append(f"| {arm} | {s['acceptable_count']}/{s['sample_count']} | {s['correct_count']} | "
                         f"{s['verified_saved_tokens']} | {s['cross_entropy']:.8g} | {s['expected_cosine_loss']:.8g} | {s['rejected_probability_mass']:.8g} |")
        lines.extend(["", f"Selected on training metrics only: {record['selected']}.",
            "Graph arms use identical initial weights, grammar, source DAGs, examples and update counts.",
            "CE, cosine weight and smoothing are unchanged; the rejection penalty is auxiliary."])
    else:
        lines.extend(["", f"Stopped before training: {record['reason']}."])
    lines.extend(["", "Unknown native failures do not become negative labels. No gradients pass through Lean.",
        "Reported savings are within a bounded training grammar; not a global minimum or generalization result.",
        "Edit-policy losses are not reconstruction fidelity or semantic equivalence; no NCA/reconstruction training here.", ""])
    artifacts = {"measurement.json": json.dumps(record, sort_keys=True, indent=2, allow_nan=False)+"\n", "summary.md": "\n".join(lines)}
    if not compact_only:
        artifacts["experiment.json"] = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, contents in artifacts.items():
        with (output_dir/name).open("x", encoding="utf-8") as stream:
            stream.write(contents)
    return {"ok": result["ok"], "model_trained": result["model_trained"], "output_dir": str(output_dir), "checkpoint_promoted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--environment-sha256")
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--learning-rate", type=float, default=.25)
    parser.add_argument("--report-from", type=Path, help="existing experiment.json; regenerate compact reports without Lean or training")
    args = parser.parse_args(argv)
    if args.output_dir.exists() or args.output_dir.is_symlink():
        parser.error("choose a new output directory")
    if args.report_from:
        result = json.loads(args.report_from.read_text())
        receipt = json.loads(args.report_from.with_name("measurement.json").read_text())
        if receipt["experiment_sha256"] != digest(result):
            parser.error("training artifact hash mismatch")
        print(json.dumps(write_reports(result, args.output_dir, compact_only=True), sort_keys=True))
        return 0
    if not args.environment_sha256:
        parser.error("--environment-sha256 is required for native training")
    from .router_tuning import _lean_compiler
    torch.set_num_threads(1)
    compiler = _lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake, kernel_only=True,
        collect_diagnostics=True, export_dags=True, environment_sha256=args.environment_sha256)
    result = run_training(training_rows(), compiler, environment_sha256=args.environment_sha256, epochs=args.epochs,
                          seed=args.seed, learning_rate=args.learning_rate)
    print(json.dumps(write_reports(result, args.output_dir), sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
