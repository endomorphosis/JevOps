#!/usr/bin/env python3
"""Order and try candidate drafts against an implementation oracle.

The oracle (lake, tests, …) is injected. Cache hits never admit.
Jev does not write Lean.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence


def closed(reason: str, name: Any, **extra: Any) -> dict[str, Any]:
    """Fail-closed oracle payload. Never a lake admit."""

    out = {"ok": False, "reason": str(reason), "name": name, "theorem_ok": False}
    out.update(extra)
    return out


def require_named(
    records: Sequence[Mapping[str, Any]],
    name: str,
    *,
    cap: Optional[int] = None,
    token_key: str = "n_tokens",
) -> tuple[Optional[Mapping[str, Any]], Optional[dict[str, Any]]]:
    """Lookup a named record. Fail closed if missing or over cap."""

    from jevops.outer import lookup_named

    match = lookup_named(records, name)
    if not match:
        return None, closed("not_small_or_unknown", name)
    n_tok = int(match.get(token_key) or 0)
    if cap is not None and n_tok > int(cap):
        return None, closed("not_small_or_unknown", name, tokens=n_tok)
    return match, None


def lake_budget(n_tokens: Any, *, cap: int, top: int = 3) -> tuple[bool, int]:
    """too_big scripts get a 1-slot budget; else lake_top."""

    too_big = int(n_tokens or 0) > int(cap)
    return too_big, (1 if too_big else max(1, int(top or 3)))


def preferred_kinds(memory: Mapping[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in memory.get("successes") or []:
        kind = str(item.get("kind") or "").split("#")[0]
        if kind and kind not in seen:
            seen.add(kind)
            out.append(kind)
    return out


def order_kinds(
    *,
    drafts: Sequence[Mapping[str, Any]],
    intent: Mapping[str, Any],
    ranked: Mapping[str, Any],
    preferred: Optional[Sequence[str]] = None,
    too_big: bool = False,
    too_big_kinds: Sequence[str] = ("collapse_rw", "drop_unused_binders", "collapse_simp_at"),
) -> list[str]:
    """Stable candidate order: pipeline, skill, beam, memory wins, then leftover."""

    order: list[str] = []
    skill = str(intent.get("skill") or "")
    if intent.get("compose") == "pipeline":
        order.extend(
            str(item["kind"])
            for item in drafts
            if str(item.get("kind") or "").startswith("port_pipeline")
        )
    if skill and skill not in {"keep", "None"}:
        order.append(skill)
    order.extend(list(ranked.get("beam_kinds") or []))
    order.extend(list(preferred or []))
    if ranked.get("best_draft"):
        order.append(str(ranked.get("best_draft")))
    if too_big:
        order = [
            kind
            for kind in too_big_kinds
            if any(item.get("kind") == kind for item in drafts)
        ] + [str(ranked.get("best_draft") or "")]
    order.extend(str(item.get("kind") or "") for item in drafts if item.get("kind"))
    return [k for k in order if k]


def noul_fire_all(ranked: Mapping[str, Any], by_kind: Mapping[str, Any]) -> bool:
    fired_skip = set(ranked.get("fired_leaves") or [])
    # A closed compiler probe must still receive one Lake verdict.  Noul is a
    # soft routing prior; treating every probe as fired can make a stale
    # residual prediction suppress the entire proof search.
    unfired = [
        kind
        for kind, item in by_kind.items()
        if kind not in fired_skip or bool(item.get("compiler_probe"))
    ]
    return bool(ranked.get("fired") and not unfired)


def try_kind(
    memory: Optional[dict[str, Any]],
    *,
    name: Any,
    kind: str,
    tactics: str,
    compile_fn: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Single-flight + negative TTL around one oracle call."""

    from jevops import kernel as lra_kern

    return dict(
        lra_kern.guarded_compile(
            memory if isinstance(memory, dict) else None,
            name=name,
            kind=kind,
            tactics=tactics,
            compile_fn=compile_fn,
        )
    )


