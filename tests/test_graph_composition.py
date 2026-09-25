"""Mocked policy/compiler plumbing is not native Lean or learned performance."""
import copy
import json
from pathlib import Path
import shutil

import pytest

torch = pytest.importorskip("torch")

from jevops import graph_composition as composition
from jevops.composition_curriculum import path_states, training_edges, training_rows, transfer_rows
from jevops.graph_policy import GraphEditPolicy
from jevops.graph_refinement import fit_training
from jevops.rewrite_policy import body_of, choices, mine_template
from jevops.structural_policy import StructuralEditPolicy, digest
from tests.test_structural_training import ENV, fixture_receipt

pytestmark = pytest.mark.no_seal(reason="optional PyTorch runtime and compiler-bound composition")


def templates():
    bank = {rule["id"]: rule for r in training_rows()
            if (rule := mine_template(r["source"], body_of(r["target"])[1]))}
    return [bank[k] for k in sorted(bank)]


def root_path():
    edges = training_rows()[5:]
    return [r["source"] for r in edges] + [edges[-1]["target"]]


def checker(compiler=fixture_receipt, **kwargs):
    return composition.CheckedCompiler(compiler, environment_sha256=ENV, toolchain=("fixture", "fixture"), **kwargs)


def scripted_model(monkeypatch, states, *, toolchain=("fixture", "fixture")):
    """An oracle for runner tests ONLY, never used in measured experiments."""
    model = GraphEditPolicy(templates(), environment_sha256=ENV, toolchain=toolchain)
    observed = []
    def predict(source, context):
        context.wire(source, ENV, model.toolchain)  # Stale preceding-state DAGs fail.
        observed.append(source)
        at = states.index(source)
        target = states[at+1] if at+1 < len(states) else source
        rows = model.rows(source, context)
        choice = next(i for i, r in enumerate(rows) if r["body"] == body_of(target)[1])
        return {"source": target, "choice": choice}
    monkeypatch.setattr(model, "predict", predict)
    return model, observed


def test_paths_keep_parent_split_and_have_no_invented_terminal_labels():
    rows = training_rows()
    assert rows == training_rows() and rows != training_rows(0)
    assert len(rows) == 8 and len(templates()) == 4
    assert {r["split"] for r in rows} == {"train"}
    assert len({r["parent_id"] for r in rows[5:]}) == 1
    assert all(r["source"] != r["target"] for r in rows)
    assert rows[-1]["target"] not in {r["source"] for r in rows[5:]}
    # Grammar-only fixture preflight. These are not blind mathematical holdouts.
    for row in transfer_rows():
        states = path_states(row)
        assert len(states) == 4
        assert not {row["family"]} & {r["family"] for r in rows}
        for a, b in zip(states, states[1:]):
            assert any(c["body"] == body_of(b)[1] for c in choices(a, templates()))


@pytest.mark.parametrize("seed", [True, -1, 2**32, "x"])
def test_bad_seeds(seed):
    for generate in (training_rows, transfer_rows):
        with pytest.raises(ValueError, match="seed"):
            generate(seed)


def test_training_rejects_eval_paths_before_labels():
    class Guard(dict):
        def __getitem__(self, key):
            if key in {"states", "source"}:
                pytest.fail("nontraining labels accessed")
            return super().__getitem__(key)
    with pytest.raises(ValueError, match="training paths only"):
        training_edges([Guard(split="holdout")])


@pytest.mark.parametrize("damage", ["first", "header", "length", "identity", "duplicate"])
def test_disconnected_or_nonshortening_training_paths_fail(damage):
    path = {"id": "t", "family": "t", "split": "train", "source": root_path()[0], "states": root_path()}
    if damage == "first":
        path["source"] = path["states"][1]
    elif damage == "header":
        path["states"][1] = path["states"][1].replace("theorem ", "theorem changed_")
    elif damage == "length":
        path["states"] = path["states"] * 3
    elif damage == "identity":
        path["states"][1] = path["states"][0]
    with pytest.raises(ValueError):
        training_edges([path, path] if damage == "duplicate" else [path])


