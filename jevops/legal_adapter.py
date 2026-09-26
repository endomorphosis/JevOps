"""Explicit, single-owner legal backend binding; no imports of a sibling tree.

The manifest pins declared files, not loaded bytecode or a transitive dependency
closure. Callbacks are trusted dependencies. This is not an execution sandbox,
verification receipt, transaction manager, or semantic review of legal prose.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
from typing import Any, Callable, Protocol

from .statement_lock import lock_statement


MANIFEST_SCHEMA = "jevops-legal-adapter-sources/v1"
MAX_FILES = 128
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class AdapterError(RuntimeError):
    """A required adapter operation failed; never retry via ambient globals."""


def _relative_path(value: str) -> str:
    if (type(value) is not str or not value or len(value) > 1024
            or "\\" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("invalid manifest path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError("manifest paths must be canonical relative paths")
    return value


@dataclass(frozen=True)
class FileDigest:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _relative_path(self.path)
        if type(self.size) is not int or not 0 <= self.size <= MAX_FILE_BYTES:
            raise ValueError("invalid manifest file size")
        if type(self.sha256) is not str or not _SHA256.fullmatch(self.sha256):
            raise ValueError("invalid SHA-256 content hash")


def _regular_path(root: Path, relative: str) -> Path:
    """Reject symlinks in root ancestors and the declared path, not just its leaf."""
    if not root.is_absolute():
        raise ValueError("source root must be absolute")
    target = root / _relative_path(relative)
    for parent in reversed(target.parents):
        mode = parent.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise ValueError("source ancestor is not a real directory")
    if not stat.S_ISREG(target.lstat().st_mode):
        raise ValueError("source is not a regular file")
    return target


def _digest_file(root: Path, relative: str, *, limit: int) -> FileDigest:
    target = _regular_path(root, relative)
    before = target.stat()
    if before.st_size > limit:
        raise ValueError("source byte limit exceeded")
    # O_NOFOLLOW protects the leaf; the parent checks are not a hostile-race sandbox.
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("source changed during open")
        digest = hashlib.sha256()
        size = 0
        while block := stream.read(min(65536, limit - size + 1)):
            size += len(block)
            if size > limit:
                raise ValueError("source byte limit exceeded")
            digest.update(block)
        after = os.fstat(stream.fileno())
    current = _regular_path(root, relative).stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if identity(opened) != identity(after) or identity(after) != identity(current):
        raise ValueError("source changed during read")
    return FileDigest(relative, size, digest.hexdigest())


@dataclass(frozen=True)
class SourceManifest:
    implementation_id: str
    files: tuple[FileDigest, ...]

    def __post_init__(self) -> None:
        if type(self.implementation_id) is not str or not 1 <= len(self.implementation_id) <= 256:
            raise ValueError("implementation_id required (at most 256 characters)")
        if type(self.files) is not tuple or not 1 <= len(self.files) <= MAX_FILES:
            raise ValueError("bounded nonempty tuple of source files required")
        if any(type(f) is not FileDigest for f in self.files):
            raise ValueError("FileDigest records required")
        paths = [f.path for f in self.files]
        if paths != sorted(set(paths)):
            raise ValueError("manifest paths must be unique and sorted")
        if sum(f.size for f in self.files) > MAX_TOTAL_BYTES:
            raise ValueError("manifest total byte limit exceeded")

    def as_dict(self) -> dict[str, Any]:
        return {"schema": MANIFEST_SCHEMA, "implementation_id": self.implementation_id,
                "files": [{"path": f.path, "size": f.size, "sha256": f.sha256} for f in self.files]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SourceManifest:
        if (type(value) is not dict or set(value) != {"schema", "implementation_id", "files"}
                or value["schema"] != MANIFEST_SCHEMA or type(value["files"]) is not list
                or not 1 <= len(value["files"]) <= MAX_FILES):
            raise ValueError("invalid source manifest")
        if any(type(row) is not dict or set(row) != {"path", "size", "sha256"} for row in value["files"]):
            raise ValueError("invalid source file record")
        return cls(value["implementation_id"], tuple(FileDigest(**row) for row in value["files"]))

    @property
    def content_sha256(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def capture(cls, root: Path, paths: tuple[str, ...], *, implementation_id: str) -> SourceManifest:
        """Enrollment by a trusted caller, NOT approval of whichever files exist."""
        if type(paths) is not tuple or not 1 <= len(paths) <= MAX_FILES:
            raise ValueError("bounded tuple of declared paths required")
        normalized = [_relative_path(p) for p in paths]
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate declared path")
        records = []
        remaining = MAX_TOTAL_BYTES
        for path in sorted(normalized):
            record = _digest_file(Path(root), path, limit=min(MAX_FILE_BYTES, remaining))
            records.append(record)
            remaining -= record.size
        return cls(implementation_id, tuple(records))

    def verify(self, root: Path) -> None:
        for record in self.files:
            if _digest_file(Path(root), record.path, limit=record.size) != record:
                raise ValueError("source content mismatch: " + record.path)


class LegalDocuments(Protocol):
    def obligations(self, document_id: str, clause_id: str) -> dict[str, Any]: ...
    def mark(self, document_id: str, clause_id: str, disposition: str, error: str = "") -> None: ...


class LegalSession(Protocol):
    documents: LegalDocuments

    def open_document(self, text: str, **kwargs: Any) -> dict[str, Any]: ...
    def clause_get(self, document_id: str, clause_id: str) -> dict[str, Any]: ...
    def compile_clause(self, document_id: str, clause_id: str, *, frame_id: str) -> dict[str, Any]: ...
    def decompile_rule(self, document_id: str, clause_id: str) -> dict[str, Any]: ...
    def rules_for_frame(self, frame_id: str) -> dict[str, Any]: ...
    def coverage(self, document_id: str) -> dict[str, Any]: ...


def _tool_identifier(value: Any) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 1024 or any(ord(c) < 32 for c in value):
        return False
    try:
        return len(value.encode("utf-8")) <= 1024
    except UnicodeError:
        return False


class PinnedLegalAdapter:
    """Caller-owned session, documents and callbacks; fail closed on drift/error.

    Sources are hashed before AND after every backend call. Calls must remain on
    the constructing process/thread. No backend rollback or cross-process lock is
    implied. Closing the adapter does not close/delete caller-owned resources.
    """

    def __init__(self, *, root: Path, manifest: SourceManifest, expected_sha256: str,
                 session: LegalSession, documents: LegalDocuments,
                 verifier: Callable[[str], dict[str, Any]] | None,
                 attestation_writer: Callable[..., dict[str, Any]] | None,
                 prompt_builder: Callable[[str], list[dict[str, str]]] | None = None):
        if (type(manifest) is not SourceManifest or type(expected_sha256) is not str
                or not _SHA256.fullmatch(expected_sha256) or expected_sha256 != manifest.content_sha256):
            raise ValueError("source manifest identity mismatch")
        if session.documents is not documents:
            raise ValueError("session and adapter must share the explicitly supplied documents")
        for callback in (verifier, attestation_writer, prompt_builder):
            if callback is not None and not callable(callback):
                raise ValueError("adapter dependencies must be callable or None")
        self._root = Path(root)
        self._manifest = manifest
        self._session = session
        self._documents = documents
        self._verifier = verifier
        self._writer = attestation_writer
        self._prompt_builder = prompt_builder
        self._owner = (os.getpid(), threading.get_ident())
        self._closed = self._busy = self._poisoned = False
        self._guard()

    @property
    def provenance(self) -> dict[str, Any]:
        return {"schema": MANIFEST_SCHEMA, "implementation_id": self._manifest.implementation_id,
                "source_manifest_sha256": self._manifest.content_sha256,
                "scope": "caller_declared_files", "verification_performed": False}

    def _ready(self) -> None:
        if self._owner != (os.getpid(), threading.get_ident()):
            raise AdapterError("adapter_wrong_owner")
        if self._closed or self._poisoned or self._busy:
            raise AdapterError("adapter_closed" if self._closed else
                               "adapter_poisoned" if self._poisoned else "adapter_reentrant_call")

    def _guard(self) -> None:
        try:
            if self._session.documents is not self._documents:
                raise ValueError("session document binding changed")
            self._manifest.verify(self._root)
        except Exception as exc:
            self._poisoned = True
            raise AdapterError("adapter_source_or_binding_drift") from exc

    def _call(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self._ready()
        self._guard()
        self._busy = True
        try:
            result = callback(*args, **kwargs)
            self._guard()
            return result
        except Exception as exc:
            self._poisoned = True
            if isinstance(exc, AdapterError):
                raise
            raise AdapterError("adapter_backend_failed") from exc
        finally:
            self._busy = False

    def close(self) -> None:
        if self._owner != (os.getpid(), threading.get_ident()) or self._busy:
            raise AdapterError("adapter_wrong_owner_or_busy")
        self._closed = True

    def open_document(self, text: str, **kwargs: Any) -> dict[str, Any]:
        return self._call(self._session.open_document, text, **kwargs)

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ready()
        fields = {"clause_get": ("document_id", "clause_id"),
                  "compile_clause": ("document_id", "clause_id"),
                  "decompile_rule": ("document_id", "clause_id"),
                  "rules_for_frame": ("frame_id",), "coverage": ("document_id",)}
        if name not in fields:
            return {"error": "unknown_tool", "name": name}
        required = fields[name]
        allowed = set(required) | ({"frame_id"} if name == "compile_clause" else set())
        if (type(arguments) is not dict or not set(required) <= set(arguments) <= allowed
                or any(not _tool_identifier(v) for v in arguments.values())):
            return {"error": "invalid_legal_tool_arguments"}
        kwargs = dict(arguments)
        if name == "compile_clause":
            kwargs.setdefault("frame_id", "unassigned")
        return self._call(getattr(self._session, name), **kwargs)

    def obligations(self, document_id: str, clause_id: str) -> dict[str, Any]:
        return self._call(self._documents.obligations, document_id, clause_id)

    def mark(self, document_id: str, clause_id: str, disposition: str, error: str = "") -> None:
        self._call(self._documents.mark, document_id, clause_id, disposition, error)

    def check_source(self, source: str) -> dict[str, Any]:
        self._ready()
        # This only enforces the restricted source profile. Admission additionally
        # compares against the trusted expected helpers/headers at its entry point.
        locked = lock_statement(source, source)
        if not locked["ok"]:
            return {"lake_ok": False, "error": locked["error"]}
        if self._verifier is None:
            return {"lake_ok": False, "error": "verifier_unavailable"}

        def verify() -> dict[str, Any]:
            result = self._verifier(str(locked["source"]))
            if (type(result) is not dict or type(result.get("lake_ok")) is not bool
                    or type(result.get("error")) is not str):
                raise ValueError("invalid verifier result (lake_ok must be a Boolean)")
            return dict(result)

        return self._call(verify)

    def store_attestation(self, **kwargs: Any) -> dict[str, Any]:
        self._ready()
        if self._writer is None:
            raise AdapterError("attestation_writer_unavailable")

        def write() -> dict[str, Any]:
            result = self._writer(**kwargs)
            if type(result) is not dict or type(result.get("indexed")) is not bool:
                raise ValueError("invalid attestation result (indexed must be a Boolean)")
            return dict(result)

        return self._call(write)

    def messages(self, text: str) -> list[dict[str, str]]:
        self._ready()
        if self._prompt_builder is None:
            raise AdapterError("prompt_builder_unavailable")
        return self._call(self._prompt_builder, text)
