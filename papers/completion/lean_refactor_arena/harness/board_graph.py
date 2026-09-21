#!/usr/bin/env python3
"""Read-only LRA goal/subgoal/task DAG for the TypeSafe NCA.

Default source is tasks.json (no Quack, no campaign writes). Optional
fetch_board overlay is injected by the caller. Never docker0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

import _jevops_path  # noqa: F401
from jevops.board import board_window as kernel_board_window
from jevops.board import mark_ready_tasks
from jevops.board import overlay_task_status
from jevops.board import refresh_board_window as kernel_refresh_board_window
from jevops.board import seed_grid_from_board

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
TASKS_JSON = PAPER_ROOT / "tasks.json"
ROOT_GOAL = "LRA-G000"
BLOCKED = frozenset({"LRA-S09", "LRA-S10", "LRA-024", "LRA-025", "LRA-027"})
# Small canaries credit the warmup (S04) or TypeSafe (S05) tasks.
THEOREM_TASKS: dict[str, str] = {
    "CallElimCorrect.substOldPostSubset": "LRA-017",
    "CallElimCorrect.extractedOldExprInVars": "LRA-017",
    "Core.InitsUpdatesComm": "LRA-019",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress": "LRA-017",
    "Cslib.SKI.parallelReduction_diamond": "LRA-017",
    "Cslib.CCS.bisimilarity_congr_choice": "LRA-019",
}


def _ptr(kind: str, ident: str) -> str:
    from jevops.board import ptr

    return ptr(kind, ident)


def _codepath_ptr(path: str) -> str:
    from jevops.outer import path_to_dots, posix_slash, without_prefix

    text = posix_slash(path)
    if not text:
        return ""
    marker = "papers/completion/lean_refactor_arena/harness/"
    if text.startswith(marker):
        text = "harness/" + without_prefix(text, marker)
    return _ptr("codepath", path_to_dots(text))


def load_lra_board(*, path: Optional[Path] = None) -> dict[str, Any]:
    from jevops.board import board_from_payload

    target = path or TASKS_JSON
    from jevops.outer import read_json

    data = read_json(target)

    def _paths(row: Mapping[str, Any]) -> list[str]:
        paths = [str(p) for p in (row.get("suggested_code_paths") or []) if p]
        paths.extend(str(p) for p in (row.get("deliverables") or []) if str(p).endswith(".py"))
        return paths

    return board_from_payload(data, root=ROOT_GOAL, blocked=BLOCKED, code_paths_fn=_paths)


def board_payload(ident: str, board: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    from jevops.board import board_payload as kernel_payload

    data = dict(board or load_lra_board())
    data.setdefault("root", ROOT_GOAL)
    return kernel_payload(ident, data, path_ptr=_codepath_ptr)


def refresh_board_window(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild the compact board_window from current grid energies/status."""

    return kernel_refresh_board_window(memory, root_goal=ROOT_GOAL)


def seed_nca_from_board(memory: dict[str, Any], *, board: Optional[Mapping[str, Any]] = None, force: bool = False) -> dict[str, Any]:
    """Insert goal/subgoal/task/codepath cells and DAG neighbors. No campaign write."""

    data = dict(board or load_lra_board())
    data.setdefault("root", ROOT_GOAL)
    from jevops.board import seed_then_sidecar

    def _sidecar(mem: dict[str, Any], nca: dict[str, Any]) -> None:
        import codepath_graph as lra_cp

        if not nca.get("sidecar_built") and not (lra_cp.SIDECAR_DUCKDB.is_file()):
            built = lra_cp.build_sidecar_duckdb()
            nca["sidecar_built"] = bool(built.get("ok"))
        extra = lra_cp.seed_nca_call_edges(mem)
        if extra.get("ok") and extra.get("n_edges"):
            nca["call_edges"] = extra["n_edges"]

    return seed_then_sidecar(
        memory, data, force=force, path_ptr=_codepath_ptr, sidecar_fn=_sidecar
    )


def board_window(memory: Mapping[str, Any]) -> list[dict[str, Any]]:
    return kernel_board_window(memory)


def warmup_token_map() -> dict[str, int]:
    """Frozen warmup body token counts (local tokenizer). Never rewrites JSONL."""

    from jevops.outer import token_map

    try:
        import run_warmup as lra_loop
        import splice as lra_splice

        _raw, _digest, records = lra_splice.load_warmup_records()
    except Exception:
        return {}

    def _body(rec: Mapping[str, Any]) -> str:
        try:
            return str(lra_splice.split_statement_body(rec).body_suffix)
        except Exception:
            return str(rec.get("src") or "")

    return token_map(records, token_fn=lra_loop.token_count, body_fn=_body)


def credit_theorem(
    memory: dict[str, Any],
    theorem: str,
    *,
    theorem_ok: bool,
    tokens: int = 0,
) -> dict[str, Any]:
    """Push lake result onto the owning theorem/task/subgoal cells."""

    from jevops.board import credit_result

    name = str(theorem or "")
    task_id = THEOREM_TASKS.get(name)
    if not task_id:
        return {"ok": False, "reason": "unmapped_theorem", "theorem": theorem}
    sub_id = "LRA-S05" if task_id == "LRA-019" else "LRA-S04"
    return credit_result(
        memory,
        theorem=name,
        task_id=task_id,
        subgoal_id=sub_id,
        theorem_ok=theorem_ok,
        tokens=tokens,
    )


