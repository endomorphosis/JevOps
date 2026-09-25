"""Frozen prediction/loss regression; receipt replay is not a fresh Lean check."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
from jevops.measure_checkpoint import measure_checkpoint
from jevops.proof_tokens import proof_source_tokens
from jevops.rewrite_distillation import digest
from jevops.rewrite_trajectories import trajectory_metrics, verified_edges

FIXTURES = Path(__file__).with_name("fixtures")


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def frozen():
    cp = load("typed_edit_checkpoint.json")
    evidence = load("typed_edit_evidence.json")
    receipts = {}
    for row in evidence["expressions"]["evaluations"]:
        for side in ("source", "prediction"):
            receipts[row[side]] = row["receipts"][side]
    return cp, evidence, receipts


def test_saved_model_reproduces_size_regression_without_repair(frozen):
    cp, evidence, receipts = frozen
    before = digest(cp)
    report = measure_checkpoint(cp, receipts.__getitem__, family_prefix="", max_examples=32)
    assert digest(cp) == before
    assert report["evaluations"] == evidence["expressions"]["evaluations"]
    assert report["selection"] == {"family_prefix": "", "matched_count": 18, "evaluated_count": 18, "complete": True}
    assert report["ok"] and not report["expression_gates_accepted"]
    assert report["pareto_improvement_count"] == 15
    failures = [r for r in report["evaluations"] if not r["expression_nonregression"]]
    assert len(failures) == 1 and failures[0]["family"] == "projection"
    failure = failures[0]
    assert (failure["source_tokens"], failure["prediction_tokens"]) == (6, 1)
    assert failure["prediction"].endswith("  simp_all\n")
    assert failure["receipts"]["source"]["proof_metrics"]["proof"]["tree_nodes"] == 17
    assert failure["receipts"]["prediction"]["proof_metrics"]["proof"]["tree_nodes"] == 84
    assert not any(report[k] for k in ("training_enabled", "teacher_at_inference", "compiler_repair_used", "checkpoint_promoted"))


def test_typed_subset_helps_source_length_not_expression_size(frozen):
    cp, evidence, receipts = frozen
    result = measure_checkpoint(cp, receipts.__getitem__)
    assert result["ok"] and result["expression_gates_accepted"]
    assert len(result["evaluations"]) == result["pareto_improvement_count"] == 4
    assert sum(r["source_tokens"] for r in result["evaluations"]) == 29
    assert sum(r["prediction_tokens"] for r in result["evaluations"]) == 17
    for row in result["evaluations"]:
        a, b = (row["receipts"][k]["proof_metrics"]["proof"] for k in ("source", "prediction"))
        assert a["tree_nodes"] == b["tree_nodes"]
        assert a["unique_structural_nodes"] == b["unique_structural_nodes"]
    assert evidence["previous_checkpoint_typed_comparison"]["state_sha256"] == load("trajectory_edit_checkpoint.json")["state_sha256"]


@pytest.mark.parametrize("failure", ["missing", "wrong_source", "wrong_axioms", "saturated"])
def test_unavailable_or_unbound_expression_cost_cannot_pass(frozen, failure):
    cp, _, receipts = frozen
    def incomplete(source):
        receipt = copy.deepcopy(receipts[source])
        if failure == "missing": receipt.pop("proof_metrics")
        elif failure == "wrong_source": receipt["proof_metrics"]["source_sha256"] = "0" * 64
        elif failure == "wrong_axioms": receipt["proof_metrics"]["axioms"] = ["sorryAx"]
        else:
            receipt["proof_metrics"]["proof"]["tree_nodes"] = None
            receipt["proof_metrics"]["proof"]["tree_count_saturated"] = True
        return receipt
    report = measure_checkpoint(cp, incomplete)
    assert not report["expression_gates_accepted"]
    assert not report["pareto_improvement_count"]
    assert all(r["expression_nonregression"] is None for r in report["evaluations"])
    assert report["ok"] == (failure == "saturated")


def test_empty_truncated_and_mismatched_evaluations_fail_closed(frozen):
    cp, _, receipts = frozen
    with pytest.raises(ValueError, match="digest"):
        measure_checkpoint({**cp, "state_sha256": "bad"}, receipts.__getitem__)
    with pytest.raises(ValueError, match="budget"):
        measure_checkpoint(cp, receipts.__getitem__, max_examples=True)
    empty = measure_checkpoint(cp, receipts.__getitem__, family_prefix="nonexistent")
    assert not empty["ok"] and not empty["expression_gates_accepted"]
    truncated = measure_checkpoint(cp, receipts.__getitem__, max_examples=1)
    assert truncated["ok"] and not truncated["expression_gates_accepted"]
    assert not truncated["selection"]["complete"]


def test_frozen_heads_and_incomplete_step_coverage_are_reported(frozen):
    cp, evidence, _ = frozen
    data = evidence["synthetic"]
    assert digest(cp["state"]) == cp["state_sha256"] == data["state_sha256"]
    model = LeanIRAutoencoder.from_dict(cp["state"], config=AutoencoderConfig(**cp["config"]))
    cold = LeanIRAutoencoder(config=AutoencoderConfig(**cp["config"]))
    for key in ("op_bias", "transition", "feature_op", "latent_bias", "feature_latent", "vocab"):
        assert model.to_dict()[key] == cold.to_dict()[key]
    zero = model.copy()
    zero.state["rewrite_weights"] = {}
    teachers = {t["id"]: t for t in data["teachers"]}
    steps = labels = complete = tokens = 0
    # Test double validates the shape of already saved paths, not Lean truth.
    oracle = lambda _: {"theorem_ok": True, "kernel_audit": {"accepted": True}}
    for saved in data["holdout_predictions"]:
        teacher = teachers[saved["id"]]
        assert teacher["split"] == "holdout" and saved["id"] not in cp["train_parent_ids"]
        edges = verified_edges(teacher, parent_id=teacher["id"], split="holdout", compile_fn=oracle)
        metric = trajectory_metrics(model, edges)
        assert metric["cross_entropy"] == pytest.approx(saved["trajectory"]["cross_entropy"], abs=1e-12)
        assert metric["expected_cosine_loss"] == pytest.approx(saved["trajectory"]["expected_cosine_loss"], abs=1e-12)
        assert metric["complete"] == saved["trajectory"]["complete"]
        steps += metric["step_count"]
        labels += metric["labeled_step_count"]
        complete += metric["complete"]
        tokens += proof_source_tokens(saved["prediction"])
        assert zero.predict_ir(teacher["source"])["ops"] == ae.encode_lean_ir(teacher["source"])["ops"]
    assert (steps, labels, complete, tokens) == (23, 22, 17, 80)
    assert data["before"]["canary"]["cross_entropy"] == data["after"]["canary"]["cross_entropy"]
    assert data["holdout_gate"]["accepted"] and evidence["arena"]["metric_gates_accepted"]
    assert not evidence["expressions"]["expression_gates_accepted"] and not cp["checkpoint_promoted"]
    assert not load("rewrite_distillation_evidence.json")["arena"]["metric_gates_accepted"]
