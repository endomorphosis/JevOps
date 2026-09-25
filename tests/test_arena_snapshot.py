"""Source snapshot integrity is not a cached proof or timing measurement."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from jevops import arena_snapshot as snapshot


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "repo"
    (root / "jevops").mkdir(parents=True)
    (root / "jevops" / "__init__.py").write_text("")
    (root / "jevops" / "worker.py").write_text("VALUE = 'captured'\n")
    return root


def capture(project):
    return snapshot.create_snapshot(project, project.parent / "snapshot", ["jevops"])


def check(receipt):
    return snapshot.verify_snapshot(Path(receipt["root"]), receipt["manifest_sha256"])


def test_workspace_edits_do_not_change_the_captured_source(project):
    receipt = capture(project)
    (project / "jevops" / "worker.py").write_text("VALUE = 'later'\n")
    assert check(receipt)["status"] == "UNCHANGED"
    assert check(receipt)["proof_verified"] is False
    assert (Path(receipt["root"]) / "jevops/worker.py").read_text() == "VALUE = 'captured'\n"
    assert receipt["file_count"] == 2


def test_isolated_interpreter_imports_snapshot_not_mutable_workspace(project):
    receipt = capture(project)
    (project / "jevops" / "worker.py").write_text("raise RuntimeError('mutable code imported')\n")
    script = "import sys; sys.path.insert(0, sys.argv[1]); from jevops.worker import VALUE; print(VALUE)"
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, receipt["root"]], cwd=project,
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "captured"
    assert check(receipt)["status"] == "UNCHANGED"


@pytest.mark.parametrize("change", ["bytes", "size", "new_file", "removed_file", "manifest", "writable", "symlink"])
def test_snapshot_changes_are_rejected(project, change):
    receipt = capture(project)
    root = Path(receipt["root"])
    worker = root / "jevops/worker.py"
    if change == "bytes":
        worker.chmod(0o644); worker.write_text("VALUE = 'tampered'\n"); worker.chmod(0o444)
    elif change == "size":
        worker.chmod(0o644); worker.write_text("different size\n"); worker.chmod(0o444)
    elif change == "new_file":
        root.chmod(0o755); (root / "extra.py").write_text("hidden code"); root.chmod(0o555)
    elif change == "removed_file":
        worker.parent.chmod(0o755); worker.unlink(); worker.parent.chmod(0o555)
    elif change == "manifest":
        manifest = root / snapshot.MANIFEST
        manifest.chmod(0o644); manifest.write_text("{}"); manifest.chmod(0o444)
    elif change == "writable":
        worker.chmod(0o644)
    else:
        worker.parent.chmod(0o755); worker.unlink(); worker.symlink_to(project / "jevops/worker.py")
    with pytest.raises((ValueError, KeyError)):
        check(receipt)


def test_generated_bytecode_is_not_captured(project):
    cache = project / "jevops/__pycache__"
    cache.mkdir(); (cache / "worker.cpython-314.pyc").write_bytes(b"stale compiled module")
    receipt = capture(project)
    assert receipt["file_count"] == 2
    assert not (Path(receipt["root"]) / "jevops/__pycache__").exists()


@pytest.mark.parametrize("relative", ["../outside", "/abs", "./jevops", "jevops/../jevops", "snapshot.json"])
def test_unsafe_paths_are_rejected_before_creating_anything(project, relative):
    out = project.parent / "bad"
    with pytest.raises(ValueError):
        snapshot.create_snapshot(project, out, [relative])
    assert not out.exists()


def test_overlap_and_in_workspace_outputs_are_rejected(project):
    with pytest.raises(ValueError, match="overlapping"):
        snapshot.create_snapshot(project, project.parent / "bad", ["jevops", "jevops/worker.py"])
    with pytest.raises(ValueError, match="outside"):
        snapshot.create_snapshot(project, project / "snapshot", ["jevops"])


def test_existing_snapshots_are_never_overwritten(project):
    receipt = capture(project)
    with pytest.raises(ValueError, match="new output"):
        capture(project)
    assert check(receipt)["status"] == "UNCHANGED"


def test_source_symlink_is_not_followed(project):
    (project / "jevops/link.py").symlink_to(project / "jevops/worker.py")
    with pytest.raises(ValueError, match="symlink"):
        capture(project)


def test_external_project_manifest_is_copied_as_data(project):
    projects = project.parent / "projects.json"
    projects.write_text('[{"root":"/prepared/project"}]')
    receipt = snapshot.create_snapshot(project, project.parent / "snapshot", ["jevops"], {"inputs/projects.json": projects})
    projects.write_text("[]")
    assert json.loads((Path(receipt["root"]) / "inputs/projects.json").read_text())[0]["root"] == "/prepared/project"
    assert check(receipt)["status"] == "UNCHANGED"


def test_source_mutation_during_capture_is_rejected(project, monkeypatch):
    original = snapshot._sources
    calls = []
    def mutate(*args):
        calls.append(1)
        if len(calls) == 2:
            (project / "jevops/worker.py").write_text("changed while reading")
        return original(*args)
    monkeypatch.setattr(snapshot, "_sources", mutate)
    with pytest.raises(ValueError, match="changed during capture"):
        capture(project)
    assert not (project.parent / "snapshot").exists()


def test_bounded_capture(project, monkeypatch):
    monkeypatch.setattr(snapshot, "MAX_BYTES", 4)
    with pytest.raises(ValueError, match="byte limit"):
        capture(project)
    assert not (project.parent / "snapshot").exists()


def test_expected_manifest_digest_is_not_read_from_mutable_metadata(project):
    receipt = capture(project)
    with pytest.raises(ValueError, match="manifest changed"):
        snapshot.verify_snapshot(Path(receipt["root"]), "0" * 64)


def test_source_directories_and_manifest_are_readonly(project):
    receipt = capture(project)
    root = Path(receipt["root"])
    assert all(not p.stat().st_mode & 0o222 for p in [root, *root.rglob("*")])


def test_cli_is_stdlib_only_and_prints_small_receipts(project):
    utility = Path(snapshot.__file__)
    result = subprocess.run([sys.executable, "-I", "-B", str(utility), "create", "--repo", str(project),
        "--output-dir", str(project.parent / "copy"), "--include", "jevops"],
        capture_output=True, text=True, check=True)
    receipt = json.loads(result.stdout)
    assert len(result.stdout) < 1500 and receipt["status"] == "CREATED"
    verified = subprocess.run([sys.executable, "-I", "-B", str(utility), "verify", "--root", receipt["root"],
        "--manifest-sha256", receipt["manifest_sha256"]], capture_output=True, text=True, check=True)
    assert json.loads(verified.stdout)["status"] == "UNCHANGED"
