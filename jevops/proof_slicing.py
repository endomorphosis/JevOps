"""Bounded hierarchical deletion proposals and compiler-oracle minimization.

Layout is a search heuristic, not Lean syntax or dependency analysis. Every
accepted cut must preserve the original theorem envelope and pass the supplied
compiler. A bounded run does not claim even 1-minimality, much less optimality.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import math
import hashlib
import re
import time
from typing import Any


def arity_repair_variants(source: str, statement: str, diagnostics: list[dict], *,
                          diagnostics_source_sha256: str, cap: int = 2) -> list[tuple[str, str, tuple[str, ...]]]:
    """Propose one argument/goal-block repair from a source-bound Lean error.

    Restricted layout heuristic, NOT Lean syntax/dependency analysis or proof
    admission. Supports a unique parenthesized apply/refine/exact call with a
    trailing explicit ?_ and one dot-bullet block per explicit hole. A native
    'Function expected at' error must match the call minus that last argument.
    Unsupported/ambiguous syntax, other errors, or a stale source abstain.
    Every draft still needs whole-proof checking in the current pinned context.
    """
    if type(cap) is not int or not 0 <= cap <= 8:
        raise ValueError("bounded integer repair cap required")
    if cap == 0 or not isinstance(source, str) or len(source.encode()) > 262144:
        return []
    if (not isinstance(statement, str) or not statement or not source.startswith(statement)
            or hashlib.sha256(source.encode()).hexdigest() != diagnostics_source_sha256):
        return []
    body = source[len(statement):]
    if (not re.match(r"\s*:=\s*by\b", body) or len(body) > 32768
            or any(token in body for token in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return []
    if not isinstance(diagnostics, list) or len(diagnostics) > 64:
        return []
    arities = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict) or not isinstance(diagnostic.get("message"), str):
            return []
        message = diagnostic["message"]
        if (len(message) > 16384 or not isinstance(diagnostic.get("severity"), str)
                or diagnostic["severity"] not in {"error", "warning", "information"}):
            return []
        if diagnostic["severity"] != "error":
            continue
        match = re.fullmatch(r"Function expected at\n[ ]+([^\n]+)\nbut this term has type\n.+"
                             r"\n\nNote: Expected a function because this term is being applied to the argument\n[ ]+\?_", message, re.S)
        if match:
            terms = match[1].strip().split()
            terms = ["?_" if re.fullmatch(r"\?m\.\d+", term) else term for term in terms]
            if not all(term == "?_" or re.fullmatch(r"[^\W\d][\w']*", term) for term in terms):
                return []
            arities.append(terms)
        elif message.strip() != "No goals to be solved":
            return []
    if len(arities) != 1:
        return []
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return []
    pattern = re.compile(r"^( *)(?:(?:\.|·) )?(?:apply|refine|exact) \(([^()]+)\)(?:\.[1-9][0-9]*)*\s*$")
    matches = []
    for index, line in enumerate(lines):
        call = pattern.fullmatch(line)
        if call and call[2].split() == [*arities[0], "?_"]:
            matches.append((index, call))
    if len(matches) != 1:
        return []
    index, call = matches[0]
    indent = len(call[1])
    end = next((j for j in range(index + 1, len(lines))
                if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip(" ")) <= indent), len(lines))
    following = [j for j in range(index + 1, end) if lines[j].strip()]
    if not following:
        return []
    child_indent = min(len(lines[j]) - len(lines[j].lstrip(" ")) for j in following)
    children = [j for j in following if len(lines[j]) - len(lines[j].lstrip(" ")) == child_indent]
    if (len(children) != call[2].split().count("?_")
            or any(not re.match(r" *(?:\.|·) \S", lines[j]) for j in children)):
        return []
    start = children[-1]
    args = call[2]
    shortened = args[:args.rfind("?_")].rstrip()
    changed = lines[index][:call.start(2)] + shortened + lines[index][call.end(2):]
    draft = statement + "".join([*lines[:index], changed, *lines[index + 1:start], *lines[end:]]).rstrip("\n")
    return [("repair_overapplied_hole", draft,
             ("unverified_diagnostic_repair", f"body-call-line:{index}", f"body-goal-lines:{start}:{end}"))]


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


def deletion_spans(source: str, statement: str) -> tuple[tuple[int, int], ...]:
    """Bounded existing slicer spans, 1-based inclusive BODY line numbers.

    Deliberately accepts only the canonical newline tactic envelope. These are
    unverified edit actions, not assertions that context entries are redundant.
    """
    from .arena import intake_error

    if type(source) is not str or type(statement) is not str:
        raise ValueError("source and statement text required")
    prefix = statement + " := by\n"
    if (not source.startswith(prefix) or len(source.encode()) > 262144 or
            intake_error(source, statement)):
        raise ValueError("supported intact reference envelope required")
    body = source[len(prefix):]
    spans = []
    for _kind, _draft, ops in deletion_variants(body, cap=64):
        _, start, end = ops[1].split(":")
        span = (int(start) + 1, int(end))
        if span not in spans:
            spans.append(span)
    return tuple(spans)


def apply_deletion_span(source: str, statement: str, start: int, end: int, *,
                        expected_source_sha256: str) -> str:
    """Check a source-bound local edit and copy untouched bytes verbatim.

    This authorizes ONLY an edit, never acceptance of the resulting theorem.
    No generated strings, fresh declarations, whitespace repair or new imports.
    """
    from .arena import intake_error, source_hash

    if (type(source) is not str or type(statement) is not str or
            type(start) is not int or type(end) is not int or
            source_hash(source) != expected_source_sha256):
        raise ValueError("integer span and matching source identity required")
    if (start, end) not in deletion_spans(source, statement):
        raise ValueError("span is outside the declared deletion vocabulary")
    prefix = statement + " := by\n"
    lines = source[len(prefix):].splitlines(keepends=True)
    draft = prefix + "".join(lines[:start - 1] + lines[end:])
    if intake_error(draft, statement):
        raise ValueError("edit broke the proof envelope")
    return draft


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
