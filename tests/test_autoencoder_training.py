from __future__ import annotations

from types import SimpleNamespace

from jevops import autoencoder as ae


def _rows(n: int = 40) -> list[dict[str, str]]:
    patterns = (
        "intro x exact h",
        "simp [foo]",
        "rw [h] simp",
        "constructor exact h",
        "omega",
        "rfl",
        "cases h exact h",
        "norm_num",
    )
    return [{"id": f"sample-{i}", "text": patterns[i % len(patterns)]} for i in range(n)]


def test_v2_ir_preserves_goal_arguments_and_is_non_admitting() -> None:
    ir = ae.encode_lean_ir("theorem keep (h : P) : Q := by\n  intro x\n  exact h")
    assert ir["schema"] == ae.LEAN_IR_SCHEMA
    assert ir["ident"] == "keep"
    assert ir["goal"] == "Q"
    assert ir["binders"] == ["(h : P)"]
    assert ir["ops"] == [{"op": "intro", "args": ["x"]}, {"op": "exact", "args": ["h"]}]
    rendered = ae.decode_lean_ir(ir)
    assert "(h : P)" in rendered
    assert "exact h" in rendered
    assert "sorry" not in rendered.lower()
    assert "admit" not in rendered.lower()

    compact = ae.encode_lean_ir("intro simp trivial")
    assert [row["op"] for row in compact["ops"]] == ["intro", "simp", "trivial"]


def test_structural_ir_preserves_case_bullets_and_branches() -> None:
    source = """theorem shaped (xs : List Nat) : True := by
  induction xs <;> simp_all
  case nil =>
    trivial
  case cons x xs ih =>
    cases ih with
    | left h => exact h
    | right h => exact h
"""
    packed = ae.encode_lean_ir(source)
    rendered = ae.decode_lean_ir(packed)
    assert any(node.get("kind") == "control" for node in packed["script"])
    assert any(node.get("kind") == "branch" for node in packed["script"])
    assert "induction xs <;> simp_all" in rendered
    assert "case cons x xs ih =>" in rendered
    assert "| left h => exact h" in rendered
    assert "sorry" not in rendered.lower()
    assert packed["source_copy"] is False

    example = ae.coerce_training_example({"id": "shaped", "text": source})
    predicted = ae.LeanIRAutoencoder().predict_ir(source, source_ir=example.source_ir)
    assert "case cons x xs ih =>" in ae.decode_lean_ir(predicted)


def test_losses_are_finite_and_training_is_sparse_and_deterministic() -> None:
    rows = _rows()
    config = ae.AutoencoderConfig(
        seed=23,
        learning_rate=0.06,
        warmup_steps=0,
        validation_fraction=0.15,
        canary_fraction=0.15,
        holdout_fraction=0.15,
    )
    first = ae.train_autoencoder(rows, config=config, epochs=4, batch_size=8)
    second = ae.train_autoencoder(rows, config=config, epochs=4, batch_size=8)

    assert first["ok"] is True
    assert first["state_digest"] == second["state_digest"]
    assert first["state"]["step"] > 0
    assert first["after"]["train"]["cross_entropy"] <= first["before"]["train"]["cross_entropy"]
    assert first["holdout"]["accessed"] is False
    assert set(first["split_counts"]) == {"train", "validation", "canary", "holdout"}

    assignments = first["manifest"]["assignments"]
    assert not ({key for key, value in assignments.items() if value == "train"} & {key for key, value in assignments.items() if value == "holdout"})
    holdout = ae.evaluate_frozen_holdout(first["state"], rows, manifest=first["manifest"])
    assert holdout["ok"] is True
    assert holdout["holdout_accessed"] is True
    assert holdout["tuning_allowed_after_access"] is False


def test_paired_refactor_evaluation_does_not_decode_from_target_ir() -> None:
    example = ae.coerce_training_example(
        {
            "id": "paired-refactor",
            "text": "intro x",
            "source_ir": ae.encode_lean_ir("intro x"),
            "target_ir": ae.encode_lean_ir("exact h"),
        }
    )
    assert [op for op, _args in example.target_ops] == ["exact"]
    assert [row["op"] for row in example.source_ir["ops"]] == ["intro"]

    report = ae.evaluate_model(ae.LeanIRAutoencoder(), [example])
    assert report["rows"][0]["loss"]["ir_exact_match"] == 0.0


