"""Bounded, order-balanced refactoring measurements using the existing verifier.

No training, provider calls, promotion, project mutation or dependency builds.
Controls and candidates receive fresh processes; receipt caches are disabled.
These local observations are not organizer scores or statistical significance.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
from typing import Mapping, Sequence

from .arena import (ArenaContext, ArenaEvaluator, Outcome, VerificationRequest, VersionReceipt,
                    content_hash, intake_error, reference_tokens, source_hash, _units)
from .arena_lean import (CORPUS, METHOD, CapabilityGap, NativeLeanVerifier, discover_projects,
                         project_binding, readiness)
from .lean import VersionPin
from .proof_ca import canonical_json
from .seals import Fingerprinter

ORDERS = ("reference-first", "candidate-first")
SCHEMA = "jevops-arena-controlled-trial/v1"
STRATEGIES = ("drop_redundant_simp_at", "drop_rename_i", "proof_slice", "proof_slice_unused_have")


def _setup_failure(exc: Exception) -> tuple[str, str]:
    status = ("TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else
              "UNAVAILABLE" if isinstance(exc, CapabilityGap) else "ERROR")
    return status, f"preparation: {type(exc).__name__}: {exc}"[:500]


def _unused_have_cuts(body: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """Select small existing slices with no explicit use of a local ASCII name.

    This is ONLY a textual proposal heuristic. `simp_all`, `assumption`, etc.
    can depend on unnamed context entries; Lean must check every proposed cut.
    The slicer's conservative bounds/comment exclusions remain in force.
    """
    from .proof_slicing import deletion_variants

    lines = body.splitlines()
    cuts = []
    for kind, draft, ops in deletion_variants(body, cap=64):
        _, start, end = ops[1].split(":")
        if int(end) != int(start) + 1:
            continue
        match = re.fullmatch(r"\s*have ([A-Za-z_][A-Za-z_0-9']*)\s*(?::[^=]+)?\s*:=\s*\S.*", lines[int(start)])
        if match and not re.search(r"(?<![\w'])" + re.escape(match[1]) + r"(?![\w'])", draft):
            cuts.append((kind, draft, ops))
    return cuts


@dataclass(frozen=True)
class Candidate:
    label: str
    source: str
    provenance: str

    def __post_init__(self):
        if not isinstance(self.label, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", self.label):
            raise ValueError("bounded candidate label required")
        if not isinstance(self.source, str) or not self.source.strip() or len(self.source.encode()) > 262144:
            raise ValueError("bounded candidate source required")
        if not isinstance(self.provenance, str) or not self.provenance or len(self.provenance) > 256:
            raise ValueError("explicit bounded provenance required")


def diagnostic_repair_candidates(record: Mapping, trial: Mapping, *, cap: int = 2) -> list[Candidate]:
    """Recover unverified drafts from historical source-bound rejection hints.

    Saved reports are NOT verification/admission inputs. This only generates
    candidates for a new trial/selection, whose native checks cannot be skipped.
    A content hash binds the diagnostic to its old source, not to current truth.
    """
    from .proof_slicing import arity_repair_variants
    if not 0 <= _units(cap, "cap") <= 8:
        raise ValueError("bounded repair cap required")
    if cap == 0:
        return []
    if (not isinstance(trial, Mapping) or trial.get("schema") != SCHEMA or trial.get("evidence_mode") != "local_lean"
            or content_hash(trial.get("record")) != content_hash(record)):
        raise ValueError("matching native trial and frozen problem record required")
    if (not isinstance(trial.get("arms"), list) or len(trial["arms"]) > 9
            or not isinstance(trial.get("samples"), list) or len(trial["samples"]) > 128
            or not isinstance(trial.get("contexts"), list) or len(trial["contexts"]) > 16):
        raise ValueError("bounded diagnostic trial required")
    arms = {arm["label"]: Candidate(**arm) for arm in trial["arms"]}
    if len(arms) != len(trial["arms"]):
        raise ValueError("duplicate diagnostic arm")
    contexts = {}
    for value in trial["contexts"]:
        ctx = ArenaContext(**{**value, "versions": tuple(VersionPin(**p) for p in value["versions"]),
            "dependency_digests": tuple(value["dependency_digests"]), "allowed_axioms": tuple(value["allowed_axioms"])})
        if ctx.problem != record["name"] or ctx.statement != record["statement"] or ctx.reference_source != record["src"]:
            raise ValueError("diagnostic context mismatch")
        contexts[ctx.context_id] = ctx
    results, seen = [], {source_hash(arm.source) for arm in arms.values()}
    for sample in trial["samples"]:
        if not isinstance(sample, Mapping):
            raise ValueError("diagnostic sample must be an object")
        if sample.get("status") != "REJECTED" or sample.get("label") == "control":
            continue
        arm = arms[sample["label"]]
        context = contexts[sample["context_id"]]
        pin = VersionPin(**sample["version"])
        request = VerificationRequest(context, arm.source, pin)
        raw = sample["receipt"]
        receipt = VersionReceipt(**{**raw, "outcome": Outcome(raw["outcome"])})
        if (pin not in context.versions or receipt.outcome != Outcome.REJECTED
                or receipt.request_id != request.request_id or receipt.target != record["name"]
                or receipt.candidate_sha256 != source_hash(arm.source)
                or sample["source_sha256"] != receipt.candidate_sha256):
            raise ValueError("diagnostic receipt/source binding mismatch")
        observation = json.loads(receipt.observations_json)
        if observation.get("measurement") != METHOD:
            continue
        if not isinstance(observation.get("report"), Mapping):
            raise ValueError("diagnostic report must be an object")
        diagnostics = observation.get("report", {}).get("diagnostics", [])
        for kind, source, _ops in arity_repair_variants(arm.source, record["statement"], diagnostics,
                diagnostics_source_sha256=receipt.candidate_sha256, cap=cap - len(results)):
            identity = source_hash(source)
            if identity not in seen and not intake_error(source, record["statement"]):
                seen.add(identity)
                results.append(Candidate(f"diagnostic-{len(results)}-{kind}", source,
                    "historical native diagnostic heuristic; unverified; request " + receipt.request_id))
            if len(results) == cap:
                return results
    return results


def proposals(record: Mapping, strategies: Sequence[str], *, cap: int = 2) -> list[Candidate]:
    """Reuse existing heuristic transforms; their drafts have no proof authority."""
    from . import tactics
    from .proof_slicing import deletion_variants

    if not 0 <= _units(cap, "cap") <= 8 or any(s not in STRATEGIES for s in strategies):
        raise ValueError("bounded allowlisted strategies required")
    statement, source = record["statement"], record["src"]
    if not source.startswith(statement):
        raise ValueError("reference statement mismatch")
    suffix = source[len(statement):]
    marker = re.match(r"\s*:=\s*by\b", suffix)
    if marker is None:
        raise ValueError("heuristic transforms require a tactic-style proof")
    prefix, body = statement + suffix[:marker.end()], suffix[marker.end():].lstrip("\n")
    candidates, seen = [], {source_hash(source)}
    for strategy in strategies:
        if len(candidates) >= cap:
            break
        if strategy == "proof_slice":
            drafts = deletion_variants(body, cap=cap - len(candidates))
        elif strategy == "proof_slice_unused_have":
            drafts = _unused_have_cuts(body)
        else:
            drafts = [(strategy, getattr(tactics, strategy)(body), ())]
        for kind, draft, _ops in drafts:
            candidate = prefix + "\n" + draft
            identity = source_hash(candidate)
            if identity not in seen and draft.strip() != body.strip():
                seen.add(identity)
                candidates.append(Candidate(f"heuristic-{len(candidates)}-{kind}", candidate,
                                            "existing deterministic heuristic: " + strategy))
            if len(candidates) >= cap:
                break
    return candidates


def _pins(record: Mapping) -> tuple[VersionPin, ...]:
    pins = tuple(VersionPin(tag, commit) for row in record["version_info"] for tag, commit in row.items())
    if not 1 <= len(pins) <= 8 or len({p.lean_tag for p in pins}) != len(pins):
        raise ValueError("one to eight unique required version pins required")
    return pins


def trial_plan(record: Mapping, candidates: Sequence[Candidate], *, repetitions: int = 2, seed: int = 17,
               allow_identical_sources: bool = False) -> dict:
    if not 1 <= _units(repetitions, "repetitions") <= 5 or type(seed) is not int:
        raise ValueError("one to five repetitions and an integer seed required")
    pins = _pins(record)
    if len(candidates) > 8 or any(not isinstance(c, Candidate) or c.label == "control" for c in candidates):
        raise ValueError("at most eight typed non-control candidates required")
    arms = [Candidate("control", record["src"], "unchanged-reference"), *candidates]
    if type(allow_identical_sources) is not bool:
        raise ValueError("explicit boolean identical-source policy required")
    if (len({c.label for c in arms}) != len(arms)
            or (not allow_identical_sources and len({c.source for c in arms}) != len(arms))):
        raise ValueError("unique labels and source bytes required, including control")
    design = {"schema": SCHEMA, "record": dict(record), "arms": [asdict(c) for c in arms],
              "repetitions": repetitions, "seed": seed, "orders": list(ORDERS)}
    if allow_identical_sources:
        # Policy ablations can legitimately abstain to the unchanged reference.
        # Keep historical v1 plans unchanged; repeated bytes are not discoveries.
        design.update(schema="jevops-arena-controlled-trial/v2", allow_identical_sources=True,
                      distinct_source_count=len({c.source for c in arms}),
                      independent_discoveries_claimed=False)
    identity, schedule = content_hash(design), []
    rng = random.Random(seed)
    for repetition in range(repetitions):
        for pin in pins:
            orders = list(ORDERS); rng.shuffle(orders)
            for order in orders:
                shuffled = list(arms); rng.shuffle(shuffled)
                for arm in shuffled:
                    slot = {"repetition": repetition, "version": pin.to_dict(), "branch_order": order,
                            "label": arm.label, "source_sha256": source_hash(arm.source)}
                    schedule.append({**slot, "sample_id": content_hash({"plan_id": identity, **slot})})
    return {**design, "plan_id": identity, "planned_requests": len(schedule), "schedule": schedule}


def _comparison(record: Mapping, candidate: Candidate, samples: list[dict], repetitions: int) -> dict:
    own = [s for s in samples if s["label"] == candidate.label]
    controls = [s for s in samples if s["label"] == "control"]
    complete = (len(own) == len(controls) == 2 * repetitions * len(_pins(record))
                and all(s["status"] == "VERIFIED" for s in [*own, *controls]))
    rejected = any(s["status"] == "REJECTED" for s in own)
    intake = intake_error(candidate.source, record["statement"])
    length = None if intake else reference_tokens(candidate.source, record["statement"])
    reference_length = reference_tokens(record["src"], record["statement"])
    # No missing version, failed control or exhausted repetition becomes 100% compatibility.
    verified_pins = [p.to_dict() for p in _pins(record) if any(
        s["version"] == p.to_dict() and s["status"] == "VERIFIED" for s in own)]
    groups = []
    for pin in _pins(record):
        for order in ORDERS:
            select = lambda rows: [s for s in rows if s["version"] == pin.to_dict() and s["branch_order"] == order]
            cs, xs = select(controls), select(own)
            group = {"version": pin.to_dict(), "branch_order": order, "status": "INCOMPLETE"}
            if len(cs) == len(xs) == repetitions and all(s["status"] == "VERIFIED" for s in [*cs, *xs]):
                cvals = [s["raw_heartbeats"] for s in cs]
                xvals = [s["raw_heartbeats"] for s in xs]
                noise = max(max(cvals) - min(cvals), max(xvals) - min(xvals))
                lower = repetitions >= 2 and min(cvals) - max(xvals) > noise
                higher = repetitions >= 2 and min(xvals) - max(cvals) > noise
                paired = {s["repetition"]: s["raw_heartbeats"] for s in cs}
                group.update(status="MEASURED", control_raw=cvals, candidate_raw=xvals,
                             control_median_raw=statistics.median(cvals), candidate_median_raw=statistics.median(xvals),
                             paired_savings_raw=[paired[s["repetition"]] - s["raw_heartbeats"] for s in xs],
                             observed_range_raw=noise,
                             comparison="LOWER" if lower else "HIGHER" if higher else "OVERLAPPING_OR_TOO_FEW")
            groups.append(group)
    heartbeat = ("LOWER_IN_BOTH_ORDERS" if complete and all(g.get("comparison") == "LOWER" for g in groups)
                 else "REGRESSION_IN_AT_LEAST_ONE_ORDER" if complete and any(g.get("comparison") == "HIGHER" for g in groups)
                 else "NO_CLEAR_DIFFERENCE" if complete else "INCOMPLETE")
    return {"label": candidate.label, "source_sha256": source_hash(candidate.source), "provenance": candidate.provenance,
            "status": "REJECTED" if rejected else "MEASURED" if complete else "INCOMPLETE",
            "reference_tokens": reference_length, "candidate_tokens": length,
            "length_reduction_pct": None if length is None or not reference_length else 100 * (1 - length / reference_length),
            "verified_pins": verified_pins, "required_pins": [p.to_dict() for p in _pins(record)],
            "heartbeat_result": heartbeat, "strata": groups,
            "observed_pareto_improvement": (length < reference_length and heartbeat == "LOWER_IN_BOTH_ORDERS")
                if complete and length is not None else None,
            "statistical_significance_claimed": False, "promoted": False, "official_score": None}


def run_trial(record: Mapping, candidates: Sequence[Candidate],
              verifiers: Mapping[tuple[VersionPin, str], NativeLeanVerifier], *,
              max_calls: int = 0, repetitions: int = 2, seed: int = 17,
              evidence_mode: str = "local_lean", progress: bool = False,
              setup_failures: Mapping[tuple[VersionPin, str], tuple[str, str]] | None = None,
              allow_identical_sources: bool = False) -> dict:
    """An experiment over fixed drafts, not an optimizer or an admission shortcut.

    Reserve integer request units before evaluation; process counts are separate.
    Every successful sample must come from exactly one fresh native invocation.
    Callers own stable prepared inputs. No concurrent mutation/safety claim.
    """
    if not 0 <= _units(max_calls, "max_calls") <= 128 or evidence_mode not in {"local_lean", "offline_fixture"}:
        raise ValueError("bounded requests and explicit evidence mode required")
    plan = trial_plan(record, candidates, repetitions=repetitions, seed=seed,
                      allow_identical_sources=allow_identical_sources)
    arms = {c["label"]: c for c in plan["arms"]}
    evaluators, contexts = {}, {}
    if any(v.processes for v in verifiers.values()):
        raise ValueError("fresh verifier instances required; old invocations are not new trials")
    if len({id(v) for v in verifiers.values()}) != len(verifiers):
        raise ValueError("one owned verifier instance per pin/order required")
    allowed = {(p, order) for p in _pins(record) for order in ORDERS}
    failures = dict(setup_failures or {})
    if (set(failures) - allowed or any(not isinstance(value, tuple) or len(value) != 2
            or not isinstance(value[0], str) or value[0] not in {"TIMEOUT", "ERROR", "UNAVAILABLE"}
            or not isinstance(value[1], str) or len(value[1]) > 500 for value in failures.values())):
        raise ValueError("bounded non-success preparation outcomes required")
    if set(verifiers) - allowed:
        raise ValueError("verifier outside the declared pin/order design")
    for (pin, order), verifier in verifiers.items():
        if verifier.branch_order != order:
            raise ValueError("verifier branch-order mismatch")
        if (pin, order) in failures:
            continue
        try:
            context = verifier.context({**record, "version_info": [{pin.lean_tag: pin.git_commit}]})
        except (OSError, subprocess.SubprocessError, CapabilityGap) as exc:
            failures[pin, order] = _setup_failure(exc)
            continue
        contexts[pin, order] = context
        # No calibrated denominator is invented. This runner only consumes checked
        # receipts, not the evaluator's scalar score, and disables result caching.
        evaluators[pin, order] = ArenaEvaluator(context, verifier, max_calls=max_calls, evidence_mode=evidence_mode,
                                               max_cache_entries=0, context_validator=verifier.validate_request)
    for pin in _pins(record):
        compared = []
        for order in ORDERS:
            if (pin, order) in contexts:
                ctx = asdict(contexts[pin, order]); options = json.loads(ctx.pop("verifier_options_json"))
                if options.pop("branch_order", None) != order or ctx["reference_heartbeats"] is not None:
                    raise ValueError("uncalibrated order-bound measurement context required")
                compared.append(content_hash({**ctx, "options": options}))
        if len(set(compared)) > 1:
            raise ValueError("order controls must have identical dependencies and non-order options")
    samples, used = [], 0
    for slot in plan["schedule"]:
        pin = VersionPin(**slot["version"]); key = (pin, slot["branch_order"])
        sample = {**slot, "status": "UNAVAILABLE", "reason": "prepared_binding_missing",
                  "verifier_invocations": 0, "receipt": None}
        if key in failures:
            status, reason = failures[key]
            sample.update(status=status, reason=reason)
        if key in evaluators:
            if used >= max_calls:
                sample.update(status="BUDGET_EXHAUSTED", reason="trial_request_budget")
            else:
                used += 1  # Reserve even if intake/infrastructure subsequently fails.
                verifier, evaluator = verifiers[key], evaluators[key]
                before = verifier.processes
                result = evaluator.evaluate(arms[slot["label"]]["source"])
                sample.update(status=result.status, reason=result.reason, context_id=contexts[key].context_id,
                              verifier_invocations=verifier.processes - before)
                if result.receipts:
                    receipt = result.receipts[0]
                    sample.update(status=receipt.outcome.value, reason=receipt.reason, receipt=asdict(receipt))
                    if receipt.outcome == Outcome.VERIFIED:
                        try:
                            obs = json.loads(receipt.observations_json)
                            if (sample["verifier_invocations"] != 1 or obs.get("branch_order") != key[1]
                                    or obs.get("measurement") != METHOD):
                                raise ValueError("fresh order-bound native observation required")
                            raw = _units(obs["report"]["raw_heartbeats"], "raw_heartbeats")
                            sample.update(raw_heartbeats=raw)
                        except (KeyError, TypeError, ValueError) as exc:
                            sample.update(status="ERROR", reason=str(exc))
        samples.append(sample)
        if progress:
            print(f"[{len(samples)}/{len(plan['schedule'])}] {pin.lean_tag} {slot['branch_order']} "
                  f"{slot['label']} repeat={slot['repetition']} {sample['status']}", file=sys.stderr, flush=True)
    observations = [_comparison(record, c, samples, repetitions) for c in candidates]
    return {**plan, "evidence_mode": evidence_mode, "max_calls": max_calls, "requests_reserved": used,
            "verifier_invocations": sum(v.processes for v in verifiers.values()),
            "native_processes": sum(v.processes for v in verifiers.values()) if evidence_mode == "local_lean" else 0,
            "samples": samples,
            "contexts": [asdict(c) for c in contexts.values()], "observations": observations,
            "status": "COMPLETE" if all(s["status"] == "VERIFIED" if s["label"] == "control" else
                                          s["status"] in {"VERIFIED", "REJECTED"} for s in samples) else "INCOMPLETE",
            "receipt_cache_enabled": False, "live_model_calls": 0, "training_enabled": False,
            "production_memory_used": False, "official_score": None, "local_combined_pct": None,
            "worker_metric_parity": "UNCONFIRMED", "runner_sha256": source_hash(Path(__file__).read_text())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--state-root", type=Path)
    inputs.add_argument("--projects", type=Path)
    parser.add_argument("--seed-candidate", type=Path, action="append", default=[], help="explicit historical best_source JSON artifact")
    parser.add_argument("--candidate", type=Path, action="append", default=[],
                        help="explicit unverified draft JSON: name, label, source, provenance")
    parser.add_argument("--strategy", choices=STRATEGIES, action="append", default=[])
    parser.add_argument("--proposal-cap", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-calls", type=int, default=0, help="reserved request units, including failures; zero runs no Lean")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--elan-home", type=Path, default=Path.home() / ".elan")
    parser.add_argument("--output", type=Path, help="new evidence file; never overwritten")
    parser.add_argument("--progress", action="store_true", help="sample progress to stderr; stdout remains JSON")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("--output must be a new evidence file")
    if not 0 <= _units(args.max_calls, "max_calls") <= 128:
        parser.error("--max-calls must be between zero and 128")
    records = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
    matches = [r for r in records if r["name"] == args.problem]
    if len(matches) != 1:
        parser.error("exactly one matching corpus problem required")
    record, candidates = matches[0], []
    for path in args.seed_candidate:
        if path.stat().st_size > 1_048_576:
            parser.error("seed artifact byte limit")
        data = json.loads(path.read_text())
        if data.get("name") != args.problem:
            parser.error("seed artifact target mismatch")
        candidates.append(Candidate(f"seed-{len(candidates)}", data["best_source"],
                                    "historical regression seed; artifact SHA-256 " + source_hash(path.read_text())))
    for path in args.candidate:
        if path.stat().st_size > 1_048_576:
            parser.error("candidate artifact byte limit")
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or set(data) != {"name", "label", "source", "provenance"}:
            parser.error("candidate artifact requires name, label, source, provenance only")
        if data["name"] != args.problem:
            parser.error("candidate artifact target mismatch")
        candidates.append(Candidate(data["label"], data["source"], data["provenance"]))
    seen = {record["src"], *(c.source for c in candidates)}
    for candidate in proposals(record, args.strategy, cap=args.proposal_cap):
        if candidate.source not in seen:
            seen.add(candidate.source); candidates.append(candidate)
    plan = trial_plan(record, candidates, repetitions=args.repetitions, seed=args.seed)
    projects = (discover_projects([record], args.state_root) if args.state_root else
                json.loads(args.projects.read_text()) if args.projects else [])
    inventory = readiness([record], projects, args.elan_home)
    report = {**plan, "readiness": inventory, "status": "PLANNED", "native_processes": 0,
              "live_model_calls": 0, "official_score": None}
    if args.run:
        reader, verifiers, failures = Fingerprinter(), {}, {}
        for row in inventory["rows"]:
            if row["status"] != "UNMEASURED":
                continue
            pin = VersionPin(row["lean_tag"], row["git_commit"])
            project = next(p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                           (record["url"], pin.lean_tag, pin.git_commit))
            try:
                binding = project_binding(record, pin, project, args.elan_home)
            except (OSError, subprocess.SubprocessError, CapabilityGap) as exc:
                for order in ORDERS:
                    failures[pin, order] = _setup_failure(exc)
                continue
            for order in ORDERS:
                verifiers[pin, order] = NativeLeanVerifier({pin: binding}, max_processes=args.max_calls,
                    timeout=args.timeout, fingerprinter=reader, branch_order=order)
        report = run_trial(record, candidates, verifiers, max_calls=args.max_calls,
                           repetitions=args.repetitions, seed=args.seed, progress=args.progress,
                           setup_failures=failures)
        report.update(readiness=inventory, fingerprint_file_reads=reader.reads, fingerprint_stat_hits=reader.stat_hits)
    encoded = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        with args.output.open("x") as stream:
            stream.write(encoded + "\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
