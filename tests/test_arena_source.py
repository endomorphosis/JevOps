"""Source shape is not kernel checking, source execution, or a cost receipt."""
from dataclasses import replace
import json

import pytest

from jevops.arena import source_hash
from jevops.arena_source import (ExplicitTermPolicy, SourceMismatch, UnsupportedSource,
                                match_export, parse_source)
from jevops.expr_dag import SCHEMA, METADATA_POLICY

STATEMENT = "theorem source_example (h : True) : True"
ENV = "a" * 64
TOOLCHAIN = ("4.26.0", "b" * 40)
TRUE = ("const", [["s", "True"]], [])
INTRO = ("const", [["s", "True"], ["s", "intro"]], [])
VAR = ("bvar", "0")


def lam(name, domain, value):
    return ("lam", [["s", name]], "explicit", domain, value)


def forall(name, domain, value):
    return ("forall", [["s", name]], "explicit", domain, value)


def wire(proof, typ):
    """Independent tiny test encoder; no source parser or matcher used."""
    rows, seen = [], {}
    def emit(node):
        row = list(node)
        for p in {"app": (1, 2), "lam": (3, 4), "forall": (3, 4), "mdata": (2,)}.get(row[0], ()):
            row[p] = emit(row[p])
        key = json.dumps(row)
        if key not in seen:
            seen[key] = str(len(rows)); rows.append(row)
        return seen[key]
    roots = [emit(proof), emit(typ)]
    return {"schema": SCHEMA, "metadata_policy": METADATA_POLICY, "environment": ENV,
            "lean_version": TOOLCHAIN[0], "lean_githash": TOOLCHAIN[1],
            "levels": [], "expressions": rows, "roots": roots}


def check(body="@h", *, statement=STATEMENT, proof=None, typ=None, policy=None):
    policy = policy if policy is not None else ExplicitTermPolicy()
    source = statement + " := by exact " + body
    plan = parse_source(source, statement, policy)
    return match_export(plan, wire(proof or lam("h", TRUE, VAR), typ or forall("h", TRUE, TRUE)),
                        environment=ENV, node_budget=256, toolchain=TOOLCHAIN)


def test_explicit_local_has_source_bound_structure_not_proof_authority():
    result = check()
    assert result["structure_matches"] is True
    assert result["source_sha256"] == source_hash(STATEMENT + " := by exact @h")
    assert result["plan"]["binders"] == ("h",)
    for key in ("execution_attested", "imported_syntax_audited", "metric_integrity_established"):
        assert result[key] is False


def test_explicit_application_tracks_debruijn_indices_not_votes():
    statement = "theorem apply_example (f : True -> True) (h : True) : True"
    fn_type = forall("x", TRUE, TRUE)
    proof = lam("f", fn_type, lam("h", TRUE, ("app", ("bvar", "1"), VAR)))
    typ = forall("f", fn_type, forall("h", TRUE, TRUE))
    assert check("(@f @h)", statement=statement, proof=proof, typ=typ)["structure_matches"]
    with pytest.raises(SourceMismatch):
        check("(@h @f)", statement=statement, proof=proof, typ=typ)


def test_only_fully_qualified_allowlisted_constant_is_matched():
    policy = ExplicitTermPolicy(("True.intro",))
    assert check("@_root_.True.intro", proof=lam("h", TRUE, INTRO), policy=policy)["structure_matches"]
    with pytest.raises(SourceMismatch):
        check("@_root_.True.intro", policy=policy)


def test_scalar_metadata_erasure_is_the_only_normalization():
    mdata = ("mdata", [], VAR)
    assert check(proof=("mdata", [], lam("h", ("mdata", [], TRUE), mdata)))["structure_matches"]
    # True proofs are proof-irrelevant in Lean: that must NOT excuse a source substitution.
    with pytest.raises(SourceMismatch, match="local_reference"):
        check(proof=lam("h", TRUE, INTRO))


@pytest.mark.parametrize("body", ["h", "@unknown", "@h ", " @h", "@h\n", "(@h)", "(@h  @h)",
    "(@h\t@h)", "((@h @h) @h)", "@h --ignored", "@h /-ignored-/", "@h; skip", "@h\n#eval 1",
    "(by exact h)", "@_root_.True.intro", "@True.intro", "@h.{0}", "?hole", "_", "@«h»",
    "@h\x00", "@h😈", "@h := by skip", "", "@h @h"])