def test_rollout_rechecks_each_state_refreshes_context_and_stops_without_optimality_claim(monkeypatch):
    states = root_path()
    model, observed = scripted_model(monkeypatch, states)
    calls = []
    checks = checker(lambda source: calls.append(source) or fixture_receipt(source))
    before = model.to_dict()
    result = composition.rollout(model, states[0], checks, max_edits=4)
    assert result["ok"] and result["committed_edits"] == 3 and result["stop_reason"] == "identity"
    assert result["final_source"] == states[-1] and result["verified_saved_tokens"] == 19
    assert observed == calls == states
    assert result["model_unchanged"] and model.to_dict() == before
    assert not result["minimality_proven"] and not result["teacher_used"] and not result["alternate_candidate_search"]
    single = composition.rollout(model, states[0], checks, max_edits=1)
    assert single["stop_reason"] == "edit_limit" and single["verified_saved_tokens"] == 15
    assert single["model_sha256"] == result["model_sha256"]
    assert calls == states  # Cache reuse is bounded to this run, not fresh verification.


@pytest.mark.parametrize("damage", ["compile", "growth", "axioms", "type", "toolchain", "stale", "budget"])
def test_later_failure_never_scores_safe_prefix_or_tries_another_candidate(monkeypatch, damage):
    states = root_path()
    model, observed = scripted_model(monkeypatch, states)
    def compiler(source):
        if source == states[2] and damage == "compile":
            return {"theorem_ok": False}
        if source == states[2] and damage == "stale":
            return fixture_receipt(states[1])
        receipt = fixture_receipt(source)
        if source == states[2]:
            export = receipt["expression_dag"]
            wire = export["dag"]
            if damage == "growth":
                wire["expressions"].append(["let", [["s", "growth"]], False, "0", "0", "3"])
                wire["roots"][0] = "4"
            elif damage == "type":
                wire["expressions"][2][2] = "implicit"
            elif damage == "toolchain":
                wire["lean_version"] = "other"
            elif damage == "axioms":
                receipt["kernel_audit"]["axioms"] = export["axioms"] = ["Classical.choice"]
            export["dag_sha256"] = digest(wire)
        return receipt
    result = composition.rollout(model, states[0], checker(compiler, max_compiles=2 if damage == "budget" else 16))
    assert not result["ok"] and result["stop_reason"] == "rejected_raw_edit"
    assert result["committed_edits"] == 1 and observed == states[:2]
    assert result["final_source"] == states[1] and result["safe_prefix_saved_tokens"] == 15
    assert result["verified_saved_tokens"] == 0  # Never turn rollback into apparent success.
    assert result["trace"][-1]["prediction"]["source"] == states[2]


@pytest.mark.parametrize("budget", [True, 0, 9, "3"])
def test_bad_rollout_budget_never_calls_compiler(monkeypatch, budget):
    states = root_path()
    model, _ = scripted_model(monkeypatch, states)
    with pytest.raises(ValueError, match="edit budget"):
        composition.rollout(model, states[0], checker(lambda _: pytest.fail("compiled")), max_edits=budget)


def test_out_of_grammar_output_and_weight_mutation_fail_closed(monkeypatch):
    states = root_path()
    model, _ = scripted_model(monkeypatch, states)
    original = model.predict
    def bad_output(source, context):
        output = original(source, context)
        output["source"] = body_of(source)[0] + "\n  exact nonexistent\n"
        return output
    monkeypatch.setattr(model, "predict", bad_output)
    result = composition.rollout(model, states[0], checker())
    assert not result["ok"] and result["verified_saved_tokens"] == 0
    assert "outside frozen grammar" in result["trace"][0]["check"]["reason"]
    def update(source, context):
        model.steps += 1
        return original(source, context)
    monkeypatch.setattr(model, "predict", update)
    with pytest.raises(ValueError, match="changed frozen model"):
        composition.rollout(model, states[0], checker())


