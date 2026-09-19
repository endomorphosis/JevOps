#!/usr/bin/env python3
"""Goals / subgoals / tasks plus a graph-of-thoughts in NCA memory.

Inspired by ipfs_accelerate_py agent_supervisor (goal→subgoal→task DAG,
objective heap, plan traces) without campaign DuckDB or leases. Thoughts
are scored by Jev (Choice/Score/Noul milles) and linked to tasks so the
TypeSafe/Grok loop can see *why* a skill was tried. JSON-LD is the graph
interface. Lake is the oracle. Jev does not write Lean. Never docker0.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

from typing import Any, Mapping, Optional

MILLE = 1000
MAX_THOUGHTS = 64
PLAN_STEMS = ("got", "graph_of_thought", "thought_graph", "plan_window", "nca_plan")


def is_plan_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    if "thompson" in text or "cache" in text:
        return False
    if text in {"got", "nca_plan"}:
        return True
    return any(tag in text for tag in PLAN_STEMS if tag != "got") or text.endswith("_got")


def _plan(memory: dict[str, Any]) -> dict[str, Any]:
    plan = memory.setdefault("nca", {}).setdefault("plan", {})
    plan.setdefault("goals", [])
    plan.setdefault("subgoals", [])
    plan.setdefault("tasks", [])
    plan.setdefault("thoughts", [])
    plan.setdefault("thought_edges", [])
    return plan


def seed_plan(memory: dict[str, Any], *, board: Optional[Mapping[str, Any]] = None, force: bool = False) -> dict[str, Any]:
    """Copy the LRA board into nca.plan. No campaign write."""

    from jevops import hooks

    plan = _plan(memory)
    if plan.get("goals") and not force:
        return {"ok": True, "skipped": "already_seeded", "n_tasks": len(plan.get("tasks") or [])}
    loader = hooks.get("load_board") or hooks.try_import("board_graph", "load_lra_board")
    data = dict(board or (loader() if loader else {}))
    bg = hooks.try_import("board_graph")
    root = str(
        hooks.call("root_goal", default=None)
        or getattr(bg, "ROOT_GOAL", None)
        or data.get("root_goal")
        or ((data.get("goals") or [{}])[0].get("id") if data.get("goals") else None)
        or "G000"
    )
    plan["goals"] = [
        {
            "id": root,
            "title": data.get("goal_title"),
            "status": "active",
            "ptr": f"ptr://goal/{root}",
        }
    ]
    plan["subgoals"] = [
        {
            "id": s["id"],
            "title": s.get("title"),
            "parent": root,
            "blocked": bool(s.get("blocked")),
            "status": "blocked" if s.get("blocked") else "todo",
            "ptr": f"ptr://subgoal/{s['id']}",
        }
        for s in data.get("subgoals") or []
    ]
    plan["tasks"] = [
        {
            "id": t["id"],
            "title": t.get("title"),
            "subgoal_id": t.get("subgoal_id"),
            "depends_on": list(t.get("depends_on") or []),
            "blocked": bool(t.get("blocked")),
            "status": t.get("status") or ("blocked" if t.get("blocked") else "todo"),
            "ptr": f"ptr://task/{t['id']}",
        }
        for t in data.get("tasks") or []
    ]
    _sync_jsonld(memory)
    return {
        "ok": True,
        "n_goals": len(plan["goals"]),
        "n_subgoals": len(plan["subgoals"]),
        "n_tasks": len(plan["tasks"]),
        "campaign_write": False,
        "called_docker0": False,
    }


def add_thought(
    memory: dict[str, Any],
    *,
    kind: str = "generate",
    text: str = "",
    task_id: str = "",
    subgoal_id: str = "",
    parent_ids: Optional[list[str]] = None,
    score_m: int = 0,
    noul_m: int = 0,
    skill: str = "",
) -> dict[str, Any]:
    """Append a graph-of-thoughts node (bounded)."""

    plan = _plan(memory)
    thoughts = list(plan.get("thoughts") or [])
    tid = f"T{len(thoughts) + 1:04d}"
    node = {
        "id": tid,
        "kind": str(kind or "generate"),
        "text": str(text or "")[:240],
        "task_id": str(task_id or ""),
        "subgoal_id": str(subgoal_id or ""),
        "parent_ids": [str(p) for p in (parent_ids or []) if p],
        "score_m": int(score_m),
        "noul_m": int(noul_m),
        "skill": str(skill or ""),
        "ptr": f"ptr://cell/thought/{tid}",
        "status": "open",
    }
    thoughts.append(node)
    plan["thoughts"] = thoughts[-MAX_THOUGHTS:]
    edges = list(plan.get("thought_edges") or [])
    for parent in node["parent_ids"]:
        edges.append([f"ptr://cell/thought/{parent}", node["ptr"]])
    if node["task_id"]:
        edges.append([f"ptr://task/{node['task_id']}", node["ptr"]])
    plan["thought_edges"] = edges[-128:]
    _sync_jsonld(memory)
    return node


def record_jev(
    memory: dict[str, Any],
    *,
    choice: str = "",
    score_m: int = 0,
    noul_m: int = 0,
    task_id: str = "",
    skill: str = "",
    text: str = "",
) -> dict[str, Any]:
    """Jev Choice/Score/Noul becomes a scored thought on the current task."""

    return add_thought(
        memory,
        kind="score",
        text=text or f"jev choice={choice}",
        task_id=task_id,
        parent_ids=[t["id"] for t in (_plan(memory).get("thoughts") or [])[-1:]],
        score_m=score_m,
        noul_m=noul_m,
        skill=skill or choice,
    )


def keep_best_thoughts(memory: dict[str, Any], *, k: int = 4) -> list[dict[str, Any]]:
    thoughts = list(_plan(memory).get("thoughts") or [])
    ranked = sorted(thoughts, key=lambda t: (-int(t.get("score_m") or 0), int(t.get("noul_m") or 0)))
    return ranked[: max(1, int(k))]


def plan_window(memory: Mapping[str, Any]) -> dict[str, Any]:
    plan = dict((memory.get("nca") or {}).get("plan") or {})
    tasks = [t for t in plan.get("tasks") or [] if not t.get("blocked")]
    thoughts = list(plan.get("thoughts") or [])[-6:]
    return {
        "goal": (plan.get("goals") or [{}])[0].get("id"),
        "n_subgoals": len(plan.get("subgoals") or []),
        "n_tasks": len(plan.get("tasks") or []),
        "ready_tasks": [t.get("id") for t in tasks if str(t.get("status") or "") in {"todo", "ready", ""}][:6],
        "thoughts": [{"id": t.get("id"), "kind": t.get("kind"), "score_m": t.get("score_m"), "skill": t.get("skill")} for t in thoughts],
        "best": [{"id": t.get("id"), "score_m": t.get("score_m")} for t in keep_best_thoughts(dict(memory), k=3)],
    }


def _sync_jsonld(memory: dict[str, Any]) -> None:
    try:
        from jevops import jsonld as lra_ld

        plan = _plan(memory)
        edges: list[list[str]] = []
        for s in plan.get("subgoals") or []:
            edges.append([f"ptr://goal/{s.get('parent') or (plan.get('goals') or [{}])[0].get('id') or 'G000'}", str(s.get("ptr") or "")])
        for t in plan.get("tasks") or []:
            if t.get("subgoal_id"):
                edges.append([f"ptr://subgoal/{t['subgoal_id']}", str(t.get("ptr") or "")])
            for dep in t.get("depends_on") or []:
                edges.append([f"ptr://task/{dep}", str(t.get("ptr") or "")])
        for e in plan.get("thought_edges") or []:
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                edges.append([str(e[0]), str(e[1])])
        if edges:
            doc = lra_ld.document_from_edges(edges)
            existing = ((memory.get("nca") or {}).get("jsonld") or {}).get("@graph") or []
            # Merge without dropping prior graph nodes
            seen = {n.get("@id") for n in existing if isinstance(n, dict)}
            merged = list(existing)
            for item in doc.get("@graph") or []:
                if item.get("@id") not in seen:
                    merged.append(item)
                    seen.add(item.get("@id"))
            doc["@graph"] = merged
            lra_ld.put_jsonld(memory, doc)
    except Exception:
        pass


def call_plan(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    _ = tactics
    text = str(stem or "").lower()
    seeded = seed_plan(memory)
    if "thought" in text or "got" in text:
        if problem:
            add_thought(memory, kind="generate", text=f"work {problem}", skill="keep")
        best = keep_best_thoughts(memory)
        window = plan_window(memory)
        return {
            "ok": True,
            "kind": "port_got",
            "n_thoughts": len((_plan(memory).get("thoughts") or [])),
            "best": best,
            "window": window,
            "writes_lean": False,
            "called_docker0": False,
            "campaign_write": False,
        }
    return {
        "ok": True,
        "kind": "port_nca_plan",
        "n_goals": seeded.get("n_goals") or len(_plan(memory).get("goals") or []),
        "n_subgoals": len(_plan(memory).get("subgoals") or []),
        "n_tasks": len(_plan(memory).get("tasks") or []),
        "window": plan_window(memory),
        "writes_lean": False,
        "called_docker0": False,
        "campaign_write": False,
    }
