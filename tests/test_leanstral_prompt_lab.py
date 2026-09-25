"""Deterministic fixture experiments; no live network/model/compiler required."""
from dataclasses import asdict, replace
import json
import re
import sqlite3

import pytest

from jevops import leanstral, llm_router
from jevops.leanstral_prompt_lab import (Arm, Case, DEFAULT_ARMS, LocalGenerator, NativeJudge,
    PromptLab, arena_case, context_probes, parse_response, proposal_from_policy, render)
from tests.test_leanstral import transport  # Shared offline HTTP fixture, not a real model.
from tests.test_arena_trial import factory, RECORD, CANDIDATE  # Synthetic native-process fixture.


def oracle_response(messages, arm, *, wrong=False, marker="", truncated=False):
    content = "\n".join(m["content"] for m in messages)
    name = re.search(r"h_[0-9a-f]{16}", content)[0]
    tactic = "exact wrong" if wrong else "exact " + name
    if arm.contract == "json":
        request = re.search(r'"request_id":"([a-f0-9]{16})"', content)[1]
        tactic = json.dumps({"request_id": request, "tactic": tactic})
    return {"text": tactic + marker, "finish_reason": "length" if truncated else "stop",
            "usage": {"prompt_tokens": 20, "completion_tokens": 8}, "fixture": True}


def test_structured_messages_reach_router_without_flattening(transport):
    messages = [{"role": "system", "content": "Return a tactic"}, {"role": "user", "content": "⊢ True"}]
    generated = LocalGenerator(leanstral.BASE_URL, 32, 2)(messages, DEFAULT_ARMS[0])
    assert generated["text"] == "simp"
    assert json.loads(transport.calls[0][0].data)["messages"] == messages
    assert generated["server_identity_attested"] is False
    assert not transport.calls[0][0].has_header("Authorization")


@pytest.mark.parametrize("messages", [[], [{}], [{"role": [], "content": "x"}],
    [{"role": {}, "content": "x"}], [{"role": None, "content": "x"}], [{"role": 1, "content": "x"}],
    [{"role": "tool", "content": "x"}], [{"role": "user", "content": {"text": "x"}}],
    [{"role": "assistant", "content": "x"}], [{"role": "user", "content": ""}],
    [{"role": "user", "content": "x", "tools": []}],
    [{"role": "user", "content": "x"}, {"role": "system", "content": "y"}, {"role": "user", "content": "z"}]])
def test_message_boundaries_fail_before_network(transport, messages):
    with pytest.raises(leanstral.LeanstralError): leanstral.chat_completion(messages=messages)
    assert not transport.calls


def test_no_ambiguous_messages_or_silent_cross_provider_drop(transport):
    messages = [{"role": "user", "content": "tactic"}]
    with pytest.raises(llm_router.LLMRouterError):
        llm_router.generate_text("also a prompt", provider="leanstral", messages=messages)
    with pytest.raises(llm_router.LLMRouterError):
        llm_router.generate_text(None, provider="deterministic", messages=messages)
    assert not transport.calls


def test_structured_redacted_failure_categories(transport):
    import io
    import urllib.error
    transport.error = urllib.error.HTTPError("x", 400, "secret", {}, io.BytesIO(b"secret"))
    with pytest.raises(llm_router.LLMRouterError) as exc:
        llm_router.generate_text("x", provider="leanstral")
    assert exc.value.category == "http_error" and exc.value.http_status == 400
    assert "secret" not in str(exc.value)  # 400 is NOT a proven context-window error.
    transport.error = TimeoutError("private")
    with pytest.raises(leanstral.LeanstralError) as exc:
        leanstral.chat_completion("x")
    assert exc.value.category == "timeout"


def test_readonly_server_profile_does_not_expose_template_or_paths(transport):
    transport.payload = {"default_generation_settings": {"n_ctx": 8192}, "total_slots": 4,
                         "chat_template": "private template", "model_path": "/private/weights/model.gguf"}
    profile = leanstral.server_profile()
    assert profile["declared_context_per_slot"] == 8192 and profile["declared_slots"] == 4
    assert profile["server_reported_model_filename"] == "model.gguf"
    assert len(profile["chat_template_sha256"]) == 64 and not profile["server_identity_attested"]
    assert "private" not in json.dumps(profile)
    assert [c[0].get_method() for c in transport.calls] == ["GET", "GET"]
    transport.error = TimeoutError("private")
    assert len(leanstral.server_profile()["metadata_errors"]) == 2


