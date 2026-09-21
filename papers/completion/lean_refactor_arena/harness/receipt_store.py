#!/usr/bin/env python3
"""Optional INSERT-only DuckDB sidecar for LRA proof receipts.

Filesystem receipts remain authority for warm-up. DuckDB, when used, is
INSERT-only: no DELETE of existing edges, no upsert of huge parent rows,
and no ``upsert_task``. Proof bodies live in content-addressed files;
database rows hold CIDs, verdicts, and token/elab numbers only.

``run_warmup.py`` remains the control plane. This module is a writer, not
a scheduler and not a ``todo_daemon`` worker. Learned from LA-031 ART
crashes. Loop v1 may skip DuckDB entirely.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"
SUPERVISOR_JSON = PAPER_ROOT / "supervisor.json"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import retrieve as lra_retrieve  # noqa: E402
import splice as lra_splice  # noqa: E402

DATASETS_ROOT = _jevops_path.IPFS_DATASETS_ROOT
PROOF_STORE_SOURCE = (
    DATASETS_ROOT / "ipfs_datasets_py" / "logic" / "common" / "duckdb_proof_store.py"
)
MODELS_SOURCE = DATASETS_ROOT / "ipfs_datasets_py" / "logic" / "hammers" / "models.py"

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
PROTOCOL = "LRA/v1"
RECEIPT_SCHEMA = "lra-proof-receipt/v1"
STORE_SCHEMA = "lra-receipt-store/v1"
PR_ID = "PR-7"
LRAH_ID = "LRAH-008"
CONTROL_PLANE = "papers/completion/lean_refactor_arena/harness/run_warmup.py"
IS_CONTROL_PLANE = False
REQUIRES_TODO_DAEMON = False
REQUIRES_DUCKDB = False
FILESYSTEM_IS_AUTHORITY = True
INSERT_ONLY = True
KERNEL_COMMAND_TEMPLATE = "{lake} env {lean} --json {source_file}"
MEASUREMENT_MAX_HEARTBEATS = 400000
LEAN_NUM_THREADS = 1
NO_NEW_AXIOMS = True
NOT_APPLICABLE = "not-applicable"
DEFAULT_IR = "lean4-proof-body"
DEFAULT_PROPERTY = "statement-preserving-refactor"
DEFAULT_TRANSLATOR = "body-splice-v1"
DEFAULT_BACKEND_ID = "lake-env-lean"
DEFAULT_POLICY = "open_policy_v1"
DEFAULT_RESOURCE = "spark_gb10"
DEFAULT_GENERATOR = "leanstral_local"
MAX_ROW_BYTES = 8192
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Closed vocabulary copied from DuckDBProofStore@1. Self-check diffs this
# against logic/common/duckdb_proof_store.py and fails on drift.
PROOF_AUTHORITY_DIMENSIONS: tuple[str, ...] = (
    "ir",
    "property",
    "assumptions",
    "premises",
    "translator",
    "solver",
    "toolchain",
    "theorem_registry",
    "policy",
    "resource",
    "tree",
    "backend_id",
    "backend_binary",
    "backend_version",
    "backend_config",
)
PROOF_AUTHORITY_DIMENSION_SET = frozenset(PROOF_AUTHORITY_DIMENSIONS)

ALLOWED_SQL_HEAD = re.compile(
    r"^\s*(CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS|INSERT\s+INTO|SELECT)\b",
    re.IGNORECASE | re.DOTALL,
)
FORBIDDEN_SQL = re.compile(
    r"\b(DELETE\s+FROM|DROP\s+TABLE|UPDATE\s+\w+|MERGE\s+INTO|REPLACE\s+INTO|"
    r"INSERT\s+OR\s+REPLACE|INSERT\s+OR\s+IGNORE|TRUNCATE\s+TABLE|"
    r"ALTER\s+TABLE)\b",
    re.IGNORECASE,
)
SQL_STATEMENT_HEAD = re.compile(
    r"^\s*(DELETE\s+FROM|DROP\s+TABLE|UPDATE\s+|MERGE\s+INTO|REPLACE\s+INTO|"
    r"INSERT\s+OR\s+|TRUNCATE\s+TABLE|ALTER\s+TABLE)\b",
    re.IGNORECASE,
)
FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "fcntl",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "todo_daemon",
        "IntentRepository",
        "paper_supervisors",
        "run_warmup",
        "IndependentKernelVerifier",
        "KernelVerifier",
    }
)
FORBIDDEN_CALL_NAMES = frozenset(
    {
        "upsert_task",
        "LOCK_EX",
        "build_environment_lock",
    }
)
PROOF_BODY_KEYS = frozenset({"src", "proof_text", "candidate_source", "body", "lean_source"})

RECEIPT_DDL = """
CREATE TABLE IF NOT EXISTS lra_proof_receipts (
    key_digest VARCHAR PRIMARY KEY,
    theorem_name VARCHAR NOT NULL,
    lean_tag VARCHAR NOT NULL,
    body_digest VARCHAR NOT NULL,
    candidate_cid VARCHAR NOT NULL,
    verdict VARCHAR NOT NULL,
    token_count INTEGER,
    elab_proxy DOUBLE,
    dimensions_json VARCHAR NOT NULL,
    executable_paths_json VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
)
""".strip()

EDGE_DDL = """
CREATE TABLE IF NOT EXISTS lra_proof_edges (
    parent_digest VARCHAR NOT NULL,
    child_digest VARCHAR NOT NULL,
    edge_kind VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    PRIMARY KEY (parent_digest, child_digest, edge_kind)
)
""".strip()

INSERT_RECEIPT_SQL = """
INSERT INTO lra_proof_receipts (
    key_digest, theorem_name, lean_tag, body_digest, candidate_cid,
    verdict, token_count, elab_proxy, dimensions_json,
    executable_paths_json, payload_json, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""".strip()

INSERT_EDGE_SQL = """
INSERT INTO lra_proof_edges (
    parent_digest, child_digest, edge_kind, created_at
) VALUES (?, ?, ?, ?)
""".strip()

SELECT_RECEIPT_SQL = (
    "SELECT key_digest, theorem_name, lean_tag, body_digest, candidate_cid, "
    "verdict, token_count, elab_proxy, dimensions_json, executable_paths_json, "
    "payload_json, created_at FROM lra_proof_receipts WHERE key_digest = ?"
)
SELECT_NEGATIVE_SQL = (
    "SELECT key_digest, verdict FROM lra_proof_receipts "
    "WHERE theorem_name = ? AND body_digest = ? AND lean_tag = ?"
)
SELECT_EDGE_SQL = (
    "SELECT parent_digest, child_digest, edge_kind, created_at "
    "FROM lra_proof_edges WHERE parent_digest = ?"
)
SELECT_EDGE_ONE_SQL = (
    "SELECT parent_digest, child_digest, edge_kind FROM lra_proof_edges "
    "WHERE parent_digest = ? AND child_digest = ? AND edge_kind = ?"
)
SELECT_COUNT_RECEIPTS_SQL = "SELECT COUNT(*) FROM lra_proof_receipts"
SELECT_COUNT_EDGES_SQL = "SELECT COUNT(*) FROM lra_proof_edges"


class ReceiptStoreError(RuntimeError):
    """Fail-closed receipt-store error."""


class DimensionError(ReceiptStoreError):
    """A PROOF_AUTHORITY_DIMENSIONS key was dropped, empty, or unknown."""


class InsertOnlyError(ReceiptStoreError):
    """SQL outside the INSERT/SELECT/CREATE TABLE IF NOT EXISTS vocabulary."""


from jevops.lean import ExecutablePaths
from jevops.lean import ProofReceipt as _KernelProofReceipt


@dataclass
class ProofReceipt(_KernelProofReceipt):
    """LRA overlay: closed authority constants stay on the public dict."""

    generator: str = DEFAULT_GENERATOR
    policy: str = DEFAULT_POLICY
    resource: str = DEFAULT_RESOURCE
    translator: str = DEFAULT_TRANSLATOR
    backend_id: str = DEFAULT_BACKEND_ID
    git_commit: str = NOT_APPLICABLE
    lean_version: str = NOT_APPLICABLE
    hardware_class: str = DEFAULT_RESOURCE

    def to_public_dict(self) -> dict[str, Any]:
        return super().to_public_dict(
            extra={
                "schema": RECEIPT_SCHEMA,
                "protocol": PROTOCOL,
                "control_plane": CONTROL_PLANE,
                "is_control_plane": IS_CONTROL_PLANE,
                "filesystem_authority": FILESYSTEM_IS_AUTHORITY,
                "insert_only": INSERT_ONLY,
                "upsert_task": False,
                "pr": PR_ID,
                "lrah": LRAH_ID,
            }
        )


def sha256_bytes(data: bytes) -> str:
    from jevops.outer import digest_hex

    return digest_hex(data)


def sha256_file(path: Path) -> str:
    from jevops.outer import digest_file

    return digest_file(path)


def canonical_bytes(value: Any) -> bytes:
    from jevops.outer import canonical_bytes as _fn

    return _fn(value)


def content_digest(value: Any) -> str:
    from jevops.outer import digest_canonical

    return digest_canonical(value)


def not_applicable_digest() -> str:
    return content_digest(NOT_APPLICABLE)


def load_warmup_records(path: Optional[Path] = None) -> tuple[bytes, str, list[dict[str, Any]]]:
    return lra_splice.load_warmup_records(path)


def closed_dimensions_from_source(path: Path = PROOF_STORE_SOURCE) -> tuple[str, ...]:
    """Parse PROOF_AUTHORITY_DIMENSIONS from DuckDBProofStore@1 source."""

    from jevops.outer import quoted_strings, read_text, require_file

    path = require_file(path, error_cls=ReceiptStoreError, miss="missing proof-store source: {path}")
    text = read_text(path)
    match = re.search(
        r"PROOF_AUTHORITY_DIMENSIONS: Final\[tuple\[str, \.\.\.\]\] = \((.*?)\)",
        text,
        re.S,
    )
    if match is None:
        raise ReceiptStoreError("PROOF_AUTHORITY_DIMENSIONS missing from duckdb_proof_store.py")
    names = quoted_strings(match.group(1))
    if not names:
        raise ReceiptStoreError("PROOF_AUTHORITY_DIMENSIONS parsed empty")
    return names


def environment_lock_field_names(path: Path = MODELS_SOURCE) -> list[str]:
    """AnnAssign names on EnvironmentLockRecord. No primary_executable field."""

    from jevops.repair import class_ann_names
    from jevops.outer import read_text, require_file

    path = require_file(path, error_cls=ReceiptStoreError, miss="missing hammer models source: {path}")
    names = class_ann_names(read_text(path), "EnvironmentLockRecord")
    if names is None:
        raise ReceiptStoreError("EnvironmentLockRecord class missing from models.py")
    return names


def parse_executable_paths(value: Any) -> ExecutablePaths:
    from jevops.outer import reject_present_keys, require_exact_keys

    if isinstance(value, ExecutablePaths):
        paths = value.to_dict()
    elif isinstance(value, Mapping):
        reject_present_keys(
            value,
            ("primary_executable",),
            error_cls=ReceiptStoreError,
            fmt="executable_paths must not include {key}",
            empty=(),
        )
        paths = {str(key): str(item) for key, item in value.items()}
    else:
        raise ReceiptStoreError("executable_paths must be a mapping of lean and lake")
    got = require_exact_keys(
        paths,
        ("lean", "lake"),
        error_cls=ReceiptStoreError,
        not_map="executable_paths must be a mapping of lean and lake",
        extra_fmt="executable_paths must be exactly lean and lake",
        miss_fmt="executable_paths must be exactly lean and lake",
        empty_fmt="executable_paths lean and lake must be nonempty",
    )
    return ExecutablePaths(lean=got["lean"], lake=got["lake"])


def assumptions_digest(
    *,
    max_heartbeats: int = MEASUREMENT_MAX_HEARTBEATS,
    lean_num_threads: int = LEAN_NUM_THREADS,
    no_new_axioms: bool = NO_NEW_AXIOMS,
) -> str:
    return content_digest(
        {
            "lean_num_threads": lean_num_threads,
            "maxHeartbeats": max_heartbeats,
            "no_new_axioms": no_new_axioms,
        }
    )


def project_dimensions(receipt: ProofReceipt) -> dict[str, str]:
    """Project every closed authority dimension. Missing keys fail closed."""

    from jevops.lean import project_authority_dimensions

    premises = receipt.premises_digest or not_applicable_digest()
    backend_config = receipt.backend_config_digest or not_applicable_digest()
    mapping = {
        "ir": DEFAULT_IR,
        "property": DEFAULT_PROPERTY,
        "assumptions": assumptions_digest(),
        "premises": premises,
        "translator": receipt.translator,
        "solver": receipt.generator,
        "toolchain": receipt.lean_tag,
        "theorem_registry": receipt.name,
        "policy": receipt.policy,
        "resource": receipt.resource,
        "tree": receipt.git_commit,
        "backend_id": receipt.backend_id,
        "backend_binary": receipt.executable_paths.lean,
        "backend_version": receipt.lean_version,
        "backend_config": backend_config,
    }
    return project_authority_dimensions(
        receipt, PROOF_AUTHORITY_DIMENSIONS, mapping, error_cls=DimensionError
    )


def receipt_key_digest(receipt: ProofReceipt, dimensions: Mapping[str, str]) -> str:
    return content_digest(
        {
            "body_digest": receipt.body_digest,
            "dimensions": dict(dimensions),
            "lean_tag": receipt.lean_tag,
            "name": receipt.name,
            "schema": RECEIPT_SCHEMA,
        }
    )


def _reject_proof_bodies(payload: Mapping[str, Any]) -> None:
    from jevops.outer import reject_present_keys

    reject_present_keys(
        payload,
        PROOF_BODY_KEYS,
        error_cls=ReceiptStoreError,
        fmt="proof body field {key!r} is not stored in receipt rows",
    )


def _tiny_payload(payload: Mapping[str, Any]) -> str:
    from jevops.outer import dump_tiny

    return dump_tiny(
        payload,
        max_bytes=MAX_ROW_BYTES,
        error_cls=ReceiptStoreError,
        fmt="receipt row {n} bytes exceeds tiny-row cap {max_bytes}",
    )


def sanitize_name(name: str) -> str:
    from jevops.outer import sanitize_ident

    return sanitize_ident(name, error_cls=ReceiptStoreError, empty="theorem name sanitizes empty")


def write_cas_body(root: Path, body: str) -> str:
    from jevops.outer import write_cas

    return write_cas(root, body.encode("utf-8"), prefix="artifacts", filename="candidate.lean")


def filesystem_receipt_path(root: Path, name: str, lean_tag: str) -> Path:
    from jevops.outer import join_under

    return join_under(root, "receipts", sanitize_name(name), f"{lean_tag}.json")


def write_filesystem_receipt(root: Path, receipt: ProofReceipt) -> Path:
    from jevops.outer import write_json

    path = filesystem_receipt_path(root, receipt.name, receipt.lean_tag)
    payload = receipt.to_public_dict()
    _reject_proof_bodies(payload)
    write_json(path, payload)
    return path


def try_import_duckdb() -> Any:
    from jevops.outer import try_import

    return try_import("duckdb")


def _guard_sql(sql: str) -> str:
    from jevops.outer import guard_sql

    return guard_sql(
        sql,
        allowed_head=ALLOWED_SQL_HEAD,
        forbidden=FORBIDDEN_SQL,
        error_cls=InsertOnlyError,
        empty="empty SQL",
        forbidden_fmt="forbidden mutating SQL: {sql}",
        outside_fmt="SQL outside INSERT/SELECT/CREATE TABLE IF NOT EXISTS: {sql}",
    )


from jevops.outer import InsertOnlyConnection as _KernelInsertOnly


class InsertOnlyConnection(_KernelInsertOnly):
    """Wrap a DuckDB or sqlite3 connection. Only INSERT/SELECT/CREATE IF NOT EXISTS."""

    def __init__(self, raw: Any) -> None:
        super().__init__(raw, guard_fn=_guard_sql)


def connect_optional_db(path: Path, *, duckdb_module: Any = None) -> tuple[InsertOnlyConnection, str]:
    """Open DuckDB when the package exists; otherwise sqlite3 (still INSERT-only)."""

    from jevops.outer import connect_engine

    raw, engine = connect_engine(path, duckdb_module=duckdb_module)
    return InsertOnlyConnection(raw), engine


def install_schema(conn: InsertOnlyConnection) -> None:
    conn.execute(RECEIPT_DDL)
    conn.execute(EDGE_DDL)


def _integrity_conflict(exc: BaseException) -> bool:
    from jevops.outer import integrity_conflict

    return integrity_conflict(exc)


def insert_receipt_row(conn: InsertOnlyConnection, receipt: ProofReceipt) -> bool:
    """INSERT one tiny row. Existing key is skipped; never DELETE/UPDATE."""

    from jevops.outer import dumps_compact, insert_ignore_conflict, pack_receipt_insert_params

    params = pack_receipt_insert_params(
        receipt,
        schema=RECEIPT_SCHEMA,
        dumps_fn=dumps_compact,
        tiny_fn=_tiny_payload,
    )
    return insert_ignore_conflict(
        conn.execute,
        INSERT_RECEIPT_SQL,
        params,
        error_cls=ReceiptStoreError,
        fail_fmt="INSERT receipt failed: {exc}",
    )


def insert_edge(
    conn: InsertOnlyConnection,
    parent_digest: str,
    child_digest: str,
    edge_kind: str = "candidate",
    *,
    created_at: Optional[float] = None,
) -> bool:
    """INSERT an edge. Existing edges stay; there is no DELETE."""

    from jevops.outer import insert_ignore_conflict

    stamp = time.time() if created_at is None else float(created_at)
    return insert_ignore_conflict(
        conn.execute,
        INSERT_EDGE_SQL,
        (parent_digest, child_digest, edge_kind, stamp),
        error_cls=ReceiptStoreError,
        fail_fmt="INSERT edge failed: {exc}",
    )


def select_edges(conn: InsertOnlyConnection, parent_digest: str) -> list[tuple[str, str, str]]:
    from jevops.outer import fetch_mapped

    result = conn.execute(SELECT_EDGE_SQL, (parent_digest,))
    return fetch_mapped(result, lambda row: (str(row[0]), str(row[1]), str(row[2])))


def lookup_receipt(conn: InsertOnlyConnection, key_digest: str) -> Optional[dict[str, Any]]:
    from jevops.outer import row_dict

    result = conn.execute(SELECT_RECEIPT_SQL, (key_digest,))
    return row_dict(
        result.fetchone(),
        (
            "key_digest",
            "theorem_name",
            "lean_tag",
            "body_digest",
            "candidate_cid",
            "verdict",
            "token_count",
            "elab_proxy",
            "dimensions_json",
            "executable_paths_json",
            "payload_json",
            "created_at",
        ),
    )


def lookup_negative(
    conn: InsertOnlyConnection,
    theorem_name: str,
    body_digest: str,
    lean_tag: str,
) -> Optional[str]:
    """Return the stored verdict for a failed (theorem, body, toolchain)."""

    from jevops.outer import row_cell

    result = conn.execute(SELECT_NEGATIVE_SQL, (theorem_name, body_digest, lean_tag))
    value = row_cell(result.fetchone(), 1)
    return None if value is None else str(value)


def should_skip_retry(verdict: Optional[str]) -> bool:
    return verdict in {"fail", "error"}


def finalize_receipt(receipt: ProofReceipt, *, body: Optional[str] = None) -> ProofReceipt:
    if receipt.executable_paths is None:
        raise ReceiptStoreError("executable_paths required")
    from jevops.outer import ensure_digest

    receipt.body_digest = ensure_digest(
        receipt.body_digest,
        data=body.encode("utf-8") if body is not None else None,
        digest_fn=sha256_bytes,
        error_cls=ReceiptStoreError,
        empty="body_digest must be sha256 hex",
    )
    if not receipt.candidate_cid:
        receipt.candidate_cid = receipt.body_digest
    receipt.created_at = receipt.created_at or time.time()
    receipt.dimensions = project_dimensions(receipt)
    receipt.key_digest = receipt_key_digest(receipt, receipt.dimensions)
    return receipt


def store_receipt(
    receipt: ProofReceipt,
    *,
    root: Path,
    body: Optional[str] = None,
    duckdb_path: Optional[Path] = None,
    parent_digest: Optional[str] = None,
    require_duckdb: bool = False,
    duckdb_module: Any = None,
) -> ProofReceipt:
    """Write the filesystem receipt, then optionally INSERT a tiny DuckDB row.

    DuckDB is skipped when the package is absent unless ``require_duckdb``.
    Filesystem remains authority either way. ``run_warmup.py`` is still the
    control plane; this function does not schedule work.
    """

    from jevops.lean import persist_receipt

    return persist_receipt(
        receipt,
        root=root,
        body=body,
        duckdb_path=duckdb_path,
        parent_digest=parent_digest,
        require_duckdb=require_duckdb,
        control_plane=IS_CONTROL_PLANE or REQUIRES_TODO_DAEMON,
        finalize_fn=finalize_receipt,
        write_cas_fn=write_cas_body,
        write_fs_fn=write_filesystem_receipt,
        connect_fn=lambda path, module: connect_optional_db(path, duckdb_module=module),
        install_fn=install_schema,
        insert_fn=insert_receipt_row,
        insert_edge_fn=insert_edge,
        try_import_fn=lambda: duckdb_module if duckdb_module is not None else try_import_duckdb(),
        error_cls=ReceiptStoreError,
        control_msg="receipt_store must not be the control plane",
    )


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _call_func_names(source: str) -> set[str]:
    from jevops.repair import call_func_names

    return call_func_names(source)


def _keyword_names(source: str) -> set[str]:
    from jevops.repair import keyword_names

    return keyword_names(source)


def _string_constants(source: str) -> list[str]:
    from jevops.repair import string_constants

    return string_constants(source)


def _function_names(source: str) -> set[str]:
    from jevops.repair import function_names

    return function_names(source)


def _forbidden_sql_in_constants(source: str) -> list[str]:
    """Flag string constants that are mutating SQL statements, not prose."""

    from jevops.outer import head_chars

    issues: list[str] = []
    for value in _string_constants(source):
        stripped = value.strip()
        if SQL_STATEMENT_HEAD.match(stripped) or (
            ALLOWED_SQL_HEAD.match(stripped) and FORBIDDEN_SQL.search(stripped)
        ):
            issues.append(head_chars(stripped, 80))
    return issues


def _primary_executable_kwargs(source: str) -> bool:
    return "primary_executable" in _keyword_names(source)


def _synthetic_receipt(
    *,
    name: str = "CallElimCorrect.substOldPostSubset",
    lean_tag: str = "v4.26.0",
    verdict: str = "fail",
    body: str = "rfl",
    premises_digest: str = "",
    git_commit: str = "451e5f047bafa010d178856db76c00029bfa4d7f",
) -> tuple[ProofReceipt, str]:
    digest = sha256_bytes(body.encode("utf-8"))
    receipt = ProofReceipt(
        name=name,
        lean_tag=lean_tag,
        body_digest=digest,
        verdict=verdict,
        executable_paths=ExecutablePaths(
            lean=f"/elan/toolchains/leanprover--lean4---{lean_tag}/bin/lean",
            lake=f"/elan/toolchains/leanprover--lean4---{lean_tag}/bin/lake",
        ),
        premises_digest=premises_digest,
        git_commit=git_commit,
        lean_version=lean_tag,
        token_count=1,
        elab_proxy=None,
    )
    return receipt, body


def _load_control_plane_pin() -> dict[str, Any]:
    from jevops.outer import read_json

    cfg = read_json(SUPERVISOR_JSON)
    return {
        "primary_control_plane": cfg.get("primary_control_plane"),
        "matches_constant": cfg.get("primary_control_plane") == CONTROL_PLANE,
        "run_warmup_exists": (REPO_ROOT / CONTROL_PLANE).is_file(),
        "receipt_store_is_control_plane": IS_CONTROL_PLANE,
        "requires_todo_daemon": REQUIRES_TODO_DAEMON,
        "requires_duckdb": REQUIRES_DUCKDB,
        "filesystem_is_authority": FILESYSTEM_IS_AUTHORITY,
        "insert_only": INSERT_ONLY,
    }


def self_check(path: Optional[Path] = None) -> dict[str, Any]:
    """Exercise filesystem authority, INSERT-only SQL, and closed dimensions."""

    from jevops.outer import read_text

    source = read_text(__file__)
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    before = sha256_file(jsonl)
    raw, digest, records = load_warmup_records(jsonl)
    after = sha256_file(jsonl)
    first = records[0]
    retrieval = lra_retrieve.retrieve_record(first, records)
    closed_src = closed_dimensions_from_source()
    lock_fields = environment_lock_field_names()
    imported = _imported_names(source)
    forbidden_imports = sorted(name for name in imported if name in FORBIDDEN_IMPORT_NAMES)
    call_names = _call_func_names(source)
    forbidden_calls = sorted(name for name in call_names if name in FORBIDDEN_CALL_NAMES)
    sql_issues = _forbidden_sql_in_constants(source)
    fn_names = _function_names(source)
    control = _load_control_plane_pin()
    duckdb_module = try_import_duckdb()
    duckdb_available = duckdb_module is not None

    dropped_error = ""
    try:
        bad = ProofReceipt(
            name="x",
            lean_tag="v4.26.0",
            body_digest="0" * 64,
            verdict="fail",
            executable_paths=ExecutablePaths(lean="/lean", lake="/lake"),
        )
        mapping = project_dimensions(bad)
        mapping.pop("assumptions")
        missing = PROOF_AUTHORITY_DIMENSION_SET - set(mapping)
        if missing:
            raise DimensionError(f"authority dimension(s) dropped: {', '.join(sorted(missing))}")
    except DimensionError as exc:
        dropped_error = str(exc)

    primary_rejected = False
    try:
        parse_executable_paths({"lean": "/lean", "lake": "/lake", "primary_executable": "/lean"})
    except ReceiptStoreError:
        primary_rejected = True

    huge_rejected = False
    try:
        _tiny_payload({"src": "x" * (MAX_ROW_BYTES + 1)})
    except ReceiptStoreError:
        huge_rejected = True

    body_rejected = False
    try:
        _reject_proof_bodies({"src": "theorem T : True := by rfl"})
    except ReceiptStoreError:
        body_rejected = True

    delete_sql_rejected = False
    try:
        _guard_sql("DELETE" + " FROM lra_proof_edges WHERE parent_digest = 'x'")
    except InsertOnlyError:
        delete_sql_rejected = True

    update_sql_rejected = False
    try:
        _guard_sql("UPDATE" + " lra_proof_receipts SET verdict = 'pass'")
    except InsertOnlyError:
        update_sql_rejected = True

    upsert_sql_rejected = False
    try:
        _guard_sql("INSERT" + " OR REPLACE INTO lra_proof_receipts (key_digest) VALUES ('x')")
    except InsertOnlyError:
        upsert_sql_rejected = True

    from jevops.outer import temp_dir

    with temp_dir(prefix="lra-023-receipt-") as tmp:
        root = Path(tmp)
        db_path = root / "receipts.duckdb"
        receipt, body = _synthetic_receipt(premises_digest=retrieval.lemma_id_digest)
        stored = store_receipt(
            receipt,
            root=root,
            body=body,
            duckdb_path=db_path,
            parent_digest=content_digest({"problem": receipt.name}),
            require_duckdb=False,
            duckdb_module=duckdb_module,
        )
        fs_path = Path(stored.filesystem_path)
        from jevops.outer import read_json

        fs_payload = read_json(fs_path)
        cas_path = root / "artifacts" / stored.candidate_cid[:2] / stored.candidate_cid / "candidate.lean"
        conn, engine = connect_optional_db(db_path, duckdb_module=duckdb_module)
        try:
            install_schema(conn)
            parent = content_digest({"problem": stored.name})
            first_edge = insert_edge(conn, parent, stored.key_digest, "candidate")
            second_child = content_digest({"other": stored.name, "n": 2})
            second_edge = insert_edge(conn, parent, second_child, "candidate")
            dup_edge = insert_edge(conn, parent, stored.key_digest, "candidate")
            edges = select_edges(conn, parent)
            row = lookup_receipt(conn, stored.key_digest)
            negative = lookup_negative(conn, stored.name, stored.body_digest, stored.lean_tag)
            count_receipts = conn.execute(SELECT_COUNT_RECEIPTS_SQL).fetchone()[0]
            count_edges = conn.execute(SELECT_COUNT_EDGES_SQL).fetchone()[0]
            commit = getattr(conn._raw, "commit", None)
            if callable(commit):
                commit()
        finally:
            conn.close()
        fs_exists = fs_path.is_file()
        cas_exists = cas_path.is_file()
        cas_bytes = cas_path.stat().st_size if cas_exists else 0
        stored_again = store_receipt(
            ProofReceipt(
                name=stored.name,
                lean_tag=stored.lean_tag,
                body_digest=stored.body_digest,
                verdict=stored.verdict,
                executable_paths=stored.executable_paths,
                premises_digest=stored.premises_digest,
                git_commit=stored.git_commit,
                lean_version=stored.lean_version,
                token_count=stored.token_count,
            ),
            root=root,
            body=body,
            duckdb_path=db_path,
            parent_digest=parent,
            duckdb_module=duckdb_module,
        )
        conn, _ = connect_optional_db(db_path, duckdb_module=duckdb_module)
        try:
            edges_after = select_edges(conn, parent)
            row_after = lookup_receipt(conn, stored.key_digest)
            count_edges_after = conn.execute(SELECT_COUNT_EDGES_SQL).fetchone()[0]
            payload_after = str(row_after["payload_json"] if row_after else "")
        finally:
            conn.close()

    dim_keys = list(stored.dimensions)
    fs_dim_keys = list(fs_payload.get("dimensions") or {})
    from jevops.outer import loads_json

    row_dims = loads_json(row["dimensions_json"] if row else None, default={})
    exec_paths = loads_json(row["executable_paths_json"] if row else None, default={})
    row_payload = loads_json(row["payload_json"] if row else None, default={})
    edge_children = sorted(item[1] for item in edges)
    expected_children = sorted({stored.key_digest, second_child})

    report = {
        "ok": True,
        "schema": STORE_SCHEMA,
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "lrah": LRAH_ID,
        "n_records": len(records),
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": before == after == FROZEN_WARMUP_SHA256,
        "proof_authority_dimensions": list(PROOF_AUTHORITY_DIMENSIONS),
        "proof_authority_dimensions_source": list(closed_src),
        "dimensions_match_duckdb_proof_store": tuple(closed_src) == PROOF_AUTHORITY_DIMENSIONS,
        "all_dimensions_populated": dim_keys == list(PROOF_AUTHORITY_DIMENSIONS)
        and set(dim_keys) == PROOF_AUTHORITY_DIMENSION_SET
        and set(fs_dim_keys) == PROOF_AUTHORITY_DIMENSION_SET
        and set(row_dims) == PROOF_AUTHORITY_DIMENSION_SET,
        "dropped_dimension_fail_closed": "assumptions" in dropped_error,
        "environment_lock_fields": lock_fields,
        "environment_lock_has_executable_paths": "executable_paths" in lock_fields,
        "environment_lock_has_primary_executable": "primary_executable" in lock_fields,
        "primary_executable_kwarg": _primary_executable_kwargs(source),
        "primary_executable_payload_rejected": primary_rejected,
        "lock_executable_paths": stored.executable_paths.to_dict(),
        "row_executable_paths": exec_paths,
        "filesystem_authority": FILESYSTEM_IS_AUTHORITY,
        "filesystem_receipt_exists": fs_exists,
        "cas_body_exists": cas_exists,
        "cas_body_bytes": cas_bytes,
        "filesystem_has_src": "src" in fs_payload,
        "row_has_src": "src" in row_payload,
        "row_payload_bytes": len(row["payload_json"].encode("utf-8")) if row else -1,
        "tiny_row": (len(row["payload_json"].encode("utf-8")) if row else MAX_ROW_BYTES + 1) <= MAX_ROW_BYTES,
        "huge_parent_row_rejected": huge_rejected,
        "proof_body_rejected": body_rejected,
        "insert_only": INSERT_ONLY,
        "insert_receipt": stored.inserted or stored.skipped_duplicate,
        "duplicate_skipped": stored_again.skipped_duplicate or not stored_again.inserted,
        "first_edge_insert_or_present": first_edge or stored.key_digest in edge_children,
        "second_edge_inserted": second_edge,
        "duplicate_edge_skipped": dup_edge is False,
        "existing_edges_survived": edge_children == expected_children
        and sorted(item[1] for item in edges_after) == expected_children
        and int(count_edges_after) >= 2,
        "n_edges": int(count_edges),
        "n_receipts": int(count_receipts),
        "no_delete_of_existing_edges": delete_sql_rejected
        and sorted(item[1] for item in edges_after) == expected_children,
        "delete_sql_rejected": delete_sql_rejected,
        "update_sql_rejected": update_sql_rejected,
        "upsert_sql_rejected": upsert_sql_rejected,
        "forbidden_sql_constants": sql_issues,
        "has_delete_method": "delete_edge" in fn_names or "delete_receipt" in fn_names,
        "has_upsert_task": "upsert_task" in fn_names or "upsert_task" in call_names,
        "engine": engine,
        "duckdb_available": duckdb_available,
        "duckdb_used": stored.duckdb_used or engine in {"duckdb", "sqlite3"},
        "requires_duckdb": REQUIRES_DUCKDB,
        "negative_cache_verdict": negative,
        "negative_cache_skips_retry": should_skip_retry(negative),
        "premises_digest": retrieval.lemma_id_digest,
        "premises_from_retrieve": stored.dimensions.get("premises") == retrieval.lemma_id_digest,
        "control_plane": CONTROL_PLANE,
        "control_plane_pin": control,
        "run_warmup_remains_control_plane": control["matches_constant"]
        and control["receipt_store_is_control_plane"] is False
        and control["requires_todo_daemon"] is False,
        "imported_names": sorted(imported),
        "forbidden_imports": forbidden_imports,
        "forbidden_calls": forbidden_calls,
        "uses_fcntl": "fcntl" in imported,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
        "arena_score": None,
        "score": None,
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
        "row_after_duplicate_unchanged": payload_after == (row["payload_json"] if row else None),
        "sample": {
            "name": stored.name,
            "lean_tag": stored.lean_tag,
            "verdict": stored.verdict,
            "key_digest": stored.key_digest,
            "dimensions": stored.dimensions,
            "executable_paths": stored.executable_paths.to_dict(),
        },
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and report["dimensions_match_duckdb_proof_store"]
        and report["all_dimensions_populated"]
        and report["dropped_dimension_fail_closed"]
        and report["environment_lock_has_executable_paths"]
        and not report["environment_lock_has_primary_executable"]
        and not report["primary_executable_kwarg"]
        and report["primary_executable_payload_rejected"]
        and report["filesystem_receipt_exists"]
        and report["cas_body_exists"]
        and not report["filesystem_has_src"]
        and not report["row_has_src"]
        and report["tiny_row"]
        and report["huge_parent_row_rejected"]
        and report["proof_body_rejected"]
        and report["insert_only"]
        and report["existing_edges_survived"]
        and report["no_delete_of_existing_edges"]
        and report["delete_sql_rejected"]
        and report["update_sql_rejected"]
        and report["upsert_sql_rejected"]
        and not report["forbidden_sql_constants"]
        and not report["has_delete_method"]
        and not report["has_upsert_task"]
        and not forbidden_imports
        and not forbidden_calls
        and report["run_warmup_remains_control_plane"]
        and report["negative_cache_skips_retry"]
        and report["premises_from_retrieve"]
        and report["compiled"] is False
        and report["lake"] is False
        and report["arena_score"] is None
        and report["score"] is None
        and not REQUIRES_DUCKDB
        and not IS_CONTROL_PLANE
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="filesystem + INSERT-only audit; no compile")
    parser.add_argument("--store", action="store_true", help="write one tiny receipt (filesystem, optional DuckDB)")
    parser.add_argument("--name", default="CallElimCorrect.substOldPostSubset")
    parser.add_argument("--tag", default="v4.26.0")
    parser.add_argument("--verdict", default="fail", choices=("pass", "fail", "error", "unknown"))
    parser.add_argument("--body", default="rfl", help="proof body written to CAS only")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--duckdb", type=Path, default=None, help="optional DuckDB/sqlite file; omitted = filesystem only")
    parser.add_argument("--require-duckdb", action="store_true")
    parser.add_argument("--jsonl", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.store:
        jsonl = args.jsonl if args.jsonl is not None else WARMUP_JSONL
        _raw, _digest, records = load_warmup_records(jsonl)
        retrieval = lra_retrieve.retrieve_by_name(args.name, records)
        receipt, body = _synthetic_receipt(
            name=args.name,
            lean_tag=args.tag,
            verdict=args.verdict,
            body=args.body,
            premises_digest=retrieval.lemma_id_digest,
        )
        from jevops.outer import mkdtemp

        root = args.out_dir if args.out_dir is not None else mkdtemp(prefix="lra-023-store-")
        stored = store_receipt(
            receipt,
            root=root,
            body=body,
            duckdb_path=args.duckdb,
            parent_digest=content_digest({"problem": args.name}),
            require_duckdb=args.require_duckdb,
        )
        from jevops.outer import print_json

        print_json(stored.to_public_dict())
        return 0
    if args.self_check or argv is None or argv == []:
        from jevops.outer import print_ok

        return print_ok(self_check(args.jsonl))
    parser.error("choose --self-check or --store")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
