#!/usr/bin/env python3
"""Proof-carrying neurosymbolic graph cellular automaton.

This module is deliberately smaller and stricter than the legacy energy NCA in
``jevops.nca``.  It provides a finite, ground, positive-Horn reasoning core:

* cells carry separate symbolic, policy, evidence, and runtime state;
* typed dependency edges are indexed in both directions;
* policy output proposes an action, but ``checked_apply`` is the only route
  that can admit a symbolic fact;
* accepted facts are monotone inside one immutable verification context;
* fact notifications are delivered through an idempotent local message queue;
* periodic FIFO service prevents a policy from permanently suppressing an
  enabled rule;
* checkpoints and evidence are JSON-serializable and replay-safe.

The language is intentionally ground-only.  It has no eval, variables,
negation-as-failure, fresh symbols, rule mutation, or retraction.  External
verifiers are injected adapters for obligations the local rule engine cannot
discharge.  A model response, activation value, cache hit, test result, or
legacy ``theorem_ok`` field is never authoritative by itself.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import random
import re
import time
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable


SCHEMA = "jevops-proof-ca/v1"
MAX_PROPOSAL_BYTES = 16_384
MAX_MESSAGE_BYTES = 16_384
MAX_RETRIEVALS_PER_PROPOSAL = 1


class ProofCAError(ValueError):
    """Base class for validation and runtime errors in the proof CA."""


class ValidationError(ProofCAError):
    """Raised when a declared symbolic object is malformed."""


class PolicyOutputError(ProofCAError):
    """Raised when a policy returns an invalid or unauthorized proposal."""


class ContextMismatch(ProofCAError):
    """Raised when evidence or a proposal belongs to another context."""


class CellType(str, Enum):
    FACT = "fact"
    RULE = "rule"
    TARGET = "target"
    VERIFIER = "verifier"
    POLICY = "policy"
    BUDGET = "budget"


class EdgeType(str, Enum):
    PREMISE = "premise"
    CONCLUSION = "conclusion"
    DEPENDENCY = "dependency"
    VERIFIER = "verifier"


class EvidenceKind(str, Enum):
    TRUSTED_ASSUMPTION = "trusted_assumption"
    RULE_DERIVATION = "checked_rule_derivation"
    EXTERNAL_VERIFICATION = "external_verification"
    COUNTEREXAMPLE = "counterexample"
    TEST_OBSERVATION = "test_observation"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class EvidenceStatus(str, Enum):
    ASSUMED = "assumed"
    VERIFIED = "verified"
    COUNTEREXAMPLE = "counterexample"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"
    TRANSIENT_FAILURE = "transient_failure"


class ActionType(str, Enum):
    ATTEMPT_RULE = "attempt_rule"
    REQUEST_DEPENDENCY = "request_dependency"
    REQUEST_EXTERNAL_VERIFICATION = "request_external_verification"
    UPDATE_POLICY = "update_policy"
    DEFER = "defer"


class RunStatus(str, Enum):
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"
    QUIESCENT_INCOMPLETE = "QUIESCENT_INCOMPLETE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    COUNTEREXAMPLE = "counterexample"
    INCONCLUSIVE = "inconclusive"
    TRANSIENT_FAILURE = "transient_failure"
    ERROR = "error"


_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_GROUND = re.compile(r"^[A-Za-z0-9_./:-]+$")


def _strict_value(value: Any) -> Any:
    """Return a canonicalizable JSON value or reject it.

    ``default=str`` is intentionally not used: silently stringifying an
    object would make context identities and evidence hashes ambiguous.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("non_finite_number")
        return value
    if isinstance(value, Enum):
        return _strict_value(value.value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("mapping_keys_must_be_strings")
            out[key] = _strict_value(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_strict_value(item) for item in value]
    raise ValidationError(f"unsupported_serialization_type:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Canonical, version-independent JSON serialization for identities."""

    return json.dumps(
        _strict_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_digest(value: Any) -> str:
    """Return a SHA-256 content digest, not a CID."""

    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _pairs(value: Optional[Mapping[str, Any]]) -> tuple[tuple[str, Any], ...]:
    data = dict(value or {})
    _strict_value(data)
    return tuple((key, data[key]) for key in sorted(data))


def _mapping(value: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    return {str(key): _strict_value(item) for key, item in value}


def _finite_unit(value: Any, *, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name}_must_be_numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValidationError(f"{field_name}_out_of_range")
    return number


@dataclass(frozen=True, order=True)
class Atom:
    """A ground atom with a predicate and explicit argument tuple."""

    predicate: str
    args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        predicate = str(self.predicate or "")
        if not _IDENT.fullmatch(predicate):
            raise ValidationError("invalid_predicate")
        args = tuple(str(arg) for arg in self.args)
        if any(not _GROUND.fullmatch(arg) for arg in args):
            raise ValidationError("invalid_ground_argument")
        object.__setattr__(self, "predicate", predicate)
        object.__setattr__(self, "args", args)

    @property
    def key(self) -> str:
        if not self.args:
            return self.predicate
        return f"{self.predicate}({','.join(self.args)})"

    def to_dict(self) -> dict[str, Any]:
        return {"predicate": self.predicate, "args": list(self.args), "key": self.key}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Atom":
        return cls(str(data.get("predicate") or ""), tuple(str(x) for x in data.get("args") or ()))


@dataclass(frozen=True)
class PredicateSignature:
    name: str
    arity: int

    def __post_init__(self) -> None:
        if not _IDENT.fullmatch(str(self.name or "")):
            raise ValidationError("invalid_predicate_signature")
        if int(self.arity) < 0:
            raise ValidationError("negative_predicate_arity")
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "arity", int(self.arity))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arity": self.arity}


@dataclass(frozen=True)
class Rule:
    """A fixed, ground, positive Horn rule."""

    rule_id: str
    premises: tuple[Atom, ...]
    conclusion: Atom

    def __post_init__(self) -> None:
        rid = str(self.rule_id or "")
        if not _GROUND.fullmatch(rid):
            raise ValidationError("invalid_rule_id")
        premises = tuple(self.premises)
        if any(not isinstance(atom, Atom) for atom in premises):
            raise ValidationError("rule_premises_must_be_atoms")
        if len({atom.key for atom in premises}) != len(premises):
            raise ValidationError("duplicate_rule_premise")
        if not isinstance(self.conclusion, Atom):
            raise ValidationError("rule_conclusion_must_be_atom")
        object.__setattr__(self, "rule_id", rid)
        object.__setattr__(self, "premises", premises)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "premises": [atom.to_dict() for atom in self.premises],
            "conclusion": self.conclusion.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rule":
        return cls(
            str(data.get("rule_id") or ""),
            tuple(Atom.from_dict(row) for row in data.get("premises") or ()),
            Atom.from_dict(dict(data.get("conclusion") or {})),
        )


@dataclass(frozen=True)
class ContextIdentity:
    """Immutable logical and external verification context."""

    facts_revision: str
    rules_revision: str
    target: str = ""
    candidate_artifact: str = ""
    source_dependencies: tuple[str, ...] = ()
    verifier_id: str = ""
    verifier_version: str = ""
    verifier_options: tuple[tuple[str, Any], ...] = ()
    axiom_policy: str = ""
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        for name in ("facts_revision", "rules_revision", "schema"):
            value = str(getattr(self, name) or "")
            if not value:
                raise ValidationError(f"empty_context_{name}")
            object.__setattr__(self, name, value)
        for name in (
            "target",
            "candidate_artifact",
            "verifier_id",
            "verifier_version",
            "axiom_policy",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or ""))
        deps = tuple(sorted({str(item) for item in self.source_dependencies if str(item)}))
        object.__setattr__(self, "source_dependencies", deps)
        if isinstance(self.verifier_options, Mapping):
            opts = _pairs(self.verifier_options)
        else:
            opts = _pairs({str(key): value for key, value in self.verifier_options}) if self.verifier_options else ()
        object.__setattr__(self, "verifier_options", opts)

    @classmethod
    def create(
        cls,
        *,
        facts_revision: str,
        rules_revision: str,
        target: str = "",
        candidate_artifact: str = "",
        source_dependencies: Sequence[str] = (),
        verifier_id: str = "",
        verifier_version: str = "",
        verifier_options: Optional[Mapping[str, Any]] = None,
        axiom_policy: str = "",
    ) -> "ContextIdentity":
        return cls(
            facts_revision=str(facts_revision),
            rules_revision=str(rules_revision),
            target=str(target),
            candidate_artifact=str(candidate_artifact),
            source_dependencies=tuple(str(item) for item in source_dependencies),
            verifier_id=str(verifier_id),
            verifier_version=str(verifier_version),
            verifier_options=_pairs(verifier_options),
            axiom_policy=str(axiom_policy),
        )

    @property
    def context_id(self) -> str:
        return sha256_digest(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        row: dict[str, Any] = {
            "schema": self.schema,
            "facts_revision": self.facts_revision,
            "rules_revision": self.rules_revision,
            "target": self.target,
            "candidate_artifact": self.candidate_artifact,
            "source_dependencies": list(self.source_dependencies),
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verifier_options": _mapping(self.verifier_options),
            "axiom_policy": self.axiom_policy,
        }
        if include_id:
            row["context_id"] = self.context_id
        return row

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContextIdentity":
        context = cls.create(
            facts_revision=str(data.get("facts_revision") or ""),
            rules_revision=str(data.get("rules_revision") or ""),
            target=str(data.get("target") or ""),
            candidate_artifact=str(data.get("candidate_artifact") or ""),
            source_dependencies=tuple(str(x) for x in data.get("source_dependencies") or ()),
            verifier_id=str(data.get("verifier_id") or ""),
            verifier_version=str(data.get("verifier_version") or ""),
            verifier_options=dict(data.get("verifier_options") or {}),
            axiom_policy=str(data.get("axiom_policy") or ""),
        )
        stored = str(data.get("context_id") or "")
        if stored and stored != context.context_id:
            raise ContextMismatch("context_digest_mismatch")
        return context


@dataclass(frozen=True)
class Evidence:
    """A typed evidence record; only selected kinds are authoritative."""

    evidence_id: str
    kind: EvidenceKind
    status: EvidenceStatus
    subject: Atom
    context_id: str
    rule_id: str = ""
    premise_atoms: tuple[str, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    source: str = ""
    details: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.evidence_id or ""):
            raise ValidationError("empty_evidence_id")
        if not str(self.context_id or ""):
            raise ValidationError("empty_evidence_context")
        object.__setattr__(self, "kind", EvidenceKind(self.kind))
        object.__setattr__(self, "status", EvidenceStatus(self.status))
        object.__setattr__(self, "premise_atoms", tuple(str(x) for x in self.premise_atoms))
        object.__setattr__(self, "supporting_evidence", tuple(str(x) for x in self.supporting_evidence))
        if isinstance(self.details, Mapping):
            detail_pairs = _pairs(self.details)
        else:
            detail_pairs = _pairs({str(key): value for key, value in self.details}) if self.details else ()
        object.__setattr__(self, "details", detail_pairs)

    @classmethod
    def make(
        cls,
        *,
        kind: EvidenceKind,
        status: EvidenceStatus,
        subject: Atom,
        context_id: str,
        rule_id: str = "",
        premise_atoms: Sequence[str] = (),
        supporting_evidence: Sequence[str] = (),
        source: str = "",
        details: Optional[Mapping[str, Any]] = None,
    ) -> "Evidence":
        body = {
            "schema": SCHEMA,
            "kind": EvidenceKind(kind).value,
            "status": EvidenceStatus(status).value,
            "subject": subject.to_dict(),
            "context_id": str(context_id),
            "rule_id": str(rule_id),
            "premise_atoms": [str(x) for x in premise_atoms],
            "supporting_evidence": [str(x) for x in supporting_evidence],
            "source": str(source),
            "details": dict(details or {}),
        }
        return cls(
            evidence_id=sha256_digest(body),
            kind=EvidenceKind(kind),
            status=EvidenceStatus(status),
            subject=subject,
            context_id=str(context_id),
            rule_id=str(rule_id),
            premise_atoms=tuple(str(x) for x in premise_atoms),
            supporting_evidence=tuple(str(x) for x in supporting_evidence),
            source=str(source),
            details=_pairs(details),
        )

    @property
    def authoritative(self) -> bool:
        return (
            (self.kind == EvidenceKind.TRUSTED_ASSUMPTION and self.status == EvidenceStatus.ASSUMED)
            or (self.kind in {EvidenceKind.RULE_DERIVATION, EvidenceKind.EXTERNAL_VERIFICATION} and self.status == EvidenceStatus.VERIFIED)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "subject": self.subject.to_dict(),
            "context_id": self.context_id,
            "rule_id": self.rule_id,
            "premise_atoms": list(self.premise_atoms),
            "supporting_evidence": list(self.supporting_evidence),
            "source": self.source,
            "details": _mapping(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Evidence":
        row = cls(
            evidence_id=str(data.get("evidence_id") or ""),
            kind=EvidenceKind(str(data.get("kind") or "")),
            status=EvidenceStatus(str(data.get("status") or "")),
            subject=Atom.from_dict(dict(data.get("subject") or {})),
            context_id=str(data.get("context_id") or ""),
            rule_id=str(data.get("rule_id") or ""),
            premise_atoms=tuple(str(x) for x in data.get("premise_atoms") or ()),
            supporting_evidence=tuple(str(x) for x in data.get("supporting_evidence") or ()),
            source=str(data.get("source") or ""),
            details=_pairs(dict(data.get("details") or {})),
        )
        expected = Evidence.make(
            kind=row.kind,
            status=row.status,
            subject=row.subject,
            context_id=row.context_id,
            rule_id=row.rule_id,
            premise_atoms=row.premise_atoms,
            supporting_evidence=row.supporting_evidence,
            source=row.source,
            details=_mapping(row.details),
        )
        if expected.evidence_id != row.evidence_id:
            raise ValidationError("evidence_digest_mismatch")
        return row


@dataclass(frozen=True)
class SymbolicState:
    """Authoritative symbolic fields kept apart from policy and runtime data.

    ``obligation`` and ``target_identity`` are explicit so a target cell is
    not represented only by an overloaded Boolean.  For a target fact they
    contain stable, serializable identities; non-target and rule cells leave
    them empty.
    """

    atom: Optional[Atom] = None
    rule_id: str = ""
    conclusion: Optional[Atom] = None
    target: bool = False
    dependencies: tuple[str, ...] = ()
    accepted_derivations: tuple[str, ...] = ()
    obligation: str = ""
    target_identity: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom": self.atom.to_dict() if self.atom else None,
            "rule_id": self.rule_id,
            "conclusion": self.conclusion.to_dict() if self.conclusion else None,
            "target": self.target,
            "dependencies": list(self.dependencies),
            "accepted_derivations": list(self.accepted_derivations),
            "obligation": self.obligation,
            "target_identity": self.target_identity,
        }


@dataclass(frozen=True)
class PolicyState:
    activation: float = 0.5
    latent_features: tuple[float, ...] = ()
    uncertainty: float = 0.0
    observations: int = 0
    last_answer: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "activation", _finite_unit(self.activation, field_name="activation"))
        object.__setattr__(self, "uncertainty", _finite_unit(self.uncertainty, field_name="uncertainty"))
        features = tuple(float(x) for x in self.latent_features)
        if any(not math.isfinite(x) for x in features):
            raise ValidationError("latent_feature_not_finite")
        object.__setattr__(self, "latent_features", features)
        if int(self.observations) < 0:
            raise ValidationError("negative_policy_observations")
        object.__setattr__(self, "observations", int(self.observations))
        if self.last_answer is not None:
            _strict_value(self.last_answer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activation": self.activation,
            "latent_features": list(self.latent_features),
            "uncertainty": self.uncertainty,
            "observations": self.observations,
            "last_answer": self.last_answer,
        }


@dataclass(frozen=True)
class EvidenceState:
    references: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"references": list(self.references)}


@dataclass(frozen=True)
class RuntimeState:
    version: int = 0
    execution_status: str = "idle"
    pending_messages: int = 0
    resource_ref: str = "operations"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "execution_status": self.execution_status,
            "pending_messages": self.pending_messages,
            "resource_ref": self.resource_ref,
        }


@dataclass(frozen=True)
class Cell:
    cell_id: str
    cell_type: CellType
    symbolic: SymbolicState = field(default_factory=SymbolicState)
    policy: PolicyState = field(default_factory=PolicyState)
    evidence: EvidenceState = field(default_factory=EvidenceState)
    runtime: RuntimeState = field(default_factory=RuntimeState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "cell_type": self.cell_type.value,
            "symbolic": self.symbolic.to_dict(),
            "policy": self.policy.to_dict(),
            "evidence": self.evidence.to_dict(),
            "runtime": self.runtime.to_dict(),
        }


@dataclass(frozen=True)
class DependencyEdge:
    edge_id: str
    source: str
    target: str
    edge_type: EdgeType
    rule_id: str = ""
    premise_index: Optional[int] = None

    @classmethod
    def make(
        cls,
        source: str,
        target: str,
        edge_type: EdgeType,
        *,
        rule_id: str = "",
        premise_index: Optional[int] = None,
    ) -> "DependencyEdge":
        body = {
            "schema": SCHEMA,
            "source": source,
            "target": target,
            "edge_type": EdgeType(edge_type).value,
            "rule_id": rule_id,
            "premise_index": premise_index,
        }
        return cls(sha256_digest(body), str(source), str(target), EdgeType(edge_type), str(rule_id), premise_index)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type.value,
            "rule_id": self.rule_id,
            "premise_index": self.premise_index,
        }


