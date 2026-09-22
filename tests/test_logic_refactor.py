from __future__ import annotations

import json
import math
from pathlib import Path
import shutil

import pytest

from jevops import autoencoder as ae
from jevops.logic_refactor import (
    LOGIC_STRATEGIES, analysis_summary, equivalence_proof, reduction_catalog, reduction_sweep,
    reduction_variants, structural_observations,
)
from jevops.router_tuning import RouterTuningConfig, RouterTuningLoop, _lean_compiler, parse_router_plan
from jevops.autoencoder_training import LeanIRAutoencoder, coerce_training_example
from jevops.invariant_inference import infer_invariants
from jevops.logic_ir import parse_formula

requires_lean = pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")


@requires_lean
def test_new_kernel_egraph_and_invariant_obligations_compile(tmp_path: Path) -> None:
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True)
    rows = []
    for i, tactic in enumerate(("rfl", "decide", "decide +kernel")):
        assert any(body == tactic for _, body, _ in reduction_variants("skip", strategy="kernel_reduce"))
        rows.append(theorem(f"reduce_{i}", "", "2 + 2 = 4", tactic))
    generated = reduction_variants("skip", strategy="egraph_minimize", goal="((p ∧ q) ∨ (p ∧ ¬ q)) ↔ p")
    assert generated
    rows.append(theorem("egraph_checked", "(p q : Prop)", "((p ∧ q) ∨ (p ∧ ¬ q)) ↔ p", generated[0][1]))
    report = infer_invariants(parse_formula("x ∧ y"), parse_formula("(xn ↔ y) ∧ (yn ↔ x)"),
                              [parse_formula("x"), parse_formula("y")], {"x": "xn", "y": "yn"})
    for i, obligation in enumerate((report["initiation_obligation"], report["preservation_obligation"])):
        proof = "classical\nby_cases x <;> by_cases y <;> by_cases xn <;> by_cases yn <;> simp_all"
        rows.append(theorem(f"invariant_{i}", "(x y xn yn : Prop)", obligation, proof))
    result = compiler("import Std\n" + "\n".join(rows))
    assert result["theorem_ok"], result
    assert result["kernel_audit"]["accepted"]


def test_rewrite_transport_only_proposes_edits_and_preserves_context():
    rows = reduction_variants("  simp [Nat.add_zero] at h\n  exact h", strategy="rewrite_transport")
    assert any("simpa [Nat.add_zero] using h" in body for _, body, _ in rows)
    rows = reduction_variants("  rw [h]\n  rfl", strategy="rewrite_transport")
    assert any("simpa only [h]" in body for _, body, _ in rows)


def theorem(name: str, binders: str, goal: str, body: str) -> str:
    return f"theorem {name} {binders} : {goal} := by\n" + "\n".join("  " + s for s in body.splitlines()) + "\n"


def test_catalog_routes_every_method_and_sweep_is_bounded_and_rotates() -> None:
    assert len(set(LOGIC_STRATEGIES)) == len(reduction_catalog())
    plan = parse_router_plan(json.dumps({"strategies": list(LOGIC_STRATEGIES)}),
                             config=RouterTuningConfig(strategy_cap=len(LOGIC_STRATEGIES)))
    assert plan["strategies"] == list(LOGIC_STRATEGIES)
    source = "Prop ∧ ∨ ¬ ∀ ∃ = Nat Int + * / BitVec Set ∈ Function List case simp ≤ Fin exact"
    seen = set()
    for offset in range(len(LOGIC_STRATEGIES)):
        rows = reduction_sweep("have unused : True := True.intro\nsimp [and_comm] at h\nexact h",
                               goal="p ∨ ¬ p", source=source, cap=4, offset=offset)
        assert 0 < len(rows) <= 4
        assert len({body for _, body, _ in rows}) == len(rows)
        seen.update(ops[0] for _, _, ops in rows)
    # These require specific structural patterns, exercised separately.
    assert set(LOGIC_STRATEGIES) - {"branch_invariant", "local_alias_reduce", "symmetry_reduce", "application_reduce", "eta_reduce"} <= seen
    assert reduction_sweep("exact h", cap=0) == []


def test_terminal_alias_and_symmetry_reductions_keep_operands_and_reject_nested_terms():
    from jevops.logic_refactor import reduction_variants

    assert reduction_variants("have copy : p := evidence\nexact copy", strategy="local_alias_reduce")[0][1] == "exact evidence"
    assert reduction_variants("have copy : p := by\n  exact evidence\nexact copy", strategy="local_alias_reduce") == []
    assert reduction_variants("symm\nexact Eq.symm h", strategy="symmetry_reduce")[0][1] == "exact h"
    assert reduction_variants("symm\nsymm\nexact h", strategy="symmetry_reduce")[0][1] == "exact h"


