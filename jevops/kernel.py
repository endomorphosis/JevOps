#!/usr/bin/env python3
"""TypeSafe/JevOps kernel: cache tiers, CID put/get, negative TTL, single-flight, budget.

Tiers:
  L0  tape / DT window (working set; not a proof cache)
  L1  process dict ``nca.kernel.l1``
  L2  host files under JEVOPS_CAS_DIR (optional)
  L3  optional JSON-LD→DuckDB adapter (never control.duckdb)

A cache hit never becomes lake-ok. Jev does not write Lean. Never docker0.
Implementations (LRA, other papers) live outside this package.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Optional

def cas_dir() -> Path:
    override = os.environ.get("JEVOPS_CAS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "jevops" / "cas"


CAS_DIR = cas_dir()  # snapshot; inflight/L2 helpers call cas_dir()
NEGATIVE_TTL_TICKS = 32
MAX_CELLS = 12
MAX_BYTES = 65536
L1_CAP = 32
L1_MAX_BYTES = 262144
L2_MAX_FILES = 128
INFLIGHT_TTL_S = 180
KERNEL_STEMS = (
    "cache_put",
    "cache_get",
    "cache_lru",
    "cache_arc",
    "negative_ttl",
    "singleflight",
    "single_flight",
    "context_budget",
    "nca_kernel",
)


def is_kernel_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    return any(tag in text for tag in KERNEL_STEMS)


def _kernel(memory: dict[str, Any]) -> dict[str, Any]:
    k = memory.setdefault("nca", {}).setdefault("kernel", {})
    k.setdefault("l1", {})
    k.setdefault("negative", {})
    k.setdefault("in_flight", [])
    k.setdefault("tick", 0)
    k.setdefault("policy", "arc")
    k.setdefault("l1_cap", L1_CAP)
    k.setdefault(
        "arc",
        {"t1": [], "t2": [], "b1": [], "b2": [], "p": 0},
    )
    k.setdefault("lru", [])
    k.setdefault("l1_max_bytes", L1_MAX_BYTES)
    k.setdefault(
        "stats",
        {"hits": 0, "misses": 0, "evicts": 0, "negative_hits": 0, "flights": 0, "integrity_miss": 0},
    )
    k.setdefault("budget", {"max_cells": MAX_CELLS, "max_bytes": MAX_BYTES, "max_depth": 3})
    return k


def _stat(k: dict[str, Any], name: str, n: int = 1) -> None:
    stats = k.setdefault("stats", {})
    stats[name] = int(stats.get(name) or 0) + int(n)


def lake_key(name: Any, kind: Any, tactics: str) -> str:
    return content_cid({"name": str(name or ""), "kind": str(kind or ""), "tactics": str(tactics or "")})


def _l1_store_key(ns: str, cid: str) -> str:
    ns = str(ns or "draft")
    if ns not in {"draft", "jev", "graph", "context"}:
        ns = "draft"
    return f"{ns}/{cid}"


def _verify_cid(entry: Mapping[str, Any], cid: str) -> bool:
    expect = content_cid({"kind": entry.get("kind"), "body": entry.get("body")})
    stored = str(entry.get("cid") or "")
    return stored == cid and expect == cid


def _l1_bytes(l1: Mapping[str, Any]) -> int:
    try:
        return len(json.dumps(l1, default=str, separators=(",", ":")))
    except Exception:
        return 0


def gc_l2(*, max_files: int = L2_MAX_FILES) -> int:
    dest = cas_dir()
    if not dest.is_dir():
        return 0
    files = sorted(dest.glob("sha256_*.json"), key=lambda p: p.stat().st_mtime)
    drop = len(files) - max(1, int(max_files))
    n = 0
    for path in files[: max(0, drop)]:
        try:
            path.unlink()
            n += 1
        except OSError:
            pass
    return n


def content_cid(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def set_policy(memory: dict[str, Any], policy: str) -> dict[str, Any]:
    k = _kernel(memory)
    name = "arc" if str(policy or "").lower() == "arc" else "lru"
    k["policy"] = name
    return {"ok": True, "kind": "port_cache_arc" if name == "arc" else "port_cache_lru", "policy": name, "admit": False}


def _move_mru(seq: list[str], cid: str) -> list[str]:
    out = [x for x in seq if x != cid]
    out.append(cid)
    return out


def _lru_evict(k: dict[str, Any], cid: str, *, hit: bool) -> None:
    cap = max(1, int(k.get("l1_cap") or L1_CAP))
    order = [x for x in (k.get("lru") or []) if x != cid]
    if hit or cid in (k.get("l1") or {}):
        order.append(cid)
    k["lru"] = order
    l1 = dict(k.get("l1") or {})
    while (len(l1) > cap or _l1_bytes(l1) > int(k.get("l1_max_bytes") or L1_MAX_BYTES)) and order:
        victim = order.pop(0)
        if victim in l1:
            l1.pop(victim, None)
            _stat(k, "evicts")
    k["lru"] = [x for x in order if x in l1]
    k["l1"] = l1


def _arc_replace(k: dict[str, Any], *, in_b2: bool) -> None:
    cap = max(1, int(k.get("l1_cap") or L1_CAP))
    arc = dict(k.get("arc") or {})
    t1 = list(arc.get("t1") or [])
    t2 = list(arc.get("t2") or [])
    b1 = list(arc.get("b1") or [])
    b2 = list(arc.get("b2") or [])
    p = int(arc.get("p") or 0)
    l1 = dict(k.get("l1") or {})
    if t1 and (len(t1) > p or (in_b2 and len(t1) == p)):
        victim = t1.pop(0)
        if victim in l1:
            l1.pop(victim, None)
            _stat(k, "evicts")
        b1 = _move_mru(b1, victim)
        if len(b1) > cap:
            b1 = b1[-cap:]
    elif t2:
        victim = t2.pop(0)
        if victim in l1:
            l1.pop(victim, None)
            _stat(k, "evicts")
        b2 = _move_mru(b2, victim)
        if len(b2) > cap:
            b2 = b2[-cap:]
    k["l1"] = l1
    k["arc"] = {"t1": t1, "t2": t2, "b1": b1, "b2": b2, "p": p}


def _arc_touch(k: dict[str, Any], cid: str, *, hit: bool) -> None:
    cap = max(1, int(k.get("l1_cap") or L1_CAP))
    arc = dict(k.get("arc") or {})
    t1 = list(arc.get("t1") or [])
    t2 = list(arc.get("t2") or [])
    b1 = list(arc.get("b1") or [])
    b2 = list(arc.get("b2") or [])
    p = int(arc.get("p") or 0)
    in_t1, in_t2 = cid in t1, cid in t2
    in_b1, in_b2 = cid in b1, cid in b2
    if hit and (in_t1 or in_t2):
        t1 = [x for x in t1 if x != cid]
        t2 = _move_mru(t2, cid)
    elif in_b1:
        delta = max(1, (len(b2) // max(1, len(b1))))
        p = min(cap, p + delta)
        arc["p"] = p
        k["arc"] = {"t1": t1, "t2": t2, "b1": b1, "b2": b2, "p": p}
        _arc_replace(k, in_b2=False)
        arc = dict(k.get("arc") or {})
        t1 = [x for x in (arc.get("t1") or []) if x != cid]
        t2 = _move_mru([x for x in (arc.get("t2") or []) if x != cid], cid)
        b1 = [x for x in (arc.get("b1") or []) if x != cid]
        b2 = list(arc.get("b2") or [])
        p = int(arc.get("p") or p)
    elif in_b2:
        delta = max(1, (len(b1) // max(1, len(b2))))
        p = max(0, p - delta)
        arc["p"] = p
        k["arc"] = {"t1": t1, "t2": t2, "b1": b1, "b2": b2, "p": p}
        _arc_replace(k, in_b2=True)
        arc = dict(k.get("arc") or {})
        t1 = [x for x in (arc.get("t1") or []) if x != cid]
        t2 = _move_mru([x for x in (arc.get("t2") or []) if x != cid], cid)
        b1 = list(arc.get("b1") or [])
        b2 = [x for x in (arc.get("b2") or []) if x != cid]
        p = int(arc.get("p") or p)
    else:
        if len(t1) + len(t2) >= cap:
            k["arc"] = {"t1": t1, "t2": t2, "b1": b1, "b2": b2, "p": p}
            _arc_replace(k, in_b2=False)
            arc = dict(k.get("arc") or {})
            t1 = list(arc.get("t1") or [])
            t2 = list(arc.get("t2") or [])
            b1 = list(arc.get("b1") or [])
            b2 = list(arc.get("b2") or [])
            p = int(arc.get("p") or p)
        t1 = _move_mru([x for x in t1 if x != cid], cid)
    k["arc"] = {"t1": t1, "t2": t2, "b1": b1, "b2": b2, "p": p}


def _l1_touch(k: dict[str, Any], cid: str, *, hit: bool) -> None:
    policy = str(k.get("policy") or "arc").lower()
    if policy == "lru":
        _lru_evict(k, cid, hit=True)
    else:
        _arc_touch(k, cid, hit=hit)


def bump_tick(memory: dict[str, Any]) -> int:
    k = _kernel(memory)
    k["tick"] = int(k.get("tick") or 0) + 1
    return int(k["tick"])


def cache_put(
    memory: dict[str, Any],
    payload: Any,
    *,
    kind: str = "blob",
    ns: str = "draft",
    durable: bool = False,
    duckdb_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Store a CID-keyed blob. ``theorem_ok`` is stripped — cache is not lake."""

    body = payload
    if isinstance(payload, dict):
        body = {k: v for k, v in payload.items() if k not in {"theorem_ok", "lake_ok"}}
    cid = content_cid({"kind": kind, "body": body})
    ns_name = str(ns or "draft")
    if ns_name not in {"draft", "jev", "graph", "context"}:
        ns_name = "draft"
    entry = {"cid": cid, "ns": ns_name, "kind": str(kind), "body": body, "admit": False}
    k = _kernel(memory)
    k["l1"][cid] = entry
    _l1_touch(k, cid, hit=False)
    l2 = None
    if durable:
        gc_l2()
        dest = cas_dir() / (cid.replace(":", "_") + ".json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
        l2 = str(dest)
    l3 = None
    if duckdb_path is not None:
        try:
            from jevops import jsonld as lra_ld

            doc = lra_ld.empty_document()
            doc["@graph"] = [{"@id": cid, "@type": "Node", "kind": kind, "identifier": cid}]
            l3 = lra_ld.ingest_duckdb(doc, db_path=Path(duckdb_path))
        except Exception as exc:
            l3 = {"ok": False, "reason": type(exc).__name__, "optional": True}
    return {
        "ok": True,
        "kind": "port_cache_put",
        "cid": cid,
        "tiers": ["L1"] + (["L2"] if l2 else []) + (["L3"] if l3 and l3.get("ok") else []),
        "l2": l2,
        "l3": l3,
        "admit": False,
        "writes_lean": False,
        "called_docker0": False,
    }


def cache_get(memory: dict[str, Any], cid: str, *, duckdb_path: Optional[Path] = None) -> dict[str, Any]:
    cid = str(cid or "")
    k = _kernel(memory)
    hit = dict(k.get("l1") or {}).get(cid)
    tier = "L1" if hit else None
    if hit:
        if not _verify_cid(hit, cid):
            _stat(k, "integrity_miss")
            dict(k.get("l1") or {}).pop(cid, None)
            k["l1"].pop(cid, None)
            hit = None
            tier = None
        else:
            _l1_touch(k, cid, hit=True)
            _stat(k, "hits")
    if not hit:
        path = cas_dir() / (cid.replace(":", "_") + ".json")
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if _verify_cid(loaded, cid):
                    hit = loaded
                    tier = "L2"
                    k["l1"][cid] = hit
                    _l1_touch(k, cid, hit=False)
                    _stat(k, "hits")
                else:
                    _stat(k, "integrity_miss")
                    hit = None
            except Exception:
                hit = None
    if not hit and duckdb_path is not None:
        try:
            from jevops import jsonld as lra_ld

            q = lra_ld.query_duckdb(cid, db_path=Path(duckdb_path))
            if q.get("ok") and q.get("hits"):
                hit = {"cid": cid, "kind": "jsonld", "body": q["hits"][0], "admit": False}
                tier = "L3"
        except Exception:
            hit = None
    if not hit:
        _stat(k, "misses")
        return {"ok": False, "reason": "miss", "cid": cid, "admit": False, "kind": "port_cache_get"}
    hit = dict(hit)
    hit["admit"] = False
    hit.pop("theorem_ok", None)
    return {
        "ok": True,
        "kind": "port_cache_get",
        "cid": cid,
        "tier": tier,
        "entry": hit,
        "admit": False,
        "writes_lean": False,
        "called_docker0": False,
    }


def negative_put(memory: dict[str, Any], key: str, *, reason: str = "lake_fail", ttl: int = NEGATIVE_TTL_TICKS) -> dict[str, Any]:
    k = _kernel(memory)
    tick = int(k.get("tick") or 0)
    k["negative"][str(key)] = {"until": tick + max(1, int(ttl)), "reason": str(reason), "admit": False}
    return {"ok": True, "kind": "port_negative_ttl", "key": key, "until": tick + max(1, int(ttl)), "admit": False}


def negative_hit(memory: Mapping[str, Any], key: str) -> bool:
    k = dict((memory.get("nca") or {}).get("kernel") or {})
    row = dict(k.get("negative") or {}).get(str(key))
    if not row:
        return False
    hit = int(k.get("tick") or 0) < int(row.get("until") or 0)
    if hit and isinstance(memory, dict):
        _stat(_kernel(memory), "negative_hits")
    return hit


def sweep_negative(memory: dict[str, Any]) -> int:
    k = _kernel(memory)
    tick = int(k.get("tick") or 0)
    neg = dict(k.get("negative") or {})
    keep = {key: row for key, row in neg.items() if tick < int((row or {}).get("until") or 0)}
    dropped = len(neg) - len(keep)
    k["negative"] = keep
    return dropped


def _inflight_dir() -> Path:
    override = os.environ.get("LRA_NCA_INFLIGHT")
    return Path(override) if override else (cas_dir() / "inflight")


def _inflight_path(key: str) -> Path:
    digest = content_cid(key).replace(":", "_")
    return _inflight_dir() / f"{digest}.json"


def flight_begin(memory: dict[str, Any], key: str) -> dict[str, Any]:
    k = _kernel(memory)
    inflight = [str(x) for x in (k.get("in_flight") or [])]
    key = str(key)
    if key in inflight:
        _stat(k, "flights")
        return {"ok": False, "kind": "port_singleflight", "reason": "in_flight", "key": key, "admit": False}
    path = _inflight_path(key)
    if path.is_file():
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = INFLIGHT_TTL_S + 1
        if age < INFLIGHT_TTL_S:
            _stat(k, "flights")
            return {
                "ok": False,
                "kind": "port_singleflight",
                "reason": "in_flight",
                "key": key,
                "durable": True,
                "admit": False,
            }
        try:
            path.unlink()
        except OSError:
            pass
    inflight.append(key)
    _stat(k, "flights")
    k["in_flight"] = inflight[-64:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "t": time.time()}), encoding="utf-8")
    except OSError:
        pass
    return {"ok": True, "kind": "port_singleflight", "key": key, "begun": True, "admit": False}


