"""Derived historical measurements are not fresh Lean verification."""
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from jevops import rejection_reports as reports
from jevops import rejection_training as training
from jevops.structural_policy import digest
from tests.test_candidate_audit import compiler, rows
from tests.test_structural_training import ENV

pytestmark = pytest.mark.no_seal(reason="optional PyTorch control artifacts")


def test_saved_comparison_preserves_all_failed_graph_controls_and_stronger_baseline():
    path = Path(__file__).with_name("fixtures") / "rejection_training_control" / "measurement.json"
    record = json.loads(path.read_text())
    assert record["comparison_sha256"] == digest({k: v for k, v in record.items() if k != "comparison_sha256"})
    assert [r["learning_rate"] for r in record["runs"]] == [.05, .15, .25]
    for run in record["runs"]:
        measured = run["measurement"]
        assert measured["audit_statuses"] == {"accepted": 10, "elaborator_rejected": 3, "identity": 8}
        assert measured["admitted_pairs"] == 8 and measured["native_compile_calls"] == 21
        assert not measured["ok"] and not measured["evaluation_accessed"]
        assert measured["token_length"]["acceptable_count"] == 5
        assert measured["token_length"]["verified_saved_tokens"] == 44
        for arm in training.ARM_WEIGHTS:
            stats = measured["statistics"][arm]
            assert stats["updates"] == stats["examples_seen"] == 640
            assert stats["after"]["acceptable_count"] == 8 and stats["after"]["correct_count"] == 6
            assert stats["after"]["verified_saved_tokens"] == 72
        standard, penalized = [measured["statistics"][a]["after"] for a in training.ARM_WEIGHTS]
        assert penalized["rejected_probability_mass"] < standard["rejected_probability_mass"]
        assert penalized["cross_entropy"] > standard["cross_entropy"]
    assert record["best_trained_control"]["arm"] == "fixed_graph"
    assert record["best_trained_control"]["metrics"]["verified_saved_tokens"] == 74
    assert not record["checkpoint_promoted"] and not record["all_graph_training_gates_passed"]


@pytest.fixture
def directories(tmp_path):
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    paths = []
    for i, rate in enumerate((.05, .15)):
        result = training.run_training(rows(), compiler, environment_sha256=ENV, epochs=1, learning_rate=rate)
        path = tmp_path / str(i)
        training.write_reports(result, path)
        paths.append(path)
    yield paths
    torch.set_num_threads(before)


def test_reports_compare_only_matched_runs_without_training(directories, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(training, "run_training", lambda *a, **kw: pytest.fail("reporter trained"))
    output = tmp_path/"comparison"
    status = reports.generate_reports(directories, output)
    assert capsys.readouterr().out == "" and status["runs"] == 2
    measured = json.loads((output/"measurement.json").read_text())
    assert measured["selection_scope"] == "training_only_sequential_development"
    assert not measured["evaluation_accessed"] and not measured["checkpoint_promoted"]
    with pytest.raises(FileExistsError):
        reports.generate_reports(directories, output)
    with pytest.raises(ValueError, match="learning rate"):
        reports.summarize_runs([directories[0], directories[0]])


def test_mismatched_update_budgets_cannot_be_reported_as_matched(directories, tmp_path):
    result = training.run_training(rows(), compiler, environment_sha256=ENV, epochs=2, learning_rate=.25)
    path = tmp_path/"different"
    training.write_reports(result, path)
    with pytest.raises(ValueError, match="runs differ"):
        reports.summarize_runs([directories[0], path])
