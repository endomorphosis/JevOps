"""Bounded assignment dereference is observational, not proof or constraint solving."""

from pathlib import Path
import subprocess

import pytest

from jevops import arena_local as local, arena_providers as providers
from jevops.arena import content_hash
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from tests.test_arena_local import guard, PIN, RECORD, SOURCE
from tests.test_cycle_guard import (
    cycle_stage,
    installed_lean,
    test_native_cycle_search as search_control,
)
from tests.test_subgoal_ordering import test_native_sibling_ordering as sibling_control
from tests.test_local_premise_replay import capture_fixture, inventory, RECORD as PLAN_RECORD
from tests.test_local_premise_pilot import pilot, NOMINEES


def assigned_stage(binding, payload):
    value = cycle_stage(binding, payload)
    if payload["mode"] == "search":
        r = value["report"]
        r.update(schema="jevops-local-search/v6", cycle_key=payload["cycle_key"])
        r["cycle_checks"][0].update(
            expr_nodes=1, level_nodes=0, term_dereferences=0, level_dereferences=0, blocked_in=None
        )
    return value


def runtime(guard, runner=assigned_stage, max_processes=3):
    return local.ArenaLocalRuntime(guard, RECORD, runner=runner, max_processes=max_processes)


SETTINGS = dict(cycle_guard="prune-v1", cycle_key="assigned-v1")


def test_fixture_identity_and_separate_counts(guard):
    rt = runtime(guard)
    c = rt.capture(PIN)["capture"]
    r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **SETTINGS, max_cycle_checks=1)
    assert (
        r["ok"]
        and r["closing_reproduced"]
        and r["cycle_checks_reserved"] == r["cycle_checks_observed"] == 1
    )
    assert r["cycle_nodes_observed"] == r["cycle_expr_nodes_observed"] == 1
    assert (
        r["cycle_level_nodes_observed"]
        == r["cycle_term_dereferences_observed"]
        == r["cycle_level_dereferences_observed"]
        == 0
    )
    assert r["evidence_mode"] == "fixture" and not r["proof_admitted"]
    assert r["binding"]["cycle_key"] == "assigned-v1"


@pytest.mark.parametrize(
    "damage",
    [
        "schema",
        "key",
        "nodes",
        "negative",
        "bool",
        "level_count",
        "term_count",
        "blocked",
        "location",
        "unknown_kind",
        "term_visit",
        "level_visit",
        "unresolved_location",
        "delayed_location",
        "depth_location",
        "error_repeat",
        "extra",
        "forged",
    ],
)
def test_malformed_resolution_receipt_fails_closed(guard, damage):
    def corrupt(binding, payload):
        v = assigned_stage(binding, payload)
        if payload["mode"] == "search":
            r = v["report"]
            c = r["cycle_checks"][0]
            if damage == "schema":
                r["schema"] = "jevops-local-search/v5"
            elif damage == "key":
                r["cycle_key"] = "raw-v1"
            elif damage == "nodes":
                c["nodes"] = 2
            elif damage == "negative":
                c["term_dereferences"] = -1
            elif damage == "bool":
                c["expr_nodes"] = True
            elif damage == "level_count":
                c["level_dereferences"] = 1
            elif damage == "term_count":
                c["term_dereferences"] = 2
            elif damage == "blocked":
                c["blocked_in"] = "goal"
            elif damage == "location":
                c.update(kind="error", blocked_in="hidden_runtime")
            elif damage == "unknown_kind":
                c["kind"] = "metavariables"
            elif damage == "term_visit":
                c.update(kind="unresolved_term", blocked_in="goal", term_dereferences=1)
            elif damage == "level_visit":
                c.update(kind="unresolved_level", blocked_in="goal")
            elif damage == "unresolved_location":
                c["kind"] = "unresolved_term"
            elif damage == "delayed_location":
                c["kind"] = "delayed_assignment"
            elif damage == "depth_location":
                c["kind"] = "depth_limit"
            elif damage == "error_repeat":
                c.update(kind="error", repeat_of=0)
            elif damage == "extra":
                c["solved_constraints"] = True
            else:
                r["application"]["roundtrip"]["environment"] = "c" * 64
        return v

    rt = runtime(guard, corrupt)
    c = rt.capture(PIN)["capture"]
    r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **SETTINGS)
    assert (
        r["status"] == "ERROR" and not r["closing_reproduced"] and r["extracted_candidate"] is None
    )
    assert r["cycle_checks_reserved"] == 256


