"""Learned binary binding retention using bounded symbolic source features.

The graph analysis is symbolic. Only the keep/delete weights are learned;
this is not an elaborator, a neural dependency-discovery system, or a prover.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from .ir_dependencies import analyze_dependencies

FEATURES = ("bias", "reaches_root", "direct_root_use", "used_by_binding", "no_users", "trivial_true")


def source_features(body: str, operations: Sequence[tuple[str, Sequence[str]]]) -> dict[str, Any]:
    analysis = analyze_dependencies(body, operations)
    if not analysis["supported"]:
        return {**analysis, "rows": []}
    bindings = set(analysis["bindings"])
    roots = set(range(len(operations))) - bindings
    dependencies = analysis["dependencies"]
    reachable = set(roots)
    users = [set() for _ in operations]
    for index, refs in enumerate(dependencies):
        for ref in refs:
            users[ref].add(index)
    for index in reversed(range(len(operations))):
        if index in reachable:
            reachable.update(dependencies[index])
    return {"supported": True, "reason": "symbolic_dependency_features", "rows": [
        {"index": i, "features": {"bias": 1.0, "reaches_root": float(i in reachable),
         "direct_root_use": float(bool(users[i] & roots)),
         "used_by_binding": float(bool(users[i] & bindings)), "no_users": float(not users[i]),
         "trivial_true": float(bool(re.search(r":\s*True\s*:=\s*True\.intro\s*$", " ".join(operations[i][1]))))}}
        for i in sorted(bindings)]}


def subsequence_labels(source: Sequence[tuple[str, Sequence[str]]],
                       target: Sequence[tuple[str, Sequence[str]]]) -> list[int] | None:
    """Align exact operations AND operands; ambiguous duplicates are skipped.

    Both forward and backward greedy alignments must select the same source
    positions. Relabeled/reordered/replaced operations cannot teach deletion.
    """
    if len(source) > 256 or len(target) > len(source):
        return None
    a = [(op, tuple(args)) for op, args in source]
    b = [(op, tuple(args)) for op, args in target]
    left, right = [], []
    cursor = 0
    for item in b:
        while cursor < len(a) and a[cursor] != item:
            cursor += 1
        if cursor == len(a):
            return None
        left.append(cursor)
        cursor += 1
    cursor = len(a) - 1
    for item in reversed(b):
        while cursor >= 0 and a[cursor] != item:
            cursor -= 1
        if cursor < 0:
            return None
        right.append(cursor)
        cursor -= 1
    if left != list(reversed(right)):
        return None
    kept = set(left)
    return [int(i in kept) for i in range(len(a))]


def keep_probability(weights: Mapping[str, float], features: Mapping[str, float]) -> float:
    logit = sum(weights.get(key, 0.0) * features.get(key, 0.0) for key in FEATURES)
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp = math.exp(logit)
    return exp / (1.0 + exp)


def loss_and_gradient(weights: Mapping[str, float], rows: Sequence[Mapping[str, Any]],
                      labels: Sequence[int]) -> tuple[float, dict[str, float]]:
    gradient = dict.fromkeys(FEATURES, 0.0)
    loss = 0.0
    for row in rows:
        features = row["features"]
        label = labels[row["index"]]
        logit = sum(weights.get(key, 0.0) * features.get(key, 0.0) for key in FEATURES)
        probability = keep_probability(weights, features)
        # Stable softplus BCE, without clipping away the gradient at saturation.
        loss += max(logit, 0.0) - label * logit + math.log1p(math.exp(-abs(logit)))
        for key in FEATURES:
            gradient[key] += (probability - label) * features.get(key, 0.0)
    size = max(1, len(rows))
    return loss / size, {key: value / size for key, value in gradient.items()}
