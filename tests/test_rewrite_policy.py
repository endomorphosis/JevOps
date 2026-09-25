from __future__ import annotations

import copy
import math
import re
import shutil

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import (AutoencoderConfig, LeanIRAutoencoder, canary_gate,
                                         coerce_training_example, evaluate_model, evaluate_stream_split)
from jevops.rewrite_policy import body_of, choices, decode, loss_and_gradient, mine_template, validate_templates
from jevops.router_tuning import _lean_compiler


def pair(name="sample", prop="p", hyp="h"):
    source = f"theorem {name} ({prop} : Prop) ({hyp} : {prop}) : {prop} := by\n  exact {hyp}"
    target = source.replace(f"exact {hyp}", "assumption")
    return source, target


def example(source, target):
    return coerce_training_example({"text": source, "target_ir": ae.encode_lean_ir(target)})


def test_templates_copy_new_local_names_and_zero_weights_are_identity():
    source, target = pair()
    bank = validate_templates([mine_template(source, body_of(target)[1])])
    unseen, _ = pair("different", "q", "evidence")
    assert choices(unseen, bank)[1]["body"] == "assumption"
    assert decode(unseen, bank, {})["body"] == "exact evidence"
    constant = "theorem t : True := by\n  exact True.intro"
    assert len(choices(constant, bank)) == 1
    hostile = "theorem t : True := by\n  run_tac sorry"
    assert len(choices(hostile, bank)) == 1


def test_copy_slots_preserve_repeated_identifiers_and_target_does_not_supply_free_locals():
    source = "theorem t (p : Prop) (h : p) : p := by\n  have alias : p := h\n  exact alias"
    bank = [mine_template(source, "exact h")]
    renamed = re.sub(r"\bh\b", "evidence", source.replace("alias", "new_alias"))
    assert choices(renamed, bank)[1]["body"] == "exact evidence"
    assert len(choices(renamed.replace("exact new_alias", "exact evidence"), bank)) == 1
    # A new reference to a local not in the matched span cannot be memorized.
    other = "theorem t (p : Prop) (h k : p) : p := by\n  exact h"
    assert mine_template(other, "exact k") is None


def test_let_deletion_retains_continuation_and_does_not_match_a_required_witness():
    source = "theorem t (x : Nat) : x = x := by\n  let y := x\n  rfl"
    rule = mine_template(source, "rfl")
    assert rule["lines"] == 2
    bank = validate_templates([rule])
    renamed = source.replace("let y := x", "let alias := x")
    assert choices(renamed, bank)[1]["body"] == "rfl"
    for continuation in ("exact Eq.refl y", "exact ⟨y, rfl⟩"):
        assert len(choices(source.rsplit("rfl", 1)[0] + continuation, bank)) == 1
    # Keep ALL unchanged continuation, not only the next line. This tests the
    # lexical miner, not validity of these deliberately schematic proof bodies.
    long_source = source + "\n  exact y"
    full = mine_template(long_source, "rfl\nexact y")
    assert full["lines"] == 3
    assert len(choices(source, [full])) == 1
    assert choices(long_source, [full])[1]["body"] == "rfl\nexact y"


def test_let_deletion_abstains_without_bounded_same_scope_continuation():
    prefix = "theorem t (x : Nat) : x = x := by\n"
    assert mine_template(prefix + "  rfl\n  let y := x", "rfl") is None
    tail = "\n".join(["skip"] * 7 + ["rfl"])
    assert mine_template(prefix + "  let y := x\n" + "\n".join("  " + s for s in tail.splitlines()), tail) is None
    source = prefix + "  constructor\n  case left =>\n    let y := x\n    rfl\n  case right => trivial"
    target = "constructor\ncase left =>\n  rfl\ncase right => trivial"
    assert mine_template(source, target) is None


