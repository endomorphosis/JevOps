from __future__ import annotations

import shutil

import pytest

from jevops.constructive_proofs import propose, search
from jevops.logic_ir import parse_formula
from jevops.rewrite_distillation import collect_teacher, constructive_rows, run_distillation
from jevops.router_tuning import RouterTuningConfig, RouterTuningLoop, _lean_compiler
from jevops.solver_feedback import source_digest


def test_support_and_budget_are_not_a_claim_of_completeness():
    p = parse_formula
    result = search(p("q"), [("f", p("p → q")), ("h", p("p")), ("unused", p("r"))])
    assert result["term"] == "f h" and result["support"] == ["f", "h"]
    assert not result["complete"] and not result["global_minimum"]
    assert search(p("p ∨ ¬ p"), [])["term"] is None
    assert search(p("False"), [])["term"] is None
    assert search(p("p"), [("h", p("p ∨ q"))])["term"] is None
    small = search(p("p → p"), [], max_states=1)
    assert small["budget_exhausted"] and small["term"] is None
    with pytest.raises(ValueError, match="budget"):
        search(p("p"), [], max_states=True)


@pytest.mark.parametrize("source", [
    "theorem t (p : Prop) (h : p) : _ := by\n  exact h\n",
    "theorem t (p : Prop) (h : p) (h : ¬ p) : False := by\n  contradiction\n",
    "theorem t (n : Nat) : n = n := by\n  rfl\n",
    "theorem t (p : Prop) : q := by\n  sorry\n",
    "namespace N\ntheorem t (p : Prop) : p → p := by\n  intro h\n  exact h\n",
])
def test_unsupported_or_ambiguous_sources_abstain(source):
    assert not propose(source)["supported"]


def metric_oracle(source):
    # Test double: simp_all is assigned a larger term, independently of tokens.
    growth = "simp_all" in source or "tauto" in source
    return {"theorem_ok": True, "kernel_audit": {"accepted": True, "axioms": []},
            "proof_metrics": {"ok": True, "source_sha256": source_digest(source), "axioms": [],
                              "proof": {"tree_nodes": 84 if growth else 17, "unique_structural_nodes": 39 if growth else 14}}}


def test_teacher_guard_rejects_source_shortening_with_expression_growth():
    row = constructive_rows()[0]
    legacy = collect_teacher(row, metric_oracle)
    guarded = collect_teacher(row, metric_oracle, constructive_terms=True, cost_guard=True)
    assert "simp_all" in legacy["target"]
    assert guarded["target"].endswith("  exact And.left\n")
    assert any(not r["accepted"] for r in guarded["cost_checks"])
    assert guarded["trace"][-1]["strategy"] == "constructive_terms"
    missing = collect_teacher(row, lambda _: {"theorem_ok": True, "kernel_audit": {"accepted": True}}, cost_guard=True)
    assert not missing["ok"] and missing["reason"] == "unmeasured_source_cost"


def test_training_uses_guarded_teachers_and_frozen_inference_rejects_growth(monkeypatch):
    from jevops import autoencoder as ae
    from jevops.autoencoder_training import LeanIRAutoencoder
    rows = constructive_rows(333)
    result = run_distillation(metric_oracle, rows=rows, constructive_terms=True, cost_guard=True,
                              freeze_reconstruction_heads=True, trajectory_training=True, epochs=40)
    assert result["cost_gate"]["accepted"] and result["reconstruction_heads_unchanged"]
    assert all("simp_all" not in t["target"] for t in result["teachers"].values())
    old = LeanIRAutoencoder.predict_ir
    def corrupt(self, text, **kw):
        if self.step and "constructive_holdout_projection" in text and self.state["rewrite_weights"]:
            return ae.encode_lean_ir(text.partition(":= by")[0] + ":= by\n  simp_all\n")
        return old(self, text, **kw)
    monkeypatch.setattr(LeanIRAutoencoder, "predict_ir", corrupt)
    bad = run_distillation(metric_oracle, rows=rows, constructive_terms=True, cost_guard=True,
                           freeze_reconstruction_heads=True, trajectory_training=True, epochs=40)
    assert not bad["ok"] and not bad["cost_gate"]["accepted"]
    assert any("simp_all" in r["prediction"] for r in bad["holdout"]["holdout"]["rows"])
    assert not bad["checkpoint_promoted"]


def test_router_exposes_bounded_constructive_branch_and_fixed_training_seed():
    source = constructive_rows()[0]["source"]
    loop = RouterTuningLoop({}, source, compile_fn=lambda s, **kw: metric_oracle(s), router_generate=lambda _: "{}",
                           config=RouterTuningConfig(constructive_terms=True, train=False))
    rows = []
    count, result = loop._constructive_rows(rows, set(), source, max_new=1)
    assert count == 1 and result["supported"] and rows[0]["origin"] == "logic:constructive_terms"
    assert [r for r in constructive_rows(7) if r["split"] == "train"] == [r for r in constructive_rows(8) if r["split"] == "train"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_checks_terms_without_classical_axioms(tmp_path):
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True)
    sources = [r["source"] for r in constructive_rows()[:7]]
    sources += [f"theorem c{i} (p q r : Prop) {context} : {goal} := by\n  skip\n" for i, (context,goal) in enumerate([
        ("", "p → ¬ ¬ p"), ("", "p ↔ p"),
        ("(h : p ∨ q) (f : p → r) (g : q → r)", "r"),
        ("(h : False)", "p"), ("", "True"), ("", "(p ∧ q) → (q ∧ p)"),
    ])]
    candidates = [propose(source)["candidate"] for source in sources]
    assert all(candidates)
    result = compiler("\n".join(candidates))
    assert result["theorem_ok"] and result["kernel_audit"]["axioms"] == [], result
