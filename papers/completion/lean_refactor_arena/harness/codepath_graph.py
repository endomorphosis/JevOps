#!/usr/bin/env python3
"""Allowlisted code-path slices for the NCA (ids/spans, no source bodies).

Roots: LRA harness and ipfs_accelerate_py. Campaign DuckDB is never opened.
Generated sidecars live under the configured LRA state directory; the Arena
source tree and curated evidence remain read-only inputs.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
PAPER_ROOT = HERE.parent
ACCEL = _jevops_path.IPFS_ACCELERATE_PY_ROOT
NCA_ARTIFACT_ROOT = _jevops_path.LRA_NCA_ROOT
SIDECAR = NCA_ARTIFACT_ROOT / "nca-ast-sidecar.json"
SIDECAR_DUCKDB = NCA_ARTIFACT_ROOT / "nca-ast.duckdb"
MAX_NEIGHBORS = 12
_CROSS: dict[str, Any] | None = None
_HARNESS_CROSS: dict[str, Any] | None = None
INSPECT_ONLY_MARKERS = ("generate_text", "docker0", "leanstral_local", "172.17")


def is_inspect_only(name: str) -> bool:
    from jevops.outer import contains_any

    if contains_any(name, INSPECT_ONLY_MARKERS):
        return True
    path = resolve_codepath(name)
    if path is None or not path.is_file():
        return False
    try:
        from jevops.outer import read_text

        head = read_text(path, errors="ignore", max_chars=8000)
    except OSError:
        return False
    return contains_any(head, ("172.17.0.1",))


def _roots() -> tuple[Path, ...]:
    roots = [HERE.resolve(), PAPER_ROOT.resolve()]
    if ACCEL.is_dir():
        roots.append(ACCEL.resolve())
    return tuple(roots)


def resolve_codepath(name: str) -> Optional[Path]:
    from jevops.outer import module_stem

    module = module_stem(name, strip_prefix="ptr://codepath/")
    if module is None:
        return None
    # harness.portable_rewrites:fold_hoist → portable_rewrites.py
    rel = module.replace("harness.", "").replace(".", "/")
    candidates = [
        HERE / f"{Path(rel).name}.py" if "/" not in rel.replace("harness/", "") else HERE / Path(rel).name,
        HERE / Path(rel).with_suffix(".py").name,
        HERE / f"{rel.split('/')[-1]}.py",
        ACCEL / Path(*rel.split("/")).with_suffix(".py"),
    ]
    if rel.endswith(".py"):
        candidates.append(HERE / Path(rel).name)
        candidates.append(ACCEL / rel)
    from jevops.nca import first_existing_file

    return first_existing_file(candidates, roots=_roots())


def slice_codepath(name: str) -> dict[str, Any]:
    """Callers/callees-style slice from Python AST. No source bodies."""

    from jevops.nca import pack_codepath_slice

    path = resolve_codepath(name)
    if path is None:
        return pack_codepath_slice(
            ok=False,
            name=name,
            reason="codepath_not_allowed",
            inspect_only=is_inspect_only(name),
        )
    try:
        from jevops.nca import function_call_map

        from jevops.outer import exc_head, head_seq, read_text

        defs, calls_by = function_call_map(read_text(path))
    except (OSError, SyntaxError) as exc:
        return pack_codepath_slice(ok=False, reason="parse_failed", error=exc_head(exc, 160))
    from jevops.nca import focus_symbol
    from jevops.outer import head_seq

    focus = focus_symbol(name, defs, calls_by)
    inspect = is_inspect_only(name)
    return pack_codepath_slice(
        ok=True,
        path=path.name,
        symbol=focus,
        definitions=head_seq(defs, 40),
        callees=head_seq(calls_by.get(focus), MAX_NEIGHBORS),
        callers=head_seq([fn for fn, kids in calls_by.items() if focus and focus in kids], MAX_NEIGHBORS),
        inspect_only=inspect,
    )


def _iter_allowlisted_py() -> list[Path]:
    from jevops.outer import existing_files, head_seq

    files = head_seq(sorted(HERE.glob("*.py")), 40)
    files.extend(
        existing_files(
            (
                ACCEL / "llm_router.py",
                ACCEL / "agent_supervisor" / "analysis" / "program_graph_queries.py",
                ACCEL / "agent_supervisor" / "analysis" / "duckdb_ast_index.py",
                ACCEL / "agent_supervisor" / "task_sources" / "database_task_source.py",
            )
        )
    )
    return files


def build_sidecar_index(*, root: Optional[Path] = None, write: bool = True) -> dict[str, Any]:
    """JSON AST sidecar of harness (+ allowlisted) files. Never campaign DuckDB."""

    from jevops.nca import sidecar_files

    base = root or HERE
    files_payload = sidecar_files(sorted(base.glob("*.py")), cap_files=80, cap_symbols=80)
    from jevops.nca import pack_sidecar_index

    payload = pack_sidecar_index(files_payload)
    if write:
        from jevops.outer import write_json

        write_json(SIDECAR, payload)
        payload["path"] = str(SIDECAR)
    return payload


def build_sidecar_duckdb(*, path: Optional[Path] = None, refresh: bool = True) -> dict[str, Any]:
    """Build the NCA symbols/calls sidecar outside the source tree.

    An explicit ``path`` remains supported for isolated tests and experiments;
    the default is always the configured state artifact directory.
    """

    from jevops.outer import connect_engine, exec_many, path_refused, table_count, try_import

    dest = Path(path or SIDECAR_DUCKDB)
    graph = harness_call_graph(refresh=refresh)
    from jevops.nca import fill_sidecar_duckdb

    return fill_sidecar_duckdb(
        dest,
        graph,
        connect_fn=connect_engine,
        exec_fn=exec_many,
        count_fn=table_count,
        try_import_fn=try_import,
        refuse_fn=path_refused,
        refuse_names=("control.duckdb",),
    )


def query_sidecar_duckdb(query: str, *, db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    from jevops.outer import query_engine

    needle = f"%{str(query or '').casefold()}%"
    return query_engine(
        Path(db_path or SIDECAR_DUCKDB),
        "SELECT qualified_name, path, symbol_kind FROM symbols "
        "WHERE lower(CAST(qualified_name AS VARCHAR)) LIKE ? LIMIT 20",
        [needle],
        refuse_names=("control.duckdb",),
        row_fn=lambda row: (
            {
                "symbol": str(row[0]),
                "path": str(row[1] or ""),
                "kind": str(row[2] or ""),
                "source": "sidecar_duckdb",
            }
            if row and row[0]
            else None
        ),
    )


def query_calls_duckdb(
    symbol: str,
    *,
    db_path: Optional[Path] = None,
    direction: str = "callees",
) -> list[str]:
    from jevops.outer import query_engine, without_prefix

    name = without_prefix(str(symbol or ""), "ptr://codepath/")
    column = "caller" if direction == "callers" else "callee"
    match_on = "callee" if direction == "callers" else "caller"
    return query_engine(
        Path(db_path or SIDECAR_DUCKDB),
        f"SELECT {column} FROM calls WHERE {match_on} = ? OR {match_on} LIKE ? LIMIT 12",
        [name, f"%:{name.rsplit(':', 1)[-1]}"],
        refuse_names=("control.duckdb",),
        row_fn=lambda row: str(row[0]) if row and row[0] else None,
    )


def harness_call_graph(*, refresh: bool = False) -> dict[str, Any]:
    """Call graph over harness/*.py only (no accelerate parse)."""

    global _HARNESS_CROSS
    if _HARNESS_CROSS is not None and not refresh:
        return _HARNESS_CROSS
    try:
        from jevops.nca import call_graph_from_paths

        _HARNESS_CROSS = call_graph_from_paths(
            sorted(HERE.glob("*.py")),
            cap_files=40,
            cap_neighbors=MAX_NEIGHBORS,
        )
    except Exception:
        _HARNESS_CROSS = {"defs": {}, "calls": {}, "n_defs": 0}
    return _HARNESS_CROSS


def seed_nca_call_edges(memory: dict[str, Any], *, db_path: Optional[Path] = None, limit: int = 48) -> dict[str, Any]:
    """Attach caller→callee pairs as NCA board_edges. DuckDB sidecar or harness AST."""

    from jevops.nca import append_board_edges
    from jevops.outer import path_refused

    dest = Path(db_path or SIDECAR_DUCKDB)
    if path_refused(dest, names=("control.duckdb",)):
        return {"ok": False, "reason": "campaign_db_refused", "n_edges": 0, "control_duckdb": True}
    from jevops.outer import query_engine

    rows: list[tuple[str, str]] = []
    source = "harness_ast"
    fetched = query_engine(
        dest,
        "SELECT caller, callee FROM calls LIMIT ?",
        [int(limit)],
        refuse_names=("control.duckdb",),
        row_fn=lambda row: (str(row[0]), str(row[1])) if row and row[0] and row[1] else None,
    )
    if fetched:
        rows = fetched
        source = "sidecar_duckdb"
    if not rows:
        from jevops.nca import call_pairs_from_graph

        rows = call_pairs_from_graph(harness_call_graph(), limit=limit)
        source = "harness_ast"
    added = append_board_edges(memory, rows, limit=limit)
    return {"ok": True, "n_edges": added, "source": source, "control_duckdb": False, "called_docker0": False}


def query_sidecar(query: str, *, payload: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    from jevops.nca import query_sidecar_symbols

    from jevops.outer import load_json_object

    data = payload
    if data is None and SIDECAR.is_file():
        data = load_json_object(SIDECAR)
    if not data:
        data = build_sidecar_index(write=False)
    return query_sidecar_symbols(data.get("files") or [], query, limit=24)


def allowlist_call_graph(*, refresh: bool = False) -> dict[str, Any]:
    """Cross-module name→qualified-def graph on allowlisted roots."""

    global _CROSS
    if _CROSS is not None and not refresh:
        return _CROSS
    from jevops.nca import call_graph_from_paths

    _CROSS = call_graph_from_paths(_iter_allowlisted_py(), cap_neighbors=MAX_NEIGHBORS)
    return _CROSS


def slice_cross_module(name: str, *, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Callers/callees across allowlisted modules. Ids only; no source bodies."""

    from jevops.nca import first_matching_symbol, pick_qualified, slice_cross_or_local

    return slice_cross_or_local(
        name,
        inspect_fn=slice_codepath,
        inspect_only_fn=is_inspect_only,
        db_hits_fn=lambda query: query_sidecar_duckdb(query, db_path=db_path),
        match_fn=first_matching_symbol,
        callees_fn=lambda symbol: query_calls_duckdb(symbol, db_path=db_path, direction="callees"),
        callers_fn=lambda symbol: query_calls_duckdb(symbol, db_path=db_path, direction="callers"),
        graph_fn=allowlist_call_graph,
        pick_fn=pick_qualified,
        local_fn=slice_codepath,
        cap=MAX_NEIGHBORS,
        strip_prefixes=("harness.",),
    )
