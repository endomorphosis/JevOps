"""Explicit axiom auditing; compilation alone is not kernel-only assurance."""
from __future__ import annotations

import re
import json
from collections.abc import Sequence
from typing import Any

STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_AXIOMS = re.compile(r"'([^\n]+?)'\s+(?:depends on axioms:\s*\[([^\]]*)\]|does not depend on any axioms)", re.DOTALL)
_NAME = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*\Z", re.UNICODE)


def audit_axioms(output: str, declarations: Sequence[str], *,
                 allowed_axioms: Sequence[str] = tuple(sorted(STANDARD_AXIOMS))) -> dict[str, Any]:
    """Fail closed on missing/conflicting reports and unexpected axioms.

    Explicit allowlists may include project axioms, but must never be expanded
    using the candidate's own output. Accepts plain or JSON Lean diagnostics.
    """
    requested = list(dict.fromkeys(declarations))
    if not requested or any(not _NAME.fullmatch(n) for n in requested):
        raise ValueError("explicit valid declaration names required")
    messages = []
    for line in output.splitlines():
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            messages.append(line)
        else:
            if isinstance(data, dict) and isinstance(data.get("data"), str):
                messages.append(data["data"])
    output = "\n".join(messages)
    reports: dict[str, list[list[str]]] = {}
    for name, raw in _AXIOMS.findall(output):
        reports.setdefault(name, []).append(sorted(n.strip() for n in raw.split(",") if n.strip()))
    missing = [n for n in requested if n not in reports]
    conflicts = [n for n in requested if n in reports and len({tuple(r) for r in reports[n]}) != 1]
    observed = sorted({a for n in requested for row in reports.get(n, []) for a in row})
    forbidden = sorted(set(observed) - set(allowed_axioms) | (set(observed) & {"sorryAx"}))
    native = [n for n in observed if n in {"Lean.ofReduceBool", "Lean.trustCompiler"} or "._native." in n]
    return {"schema": "jevops-axiom-audit/v1", "accepted": not (missing or conflicts or forbidden),
            "declarations": requested, "axioms": observed, "unexpected_axioms": forbidden,
            "missing_reports": missing, "conflicting_reports": conflicts, "native_axioms": native,
            "allowed_axioms": sorted(set(allowed_axioms)), "independent_kernel_verifier_used": False}


def axiom_audit_command(declaration: str) -> str:
    if not _NAME.fullmatch(declaration):
        raise ValueError("unsupported axiom audit declaration name")
    return f"\n#print axioms _root_.{declaration}\n"


def top_level_declarations(source: str) -> list[str]:
    """Small compiler-helper scope, not a Lean parser. Ambiguity fails closed."""
    if re.search(r"(?m)^\s*(?:namespace|section|end|private|protected|mutual)\b", source):
        raise ValueError("axiom audit helper requires explicit top-level named declarations")
    names = re.findall(r"(?m)^\s*(?:theorem|lemma)\s+([^\s:(]+)", source)
    if not names or any(not _NAME.fullmatch(n) for n in names):
        raise ValueError("axiom audit helper requires top-level named declarations")
    return list(dict.fromkeys(names))
