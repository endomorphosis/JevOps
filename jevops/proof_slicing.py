"""Bounded hierarchical deletion proposals and compiler-oracle minimization.

Layout is a search heuristic, not Lean syntax or dependency analysis. Every
accepted cut must preserve the original theorem envelope and pass the supplied
compiler. A bounded run does not claim even 1-minimality, much less optimality.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import math
import time
from typing import Any


def deletion_variants(body: str, *, cap: int = 32) -> list[tuple[str, str, tuple[str, ...]]]:
    if cap <= 0 or len(body) > 32_768:
        return []
    lines = body.splitlines(keepends=True)
    if len(lines) > 256 or any(token in body for token in ('/-', '-/', '--', '"', '`', '\t')):
        return []
    positions = [i for i, line in enumerate(lines) if line.strip()]
    if len(positions) <= 1:
        return []
    indents = {i: len(lines[i]) - len(lines[i].lstrip()) for i in positions}
    spans = {i: next((j for j in positions if j > i and indents[j] <= indents[i]), len(lines)) for i in positions}
    # Sibling groups share a layout parent, not merely the same indentation.
    groups: dict[tuple[int, int], list[int]] = {}
    stack = []
    for i in positions:
        while stack and indents[stack[-1]] >= indents[i]:
            stack.pop()
        groups.setdefault((stack[-1] if stack else -1, indents[i]), []).append(i)
        stack.append(i)
    proposals = []
    seen = {body.strip()}
    budget = min(64, int(cap))

    def push(start: int, end: int, kind: str) -> None:
        candidate = "".join(lines[:start] + lines[end:]).rstrip()
        if candidate.strip() and candidate.strip() not in seen and len(proposals) < budget:
            seen.add(candidate.strip())
            proposals.append((kind, candidate, ("proof_slice", f"lines:{start}:{end}")))

    # Coarse-to-fine chunks can eliminate mutually dependent dead blocks
    # whose individual removal fails. Restart on each admitted shorter body.
    for width_divisor in (1, 2, 4, 8):
        for group in groups.values():
            if len(group) < 2:
                continue
            width = max(1, math.ceil(len(group) / width_divisor))
            for start in range(0, len(group), width):
                chunk = group[start:start + width]
                push(chunk[0], spans[chunk[-1]], "delete_sibling_chunk")
    for i in sorted(positions, key=lambda j: (-(spans[j] - j), j)):
        push(i, spans[i], "delete_layout_block")
    return proposals


def minimize_checked(source: str, compile_fn: Callable[..., Mapping[str, Any]], *,
                     max_calls: int = 64, max_rounds: int = 8,
                     token_fn: Callable[[str], int] | None = None) -> dict[str, Any]:
    """Isolated compiler-gated search; never writes production/training memory.

    The callback must enforce the target project's admission/trust policy.
    ``token_fn`` measures proof bodies and must stay fixed across the run.
    """
    from . import autoencoder as ae
    from .router_tuning import RouterTuningConfig, RouterTuningLoop, _source_parts

    if not 1 <= max_calls <= 512 or not 1 <= max_rounds <= 64:
        raise ValueError("invalid proof slicing budget")
    prefix, body, has_theorem = _source_parts(source)
    if not has_theorem:
        raise ValueError("a theorem envelope is required")
    measure = token_fn or ae.proof_body_token_count
    attempts: list[dict[str, Any]] = []

    def audited(candidate: str, **kwargs: Any) -> Mapping[str, Any]:
        if len(attempts) >= max_calls:
            return {"theorem_ok": False, "reason": "compile_budget"}
        started = time.monotonic()
        try:
            receipt = dict(compile_fn(candidate, **kwargs))
        except Exception as exc:
            receipt = {"theorem_ok": False, "reason": type(exc).__name__}
        attempts.append({"wall_seconds": time.monotonic() - started, "receipt": receipt})
        return receipt

    loop = RouterTuningLoop({}, source, compile_fn=audited, router_generate=lambda _: "{}",
                           config=RouterTuningConfig(train=False, max_candidate_pool=64, max_tactic_lines=160))
    baseline = loop._row(source, origin="current", kind="baseline")
    best, best_body, best_cost = source, body, int(measure(body))
    trajectory, exhausted = [], False
    if baseline["lake_ok"]:
        for round_index in range(max_rounds):
            changed = False
            for kind, draft, _ in deletion_variants(best_body, cap=64):
                cost = int(measure(draft))
                if cost >= best_cost:
                    continue
                if len(attempts) >= max_calls:
                    exhausted = True
                    break
                rows: list[dict[str, Any]] = []
                loop._push(rows, set(), draft, origin="logic:proof_slice", kind=kind)
                if not rows or not rows[0]["lake_ok"]:
                    continue
                best, best_body = rows[0]["source"], _source_parts(rows[0]["source"])[1]
                assert _source_parts(best)[0] == prefix
                trajectory.append({"round": round_index, "before_tokens": best_cost, "after_tokens": cost,
                                   "kind": kind, "source": best, "compile": rows[0]["compile"]})
                best_cost, changed = cost, True
                break
            if exhausted or not changed:
                break
        else:
            exhausted = True
    return {"schema": "jevops-checked-proof-slicing/v1", "ok": baseline["lake_ok"],
            "source_body_tokens": int(measure(body)), "best_body_tokens": best_cost,
            "best_source": best, "trajectory": trajectory, "compile_attempts": attempts,
            "budget_exhausted": exhausted, "minimality_proven": False,
            "training_enabled": False, "production_memory_used": False, "official_score": None}
