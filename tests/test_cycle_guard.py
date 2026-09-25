"""Exact ancestor detection is a search hint; native replay remains mandatory."""
import os
from pathlib import Path
import subprocess

import pytest

from jevops import arena_local as local, arena_lean as native, arena_providers as providers
from jevops.arena import VerificationRequest, content_hash
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from jevops.proof_replay import replace_event
from tests.test_arena_local import guard, PIN, RECORD, SOURCE
from tests.test_local_backward_search import search_stage, PREFIX
from tests.test_local_premise_replay import capture_fixture, inventory, RECORD as PLAN_RECORD
from tests.test_local_premise_pilot import pilot, NOMINEES
from tests.test_subgoal_ordering import test_native_sibling_ordering as sibling_control


def cycle_stage(binding, payload):
    value = search_stage(binding, payload)
    if payload["mode"] == "search":
        value["report"].update(schema="jevops-local-search/v5", cycle_guard=payload["cycle_guard"],
            max_cycle_checks=payload["max_cycle_checks"], cycle_checks_exhausted=False,
            cycle_checks=[dict(id=0, at_step=0, depth=0, kind="eligible", nodes=1,
                               declarations=0, repeat_of=None, decision="continue")])
    return value


def runtime(guard, runner=cycle_stage, max_processes=3):
    return local.ArenaLocalRuntime(guard, RECORD, runner=runner, max_processes=max_processes)


def test_fixture_exact_budget_and_bound_mode(guard):
    rt = runtime(guard)
    c = rt.capture(PIN)["capture"]
    results = [rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], cycle_guard=m,
        max_cycle_checks=1, max_steps=1) for m in ("observe-v1", "prune-v1")]
    for r in results:
        assert r["ok"] and r["closing_reproduced"] and r["evidence_mode"] == "fixture"
        assert r["cycle_checks_reserved"] == r["cycle_checks_observed"] == r["cycle_nodes_observed"] == 1
        assert r["cycle_prunes"] == 0 and not r["proof_admitted"]
    assert results[0]["environment"] != results[1]["environment"]


@pytest.mark.parametrize("damage", ["schema", "mode", "limit", "bool", "count", "exhaustion", "id", "step",
    "depth", "kind", "nodes", "declarations", "self", "negative", "bool_ancestor", "prune", "extra", "receipt"])
def test_malformed_cycle_observation_rejected(guard, damage):
    def corrupt(binding, payload):
        value = cycle_stage(binding, payload)
        if payload["mode"] == "search":
            r = value["report"]; c = r["cycle_checks"][0]
            if damage == "schema": r["schema"] = "jevops-local-search/v1"
            elif damage == "mode": r["cycle_guard"] = "observe-v1"
            elif damage == "limit": r["max_cycle_checks"] = 1
            elif damage == "bool": c["nodes"] = True
            elif damage == "count": r["cycle_checks"] *= 257
            elif damage == "exhaustion": r["cycle_checks_exhausted"] = True
            elif damage == "id": c["id"] = 1
            elif damage == "step": c["at_step"] = 2
            elif damage == "depth": c["depth"] = 4
            elif damage == "kind": c["kind"] = "proved"
            elif damage == "nodes": c["nodes"] = 2049
            elif damage == "declarations": c["declarations"] = 65
            elif damage == "self": c["repeat_of"] = 0
            elif damage == "negative": c["repeat_of"] = -1
            elif damage == "bool_ancestor": c["repeat_of"] = True
            elif damage == "prune": c["decision"] = "prune"
            elif damage == "extra": c["verified"] = True
            else: r["application"]["roundtrip"]["environment"] = "c" * 64
        return value
    rt = runtime(guard, corrupt)
    c = rt.capture(PIN)["capture"]
    r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], cycle_guard="prune-v1")
    assert r["status"] == "ERROR" and not r["closing_reproduced"] and r["extracted_candidate"] is None
    assert r["cycle_checks_reserved"] == 256


