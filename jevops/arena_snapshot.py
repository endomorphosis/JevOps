"""Read-only experiment source copies; hashes establish identity, not proof.

Stdlib-only so creation/verification need not import the mutable JevOps package.
This isolates accidental workspace edits, not hostile users with filesystem
access. Python installations and prepared Lean dependencies are not copied;
the native verifier must still validate its own complete dependency contexts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys

SCHEMA = "jevops-arena-source-snapshot/v1"
MAX_FILES = 4096
MAX_BYTES = 64 * 1024 * 1024
MANIFEST = "snapshot.json"
IGNORED = {"__pycache__", ".pytest_cache", ".git"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or str(path) != value or ".." in path.parts
            or "\\" in value or value == "." or value == MANIFEST):
        raise ValueError("safe non-manifest relative path required")
    return value


def _files(root: Path, *, ignore_generated: bool = False) -> dict[str, Path]:
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(parent) / name
            if path.is_symlink():
                raise ValueError(f"symlinks are not captured: {path}")
        if ignore_generated:
            dirs[:] = [name for name in dirs if name not in IGNORED]
        for name in files:
            if ignore_generated and name.endswith((".pyc", ".pyo")):
                continue
            path = Path(parent) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("only regular files may be captured")
            result[path.relative_to(root).as_posix()] = path
            if len(result) > MAX_FILES:
                raise ValueError("snapshot file limit")
    return result


def _sources(repo: Path, includes: list[str], inputs: dict[str, Path]) -> dict[str, Path]:
    result = {}
    for relative in includes:
        relative = _relative(relative)
        path = repo / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p != repo.parent):
            raise ValueError("source symlink not allowed")
        if path.is_dir():
            entries = {f"{relative}/{name}": p for name, p in _files(path, ignore_generated=True).items()}
        elif path.is_file():
            entries = {relative: path}
        else:
            raise ValueError(f"missing snapshot input: {relative}")
        if result.keys() & entries.keys():
            raise ValueError("overlapping snapshot inputs")
        result.update(entries)
    for relative, path in inputs.items():
        relative = _relative(relative)
        if not relative.startswith("inputs/") or relative in result:
            raise ValueError("extra inputs require distinct inputs/ paths")
        if path.is_symlink() or not path.is_file():
            raise ValueError("extra input must be a regular non-symlink file")
        result[relative] = path.resolve()
    if not result or len(result) > MAX_FILES:
        raise ValueError("nonempty bounded file inventory required")
    return dict(sorted(result.items()))


def create_snapshot(repo: Path, output: Path, includes: list[str], inputs: dict[str, Path] | None = None) -> dict:
    repo, output = repo.resolve(strict=True), output.absolute()
    if not repo.is_dir() or output.exists() or output.is_symlink():
        raise ValueError("existing repository and new output directory required")
    if output.resolve().is_relative_to(repo):
        raise ValueError("snapshot must be outside the mutable repository")
    inputs = inputs or {}
    sources = _sources(repo, includes, inputs)
    payloads, total = {}, 0
    for name, path in sources.items():
        if path.stat().st_size > MAX_BYTES - total:
            raise ValueError("snapshot byte limit")
        # Bounded even if an input grows between stat and read.
        with path.open("rb") as stream:
            value = stream.read(MAX_BYTES - total + 1)
        total += len(value)
        if total > MAX_BYTES:
            raise ValueError("snapshot byte limit")
        payloads[name] = value
    # Observe inventory and bytes twice. Not an atomic filesystem transaction;
    # the resulting independent copy is the experiment's explicit input state.
    if sources != _sources(repo, includes, inputs):
        raise ValueError("source inventory changed during capture")
    for name, path in sources.items():
        with path.open("rb") as stream:
            value = stream.read(len(payloads[name]) + 1)
        if value != payloads[name]:
            raise ValueError(f"source changed during capture: {name}")
    files = {name: {"sha256": _digest(value), "bytes": len(value)} for name, value in payloads.items()}
    manifest = {"schema": SCHEMA, "source_root": str(repo), "includes": includes,
        "input_origins": {name: str(path.resolve()) for name, path in inputs.items()},
        "created_at": datetime.now(timezone.utc).isoformat(), "files": files,
        "file_count": len(files), "bytes": total, "content_root": _digest(_encoded(files)),
        "python": {"executable": str(Path(sys.executable).resolve()), "version": sys.version},
        "proof_verified": False, "os_sandbox": False, "dependencies_copied": False}
    encoded = _encoded(manifest)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in payloads.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(value)
        path.chmod(0o444)
    with (output / MANIFEST).open("xb") as stream:
        stream.write(encoded)
    (output / MANIFEST).chmod(0o444)
    for parent, _, _ in os.walk(output, topdown=False):
        Path(parent).chmod(0o555)
    return {"schema": SCHEMA, "status": "CREATED", "root": str(output),
        "manifest_sha256": _digest(encoded), "content_root": manifest["content_root"],
        "file_count": len(files), "bytes": total, "proof_verified": False}


def verify_snapshot(root: Path, expected_manifest_sha256: str) -> dict:
    if (len(expected_manifest_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_manifest_sha256)
            or root.is_symlink() or not root.is_dir()):
        raise ValueError("snapshot directory and externally retained manifest SHA-256 required")
    inventory = _files(root)
    with inventory.pop(MANIFEST).open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or _digest(raw) != expected_manifest_sha256:
        raise ValueError("snapshot manifest changed")
    manifest = json.loads(raw)
    if manifest["schema"] != SCHEMA or manifest["content_root"] != _digest(_encoded(manifest["files"])):
        raise ValueError("snapshot schema/root mismatch")
    files = manifest["files"]
    if set(files) != set(inventory) or len(files) != manifest["file_count"]:
        raise ValueError("snapshot inventory changed")
    total = 0
    for name, expected in files.items():
        _relative(name)
        path = inventory[name]
        if path.stat().st_size != expected["bytes"] or expected["bytes"] > MAX_BYTES - total:
            raise ValueError(f"snapshot file size changed: {name}")
        with path.open("rb") as stream:
            value = stream.read(expected["bytes"] + 1)
        total += len(value)
        if len(value) != expected["bytes"] or _digest(value) != expected["sha256"]:
            raise ValueError(f"snapshot file changed: {name}")
    if total != manifest["bytes"]:
        raise ValueError("snapshot byte accounting mismatch")
    for path in [root, *root.rglob("*")]:
        if path.stat().st_mode & 0o222:
            raise ValueError(f"snapshot became writable: {path.relative_to(root)}")
    return {"schema": SCHEMA, "status": "UNCHANGED", "root": str(root.absolute()),
        "manifest_sha256": expected_manifest_sha256, "content_root": manifest["content_root"],
        "file_count": len(files), "bytes": total, "proof_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    create = modes.add_parser("create")
    create.add_argument("--repo", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--include", action="append", required=True)
    create.add_argument("--input", action="append", default=[], help="inputs/name=external-file")
    verify = modes.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.mode == "create":
            pairs = [entry.split("=", 1) for entry in args.input]
            if any(len(pair) != 2 for pair in pairs) or len({pair[0] for pair in pairs}) != len(pairs):
                raise ValueError("unique input mappings required")
            result = create_snapshot(args.repo, args.output_dir, args.include, {k: Path(v) for k, v in pairs})
        else:
            result = verify_snapshot(args.root, args.manifest_sha256)
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc), "proof_verified": False}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
