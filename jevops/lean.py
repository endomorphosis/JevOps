#!/usr/bin/env python3
"""Lean syntax and lake-compile helpers. Jev does not write Lean.

Lake is the oracle. IndependentKernelVerifier is not. Never docker0.
Not Arena scores. Not Track 2.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

BODY_BY_PREFIXES = (
    " := by \n",
    " := by\n",
    " := by ",
    " := by",
    ":= by \n",
    ":= by\n",
    ":= by",
)
STATEMENT_SORRY_SUFFIX = " := by\nsorry"
FORBIDDEN_PROOF_TOKENS = ("theorem", "lemma", "import", "open")
ASSIGN_NEEDLE = ":" + "="
TOKEN_BOUNDARY = r"(?<![A-Za-z0-9_']){token}(?![A-Za-z0-9_'])"


@dataclass(frozen=True)
class VersionPin:
    lean_tag: str
    git_commit: str

    def to_dict(self) -> dict[str, str]:
        return {"lean_tag": self.lean_tag, "git_commit": self.git_commit}

HEADER_HEARTBEATS = re.compile(r"set_option\s+maxHeartbeats\s+(\d+)")
AXIOM_LINE = re.compile(
    r"^[^\s:]+\s*:\s*(?:\[(?P<bracket>[^\]]*)\]|(?P<bare>.+))\s*$"
)
IKV_DEFAULT_TIMEOUT_SECONDS = 30.0
TOKEN = re.compile(r"[A-Za-z0-9_']+|[^A-Za-z0-9_\s]")


def token_count(text: str) -> int:
    """Frozen local tokenizer. Not the unpublished Arena tokenizer."""

    from jevops.search import count_matches

    return count_matches(text, TOKEN)


def header_max_heartbeats(header: str) -> Optional[int]:
    from jevops.outer import first_group_int

    return first_group_int(header, HEADER_HEARTBEATS)


def require_lake_timeout(
    timeout: float,
    *,
    floor: float = IKV_DEFAULT_TIMEOUT_SECONDS,
    error_cls: type[BaseException] = ValueError,
    too_small_cls: Optional[type[BaseException]] = None,
) -> float:
    """Reject the IndependentKernelVerifier 30 s default as a lake timeout."""

    from jevops.outer import require_positive_above

    return require_positive_above(
        timeout,
        floor,
        error_cls=error_cls,
        too_small_cls=too_small_cls,
        not_positive="lake compile timeout must be a positive number",
        too_small=(
            "lake compile timeout {value}s must exceed IndependentKernelVerifier "
            "default {floor}s; the 30s kernel verifier is not the lake oracle"
        ),
    )


def measurement_argv(
    lake_path: str,
    lean_path: str,
    source_file: str,
    *,
    max_heartbeats: int,
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
    refuse_fmt: str = "refusing to compile {name} as the Putnam module",
) -> list[str]:
    from jevops.outer import pinned_env_argv, require_positive_above

    require_positive_above(
        max_heartbeats,
        0,
        error_cls=error_cls,
        not_positive="measurement maxHeartbeats must be finite and positive",
    )
    return pinned_env_argv(
        lake_path,
        lean_path,
        source_file,
        driver_name="lake",
        tool_name="lean",
        flags=(f"-DmaxHeartbeats={max_heartbeats}", "--json"),
        refuse=refuse,
        error_cls=error_cls,
        refuse_fmt=refuse_fmt,
    )


def axiom_digest(axiom_names: Sequence[str]) -> str:
    from jevops.outer import digest_compact

    return digest_compact(list(axiom_names))


def parse_axioms(stdout: str, stderr: str = "") -> tuple[list[str], bool]:
    """Extract axiom names and sorryAx from lake/lean stdout."""

    from jevops.search import parse_marked_list

    text = f"{stdout}\n{stderr}"
    names, _flagged = parse_marked_list(
        text,
        start_prefix="#print axioms",
        line_re=AXIOM_LINE,
        flag_needles=("sorryAx",),
        extra_if_flagged=("sorryAx",),
    )
    sorry = "sorryAx" in text or "hasSorry" in text
    if sorry and "sorryAx" not in names:
        names.append("sorryAx")
    return names, sorry


def lake_measurement_ok(
    *,
    exit_code: int,
    timed_out: bool,
    sorry: bool,
    axiom_names: Sequence[str],
    stdout: str,
    argv: Sequence[str],
    max_heartbeats: int,
    error: str = "",
    lean_path: str = "",
    timeout_seconds: float = 0.0,
    ikv_floor: float = IKV_DEFAULT_TIMEOUT_SECONDS,
    used_ikv: bool = False,
    sorry_tactic: bool = False,
    used_snapshot: bool = False,
    used_frontend: bool = False,
) -> bool:
    """True when tag-pinned ``lake env lean --json`` succeeded. Not an admit from cache."""

    from jevops.outer import nonempty

    if (
        int(exit_code) != 0
        or timed_out
        or error
        or sorry
        or "sorryAx" in axiom_names
        or sorry_tactic
        or used_ikv
        or used_snapshot
        or used_frontend
        or not nonempty(stdout)
        or int(max_heartbeats) <= 0
        or (timeout_seconds and float(timeout_seconds) <= float(ikv_floor))
        or len(argv) < 6
        or str(argv[1]) != "env"
        or str(argv[4]) != "--json"
        or str(argv[3]) != f"-DmaxHeartbeats={int(max_heartbeats)}"
    ):
        return False
    if lean_path:
        return str(argv[2]) == str(lean_path)
    return Path(str(argv[0])).name == "lake" and Path(str(argv[2])).name == "lean"


def lake_candidate_source(*, header: str, statement: str, tactic_block: str) -> str:
    from jevops.outer import as_str, join_decl

    return join_decl(statement, tactic_block, header=as_str(header))


def tactic_block_from_body(body_suffix: str, *, error_cls: type[BaseException] = ValueError) -> str:
    from jevops.outer import strip_leading_prefixes

    return strip_leading_prefixes(
        body_suffix,
        BODY_BY_PREFIXES,
        error_cls=error_cls,
        empty_msg="body suffix is empty",
        miss_msg="body suffix does not start with ' := by' after the frozen statement",
    )


def statement_sorry_template(statement: str, *, error_cls: type[BaseException] = ValueError) -> str:
    if not isinstance(statement, str) or not statement:
        raise error_cls("statement must be a non-empty string")
    return statement + STATEMENT_SORRY_SUFFIX


def tactic_block_from_record(
    record: Mapping[str, Any],
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    body_fn: Callable[[str], str],
) -> str:
    split = split_fn(record)
    return body_fn(getattr(split, "body_suffix"))


def listed_version_tags(version_info: Any, *, first_only: bool = False) -> list[str]:
    """JSONL ``version_info`` order. Never newest-mtime and never PATH lean."""

    tags: list[str] = []
    if not isinstance(version_info, list):
        return tags
    for item in version_info:
        if isinstance(item, dict):
            keys = list(item.keys())
            if first_only and keys:
                keys = keys[:1]
            for tag in keys:
                if isinstance(tag, str) and tag.strip() and tag not in tags:
                    tags.append(tag)
        elif isinstance(item, str) and item.strip() and item not in tags:
            tags.append(item)
    return tags


def listed_version_commits(version_info: Any) -> dict[str, str]:
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


def _record_field(record: Any, name: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def axiom_report_exists(record: Any, *, hex64: Any = None) -> bool:
    digest = _record_field(record, "axiom_digest", "")
    names = _record_field(record, "axiom_names", [])
    stdout = _record_field(record, "stdout", "") or ""
    stderr = _record_field(record, "stderr", "") or ""
    if hex64 is None:
        from jevops.catalogs import HEX64 as hex64
    has_digest = isinstance(digest, str) and hex64.fullmatch(digest) is not None
    has_names = isinstance(names, list)
    printed = "#print axioms" in stdout or "#print axioms" in stderr
    return bool((has_digest or has_names) and (printed or has_digest or has_names))


def has_sorry_ax(record: Any) -> bool:
    names = [str(item) for item in (_record_field(record, "axiom_names", []) or [])]
    stdout = _record_field(record, "stdout", "") or ""
    stderr = _record_field(record, "stderr", "") or ""
    text = f"{stdout}\n{stderr}"
    return bool(
        _record_field(record, "sorryAx", False)
        or "sorryAx" in names
        or "sorryAx" in text
        or "hasSorry" in text
    )


def _score_hits(payload: Mapping[str, Any], names: Sequence[str]) -> list[str]:
    return [str(key) for key in names if key in payload and payload.get(key) is not None]


def judge_warmup_receipt(
    record: Mapping[str, Any],
    receipts: Sequence[Any],
    *,
    frozen_digest: str,
    tags: Sequence[str],
    score_names: Sequence[str],
    bind_fn: Callable[[str, str, str], bool],
    axiom_ok_fn: Callable[[Any], bool],
    sorry_fn: Callable[[Any], bool],
) -> dict[str, Any]:
    """Judge one warmup receipt. Prefix bind only. Lake remains the admit oracle."""

    name = str(record.get("name") or "")
    source = str(record.get("source") or "")
    header = record.get("header") or ""
    if not isinstance(header, str):
        header = ""
    statement = record.get("statement") or ""
    if not isinstance(statement, str):
        statement = ""
    src = record.get("src") or ""
    matches = [item for item in receipts if str(_record_field(item, "name", "")) == name]
    failures: list[str] = []
    out: dict[str, Any] = {
        "name": name,
        "source": source,
        "listed_tags": list(tags),
        "receipt_found": bool(matches),
        "duplicate": len(matches) > 1,
        "digest_ok": False,
        "statement_bind_ok": False,
        "all_tags_ok": False,
        "no_sorry_ok": False,
        "one_receipt": len(matches) == 1,
        "arena_score_null": True,
        "failures": failures,
        "tag_records": [],
    }
    jsonl_bind = isinstance(src, str) and bool(statement) and src.startswith(statement)
    if not jsonl_bind:
        failures.append("jsonl src does not start with statement")
    if not matches:
        failures.append("missing receipt")
        return out
    if out["duplicate"]:
        failures.append("duplicate receipts")
        return out
    receipt = matches[0]
    payload = _record_field(receipt, "payload", {}) or {}
    if not isinstance(payload, Mapping):
        payload = {}
    compile_records = _record_field(receipt, "compile_records", {}) or {}
    score_keys = _score_hits(payload, score_names)
    for tag_record in compile_records.values():
        tag_payload = _record_field(tag_record, "payload", {}) or {}
        if isinstance(tag_payload, Mapping):
            score_keys.extend(_score_hits(tag_payload, score_names))
    score_keys = sorted(set(score_keys))
    out["arena_score_null"] = not score_keys
    if score_keys:
        failures.append("arena score written: " + ",".join(score_keys))
    if bool(_record_field(receipt, "mock", False)):
        failures.append("mock/fixed-program/silent-replay receipt")
    warmup = str(_record_field(receipt, "warmup_sha256", "") or "")
    digest_ok = True
    if warmup:
        digest_ok = warmup == frozen_digest
        if not digest_ok:
            failures.append("receipt warmup_sha256 mismatch")
    out["digest_ok"] = digest_ok
    receipt_header_raw = _record_field(receipt, "header", "")
    receipt_header = receipt_header_raw if receipt_header_raw else header
    statement_ok = True
    stored_statement = _record_field(receipt, "statement", "")
    if stored_statement and str(stored_statement) != statement:
        failures.append("receipt statement mutated")
        statement_ok = False
    stored_header = _record_field(receipt, "header", "")
    if stored_header and str(stored_header) != header:
        if str(stored_header).rstrip() != header.rstrip():
            failures.append("receipt header mutated")
            statement_ok = False
    candidate = str(_record_field(receipt, "candidate", "") or "")
    bind_ok = bool(candidate) and bind_fn(candidate, str(receipt_header or ""), statement)
    if not candidate:
        failures.append("missing candidate")
    elif not bind_ok:
        failures.append("candidate does not bind header+statement")
    out["statement_bind_ok"] = bool(jsonl_bind and statement_ok and bind_ok)
    present_tags = [tag for tag in tags if tag in compile_records]
    out["tag_records"] = sorted(compile_records)
    missing_tags = [tag for tag in tags if tag not in compile_records]
    all_tags_ok = not missing_tags and bool(tags)
    if missing_tags:
        failures.append("missing tags: " + ",".join(missing_tags))
    out["all_tags_ok"] = all_tags_ok
    sorry_ok = True
    if not present_tags:
        sorry_ok = False
        if "missing receipt" not in failures and missing_tags:
            pass
        elif not compile_records:
            failures.append("missing axiom reports")
    accepted = _record_field(receipt, "accepted", None)
    for tag in tags:
        tag_record = compile_records.get(tag)
        if tag_record is None:
            sorry_ok = False
            continue
        if not axiom_ok_fn(tag_record):
            sorry_ok = False
            failures.append(f"{tag}: missing axiom report")
        if sorry_fn(tag_record):
            sorry_ok = False
            failures.append(f"{tag}: sorryAx")
        exit_code = _record_field(tag_record, "exit_code", -1)
        if exit_code not in (0,):
            sorry_ok = False
            failures.append(f"{tag}: compile exit {exit_code}")
        if accepted is False:
            sorry_ok = False
            if "accepted is false" not in failures:
                failures.append("accepted is false")
    out["no_sorry_ok"] = bool(sorry_ok and present_tags and not missing_tags)
    return out


def synthetic_ok_tag(
    record: Mapping[str, Any],
    tag: str,
    commit: str,
    *,
    schema: str,
    axiom_digest: str,
    hardware: str = "synthetic-verify",
) -> dict[str, Any]:
    """Synthetic lake-ok tag receipt. Not a lake admit."""

    import json

    name = str(record.get("name") or "")
    decl = name.rsplit(".", 1)[-1].replace("'", "") or "lra_candidate"
    stdout = (
        json.dumps({"severity": "information", "data": "ok", "pos": {"line": 1, "column": 0}})
        + f"\n#print axioms {decl}\n{decl} : []\n"
    )
    return {
        "schema": schema,
        "name": name,
        "source": record.get("source"),
        "lean_tag": tag,
        "git_commit": commit,
        "sorryAx": False,
        "axiom_names": [],
        "axiom_digest": axiom_digest,
        "stdout": stdout,
        "stderr": "",
        "exit_code": 0,
        "ok": True,
        "arena_score": None,
        "score": None,
        "hardware_class": hardware,
    }


def tag_from_payload(payload: Mapping[str, Any], *, path: str = "", tag_cls: Callable[..., Any]) -> Any:
    names = payload.get("axiom_names")
    if not isinstance(names, list):
        names = []
    return tag_cls(
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


def read_candidate_text(directory: Path, payload: Mapping[str, Any]) -> str:
    if isinstance(payload.get("candidate"), str) and payload["candidate"]:
        return payload["candidate"]
    for name in ("candidate.lean", "candidate.src", "src.lean"):
        path = Path(directory) / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def compile_records_from_payload(
    payload: Mapping[str, Any],
    *,
    path: str,
    tag_fn: Callable[..., Any],
) -> dict[str, Any]:
    records: dict[str, Any] = {}
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
        record = tag_fn(item, path=path)
        lean_tag = getattr(record, "lean_tag", "")
        if lean_tag:
            records[str(lean_tag)] = record
    return records


def load_tag_directory(
    directory: Path,
    *,
    skip_names: Any,
    compile_schema: str,
    tag_fn: Callable[..., Any],
    load_json_fn: Callable[[Path], Any],
    problem_prefixes: Sequence[str] = ("lra-problem", "lra-batch"),
) -> dict[str, Any]:
    import json

    records: dict[str, Any] = {}
    directory = Path(directory)
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        if path.name in skip_names:
            continue
        try:
            payload = load_json_fn(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        schema = str(payload.get("schema") or "")
        if schema not in {"", compile_schema}:
            if any(schema.startswith(prefix) for prefix in problem_prefixes):
                continue
        record = tag_fn(payload, path=str(path))
        lean_tag = str(getattr(record, "lean_tag", "") or "")
        if not lean_tag:
            stem = path.stem
            if stem.startswith("v"):
                record.lean_tag = stem
                lean_tag = stem
        if lean_tag:
            records[lean_tag] = record
    tags_dir = directory / "tags"
    if tags_dir.is_dir():
        records.update(
            load_tag_directory(
                tags_dir,
                skip_names=skip_names,
                compile_schema=compile_schema,
                tag_fn=tag_fn,
                load_json_fn=load_json_fn,
                problem_prefixes=problem_prefixes,
            )
        )
    return records


def _mock_flag(payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("mock")
        or payload.get("fixed_program_substituted")
        or payload.get("silent_replay")
    )


def problem_from_directory(
    directory: Path,
    *,
    reserved: Any,
    skip_names: Any,
    compile_schema: str,
    tag_fn: Callable[..., Any],
    problem_cls: Callable[..., Any],
    load_json_fn: Callable[[Path], Any],
    error_cls: type[BaseException],
) -> Any:
    directory = Path(directory)
    problem_path = directory / "problem.json"
    payload: dict[str, Any] = {}
    if problem_path.is_file():
        loaded = load_json_fn(problem_path)
        if not isinstance(loaded, dict):
            raise error_cls(f"{problem_path}: problem.json is not an object")
        payload = loaded
    tag_records = load_tag_directory(
        directory,
        skip_names=skip_names,
        compile_schema=compile_schema,
        tag_fn=tag_fn,
        load_json_fn=load_json_fn,
    )
    nested = compile_records_from_payload(payload, path=str(problem_path), tag_fn=tag_fn)
    for tag, record in nested.items():
        if tag in tag_records:
            existing = tag_records[tag]
            if existing.axiom_digest and record.axiom_digest and existing.axiom_digest != record.axiom_digest:
                raise error_cls(f"{directory}: duplicate compile records for tag {tag}")
        tag_records.setdefault(tag, record)
    name = str(payload.get("name") or directory.name)
    if not name or name in reserved:
        if not payload and not tag_records:
            return None
        if not name or name in reserved:
            return None
    if not payload and not tag_records and not read_candidate_text(directory, {}):
        return None
    accepted = payload.get("accepted")
    return problem_cls(
        name=name,
        source=str(payload.get("source") or ""),
        header=str(payload.get("header") or ""),
        statement=str(payload.get("statement") or ""),
        candidate=read_candidate_text(directory, payload),
        warmup_sha256=str(payload.get("warmup_sha256") or payload.get("jsonl_sha256") or ""),
        accepted=None if accepted is None else bool(accepted),
        compile_records=tag_records,
        path=str(directory),
        mock=_mock_flag(payload),
        payload=payload,
    )


def problem_from_json_file(
    path: Path,
    *,
    compile_schema: str,
    problem_schema: str,
    tag_fn: Callable[..., Any],
    problem_cls: Callable[..., Any],
    load_json_fn: Callable[[Path], Any],
    error_cls: type[BaseException],
) -> Any:
    path = Path(path)
    payload = load_json_fn(path)
    if not isinstance(payload, dict):
        raise error_cls(f"{path}: receipt is not an object")
    schema = str(payload.get("schema") or "")
    if schema == compile_schema:
        record = tag_fn(payload, path=str(path))
        name = str(payload.get("name") or path.stem)
        return problem_cls(
            name=name,
            source=str(payload.get("source") or ""),
            compile_records={record.lean_tag: record} if record.lean_tag else {},
            path=str(path),
            payload=payload,
        )
    if schema and schema not in {problem_schema, ""}:
        return None
    records = compile_records_from_payload(payload, path=str(path), tag_fn=tag_fn)
    accepted = payload.get("accepted")
    return problem_cls(
        name=str(payload.get("name") or path.stem),
        source=str(payload.get("source") or ""),
        header=str(payload.get("header") or ""),
        statement=str(payload.get("statement") or ""),
        candidate=str(payload.get("candidate") or ""),
        warmup_sha256=str(payload.get("warmup_sha256") or payload.get("jsonl_sha256") or ""),
        accepted=None if accepted is None else bool(accepted),
        compile_records=records,
        path=str(path),
        mock=_mock_flag(payload),
        payload=payload,
    )


def iter_receipt_roots(receipts_dir: Path) -> list[Path]:
    roots: list[Path] = []
    problems = Path(receipts_dir) / "problems"
    if problems.is_dir():
        roots.append(problems)
    roots.append(Path(receipts_dir))
    return roots


def load_receipt_tree(
    receipts_dir: Path,
    *,
    reserved: Any,
    skip_names: Any,
    from_dir_fn: Callable[[Path], Any],
    from_file_fn: Callable[[Path], Any],
    error_cls: type[BaseException],
) -> list[Any]:
    receipts_dir = Path(receipts_dir)
    if not receipts_dir.is_dir():
        raise error_cls(f"receipts directory does not exist: {receipts_dir}")
    loaded: list[Any] = []
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
                if child.name in reserved and child.parent == receipts_dir:
                    continue
                receipt = from_dir_fn(child)
                if receipt is not None:
                    loaded.append(receipt)
                continue
            if child.suffix == ".json" and child.name not in skip_names:
                receipt = from_file_fn(child)
                if receipt is not None and (getattr(receipt, "compile_records", None) or getattr(receipt, "candidate", "")):
                    loaded.append(receipt)
    return loaded


def load_freeze_file(
    receipts_dir: Path,
    *,
    load_json_fn: Callable[[Path], Any],
    error_cls: type[BaseException],
) -> dict[str, Any]:
    path = Path(receipts_dir) / "freeze_binding.json"
    if not path.is_file():
        return {}
    payload = load_json_fn(path)
    if not isinstance(payload, dict):
        raise error_cls("freeze_binding.json is not an object")
    return payload


def note_freeze_binding(
    binding: Mapping[str, Any],
    *,
    frozen_digest: str,
    score_names: Sequence[str],
    failures: list[str],
) -> None:
    """Append freeze-binding failures. Does not admit Lean."""

    if not binding:
        return
    bound = str(binding.get("warmup_sha256") or binding.get("jsonl_sha256") or "")
    if bound and bound != frozen_digest:
        failures.append("freeze_binding warmup_sha256 mismatch")
    if binding.get("tiny_byte_lm") is True:
        failures.append("tiny-byte-lm freeze")
    score_keys = _score_hits(binding, score_names)
    if score_keys:
        failures.append("freeze_binding writes arena scores")


def schedule_rows(records: Sequence[Mapping[str, Any]], *, tags_fn: Callable[[Any], Sequence[str]]) -> list[dict[str, Any]]:
    problems = []
    for record in records:
        problems.append(
            {
                "name": record.get("name"),
                "source": record.get("source"),
                "listed_tags": list(tags_fn(record.get("version_info"))),
                "header_chars": len(record.get("header") or ""),
                "statement_chars": len(record.get("statement") or ""),
                "src_startswith_statement": str(record.get("src") or "").startswith(
                    str(record.get("statement") or "")
                ),
            }
        )
    return problems


def rollup_warmup_batch(
    *,
    records: Sequence[Mapping[str, Any]],
    receipts: Sequence[Any],
    judgments: Sequence[Any],
    failures: list[str],
    gates: Any,
    jsonl_unchanged: bool,
    digest: str,
    raw_len: int,
    frozen_digest: str,
    expected_n: int,
    schema: str,
    protocol: str,
) -> tuple[int, dict[str, Any], str]:
    """Roll per-problem judgments into a batch status. Not a lake admit."""

    scheduled_names = [str(record.get("name") or "") for record in records]
    by_name = {str(_record_field(item, "name", "")): item for item in judgments}
    extra_names = sorted(
        {str(_record_field(item, "name", "")) for item in receipts if str(_record_field(item, "name", "")) not in by_name}
    )
    missing = [str(_record_field(item, "name", "")) for item in judgments if not _record_field(item, "receipt_found", False)]
    duplicates = [str(_record_field(item, "name", "")) for item in judgments if _record_field(item, "duplicate", False)]
    digest_bad = [
        str(_record_field(item, "name", ""))
        for item in judgments
        if _record_field(item, "receipt_found", False) and not _record_field(item, "digest_ok", False)
    ]
    bind_bad = [str(_record_field(item, "name", "")) for item in judgments if not _record_field(item, "statement_bind_ok", False)]
    tags_bad = [str(_record_field(item, "name", "")) for item in judgments if not _record_field(item, "all_tags_ok", False)]
    sorry_bad = [str(_record_field(item, "name", "")) for item in judgments if not _record_field(item, "no_sorry_ok", False)]
    score_bad = [str(_record_field(item, "name", "")) for item in judgments if not _record_field(item, "arena_score_null", True)]
    one_receipt_ok = not missing and not duplicates and len(list(judgments)) == expected_n
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
    complete = bool(
        digest_ok
        and statement_ok
        and all_tags_ok
        and no_sorry_ok
        and one_receipt_ok
        and not score_bad
        and len(list(records)) == expected_n
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
    problems = []
    for item in judgments:
        to_dict = getattr(item, "to_dict", None)
        problems.append(to_dict() if callable(to_dict) else dict(item))
    payload = {
        "schema": schema,
        "status": status,
        "protocol": protocol,
        "n_scheduled": len(list(records)),
        "n_receipts": len({str(_record_field(item, "name", "")) for item in receipts}),
        "scheduled_names": scheduled_names,
        "missing_receipts": missing,
        "duplicate_receipts": duplicates,
        "digest_ok": digest_ok,
        "statement_bind_ok": statement_ok,
        "all_tags_ok": all_tags_ok,
        "no_sorryAx": no_sorry_ok,
        "one_receipt_per_scheduled_problem": one_receipt_ok,
        "complete": complete,
        "frozen_warmup_sha256": frozen_digest,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": raw_len,
        "jsonl_unchanged": jsonl_unchanged,
        "gates": sorted(gates),
        "triggered_gates": triggered,
        "failures": failures,
        "problems": problems,
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


def fail_batch_payload(
    gates: Sequence[str],
    failures: Sequence[str],
    *,
    n_scheduled: int,
    schema: str,
    protocol: str,
) -> dict[str, Any]:
    return {
        "schema": schema,
        "status": "FAIL",
        "protocol": protocol,
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


def drive_verify_batch(
    *,
    jsonl: Any,
    receipts_dir: Any,
    gates: Any,
    load_fn: Callable[..., tuple[Any, str, Sequence[Any]]],
    digest_fn: Callable[[Any], str],
    frozen: str,
    expected_n: int,
    fail_fn: Callable[..., Any],
    mismatch_type: type[BaseException],
    io_types: tuple[type[BaseException], ...],
    load_receipts_fn: Callable[[Any], Any],
    load_binding_fn: Callable[[Any], Any],
    note_fn: Callable[..., None],
    judge_fn: Callable[..., Any],
    error_types: tuple[type[BaseException], ...],
    score_names: Sequence[str],
    schema: str,
    protocol: str,
) -> Any:
    """Open a frozen warmup and roll judgments. Exit 2 is fail-closed. Not a lake admit."""

    failed, opened = open_frozen_warmup(
        jsonl,
        load_fn=load_fn,
        digest_fn=digest_fn,
        frozen=frozen,
        expected_n=expected_n,
        fail_fn=fail_fn,
        mismatch_type=mismatch_type,
        io_types=io_types,
    )
    if failed is not None:
        return failed
    assert opened is not None
    raw, digest, records, jsonl_unchanged, failures = opened
    try:
        receipts = load_receipts_fn(receipts_dir)
        binding = load_binding_fn(receipts_dir)
    except error_types as exc:
        payload = fail_fn(sorted(gates) or ["complete"], [str(exc)], n_scheduled=len(records))
        return 2, payload, str(exc)
    note_fn(binding, frozen_digest=frozen, score_names=score_names, failures=failures)
    judgments = [judge_fn(record, receipts, frozen_digest=digest) for record in records]
    return rollup_warmup_batch(
        records=records,
        receipts=receipts,
        judgments=judgments,
        failures=failures,
        gates=gates,
        jsonl_unchanged=jsonl_unchanged,
        digest=digest,
        raw_len=len(raw),
        frozen_digest=frozen,
        expected_n=expected_n,
        schema=schema,
        protocol=protocol,
    )


def write_problem_fixture_dir(
    dest: Path,
    record: Mapping[str, Any],
    *,
    digest: str,
    problem_schema: str,
    tags: Sequence[str],
    commits: Mapping[str, str],
    tag_payload_fn: Callable[[Mapping[str, Any], str, str], dict[str, Any]],
    candidate_fn: Callable[[Mapping[str, Any]], str],
    lake_source_fn: Callable[..., str],
    sorry_digest_fn: Callable[[str], str],
    drop_tags: Sequence[str] = (),
    mutate_candidate: Optional[str] = None,
    sorry_tags: Sequence[str] = (),
    injected_score: Any = None,
    warmup_sha256: Optional[str] = None,
    accepted: bool = True,
    statement: Optional[str] = None,
) -> Path:
    """Write a synthetic problem receipt tree. Not a lake compile."""

    import json
    import shutil

    name = str(record.get("name") or "")
    directory = Path(dest) / name
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    compile_records = []
    skip = set(drop_tags)
    sorry = set(sorry_tags)
    for tag in tags:
        if tag in skip:
            continue
        payload = tag_payload_fn(record, tag, commits.get(tag, ""))
        if tag in sorry:
            payload["sorryAx"] = True
            payload["axiom_names"] = ["sorryAx"]
            payload["axiom_digest"] = sorry_digest_fn(json.dumps(["sorryAx"], separators=(",", ":")))
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
    candidate = mutate_candidate if mutate_candidate is not None else candidate_fn(record)
    if statement is not None:
        candidate = lake_source_fn(
            header=header if isinstance(header, str) else "",
            statement=used_statement,
            tactic_block="rfl",
        )
    problem = {
        "schema": problem_schema,
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


def write_freeze_bundle(
    dest: Path,
    records: Sequence[Mapping[str, Any]],
    *,
    digest: str,
    schema: str,
    protocol: str,
    write_problem_fn: Callable[..., Path],
) -> None:
    import json

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    binding = {
        "schema": schema,
        "warmup_sha256": digest,
        "protocol": protocol,
        "n_problems": len(list(records)),
        "arena_score": None,
        "score": None,
        "tiny_byte_lm": False,
    }
    (dest / "freeze_binding.json").write_text(
        json.dumps(binding, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for record in records:
        write_problem_fn(dest, record, digest=digest)


def elan_toolchain_dirname(
    lean_tag: str,
    *,
    prefix: str,
    normalize_fn: Optional[Callable[[str], str]] = None,
) -> str:
    tag = normalize_fn(lean_tag) if normalize_fn is not None else str(lean_tag)
    return f"{prefix}{tag}"


def putnam_root_import(module: str) -> str:
    return f"import {module}\n"


def cache_marker_path(cache_dir: Path, marker: str = "BAKED") -> Path:
    return Path(cache_dir) / marker


def require_plan_caches(
    jobs: Sequence[Any],
    *,
    require_fn: Callable[..., Any],
    **kwargs: Any,
) -> list[Any]:
    return [require_fn(job, **kwargs) for job in jobs]


END_MARKERS = ("<|im_end|>", "</s>", "<|endoftext|>", "<|eot_id|>")


def plain_hole_prompt(
    record: Mapping[str, Any],
    skeleton: str,
    holes: Sequence[Any],
    *,
    limit: int = 8,
) -> str:
    """Leanstral hole-fill prompt. The model reply is not a lake admit."""

    from jevops.outer import get_str, head_seq

    docs = [
        f"{hole.hole_id} kind={hole.kind} ORIGINAL={hole.original!r}\n"
        for hole in head_seq(holes, limit)
    ]
    return (
        "Lean 4 tactic hole-fill. Each <<<SYM_i kind=...>>> is one operator or symbol. "
        "Fill with a SHORTER Lean operator/symbol from the language (constructor, simp_all, $, "
        "‹_›, all_goals, intro, .update_some, a hyp already in the proof). "
        "Keep induction and every · / case arm. No sorry, no theorem, no open.\n\n"
        f"Problem: {get_str(record, 'name')}\n"
        f"SKELETON:\n{skeleton}\n\n"
        f"HOLES:\n{''.join(docs)}\n"
        "Reply as:\n<<<SYM_0 kind=...>>>\n<fill>\n<<<SYM_1 kind=...>>>\n<fill>\n"
    )


def trim_tactic_body(text: str) -> str:
    """Trim the envelope, not Lean's relative multiline indentation.

    In particular, str.strip() moves only the first tactic to column zero.
    Keep all nonblank multiline lines verbatim (including CRLF); callers may
    uniformly indent the whole block. Single-line compatibility is retained.
    This is whitespace handling, not syntax repair or proof admission.
    """
    lines = text.splitlines(keepends=True)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) == 1:
        return lines[0].strip()
    return "".join(lines).rstrip("\r\n")


def extract_generated_tactics(text: str) -> str:
    """Take a tactic block from an untrusted model payload. Not a statement splice."""

    if not isinstance(text, str):
        return ""
    raw = text
    for marker in END_MARKERS:
        raw = raw.split(marker, 1)[0]
    raw = trim_tactic_body(raw)
    if raw.lstrip().startswith("```"):
        lines = raw.splitlines(keepends=True)[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines.pop()
        raw = trim_tactic_body("".join(lines))
    # Remove only a known envelope, never lstrip an ordinary tactic body.
    for prefix in BODY_BY_PREFIXES:
        if raw.lstrip().startswith(prefix.lstrip()):
            raw = raw.lstrip()[len(prefix.lstrip()):]
            break
    return trim_tactic_body(raw)


def parse_next_tactic_line(text: str, *, stop: str = "STOP") -> str:
    from jevops.search import first_line
    from jevops.tactics import looks_like_tactic

    body = extract_generated_tactics(text)
    return first_line(
        body,
        stop_pred=lambda s: s.upper() == stop
        or s in {".", "qed"}
        or s.startswith("sorry")
        or s.startswith("admit"),
        skip_pred=lambda s: "<|im_start|>" in s
        or "<|im_end|>" in s
        or s.startswith("<|")
        or s.startswith("You are")
        or s.startswith("Lean 4")
        or len(s) > 160,
        keep_pred=lambda s: looks_like_tactic(s, stop=stop),
        default=stop,
    )


PATH_A_TACTICS: tuple[str, ...] = ("rfl", "decide", "omega", "simp_all")
AESOP_TACTIC = "aesop"
SORRY_TACTIC = "sorry"
AESOP_IMPORT = re.compile(r"(?m)^\s*import\s+Aesop\b")


def path_a_tactics(header: str = "", src: str = "") -> list[str]:
    from jevops.outer import any_search

    rows = list(PATH_A_TACTICS)
    if any_search((header, src), AESOP_IMPORT):
        rows.append(AESOP_TACTIC)
    return rows


def fill_from_process(
    result: Any,
    *,
    argv: Sequence[str],
    max_heartbeats: int,
    wall_ms: float = 0.0,
    cpu_ms: float = 0.0,
    lean_path: str = "",
    timeout_seconds: float = 0.0,
    ikv_floor: float = IKV_DEFAULT_TIMEOUT_SECONDS,
    sorry_tactic: bool = False,
    used_snapshot: bool = False,
    used_frontend: bool = False,
    used_ikv: bool = False,
) -> dict[str, Any]:
    """Parse a lake/lean process result. Cache hits never admit."""

    from jevops.outer import digest_text, process_exit_code

    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    error = str(getattr(result, "error", "") or "")
    exit_code, timed_out = process_exit_code(result)
    axiom_names, sorry = parse_axioms(stdout, stderr)
    ok = lake_measurement_ok(
        exit_code=exit_code,
        timed_out=timed_out,
        sorry=sorry,
        axiom_names=axiom_names,
        stdout=stdout,
        argv=argv,
        max_heartbeats=max_heartbeats,
        error=error,
        lean_path=lean_path,
        timeout_seconds=timeout_seconds,
        ikv_floor=ikv_floor,
        used_ikv=used_ikv,
        sorry_tactic=sorry_tactic,
        used_snapshot=used_snapshot,
        used_frontend=used_frontend,
    )
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_digest": digest_text(stdout),
        "axiom_names": axiom_names,
        "axiom_digest": axiom_digest(axiom_names),
        "sorryAx": sorry,
        "wall_ms": wall_ms,
        "cpu_ms": cpu_ms,
        "error": error,
        "ok": ok,
        "measurement_maxHeartbeats": int(max_heartbeats),
    }


def overlay_measurement(target: Any, filled: Mapping[str, Any], *, extra_ok: bool = True) -> Any:
    for key, value in dict(filled or {}).items():
        if hasattr(target, key):
            setattr(target, key, value)
    if hasattr(target, "ok"):
        target.ok = bool(filled.get("ok")) and extra_ok
    return target


def compile_closed(*, token_count: int = 0, error: str = "no_installed_matching_toolchain") -> dict[str, Any]:
    """Fail-closed compile payload. Never a lake admit."""

    return {
        "ok": False,
        "theorem_ok": False,
        "module_exit_0": False,
        "exit_code": -1,
        "error": str(error),
        "token_count": int(token_count),
        "errors": [],
        "arena_score": None,
    }


@dataclass
class CompileReceipt:
    """One per-tag lake compile receipt. IndependentKernelVerifier is unused."""

    schema: str = "lake-compile-receipt/v1"
    name: str = ""
    source: str = ""
    file_path: str = ""
    url: str = ""
    lean_tag: str = ""
    git_commit: str = ""
    argv: list[str] = field(default_factory=list)
    cwd: str = ""
    exit_code: int = -1
    timed_out: bool = False
    timeout_seconds: float = 600.0
    stdout: str = ""
    stderr: str = ""
    stdout_digest: str = ""
    axiom_names: list[str] = field(default_factory=list)
    axiom_digest: str = ""
    sorryAx: bool = False
    wall_ms: float = 0.0
    cpu_ms: float = 0.0
    n_samples: int = 1
    measurement_maxHeartbeats: int = 400000
    header_maxHeartbeats: Optional[int] = None
    lean_num_threads: int = 1
    independent_kernel_verifier_used: bool = False
    independent_kernel_verifier_timeout_seconds: None = None
    lake_oracle: bool = True
    kernel_command_template: str = "{lake} env {lean} --json {source_file}"
    ok: bool = False
    aborted_remaining_tags: list[str] = field(default_factory=list)
    hardware_class: str = "unscored-dev"
    error: str = ""
    arena_score: None = None
    score: None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["arena_score"] = None
        payload["score"] = None
        payload["independent_kernel_verifier_used"] = False
        payload["independent_kernel_verifier_timeout_seconds"] = None
        payload["lake_oracle"] = True
        return payload


def init_compile_receipt(
    record: Mapping[str, Any],
    pin: Any,
    *,
    timeout: float,
    relpath: str,
    schema: str = "lake-compile-receipt/v1",
    max_heartbeats: int = 400000,
    header_cap: Optional[int] = None,
    lean_num_threads: int = 1,
    kernel_command_template: str = "{lake} env {lean} --json {source_file}",
    hardware_class: str = "unscored-dev",
) -> CompileReceipt:
    """Seed a lake receipt. IndependentKernelVerifier is unused."""

    return CompileReceipt(
        schema=schema,
        name=str(record.get("name") or ""),
        source=str(record.get("source") or ""),
        file_path=relpath,
        url=str(record.get("url") or ""),
        lean_tag=str(getattr(pin, "lean_tag", "") or ""),
        git_commit=str(getattr(pin, "git_commit", "") or ""),
        timeout_seconds=float(timeout),
        measurement_maxHeartbeats=int(max_heartbeats),
        header_maxHeartbeats=header_cap,
        lean_num_threads=int(lean_num_threads),
        kernel_command_template=kernel_command_template,
        hardware_class=hardware_class,
    )


@dataclass
class TacticAttempt:
    """One ``lake env lean`` invocation for a single tactic (or the sorry hole)."""

    tactic: str = ""
    argv: list[str] = field(default_factory=list)
    cwd: str = ""
    source_file: str = ""
    exit_code: int = -1
    timed_out: bool = False
    timeout_seconds: float = 120.0
    stdout: str = ""
    stderr: str = ""
    stdout_digest: str = ""
    axiom_names: list[str] = field(default_factory=list)
    axiom_digest: str = ""
    sorryAx: bool = False
    wall_ms: float = 0.0
    cpu_ms: float = 0.0
    measurement_maxHeartbeats: int = 400000
    ok: bool = False
    error: str = ""
    used_snapshot_goal: bool = False
    used_lean_frontend: bool = False
    used_goal_snapshot: bool = False
    generator: str = "lake_native"
    arena_score: None = None
    score: None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["arena_score"] = None
        payload["score"] = None
        payload["used_snapshot_goal"] = False
        payload["used_lean_frontend"] = False
        payload["used_goal_snapshot"] = False
        payload["generator"] = "lake_native"
        return payload


def path_a_try(
    considered: Sequence[str],
    run_fn: Callable[[str], TacticAttempt],
) -> tuple[list[TacticAttempt], Optional[str]]:
    """Try Path A closers until one lake-ok. Caller already proved sorry is not ok."""

    from jevops.outer import collect_until

    attempts = collect_until(list(considered), run_fn, abort_fn=lambda attempt: attempt.ok)
    winner = next((item.tactic for item in attempts if item.ok), None)
    return attempts, winner


@dataclass(frozen=True)
class ExecutablePaths:
    lean: str
    lake: str

    def to_dict(self) -> dict[str, str]:
        return {"lean": self.lean, "lake": self.lake}


def parse_executable_paths(
    value: Any,
    *,
    paths_cls: Any = ExecutablePaths,
    error_cls: Any = ValueError,
) -> Any:
    """Require exactly lean and lake. ``primary_executable`` is rejected. Not a lake admit."""

    from jevops.outer import reject_present_keys, require_exact_keys, str_map

    if isinstance(value, paths_cls):
        paths = value.to_dict()
    elif isinstance(value, Mapping):
        reject_present_keys(
            value,
            ("primary_executable",),
            error_cls=error_cls,
            fmt="executable_paths must not include {key}",
            empty=(),
        )
        paths = str_map(value)
    else:
        raise error_cls("executable_paths must be a mapping of lean and lake")
    got = require_exact_keys(
        paths,
        ("lean", "lake"),
        error_cls=error_cls,
        not_map="executable_paths must be a mapping of lean and lake",
        extra_fmt="executable_paths must be exactly lean and lake",
        miss_fmt="executable_paths must be exactly lean and lake",
        empty_fmt="executable_paths lean and lake must be nonempty",
    )
    return paths_cls(lean=got["lean"], lake=got["lake"])


@dataclass(frozen=True)
class PutnamPin:
    lean_tag: str
    mathlib_git: str
    mathlib_rev: str
    aesop_git: str
    aesop_rev: str
    jsonl_version_pin: str
    package: str = "putnam_lake"
    lib: str = "Putnam"
    module: str = "Putnam.Candidate"
    candidate_relpath: str = "Putnam/Candidate.lean"
    putnambench_url: None = None
    tmp_lean: bool = False

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


@dataclass(frozen=True)
class BakeJob:
    kind: str
    source: str
    lean_tag: str
    git_commit: str
    url: str
    cache_key: str
    phase: int
    record_names: tuple[str, ...]
    file_paths: tuple[str, ...]
    module: str
    mathlib_rev: str = ""
    aesop_rev: str = ""
    lakefile_required: bool = False
    putnambench_url: None = None
    arena_score: None = None

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        payload = asdict(self)
        payload["record_names"] = list(self.record_names)
        payload["file_paths"] = list(self.file_paths)
        payload["arena_score"] = None
        return payload


def write_lake_source(
    dest: Any,
    *,
    header: str,
    statement: str,
    tactic_block: str,
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
    refuse_fmt: str = "refusing to write {name}",
) -> Path:
    from jevops.outer import write_text

    return write_text(
        dest,
        lake_candidate_source(header=header, statement=statement, tactic_block=tactic_block),
        refuse=refuse,
        error_cls=error_cls,
        refuse_fmt=refuse_fmt,
    )


def render_lean_toolchain(tag: str) -> str:
    return f"leanprover/lean4:{tag}\n"


def render_package_lakefile(
    *,
    package: str,
    lib: str,
    max_heartbeats: int,
    server_args: bool = False,
) -> str:
    """Minimal lake package. Not a Mathlib/Aesop lakefile and not Tmp.lean."""

    server = (
        f'  moreServerArgs := #["-DmaxHeartbeats={int(max_heartbeats)}"]\n' if server_args else ""
    )
    return (
        "import Lake\n"
        "open Lake DSL\n"
        "\n"
        f"package «{package}» where\n"
        f'  moreLeanArgs := #["-DmaxHeartbeats={int(max_heartbeats)}"]\n'
        f"{server}"
        "\n"
        f"lean_lib «{lib}»\n"
    )


def render_mathlib_aesop_lakefile(
    *,
    package: str,
    lib: str,
    max_heartbeats: int,
    mathlib_git: str,
    mathlib_rev: str,
    aesop_git: str,
    aesop_rev: str,
) -> str:
    """Mathlib+Aesop lakefile. Candidate module is not Tmp.lean."""

    return (
        "import Lake\n"
        "open Lake DSL\n"
        "\n"
        f"package «{package}» where\n"
        f'  moreLeanArgs := #["-DmaxHeartbeats={int(max_heartbeats)}"]\n'
        f'  moreServerArgs := #["-DmaxHeartbeats={int(max_heartbeats)}"]\n'
        "\n"
        "require mathlib from git\n"
        f'  "{mathlib_git}" @ "{mathlib_rev}"\n'
        "\n"
        "require aesop from git\n"
        f'  "{aesop_git}" @ "{aesop_rev}"\n'
        "\n"
        "@[default_target]\n"
        f"lean_lib «{lib}» where\n"
        f"  globs := #[.submodules `{lib}]\n"
    )


def render_placeholder_theorem(*, ident: str = "lra_putnam_candidate_placeholder") -> str:
    return f"theorem {ident} : True := by\n  trivial\n"


def materialize_lake_files(
    dest: Any,
    files: Mapping[str, str],
    *,
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
) -> dict[str, str]:
    from jevops.outer import plant_files, refuse_basename

    dest_path = Path(dest)
    for relpath in files:
        if refuse:
            refuse_basename(relpath, refuse, error_cls=error_cls, fmt="refusing to materialize {name}")
    plant_files(dest_path, files)
    if refuse and (dest_path / refuse).exists():
        raise error_cls(f"Putnam lake project must not contain {refuse}")
    return {relpath: str(dest_path / relpath) for relpath in files}


@dataclass(frozen=True)
class StatementBody:
    name: str
    source: str
    statement: str
    body_suffix: str
    header: str

    @property
    def reconstructed_src(self) -> str:
        return self.statement + self.body_suffix


@dataclass(frozen=True)
class AdmissionView:
    accepted: bool
    failure_code: str
    reason: str
    name: str
    native_source_starts_with_statement: bool
    used_full_src_as_native: bool = False
    used_full_src_as_canonical: bool = False
    arena_score: None = None


def admit_tactic_only(
    statement: str,
    proof_text: str,
    *,
    admit_loader: Callable[[], Callable[..., Any]],
    forbid_fn: Callable[[str], Any],
    sorry_fn: Callable[[str], str],
    theorem_id: str = "",
    declaration_name: str = "",
) -> Any:
    """Lexical admit of a tactic block. Not a lake admit and not a Lean write."""

    forbid_fn(proof_text)
    return admit_empty_canonical(
        admit_loader(),
        proof_text,
        sorry_fn(statement),
        theorem_id=theorem_id,
        declaration_name=declaration_name,
    )


def tex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
        .replace("#", "\\#")
    )


def warmup_problem_row(record: Mapping[str, Any], *, versions: Sequence[str]) -> dict[str, Any]:
    return {
        "name": record["name"],
        "source": record["source"],
        "file_path": record.get("file_path") or "",
        "url": record.get("url") or "",
        "num_lines": record["num_lines"],
        "proof_length": record["proof_length"],
        "src_chars": len(record.get("src") or ""),
        "statement_chars": len(record.get("statement") or ""),
        "has_header": bool((record.get("header") or "").strip()),
        "start_line": record.get("start_line"),
        "end_line": record.get("end_line"),
        "n_toolchains": len(list(versions)),
        "lean_versions": list(versions),
    }


def warmup_latex_table(
    problems: Sequence[Mapping[str, Any]],
    *,
    display_names: Mapping[str, str],
    source_labels: Mapping[str, str],
) -> str:
    lines = [
        r"\begin{tabular}{llrrl}",
        r"  \toprule",
        r"  Source & Theorem (short) & Lines & Tokens & Toolchains \\",
        r"  \midrule",
    ]
    for problem in problems:
        name = str(problem["name"])
        display = display_names.get(name, name.split(".")[-1])
        source = str(problem["source"])
        lines.append(
            "  {source} & \\texttt{{{name}}} & {lines} & {tokens} & {n} \\\\".format(
                source=source_labels.get(source, source),
                name=tex_escape(display),
                lines=problem["num_lines"],
                tokens=problem["proof_length"],
                n=problem["n_toolchains"],
            )
        )
    lines.extend([r"  \bottomrule", r"\end{tabular}", ""])
    return "\n".join(lines)


def join_declaration_proof(declaration: str, body: str) -> str:
    """Glue a declaration and a proof body. Not a lake file and not an admit."""

    text = declaration.rstrip()
    if not text.endswith(":="):
        text += " :="
    proof = body.strip()
    if proof and not proof.startswith("by"):
        proof = "by\n" + proof
    return text + " " + proof + "\n"


def check_standalone_lean(
    declaration: str,
    body: str,
    *,
    lean_bin: Path,
    timeout: float = 30.0,
    autostart_key: str = "",
    prefix: str = "lean-check-",
) -> dict[str, Any]:
    """Run one ``lean`` file. Not ``lake``. Not an admit."""

    import os
    import subprocess
    import time

    from jevops.outer import elapsed_ms, exc_text, temp_dir

    source = join_declaration_proof(declaration, body)
    started = time.perf_counter()
    run_env = dict(os.environ)
    if autostart_key:
        run_env[autostart_key] = "0"
    try:
        with temp_dir(prefix=prefix) as tmp:
            path = Path(tmp) / "Canary.lean"
            path.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                [str(lean_bin), str(path)],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "exit_code": None,
            "error": exc_text(exc),
            "wall_ms": elapsed_ms(started),
            "source_chars": len(source),
        }
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-800:],
        "stderr_tail": (proc.stderr or "")[-800:],
        "wall_ms": elapsed_ms(started),
        "source_chars": len(source),
        "error": "" if proc.returncode == 0 else "lean_nonzero_exit",
    }


def fol_expected_match(
    *,
    expected_provable: bool,
    parsed_kind: str,
    kernel_ok: bool,
    kernel_ran: bool,
) -> Optional[bool]:
    """Advisory match against a FOL canary. Not a lake admit."""

    if expected_provable:
        return bool(kernel_ok)
    if parsed_kind == "abstain":
        return True
    if kernel_ran:
        return not kernel_ok
    return None


def selected_gates(
    *,
    digest: bool = False,
    statement: bool = False,
    tags: bool = False,
    sorry: bool = False,
    complete: bool = False,
    all_gates: Sequence[str] = (),
) -> set[str]:
    gates: set[str] = set()
    if digest:
        gates.add("digest")
    if statement:
        gates.add("statement_bind")
    if tags:
        gates.add("all_tags")
    if sorry:
        gates.add("no_sorry")
    if complete:
        gates.update(all_gates)
    return gates


def frozen_jsonl_failures(
    *,
    before: str,
    after: str,
    digest: str,
    frozen: str,
    n_records: int,
    expected_n: int,
) -> tuple[bool, list[str]]:
    unchanged = before == after == frozen == digest
    failures: list[str] = []
    if not unchanged:
        failures.append(f"warmup JSONL hash mismatch: {digest} != {frozen}")
    if n_records != expected_n:
        failures.append(f"warmup JSONL must contain {expected_n} records, got {n_records}")
    return unchanged, failures


def open_frozen_warmup(
    jsonl: Any,
    *,
    load_fn: Callable[..., tuple[Any, str, Sequence[Any]]],
    digest_fn: Callable[[Any], str],
    frozen: str,
    expected_n: int,
    fail_fn: Callable[..., tuple[int, dict[str, Any], str]],
    mismatch_type: type[BaseException],
    io_types: tuple[type[BaseException], ...],
) -> tuple[Optional[tuple[int, dict[str, Any], str]], Optional[tuple[Any, str, list[Any], bool, list[str]]]]:
    """Load a frozen JSONL or return a fail-closed triple. Does not compile."""

    try:
        before = digest_fn(jsonl)
        raw, digest, records = load_fn(jsonl)
        after = digest_fn(jsonl)
    except mismatch_type as exc:
        return fail_fn(["digest"], [str(exc)], n_scheduled=expected_n), None
    except io_types as exc:
        return fail_fn(["digest"], [str(exc)], n_scheduled=expected_n), None
    unchanged, failures = frozen_jsonl_failures(
        before=before,
        after=after,
        digest=digest,
        frozen=frozen,
        n_records=len(list(records)),
        expected_n=expected_n,
    )
    return None, (raw, digest, list(records), unchanged, failures)


def admit_empty_canonical(
    admit_fn: Callable[..., Any],
    proof_text: str,
    native: str,
    *,
    theorem_id: str = "",
    declaration_name: str = "",
) -> Any:
    """Lexical admit with empty canonical_source/expected_statement. Not a lake admit."""

    return admit_fn(
        proof_text,
        native,
        theorem_id=theorem_id,
        declaration_name=declaration_name,
        canonical_source="",
        expected_statement="",
    )


def drive_admission_view(
    record: Mapping[str, Any],
    proof_text: str,
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    sorry_fn: Callable[[str], str],
    admit_fn: Callable[..., Any],
    last_fn: Callable[[str], str],
    view_cls: Any = None,
) -> Any:
    """Lexical admission view. Not a lake admit and not a copy of src."""

    split = split_fn(record)
    native = sorry_fn(split.statement)
    admission = admit_fn(
        split.statement,
        proof_text,
        theorem_id=split.name,
        declaration_name=last_fn(split.name),
    )
    return pack_admission_view(
        admission,
        name=split.name,
        native=native,
        statement=split.statement,
        view_cls=view_cls,
    )


def pack_admission_view(
    admission: Any,
    *,
    name: str,
    native: str,
    statement: str,
    view_cls: Any = None,
) -> AdmissionView:
    """Lexical admission view. Not a lake admit. Never copies full src."""

    cls = view_cls or AdmissionView
    return cls(
        accepted=bool(getattr(admission, "accepted", False)),
        failure_code=str(getattr(getattr(admission, "failure_code", None), "value", getattr(admission, "failure_code", ""))),
        reason=str(getattr(admission, "reason", "")),
        name=name,
        native_source_starts_with_statement=str(native).startswith(str(statement)),
        used_full_src_as_native=False,
        used_full_src_as_canonical=False,
        arena_score=None,
    )


@dataclass
class TacticTryReceipt:
    """Path A lake-native try receipt. Snapshot/HAMMER flags stay false."""

    schema: str = "lake-native-try/v1"
    name: str = ""
    source: str = ""
    file_path: str = ""
    url: str = ""
    lean_tag: str = ""
    git_commit: str = ""
    sorry_template_digest: str = ""
    sorry_template_prefix_bound: bool = False
    aesop_imported: bool = False
    tactics_considered: list[str] = field(default_factory=list)
    tactics_run: list[str] = field(default_factory=list)
    sorry_attempt: Optional[dict[str, Any]] = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    winning_tactic: Optional[str] = None
    ok: bool = False
    loop: str = "v2"
    path: str = "A"
    pr: str = ""
    lrah: str = ""
    on_30_sep_critical_path: bool = False
    v1_runs_this: bool = False
    hammer_006_lra_ready: bool = False
    uses_snapshot_goal: bool = False
    goal_snapshot_required: bool = False
    path_b_implemented: bool = False
    generator: str = "lake_native"
    kernel_command_template: str = "{lake} env {lean} --json {source_file}"
    measurement_argv_template: str = ""
    timeout_seconds: float = 120.0
    error: str = ""
    arena_score: None = None
    score: None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["arena_score"] = None
        payload["score"] = None
        payload["on_30_sep_critical_path"] = False
        payload["v1_runs_this"] = False
        payload["hammer_006_lra_ready"] = False
        payload["uses_snapshot_goal"] = False
        payload["goal_snapshot_required"] = False
        payload["path_b_implemented"] = False
        payload["generator"] = "lake_native"
        return payload


def init_try_receipt(
    record: Mapping[str, Any],
    pin: Any,
    *,
    relpath: str,
    template_digest: str,
    prefix_bound: bool,
    aesop: bool,
    considered: Sequence[str],
    timeout: float,
    schema: str = "lake-native-try/v1",
    loop: str = "v2",
    path: str = "A",
    pr: str = "",
    lrah: str = "",
    generator: str = "lake_native",
    kernel_command_template: str = "{lake} env {lean} --json {source_file}",
    measurement_argv_template: str = "",
) -> TacticTryReceipt:
    """Seed a Path A try receipt. HAMMER/snapshot flags stay false."""

    return TacticTryReceipt(
        schema=schema,
        name=str(record.get("name") or ""),
        source=str(record.get("source") or ""),
        file_path=relpath,
        url=str(record.get("url") or ""),
        lean_tag=str(getattr(pin, "lean_tag", "") or ""),
        git_commit=str(getattr(pin, "git_commit", "") or ""),
        sorry_template_digest=str(template_digest or ""),
        sorry_template_prefix_bound=bool(prefix_bound),
        aesop_imported=bool(aesop),
        tactics_considered=list(considered or ()),
        timeout_seconds=float(timeout),
        loop=loop,
        path=path,
        pr=pr,
        lrah=lrah,
        generator=generator,
        kernel_command_template=kernel_command_template,
        measurement_argv_template=measurement_argv_template,
    )


def pin_reference_scores(candidate: Any, *, composite_fn: Callable[[float, float], float]) -> Any:
    """Reference elab is the unit baseline when lake returned a positive wall."""

    if float(getattr(candidate, "elab_ms", 0) or 0) > 0:
        candidate.elab_ratio = 1.0
        candidate.composite = composite_fn(1.0, 1.0)
    return candidate


def compile_receipt_files(
    kept: Any,
    *,
    hardware_class: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Kept compile receipts as files. Arena scores stay None."""

    files: dict[str, Any] = {}
    compile_records: list[dict[str, Any]] = []
    if kept is None:
        return files, compile_records
    for item in getattr(kept, "compile_receipts", ()) or ():
        payload = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        payload["arena_score"] = None
        payload["score"] = None
        payload["hardware_class"] = hardware_class
        compile_records.append(payload)
        tag = str(payload.get("lean_tag") or getattr(item, "lean_tag", "") or "unknown")
        files[f"{tag}.json"] = payload
    return files, compile_records


