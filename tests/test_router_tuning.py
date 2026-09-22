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
    RouterTuningLoop,
    _lean_compiler,
    parse_router_plan,
    tune_autoencoder_with_router,
    _compact_row,
    _router_prompt,
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


def test_router_receives_compiler_failures_without_truncated_json_or_training_dump() -> None:
    failed = _compact_row({"id": "bad", "lake_ok": False, "origin": "logic:test", "compile": {
        "compile": {"exit_code": 1, "errors": [{"data": "unsolved goals: missing premise h"}]}}})
    assert "missing premise h" in failed["failure"]["message"]
    history = [{"round": 1, "candidates": [failed], "training": {"state": "x" * 100_000}}]
    prompt = _router_prompt(source="theorem test : True := by trivial", body="trivial", problem="test",
                            current={}, analysis={}, history=history, config=RouterTuningConfig())
    payload = json.loads(prompt.rsplit("\n", 1)[-1])
    assert payload["recent_rounds"][0]["failures"][0]["failure"]["exit_code"] == 1
    assert "missing premise h" in prompt and "training" not in payload["recent_rounds"][0]
    assert len(prompt) < RouterTuningConfig().max_prompt_chars
    short = _router_prompt(source="x" * 20_000, body="y" * 20_000, problem="test", current={}, analysis={},
                           history=history, config=RouterTuningConfig(max_prompt_chars=2500))
    # The final payload is a complete JSON object, even under a tight budget.
    json.loads(short.rsplit("\n", 1)[-1])
    assert len(short) <= 2500


def test_known_failures_do_not_consume_later_round_slots_or_persist_between_runs() -> None:
    source = "theorem test : True := by\n  trivial"
    calls = []
    loop = RouterTuningLoop({}, source, compile_fn=lambda s, **kw: calls.append(s) or {"theorem_ok": False},
                           router_generate=lambda _: "{}")
    first = []
    loop._push(first, set(), "rfl", origin="test", kind="test")
    assert len(first) == 1 and not first[0]["lake_ok"]
    later = []
    loop._push(later, set(), "rfl", origin="test", kind="test")
    assert not later and len(calls) == 1 and loop._known_failure_skips == 1
    fresh = RouterTuningLoop({}, source, compile_fn=lambda s, **kw: {"theorem_ok": True},
                            router_generate=lambda _: "{}")
    fresh._push(later, set(), "rfl", origin="test", kind="test")
    assert len(later) == 1 and later[0]["lake_ok"]  # Repaired tactics may be retried in a new run.


def test_requested_strategy_families_share_the_router_quota(monkeypatch) -> None:
    import jevops.router_tuning as rt

    def variants(name, body, rng, **kwargs):
        return [(f"{name}-{i}", f"exact proof_{name}_{i}", name) for i in range(8)]

    monkeypatch.setattr(rt, "_strategy_body", variants)
    source = "theorem test : True := by\n  trivial"
    loop = RouterTuningLoop({}, source, compile_fn=lambda s, **kw: {"theorem_ok": True},
                           router_generate=lambda _: "{}")
    rows = []
    loop._router_rows(parse_router_plan('{"strategies":["simp_set_reduce","branch_invariant"]}'),
                      rows, set(), source, max_new=2)
    assert [r["origin"] for r in rows] == ["router_strategy:simp_set_reduce", "router_strategy:branch_invariant"]


def test_training_rolls_back_invalid_predictions_even_when_soft_metrics_improve(monkeypatch) -> None:
    source = "theorem rollback (h : True) : True := by\n  have unused : True := True.intro\n  exact h"
    memory = {}
    loop = RouterTuningLoop(memory, source, compile_fn=lambda s, **kw: {"theorem_ok": True},
                           router_generate=lambda _: "{}")
    winner = loop._row("theorem rollback (h : True) : True := by\n  exact h", origin="test", kind="test")
    diagnostics = loop._model_diagnostics
    phases = []

    def invalid_after(model, example, *, phase):
        phases.append(phase)
        report = diagnostics(model, example, phase=phase)
        if phase == "after":
            report["loss"].update(cross_entropy=0.0, cosine_similarity=1.0)
            report["row"].update(lake_ok=False, compile={"theorem_ok": False, "compile": {
                "exit_code": 1, "errors": [{"data": "missing live binding"}]}})
        return report

    monkeypatch.setattr(loop, "_model_diagnostics", invalid_after)
    result = loop._train(winner, [winner])
    assert result["ok"] and not result["trained"] and not result["update_accepted"]
    assert result["step"] == 0 and memory["nca"]["autoencoder"]["training_state"]["step"] == 0
    assert phases == ["before", "after", "rollback"]
    rejection = result["update_rejection"]
    assert rejection["verifier_regression"] and rejection["cross_entropy_rise"] < 0
    assert "missing live binding" in rejection["attempted_prediction"]["failure"]["message"]
    assert result["model_prediction_after"]["lake_ok"]


