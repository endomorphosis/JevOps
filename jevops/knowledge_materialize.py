"""Materialize a nominated lookup application, then independently check it.

Saved discovery is a seed nomination, never fresh verification. Only the seed
tactic is captured/replayed; the reference body is not an extraction input.
Local replay is not whole-proof admission or a token/heartbeat measurement.
"""
from dataclasses import asdict
from pathlib import Path

from .arena import ArenaContext, ArenaEvaluator, Outcome, content_hash, intake_error, reference_tokens, source_hash
from .arena_lean import NativeLeanVerifier
from .arena_local import ArenaLocalRuntime, _identity as local_identity
from .arena_trial import Candidate, _comparison, run_trial, trial_plan
from .knowledge_lookup import POLICIES, _implementation as lookup_identity, confirmation_plan as validate_discovery
from .knowledge_trial import _validate_contexts
from .lean import VersionPin
from .premise_search import bounded_int

SCHEMA = "jevops-lookup-materialization/v1"


def _identity():
    return content_hash(dict(adapter=source_hash(Path(__file__).read_text()),
                             lookup=lookup_identity(), local=local_identity()))


def materialization_plan(discovery, *, context, policy="bm25", node_budget=4096, event_budget=128):
    """Freeze one policy before extraction; no metric-based seed selection."""
    if policy not in POLICIES or type(context) is not ArenaContext:
        raise ValueError("explicit policy and native context required")
    bounded_int(node_budget, 1, 4096)
    bounded_int(event_budget, 1, 128)
    validate_discovery(discovery)  # integrity/current implementation, NOT fresh proof evidence
    if content_hash(asdict(context)) != content_hash(discovery["plan"]["context"]):
        raise ValueError("exact discovery environment required")
    row = discovery["policies"][policy]
    ready = row["status"] == "FOUND" and row["selected_method"] == "apply-assumption"
    record = discovery["plan"]["record"]
    if ready:
        expected = record["statement"] + f" := by solve | apply _root_.{row['selected_name']} <;> assumption\n"
        if row["candidate"] != expected:
            raise ValueError("exact one-lemma recipe required")
    plan = dict(schema=SCHEMA, discovery_sha256=discovery["report_sha256"], record=record,
        context=asdict(context), policy=policy, status="READY" if ready else "NOT_AN_APPLICATION",
        seed=row["candidate"] if ready else None, premise=row["selected_name"] if ready else None,
        evidence_mode=discovery["evidence_mode"], node_budget=node_budget, event_budget=event_budget,
        max_calls=2 * len(context.versions) if ready else 0,
        max_local_processes=2 * len(context.versions) if ready else 0,
        extraction_source="selected_generated_application_only", reference_body_used_for_extraction=False,
        term_policy="exact_wrapper_removed; identical_printed_term_on_all_pins; strictly_shorter_than_application",
        selection="frozen_policy; no_heartbeat_selection", implementation_sha256=_identity(),
        fresh_retrieval=False, novelty_claimed=False, training_enabled=False, promoted=False, official_score=None)
    return {**plan, "plan_sha256": content_hash(plan)}


def _root_event(source, statement, capture):
    """Only the complete generated tactic; never a nested after-state goal."""
    prefix = statement + " := by "
    if not source.startswith(prefix):
        raise ValueError("generated application envelope required")
    raw = source.encode()
    start = len(prefix.encode())
    stop = len(raw.rstrip())
    matches = [e for e in capture["trace"]["events"] if e["status"] == "captured"
               and e["start"] == str(start) and e["end"] == str(stop)
               and len(e["before"]["goals"]) == 1 and not e["after"]["goals"]]
    if len(matches) != 1:
        raise ValueError("unique complete application anchor unavailable")
    return int(matches[0]["id"])


def _term_source(statement, text):
    # This is only envelope surgery, not a parser, type checker or proof.
    if (type(text) is not str or not text.startswith("exact ") or len(text.encode()) > 4096
            or "\x00" in text or "\r" in text):
        raise ValueError("bounded extracted exact term required")
    body = text[6:].strip()
    if not body or "\x00" in body or "\r" in body:
        raise ValueError("invalid extracted term")
    source = statement + " := " + body + "\n"
    if intake_error(source, statement):
        raise ValueError("unsupported extracted source")
    return source


