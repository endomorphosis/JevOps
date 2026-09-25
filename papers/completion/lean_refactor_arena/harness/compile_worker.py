#!/usr/bin/env python3
"""Multi-tag lake compile worker for Lean Refactor Arena.

Cached clone, checkout commit, tag-pinned ``lake env lean --json``. The
measurement command forces a finite ``maxHeartbeats`` even when a Putnam
header sets ``set_option maxHeartbeats 0``. Per-tag timeout is 10 min on
warm-up (20 min official), not the IndependentKernelVerifier 30 s default.
That verifier is not the lake oracle.

Start with one Strata module (CallElimCorrect.lean at v4.26.0). Expand
remaining tags after that file is green. Receipts record argv, exit,
stdout digest, axiom digest, wall-ms, cpu-ms, and header vs measurement
heartbeats. This worker does not claim Arena scores.
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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import bake_oleans as lra_bake  # noqa: E402
import splice as lra_splice  # noqa: E402

DATASETS_ROOT = _jevops_path.IPFS_DATASETS_ROOT

from lean_toolchain import (  # noqa: E402
    KERNEL_COMMAND_TEMPLATE,
    LeanToolchainMissing,
    LeanToolchainResolver,
    run_lean_process,
)

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
STRATA_SOURCE = lra_bake.STRATA_SOURCE
PUTNAM_SOURCE = lra_bake.PUTNAM_SOURCE
STRATA_FIRST_TAG = lra_bake.STRATA_FIRST_TAG
STRATA_FIRST_COMMIT = lra_bake.STRATA_FIRST_COMMIT
STRATA_URL = lra_bake.STRATA_URL
STRATA_FIRST_FILE = "Strata/Transform/CallElimCorrect.lean"
STRATA_EXPAND_FILE = "Strata/Languages/Core/StatementSemanticsProps.lean"
MEASUREMENT_MAX_HEARTBEATS = lra_bake.MEASUREMENT_MAX_HEARTBEATS
MEASUREMENT_ARGV_TEMPLATE = (
    "{lake} env {lean} -DmaxHeartbeats="
    f"{MEASUREMENT_MAX_HEARTBEATS} --json {{source_file}}"
)
LEAN_NUM_THREADS = 1
WARMUP_TAG_TIMEOUT_SECONDS = 600.0
OFFICIAL_TAG_TIMEOUT_SECONDS = 1200.0
INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS = 30.0
GIT_BIN = lra_bake.GIT_BIN
RECEIPT_SCHEMA = "lra-compile-receipt/v1"
PROCESS_SUPERVISOR_ENV = "IPFS_DATASETS_PROCESS_SUPERVISOR_DIR"

FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "fcntl",
        "IndependentKernelVerifier",
        "KernelVerifier",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "shutil",
    }
)
FORBIDDEN_ORACLE_NAMES = frozenset(
    {
        "IndependentKernelVerifier",
        "KernelVerifier",
        "verify_admitted_lean_proof",
        "verify_lean_proof_text",
    }
)
FORBIDDEN_CALLS = frozenset({"which", "find_executable", "LOCK_EX"})
FORBIDDEN_SCORE_NAMES = frozenset(
    {
        "arena_score",
        "arena_score_tokens",
        "arena_score_elab",
        "official_track2_score",
        "token_savings",
    }
)
_HEADER_HEARTBEATS = re.compile(r"set_option\s+maxHeartbeats\s+(\d+)")
_AXIOM_LINE = re.compile(
    r"^[^\s:]+\s*:\s*(?:\[(?P<bracket>[^\]]*)\]|(?P<bare>.+))\s*$"
)


class CompileError(RuntimeError):
    """Fail-closed lake compile-worker error."""


class CompileToolchainMissing(CompileError):
    """Tag-pinned elan lake/lean is not installed. Not a PATH fallback."""


class CloneMissing(CompileError):
    """Cached clone is absent while network is denied."""


class LakeTimeoutTooSmall(CompileError):
    """Lake timeout must exceed the IndependentKernelVerifier 30 s default."""


from jevops.lean import CompilePlan as _KernelCompilePlan
from jevops.lean import CompileReceipt
from jevops.lean import VersionPin


@dataclass
class CompilePlan(_KernelCompilePlan):
    first_source: str = STRATA_SOURCE

    @property
    def first_record(self) -> dict[str, Any]:
        return super().first_record(error_cls=CompileError, miss="warmup JSONL has no Strata record")

    def to_dict(self) -> dict[str, Any]:
        first = self.first_record
        first_pins = iter_version_pins(first.get("version_info"))
        return {
            "arena_score": None,
            "expand_after_first_green": True,
            "first_commit": first_pins[0].git_commit if first_pins else "",
            "first_file": str(first.get("file_path") or ""),
            "first_is_strata": first.get("source") == STRATA_SOURCE,
            "first_is_strata_v4_26": (
                first.get("source") == STRATA_SOURCE
                and first_pins
                and first_pins[0].lean_tag == STRATA_FIRST_TAG
                and first_pins[0].git_commit == STRATA_FIRST_COMMIT
                and str(first.get("file_path") or "") == STRATA_FIRST_FILE
                and str(first.get("url") or "") == STRATA_URL
            ),
            "first_name": str(first.get("name") or ""),
            "first_tag": first_pins[0].lean_tag if first_pins else "",
            "first_url": str(first.get("url") or ""),
            "frozen_warmup_sha256": self.frozen_warmup_sha256,
            "independent_kernel_verifier_default_timeout_seconds": (
                INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS
            ),
            "independent_kernel_verifier_is_lake_oracle": False,
            "jsonl_bytes": self.jsonl_bytes,
            "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
            "measurement_argv_template": MEASUREMENT_ARGV_TEMPLATE,
            "measurement_maxHeartbeats": MEASUREMENT_MAX_HEARTBEATS,
            "n_records": self.n_records,
            "newest_tag_first": True,
            "official_timeout_seconds": OFFICIAL_TAG_TIMEOUT_SECONDS,
            "score": None,
            "warmup_timeout_seconds": WARMUP_TAG_TIMEOUT_SECONDS,
        }


def sha256_bytes(data: bytes) -> str:
    from jevops.outer import digest_hex

    return digest_hex(data)


def sha256_file(path: Path) -> str:
    from jevops.outer import digest_file

    return digest_file(path)


def sha256_text(text: str) -> str:
    from jevops.outer import digest_text

    return digest_text(text)


def require_lake_timeout(timeout: float) -> float:
    """Reject the IndependentKernelVerifier 30 s default as a lake timeout."""

    from jevops.lean import require_lake_timeout as _fn

    return _fn(
        timeout,
        floor=INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS,
        error_cls=CompileError,
        too_small_cls=LakeTimeoutTooSmall,
    )


def header_max_heartbeats(header: str) -> Optional[int]:
    from jevops.lean import header_max_heartbeats as _fn

    return _fn(header)


def iter_version_pins(version_info: Any) -> list[VersionPin]:
    pins = [
        VersionPin(lean_tag=item.lean_tag, git_commit=item.git_commit)
        for item in lra_bake.iter_version_pins(version_info)
    ]
    return sorted(pins, key=lambda pin: _tag_sort_key(pin.lean_tag), reverse=True)


def _tag_sort_key(tag: str) -> tuple[tuple[int, int, int], str]:
    from jevops.outer import version_sort_key

    return version_sort_key(lra_bake.normalize_lean_tag(tag))


def measurement_argv(
    lake_path: str,
    lean_path: str,
    source_file: str,
    *,
    max_heartbeats: int = MEASUREMENT_MAX_HEARTBEATS,
) -> list[str]:
    from jevops.lean import measurement_argv as _fn

    return _fn(
        lake_path,
        lean_path,
        source_file,
        max_heartbeats=max_heartbeats,
        refuse=lra_bake.FORBIDDEN_PUTNAM_BASENAME,
        error_cls=CompileError,
    )


def axiom_digest(axiom_names: Sequence[str]) -> str:
    from jevops.lean import axiom_digest as _fn

    return _fn(axiom_names)


def parse_axioms(stdout: str, stderr: str = "") -> tuple[list[str], bool]:
    """Extract axiom names and sorryAx from lake/lean stdout."""

    from jevops.lean import parse_axioms as _fn

    return _fn(stdout, stderr)


def clone_dir(url: str, state_root: Optional[Path] = None) -> Path:
    from jevops.outer import url_clone_dir

    root = Path(state_root) if state_root is not None else lra_bake.default_state_root()
    return url_clone_dir(root, url)


def require_clone(
    url: str,
    *,
    network: str,
    state_root: Optional[Path] = None,
) -> Path:
    from jevops.outer import require_marked_dir

    return require_marked_dir(
        clone_dir(url, state_root),
        (".git", "lakefile.lean"),
        error_cls=CloneMissing if network == "deny" else None,
        miss=(
            f"cached clone missing for {url} under network=deny; never falling "
            "back to PATH lean or a guessed GitHub URL"
        ),
    )


def checkout_commit(clone: Path, commit: str) -> dict[str, Any]:
    from jevops.outer import git_checkout

    return git_checkout(
        clone,
        commit,
        git_bin=GIT_BIN,
        error_cls=CompileError,
        miss_cls=CompileToolchainMissing,
    )


def project_dir_for_record(
    record: Mapping[str, Any],
    pin: VersionPin,
    *,
    state_root: Optional[Path] = None,
) -> Path:
    from jevops.lean import project_dir_for_record as _fn

    def _putnam_dir(_rec: Mapping[str, Any], p: VersionPin, root: Optional[Path]) -> Path:
        return lra_bake.putnam_project_dir(
            lra_bake.BakeJob(
                kind="putnam",
                source=PUTNAM_SOURCE,
                lean_tag=p.lean_tag,
                git_commit=p.git_commit,
                url="",
                cache_key=f"putnam/{p.lean_tag}",
                phase=2,
                record_names=(str(_rec.get("name") or ""),),
                file_paths=(lra_bake.PUTNAM_CANDIDATE_RELPATH,),
                module=lra_bake.PUTNAM_MODULE,
                lakefile_required=True,
            ),
            root,
        )

    return _fn(
        record,
        pin,
        putnam_source=PUTNAM_SOURCE,
        putnam_dir_fn=_putnam_dir,
        clone_dir_fn=lambda url: clone_dir(url, state_root),
        error_cls=CompileError,
        state_root=state_root,
    )


def source_relpath(record: Mapping[str, Any]) -> str:
    from jevops.lean import source_relpath as _fn

    return _fn(
        record,
        putnam_source=PUTNAM_SOURCE,
        putnam_relpath=lra_bake.PUTNAM_CANDIDATE_RELPATH,
        refuse=lra_bake.FORBIDDEN_PUTNAM_BASENAME,
        error_cls=CompileError,
    )


def write_record_source(record: Mapping[str, Any], dest: Path) -> Path:
    from jevops.lean import write_lake_source

    split = lra_splice.split_statement_body(record)
    return write_lake_source(
        dest,
        header=split.header,
        statement=split.statement,
        tactic_block=lra_splice.tactic_block_from_body(split.body_suffix),
        refuse=lra_bake.FORBIDDEN_PUTNAM_BASENAME,
        error_cls=CompileError,
    )


def resolve_pin(
    pin: VersionPin,
    *,
    elan_home: Optional[Path] = None,
    require_installed: bool = True,
):
    resolver = LeanToolchainResolver(elan_home)
    try:
        return resolver.resolve_tag(
            pin.lean_tag, git_commit=pin.git_commit, require_installed=require_installed
        )
    except LeanToolchainMissing as exc:
        raise CompileToolchainMissing(str(exc)) from exc


def compile_tag(
    record: Mapping[str, Any],
    pin: VersionPin,
    *,
    timeout: float = WARMUP_TAG_TIMEOUT_SECONDS,
    state_root: Optional[Path] = None,
    elan_home: Optional[Path] = None,
    network: str = "allow",
    require_oleans: bool = False,
    hardware_class: str = "unscored-dev",
    skip_checkout: bool = False,
) -> CompileReceipt:
    """Run tag-pinned ``lake env lean`` with finite measurement maxHeartbeats."""

    timeout = require_lake_timeout(timeout)
    header_cap = header_max_heartbeats(str(record.get("header") or ""))
    relpath = source_relpath(record)
    from jevops.lean import init_compile_receipt

    receipt = init_compile_receipt(
        record,
        pin,
        timeout=timeout,
        relpath=relpath,
        schema=RECEIPT_SCHEMA,
        max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        header_cap=header_cap,
        lean_num_threads=LEAN_NUM_THREADS,
        kernel_command_template=KERNEL_COMMAND_TEMPLATE,
        hardware_class=hardware_class,
    )
    from jevops.lean import (
        close_failed_receipt,
        prepare_lake_paths,
        run_tag_compile,
        stamp_measured_receipt,
        stamp_tag_compile,
        write_candidate_if_needed,
    )
    from jevops.outer import under_or_tmp

    def _stamp(receipt: CompileReceipt, *, toolchain: Any, cwd: Path, source_file: str) -> CompileReceipt:
        argv = measurement_argv(
            toolchain.lake_path,
            toolchain.lean_path,
            source_file,
            max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        )
        supervisor_dir = under_or_tmp(
            state_root, "process-supervisor", tmp_name="lra-014-process-supervisor"
        )
        stamp_tag_compile(
            receipt,
            cwd=cwd,
            argv=argv,
            toolchain=toolchain,
            timeout=timeout,
            stamp_fn=stamp_measured_receipt,
            run_fn=lambda argv, env: run_lean_process(
                argv,
                timeout=timeout,
                cwd=str(cwd),
                env=env,
            ),
            supervisor_dir=supervisor_dir,
            process_env_key=PROCESS_SUPERVISOR_ENV,
            threads=LEAN_NUM_THREADS,
            max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
            ikv_floor=INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS,
        )
        return receipt

    return run_tag_compile(
        receipt,
        resolve_fn=lambda: resolve_pin(pin, elan_home=elan_home, require_installed=True),
        prepare_fn=lambda: prepare_lake_paths(
            record,
            pin,
            putnam_source=PUTNAM_SOURCE,
            putnam_relpath=lra_bake.PUTNAM_CANDIDATE_RELPATH,
            source_relpath_fn=source_relpath,
            putnam_dir_fn=lambda rec, p, root: project_dir_for_record(rec, p, state_root=root),
            materialize_fn=lambda p, project: lra_bake.materialize_putnam_project(
                p.lean_tag, project, jsonl_version_pin=p.git_commit
            ),
            require_clone_fn=lambda url, net, root: require_clone(
                url, network=net, state_root=root
            ),
            checkout_fn=checkout_commit,
            skip_checkout=skip_checkout,
            network=network,
            state_root=state_root,
        ),
        write_fn=lambda dest: write_candidate_if_needed(
            record,
            dest,
            putnam_source=PUTNAM_SOURCE,
            write_fn=write_record_source,
        ),
        bake_fn=(
            (lambda: lra_bake.require_cache(_bake_job_for_record(record, pin), network=network, state_root=state_root))
            if require_oleans
            else None
        ),
        stamp_fn=_stamp,
        close_fn=lambda rec, exc: close_failed_receipt(
            rec, exc, digest_fn=sha256_text, axiom_digest_fn=axiom_digest
        ),
        error_types=(CompileError, LeanToolchainMissing, lra_bake.BakeError),
    )


def _bake_job_for_record(record: Mapping[str, Any], pin: VersionPin) -> lra_bake.BakeJob:
    from jevops.lean import bake_job_for_record as _fn

    return _fn(
        record,
        pin,
        putnam_source=PUTNAM_SOURCE,
        strata_source=STRATA_SOURCE,
        strata_first_tag=STRATA_FIRST_TAG,
        putnam_relpath=lra_bake.PUTNAM_CANDIDATE_RELPATH,
        putnam_module=lra_bake.PUTNAM_MODULE,
        url_key_fn=lra_bake._url_cache_key,
    )


def compile_record(
    record: Mapping[str, Any],
    *,
    timeout: float = WARMUP_TAG_TIMEOUT_SECONDS,
    state_root: Optional[Path] = None,
    elan_home: Optional[Path] = None,
    network: str = "allow",
    require_oleans: bool = False,
    hardware_class: str = "unscored-dev",
    skip_checkout: bool = False,
    abort_on_first_failure: bool = True,
) -> list[CompileReceipt]:
    from jevops.outer import collect_until

    pins = iter_version_pins(record.get("version_info"))
    return collect_until(
        pins,
        lambda pin: compile_tag(
            record,
            pin,
            timeout=timeout,
            state_root=state_root,
            elan_home=elan_home,
            network=network,
            require_oleans=require_oleans,
            hardware_class=hardware_class,
            skip_checkout=skip_checkout,
        ),
        abort_fn=(lambda receipt: not receipt.ok) if abort_on_first_failure else None,
        remaining_fn=lambda rest: [item.lean_tag for item in rest],
        remaining_attr="aborted_remaining_tags" if abort_on_first_failure else "",
    )


def write_receipts(receipts: Sequence[CompileReceipt], dest_dir: Path) -> list[str]:
    from jevops.outer import write_named_jsons

    return write_named_jsons(
        dest_dir,
        receipts,
        name_fn=lambda item: item.name,
        tag_fn=lambda item: item.lean_tag,
        payload_fn=lambda item: item.to_dict(),
    )


def plan_compile(path: Optional[Path] = None) -> CompilePlan:
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    from jevops.lean import plan_from_records

    return plan_from_records(
        records,
        digest,
        len(raw),
        first_source=STRATA_SOURCE,
        cls=CompilePlan,
    )


def first_strata_record(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    from jevops.outer import first_where

    return first_where(
        records,
        lambda record: record.get("source") == STRATA_SOURCE,
        error_cls=CompileError,
        miss="no Strata record in warmup JSONL",
    )


def expand_records(
    records: Sequence[Mapping[str, Any]],
    *,
    after_name: str,
) -> list[Mapping[str, Any]]:
    """Records whose tags are compiled after ``after_name`` is green."""

    from jevops.outer import after_named

    return after_named(
        records,
        after_name,
        pred=lambda record: record.get("source") == STRATA_SOURCE,
    )


def probe_toolchain(tags: Iterable[str] | None = None) -> dict[str, Any]:
    if tags is None:
        tags = (STRATA_FIRST_TAG, "v4.27.0", "v4.29.1")
    from jevops.lean import probe_pins
    from jevops.outer import env_str

    resolver = LeanToolchainResolver()
    return probe_pins(
        list(tags),
        resolve_fn=lambda tag: resolver.resolve_tag(tag, require_installed=False).to_dict(),
        extra={
            "default_elan_home": str(lra_bake.default_elan_home()),
            "elan_home_env": env_str("ELAN_HOME"),
            "independent_kernel_verifier_is_lake_oracle": False,
            "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
            "lake": False,
            "measurement_argv_template": MEASUREMENT_ARGV_TEMPLATE,
            "path": env_str("PATH"),
            "run_lean_process": run_lean_process.__name__,
            "validation_home": str(Path.home()),
            "warmup_timeout_seconds": WARMUP_TAG_TIMEOUT_SECONDS,
        },
    )


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _call_name(node: ast.AST) -> str:
    from jevops.repair import call_short_name

    return call_short_name(node)


def _oracle_name_uses(tree: ast.AST) -> set[str]:
    from jevops.repair import ast_name_hits

    return ast_name_hits(tree, FORBIDDEN_ORACLE_NAMES)


def _timeout_kwarg_values(tree: ast.AST) -> list[float]:
    from jevops.repair import call_kwarg_numbers

    return call_kwarg_numbers(tree, ("timeout", "timeout_seconds"))


def audit_source(source: Optional[str] = None) -> dict[str, Any]:
    from jevops.outer import source_text
    from jevops.repair import ast_name_hits, audit_source as _audit, call_kwarg_numbers, has_constant

    text = source_text(source, path=__file__)
    out = _audit(
        text,
        forbidden_imports=FORBIDDEN_IMPORT_NAMES,
        forbidden_calls=FORBIDDEN_CALLS,
        forbidden_scores=FORBIDDEN_SCORE_NAMES,
    )
    tree = ast.parse(text)
    oracle_uses = ast_name_hits(tree, FORBIDDEN_ORACLE_NAMES)
    timeout_literals = call_kwarg_numbers(tree, ("timeout", "timeout_seconds"))
    calls = set(out["call_names"])
    score_assignments = list(out["score_keys"])
    uses_run_lean_process = "run_lean_process" in calls
    uses_measurement_argv = "measurement_argv" in calls
    has_ikv_timeout_constant = has_constant(text, INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS)
    lake_timeout_literals_ok = all(
        value > INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS
        for value in timeout_literals
        if value == INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS or value >= 1.0
    ) and INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS not in timeout_literals
    return {
        "imported_names": out["imported_names"],
        "forbidden_imports": out["forbidden_imports"],
        "forbidden_calls": out["forbidden_calls"],
        "forbidden_oracle_uses": sorted(oracle_uses),
        "score_assignments": score_assignments,
        "timeout_kwarg_literals": timeout_literals,
        "uses_run_lean_process": uses_run_lean_process,
        "uses_measurement_argv": uses_measurement_argv,
        "has_ikv_timeout_constant": has_ikv_timeout_constant,
        "lake_timeout_literals_ok": lake_timeout_literals_ok,
        "independent_kernel_verifier_is_lake_oracle": False,
        "ok": (
            not out["forbidden_imports"]
            and not out["forbidden_calls"]
            and not oracle_uses
            and not score_assignments
            and uses_run_lean_process
            and uses_measurement_argv
            and lake_timeout_literals_ok
        ),
    }


_FAKE_LAKE = """#!/usr/bin/python3.12
import os
import sys

