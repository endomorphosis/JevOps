"""Synthetic compiler callbacks test protocol plumbing, not Lean validity."""
import copy
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from jevops import scoped_evaluation as evaluation
from jevops.graph_policy import GraphEditPolicy
from jevops.graph_refinement import fit_training
from jevops.rewrite_policy import body_of, choices
from jevops.structural_policy import StructuralEditPolicy, digest
from tests.test_structural_training import ENV, SOURCE, TARGET, fixture_receipt

pytestmark = pytest.mark.no_seal(reason="optional PyTorch and compiler-bound evaluation protocol")


@pytest.fixture(scope="module")
def fit():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    rows = [{"id": f"training_{i}", "split": "train", "family": f"train_{i}",
             "source": SOURCE.replace("bridge", f"training_{i}"), "target": TARGET.replace("bridge", f"training_{i}")}
            for i in range(2)]
    result = fit_training(fixture_receipt, rows=rows, environment_sha256=ENV, epochs=2)
    assert result["ok"]
    yield result
    torch.set_num_threads(old)


def rows():
    return [{"id": f"eval_{i}", "family": f"eval_{i}", "split": split,
             "source": SOURCE.replace("bridge", f"eval_{i}"), "target": TARGET.replace("bridge", f"eval_{i}")}
            for i, split in enumerate(evaluation.SPLITS)]


def compiler(source):
    # Vary synthetic binder flags to produce disjoint mock graphs. NOT Lean.
    r = fixture_receipt(source)
    wire = r["expression_dag"]["dag"]
    i = next(i for i in range(3) if f"eval_{i}" in source)
    wire["expressions"][2][2] = ("implicit", "strictImplicit", "instance")[i]
    r["expression_dag"]["dag_sha256"] = digest(wire)
    return r


def test_seeded_transfer_manifest_and_preservation_control():
    a = evaluation.transfer_rows()
    assert a == evaluation.transfer_rows() and a != evaluation.transfer_rows(7)
    assert {r["split"] for r in a} == set(evaluation.SPLITS)
    assert len({r["family"] for r in a}) == len(a) == 6
    assert sum(r["source"] == r["target"] for r in a) == 1
    assert any("∀" in r["source"] and "@f_" in r["target"] for r in a)


@pytest.mark.parametrize("seed", [True, -1, 2**32])
def test_bad_seed(seed):
    with pytest.raises(ValueError, match="seed"):
        evaluation.transfer_rows(seed)


def test_symbolic_choice_uses_lengths_only_identity_wins_ties():
    s = "theorem foo : True := by\n  exact True.intro\n"
    grammar = [{"body": body_of(s)[1]}, {"body": "exact False.elim"}, {"body": "trivial"}]
    p, logits = evaluation.length_proposal(s, grammar)
    assert p["choice"] == 2 and p["source"].endswith("  trivial\n")
    assert logits.tolist() == [-4., -4., -1.]
    assert not p["teacher_used"] and not p["solver_used"]
    p, _ = evaluation.length_proposal(s, grammar[:2])
    assert p["choice"] == 0 and p["source"] == s


@pytest.mark.parametrize("damage", ["hash", "family", "id", "text", "splits", "budget"])
def test_invalid_bindings_fail_before_compiler(fit, damage):
    f, rs, options = copy.deepcopy(fit), rows(), {}
    if damage == "hash":
        f["selected"] = "fixed_graph"
    elif damage == "family":
        rs[0]["family"] = f["training_families"][0]
    elif damage == "id":
        rs[0]["id"] = f["training_rows"][0]["id"]
    elif damage == "text":
        rs[0]["source"] = f["training_rows"][0]["source"]
    elif damage == "splits":
        rs[-1]["split"] = "train"
    else:
        options["max_compiles"] = 14
    with pytest.raises(ValueError):
        evaluation.evaluate_frozen(f, rs, lambda _: pytest.fail("compiled invalid manifest"), **options)


def test_renamed_native_shape_overlap_rejected_before_targets(fit):
    class Guard(dict):
        def __getitem__(self, key):
            assert key != "target", "read a label before detecting overlap"
            return super().__getitem__(key)
    with pytest.raises(ValueError, match="structural"):
        evaluation.evaluate_frozen(fit, [Guard(r) for r in rows()], fixture_receipt)


