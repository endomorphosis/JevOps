"""Historical reports are test data, never fresh proof/timing evidence."""
import copy
import json
from pathlib import Path
import sys

import pytest

from jevops import arena_report_audit as audit
from jevops.arena import content_hash, source_hash


@pytest.fixture
def recorded():
    path = (Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence"
            / "native-strict-dual-smoke-2026-09-22.json")
    report = json.loads(path.read_text())
    return copy.deepcopy(report["plan"]), report


def test_consistent_recording_is_not_fresh_authority(recorded):
    protocol, report = recorded
    before = copy.deepcopy(report)
    result = audit.audit_report(protocol, report)
    assert result["status"] == "CONSISTENT", result
    assert result["reported_selector_status"] == "CONFIRMED_LOCAL_IMPROVEMENT"
    assert result["reported_counts"]["native_processes"] == 20
    assert result["fresh_native_processes"] == 0
    assert not result["proof_verified"] and not result["promoted"] and not result["training_enabled"]
    assert result["official_score"] is None
    assert before == report
    text = audit.summary(result)
    assert "Historical JSON only" in text and len(text.splitlines()) < 30


@pytest.fixture
def synthetic_pipeline(recorded):
    # Deliberately synthetic unsigned discovery data. Consistency must NEVER
    # turn its reported native status into a freshly verified proof.
    protocol, report = recorded
    record = protocol["screen"]["record"]
    arms = {a["label"]: a for a in protocol["screen"]["arms"]}
    seed = arms[protocol["incumbent_label"]]
    env = "a" * 64
    scope = {"schema": "jevops-premise-scope/v1", "environment_sha256": env,
             "record_sha256": content_hash(record), "available_names": [], "excluded_names": [], "excluded_origins": []}
    index = {"schema": "jevops-premise-index/v1", "environment_sha256": env, "premises": []}
    inventory = {"schema": "jevops-native-premise-inventory/v1", "status": "INVENTORY_ONLY",
        "evidence_mode": "trusted_local_native", "record_sha256": content_hash(record),
        "environment_sha256": env, "scope": scope, "inventory": index,
        "metadata": [{"name": "Fake.lemma", "origin": "synthetic-test", "split": "library"}],
        "stages": [{"pin": p.to_dict(), "evidence": {"schema": "jevops-native-premises-stage/v1",
            "target": record["name"], "lean_version": p.lean_tag.removeprefix("v"),
            "report": {"status": "EXPORTED", "entries": [{"name": "Fake.lemma", "status": "MISSING"}]}}}
            for p in audit._pins(record)],
        "attempted_processes": len(audit._pins(record)), "reserved_processes": len(audit._pins(record)),
        "proof_verified": False, "promoted": False, "training_enabled": False, "official_score": None}
    request = {"record_sha256": content_hash(record), "environment_sha256": env,
        "scope_sha256": content_hash({k: v for k, v in scope.items() if k != "schema"}),
        "index_sha256": content_hash({**index, "feature_method": "test-feature-method"}),
        "target": record["name"], "statement": record["statement"], "base_source": seed["source"],
        "base_source_sha256": source_hash(seed["source"])}
    request["request_sha256"] = content_hash(request)
    batch = {"schema": "jevops-arena-provider-batch/v1", "request": request, "seed": seed,
        "ranking": {"feature_method": "test-feature-method"},
        "drafts": [{"name": record["name"], **arms[label]} for label in protocol["candidate_labels"]],
        "native_verifier_calls": 0, "proof_verified": False, "promoted": False,
        "training_enabled": False, "official_score": None}
    return protocol, report, inventory, batch


def test_pipeline_consistency_does_not_authenticate_unsigned_discovery(synthetic_pipeline):
    result = audit.audit_provider_pipeline(*synthetic_pipeline)
    assert result["status"] == "CONSISTENT", result
    assert result["fresh_native_processes"] == 0 and result["proof_verified"] is False
    assert result["reported_pipeline_native_processes"] == 21


