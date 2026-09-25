from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from jevops import proof_state as ps


def name(s):
    return [["s", s]]


def mvar(s, type_ref="0", **kwargs):
    return {"id": name(s), "name": [], "type": type_ref, "locals": [], "instances": [],
            "assignment": None, "kind": "natural", "depth": "0", "index": "0", "scope_args": "0", **kwargs}


def local(s, type_ref="0", **kwargs):
    return {"id": name(s), "name": name(s), "index": "0", "type": type_ref, "value": None,
            "nondep": False, "binder": "explicit", "kind": "default", **kwargs}


def state():
    # Format/dependency fixtures, deliberately not asserted to be well-typed.
    return {"schema": ps.STATE_SCHEMA, "goals": [name("g1"), name("g2")],
            "levels": [["zero"]], "expressions": [["sort", "0"]],
            "metavariables": [mvar("g1"), mvar("g2")], "universe_metavariables": [],
            "depth": "0", "level_assign_depth": "0"}


def test_independent_goals_and_shared_immutable_local_context():
    s = state()
    for m in s["metavariables"]:
        m["locals"] = [local("p")]
    r = ps.analyze_state(s)
    assert r["components"] == [[name("g1")], [name("g2")]]
    assert not r["kernel_typechecked"] and not r["proof_admitted"] and not r["replayable"]


@pytest.mark.parametrize("location", ["type", "local_type", "local_value", "instance", "assignment"])
def test_transitive_term_coupling_in_every_context_location(location):
    s = state()
    s["expressions"].extend([["mvar", name("a")], ["mvar", name("shared")]])
    s["metavariables"].extend([mvar("a", assignment="2"), mvar("shared")])
    for m in s["metavariables"][:2]:
        if location == "type":
            m["type"] = "1"
        elif location == "local_type":
            m["locals"] = [local("p", "1")]
        elif location == "local_value":
            m["locals"] = [local("p", value="1", nondep=False)]
        elif location == "instance":
            m["instances"] = [[name("ExampleClass"), "1"]]
        else:
            # Assignment dependencies of a referenced third mvar are traversed.
            m["type"] = "1"
    r = ps.analyze_state(s)
    assert r["components"] == [[name("g1"), name("g2")]]
    assert all(["m", name("shared")] in d["unresolved"] for d in r["dependencies"])
    assert all(["m", name("a")] not in d["unresolved"] for d in r["dependencies"])


def test_v2_opaque_have_is_typed_not_a_hidden_definition_and_v1_is_not_reinterpreted():
    s = state()
    for m in s["metavariables"]:
        m["locals"] = [local("h", nondep=True)]
    assert len(ps.analyze_state(s)["components"]) == 2
    s["schema"] = ps.LEGACY_STATE_SCHEMA
    with pytest.raises(ValueError, match="local declaration"):
        ps.analyze_state(s)  # v1 required the raw value; no silent migration
    for m in s["metavariables"]:
        m["locals"][0]["value"] = "0"
    assert len(ps.analyze_state(s)["components"]) == 2
    s["schema"] = ps.STATE_SCHEMA
    with pytest.raises(ValueError, match="local declaration"):
        ps.analyze_state(s)  # v2 cannot smuggle a hidden definition back in


def test_solved_shared_term_is_not_an_unresolved_dependency():
    s = state()
    s["expressions"].append(["mvar", name("shared")])
    s["metavariables"].append(mvar("shared", assignment="0"))
    for m in s["metavariables"][:2]:
        m["type"] = "1"
    assert ps.analyze_state(s)["components"] == [[name("g1")], [name("g2")]]


def test_transitive_component_union_and_direct_goal_dependency():
    s = state()
    s["expressions"].extend([["mvar", name("g2")], ["mvar", name("g3")]])
    s["goals"].append(name("g3"))
    s["metavariables"].append(mvar("g3"))
    s["metavariables"][0]["type"] = "1"
    s["metavariables"][1]["type"] = "2"
    assert ps.analyze_state(s)["components"] == [[name("g1"), name("g2"), name("g3")]]


def universe_state():
    s = state()
    s["levels"] = [["mvar", name("u")], ["mvar", name("v")]]
    s["universe_metavariables"] = [{"id": name("u"), "depth": "0", "assignment": "1"},
                                  {"id": name("v"), "depth": "0", "assignment": None}]
    return s


def test_universe_coupling_is_transitive_and_can_be_resolved():
    s = universe_state()
    assert ps.analyze_state(s)["components"] == [[name("g1"), name("g2")]]
    s["levels"].append(["zero"])
    s["universe_metavariables"][1]["assignment"] = "2"
    assert ps.analyze_state(s)["components"] == [[name("g1")], [name("g2")]]


