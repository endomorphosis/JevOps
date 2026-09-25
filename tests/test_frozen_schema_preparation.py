"""The snapshot changes source identity, never the watcher's state or policy."""
from dataclasses import asdict
import importlib.util
import fcntl
from pathlib import Path
import pytest

from jevops.improvement_service import Config

TOOL = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/prepare_frozen_schema_pilot.py"
spec = importlib.util.spec_from_file_location("frozen_schema_preparation", TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_config_rebinding_preserves_all_other_fields():
    original = Config(runtime="/old/runtime", snapshot_sha256="a" * 64,
        state="/old/state", volume_config="/volume/config.json", development=("dev",), holdouts=("holdout",),
        elan_home="/old/elan", docker_socket="/old/socket", docker_image="image")
    copied = module.pilot_config(original, Path("/fresh/runtime"), "b" * 64)
    assert {k for k in asdict(original) if asdict(original)[k] != asdict(copied)[k]} == {"runtime", "snapshot_sha256"}
    assert original.runtime == "/old/runtime" and copied.state == original.state


def test_snapshot_includes_the_runner_tests_and_corpus_not_build_caches():
    assert "jevops" in module.INCLUDES and "tests" in module.INCLUDES
    assert f"{module.ARENA}/data/benchmark_data_warmup.jsonl" in module.INCLUDES
    assert all(not p.startswith((".lake", "space", "upstream")) for p in module.INCLUDES)
    assert all((module.REPO / p).exists() for p in module.INCLUDES)


def test_busy_lock_does_not_create_or_capture_anything(tmp_path, monkeypatch):
    original = Config(runtime="/old/runtime", snapshot_sha256="a" * 64,
        state="/old/state", volume_config=str(tmp_path / "volume.json"), development=("dev",), holdouts=("holdout",),
        elan_home="/old/elan", docker_socket="/old/socket", docker_image="image")
    monkeypatch.setattr(module.Config, "load", lambda _: original)
    monkeypatch.setattr(module, "storage_guard", lambda _: None)
    monkeypatch.setattr(module, "create_snapshot", lambda *a, **k: pytest.fail("locked"))
    with (tmp_path / "single-build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            module.prepare(tmp_path / "config.json", tmp_path / "new")
    assert not (tmp_path / "new").exists()
