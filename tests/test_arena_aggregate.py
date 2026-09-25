"""Synthetic score controls; no model calls or native Lean evidence."""
import copy
from fractions import Fraction
import json
from pathlib import Path

import pytest

from jevops import arena_pareto as pareto
from jevops.arena import reference_tokens
from jevops.arena_report_audit import audit_report
from jevops.lean import VersionPin
from tests.test_arena_pareto import factory, run, RECORD, SOURCE, SHORT, MEDIUM, LONG, PIN

MODE = "aggregate-local-v1"


def comparison(report, candidate="long", control="original", phase="screen"):
    return report[phase + "_analysis"]["aggregate_comparisons"][candidate][control]


def test_opt_in_longer_faster_is_selected_and_freshly_confirmed(factory):
    create = factory()
    report = run(create, candidates=[LONG], selection_objective=MODE)
    assert report["status"] == "FIXTURE_CONFIRMED"
    assert report["selected_for_confirmation"] == "long"
    assert create.phases == ["screen", "confirm"] and len(create.calls) == 20
    assert report["native_processes"] == 0 and report["recommended"] is None
    assert report["official_score"] is None and not report["promoted"]
    plan = report["plan"]
    assert plan["policy"] == pareto.AGGREGATE_POLICY
    assert plan["primary_pin"] == PIN.to_dict()
    assert plan["score_scope"] == "matched-local-primary-pin"
    original_tokens = reference_tokens(SOURCE, RECORD["statement"])
    token_gain = Fraction(original_tokens - reference_tokens(LONG.source, RECORD["statement"]), original_tokens)
    for phase in ("screen", "confirmation"):
        for stratum in comparison(report, phase=phase)["strata"]:
            assert Fraction(**stratum["nominal_gain_pp"]) == Fraction(100, 3) * (token_gain + Fraction(1, 2))
            assert stratum["nominal_gain_pp"] == stratum["conservative_gain_pp"]
    assert "not the official score" in pareto.summary(report)
    for legacy in ("pareto-v1", "strict-dual-v1"):
        assert run(factory(), [LONG], selection_objective=legacy)["status"] == "NO_IMPROVEMENT"


@pytest.mark.parametrize("raw,selected", [(11000, True), (20000, False)])
def test_shorter_slower_uses_sum_not_product_or_shortest_only(factory, raw, selected):
    r = run(factory(lambda _phase, p, *_: 10000 if p["candidate"] == SOURCE else raw),
            selection_objective=MODE)
    assert (r["selected_for_confirmation"] == "short") == selected


def test_ranking_uses_score_not_token_count(factory):
    costs = {SOURCE: 10000, SHORT.source: 12000, LONG.source: 1000}
    r = run(factory(lambda _phase, p, *_: costs[p["candidate"]]), [SHORT, LONG], selection_objective=MODE)
    assert r["screen_analysis"]["eligible"] == ["long", "short"]
    assert r["selected_for_confirmation"] == "long"


def test_rejects_gain_over_original_that_loses_to_incumbent(factory):
    costs = {SOURCE: 10000, SHORT.source: 1000, MEDIUM.source: 8000}
    r = run(factory(lambda _phase, p, *_: costs[p["candidate"]]), [MEDIUM], incumbent=SHORT,
            selection_objective=MODE)
    assert comparison(r, "medium")["improves"]
    assert not comparison(r, "medium", "incumbent")["improves"]
    assert r["status"] == "NO_IMPROVEMENT"


@pytest.mark.parametrize("changed_order", pareto.ORDERS)
def test_both_primary_branch_orders_must_improve(factory, changed_order):
    def cost(_, p, order, *_args):
        return 10000 if p["candidate"] == SOURCE or order == changed_order else 1000
    r = run(factory(cost), [LONG], selection_objective=MODE)
    assert r["status"] == "NO_IMPROVEMENT"
    assert len(comparison(r)["strata"]) == 2


