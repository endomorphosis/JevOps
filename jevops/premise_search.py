"""Bounded lexical premise retrieval, never proof or native scope authority.

Adapted from the deterministic selection/exclusion design in ipfs_datasets_py
at ddf6b79467b68159650df81befc288c8553df664 (AGPL-3.0; see ARENA_PROVIDERS.md).
Inputs are an operator-supplied, environment-bound declaration inventory, not
Lean ASTs. Missing or dishonest provenance cannot be repaired by lexical search.
"""
from __future__ import annotations

import re
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from fractions import Fraction

from .arena import content_hash, source_hash
from .proof_trust import _NAME

MAX_PREMISES = 8192
MAX_INDEX_BYTES = 4 * 1024 * 1024
FEATURE_METHOD = "case-sensitive-qualified-and-leaf-identifiers/v2"
SIGNATURE_SCHEMA = "jevops-premise-signature/v1"
_WORDS = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*", re.UNICODE)
_KEYWORDS = frozenset("theorem lemma by exact apply fun forall Prop Type Sort let in have show from".split())


def digest_field(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("exact sha256 required")
    return value


def bounded_int(value: int, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("bounded integer required")
    return value


def premise_name(value: str) -> str:
    if (not isinstance(value, str) or len(value.encode()) > 256 or not _NAME.fullmatch(value)
            or value == "_root_" or value.startswith("_root_.")):
        raise ValueError("plain bounded Lean declaration name required")
    return value


def subgoal_pool(value, initial):
    """Validate/canonicalize a caller-supplied pool; this does not attest scope."""
    if type(value) not in (list, tuple) or not 1 <= len(value) <= 64:
        raise ValueError("one to 64 subgoal premises required")
    names, rows = set(), []
    for row in value:
        if type(row) is not dict or set(row) != {"name", "head"}:
            raise ValueError("invalid subgoal pool fields")
        name, head = premise_name(row["name"]), row["head"]
        if name in names or (head is not None and (type(head) is not str or not 0 < len(head.encode()) <= 1024)):
            raise ValueError("duplicate premise or invalid conclusion head")
        names.add(name)
        rows.append({"name": name, "head": head})
    if not set(initial) <= names:
        raise ValueError("initial nominees outside subgoal pool")
    return sorted(rows, key=lambda row: row["name"])


def subgoal_selection(pool, initial, head, top_k):
    """Deterministic receipt-checking counterpart of the native head lookup.

    Inputs are already validated. One fallback slot when possible, with the
    initial shortlist preceding the remaining canonical pool order in each tier.
    """
    heads = {row["name"]: row["head"] for row in pool}
    order = list(dict.fromkeys([*initial, *heads]))
    matched = [n for n in order if head is not None and heads[n] == head]
    fallback = [n for n in order if n not in matched]
    selected = matched[:top_k - int(bool(fallback) and top_k > 1)]
    return selected + fallback[:top_k - len(selected)]


def _names(values: tuple[str, ...], limit: int) -> None:
    if type(values) is not tuple or len(values) > limit:
        raise ValueError("bounded immutable names required")
    for name in values:
        premise_name(name)
    if len(set(values)) != len(values):
        raise ValueError("duplicate names")


def symbols(text: str) -> frozenset[str]:
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 16384:
        raise ValueError("bounded nonempty goal/type text required")
    # Case matters in Lean. This is deliberately a lexical baseline, not typing.
    # Native pretty-printing qualifies names; source goals often use opened
    # namespaces or dot notation. Leaf overlap is a retrieval hint, not name
    # resolution or permission to replace a fully qualified declaration.
    return frozenset(part for word in _WORDS.findall(text) for part in (word, word.rsplit(".", 1)[-1])
                     if part not in _KEYWORDS and len(part) > 1)


@dataclass(frozen=True)
class ExprHead:
    """Bounded raw Expr spine feature, NOT a type-equivalence certificate."""
    kind: str
    name: str | None = None
    arity: int = 0

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in {"const", "bound", "sort", "other"}:
            raise ValueError("unknown expression head")
        bounded_int(self.arity, 0, 256)
        if self.kind == "const":
            if type(self.name) is not str or not 0 < len(self.name.encode()) <= 1024:
                raise ValueError("bounded constant head required")
        elif self.name is not None:
            raise ValueError("only constant heads have names")


@dataclass(frozen=True)
class PremiseSignature:
    name: str
    binder_kinds: tuple[str, ...]
    binder_heads: tuple[ExprHead, ...]
    conclusion: ExprHead

    def __post_init__(self):
        premise_name(self.name)
        if (type(self.binder_kinds) is not tuple or type(self.binder_heads) is not tuple
                or len(self.binder_kinds) != len(self.binder_heads) or len(self.binder_kinds) > 64
                or any(k not in {"explicit", "implicit", "strict_implicit", "instance"} for k in self.binder_kinds)
                or any(type(h) is not ExprHead for h in self.binder_heads) or type(self.conclusion) is not ExprHead):
            raise ValueError("bounded typed telescope signature required")
        if len(json.dumps(asdict(self), ensure_ascii=False).encode()) > 16384:
            raise ValueError("signature byte budget")

    def to_dict(self):
        return {"schema": SIGNATURE_SCHEMA, "name": self.name, "binder_kinds": list(self.binder_kinds),
                "binder_heads": [asdict(h) for h in self.binder_heads], "conclusion": asdict(self.conclusion)}

    @classmethod
    def from_dict(cls, value):
        if (type(value) is not dict or set(value) != {"schema", "name", "binder_kinds", "binder_heads", "conclusion"}
                or value["schema"] != SIGNATURE_SCHEMA or type(value["binder_kinds"]) is not list
                or type(value["binder_heads"]) is not list):
            raise ValueError("invalid signature schema")
        def head(row):
            if type(row) is not dict or set(row) != {"kind", "name", "arity"}:
                raise ValueError("invalid head schema")
            return ExprHead(**row)
        return cls(value["name"], tuple(value["binder_kinds"]), tuple(head(h) for h in value["binder_heads"]),
                   head(value["conclusion"]))


@dataclass(frozen=True)
class Premise:
    name: str
    type_text: str
    origin: str
    split: str = "library"
    aliases: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        premise_name(self.name)
        symbols(self.type_text)
        if (not isinstance(self.origin, str) or not 1 <= len(self.origin.encode()) <= 256
                or self.split not in ("library", "train", "validation", "canary", "test")):
            raise ValueError("explicit origin and known split required")
        _names(self.aliases, 32)
        _names(self.dependencies, 256)
        if self.name in self.aliases:
            raise ValueError("self alias")


@dataclass(frozen=True)
class PremiseScope:
    """Trusted caller's inventory at the target's pre-declaration environment.

    Hash equality is binding only, NOT attestation that names/provenance are true.
    Excluded origins must include all protected families, not just exact names.
    """
    record_sha256: str
    environment_sha256: str
    available_names: tuple[str, ...]
    excluded_names: tuple[str, ...] = ()
    excluded_origins: tuple[str, ...] = ()

    def __post_init__(self):
        digest_field(self.record_sha256)
        digest_field(self.environment_sha256)
        _names(self.available_names, MAX_PREMISES)
        _names(self.excluded_names, MAX_PREMISES)
        if (type(self.excluded_origins) is not tuple or len(self.excluded_origins) > MAX_PREMISES
                or any(not isinstance(s, str) or not 1 <= len(s.encode()) <= 256 for s in self.excluded_origins)
                or len(set(self.excluded_origins)) != len(self.excluded_origins)):
            raise ValueError("bounded unique excluded origins required")


class PremiseIndex:
    """Precomputed inverted index; a query never silently truncates its scan."""

    def __init__(self, premises: tuple[Premise, ...], *, environment_sha256: str,
                 signatures: tuple[PremiseSignature, ...] = ()):
        self.environment_sha256 = digest_field(environment_sha256)
        if type(premises) is not tuple or len(premises) > MAX_PREMISES or any(type(p) is not Premise for p in premises):
            raise ValueError("bounded typed premise inventory required")
        # Account for metadata as well as type text before constructing the index.
        size = sum(len(p.type_text.encode()) + len(p.origin.encode()) + len(p.name.encode())
                   + sum(len(n.encode()) for n in (*p.aliases, *p.dependencies)) for p in premises)
        if size > MAX_INDEX_BYTES:
            raise ValueError("premise inventory byte budget")
        self.entries, self.owners, self.features = {}, {}, {}
        postings, dependents = defaultdict(set), defaultdict(set)
        for p in sorted(premises, key=lambda p: p.name):
            for name in (p.name, *p.aliases):
                if name in self.owners:
                    raise ValueError("duplicate declaration or alias identity")
                self.owners[name] = p.name
            self.entries[p.name] = p
            features = symbols(p.type_text)
            self.features[p.name] = features
            for feature in features:
                postings[feature].add(p.name)
            for dependency in p.dependencies:
                dependents[dependency].add(p.name)
        self.postings = {key: tuple(sorted(names)) for key, names in postings.items()}
        self.dependents = dependents
        if (type(signatures) is not tuple or len(signatures) > len(premises)
                or any(type(s) is not PremiseSignature or s.name not in self.entries for s in signatures)
                or len({s.name for s in signatures}) != len(signatures)):
            raise ValueError("unique in-inventory signatures required")
        self.signatures = {s.name: s for s in sorted(signatures, key=lambda s: s.name)}
        if size + sum(len(json.dumps(s.to_dict(), ensure_ascii=False).encode()) for s in signatures) > MAX_INDEX_BYTES:
            raise ValueError("premise inventory byte budget including signatures")
        heads, flexible = defaultdict(set), set()
        for s in signatures:
            if s.conclusion.kind == "const":
                heads[s.conclusion.name].add(s.name)
            else:
                flexible.add(s.name)
        self.head_postings = {k: tuple(sorted(v)) for k, v in heads.items()}
        self.flexible_heads = tuple(sorted(flexible))
        identity = {"schema": "jevops-premise-index/v1",
            "feature_method": FEATURE_METHOD,
            "environment_sha256": self.environment_sha256,
            "premises": [asdict(p) for p in self.entries.values()]}
        if signatures:
            identity.update(schema="jevops-premise-index/v2", signatures=[s.to_dict() for s in self.signatures.values()])
        self.index_sha256 = content_hash(identity)

    def _exclusions(self, target: str, scope: PremiseScope) -> dict:
        """One shared scope boundary for lexical queries and native search pools."""
        premise_name(target)
        if type(scope) is not PremiseScope or scope.environment_sha256 != self.environment_sha256:
            raise ValueError("premise environment mismatch")
        available, origins = set(scope.available_names), set(scope.excluded_origins)
        denied = {target, *scope.excluded_names}
        reasons = {}
        for name, p in self.entries.items():
            if p.split not in ("library", "train") or p.origin in origins:
                reasons[name] = "heldout_or_excluded_origin"
            elif name not in available or any(d not in available for d in p.dependencies):
                reasons[name] = "not_in_scope"
            if name in reasons:
                denied.update((name, *p.aliases))
        # Propagate through alias groups and dependency edges, including unknown
        # excluded names. A renamed wrapper around a protected proof stays out.
        queue = deque(sorted(denied))
        while queue:
            name = queue.popleft()
            owner = self.owners.get(name)
            affected = set(self.dependents.get(name, ()))
            if owner is not None:
                affected.add(owner)
            for affected_name in sorted(affected):
                reasons.setdefault(affected_name, "excluded_alias_or_dependency")
                p = self.entries[affected_name]
                for sibling in (p.name, *p.aliases):
                    if sibling not in denied:
                        denied.add(sibling)
                        queue.append(sibling)
        return reasons

    def scoped_pool(self, *, target: str, scope: PremiseScope, max_pool=64) -> dict:
        """Bounded setup work, not a hidden query over the whole Lean library.

        Reject pool overflow rather than silently omitting eligible declarations.
        Raw heads are retrieval hints, never type-equivalence certificates.
        """
        bounded_int(max_pool, 0, 64)
        reasons = self._exclusions(target, scope)
        names = [n for n in self.entries if n not in reasons]
        overflow = len(names) > max_pool
        entries = []
        if not overflow:
            for name in names:
                sig = self.signatures.get(name)
                entries.append({"name": name, "head": sig.conclusion.name if sig and
                                sig.conclusion.kind == "const" else None})
        return {"schema": "jevops-subgoal-pool/v1", "status": "POOL_BUDGET" if overflow else "READY",
            "index_sha256": self.index_sha256, "scope_sha256": content_hash(asdict(scope)),
            "target": target, "max_pool": max_pool, "entries_scanned": len(self.entries),
            "excluded_count": len(reasons), "eligible_count": len(names), "entries": entries,
            "proof_verified": False}

    def rank(self, goal: str, *, target: str, scope: PremiseScope, top_k: int = 4, max_scan: int = 512,
             conclusion: ExprHead | None = None) -> dict:
        bounded_int(top_k, 1, 8)
        bounded_int(max_scan, 1, MAX_PREMISES)
        if conclusion is not None and type(conclusion) is not ExprHead:
            raise ValueError("typed conclusion head required")
        reasons = self._exclusions(target, scope)
        query = symbols(goal)
        seen = set()
        overflow = False
        for feature in sorted(query):
            for name in self.postings.get(feature, ()):
                seen.add(name)
                if len(seen) > max_scan:
                    overflow = True
                    break
            if overflow:
                break
        if conclusion is not None and not overflow:
            for name in (*self.head_postings.get(conclusion.name, ()), *self.flexible_heads):
                seen.add(name)
                if len(seen) > max_scan:
                    overflow = True
                    break
        result = {"schema": "jevops-premise-ranking/v1", "index_sha256": self.index_sha256,
            "feature_method": FEATURE_METHOD,
            "scope_sha256": content_hash(asdict(scope)), "goal_sha256": source_hash(goal),
            "target": target, "top_k": top_k, "max_scan": max_scan, "considered": len(seen),
            "status": "SCAN_BUDGET" if overflow else "RANKED", "matches": [], "excluded": [],
            "proof_verified": False}
        if conclusion is not None:
            result.update(schema="jevops-premise-ranking/v2", feature_method="raw-conclusion-head-priority/v1",
                          conclusion=asdict(conclusion), fallback_slots=int(top_k > 1))
        if overflow:
            return result
        scored = []
        for name in sorted(seen):
            if name in reasons:
                result["excluded"].append({"name": name, "reason": reasons[name]})
                continue
            features = self.features[name]
            score = Fraction(len(query & features), len(query | features))
            scored.append((score, name))
        scored.sort(key=lambda row: (-row[0], row[1]))
        if conclusion is not None:
            def tier(row):
                sig = self.signatures.get(row[1])
                if sig is None or sig.conclusion.kind != "const" or conclusion.kind != "const":
                    return 1
                return 0 if sig.conclusion.name == conclusion.name else 2
            matched = [r for r in scored if tier(r) == 0]
            fallback = sorted((r for r in scored if tier(r) != 0), key=lambda r: (tier(r), -r[0], r[1]))
            # Reserve one fallback when possible; mismatching raw heads may be
            # definitionally equal, generic, or useful for a later forward step.
            selected = matched[:top_k - int(bool(fallback) and top_k > 1)]
            selected += fallback[:top_k - len(selected)]
            scored = selected
        result["matches"] = [{"name": name, "score_numerator": score.numerator,
            "score_denominator": score.denominator, "premise_sha256": content_hash(asdict(self.entries[name]))}
            for score, name in scored[:top_k]]
        if conclusion is not None:
            for row in result["matches"]:
                row["head_priority"] = tier((None, row["name"]))
        return result