def persist_receipt(
    receipt: Any,
    *,
    root: Any,
    body: Optional[str] = None,
    duckdb_path: Any = None,
    parent_digest: Optional[str] = None,
    require_duckdb: bool = False,
    control_plane: bool = False,
    finalize_fn: Callable[..., Any],
    write_cas_fn: Callable[..., str],
    write_fs_fn: Callable[..., Any],
    connect_fn: Callable[..., tuple[Any, str]],
    install_fn: Callable[[Any], None],
    insert_fn: Callable[..., bool],
    insert_edge_fn: Callable[..., Any],
    try_import_fn: Callable[[], Any],
    error_cls: Any = ValueError,
    control_msg: str = "receipt store must not be the control plane",
    duckdb_missing: str = "duckdb package is required for this write but is not installed",
    digest_drift: str = "body_digest drifted from CAS write",
) -> Any:
    """Filesystem receipt first, then optional INSERT. DuckDB is never required."""

    if control_plane:
        raise error_cls(control_msg)
    receipt = finalize_fn(receipt, body=body)
    if body is not None:
        receipt.candidate_cid = write_cas_fn(root, body)
        if receipt.body_digest != receipt.candidate_cid:
            raise error_cls(digest_drift)
    path = write_fs_fn(root, receipt)
    receipt.filesystem_path = str(path)
    if duckdb_path is None:
        receipt.duckdb_used = False
        receipt.inserted = False
        return receipt
    module = try_import_fn()
    if require_duckdb and module is None:
        raise error_cls(duckdb_missing)
    conn, engine = connect_fn(duckdb_path, module)
    try:
        install_fn(conn)
        inserted = insert_fn(conn, receipt)
        if parent_digest:
            insert_edge_fn(conn, parent_digest, receipt.key_digest)
        commit = getattr(getattr(conn, "_raw", None), "commit", None)
        if callable(commit):
            commit()
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()
    receipt.duckdb_used = engine == "duckdb"
    receipt.inserted = inserted
    receipt.skipped_duplicate = not inserted
    path = write_fs_fn(root, receipt)
    receipt.filesystem_path = str(path)
    return receipt


@dataclass(frozen=True)
class NeighborProof:
    name: str
    source: str
    statement: str
    src: str
    header: str
    file_path: str
    proof_length: int
    url: str
    head_chars: int = 400

    @property
    def statement_head(self) -> str:
        from jevops.outer import head_chars as _fn

        return _fn(self.statement, self.head_chars)

    @property
    def proof_head(self) -> str:
        from jevops.outer import head_chars as _fn

        return _fn(self.src, self.head_chars)


@dataclass(frozen=True)
class Retrieval:
    query: str
    source: str
    neighbors: tuple[NeighborProof, ...]
    src_lemmas: tuple[Any, ...]
    lemma_ids: tuple[str, ...]
    lemma_id_digest: str
    n_src_lemmas_uncapped: int
    arena_score: None = None
    corpus_manifest_ingest: bool = False
    mathlib_ingest: bool = False


@dataclass(frozen=True)
class BakeCatalog:
    warmup_n: int
    source_order: tuple[str, ...]
    putnam_source: str
    strata_source: str
    strata_first_tag: str
    putnam_tags: tuple[str, ...]
    putnam_candidate_relpath: str
    putnam_module: str
    mathlib_needle: str = "import Mathlib"
    aesop_needle: str = "import Aesop"


def putnam_pin_for_tag(
    lean_tag: str,
    tags: Sequence[str],
    *,
    mathlib_git: str,
    aesop_git: str,
    jsonl_version_pin: str = "",
    normalize_fn: Optional[Callable[[str], str]] = None,
    error_cls: type[BaseException] = ValueError,
) -> PutnamPin:
    tag = normalize_fn(lean_tag) if normalize_fn is not None else str(lean_tag)
    if tag not in set(tags):
        raise error_cls(f"Putnam lake project is not defined for lean tag {tag}")
    return PutnamPin(
        lean_tag=tag,
        mathlib_git=mathlib_git,
        # Organizer version_info hashes identify mathlib4, not PutnamBench.
        # Preserve tag-only callers, but never discard an explicitly supplied pin.
        mathlib_rev=jsonl_version_pin if jsonl_version_pin else tag,
        aesop_git=aesop_git,
        aesop_rev=tag,
        jsonl_version_pin=jsonl_version_pin,
    )


def drive_putnam_files(
    lean_tag: str,
    *,
    jsonl_version_pin: str,
    pin_fn: Callable[..., Any],
    lakefile_fn: Callable[[str], str],
    toolchain_fn: Callable[[str], str],
    root_fn: Callable[[], str],
    candidate_fn: Callable[[], str],
    root_relpath: str,
    candidate_relpath: str,
) -> dict[str, str]:
    """Putnam project file map. Does not clone or compile."""

    pin = pin_fn(lean_tag, jsonl_version_pin=jsonl_version_pin)
    return putnam_file_map(
        pin,
        lakefile=lakefile_fn(pin.lean_tag),
        toolchain=toolchain_fn(pin.lean_tag),
        root=root_fn(),
        candidate=candidate_fn(),
        root_relpath=root_relpath,
        candidate_relpath=candidate_relpath,
    )


