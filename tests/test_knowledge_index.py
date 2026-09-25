"""Fresh DuckDB storage tests. No model, Lean, network, or extension calls."""
from dataclasses import replace
import hashlib
import math
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
from jevops.arena import content_hash
from jevops.knowledge_index import KnowledgeIndex, build_index, features
from jevops.premise_search import ExprHead, Premise, PremiseScope, PremiseSignature

pytestmark = pytest.mark.no_seal(reason="exercise actual DuckDB artifacts and native engine")
ENV, SOURCE = content_hash("test environment"), content_hash("test corpus")


def scope(rows, **changes):
    names = tuple(n for row in rows for n in (row.name, *row.aliases))
    return replace(PremiseScope(SOURCE, ENV, names), **changes)


def build(tmp_path, rows, **kwargs):
    return build_index(tmp_path / "corpus.duckdb", iter(rows),
                       environment_sha256=ENV, source_sha256=SOURCE, **kwargs)


def open_index(artifact):
    return KnowledgeIndex(Path(artifact.path), expected_sha256=artifact.file_sha256)


def test_duckdb_roundtrip_exact_symbols_and_read_only(tmp_path):
    rows = [Premise("Upper", "Nat α ≤ β", "lib"), Premise("Lower", "nat Α < β", "lib")]
    artifact = build(tmp_path, rows)
    with open_index(artifact) as index:
        assert index.identity["backend"] == "duckdb"
        assert index.identity["records"] == 2
        for query in ("Nat", "α", "≤"):
            report = index.search(query, target="Target", scope=scope(rows))
            assert [h["premise"]["name"] for h in report["matches"]] == ["Upper"]
            assert report["authority"] == "context_only" and not report["proof_verified"]
        assert index.search("nat", target="Target", scope=scope(rows))["matches"][0]["premise"]["name"] == "Lower"
        with pytest.raises(duckdb.Error):
            index.connection.execute("DELETE FROM entries")
        assert index.connection.execute("SELECT current_setting('enable_external_access')").fetchone() == (False,)
    assert hashlib.sha256(Path(artifact.path).read_bytes()).hexdigest() == artifact.file_sha256
    assert not list(tmp_path.glob("*.wal"))


def test_features_preserve_qualification_case_and_operator_direction():
    assert set(features("List.Subset α β → β ⊆ γ")) >= {"List.Subset", "Subset", "α", "→", "⊆"}
    assert features("Nat α ≤") != features("nat Α <")
    assert "->" in features("P -> Q")


def test_bm25_matches_independent_arithmetic(tmp_path):
    rows = [Premise("A", "Nat Nat", "lib"), Premise("B", "Bool", "lib")]
    with open_index(build(tmp_path, rows)) as index:
        hit = index.search("Nat", target="Target", scope=scope(rows))["matches"][0]
        # Name weighted twice: lengths are 4 and 3, tf=2, df=1, N=2.
        expected = math.log(1 + 1.5 / 1.5) * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 4 / 3.5))
        assert hit["score"] == pytest.approx(expected)


def test_aliases_transitive_wrappers_cycles_and_excluded_origins(tmp_path):
    rows = [Premise("Target", "Nat", "lib", aliases=("Renamed",)),
            Premise("Wrapper", "Nat", "lib", dependencies=("Renamed",)),
            Premise("Twice", "Nat", "lib", dependencies=("Wrapper",)),
            Premise("Protected", "Nat", "reserved-family", aliases=("Alias",)),
            Premise("UsesProtected", "Nat", "lib", dependencies=("Alias",)),
            Premise("A", "Nat", "lib", dependencies=("B", "Secret")),
            Premise("B", "Nat", "lib", dependencies=("A",)),
            Premise("Good", "Nat", "lib")]
    sc = scope(rows, available_names=(*scope(rows).available_names, "Secret"),
               excluded_names=("Secret",), excluded_origins=("reserved-family",))
    with open_index(build(tmp_path, rows)) as index:
        result = index.search("Nat", target="Target", scope=sc, max_scan=1)
        assert result["status"] == "RANKED"
        assert [h["premise"]["name"] for h in result["matches"]] == ["Good"]


