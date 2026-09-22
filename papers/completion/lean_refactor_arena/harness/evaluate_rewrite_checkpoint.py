#!/usr/bin/env python3
"""Frozen model-only arena evaluation: no router search, training or repair.

Historical inputs and a supplied reference are regression data, not unseen
canaries. The reference is compiled before any prediction and used only in
loss diagnostics, never as a decoder input or fallback result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import autoencoder_bridge as bridge
from historical_seeds import load_historical_seeds
from jevops import autoencoder as ae
from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, canary_gate, coerce_training_example, loss_for_example
from jevops.router_tuning import _ir_body, _render_source, _source_parts


def state_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def evaluate_checkpoint(record: Mapping[str, Any], checkpoint: Mapping[str, Any], *,
                        compiler: Callable[..., Mapping[str, Any]] | None = None,
                        include_history: bool = True, reference_source: str | None = None,
                        timeout: float = 60) -> dict[str, Any]:
    if state_digest(checkpoint["state"]) != checkpoint["state_sha256"]:
        raise ValueError("checkpoint state digest mismatch")
    config = AutoencoderConfig(**checkpoint["config"])
    model = LeanIRAutoencoder.from_dict(checkpoint["state"], config=config)
    frozen = model.to_dict()
    zero = model.copy()
    zero.state["rewrite_weights"] = {}
    initial = LeanIRAutoencoder(config=config)
    # Match both vocabularies: cold vs trained CE must have the same support.
    initial.state["vocab"] = list(model.state["vocab"])
    initial.state["op_bias"] = dict.fromkeys(initial.state["vocab"], 0.0)
    initial.state["rewrite_templates"] = model.to_dict()["rewrite_templates"]
    compile_raw = compiler or bridge.compiler_for_record(record, compile_timeout=timeout, network="deny", kernel_only=True)
    cache = {}
    def compile_one(source):
        if source not in cache:
            cache[source] = dict(compile_raw(source))
        return cache[source]
    def accepted(result):
        return result.get("theorem_ok") is True and result.get("kernel_audit", {}).get("accepted") is True
    def tokens(source):
        body = bridge._candidate_tactics(record, source)
        if body is None:
            raise ValueError("candidate changed frozen statement")
        return bridge.lra_loop.token_count(body)

    prefix, _, theorem = _source_parts(str(record["src"]))
    inputs = [("frozen_original", str(record["src"]))]
    history = []
    if include_history:
        for seed in load_historical_seeds(str(record["name"]), token_fn=bridge.lra_loop.token_count, limit=1):
            source = _render_source(prefix, seed["body"], has_theorem=theorem)
            result = compile_one(source)
            history.append({"commit": seed["commit"], "path": seed["path"], "body_tokens": tokens(source),
                            "verified": accepted(result), "compile": result})
            if accepted(result):
                inputs.append(("historical_best", source))
    reference = reference_source or min((s for _, s in inputs), key=tokens)
    tokens(reference)  # Freeze/check its exact theorem envelope first.
    reference_receipt = compile_one(reference)
    if not accepted(reference_receipt):
        return {"ok": False, "reason": "unverified_fixed_reference", "compile": reference_receipt}
    rows = []
    for kind, source in inputs:
        source_receipt = compile_one(source)
        ex = coerce_training_example({"text": source, "target_ir": ae.encode_lean_ir(reference)})
        comparisons = {}
        for lane, decoder in (("untrained", initial), ("trained", model), ("zero_edit_weights", zero)):
            prediction = decoder.predict_ir(ex.text, source_ir=ex.source_ir)
            candidate = _render_source(prefix, _ir_body(prediction), has_theorem=theorem)
            receipt = compile_one(candidate)
            ok = accepted(receipt)
            loss = loss_for_example(decoder, ex, predicted_ir=prediction, verifier_reward=float(ok))
            comparisons[lane] = {"body_tokens": tokens(candidate), "source": candidate,
                                 "verified": ok, "verified_shortening": ok and tokens(candidate) < tokens(source),
                                 "compile": receipt, "loss": loss.to_dict(),
                                 "rewrite_policy": prediction.get("rewrite_policy")}
        def metrics(lane):
            loss = comparisons[lane]["loss"]
            return {**loss, "objective": loss["total"], "sample_count": 1,
                    "verifier_success_rate": float(comparisons[lane]["verified"]), "verifier_evaluated_count": 1,
                    "rewrite_sample_count": int(loss["rewrite_cross_entropy"] is not None)}
        gate = canary_gate(metrics("untrained"), metrics("trained"), max_cross_entropy_regression=.02)
        rows.append({"input": kind, "source_tokens": tokens(source), "source_verified": accepted(source_receipt),
                     "source_compile": source_receipt, "metric_gate": gate, **comparisons})
    assert model.to_dict() == frozen, "model-only evaluation changed checkpoint"
    return {"schema": "jevops-model-only-arena-rewrite/v1", "name": record["name"],
            "ok": all(r["source_verified"] and r["trained"]["verified"] for r in rows),
            "state_sha256": checkpoint["state_sha256"], "reference_source": reference,
            "reference_tokens": tokens(reference), "reference_compile": reference_receipt,
            "history": history, "evaluations": rows, "unique_compile_count": len(cache),
            "metric_gates_accepted": all(r["metric_gate"]["accepted"] for r in rows),
            "router_search_used": False, "teacher_at_inference": False, "training_enabled": False,
            "checkpoint_promoted": False, "production_memory_used": False, "official_score": None,
            "scope": "frozen_model_local_regression_not_unseen_arena_holdout"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--reference-fixture", type=Path, help="local regression JSON with matching name and best_source")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new receipt path")
    checkpoint = json.loads(args.checkpoint.read_text())
    _, digest, records = bridge.load_records()
    record = next((r for r in records if r["name"] == args.name), None)
    if record is None:
        parser.error("unknown frozen record")
    reference = None
    if args.reference_fixture:
        fixture = json.loads(args.reference_fixture.read_text())
        if fixture["name"] != args.name:
            parser.error("reference belongs to a different theorem")
        reference = str(fixture["best_source"])
    result = evaluate_checkpoint(record, checkpoint, include_history=not args.no_history, reference_source=reference)
    result["frozen_sha256"] = digest
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({**{k: result.get(k) for k in ("ok", "reason", "state_sha256", "reference_tokens", "metric_gates_accepted")},
                      "evaluations": [{"input": r["input"], "source_tokens": r["source_tokens"], "metric_gate": r["metric_gate"],
                                       **{lane: {k: r[lane][k] for k in ("body_tokens", "verified", "loss", "rewrite_policy")}
                                          for lane in ("untrained", "trained", "zero_edit_weights")}}
                                      for r in result.get("evaluations", [])]}, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
