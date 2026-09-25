#!/usr/bin/env python3
"""TypeSafe NCA cell store: ptr:// ids, grid, energy, journal.

The walker, lake, and Lean folds live in implementations. This module is
the kernel memory of cells. Cache hits never admit proofs. Jev does not
write Lean. Never docker0.

TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

ENERGY_CLIP = (0.0, 1.0)
BUDGET_PTR = "ptr://tool/budget"


def canonical_cell_id(cid: str, *, kind: str = "") -> str:
    """One id per cell: port_foo and ptr://skill/port_foo are the same."""

    raw = str(cid or "").strip()
    if not raw:
        return raw
    if raw.startswith("ptr://"):
        return raw
    if raw.startswith("port_") or raw.startswith("mem_"):
        return f"ptr://skill/{raw}"
    if raw.startswith("residual:"):
        return f"ptr://residual/{raw.split(':', 1)[-1]}"
    if raw.startswith("proof:"):
        return f"ptr://theorem/{raw.split(':', 1)[-1]}"
    if raw.startswith("family:"):
        return f"ptr://family/{raw.split(':', 1)[-1]}"
    if kind == "skill":
        return f"ptr://skill/{raw}"
    if kind in {"goal", "subgoal", "task", "theorem", "codepath", "tool", "rule"}:
        return f"ptr://{kind}/{raw}"
    return raw


def _clip(value: float) -> float:
    lo, hi = ENERGY_CLIP
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number != number:  # NaN
        return 0.5
    return max(lo, min(hi, number))


def _energy_value(cell: Mapping[str, Any], default: float = 0.5) -> float:
    """Read energy without turning an explicit zero into a default."""

    if isinstance(cell, Mapping) and "energy" in cell and cell.get("energy") is not None:
        try:
            return float(cell["energy"])
        except (TypeError, ValueError):
            return float(default)
    return float(default)