def test_missing_dependency_and_alias_target_fail_closed(tmp_path):
    rows = [Premise("A", "Nat", "lib", aliases=("Target",)),
            Premise("B", "Nat", "lib", dependencies=("Missing",))]
    with open_index(build(tmp_path, rows)) as index:
        assert not index.search("Nat", target="Target", scope=scope(rows))["matches"]


def test_snapshot_is_order_independent_and_binds_environment_and_metadata(tmp_path):
    rows = [Premise("B", "Nat", "lib"), Premise("A", "Nat", "lib")]
    left = build(tmp_path, rows)
    right = build_index(tmp_path / "other.duckdb", reversed(rows), environment_sha256=ENV, source_sha256=SOURCE)
    changed = build_index(tmp_path / "changed.duckdb", [replace(rows[0], origin="other"), rows[1]],
                          environment_sha256=ENV, source_sha256=SOURCE)
    assert left.snapshot_sha256 == right.snapshot_sha256 != changed.snapshot_sha256
    with open_index(left) as index:
        with pytest.raises(ValueError, match="environment"):
            index.search("Nat", target="Target", scope=replace(scope(rows), environment_sha256="a" * 64))
        # BM25 score ties break by exact declaration name, independent of ingestion.
        assert index.search("Nat", target="Target", scope=scope(rows), top_k=1)["matches"][0]["premise"]["name"] == "A"


@pytest.mark.parametrize("split", ["validation", "canary", "test"])
def test_heldouts_cannot_enter_posting_statistics(tmp_path, split):
    with pytest.raises(ValueError, match="held-out"):
        build(tmp_path, [Premise("A", "Nat", "reserved", split=split)])
    assert list(tmp_path.iterdir()) == []


def test_budget_exhaustion_returns_no_partial_hits_and_handle_recovers(tmp_path):
    rows = [Premise(f"P{i}", "Nat", "lib") for i in range(4)]
    with open_index(build(tmp_path, rows)) as index:
        for options, status in [({"max_scan": 1}, "SCAN_BUDGET"),
                                ({"max_context_bytes": 128}, "CONTEXT_BUDGET"),
                                ({"timeout_seconds": 1e-12}, "QUERY_TIMEOUT")]:
            report = index.search("Nat", target="Target", scope=scope(rows), **options)
            assert report["status"] == status and report["matches"] == []
        assert len(index.search("Nat", target="Target", scope=scope(rows))["matches"]) == 4


def test_provider_bridge_reuses_existing_scope_contract(tmp_path):
    rows = [Premise("A", "Nat", "lib"), Premise("B", "Nat", "protected")]
    sc = scope(rows, excluded_origins=("protected",))
    with open_index(build(tmp_path, rows)) as index:
        nomination, report = index.provider_index("Nat", target="Target", scope=sc)
        assert set(nomination.entries) == {"A"}
        assert nomination.rank("Nat", target="Target", scope=sc)["matches"][0]["name"] == "A"
        assert report["snapshot_sha256"] == index.identity["snapshot_sha256"]


def test_bad_hash_tampering_overwrite_and_symlink_are_rejected(tmp_path):
    artifact = build(tmp_path, [Premise("A", "Nat", "lib")])
    with pytest.raises(FileExistsError):
        build(tmp_path, [])
    with pytest.raises(ValueError, match="identity"):
        KnowledgeIndex(Path(artifact.path), expected_sha256="a" * 64)
    link = tmp_path / "link.duckdb"
    link.symlink_to(artifact.path)
    with pytest.raises(ValueError, match="regular"):
        KnowledgeIndex(link, expected_sha256=artifact.file_sha256)
    with Path(artifact.path).open("r+b") as stream:
        stream.seek(-1, 2)
        stream.write(b"!")
    with pytest.raises(ValueError, match="identity"):
        open_index(artifact)


