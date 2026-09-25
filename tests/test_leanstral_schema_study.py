"""Offline fixtures: a requested schema never substitutes for proof checking."""
import json
import re
import sqlite3
import urllib.error

import pytest

from jevops import leanstral, llm_router
from jevops.arena import Outcome
from jevops.leanstral_prompt_contracts import ClientBindingError, bind_response, check_binding, request_binding
from jevops.leanstral_prompt_lab import Arm, LocalGenerator, parse_response
from tests.test_leanstral import response, transport
from tests.test_leanstral_repair_lab import Backend, build

RID = "0123456789abcdef"


def test_router_and_client_send_and_bind_exact_schema(transport):
    arm = Arm("schema-test", contract="json")
    messages = [{"role": "user", "content": "Return the requested tactic JSON."}]
    fmt = leanstral.tactic_response_format(RID)
    raw = json.dumps({"request_id": RID, "tactic": "simp"})
    transport.payload = response(raw)
    result = LocalGenerator(leanstral.BASE_URL, 1024, 45)(messages, arm, response_format=fmt)
    payload = json.loads(transport.calls[0][0].data)
    assert payload["response_format"] == fmt and payload["messages"] == messages
    assert len(transport.calls) == 1 and not result["fallback_used"]
    check_binding(result["client_binding"], messages, arm, raw, response_format=fmt)
    with pytest.raises(ClientBindingError):
        check_binding(result["client_binding"], messages, arm, raw)
    with pytest.raises(ClientBindingError):
        check_binding(result["client_binding"], messages, arm, raw,
                      response_format=leanstral.tactic_response_format("a" * 16))


def test_default_wire_request_and_old_binding_unchanged(transport):
    arm, messages = Arm("control"), [{"role": "user", "content": "simp"}]
    result = LocalGenerator(leanstral.BASE_URL, 1024, 45)(messages, arm)
    assert "response_format" not in json.loads(transport.calls[0][0].data)
    assert request_binding(messages, arm) == request_binding(messages, arm, response_format=None)
    check_binding(result["client_binding"], messages, arm, result["text"])


@pytest.mark.parametrize("damage", ["ref", "extra", "empty", "large_repetition", "bool", "nonce", "malformed", "tools"])
def test_rejects_unapproved_schemas_before_io(transport, damage):
    fmt = leanstral.tactic_response_format(RID)
    kwargs = {}
    if damage == "ref": fmt["schema"]["$ref"] = "https://invalid.example/schema"
    if damage == "extra": fmt["schema"]["additionalProperties"] = True
    if damage == "empty": fmt["schema"]["properties"]["tactic"].pop("minLength")
    if damage == "large_repetition": fmt["schema"]["properties"]["tactic"]["maxLength"] = 16384
    if damage == "bool": fmt["schema"]["properties"]["tactic"]["minLength"] = True
    if damage == "nonce": fmt["schema"]["properties"]["request_id"]["enum"] = ["wrong"]
    if damage == "malformed": fmt = []
    if damage == "tools": kwargs["tools"] = []
    with pytest.raises(leanstral.LeanstralError):
        leanstral.chat_completion("prompt", response_format=fmt, **kwargs)
    assert not transport.calls


def test_server_grammar_avoids_large_repetition_but_host_byte_limit_remains():
    fmt = leanstral.tactic_response_format(RID)
    assert fmt["schema"]["properties"]["tactic"] == {"type": "string", "minLength": 1}
    arm = Arm("schema-test", contract="json")
    for tactic in ("x" * 16385, "α" * 8193):
        raw = json.dumps({"request_id": RID, "tactic": tactic}, ensure_ascii=False)
        parsed = parse_response(raw, arm, RID, "stop")
        assert not parsed["strict_contract"] and parsed["tactic"] is None


@pytest.mark.parametrize("provider", ["deterministic", "muse", "codex_cli"])
def test_no_silent_schema_drop_on_other_providers(transport, provider):
    with pytest.raises(llm_router.LLMRouterError, match="response_format"):
        llm_router.generate_text("prompt", provider=provider, response_format=leanstral.tactic_response_format(RID))
    assert not transport.calls


