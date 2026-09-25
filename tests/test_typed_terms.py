from __future__ import annotations

import shutil

import pytest

from jevops.rewrite_distillation import typed_term_rows
from jevops.router_tuning import RouterTuningConfig, RouterTuningLoop, _lean_compiler
from jevops.solver_feedback import source_digest
from jevops.typed_terms import collect_typed_term

SOURCE = "theorem typed (p q r : Prop) (f : p → q → r) (h : p) (k : q) : r := by\n  apply f\n  · exact h\n  · exact k\n"


def oracle(source):
    return {"theorem_ok": True, "kernel_audit": {"accepted": True}, "diagnostics_source_sha256": source_digest(source),
            "diagnostics": [{"severity": "information", "pos": {"line": 3, "column": 4},
                             "data": "Try this:\n  [apply] exact f h k"}]}


def test_typed_term_replay_preserves_header_and_never_accepts_failed_candidate():
    assert not collect_typed_term(SOURCE.replace(": r :=", ": _ :="), oracle)["ok"]
    result = collect_typed_term(SOURCE, oracle)
    assert result["trajectory"] and result["best_tokens"] == 4 < result["source_tokens"] == 8
    assert result["best_source"].split(":= by")[0] == SOURCE.split(":= by")[0]
    def fail_replay(source):
        result = oracle(source)
        if source.endswith("  exact f h k\n"):
            result["theorem_ok"] = False
        return result
    failed = collect_typed_term(SOURCE, fail_replay)
    assert failed["best_source"] == SOURCE and not failed["trajectory"]
    assert len(failed["compile_attempts"]) == 3


@pytest.mark.parametrize("mode", ["wrong_source", "wrong_position", "multiline", "no_audit", "unsafe", "nonterm"])
def test_typed_suggestions_are_hints_not_proof_authority(mode):
    def compiler(source):
        result = oracle(source)
        if mode == "wrong_source": result["diagnostics_source_sha256"] = source_digest(SOURCE)
        if mode == "wrong_position": result["diagnostics"][0]["pos"]["column"] = 2
        if mode == "no_audit": result["kernel_audit"] = None
        if mode in {"multiline", "unsafe", "nonterm"}:
            result["diagnostics"][0]["data"] = "Try this:\n  " + {"multiline": "exact\n  f h k", "unsafe": "exact sorry", "nonterm": "assumption"}[mode]
        return result
    assert not collect_typed_term(SOURCE, compiler)["trajectory"]


def test_router_has_independent_typed_term_branch_and_curriculum_keeps_training_seed_fixed():
    loop = RouterTuningLoop({}, SOURCE, compile_fn=lambda s, **kw: oracle(s), router_generate=lambda _: "{}",
                           config=RouterTuningConfig(typed_terms=True, train=False))
    rows = []
    count, report = loop._typed_term_rows(rows, set(), SOURCE, max_new=1)
    assert count == 1 and report["trajectory"] and rows[0]["origin"] == "logic:typed_term"
    assert [r for r in typed_term_rows(7) if r["split"] == "train"] == [r for r in typed_term_rows(8) if r["split"] == "train"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_replays_terms_including_dependent_application(tmp_path):
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, collect_diagnostics=True)
    for row in typed_term_rows()[:4]:
        result = collect_typed_term(row["source"], compiler)
        assert result["ok"] and result["trajectory"], result
        assert result["trajectory"][0]["compile"]["kernel_audit"]["accepted"]
        assert result["best_tokens"] < result["source_tokens"]
    false = SOURCE.replace(": r :=", ": False :=")
    assert not collect_typed_term(false, compiler)["ok"]
