"""Training/evaluation separation; replay receipts are not fresh proof authority."""
import copy
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from jevops.graph_policy import GraphEditPolicy
from jevops.graph_refinement import acceptance_gates, evaluate_frozen, fit_training, render_summary, shape_digest, transfer_rows
from jevops.structural_policy import StructuralEditPolicy, digest
from tests.test_structural_training import ENV, SOURCE, fixture_receipt

pytestmark = pytest.mark.no_seal(reason="optional external PyTorch runtime")


@pytest.fixture(scope="module")
def training_run():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    saved = json.loads((Path(__file__).with_name("fixtures") / "structural_feature_report" / "run.json").read_text())
    rows = [r for r in saved["manifest"] if r["split"] == "train"]
    allowed = {s for r in rows for s in (r["source"], r["target"])}
    receipts = {r["source"]: r["receipt"] for r in saved["compile_attempts"] if r["source"] in allowed}
    calls = []
    def compiler(source):
        assert source in allowed, "nontraining source compiled during selection"
        calls.append(source)
        return receipts[source]
    fit = fit_training(compiler, rows=rows, environment_sha256=ENV, epochs=4)
    yield fit, rows, receipts, calls
    torch.set_num_threads(old)


def test_selection_uses_only_training_and_records_real_budget_and_gradients(training_run):
    fit, rows, receipts, calls = training_run
    assert fit["ok"] and not fit["evaluation_accessed"] and not fit["checkpoint_promoted"]
    assert len(calls) == 3
    assert fit["freeze_sha256"] == digest({k: v for k, v in fit.items() if k != "freeze_sha256"})
    candidates = [name for name, stats in fit["statistics"].items() if stats["config"]["selectable"]]
    assert fit["selected"] == min(candidates, key=lambda name: (-fit["statistics"][name]["after"]["correct_count"],
                                                               fit["statistics"][name]["after"]["total"], name))
    for name, stats in fit["statistics"].items():
        assert stats["examples_seen"] == 8
        assert stats["updates"] == (4 if stats["config"]["update"] == "batch" else 8)
        if name not in {"fixed_graph", "frozen_multiscale"}:
            assert stats["encoder_changed"]
    assert not fit["statistics"]["frozen_multiscale"]["encoder_changed"]
    distances = [layer["pair_distances"][0]["l2"] for layer in fit["initial_layer_diagnostics"]]
    assert distances[0] > distances[1] > distances[2]


def test_fit_rejects_nontraining_rows_before_compiling_or_reading_labels(training_run):
    _, rows, _, _ = training_run
    class Guard(dict):
        def __getitem__(self, key):
            if key == "target":
                pytest.fail("evaluation target accessed")
            return super().__getitem__(key)
    def forbidden(_):
        pytest.fail("compiler called")
    with pytest.raises(ValueError, match="training rows only"):
        fit_training(forbidden, rows=[rows[0], Guard(rows[1], split="holdout")], environment_sha256=ENV)
    rejected = fit_training(lambda _: {"theorem_ok": True}, rows=rows, environment_sha256=ENV)
    assert not rejected["ok"] and rejected["reason"] == "teacher_admission"


def test_transfer_manifest_has_disjoint_goal_layouts_and_seeded_names():
    a, b = transfer_rows(10), transfer_rows(20)
    assert len(a) == 8 and a != b
    for split in ("validation", "canary", "holdout"):
        families = {r["family"] for r in a if r["split"] == split}
        assert not families & {r["family"] for r in a if r["split"] != split}
    assert all("reflexivity_control" != r["family"] for r in a)


def test_frozen_evaluation_rejects_tampering_and_family_leakage_before_compiling(training_run):
    fit, _, _, _ = training_run
    def forbidden(_):
        pytest.fail("compiler called")
    broken = copy.deepcopy(fit)
    broken["selected"] = "fixed_graph"
    with pytest.raises(ValueError, match="frozen training receipt"):
        evaluate_frozen(broken, transfer_rows(), forbidden)
    rows = transfer_rows()
    rows[0]["family"] = fit["training_families"][0]
    with pytest.raises(ValueError, match="family overlap"):
        evaluate_frozen(fit, rows, forbidden)
    rows = transfer_rows()
    rows[2]["family"] = rows[0]["family"]
    with pytest.raises(ValueError, match="crosses"):
        evaluate_frozen(fit, rows, forbidden)


def test_renamed_training_graph_cannot_masquerade_as_new_family(training_run):
    fit, rows, receipts, _ = training_run
    probes = transfer_rows()
    probes[0]["source"] = rows[0]["source"]
    with pytest.raises(ValueError, match="structural type/proof overlap"):
        evaluate_frozen(fit, probes, receipts.__getitem__)


def test_shape_hash_ignores_binder_names_but_retains_binder_flags():
    wire = fixture_receipt(SOURCE)["expression_dag"]["dag"]
    before = shape_digest(wire)
    for row in wire["expressions"]:
        if row[0] in {"lam", "forall", "let"}:
            row[1] = [["s", "renamed"]]
    assert shape_digest(wire) == before
    wire["expressions"][2][2] = "implicit"
    assert shape_digest(wire) != before


