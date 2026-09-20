#!/usr/bin/env python3
"""Generic goal/subgoal/task DAG on the NCA grid.

Implementations load a board dict (LRA: tasks.json). This module never
writes a campaign DB and does not write Lean.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def ptr(kind: str, ident: str) -> str:
    return f"ptr://{kind}/{ident}"


def board_from_payload(
    data: Mapping[str, Any],
    *,
    root: str,
    blocked: Sequence[str] = (),
    code_paths_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Normalize a tasks.json-like payload into a kernel board dict."""

    from jevops.outer import head_chars

    banned = {str(item) for item in blocked}
    subgoals = [
        {
            "id": str(row.get("id") or ""),
            "title": str(row.get("title") or ""),
            "parent": root,
            "blocked": str(row.get("id") or "") in banned,
        }
        for row in data.get("subgoals") or []
        if row.get("id")
    ]
    tasks: list[dict[str, Any]] = []
    for row in data.get("tasks") or []:
        tid = str(row.get("id") or "")
        if not tid:
            continue
        if code_paths_fn is not None:
            paths = list(code_paths_fn(row) or [])
        else:
            paths = [str(p) for p in (row.get("code_paths") or []) if p]
        tasks.append(
            {
                "id": tid,
                "title": str(row.get("title") or ""),
                "subgoal_id": str(row.get("subgoal_id") or ""),
                "depends_on": [str(d) for d in (row.get("depends_on") or []) if d],
                "code_paths": paths,
                "blocked": tid in banned or str(row.get("subgoal_id") or "") in banned,
                "status": "blocked" if tid in banned else "todo",
            }
        )
    return {
        "root": root,
        "goal_title": head_chars(data.get("goal") or data.get("goal_title") or "", 240),
        "subgoals": subgoals,
        "tasks": tasks,
        "n_subgoals": len(subgoals),
        "n_tasks": len(tasks),
        "called_docker0": False,
        "campaign_write": False,
    }


def prepare_overlay(
    memory: dict[str, Any],
    *,
    seed_fn: Optional[Any] = None,
    cache: bool = True,
) -> Optional[dict[str, Any]]:
    """Seed the grid if empty. Return a cached overlay result, else None to fetch."""

    grid = ((memory.get("nca") or {}).get("grid") or {})
    if seed_fn is not None and not any(str(cid).startswith("ptr://goal/") for cid in grid):
        seed_fn(memory)
    if cache and (memory.get("nca") or {}).get("overlay_done"):
        return {
            "ok": True,
            "overlay": True,
            "reason": "cached",
            "campaign_write": False,
            "called_docker0": False,
        }
    return None