def test_primary_pin_drives_cost_but_all_pins_must_verify(factory):
    pin2 = VersionPin("v4.27.0", "c" * 40)
    record = {**RECORD, "version_info": [*RECORD["version_info"], {pin2.lean_tag: pin2.git_commit}]}
    def cost(_, p, _order, _index, pin):
        return 10000 if p["candidate"] == SOURCE else (1000 if pin == PIN else 1000000)
    create = factory(cost); create.two_pins = True
    r = pareto.run_selection(record, [LONG], create, max_calls=40,
                            evidence_mode="offline_fixture", selection_objective=MODE)
    assert r["status"] == "FIXTURE_CONFIRMED" and len(create.calls) == 40
    assert len(r["screen_analysis"]["rows"]["long"]["raw_heartbeats_by_stratum"]) == 4
    assert len(comparison(r)["strata"]) == 2
    missing = factory(cost, missing=(pin2,)); missing.two_pins = True
    r = pareto.run_selection(record, [LONG], missing, max_calls=40,
                            evidence_mode="offline_fixture", selection_objective=MODE)
    assert r["status"] == "INCOMPLETE" and r["selected_for_confirmation"] is None

    # The primary pin is the declared first pin, not whichever gives the best
    # cost. Reordering the same two pins changes this expressly local objective.
    reversed_record = {**record, "version_info": list(reversed(record["version_info"]))}
    create = factory(cost); create.two_pins = True
    r = pareto.run_selection(reversed_record, [LONG], create, max_calls=40,
                            evidence_mode="offline_fixture", selection_objective=MODE)
    assert r["plan"]["primary_pin"] == pin2.to_dict()
    assert r["status"] == "NO_IMPROVEMENT" and r["selected_for_confirmation"] is None


@pytest.mark.parametrize("damage", ["reject", "axioms"])
def test_secondary_pin_failure_vetoes_primary_pin_score_gain(factory, damage):
    pin2 = VersionPin("v4.27.0", "c" * 40)
    record = {**RECORD, "version_info": [*RECORD["version_info"], {pin2.lean_tag: pin2.git_commit}]}
    def modify(_, p, data):
        if p["candidate"] == LONG.source and data["lean_version"] == "4.27.0":
            if damage == "reject": data["report"]["outcome"] = "REJECTED"
            else: data["report"]["axioms"] = ["Classical.choice"]
    create = factory(modify=modify); create.two_pins = True
    r = pareto.run_selection(record, [LONG], create, max_calls=40,
                            evidence_mode="offline_fixture", selection_objective=MODE)
    assert r["selected_for_confirmation"] is None and r["recommended"] is None
    assert not r["screen_analysis"]["rows"]["long"]["admissible"]
    assert create.phases == ["screen"]


@pytest.mark.parametrize("damage", ["axioms", "type", "target", "timeout"])
def test_score_never_bypasses_native_admission(factory, damage):
    def modify(_, p, data):
        if p["candidate"] != LONG.source:
            return
        if damage == "axioms": data["report"]["axioms"] = ["Classical.choice"]
        elif damage == "type": data["report"]["type_preserved"] = False
        elif damage == "target": data["target"] = "Other.goal"
        else: data["report"]["outcome"] = "TIMEOUT"
    r = run(factory(modify=modify), [LONG], selection_objective=MODE)
    assert r["selected_for_confirmation"] is None and r["recommended"] is None


def test_confirmation_failure_does_not_try_another_candidate(factory):
    def cost(phase, p, *_):
        return 10000 if p["candidate"] == SOURCE or phase == "confirm" else (
            1000 if p["candidate"] == LONG.source else 12000)
    create = factory(cost)
    r = run(create, [SHORT, LONG], selection_objective=MODE)
    assert r["selected_for_confirmation"] == "long" and r["status"] == "UNCONFIRMED"
    assert len(create.calls) == 24 and create.phases == ["screen", "confirm"]
    assert r["recommended"] is None and r["retained_incumbent"] == "control"


def test_zero_reference_cost_abstains_without_substituting_one(factory):
    r = run(factory(lambda *_: 0), [LONG], selection_objective=MODE)
    assert r["status"] == "NO_IMPROVEMENT"
    assert comparison(r)["reason"] == "zero_reference_heartbeat_denominator"
    assert not comparison(r)["applicable"]


