#!/usr/bin/env python3
"""Lake-native tactic try for Lean Refactor Arena loop v2 (path A).

Replace the proof body with ``sorry``, then try a fixed tactic list via
tag-pinned ``lake env lean`` and ``run_lean_process``. No
``LeanFrontend.snapshot_goal`` and no ``GoalSnapshot``. Loop v1 (30 Sep)
does not run this. Do not claim HAMMER-006 is LRA-ready. Path B (a
lake-aware frontend sibling) is a follow-up, not this module.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import bake_oleans as lra_bake  # noqa: E402
import compile_worker as lra_compile  # noqa: E402
import splice as lra_splice  # noqa: E402

DATASETS_ROOT = _jevops_path.IPFS_DATASETS_ROOT
LEAN_FRONTEND_PATH = (
    DATASETS_ROOT / "ipfs_datasets_py" / "logic" / "hammers" / "frontends" / "lean.py"
)

if str(DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASETS_ROOT))
from lean_toolchain import (  # noqa: E402
    KERNEL_COMMAND_TEMPLATE,
    LeanToolchainMissing,
    audit_lean_frontend_path_json,
    run_lean_process,
)

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
STRATA_SOURCE = lra_bake.STRATA_SOURCE
PUTNAM_SOURCE = lra_bake.PUTNAM_SOURCE
STRATA_FIRST_TAG = lra_bake.STRATA_FIRST_TAG
STRATA_FIRST_COMMIT = lra_bake.STRATA_FIRST_COMMIT
STRATA_URL = lra_bake.STRATA_URL
STRATA_FIRST_FILE = lra_compile.STRATA_FIRST_FILE
MEASUREMENT_MAX_HEARTBEATS = lra_bake.MEASUREMENT_MAX_HEARTBEATS
MEASUREMENT_ARGV_TEMPLATE = lra_compile.MEASUREMENT_ARGV_TEMPLATE
LEAN_NUM_THREADS = lra_compile.LEAN_NUM_THREADS
PROCESS_SUPERVISOR_ENV = lra_compile.PROCESS_SUPERVISOR_ENV
INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS = (
    lra_compile.INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS
)

LOOP_VERSION = "v2"
PATH_NAME = "A"
ON_30_SEP_CRITICAL_PATH = False
V1_RUNS_THIS = False
HAMMER_006_LRA_READY = False
USES_SNAPSHOT_GOAL = False
GOAL_SNAPSHOT_REQUIRED = False
PATH_B_IMPLEMENTED = False
GENERATOR_IDENTITY = "lake_native"
RECEIPT_SCHEMA = "lra-lake-native-try/v1"
PROTOCOL = "LRA/v1"
PR_ID = "PR-5"
LRAH_ID = "LRAH-005"
HAMMER_006_CLAIM = "Do not claim HAMMER-006 is LRA-ready."
CRITICAL_PATH_NOTE = "Not on the 30 Sep critical path."
from jevops.lean import AESOP_TACTIC
from jevops.lean import PATH_A_TACTICS as FIXED_TACTICS
from jevops.lean import SORRY_TACTIC
TACTIC_TIMEOUT_SECONDS = 120.0
UNSOLVED_RELPATH = "Strata/Unsolved.lean"

FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "fcntl",
        "IndependentKernelVerifier",
        "KernelVerifier",
        "LeanFrontend",
        "GoalSnapshot",
        "LeanLakeFrontend",
        "attempt_native_automation",
        "LeanReconstructor",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "shutil",
    }
)
FORBIDDEN_CALLS = frozenset(
    {
        "which",
        "find_executable",
        "LOCK_EX",
        "snapshot_goal",
        "attempt_native_automation",
    }
)
FORBIDDEN_ATTRS = frozenset(
    {
        "snapshot_goal",
        "GoalSnapshot",
        "LeanFrontend",
        "attempt_native_automation",
        "LOCK_EX",
        "find_executable",
    }
)
FORBIDDEN_SCORE_NAMES = frozenset(
    {
        "arena_score",
        "arena_score_tokens",
        "arena_score_elab",
        "official_track2_score",
        "token_savings",
    }
)

from jevops.lean import AESOP_IMPORT as _AESOP_IMPORT


class TryError(RuntimeError):
    """Fail-closed lake-native tactic-try error."""


class TryToolchainMissing(TryError):
    """Tag-pinned elan lake/lean is not installed. Not a PATH fallback."""


from jevops.lean import TacticAttempt
from jevops.lean import TacticTryReceipt


def sha256_bytes(data: bytes) -> str:
    from jevops.outer import digest_hex

    return digest_hex(data)


def sha256_file(path: Path) -> str:
    from jevops.outer import digest_file

    return digest_file(path)


def sha256_text(text: str) -> str:
    from jevops.outer import digest_text

    return digest_text(text)


def aesop_imported(record: Mapping[str, Any]) -> bool:
    from jevops.lean import AESOP_IMPORT
    from jevops.outer import any_search

    return any_search((record.get("header") or "", record.get("src") or ""), AESOP_IMPORT)


def tactics_for_record(record: Mapping[str, Any]) -> list[str]:
    from jevops.lean import path_a_tactics

    return path_a_tactics(str(record.get("header") or ""), str(record.get("src") or ""))


def sorry_lake_source(record: Mapping[str, Any]) -> str:
    from jevops.lean import lake_source_for_tactic

    split = lra_splice.split_statement_body(record)
    return lake_source_for_tactic(
        header=split.header,
        statement=split.statement,
        tactic=SORRY_TACTIC,
        error_cls=TryError,
    )


def tactic_lake_source(record: Mapping[str, Any], tactic: str) -> str:
    from jevops.lean import lake_source_for_tactic

    split = lra_splice.split_statement_body(record)
    return lake_source_for_tactic(
        header=split.header,
        statement=split.statement,
        tactic=tactic,
        error_cls=TryError,
    )


def write_tactic_source(record: Mapping[str, Any], dest: Path, tactic: str) -> Path:
    from jevops.outer import write_text

    text = (
        sorry_lake_source(record) if tactic == SORRY_TACTIC else tactic_lake_source(record, tactic)
    )
    return write_text(
        dest,
        text,
        refuse=lra_bake.FORBIDDEN_PUTNAM_BASENAME,
        error_cls=TryError,
        refuse_fmt="refusing to write {name}",
    )


def _attempt_from_result(
    *,
    tactic: str,
    argv: Sequence[str],
    cwd: str,
    source_file: str,
    timeout: float,
    result: Any,
    wall_ms: float,
    cpu_ms: float,
    error: str = "",
) -> TacticAttempt:
    from jevops.lean import fill_tactic_attempt

    return fill_tactic_attempt(
        tactic=tactic,
        argv=argv,
        cwd=cwd,
        source_file=source_file,
        timeout=timeout,
        result=result,
        wall_ms=wall_ms,
        cpu_ms=cpu_ms,
        max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        sorry=SORRY_TACTIC,
        error=error,
    )


def _run_tactic(
    record: Mapping[str, Any],
    *,
    tactic: str,
    dest: Path,
    source_file: str,
    cwd: Path,
    lake_path: str,
    lean_path: str,
    timeout: float,
    env: Mapping[str, str],
) -> TacticAttempt:
    write_tactic_source(record, dest, tactic)
    argv = lra_compile.measurement_argv(
        lake_path,
        lean_path,
        source_file,
        max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
    )
    from jevops.lean import fill_timed_attempt
    from jevops.outer import timed_call

    return fill_timed_attempt(
        tactic=tactic,
        argv=argv,
        cwd=cwd,
        source_file=source_file,
        timeout=timeout,
        run_fn=lambda: run_lean_process(
            argv,
            timeout=timeout,
            cwd=str(cwd),
            env=dict(env),
        ),
        fill_fn=_attempt_from_result,
        timed_fn=timed_call,
    )


def _prepare_project(
    record: Mapping[str, Any],
    pin: lra_compile.VersionPin,
    *,
    state_root: Optional[Path],
    network: str,
    skip_checkout: bool,
) -> tuple[Path, str, Path]:
    from jevops.lean import prepare_lake_paths

    return prepare_lake_paths(
        record,
        pin,
        putnam_source=PUTNAM_SOURCE,
        putnam_relpath=lra_bake.PUTNAM_CANDIDATE_RELPATH,
        source_relpath_fn=lra_compile.source_relpath,
        putnam_dir_fn=lambda rec, p, root: lra_compile.project_dir_for_record(rec, p, state_root=root),
        materialize_fn=lambda p, dest: lra_bake.materialize_putnam_project(
            p.lean_tag, dest, jsonl_version_pin=p.git_commit
        ),
        require_clone_fn=lambda url, net, root: lra_compile.require_clone(
            url, network=net, state_root=root
        ),
        checkout_fn=lra_compile.checkout_commit,
        skip_checkout=skip_checkout,
        network=network,
        state_root=state_root,
    )


def try_tactics(
    record: Mapping[str, Any],
    pin: lra_compile.VersionPin,
    *,
    timeout: float = TACTIC_TIMEOUT_SECONDS,
    state_root: Optional[Path] = None,
    elan_home: Optional[Path] = None,
    network: str = "allow",
    skip_checkout: bool = False,
) -> TacticTryReceipt:
    """Path A: sorry hole, then ``rfl``/``decide``/``omega``/``simp_all``/``aesop``."""

    timeout = lra_compile.require_lake_timeout(timeout)
    considered = tactics_for_record(record)
    split = lra_splice.split_statement_body(record)
    template = lra_splice.statement_sorry_template(split.statement)
    lake_sorry = sorry_lake_source(record)
    from jevops.lean import aesop_list_ok, init_try_receipt, sorry_prefix_bound

    receipt = init_try_receipt(
        record,
        pin,
        relpath=lra_compile.source_relpath(record),
        template_digest=sha256_text(template),
        prefix_bound=sorry_prefix_bound(
            template=template,
            statement=split.statement,
            suffix=lra_splice.STATEMENT_SORRY_SUFFIX,
            lake_sorry=lake_sorry,
        ),
        aesop=aesop_imported(record),
        considered=considered,
        timeout=timeout,
        schema=RECEIPT_SCHEMA,
        loop=LOOP_VERSION,
        path=PATH_NAME,
        pr=PR_ID,
        lrah=LRAH_ID,
        generator=GENERATOR_IDENTITY,
        kernel_command_template=KERNEL_COMMAND_TEMPLATE,
        measurement_argv_template=MEASUREMENT_ARGV_TEMPLATE,
    )
    aesop_err = aesop_list_ok(considered, receipt.aesop_imported)
    from jevops.lean import close_failed_receipt, lake_supervisor_fields, path_a_fill, run_path_a_try
    from jevops.outer import env_copy, under_or_tmp

    def _env(toolchain: Any) -> Mapping[str, str]:
        supervisor_dir = under_or_tmp(
            state_root, "process-supervisor", tmp_name="lra-021-process-supervisor"
        )
        return env_copy(
            lake_supervisor_fields(
                threads=LEAN_NUM_THREADS,
                elan_home=toolchain.elan_home,
                supervisor_dir=supervisor_dir,
                process_env_key=PROCESS_SUPERVISOR_ENV,
            )
        )

    def _run_one(*, tactic: str, dest: Path, source_file: str, cwd: Path, toolchain: Any, timeout: float, env: Mapping[str, str]) -> TacticAttempt:
        return _run_tactic(
            record,
            tactic=tactic,
            dest=dest,
            source_file=source_file,
            cwd=cwd,
            lake_path=toolchain.lake_path,
            lean_path=toolchain.lean_path,
            timeout=timeout,
            env=env,
        )

    def _extra(exc: BaseException) -> str:
        if isinstance(exc, (LeanToolchainMissing, lra_compile.CompileToolchainMissing)):
            return (
                "; tag-pinned elan is a capability gap, not PATH lean "
                "usability and not LeanFrontend.snapshot_goal"
            )
        return ""

    return run_path_a_try(
        receipt,
        considered,
        aesop_err=aesop_err,
        resolve_fn=lambda: lra_compile.resolve_pin(pin, elan_home=elan_home, require_installed=True),
        prepare_fn=lambda: _prepare_project(
            record,
            pin,
            state_root=state_root,
            network=network,
            skip_checkout=skip_checkout,
        ),
        env_fn=_env,
        run_tactic_fn=_run_one,
        fill_fn=path_a_fill,
        close_fn=lambda rec, exc, extra: close_failed_receipt(
            rec, exc, digest_fn=sha256_text, axiom_digest_fn=lra_compile.axiom_digest, extra=extra
        ),
        error_types=(TryError, lra_compile.CompileError, LeanToolchainMissing, lra_bake.BakeError),
        extra_fn=_extra,
        timeout=timeout,
    )


def first_record_of_source(
    records: Sequence[Mapping[str, Any]], source: str
) -> Mapping[str, Any]:
    from jevops.outer import first_where

    return first_where(
        records,
        lambda record: record.get("source") == source,
        error_cls=TryError,
        miss=f"warmup JSONL has no {source} record",
    )


def pin_for_tag(record: Mapping[str, Any], lean_tag: str) -> lra_compile.VersionPin:
    from jevops.outer import first_or_last

    return first_or_last(
        lra_compile.iter_version_pins(record.get("version_info")),
        lambda pin: pin.lean_tag == lean_tag,
        error_cls=TryError,
        miss=f"{record.get('name')}: no version_info pins",
    )


def plan_try(path: Optional[Path] = None) -> dict[str, Any]:
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    from jevops.lean import path_a_plan_rows

    per_record = path_a_plan_rows(
        records,
        tactics_fn=tactics_for_record,
        aesop_fn=aesop_imported,
        aesop_tactic=AESOP_TACTIC,
    )
    first = first_record_of_source(records, STRATA_SOURCE)
    putnam = first_record_of_source(records, PUTNAM_SOURCE)
    from jevops.lean import pack_try_plan

    return pack_try_plan(
        digest=digest,
        jsonl_bytes=len(raw),
        n_records=len(records),
        per_record=per_record,
        first_name=str(first.get("name") or ""),
        first_tactics=tactics_for_record(first),
        putnam_name=str(putnam.get("name") or ""),
        putnam_tactics=tactics_for_record(putnam),
        extra={
            "aesop_if_imported": True,
            "critical_path_note": CRITICAL_PATH_NOTE,
            "fixed_tactics": list(FIXED_TACTICS),
            "generator": GENERATOR_IDENTITY,
            "goal_snapshot_required": GOAL_SNAPSHOT_REQUIRED,
            "hammer_006_claim": HAMMER_006_CLAIM,
            "hammer_006_lra_ready": HAMMER_006_LRA_READY,
            "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
            "loop": LOOP_VERSION,
            "lrah": LRAH_ID,
            "measurement_argv_template": MEASUREMENT_ARGV_TEMPLATE,
            "on_30_sep_critical_path": ON_30_SEP_CRITICAL_PATH,
            "path": PATH_NAME,
            "path_b_implemented": PATH_B_IMPLEMENTED,
            "pr": PR_ID,
            "protocol": PROTOCOL,
            "run_lean_process": run_lean_process.__name__,
            "sorry_template": "statement + ' := by\\nsorry'",
            "tactic_timeout_seconds": TACTIC_TIMEOUT_SECONDS,
            "uses_snapshot_goal": USES_SNAPSHOT_GOAL,
            "v1_runs_this": V1_RUNS_THIS,
        },
    )


def probe_toolchain(tags: Optional[Sequence[str]] = None) -> dict[str, Any]:
    from jevops.lean import overlay_try_probe

    return overlay_try_probe(
        lra_compile.probe_toolchain(tags),
        extra={
            "arena_score": None,
            "score": None,
            "generator": GENERATOR_IDENTITY,
            "goal_snapshot_required": False,
            "hammer_006_lra_ready": False,
            "lake_native_try": True,
            "loop": LOOP_VERSION,
            "on_30_sep_critical_path": False,
            "path": PATH_NAME,
            "path_b_implemented": False,
            "tactic_timeout_seconds": TACTIC_TIMEOUT_SECONDS,
            "uses_snapshot_goal": False,
            "v1_runs_this": False,
        },
    )


def write_receipts(receipts: Sequence[TacticTryReceipt], dest_dir: Path) -> list[str]:
    from jevops.outer import write_named_jsons

    return write_named_jsons(
        dest_dir,
        receipts,
        name_fn=lambda item: item.name,
        tag_fn=lambda item: item.lean_tag,
        payload_fn=lambda item: item.to_dict(),
    )


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _call_name(node: ast.AST) -> str:
    from jevops.repair import call_short_name

    return call_short_name(node)


def _assigned_constant(tree: ast.AST, name: str) -> Any:
    from jevops.repair import assigned_constant

    return assigned_constant(tree, name)


def audit_source(source: Optional[str] = None) -> dict[str, Any]:
    from jevops.outer import source_text
    from jevops.repair import assigned_constants, audit_source as _audit

    text = source_text(source, path=__file__)
    out = _audit(
        text,
        forbidden_imports=FORBIDDEN_IMPORT_NAMES,
        forbidden_calls=FORBIDDEN_CALLS,
        forbidden_scores=FORBIDDEN_SCORE_NAMES,
        forbidden_attrs=FORBIDDEN_ATTRS,
    )
    imported = set(out["imported_names"])
    calls = set(out["call_names"])
    score_assignments = list(out["score_keys"])
    frontend = audit_lean_frontend_path_json()
    consts = assigned_constants(
        text,
        (
            "HAMMER_006_LRA_READY",
            "ON_30_SEP_CRITICAL_PATH",
            "V1_RUNS_THIS",
            "USES_SNAPSHOT_GOAL",
            "LOOP_VERSION",
            "PATH_NAME",
        ),
    )
    hammer_ready = consts["HAMMER_006_LRA_READY"]
    on_critical = consts["ON_30_SEP_CRITICAL_PATH"]
    v1_runs = consts["V1_RUNS_THIS"]
    uses_snapshot = consts["USES_SNAPSHOT_GOAL"]
    loop_value = consts["LOOP_VERSION"]
    path_value = consts["PATH_NAME"]
    return {
        "imported_names": out["imported_names"],
        "forbidden_imports": out["forbidden_imports"],
        "forbidden_calls": out["forbidden_calls"],
        "forbidden_attrs": out["forbidden_attrs"],
        "score_assignments": score_assignments,
        "uses_run_lean_process": "run_lean_process" in calls,
        "uses_measurement_argv": "measurement_argv" in calls,
        "uses_statement_sorry_template": "statement_sorry_template" in calls,
        "uses_snapshot_goal_call": "snapshot_goal" in calls,
        "imports_lean_frontend": "LeanFrontend" in imported,
        "imports_goal_snapshot": "GoalSnapshot" in imported,
        "hammer_006_lra_ready_constant": hammer_ready,
        "on_30_sep_critical_path_constant": on_critical,
        "v1_runs_this_constant": v1_runs,
        "uses_snapshot_goal_constant": uses_snapshot,
        "loop_constant": loop_value,
        "path_constant": path_value,
        "lean_frontend": frontend,
        "ok": (
            not out["forbidden_imports"]
            and not out["forbidden_calls"]
            and not out["forbidden_attrs"]
            and not score_assignments
            and "run_lean_process" in calls
            and "measurement_argv" in calls
            and "statement_sorry_template" in calls
            and "snapshot_goal" not in calls
            and "LeanFrontend" not in imported
            and "GoalSnapshot" not in imported
            and hammer_ready is False
            and on_critical is False
            and v1_runs is False
            and uses_snapshot is False
            and loop_value == "v2"
            and path_value == "A"
            and frontend.get("unchanged_path_lean_json") is True
        ),
    }


_FAKE_LAKE = """#!/usr/bin/python3.12
import os
import sys

