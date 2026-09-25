"""Native receipt binding and gradients; synthetic receipts are NOT Lean evidence."""
import copy
import json
import shutil

import pytest

torch = pytest.importorskip("torch")

from jevops import candidate_audit as audit
from jevops import rejection_training as training
from jevops.graph_composition import CheckedCompiler
from jevops.graph_policy import GraphEditPolicy
from jevops.rewrite_policy import body_of, mine_template
from jevops.solver_feedback import source_digest
from jevops.structural_policy import digest
from jevops.structural_training import _envelope
from tests.test_structural_training import ENV, fixture_receipt

pytestmark = pytest.mark.no_seal(reason="optional PyTorch and native candidate auditing")


@pytest.fixture(autouse=True)
def one_thread():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def rows():
    return [r for r in training.training_rows() if r["id"] in {"copy", "nat_refl"}]


def rejection(source):
    declaration = _envelope(source, source)
    i = next(i for i, line in enumerate(source.splitlines(), 1) if line.strip() == "rfl")
    return {"theorem_ok": False, "source_sha256": source_digest(source),
        "compiled_source_sha256": source_digest(source+f"\n#print axioms {declaration}\n"),
        "diagnostics_source_sha256": source_digest(source), "diagnostics": [
            {"severity": "error", "pos": {"line": i, "column": 2}, "endPos": {"line": i, "column": 5},
             "data": "Tactic `rfl` failed: test-only simulated nonreflexive goal"}]}


def compiler(source):
    if "scoped_train_copy" in source and body_of(source)[1] == "rfl":
        return rejection(source)
    return fixture_receipt(source)


def setup(compile_fn=compiler):
    rs = rows()
    bank = {r["id"]: mine_template(r["source"], body_of(r["target"])[1]) for r in rs}
    templates = sorted(bank.values(), key=lambda r: r["id"])
    checker = CheckedCompiler(compile_fn, environment_sha256=ENV, toolchain=("fixture", "fixture"))
    found = audit.audit_candidates(rs, templates, checker)
    model = GraphEditPolicy(templates, environment_sha256=ENV, toolchain=checker.toolchain, pooling="multiscale")
    context = checker.context(model, rs[0]["source"])
    return rs, checker, model, context, found


def test_complete_audit_has_competing_valid_and_shorter_rejected_candidates():
    rs, _, _, _, result = setup()
    assert result["ok"] and not result["evaluation_accessed"] and not result["model_trained"]
    row = result["rows"][0]
    assert row["headroom"]["choice_count"] == 3 and row["headroom"]["competing_edits"] == 2
    assert {e["status"] for e in row["entries"]} == {"identity", "accepted", "elaborator_rejected"}
    bad = next(e for e in row["entries"] if e["status"] == "elaborator_rejected")
    assert bad["tokens"] < row["entries"][row["label"]]["tokens"]
    assert not row["proof_admitted"]


@pytest.mark.parametrize("damage", ["timeout", "missing", "foreign", "position", "extra_error", "resource", "different_error"])
def test_failure_classification_is_narrow_and_source_bound(damage):
    source = body_of(rows()[0]["source"])[0] + "\n  rfl\n"
    receipt = rejection(source)
    assert audit.known_rfl_rejection(source, receipt)
    if damage == "timeout":
        receipt["reason"] = "TimeoutExpired"
    elif damage == "missing":
        receipt.pop("diagnostics")
    elif damage == "foreign":
        receipt["diagnostics_source_sha256"] = "0"*64
    elif damage == "position":
        receipt["diagnostics"][0]["pos"]["column"] = 0
    elif damage == "extra_error":
        receipt["diagnostics"].append(copy.deepcopy(receipt["diagnostics"][0]))
    elif damage == "resource":
        receipt["diagnostics"][0]["data"] += " (maximum heartbeats exceeded)"
    else:
        receipt["diagnostics"][0]["data"] = "unknown module MyDependency"
    assert not audit.known_rfl_rejection(source, receipt)


