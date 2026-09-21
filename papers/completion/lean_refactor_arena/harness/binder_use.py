"""LRA adapter — Lean binder gates live in JevOps."""
from __future__ import annotations

from pathlib import Path

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
