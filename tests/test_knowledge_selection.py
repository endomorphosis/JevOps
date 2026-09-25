"""Selection protocol fixtures: synthetic counts are never native evidence."""
import json

import pytest

pytest.importorskip("duckdb")
from jevops import arena_lean as native
from jevops.arena import content_hash
from jevops.arena_trial import Candidate
from jevops.knowledge_selection import compact_selection_plan, run_compact_selection, render_summary
from tests.test_knowledge_materialize import experiment, run as materialize
from tests.test_knowledge_lookup import setup, STATEMENT, SOURCE

pytestmark = pytest.mark.no_seal(reason="fresh compact-term selection and adversarial nomination checks")


def seal(report):
    report["report_sha256"] = content_hash({k: v for k, v in report.items() if k != "report_sha256"})
    return report


@pytest.fixture
def study(experiment, monkeypatch):
    s = experiment
    s.report = materialize(s)
    s.calls.clear()
    s.phases, s.batches, s.costs = [], [], {}
    s.phase, s.phase_failures = None, {}
    original = native.run_native
    def runner(binding, payload, **kwargs):
        data, code = original(binding, payload, **kwargs)
        raw = s.costs.get((s.phase, payload["candidate"]), s.costs.get(payload["candidate"]))
        if raw is not None:
            data["report"].update(raw_heartbeats=raw, heartbeats=raw // 1000)
        if payload["candidate"] != payload["reference"] and s.phase in s.phase_failures:
            data["report"]["outcome"] = s.phase_failures[s.phase]
        return data, code
    monkeypatch.setattr(native, "run_native", runner)
    def factory(phase, limit):
        s.phase = phase
        s.phases.append(phase)
        batch = s.verifiers()
        for guard in batch.values():
            guard.max_processes = limit
        s.batches.append(batch)
        return batch, {}
    s.factory = factory
    return s


def plan(s, **kwargs):
    return compact_selection_plan(s.report, record=s.inputs["record"], context=s.inputs["context"], **kwargs)


def run(s, frozen=None, incumbent=None, **kwargs):
    frozen = plan(s, incumbent=incumbent) if frozen is None else frozen
    options = dict(record=s.inputs["record"], incumbent=incumbent, verifier_factory=s.factory,
                   max_calls=frozen["required_request_budget"])
    return run_compact_selection(frozen, s.report, **{**options, **kwargs})


def test_fresh_two_phase_pipeline_preserves_original_and_disables_learning(study):
    s = study
    frozen = plan(s)
    assert frozen["status"] == "READY" and frozen["required_request_budget"] == 40
    assert frozen["selection"]["selection_objective"] == "strict-dual-v1"
    assert frozen["record"]["src"] == SOURCE != s.report["plan"]["seed"]
    assert not s.phases and not s.calls
    result = run(s, json.loads(json.dumps(frozen)))
    assert s.phases == ["screen", "confirm"]
    assert len(s.calls) == result["verifier_invocations"] == 40
    assert result["status"] == "FIXTURE_CONFIRMED" and result["recommended"] is None
    assert result["native_processes"] == 0 and result["official_score"] is None
    assert not result["training_enabled"] and not result["promoted"]
    assert all(not result["selection"][phase]["receipt_cache_enabled"] for phase in ("screen", "confirmation"))
    assert set(map(id, s.batches[0].values())).isdisjoint(map(id, s.batches[1].values()))
    assert "fewer tokens AND lower heartbeats" in render_summary(result)


@pytest.mark.parametrize("body", ["_root_.Z_good", "_root_.Other"])
def test_one_token_incumbent_cannot_be_beaten_by_a_one_token_nomination(study, body):
    s = study
    current = Candidate("best", STATEMENT + " := " + body, "caller current incumbent")
    result = run(s, incumbent=current)
    assert result["status"] == "NOT_SHORTER_THAN_INCUMBENT"
    assert result["plan"]["tokens"]["candidate"] == result["plan"]["tokens"]["incumbent"] == 1
    assert not s.phases and not s.calls
    assert not result["retained_incumbent_verified"] and result["recommended"] is None


def test_equal_reference_is_not_a_win_even_with_a_worse_current_incumbent(study):
    s = study
    s.report["candidate"] = SOURCE
    seal(s.report)
    current = Candidate("best", SOURCE.replace("exact ⟨", "exact id ⟨"), "synthetic longer incumbent")
    result = run(s, incumbent=current)
    assert result["status"] == "NOT_SHORTER_THAN_REFERENCE" and not s.phases


def test_distinct_incumbent_is_a_fresh_control_not_the_reference_denominator(study):
    s = study
    current = Candidate("best", STATEMENT + " := by exact _root_.Z_good\n", "current incumbent")
    s.costs[current.source] = 6000
    result = run(s, incumbent=current)
    assert result["plan"]["required_request_budget"] == 60 and len(s.calls) == 60
    assert result["status"] == "FIXTURE_CONFIRMED"
    for phase in ("screen", "confirmation"):
        rows = result["selection"][phase + "_analysis"]["rows"]
        assert rows["compact"]["tokens"] < rows["incumbent"]["tokens"] < rows["control"]["tokens"]
    assert result["retained_incumbent"]["source"] == current.source


def test_explicit_reference_incumbent_is_deduplicated_without_losing_binding(study):
    current = Candidate("best", SOURCE, "reference is current best")
    result = run(study, incumbent=current)
    assert result["plan"]["incumbent"]["label"] == "best"
    assert result["plan"]["selection"]["incumbent_label"] == "control"
    assert len(study.calls) == 40


@pytest.mark.parametrize("damage", ["reference", "statement", "incumbent", "plan", "report", "missing_pin", "options", "used_guard"])
def test_changes_fail_before_native_work(study, damage):
    s = study
    frozen, options = plan(s), {}
    if damage in {"reference", "statement"}:
        options["record"] = {**s.inputs["record"], "src" if damage == "reference" else "statement": "changed"}
    elif damage == "incumbent": options["incumbent"] = Candidate("changed", SOURCE, "different provenance")
    elif damage == "plan": frozen["tokens"]["candidate"] = 0
    elif damage == "report": s.report["candidate"] += " "
    else:
        batch = s.verifiers(timeout=61) if damage == "options" else s.verifiers()
        if damage == "missing_pin": batch.pop(next(iter(batch)))
        if damage == "used_guard": next(iter(batch.values())).processes = 1
        options["verifier_factory"] = lambda *_: (batch, {})
    with pytest.raises(ValueError): run(s, frozen, **options)
    assert not s.calls


@pytest.mark.parametrize("limit", [0, 39, 41, True])
def test_exact_budget_is_reserved_before_factory(study, limit):
    with pytest.raises(ValueError, match="budget"): run(study, max_calls=limit)
    assert not study.phases


@pytest.mark.parametrize("phase", ["screen", "confirm"])
@pytest.mark.parametrize("outcome", ["REJECTED", "TIMEOUT", "ERROR", "UNAVAILABLE"])
def test_failures_cannot_be_overridden_by_rehashed_historical_success(study, phase, outcome):
    s = study
    s.report.update(status="CHECKED_DRAFT", proof_verified=True)  # adversarial historical claim, not evidence
    seal(s.report)
    s.phase_failures[phase] = outcome
    result = run(s)
    assert result["recommended"] is None
    assert result["status"] not in {"FIXTURE_CONFIRMED", "CONFIRMED_LOCAL_IMPROVEMENT"}
    assert s.phases == (["screen"] if phase == "screen" else ["screen", "confirm"])


@pytest.mark.parametrize("heartbeat", [3000, 9000, 12000])
def test_shorter_term_cannot_tie_or_regress_incumbent_heartbeats(study, heartbeat):
    s = study
    current = Candidate("best", STATEMENT + " := by exact _root_.Z_good", "incumbent")
    s.costs[current.source] = 3000
    s.costs[s.report["candidate"]] = heartbeat
    result = run(s, incumbent=current)
    assert result["status"] == "NO_IMPROVEMENT" and s.phases == ["screen"]


def test_no_candidate_has_no_fabricated_fallback_or_verification(study):
    s = study
    s.report.update(candidate=None, status="NOT_AN_APPLICATION", proof_verified=False)
    seal(s.report)
    result = run(s)
    assert result["status"] == "NO_CANDIDATE" and result["plan"]["required_request_budget"] == 0
    assert not s.phases and not result["retained_incumbent_verified"]


@pytest.mark.parametrize("options", [{"repetitions": True}, {"confirmation_repetitions": 1}, {"seed": -1},
                                    {"heartbeat_noise_floor_raw": -1}, {"incumbent": "untyped"}])
def test_invalid_options_rejected_even_on_abstention(study, options):
    study.report.update(candidate=None, status="NOT_AN_APPLICATION")
    seal(study.report)
    with pytest.raises(ValueError): plan(study, **options)
    assert not study.calls


def test_statement_drift_in_rehashed_nomination_is_rejected(study):
    study.report["candidate"] = "theorem sample : True := True.intro"
    seal(study.report)
    with pytest.raises(ValueError, match="statement/intake"): plan(study)


def test_confirmation_environment_drift_cannot_recommend(study):
    s = study
    original = s.factory
    def factory(phase, limit):
        return (s.verifiers(timeout=61), {}) if phase == "confirm" else original(phase, limit)
    with pytest.raises(ValueError, match="exact discovery environment"):
        run(s, verifier_factory=factory)
    assert len(s.calls) == 16