def test_assigned_roots_do_not_become_search_goals_and_context_cycles_terminate():
    s = state()
    s["expressions"].extend([["mvar", name("g1")], ["mvar", name("g2")]])
    s["metavariables"][0]["type"] = "2"
    s["metavariables"][1]["type"] = "1"
    s["metavariables"][1]["assignment"] = "0"
    r = ps.analyze_state(s)
    assert r["components"] == [[name("g1")]] and r["assigned_goals"] == 1


@pytest.mark.parametrize("case", ["forward", "loose", "fvar", "scope", "duplicate_goal", "missing_mvar",
                                  "extra_mvar", "duplicate_mvar", "duplicate_expr", "unreachable",
                                  "syntax_metadata", "unknown", "numeric", "bad_kind", "assignment_cycle",
                                  "level_cycle", "level_missing", "extra_fields", "local_order"])
def test_malformed_observations_fail_closed(case):
    s = state()
    if case == "forward":
        s["expressions"][0] = ["app", "0", "0"]
    elif case == "loose":
        s["expressions"][0] = ["bvar", "0"]
    elif case in {"fvar", "scope"}:
        s["expressions"][0] = ["fvar", name("x")]
        if case == "scope":
            s["metavariables"][0]["locals"] = [local("x")]
    elif case == "duplicate_goal":
        s["goals"].append(name("g1"))
    elif case == "missing_mvar":
        s["metavariables"].pop()
    elif case == "extra_mvar":
        s["metavariables"].append(mvar("extra"))
    elif case == "duplicate_mvar":
        s["metavariables"].append(copy.deepcopy(s["metavariables"][0]))
    elif case == "duplicate_expr":
        s["expressions"].append(["sort", "0"])
    elif case == "unreachable":
        s["expressions"].append(["nat", "999"])
    elif case == "syntax_metadata":
        s["expressions"].append(["mdata", [[name("key"), ["syntax", "dropped"]]], "0"])
    elif case == "unknown":
        s["expressions"][0][0] = "fake"
    elif case == "numeric":
        s["metavariables"][0]["type"] = 0
    elif case == "bad_kind":
        s["metavariables"][0]["kind"] = "guess"
    elif case == "assignment_cycle":
        s["expressions"].append(["mvar", name("g1")])
        s["metavariables"][0]["assignment"] = "1"
    elif case == "level_cycle":
        s = universe_state()
        s["universe_metavariables"][1]["assignment"] = "0"
    elif case == "level_missing":
        s = universe_state()
        s["universe_metavariables"].pop()
    elif case == "extra_fields":
        s["trusted"] = True
    elif case == "local_order":
        s["metavariables"][0]["locals"] = [local("p"), local("q")]
    with pytest.raises(ValueError):
        ps.analyze_state(s)


@pytest.mark.parametrize("budget", [True, 0, -1, 20001, 1])
def test_node_budgets(budget):
    with pytest.raises(ValueError):
        ps.analyze_state(state(), node_budget=budget)


def test_binder_scopes_are_checked_without_expanding_shared_nodes():
    s = state()
    s["expressions"] += [["bvar", "0"], ["lam", name("x"), "implicit", "0", "1"]]
    for m in s["metavariables"]:
        m["type"] = "2"
    assert ps.analyze_state(s)["expression_nodes"] == 3
    s["expressions"][2][3] = "1"  # Binder does not scope over its own type.
    with pytest.raises(ValueError, match="unbound"):
        ps.analyze_state(s)


@pytest.mark.no_seal(reason="exercise real subprocess timeout and pipe budgets")
def test_pipe_budget_timeout_and_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "MAX_BYTES", 1024)
    with pytest.raises(ValueError, match="byte budget"):
        ps._run_bounded([sys.executable, "-c", "import sys; sys.stderr.write('x'*100000)"],
                        source=b"", cwd=tmp_path, timeout=5)
    with pytest.raises(TimeoutError):
        ps._run_bounded([sys.executable, "-c", "import time; time.sleep(10)"],
                        source=b"", cwd=tmp_path, timeout=0.1)
    with pytest.raises(ValueError, match="native"):
        ps._run_bounded([sys.executable, "-c", "raise SystemExit(1)"],
                        source=b"", cwd=tmp_path, timeout=5)


