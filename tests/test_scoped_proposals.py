from __future__ import annotations

from copy import deepcopy
from functools import partial
import shutil

import pytest

from jevops import proof_replay as replay
from jevops import proof_state as ps
from jevops import scoped_proposals as scoped
from jevops.router_tuning import _lean_compiler

ENV = "a" * 64


def name(s):
    return [["s", s]]


def unary_state():
    # Structural fixtures test the search algorithm, not theorem validity.
    local = lambda s, i, t: {"id": name(s), "name": name(s), "index": str(i),
        "type": str(t), "value": None, "nondep": False, "binder": "explicit", "kind": "default"}
    return {"schema": ps.STATE_SCHEMA, "goals": [name("goal")],
        "expressions": [["sort", "0"], ["fvar", name("p")], ["fvar", name("q")],
                        ["forall", name("arg"), "explicit", "1", "2"]],
        "levels": [["zero"]], "universe_metavariables": [], "depth": "0", "level_assign_depth": "0",
        "metavariables": [{"id": name("goal"), "name": [], "type": "2",
            "locals": [local("p", 0, 0), local("q", 1, 0), local("f", 2, 3), local("h", 3, 1)],
            "instances": [], "assignment": None, "kind": "natural", "depth": "0", "index": "0", "scope_args": "0"}]}


def candidates(state, **kwargs):
    return [c["candidate"] for c in scoped.local_terms(state, **kwargs)["candidates"]]


def test_uses_actual_local_types_and_ids_without_mutating_observation():
    s = unary_state()
    before = deepcopy(s)
    result = scoped.local_terms(s)
    assert [c["candidate"] for c in result["candidates"]] == ["exact f h"]
    assert result["candidates"][0]["local_ids"] == sorted(ps._id(name(n)) for n in ("f", "h"))
    assert not result["kernel_typechecked"] and not result["proof_admitted"]
    assert s == before
    assert candidates(s, max_applications=0) == []


@pytest.mark.parametrize("damage", ["wrong_type", "shadowed", "hidden", "hierarchical", "anonymous", "syntax"])
def test_unusable_local_is_never_referenced(damage):
    s = unary_state()
    ls = s["metavariables"][0]["locals"]
    if damage == "wrong_type":
        ls[-1]["type"] = "0"
    elif damage == "shadowed":
        ls[0]["name"] = ls[-1]["name"]
    elif damage == "hidden":
        ls[-1]["kind"] = "implDetail"
    elif damage == "hierarchical":
        ls[-1]["name"] = [["s", "a"], ["s", "h"]]
    elif damage == "anonymous":
        ls[-1]["name"] = name("_")
    else:
        ls[-1]["name"] = name("h; sorry")
    assert candidates(s) == []


def test_unicode_name_is_preserved_and_distinct_fvars_do_not_match():
    s = unary_state()
    s["metavariables"][0]["locals"][-1]["name"] = name("π")
    assert candidates(s) == ["exact f π"]
    s["metavariables"][0]["locals"][-1]["type"] = "2"
    assert candidates(s) == ["exact π"]


def test_nested_application_search_and_budgets():
    s = unary_state()
    # Add endomorphism q -> q; results include g (f h) and g (g (f h)).
    s["expressions"].append(["forall", [], "explicit", "2", "2"])
    ls = s["metavariables"][0]["locals"]
    ls.append({**ls[-1], "id": name("g"), "name": name("g"), "index": "4", "type": "4"})
    assert candidates(s) == ["exact f h", "exact g (f h)", "exact g (g (f h))"]
    assert candidates(s, max_applications=1) == ["exact f h"]
    r = scoped.local_terms(s, max_checks=1)
    assert r["truncated"] and r["checks"] == 1
    r = scoped.local_terms(s, max_terms=4)
    assert r["truncated"] and r["term_count"] == 4


