"""Frozen solver comparisons; fresh objective-bound confirmation, no promotion.

Plan-only by default. Native execution requires a read-only source snapshot,
prepared exact pins, exclusive preparation lock and capped temporary storage.
"""
from dataclasses import asdict
import argparse
import json
import os
from pathlib import Path
import sys
import time

from .arena import VerificationRequest, content_hash, intake_error, source_hash
from .arena_lean import CORPUS, NativeLeanVerifier, project_binding
from .arena_local import ArenaLocalRuntime
from .arena_pareto import run_selection, selection_plan
from .arena_prepare import exclusive, validate_volume
from .arena_snapshot import verify_snapshot
from .arena_solver import LEGACY_MODES, SolverLimits
from .arena_trial import Candidate, ORDERS, _pins
from .seals import Fingerprinter

ROOT = Path(__file__).resolve().parents[1]
LIMITS = SolverLimits(max_calls=8, max_states=4, max_depth=2, max_sites=2, max_drafts=1)
SELECTION = dict(repetitions=2, confirmation_repetitions=3, seed=17,
                 selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=100)
COMPARISONS = ("legacy-v1", "balanced-v1", "aggregate-nomination-v1", "prefix-reference-v1")


def _incumbent(record, seed):
    return None if seed.source == record["src"] else Candidate("incumbent", seed.source, seed.provenance)


def make_plan(record, seed=None, *, comparison="legacy-v1"):
    if type(comparison) is not str or comparison not in COMPARISONS:
        raise ValueError("supported frozen comparison required")
    modes = LEGACY_MODES if comparison == "legacy-v1" else ("frontier-v1", "balanced-frontier-v1")
    draft_policy = "shortest-v1" if comparison == "legacy-v1" else "discovery-dual-first-v1"
    selection = dict(SELECTION)
    limits = LIMITS
    discovery_arms = None
    if comparison == "aggregate-nomination-v1":
        # Only final nomination differs. Re-run the same bounded search in
        # separate guards, so neither arm borrows the other's proof/call budget.
        modes = ("balanced-frontier-v1", "balanced-frontier-v1")
        draft_policy = None
        selection["selection_objective"] = "aggregate-local-v1"
        discovery_arms = [dict(label=label, mode="balanced-frontier-v1", draft_policy=policy)
            for label, policy in (("dual-first", "discovery-dual-first-v1"),
                                  ("aggregate", "discovery-aggregate-v1"))]
    elif comparison == "prefix-reference-v1":
        # A single bounded search, not a matched two-controller comparison.
        # The first supported solver site is determined by each checked source's
        # parser inventory, never by a profiler hint or a historical offset.
        modes = ("balanced-frontier-v1",)
        draft_policy = "discovery-reference-v1"
        limits = SolverLimits(max_calls=16, max_states=4, max_depth=2, max_sites=1, max_drafts=1)
        selection["selection_objective"] = "aggregate-local-v1"
        discovery_arms = [dict(label="prefix-reference", mode=modes[0], draft_policy=draft_policy)]
    seed = Candidate("original", record["src"], "unchanged original control") if seed is None else seed
    if (type(seed) is not Candidate or intake_error(seed.source, record["statement"])
            or intake_error(record["src"], record["statement"])):
        raise ValueError("typed fixed-envelope seed and reference required")
    pins = _pins(record)
    extra = int(_incumbent(record, seed) is not None)
    controls = (1 + extra) * len(pins)
    screen = (1 + extra + len(modes)) * len(pins) * 2 * selection["repetitions"]
    confirm = (2 + extra) * len(pins) * 2 * selection["confirmation_repetitions"]
    total = controls + len(modes) * limits.max_calls + screen + confirm
    if screen > 128 or confirm > 128 or total > 256:
        raise ValueError("pilot exceeds fixed process ceiling")
    plan = dict(schema="jevops-arena-solver-pilot/v1", record=record, seed=asdict(seed),
        modes=list(modes), comparison=comparison, nomination_policy=draft_policy,
        limits=asdict(limits), discovery_pin=pins[0].to_dict(),
        control_ceiling=controls, discovery_ceiling=len(modes)*limits.max_calls,
        selection_ceiling=screen+confirm, max_processes=total, selection=selection,
        runner_sha256=source_hash(Path(__file__).read_text()),
        task_split="exposed-public-warmup-not-held-out", stop_on_control_failure=True,
        draft_policy=f"one draft per arm using {draft_policy}; exact-source union; no post-result expansion",
        matched_discovery_call_ceiling=True, matched_elapsed_time=False,
        retries=0, resume=False, training_enabled=False, promoted=False, official_score=None)
    if discovery_arms is not None:
        plan.update(discovery_arms=discovery_arms,
            comparison_factor="final nomination only; identical bounded search and aggregate selection",
            draft_policy="one draft per declared arm; exact-source union; no post-result expansion",
            confirmation_scope="union-selected winner only; other arm nominees are screen-only")
    if comparison == "prefix-reference-v1":
        plan.update(comparison_factor="single first-site search; not a matched controller comparison",
            confirmation_scope="one reference-normalized nominee; fresh original/incumbent comparison",
            matched_discovery_call_ceiling=False)
    return json.loads(json.dumps({**plan, "plan_id":content_hash(plan)}))


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())


