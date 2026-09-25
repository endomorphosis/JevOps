"""The frozen-set scorer, checked against the recorded replies. No model calls."""
from __future__ import annotations

import json
from pathlib import Path

from jevops.leanstral_score import faithful

ROOT = Path("/home/barberb/lift_coding/JevOps/.improve-watch")


def _head(path: str, item_id: str, temperature: float | None = None) -> str:
    rows = json.loads((ROOT / path).read_text(encoding="utf-8"))
    for row in rows:
        if row["id"] != item_id:
            continue
        if temperature is not None and row.get("temperature") not in (temperature, None):
            continue
        return row["head"]
    raise AssertionError(item_id)


def test_right_zero_is_a_pass_and_the_definition_equation_is_not() -> None:
    right = _head("leanstral-phase1.json", "E1", 0)
    assert faithful("E1", right, lake_ok=True)
    tautology = "def min_rep_age : Nat := 25\ntheorem t : min_rep_age = 25 := by\n  native_decide\n"
    assert not faithful("E5", tautology, lake_ok=True)


def test_tautology_theorems_names_a_restated_definition() -> None:
    from jevops.leanstral_score import tautology_theorems

    source = "def min_rep_age : Nat := 25\ntheorem rep_requires_two_thirds : min_rep_age = 25 := by\n  native_decide\n"
    assert tautology_theorems(source) == ["rep_requires_two_thirds"]


def test_self_equality_and_a_missing_theorem_fail() -> None:
    copied = "theorem unrel : ∀ a : Nat, a = a := by\n  intro a\n  rfl\n"
    assert not faithful("E5", copied, lake_ok=True)
    implies_self = "theorem t : ∀ a : Nat, a ≤ 24 → a = a := by\n  intro a\n  rfl\n"
    assert not faithful("E3", implies_self, lake_ok=True)
    assert not faithful("E1", "def n : Nat := 0\n", lake_ok=True)
