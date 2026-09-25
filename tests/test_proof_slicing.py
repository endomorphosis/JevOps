from __future__ import annotations

import shutil
import hashlib

import pytest

from jevops.proof_slicing import arity_repair_variants, deletion_variants, minimize_checked
from jevops.router_tuning import _lean_compiler


STATEMENT = "theorem repair_fixture (h : True) : True"


def arity_error(term="ih h ?m.42"):
    return {"severity": "error", "message": "Function expected at\n  " + term
        + "\nbut this term has type\n  True\n\nNote: Expected a function because this term is being applied to the argument\n  ?_"}


def repair(source, diagnostics=None, **kw):
    return arity_repair_variants(source, STATEMENT, [arity_error()] if diagnostics is None else diagnostics,
                                diagnostics_source_sha256=kw.pop("digest", hashlib.sha256(source.encode()).hexdigest()), **kw)


@pytest.mark.parametrize("callee", ["ih", "recursiveProof", "ih'", "υπόθεση"])
@pytest.mark.parametrize("tactic", ["apply", "refine", "exact"])
def test_repair_pairs_the_reported_extra_argument_with_its_explicit_goal_block(callee, tactic):
    source = STATEMENT + f" := by\n  {tactic} ({callee} h ?_ ?_).2.2\n    . exact h\n    . trivial"
    rows = repair(source, [arity_error(f"{callee} h ?m.42")])
    assert len(rows) == 1
    kind, candidate, provenance = rows[0]
    assert kind == "repair_overapplied_hole" and provenance[0] == "unverified_diagnostic_repair"
    assert candidate == STATEMENT + f" := by\n  {tactic} ({callee} h ?_).2.2\n    . exact h"


def test_repair_preserves_unrelated_later_branches_and_nested_remaining_goals():
    source = STATEMENT + (" := by\n  case left =>\n    apply (ih h ?_ ?_).2\n"
        "      . have witness := h\n        exact witness\n      . trivial\n  case right =>\n    exact h")
    rows = repair(source)
    assert len(rows) == 1
    assert "have witness := h\n        exact witness" in rows[0][1]
    assert rows[0][1].endswith("case right =>\n    exact h")
    assert "trivial" not in rows[0][1]


@pytest.mark.parametrize("body", [
    "  apply (ih h ?_ ?_).2\n    . exact h",  # incomplete goal mapping
    "  apply (ih h ?_ ?_).2\n    exact h\n    trivial",  # no explicit blocks
    "  apply (ih other ?_ ?_).2\n    . exact h\n    . trivial",  # different arguments
    "  apply (ih (id h) ?_ ?_).2\n    . exact h\n    . trivial",  # unsupported nested argument
    "  apply (ih h ?_ ?_).2 -- comment\n    . exact h\n    . trivial",
    "  exact h\n  apply (ih h ?_ ?_).2\n    . exact h\n    . trivial\n"
    "  apply (ih h ?_ ?_).2\n    . exact h\n    . trivial",  # ambiguous anchor
])
def test_unsupported_or_ambiguous_repair_abstains(body):
    assert repair(STATEMENT + " := by\n" + body) == []


@pytest.mark.parametrize("diagnostics", [[], [arity_error(), arity_error()],
    [arity_error(), {"severity": "error", "message": "simp_all made no progress"}],
    [{"severity": "error", "message": "maximum number of heartbeats"}],
    [{"severity": [], "message": "bad"}], [None]])
def test_unrelated_failure_or_malformed_diagnostics_are_not_a_repair_signal(diagnostics):
    source = STATEMENT + " := by\n  apply (ih h ?_ ?_).2\n    . exact h\n    . trivial"
    assert repair(source, diagnostics) == []


def test_stale_binding_zero_cap_and_wrong_statement_produce_no_draft():
    source = STATEMENT + " := by\n  apply (ih h ?_ ?_).2\n    . exact h\n    . trivial"
    assert repair(source, digest="0"*64) == []
    assert repair(source, cap=0) == []
    assert repair(source.replace(STATEMENT, "theorem wrong : True")) == []
    for cap in (True, -1, 9, 1.5):
        with pytest.raises(ValueError):
            repair(source, cap=cap)


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