args = sys.argv[1:]
if not args or args[0] != "env" or len(args) < 2:
    sys.stderr.write("lra-fake-lake: expected 'env <lean> ...'\\n")
    sys.exit(2)
os.execv(args[1], args[1:])
"""

_FAKE_LEAN = """#!/usr/bin/python3.12
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


def plant_synthetic_strata_clone(clone: Path) -> Path:
    from jevops.lean import plant_synthetic_clone

    return plant_synthetic_clone(
        clone,
        {
            "lakefile.lean": (
                "import Lake\n"
                "open Lake DSL\n"
                "\n"
                "package «strata» where\n"
                f'  moreLeanArgs := #["-DmaxHeartbeats={MEASUREMENT_MAX_HEARTBEATS}"]\n'
                "\n"
                "lean_lib «Strata»\n"
            ),
            "lean-toolchain": f"leanprover/lean4:{STRATA_FIRST_TAG}\n",
        },
    )


def _receipt_summary(receipt: CompileReceipt) -> dict[str, Any]:
    from jevops.lean import compile_receipt_summary

    return compile_receipt_summary(
        receipt,
        max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        ikv_floor=INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS,
    )


def _exec_scratch_parent() -> Path:
    """Return a directory that can exec shebang scripts. ``/tmp`` is often noexec."""

    from jevops.outer import exec_capable_dir, state_home_candidates

    return exec_capable_dir(
        state_home_candidates(),
        probe_name=".lra-014-exec-probe",
        error_cls=CompileError,
        miss=(
            "no executable filesystem for tag-pinned synthetic lake/lean "
            "(refusing /tmp noexec and PATH lake)"
        ),
    )


