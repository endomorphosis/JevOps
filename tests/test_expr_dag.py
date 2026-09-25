from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zlib

import pytest

from jevops.expr_dag import (CODEC, MARKER, METADATA_POLICY, SCHEMA, export_olean, loads_dag,
                             pack_dag, unpack_dag, validate_dag)

ENV = "a" * 64
LEAN = shutil.which("lean")


def base_wire():
    # fun p : Prop => fun h : p => h; node 1 refers to different binders.
    return {"schema": SCHEMA, "environment": ENV, "lean_version": "fixture", "lean_githash": "fixture",
            "metadata_policy": METADATA_POLICY, "levels": [["zero"]], "expressions": [
                ["sort", "0"], ["bvar", "0"],
                ["lam", [["s", "h"]], "explicit", "1", "1"],
                ["lam", [["s", "p"]], "explicit", "0", "2"]], "roots": ["3"]}


def test_shared_bvars_are_storage_not_cross_scope_semantic_equality():
    wire = base_wire()
    stats = validate_dag(wire, environment=ENV)
    assert stats["expression_nodes"] == 4 and stats["root_expanded_expression_nodes"] == [5]
    assert stats["root_expression_depth"] == [3] and stats["closed"]
    assert not stats["kernel_typechecked"] and not stats["proof_admitted"]
    data = pack_dag(wire, environment=ENV)
    assert unpack_dag(data, environment=ENV) == wire
    assert loads_dag(json.dumps(wire).encode(), environment=ENV) == wire
    with pytest.raises(ValueError, match="toolchain"):
        validate_dag(wire, environment=ENV, toolchain=("different", "different"))


@pytest.mark.parametrize("case", ["cycle", "forward", "bad_root", "loose", "wrong_scope", "negative",
                                  "leading_zero", "number", "bool_index", "missing", "extra", "unknown",
                                  "fvar", "mvar", "level_mvar", "duplicate", "unreachable", "universe",
                                  "environment", "metadata_policy", "binder", "name", "large_bvar",
                                  "bad_let", "syntax_metadata"])
def test_malformed_dags_fail_closed(case):
    wire = base_wire()
    e = wire["expressions"]
    if case == "cycle":
        e[3][4] = "3"
    elif case == "forward":
        e[2][4] = "3"
    elif case == "bad_root":
        wire["roots"] = ["999"]
    elif case == "loose":
        wire["roots"] = ["1", "3"]
    elif case == "wrong_scope":
        e[3][3] = "1"  # Binder does not scope over its own domain.
    elif case in {"negative", "leading_zero", "number", "bool_index", "large_bvar"}:
        e[1][1] = {"negative": "-1", "leading_zero": "00", "number": 0,
                    "bool_index": True, "large_bvar": "65536"}[case]
    elif case == "missing":
        wire.pop("schema")
    elif case == "extra":
        wire["admitted"] = True
    elif case in {"unknown", "fvar", "mvar"}:
        e[1][0] = case
    elif case == "level_mvar":
        wire["levels"][0] = ["mvar", [["s", "u"]]]
    elif case == "duplicate":
        e.append(copy.deepcopy(e[0]))
        wire["roots"].append("4")
    elif case == "unreachable":
        e.append(["nat", "123"])
    elif case == "universe":
        e[0][1] = "1"
    elif case == "environment":
        wire["environment"] = "b" * 64
    elif case == "metadata_policy":
        wire["metadata_policy"] = "drop-metadata"
    elif case == "binder":
        e[3][2] = "guess"
    elif case == "name":
        e[3][1] = "p"
    elif case == "bad_let":
        e[3] = ["let", [["s", "p"]], "true", "0", "0", "2"]
    elif case == "syntax_metadata":
        e.append(["mdata", [[[["s", "k"]], ["syntax", "missing"]]], "3"])
        wire["roots"] = ["4"]
    with pytest.raises(ValueError):
        validate_dag(wire, environment=ENV)


