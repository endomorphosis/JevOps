from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "papers" / "completion" / "lean_refactor_arena" / "upstream"


def test_vendored_lean_refactor_snapshot_has_provenance() -> None:
    manifest = json.loads((UPSTREAM / "VENDOR_MANIFEST.json").read_text())

    assert manifest["schema"] == "jevops-lean-refactor-upstream/v1"
    assert manifest["source"]["commit"] == "05f1dad9719979d1f2d82167fb7aeedf6b85233b"
    assert manifest["tracked_file_count"] == 353
    assert (UPSTREAM / "lean_refactor" / "cli.py").is_file()
    assert (UPSTREAM / "lean_refactor" / "planner_optimizer_framework.py").is_file()
    assert (UPSTREAM / "data_extraction" / "extract.sh").is_file()


def test_mathlib_remains_an_explicit_optional_gitlink() -> None:
    manifest = json.loads((UPSTREAM / "VENDOR_MANIFEST.json").read_text())
    mathlib = manifest["mathlib_submodule"]

    assert mathlib["path"] == "lean_refactor/mathlib4"
    assert mathlib["vendored"] is False
    assert not (UPSTREAM / "lean_refactor" / "mathlib4" / ".git").exists()


def test_vendored_arena_space_snapshot_has_ui_and_worker_boundary() -> None:
    space = ROOT / "papers" / "completion" / "lean_refactor_arena" / "space"
    manifest = json.loads((space / "VENDOR_MANIFEST.json").read_text())

    assert manifest["schema"] == "jevops-lean-refactor-arena-space/v1"
    assert manifest["source"]["commit"] == "6a1384b7e3127f5d556e727d5d53cc17b4acdb40"
    assert manifest["tracked_file_count"] == 24
    assert manifest["evaluation_worker_included"] is False
    assert (space / "app.py").is_file()
    assert (space / "benchmark.py").is_file()
    assert (space / "leaderboard.py").is_file()
