"""Replay saved structural smoke evidence; this does not repeat kernel checking."""
import gzip
import hashlib
import json
from pathlib import Path

from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
from jevops.expr_dag import _bytes, root_summaries
from jevops.refactor_report import generate_report
from jevops.rewrite_distillation import digest
from jevops.router_tuning import _ir_body, _render_source, _source_parts

REPORT = Path(__file__).with_name("fixtures") / "structural_pair_report"


def test_saved_pair_graphs_and_frozen_predictions_are_reproducible():
    raw = json.loads(gzip.decompress((REPORT / "inputs/run.json.gz").read_bytes()))
    checkpoint = json.loads((REPORT / "checkpoint.json").read_text())
    assert raw["state_sha256"] == checkpoint["state_sha256"] == digest(checkpoint["state"])
    structural = raw["structural_pairs"]
    assert structural["ok"] and structural["accepted_count"] == 1
    assert structural["compile_calls"] == 2 and not raw["graph_features_used_for_training"]
    assert raw["model_step"] == 12 and raw["reconstruction_heads_unchanged"]
    assert raw["cost_gate"]["accepted"] and raw["holdout_gate"]["accepted"]
    for pair in structural["pairs"]:
        assert pair["split"] == "train" and pair["id"] in raw["train_ids"]
        assert pair["pair_sha256"] == hashlib.sha256(_bytes({k: v for k, v in pair.items() if k != "pair_sha256"})).hexdigest()
        for side in ("source", "target"):
            wire = structural["graphs"][pair[side]["dag_sha256"]]
            assert hashlib.sha256(_bytes(wire)).hexdigest() == pair[side]["dag_sha256"]
            summary = root_summaries(wire, environment=wire["environment"])
            assert summary == [pair[side]["proof"], pair[side]["type"]]
        assert pair["target"]["proof"]["expanded_expression_nodes"] < pair["source"]["proof"]["expanded_expression_nodes"]
    model = LeanIRAutoencoder.from_dict(checkpoint["state"], config=AutoencoderConfig(**checkpoint["config"]))
    source = next(r["source"] for r in raw["manifest"] if r["split"] == "holdout")
    prefix, _, theorem = _source_parts(source)
    predicted = _render_source(prefix, _ir_body(model.predict_ir(source)), has_theorem=theorem)
    assert predicted == raw["holdout"]["holdout"]["rows"][0]["prediction"]
    assert raw["holdout"]["holdout"]["verified_shortening"] == 1
    assert raw["holdout_zero_weight_ablation"]["holdout"]["verified_shortening"] == 0
    assert not raw["checkpoint_promoted"] and raw["official_score"] is None


def test_structural_report_regenerates_byte_exactly_from_archived_receipts(tmp_path):
    provenance = json.loads((REPORT / "provenance.json").read_text())
    for name, expected in provenance["output_sha256"].items():
        assert hashlib.sha256((REPORT / name).read_bytes()).hexdigest() == expected
    raw = gzip.decompress((REPORT / "inputs/run.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == provenance["input_sha256"]["run"]
    generate_report(REPORT / "inputs/run.json.gz", tmp_path, archive_inputs=True)
    for name in ("checkpoint.json", "evidence.json", "summary.md", "inputs/run.json.gz"):
        assert (REPORT / name).read_bytes() == (tmp_path / name).read_bytes()