args = sys.argv[1:]
if not args or args[0] != "env" or len(args) < 2:
    sys.stderr.write("lra-021-fake-lake: expected 'env <lean> ...'\\n")
    sys.exit(2)
os.execv(args[1], args[1:])
"""

_FAKE_LEAN = r"""#!/usr/bin/python3.12
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


def _write_executable(path: Path, text: str) -> None:
    from jevops.outer import write_executable

    write_executable(path, text)


def plant_fake_toolchain(elan_home: Path, lean_tag: str) -> Path:
    from jevops.lean import plant_fake_toolchain as _fn

    return _fn(
        elan_home,
        lean_tag,
        dirname_fn=lra_bake.elan_toolchain_dirname,
        files={"lake": _FAKE_LAKE, "lean": _FAKE_LEAN},
    )


def unsolved_record() -> dict[str, Any]:
    from jevops.lean import unsolved_record as _fn

    return _fn(
        source=STRATA_SOURCE,
        file_path=UNSOLVED_RELPATH,
        url=STRATA_URL,
        lean_tag=STRATA_FIRST_TAG,
        git_commit=STRATA_FIRST_COMMIT,
    )


def _attempt_summary(attempt: Mapping[str, Any]) -> dict[str, Any]:
    from jevops.lean import attempt_summary

    return attempt_summary(
        attempt,
        max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        ikv_floor=INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS,
    )


