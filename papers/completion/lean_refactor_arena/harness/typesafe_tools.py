"""LRA adapter — TypeSafe tool catalog lives in JevOps."""
from __future__ import annotations

from pathlib import Path

import _jevops_path  # noqa: F401
from jevops import tools as _mod

HERE = Path(__file__).resolve().parent
globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})
# Keep LRA harness path visible to tests and walkers.
globals()["HERE"] = HERE


def run_tool(name: str, **kwargs):
    """Dispatch through JevOps with this harness as the explicit AST root."""

    return _mod.run_tool(name, harness_dir=HERE, **kwargs)
