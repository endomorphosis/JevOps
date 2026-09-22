from __future__ import annotations

import shutil

import pytest

from jevops.logic_refactor import reduction_variants
from jevops.tactic_arguments import argument_spans, argument_variants
from jevops.router_tuning import _lean_compiler


def test_balanced_lists_preserve_nested_commas_and_context_suffix():
    source = "simp only [f (a, b), g ⟨x, y⟩, h [1, 2]] at hypothesis"
    spans = argument_spans(source)
    assert spans[0][2] == ["f (a, b)", "g ⟨x, y⟩", "h [1, 2]"]
    rows = argument_variants(source)
    assert rows[0][1] == "simp only [] at hypothesis"
    assert any(body == "simp only [g ⟨x, y⟩, h [1, 2]] at hypothesis" for _, body, _ in rows)
    assert all(body.endswith(" at hypothesis") for _, body, _ in rows)
    assert len(argument_variants(source, cap=2)) == 2
    assert argument_variants(source, cap=0) == []


@pytest.mark.parametrize("body", ['simp [f (a, b]', 'simp [f -- comment\n]', 'simp ["a,b"]',
                                  'simp [f; g]', 'simp [f,,g]', 'simp [f `x]'])
def test_opaque_or_malformed_lists_abstain(body):
    assert argument_variants(body) == []


def test_application_and_eta_edits_preserve_scope_and_other_lines():
    assert reduction_variants("apply f\nexact h", strategy="application_reduce")[0][1] == "exact f h"
    assert reduction_variants("intro h\nexact f h", strategy="eta_reduce")[0][1] == "exact f"
    assert not reduction_variants("intro f\nexact f f", strategy="eta_reduce")
    assert not reduction_variants("apply f -- comment\nexact h", strategy="application_reduce")
    assert not reduction_variants("apply f\n  exact h", strategy="application_reduce")


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_checks_new_reductions_and_rejects_missing_solver_support(tmp_path):
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True)
    pairs = [("application_reduce", "(p q : Prop) (f : p → q) (h : p) : q", "apply f\nexact h"),
             ("eta_reduce", "(p q : Prop) (f : p → q) : p → q", "intro h\nexact f h")]
    for i, (strategy, header, body) in enumerate(pairs):
        candidate = reduction_variants(body, strategy=strategy)[0][1]
        source = f"theorem checked_{i} {header} := by\n  " + candidate.replace('\n', '\n  ')
        result = compiler(source)
        assert result["theorem_ok"] and result["kernel_audit"]["accepted"], result
    head = "theorem prune (n : Nat) : 0 + n = n := by\n  "
    assert compiler(head + "simp only [Nat.zero_add]")["theorem_ok"]
    # A rejected draft must not be considered an unconditional list rewrite.
    assert not compiler(head + "simp only [Nat.add_zero]")["theorem_ok"]