@pytest.mark.parametrize("damage", ["same_depth", "same_step", "ineligible", "mode", "node_limit"])
def test_repeat_receipt_requires_earlier_eligible_ancestor(damage):
    checks = [dict(id=0, at_step=0, depth=0, kind="eligible", nodes=1,
                   declarations=0, repeat_of=None, decision="continue"),
              dict(id=1, at_step=1, depth=1, kind="eligible", nodes=1,
                   declarations=0, repeat_of=0, decision="prune")]
    r = dict(cycle_guard="prune-v1", max_cycle_checks=2, cycle_checks=checks, cycle_checks_exhausted=False)
    assert local._cycle_checks(r, "prune-v1", 2, 1, 4) == checks
    if damage == "same_depth": checks[1]["depth"] = 0
    elif damage == "same_step": checks[1]["at_step"] = 0
    elif damage == "ineligible": checks[0]["kind"] = "metavariables"
    elif damage == "mode": checks[1]["decision"] = "continue"
    else: checks[0]["kind"] = "node_limit"
    with pytest.raises(ValueError): local._cycle_checks(r, "prune-v1", 2, 1, 4)


@pytest.mark.parametrize("kwargs", [{"cycle_guard": []}, {"cycle_guard": "heads"},
    {"max_cycle_checks": True}, {"max_cycle_checks": -1}, {"max_cycle_checks": 257}])
def test_invalid_configuration_no_launch(guard, kwargs):
    rt = runtime(guard)
    c = rt.capture(PIN)["capture"]
    with pytest.raises(ValueError):
        rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **{ "cycle_guard": "prune-v1", **kwargs})
    assert rt.attempts == 1


def test_zero_timeout_and_batch_accounting(guard):
    def timeout(binding, payload):
        if payload["mode"] == "search": raise TimeoutError("fixture")
        return cycle_stage(binding, payload)
    for runner in (cycle_stage, timeout):
        rt = runtime(guard, runner)
        c = rt.capture(PIN)["capture"]
        zero = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], cycle_guard="prune-v1", max_cycle_checks=0)
        assert zero["status"] == "BUDGET_EXHAUSTED" and rt.attempts == 1
        env = rt.context.context_id
        index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
        scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
        b = rt.discover_batch(PIN, c, index, scope, search="backward-v1", cycle_guard="prune-v1", max_applications=1)
        assert b["cycle_checks_reserved"] == 256
        if runner == cycle_stage:
            assert b["cycle_checks_observed"] == 1 and len(b["drafts"]) == 1
        else:
            assert b["status"] == "ERROR" and b["unknown_search_processes"] == 1 and not b["drafts"]
            r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], cycle_guard="prune-v1")
            assert r["cycle_checks_observed"] is None and r["cycle_checks_reserved"] == 256


def test_planner_default_compatibility_zero_and_pilot(monkeypatch):
    args = (PLAN_RECORD, capture_fixture(), *inventory())
    old = providers.plan_local_applications(*args, search="backward-v1")
    assert old == providers.plan_local_applications(*args, search="backward-v1", cycle_guard="none")
    new = providers.plan_local_applications(*args, search="backward-v1", cycle_guard="prune-v1", max_applications=1)
    assert new["applications"][0]["cycle_guard"] == "prune-v1"
    assert new["request"]["cycle_check_reservation_ceiling"] == 256
    assert old["request"]["request_sha256"] != new["request"]["request_sha256"]
    with pytest.raises(ValueError): providers.plan_local_applications(*args, cycle_guard="prune-v1")
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **k: pytest.fail("zero queried"))
    assert providers.plan_local_applications(*args, search="backward-v1", cycle_guard="prune-v1",
        max_cycle_checks=0)["status"] == "BUDGET_EXHAUSTED"
    p = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=55, comparison="cycle-guard")
    assert p["process_ceiling"] == 55 and p["families"] == ["baseline", "observe", "guarded"]
    opts = p["protocol"]["family_options"]
    assert opts["observe"] == {**opts["baseline"], "cycle_guard": "observe-v1", "max_cycle_checks": 256}
    assert opts["guarded"] == {**opts["observe"], "cycle_guard": "prune-v1"}
    assert p["official_score"] is None and not p["promoted"]


def installed_lean():
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1": pytest.skip("installed native opt-in only")
    tag = os.environ.get("JEVOPS_SEARCH_LEAN_TAG", "v4.26.0")
    return tag, native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)