SOURCE = """-- λ: source ranges below are UTF-8 byte offsets.
theorem independent (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  constructor
  · exact hp
  · exact hq

theorem coupled : 2 ≤ 5 := by
  apply Nat.le_trans
  · exact Nat.le_refl 2
  · decide

theorem locals (x : Nat) : x = x := by
  let y := x
  have h : y = x := rfl
  exact h
"""


@pytest.fixture(scope="module")
def native_report(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    return ps.capture_source(SOURCE, project_root=tmp_path_factory.mktemp("proof-state"),
                             environment_sha256="a" * 64, event_budget=128)


def test_native_capture_factors_independent_but_not_coupled_goals(native_report):
    r = native_report
    assert r["ok"], r
    assert not r["trace"]["elaboration_errors"]
    assert r["captured_events"] > 0 and r["unsupported_events"] == 0
    assert r["source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert not r["proof_admitted"] and not r["kernel_typechecked"] and not r["replayable"]
    events = r["trace"]["events"]
    pairs = list(zip(events, r["analyses"]))
    constructor = [(e, a) for e, a in pairs if e["start"] is not None and
                   SOURCE.encode()[int(e["start"]):int(e["end"])].decode() == "constructor"]
    assert any(len(a["after"]["components"]) == 2 for _, a in constructor)
    trans = [(e, a) for e, a in pairs if e["start"] is not None and
             SOURCE.encode()[int(e["start"]):int(e["end"])].decode() == "apply Nat.le_trans"]
    assert trans and any(a["after"]["active_goals"] >= 2 and len(a["after"]["components"]) == 1 for _, a in trans)
    # Solving the first inequality assigns the shared witness; the remaining
    # goal must no longer carry that unresolved dependency.
    solved_first = [(e, a) for e, a in pairs if e["start"] is not None and
                    SOURCE.encode()[int(e["start"]):int(e["end"])].decode() == "exact Nat.le_refl 2"]
    assert solved_first
    assert any(a["after"]["active_goals"] <= 1 for _, a in solved_first)
    assert any(d["value"] is not None for e in events for side in ("before", "after")
               for m in e[side]["metavariables"] for d in m["locals"])


def test_trace_tampering_and_unicode_spans_fail_closed(native_report):
    assert native_report["ok"], native_report
    for kind in ("parent", "span", "trust", "environment"):
        trace = copy.deepcopy(native_report["trace"])
        if kind == "parent":
            trace["events"][0]["parent"] = "0"
        elif kind == "span":
            trace["events"][0]["start"] = "4"  # Inside λ's multibyte encoding.
        elif kind == "trust":
            trace["proof_admitted"] = True
        else:
            trace["environment"] = "b" * 64
        with pytest.raises(ValueError):
            ps.validate_trace(trace, source=SOURCE, environment=native_report["environment"], event_budget=128)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_failed_tactic_and_sorry_are_never_admission(tmp_path):
    for proof in ("exact missing_identifier", "sorry"):
        r = ps.capture_source("theorem bad : False := by\n  " + proof + "\n", project_root=tmp_path,
                              environment_sha256="a" * 64)
        assert r["ok"], r
        assert r["trace"]["elaboration_errors"] == (proof != "sorry")
        assert not r["proof_admitted"] and not r["kernel_typechecked"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_capture_budgets_report_unsupported_and_do_not_truncate(tmp_path):
    source = "theorem demo (p : Prop) (h : p) : p := by exact h\n"
    r = ps.capture_source(source, project_root=tmp_path, environment_sha256="a" * 64, node_budget=1)
    assert r["ok"] and r["unsupported_events"] > 0 and r["captured_events"] == 0, r
    r = ps.capture_source(source, project_root=tmp_path, environment_sha256="a" * 64, event_budget=1)
    assert not r["ok"] and "trace" not in r


def test_collection_never_reads_evaluation_sources_and_does_not_admit_teachers(native_report):
    class Evaluation(dict):
        def __getitem__(self, key):
            assert key not in ("source", "target", "target_text"), "evaluation leakage"
            return super().__getitem__(key)

    calls = []
    report = copy.deepcopy(native_report)
    # Analysis claims are recomputed from the bound raw trace.
    report["analyses"] = []
    rows = [{"id": "train", "split": "train", "source": SOURCE},
            *[Evaluation(id=s, split=s) for s in ("validation", "canary", "holdout")]]
    result = ps.collect_training_observations(rows, capture_fn=lambda s: calls.append(s) or report)
    assert calls == [SOURCE] and result["capture_calls"] == 1
    assert len(result["observations"]) == 1
    observation = result["observations"][0]
    assert observation["capture"]["analyses"] == native_report["analyses"]
    assert not observation["teacher_admitted"] and not result["model_trained"]
    assert [d["status"] for d in result["decisions"]] == ["observed"] + ["excluded_split"] * 3


@pytest.mark.parametrize("kind", ["source", "trace", "binding", "trust", "bytes", "rows"])
def test_collection_rejects_foreign_receipts_and_budgets(native_report, kind):
    report = copy.deepcopy(native_report)
    rows = [{"id": "a", "split": "train", "source": SOURCE}]
    kwargs = {}
    if kind == "source":
        report["source_sha256"] = "b" * 64
    elif kind == "trace":
        report["trace"]["elaboration_errors"] = True
    elif kind == "binding":
        report["exporter_sha256"] = "b" * 64
    elif kind == "trust":
        report["kernel_typechecked"] = True
    elif kind == "bytes":
        kwargs["max_bytes"] = 1
    elif kind == "rows":
        rows.append({"id": "b", "split": "train", "source": SOURCE})
        kwargs["max_train_rows"] = 1
    with pytest.raises(ValueError):
        ps.collect_training_observations(rows, capture_fn=lambda _: report, **kwargs)


def test_failed_capture_is_recorded_not_replaced_by_teacher():
    r = ps.collect_training_observations([{"id": "a", "split": "train", "source": "invalid"}],
                                         capture_fn=lambda _: {"ok": False, "reason": "fixture"})
    assert not r["observations"] and r["decisions"][0]["status"] == "capture_failed"


@pytest.mark.parametrize("output", [b"missing", ps.MARKER + b'{"schema":"x","schema":"y"}',
                                    ps.MARKER + b'{"n":1e9999999}', ps.MARKER + b'{"n":NaN}',
                                    ps.MARKER + b'{}\n' + ps.MARKER + b'{}'])
def test_transport_rejects_ambiguous_or_noncanonical_receipts(tmp_path, monkeypatch, output):
    monkeypatch.setattr(ps, "_run_bounded", lambda *a, **k: output)
    report = ps.capture_source("", project_root=tmp_path, environment_sha256="a" * 64)
    assert not report["ok"] and "trace" not in report


def test_report_generator_is_deterministic_and_refuses_overwrite(native_report, tmp_path):
    for directory in (tmp_path / "a", tmp_path / "b"):
        ps.write_capture_report(native_report, directory)
    assert (tmp_path / "a/summary.md").read_bytes() == (tmp_path / "b/summary.md").read_bytes()
    assert len((tmp_path / "a/summary.md").read_text().splitlines()) < 60
    assert json.loads((tmp_path / "a/capture.json").read_bytes()) == native_report
    with pytest.raises(FileExistsError):
        ps.write_capture_report(native_report, tmp_path / "a")
    forged = {**native_report, "proof_admitted": True}
    with pytest.raises(ValueError, match="trust"):
        ps.write_capture_report(forged, tmp_path / "forged")
    assert not (tmp_path / "forged").exists()


def test_empty_trace_does_not_bypass_validation_budgets(native_report):
    trace = {**native_report["trace"], "events": []}
    for budget in (True, 0, 20001):
        with pytest.raises(ValueError, match="validation request"):
            ps.validate_trace(trace, source=SOURCE, environment=native_report["environment"], node_budget=budget)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_universe_context_and_delayed_assignment_rejection(tmp_path):
    build = subprocess.run(["lean", "-o", str(tmp_path / "ProofState.olean"), str(ps.EXPORTER)],
                           cwd=ps.EXPORTER.parent, capture_output=True, text=True, timeout=40)
    assert build.returncode == 0, build.stdout + build.stderr
    import os
    env = dict(os.environ, LEAN_PATH=str(tmp_path) + os.pathsep + os.environ.get("LEAN_PATH", ""))
    fixture = Path(__file__).with_name("lean") / "ProofStateTest.lean"
    run = subprocess.run(["lean", str(fixture)], cwd=fixture.parent, env=env,
                         capture_output=True, text=True, timeout=40)
    assert run.returncode == 0, run.stdout + run.stderr
    lines = [line.removeprefix("JEVOPS_STATE_FIXTURE:") for line in run.stdout.splitlines()
             if line.startswith("JEVOPS_STATE_FIXTURE:")]
    assert len(lines) == 1
    analysis = ps.analyze_state(json.loads(lines[0]))
    assert len(analysis["components"]) == 1 and analysis["active_goals"] == 2
    assert any(dep[0] == "u" for d in analysis["dependencies"] for dep in d["unresolved"])
