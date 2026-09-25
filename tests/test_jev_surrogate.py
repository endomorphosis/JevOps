from __future__ import annotations

import copy
from dataclasses import replace
import math
import shutil

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example
from jevops.jev_surrogate import (JeVFeedbackSpec, bind_feedback, collect_feedback, digest,
                                  expected_utility_gradient, feedback_utilities)
from jevops.rewrite_policy import choices, probabilities


SOURCE = "theorem sample (p : Prop) (h : p) : p := by\n  exact h"
TARGET = SOURCE.replace("exact h", "assumption")


def spec():
    return JeVFeedbackSpec(digest({"environment": "offline-unit-fixture"}),
                           "fixture-jev/v1", "repair-utility/v1", {"0": -1.0, "2": 0.0, "4": 1.0})


def model_and_example(*, invalid_edit=False):
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True,
                              freeze_reconstruction_heads=True, warmup_steps=0))
    example = coerce_training_example({"text": SOURCE, "target_ir": ae.encode_lean_ir(TARGET)})
    model.prepare_rewrite_training([example])
    if invalid_edit:
        # This rule is valid for the seed's False hypothesis but does not
        # generalize to an arbitrary p. Lexical applicability is not validity.
        seed = "theorem seed (h : False) : False := by\n  exact h"
        pair = coerce_training_example({"text": seed,
                "target_ir": ae.encode_lean_ir(seed.replace("exact h", "exact False.elim h"))})
        model.prepare_rewrite_training([pair])
    return model, example


def request_and_receipt(model, *, preferred="assumption", specification=None):
    specification = specification or spec()
    request = model.jev_feedback_request(SOURCE, spec=specification, split="train")
    scores = {r["id"]: 4 if preferred in r["lean"] else 0 for r in request["variations"]}
    return request, bind_feedback(request, {"scores": scores, "noul": 0.25})


@pytest.mark.parametrize("temperature", [.05, .5, 1.0, 2.0])
@pytest.mark.parametrize("kl_weight", [0.0, .3])
def test_expected_utility_and_reference_kl_gradient_matches_finite_difference(temperature, kl_weight):
    rows = [{"features": {}}, {"features": {"a": 1.0, "shared": .2}},
            {"features": {"b": -.5, "shared": 1.0}}]
    weights, reference = {"a": .12, "b": -.08, "shared": .03}, {"a": -.1, "shared": .01}

    def objective(w):
        return expected_utility_gradient(w, rows, [-.7, .3, .9], temperature=temperature,
                                         reference_weights=reference, kl_weight=kl_weight)

    result = objective(weights)
    for key in weights:
        plus = objective({**weights, key: weights[key] + 1e-6})["total"]
        minus = objective({**weights, key: weights[key] - 1e-6})["total"]
        assert result["gradient"][key] == pytest.approx((plus-minus)/2e-6, abs=1e-7)


def test_constant_rewards_identity_and_underflow_are_well_defined():
    rows = [{"features": {}}, {"features": {"a": 1.0}}]
    assert expected_utility_gradient({"a": .23}, rows, [.1, .1])["gradient"] == {"a": 0.0}
    assert expected_utility_gradient({}, rows[:1], [1.0])["gradient"] == {}
    result = expected_utility_gradient({"a": 1000.0}, rows, [0., 1.],
                                      reference_weights={"a": -1000.}, kl_weight=.1)
    assert math.isfinite(result["total"]) and result["reference_kl"] == pytest.approx(1000.)
    assert all(math.isfinite(v) for v in result["gradient"].values())


@pytest.mark.parametrize("overrides", [
    {"utilities": []}, {"utilities": [float("nan"), 1.]}, {"utilities": [0., 2.]},
    {"utilities": [False, 1.]}, {"temperature": 0}, {"temperature": float("inf")},
    {"kl_weight": .2}, {"kl_weight": -1.}, {"weights": {"a": float("nan")}},
    {"rows": [{"features": {"a": float("inf")}}, {"features": {}}]},
])
def test_gradient_rejects_malformed_domains(overrides):
    args = {"weights": {}, "rows": [{"features": {}}, {"features": {"a": 1.}}], "utilities": [0., 1.]}
    with pytest.raises(ValueError):
        expected_utility_gradient(**{**args, **overrides})


def test_spec_is_bounded_immutable_and_not_a_probability_rubric():
    raw = {"low": -1., "high": 1.}
    config = replace(spec(), utilities=raw)
    raw["low"] = .5
    assert config.utilities["low"] == -1.
    with pytest.raises(TypeError):
        config.utilities["low"] = 1.
    for kwargs in ({"context_sha256": "unpinned"}, {"scorer_id": ""},
                   {"utilities": {"x": True}}, {"utilities": {"x": float("nan")}},
                   {"utilities": {"x": 1.01}}):
        with pytest.raises(ValueError):
            replace(config, **kwargs)