@pytest.mark.parametrize(
    "changes", [{"cycle_key": []}, {"cycle_key": "normalize"}, {"cycle_guard": "none"}]
)
def test_invalid_mode_before_launch(guard, changes):
    rt = runtime(guard)
    c = rt.capture(PIN)["capture"]
    with pytest.raises(ValueError):
        rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **{**SETTINGS, **changes})
    assert rt.attempts == 1


def test_zero_timeout_and_batch(guard):
    def timeout(binding, payload):
        if payload["mode"] == "search":
            raise TimeoutError("fixture")
        return assigned_stage(binding, payload)

    for runner in (assigned_stage, timeout):
        rt = runtime(guard, runner)
        c = rt.capture(PIN)["capture"]
        r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **SETTINGS, max_cycle_checks=0)
        assert r["status"] == "BUDGET_EXHAUSTED" and rt.attempts == 1
        assert r["cycle_term_dereferences_observed"] is None
        env = rt.context.context_id
        index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
        scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
        b = rt.discover_batch(
            PIN, c, index, scope, search="backward-v1", max_applications=1, **SETTINGS
        )
        assert b["cycle_checks_reserved"] == 256
        if runner == assigned_stage:
            assert b["cycle_expr_nodes_observed"] == 1 and len(b["drafts"]) == 1
        else:
            assert b["status"] == "ERROR" and b["unknown_search_processes"] == 1 and not b["drafts"]
            r = rt.discover_search(PIN, SOURCE, c, 0, ["True.intro"], **SETTINGS)
            assert r["cycle_expr_nodes_observed"] is None and r["cycle_checks_reserved"] == 256


def test_legacy_plan_identity_and_fixed_three_arm_protocol():
    args = (PLAN_RECORD, capture_fixture(), *inventory())
    raw = providers.plan_local_applications(*args, search="backward-v1", cycle_guard="prune-v1")
    assert raw == providers.plan_local_applications(
        *args, search="backward-v1", cycle_guard="prune-v1", cycle_key="raw-v1"
    )
    assigned = providers.plan_local_applications(*args, search="backward-v1", **SETTINGS)
    assert assigned["request"]["request_sha256"] != raw["request"]["request_sha256"]
    assert assigned["applications"][0]["cycle_key"] == "assigned-v1"
    p = pilot.make_plan(RECORD, NOMINEES, cap=1, max_processes=55, comparison="assigned-cycle")
    assert p["process_ceiling"] == 55 and p["families"] == ["raw", "observe", "guarded"]
    opts = p["protocol"]["family_options"]
    assert opts["guarded"] == {**opts["raw"], "cycle_key": "assigned-v1"}
    assert opts["observe"] == {**opts["guarded"], "cycle_guard": "observe-v1"}


@pytest.mark.no_seal(reason="native assigned-key search, installed Lean only")
@pytest.mark.parametrize("case", ["chain", "siblings", "rollback", "budgets", "axiom"])
def test_native_assigned_search(tmp_path, case):
    search_control(tmp_path, case, cycle_key="assigned-v1", generic=True)


@pytest.mark.no_seal(reason="native assignment/sibling rollback, installed Lean only")
@pytest.mark.parametrize("case", ["constraining", "rollback", "conjunction"])
def test_native_assigned_sibling(tmp_path, case):
    sibling_control(
        tmp_path,
        case,
        discharge_filter="propositions-v1",
        cycle_guard="prune-v1",
        cycle_key="assigned-v1",
    )