def test_schema_http_failure_no_retry_or_fallback(transport):
    transport.error = urllib.error.HTTPError(leanstral.BASE_URL, 400, "unsupported", {}, None)
    with pytest.raises(llm_router.LLMRouterError) as exc:
        llm_router.generate_text("prompt", provider="leanstral_local", response_format=leanstral.tactic_response_format(RID))
    assert exc.value.category == "http_error" and exc.value.http_status == 400
    assert len(transport.calls) == 1


def generator_for(tactic="exact missing_h", *, malformed=False, wrong_binding=False):
    def generate(messages, arm, *, response_format=None):
        rid = re.search(r"Request: ([0-9a-f]{16})", messages[-1]["content"])[1]
        raw = "not JSON" if malformed else json.dumps({"request_id": rid, "tactic": tactic})
        bound_format = None if wrong_binding else response_format
        return {"text": raw, "finish_reason": "stop", "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                "client_binding": bind_response(request_binding(messages, arm, response_format=bound_format), raw)}
    return generate


def test_study_matches_prompts_and_budgets_but_checks_all_proofs(build):
    lab = build(study="json-schema", seed=223, generator=generator_for())
    report = lab.run()
    arms = report["cases"][0]["arms"]
    assert report["complete"] and report["model_calls"] == 6 and report["native_requests"] == 7
    assert lab.plan["study"] == "json-schema" and report["evidence_mode"] == "offline_fixture"
    for control, treatment in zip(arms["unconstrained"]["trials"], arms["schema-constrained"]["trials"]):
        assert control["messages"] == treatment["messages"]
        assert control["request_id"] == treatment["request_id"]
        assert control["reserved_tokens"] == treatment["reserved_tokens"]
        assert control["response_format"] is None
        assert treatment["response_format"] == leanstral.tactic_response_format(treatment["request_id"])
        assert "CURRENT_ATTEMPT_DATA" not in str(treatment["messages"])
        assert control["all_pin_valid"] is False and treatment["all_pin_valid"] is False
    assert all(a["strict_format_attempts"] == 3 and a["valid_attempts"] == 0 for a in arms.values())
    assert not report["promotion"] and not report["training"] and report["official_score"] is None
    with sqlite3.connect(lab.directory / "calls.sqlite") as db:
        inputs = [json.loads(row[0]) for row in db.execute("SELECT input FROM calls WHERE kind='model'")]
    assert sum(x["response_format"] is not None for x in inputs) == 3


@pytest.mark.parametrize("kwargs", [{"malformed": True}, {"tactic": "by\n  simp"}])
def test_ignored_schema_or_outer_by_still_rejected_no_salvage(build, kwargs):
    report = build(study="json-schema", generator=generator_for(**kwargs)).run()
    assert report["complete"] and report["model_calls"] == 6 and report["native_requests"] == 1
    for arm in report["cases"][0]["arms"].values():
        assert arm["strict_format_attempts"] == 0 and arm["valid_attempts"] == 0
        assert all(t["status"] == "FORMAT_REJECTED" for t in arm["trials"])


def test_schema_receipt_must_bind_decoding_options(build):
    report = build(study="json-schema", generator=generator_for(wrong_binding=True)).run()
    assert not report["complete"]
    trial = report["cases"][0]["arms"]["schema-constrained"]["trials"][0]
    assert trial["all_pin_valid"] is None
    assert trial["generation"]["error_type"] == "ClientBindingError"


def test_schema_study_still_requires_pinned_controls(build):
    report = build(study="json-schema", backend=Backend(control_outcome=Outcome.ERROR),
                   generator=lambda *a, **k: pytest.fail("model before controls")).run()
    assert not report["complete"] and report["model_calls"] == 0


@pytest.mark.parametrize("study", ["unknown", [], None])
def test_unknown_study_rejected(build, study):
    with pytest.raises(ValueError, match="study"):
        build(study=study)
