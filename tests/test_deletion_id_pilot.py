"""Offline source-bound choice IDs are edit instructions, never proof receipts."""
from collections import Counter
import json
from pathlib import Path
import re

import pytest

from tests.test_prompt_template_pilot import pilot
from tests.test_deletion_order_pilot import unpack
from tests.test_local_edit_proposals import SOURCE, STATEMENT


def test_id_plan_matches_contexts_actions_and_stable_ids(pilot):
    plan = pilot.make_deletion_id_plan()
    assert plan == pilot.make_deletion_id_plan()
    assert [s["slot"] for s in plan["schedule"]] == list(range(8))
    assert Counter(s["arm"] for s in plan["schedule"]) == {name: 2 for name in plan["arms"]}
    assert plan["max_model_calls"] == 8 and plan["max_output_tokens_total"] == 8192
    catalog = plan["edit_catalog"]
    assert plan["catalog_sha256"] == pilot.content_hash(catalog)
    assert catalog["record_sha256"] == pilot.content_hash(plan["record"])
    assert catalog["source_sha256"] == pilot.source_hash(plan["record"]["src"])
    assert [e["edit_id"] for e in catalog["entries"]] == list(range(1, 65))
    assert [tuple(e["delete_lines"]) for e in catalog["entries"]] == list(plan["allowed_delete_lines_inclusive"])
    for repetition in range(2):
        requests = [arm["requests"][repetition] for arm in plan["arms"].values()]
        assert len({r["request_id"] for r in requests}) == 1
        assert len({r["messages"][0]["content"] for r in requests}) == 1
        for order in ("forward", "reverse"):
            endpoint, ids = [plan["arms"][name + "-" + order]["requests"][repetition] for name in ("endpoints", "ids")]
            assert endpoint["messages"][1]["content"].split("</context>")[0] == ids["messages"][1]["content"].split("</context>")[0]
            _, _, _, data, tail = unpack(ids)
            expected = catalog["entries"] if order == "forward" else list(reversed(catalog["entries"]))
            assert data["edit_catalog"]["entries"] == expected
            assert "Set edit_id to the integer" in tail
            assert tail.count("Return ONLY") == 1
    assert plan["analysis_protocol"]["grammar_constrained_decoding"] is False


def parse(pilot, payload, *, record=None, digest=None, request_id="current", finish="stop"):
    record = record or {"statement": STATEMENT, "src": SOURCE}
    digest = digest if digest is not None else pilot.content_hash(pilot.deletion_catalog(record))
    return pilot.parse_deletion(json.dumps(payload), request_id, finish, record,
                                action="delete-id", expected_catalog_sha256=digest)


def test_every_id_resolves_to_exact_same_source_as_endpoints(pilot):
    plan = pilot.make_deletion_id_plan()
    for entry in plan["edit_catalog"]["entries"]:
        by_id = parse(pilot, {"request_id": "current", "edit_id": entry["edit_id"]},
                      record=plan["record"], digest=plan["catalog_sha256"])
        by_span = pilot.parse_deletion(json.dumps({"request_id": "current", "delete_lines": entry["delete_lines"]}),
                                      "current", "stop", plan["record"])
        assert by_id["status"] == by_span["status"] == "parsed"
        assert by_id["source"] == by_span["source"]
        assert by_id["resolved_delete_lines"] == entry["delete_lines"]
        assert by_id["edit"] == {"request_id": "current", "edit_id": entry["edit_id"]}


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, [1], {"edit_id": 1}])
def test_noninteger_ids_are_contract_mismatches(pilot, value):
    row = parse(pilot, {"request_id": "current", "edit_id": value})
    assert row["status"] == "contract_mismatch" and "source" not in row


@pytest.mark.parametrize("value", [0, -1, 65, 1000000])
def test_undeclared_integer_ids_are_rejected_not_clamped(pilot, value):
    row = parse(pilot, {"request_id": "current", "edit_id": value})
    assert row["status"] == "edit_rejected" and row["strict_contract"] and "source" not in row


