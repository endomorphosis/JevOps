"""Offline adapter tests; installed-Lean integration is explicitly opt-in."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jevops import arena_lean as native
from jevops.arena import Outcome, VerificationRequest, content_hash
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

PIN = VersionPin("v4.26.0", "a" * 40)
STATEMENT = "theorem sample (h : True) : True"
RECORD = {"name": "sample", "statement": STATEMENT,
          "src": STATEMENT + " := by\n  have redundant : True := h\n  exact redundant",
          "version_info": [{PIN.lean_tag: PIN.git_commit}]}


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("prepared dependencies"))
    binding = native.ProjectBinding(PIN, tmp_path / "toolchain/bin/lean", tmp_path, "", project_backed=False)
    return native.NativeLeanVerifier({PIN: binding}, max_processes=10)


def request(adapter, **context_changes):
    return VerificationRequest(replace(adapter.context(RECORD), **context_changes),
                               STATEMENT + " := by exact h", PIN)


def report(payload, **changes):
    return {"schema": "jevops-native-arena/v1", "request_id": payload["request_id"],
            "target": payload["target"], "measurement": native.METHOD,
            "branch_order": "candidate-first" if payload.get("candidate_first") else "reference-first",
            "lean_version": "4.26.0", "lean_githash": "b" * 40,
            "report": {"outcome": "VERIFIED", "reason": "", "type_preserved": True,
                       "target_absent_before": True, "raw_heartbeats": 3900, "heartbeats": 3,
                       "reference_raw_heartbeats": 6900, "reference_heartbeats": 6,
                       "axioms": [], "reference_axioms": [], "diagnostics": [], **changes}}


def fixture_runner(monkeypatch, **changes):
    calls = []
    def run(binding, payload, **kwargs):
        calls.append(payload)
        return report(payload, **changes), 0
    monkeypatch.setattr(native, "run_native", run)
    return calls


def test_adapter_preserves_measured_evidence_and_context_bound_cache(adapter, monkeypatch):
    calls = fixture_runner(monkeypatch)
    req = request(adapter, reference_heartbeats=6)
    evaluator = adapter.evaluator(req.context, max_calls=1)
    result = evaluator.evaluate(req.source)
    assert result.status == "MEASURED"
    assert result.score.heartbeat_reduction_pct == 50
    receipt = result.receipts[0]
    evidence = json.loads(receipt.observations_json)
    assert evidence["report"]["raw_heartbeats"] == 3900
    assert evidence["measurement"] == native.METHOD
    assert evidence["dependency_digest"] == req.context.dependency_digests[0]
    assert calls[0]["reference"] == RECORD["src"] and calls[0]["candidate"] == req.source
    assert evaluator.evaluate(req.source) == result
    assert evaluator.cache_hits == 1 and evaluator.calls == adapter.processes == len(calls) == 1
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("changed"))
    stale = evaluator.evaluate(req.source)
    assert stale.status == "INCOMPLETE" and stale.receipts[0].outcome == Outcome.ERROR
    assert evaluator.cache_hits == 1 and len(calls) == 1


@pytest.mark.parametrize("change", [
    {"type_preserved": False}, {"target_absent_before": False}, {"raw_heartbeats": 2999},
    {"heartbeats": True}, {"reference_raw_heartbeats": -1}, {"axioms": "forged"},
    {"reference_heartbeats": float("nan")},
])
def test_malformed_native_observations_cannot_admit(adapter, monkeypatch, change):
    fixture_runner(monkeypatch, **change)
    receipt = adapter(request(adapter))
    assert receipt.outcome == Outcome.ERROR and not receipt.type_preserved


@pytest.mark.parametrize("field,value", [("target", "other"), ("request_id", "forged"),
                                          ("lean_version", "4.34.0"), ("lean_githash", "unknown"),
                                          ("branch_order", "candidate-first"),
                                          ("measurement", "elapsed-milliseconds")])
def test_wrong_native_report_identity(adapter, monkeypatch, field, value):
    def run(_binding, payload, **_kwargs):
        data = report(payload); data[field] = value
        return data, 0
    monkeypatch.setattr(native, "run_native", run)
    assert adapter(request(adapter)).outcome == Outcome.ERROR


@pytest.mark.parametrize("field,expected", [("axioms", Outcome.REJECTED), ("reference_axioms", Outcome.ERROR)])
def test_untrusted_axioms_distinguish_candidate_from_reference_failure(adapter, monkeypatch, field, expected):
    fixture_runner(monkeypatch, **{field: ["sorryAx"]})
    assert adapter(request(adapter)).outcome == expected


def test_calibration_drift_is_inconclusive_and_not_a_zero_score(adapter, monkeypatch):
    fixture_runner(monkeypatch)
    req = request(adapter, reference_heartbeats=200)
    result = adapter.evaluator(req.context, max_calls=1).evaluate(req.source)
    assert result.status == "INCOMPLETE" and result.score is None
    assert result.receipts[0].reason == "reference_heartbeat_calibration_drift"


def test_zero_and_exact_process_budget_include_failures(adapter, monkeypatch):
    calls = fixture_runner(monkeypatch)
    adapter.max_processes = 0
    assert adapter(request(adapter)).outcome == Outcome.BUDGET_EXHAUSTED
    assert not calls and adapter.processes == 0
    adapter.max_processes = 1
    assert adapter(request(adapter)).outcome == Outcome.VERIFIED
    assert adapter(request(adapter)).outcome == Outcome.BUDGET_EXHAUSTED
    assert len(calls) == adapter.processes == 1


def test_timeout_can_retry_and_does_not_become_semantic_rejection(adapter, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError()
    monkeypatch.setattr(native, "run_native", timeout)
    req = request(adapter, reference_heartbeats=6)
    evaluator = adapter.evaluator(req.context, max_calls=2)
    assert evaluator.evaluate(req.source).receipts[0].outcome == Outcome.TIMEOUT
    fixture_runner(monkeypatch)
    assert evaluator.evaluate(req.source).status == "MEASURED"
    assert evaluator.calls == adapter.processes == 2


def test_native_selection_requires_local_calibration_and_reserves_its_cost(adapter, monkeypatch):
    fixture_runner(monkeypatch)
    context = adapter.context(RECORD)
    with pytest.raises(ValueError, match="calibrate"):
        adapter.evaluator(context, max_calls=1)
    calibrated, receipt = adapter.calibrate(context)
    assert calibrated.reference_heartbeats == 6 and calibrated.context_id != context.context_id
    assert receipt.outcome == Outcome.VERIFIED and adapter.processes == 1
    assert context.reference_heartbeats is None
    adapter.max_processes = 1
    missing, exhausted = adapter.calibrate(context)
    assert missing is None and exhausted.outcome == Outcome.BUDGET_EXHAUSTED


def test_live_receipts_without_applicability_validator_are_not_cached(adapter, monkeypatch):
    from jevops.arena import ArenaEvaluator
    calls = fixture_runner(monkeypatch)
    req = request(adapter, reference_heartbeats=6)
    evaluator = ArenaEvaluator(req.context, adapter, max_calls=2, evidence_mode="local_lean")
    assert evaluator.evaluate(req.source).status == "MEASURED"
    assert evaluator.evaluate(req.source).status == "MEASURED"
    assert evaluator.cache_hits == 0 and len(calls) == 2
    assert evaluator.accounting()["cache_entries"] == 0


def test_heartbeat_exhaustion_is_explicit_timeout(adapter, monkeypatch):
    fixture_runner(monkeypatch, outcome="REJECTED", reason="candidate_errors",
                   diagnostics=[{"message": "maximum number of heartbeats exceeded"}])
    assert adapter(request(adapter)).outcome == Outcome.TIMEOUT


def test_changed_dependency_during_execution_rejects_receipt(adapter, monkeypatch):
    def run(_binding, payload, **_kwargs):
        monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("changed mid-call"))
        return report(payload), 0
    monkeypatch.setattr(native, "run_native", run)
    assert adapter(request(adapter)).outcome == Outcome.ERROR


@pytest.mark.parametrize("field,value", [("verifier_id", "legacy"), ("verifier_version", "old"),
                                        ("heartbeat_method", "mock"), ("repository", "another"),
                                        ("verifier_options_json", '{"kernel_check":false}')])
def test_context_configuration_is_not_policy_controlled(adapter, monkeypatch, field, value):
    calls = fixture_runner(monkeypatch)
    assert adapter(request(adapter, **{field: value})).outcome == Outcome.ERROR
    assert not calls and adapter.processes == 0


def test_no_path_fallback_and_safe_toolchain_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    with pytest.raises(native.CapabilityGap, match="pinned_toolchain_missing"):
        native.pinned_lean(tmp_path, PIN.lean_tag)
    with pytest.raises(ValueError):
        native.pinned_lean(tmp_path, "../../bin/lean")


def test_readiness_does_not_claim_installed_compilers_are_complete_projects(tmp_path):
    report = native.readiness([RECORD], [], tmp_path)
    assert report["required_version_checks"] == 1 and report["completed_version_checks"] == 0
    row = report["rows"][0]
    assert row["status"] == "UNAVAILABLE" and row["baseline_compiles"] is None
    assert len(row["capability_gaps"]) == 2
    with pytest.raises(ValueError, match="nonempty"):
        native.readiness([], [], tmp_path)


def test_fingerprint_covers_changes_and_new_artifacts_without_following_epoch_updates(tmp_path):
    lean = tmp_path / "toolchain/bin/lean"; lean.parent.mkdir(parents=True); lean.write_text("fixture executable")
    lib = tmp_path / "toolchain/lib/lean"; lib.mkdir(parents=True)
    imported = lib / "Init.olean"; imported.write_bytes(b"one")
    binding = native.ProjectBinding(PIN, lean, tmp_path, "", project_backed=False)
    reader = Fingerprinter()
    first = binding.fingerprint(reader)
    assert binding.fingerprint(reader) == first
    imported.write_bytes(b"two")
    second = binding.fingerprint(reader)
    assert second != first
    (lib / "Extra.olean").write_bytes(b"new")
    assert binding.fingerprint(reader) != second
    assert replace(binding, prefix="namespace Another\n").fingerprint(reader) != binding.fingerprint(reader)


def test_project_binding_checks_exact_commit_and_reads_only_the_prefix(tmp_path, monkeypatch):
    source = tmp_path / "Main.lean"
    source.write_text("namespace Demo\n" + RECORD["src"] + "\nend Demo\ntheorem later : True := by trivial\n")
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:" + PIN.lean_tag)
    monkeypatch.setattr(native, "_git", lambda _root, *args: PIN.git_commit if args[0] == "rev-parse" else "")
    monkeypatch.setattr(native, "pinned_lean", lambda *_: tmp_path / "bin/lean")
    record = {**RECORD, "url": "fixture://project", "file_path": "Main.lean"}
    project = {"root": str(tmp_path), "repository": "fixture://project"}
    binding = native.project_binding(record, PIN, project, tmp_path)
    assert binding.prefix == "namespace Demo\n" and "later" not in binding.prefix
    assert source.read_text().endswith("theorem later : True := by trivial\n")
    monkeypatch.setattr(native, "_git", lambda *_: "b" * 40)
    with pytest.raises(native.CapabilityGap, match="commit_mismatch"):
        native.project_binding(record, PIN, project, tmp_path)


@pytest.mark.parametrize("text", ["[]", '{"metric":NaN}', '{"metric":Infinity}'])
def test_noncanonical_observations_rejected(text):
    from jevops.arena import VersionReceipt
    with pytest.raises(ValueError):
        VersionReceipt("request", "candidate", "target", Outcome.ERROR, observations_json=text)


@pytest.mark.no_seal(reason="fresh subprocess limits, cleanup and environment isolation")
@pytest.mark.parametrize("case", ["output_limit", "timeout", "bad_exit", "duplicate_report", "environment"])
def test_bounded_process_cleanup_and_environment(tmp_path, monkeypatch, case):
    program = {
        "output_limit": "print('x' * 100000)",
        "timeout": "import time; time.sleep(10)",
        "bad_exit": "raise SystemExit(7)",
        "duplicate_report": "print('JEVOPS_ARENA:{}\\nJEVOPS_ARENA:{}')",
        "environment": "import os,json; print('JEVOPS_ARENA:' + json.dumps({'leaked': 'FAKE_TEST_SECRET' in os.environ, 'path':os.environ['LEAN_PATH']}))",
    }[case]
    executable = tmp_path / "lean"
    executable.write_text(f"#!{sys.executable}\n" + program + "\n")
    executable.chmod(0o700)
    binding = native.ProjectBinding(PIN, executable, tmp_path, "", project_backed=False)
    monkeypatch.setattr(native, "MAX_OUTPUT", 1024)
    monkeypatch.setenv("FAKE_TEST_SECRET", "not-a-real-credential")
    monkeypatch.setenv("LEAN_PATH", "/not/the/bound/environment")
    if case == "environment":
        data, code = native.run_native(binding, {}, timeout=5)
        assert data == {"leaked": False, "path": ""} and code == 0
    else:
        with pytest.raises(TimeoutError if case == "timeout" else ValueError):
            native.run_native(binding, {}, timeout=0.1 if case == "timeout" else 5)


def test_oversized_source_does_not_start_a_process(tmp_path, monkeypatch):
    monkeypatch.setattr(native.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    binding = native.ProjectBinding(PIN, tmp_path / "lean", tmp_path, "", project_backed=False)
    with pytest.raises(ValueError, match="byte budget"):
        native.run_native(binding, {"candidate": "x" * 262145}, timeout=5)


NATIVE = os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") == "1"
ELAN = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))


@pytest.mark.skipif(not NATIVE, reason="opt in with JEVOPS_ARENA_NATIVE_TESTS=1; no installation or network")
@pytest.mark.parametrize("tag", ["v4.25.0", "v4.26.0", "v4.28.0", "v4.33.0-rc2", "v4.34.0"])
@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("valid", "VERIFIED"), ("wrong_type", "REJECTED"), ("target_missing", "REJECTED"),
    ("circular_target", "ERROR"), ("unproved", "REJECTED"), ("scoped", "VERIFIED"),
    ("dropped_parameter", "REJECTED"), ("missing_import", "UNAVAILABLE"),
])
def test_real_lean_independent_branches_and_type_integrity(tag, case, expected, tmp_path, candidate_first):
    try:
        lean = native.pinned_lean(ELAN, tag)
    except native.CapabilityGap as exc:
        pytest.skip(str(exc))
    payload = {"request_id": "native-test", "target": "sample", "max_heartbeats": 200000,
               "candidate_first": candidate_first,
               "prefix": "", "reference": RECORD["src"], "candidate": STATEMENT + " := by exact h"}
    if case == "wrong_type":
        payload["candidate"] = "theorem sample (h : True) : 1 = 1 := by rfl"
    elif case == "target_missing":
        payload["candidate"] = "theorem different : True := by trivial"
    elif case == "circular_target":
        payload["prefix"] = RECORD["src"] + "\n"
    elif case == "unproved":
        payload["candidate"] = STATEMENT + " := by skip"
    elif case in {"scoped", "dropped_parameter"}:
        payload["prefix"] = "namespace Demo\nsection\nvariable (h : True)\ninclude h\n"
        payload["reference"] = "theorem sample : True := by exact h"
        payload["candidate"] = "theorem sample : True := by trivial"
        payload["target"] = "Demo.sample"
        if case == "dropped_parameter":
            payload["candidate"] = "omit h in theorem sample : True := by trivial"
    elif case == "missing_import":
        payload["prefix"] = "import UnavailableArenaDependency\n"
    binding = native.ProjectBinding(VersionPin(tag, "test"), lean, tmp_path, "", project_backed=False)
    data, code = native.run_native(binding, payload, timeout=60)
    assert code == 0 and data["report"]["outcome"] == expected
    assert data["branch_order"] == ("candidate-first" if candidate_first else "reference-first")
    if expected == "VERIFIED":
        assert data["report"]["target_absent_before"] and data["report"]["type_preserved"]
        assert data["report"]["heartbeats"] == data["report"]["raw_heartbeats"] // 1000
        assert data["report"]["axioms"] == []


@pytest.mark.skipif(not NATIVE, reason="explicit opt-in native adapter smoke")
def test_real_adapter_smoke_emits_measured_not_mock_receipts():
    native.pinned_lean(ELAN, PIN.lean_tag)
    result = subprocess.run([sys.executable, "-m", "jevops.arena_lean", "--smoke", "--max-processes", "2",
                             "--elan-home", str(ELAN)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["evidence_mode"] == "local_lean" and data["official_score"] is None
    assert data["arena_problem"] is False and data["processes"] == 2
    assert data["baseline"]["outcome"] == "VERIFIED"
    assert data["candidate"]["status"] == "MEASURED"
    assert data["reference_tokens"] == 9 and data["candidate"]["length"] == 3
    assert data["candidate_source"].endswith("by exact h")
    assert data["calibrated_context"]["reference_heartbeats"] is not None


@pytest.mark.skipif(not NATIVE, reason="explicit opt-in native prepared-project integration")
def test_real_prepared_project_baseline_is_pinned_and_read_only(tmp_path):
    native.pinned_lean(ELAN, PIN.lean_tag)
    project = tmp_path / "project"; project.mkdir()
    source = "namespace Demo\n" + RECORD["src"] + "\nend Demo\n"
    (project / "Main.lean").write_text(source)
    (project / "lean-toolchain").write_text("leanprover/lean4:" + PIN.lean_tag + "\n")
    def git(*args):
        return subprocess.run(["/usr/bin/git", "-C", str(project), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "--quiet")
    git("add", "Main.lean", "lean-toolchain")
    git("-c", "user.name=Arena test", "-c", "user.email=arena-test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "native integration fixture")
    commit = git("rev-parse", "HEAD")
    record = {**RECORD, "name": "Demo.sample", "file_path": "Main.lean", "url": "fixture://local-project",
              "version_info": [{PIN.lean_tag: commit}]}
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps(record) + "\n")
    manifest = tmp_path / "projects.json"
    manifest.write_text(json.dumps([{"root": str(project), "repository": record["url"],
                                     "lean_tag": PIN.lean_tag, "git_commit": commit, "search_paths": []}]))
    argv = [sys.executable, "-m", "jevops.arena_lean", "--baseline", "--corpus", str(corpus),
            "--projects", str(manifest), "--elan-home", str(ELAN)]
    zero = subprocess.run(argv + ["--max-processes", "0"], capture_output=True, text=True, timeout=30)
    assert zero.returncode == 0, zero.stderr
    assert json.loads(zero.stdout)["rows"][0]["status"] == "BUDGET_EXHAUSTED"
    run = subprocess.run(argv + ["--max-processes", "1"], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["completed_version_checks"] == report["processes"] == 1
    assert report["rows"][0]["status"] == "VERIFIED"
    assert report["rows"][0]["context"]["versions"][0]["git_commit"] == commit
    assert report["official_score"] is report["local_combined_pct"] is None
    assert (project / "Main.lean").read_text() == source
    assert git("status", "--porcelain") == ""
