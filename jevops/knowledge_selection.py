"""Opt-in bridge from compact-term nominations to fresh strict-dual selection.

Historical receipts bind a nomination, never its validity or metric. The
original reference and caller's current incumbent remain separate controls.
This module does not promote proofs, produce training pairs or run a watcher.
"""
from dataclasses import asdict
import json
from pathlib import Path

from .arena import ArenaContext, content_hash, intake_error, reference_tokens, source_hash
from .arena_lean import NativeLeanVerifier
from .arena_pareto import selection_plan, run_selection, summary as selection_summary, _implementation, _criteria
from .arena_trial import Candidate, _pins
from .knowledge_materialize import measurement_plan, _identity as materialization_identity
from .knowledge_trial import _validate_contexts
from .lean import VersionPin
from .premise_search import bounded_int

SCHEMA = "jevops-compact-term-selection/v1"


def _identity():
    return content_hash(dict(adapter=source_hash(Path(__file__).read_text()),
        context_validator=source_hash(Path(__file__).with_name("knowledge_trial.py").read_text()),
        materialization=materialization_identity(), selection=_implementation()))


def _context(raw):
    return ArenaContext(**{**raw, "versions": tuple(VersionPin(**p) for p in raw["versions"]),
        "dependency_digests": tuple(raw["dependency_digests"]), "allowed_axioms": tuple(raw["allowed_axioms"])})


def compact_selection_plan(report, *, record, context, incumbent=None, repetitions=2,
                           confirmation_repetitions=3, seed=17, heartbeat_noise_floor_raw=0):
    """Freeze the real denominators; token-only rejection never asserts validity.

    None means the unchanged reference is the incumbent. Saved success flags
    and heartbeat values are not used to admit or rank the nominated term.
    """
    measurement_plan(report)  # Integrity/current implementation, NOT proof authority.
    if (type(context) is not ArenaContext or content_hash(record) != content_hash(report["plan"]["record"])
            or content_hash(asdict(context)) != content_hash(report["plan"]["context"])
            or context.problem != record["name"] or context.statement != record["statement"]
            or context.reference_source != record["src"] or context.versions != _pins(record)
            or context.reference_heartbeats is not None):
        raise ValueError("unchanged record and exact uncalibrated discovery context required")
    if incumbent is not None and type(incumbent) is not Candidate:
        raise ValueError("typed current incumbent required")
    current = incumbent or Candidate("control", record["src"], "unchanged-reference")
    if intake_error(current.source, record["statement"]):
        raise ValueError("incumbent violates the fixed statement/intake policy")
    mode = report["plan"]["evidence_mode"]
    if mode not in {"local_lean", "offline_fixture"}:
        raise ValueError("explicit evidence mode required")
    # Validate the knobs even when no candidate is available, without making
    # up an executable fallback or bypassing the existing selector's bounds.
    _criteria("strict-dual-v1", heartbeat_noise_floor_raw)
    bounded_int(repetitions, 2, 5)
    bounded_int(confirmation_repetitions, 2, 5)
    bounded_int(seed, 0, 2**32 - 1)
    statement = record["statement"]
    tokens = dict(reference=reference_tokens(record["src"], statement),
                  incumbent=reference_tokens(current.source, statement), candidate=None)
    source, nomination, selection = report["candidate"], None, None
    status = "NO_CANDIDATE"
    if source is not None:
        nomination = Candidate("compact", source, "unverified materialization nomination " + report["report_sha256"])
        if intake_error(source, statement):
            raise ValueError("nomination violates the fixed statement/intake policy")
        tokens["candidate"] = reference_tokens(source, statement)
        status = ("NOT_SHORTER_THAN_INCUMBENT" if tokens["candidate"] >= tokens["incumbent"] else
                  "NOT_SHORTER_THAN_REFERENCE" if tokens["candidate"] >= tokens["reference"] else "READY")
        if status == "READY":
            selection = selection_plan(record, [nomination],
                incumbent=None if current.source == record["src"] else Candidate("incumbent", current.source, current.provenance),
                repetitions=repetitions, confirmation_repetitions=confirmation_repetitions, seed=seed,
                selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=heartbeat_noise_floor_raw)
    plan = dict(schema=SCHEMA, materialization_sha256=report["report_sha256"], record=record,
        context=asdict(context), incumbent=asdict(current), candidate=asdict(nomination) if nomination else None,
        tokens=tokens, status=status, selection=selection, evidence_mode=mode,
        repetitions=repetitions, confirmation_repetitions=confirmation_repetitions, seed=seed,
        heartbeat_noise_floor_raw=heartbeat_noise_floor_raw,
        required_request_budget=selection["required_request_budget"] if selection else 0,
        implementation_sha256=_identity(), saved_receipts_are_authority=False,
        training_enabled=False, promoted=False, official_score=None)
    return json.loads(json.dumps({**plan, "plan_sha256": content_hash(plan)}))


