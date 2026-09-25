"""Saved-evidence consistency tests; these do not execute or certify Lean."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from jevops.arena_benchmark_report import build_report, main, merge_baselines, summary

ROOT = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena"


@pytest.fixture
def recorded():
    return ((ROOT / "data/benchmark_data_warmup.jsonl").read_text(),
        json.loads((ROOT / "evidence/native-baseline-prepared-2026-09-22.json").read_text()),
        [json.loads((ROOT / "evidence/native-controlled-core-repair-2026-09-22.json").read_text())])


def test_full_denominator_and_missing_values_are_preserved(recorded):
    report = build_report(*recorded)
    assert report["reported_problem_count"] == len(report["rows"]) == 15
    assert report["required_version_checks"] == 36
    assert report["verified_baseline_version_checks"] == 17
    assert report["status"] == "INCOMPLETE"
    assert report["accepted_full_set_token_total"] is None
    assert report["full_set_heartbeat_reduction_pct"] is None
    assert report["official_score"] is None
    assert report["fresh_native_processes"] == 0 and not report["proof_verified"]
    assert report["reported_native_processes"] == 41
    core = next(r for r in report["rows"] if r["name"] == "Core.InitsUpdatesComm")
    assert core["reference_tokens"] == 224 and core["accepted_tokens"] == 216
    assert len(core["heartbeat_reduction_pct_by_stratum"]) == 6
    putnam = next(r for r in report["rows"] if r["name"] == "putnam_1964_a4")
    assert putnam["accepted_tokens"] is None
    assert all(c["baseline_raw_heartbeats"] is None for c in putnam["checks"])
    assert "17/36" in summary(report) and "Official score: unavailable" in summary(report)


@pytest.mark.parametrize("damage", ["missing_pin", "duplicate_pin", "corpus", "source", "type", "raw",
    "missing_sample", "heartbeat", "cache", "fixture", "duplicate_trial", "wrong_trial_record", "boolean_calls",
    "baseline_schema", "baseline_calls", "training", "memory", "model_calls"])
def test_inconsistent_claims_cannot_be_summarized_as_results(recorded, damage):
    corpus, baseline, trials = copy.deepcopy(recorded)
    row = next(r for r in baseline["rows"] if r["status"] == "VERIFIED")
    trial = trials[0]
    if damage == "missing_pin": baseline["rows"].pop()
    elif damage == "duplicate_pin": baseline["rows"].append(copy.deepcopy(row))
    elif damage == "corpus": corpus += "\n"
    elif damage == "source": row["receipt"]["candidate_sha256"] = "0" * 64
    elif damage == "type": row["receipt"]["type_preserved"] = False
    elif damage == "raw": row["receipt"]["heartbeats"] += 1
    elif damage == "missing_sample": trial["samples"].pop()
    elif damage == "heartbeat": trial["samples"][0]["raw_heartbeats"] += 1
    elif damage == "cache": trial["receipt_cache_enabled"] = True
    elif damage == "fixture": trial["evidence_mode"] = "offline_fixture"
    elif damage == "duplicate_trial": trials.append(copy.deepcopy(trial))
    elif damage == "wrong_trial_record": trial["record"]["src"] += "\n"
    elif damage == "baseline_schema": baseline["schema"] = "unsupported"
    elif damage == "baseline_calls": baseline["processes"] = True
    elif damage == "training": trial["training_enabled"] = True
    elif damage == "memory": trial["production_memory_used"] = True
    elif damage == "model_calls": trial["live_model_calls"] = 1
    else: trial["samples"][0]["verifier_invocations"] = True
    with pytest.raises(ValueError):
        build_report(corpus, baseline, trials)


def test_missing_baseline_does_not_admit_candidate_or_supply_zero_cost(recorded):
    corpus, baseline, trials = copy.deepcopy(recorded)
    row = next(r for r in baseline["rows"] if r["name"] == "Core.InitsUpdatesComm")
    row["status"] = "UNAVAILABLE"
    report = build_report(corpus, baseline, trials)
    core = next(r for r in report["rows"] if r["name"] == row["name"])
    assert core["candidate_status"] == "INCOMPLETE" and core["accepted_tokens"] is None
    assert core["declared_candidate_tokens"] == 216  # Static length, not verified savings.
    assert not core["heartbeat_reduction_pct_by_stratum"]


def test_rejected_candidate_not_counted_as_savings(recorded):
    corpus, baseline, trials = copy.deepcopy(recorded)
    sample = next(s for s in trials[0]["samples"] if s["label"] != "control")
    sample["status"] = "REJECTED"
    report = build_report(corpus, baseline, trials)
    core = next(r for r in report["rows"] if r["name"] == "Core.InitsUpdatesComm")
    assert core["candidate_status"] == "REJECTED"
    assert core["accepted_tokens"] is None and not core["heartbeat_reduction_pct_by_stratum"]


def test_cli_generates_both_reports_and_refuses_overwrite(tmp_path, monkeypatch):
    args = ["arena_benchmark_report", "--corpus", str(ROOT / "data/benchmark_data_warmup.jsonl"),
        "--baseline", str(ROOT / "evidence/native-baseline-prepared-2026-09-22.json"),
        "--trial", str(ROOT / "evidence/native-controlled-core-repair-2026-09-22.json"),
        "--output-dir", str(tmp_path / "report")]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    assert (tmp_path / "report/report.json").is_file()
    assert (tmp_path / "report/summary.md").is_file()
    with pytest.raises(SystemExit):
        main()


def test_recorded_full15_run_reduces_without_inventing_complete_coverage():
    """Audit saved claims only; this test does not perform native verification."""
    folder = ROOT / "evidence/native-full15-benchmark-2026-09-23"
    corpus = (ROOT / "data/benchmark_data_warmup.jsonl").read_text()
    baseline = json.loads((folder / "baseline.json").read_text())
    trials = [json.loads((folder / f"trial-{name}.json").read_text()) for name in ("subst", "extracted", "core")]
    plan = json.loads((folder / "measurement-plan.json").read_text())
    for entry, trial in zip(plan["trials"], trials):
        assert all(trial[k] == v for k, v in entry["protocol"].items())
    actual = build_report(corpus, baseline, trials)
    stored = json.loads((folder / "report.json").read_text())
    assert actual == {key: stored[key] for key in actual}
    assert summary(actual) == (folder / "summary.md").read_text()
    assert actual["baseline_status_counts"] == {"VERIFIED": 20, "UNAVAILABLE": 16}
    assert actual["reported_native_processes"] == 60
    assert actual["reference_token_total"] == 17595
    assert actual["declared_candidate_token_total"] == 17474
    assert actual["fully_verified_problems"] == 8
    assert sum(r["verified_version_checks"] > 0 for r in actual["rows"]) == 12
    assert actual["accepted_full_set_token_total"] is None
    assert actual["full_set_heartbeat_reduction_pct"] is None
    assert actual["status"] == "INCOMPLETE" and not actual["proof_verified"]


@pytest.mark.parametrize("archive,names,verified,processes,covered_problems", [
    ("native-full15-continuation-2026-09-23", ("cslib-v4.30.0", "arklib-v4.30.0"), 23, 63, 12),
    ("native-full15-putnam-continuation-2026-09-23",
     ("cslib-v4.30.0", "arklib-v4.30.0", "putnam-v4.25.0"), 26, 66, 15),
])
def test_recorded_continuation_is_reproducible_without_new_proof_claims(
        archive, names, verified, processes, covered_problems):
    """Recompute a saved report; hashes check consistency, not authenticity."""
    folder = ROOT / "evidence" / archive
    corpus = (folder / "inputs/corpus.jsonl").read_text()
    baseline = json.loads((folder / "inputs/previous-baseline.json").read_text())
    for name in names:
        continuation = json.loads((folder / f"inputs/{name}-baseline.json").read_text())
        baseline = merge_baselines(corpus, baseline, continuation)
    trials = [json.loads((folder / f"inputs/trial-{name}.json").read_text())
              for name in ("subst", "extracted", "core")]
    actual = build_report(corpus, baseline, trials)
    stored = json.loads((folder / "report/report.json").read_text())
    assert actual == {key: stored[key] for key in actual}
    assert summary(actual) == (folder / "report/summary.md").read_text()
    assert actual["baseline_status_counts"] == {"VERIFIED": verified, "UNAVAILABLE": 36 - verified}
    assert actual["reported_native_processes"] == processes
    assert actual["fully_verified_problems"] == 9
    assert sum(r["verified_version_checks"] > 0 for r in actual["rows"]) == covered_problems
    assert actual["fresh_native_processes"] == 0
    assert actual["accepted_full_set_token_total"] is None
    assert actual["full_set_heartbeat_reduction_pct"] is None
    assert actual["official_score"] is None and not actual["proof_verified"]
    for entry in json.loads((folder / "archive-index.json").read_text()):
        path = (folder / entry["archive"]).resolve(strict=True)
        assert path.is_relative_to(folder.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


@pytest.fixture
def disjoint(recorded):
    """Partition saved claims, not a new native execution or synthetic proof."""
    corpus, original, _ = copy.deepcopy(recorded)
    previous, continuation = copy.deepcopy(original), copy.deepcopy(original)
    available = [i for i, row in enumerate(original["rows"]) if row["status"] == "VERIFIED"]
    split = set(available[:4])
    for i, row in enumerate(original["rows"]):
        gap = {k: row[k] for k in ("name", "lean_tag", "git_commit")}
        gap.update(status="UNAVAILABLE", dependencies_verified=False, baseline_compiles=None,
                   capability_gaps=["prepared_project_binding_missing_or_ambiguous"])
        if i in split:
            previous["rows"][i] = gap
        elif row["status"] == "VERIFIED":
            continuation["rows"][i] = gap
    previous["processes"] = len(available) - len(split)
    continuation["processes"] = len(split)
    return corpus, previous, continuation


def test_disjoint_continuation_preserves_denominator_and_provenance(disjoint):
    corpus, previous, continuation = disjoint
    untouched = copy.deepcopy((previous, continuation))
    combined = merge_baselines(corpus, previous, continuation)
    report = build_report(corpus, combined, [])
    assert report["verified_baseline_version_checks"] == 17
    assert report["reported_native_processes"] == 17
    assert report["status"] == "INCOMPLETE"
    assert len(report["baseline_continuation"]["row_sources"]) == 36
    assert len(report["baseline_continuation"]["reports"]) == 2
    assert "earlier checks were not rerun" in summary(report)
    assert "native processes across contributing runs: 17" in summary(report)
    assert "Reported fresh native processes" not in summary(report)
    assert (previous, continuation) == untouched


@pytest.mark.parametrize("damage", ["overlap", "hidden_receipt", "wrong_gap", "prior_attempt", "corpus"])
def test_continuation_cannot_hide_or_replace_attempted_pins(disjoint, damage):
    corpus, previous, continuation = disjoint
    old_index = next(i for i, r in enumerate(previous["rows"]) if r["status"] == "VERIFIED")
    new_index = next(i for i, r in enumerate(continuation["rows"]) if r["status"] == "VERIFIED")
    if damage == "overlap":
        continuation["rows"][old_index] = copy.deepcopy(previous["rows"][old_index])
        continuation["processes"] += 1
    elif damage == "hidden_receipt": continuation["rows"][old_index]["receipt"] = {}
    elif damage == "wrong_gap": continuation["rows"][old_index]["capability_gaps"] = ["wrong pin"]
    elif damage == "prior_attempt": previous["rows"][new_index]["receipt"] = {}
    else: continuation["corpus_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        merge_baselines(corpus, previous, continuation)


def test_new_failure_is_retained_not_dropped_for_an_old_gap(disjoint):
    corpus, previous, continuation = disjoint
    row = next(r for r in continuation["rows"] if r["status"] == "VERIFIED")
    row["status"] = "ERROR"
    row["receipt"]["outcome"] = "ERROR"
    row["receipt"]["reason"] = "native check failed"
    result = build_report(corpus, merge_baselines(corpus, previous, continuation), [])
    assert result["baseline_status_counts"]["ERROR"] == 1
    assert result["verified_baseline_version_checks"] == 16
    assert "native check failed" in summary(result)


def test_unattempted_gap_keeps_original_diagnostic(disjoint):
    corpus, previous, continuation = disjoint
    index = next(i for i, r in enumerate(previous["rows"])
                 if r["status"] == continuation["rows"][i]["status"] == "UNAVAILABLE")
    previous["rows"][index]["capability_gaps"] = ["putnam_compiled_import_missing: Mathlib"]
    continuation["rows"][index]["capability_gaps"] = ["prepared_project_binding_missing_or_ambiguous"]
    result = merge_baselines(corpus, previous, continuation)
    assert result["rows"][index] == previous["rows"][index]


def test_continuation_cli_records_all_inputs(disjoint, tmp_path, monkeypatch):
    corpus, previous, continuation = disjoint
    (tmp_path / "corpus").write_text(corpus)
    for name, data in (("previous", previous), ("continuation", continuation)):
        (tmp_path / name).write_text(json.dumps(data))
    monkeypatch.setattr("sys.argv", ["report", "--corpus", str(tmp_path / "corpus"),
        "--baseline", str(tmp_path / "previous"), "--continuation", str(tmp_path / "continuation"),
        "--output-dir", str(tmp_path / "output")])
    assert main() == 0
    result = json.loads((tmp_path / "output/report.json").read_text())
    assert len(result["input_sha256"]) == 3
    assert result["reported_native_processes"] == 17
    assert result["fresh_native_processes"] == 0 and not result["proof_verified"]