@pytest.mark.parametrize("extra", [{"delete_lines": [1, 2]}, {"theorem_ok": True}, {"source": "sorry"}])
def test_model_cannot_override_catalog_mapping(pilot, extra):
    row = parse(pilot, {"request_id": "current", "edit_id": 1, **extra})
    assert row["status"] == "contract_mismatch" and "source" not in row


def test_id_request_catalog_and_entire_record_binding(pilot):
    payload = {"request_id": "current", "edit_id": 1}
    original = {"statement": STATEMENT, "src": SOURCE}
    digest = pilot.content_hash(pilot.deletion_catalog(original))
    for modified in ({**original, "src": SOURCE + "\n"}, {**original, "header": "changed dependencies"}):
        row = parse(pilot, payload, record=modified, digest=digest)
        assert row["status"] == "edit_rejected" and "catalog identity" in row["edit_error"]
        assert "source" not in row
    assert parse(pilot, payload, request_id="foreign")["status"] == "contract_mismatch"
    assert parse(pilot, payload, finish="length")["status"] == "output_truncated"
    missing = pilot.parse_deletion(json.dumps(payload), "current", "stop", original, action="delete-id")
    assert missing["status"] == "edit_rejected" and "source" not in missing


def test_id_eos_fences_and_duplicate_fields(pilot):
    record = {"statement": STATEMENT, "src": SOURCE}
    digest = pilot.content_hash(pilot.deletion_catalog(record))
    raw = '{"request_id":"current","edit_id":1}'
    for text, status in ((raw + "<|im_end|>", "eos_artifact"), ("```json\n" + raw + "\n```", "contract_mismatch"),
                         ('{"request_id":"current","edit_id":1,"edit_id":2}', "contract_mismatch")):
        row = pilot.parse_deletion(text, "current", "stop", record, action="delete-id", expected_catalog_sha256=digest)
        assert row["status"] == status and not row["strict_contract"]


def test_old_order_requests_are_unchanged(pilot):
    path = Path(pilot.ROOT) / "papers/completion/lean_refactor_arena/evidence/prompt-deletion-order-2026-09-23/plan.json"
    old, current = json.loads(path.read_text()), pilot.make_deletion_order_plan()
    for name in old["arms"]:
        assert old["arms"][name]["requests"] == current["arms"][name]["requests"]


def test_both_contracts_reach_checker_and_resume_never_retries(pilot, monkeypatch, tmp_path):
    plan = pilot.make_deletion_id_plan()
    monkeypatch.setattr(pilot, "validate_volume", lambda _: tmp_path)
    monkeypatch.setattr(pilot.leanstral, "server_profile", lambda: {"declared_context_per_slot": 8192})
    monkeypatch.setattr(pilot.leanstral, "health_status", lambda _: (200, ""))
    calls = []
    def generate(prompt, **kwargs):
        assert prompt is None
        user = kwargs["messages"][1]["content"]
        calls.append(user)
        request_id = re.search(r"Request: ([0-9a-f]{16})", user)[1]
        choice = {"edit_id": 1} if "Set edit_id to the integer" in user else {"delete_lines": plan["edit_catalog"]["entries"][0]["delete_lines"]}
        return json.dumps({"request_id": request_id, **choice})
    monkeypatch.setattr(pilot.llm_router, "generate_text", generate)
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": "stop"})
    pilot.run(tmp_path, {}, plan)
    pilot.run(tmp_path, {}, plan)
    report = json.loads((tmp_path / "generation.json").read_text())
    assert len(calls) == report["requests_reserved"] == 8 and report["native_executions"] == 0
    assert len(report["candidate_files"]) == 1
    assert all(r["status"] == "parsed" and r["native_verified"] is None for r in report["rows"])
    assert sum("resolved_delete_lines" in r for r in report["rows"]) == 4
