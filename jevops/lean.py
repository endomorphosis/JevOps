#!/usr/bin/env python3
"""Lean syntax and lake-compile helpers. Jev does not write Lean.

Lake is the oracle. IndependentKernelVerifier is not. Never docker0.
Not Arena scores. Not Track 2.
"""
from __future__ import annotations

import re
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


END_MARKERS = ("<|im_end|>", "</s>", "<|endoftext|>", "<|eot_id|>")


def extract_generated_tactics(text: str) -> str:
    """Take a tactic block from an untrusted model payload. Not a statement splice."""

    from jevops.mask import split_before_markers, strip_fence
    from jevops.outer import strip_leading_prefixes

    if not isinstance(text, str):
        return ""
    raw = split_before_markers(strip_fence(text), END_MARKERS)
    try:
        raw = strip_leading_prefixes(raw, BODY_BY_PREFIXES)
    except Exception:
        pass
    return raw.strip()


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
        mathlib_rev=tag,
        aesop_git=aesop_git,
        aesop_rev=tag,
        jsonl_version_pin=jsonl_version_pin,
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
    theorem_ok = not timed_out and not list(errors or ()) and not sorry
    out = {
        "ok": bool(theorem_ok),
        "theorem_ok": bool(theorem_ok),
        "module_exit_0": receipt.get("exit_code") == 0 and not timed_out,
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

