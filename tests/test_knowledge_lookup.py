"""Uncached controls for goal-only library reuse, not learned compression."""
from dataclasses import replace
import copy
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

pytest.importorskip("duckdb")
from jevops import arena_lean as native
from jevops.arena import content_hash
from jevops.arena_trial import ORDERS
from jevops.knowledge_index import KnowledgeIndex, build_index
from jevops.knowledge_lookup import (POLICIES, confirmation_plan, confirm_lookup, goal_query,
                                     lookup_plan, render_summary, run_lookup)
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseScope

pytestmark = pytest.mark.no_seal(reason="fresh DuckDB and goal-only lookup boundaries")
STATEMENT = "theorem sample (p q : Prop) : p ∧ q ↔ q ∧ p"
SOURCE = STATEMENT + " := by constructor <;> intro h <;> exact ⟨h.2, h.1⟩\n"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("lookup fixture deps"))
    pins = tuple(VersionPin(tag, "fixture") for tag in ("fixture-a", "fixture-b"))
    bindings = {p: native.ProjectBinding(p, tmp_path / "lean", tmp_path, "", project_backed=False) for p in pins}
    def guard(max_calls=64, **kwargs):
        return native.NativeLeanVerifier(bindings, max_processes=max_calls, **kwargs)
    record = dict(name="sample", statement=STATEMENT, src=SOURCE,
                  version_info=[{p.lean_tag: p.git_commit} for p in pins])
    context = guard().context(record)
    rows = (Premise("A_wrong", "Nat", "lib"), Premise("Z_good", "p ∧ q ↔ q ∧ p", "lib"))
    scope = PremiseScope(content_hash(record), context.context_id, tuple(r.name for r in rows))
    artifact = build_index(tmp_path / "lookup.duckdb", rows, environment_sha256=context.context_id,
                           source_sha256=content_hash("fixture"))
    calls, behavior = [], {}
    def runner(binding, payload, **kwargs):
        calls.append((binding.pin, payload))
        source = payload["candidate"]
        name = "control" if source == payload["reference"] else re.search(r"_root_\.([^\s]+)", source)[1]
        method = "apply-assumption" if "<;> assumption" in source else "bare"
        key = method + ":" + name
        outcome = behavior.get((binding.pin, key), behavior.get(key, behavior.get((binding.pin, name),
            behavior.get(name, "VERIFIED" if name in {"Z_good", "control"} else "REJECTED"))))
        raw = 9000 if name == "control" else 3000
        report = dict(outcome=outcome, type_preserved=True, target_absent_before=True,
            axioms=[], reference_axioms=[], raw_heartbeats=raw, heartbeats=raw // 1000,
            reference_raw_heartbeats=9000, reference_heartbeats=9, diagnostics=[])
        return dict(schema="jevops-native-arena/v1", request_id=payload["request_id"], target=payload["target"],
            measurement=native.METHOD, lean_version=binding.pin.lean_tag.removeprefix("v"), lean_githash="b" * 40,
            branch_order="candidate-first" if payload["candidate_first"] else "reference-first", report=report), 0
    monkeypatch.setattr(native, "run_native", runner)
    def verifiers(**kwargs):
        return {(p, order): native.NativeLeanVerifier({p: b}, max_processes=6, branch_order=order, **kwargs)
                for p, b in bindings.items() for order in ORDERS}
    with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        yield SimpleNamespace(inputs=dict(record=record, index=index, scope=scope, context=context),
                              guard=guard, verifiers=verifiers, calls=calls, behavior=behavior, rows=rows)


def discover(s, plan=None, **kwargs):
    plan = lookup_plan(**s.inputs) if plan is None else plan
    return run_lookup(plan, index=s.inputs["index"], scope=s.inputs["scope"], guard=s.guard(),
        max_calls=plan["max_calls"], evidence_mode="offline_fixture", **kwargs)


