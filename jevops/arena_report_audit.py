"""Generate compact consistency reports, never proof or promotion authority.

Saved JSON is untrusted historical data. Recomputing hashes, schedules and costs
can expose inconsistencies, but cannot authenticate receipts, establish fresh
timings, attest loaded code, or replace the native verifier. No Lean/model calls.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from .arena import ArenaContext, VerificationRequest, content_hash, source_hash
from .arena_pareto import SCHEMA as SELECTION_SCHEMA, _analysis
from .arena_trial import Candidate, ORDERS, _pins, trial_plan
from .lean import VersionPin

SCHEMA = "jevops-arena-report-audit/v1"
MAX_INPUT_BYTES = 16 * 1024 * 1024


def _receipt_claims_match(trial: dict) -> bool:
    contexts = {}
    for data in trial["contexts"]:
        context = ArenaContext(**{**data, "versions": tuple(VersionPin(**p) for p in data["versions"]),
                                  "dependency_digests": tuple(data["dependency_digests"]),
                                  "allowed_axioms": tuple(data["allowed_axioms"])})
        contexts[context.context_id] = context
    if len(contexts) != len(trial["contexts"]):
        return False
    sources = {a["label"]: a["source"] for a in trial["arms"]}
    for sample in trial["samples"]:
        if sample["status"] != "VERIFIED":
            continue
        context = contexts.get(sample["context_id"])
        if context is None:
            return False
        pin = VersionPin(**sample["version"])
        receipt = sample["receipt"]
        obs = json.loads(receipt["observations_json"])
        native = obs["report"]
        if (pin not in context.versions or context.reference_source != trial["record"]["src"]
                or context.statement != trial["record"]["statement"]
                or context.problem != trial["record"]["name"]
                or receipt["request_id"] != VerificationRequest(context, sources[sample["label"]], pin).request_id
                or receipt["target"] != context.problem or receipt["exit_code"] != 0
                or receipt["type_preserved"] is not True or native["type_preserved"] is not True
                or native["target_absent_before"] is not True or native["outcome"] != "VERIFIED"
                or receipt["heartbeats"] != native["raw_heartbeats"] // 1000
                or json.loads(context.verifier_options_json)["branch_order"] != sample["branch_order"]):
            return False
    return True


def audit_report(protocol: dict, report: dict) -> dict:
    """Inspect recorded claims. Even CONSISTENT is not an admission decision."""
    checks, phases = {}, {}
    result = {"schema": SCHEMA, "status": "INCONSISTENT", "checks": checks,
              "phases": phases, "proof_verified": False, "fresh_native_processes": 0,
              "promoted": False, "training_enabled": False, "official_score": None,
              "reported_selector_status": None, "errors": []}
    try:
        result["protocol_content_sha256"] = content_hash(protocol)
        result["report_content_sha256"] = content_hash(report)
        result["reported_selector_status"] = report["status"]
        checks["supported_status"] = report["status"] in {
            "CONFIRMED_LOCAL_IMPROVEMENT", "FIXTURE_CONFIRMED", "NO_IMPROVEMENT", "INCOMPLETE", "UNCONFIRMED"}
        plan = report["plan"]
        checks["supported_schema"] = protocol["schema"] == report["schema"] == SELECTION_SCHEMA
        checks["protocol_matches_report"] = protocol == plan
        checks["plan_identity"] = plan["plan_id"] == content_hash(
            {key: value for key, value in plan.items() if key != "plan_id"})
        checks["implementation_reported_unchanged"] = report["implementation_unchanged"] is True
        checks["supported_evidence_mode"] = report["evidence_mode"] in {"local_lean", "offline_fixture"}
        checks["no_promotion_or_training_claim"] = (report["promoted"] is False
            and report["training_enabled"] is False and report["live_model_calls"] == 0
            and report["official_score"] is None)
        # Early v1 reports predate the optional strict-dual policy. Preserve
        # their original Pareto semantics rather than pretending they used it.
        criteria = {"selection_objective": plan.get("selection_objective", "pareto-v1"),
                    "heartbeat_noise_floor_raw": plan.get("heartbeat_noise_floor_raw", 0)}
        result["legacy_policy_defaults_used"] = any(k not in plan for k in criteria)
        selected = report["selected_for_confirmation"]
        checks["selected_matches_screen_analysis"] = selected == report["screen_analysis"]["selected"]
        chosen = None
        result.update(problem=plan["screen"]["record"]["name"], selected=selected,
                      objective=criteria["selection_objective"], reason=report["reason"])
        active = ["screen"] + (["confirmation"] if report["confirmation"] is not None else [])
        totals = dict.fromkeys(("requests_reserved", "verifier_invocations", "native_processes"), 0)
        for phase in active:
            trial = report[phase]
            arms = [Candidate(**arm) for arm in trial["arms"][1:]]
            expected = trial_plan(trial["record"], arms, repetitions=trial["repetitions"], seed=trial["seed"])
            checks[f"{phase}.design"] = all(trial.get(k) == v for k, v in expected.items())
            checks[f"{phase}.record"] = trial["record"] == plan["screen"]["record"]
            checks[f"{phase}.cache_disabled"] = trial["receipt_cache_enabled"] is False
            checks[f"{phase}.runner_identity"] = trial["runner_sha256"] == plan["implementation"]["arena_trial.py"]
            checks[f"{phase}.mode"] = trial["evidence_mode"] == report["evidence_mode"]
            checks[f"{phase}.receipt_claims"] = _receipt_claims_match(trial)
            samples = trial["samples"]
            checks[f"{phase}.sample_ids_unique"] = len({s["sample_id"] for s in samples}) == len(samples)
            # This also checks sample/schedule alignment, source identity, receipt
            # heartbeat agreement, per-pin coverage, axiom sets and token costs.
            labels = plan["candidate_labels"] if phase == "screen" else [selected]
            computed = _analysis(trial, plan["incumbent_label"], labels, **criteria)
            stored = report[phase + "_analysis"]
            checks[f"{phase}.cost_analysis"] = computed == {
                "selection_objective": "pareto-v1", "heartbeat_noise_floor_raw": 0, **stored}
            if phase == "screen":
                checks["screen.precommitted_design"] = all(trial.get(k) == v for k, v in plan["screen"].items())
            else:
                confirm_arms = [a for a in plan["screen"]["arms"]
                                if a["label"] in {"control", plan["incumbent_label"], selected}]
                checks["confirmation.fixed_winner"] = trial["arms"] == confirm_arms
                checks["confirmation.design_parameters"] = (trial["seed"] == plan["confirmation_seed"]
                    and trial["repetitions"] == plan["confirmation_repetitions"]
                    and trial["planned_requests"] == plan["confirmation_request_reserve"])
                checks["confirmation.contexts_match"] = sorted(map(content_hash, trial["contexts"])) == sorted(
                    map(content_hash, report["screen"]["contexts"]))
            for key in totals:
                count = trial[key]
                if type(count) is not int or count < 0:
                    raise ValueError(f"invalid {phase}.{key}")
                totals[key] += count
            calls = [s["verifier_invocations"] for s in samples]
            checks[f"{phase}.invocation_accounting"] = (all(type(c) is int and 0 <= c <= 1 for c in calls)
                and sum(calls) == trial["verifier_invocations"])
            checks[f"{phase}.native_accounting"] = trial["native_processes"] == (
                trial["verifier_invocations"] if report["evidence_mode"] == "local_lean" else 0)
            phases[phase] = {"scheduled": len(trial["schedule"]), "observed": len(samples),
                "statuses": dict(sorted(Counter(s["status"] for s in samples).items())),
                "reported_native_processes": trial["native_processes"], "rows": computed["rows"],
                "strata": [{**pin.to_dict(), "branch_order": order} for pin in _pins(trial["record"]) for order in ORDERS]}
            if selected in computed["rows"]:
                baseline, candidate = (computed["rows"][label] for label in (plan["incumbent_label"], selected))
                phases[phase]["selected_vs_incumbent"] = {
                    "baseline_tokens": baseline["tokens"], "candidate_tokens": candidate["tokens"],
                    "mean_raw_heartbeat_reduction_pct": [
                        100 * (1 - sum(a) * len(b) / (sum(b) * len(a))) if a and b and sum(b) else None
                        for a, b in zip(candidate["raw_heartbeats_by_stratum"], baseline["raw_heartbeats_by_stratum"])]}
        checks["total_accounting"] = all(report[k] == v for k, v in totals.items())
        checks["budget"] = (0 <= totals["native_processes"] <= totals["verifier_invocations"]
            <= totals["requests_reserved"] <= plan["required_request_budget"] <= report["max_calls"] <= 256)
        if selected is not None:
            chosen = next(a for a in plan["screen"]["arms"] if a["label"] == selected)
            checks["selection_commitment"] = report["selection_commitment"] == content_hash({
                "plan_id": plan["plan_id"], "screen_sha256": content_hash(report["screen"]), "selected": chosen})
            checks["confirmation_present"] = report["confirmation"] is not None
        else:
            checks["no_unselected_confirmation"] = (report["confirmation"] is None
                and report["selection_commitment"] is None and report["recommended"] is None)
        if report["status"] in {"CONFIRMED_LOCAL_IMPROVEMENT", "FIXTURE_CONFIRMED"}:
            checks["confirmed_gates"] = (selected is not None and len(active) == 2
                and all(report[p]["status"] == "COMPLETE" and report[p + "_analysis"]["selected"] == selected
                        for p in active))
            checks["recommendation_binding"] = (report["recommended"] == chosen
                if report["evidence_mode"] == "local_lean" else report["recommended"] is None)
            checks["confirmation_mode"] = report["status"] == (
                "CONFIRMED_LOCAL_IMPROVEMENT" if report["evidence_mode"] == "local_lean" else "FIXTURE_CONFIRMED")
        else:
            checks["no_unconfirmed_recommendation"] = report["recommended"] is None
        result["reported_counts"] = totals
        result["analysis_code_sha256"] = source_hash(Path(__file__).with_name("arena_pareto.py").read_text())
        result["analysis_code_matches_recorded"] = result["analysis_code_sha256"] == plan["implementation"]["arena_pareto.py"]
        result["status"] = "CONSISTENT" if all(checks.values()) else "INCONSISTENT"
    except (KeyError, ValueError, TypeError, IndexError, StopIteration, AttributeError) as exc:
        result["status"] = "MALFORMED"
        result["errors"].append(f"{type(exc).__name__}: {str(exc)[:300]}")
    return result


def audit_provider_pipeline(protocol: dict, report: dict, inventory: dict, batch: dict) -> dict:
    """Join saved discovery/measurement artifacts; never authenticate them.

    The proposal environment may differ from the later fresh measurement
    context. Check record/pin/source bindings, not equivalence of receipts.
    """
    audit = audit_report(protocol, report)
    checks = audit["checks"]
    audit["provider_pipeline_schema"] = "jevops-arena-provider-pipeline-audit/v1"
    audit["provider_audit_code_sha256"] = source_hash(Path(__file__).read_text())
    try:
        record = protocol["screen"]["record"]
        request = batch["request"]
        checks["pipeline.schemas"] = (inventory["schema"] == "jevops-native-premise-inventory/v1"
            and batch["schema"] == "jevops-arena-provider-batch/v1")
        checks["pipeline.native_inventory_reported_complete"] = (inventory["status"] == "INVENTORY_ONLY"
            and inventory["evidence_mode"] == "trusted_local_native")
        checks["pipeline.record"] = (content_hash(record) == inventory["record_sha256"] == request["record_sha256"])
        checks["pipeline.environment"] = (inventory["environment_sha256"] == request["environment_sha256"]
            == inventory["scope"]["environment_sha256"] == inventory["inventory"]["environment_sha256"])
        checks["pipeline.scope_identity"] = (inventory["scope"]["record_sha256"] == inventory["record_sha256"]
            and request["scope_sha256"] == content_hash({k: v for k, v in inventory["scope"].items() if k != "schema"}))
        checks["pipeline.index_identity"] = request["index_sha256"] == content_hash(
            {**inventory["inventory"], "feature_method": batch["ranking"]["feature_method"]})
        checks["pipeline.request_identity"] = request["request_sha256"] == content_hash(
            {k: v for k, v in request.items() if k != "request_sha256"})
        checks["pipeline.request_goal"] = (request["target"] == record["name"]
            and request["statement"] == record["statement"])
        checks["pipeline.base_source"] = (request["base_source"] == batch["seed"]["source"]
            and request["base_source_sha256"] == source_hash(request["base_source"]))
        arms = {a["label"]: a for a in protocol["screen"]["arms"]}
        checks["pipeline.incumbent"] = batch["seed"] == arms[protocol["incumbent_label"]]
        drafts = batch["drafts"]
        checks["pipeline.fixed_drafts"] = (
            [d["label"] for d in drafts] == protocol["candidate_labels"]
            and all(d["name"] == record["name"] and set(d) == {"name", "label", "source", "provenance"}
                    and {k: v for k, v in d.items() if k != "name"} == arms[d["label"]] for d in drafts))
        pins = [VersionPin(**s["pin"]) for s in inventory["stages"]]
        nominated = [d["name"] for d in inventory["metadata"]]
        checks["pipeline.stage_bindings"] = all(
            s["evidence"]["schema"] == "jevops-native-premises-stage/v1"
            and s["evidence"]["target"] == record["name"]
            and s["evidence"]["lean_version"] == pin.lean_tag.removeprefix("v")
            and s["evidence"]["report"]["status"] == "EXPORTED"
            and [e["name"] for e in s["evidence"]["report"]["entries"]] == nominated
            for s, pin in zip(inventory["stages"], pins))
        checks["pipeline.all_pins"] = (len(pins) == len(set(pins)) and set(pins) == set(_pins(record))
            and type(inventory["attempted_processes"]) is int and type(inventory["reserved_processes"]) is int
            and inventory["attempted_processes"] == inventory["reserved_processes"] == len(pins))
        checks["pipeline.no_discovery_authority"] = (
            inventory["proof_verified"] is inventory["promoted"] is inventory["training_enabled"] is False
            and batch["proof_verified"] is batch["promoted"] is batch["training_enabled"] is False
            and inventory["official_score"] is batch["official_score"] is None
            and type(batch["native_verifier_calls"]) is int and batch["native_verifier_calls"] == 0)
        audit["reported_inventory_processes"] = inventory["attempted_processes"]
        audit["reported_pipeline_native_processes"] = inventory["attempted_processes"] + report["native_processes"]
        if audit["status"] == "CONSISTENT" and not all(checks.values()):
            audit["status"] = "INCONSISTENT"
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        audit["status"] = "MALFORMED"
        audit["errors"].append(f"provider pipeline: {type(exc).__name__}: {str(exc)[:200]}")
    return audit


def summary(audit: dict) -> str:
    lines = ["# Arena report consistency audit", "", f"Audit: {audit['status']}.",
        f"Recorded selector status: {audit['reported_selector_status']}.", "",
        "Historical JSON only: no fresh Lean checks, authenticated receipts, promotion or official score.", ""]
    failed = [name for name, value in audit["checks"].items() if not value]
    lines += [f"Failed consistency checks: {', '.join(failed) or 'none'}.", ""]
    if "reported_pipeline_native_processes" in audit:
        lines += [f"Reported inventory processes: {audit['reported_inventory_processes']}; "
                  f"total discovery/selection processes: {audit['reported_pipeline_native_processes']}.",
                  "Discovery artifacts are bound to the same record and fixed drafts, not proof authority.", ""]
    for phase, data in audit["phases"].items():
        lines.append(f"{phase}: {data['observed']}/{data['scheduled']} samples; statuses {data['statuses']}.")
        lines.append("Strata: " + ", ".join(f"{s['lean_tag']}/{s['branch_order']}" for s in data["strata"]) + ".")
        lines.append("")
        for label, row in data["rows"].items():
            ranges = [f"{min(values)}–{max(values)}" if values else "missing"
                      for values in row["raw_heartbeats_by_stratum"]]
            lines.append(f"- {label}: {row['tokens']} proof tokens; raw heartbeat ranges: {', '.join(ranges)}.")
        lines.append("")
    return "\n".join(lines + audit["errors"]) + "\n"


def _read(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("report input byte limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--inventory-report", type=Path)
    parser.add_argument("--provider-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if (args.inventory_report is None) != (args.provider_manifest is None):
        parser.error("inventory report and provider manifest must be supplied together")
    try:
        protocol, report = _read(args.protocol), _read(args.report)
        audit = (audit_provider_pipeline(protocol, report, _read(args.inventory_report), _read(args.provider_manifest))
                 if args.inventory_report else audit_report(protocol, report))
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "audit.json").write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
        (args.output_dir / "summary.md").write_text(summary(audit))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": audit["status"], "proof_verified": False,
                      "fresh_native_processes": 0, "output_dir": str(args.output_dir)}))
    return 0 if audit["status"] == "CONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
