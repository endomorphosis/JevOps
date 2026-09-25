"""Opt-in regressions for errors that Lean's per-command message reset can hide."""
import os
from pathlib import Path

import pytest

from jevops import arena_lean as native
from jevops.lean import VersionPin

pytestmark = [
    pytest.mark.no_seal(reason="fresh native frontend diagnostic preservation"),
    pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1",
                       reason="installed Lean opt-in; never download"),
]


@pytest.fixture(params=["v4.27.0", "v4.29.1"])
def binding(request, tmp_path):
    try:
        lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), request.param)
    except native.CapabilityGap as exc:
        pytest.skip(str(exc))
    return native.ProjectBinding(VersionPin(request.param, "frontend-error-regression"),
                                 lean, tmp_path, "", project_backed=False)


def payload(prefix="namespace Demo\n"):
    source = "theorem sample : True := by trivial"
    return {"request_id": "frontend-error-regression", "target": "Demo.sample",
            "max_heartbeats": 200000, "prefix": prefix, "reference": source, "candidate": source}


@pytest.mark.parametrize("prefix", [
    "import UnavailableArenaDependency\nnamespace Demo\n",
    "def broken : Nat := unknownArenaValue\nnamespace Demo\n",
    "def broken : Nat := )\nnamespace Demo\n",
])
def test_prefix_errors_cannot_be_erased_by_a_later_valid_command(binding, prefix):
    result, _ = native.run_native(binding, payload(prefix), timeout=60)
    report = result["report"]
    assert report["outcome"] == "UNAVAILABLE", report
    assert report["reason"] == "prefix_errors", report
    assert any(m["severity"] == "error" for m in report["diagnostics"]), report
    assert "heartbeats" not in report


@pytest.mark.parametrize("side", ["reference", "candidate"])
def test_recovered_parser_errors_cannot_be_erased_by_elaboration(binding, side):
    request = payload()
    request[side] = "theorem sample (x Nat) : True := by trivial"
    result, _ = native.run_native(binding, request, timeout=60)
    report = result["report"]
    assert report["outcome"] == ("ERROR" if side == "reference" else "REJECTED"), report
    assert report["reason"] == side + "_errors", report
    assert any(m["severity"] == "error" for m in report["diagnostics"]), report
    assert "heartbeats" not in report
