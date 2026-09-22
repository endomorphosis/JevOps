from __future__ import annotations

import random

import pytest

from jevops.equality_saturation import EGraph, RULES, saturate_formula
from jevops.logic_ir import MAX_DEPTH, Formula, assignment_for, evaluate, parse_formula, variables


def equivalent(a, b):
    names = variables(a, b)
    return all(evaluate(a, assignment_for(i, names)) == evaluate(b, assignment_for(i, names))
               for i in range(1 << len(names)))


@pytest.mark.parametrize("name,lhs,rhs", RULES)
def test_every_egraph_rewrite_is_classically_sound(name, lhs, rhs):
    def instantiate(p):
        return Formula("var", name=p[1:]) if isinstance(p, str) else Formula(p[0], tuple(instantiate(a) for a in p[1:]))
    assert equivalent(instantiate(lhs), instantiate(rhs)), name


def test_egraph_rebuild_closes_congruent_parents_and_extracts_acyclic_terms():
    graph = EGraph()
    p, q = graph.add(parse_formula("p")), graph.add(parse_formula("q"))
    np, nq = graph.add_node("not", (p,)), graph.add_node("not", (q,))
    graph.union(p, q)
    graph.rebuild()
    assert graph.find(np) == graph.find(nq)
    dup = graph.add_node("and", (p, p))
    graph.union(p, dup)
    graph.rebuild()
    assert graph.extract(p).op == "var"


def test_factoring_can_cross_a_larger_intermediate_and_reports_limits():
    original = parse_formula("(p ∧ q) ∨ (p ∧ ¬ q)")
    result = saturate_formula(original)
    assert result["lean"] == "p" and not result["global_minimum"]
    assert "and_factor" in result["rules_used"]
    assert result["allocated_nodes"] <= 512
    limited = saturate_formula(original, max_nodes=1)
    assert not limited["supported"] and limited["reason"] == "egraph_node_budget"
    limited = saturate_formula(original, max_matches=1)
    assert limited["limit_reason"] == "egraph_match_budget"
    assert equivalent(original, parse_formula(limited["lean"]))
    with pytest.raises(ValueError):
        saturate_formula(original, objective="arena_tokens")


def test_extraction_accepts_the_same_depth_boundary_as_the_formula_ir():
    original = parse_formula("p")
    for _ in range(MAX_DEPTH):
        original = Formula("not", (original,))
    assert variables(original) == ("p",)
    graph = EGraph()
    assert graph.extract(graph.add(original)) == original
    result = saturate_formula(original, iterations=0)
    assert result["supported"] and result["lean"] == "p"


def test_random_bounded_saturations_preserve_every_truth_assignment():
    rng = random.Random(194)
    atoms = [parse_formula(n) for n in ("p", "q", "r", "True", "False")]
    def formula(depth):
        if not depth or rng.random() < .25:
            return rng.choice(atoms)
        op = rng.choice(["and", "or", "imp", "iff", "xor", "not"])
        return Formula(op, tuple(formula(depth - 1) for _ in range(1 if op == "not" else 2)))
    for _ in range(35):
        source = formula(3)
        result = saturate_formula(source, max_nodes=128, max_matches=2000, iterations=2)
        assert equivalent(source, parse_formula(result["lean"]))
        assert result["result_chars"] <= result["source_chars"]
