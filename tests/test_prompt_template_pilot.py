"""Offline pilot wiring; fabricated transport metadata never proves a theorem."""
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py"


@pytest.fixture
def pilot(monkeypatch):
    monkeypatch.setenv("JEVOPS_REGISTER_LRA_HOOKS", "0")
    spec = importlib.util.spec_from_file_location("pilot", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_is_frozen_eight_call_design_with_both_contrasts(pilot):
    p = pilot.make_plan()
    assert p == pilot.make_plan()
    assert [s["slot"] for s in p["schedule"]] == list(range(8))
    for name in p["arms"]:
        assert len([s for s in p["schedule"] if s["arm"] == name]) == 2
    assert p["arms"]["contrastive-history"]["manifest"]["max_examples"] == 2
    assert len(p["arms"]["contrastive-history"]["manifest"]["selected_source_hashes"]) == 2
    assert p["native_protocol"]["max_requests"] == 108 and not p["automatic_execution"]


@pytest.mark.parametrize("raw,finish,expected", [("rfl", "stop", "parsed"), ("sorry", "stop", "intake_rejected"),
    ("rfl", "length", "output_truncated"), ("rfl<|im_end|>", "stop", "eos_artifact")])
def test_generation_never_executes_and_rejects_truncation(pilot, monkeypatch, raw, finish, expected):
    monkeypatch.setattr(pilot.llm_router, "generate_text", lambda *a, **kw: raw)
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": finish})
    plan = pilot.make_plan()
    row = pilot.generation_row(plan["schedule"][0], "test prompt", plan["record"], plan["settings"])
    assert row["status"] == expected and row["native_verified"] is None
    if finish == "length": assert "source" not in row


def test_resume_never_retries_interrupted_reservations(pilot, monkeypatch, tmp_path):
    plan = pilot.make_plan()
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: {"test": "fixture"})
    monkeypatch.setattr(pilot.leanstral, "health_status", lambda _: (200, ""))
    monkeypatch.setattr(pilot, "generation_row", lambda *a: pytest.fail("interrupted slots must not retry"))
    for slot in plan["schedule"]:
        pilot.save(tmp_path / f"slot-{slot['slot']:02d}-reserved.json", {**slot, "plan_id": plan["plan_id"]})
    pilot.run(tmp_path, {}, plan)
    report = json.loads((tmp_path / "generation.json").read_text())
    assert report["requests_reserved"] == 8 and report["candidate_files"] == []
    assert {r["status"] for r in report["rows"]} == {"interrupted_unknown"}


def test_contract_plan_is_matched_factorial(pilot):
    plan = pilot.make_contract_plan()
    assert plan == pilot.make_contract_plan()
    assert [s["slot"] for s in plan["schedule"]] == list(range(8))
    assert plan["history"] == [] and plan["native_protocol"]["max_requests"] == 27
    for repetition in range(2):
        requests = [arm["requests"][repetition] for arm in plan["arms"].values()]
        assert len({r["request_id"] for r in requests}) == 1
        for contract in ("tactic", "json"):
            single = plan["arms"]["user-" + contract]["requests"][repetition]["messages"]
            split = plan["arms"]["system-user-" + contract]["requests"][repetition]["messages"]
            assert single[0]["content"] == split[0]["content"] + "\n" + split[1]["content"]
        assert requests[2]["messages"][1] == requests[3]["messages"][1]


def test_output_budget_plan_is_matched_and_bounded(pilot):
    plan = pilot.make_output_budget_plan()
    assert plan == pilot.make_output_budget_plan()
    assert [s["slot"] for s in plan["schedule"]] == list(range(8))
    settings = [pilot.slot_settings(plan, s) for s in plan["schedule"]]
    assert sum(s["max_new_tokens"] for s in settings) == plan["max_output_tokens_total"] == 16384
    assert {s["timeout"] for s in settings} == {300}
    assert plan["history"] == [] and plan["min_declared_context_per_slot"] == 8192
    for repetition in range(2):
        for style in ("placeholder", "descriptive"):
            low, high = [plan["arms"][f"{style}-{budget}"]["requests"][repetition] for budget in (1024, 3072)]
            assert low == high  # Only the actual generation allowance changes.
        requests = [a["requests"][repetition] for a in plan["arms"].values()]
        assert len({r["request_id"] for r in requests}) == 1
        assert len({r["messages"][1]["content"] for r in requests}) == 1
        descriptive = requests[2]["messages"][0]["content"]
        assert "the tactic body without by" not in descriptive
        assert "exactly two string fields" in descriptive
    old = json.loads((PATH.parents[1] / "evidence/prompt-contract-pilot-2026-09-23/plan.json").read_text())
    current = pilot.make_contract_plan()
    for name in old["arms"]:
        assert old["arms"][name]["requests"] == current["arms"][name]["requests"]


