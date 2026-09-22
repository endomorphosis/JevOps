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
from .router_tuning import _ir_body, _lean_compiler, _render_source, _source_parts


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def curriculum_rows(seed: int = 20260923) -> list[dict[str, Any]]:
    rows = []
    for split_index, split in enumerate(("train", "validation", "canary", "holdout")):
        rng = random.Random(17 if split == "train" else seed + split_index)
        for family in ("exact_local", "terminal_alias", "constructor_pack", "symmetry", "projection", "lift_projection"):
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
            else:
                header = f"({p} : Prop) : PLift {p} → {p}"
                body, methods = f"intro {h}\nexact {h}.1", ["logic_simp"]
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


def verified(receipt: Mapping[str, Any]) -> bool:
    # The compiler callback is trusted infrastructure, never an LLM's claim.
    return receipt.get("theorem_ok") is True and receipt.get("kernel_audit", {}).get("accepted") is True


def collect_teacher(row: Mapping[str, Any], compile_one: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    source = str(row["source"])
    original = dict(compile_one(source))
    if not verified(original):
        return {"ok": False, "reason": "unverified_source", "id": row["id"], "compile": original}
    prefix, body, has_theorem = _source_parts(source)
    best, best_tokens, trace = source, ae.proof_body_token_count(source), []
    goal = ae.encode_lean_ir(source)["goal"]
    # Ordered methods make a bounded trajectory. Each accepted intermediate
    # is checked; no equivalence is inferred from text or cosine similarity.
    for strategy in list(row.get("strategies", ()))[:8]:
        _, body = body_of(best)
        for kind, draft, _ in reduction_variants(body, strategy=strategy, goal=goal, cap=4):
            candidate = _render_source(prefix, draft, has_theorem=has_theorem)
            tokens = ae.proof_body_token_count(candidate)
            if tokens >= best_tokens:
                continue
            receipt = dict(compile_one(candidate))
            if verified(receipt):
                trace.append({"strategy": strategy, "kind": kind, "before_tokens": best_tokens,
                              "after_tokens": tokens, "source_sha256": digest(candidate), "compile": receipt})
                best, best_tokens = candidate, tokens
                break
    return {"ok": True, "id": row["id"], "source": source, "target": best,
            "source_tokens": ae.proof_body_token_count(source), "target_tokens": best_tokens,
            "strict_shortening": best_tokens < ae.proof_body_token_count(source),
            "trace": trace, "source_compile": original}


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [r["loss"] for r in rows]
    edits = [r for r in values if r["rewrite_cross_entropy"] is not None]
    mean = lambda key: sum(v[key] for v in values)/len(values) if values else None
    return {"sample_count": len(rows), "verified": sum(r["verified"] for r in rows),
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
                     event: Callable[[Mapping[str, Any]], Any] | None = None) -> dict[str, Any]:
    if not 1 <= epochs <= 200 or not 1 <= max_compiles <= 512:
        raise ValueError("invalid distillation budget")
    rows = list(curriculum_rows(seed) if rows is None else rows)
    _validate_rows(rows)
    config = AutoencoderConfig(train_rewrite_policy=True, learning_rate=.15, warmup_steps=0,
                               decay_steps=1000, rewrite_max_edits=4, seed=17)
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

    teachers = {}
    development = [r for r in rows if r["split"] != "holdout"]
    for row in development:
        notify("teacher", id=row["id"], split=row["split"])
        teachers[row["id"]] = collect_teacher(row, compile_one)
        if not teachers[row["id"]]["ok"]:
            return {"ok": False, "reason": "unverified_fixture", "failure": teachers[row["id"]],
                    "model_step": model.step, "compile_attempts": attempts}

    def example(row):
        teacher = teachers[row["id"]]
        return coerce_training_example({"id": row["id"], "text": row["source"],
                                        "target_ir": ae.encode_lean_ir(teacher["target"])})

    train = [example(row) for row in development if row["split"] == "train"]
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
            tokens = ae.proof_body_token_count(rendered)
            loss = loss_for_example(decoder, ex, predicted_ir=prediction, verifier_reward=float(ok))
            outputs.append({"id": row["id"], "split": row["split"], "family": row.get("family"),
                            "source_tokens": ae.proof_body_token_count(ex.text), "prediction_tokens": tokens,
                            "prediction": rendered, "prediction_sha256": digest(rendered), "compile": receipt,
                            "verified": ok, "verified_shortening": ok and tokens < ae.proof_body_token_count(ex.text),
                            "loss": loss.to_dict(), "rewrite_policy": prediction.get("rewrite_policy"),
                            "teacher_tokens": teachers[row["id"]]["target_tokens"]})
        assert decoder.to_dict() == snapshot, "evaluation mutated the checkpoint"
        return {split: _aggregate([r for r in outputs if r["split"] == split])
                for split in dict.fromkeys(r["split"] for r in selected)}

    before = evaluate(development, model)
    notify("training", epochs=epochs, train_count=len(train), templates=grammar["template_count"])
    history = []
    for epoch in range(epochs):
        report = model.train_batch(train)
        if epoch in {0, epochs//2, epochs-1}:
            history.append({"epoch": epoch+1, **report})
    frozen = model.to_dict()
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
        teachers[row["id"]] = collect_teacher(row, compile_one)
    holdout_valid = all(teachers[r["id"]]["ok"] for r in holdout)
    holdout_report = evaluate(holdout, model) if holdout_valid else {}
    holdout_ablation = evaluate(holdout, zeroed) if holdout_valid else {}
    holdout_gate = (canary_gate(holdout_ablation["holdout"], holdout_report["holdout"],
                                max_cross_entropy_regression=.02) if holdout and holdout_valid else
                    {"accepted": False, "status": "not_measured_or_invalid"})
    assert model.to_dict() == frozen
    assert set(r.sample_id for r in train).isdisjoint(r["id"] for r in rows if r["split"] != "train")
    all_after = [r for split in after.values() for r in split["rows"]]
    return {"schema": "jevops-verified-rewrite-distillation/v1",
            "ok": gates_accepted and holdout_valid and (not holdout or holdout_gate["accepted"]),
            "scope": "synthetic_structural_transfer_not_unseen_semantic_families_or_arena_score",
            "epochs": epochs, "fixture_seed": seed, "config": config.to_dict(), "grammar": grammar,
            "train_ids": [e.sample_id for e in train], "manifest": rows, "manifest_sha256": digest(rows),
            "before": before, "after": after, "zero_weight_ablation": ablation,
            "development_gates": gates, "holdout": holdout_report, "holdout_accessed_after_freeze": True,
            "holdout_zero_weight_ablation": holdout_ablation, "holdout_gate": holdout_gate,
            "holdout_valid": holdout_valid, "tuning_allowed_after_holdout": False,
            "learned_verified_shortening": any(r["verified_shortening"] for r in all_after if r["split"] != "train"),
            "model_step": model.step, "rewrite_steps": model.state["rewrite_steps"], "history": history,
            "state": frozen, "state_sha256": digest(frozen), "teachers": teachers,
            "compile_attempts": attempts, "events": events,
            "checkpoint_promoted": False, "production_memory_used": False, "arena_data_used": False,
            "live_llm_used": False, "official_score": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new receipt path")
    result = run_distillation(_lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake,
                                            kernel_only=True, timeout=30), epochs=args.epochs, seed=args.seed,
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