def test_atomic_vs_partial_rewrite_ce_cosine_gradient_matches_finite_differences():
    prefix = "theorem t (x : Nat) : x = x := by\n"
    source = prefix + "  let y := x\n  exact Eq.refl y"
    bank = [mine_template(prefix + "  exact Eq.refl x", "rfl"), mine_template(source, "rfl")]
    candidates = choices(source, bank)
    assert {c["body"] for c in candidates} == {body_of(source)[1], "let y := x\nrfl", "rfl"}
    weights = {k: .12 for c in candidates for k in c["features"]}
    objective = lambda w: loss_and_gradient(w, candidates, "rfl", smoothing=.1, cosine_weight=.4)
    result = objective(weights)
    for key in weights:
        plus = objective({**weights, key: weights[key]+1e-5})["total"]
        minus = objective({**weights, key: weights[key]-1e-5})["total"]
        assert result["gradient"][key] == pytest.approx((plus-minus)/2e-5, abs=1e-7)


@pytest.mark.parametrize("temperature", [.5, 1.0, 2.0])
def test_edit_ce_and_expected_cosine_gradient_matches_finite_differences(temperature):
    source, target = pair()
    bank = [mine_template(source, body_of(target)[1])]
    rows = choices(source, bank)
    weights = {k: .12 for k in rows[1]["features"]}
    def objective(w):
        return loss_and_gradient(w, rows, "assumption", temperature=temperature,
                                 smoothing=.1, cosine_weight=.4)
    result = objective(weights)
    for key in weights:
        plus = objective({**weights, key: weights[key]+1e-5})["total"]
        minus = objective({**weights, key: weights[key]-1e-5})["total"]
        assert result["gradient"][key] == pytest.approx((plus-minus)/2e-5, abs=1e-7)
    assert loss_and_gradient(weights, rows, "rfl") is None
    with_trivia = [{**row, "body": "\n" + row["body"] + "\n\n"} for row in rows]
    assert loss_and_gradient(weights, with_trivia, "assumption") is not None


def test_learned_replacement_roundtrip_inference_is_read_only_and_ablatable():
    source, target = pair()
    row = example(source, target)
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True, warmup_steps=0))
    preparation = model.prepare_rewrite_training([row])
    assert preparation["requires_new_edit_ce_baseline"]
    before = model.rewrite_objective(row)
    for _ in range(20):
        model.train_example(row)
    assert model.rewrite_objective(row)["cross_entropy"] < before["cross_entropy"]
    unseen, _ = pair("unseen", "r", "proof")
    frozen = model.to_dict()
    emitted = model.predict_ir(unseen)
    assert emitted["ops"] == [{"op": "assumption"}]
    assert not emitted["rewrite_policy"]["teacher_used"]
    assert not emitted["rewrite_policy"]["solver_used"]
    assert model.to_dict() == frozen
    restored = LeanIRAutoencoder.from_dict(frozen)
    assert ae.decode_lean_ir(restored.predict_ir(unseen)) == ae.decode_lean_ir(emitted)
    restored.state["rewrite_weights"] = {}
    assert restored.predict_ir(unseen)["ops"] == [{"op": "exact", "args": ["proof"]}]
    assert not restored.predict_ir(unseen)["rewrite_policy"]["trace"]
    legacy = model.predict_ir(unseen, rewrite_policy=False)
    assert "rewrite_policy" not in legacy


def test_edit_cross_entropy_stays_correct_when_a_probability_underflows():
    rows = [{"body": "exact h", "features": {}}, {"body": "assumption", "features": {"bias": 1.0}}]
    result = loss_and_gradient({"bias": -1000.0}, rows, "assumption", cosine_weight=0)
    assert result["cross_entropy"] == 1000.0
    assert result["gradient"]["bias"] == -1.0


