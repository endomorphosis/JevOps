"""Charged sibling discharge, reversible unification and independent replay."""
import os
from pathlib import Path

import pytest

from jevops import arena_local as local, arena_lean as native, arena_providers as providers
from jevops.arena import VerificationRequest, reference_tokens
from jevops.lean import VersionPin
from jevops.proof_replay import replace_event
from tests.test_arena_local import guard, PIN, RECORD, SOURCE
from tests.test_subgoal_retrieval import dynamic_stage, POOL
from tests.test_local_premise_replay import capture_fixture, inventory, RECORD as PLAN_RECORD


def ordered_stage(binding, payload):
    value = dynamic_stage(binding, payload)
    if payload["mode"] == "search":
        r = value["report"]
        r.update(schema="jevops-local-search/v3", discharge_window=payload["discharge_window"])
        r["trace"][0].update(phase="expand", goal_index=0)
        r["path"] = [{"action": a, "goal_index": 0} for a in r["path"]]
    return value


def test_fixture_protocol_and_window_identity(guard):
    rt = local.ArenaLocalRuntime(guard, RECORD, runner=ordered_stage, max_processes=3)
    capture = rt.capture(PIN)["capture"]
    results = [rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"],
        subgoal_pool=POOL, discharge_window=w, max_steps=1) for w in (1, 8)]
    assert all(r["ok"] and r["closing_reproduced"] for r in results)
    assert results[0]["environment"] != results[1]["environment"]
    assert results[0]["binding"]["operation"] == "discharge-backward-materialization/v1"
    assert all(r["search_steps_observed"] == r["search_steps_reserved"] == 1 for r in results)
    assert all(not r["proof_admitted"] and r["evidence_mode"] == "fixture" for r in results)


@pytest.mark.parametrize("damage", ["schema", "window", "bool", "index", "phase", "non_assumption",
    "uncharged", "extra", "script", "query", "forged", "path_index", "path_action", "unretrieved"])
def test_invalid_ordering_receipt_never_admitted(guard, damage):
    def corrupt(binding, payload):
        value = ordered_stage(binding, payload)
        if payload["mode"] == "search":
            r = value["report"]
            row, step = r["trace"][0], r["path"][0]
            if damage == "schema": r["schema"] = "jevops-local-search/v2"
            elif damage == "window": r["discharge_window"] = 9
            elif damage == "bool": row["goal_index"] = True
            elif damage == "index": row["goal_index"] = 8
            elif damage == "phase": row["phase"] = "model_verified"
            elif damage == "non_assumption": row.update(phase="discharge", retrieval_id=None)
            elif damage == "uncharged": row["applied"] = False
            elif damage == "extra": step["verified"] = True
            elif damage == "script": r["script"] = "solve | sorry"
            elif damage == "query": row.update(phase="discharge", action="assumption")
            elif damage == "forged": r["application"]["roundtrip"]["environment"] = "f" * 64
            elif damage == "path_index": step["goal_index"] = 1
            elif damage == "path_action": step["action"] = "sorry"
            else: row["retrieval_id"] = None
        return value
    rt = local.ArenaLocalRuntime(guard, RECORD, runner=corrupt, max_processes=2)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL, discharge_window=8)
    assert result["status"] == "ERROR" and not result["closing_reproduced"]
    assert result["extracted_candidate"] is None and result["search_steps_reserved"] == 96


@pytest.mark.parametrize("window", [True, -1, 17, 1.5])
def test_invalid_window_before_launch(guard, window):
    rt = local.ArenaLocalRuntime(guard, RECORD, runner=ordered_stage, max_processes=2)
    capture = rt.capture(PIN)["capture"]
    with pytest.raises(ValueError):
        rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL, discharge_window=window)
    assert rt.attempts == 1


def test_zero_steps_no_launch_and_missing_pool_rejected(guard):
    rt = local.ArenaLocalRuntime(guard, RECORD, runner=ordered_stage, max_processes=2)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL,
                                discharge_window=8, max_steps=0)
    assert result["status"] == "BUDGET_EXHAUSTED" and not result["reserved_processes"]
    with pytest.raises(ValueError, match="pool"):
        rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], discharge_window=8)
    assert rt.attempts == 1


def test_planner_preserves_default_and_binds_opt_in():
    index, scope = inventory()
    args = (PLAN_RECORD, capture_fixture(), index, scope)
    default = providers.plan_local_applications(*args, search="subgoal-v1")
    zero = providers.plan_local_applications(*args, search="subgoal-v1", discharge_window=0)
    ordered = providers.plan_local_applications(*args, search="subgoal-v1", discharge_window=8)
    assert default == zero
    assert default["request"]["request_sha256"] != ordered["request"]["request_sha256"]
    assert ordered["request"]["goal_order"] == "bounded-assumption-first/v1"
    assert all(a["discharge_window"] == 8 for a in ordered["applications"])
    with pytest.raises(ValueError, match="subgoal"):
        providers.plan_local_applications(*args, search="backward-v1", discharge_window=8)


