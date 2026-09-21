#!/usr/bin/env python3
"""Fail-closed batch verifier for Lean Refactor Arena warm-up receipts.

Dedicated LRA verifier. Does not import law_to_action ``verify_batch.py``.
Does not write Arena scores. ``--require-complete`` is the only process
allowed to declare the warm-up run complete, and it requires:

- frozen JSONL digest
- statement-bind (``candidate.startswith(header+statement)`` / prefix)
- one compile record per listed ``version_info`` tag
- axiom reports with no ``sorryAx``
- one receipt per scheduled problem

Incomplete is not success. This tool does not compile Lean, does not call
Leanstral, and does not emit Track 1/Track 2 rankings.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
HARNESS = PAPER_ROOT / "harness"
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"

if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))
import _jevops_path  # noqa: E402,F401
import splice as lra_splice  # noqa: E402

FROZEN_WARMUP_SHA256 = "6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804"
WARMUP_N = 15
PROTOCOL = "LRA/v1"
PROBLEM_SCHEMA = "lra-problem-receipt/v1"
COMPILE_SCHEMA = "lra-compile-receipt/v1"
BATCH_SCHEMA = "lra-batch-verify/v1"
FREEZE_SCHEMA = "lra-freeze-binding/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SKIP_JSON_NAMES = frozenset(
    {
        "batch.json",
        "freeze_binding.json",
        "problem.json",
        "admission.json",
        "result.json",
    }
)
RESERVED_DIR_NAMES = frozenset({"problems", "validation", "outputs"})
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "law_to_action",
        "verify_batch",
        "fcntl",
        "IndependentKernelVerifier",
        "KernelVerifier",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "driver",
    }
)
FORBIDDEN_IMPORT_NEEDLES = (
    "law_to_action",
    "verify_batch",
    "generated_code_study",
)
FORBIDDEN_SCORE_NAMES = frozenset(
    {
        "arena_score",
        "arena_score_tokens",
        "arena_score_elab",
        "official_track2_score",
        "token_savings",
        "score",
        "relevance_score",
        "official_score",
    }
)
ALL_GATES = (
    "digest",
    "statement_bind",
    "all_tags",
    "no_sorry",
    "complete",
)
EMPTY_AXIOM_DIGEST = hashlib.sha256(b"[]").hexdigest()

if lra_splice.FROZEN_WARMUP_SHA256 != FROZEN_WARMUP_SHA256:
    raise RuntimeError("verify_lra_batch frozen digest drifted from splice.py")
if lra_splice.WARMUP_N != WARMUP_N:
    raise RuntimeError("verify_lra_batch warm-up count drifted from splice.py")


class VerifyError(RuntimeError):
    """Fail-closed batch-verifier error."""


@dataclass
class TagRecord:
    lean_tag: str
    git_commit: str = ""
    sorryAx: bool = False
    axiom_names: list[str] = field(default_factory=list)
    axiom_digest: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    ok: bool = False
    path: str = ""
    arena_score: None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lean_tag": self.lean_tag,
            "git_commit": self.git_commit,
            "sorryAx": self.sorryAx,
            "axiom_names": list(self.axiom_names),
            "axiom_digest": self.axiom_digest,
            "exit_code": self.exit_code,
            "ok": self.ok,
            "path": self.path,
            "arena_score": None,
        }


@dataclass
class ProblemReceipt:
    name: str
    source: str = ""
    header: str = ""
    statement: str = ""
    candidate: str = ""
    warmup_sha256: str = ""
    accepted: Optional[bool] = None
    compile_records: dict[str, TagRecord] = field(default_factory=dict)
    path: str = ""
    arena_score: Any = None
    score: Any = None
    mock: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProblemJudgment:
    name: str
    source: str
    listed_tags: list[str]
    receipt_found: bool
    duplicate: bool
    digest_ok: bool
    statement_bind_ok: bool
    all_tags_ok: bool
    no_sorry_ok: bool
    one_receipt: bool
    arena_score_null: bool
    failures: list[str] = field(default_factory=list)
    tag_records: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "listed_tags": list(self.listed_tags),
            "receipt_found": self.receipt_found,
            "duplicate": self.duplicate,
            "digest_ok": self.digest_ok,
            "statement_bind_ok": self.statement_bind_ok,
            "all_tags_ok": self.all_tags_ok,
            "no_sorry_ok": self.no_sorry_ok,
            "one_receipt": self.one_receipt,
            "arena_score_null": self.arena_score_null,
            "failures": list(self.failures),
            "tag_records": list(self.tag_records),
            "arena_score": None,
            "score": None,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def listed_tags(version_info: Any) -> list[str]:
    """JSONL ``version_info`` order. Never newest-mtime and never PATH lean."""

    tags: list[str] = []
    if not isinstance(version_info, list):
        return tags
    for item in version_info:
        if isinstance(item, dict):
            for tag in item.keys():
                if isinstance(tag, str) and tag.strip() and tag not in tags:
                    tags.append(tag)
        elif isinstance(item, str) and item.strip() and item not in tags:
            tags.append(item)
    return tags


def listed_commits(version_info: Any) -> dict[str, str]:
    commits: dict[str, str] = {}
    if not isinstance(version_info, list):
        return commits
    for item in version_info:
        if not isinstance(item, dict):
            continue
        for tag, commit in item.items():
            if isinstance(tag, str) and tag.strip() and tag not in commits:
                commits[tag] = "" if commit is None else str(commit)
    return commits


def candidate_binds_statement(candidate: str, header: str, statement: str) -> bool:
    """Prefix check. Never scan the statement for the first ``:=``."""

    if not isinstance(candidate, str) or not isinstance(statement, str) or not statement:
        return False
    header_text = header if isinstance(header, str) else ""
    prefixes = [statement, header_text + statement]
    if header_text.strip():
        prefixes.append(header_text.rstrip() + "\n\n" + statement)
        prefixes.append(header_text.rstrip() + "\n" + statement)
    return any(candidate.startswith(prefix) for prefix in prefixes)


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _score_nonnull(payload: Mapping[str, Any], *keys: str) -> list[str]:
    bad: list[str] = []
    for key in keys:
        if key in payload and payload.get(key) is not None:
            bad.append(key)
    return bad


def axiom_report_exists(record: TagRecord) -> bool:
    has_digest = _is_hex64(record.axiom_digest)
    has_names = isinstance(record.axiom_names, list)
    printed = "#print axioms" in (record.stdout or "") or "#print axioms" in (
        record.stderr or ""
    )
    return bool((has_digest or has_names) and (printed or has_digest or has_names))


def has_sorry_ax(record: TagRecord) -> bool:
    names = [str(item) for item in record.axiom_names]
    text = f"{record.stdout}\n{record.stderr}"
    return bool(
        record.sorryAx
        or "sorryAx" in names
        or "sorryAx" in text
        or "hasSorry" in text
    )


def tag_record_from_payload(payload: Mapping[str, Any], *, path: str = "") -> TagRecord:
    names = payload.get("axiom_names")
    if not isinstance(names, list):
        names = []
    return TagRecord(
        lean_tag=str(payload.get("lean_tag") or payload.get("tag") or ""),
        git_commit=str(payload.get("git_commit") or ""),
        sorryAx=bool(payload.get("sorryAx")),
        axiom_names=[str(item) for item in names],
        axiom_digest=str(payload.get("axiom_digest") or ""),
        stdout=str(payload.get("stdout") or payload.get("axiom_report") or ""),
        stderr=str(payload.get("stderr") or ""),
        exit_code=int(payload.get("exit_code") if payload.get("exit_code") is not None else -1),
        ok=bool(payload.get("ok")),
        path=path,
        arena_score=None,
        payload=dict(payload),
    )


def _read_candidate(directory: Path, payload: Mapping[str, Any]) -> str:
    if isinstance(payload.get("candidate"), str) and payload["candidate"]:
        return payload["candidate"]
    for name in ("candidate.lean", "candidate.src", "src.lean"):
        path = directory / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def _compile_records_from_payload(payload: Mapping[str, Any], *, path: str) -> dict[str, TagRecord]:
    records: dict[str, TagRecord] = {}
    raw = payload.get("compile_records")
    items: list[Any]
    if isinstance(raw, dict):
        items = []
        for tag, value in raw.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("lean_tag", tag)
                items.append(row)
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = tag_record_from_payload(item, path=path)
        if record.lean_tag:
            records[record.lean_tag] = record
    return records


def load_tag_files(directory: Path) -> dict[str, TagRecord]:
    records: dict[str, TagRecord] = {}
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        if path.name in SKIP_JSON_NAMES:
            continue
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        schema = str(payload.get("schema") or "")
        if schema not in {"", COMPILE_SCHEMA}:
            if schema.startswith("lra-problem") or schema.startswith("lra-batch"):
                continue
        record = tag_record_from_payload(payload, path=str(path))
        if not record.lean_tag:
            stem = path.stem
            if stem.startswith("v"):
                record.lean_tag = stem
        if record.lean_tag:
            records[record.lean_tag] = record
    tags_dir = directory / "tags"
    if tags_dir.is_dir():
        records.update(load_tag_files(tags_dir))
    return records


def load_problem_from_dir(directory: Path) -> Optional[ProblemReceipt]:
    problem_path = directory / "problem.json"
    payload: dict[str, Any] = {}
    if problem_path.is_file():
        loaded = load_json(problem_path)
        if not isinstance(loaded, dict):
            raise VerifyError(f"{problem_path}: problem.json is not an object")
        payload = loaded
    tag_records = load_tag_files(directory)
    nested = _compile_records_from_payload(payload, path=str(problem_path))
    for tag, record in nested.items():
        if tag in tag_records:
            existing = tag_records[tag]
            if existing.axiom_digest and record.axiom_digest and existing.axiom_digest != record.axiom_digest:
                raise VerifyError(f"{directory}: duplicate compile records for tag {tag}")
        tag_records.setdefault(tag, record)
    name = str(payload.get("name") or directory.name)
    if not name or name in RESERVED_DIR_NAMES:
        if not payload and not tag_records:
            return None
        if not name or name in RESERVED_DIR_NAMES:
            return None
    if not payload and not tag_records and not _read_candidate(directory, {}):
        return None
    accepted = payload.get("accepted")
    return ProblemReceipt(
        name=name,
        source=str(payload.get("source") or ""),
        header=str(payload.get("header") or ""),
        statement=str(payload.get("statement") or ""),
        candidate=_read_candidate(directory, payload),
        warmup_sha256=str(payload.get("warmup_sha256") or payload.get("jsonl_sha256") or ""),
        accepted=None if accepted is None else bool(accepted),
        compile_records=tag_records,
        path=str(directory),
        mock=bool(
            payload.get("mock")
            or payload.get("fixed_program_substituted")
            or payload.get("silent_replay")
        ),
        payload=payload,
    )


def load_problem_from_file(path: Path) -> Optional[ProblemReceipt]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise VerifyError(f"{path}: receipt is not an object")
    schema = str(payload.get("schema") or "")
    if schema == COMPILE_SCHEMA:
        record = tag_record_from_payload(payload, path=str(path))
        name = str(payload.get("name") or path.stem)
        return ProblemReceipt(
            name=name,
            source=str(payload.get("source") or ""),
            compile_records={record.lean_tag: record} if record.lean_tag else {},
            path=str(path),
            payload=payload,
        )
    if schema and schema not in {PROBLEM_SCHEMA, ""}:
        return None
    records = _compile_records_from_payload(payload, path=str(path))
    return ProblemReceipt(
        name=str(payload.get("name") or path.stem),
        source=str(payload.get("source") or ""),
        header=str(payload.get("header") or ""),
        statement=str(payload.get("statement") or ""),
        candidate=str(payload.get("candidate") or ""),
        warmup_sha256=str(payload.get("warmup_sha256") or payload.get("jsonl_sha256") or ""),
        accepted=None if payload.get("accepted") is None else bool(payload.get("accepted")),
        compile_records=records,
        path=str(path),
        mock=bool(
            payload.get("mock")
            or payload.get("fixed_program_substituted")
            or payload.get("silent_replay")
        ),
        payload=payload,
    )


def iter_receipt_roots(receipts_dir: Path) -> list[Path]:
    roots: list[Path] = []
    problems = receipts_dir / "problems"
    if problems.is_dir():
        roots.append(problems)
    roots.append(receipts_dir)
    return roots


def load_problem_receipts(receipts_dir: Path) -> list[ProblemReceipt]:
    if not receipts_dir.is_dir():
        raise VerifyError(f"receipts directory does not exist: {receipts_dir}")
    loaded: list[ProblemReceipt] = []
    seen_dirs: set[Path] = set()
    for root in iter_receipt_roots(receipts_dir):
        resolved_root = root.resolve()
        if resolved_root in seen_dirs:
            continue
        seen_dirs.add(resolved_root)
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                if child.name in RESERVED_DIR_NAMES and child.parent == receipts_dir:
                    continue
                receipt = load_problem_from_dir(child)
                if receipt is not None:
                    loaded.append(receipt)
                continue
            if child.suffix == ".json" and child.name not in SKIP_JSON_NAMES:
                receipt = load_problem_from_file(child)
                if receipt is not None and (receipt.compile_records or receipt.candidate):
                    loaded.append(receipt)
    return loaded


def load_freeze_binding(receipts_dir: Path) -> dict[str, Any]:
    path = receipts_dir / "freeze_binding.json"
    if not path.is_file():
        return {}
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise VerifyError("freeze_binding.json is not an object")
    return payload


def judge_problem(
    record: Mapping[str, Any],
    receipts: Sequence[ProblemReceipt],
    *,
    frozen_digest: str,
) -> ProblemJudgment:
    name = str(record.get("name") or "")
    source = str(record.get("source") or "")
    header = record.get("header") or ""
    if not isinstance(header, str):
        header = ""
    statement = record.get("statement") or ""
    if not isinstance(statement, str):
        statement = ""
    src = record.get("src") or ""
    tags = listed_tags(record.get("version_info"))
    matches = [item for item in receipts if item.name == name]
    judgment = ProblemJudgment(
        name=name,
        source=source,
        listed_tags=list(tags),
        receipt_found=bool(matches),
        duplicate=len(matches) > 1,
        digest_ok=False,
        statement_bind_ok=False,
        all_tags_ok=False,
        no_sorry_ok=False,
        one_receipt=len(matches) == 1,
        arena_score_null=True,
        tag_records=[],
    )
    jsonl_bind = isinstance(src, str) and bool(statement) and src.startswith(statement)
    if not jsonl_bind:
        judgment.failures.append("jsonl src does not start with statement")
    if not matches:
        judgment.failures.append("missing receipt")
        return judgment
    if judgment.duplicate:
        judgment.failures.append("duplicate receipts")
        return judgment
    receipt = matches[0]
    score_keys = _score_nonnull(receipt.payload, *FORBIDDEN_SCORE_NAMES)
    for tag_record in receipt.compile_records.values():
        score_keys.extend(_score_nonnull(tag_record.payload, *FORBIDDEN_SCORE_NAMES))
    score_keys = sorted(set(score_keys))
    judgment.arena_score_null = not score_keys
    if score_keys:
        judgment.failures.append("arena score written: " + ",".join(score_keys))
    if receipt.mock:
        judgment.failures.append("mock/fixed-program/silent-replay receipt")
    digest_ok = True
    if receipt.warmup_sha256:
        digest_ok = receipt.warmup_sha256 == frozen_digest
        if not digest_ok:
            judgment.failures.append("receipt warmup_sha256 mismatch")
    judgment.digest_ok = digest_ok
    receipt_statement = receipt.statement or statement
    receipt_header = receipt.header if receipt.header else header
    if receipt.statement and receipt.statement != statement:
        judgment.failures.append("receipt statement mutated")
        statement_ok = False
    else:
        statement_ok = True
    if receipt.header and receipt.header != header:
        # Allow equivalent trailing whitespace on Putnam headers.
        if receipt.header.rstrip() != header.rstrip():
            judgment.failures.append("receipt header mutated")
            statement_ok = False
    candidate = receipt.candidate
    bind_ok = bool(candidate) and candidate_binds_statement(
        candidate, receipt_header, statement
    )
    if not candidate:
        judgment.failures.append("missing candidate")
    elif not bind_ok:
        judgment.failures.append("candidate does not bind header+statement")
    judgment.statement_bind_ok = bool(jsonl_bind and statement_ok and bind_ok)
    present_tags = [tag for tag in tags if tag in receipt.compile_records]
    extra = [tag for tag in receipt.compile_records if tag not in tags]
    judgment.tag_records = sorted(receipt.compile_records)
    missing_tags = [tag for tag in tags if tag not in receipt.compile_records]
    all_tags_ok = not missing_tags and bool(tags)
    if missing_tags:
        judgment.failures.append("missing tags: " + ",".join(missing_tags))
    if extra:
        # Extra tags are retained evidence; they do not satisfy listed tags.
        pass
    judgment.all_tags_ok = all_tags_ok
    sorry_ok = True
    if not present_tags:
        sorry_ok = False
        if "missing receipt" not in judgment.failures and missing_tags:
            pass
        elif not receipt.compile_records:
            judgment.failures.append("missing axiom reports")
            sorry_ok = False
    for tag in tags:
        record = receipt.compile_records.get(tag)
        if record is None:
            sorry_ok = False
            continue
        if not axiom_report_exists(record):
            sorry_ok = False
            judgment.failures.append(f"{tag}: missing axiom report")
        if has_sorry_ax(record):
            sorry_ok = False
            judgment.failures.append(f"{tag}: sorryAx")
        if record.exit_code not in (0,):
            sorry_ok = False
            judgment.failures.append(f"{tag}: compile exit {record.exit_code}")
        if receipt.accepted is False:
            sorry_ok = False
            if "accepted is false" not in judgment.failures:
                judgment.failures.append("accepted is false")
    judgment.no_sorry_ok = bool(sorry_ok and present_tags and not missing_tags)
    return judgment


def schedule_view(records: Sequence[Mapping[str, Any]], digest: str, nbytes: int) -> dict[str, Any]:
    problems = []
    for record in records:
        problems.append(
            {
                "name": record.get("name"),
                "source": record.get("source"),
                "listed_tags": listed_tags(record.get("version_info")),
                "header_chars": len(record.get("header") or ""),
                "statement_chars": len(record.get("statement") or ""),
                "src_startswith_statement": str(record.get("src") or "").startswith(
                    str(record.get("statement") or "")
                ),
            }
        )
    return {
        "schema": BATCH_SCHEMA,
        "status": "SCHEDULE",
        "protocol": PROTOCOL,
        "n_scheduled": len(records),
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": nbytes,
        "problems": problems,
        "arena_score": None,
        "score": None,
        "writes_arena_scores": False,
        "imports_law_to_action_verify_batch": False,
    }


def verify_batch(
    *,
    jsonl: Path,
    receipts_dir: Path,
    require_digest: bool = False,
    require_statement_bind: bool = False,
    require_all_tags: bool = False,
    require_no_sorry: bool = False,
    require_complete: bool = False,
) -> tuple[int, dict[str, Any], str]:
    """Return (exit_code, payload, fail_message). Exit 2 is fail-closed."""

    gates = set()
    if require_digest:
        gates.add("digest")
    if require_statement_bind:
        gates.add("statement_bind")
    if require_all_tags:
        gates.add("all_tags")
    if require_no_sorry:
        gates.add("no_sorry")
    if require_complete:
        gates.update(ALL_GATES)

    failures: list[str] = []
    try:
        before = sha256_file(jsonl)
        raw, digest, records = lra_splice.load_warmup_records(jsonl)
        after = sha256_file(jsonl)
    except lra_splice.DigestMismatch as exc:
        payload = _fail_payload(["digest"], [str(exc)], n_scheduled=WARMUP_N)
        return 2, payload, str(exc)
    except (OSError, lra_splice.SpliceError, json.JSONDecodeError) as exc:
        payload = _fail_payload(["digest"], [str(exc)], n_scheduled=WARMUP_N)
        return 2, payload, str(exc)

    jsonl_unchanged = before == after == FROZEN_WARMUP_SHA256 == digest
    if not jsonl_unchanged:
        failures.append(
            f"warmup JSONL hash mismatch: {digest} != {FROZEN_WARMUP_SHA256}"
        )
    if len(records) != WARMUP_N:
        failures.append(f"warmup JSONL must contain {WARMUP_N} records, got {len(records)}")

    try:
        receipts = load_problem_receipts(receipts_dir)
        binding = load_freeze_binding(receipts_dir)
    except (OSError, json.JSONDecodeError, VerifyError) as exc:
        payload = _fail_payload(sorted(gates) or ["complete"], [str(exc)], n_scheduled=len(records))
        return 2, payload, str(exc)

    if binding:
        bound = str(binding.get("warmup_sha256") or binding.get("jsonl_sha256") or "")
        if bound and bound != FROZEN_WARMUP_SHA256:
            failures.append("freeze_binding warmup_sha256 mismatch")
        if binding.get("tiny_byte_lm") is True:
            failures.append("tiny-byte-lm freeze")
        score_keys = _score_nonnull(binding, *FORBIDDEN_SCORE_NAMES)
        if score_keys:
            failures.append("freeze_binding writes arena scores")

    scheduled_names = [str(record.get("name") or "") for record in records]
    judgments = [
        judge_problem(record, receipts, frozen_digest=digest) for record in records
    ]
    by_name = {item.name: item for item in judgments}
    extra_names = sorted(
        {item.name for item in receipts if item.name not in by_name}
    )

    missing = [item.name for item in judgments if not item.receipt_found]
    duplicates = [item.name for item in judgments if item.duplicate]
    digest_bad = [item.name for item in judgments if item.receipt_found and not item.digest_ok]
    bind_bad = [item.name for item in judgments if not item.statement_bind_ok]
    tags_bad = [item.name for item in judgments if not item.all_tags_ok]
    sorry_bad = [item.name for item in judgments if not item.no_sorry_ok]
    score_bad = [item.name for item in judgments if not item.arena_score_null]
    one_receipt_ok = not missing and not duplicates and len(judgments) == WARMUP_N

    if missing:
        failures.append("missing receipts: " + ",".join(missing[:8]))
    if duplicates:
        failures.append("duplicate receipts: " + ",".join(duplicates[:8]))
    if digest_bad:
        failures.append("digest bind failed: " + ",".join(digest_bad[:8]))
    if bind_bad:
        failures.append("statement-bind failed: " + ",".join(bind_bad[:8]))
    if tags_bad:
        failures.append("missing listed tags: " + ",".join(tags_bad[:8]))
    if sorry_bad:
        failures.append("sorryAx or missing axiom report: " + ",".join(sorry_bad[:8]))
    if score_bad:
        failures.append("arena scores written: " + ",".join(score_bad[:8]))

    digest_ok = jsonl_unchanged and not digest_bad and "freeze_binding warmup_sha256 mismatch" not in failures
    statement_ok = not bind_bad and not missing
    all_tags_ok = not tags_bad and not missing
    no_sorry_ok = not sorry_bad and not missing
    # Extra receipts for unknown names are retained negatives and do not
    # block completeness of the scheduled 15.
    complete = bool(
        digest_ok
        and statement_ok
        and all_tags_ok
        and no_sorry_ok
        and one_receipt_ok
        and not score_bad
        and len(records) == WARMUP_N
        and not duplicates
    )

    triggered: list[str] = []
    if "digest" in gates and not digest_ok:
        triggered.append("digest")
    if "statement_bind" in gates and not statement_ok:
        triggered.append("statement_bind")
    if "all_tags" in gates and not all_tags_ok:
        triggered.append("all_tags")
    if "no_sorry" in gates and not no_sorry_ok:
        triggered.append("no_sorry")
    if "complete" in gates and not complete:
        triggered.append("complete")

    status = "PASS" if complete else ("FAIL" if triggered or (gates and failures) else "INCOMPLETE")
    if triggered:
        status = "FAIL"
    payload = {
        "schema": BATCH_SCHEMA,
        "status": status,
        "protocol": PROTOCOL,
        "n_scheduled": len(records),
        "n_receipts": len({item.name for item in receipts}),
        "scheduled_names": scheduled_names,
        "missing_receipts": missing,
        "duplicate_receipts": duplicates,
        "digest_ok": digest_ok,
        "statement_bind_ok": statement_ok,
        "all_tags_ok": all_tags_ok,
        "no_sorryAx": no_sorry_ok,
        "one_receipt_per_scheduled_problem": one_receipt_ok,
        "complete": complete,
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": jsonl_unchanged,
        "gates": sorted(gates),
        "triggered_gates": triggered,
        "failures": failures,
        "problems": [item.to_dict() for item in judgments],
        "extra_receipt_names": extra_names,
        "arena_score": None,
        "score": None,
        "writes_arena_scores": False,
        "imports_law_to_action_verify_batch": False,
        "tiny_byte_lm": False,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
    }
    message = failures[0] if failures else ("batch is not complete" if not complete else "")
    if status == "FAIL":
        return 2, payload, message or "batch is not complete"
    return 0, payload, ""


def _fail_payload(gates: Sequence[str], failures: Sequence[str], *, n_scheduled: int) -> dict[str, Any]:
    return {
        "schema": BATCH_SCHEMA,
        "status": "FAIL",
        "protocol": PROTOCOL,
        "n_scheduled": n_scheduled,
        "digest_ok": False,
        "statement_bind_ok": False,
        "all_tags_ok": False,
        "no_sorryAx": False,
        "one_receipt_per_scheduled_problem": False,
        "complete": False,
        "gates": list(gates),
        "failures": list(failures),
        "arena_score": None,
        "score": None,
        "writes_arena_scores": False,
        "imports_law_to_action_verify_batch": False,
    }


def compact_candidate(record: Mapping[str, Any]) -> str:
    split = lra_splice.split_statement_body(record)
    return lra_splice.lake_candidate_source(
        header=split.header,
        statement=split.statement,
        tactic_block="rfl",
    )


def compact_tag_payload(record: Mapping[str, Any], tag: str, commit: str) -> dict[str, Any]:
    name = str(record.get("name") or "")
    decl = name.rsplit(".", 1)[-1].replace("'", "") or "lra_candidate"
    stdout = (
        json.dumps({"severity": "information", "data": "ok", "pos": {"line": 1, "column": 0}})
        + f"\n#print axioms {decl}\n{decl} : []\n"
    )
    return {
        "schema": COMPILE_SCHEMA,
        "name": name,
        "source": record.get("source"),
        "lean_tag": tag,
        "git_commit": commit,
        "sorryAx": False,
        "axiom_names": [],
        "axiom_digest": EMPTY_AXIOM_DIGEST,
        "stdout": stdout,
        "stderr": "",
        "exit_code": 0,
        "ok": True,
        "arena_score": None,
        "score": None,
        "hardware_class": "synthetic-verify",
    }


def write_problem_fixture(
    dest: Path,
    record: Mapping[str, Any],
    *,
    digest: str,
    drop_tags: Sequence[str] = (),
    mutate_candidate: Optional[str] = None,
    sorry_tags: Sequence[str] = (),
    injected_score: Any = None,
    warmup_sha256: Optional[str] = None,
    accepted: bool = True,
    statement: Optional[str] = None,
) -> Path:
    name = str(record.get("name") or "")
    directory = dest / name
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tags = listed_tags(record.get("version_info"))
    commits = listed_commits(record.get("version_info"))
    compile_records = []
    skip = set(drop_tags)
    sorry = set(sorry_tags)
    for tag in tags:
        if tag in skip:
            continue
        payload = compact_tag_payload(record, tag, commits.get(tag, ""))
        if tag in sorry:
            payload["sorryAx"] = True
            payload["axiom_names"] = ["sorryAx"]
            payload["axiom_digest"] = sha256_text(json.dumps(["sorryAx"], separators=(",", ":")))
            payload["stdout"] = payload["stdout"].replace(" : []", " : sorryAx")
            payload["ok"] = False
            payload["exit_code"] = 1
        compile_records.append(payload)
        (directory / f"{tag}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    header = record.get("header") or ""
    frozen_statement = record.get("statement") or ""
    used_statement = frozen_statement if statement is None else statement
    candidate = mutate_candidate if mutate_candidate is not None else compact_candidate(record)
    if statement is not None:
        candidate = lra_splice.lake_candidate_source(
            header=header if isinstance(header, str) else "",
            statement=used_statement,
            tactic_block="rfl",
        )
    problem = {
        "schema": PROBLEM_SCHEMA,
        "name": name,
        "source": record.get("source"),
        "header": header,
        "statement": used_statement,
        "candidate": candidate,
        "warmup_sha256": digest if warmup_sha256 is None else warmup_sha256,
        "accepted": accepted,
        "compile_records": compile_records,
        "arena_score": None,
        "score": None,
        "generator": "deterministic",
        "hardware_class": "synthetic-verify",
    }
    if injected_score is not None:
        problem["arena_score"] = injected_score
    (directory / "problem.json").write_text(
        json.dumps(problem, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / "candidate.lean").write_text(candidate, encoding="utf-8")
    return directory


def write_complete_fixture(
    dest: Path,
    records: Sequence[Mapping[str, Any]],
    *,
    digest: str,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    binding = {
        "schema": FREEZE_SCHEMA,
        "warmup_sha256": digest,
        "protocol": PROTOCOL,
        "n_problems": len(records),
        "arena_score": None,
        "score": None,
        "tiny_byte_lm": False,
    }
    (dest / "freeze_binding.json").write_text(
        json.dumps(binding, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for record in records:
        write_problem_fixture(dest, record, digest=digest)


def _copy_fixture(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _imported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".", 1)[0])
                names.add(node.module)
            for alias in node.names:
                names.add(alias.name)
    return names


def _numeric_score_assignments(source: str) -> list[str]:
    tree = ast.parse(source)
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in FORBIDDEN_SCORE_NAMES:
            value = node.value
            if isinstance(value, ast.Constant) and value.value is None:
                continue
            issues.append(f"keyword {node.arg} at line {getattr(node, 'lineno', 0)}")
        if isinstance(node, ast.Assign):
            targets: list[str] = []
            for target in node.targets:
                if isinstance(target, ast.Name):
                    targets.append(target.id)
                elif isinstance(target, ast.Attribute):
                    targets.append(target.attr)
            if any(name in FORBIDDEN_SCORE_NAMES for name in targets):
                value = node.value
                if isinstance(value, ast.Constant) and value.value is None:
                    continue
                issues.append(f"assign {targets} at line {getattr(node, 'lineno', 0)}")
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in FORBIDDEN_SCORE_NAMES:
                value = node.value
                if value is None or (isinstance(value, ast.Constant) and value.value is None):
                    continue
                issues.append(f"ann-assign {node.target.id} at line {getattr(node, 'lineno', 0)}")
    return issues


def audit_source(source: Optional[str] = None) -> dict[str, Any]:
    from jevops.outer import source_text

    text = source_text(source, path=__file__)
    imported = _imported_names(text)
    forbidden = sorted(
        name
        for name in imported
        if name in FORBIDDEN_IMPORT_ROOTS or any(needle == name or needle in name.split(".") for needle in FORBIDDEN_IMPORT_NEEDLES)
    )
    needle_hits = sorted(
        {
            needle
            for needle in FORBIDDEN_IMPORT_NEEDLES
            if any(needle == name or needle in name.split(".") for name in imported)
        }
    )
    # Import audit only. Docstrings may mention the missing law_to_action path.
    score_issues = _numeric_score_assignments(text)
    uses_lock_ex = any(
        isinstance(node, ast.Attribute) and node.attr == "LOCK_EX"
        for node in ast.walk(ast.parse(text))
    )
    path_insert_law = False
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"insert", "append"}:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if "law_to_action" in arg.value or "verify_batch" in arg.value:
                        path_insert_law = True
    return {
        "imported_names": sorted(imported),
        "forbidden_imports": forbidden,
        "forbidden_import_needles": needle_hits,
        "score_assignments": score_issues,
        "uses_lock_ex": uses_lock_ex,
        "sys_path_inserts_law_to_action": path_insert_law,
        "imports_law_to_action_verify_batch": bool(forbidden or needle_hits or path_insert_law),
        "writes_arena_scores": bool(score_issues),
        "ok": (
            not forbidden
            and not needle_hits
            and not score_issues
            and not uses_lock_ex
            and not path_insert_law
        ),
    }


def _run_verify(
    receipts_dir: Path,
    jsonl: Path,
    **flags: bool,
) -> tuple[int, dict[str, Any], str]:
    return verify_batch(jsonl=jsonl, receipts_dir=receipts_dir, **flags)


def _cli_verify(receipts_dir: Path, jsonl: Path, extra: Sequence[str]) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--jsonl",
            str(jsonl),
            "--receipts-dir",
            str(receipts_dir),
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = proc.stdout or ""
    payload: dict[str, Any] = {}
    json_text = stdout
    if stdout.startswith("FAIL:"):
        newline = stdout.find("\n")
        json_text = stdout[newline + 1 :] if newline >= 0 else ""
    json_text = json_text.strip()
    if json_text.startswith("{"):
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError:
            payload = {}
    return {
        "exit_code": proc.returncode,
        "stdout_head": stdout[:400],
        "stderr_head": (proc.stderr or "")[:200],
        "fail_line": stdout.splitlines()[0] if stdout.startswith("FAIL:") else "",
        "status": payload.get("status"),
        "arena_score": payload.get("arena_score"),
        "complete": payload.get("complete"),
        "imports_law_to_action_verify_batch": payload.get("imports_law_to_action_verify_batch"),
        "writes_arena_scores": payload.get("writes_arena_scores"),
    }


def self_check(path: Optional[Path] = None) -> dict[str, Any]:
    """Prove fail-closed gates on compact synthetic receipts. No lake compile."""

    from jevops.outer import read_text

    source = read_text(__file__)
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    before = sha256_file(jsonl)
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    after = sha256_file(jsonl)
    audit = audit_source(source)
    multi = next(record for record in records if len(listed_tags(record.get("version_info"))) > 1)
    putnam = next(record for record in records if record.get("source") == "putnambench")
    first = records[0]

    fail_closed: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="lra-015-verify-") as tmp:
        tmp_path = Path(tmp)
        complete_dir = tmp_path / "complete"
        write_complete_fixture(complete_dir, records, digest=digest)
        code, payload, message = _run_verify(
            complete_dir,
            jsonl,
            require_digest=True,
            require_statement_bind=True,
            require_all_tags=True,
            require_no_sorry=True,
            require_complete=True,
        )
        complete_ok = (
            code == 0
            and payload.get("status") == "PASS"
            and payload.get("complete") is True
            and payload.get("n_scheduled") == WARMUP_N
            and payload.get("one_receipt_per_scheduled_problem") is True
            and payload.get("digest_ok") is True
            and payload.get("statement_bind_ok") is True
            and payload.get("all_tags_ok") is True
            and payload.get("no_sorryAx") is True
            and payload.get("arena_score") is None
            and payload.get("writes_arena_scores") is False
            and payload.get("imports_law_to_action_verify_batch") is False
        )
        fail_closed["complete"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "complete": payload.get("complete"),
            "message": message,
            "ok": complete_ok,
        }
        cli = _cli_verify(
            complete_dir,
            jsonl,
            [
                "--require-complete",
                "--require-digest",
                "--require-statement-bind",
                "--require-all-tags",
                "--require-no-sorry",
            ],
        )
        fail_closed["complete_cli"] = cli
        fail_closed["complete_cli"]["ok"] = (
            cli["exit_code"] == 0
            and cli["status"] == "PASS"
            and cli["arena_score"] is None
            and cli["imports_law_to_action_verify_batch"] is False
        )

        missing_dir = tmp_path / "missing"
        _copy_fixture(complete_dir, missing_dir)
        shutil.rmtree(missing_dir / first["name"])
        code, payload, message = _run_verify(missing_dir, jsonl, require_complete=True)
        fail_closed["missing_receipt"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "missing": payload.get("missing_receipts"),
            "message": message,
            "ok": code == 2 and first["name"] in (payload.get("missing_receipts") or []) and payload.get("complete") is False,
        }

        digest_dir = tmp_path / "digest"
        _copy_fixture(complete_dir, digest_dir)
        write_problem_fixture(
            digest_dir,
            first,
            digest=digest,
            warmup_sha256="0" * 64,
        )
        binding = load_json(digest_dir / "freeze_binding.json")
        binding["warmup_sha256"] = "0" * 64
        (digest_dir / "freeze_binding.json").write_text(
            json.dumps(binding, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        code, payload, message = _run_verify(digest_dir, jsonl, require_digest=True, require_complete=True)
        fail_closed["digest_mismatch"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "digest_ok": payload.get("digest_ok"),
            "message": message,
            "ok": code == 2 and payload.get("digest_ok") is False,
        }

        bind_dir = tmp_path / "bind"
        _copy_fixture(complete_dir, bind_dir)
        evil = "axiom evil : True\n\n" + compact_candidate(first)
        write_problem_fixture(bind_dir, first, digest=digest, mutate_candidate=evil)
        code, payload, message = _run_verify(bind_dir, jsonl, require_statement_bind=True, require_complete=True)
        fail_closed["statement_unbound"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "statement_bind_ok": payload.get("statement_bind_ok"),
            "message": message,
            "ok": code == 2 and payload.get("statement_bind_ok") is False,
        }

        mutated_dir = tmp_path / "mutated-statement"
        _copy_fixture(complete_dir, mutated_dir)
        write_problem_fixture(
            mutated_dir,
            first,
            digest=digest,
            statement=str(first["statement"]) + " -> True",
        )
        code, payload, message = _run_verify(
            mutated_dir, jsonl, require_statement_bind=True, require_complete=True
        )
        fail_closed["statement_mutated"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "statement_bind_ok": payload.get("statement_bind_ok"),
            "ok": code == 2 and payload.get("statement_bind_ok") is False,
        }

        tags_dir = tmp_path / "tags"
        _copy_fixture(complete_dir, tags_dir)
        drop = listed_tags(multi.get("version_info"))[-1]
        write_problem_fixture(tags_dir, multi, digest=digest, drop_tags=(drop,))
        code, payload, message = _run_verify(tags_dir, jsonl, require_all_tags=True, require_complete=True)
        fail_closed["missing_tag"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "all_tags_ok": payload.get("all_tags_ok"),
            "dropped_tag": drop,
            "problem": multi.get("name"),
            "message": message,
            "ok": code == 2 and payload.get("all_tags_ok") is False,
        }

        sorry_dir = tmp_path / "sorry"
        _copy_fixture(complete_dir, sorry_dir)
        sorry_tag = listed_tags(putnam.get("version_info"))[0]
        write_problem_fixture(sorry_dir, putnam, digest=digest, sorry_tags=(sorry_tag,))
        code, payload, message = _run_verify(sorry_dir, jsonl, require_no_sorry=True, require_complete=True)
        fail_closed["sorryAx"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "no_sorryAx": payload.get("no_sorryAx"),
            "problem": putnam.get("name"),
            "tag": sorry_tag,
            "message": message,
            "ok": code == 2 and payload.get("no_sorryAx") is False,
        }

        score_dir = tmp_path / "score"
        _copy_fixture(complete_dir, score_dir)
        write_problem_fixture(score_dir, first, digest=digest, injected_score=0.42)
        code, payload, message = _run_verify(score_dir, jsonl, require_complete=True)
        fail_closed["arena_score_written"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "message": message,
            "ok": code == 2 and payload.get("complete") is False,
        }

        dup_dir = tmp_path / "dup"
        _copy_fixture(complete_dir, dup_dir)
        duplicate = dup_dir / "problems" / first["name"]
        write_problem_fixture(dup_dir / "problems", first, digest=digest)
        code, payload, message = _run_verify(dup_dir, jsonl, require_complete=True)
        fail_closed["duplicate_receipt"] = {
            "exit_code": code,
            "status": payload.get("status"),
            "duplicate": payload.get("duplicate_receipts"),
            "ok": code == 2 and first["name"] in (payload.get("duplicate_receipts") or []),
        }
        del duplicate

        header_ok = candidate_binds_statement(
            compact_candidate(putnam),
            str(putnam.get("header") or ""),
            str(putnam.get("statement") or ""),
        )
        header_concat_ok = candidate_binds_statement(
            str(putnam.get("header") or "") + str(putnam.get("statement") or "") + " := by\nrfl\n",
            str(putnam.get("header") or ""),
            str(putnam.get("statement") or ""),
        )

        lra014 = (
            PAPER_ROOT
            / "receipts"
            / "snapshots"
            / "LRA-014"
            / "outputs"
            / "receipts"
        )
        partial = {}
        if lra014.is_dir():
            code, payload, message = _run_verify(lra014, jsonl, require_complete=True)
            partial = {
                "exit_code": code,
                "status": payload.get("status"),
                "complete": payload.get("complete"),
                "n_receipts": payload.get("n_receipts"),
                "missing_n": len(payload.get("missing_receipts") or []),
                "ok": code == 2 and payload.get("complete") is False,
            }
        fail_closed["lra014_incomplete"] = partial

    named_assign = next(
        record for record in records if record.get("name") == "Cslib.CCS.bisimilarity_congr_choice"
    )
    first_assign = str(named_assign["statement"]).find(":=")
    bind_ignores_first_assign = first_assign != -1 and first_assign < len(named_assign["statement"])

    gates_ok = all(
        fail_closed[key]["ok"]
        for key in (
            "complete",
            "complete_cli",
            "missing_receipt",
            "digest_mismatch",
            "statement_unbound",
            "statement_mutated",
            "missing_tag",
            "sorryAx",
            "arena_score_written",
            "duplicate_receipt",
        )
    )
    report = {
        "ok": False,
        "schema": BATCH_SCHEMA,
        "protocol": PROTOCOL,
        "n_records": len(records),
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": before == after == FROZEN_WARMUP_SHA256,
        "empty_axiom_digest": EMPTY_AXIOM_DIGEST,
        "require_digest": True,
        "require_statement_bind": True,
        "require_all_tags": True,
        "require_no_sorry": True,
        "require_complete": True,
        "one_receipt_per_scheduled_problem": True,
        "header_bind_putnam": header_ok,
        "header_plus_statement_bind": header_concat_ok,
        "named_assign_inside_statement": bind_ignores_first_assign,
        "named_assign_first_assign_byte": first_assign,
        "imports_law_to_action_verify_batch": audit["imports_law_to_action_verify_batch"],
        "writes_arena_scores": audit["writes_arena_scores"],
        "audit": audit,
        "fail_closed": fail_closed,
        "gates_ok": gates_ok,
        "arena_score": None,
        "score": None,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
        "independent_kernel_verifier_used": False,
        "names": [str(record.get("name") or "") for record in records],
        "n_listed_tags": sum(len(listed_tags(record.get("version_info"))) for record in records),
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)) if jsonl.is_relative_to(REPO_ROOT) else str(jsonl),
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and report["header_bind_putnam"]
        and report["header_plus_statement_bind"]
        and report["named_assign_inside_statement"]
        and audit["ok"]
        and not audit["imports_law_to_action_verify_batch"]
        and not audit["writes_arena_scores"]
        and gates_ok
        and (not fail_closed["lra014_incomplete"] or fail_closed["lra014_incomplete"].get("ok"))
        and report["arena_score"] is None
        and report["score"] is None
        and report["compiled"] is False
        and EMPTY_AXIOM_DIGEST == "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )
    return report


def _print_json(payload: Mapping[str, Any]) -> None:
    from jevops.outer import print_json

    print_json(payload)


def _print_fail(message: str, payload: Mapping[str, Any]) -> None:
    sys.stdout.write("FAIL: " + message + "\n")
    _print_json(payload)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="compact synthetic 15-problem fixture plus fail-closed mutations; no lake",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="print the frozen 15-problem schedule; check JSONL digest",
    )
    parser.add_argument(
        "--audit-source",
        action="store_true",
        help="AST-audit imports and Arena-score writes",
    )
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL (default: frozen file)")
    parser.add_argument(
        "--receipts-dir",
        "--results",
        dest="receipts_dir",
        type=Path,
        default=None,
        help="directory of per-problem receipts",
    )
    parser.add_argument("--require-complete", action="store_true", help="every scheduled problem has a receipt; all gates")
    parser.add_argument("--require-digest", action="store_true", help="JSONL SHA-256 matches frozen")
    parser.add_argument("--require-no-sorry", action="store_true", help="axiom reports exist and have no sorryAx")
    parser.add_argument(
        "--require-statement-bind",
        action="store_true",
        help="candidate.startswith(header+statement) / prefix check",
    )
    parser.add_argument("--require-all-tags", action="store_true", help="one compile record per version_info tag")
    args = parser.parse_args(list(argv) if argv is not None else None)
    jsonl = args.jsonl if args.jsonl is not None else WARMUP_JSONL

    if args.self_check or argv is None or argv == []:
        report = self_check(jsonl)
        _print_json(report)
        return 0 if report["ok"] else 1

    if args.audit_source:
        report = audit_source()
        report["arena_score"] = None
        report["score"] = None
        report["imports_law_to_action_verify_batch"] = report["imports_law_to_action_verify_batch"]
        _print_json(report)
        return 0 if report["ok"] else 1

    if args.schedule:
        try:
            raw, digest, records = lra_splice.load_warmup_records(jsonl)
        except (OSError, lra_splice.SpliceError) as exc:
            _print_fail(str(exc), _fail_payload(["digest"], [str(exc)], n_scheduled=WARMUP_N))
            return 2
        _print_json(schedule_view(records, digest, len(raw)))
        return 0

    if args.receipts_dir is None:
        parser.error("choose --self-check, --schedule, --audit-source, or --receipts-dir")
        return 2

    code, payload, message = verify_batch(
        jsonl=jsonl,
        receipts_dir=args.receipts_dir,
        require_digest=args.require_digest,
        require_statement_bind=args.require_statement_bind,
        require_all_tags=args.require_all_tags,
        require_no_sorry=args.require_no_sorry,
        require_complete=args.require_complete,
    )
    if code != 0:
        _print_fail(message or "batch is not complete", payload)
        return code
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
