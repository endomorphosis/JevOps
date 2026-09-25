"""Lean lock stays here. Legal compilation is delegated and is not an admit."""
from __future__ import annotations

import pytest

from jevops import autoformal_tools
from jevops.leanstral import _tools_ok
from jevops.statement_lock import load_autoformal, lock_statement


LEASE = (
    "The tenant shall pay one hundred dollars. "
    "When payment is after the fifth day, the tenant shall pay an additional ten dollars."
)
AGE = (
    "No person shall be eligible who shall not have attained the age of thirty five years "
    "and been fourteen years a resident."
)
PREAMBLE = "We the People, in Order to form a more perfect Union, do ordain and establish this charter."
SOURCE = "def bound : Nat := 2\ntheorem boundary : bound = 2 := by\n  decide\n"


def test_tools_delegate_the_legal_names_and_stay_within_the_server_limit() -> None:
    names = {item["function"]["name"] for item in autoformal_tools.TOOLS}
    assert {"lake_check", "extract_lean", "clause_get", "compile_clause", "decompile_rule", "rules_for_frame", "coverage"} <= names
    assert "deontic_analyze" not in names
    assert len(autoformal_tools.TOOLS) <= 8
    assert _tools_ok(autoformal_tools.TOOLS)


def test_compile_clause_is_the_same_tool_for_two_documents() -> None:
    autoformal = load_autoformal()
    autoformal.reset_session()
    session = autoformal.SESSION
    lease = session.open_document(LEASE, document_type="contract", document_id="lease")
    age = session.open_document(AGE, document_type="statute", document_id="age")
    preamble = session.open_document(PREAMBLE, document_id="preamble")
    lease_id = lease["clauses"][0]["id"]
    age_id = age["clauses"][0]["id"]
    preamble_id = preamble["clauses"][0]["id"]
    autoformal_tools.dispatch("compile_clause", {"document_id": "lease", "clause_id": lease_id, "frame_id": "fee"})
    autoformal_tools.dispatch("compile_clause", {"document_id": "age", "clause_id": age_id, "frame_id": "fee"})
    opened = autoformal_tools.dispatch("compile_clause", {"document_id": "preamble", "clause_id": preamble_id})
    assert lease_id in session.compiled_ids and age_id in session.compiled_ids
    assert opened["rows"][0]["status"] == "abstain"
    assert opened["rows"][0]["admitted"] is False
    framed = autoformal_tools.dispatch("rules_for_frame", {"frame_id": "fee"})
    assert {row["clause_id"] for row in framed["rows"]} >= {lease_id, age_id}


def test_a_repeal_edge_is_not_compiled() -> None:
    autoformal = load_autoformal()
    autoformal.reset_session()
    text = "A person shall wait at least ten days.\n\nThe later rule shall wait at least twenty days."
    opened = autoformal.SESSION.open_document(text, document_id="repeal", edges=[{"kind": "repeal", "source": "1", "target": "0"}])
    coverage = autoformal.SESSION.fill("repeal")
    first = opened["clauses"][0]["id"]
    assert first not in autoformal.SESSION.compiled_ids
    assert coverage["counts"]["inactive"] == 1


def test_the_workspace_parser_is_the_one_that_imports() -> None:
    import ipfs_datasets_py.logic.deontic.utils.deontic_parser as parser

    assert "external/ipfs_datasets" in parser.__file__
    assert any(kind == "minimum_duration" for _typ, kind, _pat in parser._TEMPORAL_PATTERNS)


