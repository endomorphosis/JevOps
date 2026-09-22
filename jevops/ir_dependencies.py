"""Conservative dependency closure for learned deletions in flat Lean IR.

This is a lexical proposal guard, not elaboration or a proof certificate.
Only simple local ``have`` declarations may be deleted. Other commands are
stateful roots; implicit-context readers retain all preceding declarations.
Unaligned or nested syntax suppresses edits rather than guessing scope.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

MAX_OPERATIONS = 256
MAX_SOURCE_CHARS = 32_768
_IDENT = r"[^\W\d][\w']*"
_NAMES = re.compile(_IDENT, re.UNICODE)
_HAVE = re.compile(rf"(?:(?P<name>{_IDENT})\s*)?(?::\s*(?P<type>.*?))?\s*:=\s*(?P<term>.+)")
_OPAQUE = re.compile(r'--|/-|-/|[;|"«»`]|=>|\b(?:by|fun|let|match|do|where|with)\b')


def analyze_dependencies(body: str, operations: Sequence[tuple[str, Sequence[str]]]) -> dict[str, Any]:
    """Bounded source-only def/use graph; no target or model decision is read."""
    count = len(operations)

    def unsupported(reason: str) -> dict[str, Any]:
        return {"supported": False, "reason": reason}

    if count > MAX_OPERATIONS or len(body) > MAX_SOURCE_CHARS:
        return unsupported("analysis_budget")
    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) != count or not lines:
        return unsupported("source_ir_alignment")
    if "\t" in body or len({len(line) - len(line.lstrip()) for line in lines}) != 1:
        return unsupported("nested_layout")
    if _OPAQUE.search(body):
        return unsupported("opaque_syntax")
    args_by_index = []
    for line, (op, args) in zip(lines, operations):
        parts = line.strip().split(None, 1)
        head = "intro" if parts[0] == "intros" else parts[0]
        tail = " ".join(parts[1].split()) if len(parts) > 1 else ""
        if head != op or tail != " ".join(" ".join(args).split()):
            return unsupported("source_ir_alignment")
        args_by_index.append(tail)

    definitions: dict[str, int] = {}
    dependencies: list[set[int]] = []
    removable: set[int] = set()
    for index, ((op, _), args) in enumerate(zip(operations, args_by_index)):
        defined = None
        refs = args
        if op == "have":
            match = _HAVE.fullmatch(args)
            if match is None:
                return unsupported("unsupported_binding")
            defined = match["name"] or "this"
            if defined == "_" or defined in definitions:
                return unsupported("ambiguous_binding")
            refs = (match["type"] or "") + " " + match["term"]
            removable.add(index)
        names = set(_NAMES.findall(refs))
        required = {definitions[name] for name in names if name in definitions}
        # Tactic search can use unnamed context facts; a lexical name scan
        # cannot justify dropping those facts. Holes can also invoke inference.
        if op not in {"have", "exact", "apply", "refine"} or "_" in names or "?" in refs:
            required.update(definitions.values())
        dependencies.append(required)
        if defined is not None:
            definitions[defined] = index

    return {"supported": True, "reason": "flat_def_use", "bindings": sorted(removable),
            "dependencies": [sorted(items) for items in dependencies]}


def close_deletions(body: str, operations: Sequence[tuple[str, Sequence[str]]],
                    selected: Sequence[int]) -> dict[str, Any]:
    """Retain source prerequisites; unsupported syntax keeps the source.

    This may exceed a proposed length limit rather than sever dependencies.
    """
    count = len(operations)
    proposed = sorted({i for i in selected if type(i) is int and 0 <= i < count})
    report: dict[str, Any] = {
        "schema": "jevops-deletion-dependencies/v1", "enabled": True,
        "authority": "lexical_hint_requires_Lean", "proposed_indices": proposed,
        "kept_indices": proposed, "restored": [], "supported": True,
        "reason": "no_deletions", "teacher_used": False,
    }
    if len(proposed) == count:
        return report
    analysis = analyze_dependencies(body, operations)
    if not analysis["supported"]:
        report.update(supported=False, reason=analysis["reason"], kept_indices=list(range(count)),
                      restored=[{"index": i, "reason": analysis["reason"]} for i in range(count) if i not in proposed])
        return report
    dependencies = analysis["dependencies"]
    kept = set(proposed) | (set(range(count)) - set(analysis["bindings"]))
    reasons = {i: {"index": i, "reason": "stateful_operation"} for i in kept if i not in proposed}
    # Edges always point backward in this deliberately flat grammar. A reverse
    # pass computes transitive closure without an unbounded fixed-point loop.
    for index in range(count - 1, -1, -1):
        if index in kept:
            for dependency in sorted(dependencies[index]):
                if dependency not in kept:
                    reasons[dependency] = {"index": dependency, "reason": "required_dependency", "required_by": index}
                    kept.add(dependency)
    report.update(reason="dependency_closure", kept_indices=sorted(kept),
                  restored=[reasons[i] for i in sorted(reasons)],
                  dependency_edges=sum(map(len, dependencies)))
    return report
