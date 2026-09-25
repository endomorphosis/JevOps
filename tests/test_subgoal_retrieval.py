"""Bounded subgoal reads never override scope or native proof admission."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path

import pytest

from jevops import arena_local as local, arena_lean as native, arena_providers as providers
from jevops.arena import content_hash, VerificationRequest, reference_tokens
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope, subgoal_pool, subgoal_selection
from jevops.proof_replay import replace_event
from tests.test_local_backward_search import search_stage
from tests.test_arena_local import guard, PIN, RECORD, SOURCE
from tests.test_local_premise_replay import capture_fixture, inventory, RECORD as PLAN_RECORD


POOL = [{"name": "True.intro", "head": "True"}]


def dynamic_stage(binding, payload):
    value = search_stage(binding, payload)
    if payload["mode"] == "search":
        r = value["report"]
        r.update(schema="jevops-local-search/v2", subgoal_pool=payload["subgoal_pool"],
            max_retrievals=payload["max_retrievals"], retrieval_top_k=payload["retrieval_top_k"],
            retrievals=[{"id": 0, "head": "True", "depth": 1, "selected": ["True.intro"]}],
            retrieval_exhausted=False)
        # Fixture authority is explicitly false: this only tests protocol shape.
        r["trace"][0].update(retrieval_id=0, depth=1)
    return value


def runtime(guard, runner=dynamic_stage, max_processes=2):
    return local.ArenaLocalRuntime(guard, RECORD, runner=runner, max_processes=max_processes)


def test_fixture_receipt_and_exact_process_retrieval_budgets(guard):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"],
        subgoal_pool=POOL, max_steps=1, max_retrievals=1)
    assert result["ok"] and result["closing_reproduced"]
    assert result["retrievals_reserved"] == result["retrievals_observed"] == 1
    assert result["search_steps_reserved"] == result["search_steps_observed"] == 1
    assert result["evidence_mode"] == "fixture" and not result["proof_admitted"]
    assert result["binding"]["operation"] == "subgoal-backward-materialization/v1"
    exhausted = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL)
    assert exhausted["status"] == "BUDGET_EXHAUSTED" and exhausted["retrievals_reserved"] == 0


@pytest.mark.parametrize("damage", ["pool", "limit", "bool", "topk", "exhausted", "query_id", "depth",
    "head", "selected", "authority", "unrecorded", "unknown_id", "wrong_depth", "unauthorized", "stale"])
def test_bad_retrieval_receipt_never_admitted(guard, damage):
    def corrupt(binding, payload):
        value = dynamic_stage(binding, payload)
        if payload["mode"] == "search":
            r = value["report"]
            query, row = r["retrievals"][0], r["trace"][0]
            if damage == "pool": r["subgoal_pool"] = [{"name": "forged", "head": "True"}]
            elif damage == "limit": r["max_retrievals"] = 9
            elif damage == "bool": r["max_retrievals"] = True
            elif damage == "topk": r["retrieval_top_k"] = 1
            elif damage == "exhausted": r["retrieval_exhausted"] = True
            elif damage == "query_id": query["id"] = 1
            elif damage == "depth": query["depth"] = 0
            elif damage == "head": query["head"] = float("nan")
            elif damage == "selected": query["selected"] = ["foreign"]
            elif damage == "authority": query["verified"] = True
            elif damage == "unrecorded": row["retrieval_id"] = None
            elif damage == "unknown_id": row["retrieval_id"] = 1
            elif damage == "wrong_depth": row["depth"] = 2
            elif damage == "unauthorized": row["action"] = "apply _root_.foreign"
            else: r["application"]["roundtrip"]["environment"] = "a" * 64
        return value
    rt = runtime(guard, runner=corrupt)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL)
    assert result["status"] == "ERROR" and not result["closing_reproduced"]
    assert result["extracted_candidate"] is None and result["retrievals_reserved"] == 32


@pytest.mark.parametrize("pool", [[], POOL * 2, [{"name": "other", "head": None}],
    [{"name": "True.intro", "head": True}], [{"name": "True.intro", "head": "x" * 1025}],
    [{"name": "True.intro; sorry", "head": None}], [{**POOL[0], "verified": True}],
    [{"name": "p" + str(i), "head": None} for i in range(65)]])
def test_invalid_pool_before_launch(guard, pool):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    with pytest.raises(ValueError): rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=pool)
    assert rt.reserved == rt.attempts == 1


@pytest.mark.parametrize("key,value", [("max_retrievals", 0), ("max_retrievals", True),
    ("max_retrievals", -1), ("max_retrievals", 257), ("retrieval_top_k", 0), ("retrieval_top_k", 9)])
def test_zero_invalid_retrieval_limits(guard, key, value):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    if value == 0 and key == "max_retrievals":
        result = rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL, **{key: value})
        assert result["status"] == "BUDGET_EXHAUSTED" and result["retrievals_reserved"] == 0
    else:
        with pytest.raises(ValueError):
            rt.discover_search(PIN, SOURCE, capture, 0, ["True.intro"], subgoal_pool=POOL, **{key: value})
    assert rt.attempts == 1


def test_selection_changed_head_unknown_fallback_and_order():
    pool = subgoal_pool([{"name": n, "head": h} for n, h in
        (("A", "Root"), ("B", "Middle"), ("C", "Middle"), ("D", None))], ["A"])
    assert subgoal_selection(pool, ["A"], "Middle", 1) == ["B"]
    assert subgoal_selection(pool, ["A"], "Middle", 2) == ["B", "A"]
    assert subgoal_selection(pool, ["A"], "Middle", 3) == ["B", "C", "A"]
    assert subgoal_selection(pool, ["C", "A"], "Middle", 3) == ["C", "B", "A"]
    assert subgoal_selection(pool, ["A"], None, 4) == ["A", "B", "C", "D"]
    assert pool == subgoal_pool(list(reversed(pool)), ["A"])


def test_scoped_pool_reuses_all_alias_dependency_split_and_origin_exclusions():
    entries = (Premise("Target", "True", "bench", aliases=("Alias",)),
        Premise("Wrapper", "True", "lib", dependencies=("Alias",)),
        Premise("Heldout", "True", "family", split="canary", aliases=("Hidden",)),
        Premise("WrapHidden", "True", "lib", dependencies=("Hidden",)),
        Premise("Origin", "True", "secret"), Premise("Missing", "True", "lib"),
        Premise("External", "True", "lib", dependencies=("Unknown",)),
        Premise("WrapExternal", "True", "lib", dependencies=("External",)),
        Premise("Good", "True", "lib"))
    index, base = inventory(entries)
    scope = replace(base, available_names=tuple(n for p in entries if p.name != "Missing"
        for n in (p.name, *p.aliases)), excluded_origins=("secret",))
    pool = index.scoped_pool(target="Target", scope=scope)
    assert pool["entries"] == [{"name": "Good", "head": None}]
    assert pool["excluded_count"] == 8 and pool["entries_scanned"] == 9
    assert index.scoped_pool(target="Target", scope=scope, max_pool=0)["status"] == "POOL_BUDGET"
    assert index.rank("True", target="Target", scope=scope)["matches"][0]["name"] == "Good"
    with pytest.raises(ValueError): index.scoped_pool(target="Target", scope=replace(scope, environment_sha256="c" * 64))


def test_planner_pool_limits_identity_and_zero_without_query(monkeypatch):
    index, scope = inventory()
    kwargs = dict(search="subgoal-v1", max_applications=1)
    result = providers.plan_local_applications(PLAN_RECORD, capture_fixture(), index, scope, **kwargs)
    app = result["applications"][0]
    assert app["subgoal_pool"] == [{"name": "True.intro", "head": None}]
    assert app["max_retrievals"] == 32 and app["retrieval_top_k"] == 4
    assert result["request"]["retrieval_reservation_ceiling"] == 32
    changed = providers.plan_local_applications(PLAN_RECORD, capture_fixture(), index, scope, **kwargs, max_retrievals=1)
    assert result["request"]["request_sha256"] != changed["request"]["request_sha256"]
    # Overflow must not return an insertion-order prefix of the pool.
    big, scope = inventory(tuple(Premise("P" + str(i), "True", "fixture") for i in range(65)))
    overflow = providers.plan_local_applications(PLAN_RECORD, capture_fixture(), big, scope, **kwargs)
    assert overflow["status"] == "BUDGET_EXHAUSTED" and not overflow["applications"]
    assert overflow["subgoal_pool"]["entries"] == []
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **k: pytest.fail("zero query"))
    for key in ("max_retrievals", "max_pool"):
        assert providers.plan_local_applications(PLAN_RECORD, capture_fixture(), big, scope,
            **kwargs, **{key: 0})["status"] == "BUDGET_EXHAUSTED"


def test_batch_preserves_budget_on_timeout_and_fixture_drafts(guard):
    def timeout(binding, payload):
        if payload["mode"] == "search": raise TimeoutError("fixture timeout")
        return dynamic_stage(binding, payload)
    for runner in (timeout, dynamic_stage):
        rt = runtime(guard, runner=runner)
        capture = rt.capture(PIN)["capture"]
        env = rt.context.context_id
        index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
        scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
        batch = rt.discover_batch(PIN, capture, index, scope, search="subgoal-v1", max_applications=1)
        assert batch["retrievals_reserved"] == 32
        if runner == timeout:
            assert batch["status"] == "ERROR" and not batch["drafts"]
            assert batch["unknown_search_processes"] == 1 and batch["retrievals_observed"] == 0
        else:
            assert batch["status"] == "FIXTURE_DRAFTS_ONLY" and len(batch["drafts"]) == 1
            assert batch["retrievals_observed"] == 1 and not batch["proof_admitted"]


PREFIX = """def Seed : Prop := True
def Middle : Prop := ¬¬Seed
def Final : Prop := Middle ∧ True
theorem finish (h : Middle) : Final := ⟨h, True.intro⟩
theorem bridge (h : Seed) : Middle := fun hn => hn h
theorem bad (h : Seed) (f : False) : Middle := False.elim f
"""


@pytest.mark.no_seal(reason="explicit native subgoal retrieval controls; installed toolchains only")
@pytest.mark.parametrize("case", ["chain", "conjunction", "rollback", "missing", "wrong_hint", "query_limit", "axiom"])
def test_native_subgoal_search(tmp_path, case):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads/API")
    tag = os.environ.get("JEVOPS_SEARCH_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "subgoal-retrieval-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    prefix, statement = PREFIX, "theorem sample (h : Seed) : Final"
    answer = "And.intro (fun hn => hn (id (id h))) True.intro"
    pool = [{"name": "bridge", "head": "Middle"}, {"name": "finish", "head": "Final"}]
    steps, depth, queries, topk = 128, 4, 32, 1
    if case == "conjunction":
        statement = "theorem sample (h : Seed) : Final ∧ Final"
        answer = "And.intro (finish (bridge (id h))) (finish (bridge (id h)))"
        depth = 5
    elif case == "rollback":
        pool.append({"name": "bad", "head": "Middle"}); topk = 3
    elif case == "missing": pool = pool[1:]
    elif case == "wrong_hint": pool[0]["head"] = "Other"
    elif case == "query_limit": queries = 1
    elif case == "axiom":
        prefix += "axiom forged : Middle\n"
        pool = [{"name": "finish", "head": "Final"}, {"name": "forged", "head": "Middle"}]
    if case == "chain": queries = 2  # exact success boundary, no extra query allowance
    source = statement + " := by\n  exact " + answer + "\n"
    record = {"name": "Suite.sample", "statement": statement, "src": source, "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix + "namespace Suite\n", project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=3)
    captured = rt.capture(pin)
    assert captured["ok"], captured.get("reason", captured)
    capture = captured["capture"]
    event = next(e for e in capture["trace"]["events"]
        if source.encode()[int(e["start"]):int(e["end"])].startswith(b"exact "))
    result = rt.discover_search(pin, source, capture, int(event["id"]), ["finish"],
        subgoal_pool=pool, max_retrievals=queries, retrieval_top_k=topk, max_depth=depth, max_steps=steps)
    assert result["ok"], result.get("reason", result)
    positive = case in {"chain", "conjunction", "rollback"}
    assert result["closing_reproduced"] == positive, result
    assert 0 < result["retrievals_observed"] <= queries
    assert result["retrievals_reserved"] == queries and not result["proof_admitted"]
    assert guard(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    if positive:
        draft = replace_event(source, event, result["extracted_candidate"])
        assert guard(VerificationRequest(rt.context, draft, pin)).outcome.value == "VERIFIED"
        assert "apply _root_.bridge" in result["search_report"]["path"]
        if case == "chain":
            assert result["retrievals_observed"] == 2
            assert reference_tokens(draft, statement) < reference_tokens(source, statement)
            fixed = rt.discover_search(pin, source, capture, int(event["id"]), ["finish"], max_steps=steps, max_depth=depth)
            assert fixed["ok"] and not fixed["closing_reproduced"]
        if case == "rollback":
            assert any(t["action"] == "apply _root_.bad" and t["applied"] for t in result["search_report"]["trace"])
            assert "apply _root_.bad" not in result["search_report"]["path"]
    if case == "query_limit":
        assert result["search_report"]["retrieval_exhausted"] and result["retrievals_observed"] == 1