@pytest.mark.parametrize("options", [{"max_records": 1}, {"max_bytes": 65536}])
def test_failed_build_does_not_publish_or_leave_scratch(tmp_path, options):
    with pytest.raises(ValueError, match="budget"):
        build(tmp_path, [Premise("A", "Nat", "lib"), Premise("B", "Nat", "lib")], **options)
    assert list(tmp_path.iterdir()) == []


def test_duplicate_identity_and_generator_failure_do_not_publish(tmp_path):
    with pytest.raises(duckdb.ConstraintException):
        build(tmp_path, [Premise("A", "Nat", "lib"), Premise("B", "Nat", "lib", aliases=("A",))])
    def broken():
        yield Premise("A", "Nat", "lib")
        raise RuntimeError("source interrupted")
    with pytest.raises(RuntimeError, match="interrupted"):
        build(tmp_path, broken())
    assert list(tmp_path.iterdir()) == []


def test_empty_corpus_and_query_syntax_are_not_commands(tmp_path):
    with open_index(build(tmp_path, [])) as index:
        result = index.search("Nat; DROP TABLE entries; --", target="Target", scope=scope([]))
        assert result["status"] == "RANKED" and not result["matches"]
        assert index.connection.execute("SELECT count(*) FROM entries").fetchone() == (0,)


def test_missing_duckdb_fails_explicitly_without_a_fallback(monkeypatch):
    import builtins
    from jevops.knowledge_index import _duckdb
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("test missing engine")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(RuntimeError, match="no fallback"):
        _duckdb()


@pytest.mark.parametrize("options", [{"timeout_seconds": True}, {"timeout_seconds": float("nan")},
                                    {"max_scan": 0}, {"top_k": True}])
def test_bad_limits_rejected_before_search(tmp_path, options):
    with open_index(build(tmp_path, [])) as index:
        with pytest.raises(ValueError):
            index.search("Nat", target="Target", scope=scope([]), **options)


def signature(name, head="Nat"):
    return PremiseSignature(name, ("implicit", "instance", "explicit"),
                            (ExprHead("sort"), ExprHead("const", "Decidable", 1), ExprHead("bound")),
                            ExprHead("const", head, 2))


def test_typed_bridge_preserves_complete_signature_and_lexical_fallback(tmp_path):
    rows = [Premise("A", "SurfaceNotation α", "lib"), Premise("B", "Nat", "lib"),
            Premise("C", "OtherNotation α", "lib")]
    sigs = (signature("A"), signature("B", "Bool"), signature("C"))
    with open_index(build(tmp_path, rows, signatures=iter(sigs))) as index:
        nomination, report = index.provider_index("Nat", target="Target", scope=scope(rows),
            conclusion=ExprHead("const", "Nat"), top_k=2)
        # A has no lexical overlap; reserve one slot for mismatching B, since
        # raw heads are not a definitional-equality oracle.
        assert [h["premise"]["name"] for h in report["matches"]] == ["A", "B"]
        assert report["matches"][0]["score"] == 0
        assert [h["head_priority"] for h in report["matches"]] == [0, 2]
        assert nomination.signatures == {"A": sigs[0], "B": sigs[1]}
        assert index.identity["signatures"] == 3
        assert not report["proof_verified"]
        assert nomination.rank("Nat", target="Target", scope=scope(rows), top_k=1,
                               conclusion=ExprHead("const", "Nat"))["matches"][0]["name"] == "A"


def test_typed_candidates_obey_exclusions_and_all_budgets(tmp_path):
    rows = [Premise("Target", "SurfaceNotation α", "lib", aliases=("Alias",)),
            Premise("Wrapper", "SurfaceNotation α", "lib", dependencies=("Alias",)),
            Premise("Good", "SurfaceNotation α", "lib")]
    with open_index(build(tmp_path, rows, signatures=map(lambda p: signature(p.name), rows))) as index:
        report = index.search("Nat", target="Target", scope=scope(rows), conclusion=ExprHead("const", "Nat"), max_scan=1)
        assert [h["premise"]["name"] for h in report["matches"]] == ["Good"]
        assert index.search("Nat", target="Unused", scope=scope(rows), conclusion=ExprHead("const", "Nat"), max_scan=1)["status"] == "SCAN_BUDGET"
        assert index.search("Nat", target="Target", scope=scope(rows), conclusion=ExprHead("const", "Nat"), max_context_bytes=128)["status"] == "CONTEXT_BUDGET"
        with pytest.raises(ValueError, match="typed"):
            index.search("Nat", target="Target", scope=scope(rows), conclusion={"kind": "const", "name": "Nat"})