def _grid(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return memory.setdefault("nca", {}).setdefault("grid", {})


def _cell(grid: dict[str, dict[str, Any]], cid: str, *, kind: str = "skill") -> dict[str, Any]:
    row = grid.setdefault(
        cid,
        {
            "id": cid,
            "kind": kind,
            "energy": 0.5,
            "wins": 0,
            "losses": 0,
            "help": 0.0,
            "unsafe": 0.0,
            "tokens": 0,
            "tick": 0,
        },
    )
    return row


def merge_alias_cells(memory: dict[str, Any]) -> dict[str, Any]:
    """Collapse duplicate keys onto canonical ptr:// ids."""

    grid = _grid(memory)
    merged: dict[str, dict[str, Any]] = {}
    for cid, cell in list(grid.items()):
        if not isinstance(cell, dict):
            continue
        canon = canonical_cell_id(cid, kind=str(cell.get("kind") or ""))
        if canon not in merged:
            row = dict(cell)
            row["id"] = canon
            merged[canon] = row
            continue
        dst = merged[canon]
        dst["wins"] = int(dst.get("wins") or 0) + int(cell.get("wins") or 0)
        dst["losses"] = int(dst.get("losses") or 0) + int(cell.get("losses") or 0)
        dst["energy"] = _clip(max(float(dst.get("energy") or 0), float(cell.get("energy") or 0)))
        dst["visited"] = bool(dst.get("visited") or cell.get("visited"))
        dst["tokens"] = max(int(dst.get("tokens") or 0), int(cell.get("tokens") or 0))
        dst["help"] = max(float(dst.get("help") or 0), float(cell.get("help") or 0))
        dst["unsafe"] = max(float(dst.get("unsafe") or 0), float(cell.get("unsafe") or 0))
        dst["count"] = max(int(dst.get("count") or 0), int(cell.get("count") or 0))
        warm = max(int(dst.get("warmup_tokens") or 0), int(cell.get("warmup_tokens") or 0))
        if warm:
            dst["warmup_tokens"] = warm
            dst["remaining_cut"] = max(0, warm - int(dst.get("tokens") or 0))
    grid.clear()
    grid.update(merged)
    edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
    rewritten = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        src, dst = canonical_cell_id(str(edge[0])), canonical_cell_id(str(edge[1]))
        pair = (src, dst)
        if pair in seen or not src or not dst:
            continue
        seen.add(pair)
        rewritten.append([src, dst])
    memory["nca"]["board_edges"] = rewritten
    return {"ok": True, "n_cells": len(grid)}


def journal_event(
    memory: dict[str, Any],
    *,
    event: str,
    ptr: str = "",
    op: str = "",
    energy_delta: float = 0.0,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    nca = memory.setdefault("nca", {})
    journal = list(nca.get("journal") or [])
    sequence = int(nca.get("journal_sequence") or 0) + 1
    nca["journal_sequence"] = sequence
    row: dict[str, Any] = {
        "event_id": f"journal:{sequence}",
        "tick": int(nca.get("tick") or 0),
        "event": str(event),
        "ptr": str(ptr or ""),
        "op": str(op or ""),
        "energy_delta": round(float(energy_delta), 4),
    }
    if extra:
        row.update(dict(extra))
    journal.append(row)
    nca["journal"] = journal[-128:]


def upsert_from_event(
    memory: dict[str, Any],
    *,
    ptr: str = "",
    kind: str = "cell",
    energy: float = 0.5,
    theorem_ok: Optional[bool] = None,
    tokens: int = 0,
    parent_ptr: str = "",
) -> dict[str, Any]:
    """Tape event → grid cell (unify stores) + optional parent backprop."""

    grid = _grid(memory)
    cid = canonical_cell_id(str(ptr or f"event:{kind}"), kind=kind)
    cell_kind = kind if kind in {"skill", "goal", "subgoal", "task", "codepath", "theorem", "proof", "tool", "family", "residual", "rule"} else "cell"
    cell = _cell(grid, cid, kind=cell_kind)
    old = _energy_value(cell)
    mixed = _clip(0.7 * old + 0.3 * float(energy))
    if theorem_ok is True:
        cell["wins"] = int(cell.get("wins") or 0) + 1
        mixed = max(mixed, 0.7)
    elif theorem_ok is False:
        cell["losses"] = int(cell.get("losses") or 0) + 1
        mixed = min(mixed, 0.35)
    cell["energy"] = mixed
    cell["updated_at"] = time.time()
    if tokens:
        cell["tokens"] = int(tokens)
        warm = int(cell.get("warmup_tokens") or 0)
        if warm:
            cell["remaining_cut"] = max(0, warm - int(tokens))
    cell["visited"] = True
    if parent_ptr and parent_ptr != cid:
        parent_ptr = canonical_cell_id(parent_ptr)
        parent = _cell(grid, parent_ptr, kind=str((grid.get(parent_ptr) or {}).get("kind") or "cell"))
        parent["energy"] = _clip(0.8 * _energy_value(parent) + 0.2 * mixed)
    journal_event(memory, event="upsert", ptr=cid, op=kind, energy_delta=mixed - old)
    return cell


def charge_budget(
    memory: dict[str, Any],
    *,
    ledger: Any = None,
    jev_calls: int = 0,
    usd: float = 0.0,
    event: str = "charge",
) -> dict[str, Any]:
    """Spend is an NCA cell: remaining_usd/budget_usd when a ledger is present."""

    grid = _grid(memory)
    existed = BUDGET_PTR in grid
    cell = _cell(grid, BUDGET_PTR, kind="tool")
    if not existed and not cell.get("visited") and "jev_calls" not in cell:
        cell["energy"] = 1.0
    old = _energy_value(cell, 1.0)
    calls = int(jev_calls)
    spent = float(usd)
    if ledger is not None:
        blob = ledger.as_dict() if hasattr(ledger, "as_dict") else {}
        calls = max(
            calls,
            int(blob.get("jev_calls") or 0)
            + int(blob.get("mistral_calls") or 0)
            + int(blob.get("grok_calls") or 0),
        )
        lines = blob.get("lines") or []
        spent = max(
            spent,
            float(blob.get("spent_usd") or 0),
            sum(float(row.get("usd") or 0) for row in lines if isinstance(row, dict)),
        )
        budget = float(blob.get("budget_usd") or 0)
        remaining = blob.get("remaining_usd")
        if budget > 0 and remaining is not None:
            cell["energy"] = _clip(float(remaining) / budget)
        else:
            cell["energy"] = _clip(old - min(0.25, 0.02 * calls + min(0.2, spent)))
    else:
        cell["energy"] = _clip(old - min(0.25, 0.02 * calls + min(0.2, spent)))
    cell["jev_calls"] = calls
    cell["usd"] = round(spent, 6)
    cell["visited"] = True
    journal_event(
        memory,
        event=event,
        ptr=BUDGET_PTR,
        op="BUDGET",
        energy_delta=float(cell["energy"]) - old,
        extra={"jev_calls": calls},
    )
    return {"ok": True, "energy": cell["energy"], "jev_calls": calls, "usd": spent}


def replay_journal(memory: dict[str, Any], *, last_n: int = 32) -> dict[str, Any]:
    """Apply recent journal deltas once; repeated replay is idempotent."""

    nca = memory.setdefault("nca", {})
    journal = list(nca.get("journal") or [])[-max(1, int(last_n)) :]
    grid = _grid(memory)
    replayed = set(str(item) for item in (nca.get("replayed_journal") or []))
    n_applied = 0
    n_duplicate = 0
    for index, row in enumerate(journal):
        event_id = str(row.get("event_id") or "")
        if not event_id:
            blob = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
            event_id = f"legacy:{index}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:24]}"
        if event_id in replayed:
            n_duplicate += 1
            continue
        ptr = canonical_cell_id(str(row.get("ptr") or ""))
        if not ptr:
            continue
        cell = _cell(grid, ptr, kind=str(row.get("op") or "cell"))
        delta = float(row.get("energy_delta") or 0.0)
        cell["energy"] = _clip(_energy_value(cell) + delta)
        if str(row.get("event") or "") in {"call", "upsert"}:
            cell["visited"] = True
        replayed.add(event_id)
        n_applied += 1
    nca["replayed_journal"] = sorted(replayed)[-256:]
    last_ran = list((nca.get("program_state") or {}).get("last_ran") or [])
    receipts = [
        {"op": row.get("op"), "ptr": row.get("ptr"), "ok": row.get("ok"), "detail_ok": row.get("detail_ok")}
        for row in last_ran
        if isinstance(row, dict)
    ]
    return {
        "ok": True,
        "n_replayed": n_applied,
        "n_duplicate": n_duplicate,
        "receipts": receipts,
        "n_receipts": len(receipts),
        "called_docker0": False,
    }


STALE_SECONDS = 3600.0
FORK_MAX = 4
HOT_TASK_ENERGY = 0.12
BUDGET_DEAD = 0.1


def feed_memory(memory: dict[str, Any], *, tactics: str = "", problem: str = "", heal: bool = True) -> dict[str, Any]:
    """Overlay successes/failures/research onto the grid. No Lean folds.

    Board seed, token_count, and heal use hooks when registered.
    """

    from jevops import hooks

    grid = _grid(memory)
    nca = memory.setdefault("nca", {})
    seen_overlays = set(str(item) for item in (nca.get("overlay_receipts") or []))

    def overlay_receipt(bucket: str, index: int, row: Mapping[str, Any]) -> str:
        blob = json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
        return f"{bucket}:{index}:{digest}"

    for index, row in enumerate(memory.get("successes") or []):
        if not isinstance(row, Mapping):
            continue
        receipt = overlay_receipt("success", index, row)
        if receipt in seen_overlays:
            continue
        cid = canonical_cell_id(str(row.get("kind") or ""), kind="skill")
        if not cid:
            continue
        cell = _cell(grid, cid, kind="skill")
        cell["wins"] = int(cell.get("wins") or 0) + 1
        cell["tokens"] = int(row.get("to_tokens") or cell.get("tokens") or 0)
        seen_overlays.add(receipt)
    for index, row in enumerate(memory.get("failures") or []):
        if not isinstance(row, Mapping):
            continue
        receipt = overlay_receipt("failure", index, row)
        if receipt in seen_overlays:
            continue
        cid = canonical_cell_id(str(row.get("kind") or ""), kind="skill")
        if not cid:
            continue
        cell = _cell(grid, cid, kind="skill")
        cell["losses"] = int(cell.get("losses") or 0) + 1
        seen_overlays.add(receipt)
    nca["overlay_receipts"] = sorted(seen_overlays)[-4096:]
    for row in memory.get("research") or []:
        if problem and row.get("name") != problem:
            continue
        for residual, help_score in (row.get("help") or {}).items():
            cid = canonical_cell_id(f"residual:{residual}", kind="residual")
            cell = _cell(grid, cid, kind="residual")
            cell["help"] = float(help_score or 0.0)
            cell["unsafe"] = float((row.get("unsafe") or {}).get(residual) or 0.0)
    if not any(str(cid).startswith("ptr://goal/") for cid in grid):
        seeder = hooks.resolve("seed_board", "board_graph", "seed_nca_from_board")
        if seeder:
            try:
                seeder(memory)
            except Exception:
                pass
    if tactics:
        proof_id = canonical_cell_id(f"proof:{problem or 'script'}", kind="theorem")
        count_fn = hooks.resolve("token_count", "run_warmup", "token_count")
        _cell(grid, proof_id, kind="proof")["tokens"] = int(
            count_fn(tactics) if count_fn else len(str(tactics).split())
        )
    if heal:
        from jevops import repair as lra_heal

        try:
            if lra_heal.diagnose(memory):
                lra_heal.heal(memory)
        except Exception:
            pass
    return {"n_cells": len(grid), "grid": grid}


def should_halt(memory: Mapping[str, Any]) -> dict[str, Any]:
    """Stop when there is nothing left to CALL: no diagnostics, no pending work, tasks blocked or cold.

    Halt does not fire on a cold seed: requires ever_ran or budget_dead.
    """

    from jevops import hooks

    diagnose = hooks.resolve("diagnose", "nca_repair", "diagnose")
    if diagnose is None:
        from jevops import repair as lra_heal

        diagnose = lra_heal.diagnose
    issues = diagnose(dict(memory))
    ops = list((((memory.get("nca") or {}).get("program_state") or {}).get("ops")) or [])
    pending = [op for op in ops if str(op.get("op") or "") not in {"KEEP", "RETURN"}]
    grid = (memory.get("nca") or {}).get("grid") or {}
    hot_tasks = [
        cid
        for cid, cell in grid.items()
        if isinstance(cell, dict)
        and cell.get("kind") == "task"
        and cell.get("visited")
        and not cell.get("do_not_fork")
        and not cell.get("blocked")
        and float(cell.get("energy") or 0) > HOT_TASK_ENERGY
    ]
    budget = grid.get(BUDGET_PTR) if isinstance(grid.get(BUDGET_PTR), dict) else {}
    budget_energy = _energy_value(budget, 1.0)
    budget_dead = bool(budget.get("visited")) and budget_energy < BUDGET_DEAD
    journal = list(((memory.get("nca") or {}).get("journal")) or [])
    last_ran = list((((memory.get("nca") or {}).get("program_state") or {}).get("last_ran")) or [])
    # ``jev`` and ``jev_pick`` are accounting observations emitted before a
    # candidate is admitted.  Treating either as a completed NCA action makes
    # a nested walker halt immediately after its first budget charge, before
    # it has a chance to call Lake.  Only completed program actions (or an
    # explicit program receipt in ``last_ran``) establish the post-run idle
    # condition.
    ever_ran = bool(last_ran) or any(
        str(row.get("event") or "") in {"call", "instruct", "grok"} for row in journal
    )
    idle = (not issues) and (not pending) and (not hot_tasks)
    halt = (ever_ran and idle) or budget_dead
    return {
        "halt": halt,
        "n_issues": len(issues),
        "n_pending_ops": len(pending),
        "n_hot_tasks": len(hot_tasks),
        "budget_energy": budget_energy,
        "budget_dead": budget_dead,
        "called_docker0": False,
    }


def neighborhood(cid: str, memory: Mapping[str, Any]) -> list[str]:
    """Neighbors from explicit board edges only.

    The old implementation connected every skill to every other skill and
    truncated that insertion-order list. A cellular neighborhood must come
    from declared edges; bounded summaries belong at the policy boundary.
    """

    cid = canonical_cell_id(str(cid))
    nbrs: list[str] = []
    for src, dst in (memory.get("nca") or {}).get("board_edges") or []:
        src_id = canonical_cell_id(str(src))
        dst_id = canonical_cell_id(str(dst))
        if src_id == cid:
            nbrs.append(dst_id)
        if dst_id == cid:
            nbrs.append(src_id)
    out: list[str] = []
    seen: set[str] = set()
    for item in nbrs:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= 12:
            break
    return out


def tick(memory: dict[str, Any], *, tactics: str = "", problem: str = "", focus: Optional[str] = None) -> dict[str, Any]:
    """One NCA update: self-state + neighbors + help/unsafe + lake wins.

    Optional ``feed_state`` hook overlays implementation residuals first.
    """

    from jevops import hooks

    feed = hooks.resolve("feed_state", "typesafe_nca", "feed_state")
    if feed:
        feed(memory, tactics=tactics, problem=problem)
    grid = _grid(memory)
    targets: Optional[set[str]] = None
    if focus:
        fid = canonical_cell_id(str(focus))
        targets = {fid}
        for edge in (memory.get("nca") or {}).get("board_edges") or []:
            if not isinstance(edge, (list, tuple)) or len(edge) < 2:
                continue
            src, dst = canonical_cell_id(str(edge[0])), canonical_cell_id(str(edge[1]))
            if src == fid:
                targets.add(dst)
            if dst == fid:
                targets.add(src)
    nxt: dict[str, dict[str, Any]] = {}
    for cid, cell in grid.items():
        if not isinstance(cell, dict):
            continue
        if targets is not None and cid not in targets:
            nxt[cid] = dict(cell)
            continue
        wins = int(cell.get("wins") or 0)
        losses = int(cell.get("losses") or 0)
        win_rate = wins / max(1, wins + losses)
        unsafe = float(cell.get("unsafe") or 0.0)
        help_score = float(cell.get("help") or 0.0)
        nbr_e = [_energy_value(grid.get(nid) or {}) for nid in neighborhood(cid, memory)]
        mean_n = sum(nbr_e) / len(nbr_e) if nbr_e else _energy_value(cell)
        energy = _clip(
            0.45 * _energy_value(cell)
            + 0.2 * mean_n
            + 0.2 * (1.0 - unsafe)
            + 0.1 * win_rate
            + 0.05 * min(1.0, help_score / 2.0)
        )
        energy = _clip(energy * 0.98)
        stale_for = time.time() - float(cell.get("updated_at") or time.time())
        if stale_for > STALE_SECONDS:
            energy = _clip(energy * 0.85)
        if losses > wins:
            energy = _clip(energy - 0.15)
        if cell.get("do_not_fork") or cell.get("blocked"):
            energy = min(energy, 0.05)
        updated = dict(cell)
        updated["energy"] = energy
        updated["tick"] = int(cell.get("tick") or 0) + 1
        nxt[cid] = updated
    memory["nca"]["grid"] = nxt
    nca = memory.setdefault("nca", {})
    nca["tick"] = int(nca.get("tick") or 0) + 1
    journal_event(memory, event="tick", op="TICK", extra={"n_cells": len(nxt), "focus": focus})
    ranked = sorted(nxt, key=lambda key: float(nxt[key].get("energy") or 0.0), reverse=True)
    from jevops.outer import head_seq

    return {
        "ok": True,
        "tick": nca["tick"],
        "n_cells": len(nxt),
        "top": [{"id": key, "energy": nxt[key]["energy"], "kind": nxt[key].get("kind")} for key in head_seq(ranked, 8)],
        "called_docker0": False,
    }


def mutate_energy(memory: dict[str, Any], *, problem: str = "", op: str = "auto") -> dict[str, Any]:
    """Reorder pipeline by energy and skip dying stems. Does not fold Lean."""

    grid = _grid(memory)
    ranked = sorted(grid, key=lambda key: float((grid.get(key) or {}).get("energy") or 0.0), reverse=True)
    applied: dict[str, Any] = {"op": op}
    if op in {"auto", "reorder"}:
        order: list[str] = []
        for cid in ranked:
            if (grid.get(cid) or {}).get("kind") != "skill":
                continue
            text = cid[len("ptr://skill/") :] if cid.startswith("ptr://skill/") else cid
            order.append(text[len("port_") :] if text.startswith("port_") else text)
        from jevops.outer import head_seq

        memory.setdefault("nca", {})["pipeline_bias"] = head_seq(order, 16)
        applied = {"op": "reorder", "pipeline_bias": head_seq(order, 8)}
    if op in {"auto", "skip"} and ranked:
        dying = ranked[-1]
        cell = grid.get(dying) or {}
        if int(cell.get("losses") or 0) > int(cell.get("wins") or 0):
            key = f"{problem}::{dying}" if problem else dying
            bl = memory.setdefault("blacklist", [])
            if key not in bl:
                bl.append(key)
            applied = {"op": "skip", "key": key}
    mutations = memory.setdefault("nca", {}).setdefault("mutations", [])
    mutations.append(applied)
    from jevops.outer import tail_seq

    memory["nca"]["mutations"] = tail_seq(mutations, 32)
    return {"ok": True, "applied": applied, "writes_lean": False, "called_docker0": False}


def fork_cells(
    memory: dict[str, Any],
    *,
    cell_ids: Optional[Sequence[str]] = None,
    tactics: str = "",
    problem: str = "",
    **spawn_kwargs: Any,
) -> dict[str, Any]:
    """Fork up to FORK_MAX high-energy cells as returnable subloops."""

    from jevops import tools as lra_tools

    tick(memory, tactics=tactics, problem=problem)
    grid = _grid(memory)
    if not cell_ids:
        from jevops.outer import head_seq

        cell_ids = head_seq(
            [
                key
                for key in sorted(grid, key=lambda cid: float((grid.get(cid) or {}).get("energy") or 0.0), reverse=True)
                if not ((grid[key] or {}).get("do_not_fork") or (grid[key] or {}).get("blocked"))
            ],
            FORK_MAX,
        )
    launched: list[dict[str, Any]] = []
    from jevops.outer import head_seq

    for cid in head_seq(cell_ids, FORK_MAX):
        child = dict(spawn_kwargs)
        child["node"] = cid
        if child.get("record") is not None and "skill_walk" in lra_tools.SUBLOOPS:
            payload = lra_tools.spawn_subloop("skill_walk", **child)
        else:
            payload = {
                "ok": True,
                "returned": True,
                "subloop": "nca_cell",
                "node": cid,
                "energy": (grid.get(cid) or {}).get("energy"),
            }
        launched.append({"id": cid, "returned": bool(payload.get("returned")), "ok": payload.get("ok")})
        memory.setdefault("subloop_returns", []).append(
            {"name": cid, "ok": payload.get("ok"), "returned": True, "nca": True}
        )
    return {"ok": True, "n_forked": len(launched), "forks": launched, "called_docker0": False}


def live_status(memory: Mapping[str, Any]) -> dict[str, Any]:
    """Halt snapshot plus board window / edges / last_ran. No Lean."""

    halt = dict(should_halt(dict(memory)) or {})
    try:
        from jevops.board import board_window

        halt["board_window"] = board_window(memory)
    except Exception:
        halt["board_window"] = []
    nca = (memory.get("nca") or {}) if isinstance(memory.get("nca"), dict) else {}
    halt["n_edges"] = len(nca.get("board_edges") or [])
    from jevops.outer import head_seq

    halt["last_ran"] = head_seq(((nca.get("program_state") or {}).get("last_ran")) or [], 8)
    return halt


def credit_skill(
    memory: dict[str, Any],
    kind: Any,
    *,
    ok: bool,
    tokens: int = 0,
) -> None:
    """Upsert a skill cell from a lake row. Fail closed. No Lean."""

    try:
        upsert_from_event(
            memory,
            ptr=str(kind),
            kind="skill",
            energy=0.7 if ok else 0.25,
            theorem_ok=bool(ok),
            tokens=int(tokens or 0),
        )
    except Exception:
        pass


def feed_with_overlays(
    memory: dict[str, Any],
    *,
    tactics: str = "",
    problem: str = "",
    counts: Optional[Mapping[str, Any]] = None,
    inverse: Optional[Mapping[str, Sequence[str]]] = None,
    tree: Optional[Mapping[str, Any]] = None,
    heal: bool = True,
) -> dict[str, Any]:
    """feed_memory plus optional residual/tree overlays. No Lean."""

    fed = feed_memory(memory, tactics=tactics, problem=problem, heal=heal)
    if counts:
        overlay_counts(memory, counts, inverse=inverse)
    if tree:
        overlay_tree(memory, tree)
    grid = _grid(memory)
    return {"n_cells": len(grid), "grid": grid, **{k: v for k, v in fed.items() if k not in {"n_cells", "grid"}}}


def dispatch_tool(name: str, *, extras: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> dict[str, Any]:
    """Closed NCA tool names. Implementations register extra keys via hooks."""

    from jevops import hooks

    key = str(name or "").strip()
    memory = kwargs.get("memory") if isinstance(kwargs.get("memory"), dict) else {}
    tactics = str(kwargs.get("tactics") or "")
    problem = str(kwargs.get("problem") or "")
    if extras and key in extras:
        return dict(extras[key](**kwargs) or {})
    if key == "nca_tick":
        return tick(memory, tactics=tactics, problem=problem)
    if key == "nca_fork":
        extra = {k: v for k, v in kwargs.items() if k not in {"memory", "tactics", "problem", "name"}}
        return fork_cells(memory, tactics=tactics, problem=problem, **extra)
    if key in {"nca_bandit", "nca_multi_armed_bandit", "nca_bandit_tactic"}:
        from jevops.tactics import multi_armed_bandit

        spec = kwargs.get("bandit") if isinstance(kwargs.get("bandit"), Mapping) else {}
        supplied = dict(spec or {})
        supplied.update({k: v for k, v in kwargs.items() if k not in {"memory", "tactics", "problem", "name", "bandit"}})
        arms = supplied.get("arms")
        if not arms:
            arms = [
                str(cid)[len("ptr://skill/") :]
                for cid, cell in _grid(memory).items()
                if str(cid).startswith("ptr://skill/") and isinstance(cell, dict)
            ]
        bandit_name = str(supplied.get("bandit_name") or supplied.get("name") or "default")
        call = {
            "name": bandit_name,
            "policy": supplied.get("policy") or "",
            "arms": arms,
            "epsilon": supplied.get("epsilon", 0.1),
            "exploration": supplied.get("exploration", 1.0),
            "seed": supplied.get("seed", 0),
        }
        for field in ("reward", "arm", "selected", "rng"):
            if field in supplied:
                call[field] = supplied[field]
        return multi_armed_bandit(memory, **call)
    if key in {"proof_ca_run", "nca_proof_ca"}:
        runtime = kwargs.get("runtime")
        if runtime is None or not hasattr(runtime, "run"):
            return {"outcome": "RUNTIME_REQUIRED", "tool": key}
        return dict(runtime.run(fair_period=int(kwargs.get("fair_period") or 3), max_steps=kwargs.get("max_steps")) or {})
    handler = hooks.get(key) or hooks.get(f"nca_tool:{key}")
    if handler is not None:
        return dict(handler(**kwargs) or {})
    return {"ok": False, "reason": "unknown_nca_tool", "tool": key}


def create_proof_ca(**kwargs: Any) -> Any:
    """Construct the strict proof CA without changing the legacy cell API."""

    from jevops.proof_ca import ProofGraphCA

    return ProofGraphCA(**kwargs)


def run_proof_ca(runtime: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Thin adapter for consumers that discover the runtime through ``nca``."""

    run_kwargs = {}
    constructor_kwargs = dict(kwargs)
    for name in ("fair_period", "max_steps"):
        if name in constructor_kwargs:
            run_kwargs[name] = constructor_kwargs.pop(name)
    active = runtime if runtime is not None else create_proof_ca(**constructor_kwargs)
    return dict(active.run(**run_kwargs) or {})


def run_unittests(*names: str, root: Path, default: Sequence[str] = ("test_skill_improve_loop",)) -> dict[str, Any]:
    """Run selected unit tests in-process. Never lake. Never docker0."""

    import io
    import unittest

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    here = Path(root)
    for name in names or tuple(default):
        stem = str(name).replace(".py", "")
        if not stem.startswith("test_"):
            continue
        path = here / f"{stem}.py"
        if not path.is_file():
            continue
        try:
            suite.addTests(loader.discover(str(here), pattern=f"{stem}.py"))
        except Exception:
            continue
    result = unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)
    return {
        "ok": result.wasSuccessful(),
        "run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "called_docker0": False,
    }


def overlay_counts(
    memory: dict[str, Any],
    counts: Mapping[str, Any],
    *,
    inverse: Optional[Mapping[str, Sequence[str]]] = None,
    kind: str = "residual",
    skill_prefix: str = "port_",
) -> dict[str, Any]:
    """Upsert count cells and optional residual→skill edges. No Lean."""

    grid = _grid(memory)
    edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
    inv = {str(k): list(v) for k, v in dict(inverse or {}).items()}
    n = 0
    for residual, count in (counts or {}).items():
        cid = canonical_cell_id(f"{kind}:{residual}", kind=kind)
        cell = _cell(grid, cid, kind=kind)
        cell["count"] = int(count)
        cell["energy"] = _clip(max(float(cell.get("energy") or 0.4), min(0.95, 0.35 + 0.08 * int(count))))
        n += 1
        for stem in inv.get(str(residual), ()):
            skill_ptr = canonical_cell_id(f"{skill_prefix}{stem}", kind="skill")
            _cell(grid, skill_ptr, kind="skill")
            pair = [cid, skill_ptr]
            if pair not in edges:
                edges.append(pair)
    return {"ok": True, "n": n}


def invert_multimap(mapping: Mapping[str, str]) -> dict[str, list[str]]:
    """Invert k→v into v→[k, ...]."""

    out: dict[str, list[str]] = {}
    for key, value in dict(mapping or {}).items():
        out.setdefault(str(value), []).append(str(key))
    return out


def overlay_tree(
    memory: dict[str, Any],
    tree: Mapping[str, Any],
    *,
    family_kind: str = "family",
    skill_kind: str = "skill",
) -> dict[str, Any]:
    """Upsert family and skill cells from a decision tree. No Lean."""

    grid = _grid(memory)
    n = 0
    for fam, kids in dict(tree or {}).items():
        _cell(grid, canonical_cell_id(f"family:{fam}", kind=family_kind), kind=family_kind)
        n += 1
        for kid in kids or ():
            _cell(grid, canonical_cell_id(str(kid), kind=skill_kind), kind=skill_kind)
            n += 1
    return {"ok": True, "n": n}


def record_mutation(memory: dict[str, Any], applied: Mapping[str, Any]) -> None:
    mutations = memory.setdefault("nca", {}).setdefault("mutations", [])
    row = dict(applied)
    if mutations:
        mutations[-1] = row
    else:
        mutations.append(row)
    memory["nca"]["mutations"] = mutations[-32:]


def drive_mutate(
    memory: dict[str, Any],
    *,
    tactics: str,
    problem: str,
    op: str,
    fold_skill_fn: Callable[..., Any],
    propose_fn: Callable[..., Mapping[str, Any]],
    expand_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Energy reorder plus an injected keep-structure fold. Does not write Lean."""

    from jevops.memory import first_fold
    from jevops.outer import call_if, get_list

    def _fold(body: str) -> Optional[dict[str, Any]]:
        return first_fold(body, get_list(memory, "skills"), fold_fn=fold_skill_fn)

    def _mint() -> dict[str, Any]:
        prop = propose_fn(memory, problem)

        def _keep() -> dict[str, Any]:
            expand_fn(memory, name=problem, tactics=tactics)
            return prop

        return call_if(prop.get("keep_structure") and prop.get("mint"), _keep, default={})

    return apply_mutate(memory, tactics=tactics, problem=problem, op=op, fold_fn=_fold, mint_fn=_mint)


def apply_mutate(
    memory: dict[str, Any],
    *,
    tactics: str = "",
    problem: str = "",
    op: str = "auto",
    fold_fn: Optional[Any] = None,
    mint_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Energy mutate plus optional implementation fold/mint. Does not write Lean."""

    tick(memory, tactics=tactics, problem=problem)
    applied: dict[str, Any] = dict(mutate_energy(memory, problem=problem, op=op).get("applied") or {"op": op})
    if op in {"auto", "fold"} and tactics:
        folded = fold_fn(tactics) if fold_fn is not None else None
        if isinstance(folded, dict) and folded.get("tactics") and str(folded["tactics"]) != tactics:
            applied = {"op": "fold", **dict(folded)}
        elif isinstance(folded, str) and folded != tactics:
            applied = {"op": "fold", "tactics": folded}
        elif applied.get("op") != "fold" and mint_fn is not None:
            prop = mint_fn()
            if isinstance(prop, dict) and (prop.get("keep_structure") or prop.get("mint")):
                applied = {"op": "mint", "proposed": prop}
        record_mutation(memory, applied)
    return {"ok": True, "applied": applied, "called_docker0": False}


def allowed_path(
    path: str | Path,
    *,
    roots: Sequence[Path],
    base: Optional[Path] = None,
) -> Optional[Path]:
    raw = Path(path)
    if not raw.is_absolute() and base is not None:
        raw = Path(base) / raw
    try:
        resolved = raw.resolve()
    except OSError:
        return None
    allowed = tuple(Path(root).resolve() for root in roots)
    if not any(resolved == root or root in resolved.parents for root in allowed):
        return None
    return resolved


def first_existing_file(
    candidates: Sequence[Any],
    *,
    roots: Sequence[Path] = (),
) -> Optional[Path]:
    """First existing file, optionally confined to allowed roots."""

    for cand in candidates:
        try:
            resolved = Path(cand).resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if roots:
            allowed = allowed_path(resolved, roots=tuple(Path(root) for root in roots))
            if allowed is None:
                continue
            return allowed
        return resolved
    return None


def codepath_rel_candidates(module: str, *, here: Any, accel: Any) -> list[Path]:
    """Candidate files for a harness/accelerate module stem. First existing wins."""

    rel = str(module or "").replace("harness.", "").replace(".", "/")
    here_p = Path(here)
    accel_p = Path(accel)
    candidates = [
        here_p / f"{Path(rel).name}.py" if "/" not in rel.replace("harness/", "") else here_p / Path(rel).name,
        here_p / Path(rel).with_suffix(".py").name,
        here_p / f"{rel.split('/')[-1]}.py",
        accel_p / Path(*rel.split("/")).with_suffix(".py"),
    ]
    if rel.endswith(".py"):
        candidates.append(here_p / Path(rel).name)
        candidates.append(accel_p / rel)
    return candidates


def inspect_python(
    path: str | Path,
    *,
    roots: Sequence[Path],
    base: Optional[Path] = None,
    import_dir: Optional[Path] = None,
    test_dir: Optional[Path] = None,
    relative_to: Optional[Path] = None,
    fold_prefix: str = "fold_",
) -> dict[str, Any]:
    """AST + import probe for one file under allowed roots. Never docker0."""

    target = allowed_path(path, roots=roots, base=base)
    if target is None or not target.is_file():
        return {"ok": False, "reason": "path_not_allowed", "path": str(path)}
    from jevops.outer import exc_head, head_seq, read_text

    text = read_text(target)
    functions: list[str] = []
    try:
        tree = ast.parse(text)
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    except SyntaxError as exc:
        return {"ok": False, "reason": "syntax", "error": exc_head(exc, 160), "path": str(target)}
    importable = False
    if import_dir is not None and target.parent == Path(import_dir).resolve() and target.suffix == ".py":
        try:
            importlib.import_module(target.stem)
            importable = True
        except Exception:
            importable = False
    tests: list[str] = []
    if test_dir is not None:
        needle = target.stem.replace("typesafe_", "").split("_")[0]
        tests = head_seq(
            [
                p.name
                for p in Path(test_dir).glob("test_*.py")
                if needle in read_text(p)
            ],
            8,
        )
    rel = target.name
    if relative_to is not None:
        root = Path(relative_to).resolve()
        if root in target.parents or target.parent == root:
            rel = str(target.relative_to(root))
    return {
        "ok": True,
        "path": rel,
        "n_functions": len(functions),
        "fold_fns": [name for name in functions if name.startswith(fold_prefix)],
        "importable": importable,
        "tests": tests,
        "n_chars": len(text),
        "called_docker0": False,
    }


def walk_python(
    root: Path,
    *,
    limit: int = 80,
    roots: Optional[Sequence[Path]] = None,
    **inspect_kw: Any,
) -> dict[str, Any]:
    """Hook every Python file in root (bounded)."""

    files = sorted(Path(root).glob("*.py"))[: max(1, int(limit))]
    allowed = list(roots) if roots is not None else [Path(root).resolve()]
    rows = [inspect_python(path, roots=allowed, base=root, **inspect_kw) for path in files]
    return {
        "ok": True,
        "n_files": len(rows),
        "importable": sum(1 for row in rows if row.get("importable")),
        "n_fold_fns": sum(len(row.get("fold_fns") or []) for row in rows),
        "files": [{"path": row.get("path"), "ok": row.get("ok"), "n_functions": row.get("n_functions")} for row in rows],
        "called_docker0": False,
    }


def function_call_map(
    source: str,
    *,
    qualify_fn: Optional[Any] = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Python AST: short function names in order, and id → unique callees.

    qualify_fn(name) keys the call map (default: the short name). No source bodies.
    """

    qualify = qualify_fn or (lambda name: name)
    tree = ast.parse(str(source or ""))
    defs: list[str] = []
    calls_by: dict[str, list[str]] = {}
    current = ""

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            nonlocal current
            ident = str(qualify(node.name))
            defs.append(node.name)
            prev, current = current, ident
            calls_by.setdefault(ident, [])
            self.generic_visit(node)
            current = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            called = ""
            if isinstance(func, ast.Name):
                called = func.id
            elif isinstance(func, ast.Attribute):
                called = func.attr
            if current and called:
                bucket = calls_by.setdefault(current, [])
                if called not in bucket:
                    bucket.append(called)
            self.generic_visit(node)

    Visitor().visit(tree)
    return defs, calls_by


def top_level_symbols(source: str, *, cap: int = 80) -> list[str]:
    """Module-body function/class names. No source bodies."""

    tree = ast.parse(str(source or ""))
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return names[: max(0, int(cap))]


def matching_top_level(
    root: Any,
    query: str,
    *,
    glob: str = "*.py",
    cap_files: int = 80,
    cap_hits: int = 24,
) -> list[dict[str, Any]]:
    """Top-level function/class names in globbed files whose names contain query."""

    base = Path(root)
    needle = str(query or "").casefold()
    hits: list[dict[str, Any]] = []
    try:
        paths = sorted(base.glob(glob))[: max(0, int(cap_files))]
    except OSError:
        return []
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            if needle and needle not in name.casefold():
                continue
            hits.append(
                {
                    "name": name,
                    "path": path.name,
                    "lineno": int(getattr(node, "lineno", 0) or 0),
                }
            )
            if len(hits) >= max(0, int(cap_hits)):
                return hits
    return hits


def sidecar_files(
    paths: Sequence[Path],
    *,
    cap_files: int = 80,
    cap_symbols: int = 80,
) -> list[dict[str, Any]]:
    """AST sidecar rows: path name + top-level symbols."""

    rows: list[dict[str, Any]] = []
    for path in list(paths or ())[: max(0, int(cap_files))]:
        target = Path(path)
        try:
            symbols = top_level_symbols(target.read_text(encoding="utf-8"), cap=cap_symbols)
        except (OSError, SyntaxError):
            continue
        rows.append({"path": target.name, "symbols": symbols, "n_symbols": len(symbols)})
    return rows


def query_sidecar_symbols(
    files: Sequence[Mapping[str, Any]],
    query: str,
    *,
    limit: int = 24,
    source: str = "sidecar",
) -> list[dict[str, Any]]:
    """Case-insensitive substring hits on sidecar symbol names. Empty query → []."""

    needle = str(query or "").casefold()
    hits: list[dict[str, Any]] = []
    if not needle:
        return hits
    for row in files or ():
        for symbol in row.get("symbols") or []:
            if needle in str(symbol).casefold():
                hits.append({"symbol": symbol, "path": row.get("path"), "source": source})
            if len(hits) >= max(0, int(limit)):
                return hits
    return hits


def resolve_unique_callees(
    defs: Mapping[str, Sequence[str]],
    calls: Mapping[str, Sequence[str]],
    *,
    cap: int = 12,
) -> dict[str, list[str]]:
    """If a callee short-name has exactly one qualified def, use it."""

    resolved: dict[str, list[str]] = {}
    for qname, raw in dict(calls or {}).items():
        out: list[str] = []
        for callee in raw:
            targets = list(defs.get(callee) or [])
            out.append(str(targets[0]) if len(targets) == 1 else str(callee))
        resolved[str(qname)] = out[: max(0, int(cap))]
    return resolved


def memo_build(slot: Any, *, refresh: bool, build_fn: Callable[[], Any]) -> Any:
    """Return a cached mapping unless refresh. Cache hits never admit Lean."""

    from jevops.outer import call_if, first_not_none

    return first_not_none(call_if(not refresh and slot is not None, lambda: slot), factory=build_fn)


def call_graph_from_paths(
    paths: Sequence[Any],
    *,
    cap_files: int = 80,
    cap_neighbors: int = 12,
) -> dict[str, Any]:
    """Qualified defs + unique callees over Python files. No source bodies."""

    defs: dict[str, list[str]] = {}
    calls: dict[str, list[str]] = {}
    for path in list(paths or ())[: max(0, int(cap_files))]:
        target = Path(path)
        module = target.stem
        try:
            _short, mapped = function_call_map(
                target.read_text(encoding="utf-8"),
                qualify_fn=lambda name, mod=module: f"{mod}:{name}",
            )
        except (OSError, SyntaxError):
            continue
        for qname, callees in mapped.items():
            short = str(qname).rsplit(":", 1)[-1]
            bucket = defs.setdefault(short, [])
            if qname not in bucket:
                bucket.append(str(qname))
            dest = calls.setdefault(str(qname), [])
            for callee in callees:
                if callee not in dest:
                    dest.append(str(callee))
    resolved = resolve_unique_callees(defs, calls, cap=int(cap_neighbors))
    return {
        "defs": defs,
        "calls": resolved,
        "n_defs": sum(len(items) for items in defs.values()),
    }


def first_matching_symbol(
    hits: Sequence[Mapping[str, Any]],
    name: str,
    *,
    key: str = "symbol",
) -> str:
    """First hit whose symbol contains name or ends with :bare. Else hits[0]."""

    raw = str(name or "")
    bare = raw.rsplit(":", 1)[-1]
    for hit in hits or ():
        symbol = str(hit.get(key) or "")
        if raw and raw in symbol:
            return symbol
        if bare and symbol.endswith(":" + bare):
            return symbol
    if hits:
        return str(hits[0].get(key) or "")
    return ""


def pick_qualified(
    name: str,
    defs: Mapping[str, Sequence[str]],
    calls: Mapping[str, Sequence[str]],
    *,
    strip_prefixes: Sequence[str] = (),
    ptr_prefix: str = "ptr://codepath/",
) -> str:
    """Resolve a codepath name to a qualified def. First unique-or-any match."""

    symbol = str(name or "")
    if ptr_prefix and symbol.startswith(ptr_prefix):
        symbol = symbol[len(ptr_prefix) :]
    if ":" not in symbol and "." in symbol:
        for prefix in strip_prefixes:
            if symbol.startswith(prefix):
                symbol = symbol[len(prefix) :]
                break
        if ":" not in symbol:
            parts = symbol.replace("/", ".").rsplit(".", 1)
            if len(parts) == 2:
                symbol = f"{parts[0]}:{parts[1]}"
    if symbol in dict(calls or {}):
        return symbol
    bare = symbol.rsplit(":", 1)[-1]
    matches = list((defs or {}).get(bare) or [])
    return str(matches[0]) if matches else ""


def focus_symbol(name: str, defs: Sequence[str], calls: Mapping[str, Sequence[str]]) -> str:
    """Bare name after ``:`` if it is a def/call, else the first def."""

    symbol = ""
    raw = str(name or "")
    if ":" in raw:
        symbol = raw.rsplit(":", 1)[-1]
    if symbol in dict(calls or {}) or symbol in list(defs or ()):
        return symbol
    return str(defs[0]) if defs else ""


def append_board_edges(
    memory: dict[str, Any],
    pairs: Sequence[Sequence[str]],
    *,
    prefix: str = "ptr://codepath/",
    limit: int = 48,
) -> int:
    edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
    added = 0
    for raw in list(pairs or ())[: max(0, int(limit))]:
        if len(raw) < 2:
            continue
        src = str(raw[0])
        dst = str(raw[1])
        if prefix and not src.startswith("ptr://"):
            src = prefix + src
        if prefix and not dst.startswith("ptr://"):
            dst = prefix + dst
        pair = [src, dst]
        if pair in edges:
            continue
        edges.append(pair)
        added += 1
    return added


def call_pairs_from_graph(graph: Mapping[str, Any], *, limit: int = 48) -> list[tuple[str, str]]:
    """Caller→callee pairs from an AST call graph. Cap at limit."""

    rows: list[tuple[str, str]] = []
    cap = max(0, int(limit))
    for caller, callees in dict((graph or {}).get("calls") or {}).items():
        for callee in callees or ():
            rows.append((str(caller), str(callee)))
            if len(rows) >= cap:
                return rows
    return rows


def seed_edges_from_query(
    memory: dict[str, Any],
    *,
    refused: bool = False,
    query_fn: Optional[Callable[[], Sequence[Any]]] = None,
    graph_fn: Optional[Callable[[], Sequence[Any]]] = None,
    limit: int = 48,
    refuse_reason: str = "campaign_db_refused",
) -> dict[str, Any]:
    """DuckDB rows, else AST pairs, then board_edges. Never campaign writes."""

    if refused:
        return {"ok": False, "reason": refuse_reason, "n_edges": 0, "control_duckdb": True}
    rows = list(query_fn() or []) if query_fn is not None else []
    source = "sidecar_duckdb" if rows else "harness_ast"
    if not rows and graph_fn is not None:
        rows = list(graph_fn() or [])
        source = "harness_ast"
    added = append_board_edges(memory, rows, limit=limit)
    return {
        "ok": True,
        "n_edges": added,
        "source": source,
        "control_duckdb": False,
        "called_docker0": False,
    }


_LEAN_MARKERS = ("simp_all", "intros ", "theorem ", "\nby\n", "exact ⟨", "induction ", "have :=")


def looks_like_lean(text: str) -> bool:
    blob = str(text or "")
    return any(marker in blob for marker in _LEAN_MARKERS)


def replace_function_def(source: str, name: str, new_def: str) -> str:
    """Replace a top-level or nested function by name. Returns unparsed Python."""

    tree = ast.parse(source)
    parsed = ast.parse(new_def)
    if not parsed.body or not isinstance(parsed.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError("new_def must be a function definition")
    new_fn = parsed.body[0]

    class _Swap(ast.NodeTransformer):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            if node.name == name:
                return ast.copy_location(new_fn, node)
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            if node.name == name:
                return ast.copy_location(new_fn, node)
            return self.generic_visit(node)

    nxt = _Swap().visit(tree)
    ast.fix_missing_locations(nxt)
    return ast.unparse(nxt) + "\n"


def rewrite_python(
    path: str | Path,
    *,
    roots: Sequence[Path],
    transform_fn: Any,
    base: Optional[Path] = None,
    accept_fn: Optional[Any] = None,
    diagnose_fn: Optional[Any] = None,
    write: bool = True,
) -> dict[str, Any]:
    """Sandboxed Python AST rewrite. Never writes Lean. Fail closed outside roots.

    transform_fn(tree, source) → ast.AST or str. Write only if accept/diagnose pass.
    """

    target = allowed_path(path, roots=roots, base=base)
    if target is None or not target.is_file():
        return {"ok": False, "reason": "path_not_allowed", "path": str(path), "wrote": False}
    from jevops.outer import read_text

    old = read_text(target)
    try:
        tree = ast.parse(old)
    except SyntaxError as exc:
        from jevops.outer import exc_head

        return {"ok": False, "reason": "syntax", "error": exc_head(exc, 160), "path": str(target), "wrote": False}
    produced = transform_fn(tree, old)
    try:
        if isinstance(produced, ast.AST):
            ast.fix_missing_locations(produced)
            new = ast.unparse(produced) + "\n"
        else:
            new = str(produced or "")
            if looks_like_lean(new):
                return {
                    "ok": False,
                    "reason": "looks_like_lean",
                    "path": str(target),
                    "wrote": False,
                    "jev_writes_lean": False,
                }
            ast.parse(new)
    except SyntaxError as exc:
        from jevops.outer import exc_head

        return {"ok": False, "reason": "syntax_after", "error": exc_head(exc, 160), "wrote": False}
    if looks_like_lean(new):
        return {
            "ok": False,
            "reason": "looks_like_lean",
            "path": str(target),
            "wrote": False,
            "jev_writes_lean": False,
        }
    if new == old:
        return {"ok": True, "reason": "unchanged", "path": str(target), "wrote": False}
    if diagnose_fn is not None:
        before = list(diagnose_fn(old) or [])
        after = list(diagnose_fn(new) or [])
        if len(after) > len(before):
            return {
                "ok": False,
                "reason": "diagnostics_worse",
                "before": len(before),
                "after": len(after),
                "wrote": False,
            }
    if accept_fn is not None and not accept_fn(old, new):
        return {"ok": False, "reason": "rejected", "path": str(target), "wrote": False}
    if write:
        target.write_text(new, encoding="utf-8")
    return {
        "ok": True,
        "path": str(target),
        "wrote": bool(write),
        "n_chars": len(new),
        "called_docker0": False,
        "jev_writes_lean": False,
    }


def pack_codepath_slice(
    *,
    ok: bool,
    name: str = "",
    path: str = "",
    symbol: str = "",
    definitions: Sequence[Any] = (),
    callees: Sequence[Any] = (),
    callers: Sequence[Any] = (),
    inspect_only: bool = False,
    reason: str = "",
    error: str = "",
) -> dict[str, Any]:
    """AST slice payload. Ids only; no source bodies. Never docker0."""

    out: dict[str, Any] = {
        "ok": bool(ok),
        "called_docker0": False,
        "inspect_only": bool(inspect_only),
    }
    if not ok:
        out["reason"] = reason
        if name:
            out["name"] = name
        if error:
            out["error"] = error
        return out
    out.update(
        {
            "path": path,
            "symbol": symbol,
            "definitions": list(definitions),
            "callees": list(callees),
            "callers": list(callers),
            "complete": True,
            "source_bodies": False,
            "campaign_write": False,
            "invoked": False if inspect_only else True,
        }
    )
    return out


def drive_sidecar_index(
    *,
    root: Any,
    default_root: Any,
    write: bool,
    dest: Any,
    cap_files: int = 80,
    cap_symbols: int = 80,
) -> dict[str, Any]:
    """JSON AST sidecar. Never campaign DuckDB."""

    from jevops.outer import call_if, if_none, set_if, text_or, write_json

    base = if_none(root, default_root)
    payload = pack_sidecar_index(sidecar_files(sorted(Path(base).glob("*.py")), cap_files=cap_files, cap_symbols=cap_symbols))
    call_if(write, lambda: write_json(dest, payload))
    return set_if(payload, write, "path", text_or(dest))


def drive_allowed_pair(path: Any, *, here: Any, paper: Any, base: Any) -> Any:
    """Allow a path under here or the paper root."""

    return allowed_path(path, roots=(Path(here).resolve(), Path(paper).resolve()), base=base)


def drive_here_inspect(
    path: Any,
    *,
    here: Any,
    paper: Any,
    base: Any,
    import_dir: Any,
    test_dir: Any,
) -> dict[str, Any]:
    """Inspect one file under the harness and paper roots."""

    roots = (Path(here).resolve(), Path(paper).resolve())
    return inspect_python(
        path,
        roots=roots,
        base=base,
        import_dir=import_dir,
        test_dir=test_dir,
        relative_to=roots[1],
    )


def drive_here_walk(
    root: Any,
    *,
    limit: int,
    here: Any,
    paper: Any,
    import_dir: Any,
    test_dir: Any,
) -> dict[str, Any]:
    """Walk Python files under the harness root. Bounded. No campaign DuckDB."""

    roots = (Path(here).resolve(), Path(paper).resolve())
    return walk_python(
        root,
        limit=limit,
        roots=roots,
        import_dir=import_dir,
        test_dir=test_dir,
        relative_to=roots[1],
    )


def drive_tick_kwargs(kwargs: Mapping[str, Any], *, tick_fn: Callable[..., Any]) -> Any:
    """Tick from a subloop kwargs bag. Does not write Lean."""

    from jevops.outer import as_dict, first_truthy, get_str, text_or

    memory = as_dict(kwargs.get("memory"), {})
    record = as_dict(kwargs.get("record"), {})
    problem = text_or(first_truthy(kwargs.get("problem"), record.get("name"), default=""))
    return tick_fn(memory, tactics=get_str(kwargs, "tactics"), problem=problem)


def drive_fork_kwargs(kwargs: Mapping[str, Any], *, fork_fn: Callable[..., Any]) -> Any:
    """Fork cells from kwargs, dropping the tool name and memory keys."""

    from jevops.outer import as_dict, without_keys

    return fork_fn(as_dict(kwargs.get("memory"), {}), **without_keys(kwargs, ("name", "memory")))


def drive_sidecar_query(
    query: str,
    payload: Any,
    *,
    present_fn: Callable[[], bool],
    load_fn: Callable[[], Any],
    build_fn: Callable[[], Any],
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Sidecar symbols from a payload, a file, or a fresh index. Ids only."""

    from jevops.outer import call_if, get_list, if_none, or_call

    data = or_call(
        if_none(payload, factory=lambda: call_if(present_fn(), load_fn)),
        build_fn,
    )
    return query_sidecar_symbols(get_list(data, "files"), query, limit=limit)


def drive_module_file(
    name: str,
    *,
    stem_fn: Callable[[str], Any],
    candidates_fn: Callable[[str], Sequence[Any]],
    roots_fn: Callable[[], Sequence[Any]],
    first_fn: Callable[..., Any],
) -> Any:
    """First existing file for a codepath module. None when the stem is empty."""

    from jevops.outer import call_if

    module = stem_fn(name)
    return call_if(
        module is not None,
        lambda: first_fn(candidates_fn(module), roots=roots_fn()),
    )


def drive_ast_hits(
    root: Any,
    query: str,
    *,
    cap: int,
    hit_fn: Callable[[Mapping[str, Any]], Any],
) -> list[Any]:
    """Top-level AST hits. Ids only. No source bodies."""

    from jevops.outer import map_hits

    return map_hits(matching_top_level(root, query, cap_hits=cap), hit_fn)


def drive_query_symbols(
    query: str,
    *,
    db_path: Any,
    default_db: Any,
    sql: str,
    refuse_names: Sequence[str] = ("control.duckdb",),
) -> list[Any]:
    """Symbol rows from the sidecar. Ids only. Refuses campaign DuckDB."""

    from jevops.outer import call_if, if_none, query_engine, text_or

    needle = f"%{text_or(query).casefold()}%"
    return query_engine(
        Path(if_none(db_path, default_db)),
        sql,
        [needle],
        refuse_names=tuple(refuse_names),
        row_fn=lambda row: call_if(
            row and row[0],
            lambda: {
                "symbol": text_or(row[0]),
                "path": text_or(row[1]),
                "kind": text_or(row[2]),
                "source": "sidecar_duckdb",
            },
        ),
    )


def drive_sidecar_db(
    path: Any,
    *,
    default_db: Any,
    refresh: bool,
    graph_fn: Callable[..., Mapping[str, Any]],
    connect_fn: Callable[..., Any],
    exec_fn: Callable[..., Any],
    count_fn: Callable[..., Any],
    try_import_fn: Callable[[], Any],
    refuse_fn: Callable[..., bool],
    refuse_names: Sequence[str] = ("control.duckdb",),
) -> dict[str, Any]:
    """Fill a symbols sidecar. Refuses campaign control.duckdb."""

    from jevops.outer import if_none

    dest = Path(if_none(path, default_db))
    return fill_sidecar_duckdb(
        dest,
        graph_fn(refresh=refresh),
        connect_fn=connect_fn,
        exec_fn=exec_fn,
        count_fn=count_fn,
        try_import_fn=try_import_fn,
        refuse_fn=refuse_fn,
        refuse_names=tuple(refuse_names),
    )


def drive_seed_edges(
    memory: dict[str, Any],
    *,
    db_path: Any,
    default_db: Any,
    limit: int,
    sql: str,
    graph_fn: Callable[[int], Any],
    refuse_names: Sequence[str] = ("control.duckdb",),
) -> dict[str, Any]:
    """Caller/callee edges from DuckDB, else the injected graph. Not a lake admit."""

    from jevops.outer import call_if, first_int, if_none, path_refused, query_engine, text_or

    dest = Path(if_none(db_path, default_db))
    cap = first_int(limit)
    return seed_edges_from_query(
        memory,
        refused=path_refused(dest, names=tuple(refuse_names)),
        query_fn=lambda: query_engine(
            dest,
            sql,
            [cap],
            refuse_names=tuple(refuse_names),
            row_fn=lambda row: call_if(
                row and row[0] and row[1],
                lambda: (text_or(row[0]), text_or(row[1])),
            ),
        ),
        graph_fn=lambda: graph_fn(cap),
        limit=cap,
    )


def drive_query_calls(
    symbol: str,
    *,
    db_path: Any,
    default_db: Any,
    direction: str,
    sql: str,
    refuse_names: Sequence[str] = ("control.duckdb",),
) -> list[str]:
    """Caller or callee names from the sidecar. Ids only."""

    from jevops.outer import call_if, if_none, query_engine, text_or, without_prefix

    name = without_prefix(text_or(symbol), "ptr://codepath/")
    callers = direction == "callers"
    column = "caller" if callers else "callee"
    match_on = "callee" if callers else "caller"
    return query_engine(
        Path(if_none(db_path, default_db)),
        sql.format(column=column, match_on=match_on),
        [name, f"%:{name.rsplit(':', 1)[-1]}"],
        refuse_names=tuple(refuse_names),
        row_fn=lambda row: call_if(row and row[0], lambda: text_or(row[0])),
    )


def drive_feed_state(
    memory: dict[str, Any],
    *,
    tactics: str = "",
    problem: str = "",
    residual_fn: Callable[[str], Any],
    tree_fn: Callable[..., Any],
    inverse_src: Any,
) -> dict[str, Any]:
    """Overlay residuals and a decision tree. Does not write Lean."""

    from jevops.outer import call_if

    counts = call_if(tactics, lambda: residual_fn(tactics))
    tree = call_if(tactics, lambda: tree_fn(tactics, memory, problem))
    return feed_with_overlays(
        memory,
        tactics=tactics,
        problem=problem,
        counts=counts,
        inverse=call_if(counts, lambda: invert_multimap(inverse_src)),
        tree=tree,
    )


def drive_nca_tool(
    name: str,
    *,
    walk_fn: Callable[[], Any],
    hook_fn: Callable[[str], Any],
    mutate_fn: Callable[..., Any],
    eval_fn: Callable[..., Any],
    default_path: str = "portable_rewrites.py",
    default_tests: Sequence[str] = ("test_skill_improve_loop",),
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch an NCA tool. Lake is not called here."""

    from jevops.outer import as_dict, get_list, get_str

    memory = as_dict(kwargs.get("memory"), {})
    tactics = get_str(kwargs, "tactics")
    problem = get_str(kwargs, "problem")
    return dispatch_tool(
        name,
        extras={
            "nca_walk": lambda **_k: walk_fn(),
            "nca_hook": lambda **k: hook_fn(get_str(k, "path", default=default_path)),
            "nca_mutate": lambda **k: mutate_fn(
                memory,
                tactics=tactics,
                problem=problem,
                op=get_str(k, "op", default="auto"),
            ),
            "nca_eval": lambda **k: eval_fn(*get_list(k, "tests", default=list(default_tests))),
        },
        **kwargs,
    )


def drive_codepath_slice(
    name: str,
    *,
    resolve_fn: Callable[[str], Any],
    inspect_fn: Callable[[str], bool],
    read_fn: Callable[[Any], str],
    max_defs: int = 40,
    max_neighbors: int = 8,
) -> dict[str, Any]:
    """AST caller/callee slice. Missing paths and parse errors are not admits."""

    from jevops.outer import either, exc_head, head_seq

    path = resolve_fn(name)

    def _missing() -> dict[str, Any]:
        return pack_codepath_slice(
            ok=False,
            name=name,
            reason="codepath_not_allowed",
            inspect_only=bool(inspect_fn(name)),
        )

    def _present() -> dict[str, Any]:
        try:
            defs, calls_by = function_call_map(read_fn(path))
        except (OSError, SyntaxError) as exc:
            return pack_codepath_slice(ok=False, reason="parse_failed", error=exc_head(exc, 160))
        focus = focus_symbol(name, defs, calls_by)
        return pack_codepath_slice(
            ok=True,
            path=getattr(path, "name", str(path)),
            symbol=focus,
            definitions=head_seq(defs, max_defs),
            callees=head_seq(calls_by.get(focus), max_neighbors),
            callers=head_seq(
                [fn for fn, kids in calls_by.items() if focus and focus in kids],
                max_neighbors,
            ),
            inspect_only=bool(inspect_fn(name)),
        )

    return either(path is None, _missing, _present)


def pack_sidecar_index(
    files_payload: Sequence[Any],
    *,
    schema: str = "lra-nca-ast-sidecar/v1",
) -> dict[str, Any]:
    """JSON AST sidecar payload. Never campaign DuckDB."""

    return {
        "schema": schema,
        "n_files": len(list(files_payload)),
        "files": list(files_payload),
        "campaign_write": False,
        "called_docker0": False,
        "control_duckdb": False,
    }


def fill_sidecar_duckdb(
    dest: Any,
    graph: Mapping[str, Any],
    *,
    connect_fn: Callable[..., tuple[Any, Any]],
    exec_fn: Callable[..., Any],
    count_fn: Callable[..., int],
    try_import_fn: Callable[[str], Any],
    refuse_fn: Callable[..., bool],
    refuse_names: Sequence[str] = ("control.duckdb",),
) -> dict[str, Any]:
    """Fill a local symbols/calls DuckDB. Refuses campaign control.duckdb. JSON-LD first."""

    dest = Path(dest)
    if refuse_fn(dest, names=tuple(refuse_names), needles=tuple(refuse_names)):
        return {"ok": False, "reason": "campaign_db_refused", "control_duckdb": True, "called_docker0": False}
    duckdb = try_import_fn("duckdb")
    if duckdb is None:
        return {"ok": False, "reason": "duckdb_unavailable", "control_duckdb": False, "called_docker0": False}
    statements: list[Any] = [
        "CREATE TABLE IF NOT EXISTS symbols (qualified_name VARCHAR, path VARCHAR, symbol_kind VARCHAR)",
        "CREATE TABLE IF NOT EXISTS calls (caller VARCHAR, callee VARCHAR, path VARCHAR)",
        "DELETE FROM symbols",
        "DELETE FROM calls",
    ]
    for _bare, qnames in (graph.get("defs") or {}).items():
        for qname in qnames:
            statements.append(
                (
                    "INSERT INTO symbols VALUES (?, ?, ?)",
                    [qname, f"{str(qname).split(':', 1)[0]}.py", "function"],
                )
            )
    for caller, callees in (graph.get("calls") or {}).items():
        for callee in callees:
            statements.append(
                (
                    "INSERT INTO calls VALUES (?, ?, ?)",
                    [caller, callee, f"{str(caller).split(':', 1)[0]}.py"],
                )
            )
    con, _engine = connect_fn(dest, duckdb_module=duckdb)
    try:
        exec_fn(con, statements)
        n_sym = count_fn(con, "symbols")
        n_calls = count_fn(con, "calls")
    finally:
        close = getattr(con, "close", None)
        if callable(close):
            close()
    return {
        "ok": True,
        "n_symbols": n_sym,
        "n_calls": n_calls,
        "path": str(dest),
        "control_duckdb": False,
        "called_docker0": False,
        "campaign_write": False,
    }


def pack_cross_slice(
    *,
    symbol: str,
    callees: Sequence[str],
    callers: Sequence[str],
    source: str = "",
    n_defs: Any = None,
    cap: int = 12,
) -> dict[str, Any]:
    """Cross-module callers/callees. Ids only; no source bodies."""

    callees = list(callees or ())[: int(cap)]
    callers = list(callers or ())[: int(cap)]
    prefix = str(symbol).split(":")[0] + ":" if ":" in str(symbol) else ""
    cross = any(":" in item and not str(item).startswith(prefix) for item in callees + callers)
    out: dict[str, Any] = {
        "ok": True,
        "symbol": symbol,
        "callees": callees,
        "callers": callers,
        "cross_module": bool(cross) or any(":" in item for item in callees),
        "source_bodies": False,
        "called_docker0": False,
        "campaign_write": False,
        "complete": True,
    }
    if source:
        out["source"] = source
    if n_defs is not None:
        out["n_defs"] = n_defs
    return out


def slice_cross_or_local(
    name: str,
    *,
    inspect_fn: Callable[[str], Mapping[str, Any]],
    inspect_only_fn: Callable[[str], bool],
    db_hits_fn: Callable[[str], Sequence[Any]],
    match_fn: Callable[..., Any],
    callees_fn: Callable[..., Sequence[str]],
    callers_fn: Callable[..., Sequence[str]],
    graph_fn: Callable[[], Mapping[str, Any]],
    pick_fn: Callable[..., Any],
    local_fn: Callable[[str], Mapping[str, Any]],
    cap: int = 12,
    strip_prefixes: Sequence[str] = ("harness.",),
) -> dict[str, Any]:
    """DuckDB sidecar first, then AST graph, then local slice. No source bodies."""

    if inspect_only_fn(name):
        sliced = dict(inspect_fn(name) or {})
        sliced["cross_module"] = False
        return sliced
    raw_name = str(name or "").replace("ptr://codepath/", "")
    db_hits = list(db_hits_fn(raw_name.rsplit(":", 1)[-1]) or ())
    q_db = match_fn(db_hits, raw_name)
    if q_db:
        db_callees = list(callees_fn(q_db) or ())
        db_callers = list(callers_fn(q_db) or ())
        if db_callees or db_callers:
            packed = pack_cross_slice(
                symbol=str(q_db),
                callees=db_callees,
                callers=db_callers,
                source="sidecar_duckdb",
                cap=cap,
            )
            packed["cross_module"] = any(
                ":" in item and item.split(":")[0] != str(q_db).split(":")[0]
                for item in db_callees + db_callers
            )
            return packed
    graph = dict(graph_fn() or {})
    qname = pick_fn(name, graph.get("defs") or {}, graph.get("calls") or {}, strip_prefixes=strip_prefixes)
    if not qname:
        local = dict(local_fn(name) or {})
        local["cross_module"] = False
        return local
    calls = graph.get("calls") or {}
    callees = list(calls.get(qname) or [])[: int(cap)]
    callers = [
        fn for fn, kids in calls.items() if qname in kids or str(qname).rsplit(":", 1)[-1] in kids
    ][: int(cap)]
    return pack_cross_slice(
        symbol=str(qname),
        callees=callees,
        callers=callers,
        n_defs=graph.get("n_defs"),
        cap=cap,
    )
