"""Exact, bounded Farkas search for explicit affine integer transition systems.

Unlike Boolean reachability this reasons over unbounded integer states, but is
incomplete: only nonnegative rational combinations of supplied non-strict linear
inequalities are searched. Failure/budget exhaustion means UNKNOWN, not false.
Certificates are independently checked here; Lean obligations remain mandatory.
No source program or theorem is automatically interpreted as this explicit model.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
import re
from typing import Any, Sequence


def _integer(value: int) -> bool:
    return type(value) is int and value.bit_length() <= 32


@dataclass(frozen=True)
class LinearInequality:
    coefficients: tuple[int, ...]
    bound: int

    def __post_init__(self):
        object.__setattr__(self, "coefficients", tuple(self.coefficients))
        if not 1 <= len(self.coefficients) <= 4 or not all(_integer(v) for v in (*self.coefficients, self.bound)):
            raise ValueError("expected 1..4 bounded integer coefficients and an integer bound")

    def to_dict(self):
        return {"coefficients": list(self.coefficients), "bound": self.bound}

    def lean(self):
        terms = [f"({a}) * x{i}" for i, a in enumerate(self.coefficients) if a]
        return f"({' + '.join(terms) or '(0 : Int)'}) ≤ ({self.bound})"


def _validate(premises, target):
    if len(premises) > 16 or any(len(p.coefficients) != len(target.coefficients) for p in premises):
        raise ValueError("linear premise count/dimension mismatch")


def _rational(value):
    if not isinstance(value, str) or len(value) > 100 or not re.fullmatch(r"-?\d+(?:/[1-9]\d*)?", value):
        raise ValueError("invalid rational certificate")
    result = Fraction(value)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 256:
        raise ValueError("certificate arithmetic budget")
    return result


def verify_certificate(premises: Sequence[LinearInequality], target: LinearInequality,
                       certificate: dict[str, Any]) -> bool:
    """Check exact coefficient identities, not a solver's claimed status."""
    try:
        _validate(premises, target)
        if (set(certificate) != {"weights", "slack"} or not isinstance(certificate["weights"], list)
                or len(certificate["weights"]) != len(premises)):
            return False
        weights = [_rational(v) for v in certificate["weights"]]
        slack = _rational(certificate["slack"])
        return (slack >= 0 and all(w >= 0 for w in weights)
                and all(sum(w*p.coefficients[i] for w, p in zip(weights, premises)) == a
                        for i, a in enumerate(target.coefficients))
                and sum(w*p.bound for w, p in zip(weights, premises)) + slack == target.bound)
    except (TypeError, ValueError, KeyError, ZeroDivisionError, AttributeError):
        return False


def _solve_independent(columns, target):
    """Exact overdetermined elimination; dependent supports are skipped."""
    width = len(columns)
    matrix = [[Fraction(c[i]) for c in columns] + [Fraction(t)] for i, t in enumerate(target)]
    rank = 0
    for column in range(width):
        pivot = next((i for i in range(rank, len(matrix)) if matrix[i][column]), None)
        if pivot is None:
            return None
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        divisor = matrix[rank][column]
        matrix[rank] = [v/divisor for v in matrix[rank]]
        for i in range(len(matrix)):
            if i != rank:
                factor = matrix[i][column]
                matrix[i] = [a-factor*b for a, b in zip(matrix[i], matrix[rank])]
        rank += 1
    if any(not any(row[:width]) and row[-1] for row in matrix):
        return None
    return [matrix[i][-1] for i in range(width)]


def imply(premises: Sequence[LinearInequality], target: LinearInequality, *, max_combinations=512):
    _validate(premises, target)
    if type(max_combinations) is not int or not 1 <= max_combinations <= 4096:
        raise ValueError("invalid certificate search budget")
    dimension = len(target.coefficients)
    # Slack column represents a nonnegative weakening of the resulting bound.
    columns = [(*p.coefficients, p.bound) for p in premises] + [(0,)*dimension + (1,)]
    vector = (*target.coefficients, target.bound)
    attempts = 0
    if not any(vector):
        return {"proved": True, "certificate": {"weights": ["0"]*len(premises), "slack": "0"}, "attempts": 0}
    for size in range(1, min(dimension+1, len(columns))+1):
        for support in combinations(range(len(columns)), size):
            if attempts == max_combinations:
                return {"proved": False, "status": "unknown_budget", "attempts": attempts}
            attempts += 1
            solution = _solve_independent([columns[i] for i in support], vector)
            if solution is None or any(w < 0 for w in solution):
                continue
            full = [Fraction(0)]*len(columns)
            for i, w in zip(support, solution):
                full[i] = w
            certificate = {"weights": [str(w) for w in full[:-1]], "slack": str(full[-1])}
            if verify_certificate(premises, target, certificate):
                return {"proved": True, "certificate": certificate, "attempts": attempts}
    return {"proved": False, "status": "unknown_no_certificate", "attempts": attempts}


