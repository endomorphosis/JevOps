"""Render one classified legal pattern as Lean, and reject a changed statement.

The pattern comes from the datasets legal-document processor. This module
does not segment text, call a deontic converter, or treat a compiling file
as faithful until the theorem statements still match.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any


_THEOREM = re.compile(r"^theorem\s+\w+[^:]*:\s*(.*?)\s*:=\s*by\b", re.M | re.S)
_MODULE = "ipfs_datasets_py.logic.legal_document_workspace"


def load_autoformal():
    """Load the workspace legal autoformalization tools."""

    name = "ipfs_datasets_py.logic.autoformal_workspace"
    loaded = sys.modules.get(name)
    if loaded is not None:
        return loaded
    path = Path(__file__).resolve().parents[2] / "external" / "ipfs_datasets" / "ipfs_datasets_py" / "logic" / "autoformal" / "__init__.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"autoformal tools are not at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def legal_documents():
    """Load the workspace logic processor, not another checkout on sys.path."""

    loaded = sys.modules.get(_MODULE)
    if loaded is not None:
        return loaded
    path = Path(__file__).resolve().parents[2] / "external" / "ipfs_datasets" / "ipfs_datasets_py" / "logic" / "legal_document.py"
    spec = importlib.util.spec_from_file_location(_MODULE, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"legal document processor is not at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE] = module
    spec.loader.exec_module(module)
    return module


def statements(source: str) -> list[str]:
    return [" ".join(body.split()) for body in _THEOREM.findall(source)]


_MINIMUM = re.compile(r"^(?:at_least|minimum)_(\d+)$")
_AMOUNT = re.compile(r"^(base|extra|cutoff)_(\d+)$")
_DAY_VALUE = re.compile(r"^(\d+)\s+days?$")
_NOT_MINIMUM = ("within", "longer", "at_most", "day_of", "term_of")


def _minimum_from_records(rule: dict[str, Any]) -> dict[str, Any] | None:
    """A threshold only when the parser kept kind minimum_duration and the digits."""

    for record in rule.get("temporal_records") or []:
        if not isinstance(record, dict) or record.get("temporal_kind") != "minimum_duration":
            continue
        quantity = record.get("quantity")
        value = str(record.get("value") or "").strip().lower()
        match = _DAY_VALUE.match(value)
        if isinstance(quantity, int) and quantity > 0 and match and int(match.group(1)) == quantity:
            return {"kind": "threshold", "fail": quantity - 1, "meet": quantity}
    return None


def pattern_from_rule(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    """A Lean pattern only when the rule already states one. A deadline is not a minimum."""

    if not isinstance(rule, dict):
        return None
    recorded = _minimum_from_records(rule)
    if recorded is not None:
        return recorded
    parts = [str(item) for item in list(rule.get("temporal") or []) + list(rule.get("conditions") or [])]
    if any(any(token in part for token in _NOT_MINIMUM) for part in parts):
        return None
    amounts: dict[str, int] = {}
    minima: list[int] = []
    for part in parts:
        amount = _AMOUNT.match(part)
        if amount:
            amounts[amount.group(1)] = int(amount.group(2))
            continue
        minimum = _MINIMUM.match(part)
        if minimum:
            minima.append(int(minimum.group(1)))
    if set(amounts) == {"base", "extra", "cutoff"}:
        return {"kind": "amount", "base": amounts["base"], "extra": amounts["extra"], "cutoff": amounts["cutoff"]}
    if len(minima) == 1 and minima[0] > 0:
        return {"kind": "threshold", "fail": minima[0] - 1, "meet": minima[0]}
    if len(minima) == 2 and minima[0] != minima[1] and all(item > 0 for item in minima):
        return {"kind": "conjunction", "bounds": minima}
    return None


def render_lean(pattern: dict[str, Any] | None) -> str:
    """Lean for one pattern. Empty when there is nothing to prove."""

    if not pattern:
        return ""
    kind = pattern.get("kind")
    if kind == "threshold":
        fail, meet = int(pattern["fail"]), int(pattern["meet"])
        return (
            f"def bound : Nat := {meet}\n"
            "def meets (n : Nat) : Bool := decide (bound <= n)\n"
            f"theorem boundary : ((meets {fail} = false) /\\ (meets {meet} = true)) := by\n"
            "  unfold meets bound\n"
            "  decide\n"
        )
    if kind == "conjunction":
        left, right = (int(item) for item in pattern["bounds"])
        return (
            f"def bound0 : Nat := {left}\n"
            f"def bound1 : Nat := {right}\n"
            "def eligible (n0 n1 : Nat) : Bool := decide (bound0 <= n0 /\\ bound1 <= n1)\n"
            f"theorem bound0Boundary : ((eligible {left - 1} {right} = false) /\\ (eligible {left} {right} = true)) := by\n"
            "  unfold eligible bound0 bound1\n"
            "  decide\n"
            f"theorem bound1Boundary : ((eligible {left} {right - 1} = false) /\\ (eligible {left} {right} = true)) := by\n"
            "  unfold eligible bound0 bound1\n"
            "  decide\n"
        )
    if kind == "amount":
        base, extra, cutoff = int(pattern["base"]), int(pattern["extra"]), int(pattern["cutoff"])
        return (
            f"def baseAmount : Nat := {base}\n"
            f"def extraAmount : Nat := {extra}\n"
            f"def dueCutoff : Nat := {cutoff}\n"
            "def amountDue (day : Nat) : Nat := if decide (dueCutoff < day) then baseAmount + extraAmount else baseAmount\n"
            f"theorem onCutoff : amountDue {cutoff} = {base} := by\n"
            "  unfold amountDue dueCutoff baseAmount extraAmount\n"
            "  decide\n"
            f"theorem afterCutoff : amountDue {cutoff + 1} = {base + extra} := by\n"
            "  unfold amountDue dueCutoff baseAmount extraAmount\n"
            "  decide\n"
        )
    return ""


def lock_statement(expected: str, reply: str) -> dict[str, Any]:
    """Accept a reply only when its theorem statements match. Import is refused first."""

    raw = str(reply or "")
    if "import " in raw or "import " in str(expected or ""):
        return {"ok": False, "error": "imports_refused", "source": ""}
    if any(word in raw.split() for word in ("sorry", "admit", "axiom")):
        return {"ok": False, "error": "sorry_or_axiom", "source": ""}
    expected_statements = statements(expected)
    if not expected_statements:
        return {"ok": False, "error": "no_harness_statement", "source": ""}
    if "theorem " not in raw:
        if len(expected_statements) != 1:
            return {"ok": False, "error": "proof_per_theorem_required", "source": ""}
        tactic = raw.strip()
        if not tactic:
            return {"ok": False, "error": "statement_missing", "source": ""}
        head, _sep, _tail = expected.partition(":= by")
        return {"ok": True, "error": "", "source": head + ":= by\n  " + tactic + "\n"}
    if statements(raw) != expected_statements or not raw.lstrip().startswith(("def ", "theorem ")):
        return {"ok": False, "error": "statement_changed", "source": ""}
    return {"ok": True, "error": "", "source": raw if raw.endswith("\n") else raw + "\n"}