@pytest.mark.parametrize("damage", ["validity", "cost", "coverage", "baseline_coverage", "ce", "cosine", "savings", "missing", "nan"])
def test_acceptance_requires_full_coverage_and_both_losses_not_just_length(damage):
    baseline = {"sample_count": 2, "valid_count": 2, "nonregressing_count": 2, "loss_sample_count": 2,
                "verified_saved_tokens": 16, "cross_entropy": .3, "expected_cosine_loss": .2}
    chosen = dict(baseline)
    assert all(acceptance_gates(chosen, baseline).values())
    if damage == "baseline_coverage":
        baseline["loss_sample_count"] = 1
    elif damage in {"validity", "cost", "coverage", "savings"}:
        key = {"validity": "valid_count", "cost": "nonregressing_count", "coverage": "loss_sample_count",
               "savings": "verified_saved_tokens"}[damage]
        chosen[key] -= 1
    else:
        key = "expected_cosine_loss" if damage == "cosine" else "cross_entropy"
        chosen[key] = {"ce": .4, "cosine": .4, "missing": None, "nan": float("nan")}[damage]
    assert not all(acceptance_gates(chosen, baseline).values())


def test_eval_is_read_only_commits_before_labels_and_never_repairs_bad_predictions(training_run, monkeypatch):
    fit, _, _, _ = training_run
    snapshot = digest(fit)
    committed = {}
    names = list(dict.fromkeys([fit["selected"], "last_online_0.15", "fixed_graph", "frozen_multiscale", "node_bag"]))
    for cls in (GraphEditPolicy, StructuralEditPolicy):
        original = cls.predict
        def predict(self, source, context, _original=original, **kwargs):
            out = _original(self, source, context, **kwargs)
            committed[source] = committed.get(source, 0) + 1
            out["source"] = source.split(":= by")[0] + ":= by\n  exact nonexistent\n"
            return out
        monkeypatch.setattr(cls, "predict", predict)
        monkeypatch.setattr(cls, "train_step", lambda *a, **k: pytest.fail("update during evaluation"))
    monkeypatch.setattr(GraphEditPolicy, "train_batch", lambda *a, **k: pytest.fail("batch update during evaluation"))
    class Guard(dict):
        def __getitem__(self, key):
            if key == "target":
                assert committed[self["source"]] == len(names)
            return super().__getitem__(key)
    rows = [Guard(r) for r in transfer_rows()]
    def compiler(source):
        # Mock export plumbing, NOT Lean evidence. Vary type shapes so the
        # structural-overlap guard sees distinct (artificial) contexts.
        if "nonexistent" in source:
            return {"theorem_ok": False}
        index = next(i for i, r in enumerate(rows) if r["id"] in source)
        receipt = fixture_receipt(source)
        wire = receipt["expression_dag"]["dag"]
        wire["lean_version"], wire["lean_githash"] = fit["checkpoints"]["fixed_graph"]["toolchain"]
        flags = ("explicit", "implicit", "strictImplicit", "instance")
        wire["expressions"][2][2], wire["expressions"][3][2] = flags[index % 4], flags[index // 4]
        receipt["expression_dag"]["dag_sha256"] = digest(wire)
        return receipt
    result = evaluate_frozen(fit, rows, compiler)
    assert not result["ok"] and not result["checkpoint_promoted"] and result["models_unchanged"]
    assert digest(fit) == snapshot
    assert all(data["valid_count"] == data["verified_saved_tokens"] == 0 for data in result["summary"].values())
    assert all("nonexistent" in row["prediction"]["source"] for row in result["results"])
    assert set(result["split_gates"]) == {"validation", "canary", "holdout"}
    assert not result["gates"]["all_splits_pass"]
    assert "not fresh verification" in render_summary(fit, result)
    result["summary"][fit["selected"]]["valid_count"] = 999
    with pytest.raises(ValueError, match="receipts"):
        render_summary(fit, result)


def test_native_measurement_preserves_holdout_regression_despite_aggregate_tie():
    # Saved native observations plus deterministic gate replay, not a new proof check.
    record = json.loads((Path(__file__).with_name("fixtures") / "graph_refinement_control.json").read_text())
    selected = record["selected"]
    stats = record["training_statistics"]
    candidates = [k for k, v in stats.items() if v["config"]["selectable"]]
    assert selected == min(candidates, key=lambda k: (-stats[k]["correct"],
                                                     stats[k]["cross_entropy"] + .35*stats[k]["expected_cosine_loss"], k))
    assert record["summary"][selected]["valid_count"] == 8
    assert record["summary"]["last_online_0.15"]["valid_count"] == 4
    assert record["summary"][selected]["verified_saved_tokens"] == record["summary"]["fixed_graph"]["verified_saved_tokens"] == 48
    for split, arms in record["by_split"].items():
        assert acceptance_gates(arms[selected], arms["fixed_graph"]) == record["split_gates"][split]
    assert all(record["split_gates"]["canary"].values())
    assert not record["split_gates"]["holdout"]["baseline_savings_nonregression"]
    assert record["by_split"]["holdout"][selected]["verified_saved_tokens"] == 16
    assert record["by_split"]["holdout"]["fixed_graph"]["verified_saved_tokens"] == 32
    assert not record["ok"] and not record["checkpoint_promoted"] and record["official_score"] is None
