#!/usr/bin/env python3
"""Ranked symbol search for TypeSafe.

Order: JSON-LD graph (if present) → optional DuckDB adapter → vector → KG →
AST → ripgrep. DuckDB is never required. Never docker0. Does not write Lean.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
PAPER_ROOT = HERE.parent
LRA_STATE = _jevops_path.LRA_STATE_ROOT
NCA_ARTIFACT_ROOT = _jevops_path.LRA_NCA_ROOT
MAX_HITS = 24
RG_TIMEOUT = 4.0

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.']*")

SOURCE_WEIGHT = {
    "jsonld": 1.02,
    "jsonld_duckdb": 0.92,
    "duckdb": 0.9,
    "sidecar_duckdb": 0.88,
    "vector": 0.95,
    "kg": 0.85,
    "ast": 0.7,
    "rg": 0.5,
}


def _ptr(symbol: str) -> str:
    return f"ptr://skill/{symbol}" if str(symbol).startswith("port_") else ""


def _score(query: str, symbol: str, source: str) -> float:
    from jevops.search import name_match_score

    return name_match_score(query, symbol, source=source, weights=SOURCE_WEIGHT)


def _hit(symbol: str, *, source: str, query: str, path: str = "", extra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    from jevops.search import hit_row

    return hit_row(
        symbol,
        source=source,
        query=query,
        path=path,
        extra=extra,
        weights=SOURCE_WEIGHT,
        ptr_fn=_ptr,
    )


def _candidate_duckdb_paths() -> list[Path]:
    from jevops.outer import existing_files, optional_env_path

    paths: list[Path] = []
    env_path = optional_env_path("LRA_DUCKDB_AST_INDEX")
    if env_path is not None:
        paths.append(env_path)
    paths.extend(
        (
            NCA_ARTIFACT_ROOT / "nca-ast.duckdb",
            LRA_STATE / "ast_index.duckdb",
            LRA_STATE / "code_symbols.duckdb",
        )
    )
    return existing_files(paths, exclude_names=("control.duckdb",))


def search_duckdb(query: str, *, db_path: Optional[Path] = None) -> tuple[list[dict[str, Any]], str]:
    """Query ipfs_accelerate DuckDB AST/symbol tables if a DB exists."""

    from jevops.outer import query_first_engine, try_import

    if try_import("duckdb") is None:
        return [], "duckdb_unavailable"
    paths = [db_path] if db_path is not None else _candidate_duckdb_paths()
    paths = [path for path in paths if path is not None and path.is_file()]
    if not paths:
        return [], "no_duckdb_index"
    needle = f"%{query.casefold()}%"
    table_sql = {
        "symbols": (
            "SELECT qualified_name, path, symbol_kind FROM symbols "
            "WHERE lower(CAST(qualified_name AS VARCHAR)) LIKE ? LIMIT 20"
        ),
        "code_symbols": (
            "SELECT name, path, kind FROM code_symbols "
            "WHERE lower(CAST(name AS VARCHAR)) LIKE ? LIMIT 20"
        ),
    }
    hits, used = query_first_engine(
        paths,
        table_sql,
        [needle],
        refuse_names=("control.duckdb",),
        row_fn=lambda row: (
            _hit(
                str(row[0] or ""),
                source="duckdb",
                query=query,
                path=str(row[1] or ""),
                extra={"kind": str(row[2] or "") if len(row) > 2 else ""},
            )
            if row and row[0]
            else None
        ),
    )
    return hits, (used if used not in {"no_index", "no_matching_table", "query_failed"} else "duckdb_no_symbols")


def search_vector_index(
    query: str,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    search_fn: Optional[Callable[..., Any]] = None,
) -> tuple[list[dict[str, Any]], str]:
    """ipfs_accelerate_py code-symbol vector index. Advisory only."""

    if snapshot is None:
        return [], "no_vector_snapshot"
    fn = search_fn
    if fn is None:
        try:
            from _optional_deps import load_vector_index

            vector_module, reason = load_vector_index()
            if vector_module is None:
                return [], reason or "vector_index_unavailable"
            fn = vector_module.search_code_symbol_vector_index
        except Exception as exc:
            from jevops.outer import tagged_exc

            return [], tagged_exc("vector_index_unavailable", exc)
    try:
        result = fn(snapshot, {"query_text": query, "max_results": 12})
    except Exception as exc:
        from jevops.outer import tagged_exc

        return [], tagged_exc("vector_search_failed", exc)
    from jevops.search import vector_hits_from_result

    return (
        vector_hits_from_result(
            result,
            query=query,
            hit_fn=_hit,
            cap=12,
            vector_weight=SOURCE_WEIGHT["vector"],
        ),
        "vector",
    )


def search_kg(query: str, memory: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    import typesafe_tools as lra_tools

    from jevops.outer import matching_nodes

    graph = lra_tools.skill_knowledge_graph(memory)
    return [
        _hit(str(node.get("id") or ""), source="kg", query=query, extra={"kind": node.get("kind")})
        for node in matching_nodes(graph.get("nodes") or [], query, cap=MAX_HITS)
    ]


def search_ast(query: str, *, root: Optional[Path] = None) -> list[dict[str, Any]]:
    from jevops.nca import matching_top_level

    rows = matching_top_level(root or HERE, query, cap_hits=MAX_HITS)
    return [
        _hit(
            str(row["name"]),
            source="ast",
            query=query,
            path=str(row["path"]),
            extra={"lineno": int(row.get("lineno") or 0)},
        )
        for row in rows
    ]


def search_rg(query: str, *, root: Optional[Path] = None) -> tuple[list[dict[str, Any]], str]:
    from jevops.search import search_rg as _search_rg

    return _search_rg(
        query,
        root=root or HERE,
        ident_re=_IDENT,
        timeout=RG_TIMEOUT,
        cap=MAX_HITS,
        globs=("*.py", "*.lean"),
        hit_fn=lambda symbol, path="", snippet="", **_k: _hit(
            symbol, source="rg", query=query, path=path, extra={"line": snippet}
        ),
    )


def rank_hits(hits: list[dict[str, Any]], *, limit: int = 16) -> list[dict[str, Any]]:
    from jevops.search import rank_hits as _rank_hits

    return _rank_hits(hits, limit=limit)


def search_symbols(
    query: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    tactics: str = "",
    duckdb_path: Optional[Path] = None,
    use_duckdb: bool = True,
    vector_snapshot: Optional[Mapping[str, Any]] = None,
    vector_search: Optional[Callable[..., Any]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Search/rank symbols. JSON-LD → optional DuckDB → vector → KG → ast → rg."""

    from jevops.search import collect_source_hits, credit_search_hits, first_ident, pack_symbol_search

    q = str(query or "").strip() or first_ident(tactics, _IDENT)
    sources: dict[str, str] = {}
    hits: list[dict[str, Any]] = []
    if q:

        def _jsonld() -> list[dict[str, Any]]:
            import nca_jsonld as lra_ld

            doc = lra_ld.memory_jsonld(memory or {})
            return [
                _hit(str(hit.get("symbol") or ""), source="jsonld", query=q)
                for hit in lra_ld.search_jsonld(doc, q)
            ]

        def _sidecar() -> list[dict[str, Any]]:
            import codepath_graph as lra_cp

            return [
                {
                    "symbol": row.get("symbol"),
                    "source": "sidecar",
                    "path": row.get("path"),
                    "score": 0.72,
                    "ptr": "",
                }
                for row in lra_cp.query_sidecar(
                    q, payload=None if root is None else lra_cp.build_sidecar_index(root=root, write=False)
                )
            ]

        hits, sources = collect_source_hits(
            (
                ("jsonld", _jsonld),
                (
                    "duckdb",
                    (lambda: search_duckdb(q, db_path=duckdb_path))
                    if use_duckdb
                    else (lambda: ([], "skipped_optional")),
                ),
                ("vector", lambda: search_vector_index(q, snapshot=vector_snapshot, search_fn=vector_search)),
                ("kg", lambda: search_kg(q, memory)),
                ("ast", lambda: search_ast(q, root=root)),
                ("sidecar", _sidecar),
                ("rg", lambda: search_rg(q, root=root)),
            ),
            fail_notes={"sidecar": "sidecar_failed"},
        )
    ranked = rank_hits(hits)
    promoted = credit_search_hits(memory if isinstance(memory, dict) else None, ranked)
    return pack_symbol_search(query=q, ranked=ranked, sources=sources, promoted=promoted)
