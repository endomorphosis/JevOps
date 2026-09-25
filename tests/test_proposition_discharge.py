"""Read-only sort inspection is a bounded search hint, never proof admission."""
import os
from pathlib import Path

import pytest

from jevops import arena_local as local, arena_lean as native, arena_providers as providers
from jevops.arena import VerificationRequest, content_hash
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from jevops.proof_replay import replace_event
from tests.test_arena_local import guard, PIN, RECORD, SOURCE
from tests.test_subgoal_retrieval import POOL
from tests.test_subgoal_ordering import ordered_stage, test_native_sibling_ordering as sibling_control
from tests.test_local_premise_replay import capture_fixture, inventory, RECORD as PLAN_RECORD


def inspected_stage(binding, payload):
    value = ordered_stage(binding, payload)
    if payload["mode"] == "search":
        r = value["report"]
        r.update(schema="jevops-local-search/v4", discharge_filter=payload["discharge_filter"],
            max_discharge_checks=payload["max_discharge_checks"], discharge_checks_exhausted=False,
            discharge_checks=[dict(id=0, at_step=0, depth=0, goal_index=0, head="True", kind="prop", decision="attempt")])
        r["trace"][0].update(action="assumption", depth=0, phase="discharge", retrieval_id=None, check_id=0)
        r["path"] = [dict(action="assumption", goal_index=0)]
        r["script"] = "solve | (focus (assumption))"
        r["application"]["search"]["candidate"] = r["script"]
    return value


def runtime(guard, runner=inspected_stage, max_processes=2):
    return local.ArenaLocalRuntime(guard, RECORD, runner=runner, max_processes=max_processes)


SETTINGS = dict(subgoal_pool=POOL, discharge_window=8, discharge_filter="propositions-v1")


def test_fixture_exact_inspection_budget_and_mode_identity(guard):
    rt = runtime(guard, max_processes=3)
    capture = rt.capture(PIN)["capture"]
    prop = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], **SETTINGS, max_discharge_checks=1, max_steps=1)
    obs = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"],
        **{**SETTINGS, "discharge_filter": "observe-all-v1"}, max_discharge_checks=1, max_steps=1)
    assert prop["ok"] and prop["closing_reproduced"] and obs["closing_reproduced"]
    assert prop["discharge_checks_reserved"] == prop["discharge_checks_observed"] == 1
    assert prop["search_steps_observed"] == prop["search_steps_reserved"] == 1
    assert prop["discharge_skips"] == 0 and prop["environment"] != obs["environment"]
    assert prop["evidence_mode"] == "fixture" and not prop["proof_admitted"]


@pytest.mark.parametrize("kind", ["data", "unknown", "error"])
def test_nonproposition_observations_are_explicit_skips(guard, kind):
    def skipped(binding, payload):
        v = inspected_stage(binding, payload)
        if payload["mode"] == "search":
            r = v["report"]
            r["discharge_checks"].insert(0, dict(id=0, at_step=0, depth=1, goal_index=1,
                head=None, kind=kind, decision="skip"))
            r["discharge_checks"][1]["id"] = r["trace"][0]["check_id"] = 1
        return v
    rt = runtime(guard, skipped)
    capture = rt.capture(PIN)["capture"]
    r = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], **SETTINGS)
    assert r["ok"] and r["closing_reproduced"] and r["discharge_skips"] == 1
    assert r["discharge_checks_observed"] == 2 and r["search_steps_observed"] == 1


@pytest.mark.parametrize("damage", ["mode", "limit", "bool", "count", "exhaustion", "id", "step", "index",
    "depth", "head", "kind", "decision", "unknown_attempt", "data_attempt", "error_attempt", "extra",
    "missing_link", "linked_skip", "wrong_depth", "wrong_index", "unconsumed", "double_link", "forged"])
