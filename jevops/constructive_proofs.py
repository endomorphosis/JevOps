"""Bounded constructive propositional proof search, with replayable Lean terms.

This is an incomplete sequent/forward search, not a parser for dependent Lean
types or a proof authority. Each term must be replayed in the unchanged theorem.
No classical truth-table result or guessed invariant becomes an assumption.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .logic_ir import FALSE, Formula, parse_formula, variables
from .constructive_terms import node, validate_tree
from .proof_tokens import proof_source_tokens
from .rewrite_policy import NAME, body_of, supported


def _normalize(f):
    if f.op == "xor":
        raise ValueError("XOR is outside constructive syntax")
    args = tuple(_normalize(a) for a in f.args)
    return Formula("imp", (args[0], FALSE)) if f.op == "not" else Formula(f.op, args, f.name)


def read_proposition(source):
    """Explicit named propositional binders only; unsupported syntax abstains."""
    prefix, body = body_of(source)
    if not prefix or len(source) > 32768 or not supported(body):
        raise ValueError("unsupported theorem")
    match = re.fullmatch(r"(?:\s*import [\w. ]+\n)*\s*(?:theorem|lemma) (" + NAME + r")\s*(.*?)\s*:=\s*by", prefix, re.S)
    if not match:
        raise ValueError("unsupported declaration envelope")
    rest, atoms, names, assumptions = match[2].strip(), set(), {match[1]}, []
    while rest.startswith("("):
        depth, end = 0, None
        for i, c in enumerate(rest):
            depth += (c == "(") - (c == ")")
            if depth == 0:
                end = i
                break
        if end is None:
            raise ValueError("unbalanced binder")
        names_text, sep, type_text = rest[1:end].partition(":")
        bound = names_text.split()
        if not sep or not bound or any(not re.fullmatch(NAME, n) or n in names or n in {"_", "True", "False"} for n in bound) or len(set(bound)) != len(bound):
            raise ValueError("unsupported/ambiguous binder")
        if type_text.strip() == "Prop":
            atoms.update(bound)
        else:
            formula = _normalize(parse_formula(type_text))
            if not set(variables(formula)) <= atoms:
                raise ValueError("unknown proposition")
            assumptions.extend((n, formula) for n in bound)
        names.update(bound)
        rest = rest[end + 1:].strip()
    if not rest.startswith(":") or len(atoms) > 8 or len(assumptions) > 16:
        raise ValueError("proposition budget or unsupported goal")
    goal = _normalize(parse_formula(rest[1:]))
    if not set(variables(goal)) <= atoms:
        raise ValueError("unknown goal proposition")
    return prefix, goal, assumptions


@dataclass(frozen=True)
class Proof:
    text: str
    used: frozenset[str]
    tree: dict

    @property
    def cost(self):
        return (proof_source_tokens("exact " + self.text), len(self.text), self.text)


def _arg(proof):
    return proof.text if re.fullmatch(NAME + r"(?:\.(?:left|right|mp|mpr))*", proof.text) else f"({proof.text})"


def search(goal, assumptions, *, max_states=512, max_depth=10, max_facts=96, include_term_ir=False):
    if type(include_term_ir) is not bool:
        raise ValueError("explicit term IR policy required")
    if any(type(n) is not int for n in (max_states, max_depth, max_facts)) or not (1 <= max_states <= 4096 and 1 <= max_depth <= 20 and 1 <= max_facts <= 256):
        raise ValueError("invalid constructive search budget")
    goal = _normalize(goal)
    variables(goal, *(f for _, f in assumptions))
    if len(assumptions) > 16 or len({n for n, _ in assumptions}) != len(assumptions) or any(not re.fullmatch(NAME, n) for n, _ in assumptions):
        raise ValueError("invalid constructive context")
    states, exhausted, serial = 0, False, 0
    reserved = set(variables(goal, *(f for _, f in assumptions))) | {n for n, _ in assumptions}

    def fresh():
        nonlocal serial
        while True:
            name = f"_cp{serial}"
            serial += 1
            if name not in reserved:
                reserved.add(name)
                return name

    def prove(target, facts, depth, active):
        nonlocal states, exhausted
        if states >= max_states or depth > max_depth:
            exhausted = True
            return None
        states += 1
        facts = dict(facts)

        def add(f, p):
            nonlocal exhausted
            if len(p.text) > 8192:
                exhausted = True
                return False
            old = facts.get(f)
            if old is None and len(facts) >= max_facts:
                exhausted = True
                return False
            if old is None or p.cost < old.cost:
                facts[f] = p
                return True
            return False

        # Local saturation: elimination, implication chaining, contradiction.
        for _ in range(max_facts):
            changed = False
            for f, p in list(facts.items()):
                if f.op in {"and", "iff"}:
                    for i, suffix in enumerate(("left", "right") if f.op == "and" else ("mp", "mpr")):
                        ty = f.args[i] if f.op == "and" else Formula("imp", (f.args[i], f.args[1-i]))
                        changed |= add(ty, Proof(f"{_arg(p)}.{suffix}", p.used, node("proj", p.tree, name=suffix)))
                if f.op == "imp" and f.args[0] in facts:
                    arg = facts[f.args[0]]
                    changed |= add(f.args[1], Proof(f"{_arg(p)} {_arg(arg)}", p.used | arg.used, node("app", p.tree, arg.tree)))
            if not changed:
                break
        key = (target, frozenset(facts))
        if key in active:
            return facts.get(target)
        active = active | {key}
        choices = [facts[target]] if target in facts else []
        if FALSE in facts:
            p = facts[FALSE]
            choices.append(Proof(f"False.elim {_arg(p)}", p.used, node("app", node("const", name="False.elim"), p.tree)))
        if target.op == "true":
            choices.append(Proof("True.intro", frozenset(), node("const", name="True.intro")))
        if target.op == "imp":
            a, b = target.args
            if a.op == "and" and b in a.args:
                name = "And.left" if b == a.args[0] else "And.right"
                choices.append(Proof(name, frozenset(), node("const", name=name)))
            name = fresh()
            body = prove(b, {**facts, a: Proof(name, frozenset({name}), node("local", name=name))}, depth + 1, active)
            if body:
                choices.append(Proof(f"fun {name} => {body.text}", body.used - {name}, node("lambda", body.tree, name=name)))
        if target.op in {"and", "iff"}:
            goals = target.args if target.op == "and" else (Formula("imp", target.args), Formula("imp", tuple(reversed(target.args))))
            a, b = [prove(g, facts, depth + 1, active) for g in goals]
            if a and b:
                choices.append(Proof(f"⟨{a.text}, {b.text}⟩", a.used | b.used, node("pair", a.tree, b.tree)))
        if target.op == "or":
            for i, side in enumerate(("inl", "inr")):
                p = prove(target.args[i], facts, depth + 1, active)
                if p:
                    choices.append(Proof(f"Or.{side} {_arg(p)}", p.used, node("app", node("const", name=f"Or.{side}"), p.tree)))
        # Use implications whose premise requires construction, not just lookup.
        if not choices:
            for f, p in list(facts.items()):
                if f.op == "imp" and f.args[1] == target:
                    arg = prove(f.args[0], {k:v for k,v in facts.items() if k != f}, depth + 1, active)
                    if arg:
                        choices.append(Proof(f"{_arg(p)} {_arg(arg)}", p.used | arg.used, node("app", p.tree, arg.tree)))
        # Case splitting is constructive; no excluded-middle assumption.
        if not choices:
            for f, p in list(facts.items()):
                if f.op != "or":
                    continue
                names = (fresh(), fresh())
                branches = [prove(target, {**{k:v for k,v in facts.items() if k != f}, g: Proof(n, frozenset({n}), node("local", name=n))},
                                  depth + 1, active) for n,g in zip(names, f.args)]
                a,b = branches
                if a and b:
                    choices.append(Proof(f"Or.elim {_arg(p)} (fun {names[0]} => {a.text}) (fun {names[1]} => {b.text})",
                                         p.used | (a.used - {names[0]}) | (b.used - {names[1]}),
                                         node("app", node("app", node("app", node("const", name="Or.elim"), p.tree),
                                              node("lambda", a.tree, name=names[0])), node("lambda", b.tree, name=names[1]))))
        return min(choices, key=lambda p:p.cost) if choices else None

    initial = {}
    for name, formula in assumptions:
        f, p = _normalize(formula), Proof(name, frozenset({name}), node("local", name=name))
        if f not in initial or p.cost < initial[f].cost:
            initial[f] = p
    proof = prove(goal, initial, 0, set())
    result = {"term": proof.text if proof else None, "support": sorted(proof.used) if proof else [],
            "states": states, "budget_exhausted": exhausted, "complete": False,
            "authority": "proposal_requires_Lean", "global_minimum": False}
    if include_term_ir:
        result["term_ir"] = None
        if proof:
            try:
                validate_tree(proof.tree)
                result["term_ir"] = proof.tree
            except ValueError:
                pass  # IR budget failure never removes the original proposal.
    return result


def propose(source, **budgets):
    try:
        prefix, goal, assumptions = read_proposition(source)
        result = search(goal, assumptions, **budgets)
    except ValueError as exc:
        return {"supported": False, "reason": str(exc), "candidate": None}
    candidate = prefix + "\n  exact " + result["term"] + "\n" if result["term"] else None
    return {"supported": True, **result, "candidate": candidate}