def assumption_digest(
    *,
    max_heartbeats: int,
    lean_num_threads: int,
    no_new_axioms: bool,
    digest_fn: Callable[[Mapping[str, Any]], str],
) -> str:
    """Digest of the measurement assumptions. Not a lake admit."""

    return digest_fn(
        {
            "lean_num_threads": lean_num_threads,
            "maxHeartbeats": max_heartbeats,
            "no_new_axioms": no_new_axioms,
        }
    )


def putnam_file_map(
    pin: PutnamPin,
    *,
    lakefile: str,
    toolchain: str,
    root: str,
    candidate: str,
    root_relpath: str,
    candidate_relpath: str,
) -> dict[str, str]:
    from jevops.outer import dumps_sorted

    return {
        "lakefile.lean": lakefile,
        "lean-toolchain": toolchain,
        root_relpath: root,
        candidate_relpath: candidate,
        "pins.json": dumps_sorted(pin.to_dict(), indent=2, newline=True),
    }


def collect_bake_jobs(
    records: Sequence[Mapping[str, Any]],
    catalog: BakeCatalog,
    *,
    pin_fn: Callable[[Any], Sequence[VersionPin]],
    putnam_pin_fn: Callable[[str, str], PutnamPin],
    url_key_fn: Callable[[str], str],
    error_cls: type[BaseException] = ValueError,
) -> list[BakeJob]:
    """Group warmup records into repo then Putnam lake jobs. Strata-first order."""

    from jevops.outer import group_append, group_get, require_len, unique_append

    require_len(
        records,
        catalog.warmup_n,
        error_cls=error_cls,
        fmt="warmup JSONL must contain {n} records, got {got}",
    )
    repo_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    putnam_groups: dict[str, dict[str, Any]] = {}
    for record in records:
        name = str(record.get("name") or "")
        source = str(record.get("source") or "")
        if source not in catalog.source_order:
            raise error_cls(f"{name}: unknown source {source!r}")
        url = record.get("url") or ""
        file_path = record.get("file_path") or ""
        if not isinstance(url, str) or not isinstance(file_path, str):
            raise error_cls(f"{name}: url and file_path must be strings")
        pins = list(pin_fn(record.get("version_info")))
        if source == catalog.putnam_source:
            if url.strip() or file_path.strip():
                raise error_cls(
                    f"{name}: Putnam url/file_path must be empty; do not guess a PutnamBench GitHub URL"
                )
            header = record.get("header") or ""
            if (
                not isinstance(header, str)
                or catalog.mathlib_needle not in header
                or catalog.aesop_needle not in header
            ):
                raise error_cls(f"{name}: Putnam header must import Mathlib and Aesop")
            for pin in pins:
                group = group_get(
                    putnam_groups,
                    pin.lean_tag,
                    factory=lambda p=pin: {"names": [], "commit": p.git_commit},
                )
                if group["commit"] != pin.git_commit:
                    raise error_cls(
                        f"Putnam tag {pin.lean_tag} has disagreeing JSONL pins "
                        f"{group['commit']!r} vs {pin.git_commit!r}"
                    )
                group["names"].append(name)
            continue
        if not url.strip():
            raise error_cls(f"{name}: repo record is missing url")
        if not file_path.strip():
            raise error_cls(f"{name}: repo record is missing file_path")
        for pin in pins:
            key = (source, url, pin.git_commit, pin.lean_tag)
            group = group_append(
                repo_groups,
                key,
                name,
                factory=lambda: {"names": [], "files": []},
            )
            unique_append(group["files"], file_path)

    jobs: list[BakeJob] = []
    strata_first_keys = [
        key
        for key in repo_groups
        if key[0] == catalog.strata_source and key[3] == catalog.strata_first_tag
    ]
    strata_first_keys.sort(key=lambda key: (key[1], key[2], key[3]))
    remaining_keys = [key for key in repo_groups if key not in set(strata_first_keys)]
    remaining_keys.sort(
        key=lambda key: (catalog.source_order.index(key[0]), key[1], key[3], key[2])
    )

    def repo_job(key: tuple[str, str, str, str], phase: int) -> BakeJob:
        source, url, commit, tag = key
        group = repo_groups[key]
        return BakeJob(
            kind="repo",
            source=source,
            lean_tag=tag,
            git_commit=commit,
            url=url,
            cache_key=f"repo/{url_key_fn(url)}/{commit}/{tag}",
            phase=phase,
            record_names=tuple(group["names"]),
            file_paths=tuple(group["files"]),
            module=group["files"][0],
            lakefile_required=True,
        )

    for key in strata_first_keys:
        jobs.append(repo_job(key, phase=0))
    for key in remaining_keys:
        jobs.append(repo_job(key, phase=1))
    for tag in catalog.putnam_tags:
        if tag not in putnam_groups:
            raise error_cls(f"missing Putnam JSONL tag {tag}")
        group = putnam_groups[tag]
        pin = putnam_pin_fn(tag, group["commit"])
        jobs.append(
            BakeJob(
                kind="putnam",
                source=catalog.putnam_source,
                lean_tag=tag,
                git_commit=group["commit"],
                url="",
                cache_key=f"putnam/{tag}",
                phase=2,
                record_names=tuple(group["names"]),
                file_paths=(catalog.putnam_candidate_relpath,),
                module=catalog.putnam_module,
                mathlib_rev=pin.mathlib_rev,
                aesop_rev=pin.aesop_rev,
                lakefile_required=True,
                putnambench_url=None,
            )
        )
    extra_putnam = sorted(set(putnam_groups) - set(catalog.putnam_tags))
    if extra_putnam:
        raise error_cls(f"unexpected Putnam tags {extra_putnam}")
    if (
        not jobs
        or jobs[0].source != catalog.strata_source
        or jobs[0].lean_tag != catalog.strata_first_tag
    ):
        raise error_cls("bake plan must record Strata v4.26.0 first")
    return jobs


def drive_collect_jobs(
    records: Sequence[Mapping[str, Any]],
    *,
    warmup_n: int,
    source_order: Sequence[str],
    putnam_source: str,
    strata_source: str,
    strata_first_tag: str,
    putnam_tags: Sequence[str],
    putnam_candidate_relpath: str,
    putnam_module: str,
    pin_fn: Callable[[Any], Sequence[Any]],
    putnam_pin_fn: Callable[[str, str], Any],
    url_key_fn: Callable[[str], str],
    error_cls: Any,
) -> list[BakeJob]:
    """Build the bake catalog, then group jobs. Does not run lake."""

    return collect_bake_jobs(
        records,
        BakeCatalog(
            warmup_n=warmup_n,
            source_order=tuple(source_order),
            putnam_source=putnam_source,
            strata_source=strata_source,
            strata_first_tag=strata_first_tag,
            putnam_tags=tuple(putnam_tags),
            putnam_candidate_relpath=putnam_candidate_relpath,
            putnam_module=putnam_module,
        ),
        pin_fn=pin_fn,
        putnam_pin_fn=putnam_pin_fn,
        url_key_fn=url_key_fn,
        error_cls=error_cls,
    )


def jsonl_neighbors(
    records: Sequence[Mapping[str, Any]],
    query_name: str,
    *,
    expected_n: int,
    neighbor_n: int,
    error_cls: type[BaseException] = ValueError,
    unknown_cls: Optional[type[BaseException]] = None,
    head_chars: int = 400,
) -> tuple[NeighborProof, ...]:
    """Other warmup proofs in JSONL order. Never the query."""

    from jevops.outer import as_str, exclude_named, require_len, require_startswith, require_str, require_unique_n

    unknown = unknown_cls or error_cls
    if not query_name:
        raise error_cls("query name is empty")
    names = require_unique_n(
        records,
        expected_n,
        error_cls=error_cls,
        fmt="warmup JSONL must contain {n} uniquely named records",
    )
    if query_name not in names:
        raise unknown(f"unknown warm-up problem: {query_name}")
    neighbors: list[NeighborProof] = []
    for record in exclude_named(records, query_name):
        name = str(record.get("name") or "")
        statement = require_str(
            record.get("statement"),
            error_cls=error_cls,
            empty=f"{name}: statement must be a non-empty string",
        )
        src = require_str(
            record.get("src"),
            error_cls=error_cls,
            empty=f"{name}: src must be a non-empty string",
        )
        require_startswith(
            src,
            statement,
            error_cls=error_cls,
            fmt="{name}: src does not start with the frozen statement",
            name=name,
        )
        neighbors.append(
            NeighborProof(
                name=name,
                source=str(record.get("source") or ""),
                statement=statement,
                src=src,
                header=as_str(record.get("header")),
                file_path=as_str(record.get("file_path")),
                proof_length=int(record.get("proof_length") or 0),
                url=as_str(record.get("url")),
                head_chars=head_chars,
            )
        )
    require_len(
        neighbors,
        neighbor_n,
        error_cls=error_cls,
        fmt=f"{query_name}: expected {{n}} neighbors, got {{got}}",
    )
    if any(item.name == query_name for item in neighbors):
        raise error_cls(f"{query_name}: neighbor table includes the query")
    return tuple(neighbors)


def lemma_id_digest(
    query: str,
    neighbor_names: Sequence[str],
    lemma_names: Sequence[str],
    *,
    cap: int,
    neighbor_n: int,
) -> str:
    from jevops.outer import digest_canonical

    return digest_canonical(
        {
            "cap": int(cap),
            "n_jsonl_neighbors": int(neighbor_n),
            "neighbors": list(neighbor_names),
            "query": query,
            "src_lemmas": list(lemma_names),
        }
    )


def retrieve_record(
    record: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    expected_n: int,
    neighbor_n: int,
    lemma_cap: int,
    error_cls: type[BaseException] = ValueError,
    unknown_cls: Optional[type[BaseException]] = None,
    head_chars: int = 400,
) -> Retrieval:
    from jevops.outer import require_str
    from jevops.tactics import extract_src_lemmas

    name = str(record.get("name") or "")
    src = require_str(
        record.get("src"),
        error_cls=error_cls,
        empty=f"{name}: src must be a non-empty string",
    )
    neighbors = jsonl_neighbors(
        records,
        name,
        expected_n=expected_n,
        neighbor_n=neighbor_n,
        error_cls=error_cls,
        unknown_cls=unknown_cls,
        head_chars=head_chars,
    )
    src_lemmas, uncapped = extract_src_lemmas(src, cap=lemma_cap, error_cls=error_cls)
    neighbor_names = tuple(item.name for item in neighbors)
    lemma_names = tuple(item.name for item in src_lemmas)
    lemma_ids = tuple(f"jsonl:{item}" for item in neighbor_names) + tuple(
        f"src:{item}" for item in lemma_names
    )
    return Retrieval(
        query=name,
        source=str(record.get("source") or ""),
        neighbors=neighbors,
        src_lemmas=src_lemmas,
        lemma_ids=lemma_ids,
        lemma_id_digest=lemma_id_digest(
            name, neighbor_names, lemma_names, cap=lemma_cap, neighbor_n=neighbor_n
        ),
        n_src_lemmas_uncapped=uncapped,
        arena_score=None,
        corpus_manifest_ingest=False,
        mathlib_ingest=False,
    )


def aesop_list_ok(
    considered: Sequence[str],
    imported: bool,
    *,
    tactic: str = AESOP_TACTIC,
) -> str:
    """Empty when aesop appears in the list iff Aesop is imported."""

    listed = tactic in considered
    if listed and not imported:
        return "aesop listed without an Aesop import"
    if imported and not listed:
        return "Aesop imported but aesop was omitted from the tactic list"
    return ""


def sorry_prefix_bound(
    *,
    template: str,
    statement: str,
    suffix: str,
    lake_sorry: str,
) -> bool:
    return (
        template.startswith(statement)
        and template == statement + suffix
        and template in lake_sorry
    )


def begin_path_a_receipt(
    record: Mapping[str, Any],
    pin: Any,
    *,
    relpath: str,
    template: str,
    statement: str,
    suffix: str,
    lake_sorry: str,
    aesop: bool,
    considered: Sequence[str],
    timeout: float,
    digest_fn: Callable[[str], str],
    **fields: Any,
) -> Any:
    """Seed Path A receipt from a prefix-bound sorry template. Lake still admits."""

    return init_try_receipt(
        record,
        pin,
        relpath=relpath,
        template_digest=digest_fn(template),
        prefix_bound=sorry_prefix_bound(
            template=template,
            statement=statement,
            suffix=suffix,
            lake_sorry=lake_sorry,
        ),
        aesop=aesop,
        considered=considered,
        timeout=timeout,
        **fields,
    )


def lake_source_for_tactic(
    *,
    header: str,
    statement: str,
    tactic: str,
    sorry: str = SORRY_TACTIC,
    error_cls: type[BaseException] = ValueError,
) -> str:
    from jevops.outer import require_single_token

    block = tactic
    if tactic != sorry:
        block = require_single_token(
            tactic,
            error_cls=error_cls,
            empty="tactic must be a nonempty string",
            multi_fmt="path A tries a single tactic name, not a script: {text!r}",
        ).strip()
    return lake_candidate_source(header=header, statement=statement, tactic_block=block)


def path_a_receipt_ok(
    winner: Optional[str],
    attempts: Sequence[TacticAttempt],
) -> bool:
    from pathlib import Path

    return winner is not None and all(
        not item.used_snapshot_goal and Path(item.argv[0]).name == "lake" if item.argv else False
        for item in attempts
    )


def source_relpath(
    record: Mapping[str, Any],
    *,
    putnam_source: str,
    putnam_relpath: str,
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
) -> str:
    source = str(record.get("source") or "")
    if source == putnam_source:
        return putnam_relpath
    from jevops.outer import refuse_basename

    path = str(record.get("file_path") or "")
    if not path:
        raise error_cls(f"{record.get('name')}: missing file_path")
    if refuse:
        refuse_basename(path, refuse, error_cls=error_cls, fmt="refusing {name}")
    return path


def bake_job_for_record(
    record: Mapping[str, Any],
    pin: VersionPin,
    *,
    putnam_source: str,
    strata_source: str,
    strata_first_tag: str,
    putnam_relpath: str,
    putnam_module: str,
    url_key_fn: Callable[[str], str],
) -> BakeJob:
    source = str(record.get("source") or "")
    if source == putnam_source:
        return BakeJob(
            kind="putnam",
            source=putnam_source,
            lean_tag=pin.lean_tag,
            git_commit=pin.git_commit,
            url="",
            cache_key=f"putnam/{pin.lean_tag}",
            phase=2,
            record_names=(str(record.get("name") or ""),),
            file_paths=(putnam_relpath,),
            module=putnam_module,
            lakefile_required=True,
        )
    url = str(record.get("url") or "")
    relpath = str(record.get("file_path") or "")
    return BakeJob(
        kind="repo",
        source=source,
        lean_tag=pin.lean_tag,
        git_commit=pin.git_commit,
        url=url,
        cache_key=f"repo/{url_key_fn(url)}/{pin.git_commit}/{pin.lean_tag}",
        phase=0 if source == strata_source and pin.lean_tag == strata_first_tag else 1,
        record_names=(str(record.get("name") or ""),),
        file_paths=(relpath,),
        module=relpath,
        lakefile_required=True,
    )


def prepare_lake_paths(
    record: Mapping[str, Any],
    pin: VersionPin,
    *,
    putnam_source: str,
    putnam_relpath: str,
    source_relpath_fn: Callable[[Mapping[str, Any]], str],
    putnam_dir_fn: Callable[..., Path],
    materialize_fn: Callable[..., Any],
    require_clone_fn: Callable[..., Path],
    checkout_fn: Callable[[Path, str], Any],
    skip_checkout: bool,
    network: str,
    state_root: Any,
    lakefile: str = "lakefile.lean",
) -> tuple[Path, str, Path]:
    """Putnam lake project or cached repo clone. Does not write the candidate body."""

    source = str(record.get("source") or "")
    relpath = source_relpath_fn(record)
    if source == putnam_source:
        project = putnam_dir_fn(record, pin, state_root)
        if not (Path(project) / lakefile).is_file():
            materialize_fn(pin, project)
        dest = Path(project) / putnam_relpath
        return Path(project), putnam_relpath, dest
    cwd = require_clone_fn(str(record.get("url") or ""), network, state_root)
    if not skip_checkout:
        checkout_fn(cwd, pin.git_commit)
    dest = Path(cwd) / relpath
    return Path(cwd), relpath, dest


def project_dir_for_record(
    record: Mapping[str, Any],
    pin: VersionPin,
    *,
    putnam_source: str,
    putnam_dir_fn: Callable[..., Path],
    clone_dir_fn: Callable[[str], Path],
    error_cls: type[BaseException] = ValueError,
    state_root: Any = None,
) -> Path:
    source = str(record.get("source") or "")
    if source == putnam_source:
        return putnam_dir_fn(record, pin, state_root)
    url = str(record.get("url") or "")
    if not url:
        raise error_cls(f"{record.get('name')}: repo record is missing url")
    return clone_dir_fn(url)


def close_failed_receipt(
    receipt: Any,
    exc: BaseException,
    *,
    digest_fn: Callable[[str], str],
    axiom_digest_fn: Callable[[Sequence[str]], str],
    extra: str = "",
) -> Any:
    """Fail-closed overlay. Never a lake admit."""

    receipt.error = f"{exc}{extra}" if extra else str(exc)
    receipt.ok = False
    receipt.exit_code = -1
    receipt.axiom_digest = axiom_digest_fn(getattr(receipt, "axiom_names", []) or [])
    receipt.stdout_digest = digest_fn(getattr(receipt, "stdout", "") or "")
    return receipt


def measure_overlay(
    receipt: Any,
    run_fn: Callable[[], Any],
    *,
    argv: Sequence[str],
    max_heartbeats: int,
    lean_path: str = "",
    timeout_seconds: float = 0.0,
    ikv_floor: float = IKV_DEFAULT_TIMEOUT_SECONDS,
    extra_ok: bool = True,
    sorry_tactic: bool = False,
    used_snapshot: bool = False,
    used_frontend: bool = False,
) -> Any:
    """Time an injected lake/lean run and overlay the receipt. Cache hits never admit."""

    from jevops.outer import timed_call

    result, wall_ms, cpu_ms = timed_call(run_fn)
    return overlay_measurement(
        receipt,
        fill_from_process(
            result,
            argv=argv,
            max_heartbeats=max_heartbeats,
            wall_ms=wall_ms,
            cpu_ms=cpu_ms,
            lean_path=lean_path,
            timeout_seconds=timeout_seconds,
            ikv_floor=ikv_floor,
            used_ikv=bool(getattr(receipt, "independent_kernel_verifier_used", False)),
            sorry_tactic=sorry_tactic,
            used_snapshot=used_snapshot,
            used_frontend=used_frontend,
        ),
        extra_ok=extra_ok,
    )


def path_a_fill(
    receipt: TacticTryReceipt,
    considered: Sequence[str],
    run_fn: Callable[[str], TacticAttempt],
    *,
    sorry: str = SORRY_TACTIC,
) -> TacticTryReceipt:
    """Sorry hole must fail, then Path A closers until one lake-ok."""

    sorry_attempt = run_fn(sorry)
    receipt.sorry_attempt = sorry_attempt.to_dict()
    if sorry_attempt.ok:
        receipt.error = "sorry hole must not be a successful tactic try"
        receipt.ok = False
        return receipt

    def _one(tactic: str) -> TacticAttempt:
        attempt = run_fn(tactic)
        receipt.tactics_run.append(tactic)
        return attempt

    attempts, winner = path_a_try(considered, _one)
    receipt.attempts = [item.to_dict() for item in attempts]
    receipt.winning_tactic = winner
    receipt.ok = path_a_receipt_ok(winner, attempts)
    return receipt


@dataclass
class CandidateRecord:
    kind: str
    tactics: str
    source_text: str
    admission_accepted: bool
    admission_code: str
    admission_reason: str
    compile_receipts: list[Any] = field(default_factory=list)
    valid: bool = False
    token_count: int = 0
    elab_ms: float = 0.0
    token_ratio: float = 1.0
    elab_ratio: float = 1.0
    composite: float = 1.0
    generator: str = "deterministic"
    error: str = ""
    called_leanstral: bool = False
    skipped_generate: bool = False
    hardware_class: str = "unscored-dev"
    arena_score: None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission_accepted": self.admission_accepted,
            "admission_code": self.admission_code,
            "admission_reason": self.admission_reason,
            "arena_score": None,
            "called_leanstral": self.called_leanstral,
            "compile_ok_tags": [item.lean_tag for item in self.compile_receipts if getattr(item, "ok", False)],
            "compile_n": len(self.compile_receipts),
            "composite": self.composite,
            "elab_ms": self.elab_ms,
            "elab_ratio": self.elab_ratio,
            "error": self.error,
            "generator": self.generator,
            "hardware_class": self.hardware_class,
            "kind": self.kind,
            "skipped_generate": self.skipped_generate,
            "sorryAx": any(getattr(item, "sorryAx", False) for item in self.compile_receipts),
            "tactic_chars": len(self.tactics),
            "token_count": self.token_count,
            "token_ratio": self.token_ratio,
            "valid": self.valid,
        }


def failed_candidate(
    *,
    kind: str,
    code: str,
    reason: str,
    generator: str,
    error: str = "",
    hardware_class: str = "unscored-dev",
    called_leanstral: bool = True,
    skipped_generate: bool = False,
) -> CandidateRecord:
    """Fail-closed candidate with no tactic block. Not a lake admit."""

    return CandidateRecord(
        kind=kind,
        tactics="",
        source_text="",
        admission_accepted=False,
        admission_code=code,
        admission_reason=reason,
        generator=generator,
        called_leanstral=called_leanstral,
        skipped_generate=skipped_generate,
        error=error or reason,
        hardware_class=hardware_class,
        arena_score=None,
    )


def generation_skip_reason(
    generation: Any,
    *,
    probe_ok: bool,
    down_msg: str = "docker0 down; skip generate; keep reference",
) -> tuple[bool, str]:
    skipped = bool(getattr(generation, "skipped", False)) or not probe_ok
    if skipped:
        return True, str(getattr(generation, "error", "") or down_msg)
    err = str(getattr(generation, "error", "") or "")
    return False, err


def append_generated(
    candidates: list[Any],
    *,
    called: bool,
    skipped: bool,
    generation: Any,
    cap: int,
    extract_fn: Callable[[str], str],
    evaluate_fn: Callable[[str, Any], Any],
    generator_default: str,
    hardware_class: str,
) -> list[Any]:
    """Append a generated or fail-closed candidate. Does not write Lean."""

    if called and not skipped and len(candidates) < int(cap):
        tactics = extract_fn(getattr(generation, "text", "") or "")
        if not tactics:
            identity = getattr(generation, "identity", None)
            candidates.append(
                failed_candidate(
                    kind="generated",
                    code="empty_generation",
                    reason="Leanstral returned no tactic block",
                    generator=str(getattr(identity, "resolved_provider", "") or generator_default),
                    error=str(getattr(generation, "error", "") or "empty tactic block"),
                    hardware_class=hardware_class,
                )
            )
        else:
            candidates.append(evaluate_fn(tactics, generation))
        return candidates
    if called and getattr(generation, "error", "") and not skipped:
        candidates.append(
            failed_candidate(
                kind="generated",
                code="generate_error",
                reason=str(generation.error),
                generator=generator_default,
                error=str(generation.error),
                hardware_class=hardware_class,
            )
        )
    return candidates


def catch_trace(trace_fn: Optional[Callable[[], Any]]) -> dict[str, Any]:
    if trace_fn is None:
        return {}
    try:
        return dict(trace_fn() or {})
    except Exception:
        return {}


def require_text(text: Any, *, error_cls: Any, msg: str = "Leanstral returned a non-text payload") -> str:
    if not isinstance(text, str):
        raise error_cls(msg)
    return text


def make_candidate(
    *,
    kind: str,
    tactics: str,
    source_text: str,
    admission_accepted: bool,
    admission_code: str,
    admission_reason: str,
    generator: str,
    token_count: int,
    hardware_class: str = "unscored-dev",
    called_leanstral: bool = False,
    skipped_generate: bool = False,
    error: str = "",
) -> CandidateRecord:
    """Build a candidate before lake. Admission is lexical, not a lake admit."""

    return CandidateRecord(
        kind=kind,
        tactics=tactics,
        source_text=source_text,
        admission_accepted=bool(admission_accepted),
        admission_code=str(admission_code),
        admission_reason=str(admission_reason),
        generator=generator,
        called_leanstral=called_leanstral,
        skipped_generate=skipped_generate,
        error=error,
        token_count=int(token_count),
        hardware_class=hardware_class,
        arena_score=None,
    )


def attach_compile(
    candidate: CandidateRecord,
    receipts: Sequence[Any],
    *,
    hardware_class: str,
    elab_fn: Callable[[Sequence[Any]], float],
) -> CandidateRecord:
    """Attach lake receipts. Lake is the oracle."""

    from jevops.outer import first_where

    rows = list(receipts or ())
    for item in rows:
        if hasattr(item, "hardware_class"):
            item.hardware_class = hardware_class
    candidate.compile_receipts = rows
    candidate.elab_ms = float(elab_fn(rows) or 0.0)
    hit = first_where(rows, lambda item: bool(getattr(item, "error", None)))
    if hit is not None and not candidate.error:
        candidate.error = str(hit.error)
    return candidate


def failure_row(
    candidate: Any,
    *,
    hardware_class: str,
    failing_tags: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "admission_accepted": getattr(candidate, "admission_accepted", None),
        "admission_code": getattr(candidate, "admission_code", None),
        "arena_score": None,
        "error": getattr(candidate, "error", None),
        "failing_tags": list(failing_tags or ()),
        "generator": getattr(candidate, "generator", None),
        "hardware_class": hardware_class,
        "kind": getattr(candidate, "kind", None),
        "valid": getattr(candidate, "valid", None),
    }


@dataclass
class ProblemResult:
    name: str
    source: str
    header: str
    statement: str
    phases: list[str]
    health_ok: bool
    called_leanstral: bool
    skipped_generate: bool
    skip_reason: str
    retrieval_digest: str
    n_neighbors: int
    n_src_lemmas: int
    candidates: list[CandidateRecord]
    kept: Optional[CandidateRecord]
    failures: list[dict[str, Any]]
    hardware_class: str = "unscored-dev"
    hammers: str = "off"
    typesafe: str = "off"
    generator: str = "deterministic"
    loop_version: str = "v1"
    arena_score: None = None
    official_score: None = None

    def to_dict(self) -> dict[str, Any]:
        kept = self.kept
        return {
            "arena_score": None,
            "called_leanstral": self.called_leanstral,
            "candidates": [item.to_dict() for item in self.candidates],
            "failures": list(self.failures),
            "failures_retained": True,
            "generator": self.generator,
            "hammers": self.hammers,
            "hardware_class": self.hardware_class,
            "header_chars": len(self.header),
            "health_ok": self.health_ok,
            "kept_kind": None if kept is None else kept.kind,
            "kept_valid": False if kept is None else kept.valid,
            "local_proxy_composite": None if kept is None else kept.composite,
            "local_proxy_elab_ms": None if kept is None else kept.elab_ms,
            "local_proxy_tokens": None if kept is None else kept.token_count,
            "loop_version": self.loop_version,
            "n_candidates": len(self.candidates),
            "n_failures": len(self.failures),
            "n_neighbors": self.n_neighbors,
            "n_src_lemmas": self.n_src_lemmas,
            "name": self.name,
            "official_score": None,
            "phases": list(self.phases),
            "retrieval_digest": self.retrieval_digest,
            "skip_reason": self.skip_reason,
            "skipped_generate": self.skipped_generate,
            "source": self.source,
            "statement_chars": len(self.statement),
            "typesafe": self.typesafe,
        }


def pack_problem_result(
    split: Any,
    *,
    phases: Sequence[str],
    probe: Any,
    called: bool,
    skipped: bool,
    skip_reason: str,
    retrieval: Any,
    candidates: Sequence[CandidateRecord],
    kept: Optional[CandidateRecord],
    failures: Sequence[Mapping[str, Any]],
    hardware_class: str,
    hammers: str,
    typesafe: str,
    generator: str,
    loop_version: str,
    result_cls: Any = None,
) -> ProblemResult:
    """Warm-up problem result. Arena scores stay None."""

    cls = result_cls or ProblemResult
    return cls(
        name=getattr(split, "name", ""),
        source=getattr(split, "source", ""),
        header=getattr(split, "header", ""),
        statement=getattr(split, "statement", ""),
        phases=list(phases or ()),
        health_ok=bool(getattr(probe, "ok", False)),
        called_leanstral=bool(called),
        skipped_generate=bool(skipped),
        skip_reason=str(skip_reason or ""),
        retrieval_digest=str(getattr(retrieval, "lemma_id_digest", "") or ""),
        n_neighbors=len(getattr(retrieval, "neighbors", ()) or ()),
        n_src_lemmas=len(getattr(retrieval, "src_lemmas", ()) or ()),
        candidates=list(candidates or ()),
        kept=kept,
        failures=list(failures or ()),
        hardware_class=hardware_class,
        hammers=hammers,
        typesafe=typesafe,
        generator=generator,
        loop_version=loop_version,
        arena_score=None,
        official_score=None,
    )


def admission_receipt(
    result: Any,
    *,
    hardware_class: str,
) -> dict[str, Any]:
    return {
        "arena_score": None,
        "candidates": [
            {
                "accepted": getattr(item, "admission_accepted", None),
                "code": getattr(item, "admission_code", None),
                "kind": getattr(item, "kind", None),
                "reason": getattr(item, "admission_reason", None),
            }
            for item in getattr(result, "candidates", ()) or ()
        ],
        "hardware_class": hardware_class,
        "name": getattr(result, "name", ""),
    }


def problem_receipt_json(
    result: Any,
    *,
    schema: str,
    hammers: str,
    hardware_class: str,
    loop_version: str,
    typesafe: str,
    warmup_sha256: str,
    compile_records: Sequence[Mapping[str, Any]],
    candidate_text: str,
) -> dict[str, Any]:
    kept = getattr(result, "kept", None)
    return {
        "schema": schema,
        "accepted": bool(kept is not None and getattr(kept, "valid", False)),
        "arena_score": None,
        "candidate": candidate_text,
        "failures_retained": True,
        "generator": getattr(result, "generator", ""),
        "hammers": hammers,
        "hardware_class": hardware_class,
        "header": getattr(result, "header", ""),
        "kept_kind": None if kept is None else getattr(kept, "kind", None),
        "loop_version": loop_version,
        "name": getattr(result, "name", ""),
        "official_score": None,
        "score": None,
        "source": getattr(result, "source", ""),
        "statement": getattr(result, "statement", ""),
        "typesafe": typesafe,
        "warmup_sha256": warmup_sha256,
        "compile_records": list(compile_records or ()),
    }


def drive_problem_receipt(
    result: Any,
    dest_dir: Any,
    *,
    hardware_class: str,
    schema: str,
    hammers: str,
    loop_version: str,
    typesafe: str,
    warmup_sha256: str,
    index: Mapping[str, str],
) -> dict[str, Any]:
    """Write kept candidate, compile receipts, and problem JSON. Not a lake admit."""

    from jevops.outer import attr_or, first_truthy, index_paths, overlay_map, path_safe, write_tree

    kept = getattr(result, "kept", None)
    candidate_text = first_truthy(attr_or(kept, "source_text", ""), default="")
    receipt_files, compile_records = compile_receipt_files(kept, hardware_class=hardware_class)
    files = overlay_map(
        overlay_map({"candidate.lean": candidate_text}, **overlay_map(receipt_files)),
        **{
            "problem.json": problem_receipt_json(
                result,
                schema=schema,
                hammers=hammers,
                hardware_class=hardware_class,
                loop_version=loop_version,
                typesafe=typesafe,
                warmup_sha256=warmup_sha256,
                compile_records=compile_records,
                candidate_text=candidate_text,
            ),
            "result.json": result.to_dict(),
            "admission.json": admission_receipt(result, hardware_class=hardware_class),
        },
    )
    paths = write_tree(Path(dest_dir) / path_safe(getattr(result, "name", "")), files)
    return index_paths(paths, index)