def test_signature_identity_order_and_mutation(tmp_path):
    rows = [Premise("A", "Nat", "lib"), Premise("B", "Nat", "lib")]
    artifacts = [build_index(tmp_path / f"{i}.duckdb", rows, signatures=sigs,
                            environment_sha256=ENV, source_sha256=SOURCE)
                 for i, sigs in enumerate(((signature("A"), signature("B")),
                                          (signature("B"), signature("A")),
                                          (signature("A", "Bool"), signature("B")), ()))]
    assert artifacts[0].snapshot_sha256 == artifacts[1].snapshot_sha256
    assert len({a.snapshot_sha256 for a in artifacts}) == 3
    entry_ids = []
    for artifact in artifacts:
        with open_index(artifact) as index:
            entry_ids.append(index.search("A", target="Target", scope=scope(rows))["matches"][0]["entry_id"])
    assert entry_ids[0] == entry_ids[1]
    assert len(set(entry_ids)) == 3


@pytest.mark.parametrize("sigs", [(signature("Missing"),), (signature("A"), signature("A")), ({"name": "A"},)])
def test_invalid_signatures_never_publish(tmp_path, sigs):
    with pytest.raises(ValueError, match="signatures"):
        build(tmp_path, [Premise("A", "Nat", "lib"), Premise("B", "Nat", "lib")], signatures=sigs)
    assert not list(tmp_path.iterdir())