def _receipt_summary(receipt: TacticTryReceipt) -> dict[str, Any]:
    from jevops.lean import try_receipt_summary

    return try_receipt_summary(
        receipt,
        attempt_fn=_attempt_summary,
        aesop_tactic=AESOP_TACTIC,
        sorry_tactic=SORRY_TACTIC,
    )


def _synthetic_try(
    records: Sequence[Mapping[str, Any]],
    *,
    persist_receipts: Optional[Path] = None,
) -> dict[str, Any]:
    from jevops.outer import temp_dir

    with temp_dir(prefix="lra-021-try-", parent=lra_compile._exec_scratch_parent()) as tmp:
        root = Path(tmp)
        elan_home = root / "elan"
        state_root = root / "state"
        receipts_dir = root / "receipts"
        for tag in ("v4.25.0", "v4.26.0", "v4.27.0"):
            plant_fake_toolchain(elan_home, tag)
        clone = lra_compile.plant_synthetic_strata_clone(
            lra_compile.clone_dir(STRATA_URL, state_root)
        )
        first = first_record_of_source(records, STRATA_SOURCE)
        putnam = first_record_of_source(records, PUTNAM_SOURCE)
        unsolved = unsolved_record()
        write_tactic_source(first, clone / STRATA_FIRST_FILE, SORRY_TACTIC)
        write_tactic_source(unsolved, clone / UNSOLVED_RELPATH, SORRY_TACTIC)
        first_pin = pin_for_tag(first, STRATA_FIRST_TAG)
        putnam_pin = pin_for_tag(putnam, STRATA_FIRST_TAG)
        unsolved_pin = pin_for_tag(unsolved, STRATA_FIRST_TAG)
        timeout_30_rejected = False
        try:
            lra_compile.require_lake_timeout(
                INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS
            )
        except lra_compile.LakeTimeoutTooSmall:
            timeout_30_rejected = True
        strata_receipt = try_tactics(
            first,
            first_pin,
            timeout=TACTIC_TIMEOUT_SECONDS,
            state_root=state_root,
            elan_home=elan_home,
            network="deny",
            skip_checkout=True,
        )
        putnam_receipt = try_tactics(
            putnam,
            putnam_pin,
            timeout=TACTIC_TIMEOUT_SECONDS,
            state_root=state_root,
            elan_home=elan_home,
            network="allow",
            skip_checkout=True,
        )
        unsolved_receipt = try_tactics(
            unsolved,
            unsolved_pin,
            timeout=TACTIC_TIMEOUT_SECONDS,
            state_root=state_root,
            elan_home=elan_home,
            network="deny",
            skip_checkout=True,
        )
        all_receipts = [strata_receipt, putnam_receipt, unsolved_receipt]
        written = write_receipts(all_receipts, receipts_dir)
        persisted: list[str] = []
        if persist_receipts is not None:
            persisted = write_receipts(all_receipts, Path(persist_receipts))
        missing_closed = False
        try:
            lra_compile.require_clone(
                "https://github.com/example/missing-lra-021",
                network="deny",
                state_root=state_root,
            )
        except lra_compile.CloneMissing:
            missing_closed = True
        from jevops.lean import pack_synthetic_try

        return pack_synthetic_try(
            elan_home=elan_home,
            missing_closed=missing_closed,
            written=written,
            persisted=persisted,
            putnam=putnam_receipt,
            strata=strata_receipt,
            unsolved=unsolved_receipt,
            timeout_30_rejected=timeout_30_rejected,
            summary_fn=_receipt_summary,
        )


