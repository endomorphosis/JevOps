"""The experiment planner is offline; its resource ceiling precedes execution."""
from pathlib import Path
import importlib.util
import json

import pytest

from jevops.arena import ArenaContext, Outcome, VersionReceipt, source_hash
from tests.test_arena_local import RECORD

PATH = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py"
SPEC = importlib.util.spec_from_file_location("local_premise_pilot", PATH)
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)
NOMINEES = [{"name": "True.intro", "origin": "fixture", "split": "library"}]


def test_plan_is_fixed_bounded_and_honest_about_discovery_overhead():
    plan = pilot.make_plan(RECORD, NOMINEES, max_processes=55)
    assert plan == pilot.make_plan(RECORD, NOMINEES, max_processes=55)
    assert plan["process_ceiling"] == 55
    assert plan["cap_per_family"] == 2 and plan["families"] == ["whole", "local"]
    assert plan["protocol"]["same_draft_and_screen_cap_per_family"]
    assert not plan["protocol"]["discovery_overhead_matched"]
    assert plan["official_score"] is None and not plan["promoted"]


def test_local_comparison_reserves_both_replay_families():
    old = pilot.make_plan(RECORD, NOMINEES, max_processes=57)
    new = pilot.make_plan(RECORD, NOMINEES, max_processes=57, comparison="local-portfolio")
    assert new["families"] == ["local", "portfolio"]
    assert new["process_ceiling"] == 57 == old["process_ceiling"] + 2
    assert new["protocol"]["discovery_overhead_matched"]
    assert new["protocol"]["local_replay_cap_per_family"] == 2
    assert new["protocol"]["strategies"] == {"local": "baseline-v1", "portfolio": "portfolio-v1"}
    assert new["plan_id"] != old["plan_id"]
    with pytest.raises(ValueError, match="comparison"):
        pilot.make_plan(RECORD, NOMINEES, comparison="anything")


def test_application_retrieval_plan_has_equal_explicit_discovery_units():
    plan = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=41, comparison="application-retrieval")
    assert plan["process_ceiling"] == 41  # two-pin fixture: 13 discovery + 4 screen + 24 measurement
    assert plan["families"] == ["lexical", "typed"]
    assert plan["protocol"]["max_applications_per_family"] == 4
    assert plan["protocol"]["include_signatures"]
    assert plan["protocol"]["retrievals"] == {"lexical": "lexical-v1", "typed": "typed-head-v1"}
    assert not plan["protocol"]["measured_wall_time_matched"] and not plan["protocol"]["confirmation"]


def test_search_plan_separates_span_and_construction_ablations():
    plan = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=55, comparison="bounded-search")
    assert plan["process_ceiling"] == 55  # 17 discovery + 6 screen + 32 measurement
    assert plan["families"] == ["headroom", "matching", "backward"]
    options = plan["protocol"]["family_options"]
    assert options["headroom"]["span_order"] == "headroom-v1"
    assert options["matching"]["span_order"] == options["backward"]["span_order"] == "matching-head-v1"
    assert options["backward"]["search"] == "backward-v1"
    assert plan["protocol"]["search_primitive_ceiling"] == 384
    assert plan["protocol"]["process_ceiling_matched"] and not plan["protocol"]["primitive_work_matched"]
    assert plan["official_score"] is None and not plan["promoted"]


def test_subgoal_plan_separates_retrieval_from_depth_and_matches_step_ceiling():
    plan = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=55, comparison="subgoal-retrieval")
    assert plan["process_ceiling"] == 55 and plan["families"] == ["fixed", "subgoal", "deeper"]
    options = plan["protocol"]["family_options"]
    assert options["fixed"]["search"] == "backward-v1"
    assert options["subgoal"]["search"] == options["deeper"]["search"] == "subgoal-v1"
    assert options["fixed"]["max_depth"] == options["subgoal"]["max_depth"] == 4
    assert options["deeper"]["max_depth"] == 8
    assert {o["max_steps"] for o in options.values()} == {96}
    assert plan["protocol"]["retrieval_ceiling_per_dynamic_family"] == 128
    assert plan["protocol"]["primitive_ceiling_matched"] and not plan["protocol"]["primitive_work_matched"]


def test_ordering_plan_changes_only_the_discharge_window():
    plan = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=41, comparison="subgoal-ordering")
    assert plan["process_ceiling"] == 41 and plan["families"] == ["baseline", "discharge"]
    options = plan["protocol"]["family_options"]
    assert options["discharge"] == {**options["baseline"], "discharge_window": 8}
    assert options["baseline"]["max_depth"] == 8
    assert plan["protocol"]["search_primitive_ceiling_per_family"] == 384
    assert plan["protocol"]["retrieval_ceiling_per_dynamic_family"] == 128


def test_proposition_plan_isolates_filter_from_observation_and_ordering():
    plan = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=55, comparison="proposition-discharge")
    assert plan["process_ceiling"] == 55
    assert plan["families"] == ["baseline", "observe_all", "propositions"]
    opts = plan["protocol"]["family_options"]
    assert opts["propositions"] == {**opts["observe_all"], "discharge_filter": "propositions-v1"}
    assert {v["max_steps"] for v in opts.values()} == {96}
    assert plan["protocol"]["inspection_ceiling_per_observed_family"] == 1024


