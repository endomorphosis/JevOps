#!/usr/bin/env python3
"""Bake lake .olean caches and per-tag Putnam Mathlib+Aesop lake projects.

First ``lake build`` is hours. Record **Strata v4.26.0** first, then the other
``(clone, commit, tag)`` units, then one Putnam Mathlib+Aesop lake project per
JSONL Putnam tag. Missing oleans under ``network=deny`` fail closed. Putnam is
never ``Tmp.lean`` and never a guessed PutnamBench GitHub URL.

This module plans, materializes lakefiles, and checks the olean cache. A live
``lake build`` runs only when a tag-pinned elan ``lake`` is installed and
network is allowed. Self-check does not compile, does not start llama-server,
and does not claim Arena scores.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"
PUTNAM_README = HERE / "putnam_lake" / "README.md"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import splice as lra_splice  # noqa: E402

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
STRATA_SOURCE = "strata"
PUTNAM_SOURCE = "putnambench"
STRATA_FIRST_TAG = "v4.26.0"
STRATA_FIRST_COMMIT = "451e5f047bafa010d178856db76c00029bfa4d7f"
STRATA_URL = "https://github.com/strata-org/Strata"
SOURCE_ORDER = ("strata", "physlib", "cslib", "arklib", "putnambench")
PUTNAM_TAGS: tuple[str, ...] = ("v4.25.0", "v4.26.0", "v4.27.0")
MATHLIB_GIT = "https://github.com/leanprover-community/mathlib4.git"
AESOP_GIT = "https://github.com/leanprover-community/aesop.git"
PUTNAM_PACKAGE = "putnam_lake"
PUTNAM_LIB = "Putnam"
PUTNAM_MODULE = "Putnam.Candidate"
PUTNAM_CANDIDATE_RELPATH = "Putnam/Candidate.lean"
PUTNAM_ROOT_RELPATH = "Putnam.lean"
FORBIDDEN_PUTNAM_BASENAME = "Tmp.lean"
MEASUREMENT_MAX_HEARTBEATS = 400000
ELAN_TOOLCHAIN_DIRNAME_PREFIX = "leanprover--lean4---"
KERNEL_COMMAND_TEMPLATE = "{lake} env {lean} --json {source_file}"
BAKE_ARGV_TEMPLATE = "{lake} build"
DEFAULT_LAKE_TIMEOUT_SECONDS = 28800
NETWORK_DENY_VALUES = frozenset({"deny", "offline", "none", "no", "0", "false", "off"})
STATE_RELATIVE = Path("ipfs_accelerate_py") / "vericodegen-2026" / "lean_refactor_arena"
GIT_BIN = Path("/usr/bin/git")

FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "fcntl",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "shutil",
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
FORBIDDEN_PUTNAM_URL_NEEDLES = (
    "github.com/trishullab/PutnamBench",
    "github.com/trishullab/putnambench",
    "github.com/openai/putnam-bench",
)


class BakeError(RuntimeError):
    """Fail-closed olean-bake or Putnam lake-project error."""


class OleanCacheMissing(BakeError):
    """Required .olean cache is absent while network is denied."""


class BakeToolchainMissing(BakeError):
    """Tag-pinned elan lake/lean is not installed. Not a PATH fallback."""


from jevops.lean import BakeJob
from jevops.lean import BakePlan as _KernelBakePlan
from jevops.lean import PutnamPin
from jevops.lean import VersionPin


@dataclass
class BakePlan(_KernelBakePlan):
    frozen_warmup_sha256: str = FROZEN_WARMUP_SHA256

    @property
    def first_job(self) -> BakeJob:
        return super().first_job(error_cls=BakeError)

    def to_dict(self) -> dict[str, Any]:
        first = self.first_job
        return {
            "arena_score": None,
            "bake_argv_template": BAKE_ARGV_TEMPLATE,
            "first_is_strata_v4_26": (
                first.kind == "repo"
                and first.source == STRATA_SOURCE
                and first.lean_tag == STRATA_FIRST_TAG
                and first.git_commit == STRATA_FIRST_COMMIT
            ),
            "first_job": first.to_dict(),
            "frozen_warmup_sha256": self.frozen_warmup_sha256,
            "jsonl_bytes": self.jsonl_bytes,
            "jobs": [job.to_dict() for job in self.jobs],
            "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
            "measurement_maxHeartbeats": MEASUREMENT_MAX_HEARTBEATS,
            "n_jobs": len(self.jobs),
            "n_putnam_jobs": sum(1 for job in self.jobs if job.kind == "putnam"),
            "n_records": self.n_records,
            "n_repo_jobs": sum(1 for job in self.jobs if job.kind == "repo"),
            "putnam_module": PUTNAM_MODULE,
            "putnam_not_tmp_lean": True,
            "putnam_tags": list(PUTNAM_TAGS),
            "score": None,
            "strata_first_tag": STRATA_FIRST_TAG,
        }


def sha256_bytes(data: bytes) -> str:
    from jevops.outer import digest_hex

    return digest_hex(data)


def sha256_file(path: Path) -> str:
    from jevops.outer import digest_file

    return digest_file(path)


def default_elan_home() -> Path:
    from jevops.outer import first_env_path

    return first_env_path("ELAN_HOME", default=Path.home() / ".elan")


def default_state_root() -> Path:
    from jevops.outer import state_root_from_env

    return state_root_from_env(override_key="LRA_STATE_ROOT", relative=STATE_RELATIVE)


def network_mode(value: Optional[str] = None) -> str:
    from jevops.outer import allow_or_deny

    return allow_or_deny(
        value,
        deny=NETWORK_DENY_VALUES,
        default="allow",
        env_keys=("LRA_NETWORK", "IPFS_ACCELERATE_LRA_NETWORK"),
    )


def normalize_lean_tag(value: str) -> str:
    from jevops.outer import normalize_tag

    return normalize_tag(
        value,
        prefix=ELAN_TOOLCHAIN_DIRNAME_PREFIX,
        error_cls=BakeError,
        empty="lean tag must be a nonempty string",
    )


def elan_toolchain_dirname(lean_tag: str) -> str:
    return f"{ELAN_TOOLCHAIN_DIRNAME_PREFIX}{normalize_lean_tag(lean_tag)}"


def tag_pinned_paths(lean_tag: str, *, elan_home: Optional[Path] = None) -> dict[str, Any]:
    """Return elan ``lean``/``lake`` paths. Never searches PATH."""

    from jevops.outer import pinned_bin_paths

    home = Path(elan_home) if elan_home is not None else default_elan_home()
    tag = normalize_lean_tag(lean_tag)
    return pinned_bin_paths(
        home,
        elan_toolchain_dirname(tag),
        ("lean", "lake"),
        extra={"lean_tag": tag},
    )


def _is_executable(path: Path) -> bool:
    from jevops.outer import is_executable

    return is_executable(path)


def iter_version_pins(version_info: Any) -> list[VersionPin]:
    from jevops.outer import iter_tag_commit_pins

    return iter_tag_commit_pins(
        version_info,
        pin_fn=lambda tag, commit: VersionPin(lean_tag=tag, git_commit=commit),
        normalize_fn=normalize_lean_tag,
        error_cls=BakeError,
        not_list="version_info must be a list of {lean_tag: git_commit} maps",
        empty_tag="version_info[{index}] has an empty lean tag",
        bad_commit="version_info[{index}] git commit must be a string, not {type}",
        not_map="version_info[{index}] is not a {{lean_tag: git_commit}} map",
        empty="version_info is empty",
    )


def _url_cache_key(url: str) -> str:
    from jevops.outer import url_cache_key

    return url_cache_key(url)


def putnam_pin(lean_tag: str, *, jsonl_version_pin: str = "") -> PutnamPin:
    from jevops.lean import putnam_pin_for_tag

    return putnam_pin_for_tag(
        lean_tag,
        PUTNAM_TAGS,
        mathlib_git=MATHLIB_GIT,
        aesop_git=AESOP_GIT,
        jsonl_version_pin=jsonl_version_pin,
        normalize_fn=normalize_lean_tag,
        error_cls=BakeError,
    )


def render_lean_toolchain(lean_tag: str) -> str:
    from jevops.lean import render_lean_toolchain as _fn

    return _fn(normalize_lean_tag(lean_tag))


def render_lakefile(lean_tag: str, *, jsonl_version_pin: str = "") -> str:
    """Per-tag Mathlib+Aesop lakefile. Candidate module is Putnam.Candidate, not Tmp.lean."""

    from jevops.lean import render_mathlib_aesop_lakefile

    pin = putnam_pin(lean_tag, jsonl_version_pin=jsonl_version_pin)
    return render_mathlib_aesop_lakefile(
        package=pin.package,
        lib=pin.lib,
        max_heartbeats=MEASUREMENT_MAX_HEARTBEATS,
        mathlib_git=pin.mathlib_git,
        mathlib_rev=pin.mathlib_rev,
        aesop_git=pin.aesop_git,
        aesop_rev=pin.aesop_rev,
    )


def render_putnam_root() -> str:
    return f"import {PUTNAM_MODULE}\n"


def render_putnam_candidate_stub() -> str:
    from jevops.lean import putnam_candidate_stub

    return putnam_candidate_stub()


def putnam_project_files(lean_tag: str, *, jsonl_version_pin: str = "") -> dict[str, str]:
    pin = putnam_pin(lean_tag, jsonl_version_pin=jsonl_version_pin)
    from jevops.lean import putnam_file_map

    return putnam_file_map(
        pin,
        lakefile=render_lakefile(pin.lean_tag, jsonl_version_pin=jsonl_version_pin),
        toolchain=render_lean_toolchain(pin.lean_tag),
        root=render_putnam_root(),
        candidate=render_putnam_candidate_stub(),
        root_relpath=PUTNAM_ROOT_RELPATH,
        candidate_relpath=PUTNAM_CANDIDATE_RELPATH,
    )


def materialize_putnam_project(
    lean_tag: str,
    dest: Path,
    *,
    jsonl_version_pin: str = "",
) -> dict[str, str]:
    from jevops.lean import materialize_lake_files

    files = putnam_project_files(lean_tag, jsonl_version_pin=jsonl_version_pin)
    return materialize_lake_files(
        dest,
        files,
        refuse=FORBIDDEN_PUTNAM_BASENAME,
        error_cls=BakeError,
    )


def collect_bake_jobs(records: Sequence[Mapping[str, Any]]) -> list[BakeJob]:
    from jevops.lean import BakeCatalog, collect_bake_jobs as _fn

    return _fn(
        records,
        BakeCatalog(
            warmup_n=WARMUP_N,
            source_order=SOURCE_ORDER,
            putnam_source=PUTNAM_SOURCE,
            strata_source=STRATA_SOURCE,
            strata_first_tag=STRATA_FIRST_TAG,
            putnam_tags=PUTNAM_TAGS,
            putnam_candidate_relpath=PUTNAM_CANDIDATE_RELPATH,
            putnam_module=PUTNAM_MODULE,
        ),
        pin_fn=iter_version_pins,
        putnam_pin_fn=lambda tag, commit: putnam_pin(tag, jsonl_version_pin=commit),
        url_key_fn=_url_cache_key,
        error_cls=BakeError,
    )


def plan_bake(path: Optional[Path] = None) -> BakePlan:
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    jobs = collect_bake_jobs(records)
    from jevops.lean import plan_bake_from_jobs

    return plan_bake_from_jobs(
        jobs,
        digest,
        len(raw),
        len(records),
        cls=BakePlan,
    )


def job_cache_dir(job: BakeJob, state_root: Optional[Path] = None) -> Path:
    from jevops.outer import join_under

    root = Path(state_root) if state_root is not None else default_state_root()
    return join_under(root, "oleans", job.cache_key)


def putnam_project_dir(job: BakeJob, state_root: Optional[Path] = None) -> Path:
    from jevops.outer import join_under

    if job.kind != "putnam":
        raise BakeError("putnam_project_dir is only defined for Putnam jobs")
    root = Path(state_root) if state_root is not None else default_state_root()
    return join_under(root, "putnam_lake", job.lean_tag)


def cache_marker_path(cache_dir: Path) -> Path:
    return cache_dir / "BAKED"


def olean_paths(cache_dir: Path) -> list[Path]:
    from jevops.outer import walk_suffix_files

    return walk_suffix_files(cache_dir, ".olean")


def cache_present(job: BakeJob, state_root: Optional[Path] = None) -> bool:
    from jevops.outer import dir_marked

    return dir_marked(job_cache_dir(job, state_root), marker="BAKED", suffix=".olean")


def plant_synthetic_cache(job: BakeJob, state_root: Path, *, n_oleans: int = 1) -> Path:
    """Write a dummy olean cache. Not a live lake bake."""

    from jevops.lean import plant_synthetic_olean_cache

    return plant_synthetic_olean_cache(
        job_cache_dir(job, state_root),
        blobs={f"LraBake{index}.olean": b"LRA-013-synthetic-olean\n" for index in range(n_oleans)},
        receipt={
            "schema": "lra-olean-bake/v1",
            "cache_key": job.cache_key,
            "kind": job.kind,
            "lean_tag": job.lean_tag,
            "synthetic": True,
            "lake_build_executed": False,
            "arena_score": None,
        },
    )


def require_cache(
    job: BakeJob,
    *,
    network: str,
    state_root: Optional[Path] = None,
) -> dict[str, Any]:
    from jevops.outer import hit_or_miss

    present = cache_present(job, state_root)
    cache_dir = job_cache_dir(job, state_root)
    base = {
        "cache_key": job.cache_key,
        "cache_dir": str(cache_dir),
        "network": network,
        "arena_score": None,
    }
    return hit_or_miss(
        present,
        deny=network == "deny",
        error_cls=OleanCacheMissing,
        deny_msg=(
            "olean cache missing for "
            f"{job.cache_key} under network=deny; first lake build is hours and "
            "must be pre-vendored before the 48h clock. Never falling back to "
            "PATH lean, Tmp.lean, or a guessed PutnamBench GitHub URL."
        ),
        hit={**base, "ok": True, "status": "cache-hit", "n_oleans": len(olean_paths(cache_dir))},
        miss={**base, "ok": False, "status": "cache-missing", "n_oleans": 0},
    )


def require_plan_caches(
    plan: BakePlan,
    *,
    network: str,
    state_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    return [require_cache(job, network=network, state_root=state_root) for job in plan.jobs]


def lake_argv(lean_tag: str, *args: str, elan_home: Optional[Path] = None) -> list[str]:
    from jevops.outer import prepend_argv

    pin = tag_pinned_paths(lean_tag, elan_home=elan_home)
    return prepend_argv(pin["lake_path"], *args)


def _run_tag_pinned_lake(
    lean_tag: str,
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    env: Optional[Mapping[str, str]] = None,
    elan_home: Optional[Path] = None,
) -> dict[str, Any]:
    """Run tag-pinned lake. Never PATH ``lake``. Not used by --self-check."""

    from jevops.outer import run_pinned_bin

    pin = tag_pinned_paths(lean_tag, elan_home=elan_home)
    return run_pinned_bin(
        [pin["lake_path"], *list(args)],
        basename="lake",
        cwd=cwd,
        env=env,
        timeout=timeout,
        error_cls=BakeError,
        miss_cls=BakeToolchainMissing,
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


def bake_job(
    job: BakeJob,
    *,
    network: str,
    state_root: Optional[Path] = None,
    timeout: float = DEFAULT_LAKE_TIMEOUT_SECONDS,
    execute: bool = False,
) -> dict[str, Any]:
    """Return a cache hit, fail closed under network=deny, or bake if asked."""

    from jevops.lean import bake_or_hit
    from jevops.outer import git_checkout, git_clone, url_clone_dir

    root = Path(state_root) if state_root is not None else default_state_root()

    def _clone(item: BakeJob) -> Path:
        clone = url_clone_dir(root, item.url)
        if not (clone / ".git").is_dir():
            git_clone(
                item.url,
                clone,
                git_bin=GIT_BIN,
                error_cls=BakeError,
                miss_cls=BakeToolchainMissing,
            )
        return clone

    def _checkout(clone: Path, commit: str) -> Any:
        return git_checkout(
            clone,
            commit,
            git_bin=GIT_BIN,
            error_cls=BakeError,
            miss_cls=BakeToolchainMissing,
            skip_empty=False,
            skip_missing_git=False,
        )

    out = bake_or_hit(
        job,
        network=network,
        execute=execute,
        require_cache_fn=lambda item, network: require_cache(item, network=network, state_root=root),
        tag_paths_fn=tag_pinned_paths,
        materialize_fn=lambda item, project: materialize_putnam_project(
            item.lean_tag, project, jsonl_version_pin=item.git_commit
        ),
        putnam_dir_fn=lambda item: putnam_project_dir(item, root),
        clone_fn=_clone,
        checkout_fn=_checkout,
        run_lake_fn=lambda tag, args, cwd: _run_tag_pinned_lake(tag, args, cwd=cwd, timeout=timeout),
        copy_oleans_fn=_copy_oleans,
        cache_dir_fn=lambda item: job_cache_dir(item, root),
        mark_fn=lambda cache_dir: cache_marker_path(cache_dir).write_text("baked\n", encoding="utf-8"),
        olean_fn=olean_paths,
        error_cls=BakeError,
        miss_cls=BakeToolchainMissing,
    )
    if out.get("status") == "baked":
        out["lake_argv"] = lake_argv(job.lean_tag, "build")
    return out


def _copy_oleans(src: Path, dest: Path) -> None:
    from jevops.outer import copy_dir_required

    copy_dir_required(src, dest, error_cls=BakeError, miss="expected .lake directory at {src}")


def _copytree(src: Path, dest: Path) -> None:
    from jevops.outer import copy_tree

    copy_tree(src, dest)


def write_candidate(lean_tag: str, source_text: str, dest: Optional[Path] = None) -> Path:
    """Copy a Putnam candidate into Putnam/Candidate.lean. Never Tmp.lean."""

    if dest is None:
        dest = putnam_project_dir(
            BakeJob(
                kind="putnam",
                source=PUTNAM_SOURCE,
                lean_tag=normalize_lean_tag(lean_tag),
                git_commit="",
                url="",
                cache_key=f"putnam/{normalize_lean_tag(lean_tag)}",
                phase=2,
                record_names=(),
                file_paths=(PUTNAM_CANDIDATE_RELPATH,),
                module=PUTNAM_MODULE,
                lakefile_required=True,
            )
        )
    from jevops.lean import write_putnam_candidate

    return write_putnam_candidate(
        dest,
        source_text,
        candidate_relpath=PUTNAM_CANDIDATE_RELPATH,
        refuse=FORBIDDEN_PUTNAM_BASENAME,
        error_cls=BakeError,
    )


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _call_name(node: ast.AST) -> str:
    from jevops.repair import call_short_name

    return call_short_name(node)


def audit_source(source: Optional[str] = None) -> dict[str, Any]:
    from jevops.outer import source_text
    from jevops.repair import audit_source as _audit, matching_constants

    text = source_text(source, path=__file__)
    out = _audit(
        text,
        forbidden_imports=FORBIDDEN_IMPORT_NAMES,
        forbidden_calls=FORBIDDEN_CALLS,
        forbidden_scores=FORBIDDEN_SCORE_NAMES,
    )
    imported = set(out["imported_names"])
    calls = set(out["call_names"])
    constants = out["string_constants"]
    forbidden_urls = sorted(
        matching_constants(
            text,
            lambda value: "://" in value
            and any(needle.lower() in value.lower() for needle in FORBIDDEN_PUTNAM_URL_NEEDLES),
        )
    )
    score_assignments = list(out["score_keys"])
    has_tmp_constant = FORBIDDEN_PUTNAM_BASENAME in constants
    has_putnam_module = PUTNAM_MODULE in constants
    has_mathlib_git = MATHLIB_GIT in constants
    has_aesop_git = AESOP_GIT in constants
    return {
        "imported_names": out["imported_names"],
        "forbidden_imports": out["forbidden_imports"],
        "forbidden_calls": out["forbidden_calls"],
        "forbidden_putnambench_urls": forbidden_urls,
        "score_assignments": score_assignments,
        "has_tmp_lean_constant": has_tmp_constant,
        "has_putnam_module": has_putnam_module,
        "has_mathlib_git": has_mathlib_git,
        "has_aesop_git": has_aesop_git,
        "uses_fcntl": "fcntl" in imported,
        "uses_shutil_which": "shutil" in imported and "which" in calls,
        "ok": (
            not out["forbidden_imports"]
            and not out["forbidden_calls"]
            and not forbidden_urls
            and not score_assignments
            and has_tmp_constant
            and has_putnam_module
            and has_mathlib_git
            and has_aesop_git
        ),
    }


def _synthetic_fail_closed(plan: BakePlan) -> dict[str, Any]:
    from jevops.outer import temp_dir

    with temp_dir(prefix="lra-013-oleans-") as tmp:
        root = Path(tmp)
        first = plan.first_job
        planted = plant_synthetic_cache(first, root)
        hit = require_cache(first, network="deny", state_root=root)
        missing_raised = False
        missing_message = ""
        putnam_job = next(job for job in plan.jobs if job.kind == "putnam")
        try:
            require_cache(putnam_job, network="deny", state_root=root)
        except OleanCacheMissing as exc:
            missing_raised = True
            missing_message = str(exc)
        allow_missing = require_cache(putnam_job, network="allow", state_root=root)
        write_denied = False
        try:
            write_candidate(STRATA_FIRST_TAG, "theorem x : True := by trivial", dest=root / FORBIDDEN_PUTNAM_BASENAME)
        except BakeError:
            write_denied = True
        materialized: dict[str, Any] = {}
        for job in plan.jobs:
            if job.kind != "putnam":
                continue
            dest = root / "putnam_lake" / job.lean_tag
            files = materialize_putnam_project(job.lean_tag, dest, jsonl_version_pin=job.git_commit)
            from jevops.lean import pack_materialized_putnam
            from jevops.outer import read_json, read_text

            lakefile = read_text(dest / "lakefile.lean")
            toolchain = read_text(dest / "lean-toolchain").strip()
            pins = read_json(dest / "pins.json")
            materialized[job.lean_tag] = pack_materialized_putnam(
                dest,
                files,
                lakefile=lakefile,
                toolchain=toolchain,
                pins=pins,
                mathlib_git=MATHLIB_GIT,
                aesop_git=AESOP_GIT,
                refuse=FORBIDDEN_PUTNAM_BASENAME,
            )
        from jevops.lean import pack_synthetic_bake

        return pack_synthetic_bake(
            planted=planted,
            planted_n=len(olean_paths(planted)),
            hit=hit,
            missing_raised=missing_raised,
            missing_message=missing_message,
            allow_missing=allow_missing,
            write_denied=write_denied,
            materialized=materialized,
            putnam_tags=PUTNAM_TAGS,
            putnam_module=PUTNAM_MODULE,
        )


def probe_toolchain(tags: Iterable[str] | None = None) -> dict[str, Any]:
    if tags is None:
        tags = (STRATA_FIRST_TAG, *PUTNAM_TAGS)
    from jevops.lean import probe_pins
    from jevops.outer import env_str

    return probe_pins(
        list(tags),
        resolve_fn=tag_pinned_paths,
        extra={
            "default_elan_home": str(default_elan_home()),
            "elan_home_env": env_str("ELAN_HOME"),
            "lake": False,
            "path": env_str("PATH"),
            "validation_home": str(Path.home()),
        },
        gap_msg=(
            "No tag-pinned elan lean/lake binaries are installed under the "
            "resolver elan home. Paths remain tag-pinned; this is not PATH "
            "lake usability and is not a completed olean bake."
        ),
    )


def self_check(path: Optional[Path] = None) -> dict[str, Any]:
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    plan = plan_bake(jsonl)
    first = plan.first_job
    audit = audit_source()
    synthetic = _synthetic_fail_closed(plan)
    toolchain = probe_toolchain()
    putnam_jobs = [job for job in plan.jobs if job.kind == "putnam"]
    repo_jobs = [job for job in plan.jobs if job.kind == "repo"]
    phases = [job.phase for job in plan.jobs]
    from jevops.outer import env_str, head_seq

    first_phase_ok = head_seq(phases, 1) == [0] and all(phase >= 0 for phase in phases)
    strata_v426_before_rest = all(
        job.phase == 0
        for job in plan.jobs
        if job.source == STRATA_SOURCE and job.lean_tag == STRATA_FIRST_TAG
    ) and all(job.phase > 0 for job in plan.jobs if not (
        job.source == STRATA_SOURCE and job.lean_tag == STRATA_FIRST_TAG
    ))
    putnam_headers_ok = True
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    putnam_records = [record for record in records if record.get("source") == PUTNAM_SOURCE]
    for record in putnam_records:
        header = record.get("header") or ""
        if "import Mathlib" not in header or "import Aesop" not in header:
            putnam_headers_ok = False
        if (record.get("url") or "").strip() or (record.get("file_path") or "").strip():
            putnam_headers_ok = False
    report: dict[str, Any] = {
        "ok": False,
        "arena_score": None,
        "score": None,
        "compiled": False,
        "lake": False,
        "lake_build_executed": False,
        "oleans_baked": False,
        "llama_server_started": False,
        "frozen_warmup_sha256": digest,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": digest == FROZEN_WARMUP_SHA256,
        "n_records": len(records),
        "n_jobs": len(plan.jobs),
        "n_repo_jobs": len(repo_jobs),
        "n_putnam_jobs": len(putnam_jobs),
        "n_putnam_records": len(putnam_records),
        "first_job": first.to_dict(),
        "first_is_strata_v4_26": (
            first.kind == "repo"
            and first.source == STRATA_SOURCE
            and first.lean_tag == STRATA_FIRST_TAG
            and first.git_commit == STRATA_FIRST_COMMIT
            and first.url == STRATA_URL
            and first.phase == 0
        ),
        "first_cache_key": first.cache_key,
        "strata_v4_26_recorded_first": True,
        "strata_v426_before_rest": strata_v426_before_rest,
        "first_phase_ok": first_phase_ok,
        "putnam_tags": [job.lean_tag for job in putnam_jobs],
        "putnam_tags_match": tuple(job.lean_tag for job in putnam_jobs) == PUTNAM_TAGS,
        "putnam_module": PUTNAM_MODULE,
        "putnam_not_tmp_lean": all(job.module == PUTNAM_MODULE for job in putnam_jobs)
        and all(FORBIDDEN_PUTNAM_BASENAME not in job.file_paths for job in putnam_jobs),
        "putnam_headers_import_mathlib_aesop": putnam_headers_ok,
        "putnam_url_file_path_empty": all(not job.url for job in putnam_jobs),
        "putnambench_url_not_guessed": all(job.putnambench_url is None for job in putnam_jobs),
        "missing_cache_fails_closed_under_network_deny": bool(
            synthetic["missing_putnam_under_network_deny_raises"]
            and synthetic["missing_message_mentions_network_deny"]
            and synthetic["deny_cache_hit_on_planted_strata_v4_26"]
        ),
        "measurement_maxHeartbeats": MEASUREMENT_MAX_HEARTBEATS,
        "kernel_command_template": KERNEL_COMMAND_TEMPLATE,
        "bake_argv_template": BAKE_ARGV_TEMPLATE,
        "default_state_root": str(default_state_root()),
        "network_env": env_str("LRA_NETWORK"),
        "protocol": "LRA/v1",
        "audit": audit,
        "synthetic": {
            key: value
            for key, value in synthetic.items()
            if key != "materialized_putnam"
        },
        "putnam_projects": synthetic["materialized_putnam"],
        "toolchain": toolchain,
        "jobs": [job.to_dict() for job in plan.jobs],
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
        "putnam_readme_exists": PUTNAM_README.is_file(),
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and report["n_jobs"] == 15
        and report["n_repo_jobs"] == 12
        and report["n_putnam_jobs"] == 3
        and report["first_is_strata_v4_26"]
        and report["strata_v426_before_rest"]
        and report["putnam_tags_match"]
        and report["putnam_not_tmp_lean"]
        and report["putnam_headers_import_mathlib_aesop"]
        and report["putnam_url_file_path_empty"]
        and report["putnambench_url_not_guessed"]
        and report["missing_cache_fails_closed_under_network_deny"]
        and synthetic["all_putnam_tags_materialized"]
        and not synthetic["any_putnam_tmp_lean"]
        and synthetic["all_putnam_have_mathlib_aesop_lakefile"]
        and synthetic["all_putnam_module_candidate"]
        and synthetic["all_putnambench_url_null"]
        and synthetic["write_candidate_rejects_tmp_lean"]
        and audit["ok"]
        and report["compiled"] is False
        and report["lake"] is False
        and report["lake_build_executed"] is False
        and report["oleans_baked"] is False
        and report["arena_score"] is None
        and report["score"] is None
        and report["putnam_readme_exists"]
    )
    return report


def _print_json(payload: Mapping[str, Any]) -> None:
    from jevops.outer import print_json

    print_json(payload)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="plan, fail-closed cache, Putnam lakefiles; no lake build")
    parser.add_argument("--plan", action="store_true", help="print the bake plan; Strata v4.26 first")
    parser.add_argument("--probe-toolchain", action="store_true", help="record tag-pinned elan paths; do not run lake")
    parser.add_argument("--dump-putnam-project", action="store_true", help="print one per-tag Putnam lake project")
    parser.add_argument("--require-cache", action="store_true", help="fail closed if oleans are missing")
    parser.add_argument("--materialize-putnam", type=Path, default=None, help="write per-tag Putnam lake projects under this directory")
    parser.add_argument("--tag", default=STRATA_FIRST_TAG, help="Putnam/Lean tag for dump/materialize (default v4.26.0)")
    parser.add_argument("--network", default=None, help="allow or deny (default: LRA_NETWORK or allow)")
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL path")
    parser.add_argument("--state-root", type=Path, default=None, help="olean/putnam_lake state root")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_check or argv is None or argv == []:
        from jevops.outer import print_ok

        return print_ok(self_check(args.jsonl))

    if args.plan:
        plan = plan_bake(args.jsonl)
        _print_json(plan.to_dict())
        return 0

    if args.probe_toolchain:
        _print_json(probe_toolchain())
        return 0

    if args.dump_putnam_project:
        plan = plan_bake(args.jsonl)
        tag = normalize_lean_tag(args.tag)
        from jevops.outer import first_where

        job = first_where(plan.jobs, lambda item: item.kind == "putnam" and item.lean_tag == tag)
        pin_commit = job.git_commit if job is not None else ""
        files = putnam_project_files(tag, jsonl_version_pin=pin_commit)
        _print_json(
            {
                "arena_score": None,
                "files": files,
                "lean_tag": tag,
                "module": PUTNAM_MODULE,
                "not_tmp_lean": True,
                "putnambench_url": None,
                "jsonl_version_pin": pin_commit,
            }
        )
        return 0

    if args.materialize_putnam is not None:
        plan = plan_bake(args.jsonl)
        dest_root = Path(args.materialize_putnam)
        written: dict[str, Any] = {}
        for job in plan.jobs:
            if job.kind != "putnam":
                continue
            dest = dest_root / job.lean_tag
            files = materialize_putnam_project(job.lean_tag, dest, jsonl_version_pin=job.git_commit)
            written[job.lean_tag] = files
        _print_json(
            {
                "arena_score": None,
                "dest": str(dest_root),
                "module": PUTNAM_MODULE,
                "not_tmp_lean": True,
                "putnambench_url": None,
                "written": written,
            }
        )
        return 0

    if args.require_cache:
        plan = plan_bake(args.jsonl)
        network = network_mode(args.network)
        state_root = args.state_root
        results = []
        try:
            results = require_plan_caches(plan, network=network, state_root=state_root)
        except OleanCacheMissing as exc:
            from jevops.outer import failed_check

            _print_json(failed_check(exc, network=network, first_job=plan.first_job.to_dict()))
            return 1
        _print_json(
            {
                "ok": True,
                "network": network,
                "n_jobs": len(results),
                "results": results,
                "arena_score": None,
                "first_job": plan.first_job.to_dict(),
            }
        )
        return 0

    parser.error(
        "choose --self-check, --plan, --probe-toolchain, --dump-putnam-project, "
        "--materialize-putnam, or --require-cache"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
