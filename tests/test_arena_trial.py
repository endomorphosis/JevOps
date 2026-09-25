"""Synthetic measurement controls, with native execution mocked by default."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import copy

import pytest

from jevops import arena_lean as native
from jevops.arena import content_hash
from jevops.arena_trial import Candidate, ORDERS, diagnostic_repair_candidates, main, proposals, run_trial, trial_plan
from jevops.lean import VersionPin

PIN = VersionPin("v4.26.0", "a" * 40)
STATEMENT = "theorem example (h : True) : True"
RECORD = {"name": "example", "statement": STATEMENT,
          "src": STATEMENT + " := by\n  have redundant : True := h\n  exact redundant",
          "version_info": [{PIN.lean_tag: PIN.git_commit}]}
CANDIDATE = Candidate("short", STATEMENT + " := by exact h", "deterministic offline fixture")


def historical_rejection_trial():
    evidence = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence"
    return json.loads((evidence / "native-controlled-core-2026-09-22.json").read_text())


def test_historical_rejection_reconstructs_manual_repair_without_using_the_answer(monkeypatch):
    hints = historical_rejection_trial()
    monkeypatch.setattr(native, "run_native", lambda *a, **kw: pytest.fail("hints cannot invoke verifier"))
    before = copy.deepcopy(hints)
    drafts = diagnostic_repair_candidates(hints["record"], hints, cap=8)
    assert len(drafts) == 1 and hints == before  # repetitions/versions do not multiply drafts
    # Read the historical answer only AFTER generation, as a regression check.
    path = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json"
    manual = json.loads(path.read_text())
    assert drafts[0].source == manual["source"]
    assert "unverified" in drafts[0].provenance and "request " in drafts[0].provenance
    assert set(drafts[0].__dict__) == {"label", "source", "provenance"}
    assert diagnostic_repair_candidates(hints["record"], hints, cap=0) == []


@pytest.mark.parametrize("damage", ["record", "source", "receipt", "context", "outcome", "fixture", "duplicate_arm", "shape"])
def test_wrong_or_stale_repair_hints_cannot_supply_candidates(damage):
    hints = historical_rejection_trial()
    record = copy.deepcopy(hints["record"])
    sample = next(s for s in hints["samples"] if s["status"] == "REJECTED")
    if damage == "record":
        hints["record"]["src"] += "\n"
    elif damage == "source":
        next(a for a in hints["arms"] if a["label"] == sample["label"])["source"] += "\n"
    elif damage == "receipt":
        sample["receipt"]["request_id"] = "0" * 64
    elif damage == "context":
        hints["contexts"][0]["statement"] += " "
    elif damage == "outcome":
        sample["receipt"]["outcome"] = "TIMEOUT"
    elif damage == "fixture":
        hints["evidence_mode"] = "offline_fixture"
    elif damage == "duplicate_arm":
        hints["arms"].append(hints["arms"][-1])
    else:
        hints = []
    with pytest.raises(ValueError):
        diagnostic_repair_candidates(record, hints)


def test_timeout_and_verified_results_are_not_error_repair_signals():
    for status in ("TIMEOUT", "VERIFIED", "UNAVAILABLE", "ERROR", "BUDGET_EXHAUSTED"):
        hints = historical_rejection_trial()
        for sample in hints["samples"]:
            sample["status"] = status
        assert diagnostic_repair_candidates(hints["record"], hints) == []


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture deps"))
    def make(cost=None, **kwargs):
        counts = {}
        def runner(binding, payload, **_kwargs):
            order = "candidate-first" if payload["candidate_first"] else "reference-first"
            key = (order, payload["candidate"])
            index = counts.get(key, 0); counts[key] = index + 1
            raw = cost(payload, order, index) if cost else (6900 if payload["candidate"] == payload["reference"] else 3900)
            report = {"outcome": "VERIFIED", "type_preserved": True, "target_absent_before": True,
                      "axioms": [], "reference_axioms": [], "raw_heartbeats": raw, "heartbeats": raw // 1000,
                      "reference_raw_heartbeats": 7900, "reference_heartbeats": 7, "diagnostics": []}
            return {"schema": "jevops-native-arena/v1", "request_id": payload["request_id"],
                    "target": payload["target"], "measurement": native.METHOD, "lean_version": "4.26.0",
                    "lean_githash": "b" * 40, "branch_order": order, "report": report}, 0
        monkeypatch.setattr(native, "run_native", runner)
        binding = native.ProjectBinding(PIN, tmp_path / "lean", tmp_path, "", project_backed=False)
        return {(PIN, order): native.NativeLeanVerifier({PIN: binding}, max_processes=128, branch_order=order, **kwargs)
                for order in ORDERS}
    return make


def trial(factory, cost=None, **kwargs):
    return run_trial(RECORD, [CANDIDATE], factory(cost), max_calls=kwargs.pop("max_calls", 8),
                     evidence_mode="offline_fixture", **kwargs)


def test_balanced_plan_is_reproducible_bounded_and_has_distinct_repetition_ids():
    one = trial_plan(RECORD, [CANDIDATE], repetitions=3, seed=3)
    assert one == trial_plan(RECORD, [CANDIDATE], repetitions=3, seed=3)
    assert one != trial_plan(RECORD, [CANDIDATE], repetitions=3, seed=4)
    assert len({r["sample_id"] for r in one["schedule"]}) == one["planned_requests"] == 12
    for order in ORDERS:
        for label in ("control", "short"):
            assert sum(r["label"] == label and r["branch_order"] == order for r in one["schedule"]) == 3


@pytest.mark.parametrize("kwargs", [{"repetitions": 0}, {"repetitions": 6}, {"seed": True}])
def test_invalid_design_rejected(kwargs):
    with pytest.raises(ValueError):
        trial_plan(RECORD, [CANDIDATE], **kwargs)


def test_duplicate_sources_or_labels_cannot_count_as_independent_arms():
    for other in (replace(CANDIDATE, label="alias"), replace(CANDIDATE, source=RECORD["src"])):
        with pytest.raises(ValueError, match="unique"):
            trial_plan(RECORD, [CANDIDATE, other])
    with pytest.raises(ValueError, match="non-control"):
        trial_plan(RECORD, [replace(CANDIDATE, label="control")])


def test_identical_policy_outputs_are_explicit_and_still_get_fresh_processes(factory):
    candidates = [replace(CANDIDATE, label=label, source=RECORD["src"]) for label in ("local", "mapped")]
    plan = trial_plan(RECORD, candidates, allow_identical_sources=True)
    assert plan["schema"].endswith("/v2") and plan["distinct_source_count"] == 1
    assert not plan["independent_discoveries_claimed"]
    assert len({s["sample_id"] for s in plan["schedule"]}) == 12
    report = run_trial(RECORD, candidates, factory(), max_calls=12,
                       evidence_mode="offline_fixture", allow_identical_sources=True)
    assert report["verifier_invocations"] == 12 and report["status"] == "COMPLETE"
    assert all(o["heartbeat_result"] == "NO_CLEAR_DIFFERENCE" for o in report["observations"])
    with pytest.raises(ValueError, match="unique"):
        trial_plan(RECORD, [CANDIDATE, CANDIDATE], allow_identical_sources=True)
    with pytest.raises(ValueError, match="boolean"):
        trial_plan(RECORD, [CANDIDATE], allow_identical_sources=1)


def test_strictly_better_fixture_has_fresh_checks_not_cached_measurements(factory):
    report = trial(factory)
    assert report["status"] == "COMPLETE"
    assert report["requests_reserved"] == report["verifier_invocations"] == 8
    assert report["native_processes"] == report["live_model_calls"] == 0  # mocked, not real compilation
    assert report["receipt_cache_enabled"] is False
    assert report["official_score"] is report["local_combined_pct"] is None
    observation = report["observations"][0]
    assert observation["observed_pareto_improvement"] is True
    assert observation["heartbeat_result"] == "LOWER_IN_BOTH_ORDERS"
    assert observation["promoted"] is observation["statistical_significance_claimed"] is False
    assert all(s["verifier_invocations"] == 1 and s["receipt"] for s in report["samples"])
    # Repeated identical requests have the same content identity but distinct trial slots.
    controls = [s for s in report["samples"] if s["label"] == "control" and s["branch_order"] == ORDERS[0]]
    assert controls[0]["receipt"]["request_id"] == controls[1]["receipt"]["request_id"]
    assert controls[0]["sample_id"] != controls[1]["sample_id"]


def test_order_warming_alone_cannot_be_called_a_gain(factory):
    report = trial(factory, lambda payload, order, index: 1000 if order == "reference-first" else 9000)
    obs = report["observations"][0]
    assert obs["status"] == "MEASURED" and obs["candidate_tokens"] < obs["reference_tokens"]
    assert obs["heartbeat_result"] == "NO_CLEAR_DIFFERENCE"
    assert obs["observed_pareto_improvement"] is False


def test_shorter_slower_candidate_is_reported_as_a_tradeoff(factory):
    report = trial(factory, lambda p, *_: 1000 if p["candidate"] == p["reference"] else 5000)
    obs = report["observations"][0]
    assert obs["length_reduction_pct"] > 0
    assert obs["heartbeat_result"] == "REGRESSION_IN_AT_LEAST_ONE_ORDER"
    assert obs["observed_pareto_improvement"] is False


def test_longer_faster_proof_is_measured_not_rejected_for_length(factory):
    candidate = Candidate("longer", STATEMENT + " := by\n  have one : True := h\n  have two : True := one\n  exact id two",
                          "longer/faster synthetic fixture")
    report = run_trial(RECORD, [candidate], factory(), max_calls=8, evidence_mode="offline_fixture")
    obs = report["observations"][0]
    assert obs["status"] == "MEASURED" and obs["length_reduction_pct"] < 0
    assert obs["heartbeat_result"] == "LOWER_IN_BOTH_ORDERS"
    assert obs["observed_pareto_improvement"] is False


def test_improvement_in_only_one_order_is_not_pareto_claim(factory):
    def cost(p, order, _index):
        if p["candidate"] == p["reference"]: return 5000
        return 1000 if order == "reference-first" else 9000
    report = trial(factory, cost)
    assert report["observations"][0]["observed_pareto_improvement"] is False


def test_variation_larger_than_the_separation_is_inconclusive(factory):
    def cost(p, _order, index):
        return (10000 if index else 5000) if p["candidate"] == p["reference"] else 4900
    report = trial(factory, cost)
    assert report["observations"][0]["heartbeat_result"] == "NO_CLEAR_DIFFERENCE"


def test_one_repetition_cannot_establish_observed_range(factory):
    report = trial(factory, repetitions=1, max_calls=4)
    assert report["observations"][0]["heartbeat_result"] == "NO_CLEAR_DIFFERENCE"


@pytest.mark.parametrize("limit", [0, 1, 7, 8])
def test_zero_partial_and_exact_request_budgets(factory, limit):
    report = trial(factory, max_calls=limit)
    assert report["requests_reserved"] == report["verifier_invocations"] == limit
    assert sum(s["status"] == "BUDGET_EXHAUSTED" for s in report["samples"]) == 8 - limit
    assert report["status"] == ("COMPLETE" if limit == 8 else "INCOMPLETE")
    assert report["observations"][0]["observed_pareto_improvement"] == (True if limit == 8 else None)


def test_missing_required_version_never_looks_like_complete_compatibility(factory):
    record = {**RECORD, "version_info": [*RECORD["version_info"], {"v4.27.0": "c" * 40}]}
    report = run_trial(record, [CANDIDATE], factory(), max_calls=16, evidence_mode="offline_fixture")
    obs = report["observations"][0]
    assert report["status"] == obs["status"] == "INCOMPLETE"
    assert len(obs["verified_pins"]) == 1 and len(obs["required_pins"]) == 2
    assert obs["observed_pareto_improvement"] is None
    assert sum(s["status"] == "UNAVAILABLE" for s in report["samples"]) == 8


def test_invalid_candidate_is_not_submitted_or_promoted(factory):
    bad = Candidate("bad", STATEMENT + " := by sorry", "adversarial fixture")
    report = run_trial(RECORD, [bad], factory(), max_calls=8, evidence_mode="offline_fixture")
    assert report["verifier_invocations"] == 4 and report["requests_reserved"] == 8
    assert report["observations"][0]["status"] == "REJECTED"
    assert report["observations"][0]["observed_pareto_improvement"] is None


def test_transient_failure_is_neither_a_counterexample_nor_reused(factory, monkeypatch):
    verifiers = factory()
    calls, runner = [], native.run_native
    def transient(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1: raise TimeoutError()
        return runner(*args, **kwargs)
    monkeypatch.setattr(native, "run_native", transient)
    report = run_trial(RECORD, [CANDIDATE], verifiers, max_calls=8, evidence_mode="offline_fixture")
    assert len(calls) == 8
    assert sum(s["status"] == "TIMEOUT" for s in report["samples"]) == 1
    assert report["observations"][0]["status"] == "INCOMPLETE"


@pytest.mark.parametrize("error,status", [(subprocess.TimeoutExpired("git status", 10), "TIMEOUT"),
                                         (OSError("mount unavailable"), "ERROR"),
                                         (native.CapabilityGap("changed pin"), "UNAVAILABLE")])
def test_preparation_failure_retains_schedule_without_claiming_proof_attempts(factory, monkeypatch, error, status):
    verifiers = factory()
    def fail(*_args):
        raise error
    for verifier in verifiers.values():
        monkeypatch.setattr(verifier, "context", fail)
    report = run_trial(RECORD, [CANDIDATE], verifiers, max_calls=8, evidence_mode="offline_fixture")
    assert report["status"] == "INCOMPLETE" and len(report["samples"]) == 8
    assert report["requests_reserved"] == report["verifier_invocations"] == 0
    assert all(s["status"] == status and s["receipt"] is None for s in report["samples"])
    assert all(s["reason"].startswith("preparation:") for s in report["samples"])
    assert report["observations"][0]["observed_pareto_improvement"] is None


def test_preparation_cannot_supply_a_forged_success(factory):
    with pytest.raises(ValueError, match="non-success"):
        run_trial(RECORD, [CANDIDATE], factory(), setup_failures={(PIN, ORDERS[0]): ("VERIFIED", "forged")})


def test_cli_binding_timeout_writes_explicit_incomplete_report(tmp_path, monkeypatch, capsys):
    from jevops import arena_trial as trial_module
    record = {**RECORD, "url": "fixture://project"}
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps(record))
    projects = tmp_path / "projects.json"
    projects.write_text(json.dumps([{"repository": record["url"], **PIN.to_dict()}]))
    output = tmp_path / "timeout.json"
    monkeypatch.setattr(trial_module, "readiness", lambda *_: {"rows": [{**PIN.to_dict(), "status": "UNMEASURED"}]})
    def fail(*_args):
        raise subprocess.TimeoutExpired("git status", 10)
    monkeypatch.setattr(trial_module, "project_binding", fail)
    monkeypatch.setattr(sys, "argv", ["trial", "--run", "--problem", "example", "--corpus", str(corpus),
                                    "--projects", str(projects), "--max-calls", "8", "--output", str(output)])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report == json.loads(capsys.readouterr().out)
    assert report["status"] == "INCOMPLETE" and report["native_processes"] == 0
    assert all(s["status"] == "TIMEOUT" for s in report["samples"])


def test_failed_control_prevents_a_complete_experiment(factory, monkeypatch):
    verifiers = factory()
    runner = native.run_native
    def reject_control(binding, payload, **kwargs):
        data, exit_code = runner(binding, payload, **kwargs)
        if payload["candidate"] == payload["reference"]:
            data["report"]["outcome"] = "REJECTED"
        return data, exit_code
    monkeypatch.setattr(native, "run_native", reject_control)
    report = run_trial(RECORD, [CANDIDATE], verifiers, max_calls=8, evidence_mode="offline_fixture")
    assert report["status"] == report["observations"][0]["status"] == "INCOMPLETE"
    assert report["observations"][0]["observed_pareto_improvement"] is None


def test_different_order_contexts_cannot_be_compared(factory):
    verifiers = factory()
    verifiers[PIN, ORDERS[0]].timeout = 33
    with pytest.raises(ValueError, match="identical dependencies"):
        run_trial(RECORD, [CANDIDATE], verifiers, max_calls=8)


def test_old_verifier_work_cannot_be_relabelled_as_new_trials(factory):
    verifiers = factory()
    verifiers[PIN, ORDERS[0]].processes = 1
    with pytest.raises(ValueError, match="fresh verifier"):
        run_trial(RECORD, [CANDIDATE], verifiers)


def test_changed_context_mid_trial_does_not_keep_measurements_applicable(factory, monkeypatch):
    verifiers = factory()
    runner = native.run_native
    def change(*args, **kwargs):
        result = runner(*args, **kwargs)
        monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("changed epoch"))
        return result
    monkeypatch.setattr(native, "run_native", change)
    report = run_trial(RECORD, [CANDIDATE], verifiers, max_calls=8, evidence_mode="offline_fixture")
    assert all(s["status"] == "ERROR" for s in report["samples"])
    assert report["verifier_invocations"] == 1


def test_proposals_reuse_transforms_without_touching_the_known_statement_boundary():
    record = {**RECORD, "statement": "theorem t (n : Nat := by exact 1) : n = n",
              "src": "theorem t (n : Nat := by exact 1) : n = n := by\n  have unused : True := by trivial\n  rfl"}
    result = proposals(record, ["proof_slice"], cap=2)
    assert result and all(c.source.startswith(record["statement"] + " := by") for c in result)
    assert all("heuristic" in c.provenance for c in result)
    assert proposals(record, ["proof_slice"], cap=0) == []
    with pytest.raises(ValueError): proposals(record, ["run_code"])


def test_unused_have_slicing_preserves_required_case_bodies_and_explicit_uses():
    body = ("  have h : True := by trivial\n"
            "  have helper : True := h\n"
            "  have spare : True := by trivial\n"
            "  cases helper\n"
            "  case intro =>\n"
            "    trivial")
    record = {**RECORD, "src": STATEMENT + " := by\n" + body}
    candidates = proposals(record, ["proof_slice_unused_have"], cap=8)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert "have spare" not in candidate.source
    assert "have h :" in candidate.source and "have helper :" in candidate.source
    assert "case intro =>\n    trivial" in candidate.source
    assert candidate.source.startswith(STATEMENT + " := by\n")
    assert "existing deterministic heuristic" in candidate.provenance
    assert proposals(record, ["proof_slice_unused_have"], cap=0) == []


@pytest.mark.parametrize("tail", ["  assumption", "  simp_all"])
def test_unused_have_is_a_proposal_not_proof_of_semantic_independence(tail):
    record = {**RECORD, "src": STATEMENT + " := by\n  have needed : True := h\n" + tail}
    candidates = proposals(record, ["proof_slice_unused_have"])
    assert len(candidates) == 1  # Context-sensitive tactics may still need it.
    assert candidates[0].source.endswith(tail)
    assert "heuristic" in candidates[0].provenance


@pytest.mark.parametrize("body", ["  have h : True := by\n    trivial\n  trivial",
                                 "  have h : True := by trivial -- comment\n  trivial"])
def test_unused_have_cuts_do_not_treat_multiline_or_opaque_text_as_single_line(body):
    record = {**RECORD, "src": STATEMENT + " := by\n" + body}
    assert proposals(record, ["proof_slice_unused_have"]) == []


def test_cli_plan_is_offline_and_does_not_overwrite_evidence(tmp_path, monkeypatch, capsys):
    record = {**RECORD, "url": "fixture://project", "file_path": "Main.lean"}
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps(record))
    output = tmp_path / "plan.json"
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("plan must not run Lean"))
    monkeypatch.setattr(sys, "argv", ["trial", "--plan", "--problem", "example", "--corpus", str(corpus),
                                    "--output", str(output)])
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_text())
    assert report["native_processes"] == 0 and report["status"] == "PLANNED"
    with pytest.raises(SystemExit): main()


@pytest.mark.parametrize("invalid", [None, "target", "authority_field"])
def test_cli_explicit_drafts_are_not_mislabeled_as_historical_successes(tmp_path, monkeypatch, capsys, invalid):
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps(RECORD))
    draft = {"name": RECORD["name"], "label": "repair", "source": CANDIDATE.source,
             "provenance": "manual diagnostic-guided draft; not yet verified"}
    if invalid == "target": draft["name"] = "different"
    if invalid == "authority_field": draft["theorem_ok"] = True
    artifact = tmp_path / "draft.json"; artifact.write_text(json.dumps(draft))
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("plan must not run Lean"))
    monkeypatch.setattr(sys, "argv", ["trial", "--plan", "--problem", "example", "--corpus", str(corpus),
                                    "--candidate", str(artifact)])
    if invalid:
        with pytest.raises(SystemExit): main()
    else:
        assert main() == 0
        report = json.loads(capsys.readouterr().out)
        assert report["native_processes"] == 0 and report["arms"][1]["provenance"] == draft["provenance"]
        assert "historical" not in report["arms"][1]["provenance"]


@pytest.mark.parametrize("filename,calls,tokens,candidate_outcome", [
    ("native-controlled-strata-2026-09-22.json", 12, [237, 289], "VERIFIED"),
    ("native-controlled-core-2026-09-22.json", 36, [213, 219], "REJECTED"),
    ("native-controlled-core-repair-2026-09-22.json", 24, [216], "VERIFIED"),
])
def test_historical_native_trial_preserves_design_and_request_bindings(filename, calls, tokens, candidate_outcome):
    """Bookkeeping audit of saved observations, not fresh Lean verification."""
    from jevops.arena import ArenaContext, VerificationRequest, source_hash
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "papers/completion/lean_refactor_arena/evidence" / filename).read_text())
    candidates = [Candidate(**arm) for arm in report["arms"][1:]]
    plan = trial_plan(report["record"], candidates, repetitions=report["repetitions"], seed=report["seed"])
    assert plan["plan_id"] == report["plan_id"] and plan["schedule"] == report["schedule"]
    assert len({s["sample_id"] for s in report["samples"]}) == report["native_processes"] == calls
    contexts = {}
    for value in report["contexts"]:
        context = ArenaContext(**{**value, "versions": tuple(VersionPin(**p) for p in value["versions"]),
                                  "dependency_digests": tuple(value["dependency_digests"]),
                                  "allowed_axioms": tuple(value["allowed_axioms"])})
        contexts[context.context_id] = context
    arms = {arm["label"]: arm["source"] for arm in report["arms"]}
    for sample in report["samples"]:
        context = contexts[sample["context_id"]]
        source = arms[sample["label"]]
        request = VerificationRequest(context, source, VersionPin(**sample["version"]))
        assert request.request_id == sample["receipt"]["request_id"]
        assert sample["source_sha256"] == sample["receipt"]["candidate_sha256"] == source_hash(source)
        assert sample["status"] == sample["receipt"]["outcome"] == (
            "VERIFIED" if sample["label"] == "control" else candidate_outcome)
        assert sample["verifier_invocations"] == 1
        assert json.loads(sample["receipt"]["observations_json"])["branch_order"] == sample["branch_order"]
    assert report["live_model_calls"] == 0 and report["official_score"] is None
    assert report["receipt_cache_enabled"] is False
    assert [obs["candidate_tokens"] for obs in report["observations"]] == tokens
    assert all(obs["promoted"] is False for obs in report["observations"])
    if candidate_outcome == "REJECTED":
        assert all(obs["observed_pareto_improvement"] is None and not obs["verified_pins"]
                   for obs in report["observations"])
    if filename == "native-controlled-core-repair-2026-09-22.json":
        draft = json.loads((root / "papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json").read_text())
        assert report["arms"][1]["source"] == draft["source"]
        obs = report["observations"][0]
        assert obs["observed_pareto_improvement"] is True
        assert len(obs["verified_pins"]) == 3 and len(obs["strata"]) == 6
        assert all(s["candidate_median_raw"] < s["control_median_raw"] for s in obs["strata"])
