"""Bounded native AND/OR search. Offline receipts are labelled fixtures only."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path

import pytest

from jevops import arena_local as local, arena_lean as native, arena_providers as providers
from jevops.arena import content_hash, VerificationRequest, reference_tokens
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope, PremiseSignature, ExprHead
from jevops.proof_replay import replace_event
from tests.test_arena_local import guard, stage, PIN, OTHER, RECORD, SOURCE
from tests.test_local_application import application_stage
from tests.test_local_premise_replay import capture_fixture, rehash, inventory, RECORD as PLAN_RECORD, name


def search_stage(binding, payload):
    if payload["mode"] != "search":
        return stage(binding, payload)
    path = ["apply _root_.True.intro"]
    script = "solve | (focus (apply _root_.True.intro))"
    value = application_stage(binding, {**payload, "mode": "application", "candidate": script})
    value["report"] = {"schema": "jevops-local-search/v1", "lean_version": value["lean_version"],
        "lean_githash": value["lean_githash"], "premises": payload["premises"],
        "max_steps": payload["max_steps"], "max_depth": payload["max_depth"],
        "attempted_steps": 1, "depth_cutoffs": 0, "step_exhausted": False,
        "trace": [{"action": path[0], "depth": 0, "applied": True}],
        "path": path, "script": script, "application": value["report"]}
    return value


def runtime(guard, runner=search_stage, max_processes=3):
    return local.ArenaLocalRuntime(guard, RECORD, runner=runner, max_processes=max_processes)


def test_fixture_roundtrip_reservation_and_exact_budget(guard):
    rt = runtime(guard, max_processes=2)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], max_steps=1, max_depth=1)
    assert result["closing_reproduced"] and result["extracted_candidate"] == "exact True.intro"
    assert result["search_steps_reserved"] == result["search_steps_observed"] == 1
    assert result["application_attempts"] == result["roundtrip_attempts"] == 1
    assert result["evidence_mode"] == "fixture" and not result["proof_admitted"]
    assert not result["whole_source_checked"] and rt.reserved == rt.attempts == 2
    exhausted = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"])
    assert exhausted["status"] == "BUDGET_EXHAUSTED" and exhausted["search_steps_reserved"] == 0


@pytest.mark.parametrize("field,value", [("max_steps", 0), ("max_depth", 0), ("max_steps", True),
    ("max_steps", -1), ("max_steps", 257), ("max_depth", 9), ("max_depth", 1.0)])
def test_zero_invalid_limits_before_launch(guard, field, value):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    if type(value) is int and value == 0:
        assert rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], **{field: value})["status"] == "BUDGET_EXHAUSTED"
    else:
        with pytest.raises(ValueError):
            rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], **{field: value})
    assert rt.attempts == rt.reserved == 1


@pytest.mark.parametrize("names", [[], ["True.intro"] * 2, ["True.intro; sorry"], "True.intro",
                                  ["x" + str(i) for i in range(9)]])
def test_bad_names(guard, names):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    with pytest.raises(ValueError): rt.discover_search(PIN, SOURCE, capture, 0, names)
    assert rt.attempts == 1


@pytest.mark.parametrize("damage", ["steps", "bool", "names", "action", "path", "script", "depth",
    "axiom", "receipt", "forged", "roundtrip", "extra", "null", "exhausted"])
def test_forgery_rejected(guard, damage):
    def corrupt(binding, payload):
        value = search_stage(binding, payload)
        if payload["mode"] == "search":
            r = value["report"]
            if damage == "steps": r["attempted_steps"] = 97
            elif damage == "bool": r["max_steps"] = True
            elif damage == "names": r["premises"] = ["evil"]
            elif damage == "action": r["trace"][0]["action"] = "sorry"
            elif damage == "path": r["path"] = ["sorry"]
            elif damage == "script": r["script"] = "exact True.intro"
            elif damage == "depth": r["trace"][0]["depth"] = 4
            elif damage == "axiom": r["application"]["search"]["proposed"]["axioms"] = ["sorryAx"]
            elif damage == "receipt": r["application"]["roundtrip"]["environment"] = "b" * 64
            elif damage == "forged": r["application"]["search"]["proof_admitted"] = True
            elif damage == "roundtrip": r["application"]["roundtrip"]["candidate"] = "exact False.elim h"
            elif damage == "extra": r["verified"] = True
            elif damage == "null": r["application"] = None
            else: r["step_exhausted"] = True
        return value
    rt = runtime(guard, runner=corrupt)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"])
    assert result["status"] == "ERROR" and not result["closing_reproduced"]
    assert result["extracted_candidate"] is None and result["search_steps_reserved"] == 96


@pytest.mark.parametrize("damage", ["pin", "source", "origin", "event"])
def test_stale_search_before_launch(guard, damage):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    pin, source, event = PIN, SOURCE, 0
    if damage == "pin": pin = OTHER
    elif damage == "source": source += "\n"
    elif damage == "origin": capture["origin"]["target"] = "Foreign"
    else: event = True
    with pytest.raises(ValueError): rt.discover_search(pin, source, capture, event, ["True.intro"])
    assert rt.attempts == 1


def test_timeout_unknown_steps_keeps_charge_and_no_draft(guard):
    def timeout(binding, payload):
        if payload["mode"] == "search": raise TimeoutError("fixture timeout")
        return stage(binding, payload)
    rt = runtime(guard, runner=timeout)
    capture = rt.capture(PIN)["capture"]
    env = rt.context.context_id
    index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
    scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
    batch = rt.discover_batch(PIN, capture, index, scope, search="backward-v1", max_applications=1)
    assert batch["status"] == "ERROR" and not batch["drafts"]
    assert batch["search_steps_reserved"] == 96 and batch["search_steps_observed"] == 0
    assert batch["unknown_search_processes"] == 1 and rt.attempts == 2


def test_batch_fixture_and_no_path_abstention(guard):
    def failed(binding, payload):
        value = search_stage(binding, payload)
        if payload["mode"] == "search":
            value["report"].update(path=None, script=None, application=None, depth_cutoffs=1)
        return value
    for runner in (search_stage, failed):
        rt = runtime(guard, runner=runner)
        capture = rt.capture(PIN)["capture"]
        env = rt.context.context_id
        index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
        scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
        batch = rt.discover_batch(PIN, capture, index, scope, search="backward-v1", max_applications=1)
        assert batch["status"] == ("FIXTURE_DRAFTS_ONLY" if runner == search_stage else "ABSTAINED")
        assert len(batch["drafts"]) == int(runner == search_stage)
        assert batch["search_steps_observed"] == 1 and batch["search_steps_reserved"] == 96


def test_matching_span_schedule_and_explicit_fallback():
    capture = capture_fixture()
    large = capture["trace"]["events"][0]
    large["before"]["expressions"][0][1] = name("And")  # no nominated And conclusion
    small = deepcopy(large)
    small.update(id="1", start=str(SOURCE.encode().index(b"have second")))
    small["before"]["expressions"][0][1] = name("True")
    capture["trace"]["events"].append(small)
    rehash(capture)
    index, scope = inventory((Premise("True.intro", "And True", "fixture"),))
    index = PremiseIndex(tuple(index.entries.values()), environment_sha256=index.environment_sha256,
        signatures=(PremiseSignature("True.intro", (), (), ExprHead("const", "True")),))
    runs = [providers.plan_local_applications(PLAN_RECORD, capture, index, scope, span_order=order,
        retrieval="typed-head-v1", search="backward-v1", max_applications=2)
        for order in ("headroom-v1", "matching-head-v1")]
    assert [[a["event_id"] for a in r["applications"]] for r in runs] == [[0, 1], [1, 0]]
    assert runs[0]["request"]["request_sha256"] != runs[1]["request"]["request_sha256"]
    assert runs[1]["events"][0]["span_priority"] == "fallback"
    excluded = replace(scope, excluded_names=("True.intro",))
    assert not providers.plan_local_applications(PLAN_RECORD, capture, index, excluded,
        search="backward-v1")["applications"]
    with pytest.raises(ValueError):
        providers.plan_local_applications(PLAN_RECORD, capture, index, scope, span_order="matching-head-v1")


def test_periodic_fallback_survives_many_preferred_observations():
    # Deliberately synthetic observation spans, not native proof evidence.
    capture = capture_fixture()
    root = capture["trace"]["events"][0]
    for i in range(1, 6):
        child = deepcopy(root)
        child.update(id=str(i), start=str(int(root["start"]) + i))
        capture["trace"]["events"].append(child)
    root["before"]["expressions"][0][1] = name("And")
    rehash(capture)
    index, scope = inventory((Premise("True.intro", "And True", "fixture"),))
    index = PremiseIndex(tuple(index.entries.values()), environment_sha256=index.environment_sha256,
        signatures=(PremiseSignature("True.intro", (), (), ExprHead("const", "True")),))
    def plan():
        return providers.plan_local_applications(PLAN_RECORD, capture, index, scope,
            span_order="matching-head-v1", retrieval="typed-head-v1", search="backward-v1", max_applications=6)
    result = plan()
    assert result == plan()
    ids = [a["event_id"] for a in result["applications"]]
    assert ids[3] == 0 and set(ids) == set(range(6))


@pytest.mark.parametrize("key", ["max_steps", "max_depth"])
def test_zero_plan_no_queries(key, monkeypatch):
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **k: pytest.fail("zero budget queried"))
    result = providers.plan_local_applications(PLAN_RECORD, capture_fixture(), *inventory(),
                                              search="backward-v1", **{key: 0})
    assert result["status"] == "BUDGET_EXHAUSTED"


PREFIX = """inductive P : Prop where | mk
inductive Q : Prop where | mk : P → Q
inductive R : Prop where | mk : Q → R
theorem bad (p : P) (f : False) : R := False.elim f
theorem toR (q : Q) : R := R.mk q
theorem toQ (p : P) : Q := Q.mk p
theorem loop {p : Prop} (h : p) : p := h
"""


@pytest.mark.no_seal(reason="explicit installed native bounded search; no downloads/models")
@pytest.mark.parametrize("case", ["chain", "conjunction", "rollback", "intro", "cycle", "steps", "depth", "axiom"])
def test_native_search(tmp_path, case):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in")
    tag = os.environ.get("JEVOPS_SEARCH_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "bounded-search-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    prefix, statement = PREFIX, "theorem sample (h : P) : R"
    answer, names, steps, depth = "R.mk (Q.mk (id (id h)))", ["toR", "toQ"], 128, 4
    if case == "conjunction":
        statement, answer = "theorem sample (h : P) : R ∧ R", "And.intro (R.mk (Q.mk h)) (R.mk (Q.mk h))"
    elif case == "rollback": names = ["bad", "toR", "toQ"]
    elif case == "intro":
        statement, answer = "theorem sample : P → R", "fun h => R.mk (Q.mk (id h))"
    elif case == "cycle":
        statement, answer, names = "theorem sample (p : Prop) : p ∨ True", "Or.inr True.intro", ["loop"]
        depth = 3
    elif case == "steps": steps = 1
    elif case == "depth": depth = 1
    elif case == "axiom":
        prefix += "axiom forged : R\n"
        names = ["forged"]
    source = statement + " := by\n  exact " + answer + "\n"
    record = {"name": "Suite.sample", "statement": statement, "src": source,
              "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix + "namespace Suite\n", project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(verifier, record, max_processes=3)
    captured = rt.capture(pin)
    assert captured["ok"], captured.get("reason", captured)
    capture = captured["capture"]
    event = next(e for e in capture["trace"]["events"]
                 if source.encode()[int(e["start"]):int(e["end"])].startswith(b"exact "))
    result = rt.discover_search(pin, source, capture, int(event["id"]), names, max_steps=steps, max_depth=depth)
    assert result["ok"], result.get("reason", result)
    positive = case in {"chain", "conjunction", "rollback", "intro"}
    assert result["closing_reproduced"] == positive, result
    assert 0 < result["search_steps_observed"] <= steps
    assert result["search_steps_reserved"] == steps
    assert verifier(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    if positive:
        draft = replace_event(source, event, result["extracted_candidate"])
        assert verifier(VerificationRequest(rt.context, draft, pin)).outcome.value == "VERIFIED"
        path = result["search_report"]["path"]
        assert "apply _root_.toR" in path and "apply _root_.toQ" in path
        if case == "chain":
            assert reference_tokens(draft, statement) < reference_tokens(source, statement)
            direct = rt.discover_application(pin, source, capture, int(event["id"]), "toR")
            assert not direct["closing_reproduced"]
        elif case == "conjunction":
            assert path.count("apply _root_.toR") == 2
        elif case == "rollback":
            assert "apply _root_.bad" not in path
            assert any(t["action"] == "apply _root_.bad" and t["applied"] for t in result["search_report"]["trace"])
    else:
        assert result["extracted_candidate"] is None and not result["roundtrip_attempts"]
    if case == "steps": assert result["search_report"]["step_exhausted"]
    if case == "depth": assert result["search_report"]["depth_cutoffs"] > 0
    assert not result["proof_admitted"] and not result["whole_source_checked"]