def confirm(s, discovery):
    plan = confirmation_plan(discovery)
    return confirm_lookup(plan, discovery, verifiers=s.verifiers(), max_calls=plan["planned_requests"])


@pytest.mark.parametrize("mode", ["bare", "bare-then-apply"])
def test_query_uses_only_signature_not_name_comments_or_reference(setup, tmp_path, mode):
    s = setup
    expected = "(p q : Prop) : p ∧ q ↔ q ∧ p"
    assert goal_query(STATEMENT) == expected
    assert goal_query(STATEMENT.replace("sample", "Z_good")) == expected
    assert goal_query("/- answer Z_good -/" + STATEMENT) == expected
    plan = lookup_plan(**s.inputs, application_mode=mode)
    assert plan["query"] == expected and "Z_good" not in plan["query"]
    record = {**s.inputs["record"], "src": STATEMENT + " := by exact Z_good\n"}
    context = s.guard().context(record)
    sc = replace(s.inputs["scope"], record_sha256=content_hash(record), environment_sha256=context.context_id)
    # Rebuild solely because environment identity includes the reference. The
    # search order must remain independent of that changed reference body.
    artifact = build_index(tmp_path / "changed.duckdb", s.rows,
        environment_sha256=context.context_id, source_sha256=content_hash("fixture"))
    with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        other = lookup_plan(record=record, index=index, scope=sc, context=context, application_mode=mode)
    assert plan["query"] == other["query"] and plan["candidates"] == other["candidates"]
    assert not s.calls


def test_query_keeps_inner_let_assignments():
    statement = "theorem example1 (n : Nat) : (let x := n; x) = n"
    assert goal_query(statement) == "(n : Nat) : (let x := n; x) = n"


@pytest.mark.parametrize("text", ["", "theorem sample", "def sample : True", "example : True", "theorem sample : sorry", "x" * 17000])
def test_bad_envelopes_fail_closed(text):
    with pytest.raises(ValueError):
        goal_query(text)


def test_discovery_is_first_all_pin_valid_not_shortest_heartbeat_selection(setup):
    s = setup
    plan = lookup_plan(**s.inputs)
    assert plan["max_calls"] == 6 and plan["per_policy_call_ceiling"] == 128
    assert [r["name"] for r in plan["candidates"]["direct-scan"]] == ["A_wrong", "Z_good"]
    assert plan["candidates"]["bm25"][0]["name"] == "Z_good"
    report = discover(s)
    assert report["status"] == "COMPLETE" and report["calls"] == len(s.calls) == 6
    assert report["native_processes"] == 0 and report["receipt_cache_hits"] == 0
    assert all(r["status"] == "FOUND" and not r["proof_verified"] for r in report["policies"].values())
    assert report["policies"]["direct-scan"]["checked_candidates"] == 2
    assert report["policies"]["bm25"]["checked_candidates"] == 1
    assert report["official_score"] is None and not report["training_enabled"]


@pytest.mark.parametrize("outcome", ["REJECTED", "TIMEOUT", "ERROR", "UNAVAILABLE"])
def test_any_pin_failure_prevents_found_and_resource_gaps_are_not_counterexamples(setup, outcome):
    s = setup
    s.behavior[(s.inputs["context"].versions[-1], "Z_good")] = outcome
    report = discover(s)
    assert all(r["candidate"] is None and not r["proof_verified"] for r in report["policies"].values())
    assert report["status"] == ("COMPLETE" if outcome == "REJECTED" else "INCOMPLETE")
    if outcome != "REJECTED":
        assert all(r["status"] == "INCOMPLETE" for r in report["policies"].values())