def guarded_compile(
    memory: Optional[dict[str, Any]],
    *,
    name: Any,
    kind: str,
    tactics: str,
    compile_fn: Any,
) -> dict[str, Any]:
    """Wrap a lake compile: negative TTL + single-flight. Never admits from cache."""

    if not isinstance(memory, dict):
        return dict(compile_fn() or {})
    bump_tick(memory)
    sweep_negative(memory)
    key = lake_key(name, kind, tactics)
    if negative_hit(memory, key):
        return {
            "theorem_ok": False,
            "ok": False,
            "token_count": 0,
            "errors": [],
            "skipped": "negative_ttl",
            "reason": "negative_ttl",
        }
    begun = flight_begin(memory, key)
    if not begun.get("ok"):
        return {
            "theorem_ok": False,
            "ok": False,
            "token_count": 0,
            "errors": [],
            "skipped": "in_flight",
            "reason": "in_flight",
        }
    try:
        compiled = dict(compile_fn() or {})
        if not compiled.get("theorem_ok"):
            negative_put(memory, key, reason=str(compiled.get("error_class") or "lake_fail"))
            cache_put(
                memory,
                {"name": name, "kind": kind, "tactics": str(tactics)[:400]},
                kind=str(kind or "compile"),
                ns="draft",
            )
        return compiled
    finally:
        flight_end(memory, key)


