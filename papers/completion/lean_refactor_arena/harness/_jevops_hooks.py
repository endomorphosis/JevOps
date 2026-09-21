"""Register LRA implementation hooks on the JevOps kernel.

Lazy wrappers so importing this file does not import Lean/lake modules.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent


def _lazy(module: str, attr: str) -> Callable[..., Any]:
    def fn(*args: Any, **kwargs: Any) -> Any:
        mod = importlib.import_module(module)
        return getattr(mod, attr)(*args, **kwargs)

    fn.__name__ = attr
    fn.__qualname__ = f"{module}.{attr}"
    return fn


def _const(module: str, attr: str, default: Any = None) -> Callable[[], Any]:
    def fn() -> Any:
        try:
            mod = importlib.import_module(module)
            return getattr(mod, attr, default)
        except Exception:
            return default

    return fn


def register_lra_hooks() -> None:
    from jevops import hooks

    if hooks.get("_lra_registered"):
        return
    hooks.register("_lra_registered", lambda: True)
    hooks.register("harness_dir", lambda: HERE)
    hooks.register("mcp_catalog_path", lambda: HERE.parent / "evidence" / "canaries" / "mcp-catalog.json")
    hooks.register("load_board", _lazy("board_graph", "load_lra_board"))
    hooks.register("seed_board", _lazy("board_graph", "seed_nca_from_board"))
    hooks.register("overlay_board", _lazy("board_graph", "overlay_live_board"))
    hooks.register("board_payload", _lazy("board_graph", "board_payload"))
    hooks.register("board_window", _lazy("board_graph", "board_window"))
    hooks.register("credit_theorem", _lazy("board_graph", "credit_theorem"))
    hooks.register("root_goal", _const("board_graph", "ROOT_GOAL", "LRA-G000"))
    hooks.register("blocked_ids", _const("board_graph", "BLOCKED", frozenset()))
    hooks.register("decision_tree", _lazy("portable_rewrites", "decision_tree"))
    hooks.register("portable_drafts", _lazy("portable_rewrites", "portable_drafts"))
    hooks.register("compose_pipeline", _lazy("portable_rewrites", "compose_pipeline"))
    hooks.register("analyze_residuals", _lazy("portable_rewrites", "analyze_residuals"))
    hooks.register("pipeline_order", _lazy("portable_rewrites", "pipeline_order"))
    hooks.register(
        "skill_residual_map",
        lambda: getattr(importlib.import_module("portable_rewrites"), "SKILL_RESIDUAL", {}),
    )
    hooks.register("token_count", _lazy("run_warmup", "token_count"))
    hooks.register("symbol_search", _lazy("symbol_search", "search_symbols"))
    hooks.register("find_holes", _lazy("mca_mask_replace", "find_holes"))
    hooks.register("mask_skeleton", _lazy("mca_mask_replace", "mask_skeleton"))
    hooks.register("find_symbol_holes", _lazy("symbol_diffuse", "find_symbol_holes"))
    hooks.register("closed_candidates", _lazy("symbol_diffuse", "closed_candidates"))
    hooks.register("nca_tick", _lazy("typesafe_nca", "tick"))
    hooks.register("nca_mutate", _lazy("typesafe_nca", "mutate"))
    hooks.register("feed_state", _lazy("typesafe_nca", "feed_state"))
    hooks.register("diagnose", _lazy("nca_repair", "diagnose"))
    hooks.register("nca_tool", _lazy("typesafe_nca", "nca_tool"))
    hooks.register("eval_theorem", _lazy("typesafe_inner", "eval_theorem"))
    hooks.register("apply_lake_round", _lazy("typesafe_inner", "apply_lake_round"))
    hooks.register("slice_codepath", _lazy("codepath_graph", "slice_cross_module"))
    hooks.register("is_inspect_only", _lazy("codepath_graph", "is_inspect_only"))
    hooks.register("leanstral_generate", _lazy("track1_mistral_leanstral", "generate_mistral"))
    hooks.register("track1_error", _const("track1_ledger", "Track1LedgerError"))
    hooks.register("fire_t", _const("random_canary", "FIRE_T", 0.7))
    hooks.register("propose_skill", _lazy("binder_use", "propose_skill_from_research"))
    hooks.register("expand_skills", _lazy("binder_use", "expand_skills_from_memory"))
    hooks.register("load_keyfile", _lazy("pca_mca_fanout", "load_keyfile"))
    hooks.register("pin_typesafe", _lazy("pca_mca_fanout", "pin_typesafe_path"))
    hooks.register("install_fold", _lazy("binder_use", "install_memory_skill"))
    hooks.register(
        "memory_default",
        lambda: HERE.parent / "evidence" / "canaries" / "refactor-memory.json",
    )
    hooks.register(
        "skill_analysis_default",
        lambda: HERE.parent / "evidence" / "canaries" / "skill-analysis.json",
    )
