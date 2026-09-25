"""Orchestration fixtures are not Lean evidence; native replay has its own suite."""
import copy
import json

import pytest

pytest.importorskip("duckdb")
from jevops.arena import content_hash
from jevops.arena_local import ArenaLocalRuntime
from jevops.knowledge_lookup import lookup_plan
from jevops.knowledge_materialize import (_term_source, materialization_plan, run_materialization,
    measurement_plan, measure_materialization, render_summary)
from tests.test_knowledge_lookup import setup, discover, STATEMENT, SOURCE

pytestmark = pytest.mark.no_seal(reason="fresh materialization orchestration and negative controls")


@pytest.fixture
def experiment(setup, monkeypatch):
    s = setup
    s.behavior["bare:Z_good"] = "REJECTED"
    discovery = discover(s, lookup_plan(**s.inputs, application_mode="bare-then-apply"))
    s.behavior["bare:Z_good"] = "VERIFIED"
    s.calls.clear()
    s.discovery = discovery
    s.plan = materialization_plan(discovery, context=s.inputs["context"])
    s.local_calls, s.local_behavior = [], {}

    def capture(runtime, pin, *, source=None):
        assert source == s.plan["seed"] and source != SOURCE
        runtime.reserved += 1
        runtime.attempts += 1
        s.local_calls.append((pin, "capture", source))
        start = len((STATEMENT + " := by ").encode())
        event = dict(id="0", status="captured", start=str(start), end=str(len(source.rstrip().encode())),
                     before={"goals": [0]}, after={"goals": []})
        if s.local_behavior.get("anchor") == "nested": event["start"] = str(start + 8)
        if s.local_behavior.get("anchor") == "open": event["after"] = {"goals": [1]}
        events = [event, copy.deepcopy(event)] if s.local_behavior.get("anchor") == "duplicate" else [event]
        return dict(ok=not s.local_behavior.get("capture_error"), evidence_mode="fixture", capture={"trace": {"events": events}})

    def application(runtime, pin, source, capture, event_id, premise):
        assert source == s.plan["seed"] and premise == "Z_good" and event_id == 0
        runtime.reserved += 1
        runtime.attempts += 1
        assert runtime.reserved <= runtime.max_processes
        s.local_calls.append((pin, "application", source))
        text = s.local_behavior.get(pin, s.local_behavior.get("text", "exact _root_.Z_good"))
        return dict(ok=not s.local_behavior.get("application_error"),
            closing_reproduced=not s.local_behavior.get("roundtrip_error"), extracted_candidate=text,
            evidence_mode="fixture", proof_admitted=False, whole_source_checked=False)

    monkeypatch.setattr(ArenaLocalRuntime, "capture", capture)
    monkeypatch.setattr(ArenaLocalRuntime, "discover_application", application)
    return s


def run(s, **changes):
    args = dict(guard=s.guard(max_calls=s.plan["max_calls"]), max_calls=s.plan["max_calls"],
                max_local_processes=s.plan["max_local_processes"])
    return run_materialization(s.plan, s.discovery, **{**args, **changes})


def measure(s, report, **changes):
    plan = measurement_plan(report)
    args = dict(verifiers=s.verifiers(), max_calls=plan["planned_requests"])
    return measure_materialization(plan, report, **{**args, **changes})


def test_plan_is_fixed_and_budgets_both_stages_without_work(experiment):
    s = experiment
    assert s.plan == materialization_plan(s.discovery, context=s.inputs["context"])
    assert s.plan["max_calls"] == s.plan["max_local_processes"] == 4
    assert s.plan["policy"] == "bm25" and not s.plan["fresh_retrieval"]
    assert not s.plan["reference_body_used_for_extraction"] and not s.calls and not s.local_calls