@pytest.mark.parametrize("budget", [0, 54])
def test_insufficient_total_budget_cannot_create_output_or_verifiers(tmp_path, monkeypatch, budget):
    monkeypatch.setattr(pilot, "NativeLeanVerifier", lambda *a, **k: pytest.fail("native setup at exhausted budget"))
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="full pilot"):
        pilot.run_pilot(pilot.make_plan(RECORD, NOMINEES, max_processes=budget), output, {},
                        reader=None, excluded_names=(), check_resources=lambda: None)
    assert not output.exists()


@pytest.mark.parametrize("kwargs", [{"cap": 0}, {"cap": 3}, {"cap": True}, {"max_processes": -1},
                                   {"max_processes": 129}])
def test_bad_limits_are_rejected(kwargs):
    with pytest.raises(ValueError): pilot.make_plan(RECORD, NOMINEES, **kwargs)


def test_duplicate_and_authority_bearing_nominees_rejected():
    with pytest.raises(ValueError): pilot.make_plan(RECORD, NOMINEES * 2)
    with pytest.raises(TypeError): pilot.make_plan(RECORD, [{**NOMINEES[0], "verified": True}])


@pytest.mark.parametrize("failure", [Outcome.REJECTED, Outcome.TIMEOUT])
@pytest.mark.parametrize("comparison", ["whole-local", "local-portfolio", "application-retrieval", "bounded-search", "subgoal-retrieval", "subgoal-ordering", "proposition-discharge", "cycle-guard", "assigned-cycle"])
def test_replay_failure_does_not_prune_screen_and_errors_are_not_rejections(tmp_path, monkeypatch, failure, comparison):
    """Orchestration fixtures only: no Lean process or claimed native result."""
    pins = pilot._pins(RECORD)
    context = ArenaContext(RECORD["name"], RECORD["statement"], RECORD["src"], 20, None,
        tuple(pins), tuple("a" * 64 for _ in pins), "fixture", "1", "fixture")
    calls = []

    class Guard:
        processes = 0

        def __init__(self, *a, **kw): pass

        def context(self, record): return context

        def __call__(self, request):
            self.processes += 1
            calls.append(request)
            outcome = Outcome.VERIFIED if request.source == RECORD["src"] else failure
            return VersionReceipt(request.request_id, source_hash(request.source), context.problem, outcome)

    class Exporter:
        attempts = 0

        def __init__(self, *a, **kw): pass

        def export(self, *a, **kw):
            self.attempts += len(pins)
            return {"status": "INVENTORY_ONLY", "inventory": {}, "scope": {}}

    class Local:
        attempts = 0

        def __init__(self, *a, **kw): pass

        def capture(self, *a):
            self.attempts += 1
            return {"ok": True, "capture": {}}

        def replay(self, *a, **kw):
            self.attempts += 1
            return {"ok": False, "closing_reproduced": False}

        def discover_batch(self, *a, **kw):
            self.attempts += 4
            return {**batch(), "status": "DRAFTS_ONLY", "application_attempts": 4,
                    "roundtrip_attempts": 1, "truncated": True}

    def batch(*a, **kw):
        return {"drafts": [{"source": RECORD["statement"] + " := by trivial", "provenance": "fixture"}],
                "proposals": [{"event_id": 0, "candidate": "trivial"}]}

    monkeypatch.setattr(pilot, "NativeLeanVerifier", Guard)
    monkeypatch.setattr(pilot, "NativePremiseExporter", Exporter)
    monkeypatch.setattr(pilot, "ArenaLocalRuntime", Local)
    monkeypatch.setattr(pilot, "load_inventory", lambda *a: (None, None))
    monkeypatch.setattr(pilot, "propose_batch", batch)
    monkeypatch.setattr(pilot, "propose_local_batch", batch)
    monkeypatch.setattr(pilot, "run_trial", lambda *a, **kw: pytest.fail("unverified arm reached measurement"))
    output = tmp_path / "run"
    result = pilot.run_pilot(pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=55, comparison=comparison), output, {},
        reader=None, excluded_names=(), check_resources=lambda: None)
    assert len(calls) == len(pins) + (3 if comparison in {"bounded-search", "subgoal-retrieval", "proposition-discharge", "cycle-guard", "assigned-cycle"} else 2)
    assert [r["family"] for r in result["screen"]] == {"whole-local": ["whole", "local"],
        "local-portfolio": ["local", "portfolio"], "application-retrieval": ["lexical", "typed"],
        "bounded-search": ["headroom", "matching", "backward"],
        "subgoal-retrieval": ["fixed", "subgoal", "deeper"], "subgoal-ordering": ["baseline", "discharge"],
        "proposition-discharge": ["baseline", "observe_all", "propositions"], "cycle-guard": ["baseline", "observe", "guarded"],
        "assigned-cycle": ["raw", "observe", "guarded"]}[comparison]
    assert result["status"] == ("COMPLETE" if failure == Outcome.REJECTED else "INCOMPLETE")
    assert result["native_processes"] == result["reserved_processes"] == {
        "whole-local": 8, "local-portfolio": 9, "application-retrieval": 15, "bounded-search": 20,
        "subgoal-retrieval": 20, "subgoal-ordering": 15, "proposition-discharge": 20, "cycle-guard": 20, "assigned-cycle": 20}[comparison]
    assert result["measurement"] is None and not result["all_pin_verified"]
    assert json.loads((output / "report.json").read_text()) == result
