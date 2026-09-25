"""Replay is not fresh proof authority; the final test also invokes native Lean."""
import copy
import json
import os
from pathlib import Path
import shutil

import pytest

from jevops.structural_ablation import control_rows, render_summary, run_ablation
from jevops.structural_policy import StructuralEditPolicy, digest, source_context
from jevops.solver_feedback import source_digest
from tests.test_structural_training import ENV

REPORT = Path(__file__).with_name("fixtures") / "structural_feature_report"


@pytest.fixture(scope="module")
def saved():
    return json.loads((REPORT / "run.json").read_text())


def replay_compiler(saved):
    receipts = {r["source"]: r["receipt"] for r in saved["compile_attempts"]}
    return receipts.__getitem__


def test_native_experiment_artifact_shows_validity_gain_not_extra_token_savings(saved):
    assert saved["ok"] and saved["checkpoints_sha256"] == digest(saved["checkpoints"])
    assert saved["manifest_sha256"] == digest(saved["manifest"])
    assert all(a["source_sha256"] == source_digest(a["source"]) for a in saved["compile_attempts"])
    assert all(key == context["source_sha256"] for key, context in saved["contexts"].items())
    assert render_summary(saved) == (REPORT / "summary.md").read_text()
    result = saved["holdout"]["holdout"]
    assert result["lexical"]["verifier_success_rate"] == .5
    assert result["structural"]["verifier_success_rate"] == 1
    assert saved["structural_holdout_saved_tokens_advantage"] == 0
    assert result["structural"]["verified_saved_tokens"] == result["lexical"]["verified_saved_tokens"] == 16
    assert result["drop_graph"]["verified_shortening"] == result["zero_weights"]["verified_shortening"] == 0
    assert result["structural"]["rewrite_cross_entropy"] < result["lexical"]["rewrite_cross_entropy"]
    assert result["structural"]["rewrite_expected_cosine_loss"] < result["lexical"]["rewrite_expected_cosine_loss"]
    assert saved["reconstruction_heads_unchanged"] and not saved["graph_encoder_trained"]
    assert saved["graph_readout_trained"] and not saved["checkpoint_promoted"] and saved["official_score"] is None
    events = [r["event"] for r in saved["events"]]
    assert events.index("checkpoint_frozen") < events.index("final_holdout")
    assert saved["holdout_accessed_after_freeze"] and not saved["tuning_allowed_after_holdout"]


def test_matched_arms_and_read_only_prediction_replay_require_source_graphs(saved):
    compiler = replay_compiler(saved)
    models = {name: StructuralEditPolicy.from_dict(state) for name, state in saved["checkpoints"].items()}
    assert models["lexical"].templates == models["structural"].templates
    assert models["lexical"].steps == models["structural"].steps == 160
    train = [r for r in saved["manifest"] if r["split"] == "train"]
    features = [[r["features"] for r in models["lexical"].rows(ex["source"])] for ex in train]
    assert features[0] == features[1], "lexical control must be genuinely ambiguous"
    contexts = [source_context(r["source"], compiler(r["source"]), environment_sha256=ENV) for r in train]
    assert contexts[0].features != contexts[1].features
    snapshot = {k: m.to_dict() for k, m in models.items()}
    for row in saved["manifest"]:
        if row["split"] != "holdout":
            continue
        ctx = source_context(row["source"], compiler(row["source"]), environment_sha256=ENV)
        for name, model in models.items():
            expected = next(r for r in saved["holdout"]["holdout"][name]["rows"] if r["id"] == row["id"])
            assert model.predict(row["source"], ctx) == expected["prediction"]
        with pytest.raises(ValueError, match="requires source"):
            models["structural"].predict(row["source"])
    assert snapshot == {k: m.to_dict() for k, m in models.items()}


def test_seed_changes_evaluation_names_not_training():
    a, b = control_rows(10), control_rows(20)
    assert [r for r in a if r["split"] == "train"] == [r for r in b if r["split"] == "train"]
    assert [r for r in a if r["split"] == "holdout"] != [r for r in b if r["split"] == "holdout"]


