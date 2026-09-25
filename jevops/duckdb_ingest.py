"""Bounded, parameterized inserts for the two immutable knowledge builders.

No engine imports, Arrow dependency, extension loading or automatic fallback.
The caller validates semantics and owns the transaction/publication boundary.
"""
from __future__ import annotations

INGESTION_MODES = ("columnar", "executemany")
# Only these internal tables/types may appear in generated SQL. Data never does.
_TYPES = {
    "entries": ("BIGINT", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT", "VARCHAR"),
    "owners": ("VARCHAR", "BIGINT"),
    "dependencies": ("BIGINT", "VARCHAR"),
    "postings": ("BIGINT", "VARCHAR", "INTEGER"),
    "evidence": ("BIGINT", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT"),
    "cid_index": ("BIGINT", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR"),
}
MAX_BATCH_ROWS = 65536  # Includes expanded postings/dependencies, not just premises.


def validate_ingestion_mode(mode: str) -> str:
    if type(mode) is not str or mode not in INGESTION_MODES:
        raise ValueError("ingestion_mode must be columnar or executemany")
    return mode


def insert_batch(connection, table: str, rows: list | tuple, *, mode: str) -> None:
    """Insert one rectangular, bounded batch, without committing or retrying.

    Explicit list casts preserve all-null columns. DuckDB unnests columns side
    by side; validating widths prevents truncation/null-padding of ragged rows.
    Physical file hashes may differ between modes; semantic identities must not.
    """
    validate_ingestion_mode(mode)
    if type(table) is not str or table not in _TYPES:
        raise ValueError("unknown knowledge ingestion table")
    types = _TYPES[table]
    if (type(rows) not in (list, tuple) or len(rows) > MAX_BATCH_ROWS
            or any(type(row) not in (list, tuple) or len(row) != len(types) for row in rows)):
        raise ValueError("bounded rectangular ingestion batch required")
    if not rows:
        return
    if mode == "executemany":
        placeholders = ",".join("?" for _ in types)
        connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    else:
        columns = [list(column) for column in zip(*rows, strict=True)]
        expressions = ",".join(f"unnest(?::{kind}[])" for kind in types)
        connection.execute(f"INSERT INTO {table} SELECT {expressions}", columns)
