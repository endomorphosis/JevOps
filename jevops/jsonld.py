#!/usr/bin/env python3
"""JSON-LD is the graph interface. DuckDB is an optional adapter.

Canonical document shape is JSON-LD 1.1 (compact). Traverse / GraphRAG /
neural message-passing consume ``@graph`` nodes and edges. They do not
import DuckDB. Optional ``ingest_duckdb`` / ``query_duckdb`` project the
same JSON-LD into a sidecar DuckDB (never campaign control.duckdb).
Never docker0. Does not write Lean.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

CONTEXT = {
    "@vocab": "https://lra.local/nca#",
    "id": "@id",
    "type": "@type",
    "schema": "https://schema.org/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "Node": "https://lra.local/nca#Node",
    "Edge": "https://lra.local/nca#Edge",
    "ptr": "https://lra.local/nca#ptr",
    "kind": "https://lra.local/nca#kind",
    "energyM": {"@id": "https://lra.local/nca#energyM", "@type": "xsd:integer"},
    "from": {"@id": "https://lra.local/nca#from", "@type": "@id"},
    "to": {"@id": "https://lra.local/nca#to", "@type": "@id"},
    "name": "schema:name",
    "identifier": "schema:identifier",
}

JSONLD_KEY = "jsonld"


def empty_document() -> dict[str, Any]:
    return {
        "@context": dict(CONTEXT),
        "@graph": [],
        "@type": "schema:Dataset",
        "identifier": "lra-nca-graph",
    }


def _node_id(ptr: str) -> str:
    text = str(ptr or "").strip()
    if text.startswith("ptr://") or text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("_:"):
        return text
    return f"ptr://cell/{text}" if text else "_:anon"


def document_from_edges(
    edges: Sequence[Sequence[str]],
    *,
    grid: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build JSON-LD from board_edges / grid. No DuckDB."""

    doc = empty_document()
    seen: set[str] = set()
    graph: list[dict[str, Any]] = []
    n_edge = 0
    grid = dict(grid or {})
    for edge in edges or []:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        src, dst = _node_id(str(edge[0])), _node_id(str(edge[1]))
        for nid in (src, dst):
            if nid in seen:
                continue
            seen.add(nid)
            cell = grid.get(nid) or grid.get(str(edge[0 if nid == src else 1])) or {}
            kind = str(cell.get("kind") or "")
            if not kind and nid.startswith("ptr://"):
                parts = nid.split("/")
                kind = parts[2] if len(parts) > 2 else "cell"
            kind = kind or "cell"
            energy = cell.get("energy")
            energy_m = 0
            try:
                e = float(energy or 0)
                energy_m = int(e * 1000) if e <= 2 else int(e)
            except (TypeError, ValueError):
                energy_m = 0
            graph.append(
                {
                    "@id": nid,
                    "@type": "Node",
                    "ptr": nid,
                    "kind": kind,
                    "identifier": nid,
                    "energyM": int(energy_m),
                }
            )
        n_edge += 1
        graph.append(
            {
                "@id": f"_:e{n_edge}",
                "@type": "Edge",
                "from": src,
                "to": dst,
            }
        )
    doc["@graph"] = graph
    return doc


def memory_jsonld(memory: Mapping[str, Any]) -> dict[str, Any]:
    nca = dict((memory.get("nca") or {}) if isinstance(memory, dict) else {})
    existing = nca.get(JSONLD_KEY)
    if isinstance(existing, dict) and isinstance(existing.get("@graph"), list) and existing.get("@graph"):
        ctx = dict(CONTEXT)
        ctx.update(dict(existing.get("@context") or {}))
        return {"@context": ctx, "@graph": list(existing["@graph"]), "@type": existing.get("@type") or "schema:Dataset"}
    edges = list(nca.get("board_edges") or [])
    grid = dict(nca.get("grid") or {})
    return document_from_edges(edges, grid=grid)


def put_jsonld(memory: dict[str, Any], doc: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "@context": dict(doc.get("@context") or CONTEXT),
        "@graph": list(doc.get("@graph") or []),
        "@type": doc.get("@type") or "schema:Dataset",
        "identifier": doc.get("identifier") or "lra-nca-graph",
    }
    memory.setdefault("nca", {})[JSONLD_KEY] = payload
    return payload


