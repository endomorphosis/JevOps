from __future__ import annotations

import math

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import _canonical_ops, canary_gate, evaluate_model, evaluate_stream_split
from jevops.binding_policy import FEATURES, loss_and_gradient, source_features, subsequence_labels
from jevops.training_probe import probe_rows


def test_alignment_is_argument_sensitive_and_declines_ambiguous_duplicates() -> None:
    assert subsequence_labels([("exact", ["h"])], [("exact", ["k"])]) is None
    assert subsequence_labels([("simp", []), ("simp", [])], [("simp", [])]) is None
    assert subsequence_labels([("have", ["x := h"]), ("exact", ["h"])], [("exact", ["h"])]) == [0, 1]
    source = [("exact", ["h"])] * 300
    assert subsequence_labels(source, source) is None


def test_source_features_are_alpha_invariant_and_distinguish_dead_and_live_chains() -> None:
    def features(first, second, closer):
        body = f"have {first} : True := True.intro\nhave {second} : True := {first}\nexact {closer}"
        ir = ae.encode_lean_ir("theorem test (h : True) : True := by\n" + body)
        return source_features(body, _canonical_ops(ir))

    assert features("a", "b", "b") == features("α", "β", "β")
    live, dead = features("a", "b", "b"), features("a", "b", "h")
    assert all(r["features"]["reaches_root"] for r in live["rows"])
    assert not any(r["features"]["reaches_root"] for r in dead["rows"])


def test_binary_cross_entropy_gradient_matches_finite_difference() -> None:
    weights = dict.fromkeys(FEATURES, .2)
    rows = [{"index": 0, "features": {"bias": 1.0, "reaches_root": 1.0}},
            {"index": 1, "features": {"bias": 1.0, "no_users": 1.0}}]
    loss, gradient = loss_and_gradient(weights, rows, [1, 0])
    assert math.isfinite(loss)
    for key in FEATURES:
        plus = loss_and_gradient({**weights, key: weights[key] + 1e-5}, rows, [1, 0])[0]
        minus = loss_and_gradient({**weights, key: weights[key] - 1e-5}, rows, [1, 0])[0]
        assert gradient[key] == pytest.approx((plus - minus) / 2e-5, abs=1e-8)


def trained_model():
    model = ae.LeanIRAutoencoder(config=ae.AutoencoderConfig(train_binding_policy=True,
                                learning_rate=.2, warmup_steps=0, decay_steps=1000))
    rows = probe_rows(curriculum="balanced")
    examples = [ae.coerce_training_example({"text": r["text"], "target_ir": ae.encode_lean_ir(r["target"])})
                for r in rows if r["split"] == "train"]
    before = [model.binding_cross_entropy(e) for e in examples]
    for _ in range(40):
        model.train_batch(examples)
    assert model.state["binding_steps"] == 160
    assert sum(model.binding_cross_entropy(e) for e in examples) < sum(before)
    return model


def test_raw_binding_policy_is_learned_and_not_the_post_decode_guard() -> None:
    model = trained_model()
    for row in probe_rows():
        if row["split"] == "train":
            continue
        predicted = model.predict_ir(row["text"], dependency_guard=False)
        assert predicted["binding_policy"]["mode"] == "learned_binding_keep"
        assert predicted["ops"] == ae.encode_lean_ir(row["target"])["ops"], row["id"]
        assert not predicted["dependency_guard"]["enabled"]
    control = next(r for r in probe_rows() if r["id"] == "live_binding")
    model.state["binding_weights"] = dict.fromkeys(FEATURES, 0.0)
    model.state["binding_weights"]["bias"] = -10
    raw = model.predict_ir(control["text"], dependency_guard=False)
    guarded = model.predict_ir(control["text"])
    assert len(raw["ops"]) == 1 and len(guarded["ops"]) == 2
    assert guarded["dependency_guard"]["restored"]


