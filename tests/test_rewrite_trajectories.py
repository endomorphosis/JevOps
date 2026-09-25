from __future__ import annotations

import pytest

from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, canary_gate, coerce_training_example
from jevops.rewrite_distillation import collect_teacher, curriculum_rows, run_distillation
from jevops.rewrite_trajectories import trajectory_metrics, verified_edges
from tests.test_rewrite_distillation import fixture_oracle


def teacher():
    row = next(r for r in curriculum_rows() if r["split"] == "train" and r["family"] == "terminal_alias")
    return row, collect_teacher(row, fixture_oracle)


def test_adjacent_steps_keep_parent_split_and_recompile_every_state():
    row, trace = teacher()
    calls = []
    edges = verified_edges(trace, parent_id=row["id"], split="train", compile_fn=lambda s: calls.append(s) or fixture_oracle(s))
    assert len(edges) == 2 and len(calls) == 3
    assert all(e["parent_id"] == row["id"] and e["split"] == "train" for e in edges)
    assert edges[1]["text"] == trace["trace"][0]["after_source"]
    assert not edges[-1]["text"].endswith("assumption\n")  # no invented stop label


@pytest.mark.parametrize("bad", ["connection", "endpoint", "header", "growing", "intermediate"])
def test_invalid_or_forged_trajectories_fail_closed(bad):
    row, trace = teacher()
    compiler = fixture_oracle
    if bad == "connection":
        trace["trace"][1]["before_source"] = "unrelated"
    elif bad == "endpoint":
        trace["target"] += "\n"
    elif bad == "header":
        trace["trace"] = [{"before_source": trace["source"], "after_source": "theorem cheat : True := by trivial"}]
        trace["target"] = trace["trace"][0]["after_source"]
    elif bad == "growing":
        trace["trace"] = [{"before_source": trace["source"], "after_source": trace["source"]}]
        trace["target"] = trace["source"]
    else:
        compiler = lambda s: {"theorem_ok": s != trace["trace"][0]["after_source"], "kernel_audit": {"accepted": True}}
    with pytest.raises(ValueError):
        verified_edges(trace, parent_id=row["id"], split="train", compile_fn=compiler)


def test_steps_have_actual_ce_gradients_and_unreachable_labels_are_not_zero_loss():
    row, trace = teacher()
    edges = verified_edges(trace, parent_id=row["id"], split="train", compile_fn=fixture_oracle)
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True, freeze_reconstruction_heads=True))
    missing = trajectory_metrics(model, edges)
    assert missing["labeled_step_count"] == 0 and missing["cross_entropy"] is None
    examples = [coerce_training_example(e) for e in edges]
    model.prepare_rewrite_training(examples)
    before = trajectory_metrics(model, edges)
    for _ in range(40):
        model.train_batch(examples)
    after = trajectory_metrics(model, edges)
    assert after["complete"] and after["labeled_step_count"] == 2
    assert after["cross_entropy"] < before["cross_entropy"]


def test_trajectory_gate_rejects_coverage_loss_nonfinite_and_ce_regression():
    before = {"sample_count": 1, "trajectory_step_count": 2, "trajectory_labeled_step_count": 2,
              "trajectory_complete_examples": 1, "trajectory_cross_entropy": .3, "trajectory_expected_cosine_loss": .1}
    for key, value in (("trajectory_labeled_step_count", 1), ("trajectory_cross_entropy", float("nan")),
                       ("trajectory_cross_entropy", .4), ("trajectory_expected_cosine_loss", .3)):
        assert not canary_gate(before, {**before, key: value})["accepted"]


def test_trajectory_distillation_never_mines_holdout_steps_or_repairs_raw_predictions():
    result = run_distillation(fixture_oracle, epochs=12, extended=True, compositional_holdout=True,
                              trajectory_training=True, freeze_reconstruction_heads=True)
    assert result["reconstruction_heads_unchanged"]
    assert result["train_ids"] and all(":step:" in s for s in result["train_ids"])
    assert all("train" in s for s in result["train_parent_ids"])
    heldout = result["holdout"]["holdout"]
    assert heldout["trajectory_step_count"] >= heldout["sample_count"]
    assert all(not r["rewrite_policy"]["teacher_used"] for r in heldout["rows"])
    assert result["holdout_accessed_after_freeze"] and not result["tuning_allowed_after_holdout"]