def test_manifest_tampering_is_rejected_and_lr_has_warmup_decay() -> None:
    rows = _rows(20)
    config = ae.AutoencoderConfig(seed=4, warmup_steps=4, decay_steps=8)
    manifest = ae.build_canary_manifest(rows, config=config)
    assert ae.validate_canary_manifest(manifest, rows)["ok"] is True
    tampered = manifest.to_dict()
    tampered["assignments"][rows[0]["id"]] = "holdout" if tampered["assignments"][rows[0]["id"]] != "holdout" else "train"
    assert ae.validate_canary_manifest(tampered, rows)["ok"] is False

    changed_target = list(rows)
    changed_target[0] = {
        **changed_target[0],
        "target_ir": ae.encode_lean_ir("exact changed_target"),
    }
    assert ae.validate_canary_manifest(manifest, changed_target)["ok"] is False

    assert ae.learning_rate_for_step(config, 0) < ae.learning_rate_for_step(config, 3)
    assert ae.learning_rate_for_step(config, 20) < ae.learning_rate_for_step(config, 4)


def test_typesafe_reward_adapter_is_soft_and_verifier_can_be_hard() -> None:
    class FakeClient:
        def system_one(self, state, questions):
            assert state["task"] == "lean_ir_autoencoder_candidate_rank"
            assert "best" in questions and "unsafe" in questions
            return SimpleNamespace(
                choices={"best": SimpleNamespace(choice="v1", confidence=0.8)},
                nouls={"unsafe": SimpleNamespace(noul=0.1)},
                model="fixture-typesafe",
            )

    result = ae.typesafe_rank_variations(
        [{"id": "v0", "ir_cosine_m": 900}, {"id": "v1", "ir_cosine_m": 950}],
        client=FakeClient(),
    )
    assert result["ok"] is True
    assert result["choice"] == "v1"
    assert result["reward"] == 0.72

    rejected = ae.score_candidate({"cosine_m": 1000, "ir_cosine_m": 1000, "ce_m": 0, "ir_ce_m": 0, "lake_ok": False})
    assert rejected["admission"] == "rejected"
    assert rejected["reward"] == 0.0


def test_nca_feedback_is_auxiliary_and_records_verified_outcomes() -> None:
    memory = {
        "nca": {
            "grid": {
                "ptr://skill/port_autoencoder": {
                    "energy": 0.8,
                    "wins": 3,
                    "losses": 1,
                    "help": 1.0,
                    "unsafe": 0.0,
                },
                "ptr://residual/intro": {"energy": 0.7, "help": 0.5, "unsafe": 0.0},
            },
            "board_edges": [["ptr://skill/port_autoencoder", "ptr://residual/intro"]],
        }
    }
    example = ae.coerce_training_example({"id": "nca-row", "text": "intro x"})
    feedback = ae.nca_feedback_for_example(memory, example)
    assert feedback.active is True
    assert 0.0 <= feedback.reward <= 1.0
    assert "ptr://skill/port_autoencoder" in feedback.cells

    recorded = ae.record_autoencoder_nca_feedback(
        memory,
        problem="P",
        reward=0.91,
        theorem_ok=True,
        tokens=7,
    )
    assert recorded["ok"] is True
    assert memory["nca"]["autoencoder"]["feedback"]["count"] == 1
    assert memory["nca"]["grid"]["ptr://skill/port_autoencoder"]["wins"] == 4
    assert recorded["feedback"]["nca_tick"] == 1
    assert recorded["feedback"]["nca_cells"] >= 1
    assert memory["nca"]["tick"] == 1
    assert ["ptr://skill/port_autoencoder", "ptr://theorem/P"] in memory["nca"]["board_edges"]