def run_materialization(plan, discovery, *, guard, max_calls=0, max_local_processes=0,
                        local_runner=None, progress=False):
    """Reserve seed checks, all-pin local replay and fresh whole-term checks.

    Fixture injection is only legal in offline_fixture mode. All-pin identical
    printing is deliberately conservative: disagreement abstains, not a win.
    """
    if type(guard) is not NativeLeanVerifier or guard.processes:
        raise ValueError("fresh owned native guard required")
    context = guard.context(plan["record"])
    fresh = materialization_plan(discovery, context=context, policy=plan["policy"],
                                node_budget=plan["node_budget"], event_budget=plan["event_budget"])
    if content_hash(fresh) != content_hash(plan):
        raise ValueError("stale or mutated materialization plan")
    if (type(max_calls) is not int or max_calls != plan["max_calls"]
            or type(max_local_processes) is not int or max_local_processes != plan["max_local_processes"]):
        raise ValueError("explicit frozen whole-source and local allowances required")
    if local_runner is not None and plan["evidence_mode"] != "offline_fixture":
        raise ValueError("fixture local runner cannot supply native evidence")
    evaluator = ArenaEvaluator(context, guard, max_calls=max_calls, evidence_mode=plan["evidence_mode"],
        max_cache_entries=0, context_validator=guard.validate_request)
    runtime = ArenaLocalRuntime(guard, plan["record"], max_processes=max_local_processes,
        node_budget=plan["node_budget"], event_budget=plan["event_budget"], runner=local_runner)
    report = dict(schema=SCHEMA, plan=plan, status="NOT_AN_APPLICATION", seed_check=None,
        extractions=[], extracted_source=None, candidate_check=None, candidate=None, proof_verified=False,
        novelty_claimed=False, composition_claimed=False, training_enabled=False, promoted=False, official_score=None)
    def finish(status):
        if _identity() != plan["implementation_sha256"]:
            raise ValueError("materialization implementation changed during work")
        report.update(status=status, whole_source_calls=evaluator.calls, local_invocations=runtime.attempts,
            local_reserved=runtime.reserved, receipt_cache_hits=evaluator.cache_hits,
            native_processes=(guard.processes + runtime.attempts) if plan["evidence_mode"] == "local_lean" else 0)
        return {**report, "report_sha256": content_hash(report)}
    def passed(evaluation):
        return len(evaluation.receipts) == len(context.versions) and all(r.outcome == Outcome.VERIFIED for r in evaluation.receipts)
    if plan["status"] != "READY":
        return finish("NOT_AN_APPLICATION")
    seed = evaluator.evaluate(plan["seed"])
    report["seed_check"] = seed.to_dict()
    if not passed(seed):
        return finish("SEED_NOT_VERIFIED")
    sources = []
    for pin in context.versions:
        row = dict(pin=pin.to_dict(), capture=runtime.capture(pin, source=plan["seed"]), application=None)
        report["extractions"].append(row)
        if not row["capture"]["ok"]:
            return finish("EXTRACTION_INCOMPLETE")
        try:
            capture = row["capture"]["capture"]
            event = _root_event(plan["seed"], context.statement, capture)
        except (ValueError, KeyError, TypeError) as exc:
            row["reason"] = str(exc)[:300]
            return finish("ANCHOR_UNAVAILABLE")
        application = runtime.discover_application(pin, plan["seed"], capture, event, plan["premise"])
        row["application"] = application
        if not application["ok"] or not application["closing_reproduced"]:
            return finish("EXTRACTION_INCOMPLETE")
        try:
            sources.append(_term_source(context.statement, application["extracted_candidate"]))
        except ValueError as exc:
            row["reason"] = str(exc)[:300]
            return finish("UNSUPPORTED_TERM")
        if progress:
            print(f"materialized {pin.lean_tag}: {reference_tokens(sources[-1], context.statement)} lexical tokens", flush=True)
    if len(set(sources)) != 1:
        return finish("PIN_TERM_DISAGREEMENT")
    report["extracted_source"] = source = sources[0]
    if reference_tokens(source, context.statement) >= reference_tokens(plan["seed"], context.statement):
        return finish("NOT_SHORTER")
    checked = evaluator.evaluate(source)
    report["candidate_check"] = checked.to_dict()
    if not passed(checked):
        return finish("EXTRACTED_SOURCE_NOT_VERIFIED")
    report.update(candidate=source, proof_verified=plan["evidence_mode"] == "local_lean")
    return finish("CHECKED_DRAFT" if report["proof_verified"] else "FIXTURE_DRAFT")


