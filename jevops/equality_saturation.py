"""Bounded, binder-free propositional e-graphs; never Lean proof authority.

Congruence closure shares equivalent subexpressions. Extraction minimizes an
explicit local cost over the explored graph, not all Lean proofs. Lean must
reconstruct/check an equivalence before any replacement is admitted.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .logic_ir import Formula, LogicLimit, MAX_DEPTH, MAX_NODES, render_formula, simplify_formula, variables

# Pattern variables range over complete propositional e-classes, never binders.
X, Y, Z = "?x", "?y", "?z"
RULES = (
    ("and_true", ("and", X, ("true",)), X),
    ("or_false", ("or", X, ("false",)), X),
    ("and_false", ("and", X, ("false",)), ("false",)),
    ("or_true", ("or", X, ("true",)), ("true",)),
    ("not_true", ("not", ("true",)), ("false",)),
    ("not_false", ("not", ("false",)), ("true",)),
    ("double_negation", ("not", ("not", X)), X),
    ("and_idempotence", ("and", X, X), X),
    ("or_idempotence", ("or", X, X), X),
    ("and_complement", ("and", X, ("not", X)), ("false",)),
    ("or_complement", ("or", X, ("not", X)), ("true",)),
    ("and_commute", ("and", X, Y), ("and", Y, X)),
    ("or_commute", ("or", X, Y), ("or", Y, X)),
    ("and_associate", ("and", ("and", X, Y), Z), ("and", X, ("and", Y, Z))),
    ("or_associate", ("or", ("or", X, Y), Z), ("or", X, ("or", Y, Z))),
    ("and_absorb", ("and", X, ("or", X, Y)), X),
    ("or_absorb", ("or", X, ("and", X, Y)), X),
    ("and_distribute", ("and", X, ("or", Y, Z)), ("or", ("and", X, Y), ("and", X, Z))),
    ("or_distribute", ("or", X, ("and", Y, Z)), ("and", ("or", X, Y), ("or", X, Z))),
    ("and_factor", ("or", ("and", X, Y), ("and", X, Z)), ("and", X, ("or", Y, Z))),
    ("or_factor", ("and", ("or", X, Y), ("or", X, Z)), ("or", X, ("and", Y, Z))),
    ("de_morgan_and", ("not", ("and", X, Y)), ("or", ("not", X), ("not", Y))),
    ("de_morgan_or", ("not", ("or", X, Y)), ("and", ("not", X), ("not", Y))),
    ("implication", ("imp", X, Y), ("or", ("not", X), Y)),
    ("implication_fold", ("or", ("not", X), Y), ("imp", X, Y)),
    ("iff_expand", ("iff", X, Y), ("and", ("imp", X, Y), ("imp", Y, X))),
    ("iff_self", ("iff", X, X), ("true",)),
    ("xor_expand", ("xor", X, Y), ("not", ("iff", X, Y))),
    ("xor_self", ("xor", X, X), ("false",)),
)


class EGraph:
    def __init__(self, max_nodes: int = 512, max_matches: int = 20_000):
        self.max_nodes = max(1, min(2048, int(max_nodes)))
        self.max_matches = max(1, min(100_000, int(max_matches)))
        self.parent: list[int] = []
        self.classes: dict[int, set[tuple]] = {}
        self.memo: dict[tuple, int] = {}
        self.matches = 0
        self.unions = 0

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def canonical(self, node: tuple) -> tuple:
        op, name, children = node
        return op, name, tuple(self.find(c) for c in children)

    def add_node(self, op: str, children: tuple[int, ...] = (), name: str = "") -> int:
        node = self.canonical((op, name, children))
        if node in self.memo:
            return self.find(self.memo[node])
        # Count all allocated nodes, including ones subsequently merged.
        if len(self.parent) >= self.max_nodes:
            raise LogicLimit("egraph_node_budget")
        index = len(self.parent)
        self.parent.append(index)
        self.classes[index] = {node}
        self.memo[node] = index
        return index

    def add(self, formula: Formula) -> int:
        return self.add_node(formula.op, tuple(self.add(a) for a in formula.args), formula.name)

    def union(self, a: int, b: int) -> bool:
        a, b = sorted((self.find(a), self.find(b)))
        if a == b:
            return False
        self.parent[b] = a
        self.classes[a].update(self.classes.pop(b))
        self.unions += 1
        return True

    def rebuild(self) -> None:
        # A merge can make parent enodes congruent. Repeat until closed.
        while True:
            memo: dict[tuple, int] = {}
            changed = False
            for root, nodes in list(self.classes.items()):
                for node in sorted(nodes):
                    key = self.canonical(node)
                    if key in memo:
                        changed |= self.union(root, memo[key])
                    else:
                        memo[key] = self.find(root)
            if not changed:
                self.classes = {root: {self.canonical(n) for n in nodes}
                                for root, nodes in self.classes.items()}
                self.memo = {node: root for root, nodes in self.classes.items() for node in nodes}
                return

    def match(self, pattern: Any, root: int, bindings: dict[str, int]) -> Iterator[dict[str, int]]:
        self.matches += 1
        if self.matches > self.max_matches:
            raise LogicLimit("egraph_match_budget")
        root = self.find(root)
        if isinstance(pattern, str):
            if pattern not in bindings or self.find(bindings[pattern]) == root:
                yield {**bindings, pattern: root}
            return
        for op, _, children in sorted(self.classes[root]):
            if op != pattern[0] or len(children) != len(pattern) - 1:
                continue

            def descend(index: int, env: dict[str, int]) -> Iterator[dict[str, int]]:
                if index == len(children):
                    yield env
                else:
                    for matched in self.match(pattern[index + 1], children[index], env):
                        yield from descend(index + 1, matched)

            yield from descend(0, bindings)

    def instantiate(self, pattern: Any, bindings: dict[str, int]) -> int:
        if isinstance(pattern, str):
            return self.find(bindings[pattern])
        return self.add_node(pattern[0], tuple(self.instantiate(p, bindings) for p in pattern[1:]))

    def extract(self, root: int, *, objective: str = "render_chars") -> Formula:
        if objective not in {"render_chars", "ast_nodes"}:
            raise ValueError("unsupported extraction objective")
        # Positive tree costs prevent cyclic e-classes from producing a cyclic
        # output. Keep depth/size bounded even if the e-graph represents infinity.
        best: dict[int, tuple[tuple, Formula, int, int]] = {}
        for _ in range(min(MAX_DEPTH + 1, len(self.parent) + 1)):
            changed = False
            for owner, nodes in sorted(self.classes.items()):
                owner = self.find(owner)
                for op, name, children in sorted(nodes):
                    child_rows = [best.get(self.find(c)) for c in children]
                    if any(r is None for r in child_rows):
                        continue
                    size = 1 + sum(r[2] for r in child_rows)
                    # Match logic_ir.variables: a leaf has depth zero.
                    depth = 1 + max((r[3] for r in child_rows), default=-1)
                    if size > MAX_NODES or depth > MAX_DEPTH:
                        continue
                    term = Formula(op, tuple(r[1] for r in child_rows), name)
                    rendered = render_formula(term)
                    cost = (len(rendered), size, rendered) if objective == "render_chars" else (size, len(rendered), rendered)
                    if owner not in best or cost < best[owner][0]:
                        best[owner] = (cost, term, size, depth)
                        changed = True
            if not changed:
                break
        if self.find(root) not in best:
            raise LogicLimit("egraph_extraction_budget")
        return best[self.find(root)][1]


def saturate_formula(formula: Formula, *, max_nodes: int = 512, max_matches: int = 20_000,
                     iterations: int = 6, objective: str = "render_chars") -> dict[str, Any]:
    variables(formula)
    if objective not in {"render_chars", "ast_nodes"}:
        raise ValueError("unsupported extraction objective")
    graph = EGraph(max_nodes, max_matches)
    reason, saturated, used, rounds = None, False, set(), 0
    try:
        root = graph.add(formula)
    except LogicLimit as exc:
        return {"supported": False, "reason": str(exc), "lean": render_formula(formula),
                "authority": "search_hint_requires_Lean"}
    try:
        for rounds in range(1, max(0, min(12, int(iterations))) + 1):
            before = (len(graph.parent), graph.unions)
            for name, lhs, rhs in RULES:
                for owner in list(graph.classes):
                    for env in graph.match(lhs, owner, {}):
                        target = graph.instantiate(rhs, env)
                        if graph.union(owner, target):
                            used.add(name)
                graph.rebuild()
            graph.rebuild()
            if before == (len(graph.parent), graph.unions):
                saturated = True
                break
    except LogicLimit as exc:
        reason = str(exc)
    graph.rebuild()
    best = graph.extract(root, objective=objective)
    normalized = simplify_formula(best)
    def cost(term: Formula) -> tuple[int, int]:
        size = 1 + sum(cost(a)[1] for a in term.args)
        return len(render_formula(term)), size
    if (cost(normalized) if objective == "render_chars" else tuple(reversed(cost(normalized)))) < (
            cost(best) if objective == "render_chars" else tuple(reversed(cost(best)))):
        best = normalized
        used.add("algebraic_extraction_cleanup")
    return {"schema": "jevops-propositional-egraph/v1", "supported": True,
            "lean": render_formula(best), "ir": best.to_dict(), "objective": objective,
            "source_chars": len(render_formula(formula)), "result_chars": len(render_formula(best)),
            "saturated": saturated, "limit_reason": reason or (None if saturated else "iteration_budget"),
            "rounds": rounds, "allocated_nodes": len(graph.parent), "classes": len(graph.classes),
            "match_steps": graph.matches, "rules_used": sorted(used), "global_minimum": False,
            "semantics": "classical_propositional", "authority": "search_hint_requires_Lean"}
