"""Closed autoformalization tools. No live model and no lake download."""
from __future__ import annotations

import pytest

from jevops import autoformal_tools, leanstral


def test_lake_check_refuses_an_import_before_lake(monkeypatch) -> None:
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("lake"))
    result = autoformal_tools.lake_check("import Mathlib\ndef a : Nat := 1\n")
    assert result == {"lake_ok": False, "error": "imports_refused"}


def test_extract_lean_on_english_names_lake_check_without_echoing_it() -> None:
    statute = "No Person shall be a Representative who shall not have attained to the Age of twenty five Years."
    result = autoformal_tools.dispatch("extract_lean", {"text": statute})
    assert result["chars"] == 0
    assert "lake_check" in result["error"]
    assert '{"source":"<lean>"}' in result["error"]
    assert "Representative" not in result["error"]


def test_unknown_tool_is_not_dispatched() -> None:
    assert autoformal_tools.dispatch("shell", {})["error"] == "unknown_tool"


def test_text_tool_turn_parses_and_an_empty_list_is_no_call() -> None:
    assert leanstral._normalize_tool_calls({}, "<|im_start|>tool_calls\n[]") == []
    calls = leanstral._normalize_tool_calls(
        {},
        '<|im_start|>tool_calls\n[{"name":"lake_check","arguments":{"source":"def a : Nat := 1"}}]',
    )
    assert calls[0]["name"] == "lake_check"
    assert calls[0]["arguments"]["source"].startswith("def a")
    assert "lake_check" in {item["function"]["name"] for item in autoformal_tools.TOOLS}
    assert "extract_lean" in {item["function"]["name"] for item in autoformal_tools.TOOLS}
    assert "compile_clause" in {item["function"]["name"] for item in autoformal_tools.TOOLS}
    mistral = (
        '<|tool_call_begin|>function=extract_lean<|tool_call_arg_begin|>'
        'source = "age of twenty five"<|tool_call_arg_end|>'
    )
    parsed = leanstral._normalize_tool_calls({}, mistral)
    assert parsed[0]["name"] == "extract_lean"
    assert parsed[0]["arguments"]["source"] == "age of twenty five"
