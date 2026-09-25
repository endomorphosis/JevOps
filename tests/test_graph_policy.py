"""Actual encoder gradients, bounded data contracts and separate proof authority."""
import copy
from dataclasses import replace
import math
import shutil

import pytest

torch = pytest.importorskip("torch")

from jevops.graph_policy import GraphEditPolicy, candidate_loss, graph_context, graph_tensors, metrics
from jevops.jev_surrogate import JeVFeedbackSpec, bind_feedback, expected_utility_gradient
from jevops.rewrite_policy import body_of, mine_template
from tests.test_structural_training import ENV, SOURCE, TARGET, fixture_receipt

pytestmark = pytest.mark.no_seal(reason="optional external PyTorch runtime and native Lean probes")


@pytest.fixture(autouse=True)
def one_thread():
    count = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(count)


def setup(freeze=False, receipt=None, pooling="last"):
    ctx = graph_context(SOURCE, fixture_receipt(SOURCE) if receipt is None else receipt, environment_sha256=ENV)
    model = GraphEditPolicy([mine_template(SOURCE, body_of(TARGET)[1])], environment_sha256=ENV,
                            toolchain=ctx.toolchain, width=8, freeze_encoder=freeze, pooling=pooling)
    return model, ctx


@pytest.mark.parametrize("pooling", ["last", "multiscale"])
def test_real_encoder_gradient_matches_finite_differences_for_every_parameter_group(pooling):
    model, ctx = setup(pooling=pooling)
    # Zero readout initially abstains; the next step reaches encoder parameters.
    assert model.predict(SOURCE, ctx)["choice"] == 0
    model.train_step(SOURCE, TARGET, ctx, split="train")
    loss = model.objective(SOURCE, TARGET, ctx)["total"]
    named = list(model.named_parameters())
    gradients = torch.autograd.grad(loss, [p for _, p in named])
    for (name, parameter), grad in zip(named, gradients):
        if not grad.abs().max():
            # No numeric bvar>0 or third let child in some fixture subgraphs.
            continue
        index = int(grad.abs().argmax())
        original = float(parameter.detach().flatten()[index])
        with torch.no_grad():
            parameter.flatten()[index] = original + 1e-5
        plus = float(model.objective(SOURCE, TARGET, ctx)["total"].detach())
        with torch.no_grad():
            parameter.flatten()[index] = original - 1e-5
        minus = float(model.objective(SOURCE, TARGET, ctx)["total"].detach())
        with torch.no_grad():
            parameter.flatten()[index] = original
        assert float(grad.flatten()[index]) == pytest.approx((plus-minus)/2e-5, abs=1e-8), name
    assert any(float(g.abs().max()) > 0 for (name, _), g in zip(named, gradients) if name.startswith("encoder.layers"))
    assert float(gradients[0].abs().max()) > 0


def test_multiscale_readout_retains_each_radius_and_versioned_checkpoints():
    model, ctx = setup(pooling="multiscale")
    graph = graph_tensors(ctx.wire(SOURCE, ENV, ctx.toolchain))
    stages = model.encoder.pooled_stages(graph)
    encoded = model.encoder(graph)
    assert len(stages) == 3 and encoded.numel() == 3*4*model.width
    assert torch.equal(encoded, torch.cat(stages))
    model.train_step(SOURCE, TARGET, ctx, split="train")
    state = model.to_dict()
    assert state["schema"].endswith("/v2") and state["pooling"] == "multiscale"
    restored = GraphEditPolicy.from_dict(state)
    assert restored.to_dict() == state and restored.predict(SOURCE, ctx) == model.predict(SOURCE, ctx)
    for damage in ("missing", "last", "unknown", "schema"):
        broken = copy.deepcopy(state)
        if damage == "missing":
            broken.pop("pooling")
        elif damage == "schema":
            broken["schema"] = "jevops-trained-source-dag-policy/v1"
        else:
            broken["pooling"] = damage
        with pytest.raises(ValueError):
            GraphEditPolicy.from_dict(broken)


def test_batch_update_is_mean_gradient_before_clipping_and_order_invariant():
    model, ctx = setup(pooling="multiscale")
    ctx2 = graph_context(TARGET, fixture_receipt(TARGET), environment_sha256=ENV)
    batch = [{"source": SOURCE, "target": TARGET, "context": ctx, "split": "train"},
             {"source": TARGET, "target": TARGET, "context": ctx2, "split": "train"}]
    reverse = GraphEditPolicy.from_dict(model.to_dict())
    params = list(model.parameters())
    loss = torch.stack([model.objective(r["source"], r["target"], r["context"])["total"] for r in batch]).mean()
    grads = torch.autograd.grad(loss, params, allow_unused=True)
    norm = math.sqrt(sum(float((g*g).sum()) for g in grads if g is not None))
    scale = min(1.0, 1/(norm or 1.0))
    expected = [p.detach() - .15*scale*g if g is not None else p.detach().clone() for p, g in zip(params, grads)]
    result = model.train_batch(batch, split="train")
    reverse.train_batch(list(reversed(batch)), split="train")
    assert result["sample_count"] == 2 and model.steps == 1
    assert float(loss.detach()) == pytest.approx(result["total"])
    for a, b, c in zip(model.parameters(), reverse.parameters(), expected):
        assert torch.allclose(a, b, atol=1e-12, rtol=0)
        assert torch.allclose(a, c, atol=1e-12, rtol=0)