def test_roundtrip_then_fresh_checks_and_independent_measurement(experiment):
    s = experiment
    s.plan = json.loads(json.dumps(s.plan, sort_keys=True))
    result = run(s)
    assert result["status"] == "FIXTURE_DRAFT" and result["candidate"] == STATEMENT + " := _root_.Z_good\n"
    assert result["whole_source_calls"] == result["local_invocations"] == result["local_reserved"] == 4
    assert result["native_processes"] == result["receipt_cache_hits"] == 0
    assert not result["proof_verified"] and not result["training_enabled"]
    assert len(s.calls) == 4 and len(s.local_calls) == 4
    assert all(payload["candidate"] == s.plan["seed"] for _, payload in s.calls[:2])
    measured = measure(s, json.loads(json.dumps(result, sort_keys=True)))
    assert len(s.calls) == 28 and measured["measurement"]["verifier_invocations"] == 24
    assert measured["versus_application"]["reference_tokens"] == 7
    assert measured["versus_application"]["candidate_tokens"] == 1
    assert not measured["versus_reference"]["native_pair_verified"]
    assert measured["versus_reference"]["observed_pareto_improvement"] is None
    assert "No fresh retrieval" in render_summary(result, measured)


@pytest.mark.parametrize("damage", ["seed", "policy", "nodes", "local_budget", "call_budget", "context", "used_guard"])
def test_bad_plans_and_allowances_fail_before_work(experiment, damage):
    s = experiment
    options = {}
    if damage == "seed": s.plan["seed"] += " "
    elif damage == "policy": s.plan["policy"] = "direct-scan"
    elif damage == "nodes": s.plan["node_budget"] -= 1
    elif damage == "local_budget": options["max_local_processes"] = 3
    elif damage == "call_budget": options["max_calls"] = 3
    elif damage == "context": options["guard"] = s.guard(timeout=61)
    else:
        options["guard"] = s.guard()
        options["guard"].processes = 1
    with pytest.raises(ValueError): run(s, **options)
    assert not s.calls and not s.local_calls


@pytest.mark.parametrize("outcome", ["REJECTED", "TIMEOUT", "ERROR", "UNAVAILABLE"])
def test_unverified_seed_never_reaches_extractor(experiment, outcome):
    s = experiment
    s.behavior[(s.inputs["context"].versions[-1], "apply-assumption:Z_good")] = outcome
    result = run(s)
    assert result["status"] == "SEED_NOT_VERIFIED" and result["candidate"] is None
    assert len(s.calls) == 2 and not s.local_calls


@pytest.mark.parametrize("failure", ["capture_error", "application_error", "roundtrip_error", "nested", "open", "duplicate"])
def test_local_failures_and_non_root_anchors_are_abstentions(experiment, failure):
    s = experiment
    if failure in {"nested", "open", "duplicate"}: s.local_behavior["anchor"] = failure
    else: s.local_behavior[failure] = True
    result = run(s)
    assert result["status"] in {"ANCHOR_UNAVAILABLE", "EXTRACTION_INCOMPLETE"}
    assert result["candidate"] is None and result["candidate_check"] is None
    assert len(s.calls) == 2 and not result["proof_verified"]
    if failure in {"nested", "open", "duplicate"}:
        assert len(s.local_calls) == 1


def test_pin_printing_disagreement_abstains_before_whole_term_check(experiment):
    s = experiment
    s.local_behavior[s.inputs["context"].versions[-1]] = "exact _root_.Other"
    result = run(s)
    assert result["status"] == "PIN_TERM_DISAGREEMENT" and result["candidate"] is None
    assert len(s.calls) == 2 and len(s.local_calls) == 4


@pytest.mark.parametrize("text", [None, "apply _root_.Z_good", "exact ", "exact sorry", "exact True.intro\naxiom bad : False", "exact \x00", "exact \rX", "exact " + "x" * 4096])
def test_extracted_envelope_is_not_a_source_injection_path(text):
    with pytest.raises(ValueError): _term_source(STATEMENT, text)


