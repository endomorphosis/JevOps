"""Fresh Parquet/DuckDB IO, adversarial imports, and producer conformance."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
duckdb = pytest.importorskip("duckdb")
from jevops.skillcenter_corpus import (CID_FIELDS, CID_SCHEMA, CORPUS_SCHEMA, ENTRY_SCHEMA,
    INTRINSIC_FIELDS, ROW_FIELDS, ROW_SCHEMA, EvidenceCorpus, _cid, _entry_preimage, import_corpus, main)

pytestmark = pytest.mark.no_seal(reason="fresh SkillCenter Parquet/CID/DuckDB integration")


def row(skill="skill-a", **changes):
    value = dict(skill_id=skill, domain="logic", profile="lean", source_type="fixture",
        source_url="https://example.test/" + skill, title="Équivalence α", overall_score=4.0,
        skill_kind="guide", language="en", source_id="src-a", primary_source_id="src-a",
        metadata_yaml="license_spdx: MIT\nlicense_risk: low\n", skill_md="# α\nProof evidence, not an axiom.",
        library_md="", dataset_id="fixture/skills", dataset_revision="rev-fixture-1",
        repository_file="bundle.parquet", bundle_sha256="a" * 64)
    value.update(changes)
    digest = hashlib.sha256(_entry_preimage(value)).hexdigest()
    body = hashlib.sha256(value["skill_md"].encode()).hexdigest()
    ref = f'{value["dataset_id"]}@{value["dataset_revision"]}/{value["repository_file"]}#{skill}:{body}'
    return {**value, "entry_sha256": digest, "entry_cid": _cid(digest),
        "entry_cid_bytes": b"\x01\x55\x12\x20" + bytes.fromhex(digest),
        "entry_multihash": b"\x12\x20" + bytes.fromhex(digest), "entry_identity_schema_version": ENTRY_SCHEMA,
        "content_sha256": body, "content_cid": _cid(body), "bundle_cid": _cid(value["bundle_sha256"]),
        "source_ref_id": "skillcenter:" + hashlib.sha256(ref.encode()).hexdigest(),
        "license_expression": "MIT", "license_risk": "low", "schema_version": ROW_SCHEMA, "corpus_index": 0}


def export(root, rows=None, *, mutate_cids=None, mutate_manifest=None):
    root.mkdir()
    if rows is None:
        rows = [row(), row("skill-b")]
    rows = [{**r, "corpus_index": i} for i, r in enumerate(rows)]
    corpus_types = {k: pa.string() for k in ROW_FIELDS}
    corpus_types.update(corpus_index=pa.int64(), overall_score=pa.float64(),
                        entry_cid_bytes=pa.binary(), entry_multihash=pa.binary())
    corpus_types.update({k: pa.large_string() for k in ("skill_md", "library_md", "metadata_yaml")})
    schema = pa.schema([(k, v, k == "overall_score") for k, v in sorted(corpus_types.items())],
                       metadata={b"schema_version": ROW_SCHEMA.encode(), b"primary_key": b"entry_cid"})
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / "corpus.parquet", row_group_size=1)
    cids = sorted(({**{k: r[k] for k in CID_FIELDS}, "schema_version": CID_SCHEMA} for r in rows),
                  key=lambda r: r["entry_cid"])
    if mutate_cids:
        mutate_cids(cids)
    schema = pa.schema([(k, pa.int64() if k == "corpus_index" else pa.string(), False) for k in sorted(CID_FIELDS)],
                       metadata={b"schema_version": CID_SCHEMA.encode(), b"primary_key": b"entry_cid"})
    pq.write_table(pa.Table.from_pylist(cids, schema=schema), root / "cid_index.parquet")
    files = {}
    for name in ("corpus", "cid_index"):
        path = root / f"{name}.parquet"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[name] = dict(relative_path=path.name, sha256=digest, cid=_cid(digest),
                           size_bytes=path.stat().st_size, media_type="application/vnd.apache.parquet")
    manifest = dict(schema_version=CORPUS_SCHEMA, entry_identity_schema_version=ENTRY_SCHEMA,
        primary_key="entry_cid", files=files, source_records=len(rows), unique_entry_cids=len(rows),
        unique_skill_ids=len(rows), dataset_id="fixture/skills", dataset_revision="rev-fixture-1", bundle_count=1,
        inputs=[dict(repository_file="bundle.parquet", local_sha256="a" * 64, bundle_cid=_cid("a" * 64),
                     dataset_id="fixture/skills", dataset_revision="rev-fixture-1", total_skills=len(rows))])
    if mutate_manifest:
        mutate_manifest(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(), rows


def ingest(tmp_path, *, rows=None, mutate_cids=None, mutate_manifest=None, **kwargs):
    digest, rows = export(tmp_path / "source", rows, mutate_cids=mutate_cids, mutate_manifest=mutate_manifest)
    artifact = import_corpus(tmp_path / "source", tmp_path / "evidence.duckdb", expected_manifest_sha256=digest,
                             source_split=kwargs.pop("source_split", "library"), **kwargs)
    return artifact, rows


def test_identity_matches_pinned_upstream_golden():
    # Produced independently by ipfs_datasets_py 7f0d38572 SkillCenterSkillRecord.
    value = row()
    assert value["entry_cid"] == "bafkreiby36mv4pfbv6w6hp2uek2l3qkz2ycuogz3gxlvaqlqdiv6cleoqe"
    assert value["source_ref_id"] == "skillcenter:840c68d089da220c9672f3ac277d042ee69c815fb161a0102f0a4e2faa7a9909"
    decomposed = row(title="E\u0301quivalence α")
    assert decomposed["entry_cid"] == value["entry_cid"]
    assert row(skill_md="é")["entry_cid"] == row(skill_md="e\u0301")["entry_cid"]
    assert row(skill_md="é")["content_cid"] != row(skill_md="e\u0301")["content_cid"]


def test_duckdb_roundtrip_provenance_context_and_read_only(tmp_path):
    artifact, rows = ingest(tmp_path)
    before = Path(artifact.path).read_bytes()
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        context = index.context(tuple(r["entry_cid"] for r in rows))
        assert context["authority"] == "untrusted_source_text" and not context["proof_verified"]
        assert context["status"] == "CONTEXT" and len(context["records"]) == 2
        for value in context["records"]:
            assert set(value) == ROW_FIELDS
            assert value["dataset_revision"] == "rev-fixture-1"
            assert value["license_expression"] == "MIT"
            assert value["skill_md"] == rows[0]["skill_md"]
        assert index.identity["backend"] == "duckdb"
        assert index.connection.execute("SELECT current_setting('enable_external_access')").fetchone() == (False,)
        with pytest.raises(duckdb.Error):
            index.connection.execute("DELETE FROM evidence")
        assert index.context((rows[0]["entry_cid"],), excluded_cids=(rows[0]["entry_cid"],))["records"] == []
        assert index.context((rows[0]["entry_cid"],), max_context_bytes=128)["status"] == "CONTEXT_BUDGET"
        missing = index.context((rows[0]["entry_cid"], _cid("f" * 64)))
        assert missing["status"] == "MISSING_CID" and missing["records"] == []
    assert Path(artifact.path).read_bytes() == before
    assert not list(tmp_path.glob(".skillcenter-*"))


@pytest.mark.parametrize("split", ["unassigned", "validation", "canary", "test"])
def test_heldout_or_unassigned_evidence_cannot_be_injected(tmp_path, split):
    artifact, rows = ingest(tmp_path, source_split=split)
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        result = index.context((rows[0]["entry_cid"],))
        assert result["status"] == "EXCLUDED_SPLIT" and not result["records"]


@pytest.mark.parametrize("field,value", [("entry_cid", _cid("b" * 64)), ("skill_md", "forged claim"),
    ("content_sha256", "b" * 64), ("source_ref_id", "skillcenter:forged"), ("entry_multihash", b"bad"),
    ("license_expression", "wrong"), ("bundle_sha256", "b" * 64), ("dataset_revision", "forged")])
def test_stale_content_identities_and_provenance_never_publish(tmp_path, field, value):
    bad = {**row(), field: value}
    with pytest.raises(ValueError, match="mismatch"):
        ingest(tmp_path, rows=[bad])
    assert not (tmp_path / "evidence.duckdb").exists()
    assert not list(tmp_path.glob(".skillcenter-*"))
    assert (tmp_path / "source" / "corpus.parquet").is_file()


@pytest.mark.parametrize("field,value", [("corpus_index", 99), ("content_cid", _cid("f" * 64)),
    ("repository_file", "another.parquet"), ("skill_id", "unknown")])
def test_cid_index_must_join_every_physical_row_exactly(tmp_path, field, value):
    with pytest.raises(ValueError):
        ingest(tmp_path, mutate_cids=lambda rows: rows[0].update({field: value}))
    assert not (tmp_path / "evidence.duckdb").exists()


def test_duplicate_and_unsorted_entries_fail_closed(tmp_path):
    with pytest.raises(duckdb.ConstraintException):
        ingest(tmp_path, rows=[row(), row()])
    assert not (tmp_path / "evidence.duckdb").exists()
    other = tmp_path / "unsorted"
    other.mkdir()
    with pytest.raises(ValueError, match="sorted"):
        ingest(other, mutate_cids=lambda rows: rows.reverse())


@pytest.mark.parametrize("options", [{"max_records": 1}, {"max_bytes": 65536}, {"max_row_bytes": 1024}])
def test_import_budgets_leave_source_intact(tmp_path, options):
    with pytest.raises(ValueError, match="budget|bounded"):
        ingest(tmp_path, **options)
    assert (tmp_path / "source" / "manifest.json").is_file()
    assert not (tmp_path / "evidence.duckdb").exists()
    assert not list(tmp_path.glob(".skillcenter-*"))


def test_corrupt_file_wrong_manifest_unsafe_path_and_no_overwrite(tmp_path):
    artifact, _ = ingest(tmp_path)
    options = dict(expected_manifest_sha256=artifact.manifest_sha256, source_split="library")
    with pytest.raises(FileExistsError):
        import_corpus(tmp_path / "source", Path(artifact.path), **options)
    options["expected_manifest_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="manifest identity"):
        import_corpus(tmp_path / "source", tmp_path / "other.duckdb", **options)
    options["expected_manifest_sha256"] = artifact.manifest_sha256
    path = tmp_path / "source" / "corpus.parquet"
    content = path.read_bytes()
    path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    with pytest.raises(ValueError, match="identity"):
        import_corpus(tmp_path / "source", tmp_path / "other.duckdb", **options)
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    with pytest.raises(ValueError, match="unsafe"):
        ingest(unsafe, mutate_manifest=lambda m: m["files"]["corpus"].update(relative_path="../corpus.parquet"))


def test_symlinked_artifacts_and_mid_ingestion_mutation_rejected(tmp_path, monkeypatch):
    from jevops import skillcenter_corpus as module
    digest, _ = export(tmp_path / "source")
    path = tmp_path / "source" / "cid_index.parquet"
    saved = tmp_path / "saved.parquet"
    path.rename(saved)
    path.symlink_to(saved)
    with pytest.raises(ValueError, match="symlink"):
        import_corpus(tmp_path / "source", tmp_path / "evidence.duckdb", expected_manifest_sha256=digest, source_split="library")
    path.unlink()  # Fixture-owned symlink only.
    saved.rename(path)
    original = module._validate_row
    def mutate(*args):
        result = original(*args)
        manifest_path = tmp_path / "source" / "manifest.json"
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(module, "_validate_row", mutate)
    with pytest.raises(ValueError, match="mutated"):
        import_corpus(tmp_path / "source", tmp_path / "evidence.duckdb", expected_manifest_sha256=digest, source_split="library")
    assert not (tmp_path / "evidence.duckdb").exists()


def test_cli_emits_machine_generated_receipt(tmp_path, capsys):
    digest, _ = export(tmp_path / "source")
    main(["--corpus", str(tmp_path / "source"), "--output", str(tmp_path / "evidence.duckdb"),
          "--manifest-sha256", digest, "--split", "unassigned"])
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["records"] == 2 and not receipt["proof_verified"]
    assert receipt["file_sha256"] == hashlib.sha256(Path(receipt["path"]).read_bytes()).hexdigest()


def test_snapshot_binds_partition_and_source_but_not_output_location(tmp_path):
    digest, _ = export(tmp_path / "source")
    artifacts = [import_corpus(tmp_path / "source", tmp_path / f"{i}.duckdb",
        expected_manifest_sha256=digest, source_split=split) for i, split in enumerate(("library", "library", "canary"))]
    assert artifacts[0].snapshot_sha256 == artifacts[1].snapshot_sha256 != artifacts[2].snapshot_sha256
    empty = tmp_path / "empty"
    empty.mkdir()
    artifact, _ = ingest(empty, rows=[], max_records=0)
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        assert index.context(())["records"] == []


@pytest.mark.parametrize("damage", ["count", "bundle", "revision", "format"])
def test_manifest_contract_rejects_ambiguous_or_foreign_provenance(tmp_path, damage):
    def mutate(manifest):
        if damage == "count":
            manifest["unique_entry_cids"] = True
        elif damage == "bundle":
            manifest["inputs"][0]["local_sha256"] = "b" * 64
            manifest["inputs"][0]["bundle_cid"] = _cid("b" * 64)
        elif damage == "revision":
            manifest["dataset_revision"] = "main"
        else:
            manifest["schema_version"] = "unrecognized/v1"
    with pytest.raises(ValueError):
        ingest(tmp_path, mutate_manifest=mutate)
    assert not (tmp_path / "evidence.duckdb").exists()


def test_missing_parquet_dependency_does_not_fallback(monkeypatch):
    import builtins
    from jevops.skillcenter_corpus import _parquet
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError("deliberately missing reader")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(RuntimeError, match="no fallback"):
        _parquet()


def test_actual_upstream_writer_interoperability_without_sqlite_io(tmp_path, monkeypatch):
    upstream = pytest.importorskip("ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus")
    source = pytest.importorskip("ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter")
    import sqlite3
    def forbidden(*args, **kwargs):
        raise AssertionError("no SQLite IO in Parquet -> DuckDB adapter or producer fixture")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    fields = (*INTRINSIC_FIELDS, "dataset_id", "dataset_revision", "repository_file", "bundle_sha256")
    record = source.SkillCenterSkillRecord(**{k: row()[k] for k in fields})
    class Reader:
        repository_file = record.repository_file
        declared_total_skills = 1
        def inspect(self):
            return source.SkillCenterBundleManifest(record.dataset_id, record.dataset_revision,
                record.repository_file, record.bundle_sha256, 0, "fixture", "v1", "", 1)
        def iter_records(self, **kwargs):
            yield record
    summary = upstream.build_skillcenter_corpus([Reader()], output_dir=tmp_path / "upstream", batch_size=1)
    artifact = import_corpus(tmp_path / "upstream", tmp_path / "evidence.duckdb",
                             expected_manifest_sha256=summary.manifest_sha256, source_split="library")
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
        result = index.context((record.entry_cid,))
        assert result["records"][0]["source_ref_id"] == record.to_source_ref().ref_id
    # Conformance beyond the golden example, including NFC, signed zero,
    # scientific notation, tiny subnormal and maximum finite float64 values.
    for score in (None, 4.0, -0.0, 1e-30, 1e30, 5e-324, 1.7976931348623157e308):
        value = {**asdict(record), "overall_score": score, "title": "E\u0301quivalence α"}
        expected = source.SkillCenterSkillRecord(**value).entry_identity
        assert hashlib.sha256(_entry_preimage(value)).hexdigest() == expected.sha256


def test_multibatch_transport_modes_preserve_all_evidence_and_context(tmp_path):
    digest, rows = export(tmp_path / "source", [row(f"skill-{i}", overall_score=None if i % 2 else -0.0,
        title="E\u0301 α", skill_md="quoted ' text; DROP TABLE evidence; --") for i in range(65)])
    outputs, snapshots = [], []
    for mode in ("executemany", "columnar"):
        artifact = import_corpus(tmp_path / "source", tmp_path / f"{mode}.duckdb",
            expected_manifest_sha256=digest, source_split="library", ingestion_mode=mode)
        snapshots.append(artifact.snapshot_sha256)
        with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as index:
            outputs.append((index.identity,
                index.connection.execute("SELECT * FROM evidence ORDER BY corpus_index").fetchall(),
                index.context(tuple(r["entry_cid"] for r in rows[:8]))))
    assert snapshots[0] == snapshots[1] and outputs[0] == outputs[1]


@pytest.mark.parametrize("mode", ["columnar", "executemany"])
@pytest.mark.parametrize("damage", ["identity", "duplicate", "join"])
def test_late_corpus_failures_rollback_validated_batches(tmp_path, mode, damage):
    rows = [row(f"skill-{i}") for i in range(65)]
    if damage == "identity":
        rows[-1]["skill_md"] = "tampered after computing CID"
    elif damage == "duplicate":
        rows[-1] = rows[0]
    def mutate(cids):
        if damage == "join":
            cids[-1]["skill_id"] = "mismatched-final-row"
    with pytest.raises((ValueError, duckdb.ConstraintException)):
        ingest(tmp_path, rows=rows, mutate_cids=mutate, ingestion_mode=mode)
    assert not (tmp_path / "evidence.duckdb").exists()
    assert not list(tmp_path.glob(".skillcenter-*"))
    assert (tmp_path / "source" / "manifest.json").is_file()


def test_invalid_import_mode_rejected_before_io(tmp_path):
    with pytest.raises(ValueError, match="ingestion_mode"):
        import_corpus(tmp_path / "missing", tmp_path / "evidence.duckdb",
            expected_manifest_sha256="a" * 64, source_split="library", ingestion_mode="auto")
    assert not list(tmp_path.iterdir())