def test_unused_fact_analysis_is_conservative_about_layout_and_live_binders() -> None:
    assert structural_observations("have h : True := True.intro\nexact h")["unused_local_lines"] == []
    assert structural_observations("let n := f\n  arg\ntrivial")["unused_local_lines"] == []
    assert structural_observations("have unused : True := True.intro\ntrivial")["unused_local_lines"] == [0]
    assert reduction_variants("simp only [f (a, b), h]", strategy="simp_set_reduce") == []


def test_shared_simp_pruning_and_expensive_branch_prefixes_receive_early_budget() -> None:
    rows = reduction_variants("simp [Nat.add_zero, Nat.zero_add]\nsimp [Nat.add_zero, Nat.zero_add]",
                              strategy="simp_set_reduce", cap=2)
    assert len(rows) == 2 and all(kind == "shared_simp_lemma" for kind, _, _ in rows)
    assert "Nat.add_zero" not in rows[0][1] and rows[0][1].count("Nat.zero_add") == 2
    body = "cases h\ncase tiny =>\n  trivial\ncase expensive =>\n  simp [foo] at *\n  intro x\n  apply bar\n  exact h1\n  exact h2"
    rows = reduction_variants(body, strategy="branch_invariant", cap=1)
    assert len(rows) == 1 and rows[0][0] == "branch_prefix_closer"
    assert "simp [foo] at *" in rows[0][1] and "intro x" in rows[0][1]
    assert "case tiny =>\n  trivial" in rows[0][1] and "apply bar" not in rows[0][1]
    assert "case expensive =>\n  simp [foo] at *\n  intro x\n  grind" in rows[0][1]


def test_multiline_case_replacement_rebases_whole_block_and_preserves_nesting() -> None:
    from jevops.tactics import case_spans, replace_case_body

    original = "  case left =>\n    trivial\n  case right =>\n    trivial\n"
    span = case_spans(original)[0]
    for donor in ("intro h\nexact h", "      intro h\n      exact h\n"):
        assert replace_case_body(original, span, donor) == (
            "  case left =>\n    intro h\n    exact h\n  case right =>\n    trivial\n")
    nested = "      constructor\n      · exact h\n      · first\n        | exact h\n        | assumption\n"
    assert "    · first\n      | exact h\n      | assumption\n  case right" in replace_case_body(original, span, nested)


@requires_lean
def test_branch_prefix_and_closer_stay_in_case_scope_in_real_lean(tmp_path: Path) -> None:
    body = "cases b\ncase false =>\n  intro hp\n  exact hp\ncase true =>\n  intro hp\n  exact hp"
    kind, candidate, _ = reduction_variants(body, strategy="branch_invariant", cap=1)[0]
    assert kind == "branch_prefix_closer"
    compile_fn = _lean_compiler(project_root=tmp_path)
    source = theorem("branch_layout", "(b : Bool) (p : Prop)", "p → p", candidate)
    result = compile_fn(source)
    assert result["theorem_ok"], result


def test_local_edits_of_long_teachers_keep_a_bounded_line_allowance() -> None:
    source = theorem("long_teacher", "(h : True)", "True", "skip\n" * 80 + "exact h")
    calls = []
    loop = RouterTuningLoop({}, source, compile_fn=lambda s, **kw: calls.append(s) or {"theorem_ok": True},
                           router_generate=lambda _: "{}")
    body = "skip\n" * 80 + "assumption"
    rows = []
    loop._push(rows, set(), body, origin="llm_router_tactic", kind="draft",
               metadata={"rule_kind": "llm_router_tactic"})
    assert not rows and not calls  # Direct model text keeps its stricter cap.
    loop._push(rows, set(), body, origin="logic:simp_set_reduce", kind="local",
               metadata={"rule_kind": "logic_reduction"})
    assert len(rows) == 1 and len(calls) == 1
    for invalid in ("skip\n" * 200 + "assumption", "skip\n" * 80 + "sorry"):
        loop._push(rows, set(), invalid, origin="logic:test", kind="local",
                   metadata={"rule_kind": "logic_reduction"})
    assert len(rows) == 1 and len(calls) == 1


def test_router_summary_is_bounded_and_does_not_assume_its_own_goal() -> None:
    report = analysis_summary("p ∧ q")
    assert report["goal_consequences_not_hypotheses"]["forced"] == {"p": True, "q": True}
    assert report["authority"] == "search_hint_requires_Lean"
    report = analysis_summary("a ⊕ b ⊕ c ⊕ d ⊕ e ⊕ f ⊕ g ⊕ h")
    assert report["supported"]
    assert len(json.dumps(report)) < 3000
    assert report["normal_forms"]["dnf"]["lean"] is None
    assert report["normal_forms"]["dnf"]["lean_chars"] > 512


