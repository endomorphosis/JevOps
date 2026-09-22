#!/usr/bin/env python3
"""Isolated, non-training reduction probes over frozen arena records.

Uses a deterministic strategy plan, not a live LLM or an official arena score.
Never reads/writes production training memory. Historical proofs, when enabled,
are recompiled as untrusted proposals and make this a seeded regression probe,
not an unseen holdout measurement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

import autoencoder_bridge as bridge
from historical_seeds import load_historical_seeds
from jevops import autoencoder as ae
from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example
from jevops.router_tuning import RouterTuningConfig, RouterTuningLoop
from jevops.logic_refactor import LOGIC_STRATEGIES


def evaluate_record(record: Mapping[str, Any], *, rounds: int = 2, pool: int = 12,
                    timeout: float = 60, seed_history: bool = True,
                    compiler: Callable[..., Mapping[str, Any]] | None = None,
                    checkpoint: Mapping[str, Any] | None = None,
                    strategies: Sequence[str] | None = None, kernel_only: bool = False) -> dict[str, Any]:
    # Optional isolated training-probe checkpoint is evaluated only; it does
    # not seed search memory and is never fine-tuned on benchmark examples.
    if checkpoint is not None:
        state = checkpoint["state"]
        digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        if checkpoint.get("state_sha256") != digest:
            raise ValueError("checkpoint state digest mismatch")
        model = LeanIRAutoencoder.from_dict(state, config=AutoencoderConfig(**checkpoint["config"]))
    else:
        model = LeanIRAutoencoder.from_dict(None, config=AutoencoderConfig())
    frozen_model = model.to_dict()
    compile_one = compiler or bridge.compiler_for_record(record, compile_timeout=timeout, network="deny", kernel_only=kernel_only)
    selected_strategies = list(strategies) if strategies is not None else ["simp_set_reduce", "branch_invariant", "invariant_reduce"]
    if any(s not in LOGIC_STRATEGIES for s in selected_strategies):
        raise ValueError("unknown reduction strategy")
    attempts = []

    def audited(source: str, **kwargs: Any) -> Mapping[str, Any]:
        started = time.monotonic()
        result = dict(compile_one(source, **kwargs))
        attempts.append({"source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                         "wall_seconds": round(time.monotonic() - started, 3), **result})
        return result

    seeds = load_historical_seeds(str(record["name"]), token_fn=bridge.lra_loop.token_count) if seed_history else []
    memory: dict[str, Any] = {"nca": {"grid": {}, "board_edges": []}}
    config = RouterTuningConfig(rounds=rounds, max_candidate_pool=pool, max_router_candidates=3,
                               max_logic_candidates=6, max_hammer_candidates=3, n_variations=2,
                               max_composed_candidates=2, max_elite_composed_candidates=2,
                               teacher_replay=False, train=False)
    loop = RouterTuningLoop(memory, str(record["src"]), problem=str(record["name"]),
                           compile_fn=audited, config=config, seed_candidates=seeds,
                           router_generate=lambda _: json.dumps({"strategies": selected_strategies}))
    result = bridge._bind_result(record, loop.run())
    # Evaluate the frozen model separately from the winning search target.
    example = coerce_training_example({"text": str(record["src"]),
                                       "source_ir": ae.encode_lean_ir(str(record["src"])),
                                       "target_ir": result["best_ir"]})
    diagnostics = loop._model_diagnostics(model, example, phase="evaluation_only")
    raw_diagnostics = loop._model_diagnostics(model, example, phase="raw_ablation", dependency_guard=False)
    sequence_diagnostics = loop._model_diagnostics(model, example, phase="sequence_ablation",
                                                   dependency_guard=False, binding_policy=False)
    assert model.to_dict() == frozen_model, "benchmark evaluation changed model weights"
    history = result["history"]
    assert not any(r["training"].get("trained") for r in history)
    assert not memory.get("nca", {}).get("autoencoder", {}).get("training_state")
    verified_seeds = [c for r in history for c in r["candidates"]
                      if c.get("origin") == "verified_seed" and c.get("lake_ok")]
    previous = min((int(s["body_tokens"]) for s in verified_seeds), default=None)
    kept = {k: result[k] for k in ("ok", "name", "source_body_tokens", "best_body_tokens", "best_source",
                                   "benchmark", "history", "search_summary") if k in result}
    kept.update(name=record["name"], schema="jevops-logic-benchmark-validation/v1",
                mode="seeded_regression" if seed_history else "unseeded_evaluation",
                router="deterministic_strategy_plan", production_memory_used=False,
                requested_strategies=selected_strategies, kernel_only=kernel_only,
                training_enabled=False, nca_memory_discarded=True, model_step=model.step,
                binding_steps=model.state.get("binding_steps", 0),
                model_checkpoint=(None if checkpoint is None else {
                    "state_sha256": checkpoint["state_sha256"], "schema": checkpoint.get("schema"),
                    "config": model.config.to_dict(), "evaluation_only": True}),
                historical_seed_tokens_reverified=previous,
                beats_reverified_history=(bool(result["ok"]) and result["best_body_tokens"] < previous)
                if previous is not None else None,
                model_evaluation={"loss": diagnostics["loss"],
                                  "body_tokens": diagnostics["row"]["body_tokens"],
                                  "lake_ok": diagnostics["row"]["lake_ok"],
                                  "dependency_guard": diagnostics["prediction"].get("dependency_guard"),
                                  "binding_policy": diagnostics["prediction"].get("binding_policy"),
                                  "raw_ablation": {"loss": raw_diagnostics["loss"],
                                                   "body_tokens": raw_diagnostics["row"]["body_tokens"],
                                                   "lake_ok": raw_diagnostics["row"]["lake_ok"]},
                                  "sequence_ablation": {"loss": sequence_diagnostics["loss"],
                                                        "body_tokens": sequence_diagnostics["row"]["body_tokens"],
                                                        "lake_ok": sequence_diagnostics["row"]["lake_ok"]},
                                  "target": "best_verified_search_result" if result["ok"] else "unverified_reference"},
                compile_attempts=attempts, arena_score=None, official_score=None)
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--pool", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--strategy", action="append", choices=LOGIC_STRATEGIES)
    parser.add_argument("--kernel-only", action="store_true", help="audit target transitive axiom closure in each pinned project")
    parser.add_argument("--model-checkpoint", type=Path, help="training-probe JSON; evaluation only, never search/training memory")
    parser.add_argument("--output", type=Path, required=True, help="new receipt file outside the curated dataset")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new receipt path")
    checkpoint = json.loads(args.model_checkpoint.read_text(encoding="utf-8")) if args.model_checkpoint else None
    raw, digest, records = bridge.load_records()
    names = args.name or [str(records[0]["name"]) ]
    by_name = {str(r["name"]): r for r in records}
    if set(names) - set(by_name):
        parser.error("unknown frozen record name")
    results = []
    for name in names:
        print(json.dumps({"event": "start", "name": name}), flush=True)
        result = evaluate_record(by_name[name], rounds=args.rounds, pool=args.pool,
                                 timeout=args.timeout, seed_history=not args.no_history, checkpoint=checkpoint,
                                 strategies=args.strategy, kernel_only=args.kernel_only)
        results.append(result)
        print(json.dumps({key: result[key] for key in (
            "name", "ok", "source_body_tokens", "best_body_tokens", "historical_seed_tokens_reverified",
            "beats_reverified_history", "model_evaluation", "search_summary")}), flush=True)
    payload = {"schema": "jevops-logic-benchmark-validation-batch/v1", "frozen_sha256": digest,
               "frozen_bytes": len(raw), "results": results, "official_score": None, "arena_score": None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
