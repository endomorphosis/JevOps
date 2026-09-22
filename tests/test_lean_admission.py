from __future__ import annotations

from pathlib import Path
import json

import pytest

from jevops import lean


@pytest.mark.parametrize("receipt", [
    {}, {"exit_code": 1}, {"exit_code": -9}, {"exit_code": False},
    {"exit_code": 0, "timed_out": True}, {"exit_code": 0, "error": "missing_toolchain"},
])
def test_absence_of_json_errors_does_not_admit_a_failed_process(receipt: dict) -> None:
    result = lean.pack_compile_view(receipt, token_count=1, extra={"theorem_ok": True, "ok": True})
    assert not result["theorem_ok"] and not result["ok"]


def test_sorry_is_scoped_but_successful_process_is_still_required() -> None:
    receipt = {"exit_code": 0, "sorryAx": True}
    assert lean.pack_compile_view(receipt, token_count=1, sorry=False)["theorem_ok"]
    assert not lean.pack_compile_view(receipt, token_count=1, sorry=True)["theorem_ok"]
    assert not lean.pack_compile_view(receipt, token_count=1, errors=[{"message": "error"}])["theorem_ok"]


def keepbest_args(receipts: list[dict], *, source: str = "putnambench", tags: int = 2) -> dict:
    return dict(
        record={"name": "fixture", "source": source, "src": "original", "version_info": [{str(i): "sha"} for i in range(tags)]},
        tactics="trivial", putnam_source="putnambench", token_fn=lambda _: 1,
        closed_fn=lambda **kw: {"theorem_ok": False, **kw}, pins_fn=lambda r: r["version_info"],
        compile_fn=lambda _: receipts, parse_errors_fn=lambda _: [], sorry_fn=lambda *_: False,
        pack_fn=lean.pack_compile_view, elapsed_fn=lambda _: 1, now_fn=lambda: 0,
        patch_fn=lambda r, *_, **kw: r, statement_fn=lambda _: "statement",
        dest_fn=lambda _: Path("unused.lean"), restore=b"original", write_bytes_fn=lambda *_: None,
        candidate_source_fn=lambda *_: "candidate", splice_fn=lambda *_: None,
        span_fn=lambda *_: (1, 2), line_in_span_fn=lambda *_: True, extra_fn=lambda *_: {},
    )


@pytest.mark.parametrize("source", ["putnambench", "repo"])
@pytest.mark.parametrize("receipts,accepted", [
    ([], False), ([{"exit_code": 0}], False),
    ([{"exit_code": 0}, {"exit_code": 1}], False),
    ([{"exit_code": 0}, {"exit_code": 0, "timed_out": True}], False),
    ([{"exit_code": 0}, {"exit_code": 0}], True),
])
def test_every_expected_compile_receipt_must_pass(source: str, receipts: list[dict], accepted: bool) -> None:
    result = lean.compile_keepbest(**keepbest_args(receipts, source=source))
    assert result["theorem_ok"] is accepted
    assert result["all_tags_ok"] is accepted
    assert result["checked_tag_count"] == len(receipts)
    assert len(result["tag_results"]) == len(receipts)


@pytest.mark.parametrize("fail_at", ["splice", "compile"])
def test_compile_exception_restores_spliced_source(fail_at: str) -> None:
    content = [b"original"]
    args = keepbest_args([], source="repo", tags=1)
    args["write_bytes_fn"] = lambda _, data: content.__setitem__(0, data)

    def splice(*_: object) -> None:
        content[0] = b"candidate"
        if fail_at == "splice":
            raise RuntimeError("splice failed")

    def compile_one(_: object) -> None:
        assert content[0] == b"candidate"
        raise RuntimeError("compile failed")

    args.update(splice_fn=splice, compile_fn=compile_one)
    with pytest.raises(RuntimeError, match="failed"):
        lean.compile_keepbest(**args)
    assert content[0] == b"original"


@pytest.mark.parametrize("axioms,accepted", [("propext, Quot.sound", True), ("sorryAx", False), ("Lean.ofReduceBool", False)])
@pytest.mark.parametrize("source", ["putnambench", "repo"])
def test_strict_keepbest_audits_transitive_axioms_and_restores_source(tmp_path, axioms, accepted, source):
    path = tmp_path / "Fixture.lean"
    receipt = {"exit_code": 0, "stdout": json.dumps({"data": f"'fixture' depends on axioms: [{axioms}]"})}
    args = keepbest_args([receipt], source=source, tags=1)
    observed = []
    def compile_one(record):
        text = record["src"] if source == "putnambench" else path.read_text()
        observed.append(text)
        assert "#print axioms _root_.fixture" in text
        return [receipt]
    args.update(compile_fn=compile_one, audit_declaration="fixture", dest_fn=lambda _: path,
                write_bytes_fn=lambda p, data: p.write_bytes(data),
                splice_fn=lambda p, old, new: p.write_text(new))
    result = lean.compile_keepbest(**args)
    assert result["theorem_ok"] is accepted and result["kernel_audit"]["accepted"] is accepted
    if source == "repo":
        assert path.read_bytes() == b"original"


def test_strict_keepbest_does_not_accept_missing_audit_reports():
    args = keepbest_args([{"exit_code": 0, "stdout": ""}], tags=1)
    args["audit_declaration"] = "fixture"
    result = lean.compile_keepbest(**args)
    assert not result["theorem_ok"] and result["kernel_audit"]["missing_reports"] == ["fixture"]