def test_visible_server_drift_stops_before_confirmation(monkeypatch, tmp_path):
    profiles = iter([{"declared_context_per_slot": 8192}, {"declared_context_per_slot": 4096}])
    monkeypatch.setattr(leanstral, "server_profile", lambda *a, **k: next(profiles))
    def generate(self, messages, arm):
        return {**oracle_response(messages, arm), "fixture": False, "fallback_used": False,
                "response_model": "Leanstral", "endpoint": leanstral.endpoint(leanstral.BASE_URL)}
    monkeypatch.setattr(LocalGenerator, "__call__", generate)
    lab = PromptLab(tmp_path, context_probes())
    with pytest.raises(ValueError, match="metadata changed"): lab.run()
    with sqlite3.connect(tmp_path / "experiment.sqlite") as db:
        assert db.execute("SELECT count(*) FROM trials").fetchone()[0] == 24
        assert db.execute("SELECT value FROM meta WHERE key='nomination'").fetchone() is None


@pytest.mark.parametrize("mode,category", [("reasoning", "reasoning_without_answer"),
    ("truncated", "output_truncated"), ("tool", "unexpected_tool_calls")])
def test_response_failure_categories_remain_distinct(transport, mode, category):
    message = transport.payload["choices"][0]["message"]
    message["content"] = ""
    if mode == "reasoning": message["reasoning_content"] = "private thoughts"
    if mode == "truncated": transport.payload["choices"][0]["finish_reason"] = "length"
    if mode == "tool": message["tool_calls"] = [{"name": "shell"}]
    with pytest.raises(leanstral.LeanstralError) as exc: leanstral.chat_completion("x")
    assert exc.value.category == category and "private" not in str(exc.value)


def test_probe_oracles_are_hidden_and_formats_share_content():
    cases = context_probes()
    assert cases == context_probes() and cases != context_probes(18)
    for case in cases:
        for arm in DEFAULT_ARMS:
            messages, _ = render(case, arm)
            assert case.expected not in json.dumps(messages)
            if arm.context_format == "json":
                data = json.loads(messages[-1]["content"].split("\n")[-1])
                assert data["context"] == case.context
    assert "⊢" in cases[0].context


@pytest.mark.parametrize("value,contract", [(1, "json"), ("false", "json"), (None, "json"), (True, "tactic")])
def test_contract_example_is_strictly_typed_and_json_only(value, contract):
    with pytest.raises(ValueError, match="JSON-only"):
        Arm("example", contract=contract, contract_example=value)


def test_contract_example_has_no_answer_and_does_not_change_context_or_request():
    baseline = DEFAULT_ARMS[2]
    treatment = replace(baseline, contract_example=True)
    for case in context_probes(19):
        before, request_id = render(case, baseline)
        after, treatment_id = render(case, treatment)
        assert request_id == treatment_id and before[-1] == after[-1]
        assert after[0]["content"].startswith(before[0]["content"])
        assert "exact h_example" in after[0]["content"]
        assert case.expected not in json.dumps(after)
        assert parse_response('{"request_id":"example-request","tactic":"exact h_example"}',
                              treatment, request_id, "stop")["tactic"] is None
        # Even when the actual request ID is used, copying the unrelated tactic
        # cannot pass the independent exact-match oracle.
        copied = json.dumps({"request_id": request_id, "tactic": "exact h_example"})
        assert parse_response(copied, treatment, request_id, "stop")["tactic"] != case.expected


def test_copied_example_is_not_a_success_or_teacher(tmp_path):
    baseline = DEFAULT_ARMS[2]
    def generate(messages, arm):
        response = oracle_response(messages, arm)
        if arm.contract_example:
            value = json.loads(response["text"])
            value["tactic"] = "exact h_example"
            response["text"] = json.dumps(value)
        return response
    report = PromptLab(tmp_path, context_probes(), arms=(baseline,
        replace(baseline, name="example", contract_example=True)),
        generator=generate, objective="strict_context_accuracy").run()
    assert report["nomination"]["development_successes"] == {"system-json": 6, "example": 0}
    assert all(r["success"] is False for r in report["rows"] if r["arm"] == "example")
    assert report["official_score"] is None and not report["promotion"]