def test_one_neighbor_objective_is_a_conflict_and_not_a_proof() -> None:
    import json
    memory: dict = {}
    cited = [
        {"subject": "anchor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "unrelated", "predicate": "citation", "object": "12 U.S.C. 1"},
    ]
    scope = {
        "jurisdiction": "US-OR",
        "as_of": "2024-06-15",
        "territory": "Multnomah",
        "subject_matter": "public-records",
        "actor": "agency",
        "subject": "requester",
        "resource": "records",
        "purpose": "disclosure",
        "authority_id": "auth:or-legislature",
        "enacted_date": "2019-01-01",
        "effective_from": "2020-01-01",
        "source_ref": "source:or-192",
        "provenance_id": "prov:or-192",
    }
    outcome = autoformal_tools.run_neighbor_objective(
        anchor_text="Company A shall submit backup report within 10 days unless emergency.",
        neighbor_text="Company A shall not submit backup report within 10 days unless emergency.",
        triples=cited,
        anchor_id="anchor",
        neighbor_id="neighbor",
        scope=scope,
        memory=memory,
    )
    receipt = outcome["receipt"]
    assert outcome["anchor_status"] == "roundtrip_ok"
    assert receipt["label"] == "contradiction"
    assert receipt["margin"] == 100
    assert receipt["content_cid"] == ""
    assert receipt["proved"] is False
    assert receipt["completion_authoritative"] is False
    assert outcome["admitted"] is False
    stored = json.dumps(memory)
    assert "contrastive_m" in stored
    assert "must not submit" not in stored
    assert "def " not in stored


def test_a_conflict_receipt_records_a_margin_without_a_proof_index() -> None:
    import json
    memory: dict = {}
    receipt = autoformal_tools.record_formalization(memory, {
        "anchor_decompiled": "Company A must submit backup report 10 days unless emergency.",
        "neighbor_decompiled": "Company A must not submit backup report 10 days unless emergency.",
        "receipt": {
            "clause_id": "neighbor-c0",
            "label": "contradiction",
            "margin": 100,
            "content_cid": "",
            "proved": False,
        },
    })
    assert receipt["label"] == "contradiction"
    assert receipt["proved"] is False
    assert receipt["writes_lean"] is False
    assert receipt["content_cid"] == ""
    stored = json.dumps(memory)
    assert "contrastive_m" in stored
    assert "must not submit" not in stored
    assert "def " not in stored


def test_pair_margin_lands_on_the_nca_cell_and_does_not_write_lean() -> None:
    import json
    memory: dict = {}
    receipt = autoformal_tools.record_pair_margin(
        memory,
        clause_id="neighbor-c0",
        label="conflict",
        margin=100,
        positive="Agency must disclose records.",
        negative="Agency must not disclose records.",
    )
    assert receipt["writes_lean"] is False
    assert receipt["admitted"] is False
    assert receipt["proved"] is False
    assert receipt["content_cid"] == ""
    assert receipt["label"] == "conflict"
    assert receipt["margin"] == 100
    assert memory["nca"]["autoencoder"]["contrastive_m"] == receipt["contrastive_m"]
    stored = json.dumps(memory)
    assert "def " not in stored
    assert "Agency must disclose" not in stored
    proved = autoformal_tools.record_pair_margin(
        memory,
        clause_id="neighbor-c0",
        label="positive",
        margin=0,
        positive="Agency must disclose records.",
        negative="Agency must disclose records.",
        content_cid="bafy-test",
    )
    assert proved["proved"] is True
    assert proved["completion_authoritative"] is False
    assert "bafy-test" not in json.dumps(memory["nca"]["autoencoder"])


def test_a_minimum_duration_with_its_quantity_is_lake_checked() -> None:
    import json
    autoformal = load_autoformal()
    autoformal.reset_session()
    within = {
        "temporal": ["10 days"],
        "temporal_records": [{"temporal_kind": "within_duration", "value": "10 days", "quantity": 10}],
    }
    assert autoformal_tools.pattern_from_rule(within) is None
    text = "A person shall wait at least 20 days."
    opened = autoformal.SESSION.open_document(text, document_id="wait")
    clause_id = opened["clauses"][0]["id"]
    row = autoformal.SESSION.compile_clause("wait", clause_id)["rows"][0]
    pattern = autoformal_tools.pattern_from_rule(row["rule"])
    assert pattern == {"kind": "threshold", "fail": 19, "meet": 20}
    autoformal.SESSION.roundtrip_clause("wait", clause_id)
    row = autoformal.SESSION.decompile_rule("wait", clause_id)["rows"][0]
    assert row["status"] == "roundtrip_ok"
    source = autoformal_tools.render_lean(pattern)
    memory: dict = {}
    result = autoformal_tools.admit_roundtrip_rule(row, source, memory=memory)
    assert result["lake_ok"] is True, result
    assert result["stored"] is True
    body = result["repository"].blob_store.get_bytes(result["content_cid"])
    assert json.loads(body)["lean"] == source
    assert result["repository"].get_index_record(result["content_cid"]).content_cid == result["content_cid"]
    assert "def bound" not in json.dumps(memory)
    house = "No Person shall be a Representative who shall not have attained to the Age of twenty five Years, and been seven Years a Citizen of the United States."
    opened = autoformal.SESSION.open_document(house, document_id="house")
    house_row = autoformal.SESSION.compile_clause("house", opened["clauses"][0]["id"])["rows"][0]
    assert house_row["status"] == "abstain"
    refused = autoformal_tools.admit_roundtrip_rule(house_row, source)
    assert refused["error"] == "not_roundtrip"
    assert refused["stored"] is False


def test_a_deadline_rule_is_not_rendered_or_stored(monkeypatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("lake"))
    row = {
        "status": "roundtrip_ok",
        "clause_id": "backup-c0",
        "rule": {"temporal": ["within_10_days"], "conditions": [], "rule_cid": "rule-backup"},
    }
    result = autoformal_tools.admit_roundtrip_rule(row, "decide")
    assert result["error"] == "not_renderable"
    assert result["stored"] is False


def test_a_minimum_rule_is_stored_only_when_the_statement_matches() -> None:
    import json
    row = {
        "status": "roundtrip_ok",
        "clause_id": "wait-c0",
        "rule": {
            "temporal": ["at_least_20"],
            "conditions": [],
            "rule_cid": "rule-wait",
        },
    }
    source = autoformal_tools.render_lean(autoformal_tools.pattern_from_rule(row["rule"]))
    memory: dict = {}
    changed = autoformal_tools.admit_roundtrip_rule(
        row, source.replace("meets 20 = true", "meets 21 = true", 1), memory=memory,
    )
    assert changed["error"] == "statement_changed"
    assert changed["stored"] is False
    assert "def bound" not in json.dumps(memory)
    admitted = autoformal_tools.admit_roundtrip_rule(row, source, memory=memory)
    assert admitted["lake_ok"] is True, admitted
    assert admitted["stored"] is True
    repo = admitted["repository"]
    body = repo.blob_store.get_bytes(admitted["content_cid"])
    assert body is not None
    assert json.loads(body)["lean"] == source
    assert repo.get_index_record(admitted["content_cid"]).content_cid == admitted["content_cid"]
    assert "def bound" not in json.dumps(memory)
    assert "wait-c0" in json.dumps(memory)


def test_import_and_a_changed_numeral_never_reach_lake(monkeypatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("lake"))
    changed = lock_statement(SOURCE, SOURCE.replace("bound = 2", "bound = 3", 1))
    assert changed["error"] == "statement_changed"
    refused = lock_statement(SOURCE, "import Mathlib\n" + SOURCE)
    assert refused["error"] == "imports_refused"
    assert autoformal_tools.lake_check("import Mathlib\ndef a : Nat := 1\n")["error"] == "imports_refused"
