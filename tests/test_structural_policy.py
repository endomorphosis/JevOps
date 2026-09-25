"""Feature/gradient contracts; native experiment replay is tested separately."""
import copy
from dataclasses import replace
import math

import pytest

from jevops.rewrite_policy import body_of, choices, mine_template
from jevops.structural_policy import (FEATURE_SCHEMA, SourceDAGContext, StructuralEditPolicy,
                                     graph_features, source_context)
from tests.test_structural_training import ENV, SOURCE, TARGET, fixture_receipt


def setup(structural=True):
    context = source_context(SOURCE, fixture_receipt(SOURCE), environment_sha256=ENV)
    templates = [mine_template(SOURCE, body_of(TARGET)[1])]
    model = StructuralEditPolicy(templates, environment_sha256=ENV, toolchain=context.toolchain, structural=structural)
    return model, context


def test_feature_extractor_is_bounded_name_independent_and_not_a_lossless_embedding():
    wire = fixture_receipt(SOURCE)["expression_dag"]["dag"]
    before = copy.deepcopy(wire)
    features = graph_features(wire)
    renamed = copy.deepcopy(wire)
    for node in renamed["expressions"]:
        if node[0] in {"lam", "forall", "let"}:
            node[1] = [["s", "different_" + str(node[1])]]
    renamed["environment"] = "b" * 64
    assert graph_features(renamed) == features
    assert len(features) <= 1024 and sum(v*v for v in features.values()) == pytest.approx(1)
    assert wire == before
    # Changing topology is observable, but no equality/correctness claim is made.
    changed = copy.deepcopy(wire)
    changed["expressions"][-1] = ["app", "3", "3"]
    assert graph_features(changed) != features
    assert all("different" not in k and "bridge" not in k for k in features)


def test_features_do_not_expand_exponential_sharing_and_reject_extra_roots():
    wire = fixture_receipt(TARGET)["expression_dag"]["dag"]
    wire["levels"], wire["expressions"], wire["roots"] = [], [["nat", "0"]], ["199", "0"]
    for i in range(1, 200):
        wire["expressions"].append(["app", str(i-1), str(i-1)])
    assert len(graph_features(wire)) <= 1024
    wire["roots"].append("0")
    with pytest.raises(ValueError, match="roots"):
        graph_features(wire)


def test_context_factory_rejects_target_receipts_and_unverified_exports():
    with pytest.raises(ValueError, match="source_binding"):
        source_context(SOURCE, fixture_receipt(TARGET), environment_sha256=ENV)
    receipt = fixture_receipt(SOURCE)
    receipt["expression_dag"]["kernel_typechecked"] = False
    with pytest.raises(ValueError, match="export"):
        source_context(SOURCE, receipt, environment_sha256=ENV)


@pytest.mark.parametrize("damage", ["missing", "source", "environment", "toolchain", "schema", "nan", "key", "scale"])
def test_stale_or_malformed_context_fails_without_mutating_weights(damage):
    model, ctx = setup()
    snapshot = model.to_dict()
    if damage == "missing":
        ctx = None
    elif damage == "source":
        ctx = replace(ctx, source_sha256="0" * 64)
    elif damage == "environment":
        ctx = replace(ctx, environment_sha256="0" * 64)
    elif damage == "toolchain":
        ctx = replace(ctx, toolchain=("different", "different"))
    elif damage == "schema":
        ctx = replace(ctx, feature_schema="unknown")
    elif damage == "nan":
        ctx = replace(ctx, features=(("proof/r0/root/0", math.nan),))
    elif damage == "key":
        ctx = replace(ctx, features=(("teacher/shorter", 1.0),))
    else:
        ctx = replace(ctx, features=(("proof/r0/root/0", .5),))
    with pytest.raises(ValueError):
        model.train_step(SOURCE, TARGET, ctx, split="train")
    with pytest.raises(ValueError):
        model.predict(SOURCE, ctx)
    assert model.to_dict() == snapshot


def test_lexical_arm_is_the_existing_selector_and_graph_gradients_match_finite_differences():
    lexical, ctx = setup(False)
    assert lexical.rows(SOURCE, ctx) == choices(SOURCE, lexical.templates)
    model, ctx = setup()
    rows = model.rows(SOURCE, ctx)
    assert [r["body"] for r in rows] == [r["body"] for r in lexical.rows(SOURCE, ctx)]
    assert rows[0]["features"] == {}
    graph_keys = [k for k in rows[1]["features"] if "|dag:" in k]
    keys = [*graph_keys[::max(1, len(graph_keys)//8)], next(k for k in rows[1]["features"] if k.endswith("|bias"))]
    model.weights = {k: .13 for k in keys}
    gradient = model.objective(SOURCE, TARGET, ctx)["gradient"]
    for key in keys:
        model.weights[key] += 1e-5
        plus = model.objective(SOURCE, TARGET, ctx)["total"]
        model.weights[key] -= 2e-5
        minus = model.objective(SOURCE, TARGET, ctx)["total"]
        model.weights[key] += 1e-5
        assert gradient[key] == pytest.approx((plus-minus)/2e-5, abs=1e-7)


def test_learning_single_step_checkpoint_and_explicit_ablation():
    model, ctx = setup()
    before = model.objective(SOURCE, TARGET, ctx)
    for _ in range(12):
        model.train_step(SOURCE, TARGET, ctx, split="train")
    after = model.objective(SOURCE, TARGET, ctx)
    assert after["cross_entropy"] < before["cross_entropy"]
    assert after["expected_cosine_loss"] < before["expected_cosine_loss"]
    assert any(v != 0 for k, v in model.weights.items() if "|dag:" in k)
    snapshot = model.to_dict()
    prediction = model.predict(SOURCE, ctx)
    assert prediction["source"] == TARGET and prediction["max_edits"] == 1
    assert not prediction["teacher_used"] and not prediction["solver_used"]
    assert model.predict(SOURCE, ctx, ablation="zero_weights")["choice"] == 0
    restored = StructuralEditPolicy.from_dict(snapshot)
    assert restored.predict(SOURCE, ctx) == prediction
    assert model.to_dict() == snapshot
    with pytest.raises(ValueError, match="training split"):
        model.train_step(SOURCE, TARGET, ctx, split="holdout")
    with pytest.raises(ValueError, match="unreachable"):
        model.train_step(SOURCE, TARGET.replace("exact h", "rfl"), ctx, split="train")
    assert model.to_dict() == snapshot


@pytest.mark.parametrize("damage", ["schema", "feature_schema", "steps", "weights", "foreign_rule", "graph_in_lexical"])
def test_checkpoint_contract_is_versioned_and_fails_closed(damage):
    model, ctx = setup()
    model.train_step(SOURCE, TARGET, ctx, split="train")
    state = model.to_dict()
    if damage in {"schema", "feature_schema"}:
        state[damage] = "wrong"
    elif damage == "steps":
        state["steps"] = True
    elif damage == "weights":
        state["weights"][next(iter(state["weights"]))] = float("inf")
    elif damage == "foreign_rule":
        state["weights"]["foreign|bias"] = 1
    else:
        state["structural"] = False
    with pytest.raises(ValueError):
        StructuralEditPolicy.from_dict(state)