@pytest.fixture(scope="module")
def training_run():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        rows = training_rows()
        allowed = {s for r in rows for s in (r["source"], r["target"])}
        def compiler(source):
            assert source in allowed, "nontraining source used for training"
            return fixture_receipt(source)
        yield fit_training(compiler, rows=rows, environment_sha256=ENV, epochs=2)
    finally:
        torch.set_num_threads(old)


def mock_transfer_compiler(rows):
    def compiler(source):
        receipt = fixture_receipt(source)
        # Artificial closed DAGs with distinct binder annotations test plumbing,
        # not actual proof/type shapes or semantic correctness.
        index = 1 + next(i for i, row in enumerate(rows) if row["id"] in source)
        wire = receipt["expression_dag"]["dag"]
        flags = ("explicit", "implicit", "strictImplicit", "instance")
        wire["expressions"][2][2], wire["expressions"][3][2] = flags[index % 4], flags[index // 4]
        receipt["expression_dag"]["dag_sha256"] = digest(wire)
        return receipt
    return compiler


def test_evaluation_commits_all_raw_paths_before_labels_and_never_updates(training_run, monkeypatch):
    fit = training_run
    before = digest(fit)
    committed = {}
    original = composition.rollout
    def counted(model, source, *args, **kwargs):
        run = original(model, source, *args, **kwargs)
        committed[source] = committed.get(source, 0) + 1
        return run
    monkeypatch.setattr(composition, "rollout", counted)
    for cls in (GraphEditPolicy, StructuralEditPolicy):
        monkeypatch.setattr(cls, "train_step", lambda *a, **k: pytest.fail("evaluation update"))
    monkeypatch.setattr(GraphEditPolicy, "train_batch", lambda *a, **k: pytest.fail("evaluation update"))
    class Guard(dict):
        def __getitem__(self, key):
            if key == "states":
                assert committed[self["source"]] == 5
            return super().__getitem__(key)
    rows = [Guard(r) for r in transfer_rows()]
    result = composition.evaluate_composition(fit, rows, mock_transfer_compiler(rows))
    assert result["models_unchanged"] and digest(fit) == before
    assert all(s["teacher_steps"] == s["labeled_teacher_steps"] == 18 for s in result["summary"].values())
    for row in result["results"]:
        runs = row["runs"]
        assert runs["selected_one"]["model_sha256"] == runs["selected_composed"]["model_sha256"]
        assert runs["fixed_one"]["model_sha256"] == runs["fixed_composed"]["model_sha256"]
    assert result["summary"]["selected_one"]["cross_entropy"] == result["summary"]["selected_composed"]["cross_entropy"]
    assert not result["checkpoint_promoted"] and result["official_score"] is None
    assert "not final-output reconstruction" in composition.render_summary(fit, result)
    result["ok"] = not result["ok"]
    with pytest.raises(ValueError, match="receipts"):
        composition.render_summary(fit, result)


@pytest.mark.parametrize("damage", ["hash", "family", "shape", "missing_split"])
def test_evaluation_rejects_overlap_before_accessing_path_labels(training_run, damage):
    fit = copy.deepcopy(training_run)
    rows = transfer_rows()
    class Guard(dict):
        def __getitem__(self, key):
            if key == "states":
                pytest.fail("overlapping evaluation labels accessed")
            return super().__getitem__(key)
    if damage == "hash":
        fit["seed"] += 1
    elif damage == "family":
        rows[0]["family"] = fit["training_families"][0]
    elif damage == "missing_split":
        rows = [r for r in rows if r["split"] != "holdout"]
    # fixture_receipt deliberately has the training shape for damage == shape.
    with pytest.raises(ValueError):
        composition.evaluate_composition(fit, [Guard(r) for r in rows], fixture_receipt)


def test_missing_teacher_edge_is_not_reported_as_zero_loss_or_full_coverage(training_run):
    rows = transfer_rows()
    bad = rows[0]["states"][-1]
    base = mock_transfer_compiler(rows)
    def compiler(source):
        return {"theorem_ok": False} if source == bad else base(source)
    result = composition.evaluate_composition(training_run, rows, compiler)
    assert not result["ok"] and not result["gates"]["complete_cost_and_loss_coverage"]
    assert all(s["labeled_teacher_steps"] == 17 and s["loss_sample_count"] == 5 for s in result["summary"].values())
    assert result["results"][0]["losses"]["selected"][-1] is None


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires native Lean")
def test_native_each_composed_step_passes_kernel_and_cost_checks(tmp_path, monkeypatch):
    # Prescribed choices test fresh native rollout checking, not model learning.
    from jevops.router_tuning import _lean_compiler
    native = _lean_compiler(project_root=tmp_path, kernel_only=True, export_dags=True, environment_sha256=ENV)
    states = root_path()
    first = native(states[0])
    wire = first["expression_dag"]["dag"]
    toolchain = (wire["lean_version"], wire["lean_githash"])
    model, observed = scripted_model(monkeypatch, states, toolchain=toolchain)
    checks = composition.CheckedCompiler(lambda s: first if s == states[0] else native(s),
                                         environment_sha256=ENV, toolchain=toolchain)
    result = composition.rollout(model, states[0], checks)
    assert result["ok"] and result["committed_edits"] == 3 and result["verified_saved_tokens"] == 19
    assert observed == states[:-1] and len(checks.compiler.attempts) == 4
    for step in result["trace"]:
        check = step["check"]
        assert step["committed"] and check["verified"] and check["strict_shortening"]
        for key in ("unique_expression_nodes", "expanded_expression_nodes"):
            assert check["prediction_proof"][key] <= check["source_proof"][key]


@pytest.mark.parametrize("bad_protocol", [False, True])
def test_cli_persists_fit_before_generating_labels_and_preserves_failures(training_run, tmp_path, monkeypatch, bad_protocol):
    from jevops import router_tuning
    output = tmp_path / "run"
    original_rows = transfer_rows()
    monkeypatch.setattr(router_tuning, "_lean_compiler", lambda **k: mock_transfer_compiler(original_rows))
    monkeypatch.setattr(composition, "fit_training", lambda *a, **k: training_run)
    def generate(seed):
        assert json.loads((output / "training.json").read_text()) == training_run
        if bad_protocol:
            raise ValueError("invalid manifest")
        return original_rows
    monkeypatch.setattr(composition, "transfer_rows", generate)
    code = composition.main(["--environment-sha256", ENV, "--output-dir", str(output)])
    if bad_protocol:
        assert code == 1 and not (output / "evaluation.json").exists()
        failure = json.loads((output / "failure.json").read_text())
        assert failure["freeze_sha256"] == training_run["freeze_sha256"] and not failure["checkpoint_promoted"]
    else:
        result = json.loads((output / "evaluation.json").read_text())
        assert code == (0 if result["ok"] else 1)
        assert (output / "summary.md").read_text() == composition.render_summary(training_run, result)
        assert json.loads((output / "measurement.json").read_text()) == composition.measurement_record(training_run, result)
    with pytest.raises(SystemExit):
        composition.main(["--environment-sha256", ENV, "--output-dir", str(output)])


@pytest.fixture(scope="module")
def report_input(training_run, tmp_path_factory):
    root = tmp_path_factory.mktemp("composition-report-input")
    rows = transfer_rows()
    result = composition.evaluate_composition(training_run, rows, mock_transfer_compiler(rows))
    (root / "training.json").write_text(json.dumps(training_run, sort_keys=True))
    (root / "evaluation.json").write_text(json.dumps(result, sort_keys=True))
    return root, result


def test_report_generator_writes_large_artifacts_without_printing_them(report_input, tmp_path, capsys, monkeypatch):
    from jevops import graph_reports, router_tuning
    root, result = report_input
    monkeypatch.setattr(GraphEditPolicy, "train_step", lambda *a, **k: pytest.fail("reporting trained a model"))
    monkeypatch.setattr(router_tuning, "_lean_compiler", lambda **k: pytest.fail("reporting reran Lean"))
    prefix = tmp_path / "generated"
    assert graph_reports.main(["--input-dir", str(root), "--output-prefix", str(prefix)]) == 0
    output = capsys.readouterr().out
    assert len(output) < 1024 and "weights" not in output and "selected_observations" not in output
    status = json.loads(output)
    assert status["evaluation_ok"] == result["ok"] and not status["checkpoint_promoted"]
    before = {key: Path(status[key]).read_bytes() for key in ("measurement", "summary")}
    assert len(before["measurement"]) > 10_000  # Payload is on disk, not stdout.
    with pytest.raises(FileExistsError):
        graph_reports.generate_reports(root, prefix)
    graph_reports.generate_reports(root, prefix, overwrite=True)
    assert all(Path(status[k]).read_bytes() == contents for k, contents in before.items())


@pytest.mark.parametrize("damage", ["hash", "schema", "existing_summary", "symlink", "directory"])
def test_report_generator_refuses_bad_inputs_and_unsafe_overwrites(report_input, tmp_path, damage):
    from jevops.graph_reports import generate_reports
    original, result = report_input
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "training.json").write_bytes((original / "training.json").read_bytes())
    altered = copy.deepcopy(result)
    if damage == "hash":
        altered["ok"] = not altered["ok"]
    elif damage == "schema":
        altered["schema"] = "unknown"
    (inputs / "evaluation.json").write_text(json.dumps(altered))
    prefix = tmp_path / "out"
    measurement, summary = tmp_path / "out_control.json", tmp_path / "out_summary.md"
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep")
    if damage == "existing_summary":
        summary.write_text("keep")
    elif damage == "symlink":
        measurement.symlink_to(sentinel)
    elif damage == "directory":
        measurement.mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        generate_reports(inputs, prefix, overwrite=damage in {"symlink", "directory"})
    assert sentinel.read_text() == "keep"
    if damage == "existing_summary":
        assert summary.read_text() == "keep" and not measurement.exists()
    elif damage in {"hash", "schema"}:
        assert not measurement.exists() and not summary.exists()


