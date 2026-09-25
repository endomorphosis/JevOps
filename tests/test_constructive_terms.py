"""Structural rendering is hygienic, bounded and never an admission shortcut."""
import json
import shutil

import pytest

from jevops.constructive_proofs import read_proposition, search
from jevops.constructive_terms import node, render_tree, validate_tree
from jevops.logic_ir import parse_formula


CASES = [
    ("", "p → p"), ("", "True"), ("(h : False)", "p"),
    ("(h : p ∧ q)", "q ∧ p"), ("(h : p ↔ q) (hp : p)", "q"),
    ("(h : p ∨ q) (f : p → r) (g : q → r)", "r"),
    ("", "p → (p ∨ q)"), ("", "p ↔ p"), ("", "(p ∧ q) → p"),
    ("(f : p → q) (g : q → r) (h : p)", "r"),
]


@pytest.mark.parametrize("context,goal", CASES)
def test_tree_output_preserves_existing_search_decisions(context, goal):
    _, formula, assumptions = read_proposition(f"theorem t (p q r : Prop) {context} : {goal} := by skip")
    original = search(formula, assumptions)
    structured = search(formula, assumptions, include_term_ir=True)
    tree = structured.pop("term_ir")
    assert original == structured and tree is not None
    assert render_tree(tree) == render_tree(json.loads(json.dumps(tree)))
    assert not original["global_minimum"]


def test_replaces_exact_local_leaves_not_prefixes_and_rejects_shadowing():
    term = node("app", node("local", name="_g1"), node("local", name="_g10"))
    assert render_tree(term, {"_g1": ("_root_.Or.inl", True)}) == "_root_.Or.inl _g10"
    with pytest.raises(ValueError, match="shadowing"):
        render_tree(node("lambda", term, name="_g1"), {"_g1": ("x", True)})
    assert render_tree(node("proj", node("local", name="_g1"), name="mpr"),
                       {"_g1": ("_root_.And.comm", True)}) == "(_root_.And.comm).mpr"


def test_free_identifier_in_replacement_cannot_be_captured():
    tree = node("lambda", node("local", name="h"), name="p")
    with pytest.raises(ValueError, match="shadowing"):
        render_tree(tree, {"h": ("@_root_.Or.inl (p) (q)", False)})


@pytest.mark.parametrize("tree", [node("const", name="axiom"), node("local", name="x.y"),
    node("proj", node("local", name="h"), name="bad"), node("lambda", name="h"),
    {"op": "local", "name": "h", "args": [], "authority": True}, node("eval", name="x"),
    node("local", name="h" * 257)])
def test_invalid_tree_cannot_inject_lean_text(tree):
    with pytest.raises(ValueError):
        render_tree(tree)


def test_tree_depth_cycles_size_and_replacement_limits_fail_closed():
    tree = node("local", name="h")
    tree["op"], tree["name"], tree["args"] = "app", "", [tree, node("local", name="h")]
    with pytest.raises(ValueError, match="budget"):
        validate_tree(tree)
    tree = node("local", name="h")
    for _ in range(13):
        tree = node("pair", tree, tree)
    with pytest.raises(ValueError, match="budget"):
        validate_tree(tree)
    with pytest.raises(ValueError):
        render_tree(node("local", name="h"), {str(i): ("x", True) for i in range(17)})
    with pytest.raises(ValueError, match="policy"):
        search(parse_formula("True"), [], include_term_ir=1)


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires installed Lean")
@pytest.mark.no_seal(reason="fresh native structural renderer operator control")
def test_native_renderer_covers_all_constructive_operators(tmp_path):
    from jevops.router_tuning import _lean_compiler
    compiler = _lean_compiler(project_root=tmp_path, kernel_only=True)
    candidates = []
    for i, (context, goal) in enumerate(CASES):
        statement = f"theorem render{i} (p q r : Prop) {context} : {goal}"
        _, formula, assumptions = read_proposition(statement + " := by skip")
        proof = search(formula, assumptions, include_term_ir=True)
        candidates.append(statement + " := " + render_tree(proof["term_ir"]))
    result = compiler("\n".join(candidates))
    assert result["theorem_ok"] and result["kernel_audit"]["axioms"] == [], result
