#!/usr/bin/env python3
"""Validate a Lean Refactor Arena JSONL corpus without running Lean.

The public Arena currently publishes a frozen 15-row warm-up corpus.  This
checker makes that corpus ready for offline optimization and provides the same
schema gate for the future full release.  It never calls a model, downloads a
repository, or labels an arbitrary JSONL file as the official Arena corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
DEFAULT_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"
FROZEN_WARMUP_SHA256 = "6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804"
FROZEN_WARMUP_RECORDS = 15
FULL_BENCHMARK_RELEASE = "2026-11-01"
KNOWN_SOURCES = frozenset({"strata", "physlib", "cslib", "arklib", "putnambench"})
REQUIRED_FIELDS = (
    "name",
    "source",
    "statement",
    "src",
    "proof_length",
    "num_lines",
    "header",
    "file_path",
    "url",
    "version_info",
)


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_record(record: Mapping[str, Any], line_no: int, names: set[str]) -> list[str]:
    errors: list[str] = []
    prefix = f"line {line_no}"
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        errors.append(f"{prefix}: missing fields {','.join(missing)}")

    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{prefix}: name must be a non-empty string")
    elif name in names:
        errors.append(f"{prefix}: duplicate name {name!r}")
    else:
        names.add(name)

    source = record.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(f"{prefix}: source must be a non-empty string")
    elif source not in KNOWN_SOURCES:
        errors.append(f"{prefix}: unknown source {source!r}")

    statement = record.get("statement")
    src = record.get("src")
    if not isinstance(statement, str) or not statement:
        errors.append(f"{prefix}: statement must be a non-empty string")
    if not isinstance(src, str) or not src:
        errors.append(f"{prefix}: src must be a non-empty string")
    elif isinstance(statement, str) and statement and not src.startswith(statement):
        errors.append(f"{prefix}: src does not start with statement")

    if not _is_nonnegative_int(record.get("proof_length")):
        errors.append(f"{prefix}: proof_length must be a non-negative integer")
    if not _is_nonnegative_int(record.get("num_lines")):
        errors.append(f"{prefix}: num_lines must be a non-negative integer")

    for field in ("header", "file_path", "url"):
        if not isinstance(record.get(field), str):
            errors.append(f"{prefix}: {field} must be a string")

    versions = record.get("version_info")
    if not isinstance(versions, list) or not versions:
        errors.append(f"{prefix}: version_info must be a non-empty list")
    else:
        for index, item in enumerate(versions):
            if not isinstance(item, dict) or len(item) != 1:
                errors.append(f"{prefix}: version_info[{index}] must be a one-entry object")
                continue
            version, commit = next(iter(item.items()))
            if not isinstance(version, str) or not version.strip():
                errors.append(f"{prefix}: version_info[{index}] has invalid version")
            if not isinstance(commit, str) or not commit.strip():
                errors.append(f"{prefix}: version_info[{index}] has invalid commit")

    return errors


def inspect_corpus(path: Path, *, require_full: bool = False) -> dict[str, Any]:
    """Return a machine-readable corpus report; never mutates ``path``."""

    path = Path(path)
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {
            "schema": "jevops-lean-refactor-arena-corpus-report/v1",
            "path": str(path),
            "readable": False,
            "optimization_ready": False,
            "errors": [str(exc)],
        }

    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {
            "schema": "jevops-lean-refactor-arena-corpus-report/v1",
            "path": str(path),
            "readable": False,
            "sha256": digest,
            "optimization_ready": False,
            "errors": [f"invalid UTF-8: {exc}"],
        }

    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (TypeError, ValueError) as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_no}: record must be an object")
            continue
        errors.extend(_validate_record(value, line_no, names))
        records.append(value)

    source_counts = dict(sorted(Counter(str(row.get("source", "")) for row in records).items()))
    if not records:
        errors.append("corpus must contain at least one record")
    is_frozen_warmup = len(records) == FROZEN_WARMUP_RECORDS and digest == FROZEN_WARMUP_SHA256
    is_candidate_full = len(records) > FROZEN_WARMUP_RECORDS and not is_frozen_warmup
    if require_full and not is_candidate_full:
        errors.append(
            "full corpus is not available: the supplied file is the public 15-row "
            f"warm-up; announced release is {FULL_BENCHMARK_RELEASE}"
        )

    if is_frozen_warmup:
        kind = "warmup"
    elif is_candidate_full:
        kind = "candidate_full"
    else:
        kind = "unknown"

    return {
        "schema": "jevops-lean-refactor-arena-corpus-report/v1",
        "path": str(path),
        "readable": True,
        "kind": kind,
        "records": len(records),
        "sha256": digest,
        "source_counts": source_counts,
        "unique_names": len(names),
        "optimization_ready": not errors,
        "official_full_corpus": False,
        "full_benchmark_release": FULL_BENCHMARK_RELEASE,
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument(
        "--require-full",
        action="store_true",
        help="fail unless the input has more than the published warm-up rows",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = inspect_corpus(args.jsonl, require_full=args.require_full)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["optimization_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
