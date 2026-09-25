from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "papers" / "completion" / "lean_refactor_arena" / "tools" / "check_corpus.py"


def _checker_module():
    spec = importlib.util.spec_from_file_location("jevops_lra_check_corpus", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_warmup_is_ready_as_the_complete_available_fixture() -> None:
    module = _checker_module()
    path = ROOT / "papers" / "completion" / "lean_refactor_arena" / "data" / "benchmark_data_warmup.jsonl"

    report = module.inspect_corpus(path)

    assert report["optimization_ready"] is True
    assert report["kind"] == "warmup"
    assert report["records"] == 15
    assert report["sha256"] == module.FROZEN_WARMUP_SHA256
    assert report["source_counts"] == {
        "arklib": 3,
        "cslib": 3,
        "physlib": 3,
        "putnambench": 3,
        "strata": 3,
    }


def test_full_requirement_fails_closed_until_a_larger_corpus_exists() -> None:
    module = _checker_module()
    path = ROOT / "papers" / "completion" / "lean_refactor_arena" / "data" / "benchmark_data_warmup.jsonl"

    report = module.inspect_corpus(path, require_full=True)

    assert report["optimization_ready"] is False
    assert any("full corpus is not available" in error for error in report["errors"])


def test_corpus_manifest_records_the_frozen_input_and_release_boundary() -> None:
    manifest_path = (
        ROOT
        / "papers"
        / "completion"
        / "lean_refactor_arena"
        / "data"
        / "corpus_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())

    assert manifest["corpus"]["records"] == 15
    assert manifest["corpus"]["optimization_ready"] is True
    assert manifest["full_benchmark"]["status"] == "not_released"
    assert manifest["full_benchmark"]["path"] is None


def test_empty_corpus_is_not_ready(tmp_path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("\n")
    report = _checker_module().inspect_corpus(path)
    assert report["records"] == 0
    assert report["optimization_ready"] is False
    assert "corpus must contain at least one record" in report["errors"]
