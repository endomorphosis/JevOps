"""Goal-only library reuse controls; no supplied solution mapping or training.

The default baseline tries bare constants. Opt-in bare-then-apply additionally
tries one lemma with Lean argument inference and local assumption discharge.
It neither enumerates arbitrary argument terms nor searches lemma compositions.
Inventories are trusted, bounded inputs: this cannot certify that their producer
never saw an evaluation task. Failure is never a novelty certificate.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from .arena import (ArenaContext, ArenaEvaluator, Outcome, TOKENIZER_ID, content_hash,
                    intake_error, reference_tokens, source_hash, strip_comments)
from .arena_lean import NativeLeanVerifier
from .arena_trial import Candidate, _comparison, _pins, run_trial, trial_plan
from .knowledge_index import KnowledgeIndex, SCHEMA as INDEX_SCHEMA
from .knowledge_trial import _validate_contexts
from .premise_search import Premise, PremiseIndex, PremiseScope, PremiseSignature, bounded_int

SCHEMA = "jevops-goal-only-lemma-lookup/v2"
POLICIES = ("direct-scan", "bm25")
APPLICATION_MODES = ("bare", "bare-then-apply")
NO_MATCH = {"bare": "NO_DIRECT_MATCH_IN_SEARCHED_SET",
            "bare-then-apply": "NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET"}


def _candidates(statement, names, mode):
    # Complete the one-token sweep before any longer recipe, within each
    # policy's bounded shortlist. No reference-body replay or new helpers.
    rows = [dict(name=name, method="bare", source=statement + " := _root_." + name + "\n") for name in names]
    if mode == "bare-then-apply":
        rows += [dict(name=name, method="apply-assumption", source=statement +
                      f" := by solve | apply _root_.{name} <;> assumption\n") for name in names]
    return rows


def goal_query(statement: str) -> str:
    """Only the frozen binders/type, not theorem name, reference body or hints.

    This is a lexical query, not a Lean type parser or semantic certificate.
    General named theorem/lemma signatures are accepted; other envelopes fail.
    """
    if type(statement) is not str or not 0 < len(statement.encode()) <= 16384:
        raise ValueError("bounded statement required")
    text = strip_comments(statement).strip()
    match = re.fullmatch(r"(?:theorem|lemma)\s+[^\s(\[{:\n]+\s*((?:[({\[:]).+)", text, re.S)
    if not match or intake_error(statement + " := by skip", statement):
        raise ValueError("unsupported statement envelope")
    return match[1].strip()


def _inventory(index):
    if type(index) is not KnowledgeIndex or index.identity["schema"] != INDEX_SCHEMA:
        raise ValueError("explicit v2 DuckDB snapshot required")
    # Bound setup BEFORE loading payloads. No silent prefix sample of a corpus.
    count, size = index.connection.execute(
        "SELECT count(*), coalesce(sum(octet_length(encode(payload)) + "
        "coalesce(octet_length(encode(signature)), 0)), 0) FROM entries").fetchone()
    if count > 64 or size > 4 * 1024 * 1024:
        raise ValueError("bounded full inventory required; no truncated lookup baseline")
    entries, signatures = [], []
    for payload, sig in index.connection.execute("SELECT payload, signature FROM entries ORDER BY name").fetchall():
        p = json.loads(payload)
        entries.append(Premise(**{**p, "aliases": tuple(p["aliases"]), "dependencies": tuple(p["dependencies"])}))
        if sig is not None:
            signatures.append(PremiseSignature.from_dict(json.loads(sig)))
    return PremiseIndex(tuple(entries), environment_sha256=index.identity["environment_sha256"],
                        signatures=tuple(signatures))


def _implementation():
    files = ("knowledge_lookup.py", "knowledge_index.py", "premise_search.py", "arena.py",
             "arena_lean.py", "arena_trial.py", "knowledge_trial.py", "lean/ArenaCheck.lean")
    return content_hash({f: source_hash(Path(__file__).parent.joinpath(f).read_text()) for f in files})


def lookup_plan(*, record, index, scope, context, top_k=8, max_candidates=64, application_mode="bare"):
    """Freeze the eligible pool and per-policy ceilings before discovery.

    max_candidates caps distinct declarations per policy, as in v1. The opt-in
    mode reserves two recipes per declaration; it never spends unbudgeted work.
    Argument inference/typeclass synthesis may use the frozen environment: this
    is not a checked-term dependency restriction for composition-only scoring.
    """
    bounded_int(top_k, 1, 32)
    bounded_int(max_candidates, 1, 64)
    if type(application_mode) is not str or application_mode not in APPLICATION_MODES:
        raise ValueError("explicit supported application mode required")
    if (type(context) is not ArenaContext or type(scope) is not PremiseScope
            or scope.record_sha256 != content_hash(record) or scope.environment_sha256 != context.context_id
            or context.versions != _pins(record) or context.problem != record["name"]
            or context.statement != record["statement"] or context.reference_source != record["src"]
            or context.reference_heartbeats is not None or intake_error(record["src"], record["statement"])):
        raise ValueError("unchanged all-pin record/context/scope required")
    query = goal_query(record["statement"])
    pool = _inventory(index).scoped_pool(target=record["name"], scope=scope, max_pool=64)
    if pool["status"] != "READY":
        raise ValueError("complete eligible pool required")
    names = [r["name"] for r in pool["entries"]]
    retrieval = index.search(query, target=record["name"], scope=scope, top_k=top_k, max_scan=64)
    ranked = [r["premise"]["name"] for r in retrieval["matches"]]
    if not set(ranked) <= set(names):
        raise ValueError("retrieval departed from baseline scope")
    orders = {"direct-scan": names[:max_candidates], "bm25": ranked[:max_candidates]}
    candidates = {label: _candidates(record["statement"], order, application_mode) for label, order in orders.items()}
    templates = 1 if application_mode == "bare" else 2
    plan = dict(schema=SCHEMA, track="library_reuse", record=record, context=asdict(context),
        snapshot=dict(index.identity), pool=pool, query=query, query_source="statement_without_declaration_name",
        retrieval=retrieval, candidates=candidates, top_k=top_k, max_candidates=max_candidates,
        max_calls=sum(len(rows) for rows in candidates.values()) * len(context.versions),
        application_mode=application_mode, templates_per_declaration=templates,
        per_policy_call_ceiling=max_candidates * templates * len(context.versions),
        selection="first_all_pin_valid_in_frozen_order_not_heartbeat_selection",
        baseline=("bare_library_constant_with_implicit_inference_only" if application_mode == "bare" else
                  "bare_then_single_apply_with_local_assumption_discharge"), tokenizer=TOKENIZER_ID,
        implementation_sha256=_implementation(), training_enabled=False, promoted=False, official_score=None,
        supplied_answer_names=False, inventory_selection_independence_verified=False,
        novelty_claimed=False, composition_claimed=False, graph_structure_isolated=False)
    return {**plan, "plan_sha256": content_hash(plan)}


def run_lookup(plan, *, index, scope, guard, max_calls=0, evidence_mode="local_lean", progress=False):
    """Fresh uncached checks, including all pins for every attempted constant.

    Default zero budget performs no compiler work. Trusted guard/fixture boundary
    is the same as arena_trial. Infrastructure gaps stop that policy, not count
    as failed lemmas. Discovery heartbeats are not a comparative metric.
    """
    if type(guard) is not NativeLeanVerifier or guard.processes:
        raise ValueError("fresh explicit native guard required")
    fresh = lookup_plan(record=plan["record"], index=index, scope=scope, context=guard.context(plan["record"]),
                        top_k=plan["top_k"], max_candidates=plan["max_candidates"], application_mode=plan["application_mode"])
    if content_hash(fresh) != content_hash(plan):
        raise ValueError("stale or mutated lookup plan")
    if type(max_calls) is not int or max_calls != plan["max_calls"]:
        raise ValueError("explicit frozen discovery allowance required")
    evaluator = ArenaEvaluator(guard.context(plan["record"]), guard, max_calls=max_calls,
        evidence_mode=evidence_mode, max_cache_entries=0, context_validator=guard.validate_request)
    policies = {}
    for label in POLICIES:
        starting_calls = evaluator.calls
        rows = []
        result = dict(status=NO_MATCH[plan["application_mode"]], candidate=None, selected_name=None,
                      selected_method=None, attempts=rows, proof_verified=False, composition_claimed=False)
        if label == "bm25" and plan["retrieval"]["status"] != "RANKED":
            result["status"] = plan["retrieval"]["status"]
        for candidate in plan["candidates"][label]:
            if _implementation() != plan["implementation_sha256"]:
                raise ValueError("implementation changed during discovery")
            evaluation = evaluator.evaluate(candidate["source"])
            outcomes = [r.outcome for r in evaluation.receipts]
            complete = (len(outcomes) == len(evaluator.context.versions)
                        and all(o in (Outcome.VERIFIED, Outcome.REJECTED) for o in outcomes))
            rows.append({**candidate, "evaluation": evaluation.to_dict()})
            if progress:
                print(f"{label} [{len(rows)}/{len(plan['candidates'][label])}] {candidate['method']} {candidate['name']}: "
                      + ",".join(o.value for o in outcomes), flush=True)
            if not complete:
                result["status"] = "INCOMPLETE"
                break
            if all(o == Outcome.VERIFIED for o in outcomes):
                result.update(status="FOUND", candidate=candidate["source"], selected_name=candidate["name"],
                              selected_method=candidate["method"], proof_verified=evidence_mode == "local_lean")
                break
        result.update(checked_candidates=len(rows), calls=evaluator.calls - starting_calls,
                      checked_declarations=len({r["name"] for r in rows}),
                      whole_pool_exhausted=(len(rows) == plan["pool"]["eligible_count"] * plan["templates_per_declaration"]
                                            and result["status"] in {"FOUND", *NO_MATCH.values()}),
                      semantic_equivalence_decided=False)
        policies[label] = result
    if _implementation() != plan["implementation_sha256"]:
        raise ValueError("implementation changed during discovery")
    report = dict(schema=SCHEMA, plan_sha256=plan["plan_sha256"], plan=plan, policies=policies,
        evidence_mode=evidence_mode, calls=evaluator.calls, native_processes=guard.processes if evidence_mode == "local_lean" else 0,
        process_allowance=max_calls, receipt_cache_hits=evaluator.cache_hits,
        status="COMPLETE" if all(r["status"] in {"FOUND", *NO_MATCH.values()}
                                 for r in policies.values()) else "INCOMPLETE",
        training_enabled=False, official_score=None, novelty_claimed=False, composition_claimed=False)
    return {**report, "report_sha256": content_hash(report)}


def confirmation_plan(discovery, *, repetitions=2):
    unsigned = {k:v for k,v in discovery.items() if k != "report_sha256"}
    if content_hash(unsigned) != discovery["report_sha256"]:
        raise ValueError("mutated discovery receipt")
    if discovery["plan"]["implementation_sha256"] != _implementation():
        raise ValueError("stale discovery implementation")
    if set(discovery["policies"]) != set(POLICIES):
        raise ValueError("both frozen policies required")
    for label in POLICIES:
        row = discovery["policies"][label]
        if row["status"] == "FOUND":
            expected = dict(name=row["selected_name"], method=row["selected_method"], source=row["candidate"])
            if expected not in discovery["plan"]["candidates"][label]:
                raise ValueError("selected source outside frozen candidate set")
        elif any(row[k] is not None for k in ("candidate", "selected_name", "selected_method")) or row["proof_verified"]:
            raise ValueError("non-found policy cannot claim a discovered proof")
    record = discovery["plan"]["record"]
    candidates = [Candidate(label, row["candidate"] or record["src"],
        f"{label}: {row['status']}; discovery {discovery['report_sha256']}; no novelty claim")
        for label in POLICIES for row in (discovery["policies"][label],)]
    return trial_plan(record, candidates, repetitions=repetitions, allow_identical_sources=True)


def confirm_lookup(plan, discovery, *, verifiers, max_calls=0, progress=False):
    """Separate, order-balanced metric measurement; reused selection is labeled."""
    if content_hash(plan) != content_hash(confirmation_plan(discovery, repetitions=plan["repetitions"])):
        raise ValueError("mutated confirmation plan")
    if type(max_calls) is not int or max_calls != plan["planned_requests"]:
        raise ValueError("explicit confirmation allowance required")
    # Recreate all-pin context from the frozen discovery, then validate each
    # single-pin/order projection with the established ablation boundary.
    raw = discovery["plan"]["context"]
    from .lean import VersionPin
    context = ArenaContext(**{**raw, "versions": tuple(VersionPin(**p) for p in raw["versions"]),
                              "dependency_digests": tuple(raw["dependency_digests"]),
                              "allowed_axioms": tuple(raw["allowed_axioms"])})
    _validate_contexts(context, plan["record"], verifiers)
    candidates = [Candidate(**a) for a in plan["arms"] if a["label"] != "control"]
    trial = run_trial(plan["record"], candidates, verifiers, max_calls=max_calls,
        repetitions=plan["repetitions"], allow_identical_sources=True,
        evidence_mode=discovery["evidence_mode"], progress=progress)
    if discovery["plan"]["implementation_sha256"] != _implementation():
        raise ValueError("implementation changed during confirmation")
    arms = {c.label: c for c in candidates}
    samples = [{**s, "label": "control" if s["label"] == "direct-scan" else s["label"]}
               for s in trial["samples"] if s["label"] in POLICIES]
    comparison = _comparison({**plan["record"], "src": arms["direct-scan"].source}, arms["bm25"], samples, plan["repetitions"])
    eligible = (discovery["evidence_mode"] == "local_lean"
        and all(r["proof_verified"] for r in discovery["policies"].values())
        and all(s["status"] == "VERIFIED" for s in trial["samples"])
        and comparison["status"] == "MEASURED")
    if not eligible:
        comparison.update(status="INCOMPLETE", heartbeat_result="INCOMPLETE", observed_pareto_improvement=None)
    comparison.update(native_pair_verified=eligible,
        identical_sources=arms["direct-scan"].source == arms["bm25"].source,
        novelty_claimed=False, composition_claimed=False, learned_compression_claimed=False)
    return dict(schema="jevops-library-reuse-comparison/v1", discovery_sha256=discovery["report_sha256"],
        measurement=trial, comparison=comparison, original_reference_tokens=reference_tokens(plan["record"]["src"], plan["record"]["statement"]),
        training_enabled=False, promoted=False, official_score=None)


def render_summary(discovery, confirmation):
    """Generate a compact report from receipts; no hand-authored score tables."""
    c = confirmation["comparison"]
    lines = ["# Goal-only library reuse regression", "",
        "Frozen bounded library pool; no supplied solution names in the query. Not a blind benchmark, graph ablation or learning claim.", "",
        f"Original reference: {confirmation['original_reference_tokens']} lexical proof-body tokens.", "",
        f"Application mode: {discovery['plan'].get('application_mode', 'bare')}. Candidate checks count recipes, not distinct declarations.", "",
        "| Policy | Discovery status | Selected declaration | Method | Candidate checks | Tokens |",
        "| --- | --- | --- | --- | ---: | ---: |"]
    for label in POLICIES:
        row = discovery["policies"][label]
        tokens = c["reference_tokens"] if label == "direct-scan" else c["candidate_tokens"]
        lines.append(f"| {label} | {row['status']} | {row['selected_name']} | {row.get('selected_method', 'bare')} | {row['checked_candidates']} | {tokens} |")
    lines += ["", f"BM25 vs direct lookup: {c['heartbeat_result']}; identical sources: {c['identical_sources']}; "
        f"native paired coverage: {c['native_pair_verified']}.", "",
        f"Fresh discovery processes: {discovery['native_processes']}; confirmation processes: {confirmation['measurement']['native_processes']}.",
        "Inventory exports are accounted separately. Non-found policies use unchanged-reference fallback, not discovered proofs.",
        "Lookup covers only the frozen application recipes. Failure does not establish novelty, semantic inequivalence or absence of a compositional proof.", ""]
    if c["native_pair_verified"]:
        lines += ["## Fresh command-elaboration measurements", "",
            "Raw heartbeat units, two branch orders; not end-to-end search or library build costs.", "",
            "| Lean | Order | Original reference | Direct scan | BM25 |",
            "| --- | --- | ---: | ---: | ---: |"]
        observations = {r["label"]: r for r in confirmation["measurement"]["observations"]}
        for s in c["strata"]:
            original = next(r for r in observations["direct-scan"]["strata"]
                            if r["version"] == s["version"] and r["branch_order"] == s["branch_order"])
            lines.append(f"| {s['version']['lean_tag']} | {s['branch_order']} | {original['control_median_raw']} | "
                         f"{s['control_median_raw']} | {s['candidate_median_raw']} |")
        lines.append("")
    return "\n".join(lines)