def test_request_and_provider_are_read_only_and_scores_are_bound_by_id():
    model, _ = model_and_example()
    before = model.to_dict()
    request = model.jev_feedback_request(SOURCE, spec=spec(), split="train")
    original = copy.deepcopy(request)

    def scorer(payload):
        assert payload == original
        scores = {r["id"]: 4.0 if "assumption" in r["lean"] else 0 for r in reversed(payload["variations"])}
        payload["source"] = "provider must not mutate the original"
        return {"scores": scores, "theorem_ok": True, "noul": .9}

    receipt = collect_feedback(request, scorer)
    assert request == original and model.to_dict() == before
    assert feedback_utilities(request, receipt) == [-1., 1.]
    assert "theorem_ok" not in receipt and receipt["noul"] == .9
    assert receipt["authority"] == "surrogate_only"


@pytest.mark.parametrize("kind", ["missing", "partial", "extra_id", "nan", "infinity", "boolean",
                                  "unknown_label", "fractional", "choice_only", "abstain", "bad_abstain",
                                  "bad_noul", "wrong_request", "wrong_scorer", "not_mapping"])
def test_bad_or_abstained_feedback_never_updates_weights(kind):
    model, _ = model_and_example()
    request, valid = request_and_receipt(model)
    scores = dict(valid["scores"])
    first = next(iter(scores))
    response = {"scores": scores}
    if kind == "missing":
        response = {}
    elif kind == "partial":
        scores.pop(first)
    elif kind == "extra_id":
        scores["foreign-candidate"] = 4
    elif kind in {"nan", "infinity", "boolean", "unknown_label", "fractional"}:
        scores[first] = {"nan": float("nan"), "infinity": float("inf"), "boolean": True,
                         "unknown_label": "99", "fractional": .5}[kind]
    elif kind == "choice_only":
        response = {"choice": first}
    elif kind == "abstain":
        response["abstain"] = True
    elif kind == "bad_abstain":
        response["abstain"] = "false"
    elif kind == "bad_noul":
        response["noul"] = 2.
    elif kind == "wrong_request":
        response["request_id"] = "foreign-request"
    elif kind == "wrong_scorer":
        response["scorer_id"] = "other-scorer"
    else:
        response = None
    receipt = bind_feedback(request, response)
    assert receipt["status"] != "scored"
    before = model.to_dict()
    report = model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", weight=.3)
    assert not report["updated"] and not report["proof_admitted"] and not report["teacher_created"]
    assert model.to_dict() == before


def test_scorer_errors_are_redacted_and_receipt_tampering_is_rejected():
    model, _ = model_and_example()
    request, receipt = request_and_receipt(model)
    def broken(_):
        raise RuntimeError("do not leak provider credentials")
    failed = collect_feedback(request, broken)
    assert failed["reason"] == "scorer_error" and "credentials" not in str(failed)
    receipt["scores"][next(iter(receipt["scores"]))] = "4"
    before = model.to_dict()
    report = model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", weight=.3)
    assert report["reason"] == "invalid_receipt_digest" and model.to_dict() == before


@pytest.mark.parametrize("change", ["source", "context", "scorer", "rubric_id", "rubric_mapping",
                                    "policy", "step", "temperature", "grammar"])
def test_feedback_cannot_cross_request_boundaries(change):
    model, _ = model_and_example()
    _, receipt = request_and_receipt(model)
    source, specification = SOURCE, spec()
    if change == "source":
        source = SOURCE.replace("sample", "different")
    elif change == "context":
        specification = replace(specification, context_sha256=digest("other-environment"))
    elif change == "scorer":
        specification = replace(specification, scorer_id="other/v1")
    elif change == "rubric_id":
        specification = replace(specification, rubric_id="other/v1")
    elif change == "rubric_mapping":
        specification = replace(specification, utilities={"0": 1., "2": 0., "4": -1.})
    elif change == "policy":
        model.state["rewrite_weights"]["new-key"] = .1
    elif change == "step":
        model.state["step"] += 1
    elif change == "temperature":
        model.config = replace(model.config, temperature=.5)
    elif change == "grammar":
        model.state["rewrite_templates"] = []
    before = model.to_dict()
    result = model.train_jev_feedback(source, receipt, spec=specification, split="train", weight=.3)
    assert result["reason"] == "stale_or_mismatched_feedback" and model.to_dict() == before


@pytest.mark.parametrize("split", ["development", "validation", "holdout", "canary", "test"])
def test_nontraining_splits_cannot_be_scored_or_updated(split):
    model, _ = model_and_example()
    _, receipt = request_and_receipt(model)
    before = model.to_dict()
    with pytest.raises(ValueError, match="training-only"):
        model.jev_feedback_request(SOURCE, spec=spec(), split=split)
    report = model.train_jev_feedback(SOURCE, receipt, spec=spec(), split=split, weight=.3)
    assert not report["updated"] and model.to_dict() == before


