"""Catalog screen wiring, offline fixtures only; no native/model requests."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from jevops.arena import ArenaContext, Outcome, VersionReceipt, source_hash
from jevops.arena_lean import CORPUS

PATH = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/run_deletion_catalog_sweep.py"
STATEMENT = "theorem example (h : True) : True"
RECORD = {"name": "example", "statement": STATEMENT,
    "src": STATEMENT + " := by\n  have unused : True := h\n  exact h\n",
    "version_info": [{"v4.26.0": "a" * 40}, {"v4.27.0": "b" * 40}]}


@pytest.fixture
def sweep():
    spec = importlib.util.spec_from_file_location("deletion_sweep", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verifier_factory(directory, *, outcome=None, corrupt=False, interrupt=False, native_count=1):
    class Fixture:
        processes = 0

        def __init__(self, pin):
            self.pin = pin

        def context(self, record):
            return ArenaContext(record["name"], record["statement"], record["src"], 12, None,
                (self.pin,), ("d" * 64,), "offline-fixture", "fixture-v1", "fixture")

        def validate_request(self, request):
            assert request.version == self.pin

        def __call__(self, request):
            reservations = list(directory.glob("request-*-reserved.json"))
            assert any(json.loads(p.read_text())["request_id"] == request.request_id for p in reservations)
            if interrupt:
                raise KeyboardInterrupt("interrupted after reservation")
            self.processes += native_count
            result = Outcome.VERIFIED
            if request.source != request.context.reference_source and outcome:
                result = outcome(request)
            return VersionReceipt("0" * 64 if corrupt else request.request_id, source_hash(request.source),
                request.context.problem, result, type_preserved=True, exit_code=0,
                axiom_output=f"'{request.context.problem}' depends on axioms: []", heartbeats=1)
    return Fixture


def run(sweep, tmp_path, *, budget=6, **kwargs):
    directory = tmp_path / "run"
    return sweep.run_sweep(sweep.make_plan(RECORD, max_calls=budget), directory,
        verifier_factory(directory, **kwargs), check_resources=lambda: None, evidence_mode="offline_fixture")


def test_current_64_action_catalog_is_identical_to_prompt_pilots(sweep):
    record = next(json.loads(line) for line in CORPUS.read_text().splitlines()
                  if json.loads(line)["name"] == "Core.InitsUpdatesComm")
    plan = sweep.make_plan(record, max_calls=195)
    assert plan == sweep.make_plan(record, max_calls=195)
    assert plan["catalog_sha256"] == "52677802aa9a72d367b5a883b0b552a21d71b1d948af13ef7e1026e12f052219"
    assert len(plan["candidates"]) == len(plan["catalog"]["entries"]) == 64
    assert plan["exhaustive_request_ceiling"] == 195 and plan["model_calls"] == 0
    prefix = record["statement"] + " := by\n"
    lines = record["src"][len(prefix):].splitlines(keepends=True)
    for entry, candidate in zip(plan["catalog"]["entries"], plan["candidates"]):
        start, end = entry["delete_lines"]
        assert candidate["source"] == prefix + "".join(lines[:start - 1] + lines[end:])
        assert candidate["edit_ids"] == [entry["edit_id"]]


@pytest.mark.parametrize("budget", [-1, True, 1.5, 521])
def test_invalid_budget(sweep, budget):
    with pytest.raises(ValueError, match="integer request budget"):
        sweep.make_plan(RECORD, max_calls=budget)


@pytest.mark.parametrize("budget,requests,status", [(0, 0, "INCOMPLETE"), (5, 5, "INCOMPLETE"), (6, 6, "COMPLETE")])
def test_zero_and_exact_boundary(sweep, tmp_path, budget, requests, status):
    result = run(sweep, tmp_path, budget=budget)
    assert result["native_requests_reserved"] == result["native_processes"] == requests
    assert result["status"] == status
    assert len(list((tmp_path / "run").glob("request-*-reserved.json"))) == requests
    if budget == 0:
        assert result["contexts"] == {} and result["all_pin_verified_candidates"] == []
    assert not result["performance_selected"] and result["official_score"] is None


def test_fail_fast_semantic_rejection_not_unknown(sweep, tmp_path):
    result = run(sweep, tmp_path, outcome=lambda _: Outcome.REJECTED)
    assert result["native_requests_reserved"] == 4  # two controls, two first-pin edits
    assert result["status"] == "COMPLETE" and result["all_pin_verified_candidates"] == []
    assert {c["status"] for c in result["candidates"]} == {"REJECTED"}
    assert sum(r["status"] == "NOT_RUN_AFTER_NON_SUCCESS" for r in result["rows"]) == 2


@pytest.mark.parametrize("outcome", [Outcome.TIMEOUT, Outcome.UNAVAILABLE, Outcome.ERROR, Outcome.BUDGET_EXHAUSTED])
def test_transient_non_success_cannot_establish_infeasibility(sweep, tmp_path, outcome):
    result = run(sweep, tmp_path, outcome=lambda _: outcome)
    assert result["status"] == "INCOMPLETE" and result["native_requests_reserved"] == 4
    assert {c["status"] for c in result["candidates"]} == {"INCONCLUSIVE"}


def test_candidate_must_pass_every_pin(sweep, tmp_path):
    result = run(sweep, tmp_path, outcome=lambda r: Outcome.REJECTED if r.version.lean_tag == "v4.27.0" else Outcome.VERIFIED)
    assert result["status"] == "COMPLETE" and result["native_processes"] == 6
    assert result["all_pin_verified_candidates"] == []


@pytest.mark.parametrize("kwargs", [{"corrupt": True}, {"native_count": 0}])
def test_control_receipt_binding_and_fresh_process_gate(sweep, tmp_path, kwargs):
    result = run(sweep, tmp_path, **kwargs)
    assert result["status"] == "CONTROL_FAILED" and result["native_requests_reserved"] == 1
    assert result["all_pin_verified_candidates"] == []
    assert result["rows"][0]["status"] == "ERROR"


def test_setup_failure_is_explicit_and_does_not_charge(sweep, tmp_path):
    def unavailable(_):
        raise ValueError("missing fixture dependency")
    result = sweep.run_sweep(sweep.make_plan(RECORD, max_calls=6), tmp_path / "run", unavailable,
        check_resources=lambda: None, evidence_mode="offline_fixture")
    assert result["status"] == "CONTROL_FAILED" and result["native_requests_reserved"] == 0
    assert result["rows"][0]["status"] == "ERROR" and "setup" in result["rows"][0]["reason"]


def test_interrupted_reservation_cannot_be_reexecuted(sweep, tmp_path):
    with pytest.raises(KeyboardInterrupt):
        run(sweep, tmp_path, interrupt=True)
    assert len(list((tmp_path / "run").glob("request-*-reserved.json"))) == 1
    assert not (tmp_path / "run/sweep.json").exists()
    with pytest.raises(FileExistsError):
        run(sweep, tmp_path)


def test_completed_work_cannot_be_replayed_or_plan_tampered(sweep, tmp_path):
    run(sweep, tmp_path)
    with pytest.raises(FileExistsError):
        run(sweep, tmp_path)
    plan = sweep.make_plan(RECORD, max_calls=6)
    plan["candidates"][0]["source"] = STATEMENT + " := by sorry"
    with pytest.raises(ValueError, match="plan changed"):
        sweep.run_sweep(plan, tmp_path / "other", None, check_resources=lambda: None)
    assert not (tmp_path / "other").exists()


def test_source_equivalent_actions_are_checked_once(sweep, tmp_path, monkeypatch):
    spans = sweep.deletion_spans(RECORD["src"], RECORD["statement"])
    monkeypatch.setattr(sweep, "deletion_spans", lambda *_: (spans[0], spans[0]))
    plan = sweep.make_plan(RECORD, max_calls=4)
    assert len(plan["candidates"]) == 1 and plan["candidates"][0]["edit_ids"] == [1, 2]
    result = sweep.run_sweep(plan, tmp_path / "run", verifier_factory(tmp_path / "run"),
        check_resources=lambda: None, evidence_mode="offline_fixture")
    assert result["status"] == "COMPLETE" and result["native_processes"] == 4


def test_wrong_factory_context_is_not_accepted(sweep, tmp_path):
    factory = verifier_factory(tmp_path / "run")
    original = factory.context
    factory.context = lambda self, record: replace(original(self, record), problem="wrong")
    result = sweep.run_sweep(sweep.make_plan(RECORD, max_calls=6), tmp_path / "run", factory,
        check_resources=lambda: None, evidence_mode="offline_fixture")
    assert result["status"] == "CONTROL_FAILED" and result["native_requests_reserved"] == 0
