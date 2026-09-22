"""Finite Boolean Houdini inference and safety-preserving invariant reduction.

Explicit state/transition models only: no invariants are inferred from a Lean
goal as if they were hypotheses. Exhaustive Python checks remain search hints;
the returned initiation/preservation obligations must be proved in Lean.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .logic_ir import (Formula, LogicLimit, MAX_VARIABLES, _join,
                       assignment_for, evaluate, render_formula, variables)


def _system(initial: Formula, transition: Formula, candidates: Sequence[Formula],
            state_pairs: Mapping[str, str]) -> tuple[list[dict[str, bool]], list[tuple[dict, dict]]]:
    if len(candidates) > 32:
        raise LogicLimit("at most 32 invariant candidates")
    current, future = set(state_pairs), set(state_pairs.values())
    if not current or current & future or len(current) != len(future):
        raise ValueError("state names must be nonempty, injective and disjoint")
    if len(current | future) > MAX_VARIABLES:
        raise LogicLimit("finite invariant transition budget")
    for name in current | future:
        Formula("var", name=name)
    if not set(variables(initial, *candidates)) <= current:
        raise ValueError("initial state and candidates must use current variables")
    if not set(variables(transition)) <= current | future:
        raise ValueError("undeclared transition variable")
    names = sorted(current)
    states = [assignment_for(i, names) for i in range(1 << len(names))]
    edges = [(a, b) for a in states for b in states if evaluate(
        transition, {**a, **{state_pairs[k]: v for k, v in b.items()}})]
    return [a for a in states if evaluate(initial, a)], edges


def _prime(formula: Formula, state_pairs: Mapping[str, str]) -> Formula:
    return (Formula("var", name=state_pairs[formula.name]) if formula.op == "var" else
            Formula(formula.op, tuple(_prime(a, state_pairs) for a in formula.args)))


def infer_invariants(initial: Formula, transition: Formula, candidates: Sequence[Formula],
                     state_pairs: Mapping[str, str]) -> dict[str, Any]:
    """Greatest inductive conjunction drawn from a fixed candidate set.

    Removing a failed conjunct can invalidate another. Recheck to a fixed
    point; never treat each candidate's independent validity as sufficient.
    Mutually supporting candidates are allowed. Redundancy removal preserves
    the entire inferred conjunction, not just samples from execution traces.
    """
    initial_states, edges = _system(initial, transition, candidates, state_pairs)
    active = list(range(len(candidates)))
    removed, rounds = [], 0
    while active:
        rounds += 1
        failures = []
        for index in active:
            candidate = candidates[index]
            initial_bad = next((a for a in initial_states if not evaluate(candidate, a)), None)
            step_bad = next(((a, b) for a, b in edges if
                             all(evaluate(candidates[i], a) for i in active) and not evaluate(candidate, b)), None)
            if initial_bad is not None or step_bad is not None:
                failures.append(index)
                removed.append({"index": index, "round": rounds,
                                "reason": "initiation" if initial_bad is not None else "preservation",
                                "counterexample": initial_bad if initial_bad is not None else
                                {"before": step_bad[0], "after": step_bad[1]}})
        if not failures:
            break
        active = [i for i in active if i not in failures]
    inferred = list(active)
    # Sequential logical implication, NOT independent removal of duplicates.
    names = sorted(state_pairs)
    states = [assignment_for(i, names) for i in range(1 << len(names))]
    redundant = []
    for index in reversed(active[:]):
        others = [i for i in active if i != index]
        if all(not all(evaluate(candidates[i], a) for i in others) or evaluate(candidates[index], a) for a in states):
            active.remove(index)
            redundant.append(index)
    invariant = _join("and", [candidates[i] for i in active])
    # Reject a combined output beyond the same public formula budget.
    variables(invariant)
    initial_obligation = Formula("imp", (initial, invariant))
    step_obligation = Formula("imp", (Formula("and", (invariant, transition)), _prime(invariant, state_pairs)))
    return {"schema": "jevops-finite-houdini/v1", "inferred_indices": inferred,
            "kept_indices": active, "removed": removed, "redundant_indices": redundant,
            "lean": render_formula(invariant), "ir": invariant.to_dict(), "rounds": rounds,
            "initial_satisfiable": bool(initial_states),
            "preservation_vacuous": not any(all(evaluate(candidates[i], a) for i in active) for a, _ in edges),
            "initiation_obligation": render_formula(initial_obligation),
            "preservation_obligation": render_formula(step_obligation),
            "inductive_in_finite_model": True, "lean_verified": False,
            "global_minimum": False, "authority": "finite_boolean_hint_requires_Lean"}


def reachable_states(initial: Formula, transition: Formula, state_pairs: Mapping[str, str]) -> dict[str, Any]:
    """Exact bounded reachability, distinct from one-step inductiveness."""
    starts, edges = _system(initial, transition, [], state_pairs)
    names = sorted(state_pairs)
    key = lambda a: tuple(a[n] for n in names)
    reached = {key(a) for a in starts}
    rounds = 0
    while True:
        added = {key(b) for a, b in edges if key(a) in reached} - reached
        if not added:
            break
        reached.update(added)
        rounds += 1
    return {"variables": names, "states": [dict(zip(names, s)) for s in sorted(reached)],
            "rounds": rounds, "initial_satisfiable": bool(starts),
            "authority": "finite_boolean_hint_requires_Lean", "lean_verified": False}
