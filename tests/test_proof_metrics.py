from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from jevops.proof_metrics import compare_proofs, inspect_olean
from jevops.router_tuning import _lean_compiler
from jevops.solver_feedback import source_digest

SOURCE = "theorem sizes (p : Prop) (h : p) : p := by\n  exact h\n"


def test_measurement_rejects_missing_artifact_budget_and_changed_statement(tmp_path):
    result = inspect_olean(directory=tmp_path, declaration="sizes", source=SOURCE, project_root=tmp_path)
    assert not result["ok"]
    with pytest.raises(ValueError, match="budget"):
        _lean_compiler(project_root=tmp_path, kernel_only=True, measure_proofs=True, proof_node_budget=0)
    with pytest.raises(ValueError, match="kernel-only"):
        _lean_compiler(project_root=tmp_path, measure_proofs=True)
    with pytest.raises(ValueError, match="envelope"):
        compare_proofs(SOURCE, SOURCE.replace(": p :=", ": False :="), lambda _: {})
    ambiguous = SOURCE.replace(": p :=", ": _ :=")
    with pytest.raises(ValueError, match="envelope"):
        compare_proofs(ambiguous, ambiguous, lambda _: {})


def test_proof_validity_does_not_substitute_for_missing_size_measurement():
    report = compare_proofs(SOURCE, SOURCE, lambda _: {"theorem_ok": True, "kernel_audit": {"accepted": True}})
    assert not report["ok"] and report["expression_nonregression"] is None
    assert not report["source_and_expression_improvement"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_exact_compiled_expression_counts_sharing_axioms_and_budget_failure(tmp_path):
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, measure_proofs=True)
    receipt = compiler(SOURCE)
    metric = receipt["proof_metrics"]
    assert receipt["theorem_ok"] and metric["ok"], receipt
    assert metric["source_sha256"] == source_digest(SOURCE)
    assert metric["proof"]["unique_structural_nodes"] == 4
    assert metric["proof"]["tree_nodes"] == 5  # repeated bvar 0 has the same structural node
    assert metric["proof"]["height"] == 3 and metric["proof"]["closed"]
    assert metric["type"]["tree_nodes"] == 5
    assert metric["axioms"] == [] and not metric["constant_bodies_unfolded"]
    assert "Main.olean" in metric["artifact_files_sha256"]
    rejected = compiler("theorem no_proof : False := by\n  sorry\n")
    assert not rejected["theorem_ok"] and not rejected["proof_metrics"]["ok"]
    small = _lean_compiler(project_root=tmp_path, kernel_only=True, measure_proofs=True, proof_node_budget=1)
    exhausted = small(SOURCE)
    assert exhausted["theorem_ok"] and not exhausted["proof_metrics"]["ok"]


@pytest.mark.skipif(not os.environ.get("JEVOPS_MATHLIB_PROJECT"), reason="requires Mathlib")
def test_mathlib_expression_reader_matches_audited_axioms():
    compiler = _lean_compiler(project_root=Path(os.environ["JEVOPS_MATHLIB_PROJECT"]), use_lake=True,
                              kernel_only=True, measure_proofs=True, timeout=45)
    source = "import Mathlib\ntheorem sizes_ring (x : Int) : x + 0 = x := by\n  ring\n"
    result = compare_proofs(source, source.replace("  ring", "  simp"), compiler)
    assert result["ok"], result
    assert isinstance(result["expression_nonregression"], bool)