def implication_obligation(premises, target, certificate, *, name="linear_certificate"):
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", name) or not verify_certificate(premises, target, certificate):
        raise ValueError("cannot render invalid certificate/name")
    used = [i for i, weight in enumerate(certificate["weights"]) if _rational(weight)]
    variables = " ".join(f"x{i}" for i in range(len(target.coefficients)))
    hypotheses = " ".join(f"(h{i} : {premises[i].lean()})" for i in used)
    support = ", ".join(f"h{i}" for i in used)
    return (f"theorem {name} ({variables} : Int) {hypotheses} : {target.lean()} := by\n"
            f"  linarith only [{support}]\n")


def reduce_constraints(constraints: Sequence[LinearInequality], *, max_combinations=512):
    """Sequential deletions, each with explicit retained premises/certificate."""
    if not constraints or len(constraints) > 16:
        raise ValueError("expected 1..16 linear constraints")
    _validate(constraints, constraints[0])
    active, removed = list(range(len(constraints))), []
    for index in list(active):
        rest = [i for i in active if i != index]
        result = imply([constraints[i] for i in rest], constraints[index], max_combinations=max_combinations)
        if result["proved"]:
            active.remove(index)
            removed.append({"index": index, "premise_indices": rest, **result,
                            "obligation": implication_obligation([constraints[i] for i in rest], constraints[index],
                                                                  result["certificate"], name=f"redundant_{index}")})
    return {"kept_indices": active, "removed": removed, "lean_verified": False,
            "authority": "exact_rational_search_requires_Lean"}


def pullback(target: LinearInequality, matrix: Sequence[Sequence[int]], offset: Sequence[int]):
    n = len(target.coefficients)
    if len(matrix) != n or len(offset) != n or any(len(r) != n for r in matrix):
        raise ValueError("affine update dimension mismatch")
    if not all(_integer(x) for row in matrix for x in row) or not all(_integer(x) for x in offset):
        raise ValueError("affine update must use bounded integer coefficients")
    return LinearInequality(tuple(sum(target.coefficients[i]*matrix[i][j] for i in range(n)) for j in range(n)),
                            target.bound - sum(a*b for a, b in zip(target.coefficients, offset)))


def _affine_goal(target, matrix, offset):
    # Render the ORIGINAL update, not just Python's normalized pullback.
    # Lean must also check the algebra relating the update to the invariant.
    terms = []
    for a, row, c in zip(target.coefficients, matrix, offset):
        if a:
            updated = ' + '.join(f"({v}) * x{j}" for j, v in enumerate(row) if v) or '(0 : Int)'
            terms.append(f"({a}) * (({updated}) + ({c}))")
    return f"({' + '.join(terms) or '(0 : Int)'}) ≤ ({target.bound})"


def infer_linear_invariants(initial: Sequence[LinearInequality], guards: Sequence[LinearInequality],
                            candidates: Sequence[LinearInequality], matrix: Sequence[Sequence[int]],
                            offset: Sequence[int], *, max_combinations=512):
    """Certificate-backed Houdini for one explicit guarded affine transition.

    The result is a conservative subset, not the greatest inductive subset:
    unproved candidates may be true outside this incomplete certificate domain.
    """
    if not candidates or len(candidates) > 8 or len(guards) > 8:
        raise ValueError("expected 1..8 candidates and at most 8 guards")
    _validate([*initial, *guards], candidates[0])
    _validate(candidates, candidates[0])
    transformed = [pullback(c, matrix, offset) for c in candidates]
    active, removed, rounds = list(range(len(candidates))), [], 0
    while active:
        rounds += 1
        failed = []
        premises = [candidates[i] for i in active] + list(guards)
        for index in active:
            initiation = imply(initial, candidates[index], max_combinations=max_combinations)
            preservation = imply(premises, transformed[index], max_combinations=max_combinations)
            if not initiation["proved"] or not preservation["proved"]:
                failed.append(index)
                removed.append({"index": index, "round": rounds, "initiation": initiation,
                                "preservation": preservation, "reason": "unproved_not_counterexample"})
        if not failed:
            break
        active = [i for i in active if i not in failed]
    obligations = []
    premises = [candidates[i] for i in active] + list(guards)
    for index in active:
        for phase, context, target in (("init", initial, candidates[index]), ("step", premises, transformed[index])):
            result = imply(context, target, max_combinations=max_combinations)
            assert result["proved"]
            lean = implication_obligation(context, target, result["certificate"], name=f"{phase}_{index}")
            goal = target.lean() if phase == "init" else _affine_goal(candidates[index], matrix, offset)
            lean = lean.replace(f": {target.lean()} := by", f": {goal} := by", 1)
            obligations.append({"index": index, "phase": phase, "premises": [p.to_dict() for p in context],
                                "target": target.to_dict(), **result,
                                "lean_goal": goal, "lean": lean})
    return {"schema": "jevops-affine-integer-invariants/v1", "kept_indices": active,
            "removed": removed, "rounds": rounds, "obligations": obligations,
            "initial": [p.to_dict() for p in initial], "guards": [p.to_dict() for p in guards],
            "candidates": [p.to_dict() for p in candidates], "matrix": [list(r) for r in matrix], "offset": list(offset),
            "lean_verified": False, "source_program_binding_verified": False,
            "complete": False, "authority": "exact_rational_search_requires_Lean"}