@pytest.mark.parametrize("damage", ["source", "query", "scope", "top_k", "context", "budget", "reused_guard"])
def test_plan_changes_fail_before_any_compiler_work(setup, damage):
    s = setup
    plan = copy.deepcopy(lookup_plan(**s.inputs))
    scope, guard, budget = s.inputs["scope"], s.guard(), plan["max_calls"]
    if damage == "source": plan["candidates"]["bm25"][0]["source"] += " "
    elif damage == "query": plan["query"] = "Z_good"
    elif damage == "scope": scope = replace(scope, excluded_names=("Z_good",))
    elif damage == "top_k": plan["top_k"] = 1
    elif damage == "context": guard = s.guard(timeout=61)
    elif damage == "budget": budget = 0
    else: guard.processes = 1
    with pytest.raises(ValueError):
        run_lookup(plan, index=s.inputs["index"], scope=scope, guard=guard, max_calls=budget)
    assert not s.calls


def test_record_scope_mismatch_fail_closed(setup):
    with pytest.raises(ValueError, match="record/context/scope"):
        lookup_plan(**{**setup.inputs, "scope": replace(setup.inputs["scope"], record_sha256="f" * 64)})


@pytest.mark.parametrize("mode", ["bare", "bare-then-apply"])
def test_exclusions_are_identical_for_both_policies(setup, tmp_path, mode):
    s = setup
    rows = (*s.rows, Premise("sample", "p q ∧ ↔", "lib", aliases=("Alias",)),
        Premise("Wrapper", "p q ∧ ↔", "lib", dependencies=("Alias",)),
        Premise("Protected", "p q ∧ ↔", "protected"),
        Premise("ProtectedWrapper", "p q ∧ ↔", "lib", dependencies=("Protected",)),
        Premise("MissingDependency", "p q ∧ ↔", "lib", dependencies=("Missing",)))
    scope = replace(s.inputs["scope"], available_names=tuple(r.name for r in rows) + ("Alias",),
                    excluded_origins=("protected",))
    artifact = build_index(tmp_path / "exclusions.duckdb", rows,
        environment_sha256=scope.environment_sha256, source_sha256=content_hash("excluded"))
    with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        plan = lookup_plan(**{**s.inputs, "scope": scope, "index": index}, application_mode=mode)
    assert plan["pool"]["excluded_count"] == 5
    assert {r["name"] for r in plan["pool"]["entries"]} == {"A_wrong", "Z_good"}
    assert all({r["name"] for r in plan["candidates"][p]} <= {"A_wrong", "Z_good"} for p in POLICIES)


def test_no_silent_full_inventory_truncation(setup, tmp_path):
    s = setup
    rows = [Premise(f"P{i}", "Prop", "lib") for i in range(65)]
    artifact = build_index(tmp_path / "oversized.duckdb", rows,
        environment_sha256=s.inputs["context"].context_id, source_sha256=content_hash("large"))
    with KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        with pytest.raises(ValueError, match="full inventory"):
            lookup_plan(**{**s.inputs, "index": index})
    assert not s.calls


def test_declared_candidate_cap_is_not_a_no_match_certificate(setup):
    s = setup
    report = discover(s, lookup_plan(**s.inputs, max_candidates=1))
    row = report["policies"]["direct-scan"]
    assert row["status"] == "NO_DIRECT_MATCH_IN_SEARCHED_SET"
    assert not row["whole_pool_exhausted"] and not row["semantic_equivalence_decided"]


def test_query_resource_failures_are_incomplete_not_negative_evidence(setup, monkeypatch):
    s = setup
    original = s.inputs["index"].search
    def timeout(*args, **kwargs):
        return {**original(*args, **kwargs), "status": "QUERY_TIMEOUT", "matches": []}
    monkeypatch.setattr(s.inputs["index"], "search", timeout)
    report = discover(s)
    assert report["status"] == "INCOMPLETE"
    assert report["policies"]["bm25"]["status"] == "QUERY_TIMEOUT"


def test_confirmation_is_fresh_balanced_and_json_roundtrip_stable(setup):
    s = setup
    report = discover(s, json.loads(json.dumps(lookup_plan(**s.inputs), sort_keys=True)))
    report = json.loads(json.dumps(report, sort_keys=True))
    trial = confirm(s, report)
    assert len(s.calls) == 30 and trial["measurement"]["verifier_invocations"] == 24
    c = trial["comparison"]
    assert c["reference_tokens"] == c["candidate_tokens"] == 1 and c["identical_sources"]
    assert not c["native_pair_verified"] and c["observed_pareto_improvement"] is None
    assert trial["measurement"]["native_processes"] == 0 and not trial["training_enabled"]
    assert "Not a blind benchmark" in render_summary(report, trial)