def _synthetic_compile(
    plan: CompilePlan,
    *,
    persist_receipts: Optional[Path] = None,
) -> dict[str, Any]:
    from jevops.outer import temp_dir

    with temp_dir(prefix="lra-014-compile-", parent=_exec_scratch_parent()) as tmp:
        root = Path(tmp)
        elan_home = root / "elan"
        state_root = root / "state"
        receipts_dir = root / "receipts"
        for tag in ("v4.25.0", "v4.26.0", "v4.27.0", "v4.29.1"):
            plant_fake_toolchain(elan_home, tag)
        clone = plant_synthetic_strata_clone(clone_dir(STRATA_URL, state_root))
        first = plan.first_record
        write_record_source(first, clone / STRATA_FIRST_FILE)
        expand = expand_records(plan.records, after_name=str(first.get("name") or ""))
        if expand:
            write_record_source(expand[-1], clone / STRATA_EXPAND_FILE)
        first_job = _bake_job_for_record(first, iter_version_pins(first.get("version_info"))[0])
        lra_bake.plant_synthetic_cache(first_job, state_root)
        timeout_30_rejected = False
        try:
            require_lake_timeout(INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS)
        except LakeTimeoutTooSmall:
            timeout_30_rejected = True
        first_receipts = compile_record(
            first,
            timeout=WARMUP_TAG_TIMEOUT_SECONDS,
            state_root=state_root,
            elan_home=elan_home,
            network="deny",
            require_oleans=False,
            hardware_class="synthetic",
            skip_checkout=True,
        )
        first_green = bool(first_receipts) and all(item.ok for item in first_receipts)
        expand_receipts: list[CompileReceipt] = []
        if first_green:
            for record in expand:
                if str(record.get("file_path") or "") != STRATA_EXPAND_FILE:
                    continue
                expand_receipts.extend(
                    compile_record(
                        record,
                        timeout=WARMUP_TAG_TIMEOUT_SECONDS,
                        state_root=state_root,
                        elan_home=elan_home,
                        network="deny",
                        hardware_class="synthetic",
                        skip_checkout=True,
                    )
                )
                break
        putnam = next(
            record for record in plan.records if record.get("source") == PUTNAM_SOURCE
        )
        putnam_pins = iter_version_pins(putnam.get("version_info"))
        putnam_pin = next(pin for pin in putnam_pins if pin.lean_tag == STRATA_FIRST_TAG)
        putnam_receipt = compile_tag(
            putnam,
            putnam_pin,
            timeout=WARMUP_TAG_TIMEOUT_SECONDS,
            state_root=state_root,
            elan_home=elan_home,
            network="allow",
            hardware_class="synthetic",
            skip_checkout=True,
        )
        all_receipts = [*first_receipts, *expand_receipts, putnam_receipt]
        written = write_receipts(all_receipts, receipts_dir)
        persisted: list[str] = []
        if persist_receipts is not None:
            persisted = write_receipts(all_receipts, Path(persist_receipts))
        missing_clone_closed = False
        try:
            require_clone(
                "https://github.com/example/missing-lra-014",
                network="deny",
                state_root=state_root,
            )
        except CloneMissing:
            missing_clone_closed = True
        from jevops.lean import pack_synthetic_compile

        return pack_synthetic_compile(
            elan_home=elan_home,
            expand_receipts=expand_receipts,
            first_receipts=first_receipts,
            putnam_receipt=putnam_receipt,
            written=written,
            persisted=persisted,
            receipts_dir=receipts_dir,
            first_file=STRATA_FIRST_FILE,
            first_name=str(first.get("name") or ""),
            first_green=first_green,
            missing_clone_closed=missing_clone_closed,
            timeout_30_rejected=timeout_30_rejected,
            timeout_is_warmup=all(
                item.timeout_seconds == WARMUP_TAG_TIMEOUT_SECONDS
                for item in [*first_receipts, *expand_receipts, putnam_receipt]
            ),
            summary_fn=_receipt_summary,
            tag_sort_fn=_tag_sort_key,
            max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        )


