"""Bounded, all-pin premise extraction from trusted target-free Lean prefixes.

Not a proof checker, provenance oracle, whole-library crawler or measurement.
Family/split metadata is operator-owned; no candidate proof is elaborated here.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .arena import VerificationRequest, content_hash, source_hash
from .arena_isolation import capture_process
from .arena_lean import CORPUS, DRIVER, MAX_PREFIX, NativeLeanVerifier, project_binding
from .arena_providers import strict_json, _fields
from .lean import VersionPin
from .premise_search import Premise, PremiseIndex, PremiseScope, PremiseSignature, bounded_int, premise_name
from .proof_trust import STANDARD_AXIOMS

EXPORTER = Path(__file__).with_name("lean") / "ArenaPremises.lean"
SCHEMA = "jevops-native-premise-inventory/v1"
STAGE_SCHEMA = "jevops-native-premises-stage/v1"
SIGNATURE_STAGE_SCHEMA = "jevops-native-premises-stage/v2"
MARKER = "JEVOPS_PREMISES:"
MAX_IO = 8 * 1024 * 1024
ENTRY_FAILURES = frozenset({"MISSING", "PRIVATE", "OPEN_TYPE", "TYPE_BUDGET",
                            "dependency_budget", "audit_missing", "audit_mismatch"})


@dataclass(frozen=True)
class PremiseOrigin:
    name: str
    origin: str
    split: str

    def __post_init__(self):
        # Share the existing metadata contract; type text is always extracted.
        Premise(self.name, "Prop", self.origin, self.split)


def driver_source() -> str:
    source, tail = DRIVER.read_text(), EXPORTER.read_text()
    boundary = "\nend JevOpsArena\n"
    if (not source.startswith("import Lean\n") or source.count(boundary) != 1
            or not tail.startswith("import Lean\n")):
        raise ValueError("unsupported trusted inventory library layout")
    return source.split(boundary)[0] + boundary + tail[len("import Lean\n"):]


def parse_stage(output: bytes) -> dict:
    if type(output) is not bytes or len(output) > MAX_IO:
        raise ValueError("inventory output byte budget")
    rows = [line[len(MARKER):] for line in output.decode().splitlines() if line.startswith(MARKER)]
    if len(rows) != 1:
        raise ValueError("exactly one inventory envelope required")
    return strict_json(rows[0], limit=MAX_IO)


def _dependency_names(value, limit):
    # Internal/private dependency names need not fit the public nomination grammar.
    if (type(value) is not list or len(value) > limit
            or any(type(n) is not str or not 0 < len(n.encode()) <= 1024 for n in value)
            or len(set(value)) != len(value)):
        raise ValueError("bounded unique native dependency names required")


def validate_stage(value, payload, pin):
    _fields(value, "schema request_sha256 target lean_version lean_githash report")
    if (payload["schema"] not in {STAGE_SCHEMA, SIGNATURE_STAGE_SCHEMA}
            or value["schema"] != payload["schema"] or value["request_sha256"] != payload["request_sha256"]
            or value["target"] != payload["target"] or value["lean_version"] != pin.lean_tag.removeprefix("v")
            or type(value["lean_githash"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", value["lean_githash"])):
        raise ValueError("foreign inventory envelope")
    report = value["report"]
    if type(report) is not dict or report.get("status") != "EXPORTED":
        raise ValueError("native inventory unavailable")
    _fields(report, "status entries")
    entries = report["entries"]
    if type(entries) is not list or len(entries) != len(payload["names"]):
        raise ValueError("incomplete inventory rows")
    for expected, row in zip(payload["names"], entries):
        if type(row) is not dict or row.get("name") != expected:
            raise ValueError("inventory row binding mismatch")
        if row.get("status") == "AVAILABLE":
            typed = payload["schema"] == SIGNATURE_STAGE_SCHEMA
            _fields(row, "name status type_text dependencies axioms" + (" signature" if typed else ""))
            if typed and row["signature"] is not None:
                signature = PremiseSignature.from_dict(row["signature"])
                if signature.name != expected:
                    raise ValueError("signature declaration mismatch")
            Premise(expected, row["type_text"], "native-extraction", "library")
            for key in ("dependencies", "axioms"):
                _dependency_names(row[key], payload["dependency_budget"])
            if expected not in row["dependencies"] or not set(row["axioms"]) <= set(row["dependencies"]):
                raise ValueError("incomplete native dependency closure")
        else:
            _fields(row, "name status")
            if row["status"] not in ENTRY_FAILURES:
                raise ValueError("unknown native inventory status")
    return value


class NativePremiseExporter:
    """Single-owner exporter; reserve every pin before starting any process.

    Uses the guard's dependency/context validation and optional Docker profile.
    Its process budget is separate from the guard's proof-verification budget.
    No result cache. An injected runner is labeled FIXTURE_ONLY, never native.
    """
    def __init__(self, guard: NativeLeanVerifier, *, max_processes: int = 0,
                 total_seconds: float = 120, dependency_budget: int = 2048, runner=None,
                 include_signatures: bool = False):
        if type(guard) is not NativeLeanVerifier:
            raise ValueError("explicit native verifier guard required")
        bounded_int(max_processes, 0, 256)
        bounded_int(dependency_budget, 1, 4096)
        if type(total_seconds) not in (int, float) or not math.isfinite(total_seconds) or not 0 < total_seconds <= 300:
            raise ValueError("bounded positive total deadline required")
        if runner is not None and not callable(runner):
            raise ValueError("fixture runner must be callable")
        if type(include_signatures) is not bool:
            raise ValueError("explicit Boolean signature mode required")
        self.include_signatures = include_signatures
        self.guard, self.max_processes = guard, max_processes
        self.total_seconds, self.dependency_budget, self.runner = total_seconds, dependency_budget, runner
        self.reserved = self.attempts = 0
        self.source = driver_source()
        self.code_identity = self._code_identity()

    def _code_identity(self):
        return content_hash({"driver": source_hash(driver_source()),
            "adapter": source_hash(Path(__file__).read_text()),
            "contracts": {name: source_hash(Path(__file__).with_name(name).read_text())
                          for name in ("premise_search.py", "arena_providers.py")}})

    def _check(self, context, deadline):
        for pin in context.versions:
            self.guard.validate_request(VerificationRequest(context, context.reference_source, pin))
        if self._code_identity() != self.code_identity:
            raise ValueError("inventory implementation changed")
        if time.monotonic() >= deadline:
            raise TimeoutError("inventory deadline")

    def _run(self, binding, payload, deadline):
        self.attempts += 1
        if self.runner is not None:
            return self.runner(binding, payload)
        with ExitStack() as stack:
            scratch = stack.enter_context(tempfile.TemporaryDirectory(prefix="jevops-premises-"))
            driver = Path(scratch) / "ArenaPremises.lean"
            driver.write_text(self.source)
            driver.chmod(0o444)
            stdin = stack.enter_context(tempfile.TemporaryFile())
            stdin.write(json.dumps(payload, ensure_ascii=False).encode()); stdin.seek(0)
            command = [str(binding.lean), "--run", str(driver)]
            env = {"PATH": f"{binding.lean.parent}:/usr/bin:/bin", "HOME": scratch, "TMPDIR": scratch,
                   "LEAN_PATH": os.pathsep.join(map(str, binding.search_paths)), "LEAN_NUM_THREADS": "1"}
            if self.guard.isolation is not None:
                command, env = stack.enter_context(self.guard.isolation.launch(binding.lean,
                    binding.search_paths, driver, scratch=scratch, deadline=deadline))
            out, err, code = capture_process(command, stdin=stdin, cwd=scratch, env=env,
                timeout=min(self.guard.timeout, deadline - time.monotonic()), output_limit=MAX_IO)
            if code:
                raise ValueError("native inventory driver failed")
            return parse_stage(out)

    def export(self, record, declarations: tuple[PremiseOrigin, ...], *,
               excluded_names: tuple[str, ...] = (), excluded_origins: tuple[str, ...] = ()) -> dict:
        deadline = time.monotonic() + self.total_seconds
        if (type(declarations) is not tuple or not 1 <= len(declarations) <= 64
                or any(type(d) is not PremiseOrigin for d in declarations)
                or len({d.name for d in declarations}) != len(declarations)):
            raise ValueError("one to 64 unique typed premise declarations required")
        context = self.guard.context(record)
        premise_name(context.problem)
        spec = tuple(sorted(declarations, key=lambda d: d.name))
        scope = PremiseScope(content_hash(record), context.context_id, (), excluded_names, excluded_origins)
        for pin in context.versions:
            if len(self.guard.bindings[pin].prefix.encode()) > MAX_PREFIX:
                raise ValueError("prefix byte budget")
        report = {"schema": SCHEMA, "status": "INCOMPLETE", "record_sha256": scope.record_sha256,
            "environment_sha256": context.context_id, "exporter_sha256": self.code_identity,
            "evidence_mode": "fixture" if self.runner is not None else "trusted_local_native",
            "os_sandbox": self.guard.isolation is not None,
            "metadata": [asdict(d) for d in spec], "excluded_names": list(excluded_names),
            "excluded_origins": list(excluded_origins), "stages": [], "exclusions": [],
            "inventory": None, "scope": None, "proof_verified": False, "training_enabled": False,
            "promoted": False, "official_score": None, "reserved_processes": 0, "attempted_processes": 0}
        if self.include_signatures:
            report.update(schema="jevops-native-premise-inventory/v2", signature_exclusions=[])
        if self.reserved + len(context.versions) > self.max_processes:
            return {**report, "reason": "PROCESS_BUDGET"}
        self.reserved += len(context.versions)
        report["reserved_processes"] = len(context.versions)
        start = self.attempts
        try:
            self._check(context, deadline)
            for pin in context.versions:
                self._check(context, deadline)
                binding = self.guard.bindings[pin]
                payload = {"schema": SIGNATURE_STAGE_SCHEMA if self.include_signatures else STAGE_SCHEMA,
                    "context_sha256": context.context_id,
                    "target": context.problem, "prefix": binding.prefix, "names": [d.name for d in spec],
                    "max_heartbeats": self.guard.max_heartbeats, "dependency_budget": self.dependency_budget,
                    "exporter_sha256": self.code_identity, "pin": pin.to_dict()}
                payload["request_sha256"] = content_hash(payload)
                value = validate_stage(self._run(binding, payload, deadline), payload, pin)
                self._check(context, deadline)
                report["stages"].append({"pin": pin.to_dict(), "evidence": value})
            self._merge(report, scope, spec, context.problem)
            self._check(context, deadline)
            report["status"] = "FIXTURE_ONLY" if self.runner is not None else "INVENTORY_ONLY"
        except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
            # Partial or stale observations never produce an admission inventory.
            report.update(reason="EXTRACTION_FAILED", inventory=None, scope=None)
        report["attempted_processes"] = self.attempts - start
        return report

    def _merge(self, report, scope, spec, target):
        denied = {target, *scope.excluded_names,
                  *(d.name for d in spec if d.split not in ("library", "train") or d.origin in scope.excluded_origins)}
        rows = [s["evidence"]["report"]["entries"] for s in report["stages"]]
        accepted = []
        for i, declaration in enumerate(spec):
            versions = [entries[i] for entries in rows]
            reason = ""
            if declaration.name in denied:
                reason = "EXCLUDED_PROVENANCE"
            elif any(row["status"] != "AVAILABLE" for row in versions):
                reason = "NOT_AVAILABLE_ON_ALL_PINS"
            elif any(denied.intersection(row["dependencies"]) for row in versions):
                reason = "EXCLUDED_DEPENDENCY"
            elif any(set(row["axioms"]) - STANDARD_AXIOMS for row in versions):
                reason = "AXIOM_POLICY"
            elif len({row["type_text"] for row in versions}) != 1:
                reason = "TYPE_TEXT_DIFFERS"
            if reason:
                report["exclusions"].append({"name": declaration.name, "reason": reason})
            else:
                accepted.append((declaration, versions))
        names = {d.name for d, _ in accepted}
        entries = tuple(Premise(d.name, versions[0]["type_text"], d.origin, d.split,
            dependencies=tuple(sorted((set().union(*(set(r["dependencies"]) for r in versions)) & names) - {d.name})))
            for d, versions in accepted)
        signatures = []
        if self.include_signatures:
            for d, versions in accepted:
                if any(r["signature"] is None for r in versions):
                    report["signature_exclusions"].append({"name": d.name, "reason": "UNSUPPORTED_ON_A_PIN"})
                elif len({content_hash(r["signature"]) for r in versions}) != 1:
                    report["signature_exclusions"].append({"name": d.name, "reason": "SIGNATURE_DIFFERS"})
                else:
                    signatures.append(PremiseSignature.from_dict(versions[0]["signature"]))
        index = PremiseIndex(entries, environment_sha256=scope.environment_sha256, signatures=tuple(signatures))
        scope = PremiseScope(scope.record_sha256, scope.environment_sha256, tuple(sorted(names)),
                             scope.excluded_names, scope.excluded_origins)
        report["inventory"] = {"schema": "jevops-premise-index/v1", "environment_sha256": index.environment_sha256,
                               "premises": [asdict(p) for p in entries]}
        if self.include_signatures:
            report["inventory"].update(schema="jevops-premise-index/v2", signatures=[s.to_dict() for s in signatures])
        report["scope"] = {"schema": "jevops-premise-scope/v1", **asdict(scope)}


def write_inventory(report: dict, directory: Path) -> None:
    """Generate consumer-compatible files; never overwrite earlier evidence."""
    if report.get("status") != "INVENTORY_ONLY" or not report.get("inventory") or not report.get("scope"):
        raise ValueError("completed native extraction required; fixtures/partial reports cannot publish")
    directory.mkdir(parents=True, exist_ok=False)
    for name, value in (("inventory", report["inventory"]), ("scope", report["scope"]), ("report", report)):
        with (directory / f"{name}.json").open("x") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")


def _read_input(path: Path):
    with path.open("rb") as stream:
        return strict_json(stream.read(MAX_IO + 1), limit=MAX_IO)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--projects", type=Path, required=True)
    parser.add_argument("--nominees", type=Path, required=True,
                        help="JSON array of explicit name/origin/split metadata; at most 64")
    parser.add_argument("--elan-home", type=Path, default=Path.home() / ".elan")
    parser.add_argument("--excluded-name", action="append", default=[])
    parser.add_argument("--excluded-origin", action="append", default=[])
    parser.add_argument("--trusted-local", action="store_true", required=True,
                        help="acknowledge trusted project metaprograms; this CLI is not an OS sandbox")
    parser.add_argument("--max-processes", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=120, help="whole extraction deadline in seconds")
    parser.add_argument("--dependency-budget", type=int, default=2048)
    parser.add_argument("--include-signatures", action="store_true",
                        help="opt-in V2 raw Expr telescope/head features, not applicability certificates")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output_dir.exists() or args.output_dir.is_symlink():
            raise ValueError("output directory must be new")
        bounded_int(args.max_processes, 0, 256)
        bounded_int(args.dependency_budget, 1, 4096)
        if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
            raise ValueError("bounded positive total deadline required")
        with args.corpus.open("rb") as stream:
            raw = stream.read(MAX_IO + 1)
        if len(raw) > MAX_IO:
            raise ValueError("corpus byte budget")
        records = [strict_json(line, limit=MAX_IO) for line in raw.splitlines() if line.strip()]
        matches = [r for r in records if r["name"] == args.problem]
        if len(matches) != 1:
            raise ValueError("exactly one matching benchmark required")
        record = matches[0]
        rows = _read_input(args.nominees)
        if type(rows) is not list or not 1 <= len(rows) <= 64:
            raise ValueError("one to 64 nominees required")
        for row in rows:
            _fields(row, "name origin split")
        nominees = tuple(PremiseOrigin(**row) for row in rows)
        if len({d.name for d in nominees}) != len(nominees):
            raise ValueError("duplicate nominees")
        # Known corpus targets cannot be mined as premises for each other.
        excluded = tuple(sorted({r["name"] for r in records} | set(args.excluded_name)))
        origins = tuple(sorted(set(args.excluded_origin)))
        PremiseScope("0" * 64, "0" * 64, (), excluded, origins)
        projects = _read_input(args.projects)
        if type(projects) is not list or len(projects) > 256 or any(type(p) is not dict for p in projects):
            raise ValueError("bounded project binding list required")
        bindings = {}
        pins = [VersionPin(tag, commit) for row in record["version_info"] for tag, commit in row.items()]
        if not pins or len(set(pins)) != len(pins):
            raise ValueError("unique required pins needed")
        for pin in pins:
            matches = [p for p in projects if (p.get("repository"), p.get("lean_tag"), p.get("git_commit")) ==
                       (record.get("url"), pin.lean_tag, pin.git_commit)]
            if len(matches) != 1:
                raise ValueError("exactly one project binding per required pin")
            bindings[pin] = project_binding(record, pin, matches[0], args.elan_home)
        guard = NativeLeanVerifier(bindings, max_processes=0, timeout=args.timeout)
        exporter = NativePremiseExporter(guard, max_processes=args.max_processes,
            total_seconds=args.timeout, dependency_budget=args.dependency_budget,
            include_signatures=args.include_signatures)
        report = exporter.export(record, nominees, excluded_names=excluded, excluded_origins=origins)
        if report["status"] == "INVENTORY_ONLY":
            write_inventory(report, args.output_dir)
        else:
            # Keep failed and zero-budget experiments visible, without usable inputs.
            args.output_dir.mkdir(parents=True, exist_ok=False)
            with (args.output_dir / "report.json").open("x") as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write("\n")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": report["status"], "attempted_processes": report["attempted_processes"],
        "admitted": len(report["inventory"]["premises"]) if report["inventory"] else 0,
        "output_dir": str(args.output_dir), "proof_verified": False}))
    return 0 if report["status"] == "INVENTORY_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