def test_no_implicit_syntax_comments_commands_or_unknown_names(body):
    with pytest.raises(UnsupportedSource):
        check(body)


@pytest.mark.parametrize("statement", [
    "theorem source_example : (h : True) -> True",  # h is NOT in the declaration context.
    "theorem source_example {h : True} : True", "theorem source_example (h k : True) : True",
    "theorem source_example (h : True) (h : True) : True",
    "theorem source_example (h : True := True.intro) : True",
    "theorem source_example /- comment -/ (h : True) : True",
    "theorem source_example (h : ) : True", "theorem source_example (h : True : True",
])
def test_binders_are_not_inferred_from_export_or_goal(statement):
    with pytest.raises(UnsupportedSource):
        check(statement=statement)


@pytest.mark.parametrize("proof,typ", [
    (lam("other", TRUE, VAR), forall("h", TRUE, TRUE)),
    (lam("h", INTRO, VAR), forall("h", TRUE, TRUE)),
    (lam("h", TRUE, lam("hidden", TRUE, VAR)), forall("h", TRUE, forall("hidden", TRUE, TRUE))),
    (INTRO, forall("h", TRUE, TRUE)),
])
def test_generated_binders_and_parameter_domains_cannot_be_substituted(proof, typ):
    with pytest.raises(SourceMismatch):
        check(proof=proof, typ=typ)


@pytest.mark.parametrize("constants", [["True.intro"], ("True.intro", "True.intro"), ("x;run",),
                                      ("_root_.x",), ("",), (True,), tuple(f"c{i}" for i in range(65))])
def test_policy_is_typed_bounded_and_unique(constants):
    with pytest.raises(ValueError): ExplicitTermPolicy(constants)


def test_policy_order_has_canonical_identity():
    assert ExplicitTermPolicy(("A", "B")).record() == ExplicitTermPolicy(("B", "A")).record()


@pytest.mark.parametrize("limit", ["bytes", "depth", "nodes"])
def test_source_size_depth_and_node_limits(limit):
    if limit == "bytes": body = "@" + "x" * 8192
    elif limit == "depth": body = "(@h " * 33 + "@h" + ")" * 33
    else:
        body = "@h"
        for _ in range(7): body = f"(@h {body} {body})"  # shallow 509-node term, under 8192 bytes
    with pytest.raises(UnsupportedSource, match="budget"):
        check(body)


def test_statement_binder_count_limit():
    statement = "theorem many " + " ".join(f"(h{i} : True)" for i in range(65)) + " : True"
    with pytest.raises(UnsupportedSource): check("@h0", statement=statement)


def test_plan_is_frozen_and_wrong_dag_context_rejected():
    plan = parse_source(STATEMENT + " := by exact @h", STATEMENT, ExplicitTermPolicy())
    assert replace(plan, source_sha256="old").source_sha256 != plan.source_sha256
    with pytest.raises(AttributeError): plan.binders += ("extra",)
    with pytest.raises(ValueError, match="environment mismatch"):
        match_export(plan, wire(lam("h", TRUE, VAR), forall("h", TRUE, TRUE)),
                     environment="c" * 64, node_budget=256, toolchain=TOOLCHAIN)


def test_universe_arguments_are_not_silently_inferred_from_constant_names():
    plan = parse_source(STATEMENT + " := by exact @_root_.True.intro", STATEMENT,
                        ExplicitTermPolicy(("True.intro",)))
    data = wire(lam("h", TRUE, INTRO), forall("h", TRUE, TRUE))
    data["levels"] = [["zero"]]
    for row in data["expressions"]:
        if row[0] == "const" and row[1] == INTRO[1]: row[2] = ["0"]
    with pytest.raises(SourceMismatch, match="universes"):
        match_export(plan, data, environment=ENV, node_budget=256, toolchain=TOOLCHAIN)


def test_flat_explicit_spine_is_left_associative_and_its_ast_depth_is_bounded():
    plan = parse_source(STATEMENT + " := by exact (@h @h @h)", STATEMENT, ExplicitTermPolicy())
    assert plan.term.kind == plan.term.children[0].kind == "app"
    # Even shallow source parentheses cannot smuggle in a deep left spine.
    with pytest.raises(UnsupportedSource, match="depth_budget"):
        parse_source(STATEMENT + " := by exact (" + " ".join(["@h"] * 34) + ")",
                     STATEMENT, ExplicitTermPolicy())
