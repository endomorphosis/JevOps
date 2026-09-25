"""Mock receipts test admission plumbing; native tests below establish Lean behavior."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from jevops.expr_dag import CODEC, _bytes, root_summaries
from jevops.proof_trust import audit_axioms, top_level_declarations
from jevops.rewrite_distillation import curriculum_rows, run_distillation
from jevops.router_tuning import _lean_compiler
from jevops.solver_feedback import source_digest
from jevops.structural_training import collect_structural_pairs
from tests.test_expr_dag import ENV, base_wire
from tests.test_rewrite_distillation import fixture_oracle

SOURCE = "theorem bridge (p : Prop) (h : p) : p := by\n  have unused : p := h\n  exact h\n"
TARGET = "theorem bridge (p : Prop) (h : p) : p := by\n  exact h\n"


def fixture_receipt(source):
    """Trusted *test* callback, not actual compiled proof evidence."""
    declaration = top_level_declarations(source)[0]
    audit = audit_axioms(f"'{declaration}' does not depend on any axioms", [declaration])
    wire = base_wire()
    wire["roots"] = ["3", "3"]
    if "have " in source:
        wire["expressions"].append(["let", [["s", "u"]], False, "0", "0", "3"])
        wire["roots"][0] = "4"
    binding = {"dependency_environment_sha256": ENV, "dependency_closure_verified": False,
               "proof_admitted": False, "artifact_files_sha256": {"Main.olean": source_digest(source)},
               "codec_sha256": hashlib.sha256(CODEC.read_bytes()).hexdigest()}
    wire["environment"] = hashlib.sha256(_bytes(binding)).hexdigest()
    report = {"schema": "jevops-lean-expr-export/v1", "ok": True, "declaration": declaration,
              "exact_roundtrip": True, "kernel_typechecked": True, "axioms": [], "level_parameters": [],
              "dag": wire, "dag_sha256": hashlib.sha256(_bytes(wire)).hexdigest(), **binding}
    return {"theorem_ok": True, "source_sha256": source_digest(source),
            "compiled_source_sha256": source_digest(source + f"\n#print axioms {declaration}\n"),
            "kernel_audit": audit, "expression_dag": report}


def collect(compiler=fixture_receipt, **kwargs):
    return collect_structural_pairs([{"id": "train", "split": "train", "source": SOURCE}], {"train": TARGET},
                                    compile_fn=compiler, environment_sha256=ENV, **kwargs)


def test_root_costs_and_fingerprints_ignore_unrelated_nodes_and_numbering():
    first = base_wire()
    shifted = base_wire()
    shifted["expressions"] = [["nat", "7"], ["sort", "0"], ["bvar", "0"],
                               ["lam", [["s", "h"]], "explicit", "2", "2"],
                               ["lam", [["s", "p"]], "explicit", "1", "3"]]
    shifted["roots"] = ["0", "4"]
    a = root_summaries(first, environment=ENV)[0]
    assert root_summaries(shifted, environment=ENV)[1] == a
    assert a["unique_expression_nodes"] == 4 and a["expanded_expression_nodes"] == 5
    for field, value in ((1, [["s", "renamed"]]), (2, "implicit")):
        changed = copy.deepcopy(first)
        changed["expressions"][3][field] = value
        assert root_summaries(changed, environment=ENV)[0]["structure_sha256"] != a["structure_sha256"]


def test_only_strict_training_pairs_are_recompiled_and_ready_for_supervision():
    calls = []
    result = collect(lambda text: calls.append(text) or fixture_receipt(text))
    assert result["ok"] and calls == [SOURCE, TARGET]
    assert result["compile_calls"] == 2 and result["accepted_count"] == 1
    pair = result["pairs"][0]
    assert pair["teacher_admitted"] and pair["text"] == SOURCE and pair["target_text"] == TARGET
    assert pair["source_tokens"] > pair["target_tokens"]
    assert pair["source"]["proof"]["unique_expression_nodes"] == 5
    assert pair["target"]["proof"]["unique_expression_nodes"] == 4
    assert pair["source"]["type"] == pair["target"]["type"]
    assert len(result["graphs"]) == 2 and not result["graph_model_trained"]
    assert not result["dependency_closure_verified"] and not result["checkpoint_promoted"]
    assert result["official_score"] is None


def test_nontraining_targets_are_not_even_read_and_identities_are_not_compression():
    class Targets(dict):
        def get(self, key, default=None):
            assert key in {"train", "identity"}, "read an evaluation target"
            return super().get(key, default)
    rows = [{"id": "train", "split": "train", "source": SOURCE},
            {"id": "identity", "split": "train", "source": TARGET.replace("bridge", "identity")},
            *[{"id": split, "split": split, "source": SOURCE.replace("bridge", split)}
              for split in ("validation", "canary", "holdout")]]
    calls = []
    targets = Targets(train=TARGET, identity=rows[1]["source"], holdout=object())
    result = collect_structural_pairs(rows, targets, compile_fn=lambda s: calls.append(s) or fixture_receipt(s),
                                     environment_sha256=ENV)
    assert result["ok"] and calls == [SOURCE, TARGET]
    assert [d["status"] for d in result["decisions"]] == ["accepted", "identity_control_not_compression",
                                                           "excluded_split", "excluded_split", "excluded_split"]


@pytest.mark.parametrize("case", ["unaudited", "failed", "source", "compiled_source", "roundtrip", "kernel",
                                  "environment", "codec", "artifact", "digest", "type", "universes", "toolchain",
                                  "axiom", "axiom_growth", "expanded_growth", "shared_growth", "missing"])
def test_invalid_or_stale_evidence_cannot_create_teachers(case):
    def corrupted(text):
        receipt = fixture_receipt(text)
        if text != TARGET:
            return receipt
        report = receipt["expression_dag"]
        wire = report["dag"]
        if case == "unaudited":
            receipt["kernel_audit"]["accepted"] = False
        elif case == "failed":
            receipt["theorem_ok"] = False
        elif case in {"source", "compiled_source"}:
            receipt[case + "_sha256"] = "f" * 64
        elif case == "roundtrip":
            report["exact_roundtrip"] = False
        elif case == "kernel":
            report["kernel_typechecked"] = False
        elif case == "environment":
            report["dependency_environment_sha256"] = "b" * 64
        elif case == "codec":
            report["codec_sha256"] = "b" * 64
        elif case == "artifact":
            report["artifact_files_sha256"] = {}
        elif case == "digest":
            report["dag_sha256"] = "b" * 64
        elif case == "type":
            wire["roots"][1] = "0"
        elif case == "universes":
            report["level_parameters"] = [[["s", "u"]]]
        elif case == "toolchain":
            wire["lean_githash"] = "other"
        elif case in {"axiom", "axiom_growth"}:
            value = "sorryAx" if case == "axiom" else "Classical.choice"
            receipt["kernel_audit"]["axioms"] = report["axioms"] = [value]
        elif case in {"expanded_growth", "shared_growth"}:
            wire["expressions"].append(["app", "3", "3"])
            wire["roots"][0] = "4"
            if case == "shared_growth":
                wire["expressions"].append(["app", "4", "3"])
                wire["roots"][0] = "5"
            # Fake favorable reported costs cannot substitute for graph counts.
            report["storage"] = {"expression_nodes": 1, "root_expanded_expression_nodes": [1, 1]}
        else:
            receipt.pop("expression_dag")
        if case != "digest":
            report["dag_sha256"] = hashlib.sha256(_bytes(wire)).hexdigest()
        return receipt
    result = collect(corrupted)
    assert not result["ok"] and not result["pairs"] and not result["graphs"]
    assert result["decisions"][0]["status"] == "rejected"
    if case.endswith("growth") and case != "axiom_growth":
        assert result["decisions"][0]["reason"] == "proof_expression_growth"


@pytest.mark.parametrize("case", ["header", "hole", "helper", "unsafe", "no_shortening", "missing", "binder_default"])
def test_text_changes_and_unmeasured_targets_fail_before_compilation(case):
    source, target = SOURCE, TARGET
    if case == "header":
        target = target.replace(": p := by", ": True := by")
    elif case == "hole":
        source, target = (s.replace(": p := by", ": _ := by") for s in (source, target))
    elif case == "helper":
        source, target = ("def hidden := True\n" + s for s in (source, target))
    elif case == "unsafe":
        target = target.replace("exact h", "run_tac pure ()")
    elif case == "no_shortening":
        source, target = target, source
    elif case == "binder_default":
        source = "theorem nested (h : True := by\n have t : True := True.intro\n exact t) : True := by trivial"
        target = "theorem nested (h : True := by\n trivial) : True := by trivial"
    else:
        target = None
    def forbidden(_):
        pytest.fail("preflight should reject before compiling")
    result = collect_structural_pairs([{"id": "train", "source": source, "split": "train"}], {"train": target},
                                     compile_fn=forbidden, environment_sha256=ENV)
    assert not result["ok"] and result["compile_calls"] == 0


def test_bounds_duplicates_and_callback_failures_fail_closed():
    with pytest.raises(ValueError, match="budget"):
        collect(max_pairs=0)
    with pytest.raises(ValueError, match="budget"):
        collect(node_budget=True)
    def broken(_):
        raise TimeoutError("compiler timeout")
    result = collect(broken)
    assert not result["ok"] and result["compile_calls"] == 1
    assert result["decisions"][0]["error_type"] == "TimeoutError"
    result = collect(byte_budget=1)
    assert not result["pairs"] and not result["graphs"] and result["graph_bytes"] == 0
    assert result["decisions"][0]["reason"] == "dataset_byte_budget"
    with pytest.raises(ValueError, match="duplicate"):
        collect_structural_pairs([{"id": "a", "split": "train", "source": SOURCE},
                                  {"id": "b", "split": "holdout", "source": SOURCE + "\n"}], {},
                                 compile_fn=broken, environment_sha256=ENV)


def test_lossy_tactic_ir_cannot_be_used_as_a_verified_label(monkeypatch):
    from jevops import autoencoder as ae
    original = ae.decode_lean_ir
    monkeypatch.setattr(ae, "decode_lean_ir", lambda ir: original(ir).replace("exact h", "exact wrong"))
    result = collect()
    assert not result["ok"] and result["compile_calls"] == 0
    assert result["decisions"][0]["reason"] == "target_tactic_IR_roundtrip_mismatch"


def test_opt_in_distillation_consumes_pairs_before_training_not_holdout_labels():
    rows = [r for r in curriculum_rows() if r["family"] == "terminal_alias"]
    calls = []
    result = run_distillation(fixture_oracle, rows=rows, epochs=5,
                              structural_compile_fn=lambda s: calls.append(s) or fixture_receipt(s),
                              structural_environment_sha256=ENV)
    assert result["structural_pairs"]["ok"] and result["structural_pair_targets_used"]
    assert not result["graph_features_used_for_training"]
    assert result["model_step"] == 5 and result["train_ids"] == [rows[0]["id"]]
    assert len(calls) == 2 and all("distill_train_" in s for s in calls)
    events = [e["event"] for e in result["events"]]
    assert events.index("structural_training_pairs") < events.index("training") < events.index("final_holdout")
    blocked = run_distillation(fixture_oracle, rows=rows, epochs=5,
                               structural_compile_fn=lambda _: {"theorem_ok": True},
                               structural_environment_sha256=ENV)
    assert not blocked["ok"] and blocked["model_step"] == 0 and blocked["reason"] == "structural_teacher_gate"
    with pytest.raises(ValueError, match="trajectory"):
        run_distillation(fixture_oracle, trajectory_training=True, structural_compile_fn=fixture_receipt,
                         structural_environment_sha256=ENV)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_compiler_capture_pair_and_sparse_learning_rounds(tmp_path):
    from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, export_dags=True, environment_sha256=ENV)
    result = collect(compiler)
    assert result["ok"], result["decisions"]
    pair = result["pairs"][0]
    assert pair["source"]["export"]["kernel_typechecked"] and pair["target"]["export"]["kernel_typechecked"]
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True, freeze_reconstruction_heads=True,
                                                     learning_rate=.15, warmup_steps=0))
    examples = [coerce_training_example(p) for p in result["pairs"]]
    model.prepare_rewrite_training(examples)
    before = model.rewrite_objective(examples[0])
    operation_ce = model._sequence_loss(examples[0])
    for _ in range(12):
        model.train_batch(examples)
    after = model.rewrite_objective(examples[0])
    assert after["cross_entropy"] < before["cross_entropy"]
    assert after["expected_cosine_loss"] < before["expected_cosine_loss"]
    assert model._sequence_loss(examples[0]) == operation_ce
    prediction = model.predict_ir(SOURCE)
    from jevops.router_tuning import _ir_body, _render_source, _source_parts
    prefix, _, theorem = _source_parts(SOURCE)
    rendered = _render_source(prefix, _ir_body(prediction), has_theorem=theorem)
    assert rendered.strip() == TARGET.strip()
    assert compiler(rendered)["theorem_ok"]
    rejected = compiler("theorem bad : False := by\n  sorry\n")
    assert not rejected["theorem_ok"] and not rejected["expression_dag"]["ok"]


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_structural_distillation_and_generated_report(tmp_path):
    from jevops.refactor_report import generate_report
    rows = [r for r in curriculum_rows() if r["family"] == "terminal_alias"]
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True, measure_proofs=True)
    structural = _lean_compiler(project_root=tmp_path, kernel_only=True, export_dags=True, environment_sha256=ENV)
    result = run_distillation(compiler, rows=rows, epochs=12, freeze_reconstruction_heads=True,
                              cost_guard=True, structural_compile_fn=structural, structural_environment_sha256=ENV)
    assert result["ok"], {k: result.get(k) for k in ("reason", "structural_pairs", "development_gates", "holdout_gate", "cost_gate")}
    assert result["structural_pairs"]["accepted_count"] == 1
    assert result["model_step"] == 12 and result["reconstruction_heads_unchanged"]
    assert result["holdout"]["holdout"]["verified_shortening"] == 1
    before, after = result["before"]["canary"], result["after"]["canary"]
    assert after["rewrite_cross_entropy"] < before["rewrite_cross_entropy"]
    assert after["rewrite_expected_cosine_loss"] < before["rewrite_expected_cosine_loss"]
    assert after["cross_entropy"] == before["cross_entropy"]
    assert not result["graph_features_used_for_training"] and not result["checkpoint_promoted"]
    raw = tmp_path / "run.json"
    raw.write_text(json.dumps(result, allow_nan=False))
    report = generate_report(raw, tmp_path / "report", archive_inputs=True)
    summary = Path(report["summary"]).read_text()
    assert "Structural training-pair gate: PASS; 1 compressed pairs" in summary
    assert "Teacher/prediction cost guard: PASS" in summary


@pytest.mark.skipif(not os.environ.get("JEVOPS_MATHLIB_PROJECT"), reason="requires Mathlib")
def test_mathlib_structural_pair_is_checked_in_project_context():
    project = Path(os.environ["JEVOPS_MATHLIB_PROJECT"])
    source = "import Mathlib\ntheorem bridge_ring (x : Int) : x + 0 = x := by\n  have h : x + 0 = x := by ring\n  exact h\n"
    target = "import Mathlib\ntheorem bridge_ring (x : Int) : x + 0 = x := by\n  ring\n"
    compiler = _lean_compiler(project_root=project, use_lake=True, kernel_only=True, export_dags=True,
                              environment_sha256=ENV, timeout=60)
    result = collect_structural_pairs([{"id": "mathlib", "split": "train", "source": source}], {"mathlib": target},
                                     compile_fn=compiler, environment_sha256=ENV)
    assert result["ok"], result["decisions"]
    assert result["pairs"][0]["target"]["export"]["kernel_typechecked"]


def test_compiler_capture_is_opt_in_and_requires_kernel_audit_and_context(tmp_path):
    with pytest.raises(ValueError, match="kernel-only"):
        _lean_compiler(project_root=tmp_path, export_dags=True, environment_sha256=ENV)
    with pytest.raises(ValueError, match="fingerprint"):
        _lean_compiler(project_root=tmp_path, kernel_only=True, export_dags=True)
