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


def plant_fake_toolchain(
    elan_home: Any,
    lean_tag: str,
    *,
    dirname_fn: Callable[[str], str],
    files: Mapping[str, str],
) -> Path:
    """Plant tag-pinned lake/lean scripts. Injected bodies stay in the consumer."""

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
) -> dict[str, Any]:
    """Putnam vs repo keep-best compile. Lake is the oracle. Never PATH lean."""

    record = dict(record)
    record["version_info"] = list(pins_fn(record) or ())
    if not record["version_info"]:
        return dict(closed_fn(token_count=token_fn(tactics)))
    if str(record.get("source") or "") == putnam_source:
        patched = patch_fn(record, tactics, statement=statement_fn(record))
        started = now_fn()
        receipt = _first_receipt_dict(compile_fn(patched))
        stdout = str(receipt.get("stdout") or "")
        errors = list(parse_errors_fn(stdout) or ())
        return dict(
            pack_fn(
                receipt,
                token_count=token_fn(tactics),
                errors=errors,
                sorry=bool(sorry_fn(stdout, 1, 10**9)),
                extra={"compile_wall_ms_outer": elapsed_fn(started)},
            )
        )
    dest = dest_fn(record)
    write_bytes_fn(dest, restore)
    replacement = candidate_source_fn(record, tactics)
    original = restore.decode("utf-8") if isinstance(restore, (bytes, bytearray)) else str(restore)
    start_line, end_line = span_fn(original, str(record["src"]), replacement)
    splice_fn(dest, str(record["src"]), replacement)
    started = now_fn()
    receipts = compile_fn(record)
    write_bytes_fn(dest, restore)
    receipt = _first_receipt_dict(receipts)
    stdout = str(receipt.get("stdout") or "")
    errors = list(parse_errors_fn(stdout) or ())
    errors_in = [item for item in errors if line_in_span_fn(item.get("pos"), start_line, end_line)]
    errors_out = [item for item in errors if not line_in_span_fn(item.get("pos"), start_line, end_line)]
    return dict(
        pack_fn(
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
        )
    )


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


def pack_statement_report(**fields: Any) -> dict[str, Any]:
    """Prefix-bind / admission report overlay. Bind literals stay in the consumer."""

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
