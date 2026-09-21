from __future__ import annotations

import json
import shutil
from types import SimpleNamespace
from pathlib import Path

import pytest

from jevops.router_tuning import (
    RouterTuningConfig,
    _lean_compiler,
    parse_router_plan,
    tune_autoencoder_with_router,
)


def test_router_plan_is_bounded_and_rejects_unsafe_candidates() -> None:
    plan = parse_router_plan(
        json.dumps(
            {
                "strategies": ["drop-unused-haves", "run-python"],
                "candidates": [
                    {"ops": [{"op": "trivial"}]},
                    {"tactics": "sorry"},
                    {"ops": [{"op": "not_a_lean_operation"}]},
                ],
            }
        )
    )

    assert plan["ok"] is True
    assert plan["strategies"] == ["drop_unused_haves"]
    assert plan["unknown_strategies"] == ["run_python"]
    assert len(plan["candidates"]) == 1
    assert plan["rejected_candidates"] == 2


def test_router_loop_uses_gpt_luna_route_and_trains_from_verified_shortening() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def generate_text(prompt: str, **kwargs: object) -> str:
        calls.append((prompt, dict(kwargs)))
        return json.dumps(
            {
                "focus": "try a one-command closer",
                "strategies": ["drop_unused_haves", "closed_tree"],
                "candidates": [
                    {"kind": "ir_short", "ops": [{"op": "trivial"}]},
                    {"kind": "unsafe", "tactics": "sorry"},
                ],
            }
        )

    def compile_fn(source: str, problem: str = "") -> dict[str, object]:
        del problem
        body = source.split(":= by", 1)[-1].strip()
        return {
            "theorem_ok": body in {"trivial", "assumption", "simp", "decide", "exact h"},
            "token_count": len(source.split()),
        }

    memory: dict[str, object] = {"nca": {"grid": {}, "board_edges": []}}
    result = tune_autoencoder_with_router(
        memory,
        "theorem routed (h : True) : True := by\n  have hx : True := h\n  exact hx",
        problem="routed",
        compile_fn=compile_fn,
        router=SimpleNamespace(generate_text=generate_text),
        config=RouterTuningConfig(rounds=2, max_candidate_pool=20, max_router_candidates=4),
    )

    assert result["ok"] is True
    assert result["admission"] == "verified"
    assert result["best_body_tokens"] == 1
    assert result["best_body_tokens"] < result["source_body_tokens"]
    assert len(calls) == 2
    assert calls[0][1]["provider"] == "codex_cli"
    assert calls[0][1]["model_name"] == "gpt-5.6-luna"
    assert calls[0][1]["reasoning_effort"] == "high"
    assert calls[0][1]["allow_cross_provider_fallback"] is False
    assert memory["nca"]["autoencoder"]["training_state"]["step"] >= 1
    assert memory["nca"]["autoencoder"]["feedback"]["count"] > 0
    assert any(row["router"]["rejected_candidates"] == 1 for row in result["history"])


def test_router_loop_requires_a_proof_compiler_before_accepting() -> None:
    result = tune_autoencoder_with_router(
        {"nca": {}},
        "theorem no_oracle : True := by\n  trivial",
        router_generate=lambda _prompt: '{"candidates":[{"ops":[{"op":"trivial"}]}]}',
        config=RouterTuningConfig(rounds=1),
    )

    assert result["ok"] is False
    assert result["reason"] == "compile_fn_required"


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires the elan lean executable")
def test_router_loop_can_use_the_real_lean_compiler_for_multiple_rounds() -> None:
    result = tune_autoencoder_with_router(
        {"nca": {"grid": {}, "board_edges": []}},
        "theorem real_router (h : True) : True := by\n  have hx : True := h\n  exact hx",
        problem="real-router",
        compile_fn=_lean_compiler(project_root=Path("/tmp")),
        router_generate=lambda _prompt: '{"candidates":[{"ops":[{"op":"trivial"}]}]}',
        config=RouterTuningConfig(rounds=2, train=True),
    )

    assert result["ok"] is True
    assert result["best_body_tokens"] == 1
    assert len(result["history"]) == 2
