from __future__ import annotations

import shutil

import pytest

from jevops.proof_slicing import deletion_variants, minimize_checked
from jevops.router_tuning import _lean_compiler


def test_slicing_preserves_whole_nested_blocks_and_is_bounded():
    body = "have a : True := by\n  trivial\nhave b : True := a\nexact h\n"
    rows = deletion_variants(body, cap=5)
    assert 0 < len(rows) <= 5
    assert any(draft.strip() == "exact h" for _, draft, _ in rows)
    assert all(not draft.startswith("  trivial") for _, draft, _ in rows)
    assert deletion_variants("/- opaque -/\nexact h") == []
    assert deletion_variants(body, cap=0) == []


def test_minimization_never_accepts_missing_compiler_or_changes_theorem():
    source = "theorem t (h : True) : True := by\n  have a : True := h\n  exact a"
    failed = minimize_checked(source, lambda *a, **kw: {"theorem_ok": False})
    assert not failed["ok"] and failed["best_source"] == source
    calls = []
    def compiler(candidate, **kwargs):
        calls.append(candidate)
        return {"theorem_ok": "have a" in candidate and "exact a" in candidate}
    result = minimize_checked(source, compiler, max_calls=2)
    assert result["best_source"] == source and len(calls) <= 2
    assert all(s.split(":= by")[0] == source.split(":= by")[0] for s in calls)
    assert not result["minimality_proven"] and not result["training_enabled"]
    with pytest.raises(ValueError):
        minimize_checked("trivial", compiler)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_kernel_checked_slicing_removes_mutually_dependent_dead_blocks(tmp_path):
    source = ("theorem slice (p : Prop) (h : p) : p := by\n"
              "  have a : True := by\n    trivial\n  have b : True := a\n  exact h\n")
    result = minimize_checked(source, _lean_compiler(project_root=tmp_path, kernel_only=True), max_calls=12)
    assert result["ok"] and result["best_body_tokens"] < result["source_body_tokens"]
    assert result["best_source"].strip().endswith("exact h") and "have" not in result["best_source"]
    assert all(r["compile"]["kernel_audit"]["accepted"] for r in result["trajectory"])