@dataclass(frozen=True)
class RuleObservation:
    rule_id: str
    premise_atoms: tuple[str, ...]
    conclusion: str
    premise_evidence: tuple[str, ...]
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "premise_atoms": list(self.premise_atoms),
            "conclusion": self.conclusion,
            "premise_evidence": list(self.premise_evidence),
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class NeighborObservation:
    cell_id: str
    cell_type: str
    edge_type: str
    atom: str = ""
    accepted: bool = False
    activation: float = 0.0
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "cell_type": self.cell_type,
            "edge_type": self.edge_type,
            "atom": self.atom,
            "accepted": self.accepted,
            "activation": self.activation,
            "version": self.version,
        }


@dataclass(frozen=True)
class LocalSnapshot:
    """Bounded policy view; complete mandatory premises are never truncated."""

    context_id: str
    cell_id: str
    cell_type: str
    atom: str
    rule_id: str
    step: int
    mandatory_dependencies: tuple[str, ...]
    enabled_rules: tuple[RuleObservation, ...]
    neighbor_summaries: tuple[NeighborObservation, ...]
    full_neighbor_count: int
    feature_map: tuple[tuple[str, Any], ...]
    allowed_actions: tuple[str, ...]
    dependency_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "context_id": self.context_id,
            "cell_id": self.cell_id,
            "cell_type": self.cell_type,
            "atom": self.atom,
            "rule_id": self.rule_id,
            "step": self.step,
            "mandatory_dependencies": list(self.mandatory_dependencies),
            "enabled_rules": [row.to_dict() for row in self.enabled_rules],
            "neighbor_summaries": [row.to_dict() for row in self.neighbor_summaries],
            "full_neighbor_count": self.full_neighbor_count,
            "feature_map": _mapping(self.feature_map),
            "allowed_actions": list(self.allowed_actions),
            "dependency_fingerprint": self.dependency_fingerprint,
        }


@dataclass(frozen=True)
class PolicyAnswer:
    """Rich Jev answer metadata, kept observational rather than authoritative."""

    selected: str
    probabilities: tuple[tuple[str, float], ...] = ()
    confidence: Optional[float] = None
    question_version: str = ""
    model_id: str = ""
    fixture: bool = False
    raw: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        selected = str(self.selected or "")
        if not selected:
            raise PolicyOutputError("missing_policy_selection")
        object.__setattr__(self, "selected", selected)
        raw_probabilities = self.probabilities.items() if isinstance(self.probabilities, Mapping) else (self.probabilities or ())
        probs = []
        for key, value in raw_probabilities:
            probs.append((str(key), _finite_unit(value, field_name="probability")))
        if sum(value for _, value in probs) > 1.000001:
            raise PolicyOutputError("probabilities_sum_over_one")
        object.__setattr__(self, "probabilities", tuple(probs))
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _finite_unit(self.confidence, field_name="confidence"))
        object.__setattr__(self, "question_version", str(self.question_version or ""))
        object.__setattr__(self, "model_id", str(self.model_id or ""))
        if isinstance(self.raw, Mapping):
            raw_pairs = _pairs(self.raw)
        else:
            raw_pairs = _pairs({str(key): value for key, value in self.raw}) if self.raw else ()
        object.__setattr__(self, "raw", raw_pairs)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, allowed: Sequence[str]) -> "PolicyAnswer":
        data = dict(raw)
        selected = data.get("selected", data.get("choice", data.get("action")))
        if not isinstance(selected, str) or selected not in set(allowed):
            raise PolicyOutputError("choice_outside_allowed_action_set")
        probabilities = data.get("probabilities", data.get("distribution", {}))
        if probabilities is None:
            probabilities = {}
        if not isinstance(probabilities, Mapping):
            raise PolicyOutputError("probabilities_must_be_mapping")
        if any(str(key) not in set(allowed) for key in probabilities):
            raise PolicyOutputError("probability_choice_outside_allowed_action_set")
        raw_safe = _strict_value(data)
        return cls(
            selected=selected,
            probabilities=tuple((str(key), float(value)) for key, value in probabilities.items()),
            confidence=data.get("confidence"),
            question_version=str(data.get("question_version") or ""),
            model_id=str(data.get("model_id") or ""),
            fixture=bool(data.get("fixture", False)),
            raw=_pairs(raw_safe),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
            "question_version": self.question_version,
            "model_id": self.model_id,
            "fixture": self.fixture,
            "raw": _mapping(self.raw),
        }


@dataclass(frozen=True)
class ActionProposal:
    """A bounded local request which still requires checker authorization."""

    proposal_id: str
    context_id: str
    target_cell: str
    action: ActionType
    payload: tuple[tuple[str, Any], ...]
    dependency_fingerprint: str
    idempotency_key: str
    policy_answer: Optional[PolicyAnswer] = None

    def __post_init__(self) -> None:
        if not str(self.proposal_id or "") or not str(self.context_id or ""):
            raise ValidationError("proposal_identity_missing")
        if not str(self.target_cell or ""):
            raise ValidationError("proposal_target_missing")
        object.__setattr__(self, "action", ActionType(self.action))
        if isinstance(self.payload, Mapping):
            payload = _pairs(self.payload)
        else:
            payload = _pairs({str(key): value for key, value in self.payload}) if self.payload else ()
        if len(canonical_json(_mapping(payload)).encode("utf-8")) > MAX_PROPOSAL_BYTES:
            raise ValidationError("proposal_payload_too_large")
        object.__setattr__(self, "payload", payload)
        if not str(self.dependency_fingerprint or ""):
            raise ValidationError("proposal_dependency_fingerprint_missing")
        if not str(self.idempotency_key or ""):
            raise ValidationError("proposal_idempotency_missing")

    @classmethod
    def make(
        cls,
        *,
        context_id: str,
        target_cell: str,
        action: ActionType,
        payload: Optional[Mapping[str, Any]],
        dependency_fingerprint: str,
        policy_answer: Optional[PolicyAnswer] = None,
        idempotency_key: str = "",
    ) -> "ActionProposal":
        body = {
            "schema": SCHEMA,
            "context_id": context_id,
            "target_cell": target_cell,
            "action": ActionType(action).value,
            "payload": dict(payload or {}),
            "dependency_fingerprint": dependency_fingerprint,
            "answer": policy_answer.to_dict() if policy_answer else None,
        }
        proposal_id = sha256_digest(body)
        idem = str(idempotency_key or proposal_id)
        return cls(
            proposal_id=proposal_id,
            context_id=str(context_id),
            target_cell=str(target_cell),
            action=ActionType(action),
            payload=_pairs(payload),
            dependency_fingerprint=str(dependency_fingerprint),
            idempotency_key=idem,
            policy_answer=policy_answer,
        )

    def payload_dict(self) -> dict[str, Any]:
        return _mapping(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "context_id": self.context_id,
            "target_cell": self.target_cell,
            "action": self.action.value,
            "payload": self.payload_dict(),
            "dependency_fingerprint": self.dependency_fingerprint,
            "idempotency_key": self.idempotency_key,
            "policy_answer": self.policy_answer.to_dict() if self.policy_answer else None,
        }


@dataclass(frozen=True)
class PolicyOutput:
    proposal: ActionProposal
    answer: PolicyAnswer


@runtime_checkable
class LocalPolicy(Protocol):
    """Shared policy interface for every cell."""

    def propose(self, snapshot: LocalSnapshot, allowed_actions: Sequence[str]) -> PolicyOutput | ActionProposal | Mapping[str, Any]:
        ...


