"""Multi-rule coverage and admission; mocked receipts are not Lean evidence."""
import copy
import json
from pathlib import Path
import shutil

import pytest

torch = pytest.importorskip("torch")

from jevops import graph_curriculum as curriculum
from jevops import graph_refinement as refinement
from jevops.proof_tokens import proof_source_tokens
from jevops.rewrite_policy import body_of, choices, mine_template
from jevops.router_tuning import _lean_compiler
from jevops.structural_policy import digest
from tests.test_structural_training import ENV, fixture_receipt

pytestmark = pytest.mark.no_seal(reason="optional PyTorch and fresh native Lean probes")


def test_training_rules_are_seed_invariant_and_transfer_targets_are_reachable():
    # Lexical coverage only, not proof validity or a measure of learning.
    rows = curriculum.training_rows()
    assert rows == curriculum.training_rows() and rows != curriculum.training_rows(1)
    assert len(rows) == 5 and {r["split"] for r in rows} == {"train"}
    banks = [{t["id"]: t for r in bank if (t := mine_template(r["source"], body_of(r["target"])[1]))}
             for bank in (rows, curriculum.training_rows(1))]
    assert banks[0] == banks[1] and len(banks[0]) == 4
    templates = list(banks[0].values())
    probes = curriculum.transfer_rows()
    assert probes == curriculum.transfer_rows() and probes != curriculum.transfer_rows(1)
    assert len(probes) == 7 and len({r["id"] for r in rows + probes}) == 12
    assert not {r["family"] for r in rows} & {r["family"] for r in probes}
    for family in {r["family"] for r in probes}:
        assert len({r["split"] for r in probes if r["family"] == family}) == 1
    for row in rows + probes:
        assert proof_source_tokens(row["target"]) < proof_source_tokens(row["source"])
        assert body_of(row["target"])[0] == body_of(row["source"])[0]
        candidates = choices(row["source"], templates)
        assert len([c for c in candidates if c["body"] == body_of(row["target"])[1]]) == 1
        if row["family"].startswith("alias_"):
            assert len(candidates) == 3  # identity, copying, and competing rfl


@pytest.mark.parametrize("seed", [True, -1, 2**32, "1", None])
def test_invalid_seeds_are_not_silently_accepted(seed):
    for generate in (curriculum.training_rows, curriculum.transfer_rows):
        with pytest.raises(ValueError, match="seed"):
            generate(seed)


@pytest.fixture(scope="module")
def training_run():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    rows = curriculum.training_rows()
    allowed = {s for r in rows for s in (r["source"], r["target"])}
    def compiler(source):
        assert source in allowed, "evaluation source used for training"
        return fixture_receipt(source)
    try:
        yield refinement.fit_training(compiler, rows=rows, environment_sha256=ENV, epochs=2)
    finally:
        torch.set_num_threads(old)


def test_shared_grammar_has_only_admitted_training_origins(training_run):
    diagnostics = curriculum.grammar_diagnostics(training_run)
    assert diagnostics["template_count"] == 4
    assert diagnostics["frozen_grammar_shared_across_arms"]
    assert not diagnostics["teacher_optimality_proven"]
    assert sorted(len(ids) for ids in diagnostics["training_origins"].values()) == [1, 1, 1, 2]
    assert all(not r["identity_target"] for r in diagnostics["rows"])
    for arm, stats in training_run["statistics"].items():
        assert stats["examples_seen"] == 10
        assert stats["updates"] == (2 if stats["config"]["update"] == "batch" else 10)
        if arm not in {"fixed_graph", "frozen_multiscale"}:
            assert stats["encoder_changed"]


@pytest.mark.parametrize("damage, message", [
    ("hash", "invalid frozen"), ("split", "training-only"), ("arms", "different grammars"),
    ("unadmitted", "unadmitted"), ("no_origins", "without verified"), ("target", "outside frozen")])
def test_grammar_provenance_fails_closed(training_run, damage, message):
    fit = copy.deepcopy(training_run)
    if damage == "hash":
        fit["seed"] += 1
    elif damage == "split":
        fit["training_rows"][0]["split"] = "holdout"
    elif damage == "arms":
        fit["checkpoints"]["fixed_graph"]["templates"] = []
    elif damage == "unadmitted":
        fit["training_pairs"]["pairs"][0]["teacher_admitted"] = False
    elif damage == "no_origins":
        fit["training_pairs"]["pairs"] = []
    else:
        fit["training_rows"][0]["target"] = fit["training_rows"][0]["source"] + "  skip\n"
    if damage != "hash":
        fit["freeze_sha256"] = digest({k: v for k, v in fit.items() if k != "freeze_sha256"})
    with pytest.raises(ValueError, match=message):
        curriculum.grammar_diagnostics(fit)