PREFIX = """def Middle (P : Nat → Prop) (n : Nat) : Prop := ¬¬ P n
def Final (P : Nat → Prop) (K : Nat → Nat → Prop) (n : Nat) : Prop :=
  ∃ m, Middle P m ∧ K m n
theorem finish {P K m n} (h : Middle P m) (hk : K m n) : Final P K n := ⟨m, h, hk⟩
theorem bridge {P n} (h : P n) : Middle P n := fun hn => hn h
"""


@pytest.mark.no_seal(reason="native sibling ordering; installed Lean only, no downloads/API")
@pytest.mark.parametrize("case", ["constraining", "rollback", "conjunction", "missing", "boundary", "window"])
def test_native_sibling_ordering(tmp_path, case, discharge_filter="none", cycle_guard="none", cycle_key="raw-v1"):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in")
    tag = os.environ.get("JEVOPS_SEARCH_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "sibling-order-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    # Lean assumption scans locals in reverse: ha gives the WRONG intermediate
    # state unless the K sibling has first constrained it to b.
    statement = "theorem sample (P : Nat → Prop) (K : Nat → Nat → Prop) (a b c : Nat) (hb : P b) (ha : P a) (hk : K b c) : Final P K c"
    answer = "Exists.intro b (And.intro (fun hn => hn (id (id hb))) (id hk))"
    if case == "rollback":
        # The first successful later-sibling discharge chooses b, but no P b
        # is available. It must undo b and fall back to ordinary first-goal work.
        statement = "theorem sample (P : Nat → Prop) (K : Nat → Nat → Prop) (a b c : Nat) (ha : P a) (hgood : K a c) (hbad : K b c) : Final P K c"
        answer = "Exists.intro a (And.intro (fun hn => hn (id (id ha))) (id hgood))"
    elif case == "conjunction":
        statement += " ∧ Final P K c"
        answer = f"And.intro ({answer}) ({answer})"
    source = statement + " := by\n  exact " + answer + "\n"
    record = {"name": "Suite.sample", "statement": statement, "src": source, "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, PREFIX + "namespace Suite\n", project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=6)
    captured = rt.capture(pin)
    assert captured["ok"], captured.get("reason", captured)
    capture = captured["capture"]
    event = next(e for e in capture["trace"]["events"] if source.encode()[int(e["start"]):int(e["end"])].startswith(b"exact "))
    pool = [{"name": "bridge", "head": "Middle"}, {"name": "finish", "head": "Final"}]
    if case == "missing": pool = pool[1:]
    settings = dict(subgoal_pool=pool, max_steps=96, max_depth=4 if case == "conjunction" else 3,
                    max_retrievals=32, retrieval_top_k=2, discharge_window=1 if case == "window" else 8,
                    discharge_filter=discharge_filter, cycle_guard=cycle_guard, cycle_key=cycle_key)
    def run(**updates):
        return rt.discover_search(pin, source, capture, int(event["id"]), ["finish"], **{**settings, **updates})
    result = run()
    assert result["ok"], result.get("reason", result)
    positive = case not in {"missing", "window"}
    assert result["closing_reproduced"] == positive, result
    report = result["search_report"]
    assert result["search_steps_observed"] == len(report["trace"]) <= 96
    assert guard(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    if positive:
        draft = replace_event(source, event, result["extracted_candidate"])
        assert guard(VerificationRequest(rt.context, draft, pin)).outcome.value == "VERIFIED"
        assert reference_tokens(draft, statement) < reference_tokens(source, statement)
        if case == "rollback":
            assert any(t["goal_index"] == 1 and t["applied"] for t in report["trace"])
            assert all(p["goal_index"] == 0 for p in report["path"])
        else:
            assert any(p["goal_index"] == 1 for p in report["path"])
            assert "(all_goals skip); (rotate_left 1); (focus (assumption))" in report["script"]
    if case == "constraining":
        fixed = run(discharge_window=0, discharge_filter="none")
        assert fixed["ok"] and not fixed["closing_reproduced"]
    if case == "boundary":
        exact = run(max_steps=result["search_steps_observed"])
        assert exact["closing_reproduced"] and exact["search_steps_observed"] == exact["search_steps_reserved"]
        below = run(max_steps=result["search_steps_observed"] - 1)
        assert below["ok"] and not below["closing_reproduced"] and below["search_report"]["step_exhausted"]
