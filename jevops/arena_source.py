"""Bounded explicit-term/source correspondence for the Arena replay diagnostic.

This is a deliberately small grammar, not a Lean parser or execution attestation.
It matches a source-derived term against exported Expr data. Only the separate
kernel checker establishes that those data prove the frozen target. Imported
syntax/elaborators and producer-reported costs are NOT authenticated here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re

from .arena import source_hash
from .expr_dag import validate_dag
from .proof_ca import canonical_json

SCHEMA = "jevops-arena-explicit-term/v1"
MAX_BODY_BYTES, MAX_NODES, MAX_DEPTH, MAX_BINDERS = 8192, 256, 32, 64
IDENT = r"[A-Za-z][A-Za-z0-9_']*"
QUALIFIED = IDENT + r"(?:\." + IDENT + r")*"
RESERVED = {"by", "exact", "theorem", "lemma", "fun", "forall", "let", "in", "do",
            "match", "with", "if", "then", "else", "Type", "Sort", "Prop"}


class UnsupportedSource(ValueError):
    """Outside the specified grammar/policy; never silently use a fallback."""


class SourceMismatch(ValueError):
    """An export does not have the claimed explicit source's structure."""


@dataclass(frozen=True)
class ExplicitTermPolicy:
    """Caller-owned constant allowlist, not a claim of audited tactic imports.

    Empty permits only theorem-local parameters/application. Constants are
    fully qualified in generated source and must have no universe arguments
    in the export. No tactic search, implicit argument synthesis or reduction
    is accepted by the structural matcher.
    """
    constants: tuple[str, ...] = ()

    def __post_init__(self):
        if (type(self.constants) is not tuple or len(self.constants) > 64
                or any(type(n) is not str or len(n) > 256 or not re.fullmatch(QUALIFIED, n)
                       or any(p in RESERVED for p in n.split(".")) for n in self.constants)
                or len(set(self.constants)) != len(self.constants)):
            raise ValueError("bounded unique constant names required")

    def record(self):
        return {"schema": SCHEMA, "constants": sorted(self.constants),
                "normalization": "erase-expression-metadata-only",
                "max_body_bytes": MAX_BODY_BYTES, "max_nodes": MAX_NODES,
                "max_depth": MAX_DEPTH, "max_binders": MAX_BINDERS}


@dataclass(frozen=True)
class Term:
    kind: str
    name: str = ""
    children: tuple[Term, ...] = ()


@dataclass(frozen=True)
class SourcePlan:
    source_sha256: str
    binders: tuple[str, ...]
    term: Term


def _binders(statement: str) -> tuple[str, ...]:
    # The trusted statement is NOT reinterpreted as a type here. Identify only
    # explicit, single-name, parenthesized declaration parameters. In particular
    # binders *inside the result type* must not become source-visible locals.
    # Ambiguous syntax, defaults, autoImplicit/section-added binders fail closed.
    head = re.match(r"(?:theorem|lemma) " + QUALIFIED + r"(?= |:)", statement)
    if (not head or len(statement.encode()) > 65_536
            or any(s in statement for s in ("--", "/-", '"', "«", "»", ":="))):
        raise UnsupportedSource("explicit_statement_envelope")
    remaining, names = statement[head.end():].lstrip(), []
    while remaining.startswith("("):
        binder = re.match(r"\((" + IDENT + r") : ", remaining)
        if not binder or binder[1] in RESERVED or binder[1] in names or len(names) >= MAX_BINDERS:
            raise UnsupportedSource("explicit_unique_parameter_required")
        depth, end = 0, None
        for i, char in enumerate(remaining):
            if char == "(": depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None or not remaining[binder.end():end].strip():
            raise UnsupportedSource("unbalanced_or_empty_parameter")
        names.append(binder[1])
        remaining = remaining[end + 1:].lstrip()
    if not remaining.startswith(": ") or not remaining[2:].strip():
        raise UnsupportedSource("explicit_result_type_required")
    return tuple(names)


