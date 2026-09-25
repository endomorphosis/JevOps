from __future__ import annotations

import copy
import shutil

import pytest

from jevops import replay_distillation as rd
from jevops.proof_replay import replay_candidate
from jevops.proof_state import capture_source
from jevops.router_tuning import _lean_compiler

ENV = "a" * 64


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    project = tmp_path_factory.mktemp("replay-training")
    frozen = False
    training = False
    class Guarded(dict):
        def __getitem__(self, key):
            if key in ("source", "target") and super().__getitem__("split") == "holdout":
                assert frozen, "holdout read before checkpoint freeze"
            if key == "target" and super().__getitem__("split") == "train":
                pytest.fail("training read a target instead of replay-discovered teacher")
            return super().__getitem__(key)
    rows = [Guarded(r) for r in rd.control_rows()]
    train_sources = {r["source"] for r in rows if r["split"] == "train"}
    kwargs = dict(project_root=project, environment_sha256=ENV)
    def capture(source):
        assert source in train_sources and not training
        return capture_source(source, **kwargs)
    def replay(source, *args):
        assert source in train_sources and not training
        return replay_candidate(source, *args, **kwargs)
    def event(item):
        nonlocal frozen, training
        if item["event"] == "training":
            training = True
        if item["event"] == "checkpoint_frozen":
            frozen = True
    return rd.run_experiment(rows=rows, capture_fn=capture, replay_fn=replay,
        compile_fn=_lean_compiler(**kwargs, kernel_only=True, export_dags=True),
        environment_sha256=ENV, event=event)


def test_native_replay_teachers_train_only_edit_weights(experiment):
    run = experiment
    assert run["ok"] and run["model_step"] == 24, run.get("gates")
    assert run["checkpoint"]["rewrite_steps"] == 24
    assert run["initial_checkpoint"]["rewrite_weights"] != run["checkpoint"]["rewrite_weights"]
    assert all(run["initial_checkpoint"][k] == run["checkpoint"][k] for k in rd.HEADS)
    assert run["checkpoint_sha256"] == rd.digest(run["checkpoint"])
    assert run["training_pairs"]["pairs"][0]["teacher_admitted"]
    assert [a["status"] for a in run["training_pairs"]["attempts"]] == ["rejected", "admitted_candidate"]
    for split in ("train", "validation", "canary"):
        a, b = run["before"][split], run["after"][split]
        assert a["cross_entropy"] == b["cross_entropy"]
        assert b["rewrite_cross_entropy"] < a["rewrite_cross_entropy"]
        assert b["rewrite_expected_cosine_loss"] < a["rewrite_expected_cosine_loss"]
        assert b["cosine_similarity"] >= a["cosine_similarity"]


def test_raw_holdout_shortening_is_independently_checked_not_repaired(experiment):
    trained, zero = experiment["holdout"]["holdout"], experiment["holdout_zero_weights"]["holdout"]
    assert trained["verified_shortening"] == 1 and trained["verified_saved_tokens"] == 2
    assert zero["verified_shortening"] == 0 and zero["verified_saved_tokens"] == 0
    row = trained["rows"][0]
    assert row["prediction_tokens"] == 1 and row["source_tokens"] == 3
    assert row["check"]["verified"] and row["expression_nonregression"]
    assert row["loss"]["minimality_reward"] == 1
    assert zero["rows"][0]["loss"]["minimality_reward"] == 0
    assert experiment["holdout_accessed_after_freeze"] and not experiment["checkpoint_promoted"]
    assert experiment["official_score"] is None and not experiment["open_state_encoder_trained"]


def test_report_is_generated_deterministic_and_bound(experiment):
    text = rd.render_summary(experiment)
    assert text == rd.render_summary(experiment)
    assert len(text.splitlines()) < 30 and "no arena" in text and "frozen" in text
    forged = copy.deepcopy(experiment)
    forged["checkpoint"]["rewrite_weights"]["bogus"] = 1
    with pytest.raises(ValueError):
        rd.render_summary(forged)


def test_old_v1_report_remains_readable_without_inventing_coverage(experiment):
    legacy = copy.deepcopy(experiment)
    legacy.pop("fixture_seed")
    for group in legacy["holdout"].values():
        for key in ("compression_sample_count", "preservation_sample_count", "identity_only_count",
                    "target_reachable_count", "verified_target_count", "families"):
            group.pop(key)
    text = rd.render_summary(legacy)
    assert "diagnostics unavailable in this legacy receipt" in text
    assert "Seed: not recorded" in text


def test_invalid_short_prediction_gets_no_reward_or_teacher_fallback(experiment, monkeypatch):
    # Reuse source-bound native receipts as test fixtures, not fresh benchmarks.
    receipts = {a["source"]: a["receipt"] for a in experiment["compile_attempts"]}
    teachers = experiment["training_pairs"]
    capture = next(iter(teachers["captures"].values()))
    replays = {(a["proposal"]["event_id"], a["proposal"]["candidate"]): a["replay"] for a in teachers["attempts"]}
    predict = rd.LeanIRAutoencoder.predict_ir
    def corrupted(self, source, **kwargs):
        if "replay_holdout_" in source:
            prefix, _, _ = rd._source_parts(source)
            return rd.ae.encode_lean_ir(prefix + "\n  rfl\n")
        return predict(self, source, **kwargs)
    monkeypatch.setattr(rd.LeanIRAutoencoder, "predict_ir", corrupted)
    run = rd.run_experiment(capture_fn=lambda _: capture,
        replay_fn=lambda s, c, i, t: replays[i, t],
        compile_fn=lambda s: receipts.get(s, {"theorem_ok": False}), environment_sha256=ENV)
    holdout = run["holdout"]["holdout"]
    assert not run["ok"] and not run["checkpoint_promoted"]
    assert holdout["prediction_tokens"] == 1 and holdout["verified_saved_tokens"] == 0
    assert holdout["verified_shortening"] == holdout["verified"] == 0
    assert holdout["rows"][0]["prediction"].endswith("  rfl\n")
    assert holdout["rows"][0]["loss"]["minimality_reward"] == 0


@pytest.mark.parametrize("kwargs", [{"epochs": True}, {"epochs": 201}, {"max_compiles": 0},
                                    {"rows": []}, {"rows": rd.control_rows() * 2}])
def test_invalid_budgets_and_manifests_do_not_start_executor(kwargs):
    def forbidden(*a, **k):
        pytest.fail("invalid experiment reached executor")
    with pytest.raises(ValueError):
        rd.run_experiment(capture_fn=forbidden, replay_fn=forbidden, compile_fn=forbidden,
                          environment_sha256=ENV, **kwargs)


def test_failed_teacher_gate_does_not_train_or_read_evaluation(monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("failed teacher gate reached training or compilation")
    monkeypatch.setattr(rd.LeanIRAutoencoder, "train_batch", forbidden)
    run = rd.run_experiment(capture_fn=lambda _: {"ok": False}, replay_fn=forbidden, compile_fn=forbidden,
                            environment_sha256=ENV)
    assert not run["ok"] and run["model_step"] == 0 and "checkpoint" not in run