def test_binding_head_roundtrips_and_merges_without_changing_predictions() -> None:
    model = trained_model()
    state = model.to_dict()
    restored = ae.LeanIRAutoencoder.from_dict(state)
    assert restored.to_dict() == state
    merged = ae.LeanIRAutoencoder.from_dict(ae.merge_model_states([state, state]))
    assert merged.state["binding_steps"] == 320
    assert merged.state["binding_weights"] == state["binding_weights"]
    legacy = dict(state)
    legacy.pop("binding_steps")
    legacy.pop("binding_weights")
    assert not ae.LeanIRAutoencoder.from_dict(legacy).state["binding_steps"]
    for row in probe_rows():
        assert restored.predict_ir(row["text"])["ops"] == merged.predict_ir(row["text"])["ops"]


def test_unaligned_targets_do_not_update_the_binding_classifier() -> None:
    model = ae.LeanIRAutoencoder(config=ae.AutoencoderConfig(train_binding_policy=True))
    source = "theorem test (h : True) : True := by\n  have hx : True := h\n  exact hx"
    example = ae.coerce_training_example({"text": source, "target_ir": ae.encode_lean_ir("trivial")})
    model.train_example(example)
    assert model.state["binding_steps"] == 0


def test_ir_exact_match_does_not_ignore_operands() -> None:
    model = ae.LeanIRAutoencoder()
    example = ae.coerce_training_example("exact h")
    loss = ae.loss_for_example(model, example, predicted_ir=ae.encode_lean_ir("exact k"))
    assert loss.ir_exact_match == 0.0


def test_binding_bce_remains_finite_and_gradient_consistent_at_saturation() -> None:
    rows = [{"index": 0, "features": {"bias": 1.0}}]
    for bias, label, expected in [(1000.0, 0, 1.0), (-1000.0, 1, -1.0)]:
        loss, gradient = loss_and_gradient({"bias": bias}, rows, [label])
        assert loss == pytest.approx(1000.0)
        assert gradient["bias"] == expected
        plus = loss_and_gradient({"bias": bias + .001}, rows, [label])[0]
        minus = loss_and_gradient({"bias": bias - .001}, rows, [label])[0]
        assert gradient["bias"] == pytest.approx((plus - minus) / .002)


def test_binding_loss_aggregation_and_coverage_match_in_batch_and_stream() -> None:
    model = trained_model()
    examples = [ae.coerce_training_example({"text": r["text"], "target_ir": ae.encode_lean_ir(r["target"])}, i)
                for i, r in enumerate(probe_rows(curriculum="balanced")) if r["split"] == "train"]
    examples.append(ae.coerce_training_example("trivial", len(examples)))
    batch = evaluate_model(model, examples)
    stream = evaluate_stream_split(model, iter(examples), split="test")
    assert batch["binding_sample_count"] == stream["binding_sample_count"] == 4
    assert batch["binding_cross_entropy"] == pytest.approx(stream["binding_cross_entropy"])
    assert batch["binding_cross_entropy"] == pytest.approx(
        sum(model.binding_cross_entropy(e) for e in examples[:-1]) / 4)
    assert canary_gate(batch, stream)["accepted"]
    assert evaluate_model(model, [])["binding_cross_entropy"] is None
    assert evaluate_stream_split(model, [], split="test")["binding_sample_count"] == 0


@pytest.mark.parametrize("changes,reason", [
    ({"binding_cross_entropy": .4}, "binding_cross_entropy"),
    ({"binding_cross_entropy": None}, "binding_coverage_changed"),
    ({"binding_sample_count": 1}, "binding_coverage_changed"),
    ({"binding_cross_entropy": float("nan")}, "binding_cross_entropy_not_finite"),
    ({"sample_count": 0}, "sample_coverage_changed"),
    ({"verifier_success_rate": .5}, "verifier_success_rate"),
    ({"verifier_evaluated_count": 1}, "verifier_coverage_changed"),
])
def test_canary_gate_rejects_binding_and_verifier_regressions(changes, reason) -> None:
    before = {"sample_count": 2, "cross_entropy": 1.0, "binding_cross_entropy": .2,
              "binding_sample_count": 2, "cosine_similarity": .8, "reconstruction_loss": .1,
              "verifier_evaluated_count": 2, "verifier_success_rate": 1.0}
    result = canary_gate(before, {**before, "cross_entropy": .8, "cosine_similarity": .9, **changes})
    assert not result["accepted"] and reason in result["regressions"]
