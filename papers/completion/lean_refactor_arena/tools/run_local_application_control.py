#!/usr/bin/env python3
"""Installed-Lean search-to-term control. Plan only unless --execute is supplied.

No downloads, builds, model calls, credentials or Arena performance claims.
One process at a time; explicit prefix fixtures are not real project benchmarks.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from jevops.arena import VerificationRequest, content_hash, reference_tokens
from jevops.arena_lean import NativeLeanVerifier, ProjectBinding, pinned_lean
from jevops.arena_local import ArenaLocalRuntime
from jevops.arena_providers import propose_local_batch
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope

STATEMENT = "theorem sample (p : Prop) (h : p) : p ∨ True"
SOURCE = STATEMENT + " := by\n  exact Or.inl (id h)\n"
PREFIX = "theorem library_step {p : Prop} (h : p) : p ∨ True := Or.inl h\nnamespace Suite\n"


def run(tags, *, execute=False, max_processes=0):
    if (type(max_processes) is not int or not 0 <= max_processes <= 16
            or not 1 <= len(tags) <= 4 or len(set(tags)) != len(tags)):
        raise ValueError("bounded distinct pins and integer process budget required")
    pins = tuple(VersionPin(tag, "synthetic-application-control/v1") for tag in tags)
    ceiling = 4 * len(pins)  # capture + application/roundtrip + reference + extracted source
    report = {"schema": "jevops-application-control/v1", "status": "PLANNED", "pins": tags,
        "process_ceiling": ceiling, "max_processes": max_processes,
        "task_kind": "synthetic-mechanism-control-not-arena-benchmark",
        "native_processes": 0, "model_calls": 0, "api_cost": None, "official_score": None,
        "promoted": False, "runs": []}
    if not execute:
        return report
    if max_processes < ceiling:
        raise ValueError("reserve the entire control ceiling before native work")
    # Resolve all explicitly installed executables before running any work.
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    compilers = {pin: pinned_lean(elan, pin.lean_tag) for pin in pins}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="jevops-application-control-") as scratch:
        record = {"name": "Suite.sample", "statement": STATEMENT, "src": SOURCE,
                  "version_info": [{p.lean_tag: p.git_commit} for p in pins]}
        bindings = {p: ProjectBinding(p, compilers[p], Path(scratch), PREFIX, project_backed=False) for p in pins}
        verifier = NativeLeanVerifier(bindings, max_processes=2 * len(pins), timeout=60)
        runtime = ArenaLocalRuntime(verifier, record, max_processes=2 * len(pins))
        env = runtime.context.context_id
        index = PremiseIndex((Premise("library_step", "∀ {p : Prop}, p → p ∨ True", "explicit-control-prefix"),),
                             environment_sha256=env)
        scope = PremiseScope(content_hash(record), env, ("library_step",))
        for pin in pins:
            reference = verifier(VerificationRequest(runtime.context, SOURCE, pin))
            row = {"pin": pin.to_dict(), "reference": asdict(reference)}
            report["runs"].append(row)
            if reference.outcome.value != "VERIFIED":
                break
            observed = runtime.capture(pin)
            row["capture"] = observed
            if not observed["ok"]:
                break
            capture = observed["capture"]
            row["baseline_drafts"] = propose_local_batch(record, capture, index, scope, cap=2)
            row["discovery"] = runtime.discover_batch(pin, capture, index, scope, cap=1,
                max_events=1, max_applications=1, span_order="headroom-v1")
            drafts = row["discovery"]["drafts"]
            if len(drafts) != 1:
                break
            draft = drafts[0]
            row["candidate"] = asdict(verifier(VerificationRequest(runtime.context, draft["source"], pin)))
            row.update(source_tokens=reference_tokens(SOURCE, STATEMENT),
                       candidate_tokens=reference_tokens(draft["source"], STATEMENT))
        report.update(native_processes=runtime.attempts + verifier.processes,
                      wall_seconds=round(time.monotonic() - started, 4))
    successful = (len(report["runs"]) == len(pins) and all(
        row.get("candidate", {}).get("outcome") == "VERIFIED" and row["candidate_tokens"] < row["source_tokens"]
        for row in report["runs"]))
    report["status"] = "CONTROL_PASSED" if successful else "INCOMPLETE"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", nargs="+", default=["v4.26.0", "v4.29.1"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-processes", type=int, default=0)
    parser.add_argument("--output", type=Path, help="new JSON artifact; existing files are refused")
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("output already exists")
    try:
        report = run(args.tags, execute=args.execute, max_processes=args.max_processes)
        text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output is not None:
            with args.output.open("x") as stream:
                stream.write(text)
        print(text if args.output is None else json.dumps({k: report[k] for k in
            ("status", "native_processes", "official_score")}))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0 if report["status"] in {"PLANNED", "CONTROL_PASSED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
