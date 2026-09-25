"""Offline report tests; fake training receipts are not Lean evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from jevops.refactor_report import build_bundle, generate_report, main, render_summary
from jevops.rewrite_distillation import digest, run_distillation


@pytest.fixture
def run():
    return run_distillation(lambda _: {"theorem_ok": True, "kernel_audit": {"accepted": True}}, epochs=1)


def test_bundle_is_deterministic_and_does_not_mutate_or_train(run):
    before = copy.deepcopy(run)
    cp, evidence = build_bundle(run)
    assert (cp, evidence) == build_bundle(run)
    assert run == before
    assert digest(cp["state"]) == run["state_sha256"]
    assert cp["state"]["step"] == run["model_step"]
    assert cp["expression_nonregression_accepted"] is None
    assert evidence["synthetic"]["holdout_gate"] == run["holdout_gate"]
    assert "Expression non-growth gate: UNAVAILABLE" in render_summary(evidence)
    assert "Holdout step labels: unavailable/unavailable" in render_summary(evidence)


@pytest.mark.parametrize("part", ["state", "manifest", "arena", "expressions"])
def test_mixed_or_corrupted_receipts_are_rejected(run, part):
    kwargs = {}
    if part in ("state", "manifest"):
        run[part + "_sha256"] = "bad"
    else:
        kwargs[part] = {"state_sha256": "bad"}
    with pytest.raises(ValueError, match="digest mismatch"):
        build_bundle(run, **kwargs)


def test_generated_files_have_repeatable_bytes_hashes_and_no_overwrite(tmp_path, run):
    source = tmp_path / "run.json"
    source.write_text(json.dumps(run))
    before = source.read_bytes()
    a, b = tmp_path / "a", tmp_path / "b"
    generate_report(source, a)
    generate_report(source, b)
    assert {p.name for p in a.iterdir()} == {"checkpoint.json", "evidence.json", "summary.md", "provenance.json"}
    for p in a.iterdir():
        assert p.read_bytes() == (b / p.name).read_bytes()
    provenance = json.loads((a / "provenance.json").read_text())
    assert provenance["input_sha256"]["run"] == hashlib.sha256(before).hexdigest()
    assert not provenance["new_measurements_performed"]
    for name, expected in provenance["output_sha256"].items():
        assert hashlib.sha256((a / name).read_bytes()).hexdigest() == expected
    with pytest.raises(FileExistsError):
        generate_report(source, a)
    assert source.read_bytes() == before


def test_cli_outputs_only_paths_and_report_success_is_not_gate_success(tmp_path, run, capsys):
    run["holdout_gate"]["accepted"] = False
    source, out = tmp_path / "run.json", tmp_path / "out"
    source.write_text(json.dumps(run))
    assert main(["--run", str(source), "--output-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert len(printed) < 1000 and "theorem_ok" not in printed
    assert json.loads(printed)["summary"] == str(out / "summary.md")
    assert "Holdout CE/cosine gate: FAIL" in (out / "summary.md").read_text()
    assert "Recorded checkpoint promotion: False" in (out / "summary.md").read_text()


def test_report_keeps_real_saved_expression_failure_and_missing_step_label_visible():
    evidence = json.loads((Path(__file__).with_name("fixtures") / "typed_edit_evidence.json").read_text())
    summary = render_summary(evidence)
    assert "Expression non-growth gate: FAIL" in summary
    assert "source tokens 6 → 1, expression tree nodes 17 → 84" in summary
    assert "Holdout step labels: 22/23; complete examples: 17/18" in summary
    assert "482 → 481; 392 → 391" in summary
    assert len(summary.splitlines()) < 45


def test_nonfinite_json_fails_before_creating_output(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"loss": NaN}')
    with pytest.raises(ValueError, match="non-finite"):
        generate_report(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_cost_guard_receipts_survive_report_projection(run):
    run["cost_guard_enabled"] = True
    run["cost_gate"] = {"accepted": False, "nonregressing_count": 1, "evaluated_count": 2}
    for teacher in run["teachers"].values():
        teacher["cost_checks"] = [{"accepted": False, "expression_nonregression": False}]
    _, evidence = build_bundle(run)
    assert "Teacher/prediction cost guard: FAIL; 1/2" in render_summary(evidence)
    assert all(t["cost_checks"] == [{"accepted": False, "expression_nonregression": False}] for t in evidence["synthetic"]["teachers"])


def test_structural_pair_report_is_compact_and_does_not_imply_graph_training(run):
    from tests.test_structural_training import collect
    run["structural_pairs"] = collect()
    run["structural_pair_targets_used"] = True
    run["graph_features_used_for_training"] = False
    _, evidence = build_bundle(run)
    pairs = evidence["synthetic"]["structural_pairs"]
    assert pairs["ok"] and pairs["accepted_count"] == 1
    assert "graphs" not in pairs and "pairs" not in pairs
    assert len(pairs["pair_sha256"]) == 1
    summary = render_summary(evidence)
    assert "Structural training-pair gate: PASS; 1 compressed pairs, 2 fresh compilation calls." in summary
    assert "graph features do not drive this sparse-model update" in summary
    assert len(summary.splitlines()) < 45


def test_archived_inputs_reproduce_reports_without_the_original_path(tmp_path, run):
    import gzip
    source = tmp_path / "run.json"
    source.write_text(json.dumps(run))
    a, b = tmp_path / "a", tmp_path / "b"
    generate_report(source, a, archive_inputs=True)
    archive = a / "inputs/run.json.gz"
    assert gzip.decompress(archive.read_bytes()) == source.read_bytes()
    generate_report(archive, b, archive_inputs=True)
    for path in a.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (b / path.relative_to(a)).read_bytes()
