"""Fresh two-phase selection; fixture counts are explicitly not native evidence."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from jevops import arena_lean as native
from jevops import arena_pareto as pareto
from jevops.arena import ArenaContext, VerificationRequest, content_hash, reference_tokens, source_hash
from jevops.arena_trial import Candidate, ORDERS
from jevops.lean import VersionPin

PIN = VersionPin("v4.26.0", "a" * 40)
STATEMENT = "theorem selection_example (h : True) : True"
SOURCE = STATEMENT + " := by\n  have one : True := h\n  have two : True := one\n  exact two"
RECORD = {"name": "selection_example", "statement": STATEMENT, "src": SOURCE,
          "version_info": [{PIN.lean_tag: PIN.git_commit}]}
SHORT = Candidate("short", STATEMENT + " := by exact h", "offline test draft")
MEDIUM = Candidate("medium", STATEMENT + " := by exact id h", "offline test draft")
LONG = Candidate("long", SOURCE.replace("exact two", "exact id two"), "offline test draft")


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture deps"))
    def make(cost=None, modify=None, missing=()):
        phases, calls, batches = [], [], []
        def create(phase, limit):
            phases.append(phase)
            counts = {}
            def runner(binding, payload, **_kwargs):
                order = "candidate-first" if payload["candidate_first"] else "reference-first"
                key = (binding.pin, order, payload["candidate"])
                index = counts.get(key, 0); counts[key] = index + 1
                calls.append((phase, binding.pin, order, payload["candidate"], index))
                raw = cost(phase, payload, order, index, binding.pin) if cost else (
                    10000 if payload["candidate"] == payload["reference"] else 5000)
                data = {"schema": "jevops-native-arena/v1", "request_id": payload["request_id"],
                    "target": payload["target"], "measurement": native.METHOD,
                    "lean_version": binding.pin.lean_tag.removeprefix("v"), "lean_githash": "b" * 40,
                    "branch_order": order, "report": {"outcome": "VERIFIED", "type_preserved": True,
                        "target_absent_before": True, "axioms": [], "reference_axioms": [],
                        "raw_heartbeats": raw, "heartbeats": raw // 1000,
                        "reference_raw_heartbeats": 10000, "reference_heartbeats": 10, "diagnostics": []}}
                if modify:
                    modify(phase, payload, data)
                return data, 0
            monkeypatch.setattr(native, "run_native", runner)
            verifiers = {}
            for pin in (PIN, VersionPin("v4.27.0", "c" * 40)):
                if pin in missing:
                    continue
                # A second pin is included only when the factory explicitly requests it.
                if pin != PIN and not getattr(create, "two_pins", False):
                    continue
                binding = native.ProjectBinding(pin, tmp_path / "lean", tmp_path, "", project_backed=False)
                for order in ORDERS:
                    verifiers[pin, order] = native.NativeLeanVerifier({pin: binding}, max_processes=limit,
                                                                      branch_order=order)
            batches.append(verifiers)
            return verifiers, {}
        create.phases, create.calls, create.batches = phases, calls, batches
        return create
    return make


def run(factory, candidates=(SHORT,), **kwargs):
    return pareto.run_selection(RECORD, candidates, factory, max_calls=kwargs.pop("max_calls", 32),
                                evidence_mode="offline_fixture", **kwargs)


def test_plan_has_full_budget_and_separate_frozen_confirmation_seed():
    plan = pareto.selection_plan(RECORD, [SHORT])
    assert plan["screen"]["planned_requests"] == 8
    assert plan["confirmation_request_reserve"] == 12
    assert plan["required_request_budget"] == 20
    assert plan["confirmation_seed"] == 18
    assert plan == pareto.selection_plan(RECORD, [SHORT])
    assert plan["retries"] == plan["confirmation_alternatives"] == 0


@pytest.mark.parametrize("kwargs", [{"seed": True}, {"seed": -1}, {"repetitions": 1},
                                  {"confirmation_repetitions": 1}, {"confirmation_repetitions": 6},
                                  {"incumbent": "source"}])
def test_invalid_plan_rejected_before_work(kwargs):
    with pytest.raises(ValueError):
        pareto.selection_plan(RECORD, [SHORT], **kwargs)


@pytest.mark.parametrize("limit", [0, 19, 257, True])
@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_budget_reserves_confirmation_before_any_factory_call(factory, limit, objective):
    create = factory()
    with pytest.raises(ValueError, match="budget|integer"):
        run(create, max_calls=limit, selection_objective=objective)
    assert create.phases == []


def test_empty_duplicate_and_oversized_designs_are_rejected():
    for candidates in ([], [SHORT, SHORT], [replace(SHORT, label=str(i)) for i in range(9)]):
        with pytest.raises(ValueError):
            pareto.selection_plan(RECORD, candidates)
    record = {**RECORD, "version_info": [{f"v4.{i}.0": "c" * 40} for i in range(20, 28)]}
    with pytest.raises(ValueError, match="128-request"):
        pareto.selection_plan(record, [SHORT], repetitions=5)


def test_fresh_confirmation_is_not_cached_and_fixtures_never_recommend(factory):
    create = factory()
    report = run(create)
    assert create.phases == ["screen", "confirm"]
    assert report["status"] == "FIXTURE_CONFIRMED"
    assert report["selected_for_confirmation"] == "short"
    assert report["selection_commitment"]
    assert report["requests_reserved"] == report["verifier_invocations"] == len(create.calls) == 20
    assert report["native_processes"] == 0
    assert report["recommended"] is None and report["promoted"] is False
    assert report["training_enabled"] is False and report["official_score"] is None
    assert all(t["receipt_cache_enabled"] is False for t in (report["screen"], report["confirmation"]))
    assert {id(v) for v in create.batches[0].values()}.isdisjoint(id(v) for v in create.batches[1].values())


def test_shorter_slower_is_kept_on_frontier_not_selected(factory):
    create = factory(lambda phase, p, *_: 10000 if p["candidate"] == SOURCE else 20000)
    report = run(create)
    assert report["status"] == "NO_IMPROVEMENT" and create.phases == ["screen"]
    assert report["screen_analysis"]["frontier"] == ["control", "short"]


def test_longer_faster_is_kept_on_frontier_not_selected(factory):
    report = run(factory(), candidates=[LONG])
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["screen_analysis"]["frontier"] == ["control", "long"]


def test_exact_equal_heartbeats_with_shorter_tokens_is_eligible(factory):
    report = run(factory(lambda *_: 10000))
    assert report["status"] == "FIXTURE_CONFIRMED"


def test_equal_tokens_with_lower_heartbeats_is_eligible(factory):
    same_length = Candidate("same-length", SOURCE.replace("exact two", "exact one"), "fixture")
    report = run(factory(), candidates=[same_length])
    assert report["status"] == "FIXTURE_CONFIRMED"


def test_strict_dual_is_opt_in_and_bound_into_plan_and_confirmation(factory):
    legacy = pareto.selection_plan(RECORD, [SHORT])
    strict = pareto.selection_plan(RECORD, [SHORT], selection_objective="strict-dual-v1")
    floor = pareto.selection_plan(RECORD, [SHORT], selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=10)
    assert legacy["selection_objective"] == "pareto-v1" and legacy["policy"] == pareto.POLICY
    assert strict["policy"] == pareto.STRICT_DUAL_POLICY
    assert len({p["plan_id"] for p in (legacy, strict, floor)}) == 3
    assert all(p["required_request_budget"] == 20 for p in (legacy, strict, floor))
    report = run(factory(), selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=10)
    assert report["status"] == "FIXTURE_CONFIRMED"
    assert report["plan"] == floor
    for phase in ("screen", "confirmation"):
        analysis = report[phase + "_analysis"]
        assert analysis["selection_objective"] == "strict-dual-v1"
        assert analysis["heartbeat_noise_floor_raw"] == 10
        assert analysis["selected"] == "short"
    assert report["recommended"] is None and report["promoted"] is False
    assert report["native_processes"] == 0
    assert "Selection objective: strict-dual-v1; heartbeat noise floor: 10 raw units." in pareto.summary(report)


@pytest.mark.parametrize("cost", [5000, 10000, 15000])
@pytest.mark.parametrize("shape", ["shorter", "same", "longer"])
def test_strict_dual_requires_both_costs_to_improve(factory, shape, cost):
    candidate = {"shorter": SHORT, "same": Candidate("same", SOURCE.replace("exact two", "exact one"), "fixture"),
                 "longer": LONG}[shape]
    create = factory(lambda phase, p, *_: 10000 if p["candidate"] == SOURCE else cost)
    report = run(create, candidates=[candidate], selection_objective="strict-dual-v1")
    succeeds = shape == "shorter" and cost < 10000
    assert report["status"] == ("FIXTURE_CONFIRMED" if succeeds else "NO_IMPROVEMENT")
    assert create.phases == (["screen", "confirm"] if succeeds else ["screen"])
    assert report["recommended"] is None
    if not succeeds:
        assert report["retained_incumbent"] == "control"
        assert report["retained_incumbent_verified"] is True


def test_strict_dual_retains_discovery_frontier_without_admitting_equal_costs(factory):
    report = run(factory(lambda *_: 10000), selection_objective="strict-dual-v1")
    assert report["screen_analysis"]["frontier"] == ["short"]
    assert report["screen_analysis"]["eligible"] == []
    assert report["retained_incumbent"] == "control"


@pytest.mark.parametrize("axis", ["version", "order"])
def test_strict_dual_cannot_average_away_an_unchanged_stratum(factory, axis):
    record = {**RECORD, "version_info": [*RECORD["version_info"], {"v4.27.0": "c" * 40}]}
    def costs(phase, p, order, i, pin):
        if p["candidate"] == SOURCE or (pin != PIN if axis == "version" else order == "candidate-first"):
            return 10000
        return 5000
    create = factory(costs)
    create.two_pins = True
    report = pareto.run_selection(record, [SHORT], create, max_calls=40, evidence_mode="offline_fixture",
                                  selection_objective="strict-dual-v1")
    assert report["status"] == "NO_IMPROVEMENT" and report["confirmation"] is None


@pytest.mark.parametrize("dimension", ["tokens", "heartbeats"])
def test_strict_dual_must_improve_both_costs_over_incumbent_too(factory, dimension):
    incumbent = (Candidate("incumbent", STATEMENT + " := by exact h", "fixture")
                 if dimension == "tokens" else MEDIUM)
    candidate = (Candidate("candidate", STATEMENT + " := by exact h ", "distinct source, same tokens")
                 if dimension == "tokens" else SHORT)
    cost = {SOURCE: 10000, incumbent.source: 7000, candidate.source: 5000 if dimension == "tokens" else 7000}
    report = run(factory(lambda phase, p, *_: cost[p["candidate"]]), candidates=[candidate], incumbent=incumbent,
                 selection_objective="strict-dual-v1")
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["retained_incumbent"] == incumbent.label


def test_strict_dual_confirmation_cannot_relax_to_legacy_equal_heartbeats(factory):
    create = factory(lambda phase, p, *_: 5000 if phase == "screen" and p["candidate"] != SOURCE else 10000)
    report = run(create, selection_objective="strict-dual-v1")
    assert report["selected_for_confirmation"] == "short" and create.phases == ["screen", "confirm"]
    assert report["status"] == "UNCONFIRMED"
    assert report["recommended"] is None and report["retained_incumbent_verified"]


def test_strict_dual_must_improve_original_even_if_it_beats_incumbent(factory):
    costs = {SOURCE: 3000, MEDIUM.source: 5000, LONG.source: 10000}
    report = run(factory(lambda phase, p, *_: costs[p["candidate"]]), candidates=[MEDIUM], incumbent=LONG,
                 selection_objective="strict-dual-v1")
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["confirmation"] is None and report["retained_incumbent"] == "long"


@pytest.mark.parametrize("floor,expected", [(0, "FIXTURE_CONFIRMED"), (99, "FIXTURE_CONFIRMED"),
                                             (100, "NO_IMPROVEMENT"), (101, "NO_IMPROVEMENT")])
def test_predeclared_raw_noise_floor_is_a_strict_boundary(factory, floor, expected):
    report = run(factory(lambda phase, p, *_: 10000 if p["candidate"] == SOURCE else 9900),
                 selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=floor)
    assert report["status"] == expected


def test_noise_floor_is_applied_again_in_confirmation(factory):
    def costs(phase, p, *_):
        return 10000 if p["candidate"] == SOURCE else 9000 if phase == "screen" else 9900
    report = run(factory(costs), selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=100)
    assert report["status"] == "UNCONFIRMED" and report["recommended"] is None


def test_noise_floor_never_weakens_the_observed_variation_gate():
    assert pareto.heartbeat_relation([100, 150], [175, 175], noise_floor_raw=0) == "UNKNOWN"
    assert pareto.heartbeat_relation([100, 150], [175, 175], noise_floor_raw=10) == "UNKNOWN"


@pytest.mark.parametrize("kwargs", [{"selection_objective": "shortest"}, {"selection_objective": None},
    {"selection_objective": []}, *({"heartbeat_noise_floor_raw": bad} for bad in
        [True, -1, 1.5, "10", None, float("nan"), float("inf")])])
def test_invalid_selection_policy_is_rejected_before_reserving_work(factory, kwargs):
    create = factory()
    with pytest.raises(ValueError):
        run(create, **kwargs)
    assert create.phases == []


def test_noisy_overlap_is_not_treated_as_equal(factory):
    report = run(factory(lambda phase, p, order, i, pin: 10000 + i))
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["selected_for_confirmation"] is None


def test_regression_in_one_order_is_not_averaged_away(factory):
    report = run(factory(lambda phase, p, order, *_: 10000 if p["candidate"] == SOURCE else (
        1000 if order == "reference-first" else 11000)))
    assert report["status"] == "NO_IMPROVEMENT"


@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_missing_required_pin_prevents_selection(factory, objective):
    record = {**RECORD, "version_info": [*RECORD["version_info"], {"v4.27.0": "c" * 40}]}
    report = pareto.run_selection(record, [SHORT], factory(), max_calls=40, evidence_mode="offline_fixture",
                                  selection_objective=objective)
    assert report["status"] == "INCOMPLETE" and report["selected_for_confirmation"] is None
    assert report["confirmation"] is None


def test_every_required_pin_must_be_nonregressing(factory):
    record = {**RECORD, "version_info": [*RECORD["version_info"], {"v4.27.0": "c" * 40}]}
    create = factory(lambda phase, p, order, i, pin: 10000 if p["candidate"] == SOURCE else (
        5000 if pin == PIN else 15000))
    create.two_pins = True
    report = pareto.run_selection(record, [SHORT], create, max_calls=40, evidence_mode="offline_fixture")
    assert report["status"] == "NO_IMPROVEMENT"


def test_all_version_success_and_frontier_tie_break_are_order_independent(factory):
    alternate = Candidate("alternate", STATEMENT + " := by exact (h)", "fixture")
    def costs(phase, p, *_):
        return {SOURCE: 10000, SHORT.source: 5000, alternate.source: 3000}[p["candidate"]]
    first = run(factory(costs), candidates=[SHORT, alternate])
    second = run(factory(costs), candidates=[alternate, SHORT])
    assert first["selected_for_confirmation"] == second["selected_for_confirmation"]
    assert first["screen_analysis"]["frontier"] == second["screen_analysis"]["frontier"]


def test_improvement_over_original_is_not_enough_to_beat_current_incumbent(factory):
    create = factory(lambda phase, p, *_: {SOURCE: 10000, MEDIUM.source: 2000, SHORT.source: 5000}[p["candidate"]])
    report = run(create, incumbent=MEDIUM)
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["retained_incumbent"] == "medium"
    assert report["screen_analysis"]["frontier"] == ["medium", "short"]


def test_incumbent_and_original_are_rechecked_in_confirmation(factory):
    create = factory(lambda phase, p, *_: {SOURCE: 10000, MEDIUM.source: 7000, SHORT.source: 5000}[p["candidate"]])
    report = run(create, incumbent=MEDIUM, max_calls=30)
    assert report["status"] == "FIXTURE_CONFIRMED"
    assert report["verifier_invocations"] == 30
    assert {arm["label"] for arm in report["confirmation"]["arms"]} == {"control", "medium", "short"}


def test_fixed_winner_failure_does_not_retry_other_candidates(factory):
    def cost(phase, p, *_):
        if p["candidate"] == SOURCE:
            return 10000
        if p["candidate"] == SHORT.source:
            return 3000 if phase == "screen" else 15000
        return 5000
    create = factory(cost)
    report = run(create, candidates=[SHORT, MEDIUM])
    assert report["selected_for_confirmation"] == "short"
    assert report["status"] == "UNCONFIRMED"
    assert report["recommended"] is None and report["retained_incumbent"] == "control"
    assert all(source != MEDIUM.source for phase, pin, order, source, i in create.calls if phase == "confirm")
    assert len(create.calls) == 24


@pytest.mark.parametrize("kind", ["axiom", "sorry", "type", "target", "forged_request", "raw_boolean", "timeout"])
@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_bad_native_evidence_cannot_select(factory, kind, objective):
    def modify(phase, payload, data):
        if payload["candidate"] == SOURCE:
            return
        if kind == "axiom": data["report"]["axioms"] = ["extraAxiom"]
        if kind == "sorry": data["report"]["axioms"] = ["sorryAx"]
        if kind == "type": data["report"]["type_preserved"] = False
        if kind == "target": data["report"]["target_absent_before"] = False
        if kind == "forged_request": data["request_id"] = "bad"
        if kind == "raw_boolean": data["report"]["raw_heartbeats"] = True
        if kind == "timeout":
            data["report"].update(outcome="REJECTED", diagnostics=[{"message": "maximum number of heartbeats"}])
    report = run(factory(modify=modify), selection_objective=objective)
    assert report["selected_for_confirmation"] is report["recommended"] is None
    assert report["confirmation"] is None


@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_standard_axiom_expansion_is_not_allowed_even_within_allowlist(factory, objective):
    def modify(phase, p, data):
        if p["candidate"] != SOURCE:
            data["report"]["axioms"] = ["Classical.choice"]
    report = run(factory(modify=modify), selection_objective=objective)
    assert report["screen"]["status"] == "COMPLETE"  # verifier's fixed allowlist permits it
    assert report["screen_analysis"]["rows"]["short"]["reason"] == "axiom_expansion_over_reference"
    assert report["status"] == "NO_IMPROVEMENT"


def test_failure_of_one_alternative_is_retained_but_cannot_become_a_teacher(factory):
    bad = Candidate("bad", STATEMENT + " := by sorry", "adversarial fixture")
    report = run(factory(), candidates=[SHORT, bad])
    assert report["status"] == "FIXTURE_CONFIRMED"
    assert report["screen_analysis"]["rows"]["bad"]["admissible"] is False
    assert report["requests_reserved"] == 24 and report["verifier_invocations"] == 20
    assert report["training_enabled"] is False


def test_rejected_incumbent_is_not_reported_as_verified_fallback(factory):
    def modify(phase, p, data):
        if p["candidate"] == MEDIUM.source:
            data["report"]["outcome"] = "REJECTED"
    report = run(factory(modify=modify), incumbent=MEDIUM)
    assert report["status"] == "INCOMPLETE" and report["reason"] == "incumbent_not_admissible"
    assert report["retained_incumbent_verified"] is False


def test_axiom_elimination_in_incumbent_cannot_be_undone(factory):
    def modify(phase, p, data):
        data["report"]["reference_axioms"] = ["Classical.choice"]
        data["report"]["axioms"] = [] if p["candidate"] == MEDIUM.source else ["Classical.choice"]
    create = factory(lambda phase, p, *_: {SOURCE: 10000, MEDIUM.source: 7000, SHORT.source: 5000}[p["candidate"]], modify)
    report = run(create, incumbent=MEDIUM)
    assert report["screen_analysis"]["rows"]["short"]["admissible"]
    assert report["status"] == "NO_IMPROVEMENT"  # cannot expand incumbent's smaller axiom set


def test_equal_cost_ties_do_not_replace_incumbent(factory):
    candidate = Candidate("tie", SOURCE.replace("exact two", "exact one"), "fixture")
    report = run(factory(lambda *_: 10000), candidates=[candidate])
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["retained_incumbent_verified"] is True


def test_source_change_during_selection_cannot_recommend(factory, monkeypatch):
    create = factory()
    original = pareto._implementation()
    calls = []
    def stamp():
        calls.append(1)
        return original if len(calls) == 1 else {**original, "arena_pareto.py": "changed"}
    monkeypatch.setattr(pareto, "_implementation", stamp)
    report = run(create)
    assert report["status"] == "INCOMPLETE"
    assert report["reason"] == "implementation_changed_during_selection"
    assert report["recommended"] is None


def test_confirmation_rejection_is_not_rescued(factory):
    def modify(phase, p, data):
        if phase == "confirm" and p["candidate"] != SOURCE:
            data["report"]["outcome"] = "REJECTED"
    report = run(factory(modify=modify))
    assert report["status"] == "UNCONFIRMED" and report["recommended"] is None
    assert report["retained_incumbent_verified"] is True


def test_confirmation_timeout_is_incomplete_not_a_negative_label(factory):
    def modify(phase, p, data):
        if phase == "confirm" and p["candidate"] != SOURCE:
            data["report"].update(outcome="REJECTED", diagnostics=[{"message": "maximum number of heartbeats"}])
    report = run(factory(modify=modify))
    assert report["status"] == "INCOMPLETE" and report["recommended"] is None
    assert report["training_enabled"] is False


def test_incumbent_failure_during_confirmation_is_explicit(factory):
    def modify(phase, p, data):
        if phase == "confirm" and p["candidate"] == MEDIUM.source:
            data["report"]["outcome"] = "REJECTED"
    create = factory(lambda phase, p, *_: {SOURCE: 10000, MEDIUM.source: 7000, SHORT.source: 5000}[p["candidate"]], modify)
    report = run(create, incumbent=MEDIUM)
    assert report["status"] == "INCOMPLETE" and report["recommended"] is None
    assert report["reason"] == "confirmation_incumbent_not_admissible"
    assert report["retained_incumbent_verified"] is False


@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_policy_options_cannot_change_between_phases(factory, objective):
    create = factory()
    def changed(phase, limit):
        verifiers, failures = create(phase, limit)
        if phase == "confirm":
            for verifier in verifiers.values():
                verifier.max_heartbeats += 100
        return verifiers, failures
    report = run(changed, selection_objective=objective)
    assert report["status"] == "INCOMPLETE" and report["reason"] == "contexts_changed_between_phases"


@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_reused_verifier_cannot_supply_fresh_confirmation(factory, objective):
    create = factory()
    first = None
    def reused(phase, limit):
        nonlocal first
        if first is None:
            first = create(phase, limit)
        return first
    with pytest.raises(ValueError, match="new verifier"):
        run(reused, selection_objective=objective)


@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_environment_change_between_phases_invalidates_recommendation(factory, monkeypatch, objective):
    create = factory()
    def changed(phase, limit):
        if phase == "confirm":
            monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("changed deps"))
        return create(phase, limit)
    report = run(changed, selection_objective=objective)
    assert report["status"] == "INCOMPLETE" and report["recommended"] is None
    assert report["reason"] == "contexts_changed_between_phases"


def test_contexts_are_revalidated_after_the_last_sample(factory, monkeypatch):
    create = factory()
    original = pareto.run_trial
    def changed_after_trial(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("changed after trial"))
        return result
    monkeypatch.setattr(pareto, "run_trial", changed_after_trial)
    report = run(create)
    assert report["status"] == "INCOMPLETE" and report["confirmation"] is None
    assert report["reason"].startswith("final_context_validation")


def test_changed_confirmation_context_is_revalidated_after_last_sample(factory, monkeypatch):
    original = pareto.run_trial
    calls = []
    def changed_after_trial(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("late mutation"))
        return result
    monkeypatch.setattr(pareto, "run_trial", changed_after_trial)
    report = run(factory())
    assert report["status"] == "INCOMPLETE" and report["recommended"] is None
    assert report["reason"].startswith("final_context_validation")


def test_mutating_caller_record_cannot_change_the_frozen_experiment(factory):
    create = factory()
    record = {**RECORD, "version_info": list(RECORD["version_info"])}
    def mutated(phase, limit):
        if phase == "screen":
            record["src"] = SHORT.source
            record["version_info"].clear()
        return create(phase, limit)
    report = pareto.run_selection(record, [SHORT], mutated, max_calls=20, evidence_mode="offline_fixture")
    assert report["status"] == "FIXTURE_CONFIRMED"
    assert report["plan"]["screen"]["record"]["src"] == SOURCE
    assert report["plan"]["screen"]["record"]["version_info"] == RECORD["version_info"]


@pytest.mark.parametrize("left,right,want", [([1, 1], [5, 5], "LOWER"), ([5, 5], [1, 1], "HIGHER"),
    ([0, 0], [0, 0], "EQUAL"), ([4, 5], [5, 6], "UNKNOWN"), ([1], [2], "UNKNOWN"),
    ([1, 5], [6, 6], "UNKNOWN")])
def test_conservative_heartbeat_comparison(left, right, want):
    assert pareto.heartbeat_relation(left, right) == want


@pytest.mark.parametrize("bad", [True, -1, 2.5, float("nan")])
def test_heartbeat_comparison_rejects_noncounts(bad):
    with pytest.raises(ValueError):
        pareto.heartbeat_relation([bad, bad], [5, 5])


@pytest.mark.parametrize("objective", pareto.OBJECTIVES)
def test_cli_writes_small_stdout_and_programmatic_protocol_without_lean(tmp_path, monkeypatch, capsys, objective):
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps(RECORD))
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"name": RECORD["name"], **SHORT.__dict__}))
    out = tmp_path / "output"
    monkeypatch.setattr(native, "run_native", lambda *a, **kw: pytest.fail("offline plan"))
    monkeypatch.setattr(sys, "argv", ["pareto", "--plan", "--problem", RECORD["name"], "--corpus", str(corpus),
                                    "--candidate", str(draft), "--output-dir", str(out),
                                    "--selection-objective", objective, "--heartbeat-noise-floor-raw", "42"])
    assert pareto.main() == 0
    stdout = capsys.readouterr().out
    assert len(stdout) < 1000 and json.loads(stdout)["status"] == "PLANNED"
    plan = json.loads((out / "protocol.json").read_text())
    assert plan["required_request_budget"] == 20
    assert plan["selection_objective"] == objective and plan["heartbeat_noise_floor_raw"] == 42
    with pytest.raises(SystemExit): pareto.main()


def test_report_generator_does_not_claim_fixture_compilation(factory):
    report = run(factory())
    rendered = pareto.summary(report)
    assert "FIXTURE_CONFIRMED" in rendered and "native processes: 0" in rendered
    assert "No production promotion" in rendered


def test_historical_reports_still_render_with_the_original_policy(factory):
    report = run(factory())
    report["plan"].pop("selection_objective")
    report["plan"].pop("heartbeat_noise_floor_raw")
    assert "Selection objective: pareto-v1; heartbeat noise floor: 0 raw units." in pareto.summary(report)


@pytest.mark.parametrize("filename,input_kind,label,requests,tokens,axioms", [
    ("native-strict-dual-smoke-2026-09-22.json", "non_arena_stdlib_smoke", "exact-h", 20, (15, 3), set()),
    ("native-strict-dual-core-2026-09-23.json", "caller_supplied_corpus", "repair-Hlen2-induction-arity",
     48, (224, 216), {"Quot.sound", "propext", "Classical.choice"}),
])
def test_saved_strict_native_trials_preserve_receipt_and_plan_bindings(monkeypatch, filename, input_kind,
                                                                     label, requests, tokens, axioms):
    """Audit historical bookkeeping; neither re-execute nor admit its proof."""
    monkeypatch.setattr(native, "run_native", lambda *a, **kw: pytest.fail("historical bookkeeping only"))
    path = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence" / filename
    report = json.loads(path.read_text())
    plan = report["plan"]
    assert plan["plan_id"] == content_hash({k: v for k, v in plan.items() if k != "plan_id"})
    assert plan["selection_objective"] == "strict-dual-v1" and plan["heartbeat_noise_floor_raw"] == 0
    assert report["status"] == "CONFIRMED_LOCAL_IMPROVEMENT" and report["implementation_unchanged"]
    assert report["evidence_mode"] == "local_lean" and report["input_kind"] == input_kind
    assert report["native_processes"] == report["requests_reserved"] == report["verifier_invocations"] == requests
    assert report["live_model_calls"] == 0 and report["official_score"] is None
    assert report["promoted"] is False and report["training_enabled"] is False
    assert report["selection_commitment"] == content_hash({"plan_id": plan["plan_id"],
        "screen_sha256": content_hash(report["screen"]), "selected": report["recommended"]})
    assert report["screen"]["contexts"] == report["confirmation"]["contexts"]
    sample_ids = []
    for phase in ("screen", "confirmation"):
        trial = report[phase]
        assert trial["status"] == "COMPLETE" and trial["receipt_cache_enabled"] is False
        sources = {arm["label"]: arm["source"] for arm in trial["arms"]}
        contexts = {}
        for data in trial["contexts"]:
            ctx = ArenaContext(**{**data, "versions": tuple(VersionPin(**p) for p in data["versions"]),
                "dependency_digests": tuple(data["dependency_digests"]), "allowed_axioms": tuple(data["allowed_axioms"])})
            contexts[ctx.context_id] = ctx
        for slot, sample in zip(trial["schedule"], trial["samples"], strict=True):
            assert all(sample[key] == value for key, value in slot.items())
            assert sample["status"] == "VERIFIED" and sample["verifier_invocations"] == 1
            ctx = contexts[sample["context_id"]]
            source = sources[sample["label"]]
            request = VerificationRequest(ctx, source, VersionPin(**sample["version"]))
            receipt = sample["receipt"]
            assert receipt["request_id"] == request.request_id
            assert receipt["candidate_sha256"] == sample["source_sha256"] == source_hash(source)
            assert receipt["outcome"] == "VERIFIED" and receipt["target"] == trial["record"]["name"]
            assert receipt["type_preserved"] and receipt["exit_code"] == 0
            observation = json.loads(receipt["observations_json"])
            assert observation["measurement"] == native.METHOD
            assert observation["branch_order"] == sample["branch_order"]
            assert observation["report"]["raw_heartbeats"] == sample["raw_heartbeats"]
            assert observation["report"]["type_preserved"] and observation["report"]["target_absent_before"]
            assert set(observation["report"]["axioms"]) == set(observation["report"]["reference_axioms"]) == axioms
            sample_ids.append(sample["sample_id"])
        analysis = pareto._analysis(trial, "control", [label], selection_objective="strict-dual-v1")
        assert analysis == report[phase + "_analysis"] and analysis["selected"] == label
        assert reference_tokens(sources["control"], trial["record"]["statement"]) == tokens[0]
        assert reference_tokens(sources[label], trial["record"]["statement"]) == tokens[1]
        assert sources[label] == report["recommended"]["source"]
    assert len(set(sample_ids)) == len(sample_ids) == requests


def test_cli_run_preserves_missing_infrastructure_as_incomplete(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps({**RECORD, "url": "fixture://project"}))
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"name": RECORD["name"], **SHORT.__dict__}))
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["pareto", "--run", "--problem", RECORD["name"], "--corpus", str(corpus),
        "--candidate", str(draft), "--output-dir", str(out), "--max-calls", "20", "--elan-home", str(tmp_path)])
    monkeypatch.setattr(native, "run_native", lambda *a, **kw: pytest.fail("no prepared projects"))
    assert pareto.main() == 2
    assert len(capsys.readouterr().out) < 1000
    report = json.loads((out / "report.json").read_text())
    assert report["status"] == "INCOMPLETE" and report["native_processes"] == 0
    assert (out / "summary.md").is_file()


def test_cli_plans_fresh_verification_for_repaired_drafts_not_saved_success(tmp_path, monkeypatch, capsys):
    root = Path(__file__).resolve().parents[1]
    hints = root / "papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json"
    out = tmp_path / "repaired-plan"
    monkeypatch.setattr(native, "run_native", lambda *a, **kw: pytest.fail("plan must be offline"))
    monkeypatch.setattr(sys, "argv", ["pareto", "--plan", "--problem", "Core.InitsUpdatesComm",
        "--repair-from-trial", str(hints), "--output-dir", str(out), "--selection-objective", "strict-dual-v1",
        "--repetitions", "2", "--confirmation-repetitions", "2"])
    assert pareto.main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response["native_processes"] == 0 and response["required_request_budget"] == 48
    plan = json.loads((out / "protocol.json").read_text())
    assert len(plan["screen"]["arms"]) == 2
    assert "unverified" in plan["screen"]["arms"][1]["provenance"]
    assert not (out / "report.json").exists()
    assert plan["confirmation_request_reserve"] == 24


def test_cli_rejects_malformed_repair_report_before_creating_output(tmp_path, monkeypatch):
    hints = tmp_path / "bad.json"
    hints.write_text("[]")
    out = tmp_path / "bad-repair"
    monkeypatch.setattr(sys, "argv", ["pareto", "--plan", "--problem", "Core.InitsUpdatesComm",
        "--repair-from-trial", str(hints), "--output-dir", str(out)])
    with pytest.raises(SystemExit):
        pareto.main()
    assert not out.exists()


@pytest.mark.parametrize("field", ["theorem_ok", "heartbeats", "confidence", "selection_objective", "heartbeat_noise_floor_raw"])
def test_draft_authority_fields_are_rejected(tmp_path, field):
    path = tmp_path / "draft.json"
    path.write_text(json.dumps({"name": RECORD["name"], **SHORT.__dict__, field: True}))
    with pytest.raises(ValueError, match="only"):
        pareto._draft(path, RECORD["name"])


@pytest.mark.parametrize("flag,value", [("--timeout", "nan"), ("--timeout", "0"), ("--max-calls", "-1"),
    ("--selection-objective", "shortest"), ("--heartbeat-noise-floor-raw", "-1"), ("--heartbeat-noise-floor-raw", "nan")])
def test_cli_rejects_invalid_resource_limits_before_creating_reports(tmp_path, monkeypatch, flag, value):
    out = tmp_path / "bad"
    monkeypatch.setattr(sys, "argv", ["pareto", "--smoke", "--output-dir", str(out), flag, value])
    with pytest.raises(SystemExit):
        pareto.main()
    assert not out.exists()
