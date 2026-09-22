"""Model-only regression tests; fake compiler tests are not Lean evidence."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "papers/completion/lean_refactor_arena/harness"


def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    return importlib.import_module("evaluate_rewrite_checkpoint")


def small_checkpoint(module):
    source = "theorem t (p : Prop) (h : p) : p := by\n  exact h\n"
    target = source.replace("exact h", "assumption")
    row = coerce_training_example({"text": source, "target_ir": ae.encode_lean_ir(target)})
    config = AutoencoderConfig(train_rewrite_policy=True, warmup_steps=0)
    model = LeanIRAutoencoder(config=config)
    model.prepare_rewrite_training([row])
    for _ in range(20):
        model.train_example(row)
    checkpoint = {"state": model.to_dict(), "config": config.to_dict()}
    checkpoint["state_sha256"] = module.state_digest(checkpoint["state"])
    record = {"name": "t", "src": source, "statement": source.partition(" := by")[0]}
    return record, target, checkpoint


def fake_compile(source):
    return {"theorem_ok": True, "kernel_audit": {"accepted": True}, "test_double": True}


def test_model_only_evaluation_is_read_only_and_ablates_edit_weights(monkeypatch):
    module = harness(monkeypatch)
    record, target, checkpoint = small_checkpoint(module)
    before = module.state_digest(checkpoint)
    result = module.evaluate_checkpoint(record, checkpoint, compiler=fake_compile,
                                        include_history=False, reference_source=target)
    row = result["evaluations"][0]
    assert row["trained"]["body_tokens"] == 1
    assert row["untrained"]["body_tokens"] == row["zero_edit_weights"]["body_tokens"] == 2
    assert row["trained"]["loss"]["rewrite_cross_entropy"] is not None
    assert row["trained"]["rewrite_policy"]["trace"]
    assert result["ok"] and result["metric_gates_accepted"]
    assert not any(result[k] for k in ("training_enabled", "router_search_used", "teacher_at_inference",
                                     "checkpoint_promoted", "production_memory_used"))
    assert module.state_digest(checkpoint) == before


def test_bad_checkpoint_reference_and_failed_predictions_are_not_repaired(monkeypatch):
    module = harness(monkeypatch)
    record, target, checkpoint = small_checkpoint(module)
    with pytest.raises(ValueError, match="digest"):
        module.evaluate_checkpoint(record, {**checkpoint, "state_sha256": "bad"}, compiler=fake_compile)
    with pytest.raises(ValueError, match="statement"):
        module.evaluate_checkpoint(record, checkpoint, compiler=fake_compile, include_history=False,
                                   reference_source=target.replace(": p :=", ": True :="))
    reject = lambda _: {"theorem_ok": False, "kernel_audit": {"accepted": False}}
    failed = module.evaluate_checkpoint(record, checkpoint, compiler=reject, include_history=False,
                                        reference_source=target)
    assert not failed["ok"] and failed["reason"] == "unverified_fixed_reference"
    # The original is the fixed reference; only the learned proposal fails.
    def reject_edit(source):
        return reject(source) if "assumption" in source else fake_compile(source)
    result = module.evaluate_checkpoint(record, checkpoint, compiler=reject_edit, include_history=False)
    row = result["evaluations"][0]
    assert not result["ok"] and not row["trained"]["verified"]
    assert "assumption" in row["trained"]["source"]  # No fallback substitution.
    assert not row["trained"]["verified_shortening"]
    assert not result["metric_gates_accepted"]


def test_saved_learned_editor_reproduces_arena_edit_without_search(monkeypatch):
    module = harness(monkeypatch)
    checkpoint = json.loads((ROOT / "tests/fixtures/rewrite_distillation_checkpoint.json").read_text())
    reference = json.loads((ROOT / "tests/fixtures/kernel_refactor_local_best.json").read_text())
    assert module.state_digest(checkpoint["state"]) == checkpoint["state_sha256"]
    model = LeanIRAutoencoder.from_dict(checkpoint["state"], config=AutoencoderConfig(**checkpoint["config"]))
    predicted = model.predict_ir(reference["previous_best_source"])
    assert predicted["ops"] == ae.encode_lean_ir(reference["best_source"])["ops"]
    assert len(predicted["rewrite_policy"]["trace"]) == 1
    assert not predicted["rewrite_policy"]["teacher_used"]
    assert not predicted["rewrite_policy"]["solver_used"]
    zero = model.copy()
    zero.state["rewrite_weights"] = {}
    assert zero.predict_ir(reference["previous_best_source"])["ops"] != predicted["ops"]
    assert not checkpoint["checkpoint_promoted"] and not checkpoint["arena_data_used"]


def test_saved_arena_ce_gate_stays_rejected_despite_shortening(monkeypatch):
    module = harness(monkeypatch)
    checkpoint = json.loads((ROOT / "tests/fixtures/rewrite_distillation_checkpoint.json").read_text())
    evidence = json.loads((ROOT / "tests/fixtures/rewrite_distillation_evidence.json").read_text())
    reference = json.loads((ROOT / "tests/fixtures/kernel_refactor_local_best.json").read_text())
    _, digest, records = module.bridge.load_records()
    record = next(row for row in records if row["name"] == reference["name"])
    # Recompute metrics, not real Lean admission. Real audits are saved separately.
    report = module.evaluate_checkpoint(record, checkpoint, compiler=fake_compile,
                                         include_history=False, reference_source=reference["best_source"])
    actual = report["evaluations"][0]
    measured = evidence["arena"]["evaluations"][0]
    assert digest == evidence["arena"]["frozen_sha256"]
    assert actual["trained"]["body_tokens"] == measured["trained"]["body_tokens"] == 481
    assert actual["trained"]["loss"]["cross_entropy"] == pytest.approx(
        measured["trained"]["loss"]["cross_entropy"], abs=1e-12)
    assert actual["metric_gate"]["regressions"]["cross_entropy"] > .02
    assert not report["metric_gates_accepted"]
    assert not evidence["arena"]["metric_gates_accepted"]
    assert measured["trained"]["kernel_audit"]["accepted"]
    assert not evidence["synthetic"]["semantic_family_decontamination"]


def test_saved_edit_adapter_preserves_heads_and_reproduces_composed_holdouts(monkeypatch):
    from jevops.rewrite_distillation import compositional_holdout_rows, curriculum_rows

    module = harness(monkeypatch)
    checkpoint = json.loads((ROOT / "tests/fixtures/certified_edit_checkpoint.json").read_text())
    evidence = json.loads((ROOT / "tests/fixtures/certified_edit_evidence.json").read_text())["synthetic"]
    assert module.state_digest(checkpoint["state"]) == checkpoint["state_sha256"] == evidence["state_sha256"]
    config = AutoencoderConfig(**checkpoint["config"])
    model = LeanIRAutoencoder.from_dict(checkpoint["state"], config=config)
    cold = LeanIRAutoencoder(config=config)
    for key in ("op_bias", "transition", "feature_op", "latent_bias", "feature_latent", "vocab"):
        assert model.to_dict()[key] == cold.to_dict()[key]
    source_rows = curriculum_rows(evidence["fixture_seed"], extended=True)
    source_rows += compositional_holdout_rows(evidence["fixture_seed"] + 100)
    sources = {r["id"]: r["source"] for r in source_rows}
    for measured in evidence["holdout_predictions"]:
        source = sources[measured["id"]]
        prefix, _, theorem = module._source_parts(source)
        predicted = model.predict_ir(source)
        rendered = module._render_source(prefix, module._ir_body(predicted), has_theorem=theorem)
        assert rendered == measured["prediction"]
        assert measured["kernel_audit"]["accepted"]  # Saved real receipt, not recompilation.
    assert evidence["holdout"]["holdout"]["verified"] == 13
    assert evidence["holdout"]["holdout"]["verified_shortening"] == 11
    assert evidence["holdout"]["holdout"]["rewrite_sample_count"] == 11
    assert evidence["holdout_zero_weight_ablation"]["holdout"]["verified_shortening"] == 0
    assert not evidence["checkpoint_promoted"]


def test_saved_edit_adapter_passes_arena_metrics_without_relabeling_old_failure(monkeypatch):
    module = harness(monkeypatch)
    checkpoint = json.loads((ROOT / "tests/fixtures/certified_edit_checkpoint.json").read_text())
    evidence = json.loads((ROOT / "tests/fixtures/certified_edit_evidence.json").read_text())["arena"]
    reference = json.loads((ROOT / "tests/fixtures/kernel_refactor_local_best.json").read_text())
    _, _, records = module.bridge.load_records()
    record = next(r for r in records if r["name"] == reference["name"])
    result = module.evaluate_checkpoint(record, checkpoint, compiler=fake_compile, include_history=False,
                                        reference_source=reference["best_source"])
    row = result["evaluations"][0]
    assert row["trained"]["body_tokens"] == 481
    assert row["trained"]["loss"]["cross_entropy"] == row["untrained"]["loss"]["cross_entropy"]
    assert result["metric_gates_accepted"] and evidence["metric_gates_accepted"]
    old = json.loads((ROOT / "tests/fixtures/rewrite_distillation_evidence.json").read_text())["arena"]
    assert not old["metric_gates_accepted"]  # Retain the earlier failure.