def test_budgets_and_compressed_input_are_bounded(monkeypatch):
    from jevops import expr_dag as codec
    wire = base_wire()
    for n in (0, True, -1, 100001, 1):
        with pytest.raises(ValueError):
            validate_dag(wire, environment=ENV, node_budget=n)
    compressed = pack_dag(wire, environment=ENV)
    for bad in (compressed[:-1], compressed + b"extra", compressed + compressed, b"garbage"):
        with pytest.raises(ValueError):
            unpack_dag(bad, environment=ENV)
    raw = json.dumps(wire).encode()
    with pytest.raises(ValueError):
        loads_dag(raw.replace(b'"roots":', b'"schema":"duplicate", "roots":'), environment=ENV)
    with pytest.raises(ValueError):
        loads_dag(raw.replace(b'"3"', b'1e999999999'), environment=ENV)
    monkeypatch.setattr(codec, "MAX_BYTES", 512)
    with pytest.raises(ValueError):
        unpack_dag(zlib.compress(b"x" * 100000), environment=ENV)


def test_exponential_tree_counts_do_not_expand_the_dag():
    wire = base_wire()
    wire["levels"], wire["expressions"] = [], [["nat", "0"]]
    for i in range(1, 200):
        wire["expressions"].append(["app", str(i-1), str(i-1)])
    wire["roots"] = ["199"]
    result = validate_dag(wire, environment=ENV)
    assert result["expression_nodes"] == 200
    assert result["root_expanded_expression_nodes"] == [2**200 - 1]
    assert result["zlib_bytes"] < result["json_bytes"]
    for i in range(200, 257):
        wire["expressions"].append(["app", str(i-1), str(i-1)])
    wire["roots"] = ["256"]
    with pytest.raises(ValueError, match="depth"):
        validate_dag(wire, environment=ENV)


def test_noncanonical_numbering_and_excessive_universe_arity_are_rejected():
    wire = base_wire()
    wire["expressions"] = [["bvar", "0"], ["sort", "0"],
                            ["lam", [["s", "h"]], "explicit", "0", "0"],
                            ["lam", [["s", "p"]], "explicit", "1", "2"]]
    with pytest.raises(ValueError, match="noncanonical"):
        validate_dag(wire, environment=ENV)
    wire = base_wire()
    wire["expressions"] = [["const", [["s", "fake"]], ["0"] * 257]]
    wire["roots"] = ["0"]
    with pytest.raises(ValueError, match="arity"):
        validate_dag(wire, environment=ENV)


@pytest.fixture(scope="module")
def native_wire(tmp_path_factory):
    if LEAN is None:
        pytest.skip("requires Lean")
    directory = tmp_path_factory.mktemp("native-expr-dag")
    build = subprocess.run([LEAN, "-o", str(directory / "ExprDAG.olean"), str(CODEC)],
                           cwd=CODEC.parent, capture_output=True, text=True, timeout=45)
    assert build.returncode == 0, build.stdout + build.stderr
    env = dict(os.environ, LEAN_PATH=str(directory) + os.pathsep + os.environ.get("LEAN_PATH", ""))
    fixture = Path(__file__).with_name("lean") / "ExprDAGTest.lean"
    run = subprocess.run([LEAN, str(fixture)], cwd=fixture.parent, env=env,
                         capture_output=True, text=True, timeout=45)
    assert run.returncode == 0, run.stdout + run.stderr
    lines = [s.removeprefix("JEVOPS_DAG_FIXTURE:") for s in run.stdout.splitlines() if s.startswith("JEVOPS_DAG_FIXTURE:")]
    assert len(lines) == 1
    return json.loads(lines[0])


def native_roundtrip(wire, environment=ENV):
    return subprocess.run([LEAN, "--run", str(CODEC), "roundtrip", environment, "50000"],
                          input=json.dumps(wire), capture_output=True, text=True, timeout=30)


def test_native_constructors_binders_universes_names_metadata_and_literals_roundtrip(native_wire):
    wire = native_wire
    stats = validate_dag(wire, environment=ENV)
    assert stats["root_expanded_expression_nodes"][-1] == 2**25 - 1
    assert stats["expression_nodes"] < 100
    assert {r[0] for r in wire["levels"]} == {"zero", "param", "succ", "max", "imax"}
    assert {r[2] for r in wire["expressions"] if r[0] == "lam"} == {"explicit", "implicit", "strictImplicit", "instance"}
    assert {r[2] for r in wire["expressions"] if r[0] == "let"} == {True, False}
    constants = [r[1] for r in wire["expressions"] if r[0] == "const"]
    assert [["s", "A.B"]] in constants and [["s", "A"], ["s", "B"]] in constants
    assert [["s", "A"], ["n", "7"]] in constants and [["s", "A"], ["s", "7"]] in constants
    metadata = [r[1] for r in wire["expressions"] if r[0] == "mdata"]
    assert len(metadata) == 2 and metadata[0] == list(reversed(metadata[1]))
    assert metadata[0][1][1] == ["nat", str(2**128)]
    restored = unpack_dag(pack_dag(wire, environment=ENV), environment=ENV)
    run = native_roundtrip(restored)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout.removeprefix(MARKER)) == wire


