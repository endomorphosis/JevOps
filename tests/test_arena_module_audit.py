"""Opt-in installed-Lean audit tests. Never download dependencies/toolchains."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from jevops import arena_lean as native
from jevops.arena import Outcome, VerificationRequest
from jevops.lean import VersionPin

pytestmark = pytest.mark.no_seal(reason="fresh native module visibility and axiom audits")


# v4.26 does not enable `module` by default; its non-module path remains covered
# by test_arena_lean.py. Do not silently change compiler options to make it fit.
@pytest.fixture(params=["v4.27.0", "v4.28.0", "v4.29.1", "v4.32.0", "v4.33.0-rc2"])
def module_environment(request, tmp_path):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads")
    tag = request.param
    try:
        lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    except native.CapabilityGap as exc:
        pytest.skip(str(exc))
    dependency = tmp_path / "AuditSupport.lean"
    dependency.write_text("""module
public axiom forbidden : False
private theorem private_helper : False := forbidden
public theorem tainted : False := private_helper
public theorem clean : True := trivial
private theorem concealed : True := trivial
""")
    env = {"PATH": str(lean.parent) + ":/usr/bin:/bin", "HOME": str(tmp_path),
           "TMPDIR": str(tmp_path), "LEAN_NUM_THREADS": "1"}
    result = subprocess.run([str(lean), "-o", "AuditSupport.olean", "AuditSupport.lean"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "AuditSupport.olean.private").exists()
    pin = VersionPin(tag, "offline-module-audit")
    binding = native.ProjectBinding(pin, lean, tmp_path, "module\nimport AuditSupport\npublic section\n",
                                    search_paths=(tmp_path,), project_backed=False)
    return pin, binding


@pytest.mark.parametrize("case,expected", [("clean", Outcome.VERIFIED), ("hidden_axiom", Outcome.REJECTED),
                                           ("private_visibility", Outcome.REJECTED)])
def test_module_audit_retains_privacy_and_real_axioms(module_environment, case, expected):
    pin, binding = module_environment
    statement = "theorem sample : True"
    source = statement + " := by trivial"
    record = {"name": "sample", "statement": statement, "src": source,
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    adapter = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    context = adapter.context(record)
    body = {"clean": "exact clean", "hidden_axiom": "exact False.elim tainted",
            "private_visibility": "exact concealed"}[case]
    receipt = adapter(VerificationRequest(context, statement + " := by " + body, pin))
    assert receipt.outcome == expected, receipt
    report = json.loads(receipt.observations_json).get("report", {})
    if case == "clean":
        assert report["axioms"] == report["reference_axioms"] == []
    elif case == "hidden_axiom":
        assert "forbidden" in report["axioms"] and receipt.reason == "axioms_policy"
    else:
        assert report["reason"] == "candidate_errors"


@pytest.mark.parametrize("tag", ["v4.27.0", "v4.29.1"])
def test_module_audit_restores_stdlib_proof_bodies(tag, tmp_path):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    pin = VersionPin(tag, "module-stdlib")
    source = "theorem sample (n : Nat) : n + 0 = n := by simp"
    binding = native.ProjectBinding(pin, lean, tmp_path, "module\npublic section\n", project_backed=False)
    record = {"name": "sample", "statement": source.split(" :=")[0], "src": source,
              "version_info": [{tag: pin.git_commit}]}
    adapter = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    receipt = adapter(VerificationRequest(adapter.context(record), source, pin))
    assert receipt.outcome == Outcome.VERIFIED, receipt


@pytest.mark.parametrize("case", ["clean", "hidden_axiom", "private_visibility", "replace_env"])
def test_local_replay_uses_original_project_audit_without_exposing_private_names(module_environment, case):
    from jevops.arena_local import ArenaLocalRuntime
    pin, binding = module_environment
    statement = "theorem sample : True"
    source = statement + " := by exact clean"
    record = {"name": "sample", "statement": statement, "src": source,
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    rt = ArenaLocalRuntime(guard, record, max_processes=2)
    capture = rt.capture(pin)
    assert capture["ok"], capture
    event = next(e for e in capture["capture"]["trace"]["events"] if e["start"] is not None and
                 source.encode()[int(e["start"]):int(e["end"])] == b"exact clean")
    candidate = {"clean": "exact clean", "hidden_axiom": "exact False.elim tainted",
        "private_visibility": "exact concealed", "replace_env":
        "run_tac do\n  (← Lean.Elab.Tactic.getMainGoal).assign (Lean.mkApp (Lean.mkApp "
        "(Lean.mkConst ``False.elim [Lean.Level.zero]) (Lean.mkConst ``True)) (Lean.mkConst `tainted))\n"
        "  Lean.Elab.Tactic.setGoals []\n  Lean.setEnv (← Lean.importModules #[{module := `Lean}] {})"}[case]
    if case == "replace_env":
        # Arena rejects executable metaprograms before reserving/launching work.
        # The standalone replay tests exercise original-environment auditing
        # inside Lean as defense in depth; do not weaken this envelope to do so.
        before = (rt.reserved, rt.attempts)
        with pytest.raises(ValueError, match="changed_or_unsupported_envelope"):
            rt.replay(pin, source, capture["capture"], int(event["id"]), candidate)
        assert (rt.reserved, rt.attempts) == before
        candidate = "exact clean"
    outcome = rt.replay(pin, source, capture["capture"], int(event["id"]), candidate)
    assert outcome["ok"], outcome
    assert outcome["native"]["baseline"]["status"] == "closed_kernel_checked", outcome
    assert outcome["closing_reproduced"] == (case in {"clean", "replace_env"}), outcome
    if case == "hidden_axiom":
        assert "forbidden" in outcome["native"]["proposed"]["reason"], outcome
    assert not outcome["proof_admitted"]
    control = guard(VerificationRequest(rt.context, source, pin))
    assert control.outcome == Outcome.VERIFIED, control