@pytest.mark.parametrize("raw,status", [("exact h<|im_end|>", "eos_artifact"),
    ("exact h", "parsed"), ("```lean\nexact h\n```", "contract_mismatch"),
    ("by exact h", "contract_mismatch"), ("exact <|im_end|> h", "contract_mismatch")])
def test_raw_and_normalized_contracts_are_distinct(raw, status):
    row = parse_response(raw, DEFAULT_ARMS[0], "id", "stop")
    assert row["status"] == status
    assert row["strict_contract"] == (status == "parsed")
    assert parse_response(raw, DEFAULT_ARMS[0], "id", "length")["tactic"] is None


@pytest.mark.parametrize("raw", ['{"request_id":"id","tactic":"rfl","score":100}',
    '{"request_id":"id","tactic":"rfl","tactic":"sorry"}',
    '{"request_id":"foreign","tactic":"rfl"}', '{"request_id":"id","tactic":NaN}'])
def test_json_is_strict_bound_and_cannot_self_report_success(raw):
    assert parse_response(raw, DEFAULT_ARMS[2], "id", "stop")["tactic"] is None


def test_balanced_repeated_design_is_durable_and_never_a_proof(tmp_path):
    calls = []
    def generate(messages, arm):
        calls.append((messages, arm.name))
        return oracle_response(messages, arm, marker="<|im_end|>")
    lab = PromptLab(tmp_path, context_probes(), generator=generate)
    report = lab.run()
    assert report["calls_reserved"] == len(calls) == 28
    assert report["nomination"]["arm"] == "plain"  # Fixed baseline tie-break.
    assert report["confirmation_complete"] and report["paired_confirmation"] == {"tie": 4}
    assert all(r["native_verified"] is None for r in report["rows"])
    assert report["official_score"] is None and report["promotion"] is False
    assert report["context_window_limit"] is None
    assert all(g["strict_contracts"] == 0 for g in report["groups"])
    assert all(g["attempts"] == 6 for g in report["groups"] if g["split"] == "development")
    assert lab.run() == report and len(calls) == 28
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved == report
    with pytest.raises(ValueError, match="changed"):
        PromptLab(tmp_path, context_probes(), generator=generate, model_revision="different").run()


def test_freezes_winner_before_confirmation_and_does_not_retune(tmp_path):
    cases = context_probes()
    def generate(messages, arm):
        content = "\n".join(m["content"] for m in messages)
        is_confirmation = any(c.expected.split()[1] in content for c in cases if c.split == "confirmation")
        wrong = arm.name != "json-context" if not is_confirmation else arm.name == "json-context"
        return oracle_response(messages, arm, wrong=wrong)
    report = PromptLab(tmp_path, cases, generator=generate).run()
    assert report["nomination"]["arm"] == "json-context"
    assert report["calls_reserved"] == 32 and report["confirmation_used_for_selection"] is False
    assert report["paired_confirmation"] == {"baseline_only_success": 4}
    assert set(r["arm"] for r in report["rows"] if r["split"] == "confirmation") == {"plain", "json-context"}


def test_crashed_call_is_reserved_never_retried_and_prevents_nomination(tmp_path):
    def crash(*_): raise KeyboardInterrupt()
    lab = PromptLab(tmp_path, context_probes(), generator=crash)
    with pytest.raises(KeyboardInterrupt): lab.run()
    calls = []
    def generate(messages, arm):
        calls.append(1)
        return oracle_response(messages, arm)
    lab.generator = generate
    report = lab.run()
    assert report["interrupted_calls"] == 1 and len(calls) == 23
    assert report["calls_reserved"] == 24 and report["nomination"]["arm"] is None
    assert not report["confirmation_complete"]


def test_transport_failures_are_retained_and_no_retry(tmp_path):
    def fail(*_): raise llm_router.LLMRouterError("do not log this secret", category="timeout")
    report = PromptLab(tmp_path, context_probes(), generator=fail).run()
    assert report["calls_reserved"] == 24 and report["nomination"]["arm"] is None
    assert all(r["status"] == "timeout" for r in report["rows"])
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize("kwargs", [{"max_calls": 31}, {"repetitions": 1}, {"max_new_tokens": True},
    {"timeout": 61}, {"max_prompt_bytes": 1024}, {"max_native_requests": -1}])
def test_invalid_budget_rejected_without_side_effects(tmp_path, kwargs):
    with pytest.raises(ValueError): PromptLab(tmp_path / "unused", context_probes(), **kwargs)
    assert not (tmp_path / "unused").exists()