@pytest.mark.parametrize("tokens", [0, -1, True, 1.5, 32769])
def test_invalid_treatment_allowance_is_rejected(pilot, tokens):
    plan = pilot.make_output_budget_plan()
    slot = plan["schedule"][0]
    plan["arms"][slot["arm"]]["settings"]["max_new_tokens"] = tokens
    with pytest.raises(ValueError, match="positive integer"):
        pilot.slot_settings(plan, slot)


def test_budget_and_context_checks_precede_model_calls(pilot, monkeypatch, tmp_path):
    plan = pilot.make_output_budget_plan()
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: {"declared_context_per_slot": 4096})
    monkeypatch.setattr(pilot.leanstral, "health_status", lambda _: pytest.fail("must fail before HTTP"))
    plan["max_output_tokens_total"] = 16383
    with pytest.raises(ValueError, match="aggregate"):
        pilot.run(tmp_path, {}, plan)
    assert not (tmp_path / "plan.json").exists()
    plan["max_output_tokens_total"] = 16384
    with pytest.raises(ValueError, match="serving context"):
        pilot.run(tmp_path, {}, plan)
    assert not list(tmp_path.glob("slot-*-reserved.json"))
    plan["arms"][plan["schedule"][0]["arm"]]["settings"]["base_url"] = "http://untrusted.invalid"
    with pytest.raises(ValueError, match="only the output allowance"):
        pilot.slot_settings(plan, plan["schedule"][0])


def test_treatment_allowance_reaches_transport_and_resume_does_not_retry(pilot, monkeypatch, tmp_path):
    import re
    plan = pilot.make_output_budget_plan()
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: {"declared_context_per_slot": 8192})
    monkeypatch.setattr(pilot.leanstral, "health_status", lambda _: (200, ""))
    calls = []
    def generate(prompt, **kwargs):
        assert prompt is None
        calls.append(kwargs["max_new_tokens"])
        request_id = re.search(r"Request: ([0-9a-f]{16})", kwargs["messages"][1]["content"])[1]
        return json.dumps({"request_id": request_id, "tactic": "rfl"})
    monkeypatch.setattr(pilot.llm_router, "generate_text", generate)
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": "stop"})
    pilot.run(tmp_path, {}, plan)
    pilot.run(tmp_path, {}, plan)
    assert len(calls) == 8 and calls.count(1024) == calls.count(3072) == 4
    reservations = [json.loads(p.read_text()) for p in tmp_path.glob("slot-*-reserved.json")]
    assert sum(r["max_output_tokens_reserved"] for r in reservations) == 16384
    report = json.loads((tmp_path / "generation.json").read_text())
    assert report["native_executions"] == 0
    assert [r["request_settings"]["max_new_tokens"] for r in report["rows"]] == calls


@pytest.mark.parametrize("style,contract", [("unknown", "json"), ("descriptive", "tactic"), (None, "json")])
def test_contract_wording_validation(pilot, style, contract):
    with pytest.raises(ValueError, match="JSON-only"):
        pilot.Arm("invalid", json_contract_style=style, contract=contract)


def test_new_verification_epoch_preserves_generation_and_rejects_tampering(pilot, monkeypatch, tmp_path):
    import copy
    current = pilot.make_output_budget_plan()
    previous = copy.deepcopy(current)
    previous["implementation"]["jevops/llm_router.py"] = "older-router-content-hash"
    previous["plan_id"] = pilot.content_hash({k: v for k, v in previous.items() if k != "plan_id"})
    origin, target = tmp_path / "generation", tmp_path / "verification"
    origin.mkdir()
    source = previous["record"]["statement"] + " := by\n  rfl"
    pilot.save(origin / "plan.json", previous)
    pilot.save(origin / "generation.json", {"plan_id": previous["plan_id"], "candidate_files": ["draft-0.json"],
        "rows": [{"candidate_label": "draft-0", "source": source, "source_sha256": pilot.source_hash(source)}]})
    pilot.save(origin / "draft-0.json", {"name": pilot.PROBLEM, "label": "draft-0", "source": source})
    before = {p.name: p.read_bytes() for p in origin.iterdir()}
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    epoch = pilot.verification_epoch(origin, target, {}, current)
    assert epoch["plan_id"] not in (current["plan_id"], previous["plan_id"])
    assert epoch["generation_origin"]["new_model_calls"] == 0
    assert epoch["generation_origin"]["plan_id"] == previous["plan_id"]
    assert json.loads((target / "generation.json").read_text())["plan_id"] == previous["plan_id"]
    assert before == {p.name: p.read_bytes() for p in origin.iterdir()}
    with pytest.raises(ValueError, match="verification-only"):
        pilot.run(target, {}, epoch)
    with pytest.raises(ValueError, match="new empty"):
        pilot.verification_epoch(origin, target, {}, current)
    changed = copy.deepcopy(current)
    changed["settings"]["temperature"] = 1
    with pytest.raises(ValueError, match="task/protocol/settings changed"):
        pilot.verification_epoch(origin, tmp_path / "changed", {}, changed)
    (target / "draft-0.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact changed"):
        pilot.triage(target, {}, epoch, [], tmp_path, [pilot.source_hash(source)])
    assert not (target / "native-plan.json").exists()