def test_bad_inspection_receipt_is_not_admitted(guard, damage):
    def corrupt(binding, payload):
        v = inspected_stage(binding, payload)
        if payload["mode"] == "search":
            r = v["report"]; c = r["discharge_checks"][0]; row = r["trace"][0]
            if damage == "mode": r["discharge_filter"] = "observe-all-v1"
            elif damage == "limit": r["max_discharge_checks"] = 1
            elif damage == "bool": c["id"] = True
            elif damage == "count": r["discharge_checks"] *= 257
            elif damage == "exhaustion": r["discharge_checks_exhausted"] = True
            elif damage == "id": c["id"] = 1
            elif damage == "step": c["at_step"] = 1
            elif damage == "index": c["goal_index"] = 8
            elif damage == "depth": c["depth"] = 4
            elif damage == "head": c["head"] = float("nan")
            elif damage == "kind": c["kind"] = "proof"
            elif damage == "decision": c["decision"] = "skip"
            elif damage.endswith("_attempt"): c["kind"] = damage.split("_")[0]
            elif damage == "extra": c["verified"] = True
            elif damage == "missing_link": row["check_id"] = None
            elif damage == "linked_skip": c.update(kind="data", decision="skip")
            elif damage == "wrong_depth": c["depth"] = 1
            elif damage == "wrong_index": c["goal_index"] = 1
            elif damage == "unconsumed": r["discharge_checks"].append({**c, "id": 1})
            elif damage == "double_link":
                r["trace"].append(dict(row)); r["attempted_steps"] = 2
            else: r["application"]["roundtrip"]["environment"] = "c" * 64
        return v
    rt = runtime(guard, corrupt)
    capture = rt.capture(PIN)["capture"]
    r = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], **SETTINGS)
    assert r["status"] == "ERROR" and not r["closing_reproduced"] and r["extracted_candidate"] is None
    assert r["discharge_checks_reserved"] == 256


@pytest.mark.parametrize("args", [{"max_discharge_checks": True}, {"max_discharge_checks": -1},
    {"max_discharge_checks": 257}, {"discharge_filter": "bad"}, {"discharge_filter": {}}, {"discharge_window": 0}])
def test_invalid_filter_configuration_before_launch(guard, args):
    rt = runtime(guard)
    c = rt.capture(PIN)["capture"]
    with pytest.raises(ValueError):
        rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **{**SETTINGS, **args})
    assert rt.attempts == 1


def test_zero_inspection_budget_and_timeout_reservations(guard):
    def timeout(binding, payload):
        if payload["mode"] == "search": raise TimeoutError("fixture infrastructure timeout")
        return inspected_stage(binding, payload)
    rt = runtime(guard, timeout)
    c = rt.capture(PIN)["capture"]
    zero = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **SETTINGS, max_discharge_checks=0)
    assert zero["status"] == "BUDGET_EXHAUSTED" and zero["discharge_checks_reserved"] == 0
    assert rt.attempts == 1
    r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **SETTINGS)
    assert r["status"] == "ERROR" and r["discharge_checks_reserved"] == 256
    assert r["discharge_checks_observed"] is r["search_steps_observed"] is None


def test_planner_binds_new_mode_preserves_legacy_and_zero_no_query(monkeypatch):
    index, scope = inventory()
    args = (PLAN_RECORD, capture_fixture(), index, scope)
    options = dict(search="subgoal-v1", discharge_window=8, max_applications=1)
    legacy = providers.plan_local_applications(*args, **options)
    assert legacy == providers.plan_local_applications(*args, **options, discharge_filter="none")
    typed = providers.plan_local_applications(*args, **options, discharge_filter="propositions-v1")
    assert typed["request"]["request_sha256"] != legacy["request"]["request_sha256"]
    assert typed["request"]["discharge_check_reservation_ceiling"] == 256
    assert typed["applications"][0]["discharge_filter"] == "propositions-v1"
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **k: pytest.fail("zero observation query"))
    zero = providers.plan_local_applications(*args, **options, discharge_filter="propositions-v1", max_discharge_checks=0)
    assert zero["status"] == "BUDGET_EXHAUSTED" and not zero["applications"]


def test_batch_propagates_observation_accounting(guard):
    rt = runtime(guard)
    c = rt.capture(PIN)["capture"]
    env = rt.context.context_id
    index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
    scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
    b = rt.discover_batch(PIN, c, index, scope, search="subgoal-v1", discharge_window=8,
        discharge_filter="propositions-v1", max_applications=1)
    assert b["status"] == "FIXTURE_DRAFTS_ONLY" and len(b["drafts"]) == 1
    assert b["discharge_checks_reserved"] == 256 and b["discharge_checks_observed"] == 1


