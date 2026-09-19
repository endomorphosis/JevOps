#!/usr/bin/env python3
"""Outer-loop routing: closed JSON actions, deterministic fallback, NCA snapshot.

Grok (outer) does not write Lean. Jev does not write Lean.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
ACTIONS = ("run", "nest_inner", "mint", "skip_stem", "install_fold", "stop")


def parse_action(text: str, *, actions: tuple[str, ...] = ACTIONS) -> dict[str, Any]:
    """First JSON object in outer-loop text; fail closed to action=run."""

    match = _JSON_OBJ.search(str(text or ""))
    if not match:
        return {"action": "run", "reason": "no_json"}
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"action": "run", "reason": "bad_json"}
    if not isinstance(raw, dict):
        return {"action": "run", "reason": "not_object"}
    action = str(raw.get("action") or "run").strip()
    if action not in actions:
        return {"action": "run", "reason": "unknown_action"}
    out = {"action": action, "reason": str(raw.get("reason") or "router")}
    for key in ("stem", "name", "old", "new", "family"):
        if key in raw:
            out[key] = str(raw.get(key) or "")
    if "keep" in raw and isinstance(raw["keep"], list):
        out["keep"] = [str(item) for item in raw["keep"]]
    if "count" in raw:
        try:
            out["count"] = int(raw["count"])
        except (TypeError, ValueError):
            out["count"] = 1
    return out


def deterministic_route(
    *,
    gaps: list[dict[str, Any]],
    last_lake: list[dict[str, Any]],
    stalled: bool,
) -> dict[str, Any]:
    """Closed-vocab next action from gaps + last oracle rows (no grok)."""

    failed = [
        row
        for row in last_lake
        if row.get("ok") is False and str(row.get("kind") or "").startswith("port_")
    ]
    if failed:
        kind = str(failed[0].get("kind") or "")
        stem = kind[len("port_") :] if kind.startswith("port_") else kind
        return {
            "action": "skip_stem",
            "stem": stem.split("_pipeline")[0],
            "name": str(failed[0].get("name") or ""),
            "reason": "lake_failed_port",
        }
    for gap in gaps:
        mints = list((gap.get("proposed") or {}).get("mint") or gap.get("keep_structure") or [])
        if mints:
            return {
                "action": "mint",
                "stem": str(mints[0]),
                "name": str(gap.get("name") or ""),
                "reason": "autoresearch_mint",
            }
    if last_lake and all(str(row.get("skipped") or "") == "nca_budget" for row in last_lake):
        return {"action": "stop", "reason": "nca_budget"}
    if stalled:
        return {"action": "stop", "reason": "no_token_cut"}
    return {"action": "nest_inner", "reason": "continue_typesafe"}


def route_next(
    *,
    gaps: list[dict[str, Any]],
    last_lake: list[dict[str, Any]],
    stalled: bool,
    llm: bool = False,
    memory: Optional[Mapping[str, Any]] = None,
    generate_fn: Optional[Any] = None,
    prompt: str = "",
    charge_fn: Optional[Any] = None,
    ledger: Any = None,
) -> dict[str, Any]:
    """Halt/budget stop, else deterministic route, else optional LLM JSON action."""

    nca = nca_status(memory)
    if nca.get("budget_dead"):
        return {"action": "stop", "reason": "nca_budget", "router": "nca"}
    if nca.get("halt"):
        return {"action": "stop", "reason": "nca_halt", "router": "nca"}
    fallback = deterministic_route(gaps=gaps, last_lake=last_lake, stalled=stalled)
    if not llm or generate_fn is None:
        fallback["router"] = "deterministic"
        return fallback
    try:
        text = generate_fn(prompt)
        if isinstance(text, tuple):
            text = text[0]
    except Exception as exc:
        fallback["router"] = "llm_router_error"
        fallback["error"] = str(exc)[:240]
        return fallback
    action = parse_action(str(text))
    action["router"] = "llm_router"
    action["raw_head"] = str(text)[:240]
    if isinstance(memory, dict):
        try:
            charger = charge_fn
            if charger is None:
                from jevops.nca import charge_budget

                charger = charge_budget
            charger(memory, ledger=ledger, event="grok")
        except Exception:
            pass
    return action


def compact_gaps(gaps: Sequence[Mapping[str, Any]], *, help_n: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "name": item.get("name"),
            "proposed": item.get("proposed"),
            "keep_structure": item.get("keep_structure"),
            "top_help": (item.get("top_help") or [])[: int(help_n)],
        }
        for item in gaps
    ]


def compact_lake(rows: Sequence[Mapping[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "name": row.get("name"),
            "kind": row.get("kind"),
            "ok": row.get("ok"),
            "tokens": row.get("tokens"),
            "skipped": row.get("skipped"),
            "error_class": row.get("error_class"),
        }
        for row in list(rows)[: int(limit)]
    ]


def seed_runtime(
    memory: dict[str, Any],
    *,
    seed_fn: Any,
    overlay_fn: Any,
    keepbest_fn: Optional[Any] = None,
) -> None:
    """Seed board, overlay live status, optional keep-best. Fail closed."""

    try:
        seed_fn(memory)
        overlay_fn(memory)
        if keepbest_fn is not None:
            try:
                keepbest_fn(memory)
            except Exception:
                pass
    except Exception:
        pass


def memory_counts(memory: Mapping[str, Any]) -> dict[str, int]:
    return {
        "n_successes": len(memory.get("successes") or []),
        "n_failures": len(memory.get("failures") or []),
        "n_blacklist": len(memory.get("blacklist") or []),
    }


def board_total(board: Mapping[str, int]) -> int:
    return int(sum(board.values()))


def lookup_named(records: Sequence[Mapping[str, Any]], name: str) -> Optional[Mapping[str, Any]]:
    want = str(name or "")
    return next((item for item in records if str(item.get("name") or "") == want), None)


def tokens_from_canaries(
    payload: Mapping[str, Any],
    *,
    names: Optional[Sequence[str]] = None,
) -> dict[str, int]:
    """Read n_tokens from canary analysis rows."""

    allow = set(names) if names is not None else None
    board: dict[str, int] = {}
    for row in payload.get("canaries") or []:
        name = str((row.get("analysis") or {}).get("name") or "")
        tok = (row.get("analysis") or {}).get("n_tokens")
        if name and tok and (allow is None or name in allow):
            board[name] = int(tok)
    return board


def write_json_pair(
    directory: Path,
    payload: Mapping[str, Any],
    *,
    prefix: str,
    latest: str,
) -> Path:
    """Write stamped JSON and a latest alias. No Lean."""

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n"
    (out / f"{prefix}-{stamp}.json").write_text(text)
    latest_path = out / latest
    latest_path.write_text(text)
    return latest_path


def glob_stem_int(directory: Path, pattern: str) -> list[tuple[int, Path]]:
    """Files whose last stem token is an int (token count), shortest first."""

    rows: list[tuple[int, Path]] = []
    for path in Path(directory).glob(pattern):
        tail = path.stem.rsplit("-", 1)[-1]
        tok = int(tail) if tail.isdigit() else 10**9
        rows.append((tok, path))
    rows.sort()
    return rows


def stall_after(total: int, best_total: int, stalled: int) -> tuple[int, int, bool]:
    """Shorter board total is improvement. Returns (best_total, stalled, improved)."""

    improved = int(total) < int(best_total) and int(total) > 0
    if improved:
        return int(total), 0, True
    return int(best_total), int(stalled) + 1, False


def should_stop_outer(
    *,
    action: Mapping[str, Any],
    applied: Mapping[str, Any],
    stalled: int,
    stalled_limit: int = 2,
    hard_stopped: bool = False,
    halt: Optional[Mapping[str, Any]] = None,
) -> str:
    """Closed stop reason, or empty to keep looping."""

    if str(action.get("action") or "") == "stop" or str(applied.get("applied") or "") == "stop":
        return str(action.get("reason") or "stop")
    if hard_stopped:
        return "ledger_hard_stop"
    if int(stalled) >= int(stalled_limit):
        return "no_token_cut"
    if halt:
        if halt.get("budget_dead"):
            return "nca_budget"
        if halt.get("halt"):
            return "nca_halt"
    return ""


def history_row(
    *,
    step: int,
    llm: bool,
    board: Mapping[str, Any],
    total: int,
    improved: bool,
    last_lake: Sequence[Mapping[str, Any]],
    action: Mapping[str, Any],
    applied: Mapping[str, Any],
    traces: Sequence[Any],
    flatten_fn: Optional[Any] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    flatten = flatten_fn
    depths = []
    if flatten is not None:
        depths = [
            int(ev.get("depth") or 0)
            for tr in traces
            for ev in flatten(list(tr or []))
        ]
    return {
        "step": step,
        "outer": "grok" if llm else "deterministic",
        "inner": "typesafe_nested",
        "board": dict(board),
        "total": int(total),
        "improved": bool(improved),
        "n_lake": len(list(last_lake or [])),
        "n_ok": sum(1 for item in last_lake or [] if item.get("ok")),
        "action": dict(action),
        "applied": dict(applied),
        "n_traces": len(list(traces or [])),
        "max_trace_depth": max(depths, default=0),
        "jev_calls": ((payload or {}).get("ledger") or {}).get("jev_calls"),
    }


def format_prompt(
    *,
    preamble: str,
    actions: Sequence[str],
    extra: str = "",
    board: Mapping[str, Any],
    gaps: Sequence[Mapping[str, Any]],
    last_lake: Sequence[Mapping[str, Any]],
    nca_status: Optional[Mapping[str, Any]] = None,
    total: Optional[int] = None,
) -> str:
    """Closed outer-router prompt. Does not write Lean."""

    tot = int(total) if total is not None else int(sum(int(v) for v in dict(board).values() if str(v).lstrip("-").isdigit() or isinstance(v, int)))
    return (
        str(preamble)
        + f"action must be one of: {', '.join(actions)}.\n"
        + str(extra)
        + f"keep_best_tokens={json.dumps(dict(board), sort_keys=True)}\n"
        + f"total={tot}\n"
        + f"gaps={json.dumps(compact_gaps(gaps), sort_keys=True)}\n"
        + f"last_lake={json.dumps(compact_lake(last_lake), sort_keys=True)}\n"
        + f"nca={json.dumps(dict(nca_status or {}), sort_keys=True)}\n"
    )


def run_steps(
    *,
    n: int,
    memory: dict[str, Any],
    llm: bool,
    gaps_fn: Any,
    route_fn: Any,
    apply_fn: Any,
    inner_fn: Any,
    board_fn: Any,
    persist_fn: Optional[Any] = None,
    halt_fn: Optional[Any] = None,
    flatten_fn: Optional[Any] = None,
    hard_stop_fn: Optional[Any] = None,
    stalled_limit: int = 2,
    on_inner_start: Optional[Any] = None,
) -> dict[str, Any]:
    """OUTER route/apply then INNER payload. Implementations inject lake/Jev."""

    history: list[dict[str, Any]] = []
    board, best_total = board_fn()
    stalled = 0
    stop_reason = ""
    last_lake: list[dict[str, Any]] = []
    gaps = list(gaps_fn() or [])
    total = int(best_total)
    for step in range(max(1, int(n))):
        action = dict(
            route_fn(
                board=board,
                gaps=gaps,
                last_lake=last_lake,
                stalled=stalled >= int(stalled_limit),
            )
            or {}
        )
        applied = dict(apply_fn(memory, action) or {})
        if persist_fn is not None:
            persist_fn(memory)
        payload: dict[str, Any] = {}
        traces: list[Any] = []
        if str(action.get("action") or "") != "stop":
            if on_inner_start is not None:
                on_inner_start(memory)
            payload = dict(inner_fn(step) or {})
            gaps = list(payload.get("skill_analysis") or gaps_fn() or [])
            last_lake = list(payload.get("lake") or [])
            traces = [row.get("trace") for row in payload.get("canaries") or [] if row.get("trace")]
        board, total = board_fn()
        best_total, stalled, improved = stall_after(total, best_total, stalled)
        row = history_row(
            step=step,
            llm=llm,
            board=board,
            total=total,
            improved=improved,
            last_lake=last_lake,
            action=action,
            applied=applied,
            traces=traces,
            flatten_fn=flatten_fn,
            payload=payload,
        )
        history.append(row)
        halt = None
        if halt_fn is not None:
            try:
                halt = halt_fn(memory)
                row["nca_halt"] = halt
            except Exception:
                halt = None
        stop_reason = should_stop_outer(
            action=action,
            applied=applied,
            stalled=stalled,
            stalled_limit=stalled_limit,
            hard_stopped=bool(hard_stop_fn() if hard_stop_fn is not None else False),
            halt=halt,
        )
        if stop_reason:
            break
    return {
        "history": history,
        "stop_reason": stop_reason,
        "best_total": best_total,
        "board": dict(board),
        "total": int(total),
        "gaps": gaps,
        "last_lake": last_lake,
    }


def apply_action(memory: dict[str, Any], action: Mapping[str, Any]) -> dict[str, Any]:
    """Mutate memory from a closed action. No Python exec. No Lean."""

    from jevops import hooks

    kind = str(action.get("action") or "run")
    if kind == "skip_stem":
        stem = str(action.get("stem") or "")
        name = str(action.get("name") or "")
        if not stem:
            return {"ok": False, "reason": "no_stem"}
        key = f"{name}::port_{stem}" if name else f"*::port_{stem}"
        blacklist = memory.setdefault("blacklist", [])
        if key not in blacklist:
            blacklist.append(key)
        return {"ok": True, "applied": "skip_stem", "key": key}
    if kind == "mint":
        stem = str(action.get("stem") or "")
        name = str(action.get("name") or "")
        if not stem:
            return {"ok": False, "reason": "no_stem"}
        memory.setdefault("expanded", []).append(
            {
                "name": name,
                "notes": [{"action": "keep_structure", "mint": [stem], "source": "loop"}],
            }
        )
        return {"ok": True, "applied": "mint", "stem": stem}
    if kind == "install_fold":
        install = hooks.resolve("install_fold", "binder_use", "install_memory_skill")
        if install is None:
            return {"ok": False, "reason": "no_install_fold"}
        installed = install(memory, action)
        return {"ok": bool(installed.get("ok")), **installed}
    return {"ok": True, "applied": kind}


def nca_status(memory: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compact NCA snapshot for the outer loop."""

    mem = dict(memory or {})
    try:
        from jevops import nca as lra_nca
        from jevops import board as lra_board

        halt = lra_nca.should_halt(mem)
        window = lra_board.board_window(mem)
    except Exception:
        halt, window = {}, []
    budget = (((mem.get("nca") or {}).get("grid") or {}).get("ptr://tool/budget") or {})
    plan = {}
    try:
        from jevops import plan as lra_plan

        plan = lra_plan.plan_window(mem)
    except Exception:
        plan = {}
    kern = dict((mem.get("nca") or {}).get("kernel") or {})
    stats = dict(kern.get("stats") or {})
    return {
        "halt": bool(halt.get("halt")),
        "budget_dead": bool(halt.get("budget_dead")),
        "budget_energy": halt.get("budget_energy", budget.get("energy")),
        "n_hot_tasks": halt.get("n_hot_tasks"),
        "board_window": window[:6],
        "plan": plan,
        "kernel": {
            "policy": kern.get("policy") or "arc",
            "tick": kern.get("tick") or 0,
            "n_l1": len(kern.get("l1") or {}),
            "n_negative": len(kern.get("negative") or {}),
            "n_in_flight": len(kern.get("in_flight") or []),
            "stats": stats,
        },
    }
