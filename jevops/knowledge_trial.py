"""Frozen mapped-premise injection ablation, not a graph-learning benchmark.

Both policies share constructive search ceilings and one output slot. Actual
work differs: the mapped arm resolves evidence and adds premises. Abstention
falls back to the unchanged source, never to a fabricated successful proposal.
The native trial measures every fixed arm afresh in both elaboration orders.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

from .arena import (ArenaContext, TOKENIZER_ID, VerificationRequest, content_hash,
                    intake_error, reference_tokens, source_hash)
from .arena_trial import Candidate, ORDERS, _comparison, _pins, run_trial, trial_plan
from .constructive_proofs import read_proposition, search
from .constructive_terms import render_tree
from .knowledge_relations import RelationLimits, propose_relations
from .logic_ir import Formula, render_formula
from .proof_ca import canonical_json


RENDERINGS = ("local-term", "typed-inline", "inferred-term")


def _local_proposal(record, limits, include_term_ir=False):
    report = {"status": "NO_PLAN", "candidate": None, "search_states": 0, "used_edges": [],
              "proof_verified": False}
    try:
        _, goal, assumptions = read_proposition(record["src"])
    except ValueError as exc:
        return {**report, "status": "UNSUPPORTED", "reason": str(exc)}
    result = search(goal, assumptions, max_states=limits.max_states,
                    max_depth=limits.max_depth, max_facts=limits.max_facts, include_term_ir=include_term_ir)
    report["search_states"] = result["states"]
    if result["budget_exhausted"]:
        return {**report, "status": "SEARCH_BUDGET"}
    if result["term"] is None:
        return report
    source = record["statement"] + " := by\n  exact " + result["term"] + "\n"
    if len(source.encode()) > limits.max_candidate_bytes:
        return {**report, "status": "CANDIDATE_BUDGET"}
    if intake_error(source, record["statement"]):
        return {**report, "status": "UNSUPPORTED"}
    return {**report, "status": "PROPOSED", "candidate": source,
            **({"term_ir": result["term_ir"]} if include_term_ir else {})}


def _render_proposal(mode, original, graph, index, record, limits):
    """Only called on freshly regenerated structured search output, never an LLM edit."""
    report = dict(status=original["status"], candidate=None, used_edges=[],
        search_states=original["search_states"], rendering=mode, proof_verified=False,
        mapping_witness_required=mode != "local-term", source_fidelity_verified=False,
        witness_proposal_sha256=original.get("proposal_sha256"))
    if original["status"] != "PROPOSED":
        return report
    if original.get("term_ir") is None:
        return {**report, "status": "IR_UNAVAILABLE"}
    bindings = {b.edge_id: b for b in graph.bindings}
    relations = {r.edge_id: r for r in graph.relations}
    nodes = {n.node_id: n.proposition for n in graph.nodes}
    replacements = {}
    for name, edge in original.get("mapped_locals", {}).items():
        b, relation = bindings[edge], relations[edge]
        expected = Formula("imp" if relation.kind == "implies" else "iff",
                           (nodes[relation.subject], nodes[relation.object]))
        explicit = "@_root_." + b.declaration + "".join(" (" + render_formula(a) + ")" for a in b.arguments)
        if mode == "typed-inline":
            replacements[name] = ("(" + explicit + " : " + render_formula(expected) + ")", True)
        else:
            kinds = index.signatures[b.declaration].binder_kinds[:len(b.arguments)]
            # Only a wholly implicit supplied prefix is omitted. Explicit
            # proposition parameters are not silently erased or re-ordered.
            inferred = all(k in {"implicit", "strict_implicit"} for k in kinds)
            replacements[name] = ("_root_." + b.declaration, True) if inferred else (explicit, False)
    try:
        source = record["statement"] + " := " + render_tree(original["term_ir"], replacements) + "\n"
    except ValueError as exc:
        return {**report, "status": "RENDERING_UNSUPPORTED", "reason": str(exc)}
    if len(source.encode()) > limits.max_candidate_bytes:
        return {**report, "status": "CANDIDATE_BUDGET"}
    if intake_error(source, record["statement"]):
        return {**report, "status": "RENDERING_UNSUPPORTED"}
    return {**report, "status": "PROPOSED", "candidate": source, "used_edges": original["used_edges"]}


def relation_trial_plan(graph, *, record, index, scope, corpus, discovery_context: ArenaContext,
                        excluded_cids=(), limits=RelationLimits(), repetitions=2, seed=17, renderings=()):
    """No compiler calls. Freeze both policies, bounds, full sources and schedule.

    Discovery context is the ALL-pin inventory environment. Trial contexts may
    differ only by pin projection and branch order, checked before execution.
    Identity hashes detect changes; they do not attest external source fidelity.
    """
    if (type(renderings) is not tuple or len(renderings) > len(RENDERINGS)
            or any(type(r) is not str or r not in RENDERINGS for r in renderings)
            or len(set(renderings)) != len(renderings)):
        raise ValueError("unique allowlisted rendering tuple required")
    if renderings and "local-term" not in renderings:
        raise ValueError("compact local control required for rendering comparisons")
    if (type(discovery_context) is not ArenaContext
            or discovery_context.context_id != graph.environment_sha256
            or discovery_context.versions != _pins(record)
            or discovery_context.problem != record["name"]
            or discovery_context.statement != record["statement"]
            or discovery_context.reference_source != record["src"]
            or discovery_context.reference_heartbeats is not None):
        raise ValueError("unchanged uncalibrated all-pin discovery context required")
    mapped = propose_relations(graph, record=record, index=index, scope=scope, corpus=corpus,
                               excluded_cids=excluded_cids, limits=limits, include_term_ir=bool(renderings))
    local = _local_proposal(record, limits, include_term_ir=bool(renderings))
    policies = {"local-only": local, "mapped-relations": mapped}
    for mode in renderings:
        policies[mode] = _render_proposal(mode, local if mode == "local-term" else mapped, graph, index, record, limits)
    candidates = [Candidate(label, proposal["candidate"] or record["src"],
                    "fixed policy: " + label + "; " + proposal["status"] +
                    ("; unchanged fallback" if proposal["candidate"] is None else "; unverified draft"))
                  for label, proposal in policies.items()]
    measurement = trial_plan(record, candidates, repetitions=repetitions, seed=seed, allow_identical_sources=True)
    plan = {"schema": "jevops-relation-trial-plan/v1", "measurement_plan": measurement,
            "discovery_context": asdict(discovery_context), "graph": graph.to_dict(),
            "limits": asdict(limits), "excluded_cids": sorted(set(excluded_cids)), "policies": policies,
            "budget_contract": {"search_ceilings_matched": True, "actual_work_matched": False,
                "candidate_cap_per_arm": 1, "verification_slots_per_arm": measurement["planned_requests"] // (len(policies) + 1),
                "inventory_and_evidence_costs_in_measurement": False},
            "contrast": "mapped-premise injection versus local-only constructive search",
            "graph_structure_isolated": False, "learned_graph_encoder": False,
            "tokenizer": TOKENIZER_ID, "proof_verified": False, "source_fidelity_verified": False,
            "training_enabled": False, "promoted": False, "official_score": None,
            "implementation_sha256": content_hash({name: source_hash(Path(__file__).with_name(name).read_text())
                for name in ("knowledge_trial.py", "knowledge_relations.py", "constructive_proofs.py", "constructive_terms.py", "arena_trial.py")})}
    if renderings:
        plan.update(schema="jevops-relation-trial-plan/v2", renderings=list(renderings),
            rendering_contract={"search_reused": True, "native_witness_required": True,
                "expected_type_inference_not_mapping_authority": True, "candidates_selected_after_measurement": False})
    return {**plan, "plan_sha256": content_hash(plan)}


def _validate_contexts(discovery_context, record, verifiers):
    """No pin omissions or dependency/option changes disguised as an ablation."""
    allowed = {(p, order) for p in discovery_context.versions for order in ORDERS}
    if set(verifiers) != allowed:
        raise ValueError("all required pin/order verifiers required")
    for (pin, order), verifier in verifiers.items():
        options = json.loads(discovery_context.verifier_options_json)
        if options.get("branch_order") not in ORDERS or verifier.branch_order != order:
            raise ValueError("order-bound discovery and measurement contexts required")
        options["branch_order"] = order
        expected = replace(discovery_context, versions=(pin,),
            dependency_digests=(discovery_context.dependency_digests[discovery_context.versions.index(pin)],),
            verifier_options_json=canonical_json(options))
        actual = verifier.context({**record, "version_info": [{pin.lean_tag: pin.git_commit}]})
        if actual != expected:
            raise ValueError("measurement must project the exact discovery environment")
        verifier.validate_request(VerificationRequest(actual, record["src"], pin))


def _policy_comparison(trial, policies, candidate_label="mapped-relations", baseline_label="local-only"):
    # Reuse the order/noise rules, but compare mapped against local, not against
    # the original proof. Source-based token counts also use the local baseline.
    arms = {a["label"]: Candidate(**a) for a in trial["arms"]}
    baseline = {**trial["record"], "src": arms[baseline_label].source}
    samples = [{**s, "label": "control" if s["label"] == baseline_label else s["label"]}
               for s in trial["samples"] if s["label"] in {candidate_label, baseline_label}]
    comparison = _comparison(baseline, arms[candidate_label], samples, trial["repetitions"])
    # A failed original control invalidates the experiment even if both new
    # drafts happened to elaborate. Never claim an improvement from that run.
    controls_passed = all(s["status"] == "VERIFIED" for s in trial["samples"] if s["label"] == "control")
    mapped = policies[candidate_label]
    needs_witness = mapped.get("mapping_witness_required", False)
    witness = [s for s in trial["samples"] if s["label"] == "mapped-relations"]
    witness_passed = (policies["mapped-relations"]["status"] == "PROPOSED"
        and len(witness) == 2 * trial["repetitions"] * len(_pins(trial["record"]))
        and all(s["status"] == "VERIFIED" for s in witness))
    if not controls_passed or (needs_witness and not witness_passed):
        comparison.update(status="INCOMPLETE", heartbeat_result="INCOMPLETE", observed_pareto_improvement=None)
    if mapped["status"] != "PROPOSED":
        # Measured fallback costs stay visible, but no generated graph edit won.
        comparison["observed_pareto_improvement"] = None
    native = trial["evidence_mode"] == "local_lean" and comparison["status"] == "MEASURED"
    return {**comparison, "baseline_policy": baseline_label, "candidate_policy": candidate_label,
            "unchanged_controls_passed": controls_passed,
            "identical_policy_sources": arms[baseline_label].source == arms[candidate_label].source,
            "abstained": [label for label, p in policies.items() if p["candidate"] is None],
            "proof_verified": native, "checked_edges": mapped["used_edges"] if native else [],
            "checked_edges_evidence": "original_typed_witness" if candidate_label == "inferred-term" else "candidate_obligations",
            "graph_proposal_verified": native and mapped["status"] == "PROPOSED",
            **({"mapping_witness_passed": witness_passed,
                "mapping_witness_verified": witness_passed and trial["evidence_mode"] == "local_lean",
                "mapping_correspondence_verified": native and mapped["status"] == "PROPOSED" and candidate_label == "typed-inline"}
               if needs_witness else {}),
            "source_fidelity_verified": False, "minimality_proven": False}


def run_relation_trial(plan, graph, *, record, index, scope, corpus, discovery_context,
                       verifiers, excluded_cids=(), max_calls=0, evidence_mode="local_lean", progress=False):
    """Re-resolve frozen evidence/scope, then measure; no training or promotion.

    Trusted caller owns stable artifacts and bounded prepared verifiers. This
    runner neither installs dependencies nor mutates prepared environments.
    Setup/export processes are outside max_calls and must be budgeted separately.
    """
    fresh = relation_trial_plan(graph, record=record, index=index, scope=scope, corpus=corpus,
        discovery_context=discovery_context, excluded_cids=excluded_cids, limits=RelationLimits(**plan["limits"]),
        repetitions=plan["measurement_plan"]["repetitions"], seed=plan["measurement_plan"]["seed"],
        renderings=tuple(plan.get("renderings", ())))
    # JSON preserves these immutable values but serializes tuples as arrays.
    # Compare the same strict canonical representation used by plan identities.
    if content_hash(fresh) != content_hash(plan):
        raise ValueError("stale or mutated frozen relation trial")
    _validate_contexts(discovery_context, record, verifiers)
    candidates = [Candidate(**c) for c in fresh["measurement_plan"]["arms"] if c["label"] != "control"]
    trial = run_trial(record, candidates, verifiers, max_calls=max_calls,
        repetitions=fresh["measurement_plan"]["repetitions"], seed=fresh["measurement_plan"]["seed"],
        evidence_mode=evidence_mode, progress=progress, allow_identical_sources=True)
    paired = _policy_comparison(trial, fresh["policies"])
    return {"schema": "jevops-relation-trial/v2" if fresh.get("renderings") else "jevops-relation-trial/v1",
            "plan": fresh, "measurement": trial,
            "comparison": paired, "status": trial["status"],
            **({"rendering_comparisons": {label: {
                "versus_compact_local": _policy_comparison(trial, fresh["policies"], label, "local-term"),
                "versus_scaffolded": _policy_comparison(trial, fresh["policies"], label, "mapped-relations")}
                for label in fresh["renderings"] if label != "local-term"}} if fresh.get("renderings") else {}),
            "training_enabled": False, "promoted": False, "official_score": None,
            "source_fidelity_verified": False, "graph_structure_isolated": False,
            "end_to_end_cost_measured": False}


def render_summary(reports, negative_controls=None):
    """Small generated receipt summary; full observations remain in JSON."""
    lines = ["# Mapped-premise injection controls", "",
        "Synthetic evidence provenance; real Lean library declarations. Not the all-15 Arena,",
        "a graph-structure ablation, training evidence, or an official score.", "",
        "| Case | Reference tokens | Local tokens | Mapped tokens | Mapped vs local heartbeats | Status |",
        "| --- | ---: | ---: | ---: | --- | --- |"]
    for name, report in reports.items():
        trial, comparison = report["measurement"], report["comparison"]
        tokens = {a["label"]: reference_tokens(a["source"], trial["record"]["statement"]) for a in trial["arms"]}
        lines.append(f"| {name} | {tokens['control']} | {tokens['local-only']} | {tokens['mapped-relations']} | "
                     f"{comparison['heartbeat_result']} | {report['status']} |")
    compact = {name: report for name, report in reports.items() if report.get("rendering_comparisons")}
    if compact:
        lines.extend(["", "## Frozen rendering variants", "",
            "| Case | Compact local tokens | Typed inline tokens | Inferred term tokens | Inferred vs compact local heartbeats | Inferred vs scaffold heartbeats |",
            "| --- | ---: | ---: | ---: | --- | --- |"])
        for name, report in compact.items():
            trial = report["measurement"]
            tokens = {a["label"]: reference_tokens(a["source"], trial["record"]["statement"]) for a in trial["arms"]}
            inferred = report["rendering_comparisons"].get("inferred-term", {})
            status = lambda label: inferred.get(label, {}).get("heartbeat_result", "NOT_RUN")
            lines.append(f"| {name} | {tokens.get('local-term', 'NOT_RUN')} | {tokens.get('typed-inline', 'NOT_RUN')} | "
                f"{tokens.get('inferred-term', 'NOT_RUN')} | {status('versus_compact_local')} | {status('versus_scaffolded')} |")
        lines.extend(["", "Implicit inference is not evidence of the supplied instantiation. A passing original",
            "typed witness is mandatory; shorter drafts do not independently certify graph correspondence."])
    for name, report in (negative_controls or {}).items():
        gate = report["rendering_comparisons"]["inferred-term"]["versus_compact_local"]
        lines.extend(["", f"Negative control `{name}`: mapping witness passed = {gate['mapping_witness_passed']}; "
            f"graph proposal verified = {gate['graph_proposal_verified']}; comparison = {gate['status']}."])
    lines.extend(["", "Matched search ceilings, not matched primitive work. Two branch orders; fresh",
        "process per sample; no receipt reuse. Raw heartbeat strata and exact sources are in the JSON.",
        "Setup/evidence ingestion costs are not included in proof-elaboration heartbeats.", ""])
    return "\n".join(lines)
