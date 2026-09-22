"""Bounded classical propositional IR and independently checkable reductions.

This module does not parse arbitrary Lean or certify Lean proofs. It implements
finite truth-table semantics, Quine–McCluskey (K-map) minimization, reduced ordered
decision diagrams, and finite-state invariant obligations. Context assumptions
are explicit; an inconsistent context is reported as vacuous, never as evidence
for an unconditional rewrite. Lean must check any generated proof separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
import re
from typing import Any, Mapping, Sequence

SCHEMA = "jevops-propositional-ir/v1"
MAX_VARIABLES = 8
MAX_NODES = 256
MAX_DEPTH = 48
_NAME = re.compile(r"[^\W\d]\w*'*\Z", re.UNICODE)
_TOKEN = re.compile(r"\s*(<->|->|&&|\|\||[()¬!∧∨→↔⊕]|[^\W\d]\w*'*)", re.UNICODE)
_ARITY = {"var": 0, "true": 0, "false": 0, "not": 1, "and": 2, "or": 2,
          "imp": 2, "iff": 2, "xor": 2}
_BINARY = {"↔": (1, "iff"), "<->": (1, "iff"), "→": (2, "imp"), "->": (2, "imp"),
           "∨": (3, "or"), "||": (3, "or"), "⊕": (4, "xor"), "∧": (5, "and"), "&&": (5, "and")}


class LogicLimit(ValueError):
    """The requested finite analysis exceeds a declared resource bound."""


@dataclass(frozen=True)
class Formula:
    op: str
    args: tuple["Formula", ...] = ()
    name: str = ""

    def __post_init__(self) -> None:
        if self.op not in _ARITY or not isinstance(self.args, tuple) or len(self.args) != _ARITY[self.op]:
            raise ValueError("invalid propositional operation/arity")
        if any(not isinstance(arg, Formula) for arg in self.args):
            raise ValueError("formula children must be Formula values")
        if self.op == "var":
            if not _NAME.fullmatch(self.name) or self.name in {"True", "False", "true", "false"}:
                raise ValueError("invalid proposition identifier")
        elif self.name:
            raise ValueError("only variables have names")

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, **({"name": self.name} if self.name else {}),
                **({"args": [a.to_dict() for a in self.args]} if self.args else {})}


TRUE, FALSE = Formula("true"), Formula("false")


def parse_formula(text: str) -> Formula:
    """Parse *only* bare propositional atoms and explicit logical connectives."""
    text = str(text).strip()
    if len(text) > 8192:
        raise LogicLimit("formula character budget")
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            raise ValueError(f"unsupported formula syntax at {pos}")
        tokens.append(match.group(1))
        pos = match.end()
        if len(tokens) > MAX_NODES * 3:
            raise LogicLimit("formula token budget")
    cursor = 0

    def expr(min_precedence: int = 0, depth: int = 0) -> Formula:
        nonlocal cursor
        if depth > MAX_DEPTH:
            raise LogicLimit("formula depth budget")
        if cursor >= len(tokens):
            raise ValueError("missing formula operand")
        token = tokens[cursor]
        cursor += 1
        if token in {"¬", "!"}:
            left = Formula("not", (expr(6, depth + 1),))
        elif token == "(":
            left = expr(0, depth + 1)
            if cursor >= len(tokens) or tokens[cursor] != ")":
                raise ValueError("unbalanced parentheses")
            cursor += 1
        elif token in {"True", "true", "False", "false"}:
            left = TRUE if token.lower() == "true" else FALSE
        else:
            left = Formula("var", name=token)
        while cursor < len(tokens) and tokens[cursor] in _BINARY:
            precedence, op = _BINARY[tokens[cursor]]
            if precedence < min_precedence:
                break
            cursor += 1
            right = expr(precedence if op == "imp" else precedence + 1, depth + 1)
            left = Formula(op, (left, right))
        return left

    result = expr()
    if cursor != len(tokens):
        raise ValueError("unconsumed formula syntax")
    variables(result)  # validates node, depth and atom bounds
    return result


def formula_from_ir(value: Mapping[str, Any]) -> Formula:
    count = 0

    def read(row: Mapping[str, Any], depth: int) -> Formula:
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise LogicLimit("formula IR budget")
        if not isinstance(row, Mapping) or set(row) - {"op", "args", "name"}:
            raise ValueError("invalid formula IR")
        children = row.get("args", [])
        if not isinstance(children, (list, tuple)) or len(children) > 2:
            raise ValueError("invalid formula children")
        return Formula(str(row.get("op", "")), tuple(read(a, depth + 1) for a in children), str(row.get("name", "")))

    result = read(value, 0)
    variables(result)
    return result


def variables(*formulas: Formula) -> tuple[str, ...]:
    names: set[str] = set()
    stack = [(f, 0) for f in formulas]
    count = 0
    while stack:
        f, depth = stack.pop()
        count += 1
        if count > MAX_NODES * max(1, len(formulas)) or depth > MAX_DEPTH:
            raise LogicLimit("formula node/depth budget")
        if f.op == "var":
            names.add(f.name)
        stack.extend((a, depth + 1) for a in f.args)
    if len(names) > MAX_VARIABLES:
        raise LogicLimit(f"at most {MAX_VARIABLES} Boolean variables")
    return tuple(sorted(names))


def evaluate(formula: Formula, assignment: Mapping[str, bool]) -> bool:
    if formula.op == "var":
        value = assignment[formula.name]
        if not isinstance(value, bool):
            raise ValueError("Boolean assignments required")
        return value
    if formula.op in {"true", "false"}:
        return formula.op == "true"
    a = evaluate(formula.args[0], assignment)
    if formula.op == "not":
        return not a
    b = evaluate(formula.args[1], assignment)
    return {"and": a and b, "or": a or b, "imp": not a or b, "iff": a == b, "xor": a != b}[formula.op]


def assignment_for(index: int, names: Sequence[str]) -> dict[str, bool]:
    return {name: bool(index & (1 << bit)) for bit, name in enumerate(names)}


def render_formula(f: Formula) -> str:
    if f.op == "var":
        return f.name
    if f.op in {"true", "false"}:
        return "True" if f.op == "true" else "False"
    if f.op == "not":
        return "¬ " + render_formula(f.args[0])
    a, b = map(render_formula, f.args)
    if f.op == "xor":
        return f"¬ ({a} ↔ {b})"
    op = {"and": "∧", "or": "∨", "imp": "→", "iff": "↔"}[f.op]
    return f"({a} {op} {b})"


def _join(op: str, items: Sequence[Formula]) -> Formula:
    if not items:
        return TRUE if op == "and" else FALSE
    # Balanced trees avoid a linear-depth blowup in large DNF/CNF outputs.
    if len(items) == 1:
        return items[0]
    mid = len(items) // 2
    return Formula(op, (_join(op, items[:mid]), _join(op, items[mid:])))


def simplify_formula(f: Formula) -> Formula:
    """Constant folding, AC/idempotence, absorption and complement laws."""
    if not f.args:
        return f
    args = tuple(simplify_formula(a) for a in f.args)
    if f.op == "not":
        a = args[0]
        if a in (TRUE, FALSE):
            return FALSE if a == TRUE else TRUE
        return a.args[0] if a.op == "not" else Formula("not", args)
    a, b = args
    if f.op in {"iff", "xor"}:
        if a == b:
            return TRUE if f.op == "iff" else FALSE
        if a in (TRUE, FALSE):
            return simplify_formula(b if (a == TRUE) == (f.op == "iff") else Formula("not", (b,)))
        if b in (TRUE, FALSE):
            return simplify_formula(Formula(f.op, (b, a)))
        return Formula(f.op, args)
    if f.op == "imp":
        return simplify_formula(Formula("or", (Formula("not", (a,)), b)))
    op = f.op
    items: list[Formula] = []

    def flatten(item: Formula) -> None:
        if item.op == op:
            for child in item.args:
                flatten(child)
        else:
            items.append(item)

    for arg in args:
        flatten(arg)
    identity, annihilator = (TRUE, FALSE) if op == "and" else (FALSE, TRUE)
    terms = set(items) - {identity}
    if annihilator in terms or any(Formula("not", (t,)) in terms for t in terms):
        return annihilator
    dual = "or" if op == "and" else "and"

    def factors(t: Formula) -> set[Formula]:
        return factors(t.args[0]) | factors(t.args[1]) if t.op == dual else {t}

    terms = {t for t in terms if not any(t != u and factors(u) < factors(t) for u in terms)}
    return _join(op, sorted(terms, key=render_formula))


def to_nnf(f: Formula, negate: bool = False, *, expansion_budget: int = 2048) -> Formula:
    """Push negations inward, bounding the exponential expansion of parity."""
    variables(f)
    remaining = min(4096, max(0, int(expansion_budget)))

    def visit(node: Formula, neg: bool) -> Formula:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise LogicLimit("NNF expansion budget")
        if node.op == "not":
            return visit(node.args[0], not neg)
        if node.op in {"var", "true", "false"}:
            return simplify_formula(Formula("not", (node,))) if neg else node
        a, b = node.args
        if node.op == "imp":
            return visit(Formula("or", (Formula("not", (a,)), b)), neg)
        if node.op in {"iff", "xor"}:
            different = (node.op == "xor") != neg
            return simplify_formula(_join("or", [
                _join("and", [visit(a, False), visit(b, different)]),
                _join("and", [visit(a, True), visit(b, not different)]),
            ]))
        op = {"and": "or", "or": "and"}[node.op] if neg else node.op
        return simplify_formula(Formula(op, (visit(a, neg), visit(b, neg))))

    return visit(f, negate)


def check_equivalent(left: Formula, right: Formula, *, assumptions: Formula = TRUE) -> dict[str, Any]:
    names = variables(left, right, assumptions)
    checked = 0
    for index in range(1 << len(names)):
        assignment = assignment_for(index, names)
        if not evaluate(assumptions, assignment):
            continue
        checked += 1
        if evaluate(left, assignment) != evaluate(right, assignment):
            return {"equivalent": False, "counterexample": assignment, "vacuous": False}
    return {"equivalent": True, "counterexample": None, "vacuous": checked == 0}


def _cover(on: set[int], dc: set[int], n: int, budget: int) -> tuple[list[tuple[int, int]], bool]:
    """Prime implicants plus bounded exact minimum (terms, literals) cover."""
    if not on:
        return [], True
    level = {(m, 0) for m in on | dc}
    primes: set[tuple[int, int]] = set()
    while level:
        used: set[tuple[int, int]] = set()
        merged: set[tuple[int, int]] = set()
        for bits, mask in sorted(level):
            for bit in range(n):
                flag = 1 << bit
                neighbor = (bits ^ flag, mask)
                if not mask & flag and neighbor in level:
                    used.update(((bits, mask), neighbor))
                    merged.add((bits & ~flag, mask | flag))
        primes.update(level - used)
        level = merged
    cubes = sorted(c for c in primes if any(m & ~c[1] == c[0] for m in on))
    covered = [frozenset(m for m in on if m & ~mask == bits) for bits, mask in cubes]

    def cost(indices: Sequence[int]) -> tuple[int, int, tuple[int, ...]]:
        return len(indices), sum(n - cubes[i][1].bit_count() for i in indices), tuple(sorted(indices))

    # A valid greedy cover is always available if exact search hits its cap.
    remaining = set(on)
    best: list[int] = []
    while remaining:
        i = min(range(len(cubes)), key=lambda j: (-len(covered[j] & remaining), n - cubes[j][1].bit_count(), j))
        best.append(i)
        remaining.difference_update(covered[i])
    calls = 0
    exhausted = False

    def search(remaining: frozenset[int], chosen: tuple[int, ...]) -> None:
        nonlocal best, calls, exhausted
        if calls >= budget:
            exhausted = True
            return
        calls += 1
        if not remaining:
            if cost(chosen) < cost(best):
                best = list(chosen)
            return
        if len(chosen) >= len(best):
            return
        m = min(remaining, key=lambda k: sum(k in c for c in covered))
        options = [i for i, c in enumerate(covered) if m in c]
        options.sort(key=lambda i: (-len(covered[i] & remaining), n - cubes[i][1].bit_count(), i))
        for i in options:
            search(remaining - covered[i], (*chosen, i))
            if exhausted:
                break

    search(frozenset(on), ())
    return [cubes[i] for i in sorted(best)], not exhausted


def minimize_formula(f: Formula, *, assumptions: Formula = TRUE, form: str = "dnf", search_budget: int = 20_000) -> dict[str, Any]:
    """K-map-equivalent cube minimization; exactness refers to two-level cost."""
    if form not in {"dnf", "cnf"}:
        raise ValueError("form must be dnf or cnf")
    names = variables(f, assumptions)
    on, dc = set(), set()
    for index in range(1 << len(names)):
        assignment = assignment_for(index, names)
        if not evaluate(assumptions, assignment):
            dc.add(index)
        elif evaluate(f, assignment) == (form == "dnf"):
            on.add(index)
    cubes, optimal = _cover(on, dc, len(names), min(100_000, max(0, int(search_budget))))
    terms = []
    for bits, mask in cubes:
        literals = []
        for bit, name in enumerate(names):
            if not mask & (1 << bit):
                atom = Formula("var", name=name)
                positive = bool(bits & (1 << bit)) == (form == "dnf")
                literals.append(atom if positive else Formula("not", (atom,)))
        terms.append(_join("and" if form == "dnf" else "or", literals))
    reduced = simplify_formula(_join("or" if form == "dnf" else "and", terms))
    # Compare all care assignments independently of the cover implementation.
    # Outputs may exceed the input AST size budget (e.g. parity in DNF).
    equivalent = all(not evaluate(assumptions, a) or evaluate(f, a) == evaluate(reduced, a)
                     for a in (assignment_for(i, names) for i in range(1 << len(names))))
    if not equivalent:
        raise AssertionError("Boolean minimization failed its equivalence check")
    return {"schema": SCHEMA, "form": form, "formula": reduced.to_dict(), "lean": render_formula(reduced),
            "assumptions": render_formula(assumptions), "equivalent_on_context": equivalent,
            "vacuous": len(dc) == 1 << len(names), "optimal_two_level": optimal,
            "cost": {"terms": len(cubes), "literals": sum(len(names) - mask.bit_count() for _, mask in cubes)},
            "variables": list(names), "dont_care_count": len(dc)}


def decision_diagram(f: Formula) -> dict[str, Any]:
    """Reduced ordered BDD using Shannon cofactors and shared subgraphs."""
    names = variables(f)
    table = tuple(evaluate(f, assignment_for(i, names)) for i in range(1 << len(names)))
    unique: dict[tuple[int, int, int], int] = {}
    nodes: list[dict[str, Any]] = []

    def build(values: tuple[bool, ...], level: int) -> int:
        if all(v == values[0] for v in values):
            return int(values[0])
        low, high = build(values[::2], level + 1), build(values[1::2], level + 1)
        if low == high:
            return low
        key = (level, low, high)
        if key not in unique:
            ident = len(nodes) + 2
            unique[key] = ident
            nodes.append({"id": ident, "variable": names[level], "low": low, "high": high})
        return unique[key]

    root = build(table, 0)
    return {"root": root, "nodes": nodes, "order": list(names),
            "independent_variables": sorted(set(names) - {node["variable"] for node in nodes})}


def karnaugh_map(f: Formula, *, assumptions: Formula = TRUE) -> dict[str, Any]:
    names = variables(f, assumptions)
    if len(names) > 6:
        raise LogicLimit("K-map display supports at most six variables")
    nrows = len(names) // 2
    rows = [i ^ (i >> 1) for i in range(1 << nrows)]
    cols = [i ^ (i >> 1) for i in range(1 << (len(names) - nrows))]
    cells = []
    for row in rows:
        line = []
        for col in cols:
            a = assignment_for(row | (col << nrows), names)
            line.append(int(evaluate(f, a)) if evaluate(assumptions, a) else None)
        cells.append(line)
    return {"row_variables": list(names[:nrows]), "column_variables": list(names[nrows:]),
            "row_gray_codes": rows, "column_gray_codes": cols, "cells": cells}


def detect_invariants(constraint: Formula) -> dict[str, Any]:
    """Entailed literals, equal/opposite atoms, and redundant conjuncts."""
    names = variables(constraint)
    models = [assignment_for(i, names) for i in range(1 << len(names))]
    models = [a for a in models if evaluate(constraint, a)]
    if not models:
        return {"satisfiable": False, "vacuous": True, "forced": {}, "relations": [], "redundant_conjuncts": []}
    forced = {name: models[0][name] for name in names if all(a[name] == models[0][name] for a in models)}
    relations = [{"left": a, "right": b, "relation": "equal" if models[0][a] == models[0][b] else "opposite"}
                 for a, b in combinations(names, 2) if all((m[a] == m[b]) == (models[0][a] == models[0][b]) for m in models)]
    conjuncts: list[Formula] = []

    def split(f: Formula) -> None:
        if f.op == "and":
            for a in f.args:
                split(a)
        else:
            conjuncts.append(f)

    split(constraint)
    kept = list(conjuncts)
    removed = []
    # Sequential elimination is essential: removing both duplicate constraints
    # independently would incorrectly turn p ∧ p into True.
    for index in reversed(range(len(kept))):
        rest = _join("and", kept[:index] + kept[index + 1:])
        if all(not evaluate(rest, a) or evaluate(kept[index], a)
               for a in (assignment_for(i, names) for i in range(1 << len(names)))):
            removed.append(render_formula(kept.pop(index)))
    return {"satisfiable": True, "vacuous": False, "forced": forced, "relations": relations,
            "redundant_conjuncts": removed, "reduced": render_formula(_join("and", kept))}


def check_inductive_invariant(invariant: Formula, initial: Formula, transition: Formula,
                              state_pairs: Mapping[str, str]) -> dict[str, Any]:
    """Check initiation and one-step preservation for an explicit Boolean system."""
    current, future = set(state_pairs), set(state_pairs.values())
    if not current or len(future) != len(current) or current & future:
        raise ValueError("state mapping must be injective with disjoint current/next names")
    for name in current | future:
        Formula("var", name=name)
    if not set(variables(invariant, initial)) <= current or not set(variables(transition)) <= current | future:
        raise ValueError("undeclared state variable")
    names = tuple(sorted(current | future))
    if len(names) > MAX_VARIABLES:
        raise LogicLimit("transition variable budget")
    initiation = preservation = None
    initial_count = step_count = 0
    for index in range(1 << len(names)):
        a = assignment_for(index, names)
        inv = evaluate(invariant, a)
        if evaluate(initial, a):
            initial_count += 1
            if not inv and initiation is None:
                initiation = a
        if inv and evaluate(transition, a):
            step_count += 1
            after = {name: a[nxt] for name, nxt in state_pairs.items()}
            if not evaluate(invariant, after) and preservation is None:
                preservation = a
    return {"inductive": initiation is None and preservation is None,
            "initiation_counterexample": initiation, "preservation_counterexample": preservation,
            "initial_satisfiable": initial_count > 0, "preservation_vacuous": step_count == 0,
            "authority": "finite_boolean_semantics"}


@lru_cache(maxsize=128)
def _analyze(text: str) -> dict[str, Any]:
    f = parse_formula(text)
    try:
        nnf, nnf_reason = render_formula(to_nnf(f)), None
    except LogicLimit as exc:
        nnf, nnf_reason = None, str(exc)
    return {"schema": SCHEMA, "supported": True, "semantics": "classical_propositional",
            "ir": f.to_dict(), "variables": list(variables(f)),
            "algebraic": render_formula(simplify_formula(f)), "nnf": nnf, "nnf_limit": nnf_reason,
            "dnf": minimize_formula(f), "cnf": minimize_formula(f, form="cnf"),
            "bdd": decision_diagram(f), "invariants": detect_invariants(f)}


def analyze_formula(text: str) -> dict[str, Any]:
    # Return detached data: a consumer must not mutate a cached analysis.
    from copy import deepcopy
    try:
        return deepcopy(_analyze(str(text)))
    except (ValueError, RecursionError) as exc:
        return {"schema": SCHEMA, "supported": False, "reason": str(exc)}
