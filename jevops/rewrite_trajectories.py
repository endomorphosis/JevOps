"""Audited adjacent rewrite supervision, with explicit step-label coverage.

The compiler is trusted infrastructure. Persisted traces and their receipts are
not proof authority: every state is rechecked under its exact original header.
These are teacher paths, not on-policy DAgger or a certificate of minimality.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from . import autoencoder as ae
from .autoencoder_training import coerce_training_example
from .rewrite_policy import body_of, supported
from .proof_tokens import proof_source_tokens


def verified_edges(teacher: Mapping[str, Any], *, parent_id: str, split: str,
                   compile_fn: Callable[[str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    if split not in {"train", "validation", "canary", "holdout"}:
        raise ValueError("unknown trajectory split")
    source, target = teacher.get("source"), teacher.get("target")
    trace = teacher.get("trace", [])
    if not isinstance(source, str) or not isinstance(target, str) or not isinstance(trace, list) or len(trace) > 16:
        raise ValueError("invalid trajectory")
    states = [source]
    for step in trace:
        if not isinstance(step, Mapping) or step.get("before_source") != states[-1] or not isinstance(step.get("after_source"), str):
            raise ValueError("disconnected trajectory")
        states.append(step["after_source"])
    if states[-1] != target:
        raise ValueError("trajectory endpoint mismatch")
    prefix, _ = body_of(source)
    if not prefix:
        raise ValueError("trajectory requires theorem envelope")
    for i, state in enumerate(states):
        envelope, body = body_of(state)
        if envelope != prefix or not supported(body):
            raise ValueError("trajectory envelope or syntax changed")
        if i and proof_source_tokens(state) >= proof_source_tokens(states[i-1]):
            raise ValueError("trajectory is not strictly shortening")
        receipt = compile_fn(state)
        audit = receipt.get("kernel_audit")
        if receipt.get("theorem_ok") is not True or not isinstance(audit, Mapping) or audit.get("accepted") is not True:
            raise ValueError("unverified trajectory state")
    # A no-change fixture supplies a real identity label. Do not invent stop
    # labels for shortened endpoints: the teacher need not be maximally short.
    pairs = list(zip(states, states[1:])) or [(source, source)]
    return [{"id": f"{parent_id}:step:{i}", "parent_id": parent_id, "split": split,
             "text": before, "target_ir": ae.encode_lean_ir(after)}
            for i, (before, after) in enumerate(pairs)]


def trajectory_metrics(model, edges: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [model.rewrite_objective(coerce_training_example(edge)) for edge in edges]
    labeled = [v for v in values if v is not None]
    return {"step_count": len(edges), "labeled_step_count": len(labeled),
            "complete": bool(edges) and len(labeled) == len(edges),
            "cross_entropy": sum(v["cross_entropy"] for v in labeled)/len(labeled) if labeled else None,
            "expected_cosine_loss": sum(v["expected_cosine_loss"] for v in labeled)/len(labeled) if labeled else None}
