"""Local, content-addressed test evidence. A seal is not a proof certificate.

The dependency contract belongs to the caller. AST hashes are diagnostics;
only raw content hashes authorize reuse. No Python code is imported or run by
this module while inspecting source files or an existing manifest.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

SCHEMA = "jevops-test-seals/v1"
IGNORED_DIRECTORIES = frozenset({".git", ".pytest_cache", "__pycache__", ".venv",
                                 ".mypy_cache", ".ruff_cache", ".hypothesis"})


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def stable_value(value: Any) -> Any:
    """Type-preserving parameter serialization; never trust repr(object)."""
    if value is None or type(value) in (bool, int, str):
        return [type(value).__name__, value]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is bytes:
        return ["bytes", value.hex()]
    if type(value) in (list, tuple):
        return [type(value).__name__, [stable_value(v) for v in value]]
    if type(value) is dict:
        pairs = [[stable_value(k), stable_value(v)] for k, v in value.items()]
        return ["dict", sorted(pairs, key=lambda p: digest(p[0]))]
    raise ValueError(f"untracked parameter type: {type(value).__name__}")


def _signature(info: os.stat_result) -> list[int]:
    # ctime/inode catch atomic replacements and same-size/restored-mtime edits.
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


@dataclass(frozen=True)
class Snapshot:
    root: str
    ast_root: str
    leaves: dict[str, dict[str, str]]


class Fingerprinter:
    """Injectable filesystem reader with a persistent stat -> digest fast path.

    Stat reuse assumes an ordinary local filesystem and a trusted local cache.
    Whole-second ctime values disable stat reuse (notably fuse2fs). Use
    strict=True for other timestamp-unreliable filesystems. Readers still
    require stable inputs; this is not a concurrent filesystem snapshot.
    Directory membership is always rescanned; directories are never stat-cached.
    """

    def __init__(self, files: dict | None = None, *, strict: bool = False):
        self.files = files if files is not None else {}
        self.strict = strict
        self.reads = 0
        self.stat_hits = 0

    def _file(self, path: Path) -> dict[str, str]:
        before = _signature(path.stat())
        if not stat.S_ISREG(before[2]):
            raise ValueError(f"not a regular file: {path}")
        key = str(path)
        old = self.files.get(key, {})
        fine_ctime = before[5] % 1_000_000_000 != 0
        if (not self.strict and fine_ctime and isinstance(old, dict) and old.get("stat") == before
                and all(isinstance(old.get(k), str) for k in ("raw", "ast"))):
            self.stat_hits += 1
            return {"raw": old["raw"], "ast": old["ast"]}
        hasher = hashlib.sha256()
        source = bytearray() if path.suffix == ".py" and before[3] <= 4_194_304 else None
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1_048_576), b""):
                hasher.update(chunk)
                if source is not None:
                    source.extend(chunk)
        if before != _signature(path.stat()):
            raise ValueError(f"dependency changed while hashing: {path}")
        self.reads += 1
        raw = hasher.hexdigest()
        ast_hash = raw
        imports: list[str] = []
        if source is not None:
            try:
                tree = ast.parse(bytes(source), filename=key)
                ast_hash = digest(ast.dump(tree, annotate_fields=True, include_attributes=False))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(a.name for a in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imports.append("." * node.level + (node.module or ""))
            except (SyntaxError, ValueError, RecursionError):
                # Non-Python / unparsable files still have authoritative byte hashes.
                pass
        self.files[key] = {"stat": before, "raw": raw, "ast": ast_hash,
                           "imports": sorted(set(imports))}
        return {"raw": raw, "ast": ast_hash}

    def snapshot(self, paths: list[str | Path]) -> Snapshot:
        leaves: dict[str, dict[str, str]] = {}

        def walk(path: Path, ancestors: frozenset[Path]) -> None:
            key = str(path)
            if key in leaves:
                return
            try:
                info = path.lstat()
            except FileNotFoundError:
                leaves[key] = {"raw": digest("missing"), "ast": digest("missing")}
                return
            if stat.S_ISLNK(info.st_mode):
                target = path.resolve(strict=True)
                if target in ancestors:
                    raise ValueError(f"cyclic dependency symlink: {path}")
                value = digest(["symlink", os.readlink(path), str(target)])
                leaves[key] = {"raw": value, "ast": value}
                walk(target, ancestors | {target})
            elif stat.S_ISDIR(info.st_mode):
                value = digest("directory")
                leaves[key] = {"raw": value, "ast": value}
                for child in sorted(path.iterdir()):
                    if child.name in IGNORED_DIRECTORIES or child.suffix in {".pyc", ".pyo"}:
                        continue
                    walk(child, ancestors | {path.resolve()})
            elif stat.S_ISREG(info.st_mode):
                hashes = self._file(path)
                # Executable/read permission changes are observable inputs, too.
                leaves[key] = {k: digest(["file", stat.S_IMODE(info.st_mode), v])
                               for k, v in hashes.items()}
            else:
                raise ValueError(f"unsupported dependency kind: {path}")

        for entry in sorted({os.path.abspath(p) for p in paths}):
            walk(Path(entry), frozenset())
        return Snapshot(digest({p: h["raw"] for p, h in leaves.items()}),
                        digest({p: h["ast"] for p, h in leaves.items()}), leaves)


class SealStore:
    """Checksummed JSON, atomic replacement, nonblocking single-writer lock.

    This detects accidental corruption, not malicious rewriting. Never share
    this writable cache across a trust boundary or use it as Lean evidence.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "manifest.json"
        self.records: dict[str, dict] = {}
        self.files: dict[str, dict] = {}
        self._lock = None

    def acquire(self) -> None:
        import fcntl  # POSIX only: plugin falls back to execution elsewhere.

        self.directory.mkdir(parents=True, exist_ok=True)
        stream = (self.directory / "writer.lock").open("a+b")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise
        self._lock = stream
        try:
            envelope = json.loads(self.path.read_text())
            payload = envelope["payload"]
            if (envelope["sha256"] != digest(payload) or payload["schema"] != SCHEMA
                    or not isinstance(payload["records"], dict)
                    or not isinstance(payload["files"], dict)):
                return
            if not all(isinstance(r, dict) for r in payload["records"].values()):
                return
            self.records = payload["records"]
            self.files = payload["files"]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def save(self) -> None:
        if self._lock is None:
            raise RuntimeError("seal store is not locked")
        payload = {"schema": SCHEMA, "records": self.records, "files": self.files}
        encoded = json.dumps({"payload": payload, "sha256": digest(payload)}, sort_keys=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False,
                                             prefix="manifest-", suffix=".tmp") as stream:
                temp = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def close(self) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None


def seal_status(record: dict | None, fingerprint: str) -> str:
    if not record:
        return "unsealed"
    if record.get("fingerprint") != fingerprint:
        return "stale"
    if record.get("outcome") == "passed":
        return "sealed"
    if record.get("outcome") == "failed":
        return "failing"
    return "unsealed"