def pack_eval(compiled: Mapping[str, Any], *, name: Any, tactics: str) -> dict[str, Any]:
    """Closed oracle payload. Cache skips never admit."""

    skipped = str(compiled.get("skipped") or compiled.get("reason") or "")
    if skipped in {"negative_ttl", "in_flight"}:
        return {
            "ok": False,
            "name": name,
            "theorem_ok": False,
            "tactics": tactics,
            "energy": 0.25,
            "reason": skipped,
            "skipped": skipped,
        }
    ok = bool(compiled.get("theorem_ok"))
    return {
        "ok": ok,
        "name": name,
        "theorem_ok": ok,
        "tokens": compiled.get("token_count"),
        "tactics": tactics,
        "energy": 0.75 if ok else 0.25,
        "reason": None if ok else "lake_failed",
    }


def eval_named_or_current(
    name: str,
    *,
    current: Mapping[str, Any],
    tactics: str,
    compile_fn: Callable[..., Mapping[str, Any]],
    memory: Optional[dict[str, Any]] = None,
    timeout: float = 180.0,
    load_records_fn: Optional[Callable[[], Sequence[Mapping[str, Any]]]] = None,
    tactic_block_fn: Optional[Callable[[Mapping[str, Any]], str]] = None,
    clone_dir_fn: Optional[Callable[[str], Any]] = None,
    relpath_fn: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    read_bytes_fn: Optional[Callable[..., Any]] = None,
    cap: Optional[int] = None,
    state_root: Any = None,
    restore: bytes = b"",
) -> dict[str, Any]:
    """Lake the current theorem, or a named warmup clone when names differ."""

    from pathlib import Path

    if compile_fn is None:
        return closed("no_compile_fn", name)
    target = str(name or current.get("name") or "")
    rec: Mapping[str, Any] = current
    body = tactics
    restore_bytes = restore
    if target and target != str(current.get("name") or ""):
        if load_records_fn is None:
            return closed("warmup_unreadable", target)
        try:
            records = list(load_records_fn() or [])
        except Exception:
            return closed("warmup_unreadable", target)
        match, fail = require_named(records, target, cap=cap)
        if fail:
            return fail
        rec = match
        body = tactic_block_fn(match) if tactic_block_fn is not None else str(match.get("src") or "")
        if clone_dir_fn is None or relpath_fn is None:
            return closed("no_clone", target)
        dest = Path(clone_dir_fn(str(match.get("url") or ""))) / relpath_fn(match)
        if read_bytes_fn is not None:
            restore_bytes = read_bytes_fn(dest)
        if not dest.is_file():
            return closed("no_clone", target)

    def _compile() -> Mapping[str, Any]:
        return compile_fn(
            rec,
            body,
            state_root=state_root,
            timeout=timeout,
            restore=restore_bytes,
        )

    compiled = try_kind(
        memory if isinstance(memory, dict) else None,
        name=rec.get("name"),
        kind="eval_theorem",
        tactics=body,
        compile_fn=_compile,
    )
    return pack_eval(compiled, name=rec.get("name"), tactics=body)