def test_range_and_predeclared_noise_floor_can_turn_nominal_win_into_abstention(factory):
    # Equal-length proof with a 1-unit win has no conservative win after margin.
    same = pareto.Candidate("long", SOURCE.replace("exact two", "exact one"), "fixture")
    r = run(factory(lambda _phase, p, *_: 10000 if p["candidate"] == SOURCE else 9999),
            [same], selection_objective=MODE, heartbeat_noise_floor_raw=1)
    s = comparison(r)["strata"][0]
    assert Fraction(**s["nominal_gain_pp"]) > 0
    assert Fraction(**s["conservative_gain_pp"]) == 0
    assert r["status"] == "NO_IMPROVEMENT"
    def noisy(_, p, _order, index, _pin):
        return 10000 if p["candidate"] == SOURCE else (9800, 9999, 9900)[index]
    r = run(factory(noisy), [same], selection_objective=MODE)
    assert r["status"] == "NO_IMPROVEMENT"
    assert comparison(r)["strata"][0]["margin_raw"] == 199


def test_conservative_reference_denominator_depends_on_gain_direction(factory):
    def cost(_, p, _order, index, _pin):
        return (10000, 11000, 10500)[index] if p["candidate"] == SOURCE else 12000
    r = run(factory(cost), selection_objective=MODE)
    s = comparison(r, "short")["strata"][0]
    assert s["adjusted_heartbeat_delta_raw"] == -3000
    assert s["conservative_reference_raw"] == 10000
    def positive(_, p, _order, index, _pin):
        return (10000, 11000, 10500)[index] if p["candidate"] == SOURCE else 1000
    r = run(factory(positive), selection_objective=MODE)
    assert comparison(r, "short")["strata"][0]["conservative_reference_raw"] == 11000


def test_audit_recomputes_exact_aggregate_deltas_without_creating_authority(factory):
    r = run(factory(), [LONG], selection_objective=MODE)
    result = audit_report(r["plan"], r)
    assert result["status"] == "CONSISTENT", result
    assert result["fresh_native_processes"] == 0 and not result["proof_verified"]
    bad = copy.deepcopy(r)
    comparison(bad)["strata"][0]["conservative_gain_pp"]["numerator"] += 1
    assert audit_report(bad["plan"], bad)["status"] == "INCONSISTENT"


def test_archived_native_aggregate_trial_is_consistent_not_fresh_authority():
    root = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence/solver-aggregate-pilot-2026-09-24"
    report = json.loads((root / "report.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    audit = audit_report(protocol, report)
    assert audit["status"] == "CONSISTENT", audit
    assert not audit["proof_verified"] and audit["fresh_native_processes"] == 0
    assert report["status"] == "CONFIRMED_LOCAL_IMPROVEMENT"
    assert report["native_processes"] == report["requests_reserved"] == report["max_calls"] == 24
    assert report["selected_for_confirmation"] == "longer-intermediate"
    assert report["official_score"] is None and not report["promoted"] and not report["training_enabled"]
    screen = report["screen_analysis"]
    confirm = report["confirmation_analysis"]
    assert screen["eligible"] == ["longer-intermediate", "solver-0"]
    assert screen["rows"]["longer-intermediate"]["tokens"] == 1377 > screen["rows"]["control"]["tokens"] == 1372
    for phase in ("screen", "confirmation"):
        assert all(s["status"] == "VERIFIED" for s in report[phase]["samples"])
        assert not report[phase]["receipt_cache_enabled"]
    for row in (screen, confirm):
        strata = row["aggregate_comparisons"]["longer-intermediate"]["original"]["strata"]
        assert all(Fraction(**s["conservative_gain_pp"]) > Fraction(275, 100) for s in strata)
    for mode in ("pareto-v1", "strict-dual-v1"):
        reanalysis = pareto._analysis(report["screen"], "control", protocol["candidate_labels"],
                                     selection_objective=mode, heartbeat_noise_floor_raw=100)
        assert reanalysis["selected"] is None
    binding = json.loads((root / "source-binding.json").read_text())
    assert binding["before"]["content_root"] == binding["after"]["content_root"]
    assert binding["before"]["status"] == binding["after"]["status"] == "UNCHANGED"