class DeterministicPolicy:
    """Offline baseline: select the first enabled rule lexicographically."""

    model_id = "deterministic-baseline"
    fixture = True

    def propose(self, snapshot: LocalSnapshot, allowed_actions: Sequence[str]) -> PolicyOutput:
        allowed = tuple(str(action) for action in allowed_actions)
        if snapshot.enabled_rules and ActionType.ATTEMPT_RULE.value in allowed:
            row = snapshot.enabled_rules[0]
            answer = PolicyAnswer(
                selected=ActionType.ATTEMPT_RULE.value,
                probabilities=((ActionType.ATTEMPT_RULE.value, 1.0),),
                question_version="deterministic/v1",
                model_id=self.model_id,
                fixture=True,
                raw=(
                    ("selected", ActionType.ATTEMPT_RULE.value),
                    ("rule_id", row.rule_id),
                ),
            )
            proposal = ActionProposal.make(
                context_id=snapshot.context_id,
                target_cell=snapshot.cell_id,
                action=ActionType.ATTEMPT_RULE,
                payload={
                    "rule_id": row.rule_id,
                    "conclusion": row.conclusion,
                    "premises": list(row.premise_atoms),
                    "premise_evidence": list(row.premise_evidence),
                },
                dependency_fingerprint=snapshot.dependency_fingerprint,
                policy_answer=answer,
            )
            return PolicyOutput(proposal, answer)
        answer = PolicyAnswer(
            selected=ActionType.DEFER.value,
            probabilities=((ActionType.DEFER.value, 1.0),),
            question_version="deterministic/v1",
            model_id=self.model_id,
            fixture=True,
        )
        proposal = ActionProposal.make(
            context_id=snapshot.context_id,
            target_cell=snapshot.cell_id,
            action=ActionType.DEFER,
            payload={"reason": "no_enabled_rule"},
            dependency_fingerprint=snapshot.dependency_fingerprint,
            policy_answer=answer,
        )
        return PolicyOutput(proposal, answer)


class JevPolicyAdapter:
    """Inject an existing Jev/fixture answer function into local policy.

    The callable receives only ``snapshot.to_dict()`` and the allowed action
    names.  It cannot access the runtime, evidence store, or global hooks.
    The returned answer is observational metadata; the checker still validates
    the exact rule, premises, evidence, context, and dependency fingerprint.
    """

    def __init__(
        self,
        answer_fn: Callable[[Mapping[str, Any], Sequence[str]], Mapping[str, Any]],
        *,
        model_id: str = "jev-injected",
        question_version: str = "proof-ca/v1",
        fixture: bool = False,
    ) -> None:
        self.answer_fn = answer_fn
        self.model_id = str(model_id)
        self.question_version = str(question_version)
        self.fixture = bool(fixture)

    def propose(self, snapshot: LocalSnapshot, allowed_actions: Sequence[str]) -> PolicyOutput:
        raw = self.answer_fn(snapshot.to_dict(), tuple(str(x) for x in allowed_actions))
        if not isinstance(raw, Mapping):
            raise PolicyOutputError("policy_answer_must_be_mapping")
        data = dict(raw)
        data.setdefault("question_version", self.question_version)
        data.setdefault("model_id", self.model_id)
        data.setdefault("fixture", self.fixture)
        answer = PolicyAnswer.from_mapping(data, allowed=allowed_actions)
        payload = dict(data.get("payload") or {})
        for key in ("rule_id", "conclusion", "premises", "premise_evidence", "dependency_cell_id", "target"):
            if key in data and key not in payload:
                payload[key] = data[key]
        if answer.selected == ActionType.ATTEMPT_RULE.value and "rule_id" not in payload:
            payload["rule_id"] = snapshot.rule_id
            row = next((item for item in snapshot.enabled_rules if item.rule_id == snapshot.rule_id), None)
            if row:
                payload.update(
                    {
                        "conclusion": row.conclusion,
                        "premises": list(row.premise_atoms),
                        "premise_evidence": list(row.premise_evidence),
                    }
                )
        proposal = ActionProposal.make(
            context_id=snapshot.context_id,
            target_cell=snapshot.cell_id,
            action=ActionType(answer.selected),
            payload=payload,
            dependency_fingerprint=snapshot.dependency_fingerprint,
            policy_answer=answer,
            idempotency_key=str(data.get("idempotency_key") or ""),
        )
        return PolicyOutput(proposal, answer)


@dataclass(frozen=True)
class VerificationRequest:
    context_id: str
    target: str
    candidate_artifact: str
    source_dependencies: tuple[str, ...]
    verifier_id: str
    verifier_version: str
    verifier_options: tuple[tuple[str, Any], ...]
    axiom_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "target": self.target,
            "candidate_artifact": self.candidate_artifact,
            "source_dependencies": list(self.source_dependencies),
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verifier_options": _mapping(self.verifier_options),
            "axiom_policy": self.axiom_policy,
        }


@dataclass(frozen=True)
class VerificationReceipt:
    receipt_id: str
    context_id: str
    target: str
    status: VerificationStatus
    verifier_id: str
    verifier_version: str
    candidate_artifact: str = ""
    source_dependencies: tuple[str, ...] = ()
    details: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.receipt_id or not self.context_id or not self.target:
            raise ValidationError("verification_receipt_identity_missing")
        object.__setattr__(self, "status", VerificationStatus(self.status))
        object.__setattr__(self, "source_dependencies", tuple(sorted({str(x) for x in self.source_dependencies})))
        if isinstance(self.details, Mapping):
            detail_pairs = _pairs(self.details)
        else:
            detail_pairs = _pairs({str(key): value for key, value in self.details}) if self.details else ()
        object.__setattr__(self, "details", detail_pairs)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VerificationReceipt":
        row = cls(
            receipt_id=str(raw.get("receipt_id") or ""),
            context_id=str(raw.get("context_id") or ""),
            target=str(raw.get("target") or ""),
            status=VerificationStatus(str(raw.get("status") or "")),
            verifier_id=str(raw.get("verifier_id") or ""),
            verifier_version=str(raw.get("verifier_version") or ""),
            candidate_artifact=str(raw.get("candidate_artifact") or ""),
            source_dependencies=tuple(str(x) for x in raw.get("source_dependencies") or ()),
            details=_pairs(dict(raw.get("details") or {})),
        )
        _strict_value(row.to_dict())
        return row

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "context_id": self.context_id,
            "target": self.target,
            "status": self.status.value,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "candidate_artifact": self.candidate_artifact,
            "source_dependencies": list(self.source_dependencies),
            "details": _mapping(self.details),
        }


@runtime_checkable
class VerifierAdapter(Protocol):
    def verify(self, request: VerificationRequest) -> VerificationReceipt | Mapping[str, Any]:
        ...


@dataclass
class RuntimeMetrics:
    cells_visited: int = 0
    edges_traversed: int = 0
    messages_delivered: int = 0
    policy_calls: int = 0
    rule_attempts: int = 0
    verifier_attempts: int = 0
    policy_rejections: int = 0
    duplicate_messages: int = 0
    retrieval_requests: int = 0
    steps: int = 0

    def to_dict(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.__dict__.items()}


@dataclass
class ResourceLedger:
    """Authoritative integer operation budget; ``None`` means explicitly unlimited."""

    operation_limit: Optional[int] = None
    consumed: int = 0
    reservations: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.operation_limit is not None and int(self.operation_limit) < 0:
            raise ValidationError("negative_operation_budget")
        self.operation_limit = None if self.operation_limit is None else int(self.operation_limit)
        self.consumed = int(self.consumed)
        if self.consumed < 0:
            raise ValidationError("negative_consumed_budget")
        if self.operation_limit is not None and self.consumed > self.operation_limit:
            raise ValidationError("consumed_budget_exceeds_limit")
        self.reservations = {str(key): int(value) for key, value in dict(self.reservations).items()}

    @property
    def remaining(self) -> Optional[int]:
        if self.operation_limit is None:
            return None
        return max(0, int(self.operation_limit) - int(self.consumed))

    def reserve(self, operation_id: str, units: int = 1) -> dict[str, Any]:
        key = str(operation_id or "")
        amount = int(units)
        if not key or amount <= 0:
            raise ValidationError("invalid_resource_reservation")
        if key in self.reservations:
            return {"reserved": False, "duplicate": True, "remaining": self.remaining}
        if self.operation_limit is not None and self.remaining is not None and self.remaining < amount:
            return {"reserved": False, "exhausted": True, "remaining": self.remaining}
        self.reservations[key] = amount
        self.consumed += amount
        return {"reserved": True, "duplicate": False, "remaining": self.remaining}

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_limit": self.operation_limit,
            "consumed": self.consumed,
            "reservations": dict(self.reservations),
            "remaining": self.remaining,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResourceLedger":
        return cls(
            operation_limit=data.get("operation_limit"),
            consumed=int(data.get("consumed") or 0),
            reservations={str(k): int(v) for k, v in dict(data.get("reservations") or {}).items()},
        )