@pytest.mark.parametrize("reuse_frozen", [False, True])
def test_cli_freezes_before_generating_transfer_and_preserves_protocol_failure(training_run, tmp_path, monkeypatch, reuse_frozen):
    # Only orchestration is mocked here; these are not successful benchmark runs.
    from jevops import router_tuning
    output = tmp_path / "result"
    def fit_training(*args, **kwargs):
        assert not reuse_frozen, "retrained frozen checkpoint"
        assert kwargs["rows"] == curriculum.training_rows()
        return training_run
    def transfer(seed):
        saved = json.loads((output / "training.json").read_text())
        assert saved == training_run and (output / "grammar.json").exists()
        return curriculum_rows
    curriculum_rows = curriculum.transfer_rows()
    def evaluate(fit, rows, compiler):
        assert fit == training_run and rows is curriculum_rows
        raise ValueError("renamed or structural type/proof overlap")
    monkeypatch.setattr(refinement, "fit_training", fit_training)
    monkeypatch.setattr(refinement, "evaluate_frozen", evaluate)
    monkeypatch.setattr(curriculum, "transfer_rows", transfer)
    monkeypatch.setattr(router_tuning, "_lean_compiler", lambda **kwargs: None)
    args = ["--environment-sha256", ENV, "--output-dir", str(output)]
    if reuse_frozen:
        saved = tmp_path / "training.json"
        saved.write_text(json.dumps(training_run))
        args += ["--frozen-fit", str(saved)]
    assert curriculum.main(args) == 1
    failure = json.loads((output / "failure.json").read_text())
    assert failure["stage"] == "evaluation_protocol" and failure["freeze_sha256"] == training_run["freeze_sha256"]
    assert not failure["ok"] and not failure["checkpoint_promoted"] and failure["official_score"] is None
    assert not (output / "evaluation.json").exists() and not (output / "summary.md").exists()


@pytest.mark.parametrize("damage", ["hash", "environment", "existing_directory"])
def test_cli_rejects_stale_fits_environment_changes_and_overwrites(training_run, tmp_path, monkeypatch, damage):
    from jevops import router_tuning
    fit = copy.deepcopy(training_run)
    if damage == "hash":
        fit["seed"] += 1
    saved, output = tmp_path / "training.json", tmp_path / "result"
    saved.write_text(json.dumps(fit))
    if damage == "existing_directory":
        output.mkdir()
        (output / "sentinel").write_text("preserve me")
    monkeypatch.setattr(router_tuning, "_lean_compiler", lambda **kwargs: None)
    monkeypatch.setattr(refinement, "fit_training", lambda *a, **k: pytest.fail("unexpected training"))
    monkeypatch.setattr(refinement, "evaluate_frozen", lambda *a, **k: pytest.fail("unexpected evaluation"))
    args = ["--environment-sha256", "b" * 64 if damage == "environment" else ENV,
            "--output-dir", str(output), "--frozen-fit", str(saved)]
    with pytest.raises(ValueError if damage == "hash" else SystemExit):
        curriculum.main(args)
    if damage == "existing_directory":
        assert (output / "sentinel").read_text() == "preserve me" and len(list(output.iterdir())) == 1
    else:
        assert not output.exists()


