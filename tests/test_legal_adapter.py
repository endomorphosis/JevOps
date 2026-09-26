"""Offline adapter-boundary fixtures, not Lean/compiler qualification."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path

import pytest

from jevops import autoformal_tools as tools, leanstral
from jevops import legal_adapter as api
from jevops.statement_lock import pattern_from_rule, render_lean


ROW = {"status": "roundtrip_ok", "clause_id": "same-clause", "rule": {
    "temporal": ["at_least_20"], "conditions": [], "rule_cid": "fixture-rule",
}}
PATTERN = pattern_from_rule(ROW["rule"])
SOURCE = render_lean(PATTERN)


class FixtureDocuments:
    def __init__(self):
        self.marks = []

    def obligations(self, document_id, clause_id):
        return {"disposition": "pending", "pattern": dict(PATTERN)}

    def mark(self, *args):
        self.marks.append(args)


class FixtureSession:
    def __init__(self, label):
        self.label = label
        self.documents = FixtureDocuments()
        self.rows = []

    def open_document(self, text, **kwargs):
        return {"fixture": self.label, "text": text, **kwargs}

    def clause_get(self, document_id, clause_id):
        return {"fixture": self.label, "document_id": document_id, "clause_id": clause_id}

    def compile_clause(self, document_id, clause_id, *, frame_id):
        row = {"fixture": self.label, "document_id": document_id, "clause_id": clause_id,
               "frame_id": frame_id, "status": "fixture_only"}
        self.rows.append(row)
        return row

    def decompile_rule(self, document_id, clause_id):
        return {"fixture": self.label, "text": "fixture-only text"}

    def rules_for_frame(self, frame_id):
        return {"rows": [dict(row) for row in self.rows if row["frame_id"] == frame_id]}

    def coverage(self, document_id):
        return {"fixture": self.label, "compiled": sum(r["document_id"] == document_id for r in self.rows)}


@pytest.fixture(autouse=True)
def no_ambient_or_live_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("no ambient imports, real Lean, global store or model calls allowed")

    for name in ("load_autoformal", "_store", "lake_check"):
        monkeypatch.setattr(tools, name, forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr(leanstral, "chat_completion", forbidden)


@pytest.fixture
def fixture_backend(tmp_path):
    def make(label="fixture", **overrides):
        root = tmp_path / label
        root.mkdir()
        (root / "backend.txt").write_text("declared fixture artifact\n")
        manifest = api.SourceManifest.capture(root, ("backend.txt",), implementation_id="fixture/legal-v1")
        session = FixtureSession(label)
        calls = {"checks": [], "stores": []}

        def check(source):
            calls["checks"].append(source)
            return {"lake_ok": True, "error": "", "kind": "fixture"}

        def store(**kwargs):
            calls["stores"].append(kwargs)
            return {"indexed": True, "content_cid": "fixture-not-a-proof", "repository": kwargs["repository"]}

        kwargs = dict(root=root, manifest=manifest, expected_sha256=manifest.content_sha256,
                      session=session, documents=session.documents, verifier=check,
                      attestation_writer=store,
                      prompt_builder=lambda text: [{"role": "developer", "content": "fixture"},
                                                   {"role": "user", "content": text}])
        kwargs.update(overrides)
        return api.PinnedLegalAdapter(**kwargs), session, calls, kwargs

    return make


def test_manifest_roundtrip_is_order_and_location_independent(tmp_path):
    root = tmp_path / "one"
    root.mkdir()
    (root / "a").write_bytes(b"a")
    (root / "b").write_bytes(b"")
    manifest = api.SourceManifest.capture(root, ("b", "a"), implementation_id="fixture/v1")
    restored = api.SourceManifest.from_dict(json.loads(json.dumps(manifest.as_dict())))
    assert restored == manifest
    assert restored.files[0].sha256 == hashlib.sha256(b"a").hexdigest()
    copy = tmp_path / "two"
    copy.mkdir()
    (copy / "a").write_bytes(b"a")
    (copy / "b").write_bytes(b"")
    assert restored == api.SourceManifest.capture(copy, ("a", "b"), implementation_id="fixture/v1")
    restored.verify(copy)
    with pytest.raises(FrozenInstanceError):
        restored.implementation_id = "changed"


@pytest.mark.parametrize("path", ["../outside", "/absolute", "a/../b", "./a", "a//b", "a/", "a\\b", "", ".", "a\x00"])
def test_manifest_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        api.FileDigest(path, 0, "0" * 64)


@pytest.mark.parametrize("change", [
    {"schema": "v0"}, {"unexpected": 1}, {"files": []}, {"files": [None]},
    {"files": [{"path": "a", "size": True, "sha256": "0" * 64}]},
    {"files": [{"path": "a", "size": float("nan"), "sha256": "0" * 64}]},
    {"files": [{"path": "a", "size": -1, "sha256": "0" * 64}]},
    {"files": [{"path": "a", "size": 0, "sha256": "not-a-content-hash"}]},
])
def test_manifest_rejects_malformed_records(change):
    value = api.SourceManifest("fixture", (api.FileDigest("a", 0, "0" * 64),)).as_dict()
    with pytest.raises(ValueError):
        api.SourceManifest.from_dict({**value, **change})


def test_manifest_rejects_duplicate_and_excess_records(tmp_path, monkeypatch):
    row = api.FileDigest("a", 0, "0" * 64)
    with pytest.raises(ValueError):
        api.SourceManifest("fixture", (row, row))
    with pytest.raises(ValueError):
        api.SourceManifest.capture(tmp_path, ("a", "a"), implementation_id="fixture")
    monkeypatch.setattr(api, "MAX_FILES", 1)
    with pytest.raises(ValueError):
        api.SourceManifest("fixture", (row, api.FileDigest("b", 0, "0" * 64)))


def test_byte_limits_include_zero_and_exact_boundary(tmp_path, monkeypatch):
    (tmp_path / "a").write_bytes(b"abc")
    (tmp_path / "b").write_bytes(b"de")
    monkeypatch.setattr(api, "MAX_TOTAL_BYTES", 5)
    monkeypatch.setattr(api, "MAX_FILE_BYTES", 3)
    manifest = api.SourceManifest.capture(tmp_path, ("a", "b"), implementation_id="fixture")
    manifest.verify(tmp_path)
    (tmp_path / "b").write_bytes(b"def")
    with pytest.raises(ValueError, match="byte limit"):
        api.SourceManifest.capture(tmp_path, ("a", "b"), implementation_id="fixture")
    monkeypatch.setattr(api, "MAX_TOTAL_BYTES", 0)
    with pytest.raises(ValueError, match="byte limit"):
        api.SourceManifest.capture(tmp_path, ("a",), implementation_id="fixture")
    (tmp_path / "empty").write_bytes(b"")
    api.SourceManifest.capture(tmp_path, ("empty",), implementation_id="fixture").verify(tmp_path)


def test_symlink_leaf_parent_and_root_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a").write_text("fixture")
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    (tmp_path / "file").symlink_to(real / "a")
    for root, path in ((tmp_path, "link/a"), (tmp_path / "link", "a"), (tmp_path, "file")):
        with pytest.raises(ValueError):
            api.SourceManifest.capture(root, (path,), implementation_id="fixture")
    with pytest.raises(ValueError):
        api.SourceManifest.capture(Path("relative"), ("a",), implementation_id="fixture")


def test_wrong_pin_or_document_binding_never_enters_backend(fixture_backend):
    _, _, calls, kwargs = fixture_backend()
    with pytest.raises(ValueError, match="identity mismatch"):
        api.PinnedLegalAdapter(**{**kwargs, "expected_sha256": "0" * 64})
    with pytest.raises(ValueError, match="explicitly supplied"):
        api.PinnedLegalAdapter(**{**kwargs, "documents": FixtureDocuments()})
    assert calls == {"checks": [], "stores": []}


def test_expected_pin_must_be_a_literal_digest_string(fixture_backend):
    _, _, _, kwargs = fixture_backend()

    class PretendMatch:
        def __ne__(self, other):
            return False

    with pytest.raises(ValueError, match="identity mismatch"):
        api.PinnedLegalAdapter(**{**kwargs, "expected_sha256": PretendMatch()})


def test_two_interleaved_adapters_do_not_share_rows_documents_or_receipts(fixture_backend):
    a, sa, ca, _ = fixture_backend("a")
    b, sb, cb, _ = fixture_backend("b")
    args = {"document_id": "same-document", "clause_id": "same-clause"}
    assert a.open_document("first")["fixture"] == "a"
    for adapter, label in ((b, "b"), (a, "a")):
        assert tools.dispatch("clause_get", args, adapter=adapter)["fixture"] == label
        assert tools.dispatch("compile_clause", args, adapter=adapter)["fixture"] == label
        assert tools.dispatch("decompile_rule", args, adapter=adapter)["fixture"] == label
        rows = tools.dispatch("rules_for_frame", {"frame_id": "unassigned"}, adapter=adapter)["rows"]
        assert [r["fixture"] for r in rows] == [label]
        assert tools.dispatch("coverage", {"document_id": "same-document"}, adapter=adapter)["compiled"] == 1
    assert tools.admit_locked("same-document", "same-clause", "decide", adapter=a)["ok"]
    assert len(sa.documents.marks) == 1 and sb.documents.marks == []
    repository = object()
    result = tools.admit_roundtrip_rule(ROW, SOURCE, repository=repository, adapter=b)
    assert result["stored"] and result["repository"] is repository
    assert cb["stores"][0]["lean"] == SOURCE and ca["stores"] == []
    assert result["source_adapter"]["verification_performed"] is False
    assert result["source_adapter"] == b.provenance


@pytest.mark.parametrize("arguments", [{}, {"document_id": "d", "clause_id": "c", "theorem_ok": True},
                                      {"document_id": 7, "clause_id": "c"},
                                      {"document_id": "\ud800", "clause_id": "c"},
                                      {"document_id": "d\x00", "clause_id": "c"},
                                      {"document_id": "x" * 1025, "clause_id": "c"}])
def test_malformed_tool_payload_cannot_invoke_backend(fixture_backend, arguments):
    adapter, session, _, _ = fixture_backend()
    assert tools.dispatch("compile_clause", arguments, adapter=adapter)["error"] == "invalid_legal_tool_arguments"
    assert session.rows == []
    assert tools.dispatch("store_attestation", {}, adapter=adapter)["error"] == "unknown_tool"


@pytest.mark.parametrize("mutation", ["change", "delete", "symlink", "binding"])
def test_drift_is_terminal_and_never_falls_back(fixture_backend, mutation):
    adapter, session, calls, kwargs = fixture_backend()
    source = kwargs["root"] / "backend.txt"
    original = source.read_bytes()
    if mutation == "change":
        source.write_bytes(b"X" * len(original))
    elif mutation == "delete":
        source.unlink()
    elif mutation == "symlink":
        replacement = kwargs["root"] / "replacement"
        replacement.write_bytes(original)
        source.unlink()
        source.symlink_to(replacement)
    else:
        session.documents = FixtureDocuments()
    with pytest.raises(api.AdapterError, match="drift"):
        tools.admit_roundtrip_rule(ROW, "decide", adapter=adapter)
    assert calls == {"checks": [], "stores": []}
    if mutation == "change":
        source.write_bytes(original)
    with pytest.raises(api.AdapterError, match="poisoned"):
        tools.dispatch("coverage", {"document_id": "d"}, adapter=adapter)


def test_post_verifier_drift_blocks_storage_and_admission_mark(fixture_backend):
    _, session, calls, kwargs = fixture_backend()

    def mutate(source):
        (kwargs["root"] / "backend.txt").write_text("changed during verification")
        return {"lake_ok": True, "error": ""}

    for entry in ("roundtrip", "locked"):
        (kwargs["root"] / "backend.txt").write_text("declared fixture artifact\n")
        guarded = api.PinnedLegalAdapter(**{**kwargs, "verifier": mutate})
        with pytest.raises(api.AdapterError, match="drift"):
            if entry == "roundtrip":
                tools.admit_roundtrip_rule(ROW, SOURCE, adapter=guarded)
            else:
                tools.admit_locked("d", "c", SOURCE, adapter=guarded)
    assert calls["stores"] == [] and session.documents.marks == []


@pytest.mark.parametrize("result", [{"lake_ok": "true", "error": ""}, {"lake_ok": 1, "error": ""},
                                   {"lake_ok": True}, {"theorem_ok": True}, None])
def test_malformed_verifier_result_cannot_establish_success(fixture_backend, result):
    adapter, _, calls, _ = fixture_backend(verifier=lambda _: result)
    with pytest.raises(api.AdapterError, match="backend_failed"):
        tools.admit_roundtrip_rule(ROW, SOURCE, adapter=adapter)
    assert calls["stores"] == []
    with pytest.raises(api.AdapterError, match="poisoned"):
        adapter.check_source(SOURCE)


@pytest.mark.parametrize("entry", ["roundtrip", "locked", "tool"])
def test_source_command_injection_never_reaches_injected_verifier(fixture_backend, entry):
    adapter, _, calls, _ = fixture_backend()
    attack = SOURCE + "#eval 1\n"
    if entry == "roundtrip":
        result = tools.admit_roundtrip_rule(ROW, attack, adapter=adapter)
    elif entry == "locked":
        result = tools.admit_locked("d", "c", attack, adapter=adapter)
    else:
        result = tools.dispatch("lake_check", {"source": attack}, adapter=adapter)
    assert result["lake_ok"] is False
    assert calls == {"checks": [], "stores": []}


def test_absence_rejection_and_transient_failure_are_distinct(fixture_backend):
    adapter, _, calls, _ = fixture_backend("absent", verifier=None)
    result = tools.admit_roundtrip_rule(ROW, SOURCE, adapter=adapter)
    assert result["error"] == "verifier_unavailable" and not result["stored"]
    rejected, _, _, _ = fixture_backend("rejected", verifier=lambda _: {"lake_ok": False, "error": "fixture_rejected"})
    assert tools.admit_roundtrip_rule(ROW, SOURCE, adapter=rejected)["error"] == "fixture_rejected"

    def timeout(_):
        raise TimeoutError("fixture timeout")

    broken, _, broken_calls, _ = fixture_backend("broken", verifier=timeout)
    with pytest.raises(api.AdapterError, match="backend_failed") as exc:
        tools.admit_roundtrip_rule(ROW, SOURCE, adapter=broken)
    assert isinstance(exc.value.__cause__, TimeoutError)
    assert calls["stores"] == broken_calls["stores"] == []


def test_missing_writer_or_prompt_does_not_fall_back(fixture_backend):
    adapter, _, _, _ = fixture_backend(attestation_writer=None, prompt_builder=None)
    with pytest.raises(api.AdapterError, match="writer_unavailable"):
        tools.admit_roundtrip_rule(ROW, SOURCE, adapter=adapter)
    with pytest.raises(api.AdapterError, match="prompt_builder_unavailable"):
        tools.run_leanstral("fixture legal text", adapter=adapter)


@pytest.mark.parametrize("result", [{"indexed": "false"}, {"indexed": 1}, None])
def test_invalid_writer_result_is_not_reported_as_stored(fixture_backend, result):
    adapter, _, _, _ = fixture_backend(attestation_writer=lambda **_: result)
    with pytest.raises(api.AdapterError, match="backend_failed"):
        tools.admit_roundtrip_rule(ROW, SOURCE, adapter=adapter)


def test_drift_during_compilation_does_not_claim_to_rollback_backend_state(fixture_backend):
    adapter, session, _, kwargs = fixture_backend()
    original = session.compile_clause

    def mutate(**args):
        result = original(**args)
        (kwargs["root"] / "backend.txt").write_text("fixture changed during compile")
        return result

    session.compile_clause = mutate
    with pytest.raises(api.AdapterError, match="drift"):
        adapter.dispatch("compile_clause", {"document_id": "d", "clause_id": "c"})
    assert len(session.rows) == 1  # Caller must discard/recover this poisoned session.
    assert session.documents.marks == []


def test_writer_false_preserves_non_storage_result(fixture_backend):
    adapter, _, _, _ = fixture_backend(attestation_writer=lambda **_: {"indexed": False})
    result = tools.admit_roundtrip_rule(ROW, SOURCE, adapter=adapter)
    assert result["lake_ok"] is True and result["stored"] is False


def test_single_owner_reentrancy_and_close(fixture_backend):
    adapter, session, _, kwargs = fixture_backend()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(api.AdapterError, match="wrong_owner"):
            executor.submit(adapter.check_source, SOURCE).result()
    assert adapter.check_source(SOURCE)["lake_ok"]
    recursive = api.PinnedLegalAdapter(**{**kwargs, "verifier": lambda _: recursive.check_source(SOURCE)})
    with pytest.raises(api.AdapterError, match="reentrant"):
        recursive.check_source(SOURCE)
    adapter.close()
    adapter.close()
    assert session.documents is kwargs["documents"]
    with pytest.raises(api.AdapterError, match="closed"):
        adapter.check_source(SOURCE)


def test_fixture_model_tool_and_final_turn_use_only_injected_dependencies(fixture_backend, monkeypatch):
    adapter, _, calls, _ = fixture_backend()
    model_calls = []

    def fixture_chat(_prompt, **kwargs):
        model_calls.append(kwargs)
        assert kwargs["model"] == "leanstral_local"
        if len(model_calls) == 1:
            return {"tool_calls": [{"id": "fixture-call", "name": "lake_check", "arguments": {"source": SOURCE}}]}
        assert json.loads(kwargs["messages"][-1]["content"])["kind"] == "fixture"
        return {"text": SOURCE, "finish_reason": "fixture"}

    monkeypatch.setattr(leanstral, "chat_completion", fixture_chat)
    result = tools.run_leanstral("fixture-only legal prose", rounds=2, adapter=adapter)
    assert result["lake_ok"] is True and result["source"] == SOURCE.rstrip()
    assert len(model_calls) == 2
    assert calls["checks"] == [SOURCE, SOURCE, SOURCE]
    assert calls["stores"] == []
    assert result["source_adapter"] == adapter.provenance