def test_holdout_overlap_and_storage_limit_are_fail_closed(tmp_path):
    cases = list(context_probes())
    cases[-1] = replace(cases[0], name="duplicate", split="confirmation")
    with pytest.raises(ValueError, match="overlap"): PromptLab(tmp_path, cases)
    def full(): raise RuntimeError("storage limit")
    lab = PromptLab(tmp_path, context_probes(), generator=lambda *_: pytest.fail("no model call"), storage_guard=full)
    with pytest.raises(RuntimeError, match="storage"): lab.run()
    assert not (tmp_path / "experiment.sqlite").exists()


def arena_cases():
    return tuple(arena_case({**RECORD, "name": f"case-{i}",
                            "statement": RECORD["statement"].replace("example", f"case_{i}"),
                            "src": RECORD["src"].replace("example", f"case_{i}")},
                           split="development" if i < 3 else "confirmation") for i in range(5))


def test_no_native_measurement_means_no_proof_policy_selection(tmp_path):
    cases = arena_cases()
    def generate(messages, arm): return {"text": "exact h", "finish_reason": "stop"}
    report = PromptLab(tmp_path, cases, arms=DEFAULT_ARMS[:2], generator=generate).run()
    assert report["nomination"]["arm"] is None and report["calls_reserved"] == 12
    assert all(r["native_verified"] is None and r["success"] is None for r in report["rows"])
    assert all(r["status"] == "native_not_measured" for r in report["rows"])


def test_policy_only_yields_unverified_candidates_and_forbids_sorry():
    case = arena_case(RECORD)
    def generator(text): return lambda *_: {"text": text, "finish_reason": "stop"}
    candidate = proposal_from_policy(case, DEFAULT_ARMS[0], generator=generator("exact h<|im_end|>"))
    assert candidate.source.startswith(RECORD["statement"] + " := by")
    assert candidate.provenance.startswith("unverified-")
    for bad in ("sorry", "set_option maxHeartbeats 0 in trivial", "theorem hacked : True := by trivial"):
        assert proposal_from_policy(case, DEFAULT_ARMS[0], generator=generator(bad)) is None


def test_native_adapter_uses_real_trial_gates_but_fixtures_are_not_proofs(factory):
    judge = NativeJudge(lambda record, limit: (factory(), {}), identity="test-fixture", evidence_mode="offline_fixture")
    result = judge(arena_case(RECORD), CANDIDATE)
    assert result["native_verified"] is None and result["strict_dual_win"] is True
    assert result["trial"]["verifier_invocations"] == judge.cost(arena_case(RECORD)) == 8
    assert result["trial"]["native_processes"] == 0 and result["evidence_mode"] == "offline_fixture"
    # No strict-dual reward for shorter tokens with worse heartbeats.
    worse = NativeJudge(lambda record, limit: (factory(lambda payload, *_:
        1 if payload["candidate"] == payload["reference"] else 99999), {}),
        identity="fixture-worse", evidence_mode="offline_fixture")
    assert worse(arena_case(RECORD), CANDIDATE)["strict_dual_win"] is False


def test_native_missing_environment_abstains_before_reward(factory, tmp_path):
    judge = NativeJudge(lambda *_: ({}, {}), identity="missing")
    result = judge(arena_case(RECORD), CANDIDATE)
    assert result["status"] == "environment_or_control_failure" and not result["strict_dual_win"]
    with pytest.raises(ValueError, match="native design"):
        PromptLab(tmp_path, arena_cases(), arms=DEFAULT_ARMS[:2], judge=judge, max_native_requests=0)


def test_arena_records_are_snapshotted_against_caller_mutation(tmp_path):
    cases = arena_cases()
    lab = PromptLab(tmp_path, cases, arms=DEFAULT_ARMS[:2], generator=lambda *_: {})
    before = asdict(lab.cases[0])
    cases[0].record["src"] = "changed"
    assert asdict(lab.cases[0]) == before


def test_renamed_record_cannot_hide_identical_statement_holdout_leak(tmp_path):
    cases = list(arena_cases())
    leaked = {**cases[0].record, "name": "new-name"}
    cases[-1] = arena_case(leaked, split="confirmation")
    with pytest.raises(ValueError, match="overlap"): PromptLab(tmp_path, cases)
