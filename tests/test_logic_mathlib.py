"""Opt-in real Mathlib validation; never download dependencies during tests.

JEVOPS_MATHLIB_PROJECT=/cached/lake/project python -m pytest -q tests/test_logic_mathlib.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jevops.logic_refactor import reduction_variants
from jevops.router_tuning import _lean_compiler

PROJECT = os.environ.get("JEVOPS_MATHLIB_PROJECT")
pytestmark = pytest.mark.skipif(not PROJECT, reason="set JEVOPS_MATHLIB_PROJECT to a built Mathlib project")


def test_mathlib_reductions_compile_in_the_pinned_project() -> None:
    # Pick emitted proposals, not handcrafted tactic implementations. Indices
    # select the particular optional solver being exercised within each family.
    fixtures = [
        ("arithmetic_polynomial", 0, "(x y : ℚ)", "(x + y)^2 = x^2 + 2*x*y + y^2"),
        ("arithmetic_polynomial", 2, "(x : ℝ)", "0 ≤ x^2"),
        ("arithmetic_polynomial", 3, "", "(2 : ℚ) / 3 + 1 / 3 = 1"),
        ("arithmetic_polynomial", 4, "(x : ℝ) (hx : 0 < x)", "0 < x + 1"),
        ("arithmetic_linear", 2, "(x y : ℚ) (h : x ≤ y)", "2*x + 1 ≤ 2*y + 1"),
        ("rational_normalize", 0, "(x : ℚ) (hx : x ≠ 0)", "1 / x + 1 / x = 2 / x"),
        ("set_extensionality", 0, "(A B : Set Nat)", "A ∩ (A ∪ B) = A"),
        ("quantifier_simp", 2, "(P : Nat → Prop)", "(¬ ∀ n, P n) ↔ ∃ n, ¬ P n"),
        ("logic_simp", 3, "(p q r : Prop)", "(p ∧ (q ∨ r)) ↔ ((p ∧ q) ∨ (p ∧ r))"),
        ("additive_normalize", 0, "(x y : ℤ)", "x + y - x = y"),
        ("noncommutative_normalize", 0, "{R : Type} [Ring R] (x y : R)", "(x + y)*(x + y) = x*x + x*y + y*x + y*y"),
        ("noncommutative_normalize", 1, "{G : Type} [Group G] (x y : G)", "x*y*y⁻¹ = x"),
        ("grind_control", 0, "(α : Type) (x y : α) (f : α → α) (h : x = y)", "f x = f y"),
        ("order_normalize", 0, "(x y z : ℝ) (hxy : x ≤ y) (hyz : y ≤ z)", "x ≤ z"),
        ("cast_transport", 0, "(n m : ℕ) (h : n = m)", "(n : ℤ) = (m : ℤ)"),
        ("finite_context", 0, "", "∀ b : Bool, b = true ∨ b = false"),
    ]
    source = "import Mathlib\n"
    for i, (strategy, index, binders, goal) in enumerate(fixtures):
        rows = reduction_variants("skip", strategy=strategy, goal=goal)
        body = rows[index][1]
        source += f"theorem mathlib_family_{i} {binders} : {goal} := by\n"
        source += "\n".join("  " + line for line in body.splitlines()) + "\n"
    compiler = _lean_compiler(project_root=Path(PROJECT), use_lake=True, timeout=60)
    result = compiler(source)
    assert result["theorem_ok"], result
    # A nonzero denominator condition must not be silently discharged for an
    # actually false statement at x=0.
    rows = reduction_variants("skip", strategy="rational_normalize", goal="x / x = 1")
    body = "\n".join("  " + line for line in rows[0][1].splitlines())
    bad = compiler("import Mathlib\ntheorem bad (x : ℚ) : x / x = 1 := by\n" + body + "\n")
    assert not bad["theorem_ok"], bad