def test_training_replays_exactly_and_holdout_compilation_is_after_final_update(saved, monkeypatch):
    compiler, updates = replay_compiler(saved), []
    original = StructuralEditPolicy.train_step
    def train(self, source, target, context, **kwargs):
        assert "graph_train_" in source and kwargs["split"] == "train"
        updates.append(source)
        return original(self, source, target, context, **kwargs)
    monkeypatch.setattr(StructuralEditPolicy, "train_step", train)
    def check(source):
        if "graph_holdout_" in source:
            assert len(updates) == 320
        return compiler(source)
    result = run_ablation(check, environment_sha256=ENV, rows=saved["manifest"], epochs=80)
    assert result["ok"] and result["checkpoints"] == saved["checkpoints"]
    assert result["holdout"] == saved["holdout"]
    assert result["before"] == saved["before"] and result["after"] == saved["after"]


def test_raw_bad_structural_predictions_remain_failures_not_teacher_repairs(saved, monkeypatch):
    original = StructuralEditPolicy.predict
    def corrupted(self, source, context=None, **kwargs):
        prediction = original(self, source, context, **kwargs)
        if self.structural and self.steps and kwargs.get("ablation", "none") == "none":
            prediction["source"] = prediction["source"].split(":= by")[0] + ":= by\n  exact missingProof\n"
        return prediction
    monkeypatch.setattr(StructuralEditPolicy, "predict", corrupted)
    result = run_ablation(replay_compiler(saved), environment_sha256=ENV, rows=saved["manifest"], epochs=2)
    assert not result["ok"] and not result["gates"]["holdout"]["accepted"]
    structural = result["holdout"]["holdout"]["structural"]
    assert structural["verified_shortening"] == 0 and structural["verifier_success_rate"] == 0
    assert all("missingProof" in r["prediction"]["source"] for r in structural["rows"])


def test_bad_training_evidence_stops_before_training_and_report_hashes_fail_closed(saved, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("training must not start")
    monkeypatch.setattr(StructuralEditPolicy, "train_step", forbidden)
    result = run_ablation(lambda _: {"theorem_ok": True}, environment_sha256=ENV, rows=saved["manifest"])
    assert not result["ok"] and result["reason"] == "structural_teacher_gate"
    for field in ("manifest_sha256", "checkpoints_sha256"):
        altered = {**saved, field: "bad"}
        with pytest.raises(ValueError, match="receipt"):
            render_summary(altered)
    result = run_ablation(replay_compiler(saved), environment_sha256=ENV, rows=saved["manifest"], max_compiles=1)
    assert not result["ok"] and len(result["compile_attempts"]) == 1


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_source_context_and_predictions_recheck_on_new_names(saved, tmp_path):
    from jevops.router_tuning import _lean_compiler
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, export_dags=True, environment_sha256=ENV)
    model = StructuralEditPolicy.from_dict(saved["checkpoints"]["structural"])
    # A deterministic regression probe, not an untouched final benchmark.
    rows = [r for r in control_rows(42) if r["split"] == "holdout"]
    predictions = []
    for row in rows:
        receipt = compiler(row["source"])
        ctx = source_context(row["source"], receipt, environment_sha256=ENV)
        prediction = model.predict(row["source"], ctx)
        checked = compiler(prediction["source"])
        assert checked["theorem_ok"] and checked["expression_dag"]["kernel_typechecked"]
        predictions.append(prediction["choice"])
    assert predictions == [1, 0]


@pytest.mark.skipif(not os.environ.get("JEVOPS_MATHLIB_PROJECT"), reason="requires Mathlib")
def test_mathlib_source_features_are_checked_and_toolchain_bound():
    from jevops.router_tuning import _lean_compiler
    source = "import Mathlib\ntheorem graph_ring (n : Nat) : n + 0 = n := by\n  simp\n"
    compiler = _lean_compiler(project_root=Path(os.environ["JEVOPS_MATHLIB_PROJECT"]), use_lake=True,
                              kernel_only=True, export_dags=True, environment_sha256=ENV, timeout=60)
    receipt = compiler(source)
    ctx = source_context(source, receipt, environment_sha256=ENV)
    assert receipt["expression_dag"]["kernel_typechecked"] and len(ctx.features) <= 1024
    model = StructuralEditPolicy([], environment_sha256=ENV, toolchain=ctx.toolchain, structural=True)
    assert model.predict(source, ctx)["source"] == source
    wrong_toolchain = StructuralEditPolicy([], environment_sha256=ENV, toolchain=("wrong", "wrong"), structural=True)
    with pytest.raises(ValueError, match="mismatched"):
        wrong_toolchain.predict(source, ctx)
