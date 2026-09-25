"""Exact difference-bound closure and certificate-backed redundancy reduction.

Explicit unbounded-integer constraints x_i - x_j <= c only. This does not infer
a transition model from Lean code. Path witnesses are independently checked;
Lean still checks emitted obligations. Inconsistent contexts never yield a
claimed non-vacuous reduction. No octagons, widening, or global minimality.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DifferenceBound:
    left: int
    right: int
    bound: int

    def __post_init__(self):
        if any(type(x) is not int for x in (self.left, self.right, self.bound)) or not (0 <= self.left < 16 and 0 <= self.right < 16) or self.bound.bit_length() > 32:
            raise ValueError("difference bound outside budget")

    def lean(self):
        return f"x{self.left} - x{self.right} ≤ ({self.bound})"


def _validate(constraints, dimensions):
    if type(dimensions) is not int or not 1 <= dimensions <= 16 or len(constraints) > 64:
        raise ValueError("difference system outside budget")
    if any(not isinstance(c, DifferenceBound) or max(c.left, c.right) >= dimensions for c in constraints):
        raise ValueError("difference dimension mismatch")


def verify_path(constraints, target, path):
    """Check connectivity and telescoping sum without trusting closure output."""
    if not isinstance(target, DifferenceBound) or not isinstance(path, list) or len(path) > 64:
        return False
    if any(type(i) is not int or not 0 <= i < len(constraints) for i in path):
        return False
    cursor, weight = target.left, 0
    for i in path:
        c = constraints[i]
        if not isinstance(c, DifferenceBound) or c.left != cursor:
            return False
        weight += c.bound
        cursor = c.right
    return cursor == target.right and weight <= target.bound


def closure(constraints, dimensions):
    _validate(constraints, dimensions)
    dist = [[0 if i == j else None for j in range(dimensions)] for i in range(dimensions)]
    paths = [[[] if i == j else None for j in range(dimensions)] for i in range(dimensions)]
    for index, c in enumerate(constraints):
        old = dist[c.left][c.right]
        if old is None or c.bound < old:
            dist[c.left][c.right], paths[c.left][c.right] = c.bound, [index]
    def inconsistent():
        return next((i for i in range(dimensions) if dist[i][i] < 0), None)
    bad = inconsistent()
    for k in range(dimensions):
        if bad is not None:
            break
        for i in range(dimensions):
            for j in range(dimensions):
                if dist[i][k] is None or dist[k][j] is None:
                    continue
                candidate = dist[i][k] + dist[k][j]
                if dist[i][j] is None or candidate < dist[i][j]:
                    dist[i][j] = candidate
                    paths[i][j] = paths[i][k] + paths[k][j]
            bad = inconsistent()
            if bad is not None:
                break
    return {"consistent": bad is None, "bounds": dist, "paths": paths,
            "negative_cycle": paths[bad][bad] if bad is not None else None}


def reduce_bounds(constraints, dimensions):
    original = closure(constraints, dimensions)
    if not original["consistent"]:
        return {"schema": "jevops-difference-bounds/v1", "status": "inconsistent_context",
                "negative_cycle": original["negative_cycle"], "reduced": False,
                "kept_indices": list(range(len(constraints))), "certificates": [], "lean_verified": False}
    active = list(range(len(constraints)))
    # Sequential removal prevents mutually redundant duplicates disappearing
    # together. Recompute final witnesses using only the retained constraints.
    for index in reversed(active[:]):
        others = [i for i in active if i != index]
        table = closure([constraints[i] for i in others], dimensions)
        c = constraints[index]
        path = table["paths"][c.left][c.right]
        if path is not None and verify_path(constraints, c, [others[i] for i in path]):
            active.remove(index)
    final = closure([constraints[i] for i in active], dimensions)
    certificates = []
    for index, c in enumerate(constraints):
        if index in active:
            continue
        path = [active[i] for i in final["paths"][c.left][c.right]]
        if not verify_path(constraints, c, path):
            raise AssertionError("invalid final difference certificate")
        certificates.append({"removed_index": index, "path": path})
    return {"schema": "jevops-difference-bounds/v1", "status": "consistent", "kept_indices": active,
            "certificates": certificates, "reduced": len(active) < len(constraints),
            "lean_verified": False, "global_minimum": False, "authority": "path_certificate_requires_Lean"}


def implication_obligation(constraints, target, path, *, name="difference_certificate"):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or not verify_path(constraints, target, path):
        raise ValueError("invalid difference certificate/name")
    if len(constraints) > 64:
        raise ValueError("difference certificate outside budget")
    dimension = 1 + max([target.left, target.right] + [x for i in path for x in (constraints[i].left, constraints[i].right)])
    variables = " ".join(f"x{i}" for i in range(dimension))
    hypotheses = " ".join(f"(h{i} : {constraints[i].lean()})" for i in sorted(set(path)))
    # Only the certified supporting hypotheses enter this standalone lemma.
    # The original user theorem is never edited to drop assumptions.
    return f"theorem {name} ({variables} : Int) {hypotheses} : {target.lean()} := by\n  omega\n"
