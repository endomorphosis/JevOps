from __future__ import annotations

from dataclasses import replace
import itertools
import os
from pathlib import Path

import pytest

from jevops.linear_invariants import (LinearInequality as L, imply, infer_linear_invariants,
                                      implication_obligation, pullback, reduce_constraints, verify_certificate)
from jevops.router_tuning import _lean_compiler


def test_exact_certificates_include_fractional_weights_and_reject_tampering():
    premises, target = [L((2,), 4)], L((1,), 3)
    proof = imply(premises, target)
    assert proof["proved"] and proof["certificate"] == {"weights": ["1/2"], "slack": "1"}
    assert verify_certificate(premises, target, proof["certificate"])
    for broken in ({"weights": ["-1/2"], "slack": "5"}, {"weights": ["1/2"], "slack": "0"},
                   {"weights": ["NaN"], "slack": "1"}, {"weights": ["1/0"], "slack": "1"}):
        assert not verify_certificate(premises, target, broken)
    assert not verify_certificate(premises, replace(target, coefficients=(2,)), proof["certificate"])


def test_certificate_search_is_conservative_about_integer_rounding_and_budgets():
    # True for integers, but not implied over the rational relaxation.
    assert imply([L((2,), 1)], L((1,), 0))["status"] == "unknown_no_certificate"
    assert imply([L((1, 0), 0), L((0, 1), 0)], L((1, 1), 0), max_combinations=1)["status"] == "unknown_budget"
    with pytest.raises(ValueError):
        L((True,), 0)
    with pytest.raises(ValueError):
        imply([L((1, 0), 0)], L((1,), 0))
    with pytest.raises(ValueError):
        pullback(L((1,), 0), [[1, 0]], [0])


def test_redundancy_deletion_preserves_conjunction_on_exhaustive_small_grid():
    constraints = [L((1, 0), 0), L((0, 1), 0), L((1, 1), 0), L((2, 2), 1)]
    result = reduce_constraints(constraints)
    assert result["kept_indices"] == [0, 1]
    for state in itertools.product(range(-3, 4), repeat=2):
        satisfies = lambda rows: all(sum(a*x for a, x in zip(c.coefficients, state)) <= c.bound for c in rows)
        assert satisfies(constraints) == satisfies([constraints[i] for i in result["kept_indices"]])
    for removed in result["removed"]:
        assert verify_certificate([constraints[i] for i in removed["premise_indices"]],
                                  constraints[removed["index"]], removed["certificate"])
    assert not result["lean_verified"]


def system():
    initial = [L((1, 0), 0), L((-1, 0), 0), L((0, 1), 0), L((0, -1), 0)]
    candidates = [L((1, -1), 0), L((-1, 1), 0), L((-1, 0), 0), L((1, 0), 5)]
    return infer_linear_invariants(initial, [], candidates, [[1, 0], [0, 1]], [1, 1])


def test_guarded_unbounded_integer_invariants_and_fixed_point_removal():
    report = system()
    assert report["kept_indices"] == [0, 1, 2]
    assert report["removed"][0]["index"] == 3
    assert not report["complete"] and not report["source_program_binding_verified"]
    for row in report["obligations"]:
        assert verify_certificate([L(**p) for p in row["premises"]], L(**row["target"]), row["certificate"])
    guarded = infer_linear_invariants([L((1,), 0)], [L((1,), 4)], [L((1,), 5)], [[1]], [1])
    assert guarded["kept_indices"] == [0]
    mutual = infer_linear_invariants([L((1, 0), 0), L((0, 1), 0)], [],
                                     [L((1, 0), 0), L((0, 1), 0)], [[1, 1], [0, 1]], [0, 1])
    assert mutual["kept_indices"] == []
    assert {r["round"] for r in mutual["removed"]} == {1, 2}


@pytest.mark.skipif(not os.environ.get("JEVOPS_MATHLIB_PROJECT"), reason="requires pinned Mathlib project")
def test_real_lean_checks_linear_initiation_preservation_and_redundancy():
    compiler = _lean_compiler(project_root=Path(os.environ["JEVOPS_MATHLIB_PROJECT"]),
                              use_lake=True, kernel_only=True, timeout=60)
    report = system()
    reduced = reduce_constraints([L((1, 0), 0), L((0, 1), 0), L((1, 1), 0)])
    source = "import Mathlib\n" + "\n".join(r["lean"] for r in report["obligations"])
    source += "\n" + "\n".join(r["obligation"] for r in reduced["removed"])
    receipt = compiler(source)
    assert receipt["theorem_ok"] and receipt["kernel_audit"]["accepted"], receipt
    # Lean, not a Python claim, rejects the stronger false invariant.
    bad = compiler("import Mathlib\ntheorem invalid (x : Int) (h : x ≤ 5) : x + 1 ≤ 5 := by\n  linarith only [h]\n")
    assert not bad["theorem_ok"]


@pytest.mark.skipif(not os.environ.get("JEVOPS_MATHLIB_PROJECT"), reason="requires pinned Mathlib project")
def test_autoencoder_learns_verified_certificate_support_compression():
    from jevops import autoencoder as ae
    from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example
    from jevops.router_tuning import _ir_body, _render_source, _source_parts

    premises, target = [L((1, 0), 0), L((0, 1), 0), L((0, 0), 42)], L((1, 1), 0)
    result = imply(premises, target)
    assert result["proved"]
    teacher_body = implication_obligation(premises, target, result["certificate"]).split(":= by\n")[1].strip()
    header = "import Mathlib\ntheorem learned_linear (x0 x1 : Int) "
    header += " ".join(f"(h{i} : {p.lean()})" for i, p in enumerate(premises))
    header += f" : {target.lean()} := by\n  "
    source, teacher = header + "linarith only [h0, h1, h2]", header + teacher_body
    compiler = _lean_compiler(project_root=Path(os.environ["JEVOPS_MATHLIB_PROJECT"]), use_lake=True,
                              kernel_only=True, timeout=60)
    for text in (source, teacher):
        receipt = compiler(text)
        assert receipt["theorem_ok"] and receipt["kernel_audit"]["accepted"], receipt
    config = AutoencoderConfig(train_rewrite_policy=True, freeze_reconstruction_heads=True, warmup_steps=0)
    model = LeanIRAutoencoder(config=config)
    example = coerce_training_example({"text": source, "target_ir": ae.encode_lean_ir(teacher)})
    model.prepare_rewrite_training([example])
    before, ce = model.rewrite_objective(example), model._sequence_loss(example)
    for _ in range(20):
        model.train_example(example)
    fresh = source.replace("learned_linear", "fresh_linear").replace("h0", "ha").replace("h1", "hb").replace("h2", "hc")
    prediction = model.predict_ir(fresh)
    prefix, _, theorem = _source_parts(fresh)
    rendered = _render_source(prefix, _ir_body(prediction), has_theorem=theorem)
    receipt = compiler(rendered)
    assert receipt["theorem_ok"] and receipt["kernel_audit"]["accepted"], receipt
    assert ae.proof_body_token_count(rendered) < ae.proof_body_token_count(fresh)
    assert model._sequence_loss(example) == ce
    assert model.rewrite_objective(example)["cross_entropy"] < before["cross_entropy"]
    model.state["rewrite_weights"] = {}
    assert not model.predict_ir(fresh)["rewrite_policy"]["trace"]