def test_saved_native_composition_gain_is_not_claimed_as_a_neural_advantage():
    # Saved observations are a regression record, not fresh Lean verification.
    record = json.loads((Path(__file__).with_name("fixtures") / "graph_composition_control.json").read_text())
    assert record["measurement_sha256"] == digest({k: v for k, v in record.items() if k != "measurement_sha256"})
    assert record["ok"] and all(record["gates"].values()) and record["models_unchanged"]
    for name in ("selected", "fixed"):
        one, multi = record["summary"][name + "_one"], record["summary"][name + "_composed"]
        assert one["valid_count"] == multi["valid_count"] == multi["loss_sample_count"] == 6
        assert one["verified_saved_tokens"] == 90 and multi["verified_saved_tokens"] == 114
        assert multi["teacher_steps"] == multi["labeled_teacher_steps"] == 18
        assert one["cross_entropy"] == multi["cross_entropy"]
        assert one["expected_cosine_loss"] == multi["expected_cosine_loss"]
    assert record["summary"]["frozen_composed"]["verified_saved_tokens"] == 114
    for split, stats in record["by_split"].items():
        assert record["split_gates"][split] == composition.acceptance_gates(stats["selected_composed"], stats["fixed_composed"])
        assert all(record["split_gates"][split].values())
    selected = record["training_statistics"][record["selected"]]
    assert selected["after"]["correct_count"] == 8 and selected["encoder_changed"]
    assert selected["after"]["cross_entropy"] < selected["before"]["cross_entropy"]
    assert selected["after"]["expected_cosine_loss"] < selected["before"]["expected_cosine_loss"]
    assert not record["checkpoint_promoted"] and record["official_score"] is None
