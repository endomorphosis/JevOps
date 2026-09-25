"""Bounded SkillCenter canonical Parquet -> immutable DuckDB evidence adapter.

Wire format reviewed at ipfs_datasets_py 7f0d38572 (skillcenter_corpus.py,
source_adapters/skillcenter.py, ir_core/{canonical,identity}.py). No upstream
database imports. CIDs certify identity, not truth, licensing, or Lean validity.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import unicodedata

from .arena import content_hash
from .duckdb_ingest import INGESTION_MODES, insert_batch, validate_ingestion_mode
from .knowledge_index import DATABASE_CONFIG, _duckdb, _file_hash
from .premise_search import bounded_int, digest_field
from .proof_ca import canonical_json

SCHEMA = "jevops-skillcenter-evidence/v1"
CORPUS_SCHEMA = "skillcenter-corpus/v1"
ROW_SCHEMA = "skillcenter-corpus-row/v1"
CID_SCHEMA = "skillcenter-corpus-cid-index/v1"
ENTRY_SCHEMA = "skillcenter-entry-identity/v1"
INTRINSIC_FIELDS = tuple(sorted((
    "domain", "language", "library_md", "metadata_yaml", "overall_score", "primary_source_id",
    "profile", "skill_id", "skill_kind", "skill_md", "source_id", "source_type", "source_url", "title")))
ROW_FIELDS = frozenset((*INTRINSIC_FIELDS, "bundle_cid", "bundle_sha256", "content_cid",
    "content_sha256", "corpus_index", "dataset_id", "dataset_revision", "entry_cid", "entry_cid_bytes",
    "entry_identity_schema_version", "entry_multihash", "entry_sha256", "license_expression",
    "license_risk", "repository_file", "schema_version", "source_ref_id"))
CID_FIELDS = frozenset(("content_cid", "corpus_index", "entry_cid", "repository_file", "schema_version", "skill_id"))
SPLITS = frozenset(("unassigned", "library", "train", "validation", "canary", "test"))


def _cid(digest: str) -> str:
    digest_field(digest)
    return "b" + base64.b32encode(b"\x01\x55\x12\x20" + bytes.fromhex(digest)).decode().rstrip("=").lower()


def _entry_preimage(row: dict) -> bytes:
    """Restricted ir-canonical-json-v1 profile: flat strings/float64/null only.

    This is not a general IntentIR canonicalizer. Fixed keys avoid collection
    semantics and normalized-key collisions; floats use finite decimal repr,
    strings NFC. Body CIDs separately hash the ORIGINAL UTF-8, without NFC.
    """
    def scalar(value):
        if value is None:
            return "null"
        if type(value) is str:
            return json.dumps(unicodedata.normalize("NFC", value), ensure_ascii=False)
        if type(value) is not float or not math.isfinite(value):
            raise ValueError("SkillCenter score must be finite float64 or null")
        if value == 0:
            return "0"
        number = format(Decimal(repr(value)), "f")
        return number.rstrip("0").rstrip(".") if "." in number else number
    payload = "{" + ",".join(json.dumps(k) + ":" + scalar(row[k]) for k in INTRINSIC_FIELDS) + "}"
    return ('{"canonicalization":"ir-canonical-json-v1","collection_semantics":{},'
            '"domain":"intent-ir.skillcenter-entry","identity_profile":"ir-canonical-identity-v1",'
            '"payload":' + payload + ',"schema_version":"' + ENTRY_SCHEMA + '"}').encode()


def _metadata_scalar(text: str, key: str) -> str:
    # Match the producer's deliberately limited, non-executable YAML scalar reader.
    match = re.search(r"^" + re.escape(key) + r":[ \t]*(.*)$", text, re.MULTILINE)
    if match is None:
        return ""
    value = match[1].strip()
    if value.startswith('"'):
        try:
            return str(json.loads(value)).strip()
        except ValueError:
            return value.strip('"').strip()
    return value.strip("'").strip() if value.startswith("'") else value


def _validate_row(row: dict, manifest: dict, position: int, max_row_bytes: int) -> dict:
    if set(row) != ROW_FIELDS or type(row["corpus_index"]) is not int or row["corpus_index"] != position:
        raise ValueError("corpus fields or dense ordered row coverage mismatch")
    binary = {"entry_cid_bytes", "entry_multihash"}
    for key in ROW_FIELDS - binary - {"overall_score", "corpus_index"}:
        if type(row[key]) is not str:
            raise ValueError("corpus text fields must be non-null strings")
    if any(type(row[k]) is not bytes for k in binary):
        raise ValueError("corpus identity bytes required")
    if row["overall_score"] is not None and (type(row["overall_score"]) is not float or not math.isfinite(row["overall_score"])):
        raise ValueError("SkillCenter score must be finite float64 or null")
    value = {k: v.hex() if k in binary else v for k, v in row.items()}
    if len(canonical_json(value).encode()) > max_row_bytes:
        raise ValueError("corpus row byte budget")
    if (row["schema_version"] != ROW_SCHEMA or row["entry_identity_schema_version"] != ENTRY_SCHEMA
            or any(row[k] != manifest[k] for k in ("dataset_id", "dataset_revision"))
            or not row["skill_id"] or not row["repository_file"]):
        raise ValueError("corpus schema or provenance mismatch")
    entry_sha = hashlib.sha256(_entry_preimage(row)).hexdigest()
    body_sha = hashlib.sha256(row["skill_md"].encode()).hexdigest()
    if (row["entry_sha256"] != entry_sha or row["entry_cid"] != _cid(entry_sha)
            or row["entry_cid_bytes"] != b"\x01\x55\x12\x20" + bytes.fromhex(entry_sha)
            or row["entry_multihash"] != b"\x12\x20" + bytes.fromhex(entry_sha)
            or row["content_sha256"] != body_sha or row["content_cid"] != _cid(body_sha)
            or row["bundle_cid"] != _cid(row["bundle_sha256"])):
        raise ValueError("corpus CID identity mismatch")
    reference = (f'{row["dataset_id"]}@{row["dataset_revision"]}/{row["repository_file"]}'
                 f'#{row["skill_id"]}:{body_sha}')
    if row["source_ref_id"] != "skillcenter:" + hashlib.sha256(reference.encode()).hexdigest():
        raise ValueError("corpus source reference mismatch")
    if (row["license_expression"] != (_metadata_scalar(row["metadata_yaml"], "license_spdx")
                                     or _metadata_scalar(row["metadata_yaml"], "license"))
            or row["license_risk"] != _metadata_scalar(row["metadata_yaml"], "license_risk")):
        raise ValueError("corpus license metadata mismatch")
    return value


def _regular(root: Path, relative: str) -> Path:
    if type(relative) is not str:
        raise ValueError("relative corpus path required")
    pure = PurePosixPath(relative)
    if not pure.parts or pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
        raise ValueError("unsafe corpus path")
    path = root
    for part in pure.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("corpus symlinks are not accepted")
    if not path.is_file():
        raise ValueError("regular corpus file required")
    return path


def _parquet():
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("SkillCenter Parquet ingestion requires jevops[knowledge-corpus]; no fallback") from exc
    return pq


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite manifest number")


@dataclass(frozen=True)
class CorpusArtifact:
    path: str
    file_sha256: str
    snapshot_sha256: str
    manifest_sha256: str
    dataset_revision: str
    records: int
    size_bytes: int


def import_corpus(root: Path, output: Path, *, expected_manifest_sha256: str, source_split: str,
                  max_records: int = 100_000, max_bytes: int = 256 * 1024 * 1024,
                  max_row_bytes: int = 1024 * 1024,
                  ingestion_mode: str = "columnar") -> CorpusArtifact:
    """Verify every source row and CID-index join BEFORE publishing a new DB.

    File/source hashes, records, metadata-declared uncompressed bytes, decoded
    payload bytes and final DB size are capped. Not a hard RSS/peak-disk sandbox.
    Inputs must remain immutable during import; existing artifacts never change.
    Insertion mode changes transport only, not validation or snapshot identity.
    """
    validate_ingestion_mode(ingestion_mode)
    digest_field(expected_manifest_sha256)
    bounded_int(max_records, 0, 1_000_000)
    bounded_int(max_bytes, 65536, 256 * 1024 * 1024)
    bounded_int(max_row_bytes, 1024, 16 * 1024 * 1024)
    if type(source_split) is not str or source_split not in SPLITS:
        raise ValueError("explicit known source split required")
    root, output = Path(root).absolute(), Path(output).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("regular corpus directory required")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError("output parent must exist")
    manifest_path = _regular(root, "manifest.json")
    if manifest_path.stat().st_size > min(max_bytes, 16 * 1024 * 1024):
        raise ValueError("manifest byte budget")
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise ValueError("manifest identity mismatch")
    manifest = json.loads(raw, object_pairs_hook=_json_object, parse_constant=_invalid_constant)
    if (type(manifest) is not dict or manifest.get("schema_version") != CORPUS_SCHEMA
            or manifest.get("entry_identity_schema_version") != ENTRY_SCHEMA
            or manifest.get("primary_key") != "entry_cid" or type(manifest.get("files")) is not dict
            or set(manifest["files"]) != {"corpus", "cid_index"}):
        raise ValueError("unsupported corpus manifest")
    count = bounded_int(manifest.get("source_records"), 0, max_records)
    if any(type(manifest.get(k)) is not int or manifest[k] != count
           for k in ("unique_entry_cids", "unique_skill_ids")):
        raise ValueError("manifest unique coverage mismatch")
    if any(type(manifest.get(k)) is not str or not manifest[k] for k in ("dataset_id", "dataset_revision")):
        raise ValueError("dataset provenance required")
    if manifest["dataset_revision"].lower() in {"main", "master", "head", "latest", "refs/heads/main", "refs/heads/master"}:
        raise ValueError("immutable dataset revision required")
    bundle_count = bounded_int(manifest.get("bundle_count"), 1, 100_000)
    if type(manifest.get("inputs")) is not list or len(manifest["inputs"]) != bundle_count:
        raise ValueError("manifest bundle coverage mismatch")
    bundles = {}
    for item in manifest["inputs"]:
        if (type(item) is not dict or any(item.get(k) != manifest[k] for k in ("dataset_id", "dataset_revision"))
                or type(item.get("repository_file")) is not str or not item["repository_file"]
                or item["repository_file"] in bundles or item.get("bundle_cid") != _cid(item.get("local_sha256"))):
            raise ValueError("manifest bundle provenance mismatch")
        bundles[item["repository_file"]] = (item["local_sha256"], bounded_int(item.get("total_skills"), 0, count))
    if sum(v[1] for v in bundles.values()) != count:
        raise ValueError("manifest physical bundle coverage mismatch")
    pq, paths, readers, source_bytes, expanded_bytes = _parquet(), {}, {}, len(raw), 0
    try:
        for key, schema, fields in (("corpus", ROW_SCHEMA, ROW_FIELDS), ("cid_index", CID_SCHEMA, CID_FIELDS)):
            desc = manifest["files"][key]
            if type(desc) is not dict or desc.get("media_type") != "application/vnd.apache.parquet":
                raise ValueError("Parquet file descriptor required")
            path = _regular(root, desc.get("relative_path"))
            size = bounded_int(desc.get("size_bytes"), 1, max_bytes)
            source_bytes += size
            if source_bytes > max_bytes or path.stat().st_size != size:
                raise ValueError("source byte budget or size mismatch")
            digest = _file_hash(path)
            if desc.get("sha256") != digest or desc.get("cid") != _cid(digest):
                raise ValueError("Parquet file identity mismatch")
            paths[key] = path
            reader = readers[key] = pq.ParquetFile(path)
            metadata = reader.schema_arrow.metadata or {}
            if (set(reader.schema_arrow.names) != fields or len(reader.schema_arrow.names) != len(fields)
                    or metadata.get(b"schema_version") != schema.encode()
                    or metadata.get(b"primary_key") != b"entry_cid" or reader.metadata.num_rows != count):
                raise ValueError("Parquet schema or row coverage mismatch")
            for group in range(reader.metadata.num_row_groups):
                size = reader.metadata.row_group(group).total_byte_size
                expanded_bytes += size
                if size > 16 * 1024 * 1024 or expanded_bytes > max_bytes:
                    raise ValueError("Parquet declared expansion budget")
        duckdb = _duckdb()
        with tempfile.TemporaryDirectory(prefix=".skillcenter-", dir=output.parent) as scratch:
            staging = Path(scratch) / "evidence.duckdb"
            connection = duckdb.connect(str(staging), config=DATABASE_CONFIG)
            try:
                connection.execute("""CREATE TABLE meta(key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL);
                    CREATE TABLE evidence(corpus_index BIGINT PRIMARY KEY, entry_cid VARCHAR UNIQUE NOT NULL,
                        content_cid VARCHAR NOT NULL, repository_file VARCHAR NOT NULL, skill_id VARCHAR UNIQUE NOT NULL,
                        payload VARCHAR NOT NULL, payload_bytes BIGINT NOT NULL);
                    CREATE TABLE cid_index(corpus_index BIGINT PRIMARY KEY, entry_cid VARCHAR UNIQUE NOT NULL,
                        content_cid VARCHAR NOT NULL, repository_file VARCHAR NOT NULL, skill_id VARCHAR UNIQUE NOT NULL);
                    BEGIN TRANSACTION;""")
                position, payload_bytes = 0, 0
                bundle_counts = dict.fromkeys(bundles, 0)
                for batch in readers["corpus"].iter_batches(batch_size=64):
                    values = []
                    for row in batch.to_pylist():
                        value = _validate_row(row, manifest, position, max_row_bytes)
                        bundle = bundles.get(row["repository_file"])
                        if bundle is None or row["bundle_sha256"] != bundle[0]:
                            raise ValueError("row bundle provenance mismatch")
                        bundle_counts[row["repository_file"]] += 1
                        payload = canonical_json(value)
                        payload_bytes += len(payload.encode())
                        if payload_bytes > max_bytes or position >= count:
                            raise ValueError("decoded corpus budget")
                        values.append((position, row["entry_cid"], row["content_cid"],
                                       row["repository_file"], row["skill_id"], payload, len(payload.encode())))
                        position += 1
                    if values:
                        insert_batch(connection, "evidence", values, mode=ingestion_mode)
                if position != count:
                    raise ValueError("decoded corpus coverage mismatch")
                if any(bundle_counts[k] != v[1] for k, v in bundles.items()):
                    raise ValueError("decoded bundle coverage mismatch")
                position, previous = 0, ""
                for batch in readers["cid_index"].iter_batches(batch_size=64):
                    values = []
                    for row in batch.to_pylist():
                        if (any(type(row[k]) is not str for k in CID_FIELDS - {"corpus_index"})
                                or type(row["corpus_index"]) is not int or not 0 <= row["corpus_index"] < count
                                or row["schema_version"] != CID_SCHEMA or row["entry_cid"] <= previous):
                            raise ValueError("sorted unique CID index required")
                        previous = row["entry_cid"]
                        position += 1
                        payload_bytes += len(canonical_json(row).encode())
                        if payload_bytes > max_bytes or position > count:
                            raise ValueError("decoded CID index budget")
                        values.append(tuple(row[k] for k in ("corpus_index", "entry_cid", "content_cid", "repository_file", "skill_id")))
                    if values:
                        insert_batch(connection, "cid_index", values, mode=ingestion_mode)
                missing = connection.execute("""SELECT count(*) FROM evidence e ANTI JOIN cid_index c
                    ON e.corpus_index=c.corpus_index AND e.entry_cid=c.entry_cid AND e.content_cid=c.content_cid
                    AND e.repository_file=c.repository_file AND e.skill_id=c.skill_id""").fetchone()[0]
                if position != count or missing:
                    raise ValueError("CID index foreign-key coverage mismatch")
                # Detect ordinary mid-import mutation; not an adversarial filesystem attestation.
                if _file_hash(manifest_path) != expected_manifest_sha256 or any(
                    _file_hash(path) != manifest["files"][key]["sha256"] for key, path in paths.items()
                ):
                    raise ValueError("corpus mutated during ingestion")
                identity = {"schema": SCHEMA, "manifest_sha256": expected_manifest_sha256,
                            "source_split": source_split, "records": count, "manifest": manifest,
                            "backend": "duckdb", "duckdb_version": duckdb.__version__,
                            "authority": "context_only", "proof_verified": False}
                snapshot = content_hash(identity)
                identity["snapshot_sha256"] = snapshot
                connection.execute("INSERT INTO meta VALUES ('identity', ?)", [canonical_json(identity)])
                connection.execute("DROP TABLE cid_index; COMMIT; CHECKPOINT;")
            finally:
                connection.close()
            if staging.stat().st_size > max_bytes:
                raise ValueError("artifact byte budget")
            with staging.open("rb") as stream:
                os.fsync(stream.fileno())
            artifact = CorpusArtifact(str(output), _file_hash(staging), snapshot, expected_manifest_sha256,
                                      manifest["dataset_revision"], count, staging.stat().st_size)
            os.link(staging, output)
            return artifact
    finally:
        for reader in readers.values():
            reader.close()


class EvidenceCorpus:
    """Read-only evidence lookup, not a premise inventory or theorem compiler."""
    def __init__(self, path: Path, *, expected_sha256: str):
        digest_field(expected_sha256)
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("bounded regular evidence artifact required")
        if _file_hash(path) != expected_sha256:
            raise ValueError("evidence artifact identity mismatch")
        self.connection = _duckdb().connect(str(path), read_only=True, config=DATABASE_CONFIG)
        try:
            self.identity = json.loads(self.connection.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
            if (self.identity.get("schema") != SCHEMA or self.identity.get("backend") != "duckdb"
                    or self.identity.get("source_split") not in SPLITS):
                raise ValueError("unsupported evidence identity")
            digest_field(self.identity["snapshot_sha256"])
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def context(self, entry_cids: tuple[str, ...], *, excluded_cids: tuple[str, ...] = (),
                max_context_bytes: int = 32768) -> dict:
        bounded_int(max_context_bytes, 128, 1024 * 1024)
        for values, limit in ((entry_cids, 32), (excluded_cids, 8192)):
            if (type(values) is not tuple or len(values) > limit
                    or any(type(v) is not str or not re.fullmatch(r"b[a-z2-7]{58}", v) for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError("bounded unique CID nominations required")
        result = {"schema": "jevops-skillcenter-context/v1", "snapshot_sha256": self.identity["snapshot_sha256"],
                  "authority": "untrusted_source_text", "proof_verified": False, "status": "CONTEXT", "records": []}
        result["request_sha256"] = content_hash({"snapshot_sha256": result["snapshot_sha256"],
            "entry_cids": sorted(entry_cids), "excluded_cids": sorted(excluded_cids),
            "max_context_bytes": max_context_bytes})
        if self.identity["source_split"] not in {"library", "train"}:
            return {**result, "status": "EXCLUDED_SPLIT"}
        wanted = sorted(set(entry_cids) - set(excluded_cids))
        count, size = self.connection.execute("""SELECT count(*), coalesce(sum(payload_bytes), 0)
            FROM evidence WHERE entry_cid IN (SELECT unnest(?::VARCHAR[]))""", [wanted]).fetchone()
        if count != len(wanted):
            return {**result, "status": "MISSING_CID"}
        # Check encoded payload bytes before materializing potentially large bodies.
        if size > max_context_bytes:
            return {**result, "status": "CONTEXT_BUDGET", "records": []}
        rows = self.connection.execute("""SELECT payload FROM evidence
            WHERE entry_cid IN (SELECT unnest(?::VARCHAR[])) ORDER BY entry_cid""", [wanted]).fetchall()
        result["records"] = [json.loads(row[0]) for row in rows]
        if len(canonical_json(result).encode()) > max_context_bytes:
            return {**result, "status": "CONTEXT_BUDGET", "records": []}
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--split", choices=sorted(SPLITS), required=True)
    parser.add_argument("--max-records", type=int, default=100_000)
    parser.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--ingestion-mode", choices=INGESTION_MODES, default="columnar")
    args = parser.parse_args(argv)
    result = import_corpus(args.corpus, args.output, expected_manifest_sha256=args.manifest_sha256,
                           source_split=args.split, max_records=args.max_records, max_bytes=args.max_bytes,
                           ingestion_mode=args.ingestion_mode)
    print(canonical_json({**asdict(result), "ingestion_mode": args.ingestion_mode,
                          "authority": "context_only", "proof_verified": False}))


if __name__ == "__main__":
    main()