def self_check(
    path: Optional[Path] = None,
    *,
    receipts_dir: Optional[Path] = None,
) -> dict[str, Any]:
    from jevops.outer import head_seq

    jsonl = Path(path) if path is not None else WARMUP_JSONL
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    audit = audit_source()
    synthetic = _synthetic_try(records, persist_receipts=receipts_dir)
    toolchain = probe_toolchain()
    plan = plan_try(jsonl)
    strata = synthetic["strata"]
    putnam = synthetic["putnam"]
    unsolved = synthetic["unsolved"]
    putnam_aesop_only = all(
        item["aesop_imported"] and item["aesop_in_list"] for item in plan["records"]
        if item["source"] == PUTNAM_SOURCE
    )
    non_putnam_no_aesop = all(
        (not item["aesop_imported"]) and (not item["aesop_in_list"])
        for item in plan["records"]
        if item["source"] != PUTNAM_SOURCE
    )
    report: dict[str, Any] = {
        "ok": False,
        "arena_score": None,
        "score": None,
        "aesop_only_when_imported": putnam_aesop_only and non_putnam_no_aesop,
        "audit": audit,
        "capability_gap": toolchain.get("capability_gap") or "",
        "compiled": bool(strata["ok"] and putnam["ok"]),
        "critical_path_note": CRITICAL_PATH_NOTE,
        "first_putnam_name": plan["first_putnam_name"],
        "first_strata_name": plan["first_strata_name"],
        "frozen_warmup_sha256": digest,
        "generator": GENERATOR_IDENTITY,
        "goal_snapshot_required": False,
        "hammer_006_claim": HAMMER_006_CLAIM,
        "hammer_006_lra_ready": False,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": digest == FROZEN_WARMUP_SHA256,
        "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
        "lake": True,
        "lean_frontend_unchanged_path_lean_json": bool(
            audit["lean_frontend"].get("unchanged_path_lean_json")
        ),
        "live_elan_installed": bool(toolchain.get("installed_tags")),
        "llama_server_started": False,
        "loop": LOOP_VERSION,
        "lrah": LRAH_ID,
        "measurement_argv_template": MEASUREMENT_ARGV_TEMPLATE,
        "n_records": len(records),
        "on_30_sep_critical_path": False,
        "path": PATH_NAME,
        "path_a_lake_env_lean": bool(
            strata["all_attempts_lake_env_lean"] and putnam["all_attempts_lake_env_lean"]
        ),
        "path_b_implemented": False,
        "plan": {
            "fixed_tactics": plan["fixed_tactics"],
            "first_putnam_tactics": plan["first_putnam_tactics"],
            "first_strata_tactics": plan["first_strata_tactics"],
        },
        "pr": PR_ID,
        "protocol": PROTOCOL,
        "putnam_aesop_won": putnam["winning_tactic"] == AESOP_TACTIC,
        "putnam_tried_fixed_tactics_before_aesop": putnam["tactics_run"]
        == list(FIXED_TACTICS) + [AESOP_TACTIC],
        "run_lean_process": run_lean_process.__name__,
        "snapshot_goal_required": False,
        "sorry_hole_then_tactic_list": bool(
            strata["sorry_first"]
            and strata["sorry_failed"]
            and putnam["sorry_first"]
            and putnam["sorry_failed"]
        ),
        "strata_decide_won": strata["winning_tactic"] == "decide",
        "strata_rfl_failed_first": (
            head_seq(strata["tactics_run"], 1) == ["rfl"] and strata["winning_tactic"] == "decide"
        ),
        "synthetic": synthetic,
        "tactic_timeout_seconds": TACTIC_TIMEOUT_SECONDS,
        "toolchain": toolchain,
        "unsolved_has_no_winner": unsolved["winning_tactic"] is None and not unsolved["ok"],
        "unsolved_ran_fixed_tactics": unsolved["tactics_run"] == list(FIXED_TACTICS),
        "uses_snapshot_goal": False,
        "v1_runs_this": False,
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and report["aesop_only_when_imported"]
        and report["path_a_lake_env_lean"]
        and report["sorry_hole_then_tactic_list"]
        and report["strata_decide_won"]
        and report["strata_rfl_failed_first"]
        and report["putnam_aesop_won"]
        and report["putnam_tried_fixed_tactics_before_aesop"]
        and report["unsolved_has_no_winner"]
        and report["unsolved_ran_fixed_tactics"]
        and strata["stopped_after_winner"]
        and putnam["stopped_after_winner"]
        and strata["sorry_template_prefix_bound"]
        and putnam["sorry_template_prefix_bound"]
        and strata["no_snapshot_goal_on_attempts"]
        and putnam["no_snapshot_goal_on_attempts"]
        and synthetic["timeout_30s_rejected"]
        and synthetic["missing_clone_fails_closed_under_network_deny"]
        and audit["ok"]
        and report["lean_frontend_unchanged_path_lean_json"]
        and report["hammer_006_lra_ready"] is False
        and report["on_30_sep_critical_path"] is False
        and report["v1_runs_this"] is False
        and report["uses_snapshot_goal"] is False
        and report["path_b_implemented"] is False
        and report["goal_snapshot_required"] is False
        and report["arena_score"] is None
        and report["score"] is None
        and report["llama_server_started"] is False
        and report["loop"] == "v2"
        and report["path"] == "A"
    )
    return report