def test_metavariables_and_multiple_goals_abstain():
    s = unary_state()
    s["levels"] = [["mvar", name("u")]]
    s["universe_metavariables"] = [{"id": name("u"), "depth": "0", "assignment": None}]
    assert scoped.local_terms(s)["reason"] == "metavariable_context"
    s = unary_state()
    s["goals"].append(name("other"))
    s["metavariables"].append({**deepcopy(s["metavariables"][0]), "id": name("other")})
    assert scoped.local_terms(s)["reason"] == "requires_single_goal"


def test_even_assigned_term_metavariables_abstain():
    s = unary_state()
    goal = s["metavariables"][0]
    s["expressions"].append(["mvar", name("other")])
    s["metavariables"].append({**deepcopy(goal), "id": name("other"), "assignment": "2"})
    goal["locals"][-1]["type"] = "4"
    assert scoped.local_terms(s)["reason"] == "metavariable_context"


@pytest.mark.parametrize("options", [{"max_terms": True}, {"max_applications": 5}, {"max_checks": 0}])
def test_invalid_budgets_rejected(options):
    with pytest.raises(ValueError, match="budget"):
        scoped.local_terms(unary_state(), **options)


def test_malformed_scope_does_not_reach_search():
    s = unary_state()
    s["expressions"][1] = ["fvar", name("absent")]
    with pytest.raises(ValueError, match="unbound"):
        scoped.local_terms(s)


@pytest.mark.parametrize("tag", ["lam", "forall", "let"])
def test_capture_avoiding_substitution_under_binders(tag):
    rows = [["sort", "0"], ["bvar", "0"], ["bvar", "1"], ["bvar", "2"],
            ["app", "2", "1"], ["fvar", name("n")]]
    rows.append([tag, name("x"), "explicit", "0", "4"] if tag != "let" else
                ["let", name("x"), False, "0", "1", "4"])
    g = scoped._Graph(rows)
    result = g.instantiate(g.refs[6], g.refs[5])
    body = g.nodes[result][-1]
    assert g.nodes[body] == ("app", g.refs[5], g.refs[1])
    if tag == "let":
        assert g.nodes[result][-2] == g.refs[5]  # Value is outside the new binder.
    assert g.instantiate(g.refs[3], g.refs[5]) == g.refs[2]  # Outer index decrements.
    with pytest.raises(ValueError, match="loose"):
        g.instantiate(g.refs[6], g.refs[1])


def test_normalization_and_substitution_keep_dag_sharing():
    rows = [["sort", "0"], ["bvar", "0"], ["fvar", name("x")]]
    root = 1
    for _ in range(28):
        rows.append(["app", str(root), str(root)])
        root = len(rows) - 1
    rows.extend([["forall", name(n), "explicit", "0", str(root)] for n in ("a", "b")])
    g = scoped._Graph(rows)
    assert g.refs[-1] == g.refs[-2]
    r = g.instantiate(g.refs[root], g.refs[2])
    work = g.work
    assert g.nodes[r][1] == g.nodes[r][2]
    assert g.instantiate(g.refs[root], g.refs[2]) == r and g.work == work
    assert len(g.nodes) < 70 and work < 32  # Expanded tree has > 2**28 nodes.


def test_substitution_memoization_distinguishes_binder_depth():
    # The same bvar 0 is substituted outside a lambda, and retained inside it.
    g = scoped._Graph([["sort", "0"], ["bvar", "0"], ["fvar", name("x")],
                       ["lam", name("a"), "explicit", "0", "1"], ["app", "1", "3"]])
    result = g.instantiate(g.refs[4], g.refs[2])
    assert g.nodes[result] == ("app", g.refs[2], g.refs[3])


def test_substitution_work_budget_and_metadata_erasure():
    g = scoped._Graph([["bvar", "0"], ["fvar", name("x")], ["mdata", [], "1"]], work_limit=0)
    assert g.refs[1] == g.refs[2]
    with pytest.raises(scoped._Exhausted, match="work budget"):
        g.instantiate(g.refs[0], g.refs[1])