def overlay_task_status(
    memory: dict[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    *,
    prefix: str = "",
    alias_keys: Sequence[str] = ("task_alias", "id", "task_id"),
    status_keys: Sequence[str] = ("status", "state"),
) -> dict[str, Any]:
    """Copy live task status onto existing grid cells. Never writes a campaign DB."""

    grid = memory.setdefault("nca", {}).setdefault("grid", {})
    n_overlaid = 0
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        alias = ""
        for key in alias_keys:
            alias = str(task.get(key) or "")
            if alias:
                break
        if prefix and not alias.startswith(prefix):
            continue
        cid = ptr("task", alias)
        if cid not in grid or not isinstance(grid[cid], dict):
            continue
        status = ""
        for key in status_keys:
            status = str(task.get(key) or "")
            if status:
                break
        if status:
            grid[cid]["status"] = status
            n_overlaid += 1
        if status in {"ready", "todo", "needed"}:
            grid[cid]["blocked"] = False
            if status == "ready":
                grid[cid]["energy"] = max(float(grid[cid].get("energy") or 0.5), 0.55)
        if status in {"completed", "done"}:
            grid[cid]["energy"] = min(float(grid[cid].get("energy") or 0.5), 0.15)
        if status == "blocked":
            grid[cid]["blocked"] = True
            grid[cid]["do_not_fork"] = True
            grid[cid]["energy"] = min(float(grid[cid].get("energy") or 0.5), 0.05)
    return {"ok": True, "n_overlaid": n_overlaid, "campaign_write": False}


def mark_ready_tasks(
    memory: dict[str, Any],
    tasks: Sequence[Any],
    *,
    prefix: str = "",
) -> dict[str, Any]:
    """Force matching task cells to ready. Never writes a campaign DB."""

    normalized: list[dict[str, str]] = []
    for item in tasks or []:
        if isinstance(item, dict):
            alias = str(item.get("task_alias") or item.get("id") or "")
        else:
            alias = str(getattr(item, "task_alias", "") or getattr(item, "id", "") or "")
        if alias:
            normalized.append({"task_alias": alias, "status": "ready"})
    out = overlay_task_status(memory, normalized, prefix=prefix)
    n_ready = int(out.get("n_overlaid") or 0)
    if n_ready:
        refresh_board_window(memory)
    return {"ok": True, "n_ready": n_ready, "campaign_write": False}


def seed_token_cells(
    memory: dict[str, Any],
    tokens: Mapping[str, int],
    *,
    warmup: Optional[Mapping[str, int]] = None,
    kind: str = "theorem",
    link_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Upsert token counts onto named cells. No lake. No campaign write."""

    warm_map = dict(warmup or {})
    n = 0
    for name, tok in (tokens or {}).items():
        if not name:
            continue
        if link_fn is not None:
            link_fn(memory, str(name))
        cid = ptr(kind, str(name))
        grid = (memory.get("nca") or {}).get("grid") or {}
        if isinstance(grid.get(cid), dict):
            grid[cid]["tokens"] = int(tok)
            warm = warm_map.get(name)
            if warm is not None:
                grid[cid]["warmup_tokens"] = int(warm)
                grid[cid]["remaining_cut"] = max(0, int(warm) - int(tok))
            n += 1
    refresh_board_window(memory)
    return {"ok": True, "n_theorems": n, "campaign_write": False}


def finish_overlay(
    memory: dict[str, Any],
    live: Mapping[str, Any],
    *,
    prefix: str = "",
    reason: str = "",
    cache: bool = True,
    ready_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Apply a fetched live board onto the grid. Never writes a campaign DB."""

    overlaid = overlay_task_status(memory, list(live.get("tasks") or []), prefix=prefix)
    n_overlaid = int(overlaid.get("n_overlaid") or 0)
    memory.setdefault("nca", {})["live_overlay"] = {"n_overlaid": n_overlaid, "reason": reason}
    refresh_board_window(memory)
    if cache:
        memory["nca"]["overlay_done"] = True
    extra_ready = ready_fn() if ready_fn is not None else {"ok": True, "n_ready": 0}
    return {
        "ok": True,
        "overlay": True,
        "n_overlaid": n_overlaid,
        "reason": reason,
        "ready_overlay": extra_ready,
        "campaign_write": False,
        "called_docker0": False,
    }


def overlay_ready(
    memory: dict[str, Any],
    *,
    ready_fn: Optional[Any] = None,
    replica_fn: Optional[Any] = None,
    prefix: str = "",
    env_key: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Mark ready tasks. replica_fn/ready_fn are injected. Never writes a campaign DB."""

    import os

    from jevops.jev import env_truthy

    source_reason = "injected"
    if ready_fn is None:
        source = env if env is not None else os.environ
        if env_key and not env_truthy(source.get(env_key)):
            return {"ok": True, "n_ready": 0, "reason": "no_ready_fn", "campaign_write": False}
        if replica_fn is None:
            return {"ok": True, "n_ready": 0, "reason": "no_ready_fn", "campaign_write": False}
        replica = dict(replica_fn() or {})
        if not replica.get("ok"):
            return {
                "ok": True,
                "n_ready": 0,
                "reason": str(replica.get("reason") or "env_set_no_source"),
                "campaign_write": False,
            }
        page: Any = replica
        source_reason = "replica"
    else:
        try:
            page = ready_fn()
        except Exception as exc:
            return {"ok": False, "n_ready": 0, "reason": type(exc).__name__, "campaign_write": False}
    tasks = page.get("tasks") if isinstance(page, dict) else getattr(page, "tasks", ()) or ()
    marked = mark_ready_tasks(memory, list(tasks or []), prefix=prefix)
    return {
        "ok": True,
        "n_ready": int(marked.get("n_ready") or 0),
        "reason": source_reason,
        "campaign_write": False,
    }


def overlay_or_empty(
    memory: dict[str, Any],
    live: Any,
    *,
    reason: str,
    prefix: str = "",
    cache: bool = True,
    ready_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Finish overlay if live has tasks; else cache-closed empty overlay."""

    if not isinstance(live, dict) or not live.get("tasks"):
        if cache:
            memory.setdefault("nca", {})["overlay_done"] = True
        return {
            "ok": True,
            "overlay": False,
            "reason": reason,
            "campaign_write": False,
            "called_docker0": False,
        }
    return finish_overlay(
        memory,
        live,
        prefix=prefix,
        reason=reason,
        cache=cache,
        ready_fn=ready_fn,
    )


def codepath_ptr(path: str, *, strip_prefix: str = "") -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return ""
    if strip_prefix and text.startswith(strip_prefix):
        text = text[len(strip_prefix) :]
    return ptr("codepath", text.replace("/", ".").replace(".py", ""))


def board_payload(
    ident: str,
    board: Mapping[str, Any],
    *,
    path_ptr: Optional[Any] = None,
) -> dict[str, Any]:
    data = dict(board or {})
    root = str(data.get("root") or "G000")
    ptr_fn = path_ptr or codepath_ptr
    if ident == data.get("root") or ident == root:
        return {
            "kind": "goal",
            "id": root,
            "title": data.get("goal_title"),
            "children": [f"ptr://subgoal/{s['id']}" for s in data.get("subgoals") or []],
            "blocked": False,
        }
    for sub in data.get("subgoals") or []:
        if sub["id"] == ident:
            kids = [f"ptr://task/{t['id']}" for t in data.get("tasks") or [] if t.get("subgoal_id") == ident]
            return {
                "kind": "subgoal",
                "id": ident,
                "title": sub.get("title"),
                "parent": f"ptr://goal/{root}",
                "children": kids,
                "blocked": bool(sub.get("blocked")),
            }
    for task in data.get("tasks") or []:
        if task["id"] == ident:
            return {
                "kind": "task",
                "id": ident,
                "title": task.get("title"),
                "parent": f"ptr://subgoal/{task.get('subgoal_id')}",
                "depends_on": [f"ptr://task/{d}" for d in task.get("depends_on") or []],
                "code_paths": [ptr_fn(p) for p in task.get("code_paths") or [] if ptr_fn(p)],
                "blocked": bool(task.get("blocked")),
                "status": task.get("status"),
            }
    return {"ok": False, "reason": "unknown_board_id", "id": ident}


def refresh_board_window(memory: dict[str, Any], *, root_goal: str = "") -> list[dict[str, Any]]:
    nca = memory.setdefault("nca", {})
    grid = nca.setdefault("grid", {})
    root_id = str(root_goal or "")
    if not root_id:
        for cid in grid:
            if str(cid).startswith("ptr://goal/"):
                root_id = str(cid).rsplit("/", 1)[-1]
                break
        root_id = root_id or "G000"
    root = ptr("goal", root_id)
    window: list[dict[str, Any]] = []
    goal = grid.get(root) if isinstance(grid.get(root), dict) else {}
    if goal:
        window.append({"id": root_id, "kind": "goal", "energy": goal.get("energy")})
    cuts = [
        {
            "id": str(cid).rsplit("/", 1)[-1],
            "kind": "theorem",
            "energy": cell.get("energy"),
            "remaining_cut": int(cell.get("remaining_cut") or 0),
            "tokens": cell.get("tokens"),
        }
        for cid, cell in grid.items()
        if isinstance(cell, dict)
        and (cell.get("kind") in {"theorem", "proof"} or "/theorem/" in str(cid))
        and int(cell.get("remaining_cut") or 0) > 0
    ]
    cuts.sort(key=lambda row: int(row.get("remaining_cut") or 0), reverse=True)
    from jevops.outer import head_seq

    window.extend(head_seq(cuts, 3))
    subs = [
        {
            "id": str(cid).rsplit("/", 1)[-1],
            "kind": "subgoal",
            "energy": cell.get("energy"),
            "blocked": bool(cell.get("blocked")),
        }
        for cid, cell in grid.items()
        if isinstance(cell, dict) and cell.get("kind") == "subgoal"
    ]
    subs.sort(key=lambda row: float(row.get("energy") or 0), reverse=True)
    window.extend(head_seq(subs, 6))
    ready = [
        {
            "id": str(cid).rsplit("/", 1)[-1],
            "kind": "task",
            "energy": cell.get("energy"),
            "status": cell.get("status"),
            "visited": bool(cell.get("visited")),
        }
        for cid, cell in grid.items()
        if isinstance(cell, dict)
        and cell.get("kind") == "task"
        and not cell.get("do_not_fork")
        and str(cell.get("status") or "") in {"ready", "todo", "needed", ""}
    ]
    ready.sort(key=lambda row: (0 if row.get("status") == "ready" else 1, -float(row.get("energy") or 0)))
    window.extend(head_seq(ready, 6))
    nca["board_window"] = head_seq(window, 12)
    return window


def credit_result(
    memory: dict[str, Any],
    *,
    theorem: str,
    task_id: str = "",
    subgoal_id: str = "",
    theorem_ok: bool,
    tokens: int = 0,
) -> dict[str, Any]:
    """Push an oracle result onto theorem/task/subgoal cells."""

    from jevops.nca import upsert_from_event

    name = str(theorem or "")
    if not name:
        return {"ok": False, "reason": "no_theorem"}
    thm_ptr = ptr("theorem", name)
    task_ptr = ptr("task", task_id) if task_id else ""
    sub_ptr = ptr("subgoal", subgoal_id) if subgoal_id else ""
    upsert_from_event(
        memory,
        ptr=thm_ptr,
        kind="theorem",
        energy=0.75 if theorem_ok else 0.25,
        theorem_ok=theorem_ok,
        tokens=tokens,
        parent_ptr=task_ptr,
    )
    if task_ptr:
        upsert_from_event(
            memory,
            ptr=task_ptr,
            kind="task",
            energy=0.75 if theorem_ok else 0.25,
            theorem_ok=theorem_ok,
            tokens=tokens,
            parent_ptr=sub_ptr,
        )
        grid = (memory.get("nca") or {}).get("grid") or {}
        if isinstance(grid.get(task_ptr), dict):
            grid[task_ptr]["visited"] = True
    grid = (memory.get("nca") or {}).get("grid") or {}
    if isinstance(grid.get(thm_ptr), dict) and tokens:
        cell = grid[thm_ptr]
        cell["tokens"] = int(tokens)
        warm = int(cell.get("warmup_tokens") or 0)
        if warm:
            cell["remaining_cut"] = max(0, warm - int(tokens))
    return {"ok": True, "task": task_ptr, "subgoal": sub_ptr, "theorem": thm_ptr, "theorem_ok": theorem_ok}


def link_entity(
    memory: dict[str, Any],
    *,
    ident: str,
    kind: str = "theorem",
    parent_ptr: str = "",
    energy: float = 0.55,
) -> dict[str, Any]:
    """Upsert a cell and optionally edge it to a parent."""

    from jevops.nca import upsert_from_event

    name = str(ident or "")
    if not name:
        return {"ok": False, "reason": "no_id"}
    cid = ptr(kind, name) if not name.startswith("ptr://") else name
    upsert_from_event(memory, ptr=cid, kind=kind, energy=energy)
    if parent_ptr:
        edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
        pair = [cid, parent_ptr]
        if pair not in edges:
            edges.append(pair)
    return {"ok": True, "id": cid, "parent": parent_ptr}


def board_window(memory: Mapping[str, Any]) -> list[dict[str, Any]]:
    from jevops.outer import head_seq

    return head_seq(((memory.get("nca") or {}).get("board_window")) or [], 8)


def seed_grid_from_board(
    memory: dict[str, Any],
    board: Mapping[str, Any],
    *,
    force: bool = False,
    path_ptr: Optional[Any] = None,
) -> dict[str, Any]:
    """Insert goal/subgoal/task/codepath cells. No campaign write."""

    from jevops import nca as lra_nca
    from jevops import plan as lra_plan

    nca = memory.setdefault("nca", {})
    grid = nca.setdefault("grid", {})
    if not force and any(str(cid).startswith("ptr://goal/") for cid in grid):
        window = refresh_board_window(memory)
        return {
            "ok": True,
            "skipped": "already_seeded",
            "n_cells": len(grid),
            "board_window": window,
            "campaign_write": False,
            "called_docker0": False,
        }
    data = dict(board or {})
    root_id = str(data.get("root") or "G000")
    edges: list[tuple[str, str]] = []

    def _put(cid: str, kind: str, **extra: Any) -> None:
        cell = lra_nca._cell(grid, cid, kind=kind)
        cell["kind"] = kind
        cell.update({k: v for k, v in extra.items() if v is not None})
        if extra.get("blocked"):
            cell["energy"] = min(float(cell.get("energy") or 0.5), 0.05)
            cell["do_not_fork"] = True

    root = ptr("goal", root_id)
    _put(root, "goal", title=data.get("goal_title"), blocked=False)
    for sub in data.get("subgoals") or []:
        sid = ptr("subgoal", sub["id"])
        _put(sid, "subgoal", title=sub.get("title"), blocked=sub.get("blocked"))
        edges.append((root, sid))
    for task in data.get("tasks") or []:
        tid = ptr("task", task["id"])
        _put(
            tid,
            "task",
            title=task.get("title"),
            blocked=task.get("blocked"),
            status=task.get("status"),
        )
        if task.get("subgoal_id"):
            edges.append((ptr("subgoal", task["subgoal_id"]), tid))
        for dep in task.get("depends_on") or []:
            edges.append((ptr("task", dep), tid))
        to_ptr = path_ptr or codepath_ptr
        for path in task.get("code_paths") or []:
            cptr = to_ptr(path)
            if not cptr:
                continue
            _put(cptr, "codepath", path=path, blocked=False)
            edges.append((tid, cptr))
    nca["board_edges"] = [list(edge) for edge in edges]
    try:
        lra_plan.seed_plan(memory, board=data, force=force)
    except Exception:
        pass
    seen: set[tuple[str, str]] = set()
    uniq: list[list[str]] = []
    for edge in nca.get("board_edges") or []:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        pair = (str(edge[0]), str(edge[1]))
        if pair in seen:
            continue
        seen.add(pair)
        uniq.append([pair[0], pair[1]])
    nca["board_edges"] = uniq
    memory["nca"] = nca
    refresh_board_window(memory, root_goal=root_id)
    return {
        "ok": True,
        "n_cells": len(grid),
        "n_edges": len(edges),
        "n_subgoals": data.get("n_subgoals") or len(data.get("subgoals") or []),
        "n_tasks": data.get("n_tasks") or len(data.get("tasks") or []),
        "campaign_write": False,
        "called_docker0": False,
    }