def test_disabled_constant_reward_and_bad_update_configuration_are_atomic():
    model, _ = model_and_example()
    request, receipt = request_and_receipt(model)
    before = model.to_dict()
    assert model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train")["reason"] == "disabled"
    constant = bind_feedback(request, {"scores": {r["id"]: 2 for r in request["variations"]}})
    result = model.train_jev_feedback(SOURCE, constant, spec=spec(), split="train", weight=.3)
    assert result["reason"] == "zero_update"
    for kwargs in ({"weight": float("nan")}, {"weight": 1.1}, {"weight": True},
                   {"learning_rate": 10.}, {"learning_rate": -1.}, {"kl_weight": .1},
                   {"reference_weights": {"broken": float("inf")}, "kl_weight": .1}):
        result = model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", **{"weight": .3, **kwargs})
        assert not result["updated"] and model.to_dict() == before


def test_multiple_rounds_improve_surrogate_and_edit_ce_without_touching_reconstruction():
    model, example = model_and_example()
    baseline = model.to_dict()
    before_ce, before_edit = model._sequence_loss(example), model.rewrite_objective(example)
    rows = choices(SOURCE, model.state["rewrite_templates"])
    probability = probabilities(model.state["rewrite_weights"], rows)[1]
    for _ in range(8):
        _, receipt = request_and_receipt(model)
        report = model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", weight=.3,
                                          reference_weights=baseline["rewrite_weights"], kl_weight=.1)
        assert report["updated"] and report["expected_utility_after"] > report["expected_utility_before"]
        assert report["objective_after"] < report["objective_before"]
        assert report["applied_gradient_norm"] <= model.config.gradient_clip
        new_probability = probabilities(model.state["rewrite_weights"], rows)[1]
        assert new_probability > probability
        probability = new_probability
    for key in baseline:
        if key not in {"step", "rewrite_steps", "rewrite_weights"}:
            assert baseline[key] == model.state[key]
    assert model._sequence_loss(example) == before_ce
    after_edit = model.rewrite_objective(example)
    assert after_edit["cross_entropy"] < before_edit["cross_entropy"]
    assert after_edit["expected_cosine_loss"] < before_edit["expected_cosine_loss"]
    restored = LeanIRAutoencoder.from_dict(model.to_dict(), config=model.config)
    assert restored.to_dict() == model.to_dict()
    # Replaying the old policy's receipt is not a new training observation.
    assert model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", weight=.3)["reason"] == "stale_or_mismatched_feedback"


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_checks_good_edit_and_rejects_high_scoring_lossy_edit(tmp_path):
    from jevops.router_tuning import _lean_compiler
    from jevops.autoencoder_training import score_candidate

    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True)
    model, _ = model_and_example()
    for _ in range(3):
        _, receipt = request_and_receipt(model)
        assert model.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", weight=.3)["updated"]
    unseen = SOURCE.replace("sample", "unseen").replace("(h : p)", "(evidence : p)").replace("exact h", "exact evidence")
    prediction = ae.decode_lean_ir(model.predict_ir(unseen))
    assert "assumption" in prediction and compiler(prediction)["theorem_ok"]

    lossy, _ = model_and_example(invalid_edit=True)
    grammar = copy.deepcopy(lossy.state["rewrite_templates"])
    # Verify the rule's original, narrower seed, then show unsafe generalization.
    assert compiler("theorem seed (h : False) : False := by\n  exact False.elim h")["theorem_ok"]
    for _ in range(3):
        _, receipt = request_and_receipt(lossy, preferred="False.elim")
        result = lossy.train_jev_feedback(SOURCE, receipt, spec=spec(), split="train", weight=.3)
        assert result["updated"] and not result["proof_admitted"] and not result["teacher_created"]
    bad = ae.decode_lean_ir(lossy.predict_ir(SOURCE))
    assert "False.elim" in bad
    check = compiler(bad)
    assert not check["theorem_ok"] and lossy.state["rewrite_templates"] == grammar
    score = score_candidate({"lake_ok": False, "verifier_reward": 0., "n_tokens": 1},
                            typesafe_reward=1., fuzzy_prover_reward=1., minimality_reward=1.)
    without_size_bonus = score_candidate({"lake_ok": False, "n_tokens": 1},
                                         typesafe_reward=1., fuzzy_prover_reward=1., minimality_reward=0.)
    # The old ranker intentionally retains a bounded soft hint on failures.
    # Neither that hint nor a claimed token saving constitutes admission.
    assert score["admission"] == "rejected"
    assert score["reward"] == without_size_bonus["reward"]
