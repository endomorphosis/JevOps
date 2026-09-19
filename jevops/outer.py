#!/usr/bin/env python3
"""Outer-loop routing: closed JSON actions, deterministic fallback, NCA snapshot.

Grok (outer) does not write Lean. Jev does not write Lean.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
ACTIONS = ("run", "nest_inner", "mint", "skip_stem", "install_fold", "stop")


def split_after_prefix(
    src: str,
    prefix: str,
    *,
    name: str = "",
    error_cls: Any = ValueError,
    miss_msg: Optional[str] = None,
) -> str:
    """Require src.startswith(prefix); return the suffix. Never scans for :=."""

    if not isinstance(prefix, str) or not prefix:
        raise error_cls(f"{name}: prefix must be a non-empty string" if name else "prefix must be a non-empty string")
    if not isinstance(src, str) or not src:
        raise error_cls(f"{name}: src must be a non-empty string" if name else "src must be a non-empty string")
    if not src.startswith(prefix):
        raise error_cls(
            miss_msg
            or (f"{name}: src does not start with prefix" if name else "src does not start with prefix")
        )
    return src[len(prefix) :]


def strip_leading_prefixes(
    text: str,
    prefixes: Sequence[str],
    *,
    error_cls: Any = ValueError,
    empty_msg: str = "body is empty",
    miss_msg: str = "body does not start with a known prefix",
) -> str:
    if not isinstance(text, str) or not text:
        raise error_cls(empty_msg)
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix) :]
    raise error_cls(miss_msg)


def join_decl(
    statement: str,
    tactics: str,
    *,
    header: str = "",
    by_marker: str = " := by\n",
) -> str:
    core = str(statement) + by_marker + str(tactics).lstrip("\n")
    if isinstance(header, str) and header.strip():
        return header.rstrip() + "\n\n" + core
    return core


def head_lines(text: str, n: int) -> str:
    return "\n".join(str(text or "").splitlines()[: max(0, int(n))]).strip("\n")


def ensure_sys_path(path: Any) -> None:
    import sys

    text = str(path)
    if text and text not in sys.path:
        sys.path.insert(0, text)


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest_canonical(payload: Any) -> str:
    return digest_hex(canonical_bytes(payload))


def exclude_named(
    records: Sequence[Mapping[str, Any]],
    query: str,
    *,
    name_key: str = "name",
) -> list[Mapping[str, Any]]:
    want = str(query or "")
    return [row for row in records if str(row.get(name_key) or "") != want]


def unique_names(
    records: Sequence[Mapping[str, Any]],
    *,
    name_key: str = "name",
) -> list[str]:
    return [str(row.get(name_key) or "") for row in records]


def digest_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_jsonl_objects(
    path: Path,
    *,
    expected_digest: Optional[str] = None,
    expected_n: Optional[int] = None,
    required_fields: Sequence[str] = (),
    mismatch_exc: Any = ValueError,
    record_exc: Any = ValueError,
) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Load JSONL objects. Optional digest/count/field checks. No Lean."""

    raw = Path(path).read_bytes()
    digest = digest_hex(raw)
    if expected_digest is not None and digest != expected_digest:
        raise mismatch_exc(f"JSONL hash mismatch: {digest} != {expected_digest}")
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if expected_n is not None and len(records) != int(expected_n):
        raise record_exc(f"JSONL must contain {expected_n} records, got {len(records)}")
    required = tuple(required_fields)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise record_exc(f"record {index} is not an object")
        missing = [field for field in required if field not in record]
        if missing:
            raise record_exc(f"record {index} missing fields: {missing}")
    return raw, digest, records


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


def closed_evidence(**extra: Any) -> dict[str, Any]:
    """Evidence flags that never claim Lean, docker0, Track 2, or Arena scores."""

    out: dict[str, Any] = {
        "called_docker0": False,
        "official_track2": False,
        "arena_score": None,
        "jev_writes_lean": False,
    }
    out.update(extra)
    return out


def namespace(**kwargs: Any) -> Any:
    """Closed attribute bag (argparse-compatible). No Lean."""

    from types import SimpleNamespace

    return SimpleNamespace(**kwargs)


def inner_budget(
    args: Any,
    *,
    min_steps: int,
    rounds_key: str = "rounds",
    depth_key: str = "nest_depth",
    default_depth: int = 3,
) -> tuple[int, int]:
    """(max_steps, max_depth) from args. No Lean."""

    max_steps = max(int(arg_value(args, rounds_key, 1, cast=int) or 1), int(min_steps))
    max_depth = int(arg_value(args, depth_key, default_depth, cast=int) or default_depth)
    return max_steps, max_depth


def token_map(
    records: Sequence[Mapping[str, Any]],
    *,
    token_fn: Any,
    body_fn: Optional[Any] = None,
) -> dict[str, int]:
    """name → token count. body_fn/token_fn injected. Fail closed per row."""

    out: dict[str, int] = {}
    for rec in records:
        name = str(rec.get("name") or "")
        if not name:
            continue
        try:
            body = body_fn(rec) if body_fn is not None else str(rec.get("src") or "")
            if not body:
                continue
            out[name] = int(token_fn(body))
        except Exception:
            continue
    return out


def arg_value(args: Any, key: str, default: Any, *, cast: Any = None) -> Any:
    """getattr with None→default, optional cast. No Lean."""

    raw = default
    if args is not None:
        raw = getattr(args, key, default)
    if raw is None:
        raw = default
    return cast(raw) if cast is not None else raw


