from __future__ import annotations

import random
import shutil

import pytest

from jevops.affine_invariants import infer_affine_invariants, nullspace_gf2
from jevops.logic_ir import parse_formula as p
from jevops.logic_refactor import equivalence_proof
from jevops.router_tuning import _lean_compiler


def test_gf2_basis_spans_exact_nullspace_exhaustively():
    rng = random.Random(37)
    for columns in range(1, 6):
        rows = [rng.randrange(1 << columns) for _ in range(4)]
        basis = nullspace_gf2(rows, columns)
        span = {0}
        for v in basis:
            span |= {u ^ v for u in span}
        exact = {v for v in range(1 << columns) if all((v & r).bit_count() % 2 == 0 for r in rows)}
        assert span == exact
    with pytest.raises(ValueError):
        nullspace_gf2([8], 3)


def test_affine_inference_finds_relations_and_rechecks_inductiveness():
    report = infer_affine_invariants(p("¬ x ∧ ¬ y"), p("(xn ↔ ¬ x) ∧ (yn ↔ ¬ y)"), {"x": "xn", "y": "yn"})
    assert len(report["candidates"]) == 1
    assert report["inference"]["kept_indices"] == [0]
    assert not report["lean_verified"] and not report["infinite_state_analysis"]
    # Three states of a parity plane have an affine hull containing a fourth
    # unreachable state. Its transition exits the hull: Houdini must reject it.
    initial = p("(¬ x ∧ ¬ y ∧ ¬ z) ∨ (x ∧ y ∧ ¬ z) ∨ (x ∧ ¬ y ∧ z)")
    transition = p("((x ∨ ¬ y ∨ ¬ z) ∧ (xn ↔ x) ∧ (yn ↔ y) ∧ (zn ↔ z)) ∨ (¬ x ∧ y ∧ z ∧ xn ∧ yn ∧ zn)")
    rejected = infer_affine_invariants(initial, transition, {"x": "xn", "y": "yn", "z": "zn"})
    assert rejected["candidates"] and rejected["inference"]["removed"]
    assert rejected["inference"]["lean"] == "True"


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_checks_affine_initiation_and_preservation(tmp_path):
    report = infer_affine_invariants(p("¬ x ∧ ¬ y"), p("(xn ↔ ¬ x) ∧ (yn ↔ ¬ y)"), {"x": "xn", "y": "yn"})
    source = ""
    for i, field in enumerate(("initiation_obligation", "preservation_obligation")):
        goal = report["inference"][field]
        proof = equivalence_proof(goal, "True")
        source += f"theorem obligation_{i} (x y xn yn : Prop) : ({goal}) ↔ True := by\n"
        source += "\n".join("  "+line for line in proof.splitlines()) + "\n"
    result = _lean_compiler(project_root=tmp_path, kernel_only=True)(source)
    assert result["theorem_ok"], result