@dataclass(frozen=True)
class LocalMessage:
    message_id: str
    context_id: str
    source_cell: str
    target_cell: str
    kind: str
    payload: tuple[tuple[str, Any], ...]

    @classmethod
    def make(
        cls,
        *,
        context_id: str,
        source_cell: str,
        target_cell: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> "LocalMessage":
        body = {
            "schema": SCHEMA,
            "context_id": context_id,
            "source_cell": source_cell,
            "target_cell": target_cell,
            "kind": kind,
            "payload": dict(payload),
        }
        return cls(
            message_id=sha256_digest(body),
            context_id=str(context_id),
            source_cell=str(source_cell),
            target_cell=str(target_cell),
            kind=str(kind),
            payload=_pairs(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "context_id": self.context_id,
            "source_cell": self.source_cell,
            "target_cell": self.target_cell,
            "kind": self.kind,
            "payload": _mapping(self.payload),
        }


class ProofGraphCA:
    """Single-process proof-carrying graph cellular automaton."""

    def __init__(
        self,
        *,
        atoms: Sequence[Atom],
        rules: Sequence[Rule],
        assumptions: Sequence[Atom],
        targets: Sequence[Atom] = (),
        predicates: Optional[Mapping[str, int]] = None,
        context: Optional[ContextIdentity] = None,
        policy: Optional[LocalPolicy] = None,
        verifier: Optional[VerifierAdapter] = None,
        operation_budget: Optional[int] = None,
        neighbor_limit: int = 8,
        max_events: int = 256,
        max_evidence: int = 1024,
        schedule_seed: Optional[int] = None,
        _seed_assumptions: bool = True,
    ) -> None:
        self.schema = SCHEMA
        self.atoms = self._validate_universe(atoms, rules, predicates)
        self.atom_by_key = {atom.key: atom for atom in self.atoms}
        self.predicates = self._predicate_table(self.atoms, predicates)
        self.rules = self._validate_rules(rules)
        self.rule_by_id = {rule.rule_id: rule for rule in self.rules}
        self.assumptions = self._validate_atom_list(assumptions, "assumptions")
        self.targets = self._validate_atom_list(targets, "targets")
        if context is None:
            context = ContextIdentity.create(
                facts_revision=sha256_digest(
                    {"atoms": [atom.to_dict() for atom in self.atoms], "assumptions": [atom.key for atom in self.assumptions]}
                ),
                rules_revision=sha256_digest([rule.to_dict() for rule in self.rules]),
            )
        self.context = context
        self.policy: LocalPolicy = policy or DeterministicPolicy()
        self.verifier = verifier
        self.neighbor_limit = max(1, int(neighbor_limit))
        self.max_events = max(1, int(max_events))
        self.max_evidence = max(1, int(max_evidence))
        self.schedule_seed = schedule_seed
        self._schedule_rng = random.Random(schedule_seed) if schedule_seed is not None else None
        self.cells: dict[str, Cell] = {}
        self.edges: dict[str, DependencyEdge] = {}
        self.forward_edges: dict[str, list[str]] = {}
        self.reverse_edges: dict[str, list[str]] = {}
        self.rules_by_premise: dict[str, list[str]] = {}
        self.rules_by_conclusion: dict[str, list[str]] = {}
        self.evidence: dict[str, Evidence] = {}
        self.historical_evidence: dict[str, Evidence] = {}
        self.fact_evidence: dict[str, list[str]] = {}
        self.accepted_facts: set[str] = set()
        self.pending_messages: deque[LocalMessage] = deque()
        self.delivered_message_ids: set[str] = set()
        self.ready_queue: deque[str] = deque()
        self.queued_rules: set[str] = set()
        self.applied_proposals: dict[str, dict[str, Any]] = {}
        self.idempotency_keys: dict[str, str] = {}
        self.verification_cache: dict[str, dict[str, Any]] = {}
        self.policy_retrievals: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []
        self._event_sequence = 0
        self._scheduler_step = 0
        self._error: Optional[str] = None
        self.metrics = RuntimeMetrics()
        self.resources = ResourceLedger(operation_budget)
        self._build_graph()
        if _seed_assumptions:
            for atom in self.assumptions:
                self._admit_assumption(atom)
            self.deliver_pending()
            for rule in self.rules:
                if not rule.premises:
                    self._enqueue_rule(rule.rule_id, reason="zero_premise_rule")
        else:
            self._set_pending_counts()

    @staticmethod
    def _validate_universe(
        atoms: Sequence[Atom], rules: Sequence[Rule], predicates: Optional[Mapping[str, int]]
    ) -> tuple[Atom, ...]:
        declared = tuple(atoms)
        if not declared:
            raise ValidationError("empty_atom_universe")
        if any(not isinstance(atom, Atom) for atom in declared):
            raise ValidationError("universe_requires_atoms")
        keys = [atom.key for atom in declared]
        if len(set(keys)) != len(keys):
            raise ValidationError("duplicate_declared_atom")
        all_rows = list(declared)
        for rule in rules:
            if not isinstance(rule, Rule):
                raise ValidationError("rules_require_typed_rule_records")
            all_rows.extend(rule.premises)
            all_rows.append(rule.conclusion)
        declared_keys = set(keys)
        missing = sorted({atom.key for atom in all_rows if atom.key not in declared_keys})
        if missing:
            raise ValidationError(f"undeclared_atom:{missing[0]}")
        table = dict(predicates or {})
        if table:
            for name, arity in table.items():
                if not _IDENT.fullmatch(str(name)) or int(arity) < 0:
                    raise ValidationError("malformed_predicate_table")
            for atom in declared:
                if atom.predicate not in table or int(table[atom.predicate]) != len(atom.args):
                    raise ValidationError(f"predicate_arity_mismatch:{atom.key}")
        return tuple(declared)

    @staticmethod
    def _predicate_table(atoms: Sequence[Atom], predicates: Optional[Mapping[str, int]]) -> dict[str, int]:
        table: dict[str, int] = {}
        for atom in atoms:
            old = table.setdefault(atom.predicate, len(atom.args))
            if old != len(atom.args):
                raise ValidationError(f"predicate_arity_mismatch:{atom.predicate}")
        if predicates:
            for name, arity in predicates.items():
                table[str(name)] = int(arity)
        return table

    def _validate_rules(self, rules: Sequence[Rule]) -> tuple[Rule, ...]:
        rows = tuple(rules)
        ids = [rule.rule_id for rule in rows]
        if len(set(ids)) != len(ids):
            raise ValidationError("duplicate_rule_id")
        for rule in rows:
            if any(atom.key not in self.atom_by_key for atom in (*rule.premises, rule.conclusion)):
                raise ValidationError(f"rule_uses_undeclared_atom:{rule.rule_id}")
        return tuple(sorted(rows, key=lambda row: row.rule_id))

    def _validate_atom_list(self, atoms: Sequence[Atom], name: str) -> tuple[Atom, ...]:
        rows = tuple(atoms)
        if any(not isinstance(atom, Atom) for atom in rows):
            raise ValidationError(f"{name}_requires_atoms")
        if len({atom.key for atom in rows}) != len(rows):
            raise ValidationError(f"duplicate_{name}_atom")
        for atom in rows:
            if atom.key not in self.atom_by_key:
                raise ValidationError(f"{name}_uses_undeclared_atom:{atom.key}")
        return rows

    @staticmethod
    def fact_cell_id(atom: Atom | str) -> str:
        key = atom.key if isinstance(atom, Atom) else str(atom)
        return f"cell://fact/{key}"

    @staticmethod
    def rule_cell_id(rule_id: str) -> str:
        return f"cell://rule/{str(rule_id)}"

    def _build_graph(self) -> None:
        target_keys = {atom.key for atom in self.targets}
        for atom in self.atoms:
            cid = self.fact_cell_id(atom)
            is_target = atom.key in target_keys
            self.cells[cid] = Cell(
                cell_id=cid,
                cell_type=CellType.TARGET if is_target else CellType.FACT,
                symbolic=SymbolicState(
                    atom=atom,
                    target=is_target,
                    obligation=f"prove:{atom.key}" if is_target else "",
                    target_identity=f"target:{atom.key}" if is_target else "",
                ),
            )
        for rule in self.rules:
            cid = self.rule_cell_id(rule.rule_id)
            self.cells[cid] = Cell(
                cell_id=cid,
                cell_type=CellType.RULE,
                symbolic=SymbolicState(
                    rule_id=rule.rule_id,
                    conclusion=rule.conclusion,
                    dependencies=tuple(self.fact_cell_id(atom) for atom in rule.premises),
                ),
            )
            self.rules_by_conclusion.setdefault(rule.conclusion.key, []).append(rule.rule_id)
            for index, premise in enumerate(rule.premises):
                self.rules_by_premise.setdefault(premise.key, []).append(rule.rule_id)
                self._add_edge(
                    self.fact_cell_id(premise),
                    cid,
                    EdgeType.PREMISE,
                    rule_id=rule.rule_id,
                    premise_index=index,
                )
            self._add_edge(cid, self.fact_cell_id(rule.conclusion), EdgeType.CONCLUSION, rule_id=rule.rule_id)
        for rows in self.rules_by_premise.values():
            rows.sort()
        for rows in self.rules_by_conclusion.values():
            rows.sort()

    def _add_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType,
        *,
        rule_id: str = "",
        premise_index: Optional[int] = None,
    ) -> None:
        edge = DependencyEdge.make(
            source,
            target,
            edge_type,
            rule_id=rule_id,
            premise_index=premise_index,
        )
        self.edges[edge.edge_id] = edge
        self.forward_edges.setdefault(source, []).append(edge.edge_id)
        self.reverse_edges.setdefault(target, []).append(edge.edge_id)

    def _cell(self, cell_id: str) -> Cell:
        try:
            return self.cells[cell_id]
        except KeyError as exc:
            raise ValidationError(f"unknown_cell:{cell_id}") from exc

    def _replace_cell(
        self,
        cell: Cell,
        *,
        symbolic: Optional[SymbolicState] = None,
        policy: Optional[PolicyState] = None,
        evidence: Optional[EvidenceState] = None,
        runtime: Optional[RuntimeState] = None,
    ) -> None:
        self.cells[cell.cell_id] = Cell(
            cell_id=cell.cell_id,
            cell_type=cell.cell_type,
            symbolic=symbolic or cell.symbolic,
            policy=policy or cell.policy,
            evidence=evidence or cell.evidence,
            runtime=runtime or cell.runtime,
        )

    def _record_event(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        safe = _strict_value(dict(payload))
        self._event_sequence += 1
        row = {
            "event_id": sha256_digest(
                {"schema": SCHEMA, "context_id": self.context.context_id, "sequence": self._event_sequence, "type": event_type, "payload": safe}
            ),
            "sequence": self._event_sequence,
            "context_id": self.context.context_id,
            "type": str(event_type),
            "payload": safe,
        }
        self.event_log.append(row)
        self.event_log = self.event_log[-self.max_events :]
        return row

    def _set_pending_counts(self) -> None:
        count = len(self.pending_messages)
        for cell in list(self.cells.values()):
            runtime = RuntimeState(
                version=cell.runtime.version,
                execution_status=cell.runtime.execution_status,
                pending_messages=count,
                resource_ref=cell.runtime.resource_ref,
            )
            self._replace_cell(cell, runtime=runtime)

    def _admit_assumption(self, atom: Atom) -> dict[str, Any]:
        evidence = Evidence.make(
            kind=EvidenceKind.TRUSTED_ASSUMPTION,
            status=EvidenceStatus.ASSUMED,
            subject=atom,
            context_id=self.context.context_id,
            source="declared_assumption",
        )
        return self._admit_evidence(evidence, accept=True)

    def _store_evidence(self, evidence: Evidence) -> dict[str, Any]:
        if evidence.context_id != self.context.context_id:
            raise ContextMismatch("evidence_context_mismatch")
        existing = self.evidence.get(evidence.evidence_id)
        if existing is not None:
            if existing != evidence:
                raise ValidationError("evidence_id_collision")
            return {"stored": False, "duplicate": True}
        if len(self.evidence) >= self.max_evidence:
            removable = next(
                (
                    eid
                    for eid, row in self.evidence.items()
                    if not row.authoritative and eid not in {ref for refs in self.fact_evidence.values() for ref in refs}
                ),
                None,
            )
            if removable is None:
                raise ProofCAError("evidence_store_full")
            self.evidence.pop(removable, None)
        self.evidence[evidence.evidence_id] = evidence
        self._record_event("evidence_stored", {"evidence_id": evidence.evidence_id, "kind": evidence.kind.value, "subject": evidence.subject.key})
        return {"stored": True, "duplicate": False}

    def _validate_authoritative_evidence(self, evidence: Evidence) -> None:
        if evidence.context_id != self.context.context_id:
            raise ContextMismatch("evidence_context_mismatch")
        if evidence.subject.key not in self.atom_by_key:
            raise ValidationError("evidence_subject_undeclared")
        if not evidence.authoritative:
            raise ValidationError("evidence_not_authoritative")
        if evidence.kind == EvidenceKind.TRUSTED_ASSUMPTION:
            if evidence.status != EvidenceStatus.ASSUMED or evidence.subject.key not in {atom.key for atom in self.assumptions}:
                raise ValidationError("undeclared_trusted_assumption")
            if evidence.rule_id or evidence.supporting_evidence:
                raise ValidationError("malformed_assumption_evidence")
            return
        if evidence.kind == EvidenceKind.EXTERNAL_VERIFICATION:
            if evidence.status != EvidenceStatus.VERIFIED:
                raise ValidationError("external_evidence_not_verified")
            if not evidence.source:
                raise ValidationError("external_evidence_missing_source")
            receipt_raw = dict(evidence.details).get("receipt")
            if not isinstance(receipt_raw, Mapping):
                raise ValidationError("external_evidence_missing_receipt")
            receipt = VerificationReceipt.from_mapping(receipt_raw)
            if (
                receipt.context_id != self.context.context_id
                or receipt.target != evidence.subject.key
                or receipt.status != VerificationStatus.VERIFIED
                or receipt.verifier_id != self.context.verifier_id
                or receipt.verifier_version != self.context.verifier_version
            ):
                raise ValidationError("external_receipt_not_applicable")
            return
        if evidence.kind != EvidenceKind.RULE_DERIVATION or evidence.status != EvidenceStatus.VERIFIED:
            raise ValidationError("unsupported_authoritative_evidence")
        rule = self.rule_by_id.get(evidence.rule_id)
        if rule is None:
            raise ValidationError("unknown_derivation_rule")
        if evidence.subject != rule.conclusion:
            raise ValidationError("derivation_conclusion_mismatch")
        if tuple(evidence.premise_atoms) != tuple(atom.key for atom in rule.premises):
            raise ValidationError("derivation_premises_mismatch")
        if len(evidence.supporting_evidence) != len(rule.premises):
            raise ValidationError("missing_premise_evidence")
        for atom_key, evidence_id in zip(evidence.premise_atoms, evidence.supporting_evidence):
            if atom_key not in self.atom_by_key:
                raise ValidationError("derivation_uses_undeclared_premise")
            if atom_key not in self.accepted_facts:
                raise ValidationError("premise_not_accepted")
            supporting = self.evidence.get(evidence_id)
            if supporting is None or supporting.context_id != self.context.context_id:
                raise ValidationError("supporting_evidence_missing_or_stale")
            if supporting.subject.key != atom_key or not supporting.authoritative:
                raise ValidationError("supporting_evidence_subject_mismatch")
            if evidence_id not in self.fact_evidence.get(atom_key, ()):
                raise ValidationError("supporting_evidence_not_attached")

    def _admit_evidence(self, evidence: Evidence, *, accept: bool) -> dict[str, Any]:
        if accept:
            self._validate_authoritative_evidence(evidence)
            self._store_evidence(evidence)
            return self._accept_fact(evidence)
        self._store_evidence(evidence)
        return {"accepted": False, "stored": True, "evidence_id": evidence.evidence_id}

    def _accept_fact(self, evidence: Evidence) -> dict[str, Any]:
        key = evidence.subject.key
        refs = self.fact_evidence.setdefault(key, [])
        if evidence.evidence_id not in refs:
            refs.append(evidence.evidence_id)
        if key in self.accepted_facts:
            cell = self._cell(self.fact_cell_id(evidence.subject))
            self._replace_cell(cell, evidence=EvidenceState(tuple(refs)))
            return {
                "accepted": True,
                "new_fact": False,
                "outcome": "FACT_ALREADY_ACCEPTED",
                "atom": key,
                "evidence_id": evidence.evidence_id,
            }
        self.accepted_facts.add(key)
        cell = self._cell(self.fact_cell_id(evidence.subject))
        symbolic = SymbolicState(
            atom=cell.symbolic.atom,
            rule_id=cell.symbolic.rule_id,
            conclusion=cell.symbolic.conclusion,
            target=cell.symbolic.target,
            dependencies=cell.symbolic.dependencies,
            accepted_derivations=tuple(refs),
            obligation=cell.symbolic.obligation,
            target_identity=cell.symbolic.target_identity,
        )
        runtime = RuntimeState(
            version=cell.runtime.version + 1,
            execution_status="accepted",
            pending_messages=len(self.pending_messages),
            resource_ref=cell.runtime.resource_ref,
        )
        self._replace_cell(cell, symbolic=symbolic, evidence=EvidenceState(tuple(refs)), runtime=runtime)
        self._record_event(
            "fact_accepted",
            {
                "atom": key,
                "cell_id": cell.cell_id,
                "evidence_id": evidence.evidence_id,
                "kind": evidence.kind.value,
            },
        )
        for rule_id in self.rules_by_premise.get(key, ()):
            message = LocalMessage.make(
                context_id=self.context.context_id,
                source_cell=cell.cell_id,
                target_cell=self.rule_cell_id(rule_id),
                kind="fact_available",
                payload={"atom": key, "evidence_id": evidence.evidence_id},
            )
            self.pending_messages.append(message)
            self._record_event("message_enqueued", message.to_dict())
        self._set_pending_counts()
        return {
            "accepted": True,
            "new_fact": True,
            "outcome": "FACT_ACCEPTED",
            "atom": key,
            "evidence_id": evidence.evidence_id,
        }

    def _enqueue_rule(self, rule_id: str, *, reason: str) -> bool:
        if rule_id in self.queued_rules:
            return False
        if rule_id not in self.rule_by_id:
            return False
        self.queued_rules.add(rule_id)
        self.ready_queue.append(rule_id)
        self._record_event("rule_enqueued", {"rule_id": rule_id, "reason": reason})
        return True

    def deliver_message(self, message: LocalMessage | Mapping[str, Any]) -> dict[str, Any]:
        row = message if isinstance(message, LocalMessage) else LocalMessage(
            message_id=str(message.get("message_id") or ""),
            context_id=str(message.get("context_id") or ""),
            source_cell=str(message.get("source_cell") or ""),
            target_cell=str(message.get("target_cell") or ""),
            kind=str(message.get("kind") or ""),
            payload=_pairs(dict(message.get("payload") or {})),
        )
        if not row.message_id or not row.source_cell or not row.target_cell or not row.kind:
            return {"delivered": False, "outcome": "INVALID_MESSAGE", "message_id": row.message_id}
        if row.context_id != self.context.context_id:
            return {"delivered": False, "outcome": "STALE_MESSAGE", "message_id": row.message_id}
        if row.source_cell not in self.cells or row.target_cell not in self.cells:
            return {"delivered": False, "outcome": "INVALID_MESSAGE", "message_id": row.message_id}
        expected_id = LocalMessage.make(
            context_id=row.context_id,
            source_cell=row.source_cell,
            target_cell=row.target_cell,
            kind=row.kind,
            payload=_mapping(row.payload),
        ).message_id
        if row.message_id != expected_id:
            return {"delivered": False, "outcome": "INVALID_MESSAGE", "message_id": row.message_id}
        if row.message_id in self.delivered_message_ids:
            self.metrics.duplicate_messages += 1
            return {"delivered": False, "duplicate": True, "message_id": row.message_id}
        if len(canonical_json(row.to_dict()).encode("utf-8")) > MAX_MESSAGE_BYTES:
            return {"delivered": False, "outcome": "MESSAGE_TOO_LARGE", "message_id": row.message_id}
        self.delivered_message_ids.add(row.message_id)
        if row.kind == "fact_available" and row.target_cell.startswith("cell://rule/"):
            self._enqueue_rule(row.target_cell.split("cell://rule/", 1)[1], reason="message")
        self.metrics.messages_delivered += 1
        self._record_event("message_delivered", row.to_dict())
        self._set_pending_counts()
        return {"delivered": True, "message_id": row.message_id, "target_cell": row.target_cell}

    def deliver_pending(self, *, limit: Optional[int] = None, reverse: bool = False) -> dict[str, Any]:
        count = 0
        while self.pending_messages and (limit is None or count < int(limit)):
            if reverse and len(self.pending_messages) > 1:
                rows = list(self.pending_messages)
                row = rows.pop()
                self.pending_messages = deque(rows)
            else:
                row = self.pending_messages.popleft()
            self.deliver_message(row)
            count += 1
        self._set_pending_counts()
        return {"delivered": count, "pending": len(self.pending_messages)}

    def _rule_enabled(self, rule: Rule) -> bool:
        return all(atom.key in self.accepted_facts for atom in rule.premises)

    def _premise_evidence(self, rule: Rule) -> tuple[str, ...]:
        return tuple(self.fact_evidence[atom.key][-1] for atom in rule.premises)

    def _dependency_fingerprint(self, rule: Rule) -> str:
        rows = []
        for atom in rule.premises:
            rows.append(
                {
                    "cell_id": self.fact_cell_id(atom),
                    "atom": atom.key,
                    "evidence": list(self.fact_evidence.get(atom.key) or ()),
                }
            )
        rows.append({"cell_id": self.rule_cell_id(rule.rule_id), "rule": rule.to_dict()})
        return sha256_digest({"context_id": self.context.context_id, "dependencies": rows})

    def _external_target_fingerprint(self, target: str) -> str:
        return sha256_digest(
            {
                "context_id": self.context.context_id,
                "cell_id": self.fact_cell_id(target),
                "atom": target,
                "evidence": list(self.fact_evidence.get(target) or ()),
            }
        )

    def _snapshot(self, rule: Rule) -> LocalSnapshot:
        rule_cell = self._cell(self.rule_cell_id(rule.rule_id))
        dependency_ids = tuple(self.fact_cell_id(atom) for atom in rule.premises)
        edge_ids = list(self.forward_edges.get(rule_cell.cell_id, ())) + list(self.reverse_edges.get(rule_cell.cell_id, ()))
        neighbors: list[NeighborObservation] = []
        seen_edges: set[str] = set()
        for edge_id in edge_ids:
            if edge_id in seen_edges:
                continue
            seen_edges.add(edge_id)
            edge = self.edges[edge_id]
            other_id = edge.target if edge.source == rule_cell.cell_id else edge.source
            other = self._cell(other_id)
            atom = other.symbolic.atom.key if other.symbolic.atom else ""
            neighbors.append(
                NeighborObservation(
                    cell_id=other.cell_id,
                    cell_type=other.cell_type.value,
                    edge_type=edge.edge_type.value,
                    atom=atom,
                    accepted=bool(atom and atom in self.accepted_facts),
                    activation=other.policy.activation,
                    version=other.runtime.version,
                )
            )
        neighbors.sort(key=lambda row: (row.cell_id, row.edge_type))
        enabled = self._rule_enabled(rule)
        observation = RuleObservation(
            rule_id=rule.rule_id,
            premise_atoms=tuple(atom.key for atom in rule.premises),
            conclusion=rule.conclusion.key,
            premise_evidence=self._premise_evidence(rule) if enabled else tuple(
                self.fact_evidence.get(atom.key, [""])[-1] if self.fact_evidence.get(atom.key) else "" for atom in rule.premises
            ),
            enabled=enabled,
        )
        self.metrics.cells_visited += 1
        self.metrics.edges_traversed += len(edge_ids)
        features = {
            "cell_type": rule_cell.cell_type.value,
            "edge_types": sorted({self.edges[eid].edge_type.value for eid in edge_ids}),
            "n_mandatory_dependencies": len(dependency_ids),
            "n_missing_premises": sum(atom.key not in self.accepted_facts for atom in rule.premises),
            "full_neighbor_count": len(neighbors),
            "bounded_neighbor_count": min(len(neighbors), self.neighbor_limit),
        }
        return LocalSnapshot(
            context_id=self.context.context_id,
            cell_id=rule_cell.cell_id,
            cell_type=rule_cell.cell_type.value,
            atom=rule.conclusion.key,
            rule_id=rule.rule_id,
            step=self._scheduler_step,
            mandatory_dependencies=dependency_ids,
            enabled_rules=(observation,),
            neighbor_summaries=tuple(neighbors[: self.neighbor_limit]),
            full_neighbor_count=len(neighbors),
            feature_map=_pairs(features),
            allowed_actions=tuple(action.value for action in ActionType),
            dependency_fingerprint=self._dependency_fingerprint(rule),
        )

    def _normalize_policy_output(
        self,
        output: PolicyOutput | ActionProposal | Mapping[str, Any],
        snapshot: LocalSnapshot,
    ) -> tuple[ActionProposal, PolicyAnswer]:
        if isinstance(output, PolicyOutput):
            proposal, answer = output.proposal, output.answer
        elif isinstance(output, ActionProposal):
            proposal = output
            answer = output.policy_answer or PolicyAnswer(
                selected=proposal.action.value,
                question_version="unknown",
                model_id="unknown",
                fixture=False,
            )
        elif isinstance(output, Mapping):
            data = dict(output)
            answer = PolicyAnswer.from_mapping(data, allowed=snapshot.allowed_actions)
            payload = dict(data.get("payload") or {})
            for key in ("rule_id", "conclusion", "premises", "premise_evidence", "dependency_cell_id", "target"):
                if key in data and key not in payload:
                    payload[key] = data[key]
            proposal = ActionProposal.make(
                context_id=snapshot.context_id,
                target_cell=snapshot.cell_id,
                action=ActionType(answer.selected),
                payload=payload,
                dependency_fingerprint=str(data.get("dependency_fingerprint") or snapshot.dependency_fingerprint),
                policy_answer=answer,
                idempotency_key=str(data.get("idempotency_key") or ""),
            )
        else:
            raise PolicyOutputError("unsupported_policy_output")
        allowed = set(snapshot.allowed_actions)
        if answer.selected not in allowed:
            raise PolicyOutputError("answer_choice_not_allowed")
        if any(choice not in allowed for choice, _ in answer.probabilities):
            raise PolicyOutputError("probability_choice_not_allowed")
        if proposal.action.value != answer.selected:
            raise PolicyOutputError("proposal_action_answer_mismatch")
        if proposal.policy_answer is not None and proposal.policy_answer.selected not in allowed:
            raise PolicyOutputError("proposal_answer_choice_not_allowed")
        if proposal.policy_answer is not None and proposal.policy_answer.selected != proposal.action.value:
            raise PolicyOutputError("proposal_answer_action_mismatch")
        if proposal.context_id != self.context.context_id:
            raise PolicyOutputError("policy_proposal_context_mismatch")
        if proposal.target_cell != snapshot.cell_id:
            raise PolicyOutputError("policy_proposal_target_mismatch")
        if proposal.action.value not in snapshot.allowed_actions:
            raise PolicyOutputError("policy_action_not_allowed")
        return proposal, answer

    def _invalid_policy_result(self, rule: Rule, reason: str) -> dict[str, Any]:
        self.metrics.policy_rejections += 1
        self._record_event("policy_rejected", {"rule_id": rule.rule_id, "reason": reason})
        self._enqueue_rule(rule.rule_id, reason="policy_rejected")
        return {"applied": False, "accepted": False, "outcome": "POLICY_REJECTED", "reason": reason, "rule_id": rule.rule_id}

    def _validate_proposal(self, proposal: ActionProposal) -> Optional[dict[str, Any]]:
        if proposal.context_id != self.context.context_id:
            return {"applied": False, "accepted": False, "outcome": "STALE_CONTEXT", "reason": "proposal_context_mismatch"}
        previous_id = self.idempotency_keys.get(proposal.idempotency_key)
        if previous_id and previous_id != proposal.proposal_id:
            return {"applied": False, "accepted": False, "outcome": "IDEMPOTENCY_CONFLICT", "reason": "idempotency_key_reused"}
        if proposal.dependency_fingerprint:
            payload = proposal.payload_dict()
            rule_id = str(payload.get("rule_id") or "")
            if rule_id in self.rule_by_id and proposal.dependency_fingerprint != self._dependency_fingerprint(self.rule_by_id[rule_id]):
                return {"applied": False, "accepted": False, "outcome": "STALE_PROPOSAL", "reason": "stale_dependency_fingerprint"}
            if proposal.action == ActionType.REQUEST_EXTERNAL_VERIFICATION:
                target = str(payload.get("target") or self.context.target or "")
                if target in self.atom_by_key:
                    expected = self._external_target_fingerprint(target)
                    if proposal.dependency_fingerprint != expected:
                        return {"applied": False, "accepted": False, "outcome": "STALE_PROPOSAL", "reason": "stale_target_fingerprint"}
        return None

    def checked_apply(self, proposal: ActionProposal | Mapping[str, Any]) -> dict[str, Any]:
        """Validate and apply one local action; only this method admits facts."""

        if isinstance(proposal, ActionProposal):
            row = proposal
        elif isinstance(proposal, Mapping):
            try:
                answer_raw = proposal.get("policy_answer")
                answer = PolicyAnswer.from_mapping(answer_raw, allowed=tuple(action.value for action in ActionType)) if isinstance(answer_raw, Mapping) else None
                row = ActionProposal(
                    proposal_id=str(proposal.get("proposal_id") or ""),
                    context_id=str(proposal.get("context_id") or ""),
                    target_cell=str(proposal.get("target_cell") or ""),
                    action=ActionType(str(proposal.get("action") or "")),
                    payload=_pairs(dict(proposal.get("payload") or {})),
                    dependency_fingerprint=str(proposal.get("dependency_fingerprint") or ""),
                    idempotency_key=str(proposal.get("idempotency_key") or ""),
                    policy_answer=answer,
                )
            except (ProofCAError, KeyError, TypeError, ValueError) as exc:
                return {"applied": False, "accepted": False, "outcome": "INVALID_PROPOSAL", "reason": str(exc)}
        else:
            return {"applied": False, "accepted": False, "outcome": "INVALID_PROPOSAL", "reason": "proposal_must_be_typed"}
        prior = self.applied_proposals.get(row.proposal_id)
        if prior is not None:
            return {**prior, "duplicate": True}
        invalid = self._validate_proposal(row)
        if invalid is not None:
            self.applied_proposals[row.proposal_id] = dict(invalid)
            self.idempotency_keys.setdefault(row.idempotency_key, row.proposal_id)
            self._record_event("proposal_rejected", {"proposal_id": row.proposal_id, **invalid})
            return invalid
        payload = row.payload_dict()
        if row.action == ActionType.ATTEMPT_RULE:
            result = self._apply_rule_proposal(row, payload)
        elif row.action == ActionType.REQUEST_DEPENDENCY:
            result = self._apply_dependency_request(row, payload)
        elif row.action == ActionType.REQUEST_EXTERNAL_VERIFICATION:
            result = self._apply_external_request(row, payload)
        elif row.action == ActionType.UPDATE_POLICY:
            result = self._apply_policy_update(row, payload)
        elif row.action == ActionType.DEFER:
            result = {"applied": False, "accepted": False, "outcome": "DEFERRED", "reason": str(payload.get("reason") or "policy_defer")}
        else:
            result = {"applied": False, "accepted": False, "outcome": "UNKNOWN_ACTION", "reason": row.action.value}
        self.applied_proposals[row.proposal_id] = dict(result)
        self.idempotency_keys[row.idempotency_key] = row.proposal_id
        self._record_event("proposal_applied", {"proposal_id": row.proposal_id, "action": row.action.value, **result})
        return result

    def _apply_rule_proposal(self, proposal: ActionProposal, payload: Mapping[str, Any]) -> dict[str, Any]:
        if "theorem_ok" in payload or "lake_ok" in payload or "verified" in payload:
            return {"applied": False, "accepted": False, "outcome": "AUTHORITY_FIELD_REJECTED", "reason": "policy_cannot_forge_evidence"}
        rule_id = str(payload.get("rule_id") or "")
        rule = self.rule_by_id.get(rule_id)
        if rule is None:
            return {"applied": False, "accepted": False, "outcome": "INVALID_RULE", "reason": "unknown_rule"}
        if proposal.target_cell != self.rule_cell_id(rule_id):
            return {"applied": False, "accepted": False, "outcome": "INVALID_TARGET", "reason": "rule_cell_mismatch"}
        conclusion = str(payload.get("conclusion") or "")
        premises = tuple(str(item) for item in payload.get("premises") or ())
        premise_evidence = tuple(str(item) for item in payload.get("premise_evidence") or ())
        if conclusion != rule.conclusion.key:
            return {"applied": False, "accepted": False, "outcome": "INVALID_CONCLUSION", "reason": "conclusion_mismatch"}
        expected_premises = tuple(atom.key for atom in rule.premises)
        if premises != expected_premises:
            return {"applied": False, "accepted": False, "outcome": "INVALID_PREMISES", "reason": "premise_identity_mismatch"}
        if not self._rule_enabled(rule):
            return {"applied": False, "accepted": False, "outcome": "NOT_ENABLED", "reason": "missing_premise"}
        evidence = Evidence.make(
            kind=EvidenceKind.RULE_DERIVATION,
            status=EvidenceStatus.VERIFIED,
            subject=rule.conclusion,
            context_id=self.context.context_id,
            rule_id=rule.rule_id,
            premise_atoms=premises,
            supporting_evidence=premise_evidence,
            source="local_transition_checker",
        )
        try:
            result = self._admit_evidence(evidence, accept=True)
        except (ProofCAError, ContextMismatch) as exc:
            return {"applied": False, "accepted": False, "outcome": "DERIVATION_REJECTED", "reason": str(exc)}
        self.metrics.rule_attempts += 1
        return {
            **result,
            "rule_id": rule.rule_id,
            "conclusion": rule.conclusion.key,
            "premises": list(premises),
            "derivation_evidence": evidence.to_dict(),
        }

    def _apply_dependency_request(self, proposal: ActionProposal, payload: Mapping[str, Any]) -> dict[str, Any]:
        dependency = str(payload.get("dependency_cell_id") or "")
        rule_id = str(payload.get("rule_id") or "")
        rule = self.rule_by_id.get(rule_id)
        if rule is None or proposal.target_cell != self.rule_cell_id(rule_id):
            return {"applied": False, "accepted": False, "outcome": "DEPENDENCY_TARGET_MISMATCH", "reason": "retrieval_rule_cell_mismatch"}
        allowed = {self.fact_cell_id(atom) for atom in rule.premises}
        if dependency not in allowed:
            return {"applied": False, "accepted": False, "outcome": "DEPENDENCY_NOT_LOCAL", "reason": "explicit_retrieval_outside_neighborhood"}
        if MAX_RETRIEVALS_PER_PROPOSAL < 1:
            return {"applied": False, "accepted": False, "outcome": "RETRIEVAL_LIMIT", "reason": "retrieval_limit"}
        self.metrics.retrieval_requests += 1
        row = {"cell_id": dependency, "target_cell": proposal.target_cell, "step": self._scheduler_step}
        self.policy_retrievals.append(row)
        self._record_event("dependency_retrieved", row)
        return {"applied": True, "accepted": False, "outcome": "DEPENDENCY_RETRIEVED", "dependency_cell_id": dependency}

    def _validate_cached_external_evidence(
        self,
        evidence: Evidence,
        cached: Mapping[str, Any],
        *,
        target: str,
    ) -> VerificationReceipt:
        """Check a cached receipt before allowing it to affect symbolic state."""

        if evidence.context_id != self.context.context_id or evidence.subject.key != target:
            raise ContextMismatch("cached_external_context_mismatch")
        receipt_raw = dict(evidence.details).get("receipt")
        if not isinstance(receipt_raw, Mapping):
            raise ValidationError("cached_external_receipt_missing")
        receipt = VerificationReceipt.from_mapping(receipt_raw)
        if (
            receipt.context_id != self.context.context_id
            or receipt.target != target
            or receipt.verifier_id != self.context.verifier_id
            or receipt.verifier_version != self.context.verifier_version
            or evidence.source != receipt.verifier_id
            or str(cached.get("status") or "") != receipt.status.value
        ):
            raise ValidationError("cached_external_receipt_not_applicable")
        status_map = {
            VerificationStatus.VERIFIED: (EvidenceKind.EXTERNAL_VERIFICATION, EvidenceStatus.VERIFIED),
            VerificationStatus.COUNTEREXAMPLE: (EvidenceKind.COUNTEREXAMPLE, EvidenceStatus.COUNTEREXAMPLE),
            VerificationStatus.INCONCLUSIVE: (EvidenceKind.INCONCLUSIVE, EvidenceStatus.INCONCLUSIVE),
            VerificationStatus.TRANSIENT_FAILURE: (EvidenceKind.ERROR, EvidenceStatus.TRANSIENT_FAILURE),
            VerificationStatus.ERROR: (EvidenceKind.ERROR, EvidenceStatus.ERROR),
        }
        expected_kind, expected_status = status_map[receipt.status]
        if evidence.kind != expected_kind or evidence.status != expected_status:
            raise ValidationError("cached_external_evidence_status_mismatch")
        if receipt.status in {VerificationStatus.TRANSIENT_FAILURE, VerificationStatus.ERROR}:
            raise ValidationError("cached_external_failure_not_reusable")
        if evidence.authoritative:
            self._validate_authoritative_evidence(evidence)
        return receipt

    def _apply_external_request(self, proposal: ActionProposal, payload: Mapping[str, Any]) -> dict[str, Any]:
        target = str(payload.get("target") or self.context.target or "")
        if target not in self.atom_by_key:
            return {"applied": False, "accepted": False, "outcome": "INVALID_EXTERNAL_TARGET", "reason": "undeclared_target"}
        if proposal.target_cell != self.fact_cell_id(target):
            return {"applied": False, "accepted": False, "outcome": "INVALID_EXTERNAL_TARGET", "reason": "target_cell_mismatch"}
        if not self.context.verifier_id:
            return {"applied": False, "accepted": False, "outcome": "VERIFIER_CONTEXT_MISSING", "reason": "context_has_no_verifier_identity"}
        if self.context.target and target != self.context.target:
            return {"applied": False, "accepted": False, "outcome": "EXTERNAL_TARGET_MISMATCH", "reason": "context_target_mismatch"}
        cache_key = sha256_digest(
            {
                "context_id": self.context.context_id,
                "target": target,
                "candidate_artifact": self.context.candidate_artifact,
                "source_dependencies": list(self.context.source_dependencies),
                "verifier_id": self.context.verifier_id,
                "verifier_version": self.context.verifier_version,
                "verifier_options": _mapping(self.context.verifier_options),
                "axiom_policy": self.context.axiom_policy,
            }
        )
        cached = self.verification_cache.get(cache_key)
        if cached:
            cached_evidence = self.evidence.get(str(cached.get("evidence_id") or ""))
            if cached_evidence is not None:
                try:
                    receipt = self._validate_cached_external_evidence(cached_evidence, cached, target=target)
                except (ProofCAError, ContextMismatch, TypeError, ValueError):
                    self.verification_cache.pop(cache_key, None)
                else:
                    if cached_evidence.authoritative:
                        admitted = self._accept_fact(cached_evidence)
                        return {
                            "applied": False,
                            "accepted": bool(admitted.get("accepted")),
                            "outcome": "EXTERNAL_CACHE_HIT",
                            "cache_hit": True,
                            "verification_event": False,
                            "evidence_id": cached_evidence.evidence_id,
                            "receipt": receipt.to_dict(),
                        }
                    return {
                        "applied": False,
                        "accepted": False,
                        "outcome": "EXTERNAL_CACHE_HIT",
                        "cache_hit": True,
                        "verification_event": False,
                        "evidence_id": cached_evidence.evidence_id,
                        "receipt": receipt.to_dict(),
                    }
        if self.verifier is None:
            return {"applied": False, "accepted": False, "outcome": "VERIFIER_UNAVAILABLE", "reason": "no_verifier_adapter"}
        request = VerificationRequest(
            context_id=self.context.context_id,
            target=target,
            candidate_artifact=self.context.candidate_artifact,
            source_dependencies=self.context.source_dependencies,
            verifier_id=self.context.verifier_id,
            verifier_version=self.context.verifier_version,
            verifier_options=self.context.verifier_options,
            axiom_policy=self.context.axiom_policy,
        )
        self.metrics.verifier_attempts += 1
        try:
            raw = self.verifier.verify(request)
            receipt = raw if isinstance(raw, VerificationReceipt) else VerificationReceipt.from_mapping(raw)
        except Exception as exc:  # adapter failures are explicit non-success outcomes
            self._error = "verifier_error"
            self._record_event("verifier_error", {"target": target, "error": type(exc).__name__})
            return {"applied": False, "accepted": False, "outcome": "VERIFIER_ERROR", "reason": type(exc).__name__}
        if receipt.context_id != self.context.context_id or receipt.target != target:
            return {"applied": False, "accepted": False, "outcome": "RECEIPT_MISMATCH", "reason": "receipt_context_or_target_mismatch"}
        if receipt.verifier_id != self.context.verifier_id or receipt.verifier_version != self.context.verifier_version:
            return {"applied": False, "accepted": False, "outcome": "RECEIPT_MISMATCH", "reason": "receipt_verifier_mismatch"}
        status_map = {
            VerificationStatus.VERIFIED: (EvidenceKind.EXTERNAL_VERIFICATION, EvidenceStatus.VERIFIED, True),
            VerificationStatus.COUNTEREXAMPLE: (EvidenceKind.COUNTEREXAMPLE, EvidenceStatus.COUNTEREXAMPLE, False),
            VerificationStatus.INCONCLUSIVE: (EvidenceKind.INCONCLUSIVE, EvidenceStatus.INCONCLUSIVE, False),
            VerificationStatus.TRANSIENT_FAILURE: (EvidenceKind.ERROR, EvidenceStatus.TRANSIENT_FAILURE, False),
            VerificationStatus.ERROR: (EvidenceKind.ERROR, EvidenceStatus.ERROR, False),
        }
        kind, status, accepts = status_map[receipt.status]
        evidence = Evidence.make(
            kind=kind,
            status=status,
            subject=self.atom_by_key[target],
            context_id=self.context.context_id,
            source=receipt.verifier_id,
            details={"receipt": receipt.to_dict()},
        )
        try:
            stored = self._admit_evidence(evidence, accept=accepts)
        except (ProofCAError, ContextMismatch) as exc:
            return {"applied": False, "accepted": False, "outcome": "EVIDENCE_REJECTED", "reason": str(exc)}
        if receipt.status == VerificationStatus.ERROR:
            self._error = "verifier_reported_error"
        if receipt.status not in {VerificationStatus.TRANSIENT_FAILURE, VerificationStatus.ERROR}:
            self.verification_cache[cache_key] = {
                "evidence_id": evidence.evidence_id,
                "receipt": receipt.to_dict(),
                "status": receipt.status.value,
            }
        return {
            **stored,
            "outcome": "EXTERNAL_VERIFIED" if accepts else f"EXTERNAL_{receipt.status.value.upper()}",
            "receipt": receipt.to_dict(),
            "evidence_id": evidence.evidence_id,
        }

    def _apply_policy_update(self, proposal: ActionProposal, payload: Mapping[str, Any]) -> dict[str, Any]:
        cell = self._cell(proposal.target_cell)
        try:
            activation = payload.get("activation", cell.policy.activation)
            uncertainty = payload.get("uncertainty", cell.policy.uncertainty)
            latent = tuple(float(x) for x in payload.get("latent_features", cell.policy.latent_features))
            updated = PolicyState(
                activation=_finite_unit(activation, field_name="activation"),
                latent_features=latent,
                uncertainty=_finite_unit(uncertainty, field_name="uncertainty"),
                observations=cell.policy.observations + 1,
                last_answer=proposal.policy_answer.to_dict() if proposal.policy_answer else cell.policy.last_answer,
            )
        except (ProofCAError, TypeError, ValueError) as exc:
            return {"applied": False, "accepted": False, "outcome": "POLICY_STATE_REJECTED", "reason": str(exc)}
        runtime = RuntimeState(
            version=cell.runtime.version + 1,
            execution_status="policy_updated",
            pending_messages=len(self.pending_messages),
            resource_ref=cell.runtime.resource_ref,
        )
        self._replace_cell(cell, policy=updated, runtime=runtime)
        return {"applied": True, "accepted": False, "outcome": "POLICY_STATE_UPDATED", "cell_id": cell.cell_id}

    def _fallback_proposal(self, snapshot: LocalSnapshot, rule: Rule) -> ActionProposal:
        row = RuleObservation(
            rule_id=rule.rule_id,
            premise_atoms=tuple(atom.key for atom in rule.premises),
            conclusion=rule.conclusion.key,
            premise_evidence=self._premise_evidence(rule),
            enabled=True,
        )
        answer = PolicyAnswer(
            selected=ActionType.ATTEMPT_RULE.value,
            probabilities=((ActionType.ATTEMPT_RULE.value, 1.0),),
            question_version="deterministic/v1",
            model_id="fairness-fallback",
            fixture=True,
            raw=(("reason", "periodic_fifo_service"),),
        )
        return ActionProposal.make(
            context_id=self.context.context_id,
            target_cell=self.rule_cell_id(rule.rule_id),
            action=ActionType.ATTEMPT_RULE,
            payload={
                "rule_id": row.rule_id,
                "conclusion": row.conclusion,
                "premises": list(row.premise_atoms),
                "premise_evidence": list(row.premise_evidence),
            },
            dependency_fingerprint=snapshot.dependency_fingerprint,
            policy_answer=answer,
            idempotency_key=f"fair:{self._scheduler_step}:{rule.rule_id}",
        )

    def _record_policy_observation(self, cell_id: str, answer: PolicyAnswer) -> None:
        """Persist rich policy metadata without changing symbolic authority."""

        cell = self._cell(cell_id)
        updated = PolicyState(
            activation=cell.policy.activation,
            latent_features=cell.policy.latent_features,
            uncertainty=cell.policy.uncertainty,
            observations=cell.policy.observations + 1,
            last_answer=answer.to_dict(),
        )
        # Policy observations are deliberately not a logical cell-version
        # change: an unrelated neural read must not invalidate a proof or an
        # otherwise applicable logical dependency fingerprint.
        self._replace_cell(cell, policy=updated)
        self._record_event(
            "policy_observation",
            {"cell_id": cell_id, "answer": answer.to_dict(), "authoritative": False},
        )

    def _is_structural_attempt(self, proposal: ActionProposal, rule: Rule) -> bool:
        # A fairness turn may preserve a policy's exact valid proposal, but a
        # malformed attempt must not be allowed to consume every FIFO turn.
        # Evidence IDs are part of the checked local derivation, not merely a
        # shape hint.
        payload = proposal.payload_dict()
        return (
            proposal.action == ActionType.ATTEMPT_RULE
            and proposal.target_cell == ProofGraphCA.rule_cell_id(rule.rule_id)
            and proposal.context_id == self.context.context_id
            and str(payload.get("rule_id") or "") == rule.rule_id
            and str(payload.get("conclusion") or "") == rule.conclusion.key
            and tuple(str(item) for item in payload.get("premises") or ()) == tuple(atom.key for atom in rule.premises)
            and tuple(str(item) for item in payload.get("premise_evidence") or ()) == self._premise_evidence(rule)
            and proposal.dependency_fingerprint == self._dependency_fingerprint(rule)
            and not any(key in payload for key in ("theorem_ok", "lake_ok", "verified"))
        )

    def _choose_rule(self, *, force_fifo: bool) -> Optional[str]:
        if not self.ready_queue:
            return None
        if force_fifo or self._schedule_rng is None or len(self.ready_queue) == 1:
            rule_id = self.ready_queue.popleft()
        else:
            index = self._schedule_rng.randrange(len(self.ready_queue))
            rows = list(self.ready_queue)
            rule_id = rows.pop(index)
            self.ready_queue = deque(rows)
        self.queued_rules.discard(rule_id)
        return rule_id

    def step(self, *, fair_period: int = 3) -> dict[str, Any]:
        """Run one reproducible asynchronous scheduler step."""

        if self._error:
            return {"status": RunStatus.ERROR.value, "reason": self._error}
        if self.pending_messages:
            delivered = self.deliver_pending(limit=1)
            return {"status": "MESSAGE_DELIVERED", **delivered}
        self._scheduler_step += 1
        self.metrics.steps += 1
        period = max(1, int(fair_period))
        force_fifo = period == 1 or self._scheduler_step % period == 0
        rule_id = self._choose_rule(force_fifo=force_fifo)
        if rule_id is None:
            return {"status": self._terminal_status().value, "outcome": "NO_READY_WORK"}
        rule = self.rule_by_id[rule_id]
        if not self._rule_enabled(rule):
            return {"status": "STALE_WORK", "rule_id": rule_id}
        reservation = self.resources.reserve(f"step:{self._scheduler_step}", 1)
        if not reservation.get("reserved"):
            self._enqueue_rule(rule_id, reason="budget_wait")
            return {"status": RunStatus.BUDGET_EXHAUSTED.value, "rule_id": rule_id, "resource": reservation}
        snapshot = self._snapshot(rule)
        self.metrics.policy_calls += 1
        try:
            output = self.policy.propose(snapshot, snapshot.allowed_actions)
            proposal, answer = self._normalize_policy_output(output, snapshot)
        except Exception as exc:
            if force_fifo:
                proposal = self._fallback_proposal(snapshot, rule)
                answer = proposal.policy_answer or PolicyAnswer(selected=ActionType.ATTEMPT_RULE.value)
            else:
                result = self._invalid_policy_result(rule, type(exc).__name__)
                return {"status": "POLICY_REJECTED", **result}
        if force_fifo and not self._is_structural_attempt(proposal, rule):
            proposal = self._fallback_proposal(snapshot, rule)
            answer = proposal.policy_answer or answer
        self._record_policy_observation(snapshot.cell_id, answer)
        result = self.checked_apply(proposal)
        # Any non-authoritative action leaves the enabled symbolic obligation
        # live.  Requeueing here prevents update/retrieval/external tactics
        # from accidentally erasing the only enabled inference; FIFO fairness
        # will eventually replace them with the checked rule action.
        if rule.conclusion.key not in self.accepted_facts:
            self._enqueue_rule(rule_id, reason="retry")
        return {
            "status": result.get("outcome") or "ACTION_APPLIED",
            "rule_id": rule_id,
            "policy_answer": answer.to_dict(),
            "result": result,
        }

    def _terminal_status(self) -> RunStatus:
        if self._error:
            return RunStatus.ERROR
        if self.targets and all(atom.key in self.accepted_facts for atom in self.targets):
            return RunStatus.VERIFIED_COMPLETE
        return RunStatus.QUIESCENT_INCOMPLETE

    def run(
        self,
        *,
        fair_period: int = 3,
        max_steps: Optional[int] = None,
    ) -> dict[str, Any]:
        """Run until verified completion, quiescence, or explicit exhaustion."""

        started = time.perf_counter()
        step_limit = None if max_steps is None else max(0, int(max_steps))
        while self.pending_messages or self.ready_queue:
            if step_limit is not None and self.metrics.steps >= step_limit:
                status = RunStatus.BUDGET_EXHAUSTED
                break
            if self.pending_messages:
                self.deliver_pending(limit=1)
                continue
            try:
                result = self.step(fair_period=fair_period)
            except Exception as exc:
                self._error = type(exc).__name__
                self._record_event("runtime_error", {"error": self._error})
                status = RunStatus.ERROR
                break
            if result.get("status") == RunStatus.ERROR.value:
                status = RunStatus.ERROR
                break
            if result.get("status") == RunStatus.BUDGET_EXHAUSTED.value:
                status = RunStatus.BUDGET_EXHAUSTED
                break
        else:
            status = self._terminal_status()
        if self._error:
            status = RunStatus.ERROR
        report = self.report(status=status, wall_time_ms=(time.perf_counter() - started) * 1000.0)
        return report

    def report(self, *, status: Optional[RunStatus] = None, wall_time_ms: Optional[float] = None) -> dict[str, Any]:
        resolved = status or self._terminal_status()
        return {
            "schema": SCHEMA,
            "status": resolved.value,
            "context_id": self.context.context_id,
            "accepted_facts": sorted(self.accepted_facts),
            "targets": [atom.key for atom in self.targets],
            "target_evidence": {
                atom.key: list(self.fact_evidence.get(atom.key) or []) for atom in self.targets if atom.key in self.accepted_facts
            },
            "n_cells": len(self.cells),
            "n_edges": len(self.edges),
            "ready_queue": list(self.ready_queue),
            "pending_messages": len(self.pending_messages),
            "metrics": self.metrics.to_dict(),
            "resources": self.resources.to_dict(),
            "wall_time_ms": None if wall_time_ms is None else round(float(wall_time_ms), 3),
            "actual_cost": None,
        }

    def evidence_for(self, atom: Atom | str) -> list[Evidence]:
        key = atom.key if isinstance(atom, Atom) else str(atom)
        return [self.evidence[eid] for eid in self.fact_evidence.get(key, ()) if eid in self.evidence]

    def accepted_derivations(self, atom: Atom | str) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.evidence_for(atom)]

    def make_rule_proposal(self, rule_id: str) -> ActionProposal:
        rule = self.rule_by_id.get(str(rule_id))
        if rule is None:
            raise ValidationError("unknown_rule")
        if not self._rule_enabled(rule):
            raise ValidationError("rule_not_enabled")
        return self._fallback_proposal(self._snapshot(rule), rule)

    def make_external_proposal(self, *, target: Optional[Atom | str] = None, target_cell: str = "") -> ActionProposal:
        target_key = target.key if isinstance(target, Atom) else str(target or self.context.target or "")
        if target_key not in self.atom_by_key:
            raise ValidationError("external_target_undeclared")
        cell_id = target_cell or self.fact_cell_id(target_key)
        if cell_id != self.fact_cell_id(target_key):
            raise ValidationError("external_target_cell_mismatch")
        self._cell(cell_id)
        fingerprint = self._external_target_fingerprint(target_key)
        return ActionProposal.make(
            context_id=self.context.context_id,
            target_cell=cell_id,
            action=ActionType.REQUEST_EXTERNAL_VERIFICATION,
            payload={"target": target_key},
            dependency_fingerprint=fingerprint,
            policy_answer=PolicyAnswer(selected=ActionType.REQUEST_EXTERNAL_VERIFICATION.value, model_id="caller"),
        )

    def new_epoch(
        self,
        context: ContextIdentity,
        *,
        assumptions: Optional[Sequence[Atom]] = None,
        targets: Optional[Sequence[Atom]] = None,
    ) -> "ProofGraphCA":
        """Start a new monotonic epoch while retaining old evidence as history."""

        child = ProofGraphCA(
            atoms=self.atoms,
            predicates=self.predicates,
            rules=self.rules,
            assumptions=self.assumptions if assumptions is None else assumptions,
            targets=self.targets if targets is None else targets,
            context=context,
            policy=self.policy,
            verifier=self.verifier,
            # A new logical context does not replenish the authoritative
            # operation ledger.  Carry remaining units forward; ``None`` is
            # the explicit unlimited mode.
            operation_budget=self.resources.remaining,
            neighbor_limit=self.neighbor_limit,
            max_events=self.max_events,
            max_evidence=self.max_evidence,
            schedule_seed=self.schedule_seed,
        )
        child.historical_evidence.update(self.evidence)
        child._record_event(
            "new_epoch",
            {"previous_context_id": self.context.context_id, "historical_evidence": len(self.evidence)},
        )
        return child

    def checkpoint(self) -> dict[str, Any]:
        """Return a bounded checkpoint; evidence is never replaced by text."""

        return {
            "schema": SCHEMA,
            "context": self.context.to_dict(),
            "predicates": dict(self.predicates),
            "atoms": [atom.to_dict() for atom in self.atoms],
            "rules": [rule.to_dict() for rule in self.rules],
            "assumptions": [atom.key for atom in self.assumptions],
            "targets": [atom.key for atom in self.targets],
            "cells": {key: cell.to_dict() for key, cell in self.cells.items()},
            "evidence": [row.to_dict() for row in self.evidence.values()],
            "historical_evidence": [row.to_dict() for row in self.historical_evidence.values()],
            "verification_cache": dict(self.verification_cache),
            "fact_evidence": {key: list(value) for key, value in self.fact_evidence.items()},
            "pending_messages": [row.to_dict() for row in self.pending_messages],
            "delivered_message_ids": sorted(self.delivered_message_ids),
            "ready_queue": list(self.ready_queue),
            "queued_rules": sorted(self.queued_rules),
            "event_log": list(self.event_log[-self.max_events :]),
            "event_sequence": self._event_sequence,
            "scheduler_step": self._scheduler_step,
            "metrics": self.metrics.to_dict(),
            "resources": self.resources.to_dict(),
            "neighbor_limit": self.neighbor_limit,
            "max_events": self.max_events,
            "max_evidence": self.max_evidence,
            "schedule_seed": self.schedule_seed,
        }

    def save_checkpoint(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.checkpoint(), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return destination

    @classmethod
    def from_checkpoint(
        cls,
        payload: Mapping[str, Any] | str | Path,
        *,
        policy: Optional[LocalPolicy] = None,
        verifier: Optional[VerifierAdapter] = None,
    ) -> "ProofGraphCA":
        if isinstance(payload, (str, Path)):
            data = json.loads(Path(payload).read_text(encoding="utf-8"))
        else:
            data = dict(payload)
        if str(data.get("schema") or "") != SCHEMA:
            raise ValidationError("checkpoint_schema_mismatch")
        atoms = tuple(Atom.from_dict(row) for row in data.get("atoms") or ())
        by_key = {atom.key: atom for atom in atoms}
        rules = tuple(Rule.from_dict(row) for row in data.get("rules") or ())
        assumptions = tuple(by_key[str(key)] for key in data.get("assumptions") or ())
        targets = tuple(by_key[str(key)] for key in data.get("targets") or ())
        runtime = cls(
            atoms=atoms,
            predicates=dict(data.get("predicates") or {}),
            rules=rules,
            assumptions=assumptions,
            targets=targets,
            context=ContextIdentity.from_dict(dict(data.get("context") or {})),
            policy=policy,
            verifier=verifier,
            operation_budget=(dict(data.get("resources") or {}).get("operation_limit")),
            neighbor_limit=int(data.get("neighbor_limit") or 8),
            max_events=int(data.get("max_events") or 256),
            max_evidence=int(data.get("max_evidence") or 1024),
            schedule_seed=data.get("schedule_seed"),
            _seed_assumptions=False,
        )
        runtime._restore_checkpoint(data)
        return runtime

    def _restore_checkpoint(self, data: Mapping[str, Any]) -> None:
        # Restore policy/runtime metadata only; symbolic acceptance below is
        # recomputed from evidence and never trusted from the checkpoint.
        for cell_id, raw_cell in dict(data.get("cells") or {}).items():
            if cell_id not in self.cells or not isinstance(raw_cell, Mapping):
                continue
            try:
                raw_policy = dict(raw_cell.get("policy") or {})
                raw_runtime = dict(raw_cell.get("runtime") or {})
                policy = PolicyState(
                    activation=raw_policy.get("activation", 0.5),
                    latent_features=tuple(float(x) for x in raw_policy.get("latent_features") or ()),
                    uncertainty=raw_policy.get("uncertainty", 0.0),
                    observations=int(raw_policy.get("observations") or 0),
                    last_answer=raw_policy.get("last_answer"),
                )
                runtime_state = RuntimeState(
                    version=max(0, int(raw_runtime.get("version") or 0)),
                    execution_status=str(raw_runtime.get("execution_status") or "idle"),
                    pending_messages=max(0, int(raw_runtime.get("pending_messages") or 0)),
                    resource_ref=str(raw_runtime.get("resource_ref") or "operations"),
                )
            except (ProofCAError, TypeError, ValueError):
                continue
            self._replace_cell(self.cells[cell_id], policy=policy, runtime=runtime_state)
        raw_evidence = list(data.get("evidence") or ())
        for raw in raw_evidence[: self.max_evidence]:
            try:
                evidence = Evidence.from_dict(dict(raw))
            except (ProofCAError, TypeError, ValueError):
                continue
            if evidence.context_id == self.context.context_id:
                self.evidence[evidence.evidence_id] = evidence
        for raw in list(data.get("historical_evidence") or ()):
            try:
                evidence = Evidence.from_dict(dict(raw))
            except (ProofCAError, TypeError, ValueError):
                continue
            self.historical_evidence[evidence.evidence_id] = evidence
        # Recompute accepted state from checked evidence.  The checkpoint's
        # accepted set is not trusted as proof.
        self.fact_evidence.clear()
        self.accepted_facts.clear()
        for evidence in sorted(self.evidence.values(), key=lambda row: (row.kind.value, row.evidence_id)):
            if evidence.kind == EvidenceKind.TRUSTED_ASSUMPTION:
                try:
                    self._validate_authoritative_evidence(evidence)
                except (ProofCAError, ContextMismatch):
                    continue
                if evidence.subject.key in {atom.key for atom in self.assumptions}:
                    self.fact_evidence.setdefault(evidence.subject.key, []).append(evidence.evidence_id)
                    self.accepted_facts.add(evidence.subject.key)
        changed = True
        while changed:
            changed = False
            for evidence in sorted(self.evidence.values(), key=lambda row: row.evidence_id):
                if evidence.kind != EvidenceKind.RULE_DERIVATION:
                    continue
                try:
                    self._validate_authoritative_evidence(evidence)
                except (ProofCAError, ContextMismatch):
                    continue
                refs = self.fact_evidence.setdefault(evidence.subject.key, [])
                if evidence.evidence_id not in refs:
                    refs.append(evidence.evidence_id)
                if evidence.subject.key not in self.accepted_facts:
                    self.accepted_facts.add(evidence.subject.key)
                    changed = True
            for evidence in sorted(self.evidence.values(), key=lambda row: row.evidence_id):
                if evidence.kind == EvidenceKind.EXTERNAL_VERIFICATION and evidence.status == EvidenceStatus.VERIFIED:
                    try:
                        self._validate_authoritative_evidence(evidence)
                    except (ProofCAError, ContextMismatch):
                        continue
                    refs = self.fact_evidence.setdefault(evidence.subject.key, [])
                    if evidence.evidence_id not in refs:
                        refs.append(evidence.evidence_id)
                    if evidence.subject.key not in self.accepted_facts:
                        self.accepted_facts.add(evidence.subject.key)
                        changed = True
        for atom in self.atoms:
            cell = self._cell(self.fact_cell_id(atom))
            refs = tuple(self.fact_evidence.get(atom.key) or ())
            symbolic = SymbolicState(
                atom=cell.symbolic.atom,
                rule_id=cell.symbolic.rule_id,
                conclusion=cell.symbolic.conclusion,
                target=cell.symbolic.target,
                dependencies=cell.symbolic.dependencies,
                accepted_derivations=refs,
                obligation=cell.symbolic.obligation,
                target_identity=cell.symbolic.target_identity,
            )
            runtime_state = RuntimeState(
                version=cell.runtime.version + (1 if atom.key in self.accepted_facts and cell.runtime.execution_status != "accepted" else 0),
                execution_status="accepted" if atom.key in self.accepted_facts else cell.runtime.execution_status,
                pending_messages=cell.runtime.pending_messages,
                resource_ref=cell.runtime.resource_ref,
            )
            self._replace_cell(cell, symbolic=symbolic, evidence=EvidenceState(refs), runtime=runtime_state)
        self.delivered_message_ids = {str(x) for x in data.get("delivered_message_ids") or ()}
        raw_messages = []
        for raw in data.get("pending_messages") or ():
            message = LocalMessage(
                message_id=str(raw.get("message_id") or ""),
                context_id=str(raw.get("context_id") or ""),
                source_cell=str(raw.get("source_cell") or ""),
                target_cell=str(raw.get("target_cell") or ""),
                kind=str(raw.get("kind") or ""),
                payload=_pairs(dict(raw.get("payload") or {})),
            )
            if message.context_id == self.context.context_id and message.message_id not in self.delivered_message_ids:
                raw_messages.append(message)
        self.pending_messages = deque(raw_messages)
        self.ready_queue = deque(str(x) for x in data.get("ready_queue") or () if str(x) in self.rule_by_id)
        self.queued_rules = set(self.ready_queue)
        self.event_log = list(data.get("event_log") or ())[-self.max_events :]
        self._event_sequence = int(data.get("event_sequence") or 0)
        self._scheduler_step = int(data.get("scheduler_step") or 0)
        metrics = dict(data.get("metrics") or {})
        self.metrics = RuntimeMetrics(**{name: int(metrics.get(name) or 0) for name in RuntimeMetrics().__dict__})
        self.resources = ResourceLedger.from_dict(dict(data.get("resources") or {}))
        self.verification_cache = {
            str(key): dict(value)
            for key, value in dict(data.get("verification_cache") or {}).items()
            if isinstance(value, Mapping)
        }
        self._set_pending_counts()

    def replay(self, events: Optional[Sequence[Mapping[str, Any]]] = None) -> dict[str, Any]:
        """Replay event/message receipts idempotently without manufacturing proof."""

        rows = list(events if events is not None else self.event_log)
        duplicates = 0
        accepted_seen = 0
        for row in rows:
            event_id = str(row.get("event_id") or "")
            if not event_id:
                continue
            if event_id in {str(item.get("event_id") or "") for item in self.event_log}:
                duplicates += 1
                continue
            if str(row.get("context_id") or "") != self.context.context_id:
                continue
            if str(row.get("type") or "") == "message_delivered":
                payload = row.get("payload")
                if isinstance(payload, Mapping):
                    result = self.deliver_message(payload)
                    if result.get("duplicate"):
                        duplicates += 1
            elif str(row.get("type") or "") == "fact_accepted":
                accepted_seen += 1
        return {"replayed": len(rows) - duplicates, "duplicates": duplicates, "accepted_fact_events_seen": accepted_seen}


def checked_apply(runtime: ProofGraphCA, proposal: ActionProposal | Mapping[str, Any]) -> dict[str, Any]:
    """Functional adapter for callers that prefer the conceptual API."""

    return runtime.checked_apply(proposal)


def run_reasoning(
    *,
    atoms: Sequence[Atom],
    rules: Sequence[Rule],
    assumptions: Sequence[Atom],
    targets: Sequence[Atom] = (),
    **kwargs: Any,
) -> dict[str, Any]:
    """Construct and run one offline runtime."""

    runtime = ProofGraphCA(atoms=atoms, rules=rules, assumptions=assumptions, targets=targets, **kwargs)
    return runtime.run()


__all__ = [
    "ActionProposal",
    "ActionType",
    "Atom",
    "Cell",
    "CellType",
    "ContextIdentity",
    "DependencyEdge",
    "DeterministicPolicy",
    "EdgeType",
    "Evidence",
    "EvidenceKind",
    "EvidenceState",
    "EvidenceStatus",
    "JevPolicyAdapter",
    "LocalMessage",
    "LocalPolicy",
    "LocalSnapshot",
    "NeighborObservation",
    "PolicyAnswer",
    "PolicyOutput",
    "PolicyState",
    "PredicateSignature",
    "ProofCAError",
    "ProofGraphCA",
    "ResourceLedger",
    "Rule",
    "RuleObservation",
    "RuntimeMetrics",
    "RunStatus",
    "SCHEMA",
    "SymbolicState",
    "ValidationError",
    "VerificationReceipt",
    "VerificationRequest",
    "VerificationStatus",
    "checked_apply",
    "canonical_json",
    "run_reasoning",
    "sha256_digest",
]
