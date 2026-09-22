"""Bounded balanced tactic-list edits. Syntax hints, never Lean authority."""
from __future__ import annotations

import re

OPEN = {"(": ")", "[": "]", "{": "}", "⟨": "⟩"}
CLOSE = set(OPEN.values())
HEAD = re.compile(r"(?m)^[ ]*(?:(?:simp|simp_all|simpa|dsimp|rw|grind|linarith|nlinarith)(?: only)?)\s*\[")


def argument_spans(body: str) -> list[tuple[int, int, list[str]]]:
    """Recognize one-line lists; nested term commas are not separators.

    Opaque syntax is skipped wholesale. This is intentionally not Lean's parser.
    Returned offsets exclude the outer brackets and preserve all surrounding text.
    """
    if len(body) > 32_768 or any(s in body for s in ('--', '/-', '-/', '"', '`', '$', '\t')):
        return []
    rows = []
    for match in HEAD.finditer(body):
        start, cursor, stack, pieces = match.end(), match.end(), [], []
        end = None
        for index in range(start, min(len(body), start + 2048)):
            char = body[index]
            if char in '\n;':
                break
            if char in OPEN:
                stack.append(OPEN[char])
                if len(stack) > 16:
                    break
            elif char == ']' and not stack:
                pieces.append(body[cursor:index].strip())
                end = index
                break
            elif char in CLOSE:
                if not stack or stack.pop() != char:
                    break
            elif char == ',' and not stack:
                pieces.append(body[cursor:index].strip())
                cursor = index + 1
        if end is not None and len(pieces) <= 16 and all(pieces):
            rows.append((start, end, pieces))
        if len(rows) == 32:
            break
    return rows


def argument_variants(body: str, *, cap: int = 16) -> list[tuple[str, str, tuple[str, ...]]]:
    """Try whole-set/chunk/singleton deletions; accept only after compilation."""
    out, seen = [], {body}
    limit = max(0, min(64, int(cap)))
    for start, end, items in argument_spans(body):
        spans = [(0, len(items))]
        width = len(items) // 2
        while width:
            spans.extend((i, min(i + width, len(items))) for i in range(0, len(items), width))
            width //= 2
        for left, right in dict.fromkeys(spans):
            if len(out) >= limit:
                return out
            replacement = ', '.join(items[:left] + items[right:])
            candidate = body[:start] + replacement + body[end:]
            if candidate not in seen:
                seen.add(candidate)
                out.append(("solver_argument_delete", candidate, ("solver_argument_reduce", "balanced_list_delete")))
    return out