def drive_warmup_batch(
    *,
    jsonl: Any,
    names: Optional[Sequence[str]],
    limit: Optional[int],
    health: Any,
    generate: Optional[Callable[..., str]],
    get_trace: Optional[Callable[[], Mapping[str, Any]]],
    max_new_tokens: Optional[int],
    generate_timeout: Optional[float],
    compile_timeout: float,
    state_root: Optional[Any],
    elan_home: Optional[Any],
    network: str,
    skip_checkout: bool,
    receipts_dir: Optional[Any],
    plant_synthetic: bool,
    pin_env_fn: Callable[[], Any],
    load_fn: Callable[..., tuple[Any, str, Sequence[Mapping[str, Any]]]],
    plant_fn: Callable[..., Mapping[str, Any]],
    probe_factory: Callable[[], Any],
    run_fn: Callable[..., Any],
    write_fn: Callable[..., Mapping[str, Any]],
    error_cls: type[BaseException],
    generator: str,
    hammers: str,
    hardware_class: str,
    loop_version: str,
    protocol: str,
    typesafe: str,
    gates: Any,
    phases: Sequence[str],
) -> dict[str, Any]:
    """Run selected warmup records. ``run_fn`` still owns lake."""

    from jevops.outer import if_none, map_collect, optional_fn, select_limit, select_named

    pin_env_fn()
    raw, digest, records = load_fn(jsonl)
    selected = select_limit(
        select_named(records, names, error_cls=error_cls, miss_fmt="unknown warm-up names: {missing}"),
        limit,
    )
    planted = None
    if plant_synthetic:
        planted = plant_fn(selected)
        elan_home = planted["elan_home"]
        state_root = planted["state_root"]
        skip_checkout = True
        network = "deny"
    live_health = if_none(health, factory=probe_factory)
    results, written = map_collect(
        selected,
        lambda record: run_fn(
            record,
            records,
            health=live_health,
            generate=generate,
            get_trace=get_trace,
            max_new_tokens=max_new_tokens,
            generate_timeout=generate_timeout,
            compile_timeout=compile_timeout,
            state_root=state_root,
            elan_home=elan_home,
            network=network,
            skip_checkout=skip_checkout,
        ),
        after_fn=optional_fn(
            receipts_dir is not None,
            lambda result: list(write_fn(result, Path(receipts_dir)).values()),
        ),
    )
    return warmup_batch_payload(
        digest=digest,
        results=results,
        health_ok=bool(live_health.ok),
        jsonl_bytes=len(raw),
        n_records=len(records),
        planted=bool(planted),
        written=written,
        generator=generator,
        hammers=hammers,
        hardware_class=hardware_class,
        loop_version=loop_version,
        protocol=protocol,
        typesafe=typesafe,
        gates=gates,
        phases=phases,
    )


def drive_fol_canary(
    spec: Mapping[str, Any],
    *,
    goal_cls: Callable[..., Any],
    solve_fn: Callable[..., Mapping[str, Any]],
    kernel_fn: Callable[[str, str], Mapping[str, Any]],
    redact_fn: Callable[[Any], Any],
    base_url: str,
    max_tokens: int = 256,
    leanstral_timeout: float = 120.0,
    typesafe_timeout: float = 30.0,
) -> dict[str, Any]:
    """Propose a FOL canary and optionally check the body. Not a lake admit."""

    import time

    from jevops.outer import elapsed_ms

    goal = goal_cls(
        goal_id=str(spec["goal_id"]),
        declaration=str(spec["declaration"]),
        expected_provable=spec.get("expected_provable"),
        expected_solver_status=str(spec.get("expected_solver_status") or ""),
    )
    started = time.perf_counter()
    payload = solve_fn(
        goal,
        leanstral_base_url=base_url,
        max_tokens=max_tokens,
        leanstral_timeout=leanstral_timeout,
        typesafe_timeout=typesafe_timeout,
        call_typesafe=True,
    )
    parsed = payload.get("parsed") or {}
    body = str(parsed.get("body") or "")
    kernel = None
    if parsed.get("kind") == "proof_body" and body:
        kernel = kernel_fn(goal.declaration, body)
    expected_provable = bool(spec.get("expected_provable"))
    return redact_fn(
        {
            "kind": "fol",
            "goal_id": goal.goal_id,
            "expected_provable": expected_provable,
            "expected_solver_status": spec.get("expected_solver_status"),
            "parsed": parsed,
            "verdict": payload.get("verdict") or {},
            "kernel": kernel,
            "leanstral_usage": payload.get("leanstral_usage"),
            "leanstral_finish_reason": payload.get("leanstral_finish_reason"),
            "typesafe_skipped": payload.get("typesafe_skipped"),
            "match_expected": fol_expected_match(
                expected_provable=expected_provable,
                parsed_kind=str(parsed.get("kind") or ""),
                kernel_ok=bool(kernel and kernel.get("ok")),
                kernel_ran=kernel is not None,
            ),
            "advisory_only": True,
            "arena_score": None,
            "wall_ms": elapsed_ms(started),
        }
    )


def warmup_batch_payload(
    *,
    digest: str,
    results: Sequence[Any],
    health_ok: bool,
    jsonl_bytes: int,
    n_records: int,
    planted: bool,
    written: Sequence[str],
    generator: str,
    hammers: str,
    hardware_class: str,
    loop_version: str,
    protocol: str,
    typesafe: str,
    gates: str,
    phases: Sequence[str],
) -> dict[str, Any]:
    rows = list(results or ())
    return {
        "arena_score": None,
        "called_leanstral_when_healthy": all(item.called_leanstral for item in rows) if health_ok else True,
        "failures_retained": all(item.to_dict()["failures_retained"] for item in rows) if rows else True,
        "frozen_warmup_sha256": digest,
        "gates": gates,
        "generator": generator,
        "hammers": hammers,
        "hardware_class": hardware_class,
        "health_ok": bool(health_ok),
        "jsonl_bytes": int(jsonl_bytes),
        "llama_server_started": False,
        "lock_ex_taken_by_client": False,
        "loop_version": loop_version,
        "n_failures": sum(len(getattr(item, "failures", ()) or ()) for item in rows),
        "n_problems": len(rows),
        "n_records": int(n_records),
        "official_score": None,
        "phases": list(phases or ()),
        "planted_synthetic": bool(planted),
        "protocol": protocol,
        "receipts_written": list(written or ()),
        "results": [item.to_dict() for item in rows],
        "score": None,
        "skip_generate_only_if_docker0_down": True,
        "skipped_generate": (not health_ok),
        "typesafe": typesafe,
        "warmup_jsonl_sha256": digest,
    }