@pytest.mark.parametrize("case", ["cycle", "metadata", "toolchain", "environment", "unreachable", "loose"])
def test_native_decoder_rejects_corruption(native_wire, case):
    wire = copy.deepcopy(native_wire)
    if case == "cycle":
        last = len(wire["expressions"]) - 1
        wire["expressions"][last] = ["app", str(last), str(last)]
    elif case == "metadata":
        row = next(r for r in wire["expressions"] if r[0] == "mdata")
        row[1][0][1] = ["syntax", "missing"]
    elif case == "toolchain":
        wire["lean_githash"] = "wrong"
    elif case == "environment":
        wire["environment"] = "b" * 64
    elif case == "unreachable":
        wire["expressions"].append(["nat", "999999"])
    else:
        wire["roots"].append(str(next(i for i, r in enumerate(wire["expressions"]) if r[0] == "bvar")))
    run = native_roundtrip(wire)
    assert run.returncode != 0


@pytest.mark.skipif(LEAN is None, reason="requires Lean")
def test_export_real_universe_polymorphic_proof_rechecks_native_kernel(tmp_path):
    source = "universe u\ntheorem same {α : Sort u} (x : α) : x = x := by\n  rfl\n"
    (tmp_path / "Main.lean").write_text(source)
    run = subprocess.run([LEAN, "-o", str(tmp_path / "Main.olean"), "Main.lean"],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    context = hashlib.sha256(b"isolated-core-fixture").hexdigest()
    report = export_olean(directory=tmp_path, declaration="same", project_root=tmp_path,
                          environment_sha256=context)
    assert report["ok"], report
    assert report["exact_roundtrip"] and report["kernel_typechecked"]
    assert report["axioms"] == [] and not report["proof_admitted"]
    assert report["level_parameters"] == [[["s", "u"]]]
    assert len(report["dag"]["roots"]) == 2
    assert not report["dependency_closure_verified"]
    assert "Main.olean" in report["artifact_files_sha256"]
    packed = pack_dag(report["dag"], environment=report["dag"]["environment"])
    assert unpack_dag(packed, environment=report["dag"]["environment"]) == report["dag"]
    small = export_olean(directory=tmp_path, declaration="same", project_root=tmp_path,
                         environment_sha256=context, node_budget=1)
    assert not small["ok"] and not small["proof_admitted"]


def test_export_fails_for_missing_artifact_or_bad_identity(tmp_path):
    assert not export_olean(directory=tmp_path, declaration="same", project_root=tmp_path,
                            environment_sha256=ENV)["ok"]
    with pytest.raises(ValueError):
        export_olean(directory=tmp_path, declaration="same", project_root=tmp_path,
                     environment_sha256="unpinned")


@pytest.mark.skipif(not os.environ.get("JEVOPS_MATHLIB_PROJECT"), reason="requires Mathlib")
def test_mathlib_theorem_export_uses_project_toolchain(tmp_path):
    project = Path(os.environ["JEVOPS_MATHLIB_PROJECT"])
    source = tmp_path / "Main.lean"
    source.write_text("import Mathlib\ntheorem ring_dag (x : Int) : x + 0 = x := by ring\n")
    run = subprocess.run(["lake", "env", "lean", "-R", str(tmp_path), "-o",
                          str(tmp_path / "Main.olean"), str(source)], cwd=project,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    report = export_olean(directory=tmp_path, declaration="ring_dag", project_root=project,
                          use_lake=True, environment_sha256=ENV, timeout=60)
    assert report["ok"] and report["kernel_typechecked"], report
    assert report["exact_roundtrip"] and not report["proof_admitted"]
    assert report["storage"]["expression_nodes"] > 0