def test_abstention_and_bad_original_controls_never_become_wins(setup):
    s = setup
    s.behavior["Z_good"] = "REJECTED"
    report = discover(s)
    s.behavior["control"] = "REJECTED"
    trial = confirm(s, report)
    c = trial["comparison"]
    assert c["status"] == "INCOMPLETE" and not c["native_pair_verified"]
    assert c["observed_pareto_improvement"] is None
    assert all(a["source"] == SOURCE for a in trial["measurement"]["arms"])


@pytest.mark.parametrize("failed_arm", [None, "control", "Z_good"])
def test_simulated_native_protocol_requires_every_confirmation_arm(setup, failed_arm):
    """Exercise the eligibility branch using a MOCK native protocol.

    These synthetic labels are unit-test inputs, never saved as Lean evidence.
    In particular, a failed control must block eligibility independently of
    the separate offline-fixture exclusion.
    """
    s = setup
    report = discover(s)
    report["evidence_mode"] = "local_lean"
    for row in report["policies"].values():
        row["proof_verified"] = True
    report["report_sha256"] = content_hash({k: v for k, v in report.items() if k != "report_sha256"})
    if failed_arm is not None:
        s.behavior[failed_arm] = "REJECTED"
    comparison = confirm(s, report)["comparison"]
    assert comparison["native_pair_verified"] is (failed_arm is None)
    if failed_arm is not None:
        assert comparison["status"] == "INCOMPLETE" and comparison["observed_pareto_improvement"] is None
    else:
        assert comparison["heartbeat_result"] == "NO_CLEAR_DIFFERENCE"
        assert comparison["observed_pareto_improvement"] is False


@pytest.mark.parametrize("damage", ["receipt", "plan", "budget", "missing_pin", "options", "reused_guard"])
def test_confirmation_fail_closed_without_more_work(setup, damage):
    s = setup
    report = discover(s)
    plan, verifiers = confirmation_plan(report), s.verifiers()
    budget = plan["planned_requests"]
    if damage == "receipt": report["policies"]["bm25"]["candidate"] += " "
    elif damage == "plan": plan["arms"][1]["source"] += " "
    elif damage == "budget": budget -= 1
    elif damage == "missing_pin": verifiers.pop(next(iter(verifiers)))
    elif damage == "options": verifiers = s.verifiers(timeout=61)
    else: next(iter(verifiers.values())).processes = 1
    before = len(s.calls)
    with pytest.raises(ValueError):
        confirm_lookup(plan, report, verifiers=verifiers, max_calls=budget)
    assert len(s.calls) == before


@pytest.mark.parametrize("mode", ["apply", "simp", "", None, True, []])
def test_application_mode_allowlist_fails_before_retrieval(setup, monkeypatch, mode):
    monkeypatch.setattr(setup.inputs["index"], "search", lambda *a, **k: pytest.fail("invalid mode queried"))
    with pytest.raises(ValueError, match="application mode"):
        lookup_plan(**setup.inputs, application_mode=mode)
    assert not setup.calls


def test_bare_default_preserved_and_recipe_budget_explicit(setup):
    s = setup
    bare = lookup_plan(**s.inputs)
    plan = lookup_plan(**s.inputs, application_mode="bare-then-apply")
    assert bare["templates_per_declaration"] == 1 and plan["templates_per_declaration"] == 2
    assert plan["query"] == bare["query"] and plan["pool"] == bare["pool"]
    assert plan["max_calls"] == 2 * bare["max_calls"] == 12
    assert plan["per_policy_call_ceiling"] == 2 * bare["per_policy_call_ceiling"]
    assert [r["method"] for r in plan["candidates"]["direct-scan"]] == ["bare", "bare", "apply-assumption", "apply-assumption"]
    for label in POLICIES:
        assert plan["candidates"][label][:len(bare["candidates"][label])] == bare["candidates"][label]
    assert not plan["composition_claimed"] and not plan["novelty_claimed"]


