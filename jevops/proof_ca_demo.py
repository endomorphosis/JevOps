#!/usr/bin/env python3
"""Offline proof-carrying graph cellular automaton example and benchmark.

Run from the repository root with::

    python -m jevops.proof_ca_demo

The verifier is an injected mock.  It is present only to exercise the adapter
boundary; no API, model, Lean installation, or external credential is used.
"""
from __future__ import annotations

import json
import time
from typing import Any, Mapping

from jevops.proof_ca import (
    Atom,
    ActionType,
    ContextIdentity,
    DeterministicPolicy,
    ProofGraphCA,
    Rule,
    VerificationReceipt,
    VerificationStatus,
)


class CentralizedScorePolicy(DeterministicPolicy):
    """A centralized scoring fixture using the same local policy interface.

    The score only orders proposed actions.  The proof runtime still performs
    all symbolic validation, so this is a scheduling comparison rather than a
    second source of logical authority.
    """

    model_id = "centralized-score-fixture"

    @staticmethod
    def action_score(snapshot: Any, action: str) -> float:
        if action == ActionType.ATTEMPT_RULE.value and snapshot.enabled_rules:
            return 1.0
        if action == ActionType.REQUEST_DEPENDENCY.value and snapshot.mandatory_dependencies:
            return 0.5
        return 0.0

    def propose(self, snapshot: Any, allowed_actions: Any) -> Any:
        # Evaluate the same bounded snapshot/action interface as a controller
        # would.  DeterministicPolicy supplies the checked proposal shape.
        ranked = sorted(
            (str(action) for action in allowed_actions),
            key=lambda action: (-self.action_score(snapshot, action), action),
        )
        if ranked and ranked[0] == ActionType.ATTEMPT_RULE.value and snapshot.enabled_rules:
            return super().propose(snapshot, (ActionType.ATTEMPT_RULE.value,))
        return super().propose(snapshot, allowed_actions)


class MockVerifier:
    """Deterministic verifier fixture; not a live verifier or proof engine."""

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, request: Any) -> VerificationReceipt:
        self.calls += 1
        return VerificationReceipt(
            receipt_id=f"mock-receipt-{self.calls}",
            context_id=request.context_id,
            target=request.target,
            status=VerificationStatus.VERIFIED,
            verifier_id=request.verifier_id,
            verifier_version=request.verifier_version,
            candidate_artifact=request.candidate_artifact,
            source_dependencies=request.source_dependencies,
            details=(
                ("fixture", True),
                ("note", "mock receipt; not a Lean proof"),
            ),
        )


def _reasoning_runtime(*, policy: Any = None, seed: int | None = None) -> ProofGraphCA:
    a, b, c, goal, x, y = [Atom(name) for name in ("A", "B", "C", "Goal", "X", "Y")]
    return ProofGraphCA(
        atoms=[a, b, c, goal, x, y],
        rules=[
            Rule("r_ab", (a,), b),
            Rule("r_ac", (a,), c),
            Rule("r_goal", (b, c), goal),
            Rule("r_disconnected", (x,), y),
        ],
        assumptions=[a],
        targets=[goal],
        policy=policy or DeterministicPolicy(),
        schedule_seed=seed,
        operation_budget=64,
    )


def _schedule_report(name: str, *, policy: Any, seed: int | None, fair_period: int) -> dict[str, Any]:
    runtime = _reasoning_runtime(policy=policy, seed=seed)
    result = runtime.run(fair_period=fair_period)
    metrics = result["metrics"]
    return {
        "controller": name,
        "status": result["status"],
        "accepted_facts": result["accepted_facts"],
        "achieved_targets": [target for target in result["targets"] if target in result["accepted_facts"]],
        "rule_attempts": metrics["rule_attempts"],
        "verifier_attempts": metrics["verifier_attempts"],
        "policy_calls": metrics["policy_calls"],
        "messages_delivered": metrics["messages_delivered"],
        "graph_traversal_edges": metrics["edges_traversed"],
        "cells_visited": metrics["cells_visited"],
        "resource_units": result["resources"]["consumed"],
        "wall_time_ms": result["wall_time_ms"],
        "actual_cost": result["actual_cost"],
    }


def _external_report() -> dict[str, Any]:
    checked = Atom("Checked")
    verifier = MockVerifier()
    context = ContextIdentity.create(
        facts_revision="demo-facts-v1",
        rules_revision="demo-rules-v1",
        target=checked.key,
        candidate_artifact="demo-artifact",
        source_dependencies=["demo/source.py"],
        verifier_id="mock-verifier",
        verifier_version="1",
        verifier_options={"axioms": "none"},
        axiom_policy="none",
    )
    runtime = ProofGraphCA(
        atoms=[checked],
        rules=[],
        assumptions=[],
        targets=[checked],
        context=context,
        verifier=verifier,
    )
    outcome = runtime.checked_apply(runtime.make_external_proposal(target=checked))
    return {
        "outcome": outcome["outcome"],
        "status": runtime.report()["status"],
        "verifier_calls": verifier.calls,
        "receipt_is_mock": True,
        "receipt_is_live": False,
    }


def _dependency_change() -> dict[str, Any]:
    runtime = _reasoning_runtime(seed=0)
    first = runtime.run(fair_period=1)
    changed_context = ContextIdentity.create(
        facts_revision="demo-facts-v2-dependency-changed",
        rules_revision=runtime.context.rules_revision,
    )
    next_epoch = runtime.new_epoch(changed_context)
    second = next_epoch.run(fair_period=1)
    return {
        "old_context": runtime.context.context_id,
        "new_context": next_epoch.context.context_id,
        "historical_evidence_retained": len(next_epoch.historical_evidence),
        "work_reused_as_current": 0,
        "work_recomputed": second["metrics"]["rule_attempts"],
        "new_epoch_rule_attempts": second["metrics"]["rule_attempts"],
        "new_epoch_status": second["status"],
        "old_rule_attempts": first["metrics"]["rule_attempts"],
        "old_evidence_reused_as_current": False,
    }


def run_demo() -> dict[str, Any]:
    started = time.perf_counter()
    runtime = _reasoning_runtime(seed=7)
    result = runtime.run(fair_period=3)
    accepted_events = [
        {
            "atom": row.get("payload", {}).get("atom"),
            "evidence_id": row.get("payload", {}).get("evidence_id"),
            "event": row.get("type"),
        }
        for row in runtime.event_log
        if row.get("type") == "fact_accepted"
    ]
    benchmark = [
        _schedule_report("deterministic_dependency_queue", policy=DeterministicPolicy(), seed=None, fair_period=1),
        _schedule_report("centralized_same_action_interface", policy=CentralizedScorePolicy(), seed=0, fair_period=1),
        _schedule_report("local_cellular_fair_scheduler", policy=DeterministicPolicy(), seed=7, fair_period=3),
    ]
    return {
        "schema": "jevops-proof-ca-demo/v1",
        "offline": True,
        "model_calls": 0,
        "trace": {
            "status": result["status"],
            "accepted_facts": result["accepted_facts"],
            "goal_evidence": result["target_evidence"],
            "local_fact_events": accepted_events,
        },
        "external_adapter": _external_report(),
        "benchmark": benchmark,
        "dependency_change": _dependency_change(),
        "runtime_wall_time_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "cost_measured": False,
        "limitations": [
            "The verifier in this example is a mock fixture, not Lean or a live model.",
            "Scheduling is single-process ownership; no cross-process lock claim is made.",
            "The Horn language is ground, positive, finite, and does not provide arbitrary theorem proving.",
        ],
    }


def main() -> None:
    print(json.dumps(run_demo(), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