def safe_call(fn: Any, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


def starting_body(
    fallback: str,
    directory: Any,
    name: str,
    *,
    glob_fmt: str = "random-best-{safe}-*.lean",
    extras: Optional[Mapping[str, str]] = None,
) -> str:
    """Keep-best glob, then a named extra file, else fallback. Does not generate Lean."""

    if directory is None:
        return fallback
    out = Path(directory)
    body = read_shortest_glob(out, glob_fmt.format(safe=file_stem(name or "canary"), name=name))
    if body is not None:
        return body
    fname = dict(extras or {}).get(str(name or ""))
    if fname:
        path = out / fname
        if path.is_file():
            return path.read_text(encoding="utf-8").strip("\n")
    return fallback


def file_stem(name: str, *, limit: int = 80, empty: str = "canary") -> str:
    """Filesystem-safe stem from a theorem/problem name."""

    return str(name or empty).replace("/", "_")[: int(limit)]


def load_json_object(path: Path) -> dict[str, Any]:
    """Fail closed to {}. No Lean."""

    target = Path(path)
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def read_shortest_glob(directory: Path, pattern: str, *, encoding: str = "utf-8") -> Optional[str]:
    """Read the shortest glob_stem_int hit. None if missing."""

    bests = glob_stem_int(directory, pattern)
    if not bests:
        return None
    return bests[0][1].read_text(encoding=encoding).strip("\n")


def merge_keep_best(
    directory: Path,
    names: Sequence[str],
    *,
    latest_json: str = "",
    glob_fmt: str = "random-best-{safe}-*.lean",
    extras: Optional[Mapping[str, tuple[str, int]]] = None,
) -> dict[str, int]:
    """JSON canary tokens, then glob files, then optional named extras."""

    out = Path(directory)
    board: dict[str, int] = {}
    if latest_json:
        board.update(tokens_from_canaries(load_json_object(out / latest_json), names=names))
    extra = dict(extras or {})
    for name in names:
        safe = file_stem(name)
        bests = glob_stem_int(out, glob_fmt.format(safe=safe, name=name))
        if bests:
            file_tok = int(bests[0][0])
            board[name] = min(int(board.get(name) or file_tok), file_tok)
            continue
        if name in extra:
            fname, tok = extra[name]
            if (out / fname).is_file():
                board[name] = min(int(board.get(name) or int(tok)), int(tok))
    return board


def write_best_body(
    directory: Path,
    name: str,
    tokens: int,
    body: str,
    *,
    prefix: str = "random-best",
    suffix: str = ".lean",
) -> Path:
    """Write a keep-best body next to other evidence. Does not generate Lean."""

    path = Path(directory) / f"{prefix}-{file_stem(name)}-{int(tokens)}{suffix}"
    path.write_text(str(body) + "\n", encoding="utf-8")
    return path


def landscape_rows(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compact analysis rows for canary evidence. No Lean."""

    rows: list[dict[str, Any]] = []
    for item in items:
        families = list(item.get("families") or [])
        counts = dict(item.get("counts") or {})
        rows.append(
            {
                "name": item.get("name"),
                "source": item.get("source"),
                "n_tokens": item.get("n_tokens"),
                "n_mca_holes": item.get("n_mca_holes"),
                "n_have": counts.get("n_have"),
                "n_simp_at": counts.get("n_simp_at"),
                "n_rw": counts.get("n_rw"),
                "n_induction": counts.get("n_induction"),
                "top_family": (families[0].get("family") if families else None),
            }
        )
    return rows


def restore_if(path: Any, data: bytes) -> bool:
    """Write bytes back if the file still exists. Returns True if written."""

    target = Path(path)
    if target.is_file() and data:
        target.write_bytes(data)
        return True
    return False


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


def load_env_file(
    path: Any,
    *,
    environ: Optional[Any] = None,
    encoding: str = "utf-8",
    strip_quotes: bool = False,
) -> dict[str, str]:
    """KEY=VALUE lines. setdefault into environ (os.environ by default)."""

    import os

    loaded: dict[str, str] = {}
    target = Path(path) if path else None
    if target is None or not target.is_file():
        return loaded
    dest = os.environ if environ is None else environ
    for line in target.read_text(encoding=encoding).splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, value = text.split("=", 1)
        key, val = name.strip(), value.strip()
        if strip_quotes and len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        dest.setdefault(key, val)
        loaded[key] = val
    return loaded


def pin_sys_path(
    path: Any,
    *,
    environ: Optional[Any] = None,
    defaults: Optional[Mapping[str, str]] = None,
) -> None:
    """Move path to sys.path[0]. setdefault env defaults."""

    import os
    import sys

    text = str(path or "")
    if text:
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    dest = os.environ if environ is None else environ
    for key, value in dict(defaults or {}).items():
        dest.setdefault(str(key), str(value))


def is_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "503" in text or "unavailable" in text or "429" in text


def retry_call(
    fn: Any,
    *,
    attempts: int = 4,
    sleep_fn: Optional[Any] = None,
    unavailable_pred: Optional[Any] = None,
    backoff: Optional[Any] = None,
) -> Any:
    """Retry fn on unavailable (503/429). Last exception is raised."""

    import time

    sleep = sleep_fn or time.sleep
    pred = unavailable_pred or is_unavailable
    delay_fn = backoff or (lambda index: min(20.0, 2.0 ** int(index)))
    last: Optional[BaseException] = None
    for attempt in range(max(1, int(attempts))):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not pred(exc) or attempt + 1 >= int(attempts):
                raise
            sleep(delay_fn(attempt))
    raise last or RuntimeError("retry exhausted")


def failed_leaves_from_history(
    payload: Mapping[str, Any],
    *,
    lake_fail_actions: Sequence[str] = ("lake",),
    skip_actions: Sequence[str] = ("skip_lake", "skip_not_shorter"),
) -> set[str]:
    """Leaf ids from JSON history that lake-failed or were skipped."""

    failed: set[str] = set()
    lake = {str(x) for x in lake_fail_actions}
    skip = {str(x) for x in skip_actions}
    for row in (payload or {}).get("history") or []:
        picked = row.get("picked") if isinstance(row, Mapping) else None
        leaf = str((picked or {}).get("leaf") or "") if isinstance(picked, Mapping) else ""
        if not leaf:
            continue
        action = str(row.get("action") or "")
        if action in lake and row.get("ok") is False:
            failed.add(leaf)
        if action in skip:
            failed.add(leaf)
    return failed


def fill_template(
    template: str,
    values: Mapping[str, Any],
    *,
    left: str = "{{",
    right: str = "}}",
) -> str:
    """Replace ``{{key}}`` placeholders. No Lean."""

    filled = str(template)
    for key, value in dict(values or {}).items():
        filled = filled.replace(f"{left}{key}{right}", str(value))
    return filled


def version_sort_key(tag: str, *, strip_prefix: str = "v") -> tuple[tuple[int, int, int], str]:
    """Numeric (major, minor, patch) then suffix. ``v4.26.0-rc1`` → ((4,26,0), 'rc1')."""

    text = str(tag or "")
    if strip_prefix and text.startswith(strip_prefix):
        text = text[len(strip_prefix) :]
    main, _, suffix = text.partition("-")
    parts = main.split(".")
    nums = [int(part) if part.isdigit() else 0 for part in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2]), suffix


def mean_nonneg(rows: Sequence[Any], *, getter: Any) -> float:
    """Mean of max(0, getter(item)). Empty → 0.0."""

    items = list(rows or ())
    if not items:
        return 0.0
    return sum(max(0.0, float(getter(item))) for item in items) / float(len(items))


def flatten_version_tags(version_info: Any) -> list[str]:
    """Dict keys or bare strings from a version_info list."""

    listed: list[str] = []
    for item in version_info or []:
        if isinstance(item, Mapping):
            listed.extend(str(tag) for tag in item.keys() if str(tag).strip())
        elif isinstance(item, str) and item.strip():
            listed.append(item)
    return listed


def iter_tag_commit_pins(
    version_info: Any,
    *,
    pin_fn: Any,
    normalize_fn: Any = None,
    error_cls: Any = ValueError,
    not_list: str = "version_info must be a list of {tag: commit} maps",
    empty_tag: str = "version_info[{index}] has an empty tag",
    bad_commit: str = "version_info[{index}] git commit must be a string, not {type}",
    not_map: str = "version_info[{index}] is not a {{tag: commit}} map",
    empty: str = "version_info is empty",
) -> list[Any]:
    """List of {tag: commit} maps → pin objects. normalize_fn/pin_fn injected."""

    if not isinstance(version_info, list):
        raise error_cls(not_list)
    pins: list[Any] = []
    for index, item in enumerate(version_info):
        if isinstance(item, dict) and item:
            for tag, commit in item.items():
                if not isinstance(tag, str) or not tag.strip():
                    raise error_cls(empty_tag.format(index=index))
                if commit is None:
                    commit_text = ""
                elif isinstance(commit, str):
                    commit_text = commit.strip()
                else:
                    raise error_cls(bad_commit.format(index=index, type=type(commit).__name__))
                text = normalize_fn(tag) if normalize_fn is not None else tag.strip()
                pins.append(pin_fn(text, commit_text))
            continue
        raise error_cls(not_map.format(index=index))
    if not pins:
        raise error_cls(empty)
    return pins


def listed_all_ok(
    listed: Sequence[str],
    items: Sequence[Any],
    *,
    id_fn: Any,
    ok_fn: Any,
) -> bool:
    """True iff every listed id is present and ok_fn(item). Empty listed → False."""

    rows = list(listed or ())
    if not rows:
        return False
    by_id = {id_fn(item): item for item in items or ()}
    if any(tag not in by_id for tag in rows):
        return False
    return all(ok_fn(by_id[tag]) for tag in rows)


def load_module_from_path(path: Any, name: str) -> Optional[Any]:
    """Load a Python module from a file path. None if missing."""

    import importlib.util
    import sys

    target = Path(path)
    if not target.is_file():
        return None
    spec = importlib.util.spec_from_file_location(str(name), target)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def http_get(url: str, *, timeout: float, accept: str = "application/json") -> tuple[Optional[int], str]:
    """GET url. Returns (status, error). Transport errors → (None, 'Type: msg')."""

    import urllib.error
    import urllib.request

    request = urllib.request.Request(str(url), method="GET", headers={"Accept": str(accept)})
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            return int(getattr(response, "status", 200) or 200), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc.reason or exc)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def require_positive_above(
    value: Any,
    floor: float,
    *,
    error_cls: Any = ValueError,
    too_small_cls: Optional[Any] = None,
    not_positive: str = "must be a positive number",
    too_small: str = "must exceed {floor}",
) -> float:
    """Reject bool/non-numeric/≤0; reject ≤ floor with too_small.format(value, floor)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise error_cls(not_positive)
    number = float(value)
    if number <= float(floor):
        raise (too_small_cls or error_cls)(str(too_small).format(value=number, floor=floor))
    return number


def first_group(text: str, pattern: Any, *, group: int = 1, method: str = "search") -> Optional[str]:
    """First regex group as str, or None. Empty text → None."""

    if not isinstance(text, str) or not text.strip():
        return None
    finder = getattr(pattern, method, None)
    if finder is None:
        return None
    match = finder(text)
    if match is None:
        return None
    got = match.group(int(group))
    return None if got is None else str(got)


def first_group_int(text: str, pattern: Any) -> Optional[int]:
    """First regex group as int, or None. Empty text → None."""

    raw = first_group(text, pattern)
    return None if raw is None else int(raw)


def first_nonempty(mapping: Mapping[str, Any], *keys: str, default: str = "") -> str:
    """First stripped non-empty mapping[key]."""

    row = dict(mapping or {})
    for key in keys:
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return str(default)


def contains_flags(text: str, checks: Mapping[str, Any]) -> dict[str, bool]:
    """Lowercased membership flags. spec is a needle, all-tuple, or {all|any|absent}."""

    blob = str(text or "").lower()
    out: dict[str, bool] = {}
    for key, spec in dict(checks or {}).items():
        if isinstance(spec, Mapping):
            if spec.get("absent") is not None:
                needles = list(spec.get("absent") or ())
                out[str(key)] = all(str(item).lower() not in blob for item in needles)
            elif spec.get("any") is not None:
                needles = list(spec.get("any") or ())
                out[str(key)] = any(str(item).lower() in blob for item in needles)
            else:
                needles = list(spec.get("all") or ())
                out[str(key)] = all(str(item).lower() in blob for item in needles)
        elif isinstance(spec, (list, tuple)):
            out[str(key)] = all(str(item).lower() in blob for item in spec)
        else:
            out[str(key)] = str(spec).lower() in blob
    return out


def first_env_path(*names: str, default: Any, environ: Optional[Any] = None) -> Path:
    """First nonempty env path, else default."""

    import os

    dest = os.environ if environ is None else environ
    for name in names:
        raw = dest.get(name)
        if raw is not None and str(raw).strip():
            return Path(str(raw)).expanduser()
    return Path(default)


def allow_or_deny(
    value: Optional[str] = None,
    *,
    deny: Sequence[str] = (),
    default: str = "allow",
    env_keys: Sequence[str] = (),
    environ: Optional[Any] = None,
) -> str:
    """allow unless value/env is in deny."""

    import os

    dest = os.environ if environ is None else environ
    raw = value
    if raw is None or not str(raw).strip():
        for key in env_keys:
            got = dest.get(key)
            if got is not None and str(got).strip():
                raw = got
                break
    if raw is None or not str(raw).strip():
        return str(default)
    text = str(raw).strip().lower()
    if text in {str(item).lower() for item in deny}:
        return "deny"
    return str(default)


def is_executable(path: Any) -> bool:
    import stat

    target = Path(path)
    try:
        mode = target.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def url_cache_key(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(str(url or ""))
    host = parsed.netloc or "no-host"
    path = parsed.path.strip("/") or "unnamed"
    return f"{host}/{path}"


def normalize_tag(
    value: str,
    *,
    prefix: str = "",
    error_cls: Any = ValueError,
    empty: str = "tag must be a nonempty string",
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_cls(empty)
    text = value.strip()
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :]
    elif ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.strip()
    if not text:
        raise error_cls(f"tag {value!r} normalized to empty")
    return text


def copy_tree(src: Any, dest: Any) -> None:
    source = Path(src)
    target_root = Path(dest)
    target_root.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = target_root / entry.name
        if entry.is_dir():
            copy_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


def redact_secret(text: str, secret: str, *, token: str = "[redacted]") -> str:
    if not text:
        return ""
    if secret:
        return str(text).replace(str(secret), str(token))
    return str(text)


def require_host(
    url: str,
    expected: str,
    *,
    forbidden: Sequence[str] = (),
    error_cls: Any = ValueError,
    prototype_fmt: str = "refusing prototype host {host!r}",
    mismatch_fmt: str = "refusing host {host!r}; expected {expected}",
) -> str:
    from urllib.parse import urlparse

    host = (urlparse(str(url)).hostname or "").lower()
    banned = {str(item).lower() for item in forbidden}
    if host in banned or host.endswith(".local"):
        raise error_cls(prototype_fmt.format(host=host, expected=expected))
    if host != str(expected).lower():
        raise error_cls(mismatch_fmt.format(host=host, expected=expected))
    return host


def estimate_tokens_chars(text: str, *, width: int = 4, minimum: int = 1) -> int:
    """Ceil(len/width) token estimate. Empty → minimum."""

    if not text:
        return int(minimum)
    return max(int(minimum), (len(text) + int(width) - 1) // int(width))


def first_match(rules: Sequence[tuple[Any, str]], *, default: str = "") -> str:
    """First (pred, action) whose pred() is true."""

    for pred, action in rules:
        if pred():
            return str(action)
    return str(default)


def poll_until(
    probe_fn: Any,
    *,
    ok_fn: Any,
    timeout: float,
    interval: float = 0.25,
    sleep_fn: Optional[Any] = None,
    min_interval: float = 0.01,
) -> Any:
    """Call probe_fn until ok_fn(result) or timeout. Returns last result."""

    import time

    sleep = sleep_fn or time.sleep
    deadline = time.monotonic() + max(0.0, float(timeout))
    last = probe_fn()
    while not ok_fn(last) and time.monotonic() < deadline:
        sleep(max(float(min_interval), float(interval)))
        last = probe_fn()
    return last


def sanitize_ident(
    name: str,
    *,
    pattern: str = r"[^A-Za-z0-9._-]+",
    error_cls: Any = ValueError,
    empty: str = "name sanitizes empty",
) -> str:
    cleaned = re.sub(pattern, "_", str(name)).strip("._")
    if not cleaned:
        raise error_cls(empty)
    return cleaned


def write_cas(
    root: Any,
    data: bytes,
    *,
    prefix: str = "artifacts",
    filename: str = "blob",
) -> str:
    """Write data under root/prefix/aa/<digest>/filename. Returns digest hex."""

    digest = digest_hex(data)
    folder = Path(root) / str(prefix) / digest[:2] / digest
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / str(filename)
    if not path.exists():
        path.write_bytes(data)
    return digest


def dump_tiny(
    payload: Any,
    *,
    max_bytes: int,
    error_cls: Any = ValueError,
    fmt: str = "payload {n} bytes exceeds cap {max_bytes}",
) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    n = len(blob.encode("utf-8"))
    if n > int(max_bytes):
        raise error_cls(fmt.format(n=n, max_bytes=int(max_bytes)))
    return blob


def keyed_pair(
    key: str,
    table: Mapping[str, tuple[Any, ...]],
    default: tuple[Any, ...],
) -> tuple[Any, ...]:
    return tuple(table.get(str(key or "").strip().lower(), default))


def stat_dev_ino(path: Any) -> Optional[tuple[int, int, int]]:
    import os

    try:
        st = Path(path).stat()
    except OSError:
        return None
    return os.major(st.st_dev), os.minor(st.st_dev), st.st_ino


def object_fields(
    obj: Any,
    fields: Sequence[str],
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Project an object or mapping onto fields. None → None."""

    more = dict(extra or {})
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        out = dict(obj)
        out.update(more)
        return out
    if fields and hasattr(obj, str(fields[0])):
        out = {str(name): getattr(obj, name, None) for name in fields}
        out.update(more)
        return out
    out = {"repr": str(obj)}
    out.update(more)
    return out


def digest_file(path: Any) -> str:
    return digest_hex(Path(path).read_bytes())


def digest_text(text: str) -> str:
    return digest_hex(str(text).encode("utf-8"))


def write_executable(path: Any, text: str, *, encoding: str = "utf-8") -> Path:
    import stat

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding=encoding)
    mode = target.stat().st_mode
    target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def write_json(path: Any, payload: Any, *, indent: int = 2) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=indent, sort_keys=True) + "\n", encoding="utf-8")
    return target


def first_where(
    items: Sequence[Any],
    pred: Any,
    *,
    error_cls: Optional[Any] = None,
    miss: str = "",
) -> Any:
    for item in items or ():
        if pred(item):
            return item
    if error_cls is not None:
        raise error_cls(miss)
    return None


def after_named(
    records: Sequence[Mapping[str, Any]],
    after_name: str,
    *,
    name_key: str = "name",
    pred: Optional[Any] = None,
) -> list[Mapping[str, Any]]:
    """Items after the named record (the named record itself excluded)."""

    found = False
    out: list[Mapping[str, Any]] = []
    want = str(after_name or "")
    for record in records or ():
        if not found:
            if str(record.get(name_key) or "") == want:
                found = True
            continue
        if pred is None or pred(record):
            out.append(record)
    return out


def unique_keep(items: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for item in items or ():
        if item in out:
            continue
        out.append(item)
    return out


def merge_head_row(
    item: Mapping[str, Any],
    compiled: Mapping[str, Any],
    *,
    drop: Sequence[str] = ("tactics",),
    head: int = 240,
) -> dict[str, Any]:
    body = str(item.get("tactics") or "")
    payload = {
        **dict(item),
        **dict(compiled),
        "n_chars": len(body),
        "tactics_head": body[: max(0, int(head))],
    }
    for key in drop:
        payload.pop(key, None)
    return payload


def http_post(
    url: str,
    data: bytes,
    *,
    timeout: float,
    headers: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[int], str, str, str]:
    """POST bytes. Returns (status, body, final_url, error). Transport → error string."""

    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        str(url),
        data=data,
        method="POST",
        headers=dict(headers or {}),
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
            getter = getattr(response, "geturl", None)
            final = str(getter() if callable(getter) else url)
            return status, body, final, ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), detail, str(url), ""
    except Exception as exc:  # noqa: BLE001
        return None, "", str(url), f"{type(exc).__name__}: {exc}"


def xdg_runtime_dir(*, environ: Optional[Any] = None) -> Path:
    import os

    dest = os.environ if environ is None else environ
    raw = dest.get("XDG_RUNTIME_DIR")
    if raw and str(raw).strip():
        return Path(str(raw))
    return Path(f"/run/user/{os.getuid()}")


def try_import(name: str) -> Any:
    try:
        return __import__(name)
    except ImportError:
        return None


def dir_has_markers(path: Any, markers: Sequence[str]) -> bool:
    target = Path(path)
    if not target.is_dir():
        return False
    return any((target / str(marker)).exists() for marker in markers)


def run_process(
    argv: Sequence[str],
    *,
    cwd: Any = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
    error_cls: Optional[Any] = None,
    fail_fmt: str = "{stderr}",
) -> dict[str, Any]:
    import subprocess

    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd is not None else None,
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if env is not None:
        kwargs["env"] = {str(key): str(value) for key, value in env.items()}
    if timeout is not None:
        kwargs["timeout"] = float(timeout)
    try:
        completed = subprocess.run([str(item) for item in argv], **kwargs)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        result = {
            "ok": False,
            "exit_code": None,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "cwd": str(cwd) if cwd is not None else "",
            "timeout": True,
            "error": f"TimeoutExpired: {exc}",
            "pid": getattr(exc, "pid", None),
        }
        if error_cls is not None:
            raise error_cls(
                fail_fmt.format(stderr=result["error"], code="timeout")
            ) from exc
        return result
    if int(completed.returncode) != 0 and error_cls is not None:
        raise error_cls(
            fail_fmt.format(
                stderr=(completed.stderr or "").strip() or (completed.stdout or "").strip(),
                code=int(completed.returncode),
            )
        )
    return {
        "ok": int(completed.returncode) == 0,
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "cwd": str(cwd) if cwd is not None else "",
        "timeout": False,
        "error": "",
        "pid": None,
    }


def usage_tokens(usage: Mapping[str, Any], *, fallback_in: int = 0) -> tuple[int, int]:
    inn = int(usage.get("input_tokens") or usage.get("prompt_tokens") or fallback_in)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return inn, out


def chat_choice_texts(payload: Mapping[str, Any]) -> tuple[str, list[str], Mapping[str, Any]]:
    """OpenAI/Mistral-style choices[].message.content. Returns (first, all, usage)."""

    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    texts: list[str] = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}
        content = str(message.get("content") or "")
        if content:
            texts.append(content)
    message: Mapping[str, Any] = {}
    if choices and isinstance(choices[0], Mapping):
        raw = choices[0].get("message")
        message = raw if isinstance(raw, Mapping) else {}
    text = texts[0] if texts else str(message.get("content") or "")
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    return text, texts, usage


def integrity_conflict(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    needles = ("constraint", "unique", "duplicate", "primary key", "integrity")
    return any(item in name for item in needles) or any(item in text for item in needles)


def guard_sql(
    sql: str,
    *,
    allowed_head: Any,
    forbidden: Any,
    error_cls: Any = ValueError,
    empty: str = "empty SQL",
    forbidden_fmt: str = "forbidden mutating SQL: {sql}",
    outside_fmt: str = "SQL outside allowed: {sql}",
) -> str:
    text = str(sql or "").strip()
    if not text:
        raise error_cls(empty)
    if forbidden.search(text):
        raise error_cls(forbidden_fmt.format(sql=text[:120]))
    if not allowed_head.match(text):
        raise error_cls(outside_fmt.format(sql=text[:120]))
    return text


def contains_any(text: str, markers: Sequence[str]) -> bool:
    blob = str(text or "").casefold()
    return any(str(marker).casefold() in blob for marker in markers)


def replace_once(
    path: Any,
    original: str,
    replacement: str,
    *,
    error_cls: Any = ValueError,
    miss: str = "{path}: substring missing",
    encoding: str = "utf-8",
) -> None:
    target = Path(path)
    text = target.read_text(encoding=encoding)
    if original not in text:
        raise error_cls(miss.format(path=target))
    target.write_text(text.replace(original, replacement, 1), encoding=encoding)


def mapping_line_in_span(pos: Any, start_line: int, end_line: int) -> bool:
    if not isinstance(pos, Mapping):
        return False
    try:
        line = int(pos.get("line"))
    except (TypeError, ValueError):
        return False
    return int(start_line) <= line <= int(end_line)


def jsonl_pred_in_span(
    stdout: str,
    *,
    pred: Any,
    start_line: int,
    end_line: int,
) -> bool:
    for line in str(stdout or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not pred(payload):
            continue
        if mapping_line_in_span(payload.get("pos"), start_line, end_line):
            return True
    return False


def proc_exclusive_holder(
    path: Any,
    *,
    proc_locks: Any = "/proc/locks",
) -> tuple[Optional[bool], Optional[int], str]:
    """Parse /proc/locks for an exclusive FLOCK/WRITE holder of path. Query only."""

    ident = stat_dev_ino(path)
    if ident is None:
        return False, None, "missing"
    maj, minr, ino = ident
    tokens = (
        f"{maj:x}:{minr:x}:{ino}",
        f"{maj:02x}:{minr:02x}:{ino}",
        f"{maj:08x}:{minr:08x}:{ino}",
    )
    try:
        text = Path(proc_locks).read_text(encoding="utf-8")
    except OSError as exc:
        return None, None, f"proc_locks_unreadable: {exc}"
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        kind = parts[1].upper()
        mode = parts[3].upper() if len(parts) > 3 else ""
        if kind not in {"FLOCK", "POSIX", "OFDLCK"}:
            continue
        if mode not in {"WRITE", "EX", "WRLCK"}:
            continue
        if not any(token in parts[5] for token in tokens):
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            pid = None
        return True, pid, "proc_locks"
    return False, None, "proc_locks"


def shared_lock_busy(path: Any, *, error_cls: Any = OSError) -> tuple[bool, str]:
    """Non-blocking shared flock probe. True means an exclusive holder exists."""

    import fcntl
    import os

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise error_cls(f"cannot open lock file for shared probe: {exc}") from exc
    try:
        sh = int(getattr(fcntl, "LOCK_SH", 1))
        nb = int(getattr(fcntl, "LOCK_NB", 4))
        un = int(getattr(fcntl, "LOCK_UN", 8))
        try:
            fcntl.flock(fd, sh | nb)
        except BlockingIOError:
            return True, "shared_probe"
        except OSError as exc:
            if getattr(exc, "errno", None) in {11, 13}:
                return True, "shared_probe"
            raise
        fcntl.flock(fd, un)
        return False, "shared_probe"
    finally:
        os.close(fd)


def git_head(clone: Any) -> str:
    ran = run_process(["git", "-C", str(clone), "rev-parse", "HEAD"])
    if not ran.get("ok"):
        return ""
    return str(ran.get("stdout") or "").strip()


def require_basename(
    path: Any,
    name: str,
    *,
    error_cls: Any = ValueError,
    fmt: str = "expected {name}, got {path!r}",
) -> str:
    text = str(path or "")
    if not text or Path(text).name != str(name):
        raise error_cls(fmt.format(name=name, path=path))
    return text


def print_json(payload: Any, *, stream: Any = None, indent: int = 2) -> None:
    import sys

    dest = sys.stdout if stream is None else stream
    json.dump(payload, dest, indent=indent, sort_keys=True)
    dest.write("\n")


def with_fields(record: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    updated = dict(record)
    updated.update(fields)
    return updated


def with_field(record: Mapping[str, Any], key: str, value: Any) -> dict[str, Any]:
    return with_fields(record, **{key: value})


def join_under(root: Any, *parts: Any) -> Path:
    path = Path(root)
    for part in parts:
        path = path / str(part)
    return path


def plant_files(root: Any, files: Mapping[str, str], *, encoding: str = "utf-8") -> Path:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        path = dest / str(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding=encoding)
    return dest


def plant_git_skeleton(
    clone: Any,
    *,
    head: str = "ref: refs/heads/main\n",
    files: Optional[Mapping[str, str]] = None,
    encoding: str = "utf-8",
) -> Path:
    dest = Path(clone)
    dest.mkdir(parents=True, exist_ok=True)
    git_dir = dest / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(head, encoding=encoding)
    if files:
        plant_files(dest, files, encoding=encoding)
    return dest


def python_argv(
    *args: Any,
    python: Optional[str] = None,
    flags: Sequence[str] = ("-B",),
) -> list[str]:
    import sys

    py = python or sys.executable
    return [str(py), *[str(flag) for flag in flags], *[str(arg) for arg in args]]


def state_home_candidates(*, environ: Optional[Any] = None, home: Optional[Any] = None) -> list[Path]:
    import os

    dest = os.environ if environ is None else environ
    out: list[Path] = []
    raw = dest.get("XDG_STATE_HOME") if hasattr(dest, "get") else None
    if raw is not None and str(raw).strip():
        out.append(Path(str(raw).strip()))
    home_path = Path.home() if home is None else Path(home)
    out.append(home_path / ".local" / "state")
    out.append(home_path)
    return out


def exec_capable_dir(
    candidates: Sequence[Any],
    *,
    probe_name: str = ".exec-probe",
    probe_text: str = "#!/usr/bin/python3.12\nimport sys\nsys.exit(0)\n",
    check_fn: Optional[Any] = None,
    error_cls: Any = OSError,
    miss: str = "no executable filesystem",
) -> Path:
    import os

    checker = check_fn if check_fn is not None else (lambda path: os.system(str(path)) == 0)
    for base in candidates:
        try:
            root = Path(base)
            root.mkdir(parents=True, exist_ok=True)
            probe = root / str(probe_name)
            write_executable(probe, probe_text)
            ok = bool(checker(probe))
            probe.unlink(missing_ok=True)
            if ok:
                return root
        except OSError:
            continue
    raise error_cls(miss)


def inspect_lock(path: Any, *, error_cls: Any = OSError) -> dict[str, Any]:
    """Inspect a flock file without taking exclusive ownership."""

    lock_path = Path(path)
    if not lock_path.exists():
        return {
            "path": str(lock_path),
            "exists": False,
            "held": False,
            "pid": None,
            "method": "missing",
            "error": "",
        }
    held, pid, method = proc_exclusive_holder(lock_path)
    error = ""
    if held is None:
        error = method
        try:
            held, method = shared_lock_busy(lock_path, error_cls=error_cls)
            pid = None
        except Exception as exc:  # noqa: BLE001 — lock state must fail closed
            return {
                "path": str(lock_path),
                "exists": True,
                "held": True,
                "pid": None,
                "method": "error",
                "error": f"{error}; {type(exc).__name__}: {exc}",
            }
    elif held is False:
        try:
            sh_held, sh_method = shared_lock_busy(lock_path, error_cls=error_cls)
            if sh_held:
                held = True
                method = sh_method
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
    return {
        "path": str(lock_path),
        "exists": True,
        "held": bool(held),
        "pid": pid,
        "method": method,
        "error": error,
    }


def refuse_basename(
    path: Any,
    name: str,
    *,
    error_cls: Any = ValueError,
    fmt: str = "refusing {name}: {path!r}",
) -> str:
    text = str(path or "")
    if Path(text).name == str(name):
        raise error_cls(fmt.format(name=name, path=path))
    return text


def walk_suffix_files(root: Any, suffix: str) -> list[Path]:
    import os

    target = Path(root)
    if not target.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames.sort()
        for name in sorted(filenames):
            if name.endswith(suffix):
                found.append(Path(dirpath) / name)
    return found


def existing_files(candidates: Sequence[Any], *, exclude_names: Sequence[str] = ()) -> list[Path]:
    banned = {str(name) for name in exclude_names}
    out: list[Path] = []
    for cand in candidates:
        if cand is None:
            continue
        path = Path(cand)
        try:
            if path.is_file() and path.name not in banned:
                out.append(path)
        except OSError:
            continue
    return out


def write_blobs(root: Any, files: Mapping[str, bytes]) -> Path:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        path = dest / str(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return dest


def plant_executables(root: Any, files: Mapping[str, str], *, encoding: str = "utf-8") -> Path:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        write_executable(dest / str(name), text, encoding=encoding)
    return dest


def pinned_bin_paths(
    home: Any,
    dirname: str,
    names: Sequence[str],
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    home_path = Path(home)
    toolchain_dir = home_path / "toolchains" / str(dirname)
    bin_dir = toolchain_dir / "bin"
    paths = {str(name): bin_dir / str(name) for name in names}
    installed = {name: is_executable(path) for name, path in paths.items()}
    out: dict[str, Any] = {
        "elan_home": str(home_path),
        "toolchain_dir": str(toolchain_dir),
        "bin_dir": str(bin_dir),
        "executable_paths": {name: str(path) for name, path in paths.items()},
        "installed": all(installed.values()) if installed else False,
    }
    for name, path in paths.items():
        out[f"{name}_path"] = str(path)
        out[f"{name}_installed"] = installed[name]
    if extra:
        out.update(dict(extra))
    return out


def nonempty_file(path: Any) -> bool:
    target = Path(path)
    try:
        return target.is_file() and target.stat().st_size > 0
    except OSError:
        return False


def path_parts_status(
    path: Any,
    *,
    forbidden: Sequence[str] = (),
    all_markers: Sequence[str] = (),
    forbidden_reason: str = "forbidden_path",
    markers_reason: str = "marker_path",
    ok_reason: str = "ok",
) -> tuple[bool, str]:
    parts = [str(part).strip().lower() for part in Path(path).parts]
    banned = {str(item).strip().lower() for item in forbidden}
    if any(part in banned for part in parts):
        return False, forbidden_reason
    markers = [str(item).strip().lower() for item in all_markers]
    if markers and all(marker in parts for marker in markers):
        return False, markers_reason
    return True, ok_reason


def first_json_dict(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    candidates = [raw, *reversed([line.strip() for line in raw.splitlines() if line.strip()])]
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def http_ok(
    status: Optional[int],
    error: str = "",
    *,
    max_status: int = 500,
) -> tuple[bool, str]:
    ok = status is not None and int(status) < int(max_status)
    detail = str(error or "")
    if not ok and not detail and status is not None:
        detail = f"HTTP {status}"
    return ok, detail


def name_fallback_used(
    resolved: str,
    *,
    allowed: Sequence[str],
    forbidden: Sequence[str] = (),
) -> bool:
    text = str(resolved or "").strip().lower()
    if not text:
        return False
    allowed_set = {str(item).strip().lower() for item in allowed}
    forbidden_set = {str(item).strip().lower() for item in forbidden}
    return text not in allowed_set or text in forbidden_set


def write_text(
    path: Any,
    text: str,
    *,
    encoding: str = "utf-8",
    refuse: Optional[str] = None,
    error_cls: Any = ValueError,
    refuse_fmt: str = "refusing {name}: {path!r}",
) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if refuse:
        refuse_basename(dest, refuse, error_cls=error_cls, fmt=refuse_fmt)
    dest.write_text(str(text), encoding=encoding)
    return dest


def state_root_from_env(
    *,
    override_key: str,
    relative: Any,
    environ: Optional[Any] = None,
    home: Optional[Any] = None,
) -> Path:
    import os

    dest = os.environ if environ is None else environ
    raw = dest.get(override_key) if hasattr(dest, "get") else None
    if raw is not None and str(raw).strip():
        return Path(str(raw).strip())
    homes = state_home_candidates(environ=dest, home=home)
    rel = Path(relative)
    if homes:
        return homes[0] / rel
    return Path.home() / ".local" / "state" / rel


def mkdtemp_under(
    parent: Any,
    *,
    prefix: str = "tmp-",
    files: Optional[Mapping[str, str]] = None,
) -> Path:
    import tempfile

    root = Path(parent)
    root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix=str(prefix), dir=str(root)))
    if files:
        plant_files(dest, files)
    return dest


def timed_call(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, float, float]:
    """Run fn and return (result, wall_ms, child_cpu_ms)."""

    import resource
    import time

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    result = fn(*args, **kwargs)
    wall_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = max(
        0.0,
        ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1000.0,
    )
    return result, wall_ms, cpu_ms


def process_exit_code(result: Any, *, timeout_code: int = 124) -> tuple[int, bool]:
    timed_out = bool(getattr(result, "timed_out", False))
    if isinstance(result, Mapping):
        timed_out = timed_out or bool(result.get("timeout") or result.get("timed_out"))
    error = getattr(result, "error", None)
    if not error and isinstance(result, Mapping):
        error = result.get("error") or None
    returncode = getattr(result, "returncode", None)
    if returncode is None and isinstance(result, Mapping):
        returncode = result.get("exit_code")
    if timed_out:
        return int(timeout_code), True
    if error:
        return (1 if returncode in (None, 0) else int(returncode)), False
    if returncode is None:
        return 0, False
    return int(returncode), False


def write_named_jsons(
    dest_dir: Any,
    rows: Sequence[Any],
    *,
    name_fn: Any,
    tag_fn: Any,
    payload_fn: Any,
    empty: str = "unnamed",
) -> list[str]:
    dest = Path(dest_dir)
    written: list[str] = []
    for row in rows:
        name = str(name_fn(row) or "").replace("/", "_") or empty
        tag = str(tag_fn(row))
        path = write_json(dest / name / f"{tag}.json", payload_fn(row))
        written.append(str(path))
    return written


def which_bin(name: str, *, default: str = "") -> str:
    import shutil

    return shutil.which(str(name)) or str(default)


def any_search(texts: Sequence[Any], pattern: Any) -> bool:
    search = getattr(pattern, "search", None)
    if search is None:
        return False
    return any(bool(search(str(text or ""))) for text in texts)


def glob_after(root: Any, pattern: str, *, first: Optional[Any] = None) -> list[Path]:
    dest = Path(root)
    out: list[Path] = []
    if first is not None:
        head = Path(first)
        try:
            if head.is_file():
                out.append(head)
        except OSError:
            pass
    try:
        extra = sorted(dest.glob(str(pattern)))
    except OSError:
        extra = []
    for path in extra:
        if path not in out:
            out.append(path)
    return out


def first_file_text(
    paths: Sequence[Any],
    *,
    drop_substr: str = "",
    reject_fn: Optional[Any] = None,
    error_cls: Any = FileNotFoundError,
    miss: str = "no matching file",
) -> str:
    for path in paths:
        target = Path(path)
        try:
            if not target.is_file():
                continue
            raw = target.read_text(encoding="utf-8")
        except OSError:
            continue
        if drop_substr:
            lines = [line for line in raw.splitlines() if drop_substr not in line]
            body = "\n".join(lines).strip()
        else:
            body = raw.strip()
        if not body:
            continue
        if reject_fn is not None and reject_fn(body):
            continue
        return body + "\n"
    raise error_cls(miss)


def is_stub_text(
    text: str,
    *,
    marker: str = "",
    max_words: int = 12,
    exact: str = "",
) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    if marker and marker in stripped and len(stripped.split()) < int(max_words):
        return True
    if exact and stripped == str(exact).strip():
        return True
    return False


def collect_until(
    items: Sequence[Any],
    fn: Any,
    *,
    abort_fn: Optional[Any] = None,
    remaining_fn: Optional[Any] = None,
    remaining_attr: str = "",
) -> list[Any]:
    """Map items through fn; stop after abort_fn(result). Optional remaining list."""

    out: list[Any] = []
    rest = list(items)
    for item in items or ():
        rest = rest[1:]
        result = fn(item)
        if remaining_attr and abort_fn is not None and abort_fn(result):
            leftover = remaining_fn(rest) if remaining_fn is not None else list(rest)
            try:
                setattr(result, remaining_attr, leftover)
            except Exception:
                if isinstance(result, dict):
                    result[remaining_attr] = leftover
        out.append(result)
        if abort_fn is not None and abort_fn(result):
            break
    return out


def first_or_last(
    items: Sequence[Any],
    pred: Any,
    *,
    error_cls: Any = ValueError,
    miss: str = "empty",
) -> Any:
    rows = list(items or ())
    for item in rows:
        if pred(item):
            return item
    if rows:
        return rows[-1]
    raise error_cls(miss)


def require_exact_keys(
    mapping: Any,
    keys: Sequence[str],
    *,
    error_cls: Any = ValueError,
    not_map: str = "must be a mapping",
    extra_fmt: str = "unexpected keys {keys}",
    miss_fmt: str = "missing keys {keys}",
    empty_fmt: str = "empty {key}",
) -> dict[str, str]:
    if not isinstance(mapping, Mapping):
        raise error_cls(not_map)
    got = {str(key): str(value) for key, value in mapping.items()}
    expected = [str(key) for key in keys]
    extra = sorted(set(got) - set(expected))
    if extra:
        raise error_cls(extra_fmt.format(keys=extra))
    missing = sorted(set(expected) - set(got))
    if missing:
        raise error_cls(miss_fmt.format(keys=missing))
    out: dict[str, str] = {}
    for key in expected:
        text = got[key].strip()
        if not text:
            raise error_cls(empty_fmt.format(key=key))
        out[key] = text
    return out


def reject_present_keys(
    mapping: Mapping[str, Any],
    keys: Sequence[str],
    *,
    error_cls: Any = ValueError,
    fmt: str = "forbidden field {key!r}",
    empty: Any = (None, "", []),
) -> None:
    for key in keys:
        if key in mapping and mapping[key] not in empty:
            raise error_cls(fmt.format(key=key))


def quoted_strings(text: str, *, pattern: str = r'"([a-z_]+)"') -> tuple[str, ...]:
    return tuple(re.findall(str(pattern), str(text or "")))


def is_hex_digest(text: str, *, n: int = 64) -> bool:
    blob = str(text or "")
    return bool(re.fullmatch(r"[0-9a-f]{" + str(int(n)) + r"}", blob))


def pin_env(
    pairs: Mapping[str, str],
    *,
    environ: Optional[Any] = None,
    overwrite: bool = True,
) -> None:
    import os

    dest = os.environ if environ is None else environ
    for key, value in dict(pairs).items():
        name = str(key)
        if overwrite or not dest.get(name):
            dest[name] = str(value)


def require_env_eq(
    key: str,
    expected: str,
    *,
    environ: Optional[Any] = None,
    error_cls: Any = ValueError,
    fmt: str = "{key} must be {expected}",
) -> str:
    import os

    dest = os.environ if environ is None else environ
    got = dest.get(key)
    if str(got) != str(expected):
        raise error_cls(fmt.format(key=key, expected=expected, got=got))
    return str(got)


def argv_layout(
    argv: Sequence[Any],
    *,
    min_len: int = 0,
    names: Optional[Mapping[int, str]] = None,
    eq: Optional[Mapping[int, str]] = None,
    contains: Optional[Mapping[int, str]] = None,
) -> bool:
    rows = [str(item) for item in argv or ()]
    if len(rows) < int(min_len):
        return False
    for index, name in dict(names or {}).items():
        if int(index) >= len(rows) or Path(rows[int(index)]).name != str(name):
            return False
    for index, value in dict(eq or {}).items():
        if int(index) >= len(rows) or rows[int(index)] != str(value):
            return False
    for index, needle in dict(contains or {}).items():
        if int(index) >= len(rows) or str(needle) not in rows[int(index)]:
            return False
    return True


def token_family(
    opener: str,
    *,
    prefixes: Sequence[str] = (),
    aliases: Optional[Mapping[str, str]] = None,
    trail: str = "!'",
) -> str:
    parts = str(opener or "").split()
    token = parts[0].rstrip(trail) if parts else ""
    for prefix in prefixes:
        if token.startswith(str(prefix)):
            return str(prefix)
    return str(dict(aliases or {}).get(token, token))


def row_dict(row: Any, keys: Sequence[str]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for index, key in enumerate(keys):
        try:
            out[str(key)] = row[index]
        except Exception:
            out[str(key)] = None
    return out


def row_cell(row: Any, index: int = 0, *, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        value = row[int(index)]
    except Exception:
        return default
    return default if value is None else value


def path_refused(
    path: Any,
    *,
    names: Sequence[str] = (),
    needles: Sequence[str] = (),
) -> bool:
    dest = Path(path)
    text = str(dest)
    if dest.name in {str(name) for name in names}:
        return True
    return any(str(needle) in text for needle in needles)


def without_prefix(text: str, prefix: str) -> str:
    raw = str(text or "")
    if prefix and raw.startswith(prefix):
        return raw[len(prefix) :]
    return raw


def cut_prefix(text: str, end: int, *, suffix: str = "\n") -> str:
    return str(text or "")[: int(end)].rstrip() + str(suffix)


def dumps_compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def digest_compact(value: Any) -> str:
    return digest_hex(dumps_compact(value).encode("utf-8"))


def connect_engine(path: Any, *, duckdb_module: Any = None) -> tuple[Any, str]:
    import sqlite3

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    module = duckdb_module if duckdb_module is not None else try_import("duckdb")
    if module is not None:
        return module.connect(str(dest)), "duckdb"
    return sqlite3.connect(str(dest)), "sqlite3"


def env_str(key: str, default: str = "", *, environ: Optional[Any] = None) -> str:
    import os

    dest = os.environ if environ is None else environ
    raw = dest.get(key) if hasattr(dest, "get") else None
    return str(raw if raw not in (None, "") else default)


def env_int(
    key: str,
    default: Any,
    *,
    minimum: Optional[int] = None,
    environ: Optional[Any] = None,
) -> int:
    value = int(env_str(key, str(default), environ=environ) or int(default))
    if minimum is not None:
        value = max(int(minimum), value)
    return value


def partition(items: Sequence[Any], pred: Any) -> tuple[list[Any], list[Any]]:
    yes: list[Any] = []
    no: list[Any] = []
    for item in items or ():
        (yes if pred(item) else no).append(item)
    return yes, no


def map_partition(items: Sequence[Any], pred: Any, fn: Any) -> tuple[list[Any], list[Any]]:
    yes, no = partition(items, pred)
    return [fn(item) for item in yes], [fn(item) for item in no]


def first_matching_line(text: str, pred: Any) -> Optional[str]:
    for line in str(text or "").splitlines():
        if pred(line):
            return line
    return None


def first_token(text: str) -> str:
    parts = str(text or "").split()
    return parts[0] if parts else ""


def result_usage(result: Any, *, fallback_in: int = 0) -> tuple[int, int]:
    usage = getattr(result, "usage", None)
    if not isinstance(usage, Mapping):
        usage = {}
    return usage_tokens(usage, fallback_in=int(fallback_in))


def attr_map(
    container: Any,
    names: Sequence[str],
    attr: str,
    *,
    default: Any = 0.0,
    cast: Any = float,
) -> dict[str, Any]:
    row = container if isinstance(container, Mapping) else {}
    out: dict[str, Any] = {}
    for name in names:
        item = row.get(name)
        value = getattr(item, attr, default) if item is not None else default
        out[str(name)] = cast(value or default)
    return out


def client_kwargs(
    module: Any,
    *,
    timeout: float = 45.0,
    max_retries: int = 5,
    backoff_max: float = 20.0,
    retry_statuses: Sequence[int] = (429, 503, 529),
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": float(timeout)}
    policy_cls = getattr(module, "RetryPolicy", None)
    if policy_cls is None:
        return kwargs
    try:
        kwargs["retry"] = policy_cls(
            max_retries=int(max_retries),
            backoff_max=float(backoff_max),
            timeout=float(timeout),
            retry_statuses=tuple(retry_statuses),
        )
    except TypeError:
        kwargs["retry"] = policy_cls(
            max_retries=int(max_retries),
            backoff_max=float(backoff_max),
            timeout=float(timeout),
        )
    return kwargs


def load_configured(path: Any, spec: str, *, configured: str = "typesafe_configured") -> Any:
    module = load_module_from_path(path, spec)
    if module is None:
        return None
    fn = getattr(module, configured, None)
    if callable(fn) and not fn():
        return None
    return module


def unique_kind_bodies(
    items: Sequence[Mapping[str, Any]],
    *,
    kind_key: str = "kind",
    body_key: str = "tactics",
    keep: Optional[Mapping[str, str]] = None,
    skip_eq: str = "",
) -> dict[str, str]:
    found = dict(keep or {})
    skip = str(skip_eq).strip("\n")
    for item in items or ():
        kind = str(item.get(kind_key) or "")
        body = str(item.get(body_key) or "").strip("\n")
        if kind and body and body != skip:
            found[kind] = body
    return found


def field_of(item: Any, *names: str, default: Any = "") -> Any:
    """First nonempty mapping key or attribute among names."""

    for name in names:
        value = None
        if isinstance(item, Mapping) and name in item:
            value = item.get(name)
        elif item is not None and hasattr(item, name):
            value = getattr(item, name, None)
        if value not in (None, ""):
            return value
    return default


def filter_map(
    items: Sequence[Any],
    *,
    pred: Any = None,
    map_fn: Any = None,
    skip_exc: Any = (),
) -> list[Any]:
    """Keep items where pred is true, optionally map. pred exceptions in skip_exc skip."""

    out: list[Any] = []
    errors = skip_exc if skip_exc else ()
    for item in items or ():
        try:
            if pred is not None and not pred(item):
                continue
        except errors:
            continue
        out.append(map_fn(item) if map_fn is not None else item)
    return out


def first_table_sql(tables: Any, mapping: Mapping[str, str]) -> Optional[str]:
    """First SQL whose table name is in the SHOW TABLES set (casefold)."""

    bag = {str(name).casefold() for name in tables or ()}
    for name, sql in dict(mapping or {}).items():
        if str(name).casefold() in bag:
            return str(sql)
    return None


def engine_tables(con: Any, *, sql: str = "SHOW TABLES") -> set[str]:
    try:
        return {str(row[0]).casefold() for row in con.execute(sql).fetchall() if row and row[0]}
    except Exception:
        return set()


def open_readonly(
    path: Any,
    *,
    refuse_names: Sequence[str] = (),
    engine_module: Any = None,
) -> tuple[Any, str]:
    """Open DuckDB (if present) read-only. Does not mkdir. Campaign names can be refused."""

    dest = Path(path)
    if path_refused(dest, names=refuse_names):
        return None, "refused"
    if not dest.is_file():
        return None, "missing"
    module = engine_module if engine_module is not None else try_import("duckdb")
    if module is None:
        return None, "unavailable"
    try:
        try:
            return module.connect(str(dest), read_only=True), "ok"
        except TypeError:
            return module.connect(str(dest)), "ok"
    except Exception:
        return None, "connect_failed"


def query_engine(
    path: Any,
    sql: str,
    params: Sequence[Any] = (),
    *,
    refuse_names: Sequence[str] = (),
    read_only: bool = True,
    row_fn: Any = None,
    engine_module: Any = None,
) -> list[Any]:
    """Optional DuckDB SELECT. Missing/refused/unavailable → []. Never campaign writes."""

    dest = Path(path)
    if not read_only:
        con, note = None, "write_unsupported"
        module = engine_module if engine_module is not None else try_import("duckdb")
        if module is None or path_refused(dest, names=refuse_names):
            return []
        try:
            con = module.connect(str(dest))
            note = "ok"
        except Exception:
            return []
    else:
        con, note = open_readonly(dest, refuse_names=refuse_names, engine_module=engine_module)
    if con is None or note not in {"ok"}:
        return []
    try:
        try:
            rows = con.execute(str(sql), list(params)).fetchall()
        except Exception:
            return []
    finally:
        try:
            con.close()
        except Exception:
            pass
    out: list[Any] = []
    for row in rows or ():
        mapped = row_fn(row) if row_fn is not None else row
        if mapped is not None:
            out.append(mapped)
    return out


def insert_ignore_conflict(
    fn: Any,
    *args: Any,
    error_cls: Any = ValueError,
    fail_fmt: str = "INSERT failed: {exc}",
    **kwargs: Any,
) -> bool:
    """Run fn; unique/integrity conflicts return False. Other errors raise error_cls."""

    try:
        fn(*args, **kwargs)
        return True
    except Exception as exc:
        if integrity_conflict(exc):
            return False
        raise error_cls(fail_fmt.format(exc=exc)) from exc


def fetch_mapped(result: Any, row_fn: Any) -> list[Any]:
    """Map fetchall/iterable rows. row_fn returning None is dropped."""

    if result is None:
        rows: Sequence[Any] = ()
    elif hasattr(result, "fetchall"):
        rows = result.fetchall()
    else:
        rows = list(result)
    out: list[Any] = []
    for row in rows or ():
        mapped = row_fn(row)
        if mapped is not None:
            out.append(mapped)
    return out