def test_sweep_all_shortlisted_bare_constants_before_any_longer_application(setup):
    s = setup
    s.behavior["apply-assumption:A_wrong"] = "VERIFIED"
    report = discover(s, lookup_plan(**s.inputs, application_mode="bare-then-apply"))
    assert report["calls"] == 6
    for row in report["policies"].values():
        assert row["selected_name"] == "Z_good" and row["selected_method"] == "bare"
        assert all(a["method"] == "bare" for a in row["attempts"])


def test_application_requires_bare_rejections_then_fresh_all_pin_validation(setup):
    s = setup
    s.behavior["bare:Z_good"] = "REJECTED"
    plan = json.loads(json.dumps(lookup_plan(**s.inputs, application_mode="bare-then-apply")))
    report = discover(s, plan)
    assert report["calls"] == 12 and report["receipt_cache_hits"] == 0
    assert report["policies"]["direct-scan"]["checked_candidates"] == 4
    assert report["policies"]["direct-scan"]["checked_declarations"] == 2
    assert report["policies"]["direct-scan"]["whole_pool_exhausted"]
    for row in report["policies"].values():
        assert row["selected_method"] == "apply-assumption" and not row["composition_claimed"]
        assert row["candidate"] == STATEMENT + " := by solve | apply _root_.Z_good <;> assumption\n"
        assert not row["proof_verified"]  # synthetic offline fixture
    confirmation = confirm(s, json.loads(json.dumps(report, sort_keys=True)))
    assert len(s.calls) == 36 and not confirmation["comparison"]["native_pair_verified"]
    assert "bare-then-apply" in render_summary(report, confirmation)


@pytest.mark.parametrize("outcome", ["REJECTED", "TIMEOUT", "ERROR", "UNAVAILABLE"])
def test_application_partial_pin_success_cannot_claim_found(setup, outcome):
    s = setup
    s.behavior["bare:Z_good"] = "REJECTED"
    s.behavior[(s.inputs["context"].versions[-1], "apply-assumption:Z_good")] = outcome
    report = discover(s, lookup_plan(**s.inputs, application_mode="bare-then-apply"))
    assert report["status"] == ("COMPLETE" if outcome == "REJECTED" else "INCOMPLETE")
    for row in report["policies"].values():
        assert row["candidate"] is None and row["selected_method"] is None
        assert not row["semantic_equivalence_decided"] and not row["composition_claimed"]
        if outcome != "REJECTED":
            assert not row["whole_pool_exhausted"]


def test_recipe_count_is_not_distinct_declaration_coverage(setup):
    s = setup
    report = discover(s, lookup_plan(**s.inputs, application_mode="bare-then-apply", max_candidates=1))
    row = report["policies"]["direct-scan"]
    assert row["status"] == "NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET"
    assert row["checked_candidates"] == 2 and row["checked_declarations"] == 1
    assert not row["whole_pool_exhausted"] and not row["semantic_equivalence_decided"]


@pytest.mark.parametrize("damage", ["mode", "method", "budget", "order"])
def test_application_design_changes_rejected_without_compilation(setup, damage):
    s = setup
    plan = lookup_plan(**s.inputs, application_mode="bare-then-apply")
    if damage == "mode": plan["application_mode"] = "bare"
    elif damage == "method": plan["candidates"]["bm25"][0]["method"] = "apply-assumption"
    elif damage == "budget": plan["max_calls"] //= 2
    else: plan["candidates"]["direct-scan"].reverse()
    with pytest.raises(ValueError, match="stale or mutated"):
        discover(s, plan)
    assert not s.calls
