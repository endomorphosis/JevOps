from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from jevops.router_tuning import _lean_compiler
from jevops.training_probe import probe_rows, run_probe


def test_training_probe_refuses_an_unverified_teacher_before_any_update() -> None:
    result = run_probe(lambda source: {"theorem_ok": False})
    assert not result["ok"] and result["model_step"] == 0
    assert result["reason"] == "unverified_training_pair"


def test_probe_checks_development_fixture_validity_before_any_training() -> None:
    result = run_probe(lambda source: {"theorem_ok": "validation_prop" not in source})
    assert not result["ok"] and result["model_step"] == 0
    assert result["reason"] == "unverified_fixture" and result["id"] == "validation_prop"


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_probe_learns_real_shortening_and_reports_raw_dependency_failures(tmp_path: Path) -> None:
    result = run_probe(_lean_compiler(project_root=tmp_path))
    assert result["ok"] and result["model_step"] == 160
    assert not result["arena_data_used"] and not result["production_memory_used"]
    before = {r["id"]: r for r in result["before"]["validation"]}
    assert not set(before) & set(result["train_ids"])
    for row in result["after"]["validation"]:
        assert row["verified_shortening"]
        assert row["cross_entropy"] < before[row["id"]]["cross_entropy"]
        assert row["cosine_similarity"] >= before[row["id"]]["cosine_similarity"]
        assert "have spare" not in row["prediction"]
    control = result["after"]["negative_control"][0]
    assert result["before"]["negative_control"][0]["verified"]
    assert control["verified"] and not control["verified_shortening"]
    assert not control["raw_ablation"]["verified"] and not control["raw_ablation"]["verified_shortening"]
    assert control["dependency_guard"]["restored"]
    for row in result["after"]["dependency_validation"]:
        assert row["verified"], row["compile"]
        if row["family"] == "dead_chain":
            assert row["verified_shortening"]
        else:
            assert not row["verified_shortening"]
            assert row["dependency_guard"]["restored"]
    assert not set(result["train_ids"]) & {r["id"] for r in result["after"]["dependency_validation"]}


def test_randomized_dependency_fixtures_are_reproducible_and_never_training_rows() -> None:
    first, second = probe_rows(fixture_seed=11), probe_rows(fixture_seed=12)
    assert first == probe_rows(fixture_seed=11) and first != second
    assert [r for r in first if r["split"] == "train"] == [r for r in second if r["split"] == "train"]
    assert {r["family"] for r in first if r["split"] == "dependency_validation"} == {
        "dead_chain", "live_chain", "type_chain", "implicit_context"}


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_balanced_binding_policy_has_real_raw_predictions_not_guard_substitution(tmp_path: Path) -> None:
    result = run_probe(_lean_compiler(project_root=tmp_path), curriculum="balanced", train_binding_policy=True)
    assert result["ok"] and result["model_step"] == result["binding_steps"] == 160
    evaluation = [row for split, rows in result["after"].items() if split != "train" for row in rows]
    assert len(evaluation) == 11
    assert all(row["raw_ablation"]["verified"] for row in evaluation)
    assert sum(row["raw_ablation"]["verified_shortening"] for row in evaluation) == 4
    assert all(not row["dependency_guard"]["restored"] for row in evaluation)
    assert all(row["binding_policy"]["mode"] == "learned_binding_keep" for row in evaluation)
    assert all(row["sequence_ablation"]["verified"] for row in evaluation)
    assert not any(row["sequence_ablation"]["verified_shortening"] for row in evaluation)
    before = result["before"]["train"]
    after = result["after"]["train"]
    assert sum(r["binding_cross_entropy"] for r in after) < sum(r["binding_cross_entropy"] for r in before)
    assert not set(result["train_ids"]) & {r["id"] for r in evaluation}