def test_opt_in_binding_classifier_trains_from_a_verified_strict_cut() -> None:
    prefix = "theorem binding_train (p : Prop) (h : p) : p := by\n"
    target = prefix + "  have proof : p := h\n  exact proof"
    source = prefix + "  have unused : True := True.intro\n  have proof : p := h\n  exact proof"
    memory = {}
    loop = RouterTuningLoop(memory, source, compile_fn=lambda s, **kw: {"theorem_ok": "have proof" in s},
                           router_generate=lambda _: "{}", config=RouterTuningConfig(train_binding_policy=True))
    winner = loop._row(target, origin="test", kind="test")
    result = loop._train(winner, [winner])
    assert result["ok"] and result["trained"] and result["binding_updates"] == 1
    assert memory["nca"]["autoencoder"]["training_state"]["binding_steps"] == 1
    assert result["model_prediction_after"]["binding_policy"]["mode"] == "learned_binding_keep"


@pytest.mark.parametrize("attempted_bce", [.5, None])
def test_training_rolls_back_binding_loss_regression_or_lost_coverage(monkeypatch, attempted_bce) -> None:
    prefix = "theorem rollback_binding (p : Prop) (h : p) : p := by\n"
    source = prefix + "  have unused : True := True.intro\n  have proof : p := h\n  exact proof"
    memory = {}
    loop = RouterTuningLoop(memory, source, compile_fn=lambda s, **kw: {"theorem_ok": "have proof" in s},
                           router_generate=lambda _: "{}", config=RouterTuningConfig(train_binding_policy=True))
    winner = loop._row(prefix + "  have proof : p := h\n  exact proof", origin="test", kind="test")
    diagnostics = loop._model_diagnostics

    def injected_loss(model, example, *, phase):
        report = diagnostics(model, example, phase=phase)
        report["loss"]["binding_cross_entropy"] = attempted_bce if phase == "after" else .1
        if phase == "after":
            report["loss"].update(cross_entropy=0.0, cosine_similarity=1.0)
        return report

    monkeypatch.setattr(loop, "_model_diagnostics", injected_loss)
    result = loop._train(winner, [winner])
    assert not result["update_accepted"] and not result["trained"]
    assert memory["nca"]["autoencoder"]["training_state"]["binding_steps"] == 0
    assert result["update_rejection"]["binding_coverage_lost"] == (attempted_bce is None)


def test_raw_binding_proposal_cannot_bypass_compiler_admission() -> None:
    model = ae.LeanIRAutoencoder()
    model.state["binding_steps"] = 1
    model.state["binding_weights"]["bias"] = -10.0  # Deliberately unsafe deletion policy.
    source = "theorem raw_gate (p : Prop) (h : p) : p := by\n  have proof : p := h\n  exact proof"
    memory = {"nca": {"autoencoder": {"training_state": model.to_dict()}}}
    loop = RouterTuningLoop(memory, source, compile_fn=lambda s, **kw: {"theorem_ok": "have proof" in s},
                           router_generate=lambda _: "{}")
    raw = next(ir for ir in loop._autoencoder_irs(source) if ir.get("proposal_policy") == "binding_raw")
    assert not raw["dependency_guard"]["enabled"] and len(raw["ops"]) == 1
    rows = []
    loop._push_ir(rows, set(), raw, origin="autoencoder:binding_raw", kind="test")
    assert len(rows) == 1 and rows[0]["admission"] == "rejected"
    assert rows[0]["reward"] == 0.0 and rows[0]["minimality_reward"] == 0.0


def test_trained_binding_proposal_is_assessed_before_local_candidates_fill_pool(monkeypatch) -> None:
    model = ae.LeanIRAutoencoder()
    model.state["binding_steps"] = 1
    model.state["binding_weights"]["bias"] = -10.0
    source = "theorem binding_slot (p : Prop) (h : p) : p := by\n  have proof : p := h\n  exact proof"
    memory = {"nca": {"autoencoder": {"training_state": model.to_dict()}}}
    loop = RouterTuningLoop(memory, source, compile_fn=lambda s, **kw: {"theorem_ok": "have proof" in s},
                           router_generate=lambda _: "{}", config=RouterTuningConfig(
                               rounds=1, train=False, max_candidate_pool=12, hammer_sweep=False,
                               logic_reductions=False, teacher_replay=False))
    monkeypatch.setattr(loop, "_local_rows", lambda *a: [(f"local-{i}", f"exact local_{i}", "test") for i in range(20)])
    result = loop.run()
    rows = result["history"][0]["candidates"]
    raw = [r for r in rows if r["origin"] == "autoencoder:binding_raw"]
    assert len(raw) == 1 and not raw[0]["lake_ok"]
    assert len(rows) <= 12 and result["ok"]


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


def test_hypothesis_refactor_strategy_expands_into_closed_candidates() -> None:
    plan = parse_router_plan('{"strategies":["hypothesis_refactor"]}')
    assert plan["strategies"] == ["hypothesis_refactor"]
    variants = tactics.hypothesis_refactor_variants("  simp at h\n  exact h\n", cap=8)
    assert variants
    assert all("hypothesis_refactor" in ops for _kind, _body, ops in variants)


