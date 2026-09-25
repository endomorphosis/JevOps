from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from jevops.router_tuning import RouterTuningConfig, RouterTuningLoop, _lean_compiler
from jevops.solver_feedback import compiler_messages, harvest_solver_feedback, query_sites, source_digest, suggestions

SOURCE = "theorem feedback (n : Nat) : 0 + n = n := by\n  simp only [Nat.zero_add, Nat.add_zero, Nat.mul_one]\n"


def oracle(source):
    # Mocked transport tests, not evidence that arbitrary proofs compile.
    return {"theorem_ok": True, "kernel_audit": {"accepted": True},
            "diagnostics_source_sha256": source_digest(source),
            "diagnostics": [{"severity": "information", "pos": {"line": 2, "column": 2},
                             "data": "Try this:\n  [apply] simp only [Nat.zero_add]"}]}


def test_messages_restrict_file_and_fail_closed_on_malformed_or_oversized_output():
    rows = [{"fileName": "/a", "data": "Try this:\n  simp", "severity": "information"},
            {"fileName": "/b", "data": "foreign message"}]
    diagnostics, plain = compiler_messages('\n'.join(map(json.dumps, rows)), "/a")
    assert len(diagnostics) == 1 and "foreign message" in plain
    for bad in ("not JSON", "[]", json.dumps({"data": 1}), "x"*1_048_577,
                json.dumps({"fileName": "/a", "data": "x"*16_385})):
        with pytest.raises(ValueError):
            compiler_messages(bad, "/a")


@pytest.mark.parametrize("change", ["position", "digest", "audit", "severity", "multiline", "unsafe", "question", "foreign_head"])
def test_suggestions_bind_probe_and_location_and_reject_unsafe_hints(change):
    site = query_sites(SOURCE)[0]
    receipt = oracle(site["probe"])
    assert suggestions(receipt, site["probe"], site) == ["simp only [Nat.zero_add]"]
    if change == "position":
        receipt["diagnostics"][0]["pos"]["line"] = 3
    elif change == "digest":
        receipt["diagnostics_source_sha256"] = source_digest(SOURCE)
    elif change == "audit":
        receipt["kernel_audit"] = None
    elif change == "severity":
        receipt["diagnostics"][0]["severity"] = "warning"
    else:
        draft = {"multiline": "simp\nexact h", "unsafe": "exact sorry", "question": "simp?", "foreign_head": "set_option maxRecDepth 999"}[change]
        receipt["diagnostics"][0]["data"] = "Try this:\n  " + draft
    assert suggestions(receipt, site["probe"], site) == []


def test_query_sites_exclude_inline_headers_comments_and_composed_tactics():
    assert query_sites(SOURCE)[0]["probe"].splitlines()[1].startswith("  simp?")
    for body in ("simp; assumption", "simp -- comment", "simp?", "first | simp => rfl"):
        assert query_sites(SOURCE.split(":= by")[0] + ":= by\n  " + body) == []
    assert not query_sites("theorem t : True := by simp")


def test_harvesting_requires_fresh_replay_and_respects_compiler_budget():
    calls = []
    def compiler(source):
        calls.append(source)
        receipt = oracle(source)
        if "simp only [Nat.zero_add]\n" in source:
            receipt["theorem_ok"] = False
        return receipt
    result = harvest_solver_feedback(SOURCE, compiler)
    assert result["best_source"] == SOURCE and not result["trajectory"]
    assert len(calls) == 3
    result = harvest_solver_feedback(SOURCE, oracle, max_calls=2)
    assert result["budget_exhausted"] and not result["trajectory"]
    assert len(result["compile_attempts"]) == 2
    result = harvest_solver_feedback(SOURCE, lambda _: {"theorem_ok": True})
    assert not result["ok"]


def test_feedback_rejects_invalid_budgets_and_compiler_exceptions():
    for value in (0, 65, 2.5, True):
        with pytest.raises(ValueError, match="budget"):
            harvest_solver_feedback(SOURCE, oracle, max_calls=value)
    def broken(_):
        raise RuntimeError("compiler unavailable")
    report = harvest_solver_feedback(SOURCE, broken)
    assert not report["ok"] and report["best_source"] == SOURCE
    assert report["compile_attempts"][0]["compile"]["reason"] == "RuntimeError"


def test_router_feedback_branch_registers_verified_proposal_without_llm():
    loop = RouterTuningLoop({}, SOURCE, compile_fn=lambda s, **kw: oracle(s),
                           config=RouterTuningConfig(solver_feedback=True, train=False), router_generate=lambda _: "{}")
    rows, seen = [], set()
    count, report = loop._solver_feedback_rows(rows, seen, SOURCE, max_new=1)
    assert count == 1 and report["trajectory"]
    assert rows[0]["origin"] == "logic:solver_feedback" and rows[0]["lake_ok"]
    assert len(report["compile_attempts"]) <= 8


@pytest.mark.no_seal(reason="opt-in native solver-feedback replay")
@pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1" or shutil.which("lean") is None,
                    reason="requires explicit native opt-in and Lean")
def test_real_lean_simp_feedback_replays_with_exact_envelope(tmp_path):
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, collect_diagnostics=True)
    result = harvest_solver_feedback(SOURCE, compiler)
    assert result["ok"] and result["best_tokens"] == 7 < result["source_tokens"] == 15
    assert result["trajectory"][0]["compile"]["kernel_audit"]["accepted"]
    assert result["best_source"].split(":= by")[0] == SOURCE.split(":= by")[0]
    assert not compiler("theorem bad : False := by\n  sorry\n")["theorem_ok"]


@pytest.mark.no_seal(reason="opt-in native grind-feedback replay")
@pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1" or shutil.which("lean") is None,
                    reason="requires explicit native opt-in and Lean")
def test_real_grind_query_does_not_accept_longer_hint(tmp_path):
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, collect_diagnostics=True)
    source = "theorem grind_feedback (n : Nat) : 0 + n = n := by\n  grind (splits := 2)\n"
    result = harvest_solver_feedback(source, compiler)
    assert result["ok"] and result["best_tokens"] <= result["source_tokens"]
    assert any("Try this:" in a["compile"].get("stdout_tail", "") for a in result["compile_attempts"])
    assert all(s["after_tokens"] < s["before_tokens"] for s in result["trajectory"])


@pytest.mark.no_seal(reason="opt-in native Mathlib solver-feedback replay")
@pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1" or not os.environ.get("JEVOPS_MATHLIB_PROJECT"),
                    reason="requires explicit native opt-in and cached Mathlib")
def test_real_mathlib_linarith_feedback(tmp_path):
    compiler = _lean_compiler(project_root=Path(os.environ["JEVOPS_MATHLIB_PROJECT"]), use_lake=True,
                              kernel_only=True, collect_diagnostics=True, timeout=45)
    source = "import Mathlib\ntheorem feedback_linear (x y : Int) (h : 0 ≤ x) (k : 0 ≤ y) : 0 ≤ x := by\n  linarith only [h, k]\n"
    result = harvest_solver_feedback(source, compiler)
    assert result["ok"] and result["trajectory"], result
    assert result["best_tokens"] < result["source_tokens"]