def apply_round(
    *,
    memory: Optional[dict[str, Any]],
    name: Any,
    drafts: Sequence[Mapping[str, Any]],
    intent: Mapping[str, Any],
    ranked: Mapping[str, Any],
    round_i: int = 0,
    budget: int = 3,
    compile_fn: Callable[[str, str], Mapping[str, Any]],
    repair_fn: Optional[Callable[..., Optional[str]]] = None,
    error_class_fn: Optional[Callable[[Sequence[Any]], Optional[str]]] = None,
    on_ok: Optional[Callable[..., None]] = None,
    on_fail: Optional[Callable[..., None]] = None,
    from_tokens: int = 10**9,
    too_big: bool = False,
    preferred: Optional[Sequence[str]] = None,
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Try ordered drafts against the injected oracle. Cache hits never admit."""

    from jevops import kernel as lra_kern

    lake: list[dict[str, Any]] = []
    wins = list(preferred) if preferred is not None else preferred_kinds(memory or {})
    order = order_kinds(
        drafts=drafts,
        intent=intent,
        ranked=ranked,
        preferred=wins,
        too_big=too_big,
    )
    by_kind = {item["kind"]: item for item in drafts if "tactics" in item}
    fired_skip = set(ranked.get("fired_leaves") or [])
    unfired = [
        kind
        for kind, item in by_kind.items()
        if kind not in fired_skip or bool(item.get("compiler_probe"))
    ]
    if noul_fire_all(ranked, by_kind):
        lake.append(
            {
                "name": name,
                "round": round_i,
                "skipped": "noul_fire_all",
                "fired_leaves": sorted(fired_skip),
            }
        )
        return None, lake
    tried = 0
    seen: set[str] = set()
    accepted_body: Optional[str] = None
    accepted_tok = int(from_tokens)
    tree_node = intent.get("tree_node")
    if isinstance(memory, dict):
        lra_kern.bump_tick(memory)
        lra_kern.sweep_negative(memory)
    for kind in order:
        if kind in seen or kind not in by_kind:
            continue
        if kind in fired_skip and unfired and not bool(by_kind[kind].get("compiler_probe")):
            continue
        seen.add(str(kind))
        body = str(by_kind[kind]["tactics"])
        compiled = dict(
            try_kind(
                memory,
                name=name,
                kind=kind,
                tactics=body,
                compile_fn=lambda script=body, k=kind: compile_fn(k, script),
            )
        )
        skipped = str(compiled.get("skipped") or "")
        if skipped:
            lake.append(
                {
                    "name": name,
                    "round": round_i,
                    "kind": kind,
                    "skipped": skipped,
                    "ok": False,
                }
            )
            continue
        from jevops.outer import head_seq

        err = None
        if not compiled.get("theorem_ok") and error_class_fn is not None:
            err = error_class_fn(compiled.get("errors") or [])
        row: dict[str, Any] = {
            "name": name,
            "round": round_i,
            "kind": kind,
            "ok": bool(compiled.get("theorem_ok")),
            "tokens": compiled.get("token_count"),
            "repaired": False,
            "error_class": err,
            "errors": head_seq(compiled.get("errors"), 1),
            "depth": tree_node,
        }
        if not row["ok"] and repair_fn is not None:
            repaired_body = repair_fn(kind=kind, tactics=body, compiled=compiled, row=row)
            if repaired_body and str(repaired_body).strip("\n") != body.strip("\n"):
                repaired = dict(
                    try_kind(
                        memory,
                        name=name,
                        kind=f"{kind}#repair",
                        tactics=str(repaired_body),
                        compile_fn=lambda script=repaired_body, k=kind: compile_fn(f"{k}#repair", script),
                    )
                )
                err = None
                if not repaired.get("theorem_ok") and error_class_fn is not None:
                    err = error_class_fn(repaired.get("errors") or [])
                row = {
                    "name": name,
                    "round": round_i,
                    "kind": f"{kind}#repair",
                    "ok": bool(repaired.get("theorem_ok")),
                    "tokens": repaired.get("token_count"),
                    "repaired": True,
                    "error_class": err,
                    "errors": head_seq(repaired.get("errors"), 1),
                    "depth": tree_node,
                }
                if row["ok"]:
                    by_kind[kind]["tactics"] = repaired_body
        lake.append(row)
        if row["ok"]:
            better = int(row["tokens"] or 10**9) < accepted_tok
            if better:
                accepted_tok = int(row["tokens"])
                accepted_body = str(by_kind[kind].get("tactics") or "")
            if on_ok is not None:
                on_ok(row, str(by_kind[kind].get("tactics") or body), by_kind[kind], better=better)
        elif on_fail is not None:
            on_fail(
                row,
                str(by_kind[kind].get("tactics") or body),
                by_kind[kind],
                compiled=compiled,
                kind=kind,
            )
        tried += 1
        if tried >= max(1, int(budget)):
            break
    return accepted_body, lake
