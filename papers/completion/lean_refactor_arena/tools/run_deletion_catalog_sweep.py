#!/usr/bin/env python3
"""Explicit, deletion-only catalog feasibility checks; no model or build calls.

Default: emit a reviewable plan. Execution requires a pinned source snapshot,
reviewed catalog hash, capped preparation volume and exclusive build lock.
This is trusted-local native execution, NOT an OS sandbox or a score trial.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from jevops.arena import ArenaEvaluator, Outcome, content_hash, reference_tokens, source_hash
from jevops.lean import VersionPin
from jevops.proof_slicing import apply_deletion_span, deletion_spans

SCHEMA = "jevops-deletion-catalog-sweep/v1"


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def make_plan(record, *, max_calls=0):
    if type(max_calls) is not int or not 0 <= max_calls <= 520:
        raise ValueError("integer request budget required: 0..520")
    pins = [VersionPin(tag, commit) for row in record["version_info"] for tag, commit in row.items()]
    if not 1 <= len(pins) <= 8 or len({p.lean_tag for p in pins}) != len(pins):
        raise ValueError("one to eight unique version pins required")
    catalog = {"schema": "jevops-source-bound-deletion-catalog/v1", "record_sha256": content_hash(record),
        "source_sha256": source_hash(record["src"]), "entries": [
            {"edit_id": i, "delete_lines": list(span)} for i, span in enumerate(
                deletion_spans(record["src"], record["statement"]), 1)]}
    if not catalog["entries"]:
        raise ValueError("no supported deletion actions")
    candidates, by_source = [], {}
    for entry in catalog["entries"]:
        source = apply_deletion_span(record["src"], record["statement"], *entry["delete_lines"],
                                     expected_source_sha256=catalog["source_sha256"])
        if source not in by_source:
            candidate = {"label": f"edit-{entry['edit_id']:02d}", "source": source,
                "source_sha256": source_hash(source), "tokens": reference_tokens(source, record["statement"]),
                "edit_ids": []}
            by_source[source] = candidate
            candidates.append(candidate)
        by_source[source]["edit_ids"].append(entry["edit_id"])
    plan = {"schema": SCHEMA, "record": record, "catalog": catalog,
        "catalog_sha256": content_hash(catalog), "candidates": candidates,
        "pin_order": [asdict(p) for p in sorted(pins, key=lambda p: p.lean_tag)],
        "max_requests": max_calls, "exhaustive_request_ceiling": (len(candidates) + 1) * len(pins),
        "protocol": {"controls_per_pin": 1, "attempts_per_source_per_pin": 1,
            "stop_candidate_after_non_verified": True, "stop_on_control_failure": True,
            "branch_order": "reference-first", "timeout_seconds": 90, "cache_entries": 0,
            "resume": False, "compose_edits": False, "fresh_native_process_required": True},
        "execution": "trusted-local-private-scratch-not-OS-sandbox",
        "task_split": "exploratory-public-warmup-not-held-out",
        "model_calls": 0, "training": False, "promotion": False, "official_score": None}
    return {**plan, "plan_id": content_hash(plan)}


def run_sweep(plan, directory, factory, *, check_resources, evidence_mode="local_lean"):
    """Single-owner, no resume; injected verifier factory for offline tests.

    Plan reservation prevents re-execution even after interruption. Each charged
    request is fsynced BEFORE work, then its checked receipt is fsynced. To retry
    an interruption, explicitly start a new epoch/directory; never count the old
    reservation as successful evidence. Caller holds the preparation lock.
    """
    if plan != make_plan(plan["record"], max_calls=plan["max_requests"]):
        raise ValueError("plan changed: exact current catalog and protocol required")
    if evidence_mode not in {"local_lean", "offline_fixture"}:
        raise ValueError("explicit evidence mode required")
    check_resources()
    directory.mkdir()  # No overwriting or resuming previous work.
    save(directory / "plan.json", plan)
    rows, contexts, stopped = [], {}, set()
    requests = processes = 0
    control_failed = False
    start = time.monotonic()
    control = {"label": "control", "source": plan["record"]["src"],
               "source_sha256": plan["catalog"]["source_sha256"]}
    for pin_data in plan["pin_order"]:
        pin = VersionPin(**pin_data)
        verifier = evaluator = None
        setup_error = None
        for candidate in [control, *plan["candidates"]]:
            label = candidate["label"]
            row = {"pin": pin_data, "label": label, "source_sha256": candidate["source_sha256"]}
            if control_failed or label in stopped:
                row["status"] = "NOT_RUN_AFTER_NON_SUCCESS"
            elif requests >= plan["max_requests"]:
                row["status"] = "BUDGET_EXHAUSTED"
            else:
                check_resources()
                if verifier is None and setup_error is None:
                    try:
                        print(json.dumps({"native_setup": pin.lean_tag}), flush=True)
                        verifier = factory(pin)
                        if verifier.processes != 0:
                            raise ValueError("fresh verifier required")
                        selected = {**plan["record"], "version_info": [{pin.lean_tag: pin.git_commit}]}
                        context = verifier.context(selected)
                        if (context.versions != (pin,) or context.problem != selected["name"] or
                                context.statement != selected["statement"] or
                                context.reference_source != selected["src"]):
                            raise ValueError("verifier context mismatch")
                        contexts[pin.lean_tag] = asdict(context)
                        save(directory / f"context-{pin.lean_tag}.json", asdict(context))
                        evaluator = ArenaEvaluator(context, verifier, max_calls=1 + len(plan["candidates"]),
                            evidence_mode=evidence_mode, max_cache_entries=0,
                            context_validator=verifier.validate_request)
                    except Exception as exc:
                        setup_error = f"{type(exc).__name__}: {str(exc)[:400]}"
                if setup_error:
                    row.update(status="ERROR", reason="setup: " + setup_error)
                else:
                    from jevops.arena import VerificationRequest
                    request = VerificationRequest(evaluator.context, candidate["source"], pin)
                    save(directory / f"request-{requests:03d}-reserved.json", {**row,
                        "plan_id": plan["plan_id"], "request_id": request.request_id,
                        "context_id": evaluator.context.context_id, "operation_units": 1})
                    requests += 1  # Reserve including transient failures; never retry here.
                    before, tick = verifier.processes, time.monotonic()
                    evaluation = evaluator.evaluate(candidate["source"])
                    used = verifier.processes - before
                    processes += used
                    receipts = evaluation.receipts
                    status = receipts[0].outcome.value if len(receipts) == 1 else "ERROR"
                    if status in {"VERIFIED", "REJECTED"} and used != 1:
                        status = "ERROR"  # A cached/non-native result is not a fresh check.
                    row.update(status=status, context_id=evaluator.context.context_id,
                        receipt=asdict(receipts[0]) if len(receipts) == 1 else None,
                        native_processes=used, wall_seconds=round(time.monotonic() - tick, 4))
                if row["status"] != "VERIFIED":
                    if label == "control":
                        control_failed = True
                    else:
                        stopped.add(label)
            rows.append(row)
            save(directory / f"row-{len(rows):03d}.json", row)
            print(json.dumps({k: row[k] for k in ("pin", "label", "status")}), flush=True)
    classified = []
    for candidate in plan["candidates"]:
        results = [r["status"] for r in rows if r["label"] == candidate["label"]]
        status = ("REJECTED" if "REJECTED" in results else
                  "ALL_PIN_VERIFIED" if results and all(s == "VERIFIED" for s in results) else "INCONCLUSIVE")
        classified.append({"label": candidate["label"], "edit_ids": candidate["edit_ids"],
            "source_sha256": candidate["source_sha256"], "tokens": candidate["tokens"], "status": status})
    complete = (not control_failed and all(r["status"] == "VERIFIED" for r in rows if r["label"] == "control")
                and all(c["status"] != "INCONCLUSIVE" for c in classified))
    report = {"schema": SCHEMA, "plan_id": plan["plan_id"], "catalog_sha256": plan["catalog_sha256"],
        "status": "CONTROL_FAILED" if control_failed else "COMPLETE" if complete else "INCOMPLETE",
        "evidence_mode": evidence_mode, "rows": rows, "contexts": contexts, "candidates": classified,
        "native_requests_reserved": requests, "native_processes": processes, "model_calls": 0,
        "reference_tokens": reference_tokens(control["source"], plan["record"]["statement"]),
        "all_pin_verified_candidates": [c["label"] for c in classified if c["status"] == "ALL_PIN_VERIFIED"],
        "wall_seconds_including_setup": round(time.monotonic() - start, 4),
        "request_wall_seconds": round(sum(r.get("wall_seconds", 0) for r in rows), 4),
        "paid_api_cost": None, "electricity_cost": None, "performance_selected": False,
        "promotion": False, "official_score": None}
    save(directory / "sweep.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", default="Core.InitsUpdatesComm")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--reviewed-catalog-sha256")
    parser.add_argument("--snapshot-manifest-sha256")
    parser.add_argument("--preparation-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--elan-home", type=Path)
    args = parser.parse_args()
    from jevops.arena_lean import CORPUS, NativeLeanVerifier, project_binding
    record = next(json.loads(line) for line in CORPUS.read_text().splitlines()
                  if line.strip() and json.loads(line)["name"] == args.problem)
    plan = make_plan(record, max_calls=args.max_requests)
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if (not all((args.snapshot_manifest_sha256, args.preparation_root, args.output, args.projects, args.elan_home))
            or args.reviewed_catalog_sha256 != plan["catalog_sha256"]):
        parser.error("execution requires source snapshot, reviewed catalog hash, preparation, output, projects and elan-home")
    from jevops.arena_prepare import exclusive, validate_volume
    from jevops.arena_snapshot import verify_snapshot
    from jevops.seals import Fingerprinter
    config = json.loads((args.preparation_root / "preparation.json").read_text())
    with exclusive(args.preparation_root / "single-build.lock"):
        mount = validate_volume(config)
        if not args.output.resolve().is_relative_to(mount) or args.output.is_symlink():
            raise ValueError("output must be inside capped volume")
        if not args.projects.resolve().is_relative_to(ROOT / "inputs"):
            raise ValueError("projects manifest must be captured in the source snapshot")
        binding = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
        if any(getattr(m, "__file__", None) and not Path(m.__file__).resolve().is_relative_to(ROOT)
               for n, m in sys.modules.items() if n == "jevops" or n.startswith("jevops.")):
            raise ValueError("JevOps import escaped source snapshot")
        projects = json.loads(args.projects.read_text())
        reader = Fingerprinter()

        def factory(pin):
            project = next(p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                           (record["url"], pin.lean_tag, pin.git_commit))
            return NativeLeanVerifier({pin: project_binding(record, pin, project, args.elan_home)},
                max_processes=1 + len(plan["candidates"]), timeout=plan["protocol"]["timeout_seconds"],
                fingerprinter=reader, branch_order=plan["protocol"]["branch_order"])

        report = run_sweep(plan, args.output, factory, check_resources=lambda: validate_volume(config))
        save(args.output / "source-binding.json", {"before": binding,
             "after": verify_snapshot(ROOT, args.snapshot_manifest_sha256)})
        print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "contexts", "candidates"}}))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
