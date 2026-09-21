from __future__ import annotations

import json
import shutil
from types import SimpleNamespace
from pathlib import Path

import pytest

from jevops import autoencoder as ae
from jevops import tactics
from jevops.outer import make_llm_router_generate
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


def test_strict_router_adapter_rejects_an_unexpected_provider_trace() -> None:
    class TracedRouter:
        __name__ = "ipfs_accelerate_py.llm_router"

        @staticmethod
        def generate_text(prompt: str, **kwargs: object) -> str:
            del prompt, kwargs
            return '{"candidates":[{"tactic":"by trivial"}]}'

        @staticmethod
        def get_last_generation_trace() -> dict[str, str]:
            return {
                "effective_provider_name": "openai",
                "effective_model_name": "gpt-5.6-luna",
            }

    generate = make_llm_router_generate(
        router=TracedRouter,
        model_name="gpt-5.6-luna",
        provider="codex_cli",
        verify_route=True,
    )
    with pytest.raises(RuntimeError, match="route mismatch"):
        generate("return JSON")
    assert generate.last_route_attestation["verified"] is False


def test_router_plan_accepts_compact_singular_tactic_field() -> None:
    plan = parse_router_plan('{"tactics":"by trivial"}')
    assert plan["ok"] is True
    assert plan["candidates"][0]["tactics"] == "trivial"


def test_router_plan_accepts_new_structural_ir_operations() -> None:
    plan = parse_router_plan(
        json.dumps(
            {
                "candidates": [
                    {
                        "kind": "structural_shortcut",
                        "ops": [
                            {"op": "rintro", "args": ["h"]},
                            {"op": "rcases", "args": ["h with ⟨hx, hy⟩"]},
                            {"op": "solve_by_elim"},
                        ],
                    }
                ]
            }
        )
    )

    assert plan["ok"] is True
    assert plan["rejected_candidates"] == 0
    assert [row["op"] for row in plan["candidates"][0]["ops"]] == [
        "rintro",
        "rcases",
        "solve_by_elim",
    ]


def test_hammer_sweep_and_teacher_composition_are_bounded() -> None:
    sweep = tactics.hammer_sweep_variants("  exact h\n", cap=12)
    assert 0 < len(sweep) <= 12
    assert any("shortcut" in ops for _kind, _body, ops in sweep)

    composed = tactics.compose_tactic_bodies(
        "  intro h\n  exact h\n",
        "  rintro h\n  assumption\n",
        cap=8,
    )
    assert composed
    assert any("assumption" in body for _kind, body, _ops in composed)

    crossovers = ae.crossover_lean_ir(
        ae.encode_lean_ir("intro h\nexact h"),
        ae.encode_lean_ir("intro h\nassumption"),
        limit=8,
    )
    assert crossovers
    assert all(row["schema"] == ae.LEAN_IR_SCHEMA for row in crossovers)


def test_router_loop_records_hammer_and_verified_composition_rules() -> None:
    source = "theorem composed (h : True) : True := by\n  have hx : True := h\n  exact hx"
    memory: dict[str, object] = {"nca": {"grid": {}, "board_edges": []}}

    def compile_fn(candidate: str, problem: str = "") -> dict[str, object]:
        del problem
        return {"theorem_ok": True, "token_count": len(candidate.split())}

    result = tune_autoencoder_with_router(
        memory,
        source,
        problem="composed",
        compile_fn=compile_fn,
        seed_candidates=[
            {"body": "  intro h\n  exact h\n", "provenance": "git_history", "commit": "seed-a"},
            {"body": "  rintro h\n  assumption\n", "provenance": "git_history", "commit": "seed-b"},
        ],
        router_generate=lambda _prompt: "{}",
        config=RouterTuningConfig(
            rounds=1,
            max_candidate_pool=32,
            max_composed_candidates=4,
            max_hammer_candidates=4,
            max_composition_sources=4,
            max_tactic_lines=1,
            n_variations=2,
        ),
    )

    search = result["history"][0]["search"]
    assert search["composed_candidates"] > 0
    assert search["hammer_candidates"] > 0
    origins = [row["origin"] for row in result["history"][0]["candidates"]]
    assert any(str(origin).startswith("composition:") for origin in origins)
    assert any(str(origin).startswith("hammer") for origin in origins)
    assert any(row.get("kind") == "verified_composition" for row in result["history"][0]["rules"])
    assert any(
        row.get("kind") in {"hammer_sweep", "hammer_strategy"}
        for row in result["history"][0]["rules"]
    )
    assert any(row.get("kind") == "verified_composition" for row in memory["nca"]["router_rules"])