def test_router_rule_feedback_is_auditable_and_nca_connected() -> None:
    memory: dict = {"nca": {"grid": {}, "board_edges": []}}
    proposal = ae.record_autoencoder_rule_feedback(
        memory,
        problem="P",
        rule={
            "kind": "router_ir",
            "ops": [{"op": "simp"}],
            "origin": "llm_router_ir",
            "rationale_digest": "abc",
        },
    )
    assert proposal["ok"] is True
    rule_id = proposal["rule_id"]
    assert rule_id.startswith("rule-")
    assert memory["nca"]["router_rules"][0]["training_eligible"] is False

    observed = ae.record_autoencoder_rule_feedback(
        memory,
        problem="P",
        rule={"rule_id": rule_id, "kind": "router_ir", "ops": [{"op": "simp"}]},
        outcome={"lake_ok": True, "body_tokens": 3, "reward": 0.9},
    )
    assert observed["record"]["training_eligible"] is True
    assert observed["record"]["verified_count"] == 1
    assert f"ptr://rule/{rule_id}" in memory["nca"]["grid"]
    assert ["ptr://skill/port_autoencoder", f"ptr://rule/{rule_id}"] in memory["nca"]["board_edges"]

    example = ae.coerce_training_example(
        {"id": "rule-example", "text": "simp", "rule_id": rule_id}
    )
    feedback = ae.nca_feedback_for_example(memory, example)
    assert f"ptr://rule/{rule_id}" in feedback.cells


def test_fuzzy_typesafe_prover_is_typed_soft_advice_only() -> None:
    class FakeClient:
        def system_one(self, state, questions):
            assert state["constraints"]["lake_is_proof_authority"] is True
            assert set(questions) == {"best", "semantic", "unsafe", "solves_goal"}
            return SimpleNamespace(
                choices={"best": SimpleNamespace(choice="v0", confidence=0.9)},
                scores={"semantic": SimpleNamespace(score=3.0)},
                nouls={
                    "unsafe": SimpleNamespace(noul=0.1),
                    "solves_goal": SimpleNamespace(noul=0.8),
                },
                model="fixture-typesafe",
                usage={"total_tokens": 42},
            )

    result = ae.typesafe_fuzzy_prove(
        "theorem P",
        [{"id": "v0", "ir_ops": ["exact"], "n_tokens": 3}, {"id": "v1", "ir_ops": ["simp"], "n_tokens": 4}],
        client=FakeClient(),
    )
    assert result["ok"] is True
    assert result["choice"] == "v0"
    assert result["verified"] is False
    assert result["requires_lake"] is True
    assert result["candidate_rewards"]["v0"] > result["candidate_rewards"]["v1"]

    integrated = ae.refactor_smallest(
        {"nca": {}},
        "intro simp",
        problem="theorem P",
        compile_fn=lambda lean, problem="": {"theorem_ok": True, "token_count": len(lean.split())},
        typesafe_client=FakeClient(),
        train=False,
    )
    assert integrated["admission"] == "verified"
    assert integrated["fuzzy_prover"]["verified"] is False


def test_minimality_only_prefers_shorter_candidates_after_verification() -> None:
    short = {"cosine_m": 900, "ir_cosine_m": 900, "ce_m": 100, "ir_ce_m": 100, "lake_ok": True, "n_tokens": 4, "source_tokens": 10, "source_ops": 3, "ir_ops": 1}
    long = {"cosine_m": 900, "ir_cosine_m": 900, "ce_m": 100, "ir_ce_m": 100, "lake_ok": True, "n_tokens": 8, "source_tokens": 10, "source_ops": 3, "ir_ops": 3}
    short_score = ae.score_candidate(short, minimality_reward=ae.minimality_score(short))
    long_score = ae.score_candidate(long, minimality_reward=ae.minimality_score(long))
    assert short_score["admission"] == "verified"
    assert short_score["reward"] > long_score["reward"]


def test_sparse_shard_states_merge_without_corpus_materialization() -> None:
    config = ae.AutoencoderConfig(seed=5, warmup_steps=0)
    first = ae.LeanIRAutoencoder(config=config)
    second = ae.LeanIRAutoencoder(config=config)
    first.train_batch([ae.coerce_training_example("intro x")])
    second.train_batch([ae.coerce_training_example("simp")])

    merged = ae.merge_model_states([first.to_dict(), second.to_dict()], config=config)
    merged_reverse = ae.merge_model_states([second.to_dict(), first.to_dict()], config=config)
    assert merged["step"] == 2
    assert merged["schema"] == ae.MODEL_SCHEMA
    assert ae.LeanIRAutoencoder.from_dict(merged).to_dict() == merged
    assert merged == merged_reverse


def test_malformed_checkpoint_is_sanitized_without_admitting_arbitrary_state() -> None:
    model = ae.LeanIRAutoencoder.from_dict(
        {
            "schema": ae.MODEL_SCHEMA,
            "step": "not-an-int",
            "op_bias": ["not-a-map"],
            "latent_bias": None,
            "transition": "bad",
            "feature_op": None,
            "feature_latent": {"1": "bad"},
        }
    )
    assert model.step == 0
    assert len(model.predict_latent("intro")) == 16
    assert model.predict_ir("intro")["schema"] == ae.LEAN_IR_SCHEMA