def parse_source(source: str, statement: str, policy: ExplicitTermPolicy) -> SourcePlan:
    """Parse EXACT canonical bytes: `statement := by exact TERM`.

    TERM ::= REF | (REF TERM+); REF ::= @local | @_root_.allowedConstant
    An application's entire spine stays in ONE group: wrapping partial
    applications in parentheses would let Lean resume implicit insertion.
    No comments, strings, holes, options or extra commands.
    Unsupported valid Lean is intentionally rejected rather than approximated.
    """
    if type(policy) is not ExplicitTermPolicy:
        raise ValueError("explicit typed source policy required")
    prefix = statement + " := by exact "
    if type(source) is not str or not source.startswith(prefix):
        raise UnsupportedSource("canonical_exact_source_required")
    body = source[len(prefix):]
    if len(body.encode()) > MAX_BODY_BYTES:
        raise UnsupportedSource("explicit_term_byte_budget")
    binders = _binders(statement)
    offset = count = 0

    def parse(depth=1):
        nonlocal offset, count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise UnsupportedSource("explicit_term_node_or_depth_budget")
        if body[offset:offset + 1] == "(":
            offset += 1
            fn, height = parse(depth + 1)
            if fn.kind == "app":
                raise UnsupportedSource("explicit_reference_application_head_required")
            arity = 0
            while body[offset:offset + 1] == " ":
                offset += 1
                arg, arg_height = parse(depth + 1)
                arity += 1
                if arity > 1: count += 1  # every implicit AST app node is charged
                height = 1 + max(height, arg_height)
                if count > MAX_NODES or height > MAX_DEPTH:
                    raise UnsupportedSource("explicit_term_node_or_depth_budget")
                fn = Term("app", children=(fn, arg))
            if not arity or body[offset:offset + 1] != ")":
                raise UnsupportedSource("canonical_application_required")
            offset += 1
            return fn, height
        match = re.match(r"@(?:_root_\.)?" + QUALIFIED, body[offset:])
        if not match:
            raise UnsupportedSource("explicit_reference_required")
        offset += match.end()
        name = match[0][1:]
        if name.startswith("_root_."):
            name = name[len("_root_."):]
            if name not in policy.constants:
                raise UnsupportedSource("constant_not_allowlisted")
            return Term("const", name), 1
        if name not in binders:
            raise UnsupportedSource("unknown_local_parameter")
        return Term("local", name), 1

    term, _ = parse()
    if offset != len(body):
        raise UnsupportedSource("trailing_or_noncanonical_source")
    return SourcePlan(source_hash(source), binders, term)


def match_export(plan: SourcePlan, wire: dict, *, environment: str, node_budget: int,
                 toolchain: tuple[str, str]) -> dict:
    """Compare bounded DAG structure, NOT definitional/proof-irrelevant equality.

    The type root is still untrusted until fresh kernel replay. Matching it to
    the trusted reference later prevents a forged type from authorizing facts.
    Work is linear in DAG nodes + the small source plan, never expanded trees.
    """
    validate_dag(wire, environment=environment, node_budget=node_budget, toolchain=toolchain)
    if len(wire["roots"]) != 2:
        raise SourceMismatch("proof_and_type_roots_required")
    rows, peeled, fingerprints = wire["expressions"], [], []
    # Numbering-independent comparison of binder domains. Only scalar metadata
    # may be erased; no reductions, metavariables, proof irrelevance or name
    # resolution against a mutable environment are used.
    for i, row in enumerate(rows):
        if row[0] == "mdata":
            child = int(row[2])
            peeled.append(peeled[child]); fingerprints.append(fingerprints[child])
            continue
        peeled.append(i)
        normalized = list(row)
        for pos in {"app": (1, 2), "lam": (3, 4), "forall": (3, 4),
                    "let": (3, 4, 5), "proj": (3,)}.get(row[0], ()):
            normalized[pos] = fingerprints[int(row[pos])]
        fingerprints.append(hashlib.sha256(canonical_json(normalized).encode()).hexdigest())
    proof, typ = (peeled[int(i)] for i in wire["roots"])
    for name in plan.binders:
        p, t = rows[proof], rows[typ]
        expected_name = [["s", name]]
        if (p[0] != "lam" or t[0] != "forall" or p[1] != expected_name or t[1] != expected_name
                or p[2] != "explicit" or t[2] != "explicit"
                or fingerprints[int(p[3])] != fingerprints[int(t[3])]):
            raise SourceMismatch("declaration_parameter_mismatch")
        proof, typ = peeled[int(p[4])], peeled[int(t[4])]
    local_indices = {name: len(plan.binders) - i - 1 for i, name in enumerate(plan.binders)}
    pending = [(plan.term, proof)]
    while pending:
        term, index = pending.pop()
        row = rows[peeled[index]]
        if term.kind == "local":
            if row != ["bvar", str(local_indices[term.name])]:
                raise SourceMismatch("local_reference_mismatch")
        elif term.kind == "const":
            if row != ["const", [["s", p] for p in term.name.split(".")], []]:
                raise SourceMismatch("explicit_constant_or_universes_mismatch")
        elif term.kind == "app":
            if row[0] != "app":
                raise SourceMismatch("application_mismatch")
            pending.extend(zip(term.children, (int(row[1]), int(row[2]))))
        else:
            raise SourceMismatch("unknown_plan_node")
    return {"schema": SCHEMA, "source_sha256": plan.source_sha256,
            "plan": asdict(plan), "normalization": "erase-expression-metadata-only",
            "structure_matches": True, "execution_attested": False,
            "imported_syntax_audited": False, "metric_integrity_established": False}