@pytest.mark.parametrize("damage", ["record", "scope", "index", "request", "seed", "draft", "pin",
                                    "fixture", "authority", "boolean_count", "stage_target", "stage_status"])
def test_pipeline_cross_artifact_mismatches_are_not_consistent(synthetic_pipeline, damage):
    protocol, report, inventory, batch = copy.deepcopy(synthetic_pipeline)
    if damage == "record": inventory["record_sha256"] = "b" * 64
    elif damage == "scope": inventory["scope"]["excluded_names"] = ["Changed.target"]
    elif damage == "index": inventory["inventory"]["premises"] = [{"name": "Changed.lemma"}]
    elif damage == "request": batch["request"]["request_sha256"] = "b" * 64
    elif damage == "seed": batch["seed"]["source"] += "\n"
    elif damage == "draft": batch["drafts"][0]["source"] += "\n"
    elif damage == "pin": inventory["stages"] = []
    elif damage == "fixture": inventory["status"] = "FIXTURE_ONLY"
    elif damage == "boolean_count": inventory["attempted_processes"] = True
    elif damage == "stage_target": inventory["stages"][0]["evidence"]["target"] = "Other.goal"
    elif damage == "stage_status": inventory["stages"][0]["evidence"]["report"]["status"] = "ERROR"
    else: batch["proof_verified"] = True
    result = audit.audit_provider_pipeline(protocol, report, inventory, batch)
    assert result["status"] != "CONSISTENT"
    assert result["fresh_native_processes"] == 0 and result["proof_verified"] is False


@pytest.mark.parametrize("damage", [
    "protocol", "plan_hash", "schema", "implementation", "status", "promotion", "training", "score",
    "source", "missing_sample", "duplicate_sample", "sample_order", "heartbeat", "cost_row", "seed",
    "runner", "mode", "cache", "counters", "budget", "commitment", "recommendation", "contexts",
    "missing_confirmation", "not_selected", "timeout", "target", "type", "request", "context_id", "exit",
])
def test_inconsistent_claims_are_not_reported_consistent(recorded, damage):
    protocol, report = recorded
    screen, confirm = report["screen"], report["confirmation"]
    if damage == "protocol":
        protocol["heartbeat_noise_floor_raw"] += 1
    elif damage == "plan_hash":
        report["plan"]["plan_id"] = "0" * 64
    elif damage == "schema":
        report["schema"] = "new-unsupported-schema"
    elif damage == "implementation":
        report["implementation_unchanged"] = False
    elif damage == "status":
        report["status"] = "BEST_SCORE_EVER"
    elif damage == "promotion":
        report["promoted"] = True
    elif damage == "training":
        report["training_enabled"] = True
    elif damage == "score":
        report["official_score"] = 99
    elif damage == "source":
        screen["arms"][1]["source"] += "\n"
    elif damage == "missing_sample":
        screen["samples"].pop()
    elif damage == "duplicate_sample":
        screen["samples"][1] = copy.deepcopy(screen["samples"][0])
    elif damage == "sample_order":
        screen["samples"].reverse()
    elif damage == "heartbeat":
        screen["samples"][0]["raw_heartbeats"] -= 1
    elif damage == "cost_row":
        report["screen_analysis"]["rows"]["control"]["tokens"] += 1
    elif damage == "seed":
        confirm["seed"] += 1
    elif damage == "runner":
        confirm["runner_sha256"] = "0" * 64
    elif damage == "mode":
        confirm["evidence_mode"] = "offline_fixture"
    elif damage == "cache":
        screen["receipt_cache_enabled"] = True
    elif damage == "counters":
        report["native_processes"] -= 1
    elif damage == "budget":
        report["max_calls"] = 0
    elif damage == "commitment":
        report["selection_commitment"] = "0" * 64
    elif damage == "recommendation":
        report["recommended"]["source"] += "\n"
    elif damage == "contexts":
        confirm["contexts"].pop()
    elif damage == "missing_confirmation":
        report["confirmation"] = None
    elif damage == "not_selected":
        report["selected_for_confirmation"] = None
    elif damage == "target":
        screen["samples"][0]["receipt"]["target"] = "easier_goal"
    elif damage == "type":
        screen["samples"][0]["receipt"]["type_preserved"] = False
    elif damage == "request":
        screen["samples"][0]["receipt"]["request_id"] = "0" * 64
    elif damage == "context_id":
        screen["samples"][0]["context_id"] = "0" * 64
    elif damage == "exit":
        screen["samples"][0]["receipt"]["exit_code"] = 1
    else:
        screen["samples"][0]["status"] = "TIMEOUT"
    result = audit.audit_report(protocol, report)
    assert result["status"] in {"INCONSISTENT", "MALFORMED"}, damage
    assert result["proof_verified"] is False and result["fresh_native_processes"] == 0