def adj_from_jsonld(doc: Mapping[str, Any]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {}
    for item in doc.get("@graph") or []:
        if not isinstance(item, dict):
            continue
        types = item.get("@type") or item.get("type")
        type_s = types if isinstance(types, str) else " ".join(types or [])
        if "Edge" not in str(type_s):
            continue
        src = _node_id(str(item.get("from") or item.get("https://lra.local/nca#from") or ""))
        dst = _node_id(str(item.get("to") or item.get("https://lra.local/nca#to") or ""))
        if not src or not dst or src == "_:anon" or dst == "_:anon":
            continue
        adj.setdefault(src, [])
        adj.setdefault(dst, [])
        if dst not in adj[src]:
            adj[src].append(dst)
        if src not in adj[dst]:
            adj[dst].append(src)
    for item in doc.get("@graph") or []:
        if not isinstance(item, dict):
            continue
        types = item.get("@type") or item.get("type")
        type_s = types if isinstance(types, str) else " ".join(types or [])
        if "Node" in str(type_s) or str(item.get("@id") or "").startswith("ptr://"):
            nid = _node_id(str(item.get("@id") or item.get("ptr") or ""))
            if nid and nid != "_:anon":
                adj.setdefault(nid, [])
    return adj


def search_jsonld(doc: Mapping[str, Any], query: str, *, limit: int = 12) -> list[dict[str, Any]]:
    needle = str(query or "").casefold()
    hits: list[dict[str, Any]] = []
    if not needle:
        return hits
    for item in doc.get("@graph") or []:
        if not isinstance(item, dict):
            continue
        blob = " ".join(str(item.get(k) or "") for k in ("@id", "ptr", "kind", "identifier", "name", "schema:name"))
        if needle not in blob.casefold():
            continue
        hits.append(
            {
                "symbol": str(item.get("@id") or item.get("ptr") or ""),
                "source": "jsonld",
                "kind": item.get("kind"),
                "score": 0.88,
            }
        )
        if len(hits) >= limit:
            break
    return hits


def ingest_duckdb(doc: Mapping[str, Any], *, db_path: Path) -> dict[str, Any]:
    """Optional projection of JSON-LD into DuckDB. Not required by graph CALLs."""

    dest = Path(db_path)
    if dest.name == "control.duckdb" or "control.duckdb" in str(dest):
        return {"ok": False, "reason": "campaign_db_refused", "control_duckdb": True}
    try:
        import duckdb  # type: ignore[import-not-found]
    except Exception:
        return {"ok": False, "reason": "duckdb_unavailable", "optional": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(dest))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS jsonld_nodes (id VARCHAR, type VARCHAR, kind VARCHAR, energy_m INTEGER, doc JSON)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS jsonld_edges (src VARCHAR, dst VARCHAR, rel VARCHAR, doc JSON)"
        )
        con.execute("DELETE FROM jsonld_nodes")
        con.execute("DELETE FROM jsonld_edges")
        n_nodes = 0
        n_edges = 0
        for item in doc.get("@graph") or []:
            if not isinstance(item, dict):
                continue
            raw = json.dumps(item, sort_keys=True)
            types = item.get("@type") or item.get("type") or ""
            type_s = types if isinstance(types, str) else " ".join(types or [])
            if "Edge" in str(type_s):
                src = str(item.get("from") or "")
                dst = str(item.get("to") or "")
                con.execute("INSERT INTO jsonld_edges VALUES (?, ?, ?, ?)", [src, dst, "from_to", raw])
                n_edges += 1
            else:
                nid = str(item.get("@id") or item.get("ptr") or "")
                kind = str(item.get("kind") or "")
                energy = int(item.get("energyM") or 0)
                con.execute(
                    "INSERT INTO jsonld_nodes VALUES (?, ?, ?, ?, ?)",
                    [nid, str(type_s), kind, energy, raw],
                )
                n_nodes += 1
    finally:
        con.close()
    return {
        "ok": True,
        "path": str(dest),
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "optional": True,
        "control_duckdb": False,
        "interface": "json-ld",
    }


def query_duckdb(query: str, *, db_path: Path, limit: int = 12) -> dict[str, Any]:
    """Optional DuckDB read of a JSON-LD projection. Fail-closed if missing."""

    dest = Path(db_path)
    if dest.name == "control.duckdb" or not dest.is_file():
        return {"ok": False, "reason": "no_db", "hits": [], "optional": True}
    try:
        import duckdb  # type: ignore[import-not-found]
    except Exception:
        return {"ok": False, "reason": "duckdb_unavailable", "hits": [], "optional": True}
    needle = f"%{str(query or '').casefold()}%"
    con = duckdb.connect(str(dest), read_only=True)
    try:
        rows = con.execute(
            "SELECT id, kind FROM jsonld_nodes WHERE lower(id) LIKE ? OR lower(kind) LIKE ? LIMIT ?",
            [needle, needle, int(limit)],
        ).fetchall()
    except Exception as exc:
        con.close()
        return {"ok": False, "reason": type(exc).__name__, "hits": [], "optional": True}
    con.close()
    hits = [{"symbol": str(r[0]), "kind": str(r[1]), "source": "jsonld_duckdb"} for r in rows]
    return {"ok": True, "hits": hits, "optional": True, "interface": "json-ld"}
