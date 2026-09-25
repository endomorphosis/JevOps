"""Offline layout regressions; these do not establish native Lean validity."""
import json

import pytest

from jevops.lean import extract_generated_tactics, trim_tactic_body
from jevops.leanstral_prompt_lab import Arm, parse_response
from jevops.outer import join_decl


BODY = "  constructor\n  · exact True.intro\n  · exact True.intro"


@pytest.mark.parametrize("envelope", ["{}", "\n  \n{}\n \n", "```lean\n{}\n```",
    "```\n{}\n```<|im_end|>", ":= by\n{}", " := by \n{}"])
def test_extractor_preserves_multiline_layout(envelope):
    assert extract_generated_tactics(envelope.format(BODY)) == BODY
    assert join_decl("theorem layout : True ∧ True", extract_generated_tactics(envelope.format(BODY))) == (
        "theorem layout : True ∧ True := by\n" + BODY)


@pytest.mark.parametrize("body", [BODY, BODY.replace("\n", "\r\n"),
    "intro h\nexact h", "  intro h\n  have g := by\n    exact h\n  exact g"])
@pytest.mark.parametrize("contract", ["tactic", "json"])
def test_strict_parser_preserves_plain_and_json_body(body, contract):
    raw = body if contract == "tactic" else json.dumps({"request_id": "id", "tactic": body})
    for suffix in ("", "<|im_end|>"):
        row = parse_response(raw + suffix, Arm("test", contract=contract), "id", "stop")
        assert row["tactic"] == body
        assert row["strict_contract"] == (not suffix)


def test_single_line_compatibility_and_no_syntax_repairs():
    assert extract_generated_tactics("```lean\n  simp\n```") == "simp"
    assert trim_tactic_body(" \n \n") == ""
    malformed = "intro h\n  exact h"
    assert trim_tactic_body(malformed) == malformed
    assert extract_generated_tactics("```") == ""
    assert extract_generated_tactics(None) == ""


@pytest.mark.parametrize("raw", ["by\n  trivial", "by\ttrivial", "by trivial"])
def test_strict_parser_rejects_by_envelope(raw):
    assert parse_response(raw, Arm("test"), "id", "stop")["tactic"] is None


def test_frozen_core_fence_roundtrip():
    from jevops.arena_lean import CORPUS
    record = next(r for line in CORPUS.read_text().splitlines()
                  if (r := json.loads(line))["name"] == "Core.InitsUpdatesComm")
    body = record["src"].split(" := by\n", 1)[1]
    recovered = extract_generated_tactics("```lean\n" + body + "\n```")
    assert join_decl(record["statement"], recovered) == record["src"].rstrip("\r\n")
