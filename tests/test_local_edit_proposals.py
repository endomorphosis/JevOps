"""Offline edit checks; an allowed deletion is never itself a Lean proof."""
import json

import pytest

from jevops.arena import source_hash
from jevops.proof_slicing import apply_deletion_span, deletion_spans
from tests.test_prompt_template_pilot import pilot

STATEMENT = "theorem EditFixture (h : True) : True"
BODY = "  have unused : True := by\n    trivial\n  exact h\n"
SOURCE = STATEMENT + " := by\n" + BODY


def test_deletions_reuse_slicer_and_preserve_every_untouched_byte():
    spans = deletion_spans(SOURCE, STATEMENT)
    assert (1, 2) in spans and 0 < len(spans) <= 64
    assert apply_deletion_span(SOURCE, STATEMENT, 1, 2, expected_source_sha256=source_hash(SOURCE)) == (
        STATEMENT + " := by\n  exact h\n")
    lines = BODY.splitlines(keepends=True)
    for start, end in spans:
        result = apply_deletion_span(SOURCE, STATEMENT, start, end, expected_source_sha256=source_hash(SOURCE))
        assert result == STATEMENT + " := by\n" + "".join(lines[:start - 1] + lines[end:])


@pytest.mark.parametrize("start,end", [(0, 1), (1, 99), (2, 1), (True, 2), (1, 2.0), (1, 3)])
def test_undeclared_or_malformed_spans_fail(start, end):
    with pytest.raises(ValueError):
        apply_deletion_span(SOURCE, STATEMENT, start, end, expected_source_sha256=source_hash(SOURCE))


def test_stale_source_and_unsupported_envelope_fail():
    with pytest.raises(ValueError, match="source identity"):
        apply_deletion_span(SOURCE + "\n", STATEMENT, 1, 2, expected_source_sha256=source_hash(SOURCE))
    with pytest.raises(ValueError):
        deletion_spans(SOURCE.replace(STATEMENT, "theorem Other : True"), STATEMENT)
    assert deletion_spans(SOURCE.replace("  exact h", "  -- opaque\n  exact h"), STATEMENT) == ()


def test_plan_matches_contexts_and_allows_only_declared_spans(pilot):
    plan = pilot.make_local_edit_plan()
    assert plan == pilot.make_local_edit_plan()
    assert [s["slot"] for s in plan["schedule"]] == list(range(8))
    assert plan["max_output_tokens_total"] == 8192
    assert len(plan["allowed_delete_lines_inclusive"]) <= 64
    for repetition in range(4):
        body, edit = [plan["arms"][name]["requests"][repetition] for name in ("whole-body", "delete-span")]
        assert body["request_id"] == edit["request_id"] and body["messages"][1] == edit["messages"][1]
        assert body["messages"][0]["content"].rsplit("\n", 1)[0] == edit["messages"][0]["content"].rsplit("\n", 1)[0]
        assert "No tactic text" in edit["messages"][0]["content"]


@pytest.mark.parametrize("extra", [{"theorem_ok": True}, {"source": "sorry"}, {"confidence": 1}])
def test_forged_admission_or_generated_strings_rejected(pilot, extra):
    row = pilot.parse_deletion(json.dumps({"request_id": "id", "delete_lines": [1, 2], **extra}),
                               "id", "stop", {"statement": STATEMENT, "src": SOURCE})
    assert row["status"] == "contract_mismatch" and "source" not in row


def test_parser_binding_truncation_eos_and_edit_identity(pilot):
    record = {"statement": STATEMENT, "src": SOURCE}
    raw = json.dumps({"request_id": "id", "delete_lines": [1, 2]})
    good = pilot.parse_deletion(raw, "id", "stop", record)
    assert good["status"] == "parsed" and good["strict_contract"]
    assert good["source"].endswith("  exact h\n")
    assert pilot.parse_deletion(raw + "<|im_end|>", "id", "stop", record)["status"] == "eos_artifact"
    assert pilot.parse_deletion(raw, "id", "length", record)["status"] == "output_truncated"
    assert pilot.parse_deletion(raw, "other", "stop", record)["status"] == "contract_mismatch"
    assert pilot.parse_deletion(raw.replace("[1, 2]", "[1, 999]"), "id", "stop", record)["status"] == "edit_rejected"


def test_transport_constructs_edit_without_model_lean_text(pilot, monkeypatch):
    plan = pilot.make_local_edit_plan()
    arm = plan["arms"]["delete-span"]
    request = arm["requests"][0]
    span = plan["allowed_delete_lines_inclusive"][0]
    monkeypatch.setattr(pilot.llm_router, "generate_text", lambda *a, **kw:
        json.dumps({"request_id": request["request_id"], "delete_lines": span}))
    monkeypatch.setattr(pilot.llm_router, "get_last_generation_trace", lambda: {
        "fixture": False, "fallback_used": False, "response_model": "leanstral_local",
        "endpoint": pilot.leanstral.endpoint(pilot.leanstral.BASE_URL), "finish_reason": "stop"})
    row = pilot.generation_row({}, request["messages"], plan["record"], plan["settings"],
        pilot.Arm(**arm["arm"]), request["request_id"], "delete-span")
    assert row["status"] == "parsed" and row["native_verified"] is None
    assert row["source"] == apply_deletion_span(plan["record"]["src"], plan["record"]["statement"], *span,
                                               expected_source_sha256=source_hash(plan["record"]["src"]))