def run_pilot(plan, *, bindings, directory, max_processes, check_resources, evidence_mode="local_lean"):
    """Trusted in-process orchestration, never admission from a saved report."""
    if plan != make_plan(plan["record"], Candidate(**plan["seed"]), comparison=plan["comparison"]):
        raise ValueError("mutated or stale frozen solver plan")
    if type(max_processes) is not int or max_processes != plan["max_processes"]:
        raise ValueError("reserve the exact full process ceiling")
    if evidence_mode not in ("local_lean", "offline_fixture"):
        raise ValueError("explicit evidence mode required")
    plan = json.loads(json.dumps(plan))
    record, seed = plan["record"], Candidate(**plan["seed"])
    limits = SolverLimits(**plan["limits"])
    pins = _pins(record)
    if set(bindings) != set(pins):
        raise ValueError("every declared pin must have an explicit binding")
    check_resources()
    directory.mkdir()
    save(directory/"plan.json", plan)
    started, reserved, guards = time.monotonic(), 0, []
    report = dict(schema=plan["schema"], plan_id=plan["plan_id"], status="INCOMPLETE",
        evidence_mode=evidence_mode, controls=[], arms={}, drafts=[], selection=None,
        reservations=[], max_processes=max_processes, recommended=None,
        task_split=plan["task_split"], proof_receipt_cache_enabled=False,
        training_enabled=False, promoted=False, models_called=0, official_score=None,
        measured_api_cost=None)

    def reserve(label, units):
        nonlocal reserved
        check_resources()
        if reserved + units > max_processes:
            raise ValueError("pilot reservation exhausted")
        row = dict(label=label, units=units, prior_reserved=reserved, plan_id=plan["plan_id"])
        save(directory/f"reservation-{len(report['reservations']):02}.json", row)
        reserved += units
        report["reservations"].append(row)
        print(json.dumps(dict(phase=label, reserved=reserved)), flush=True)

    def guard_for(chosen, limit, reader, order="reference-first"):
        guard = NativeLeanVerifier(chosen, max_processes=limit, timeout=90,
                                   fingerprinter=reader, branch_order=order)
        guards.append(guard)
        return guard

    def finish(status, reason):
        report.update(status=status, reason=reason, reserved_processes=reserved,
            native_processes=sum(g.processes for g in guards) if evidence_mode=="local_lean" else 0,
            adapter_process_invocations=sum(g.processes for g in guards),
            wall_seconds=time.monotonic()-started)
        save(directory/"report.json", report)
        return report

    try:
        # Hash-cache sharing saves repeated file reads, not verification calls.
        reader = Fingerprinter()
        control = guard_for(bindings, plan["control_ceiling"], reader)
        context = control.context(record)
        save(directory/"context.json", asdict(context))
        sources = [record["src"], *([seed.source] if _incumbent(record, seed) else [])]
        for pin in pins:
            for index, source in enumerate(sources):
                reserve(f"control-{pin.lean_tag}-{index}", 1)
                receipt = control(VerificationRequest(context, source, pin))
                row = dict(pin=pin.to_dict(), source_sha256=source_hash(source), receipt=asdict(receipt))
                report["controls"].append(row)
                save(directory/f"control-{pin.lean_tag}-{index}.json", row)
                if receipt.outcome.value != "VERIFIED":
                    return finish("INCOMPLETE", "reference_or_incumbent_control_failed")

        drafts, origins = {}, {}
        incomplete = False
        arms = plan.get("discovery_arms") or [dict(label=m, mode=m, draft_policy=plan["nomination_policy"])
                                              for m in plan["modes"]]
        for arm in arms:
            label, mode = arm["label"], arm["mode"]
            reserve(label, limits.max_calls)
            guard = guard_for(bindings, limits.max_calls, reader)
            if evidence_mode == "local_lean":
                result = ArenaLocalRuntime(guard, record).discover_solver(pins[0], source=seed.source,
                    mode=mode, limits=limits, draft_policy=arm["draft_policy"])
            else:
                from .arena_solver import discover_solver_frontier
                result = discover_solver_frontier(guard.context(record), seed.source, pins[0], guard,
                    context_validator=guard.validate_request, evidence_mode=evidence_mode, mode=mode,
                    limits=limits, draft_policy=arm["draft_policy"])
            save(directory/f"discovery-{label}.json", result)
            if result["plan"]["context_id"] != context.context_id:
                raise ValueError("discovery context changed between arms")
            report["arms"][label] = dict(status=result["status"], verifier_calls=result["verifier_calls"],
                process_invocations=guard.processes, states=len(result["frontier"]),
                draft_count=len(result["drafts"]), tokens=[n["tokens"] for n in result["frontier"]],
                raw_heartbeats=[n["raw_heartbeats"] for n in result["frontier"]],
                wall_seconds=result["wall_seconds"], truncated=result["truncated"], omitted=result["omitted"])
            if "discovery_arms" in plan:
                report["arms"][label].update(mode=mode, draft_policy=arm["draft_policy"])
            print(json.dumps(dict(phase="discovery-finished", label=label,
                                  **{"mode": mode, **report["arms"][label]})), flush=True)
            incomplete |= not result["seed_checked"] or result["status"] not in ("COMPLETE", "BUDGET_EXHAUSTED")
            for d in result["drafts"]:
                key = source_hash(d["source"])
                origins.setdefault(key, []).append(label)
                if key not in drafts:
                    drafts[key] = Candidate(f"solver-{len(drafts)}", d["source"], d["provenance"])
        # A partial arm is not silently dropped from the comparison denominator.
        if incomplete:
            return finish("INCOMPLETE", "discovery_infrastructure_or_seed_failure")
        for pin in pins:
            control.validate_request(VerificationRequest(context, seed.source, pin))
        candidates = list(drafts.values())
        report["draft_origins"] = origins
        for candidate in candidates:
            draft = dict(name=record["name"], **asdict(candidate))
            report["drafts"].append(draft)
            save(directory/(candidate.label+".json"), draft)
        if not candidates:
            reason = ("bounded_discovery_no_eligible_draft" if "discovery_arms" in plan
                      else "bounded_discovery_no_shorter_draft")
            return finish("NO_CANDIDATE", reason)
        selection = selection_plan(record, candidates, incumbent=_incumbent(record, seed), **plan["selection"])
        if selection["required_request_budget"] > plan["selection_ceiling"]:
            raise ValueError("selection exceeds frozen reservation")
        save(directory/"selection-plan.json", selection)
        reserve("fresh-all-pin-selection-and-confirmation", selection["required_request_budget"])

        def factory(phase, limit):
            check_resources()
            save(directory/(phase+"-phase.json"), dict(phase=phase, limit=limit,
                covered_by="fresh-all-pin-selection-and-confirmation", retries=0))
            fresh_reader = Fingerprinter()
            return {(p, order):guard_for({p:bindings[p]}, limit, fresh_reader, order)
                    for p in pins for order in ORDERS}, {}

        selected = run_selection(record, candidates, factory, incumbent=_incumbent(record, seed),
            max_calls=selection["required_request_budget"], evidence_mode=evidence_mode, progress=True, **plan["selection"])
        save(directory/"selection.json", selected)
        report.update(selection="selection.json", recommended=selected["recommended"])
        check_resources()
        return finish(selected["status"], selected["reason"])
    except Exception as exc:
        report["recommended"] = None
        return finish("INCOMPLETE", f"{type(exc).__name__}: {str(exc)[:500]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", required=True)
    parser.add_argument("--incumbent", type=Path)
    parser.add_argument("--comparison", choices=COMPARISONS, default="legacy-v1")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-processes", type=int, default=0)
    parser.add_argument("--snapshot-manifest-sha256")
    parser.add_argument("--preparation-root", type=Path)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--elan-home", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = [json.loads(s) for s in CORPUS.read_text().splitlines() if s.strip()]
    matches = [r for r in records if r["name"] == args.problem]
    if len(matches) != 1:
        parser.error("one exact public-warmup task required")
    record, seed = matches[0], None
    if args.incumbent:
        if args.incumbent.stat().st_size > 1_048_576:
            parser.error("incumbent byte limit")
        d = json.loads(args.incumbent.read_text())
        if set(d) != {"name", "label", "source", "provenance"} or d["name"] != record["name"]:
            parser.error("matching four-field draft required, not a receipt")
        seed = Candidate(d["label"], d["source"], d["provenance"])
    plan = make_plan(record, seed, comparison=args.comparison)
    if not args.execute:
        print(json.dumps(plan, indent=2)); return 0
    if not all((args.snapshot_manifest_sha256, args.preparation_root, args.projects, args.elan_home, args.output)):
        parser.error("execution requires frozen snapshot, preparation, projects, elan-home and new output")
    if args.max_processes != plan["max_processes"]:
        parser.error("reserve the exact frozen process ceiling before execution")
    config = json.loads((args.preparation_root/"preparation.json").read_text())
    with exclusive(args.preparation_root/"single-build.lock"):
        mount = validate_volume(config)
        if args.output.exists() or not args.output.resolve().is_relative_to(mount):
            raise ValueError("new output inside capped volume required")
        if not Path(os.environ.get("TMPDIR", "/tmp")).resolve().is_relative_to(mount):
            raise ValueError("temporary storage must stay inside capped volume")
        if any(not p.resolve().is_relative_to(ROOT/"inputs") for p in
               [args.projects, *([args.incumbent] if args.incumbent else [])]):
            raise ValueError("project and incumbent inputs must belong to snapshot")
        before = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
        if any(getattr(m, "__file__", None) and not Path(m.__file__).resolve().is_relative_to(ROOT)
               for n,m in sys.modules.items() if n == "jevops" or n.startswith("jevops.")):
            raise ValueError("JevOps import escaped snapshot")
        projects, bindings = json.loads(args.projects.read_text()), {}
        for pin in _pins(record):
            rows = [p for p in projects if (p["repository"],p["lean_tag"],p["git_commit"]) ==
                    (record["url"],pin.lean_tag,pin.git_commit)]
            if len(rows) != 1: raise ValueError("one prepared project per exact pin required")
            bindings[pin] = project_binding(record, pin, rows[0], args.elan_home)
        def resources():
            validate_volume(config)
            stat = os.statvfs(mount)
            if stat.f_bavail*stat.f_frsize < 100_000_000:
                raise ValueError("storage reserve reached; retain all caches")
        result = run_pilot(plan, bindings=bindings, directory=args.output,
            max_processes=args.max_processes, check_resources=resources)
        save(args.output/"source-binding.json", dict(before=before,
            after=verify_snapshot(ROOT, args.snapshot_manifest_sha256), max_bytes=config["max_bytes"]))
    print(json.dumps({k:result[k] for k in ("status", "native_processes", "reserved_processes", "official_score")}))
    return 2 if result["status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
