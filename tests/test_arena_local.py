"""Project context boundary: fixtures and explicitly opt-in native checks."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

from jevops import arena_lean as native, arena_local as local, proof_replay as replay
from jevops.arena import VerificationRequest, content_hash
from jevops.arena_providers import propose_local_batch
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from tests.test_local_premise_replay import RECORD, SOURCE, capture_fixture, name

PIN = VersionPin("v4.26.0", "project-local-control")
OTHER = VersionPin("v4.34.0", "project-local-control")
RECORD = {**RECORD, "version_info": [{p.lean_tag: p.git_commit} for p in (PIN, OTHER)]}
PREFIX = "theorem prefixProof : True := by trivial\nnamespace Suite\nsection\n"


@pytest.fixture
def guard(tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda s, _: content_hash(s.prefix))
    bindings = {p: native.ProjectBinding(p, tmp_path / "lean", tmp_path, PREFIX, project_backed=False)
                for p in (PIN, OTHER)}
    return native.NativeLeanVerifier(bindings, max_processes=0)


def stage(binding, payload):
    trace = capture_fixture()["trace"]
    trace.update(environment=payload["environment"], lean_version=binding.pin.lean_tag[1:], lean_githash="a" * 40)
    event = trace["events"][0]
    event.update(declaration=name(RECORD["name"]), namespace=name("Suite"))
    report = trace
    if payload["mode"] == "replay":
        closed = {"status": "closed_kernel_checked", "closed_goals_checked": "1", "remaining_goals": "0", "axioms": []}
        report = {"schema": replay.SCHEMA, "environment": payload["environment"],
            "lean_version": trace["lean_version"], "lean_githash": trace["lean_githash"],
            "event": event, "candidate": payload["candidate"], "baseline": closed, "proposed": closed,
            "proof_admitted": False, "snapshot_decoded": False, "whole_source_checked": False}
    return {"schema": local.STAGE_SCHEMA, "request_sha256": payload["request_sha256"],
        "target": payload["target"], "lean_version": report["lean_version"],
        "lean_githash": report["lean_githash"], "report": report}


def runtime(guard, **kwargs):
    return local.ArenaLocalRuntime(guard, RECORD, runner=stage, **kwargs)


def proposals(guard, capture):
    env = guard.context(RECORD).context_id
    index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
    scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
    return propose_local_batch(RECORD, capture, index, scope)


def test_zero_exact_budget_fixture_identity_and_replay(guard):
    zero = runtime(guard)
    assert zero.capture(PIN)["status"] == "BUDGET_EXHAUSTED" and zero.attempts == 0
    rt = runtime(guard, max_processes=2)
    observed = rt.capture(PIN)
    assert observed["status"] == "FIXTURE_ONLY" and observed["evidence_mode"] == "fixture"
    capture = observed["capture"]
    assert capture["origin"]["pin"] == PIN.to_dict()
    assert capture["origin"]["projection"] == local.PROJECTION
    proposal = proposals(guard, capture)["proposals"][0]
    outcome = rt.replay(PIN, SOURCE, capture, **proposal)
    assert outcome["ok"] and outcome["closing_reproduced"] and not outcome["proof_admitted"]
    assert not outcome["whole_source_checked"] and guard.processes == 0
    assert rt.reserved == rt.attempts == 2
    assert rt.capture(PIN)["status"] == "BUDGET_EXHAUSTED" and rt.attempts == 2


def test_project_capture_cannot_use_ambient_replay(guard, tmp_path):
    capture = runtime(guard, max_processes=1).capture(PIN)["capture"]
    with pytest.raises(ValueError, match="explicit Arena"):
        replay.replay_candidate(SOURCE, capture, 0, "trivial", project_root=tmp_path,
                                environment_sha256=guard.context(RECORD).context_id)


@pytest.mark.parametrize("damage", ["prefix", "pin", "source", "origin", "event", "flag", "implementation"])
def test_stale_inputs_rejected_before_replay_launch(guard, monkeypatch, damage):
    rt = runtime(guard, max_processes=2)
    capture = rt.capture(PIN)["capture"]
    source, pin, event = SOURCE, PIN, 0
    if damage == "prefix": guard.bindings[PIN] = replace(guard.bindings[PIN], prefix=PREFIX + "\n")
    elif damage == "pin": pin = OTHER
    elif damage == "source": source += "\n"
    elif damage == "origin": capture["origin"]["target"] = "Other.goal"
    elif damage == "event": event = True
    elif damage == "flag": capture["proof_admitted"] = True
    else: monkeypatch.setattr(local, "_identity", lambda: "changed")
    with pytest.raises(ValueError): rt.replay(pin, source, capture, event, "trivial")
    assert rt.attempts == 1


@pytest.mark.parametrize("damage", ["request", "target", "version", "declaration", "offset", "number", "errors", "report", "open_event", "duplicate_span"])
def test_invalid_native_capture_cannot_become_usable(guard, damage):
    def corrupt(binding, payload):
        value = stage(binding, payload)
        report = value["report"]
        if damage == "request": value["request_sha256"] = "b" * 64
        elif damage == "target": value["target"] = "Other"
        elif damage == "version": value["lean_version"] = "0"
        elif damage == "declaration": report["events"][0]["declaration"] = name("prefixProof")
        elif damage == "offset": report["events"][0]["end"] = str(len(SOURCE.encode()) + 1)
        elif damage == "number": report["events"][0]["start"] = 0
        elif damage == "errors": report["elaboration_errors"] = True
        elif damage == "open_event": report["events"][0]["after"] = report["events"][0]["before"]
        elif damage == "duplicate_span": report["events"].append({**report["events"][0], "id": "1"})
        else: value["report"] = None
        return value
    rt = local.ArenaLocalRuntime(guard, RECORD, max_processes=1, runner=corrupt)
    result = rt.capture(PIN)
    assert not result["ok"] and result["status"] == "ERROR" and "capture" not in result


def test_transient_failure_is_not_a_semantic_negative_or_refunded(guard):
    def unavailable(*a): raise TimeoutError("fixture transport timeout")
    rt = local.ArenaLocalRuntime(guard, RECORD, max_processes=1, runner=unavailable)
    result = rt.capture(PIN)
    assert result["status"] == "ERROR" and result["attempted_processes"] == 1
    assert not result["proof_admitted"] and rt.capture(PIN)["status"] == "BUDGET_EXHAUSTED"


def test_wrong_replay_receipt_cannot_close_an_event(guard):
    def corrupt(binding, payload):
        value = stage(binding, payload)
        if payload["mode"] == "replay": value["report"]["candidate"] = "sorry"
        return value
    rt = local.ArenaLocalRuntime(guard, RECORD, max_processes=2, runner=corrupt)
    capture = rt.capture(PIN)["capture"]
    outcome = rt.replay(PIN, SOURCE, capture, 0, "trivial")
    assert not outcome["ok"] and not outcome["closing_reproduced"]


@pytest.mark.no_seal(reason="explicit project-context Lean control")
@pytest.mark.parametrize("pin", [PIN, OTHER])
def test_native_project_prefix_target_offsets_replay_and_whole_proof(tmp_path, pin):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit opt-in; already installed toolchains only")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), pin.lean_tag)
    record = {**RECORD, "version_info": [{pin.lean_tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, PREFIX, project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=2)
    observed = rt.capture(pin)
    assert observed["ok"], observed.get("reason")
    capture = observed["capture"]
    assert all(e["declaration"] == name(record["name"]) for e in capture["trace"]["events"])
    events = capture["trace"]["events"]
    assert len({(e["start"], e["end"]) for e in events}) == len(events)
    assert all(len(e["before"]["goals"]) == 1 and not e["after"]["goals"] for e in events)
    env = guard.context(record).context_id
    index = PremiseIndex((Premise("True.intro", "True", "library"),), environment_sha256=env)
    scope = PremiseScope(content_hash(record), env, ("True.intro",))
    batch = propose_local_batch(record, capture, index, scope, cap=1)
    assert batch["proposals"]
    outcome = rt.replay(pin, SOURCE, capture, **batch["proposals"][0])
    assert outcome["closing_reproduced"], outcome
    for source in (SOURCE, batch["drafts"][0]["source"]):
        receipt = guard(VerificationRequest(rt.context, source, pin))
        assert receipt.outcome.value == "VERIFIED", receipt
    assert not outcome["proof_admitted"] and not outcome["whole_source_checked"]


@pytest.mark.no_seal(reason="native InfoTree branch headers versus editable tactics")
@pytest.mark.parametrize("pin", [PIN, OTHER])
def test_native_branch_headers_are_observable_but_not_editable(tmp_path, pin):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit opt-in; already installed toolchains only")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), pin.lean_tag)
    statement = "theorem branches (p q : Prop) (h : p ∨ q) : q ∨ p"
    source = statement + " := by\n  cases h\n  next hp => exact Or.inr hp\n  next hq => exact Or.inl hq\n"
    record = {"name": "Suite.branches", "statement": statement, "src": source,
        "version_info": [{pin.lean_tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, PREFIX, project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=0, timeout=60)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=2)
    observed = rt.capture(pin)
    assert observed["ok"], observed
    capture = observed["capture"]
    events = capture["trace"]["events"]
    headers = [e for e in events if e["syntax_kind"] == name("null")]
    assert headers, events
    for header in headers:
        assert header["status"] == "captured"
        with pytest.raises(ValueError, match="synthetic branch header"):
            rt.replay(pin, source, capture, int(header["id"]), "assumption")
    assert rt.attempts == rt.reserved == 1
    body = next(e for e in events if source.encode()[int(e["start"]):int(e["end"])] == b"exact Or.inr hp")
    outcome = rt.replay(pin, source, capture, int(body["id"]), "exact Or.inr hp")
    assert outcome["closing_reproduced"], outcome
    assert not outcome["proof_admitted"] and not outcome["whole_source_checked"]