def test_all_rows_and_arms_committed_before_any_label_without_training(fit, monkeypatch):
    committed = []
    for cls in (GraphEditPolicy, StructuralEditPolicy):
        original = cls.predict
        def predict(self, source, context, _original=original):
            committed.append(source)
            return _original(self, source, context)
        monkeypatch.setattr(cls, "predict", predict)
        monkeypatch.setattr(cls, "train_step", lambda *a, **kw: pytest.fail("trained during evaluation"))
    monkeypatch.setattr(GraphEditPolicy, "train_batch", lambda *a, **kw: pytest.fail("batch trained during evaluation"))
    length = evaluation.length_proposal
    def symbolic(*args):
        committed.append(args[0])
        return length(*args)
    monkeypatch.setattr(evaluation, "length_proposal", symbolic)
    class Guard(dict):
        def __getitem__(self, key):
            if key == "target":
                assert len(committed) == 9
            return super().__getitem__(key)
    before = digest(fit)
    result = evaluation.evaluate_frozen(fit, [Guard(r) for r in rows()], compiler)
    assert result["models_unchanged"] and digest(fit) == before
    assert all(s["sample_count"] == s["loss_sample_count"] == 3 for s in result["summary"].values())
    assert result["source_type_shapes_disjoint"]
    assert not result["semantic_family_decontamination"] and not result["checkpoint_promoted"]


def test_bad_raw_model_choice_is_not_repaired_with_symbolic_output(fit, monkeypatch):
    def corrupt(self, source, context):
        return {"source": source.split(":= by")[0] + ":= by\n  exact unavailable\n", "choice": 1}
    monkeypatch.setattr(GraphEditPolicy, "predict", corrupt)
    result = evaluation.evaluate_frozen(fit, rows(), compiler)
    learned, symbolic = result["summary"]["learned"], result["summary"]["token_length"]
    assert learned["valid_count"] == learned["verified_saved_tokens"] == 0
    assert symbolic["valid_count"] == 3 and symbolic["verified_saved_tokens"] > 0
    assert not result["ok"] and not result["gates"]["all_arms_complete_validity_cost_and_loss"]
    assert all("unavailable" in r["prediction"]["source"] for r in result["results"] if r["arm"] == "learned")


def test_valid_grammar_but_failed_native_check_earns_no_savings(fit):
    def rejecting(source):
        return compiler(source) if "have " in source else {"theorem_ok": False}
    result = evaluation.evaluate_frozen(fit, rows(), rejecting)
    assert not result["ok"]
    assert result["summary"]["token_length"]["verified_saved_tokens"] == 0
    assert all(r["loss"] is None for r in result["results"])


def test_expression_cost_does_not_hide_source_length_growth(fit, monkeypatch):
    original = evaluation.choices
    def longer(source):
        return source.replace("exact h", "exact " + "id " * 20 + "h")
    def grammar(source, templates):
        return [*original(source, templates), {"body": body_of(longer(source))[1]}]
    monkeypatch.setattr(evaluation, "choices", grammar)
    def predict(self, source, context):
        return {"source": longer(source), "choice": len(grammar(source, self.templates)) - 1}
    monkeypatch.setattr(GraphEditPolicy, "predict", predict)
    result = evaluation.evaluate_frozen(fit, rows(), compiler)
    stats = result["summary"]["learned"]
    assert stats["valid_count"] == stats["nonregressing_count"] == 3  # Synthetic native receipt accepts it.
    assert stats["length_nonregressing_count"] == stats["verified_saved_tokens"] == 0
    assert not result["gates"]["all_arms_source_length_nonregression"]
    assert not result["ok"]


def test_failed_original_and_unreachable_reference_remain_in_denominators(fit):
    rs = rows()
    rs[1]["target"] = rs[1]["source"].replace("exact h", "assumption")  # Outside this mined grammar.
    def failing(source):
        return {"theorem_ok": False} if "eval_0" in source else compiler(source)
    result = evaluation.evaluate_frozen(fit, rs, failing)
    for s in result["summary"].values():
        assert s["sample_count"] == 3 and s["loss_sample_count"] == 1
    assert result["source_shape_coverage"] == 2 and not result["source_type_shapes_disjoint"]
    assert not result["ok"]


@pytest.mark.parametrize("reference", [None, "", ["not", "text"]])
def test_invalid_or_missing_label_is_never_identity_supervision(fit, reference):
    rs = rows()
    if reference is None:
        del rs[0]["target"]
    else:
        rs[0]["target"] = reference
    result = evaluation.evaluate_frozen(fit, rs, compiler)
    assert not result["ok"]
    assert all(s["sample_count"] == 3 and s["loss_sample_count"] == 2 for s in result["summary"].values())
    assert all(r["loss"] is None and "reference" in r["teacher_check"]["reason"]
               for r in result["results"] if r["id"] == "eval_0")


