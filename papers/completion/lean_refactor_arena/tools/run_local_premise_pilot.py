#!/usr/bin/env python3
"""Frozen public-warmup whole/local or local/portfolio proposal comparison.

Plan by default. Native execution requires a reviewed source snapshot and the
existing capped-volume/exclusive-build boundary. No API, installs or builds.
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

from jevops.arena import VerificationRequest, content_hash, reference_tokens
from jevops.arena_lean import CORPUS, NativeLeanVerifier, project_binding
from jevops.arena_local import ArenaLocalRuntime, PROJECTION
from jevops.arena_premises import NativePremiseExporter, PremiseOrigin
from jevops.arena_providers import PremiseProvider, load_inventory, propose_batch, propose_local_batch, strict_json
from jevops.arena_trial import Candidate, ORDERS, _pins, run_trial, trial_plan
from jevops.premise_search import bounded_int


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())


def make_plan(record, nominees, *, cap=2, max_processes=0, comparison="whole-local"):
    bounded_int(cap, 1, 2)
    bounded_int(max_processes, 0, 128)
    if comparison not in {"whole-local", "local-portfolio", "application-retrieval", "bounded-search", "subgoal-retrieval", "subgoal-ordering", "proposition-discharge", "cycle-guard", "assigned-cycle"}:
        raise ValueError("unknown comparison")
    if type(nominees) is not list or not 1 <= len(nominees) <= 64:
        raise ValueError("one to 64 explicit nominees required")
    specs = [asdict(PremiseOrigin(**row)) for row in nominees]
    if len({s["name"] for s in specs}) != len(specs):
        raise ValueError("duplicate nominees")
    pins = _pins(record)
    discovery = 2 * len(pins) + 1 + cap * (2 if comparison == "local-portfolio" else 1)
    family_count = 3 if comparison in {"bounded-search", "subgoal-retrieval", "proposition-discharge", "cycle-guard", "assigned-cycle"} else 2
    if comparison in {"application-retrieval", "bounded-search", "subgoal-retrieval", "subgoal-ordering", "proposition-discharge", "cycle-guard", "assigned-cycle"}:
        discovery = 2 * len(pins) + 1 + family_count * 4  # includes internal materialization/replay
    screening = family_count * cap * len(pins)
    measurement = (1 + family_count * cap) * len(pins) * 4  # 2 orders x 2 repeats, only survivors
    ceiling = discovery + screening + measurement
    if ceiling > 128:
        raise ValueError("pilot exceeds bounded process protocol")
    plan = {"schema": "jevops-local-premise-pilot/v1", "record": record, "nominees": specs,
        "cap_per_family": cap, "families": ["whole", "local"], "max_processes": max_processes,
        "process_ceiling": ceiling, "discovery_ceiling": discovery, "screening_ceiling": screening,
        "measurement_ceiling": measurement, "capture_pin": pins[0].to_dict(),
        "protocol": {"stop_on_control_failure": True, "stop_candidate_after_non_verified": True,
            "retain_local_replay_failures_in_screen": True, "same_draft_and_screen_cap_per_family": True,
            "discovery_overhead_matched": False, "capture_projection": PROJECTION,
            "node_budget": 4096, "event_budget": 256,
            "max_events": 64, "top_k": 4, "max_scan": 512, "timeout_seconds": 90,
            "repetitions": 2, "seed": 17, "confirmation": False, "resume": False},
        "task_split": "exploratory-public-warmup-not-held-out", "model_calls": 0,
        "training": False, "promoted": False, "official_score": None}
    if comparison == "local-portfolio":
        # Keep the historical default protocol/plan identity unchanged.
        plan.update(comparison=comparison, families=["local", "portfolio"])
        plan["protocol"].update(discovery_overhead_matched=True,
            shared_capture_and_inventory=True, local_replay_cap_per_family=cap,
            strategies={"local": "baseline-v1", "portfolio": "portfolio-v1"},
            max_templates=128, max_query_nodes=256)
    if comparison == "application-retrieval":
        plan.update(comparison=comparison, families=["lexical", "typed"])
        plan["protocol"].update(shared_capture_and_inventory=True, include_signatures=True,
            discovery_overhead_matched=True, measured_wall_time_matched=False,
            max_applications_per_family=4, max_query_nodes=256, span_order="headroom-v1",
            retrievals={"lexical": "lexical-v1", "typed": "typed-head-v1"},
            retain_local_replay_failures_in_screen=False,
            local_replay_failure_reason="only materialized independently replayed drafts reach screening",
            family_discovery_order=["lexical", "typed"])
    if comparison == "bounded-search":
        plan.update(comparison=comparison, families=["headroom", "matching", "backward"])
        plan["protocol"].update(shared_capture_and_inventory=True, include_signatures=True,
            discovery_overhead_matched=False, process_ceiling_matched=True,
            primitive_work_matched=False, measured_wall_time_matched=False,
            max_applications_per_family=4, max_query_nodes=256,
            family_options={
                "headroom": {"span_order": "headroom-v1", "retrieval": "typed-head-v1"},
                "matching": {"span_order": "matching-head-v1", "retrieval": "typed-head-v1"},
                "backward": {"span_order": "matching-head-v1", "retrieval": "typed-head-v1",
                             "search": "backward-v1", "max_steps": 96, "max_depth": 4}},
            search_primitive_ceiling=384, retain_local_replay_failures_in_screen=False,
            local_replay_failure_reason="only materialized independently replayed drafts reach screening",
            family_discovery_order=["headroom", "matching", "backward"])
    if comparison == "subgoal-retrieval":
        fixed = {"span_order": "matching-head-v1", "retrieval": "typed-head-v1",
                 "search": "backward-v1", "max_steps": 96, "max_depth": 4}
        dynamic = {**fixed, "search": "subgoal-v1", "max_pool": 64,
                   "max_retrievals": 32, "retrieval_top_k": 4}
        plan.update(comparison=comparison, families=["fixed", "subgoal", "deeper"])
        plan["protocol"].update(shared_capture_and_inventory=True, include_signatures=True,
            discovery_overhead_matched=False, process_ceiling_matched=True,
            primitive_ceiling_matched=True, primitive_work_matched=False,
            measured_wall_time_matched=False, max_applications_per_family=4, max_query_nodes=256,
            family_options={"fixed": fixed, "subgoal": dynamic, "deeper": {**dynamic, "max_depth": 8}},
            search_primitive_ceiling_per_family=384, retrieval_ceiling_per_dynamic_family=128,
            retain_local_replay_failures_in_screen=False,
            local_replay_failure_reason="only materialized independently replayed drafts reach screening",
            family_discovery_order=["fixed", "subgoal", "deeper"])
    if comparison == "subgoal-ordering":
        baseline = {"span_order": "matching-head-v1", "retrieval": "typed-head-v1",
                    "search": "subgoal-v1", "max_steps": 96, "max_depth": 8,
                    "max_pool": 64, "max_retrievals": 32, "retrieval_top_k": 4}
        plan.update(comparison=comparison, families=["baseline", "discharge"])
        plan["protocol"].update(shared_capture_and_inventory=True, include_signatures=True,
            discovery_overhead_matched=False, process_ceiling_matched=True,
            primitive_ceiling_matched=True, primitive_work_matched=False,
            measured_wall_time_matched=False, max_applications_per_family=4, max_query_nodes=256,
            family_options={"baseline": baseline, "discharge": {**baseline, "discharge_window": 8}},
            search_primitive_ceiling_per_family=384, retrieval_ceiling_per_dynamic_family=128,
            retain_local_replay_failures_in_screen=False,
            local_replay_failure_reason="only materialized independently replayed drafts reach screening",
            family_discovery_order=["baseline", "discharge"])
    if comparison == "proposition-discharge":
        baseline = {"span_order": "matching-head-v1", "retrieval": "typed-head-v1",
                    "search": "subgoal-v1", "max_steps": 96, "max_depth": 8,
                    "max_pool": 64, "max_retrievals": 32, "retrieval_top_k": 4}
        observed = {**baseline, "discharge_window": 8, "max_discharge_checks": 256}
        plan.update(comparison=comparison, families=["baseline", "observe_all", "propositions"])
        plan["protocol"].update(shared_capture_and_inventory=True, include_signatures=True,
            discovery_overhead_matched=False, process_ceiling_matched=True,
            primitive_ceiling_matched=True, primitive_work_matched=False,
            measured_wall_time_matched=False, max_applications_per_family=4, max_query_nodes=256,
            family_options={"baseline": baseline,
                "observe_all": {**observed, "discharge_filter": "observe-all-v1"},
                "propositions": {**observed, "discharge_filter": "propositions-v1"}},
            search_primitive_ceiling_per_family=384, retrieval_ceiling_per_dynamic_family=128,
            inspection_ceiling_per_observed_family=1024,
            retain_local_replay_failures_in_screen=False,
            local_replay_failure_reason="only materialized independently replayed drafts reach screening",
            family_discovery_order=["baseline", "observe_all", "propositions"])
    if comparison in {"cycle-guard", "assigned-cycle"}:
        baseline = {"span_order": "matching-head-v1", "retrieval": "typed-head-v1",
                    "search": "subgoal-v1", "max_steps": 96, "max_depth": 8,
                    "max_pool": 64, "max_retrievals": 32, "retrieval_top_k": 4,
                    "discharge_window": 8, "discharge_filter": "propositions-v1", "max_discharge_checks": 256}
        plan.update(comparison=comparison, families=["baseline", "observe", "guarded"])
        plan["protocol"].update(shared_capture_and_inventory=True, include_signatures=True,
            discovery_overhead_matched=False, process_ceiling_matched=True,
            primitive_ceiling_matched=True, primitive_work_matched=False,
            measured_wall_time_matched=False, max_applications_per_family=4, max_query_nodes=256,
            family_options={"baseline": baseline,
                "observe": {**baseline, "cycle_guard": "observe-v1", "max_cycle_checks": 256},
                "guarded": {**baseline, "cycle_guard": "prune-v1", "max_cycle_checks": 256}},
            search_primitive_ceiling_per_family=384, retrieval_ceiling_per_dynamic_family=128,
            inspection_ceiling_per_observed_family=1024, cycle_check_ceiling_per_observed_family=1024,
            retain_local_replay_failures_in_screen=False,
            local_replay_failure_reason="only materialized independently replayed drafts reach screening",
            family_discovery_order=["baseline", "observe", "guarded"])
        if comparison == "assigned-cycle":
            raw = {**baseline, "cycle_guard": "prune-v1", "max_cycle_checks": 256}
            plan["families"] = ["raw", "observe", "guarded"]
            plan["protocol"].update(family_discovery_order=plan["families"], key_work_matched=False,
                family_options={"raw": raw,
                    "observe": {**raw, "cycle_guard": "observe-v1", "cycle_key": "assigned-v1"},
                    "guarded": {**raw, "cycle_key": "assigned-v1"}})
    return {**plan, "plan_id": content_hash(plan)}


def run_pilot(plan, directory, bindings, *, reader, excluded_names, check_resources):
    if plan != make_plan(plan["record"], plan["nominees"], cap=plan["cap_per_family"],
                         max_processes=plan["max_processes"], comparison=plan.get("comparison", "whole-local")):
        raise ValueError("pilot plan changed")
    if plan["max_processes"] < plan["process_ceiling"]:
        raise ValueError("reserve the full pilot ceiling before native work")
    directory.mkdir()
    save(directory / "plan.json", plan)
    started, reserved, charges = time.monotonic(), 0, []
    cap, record, pins = plan["cap_per_family"], plan["record"], _pins(plan["record"])
    guard = NativeLeanVerifier(bindings, max_processes=(1 + len(plan["families"]) * cap) * len(pins),
        timeout=90, fingerprinter=reader)
    context = guard.context(record)
    save(directory / "context.json", asdict(context))
    result = {"schema": plan["schema"], "plan_id": plan["plan_id"], "status": "INCOMPLETE",
        "controls": [], "screen": [], "families": {}, "all_pin_verified": [],
        "measurement": None, "evidence_mode": "trusted_local_native", "os_sandbox": False,
        "training": False, "promoted": False, "official_score": None, "model_calls": 0,
        "api_cost": None, "electricity_cost": None}

    def reserve(label, units):
        nonlocal reserved
        check_resources()
        if reserved + units > plan["max_processes"]:
            raise ValueError("pilot budget exhausted")
        save(directory / f"reservation-{len(charges):03}.json", {"label": label, "units": units,
            "plan_id": plan["plan_id"], "prior_reserved": reserved})
        reserved += units
        charges.append({"label": label, "units": units})
        print(json.dumps({"phase": label, "reserved": reserved}), flush=True)

    def finish(reason, *, extra_processes=0):
        result.update(reason=reason, reserved_processes=reserved,
            native_processes=guard.processes + extra_processes, charges=charges,
            wall_seconds=round(time.monotonic() - started, 4))
        save(directory / "report.json", result)
        return result

    for pin in pins:
        reserve("control-" + pin.lean_tag, 1)
        receipt = guard(VerificationRequest(context, record["src"], pin))
        result["controls"].append(asdict(receipt))
        save(directory / f"control-{pin.lean_tag}.json", asdict(receipt))
        if receipt.outcome.value != "VERIFIED":
            return finish("reference_control_failed")

    reserve("all-pin-inventory", len(pins))
    application_trial = plan.get("comparison") in {"application-retrieval", "bounded-search", "subgoal-retrieval", "subgoal-ordering", "proposition-discharge", "cycle-guard", "assigned-cycle"}
    exporter = NativePremiseExporter(guard, max_processes=len(pins), total_seconds=300,
                                    **({"include_signatures": True} if application_trial else {}))
    inventory = exporter.export(record, tuple(PremiseOrigin(**s) for s in plan["nominees"]),
                                excluded_names=excluded_names)
    save(directory / "inventory.json", inventory)
    if inventory["status"] != "INVENTORY_ONLY":
        return finish("inventory_incomplete", extra_processes=exporter.attempts)
    index, scope = load_inventory(json.loads(json.dumps(inventory["inventory"])),
                                  json.loads(json.dumps(inventory["scope"])))
    reserve("project-capture", 1)
    matched_local = plan.get("comparison") == "local-portfolio"
    application_budget = plan["protocol"].get("max_applications_per_family", 0)
    local = ArenaLocalRuntime(guard, record,
        max_processes=1 + (len(plan["families"]) * application_budget if application_trial else cap * (2 if matched_local else 1)),
        event_budget=256)
    capture = local.capture(pins[0])
    save(directory / "capture.json", capture)
    if not capture["ok"]:
        return finish("capture_incomplete", extra_processes=exporter.attempts + local.attempts)
    if application_trial:
        families = {}
        for family in plan["protocol"]["family_discovery_order"]:
            reserve(f"{family}-application-discovery", application_budget)
            start_family = time.monotonic()
            options = (plan["protocol"]["family_options"][family] if "family_options" in plan["protocol"]
                else {"span_order": plan["protocol"]["span_order"], "retrieval": plan["protocol"]["retrievals"][family]})
            families[family] = local.discover_batch(pins[0], capture["capture"], index, scope,
                cap=cap, max_events=plan["protocol"]["max_events"], top_k=plan["protocol"]["top_k"],
                max_scan=plan["protocol"]["max_scan"], max_query_nodes=plan["protocol"]["max_query_nodes"],
                max_applications=application_budget, **options)
            families[family]["wall_seconds"] = round(time.monotonic() - start_family, 4)
    elif matched_local:
        families = {family: propose_local_batch(record, capture["capture"], index, scope,
            cap=cap, max_events=64, strategy=strategy, max_templates=plan["protocol"]["max_templates"],
            max_query_nodes=plan["protocol"]["max_query_nodes"])
            for family, strategy in plan["protocol"]["strategies"].items()}
    else:
        families = {"whole": propose_batch(record, index, scope, providers=(PremiseProvider(),), cap=cap),
            "local": propose_local_batch(record, capture["capture"], index, scope, cap=cap, max_events=64)}
    for family, batch in families.items():
        save(directory / f"{family}-drafts.json", batch)
        result["families"][family] = {"drafts": len(batch["drafts"]), "cap": cap, "verified": 0}
        if application_trial:
            result["families"][family].update({key: batch[key] for key in
                ("status", "application_attempts", "roundtrip_attempts", "wall_seconds", "truncated")})
            result["families"][family].update({key: batch[key] for key in
                ("search_steps_reserved", "search_steps_observed", "unknown_search_processes",
                 "retrievals_reserved", "retrievals_observed", "discharge_checks_reserved",
                 "discharge_checks_observed", "discharge_skips", "cycle_checks_reserved",
                 "cycle_checks_observed", "cycle_prunes", "cycle_nodes_observed", "cycle_expr_nodes_observed",
                 "cycle_level_nodes_observed", "cycle_term_dereferences_observed", "cycle_level_dereferences_observed") if key in batch})
    if application_trial and any(batch["status"] in {"ERROR", "BUDGET_EXHAUSTED"} for batch in families.values()):
        return finish("application_discovery_incomplete", extra_processes=exporter.attempts + local.attempts)
    # Each candidate remains an independent invocation; a failure cannot poison
    # or help the next candidate's Lean state. Equal replay ceilings, alternated.
    for i in range(cap):
        for family in ([] if application_trial else ["local", "portfolio"] if matched_local else ["local"]):
            proposals = families[family]["proposals"]
            if i >= len(proposals):
                continue
            reserve(f"{family}-replay-{i}", 1)
            outcome = local.replay(pins[0], record["src"], capture["capture"], **proposals[i])
            save(directory / f"{family}-replay-{i}.json", outcome)
    survivors, seen = [], set()
    # Alternation makes the screening order explicit; all families get equal
    # ceilings. Local replay outcomes do not prune whole-source comparisons.
    for i in range(cap):
        for family in plan["families"]:
            drafts = families[family]["drafts"]
            if i >= len(drafts):
                continue
            draft = drafts[i]
            candidate = Candidate(f"{family}-{i}", draft["source"], draft["provenance"])
            row = {"family": family, "candidate": asdict(candidate), "receipts": [],
                "tokens": reference_tokens(candidate.source, record["statement"]), "status": "INCOMPLETE"}
            for pin in pins:
                reserve(f"screen-{candidate.label}-{pin.lean_tag}", 1)
                receipt = guard(VerificationRequest(context, candidate.source, pin))
                row["receipts"].append(asdict(receipt))
                if receipt.outcome.value != "VERIFIED":
                    row["status"] = receipt.outcome.value
                    break
            else:
                row["status"] = "ALL_PIN_VERIFIED"
                result["families"][family]["verified"] += 1
                result["all_pin_verified"].append(candidate.label)
                if candidate.source not in seen:
                    survivors.append(candidate); seen.add(candidate.source)
            result["screen"].append(row)
            save(directory / f"screen-{candidate.label}.json", row)
    measured_processes = 0
    if survivors:
        measurement_plan = trial_plan(record, survivors, repetitions=2, seed=17)
        calls = measurement_plan["planned_requests"]
        save(directory / "measurement-plan.json", measurement_plan)
        reserve("fresh-balanced-measurement", calls)
        verifiers = {(pin, order): NativeLeanVerifier({pin: bindings[pin]}, max_processes=calls,
            timeout=90, fingerprinter=reader, branch_order=order) for pin in pins for order in ORDERS}
        report = run_trial(record, survivors, verifiers, max_calls=calls, repetitions=2, seed=17, progress=True)
        save(directory / "measurement.json", report)
        result["measurement"] = "measurement.json"
        measured_processes = sum(v.processes for v in verifiers.values())
    result["status"] = "COMPLETE" if all(r["status"] in {"ALL_PIN_VERIFIED", "REJECTED"}
        for r in result["screen"]) else "INCOMPLETE"
    return finish("screened_fixed_candidates_no_promotion", extra_processes=exporter.attempts + local.attempts + measured_processes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", default="Core.InitsUpdatesComm")
    parser.add_argument("--nominees", type=Path, required=True)
    parser.add_argument("--cap", type=int, default=2)
    parser.add_argument("--max-processes", type=int, default=0)
    parser.add_argument("--comparison", choices=("whole-local", "local-portfolio", "application-retrieval", "bounded-search", "subgoal-retrieval", "subgoal-ordering", "proposition-discharge", "cycle-guard", "assigned-cycle"), default="whole-local")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--snapshot-manifest-sha256")
    parser.add_argument("--preparation-root", type=Path)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--elan-home", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    record = next(r for r in records if r["name"] == args.problem)
    with args.nominees.open("rb") as stream:
        nominees = strict_json(stream.read(65537))
    plan = make_plan(record, nominees, cap=args.cap, max_processes=args.max_processes, comparison=args.comparison)
    if not args.execute:
        print(json.dumps(plan, indent=2)); return 0
    if not all((args.snapshot_manifest_sha256, args.preparation_root, args.projects, args.elan_home, args.output)):
        parser.error("execution requires snapshot, preparation, projects, elan-home and new output")
    from jevops.arena_prepare import exclusive, validate_volume
    from jevops.arena_snapshot import verify_snapshot
    from jevops.seals import Fingerprinter
    config = json.loads((args.preparation_root / "preparation.json").read_text())
    with exclusive(args.preparation_root / "single-build.lock"):
        mount = validate_volume(config)
        if not args.output.resolve().is_relative_to(mount) or args.output.exists():
            raise ValueError("new output inside capped preparation volume required")
        if any(not path.resolve().is_relative_to(ROOT / "inputs") for path in (args.projects, args.nominees)):
            raise ValueError("project and nominee inputs must belong to source snapshot")
        before = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
        if any(getattr(m, "__file__", None) and not Path(m.__file__).resolve().is_relative_to(ROOT)
               for n, m in sys.modules.items() if n == "jevops" or n.startswith("jevops.")):
            raise ValueError("JevOps import escaped snapshot")
        projects, reader = json.loads(args.projects.read_text()), Fingerprinter()
        bindings = {}
        for pin in _pins(record):
            matches = [p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                       (record["url"], pin.lean_tag, pin.git_commit)]
            if len(matches) != 1: raise ValueError("one prepared project per required pin")
            bindings[pin] = project_binding(record, pin, matches[0], args.elan_home)
        result = run_pilot(plan, args.output, bindings, reader=reader,
            excluded_names=tuple(sorted(r["name"] for r in records)), check_resources=lambda: validate_volume(config))
        save(args.output / "source-binding.json", {"before": before,
             "after": verify_snapshot(ROOT, args.snapshot_manifest_sha256)})
    print(json.dumps({k: result[k] for k in ("status", "reason", "families", "native_processes", "official_score")}))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
