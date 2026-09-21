"""Read-only historical proof seeds for the Lean refactor campaign.

Historical keep-bests are useful teacher proposals, but their old compiler
environment is not evidence for the current run.  This module therefore does
only two things: read bodies from a pinned parent-repository commit and attach
content-addressed provenance.  Callers must still send every body through the
current theorem/Lake gate before admitting it or training on it.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import _jevops_path  # noqa: F401


HISTORY_COMMIT = "5eecbf7b7e6566a7de02f52467f88c5761683313"
HISTORY_RELROOT = "papers/completion/lean_refactor_arena/evidence/canaries"
SEED_SCHEMA = "lra-historical-seed/v1"
_SEED_FILE = re.compile(r"^random-best-(?P<name>.+)-(?P<tokens>[0-9]+)\.lean$")


def _digest(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _run_git(root: Path, args: Sequence[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    """Run a read-only Git query without invoking a shell."""

    return subprocess.run(
        ["git", "-C", str(root), *[str(item) for item in args]],
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout)),
        check=False,
    )


def _usable_root(root: Path, commit: str) -> bool:
    try:
        result = _run_git(root, ["cat-file", "-e", f"{commit}^{{commit}}"])
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def find_history_root(*, commit: str = HISTORY_COMMIT, preferred: Optional[Path] = None) -> Optional[Path]:
    """Find the parent ``lift_coding`` checkout containing the pinned commit."""

    candidates: list[Path] = []
    if preferred is not None:
        candidates.append(Path(preferred).expanduser().resolve())
    configured = str(os.environ.get("LRA_HISTORY_GIT_ROOT") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser().resolve())
    # The Arena is nested in JevOps, which is itself nested in the historical
    # lift_coding checkout.  Include ancestors so CI can use a different
    # absolute workspace without changing this module.
    here = Path(__file__).resolve()
    candidates.extend(path for path in here.parents if path not in candidates)
    candidates.extend(
        path
        for path in (_jevops_path.JEVOPS_ROOT, _jevops_path.JEVOPS_ROOT.parent)
        if path not in candidates
    )
    seen: set[Path] = set()
    for root in candidates:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        if _usable_root(root, commit):
            return root
    return None


def _history_paths(root: Path, *, commit: str, theorem: str) -> list[tuple[str, int]]:
    try:
        listed = _run_git(root, ["ls-tree", "-r", "--name-only", commit, "--", HISTORY_RELROOT])
    except (OSError, subprocess.TimeoutExpired):
        return []
    if listed.returncode != 0:
        return []
    prefix = f"{HISTORY_RELROOT}/random-best-{theorem}-"
    rows: list[tuple[str, int]] = []
    for path in listed.stdout.splitlines():
        if not path.startswith(prefix):
            continue
        match = _SEED_FILE.match(path.rsplit("/", 1)[-1])
        if match is None or match.group("name") != theorem:
            continue
        rows.append((path, int(match.group("tokens"))))
    return sorted(rows, key=lambda row: (row[1], row[0]))


def load_historical_seeds(
    theorem: str,
    *,
    root: Optional[Path] = None,
    commit: str = HISTORY_COMMIT,
    token_fn: Optional[Callable[[str], int]] = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Load the shortest pinned historical bodies for one theorem.

    The returned rows are explicitly ``unverified``.  The filename token
    count is a claim retained for comparison only; ``actual_tokens`` is a
    local diagnostic and neither value admits the candidate.
    """

    name = str(theorem or "").strip()
    if not name:
        return []
    history_root = root or find_history_root(commit=commit)
    if history_root is None:
        return []
    rows: list[dict[str, Any]] = []
    for path, claimed_tokens in _history_paths(history_root, commit=commit, theorem=name)[: max(1, int(limit))]:
        try:
            shown = _run_git(history_root, ["show", f"{commit}:{path}"])
        except (OSError, subprocess.TimeoutExpired):
            continue
        if shown.returncode != 0 or not shown.stdout.strip():
            continue
        body = shown.stdout.strip("\n")
        if token_fn is not None:
            try:
                actual_tokens = int(token_fn(body))
            except Exception:
                actual_tokens = len(body.split())
        else:
            actual_tokens = len(body.split())
        rows.append(
            {
                "schema": SEED_SCHEMA,
                "name": name,
                "body": body,
                "source": "lift_coding_git_history",
                "provenance": "git_history",
                "history_root": str(history_root),
                "commit": commit,
                "path": path,
                "claimed_tokens": int(claimed_tokens),
                "actual_tokens": int(actual_tokens),
                "body_digest": _digest(body),
                # These fields are deliberately false until the current
                # compiler callback records a successful admission.
                "admission": "unverified",
                "lake_verified": False,
                "training_eligible": False,
            }
        )
    return rows


def load_historical_catalog(
    records: Sequence[Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
    commit: str = HISTORY_COMMIT,
    token_fn: Optional[Callable[[str], int]] = None,
    limit: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    """Load a bounded, theorem-keyed historical seed catalog."""

    catalog: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        name = str(record.get("name") or "").strip()
        if not name or name in catalog:
            continue
        seeds = load_historical_seeds(
            name,
            root=root,
            commit=commit,
            token_fn=token_fn,
            limit=limit,
        )
        if seeds:
            catalog[name] = seeds
    return catalog


def catalog_manifest(catalog: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Return persistence-safe metadata without copying proof bodies."""

    return {
        str(name): [
            {
                key: row.get(key)
                for key in (
                    "schema",
                    "name",
                    "source",
                    "provenance",
                    "commit",
                    "path",
                    "claimed_tokens",
                    "actual_tokens",
                    "body_digest",
                    "admission",
                    "lake_verified",
                    "training_eligible",
                )
                if key in row
            }
            for row in list(rows)[:8]
            if isinstance(row, Mapping)
        ]
        for name, rows in catalog.items()
    }


def seed_rows_for(memory: Optional[Mapping[str, Any]], theorem: str) -> list[dict[str, Any]]:
    """Read untrusted seed rows from live memory without admitting them."""

    if not isinstance(memory, Mapping):
        return []
    catalog = ((memory.get("nca") or {}).get("historical_seed_candidates") or {})
    rows = catalog.get(str(theorem or "")) if isinstance(catalog, Mapping) else None
    return [dict(row) for row in list(rows or ()) if isinstance(row, Mapping) and str(row.get("body") or "").strip()]


def record_seed_outcome(
    memory: Optional[dict[str, Any]],
    theorem: str,
    body_digest: str,
    *,
    lake_ok: bool,
    tokens: int = 0,
) -> None:
    """Update seed provenance after a current-run compiler attempt."""

    if not isinstance(memory, dict):
        return
    catalog = ((memory.get("nca") or {}).get("historical_seed_candidates") or {})
    rows = catalog.get(str(theorem or "")) if isinstance(catalog, dict) else None
    for row in list(rows or ()):
        if not isinstance(row, dict) or str(row.get("body_digest") or "") != str(body_digest or ""):
            continue
        row["last_lake_ok"] = bool(lake_ok)
        row["last_tokens"] = max(0, int(tokens or 0))
        if lake_ok:
            row["admission"] = "verified"
            row["lake_verified"] = True
            row["training_eligible"] = True
