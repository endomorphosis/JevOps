"""Replay tests exercise orchestration; receipts here are not fresh Lean evidence."""
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from jevops.graph_experiment import render_summary, run_experiment
from jevops.graph_policy import GraphEditPolicy
from jevops.structural_policy import StructuralEditPolicy
from tests.test_structural_training import ENV

pytestmark = pytest.mark.no_seal(reason="optional external PyTorch runtime")


@pytest.fixture
def experiment_input():
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    saved = json.loads((Path(__file__).with_name("fixtures") / "structural_feature_report" / "run.json").read_text())
    receipts = {r["source"]: r["receipt"] for r in saved["compile_attempts"]}
    yield saved["manifest"], receipts
    torch.set_num_threads(threads)


def test_matched_experiment_freezes_before_eval_and_has_no_fake_graph_training(experiment_input, monkeypatch):
    rows, receipts = experiment_input
    updates = []
    for cls in (GraphEditPolicy, StructuralEditPolicy):
        original = cls.train_step
        def wrapped(self, source, target, context, _original=original, **kwargs):
            assert "graph_train_" in source and kwargs["split"] == "train"
            updates.append(source)
            return _original(self, source, target, context, **kwargs)
        monkeypatch.setattr(cls, "train_step", wrapped)
    def compile_one(source):
        if "graph_train_" not in source:
            assert len(updates) == 2*5*4
        return receipts[source]
    run = run_experiment(compile_one, rows=rows, environment_sha256=ENV, epochs=4)
    assert run["graph_encoder_changed"] and run["frozen_encoder_unchanged"]
    assert all(c["steps"] == 8 for c in run["checkpoints"].values())
    assert not run["checkpoint_promoted"] and run["official_score"] is None
    assert not run["trained_lossless_autoencoder"] and not run["semantic_family_decontamination"]
    assert run["holdout_accessed_after_freeze"]
    events = [r["event"] for r in run["events"]]
    assert events.index("checkpoint_frozen") < events.index("final_holdout")
    assert "not an arena score" in render_summary(run)
    assert "type-safe by construction" in render_summary(run)
    run["checkpoints_sha256"] = "bad"
    with pytest.raises(ValueError, match="receipt"):
        render_summary(run)


def test_bad_evidence_stops_before_training_and_failed_predictions_are_not_repaired(experiment_input, monkeypatch):
    rows, receipts = experiment_input
    blocked = run_experiment(lambda _: {"theorem_ok": True}, rows=rows, environment_sha256=ENV)
    assert not blocked["ok"] and blocked["reason"] == "structural_teacher_gate"
    original = GraphEditPolicy.predict
    def corrupted(self, source, context, **kwargs):
        prediction = original(self, source, context, **kwargs)
        if not self.freeze_encoder and self.rounds and kwargs.get("ablation", "none") == "none":
            prediction["source"] = source.split(":= by")[0] + ":= by\n  exact nonexistent\n"
        return prediction
    monkeypatch.setattr(GraphEditPolicy, "predict", corrupted)
    run = run_experiment(receipts.__getitem__, rows=rows, environment_sha256=ENV, epochs=2)
    assert not run["ok"]
    assert run["summary"]["holdout"]["learned_graph"]["valid_count"] == 0
    assert run["summary"]["holdout"]["learned_graph"]["verified_saved_tokens"] == 0
    assert all("nonexistent" in r["prediction"]["source"] for r in run["results"] if r["arm"] == "learned_graph")


def test_recorded_control_failure_is_retained_and_not_claimed_as_compression_gain(experiment_input):
    rows, receipts = experiment_input
    measured = json.loads((Path(__file__).with_name("fixtures") / "trained_graph_control.json").read_text())
    # These saved compiler observations are replay evidence, not fresh authority.
    run = run_experiment(receipts.__getitem__, rows=rows, environment_sha256=ENV,
                         epochs=measured["epochs"], seed=measured["seed"])
    assert not run["ok"] and not run["checkpoint_promoted"] and run["official_score"] is None
    assert run["graph_encoder_changed"] and run["frozen_encoder_unchanged"]
    for arm in ("learned_graph", "fixed_graph", "node_bag"):
        actual, expected = run["summary"]["holdout"][arm], measured["summary"]["holdout"][arm]
        for key in ("valid_count", "verified_saved_tokens", "cross_entropy", "expected_cosine_loss"):
            assert actual[key] == pytest.approx(expected[key], abs=1e-6)
    assert run["summary"]["holdout"]["learned_graph"]["valid_count"] == 1
    assert run["summary"]["holdout"]["fixed_graph"]["valid_count"] == 2
    assert run["summary"]["holdout"]["learned_graph"]["verified_saved_tokens"] == 16
