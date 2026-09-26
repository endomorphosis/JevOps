"""Fixture-only legal admission plumbing; no real proof or storage authority."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from jevops import autoformal_tools as tools
from jevops.statement_lock import admission_ready, pattern_from_rule, render_lean, render_norm_batch


ROW = {"status": "roundtrip_ok", "clause_id": "fixture-clause", "rule": {
    "temporal": ["at_least_20"], "conditions": [], "rule_cid": "fixture-rule",
}}
SOURCE = render_lean(pattern_from_rule(ROW["rule"]))


@pytest.fixture
def boundary(monkeypatch):
    calls = {"checks": [], "stores": [], "marks": []}
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("no real Lean in this fixture"))

    def check(source):
        calls["checks"].append(source)
        return {"lake_ok": False, "error": "fixture_rejection"}

    def store(**kwargs):
        calls["stores"].append(kwargs)
        return {"indexed": True, "content_cid": "fixture-only", "repository": "fixture-repository"}

    monkeypatch.setattr(tools, "lake_check", check)
    monkeypatch.setattr(tools, "load_autoformal", lambda: SimpleNamespace(store_lake_attestation=store))
    monkeypatch.setattr(tools, "_store", lambda: SimpleNamespace(
        obligations=lambda *_: {"disposition": "pending", "pattern": pattern_from_rule(ROW["rule"])},
        mark=lambda *args: calls["marks"].append(args),
    ))
    return calls


@pytest.mark.parametrize("entry", ["roundtrip", "locked"])
@pytest.mark.parametrize("attack", [
    SOURCE.replace("decide (bound <= n)", "decide (n = bound)"),
    SOURCE.replace("theorem boundary", "theorem weaker"),
    SOURCE.replace("meets 20 = true", "meets 21 = true"),
    SOURCE + "#eval 1\n",
    "decide\n#eval 1",
    "decide +native",
    "import\tMathlib\n" + SOURCE,
    SOURCE + "def changed : Nat := 0\n",
])
def test_invalid_sources_reach_neither_checker_nor_attestation_store(boundary, entry, attack):
    if entry == "roundtrip":
        result = tools.admit_roundtrip_rule(ROW, attack)
        assert result["stored"] is False
    else:
        result = tools.admit_locked("fixture-document", "fixture-clause", attack)
        assert result["ok"] is False
        assert boundary["marks"][-1][2] == "failed"
    assert result["lake_ok"] is False
    assert boundary["checks"] == boundary["stores"] == []


@pytest.mark.parametrize("entry", ["roundtrip", "locked"])
def test_source_lock_does_not_override_failed_verification(boundary, entry):
    result = (tools.admit_roundtrip_rule(ROW, "decide") if entry == "roundtrip"
              else tools.admit_locked("fixture-document", "fixture-clause", "decide"))
    assert result["lake_ok"] is False and result["error"] == "fixture_rejection"
    assert len(boundary["checks"]) == 1 and boundary["stores"] == []
    assert result["source_lock"]["verification_performed"] is False
    assert result["source_lock"]["candidate_source_sha256"] == hashlib.sha256(boundary["checks"][0].encode()).hexdigest()


def test_mock_success_stores_the_exact_locked_bytes(boundary, monkeypatch):
    def check(source):
        boundary["checks"].append(source)
        return {"lake_ok": True, "error": ""}

    monkeypatch.setattr(tools, "lake_check", check)
    result = tools.admit_roundtrip_rule(ROW, SOURCE)
    assert result["stored"] and result["content_cid"] == "fixture-only"
    assert boundary["checks"] == [SOURCE]
    assert boundary["stores"][0]["lean"] == SOURCE
    assert result["source_lock"]["candidate_source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert result["source_lock"]["verification_performed"] is False


def test_a_norm_batch_keeps_each_lock_and_skips_thresholds() -> None:
    norms = [
        {"kind": "norm", "modality": 0, "fingerprint": 11},
        {"kind": "norm", "modality": 2, "fingerprint": 22},
    ]
    files = render_norm_batch(norms + [{"kind": "threshold", "fail": 19, "meet": 20}])
    assert len(files) == 1
    assert "def modalityCode0 : Nat := 0" in files[0]
    assert "def modalityCode1 : Nat := 2" in files[0]
    assert "bound :" not in files[0]
    assert '"' not in files[0]
    tiny = render_norm_batch(norms, max_bytes=120)
    assert len(tiny) == 2


def test_a_prohibition_cannot_supply_an_admission_target_from_its_fingerprint(boundary) -> None:
    rule = {"modality": "F", "actor": "Agency", "action": "disclose", "object": "records",
            "temporal": ["within 10 days"]}
    verdict = admission_ready(rule)
    assert verdict["ready"] is False and verdict["reason"] == "not_renderable"
    assert verdict["admitted"] is False and verdict["formalized"] is False
    assert pattern_from_rule(rule) is None
    assert render_lean(pattern_from_rule(rule)) == ""
    assert tools.admit_roundtrip_rule({**ROW, "rule": rule}, SOURCE)["error"] == "not_renderable"
    assert boundary["checks"] == boundary["stores"] == []


def test_a_minimum_is_ready_for_lake_and_a_deadline_is_not() -> None:
    minimum = admission_ready({"temporal_records": [{
        "temporal_kind": "minimum_duration",
        "quantity": 20,
        "value": "20 days",
    }]})
    assert minimum["ready"] is True
    assert minimum["pattern"] == "threshold"
    assert minimum["admitted"] is False
    assert minimum["formalized"] is False
    rule = {"modality": "O", "actor": "Company A", "action": "submit", "object": "backup report",
            "temporal": ["within_10_days"], "conditions": ["unless_emergency"],
            "temporal_records": [{"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"}]}
    assert pattern_from_rule(rule) is None
    deadline = admission_ready(rule)
    assert deadline["ready"] is False
    assert deadline["reason"] == "not_renderable"
    assert deadline["admitted"] is False


def test_deadlines_and_non_roundtrip_rows_still_abstain(boundary):
    row = {**ROW, "rule": {"temporal": ["within_10_days"]}}
    assert tools.admit_roundtrip_rule(row, SOURCE)["error"] == "not_renderable"
    assert tools.admit_roundtrip_rule({**ROW, "status": "abstain"}, SOURCE)["error"] == "not_roundtrip"
    assert boundary["checks"] == boundary["stores"] == []
