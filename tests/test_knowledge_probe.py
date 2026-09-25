import json

import pytest

pytest.importorskip("duckdb")
from jevops.knowledge_probe import compare_ingestion, main, measure

pytestmark = pytest.mark.no_seal(reason="actual DuckDB artifact and elapsed-time probe")


def test_probe_generates_measurements_without_proof_claims(tmp_path):
    assert main(["--output", str(tmp_path / "probe"), "--records", "3", "--queries", "2"]) == 0
    report = json.loads((tmp_path / "probe/report.json").read_text())
    row = report["results"][0]
    assert row["status"] == "PASS" and row["synthetic"]
    assert not row["proof_verified"] and row["official_score"] is None
    assert row["build_seconds"] > 0 and row["artifact"]["size_bytes"] > 0
    assert len(row["query_ms"]) == 2
    assert row["broad_query_status"] == "RANKED"
    with pytest.raises(FileExistsError):
        main(["--output", str(tmp_path / "probe"), "--records", "3"])


def test_probe_exercises_multi_batch_build_and_exhaustion(tmp_path):
    report = measure(tmp_path, records=65, queries=2)
    assert report["status"] == "PASS"
    assert report["broad_query_status"] == "SCAN_BUDGET"
    assert report["records"] == 65


def test_comparison_repeats_both_modes_with_semantic_parity(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from jevops import knowledge_probe as module
    # Disk preflight policy is tested separately; don't require host free space.
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=2**40))
    assert main(["--output", str(tmp_path / "comparison"), "--records", "3", "--queries", "2",
                 "--compare-ingestion", "--rounds", "2"]) == 0
    payload = json.loads((tmp_path / "comparison/report.json").read_text())
    result = payload["results"][0]
    assert result["status"] == "PASS" and result["complete"] and result["semantic_parity"]
    assert [r["ingestion_mode"] for r in result["runs"]] == ["executemany", "columnar", "columnar", "executemany"]
    assert result["columnar_build_speedup"] > 0  # No flaky speed threshold in correctness tests.
    assert not result["proof_verified"] and result["official_score"] is None
    assert len(list((tmp_path / "comparison").rglob("*.duckdb"))) == 4
    with pytest.raises(FileExistsError):
        compare_ingestion(tmp_path / "comparison", records=3)


def test_comparison_storage_stop_never_deletes_or_measures(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from jevops import knowledge_probe as module
    marker = tmp_path / "existing-cache"
    marker.write_text("retain")
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    def forbidden(*args, **kwargs):
        raise AssertionError("must stop before building")
    monkeypatch.setattr(module, "measure", forbidden)
    assert main(["--output", str(tmp_path / "stopped"), "--records", "3", "4", "--compare-ingestion"]) == 1
    payload = json.loads((tmp_path / "stopped/report.json").read_text())
    assert payload["status"] == "STORAGE_STOP" and len(payload["results"]) == 1
    assert payload["results"][0]["runs"] == []
    assert payload["results"][0]["columnar_build_speedup"] is None
    assert marker.read_text() == "retain"


@pytest.mark.parametrize("damage", ["error", "parity", "retrieval_failure"])
def test_bad_comparison_cannot_emit_speedup(tmp_path, monkeypatch, damage):
    from types import SimpleNamespace
    from jevops import knowledge_probe as module
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=2**40))
    def fixture_measure(directory, *, ingestion_mode, **kwargs):
        if damage == "error":
            raise RuntimeError("fixture insertion error")
        return {"status": "FAIL" if damage == "retrieval_failure" else "PASS",
                "ingestion_mode": ingestion_mode, "build_seconds": 1,
                "artifact": {"snapshot_sha256": "same"}, "retrieval_sha256": ingestion_mode}
    monkeypatch.setattr(module, "measure", fixture_measure)
    result = compare_ingestion(tmp_path / "failed", records=3, rounds=1)
    assert result["status"] == "FAIL" and result["columnar_build_speedup"] is None
    assert not result["semantic_parity"]
    assert list((tmp_path / "failed").glob("round-*/report.json"))
