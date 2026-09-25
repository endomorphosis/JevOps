from copy import deepcopy
import json

import pytest

pytest.importorskip("torch")

from jevops import scoped_training as training
from jevops import graph_refinement
from jevops.proof_replay import digest


def failed_result():
    return {"schema": training.SCHEMA, "ok": False, "scope": "inspected_training_control_not_generalization",
            "teacher_discovery": {"pairs": [], "attempts": []}, "compile_attempts": [],
            "reason": "teacher_admission", "model_trained": False, "checkpoint_promoted": False,
            "official_score": None, "evaluation_accessed": False}


def test_admission_failure_stops_before_any_parameter_update(monkeypatch):
    seen = []
    def collect(rows, **kwargs):
        seen.append(kwargs)
        return {"ok": False, "pairs": [], "attempts": []}
    monkeypatch.setattr(training, "collect_replay_pairs", collect)
    monkeypatch.setattr(graph_refinement, "fit_training", lambda *a, **kw: pytest.fail("trained on rejected teacher"))
    result = training.run_training(training.control_rows(), capture_fn=None, replay_fn=None,
                                   compile_fn=None, environment_sha256="a" * 64)
    assert result["reason"] == "teacher_admission" and not result["model_trained"]
    assert not result["ok"] and not result["checkpoint_promoted"]
    assert callable(seen[0]["proposal_fn"])


def test_fit_only_receives_verified_training_targets(monkeypatch):
    class Evaluation(dict):
        def __getitem__(self, key):
            assert key not in ("source", "target", "family"), "evaluation content accessed"
            return super().__getitem__(key)
    rows = training.control_rows()
    rows += [Evaluation(id=s, split=s) for s in ("validation", "canary", "holdout")]
    pairs = [{"id": r["id"], "text": r["source"], "target_text": "ADMITTED " + r["id"]}
             for r in rows if r["split"] == "train"]
    monkeypatch.setattr(training, "collect_replay_pairs", lambda *a, **kw: {"ok": True, "pairs": pairs})
    def fit(compiler, **kw):
        assert len(kw["rows"]) == 4
        assert all(r["split"] == "train" and r["target"] == "ADMITTED " + r["id"] for r in kw["rows"])
        return {"ok": False}
    monkeypatch.setattr(graph_refinement, "fit_training", fit)
    result = training.run_training(rows, capture_fn=None, replay_fn=None, compile_fn=None, environment_sha256="a" * 64)
    assert result["reason"] == "training_admission" and not result["evaluation_accessed"]


@pytest.mark.parametrize("kwargs", [{"epochs": True}, {"epochs": 201}, {"seed": -1}, {"max_proposals": 0}])
def test_invalid_training_budget_rejected_before_collect(monkeypatch, kwargs):
    monkeypatch.setattr(training, "collect_replay_pairs", lambda *a, **kw: pytest.fail("invalid budget reached collection"))
    with pytest.raises(ValueError, match="budget"):
        training.run_training(training.control_rows(), capture_fn=None, replay_fn=None,
                              compile_fn=None, environment_sha256="a" * 64, **kwargs)


def test_reports_are_derived_written_directly_and_never_overwritten(tmp_path, capsys):
    result = failed_result()
    before = deepcopy(result)
    output = tmp_path / "report"
    status = training.write_reports(result, output)
    assert capsys.readouterr().out == ""
    assert status["output_dir"] == str(output) and not status["ok"]
    record = json.loads((output / "measurement.json").read_text())
    assert record["experiment_sha256"] == digest(json.loads((output / "experiment.json").read_text()))
    assert record["training_pairs"] == 0 and record["reason"] == "teacher_admission"
    assert "Stopped before training" in (output / "summary.md").read_text()
    with pytest.raises(FileExistsError):
        training.write_reports(result, output)
    assert result == before


def test_reports_refuse_symlink_directory(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        training.write_reports(failed_result(), link)
    assert not list(target.iterdir())


def test_cli_prints_only_short_status(tmp_path, monkeypatch, capsys):
    import jevops.router_tuning as router
    monkeypatch.setattr(router, "_lean_compiler", lambda **kw: None)
    monkeypatch.setattr(training, "run_training", lambda *a, **kw: failed_result())
    output = tmp_path / "run"
    assert training.main(["--environment-sha256", "a" * 64, "--output-dir", str(output)]) == 1
    text = capsys.readouterr().out
    assert len(text) < 400 and "teacher_discovery" not in text
    assert json.loads(text)["checkpoint_promoted"] is False
