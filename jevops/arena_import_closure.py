"""Pinned native import inventory for smaller, scope-bound sandbox inputs.

No proof proposals, downloads, builds, cleanup, provider calls or promotion.
Discovery runs trusted project prefixes on the host, NOT untrusted candidates.
The caller owns the shared preparation lock and the existing storage guard.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

from .arena import content_hash, source_hash
from .arena_isolation import capture_process
from .arena_lean import DRIVER, MAX_PREFIX, ProjectBinding
from .arena_providers import strict_json
from .arena_staging import selected_metadata, reservation
from .seals import Fingerprinter

SCHEMA = "jevops-import-closure-plan/v1"
NATIVE_SCHEMA = "jevops-native-import-closure/v1"
MARKER = "JEVOPS_IMPORT_CLOSURE:"
EXPORTER = Path(__file__).with_name("lean") / "ArenaImportClosure.lean"
SUPPORTED_TAGS = frozenset({"v4.27.0", "v4.29.1"})
MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")


def driver_source():
    source, tail = DRIVER.read_text(), EXPORTER.read_text()
    boundary = "\nend JevOpsArena\n"
    if source.count(boundary) != 1 or not tail.startswith("import Lean\n"):
        raise ValueError("unsupported trusted closure library layout")
    return source.split(boundary)[0] + boundary + tail.removeprefix("import Lean\n")


def select_modules(binding, modules):
    """Validate native resolution against pinned Lean's root-prefix search.

    Return only external module families; the compiler library is already
    mounted read-only. Unsupported names/paths fail closed, never approximated.
    """
    if type(modules) is not list or not 1 <= len(modules) <= 4096:
        raise ValueError("bounded native module inventory required")
    library = (binding.lean.resolve(strict=True).parent.parent / "lib/lean").resolve(strict=True)
    roots = (*binding.search_paths, library)
    selection, seen = [set() for _ in binding.search_paths], set()
    for row in modules:
        if (type(row) is not dict or set(row) != {"name", "olean"} or
                type(row["name"]) is not str or len(row["name"]) > 512 or
                not MODULE_NAME.fullmatch(row["name"]) or row["name"] in seen or
                type(row["olean"]) is not str or len(row["olean"]) > 4096):
            raise ValueError("unique supported module names and bounded native paths required")
        seen.add(row["name"])
        parts = row["name"].split(".")
        relative = "/".join(parts) + ".olean"
        # findWithExt chooses the first ROOT PACKAGE, not the first matching
        # file. Falling through on a missing submodule would change semantics.
        index = next((i for i, root in enumerate(roots) if (root / parts[0]).is_dir()
                      or (root / (parts[0] + ".olean")).exists()), None)
        if index is None: raise ValueError("module has no pinned import root")
        expected = roots[index] / relative
        observed = Path(row["olean"])
        if not expected.is_file() or not observed.is_absolute() or observed.resolve(strict=True) != expected.resolve(strict=True):
            raise ValueError("native module path differs from pinned search order")
        if index < len(selection):
            selection[index].add(relative)
    selected = tuple(tuple(sorted(group)) for group in selection)
    if not any(selected): raise ValueError("no external imports to stage")
    return selected


class ImportClosureDiscovery:
    """Single-owner, no-retry native inventory; no calls unless budgeted.

    Injected runners are fixtures, never native evidence. No output from this
    class, including a real inventory, is a proof-verification receipt.
    """
    def __init__(self, binding, *, max_processes=0, timeout=90, runner=None, scratch_parent=None):
        if type(binding) is not ProjectBinding or binding.staged_imports is not None:
            raise ValueError("original unstaged native binding required")
        if binding.pin.lean_tag not in SUPPORTED_TAGS:
            raise ValueError("unsupported pinned artifact layout")
        if type(max_processes) is not int or not 0 <= max_processes <= 4:
            raise ValueError("bounded explicit native discovery budget required")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("bounded discovery timeout")
        if len(binding.prefix.encode()) > MAX_PREFIX: raise ValueError("prefix byte budget")
        if runner is not None and not callable(runner): raise ValueError("fixture runner must be callable")
        self.binding, self.max_processes, self.timeout = binding, max_processes, timeout
        self.runner, self.scratch_parent = runner, scratch_parent
        self.attempts, self.reader = 0, Fingerprinter()

    def discover(self, target):
        if not isinstance(target, str) or len(target) > 512 or not MODULE_NAME.fullmatch(target):
            raise ValueError("explicit supported target name required")
        if self.attempts >= self.max_processes: raise ValueError("native discovery budget exhausted")
        source = driver_source()
        scope = self.binding.fingerprint(self.reader)
        request = {"prefix": self.binding.prefix, "target": target,
                   "request_sha256": content_hash({"scope": scope, "target": target, "driver": source_hash(source)})}
        self.attempts += 1  # Includes failed, unavailable and interrupted attempts.
        if self.runner is not None:
            value = self.runner(request)
        else:
            with tempfile.TemporaryDirectory(prefix="jevops-import-closure-", dir=self.scratch_parent) as scratch:
                driver = Path(scratch) / "ArenaImportClosure.lean"
                driver.write_text(source)
                with tempfile.TemporaryFile(dir=scratch) as stream:
                    stream.write(json.dumps(request).encode()); stream.seek(0)
                    out, err, code = capture_process([str(self.binding.lean), "--run", str(driver)],
                        stdin=stream, cwd=scratch, timeout=self.timeout, output_limit=2_097_152,
                        env={"PATH": str(self.binding.lean.parent) + ":/usr/bin:/bin", "HOME": scratch,
                             "TMPDIR": scratch, "LEAN_NUM_THREADS": "1",
                             "LEAN_PATH": os.pathsep.join(map(str, self.binding.search_paths))})
                if code: raise ValueError("native import discovery failed: " + (err + out).decode(errors="replace")[:1000])
                lines = [line[len(MARKER):] for line in out.decode().splitlines() if line.startswith(MARKER)]
                if len(lines) != 1: raise ValueError("exactly one native import inventory required")
                value = strict_json(lines[0], limit=2_097_152)
        if (type(value) is not dict or set(value) != {"schema", "request_sha256", "lean_version", "lean_githash", "modules"}
                or value["schema"] != NATIVE_SCHEMA or value["request_sha256"] != request["request_sha256"]
                or value["lean_version"] != self.binding.pin.lean_tag.removeprefix("v")
                or not isinstance(value["lean_githash"], str) or not re.fullmatch("[0-9a-f]{40}", value["lean_githash"])):
            raise ValueError("native import envelope mismatch")
        selection = select_modules(self.binding, value["modules"])
        entries = selected_metadata(self.binding.search_paths, selection, deadline=time.monotonic() + self.timeout)
        if self.binding.fingerprint(self.reader) != scope or driver_source() != source:
            raise ValueError("discovery context changed")
        return {"schema": SCHEMA, "evidence_mode": "fixture" if self.runner else "trusted_native_inventory",
            "scope_sha256": scope, "target": target, "pin": self.binding.pin.to_dict(),
            "selection": selection, "source_paths": list(map(str, self.binding.search_paths)),
            "native_inventory": value, "driver_sha256": source_hash(source),
            "attempts": self.attempts, "native_processes": 0 if self.runner else self.attempts,
            "selected_modules": sum(map(len, selection)), "files": sum(e["kind"] == "file" for e in entries),
            "payload_bytes": sum(e.get("bytes", 0) for e in entries), "required_reservation_bytes": reservation(entries),
            "proofs_verified": 0, "promotion": False}
