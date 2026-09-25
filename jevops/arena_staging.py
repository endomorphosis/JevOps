"""Bounded read-only import copies, not build receipts or proof authority.

The preparation runner owns the destination and reserves disk headroom before
calling the writer. The host/filesystem and source producer remain trusted;
read-only modes do not defend against a hostile host owner changing the files.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

SCHEMA = "jevops-arena-import-stage/v1"
SELECTED_SCHEMA = "jevops-arena-selected-import-stage/v1"
MAX_ENTRIES = 4096
MAX_BYTES = 128_000_000
MANIFEST_LIMIT = 1_048_576
ALLOCATION_UNIT = 65_536
MODULE_SUFFIXES = (".olean", ".olean.server", ".olean.private", ".ir")


def _check_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("import staging deadline")


def _root(path: Path) -> Path:
    if (not isinstance(path, Path) or not path.is_absolute() or len(path.parts) < 4
            or any(c in str(path) for c in ",\n\r\0")):
        raise ValueError("narrow absolute import directory required")
    if any(p.is_symlink() for p in (path, *path.parents)) or path.resolve(strict=True) != path:
        raise ValueError("import directory must not traverse symlinks")
    if not path.is_dir():
        raise ValueError("import directory required")
    return path


def _digest(path: Path, size: int, deadline: float, output=None) -> str:
    _check_time(deadline)
    result, count = hashlib.sha256(), 0
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != size:
            raise ValueError("import source changed")
        while chunk := source.read(min(65536, size - count + 1)):
            _check_time(deadline)
            count += len(chunk)
            if count > size:
                raise ValueError("import source grew")
            result.update(chunk)
            if output is not None:
                output.write(chunk)
        after = os.fstat(source.fileno())
    if (count != size or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError("import source changed")
    return result.hexdigest()


def metadata_inventory(roots: tuple[Path, ...], *, deadline: float,
                       readonly: bool = False) -> list[dict]:
    """Bounded membership/size inspection only; never content or proof authority.

    Oversize payloads are counted without opening files so callers can explain
    why a tree does not fit. Entry, path and time bounds still apply.
    """
    if not 1 <= len(roots) <= 64 or len(set(roots)) != len(roots):
        raise ValueError("one to 64 distinct import roots required")
    entries = []
    for index, root in enumerate(roots):
        _root(root)
        pending = [root]
        while pending:
            _check_time(deadline)
            path = pending.pop()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("only regular import files/directories; no symlinks or devices")
            relative = path.relative_to(root).as_posix()
            if len(relative.encode()) > 512 or len(path.relative_to(root).parts) > 32:
                raise ValueError("import path bound")
            directory = stat.S_ISDIR(info.st_mode)
            if readonly and stat.S_IMODE(info.st_mode) != (0o555 if directory else 0o444):
                raise ValueError("staged imports must remain read-only and non-root-readable")
            if readonly and not directory and info.st_nlink != 1:
                raise ValueError("staged imports must not share hardlinks")
            entry = {"root": index, "path": relative, "kind": "directory" if directory else "file"}
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                raise ValueError("import entry budget")
            if directory:
                # Never materialize an unbounded scandir before checking capacity.
                with os.scandir(path) as children:
                    for child in children:
                        pending.append(Path(child.path))
                        if len(pending) + len(entries) > MAX_ENTRIES:
                            raise ValueError("import entry budget")
            else:
                entry.update(bytes=info.st_size)
    return sorted(entries, key=lambda e: (e["root"], e["path"]))


def selected_metadata(roots: tuple[Path, ...], selection, *, deadline: float) -> list[dict]:
    """Select complete compiled module families; preserve root-prefix blockers.

    All source membership is inspected (including symlinks), but no payload is
    read. Empty package directories prevent Lean's root-prefix search from
    falling through to a later root when an unselected module is requested.
    Selection is a bounded tuple of tuples of relative .olean paths, not globs.
    """
    if (type(selection) is not tuple or len(selection) != len(roots)
            or any(type(group) is not tuple for group in selection)
            or not 1 <= sum(map(len, selection)) <= MAX_ENTRIES):
        raise ValueError("bounded per-root module selection required")
    all_entries = metadata_inventory(roots, deadline=deadline)
    source = {(e["root"], e["path"]): e for e in all_entries}
    result = {(i, "."): source[i, "."] for i in range(len(roots))}
    packages = {}
    for e in all_entries:
        path = e["path"]
        if path == "." or "/" in path: continue
        package = path if e["kind"] == "directory" else path.removesuffix(".olean")
        if e["kind"] != "directory" and not path.endswith(".olean"): continue
        if not package: raise ValueError("empty module prefix")
        packages.setdefault(package, e["root"])
        # For a top-level A.olean without A/, the empty A/ directory is a
        # synthetic search blocker, NOT a substitute compiled module.
        result[e["root"], package] = {"root": e["root"], "path": package, "kind": "directory"}
    for index, group in enumerate(selection):
        if any(type(path) is not str for path in group):
            raise ValueError("canonical relative .olean path required")
        if len(set(group)) != len(group): raise ValueError("duplicate selected module")
        for path in group:
            if (not path.endswith(".olean") or "\\" in path or "\0" in path
                    or len(path.encode()) > 512 or path.startswith("/")
                    or any(p in ("", ".", "..") for p in path.split("/"))):
                raise ValueError("canonical relative .olean path required")
            package = path.split("/")[0].removesuffix(".olean")
            if packages.get(package) != index:
                raise ValueError("selected module changes import search precedence")
            base = path[:-len(".olean")]
            required = source.get((index, path))
            if required is None or required["kind"] != "file":
                raise ValueError("selected compiled module missing")
            # The supported pinned compilers use these artifacts. Do not
            # silently ignore a newer split IR layout.
            if (index, base + ".ir.sig") in source:
                raise ValueError("unsupported split IR layout")
            for suffix in MODULE_SUFFIXES:
                entry = source.get((index, base + suffix))
                if entry is None: continue
                if entry["kind"] != "file": raise ValueError("compiled artifact must be a file")
                result[index, entry["path"]] = entry
                for parent in Path(entry["path"]).parents:
                    key = (index, parent.as_posix())
                    result[key] = source[key]
    if len(result) > MAX_ENTRIES: raise ValueError("selected import entry budget")
    return sorted(result.values(), key=lambda e: (e["root"], e["path"]))


def inventory(roots: tuple[Path, ...], *, deadline: float, readonly: bool = False,
              selection=None) -> list[dict]:
    """Full directory membership and exact bytes, including empty directories."""
    if readonly and selection is not None: raise ValueError("inspect all staged membership")
    entries = (metadata_inventory(roots, deadline=deadline, readonly=readonly) if selection is None
               else selected_metadata(roots, selection, deadline=deadline))
    if sum(e.get("bytes", 0) for e in entries) > MAX_BYTES:
        raise ValueError("import byte budget")
    for entry in entries:
        if entry["kind"] == "file":
            entry["sha256"] = _digest(roots[entry["root"]] / entry["path"], entry["bytes"], deadline)
    return entries


def reservation(entries: list[dict]) -> int:
    # Conservative data/directory/dentry rounding plus bounded manifest space.
    return MANIFEST_LIMIT + 4 * ALLOCATION_UNIT + sum(
        ALLOCATION_UNIT * (1 + (e.get("bytes", 0) + ALLOCATION_UNIT - 1) // ALLOCATION_UNIT)
        for e in entries)


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _entries_valid(entries, roots: int) -> bool:
    if type(entries) is not list or not 1 <= len(entries) <= MAX_ENTRIES:
        return False
    for e in entries:
        if type(e) is not dict or e.get("kind") not in ("file", "directory"):
            return False
        fields = {"root", "path", "kind"} | ({"bytes", "sha256"} if e["kind"] == "file" else set())
        if (set(e) != fields or type(e["root"]) is not int or not 0 <= e["root"] < roots
                or type(e["path"]) is not str):
            return False
        if e["kind"] == "file" and (type(e["bytes"]) is not int or not 0 <= e["bytes"] <= MAX_BYTES
                or type(e["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", e["sha256"])):
            return False
    return True  # Paths/order/membership must additionally equal the fresh inventory.


@dataclass(frozen=True)
class StagedImports:
    manifest: Path
    manifest_sha256: str
    sources: tuple[Path, ...]
    scope_sha256: str | None = None

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self.manifest.parent / str(i) for i in range(len(self.sources)))

    def validate(self, *, deadline: float = float("inf")) -> None:
        _check_time(deadline)
        _root(self.manifest.parent)
        if (self.manifest.name != "manifest.json" or self.manifest.is_symlink()
                or self.manifest.stat().st_size > MANIFEST_LIMIT
                or stat.S_IMODE(self.manifest.stat().st_mode) != 0o444
                or stat.S_IMODE(self.manifest.parent.stat().st_mode) != 0o555):
            raise ValueError("invalid read-only import manifest")
        data = self.manifest.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.manifest_sha256:
            raise ValueError("import manifest changed")
        value = json.loads(data)
        selected = isinstance(value, dict) and value.get("schema") == SELECTED_SCHEMA
        fields = {"schema", "sources", "entries"} | ({"selection", "scope_sha256"} if selected else set())
        if (not isinstance(value, dict) or set(value) != fields
                or _encoded(value) != data or value["schema"] not in (SCHEMA, SELECTED_SCHEMA)
                or value["sources"] != list(map(str, self.sources))):
            raise ValueError("noncanonical or mismatched import manifest")
        selection = None
        if selected:
            if (not isinstance(self.scope_sha256, str) or not re.fullmatch("[0-9a-f]{64}", self.scope_sha256)
                    or value["scope_sha256"] != self.scope_sha256
                    or type(value["selection"]) is not list
                    or any(type(g) is not list for g in value["selection"])):
                raise ValueError("selected imports require matching original context scope")
            selection = tuple(tuple(g) for g in value["selection"])
        elif self.scope_sha256 is not None:
            raise ValueError("full-tree imports do not carry a selected scope")
        if not _entries_valid(value["entries"], len(self.sources)):
            raise ValueError("malformed typed import entries")
        expected_names = {"manifest.json", *map(str, range(len(self.sources)))}
        names = set()
        for p in self.manifest.parent.iterdir():
            names.add(p.name)
            if len(names) > len(expected_names):
                raise ValueError("unexpected staged input")
        if names != expected_names:
            raise ValueError("unexpected staged input")
        if inventory(self.sources, deadline=deadline, selection=selection) != value["entries"]:
            raise ValueError("original imports changed; restage in a new context")
        if inventory(self.paths, deadline=deadline, readonly=True) != value["entries"]:
            raise ValueError("staged imports changed")


def write_stage(destination: Path, sources: tuple[Path, ...], entries: list[dict], *, deadline: float,
                selection=None, scope_sha256=None) -> StagedImports:
    """Caller holds the preparation lock and has reserved `reservation(entries)`.

    No overwrites or hardlinks. On failure, incomplete owned copies remain for
    inspection, charged to preparation headroom; they have no valid manifest.
    """
    extra = {}
    if selection is not None:
        if not isinstance(scope_sha256, str) or not re.fullmatch("[0-9a-f]{64}", scope_sha256):
            raise ValueError("original context scope hash required")
        extra = {"selection": selection, "scope_sha256": scope_sha256}
    elif scope_sha256 is not None:
        raise ValueError("scope requires a selection")
    payload = _encoded({"schema": SELECTED_SCHEMA if selection is not None else SCHEMA,
                        "sources": list(map(str, sources)), "entries": entries, **extra})
    if len(payload) > MANIFEST_LIMIT:
        raise ValueError("import manifest byte budget")
    destination.mkdir(mode=0o700)
    directories = [destination]
    for e in entries:
        _check_time(deadline)
        target = destination / str(e["root"]) / e["path"]
        if e["kind"] == "directory":
            target.mkdir(mode=0o700)
            directories.append(target)
        else:
            with target.open("xb") as output:
                digest = _digest(sources[e["root"]] / e["path"], e["bytes"], deadline, output)
            target.chmod(0o444)
            if digest != e["sha256"]:
                raise ValueError("import source changed during copy")
    # Do not publish a copy from a partially changed source tree.
    if inventory(sources, deadline=deadline, selection=selection) != entries:
        raise ValueError("import source membership/content changed during copy")
    manifest = destination / "manifest.json"
    with manifest.open("xb") as stream:
        stream.write(payload)
    manifest.chmod(0o444)
    for directory in reversed(directories):
        directory.chmod(0o555)
    result = StagedImports(manifest, hashlib.sha256(payload).hexdigest(), sources, scope_sha256)
    result.validate(deadline=deadline)
    return result