def test_batch_rejects_eval_rows_before_labels_and_bad_batches_atomically():
    model, ctx = setup()
    class HiddenTarget(dict):
        def __getitem__(self, key):
            if key == "target":
                pytest.fail("read an evaluation label")
            return super().__getitem__(key)
    state = model.to_dict()
    good = {"source": SOURCE, "target": TARGET, "context": ctx, "split": "train"}
    bad = HiddenTarget(good, split="holdout")
    with pytest.raises(ValueError, match="training rows"):
        model.train_batch([good, bad], split="train")
    for batch, kwargs in (([], {}), ([good]*33, {}), ([good], {"learning_rate": math.inf}),
                          ([good, {**good, "context": None}], {})):
        with pytest.raises(ValueError):
            model.train_batch(batch, split="train", **kwargs)
    with pytest.raises(ValueError, match="training split"):
        model.train_batch([good], split="canary")
    assert model.to_dict() == state


def test_learning_changes_encoder_and_preserves_frozen_control_and_rng():
    rng = torch.get_rng_state().clone()
    model, ctx = setup()
    frozen, _ = setup(True)
    assert torch.equal(rng, torch.get_rng_state())
    initial = model.to_dict()
    before = metrics(model.objective(SOURCE, TARGET, ctx))
    for _ in range(15):
        for m in (model, frozen):
            m.train_step(SOURCE, TARGET, ctx, split="train")
    after = metrics(model.objective(SOURCE, TARGET, ctx))
    assert after["cross_entropy"] < before["cross_entropy"]
    assert after["expected_cosine_loss"] < before["expected_cosine_loss"]
    assert any(v != initial["weights"][k] for k, v in model.to_dict()["weights"].items() if k.startswith("encoder."))
    assert all(v == initial["weights"][k] for k, v in frozen.to_dict()["weights"].items() if k.startswith("encoder."))
    state = model.to_dict()
    prediction = model.predict(SOURCE, ctx)
    assert prediction["source"] == TARGET and not prediction["decoder_type_safe_by_construction"]
    assert not prediction["teacher_used"] and not prediction["solver_used"]
    assert GraphEditPolicy.from_dict(state).predict(SOURCE, ctx) == prediction
    assert model.predict(SOURCE, ctx, ablation="zero_weights")["source"] == SOURCE
    assert model.to_dict() == state


def test_surrogate_gradient_is_exact_detached_and_additive_not_a_ce_replacement():
    model, ctx = setup()
    rows, _ = model.logits(SOURCE, ctx)
    logits = torch.tensor([.2, -.1], dtype=torch.float64, requires_grad=True)
    reference = torch.tensor([-.3, .4], dtype=torch.float64, requires_grad=True)
    target = body_of(TARGET)[1]
    base = candidate_loss(logits, rows, target)
    full = candidate_loss(logits, rows, target, utilities=[-.8, .7], reference_logits=reference,
                          surrogate_weight=.6, kl_weight=.12)
    delta = torch.autograd.grad(full["total"]-base["total"], logits, retain_graph=True)[0]
    fake_rows = [{"features": {str(i): 1.0}} for i in range(2)]
    expected = expected_utility_gradient({"0": .2, "1": -.1}, fake_rows, [-.8, .7],
                                         reference_weights={"0": -.3, "1": .4}, kl_weight=.2)
    assert delta.tolist() == pytest.approx([.6*expected["gradient"][str(i)] for i in range(2)])
    assert torch.autograd.grad(full["total"], reference, allow_unused=True)[0] is None
    assert float(full["cross_entropy"].detach()) == float(base["cross_entropy"].detach())
    assert float(full["expected_cosine_loss"].detach()) == float(base["expected_cosine_loss"].detach())
    assert torch.autograd.gradcheck(lambda z: candidate_loss(z, rows, target, utilities=[-.8, .7],
                                  reference_logits=reference, surrogate_weight=.6, kl_weight=.12)["total"], (logits,))