def test_unknown_failure_is_not_negative_and_stops_training(monkeypatch):
    def unknown(source):
        if "scoped_train_copy" in source and body_of(source)[1] == "rfl":
            return {"theorem_ok": False, "reason": "TimeoutExpired"}
        return fixture_receipt(source)
    rs, _, _, _, result = setup(unknown)
    assert not result["ok"]
    assert any(e["status"] == "unknown" for a in result["rows"] for e in a["entries"])
    monkeypatch.setattr(training, "GraphEditPolicy", lambda *a, **kw: pytest.fail("model created before complete audit"))
    fitted = training.run_training(rs, unknown, environment_sha256=ENV, epochs=1)
    assert not fitted["model_trained"] and not fitted["ok"]
    assert fitted["reason"] == "incomplete_candidate_audit_or_nonminimal_teacher"


def test_native_penalty_keeps_ce_cosine_and_has_correct_gradient():
    rs, _, model, ctx, found = setup()
    r, a = rs[0], found["rows"][0]
    base = audit.audited_loss(model, r["source"], r["target"], ctx, a, split="train", rejection_weight=0)
    penalized = audit.audited_loss(model, r["source"], r["target"], ctx, a, split="train", rejection_weight=.25)
    assert float(penalized["rejected_probability_mass"].detach()) == pytest.approx(1/3)
    for k in ("cross_entropy", "expected_cosine_loss", "supervised_total"):
        assert torch.equal(base[k], penalized[k])
    assert float((penalized["total"] - base["total"]).detach()) == pytest.approx(.25/3)
    # Check the actual trainable readout gradient against central differences.
    parameter = model.head.weight
    gradient = torch.autograd.grad(penalized["total"], parameter)[0]
    at = int(gradient.abs().argmax())
    value = float(parameter.detach().flatten()[at])
    def loss():
        return float(audit.audited_loss(model, r["source"], r["target"], ctx, a, split="train")["total"].detach())
    with torch.no_grad():
        parameter.flatten()[at] = value+1e-5
    plus = loss()
    with torch.no_grad():
        parameter.flatten()[at] = value-1e-5
    minus = loss()
    with torch.no_grad():
        parameter.flatten()[at] = value
    assert float(gradient.flatten()[at]) == pytest.approx((plus-minus)/2e-5, abs=1e-8)


@pytest.mark.parametrize("damage", ["hash", "source", "target", "environment", "graph", "order", "missing", "unknown", "bool_index", "bool_label"])
def test_stale_or_partial_audits_fail_before_parameter_changes(damage):
    rs, _, model, ctx, found = setup()
    a = copy.deepcopy(found["rows"][0])
    if damage in {"source", "target", "environment"}:
        a[damage+"_sha256"] = "0"*64
    elif damage == "graph":
        a["dag_sha256"] = "0"*64
    elif damage == "hash":
        a["audit_sha256"] = "0"*64
    elif damage == "order":
        a["entries"].reverse()
    elif damage == "missing":
        a["entries"].pop()
    elif damage == "unknown":
        a["entries"][0]["status"] = "unknown"
    elif damage == "bool_label":
        a["label"] = True
    else:
        a["entries"][0]["index"] = False
    if damage != "hash":
        a["audit_sha256"] = digest({k: v for k, v in a.items() if k != "audit_sha256"})
    before = model.to_dict()
    with pytest.raises(ValueError):
        audit.audited_loss(model, rs[0]["source"], rs[0]["target"], ctx, a, split="train")
    assert model.to_dict() == before


def test_eval_rows_never_reach_compiler_or_target_access():
    class Guard(dict):
        def __getitem__(self, key):
            if key in {"source", "target"}:
                pytest.fail("evaluation contents accessed")
            return super().__getitem__(key)
    data = [rows()[0], Guard(id="eval", split="holdout")]
    with pytest.raises(ValueError, match="training rows only"):
        audit.audit_candidates(data, [], None)
    with pytest.raises(ValueError, match="training rows only"):
        training.run_training(data, lambda _: pytest.fail("compiled evaluation"), environment_sha256=ENV)


