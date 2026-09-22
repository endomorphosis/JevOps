from __future__ import annotations

from itertools import product
import random

import pytest

from jevops.logic_ir import (
    FALSE, TRUE, Formula, LogicLimit, analyze_formula, assignment_for,
    check_equivalent, check_inductive_invariant, decision_diagram, detect_invariants,
    evaluate, formula_from_ir, karnaugh_map, minimize_formula, parse_formula,
    render_formula, simplify_formula, to_nnf, variables,
)


def join(op: str, values: list[Formula]) -> Formula:
    if not values:
        return TRUE if op == "and" else FALSE
    if len(values) == 1:
        return values[0]
    middle = len(values) // 2
    return Formula(op, (join(op, values[:middle]), join(op, values[middle:])))


def truth_formula(mask: int) -> Formula:
    terms = []
    for row in range(8):
        if mask & (1 << row):
            atoms = [Formula("var", name=name) for name in ("p", "q", "r")]
            terms.append(join("and", [a if row & (1 << bit) else Formula("not", (a,))
                                      for bit, a in enumerate(atoms)]))
    return join("or", terms)


def optimal_cover_cost(mask: int) -> tuple[int, int]:
    """Independent exhaustive cube/coverage DP; does not use the minimizer."""
    cubes = []
    for cube in product((None, False, True), repeat=3):
        covered = sum(1 << row for row in range(8)
                      if all(v is None or bool(row & (1 << i)) == v for i, v in enumerate(cube)))
        if covered & ~mask == 0:
            cubes.append((covered, sum(v is not None for v in cube)))
    costs = {0: (0, 0)}
    for covered, literals in cubes:
        for prev, (n, k) in list(costs.items()):
            union = prev | covered
            costs[union] = min(costs.get(union, (1000, 1000)), (n + 1, k + literals))
    return costs[mask]


def test_every_three_variable_function_minimizes_equivalently_and_optimally() -> None:
    for mask in range(256):
        source = truth_formula(mask)
        for form in ("dnf", "cnf"):
            result = minimize_formula(source, form=form)
            reduced = formula_from_ir(result["formula"])
            assert check_equivalent(source, reduced)["equivalent"], (mask, form)
            assert result["optimal_two_level"]
            expected = optimal_cover_cost(mask if form == "dnf" else mask ^ 255)
            assert (result["cost"]["terms"], result["cost"]["literals"]) == expected


def test_random_formulas_algebra_nnf_ir_roundtrip_and_bdd_match_semantics() -> None:
    rng = random.Random(825)

    def build(depth: int) -> Formula:
        if depth == 0:
            return rng.choice([TRUE, FALSE, *(Formula("var", name=n) for n in "pqrs")])
        op = rng.choice(["not", "and", "or", "imp", "iff", "xor"])
        return Formula(op, tuple(build(depth - 1) for _ in range(1 if op == "not" else 2)))

    for _ in range(96):
        f = build(3)
        assert formula_from_ir(f.to_dict()) == f
        for reduced in (simplify_formula(f), to_nnf(f), parse_formula(render_formula(f))):
            assert check_equivalent(f, reduced)["equivalent"]
        diagram = decision_diagram(f)
        nodes = {row["id"]: row for row in diagram["nodes"]}
        assert all(row["low"] != row["high"] for row in nodes.values())
        assert len({(r["variable"], r["low"], r["high"]) for r in nodes.values()}) == len(nodes)
        for i in range(1 << len(variables(f))):
            assignment = assignment_for(i, variables(f))
            node = diagram["root"]
            while node > 1:
                row = nodes[node]
                node = row["high"] if assignment[row["variable"]] else row["low"]
            assert bool(node) == evaluate(f, assignment)


def test_kmap_gray_order_dont_cares_and_irrelevant_variables() -> None:
    f = parse_formula("(p ∧ q) ∨ (p ∧ ¬ q)")
    assert minimize_formula(f)["lean"] == "p"
    assert decision_diagram(f)["independent_variables"] == ["q"]
    f = parse_formula("(p ∧ q) ∨ (r ∧ s)")
    context = parse_formula("p → r")
    table = karnaugh_map(f, assumptions=context)
    names = table["row_variables"] + table["column_variables"]
    for codes in (table["row_gray_codes"], table["column_gray_codes"]):
        assert all((a ^ b).bit_count() == 1 for a, b in zip(codes, codes[1:] + codes[:1]))
    for i, row in enumerate(table["row_gray_codes"]):
        for j, col in enumerate(table["column_gray_codes"]):
            assignment = assignment_for(row | col << len(table["row_variables"]), names)
            expected = int(evaluate(f, assignment)) if evaluate(context, assignment) else None
            assert table["cells"][i][j] == expected


