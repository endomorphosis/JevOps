"""Reproduce archived measurements; receipt replay is not a fresh Lean check."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from jevops import autoencoder as ae
from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
from jevops.measure_checkpoint import measure_checkpoint
from jevops.refactor_report import generate_report
from jevops.rewrite_distillation import digest

REPORT = Path(__file__).with_name("fixtures") / "guarded_rewrite_report"


def test_frozen_guarded_model_reproduces_raw_proofs_and_costs():
    cp = json.loads((REPORT / "checkpoint.json").read_text())
    evidence = json.loads((REPORT / "evidence.json").read_text())
    assert digest(cp["state"]) == cp["state_sha256"] == evidence["expressions"]["state_sha256"]
    receipts = {r[side]: r["receipts"][side] for r in evidence["expressions"]["evaluations"] for side in ("source", "prediction")}
    report = measure_checkpoint(cp, receipts.__getitem__, family_prefix="", max_examples=32)
    assert report["evaluations"] == evidence["expressions"]["evaluations"]
    assert report["expression_gates_accepted"] and report["pareto_improvement_count"] == 8
    assert sum(r["source_tokens"] for r in report["evaluations"]) == 95
    assert sum(r["prediction_tokens"] for r in report["evaluations"]) == 33
    for row in report["evaluations"]:
        a,b = (row["receipts"][k]["proof_metrics"]["proof"] for k in ("source", "prediction"))
        assert b["tree_nodes"] < a["tree_nodes"]
    config = AutoencoderConfig(**cp["config"])
    model = LeanIRAutoencoder.from_dict(cp["state"], config=config)
    cold = LeanIRAutoencoder(config=config)
    for key in ("op_bias", "transition", "feature_op", "latent_bias", "feature_latent", "vocab"):
        assert model.to_dict()[key] == cold.to_dict()[key]
    model.state["rewrite_weights"] = {}
    for row in cp["manifest"]:
        if row["split"] == "holdout":
            assert row["id"] not in cp["train_parent_ids"]
            assert model.predict_ir(row["source"])["ops"] == ae.encode_lean_ir(row["source"])["ops"]
    s = evidence["synthetic"]
    assert s["holdout"]["holdout"]["trajectory_labeled_step_count"] == s["holdout"]["holdout"]["trajectory_step_count"] == 8
    assert s["cost_gate"]["accepted"] and not cp["checkpoint_promoted"]
    # This focused curriculum did not reproduce the older arena shortening.
    assert [(r["source_tokens"],r["trained"]["body_tokens"]) for r in evidence["arena"]["evaluations"]] == [(482,482),(392,392)]
    assert evidence["arena"]["reference_tokens"] == 391
    old = json.loads((REPORT.parent / "typed_edit_evidence.json").read_text())
    assert not old["expressions"]["expression_gates_accepted"]


def test_generated_bundle_is_rebuildable_from_archived_raw_receipts(tmp_path):
    provenance = json.loads((REPORT / "provenance.json").read_text())
    for name, expected in provenance["output_sha256"].items():
        assert hashlib.sha256((REPORT / name).read_bytes()).hexdigest() == expected
    for key, expected in provenance["input_sha256"].items():
        assert hashlib.sha256(gzip.decompress((REPORT / f"inputs/{key}.json.gz").read_bytes())).hexdigest() == expected
    generate_report(REPORT / "inputs/run.json.gz", tmp_path, arena_path=REPORT / "inputs/arena.json.gz",
                     expressions_path=REPORT / "inputs/expressions.json.gz", archive_inputs=True)
    for name in ("checkpoint.json", "evidence.json", "summary.md"):
        assert (REPORT / name).read_bytes() == (tmp_path / name).read_bytes()