@pytest.mark.no_seal(reason="native guard/discharge composition, installed Lean only")
@pytest.mark.parametrize("case", ["constraining", "rollback", "conjunction"])
def test_native_cycle_with_proposition_discharge(tmp_path, case):
    sibling_control(tmp_path, case, discharge_filter="propositions-v1", cycle_guard="prune-v1")


@pytest.mark.no_seal(reason="native guard control, no downloads/models")
@pytest.mark.parametrize("case", ["chain", "siblings", "rollback", "cycle", "mutual", "context", "budgets", "axiom"])
def test_native_cycle_search(tmp_path, case, cycle_key="raw-v1", generic=False):
    tag, lean = installed_lean()
    pin = VersionPin(tag, "cycle-control")
    prefix, statement = PREFIX + "theorem repeatR (h : R) : R := h\n", "theorem sample (h : P) : R"
    answer, names = "R.mk (Q.mk (id (id h)))", ["repeatR", "toR", "toQ"]
    if case == "siblings":
        statement, answer = "theorem sample (h : P) : R ∧ R", "And.intro (R.mk (Q.mk h)) (R.mk (Q.mk h))"
    elif case == "rollback": names = ["repeatR", "bad", "toR", "toQ"]
    elif case == "cycle":
        prefix += "opaque Missing : Prop := False\ntheorem repeatChoice (h : Missing ∨ True) : Missing ∨ True := h\n"
        statement, answer, names = "theorem sample : Missing ∨ True", "Or.inr True.intro", ["repeatChoice"]
    elif case == "mutual":
        prefix += "theorem back (h : R) : Q := by cases h with | mk h => exact h\n"
        names = ["toR", "back", "toQ"]
    elif case == "context":
        prefix += "theorem under (h : True → R) : R := h True.intro\n"
        names = ["under", "toR", "toQ"]
    elif case == "axiom":
        prefix += "axiom forged : R\n"
        names = ["repeatR", "forged"]
    if generic:
        names = ["loop" if name == "repeatR" else name for name in names]
    source = statement + " := by\n  exact " + answer + "\n"
    record = dict(name="Suite.sample", statement=statement, src=source, version_info=[{tag: pin.git_commit}])
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix + "namespace Suite\n", project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    rt = local.ArenaLocalRuntime(verifier, record, max_processes=6)
    captured = rt.capture(pin)
    assert captured["ok"], captured
    c = captured["capture"]
    event = next(e for e in c["trace"]["events"] if source.encode()[int(e["start"]):int(e["end"])].startswith(b"exact "))
    args = (pin, source, c, int(event["id"]), names)
    opts = dict(max_steps=256, max_depth=4 if case == "context" else 8)
    r = rt.discover_search(*args, **opts, cycle_guard="prune-v1", cycle_key=cycle_key)
    assert r["ok"], r
    report = r["search_report"]
    positive = case not in {"cycle", "axiom"}
    assert r["closing_reproduced"] == positive, r
    if case != "context": assert r["cycle_prunes"] > 0, report["cycle_checks"]
    if positive:
        draft = replace_event(source, event, r["extracted_candidate"])
        assert verifier(VerificationRequest(rt.context, draft, pin)).outcome.value == "VERIFIED"
    if case == "siblings": assert report["path"].count("apply _root_.toR") == 2
    if case == "rollback": assert "apply _root_.bad" not in report["path"]
    if case == "context":
        # Repeated R beneath introduced True hypotheses is not the same context.
        assert any(c["kind"] == "eligible" and c["depth"] > 1 and c["repeat_of"] is None
                   for c in report["cycle_checks"])
    if case == "budgets":
        checks = r["cycle_checks_observed"]
        exact = rt.discover_search(*args, **opts, cycle_guard="prune-v1", max_cycle_checks=checks, cycle_key=cycle_key)
        below = rt.discover_search(*args, **opts, cycle_guard="prune-v1", max_cycle_checks=checks - 1, cycle_key=cycle_key)
        assert exact["closing_reproduced"] and not below["closing_reproduced"]
        assert below["search_report"]["cycle_checks_exhausted"]
    if case == "chain":
        baseline = rt.discover_search(*args, **opts)
        observe = rt.discover_search(*args, **opts, cycle_guard="observe-v1", cycle_key=cycle_key)
        assert baseline["ok"] and observe["ok"]
        for key in ("trace", "path", "attempted_steps", "depth_cutoffs"):
            assert baseline["search_report"][key] == observe["search_report"][key]
        assert r["search_steps_observed"] < observe["search_steps_observed"]
    assert not r["proof_admitted"] and not r["whole_source_checked"]


