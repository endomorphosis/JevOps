"""Bounded two-objective selection followed by fresh, fixed-winner confirmation.

Uses the existing native verifier and balanced trial runner without changing
their trust boundary. No saved-report admission, model calls, training, project
builds or production promotion. A recommendation is local evidence, not an
organizer score or a statistical/generalization guarantee.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, Sequence

from .arena import (ArenaContext, TOKENIZER_ID, VerificationRequest, content_hash,
                    intake_error, reference_tokens, source_hash, _units)
from .arena_lean import (CORPUS, METHOD, CapabilityGap, NativeLeanVerifier, ProjectBinding,
                         pinned_lean, project_binding, readiness)
from .arena_trial import (Candidate, ORDERS, STRATEGIES, _pins, _setup_failure, diagnostic_repair_candidates,
                          proposals, run_trial, trial_plan)
from .lean import VersionPin
from .seals import Fingerprinter

SCHEMA = "jevops-arena-pareto-selection/v1"
POLICY = "no-token-growth-and-separated-or-exact-heartbeats/v1"
STRICT_DUAL_POLICY = "strict-token-reduction-and-separated-heartbeats/v1"
AGGREGATE_POLICY = "matched-primary-pin-normalized-sum-with-range-margin/v1"
OBJECTIVES = ("pareto-v1", "strict-dual-v1", "aggregate-local-v1")
# This factory is trusted infrastructure, never an LLM-supplied callback.
VerifierFactory = Callable[[str, int], tuple[Mapping, Mapping]]


def _criteria(selection_objective: str, heartbeat_noise_floor_raw: int) -> str:
    if type(selection_objective) is not str or selection_objective not in OBJECTIVES:
        raise ValueError("unknown selection objective")
    _units(heartbeat_noise_floor_raw, "heartbeat_noise_floor_raw")
    return {"pareto-v1": POLICY, "strict-dual-v1": STRICT_DUAL_POLICY,
            "aggregate-local-v1": AGGREGATE_POLICY}[selection_objective]


def _implementation() -> dict[str, str]:
    # File identity, not an attestation of loaded Python bytecode.
    return {name: source_hash(Path(__file__).with_name(name).read_text())
            for name in ("arena_pareto.py", "arena_trial.py")}


def selection_plan(record: Mapping, candidates: Sequence[Candidate], *, incumbent: Candidate | None = None,
                   repetitions: int = 2, confirmation_repetitions: int = 3, seed: int = 17,
                   selection_objective: str = "pareto-v1", heartbeat_noise_floor_raw: int = 0) -> dict:
    policy = _criteria(selection_objective, heartbeat_noise_floor_raw)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("uint32 seed required")
    if not 2 <= _units(repetitions, "repetitions") <= 5 or not 2 <= _units(
            confirmation_repetitions, "confirmation_repetitions") <= 5:
        raise ValueError("two to five repetitions required in both phases")
    if not candidates or incumbent is not None and not isinstance(incumbent, Candidate):
        raise ValueError("nonempty candidate batch and typed incumbent required")
    if intake_error(record["src"], record["statement"]):
        raise ValueError("reference violates the fixed intake policy")
    if incumbent is not None and intake_error(incumbent.source, record["statement"]):
        raise ValueError("incumbent violates the fixed intake policy")
    arms = [*([incumbent] if incumbent else []), *candidates]
    screen = trial_plan(record, arms, repetitions=repetitions, seed=seed)
    confirmation_calls = (3 if incumbent else 2) * len(_pins(record)) * 2 * confirmation_repetitions
    if screen["planned_requests"] > 128 or confirmation_calls > 128:
        raise ValueError("each phase must fit the existing 128-request trial bound")
    plan = {"schema": SCHEMA, "policy": policy, "selection_objective": selection_objective,
            "heartbeat_noise_floor_raw": heartbeat_noise_floor_raw, "tokenizer_id": TOKENIZER_ID,
            "measurement": METHOD, "implementation": _implementation(), "screen": screen,
            "incumbent_label": incumbent.label if incumbent else "control",
            "candidate_labels": [c.label for c in candidates],
            "confirmation_repetitions": confirmation_repetitions, "confirmation_seed": (seed + 1) % 2**32,
            "confirmation_request_reserve": confirmation_calls,
            "required_request_budget": screen["planned_requests"] + confirmation_calls,
            "selection_order": ["tokens", "worst_mean_heartbeat_ratio_to_incumbent", "label"],
            "unknown_comparison": "abstain", "retries": 0, "confirmation_alternatives": 0}
    if selection_objective == "aggregate-local-v1":
        plan.update(score_scope="matched-local-primary-pin", primary_pin=_pins(record)[0].to_dict(),
            score_reference="fresh-original-control-per-phase-and-order",
            compatibility_policy="all-declared-pins-verified-no-axiom-growth",
            score_formula="100/3 * ((comparator_tokens-candidate_tokens)/original_tokens + "
                          "(comparator_raw-candidate_raw)/original_raw)",
            rounding="none; exact rational deltas; not an official Arena score",
            selection_order=["descending_worst_conservative_gain_to_incumbent",
                             "descending_mean_nominal_gain_to_incumbent", "tokens", "label"])
    return {**plan, "plan_id": content_hash(plan)}


def _costs(trial: dict) -> dict[str, dict]:
    """Reduce this invocation's checked samples, not externally supplied scores.

    Private: the trusted runner owns provenance. Content hashes do not
    authenticate a serialized report or replace fresh verification.
    """
    schedule, samples = trial["schedule"], trial["samples"]
    if len(schedule) != len(samples) or any(any(s.get(k) != v for k, v in slot.items())
                                           for slot, s in zip(schedule, samples)):
        raise ValueError("sample schedule mismatch")
    rows = {}
    for arm in trial["arms"]:
        own = [s for s in samples if s["label"] == arm["label"]]
        reason = "" if all(s["status"] == "VERIFIED" for s in own) else "unverified_samples"
        costs, axioms = [], {}
        for pin in _pins(trial["record"]):
            for order in ORDERS:
                group = sorted((s for s in own if s["version"] == pin.to_dict() and s["branch_order"] == order),
                               key=lambda s: s["repetition"])
                values = []
                for sample in group:
                    if sample["status"] != "VERIFIED":
                        continue
                    receipt = sample["receipt"]
                    obs = json.loads(receipt["observations_json"])
                    raw = _units(obs["report"]["raw_heartbeats"], "raw_heartbeats")
                    if (sample["verifier_invocations"] != 1 or receipt["outcome"] != "VERIFIED"
                            or sample["source_sha256"] != source_hash(arm["source"])
                            or receipt["candidate_sha256"] != sample["source_sha256"]
                            or sample["raw_heartbeats"] != raw or obs["branch_order"] != order
                            or obs["measurement"] != METHOD):
                        raise ValueError("fresh bound sample required")
                    proof_axioms = sorted(set(obs["report"]["axioms"]))
                    if set(proof_axioms) - set(obs["report"]["reference_axioms"]):
                        reason = "axiom_expansion_over_reference"
                    tag = pin.lean_tag
                    if tag in axioms and axioms[tag] != proof_axioms:
                        reason = "inconsistent_axiom_observations"
                    axioms[tag] = proof_axioms
                    values.append(raw)
                costs.append(values)
        if any(len(v) != trial["repetitions"] for v in costs):
            reason = "incomplete_cost_coverage"
        error = intake_error(arm["source"], trial["record"]["statement"])
        rows[arm["label"]] = {"label": arm["label"], "source_sha256": source_hash(arm["source"]),
            "tokens": None if error else reference_tokens(arm["source"], trial["record"]["statement"]),
            "admissible": not reason and not error, "reason": reason or error or "",
            "raw_heartbeats_by_stratum": costs, "axioms_by_version": axioms}
    return rows


def heartbeat_relation(left: Sequence[int], right: Sequence[int], *, noise_floor_raw: int = 0) -> str:
    """Conservative descriptive comparison, not a significance test.

    Overlapping noisy ranges are UNKNOWN, not evidence of equivalence. EQUAL
    requires all observations in both arms to be the same exact raw count.
    Strict separation must exceed both observed variation and the precommitted
    integer noise floor. A zero floor preserves the historical comparison.
    """
    _units(noise_floor_raw, "noise_floor_raw")
    if len(left) < 2 or len(left) != len(right):
        return "UNKNOWN"
    for value in (*left, *right):
        _units(value, "raw heartbeat")
    if min(left) == max(left) == min(right) == max(right):
        return "EQUAL"
    noise = max(max(left) - min(left), max(right) - min(right), noise_floor_raw)
    if min(right) - max(left) > noise:
        return "LOWER"
    if min(left) - max(right) > noise:
        return "HIGHER"
    return "UNKNOWN"


def _dominates(left: dict, right: dict, *, noise_floor_raw: int = 0, strict_dual: bool = False) -> bool:
    if not left["admissible"] or not right["admissible"] or left["tokens"] > right["tokens"]:
        return False
    if any(set(value) - set(right["axioms_by_version"][pin])
           for pin, value in left["axioms_by_version"].items()):
        return False
    lc, rc = left["raw_heartbeats_by_stratum"], right["raw_heartbeats_by_stratum"]
    if len(lc) != len(rc) or not lc:
        return False
    relations = [heartbeat_relation(a, b, noise_floor_raw=noise_floor_raw) for a, b in zip(lc, rc)]
    if strict_dual:
        return left["tokens"] < right["tokens"] and all(r == "LOWER" for r in relations)
    return all(r in {"LOWER", "EQUAL"} for r in relations) and (
        left["tokens"] < right["tokens"] or "LOWER" in relations)


def _rational(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _aggregate_comparison(candidate: dict, comparator: dict, original: dict, *,
                          noise_floor_raw: int = 0) -> dict:
    """A local score delta, never a receipt or a statistical lower bound.

    All pins must verify, but only the first declared pin contributes cost,
    matching Arena's default-pin convention. Each branch order is a separate
    required gate. Original control denominators are freshly measured, not
    published heartbeat fields whose parity is currently unconfirmed.
    """
    result = {"applicable": False, "improves": False, "reason": "", "strata": []}
    if not all(row["admissible"] for row in (candidate, comparator, original)):
        return {**result, "reason": "unverified_samples"}
    if any(set(value) - set(comparator["axioms_by_version"].get(pin, ()))
           for pin, value in candidate["axioms_by_version"].items()):
        return {**result, "reason": "axiom_expansion_over_comparator"}
    groups = [row["raw_heartbeats_by_stratum"] for row in (candidate, comparator, original)]
    if len({len(g) for g in groups}) != 1 or len(groups[0]) < len(ORDERS):
        return {**result, "reason": "incomplete_cost_coverage"}
    if original["tokens"] <= 0:
        return {**result, "reason": "zero_reference_token_denominator"}
    token_gain = Fraction(comparator["tokens"] - candidate["tokens"], original["tokens"])
    strata = []
    for index, order in enumerate(ORDERS):
        a, b, r = (g[index] for g in groups)
        if len(a) < 2 or len({len(a), len(b), len(r)}) != 1:
            return {**result, "reason": "incomplete_cost_coverage"}
        if min(r) <= 0:
            return {**result, "reason": "zero_reference_heartbeat_denominator"}
        margin = max(noise_floor_raw, *(max(v) - min(v) for v in (a, b, r)))
        adjusted_delta = min(b) - max(a) - margin
        # Divide positive gains by the largest reference cost and losses by
        # the smallest: either direction is conservative over observed ranges.
        denominator = max(r) if adjusted_delta >= 0 else min(r)
        lower = Fraction(100, 3) * (token_gain + Fraction(adjusted_delta, denominator))
        nominal = Fraction(100, 3) * (token_gain + Fraction(sum(b) - sum(a), sum(r)))
        strata.append({"branch_order": order, "token_gain": _rational(token_gain),
            "margin_raw": margin, "adjusted_heartbeat_delta_raw": adjusted_delta,
            "conservative_reference_raw": denominator,
            "conservative_gain_pp": _rational(lower), "nominal_gain_pp": _rational(nominal)})
    return {"applicable": True, "improves": all(s["conservative_gain_pp"]["numerator"] > 0 for s in strata),
            "reason": "", "strata": strata}


def _analysis(trial: dict, incumbent_label: str, candidate_labels: Sequence[str], *,
              selection_objective: str = "pareto-v1", heartbeat_noise_floor_raw: int = 0) -> dict:
    _criteria(selection_objective, heartbeat_noise_floor_raw)
    rows = _costs(trial)
    baseline, original = rows[incumbent_label], rows["control"]
    # Keep the ordinary Pareto frontier for discovery, including trade-offs;
    # eligibility is a separate, optionally strict, gate against both controls.
    frontier = sorted(label for label, row in rows.items() if row["admissible"] and not any(
        _dominates(other, row, noise_floor_raw=heartbeat_noise_floor_raw)
        for name, other in rows.items() if name != label))
    if selection_objective == "aggregate-local-v1":
        comparisons = {name: {key: _aggregate_comparison(rows[name], control, original,
                                noise_floor_raw=heartbeat_noise_floor_raw)
                             for key, control in (("original", original), ("incumbent", baseline))}
                       for name in candidate_labels}
        eligible = [name for name in candidate_labels if all(
            c["improves"] for c in comparisons[name].values())]
        def aggregate_rank(label):
            strata = comparisons[label]["incumbent"]["strata"]
            return (-min(Fraction(**s["conservative_gain_pp"]) for s in strata),
                    -sum(Fraction(**s["nominal_gain_pp"]) for s in strata) / len(strata),
                    rows[label]["tokens"], label)
        eligible.sort(key=aggregate_rank)
        return {"rows": rows, "frontier": frontier, "eligible": eligible,
                "selection_objective": selection_objective, "heartbeat_noise_floor_raw": heartbeat_noise_floor_raw,
                "aggregate_comparisons": comparisons, "score_scope": "matched-local-primary-pin",
                "selected": eligible[0] if trial["status"] == "COMPLETE" and eligible else None}
    criteria = dict(noise_floor_raw=heartbeat_noise_floor_raw, strict_dual=selection_objective == "strict-dual-v1")
    eligible = [name for name in candidate_labels if name in frontier
                and _dominates(rows[name], baseline, **criteria) and _dominates(rows[name], original, **criteria)]
    def rank(label):
        row = rows[label]
        ratios = [Fraction(sum(a), sum(b)) if sum(b) else Fraction(1)
                  for a, b in zip(row["raw_heartbeats_by_stratum"], baseline["raw_heartbeats_by_stratum"])]
        return row["tokens"], max(ratios), label
    eligible.sort(key=rank)
    return {"rows": rows, "frontier": frontier, "eligible": eligible,
            "selection_objective": selection_objective, "heartbeat_noise_floor_raw": heartbeat_noise_floor_raw,
            "selected": eligible[0] if trial["status"] == "COMPLETE" and eligible else None}


def _applicability_error(trial: dict, verifiers: Mapping) -> str:
    """Revalidate every version, including ones checked early in the phase."""
    try:
        for value in trial["contexts"]:
            context = ArenaContext(**{**value, "versions": tuple(VersionPin(**p) for p in value["versions"]),
                "dependency_digests": tuple(value["dependency_digests"]),
                "allowed_axioms": tuple(value["allowed_axioms"])})
            order = json.loads(context.verifier_options_json)["branch_order"]
            for pin in context.versions:
                verifiers[pin, order].validate_request(VerificationRequest(context, context.reference_source, pin))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        return f"final_context_validation: {type(exc).__name__}: {exc}"[:500]
    return ""


def run_selection(record: Mapping, candidates: Sequence[Candidate], verifier_factory: VerifierFactory, *,
                  incumbent: Candidate | None = None, max_calls: int = 0, repetitions: int = 2,
                  confirmation_repetitions: int = 3, seed: int = 17,
                  evidence_mode: str = "local_lean", progress: bool = False,
                  selection_objective: str = "pareto-v1", heartbeat_noise_floor_raw: int = 0) -> dict:
    """Select once, then confirm only that choice with new verifiers/processes.

    The entire worst-case request budget is checked before constructing a
    verifier. A failed confirmation never triggers another candidate or retry.
    The factory must return (fresh verifiers, explicit setup failures), as used
    by run_trial. It and the local filesystem remain trusted infrastructure.
    """
    plan = selection_plan(record, candidates, incumbent=incumbent, repetitions=repetitions,
                          confirmation_repetitions=confirmation_repetitions, seed=seed,
                          selection_objective=selection_objective, heartbeat_noise_floor_raw=heartbeat_noise_floor_raw)
    # Snapshot caller-owned mutable records before invoking injected infrastructure.
    plan = json.loads(json.dumps(plan))
    if not plan["required_request_budget"] <= _units(max_calls, "max_calls") <= 256:
        raise ValueError("reserve the full screening and confirmation request budget (at most 256)")
    if evidence_mode not in {"local_lean", "offline_fixture"}:
        raise ValueError("explicit evidence mode required")
    record = plan["screen"]["record"]
    criteria = {key: plan[key] for key in ("selection_objective", "heartbeat_noise_floor_raw")}
    arms = [Candidate(**a) for a in plan["screen"]["arms"][1:]]
    screen_verifiers, failures = verifier_factory("screen", plan["screen"]["planned_requests"])
    screen = run_trial(record, arms, screen_verifiers, max_calls=plan["screen"]["planned_requests"],
                       repetitions=repetitions, seed=seed, evidence_mode=evidence_mode, progress=progress,
                       setup_failures=failures)
    analysis = _analysis(screen, plan["incumbent_label"], plan["candidate_labels"], **criteria)
    applicability_error = _applicability_error(screen, screen_verifiers)
    if not analysis["rows"][plan["incumbent_label"]]["admissible"]:
        applicability_error = applicability_error or "incumbent_not_admissible"
    if applicability_error:
        analysis["selected"] = None
    result = {"schema": SCHEMA, "plan": plan, "evidence_mode": evidence_mode, "screen": screen,
              "screen_analysis": analysis, "confirmation": None, "confirmation_analysis": None,
              "selection_commitment": None, "selected_for_confirmation": analysis["selected"],
              "recommended": None, "retained_incumbent": plan["incumbent_label"],
              "retained_incumbent_verified": not applicability_error and analysis["rows"][plan["incumbent_label"]]["admissible"],
              "status": "NO_IMPROVEMENT" if screen["status"] == "COMPLETE" else "INCOMPLETE",
              "reason": "", "promoted": False, "training_enabled": False, "live_model_calls": 0,
              "official_score": None, "worker_metric_parity": "UNCONFIRMED",
              "statistical_significance_claimed": False, "max_calls": max_calls}
    if applicability_error:
        result.update(status="INCOMPLETE", reason=applicability_error)
    selected = analysis["selected"]
    if selected is not None:
        chosen = next(c for c in arms if c.label == selected)
        confirm_arms = [c for c in arms if c.label in {plan["incumbent_label"], selected}]
        result["selection_commitment"] = content_hash({"plan_id": plan["plan_id"],
            "screen_sha256": content_hash(screen), "selected": asdict(chosen)})
        if progress:
            print(f"Selected {selected}; frozen before fresh confirmation", file=sys.stderr, flush=True)
        verifiers, failures = verifier_factory("confirm", plan["confirmation_request_reserve"])
        if {id(v) for v in verifiers.values()} & {id(v) for v in screen_verifiers.values()}:
            raise ValueError("confirmation requires new verifier instances")
        confirmation = run_trial(record, confirm_arms, verifiers, max_calls=plan["confirmation_request_reserve"],
            repetitions=confirmation_repetitions, seed=plan["confirmation_seed"], evidence_mode=evidence_mode,
            progress=progress, setup_failures=failures)
        confirm_analysis = _analysis(confirmation, plan["incumbent_label"], [selected], **criteria)
        result.update(confirmation=confirmation, confirmation_analysis=confirm_analysis, status="UNCONFIRMED")
        applicability_error = _applicability_error(confirmation, verifiers)
        if applicability_error:
            result.update(status="INCOMPLETE", reason=applicability_error)
        elif sorted(content_hash(c) for c in screen["contexts"]) != sorted(
                content_hash(c) for c in confirmation["contexts"]):
            result.update(status="INCOMPLETE", reason="contexts_changed_between_phases")
        elif confirmation["status"] != "COMPLETE":
            result.update(status="INCOMPLETE", reason="confirmation_incomplete")
        elif not confirm_analysis["rows"][plan["incumbent_label"]]["admissible"]:
            result.update(status="INCOMPLETE", reason="confirmation_incumbent_not_admissible")
        elif confirm_analysis["selected"] == selected:
            result["status"] = "CONFIRMED_LOCAL_IMPROVEMENT" if evidence_mode == "local_lean" else "FIXTURE_CONFIRMED"
            if evidence_mode == "local_lean":
                result["recommended"] = asdict(chosen)
                result["retained_incumbent"] = None
        else:
            result["reason"] = "selected_candidate_failed_confirmation_gates"
        result["retained_incumbent_verified"] = (result["retained_incumbent"] is not None
            and result["status"] != "INCOMPLETE" and confirm_analysis["rows"][plan["incumbent_label"]]["admissible"])
    trials = [screen, *([result["confirmation"]] if result["confirmation"] else [])]
    result.update({key: sum(t[key] for t in trials)
                   for key in ("requests_reserved", "verifier_invocations", "native_processes")})
    result["implementation_unchanged"] = _implementation() == plan["implementation"]
    if not result["implementation_unchanged"]:
        result.update(status="INCOMPLETE", reason="implementation_changed_during_selection", recommended=None,
                      retained_incumbent=plan["incumbent_label"], retained_incumbent_verified=False)
    result["runner_sha256"] = plan["implementation"]["arena_pareto.py"]
    return result


def summary(report: dict) -> str:
    lines = ["# Token/heartbeat selection", "", f"Status: {report['status']}.", "",
             f"Selection objective: {report['plan'].get('selection_objective', 'pareto-v1')}; "
             f"heartbeat noise floor: {report['plan'].get('heartbeat_noise_floor_raw', 0)} raw units.", "",
             f"Evidence mode: {report['evidence_mode']}. No production promotion, training or official score.", "",
             f"Selected for confirmation: {report['selected_for_confirmation'] or 'none'}.",
             f"Requests reserved: {report['requests_reserved']}; native processes: {report['native_processes']}.", "",
             "| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |", "| --- | --- | ---: | --- | --- |"]
    for phase in ("screen", "confirmation"):
        analysis = report.get(phase + "_analysis")
        if not analysis:
            continue
        for row in analysis["rows"].values():
            ranges = "; ".join(f"{min(v)}–{max(v)}" if v else "missing" for v in row["raw_heartbeats_by_stratum"])
            lines.append(f"| {phase} | {row['label']} | {row['tokens']} | {row['admissible']} | {ranges} |")
    lines += ["", "Strata follow the record's version order, reference-first then candidate-first."]
    if report["plan"].get("selection_objective") == "aggregate-local-v1":
        lines += ["All pins must verify without axiom growth. Costs use only the primary pin, in both orders.",
                  "A recommendation requires a positive conservative normalized-sum delta over both controls.",
                  "Fresh original denominators; range/floor margin; exact unrounded rational deltas in JSON.",
                  "This is a matched-local estimate, not the official score or a statistical confidence bound."]
    else:
        lines += ["Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.",
                  "Recommendations require improvement over both original and incumbent, across every stratum."]
    lines += [f"Reason: {report['reason'] or 'none'}.", ""]
    return "\n".join(lines)


def _draft(path: Path, problem: str) -> Candidate:
    if path.stat().st_size > 1_048_576:
        raise ValueError("draft byte limit")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"name", "label", "source", "provenance"} or data["name"] != problem:
        raise ValueError("draft requires matching name, label, source, provenance only")
    return Candidate(data["label"], data["source"], data["provenance"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--smoke", action="store_true", help="real Lean on a non-Arena stdlib control")
    parser.add_argument("--problem")
    parser.add_argument("--tag", default="v4.34.0", help="smoke only; never substitutes corpus pins")
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--elan-home", type=Path, default=Path.home() / ".elan")
    parser.add_argument("--candidate", type=Path, action="append", default=[])
    parser.add_argument("--repair-from-trial", type=Path,
                        help="historical rejection hints only; emitted drafts require entirely fresh verification")
    parser.add_argument("--incumbent", type=Path)
    parser.add_argument("--strategy", choices=STRATEGIES, action="append", default=[])
    parser.add_argument("--proposal-cap", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--confirmation-repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--selection-objective", choices=OBJECTIVES, default="pareto-v1",
                        help="strict-dual-v1 requires both costs lower; aggregate-local-v1 permits "
                             "trade-offs under a matched-local primary-pin score, not an official score")
    parser.add_argument("--heartbeat-noise-floor-raw", type=int, default=0,
                        help="predeclared nonnegative raw-unit floor; separation must also exceed observed ranges")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("finite positive timeout required")
    if args.smoke:
        if (args.problem or args.projects or args.candidate or args.incumbent or args.strategy
                or args.repair_from_trial or args.corpus != CORPUS):
            parser.error("smoke is separate from corpus problems, projects, drafts and strategies")
        statement = "theorem pareto_smoke (h : True) : True"
        pin = VersionPin(args.tag, "local-stdlib-smoke")
        record = {"name": "pareto_smoke", "statement": statement,
            "src": statement + " := by\n  have one : True := h\n  have two : True := one\n  exact two",
            "version_info": [{pin.lean_tag: pin.git_commit}]}
    else:
        records = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
        matches = [r for r in records if r["name"] == args.problem]
        if len(matches) != 1:
            parser.error("exactly one matching problem required")
        record = matches[0]
    try:
        incumbent = _draft(args.incumbent, args.problem) if args.incumbent else None
        candidates = ([Candidate("exact-h", statement + " := by exact h", "fixed stdlib smoke control; not Arena")]
                      if args.smoke else [_draft(p, args.problem) for p in args.candidate])
        if args.repair_from_trial:
            if args.repair_from_trial.stat().st_size > 8_388_608:
                raise ValueError("diagnostic trial byte limit")
            hints = json.loads(args.repair_from_trial.read_text())
            candidates.extend(diagnostic_repair_candidates(record, hints, cap=args.proposal_cap))
        base = {**record, "src": incumbent.source} if incumbent else record
        seen = {base["src"], *(c.source for c in candidates)}
        for candidate in proposals(base, args.strategy, cap=args.proposal_cap):
            if candidate.source not in seen:
                seen.add(candidate.source)
                candidates.append(candidate)
        kwargs = dict(incumbent=incumbent, repetitions=args.repetitions,
                      confirmation_repetitions=args.confirmation_repetitions, seed=args.seed,
                      selection_objective=args.selection_objective, heartbeat_noise_floor_raw=args.heartbeat_noise_floor_raw)
        plan = selection_plan(record, candidates, **kwargs)
        if not 0 <= _units(args.max_calls, "max_calls") <= 256:
            raise ValueError("--max-calls must be between zero and 256")
        if not args.plan and args.max_calls < plan["required_request_budget"]:
            raise ValueError(f"--max-calls must reserve {plan['required_request_budget']} to 256 requests")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "protocol.json").write_text(json.dumps(plan, indent=2, allow_nan=False) + "\n")
    if args.plan:
        print(json.dumps({"status": "PLANNED", "required_request_budget": plan["required_request_budget"],
                          "native_processes": 0, "output_dir": str(args.output_dir)}))
        return 0
    projects = json.loads(args.projects.read_text()) if args.projects else []
    inventory = ({"rows": [{"status": "UNMEASURED", **pin.to_dict()}], "kind": "non_arena_stdlib_smoke"}
                 if args.smoke else readiness([record], projects, args.elan_home))
    def factory(_phase, limit):
        reader, verifiers, failures = Fingerprinter(), {}, {}
        for row in inventory["rows"]:
            pin = VersionPin(row["lean_tag"], row["git_commit"])
            try:
                if row["status"] != "UNMEASURED":
                    raise CapabilityGap("; ".join(row["capability_gaps"]))
                if args.smoke:
                    binding = ProjectBinding(pin, pinned_lean(args.elan_home, pin.lean_tag), Path.cwd(), "",
                                             project_backed=False)
                else:
                    project = next(p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                                   (record.get("url"), pin.lean_tag, pin.git_commit))
                    binding = project_binding(record, pin, project, args.elan_home)
                for order in ORDERS:
                    verifiers[pin, order] = NativeLeanVerifier({pin: binding}, max_processes=limit,
                        timeout=args.timeout, fingerprinter=reader, branch_order=order)
            except (OSError, subprocess.SubprocessError, CapabilityGap) as exc:
                for order in ORDERS:
                    failures[pin, order] = _setup_failure(exc)
        return verifiers, failures
    report = run_selection(record, candidates, factory, max_calls=args.max_calls, progress=args.progress, **kwargs)
    report["readiness"] = inventory
    report["input_kind"] = "non_arena_stdlib_smoke" if args.smoke else "caller_supplied_corpus"
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (args.output_dir / "summary.md").write_text(summary(report))
    print(json.dumps({"status": report["status"], "selected": report["selected_for_confirmation"],
                      "native_processes": report["native_processes"], "output_dir": str(args.output_dir)}))
    return 2 if report["status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
