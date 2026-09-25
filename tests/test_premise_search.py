"""Selection is advice: exact scope binding and declared leakage exclusions."""
from dataclasses import replace

import pytest
from jevops.arena import content_hash
from jevops.premise_search import Premise, PremiseIndex, PremiseScope, symbols

ENV = content_hash("fixture environment, not an attestation")
RECORD = content_hash("fixture record")


def rank(entries, *, available=None, excluded=(), origins=(), target="Target", **kwargs):
    scope = PremiseScope(RECORD, ENV, tuple(available if available is not None else [p.name for p in entries]),
                         excluded, origins)
    return PremiseIndex(tuple(entries), environment_sha256=ENV).rank(
        "theorem Target (xs : List Nat) : xs = xs", target=target, scope=scope, **kwargs)


def test_stable_case_sensitive_ranking_and_hard_top_k():
    entries = [Premise("B", "List Nat", "lib"), Premise("A", "List Nat", "lib"),
               Premise("C", "Bool", "lib")]
    a = rank(entries, top_k=1)
    b = rank(list(reversed(entries)), top_k=1)
    # Scope identity preserves its supplied order; the index and ranks do not.
    assert a["index_sha256"] == b["index_sha256"]
    assert a["matches"] == b["matches"]
    assert [m["name"] for m in a["matches"]] == ["A"]
    assert a["proof_verified"] is False and a["considered"] == 2
    assert symbols("Nat.add List") != symbols("nat.add list")


def test_excludes_target_aliases_holdouts_wrappers_and_protected_families():
    entries = [Premise("Target", "List Nat", "benchmark", aliases=("Renamed",)),
               Premise("Wrapper", "List Nat", "lib", dependencies=("Renamed",)),
               Premise("Canary", "List Nat", "canary-family", split="canary", aliases=("CanaryAlias",)),
               Premise("CanaryWrapper", "List Nat", "train", dependencies=("CanaryAlias",)),
               Premise("FamilyClone", "List Nat", "reserved-family", split="train"),
               Premise("Good", "List Nat", "stdlib")]
    available = tuple(n for p in entries for n in (p.name, *p.aliases))
    result = rank(entries, available=available, origins=("reserved-family",))
    assert [m["name"] for m in result["matches"]] == ["Good"]
    assert len(result["excluded"]) == 5


def test_native_qualified_types_match_source_dot_notation_without_aliasing_names():
    entries = (Premise("A.subset", "List.Subset a b", "lib"),
               Premise("B.subset", "Other.Subset a b", "heldout", split="canary"))
    scope = PremiseScope(RECORD, ENV, ("A.subset", "B.subset"))
    index = PremiseIndex(entries, environment_sha256=ENV)
    result = index.rank("(extractOldExprVars post).Subset values", target="Target", scope=scope)
    assert [m["name"] for m in result["matches"]] == ["A.subset"]
    assert "List.Subset" in symbols("List.Subset a b")
    assert "Subset" in symbols("List.Subset a b")
    assert "subset" not in symbols("List.Subset a b")
    assert result["feature_method"].endswith("/v2")


def test_feature_method_is_part_of_index_identity(monkeypatch):
    from jevops import premise_search
    entries = (Premise("A", "List Nat", "lib"),)
    first = PremiseIndex(entries, environment_sha256=ENV)
    monkeypatch.setattr(premise_search, "FEATURE_METHOD", "different-test-method")
    assert PremiseIndex(entries, environment_sha256=ENV).index_sha256 != first.index_sha256


def test_alias_target_and_unknown_excluded_dependency_propagate_transitively():
    entries = [Premise("Original", "List Nat", "lib", aliases=("Target",)),
               Premise("A", "List Nat", "lib", dependencies=("Secret",)),
               Premise("B", "List Nat", "lib", dependencies=("A",))]
    assert rank(entries, available=("Original", "Target", "A", "B", "Secret"),
                excluded=("Secret",))["matches"] == []


def test_availability_is_required_for_candidate_and_declared_dependencies():
    entries = [Premise("Absent", "List Nat", "lib"),
               Premise("UsesAbsent", "List Nat", "lib", dependencies=("Absent",))]
    result = rank(entries, available=("UsesAbsent",))
    assert result["matches"] == []
    assert {e["reason"] for e in result["excluded"]} == {"not_in_scope"}


@pytest.mark.parametrize("split", ["validation", "canary", "test"])
def test_nontraining_splits_never_nominated(split):
    assert rank([Premise("Heldout", "List Nat", "family", split=split)])["matches"] == []


def test_budget_overflow_abstains_instead_of_biased_partial_ranking():
    entries = [Premise(f"P{i}", "List Nat", "lib") for i in range(10)]
    result = rank(entries, max_scan=3)
    assert result["status"] == "SCAN_BUDGET" and result["considered"] == 4
    assert result["matches"] == result["excluded"] == []


def test_index_queries_only_score_matching_postings():
    entries = [Premise(f"P{i}", "Bool", "lib") for i in range(100)] + [Premise("Useful", "List Nat", "lib")]
    result = rank(entries, max_scan=1)
    assert result["status"] == "RANKED" and result["considered"] == 1
    assert result["matches"][0]["name"] == "Useful"


def test_environment_mismatch_and_inventory_mutations_have_different_identities():
    p = Premise("Useful", "List Nat", "lib")
    index = PremiseIndex((p,), environment_sha256=ENV)
    with pytest.raises(ValueError, match="environment"):
        index.rank("List Nat", target="Target", scope=PremiseScope(RECORD, "a" * 64, (p.name,)))
    assert index.index_sha256 != PremiseIndex((replace(p, type_text="List Bool"),), environment_sha256=ENV).index_sha256
    assert index.index_sha256 != PremiseIndex((replace(p, split="canary"),), environment_sha256=ENV).index_sha256


@pytest.mark.parametrize("field,value", [("top_k", 0), ("top_k", 9), ("top_k", True),
                                        ("max_scan", 0), ("max_scan", 8193), ("max_scan", 1.1)])
def test_invalid_query_limits_fail_before_search(field, value):
    with pytest.raises(ValueError):
        rank([], **{field: value})


@pytest.mark.parametrize("name", ["Nat.zero; sorry", "_root_.Nat.zero", "bad\nname", "", "9foo", "x" * 257])
def test_declaration_text_is_not_executable_syntax(name):
    with pytest.raises(ValueError):
        Premise(name, "Nat", "lib")


def test_duplicate_names_aliases_and_missing_provenance_rejected():
    p = Premise("A", "Nat", "lib", aliases=("Alias",))
    for entries in ((p, p), (p, Premise("Alias", "Nat", "lib"))):
        with pytest.raises(ValueError, match="identity"):
            PremiseIndex(entries, environment_sha256=ENV)
    with pytest.raises(ValueError):
        replace(p, origin="")
    with pytest.raises(ValueError):
        PremiseScope(RECORD, ENV, ("A", "A"))
    with pytest.raises(ValueError):
        PremiseIndex((p,), environment_sha256="unversioned")