def flight_end(memory: dict[str, Any], key: str) -> dict[str, Any]:
    k = _kernel(memory)
    key = str(key)
    k["in_flight"] = [x for x in (k.get("in_flight") or []) if str(x) != key]
    try:
        _inflight_path(key).unlink()
    except OSError:
        pass
    return {"ok": True, "kind": "port_singleflight", "key": key, "begun": False, "admit": False}


def apply_context_budget(memory: dict[str, Any]) -> dict[str, Any]:
    k = _kernel(memory)
    budget = dict(k.get("budget") or {})
    max_cells = int(budget.get("max_cells") or MAX_CELLS)
    max_bytes = int(budget.get("max_bytes") or MAX_BYTES)
    trimmed = 0
    try:
        from jevops import tape as lra_tape

        tape = lra_tape.Tape.from_memory(memory)
        kept = tape.keep_k(max_cells)
        trimmed = tape.trim_bytes(max_bytes)
        tape.persist(memory)
    except Exception:
        kept = 0
    dt = dict((memory.get("nca") or {}).get("dt") or {})
    window = list(dt.get("window") or [])
    while window and len(json.dumps(window, default=str)) > max_bytes:
        window.pop(0)
        trimmed += 1
    if dt:
        dt["window"] = window
        memory.setdefault("nca", {})["dt"] = dt
    return {
        "ok": True,
        "kind": "port_context_budget",
        "max_cells": max_cells,
        "max_bytes": max_bytes,
        "kept": kept,
        "trimmed": trimmed,
        "writes_lean": False,
        "called_docker0": False,
    }


