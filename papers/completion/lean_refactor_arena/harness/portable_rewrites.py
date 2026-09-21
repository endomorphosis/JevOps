"""LRA adapter — portable Lean tactic folds live in JevOps."""
from __future__ import annotations

from typing import Any, Mapping, Optional

import _jevops_path  # noqa: F401
from jevops import folds as _mod

PIPELINE = _mod.PIPELINE
KEEP_STRUCTURE = _mod.KEEP_STRUCTURE
SKILL_RESIDUAL = _mod.SKILL_RESIDUAL
SKILL_CRITERIA = _mod.SKILL_CRITERIA
SHORTEN_IDENTS = _mod.SHORTEN_IDENTS


def fold_exact_hyp(tactics: str) -> str:
    return _mod.fold_exact_hyp(tactics)


def fold_use_exact(tactics: str) -> str:
    return _mod.fold_use_exact(tactics)


def fold_use_exact_reuse(tactics: str) -> str:
    return _mod.fold_use_exact_reuse(tactics)


def fold_ctor_pair_exacts(tactics: str) -> str:
    return _mod.fold_ctor_pair_exacts(tactics)


def fold_semi_assumption(tactics: str) -> str:
    return _mod.fold_semi_assumption(tactics)


def fold_repeat_par_grind(tactics: str) -> str:
    return _mod.fold_repeat_par_grind(tactics)


def fold_shorten_ident(tactics: str, old: str, new: str) -> str:
    return _mod.fold_shorten_ident(tactics, old, new)


def fold_grind_only_to_grind(tactics: str) -> str:
    return _mod.fold_grind_only_to_grind(tactics)


def fold_drop_unfold_before_split(tactics: str) -> str:
    return _mod.fold_drop_unfold_before_split(tactics)


def fold_drop_try_simp_all(tactics: str) -> str:
    return _mod.fold_drop_try_simp_all(tactics)


def fold_drop_intro_before_simp_all(tactics: str) -> str:
    return _mod.fold_drop_intro_before_simp_all(tactics)


def fold_trim_intro_names(tactics: str) -> str:
    return _mod.fold_trim_intro_names(tactics)


def fold_unused_intros(tactics: str) -> str:
    return _mod.fold_unused_intros(tactics)


def fold_trailing_tuple_comma(tactics: str) -> str:
    return _mod.fold_trailing_tuple_comma(tactics)


def fold_redundant_inner_simp(tactics: str) -> str:
    return _mod.fold_redundant_inner_simp(tactics)


def fold_hoist_repeated_simp(tactics: str) -> str:
    return _mod.fold_hoist_repeated_simp(tactics)


def fold_from_memory_skill(tactics: str, spec: Mapping[str, Any]) -> str:
    return _mod.fold_from_memory_skill(tactics, spec)


def pipeline_order(memory: Optional[dict[str, Any]] = None, *, name: str = ""):
    return _mod.pipeline_order(memory, name=name)


def compose_pipeline(
    tactics: str,
    *,
    skip: Optional[set[str]] = None,
    memory: Optional[dict[str, Any]] = None,
    name: str = "",
):
    return _mod.compose_pipeline(tactics, skip=skip, memory=memory, name=name)


def portable_drafts(
    tactics: str,
    *,
    skip: Optional[set[str]] = None,
    memory: Optional[dict[str, Any]] = None,
    name: str = "",
):
    return _mod.portable_drafts(tactics, skip=skip, memory=memory, name=name)


def analyze_residuals(tactics: str) -> dict[str, int]:
    return _mod.analyze_residuals(tactics)


def available_skills(
    tactics: str, *, memory: Optional[dict[str, Any]] = None, name: str = ""
) -> dict[str, object]:
    return _mod.available_skills(tactics, memory=memory, name=name)


def decision_tree(
    tactics: str,
    *,
    memory: Optional[dict[str, Any]] = None,
    name: str = "",
    skip: Optional[set[str]] = None,
) -> dict[str, list[str]]:
    return _mod.decision_tree(tactics, memory=memory, name=name, skip=skip)