def path_a_plan_rows(
    records: Sequence[Mapping[str, Any]],
    *,
    tactics_fn: Callable[[Mapping[str, Any]], Sequence[str]],
    aesop_fn: Callable[[Mapping[str, Any]], bool],
    aesop_tactic: str = "aesop",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records or ():
        considered = list(tactics_fn(record) or ())
        rows.append(
            {
                "aesop_imported": bool(aesop_fn(record)),
                "name": str(record.get("name") or ""),
                "source": str(record.get("source") or ""),
                "tactics": considered,
                "aesop_in_list": aesop_tactic in considered,
            }
        )
    return rows


def plan_loop_problems(
    records: Sequence[Mapping[str, Any]],
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    pins_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
) -> list[dict[str, Any]]:
    """Per-record plan rows. split_fn is the consumer prefix-bind."""

    rows: list[dict[str, Any]] = []
    for record in records or ():
        split = split_fn(record)
        pins = list(pins_fn(record) or ())
        rows.append(
            {
                "name": getattr(split, "name", record.get("name")),
                "n_tags": len(pins),
                "source": getattr(split, "source", record.get("source")),
                "tags": [getattr(pin, "lean_tag", pin) for pin in pins],
            }
        )
    return rows


def plan_loop_payload(
    *,
    digest: str,
    problems: Sequence[Mapping[str, Any]],
    health: Any,
    jsonl_bytes: int,
    autostart: str,
    health_url: str,
    generator: str,
    hammers: str,
    hardware_class: str,
    loop_version: str,
    protocol: str,
    typesafe: str,
    gates: str,
    phases: Sequence[str],
    tokenizer_id: str,
    token_weights: Mapping[str, float],
) -> dict[str, Any]:
    from dataclasses import asdict as _asdict

    health_row = dict(health) if isinstance(health, Mapping) else _asdict(health)
    return {
        "action_if_health_ok": "generate",
        "action_if_health_down": "skip_generate_keep_reference",
        "arena_score": None,
        "autostart": autostart,
        "docker0_health_url": health_url,
        "frozen_warmup_sha256": digest,
        "gates": gates,
        "generator": generator,
        "hammers": hammers,
        "hardware_class": hardware_class,
        "health": health_row,
        "jsonl_bytes": int(jsonl_bytes),
        "llama_server_started": False,
        "lock_ex_taken_by_client": False,
        "loop_version": loop_version,
        "must_call_leanstral_if_health_ok": True,
        "n_problems": len(problems),
        "official_score": None,
        "phases": list(phases or ()),
        "problems": list(problems or ()),
        "protocol": protocol,
        "skip_generate_only_if_docker0_down": True,
        "token_weights": dict(token_weights),
        "tokenizer_id": tokenizer_id,
        "typesafe": typesafe,
    }


def score_candidate(
    candidate: CandidateRecord,
    *,
    reference_tokens: int,
    reference_elab_ms: float,
    token_ratio_fn: Callable[[float, float], float],
    composite_fn: Callable[[float, float], float],
    all_tags_ok_fn: Callable[..., bool],
    record: Mapping[str, Any],
    reconstructed_ok: bool = False,
) -> CandidateRecord:
    """Fill token/elab ratios and validity. Compile receipts are already attached."""

    candidate.token_ratio = token_ratio_fn(candidate.token_count, reference_tokens)
    candidate.elab_ratio = token_ratio_fn(candidate.elab_ms, reference_elab_ms or candidate.elab_ms)
    candidate.composite = composite_fn(candidate.token_ratio, candidate.elab_ratio)
    tags_ok = bool(all_tags_ok_fn(record, candidate.compile_receipts))
    candidate.valid = bool(
        candidate.admission_accepted
        and tags_ok
        and not any(getattr(item, "sorryAx", False) for item in candidate.compile_receipts)
    )
    if str(candidate.kind).startswith("reference") and tags_ok and not candidate.admission_accepted:
        candidate.valid = bool(reconstructed_ok and tags_ok)
    return candidate


@dataclass
class ProofReceipt:
    name: str
    lean_tag: str
    body_digest: str
    verdict: str
    executable_paths: ExecutablePaths
    generator: str = "lake_native"
    policy: str = "open_policy_v1"
    resource: str = "unscored-dev"
    translator: str = "body-splice-v1"
    backend_id: str = "lake-env-lean"
    git_commit: str = "not-applicable"
    lean_version: str = "not-applicable"
    backend_config_digest: str = ""
    premises_digest: str = ""
    token_count: Optional[int] = None
    elab_proxy: Optional[float] = None
    hardware_class: str = "unscored-dev"
    kernel_command_template: str = "{lake} env {lean} --json {source_file}"
    candidate_cid: str = ""
    created_at: float = 0.0
    arena_score: None = None
    score: None = None
    official_score: None = None
    duckdb_used: bool = False
    inserted: bool = False
    skipped_duplicate: bool = False
    filesystem_path: str = ""
    dimensions: dict[str, str] = field(default_factory=dict)
    key_digest: str = ""

    def to_public_dict(self, *, extra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "lean_tag": self.lean_tag,
            "body_digest": self.body_digest,
            "candidate_cid": self.candidate_cid,
            "verdict": self.verdict,
            "token_count": self.token_count,
            "elab_proxy": self.elab_proxy,
            "generator": self.generator,
            "policy": self.policy,
            "resource": self.resource,
            "hardware_class": self.hardware_class,
            "executable_paths": self.executable_paths.to_dict(),
            "kernel_command_template": self.kernel_command_template,
            "dimensions": dict(self.dimensions),
            "key_digest": self.key_digest,
            "git_commit": self.git_commit,
            "lean_version": self.lean_version,
            "premises_digest": self.premises_digest,
            "arena_score": None,
            "score": None,
            "official_score": None,
            "duckdb_used": self.duckdb_used,
            "inserted": self.inserted,
            "skipped_duplicate": self.skipped_duplicate,
            "filesystem_path": self.filesystem_path,
        }
        payload.update(dict(extra or {}))
        payload["arena_score"] = None
        payload["score"] = None
        payload["official_score"] = None
        return payload


def project_authority_dimensions(
    receipt: ProofReceipt,
    catalog: Sequence[str],
    mapping: Mapping[str, str],
    *,
    error_cls: type[BaseException] = ValueError,
) -> dict[str, str]:
    wanted = frozenset(catalog)
    missing = wanted - set(mapping)
    if missing:
        raise error_cls(f"authority dimension(s) dropped: {', '.join(sorted(missing))}")
    extra = set(mapping) - wanted
    if extra:
        raise error_cls(f"unknown authority dimension(s): {', '.join(sorted(extra))}")
    empty = [name for name, value in mapping.items() if not str(value).strip()]
    if empty:
        raise error_cls(f"authority dimension(s) empty: {', '.join(empty)}")
    return dict(mapping)


@dataclass
class CompilePlan:
    records: list[dict[str, Any]]
    frozen_warmup_sha256: str
    jsonl_bytes: int
    n_records: int
    first_source: str = "strata"
    arena_score: None = None

    def first_record(
        self,
        *,
        error_cls: type[BaseException] = ValueError,
        miss: str = "warmup JSONL has no first-source record",
    ) -> dict[str, Any]:
        from jevops.outer import first_where

        return first_where(
            self.records,
            lambda record: record.get("source") == self.first_source,
            error_cls=error_cls,
            miss=miss,
        )


@dataclass
class BakePlan:
    jobs: list[BakeJob] = field(default_factory=list)
    frozen_warmup_sha256: str = ""
    jsonl_bytes: int = 0
    n_records: int = 0
    arena_score: None = None

    def first_job(self, *, error_cls: type[BaseException] = ValueError) -> BakeJob:
        if not self.jobs:
            raise error_cls("bake plan is empty")
        return self.jobs[0]


def fill_tactic_attempt(
    *,
    tactic: str,
    argv: Sequence[str],
    cwd: str,
    source_file: str,
    timeout: float,
    result: Any,
    wall_ms: float,
    cpu_ms: float,
    max_heartbeats: int,
    sorry: str = SORRY_TACTIC,
    error: str = "",
) -> TacticAttempt:
    attempt = TacticAttempt(
        tactic=tactic,
        argv=list(argv),
        cwd=cwd,
        source_file=source_file,
        timeout_seconds=timeout,
        measurement_maxHeartbeats=int(max_heartbeats),
    )
    filled = fill_from_process(
        result,
        argv=argv,
        max_heartbeats=max_heartbeats,
        wall_ms=wall_ms,
        cpu_ms=cpu_ms,
        sorry_tactic=tactic == sorry,
        used_snapshot=attempt.used_snapshot_goal,
        used_frontend=attempt.used_lean_frontend,
    )
    if error:
        filled["error"] = error
        filled["ok"] = False
    overlay_measurement(attempt, filled)
    return attempt


def drive_compile_tactics(
    record: Mapping[str, Any],
    tactics: str,
    *,
    timeout: float,
    state_root: Optional[Any],
    elan_home: Optional[Any],
    network: str,
    skip_checkout: bool,
    require_timeout_fn: Callable[[float], float],
    with_tactics_fn: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
    pins_fn: Callable[[Any], Sequence[Any]],
    source_text_fn: Callable[[Mapping[str, Any], str], str],
    project_dir_fn: Callable[..., Any],
    relpath_fn: Callable[..., str],
    write_fn: Callable[..., Any],
    compile_record_fn: Callable[..., Any],
    putnam_source: str,
    hardware_class: str,
) -> Any:
    """Lake-compile one tactic block across listed pins. The compile function owns lake."""

    timeout = require_timeout_fn(timeout)
    candidate_record = with_tactics_fn(record, tactics)
    return write_then_compile(
        record,
        tactics,
        putnam_source=putnam_source,
        pins=pins_fn(record.get("version_info")),
        candidate_record=candidate_record,
        source_text=source_text_fn(record, tactics),
        project_dir_fn=project_dir_fn,
        relpath_fn=relpath_fn,
        write_fn=write_fn,
        compile_fn=lambda rec: compile_record_fn(
            rec,
            timeout=timeout,
            state_root=state_root,
            elan_home=elan_home,
            network=network,
            require_oleans=False,
            hardware_class=hardware_class,
            skip_checkout=skip_checkout,
            abort_on_first_failure=True,
        ),
    )


def write_then_compile(
    record: Mapping[str, Any],
    tactics: str,
    *,
    putnam_source: str,
    pins: Sequence[Any],
    candidate_record: Mapping[str, Any],
    source_text: str,
    project_dir_fn: Callable[..., Path],
    relpath_fn: Callable[[Mapping[str, Any]], str],
    compile_fn: Callable[..., Any],
    write_fn: Callable[..., Any],
) -> Any:
    """Write a repo candidate then compile. Putnam lake files are already prepared."""

    if pins and str(record.get("source") or "") != putnam_source:
        dest_root = project_dir_fn(record, pins[0])
        dest = Path(dest_root) / relpath_fn(candidate_record)
        write_fn(dest, source_text)
    return compile_fn(candidate_record)


def write_putnam_candidate(
    dest: Any,
    source_text: str,
    *,
    candidate_relpath: str,
    refuse: str = "Tmp.lean",
    error_cls: type[BaseException] = ValueError,
) -> Path:
    from jevops.outer import refuse_basename, write_text

    dest_path = Path(dest)
    if dest_path.name == "Tmp":
        raise error_cls("refusing to write Putnam candidate as Tmp.lean")
    refuse_basename(
        dest_path,
        refuse,
        error_cls=error_cls,
        fmt="refusing to write Putnam candidate as {name}",
    )
    path = dest_path / candidate_relpath if dest_path.is_dir() else dest_path
    return write_text(
        path,
        source_text,
        refuse=refuse,
        error_cls=error_cls,
        refuse_fmt="refusing to write Putnam candidate as {name}",
    )


def pack_compile_view(
    receipt: Mapping[str, Any],
    *,
    token_count: int,
    errors: Sequence[Mapping[str, Any]] = (),
    sorry: bool = False,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Lake compile view. Errors/sorry are already scoped. Never an Arena score."""

    timed_out = bool(receipt.get("timed_out"))
    # Missing JSON diagnostics are not positive evidence: process launch,
    # import, and parser failures can produce no parseable Lean error rows.
    exit_code = receipt.get("exit_code")
    process_ok = type(exit_code) is int and exit_code == 0 and not timed_out
    theorem_ok = (process_ok
                  and not receipt.get("error") and not list(errors or ()) and not sorry)
    out = {
        "ok": bool(theorem_ok),
        "theorem_ok": bool(theorem_ok),
        "module_exit_0": process_ok,
        "exit_code": receipt.get("exit_code"),
        "wall_ms": receipt.get("wall_ms"),
        "error": receipt.get("error"),
        "token_count": int(token_count),
        "sorryAx": receipt.get("sorryAx"),
        "sorry_in_theorem": bool(sorry),
        "errors": list(errors or ()),
        "arena_score": None,
    }
    out.update(dict(extra or {}))
    # Diagnostic overlays must never override the admission decision.
    out["ok"] = out["theorem_ok"] = bool(theorem_ok)
    out["arena_score"] = None
    return out


@dataclass(frozen=True)
class HealthProbe:
    ok: bool
    url: str
    alias_ok: bool
    alias_url: str
    status_code: Optional[int]
    error: str
    autostart: str


def drive_health_probe(
    *,
    pin_fn: Callable[[], Any],
    get_fn: Callable[..., tuple[Any, str]],
    health_url: str,
    alias_url: str,
    timeout: float,
    autostart_key: str = "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART",
    probe_cls: Any = None,
) -> Any:
    """GET /health and the alias. Does not start a server. Not a lake admit."""

    from jevops.outer import env_str, first_truthy, http_ok

    pin_fn()
    status, error = get_fn(health_url, timeout=timeout)
    alias_status, alias_error = get_fn(alias_url, timeout=timeout)
    ok, error = http_ok(status, error)
    alias_ok, alias_error = http_ok(alias_status, alias_error)
    cls = probe_cls or HealthProbe
    return cls(
        ok=ok,
        url=health_url,
        alias_ok=alias_ok,
        alias_url=alias_url,
        status_code=status,
        error=first_truthy(error, alias_error),
        autostart=env_str(autostart_key),
    )


@dataclass(frozen=True)
class ProviderIdentity:
    requested_provider: str
    requested_model: str
    resolved_provider: str
    resolved_model: str
    fallback_used: bool
    arena_score: None = None


@dataclass(frozen=True)
class Generation:
    text: str
    identity: ProviderIdentity
    health: HealthProbe
    skipped: bool = False
    error: str = ""


def identity_from_trace(
    trace: Mapping[str, Any],
    *,
    generated: bool,
    requested_provider: str,
    requested_model: str,
    allowed: Sequence[str] = (),
    forbidden: Sequence[str] = (),
    identity_cls: Any = None,
) -> ProviderIdentity:
    """Resolved provider/model from a generation trace. Never writes Lean."""

    from jevops.outer import first_nonempty, name_fallback_used

    cls = identity_cls or ProviderIdentity
    resolved_provider = first_nonempty(
        trace,
        "effective_provider_name",
        "provider_name",
        "provider",
        default=requested_provider if generated else "",
    )
    resolved_model = first_nonempty(
        trace, "effective_model_name", "model_name", default=requested_model if generated else ""
    )
    fallback_used = name_fallback_used(
        resolved_provider,
        allowed=allowed,
        forbidden=forbidden,
    )
    return cls(
        requested_provider=requested_provider,
        requested_model=requested_model,
        resolved_provider=resolved_provider,
        resolved_model=resolved_model,
        fallback_used=fallback_used,
        arena_score=None,
    )


def refuse_if_fallback(
    identity: Any,
    *,
    error_cls: Any,
    fmt: str = "resolved provider/model is a forbidden fallback: {provider}/{model}",
) -> Any:
    if getattr(identity, "fallback_used", False):
        raise error_cls(
            fmt.format(
                provider=getattr(identity, "resolved_provider", ""),
                model=getattr(identity, "resolved_model", ""),
            )
        )
    return identity


def coalesce_limits(
    *,
    source: str = "",
    max_new: Optional[int] = None,
    timeout: Optional[float] = None,
    lookup_fn: Optional[Callable[[str], tuple[int, float]]] = None,
    default_new: int = 256,
    default_timeout: float = 90.0,
) -> tuple[int, float]:
    if source and lookup_fn is not None and (max_new is None or timeout is None):
        looked_new, looked_timeout = lookup_fn(source)
        if max_new is None:
            max_new = looked_new
        if timeout is None:
            timeout = looked_timeout
    if max_new is None:
        max_new = default_new
    if timeout is None:
        timeout = default_timeout
    return int(max_new), float(timeout)


def overlay_generate_kwargs(
    base: Mapping[str, Any],
    *,
    temperature: Optional[float] = None,
    stop: Optional[Sequence[str]] = None,
    stop_fn: Optional[Callable[[Sequence[str]], Sequence[str]]] = None,
) -> dict[str, Any]:
    """Fail-closed generate kwargs plus optional temperature/stop. No HTTP."""

    call_kwargs = dict(base or {})
    if temperature is not None:
        call_kwargs["temperature"] = float(temperature)
    if stop:
        call_kwargs["stop"] = list(stop_fn(stop) if stop_fn is not None else stop)
    return call_kwargs


def stamp_measured_receipt(
    receipt: Any,
    *,
    argv: Sequence[str],
    cwd: Any,
    run_fn: Callable[[], Any],
    max_heartbeats: int,
    lean_path: str = "",
    timeout_seconds: float = 0.0,
    extra_ok: bool = True,
    ikv_floor: float = IKV_DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Stamp argv/cwd, then overlay a timed lake/lean run. run_fn is injected."""

    receipt.argv = list(argv)
    receipt.cwd = str(cwd)
    return measure_overlay(
        receipt,
        run_fn,
        argv=argv,
        max_heartbeats=max_heartbeats,
        lean_path=lean_path,
        timeout_seconds=timeout_seconds,
        extra_ok=extra_ok,
        ikv_floor=ikv_floor,
    )


def skipped_generation(
    health: HealthProbe,
    *,
    reason: str,
    requested_provider: str = "",
    requested_model: str = "",
) -> Generation:
    return Generation(
        text="",
        identity=ProviderIdentity(
            requested_provider=requested_provider,
            requested_model=requested_model,
            resolved_provider="",
            resolved_model="",
            fallback_used=False,
            arena_score=None,
        ),
        health=health,
        skipped=True,
        error=reason,
    )


def generate_if_healthy(
    *,
    health_ok: bool,
    generate_fn: Callable[..., Any],
    skip_result: Any,
    fail_fn: Callable[[BaseException], Any],
) -> Any:
    """Call generate_fn only when healthy. Fail closed; never a fallback success."""

    if not health_ok:
        return skip_result
    try:
        return generate_fn()
    except Exception as exc:  # noqa: BLE001 — retain the failed generator call
        return fail_fn(exc)


def drive_maybe_generate(
    *,
    pin_fn: Callable[[], Any],
    autostart_env: str,
    error_cls: Any,
    health: Any,
    generate_fn: Callable[[], Any],
    skip_result: Any,
    fail_fn: Callable[[BaseException], Any],
    expected: str = "0",
) -> Any:
    """Generate only when autostart is off and health is ok. Not a lake admit."""

    from jevops.outer import require_env_eq

    pin_fn()
    require_env_eq(
        autostart_env,
        expected,
        error_cls=error_cls,
        fmt="{key} must be {expected}; refusing to generate",
    )
    return generate_if_healthy(
        health_ok=bool(getattr(health, "ok", False)),
        generate_fn=generate_fn,
        skip_result=skip_result,
        fail_fn=fail_fn,
    )


def bake_or_hit(
    job: BakeJob,
    *,
    network: str,
    execute: bool,
    require_cache_fn: Callable[..., Mapping[str, Any]],
    tag_paths_fn: Callable[[str], Mapping[str, Any]],
    materialize_fn: Callable[..., Any],
    putnam_dir_fn: Callable[..., Path],
    clone_fn: Callable[..., Path],
    checkout_fn: Callable[..., Any],
    run_lake_fn: Callable[..., Mapping[str, Any]],
    copy_oleans_fn: Callable[[Path, Path], None],
    cache_dir_fn: Callable[..., Path],
    mark_fn: Callable[[Path], None],
    olean_fn: Callable[[Path], Sequence[Any]],
    error_cls: type[BaseException] = ValueError,
    miss_cls: Optional[type[BaseException]] = None,
) -> dict[str, Any]:
    """Cache hit, fail closed under network=deny, or bake if asked. Never PATH lake."""

    miss = miss_cls or error_cls
    hit = dict(require_cache_fn(job, network="allow"))
    if hit.get("ok"):
        hit["status"] = "cache-hit"
        hit["lake_build_executed"] = False
        return hit
    if network == "deny":
        require_cache_fn(job, network="deny")
    pin = tag_paths_fn(job.lean_tag)
    if not pin.get("installed"):
        raise miss(
            "tag-pinned elan lake is not installed at "
            f"{pin.get('lake_path')}; capability gap, not PATH lake usability"
        )
    if not execute:
        return {
            "ok": False,
            "status": "ready-to-bake",
            "cache_key": job.cache_key,
            "network": network,
            "lake_build_executed": False,
            "lake_path": pin.get("lake_path"),
            "arena_score": None,
        }
    if job.kind == "putnam":
        project = putnam_dir_fn(job)
        materialize_fn(job, project)
        result = run_lake_fn(job.lean_tag, ["build"], project)
        if int(result.get("exit_code") or 0) != 0:
            raise error_cls(f"lake build failed for Putnam {job.lean_tag}: exit {result.get('exit_code')}")
        copy_oleans_fn(Path(project) / ".lake", cache_dir_fn(job) / ".lake")
    else:
        clone = clone_fn(job)
        checkout_fn(clone, job.git_commit)
        result = run_lake_fn(job.lean_tag, ["build"], clone)
        if int(result.get("exit_code") or 0) != 0:
            raise error_cls(f"lake build failed for {job.cache_key}: exit {result.get('exit_code')}")
        copy_oleans_fn(Path(clone) / ".lake", cache_dir_fn(job) / ".lake")
    cache_dir = cache_dir_fn(job)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    mark_fn(Path(cache_dir))
    return {
        "ok": True,
        "status": "baked",
        "cache_key": job.cache_key,
        "cache_dir": str(cache_dir),
        "n_oleans": len(list(olean_fn(Path(cache_dir)))),
        "network": network,
        "lake_build_executed": True,
        "arena_score": None,
    }


def drive_retrieval_prompt(
    record: Mapping[str, Any],
    retrieval: Any,
    *,
    prompt_fn: Callable[[Mapping[str, Any]], str],
    lemma_cap: int,
) -> str:
    """Base prompt plus retrieved lemma names. Not a Mathlib corpus."""

    lemmas = ", ".join(item.name for item in (getattr(retrieval, "src_lemmas", ()) or ()))
    neighbors = getattr(retrieval, "neighbors", ()) or ()
    return prompt_fn(record) + retrieval_prompt_extra(
        lemmas=lemmas,
        n_neighbors=len(neighbors),
        lemma_cap=lemma_cap,
    )


def drive_split_candidate(
    record: Mapping[str, Any],
    tactic_block: str,
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    header: Optional[str] = None,
) -> str:
    """Lake source from a prefix bind. header=None keeps the split header."""

    split = split_fn(record)
    return lake_candidate_source(
        header=split.header if header is None else header,
        statement=split.statement,
        tactic_block=tactic_block,
    )


def drive_split_tactic_source(
    record: Mapping[str, Any],
    tactic: str,
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    error_cls: Any,
) -> str:
    """One path-A tactic, or the sorry template, from a prefix bind."""

    split = split_fn(record)
    return lake_source_for_tactic(
        header=split.header,
        statement=split.statement,
        tactic=tactic,
        error_cls=error_cls,
    )


def drive_hosted_file(
    path: Any,
    *,
    read_fn: Callable[[Any], Mapping[str, Any]],
    extract_fn: Callable[[str], str],
    error_cls: Any,
) -> str:
    """Tactics from a hosted receipt file. Refuses prototype and docker0."""

    return hosted_tactics_from_payload(read_fn(path), extract_fn=extract_fn, error_cls=error_cls)


def drive_retrieval_report(
    record: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    retrieve_fn: Callable[..., Any],
    neighbor_fn: Callable[[Any], Sequence[Mapping[str, Any]]],
    lemma_cap: int,
    asdict_fn: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """Retrieve neighbors, then pack the report. Not a score."""

    retrieval = retrieve_fn(record, records)
    return pack_retrieval_report(
        retrieval,
        records=records,
        lemma_cap=lemma_cap,
        prompt_neighbors=neighbor_fn(retrieval),
        asdict_fn=asdict_fn,
    )


def drive_header_src_tactics(record: Mapping[str, Any]) -> list[str]:
    """Path-A tactic names from header and src. Not a lake run."""

    from jevops.outer import get_str

    return path_a_tactics(get_str(record, "header"), get_str(record, "src"))


def drive_text_pair_search(record: Mapping[str, Any], pattern: Any) -> bool:
    """Search header and src with a compiled pattern. Not an admit."""

    from jevops.outer import any_search, get_str

    return any_search((get_str(record, "header"), get_str(record, "src")), pattern)


def drive_receipt_digest(
    receipt: Any,
    dimensions: Mapping[str, str],
    *,
    digest_fn: Callable[[Any], str],
    schema: str,
) -> str:
    """Digest of body, dimensions, tag, and name. Does not store the body."""

    from jevops.outer import overlay_map

    return digest_fn(
        {
            "body_digest": receipt.body_digest,
            "dimensions": overlay_map(dimensions),
            "lean_tag": receipt.lean_tag,
            "name": receipt.name,
            "schema": schema,
        }
    )


def drive_overlay_probe(
    tags: Any,
    *,
    probe_fn: Callable[[Any], Mapping[str, Any]],
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay a toolchain probe. Does not compile."""

    return overlay_try_probe(probe_fn(tags), extra=dict(extra))


def drive_materialize_project(
    tag: str,
    dest: Any,
    *,
    pin: str,
    files_fn: Callable[..., Mapping[str, str]],
    write_fn: Callable[..., Any],
    refuse: str,
    error_cls: Any,
) -> Any:
    """Write a tag's lake files. Never Tmp.lean. Does not run lake."""

    return write_fn(dest, files_fn(tag, jsonl_version_pin=pin), refuse=refuse, error_cls=error_cls)


def drive_plant_named(
    dest: Any,
    *,
    package: str,
    lib: str,
    heartbeats: int,
    tag: str,
    lakefile_fn: Callable[..., str],
    toolchain_fn: Callable[[str], str],
    clone_fn: Optional[Callable[..., Any]] = None,
    url: str = "",
    state_root: Any = None,
) -> Any:
    """Plant a synthetic lakefile and toolchain. Not a live lake bake."""

    target = dest if clone_fn is None else clone_fn(url, state_root)
    return plant_synthetic_clone(
        target,
        {
            "lakefile.lean": lakefile_fn(package=package, lib=lib, max_heartbeats=heartbeats),
            "lean-toolchain": toolchain_fn(tag),
        },
    )


def drive_synthetic_oleans(
    job: Any,
    state_root: Any,
    *,
    n: int,
    cache_fn: Callable[..., Any],
    receipt_fn: Callable[[Any], Any],
    blob: bytes,
    prefix: str,
) -> Any:
    """Write dummy olean blobs. Not a live bake and not a lake admit."""

    return plant_synthetic_olean_cache(
        cache_fn(job, state_root),
        blobs={f"{prefix}{index}.olean": blob for index in range(int(n))},
        receipt=receipt_fn(job),
    )


def drive_write_split(
    record: Mapping[str, Any],
    dest: Any,
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    tactic_fn: Callable[[str], str],
    write_fn: Callable[..., Any],
    refuse: str,
    error_cls: Any,
) -> Any:
    """Write header, statement, and tactic block. Never PATH lake."""

    split = split_fn(record)
    return write_fn(
        dest,
        header=split.header,
        statement=split.statement,
        tactic_block=tactic_fn(split.body_suffix),
        refuse=refuse,
        error_cls=error_cls,
    )


def drive_load_frozen(
    path: Any,
    default: Any,
    *,
    load_fn: Callable[..., Any],
    digest: str,
    expected_n: int,
    fields: Sequence[str],
    mismatch_exc: Any,
    record_exc: Any,
) -> Any:
    """Load a frozen JSONL. Digest drift raises. Does not rewrite the file."""

    from jevops.outer import path_or

    return load_fn(
        path_or(path, default),
        expected_digest=digest,
        expected_n=expected_n,
        required_fields=fields,
        mismatch_exc=mismatch_exc,
        record_exc=record_exc,
    )


def drive_resolver_probe(
    tags: Any,
    *,
    resolver_cls: Callable[[], Any],
    default_tags: Sequence[str],
    elan_home_fn: Callable[[], Any],
    list_fn: Callable[[Any], Sequence[Any]],
    extra: Mapping[str, Any],
    require_installed: bool = False,
) -> dict[str, Any]:
    """Probe one resolver instance. Missing bins are not PATH lake."""

    resolver = resolver_cls()
    return drive_home_probe(
        tags,
        default_tags=default_tags,
        resolve_fn=lambda tag: resolver.resolve_tag(tag, require_installed=require_installed).to_dict(),
        elan_home_fn=elan_home_fn,
        list_fn=list_fn,
        extra=extra,
    )


def drive_normalized_toolchain(tag: str, *, normalize_fn: Callable[[str], str]) -> str:
    """Toolchain file text for a normalized tag. Does not install elan."""

    return render_lean_toolchain(normalize_fn(tag))


def drive_warmup_row(
    record: Mapping[str, Any],
    *,
    versions_fn: Callable[[Mapping[str, Any]], Sequence[str]],
) -> dict[str, Any]:
    """One warm-up table row. Not an Arena score."""

    return warmup_problem_row(record, versions=versions_fn(record))


def drive_home_probe(
    tags: Any,
    *,
    default_tags: Sequence[str],
    resolve_fn: Callable[..., Any],
    elan_home_fn: Callable[[], Any],
    extra: Optional[Mapping[str, Any]] = None,
    gap_msg: str = "",
    list_fn: Callable[[Any], Sequence[Any]] = list,
) -> dict[str, Any]:
    """Probe tag pins and record where elan lives. Missing bins are not PATH lake."""

    from jevops.outer import env_str, text_or

    base = {
        "default_elan_home": text_or(elan_home_fn()),
        "elan_home_env": env_str("ELAN_HOME"),
        "lake": False,
        "path": env_str("PATH"),
        "validation_home": text_or(Path.home()),
    }
    base.update(dict(extra or {}))
    return drive_probe_pins(
        tags,
        default_tags=default_tags,
        resolve_fn=resolve_fn,
        extra=base,
        gap_msg=gap_msg,
        list_fn=list_fn,
    )


def drive_store_receipt(
    receipt: Any,
    *,
    root: Any,
    body: Optional[str],
    duckdb_path: Any,
    parent_digest: Optional[str],
    require_duckdb: bool,
    duckdb_module: Any,
    control_flags: Sequence[Any],
    finalize_fn: Callable[..., Any],
    write_cas_fn: Callable[..., str],
    write_fs_fn: Callable[..., Any],
    connect_fn: Callable[..., Any],
    install_fn: Callable[[Any], None],
    insert_fn: Callable[..., bool],
    insert_edge_fn: Callable[..., Any],
    try_import_fn: Callable[[], Any],
    error_cls: Any,
    control_msg: str,
) -> Any:
    """Filesystem receipt, then optional INSERT. DuckDB is not the control plane."""

    from jevops.outer import first_truthy, if_none

    return persist_receipt(
        receipt,
        root=root,
        body=body,
        duckdb_path=duckdb_path,
        parent_digest=parent_digest,
        require_duckdb=require_duckdb,
        control_plane=bool(first_truthy(*control_flags, default=False)),
        finalize_fn=finalize_fn,
        write_cas_fn=write_cas_fn,
        write_fs_fn=write_fs_fn,
        connect_fn=connect_fn,
        install_fn=install_fn,
        insert_fn=insert_fn,
        insert_edge_fn=insert_edge_fn,
        try_import_fn=lambda: if_none(duckdb_module, factory=try_import_fn),
        error_cls=error_cls,
        control_msg=control_msg,
    )


def drive_listed_fixture(
    dest: Any,
    record: Mapping[str, Any],
    *,
    digest: str,
    tags_fn: Callable[[Any], Sequence[str]],
    commits_fn: Callable[[Any], Mapping[str, str]],
    **kwargs: Any,
) -> Any:
    """Write a problem fixture from listed tags. Not a lake admit."""

    info = record.get("version_info")
    return write_problem_fixture_dir(
        dest,
        record,
        digest=digest,
        tags=tags_fn(info),
        commits=commits_fn(info),
        **kwargs,
    )


def drive_pin_lakefile(
    tag: str,
    *,
    pin_fn: Callable[[str], Any],
    max_heartbeats: int,
) -> str:
    """Mathlib+Aesop lakefile for one pin. Does not clone or compile."""

    pin = pin_fn(tag)
    return render_mathlib_aesop_lakefile(
        package=pin.package,
        lib=pin.lib,
        max_heartbeats=max_heartbeats,
        mathlib_git=pin.mathlib_git,
        mathlib_rev=pin.mathlib_rev,
        aesop_git=pin.aesop_git,
        aesop_rev=pin.aesop_rev,
    )


def drive_failing_tags(
    candidate: Any,
    *,
    project_fn: Callable[..., Any],
    row_fn: Callable[..., Any],
    fields: Mapping[str, Any],
    hardware_class: str,
) -> dict[str, Any]:
    """Project compile failures. Not a lake admit."""

    failing = [item for item in getattr(candidate, "compile_receipts", ()) or () if not getattr(item, "ok", False)]
    return row_fn(candidate, hardware_class=hardware_class, failing_tags=project_fn(failing, fields))


def drive_probe_pins(
    tags: Any,
    *,
    default_tags: Sequence[str],
    resolve_fn: Callable[..., Any],
    extra: Mapping[str, Any],
    gap_msg: str = "",
    list_fn: Callable[[Any], Sequence[Any]] = list,
) -> dict[str, Any]:
    """Resolve tag pins. Missing elan is a gap, not PATH lake. Not a bake."""

    from jevops.outer import if_none

    chosen = list_fn(if_none(tags, tuple(default_tags)))
    return probe_pins(chosen, resolve_fn=resolve_fn, extra=dict(extra), gap_msg=gap_msg)


def drive_compile_pins(
    record: Mapping[str, Any],
    *,
    pins_fn: Callable[[Any], Sequence[Any]],
    compile_fn: Callable[[Any], Any],
    abort: bool,
    remaining_attr: str = "aborted_remaining_tags",
) -> list[Any]:
    """Compile each version pin. Optional abort keeps later tags unrun."""

    from jevops.outer import collect_until, optional_fn, replace_if

    return collect_until(
        pins_fn(record.get("version_info")),
        compile_fn,
        abort_fn=optional_fn(abort, lambda receipt: not getattr(receipt, "ok", False)),
        remaining_fn=lambda rest: [getattr(item, "lean_tag", "") for item in rest],
        remaining_attr=replace_if(abort, remaining_attr, ""),
    )


def drive_require_clone(
    url: str,
    *,
    network: str,
    state_root: Any,
    clone_fn: Callable[..., Any],
    deny_cls: Any,
    markers: Sequence[str] = (".git", "lakefile.lean"),
) -> Any:
    """Require a cached clone. network=deny never falls back to PATH lean."""

    from jevops.outer import replace_if, require_marked_dir

    return require_marked_dir(
        clone_fn(url, state_root),
        tuple(markers),
        error_cls=replace_if(network == "deny", deny_cls, None),
        miss=(
            f"cached clone missing for {url} under network=deny; never falling "
            "back to PATH lean or a guessed GitHub URL"
        ),
    )


def drive_judge_problem(
    record: Mapping[str, Any],
    receipts: Sequence[Any],
    *,
    frozen_digest: str,
    tags_fn: Callable[[Any], Sequence[str]],
    score_names: Sequence[str],
    bind_fn: Callable[..., Any],
    axiom_fn: Callable[[Any], bool],
    sorry_fn: Callable[[Any], bool],
    judgment_cls: Any,
) -> Any:
    """Judge one warmup receipt. Not a lake admit."""

    data = judge_warmup_receipt(
        record,
        receipts,
        frozen_digest=frozen_digest,
        tags=tags_fn(record.get("version_info")),
        score_names=tuple(score_names),
        bind_fn=bind_fn,
        axiom_ok_fn=axiom_fn,
        sorry_fn=sorry_fn,
    )
    return judgment_cls(**data)


def drive_run_pinned_lake(
    lean_tag: str,
    args: Sequence[str],
    *,
    cwd: Any,
    timeout: float,
    env: Optional[Mapping[str, str]] = None,
    elan_home: Any = None,
    paths_fn: Callable[..., Mapping[str, Any]],
    error_cls: Any,
    miss_cls: Any,
) -> dict[str, Any]:
    """Run tag-pinned lake. Never PATH lake. Not a lexical admit."""

    from jevops.outer import run_pinned_bin

    pin = paths_fn(lean_tag, elan_home=elan_home)
    return run_pinned_bin(
        [pin["lake_path"], *list(args)],
        basename="lake",
        cwd=cwd,
        env=env,
        timeout=timeout,
        error_cls=error_cls,
        miss_cls=miss_cls,
        installed=bool(pin["installed"]),
        miss=(
            "tag-pinned elan toolchain not installed at "
            f"{pin['toolchain_dir']} (lean_tag={lean_tag!r}; never falling back "
            "to PATH lean/lake)"
        ),
        timeout_fmt=f"tag-pinned lake timed out for {lean_tag}: {{error}}",
        extra={
            "lake_path": pin["lake_path"],
            "lean_path": pin["lean_path"],
            "arena_score": None,
        },
    )


def drive_write_candidate(
    lean_tag: str,
    source_text: str,
    dest: Any,
    *,
    normalize_fn: Callable[[str], str],
    job_fn: Callable[..., Any],
    dir_fn: Callable[..., Any],
    write_fn: Callable[..., Any],
    relpath: str,
    source: str,
    module: str,
    refuse: str,
    error_cls: Any,
) -> Any:
    """Write Putnam/Candidate.lean. Never Tmp.lean and never PATH lake."""

    from jevops.outer import if_none

    target = if_none(
        dest,
        factory=lambda: dir_fn(
            job_fn(
                lean_tag=normalize_fn(lean_tag),
                putnam_source=source,
                putnam_relpath=relpath,
                putnam_module=module,
            )
        ),
    )
    return write_fn(
        target,
        source_text,
        candidate_relpath=relpath,
        refuse=refuse,
        error_cls=error_cls,
    )


def drive_grok_file_command(
    workspace: Any,
    prompt_path: Any,
    *,
    dest_name: str,
    model: str,
    tools: str,
    disallowed: str,
    error_cls: Any,
    socket_env: str,
    socket_default: str,
    turns_env: str,
    turns_default: int,
    bin_name: str = "grok",
    miss: str = "grok CLI not found on PATH",
) -> list[str]:
    """Fail-closed grok CLI argv. Never docker0."""

    from jevops.outer import env_int, env_str, raise_if, which_bin

    grok_bin = which_bin(bin_name)
    raise_if(not grok_bin, error_cls, miss)
    return grok_file_argv(
        grok_bin=grok_bin,
        socket=env_str(socket_env, socket_default),
        workspace=workspace,
        model=model,
        max_turns=env_int(turns_env, turns_default, minimum=2),
        tools=tools,
        disallowed=disallowed,
        dest_name=dest_name,
        prompt_path=prompt_path,
    )


def drive_statement_report(
    record: Mapping[str, Any],
    *,
    split_fn: Callable[[Mapping[str, Any]], Any],
    tactic_fn: Callable[[str], str],
    sorry_fn: Callable[[str], str],
    admit_fn: Callable[..., Any],
    prefixes: Sequence[str],
) -> dict[str, Any]:
    """Prefix-bind report for one warmup record. Not a lake admit."""

    from dataclasses import asdict

    from jevops.outer import prefix_bind_flags

    split = split_fn(record)
    tactics = tactic_fn(split.body_suffix)
    template = sorry_fn(split.statement)
    view = admit_fn(record, "simp")
    flags = prefix_bind_flags(record["src"], record["statement"], split.body_suffix)
    return pack_statement_report(
        name=split.name,
        source=split.source,
        prefix_bind=flags["prefix_bind"],
        body_is_suffix=flags["body_is_suffix"],
        reconstructed_src=split.reconstructed_src == record["src"],
        statement_chars=len(split.statement),
        body_chars=len(split.body_suffix),
        header_chars=len(split.header),
        body_starts_with_by=any(split.body_suffix.startswith(prefix) for prefix in prefixes),
        tactic_block_chars=len(tactics),
        template_starts_with_statement=template.startswith(split.statement),
        template_sorry_count=template.count("sorry"),
        admission_simp=asdict(view),
        header_not_in_src=(not split.header.strip()) or (not record["src"].startswith(split.header)),
    )


def drive_project_dimensions(
    receipt: Any,
    *,
    dimensions: Sequence[str],
    assumptions_fn: Callable[[], str],
    premises_fn: Callable[[], str],
    backend_fn: Callable[[], str],
    ir: str,
    property_name: str,
    error_cls: Any,
) -> dict[str, str]:
    """Project closed authority dimensions. Missing keys fail closed."""

    from jevops.outer import or_call

    premises = or_call(receipt.premises_digest, premises_fn)
    backend_config = or_call(receipt.backend_config_digest, backend_fn)
    mapping = {
        "ir": ir,
        "property": property_name,
        "assumptions": assumptions_fn(),
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
    return project_authority_dimensions(receipt, dimensions, mapping, error_cls=error_cls)


def drive_require_cache(
    job: Any,
    *,
    network: str,
    state_root: Any = None,
    present_fn: Callable[..., bool],
    cache_dir_fn: Callable[..., Any],
    olean_count_fn: Callable[[Any], int],
    error_cls: Any,
) -> dict[str, Any]:
    """Cache hit, or fail closed under network=deny. Never PATH lake."""

    from jevops.outer import hit_or_miss, overlay_map, text_or

    present = present_fn(job, state_root)
    cache_dir = cache_dir_fn(job, state_root)
    base = {
        "cache_key": job.cache_key,
        "cache_dir": text_or(cache_dir),
        "network": network,
        "arena_score": None,
    }
    return hit_or_miss(
        present,
        deny=network == "deny",
        error_cls=error_cls,
        deny_msg=(
            "olean cache missing for "
            f"{job.cache_key} under network=deny; first lake build is hours and "
            "must be pre-vendored before the 48h clock. Never falling back to "
            "PATH lean, Tmp.lean, or a guessed PutnamBench GitHub URL."
        ),
        hit=overlay_map(base, ok=True, status="cache-hit", n_oleans=olean_count_fn(cache_dir)),
        miss=overlay_map(base, ok=False, status="cache-missing", n_oleans=0),
    )


def drive_loaded_plan(
    path: Any,
    *,
    default_path: Any,
    load_fn: Callable[..., tuple[Any, str, Sequence[Any]]],
    build_fn: Callable[[Any, str, Sequence[Any]], Any],
) -> Any:
    """Load a frozen JSONL and build a plan. Does not compile."""

    from jevops.outer import path_or

    raw, digest, records = load_fn(path_or(path, default_path))
    return build_fn(raw, digest, records)


def drive_plan_loop(
    path: Any,
    *,
    load_fn: Callable[..., tuple[Any, str, Sequence[Any]]],
    pin_fn: Callable[[], Any],
    probe_fn: Callable[[], Any],
    problems_fn: Callable[[Sequence[Any]], Sequence[Mapping[str, Any]]],
    autostart_env: str,
    health_url: str,
    generator: str,
    hammers: str,
    hardware_class: str,
    loop_version: str,
    protocol: str,
    typesafe: str,
    gates: str,
    phases: Sequence[str],
    tokenizer_id: str,
    token_weights: Mapping[str, float],
) -> dict[str, Any]:
    """Warmup loop plan from health plus records. Does not generate or compile."""

    from jevops.outer import env_str

    raw, digest, records = load_fn(path)
    pin_fn()
    health = probe_fn()
    return plan_loop_payload(
        digest=digest,
        problems=problems_fn(records),
        health=health,
        jsonl_bytes=len(raw),
        autostart=env_str(autostart_env),
        health_url=health_url,
        generator=generator,
        hammers=hammers,
        hardware_class=hardware_class,
        loop_version=loop_version,
        protocol=protocol,
        typesafe=typesafe,
        gates=gates,
        phases=phases,
        tokenizer_id=tokenizer_id,
        token_weights=token_weights,
    )


def drive_bake_job(
    job: Any,
    *,
    network: str,
    execute: bool,
    root: Any,
    timeout: float,
    require_cache_fn: Callable[..., Mapping[str, Any]],
    tag_paths_fn: Callable[[str], Mapping[str, Any]],
    materialize_fn: Callable[..., Any],
    putnam_dir_fn: Callable[..., Any],
    run_lake_fn: Callable[..., Mapping[str, Any]],
    copy_oleans_fn: Callable[[Any, Any], None],
    cache_dir_fn: Callable[..., Any],
    olean_fn: Callable[[Any], Sequence[Any]],
    error_cls: type[BaseException],
    miss_cls: type[BaseException],
    git_bin: str,
    git_clone_fn: Callable[..., Any],
    git_checkout_fn: Callable[..., Any],
    url_clone_dir_fn: Callable[..., Any],
    lake_argv_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Cache hit, deny, or bake, then attach lake argv only when baked. Never PATH lake."""

    def _clone(item: Any) -> Any:
        return git_clone_fn(
            item.url,
            url_clone_dir_fn(root, item.url),
            git_bin=git_bin,
            error_cls=error_cls,
            miss_cls=miss_cls,
        )

    def _checkout(clone: Any, commit: str) -> Any:
        return git_checkout_fn(
            clone,
            commit,
            git_bin=git_bin,
            error_cls=error_cls,
            miss_cls=miss_cls,
            skip_empty=False,
            skip_missing_git=False,
        )

    def _mark(cache_dir: Any) -> None:
        cache_marker_path(Path(cache_dir)).write_text("baked\n", encoding="utf-8")

    out = bake_or_hit(
        job,
        network=network,
        execute=execute,
        require_cache_fn=lambda item, network: require_cache_fn(item, network=network, state_root=root),
        tag_paths_fn=tag_paths_fn,
        materialize_fn=materialize_fn,
        putnam_dir_fn=lambda item: putnam_dir_fn(item, root),
        clone_fn=_clone,
        checkout_fn=_checkout,
        run_lake_fn=lambda tag, args, cwd: run_lake_fn(tag, args, cwd=cwd, timeout=timeout),
        copy_oleans_fn=copy_oleans_fn,
        cache_dir_fn=lambda item: cache_dir_fn(item, root),
        mark_fn=_mark,
        olean_fn=olean_fn,
        error_cls=error_cls,
        miss_cls=miss_cls,
    )
    from jevops.outer import overlay_if_status

    return overlay_if_status(out, "baked", {"lake_argv": lake_argv_fn(getattr(job, "lean_tag", ""), "build")})


def write_candidate_if_needed(
    record: Mapping[str, Any],
    dest: Any,
    *,
    putnam_source: str,
    write_fn: Callable[..., Any],
) -> None:
    """Write the candidate when Putnam or the dest file is missing. Never PATH lean."""

    source = str(record.get("source") or "")
    if source == putnam_source or not Path(dest).is_file():
        write_fn(record, dest)


def lake_supervisor_fields(
    *,
    threads: Any,
    elan_home: Any,
    supervisor_dir: Any,
    process_env_key: str,
) -> dict[str, str]:
    """Env overlay for tag-pinned lake. IndependentKernelVerifier is unused."""

    return {
        "LEAN_NUM_THREADS": str(threads),
        "ELAN_HOME": str(elan_home),
        process_env_key: str(supervisor_dir),
    }


def plan_from_records(
    records: Sequence[Mapping[str, Any]],
    digest: str,
    jsonl_bytes: int,
    *,
    first_source: str = "strata",
    cls: Any = None,
) -> CompilePlan:
    """Warmup compile plan. Arena score stays None."""

    plan_cls = cls or CompilePlan
    rows = [dict(item) for item in records]
    return plan_cls(
        records=rows,
        frozen_warmup_sha256=str(digest),
        jsonl_bytes=int(jsonl_bytes),
        n_records=len(rows),
        first_source=first_source,
        arena_score=None,
    )


def plan_bake_from_jobs(
    jobs: Sequence[BakeJob],
    digest: str,
    jsonl_bytes: int,
    n_records: int,
    *,
    cls: Any = None,
) -> BakePlan:
    """Warmup bake plan. Arena score stays None."""

    plan_cls = cls or BakePlan
    return plan_cls(
        jobs=list(jobs),
        frozen_warmup_sha256=str(digest),
        jsonl_bytes=int(jsonl_bytes),
        n_records=int(n_records),
        arena_score=None,
    )


FAKE_LAKE_EXEC = """#!/usr/bin/python3.12
import os
import sys

args = sys.argv[1:]
if not args or args[0] != "env" or len(args) < 2:
    sys.stderr.write("lra-fake-lake: expected 'env <lean> ...'\\n")
    sys.exit(2)
os.execv(args[1], args[1:])
"""

FAKE_LAKE_PATH_A = """#!/usr/bin/python3.12
import os
import sys

args = sys.argv[1:]
if not args or args[0] != "env" or len(args) < 2:
    sys.stderr.write("lra-021-fake-lake: expected 'env <lean> ...'\\n")
    sys.exit(2)
os.execv(args[1], args[1:])
"""

FAKE_LEAN_COMPILE = """#!/usr/bin/python3.12
import json
import sys
from pathlib import Path

argv = sys.argv[1:]
heartbeats = None
source = None
for arg in argv:
    if arg.startswith("-DmaxHeartbeats="):
        try:
            heartbeats = int(arg.split("=", 1)[1])
        except ValueError:
            heartbeats = -1
    elif arg == "--json":
        continue
    elif not arg.startswith("-"):
        source = arg

if heartbeats is None or heartbeats <= 0:
    sys.stderr.write("measurement maxHeartbeats must be finite and positive\\n")
    sys.exit(3)
if source is None:
    sys.stderr.write("missing source file\\n")
    sys.exit(4)
path = Path(source)
if not path.is_file():
    sys.stderr.write(f"source not found: {source}\\n")
    sys.exit(4)
text = path.read_text(encoding="utf-8")
sorry = "sorry" in text.split() or "sorryAx" in text or "admit" in text.split()
decl = path.stem.replace(".", "_") or "lra_candidate"
if sorry:
    print(json.dumps({"severity": "warning", "data": "hasSorry", "pos": {"line": 1, "column": 0}}))
    print(f"#print axioms {decl}")
    print(f"{decl} : sorryAx")
    sys.exit(1)
print(json.dumps({"severity": "information", "data": "ok", "pos": {"line": 1, "column": 0}}))
print(f"#print axioms {decl}")
print(f"{decl} : []")
sys.exit(0)
"""

FAKE_LEAN_PATH_A = r"""#!/usr/bin/python3.12
import json
import re
import sys
from pathlib import Path

argv = sys.argv[1:]
heartbeats = None
source = None
has_json = False
for arg in argv:
    if arg.startswith("-DmaxHeartbeats="):
        try:
            heartbeats = int(arg.split("=", 1)[1])
        except ValueError:
            heartbeats = -1
    elif arg == "--json":
        has_json = True
    elif not arg.startswith("-"):
        source = arg

if not has_json:
    sys.stderr.write("lra-021-fake-lean: expected --json\n")
    sys.exit(2)
if heartbeats is None or heartbeats <= 0:
    sys.stderr.write("measurement maxHeartbeats must be finite and positive\n")
    sys.exit(3)
if source is None:
    sys.stderr.write("missing source file\n")
    sys.exit(4)
path = Path(source)
if not path.is_file():
    sys.stderr.write(f"source not found: {source}\n")
    sys.exit(4)
text = path.read_text(encoding="utf-8")
if " := by\n" in text:
    tactic_block = text.rsplit(" := by\n", 1)[-1].strip()
elif " := by" in text:
    tactic_block = text.rsplit(" := by", 1)[-1].strip()
else:
    tactic_block = ""
tactic = tactic_block.split()[0] if tactic_block.split() else ""
aesop_imported = bool(re.search(r"(?m)^\s*import\s+Aesop\b", text))
unsolved = "theorem lra_unsolved" in text
decl = path.stem.replace(".", "_") or "lra_candidate"


def fail(message: str, sorry: bool = False) -> None:
    payload = {"severity": "error", "data": message, "pos": {"line": 1, "column": 0}}
    if sorry:
        payload["data"] = "hasSorry"
        payload["severity"] = "warning"
    print(json.dumps(payload))
    print(f"#print axioms {decl}")
    print(f"{decl} : sorryAx" if sorry else f"{decl} : []")
    sys.exit(1)


def succeed() -> None:
    print(json.dumps({"severity": "information", "data": "ok", "pos": {"line": 1, "column": 0}}))
    print(f"#print axioms {decl}")
    print(f"{decl} : []")
    sys.exit(0)


if tactic == "sorry":
    fail("sorry hole", sorry=True)
if unsolved:
    fail(f"unsolved under {tactic}")
if tactic == "rfl":
    fail("rfl failed on lake-project goal")
if tactic == "aesop":
    if aesop_imported:
        succeed()
    fail("unknown identifier 'aesop' (Aesop not imported)")
if tactic in {"decide", "omega", "simp_all"}:
    if aesop_imported:
        fail(f"{tactic} failed; Putnam synthetic closes with aesop")
    succeed()
fail(f"unknown tactic {tactic!r}")
"""


def plant_fake_toolchain(
    elan_home: Any,
    lean_tag: str,
    *,
    dirname_fn: Callable[[str], str],
    files: Mapping[str, str],
) -> Path:
    """Plant tag-pinned lake/lean scripts. Fake bodies live in FAKE_* constants."""

    from jevops.outer import join_under, plant_executables

    toolchain_dir = join_under(elan_home, "toolchains", dirname_fn(lean_tag), "bin")
    plant_executables(toolchain_dir, files)
    return Path(toolchain_dir)


def plant_synthetic_olean_cache(
    cache_dir: Any,
    *,
    blobs: Mapping[str, bytes],
    receipt: Mapping[str, Any],
    marker_text: str = "synthetic\n",
    receipt_name: str = "bake-receipt.json",
    marker_name: str = "BAKED",
    build_parts: Sequence[str] = (".lake", "build", "lib"),
) -> Path:
    """Write dummy oleans. Not a live lake bake. Blob bytes are injected."""

    from jevops.outer import join_under, write_blobs, write_json

    root = Path(cache_dir)
    build_dir = join_under(root, *build_parts)
    write_blobs(build_dir, blobs)
    write_json(root / receipt_name, dict(receipt))
    (root / marker_name).write_text(marker_text, encoding="utf-8")
    return root


def plant_synthetic_clone(clone: Any, files: Mapping[str, str]) -> Path:
    """Git skeleton with injected lakefile/toolchain text. Not a live clone."""

    from jevops.outer import plant_git_skeleton

    return plant_git_skeleton(clone, files=files)


def write_sorry_or_tactic(
    dest: Any,
    *,
    tactic: str,
    sorry: str,
    sorry_fn: Callable[[], str],
    tactic_fn: Callable[[], str],
    write_fn: Callable[..., Any],
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
    refuse_fmt: str = "refusing to write {name}",
) -> Any:
    """Write sorry-hole or tactic lake source. Never Tmp.lean."""

    text = sorry_fn() if tactic == sorry else tactic_fn()
    return write_fn(dest, text, refuse=refuse, error_cls=error_cls, refuse_fmt=refuse_fmt)


def pins_for_source(
    record: Mapping[str, Any],
    *,
    putnam_source: str,
    putnam_fn: Callable[[Mapping[str, Any]], Any],
    default_fn: Callable[[Mapping[str, Any]], Any],
) -> Any:
    """Putnam pins vs installed clone pins. Never PATH lean."""

    if str(record.get("source") or "") == putnam_source:
        return putnam_fn(record)
    return default_fn(record)


def toolchain_gap_note(
    exc: BaseException,
    types: tuple[type[BaseException], ...],
    note: str,
) -> str:
    """Capability-gap suffix. Not PATH lean usability."""

    if isinstance(exc, types):
        return note
    return ""


def supervisor_env(
    state_root: Any,
    toolchain: Any,
    *,
    tmp_name: str,
    threads: Any,
    process_env_key: str,
    env_copy_fn: Callable[..., Mapping[str, str]],
    under_fn: Callable[..., Any],
    fields_fn: Callable[..., Mapping[str, str]],
) -> Mapping[str, str]:
    """Tag-pinned lake env overlay. IndependentKernelVerifier is unused."""

    supervisor_dir = under_fn(state_root, "process-supervisor", tmp_name=tmp_name)
    return env_copy_fn(
        fields_fn(
            threads=threads,
            elan_home=getattr(toolchain, "elan_home", toolchain),
            supervisor_dir=supervisor_dir,
            process_env_key=process_env_key,
        )
    )


def planted_workspace(
    tmp: Any,
    *,
    tags: Sequence[str],
    plant_fn: Callable[[Any, str], Any],
    clone_fn: Callable[[Any], Any],
) -> dict[str, Any]:
    """Elan + clone + receipts dirs under an existing temp root. Not a live bake."""

    from jevops.outer import plant_named_tags

    root = Path(tmp)
    elan_home = root / "elan"
    state_root = root / "state"
    receipts_dir = root / "receipts"
    plant_named_tags(elan_home, tags, plant_fn)
    clone = Path(clone_fn(state_root))
    return {
        "root": root,
        "elan_home": elan_home,
        "state_root": state_root,
        "receipts_dir": receipts_dir,
        "clone": clone,
    }


@contextmanager
def planted_session(
    prefix: str,
    *,
    tags: Sequence[str],
    plant_fn: Callable[[Any, str], Any],
    clone_fn: Callable[[Any], Any],
    parent: Any = None,
) -> Any:
    """temp_dir + planted_workspace. Yields the planted dirs. Not a live bake."""

    from jevops.outer import temp_dir

    with temp_dir(prefix=prefix, parent=parent) as tmp:
        yield planted_workspace(tmp, tags=tags, plant_fn=plant_fn, clone_fn=clone_fn)


def probe_pins(
    tags: Sequence[str],
    *,
    resolve_fn: Callable[[str], Mapping[str, Any]],
    extra: Optional[Mapping[str, Any]] = None,
    gap_msg: Optional[str] = None,
) -> dict[str, Any]:
    """Partition tag-pinned resolver rows. Missing tags are a capability gap, not PATH lake."""

    from jevops.outer import map_partition, unique_keep

    wanted = unique_keep(list(tags))
    pins = [dict(resolve_fn(tag)) for tag in wanted]
    installed, missing = map_partition(
        pins, lambda pin: pin.get("installed"), lambda pin: pin.get("lean_tag")
    )
    default_gap = (
        "No tag-pinned elan lean/lake binaries are installed under the "
        "resolver elan home. Paths remain tag-pinned; this is not PATH "
        "lake usability and is not IndependentKernelVerifier."
    )
    out: dict[str, Any] = {
        "arena_score": None,
        "installed_tags": installed,
        "missing_tags": missing,
        "pins": pins,
        "score": None,
        "capability_gap": (
            (gap_msg or default_gap)
            if missing and not installed
            else ""
        ),
    }
    if extra:
        out.update(dict(extra))
    return out


def compile_receipt_summary(
    receipt: Any,
    *,
    max_heartbeats: int,
    ikv_floor: float,
) -> dict[str, Any]:
    """JSON view of a lake compile receipt. IndependentKernelVerifier is unused."""

    from jevops.outer import argv_layout, nonempty

    argv = list(getattr(receipt, "argv", None) or [])
    return {
        "aborted_remaining_tags": list(getattr(receipt, "aborted_remaining_tags", None) or []),
        "argv_has_lake_env_lean": argv_layout(
            argv,
            min_len=6,
            names={0: "lake", 2: "lean"},
            eq={
                1: "env",
                3: f"-DmaxHeartbeats={int(max_heartbeats)}",
                4: "--json",
            },
        ),
        "argv_tag_pinned": argv_layout(
            argv,
            min_len=3,
            contains={
                0: str(getattr(receipt, "lean_tag", "") or ""),
                2: str(getattr(receipt, "lean_tag", "") or ""),
            },
        ),
        "axiom_digest": getattr(receipt, "axiom_digest", ""),
        "axiom_digest_hex64": len(str(getattr(receipt, "axiom_digest", "") or "")) == 64,
        "axiom_names": list(getattr(receipt, "axiom_names", None) or []),
        "cpu_ms_nonnegative": float(getattr(receipt, "cpu_ms", 0.0) or 0.0) >= 0.0,
        "exit_code": getattr(receipt, "exit_code", -1),
        "file_path": getattr(receipt, "file_path", ""),
        "git_commit": getattr(receipt, "git_commit", ""),
        "header_maxHeartbeats": getattr(receipt, "header_maxHeartbeats", None),
        "independent_kernel_verifier_timeout_seconds": getattr(
            receipt, "independent_kernel_verifier_timeout_seconds", None
        ),
        "independent_kernel_verifier_used": bool(
            getattr(receipt, "independent_kernel_verifier_used", False)
        ),
        "lake_oracle": bool(getattr(receipt, "lake_oracle", True)),
        "lean_tag": getattr(receipt, "lean_tag", ""),
        "measurement_maxHeartbeats": getattr(receipt, "measurement_maxHeartbeats", 0),
        "measurement_maxHeartbeats_finite": int(
            getattr(receipt, "measurement_maxHeartbeats", 0) or 0
        )
        > 0
        and int(getattr(receipt, "measurement_maxHeartbeats", 0) or 0) == int(max_heartbeats),
        "name": getattr(receipt, "name", ""),
        "ok": bool(getattr(receipt, "ok", False)),
        "sorryAx": bool(getattr(receipt, "sorryAx", False)),
        "source": getattr(receipt, "source", ""),
        "stdout_digest": getattr(receipt, "stdout_digest", ""),
        "stdout_nonempty": nonempty(getattr(receipt, "stdout", "") or ""),
        "printed_axioms": "#print axioms" in str(getattr(receipt, "stdout", "") or ""),
        "timeout_exceeds_ikv_30s": float(getattr(receipt, "timeout_seconds", 0.0) or 0.0)
        > float(ikv_floor),
        "timeout_seconds": getattr(receipt, "timeout_seconds", 0.0),
        "timed_out": bool(getattr(receipt, "timed_out", False)),
        "wall_ms_positive": float(getattr(receipt, "wall_ms", 0.0) or 0.0) > 0.0,
        "error": getattr(receipt, "error", ""),
        "arena_score": None,
        "score": None,
    }


def prompt_neighbors(retrieval: Retrieval, *, k: int = 4) -> list[dict[str, str]]:
    """Name / statement head / proof head slice. Full src stays on the dataclass."""

    from jevops.outer import head_seq
    from jevops.pick import project_items

    return project_items(
        head_seq(retrieval.neighbors, k),
        {
            "name": "name",
            "statement": "statement_head",
            "proof_head": "proof_head",
        },
    )


def retrieval_view(
    retrieval: Retrieval,
    *,
    src_chars: int,
    lemma_cap: int,
    prompt_k: int = 4,
) -> dict[str, Any]:
    """JSON view with truncated proofs. Full src stays on the dataclass."""

    from dataclasses import asdict as _asdict

    from jevops.outer import head_chars as _head

    return {
        "query": retrieval.query,
        "source": retrieval.source,
        "n_neighbors": len(retrieval.neighbors),
        "n_src_lemmas": len(retrieval.src_lemmas),
        "n_src_lemmas_uncapped": retrieval.n_src_lemmas_uncapped,
        "src_lemma_cap": int(lemma_cap),
        "neighbors": [
            {
                "name": item.name,
                "source": item.source,
                "statement": _head(item.statement, src_chars),
                "proof_head": _head(item.src, src_chars),
                "file_path": item.file_path,
                "url": item.url,
                "proof_length": item.proof_length,
                "src_chars": len(item.src),
                "retrieved_full_src": True,
            }
            for item in retrieval.neighbors
        ],
        "src_lemmas": [_asdict(item) for item in retrieval.src_lemmas],
        "lemma_ids": list(retrieval.lemma_ids),
        "lemma_id_digest": retrieval.lemma_id_digest,
        "prompt_neighbors": prompt_neighbors(retrieval, k=prompt_k),
        "arena_score": retrieval.arena_score,
        "corpus_manifest_ingest": retrieval.corpus_manifest_ingest,
        "mathlib_ingest": retrieval.mathlib_ingest,
        "score": None,
        "relevance_score": None,
    }


def closed_provider_identity(
    *,
    requested_provider: str,
    requested_model: str,
    identity_cls: Any = None,
) -> ProviderIdentity:
    """Unresolved identity. Never a fallback success."""

    cls = identity_cls or ProviderIdentity
    return cls(
        requested_provider=requested_provider,
        requested_model=requested_model,
        resolved_provider="",
        resolved_model="",
        fallback_used=False,
        arena_score=None,
    )


def refuse_unhealthy(
    health: Any,
    *,
    require_health: bool,
    error_cls: Any,
    fmt: str,
    **fmt_kwargs: Any,
) -> None:
    """Fail closed when docker0 /health is down. Never a Grok/HF fallback."""

    if require_health and not bool(getattr(health, "ok", False)):
        raise error_cls(fmt.format(**fmt_kwargs))


def splice_span(original: str, src: str, replacement: str) -> tuple[int, int]:
    """Line span of a one-shot src splice. Does not search for ``:=``."""

    spliced = original.replace(src, replacement, 1)
    start_at = spliced.find(replacement)
    start_line = spliced[:start_at].count("\n") + 1 if start_at >= 0 else 1
    end_line = start_line + replacement.count("\n")
    return start_line, end_line


def patch_putnam_src(record: Mapping[str, Any], tactics: str, *, statement: str) -> dict[str, Any]:
    """Putnam candidate src is statement + tactic body. Never Tmp.lean."""

    body = tactics if tactics.startswith(" := by") else " := by\n" + tactics
    patched = dict(record)
    patched["src"] = statement + body
    return patched


def filter_installed_pin_maps(
    pins: Sequence[Any],
    *,
    resolve_fn: Callable[[Any], Any],
    head: str = "",
    skip_exc: Any = Exception,
) -> list[dict[str, str]]:
    """Keep pins whose tag-pinned elan resolve succeeds. Never PATH lean."""

    kept: list[dict[str, str]] = []
    for pin in pins or ():
        try:
            resolve_fn(pin)
        except skip_exc:
            continue
        commit = str(getattr(pin, "git_commit", "") or "")
        if head and commit and commit != head:
            continue
        kept.append({str(getattr(pin, "lean_tag", "") or ""): commit})
    return kept


def hosted_tactics_from_payload(
    payload: Mapping[str, Any],
    *,
    extract_fn: Callable[[str], str],
    error_cls: type[BaseException] = ValueError,
    labs_host: str = "api.mistral.ai",
) -> str:
    """Extract tactics from a Track 1 hosted receipt. Refuse prototype/docker0."""

    if payload.get("used_prototype_endpoint") or payload.get("called_docker0"):
        raise error_cls("refusing a prototype/docker0 generation as a Track 1 candidate")
    identity = payload.get("identity") or {}
    host = identity.get("url_host")
    if "url_host" in identity and host not in {None, labs_host} and host != labs_host:
        raise error_cls(f"refusing non-Labs host {host}")
    return extract_fn(str(payload.get("text") or payload.get("text_head") or ""))


def unsolved_record(
    *,
    source: str,
    file_path: str,
    url: str,
    lean_tag: str,
    git_commit: str,
    ident: str = "lra_unsolved",
) -> dict[str, Any]:
    """Sorry hole that Path A must not close. Not a lake admit."""

    statement = f"theorem {ident} : False"
    return {
        "name": ident,
        "source": source,
        "statement": statement,
        "src": statement + " := by\nsorry",
        "header": "",
        "file_path": file_path,
        "url": url,
        "version_info": [{lean_tag: git_commit}],
        "proof_length": 5,
        "num_lines": 2,
    }


def attempt_summary(
    attempt: Mapping[str, Any],
    *,
    max_heartbeats: int,
    ikv_floor: float,
    pin_needles: Sequence[str] = ("leanprover--lean4---", "leanprover--lean4---"),
) -> dict[str, Any]:
    """JSON view of one Path A tactic try. IndependentKernelVerifier is unused."""

    from jevops.outer import argv_layout

    argv = list(attempt.get("argv") or [])
    needles = list(pin_needles)
    contains = {0: needles[0]} if needles else {}
    if len(needles) > 1:
        contains[2] = needles[1]
    return {
        "argv_has_lake_env_lean": argv_layout(
            argv,
            min_len=6,
            names={0: "lake", 2: "lean"},
            eq={
                1: "env",
                3: f"-DmaxHeartbeats={int(max_heartbeats)}",
                4: "--json",
            },
        ),
        "argv_tag_pinned": bool(str(attempt.get("cwd") or ""))
        and argv_layout(argv, min_len=3, contains=contains),
        "exit_code": attempt.get("exit_code"),
        "ok": bool(attempt.get("ok")),
        "sorryAx": bool(attempt.get("sorryAx")),
        "tactic": attempt.get("tactic"),
        "used_snapshot_goal": bool(attempt.get("used_snapshot_goal")),
        "used_lean_frontend": bool(attempt.get("used_lean_frontend")),
        "generator": attempt.get("generator"),
        "stdout_nonempty": bool(str(attempt.get("stdout") or "").strip()),
        "printed_axioms": "#print axioms" in str(attempt.get("stdout") or ""),
        "timeout_exceeds_ikv_30s": float(attempt.get("timeout_seconds") or 0.0) > float(ikv_floor),
        "arena_score": None,
        "score": None,
    }


def try_receipt_summary(
    receipt: Any,
    *,
    attempt_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    aesop_tactic: str = "aesop",
    sorry_tactic: str = "sorry",
) -> dict[str, Any]:
    """JSON view of a Path A receipt. HAMMER-006 stays a consumer constant."""

    attempts = [dict(attempt_fn(item)) for item in getattr(receipt, "attempts", None) or ()]
    sorry_raw = getattr(receipt, "sorry_attempt", None)
    sorry = dict(attempt_fn(sorry_raw)) if sorry_raw else None
    considered = list(getattr(receipt, "tactics_considered", None) or [])
    run = list(getattr(receipt, "tactics_run", None) or [])
    winner = getattr(receipt, "winning_tactic", None)
    stopped = False
    if winner is not None and run and run[-1] == winner and winner in considered:
        stopped = considered.index(winner) == len(run) - 1
    return {
        "aesop_imported": bool(getattr(receipt, "aesop_imported", False)),
        "aesop_in_considered": aesop_tactic in considered,
        "attempts": attempts,
        "error": getattr(receipt, "error", ""),
        "generator": getattr(receipt, "generator", ""),
        "git_commit": getattr(receipt, "git_commit", ""),
        "hammer_006_lra_ready": bool(getattr(receipt, "hammer_006_lra_ready", False)),
        "lean_tag": getattr(receipt, "lean_tag", ""),
        "loop": getattr(receipt, "loop", ""),
        "name": getattr(receipt, "name", ""),
        "ok": bool(getattr(receipt, "ok", False)),
        "on_30_sep_critical_path": bool(getattr(receipt, "on_30_sep_critical_path", False)),
        "path": getattr(receipt, "path", ""),
        "path_b_implemented": bool(getattr(receipt, "path_b_implemented", False)),
        "sorry_attempt": sorry,
        "sorry_failed": sorry is not None and not sorry["ok"] and sorry["sorryAx"],
        "sorry_first": sorry is not None and sorry["tactic"] == sorry_tactic,
        "sorry_template_prefix_bound": bool(getattr(receipt, "sorry_template_prefix_bound", False)),
        "source": getattr(receipt, "source", ""),
        "stopped_after_winner": stopped,
        "tactics_considered": considered,
        "tactics_run": run,
        "uses_snapshot_goal": bool(getattr(receipt, "uses_snapshot_goal", False)),
        "v1_runs_this": bool(getattr(receipt, "v1_runs_this", False)),
        "winning_tactic": winner,
        "all_attempts_lake_env_lean": all(item["argv_has_lake_env_lean"] for item in attempts)
        and (sorry is None or sorry["argv_has_lake_env_lean"]),
        "no_snapshot_goal_on_attempts": all(not item["used_snapshot_goal"] for item in attempts)
        and (sorry is None or not sorry["used_snapshot_goal"]),
        "arena_score": None,
        "score": None,
    }


def stamp_measured(
    receipt: Any,
    *,
    argv: Sequence[str],
    cwd: Any,
    toolchain: Any,
    timeout: float,
    stamp_fn: Callable[..., Any],
    run_fn: Callable[[Sequence[str], Mapping[str, str]], Any],
    state_root: Any,
    tmp_name: str,
    process_env_key: str,
    threads: Any,
    max_heartbeats: int,
    ikv_floor: float,
    under_fn: Optional[Callable[..., Any]] = None,
) -> Any:
    """Compute supervisor dir and stamp a measured lake run. run_fn is injected."""

    from jevops.outer import under_or_tmp

    under = under_fn or under_or_tmp
    supervisor_dir = under(state_root, "process-supervisor", tmp_name=tmp_name)
    return stamp_tag_compile(
        receipt,
        cwd=cwd,
        argv=argv,
        toolchain=toolchain,
        timeout=timeout,
        stamp_fn=stamp_fn,
        run_fn=run_fn,
        supervisor_dir=supervisor_dir,
        process_env_key=process_env_key,
        threads=threads,
        max_heartbeats=max_heartbeats,
        ikv_floor=ikv_floor,
    )


def stamp_tag_compile(
    receipt: Any,
    *,
    cwd: Any,
    argv: Sequence[str],
    toolchain: Any,
    timeout: float,
    stamp_fn: Callable[..., Any],
    run_fn: Callable[[Sequence[str], Mapping[str, str]], Any],
    supervisor_dir: Any,
    process_env_key: str,
    threads: Any,
    max_heartbeats: int,
    ikv_floor: float,
) -> Any:
    """Stamp argv/cwd/env then overlay a timed lake run. run_fn is injected."""

    from jevops.outer import env_copy

    argv = list(argv)
    receipt.argv = list(argv)
    receipt.cwd = str(cwd)
    env = env_copy(
        lake_supervisor_fields(
            threads=threads,
            elan_home=toolchain.elan_home,
            supervisor_dir=supervisor_dir,
            process_env_key=process_env_key,
        )
    )
    return stamp_fn(
        receipt,
        argv=argv,
        cwd=cwd,
        run_fn=lambda: run_fn(argv, env),
        max_heartbeats=max_heartbeats,
        lean_path=toolchain.lean_path,
        timeout_seconds=getattr(receipt, "timeout_seconds", timeout),
        extra_ok=getattr(receipt, "measurement_maxHeartbeats", 0) == int(max_heartbeats),
        ikv_floor=ikv_floor,
    )


def load_admit_lean_proof_text(*, setup: Sequence[Any] = ()) -> Any:
    """Live ImportFrom of admit_lean_proof_text. Jev does not write Lean. Lake is the oracle."""

    for item in setup or ():
        item()
    from ipfs_accelerate_py.agent_supervisor.proof.kernel_verification import admit_lean_proof_text

    return admit_lean_proof_text


def load_lean_toolchain(*, setup: Sequence[Any] = ()) -> dict[str, Any]:
    """Live ImportFrom of tag-pinned lake/lean helpers. Never PATH lean. Never writes Lean."""

    for item in setup or ():
        item()
    from ipfs_datasets_py.logic.hammers.frontends.lean_toolchain import (
        KERNEL_COMMAND_TEMPLATE,
        LeanToolchainMissing,
        LeanToolchainResolver,
        audit_lean_frontend_path_json,
        run_lean_process,
    )

    return {
        "KERNEL_COMMAND_TEMPLATE": KERNEL_COMMAND_TEMPLATE,
        "LeanToolchainMissing": LeanToolchainMissing,
        "LeanToolchainResolver": LeanToolchainResolver,
        "audit_lean_frontend_path_json": audit_lean_frontend_path_json,
        "run_lean_process": run_lean_process,
    }


def resolve_tag_pin(
    pin: Any,
    *,
    resolver_cls: Any,
    elan_home: Any = None,
    require_installed: bool = True,
    miss_types: tuple[type[BaseException], ...] = (),
    error_cls: type[BaseException] = ValueError,
) -> Any:
    """Resolve a tag pin through an injected toolchain resolver. Never PATH lean."""

    from jevops.outer import reraise_as

    resolver = resolver_cls(elan_home)
    return reraise_as(
        lambda: resolver.resolve_tag(
            pin.lean_tag, git_commit=pin.git_commit, require_installed=require_installed
        ),
        miss_types,
        error_cls,
    )


def stamp_with_lake_process(
    receipt: Any,
    *,
    lake_path: str,
    lean_path: str,
    source_file: str,
    max_heartbeats: int,
    cwd: Any,
    toolchain: Any,
    timeout: float,
    stamp_fn: Callable[..., Any],
    run_lean_process: Callable[..., Any],
    state_root: Any,
    tmp_name: str,
    process_env_key: str,
    threads: Any,
    ikv_floor: float,
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
) -> Any:
    """Build measurement_argv and stamp via run_lean_process. Lake is the oracle. Never writes Lean."""

    argv = measurement_argv(
        lake_path,
        lean_path,
        source_file,
        max_heartbeats=max_heartbeats,
        refuse=refuse,
        error_cls=error_cls,
    )
    from jevops.outer import text_or

    return stamp_measured(
        receipt,
        argv=argv,
        cwd=cwd,
        toolchain=toolchain,
        timeout=timeout,
        stamp_fn=stamp_fn,
        run_fn=lambda argv, env: run_lean_process(
            argv,
            timeout=timeout,
            cwd=text_or(cwd),
            env=env,
        ),
        state_root=state_root,
        tmp_name=tmp_name,
        process_env_key=process_env_key,
        threads=threads,
        max_heartbeats=max_heartbeats,
        ikv_floor=ikv_floor,
    )


def failed_generation(
    health: Any,
    error: str,
    *,
    requested_provider: str,
    requested_model: str,
    generation_cls: Any = None,
    identity_cls: Any = None,
    skipped: bool = False,
) -> Any:
    """Closed generate failure. Never a fallback success. Never writes Lean."""

    cls = generation_cls or Generation
    return cls(
        text="",
        identity=closed_provider_identity(
            requested_provider=requested_provider,
            requested_model=requested_model,
            identity_cls=identity_cls,
        ),
        health=health,
        skipped=skipped,
        error=error,
    )


def retrieval_prompt_extra(
    *,
    lemmas: str,
    n_neighbors: int,
    lemma_cap: int,
) -> str:
    """Append JSONL neighbor/lemma context. Not a Mathlib CorpusManifest."""

    return (
        "\n\nRetrieved src lemmas (cap "
        f"{int(lemma_cap)}): {lemmas or '(none)'}\n"
        f"Other warm-up JSONL neighbors: {int(n_neighbors)} "
        "(public; not a Mathlib CorpusManifest).\n"
        "Return only the tactic block after := by."
    )


def drive_plant_loop(
    records: Sequence[Mapping[str, Any]],
    *,
    parent: Any,
    parent_factory: Callable[[], Any],
    prefix: str,
    pin_iter_fn: Callable[[Any], Sequence[Any]],
    plant_toolchain_fn: Callable[[Any, str], Any],
    plant_clone_fn: Callable[[str, Any], Any],
) -> dict[str, Any]:
    """Plant a loop workspace under parent. Not a live lake bake."""

    from jevops.outer import path_or

    return plant_loop_workspace(
        records,
        parent=path_or(parent, factory=parent_factory),
        prefix=prefix,
        pin_iter_fn=pin_iter_fn,
        plant_toolchain_fn=plant_toolchain_fn,
        plant_clone_fn=plant_clone_fn,
    )


def plant_loop_workspace(
    records: Sequence[Mapping[str, Any]],
    *,
    parent: Any,
    prefix: str,
    pin_iter_fn: Callable[[Any], Sequence[Any]],
    plant_toolchain_fn: Callable[[Any, str], Any],
    plant_clone_fn: Callable[[str, Any], Any],
) -> dict[str, Any]:
    """Plant tag-pinned fake toolchains and repo clones. Not a live lake bake."""

    from jevops.outer import mkdtemp_under, unique_keep

    root = mkdtemp_under(parent, prefix=prefix)
    elan_home = Path(root) / "elan"
    state_root = Path(root) / "state"
    tags = unique_keep(
        [
            pin.lean_tag
            for record in records
            for pin in pin_iter_fn(record.get("version_info"))
        ]
    )
    urls = unique_keep(
        [str(record.get("url") or "") for record in records if str(record.get("url") or "")]
    )
    for tag in tags:
        plant_toolchain_fn(elan_home, tag)
    for url in urls:
        plant_clone_fn(url, state_root)
    return {
        "elan_home": elan_home,
        "root": root,
        "state_root": state_root,
        "tags": tags,
        "urls": urls,
    }


def reraise_router_fail(
    exc: BaseException,
    *,
    identity: Any,
    generate_cls: Any,
    unreachable_cls: Any,
    refuse_fn: Callable[..., Any],
    fmt: str,
    **fmt_kwargs: Any,
) -> None:
    """Fail closed on a router exception. Fallback identities never succeed."""

    if getattr(identity, "fallback_used", False):
        try:
            refuse_fn(
                identity,
                error_cls=generate_cls,
                fmt="refusing cross-provider fallback {provider}/{model}",
            )
        except Exception as refuse_exc:
            if isinstance(refuse_exc, generate_cls):
                raise generate_cls(str(refuse_exc)) from exc
            raise
    raise unreachable_cls(fmt.format(**fmt_kwargs)) from exc


def pack_synthetic_compile(
    *,
    elan_home: Any,
    expand_receipts: Sequence[Any],
    first_receipts: Sequence[Any],
    putnam_receipt: Any,
    written: Sequence[Any],
    persisted: Sequence[Any],
    receipts_dir: Any = "",
    first_file: str,
    first_name: str,
    first_green: bool,
    missing_clone_closed: bool,
    timeout_30_rejected: bool,
    timeout_is_warmup: bool,
    summary_fn: Callable[[Any], Mapping[str, Any]],
    tag_sort_fn: Callable[[str], Any],
    max_heartbeats: int,
) -> dict[str, Any]:
    """Synthetic compile-worker payload. IndependentKernelVerifier is unused."""

    expand_tags = [item.lean_tag for item in expand_receipts]
    first_summaries = [dict(summary_fn(item)) for item in first_receipts]
    return {
        "elan_home": str(elan_home),
        "expand_n_receipts": len(list(expand_receipts)),
        "expand_ok": bool(expand_receipts) and all(item.ok for item in expand_receipts),
        "expand_receipts": [dict(summary_fn(item)) for item in expand_receipts],
        "expand_tags_newest_first": expand_tags == sorted(expand_tags, key=tag_sort_fn, reverse=True),
        "first_file": first_file,
        "first_green": bool(first_green),
        "first_n_receipts": len(list(first_receipts)),
        "first_name": first_name,
        "first_receipts": first_summaries,
        "first_strata_compiled": bool(first_green),
        "first_via_lake_env_lean": bool(first_receipts)
        and all(row["argv_has_lake_env_lean"] for row in first_summaries),
        "missing_clone_fails_closed_under_network_deny": bool(missing_clone_closed),
        "n_receipts_persisted": len(list(persisted)),
        "n_receipts_written": len(list(written)),
        "persisted_receipts": list(persisted),
        "receipts_dir": str(receipts_dir),
        "receipts_written": [Path(path).name for path in written],
        "putnam_header_maxHeartbeats": getattr(putnam_receipt, "header_maxHeartbeats", None),
        "putnam_measurement_maxHeartbeats": getattr(putnam_receipt, "measurement_maxHeartbeats", None),
        "putnam_ok": bool(getattr(putnam_receipt, "ok", False)),
        "putnam_overrides_zero_header": (
            getattr(putnam_receipt, "header_maxHeartbeats", None) == 0
            and getattr(putnam_receipt, "measurement_maxHeartbeats", None) == int(max_heartbeats)
            and bool(getattr(putnam_receipt, "ok", False))
        ),
        "putnam_receipt": dict(summary_fn(putnam_receipt)),
        "timeout_30s_rejected": bool(timeout_30_rejected),
        "timeout_is_warmup_600s": bool(timeout_is_warmup),
        "independent_kernel_verifier_used": False,
    }


def putnam_candidate_stub(*, theorem: Optional[str] = None) -> str:
    """Putnam candidate module stub. Never Tmp.lean."""

    body = theorem if theorem is not None else render_placeholder_theorem()
    return (
        "/-\n"
        "  LRA Putnam candidate module: Putnam.Candidate.\n"
        "\n"
        "  The compile worker overwrites this file with header + statement +\n"
        "  tactic block via splice.lake_candidate_source. This is a module in\n"
        "  the per-tag Mathlib+Aesop lake project, not Tmp.lean, and not\n"
        "  `lake env lean Tmp.lean` without a lakefile.\n"
        "-/\n"
        "\n"
        + body
    )


def hosted_identity(
    *,
    requested_provider: str,
    requested_model: str,
    fixture: bool,
    extra: Optional[Mapping[str, Any]] = None,
    api_host: str,
    hardware_class: str,
    error_cls: type[BaseException] = ValueError,
    host_fmt: str = "resolved host is not {host}",
) -> dict[str, Any]:
    """Track 1 hosted identity. Never docker0. Never a fallback success."""

    extra = dict(extra or {})
    if fixture:
        return {
            "requested_provider": requested_provider,
            "requested_model": requested_model,
            "resolved_provider": requested_provider,
            "resolved_model": requested_model,
            "fallback_used": False,
            "url_host": api_host,
            "hardware_class": hardware_class,
            "used_prototype_endpoint": False,
            "arena_score": None,
        }
    if extra.get("url_host") != api_host:
        raise error_cls(host_fmt.format(host=api_host))
    return {
        "requested_provider": requested_provider,
        "requested_model": requested_model,
        "resolved_provider": requested_provider,
        "resolved_model": extra.get("model") or requested_model,
        "fallback_used": False,
        "request_id": extra.get("id"),
        "url_host": extra.get("url_host"),
        "hardware_class": hardware_class,
        "used_prototype_endpoint": False,
        "finish_reason": extra.get("finish_reason"),
        "arena_score": None,
    }


def refuse_line_identity(
    identity: Any,
    *,
    allowed: Sequence[str],
    forbidden: Sequence[str],
    error_cls: type[BaseException],
) -> None:
    """Refuse fallback / non-docker0 resolved providers. Empty resolved stays local."""

    provider = str(getattr(identity, "resolved_provider", "") or "")
    model = str(getattr(identity, "resolved_model", "") or "")
    if getattr(identity, "fallback_used", False):
        raise error_cls(f"refusing fallback {provider}/{model}")
    if provider and provider not in set(allowed) and provider in set(forbidden):
        raise error_cls("refusing non-docker0 provider")


def overlay_try_probe(payload: Mapping[str, Any], extra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Path A toolchain overlay. Snapshot/HAMMER flags stay false."""

    out = dict(payload or {})
    if extra:
        out.update(dict(extra))
    gap = bool(out.get("capability_gap"))
    out["live_elan_usable"] = False if gap else bool(out.get("installed_tags"))
    out["snapshot_goal_usable_for_lake_projects"] = False
    if gap:
        out["live_elan_usable"] = False
    return out


def pack_synthetic_try(
    *,
    elan_home: Any,
    missing_closed: bool,
    written: Sequence[Any],
    persisted: Sequence[Any],
    putnam: Any,
    strata: Any,
    unsolved: Any,
    timeout_30_rejected: bool,
    summary_fn: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """Synthetic Path A try payload. IndependentKernelVerifier is unused."""

    return {
        "elan_home": str(elan_home),
        "missing_clone_fails_closed_under_network_deny": bool(missing_closed),
        "n_receipts_persisted": len(list(persisted)),
        "n_receipts_written": len(list(written)),
        "persisted_receipts": list(persisted),
        "putnam": dict(summary_fn(putnam)),
        "receipts_written": [Path(path).name for path in written],
        "strata": dict(summary_fn(strata)),
        "timeout_30s_rejected": bool(timeout_30_rejected),
        "unsolved": dict(summary_fn(unsolved)),
    }


def grok_file_prompt(
    body: str,
    *,
    dest_name: str,
    stub: str,
) -> str:
    """Instruct a file-writing generator. Chat is not the deliverable. Never docker0."""

    return (
        f"Your deliverable is the file {dest_name} in the working directory.\n"
        "Use the write_file tool once to OVERWRITE that file with Lean 4 tactics only.\n"
        "Do not read other files. Do not search the filesystem. Everything you need is in this prompt.\n"
        "Do not put the tactics in chat. Chat may be a one-line ack such as wrote tactics.lean.\n"
        "The file must contain ONLY the tactic block after := by.\n"
        "No English, no markdown fences, no theorem/lemma/import/open/sorry/admit.\n"
        "Keep induction and every case arm. Smallest lake-valid proof.\n"
        f"The file currently contains a stub `{str(stub).strip()}`. Replace it completely.\n\n"
        + str(body or "")
    )


def pack_file_result(
    cls: Any,
    *,
    tactics: str,
    identity: Any,
    line: Any,
    chat: str,
    dest: Any,
    workspace: Any,
    head_fn: Callable[..., str],
    extra: Optional[Mapping[str, Any]] = None,
) -> Any:
    """File-writing generate result. Chat is not the deliverable. Never docker0."""

    payload: dict[str, Any] = {
        "tactics": tactics,
        "identity": identity,
        "line": line,
        "chat_head": head_fn(chat or "", 240),
        "tactics_path": str(dest),
        "workspace": str(workspace),
        "used_file": True,
        "chat_ignored": True,
        "called_docker0": False,
        "arena_score": None,
    }
    if extra:
        payload.update(dict(extra))
    return cls(**payload)


def grok_file_argv(
    *,
    grok_bin: str,
    socket: str,
    workspace: Any,
    model: str,
    max_turns: int,
    tools: str,
    disallowed: str,
    dest_name: str,
    prompt_path: Any,
) -> list[str]:
    """Fail-closed grok CLI argv for a tactics file. Never docker0."""

    return [
        grok_bin,
        "--leader-socket",
        socket,
        "--cwd",
        str(workspace),
        "--model",
        model,
        "--output-format",
        "json",
        "--no-plan",
        "--no-subagents",
        "--disable-web-search",
        "--no-memory",
        "--verbatim",
        "--always-approve",
        "--max-turns",
        str(int(max_turns)),
        "--permission-mode",
        "acceptEdits",
        "--reasoning-effort",
        "low",
        "--tools",
        tools,
        "--disallowed-tools",
        disallowed,
        "--allow",
        f"Write({dest_name})",
        "--allow",
        f"Edit({dest_name})",
        "--deny",
        "Bash(*)",
        "--prompt-file",
        str(prompt_path),
    ]


def pack_try_plan(
    *,
    digest: str,
    jsonl_bytes: int,
    n_records: int,
    per_record: Sequence[Mapping[str, Any]],
    first_name: str,
    first_tactics: Sequence[str],
    putnam_name: str,
    putnam_tactics: Sequence[str],
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Path A plan overlay. Catalog strings stay in the consumer."""

    out: dict[str, Any] = {
        "arena_score": None,
        "score": None,
        "first_putnam_name": str(putnam_name),
        "first_putnam_tactics": list(putnam_tactics or ()),
        "first_strata_name": str(first_name),
        "first_strata_tactics": list(first_tactics or ()),
        "frozen_warmup_sha256": str(digest),
        "jsonl_bytes": int(jsonl_bytes),
        "n_records": int(n_records),
        "records": list(per_record or ()),
    }
    if extra:
        out.update(dict(extra))
    out["arena_score"] = None
    out["score"] = None
    return out


def drive_plan_try(
    path: Any,
    *,
    default_path: Any,
    load_fn: Callable[..., tuple[Any, str, Sequence[Mapping[str, Any]]]],
    tactics_fn: Callable[[Mapping[str, Any]], Sequence[str]],
    aesop_fn: Callable[[Mapping[str, Any]], bool],
    aesop_tactic: str,
    first_of_source_fn: Callable[..., Mapping[str, Any]],
    strata_source: str,
    putnam_source: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Path A plan from a warmup JSONL. Does not compile."""

    from jevops.outer import get_str, if_none

    jsonl = Path(if_none(path, default_path))
    raw, digest, records = load_fn(jsonl)
    per_record = path_a_plan_rows(
        records,
        tactics_fn=tactics_fn,
        aesop_fn=aesop_fn,
        aesop_tactic=aesop_tactic,
    )
    first = first_of_source_fn(records, strata_source)
    putnam = first_of_source_fn(records, putnam_source)
    return pack_try_plan(
        digest=digest,
        jsonl_bytes=len(raw),
        n_records=len(list(records)),
        per_record=per_record,
        first_name=get_str(first, "name"),
        first_tactics=tactics_fn(first),
        putnam_name=get_str(putnam, "name"),
        putnam_tactics=tactics_fn(putnam),
        extra=extra,
    )


def pack_materialized_putnam(
    dest: Any,
    files: Sequence[str],
    *,
    lakefile: str,
    toolchain: str,
    pins: Mapping[str, Any],
    mathlib_git: str,
    aesop_git: str,
    refuse: str,
) -> dict[str, Any]:
    """Per-tag Putnam lake project view. Never Tmp.lean."""

    dest_path = Path(dest)
    return {
        "dest": str(dest_path),
        "files": sorted(files),
        "has_lakefile": (dest_path / "lakefile.lean").is_file(),
        "has_tmp_lean": (dest_path / refuse).exists(),
        "toolchain": toolchain,
        "mathlib_in_lakefile": "mathlib" in lakefile and mathlib_git in lakefile,
        "aesop_in_lakefile": "aesop" in lakefile and aesop_git in lakefile,
        "candidate_module": pins.get("module"),
        "putnambench_url": pins.get("putnambench_url"),
        "tmp_lean": pins.get("tmp_lean"),
        "jsonl_version_pin": pins.get("jsonl_version_pin"),
    }


def pack_synthetic_bake(
    *,
    planted: Any,
    planted_n: int,
    hit: Mapping[str, Any],
    missing_raised: bool,
    missing_message: str,
    allow_missing: Mapping[str, Any],
    write_denied: bool,
    materialized: Mapping[str, Any],
    putnam_tags: Sequence[str],
    putnam_module: str,
) -> dict[str, Any]:
    """Synthetic olean-bake payload. IndependentKernelVerifier is unused."""

    rows = list(dict(materialized or {}).values())
    return {
        "planted_cache_dir": str(planted),
        "planted_n_oleans": int(planted_n),
        "deny_cache_hit_on_planted_strata_v4_26": hit.get("ok") is True
        and hit.get("status") == "cache-hit",
        "missing_putnam_under_network_deny_raises": bool(missing_raised),
        "missing_message_mentions_network_deny": "network=deny" in str(missing_message or ""),
        "allow_missing_does_not_raise": allow_missing.get("ok") is False
        and allow_missing.get("status") == "cache-missing",
        "write_candidate_rejects_tmp_lean": bool(write_denied),
        "materialized_putnam": dict(materialized or {}),
        "all_putnam_tags_materialized": set(materialized) == set(putnam_tags),
        "any_putnam_tmp_lean": any(row.get("has_tmp_lean") for row in rows),
        "all_putnam_have_mathlib_aesop_lakefile": bool(rows)
        and all(
            row.get("has_lakefile") and row.get("mathlib_in_lakefile") and row.get("aesop_in_lakefile")
            for row in rows
        ),
        "all_putnam_module_candidate": bool(rows)
        and all(row.get("candidate_module") == putnam_module for row in rows),
        "all_putnambench_url_null": bool(rows)
        and all(row.get("putnambench_url") is None for row in rows),
    }


def _first_receipt_dict(receipts: Sequence[Any]) -> dict[str, Any]:
    rows = list(receipts or ())
    if not rows:
        return {"ok": False, "error": "no_receipt"}
    item = rows[0]
    if hasattr(item, "to_dict"):
        return dict(item.to_dict())
    return dict(item)


def drive_keepbest_tactics(
    record: Mapping[str, Any],
    tactics: str,
    *,
    state_root: Any,
    timeout: float,
    restore: bytes,
    url: str,
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[[Mapping[str, Any]], str],
    pins_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
    compile_record_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
    parse_errors_fn: Callable[..., Any],
    sorry_fn: Callable[..., bool],
    token_fn: Callable[[str], int],
    statement_fn: Callable[[Mapping[str, Any]], str],
    candidate_source_fn: Callable[..., str],
    splice_fn: Callable[..., str],
    line_in_span_fn: Callable[..., bool],
    extra_fn: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    """Clone once, then compile keep-best tactics. Lake remains the admit."""

    clone = clone_fn(url, state_root)
    return drive_keepbest_compile(
        record,
        tactics,
        state_root=state_root,
        timeout=timeout,
        restore=restore,
        clone_fn=clone_fn,
        pins_fn=lambda rec: pins_fn(rec, clone),
        compile_record_fn=compile_record_fn,
        parse_errors_fn=parse_errors_fn,
        sorry_fn=sorry_fn,
        token_fn=token_fn,
        statement_fn=statement_fn,
        dest_fn=lambda rec: Path(clone) / relpath_fn(rec),
        candidate_source_fn=candidate_source_fn,
        splice_fn=splice_fn,
        line_in_span_fn=line_in_span_fn,
        extra_fn=extra_fn,
    )


def drive_keepbest_compile(
    record: Mapping[str, Any],
    tactics: str,
    *,
    state_root: Any,
    timeout: float,
    restore: bytes,
    clone_fn: Callable[..., Any],
    pins_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
    compile_record_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
    parse_errors_fn: Callable[..., Sequence[Mapping[str, Any]]],
    sorry_fn: Callable[..., bool],
    token_fn: Callable[[str], int],
    statement_fn: Callable[[Mapping[str, Any]], str],
    dest_fn: Callable[[Mapping[str, Any]], Any],
    candidate_source_fn: Callable[..., str],
    splice_fn: Callable[..., str],
    line_in_span_fn: Callable[..., bool],
    extra_fn: Callable[..., Mapping[str, Any]],
    putnam_source: str = "putnambench",
) -> dict[str, Any]:
    """Lake-compile a keep-best tactic block. ``compile_record_fn`` owns lake."""

    from jevops.outer import elapsed_ms, head_seq, tail_chars

    return compile_keepbest(
        record,
        tactics,
        putnam_source=putnam_source,
        token_fn=token_fn,
        closed_fn=compile_closed,
        pins_fn=pins_fn,
        compile_fn=compile_record_fn,
        parse_errors_fn=parse_errors_fn,
        sorry_fn=sorry_fn,
        pack_fn=pack_compile_view,
        elapsed_fn=elapsed_ms,
        now_fn=__import__("time").perf_counter,
        patch_fn=patch_putnam_src,
        statement_fn=statement_fn,
        dest_fn=dest_fn,
        restore=restore,
        write_bytes_fn=lambda dest, data: Path(dest).write_bytes(data),
        candidate_source_fn=candidate_source_fn,
        splice_fn=splice_fn,
        span_fn=splice_span,
        line_in_span_fn=line_in_span_fn,
        extra_fn=extra_fn,
    )


def compile_keepbest(
    record: Mapping[str, Any],
    tactics: str,
    *,
    putnam_source: str,
    token_fn: Callable[[str], int],
    closed_fn: Callable[..., Mapping[str, Any]],
    pins_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
    compile_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
    parse_errors_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    sorry_fn: Callable[[str, int, int], bool],
    pack_fn: Callable[..., Mapping[str, Any]],
    elapsed_fn: Callable[[float], float],
    now_fn: Callable[[], float],
    patch_fn: Callable[..., Mapping[str, Any]],
    statement_fn: Callable[[Mapping[str, Any]], str],
    dest_fn: Callable[[Mapping[str, Any]], Path],
    restore: bytes,
    write_bytes_fn: Callable[[Any, bytes], Any],
    candidate_source_fn: Callable[[Mapping[str, Any], str], str],
    splice_fn: Callable[..., Any],
    span_fn: Callable[[str, str, str], tuple[int, int]],
    line_in_span_fn: Callable[..., bool],
    extra_fn: Callable[..., Mapping[str, Any]],
    audit_declaration: str = "",
) -> dict[str, Any]:
    """Putnam vs repo keep-best compile. Lake is the oracle. Never PATH lean."""

    record = dict(record)
    audit_suffix = ""
    if audit_declaration:
        from .proof_trust import axiom_audit_command

        audit_suffix = axiom_audit_command(audit_declaration)
    requested_versions = list(record.get("version_info") or ())
    record["version_info"] = list(pins_fn(record) or ())
    if not record["version_info"]:
        return dict(closed_fn(token_count=token_fn(tactics)))

    def aggregate(views: list[dict[str, Any]]) -> dict[str, Any]:
        complete = len(views) == len(record["version_info"])
        accepted = complete and bool(views) and all(v.get("theorem_ok") for v in views)
        out = dict(next((v for v in views if not v.get("theorem_ok")), views[0] if views else
                        closed_fn(token_count=token_fn(tactics))))
        out.update(ok=accepted, theorem_ok=accepted, all_tags_ok=accepted,
                   checked_tag_count=len(views), expected_tag_count=len(record["version_info"]),
                   tag_results=views, requested_version_info=requested_versions,
                   selected_version_info=record["version_info"],
                   all_requested_tags_ok=accepted and requested_versions == record["version_info"])
        if not complete:
            out["error"] = out.get("error") or "incomplete_tag_receipts"
        return out

    if str(record.get("source") or "") == putnam_source:
        patched = patch_fn(record, tactics, statement=statement_fn(record))
        if audit_suffix:
            patched = {**patched, "src": str(patched["src"]) + audit_suffix}
        started = now_fn()
        views = []
        for raw in compile_fn(patched):
            receipt = _first_receipt_dict([raw])
            stdout = str(receipt.get("stdout") or "")
            errors = list(parse_errors_fn(stdout) or ())
            view = dict(pack_fn(
                receipt,
                token_count=token_fn(tactics),
                errors=errors,
                sorry=bool(sorry_fn(stdout, 1, 10**9)),
                extra={"compile_wall_ms_outer": elapsed_fn(started),
                       "lean_tag": receipt.get("lean_tag"), "argv": receipt.get("argv")},
            ))
            if audit_declaration:
                from .proof_trust import audit_axioms

                view["kernel_audit"] = audit_axioms(stdout, [audit_declaration])
                view["ok"] = view["theorem_ok"] = bool(view.get("theorem_ok") and view["kernel_audit"]["accepted"])
            views.append(view)
        return aggregate(views)
    dest = dest_fn(record)
    write_bytes_fn(dest, restore)
    replacement = candidate_source_fn(record, tactics)
    original = restore.decode("utf-8") if isinstance(restore, (bytes, bytearray)) else str(restore)
    start_line, end_line = span_fn(original, str(record["src"]), replacement)
    try:
        splice_fn(dest, str(record["src"]), replacement)
        if audit_suffix:
            write_bytes_fn(dest, Path(dest).read_bytes() + audit_suffix.encode("utf-8"))
        started = now_fn()
        receipts = compile_fn(record)
    finally:
        # Failed or interrupted compilation must not contaminate later runs.
        write_bytes_fn(dest, restore)
    views = []
    for raw in receipts:
        receipt = _first_receipt_dict([raw])
        stdout = str(receipt.get("stdout") or "")
        errors = list(parse_errors_fn(stdout) or ())
        errors_in = [item for item in errors if line_in_span_fn(item.get("pos"), start_line, end_line)]
        errors_out = [item for item in errors if not line_in_span_fn(item.get("pos"), start_line, end_line)]
        view = dict(pack_fn(
            receipt,
            token_count=token_fn(tactics),
            errors=errors_in or errors_out,
            sorry=bool(sorry_fn(stdout, start_line, end_line)),
            extra=extra_fn(
                receipt,
                record,
                start_line,
                end_line,
                stdout,
                errors_in,
                errors_out,
                elapsed_fn(started),
            ),
        ))
        if audit_declaration:
            from .proof_trust import audit_axioms

            view["kernel_audit"] = audit_axioms(stdout, [audit_declaration])
            view["ok"] = view["theorem_ok"] = bool(view.get("theorem_ok") and view["kernel_audit"]["accepted"])
        views.append(view)
    return aggregate(views)


def collect_warmup_problem(
    record: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    split: Any,
    reconstruct_ok: bool,
    error_cls: type[BaseException],
    retrieve_fn: Callable[..., Any],
    phases: Sequence[str],
    probe: Any,
    ref_tactics: str,
    stripped: str,
    token_fn: Callable[[str], int],
    evaluate_fn: Callable[..., Any],
    pin_fn: Callable[..., Any],
    composite_fn: Callable[..., float],
    prompt_fn: Callable[..., str],
    generate_fn: Callable[..., Any],
    skip_reason_fn: Callable[..., tuple[bool, str]],
    append_fn: Callable[..., Any],
    extract_fn: Callable[[str], str],
    keep_fn: Callable[..., Any],
    failure_fn: Callable[..., Mapping[str, Any]],
    pack_fn: Callable[..., Any],
    max_candidates: int,
    hardware_class: str,
    hammers: str,
    typesafe: str,
    generator: str,
    loop_version: str,
    generator_default: str,
) -> Any:
    """Warm-up problem candidate assembly. Lake still admits. Never writes Lean."""

    if not reconstruct_ok:
        raise error_cls(f"{getattr(split, 'name', '')}: prefix bind reconstruction drifted")
    retrieval = retrieve_fn(record, records)
    reference_tokens = token_fn(ref_tactics)
    candidates: list[Any] = []
    reference = evaluate_fn(
        "reference",
        ref_tactics,
        generator="deterministic",
        reference_tokens=reference_tokens,
        reference_elab_ms=0.0,
    )
    pin_fn(reference, composite_fn=composite_fn)
    candidates.append(reference)
    reference_elab = getattr(reference, "elab_ms", 0.0)
    if stripped != ref_tactics and len(candidates) < int(max_candidates):
        candidates.append(
            evaluate_fn(
                "reference_stripped",
                stripped,
                generator="deterministic",
                reference_tokens=reference_tokens,
                reference_elab_ms=reference_elab,
            )
        )
    prompt = prompt_fn(record, retrieval)
    generation = generate_fn(prompt)
    called = bool(getattr(probe, "ok", False))
    skipped, skip_reason = skip_reason_fn(generation, probe_ok=called)

    def _eval_generated(tactics: str, gen: Any) -> Any:
        identity = getattr(gen, "identity", None)
        return evaluate_fn(
            "generated",
            tactics,
            generator=str(getattr(identity, "resolved_provider", "") or generator_default),
            reference_tokens=reference_tokens,
            reference_elab_ms=reference_elab,
            called_leanstral=True,
            generate_error=str(getattr(gen, "error", "") or ""),
        )

    append_fn(
        candidates,
        called=called,
        skipped=skipped,
        generation=generation,
        cap=int(max_candidates),
        extract_fn=extract_fn,
        evaluate_fn=_eval_generated,
        generator_default=generator_default,
        hardware_class=hardware_class,
    )
    kept = keep_fn(candidates)
    failures = [failure_fn(item) for item in candidates if not getattr(item, "valid", False)]
    return pack_fn(
        split,
        phases=phases,
        probe=probe,
        called=called,
        skipped=skipped,
        skip_reason=skip_reason,
        retrieval=retrieval,
        candidates=candidates,
        kept=kept,
        failures=failures,
        hardware_class=hardware_class,
        hammers=hammers,
        typesafe=typesafe,
        generator=generator,
        loop_version=loop_version,
    )


def drive_evaluate_candidate(
    record: Mapping[str, Any],
    *,
    kind: str,
    tactics: str,
    generator: str,
    source_fn: Callable[[Mapping[str, Any], str], str],
    token_fn: Callable[[str], int],
    admit_fn: Callable[[str], Any],
    make_fn: Callable[..., Any],
    compile_fn: Callable[[str], Any],
    attach_fn: Callable[..., Any],
    score_fn: Callable[..., Any],
    reconstruct_fn: Callable[[], bool],
    hardware_class: str,
    called_leanstral: bool = False,
    skipped_generate: bool = False,
    generate_error: str = "",
) -> Any:
    """Score one candidate after an injected compile. Not an admit by itself."""

    return evaluate_with_compile(
        kind=kind,
        tactics=tactics,
        source_text=source_fn(record, tactics),
        admit_fn=admit_fn,
        make_fn=make_fn,
        compile_fn=compile_fn,
        attach_fn=attach_fn,
        score_fn=score_fn,
        reconstruct_fn=reconstruct_fn,
        generator=generator,
        token_count=token_fn(tactics),
        hardware_class=hardware_class,
        called_leanstral=called_leanstral,
        skipped_generate=skipped_generate,
        generate_error=generate_error,
    )


def evaluate_with_compile(
    *,
    kind: str,
    tactics: str,
    source_text: str,
    admit_fn: Callable[[str], Any],
    make_fn: Callable[..., Any],
    compile_fn: Callable[[str], Sequence[Any]],
    attach_fn: Callable[[Any, Sequence[Any]], Any],
    score_fn: Callable[..., Any],
    reconstruct_fn: Callable[[], bool],
    generator: str,
    token_count: int,
    hardware_class: str,
    called_leanstral: bool = False,
    skipped_generate: bool = False,
    generate_error: str = "",
) -> Any:
    """Admit lexically, lake-compile when allowed, then score. Lake is the oracle."""

    view = admit_fn(tactics)
    accepted = bool(getattr(view, "accepted", False) if not isinstance(view, Mapping) else view.get("accepted"))
    code = str(
        getattr(view, "failure_code", "") if not isinstance(view, Mapping) else view.get("failure_code") or ""
    )
    reason = str(getattr(view, "reason", "") if not isinstance(view, Mapping) else view.get("reason") or "")
    candidate = make_fn(
        kind=kind,
        tactics=tactics,
        source_text=source_text,
        admission_accepted=accepted,
        admission_code=code,
        admission_reason=reason,
        generator=generator,
        token_count=token_count,
        hardware_class=hardware_class,
        called_leanstral=called_leanstral,
        skipped_generate=skipped_generate,
        error=generate_error,
    )
    if str(kind).startswith("reference") or accepted:
        attach_fn(candidate, list(compile_fn(tactics) or ()))
    reconstructed_ok = bool(reconstruct_fn()) if str(kind).startswith("reference") else False
    return score_fn(candidate, reconstructed_ok=reconstructed_ok)


def drive_docker0_generate(
    prompt: str,
    *,
    max_new_tokens: Optional[int],
    timeout: Optional[float],
    source: str,
    require_health: bool,
    generate: Optional[Callable[..., str]],
    get_trace: Optional[Callable[[], Mapping[str, Any]]],
    base_url: Optional[str],
    temperature: Optional[float],
    stop: Optional[Sequence[str]],
    lock: Any,
    lookup_fn: Callable[[str], Any],
    default_new: int,
    default_timeout: float,
    pin_fn: Callable[..., str],
    probe_fn: Callable[[], Any],
    health_cls: Callable[..., Any],
    health_url: str,
    alias_url: str,
    autostart_key: str,
    requested_provider: str,
    requested_model: str,
    identity_cls: Callable[..., Any],
    unreachable_fmt: str,
    reraise_fmt: str,
    openai_base: str,
    base_env_key: str,
    fail_closed: Mapping[str, Any],
    load_router_fn: Callable[[], tuple[Callable[..., str], Callable[[], Mapping[str, Any]]]],
    identity_from_trace_fn: Callable[..., Any],
    generation_cls: Callable[..., Any],
    generate_cls: type[BaseException],
    unreachable_cls: type[BaseException],
) -> Any:
    """Probe docker0, then generate under the lock. Does not admit Lean."""

    from jevops.outer import coalesce_pair, either, env_str, exc_text, first_int, first_truthy, nonempty_strs

    max_new_tokens, timeout = coalesce_limits(
        source=source,
        max_new=max_new_tokens,
        timeout=timeout,
        lookup_fn=lookup_fn,
        default_new=default_new,
        default_timeout=default_timeout,
    )
    pinned_base = pin_fn(base_url=base_url)
    health = either(
        base_url is None,
        probe_fn,
        lambda: forced_unhealthy(
            health_cls,
            url=health_url,
            alias_url=alias_url,
            error=f"forced base_url={base_url}",
            autostart=env_str(autostart_key),
        ),
    )
    identity = closed_provider_identity(
        requested_provider=requested_provider,
        requested_model=requested_model,
        identity_cls=identity_cls,
    )
    refuse_unhealthy(
        health,
        require_health=require_health,
        error_cls=unreachable_cls,
        fmt=unreachable_fmt,
        url=health_url,
        error=first_truthy(health.error, default="no /health"),
        provider=identity.requested_provider,
        model=identity.requested_model,
    )
    router_generate, router_trace = coalesce_pair(generate, get_trace, load_router_fn)
    call_kwargs = overlay_generate_kwargs(fail_closed, temperature=temperature, stop=stop, stop_fn=nonempty_strs)
    return run_locked_generate(
        lock=lock,
        pin_fn=lambda: pin_fn(base_url=pinned_base),
        call_fn=lambda: router_generate(
            prompt,
            max_new_tokens=first_int(max_new_tokens),
            timeout=float(timeout),
            **call_kwargs,
        ),
        catch_trace_fn=lambda: catch_trace(router_trace),
        identity_fn=identity_from_trace_fn,
        refuse_fn=refuse_if_fallback,
        reraise_fn=reraise_router_fail,
        require_fn=require_text,
        generation_cls=generation_cls,
        health=health,
        generate_cls=generate_cls,
        unreachable_cls=unreachable_cls,
        error_fn=exc_text,
        reraise_kwargs={
            "fmt": reraise_fmt,
            "base": env_str(base_env_key, openai_base),
        },
    )


def run_locked_generate(
    *,
    lock: Any,
    pin_fn: Callable[[], Any],
    call_fn: Callable[[], Any],
    catch_trace_fn: Callable[[], Any],
    identity_fn: Callable[..., Any],
    refuse_fn: Callable[..., Any],
    reraise_fn: Callable[..., Any],
    require_fn: Callable[..., str],
    generation_cls: Any,
    health: Any,
    generate_cls: type[BaseException],
    unreachable_cls: type[BaseException],
    reraise_kwargs: Optional[Mapping[str, Any]] = None,
    error_fn: Optional[Callable[[BaseException], str]] = None,
    refuse_fmt: str = "resolved provider/model is a forbidden fallback: {provider}/{model}",
) -> Any:
    """Pin, call the injected generator under lock, then refuse fallbacks.

    ``call_fn`` is the live router call. The lock object stays in the consumer.
    """

    text = ""
    with lock:
        pin_fn()
        try:
            text = call_fn()
        except unreachable_cls:
            raise
        except generate_cls:
            raise
        except Exception as exc:
            identity = identity_fn(catch_trace_fn(), generated=False)
            extra = dict(reraise_kwargs or {})
            extra.setdefault("error", error_fn(exc) if error_fn is not None else str(exc))
            extra["requested_provider"] = getattr(identity, "requested_provider", extra.get("requested_provider", ""))
            extra["requested_model"] = getattr(identity, "requested_model", extra.get("requested_model", ""))
            extra["resolved_provider"] = getattr(identity, "resolved_provider", extra.get("resolved_provider", ""))
            extra["resolved_model"] = getattr(identity, "resolved_model", extra.get("resolved_model", ""))
            reraise_fn(
                exc,
                identity=identity,
                generate_cls=generate_cls,
                unreachable_cls=unreachable_cls,
                refuse_fn=refuse_fn,
                **extra,
            )
    identity = refuse_fn(
        identity_fn(catch_trace_fn(), generated=True),
        error_cls=generate_cls,
        fmt=refuse_fmt,
    )
    text = require_fn(text, error_cls=generate_cls)
    return generation_cls(text=text, identity=identity, health=health)


def run_path_a_try(
    receipt: Any,
    considered: Sequence[str],
    *,
    aesop_err: Any,
    resolve_fn: Callable[[], Any],
    prepare_fn: Callable[[], tuple[Any, str, Any]],
    env_fn: Callable[[Any], Mapping[str, str]],
    run_tactic_fn: Callable[..., Any],
    fill_fn: Callable[..., Any],
    close_fn: Callable[..., Any],
    error_types: tuple[type[BaseException], ...],
    extra_fn: Callable[[BaseException], str],
    timeout: float,
) -> Any:
    """Sorry-then-closers Path A try. ``run_tactic_fn`` still owns lake/lean."""

    if aesop_err:
        receipt.error = aesop_err
        receipt.ok = False
        return receipt
    try:
        toolchain = resolve_fn()
        cwd, source_file, dest = prepare_fn()
        env = env_fn(toolchain)
        return fill_fn(
            receipt,
            considered,
            lambda tactic: run_tactic_fn(
                tactic=tactic,
                dest=dest,
                source_file=source_file,
                cwd=cwd,
                toolchain=toolchain,
                timeout=timeout,
                env=env,
            ),
        )
    except error_types as exc:
        return close_fn(receipt, exc, extra=extra_fn(exc))


def run_workspace_generate(
    *,
    workspace: Any,
    dest_name: str,
    stub: str,
    reset_stub: bool,
    generate_fn: Optional[Callable[..., str]] = None,
    generate_kwargs: Optional[Mapping[str, Any]] = None,
    identity_from_generate: Optional[Callable[[], Any]] = None,
    run_fn: Optional[Callable[[], tuple[str, Any]]] = None,
    read_fn: Callable[..., str],
    write_text_fn: Callable[..., Any],
) -> tuple[str, Any, str, Path]:
    """Write a tactics file via injected generate or CLI run. Chat is not the deliverable."""

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    dest = workspace / str(dest_name)
    if reset_stub or not dest.exists():
        write_text_fn(dest, stub)
    chat = ""
    identity: Any = None
    if generate_fn is not None:
        chat = str(generate_fn(**dict(generate_kwargs or {})))
        write_text_fn(dest, chat)
        identity = identity_from_generate() if identity_from_generate is not None else None
    else:
        if run_fn is None:
            raise ValueError("run_workspace_generate needs generate_fn or run_fn")
        chat, identity = run_fn()
        chat = str(chat or "")
    tactics = read_fn(workspace, dest_name=dest_name)
    return str(tactics), identity, chat, dest


def run_tag_compile(
    receipt: Any,
    *,
    resolve_fn: Callable[[], Any],
    prepare_fn: Callable[[], tuple[Any, Any, Any]],
    write_fn: Callable[[Any], Any],
    stamp_fn: Callable[..., Any],
    close_fn: Callable[..., Any],
    error_types: tuple[type[BaseException], ...],
    bake_fn: Optional[Callable[[], Any]] = None,
) -> Any:
    """Resolve pin, prepare lake paths, stamp. stamp_fn still owns lake/lean."""

    try:
        toolchain = resolve_fn()
        cwd, source_file, dest = prepare_fn()
        write_fn(dest)
        if bake_fn is not None:
            bake_fn()
        return stamp_fn(receipt, toolchain=toolchain, cwd=cwd, source_file=source_file)
    except error_types as exc:
        return close_fn(receipt, exc)


def drive_file_generate(
    prompt: str,
    ledger: Any,
    *,
    workspace: Any,
    dest_name: str,
    max_new_tokens: int,
    timeout: float,
    generate: Optional[Callable[..., str]],
    fixture: bool,
    reset_stub: bool,
    stub: str,
    requested_provider: str,
    requested_model: str,
    fail_closed_kwargs: Mapping[str, Any],
    result_cls: Callable[..., Any],
    identity_cls: Callable[..., Any],
    estimate_fn: Callable[[str], int],
    build_cmd_fn: Callable[..., list[str]],
    read_tactics_fn: Callable[..., str],
    identity_from_trace_fn: Callable[..., Any],
    fixture_trace_fn: Callable[[], Mapping[str, Any]],
    stdout_payload_fn: Callable[[str], Mapping[str, Any]],
    error_cls: type[BaseException],
) -> Any:
    """Authorize, write tactics via CLI or injected generate, then record spend.

    Lake still reads the file. Chat is not the deliverable. This does not admit Lean.
    """

    from jevops.outer import (
        attr_or,
        call_caught,
        coalesce_chat_text,
        detail_with_file,
        either,
        env_copy,
        fail_spend,
        first_int,
        first_truthy,
        head_chars,
        read_text,
        record_required,
        reraise_as,
        require_authorized,
        require_recorded,
        run_process,
        text_or,
        write_cli_run_artifacts,
        write_json,
        write_text,
    )

    estimated_in = estimate_fn(prompt)
    estimated_out = first_int(max_new_tokens)
    require_authorized(
        ledger,
        "grok",
        estimated_in,
        estimated_out,
        fixture=fixture,
        model=requested_model,
        error_cls=error_cls,
        fmt="grok call refused: {reason}",
    )

    def _run_cli() -> tuple[str, Any]:
        prompt_path = Path(workspace) / "PROMPT.txt"
        write_text(prompt_path, text_or(prompt))
        cmd = build_cmd_fn(workspace, prompt_path, dest_name=dest_name)
        ran = reraise_as(
            lambda: run_process(cmd, cwd=workspace, env=env_copy(), timeout=float(timeout)),
            (FileNotFoundError,),
            error_cls,
            missing="grok CLI not found on PATH",
        )
        chat_out, _stderr, _code = write_cli_run_artifacts(
            workspace,
            prompt=text_or(prompt),
            cmd=cmd,
            ran=ran,
            write_text_fn=write_text,
            write_json_fn=write_json,
        )
        chat_out = coalesce_chat_text(chat_out, ran, stdout_payload_fn)
        return chat_out, grok_cli_identity(
            identity_cls,
            requested_provider=requested_provider,
            requested_model=requested_model,
        )

    chat = ""
    identity: Any = None
    generate_fn, identity_from_generate, run_fn = either(
        generate is not None,
        lambda: (
            (lambda **_kw: generate(prompt, **fail_closed_kwargs)),
            (lambda: identity_from_trace_fn(fixture_trace_fn(), generated=True)),
            None,
        ),
        lambda: (None, None, _run_cli),
    )
    ok, packed, exc = call_caught(
        lambda: run_workspace_generate(
            workspace=workspace,
            dest_name=dest_name,
            stub=stub,
            reset_stub=reset_stub,
            generate_fn=generate_fn,
            identity_from_generate=identity_from_generate,
            run_fn=run_fn,
            read_fn=read_tactics_fn,
            write_text_fn=write_text,
        ),
        error_cls,
    )
    if not ok:
        fail_spend(
            ledger,
            "grok",
            estimated_in,
            either(chat, lambda: estimate_fn(chat), lambda: 1),
            fixture=fixture,
            model=first_truthy(attr_or(identity, "resolved_model"), requested_model),
            error_cls=error_cls,
            msg=detail_with_file(exc, Path(workspace) / "grok.stderr", read_fn=read_text),
            cause=exc,
        )
    tactics, identity, chat, dest = packed
    line = record_required(
        ledger,
        "grok",
        estimated_in,
        estimate_fn(tactics),
        fixture=fixture,
        model=first_truthy(identity.resolved_model, requested_model),
        require_fn=require_recorded,
        error_cls=error_cls,
        fmt="grok spend refused after call: {reason}",
    )
    return pack_file_result(
        result_cls,
        tactics=tactics,
        identity=identity,
        line=line,
        chat=chat,
        dest=dest,
        workspace=workspace,
        head_fn=head_chars,
    )


def drive_tag_compile(
    record: Mapping[str, Any],
    pin: Any,
    *,
    timeout: float,
    state_root: Optional[Any],
    elan_home: Optional[Any],
    network: str,
    require_oleans: bool,
    hardware_class: str,
    skip_checkout: bool,
    require_timeout_fn: Callable[[float], float],
    header_cap_fn: Callable[[str], Any],
    relpath_fn: Callable[[Mapping[str, Any]], str],
    schema: str,
    max_heartbeats: int,
    threads: int,
    kernel_template: str,
    stamp_process_fn: Callable[..., Any],
    stamp_measured_fn: Callable[..., Any],
    run_lean_process: Callable[..., Any],
    process_env_key: str,
    ikv_floor: float,
    refuse: str,
    error_cls: type[BaseException],
    tmp_name: str,
    resolve_fn: Callable[..., Any],
    prepare_paths_fn: Callable[..., Any],
    write_candidate_fn: Callable[..., Any],
    optional_fn: Callable[..., Any],
    bake_fn: Callable[..., Any],
    close_failed_fn: Callable[..., Any],
    digest_fn: Callable[[str], str],
    axiom_digest_fn: Callable[..., str],
    error_types: tuple[type[BaseException], ...],
    putnam_source: str,
    putnam_relpath: str,
    putnam_dir_fn: Callable[..., Any],
    materialize_fn: Callable[..., Any],
    require_clone_fn: Callable[..., Any],
    checkout_fn: Callable[..., Any],
    write_record_fn: Callable[..., Any],
) -> Any:
    """Tag-pinned lake compile. ``stamp_process_fn`` still owns lake/lean. Not an admit by itself."""

    from jevops.outer import get_str

    timeout = require_timeout_fn(timeout)
    header_cap = header_cap_fn(get_str(record, "header"))
    relpath = relpath_fn(record)
    receipt = init_compile_receipt(
        record,
        pin,
        timeout=timeout,
        relpath=relpath,
        schema=schema,
        max_heartbeats=max_heartbeats,
        header_cap=header_cap,
        lean_num_threads=threads,
        kernel_command_template=kernel_template,
        hardware_class=hardware_class,
    )

    def _stamp(receipt: Any, *, toolchain: Any, cwd: Any, source_file: str) -> Any:
        return stamp_process_fn(
            receipt,
            lake_path=toolchain.lake_path,
            lean_path=toolchain.lean_path,
            source_file=source_file,
            max_heartbeats=max_heartbeats,
            cwd=cwd,
            toolchain=toolchain,
            timeout=timeout,
            stamp_fn=stamp_measured_fn,
            run_lean_process=run_lean_process,
            state_root=state_root,
            tmp_name=tmp_name,
            process_env_key=process_env_key,
            threads=threads,
            ikv_floor=ikv_floor,
            refuse=refuse,
            error_cls=error_cls,
        )

    return run_tag_compile(
        receipt,
        resolve_fn=lambda: resolve_fn(pin, elan_home=elan_home, require_installed=True),
        prepare_fn=lambda: prepare_paths_fn(
            record,
            pin,
            putnam_source=putnam_source,
            putnam_relpath=putnam_relpath,
            source_relpath_fn=relpath_fn,
            putnam_dir_fn=putnam_dir_fn,
            materialize_fn=materialize_fn,
            require_clone_fn=require_clone_fn,
            checkout_fn=checkout_fn,
            skip_checkout=skip_checkout,
            network=network,
            state_root=state_root,
        ),
        write_fn=lambda dest: write_candidate_fn(
            record,
            dest,
            putnam_source=putnam_source,
            write_fn=write_record_fn,
        ),
        bake_fn=optional_fn(require_oleans, lambda: bake_fn()),
        stamp_fn=_stamp,
        close_fn=lambda rec, exc: close_failed_fn(
            rec, exc, digest_fn=digest_fn, axiom_digest_fn=axiom_digest_fn
        ),
        error_types=error_types,
    )


def drive_path_a_try(
    record: Mapping[str, Any],
    pin: Any,
    *,
    timeout: float,
    state_root: Optional[Any],
    elan_home: Optional[Any],
    network: str,
    skip_checkout: bool,
    require_timeout_fn: Callable[[float], float],
    tactics_fn: Callable[[Mapping[str, Any]], Sequence[str]],
    split_fn: Callable[[Mapping[str, Any]], Any],
    sorry_template_fn: Callable[[str], str],
    lake_sorry_fn: Callable[[Mapping[str, Any]], str],
    aesop_fn: Callable[[Mapping[str, Any]], bool],
    relpath_fn: Callable[[Mapping[str, Any]], str],
    digest_fn: Callable[[str], str],
    sorry_suffix: str,
    schema: str,
    loop: str,
    path_name: str,
    pr: str,
    lrah: str,
    generator: str,
    kernel_template: str,
    argv_template: str,
    threads: int,
    process_env_key: str,
    tmp_name: str,
    gap_types: tuple[type[BaseException], ...],
    gap_note: str,
    resolve_fn: Callable[..., Any],
    prepare_fn: Callable[..., Any],
    run_tactic_fn: Callable[..., Any],
    axiom_digest_fn: Callable[..., str],
    error_types: tuple[type[BaseException], ...],
) -> Any:
    """Path A tactic try. ``run_tactic_fn`` still owns lake/lean. Not an admit by itself."""

    from jevops.outer import env_copy, under_or_tmp

    timeout = require_timeout_fn(timeout)
    considered = list(tactics_fn(record))
    split = split_fn(record)
    receipt = begin_path_a_receipt(
        record,
        pin,
        relpath=relpath_fn(record),
        template=sorry_template_fn(split.statement),
        statement=split.statement,
        suffix=sorry_suffix,
        lake_sorry=lake_sorry_fn(record),
        aesop=aesop_fn(record),
        considered=considered,
        timeout=timeout,
        digest_fn=digest_fn,
        schema=schema,
        loop=loop,
        path=path_name,
        pr=pr,
        lrah=lrah,
        generator=generator,
        kernel_command_template=kernel_template,
        measurement_argv_template=argv_template,
    )

    def _env(toolchain: Any) -> Mapping[str, str]:
        return supervisor_env(
            state_root,
            toolchain,
            tmp_name=tmp_name,
            threads=threads,
            process_env_key=process_env_key,
            env_copy_fn=env_copy,
            under_fn=under_or_tmp,
            fields_fn=lake_supervisor_fields,
        )

    return run_path_a_try(
        receipt,
        considered,
        aesop_err=aesop_list_ok(considered, receipt.aesop_imported),
        resolve_fn=lambda: resolve_fn(pin, elan_home=elan_home, require_installed=True),
        prepare_fn=lambda: prepare_fn(
            record,
            pin,
            state_root=state_root,
            network=network,
            skip_checkout=skip_checkout,
        ),
        env_fn=_env,
        run_tactic_fn=lambda *, tactic, dest, source_file, cwd, toolchain, timeout, env: run_tactic_fn(
            record,
            tactic=tactic,
            dest=dest,
            source_file=source_file,
            cwd=cwd,
            lake_path=toolchain.lake_path,
            lean_path=toolchain.lean_path,
            timeout=timeout,
            env=env,
        ),
        fill_fn=path_a_fill,
        close_fn=lambda rec, exc, extra: close_failed_receipt(
            rec, exc, digest_fn=digest_fn, axiom_digest_fn=axiom_digest_fn, extra=extra
        ),
        error_types=error_types,
        extra_fn=lambda exc: toolchain_gap_note(exc, gap_types, gap_note),
        timeout=timeout,
    )


def drive_warmup_problem(
    record: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    health: Any,
    generate: Optional[Callable[..., str]],
    get_trace: Optional[Callable[[], Mapping[str, Any]]],
    max_new_tokens: Optional[int],
    generate_timeout: Optional[float],
    compile_timeout: float,
    state_root: Optional[Any],
    elan_home: Optional[Any],
    network: str,
    skip_checkout: bool,
    pin_env_fn: Callable[[], Any],
    split_fn: Callable[[Mapping[str, Any]], Any],
    probe_factory: Callable[[], Any],
    tactic_from_body_fn: Callable[[str], str],
    strip_fn: Callable[[str], str],
    evaluate_fn: Callable[..., Any],
    retrieve_fn: Callable[..., Any],
    phases: Sequence[str],
    composite_fn: Callable[..., Any],
    prompt_fn: Callable[..., str],
    maybe_generate_fn: Callable[..., Any],
    extract_fn: Callable[[str], str],
    keep_fn: Callable[..., Any],
    failure_fn: Callable[..., Any],
    token_fn: Callable[[str], int],
    error_cls: type[BaseException],
    max_candidates: int,
    hardware_class: str,
    hammers: str,
    typesafe: str,
    generator: str,
    loop_version: str,
) -> Any:
    """One warmup problem. ``evaluate_fn`` still owns lake."""

    from jevops.outer import first_truthy, get_str, if_none

    pin_env_fn()
    split = split_fn(record)
    probe = if_none(health, factory=probe_factory)
    ref_tactics = tactic_from_body_fn(split.body_suffix)
    stripped = first_truthy(strip_fn(ref_tactics).strip(), ref_tactics)

    def _eval(kind: str, tactics: str, **kwargs: Any) -> Any:
        return evaluate_fn(
            record,
            kind=kind,
            tactics=tactics,
            timeout=compile_timeout,
            state_root=state_root,
            elan_home=elan_home,
            network=network,
            skip_checkout=skip_checkout,
            **kwargs,
        )

    return collect_warmup_problem(
        record,
        records,
        split=split,
        reconstruct_ok=record["src"] == split.reconstructed_src,
        error_cls=error_cls,
        retrieve_fn=retrieve_fn,
        phases=list(phases),
        probe=probe,
        ref_tactics=ref_tactics,
        stripped=stripped,
        token_fn=token_fn,
        evaluate_fn=_eval,
        pin_fn=pin_reference_scores,
        composite_fn=composite_fn,
        prompt_fn=prompt_fn,
        generate_fn=lambda prompt: maybe_generate_fn(
            prompt,
            health=probe,
            source=get_str(record, "source"),
            max_new_tokens=max_new_tokens,
            timeout=generate_timeout,
            generate=generate,
            get_trace=get_trace,
        ),
        skip_reason_fn=generation_skip_reason,
        append_fn=append_generated,
        extract_fn=extract_fn,
        keep_fn=keep_fn,
        failure_fn=failure_fn,
        pack_fn=pack_problem_result,
        max_candidates=max_candidates,
        hardware_class=hardware_class,
        hammers=hammers,
        typesafe=typesafe,
        generator=generator,
        loop_version=loop_version,
        generator_default=generator,
    )


def fill_timed_attempt(
    *,
    tactic: str,
    argv: Sequence[str],
    cwd: Any,
    source_file: str,
    timeout: float,
    run_fn: Callable[[], Any],
    fill_fn: Callable[..., Any],
    timed_fn: Callable[..., tuple[Any, float, float]],
) -> Any:
    """Time an injected lake/lean run, then fill a tactic attempt. run_fn is the oracle."""

    result, wall_ms, cpu_ms = timed_fn(run_fn)
    return fill_fn(
        tactic=tactic,
        argv=argv,
        cwd=str(cwd),
        source_file=source_file,
        timeout=timeout,
        result=result,
        wall_ms=wall_ms,
        cpu_ms=cpu_ms,
    )


def timed_tactic_with_lake_process(
    *,
    tactic: str,
    source_file: str,
    cwd: Any,
    lake_path: str,
    lean_path: str,
    timeout: float,
    env: Mapping[str, str],
    max_heartbeats: int,
    write_fn: Callable[..., Any],
    run_lean_process: Callable[..., Any],
    fill_fn: Callable[..., Any],
    timed_fn: Callable[..., tuple[Any, float, float]],
    refuse: str = "",
    error_cls: type[BaseException] = ValueError,
    write_args: Sequence[Any] = (),
    write_kwargs: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Write a candidate, measurement_argv, then run_lean_process. Lake is the oracle."""

    write_fn(*tuple(write_args), **dict(write_kwargs or {}))
    argv = measurement_argv(
        lake_path,
        lean_path,
        source_file,
        max_heartbeats=max_heartbeats,
        refuse=refuse,
        error_cls=error_cls,
    )
    from jevops.outer import overlay_map, text_or

    return fill_timed_attempt(
        tactic=tactic,
        argv=argv,
        cwd=cwd,
        source_file=source_file,
        timeout=timeout,
        run_fn=lambda: run_lean_process(
            argv,
            timeout=timeout,
            cwd=text_or(cwd),
            env=overlay_map(env),
        ),
        fill_fn=fill_fn,
        timed_fn=timed_fn,
    )


def pack_statement_report(**fields: Any) -> dict[str, Any]:
    """Prefix-bind / admission report overlay. Bind literals live in split_statement_suffix."""

    out = dict(fields)
    out["arena_score"] = None
    return out


def pack_retrieval_report(
    retrieval: Any,
    *,
    records: Sequence[Mapping[str, Any]],
    lemma_cap: int,
    prompt_neighbors: Sequence[Mapping[str, Any]],
    asdict_fn: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """JSONL-neighbor retrieval report. Not a score. Bind check stays in the consumer."""

    neighbors = list(getattr(retrieval, "neighbors", ()) or ())
    lemmas = list(getattr(retrieval, "src_lemmas", ()) or ())
    neighbor_names = [item.name for item in neighbors]
    all_names = [str(item.get("name") or "") for item in records]
    query = getattr(retrieval, "query", None)
    expected = [name for name in all_names if name != query]
    query_src = ""
    for row in records:
        if row.get("name") == query:
            query_src = str(row.get("src") or "")
            break
    lemma_in_src = all(item.name in query_src for item in lemmas)
    tactics = sorted({item.tactic for item in lemmas})
    families = {item.tactic for item in lemmas}
    return {
        "name": getattr(retrieval, "query", None),
        "source": getattr(retrieval, "source", None),
        "n_neighbors": len(neighbors),
        "neighbor_names": neighbor_names,
        "neighbors_are_the_other_fourteen": neighbor_names == expected,
        "self_excluded": getattr(retrieval, "query", None) not in neighbor_names,
        "full_src_retrieved": all(
            item.src == next(r["src"] for r in records if r["name"] == item.name) for item in neighbors
        ),
        "prefix_bind_neighbors": all(item.src.startswith(item.statement) for item in neighbors),
        "n_src_lemmas": len(lemmas),
        "n_src_lemmas_uncapped": getattr(retrieval, "n_src_lemmas_uncapped", 0),
        "src_lemma_cap_held": len(lemmas) <= int(lemma_cap),
        "src_lemmas": [dict(asdict_fn(item)) for item in lemmas],
        "src_lemma_names": [item.name for item in lemmas],
        "src_lemma_tactics": tactics,
        "has_simp": "simp" in families,
        "has_rw": "rw" in families,
        "has_exact": "exact" in families,
        "has_apply": "apply" in families,
        "lemmas_mentioned_in_src": lemma_in_src,
        "lemma_id_digest": getattr(retrieval, "lemma_id_digest", ""),
        "lemma_id_digest_hex64": len(str(getattr(retrieval, "lemma_id_digest", "") or "")) == 64,
        "n_lemma_ids": len(getattr(retrieval, "lemma_ids", ()) or ()),
        "arena_score": getattr(retrieval, "arena_score", None),
        "score": None,
        "relevance_score": None,
        "corpus_manifest_ingest": getattr(retrieval, "corpus_manifest_ingest", False),
        "mathlib_ingest": getattr(retrieval, "mathlib_ingest", False),
        "prompt_neighbor_names": [item["name"] for item in prompt_neighbors],
    }


def pack_lemma_cap_fixture(
    *,
    names: Sequence[str],
    lemmas: Sequence[Any],
    uncapped: int,
    cap: int,
    extra_name: str = "ExtraIdent",
) -> dict[str, Any]:
    """Self-check view of lemma-id capping. Not a score."""

    lemma_names = [item.name for item in lemmas]
    return {
        "uncapped": uncapped,
        "returned": len(lemmas),
        "names": lemma_names,
        "first": lemma_names[0] if lemma_names else "",
        "last": lemma_names[-1] if lemma_names else "",
        "includes_extra_apply": extra_name in lemma_names,
        "tactics": sorted({item.tactic for item in lemmas}),
        f"capped_at_{int(cap)}": len(lemmas) == int(cap) and lemma_names == list(names)[: int(cap)],
        "uncapped_has_all_twenty_plus_extra": int(uncapped) == len(list(names)) + 1,
    }


def synthetic_proof_receipt(
    receipt_cls: Any,
    paths_cls: Any,
    *,
    name: str,
    lean_tag: str,
    verdict: str,
    body: str,
    digest_fn: Callable[[bytes], str],
    premises_digest: str = "",
    git_commit: str = "",
    token_count: int = 1,
) -> tuple[Any, str]:
    """Build a tiny proof receipt for self-check. Body is not admitted Lean."""

    digest = digest_fn(str(body).encode("utf-8"))
    receipt = receipt_cls(
        name=name,
        lean_tag=lean_tag,
        body_digest=digest,
        verdict=verdict,
        executable_paths=paths_cls(
            lean=f"/elan/toolchains/leanprover--lean4---{lean_tag}/bin/lean",
            lake=f"/elan/toolchains/leanprover--lean4---{lean_tag}/bin/lake",
        ),
        premises_digest=premises_digest,
        git_commit=git_commit,
        lean_version=lean_tag,
        token_count=int(token_count),
        elab_proxy=None,
    )
    return receipt, body


def pack_inits_replay_receipt(
    *,
    name: str,
    source_tokens: int,
    replay_tokens: int,
    target_tokens: int,
    n_kernels: int,
    stamp: str,
    digest: str,
    schema: str = "lra-inits-updates-replay/v1",
    hardware_class: str = "spark_gb10",
) -> dict[str, Any]:
    """Closed InitsUpdatesComm replay receipt. Lake still admits."""

    return {
        "schema": schema,
        "observed_at": stamp,
        "name": name,
        "source_tokens": int(source_tokens),
        "replay_tokens": int(replay_tokens),
        "target_tokens": int(target_tokens),
        "n_kernels": int(n_kernels),
        "called_llm": False,
        "arena_score": None,
        "official_track2": False,
        "hardware_class": hardware_class,
        "warmup_jsonl_sha256": digest,
    }


def drive_home_lean(
    declaration: str,
    body: str,
    *,
    timeout: float,
    autostart_key: str,
    prefix: str,
    relative: Sequence[str] = (".elan", "bin", "lean"),
) -> dict[str, Any]:
    """Advisory standalone lean under the user elan home. Not a lake admit and not PATH lean."""

    return check_standalone_lean(
        declaration,
        body,
        lean_bin=Path.home().joinpath(*relative),
        timeout=timeout,
        autostart_key=autostart_key,
        prefix=prefix,
    )


def drive_with_first(plan: Any, pack_fn: Callable[[Any], Any]) -> Any:
    """Pack a bake plan after resolving its first job."""

    return pack_fn(plan.first_job)


def drive_compile_public(
    plan: Any,
    pack_fn: Callable[..., Any],
    *,
    pins_fn: Callable[[Any], Sequence[Any]],
) -> Any:
    """Pack a compile plan using pins from the first record."""

    first = plan.first_record
    return pack_fn(first, pins_fn(first.get("version_info")))


def drive_receipt_public(
    receipt: Any,
    parent_fn: Callable[..., dict[str, Any]],
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    """Public receipt dict plus consumer authority fields. No proof body."""

    from jevops.outer import public_fields

    return parent_fn(extra=public_fields(receipt, (), extra=dict(extra)))


def drive_file_result_public(result: Any, *, asdict_fn: Callable[[Any], Any], head_n: int = 240) -> dict[str, Any]:
    """Public grok-file result. Chat is not the deliverable."""

    from jevops.outer import head_chars

    return {
        "tactics_path": result.tactics_path,
        "workspace": result.workspace,
        "used_file": result.used_file,
        "chat_ignored": result.chat_ignored,
        "chat_head": result.chat_head,
        "n_chars": len(result.tactics),
        "tactics_head": head_chars(result.tactics, head_n),
        "called_docker0": result.called_docker0,
        "identity": asdict_fn(result.identity),
        "arena_score": result.arena_score,
    }


def pack_compile_plan(
    first: Mapping[str, Any],
    first_pins: Sequence[Any],
    *,
    frozen_warmup_sha256: str,
    jsonl_bytes: int,
    n_records: int,
    first_source: str,
    first_tag: str,
    first_commit: str,
    first_file: str,
    first_url: str,
    kernel_command_template: str,
    measurement_argv_template: str,
    measurement_max_heartbeats: int,
    ikv_timeout: float,
    official_timeout: float,
    warmup_timeout: float,
) -> dict[str, Any]:
    """Compile-plan JSON. Arena score stays None."""

    pin = first_pins[0] if first_pins else None
    tag = str(getattr(pin, "lean_tag", "") or "")
    commit = str(getattr(pin, "git_commit", "") or "")
    source = str(first.get("source") or "")
    file_path = str(first.get("file_path") or "")
    url = str(first.get("url") or "")
    return {
        "arena_score": None,
        "expand_after_first_green": True,
        "first_commit": commit,
        "first_file": file_path,
        "first_is_strata": source == first_source,
        "first_is_strata_v4_26": (
            source == first_source
            and bool(first_pins)
            and tag == first_tag
            and commit == first_commit
            and file_path == first_file
            and url == first_url
        ),
        "first_name": str(first.get("name") or ""),
        "first_tag": tag,
        "first_url": url,
        "frozen_warmup_sha256": frozen_warmup_sha256,
        "independent_kernel_verifier_default_timeout_seconds": ikv_timeout,
        "independent_kernel_verifier_is_lake_oracle": False,
        "jsonl_bytes": int(jsonl_bytes),
        "kernel_command_template": kernel_command_template,
        "measurement_argv_template": measurement_argv_template,
        "measurement_maxHeartbeats": int(measurement_max_heartbeats),
        "n_records": int(n_records),
        "newest_tag_first": True,
        "official_timeout_seconds": official_timeout,
        "score": None,
        "warmup_timeout_seconds": warmup_timeout,
    }


def pack_bake_plan(
    jobs: Sequence[Any],
    first: Any,
    *,
    frozen_warmup_sha256: str,
    jsonl_bytes: int,
    n_records: int,
    bake_argv_template: str,
    kernel_command_template: str,
    measurement_max_heartbeats: int,
    first_source: str,
    first_tag: str,
    first_commit: str,
    putnam_module: str,
    putnam_tags: Sequence[str],
    strata_first_tag: str,
) -> dict[str, Any]:
    """Bake-plan JSON. Arena score stays None."""

    from jevops.outer import count_where

    return {
        "arena_score": None,
        "bake_argv_template": bake_argv_template,
        "first_is_strata_v4_26": (
            getattr(first, "kind", "") == "repo"
            and getattr(first, "source", "") == first_source
            and getattr(first, "lean_tag", "") == first_tag
            and getattr(first, "git_commit", "") == first_commit
        ),
        "first_job": first.to_dict() if hasattr(first, "to_dict") else dict(first),
        "frozen_warmup_sha256": frozen_warmup_sha256,
        "jsonl_bytes": int(jsonl_bytes),
        "jobs": [job.to_dict() if hasattr(job, "to_dict") else dict(job) for job in jobs],
        "kernel_command_template": kernel_command_template,
        "measurement_maxHeartbeats": int(measurement_max_heartbeats),
        "n_jobs": len(list(jobs)),
        "n_putnam_jobs": count_where(jobs, lambda job: getattr(job, "kind", "") == "putnam"),
        "n_records": int(n_records),
        "n_repo_jobs": count_where(jobs, lambda job: getattr(job, "kind", "") == "repo"),
        "putnam_module": putnam_module,
        "putnam_not_tmp_lean": True,
        "putnam_tags": list(putnam_tags),
        "score": None,
        "strata_first_tag": strata_first_tag,
    }


def putnam_bake_job(
    *,
    lean_tag: str,
    putnam_source: str,
    putnam_relpath: str,
    putnam_module: str,
    git_commit: str = "",
    name: str = "",
    url: str = "",
    cache_key: Optional[str] = None,
    phase: int = 2,
) -> BakeJob:
    """Putnam lake-project job. Never Tmp.lean."""

    tag = str(lean_tag)
    return BakeJob(
        kind="putnam",
        source=putnam_source,
        lean_tag=tag,
        git_commit=str(git_commit or ""),
        url=str(url or ""),
        cache_key=str(cache_key or f"putnam/{tag}"),
        phase=int(phase),
        record_names=(str(name),) if name else (),
        file_paths=(putnam_relpath,),
        module=putnam_module,
        lakefile_required=True,
    )


def pack_olean_receipt(
    job: Any,
    *,
    schema: str = "lra-olean-bake/v1",
    synthetic: bool = True,
) -> dict[str, Any]:
    """Dummy olean-cache receipt. Not a live lake bake."""

    return {
        "schema": schema,
        "cache_key": getattr(job, "cache_key", ""),
        "kind": getattr(job, "kind", ""),
        "lean_tag": getattr(job, "lean_tag", ""),
        "synthetic": bool(synthetic),
        "lake_build_executed": False,
        "arena_score": None,
    }


def finalize_proof_receipt(
    receipt: Any,
    *,
    body: Optional[str] = None,
    digest_fn: Callable[[bytes], str],
    project_fn: Callable[[Any], Mapping[str, str]],
    key_fn: Callable[[Any, Mapping[str, str]], str],
    now_fn: Callable[[], float],
    error_cls: type[BaseException] = ValueError,
    empty: str = "body_digest must be sha256 hex",
) -> Any:
    """Fill digest/cid/dimensions/key. Filesystem still owns the body."""

    if getattr(receipt, "executable_paths", None) is None:
        raise error_cls("executable_paths required")
    from jevops.outer import ensure_digest

    receipt.body_digest = ensure_digest(
        receipt.body_digest,
        data=body.encode("utf-8") if body is not None else None,
        digest_fn=digest_fn,
        error_cls=error_cls,
        empty=empty,
    )
    if not receipt.candidate_cid:
        receipt.candidate_cid = receipt.body_digest
    receipt.created_at = receipt.created_at or now_fn()
    receipt.dimensions = dict(project_fn(receipt))
    receipt.key_digest = key_fn(receipt, receipt.dimensions)
    return receipt


def pack_compile_extra(
    receipt: Mapping[str, Any],
    *,
    lean_tag: str,
    start_line: int,
    end_line: int,
    stdout: str,
    errors_in: Sequence[Mapping[str, Any]],
    errors_out: Sequence[Mapping[str, Any]],
    wall: float,
    tail_fn: Callable[[Any, int], Any],
    head_fn: Callable[[Sequence[Any], int], Sequence[Any]],
) -> dict[str, Any]:
    """Keep-best compile overlay. Lake still admits."""

    stderr = receipt.get("stderr")
    return {
        "error": receipt.get("error") or receipt.get("stderr_digest"),
        "lean_tag": lean_tag,
        "theorem_span": [int(start_line), int(end_line)],
        "argv": receipt.get("argv"),
        "compile_wall_ms_outer": wall,
        "stdout_tail": tail_fn(stdout, 400) if stdout else None,
        "stderr_tail": tail_fn(stderr, 400) if isinstance(stderr, str) else None,
        "errors": list(errors_in or head_fn(errors_out, 6)),
    }


def identity_from_mapping(
    cls: Any,
    mapping: Mapping[str, Any],
    *,
    requested_provider: str,
    requested_model: str,
) -> Any:
    """Rebuild a provider identity from a mapping. Chat is not Lean."""

    payload = dict(mapping or {})
    return cls(
        requested_provider=str(payload.get("requested_provider") or requested_provider),
        requested_model=str(payload.get("requested_model") or requested_model),
        resolved_provider=str(payload.get("resolved_provider") or ""),
        resolved_model=str(payload.get("resolved_model") or ""),
        fallback_used=bool(payload.get("fallback_used")),
        arena_score=None,
    )


def grok_cli_identity(
    cls: Any,
    *,
    requested_provider: str,
    requested_model: str,
) -> Any:
    """Resolved grok CLI identity. Chat is not Lean."""

    return cls(
        requested_provider=requested_provider,
        requested_model=requested_model,
        resolved_provider="grok_cli",
        resolved_model=requested_model,
        fallback_used=False,
        arena_score=None,
    )


def healthy_probe(
    cls: Any,
    *,
    url: str,
    alias_url: str,
    autostart: str = "0",
    status_code: int = 200,
) -> Any:
    """Health probe that is already up. Does not start a server."""

    return cls(
        ok=True,
        url=url,
        alias_ok=False,
        alias_url=alias_url,
        status_code=status_code,
        error="",
        autostart=autostart,
    )


def forced_unhealthy(
    cls: Any,
    *,
    url: str,
    alias_url: str,
    error: str,
    autostart: str,
) -> Any:
    """Health probe that is already closed. Does not start a server."""

    return cls(
        ok=False,
        url=url,
        alias_ok=False,
        alias_url=alias_url,
        status_code=None,
        error=error,
        autostart=autostart,
    )
