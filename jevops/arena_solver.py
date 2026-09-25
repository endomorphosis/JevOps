"""Bounded solver specialization in the existing Arena verification boundary.

Single-process, deterministic discovery. Every node is a complete source,
checked on ONE explicit pin, not a promoted incumbent or all-pin cost winner.
No model, global hooks, disk cache, training or implicit toolchain provisioning.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from fractions import Fraction
import json
from pathlib import Path
import time

from .arena import (ArenaContext, ArenaEvaluator, Outcome, VerificationRequest,
                    content_hash, intake_error, reference_tokens, source_hash)
from .premise_search import bounded_int
from .solver_feedback import diagnostic_edits, query_sites, support_edits

LEGACY_MODES = ("suggestions-v1", "minimize-v1", "frontier-v1")
MODES = (*LEGACY_MODES, "balanced-frontier-v1")
DRAFT_POLICIES = ("shortest-v1", "discovery-dual-first-v1", "discovery-aggregate-v1",
                  "discovery-reference-v1")
SCHEMA = "jevops-arena-solver-frontier/v1"


@dataclass(frozen=True)
class SolverLimits:
    max_calls: int = 16
    max_states: int = 12
    max_depth: int = 3
    max_sites: int = 4
    max_proposals: int = 128
    max_source_bytes: int = 65536
    max_frontier_bytes: int = 262144
    max_drafts: int = 4

    def __post_init__(self):
        for field, low, high in (("max_calls", 0, 64), ("max_states", 1, 16),
                ("max_depth", 0, 4), ("max_sites", 0, 8), ("max_proposals", 0, 256),
                ("max_source_bytes", 1, 65536), ("max_frontier_bytes", 1, 1048576),
                ("max_drafts", 0, 8)):
            bounded_int(getattr(self, field), low, high)


def _implementation():
    root = Path(__file__).parent
    return {name: source_hash((root / name).read_text()) for name in
            ("arena_solver.py", "solver_feedback.py", "arena.py")}


def _observation(receipt, request):
    """Validate cost/diagnostic observations AFTER the typed receipt boundary."""
    observed = json.loads(receipt.observations_json)
    r = observed["report"]
    ctx, pin = request.context, request.version
    if (observed["measurement"] != ctx.heartbeat_method
            or observed["dependency_digest"] != ctx.dependency_digests[ctx.versions.index(pin)]
            or observed["lean_version"] != pin.lean_tag.removeprefix("v")
            or observed["branch_order"] != json.loads(ctx.verifier_options_json)["branch_order"]
            or r["type_preserved"] is not True or r["target_absent_before"] is not True):
        raise ValueError("foreign solver observation")
    for name in ("raw_heartbeats", "heartbeats", "reference_raw_heartbeats", "reference_heartbeats"):
        bounded_int(r[name], 0, 2**63 - 1)
    if (r["raw_heartbeats"] // 1000 != r["heartbeats"] or receipt.heartbeats != r["heartbeats"]
            or r["reference_raw_heartbeats"] // 1000 != r["reference_heartbeats"]):
        raise ValueError("inconsistent solver cost units")
    for name in ("axioms", "reference_axioms"):
        if type(r[name]) is not list or any(type(a) is not str for a in r[name]):
            raise ValueError("malformed solver axiom observation")
    if set(r["axioms"]) - set(r["reference_axioms"]) or set(r["reference_axioms"]) - set(ctx.allowed_axioms):
        raise ValueError("solver axiom expansion")
    diagnostics = r.get("diagnostics", [])
    if type(diagnostics) is not list or len(diagnostics) > 256:
        raise ValueError("solver diagnostic limit")
    spans = r.get("solver_spans")
    if spans is not None:
        query_sites(request.source, spans)  # Validate the bound inventory now.
    return r["raw_heartbeats"], diagnostics, spans, r["reference_raw_heartbeats"]


def discover_solver_frontier(context: ArenaContext, source: str, pin, verifier, *,
        context_validator, evidence_mode: str, mode: str = "frontier-v1",
        limits: SolverLimits = SolverLimits(), draft_policy: str = "shortest-v1") -> dict:
    """Nominate drafts through whole-source checked intermediate states.

    suggestions-v1: only immediately shorter suggestions; legacy-like control.
    minimize-v1: also delete explicit support entries, still immediately shorter.
    frontier-v1: retain checked longer/equal intermediate states as well.
    balanced-frontier-v1: one support try, then hints and immediate hint-child
    expansion, then remaining support tries. Bounded portfolio, not fairness.

    Legacy modes use FIFO expansion and first-fit state/byte caps. Balanced
    mode preempts FIFO for accepted hint children, within the same hard caps.
    Exact-source deduplication applies to all modes. A reported Pareto set does
    not silently prune exploration. Heartbeats here are single-sample discovery
    observations, never confirmation evidence.
    """
    if (type(context) is not ArenaContext or pin not in context.versions
            or type(limits) is not SolverLimits or type(mode) is not str or mode not in MODES):
        raise ValueError("explicit solver context, pin, mode and limits required")
    if context_validator is None or not callable(context_validator):
        raise ValueError("explicit live context validator required")
    if type(draft_policy) is not str or draft_policy not in DRAFT_POLICIES:
        raise ValueError("explicit supported draft policy required")
    if draft_policy == "discovery-reference-v1" and pin != context.versions[0]:
        raise ValueError("reference-normalized nomination requires the primary pin")
    if (intake_error(source, context.statement) or len(source.encode()) > limits.max_source_bytes
            or len(source.encode()) > limits.max_frontier_bytes):
        raise ValueError("invalid solver seed or source byte limit")
    implementation = _implementation()
    plan = dict(schema=SCHEMA, context_id=context.context_id, source_sha256=source_hash(source),
                pin=pin.to_dict(), mode=mode, limits=asdict(limits), implementation=implementation,
                evidence_mode=evidence_mode, draft_policy=draft_policy)
    if draft_policy == "discovery-reference-v1":
        plan.update(normalization="original source tokens and original raw heartbeat observation from seed request",
                    nomination_formula="(seed_tokens-candidate_tokens)/original_tokens + "
                                       "(seed_raw-candidate_raw)/original_raw",
                    normalization_attempt=0)
    plan["plan_id"] = content_hash(plan)
    evaluator = ArenaEvaluator(context, verifier, max_calls=limits.max_calls, evidence_mode=evidence_mode,
        context_validator=context_validator, max_cache_entries=0, max_cache_bytes=0)
    attempts, nodes, edits, queue = [], [], [], deque()
    # Deduplication suppresses repeated WORK, not a fresh verification event.
    seen = {source_hash(source)}
    probed = set()
    omitted = dict(duplicate=0, unsupported=0, not_shorter=0, state_limit=0, byte_limit=0,
                   support_windows=0, query_sites=0, draft_limit=0)
    stopped = None
    proposals = retained_bytes = 0
    started = time.monotonic()

    def check(text, kind):
        nonlocal stopped
        if evaluator.calls >= limits.max_calls:
            stopped = "BUDGET_EXHAUSTED"
            return None
        if _implementation() != implementation:
            stopped = "ERROR"
            return None
        request = VerificationRequest(context, text, pin)
        receipt = evaluator.verify_request(request)
        row = dict(kind=kind, source_sha256=source_hash(text), receipt=asdict(receipt))
        attempts.append(row)
        if receipt.outcome not in (Outcome.VERIFIED, Outcome.REJECTED):
            stopped = receipt.outcome.value
            return None
        if receipt.outcome == Outcome.REJECTED:
            return None
        try:
            result = _observation(receipt, request)
        except (ValueError, KeyError, TypeError) as exc:
            row["observation_error"] = str(exc)[:250]
            stopped = "ERROR"
            return None
        return result, len(attempts) - 1

    def add(text, depth, parent, check_result):
        nonlocal retained_bytes
        (cost, _, spans, reference_cost), receipt_index = check_result
        node = dict(id=len(nodes), source=text, source_sha256=source_hash(text),
                    tokens=reference_tokens(text, context.statement), raw_heartbeats=cost,
                    depth=depth, parent=parent, attempt=receipt_index, solver_spans=spans,
                    reference_raw_heartbeats=reference_cost)
        nodes.append(node)
        retained_bytes += len(text.encode())
        queue.append(node)

    root = check(source, "seed")
    if root is not None:
        add(source, 0, None, root)

    def attempt_edit(parent, edit):
        nonlocal proposals, stopped
        if stopped:
            return
        if proposals >= limits.max_proposals:
            stopped = "BUDGET_EXHAUSTED"
            return
        proposals += 1
        text = edit.apply(parent["source"])
        digest = source_hash(text)
        if digest in seen:
            omitted["duplicate"] += 1
            return
        seen.add(digest)
        if len(text.encode()) > limits.max_source_bytes or intake_error(text, context.statement):
            omitted["unsupported"] += 1
            return
        if mode in ("suggestions-v1", "minimize-v1") and reference_tokens(text, context.statement) >= parent["tokens"]:
            omitted["not_shorter"] += 1
            return
        if len(nodes) >= limits.max_states:
            omitted["state_limit"] += 1
            return
        if retained_bytes + len(text.encode()) > limits.max_frontier_bytes:
            omitted["byte_limit"] += 1
            return
        result = check(text, edit.kind)
        edits.append(dict(parent=parent["id"], edit=asdict(edit), candidate_sha256=digest,
                          retained=result is not None))
        if result is not None:
            add(text, parent["depth"] + 1, parent["id"], result)
            return nodes[-1]

    expanded = set()

    def expand(node):
        if stopped or node["id"] in expanded or node["depth"] >= limits.max_depth:
            return
        expanded.add(node["id"])
        # Each changed source is checked with its original continuation. Empty
        # support is just a try. Balanced mode delays the remaining deletions.
        support = []
        if mode != "suggestions-v1":
            # One lookahead site makes truncation observable, even at zero.
            support = support_edits(node["source"], max_sites=limits.max_sites + 1)
            starts = list(dict.fromkeys(e.start for e in support))
            omitted["support_windows"] += int(len(starts) > limits.max_sites)
            support = [e for e in support if e.start in starts[:limits.max_sites]]
            early = support[:1] if mode == "balanced-frontier-v1" else support
            for edit in early:
                attempt_edit(node, edit)
                if stopped:
                    break
        if stopped:
            return
        sites = query_sites(node["source"], node["solver_spans"])
        omitted["query_sites"] += max(0, len(sites) - limits.max_sites)
        for site in sites[:limits.max_sites]:
            probe = site["probe"]
            if len(probe.encode()) > limits.max_source_bytes:
                omitted["unsupported"] += 1
                continue
            digest = source_hash(probe)
            if digest in probed:
                omitted["duplicate"] += 1
                continue
            probed.add(digest)
            result = check(probe, "suggestion-probe")
            if result is not None:
                (_, diagnostics, _, _), _ = result
                for edit in diagnostic_edits(node["source"], site, diagnostics):
                    child = attempt_edit(node, edit)
                    # Consume the remaining slots on this newly checked path
                    # before root siblings can occupy all of them. Recursion
                    # is bounded by max_depth <= 4; queued expansion is deduped.
                    if child is not None and mode == "balanced-frontier-v1":
                        expand(child)
                    if stopped:
                        break
            if stopped:
                break
        if mode == "balanced-frontier-v1":
            for edit in support[1:]:
                if stopped:
                    break
                attempt_edit(node, edit)

    while queue and not stopped:
        expand(queue.popleft())

    # Evidence remains historical if dependencies change after the last call.
    context_applicable = True
    try:
        context_validator(VerificationRequest(context, source, pin))
        if _implementation() != implementation:
            raise ValueError("solver implementation changed")
    except Exception:
        context_applicable = False
        stopped = "ERROR"
    eligible = [] if stopped == "ERROR" else list(nodes[1:])
    # Single-pin cost is ONLY a nomination heuristic. Both arms of the balanced
    # comparison use it; fresh all-pin/order screening and confirmation remain
    # mandatory. Keep a smaller tradeoff draft if no dual-looking node exists.
    nomination = None
    if draft_policy == "discovery-reference-v1":
        # Use one shared, fresh ORIGINAL denominator for every node. In
        # particular, neither the incumbent's costs nor published/display-unit
        # heartbeat fields can supply this denominator. The seed receipt's
        # independently elaborated reference branch binds it to this context.
        reference_length = reference_tokens(context.reference_source, context.statement)
        reference_raw = nodes[0]["reference_raw_heartbeats"] if nodes else None
        nomination = dict(reference_source_sha256=source_hash(context.reference_source),
            reference_tokens=reference_length, reference_raw_heartbeats=reference_raw,
            reference_attempt=0 if nodes else None,
            reference_request_id=attempts[0]["receipt"]["request_id"] if nodes else None,
            gains=[], reason="", scope="single-primary-pin discovery estimate; not confirmation")
        if not nodes or not reference_length or not reference_raw:
            eligible = []
            nomination["reason"] = "missing_or_zero_reference_denominator"
        else:
            seed = nodes[0]
            def gain(node):
                return (Fraction(seed["tokens"] - node["tokens"], reference_length)
                        + Fraction(seed["raw_heartbeats"] - node["raw_heartbeats"], reference_raw))
            nomination["gains"] = [dict(node_id=n["id"],
                normalized_sum=dict(numerator=gain(n).numerator, denominator=gain(n).denominator))
                for n in eligible]
            eligible = [n for n in eligible if gain(n) > 0]
            eligible.sort(key=lambda n: (-gain(n), n["tokens"], n["id"]))
    elif draft_policy == "discovery-aggregate-v1":
        # Opt-in: a longer proof can be a useful final draft. These denominators
        # belong to the checked discovery seed, NOT a published Arena score.
        # No zero-to-one default and no positive claim without both denominators.
        if not nodes or not nodes[0]["tokens"] or not nodes[0]["raw_heartbeats"]:
            eligible = []
        else:
            seed = nodes[0]
            def gain(node):
                return (Fraction(seed["tokens"] - node["tokens"], seed["tokens"])
                        + Fraction(seed["raw_heartbeats"] - node["raw_heartbeats"], seed["raw_heartbeats"]))
            eligible = [n for n in eligible if gain(n) > 0]
            eligible.sort(key=lambda n: (-gain(n), n["tokens"], n["id"]))
    else:
        eligible = [n for n in eligible if
            n["tokens"] < min(reference_tokens(source, context.statement), context.reference_length)]
        eligible.sort(key=lambda n: (
            int(draft_policy == "discovery-dual-first-v1" and
                n["raw_heartbeats"] >= nodes[0]["raw_heartbeats"]),
            n["tokens"], n["raw_heartbeats"], n["id"]))
    omitted["draft_limit"] = max(0, len(eligible) - limits.max_drafts)
    drafts = [dict(name=context.problem, label=f"solver-{n['id']}", source=n["source"],
                   provenance=f"{mode}; single-pin discovery {plan['plan_id']}; fresh all-pin selection required")
              for n in eligible[:limits.max_drafts]]
    pareto = [n["id"] for n in nodes if not any(
        m["tokens"] <= n["tokens"] and m["raw_heartbeats"] <= n["raw_heartbeats"]
        and (m["tokens"], m["raw_heartbeats"]) != (n["tokens"], n["raw_heartbeats"]) for m in nodes)]
    return dict(schema=SCHEMA, plan=plan, status=stopped or ("COMPLETE" if nodes else "SEED_REJECTED"),
        evidence_mode=evidence_mode, seed_checked=bool(nodes), context_applicable=context_applicable,
        incumbent_source=source, nomination=nomination,
        incumbent_changed=False, frontier=nodes, pareto_ids=pareto, drafts=drafts,
        attempts=attempts, edits=edits, omitted=omitted, proposals=proposals,
        retained_source_bytes=retained_bytes, verifier_calls=evaluator.calls,
        cache_hits=evaluator.cache_hits, wall_seconds=time.monotonic()-started,
        truncated=bool(stopped or omitted["state_limit"] or omitted["byte_limit"]
                       or omitted["support_windows"] or omitted["query_sites"] or omitted["draft_limit"]
                       or any(n["depth"] >= limits.max_depth for n in nodes)),
        cost_scope="single-pin whole-command discovery; not fresh cost confirmation",
        proof_admitted=False, promoted=False, training_enabled=False,
        minimality_proven=False, official_score=None, measured_api_cost=None)


def fixture_comparison() -> dict:
    """Reproducible control of orchestration, NOT Lean or measured heartbeats."""
    from .arena import VersionReceipt
    from .lean import VersionPin
    statement = "theorem solver_control (n : Nat) : n + 0 = n"
    root = statement + " := by\n  simp [Nat.add_zero, Nat.add_zero]\n"
    longer = statement + " := by\n  simp only [Nat.add_zero, Nat.zero_add]\n"
    short = statement + " := by\n  simp only []\n"
    pin = VersionPin("v4.26.0", "f" * 40)
    context = ArenaContext("solver_control", statement, root, reference_tokens(root, statement),
        None, (pin,), ("f" * 64,), "solver-fixture", "v1", "synthetic-cost-units/v1",
        verifier_options_json='{"branch_order":"reference-first"}')
    costs = {root: 10000, longer: 7000, short: 4000}

    def verifier(request):
        # Every response is explicitly manufactured from this small whitelist.
        base = request.source.replace("simp?", "simp")
        if base not in costs:
            return VersionReceipt(request.request_id, source_hash(request.source), context.problem,
                                  Outcome.REJECTED, reason="fixture_unlisted_source")
        messages = []
        if request.source != base and base == root:
            messages = [dict(severity="information", fileName="ArenaCandidate.lean",
                pos=dict(line=2, column=2), message="Try this: simp only [Nat.add_zero, Nat.zero_add]")]
        raw = costs[base]
        observations = dict(measurement=context.heartbeat_method, dependency_digest="f"*64,
            lean_version="4.26.0", branch_order="reference-first", report=dict(type_preserved=True,
            target_absent_before=True, raw_heartbeats=raw, heartbeats=raw//1000,
            reference_raw_heartbeats=10000, reference_heartbeats=10, axioms=[],
            reference_axioms=[], diagnostics=messages))
        return VersionReceipt(request.request_id, source_hash(request.source), context.problem,
            Outcome.VERIFIED, True, 0, "'solver_control' depends on axioms: []", raw//1000,
            observations_json=json.dumps(observations))

    return dict(schema="jevops-solver-fixture-comparison/v1", fixture_only=True,
        synthetic_costs_not_Lean_measurements=True, models_called=0, official_score=None,
        arms={mode: discover_solver_frontier(context, root, pin, verifier,
            context_validator=lambda _: None, evidence_mode="offline_fixture", mode=mode,
            limits=SolverLimits(max_calls=12)) for mode in LEGACY_MODES})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="offline fixtures only; never calls Lean or models")
    args = parser.parse_args()
    if not args.demo:
        parser.error("choose --demo; native discovery requires an explicitly injected Arena runtime")
    print(json.dumps(fixture_comparison(), sort_keys=True, indent=2, allow_nan=False))