def test_request_bound_jev_update_rejects_stale_feedback_and_eval_splits_atomically():
    model, ctx = setup()
    spec = JeVFeedbackSpec(ENV, "offline-test", "two-label", {"bad": -1, "good": 1})
    request = model.feedback_request(SOURCE, ctx, spec=spec, split="train")
    feedback = bind_feedback(request, {"scores": {r["id"]: "good" if i else "bad"
                                                for i, r in enumerate(request["variations"])}})
    reference = GraphEditPolicy.from_dict(model.to_dict())
    result = model.train_step(SOURCE, TARGET, ctx, split="train", feedback=feedback, spec=spec,
                              surrogate_weight=.2, reference=reference, kl_weight=.1)
    assert result["cross_entropy"] > 0 and result["expected_cosine_loss"] > 0
    state = model.to_dict()
    with pytest.raises(ValueError, match="stale"):
        model.train_step(SOURCE, TARGET, ctx, split="train", feedback=feedback, spec=spec, surrogate_weight=.2)
    for split in ("validation", "canary", "holdout"):
        with pytest.raises(ValueError, match="training"):
            model.train_step(SOURCE, TARGET, ctx, split=split)
        with pytest.raises(ValueError, match="training"):
            model.feedback_request(SOURCE, ctx, spec=spec, split=split)
    assert model.to_dict() == state and reference.steps == 0


@pytest.mark.parametrize("damage", ["source", "environment", "toolchain", "wire", "missing", "target", "rate", "utility", "reference"])
def test_invalid_context_or_objective_does_not_update(damage):
    model, ctx = setup()
    target, kwargs = TARGET, {}
    if damage in {"source", "environment"}:
        ctx = replace(ctx, **{damage + "_sha256": "0" * 64})
    elif damage == "toolchain":
        ctx = replace(ctx, toolchain=("wrong", "wrong"))
    elif damage == "wire":
        ctx = replace(ctx, wire_bytes=ctx.wire_bytes + b" ")
    elif damage == "missing":
        ctx = None
    elif damage == "target":
        target = TARGET.replace("exact h", "rfl")
    elif damage == "rate":
        kwargs["learning_rate"] = math.nan
    elif damage == "utility":
        kwargs["surrogate_weight"] = 1
    else:
        kwargs["kl_weight"] = 1
    state = model.to_dict()
    with pytest.raises(ValueError):
        model.train_step(SOURCE, target, ctx, split="train", **kwargs)
    assert model.to_dict() == state


@pytest.mark.parametrize("damage", ["schema", "graph_schema", "steps", "width", "seed", "freeze_encoder", "weight_key", "shape", "nan", "boolean"])
def test_checkpoint_rejects_malformed_data_without_pickle(damage):
    model, _ = setup()
    state = model.to_dict()
    if damage in {"schema", "graph_schema"}:
        state[damage] = "unknown"
    elif damage in {"steps", "width", "seed"}:
        state[damage] = True
    elif damage == "freeze_encoder":
        state[damage] = 1
    elif damage == "weight_key":
        state["weights"]["unknown"] = []
    elif damage == "shape":
        state["weights"]["encoder.tag.weight"].append([0])
    else:
        state["weights"]["encoder.tag.weight"][0][0] = math.nan if damage == "nan" else True
    with pytest.raises(ValueError):
        GraphEditPolicy.from_dict(state)


def test_graph_features_keep_binder_roles_omit_names_and_do_not_expand_sharing():
    wire = fixture_receipt(SOURCE)["expression_dag"]["dag"]
    before = copy.deepcopy(wire)
    a = graph_tensors(wire)
    for row in wire["expressions"]:
        if row[0] in {"lam", "forall", "let"}:
            row[1] = [["s", "renamed"]]
    b = graph_tensors(wire)
    for key in ("tags", "payloads", "binders", "numbers", "edges", "bound_edges"):
        assert torch.equal(a[key], b[key])
    wire["expressions"][2][2] = "implicit"
    assert not torch.equal(a["binders"], graph_tensors(wire)["binders"])
    wire = copy.deepcopy(before)
    wire["levels"], wire["expressions"], wire["roots"] = [], [["nat", "0"]], ["199", "0"]
    for i in range(1, 200):
        wire["expressions"].append(["app", str(i-1), str(i-1)])
    tensor = graph_tensors(wire)
    assert tensor["edges"].shape == (200, 3)
    wire["roots"].append("0")
    with pytest.raises(ValueError, match="roots"):
        graph_tensors(wire)


def test_target_receipts_cannot_be_source_contexts():
    with pytest.raises(ValueError, match="source_binding"):
        graph_context(SOURCE, fixture_receipt(TARGET), environment_sha256=ENV)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires native Lean")
def test_native_graph_training_and_raw_output_recheck(tmp_path):
    from jevops.router_tuning import _lean_compiler
    from jevops.structural_training import collect_structural_pairs
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, export_dags=True, environment_sha256=ENV)
    pair = collect_structural_pairs([{"id": "train", "split": "train", "source": SOURCE}], {"train": TARGET},
                                    compile_fn=compiler, environment_sha256=ENV)
    assert pair["ok"], pair["decisions"]
    model, ctx = setup(receipt=compiler(SOURCE))
    for _ in range(15):
        model.train_step(SOURCE, TARGET, ctx, split="train")
    prediction = model.predict(SOURCE, ctx)
    assert prediction["source"] == TARGET
    checked = compiler(prediction["source"])
    assert checked["theorem_ok"] and checked["expression_dag"]["kernel_typechecked"]
    assert not compiler("theorem impossible : False := by\n  sorry\n")["theorem_ok"]