NATIVE = {
    "copy": "theorem scoped_copy (p : Prop) (h : p) : p := by\n  have a := h\n  have b := a\n  exact b\n",
    "apply": "theorem scoped_apply (p q : Prop) (f : p → q) (h : p) : q := by\n  apply f\n  exact h\n",
    "dependent": "theorem scoped_dep (p : Nat → Prop) (n : Nat) (f : ∀ x, p x) : p n := by\n  have a := f n\n  have b := a\n  exact b\n",
    "implicit": "theorem scoped_implicit (p : Nat → Prop) (n : Nat) (f : ∀ {x}, p x) : p n := by\n  have a : p n := f\n  have b := a\n  exact b\n",
    "curried": "theorem scoped_curried (p q : Nat → Prop) (n : Nat) (f : ∀ x, p x → q x) (h : p n) : q n := by\n  have a := f n h\n  have b := a\n  exact b\n",
    "alpha": "theorem scoped_alpha (f : (x : Nat) → x = x) : (y : Nat) → y = y := by\n  intro y\n  have a := f y\n  exact a\n",
}


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    project = tmp_path_factory.mktemp("scoped")
    return project, {k: ps.capture_source(s, project_root=project, environment_sha256=ENV) for k, s in NATIVE.items()}


@pytest.mark.parametrize("kind,expected", [("copy", "exact h"), ("apply", "exact f h"),
    ("dependent", "exact f n"), ("implicit", "exact @f n"),
    ("curried", "exact f n h"), ("alpha", "exact f")])
def test_native_generated_candidate_replays_in_original_context(native, kind, expected):
    project, captures = native
    source, capture = NATIVE[kind], captures[kind]
    result = scoped.propose_scoped(source, capture, environment_sha256=ENV, limit=1)
    assert result["proposals"] and result["proposals"][0]["candidate"] == expected
    p = result["proposals"][0]
    checked = replay.replay_candidate(source, capture, **p, project_root=project, environment_sha256=ENV)
    assert checked["closing_reproduced"], checked.get("reason", checked.get("native"))
    assert not result["proof_admitted"] and not checked["proof_admitted"]


def test_before_context_never_copies_a_later_alias(native):
    _, captures = native
    c, source = captures["copy"], NATIVE["copy"]
    result = scoped.propose_scoped(source, c, environment_sha256=ENV)
    for d in result["events"]:
        e = c["trace"]["events"][d["event_id"]]
        span = source.encode()[int(e["start"]):int(e["end"])].decode()
        if "have a" in span:
            assert [t["candidate"] for t in d["candidates"]] == ["exact h"]


def test_stale_capture_abstains_before_type_search(native, monkeypatch):
    _, captures = native
    monkeypatch.setattr(scoped, "local_terms", lambda *a, **kw: pytest.fail("searched stale capture"))
    with pytest.raises(ValueError, match="stale"):
        scoped.propose_scoped(NATIVE["copy"] + "\n", captures["copy"], environment_sha256=ENV)


def test_native_admission_and_eval_isolation(native):
    project, captures = native
    class Evaluation(dict):
        def __getitem__(self, key):
            assert key not in ("source", "target"), "evaluation data accessed"
            return super().__getitem__(key)
    rows = [{"id": "copy", "split": "train", "source": NATIVE["copy"]},
            *[Evaluation(id=s, split=s) for s in ("validation", "canary", "holdout")]]
    opts = dict(capture_fn=lambda _: captures["copy"],
        replay_fn=partial(replay.replay_candidate, project_root=project, environment_sha256=ENV),
        proposal_fn=partial(scoped.scoped_proposals, environment_sha256=ENV, limit=1), environment_sha256=ENV)
    compiler = _lean_compiler(project_root=project, kernel_only=True, export_dags=True, environment_sha256=ENV)
    result = replay.collect_replay_pairs(rows, compile_fn=compiler, **opts)
    assert result["ok"] and len(result["pairs"]) == 1
    assert result["pairs"][0]["teacher_admitted"] and result["pairs"][0]["expression_nonregression"]
    failed = replay.collect_replay_pairs(rows, compile_fn=lambda _: {"theorem_ok": False}, **opts)
    assert not failed["ok"] and not failed["pairs"]
    assert failed["attempts"][0]["replay"]["closing_reproduced"]