def measurement_plan(report, *, repetitions=2):
    if content_hash({k: v for k, v in report.items() if k != "report_sha256"}) != report["report_sha256"]:
        raise ValueError("mutated materialization receipt")
    if report["plan"]["implementation_sha256"] != _identity():
        raise ValueError("stale materialization implementation")
    if report["candidate"] is not None and report["status"] not in {"CHECKED_DRAFT", "FIXTURE_DRAFT"}:
        raise ValueError("abstention cannot claim an extracted candidate")
    record = report["plan"]["record"]
    application = report["plan"]["seed"] or record["src"]
    provenance = "materialization " + report["report_sha256"]
    return trial_plan(record, [Candidate("application", application, provenance),
        Candidate("compact", report["candidate"] or application, provenance + "; unchanged fallback on abstention")],
        repetitions=repetitions, allow_identical_sources=True)


def measure_materialization(plan, report, *, verifiers, max_calls=0, progress=False):
    if content_hash(plan) != content_hash(measurement_plan(report, repetitions=plan["repetitions"])):
        raise ValueError("mutated materialization measurement plan")
    if type(max_calls) is not int or max_calls != plan["planned_requests"]:
        raise ValueError("explicit frozen measurement allowance required")
    raw = report["plan"]["context"]
    context = ArenaContext(**{**raw, "versions": tuple(VersionPin(**p) for p in raw["versions"]),
        "dependency_digests": tuple(raw["dependency_digests"]), "allowed_axioms": tuple(raw["allowed_axioms"])})
    _validate_contexts(context, plan["record"], verifiers)
    candidates = [Candidate(**r) for r in plan["arms"] if r["label"] != "control"]
    trial = run_trial(plan["record"], candidates, verifiers, max_calls=max_calls,
        repetitions=plan["repetitions"], evidence_mode=report["plan"]["evidence_mode"],
        allow_identical_sources=True, progress=progress)
    if report["plan"]["implementation_sha256"] != _identity():
        raise ValueError("implementation changed during measurement")
    arms = {r.label: r for r in candidates}
    samples = [{**s, "label": "control" if s["label"] == "application" else s["label"]}
               for s in trial["samples"] if s["label"] != "control"]
    comparisons = dict(versus_application=_comparison({**plan["record"], "src": arms["application"].source},
                          arms["compact"], samples, plan["repetitions"]),
                      versus_reference=next(o for o in trial["observations"] if o["label"] == "compact"))
    eligible = (report["proof_verified"] and report["status"] == "CHECKED_DRAFT"
        and report["plan"]["evidence_mode"] == "local_lean"
        and all(s["status"] == "VERIFIED" for s in trial["samples"])
        and all(c["status"] == "MEASURED" for c in comparisons.values()))
    for comparison in comparisons.values():
        if not eligible:
            comparison.update(status="INCOMPLETE", heartbeat_result="INCOMPLETE", observed_pareto_improvement=None)
        comparison.update(native_pair_verified=eligible, novelty_claimed=False, learned_compression_claimed=False)
    return dict(schema="jevops-materialization-measurement/v1", materialization_sha256=report["report_sha256"],
        measurement=trial, **comparisons, training_enabled=False, promoted=False, official_score=None)


def render_summary(report, measured):
    a, r = measured["versus_application"], measured["versus_reference"]
    lines = ["# Checked application-term materialization", "",
        "Saved lookup used only as a seed nomination. No fresh retrieval, learning, novelty or blind-benchmark claim.", "",
        f"Status: {report['status']}; native paired coverage: {r['native_pair_verified']}.", "",
        "| Source | Lexical proof-body tokens |", "| --- | ---: |",
        f"| Original reference | {r['reference_tokens']} |",
        f"| Generated application | {a['reference_tokens']} |",
        f"| Extracted term (fallback on abstention) | {r['candidate_tokens']} |", "",
        f"Heartbeats versus application: {a['heartbeat_result']}; versus original reference: {r['heartbeat_result']}.",
        f"Measured joint improvement versus original reference: {r['observed_pareto_improvement']}.", "",
        f"Fresh materialization processes: {report['native_processes']}; separate metric processes: {measured['measurement']['native_processes']}.",
        "Abstention/failure never earns a discovered-proof or compression reward. No training or promotion.", ""]
    if r["native_pair_verified"]:
        lines += ["| Lean | Order | Reference raw HB | Application raw HB | Compact raw HB |",
                  "| --- | --- | ---: | ---: | ---: |"]
        for x, y in zip(a["strata"], r["strata"], strict=True):
            lines.append(f"| {x['version']['lean_tag']} | {x['branch_order']} | {y['control_median_raw']} | "
                         f"{x['control_median_raw']} | {x['candidate_median_raw']} |")
        lines.append("")
    return "\n".join(lines)
