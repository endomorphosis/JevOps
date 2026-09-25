"""Evidence mappings are proposals; only all-pin Lean checking discharges them."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")
from jevops.arena import (ArenaContext, ArenaEvaluator, Outcome, VersionReceipt,
                         content_hash, reference_tokens, source_hash)
from jevops.knowledge_relations import (DeclarationBinding, EvidenceRelation, PropositionNode,
    RelationGraph, RelationLimits, evaluate_relations, propose_relations)
from jevops.lean import VersionPin
from jevops.logic_ir import parse_formula
from jevops.premise_search import ExprHead, Premise, PremiseIndex, PremiseScope, PremiseSignature
from jevops.skillcenter_corpus import EvidenceCorpus, _cid
from tests.test_skillcenter_corpus import ingest

pytestmark = pytest.mark.no_seal(reason="fresh DuckDB evidence-to-Lean bridge controls")
STATEMENT = "theorem sample (p q : Prop) : (p ∧ q) ↔ (q ∧ p)"
SOURCE = STATEMENT + " := by\n  constructor\n  · intro h\n    exact And.intro h.right h.left\n  · intro h\n    exact And.intro h.right h.left\n"
PINS = (VersionPin("fixture-a", "a"), VersionPin("fixture-b", "b"))
ENV = content_hash("relation-fixture")
PREFIX = ("namespace Bridge\n"
    "theorem forward (p q : Prop) : (p ∧ q) → (q ∧ p) := fun h => ⟨h.right, h.left⟩\n"
    "theorem backward (p q : Prop) : (q ∧ p) → (p ∧ q) := fun h => ⟨h.right, h.left⟩\n"
    "theorem wrong (p q : Prop) : (p ∨ q) → (q ∨ p) := fun h => h.elim Or.inr Or.inl\n"
    "theorem left (p q : Prop) : p → (p ∨ q) := Or.inl\n"
    "theorem equiv (p q : Prop) : (p ∧ q) ↔ (q ∧ p) := ⟨forward p q, backward p q⟩\n"
    "end Bridge\n")


def binding(edge, name, index, arguments=("p", "q")):
    return DeclarationBinding(edge, name, content_hash(asdict(index.entries[name])),
        content_hash(index.signatures[name].to_dict()), tuple(parse_formula(a) for a in arguments))


def graph_for(record, index, corpus, cid):
    return RelationGraph(content_hash(record), index.environment_sha256, corpus.identity["snapshot_sha256"],
        content_hash("manual-control-extraction/v1"),
        (PropositionNode("pq", parse_formula("p ∧ q")), PropositionNode("qp", parse_formula("q ∧ p"))),
        (EvidenceRelation("forward", "implies", "pq", "qp", (cid,)),
         EvidenceRelation("backward", "implies", "qp", "pq", (cid,))),
        (binding("forward", "Bridge.forward", index), binding("backward", "Bridge.backward", index)))


@pytest.fixture
def setup(tmp_path):
    context = ArenaContext("sample", STATEMENT, SOURCE, reference_tokens(SOURCE, STATEMENT), 100,
                           PINS, (ENV, ENV), "fixture", "1", "synthetic/v1")
    record = dict(name="sample", statement=STATEMENT, src=SOURCE,
                  version_info=[{p.lean_tag: p.git_commit} for p in PINS])
    premises = tuple(Premise(name, "∀ p q : Prop, (p ∧ q) → (q ∧ p)", "library")
                     for name in ("Bridge.forward", "Bridge.backward", "Bridge.wrong"))
    signatures = tuple(PremiseSignature(p.name, ("explicit",) * 3,
        (ExprHead("sort"), ExprHead("sort"), ExprHead("const", "And", 2)), ExprHead("const", "And", 2)) for p in premises)
    index = PremiseIndex(premises, environment_sha256=context.context_id, signatures=signatures)
    scope = PremiseScope(content_hash(record), context.context_id, tuple(p.name for p in premises))
    artifact, rows = ingest(tmp_path)
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as corpus:
        cid = rows[0]["entry_cid"]
        yield SimpleNamespace(record=record, context=context, index=index, scope=scope, corpus=corpus, cid=cid,
                              graph=graph_for(record, index, corpus, cid))


def propose(s, graph=None, **changes):
    return propose_relations(graph or s.graph, **{**dict(record=s.record, index=s.index, scope=s.scope, corpus=s.corpus), **changes})


def fixture_evaluator(s, *, max_calls=2, outcome=Outcome.VERIFIED, heartbeats=50):
    calls = []
    def verifier(request):
        calls.append(request)
        return VersionReceipt(request.request_id, source_hash(request.source), request.context.problem,
            outcome, True, 0, "'sample' does not depend on any axioms", heartbeats)
    return ArenaEvaluator(s.context, verifier, max_calls=max_calls, evidence_mode="offline_fixture"), calls


def evaluate(s, proposal, evaluator, **changes):
    return evaluate_relations(proposal, s.graph, **{**dict(record=s.record, index=s.index, scope=s.scope,
                                                         corpus=s.corpus, evaluator=evaluator), **changes})


def test_opposite_directions_form_typed_obligations_not_new_assumptions(setup):
    result = propose(setup)
    assert result["status"] == "PROPOSED", result
    assert result["used_edges"] == ["backward", "forward"]
    assert result["candidate"].startswith(STATEMENT + " := by\n")
    assert "@_root_.Bridge.forward (p) (q)" in result["candidate"]
    assert "@_root_.Bridge.backward (p) (q)" in result["candidate"]
    assert all(o["status"] == "REQUIRES_NATIVE_CHECK" and not o["native_checked"] for o in result["obligations"])
    assert not result["proof_verified"] and not result["source_fidelity_verified"]
    assert not result["training_enabled"] and result["official_score"] is None
    decoded = RelationGraph.from_dict(json.loads(json.dumps(setup.graph.to_dict())))
    assert decoded.graph_sha256 == setup.graph.graph_sha256
    reversed_graph = replace(decoded, nodes=tuple(reversed(decoded.nodes)),
                             relations=tuple(reversed(decoded.relations)), bindings=tuple(reversed(decoded.bindings)))
    assert propose(setup, reversed_graph) == result


@pytest.mark.parametrize("damage", ["extra", "unknown_relation", "dangling", "duplicate_node", "duplicate_binding",
                                    "bind_similarity", "inject", "argument", "formula"])
def test_graph_contract_rejects_ambiguity_and_executable_text(setup, damage):
    value = setup.graph.to_dict()
    if damage == "extra": value["proof_verified"] = True
    elif damage == "unknown_relation": value["relations"][0]["kind"] = "transitive_similarity"
    elif damage == "dangling": value["relations"][0]["subject"] = "unknown"
    elif damage == "duplicate_node": value["nodes"].append(value["nodes"][0])
    elif damage == "duplicate_binding": value["bindings"].append(value["bindings"][0])
    elif damage == "bind_similarity": value["relations"][0]["kind"] = "similarity"
    elif damage == "inject": value["bindings"][0]["declaration"] = "x\naxiom injected : False"
    elif damage == "argument": value["bindings"][0]["arguments"] = ["by exact sorry"]
    else: value["nodes"][0]["proposition"] = {"op": "var", "name": "p); run_elab"}
    with pytest.raises(ValueError):
        RelationGraph.from_dict(value)


@pytest.mark.parametrize("field", ["record_sha256", "environment_sha256", "corpus_snapshot_sha256"])
def test_foreign_graph_identity_fails_before_planning(setup, field):
    with pytest.raises(ValueError, match="identity"):
        propose(setup, replace(setup.graph, **{field: "f" * 64}))


@pytest.mark.parametrize("damage", ["premise", "signature", "absent", "type", "origin", "target", "alias", "wrapper"])
def test_unavailable_stale_protected_or_renamed_declarations_cannot_be_used(setup, damage):
    graph, scope, index = setup.graph, setup.scope, setup.index
    if damage in {"premise", "signature"}:
        key = "premise_sha256" if damage == "premise" else "signature_sha256"
        graph = replace(graph, bindings=(replace(graph.bindings[0], **{key: "f" * 64}), graph.bindings[1]))
    elif damage == "absent": scope = replace(scope, available_names=("Bridge.backward",))
    elif damage == "origin": scope = replace(scope, excluded_origins=("library",))
    else:
        entries = list(index.entries.values())
        n = next(i for i, p in enumerate(entries) if p.name == "Bridge.forward")
        if damage == "type": entries[n] = replace(entries[n], type_text="False")
        elif damage in {"target", "alias"}:
            entries[n] = replace(entries[n], aliases=("sample" if damage == "target" else "ProtectedAlias",))
            if damage == "alias": scope = replace(scope, excluded_names=("ProtectedAlias",))
        else:
            entries[n] = replace(entries[n], dependencies=("Bridge.wrong",))
            scope = replace(scope, excluded_names=("Bridge.wrong",))
        index = PremiseIndex(tuple(entries), environment_sha256=index.environment_sha256,
                             signatures=tuple(index.signatures.values()))
        if damage != "type":
            graph = replace(graph, bindings=(binding("forward", "Bridge.forward", index), graph.bindings[1]))
    result = propose(setup, graph, scope=scope, index=index)
    assert result["status"] == "MAPPING_REJECTED" and result["candidate"] is None


def test_mutable_inventory_state_cannot_reuse_cached_identity(setup):
    setup.index.entries["Bridge.forward"] = replace(setup.index.entries["Bridge.forward"], origin="changed")
    with pytest.raises(ValueError, match="mutated"):
        propose(setup)


def test_missing_or_excluded_evidence_abstains_without_partial_proof(setup):
    graph = replace(setup.graph, relations=(replace(setup.graph.relations[0], evidence_cids=(_cid("f" * 64),)), setup.graph.relations[1]))
    missing = propose(setup, graph)
    assert missing["status"] == "EVIDENCE_UNAVAILABLE" and missing["reason"] == "MISSING_CID"
    assert propose(setup, excluded_cids=(setup.cid,))["status"] == "EVIDENCE_EXCLUDED"
    assert propose(setup, limits=RelationLimits(max_context_bytes=128))["status"] == "EVIDENCE_UNAVAILABLE"


def test_unmapped_and_similarity_edges_are_never_assumptions(setup):
    unmapped = propose(setup, replace(setup.graph, bindings=()))
    assert unmapped["status"] == "NO_GRAPH_PLAN" and unmapped["candidate"] is None
    assert all(o["status"] == "UNMAPPED" for o in unmapped["obligations"])
    graph = replace(setup.graph, relations=tuple(replace(r, kind="similarity") for r in setup.graph.relations), bindings=())
    similar = propose(setup, graph)
    assert similar["status"] == "NO_GRAPH_PLAN" and similar["candidate"] is None
    assert all(o["status"] == "CONTEXT_ONLY" for o in similar["obligations"])


@pytest.mark.parametrize("goal,hypotheses,cycle", [("p ↔ q", "", False), ("p", " (hq : q → q)", True)])
def test_no_invented_converse_or_unseeded_cycle_fact(setup, goal, hypotheses, cycle):
    statement = "theorem sample (p q : Prop)" + hypotheses + " : " + goal
    record = {**setup.record, "statement": statement, "src": statement + " := by skip"}
    graph = replace(setup.graph, record_sha256=content_hash(record),
                    nodes=(PropositionNode("pq", parse_formula("p")), PropositionNode("qp", parse_formula("q"))))
    if not cycle:
        graph = replace(graph, relations=graph.relations[:1], bindings=graph.bindings[:1])
    result = propose(setup, graph, record=record, scope=replace(setup.scope, record_sha256=content_hash(record)))
    assert result["status"] == "NO_PLAN" and result["candidate"] is None


@pytest.mark.parametrize("split", ["unassigned", "validation", "canary", "test"])
def test_evidence_partition_stays_out_of_proposals(setup, tmp_path, split):
    root = tmp_path / split
    root.mkdir()
    artifact, rows = ingest(root, source_split=split)
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as corpus:
        graph = graph_for(setup.record, setup.index, corpus, rows[0]["entry_cid"])
        result = propose(setup, graph, corpus=corpus)
        assert result["status"] == "EVIDENCE_UNAVAILABLE" and result["reason"] == "EXCLUDED_SPLIT"
        assert result["candidate"] is None


def test_fresh_generated_names_cannot_shadow_existing_locals(setup):
    statement = "theorem sample (p q : Prop) (_g0 : p → p) : (p ∧ q) ↔ (q ∧ p)"
    record = {**setup.record, "statement": statement, "src": setup.record["src"].replace(STATEMENT, statement)}
    graph = replace(setup.graph, record_sha256=content_hash(record))
    result = propose(setup, graph, record=record, scope=replace(setup.scope, record_sha256=content_hash(record)))
    assert result["status"] == "PROPOSED"
    assert "have _g0" not in result["candidate"]


def test_unused_mappings_are_not_marked_checked(setup):
    # A third edge with the same formula is redundant. Deterministic first
    # selection keeps only the actual proof support, not all graph matches.
    extra = EvidenceRelation("zz-unused", "implies", "pq", "qp", (setup.cid,))
    graph = replace(setup.graph, relations=(*setup.graph.relations, extra),
                    bindings=(*setup.graph.bindings, binding(extra.edge_id, "Bridge.forward", setup.index)))
    result = propose(setup, graph)
    assert result["status"] == "PROPOSED"
    assert "zz-unused" not in result["used_edges"]
    assert next(o for o in result["obligations"] if o["edge_id"] == "zz-unused")["status"] == "REQUIRES_NATIVE_CHECK"


@pytest.mark.parametrize("case", ["node", "argument", "search", "size"])
def test_scope_and_resource_limits_fail_closed(setup, case):
    graph, limits = setup.graph, RelationLimits()
    if case == "node": graph = replace(graph, nodes=(replace(graph.nodes[0], proposition=parse_formula("unknown")), graph.nodes[1]))
    elif case == "argument": graph = replace(graph, bindings=(replace(graph.bindings[0], arguments=(parse_formula("unknown"),)), graph.bindings[1]))
    elif case == "search": limits = replace(limits, max_states=1)
    else: limits = replace(limits, max_candidate_bytes=128)
    result = propose(setup, graph, limits=limits)
    assert result["status"] in {"UNSUPPORTED", "SEARCH_BUDGET", "CANDIDATE_BUDGET"}
    assert result["candidate"] is None


def test_nomination_pool_and_combined_hypothesis_budget_are_explicit(setup):
    entries = (*setup.index.entries.values(), *(Premise(f"Extra.p{i}", "True", "library") for i in range(65)))
    index = PremiseIndex(tuple(entries), environment_sha256=setup.index.environment_sha256,
                         signatures=tuple(setup.index.signatures.values()))
    scope = replace(setup.scope, available_names=tuple(index.entries))
    assert propose(setup, index=index, scope=scope)["status"] == "POOL_BUDGET"
    declarations = " ".join(f"(h{i} : p → p)" for i in range(15))
    statement = "theorem sample (p q : Prop) " + declarations + " : (p ∧ q) ↔ (q ∧ p)"
    record = {**setup.record, "statement": statement, "src": statement + " := by skip"}
    result = propose(setup, replace(setup.graph, record_sha256=content_hash(record)), record=record,
                     scope=replace(setup.scope, record_sha256=content_hash(record)))
    assert result["status"] == "CONTEXT_BUDGET" and result["candidate"] is None


def test_fixture_success_never_certifies_source_or_native_proof(setup):
    evaluator, calls = fixture_evaluator(setup)
    result = evaluate(setup, propose(setup), evaluator)
    assert result["all_pins_passed"] and len(calls) == 2
    assert not result["proof_verified"] and not result["checked_edges"]
    assert not result["source_fidelity_verified"] and not result["training_enabled"] and not result["promoted"]
    assert result["official_score"] is None
    assert result["verification_calls"] == 2 and result["receipt_cache_hits"] == 0
    reused = evaluate(setup, propose(setup), evaluator)
    assert reused["verification_calls"] == 0 and reused["receipt_cache_hits"] == 2
    assert not reused["proof_verified"]


@pytest.mark.parametrize("damage", ["candidate", "receipt", "excluded", "scope", "inventory", "context"])
def test_evaluation_revalidates_all_bindings_before_any_compiler_calls(setup, damage):
    proposal = propose(setup)
    evaluator, calls = fixture_evaluator(setup)
    kwargs = {}
    if damage == "candidate": proposal["candidate"] += "\n"
    elif damage == "receipt": proposal["proof_verified"] = True
    elif damage == "excluded": kwargs["excluded_cids"] = (setup.cid,)
    elif damage == "scope": kwargs["scope"] = replace(setup.scope, excluded_names=("Bridge.forward",))
    elif damage == "context": evaluator.context = replace(evaluator.context, verifier_version="changed")
    else:
        setup.index.signatures["Bridge.forward"] = replace(setup.index.signatures["Bridge.forward"], conclusion=ExprHead("const", "False"))
    with pytest.raises(ValueError):
        evaluate(setup, proposal, evaluator, **kwargs)
    assert not calls


@pytest.mark.parametrize("options", [{"max_calls": 1}, {"outcome": Outcome.REJECTED}, {"outcome": Outcome.TIMEOUT}, {"heartbeats": None}])
def test_partial_failed_or_unmeasured_evaluations_do_not_pass(setup, options):
    evaluator, _ = fixture_evaluator(setup, **options)
    result = evaluate(setup, propose(setup), evaluator)
    assert not result["all_pins_passed"] and not result["proof_verified"] and not result["checked_edges"]


@pytest.mark.skipif(os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1", reason="explicit installed-Lean opt-in")
@pytest.mark.parametrize("case", ["contrast", "wrong_type", "chain", "iff"])
def test_native_all_pin_mapping_obligations_accept_correct_and_reject_wrong_types(tmp_path, case):
    from jevops import arena_lean as native, arena_premises as exporter
    from jevops.arena_providers import load_inventory
    from jevops.knowledge_index import KnowledgeIndex, build_index
    pins = tuple(VersionPin(tag, "graph-relations-control") for tag in ("v4.26.0", "v4.29.1"))
    statement, source = STATEMENT, SOURCE
    if case == "chain":
        statement = "theorem sample (p q r : Prop) : p → ((p ∨ q) ∨ r)"
        source = statement + " := by exact fun h => Or.inl (Or.inl h)\n"
    elif case == "iff":
        statement = "theorem sample (p q : Prop) (h : p ∧ q) : q ∧ p"
        source = statement + " := by exact And.intro h.right h.left\n"
    record = dict(name="sample", statement=statement, src=source,
                  version_info=[{p.lean_tag: p.git_commit} for p in pins])
    elan = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    bindings = {p: native.ProjectBinding(p, native.pinned_lean(elan, p.lean_tag), tmp_path,
                                        PREFIX, project_backed=False) for p in pins}
    guard = native.NativeLeanVerifier(bindings, max_processes=2)
    export = exporter.NativePremiseExporter(guard, max_processes=2, include_signatures=True).export(record,
        tuple(exporter.PremiseOrigin(n, "control", "library") for n in
              ("Bridge.forward", "Bridge.backward", "Bridge.wrong", "Bridge.left", "Bridge.equiv")))
    assert export["status"] == "INVENTORY_ONLY", export
    original, scope = load_inventory(json.loads(json.dumps(export["inventory"])), json.loads(json.dumps(export["scope"])))
    indexed = build_index(tmp_path / "premises.duckdb", original.entries.values(), signatures=original.signatures.values(),
                          environment_sha256=scope.environment_sha256, source_sha256=content_hash(export["inventory"]))
    artifact, rows = ingest(tmp_path)
    with EvidenceCorpus(Path(artifact.path), expected_sha256=artifact.file_sha256) as corpus, \
            KnowledgeIndex(Path(indexed.path), expected_sha256=indexed.file_sha256) as index:
        nominated, retrieval = index.provider_index(" ".join(original.entries), target="sample", scope=scope, top_k=8)
        assert set(nominated.entries) == set(original.entries), retrieval
        graph = graph_for(record, nominated, corpus, rows[0]["entry_cid"])
        if case == "wrong_type":
            graph = replace(graph, bindings=(binding("forward", "Bridge.wrong", nominated), graph.bindings[1]))
        elif case == "chain":
            graph = replace(graph,
                nodes=tuple(PropositionNode(n, parse_formula(f)) for n, f in (("p", "p"), ("pq", "p ∨ q"), ("pqr", "(p ∨ q) ∨ r"))),
                relations=(EvidenceRelation("first", "implies", "p", "pq", (rows[0]["entry_cid"],)),
                           EvidenceRelation("second", "implies", "pq", "pqr", (rows[0]["entry_cid"],))),
                bindings=(binding("first", "Bridge.left", nominated), binding("second", "Bridge.left", nominated, ("p ∨ q", "r"))))
        elif case == "iff":
            graph = replace(graph, relations=(EvidenceRelation("equivalence", "iff", "qp", "pq", (rows[0]["entry_cid"],)),),
                            bindings=(binding("equivalence", "Bridge.equiv", nominated, ("q", "p")),))
        proposal = propose_relations(graph, record=record, index=nominated, scope=scope, corpus=corpus)
        assert proposal["status"] == "PROPOSED", proposal
        evaluator = ArenaEvaluator(guard.context(record), guard, max_calls=2, evidence_mode="local_lean")
        result = evaluate_relations(proposal, graph, record=record, index=nominated, scope=scope, corpus=corpus, evaluator=evaluator)
        assert result["proof_verified"] is (case != "wrong_type"), result
        assert result["all_pins_passed"] is (case != "wrong_type"), result
        assert not result["source_fidelity_verified"] and not result["training_enabled"]
        assert result["official_score"] is None
        if case == "wrong_type":
            assert result["checked_edges"] == []
            assert len(result["evaluation"]["receipts"]) == len(pins)
            assert all(r["outcome"] == "REJECTED" for r in result["evaluation"]["receipts"]), result
        else:
            assert result["checked_edges"] == sorted(r.edge_id for r in graph.relations)
            assert all(o["native_checked"] for o in result["obligations"])
        # Optional retained receipt, generated from real events rather than
        # hand-written reports. A prior run's receipt is never overwritten.
        directory = os.environ.get("JEVOPS_RELATION_RECEIPTS")
        if directory:
            with (Path(directory) / f"{case}.json").open("x") as stream:
                json.dump({"record": record, "graph": graph.to_dict(), "native_inventory": export,
                           "corpus_artifact": asdict(artifact), "premise_artifact": asdict(indexed),
                           "evidence": corpus.context(tuple(sorted({cid for r in graph.relations for cid in r.evidence_cids}))),
                           "retrieval": retrieval, "result": result}, stream, ensure_ascii=False, sort_keys=True)
