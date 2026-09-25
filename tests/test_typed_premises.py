"""Raw native type features are retrieval hints; only replay checks application."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path

import pytest

from jevops import arena_premises as exporter, arena_lean as native, arena_local as local
from jevops.arena import content_hash, VerificationRequest
from jevops.arena_providers import load_inventory, plan_local_applications
from jevops.lean import VersionPin
from jevops.premise_search import ExprHead, PremiseSignature, Premise, PremiseIndex, PremiseScope
from jevops.scoped_proposals import goal_head
from tests.test_arena_premises import guard, stage, SPECS, RECORD, PIN, OTHER
from tests.test_local_premise_replay import state, name, capture_fixture, RECORD as LOCAL_RECORD


def signature(n="True.intro", head="True"):
    return PremiseSignature(n, (), (), ExprHead("const", head))


def typed_stage(binding, payload):
    value = stage(binding, payload)
    value["schema"] = payload["schema"]
    if payload["schema"] == exporter.SIGNATURE_STAGE_SCHEMA:
        for row in value["report"]["entries"]:
            row["signature"] = signature(row["name"]).to_dict()
    return value


def test_v2_roundtrip_and_v1_defaults_unchanged(guard):
    reports = [exporter.NativePremiseExporter(guard, max_processes=2, runner=typed_stage,
        include_signatures=typed).export(RECORD, SPECS) for typed in (False, True)]
    old, new = reports
    assert old["inventory"]["schema"] == "jevops-premise-index/v1"
    assert "signatures" not in old["inventory"]
    assert new["inventory"]["schema"] == "jevops-premise-index/v2"
    indexes = [load_inventory(json.loads(json.dumps(r["inventory"])), json.loads(json.dumps(r["scope"])))[0] for r in reports]
    assert indexes[1].signatures["True.intro"] == signature()
    assert indexes[0].index_sha256 != indexes[1].index_sha256
    assert new["status"] == "FIXTURE_ONLY" and not new["proof_verified"]
    assert PremiseSignature.from_dict(signature().to_dict()) == signature()


@pytest.mark.parametrize("damage", ["name", "arity", "extra", "binder", "binder_count", "schema", "nan"])
def test_invalid_signature_never_exports_partial_inventory(guard, damage):
    def broken(binding, payload):
        value = typed_stage(binding, payload)
        sig = value["report"]["entries"][0]["signature"]
        if damage == "name": sig["name"] = "Foreign.proof"
        elif damage == "arity": sig["conclusion"]["arity"] = True
        elif damage == "extra": sig["verified"] = True
        elif damage == "binder": sig["binder_kinds"] = ["invented"]
        elif damage == "binder_count": sig["binder_heads"] = [sig["conclusion"]]
        elif damage == "schema": sig["schema"] = "future"
        else: sig["conclusion"]["arity"] = float("nan")
        return value
    report = exporter.NativePremiseExporter(guard, max_processes=2, runner=broken,
        include_signatures=True).export(RECORD, SPECS)
    assert report["status"] == "INCOMPLETE" and report["inventory"] is None


@pytest.mark.parametrize("damage", ["missing", "different"])
def test_unavailable_or_version_different_signature_retains_lexical_premise(guard, damage):
    def changed(binding, payload):
        value = typed_stage(binding, payload)
        if binding.pin == OTHER:
            row = value["report"]["entries"][0]
            row["signature"] = None if damage == "missing" else signature(head="Other.True").to_dict()
        return value
    report = exporter.NativePremiseExporter(guard, max_processes=2, runner=changed,
        include_signatures=True).export(RECORD, SPECS)
    assert report["status"] == "FIXTURE_ONLY" and report["inventory"]["signatures"] == []
    assert report["scope"]["available_names"] == ("True.intro",)
    assert report["signature_exclusions"][0]["reason"] == (
        "UNSUPPORTED_ON_A_PIN" if damage == "missing" else "SIGNATURE_DIFFERS")


def rank_fixture(**kwargs):
    entries = tuple(Premise(n, "List.Nodup Nat", "fixture") for n in ("A.wrong", "B.right", "C.generic", "D.right"))
    signatures = (signature("A.wrong", "True"), signature("B.right", "List.Nodup"),
        PremiseSignature("C.generic", ("implicit",), (ExprHead("sort"),), ExprHead("bound")),
        signature("D.right", "List.Nodup"))
    env = content_hash("fixture")
    index = PremiseIndex(entries, environment_sha256=env, signatures=signatures)
    scope = PremiseScope(content_hash("record"), env, tuple(p.name for p in entries))
    return index, scope


def test_head_priority_reserves_fallback_without_claiming_applicability():
    index, scope = rank_fixture()
    old = index.rank("List.Nodup Nat", target="Target", scope=scope, top_k=1)
    new = index.rank("List.Nodup Nat", target="Target", scope=scope, top_k=1, conclusion=ExprHead("const", "List.Nodup"))
    assert old["matches"][0]["name"] == "A.wrong"
    assert new["matches"][0]["name"] == "B.right" and not new["proof_verified"]
    result = index.rank("List.Nodup Nat", target="Target", scope=scope, top_k=2, conclusion=ExprHead("const", "List.Nodup"))
    assert [r["name"] for r in result["matches"]] == ["B.right", "C.generic"]
    result = index.rank("List.Nodup Nat", target="Target", scope=scope, top_k=8, conclusion=ExprHead("const", "List.Nodup"))
    assert {r["name"] for r in result["matches"]} == set(index.entries)
    excluded = replace(scope, excluded_names=("B.right", "D.right"))
    assert {r["name"] for r in index.rank("List.Nodup Nat", target="Target", scope=excluded,
        conclusion=ExprHead("const", "List.Nodup"))["matches"]} == {"A.wrong", "C.generic"}


def test_index_boundaries_bytes_and_identity():
    index, scope = rank_fixture()
    result = index.rank("List.Nodup Nat", target="Target", scope=scope, max_scan=1,
                        conclusion=ExprHead("const", "List.Nodup"))
    assert result["status"] == "SCAN_BUDGET" and not result["matches"]
    entries = tuple(index.entries.values())
    with pytest.raises(ValueError): PremiseIndex(entries, environment_sha256=index.environment_sha256, signatures=(signature(),))
    with pytest.raises(ValueError): PremiseIndex(entries, environment_sha256=index.environment_sha256,
                                                signatures=(signature("A.wrong"), signature("A.wrong")))
    with pytest.raises(ValueError, match="byte budget"):
        PremiseSignature("huge", ("explicit",) * 64, (ExprHead("const", "x" * 1024),) * 64, ExprHead("sort"))
    assert PremiseIndex(entries, environment_sha256=index.environment_sha256).index_sha256 != index.index_sha256


def test_typed_head_postings_find_low_lexical_overlap_and_still_honor_scan_cap():
    env = content_hash("fixture")
    entries = (Premise("HiddenByText", "display_alias", "fixture"), Premise("Lexical", "True", "fixture"))
    index = PremiseIndex(entries, environment_sha256=env, signatures=(signature("HiddenByText"),))
    scope = PremiseScope(content_hash("record"), env, tuple(p.name for p in entries))
    assert [r["name"] for r in index.rank("True", target="Target", scope=scope)["matches"]] == ["Lexical"]
    typed = index.rank("True", target="Target", scope=scope, conclusion=ExprHead("const", "True"))
    assert typed["matches"][0]["name"] == "HiddenByText"
    assert typed["matches"][0]["head_priority"] == 0 and typed["matches"][1]["head_priority"] == 1
    overflow = index.rank("True", target="Target", scope=scope, max_scan=1, conclusion=ExprHead("const", "True"))
    assert overflow["status"] == "SCAN_BUDGET" and overflow["matches"] == []


def test_budget_accounts_for_signature_bytes_and_v2_rejects_authority_fields(monkeypatch):
    from jevops import premise_search
    env = content_hash("fixture")
    entries = (Premise("True.intro", "True", "fixture"),)
    monkeypatch.setattr(premise_search, "MAX_INDEX_BYTES", 40)
    PremiseIndex(entries, environment_sha256=env)
    with pytest.raises(ValueError, match="byte budget"):
        PremiseIndex(entries, environment_sha256=env, signatures=(signature(),))
    with pytest.raises(ValueError, match="fields"):
        load_inventory({"schema": "jevops-premise-index/v2", "environment_sha256": env,
            "premises": [], "signatures": [], "verified": True}, {})


def test_goal_features_do_not_use_unrelated_expression_nodes_and_bind_request():
    s = state()
    s["expressions"].append(["const", name("Unrelated"), []])
    with pytest.raises(ValueError, match="unreachable"):
        goal_head(s)
    s["metavariables"][0]["locals"] = [{"id": name("u"), "name": name("u"), "index": "0",
        "type": "1", "value": None, "nondep": False, "binder": "explicit", "kind": "default"}]
    assert goal_head(s) == ExprHead("const", "True")
    assert goal_head(s, max_steps=0) is None
    env = capture_fixture()["dependency_environment_sha256"]
    index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env,
                         signatures=(signature(),))
    scope = PremiseScope(content_hash(LOCAL_RECORD), env, ("True.intro",))
    old = plan_local_applications(LOCAL_RECORD, capture_fixture(), index, scope)
    new = plan_local_applications(LOCAL_RECORD, capture_fixture(), index, scope, retrieval="typed-head-v1")
    assert new["events"][0]["goal_head"] == asdict(ExprHead("const", "True"))
    assert old["request"]["request_sha256"] != new["request"]["request_sha256"]
    with pytest.raises(ValueError): plan_local_applications(LOCAL_RECORD, capture_fixture(), index, scope, retrieval="magic")


@pytest.mark.no_seal(reason="opt-in installed Lean signature export and real application checks")
def test_native_signatures_prioritize_conclusions_not_lexical_premises(tmp_path):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in, no downloads/models")
    tag = os.environ.get("JEVOPS_SIGNATURE_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "native-signature-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    before = ("theorem A_bad {p : Prop} (h : p ∨ True) : True := True.intro\n"
              "theorem B_good {p : Prop} (h : p) : p ∨ True := Or.inl h\n"
              "theorem generic {p : Prop} (h : p) : p := h\n"
              "theorem instanceLemma {α : Type} [Inhabited α] : Nonempty α := ⟨default⟩\n"
              "abbrev Alias := True\ntheorem aliasLemma : Alias := True.intro\nnamespace Suite\n")
    statement = "theorem sample (p : Prop) (h : p) : p ∨ True"
    source = statement + " := by\n  exact Or.inl (id h)\n"
    record = {"name": "Suite.sample", "statement": statement, "src": source,
              "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, before, project_backed=False)
    guard = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    noms = tuple(exporter.PremiseOrigin(n, "control", "library") for n in
                 ("A_bad", "B_good", "generic", "instanceLemma", "aliasLemma"))
    report = exporter.NativePremiseExporter(guard, max_processes=1, include_signatures=True).export(record, noms)
    assert report["status"] == "INVENTORY_ONLY", report
    index, scope = load_inventory(json.loads(json.dumps(report["inventory"])), json.loads(json.dumps(report["scope"])))
    assert index.signatures["A_bad"].conclusion == ExprHead("const", "True")
    assert index.signatures["B_good"].conclusion == ExprHead("const", "Or", 2)
    assert index.signatures["B_good"].binder_kinds == ("implicit", "explicit")
    assert index.signatures["generic"].conclusion.kind == "bound"
    assert index.signatures["instanceLemma"].binder_kinds == ("implicit", "instance")
    assert index.signatures["aliasLemma"].conclusion.name == "Alias"  # no claimed delta reduction
    rt = local.ArenaLocalRuntime(guard, record, max_processes=3)
    observed = rt.capture(pin)
    assert observed["ok"], observed
    batches = [rt.discover_batch(pin, observed["capture"], index, scope, cap=1, max_events=1,
        max_applications=1, top_k=1, retrieval=mode) for mode in ("lexical-v1", "typed-head-v1")]
    assert batches[0]["attempts"][0]["premise"] == "A_bad" and not batches[0]["drafts"], batches[0]
    assert batches[1]["attempts"][0]["premise"] == "B_good" and len(batches[1]["drafts"]) == 1, batches[1]
    assert guard(VerificationRequest(rt.context, batches[1]["drafts"][0]["source"], pin)).outcome.value == "VERIFIED"
    assert not batches[1]["proof_verified"] and rt.attempts == 3
