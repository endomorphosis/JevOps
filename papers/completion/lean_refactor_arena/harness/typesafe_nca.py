#!/usr/bin/env python3
"""LRA TypeSafe NCA walker: Lean feed/mutate and harness file walk.

Tick, halt, neighborhood, fork, and the cell store live in `jevops.nca`.
Lake and `tasks.json` stay in this harness. Jev does not write Lean.
Never docker0. Not Track 2.
"""
from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path
from typing import Any, Mapping, Optional

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
WALK_MAX_FILES = 80

import _jevops_path  # noqa: F401
import typesafe_tools as lra_tools
from jevops.nca import (  # noqa: E402
    BUDGET_PTR,
    ENERGY_CLIP,
    FORK_MAX,
    STALE_SECONDS,
    canonical_cell_id,
    charge_budget,
    fork_cells,
    journal_event,
    merge_alias_cells,
    mutate_energy,
    neighborhood,
    replay_journal,
    should_halt,
    tick,
    upsert_from_event,
    _cell,
    _clip,
    _grid,
)


def feed_state(memory: dict[str, Any], *, tactics: str = "", problem: str = "") -> dict[str, Any]:
    """Overlay memory plus LRA Lean residuals / decision tree."""

    import portable_rewrites as lra_port
    from jevops.nca import feed_with_overlays
    from jevops.nca import invert_multimap

    counts = lra_port.analyze_residuals(tactics) if tactics else None
    tree = lra_port.decision_tree(tactics, memory=memory, name=problem) if tactics else None
    return feed_with_overlays(
        memory,
        tactics=tactics,
        problem=problem,
        counts=counts,
        inverse=invert_multimap(lra_port.SKILL_RESIDUAL) if counts else None,
        tree=tree,
    )


def _safe_path(path: str | Path) -> Optional[Path]:
    from jevops.nca import allowed_path

    return allowed_path(path, roots=(HERE.resolve(), PAPER_ROOT.resolve()), base=HERE)


def hook_and_eval(path: str | Path) -> dict[str, Any]:
    """Walk one harness/paper file: AST, import, whether a test module names it."""

    from jevops.nca import inspect_python

    return inspect_python(
        path,
        roots=(HERE.resolve(), PAPER_ROOT.resolve()),
        base=HERE,
        import_dir=HERE,
        test_dir=HERE,
        relative_to=PAPER_ROOT.resolve(),
    )


def walk_codebase(*, limit: int = WALK_MAX_FILES) -> dict[str, Any]:
    """Hook every harness Python file (bounded)."""

    from jevops.nca import walk_python

    return walk_python(
        HERE,
        limit=limit,
        roots=(HERE.resolve(), PAPER_ROOT.resolve()),
        import_dir=HERE,
        test_dir=HERE,
        relative_to=PAPER_ROOT.resolve(),
    )


def evaluate_tests(*names: str) -> dict[str, Any]:
    """Run selected harness unit tests in-process (no lake, no docker0)."""

    from jevops.nca import run_unittests

    return run_unittests(*names, root=HERE)


def mutate(
    memory: dict[str, Any],
    *,
    tactics: str = "",
    problem: str = "",
    op: str = "auto",
) -> dict[str, Any]:
    """Gated mutation: energy reorder/skip plus LRA keep-structure folds.

    Does not rewrite arbitrary repo files. Lake remains the Lean oracle.
    """

    import binder_use as lra_bind
    import portable_rewrites as lra_port
    from jevops.nca import apply_mutate

    def _fold(body: str) -> Optional[dict[str, Any]]:
        from jevops.memory import first_fold

        return first_fold(body, memory.get("skills") or [], fold_fn=lra_port.fold_from_memory_skill)

    def _mint() -> dict[str, Any]:
        prop = lra_bind.propose_skill_from_research(memory, problem)
        if prop.get("keep_structure") and prop.get("mint"):
            lra_bind.expand_skills_from_memory(memory, name=problem, tactics=tactics)
            return prop
        return {}

    return apply_mutate(memory, tactics=tactics, problem=problem, op=op, fold_fn=_fold, mint_fn=_mint)


def nca_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    from jevops.nca import dispatch_tool

    memory = kwargs.get("memory") if isinstance(kwargs.get("memory"), dict) else {}
    tactics = str(kwargs.get("tactics") or "")
    problem = str(kwargs.get("problem") or "")
    return dispatch_tool(
        name,
        extras={
            "nca_walk": lambda **_k: walk_codebase(),
            "nca_hook": lambda **k: hook_and_eval(str(k.get("path") or "portable_rewrites.py")),
            "nca_mutate": lambda **k: mutate(
                memory, tactics=tactics, problem=problem, op=str(k.get("op") or "auto")
            ),
            "nca_eval": lambda **k: evaluate_tests(*list(k.get("tests") or ["test_skill_improve_loop"])),
        },
        **kwargs,
    )


def _nca_tick_entry(**kwargs: Any) -> dict[str, Any]:
    mem = kwargs.get("memory") if isinstance(kwargs.get("memory"), dict) else {}
    rec = kwargs.get("record") if isinstance(kwargs.get("record"), dict) else {}
    problem = str(kwargs.get("problem") or rec.get("name") or "")
    return tick(mem, tactics=str(kwargs.get("tactics") or ""), problem=problem)


lra_tools.register_subloop("nca_tick", _nca_tick_entry)
lra_tools.register_subloop(
    "nca_fork",
    lambda **kw: fork_cells(
        kw.get("memory") if isinstance(kw.get("memory"), dict) else {},
        **{k: v for k, v in kw.items() if k not in {"name", "memory"}},
    ),
)
