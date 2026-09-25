"""Generate full-corpus benchmark tables from native baseline/trial reports.

This is an offline consistency check, NOT proof verification or authentication.
Missing pins remain in the denominator; no imputation, promotion or training.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from .arena import ArenaContext, TOKENIZER_ID, VerificationRequest, reference_tokens, source_hash
from .arena_lean import METHOD
from .arena_pareto import _costs
from .arena_report_audit import _receipt_claims_match
from .arena_trial import Candidate, _comparison, _pins, trial_plan
from .lean import VersionPin

SCHEMA = "jevops-arena-full-benchmark-report/v1"


def _baseline_cost(record: dict, row: dict) -> int | None:
    if row["status"] != "VERIFIED":
        return None
    value = row["context"]
    context = ArenaContext(**{**value, "versions": tuple(VersionPin(**p) for p in value["versions"]),
        "dependency_digests": tuple(value["dependency_digests"]), "allowed_axioms": tuple(value["allowed_axioms"])})
    pin = VersionPin(row["lean_tag"], row["git_commit"])
    receipt = row["receipt"]
    obs = json.loads(receipt["observations_json"])
    native = obs["report"]
    raw = native["raw_heartbeats"]
    if (context.problem != record["name"] or context.statement != record["statement"]
            or context.reference_source != record["src"] or context.versions != (pin,)
            or row["context_id"] != context.context_id
            or receipt["request_id"] != VerificationRequest(context, record["src"], pin).request_id
            or receipt["candidate_sha256"] != source_hash(record["src"])
            or receipt["target"] != record["name"] or receipt["outcome"] != "VERIFIED"
            or receipt["exit_code"] != 0 or receipt["type_preserved"] is not True
            or native["type_preserved"] is not True or native["target_absent_before"] is not True
            or native["outcome"] != "VERIFIED" or type(raw) is not int or raw < 0
            or receipt["heartbeats"] != raw // 1000 or obs["measurement"] != METHOD
            or obs["branch_order"] != "reference-first"
            or json.loads(context.verifier_options_json)["branch_order"] != "reference-first"
            or any(set(native[k]) - set(context.allowed_axioms) for k in ("axioms", "reference_axioms"))
            or any("sorryAx" in native[k] for k in ("axioms", "reference_axioms"))):
        raise ValueError("inconsistent baseline receipt")
    return raw


def build_report(corpus: str, baseline: dict, trials: list[dict]) -> dict:
    """Recompute costs from saved claims; never treat this reducer as a checker."""
    records = [json.loads(line) for line in corpus.splitlines() if line.strip()]
    names = {r["name"] for r in records}
    expected = [(r["name"], p.lean_tag, p.git_commit) for r in records for p in _pins(r)]
    if len(records) != 15 or len(names) != 15 or len(expected) != 36 or len(set(expected)) != 36:
        raise ValueError("the entire 15-problem / 36-pin corpus is required")
    if any(reference_tokens(r["src"], r["statement"]) != r["proof_length"] for r in records):
        raise ValueError("tokenizer no longer matches the corpus reference lengths")
    keys = [(r["name"], r["lean_tag"], r["git_commit"]) for r in baseline["rows"]]
    if (baseline.get("schema") != "jevops-arena-native-readiness/v1"
            or baseline["corpus_sha256"] != source_hash(corpus) or set(keys) != set(expected)
            or len(keys) != len(set(keys)) or baseline["required_version_checks"] != 36
            or baseline["measurement"] != METHOD or baseline["official_score"] is not None):
        raise ValueError("baseline corpus/version matrix mismatch")
    if (type(baseline["processes"]) is not int or not 0 <= baseline["processes"] <= 36
            or sum(r["status"] == "VERIFIED" for r in baseline["rows"]) > baseline["processes"]):
        raise ValueError("inconsistent baseline process accounting")
    indexed = dict(zip(keys, baseline["rows"]))
    by_name = {}
    for trial in trials:
        name = trial["record"]["name"]
        if name in by_name or name not in names or len(trial["arms"]) != 2:
            raise ValueError("one explicit candidate trial per corpus problem required")
        if (trial["record"] != next(r for r in records if r["name"] == name)
                or trial["evidence_mode"] != "local_lean" or trial["receipt_cache_enabled"] is not False
                or trial["repetitions"] < 2 or trial["official_score"] is not None
                or trial["training_enabled"] is not False or trial["production_memory_used"] is not False
                or trial["live_model_calls"] != 0):
            raise ValueError("matching uncached native controlled trial required")
        candidate = Candidate(**trial["arms"][1])
        design = trial_plan(trial["record"], [candidate], repetitions=trial["repetitions"], seed=trial["seed"])
        if any(trial.get(k) != v for k, v in design.items()) or not _receipt_claims_match(trial):
            raise ValueError("inconsistent controlled trial")
        costs = _costs(trial)  # Checks schedule, source, heartbeat and receipt agreement.
        calls = [s["verifier_invocations"] for s in trial["samples"]]
        if (any(type(c) is not int or c not in (0, 1) for c in calls)
                or sum(calls) != trial["native_processes"] or sum(calls) != trial["verifier_invocations"]):
            raise ValueError("inconsistent native process accounting")
        by_name[name] = (trial, candidate, costs)

    rows = []
    for record in records:
        pins = _pins(record)
        checks = []
        for pin in pins:
            entry = indexed[record["name"], pin.lean_tag, pin.git_commit]
            raw = _baseline_cost(record, entry)
            checks.append({**pin.to_dict(), "status": entry["status"], "baseline_raw_heartbeats": raw,
                "capability_gaps": entry.get("capability_gaps", []),
                "reason": entry.get("reason", entry.get("receipt", {}).get("reason", ""))})
        complete = all(c["status"] == "VERIFIED" for c in checks)
        tokens = reference_tokens(record["src"], record["statement"])
        row = {"name": record["name"], "reference_tokens": tokens, "declared_candidate_tokens": tokens,
            "candidate_kind": "unchanged_reference", "verified_version_checks": sum(c["status"] == "VERIFIED" for c in checks),
            "required_version_checks": len(pins), "checks": checks,
            "candidate_status": "UNCHANGED" if complete else "INCOMPLETE",
            "accepted_tokens": tokens if complete else None,
            "heartbeat_reduction_pct_by_stratum": [], "heartbeat_result": "UNCHANGED" if complete else "INCOMPLETE",
            "strata": [], "all_pins_verified": complete}
        if record["name"] in by_name:
            trial, candidate, costs = by_name[record["name"]]
            comparison = _comparison(record, candidate, trial["samples"], trial["repetitions"])
            admitted = complete and costs["control"]["admissible"] and costs[candidate.label]["admissible"]
            # Even allowed axioms may not silently grow relative to the control.
            no_growth = all(set(values) <= set(costs["control"]["axioms_by_version"].get(key, []))
                for key, values in costs[candidate.label]["axioms_by_version"].items())
            admitted = admitted and no_growth
            savings = []
            if admitted:
                for group in comparison["strata"]:
                    c, x = statistics.mean(group["control_raw"]), statistics.mean(group["candidate_raw"])
                    savings.append(100 * (1 - x / c) if c else None)
            row.update(declared_candidate_tokens=comparison["candidate_tokens"], candidate_kind="saved_refactor",
                candidate_label=candidate.label, candidate_sha256=source_hash(candidate.source),
                candidate_status=("VERIFIED" if admitted else "INCOMPLETE" if not complete else
                    "AXIOM_GROWTH" if not no_growth else "REJECTED" if comparison["status"] == "REJECTED" else "INCOMPLETE"),
                accepted_tokens=comparison["candidate_tokens"] if admitted else None,
                all_pins_verified=admitted, heartbeat_reduction_pct_by_stratum=savings,
                heartbeat_result=comparison["heartbeat_result"] if admitted else "INCOMPLETE",
                strata=comparison["strata"], trial_content_sha256=source_hash(json.dumps(trial, sort_keys=True)))
        rows.append(row)
    all_verified = all(r["all_pins_verified"] for r in rows)
    declared = [r["declared_candidate_tokens"] for r in rows]
    return {"schema": SCHEMA, "status": "COMPLETE" if all_verified else "INCOMPLETE",
        "reported_problem_count": 15, "required_version_checks": 36,
        "verified_baseline_version_checks": sum(r["verified_version_checks"] for r in rows),
        "fully_verified_problems": sum(r["all_pins_verified"] for r in rows),
        "reference_token_total": sum(r["reference_tokens"] for r in rows),
        "declared_candidate_token_total": sum(declared) if all(v is not None for v in declared) else None,
        "accepted_full_set_token_total": sum(r["accepted_tokens"] for r in rows) if all_verified else None,
        "full_set_heartbeat_reduction_pct": None,
        "reported_native_processes": baseline["processes"] + sum(t["native_processes"] for t in trials),
        "baseline_status_counts": dict(Counter(r["status"] for r in baseline["rows"])),
        "tokenizer_id": TOKENIZER_ID, "measurement": METHOD, "corpus_sha256": source_hash(corpus),
        "tokenizer_calibration_matches": 15,
        "rows": rows, "proof_verified": False, "fresh_native_processes": 0,
        "official_score": None, "worker_metric_parity": "UNCONFIRMED", "training_enabled": False,
        "notes": ["Offline summary of recorded native observations; not receipt authentication or a new proof check.",
            "Source-token totals count each problem once; declared lengths are not an accepted full-set score.",
            "One fresh baseline process per available pin; refactors use at least two repeats in each branch order.",
            "Raw heartbeats / 1000 are Lean display units, not milliseconds; failed/missing measurements are not zero.",
            "Unchanged rows are baseline-only, not compression wins. No full-set heartbeat aggregate is inferred."]}


def summary(report: dict) -> str:
    lines = ["# Full 15-problem benchmark", "", f"Status: **{report['status']}**.", "",
        f"Native baseline coverage: {report['verified_baseline_version_checks']}/36 pins; "
        f"fully checked problems: {report['fully_verified_problems']}/15. "
        f"Reported fresh native processes: {report['reported_native_processes']}.", "",
        f"Reference tokens: {report['reference_token_total']}; declared candidate tokens: "
        f"{report['declared_candidate_token_total']}. Accepted full-set total: "
        f"{report['accepted_full_set_token_total']}. Official score: unavailable.", "",
        "| Problem | Tokens: reference → candidate | Baseline pins | Candidate | Baseline raw heartbeats (available pins) | Matched heartbeat reduction |",
        "| --- | ---: | ---: | --- | ---: | ---: |"]
    for row in report["rows"]:
        raw = [c["baseline_raw_heartbeats"] for c in row["checks"] if c["baseline_raw_heartbeats"] is not None]
        reductions = row["heartbeat_reduction_pct_by_stratum"]
        measured = [v for v in reductions if v is not None]
        hb = f"{min(raw):,}–{max(raw):,}" if raw else "unavailable"
        savings = f"{min(measured):.3f}–{max(measured):.3f}%" if measured else "—"
        lines.append(f"| {row['name']} | {row['reference_tokens']} → {row['declared_candidate_tokens']} | "
            f"{row['verified_version_checks']}/{row['required_version_checks']} | {row['candidate_status']} | {hb} | {savings} |")
    lines.extend(["", *report["notes"], "", "## Missing/failed checks", ""])
    for row in report["rows"]:
        for check in row["checks"]:
            if check["status"] != "VERIFIED":
                reason = "; ".join(check["capability_gaps"]) or check["reason"] or check["status"]
                lines.append(f"- `{row['name']}` / `{check['lean_tag']}`: {reason}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--trial", action="append", default=[], type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    paths = [args.corpus, args.baseline, *args.trial]
    if any(p.stat().st_size > 16 * 1024 * 1024 for p in paths):
        parser.error("report input byte limit")
    report = build_report(args.corpus.read_text(), json.loads(args.baseline.read_text()),
                          [json.loads(p.read_text()) for p in args.trial])
    report["input_sha256"] = {str(p): source_hash(p.read_text()) for p in paths}
    report["report_generator_sha256"] = source_hash(Path(__file__).read_text())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (args.output_dir / "summary.md").write_text(summary(report))
    print(json.dumps({k: report[k] for k in ("status", "verified_baseline_version_checks", "fully_verified_problems",
        "reference_token_total", "declared_candidate_token_total", "reported_native_processes")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
