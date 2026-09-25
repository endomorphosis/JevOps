"""Score a Leanstral legal or equation reply. Lake is necessary, not sufficient.

A file that only restates a definition, or proves a variable equal to itself,
is a failure even when Lake builds it.
"""
from __future__ import annotations

import re

_DEF_LITERAL = re.compile(r"^def\s+(\w+)\b[^=\n]*=\s*(\d+)\s*$", re.M)
_THEOREM = re.compile(r"^theorem\s+\w+[^:]*:\s*(.*?)\s*:=\s*by\b", re.M | re.S)
_SELF_EQ = re.compile(r"(?:→|->)\s*([A-Za-z_]\w*)\s*=\s*\1\b")
_NAME_EQ = re.compile(r"^\(?\s*(\w+)\s*=\s*(\d+)\s*\)?\s*$")


def defined_literals(source: str) -> dict[str, str]:
    return {name: literal for name, literal in _DEF_LITERAL.findall(source)}


def theorem_statements(source: str) -> list[str]:
    return [" ".join(body.split()) for body in _THEOREM.findall(source)]


def tautology_theorems(source: str) -> list[str]:
    """Names of theorems that only restate a definition or prove a variable equal to itself."""

    definitions = defined_literals(source)
    names: list[str] = []
    for match in re.finditer(r"^theorem\s+(\w+)[^:]*:\s*(.*?)\s*:=\s*by\b", source, re.M | re.S):
        statement = " ".join(match.group(2).split())
        if is_tautology(statement, definitions):
            names.append(match.group(1))
    return names


def is_tautology(statement: str, definitions: dict[str, str]) -> bool:
    compact = " ".join(statement.split())
    if _SELF_EQ.search(compact):
        return True
    matched = _NAME_EQ.match(compact)
    return bool(matched and definitions.get(matched.group(1)) == matched.group(2))


def faithful(item_id: str, source: str, *, lake_ok: bool) -> bool:
    """True only for a Lake-built file that states the frozen fact."""

    if not lake_ok or "theorem " not in source:
        return False
    if any(word in source.split() for word in ("sorry", "admit", "axiom")) or "import " in source:
        return False
    if "a = a" in source and "def " not in source:
        return False
    definitions = defined_literals(source)
    statements = theorem_statements(source)
    if not statements or any(is_tautology(item, definitions) for item in statements):
        return False
    if item_id == "E1":
        return "+ 0" in source or "n+0" in source
    if item_id == "E2":
        return "0 +" in source or "0+" in source
    if item_id == "E3":
        return _pair(statements, "24", "25") and _pair(statements, "6", "7")
    if item_id == "E4":
        joined = " ".join(statements)
        return ("5" in joined and "100" in joined) and ("6" in joined and "110" in joined)
    if item_id == "E5":
        return _pair(statements, "25", "6") and "66" in " ".join(statements) and "67" in " ".join(statements)
    return False


def _pair(statements: list[str], left: str, right: str) -> bool:
    return any(left in item and right in item for item in statements)
