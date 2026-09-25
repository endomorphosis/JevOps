"""Installed pinned compilers only; no network, builds of projects, or scores."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess

import pytest

from jevops.arena_import_closure import ImportClosureDiscovery
from jevops.arena_lean import CapabilityGap, ProjectBinding, pinned_lean
from jevops.lean import VersionPin

pytestmark = [
    pytest.mark.no_seal(reason="fresh native closure discovery checks"),
    pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1",
                       reason="installed pinned Lean opt-in; no downloads"),
]


@pytest.fixture(params=["v4.27.0", "v4.29.1"])
def native_binding(request, tmp_path):
    try:
        lean = pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), request.param)
    except CapabilityGap as exc:
        pytest.skip(str(exc))
    source = tmp_path / "ClosureFixture.lean"
    source.write_text("theorem ClosureFixture.available : True := True.intro\n")
    output = subprocess.run([str(lean), "-o", str(source.with_suffix(".olean")), str(source)],
        cwd=tmp_path, capture_output=True, timeout=60,
        env={"PATH": str(lean.parent) + ":/usr/bin:/bin", "HOME": str(tmp_path),
             "TMPDIR": str(tmp_path), "LEAN_PATH": str(tmp_path), "LEAN_NUM_THREADS": "1"})
    assert output.returncode == 0, output.stderr.decode() + output.stdout.decode()
    return ProjectBinding(VersionPin(request.param, "fixture"), lean, tmp_path,
                          "import ClosureFixture\n", (tmp_path,), project_backed=False)


@pytest.mark.parametrize("case", ["valid", "prefix_error", "already_imported"])
def test_native_closure_discovery(native_binding, tmp_path, case):
    target = "Demo.future"
    if case == "prefix_error":
        native_binding = replace(native_binding, prefix="import MissingClosureModule\nnamespace Demo\n")
    if case == "already_imported": target = "ClosureFixture.available"
    discovery = ImportClosureDiscovery(native_binding, max_processes=1, scratch_parent=tmp_path.parent)
    if case == "valid":
        result = discovery.discover(target)
        assert result["selection"] == (("ClosureFixture.olean",),)
        assert result["native_processes"] == 1 and result["proofs_verified"] == 0
        assert result["evidence_mode"] == "trusted_native_inventory" and not result["promotion"]
    else:
        with pytest.raises(ValueError, match="prefix failed" if case == "prefix_error" else "already imported"):
            discovery.discover(target)
    assert discovery.attempts == 1
