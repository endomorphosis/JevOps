"""Regenerated-context closing-tactic replay and verified compression teachers.

Native contexts are regenerated, never decoded from observation JSON. Local
kernel checks do not replace fresh whole-source type/axiom/expression-cost gates.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

from . import proof_state as ps
from .expr_dag import _bytes
from .proof_tokens import proof_source_tokens
from .proof_trust import STANDARD_AXIOMS
from .structural_training import _envelope, collect_structural_pairs

SCHEMA = "jevops-closed-tactic-replay/v1"
MARKER = b"JEVOPS_TACTIC_REPLAY:"


def digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _check_capture(source, capture, environment_sha256):
    if (not isinstance(source, str) or len(source.encode()) > ps.MAX_SOURCE_BYTES
            or not isinstance(capture, dict) or capture.get("ok") is not True
            or capture.get("source_sha256") != hashlib.sha256(source.encode()).hexdigest()
            or capture.get("dependency_environment_sha256") != environment_sha256
            or capture.get("exporter_sha256") != hashlib.sha256(ps.EXPORTER.read_bytes()).hexdigest()
            or any(capture.get(k) is not False for k in ("proof_admitted", "kernel_typechecked", "replayable"))):
        raise ValueError("stale, foreign, or unsupported capture")
    binding = {k: capture[k] for k in ("source_sha256", "dependency_environment_sha256", "exporter_sha256",
                                      "node_budget", "event_budget")}
    if "origin" in capture or "origin_sha256" in capture:
        if capture.get("origin_sha256") != digest(capture.get("origin")):
            raise ValueError("capture origin mismatch")
        binding["origin_sha256"] = capture["origin_sha256"]
    if capture["environment"] != digest(binding) or capture["trace_sha256"] != digest(capture["trace"]):
        raise ValueError("capture binding mismatch")
    ps.validate_trace(capture["trace"], source=source, environment=capture["environment"],
                      node_budget=capture["node_budget"], event_budget=capture["event_budget"])
    if capture["trace"]["elaboration_errors"]:
        raise ValueError("original source has elaboration errors")


def _outcome(outcome, expected_count):
    if not isinstance(outcome, dict):
        raise ValueError("invalid replay outcome")
    rejected = outcome.get("status") == "rejected"
    ps._fields(outcome, "status closed_goals_checked remaining_goals axioms" + (" reason" if rejected else ""))
    checked = ps._nat(outcome["closed_goals_checked"], 17)
    axioms = ps._array(outcome["axioms"], 3)
    if any(not isinstance(a, str) or a not in STANDARD_AXIOMS for a in axioms) or len(set(axioms)) != len(axioms):
        raise ValueError("invalid replay axiom policy")
    if rejected:
        if checked or outcome["remaining_goals"] is not None or axioms or not ps._string(outcome["reason"]):
            raise ValueError("invalid rejected replay")
    elif outcome["status"] == "open_goals":
        if checked or not ps._nat(outcome["remaining_goals"], 65536) or axioms:
            raise ValueError("invalid open replay")
    elif outcome["status"] == "closed_kernel_checked":
        if not 1 <= checked == expected_count <= 16 or outcome["remaining_goals"] != "0":
            raise ValueError("incomplete closed replay")
    else:
        raise ValueError("unknown replay outcome")


def validate_replay(report, *, capture, event_id, candidate, environment):
    ps._fields(report, "schema environment lean_version lean_githash event candidate baseline proposed "
                       "proof_admitted snapshot_decoded whole_source_checked")
    event = capture["trace"]["events"][event_id]
    if (report["schema"] != SCHEMA or report["environment"] != environment or report["candidate"] != candidate
            or report["event"] != event or any(report[k] is not False
                                               for k in ("proof_admitted", "snapshot_decoded", "whole_source_checked"))
            or any(report[k] != capture["trace"][k] for k in ("lean_version", "lean_githash"))):
        raise ValueError("replay anchor, toolchain, or identity mismatch")
    if event["status"] != "captured":
        raise ValueError("unsupported anchor")
    count = len(event["before"]["goals"])
    _outcome(report["baseline"], count)
    _outcome(report["proposed"], count)
    return (not event["after"]["goals"] and
            all(report[k]["status"] == "closed_kernel_checked" for k in ("baseline", "proposed")))


def replay_candidate(source: str, capture: dict, event_id: int, candidate: str, *, project_root: Path,
                     environment_sha256: str, use_lake: bool = False, timeout: float = 40) -> dict[str, Any]:
    """Replay original syntax and one proposal from isolated regenerated before contexts.

    ``closing_reproduced`` checks a recorded closing outcome, not identical proof
    terms or arbitrary transition equivalence. Open local telescopes abstain.
    Candidate/source metaprograms are trusted executable code, not sandboxed.
    """
    if (type(event_id) is not int or not isinstance(candidate, str) or not candidate.strip()
            or len(candidate.encode()) > 4096 or "\x00" in candidate or "\r" in candidate
            or not isinstance(environment_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", environment_sha256)
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300):
        raise ValueError("invalid replay request")
    _check_capture(source, capture, environment_sha256)
    if "origin" in capture:
        raise ValueError("project capture requires its explicit Arena local replay adapter")
    events = capture["trace"]["events"]
    if not 0 <= event_id < len(events) or events[event_id]["status"] != "captured":
        raise ValueError("unknown or unsupported event")
    binding = {"source_sha256": capture["source_sha256"], "trace_sha256": capture["trace_sha256"],
               "dependency_environment_sha256": environment_sha256, "exporter_sha256": capture["exporter_sha256"],
               "event_id": event_id, "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
               "node_budget": capture["node_budget"], "event_budget": capture["event_budget"]}
    environment = digest(binding)
    base = {"binding": binding, "environment": environment, "closing_reproduced": False,
            "proof_admitted": False, "whole_source_checked": False, "dependency_closure_verified": False}
    cmd = (["lake", "env", "lean"] if use_lake else ["lean"]) + ["--run", str(ps.EXPORTER), "replay",
           environment, str(capture["node_budget"]), str(capture["event_budget"]), str(event_id), candidate]
    try:
        output = ps._run_bounded(cmd, source=source.encode(), cwd=Path(project_root), timeout=timeout)
        if hashlib.sha256(ps.EXPORTER.read_bytes()).hexdigest() != binding["exporter_sha256"]:
            raise ValueError("exporter changed during replay")
        lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
        if len(lines) != 1:
            raise ValueError("missing or ambiguous replay receipt")

        def pairs(items):
            out = {}
            for key, val in items:
                if key in out:
                    raise ValueError("duplicate JSON field")
                out[key] = val
            return out

        def invalid_number(_):
            raise ValueError("protocol numbers must be decimal strings")

        report = json.loads(lines[0], object_pairs_hook=pairs, parse_int=invalid_number,
                            parse_float=invalid_number, parse_constant=invalid_number)
        closing = validate_replay(report, capture=capture, event_id=event_id, candidate=candidate, environment=environment)
        return {**base, "ok": True, "closing_reproduced": closing, "native": report, "native_sha256": digest(report)}
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.TimeoutExpired) as exc:
        return {**base, "ok": False, "reason": type(exc).__name__ + ": " + str(exc)[:200]}


def replace_event(source, event, candidate):
    """Replace only the observed UTF-8 span; a separate gate checks the result."""
    if not isinstance(candidate, str) or not candidate.strip() or len(candidate.encode()) > 4096 or "\x00" in candidate:
        raise ValueError("invalid candidate text")
    if event.get("status") != "captured" or event.get("start") is None or event.get("end") is None:
        raise ValueError("event has no captured source range")
    raw = source.encode()
    start, end = ps._nat(event["start"], len(raw) + 1), ps._nat(event["end"], len(raw) + 1)
    if start >= end:
        raise ValueError("empty or reversed source span")
    # InfoTree also reports synthetic `null` nodes for case/next headers,
    # and a `case` node spanning only `=>`. Their states are observations,
    # but their syntax cannot be evaluated as a standalone closing tactic.
    # Keep them in the diagnostic trace; never offer them as source edits.
    if event.get("syntax_kind") == [["s", "null"]] or raw[start:end].strip() == b"=>":
        raise ValueError("synthetic branch header is not an editable tactic")
    target = (raw[:start] + candidate.encode() + raw[end:]).decode()
    _envelope(source, target)  # Reject edits to headers/preludes or multiple declarations.
    return target


def closing_proposals(source, capture, *, candidates=("assumption", "rfl", "trivial"), limit=8):
    """Small baseline hammer; callers may inject LLM proposals through the collector.

    Prefer larger closing spans, deduplicate resulting source edits, and avoid
    `by` wrapper events that would change the theorem envelope. No proof claim.
    """
    if (type(limit) is not int or not 1 <= limit <= 16 or not isinstance(candidates, (list, tuple))
            or len(candidates) > 16 or any(not isinstance(c, str) or len(c.encode()) > 4096 for c in candidates)):
        raise ValueError("invalid proposal budget")
    events = [e for e in capture["trace"]["events"] if e["status"] == "captured"
              and e["before"]["goals"] and not e["after"]["goals"]
              and e["start"] is not None and e["end"] is not None]
    events.sort(key=lambda e: (int(e["start"])-int(e["end"]), int(e["id"])))
    out, seen = [], set()
    for event in events:
        for candidate in candidates:
            try:
                target = replace_event(source, event, candidate)
            except ValueError:
                continue
            if target not in seen and proof_source_tokens(target) < proof_source_tokens(source):
                seen.add(target)
                out.append({"event_id": int(event["id"]), "candidate": candidate})
                if len(out) == limit:
                    return out
    return out


def collect_replay_pairs(rows, *, capture_fn, replay_fn, compile_fn, environment_sha256: str,
                         proposal_fn=closing_proposals, max_rows=8, max_proposals=8,
                         refine_fn=None, refinement_rounds=0) -> dict[str, Any]:
    """Training-only search, fresh replay, then whole-theorem structural admission.

    Callbacks are trusted infrastructure. Invalid/unchecked proposals remain
    diagnostics. Only the smallest *admitted* candidate per source becomes a
    teacher; equal-token candidates retain proposal order rather than selecting
    by a source-name-dependent hash. No checkpoint is updated and no evaluation
    source/target is read.
    """
    if (type(max_rows) is not int or not 1 <= max_rows <= 16 or type(max_proposals) is not int
            or not 1 <= max_proposals <= 16 or not re.fullmatch(r"[0-9a-f]{64}", environment_sha256)
            or type(refinement_rounds) is not int or not 0 <= refinement_rounds <= 3
            or (refine_fn is None) != (refinement_rounds == 0)
            or (refine_fn is not None and not callable(refine_fn))):
        raise ValueError("invalid replay collection budget")
    ps._array(rows, 128)
    seen, train_rows = set(), []
    for row in rows:
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
            raise ValueError("duplicate or invalid row identity")
        seen.add(row["id"])
        if row["split"] not in ("train", "validation", "canary", "holdout"):
            raise ValueError("unknown split")
        if row["split"] == "train":
            train_rows.append(row)
    if not 1 <= len(train_rows) <= max_rows:
        raise ValueError("training row budget")
    attempts, pairs, graphs, captures, selected, calls = [], [], {}, {}, {}, 0
    refinements = []
    for row in train_rows:
        source = row["source"]
        if not isinstance(source, str) or len(source.encode()) > 65_536:
            raise ValueError("training source budget")
        capture = capture_fn(source)
        if not capture.get("ok"):
            attempts.append({"id": row["id"], "status": "capture_failed"})
            continue
        _check_capture(source, capture, environment_sha256)
        captures[row["id"]] = capture
        accepted = []
        first_attempt = len(attempts)
        seen_targets = set()

        def proposals_with_feedback():
            # The generator resumes only after the previous batch was checked.
            # Its budget is TOTAL per source, not multiplied by the round count.
            batch = proposal_fn(source, capture)
            ps._array(batch, max_proposals)
            for proposal in batch:
                yield 0, proposal
            for round_index in range(1, refinement_rounds + 1):
                remaining = max_proposals - (len(attempts) - first_attempt)
                if not remaining or any(pair[0]["target_tokens"] == 1 for pair in accepted):
                    break  # One proof-body token is the lexical lower bound here.
                feedback = []
                for attempt in attempts[first_attempt:]:
                    native = attempt.get("replay", {}).get("native", {})
                    feedback.append({k: attempt.get(k) for k in ("proposal", "round", "status", "reason")}
                                    | {"baseline": native.get("baseline"), "proposed": native.get("proposed"),
                                       "replay_error": attempt.get("replay", {}).get("reason"),
                                       "whole_source_gate": attempt.get("whole_source_gate", [])})
                entry = {"id": row["id"], "round": round_index, "remaining_proposals": remaining,
                         "feedback_sha256": digest(feedback), "status": "requested"}
                refinements.append(entry)
                try:
                    batch = refine_fn(source, deepcopy(capture), deepcopy(feedback),
                                      round_index=round_index, remaining=remaining)
                    ps._array(batch, remaining)
                    entry.update(status="returned", proposal_count=len(batch))
                except Exception as exc:
                    entry.update(status="error", reason=type(exc).__name__)
                    break  # No fallback, retry or fabricated positive receipt.
                if not batch:
                    break
                for proposal in batch:
                    yield round_index, proposal

        for round_index, proposal in proposals_with_feedback():
            ps._fields(proposal, "event_id candidate")
            event_id, candidate = proposal["event_id"], proposal["candidate"]
            attempt = {"id": row["id"], "proposal": proposal, "round": round_index, "status": "rejected"}
            attempts.append(attempt)
            try:
                if type(event_id) is not int or not 0 <= event_id < len(capture["trace"]["events"]):
                    raise ValueError("invalid event ID")
                target = replace_event(source, capture["trace"]["events"][event_id], candidate)
                target_digest = hashlib.sha256(target.encode()).hexdigest()
                if target_digest in seen_targets:
                    raise ValueError("duplicate candidate endpoint")
                seen_targets.add(target_digest)
                if proof_source_tokens(target) >= proof_source_tokens(source):
                    raise ValueError("candidate not shorter")
                replay = replay_fn(source, capture, event_id, candidate)
                attempt["replay"] = replay
                if (not replay.get("ok") or replay.get("native_sha256") != digest(replay.get("native"))
                        or any(replay.get(k) is not False for k in ("proof_admitted", "whole_source_checked"))):
                    raise ValueError("replay failed or malformed")
                expected_binding = {"source_sha256": capture["source_sha256"], "trace_sha256": capture["trace_sha256"],
                    "dependency_environment_sha256": environment_sha256, "exporter_sha256": capture["exporter_sha256"],
                    "event_id": event_id, "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                    "node_budget": capture["node_budget"], "event_budget": capture["event_budget"]}
                if replay.get("binding") != expected_binding or replay.get("environment") != digest(expected_binding):
                    raise ValueError("foreign replay receipt")
                if not validate_replay(replay["native"], capture=capture, event_id=event_id, candidate=candidate,
                                       environment=replay["environment"]):
                    raise ValueError("closing outcome not reproduced")
                gate = collect_structural_pairs([row], {row["id"]: target}, compile_fn=compile_fn,
                                                environment_sha256=environment_sha256)
                calls += gate["compile_calls"]
                attempt["whole_source_gate"] = gate["decisions"]
                if not gate["ok"]:
                    raise ValueError("whole-source structural gate rejected")
                pair = gate["pairs"][0]
                accepted.append((pair, gate["graphs"], len(attempts)-1))
                attempt.update(status="admitted_candidate", target_sha256=pair["target_sha256"])
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                attempt["reason"] = str(exc)[:240]
            if len(_bytes({"attempts": attempts, "graphs": graphs, "captures": captures, "accepted": accepted})) > 33_554_432:
                raise ValueError("replay dataset byte budget")
        if accepted:
            pair, additions, index = min(accepted, key=lambda p: p[0]["target_tokens"])
            pairs.append(pair)
            graphs.update(additions)
            attempt = attempts[index]
            event_id = attempt["proposal"]["event_id"]
            event = capture["trace"]["events"][event_id]
            selected[row["id"]] = {"attempt_index": index, "event_id": event_id,
                "round": attempt["round"],
                "candidate": attempt["proposal"]["candidate"], "source_span": {k: event[k] for k in ("start", "end")},
                "replay_sha256": attempt["replay"]["native_sha256"], "pair_sha256": pair["pair_sha256"],
                "atomic_source_to_target": True, "intermediate_teacher_created": False}
        if len(_bytes({"attempts": attempts, "graphs": graphs, "captures": captures,
                       "pairs": pairs, "selected_proposals": selected, "refinements": refinements})) > 33_554_432:
            raise ValueError("replay dataset byte budget")
    return {"schema": "jevops-replay-training-pairs/v1", "ok": len(pairs) == len(train_rows),
            "pairs": pairs, "graphs": graphs, "captures": captures, "attempts": attempts, "selected_proposals": selected,
            "capture_calls": len(train_rows), "compile_calls": calls,
            "refinements": refinements, "refinement_calls": len(refinements),
            "refinement_rounds": refinement_rounds, "max_proposals_per_source": max_proposals,
            "excluded_ids": [r["id"] for r in rows if r["split"] != "train"],
            "model_trained": False, "arena_data_used": False, "official_score": None,
            "selection_policy": "least_tokens_then_proposal_order",
            "dependency_closure_verified": False, "family_decontamination_verified": False}