def call_kernel(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    text = str(stem or "").lower()
    bump_tick(memory)
    if "cache_arc" in text:
        return set_policy(memory, "arc")
    if "cache_lru" in text:
        return set_policy(memory, "lru")
    if "cache_put" in text:
        return cache_put(memory, {"tactics": tactics, "problem": problem}, kind="context")
    if "cache_get" in text:
        cid = content_cid({"kind": "context", "body": {"tactics": tactics, "problem": problem}})
        return cache_get(memory, cid)
    if "negative" in text:
        key = f"{problem}::{tactics[:80]}"
        if negative_hit(memory, key):
            return {"ok": True, "kind": "port_negative_ttl", "hit": True, "key": key, "admit": False}
        return negative_put(memory, key, reason="observe")
    if "flight" in text or "single" in text:
        key = f"{problem}::{tactics[:80]}"
        begun = flight_begin(memory, key)
        if begun.get("ok"):
            flight_end(memory, key)
        return begun
    if "budget" in text:
        return apply_context_budget(memory)
    _kernel(memory)
    return {
        "ok": True,
        "kind": "port_nca_kernel",
        "tick": _kernel(memory).get("tick"),
        "n_l1": len(_kernel(memory).get("l1") or {}),
        "n_negative": len(_kernel(memory).get("negative") or {}),
        "admit": False,
        "writes_lean": False,
        "called_docker0": False,
    }