def test_json_generation_uses_bound_messages_without_losing_layout(pilot, monkeypatch):
    plan = pilot.make_contract_plan()
    treatment = plan["arms"]["system-user-json"]
    request = treatment["requests"][0]
    body = "  intro h\n  exact h"
    def generate(prompt, **kw):
        assert prompt is None and kw["messages"] == request["messages"]
        return json.dumps({"request_id": request["request_id"], "tactic": body})
    monkeypatch.setattr(pilot.llm_router, "generate_text", generate)
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": "stop"})
    row = pilot.generation_row({}, request["messages"], plan["record"], plan["settings"],
                               pilot.Arm(**treatment["arm"]), request["request_id"])
    assert row["status"] == "parsed" and row["tactic"] == body
    assert row["source"].endswith("\n    intro h\n    exact h")


@pytest.mark.parametrize("plan_factory", ["make_contract_plan", "make_deletion_order_plan", "make_deletion_id_plan", "make_deletion_feedback_plan"])
def test_native_triage_requires_review_and_stops_failed_candidate(pilot, monkeypatch, tmp_path, plan_factory):
    from dataclasses import dataclass
    from jevops import arena_lean
    from jevops.arena import Outcome, VersionReceipt
    if plan_factory == "make_deletion_feedback_plan":
        from tests.test_deletion_feedback_pilot import ARCHIVE, history_digest
        plan = pilot.make_deletion_feedback_plan(ARCHIVE, history_digest())
    else:
        plan = getattr(pilot, plan_factory)()
    source = plan["record"]["statement"] + " := by\n  rfl"
    digest = pilot.source_hash(source)
    pilot.save(tmp_path / "plan.json", plan)
    pilot.save(tmp_path / "generation.json", {"plan_id": plan["plan_id"], "candidate_files": ["draft-0.json"],
        "rows": [{"candidate_label": "draft-0", "source": source, "source_sha256": digest}]})
    pilot.save(tmp_path / "draft-0.json", {"name": pilot.PROBLEM, "label": "draft-0", "source": source})
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    with pytest.raises(ValueError, match="explicit review"):
        pilot.triage(tmp_path, {}, plan, [], tmp_path, [])
    assert not (tmp_path / "native-plan.json").exists()

    @dataclass
    class Context:
        context_id: str = "fixture-context"

    class Verifier:
        processes = 0
        def __init__(self, *a, **kw): pass
        def context(self, record): return Context()
        def __call__(self, request):
            self.processes += 1
            return VersionReceipt(request.request_id, pilot.source_hash(request.source), pilot.PROBLEM,
                Outcome.REJECTED if request.source == source else Outcome.VERIFIED)

    monkeypatch.setattr(arena_lean, "NativeLeanVerifier", Verifier)
    monkeypatch.setattr(arena_lean, "project_binding", lambda *a: object())
    projects = [{"repository": plan["record"]["url"], "lean_tag": tag, "git_commit": commit}
                for row in plan["record"]["version_info"] for tag, commit in row.items()]
    pilot.triage(tmp_path, {}, plan, projects, tmp_path, [digest])
    result = json.loads((tmp_path / "native-triage.json").read_text())
    assert result["native_requests"] == result["native_processes"] == 4
    assert [r["status"] for r in result["rows"] if r["label"] == "draft-0"] == [
        "REJECTED", "NOT_RUN_AFTER_NON_SUCCESS", "NOT_RUN_AFTER_NON_SUCCESS"]
    assert result["all_pin_verified_candidates"] == []
    with pytest.raises(FileExistsError):
        pilot.triage(tmp_path, {}, plan, projects, tmp_path, [digest])