def test_incomplete_run_is_never_relabeled_as_a_success(recorded):
    protocol, report = recorded
    report.update(status="INCOMPLETE", reason="implementation_changed_during_selection",
                  implementation_unchanged=False, recommended=None)
    result = audit.audit_report(protocol, report)
    assert result["reported_selector_status"] == "INCOMPLETE"
    assert result["reason"] == "implementation_changed_during_selection"
    assert not result["checks"]["implementation_reported_unchanged"]


def test_legacy_policy_is_pareto_not_silently_strict_dual(recorded):
    _, report = recorded
    plan = report["plan"]
    plan.pop("selection_objective"); plan.pop("heartbeat_noise_floor_raw")
    plan["policy"] = "no-token-growth-and-separated-or-exact-heartbeats/v1"
    plan["plan_id"] = audit.content_hash({k: v for k, v in plan.items() if k != "plan_id"})
    for phase in ("screen", "confirmation"):
        report[phase + "_analysis"].pop("selection_objective")
        report[phase + "_analysis"].pop("heartbeat_noise_floor_raw")
    report["selection_commitment"] = audit.content_hash({"plan_id": plan["plan_id"],
        "screen_sha256": audit.content_hash(report["screen"]), "selected": report["recommended"]})
    result = audit.audit_report(copy.deepcopy(plan), report)
    assert result["status"] == "CONSISTENT", result
    assert result["legacy_policy_defaults_used"] is True and result["objective"] == "pareto-v1"
    assert result["proof_verified"] is False


@pytest.mark.parametrize("value", [None, [], {}, {"status": "INCOMPLETE"}])
def test_malformed_report_is_bounded_error(value):
    result = audit.audit_report({}, value)
    assert result["status"] == "MALFORMED" and result["errors"]
    assert result["proof_verified"] is False


@pytest.mark.parametrize("text", ['{"same":1,"same":2}', '{"cost":NaN}', '{"cost":Infinity}'])
def test_ambiguous_json_rejected(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        audit._read(path)


def test_cli_generates_reports_without_overwriting(recorded, tmp_path, monkeypatch, capsys):
    protocol, report = recorded
    p, r, output = tmp_path / "protocol.json", tmp_path / "report.json", tmp_path / "audit"
    p.write_text(json.dumps(protocol)); r.write_text(json.dumps(report))
    monkeypatch.setattr(sys, "argv", ["arena_report_audit", "--protocol", str(p), "--report", str(r),
                                     "--output-dir", str(output)])
    assert audit.main() == 0
    assert json.loads(capsys.readouterr().out)["fresh_native_processes"] == 0
    content = (output / "audit.json").read_bytes()
    assert (output / "summary.md").is_file()
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 2 and (output / "audit.json").read_bytes() == content


def test_input_size_limit(tmp_path, monkeypatch):
    path = tmp_path / "oversize.json"
    path.write_text('{"many":"bytes"}')
    monkeypatch.setattr(audit, "MAX_INPUT_BYTES", 4)
    with pytest.raises(ValueError, match="byte limit"):
        audit._read(path)