def test_cli_success_uses_generators_and_never_promotes(training_run, tmp_path, monkeypatch):
    from jevops import router_tuning
    output = tmp_path / "result"
    monkeypatch.setattr(router_tuning, "_lean_compiler", lambda **kwargs: None)
    monkeypatch.setattr(refinement, "fit_training", lambda *a, **k: training_run)
    def evaluation(fit, rows, compiler):
        assert json.loads((output / "training.json").read_text()) == training_run
        return {"ok": True, "checkpoint_promoted": False}
    monkeypatch.setattr(refinement, "evaluate_frozen", evaluation)
    monkeypatch.setattr(refinement, "render_summary", lambda fit, result: "generated test summary\n")
    monkeypatch.setattr(curriculum, "measurement_record", lambda fit, result: {"test_only": result})
    assert curriculum.main(["--environment-sha256", ENV, "--output-dir", str(output)]) == 0
    assert (output / "summary.md").read_text() == "generated test summary\n"
    assert json.loads((output / "measurement.json").read_text())["test_only"]["checkpoint_promoted"] is False
    assert not (output / "failure.json").exists()


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires native Lean")
def test_native_curriculum_teachers_and_transfer_shapes_are_admissible(tmp_path):
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        compiler = _lean_compiler(project_root=tmp_path, environment_sha256=ENV,
                                  kernel_only=True, export_dags=True)
        fit = refinement.fit_training(compiler, rows=curriculum.training_rows(), environment_sha256=ENV, epochs=1)
        assert fit["ok"] and fit["training_pairs"]["accepted_count"] == 5
        diagnostics = curriculum.grammar_diagnostics(fit)
        assert diagnostics["template_count"] == 4
        before = digest(fit)
        result = refinement.evaluate_frozen(fit, curriculum.transfer_rows(), compiler)
        assert result["models_unchanged"] and digest(fit) == before
        assert result["source_type_shapes_disjoint"] and result["family_labels_disjoint"]
        assert all(r["teacher_check"]["expression_nonregression"] for r in result["results"])
        assert all(s["loss_sample_count"] == s["sample_count"] == 7 for s in result["summary"].values())
        # One epoch tests native boundaries/coverage, not a success threshold.
        assert not result["checkpoint_promoted"] and result["official_score"] is None
        record = curriculum.measurement_record(fit, result)
        assert record == curriculum.measurement_record(fit, result)
        assert record["measurement_sha256"] == digest({k: v for k, v in record.items() if k != "measurement_sha256"})
        result["ok"] = not result["ok"]
        with pytest.raises(ValueError, match="receipts"):
            curriculum.measurement_record(fit, result)
    finally:
        torch.set_num_threads(old)


def test_recorded_multirule_result_is_a_baseline_tie_not_a_compression_record():
    # Deterministic replay of saved native observations, not fresh verification.
    record = json.loads((Path(__file__).with_name("fixtures") / "graph_curriculum_control.json").read_text())
    assert record["measurement_sha256"] == digest({k: v for k, v in record.items() if k != "measurement_sha256"})
    stats, selected = record["training_statistics"], record["selected"]
    candidates = [k for k, v in stats.items() if v["config"]["selectable"]]
    assert selected == min(candidates, key=lambda k: (-stats[k]["after"]["correct_count"],
        stats[k]["after"]["cross_entropy"] + .35*stats[k]["after"]["expected_cosine_loss"], k))
    assert stats[selected]["after"]["correct_count"] == 5 and stats[selected]["encoder_changed"]
    assert stats[selected]["after"]["cross_entropy"] < stats[selected]["before"]["cross_entropy"]
    assert stats[selected]["after"]["expected_cosine_loss"] < stats[selected]["before"]["expected_cosine_loss"]
    assert record["grammar"]["template_count"] == 4
    assert record["ok"] and all(record["gates"].values()) and record["models_unchanged"]
    for arm in record["summary"].values():
        assert arm["sample_count"] == arm["valid_count"] == arm["loss_sample_count"] == arm["nonregressing_count"] == 7
        assert arm["verified_saved_tokens"] == 66  # No learned compression advantage.
    assert refinement.acceptance_gates(record["summary"][selected], record["summary"]["fixed_graph"]) == {
        k: v for k, v in record["gates"].items() if k != "all_splits_pass"}
    for split, arms in record["by_split"].items():
        assert refinement.acceptance_gates(arms[selected], arms["fixed_graph"]) == record["split_gates"][split]
        assert all(record["split_gates"][split].values())
    observations = record["selected_observations"]
    assert sum(r["source_tokens"] for r in observations) == 101
    assert sum(r["prediction_tokens"] for r in observations) == 35
    for row in observations:
        assert row["choice"] == row["teacher_choice"] and row["choice"] != 0
        for checked in (row["check"], row["teacher_check"]):
            assert checked["verified"] and checked["expression_nonregression"]
            for key in ("unique_expression_nodes", "expanded_expression_nodes"):
                assert checked["prediction_proof"][key] <= checked["source_proof"][key]
    assert not record["semantic_family_decontamination"] and not record["checkpoint_promoted"]
    assert record["official_score"] is None