def test_context_is_explicit_and_inconsistent_context_is_not_a_global_rewrite() -> None:
    source, context = parse_formula("p ∨ q"), parse_formula("p")
    result = minimize_formula(source, assumptions=context)
    assert result["lean"] == "True"
    assert result["assumptions"] == "p" and result["dont_care_count"] == 2
    reduced = formula_from_ir(result["formula"])
    assert check_equivalent(source, reduced, assumptions=context)["equivalent"]
    assert not check_equivalent(source, reduced)["equivalent"]
    impossible = parse_formula("p ∧ ¬ p")
    assert minimize_formula(source, assumptions=impossible)["vacuous"]
    report = detect_invariants(impossible)
    assert report["vacuous"] and not report["forced"] and not report["relations"]


def test_cover_timeout_preserves_equivalence_without_optimality_claim() -> None:
    source = parse_formula("(p ∧ q) ∨ (¬ p ∧ r)")
    for form in ("dnf", "cnf"):
        result = minimize_formula(source, form=form, search_budget=0)
        assert not result["optimal_two_level"]
        assert check_equivalent(source, formula_from_ir(result["formula"]))["equivalent"]


def test_redundant_invariants_are_removed_sequentially() -> None:
    f = parse_formula("p ∧ (p → q) ∧ q ∧ q")
    report = detect_invariants(f)
    assert report["forced"] == {"p": True, "q": True}
    assert report["redundant_conjuncts"]
    assert check_equivalent(f, parse_formula(report["reduced"]))["equivalent"]
    assert detect_invariants(parse_formula("p ∧ p"))["reduced"] == "p"
    assert detect_invariants(parse_formula("p ↔ ¬ q"))["relations"] == [
        {"left": "p", "right": "q", "relation": "opposite"}]


def test_finite_state_invariant_obligations_return_real_counterexamples() -> None:
    inv = parse_formula("x ↔ y")
    initial = parse_formula("¬ x ∧ ¬ y")
    good_step = parse_formula("(xn ↔ ¬ x) ∧ (yn ↔ ¬ y)")
    mapping = {"x": "xn", "y": "yn"}
    report = check_inductive_invariant(inv, initial, good_step, mapping)
    assert report["inductive"] and report["initial_satisfiable"] and not report["preservation_vacuous"]
    bad_step = parse_formula("(xn ↔ ¬ x) ∧ (yn ↔ y)")
    report = check_inductive_invariant(inv, initial, bad_step, mapping)
    witness = report["preservation_counterexample"]
    assert not report["inductive"] and evaluate(inv, witness) and evaluate(bad_step, witness)
    assert not evaluate(inv, {k: witness[v] for k, v in mapping.items()})
    report = check_inductive_invariant(inv, parse_formula("x ∧ ¬ y"), good_step, mapping)
    assert not evaluate(inv, report["initiation_counterexample"])
    report = check_inductive_invariant(inv, FALSE, FALSE, mapping)
    assert not report["initial_satisfiable"] and report["preservation_vacuous"]
    for wrong_mapping in ({"x": "x"}, {"x": "xn", "y": "xn"}, {"x": "xn"}):
        with pytest.raises(ValueError):
            check_inductive_invariant(inv, initial, good_step, wrong_mapping)


@pytest.mark.parametrize("source", ["", "p q", "∀ x, P x", "x = y", "p := True", "p; exact h",
                                        " ∧ ".join("abcdefghi"), "(" * 60 + "p" + ")" * 60])
def test_unsupported_and_oversized_syntax_fails_closed(source: str) -> None:
    assert not analyze_formula(source)["supported"]


def test_typed_ir_and_expansion_budgets_and_cache_isolation() -> None:
    for value in ({"op": "var", "name": "p; exact h"}, {"op": "and", "args": []},
                  {"op": "true", "trusted": True}, {"op": "not", "args": [False]}):
        with pytest.raises(ValueError):
            formula_from_ir(value)
    f = parse_formula("p ↔ (q ↔ (p ↔ (q ↔ p)))")
    with pytest.raises(LogicLimit, match="NNF"):
        to_nnf(f, expansion_budget=4)
    nested = "p"
    for _ in range(15):
        nested = f"q ↔ ({nested})"
    report = analyze_formula(nested)
    assert report["supported"] and report["nnf"] is None and report["nnf_limit"]
    report["variables"].clear()
    assert analyze_formula(nested)["variables"] == ["p", "q"]
    with pytest.raises(ValueError):
        evaluate(parse_formula("p"), {"p": 1})