def test_teach_roundtrip_verifies_all_current_candidates_before_admission() -> None:
    memory: dict = {"nca": {}}
    calls: list[str] = []

    def compile_fn(lean: str, problem: str = ""):
        calls.append(lean)
        return {"theorem_ok": "sorry" not in lean.lower(), "token_count": len(lean.split())}

    result = ae.teach_roundtrip(
        memory,
        "intro simp trivial",
        problem="fixture",
        compile_fn=compile_fn,
        n_variations=4,
    )
    assert result["lake_ok"] is True
    assert result["admission"] == "verified"
    assert 1 <= len(calls) <= 4
    assert result["training"]["sample_count"] == 1
    assert result["training"]["refactor_target"] is True
    assert result["training"]["target_ops"] < result["training"]["source_ops"]
    # The loss must use an independent model decode, not the verified teacher
    # candidate; otherwise IR exact-match/cosine can be perfect by construction.
    assert result["training"]["model_prediction_ops"] == result["training"]["source_ops"]
    assert result["training"]["loss"]["ir_exact_match"] == 0.0
    assert result["training"]["loss"]["cosine_similarity"] < 1.0
    assert memory["nca"]["autoencoder"]["training_state"]["step"] == 1


def test_unverified_shorter_candidate_cannot_become_training_target() -> None:
    memory: dict = {"nca": {}}

    def compile_fn(lean: str, problem: str = ""):
        del lean, problem
        return {"theorem_ok": False}

    result = ae.refactor_smallest(
        memory,
        "theorem guarded (h : True) : True := by\n  exact h",
        problem="guarded",
        compile_fn=compile_fn,
        n_variations=8,
        train=True,
    )
    assert result["lake_ok"] is False
    assert result["training"]["refactor_target"] is False
    assert result["training"]["target_ops"] == result["training"]["source_ops"]


def test_invalid_shorter_candidate_cannot_beat_verified_longer_candidate() -> None:
    memory: dict = {"nca": {}}

    def compile_fn(lean: str, problem: str = ""):
        del problem
        # Simulate a verifier rejecting the shortest probe while accepting a
        # longer proof.  This isolates the hard-admission rule from Lean's
        # particular diagnostics.
        body = lean.split(":= by", 1)[-1].strip()
        return {
            "theorem_ok": body == "exact h",
            "token_count": len(lean.split()),
        }

    result = ae.refactor_smallest(
        memory,
        "theorem hard_gate (h : True) : True := by\n  exact h",
        problem="hard-gate",
        compile_fn=compile_fn,
        n_variations=8,
        train=False,
    )
    assert result["admission"] == "verified"
    assert result["lake_ok"] is True
    assert "\n  trivial" not in str(result["lean"])
    assert int(result["body_tokens"]) > 1


def test_streaming_trainer_never_requests_holdout() -> None:
    rows = _rows(24)
    config = ae.AutoencoderConfig(seed=9, validation_fraction=0.2, canary_fraction=0.2, holdout_fraction=0.2)
    manifest = ae.build_canary_manifest(rows, config=config)
    requested: list[str] = []

    def factory(split: str):
        requested.append(split)
        return [row for row in rows if manifest.assignments[row["id"]] == split]

    report = ae.train_autoencoder_stream(factory, manifest=manifest, config=config, epochs=2, batch_size=4)
    assert report["ok"] is True
    assert report["streaming"] is True
    assert "holdout" not in requested
    assert report["holdout"]["accessed"] is False
    assert report["state"]["step"] > 0


def test_stream_evaluation_bounds_metric_work_but_reports_full_count() -> None:
    rows = _rows(40)
    calls: list[str] = []

    def compile_fn(lean: str, problem: str = ""):
        calls.append(lean)
        return {"theorem_ok": True}

    examples = [ae.coerce_training_example(row) for row in rows]
    result = ae.evaluate_stream_split(
        ae.LeanIRAutoencoder(),
        examples,
        split="canary",
        compile_fn=compile_fn,
        max_metric_rows=5,
        max_verified_rows=5,
    )
    assert result["sample_count"] == 5
    assert result["stream_count"] == 40
    assert len(calls) == 5