@pytest.mark.no_seal(reason="native bounded assignment internals, installed Lean only")
def test_native_assignment_boundaries(tmp_path):
    _, lean = installed_lean()
    driver = (Path(local.__file__).parent / "lean/ArenaLocal.lean").read_text()
    definitions = driver[
        driver.index("structure LocalCycleKey") : driver.index("structure LocalRetrieval")
    ]
    source = (
        "import Lean\nopen Lean Elab\n"
        + definitions
        + r"""
elab "assigned_keys" : tactic => do
  let goal ← Tactic.getMainGoal
  goal.withContext do
    let p ← Meta.mkFreshExprMVar (mkSort .zero)
    let q ← Meta.mkFreshExprMVar (mkSort .zero)
    let g ← Meta.mkFreshExprMVar p
    let direct ← Meta.mkFreshExprMVar (mkConst ``True)
    let (k, s, _) ← inspectAssignedCycleGoal g.mvarId!
    unless k.isNone && s.kind == "unresolved_term" && s.location == some "goal" do
      throwError "unresolved goal must abstain"
    if ← p.mvarId!.isAssigned then throwError "inspection solved constraint"
    p.mvarId!.assign q
    q.mvarId!.assign (mkConst ``True)
    let (some resolved, s, _) ← inspectAssignedCycleGoal g.mvarId! | throwError "transitive assignment"
    let (some expected, _, _) ← inspectAssignedCycleGoal direct.mvarId! | throwError "direct key"
    unless sameCycleKey resolved expected && s.termDereferences == 2 do throwError "wrong resolved key"
    let some raw ← getExprMVarAssignment? p.mvarId! | throwError "lost assignment"
    unless raw.equal q do throwError "inspection compressed assignment path"
    if ← g.mvarId!.isAssigned then throwError "inspection proved goal"
    let (_, kind, _, _) ← inspectCycleGoal g.mvarId!
    unless kind == "metavariables" do throwError "legacy guard changed"
    let u ← Meta.mkFreshLevelMVar
    let .mvar uid := u | throwError "fresh universe"
    let e := mkAppN (mkConst ``Eq [u]) #[mkConst ``Nat, mkNatLit 0, mkNatLit 0]
    let gu ← Meta.mkFreshExprMVar e
    let (k, s, _) ← inspectAssignedCycleGoal gu.mvarId!
    unless k.isNone && s.kind == "unresolved_level" do throwError "unresolved universe accepted"
    let v ← Meta.mkFreshLevelMVar
    let .mvar vid := v | throwError "fresh universe"
    assignLevelMVar uid v
    assignLevelMVar vid (.succ .zero)
    let (some _, s, _) ← inspectAssignedCycleGoal gu.mvarId! | throwError "resolved universe"
    unless s.levelDereferences == 2 do throwError "universe accounting"
    unless (← getLevelMVarAssignment? uid) == some v do throwError "universe path compressed"
    let dataGoal ← Meta.mkFreshExprMVar (mkConst ``Nat)
    let (k, s, _) ← inspectAssignedCycleGoal dataGoal.mvarId!
    unless k.isNone && s.kind == "not_prop" && s.location.isNone do throwError "pruned data goal"
    let r ← Meta.mkFreshExprMVar (mkSort .zero)
    let gr ← Meta.mkFreshExprMVar r
    let saved ← Tactic.saveState
    r.mvarId!.assign (mkConst ``True)
    let (some ka, _, _) ← inspectAssignedCycleGoal gr.mvarId! | throwError "first branch"
    saved.restore (restoreInfo := true)
    if ← r.mvarId!.isAssigned then throwError "branch assignment leaked"
    r.mvarId!.assign (mkConst ``False)
    let (some kb, _, _) ← inspectAssignedCycleGoal gr.mvarId! | throwError "second branch"
    if sameCycleKey ka kb then throwError "changed assignments reused"
    let unresolved ← Meta.mkFreshExprMVar (mkSort .zero)
    Meta.withLocalDeclD `unknown unresolved fun _ => do
      let g ← Meta.mkFreshExprMVar (mkConst ``True)
      let (k, s, _) ← inspectAssignedCycleGoal g.mvarId!
      unless k.isNone && s.kind == "unresolved_term" && s.location == some "local_type" do
        throwError "dropped unresolved local type"
    let n ← Meta.mkFreshExprMVar (mkConst ``Nat)
    Meta.withLetDecl `value (mkConst ``Nat) n fun _ => do
      let g ← Meta.mkFreshExprMVar (mkConst ``True)
      let (k, s, _) ← inspectAssignedCycleGoal g.mvarId!
      unless k.isNone && s.location == some "local_value" do throwError "dropped local value"
    n.mvarId!.assign (mkNatLit 1)
    Meta.withLetDecl `value (mkConst ``Nat) n fun _ => do
      let g ← Meta.mkFreshExprMVar (mkConst ``True)
      let (some k, s, _) ← inspectAssignedCycleGoal g.mvarId! | throwError "let assignment"
      unless s.termDereferences == 1 && k.declarations.all (fun d => !(d.value? true).any Expr.hasMVar) do
        throwError "partial local substitution"
    let delayed ← Meta.mkFreshExprMVar (mkSort .zero)
    let pending ← Meta.mkFreshExprMVar (mkSort .zero)
    assignDelayedMVar delayed.mvarId! #[] pending.mvarId!
    let g ← Meta.mkFreshExprMVar delayed
    let (k, s, _) ← inspectAssignedCycleGoal g.mvarId!
    unless k.isNone && s.kind == "delayed_assignment" do throwError "synthesized delayed assignment"
    -- Malformed cyclic assignment, deliberately never used as a proof.
    let loop ← Meta.mkFreshExprMVar (mkSort .zero)
    loop.mvarId!.assign loop
    let g ← Meta.mkFreshExprMVar loop
    let (k, s, _) ← inspectAssignedCycleGoal g.mvarId!
    unless k.isNone && s.kind == "depth_limit" && s.exprNodes == 128 do throwError "unbounded recursion"
    -- Exact node allowance and one-over traversal without inference/reduction.
    let expr := mkConst ``True
    let stats ← IO.mkRef ({} : CycleResolveStats)
    for _ in [:2048] do
      unless (← (resolveCycleExpr expr 0 stats).run).isSome do throwError "early node exhaustion"
    unless (← (resolveCycleExpr expr 0 stats).run).isNone do throwError "late node exhaustion"
    unless (← stats.get).exprNodes == 2048 && (← stats.get).kind == "node_limit" do
      throwError "node counter"
    let mut tree := mkConst ``True
    for _ in [:10] do tree := mkApp2 (mkConst ``And) tree tree
    let wide ← Meta.mkFreshExprMVar (mkSort .zero)
    wide.mvarId!.assign tree
    let g ← Meta.mkFreshExprMVar wide
    let (k, s, _) ← inspectAssignedCycleGoal g.mvarId!
    unless k.isNone && s.kind == "node_limit" && s.exprNodes + s.levelNodes == 2048 do
      throwError "shared expansion escaped node budget"
    let mut bigContext ← getLCtx
    for i in [:65] do
      let name := Name.num `extra i
      bigContext := bigContext.mkLocalDecl ⟨name⟩ name (mkConst ``True)
    Meta.withLCtx bigContext (← Meta.getLocalInstances) do
      let g ← Meta.mkFreshExprMVar (mkConst ``True)
      let (k, s, count) ← inspectAssignedCycleGoal g.mvarId!
      unless k.isNone && s.kind == "context_limit" && count == 65 && s.exprNodes == 0 do
        throwError "context overflow"
  Tactic.evalTactic (← `(tactic| assumption))
example (P : Prop) (h : P) : P := by assigned_keys
"""
    )
    path = tmp_path / "AssignedKeys.lean"
    path.write_text(source)
    r = subprocess.run(
        [str(lean), str(path)], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stdout + r.stderr