def test_goal_ir_preserves_parentheses_and_typed_quantifier_colons() -> None:
    for goal in ("((p ∧ q) ∨ (p ∧ ¬ q)) ↔ p", "∀ n : Nat, n = n", "(p → q) → p → q"):
        ir = ae.encode_lean_ir(theorem("header", "(p q : Prop)", goal, "simp_all"))
        assert ir["goal"] == goal
        assert ir["binders"] == ["(p q : Prop)"]


def test_router_ir_ops_replace_stale_script_instead_of_replaying_the_original() -> None:
    source = theorem("ops", "(h : True)", "True", "have hx : True := h\nexact hx")
    compiled = []

    def compile_fn(candidate: str, **_: object) -> dict:
        compiled.append(candidate)
        return {"theorem_ok": True}

    loop = RouterTuningLoop({}, source, compile_fn=compile_fn, router_generate=lambda _: "{}")
    rows = []
    loop._router_rows(parse_router_plan('{"candidates":[{"ops":[{"op":"trivial"}]}]}'),
                      rows, set(), source, max_new=1)
    assert len(rows) == 1 and len(compiled) == 1
    assert "trivial" in compiled[0] and "have hx" not in compiled[0] and "exact hx" not in compiled[0]
    assert compiled[0].split(":= by")[0] == source.split(":= by")[0]


def test_all_goals_combinator_does_not_create_dangling_angle_bracket_arguments() -> None:
    source = theorem("chain", "(p : Prop)", "p → p ∧ p", "intro h\nconstructor <;> exact h")
    ir = ae.encode_lean_ir(source)
    assert ir["ops"] == [{"op": "intro", "args": ["h"]}, {"op": "constructor"}, {"op": "exact", "args": ["h"]}]
    assert "constructor <;> exact h" in ae.decode_lean_ir(ir)
    ir = ae.encode_lean_ir("theorem induction_case (n : Nat) : True := by\n  induction n <;> trivial")
    assert ir["ops"] == [{"op": "induction", "args": ["n"]}, {"op": "trivial"}]


def test_model_diagnostics_use_predicted_body_inside_frozen_envelope() -> None:
    source = theorem("diagnostic", "(h : True)", "True", "have hx : True := h\nexact hx")
    prefix = source.split(":= by")[0]
    seen = []

    def compile_fn(candidate: str, **_: object) -> dict:
        seen.append(candidate)
        return {"theorem_ok": candidate.startswith(prefix) and "exact h" in candidate}

    loop = RouterTuningLoop({}, source, compile_fn=compile_fn, router_generate=lambda _: "{}")
    source_ir = ae.encode_lean_ir(source)
    prediction = ae._ir_with_ops(source_ir, [{"op": "exact", "args": ["h"]}])

    class FixedPrediction(LeanIRAutoencoder):
        def predict_ir(self, *args, **kwargs):
            return prediction

    report = loop._model_diagnostics(FixedPrediction(), coerce_training_example(source), phase="test")
    assert report["row"]["lake_ok"]
    assert seen and all(s.startswith(prefix) for s in seen)
    assert "have hx" not in seen[0] and "exact h" in seen[0]
    assert report["prediction"]["ops"] == prediction["ops"]


@requires_lean
def test_generated_boolean_certificates_compile_and_false_equivalence_fails(tmp_path: Path) -> None:
    compile_fn = _lean_compiler(project_root=tmp_path)
    source = "import Std\n"
    cases = [
        ("(p ∧ q) ∨ (p ∧ ¬ q)", "p", "True"),
        ("¬ (p ∨ q)", "¬ p ∧ ¬ q", "True"),
        ("(p ∧ q) ∨ (p ∧ r) ∨ (q ∧ ¬ r)", "(p ∧ r) ∨ (q ∧ ¬ r)", "True"),
        ("p ∨ q", "True", "p"),
    ]
    for i, (left, right, context) in enumerate(cases):
        source += theorem(f"cert{i}", "(p q r : Prop)", f"({context}) → (({left}) ↔ ({right}))",
                          equivalence_proof(left, right, assumptions=context))
    result = compile_fn(source)
    assert result["theorem_ok"], result
    bad = compile_fn(theorem("bad", "(p q : Prop)", "p ↔ q", equivalence_proof("p", "q")))
    assert not bad["theorem_ok"]
    goal = "((p ∧ q) ∨ (p ∧ ¬ q)) ↔ p"
    rows = reduction_variants("skip", strategy="boolean_minimize", goal=goal)
    assert any(kind.startswith("minimized_") for kind, _, _ in rows)
    batch = "import Std\n" + "\n".join(theorem(f"min{i}", "(p q : Prop)", goal, body)
                                        for i, (_, body, _) in enumerate(rows))
    result = compile_fn(batch)
    assert result["theorem_ok"], result