def test_edit_only_training_preserves_all_reconstruction_weights_and_ce():
    source, target = pair()
    config = AutoencoderConfig(train_rewrite_policy=True, freeze_reconstruction_heads=True, warmup_steps=0)
    model = LeanIRAutoencoder(config=config)
    row = example(source, target)
    model.prepare_rewrite_training([row])
    before = model.to_dict()
    ce = model._sequence_loss(row)
    for _ in range(10):
        report = model.train_example(row)
        assert report["gradient_norm"] == report["latent_gradient_norm"] == 0
    for key in ("op_bias", "transition", "feature_op", "latent_bias", "feature_latent", "vocab"):
        assert model.to_dict()[key] == before[key]
    assert model._sequence_loss(row) == ce
    assert model.predict_ir(source)["ops"] == [{"op": "assumption"}]
    assert model.rewrite_objective(row)["cross_entropy"] < .5
    assert AutoencoderConfig(**config.to_dict()).freeze_reconstruction_heads
    with pytest.raises(ValueError, match="requires rewrite"):
        AutoencoderConfig(freeze_reconstruction_heads=True)


def test_editor_preserves_case_layout_and_never_mutates_the_statement():
    source, target = pair()
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True, warmup_steps=0))
    row = example(source, target)
    model.prepare_rewrite_training([row])
    model.train_example(row)
    nested = "theorem branches (n : Nat) : n = n := by\n  induction n\n  case zero =>\n    rfl\n  case succ k ih =>\n    exact congrArg Nat.succ ih"
    # The general exact-term case is intentionally outside the single-local template.
    assert not model.predict_ir(nested)["rewrite_policy"]["trace"]
    nested = "theorem branches (n : Nat) (p : Prop) (h : p) : p := by\n  cases n\n  case zero =>\n    exact h\n  case succ k =>\n    exact h"
    prediction = model.predict_ir(nested)
    rendered = ae.decode_lean_ir(prediction)
    assert "case succ k =>\n    assumption" in rendered
    assert "case zero =>\n    assumption" in rendered
    assert prediction["goal"] == "p" and prediction["binders"] == ae.encode_lean_ir(nested)["binders"]


def test_template_loading_envelope_migration_and_shard_merging_fail_closed():
    source, target = pair()
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True))
    before = model.to_dict()
    wrong = example(source, target.replace(": p :=", ": True :="))
    with pytest.raises(ValueError, match="envelope"):
        model.prepare_rewrite_training([wrong])
    assert model.to_dict() == before
    model.prepare_rewrite_training([example(source, target)])
    damaged = model.to_dict()
    damaged["rewrite_templates"][0]["after"] = ["sorry"]
    with pytest.raises(ValueError):
        LeanIRAutoencoder.from_dict(damaged)
    with pytest.raises(ValueError, match="grammars"):
        ae.merge_model_states([model.to_dict(), before])
    merged = ae.merge_model_states([model.to_dict(), model.to_dict()])
    assert merged["rewrite_templates"] == model.state["rewrite_templates"]


def test_edit_metrics_have_coverage_and_canary_gate_cannot_ignore_regression():
    source, target = pair()
    row = example(source, target)
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True))
    model.prepare_rewrite_training([row])
    report = evaluate_model(model, [row])
    streamed = evaluate_stream_split(model, [row], split="canary")
    assert report["rewrite_sample_count"] == streamed["rewrite_sample_count"] == 1
    assert report["rewrite_cross_entropy"] == streamed["rewrite_cross_entropy"] == pytest.approx(math.log(2))
    for corrupted in ({"rewrite_cross_entropy": None}, {"rewrite_cross_entropy": 99},
                      {"rewrite_sample_count": 0}, {"rewrite_expected_cosine_loss": float("nan")}):
        assert not canary_gate(report, {**report, **corrupted})["accepted"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_accepts_learned_unseen_edit_with_strict_audit(tmp_path):
    source, target = pair()
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True)
    assert compiler(source)["theorem_ok"] and compiler(target)["theorem_ok"]
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True, warmup_steps=0))
    row = example(source, target)
    model.prepare_rewrite_training([row])
    model.train_example(row)
    fresh, _ = pair("new_proof", "new_prop", "new_evidence")
    prediction = ae.decode_lean_ir(model.predict_ir(fresh))
    receipt = compiler(prediction)
    assert receipt["theorem_ok"] and receipt["kernel_audit"]["accepted"]
    assert ae.proof_body_token_count(prediction) < ae.proof_body_token_count(fresh)
