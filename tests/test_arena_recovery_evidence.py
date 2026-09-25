"""Saved-experiment bookkeeping, explicitly not fresh proof verification."""
import json
from pathlib import Path

from jevops.arena import reference_tokens, source_hash
from jevops.arena_report_audit import audit_provider_pipeline, audit_report

EVIDENCE = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence"


def test_one_token_provider_drafts_never_become_compression_rewards():
    root = EVIDENCE / "native-premise-provider-pilot-2026-09-23"
    protocol = json.loads((root / "selection/protocol.json").read_text())
    report = json.loads((root / "selection/report.json").read_text())
    inventory = json.loads((root / "inventory/report.json").read_text())
    batch = json.loads((root / "drafts/manifest.json").read_text())
    audit = audit_provider_pipeline(protocol, report, inventory, batch)
    assert audit["status"] == "CONSISTENT", audit
    assert audit["proof_verified"] is False and audit["fresh_native_processes"] == 0
    assert audit["reported_pipeline_native_processes"] == 21
    assert len(inventory["inventory"]["premises"]) == 4 and inventory["attempted_processes"] == 1
    assert report["status"] == "NO_IMPROVEMENT" and report["confirmation"] is None
    assert report["selected_for_confirmation"] is report["recommended"] is None
    assert protocol["required_request_budget"] == 32 and report["native_processes"] == 20
    assert report["screen"]["receipt_cache_enabled"] is False
    samples = report["screen"]["samples"]
    assert sum(s["status"] == "VERIFIED" for s in samples) == 8
    assert sum(s["status"] == "REJECTED" for s in samples) == 12
    rows = report["screen_analysis"]["rows"]
    assert rows["historical-260"]["tokens"] == batch["base_tokens"] == 185
    for label in protocol["candidate_labels"]:
        assert rows[label]["tokens"] == 1 and rows[label]["admissible"] is False
        assert all(not values for values in rows[label]["raw_heartbeats_by_stratum"])
    assert batch["proof_verified"] is report["training_enabled"] is report["promoted"] is False
    assert report["official_score"] is None


def test_recovered_185_token_seed_has_separate_fresh_confirmation_not_filename_authority():
    root = EVIDENCE / "native-historical-confirm-2026-09-23"
    protocol = json.loads((root / "protocol.json").read_text())
    report = json.loads((root / "report.json").read_text())
    audit = audit_report(protocol, report)
    assert audit["status"] == "CONSISTENT", audit
    assert audit["proof_verified"] is False and audit["fresh_native_processes"] == 0
    assert report["status"] == "CONFIRMED_LOCAL_IMPROVEMENT"
    assert report["native_processes"] == 24
    assert report["plan"]["selection_objective"] == "strict-dual-v1"
    assert report["training_enabled"] is report["promoted"] is False
    assert report["official_score"] is None
    for phase in ("screen", "confirmation"):
        trial, analysis = report[phase], report[phase + "_analysis"]
        assert len(trial["samples"]) == 12
        assert all(s["status"] == "VERIFIED" and s["verifier_invocations"] == 1 for s in trial["samples"])
        original, incumbent, recovered = [analysis["rows"][label] for label in
                                          ("control", "incumbent-213", "historical-260")]
        assert (original["tokens"], incumbent["tokens"], recovered["tokens"]) == (222, 213, 185)
        for other in (original, incumbent):
            assert all(max(a) < min(b) for a, b in zip(recovered["raw_heartbeats_by_stratum"],
                                                      other["raw_heartbeats_by_stratum"]))
    seed = json.loads((root / "historical-seed.json").read_text())
    assert set(seed) == {"name", "label", "source", "provenance"}
    assert seed["source"] == report["recommended"]["source"]
    assert reference_tokens(seed["source"], protocol["screen"]["record"]["statement"]) == 185
    inventory = json.loads((root / "recovery.json").read_text())
    assert inventory["proof_verified"] is False and inventory["native_processes"] == 0
    found = next(row for row in inventory["rows"] if row["filename_count"] == 260)
    assert found["legacy_body_tokens"] == 260 and found["reference_tokens"] == 185
    assert found["source_sha256"] == source_hash(seed["source"])


def test_shorter_portable_edits_cannot_replace_the_verified_seed_when_lean_rejects_them():
    root = EVIDENCE / "native-portable-pilot-2026-09-23"
    protocol = json.loads((root / "protocol.json").read_text())
    report = json.loads((root / "report.json").read_text())
    audit = audit_report(protocol, report)
    assert audit["status"] == "CONSISTENT", audit
    assert audit["proof_verified"] is False and audit["fresh_native_processes"] == 0
    assert report["status"] == "NO_IMPROVEMENT"
    assert report["recommended"] is report["confirmation"] is None
    assert report["retained_incumbent"] == "historical-260" and report["retained_incumbent_verified"]
    assert report["native_processes"] == report["requests_reserved"] == 20
    samples = report["screen"]["samples"]
    assert sum(s["status"] == "REJECTED" for s in samples) == 12
    assert sum(s["status"] == "VERIFIED" for s in samples) == 8
    rows = report["screen_analysis"]["rows"]
    assert rows["historical-260"]["tokens"] == 185 and rows["historical-260"]["admissible"]
    for label, tokens in (("composition-0", 183), ("composition-1", 176), ("composition-2", 174)):
        assert rows[label]["tokens"] == tokens and not rows[label]["admissible"]
    batch = json.loads((root / "drafts.json").read_text())
    assert batch["reference_tokens"] == 222 and batch["base_tokens"] == 185
    assert batch["reference_source_sha256"] == source_hash(protocol["screen"]["record"]["src"])
    assert batch["tokenizer_id"] == protocol["tokenizer_id"] == "lra-reference-lexical/v1"
    assert batch["proof_verified"] is report["training_enabled"] is report["promoted"] is False