def test_unsupported_and_not_shorter_terms_do_not_get_checked_or_selected(experiment):
    s = experiment
    for text, status in (("exact sorry", "UNSUPPORTED_TERM"),
                         ("exact _root_.Z_good " + "x " * 20, "NOT_SHORTER")):
        s.local_behavior["text"] = text
        result = run(s)
        assert result["status"] == status and result["candidate"] is None and result["candidate_check"] is None
    assert len(s.calls) == 4


@pytest.mark.parametrize("outcome", ["REJECTED", "TIMEOUT", "ERROR"])
def test_local_replay_is_not_whole_source_authority(experiment, outcome):
    s = experiment
    s.behavior[(s.inputs["context"].versions[-1], "bare:Z_good")] = outcome
    result = run(s)
    assert result["status"] == "EXTRACTED_SOURCE_NOT_VERIFIED"
    assert result["extracted_source"] and result["candidate"] is None and not result["proof_verified"]
    assert result["whole_source_calls"] == 4


def test_no_application_means_no_extraction_or_cached_success(experiment):
    s = experiment
    for row in s.discovery["policies"].values():
        row.update(status="NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET", candidate=None,
                   selected_name=None, selected_method=None, proof_verified=False)
    s.discovery["report_sha256"] = content_hash({k: v for k, v in s.discovery.items() if k != "report_sha256"})
    s.plan = materialization_plan(s.discovery, context=s.inputs["context"])
    report = run(s)
    assert report["status"] == "NOT_AN_APPLICATION" and report["candidate"] is None
    assert not s.calls and not s.local_calls and report["whole_source_calls"] == 0
    measured = measure(s, report)
    assert measured["versus_reference"]["observed_pareto_improvement"] is None
    assert all(a["source"] == SOURCE for a in measured["measurement"]["arms"])


def test_fixture_runner_cannot_enter_native_mode(experiment):
    s = experiment
    s.discovery["evidence_mode"] = "local_lean"  # synthetic protocol labels, never native evidence
    s.discovery["report_sha256"] = content_hash({k: v for k, v in s.discovery.items() if k != "report_sha256"})
    s.plan = materialization_plan(s.discovery, context=s.inputs["context"])
    with pytest.raises(ValueError, match="fixture local runner"):
        run(s, local_runner=lambda *a: {})
    assert not s.calls and not s.local_calls


@pytest.mark.parametrize("damage", ["report", "budget", "missing_pin", "options", "used_guard"])
def test_confirmation_integrity_failures_do_not_do_more_work(experiment, damage):
    s = experiment
    report = run(s)
    args = {}
    if damage == "report": report["candidate"] += " "
    elif damage == "budget": args["max_calls"] = 23
    elif damage == "options": args["verifiers"] = s.verifiers(timeout=61)
    else:
        args["verifiers"] = s.verifiers()
        if damage == "missing_pin": args["verifiers"].pop(next(iter(args["verifiers"])))
        else: next(iter(args["verifiers"].values())).processes = 1
    before = len(s.calls)
    with pytest.raises(ValueError): measure(s, report, **args)
    assert len(s.calls) == before


@pytest.mark.parametrize("failed", [None, "control", "bare:Z_good", "apply-assumption:Z_good"])
def test_simulated_native_eligibility_requires_all_three_arms(experiment, failed):
    """Mock protocol labels exercise gating; not stored as proof evidence."""
    s = experiment
    report = run(s)
    report["plan"]["evidence_mode"] = "local_lean"
    report.update(status="CHECKED_DRAFT", proof_verified=True)
    report["report_sha256"] = content_hash({k: v for k, v in report.items() if k != "report_sha256"})
    if failed is not None: s.behavior[failed] = "REJECTED"
    measured = measure(s, report)
    assert measured["versus_reference"]["native_pair_verified"] is (failed is None)
    if failed is not None:
        assert measured["versus_application"]["observed_pareto_improvement"] is None
    else:
        assert "Reference raw HB" in render_summary(report, measured)