def test_report_generation_checks_hashes_and_preserves_existing_files(fit, tmp_path, capsys):
    result = evaluation.evaluate_frozen(fit, rows(), compiler)
    output = tmp_path / "output"
    evaluation.write_reports(fit, result, output)
    assert capsys.readouterr().out == ""
    record = json.loads((output / "measurement.json").read_text())
    assert record["summary"] == result["summary"]
    assert record["receipt_sha256"] == digest({k: v for k, v in result.items() if k != "receipt_sha256"})
    assert "not wall-time" in (output / "summary.md").read_text()
    with pytest.raises(FileExistsError):
        evaluation.write_reports(fit, result, output)
    result["summary"]["learned"]["verified_saved_tokens"] = 10000
    with pytest.raises(ValueError, match="receipts"):
        evaluation.write_reports(fit, result, tmp_path / "forged")
    assert not (tmp_path / "forged").exists()


def test_saved_native_control_keeps_per_split_failure_despite_aggregate_pass():
    # Historical native observations, NOT a new proof check or fresh holdout.
    record = json.loads((Path(__file__).with_name("fixtures") / "scoped_evaluation_control" / "measurement.json").read_text())
    for group in [record["summary"], *record["by_split"].values()]:
        assert all(s["sample_count"] == s["valid_count"] == s["nonregressing_count"] == s["loss_sample_count"]
                   for s in group.values())
    assert all(all(g.values()) for g in record["comparisons"].values())
    assert all(s["verified_saved_tokens"] == 42 and s["source_tokens"] == 69
               and s["raw_prediction_tokens"] == 27 for s in record["summary"].values())
    for split, arms in record["by_split"].items():
        for base in evaluation.ARMS[1:]:
            assert evaluation.acceptance_gates(arms["learned"], arms[base]) == record["split_gates"][split][base]
    for split in ("canary", "holdout"):
        assert not record["split_gates"][split]["token_length"]["expected_cosine_loss_nonregression"]
    assert not record["ok"] and not record["gates"]["all_splits_pass"]
    assert record["models_unchanged"] and not record["checkpoint_promoted"] and record["official_score"] is None


def test_cli_seals_protocol_before_compiling_and_report_only_calls_no_lean(fit, tmp_path, monkeypatch, capsys):
    import jevops.router_tuning as router
    from jevops.scoped_training import write_reports as training_reports
    # Runtime-generated test artifact, not manually maintained receipt JSON.
    training_dir = tmp_path / "training"
    t = {"schema": "fixture", "ok": False, "scope": "mock", "fit": fit,
         "teacher_discovery": {"pairs": [], "attempts": []}, "compile_attempts": [],
         "reason": "fixture", "model_trained": False, "checkpoint_promoted": False,
         "official_score": None, "evaluation_accessed": False}
    training_reports(t, training_dir)
    output = tmp_path / "run"
    monkeypatch.setattr(evaluation, "transfer_rows", lambda seed: rows())
    calls = []
    def compile_one(source):
        sealed = json.loads((output / "protocol.json").read_text())
        assert sealed["freeze_sha256"] == fit["freeze_sha256"] and sealed["manifest_sha256"] == digest(rows())
        calls.append(source)
        return compiler(source)
    monkeypatch.setattr(router, "_lean_compiler", lambda **kw: compile_one)
    args = ["--training-dir", str(training_dir), "--output-dir", str(output), "--environment-sha256", ENV]
    evaluation.main(args)
    assert calls and len(capsys.readouterr().out) < 400
    report_output = tmp_path / "report"
    monkeypatch.setattr(router, "_lean_compiler", lambda **kw: pytest.fail("report generation compiled"))
    monkeypatch.setattr(evaluation, "transfer_rows", lambda seed: pytest.fail("report generation created a new evaluation"))
    args[3] = str(report_output)
    assert evaluation.main([*args, "--report-from", str(output / "evaluation.json")]) == 0
    assert not (report_output / "evaluation.json").exists() and not (report_output / "protocol.json").exists()
    assert json.loads((report_output / "measurement.json").read_text()) == json.loads((output / "measurement.json").read_text())
    assert len(capsys.readouterr().out) < 400


def test_mismatched_grammars_cannot_be_called_matched_budget(fit):
    changed = copy.deepcopy(fit)
    changed["checkpoints"]["fixed_graph"]["templates"] = []
    changed["checkpoints"]["fixed_graph"]["weights"] = {}
    changed["freeze_sha256"] = digest({k: v for k, v in changed.items() if k != "freeze_sha256"})
    with pytest.raises(ValueError, match="unmatched grammar"):
        evaluation.evaluate_frozen(changed, rows(), lambda _: pytest.fail("compiled mismatched arms"))


def test_inference_side_effect_cannot_rewrite_frozen_model(fit, monkeypatch):
    original = GraphEditPolicy.predict
    def mutate(self, source, context):
        prediction = original(self, source, context)
        self.steps += 1
        return prediction
    monkeypatch.setattr(GraphEditPolicy, "predict", mutate)
    frozen = digest(fit)
    with pytest.raises(ValueError, match="mutated frozen"):
        evaluation.evaluate_frozen(fit, rows(), compiler)
    assert digest(fit) == frozen
