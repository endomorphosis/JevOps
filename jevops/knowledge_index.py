"""Opt-in DuckDB premise retrieval. Index integrity is not proof authority.

Uses the immutable corpus / sparse postings / provenance separation design
reviewed in ipfs_datasets_py's SkillCenter corpus indexes (7f0d38572).
DuckDB is the only backend; no extensions, downloads, or mock embeddings.
Record IDs are explicitly sha256 URIs, not IPFS CID encodings.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Iterable

from .arena import content_hash, source_hash
from .duckdb_ingest import insert_batch, validate_ingestion_mode
from .premise_search import (ExprHead, Premise, PremiseIndex, PremiseScope, PremiseSignature,
                            bounded_int, digest_field, premise_name)
from .proof_ca import canonical_json

LEGACY_SCHEMA = "jevops-duckdb-knowledge-index/v1"
SCHEMA = "jevops-duckdb-knowledge-index/v2"
FEATURE_METHOD = "case-sensitive-unicode-weighted-bag-bm25/v1"
DATABASE_CONFIG = {"threads": 1, "memory_limit": "128MB", "enable_external_access": False,
                   "autoload_known_extensions": False, "autoinstall_known_extensions": False,
                   "max_temp_directory_size": "0B"}
_LEXEMES = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*|\d+|↔|→|←|≤|≥|≠|∈|⊆|∧|∨|¬|∀|∃|<->|->|<=|>=|!=|[=<>+*/-]", re.UNICODE)


def _feature_counts(text: str) -> Counter:
    """Lexical hints only, preserving exact case and Unicode/operator bytes."""
    if type(text) is not str or not text.strip() or len(text.encode()) > 16384:
        raise ValueError("bounded nonempty feature text required")
    values = Counter()
    for match in _LEXEMES.finditer(text):
        token = match.group()
        values[token] += 1
        if "." in token:
            values[token.rsplit(".", 1)[-1]] += 1
    if len(values) > 512:
        raise ValueError("feature budget")
    return values


def features(text: str) -> tuple[str, ...]:
    return tuple(sorted(_feature_counts(text)))


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB is required: install jevops[knowledge]; no fallback backend") from exc
    return duckdb


def _canonical(premise: Premise) -> dict:
    if type(premise) is not Premise:
        raise ValueError("typed Premise required")
    value = asdict(premise)
    for key in ("aliases", "dependencies"):
        value[key] = sorted(value[key])
    return value


def _premise(value: dict) -> Premise:
    return Premise(**{**value, "aliases": tuple(value["aliases"]),
                      "dependencies": tuple(value["dependencies"])})


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class IndexArtifact:
    path: str
    file_sha256: str
    snapshot_sha256: str
    environment_sha256: str
    records: int
    size_bytes: int


def build_index(path: Path, premises: Iterable[Premise], *, environment_sha256: str,
                source_sha256: str, max_records: int = 100_000,
                max_bytes: int = 32 * 1024 * 1024,
                signatures: Iterable[PremiseSignature] = (),
                ingestion_mode: str = "columnar") -> IndexArtifact:
    """Stream a NEW immutable artifact. Never replace an existing file/cache.

    Caller supplies honest provenance and an environment-bound inventory. Only
    library/train records may enter lexical statistics. Held-out names/families
    and their wrappers must also be excluded by the inventory producer.
    columnar inserts preserve the same validation and logical snapshot as the
    explicit executemany control; this is not a different storage backend.
    """
    validate_ingestion_mode(ingestion_mode)
    digest_field(environment_sha256)
    digest_field(source_sha256)
    bounded_int(max_records, 1, 1_000_000)
    bounded_int(max_bytes, 65536, 256 * 1024 * 1024)
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    if not path.parent.is_dir():
        raise ValueError("output parent must already exist")
    duckdb = _duckdb()
    # Only this unpublished scratch directory is cleaned. Existing artifacts
    # and all environment/build caches are retained. max_bytes bounds input and
    # published artifact size, NOT the engine's transient disk usage.
    with tempfile.TemporaryDirectory(prefix=".knowledge-", dir=path.parent) as scratch:
        staging = Path(scratch) / "index.duckdb"
        connection = duckdb.connect(str(staging), config=DATABASE_CONFIG)
        try:
            connection.execute("""
                CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL);
                CREATE TABLE entries (
                    id BIGINT PRIMARY KEY, entry_id VARCHAR NOT NULL UNIQUE,
                    name VARCHAR NOT NULL UNIQUE, origin VARCHAR NOT NULL,
                    payload VARCHAR NOT NULL, document_length BIGINT NOT NULL,
                    signature VARCHAR);
                CREATE TABLE heads (entry BIGINT PRIMARY KEY, kind VARCHAR NOT NULL, name VARCHAR);
                CREATE TABLE owners (name VARCHAR PRIMARY KEY, entry BIGINT NOT NULL);
                CREATE TABLE dependencies (entry BIGINT NOT NULL, name VARCHAR NOT NULL,
                    PRIMARY KEY(entry, name));
                CREATE TABLE postings (entry BIGINT NOT NULL, feature VARCHAR NOT NULL,
                    tf INTEGER NOT NULL, PRIMARY KEY(entry, feature));
                BEGIN TRANSACTION;
            """)
            count, input_bytes, total_length = 0, 0, 0
            batches = {"entries": [], "owners": [], "dependencies": [], "postings": []}

            def flush():
                for table, rows in batches.items():
                    if rows:
                        insert_batch(connection, table, rows, mode=ingestion_mode)
                        rows.clear()

            for count, premise in enumerate(premises, 1):
                if count > max_records:
                    raise ValueError("record budget")
                value = _canonical(premise)
                if premise.split not in {"library", "train"}:
                    raise ValueError("held-out records must not enter retrieval statistics")
                payload = canonical_json(value)
                input_bytes += len(payload.encode())
                if input_bytes > max_bytes:
                    raise ValueError("input byte budget")
                entry_id = "sha256:" + content_hash({"schema": SCHEMA, "premise": value,
                                                    "environment_sha256": environment_sha256})
                bag = _feature_counts(premise.type_text)
                names = _feature_counts(premise.name)
                bag.update(names)
                bag.update(names)  # Versioned 2x declaration-name token weight.
                length = sum(bag.values())
                total_length += length
                batches["entries"].append((count, entry_id, premise.name, premise.origin, payload, length, None))
                batches["owners"].extend((name, count) for name in (premise.name, *premise.aliases))
                batches["dependencies"].extend((count, name) for name in premise.dependencies)
                batches["postings"].extend((count, feature, tf) for feature, tf in sorted(bag.items()))
                if count % 64 == 0:
                    flush()
            flush()
            signature_count = 0
            for signature in signatures:
                signature_count += 1
                if type(signature) is not PremiseSignature or signature_count > count:
                    raise ValueError("bounded in-inventory signatures required")
                row = connection.execute("SELECT id, payload, signature FROM entries WHERE name=?",
                                         [signature.name]).fetchone()
                if row is None or row[2] is not None:
                    raise ValueError("unique in-inventory signatures required")
                payload = canonical_json(signature.to_dict())
                input_bytes += len(payload.encode())
                if input_bytes > max_bytes:
                    raise ValueError("input byte budget including signatures")
                entry_id = "sha256:" + content_hash({"schema": SCHEMA, "premise": json.loads(row[1]),
                    "environment_sha256": environment_sha256, "signature": signature.to_dict()})
                connection.execute("UPDATE entries SET signature=?, entry_id=? WHERE id=?",
                                   [payload, entry_id, row[0]])
                connection.execute("INSERT INTO heads VALUES (?, ?, ?)",
                                   [row[0], signature.conclusion.kind, signature.conclusion.name])
            connection.execute("""
                CREATE INDEX owner_entry ON owners(entry);
                CREATE INDEX dependency_name ON dependencies(name);
                CREATE INDEX posting_feature ON postings(feature);
                CREATE TABLE terms AS SELECT feature, count(*) AS df FROM postings GROUP BY feature;
                CREATE UNIQUE INDEX term_feature ON terms(feature);
                CREATE INDEX head_name ON heads(name);
            """)
            identity = {"schema": SCHEMA, "features": FEATURE_METHOD, "backend": "duckdb",
                        "environment_sha256": environment_sha256, "source_sha256": source_sha256,
                        "records": count, "signatures": signature_count, "duckdb_version": duckdb.__version__,
                        "total_document_length": total_length, "bm25_k1": 1.2, "bm25_b": 0.75}
            root = hashlib.sha256(canonical_json(identity).encode())
            cursor = connection.execute("SELECT entry_id FROM entries ORDER BY entry_id")
            while batch := cursor.fetchmany(512):
                for (entry_id,) in batch:
                    root.update(bytes.fromhex(entry_id.removeprefix("sha256:")))
            identity["snapshot_sha256"] = root.hexdigest()
            connection.execute("INSERT INTO meta VALUES ('identity', ?)", [canonical_json(identity)])
            connection.execute("COMMIT; CHECKPOINT;")
        finally:
            connection.close()
        if staging.stat().st_size > max_bytes:
            raise ValueError("artifact byte budget")
        with staging.open("rb") as stream:
            os.fsync(stream.fileno())
        artifact = IndexArtifact(str(path), _file_hash(staging), root.hexdigest(),
                                 environment_sha256, count, staging.stat().st_size)
        os.link(staging, path)  # Atomic publication, refusing any existing target.
        return artifact


class KnowledgeIndex:
    """Single-owner read-only snapshot; call close or use a context manager.

    Rehash on open, not on every query. Caller must keep the artifact immutable
    for this handle's lifetime. A hash binds bytes, not the truth of provenance.
    """

    def __init__(self, path: Path, *, expected_sha256: str):
        digest_field(expected_sha256)
        path = Path(path).absolute()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("bounded regular index required")
        if _file_hash(path) != expected_sha256:
            raise ValueError("index identity mismatch")
        self.connection = _duckdb().connect(str(path), read_only=True, config=DATABASE_CONFIG)
        try:
            self.identity = json.loads(self.connection.execute(
                "SELECT value FROM meta WHERE key='identity'").fetchone()[0])
            if (self.identity["schema"] not in {SCHEMA, LEGACY_SCHEMA} or self.identity["features"] != FEATURE_METHOD
                    or self.identity["backend"] != "duckdb"):
                raise ValueError("unsupported index schema/features")
            digest_field(self.identity["snapshot_sha256"])
            digest_field(self.identity["environment_sha256"])
        except Exception:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def search(self, goal: str, *, target: str, scope: PremiseScope, top_k: int = 8,
               max_scan: int = 512, timeout_seconds: float = 5.0,
               max_context_bytes: int = 32768, conclusion: ExprHead | None = None) -> dict:
        """Exclude target/aliases/dependency descendants BEFORE selecting hits.

        DuckDB query deadline, memory and result sizes are bounded. Exhaustion returns
        no partial ranking. Scope/provenance remain supplied by trusted callers.
        """
        premise_name(target)
        if conclusion is not None and type(conclusion) is not ExprHead:
            raise ValueError("typed conclusion head required")
        if type(scope) is not PremiseScope or scope.environment_sha256 != self.identity["environment_sha256"]:
            raise ValueError("premise environment mismatch")
        bounded_int(top_k, 1, 32)
        bounded_int(max_scan, 1, 8192)
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
            raise ValueError("query timeout must be finite and in (0, 60]")
        bounded_int(max_context_bytes, 128, 1_048_576)
        query = features(goal)
        if len(query) > 128:
            raise ValueError("query feature budget")
        result = {"schema": "jevops-knowledge-retrieval/v2", "authority": "context_only",
                  "proof_verified": False, "snapshot_sha256": self.identity["snapshot_sha256"],
                  "scope_sha256": content_hash(asdict(scope)), "goal_sha256": source_hash(goal),
                  "target": target, "feature_method": FEATURE_METHOD, "status": "RANKED",
                  "backend": "duckdb", "top_k": top_k, "max_scan": max_scan, "timeout_seconds": timeout_seconds,
                  "max_context_bytes": max_context_bytes, "matches": []}
        if conclusion is not None:
            result.update(conclusion=asdict(conclusion), head_priority="raw-conclusion-head-priority/v1",
                          fallback_slots=int(top_k > 1))
        result["request_sha256"] = content_hash(result)
        typed = self.identity["schema"] == SCHEMA
        if not query and (conclusion is None or not typed):
            return result
        connection = self.connection
        deadline = time.monotonic() + timeout_seconds

        def check_deadline():
            if time.monotonic() >= deadline:
                raise TimeoutError("query deadline")

        def execute(sql, parameters=None):
            check_deadline()
            return connection.execute(sql, parameters) if parameters is not None else connection.execute(sql)

        timer = threading.Timer(timeout_seconds, connection.interrupt)
        timer.daemon = True
        timer.start()
        try:
            execute("""
                DROP TABLE IF EXISTS available;
                DROP TABLE IF EXISTS denied;
                DROP TABLE IF EXISTS origins;
                DROP TABLE IF EXISTS query_features;
                CREATE TEMP TABLE available(name VARCHAR PRIMARY KEY);
                CREATE TEMP TABLE denied(name VARCHAR PRIMARY KEY);
                CREATE TEMP TABLE origins(name VARCHAR PRIMARY KEY);
                CREATE TEMP TABLE query_features(feature VARCHAR PRIMARY KEY);
            """)
            for table, values in (("available", scope.available_names),
                                  ("denied", tuple(sorted({target, *scope.excluded_names}))),
                                  ("origins", scope.excluded_origins), ("query_features", query)):
                execute(f"INSERT INTO {table} SELECT unnest(?::VARCHAR[])", [list(values)])
            execute("""INSERT OR IGNORE INTO denied
                SELECT e.name FROM entries e WHERE e.origin IN (SELECT name FROM origins)
                OR e.name NOT IN (SELECT name FROM available)
                OR EXISTS (SELECT 1 FROM dependencies d WHERE d.entry=e.id
                           AND d.name NOT IN (SELECT name FROM available))""")
            execute("""WITH RECURSIVE links(src, dst) AS (
                SELECT o.name, e.name FROM owners o JOIN entries e ON e.id=o.entry
                UNION ALL SELECT e.name, o.name FROM owners o JOIN entries e ON e.id=o.entry
                UNION ALL SELECT d.name, e.name FROM dependencies d JOIN entries e ON e.id=d.entry
                ), blocked(name) AS (
                SELECT name FROM denied
                UNION
                SELECT links.dst FROM blocked b JOIN links ON links.src=b.name
                ) INSERT OR IGNORE INTO denied SELECT name FROM blocked""")
            candidates = "SELECT p.entry FROM postings p JOIN query_features q ON q.feature=p.feature"
            parameters = []
            if conclusion is not None and typed:
                candidates += " UNION SELECT entry FROM heads WHERE name=? OR kind!='const'"
                parameters.append(conclusion.name)
            ids = execute(f"""SELECT DISTINCT e.id FROM ({candidates}) c JOIN entries e ON e.id=c.entry
                WHERE e.name NOT IN (SELECT name FROM denied) LIMIT ?""",
                          [*parameters, max_scan + 1]).fetchall()
            if len(ids) > max_scan:
                return {**result, "status": "SCAN_BUDGET"}
            if not ids:
                check_deadline()
                return result
            n = self.identity["records"]
            avg_length = self.identity["total_document_length"] / n
            signature_column = "e.signature" if typed else "NULL"
            rows = execute(f"""SELECT e.entry_id, e.payload, {signature_column},
                coalesce(sum(ln(1.0 + (? - t.df + 0.5) / (t.df + 0.5)) *
                    p.tf * 2.2 / (p.tf + 1.2 * (0.25 + 0.75 * e.document_length / ?))), 0) AS score
                FROM entries e LEFT JOIN (postings p JOIN query_features q ON q.feature=p.feature
                JOIN terms t ON t.feature=p.feature) ON e.id=p.entry
                WHERE e.id IN (SELECT unnest(?::BIGINT[])) GROUP BY e.entry_id, e.payload, {signature_column}
                """, [n, avg_length, [row[0] for row in ids]]).fetchall()
            hits = []
            for entry_id, payload, signature, raw_score in rows:
                value = json.loads(payload)
                score = float(raw_score)
                if not math.isfinite(score) or score < 0:
                    raise ValueError("invalid sparse score")
                sig = PremiseSignature.from_dict(json.loads(signature)) if signature is not None else None
                if sig is not None and sig.name != value["name"]:
                    raise ValueError("signature owner mismatch")
                hit = {"entry_id": entry_id, "premise": value, "score": score,
                       "signature": sig.to_dict() if sig is not None else None}
                if conclusion is not None:
                    hit["head_priority"] = (1 if sig is None or sig.conclusion.kind != "const"
                                            or conclusion.kind != "const" else
                                            0 if sig.conclusion.name == conclusion.name else 2)
                hits.append(hit)
            hits.sort(key=lambda hit: (-hit["score"], hit["premise"]["name"]))
            if conclusion is not None:
                matched = [h for h in hits if h["head_priority"] == 0]
                fallback = sorted((h for h in hits if h["head_priority"] != 0),
                                  key=lambda h: (h["head_priority"], -h["score"], h["premise"]["name"]))
                selected = matched[:top_k - int(bool(fallback) and top_k > 1)]
                hits = selected + fallback[:top_k - len(selected)]
            result["matches"] = hits[:top_k]
            check_deadline()
            if len(canonical_json(result).encode()) > max_context_bytes:
                return {**result, "status": "CONTEXT_BUDGET", "matches": []}
            return result
        except (TimeoutError, _duckdb().InterruptException):
            return {**result, "status": "QUERY_TIMEOUT", "matches": []}
        except _duckdb().OutOfMemoryException:
            return {**result, "status": "MEMORY_BUDGET", "matches": []}
        finally:
            timer.cancel()
            timer.join()  # Ensure an old timer cannot interrupt a later query.

    def provider_index(self, goal: str, *, target: str, scope: PremiseScope, **budgets) -> tuple[PremiseIndex, dict]:
        """Bridge to the existing Arena provider API without bypassing its gates.

        The returned index is a bounded nomination set, not the full corpus.
        Keep the retrieval report alongside provider receipts for provenance.
        """
        report = self.search(goal, target=target, scope=scope, **budgets)
        return PremiseIndex(tuple(_premise(hit["premise"]) for hit in report["matches"]),
                            environment_sha256=scope.environment_sha256,
                            signatures=tuple(PremiseSignature.from_dict(hit["signature"])
                                             for hit in report["matches"] if hit["signature"] is not None)), report
