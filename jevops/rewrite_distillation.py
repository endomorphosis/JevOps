"""Isolated verifier-backed rewrite distillation and rendered-proof evaluation.

The small generated curriculum measures structural transfer, not unseen theorem
family generalization or arena performance. Teachers come from reduction code.
Only training rows grow the edit grammar or update weights; the final holdout
is first compiled/scored after the checkpoint freezes, with no further tuning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import textwrap
import time
from typing import Any, Callable, Mapping, Sequence

from . import autoencoder as ae
from .autoencoder_training import (AutoencoderConfig, LeanIRAutoencoder, canary_gate,
                                   coerce_training_example, loss_for_example)
from .logic_refactor import reduction_variants
from .rewrite_policy import body_of, supported
from .proof_tokens import proof_source_tokens, TOKENIZER_ID
from .rewrite_trajectories import trajectory_metrics, verified_edges
from .router_tuning import _ir_body, _lean_compiler, _render_source, _source_parts


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def curriculum_rows(seed: int = 20260923, *, extended: bool = False, solver_feedback: bool = False) -> list[dict[str, Any]]:
    rows = []
    for split_index, split in enumerate(("train", "validation", "canary", "holdout")):
        rng = random.Random(17 if split == "train" else seed + split_index)
        families = ("exact_local", "terminal_alias", "constructor_pack", "symmetry", "projection", "lift_projection")
        if extended:
            families += ("application", "eta", "solver_arguments")
        if solver_feedback:
            families += ("solver_feedback",)
        for family in families:
            n = rng.randrange(10**6)
            p, q, h, k, alias = (f"{word}_{n}" for word in ("p", "q", "h", "k", "alias"))
            if family == "exact_local":
                header, body, methods = f"({p} : Prop) ({h} : {p}) : {p}", f"exact {h}", ["rewrite_transport"]
            elif family == "terminal_alias":
                header = f"({p} : Prop) ({h} : {p}) : {p}"
                body = f"have {alias} : {p} := {h}\nexact {alias}"
                methods = ["local_alias_reduce", "rewrite_transport"]
            elif family == "constructor_pack":
                header = f"({p} {q} : Prop) ({h} : {p}) ({k} : {q}) : {p} ∧ {q}"
                body = f"constructor\n· exact {h}\n· exact {k}"
                methods = ["structural_reduce"]
            elif family == "symmetry":
                header = f"({p} {q} : Nat) ({h} : {p} = {q}) : {p} = {q}"
                body = f"symm\nexact Eq.symm {h}"
                methods = ["symmetry_reduce", "rewrite_transport"]
            elif family == "projection":
                header = f"({p} {q} : Prop) : {p} ∧ {q} → {p}"
                body, methods = f"intro {h}\nexact {h}.1", ["logic_simp"]
            elif family == "lift_projection":
                header = f"({p} : Prop) : PLift {p} → {p}"
                body, methods = f"intro {h}\nexact {h}.1", ["logic_simp"]
            elif family == "application":
                header = f"({p} {q} : Prop) ({k} : {p} → {q}) ({h} : {p}) : {q}"
                body, methods = f"apply {k}\nexact {h}", ["application_reduce"]
            elif family == "eta":
                header = f"({p} {q} : Prop) ({k} : {p} → {q}) : {p} → {q}"
                body, methods = f"intro {h}\nexact {k} {h}", ["eta_reduce"]
            elif family == "solver_arguments":
                header = f"({p} : Nat) : 0 + {p} = {p}"
                body, methods = "simp only [Nat.zero_add, Nat.add_zero]", ["solver_argument_reduce"]
            else:
                header = f"({p} : Nat) : 0 + {p} = {p}"
                body, methods = "simp only [Nat.zero_add, Nat.add_zero, Nat.mul_one]", []
            name = f"distill_{split}_{family}_{n}"
            rows.append({"id": name, "split": split, "family": family, "strategies": methods,
                         "source": f"theorem {name} {header} := by\n" + textwrap.indent(body, "  ") + "\n"})
    return rows


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    if not 1 <= len(rows) <= 128:
        raise ValueError("distillation requires 1..128 bounded fixtures")
    ids, sources = set(), set()
    for row in rows:
        if row["split"] not in {"train", "validation", "canary", "holdout"}:
            raise ValueError("unknown distillation split")
        source = str(row["source"])
        identity = digest(" ".join(source.split()))
        if row["id"] in ids or identity in sources:
            raise ValueError("duplicate/leaking distillation row")
        prefix, body = body_of(source)
        if not prefix or not supported(body):
            raise ValueError("unsupported theorem envelope/body")
        ids.add(row["id"])
        sources.add(identity)
    if not any(row["split"] == "train" for row in rows):
        raise ValueError("training split is empty")


def compositional_holdout_rows(seed: int = 20260924) -> list[dict[str, Any]]:
    """New proof layouts/domains, scored after freeze; not new rule training."""
    n = random.Random(seed).randrange(10**6)
    p, q, h, f = (f"{s}_{n}" for s in ("p", "q", "h", "f"))
    fixtures = [
        ("composed_application", f"({p} {q} : Prop) ({f} : {p} → {q}) ({h} : {p}) : {q} ∧ {q}",
         f"constructor\ncase left =>\n  apply {f}\n  exact {h}\ncase right =>\n  apply {f}\n  exact {h}",
         ["application_reduce", "application_reduce"]),
        ("composed_eta", f"(b : Bool) ({p} {q} : Prop) ({f} : {p} → {q}) : {p} → {q}",
         f"cases b\ncase false =>\n  intro {h}\n  exact {f} {h}\ncase true =>\n  intro {h}\n  exact {f} {h}",
         ["eta_reduce", "eta_reduce"]),
        ("new_equality_context", f"({p} {q} : Int) ({h} : {p} = {q}) : {p} = {q}",
         f"exact {h}", ["rewrite_transport"]),
        ("new_identity_control", f"({p} : Nat) : {p} = {p}", "rfl", ["kernel_reduce"]),
    ]
    return [{"id": f"transfer_holdout_{family}_{n}", "split": "holdout", "family": family,
             "strategies": methods, "source": f"theorem transfer_holdout_{family}_{n} {header} := by\n"
             + textwrap.indent(body, "  ") + "\n"} for family, header, body, methods in fixtures]


def typed_term_rows(seed: int = 20260923) -> list[dict[str, Any]]:
    rows = []
    for index, split in enumerate(("train", "validation", "canary", "holdout")):
        n = random.Random(123 if split == "train" else seed + index).randrange(10**6)
        p, q, r, f, h, k, a = (f"{s}_{n}" for s in ("p", "q", "r", "f", "h", "k", "a"))
        fixtures = [
            ("typed_binary_application", f"({p} {q} {r} : Prop) ({f} : {p} → {q} → {r}) ({h} : {p}) ({k} : {q}) : {r}",
             f"apply {f}\n· exact {h}\n· exact {k}"),
            ("typed_transitivity", f"({p} {q} {r} : Nat) ({h} : {p} = {q}) ({k} : {q} = {r}) : {p} = {r}",
             f"apply Eq.trans\n· exact {h}\n· exact {k}"),
            ("typed_dependent_application", f"(α : Type) ({p} : α → Prop) ({f} : ∀ x, {p} x) ({a} : α) : {p} {a}",
             f"apply ({f} {a})"),
            ("typed_projection", f"({p} {q} : Prop) ({h} : {p} ∧ {q}) : {q}",
             f"apply And.right\nexact {h}"),
        ]
        for family, header, body in fixtures:
            name = f"{split}_{family}_{n}"
            rows.append({"id": name, "split": split, "family": family, "strategies": [],
                         "source": f"theorem {name} {header} := by\n" + textwrap.indent(body, "  ") + "\n"})
    return rows


def constructive_rows(seed: int = 20260925) -> list[dict[str, Any]]:
    """Shared structural families, renamed by split; not semantic decontamination."""
    rows = []
    for index, split in enumerate(("train", "validation", "canary", "holdout")):
        n = random.Random(401 if split == "train" else seed + index).randrange(10**6)
        p,q,h,k,f,a = (f"{s}_{n}" for s in ("p","q","h","k","f","a"))
        fixtures = [
            ("projection", f"({p} {q} : Prop) : {p} ∧ {q} → {p}", f"intro {h}\nexact {h}.1", ["logic_simp"]),
            ("nested_projection", f"({p} {q} : Prop) ({h} : {p} ∧ ({q} ∧ {p})) : {q}",
             f"have {a} : {q} ∧ {p} := {h}.right\nexact {a}.left", []),
            ("modus_ponens", f"({p} {q} : Prop) ({f} : {p} → {q}) ({h} : {p}) : {q}",
             f"have {a} : {p} := {h}\napply {f}\nexact {a}", []),
            ("iff_elimination", f"({p} {q} : Prop) ({f} : {p} ↔ {q}) ({h} : {p}) : {q}",
             f"have {a} : {p} := {h}\napply {f}.mp\nexact {a}", []),
            ("contradiction", f"({p} : Prop) ({h} : {p}) ({k} : ¬ {p}) : False",
             f"have {a} : {p} := {h}\nexact {k} {a}", []),
            ("conjunction", f"({p} {q} : Prop) ({h} : {p}) ({k} : {q}) : {p} ∧ {q}",
             f"have {a} : {p} := {h}\nconstructor\n· exact {a}\n· exact {k}", []),
            ("disjunction", f"({p} {q} : Prop) ({h} : {p}) : {p} ∨ {q}",
             f"have {a} : {p} := {h}\nleft\nexact {a}", []),
        ]
        for family, header, body, strategies in fixtures:
            name = f"constructive_{split}_{family}_{n}"
            rows.append({"id": name, "split": split, "family": f"constructive_{family}", "strategies": strategies,
                         "source": f"theorem {name} {header} := by\n" + textwrap.indent(body, "  ") + "\n"})
    return rows


def difference_rows(seed: int = 20260927) -> list[dict[str, Any]]:
    """Train compression of explicit, path-certified difference implications."""
    from .difference_bounds import DifferenceBound as B, reduce_bounds, implication_obligation
    constraints = [B(0,1,2), B(1,2,3), B(0,2,7)]
    reduction = reduce_bounds(constraints, 3)
    certificate = next(c for c in reduction["certificates"] if c["removed_index"] == 2)
    rows = []
    for index, split in enumerate(("train", "validation", "canary", "holdout")):
        n = random.Random(501 if split == "train" else seed + index).randrange(10**6)
        name, alias = f"difference_{split}_{n}", f"bound_{n}"
        certified = implication_obligation(constraints, constraints[2], certificate["path"], name=name)
        prefix, _ = body_of(certified)
        source = prefix + f"\n  have {alias} : {constraints[2].lean()} := by omega\n  exact {alias}\n"
        rows.append({"id": name, "split": split, "family": "difference_certificate", "source": source,
                     "strategies": ["arithmetic_linear"], "certificate": certificate,
                     "constraints": [{"left": c.left, "right": c.right, "bound": c.bound} for c in constraints]})
    return rows


def verified(receipt: Mapping[str, Any]) -> bool:
    # The compiler callback is trusted infrastructure, never an LLM's claim.
    audit = receipt.get("kernel_audit")
    return receipt.get("theorem_ok") is True and isinstance(audit, Mapping) and audit.get("accepted") is True


def collect_teacher(row: Mapping[str, Any], compile_one: Callable[[str], Mapping[str, Any]], *,
                    solver_feedback: bool = False, typed_terms: bool = False,
                    constructive_terms: bool = False, cost_guard: bool = False) -> dict[str, Any]:
    source = str(row["source"])
    original = dict(compile_one(source))
    if not verified(original):
        return {"ok": False, "reason": "unverified_source", "id": row["id"], "compile": original}
    cost_checks = []
    def admit(before, after):
        if not cost_guard:
            return True
        from .proof_metrics import compare_proofs
        report = compare_proofs(before, after, compile_one)
        accepted = report["ok"] and report["expression_nonregression"] is True
        cost_checks.append({"before_sha256": digest(before), "after_sha256": digest(after),
                            "measured": report["ok"], "expression_nonregression": report["expression_nonregression"],
                            "accepted": accepted})
        return accepted
    if cost_guard and not admit(source, source):
        return {"ok": False, "reason": "unmeasured_source_cost", "id": row["id"],
                "compile": original, "cost_checks": cost_checks}
    prefix, body, has_theorem = _source_parts(source)
    best, best_tokens, trace = source, proof_source_tokens(source), []
    goal = ae.encode_lean_ir(source)["goal"]
    # Ordered methods make a bounded trajectory. Each accepted intermediate
    # is checked; no equivalence is inferred from text or cosine similarity.
    for strategy in list(row.get("strategies", ()))[:8]:
        _, body = body_of(best)
        for kind, draft, _ in reduction_variants(body, strategy=strategy, goal=goal, cap=4):
            candidate = _render_source(prefix, draft, has_theorem=has_theorem)
            tokens = proof_source_tokens(candidate)
            if tokens >= best_tokens:
                continue
            receipt = dict(compile_one(candidate))
            if verified(receipt) and admit(best, candidate):
                trace.append({"strategy": strategy, "kind": kind, "before_tokens": best_tokens,
                              "before_source": best, "after_source": candidate,
                              "after_tokens": tokens, "source_sha256": digest(candidate), "compile": receipt})
                best, best_tokens = candidate, tokens
                break
    feedback = None
    if solver_feedback:
        from .solver_feedback import harvest_solver_feedback
        feedback = harvest_solver_feedback(best, compile_one, max_calls=8, max_sites=2, max_rounds=2, candidate_gate=admit)
        trace.extend({**step, "strategy": "solver_feedback", "kind": "solver_suggestion"}
                     for step in feedback["trajectory"])
        best, best_tokens = feedback["best_source"], feedback["best_tokens"]
    typed = None
    if typed_terms:
        from .typed_terms import collect_typed_term
        typed = collect_typed_term(best, compile_one, candidate_gate=admit)
        if typed["ok"]:
            trace.extend(typed["trajectory"])
        best, best_tokens = typed["best_source"], typed["best_tokens"]
    constructive = None
    if constructive_terms:
        from .constructive_proofs import propose
        constructive = propose(best)
        candidate = constructive.get("candidate")
        if candidate and proof_source_tokens(candidate) < best_tokens:
            receipt = dict(compile_one(candidate))
            if verified(receipt) and admit(best, candidate):
                tokens = proof_source_tokens(candidate)
                trace.append({"strategy": "constructive_terms", "kind": "constructive_term",
                              "before_source": best, "after_source": candidate,
                              "before_tokens": best_tokens, "after_tokens": tokens, "compile": receipt})
                best, best_tokens = candidate, tokens
    return {"ok": True, "id": row["id"], "source": source, "target": best,
            "source_tokens": proof_source_tokens(source), "target_tokens": best_tokens,
            "strict_shortening": best_tokens < proof_source_tokens(source),
            "trace": trace, "source_compile": original, "solver_feedback": feedback, "typed_terms": typed,
            "constructive_terms": constructive, "cost_guard": cost_guard, "cost_checks": cost_checks}


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [r["loss"] for r in rows]
    edits = [r for r in values if r["rewrite_cross_entropy"] is not None]
    mean = lambda key: sum(v[key] for v in values)/len(values) if values else None
    trajectories = [r["trajectory"] for r in rows if "trajectory" in r]
    labeled_steps = sum(r["labeled_step_count"] for r in trajectories)
    trajectory_report = ({"trajectory_step_count": sum(r["step_count"] for r in trajectories),
                          "trajectory_labeled_step_count": labeled_steps,
                          "trajectory_complete_examples": sum(r["complete"] for r in trajectories),
                          **{"trajectory_"+key: (sum((r[key] or 0.0)*r["labeled_step_count"] for r in trajectories)/labeled_steps
                                                 if labeled_steps else None)
                             for key in ("cross_entropy", "expected_cosine_loss")}} if trajectories else {})
    return {**trajectory_report, "sample_count": len(rows), "verified": sum(r["verified"] for r in rows),
            "verified_shortening": sum(r["verified_shortening"] for r in rows),
            "source_tokens": sum(r["source_tokens"] for r in rows),
            "prediction_tokens": sum(r["prediction_tokens"] for r in rows),
            "verified_saved_tokens": sum(r["source_tokens"]-r["prediction_tokens"] for r in rows if r["verified_shortening"]),
            "verifier_success_rate": sum(r["verified"] for r in rows)/len(rows) if rows else None,
            "verifier_evaluated_count": len(rows),
            "cross_entropy": mean("cross_entropy"), "cosine_similarity": mean("cosine_similarity"),
            "reconstruction_loss": mean("reconstruction_loss"), "objective": mean("total"),
            "rewrite_cross_entropy": sum(r["rewrite_cross_entropy"] for r in edits)/len(edits) if edits else None,
            "rewrite_expected_cosine_loss": sum(r["rewrite_expected_cosine_loss"] for r in edits)/len(edits) if edits else None,
            "rewrite_sample_count": len(edits), "rows": list(rows)}


def run_distillation(compile_fn: Callable[..., Mapping[str, Any]], *, rows: Sequence[Mapping[str, Any]] | None = None,
                     seed: int = 20260923, epochs: int = 40, max_compiles: int = 192,
                     extended: bool = False, freeze_reconstruction_heads: bool = False,
                     compositional_holdout: bool = False,
                     trajectory_training: bool = False, solver_feedback: bool = False,
                     typed_terms: bool = False, constructive_terms: bool = False, cost_guard: bool = False,
                     difference_curriculum: bool = False,
                     structural_compile_fn: Callable[[str], Mapping[str, Any]] | None = None,
                     structural_environment_sha256: str | None = None,
                     event: Callable[[Mapping[str, Any]], Any] | None = None) -> dict[str, Any]:
    if not 1 <= epochs <= 200 or not 1 <= max_compiles <= 512:
        raise ValueError("invalid distillation budget")
    if (structural_compile_fn is None) != (structural_environment_sha256 is None):
        raise ValueError("structural pairs require compiler and environment fingerprint")
    if structural_compile_fn is not None and trajectory_training:
        raise ValueError("structural pairs currently verify endpoints, not trajectory edges")
    rows = list(curriculum_rows(seed, extended=extended, solver_feedback=solver_feedback) if rows is None else rows)
    if compositional_holdout:
        rows.extend(compositional_holdout_rows(seed + 100))
    if typed_terms:
        rows.extend(typed_term_rows(seed))
    if difference_curriculum:
        rows.extend(difference_rows(seed))
    _validate_rows(rows)
    config = AutoencoderConfig(train_rewrite_policy=True, learning_rate=.15, warmup_steps=0,
                               decay_steps=1000, rewrite_max_edits=4, seed=17,
                               freeze_reconstruction_heads=freeze_reconstruction_heads)
    model = LeanIRAutoencoder(config=config)
    cache, attempts, events = {}, [], []

    def notify(kind, **data):
        item = {"event": kind, **data}
        events.append(item)
        if event:
            event(item)

    def compile_one(source):
        if source not in cache:
            if len(attempts) >= max_compiles:
                return {"theorem_ok": False, "reason": "compile_budget"}
            started = time.monotonic()
            try:
                receipt = dict(compile_fn(source))
            except Exception as exc:
                receipt = {"theorem_ok": False, "reason": type(exc).__name__}
            attempts.append({"source_sha256": digest(source), "wall_seconds": time.monotonic()-started,
                             "receipt": receipt})
            cache[source] = receipt
        return cache[source]

    teachers, paths = {}, {}
    development = [r for r in rows if r["split"] != "holdout"]
    for row in development:
        notify("teacher", id=row["id"], split=row["split"])
        teachers[row["id"]] = collect_teacher(row, compile_one, solver_feedback=solver_feedback, typed_terms=typed_terms,
                                               constructive_terms=constructive_terms, cost_guard=cost_guard)
        if not teachers[row["id"]]["ok"]:
            return {"ok": False, "reason": "unverified_fixture", "failure": teachers[row["id"]],
                    "model_step": model.step, "compile_attempts": attempts}
        if trajectory_training:
            paths[row["id"]] = verified_edges(teachers[row["id"]], parent_id=row["id"], split=row["split"], compile_fn=compile_one)

    def example(row):
        teacher = teachers[row["id"]]
        return coerce_training_example({"id": row["id"], "text": row["source"],
                                        "target_ir": ae.encode_lean_ir(teacher["target"])})

    train_rows = [row for row in development if row["split"] == "train"]
    structural, structural_examples = None, {}
    if structural_compile_fn is not None:
        from .structural_training import collect_structural_pairs
        notify("structural_training_pairs", train_count=len(train_rows))
        structural = collect_structural_pairs(rows, {r["id"]: teachers[r["id"]]["target"] for r in train_rows},
                                              compile_fn=structural_compile_fn,
                                              environment_sha256=structural_environment_sha256)
        if not structural["ok"]:
            return {"ok": False, "reason": "structural_teacher_gate", "model_step": 0,
                    "structural_pairs": structural, "compile_attempts": attempts}
        structural_examples = {p["id"]: coerce_training_example(p) for p in structural["pairs"]}
    train = ([coerce_training_example(edge) for row in train_rows for edge in paths[row["id"]]]
             if trajectory_training else [structural_examples[row["id"]] if row["id"] in structural_examples
                                          else example(row) for row in train_rows])
    grammar = model.prepare_rewrite_training(train)
    if not grammar["template_count"]:
        return {"ok": False, "reason": "no_verified_rewrite_templates", "model_step": 0,
                "compile_attempts": attempts}

    def evaluate(selected, decoder):
        snapshot = decoder.to_dict()
        outputs = []
        for row in selected:
            ex = example(row)
            # Commit the independent prediction before reading any target
            # metric. No compiler fallback or teacher repair is substituted.
            prediction = decoder.predict_ir(ex.text, source_ir=ex.source_ir)
            prefix, _, theorem = _source_parts(ex.text)
            rendered = _render_source(prefix, _ir_body(prediction), has_theorem=theorem)
            receipt = compile_one(rendered)
            ok = verified(receipt)
            tokens = proof_source_tokens(rendered)
            loss = loss_for_example(decoder, ex, predicted_ir=prediction, verifier_reward=float(ok))
            cost = None
            if cost_guard:
                from .proof_metrics import compare_proofs
                cost = compare_proofs(ex.text, rendered, compile_one)
            outputs.append({"id": row["id"], "split": row["split"], "family": row.get("family"),
                            "source_tokens": proof_source_tokens(ex.text), "prediction_tokens": tokens,
                            "prediction": rendered, "prediction_sha256": digest(rendered), "compile": receipt,
                            "verified": ok, "verified_shortening": ok and tokens < proof_source_tokens(ex.text),
                            "loss": loss.to_dict(), "rewrite_policy": prediction.get("rewrite_policy"),
                            "proof_metrics": receipt.get("proof_metrics"),
                            "source_proof_metrics": teachers[row["id"]]["source_compile"].get("proof_metrics"),
                            **({"expression_nonregression": cost["expression_nonregression"], "cost_measured": cost["ok"]} if cost else {}),
                            **({"trajectory": trajectory_metrics(decoder, paths[row["id"]])} if trajectory_training else {}),
                            "teacher_tokens": teachers[row["id"]]["target_tokens"]})
        assert decoder.to_dict() == snapshot, "evaluation mutated the checkpoint"
        return {split: _aggregate([r for r in outputs if r["split"] == split])
                for split in dict.fromkeys(r["split"] for r in selected)}

    before = evaluate(development, model)
    reconstruction_keys = ("vocab", "op_bias", "transition", "feature_op", "latent_bias", "feature_latent")
    base_heads = {k: model.to_dict()[k] for k in reconstruction_keys}
    notify("training", epochs=epochs, train_count=len(train), templates=grammar["template_count"])
    history = []
    for epoch in range(epochs):
        report = model.train_batch(train)
        if epoch in {0, epochs//2, epochs-1}:
            history.append({"epoch": epoch+1, **report})
    frozen = model.to_dict()
    base_heads_unchanged = base_heads == {k: frozen[k] for k in reconstruction_keys}
    if freeze_reconstruction_heads:
        assert base_heads_unchanged, "frozen reconstruction parameters changed"
    after = evaluate(development, model)
    gates = {split: canary_gate(before[split], after[split], max_cross_entropy_regression=.02)
             for split in ("validation", "canary") if split in before}
    gates_accepted = bool(gates) and all(g["accepted"] for g in gates.values())
    notify("checkpoint_frozen", state_sha256=digest(frozen), development_gates_accepted=gates_accepted)
    # Ablate parameters, not the grammar. Zeroed weights choose identity.
    zeroed = model.copy()
    zeroed.state["rewrite_weights"] = {}
    ablation = evaluate(development, zeroed)
    holdout = [r for r in rows if r["split"] == "holdout"]
    for row in holdout:
        notify("final_holdout", id=row["id"])
        teachers[row["id"]] = collect_teacher(row, compile_one, solver_feedback=solver_feedback, typed_terms=typed_terms,
                                               constructive_terms=constructive_terms, cost_guard=cost_guard)
        if trajectory_training and teachers[row["id"]]["ok"]:
            paths[row["id"]] = verified_edges(teachers[row["id"]], parent_id=row["id"], split="holdout", compile_fn=compile_one)
    holdout_valid = all(teachers[r["id"]]["ok"] for r in holdout)
    holdout_report = evaluate(holdout, model) if holdout_valid else {}
    holdout_ablation = evaluate(holdout, zeroed) if holdout_valid else {}
    holdout_gate = (canary_gate(holdout_ablation["holdout"], holdout_report["holdout"],
                                max_cross_entropy_regression=.02) if holdout and holdout_valid else
                    {"accepted": False, "status": "not_measured_or_invalid"})
    assert model.to_dict() == frozen
    assert set(r.sample_id for r in train).isdisjoint(r["id"] for r in rows if r["split"] != "train")
    assert all(edge["split"] == "train" for row in train_rows for edge in paths.get(row["id"], []))
    all_after = [r for split in after.values() for r in split["rows"]]
    cost_rows = [*all_after, *(r for split in holdout_report.values() for r in split["rows"])]
    cost_gate = ({"accepted": bool(cost_rows) and holdout_valid and
                 all(r.get("cost_measured") is True and r.get("expression_nonregression") is True for r in cost_rows),
                  "evaluated_count": len(cost_rows), "nonregressing_count": sum(r.get("expression_nonregression") is True for r in cost_rows)}
                 if cost_guard else {"accepted": None, "status": "not_requested"})
    return {"schema": "jevops-verified-rewrite-distillation/v1",
            "tokenizer_id": TOKENIZER_ID,
            "ok": gates_accepted and holdout_valid and (not holdout or holdout_gate["accepted"]) and (not cost_guard or cost_gate["accepted"]),
            "cost_guard_enabled": cost_guard, "cost_gate": cost_gate, "constructive_terms_enabled": constructive_terms,
            "difference_curriculum": difference_curriculum,
            "scope": "synthetic_structural_transfer_not_unseen_semantic_families_or_arena_score",
            "split_policy": "content_disjoint_alpha_renamed_shared_structural_families",
            "semantic_family_decontamination": False,
            "extended_curriculum": extended, "reconstruction_heads_unchanged": base_heads_unchanged,
            "compositional_holdout": compositional_holdout,
            "trajectory_training": trajectory_training, "solver_feedback_enabled": solver_feedback,
            "typed_terms_enabled": typed_terms,
            "train_parent_ids": [r["id"] for r in train_rows],
            "epochs": epochs, "fixture_seed": seed, "config": config.to_dict(), "grammar": grammar,
            "train_ids": [e.sample_id for e in train], "manifest": rows, "manifest_sha256": digest(rows),
            "before": before, "after": after, "zero_weight_ablation": ablation,
            "development_gates": gates, "holdout": holdout_report, "holdout_accessed_after_freeze": True,
            "holdout_zero_weight_ablation": holdout_ablation, "holdout_gate": holdout_gate,
            "holdout_valid": holdout_valid, "tuning_allowed_after_holdout": False,
            "learned_verified_shortening": any(r["verified_shortening"] for r in all_after if r["split"] != "train"),
            "model_step": model.step, "rewrite_steps": model.state["rewrite_steps"], "history": history,
            "state": frozen, "state_sha256": digest(frozen), "teachers": teachers,
            **({"structural_pairs": structural, "structural_pair_targets_used": True,
                "graph_features_used_for_training": False} if structural is not None else {}),
            "compile_attempts": attempts, "events": events,
            "checkpoint_promoted": False, "production_memory_used": False, "arena_data_used": False,
            "live_llm_used": False, "official_score": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--extended", action="store_true", help="include application, eta and solver-list teachers")
    parser.add_argument("--compositional-holdout", action="store_true", help="add held-out branch compositions and new domain/control fixtures")
    parser.add_argument("--freeze-reconstruction-heads", action="store_true", help="train only rewrite selection; keep operation and latent parameters fixed")
    parser.add_argument("--trajectory-training", action="store_true", help="train and score audited adjacent rewrite steps")
    parser.add_argument("--solver-feedback", action="store_true", help="query and independently replay compiler suggestions")
    parser.add_argument("--typed-terms", action="store_true", help="distill kernel-replayed elaborated proof terms")
    parser.add_argument("--proof-metrics", action="store_true", help="inspect exact compiled theorem expressions (extra compiler cost)")
    parser.add_argument("--cost-guard", action="store_true", help="require measured non-growing proof terms for teachers and raw predictions")
    parser.add_argument("--constructive-terms", action="store_true", help="search and distill constructive propositional terms")
    parser.add_argument("--constructive-curriculum", action="store_true", help="use the dedicated constructive curriculum")
    parser.add_argument("--difference-curriculum", action="store_true", help="add path-certified difference-bound teachers")
    parser.add_argument("--structural-pairs", action="store_true", help="require fresh source/target DAG checks before endpoint training")
    parser.add_argument("--environment-sha256", help="caller-owned dependency manifest fingerprint for structural exports")
    parser.add_argument("--max-compiles", type=int, default=192)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.structural_pairs != (args.environment_sha256 is not None):
        parser.error("--structural-pairs and --environment-sha256 must be supplied together")
    if args.structural_pairs and args.trajectory_training:
        parser.error("structural pairs currently support endpoint training, not --trajectory-training")
    if args.output.exists():
        parser.error("output exists; choose a new receipt path")
    result = run_distillation(_lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake,
                                            kernel_only=True, timeout=30, collect_diagnostics=args.solver_feedback or args.typed_terms,
                                            measure_proofs=args.proof_metrics or args.cost_guard), epochs=args.epochs, seed=args.seed,
                              rows=constructive_rows(args.seed) if args.constructive_curriculum else None,
                              extended=args.extended, freeze_reconstruction_heads=args.freeze_reconstruction_heads,
                              compositional_holdout=args.compositional_holdout,
                              trajectory_training=args.trajectory_training, solver_feedback=args.solver_feedback,
                              typed_terms=args.typed_terms, constructive_terms=args.constructive_terms, cost_guard=args.cost_guard,
                              difference_curriculum=args.difference_curriculum,
                              structural_compile_fn=(_lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake,
                                                                  kernel_only=True, export_dags=True, timeout=45,
                                                                  environment_sha256=args.environment_sha256)
                                                     if args.structural_pairs else None),
                              structural_environment_sha256=args.environment_sha256,
                              max_compiles=args.max_compiles,
                              event=lambda row: print(json.dumps(row), flush=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    summary = {key: result.get(key) for key in ("ok", "reason", "model_step", "rewrite_steps", "grammar",
                                               "development_gates", "learned_verified_shortening", "state_sha256")}
    for phase in ("before", "after", "zero_weight_ablation", "holdout"):
        summary[phase] = {split: {k: v for k, v in values.items() if k != "rows"}
                          for split, values in result.get(phase, {}).items()}
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
