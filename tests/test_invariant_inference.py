from __future__ import annotations

import pytest

from jevops.invariant_inference import infer_invariants, reachable_states
from jevops.logic_ir import LogicLimit, parse_formula as p


def test_houdini_rechecks_after_removing_a_supporting_candidate():
    report = infer_invariants(p("¬ x ∧ ¬ y"), p("(xn ↔ y) ∧ yn"),
                              [p("¬ x"), p("¬ y")], {"x": "xn", "y": "yn"})
    assert report["kept_indices"] == [] and report["lean"] == "True"
    assert [(r["index"], r["round"]) for r in report["removed"]] == [(1, 1), (0, 2)]
    assert not report["lean_verified"]


def test_mutually_supporting_invariants_are_not_tested_independently():
    report = infer_invariants(p("x ∧ y"), p("(xn ↔ y) ∧ (yn ↔ x)"),
                              [p("x"), p("y")], {"x": "xn", "y": "yn"})
    assert report["kept_indices"] == [0, 1] and not report["removed"]
    assert report["initial_satisfiable"] and not report["preservation_vacuous"]
    assert "xn" in report["preservation_obligation"]


def test_duplicate_invariants_are_reduced_sequentially_and_initial_failures_have_witnesses():
    report = infer_invariants(p("x"), p("xn ↔ x"),
                              [p("x"), p("x"), p("True"), p("¬ x")], {"x": "xn"})
    assert report["kept_indices"] == [0] and report["lean"] == "x"
    assert report["redundant_indices"] == [2, 1]
    assert report["removed"][0]["reason"] == "initiation"
    assert report["removed"][0]["counterexample"] == {"x": True}


def test_reachability_is_transitive_and_vacuity_is_explicit():
    report = reachable_states(p("¬ x"), p("xn ↔ ¬ x"), {"x": "xn"})
    assert report["states"] == [{"x": False}, {"x": True}]
    assert reachable_states(p("False"), p("True"), {"x": "xn"})["states"] == []
    report = infer_invariants(p("False"), p("False"), [p("x")], {"x": "xn"})
    assert not report["initial_satisfiable"] and report["preservation_vacuous"]


def test_bad_state_models_and_unbounded_candidates_fail_closed():
    for mapping in ({"x": "x"}, {"x": "n", "y": "n"}):
        with pytest.raises(ValueError):
            infer_invariants(p("x"), p("True"), [], mapping)
    with pytest.raises(ValueError):
        infer_invariants(p("x"), p("z"), [], {"x": "xn"})
    with pytest.raises(LogicLimit):
        infer_invariants(p("x"), p("True"), [p("x")] * 33, {"x": "xn"})