def _print_json(payload: Mapping[str, Any]) -> None:
    from jevops.outer import print_json

    print_json(payload)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="sorry-hole then lake env lean tactic try on synthetic tag-pinned lake/lean",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print loop v2 path A tactic lists; not the 30 Sep critical path",
    )
    parser.add_argument(
        "--probe-toolchain",
        action="store_true",
        help="record tag-pinned elan paths; missing lake is a capability gap, not PATH usable",
    )
    parser.add_argument(
        "--try-name",
        action="store_true",
        help="run path A on one JSONL problem (live elan; fail closed if missing)",
    )
    parser.add_argument("--name", default="", help="JSONL problem name")
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL path")
    parser.add_argument("--state-root", type=Path, default=None, help="clone/putnam state root")
    parser.add_argument("--elan-home", type=Path, default=None, help="tag-pinned elan home")
    parser.add_argument("--network", default=None, help="allow or deny (default: LRA_NETWORK or allow)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=TACTIC_TIMEOUT_SECONDS,
        help="per-tactic timeout seconds (must exceed IndependentKernelVerifier 30s)",
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=None,
        help="write per-problem lake-native try receipts here",
    )
    parser.add_argument(
        "--skip-checkout",
        action="store_true",
        help="do not git checkout (synthetic or already-checked worktree)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_check or argv is None or argv == []:
        from jevops.outer import print_ok

        return print_ok(self_check(args.jsonl, receipts_dir=args.receipts_dir))

    if args.plan:
        _print_json(plan_try(args.jsonl))
        return 0

    if args.probe_toolchain:
        _print_json(probe_toolchain())
        return 0

    if args.try_name:
        if not args.name:
            parser.error("--try-name requires --name")
        try:
            timeout = lra_compile.require_lake_timeout(args.timeout)
        except lra_compile.CompileError as exc:
            from jevops.outer import failed_check

            _print_json(
                failed_check(
                    exc,
                    hammer_006_lra_ready=False,
                    on_30_sep_critical_path=False,
                    uses_snapshot_goal=False,
                )
            )
            return 1
        raw, digest, records = lra_splice.load_warmup_records(
            args.jsonl if args.jsonl is not None else WARMUP_JSONL
        )
        del raw, digest
        from jevops.outer import closed_fail, lookup_named

        match = lookup_named(records, args.name)
        if match is None:
            _print_json(
                closed_fail(
                    f"unknown warm-up problem: {args.name}",
                    hammer_006_lra_ready=False,
                    uses_snapshot_goal=False,
                )
            )
            return 1
        pin = pin_for_tag(match, STRATA_FIRST_TAG)
        receipt = try_tactics(
            match,
            pin,
            timeout=timeout,
            state_root=args.state_root,
            elan_home=args.elan_home,
            network=lra_bake.network_mode(args.network),
            skip_checkout=args.skip_checkout,
        )
        written: list[str] = []
        if args.receipts_dir is not None:
            written = write_receipts([receipt], args.receipts_dir)
        payload = receipt.to_dict()
        payload["receipts_written"] = written
        payload["summary"] = _receipt_summary(receipt)
        _print_json(payload)
        return 0 if receipt.ok else 1

    parser.error("choose --self-check, --plan, --probe-toolchain, or --try-name")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
