"""Explicit evidence-edge -> Lean-obligation bridge, not automatic formalization.

The v1 fragment grounds graph nodes in existing local propositions and maps
implication/equivalence edges to scoped declarations with explicit proposition
arguments. Source prose and similarity never become assumptions. Only native
replay can discharge the emitted type obligations; source fidelity stays unknown.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .arena import ArenaEvaluator, Outcome, content_hash, intake_error, source_hash
from .constructive_proofs import read_proposition, search
from .logic_ir import Formula, formula_from_ir, render_formula, variables
from .premise_search import PremiseIndex, PremiseScope, bounded_int, digest_field, premise_name
from .proof_ca import canonical_json
from .skillcenter_corpus import EvidenceCorpus

SCHEMA = "jevops-evidence-relation-graph/v1"
PROPOSAL_SCHEMA = "jevops-relation-proposal/v1"


def _identifier(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}", value):
        raise ValueError("bounded graph identifier required")


def _formula(value):
    if type(value) is not Formula:
        raise ValueError("typed proposition required")
    variables(value)
    pending = [value]
    while pending:
        current = pending.pop()
        if current.op not in {"var", "true", "false", "and", "or", "imp", "iff"}:
            raise ValueError("constructive graph formula required; encode negation as implication to False")
        pending.extend(current.args)


@dataclass(frozen=True)
class PropositionNode:
    node_id: str
    proposition: Formula

    def __post_init__(self):
        _identifier(self.node_id)
        _formula(self.proposition)

    def to_dict(self):
        return {"node_id": self.node_id, "proposition": self.proposition.to_dict()}


@dataclass(frozen=True)
class EvidenceRelation:
    edge_id: str
    kind: str
    subject: str
    object: str
    evidence_cids: tuple[str, ...]

    def __post_init__(self):
        for value in (self.edge_id, self.subject, self.object):
            _identifier(value)
        if type(self.kind) is not str or self.kind not in {"implies", "iff", "similarity"}:
            raise ValueError("unsupported relation kind")
        if (type(self.evidence_cids) is not tuple or not 1 <= len(self.evidence_cids) <= 8
                or any(type(v) is not str or not re.fullmatch(r"b[a-z2-7]{58}", v) for v in self.evidence_cids)
                or len(set(self.evidence_cids)) != len(self.evidence_cids)):
            raise ValueError("bounded unique evidence CIDs required")


@dataclass(frozen=True)
class DeclarationBinding:
    edge_id: str
    declaration: str
    premise_sha256: str
    signature_sha256: str
    arguments: tuple[Formula, ...] = ()

    def __post_init__(self):
        _identifier(self.edge_id)
        premise_name(self.declaration)
        digest_field(self.premise_sha256)
        digest_field(self.signature_sha256)
        if type(self.arguments) is not tuple or len(self.arguments) > 8:
            raise ValueError("bounded immutable proposition arguments required")
        for argument in self.arguments:
            _formula(argument)

    def to_dict(self):
        return {**{k: getattr(self, k) for k in ("edge_id", "declaration", "premise_sha256", "signature_sha256")},
                "arguments": [a.to_dict() for a in self.arguments]}


@dataclass(frozen=True)
class RelationGraph:
    record_sha256: str
    environment_sha256: str
    corpus_snapshot_sha256: str
    extraction_sha256: str
    nodes: tuple[PropositionNode, ...]
    relations: tuple[EvidenceRelation, ...]
    bindings: tuple[DeclarationBinding, ...]

    def __post_init__(self):
        for value in (self.record_sha256, self.environment_sha256, self.corpus_snapshot_sha256, self.extraction_sha256):
            digest_field(value)
        for values, cls, bound, key in ((self.nodes, PropositionNode, 32, "node_id"),
                (self.relations, EvidenceRelation, 32, "edge_id"), (self.bindings, DeclarationBinding, 16, "edge_id")):
            if (type(values) is not tuple or len(values) > bound or any(type(v) is not cls for v in values)
                    or len({getattr(v, key) for v in values}) != len(values)):
                raise ValueError("bounded unique typed graph records required")
        nodes = {n.node_id for n in self.nodes}
        edges = {r.edge_id: r for r in self.relations}
        if any(r.subject not in nodes or r.object not in nodes for r in self.relations):
            raise ValueError("unresolved graph endpoint")
        if any(b.edge_id not in edges or edges[b.edge_id].kind == "similarity" for b in self.bindings):
            raise ValueError("only logical edges may have declaration bindings")
        if len({cid for r in self.relations for cid in r.evidence_cids}) > 32:
            raise ValueError("graph evidence budget")
        if len(canonical_json(self.to_dict()).encode()) > 65536:
            raise ValueError("graph byte budget")

    def to_dict(self):
        return {"schema": SCHEMA,
            **{k: getattr(self, k) for k in ("record_sha256", "environment_sha256", "corpus_snapshot_sha256", "extraction_sha256")},
            "nodes": [n.to_dict() for n in sorted(self.nodes, key=lambda n: n.node_id)],
            "relations": [{**asdict(r), "evidence_cids": sorted(r.evidence_cids)}
                          for r in sorted(self.relations, key=lambda r: r.edge_id)],
            "bindings": [b.to_dict() for b in sorted(self.bindings, key=lambda b: b.edge_id)]}

    @property
    def graph_sha256(self):
        return content_hash(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        def fields(row, keys):
            if type(row) is not dict or set(row) != set(keys.split()):
                raise ValueError("strict relation graph fields required")
            return row
        fields(value, "schema record_sha256 environment_sha256 corpus_snapshot_sha256 extraction_sha256 nodes relations bindings")
        if value["schema"] != SCHEMA:
            raise ValueError("unsupported graph schema")
        for key, bound in (("nodes", 32), ("relations", 32), ("bindings", 16)):
            if type(value[key]) is not list or len(value[key]) > bound:
                raise ValueError("bounded graph lists required")
        nodes, relations, bindings = [], [], []
        for n in value["nodes"]:
            fields(n, "node_id proposition")
            nodes.append(PropositionNode(n["node_id"], formula_from_ir(n["proposition"])))
        for r in value["relations"]:
            fields(r, "edge_id kind subject object evidence_cids")
            if type(r["evidence_cids"]) is not list or len(r["evidence_cids"]) > 8:
                raise ValueError("bounded evidence list required")
            relations.append(EvidenceRelation(**{**r, "evidence_cids": tuple(r["evidence_cids"])}))
        for b in value["bindings"]:
            fields(b, "edge_id declaration premise_sha256 signature_sha256 arguments")
            if type(b["arguments"]) is not list or len(b["arguments"]) > 8:
                raise ValueError("bounded argument list required")
            bindings.append(DeclarationBinding(**{**b, "arguments": tuple(formula_from_ir(a) for a in b["arguments"])}))
        return cls(**{k: value[k] for k in ("record_sha256", "environment_sha256", "corpus_snapshot_sha256", "extraction_sha256")},
                   nodes=tuple(nodes), relations=tuple(relations), bindings=tuple(bindings))


@dataclass(frozen=True)
class RelationLimits:
    max_states: int = 256
    max_depth: int = 8
    max_facts: int = 64
    max_context_bytes: int = 32768
    max_candidate_bytes: int = 32768

    def __post_init__(self):
        bounded_int(self.max_states, 1, 4096)
        bounded_int(self.max_depth, 1, 20)
        bounded_int(self.max_facts, 1, 256)
        bounded_int(self.max_context_bytes, 128, 1048576)
        bounded_int(self.max_candidate_bytes, 128, 65536)


def propose_relations(graph: RelationGraph, *, record: dict, index: PremiseIndex, scope: PremiseScope,
                      corpus: EvidenceCorpus, excluded_cids: tuple[str, ...] = (),
                      limits: RelationLimits = RelationLimits(), include_term_ir: bool = False) -> dict:
    """Resolve identities and construct a proposal; no compiler/model/training calls.

    Inventories, scope, corpus handles and partition exclusions are trusted
    infrastructure inputs. Graph extraction/mappings are untrusted proposals.
    Every rendered declaration use has an explicit type obligation in Lean.
    """
    if (type(include_term_ir) is not bool or type(graph) is not RelationGraph or type(index) is not PremiseIndex or type(scope) is not PremiseScope
            or type(corpus) is not EvidenceCorpus or type(limits) is not RelationLimits or type(record) is not dict):
        raise ValueError("explicit typed graph, inventory, corpus, scope and limits required")
    if (scope.record_sha256 != content_hash(record) or graph.record_sha256 != scope.record_sha256
            or graph.environment_sha256 != scope.environment_sha256 or graph.environment_sha256 != index.environment_sha256
            or graph.corpus_snapshot_sha256 != corpus.identity["snapshot_sha256"]):
        raise ValueError("graph record/environment/corpus identity mismatch")
    target, source, statement = record["name"], record["src"], record["statement"]
    premise_name(target)
    if any(type(v) is not str for v in (source, statement)) or intake_error(source, statement):
        raise ValueError("invalid unchanged source/statement")
    # Rebuild the bounded nomination index to catch mutated entries/signatures,
    # and to avoid relying on mutable cached postings/owners for admission.
    current = PremiseIndex(tuple(index.entries.values()), environment_sha256=index.environment_sha256,
                           signatures=tuple(index.signatures.values()))
    if current.index_sha256 != index.index_sha256:
        raise ValueError("premise inventory mutated")
    pool = current.scoped_pool(target=target, scope=scope, max_pool=64)
    evidence_cids = tuple(sorted({cid for r in graph.relations for cid in r.evidence_cids}))
    evidence = corpus.context(evidence_cids, excluded_cids=excluded_cids, max_context_bytes=limits.max_context_bytes)
    request = {"schema": PROPOSAL_SCHEMA, "graph_sha256": graph.graph_sha256,
        "record_sha256": content_hash(record), "source_sha256": source_hash(source),
        "environment_sha256": graph.environment_sha256, "inventory_sha256": current.index_sha256,
        "scope_sha256": content_hash(asdict(scope)), "evidence_request_sha256": evidence["request_sha256"],
        "limits": asdict(limits)}
    if include_term_ir:
        request.update(schema="jevops-relation-proposal/v2", term_ir_requested=True)
    report = {**request, "request_sha256": content_hash(request), "status": "NO_PLAN", "candidate": None,
              "obligations": [], "used_edges": [], "search_states": 0,
              "authority": "proposal_only", "proof_verified": False, "source_fidelity_verified": False,
              "training_enabled": False, "promoted": False, "official_score": None, "minimality_proven": False}

    def finish(status, reason=""):
        report.update(status=status, reason=reason)
        return {**report, "proposal_sha256": content_hash(report)}

    if pool["status"] != "READY":
        return finish("POOL_BUDGET")
    if evidence["status"] != "CONTEXT":
        return finish("EVIDENCE_UNAVAILABLE", evidence["status"])
    if {r["entry_cid"] for r in evidence["records"]} != set(evidence_cids):
        return finish("EVIDENCE_EXCLUDED")
    try:
        _, goal, assumptions = read_proposition(source)
    except ValueError as exc:
        return finish("UNSUPPORTED", str(exc))
    # Conservative v1: only proposition atoms actually present in the goal or
    # local hypothesis types. Unused/implicit/dependent binders are not inferred.
    atoms = set(variables(goal, *(f for _, f in assumptions)))
    if any(not set(variables(n.proposition)) <= atoms for n in graph.nodes):
        return finish("UNSUPPORTED", "graph node outside existing proposition context")
    allowed = {r["name"] for r in pool["entries"]}
    nodes = {n.node_id: n.proposition for n in graph.nodes}
    bindings = {b.edge_id: b for b in graph.bindings}
    reserved = set(re.findall(r"[^\W\d][\w']*", source))
    declarations, seeds = {}, list(assumptions)
    for relation in sorted(graph.relations, key=lambda r: r.edge_id):
        obligation = {"edge_id": relation.edge_id, "evidence_cids": sorted(relation.evidence_cids),
                      "status": "CONTEXT_ONLY" if relation.kind == "similarity" else "UNMAPPED",
                      "native_checked": False}
        report["obligations"].append(obligation)
        if relation.kind == "similarity":
            continue
        formula = Formula("imp" if relation.kind == "implies" else "iff",
                          (nodes[relation.subject], nodes[relation.object]))
        obligation["expected_type"] = render_formula(formula)
        binding = bindings.get(relation.edge_id)
        if binding is None:
            continue
        if binding.declaration not in allowed:
            return finish("MAPPING_REJECTED", "declaration excluded or unavailable")
        premise, signature = current.entries[binding.declaration], current.signatures.get(binding.declaration)
        if (content_hash(asdict(premise)) != binding.premise_sha256 or signature is None
                or content_hash(signature.to_dict()) != binding.signature_sha256):
            return finish("MAPPING_REJECTED", "declaration/signature identity mismatch")
        if (len(binding.arguments) > len(signature.binder_kinds)
                or any(h.kind != "sort" for h in signature.binder_heads[:len(binding.arguments)])
                or any(not set(variables(a)) <= atoms for a in binding.arguments)):
            return finish("UNSUPPORTED", "only explicit proposition instantiations are supported")
        serial = len(declarations)
        while f"_g{serial}" in reserved:
            serial += 1
        name = f"_g{serial}"
        reserved.add(name)
        term = f"@_root_.{binding.declaration}" + "".join(f" ({render_formula(a)})" for a in binding.arguments)
        # The ascription/have is a real Lean type obligation, not a text match.
        declarations[name] = (relation.edge_id, f"  have {name} : {render_formula(formula)} := {term}\n")
        seeds.append((name, formula))
        obligation.update(status="REQUIRES_NATIVE_CHECK", declaration=binding.declaration,
                          premise_sha256=binding.premise_sha256, signature_sha256=binding.signature_sha256,
                          arguments=[a.to_dict() for a in binding.arguments])
    if len(seeds) > 16:
        return finish("CONTEXT_BUDGET", "at most 16 local hypotheses plus mapped edges")
    result = search(goal, seeds, max_states=limits.max_states, max_depth=limits.max_depth,
                    max_facts=limits.max_facts, include_term_ir=include_term_ir)
    report["search_states"] = result["states"]
    if result["budget_exhausted"]:
        return finish("SEARCH_BUDGET")
    if result["term"] is None:
        return finish("NO_PLAN")
    used = sorted(set(result["support"]) & set(declarations))
    if not used:
        return finish("NO_GRAPH_PLAN", "local proof did not use any mapped relationship")
    candidate = statement + " := by\n" + "".join(declarations[n][1] for n in used) + "  exact " + result["term"] + "\n"
    if len(candidate.encode()) > limits.max_candidate_bytes:
        return finish("CANDIDATE_BUDGET")
    if intake_error(candidate, statement):
        return finish("UNSUPPORTED", "rendered proof failed intake")
    report.update(candidate=candidate, used_edges=sorted(declarations[n][0] for n in used))
    if include_term_ir:
        report.update(term_ir=result["term_ir"], mapped_locals={n: declarations[n][0] for n in used})
    return finish("PROPOSED")


def evaluate_relations(proposal: dict, graph: RelationGraph, *, record: dict, index: PremiseIndex,
                       scope: PremiseScope, corpus: EvidenceCorpus, evaluator: ArenaEvaluator,
                       excluded_cids: tuple[str, ...] = ()) -> dict:
    """Re-resolve the exact graph/scope before the existing all-pin proof gate.

    Only used mappings are checked by the emitted proof. Native success does
    not certify extraction fidelity, unused bindings, compression or promotion.
    """
    if type(proposal) is not dict or type(evaluator) is not ArenaEvaluator:
        raise ValueError("explicit proposal and ArenaEvaluator required")
    ctx = evaluator.context
    if (graph.environment_sha256 != ctx.context_id or record.get("name") != ctx.problem
            or record.get("src") != ctx.reference_source or record.get("statement") != ctx.statement):
        raise ValueError("evaluator context mismatch")
    limits = RelationLimits(**proposal["limits"])
    fresh = propose_relations(graph, record=record, index=index, scope=scope, corpus=corpus,
                               excluded_cids=excluded_cids, limits=limits,
                               include_term_ir=proposal.get("term_ir_requested", False))
    if fresh["status"] != "PROPOSED" or fresh != proposal:
        raise ValueError("stale, changed, excluded or non-proposed relation plan")
    before_calls, before_hits = evaluator.calls, evaluator.cache_hits
    evaluation = evaluator.evaluate(fresh["candidate"])
    passed = (evaluation.status == "MEASURED" and len(evaluation.receipts) == len(ctx.versions)
              and all(r.outcome == Outcome.VERIFIED for r in evaluation.receipts))
    native = passed and evaluation.evidence_mode == "local_lean"
    return {"schema": "jevops-relation-evaluation/v1", "proposal": fresh,
            "evaluation": evaluation.to_dict(), "all_pins_passed": passed, "proof_verified": native,
            "checked_edges": fresh["used_edges"] if native else [], "source_fidelity_verified": False,
            "training_enabled": False, "promoted": False, "official_score": None,
            "verification_calls": evaluator.calls - before_calls,
            "receipt_cache_hits": evaluator.cache_hits - before_hits,
            "obligations": [{**o, "native_checked": native and o["edge_id"] in fresh["used_edges"],
                             "status": "CHECKED_IN_CANDIDATE" if native and o["edge_id"] in fresh["used_edges"] else o["status"]}
                            for o in fresh["obligations"]]}
