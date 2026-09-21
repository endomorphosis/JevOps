from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from jevops import folds


LEAN = shutil.which("lean")


def _compile(source: str) -> bool:
    assert LEAN is not None
    with tempfile.TemporaryDirectory(prefix="jevops-tactic-verifier-") as temp:
        path = Path(temp) / "Main.lean"
        path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [LEAN, str(path)],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    return result.returncode == 0


@pytest.mark.skipif(LEAN is None, reason="requires the elan lean executable")
def test_portable_tactic_folds_compile_before_they_can_train_or_mutate_nca() -> None:
    """Exercise representative folds against real Lean, not string assertions only."""

    cases: list[tuple[str, str, Callable[[str], str]]] = [
        (
            "exact_hyp",
            "theorem exact_hyp (h : True) : True := by\n  exact h\n",
            folds.fold_exact_hyp,
        ),
        (
            "ctor_pair",
            "theorem ctor_pair (a b : Prop) (ha : a) (hb : b) : a ∧ b := by\n"
            "  constructor\n  · exact ha\n  · exact hb\n",
            folds.fold_ctor_pair_exacts,
        ),
        (
            "trim_intro_names",
            "theorem trim_intro_names : ∀ a : Nat, True := by\n  intro a\n  trivial\n",
            folds.fold_trim_intro_names,
        ),
        (
            "trailing_tuple_comma",
            "theorem trailing_tuple (a b : Nat) : a = a ∧ b = b := by\n"
            "  exact ⟨rfl, rfl,⟩\n",
            folds.fold_trailing_tuple_comma,
        ),
    ]

    for name, source, fold in cases:
        candidate = fold(source)
        assert _compile(source), f"baseline does not compile: {name}"
        assert candidate != source, f"fold did not fire: {name}"
        assert _compile(candidate), f"fold produced invalid Lean: {name}"
        assert len(candidate.split()) <= len(source.split()), name


def test_context_sensitive_unfold_fold_is_not_in_default_pipeline() -> None:
    stems = [name for name, _fold in folds.PIPELINE]
    assert "drop_unfold_before_split" not in stems


@pytest.mark.skipif(LEAN is None, reason="requires the elan lean executable")
def test_unused_intros_preserves_a_binder_used_later() -> None:
    source = (
        "theorem keep_intro_x : ∀ x : Nat, True → x = x := by\n"
        "  intros x Hin\n"
        "  exact Eq.refl x\n"
    )
    candidate = folds.fold_unused_intros(source)
    assert candidate == source
    assert _compile(candidate)