def test_legacy_v1_artifact_is_readable_without_mutation(tmp_path):
    # Construct the previous schema explicitly; do not mutate retained probes.
    import json
    from jevops.knowledge_index import LEGACY_SCHEMA
    artifact = build(tmp_path, [Premise("A", "Nat", "lib")])
    connection = duckdb.connect(artifact.path)
    identity = json.loads(connection.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
    identity["schema"] = LEGACY_SCHEMA
    identity.pop("signatures")
    connection.execute("UPDATE meta SET value=? WHERE key='identity'", [json.dumps(identity)])
    connection.execute("DROP TABLE heads; ALTER TABLE entries DROP COLUMN signature; CHECKPOINT")
    connection.close()
    before = Path(artifact.path).read_bytes()
    with KnowledgeIndex(Path(artifact.path), expected_sha256=hashlib.sha256(before).hexdigest()) as index:
        nomination, report = index.provider_index("Nat", target="Target", scope=scope([Premise("A", "Nat", "lib")]),
                                                  conclusion=ExprHead("const", "Nat"))
        assert list(nomination.entries) == ["A"] and not nomination.signatures
        assert report["matches"][0]["signature"] is None
    assert Path(artifact.path).read_bytes() == before


def test_native_inventory_duckdb_bridge_and_all_pin_verification(tmp_path):
    import json
    import os
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit installed Lean opt-in; no downloads or model calls")
    from jevops import arena_lean as native, arena_premises as exporter
    from jevops.arena import Outcome, VerificationRequest
    from jevops.arena_providers import load_inventory, propose_batch
    from jevops.lean import VersionPin
    pins = tuple(VersionPin(tag, "duckdb-native-control") for tag in ("v4.26.0", "v4.29.1"))
    statement = "theorem sample : True"
    record = {"name": "sample", "statement": statement, "src": statement + " := by exact True.intro\n",
              "version_info": [{p.lean_tag: p.git_commit} for p in pins]}
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    bindings = {p: native.ProjectBinding(p, native.pinned_lean(elan, p.lean_tag), tmp_path,
                 "theorem premise : True := True.intro\n", project_backed=False) for p in pins}
    guard = native.NativeLeanVerifier(bindings, max_processes=2)
    report = exporter.NativePremiseExporter(guard, max_processes=2, include_signatures=True).export(
        record, (exporter.PremiseOrigin("premise", "native-control", "library"),))
    assert report["status"] == "INVENTORY_ONLY", report
    original, sc = load_inventory(json.loads(json.dumps(report["inventory"])), json.loads(json.dumps(report["scope"])))
    artifact = build_index(tmp_path / "native.duckdb", original.entries.values(),
        signatures=original.signatures.values(), environment_sha256=sc.environment_sha256,
        source_sha256=content_hash(report["inventory"]))
    with open_index(artifact) as index:
        nominated, retrieval = index.provider_index("True", target="sample", scope=sc,
                                                    conclusion=ExprHead("const", "True"))
        assert nominated.signatures == original.signatures
        assert nominated.signatures["premise"].conclusion == ExprHead("const", "True")
        batch = propose_batch(record, nominated, sc, cap=1)
        assert batch["drafts"] and not batch["proof_verified"] and not retrieval["proof_verified"]
        for pin in pins:
            receipt = guard(VerificationRequest(guard.context(record), batch["drafts"][0]["source"], pin))
            assert receipt.outcome == Outcome.VERIFIED, receipt


def test_columnar_and_executemany_have_identical_contents_and_retrieval(tmp_path):
    rows = [Premise(f"P{i}", "Nat α ≤ β", "protected" if i == 40 else "lib",
                    aliases=(f"Alias{i}",), dependencies=(f"Alias{i - 1}",) if i else ())
            for i in range(130)]
    signatures = [signature(p.name) for p in rows[::3]]
    dumps, reports, snapshots = [], [], []
    for mode in ("executemany", "columnar"):
        artifact = build_index(tmp_path / f"{mode}.duckdb", iter(rows), signatures=iter(signatures),
            environment_sha256=ENV, source_sha256=SOURCE, ingestion_mode=mode)
        snapshots.append(artifact.snapshot_sha256)
        with open_index(artifact) as index:
            # Compare full stored rows/statistics, not only hashes or hit counts.
            dumps.append({t: index.connection.execute(f"SELECT * FROM {t} ORDER BY ALL").fetchall()
                          for t in ("entries", "owners", "dependencies", "postings", "heads", "terms", "meta")})
            reports.append([
                index.search("Nat", target="Target", scope=sc, conclusion=ExprHead("const", "Nat"), **opts)
                for sc, opts in ((scope(rows), {}),
                    (scope(rows, excluded_origins=("protected",)), {}),
                    (scope(rows, excluded_names=("Alias20",)), {}),
                    (scope(rows), {"max_scan": 1}))])
    assert snapshots[0] == snapshots[1] and dumps[0] == dumps[1] and reports[0] == reports[1]


@pytest.mark.parametrize("mode", ["columnar", "executemany"])
@pytest.mark.parametrize("damage", ["duplicate", "heldout", "interrupted", "budget"])
def test_late_batch_failure_never_publishes(tmp_path, mode, damage):
    def records():
        yield from (Premise(f"P{i}", "Nat", "lib") for i in range(64))
        if damage == "interrupted":
            raise RuntimeError("interrupted after flushed batch")
        yield Premise("P0" if damage == "duplicate" else "Last", "Nat", "lib",
                      split="canary" if damage == "heldout" else "library")
    options = {"max_records": 64} if damage == "budget" else {}
    with pytest.raises((ValueError, RuntimeError, duckdb.ConstraintException)):
        build(tmp_path, records(), ingestion_mode=mode, **options)
    assert not list(tmp_path.iterdir())


def test_bulk_index_needs_no_arrow_and_invalid_mode_creates_nothing(tmp_path, monkeypatch):
    import builtins
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise AssertionError("knowledge-only install must not require Arrow")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(ValueError, match="ingestion_mode"):
        build(tmp_path, [], ingestion_mode="auto")
    assert not list(tmp_path.iterdir())
    with open_index(build(tmp_path, [Premise("A", "Nat", "lib")])) as index:
        assert index.identity["records"] == 1