@pytest.mark.parametrize("rate", [True, 0, -.1, .26, float("nan"), float("inf")])
def test_bad_learning_rate_rejected_before_compilation(rate):
    with pytest.raises(ValueError, match="learning rate"):
        training.run_training(rows(), lambda _: pytest.fail("invalid rate compiled"), environment_sha256=ENV, learning_rate=rate)


def test_partial_choice_budget_and_nonminimal_teacher_cannot_train():
    rs, checker, model, _, _ = setup()
    with pytest.raises(ValueError, match="candidate budget"):
        audit.audit_candidates(rs, model.templates, checker, max_choices=2)
    # Deliberately select a longer admitted proof even though rfl is admitted.
    rs[1]["target"] = body_of(rs[1]["source"])[0] + "\n  exact h\n"
    result = audit.audit_candidates(rs, model.templates, checker)
    assert not result["ok"] and not result["rows"][1]["complete"]


def test_cost_growth_receives_a_distinct_label_from_elaborator_failure():
    def growing(source):
        receipt = compiler(source)
        if receipt["theorem_ok"] and body_of(source)[1] == "rfl":
            wire = receipt["expression_dag"]["dag"]
            for n in range(3):
                root = wire["roots"][0]
                wire["expressions"].append(["let", [["s", f"larger{n}"]], False, "0", "0", root])
                wire["roots"][0] = str(len(wire["expressions"])-1)
            receipt["expression_dag"]["dag_sha256"] = digest(wire)
        return receipt
    _, _, _, _, result = setup(growing)
    assert not result["ok"]
    assert any(e["status"] == "cost_rejected" for a in result["rows"] for e in a["entries"])


def test_tiny_training_run_preserves_equal_budgets_and_frozen_binding():
    result = training.run_training(rows(), compiler, environment_sha256=ENV, epochs=2)
    assert result["model_trained"] and not result["evaluation_accessed"]
    fit = result["fit"]
    assert fit["matched_initial_graph_weights"]
    assert all(s["updates"] == s["examples_seen"] == 4 for s in fit["statistics"].values())
    assert fit["freeze_sha256"] == digest({k: v for k, v in fit.items() if k != "freeze_sha256"})
    assert result["token_length"]["acceptable_count"] == 1
    assert not result["checkpoint_promoted"] and result["official_score"] is None


def test_reporting_is_generated_offline_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    result = training.run_training(rows(), compiler, environment_sha256=ENV, epochs=1)
    output = tmp_path/"run"
    training.write_reports(result, output)
    assert capsys.readouterr().out == ""
    with pytest.raises(FileExistsError):
        training.write_reports(result, output)
    monkeypatch.setattr(training, "run_training", lambda *a, **kw: pytest.fail("report mode trained"))
    report = tmp_path/"report"
    assert training.main(["--report-from", str(output/"experiment.json"), "--output-dir", str(report)]) == 0
    assert len(capsys.readouterr().out) < 400
    assert not (report/"experiment.json").exists()
    assert json.loads((report/"measurement.json").read_text())["experiment_sha256"] == digest(result)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_native_rfl_failure_is_recognized_but_not_positive_proof_evidence(tmp_path):
    from jevops.router_tuning import _lean_compiler
    source = "theorem actual_reject (n m : Nat) (h : n = m) : n = m := by\n  rfl\n"
    compile_one = _lean_compiler(project_root=tmp_path, kernel_only=True, collect_diagnostics=True,
                                 export_dags=True, environment_sha256=ENV)
    receipt = compile_one(source)
    assert audit.known_rfl_rejection(source, receipt)
    assert not receipt["theorem_ok"] and not receipt["expression_dag"]["ok"]
    assert not audit.known_rfl_rejection(source+"\n", receipt)
