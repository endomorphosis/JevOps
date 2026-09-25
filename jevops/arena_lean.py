"""Opt-in native Lean measurement, with explicit read-only project bindings.

No clone, checkout, Lake build, toolchain download, provider call, or PATH Lean.
Default execution is trusted-local. An explicit rootless Docker profile can
isolate host access; it is not a separate proof checker or official Arena worker.
The fixed LRA/v1 Lake admission path is unaffected.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Mapping
from urllib.parse import urlparse

from .arena import (ArenaContext, ArenaEvaluator, Outcome, VerificationRequest, VersionReceipt,
                    content_hash, intake_error, reference_tokens, source_hash, _units)
from .arena_isolation import DockerIsolation, IsolationUnavailable, capture_process
from .arena_staging import StagedImports, SELECTED_SCHEMA, MANIFEST_LIMIT
from .lean import VersionPin
from .proof_ca import canonical_json
from .proof_trust import _NAME
from .seals import Fingerprinter

DRIVER = Path(__file__).with_name("lean") / "ArenaCheck.lean"
BOUNDARY_FILES = (Path(__file__), DRIVER, *(Path(__file__).with_name(name) for name in
                  ("arena.py", "arena_isolation.py", "arena_staging.py", "proof_trust.py", "seals.py", "proof_ca.py", "lean.py")))
VERIFIER = "jevops-native-arena"
METHOD = "command-elaboration-internal-heartbeats-div-1000/v1"
MAX_OUTPUT = 1_048_576
MAX_PREFIX = 8_388_608
CORPUS = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl"


class CapabilityGap(ValueError):
    """Missing prepared infrastructure, never evidence against a theorem."""


def pinned_lean(elan_home: Path, tag: str) -> Path:
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\d+)?", tag):
        raise ValueError("unsupported explicit Lean tag")
    path = elan_home.resolve() / "toolchains" / f"leanprover--lean4---{tag}" / "bin/lean"
    if not path.is_file() or not os.access(path, os.X_OK):
        raise CapabilityGap(f"pinned_toolchain_missing: {tag}")
    return path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["/usr/bin/git", "-C", str(root), *args], capture_output=True,
                            text=True, timeout=10, check=False,
                            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
    if result.returncode:
        raise CapabilityGap("project_git_metadata_unavailable")
    return result.stdout.strip()


def _check_project(root: Path, pin: VersionPin) -> None:
    if _git(root, "rev-parse", "HEAD") != pin.git_commit:
        raise CapabilityGap("project_commit_mismatch")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise CapabilityGap("project_has_tracked_changes")
    _check_toolchain(root, pin)


def _check_toolchain(root: Path, pin: VersionPin) -> None:
    if (root / "lean-toolchain").read_text().strip() != f"leanprover/lean4:{pin.lean_tag}":
        raise CapabilityGap("project_toolchain_mismatch")


@dataclass(frozen=True)
class PackagePin:
    name: str
    repository: str
    commit: str
    checkout: Path
    root: Path


@dataclass(frozen=True)
class LakeEnvironment:
    """Resolved lockfile identity, not an assertion that artifacts were rebuilt."""
    manifest_sha256: str
    packages: tuple[PackagePin, ...]

    def validate(self, root: Path) -> None:
        if source_hash((root / "lake-manifest.json").read_text()) != self.manifest_sha256:
            raise CapabilityGap("lake_manifest_changed_start_new_context")
        for package in self.packages:
            if (_git(package.checkout, "rev-parse", "HEAD") != package.commit
                    or Path(_git(package.checkout, "rev-parse", "--show-toplevel")).resolve() != package.checkout):
                raise CapabilityGap(f"dependency_commit_mismatch: {package.name}")
            if _git(package.checkout, "status", "--porcelain", "--untracked-files=no"):
                raise CapabilityGap(f"dependency_has_tracked_changes: {package.name}")


def _within(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise CapabilityGap("invalid_dependency_path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise CapabilityGap("invalid_dependency_path")
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise CapabilityGap("dependency_escapes_project")
    return resolved


def lake_environment(root: Path) -> LakeEnvironment:
    """Read pinned Git packages from Lake's flattened lockfile; never run Lake.

    Path dependencies and unknown lockfile schemas require an explicit adapter.
    Unbuilt optional tooling packages need not be on the Lean import path.
    """
    path = root / "lake-manifest.json"
    if path.stat().st_size > 1_048_576:
        raise CapabilityGap("lake_manifest_byte_budget")
    source = path.read_text()
    data = json.loads(source)
    # 1.2 adds fixedToolchain metadata; Git entry semantics are unchanged.
    if not isinstance(data, dict) or data.get("version") not in ("1.1.0", "1.2.0"):
        raise CapabilityGap("unsupported_lake_manifest_schema")
    entries = data.get("packages")
    if not isinstance(entries, list) or len(entries) > 1024:
        raise CapabilityGap("invalid_lake_packages")
    packages, names = [], set()
    directory = data.get("packagesDir", ".lake/packages")
    # A dependency-free project need not have created .lake/packages yet.
    base = _within(root, directory) if entries else root
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "git":
            raise CapabilityGap("unsupported_lake_dependency_type")
        name = entry.get("name", "")
        if isinstance(name, str) and name.startswith("«") and name.endswith("»"):
            name = name[1:-1]  # Lake serializes escaped Lean identifiers this way.
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9-]*", name) or name in names:
            raise CapabilityGap("invalid_or_duplicate_lake_package_name")
        names.add(name)
        commit, url = entry.get("rev"), entry.get("url")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) or not isinstance(url, str) or not url:
            raise CapabilityGap("exact_lake_dependency_pin_required")
        checkout = _within(base, name)
        subdir = entry.get("subDir")
        package_root = _within(checkout, subdir) if subdir is not None else checkout
        packages.append(PackagePin(name, url, commit, checkout, package_root))
    environment = LakeEnvironment(source_hash(source), tuple(packages))
    environment.validate(root)
    return environment


def _lake_search(root: Path, environment: LakeEnvironment, *, include_project: bool) -> tuple[Path, ...]:
    roots = ([root] if include_project else []) + [p.root for p in environment.packages]
    return tuple(p.resolve() for r in roots if (p := r / ".lake/build/lib/lean").is_dir())


def _artifacts(root: Path) -> list[Path]:
    """Membership is rescanned; hashes use the existing inode/ctime-aware cache.

    Include sources, imported serialized environments/IR, shared libraries and
    configuration. Static archives/debug info are not read by this interpreter.
    """
    if not root.is_dir():
        raise CapabilityGap(f"dependency_directory_missing: {root}")
    return sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and
                  (p.name.endswith((".lean", ".olean", ".olean.private", ".olean.server", ".ir"))
                   or ".so" in p.name or p.name in {"lean-toolchain", "lake-manifest.json", "lakefile.toml"}))


@dataclass(frozen=True)
class ProjectBinding:
    pin: VersionPin
    lean: Path
    root: Path
    prefix: str
    search_paths: tuple[Path, ...] = ()
    repository: str = ""
    project_backed: bool = True
    lake: LakeEnvironment | None = None
    putnam: bool = False
    staged_imports: StagedImports | None = None

    def with_staged_imports(self, manifest: Path, manifest_sha256: str) -> ProjectBinding:
        if self.staged_imports is not None:
            raise ValueError("imports already staged; use the original binding for a new stage")
        if manifest.is_symlink() or manifest.stat().st_size > MANIFEST_LIMIT:
            raise ValueError("invalid bounded import manifest")
        # A selected stage is tied to the FULL original context, including
        # omitted artifacts, compiler, source, pins and verifier implementation.
        manifest_value = json.loads(manifest.read_bytes())
        if type(manifest_value) is not dict:
            raise ValueError("invalid import manifest object")
        selected = manifest_value.get("schema") == SELECTED_SCHEMA
        scope = self.fingerprint(Fingerprinter()) if selected else None
        stage = StagedImports(manifest, manifest_sha256, self.search_paths, scope)
        stage.validate()
        return replace(self, search_paths=stage.paths, staged_imports=stage)

    def fingerprint(self, reader: Fingerprinter) -> str:
        if self.staged_imports is not None:
            if self.search_paths != self.staged_imports.paths:
                raise ValueError("staged search path binding changed")
            if self.staged_imports.scope_sha256 is not None:
                original = replace(self, search_paths=self.staged_imports.sources, staged_imports=None)
                if original.fingerprint(reader) != self.staged_imports.scope_sha256:
                    raise ValueError("original selected-import context changed; rediscover and restage")
            self.staged_imports.validate()
        if self.project_backed:
            _check_project(self.root, self.pin)
        if self.lake is not None:
            _check_toolchain(self.root, self.pin)
            self.lake.validate(self.root)
        roots = (self.lean.parent.parent / "lib", *self.search_paths)
        paths = [self.lean, *BOUNDARY_FILES]
        for root in roots:
            paths.extend(_artifacts(root))
        if self.project_backed or self.lake is not None:
            paths.extend(_artifacts(self.root))
        snap = reader.snapshot(list(dict.fromkeys(paths)))
        return content_hash({"schema": "jevops-arena-dependencies/v1", "files": snap.root,
                             "prefix": source_hash(self.prefix), "repository": self.repository,
                             "pin": self.pin.to_dict(), "search_paths": [str(p) for p in self.search_paths],
                             **({"staged_import_manifest": self.staged_imports.manifest_sha256,
                                 "original_search_paths": list(map(str, self.staged_imports.sources))}
                                if self.staged_imports is not None else {}),
                             "binding_kind": "putnam" if self.putnam else "project"})


def project_binding(record: Mapping, pin: VersionPin, project: Mapping, elan_home: Path) -> ProjectBinding:
    binding = _project_binding(record, pin, project, elan_home)
    fields = ("staged_imports_manifest", "staged_imports_sha256")
    if any(key in project for key in fields):
        if not all(isinstance(project.get(key), str) and project[key] for key in fields):
            raise CapabilityGap("both staged import manifest and SHA-256 required")
        binding = binding.with_staged_imports(Path(project[fields[0]]), project[fields[1]])
    return binding


def _project_binding(record: Mapping, pin: VersionPin, project: Mapping, elan_home: Path) -> ProjectBinding:
    """Bind a prepared checkout without editing it or importing its target module."""
    root = Path(project["root"]).resolve(strict=True)
    if project.get("repository") != record.get("url"):
        raise CapabilityGap("repository_binding_mismatch")
    if project.get("kind") == "putnam":
        return putnam_binding(record, pin, project, elan_home)
    if project.get("kind", "repo") != "repo":
        raise CapabilityGap("unsupported_project_kind")
    _check_project(root, pin)
    relative = Path(record["file_path"])
    if not record["file_path"] or relative.is_absolute() or ".." in relative.parts:
        raise CapabilityGap("explicit_project_source_required")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root):
        raise CapabilityGap("source_escapes_project")
    original = path.read_text()
    source = record["src"]
    if not source or original.count(source) != 1:
        raise CapabilityGap("reference_source_not_uniquely_located")
    # No suffix: later declarations must not become premises for their own proof.
    prefix = original[:original.index(source)]
    if len(prefix.encode()) > MAX_PREFIX:
        raise CapabilityGap("prefix_byte_budget")
    lake = lake_environment(root) if project.get("resolve_lake_manifest") is True else None
    if lake is not None and "search_paths" in project:
        raise CapabilityGap("ambiguous_search_path_configuration")
    search = (_lake_search(root, lake, include_project=True) if lake is not None else
              tuple(Path(p).resolve(strict=True) for p in project.get("search_paths", [])))
    if any(not p.is_dir() for p in search):
        raise CapabilityGap("invalid_search_directory")
    return ProjectBinding(pin, pinned_lean(elan_home, pin.lean_tag), root, prefix, search, record["url"], lake=lake)


def putnam_binding(record: Mapping, pin: VersionPin, project: Mapping, elan_home: Path) -> ProjectBinding:
    """JSONL Putnam pins are Mathlib commits, not PutnamBench commits or tags.

    Use the exact frozen header, never the cached Putnam.Candidate module. The
    lockfile supplies Aesop and transitive revisions; pins.json is not evidence.
    """
    if (record.get("source") != "putnambench" or record.get("url") != ""
            or record.get("file_path") != "" or project.get("repository") != ""):
        raise CapabilityGap("invalid_putnam_record_binding")
    if "search_paths" in project:
        raise CapabilityGap("putnam_requires_lockfile_search_paths")
    prefix = record.get("header")
    if not isinstance(prefix, str) or not prefix.strip() or len(prefix.encode()) > MAX_PREFIX:
        raise CapabilityGap("bounded_putnam_header_required")
    root = Path(project["root"]).resolve(strict=True)
    _check_toolchain(root, pin)
    lake = lake_environment(root)
    packages = {p.name: p for p in lake.packages}
    for name, repo in (("mathlib", "mathlib4"), ("aesop", "aesop")):
        if name not in packages or packages[name].repository.removesuffix(".git") != f"https://github.com/leanprover-community/{repo}":
            raise CapabilityGap(f"putnam_{name}_repository_mismatch")
    if packages["mathlib"].commit != pin.git_commit:
        raise CapabilityGap("putnam_mathlib_commit_mismatch")
    _check_toolchain(packages["mathlib"].root, pin)
    search = _lake_search(root, lake, include_project=False)
    for name, module in (("mathlib", "Mathlib"), ("aesop", "Aesop")):
        if not (packages[name].root / f".lake/build/lib/lean/{module}.olean").is_file():
            raise CapabilityGap(f"putnam_compiled_import_missing: {module}")
    return ProjectBinding(pin, pinned_lean(elan_home, pin.lean_tag), root, prefix, search,
                          project_backed=False, lake=lake, putnam=True)


def discover_projects(records: list[dict], state_root: Path) -> list[dict]:
    """Inventory only the old harness's explicit layout, with no home-wide scan.

    Emit all required pins, including missing/mismatched checkouts. Never select
    the current HEAD as a substitute or mutate a clone to satisfy another pin.
    """
    root = state_root.resolve(strict=True)
    projects = {}
    for record in records:
        repository = record.get("url", "")
        putnam = record.get("source") == "putnambench" and not repository and not record.get("file_path")
        if not putnam:
            url = urlparse(repository)
            if (url.scheme != "https" or url.netloc != "github.com" or url.query or url.fragment
                    or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url.path)
                    or any(p in {".", ".."} for p in url.path.split("/"))):
                raise CapabilityGap("unsupported_harness_repository_layout")
        for row in record["version_info"]:
            for tag, commit in row.items():
                if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\d+)?", tag):
                    raise CapabilityGap("unsupported_harness_toolchain_tag")
                path = root / "putnam_lake" / tag if putnam else root / "clones/github.com" / url.path.lstrip("/")
                projects[repository, tag, commit] = {"repository": repository, "lean_tag": tag,
                    "git_commit": commit, "root": str(path), "kind": "putnam" if putnam else "repo",
                    "resolve_lake_manifest": True}
    return list(projects.values())


def run_native(binding: ProjectBinding, payload: dict, *, timeout: float,
               isolation: DockerIsolation | None = None) -> tuple[dict, int]:
    """Bound pipes/wall time; optionally require the explicit isolation profile."""
    if (len(payload.get("prefix", "").encode()) > MAX_PREFIX
            or any(len(payload.get(key, "").encode()) > 262144 for key in ("reference", "candidate"))):
        raise ValueError("native source byte budget")
    deadline = time.monotonic() + timeout
    with ExitStack() as stack:
        scratch = stack.enter_context(tempfile.TemporaryDirectory(prefix="jevops-arena-"))
        stdin = stack.enter_context(tempfile.TemporaryFile())
        stdin.write(canonical_json(payload).encode()); stdin.seek(0)
        env = {"PATH": f"{binding.lean.parent}:/usr/bin:/bin", "HOME": scratch, "TMPDIR": scratch,
               "LEAN_PATH": os.pathsep.join(map(str, binding.search_paths)), "LEAN_NUM_THREADS": "1"}
        command = [str(binding.lean), "--run", str(DRIVER)]
        if isolation is not None:
            command, env = stack.enter_context(isolation.launch(binding.lean, binding.search_paths, DRIVER,
                                                               scratch=scratch, deadline=deadline))
        output, errors, code = capture_process(command, stdin=stdin, cwd=scratch, env=env,
            timeout=deadline - time.monotonic(), output_limit=MAX_OUTPUT)
        if code:
            raise ValueError(f"native driver exit {code}: {errors.decode(errors='replace')[:500]}"
                             f" {output.decode(errors='replace')[:500]}")
        rows = [line.removeprefix("JEVOPS_ARENA:") for line in output.decode().splitlines()
                if line.startswith("JEVOPS_ARENA:")]
        if len(rows) != 1:
            raise ValueError("exactly one bound native report required")
        return json.loads(rows[0]), code


class NativeLeanVerifier:
    """Single-owner native adapter. Use evaluator() to validate cache hits too.

    The project/toolchain and local filesystem are trusted, including imported
    metaprograms. Stat-cache reuse assumes reliable inode/ctime metadata. Pass
    strict_hashes=True to rehash all bytes. No cross-process ownership claim.
    """
    def __init__(self, bindings: Mapping[VersionPin, ProjectBinding], *, max_processes: int,
                 timeout: float = 60, max_heartbeats: int = 2_000_000, strict_hashes: bool = False,
                 fingerprinter: Fingerprinter | None = None, branch_order: str = "reference-first",
                 isolation: DockerIsolation | None = None):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("finite positive timeout required")
        if _units(max_heartbeats, "max_heartbeats") == 0:
            raise ValueError("finite positive heartbeat limit required")
        if branch_order not in ("reference-first", "candidate-first"):
            raise ValueError("explicit supported branch order required")
        self.branch_order = branch_order
        self.bindings = dict(bindings)
        if not self.bindings or any(pin != b.pin for pin, b in self.bindings.items()):
            raise ValueError("explicit matching bindings required")
        self.max_processes = _units(max_processes, "max_processes")
        self.processes = 0
        self.timeout, self.max_heartbeats = timeout, max_heartbeats
        if fingerprinter is not None and strict_hashes and not fingerprinter.strict:
            raise ValueError("strict hashing requires a strict injected fingerprinter")
        self.reader = fingerprinter if fingerprinter is not None else Fingerprinter(strict=strict_hashes)
        if isolation is not None and type(isolation) is not DockerIsolation:
            raise ValueError("explicit DockerIsolation configuration required")
        self.isolation = isolation
        self.isolation_identity = self._isolation_identity()
        self.digests = {pin: b.fingerprint(self.reader) for pin, b in self.bindings.items()}
        self.version = content_hash({str(p.relative_to(Path(__file__).parent)): source_hash(p.read_text())
                                     for p in BOUNDARY_FILES})

    @property
    def options_json(self) -> str:
        options = {"max_heartbeats": self.max_heartbeats, "timeout": self.timeout,
                               "async": False, "kernel_check": True, "reference_branch": "independent",
                   "branch_order": self.branch_order, "os_sandbox": self.isolation is not None}
        if self.isolation is not None:
            options["execution_policy"] = self.isolation.policy
            options["execution_identity"] = self.isolation_identity
        return canonical_json(options)

    def _isolation_identity(self) -> str | None:
        if self.isolation is None:
            return None
        self.isolation.validate_paths()
        socket = self.isolation.socket.stat()
        return content_hash({"policy": self.isolation.policy,
            "client": self.reader.snapshot([self.isolation.executable]).root,
            "socket_device": socket.st_dev, "socket_inode": socket.st_ino})

    def context(self, record: Mapping, *, reference_heartbeats: int | None = None) -> ArenaContext:
        pins = tuple(VersionPin(tag, commit) for row in record["version_info"] for tag, commit in row.items())
        if set(pins) - self.bindings.keys():
            raise CapabilityGap("not_all_version_bindings_available")
        return ArenaContext(record["name"], record["statement"], record["src"],
                            reference_tokens(record["src"], record["statement"]), reference_heartbeats,
                            pins, tuple(self.digests[p] for p in pins), VERIFIER, self.version, METHOD,
                            record.get("header", ""), record.get("url", ""), record.get("file_path", ""),
                            self.options_json)

    def validate_request(self, request: VerificationRequest) -> None:
        if self._isolation_identity() != self.isolation_identity:
            raise ValueError("execution_environment_changed_start_new_context")
        ctx, pin = request.context, request.version
        if (ctx.verifier_id != VERIFIER or ctx.verifier_version != self.version or ctx.heartbeat_method != METHOD
                or ctx.verifier_options_json != self.options_json or pin not in ctx.versions or pin not in self.bindings):
            raise ValueError("native verifier/context mismatch")
        binding = self.bindings[pin]
        if ctx.repository != binding.repository:
            raise ValueError("native repository mismatch")
        if binding.putnam and (ctx.header != binding.prefix or ctx.file_path):
            raise ValueError("native Putnam header/context mismatch")
        if ctx.dependency_digests[ctx.versions.index(pin)] != binding.fingerprint(self.reader):
            raise ValueError("dependencies_changed_start_new_context")
        if not _NAME.fullmatch(ctx.problem):
            raise ValueError("unsupported target name")

    def evaluator(self, context: ArenaContext, *, max_calls: int, **kwargs) -> ArenaEvaluator:
        if context.reference_heartbeats is None:
            raise ValueError("calibrate the native reference before score-aware selection")
        return ArenaEvaluator(context, self, max_calls=max_calls, evidence_mode="local_lean",
                              context_validator=self.validate_request, **kwargs)

    def calibrate(self, context: ArenaContext) -> tuple[ArenaContext | None, VersionReceipt]:
        """Reserve a real process to measure this method's reference denominator.

        Never use published worker heartbeats as a native-method denominator.
        Returns a new immutable measurement context or explicit non-success.
        """
        baseline_context = replace(context, reference_heartbeats=None)
        receipt = self(VerificationRequest(baseline_context, context.reference_source, context.versions[0]))
        if receipt.outcome != Outcome.VERIFIED:
            return None, receipt
        measured = json.loads(receipt.observations_json)["report"]["reference_heartbeats"]
        return replace(baseline_context, reference_heartbeats=measured), receipt

    def __call__(self, request: VerificationRequest) -> VersionReceipt:
        empty = VersionReceipt(request.request_id, source_hash(request.source), request.context.problem, Outcome.ERROR)
        try:
            self.validate_request(request)
            error = intake_error(request.source, request.context.statement)
            if error:
                return replace(empty, outcome=Outcome.REJECTED, reason=error)
            if self.processes >= self.max_processes:
                return replace(empty, outcome=Outcome.BUDGET_EXHAUSTED, reason="native_process_budget")
            self.processes += 1
            start = time.monotonic()
            data, code = run_native(self.bindings[request.version], {
                "request_id": request.request_id, "target": request.context.problem,
                "prefix": self.bindings[request.version].prefix, "reference": request.context.reference_source,
                "candidate": request.source, "max_heartbeats": self.max_heartbeats,
                "candidate_first": self.branch_order == "candidate-first",
            }, timeout=self.timeout, **({"isolation": self.isolation} if self.isolation is not None else {}))
            self.validate_request(request)  # Changes during execution invalidate the observation.
            if (data.get("schema") != "jevops-native-arena/v1" or data.get("request_id") != request.request_id
                    or data.get("target") != request.context.problem or data.get("measurement") != METHOD
                    or data.get("branch_order") != self.branch_order
                    or data.get("lean_version") != request.version.lean_tag.removeprefix("v")
                    or not re.fullmatch(r"[0-9a-f]{40}", data.get("lean_githash", ""))):
                raise ValueError("native report identity mismatch")
            report = data["report"]
            outcome = Outcome(report["outcome"])
            # Resource-limit diagnostics are not semantic counterexamples.
            if outcome == Outcome.REJECTED and any("maximum number of heartbeats" in d.get("message", "")
                                                   for d in report.get("diagnostics", [])):
                outcome = Outcome.TIMEOUT
            observed = {"measurement": METHOD, "lean_version": data["lean_version"],
                        "branch_order": self.branch_order,
                        "lean_githash": data["lean_githash"], "wall_ms": round((time.monotonic() - start) * 1000, 3),
                        "dependency_digest": request.context.dependency_digests[request.context.versions.index(request.version)],
                        "driver_sha256": source_hash(DRIVER.read_text()), "report": report}
            if self.isolation is not None:
                observed["execution_policy"] = self.isolation.policy
                observed["execution_identity"] = self.isolation_identity
            if outcome != Outcome.VERIFIED:
                return replace(empty, outcome=outcome, exit_code=code, reason=report.get("reason", ""),
                               observations_json=canonical_json(observed))
            for key in ("heartbeats", "raw_heartbeats", "reference_heartbeats", "reference_raw_heartbeats"):
                _units(report[key], key)
            if (report.get("type_preserved") is not True or report.get("target_absent_before") is not True
                    or report["heartbeats"] != report["raw_heartbeats"] // 1000
                    or report["reference_heartbeats"] != report["reference_raw_heartbeats"] // 1000):
                raise ValueError("native evidence mismatch")
            for key in ("axioms", "reference_axioms"):
                if not isinstance(report[key], list) or any(not isinstance(x, str) for x in report[key]):
                    raise ValueError("malformed native axiom report")
                if set(report[key]) - set(request.context.allowed_axioms) or "sorryAx" in report[key]:
                    return replace(empty, outcome=Outcome.ERROR if key == "reference_axioms" else Outcome.REJECTED,
                                   exit_code=code, reason=key + "_policy", observations_json=canonical_json(observed))
            if (request.version == request.context.versions[0] and request.context.reference_heartbeats is not None
                    and report["reference_heartbeats"] != request.context.reference_heartbeats):
                return replace(empty, reason="reference_heartbeat_calibration_drift",
                               observations_json=canonical_json(observed))
            axiom_text = f"'{request.context.problem}' depends on axioms: [{', '.join(report['axioms'])}]"
            return replace(empty, outcome=Outcome.VERIFIED, type_preserved=True, exit_code=code,
                           axiom_output=axiom_text, heartbeats=report["heartbeats"],
                           observations_json=canonical_json(observed))
        except (TimeoutError, subprocess.TimeoutExpired):
            return replace(empty, outcome=Outcome.TIMEOUT, reason="native_wall_timeout")
        except IsolationUnavailable as exc:
            return replace(empty, outcome=Outcome.UNAVAILABLE, reason=str(exc)[:500])
        except Exception as exc:
            return replace(empty, reason=f"{type(exc).__name__}: {str(exc)[:500]}")


def readiness(records: list[dict], projects: list[dict], elan_home: Path) -> dict:
    """Read-only inventory; installed compiler != available dependencies or proof."""
    if not records or len({r["name"] for r in records}) != len(records):
        raise ValueError("nonempty unique corpus required")
    if not isinstance(projects, list) or any(not isinstance(p, dict) for p in projects):
        raise ValueError("projects must be an array of explicit bindings")
    rows = []
    for record in records:
        for version in record["version_info"]:
            for tag, commit in version.items():
                gaps = []
                try:
                    pinned_lean(elan_home, tag)
                except CapabilityGap as exc:
                    gaps.append(str(exc))
                matches = [p for p in projects if (p.get("repository"), p.get("lean_tag"), p.get("git_commit")) ==
                           (record.get("url"), tag, commit)]
                if len(matches) != 1:
                    gaps.append("prepared_project_binding_missing_or_ambiguous")
                elif not gaps:
                    try:
                        project_binding(record, VersionPin(tag, commit), matches[0], elan_home)
                    except (ValueError, OSError, subprocess.SubprocessError) as exc:
                        gaps.append(str(exc))
                rows.append({"name": record["name"], "lean_tag": tag, "git_commit": commit,
                             "status": "UNAVAILABLE" if gaps else "UNMEASURED", "capability_gaps": gaps,
                             "dependencies_verified": False, "baseline_compiles": None})
    return {"schema": "jevops-arena-native-readiness/v1", "required_version_checks": len(rows),
            "completed_version_checks": 0, "official_score": None, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--readiness", action="store_true")
    mode.add_argument("--baseline", action="store_true", help="explicit local execution of trusted pinned projects")
    mode.add_argument("--smoke", action="store_true", help="real Lean on a small non-Arena theorem")
    parser.add_argument("--elan-home", type=Path, default=Path.home() / ".elan")
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--projects", type=Path, help="JSON array of explicit read-only project bindings")
    source.add_argument("--state-root", type=Path, help="read-only inventory of an explicit track1-lake harness cache")
    parser.add_argument("--output", type=Path, help="also save JSON to a new file; refuses overwriting evidence")
    parser.add_argument("--tag", default="v4.26.0", help="smoke only; never substitute for corpus pins")
    parser.add_argument("--max-processes", type=int, default=0, help="zero executes no Lean processes")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--isolation", choices=("trusted-local", "docker"), default="trusted-local")
    parser.add_argument("--docker-socket", type=Path, help="explicit caller-owned local rootless Docker socket")
    parser.add_argument("--docker-image-id", help="explicit existing Linux sha256 image ID; never pulled")
    args = parser.parse_args()
    isolation = None
    try:
        if args.isolation == "docker":
            if args.docker_socket is None or args.docker_image_id is None:
                raise ValueError("docker isolation requires --docker-socket and --docker-image-id")
            isolation = DockerIsolation(args.docker_socket, args.docker_image_id)
        elif args.docker_socket is not None or args.docker_image_id is not None:
            raise ValueError("Docker options require explicit --isolation docker")
    except (OSError, ValueError, IsolationUnavailable) as exc:
        parser.error(str(exc))
    _units(args.max_processes, "max_processes")
    if args.output and args.output.exists():
        parser.error("--output must be a new evidence file")
    if args.smoke and (args.projects or args.state_root):
        parser.error("project inputs do not apply to the non-Arena smoke test")
    if args.smoke:
        pin = VersionPin(args.tag, "local-stdlib-smoke")
        statement = "theorem arena_smoke (h : True) : True"
        record = {"name": "arena_smoke", "statement": statement,
                  "src": statement + " := by\n  have redundant : True := h\n  exact redundant",
                  "version_info": [{pin.lean_tag: pin.git_commit}]}
        binding = ProjectBinding(pin, pinned_lean(args.elan_home, args.tag), Path.cwd(), "", project_backed=False)
        verifier = NativeLeanVerifier({pin: binding}, max_processes=args.max_processes, timeout=args.timeout,
                                      isolation=isolation)
        context = verifier.context(record)
        calibrated, baseline = verifier.calibrate(context)
        result = None
        candidate_source = statement + " := by exact h"
        if calibrated is not None:
            evaluator = verifier.evaluator(calibrated, max_calls=max(0, args.max_processes - verifier.processes))
            result = evaluator.evaluate(candidate_source).to_dict()
        report = {"schema": "jevops-arena-native-smoke/v1", "evidence_mode": "local_lean",
                  "arena_problem": False, "official_score": None, "worker_metric_parity": "UNCONFIRMED",
                  "processes": verifier.processes, "live_model_calls": 0,
                  "reference_source": record["src"], "candidate_source": candidate_source,
                  "reference_tokens": context.reference_length,
                  "baseline_context": asdict(context), "calibrated_context": asdict(calibrated) if calibrated else None,
                  "baseline": asdict(baseline), "candidate": result}
    else:
        records = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
        projects = (discover_projects(records, args.state_root) if args.state_root else
                    json.loads(args.projects.read_text()) if args.projects else [])
        report = readiness(records, projects, args.elan_home)
        report["projects"] = projects
        report["corpus_sha256"] = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
        if args.baseline:
            remaining = args.max_processes
            reader = Fingerprinter()  # Explicit per-run hash cache, never cached verification.
            for row in report["rows"]:
                if row["status"] == "UNAVAILABLE":
                    continue
                if not remaining:
                    row["status"] = "BUDGET_EXHAUSTED"
                    continue
                record = next(r for r in records if r["name"] == row["name"])
                pin = VersionPin(row["lean_tag"], row["git_commit"])
                project = next(p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                               (record.get("url"), pin.lean_tag, pin.git_commit))
                try:
                    binding = project_binding(record, pin, project, args.elan_home)
                    verifier = NativeLeanVerifier({pin: binding}, max_processes=1, timeout=args.timeout,
                                                  fingerprinter=reader, isolation=isolation)
                    per_version = {**record, "version_info": [{pin.lean_tag: pin.git_commit}]}
                    context = verifier.context(per_version)
                    receipt = verifier(VerificationRequest(context, record["src"], pin))
                    remaining -= verifier.processes
                    row.update(status=receipt.outcome.value, receipt=asdict(receipt), context=asdict(context),
                               context_id=context.context_id,
                               baseline_compiles=True if receipt.outcome == Outcome.VERIFIED else None)
                    row["dependencies_verified"] = receipt.outcome == Outcome.VERIFIED
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    row.update(status="ERROR", reason=str(exc)[:500])
            report["processes"] = args.max_processes - remaining
            report["completed_version_checks"] = sum(r["status"] in {"VERIFIED", "REJECTED"} for r in report["rows"])
            report["measurement"] = METHOD
            report["local_combined_pct"] = None  # Calibration report, never mix published and native metrics.
            report["worker_metric_parity"] = "UNCONFIRMED"
            report["fingerprint_file_reads"] = reader.reads
            report["fingerprint_stat_hits"] = reader.stat_hits
        report["live_model_calls"] = 0
    encoded = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        with args.output.open("x") as stream:
            stream.write(encoded + "\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