def test_outer_design_directive_reaches_inner_router_prompt() -> None:
    prompts: list[str] = []

    def generate_text(prompt: str, **_kwargs: object) -> str:
        prompts.append(prompt)
        return "{}"

    result = tune_autoencoder_with_router(
        {"nca": {"grid": {}, "board_edges": []}},
        "theorem directed : True := by\n  trivial",
        problem="directed",
        compile_fn=lambda source, problem="": {"theorem_ok": True, "token_count": len(source.split())},
        router=SimpleNamespace(generate_text=generate_text),
        design_hint={"name": "directed", "family": "search_space", "strategy": "closed_edits"},
        config=RouterTuningConfig(rounds=1),
    )

    assert result["ok"] is True
    assert prompts
    assert '"outer_design_directive"' in prompts[0]
    assert '"strategy":"closed_edits"' in prompts[0]


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
    first_training = result["history"][0]["training"]
    assert "candidate_target_loss" in first_training
    assert first_training["loss"]["ir_exact_match"] == 0.0
    assert first_training["loss"]["cosine_similarity"] < first_training["candidate_target_loss"]["cosine_similarity"]
    assert first_training["candidate_target_loss"]["ir_exact_match"] == 1.0
    assert first_training["model_prediction_after"]["body_tokens"] > result["best_body_tokens"]
    assert result["model_body_tokens_after"] == first_training["model_prediction_after"]["body_tokens"]
    assert result["model_body_tokens_after"] > result["best_body_tokens"]
    assert first_training["teacher_example_count"] >= 1
    assert first_training["rule_examples"]
    assert memory["nca"]["router_rules"]
    assert any(row.get("training_eligible") for row in memory["nca"]["router_rules"])


def test_verified_teacher_seed_preserves_layout_and_trains_separately() -> None:
    """A shorter refactor may teach the model only after a compiler re-gate."""

    source = "theorem seeded (h : True) : True := by\n  have hx : True := h\n  exact hx"
    teacher = "  intro x\n  exact h\n"

    def compile_fn(candidate: str, problem: str = "") -> dict[str, object]:
        del problem
        body = candidate.split(":= by", 1)[-1].strip()
        return {
            "theorem_ok": body == "intro x\n  exact h",
            "token_count": len(candidate.split()),
        }

    result = tune_autoencoder_with_router(
        {"nca": {"grid": {}, "board_edges": []}},
        source,
        problem="seeded",
        compile_fn=compile_fn,
        seed_candidates=[teacher],
        router_generate=lambda _prompt: "{}",
        config=RouterTuningConfig(rounds=1, max_candidate_pool=8),
    )

    assert result["ok"] is True
    assert result["best_body_tokens"] == 4
    winner = result["history"][0]["round_winner"]
    assert winner["origin"] == "verified_seed"
    training = result["history"][0]["training"]
    assert training["candidate_target_loss"]["ir_exact_match"] == 1.0
    assert training["loss"]["ir_exact_match"] == 0.0
    assert result["model_body_tokens_after"] > result["best_body_tokens"]


def test_historical_teacher_metadata_survives_admission_and_training() -> None:
    source = "theorem historical_seeded (h : True) : True := by\n  have hx : True := h\n  exact hx"
    memory: dict[str, object] = {"nca": {"grid": {}, "board_edges": []}}

    def compile_fn(candidate: str, problem: str = "") -> dict[str, object]:
        del problem
        body = candidate.split(":= by", 1)[-1].strip()
        return {"theorem_ok": body == "trivial", "token_count": len(candidate.split())}

    result = tune_autoencoder_with_router(
        memory,
        source,
        problem="historical_seeded",
        compile_fn=compile_fn,
        router_generate=lambda _prompt: "{}",
        seed_candidates=[
            {
                "body": "  trivial\n",
                "provenance": "git_history",
                "commit": "5eec",
                "path": "random-best-historical_seeded-1.lean",
                "claimed_tokens": 1,
                "actual_tokens": 1,
                "body_digest": "seed-digest",
            }
        ],
        config=RouterTuningConfig(rounds=1, max_candidate_pool=8),
    )
    winner = result["history"][0]["round_winner"]
    assert winner["origin"] == "verified_seed"
    assert winner["seed_provenance"] == "git_history"
    assert winner["claimed_tokens"] == 1
    assert result["history"][0]["training"]["teacher_example_count"] >= 1
    assert any(
        row.get("training_eligible") and row.get("commit") == "5eec"
        for row in memory["nca"]["router_rules"]
    )


def test_verified_teacher_replay_is_recompiled_before_a_later_round() -> None:
    source = "theorem replayed (h : True) : True := by\n  have hx : True := h\n  exact hx"
    memory: dict[str, object] = {"nca": {"grid": {}, "board_edges": []}}
    compiled: list[str] = []

    def compile_fn(candidate: str, problem: str = "") -> dict[str, object]:
        del problem
        compiled.append(candidate)
        return {"theorem_ok": True, "token_count": len(candidate.split())}

    config = RouterTuningConfig(
        rounds=1,
        max_candidate_pool=12,
        max_hammer_candidates=1,
        max_composed_candidates=1,
        max_composition_sources=2,
        n_variations=1,
    )
    first = tune_autoencoder_with_router(
        memory,
        source,
        problem="replayed",
        compile_fn=compile_fn,
        seed_candidates=["  trivial\n"],
        router_generate=lambda _prompt: "{}",
        config=config,
    )
    assert first["history"][0]["training"]["teacher_buffer_added"] >= 1
    assert memory["nca"]["autoencoder"]["teacher_buffer"]

    first_call_count = len(compiled)
    second = tune_autoencoder_with_router(
        memory,
        source,
        problem="replayed",
        compile_fn=compile_fn,
        router_generate=lambda _prompt: "{}",
        config=config,
    )

    assert second["history"][0]["search"]["replay_teachers"] >= 1
    assert any(row["origin"] == "teacher_replay" for row in second["history"][0]["candidates"])
    assert any(":= by\n  trivial" in candidate for candidate in compiled[first_call_count:])


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
