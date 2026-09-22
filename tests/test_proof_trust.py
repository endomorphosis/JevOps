from __future__ import annotations

import shutil

import pytest

from jevops.proof_trust import audit_axioms, top_level_declarations
from jevops.router_tuning import _lean_compiler


def test_axiom_audits_require_reports_and_reject_new_or_native_axioms():
    assert audit_axioms("'t' does not depend on any axioms", ["t"])["accepted"]
    assert audit_axioms("'t'' does not depend on any axioms", ["t'"])["accepted"]
    assert audit_axioms("'t' depends on axioms: [propext,\n Classical.choice, Quot.sound]", ["t"])["accepted"]
    for name in ("sorryAx", "Lean.ofReduceBool", "Lean.trustCompiler", "t._native.native_decide.ax_1", "Unproven"):
        assert not audit_axioms(f"'t' depends on axioms: [{name}]", ["t"])["accepted"]
    assert not audit_axioms("", ["t"])["accepted"]
    assert not audit_axioms("'t' depends on axioms: [sorryAx]\n 't' does not depend on any axioms", ["t"])["accepted"]
    assert not audit_axioms("'t' depends on axioms: [sorryAx]", ["t"], allowed_axioms=["sorryAx"])["accepted"]
    assert audit_axioms("'t' depends on axioms: [Project.fact]", ["t"], allowed_axioms=["Project.fact"])["accepted"]


def test_helper_declines_ambiguous_declaration_scopes():
    assert top_level_declarations("import Std\ntheorem a : True := by trivial\nlemma b : True := a") == ["a", "b"]
    for source in ("namespace N\ntheorem t : True := by trivial\nend N", "example : True := by trivial"):
        with pytest.raises(ValueError):
            top_level_declarations(source)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_kernel_audit_rejects_native_and_transitive_sorry(tmp_path):
    strict = _lean_compiler(project_root=tmp_path, kernel_only=True)
    assert strict("theorem checked : 2 + 2 = 4 := by decide")["theorem_ok"]
    native = strict("import Std\ntheorem native : 2 + 2 = 4 := by native_decide")
    assert not native["theorem_ok"] and native["kernel_audit"]["native_axioms"]
    admitted = strict("theorem hole : False := by sorry\ntheorem inherited : False := hole")
    assert not admitted["theorem_ok"] and "sorryAx" in admitted["kernel_audit"]["axioms"]
    unknown = strict("axiom untrusted : False\ntheorem inherited : False := untrusted")
    assert not unknown["theorem_ok"] and "untrusted" in unknown["kernel_audit"]["unexpected_axioms"]