def run_compact_selection(plan, report, *, record, incumbent=None, verifier_factory,
                          max_calls=0, progress=False):
    """Reuse balanced screening and fixed-winner confirmation, with no retries.

    Caller must supply its current record/incumbent, not substitute a longer
    generated application to inflate savings. Infrastructure factories are
    trusted and each phase must project the frozen environment exactly.
    """
    fresh = compact_selection_plan(report, record=record, context=_context(plan["context"]), incumbent=incumbent,
        **{key: plan[key] for key in ("repetitions", "confirmation_repetitions", "seed", "heartbeat_noise_floor_raw")})
    if content_hash(fresh) != content_hash(plan):
        raise ValueError("stale or mutated plan/current incumbent")
    if type(max_calls) is not int or max_calls != fresh["required_request_budget"]:
        raise ValueError("explicit full frozen screening and confirmation budget required")
    # Own snapshots before invoking injected infrastructure.
    plan = fresh
    result = dict(schema=SCHEMA, plan=plan, evidence_mode=plan["evidence_mode"],
        status=plan["status"], selection=None, recommended=None,
        retained_incumbent=plan["incumbent"], retained_incumbent_verified=False,
        native_processes=0, verifier_invocations=0, requests_reserved=0,
        training_enabled=False, promoted=False, official_score=None, novelty_claimed=False,
        learned_compression_claimed=False)
    if plan["status"] == "READY":
        context = _context(plan["context"])
        def factory(phase, limit):
            verifiers, failures = verifier_factory(phase, limit)
            if any(type(v) is not NativeLeanVerifier or v.processes for v in verifiers.values()):
                raise ValueError("fresh owned native guards required")
            _validate_contexts(context, plan["record"], verifiers)
            return verifiers, failures
        base = plan["selection"]
        arms = [Candidate(**a) for a in base["screen"]["arms"][1:]]
        outcome = run_selection(plan["record"], [a for a in arms if a.label == "compact"], factory,
            incumbent=next((a for a in arms if a.label == "incumbent"), None), max_calls=max_calls,
            repetitions=plan["repetitions"], confirmation_repetitions=plan["confirmation_repetitions"],
            seed=plan["seed"], evidence_mode=plan["evidence_mode"], progress=progress,
            selection_objective="strict-dual-v1", heartbeat_noise_floor_raw=plan["heartbeat_noise_floor_raw"])
        result.update(selection=outcome, **{key: outcome[key] for key in
            ("status", "recommended", "retained_incumbent_verified", "native_processes",
             "verifier_invocations", "requests_reserved")})
        result["retained_incumbent_verified"] &= plan["evidence_mode"] == "local_lean"
        if outcome["recommended"] is not None:
            result["retained_incumbent"] = None
    if _identity() != plan["implementation_sha256"]:
        result.update(status="INCOMPLETE", reason="implementation_changed_during_selection", recommended=None,
            retained_incumbent=plan["incumbent"], retained_incumbent_verified=False)
    return {**result, "report_sha256": content_hash(result)}


def render_summary(report):
    plan = report["plan"]
    lines = ["# Compact-term selection", "", f"Status: {report['status']}.", "",
        "Historical receipts are nominations, not proof authority. No training, promotion or official score.", "",
        "| Source | Lexical proof-body tokens |", "| --- | ---: |"]
    lines += [f"| {name} | {value if value is not None else 'no candidate'} |" for name, value in plan["tokens"].items()]
    lines += ["", "A token-only rejection performs no new verification and does not certify the retained incumbent.",
        "A recommendation requires fewer tokens AND lower heartbeats than both original and incumbent,",
        "on every pin/order in fresh screening and fixed-winner confirmation.",
        f"Fresh native processes: {report['native_processes']}.", ""]
    if report["selection"]:
        lines.append(selection_summary(report["selection"]))
    return "\n".join(lines)
