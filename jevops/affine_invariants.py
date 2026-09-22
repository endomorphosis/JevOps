"""GF(2) affine invariants mined from exact bounded Boolean reachability.

Nullspace equations are valid on reachable states, but their conjunction need
not be inductive on all states. Houdini rechecks initiation/preservation before
they are returned as inductive hints. Lean obligations remain mandatory.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .invariant_inference import infer_invariants, reachable_states
from .logic_ir import Formula, render_formula, simplify_formula


def nullspace_gf2(rows: Sequence[int], columns: int) -> list[int]:
    if not 1 <= columns <= 9 or len(rows) > 256:
        raise ValueError("GF(2) matrix exceeds finite-state budget")
    if any(type(row) is not int or not 0 <= row < 1 << columns for row in rows):
        raise ValueError("invalid GF(2) row")
    matrix = list(dict.fromkeys(rows))
    rank, pivots = 0, []
    for column in range(columns):
        pivot = next((i for i in range(rank, len(matrix)) if matrix[i] >> column & 1), None)
        if pivot is None:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        for i in range(len(matrix)):
            if i != rank and matrix[i] >> column & 1:
                matrix[i] ^= matrix[rank]
        pivots.append(column)
        rank += 1
    basis = []
    for free in range(columns):
        if free in pivots:
            continue
        vector = 1 << free
        for i, pivot in enumerate(pivots):
            if matrix[i] >> free & 1:
                vector |= 1 << pivot
        basis.append(vector)
    return basis


def infer_affine_invariants(initial: Formula, transition: Formula,
                            state_pairs: Mapping[str, str]) -> dict[str, Any]:
    reach = reachable_states(initial, transition, state_pairs)
    names = reach["variables"]
    rows = [sum(int(s[name]) << i for i, name in enumerate(names)) | (1 << len(names))
            for s in reach["states"]]
    basis = nullspace_gf2(rows, len(names)+1)
    candidates = []
    for vector in basis:
        atoms = [Formula("var", name=name) for i, name in enumerate(names) if vector >> i & 1]
        parity = atoms[0] if atoms else Formula("false")
        for atom in atoms[1:]:
            parity = Formula("xor", (parity, atom))
        constant = Formula("true" if vector >> len(names) & 1 else "false")
        candidates.append(simplify_formula(Formula("iff", (parity, constant))))
    checked = infer_invariants(initial, transition, candidates, state_pairs)
    return {"schema": "jevops-finite-affine-invariants/v1", "reachability": reach,
            "basis_vectors": basis, "candidates": [render_formula(f) for f in candidates],
            "inference": checked, "lean_verified": False,
            "authority": "finite_boolean_hint_requires_Lean", "infinite_state_analysis": False}