@pytest.mark.no_seal(reason="native proposition-only ordering, installed toolchains only")
@pytest.mark.parametrize("case", ["constraining", "rollback", "conjunction"])
def test_native_proposition_sibling_controls(tmp_path, case):
    sibling_control(tmp_path, case, discharge_filter="propositions-v1")


PREFIX = """universe u
inductive Wrapped (α : Sort u) (P : Prop) : Prop where
  | mk : α → P → Wrapped α P
abbrev DataAlias := List Nat
abbrev PropAlias (P : Prop) := P
"""


@pytest.mark.no_seal(reason="native data/Prop/sort distinction; installed Lean only")
@pytest.mark.parametrize("case", ["list", "function", "unknown", "prop_alias", "axiom"])
def test_native_goal_classification(tmp_path, case):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no API/downloads")
    tag = os.environ.get("JEVOPS_SEARCH_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "proposition-discharge-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    prefix, extra = PREFIX, ""
    alpha = {"list": "DataAlias", "function": "(Nat → Nat)", "unknown": "α", "prop_alias": "(PropAlias P)", "axiom": "DataAlias"}[case]
    if case == "unknown": extra = "(α : Sort u) "
    statement = f"theorem sample {extra}(P : Prop) (noise : {alpha}) (h : P) : Wrapped {alpha} P"
    source = statement + " := by\n  exact Wrapped.mk (id (id noise)) (id (id h))\n"
    names = ["Wrapped.mk"]
    if case == "axiom":
        prefix += "axiom forged (P : Prop) : Wrapped DataAlias P\n"
        names = ["forged"]
    record = {"name": "Suite.sample", "statement": statement, "src": source, "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix + "namespace Suite\n", project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=7)
    capture_result = rt.capture(pin)
    assert capture_result["ok"], capture_result
    capture = capture_result["capture"]
    event = next(e for e in capture["trace"]["events"] if source.encode()[int(e["start"]):int(e["end"])].startswith(b"exact "))
    settings = dict(subgoal_pool=[dict(name=n, head="Wrapped") for n in names], discharge_window=8,
                    discharge_filter="propositions-v1", max_steps=96, max_depth=5, retrieval_top_k=1)
    def run(**kwargs):
        return rt.discover_search(pin, source, capture, int(event["id"]), names, **{**settings, **kwargs})
    result = run()
    assert result["ok"], result.get("reason", result)
    positive = case not in {"unknown", "axiom"}
    assert result["closing_reproduced"] == positive, result
    checks = result["search_report"]["discharge_checks"]
    assert all(c["decision"] == ("attempt" if c["kind"] == "prop" else "skip") for c in checks)
    assert not any(c["kind"] == "error" for c in checks)
    assert guard(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    if positive:
        target = replace_event(source, event, result["extracted_candidate"])
        assert guard(VerificationRequest(rt.context, target, pin)).outcome.value == "VERIFIED"
    if case in {"list", "function"}: assert any(c["kind"] == "data" for c in checks)
    if case == "unknown": assert any(c["kind"] == "unknown" for c in checks)
    if case == "prop_alias": assert {c["kind"] for c in checks} == {"prop"}
    if case in {"list", "unknown"}:
        observed, legacy = run(discharge_filter="observe-all-v1"), run(discharge_filter="none")
        assert observed["closing_reproduced"] and legacy["closing_reproduced"]
        # Classification must not leak universe/metavariable assignments, reorder
        # actions, add queries or refund attempts when the filter is disabled.
        a, b = observed["search_report"], legacy["search_report"]
        assert a["path"] == b["path"] and a["retrievals"] == b["retrievals"]
        assert [{k:v for k,v in row.items() if k != "check_id"} for row in a["trace"]] == b["trace"]
    if case == "list":
        units = result["discharge_checks_observed"]
        exact, below = run(max_discharge_checks=units), run(max_discharge_checks=units-1)
        assert exact["closing_reproduced"] and exact["discharge_checks_observed"] == exact["discharge_checks_reserved"]
        assert below["ok"] and not below["closing_reproduced"] and below["search_report"]["discharge_checks_exhausted"]
