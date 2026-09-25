"""Offline comparison of matched native-rejection training runs.

Generate compact evidence from saved artifacts, never new Lean verification,
training, held-out selection or checkpoint promotion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .rejection_training import ARM_WEIGHTS, SCHEMA, measurement
from .structural_policy import digest


def summarize_runs(run_dirs):
    if not isinstance(run_dirs, (list, tuple)) or not 1 <= len(run_dirs) <= 8:
        raise ValueError("invalid comparison size")
    expected, seen, records = None, set(), []
    for directory in run_dirs:
        directory = Path(directory)
        experiment = json.loads((directory / "experiment.json").read_text())
        saved = json.loads((directory / "measurement.json").read_text())
        if (experiment.get("schema") != SCHEMA or experiment.get("model_trained") is not True
                or saved.get("experiment_sha256") != digest(experiment) or saved != measurement(experiment)):
            raise ValueError("mismatched training artifacts")
        fit, protocol = experiment["fit"], experiment["protocol"]
        audits = experiment["candidate_audit"]
        if (protocol["training_only"] is not True or experiment["evaluation_accessed"] is not False
                or protocol["initial_weights_matched"] is not True or protocol["rejection_weights"] != ARM_WEIGHTS
                or fit["candidate_audit_sha256"] != digest(audits) or not audits["ok"]):
            raise ValueError("unmatched or incomplete training protocol")
        binding = {"environment": fit["environment_sha256"], "toolchain": fit["checkpoints"][fit["selected"]]["toolchain"],
                   "training_rows": fit["training_rows"], "shapes": fit["training_shapes"],
                   "templates": fit["checkpoints"][fit["selected"]]["templates"],
                   "epochs": fit["epochs"], "seed": fit["seed"],
                   "protocol_without_lr": {k: v for k, v in protocol.items() if k != "learning_rate"},
                   "audit_decisions": [[{k: e[k] for k in ("index", "source_sha256", "tokens", "status")}
                                        for e in a["entries"]] for a in audits["rows"]]}
        if expected is None:
            expected = binding
        elif expected != binding:
            raise ValueError("runs differ in data, grammar, audits, initialization or update budget")
        rate = protocol["learning_rate"]
        if rate in seen or rate != fit["learning_rate"]:
            raise ValueError("duplicate/mismatched learning rate")
        seen.add(rate)
        updates = fit["epochs"] * len(fit["training_rows"])
        if any(s["updates"] != updates or s["examples_seen"] != updates for s in saved["statistics"].values()):
            raise ValueError("unmatched updates/examples")
        records.append({"learning_rate": rate, "experiment_sha256": saved["experiment_sha256"],
                        "measurement": saved})
    records.sort(key=lambda r: r["learning_rate"])
    candidates = [{"learning_rate": r["learning_rate"], "arm": arm, "metrics": stats["after"],
                   "freeze_sha256": r["measurement"]["freeze_sha256"]}
                  for r in records for arm, stats in r["measurement"]["statistics"].items()]
    rank = lambda c: (-c["metrics"]["acceptable_count"], -c["metrics"]["correct_count"],
                      c["metrics"]["supervised_total"], c["learning_rate"], c["arm"])
    best_graph = min((c for c in candidates if c["arm"] in ARM_WEIGHTS), key=rank)
    result = {"schema": SCHEMA + "/comparison", "evidence_kind": "saved_native_training_observations_not_fresh_verification",
              "selection_scope": "training_only_sequential_development", "runs": records,
              "matched_binding_sha256": digest(expected), "best_graph": best_graph,
              "best_trained_control": min(candidates, key=rank), "training_cases": len(expected["training_rows"]),
              "evaluation_accessed": False, "checkpoint_promoted": False, "official_score": None,
              "all_graph_training_gates_passed": all(
                  s["after"]["acceptable_count"] == s["after"]["correct_count"] == s["after"]["sample_count"]
                  and all(s["after"][k] <= s["before"][k] + 1e-9 for k in ("cross_entropy", "expected_cosine_loss"))
                  for r in records for arm, s in r["measurement"]["statistics"].items() if arm in ARM_WEIGHTS)}
    result["comparison_sha256"] = digest(result)
    return result


def generate_reports(run_dirs, output_dir):
    result = summarize_runs(run_dirs)
    lines = ["# Native-rejection training: learning-rate comparison", "",
        "Generated from saved native training observations, not fresh verification or held-out performance.",
        "Same eight-case protocol (or caller-supplied matched rows), initial graph weights, grammar and updates; only learning rate differs between runs.", "",
        "| Learning rate | Arm | Acceptable / cases | Correct | Verified saved tokens | CE | Expected cosine | Rejected probability |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for run in result["runs"]:
        measured = run["measurement"]
        for arm, stats in measured["statistics"].items():
            s = stats["after"]
            lines.append(f"| {run['learning_rate']} | {arm} | {s['acceptable_count']}/{s['sample_count']} | {s['correct_count']} | "
                         f"{s['verified_saved_tokens']} | {s['cross_entropy']:.8g} | {s['expected_cosine_loss']:.8g} | {s['rejected_probability_mass']:.8g} |")
        s = measured["token_length"]
        lines.append(f"| {run['learning_rate']} | token_length | {s['acceptable_count']}/{s['sample_count']} | {s['correct_count']} | "
                     f"{s['verified_saved_tokens']} | {s['cross_entropy']:.8g} | {s['expected_cosine_loss']:.8g} | {s['rejected_probability_mass']:.8g} |")
    b, c = result["best_graph"], result["best_trained_control"]
    lines.extend(["", f"Best graph on training criteria: {b['arm']} at LR {b['learning_rate']}.",
        f"Best trained control: {c['arm']} at LR {c['learning_rate']}.",
        "Unknown failures are not negative labels. CE/cosine and smoothing are unchanged by the auxiliary penalty.",
        "Lower rejected probability alone is not success: validity, shortest admitted labels and separate losses remain visible.",
        "The old frozen-transfer failure is not replaced by these training results. No promotion, arena score, or global-minimality claim.", ""])
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "measurement.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
    with (output_dir / "summary.md").open("x") as stream:
        stream.write("\n".join(lines))
    return {"output_dir": str(output_dir), "runs": len(result["runs"]), "checkpoint_promoted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(generate_reports(args.run_dirs, args.output_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