def test_llm_hypothesis_strategy_enters_the_compiler_gated_training_loop() -> None:
    source = "theorem hypothesis_loop (h : True) : True := by\n  have hx : True := h\n  exact hx"
    result = tune_autoencoder_with_router(
        {"nca": {"grid": {}, "board_edges": []}},
        source,
        problem="hypothesis_loop",
        compile_fn=lambda candidate, problem="": {"theorem_ok": True, "token_count": len(candidate.split())},
        router_generate=lambda _prompt: '{"strategies":["hypothesis_refactor"]}',
        config=RouterTuningConfig(rounds=1, max_candidate_pool=16, max_router_candidates=2),
    )
    assert any(
        "hypothesis_refactor" in str(row.get("origin") or "")
        for row in result["history"][0]["candidates"]
    )


def test_hammer_sweep_and_teacher_composition_are_bounded() -> None:
    sweep = tactics.hammer_sweep_variants("  exact h\n", cap=12)
    assert 0 < len(sweep) <= 12
    assert any("shortcut" in ops for _kind, _body, ops in sweep)

    composed = tactics.compose_tactic_bodies(
        "  intro h\n  exact h\n",
        "  rintro h\n  assumption\n",
        cap=16,
    )
    assert composed
    assert any("assumption" in body for _kind, body, _ops in composed)
    assert any("interleave" in kind or "concat" in kind for kind, _body, _ops in composed)

    multi_arm = tactics.compose_tactic_bodies(
        "  case left =>\n    simp\n  case middle =>\n    exact h\n  case right =>\n    rfl\n",
        "  case left =>\n    aesop\n  case middle =>\n    assumption\n  case right =>\n    decide\n",
        cap=8,
    )
    assert any("multi_splice" in kind for kind, _body, _ops in multi_arm)
    assert any("mixed_splice" in kind for kind, _body, _ops in multi_arm)

    crossovers = ae.crossover_lean_ir(
        ae.encode_lean_ir("intro h\nexact h"),
        ae.encode_lean_ir("intro h\nassumption"),
        limit=8,
    )
    assert crossovers
    assert all(row["schema"] == ae.LEAN_IR_SCHEMA for row in crossovers)
    assert any(
        len(row.get("ops") or ()) >= 3
        for row in crossovers
    )


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
            # Exercise the branch-aware scheduler: two historical seeds must
            # still leave room for composition, IR crossover, and hammer rows.
            max_candidate_pool=12,
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
    assert search["ir_crossover_candidates"] > 0
    assert search["branch_budgets"]["composition"] >= 1
    assert search["branch_budgets"]["hammer"] >= 1
    origins = [row["origin"] for row in result["history"][0]["candidates"]]
    assert any(str(origin).startswith("composition:") for origin in origins)
    assert any(str(origin).startswith("hammer") for origin in origins)
    composition_pairs = {
        tuple(row.get("composition_parent_ids") or ())
        for row in result["history"][0]["candidates"]
        if str(row.get("origin") or "").startswith("composition:")
    }
    assert len(composition_pairs) >= 2
    assert any(row.get("kind") == "verified_composition" for row in result["history"][0]["rules"])
    assert any(
        row.get("kind") in {"hammer_sweep", "hammer_strategy"}
        for row in result["history"][0]["rules"]
    )
    assert any(row.get("kind") == "verified_composition" for row in memory["nca"]["router_rules"])


def test_elite_composition_revisits_newly_admitted_local_teachers() -> None:
    source = "theorem elite (h : True) : True := by\n  have hx : True := h\n  exact hx"
    result = tune_autoencoder_with_router(
        {"nca": {"grid": {}, "board_edges": []}},
        source,
        problem="elite_composition",
        compile_fn=lambda candidate, problem="": {
            "theorem_ok": True,
            "token_count": len(candidate.split()),
        },
        router_generate=lambda _prompt: '{"strategies":["goal_directed"]}',
        seed_candidates=[
            {"body": "  exact h\n", "provenance": "git_history", "commit": "elite-a"},
            {"body": "  assumption\n", "provenance": "git_history", "commit": "elite-b"},
        ],
        config=RouterTuningConfig(
            rounds=1,
            max_candidate_pool=48,
            max_router_candidates=2,
            max_composed_candidates=2,
            max_elite_composed_candidates=4,
            max_hammer_candidates=2,
            max_composition_sources=5,
            n_variations=1,
        ),
    )

    search = result["history"][0]["search"]
    assert search["elite_composition_triggered"] is True
    assert search["elite_composed_candidates"] > 0
    assert any(
        str(row.get("origin") or "").startswith("elite_composition:")
        for row in result["history"][0]["candidates"]
    )
    assert any(row.get("kind") == "elite_composition" for row in result["history"][0]["rules"])


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
