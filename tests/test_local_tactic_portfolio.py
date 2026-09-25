"""Untrusted offline proposal controls and explicitly opt-in installed Lean checks."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path

import pytest

from jevops import arena_providers as providers, arena_lean as native, arena_local as local
from jevops.arena import VerificationRequest, content_hash
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from tests.test_local_premise_replay import RECORD, SOURCE, BLOCK, capture_fixture, inventory, rehash, name


def portfolio(capture=None, **kwargs):
    return providers.propose_local_batch(RECORD, capture if capture is not None else capture_fixture(),
        *inventory(), strategy="portfolio-v1", **kwargs)


def test_small_budget_reaches_application_without_changing_baseline():
    index, scope = inventory((Premise("A.proof", "True", "fixture"), Premise("B.proof", "True", "fixture")))
    baseline = providers.propose_local_batch(RECORD, capture_fixture(), index, scope, cap=2)
    assert [p["candidate"] for p in baseline["proposals"]] == ["exact _root_.A.proof", "exact _root_.B.proof"]
    result = providers.propose_local_batch(RECORD, capture_fixture(), index, scope, cap=2, strategy="portfolio-v1")
    assert [p["candidate"] for p in result["proposals"]] == [
        "solve | apply _root_.A.proof <;> assumption", "exact _root_.A.proof"]
    assert result["attempted_templates"] == 2
    assert result["family_drafts"] == {"apply_assumption": 1, "exact": 1, "local_term": 0, "close": 0}
    assert result["truncated"] and result["fresh_verification_required"]
    assert not any(result[k] for k in ("proof_verified", "proof_admitted", "whole_source_checked",
        "training_enabled", "promoted", "native_verifier_calls", "external_calls_attempted"))


def test_goal_and_family_rotation_deduplication_and_stability():
    source = SOURCE.replace("exact True.intro\n", BLOCK + "\n")
    record = {**RECORD, "src": source}
    capture = capture_fixture(source)
    event = capture["trace"]["events"][0]
    start = source.encode().rindex(BLOCK.encode())
    capture["trace"]["events"].append({**deepcopy(event), "id": "1", "start": str(start),
        "end": str(start + len(BLOCK.encode()))})
    rehash(capture)
    saved = deepcopy(capture)
    def run():
        return providers.propose_local_batch(record, capture, *inventory(record=record), strategy="portfolio-v1", cap=2)
    result = run()
    assert result == run() and capture == saved
    assert [(o["event_id"], o["family"]) for o in result["origins"]] == [(0, "apply_assumption"), (1, "exact")]
    duplicate = capture_fixture()
    duplicate["trace"]["events"].append({**deepcopy(duplicate["trace"]["events"][0]), "id": "1"})
    result = portfolio(rehash(duplicate), cap=8)
    assert len({d["source"] for d in result["drafts"]}) == len(result["drafts"])
    assert any(o["status"] == "DUPLICATE" for e in result["events"] for o in e["outcomes"])


@pytest.mark.parametrize("field", ["cap", "max_events", "max_query_nodes", "max_templates"])
def test_zero_is_exhausted_before_work(field, monkeypatch):
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **kw: pytest.fail("exhausted budget queried inventory"))
    result = portfolio(**{field: 0})
    assert result["status"] == "BUDGET_EXHAUSTED" and result["attempted_templates"] == 0
    assert not result["drafts"]


@pytest.mark.parametrize("budget", [-1, True, 513, 1.0])
def test_invalid_template_budgets(budget):
    with pytest.raises(ValueError): portfolio(max_templates=budget)


def test_exact_template_boundary_and_request_identity():
    one, two = portfolio(max_templates=1), portfolio(max_templates=2)
    assert one["attempted_templates"] == len(one["drafts"]) == 1
    assert two["attempted_templates"] == len(two["drafts"]) == 2
    assert one["request"]["request_sha256"] != two["request"]["request_sha256"]
    assert one["request"]["local_search"]["max_checks"] == 2048
    with pytest.raises(ValueError, match="strategy"):
        providers.propose_local_batch(RECORD, capture_fixture(), *inventory(), strategy="unknown")


def test_exclusion_and_scan_limits_do_not_disable_nonlibrary_families():
    index, scope = inventory()
    result = providers.propose_local_batch(RECORD, capture_fixture(), index,
        replace(scope, excluded_names=("True.intro",)), strategy="portfolio-v1")
    assert result["drafts"] and all(o["premise"] is None for o in result["origins"])
    index, scope = inventory((Premise("A.proof", "True", "fixture"), Premise("B.proof", "True", "fixture")))
    result = providers.propose_local_batch(RECORD, capture_fixture(), index, scope, strategy="portfolio-v1", max_scan=1)
    assert result["events"][0]["status"] == "SCAN_BUDGET" and result["truncated"]
    assert all(o["premise"] is None for o in result["origins"])


def test_no_constants_still_uses_typed_local_terms(monkeypatch):
    capture = capture_fixture()
    before = capture["trace"]["events"][0]["before"]
    before["levels"] = [["zero"]]
    before["expressions"] = [["sort", "0"], ["fvar", name("p")]]
    goal = before["metavariables"][0]
    goal["type"] = "1"
    goal["locals"] = [{"id": name(n), "name": name(n), "index": str(i), "type": str(i),
        "value": None, "nondep": False, "binder": "explicit", "kind": "default"} for i, n in enumerate(("p", "h"))]
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **kw: pytest.fail("no-constant state queried inventory"))
    result = portfolio(rehash(capture), cap=1)
    assert result["events"][0]["status"] == "NO_CONSTANTS"
    assert result["proposals"][0]["candidate"] == "exact h"
    assert result["origins"][0]["family"] == "local_term"
    assert result["events"][0]["local_search"]["checks"] <= 2048


@pytest.mark.no_seal(reason="explicit installed Lean portfolio control; no downloads or models")
@pytest.mark.parametrize("case", ["arguments", "missing_premise", "forbidden_axiom"])
def test_native_guarded_application_and_unchanged_admission(tmp_path, case):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit opt-in; already installed toolchains only")
    tag = os.environ.get("JEVOPS_PORTFOLIO_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "local-portfolio-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    prefix = ("axiom library_step {p : Prop} : p ∨ True\n" if case == "forbidden_axiom" else
        "theorem library_step {p : Prop} (h : p) : p ∨ True := Or.inl h\n")
    prefix += "theorem library_step_alt {p : Prop} (h : p) : p ∨ True := Or.inl h\nnamespace Suite\n"
    statement = "theorem sample (p : Prop)" + (" (h : p)" if case == "arguments" else "") + " : p ∨ True"
    answer = "Or.inl (id (id (id (id h))))" if case == "arguments" else "Or.inr (id (id (id (id True.intro))))"
    source = statement + " := by\n  exact " + answer + "\n"
    record = {"name": "Suite.sample", "statement": statement, "src": source,
        "version_info": [{pin.lean_tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix, project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=5, timeout=60)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=5)
    observed = rt.capture(pin)
    assert observed["ok"], observed
    capture = observed["capture"]
    env = guard.context(record).context_id
    index = PremiseIndex(tuple(Premise(n, "Or True", "fixture-nominee-not-type-certification")
        for n in ("library_step", "library_step_alt")), environment_sha256=env)
    scope = PremiseScope(content_hash(record), env, tuple(index.entries))
    baseline, balanced = [providers.propose_local_batch(record, capture, index, scope, cap=2,
        strategy=strategy) for strategy in providers.LOCAL_STRATEGIES]
    assert len(baseline["drafts"]) == len(balanced["drafts"]) == 2
    assert balanced["origins"][0]["family"] == "apply_assumption"
    assert balanced["origins"][0]["premise"]["name"] == "library_step"
    assert guard(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    results = []
    for batch in (baseline, balanced):
        outcomes = []
        for proposal, draft in zip(batch["proposals"], batch["drafts"]):
            replayed = rt.replay(pin, source, capture, **proposal)
            receipt = guard(VerificationRequest(rt.context, draft["source"], pin))
            outcomes.append((replayed["closing_reproduced"], receipt.outcome.value))
            assert not replayed["proof_admitted"] and not replayed["whole_source_checked"]
        results.append(outcomes)
    assert results[0] == [(False, "REJECTED"), (False, "REJECTED")], results
    assert results[1][0] == ((True, "VERIFIED") if case == "arguments" else (False, "REJECTED")), results
    assert results[1][1] == (False, "REJECTED"), results
    assert guard.processes == rt.attempts == 5
