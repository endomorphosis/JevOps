from __future__ import annotations

import json

from jevops import llm_router, program, typesafe_inference
from jevops.outer import load_ipfs_accelerate_router, make_llm_router_generate


def test_default_router_is_in_tree_and_offline(monkeypatch) -> None:
    monkeypatch.delenv("JEVOPS_USE_EXTERNAL_ROUTER", raising=False)
    monkeypatch.delenv("JEVOPS_LLM_PROVIDER", raising=False)
    module = load_ipfs_accelerate_router()
    assert module is llm_router

    generate = make_llm_router_generate(
        router=module,
        provider="deterministic",
        model_name="jevops-test",
        verify_route=True,
    )
    response = json.loads(generate("return one closed JSON action"))
    assert response["action"] == "run"
    assert generate.last_route_attestation["actual_provider"] == "deterministic"
    assert generate.last_route_attestation["verified"] is True


def test_typesafe_protocol_is_available_without_external_checkout(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert typesafe_inference.typesafe_configured(environ={}) is False
    question = typesafe_inference.Choice(
        instructions="choose a safe candidate",
        criteria={"a": "verified", "b": "unverified"},
    )
    assert typesafe_inference.serialize_questions({"best": question}) == {
        "best": {
            "type": "choice",
            "instructions": "choose a safe candidate",
            "criteria": {"a": "verified", "b": "unverified"},
        }
    }


def test_datasets_projection_is_disabled_without_explicit_legacy_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("JEVOPS_USE_EXTERNAL_DEPS", raising=False)
    result = program.compile_datasets_ir({"nca": {"grid": {}}})
    assert result["ok"] is False
    assert result["reason"] == "external_dependency_disabled"