@pytest.mark.no_seal(reason="native structural-key adversarial controls, installed Lean only")
def test_native_cycle_key_boundaries(tmp_path):
    _, lean = installed_lean()
    driver = (Path(local.__file__).parent / "lean/ArenaLocal.lean").read_text()
    definitions = driver[driver.index("structure LocalCycleKey"):driver.index("structure LocalRetrieval")]
    source = "import Lean\nopen Lean Elab\n" + definitions + r'''
elab "cycle_keys" : tactic => do
  let goal ← Tactic.getMainGoal
  let (some key, "eligible", _, _) ← inspectCycleGoal goal | throwError "expected eligible"
  let (some again, _, _, _) ← inspectCycleGoal goal | throwError "expected repeat"
  unless sameCycleKey key again do throwError "unstable observation"
  goal.withContext do
    Meta.withLocalDeclD `extra (mkConst ``True) fun _ => do
      let g ← Meta.mkFreshExprMVar key.type
      let (some changed, _, _, _) ← inspectCycleGoal g.mvarId! | throwError "new context"
      if sameCycleKey key changed then throwError "ignored new local"
    let n ← Meta.mkFreshExprMVar (mkConst ``Nat)
    let ty ← Meta.mkEq n n
    let g ← Meta.mkFreshExprMVar ty
    let (k, kind, _, _) ← inspectCycleGoal g.mvarId!
    unless k.isNone && kind == "metavariables" do throwError "unresolved term meta"
    n.mvarId!.assign (mkNatLit 0)
    let (k, kind, _, _) ← inspectCycleGoal g.mvarId!
    unless k.isNone && kind == "metavariables" do throwError "raw assigned meta must abstain"
    let u ← Meta.mkFreshLevelMVar
    let g ← Meta.mkFreshExprMVar (mkSort u)
    let (k, kind, _, _) ← inspectCycleGoal g.mvarId!
    unless k.isNone && kind == "metavariables" do throwError "unresolved universe"
    let g ← Meta.mkFreshExprMVar (mkConst ``Nat)
    let (k, kind, _, _) ← inspectCycleGoal g.mvarId!
    unless k.isNone && kind == "not_prop" do throwError "data is not a cycle key"
    let d := LocalDecl.ldecl 0 ⟨`x⟩ `x (mkConst ``Nat) (mkNatLit 0) false .default
    let e := LocalDecl.ldecl 0 ⟨`x⟩ `x (mkConst ``Nat) (mkNatLit 1) false .default
    if sameCycleDecl d e then throwError "ignored let value"
    if sameCycleKey key { key with instances := #[{ className := `Cls, fvar := mkFVar ⟨`x⟩ }] } then
      throwError "ignored local instances"
    if sameCycleKey key { key with auxiliaryNames := #[some `Aux] } then
      throwError "ignored auxiliary names"
    let mut bigContext ← getLCtx
    for i in [:65] do
      let name := Name.num `extra i
      bigContext := bigContext.mkLocalDecl ⟨name⟩ name (mkConst ``True)
    Meta.withLCtx bigContext (← Meta.getLocalInstances) do
      let g ← Meta.mkFreshExprMVar (mkConst ``True)
      let (k, kind, nodes, _) ← inspectCycleGoal g.mvarId!
      unless k.isNone && kind == "context_limit" && nodes == 0 do throwError "context overflow"
    let mut large := mkConst ``True
    for _ in [:1100] do large := mkApp (mkApp (mkConst ``And) (mkConst ``True)) large
    let g ← Meta.mkFreshExprMVar large
    let (k, kind, nodes, _) ← inspectCycleGoal g.mvarId!
    unless k.isNone && kind == "node_limit" && nodes == 2048 do throwError "expression overflow"
  Tactic.evalTactic (← `(tactic| assumption))
example (P : Prop) (h : P) : P := by cycle_keys
'''
    file = tmp_path / "CycleKeys.lean"
    file.write_text(source)
    r = subprocess.run([str(lean), str(file)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