def link_current_theorem(memory: dict[str, Any], theorem: str) -> dict[str, Any]:
    """Ensure the current canary exists as a theorem cell edged to its task."""

    from jevops.board import link_entity

    name = str(theorem or "")
    task_id = THEOREM_TASKS.get(name)
    parent = _ptr("task", task_id) if task_id else ""
    out = link_entity(memory, ident=name, kind="theorem", parent_ptr=parent, energy=0.55)
    return {"ok": out.get("ok"), "theorem": out.get("id"), "task": parent, "reason": out.get("reason")}


def seed_keepbest_theorems(
    memory: dict[str, Any], tokens: Mapping[str, int], *, warmup: Optional[Mapping[str, int]] = None
) -> dict[str, Any]:
    """Upsert theorem cells from keep-best token counts (no lake)."""

    from jevops.board import seed_token_cells

    warm_map = dict(warmup or {}) or warmup_token_map()
    return seed_token_cells(
        memory,
        tokens,
        warmup=warm_map,
        link_fn=lambda mem, name: link_current_theorem(mem, name),
    )


LRA_LANE = _jevops_path.LRA_STATE_ROOT / "lean_refactor_arena"
READY_JSON = LRA_LANE / "quack-owner" / "paper-owner.ready.json"


def overlay_live_board(
    memory: dict[str, Any],
    *,
    fetch_fn: Optional[Any] = None,
    ready_fn: Optional[Any] = None,
    lane: Optional[Path] = None,
) -> dict[str, Any]:
    """Read-only status overlay from fetch_board. Never writes campaign DB."""

    from jevops.board import overlay_fetch

    ready = (lane or LRA_LANE) / "quack-owner" / "paper-owner.ready.json"

    def _default_fetch() -> Any:
        import importlib

        from _jevops_path import SCRIPTS_ROOT
        from jevops.outer import ensure_sys_path

        ensure_sys_path(SCRIPTS_ROOT)
        campaign = importlib.import_module("paper_supervisor_campaign")
        return campaign.fetch_board("lean_refactor_arena", lane or LRA_LANE)

    injected = fetch_fn is not None
    live_fn = fetch_fn if injected else (_default_fetch if ready.is_file() else None)
    return overlay_fetch(
        memory,
        seed_fn=seed_nca_from_board,
        fetch_fn=live_fn,
        prefix="LRA-",
        cache=fetch_fn is None,
        ready_fn=lambda: overlay_ready_tasks(memory, ready_fn=ready_fn, lane=lane),
        empty_reason="no_ready_owner",
        injected_reason="injected" if injected else "fetch_board",
        inject_fail="closed" if injected else "cache",
    )


def replica_ready_page(*, lane: Optional[Path] = None) -> dict[str, Any]:
    """Read-only DatabaseTaskSource.ready_tasks. Never CAS, never install_schema."""

    from jevops.board import aliases_from_page, replica_page

    ready_path = (lane or LRA_LANE) / "quack-owner" / "paper-owner.ready.json"
    if not ready_path.is_file():
        return replica_page(ok=False, reason="no_ready_json")
    try:
        from jevops.outer import read_json

        blob = read_json(ready_path)
    except Exception as exc:
        from jevops.outer import exc_name

        return replica_page(ok=False, reason=exc_name(exc))
    endpoint = blob.get("quack_endpoint") or blob.get("database_path")
    if not endpoint:
        return replica_page(ok=False, reason="no_endpoint")
    try:
        from _optional_deps import load_database_task_source

        task_source_module, reason = load_database_task_source()
        if task_source_module is None:
            return replica_page(ok=False, reason=reason)
        DatabaseTaskSource = task_source_module.DatabaseTaskSource

        with DatabaseTaskSource(
            endpoint,
            owner_id="lra-nca-overlay-readonly",
            install_schema=False,
        ) as source:
            page = source.ready_tasks(limit=100)
        return replica_page(ok=True, reason="replica", tasks=aliases_from_page(page, prefix="LRA-"))
    except Exception as exc:
        from jevops.outer import tagged_exc

        return replica_page(ok=False, reason=tagged_exc("source_failed", exc))


def overlay_ready_tasks(
    memory: dict[str, Any], *, ready_fn: Optional[Any] = None, lane: Optional[Path] = None
) -> dict[str, Any]:
    """Mark Source.ready_tasks as ready. Default is no campaign Source (inject ready_fn)."""

    from jevops.board import overlay_ready

    return overlay_ready(
        memory,
        ready_fn=ready_fn,
        replica_fn=(None if ready_fn is not None else (lambda: replica_ready_page(lane=lane))),
        prefix="LRA-",
        env_key="LRA_NCA_READY_TASKS",
    )
