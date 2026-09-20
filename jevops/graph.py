#!/usr/bin/env python3
"""Board-graph traversal, GraphRAG search, milles message-passing.

The graph interface is JSON-LD (nca_jsonld). DuckDB is an optional adapter
that can ingest/query the same document. Neural graph reasoning is integer
neighborhood aggregation, not a CUDA GNN. GraphRAG searches JSON-LD first,
then harness symbol_search (KG/AST/rg); DuckDB is optional. Never docker0.
Jev does not write Lean. Lake is the oracle. Not Arena scores.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Optional

MILLE = 1000
GRAPH_STEMS = ("graphrag", "graph_rag", "graph-rag", "traverse", "traversal", "neural_graph", "graph_reason")
MAX_HOPS = 4
MSG_ITERS = 2


def is_graph_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    return any(tag in text for tag in GRAPH_STEMS)


def _clip(value: int, lo: int = 0, hi: int = MILLE) -> int:
    return max(lo, min(hi, int(value)))


def board_adj(memory: Mapping[str, Any]) -> dict[str, list[str]]:
    """Adjacency from JSON-LD, then board_edges. Never requires DuckDB."""

    from jevops import jsonld as lra_ld

    if isinstance(memory, dict) and not ((memory.get("nca") or {}).get("jsonld") or {}).get("@graph"):
        if not ((memory.get("nca") or {}).get("board_edges")):
            try:
                from jevops import hooks

                seeder = hooks.get("seed_board") or hooks.try_import(
                    "board_graph", "seed_nca_from_board"
                )
                if seeder:
                    seeder(memory)
            except Exception:
                pass
        doc = lra_ld.memory_jsonld(memory)
        if doc.get("@graph"):
            lra_ld.put_jsonld(memory, doc)
    doc = lra_ld.memory_jsonld(memory if isinstance(memory, dict) else {})
    adj = lra_ld.adj_from_jsonld(doc)
    if adj:
        return adj
    edges = list(((memory.get("nca") or {}).get("board_edges") or [])) if isinstance(memory, dict) else []
    adj = {}
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        a, b = str(edge[0]), str(edge[1])
        adj.setdefault(a, [])
        adj.setdefault(b, [])
        if b not in adj[a]:
            adj[a].append(b)
        if a not in adj[b]:
            adj[b].append(a)
    return adj


def _energy_m(memory: Mapping[str, Any], node: str) -> int:
    cell = ((memory.get("nca") or {}).get("grid") or {}).get(node) or {}
    try:
        e = float(cell.get("energy") or 0.0)
    except (TypeError, ValueError):
        e = 0.0
    if e <= 2:
        return _clip(int(e * MILLE))
    return _clip(int(e))


def traverse(
    memory: dict[str, Any],
    *,
    start: str = "",
    mode: str = "bfs",
    max_hops: int = MAX_HOPS,
) -> dict[str, Any]:
    adj = board_adj(memory)
    if not adj:
        return {"ok": True, "reason": "no_edges", "kind": "port_graph_traverse", "path": [], "writes_lean": False, "integer": True}
    root = start or next(iter(adj))
    if root not in adj:
        for node in adj:
            if root and root in node:
                root = node
                break
        else:
            root = next(iter(adj))
    hops = max(1, min(int(max_hops), 8))
    seen = {root: 0}
    order = [root]
    if mode == "dfs":
        stack = [root]
        while stack:
            node = stack.pop()
            if seen.get(node, 0) >= hops:
                continue
            for nxt in reversed(adj.get(node) or []):
                if nxt in seen:
                    continue
                seen[nxt] = seen[node] + 1
                order.append(nxt)
                stack.append(nxt)
    else:
        q: deque[str] = deque([root])
        while q:
            node = q.popleft()
            if seen[node] >= hops:
                continue
            for nxt in adj.get(node) or []:
                if nxt in seen:
                    continue
                seen[nxt] = seen[node] + 1
                order.append(nxt)
                q.append(nxt)
    from jevops.outer import head_seq

    path = head_seq(order, 32)
    memory.setdefault("nca", {})["traverse"] = {"order": path, "mode": mode, "integer": True}
    return {
        "ok": True,
        "kind": "port_graph_traverse",
        "start": root,
        "mode": mode,
        "path": path,
        "n": len(order),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def message_pass(memory: dict[str, Any], *, iters: int = MSG_ITERS) -> dict[str, Any]:
    """Integer GNN-style sum of neighbor energy milles. No CUDA."""

    adj = board_adj(memory)
    if not adj:
        return {"ok": True, "reason": "no_edges", "kind": "port_neural_graph", "writes_lean": False, "integer": True}
    h = {node: _energy_m(memory, node) for node in adj}
    for _ in range(max(1, int(iters))):
        nxt = {}
        for node, nbrs in adj.items():
            acc = h[node]
            if nbrs:
                acc = (acc + sum(h.get(n, 0) for n in nbrs) // len(nbrs)) // 2
            nxt[node] = _clip(acc)
        h = nxt
    ranked = sorted(h, key=lambda node: (-h[node], node))
    from jevops.outer import head_seq

    ranked_head = head_seq(ranked, 12)
    memory.setdefault("nca", {})["neural_graph"] = {"h": h, "integer": True}
    if ranked_head:
        memory.setdefault("nca", {})["pipeline_bias"] = ranked_head
    return {
        "ok": True,
        "kind": "port_neural_graph",
        "ranked": ranked_head,
        "n_nodes": len(h),
        "iters": int(iters),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def graphrag_search(
    memory: dict[str, Any],
    *,
    query: str = "",
    tactics: str = "",
    problem: str = "",
    duckdb_path: Optional[Any] = None,
) -> dict[str, Any]:
    """JSON-LD GraphRAG first. DuckDB is an optional adapter, never required."""

    from jevops import jsonld as lra_ld

    q = str(query or problem or "").strip()
    hits: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    doc = lra_ld.memory_jsonld(memory)
    if not doc.get("@graph"):
        board_adj(memory)
        doc = lra_ld.memory_jsonld(memory)
    for hit in lra_ld.search_jsonld(doc, q):
        hits.append(
            {
                "symbol": hit.get("symbol"),
                "source": "jsonld",
                "score_m": 880,
            }
        )
    sources["jsonld"] = "ok"
    if duckdb_path is not None:
        projected = lra_ld.ingest_duckdb(doc, db_path=duckdb_path)
        sources["duckdb_ingest"] = str(projected.get("reason") or "ok")
        if projected.get("ok"):
            qdb = lra_ld.query_duckdb(q, db_path=duckdb_path)
            sources["duckdb"] = "ok" if qdb.get("ok") else str(qdb.get("reason"))
            for hit in qdb.get("hits") or []:
                hits.append({"symbol": hit.get("symbol"), "source": "jsonld_duckdb", "score_m": 800})
    else:
        sources["duckdb"] = "skipped_optional"
    try:
        from jevops import hooks

        search = hooks.get("symbol_search") or hooks.try_import("symbol_search", "search_symbols")
        if search is None:
            raise RuntimeError("symbol_search_unavailable")
        found = search(q, memory=memory, tactics=tactics, use_duckdb=False)
        from jevops.outer import head_seq

        for hit in head_seq(found.get("hits") or found.get("ranked") or [], 12):
            src = str(hit.get("source") or "symbol_search")
            if src in {"duckdb", "sidecar_duckdb"}:
                continue
            hits.append(
                {
                    "symbol": hit.get("symbol") or hit.get("ptr") or hit.get("path"),
                    "source": src,
                    "score_m": _clip(
                        int(float(hit.get("score") or 0.0) * MILLE)
                        if float(hit.get("score") or 0) <= 2
                        else int(hit.get("score") or 0)
                    ),
                }
            )
        sources["symbol_search"] = "ok"
        for key, note in dict(found.get("sources") or {}).items():
            if key != "duckdb":
                sources[key] = note
    except Exception as exc:
        sources["symbol_search"] = type(exc).__name__
    try:
        from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_graphrag import SkillCenterGraphRAG

        _ = SkillCenterGraphRAG
        sources["datasets_graphrag"] = "importable"
    except Exception as exc:
        sources["datasets_graphrag"] = type(exc).__name__
    ranked = [str(h.get("symbol") or "") for h in hits if h.get("symbol")]
    from jevops.outer import head_seq

    ranked_head = head_seq(ranked, 12)
    memory.setdefault("nca", {})["graphrag"] = {
        "query": q,
        "n_hits": len(hits),
        "sources": sources,
        "interface": "json-ld",
        "integer": True,
    }
    if ranked_head:
        memory.setdefault("nca", {})["pipeline_bias"] = ranked_head
    return {
        "ok": True,
        "kind": "port_graphrag",
        "query": q,
        "n_hits": len(hits),
        "ranked": ranked_head,
        "sources": sources,
        "interface": "json-ld",
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def call_graph(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
    query: str = "",
) -> dict[str, Any]:
    text = str(stem or "").lower()
    if "graphrag" in text or "graph_rag" in text or "graph-rag" in text:
        return graphrag_search(memory, query=query or problem, tactics=tactics, problem=problem)
    if "neural" in text or "reason" in text:
        return message_pass(memory)
    if "dfs" in text:
        start = ""
        if problem:
            start = f"ptr://theorem/{problem}"
        return traverse(memory, start=start, mode="dfs")
    start = ""
    if problem:
        start = f"ptr://theorem/{problem}"
    return traverse(memory, start=start, mode="bfs")
