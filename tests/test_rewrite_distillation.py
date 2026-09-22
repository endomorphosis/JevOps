from __future__ import annotations

import copy

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import LeanIRAutoencoder
from jevops.rewrite_distillation import curriculum_rows, run_distillation
from jevops.rewrite_policy import body_of


def fixture_oracle(source):
    # Unit-test oracle only. Real Lean validation is a separate experiment.
    body = body_of(source)[1]
    ok = "wrong_proof" not in body and ("PLift" not in source or "intro " in body)
    return {"theorem_ok": ok, "kernel_audit": {"accepted": ok}}


def test_distillation_uses_verified_training_rules_and_learns_without_teacher_at_inference():
    result = run_distillation(fixture_oracle, epochs=40)
    assert result["ok"] and result["rewrite_steps"] == result["model_step"] == 240
    assert result["grammar"]["template_count"] == 5
    for split in ("validation", "canary"):
        before, after = result["before"][split], result["after"][split]
        assert after["verified"] == after["sample_count"] == 6
        assert after["verified_shortening"] == 5
        assert after["cross_entropy"] < before["cross_entropy"]
        assert after["rewrite_cross_entropy"] < before["rewrite_cross_entropy"]
        assert after["cosine_similarity"] > before["cosine_similarity"]
        assert result["zero_weight_ablation"][split]["verified_shortening"] == 0
        assert not set(result["train_ids"]) & {r["id"] for r in after["rows"]}
        assert all(not r["rewrite_policy"]["teacher_used"] for r in after["rows"])
    assert result["holdout_gate"]["accepted"]
    events = [r["event"] for r in result["events"]]
    assert events.index("checkpoint_frozen") < events.index("final_holdout")
    assert not result["tuning_allowed_after_holdout"]
    assert not result["checkpoint_promoted"] and not result["arena_data_used"]
    assert not result["production_memory_used"] and not result["live_llm_used"]


def test_failed_or_unaudited_teacher_stops_before_any_weight_update():
    for oracle in (lambda _: {"theorem_ok": False}, lambda _: {"theorem_ok": True}):
        result = run_distillation(oracle)
        assert not result["ok"] and result["model_step"] == 0
        assert result["reason"] == "unverified_fixture"


def test_distillation_rejects_duplicate_rows_and_keeps_training_independent_of_canary_seed():
    first, second = curriculum_rows(5), curriculum_rows(6)
    assert [r for r in first if r["split"] == "train"] == [r for r in second if r["split"] == "train"]
    assert [r for r in first if r["split"] == "holdout"] != [r for r in second if r["split"] == "holdout"]
    duplicate = {**first[0], "id": "different_id", "split": "holdout"}
    with pytest.raises(ValueError, match="duplicate"):
        run_distillation(fixture_oracle, rows=[*first, duplicate])


def test_raw_invalid_predictions_are_not_repaired_with_teacher_output(monkeypatch):
    original = LeanIRAutoencoder.predict_ir
    def corrupted(self, text, **kwargs):
        if self.step:
            return ae.encode_lean_ir(text.split(":= by")[0] + ":= by\n  exact wrong_proof")
        return original(self, text, **kwargs)
    monkeypatch.setattr(LeanIRAutoencoder, "predict_ir", corrupted)
    result = run_distillation(fixture_oracle, epochs=2)
    assert not result["ok"]
    assert not result["learned_verified_shortening"]
    assert result["after"]["canary"]["verified"] == 0
    assert all("wrong_proof" in r["prediction"] for r in result["after"]["canary"]["rows"])


def test_final_holdout_failure_prevents_success_without_further_training(monkeypatch):
    original = LeanIRAutoencoder.predict_ir
    def corrupted(self, text, **kwargs):
        if self.state["rewrite_weights"] and "distill_holdout_" in text:
            return ae.encode_lean_ir(text.split(":= by")[0] + ":= by\n  exact wrong_proof")
        return original(self, text, **kwargs)
    monkeypatch.setattr(LeanIRAutoencoder, "predict_ir", corrupted)
    result = run_distillation(fixture_oracle, epochs=40)
    assert all(g["accepted"] for g in result["development_gates"].values())
    assert not result["ok"] and not result["holdout_gate"]["accepted"]
    assert result["model_step"] == 240 and not result["tuning_allowed_after_holdout"]
