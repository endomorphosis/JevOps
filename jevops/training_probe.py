"""Small, isolated training experiment with real rendered-proof evaluation.

This is a deletion-learning diagnostic, not an arena score or evidence of
general theorem synthesis. Held-out fixtures include a live-binding trap;
failed predictions are recorded, never repaired with the teacher target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Callable, Mapping

from . import autoencoder as ae
from .autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example, loss_for_example
from .router_tuning import _ir_body, _lean_compiler, _render_source, _source_parts


def probe_rows(*, fixture_seed: int = 20260922, curriculum: str = "legacy") -> list[dict[str, str]]:
    if curriculum not in {"legacy", "balanced"}:
        raise ValueError("unknown curriculum")
    rows = []
    for i in range(4):
        prefix = f"theorem train_{i} (p : Prop) (h : p) : p := by\n"
        rows.append({"id": f"train-{i}", "split": "train", "text": prefix +
                     f"  have unused{i} : True := True.intro\n  exact h\n",
                     "target": prefix + "  exact h\n"})
    for ident, binders, goal, arg in (
        ("validation_prop", "(q : Prop) (evidence : q)", "q", "evidence"),
        ("validation_equality", "(n m : Nat) (equality : n = m)", "n = m", "equality"),
    ):
        prefix = f"theorem {ident} {binders} : {goal} := by\n"
        rows.append({"id": ident, "split": "validation", "text": prefix +
                     f"  have spare : True := True.intro\n  exact {arg}\n",
                     "target": prefix + f"  exact {arg}\n"})
    live = "theorem live_binding (p : Prop) (h : p) : p := by\n  have proof : p := h\n  exact proof\n"
    rows.append({"id": "live_binding", "split": "negative_control", "text": live, "target": live})
    # Randomized names and literal values, fixed structural families. These
    # are development controls, not unseen semantic families or arena canaries.
    rng = random.Random(fixture_seed)
    for index in range(8):
        suffix = rng.randrange(10**6)
        first, second = f"fact_{suffix}", f"derived_{suffix}"
        family = ("dead_chain", "live_chain", "type_chain", "implicit_context")[index % 4]
        if family == "dead_chain":
            header, closer = "(p : Prop) (h : p) : p", "exact h"
            body = f"have {first} : True := True.intro\nhave {second} : True := {first}\n{closer}"
        elif family == "live_chain":
            header, closer = "(p : Prop) (h : p) : p", f"exact {second}"
            body = f"have {first} : p := h\nhave {second} : p := {first}\n{closer}"
        elif family == "type_chain":
            n = rng.randrange(1, 100)
            header, closer = ": ∃ n : Nat, n = n", f"exact ⟨{first}, {second}⟩"
            body = f"have {first} : Nat := {n}\nhave {second} : {first} = {first} := rfl\n{closer}"
        else:
            header, closer = "(p q : Prop) (h : p ∧ q) : q", "assumption"
            body = f"have {first} : q := h.2\n{closer}"
        prefix = f"theorem dependency_{index}_{suffix} {header} := by\n"
        source = prefix + "\n".join("  " + line for line in body.splitlines()) + "\n"
        rows.append({"id": f"dependency-{index}-{suffix}", "split": "dependency_validation", "family": family,
                     "text": source, "target": prefix + "  exact h\n" if family == "dead_chain" else source})
    if curriculum == "balanced":
        # Four strict shortenings containing both discarded and retained
        # bindings. The evaluation fixtures never become training examples.
        train_specs = (
            ("(p : Prop) (h : p) : p", "have a : True := True.intro\nhave b : True := a\nexact h", "exact h"),
            ("(p : Prop) (h : p) : p", "have a : p := h\nhave b : p := a\nexact b", None),
            (": ∃ n : Nat, n = n", "have a : Nat := 7\nhave b : a = a := rfl\nexact ⟨a, b⟩", None),
            ("(p q : Prop) (h : p ∧ q) : q", "have a : q := h.2\nassumption", None),
        )
        balanced = []
        for i, (header, body, target) in enumerate(train_specs):
            prefix = f"theorem curriculum_{i} {header} := by\n"
            # Context-reader features intentionally overapproximate usage;
            # verified teacher deletions, not the guard, provide the labels.
            source = f"have discard_{i} : True := True.intro\n" + body
            render = lambda text: prefix + "\n".join("  " + line for line in text.splitlines()) + "\n"
            balanced.append({"id": f"train-balanced-{i}", "split": "train", "text": render(source),
                             "target": render(target or body)})
        rows = balanced + [row for row in rows if row["split"] != "train"]
    return rows


def run_probe(compile_fn: Callable[..., Mapping[str, Any]], *, epochs: int = 40,
              fixture_seed: int = 20260922, curriculum: str = "legacy",
              train_binding_policy: bool = False) -> dict[str, Any]:
    if not 1 <= epochs <= 200:
        raise ValueError("epochs must be between 1 and 200")
    config = AutoencoderConfig(learning_rate=.2, warmup_steps=0, decay_steps=1000, seed=17,
                               train_binding_policy=train_binding_policy)
    model = LeanIRAutoencoder(config=config)
    rows = probe_rows(fixture_seed=fixture_seed, curriculum=curriculum)
    examples = {r["id"]: coerce_training_example({"id": r["id"], "text": r["text"],
                                                "target_ir": ae.encode_lean_ir(r["target"])}) for r in rows}
    cache: dict[str, dict[str, Any]] = {}

    def compile_once(source: str) -> dict[str, Any]:
        if source not in cache:
            cache[source] = dict(compile_fn(source))
        return cache[source]

    train = [r for r in rows if r["split"] == "train"]
    # No weight update unless both endpoints of each training pair compile.
    for row in train:
        for endpoint in ("text", "target"):
            if compile_once(row[endpoint]).get("theorem_ok") is not True:
                return {"ok": False, "reason": "unverified_training_pair", "id": row["id"], "model_step": model.step}
    # Validate development fixtures themselves before attributing a compiler
    # failure to the model. They still never enter a training batch.
    for row in rows:
        for endpoint in ("text", "target"):
            if compile_once(row[endpoint]).get("theorem_ok") is not True:
                return {"ok": False, "reason": "unverified_fixture", "id": row["id"],
                        "endpoint": endpoint, "model_step": model.step}

    def evaluate_prediction(row: Mapping[str, str], *, guarded: bool, binding_policy: bool | None = None) -> dict[str, Any]:
        example = examples[row["id"]]
        prediction = model.predict_ir(example.text, source_ir=example.source_ir,
                                       dependency_guard=guarded, binding_policy=binding_policy)
        prefix, _, has_theorem = _source_parts(example.text)
        body = _ir_body(prediction)
        rendered = (_render_source(prefix, body, has_theorem=has_theorem) if body is not None
                    else ae.decode_lean_ir(prediction))
        receipt = compile_once(rendered)
        verified = receipt.get("theorem_ok") is True
        loss = loss_for_example(model, example, predicted_ir=prediction, verifier_reward=float(verified))
        return {"source_tokens": ae.proof_body_token_count(example.text),
                "prediction_tokens": ae.proof_body_token_count(rendered), "prediction": rendered,
                "verified": verified, "verified_shortening": verified and
                ae.proof_body_token_count(rendered) < ae.proof_body_token_count(example.text),
                "cross_entropy": loss.cross_entropy, "cosine_similarity": loss.cosine_similarity,
                "ir_exact_match": loss.ir_exact_match, "compile": receipt,
                "dependency_guard": prediction["dependency_guard"],
                "binding_policy": prediction["binding_policy"], "binding_cross_entropy": loss.binding_cross_entropy}

    def evaluate() -> dict[str, Any]:
        out = [{"id": row["id"], "split": row["split"], "family": row.get("family"),
                **evaluate_prediction(row, guarded=True),
                "raw_ablation": evaluate_prediction(row, guarded=False),
                **({"sequence_ablation": evaluate_prediction(row, guarded=False, binding_policy=False)}
                   if train_binding_policy else {})} for row in rows]
        return {split: [r for r in out if r["split"] == split]
                for split in ("train", "validation", "negative_control", "dependency_validation")}

    before = evaluate()
    for _ in range(epochs):
        model.train_batch([examples[r["id"]] for r in train])
    frozen_state = model.to_dict()
    after = evaluate()
    assert model.to_dict() == frozen_state, "evaluation changed the model"
    return {"ok": True, "schema": "jevops-rendered-training-probe/v3", "epochs": epochs,
            "curriculum": curriculum, "binding_steps": model.state["binding_steps"],
            "fixture_seed": fixture_seed, "decoding_policy": (
                "learned_binding_with_guard_and_sequence_ablations" if train_binding_policy else
                "lexically_guarded_with_raw_model_ablation"),
            "model_step": model.step, "train_ids": [r["id"] for r in train], "config": config.to_dict(),
            "before": before, "after": after, "compile_calls": len(cache),
            "state_sha256": hashlib.sha256(json.dumps(frozen_state, sort_keys=True).encode()).hexdigest(),
            "state": frozen_state, "production_memory_used": False, "arena_data_used": False,
            "scope": "synthetic_deletion_learning_not_arena_generalization"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--fixture-seed", type=int, default=20260922)
    parser.add_argument("--curriculum", choices=("legacy", "balanced"), default="legacy")
    parser.add_argument("--train-binding-policy", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new experiment receipt")
    report = run_probe(_lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake),
                       fixture_seed=args.fixture_seed, curriculum=args.curriculum,
                       train_binding_policy=args.train_binding_policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    summary = {k: v for k, v in report.items() if k not in {"before", "after", "state"}}
    for phase in ("before", "after"):
        summary[phase] = {split: {
            "count": len(rows), "verified": sum(r["verified"] for r in rows),
            "verified_shortening": sum(r["verified_shortening"] for r in rows),
            "raw_verified": sum(r["raw_ablation"]["verified"] for r in rows),
            "raw_verified_shortening": sum(r["raw_ablation"]["verified_shortening"] for r in rows),
            "guard_interventions": sum(bool(r["dependency_guard"]["restored"]) for r in rows),
            "mean_ce": sum(r["cross_entropy"] for r in rows) / max(1, len(rows)),
            "mean_cosine": sum(r["cosine_similarity"] for r in rows) / max(1, len(rows)),
            "mean_raw_cosine": sum(r["raw_ablation"]["cosine_similarity"] for r in rows) / max(1, len(rows)),
            "sequence_verified": sum(r.get("sequence_ablation", r["raw_ablation"])["verified"] for r in rows),
            "sequence_verified_shortening": sum(r.get("sequence_ablation", r["raw_ablation"])["verified_shortening"] for r in rows),
            "mean_binding_ce": (sum(r["binding_cross_entropy"] for r in rows if r["binding_cross_entropy"] is not None)
                                / sum(r["binding_cross_entropy"] is not None for r in rows)
                                if any(r["binding_cross_entropy"] is not None for r in rows) else None),
        } for split, rows in report.get(phase, {}).items()}
    print(json.dumps(summary, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
