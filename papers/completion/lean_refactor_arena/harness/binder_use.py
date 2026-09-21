"""LRA adapter — Lean binder gates live in JevOps."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import _jevops_path  # noqa: F401
from jevops import binders as _mod

globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})

# Keep curated benchmark evidence read-only.  Runtime memory belongs under the
# configured LRA artifact root so live runs cannot dirty the imported source
# tree (or accidentally turn a generated receipt into benchmark input).
MEMORY_DEFAULT = _jevops_path.LRA_ARTIFACT_ROOT / "refactor-memory.json"
# This file is a checked-in, read-only research fixture.  Unlike mutable
# memory, it is intentionally resolved from the imported Arena evidence tree.
SKILL_ANALYSIS_DEFAULT = (
    Path(__file__).resolve().parent.parent / "evidence" / "canaries" / "skill-analysis.json"
)


def skill_analysis_default() -> Path:
    """Use the imported Arena fixture without installing global kernel hooks."""

    return SKILL_ANALYSIS_DEFAULT


def rehydrate_from_skill_analysis(memory: dict, *, path: Path | None = None) -> dict:
    """Rehydrate from the benchmark-local analysis fixture by default."""

    return _mod.rehydrate_from_skill_analysis(memory, path=path or SKILL_ANALYSIS_DEFAULT)


def load_memory(path: Path | None = None) -> dict:
    """Load mutable live memory from the configured artifact root.

    ``jevops.binders.load_memory`` intentionally uses the generic
    ``refactor-memory.json`` default.  The Arena adapter has a stricter
    boundary: live runs must use ``MEMORY_DEFAULT`` while still rehydrating
    from the checked-in skill-analysis fixture when that artifact is new.
    """

    from jevops.memory import load_memory as _load

    target = Path(path) if path is not None else MEMORY_DEFAULT
    return _load(
        target,
        rehydrate_path=None if path is not None else SKILL_ANALYSIS_DEFAULT,
        patched_unban=_PATCHED_UNBAN,
    )


def save_memory(memory: Mapping[str, Any], path: Path | None = None) -> Path:
    """Persist live memory under the configured artifact root."""

    from jevops.memory import save_memory as _save

    target = Path(path) if path is not None else MEMORY_DEFAULT
    return _save(memory, target, patched_unban=_PATCHED_UNBAN)