@requires_lean
def test_core_reduction_families_have_real_lean_witnesses(tmp_path: Path) -> None:
    fixtures = [
        ("logic_simp", "(p : Prop)", "p ∧ True ↔ p", "skip"),
        ("invariant_reduce", "(x y : Nat) (h : x = y)", "x = y", "skip"),
        ("quantifier_simp", "(P Q : Nat → Prop)", "(∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x)", "skip"),
        ("equality_congruence", "(x y : Nat) (h : x = y)", "x + 1 = y + 1", "skip"),
        ("ac_normalize", "(x y z : Nat)", "x + (y + z) = z + (x + y)", "skip"),
        ("arithmetic_linear", "(x y : Nat) (h : x ≤ y)", "x + 1 ≤ y + 1", "skip"),
        ("bitvector_decide", "(x : BitVec 8)", "x ^^^ x = 0", "skip"),
        ("function_extensionality", "(f : Nat → Nat)", "(fun x => f x) = f", "skip"),
        ("datatype_reduce", "(a b : Nat) (h : some a = some b)", "a = b", "skip"),
        ("structural_reduce", "", "True", "have unused : True := True.intro\ntrivial"),
        ("simp_set_reduce", "(n : Nat)", "n + 0 = n", "simp only [Nat.add_zero, Nat.zero_add]"),
        ("branch_invariant", "(p : Prop) (h : p ∨ p)", "p",
         "cases h\ncase inl hp =>\n  exact hp\ncase inr hp =>\n  exact hp"),
    ]
    # First proposal is deliberate here: covers actual emitted strategies,
    # not hand-authored proofs merely bearing the same label.
    source = "import Std.Tactic.BVDecide\n"
    for i, (strategy, binders, goal, body) in enumerate(fixtures):
        variants = reduction_variants(body, strategy=strategy, goal=goal)
        assert variants, strategy
        if strategy == "simp_set_reduce":
            chosen = next(text for _, text, _ in variants if "Nat.add_zero" in text and "Nat.zero_add" not in text)
        else:
            chosen = variants[0][1]
        source += theorem(f"family{i}", binders, goal, chosen)
    result = _lean_compiler(project_root=tmp_path)(source)
    assert result["theorem_ok"], result


@requires_lean
def test_logic_candidates_train_only_after_lean_and_keep_prediction_diagnostics(tmp_path: Path) -> None:
    source = theorem("training", "(p q : Prop) (hp : p)", "(p ∧ q) ∨ (p ∧ ¬ q)",
                     "classical\nby_cases hq : q\n· exact Or.inl ⟨hp, hq⟩\n· exact Or.inr ⟨hp, hq⟩")
    compiler = _lean_compiler(project_root=tmp_path)
    assert compiler(source)["theorem_ok"]
    memory = {"nca": {"grid": {}, "board_edges": []}}
    loop = RouterTuningLoop(memory, source, compile_fn=compiler, router_generate=lambda _: "{}",
                           config=RouterTuningConfig(max_candidate_pool=16, max_logic_candidates=12))
    rows, seen = [], set()
    loop._push(rows, seen, "exact False.elim (by trivial)", origin="deliberately_false", kind="invalid")
    count = loop._logic_reduction_rows(rows, seen, source, requested=["boolean_minimize"],
                                       max_new=10, round_index=0)
    assert 0 < count <= 10
    valid = [r for r in rows if r["lake_ok"]]
    assert valid and not rows[0]["lake_ok"]
    winner = min(valid, key=lambda r: r["body_tokens"])
    assert winner["body_tokens"] < ae.proof_body_token_count(source)
    assert all(r["source"].split(":= by")[0] == source.split(":= by")[0] for r in rows)
    report = loop._train(winner, rows)
    assert report["ok"] and report["teacher_example_count"] > 0, report
    assert all(r["origin"].startswith("logic:") for r in report["rule_examples"])
    assert {r["rule_id"] for r in report["rule_examples"]} <= {r["rule_id"] for r in valid}
    for loss in (report["loss"], report["model_loss_before"], report["candidate_target_loss"]):
        assert math.isfinite(loss["cross_entropy"]) and math.isfinite(loss["cosine_similarity"])
    assert report["model_prediction"]["origin"].startswith("autoencoder:")
    assert any(r["kind"] == "logic_reduction" for r in memory["nca"]["router_rules"])
