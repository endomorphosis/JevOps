"""Measure raw frozen predictions and exact compiled proof expressions.

No grammar mining, target reading, weight updates or compiler repair. This is
a separate opt-in structural-cost gate, not production promotion or a
kernel-time study. A truncated selection cannot pass the size gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from .autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
from .proof_metrics import compare_proofs
from .rewrite_distillation import digest
from .router_tuning import _ir_body, _lean_compiler, _render_source, _source_parts


def measure_checkpoint(checkpoint, compile_fn, *, family_prefix="typed_", max_examples=16):
    if digest(checkpoint["state"]) != checkpoint["state_sha256"]:
        raise ValueError("checkpoint digest mismatch")
    if type(max_examples) is not int or not 1 <= max_examples <= 32:
        raise ValueError("invalid measurement budget")
    model = LeanIRAutoencoder.from_dict(checkpoint["state"], config=AutoencoderConfig(**checkpoint["config"]))
    frozen = model.to_dict()
    matched = [r for r in checkpoint["manifest"] if r["split"] == "holdout" and r.get("family", "").startswith(family_prefix)]
    rows = matched[:max_examples]
    cache = {}
    def compile_one(source):
        if source not in cache:
            cache[source] = dict(compile_fn(source))
        return cache[source]
    results = []
    for row in rows:
        source = row["source"]
        prediction = model.predict_ir(source)
        prefix, _, theorem = _source_parts(source)
        rendered = _render_source(prefix, _ir_body(prediction), has_theorem=theorem)
        results.append({"id": row["id"], "family": row["family"], "rewrite_policy": prediction.get("rewrite_policy"),
                        **compare_proofs(source, rendered, compile_one)})
    assert model.to_dict() == frozen
    return {"schema": "jevops-checkpoint-expression-cost/v1", "ok": bool(results) and all(r["ok"] for r in results),
            "state_sha256": checkpoint["state_sha256"], "evaluations": results,
            "selection": {"family_prefix": family_prefix, "matched_count": len(matched),
                          "evaluated_count": len(results), "complete": len(results) == len(matched)},
            "expression_gates_accepted": bool(results) and len(results) == len(matched)
                and all(r["ok"] and r["expression_nonregression"] is True for r in results),
            "pareto_improvement_count": sum(r["source_and_expression_improvement"] for r in results),
            "unique_compile_count": len(cache), "training_enabled": False, "teacher_at_inference": False,
            "compiler_repair_used": False, "checkpoint_promoted": False, "kernel_time_measured": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--family-prefix", default="typed_")
    parser.add_argument("--max-examples", type=int, default=16)
    parser.add_argument("--require-expression-nonregression", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists")
    checkpoint = json.loads(args.checkpoint.read_text())
    compiler = _lean_compiler(project_root=args.project_root.resolve(), use_lake=args.lake,
                              kernel_only=True, measure_proofs=True, timeout=45)
    result = measure_checkpoint(checkpoint, compiler, family_prefix=args.family_prefix, max_examples=args.max_examples)
    result["checkpoint_file_sha256"] = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    cmd = (["lake", "env", "lean"] if args.lake else ["lean"]) + ["--version"]
    result["compiler_version"] = subprocess.run(cmd, cwd=args.project_root, capture_output=True, text=True, check=True).stdout.strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"ok": result["ok"], "state_sha256": result["state_sha256"],
                      "expression_gates_accepted": result["expression_gates_accepted"], "selection": result["selection"],
                      "proofs": [{k:r[k] for k in ("id", "source_tokens", "prediction_tokens", "expression_nonregression")}
                                 for r in result["evaluations"]]}), flush=True)
    return 0 if result["ok"] and (not args.require_expression_nonregression or result["expression_gates_accepted"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
