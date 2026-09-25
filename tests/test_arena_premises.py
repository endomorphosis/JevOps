"""Native inventory boundaries; only real process tests opt out of sealing."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jevops import arena_lean as native
from jevops import arena_premises as inventory
from jevops.arena import Outcome, VerificationRequest, content_hash
from jevops.arena_providers import load_inventory, propose_batch
from jevops.lean import VersionPin

PIN = VersionPin("v4.26.0", "inventory-control")
OTHER = VersionPin("v4.34.0", "inventory-control")
RECORD = {"name": "sample", "statement": "theorem sample : True",
          "src": "theorem sample : True := by\n  have h : True := True.intro\n  exact h",
          "version_info": [{PIN.lean_tag: PIN.git_commit}, {OTHER.lean_tag: OTHER.git_commit}]}
SPECS = (inventory.PremiseOrigin("True.intro", "stdlib", "library"),)


@pytest.fixture
def guard(tmp_path, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture"))
    bindings = {pin: native.ProjectBinding(pin, tmp_path / "lean", tmp_path, "", project_backed=False)
                for pin in (PIN, OTHER)}
    return native.NativeLeanVerifier(bindings, max_processes=0)


def stage(binding, payload):
    return {"schema": inventory.STAGE_SCHEMA, "request_sha256": payload["request_sha256"],
        "target": payload["target"], "lean_version": binding.pin.lean_tag[1:], "lean_githash": "a" * 40,
        "report": {"status": "EXPORTED", "entries": [
            {"name": n, "status": "AVAILABLE", "type_text": "True", "dependencies": [n], "axioms": []}
            for n in payload["names"]]}}


def test_budget_reserves_all_pins_and_fixture_never_claims_native(guard, tmp_path):
    calls = []
    def runner(binding, payload):
        calls.append(payload)
        assert "candidate" not in payload and "reference" not in payload
        return stage(binding, payload)
    too_small = inventory.NativePremiseExporter(guard, max_processes=1, runner=runner)
    report = too_small.export(RECORD, SPECS)
    assert report["reason"] == "PROCESS_BUDGET" and not calls and too_small.reserved == 0
    exporter = inventory.NativePremiseExporter(guard, max_processes=2, runner=runner)
    report = exporter.export(RECORD, SPECS)
    assert report["status"] == "FIXTURE_ONLY" and report["evidence_mode"] == "fixture"
    assert exporter.reserved == exporter.attempts == len(calls) == 2 and guard.processes == 0
    assert report["proof_verified"] is report["training_enabled"] is report["promoted"] is False
    assert report["official_score"] is None
    index, scope = load_inventory(json.loads(json.dumps(report["inventory"])), json.loads(json.dumps(report["scope"])))
    assert scope.environment_sha256 == guard.context(RECORD).context_id
    assert index.rank("True", target="sample", scope=scope)["matches"][0]["name"] == "True.intro"
    with pytest.raises(ValueError, match="native extraction"):
        inventory.write_inventory(report, tmp_path / "no-fixture-publication")
    assert not (tmp_path / "no-fixture-publication").exists()
    assert exporter.export(RECORD, SPECS)["reason"] == "PROCESS_BUDGET"
    assert len(calls) == 2


def test_falsey_injected_runner_is_still_only_a_fixture(guard, tmp_path):
    class FalseyRunner:
        def __bool__(self):
            return False

        def __call__(self, binding, payload):
            return stage(binding, payload)

    report = inventory.NativePremiseExporter(guard, max_processes=2, runner=FalseyRunner()).export(RECORD, SPECS)
    assert report["status"] == "FIXTURE_ONLY" and report["evidence_mode"] == "fixture"
    with pytest.raises(ValueError, match="native extraction"):
        inventory.write_inventory(report, tmp_path / "falsey-fixture")


@pytest.mark.parametrize("case", ["missing", "different_type", "heldout_dependency", "axiom"])
def test_intersection_and_native_dependency_filters(guard, case):
    specs = (*SPECS, inventory.PremiseOrigin("Library.other", "library", "train"))
    def runner(binding, payload):
        value = stage(binding, payload)
        row = next(r for r in value["report"]["entries"] if r["name"] == "Library.other")
        if binding.pin == OTHER:
            if case == "missing":
                row.clear(); row.update(name="Library.other", status="MISSING")
            elif case == "different_type":
                row["type_text"] = "False"
            elif case == "heldout_dependency":
                row["dependencies"].append("Hidden.canary")
            else:
                row["dependencies"].append("Bad.axiom")
                row["axioms"] = ["Bad.axiom"]
        return value
    report = inventory.NativePremiseExporter(guard, max_processes=2, runner=runner).export(
        RECORD, specs, excluded_names=("Hidden.canary",))
    assert report["status"] == "FIXTURE_ONLY"
    assert report["scope"]["available_names"] == ("True.intro",)
    assert report["exclusions"][0]["reason"] == {"missing": "NOT_AVAILABLE_ON_ALL_PINS",
        "different_type": "TYPE_TEXT_DIFFERS", "heldout_dependency": "EXCLUDED_DEPENDENCY", "axiom": "AXIOM_POLICY"}[case]


@pytest.mark.parametrize("split", ["canary", "test", "validation"])
def test_declared_heldouts_and_transitive_wrappers_are_excluded(guard, split):
    specs = (inventory.PremiseOrigin("Hidden.lemma", "heldout-family", split),
             inventory.PremiseOrigin("Wrapper.lemma", "train-family", "train"), *SPECS)
    def runner(binding, payload):
        value = stage(binding, payload)
        for row in value["report"]["entries"]:
            if row["name"] == "Wrapper.lemma":
                row["dependencies"].append("Hidden.lemma")
        return value
    report = inventory.NativePremiseExporter(guard, max_processes=2, runner=runner).export(RECORD, specs)
    assert report["scope"]["available_names"] == ("True.intro",)
    assert {e["reason"] for e in report["exclusions"]} == {"EXCLUDED_PROVENANCE", "EXCLUDED_DEPENDENCY"}


@pytest.mark.parametrize("case", ["request", "version", "target", "duplicate", "partial", "extra_field",
                                 "false_closure", "axioms_outside_closure", "row_name", "entry_status"])
def test_malformed_or_foreign_stage_never_exports_partial_inventory(guard, case):
    def runner(binding, payload):
        value = stage(binding, payload)
        if binding.pin == PIN:
            return value
        row = value["report"]["entries"][0]
        if case == "request": value["request_sha256"] = "b" * 64
        elif case == "version": value["lean_version"] = "0.0.0"
        elif case == "target": value["target"] = "other"
        elif case == "duplicate": value["report"]["entries"].append(deepcopy(row))
        elif case == "partial": value["report"]["entries"] = []
        elif case == "extra_field": row["verified"] = True
        elif case == "false_closure": row["dependencies"] = []
        elif case == "axioms_outside_closure": row["axioms"] = ["Bad.axiom"]
        elif case == "row_name": row["name"] = "Unknown.lemma"
        else: row["status"] = "VERIFIED"
        return value
    exporter = inventory.NativePremiseExporter(guard, max_processes=2, runner=runner)
    report = exporter.export(RECORD, SPECS)
    assert report["status"] == "INCOMPLETE" and report["inventory"] is report["scope"] is None
    assert len(report["stages"]) == 1 and report["attempted_processes"] == 2
    assert exporter.export(RECORD, SPECS)["reason"] == "PROCESS_BUDGET"


@pytest.mark.parametrize("case", ["dependencies", "implementation", "timeout"])
def test_mutation_or_timeout_discards_successful_stage(guard, monkeypatch, case):
    exporter = inventory.NativePremiseExporter(guard, max_processes=2, runner=stage)
    def runner(binding, payload):
        value = stage(binding, payload)
        if case == "dependencies":
            monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: "b" * 64)
        elif case == "implementation":
            monkeypatch.setattr(exporter, "_code_identity", lambda: "b" * 64)
        else:
            raise subprocess.TimeoutExpired("fixture", 1)
        return value
    exporter.runner = runner
    report = exporter.export(RECORD, SPECS)
    assert report["status"] == "INCOMPLETE" and report["inventory"] is None
    assert report["attempted_processes"] == 1 and report["reserved_processes"] == 2


def test_deadline_expiration_never_launches(guard, monkeypatch):
    exporter = inventory.NativePremiseExporter(guard, max_processes=2, runner=lambda *_: pytest.fail("late launch"))
    times = iter([0, 121])
    monkeypatch.setattr(inventory.time, "monotonic", lambda: next(times))
    report = exporter.export(RECORD, SPECS)
    assert report["status"] == "INCOMPLETE" and report["attempted_processes"] == 0


@pytest.mark.parametrize("raw", [b"", b"JEVOPS_PREMISES:{}\nJEVOPS_PREMISES:{}",
                                 b'JEVOPS_PREMISES:{"a":1,"a":2}', b'JEVOPS_PREMISES:{"a":NaN}'])
def test_strict_protocol_parser(raw):
    with pytest.raises(ValueError):
        inventory.parse_stage(raw)


@pytest.mark.parametrize("kwargs", [{"max_processes": True}, {"max_processes": -1},
    {"max_processes": 257}, {"total_seconds": float("nan")}, {"total_seconds": 0},
    {"dependency_budget": 4097}, {"dependency_budget": True}, {"runner": "execute"}])
def test_invalid_limits(guard, kwargs):
    with pytest.raises(ValueError):
        inventory.NativePremiseExporter(guard, **kwargs)


def test_bad_requests_and_missing_pin_launch_nothing(guard):
    exporter = inventory.NativePremiseExporter(guard, max_processes=2,
        runner=lambda *_: pytest.fail("invalid request launched"))
    for specs in ((), list(SPECS), SPECS * 2, ("True.intro",)):
        with pytest.raises(ValueError):
            exporter.export(RECORD, specs)
    with pytest.raises(ValueError):
        exporter.export(RECORD, SPECS, excluded_names=("invalid; sorry",))
    guard.bindings.pop(OTHER)
    with pytest.raises(native.CapabilityGap, match="not_all_version"):
        exporter.export(RECORD, SPECS)
    assert exporter.attempts == exporter.reserved == 0


def test_native_stage_excludes_protected_origin_and_projects_only_admitted_edges(guard):
    specs = (*SPECS, inventory.PremiseOrigin("A.lemma", "protected-family", "train"))
    def runner(binding, payload):
        value = stage(binding, payload)
        value["report"]["entries"][1]["dependencies"].append("Unnominated.internal")
        return value
    report = inventory.NativePremiseExporter(guard, max_processes=2, runner=runner).export(
        RECORD, specs, excluded_origins=("protected-family",))
    assert report["scope"]["available_names"] == ("True.intro",)
    assert report["inventory"]["premises"][0]["dependencies"] == ()
    assert "Unnominated.internal" in report["stages"][0]["evidence"]["report"]["entries"][1]["dependencies"]


@pytest.mark.no_seal(reason="fresh all-pin native premise extraction and downstream proof checks")
def test_native_export_roundtrip_and_proof_gate(tmp_path):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads")
    bindings = {}
    before = ('theorem clean : True := True.intro\n'
              'axiom forbidden : False\n'
              'theorem tainted : True := False.elim forbidden\n'
              'theorem holdout : True := True.intro\n'
              'theorem wrapper : True := holdout\n')
    for pin in (PIN, OTHER):
        lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), pin.lean_tag)
        bindings[pin] = native.ProjectBinding(pin, lean, tmp_path, before, project_backed=False)
    guard = native.NativeLeanVerifier(bindings, max_processes=2)
    specs = tuple(inventory.PremiseOrigin(name, "control", "library") for name in
                  ("clean", "tainted", "wrapper", "Nonexistent.proof", "sample")) + SPECS
    exporter = inventory.NativePremiseExporter(guard, max_processes=2)
    report = exporter.export(RECORD, specs, excluded_names=("holdout",))
    assert report["status"] == "INVENTORY_ONLY", report
    assert report["scope"]["available_names"] == ("True.intro", "clean")
    reasons = {r["name"]: r["reason"] for r in report["exclusions"]}
    assert reasons["tainted"] == "AXIOM_POLICY" and reasons["wrapper"] == "EXCLUDED_DEPENDENCY"
    assert reasons["Nonexistent.proof"] == "NOT_AVAILABLE_ON_ALL_PINS"
    out = tmp_path / "inventory"
    inventory.write_inventory(report, out)
    index, scope = load_inventory(json.loads((out / "inventory.json").read_text()),
                                  json.loads((out / "scope.json").read_text()))
    batch = propose_batch(RECORD, index, scope, cap=1)
    assert batch["drafts"] and batch["proof_verified"] is False
    for pin in (PIN, OTHER):
        receipt = guard(VerificationRequest(guard.context(RECORD), batch["drafts"][0]["source"], pin))
        assert receipt.outcome == Outcome.VERIFIED, receipt
    assert guard.processes == exporter.attempts == 2
    prior = (out / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        inventory.write_inventory(report, out)
    assert (out / "report.json").read_bytes() == prior


@pytest.mark.no_seal(reason="fresh native prefix leakage and closure resource controls")
@pytest.mark.parametrize("case", ["target_present", "prefix_error", "closure_budget"])
def test_native_prefix_and_dependency_budget_fail_closed(tmp_path, case):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), PIN.lean_tag)
    before = {"target_present": "theorem sample : True := True.intro\n",
              "prefix_error": "theorem broken : False := by trivial\n", "closure_budget": ""}[case]
    binding = native.ProjectBinding(PIN, lean, tmp_path, before, project_backed=False)
    guard = native.NativeLeanVerifier({PIN: binding}, max_processes=0)
    record = {**RECORD, "version_info": [{PIN.lean_tag: PIN.git_commit}]}
    report = inventory.NativePremiseExporter(guard, max_processes=1, dependency_budget=1).export(record, SPECS)
    if case == "closure_budget":
        assert report["status"] == "INVENTORY_ONLY" and report["inventory"]["premises"] == []
        assert report["stages"][0]["evidence"]["report"]["entries"][0]["status"] == "dependency_budget"
    else:
        assert report["status"] == "INCOMPLETE" and report["inventory"] is None


@pytest.mark.no_seal(reason="fresh module privacy and hidden dependency audit")
@pytest.mark.parametrize("tag", ["v4.27.0", "v4.34.0"])
def test_native_module_private_proofs_do_not_hide_axioms(tmp_path, tag):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    (tmp_path / "PremiseSupport.lean").write_text(
        'module\npublic axiom forbidden : False\n'
        'private theorem internal : False := forbidden\n'
        'public theorem tainted : True := False.elim internal\n'
        'public theorem clean : True := True.intro\n'
        'private theorem concealed : True := True.intro\n')
    env = {"PATH": str(lean.parent) + ":/usr/bin:/bin", "HOME": str(tmp_path),
           "TMPDIR": str(tmp_path), "LEAN_NUM_THREADS": "1"}
    built = subprocess.run([str(lean), "-o", "PremiseSupport.olean", "PremiseSupport.lean"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    pin = VersionPin(tag, "module-inventory-control")
    binding = native.ProjectBinding(pin, lean, tmp_path, "module\nimport PremiseSupport\npublic section\n",
                                    search_paths=(tmp_path,), project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=0)
    record = {**RECORD, "version_info": [{tag: pin.git_commit}]}
    specs = tuple(inventory.PremiseOrigin(n, "module-control", "library") for n in ("tainted", "clean", "concealed"))
    report = inventory.NativePremiseExporter(guard, max_processes=1).export(record, specs)
    assert report["status"] == "INVENTORY_ONLY", report
    assert report["scope"]["available_names"] == ("clean",)
    reasons = {e["name"]: e["reason"] for e in report["exclusions"]}
    assert reasons == {"concealed": "NOT_AVAILABLE_ON_ALL_PINS", "tainted": "AXIOM_POLICY"}
    row = next(r for r in report["stages"][0]["evidence"]["report"]["entries"] if r["name"] == "tainted")
    assert "forbidden" in row["axioms"]


def cli_inputs(tmp_path, monkeypatch, guard, *, nominees=None, projects=None, extra=()):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps(RECORD) + "\n" + json.dumps({**RECORD, "name": "Other.benchmark"}) + "\n")
    metadata = tmp_path / "nominees.json"
    metadata.write_text(json.dumps(nominees if nominees is not None else
                                    [{"name": "True.intro", "origin": "stdlib", "split": "library"}]))
    bindings = tmp_path / "projects.json"
    bindings.write_text(json.dumps(projects if projects is not None else [p.to_dict() for p in (PIN, OTHER)]))
    monkeypatch.setattr(inventory, "project_binding", lambda record, pin, project, elan: guard.bindings[pin])
    out = tmp_path / "cli-output"
    monkeypatch.setattr(sys, "argv", ["arena_premises", "--corpus", str(corpus), "--problem", RECORD["name"],
        "--projects", str(bindings), "--nominees", str(metadata), "--trusted-local", "--output-dir", str(out), *extra])
    return out


def test_cli_zero_budget_persists_failure_and_excludes_entire_corpus(guard, tmp_path, monkeypatch, capsys):
    out = cli_inputs(tmp_path, monkeypatch, guard)
    monkeypatch.setattr(inventory.NativePremiseExporter, "_run", lambda *_: pytest.fail("zero budget launch"))
    assert inventory.main() == 2
    assert json.loads(capsys.readouterr().out)["attempted_processes"] == 0
    report = json.loads((out / "report.json").read_text())
    assert report["reason"] == "PROCESS_BUDGET" and report["inventory"] is None
    assert set(report["excluded_names"]) == {RECORD["name"], "Other.benchmark"}
    assert not (out / "inventory.json").exists() and not (out / "scope.json").exists()
    prior = (out / "report.json").read_bytes()
    with pytest.raises(SystemExit) as exc:
        inventory.main()
    assert exc.value.code == 2 and (out / "report.json").read_bytes() == prior


@pytest.mark.parametrize("change", ["duplicate_nominee", "extra_metadata", "missing_pin", "duplicate_binding",
                                  "bad_budget", "bad_timeout"])
def test_cli_rejects_invalid_configuration_before_export(guard, tmp_path, monkeypatch, change):
    nominee = {"name": "True.intro", "origin": "stdlib", "split": "library"}
    kwargs = {}
    if change == "duplicate_nominee": kwargs["nominees"] = [nominee, nominee]
    elif change == "extra_metadata": kwargs["nominees"] = [{**nominee, "verified": True}]
    elif change == "missing_pin": kwargs["projects"] = [PIN.to_dict()]
    elif change == "duplicate_binding": kwargs["projects"] = [PIN.to_dict(), PIN.to_dict(), OTHER.to_dict()]
    elif change == "bad_budget": kwargs["extra"] = ("--max-processes", "-1")
    else: kwargs["extra"] = ("--timeout", "nan")
    out = cli_inputs(tmp_path, monkeypatch, guard, **kwargs)
    monkeypatch.setattr(inventory.NativePremiseExporter, "export", lambda *_a, **_k: pytest.fail("invalid input export"))
    with pytest.raises(SystemExit) as exc:
        inventory.main()
    assert exc.value.code == 2 and not out.exists()
