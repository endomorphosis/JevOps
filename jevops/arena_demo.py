"""Offline score-aware router example. All verifier/heartbeat data are fixtures."""
from __future__ import annotations

import json

from .arena import (ArenaContext, ArenaEvaluator, Outcome, VersionReceipt,
                    content_hash, proof_suffix, reference_tokens, source_hash)
from .lean import VersionPin
from .router_tuning import RouterTuningConfig, RouterTuningLoop


def run_demo() -> dict:
    statement = "theorem fixture (h : True) : True"
    source = statement + " := by\n  have redundant : True := h\n  exact redundant"
    context = ArenaContext(
        "fixture", statement, source, reference_tokens(source, statement), 100,
        (VersionPin("fixture-v1", "fixture-revision-1"), VersionPin("fixture-v2", "fixture-revision-2")),
        (content_hash("fixture-deps-1"), content_hash("fixture-deps-2")),
        "mock-lean-verifier", "1", "synthetic-heartbeats/v1",
    )
    attempts = []

    def verifier(request):
        body = " ".join(proof_suffix(request.source, statement).split())
        # Deliberately illustrates shorter source versus lower elaboration cost.
        # These numbers are NOT measurements of these Lean tactics.
        heartbeats = {"by trivial": 1000, "by exact id h": 0}.get(body, 100)
        receipt = VersionReceipt(request.request_id, source_hash(request.source), "fixture", Outcome.VERIFIED,
                                 True, 0, "'fixture' does not depend on any axioms", heartbeats)
        attempts.append({"request_id": request.request_id, "source": request.source,
                         "version": request.version.lean_tag, "fixture_heartbeats": heartbeats})
        return receipt

    evaluator = ArenaEvaluator(context, verifier, max_calls=80, evidence_mode="offline_fixture")
    result = RouterTuningLoop(
        {}, source, problem="fixture", arena_evaluator=evaluator,
        config=RouterTuningConfig(selection_objective="arena-v1", train=False, rounds=2,
                                  max_candidate_pool=8, n_variations=1, teacher_replay=False,
                                  hammer_sweep=False, logic_reductions=False),
        router_generate=lambda _: json.dumps({"candidates": [{"tactics": "trivial"}, {"tactics": "exact id h"}]}),
    ).run()
    return {"schema": "jevops-arena-demo/v1", "evidence_mode": "offline_fixture", "live_model_calls": 0,
            "lean_compilations": 0, "official_score": None, "selected_source": result["best_source"],
            "evaluation": result["arena"], "attempts": attempts, "history": result["history"]}


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2, allow_nan=False))
