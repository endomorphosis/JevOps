"""Local graph inferences remain proposals until the existing Lean gate runs."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

from jevops.arena import (ArenaContext, ArenaEvaluator, Outcome, VersionReceipt,
                          content_hash, reference_tokens, source_hash)
from jevops.knowledge_proofs import ProofStep, evaluate_plan, propose_local, render_plan
from jevops.lean import VersionPin
from jevops.logic_ir import parse_formula

ENV = content_hash("fixture environment")
CASES = [
    ("(p q r : Prop) (hp : p) (hpq : p → q) (hqr : q → r) : r",
     "have hq : q := hpq hp\n  have hr : r := hqr hq\n  exact hr"),
    ("(p q : Prop) (hpq : p → q) (hqp : q → p) : p ↔ q",
     "constructor\n  · exact hpq\n  · exact hqp"),
    ("(p q : Prop) (h : p ↔ q) (hq : q) : p", "exact h.mpr hq"),
    ("(p q : Prop) (h : p ∧ q) : q ∧ p", "exact And.intro h.right h.left"),
]


def example(case=0):
    header, body = CASES[case]
    statement = "theorem sample " + header
    return statement, statement + " := by\n  " + body + "\n"


@pytest.mark.parametrize("case", range(len(CASES)))
def test_relational_plans_preserve_context_and_render_deterministically(case):
    statement, source = example(case)
    result = propose_local(source, statement=statement, environment_sha256=ENV)
    assert result["status"] == "PROPOSED"
    plan = result["plan"]
    assert not result["proof_verified"] and not plan.to_dict()["minimality_proven"]
    assert result["candidate"].startswith(statement + " := by\n  exact ")
    assert render_plan(plan, source=source, statement=statement, environment_sha256=ENV) == result["candidate"]
    assert plan.plan_sha256 == propose_local(source, statement=statement, environment_sha256=ENV)["plan"].plan_sha256


def test_missing_relation_direction_is_not_invented():
    statement = "theorem sample (p q : Prop) (h : p → q) (hq : q) : p"
    result = propose_local(statement + " := by\n  skip", statement=statement, environment_sha256=ENV)
    assert result["status"] == "NO_PLAN" and result["candidate"] is None


def test_unseeded_cycles_do_not_create_facts():
    statement = "theorem sample (p q : Prop) (h : p → q) (g : q → p) : p"
    assert propose_local(statement + " := by\n  skip", statement=statement,
                         environment_sha256=ENV)["status"] == "NO_PLAN"


@pytest.mark.parametrize("case", ["environment", "source", "goal", "forward", "unknown", "wrong_type", "unreachable"])
def test_malformed_or_foreign_plans_fail_closed(case):
    statement, source = example()
    plan = propose_local(source, statement=statement, environment_sha256=ENV)["plan"]
    steps = list(plan.steps)
    if case == "environment": plan = replace(plan, environment_sha256="a" * 64)
    elif case == "source": source += "\n"
    elif case == "goal": statement = statement[:-1] + "p"
    elif case == "forward": steps[0] = replace(steps[0], parents=(0,))
    elif case == "unknown": steps[0] = replace(steps[0], reference="GraphAssertedClaim")
    elif case == "wrong_type": steps[-1] = replace(steps[-1], conclusion=parse_formula("q"))
    elif case == "unreachable": steps.append(steps[0])
    plan = replace(plan, steps=tuple(steps))
    with pytest.raises(ValueError):
        render_plan(plan, source=source, statement=statement, environment_sha256=ENV)


def test_unsupported_dependent_types_and_search_limits_abstain():
    statement = "theorem sample (n : Nat) : n = n"
    assert propose_local(statement + " := by rfl", statement=statement, environment_sha256=ENV)["status"] == "UNSUPPORTED"
    statement, source = example()
    for options in ({"max_steps": 1}, {"max_applications": 1}):
        result = propose_local(source, statement=statement, environment_sha256=ENV, **options)
        assert result["status"] == "SEARCH_BUDGET" and result["candidate"] is None


def test_all_pin_evaluator_bridge_keeps_fixtures_out_of_native_claims():
    statement, source = example()
    pins = (VersionPin("fixture-a", "a"), VersionPin("fixture-b", "b"))
    context = ArenaContext("sample", statement, source, reference_tokens(source, statement), 100,
                           pins, (ENV, ENV), "fixture", "1", "synthetic/v1")
    calls = []
    def verifier(request):
        calls.append(request)
        return VersionReceipt(request.request_id, source_hash(request.source), "sample", Outcome.VERIFIED,
                              True, 0, "'sample' does not depend on any axioms", 50)
    evaluator = ArenaEvaluator(context, verifier, max_calls=2, evidence_mode="offline_fixture")
    plan = propose_local(source, statement=statement, environment_sha256=context.context_id)["plan"]
    report = evaluate_plan(plan, evaluator=evaluator)
    assert report["all_pins_passed"] and len(calls) == 2
    assert not report["proof_verified"] and not report["training_enabled"] and not report["promoted"]
    assert report["official_score"] is None


@pytest.mark.no_seal(reason="native Lean proof/type and axiom checks must run fresh")
@pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1", reason="explicit installed-Lean opt-in")
@pytest.mark.parametrize("tag", ["v4.26.0", "v4.29.1"])
@pytest.mark.parametrize("case", range(len(CASES)))
def test_native_lean_checks_generated_graph_proofs(tmp_path, tag, case):
    from jevops.arena_lean import ProjectBinding, pinned_lean, run_native
    lean = pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    statement, source = example(case)
    proposal = propose_local(source, statement=statement, environment_sha256=ENV)
    binding = ProjectBinding(VersionPin(tag, "local-knowledge-control"), lean, tmp_path, "", project_backed=False)
    report, code = run_native(binding, {"request_id": "knowledge-control", "target": "sample",
        "max_heartbeats": 200000, "prefix": "", "reference": source,
        "candidate": proposal["candidate"]}, timeout=30)
    assert code == 0, report
    data = report["report"]
    assert data["outcome"] == "VERIFIED" and data["type_preserved"], data
    assert data["axioms"] == [] and data["reference_axioms"] == []
    assert data["raw_heartbeats"] >= 0 and data["reference_raw_heartbeats"] >= 0
