"""Numeric gates and Constitution inventory remain separate from admission."""
from __future__ import annotations

from jevops.statement_lock import admission_ready, pattern_from_rule


def _rules(text: str, span_id: str) -> list[dict]:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    session = AutoformalSession()
    compile_span(session, text, span_id, allow_partial=True)
    return [dict(row.rule) for row in session.rows if isinstance(getattr(row, "rule", None), dict)]


def test_the_twenty_day_gate_is_ready_and_not_admitted() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    session = AutoformalSession()
    compile_span(session, "The officer shall retain the file for at least 20 days.", "gate-minimum")
    rows = [row for row in session.rows if isinstance(getattr(row, "rule", None), dict)]
    assert rows
    assert any(row.status == "roundtrip_ok" for row in rows)
    ready = [admission_ready(dict(row.rule), status=str(row.status)) for row in rows]
    assert any(item["ready"] for item in ready)
    assert all(item["admitted"] is False and item["formalized"] is False for item in ready)


def test_a_within_deadline_is_not_a_minimum() -> None:
    rules = _rules(
        "Company A shall submit backup report within 10 days unless emergency.",
        "gate-within",
    )
    assert rules
    assert all(pattern_from_rule(rule) is None for rule in rules)
    ready = [admission_ready(rule) for rule in rules]
    assert all(item["ready"] is False and item["reason"] == "not_renderable" for item in ready)
    assert all(item["admitted"] is False and item["formalized"] is False for item in ready)
    bare = admission_ready({"temporal": ["within_10_days"], "conditions": []})
    assert bare["ready"] is False
    assert bare["reason"] == "not_renderable"


def test_constitution_census_never_promotes_compiler_observations_to_admission(monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal
    from ipfs_datasets_py.logic.autoformal.constitution_inventory import census_ledger, inventory_constitution

    def forbidden(*args, **kwargs):
        raise AssertionError("Constitution regression must not invoke the compiler or Lake")

    monkeypatch.setattr(autoformal, "compile_span", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    ledger = inventory_constitution(
        "We the People of the United States.\nArticle I\nSection 1\n"
        "All legislative Powers herein granted shall be vested in a Congress of the United States.\n"
    )
    expected = [span["text"] for span in ledger["spans"] if span["status"] == "uncompiled"]
    assert expected
    assert all(span["status"] != "roundtrip_ok" for span in ledger["spans"])
    calls = []

    def synthetic_compiler_observation(text):
        calls.append(text)
        # Positive diagnostic fields are deliberately insufficient authority.
        return {"compiler_status": "compiled", "roundtrip": True, "status": "roundtrip_ok",
                "formalized": True, "admitted": True, "decompiled": text,
                "rule": {"modality": "O", "actor": "Congress", "action": "exercise", "object": "powers"}}

    outcome = census_ledger(ledger, synthetic_compiler_observation)
    assert outcome["stopped"] is False and calls == expected
    assert outcome["ledger"] is ledger
    assert ledger["compiled"] is False and ledger.get("formalized", False) is False
    assert any(span["status"] == "compiled" and span["roundtrip"] is True for span in ledger["spans"])
    for span in ledger["spans"]:
        assert span["status"] not in {"roundtrip_ok", "formalized", "admitted"}
        assert span.get("formalized", False) is False and span.get("admitted", False) is False
        verdict = admission_ready(span.get("rule"), status=span["status"])
        assert verdict["ready"] is False
        assert verdict["admitted"] is False and verdict["formalized"] is False