def self_check(
    path: Optional[Path] = None,
    *,
    receipts_dir: Optional[Path] = None,
) -> dict[str, Any]:
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    plan = plan_compile(jsonl)
    audit = audit_source()
    synthetic = _synthetic_compile(plan, persist_receipts=receipts_dir)
    toolchain = probe_toolchain()
    first = plan.first_record
    first_pins = iter_version_pins(first.get("version_info"))
    putnam_headers = []
    for record in plan.records:
        if record.get("source") != PUTNAM_SOURCE:
            continue
        putnam_headers.append(header_max_heartbeats(str(record.get("header") or "")))
    report: dict[str, Any] = {
        "ok": False,
        "arena_score": None,
        "score": None,
        "compiled": bool(synthetic["first_strata_compiled"]),
        "lake": True,
        "lake_oracle": True,
        "llama_server_started": False,
        "independent_kernel_verifier_used": False,
        "independent_kernel_verifier_is_lake_oracle": False,
        "independent_kernel_verifier_default_timeout_seconds": (
            INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS
        ),
        "warmup_timeout_seconds": WARMUP_TAG_TIMEOUT_SECONDS,
        "official_timeout_seconds": OFFICIAL_TAG_TIMEOUT_SECONDS,
        "measurement_maxHeartbeats": MEASUREMENT_MAX_HEARTBEATS,
        "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
        "measurement_argv_template": MEASUREMENT_ARGV_TEMPLATE,
        "run_lean_process": run_lean_process.__name__,
        "frozen_warmup_sha256": plan.frozen_warmup_sha256,
        "jsonl_bytes": plan.jsonl_bytes,
        "jsonl_unchanged": plan.frozen_warmup_sha256 == FROZEN_WARMUP_SHA256,
        "n_records": plan.n_records,
        "first_name": str(first.get("name") or ""),
        "first_file": str(first.get("file_path") or ""),
        "first_is_strata_v4_26": (
            first.get("source") == STRATA_SOURCE
            and first_pins
            and first_pins[0].lean_tag == STRATA_FIRST_TAG
            and first_pins[0].git_commit == STRATA_FIRST_COMMIT
            and str(first.get("file_path") or "") == STRATA_FIRST_FILE
        ),
        "first_strata_compiled_via_lake_env_lean": bool(
            synthetic["first_strata_compiled"] and synthetic["first_via_lake_env_lean"]
        ),
        "per_tag_timeout_written": bool(synthetic["timeout_is_warmup_600s"]),
        "axiom_digest_receipts_written": bool(synthetic["n_receipts_written"]),
        "putnam_headers_maxHeartbeats": putnam_headers,
        "putnam_headers_are_zero": putnam_headers == [0, 0, 0],
        "timeout_30s_rejected": bool(synthetic["timeout_30s_rejected"]),
        "audit": audit,
        "synthetic": synthetic,
        "toolchain": toolchain,
        "plan": plan.to_dict(),
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
        "protocol": "LRA/v1",
        "live_elan_installed": bool(toolchain["installed_tags"]),
        "capability_gap": toolchain["capability_gap"],
    }
    first_receipts = synthetic["first_receipts"]
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and report["first_is_strata_v4_26"]
        and report["first_strata_compiled_via_lake_env_lean"]
        and report["per_tag_timeout_written"]
        and report["axiom_digest_receipts_written"]
        and report["putnam_headers_are_zero"]
        and synthetic["putnam_overrides_zero_header"]
        and synthetic["timeout_30s_rejected"]
        and synthetic["missing_clone_fails_closed_under_network_deny"]
        and synthetic["expand_ok"]
        and synthetic["expand_tags_newest_first"]
        and all(item["axiom_digest_hex64"] for item in first_receipts)
        and all(item["stdout_nonempty"] and item["printed_axioms"] for item in first_receipts)
        and all(not item["error"] for item in first_receipts)
        and all(item["timeout_exceeds_ikv_30s"] for item in first_receipts)
        and all(not item["independent_kernel_verifier_used"] for item in first_receipts)
        and audit["ok"]
        and report["independent_kernel_verifier_used"] is False
        and report["independent_kernel_verifier_is_lake_oracle"] is False
        and report["arena_score"] is None
        and report["score"] is None
        and report["llama_server_started"] is False
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
        help="compile one Strata file via synthetic tag-pinned lake env lean; write receipts",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print the compile plan; first target is Strata v4.26 CallElimCorrect.lean",
    )
    parser.add_argument(
        "--probe-toolchain",
        action="store_true",
        help="record tag-pinned elan paths; do not treat missing lake as PATH usable",
    )
    parser.add_argument(
        "--compile-first",
        action="store_true",
        help="compile the first Strata module (live elan, fail closed if missing)",
    )
    parser.add_argument(
        "--expand-tags",
        action="store_true",
        help="after the first Strata file is green, compile remaining Strata tags",
    )
    parser.add_argument("--name", default="", help="JSONL problem name (default: first Strata)")
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL path")
    parser.add_argument("--state-root", type=Path, default=None, help="clone/olean/putnam state root")
    parser.add_argument("--elan-home", type=Path, default=None, help="tag-pinned elan home")
    parser.add_argument("--network", default=None, help="allow or deny (default: LRA_NETWORK or allow)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=WARMUP_TAG_TIMEOUT_SECONDS,
        help="per-tag timeout seconds (must exceed IndependentKernelVerifier 30s)",
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=None,
        help="write per-tag timeout and axiom-digest receipts here",
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
        _print_json(plan_compile(args.jsonl).to_dict())
        return 0

    if args.probe_toolchain:
        _print_json(probe_toolchain())
        return 0

    if args.compile_first or args.expand_tags or args.name:
        try:
            timeout = require_lake_timeout(args.timeout)
        except CompileError as exc:
            from jevops.outer import failed_check

            _print_json(failed_check(exc, independent_kernel_verifier_is_lake_oracle=False))
            return 1
        plan = plan_compile(args.jsonl)
        network = lra_bake.network_mode(args.network)
        records: list[Mapping[str, Any]] = []
        if args.name:
            from jevops.outer import closed_fail, lookup_named

            match = lookup_named(plan.records, args.name)
            if match is None:
                _print_json(closed_fail(f"unknown warm-up problem: {args.name}"))
                return 1
            records = [match]
        else:
            first = plan.first_record
            records = [first]
            if args.expand_tags:
                records.extend(expand_records(plan.records, after_name=str(first.get("name") or "")))
        all_receipts: list[CompileReceipt] = []
        first_green = False
        for index, record in enumerate(records):
            if index > 0 and args.expand_tags and not first_green:
                break
            batch = compile_record(
                record,
                timeout=timeout,
                state_root=args.state_root,
                elan_home=args.elan_home,
                network=network,
                skip_checkout=args.skip_checkout,
            )
            all_receipts.extend(batch)
            if index == 0:
                first_green = bool(batch) and all(item.ok for item in batch)
        written: list[str] = []
        if args.receipts_dir is not None:
            written = write_receipts(all_receipts, args.receipts_dir)
        payload = {
            "ok": bool(all_receipts) and all(item.ok for item in all_receipts),
            "arena_score": None,
            "score": None,
            "compiled": bool(all_receipts) and all(item.ok for item in all_receipts),
            "expand_tags": bool(args.expand_tags),
            "first_green": first_green,
            "independent_kernel_verifier_is_lake_oracle": False,
            "n_receipts": len(all_receipts),
            "receipts": [_receipt_summary(item) for item in all_receipts],
            "receipts_written": written,
        }
        _print_json(payload)
        return 0 if payload["ok"] else 1

    parser.error("choose --self-check, --plan, --probe-toolchain, or --compile-first")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
