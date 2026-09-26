"""Render a legal pattern and lock its definitions and theorem headers.

The pattern comes from the datasets legal-document processor. This module
does not establish semantic fidelity or verify proofs. The source lock accepts
only a closed, bounded proof-edit profile for the small generated packages;
it is deliberately not a general Lean parser or an execution sandbox.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, replace
import hashlib
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any


_THEOREM = re.compile(r"^theorem\s+\w+[^:]*:\s*(.*?)\s*:=\s*by\b", re.M | re.S)
_MODULE = "ipfs_datasets_py.logic.legal_document_workspace"

LOCK_SCHEMA = "jevops-legal-source-lock/v1"
PROOF_PROFILE = "legal-numeric-tactics/v1"
MAX_SOURCE_BYTES = 16_384
MAX_THEOREMS = 16
MAX_PROOF_LINES = 128
MAX_PROOF_STEPS = 256
_IDENT = r"[A-Za-z][A-Za-z0-9_]*"
_DEF = re.compile(r"def (" + _IDENT + r") [^\n]+ := [^\n]+\n")
_HEADER = re.compile(r"(theorem (" + _IDENT + r") : [^\n]+? := by)([^\n]*)\n")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
_ATOMIC_TACTICS = frozenset(("decide", "rfl", "constructor", "trivial", "assumption", "simp", "simpa", "exact rfl"))


class _UnsupportedPackage(ValueError):
    pass


@dataclass(frozen=True)
class _ProofSlot:
    name: str
    header: str  # Complete immutable header through `:= by`.
    body: str


@dataclass(frozen=True)
class _Package:
    prefix: str  # Includes every helper definition, byte-for-byte.
    helpers: tuple[str, ...]
    slots: tuple[_ProofSlot, ...]

    def source(self) -> str:
        return self.prefix + "".join(slot.header + slot.body for slot in self.slots)


def _source_text(value: Any) -> str:
    if type(value) is not str:
        raise _UnsupportedPackage("source_type")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise _UnsupportedPackage("unsupported_source") from exc
    if size + int(bool(value) and not value.endswith("\n")) > MAX_SOURCE_BYTES:
        raise _UnsupportedPackage("source_too_large")
    # No lexer ambiguity from comments, strings, escaped identifiers, control
    # characters or non-ASCII whitespace in this deliberately small profile.
    if (any(token in value for token in ('--', '/-', '-/', '"', "'", "`", "«", "»"))
            or any((ord(c) < 32 and c != "\n") or ord(c) == 127
                   or (c.isspace() and c not in " \n") for c in value)):
        raise _UnsupportedPackage("unsupported_source")
    return value if not value or value.endswith("\n") else value + "\n"


def _package(source: str) -> _Package:
    """Single-line defs followed by single-line, unparameterized theorem heads.

    Proof lines must be indented. No sections, commands, attributes, trailing
    declarations, comments, strings, or syntax extensions are recognized.
    The caller's definitions/types are trusted inputs, not interpreted here.
    """
    prefix, helpers, slots, names = [], [], [], set()
    for line in source.splitlines(keepends=True):
        if not slots and not line.strip():
            prefix.append(line)
            continue
        definition = _DEF.fullmatch(line) if not slots else None
        if definition is not None:
            name = definition[1]
            if name in names or "by" in _WORD.findall(line) or line.count(":=") != 1:
                raise _UnsupportedPackage("unsupported_package")
            names.add(name)
            helpers.append(name)
            prefix.append(line)
            continue
        header = _HEADER.fullmatch(line)
        if header is not None:
            name = header[2]
            if (name in names or len(slots) >= MAX_THEOREMS or header[1].count(":=") != 1
                    or (header[3] and not header[3].startswith(" "))):
                raise _UnsupportedPackage("unsupported_package")
            names.add(name)
            slots.append(_ProofSlot(name, header[1], header[3] + "\n"))
            continue
        if slots and (not line.strip() or line.startswith(" ")):
            slots[-1] = replace(slots[-1], body=slots[-1].body + line)
            continue
        raise _UnsupportedPackage("unsupported_package")
    if not slots:
        raise _UnsupportedPackage("no_harness_statement")
    return _Package("".join(prefix), tuple(helpers), tuple(slots))


def _proof_allowed(body: str, helpers: tuple[str, ...]) -> bool:
    """Closed tactic atoms, optionally composed with ;, <;>, all_goals, bullets.

    References in unfold/simp are ONLY immutable helper names. No arbitrary
    terms, tactic options, native evaluation, quotations, or metaprogramming.
    Lean still checks syntax, goal completion and the resulting proof.
    """
    lines = body.splitlines()
    if len(lines) > MAX_PROOF_LINES:
        return False
    steps = 0
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith("· "):
            text = text[2:]
        for atom in re.split(r"\s*(?:<;>|;)\s*", text):
            steps += 1
            if steps > MAX_PROOF_STEPS:
                return False
            if atom.startswith("all_goals "):
                atom = atom[len("all_goals "):]
            if atom in _ATOMIC_TACTICS:
                continue
            unfold = re.fullmatch(r"unfold (" + _IDENT + r"(?: +" + _IDENT + r")*)", atom)
            if unfold and all(name in helpers for name in unfold[1].split()):
                continue
            simplify = re.fullmatch(r"(?:simp|simpa)(?: only)? \[([A-Za-z0-9_, ]*)\]", atom)
            if simplify:
                names = [name.strip() for name in simplify[1].split(",")] if simplify[1].strip() else []
                if all(name in helpers for name in names):
                    continue
            return False
    return steps > 0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lock_record(expected: _Package, candidate: _Package) -> dict[str, Any]:
    protected = {"schema": LOCK_SCHEMA, "proof_profile": PROOF_PROFILE,
                 "prefix": expected.prefix, "headers": [slot.header for slot in expected.slots]}
    return {
        "schema": LOCK_SCHEMA, "proof_profile": PROOF_PROFILE,
        "protected_sha256": _sha(json.dumps(protected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
        "expected_source_sha256": _sha(expected.source()),
        "candidate_source_sha256": _sha(candidate.source()),
        "theorems": [slot.name for slot in expected.slots],
        "verification_performed": False,
    }


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
    """Legacy display/extraction helper, never an admission or parsing boundary."""
    return [" ".join(body.split()) for body in _THEOREM.findall(source)]


_MINIMUM = re.compile(r"^(?:at_least|minimum)_(\d+)$")
_AMOUNT = re.compile(r"^(base|extra|cutoff)_(\d+)$")
_DAY_VALUE = re.compile(r"^(\d+)\s+days?$")
_NOT_MINIMUM = ("within", "longer", "at_most", "day_of", "term_of")
_MODALITY_CODE = {"O": 0, "P": 1, "F": 2}


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


def _norm_from_rule(rule: dict[str, Any]) -> dict[str, Any] | None:
    """Lock a duty's modality and a fingerprint of its text. Not a proof of the duty."""

    modality = str(rule.get("modality") or "")
    if modality not in _MODALITY_CODE:
        return None
    actor = str(rule.get("actor") or "").strip()
    action = str(rule.get("action") or "").strip()
    if not actor or not action:
        return None
    payload = "\n".join((modality, actor, action, str(rule.get("object") or "").strip()))
    fingerprint = int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)
    return {"kind": "norm", "modality": _MODALITY_CODE[modality], "fingerprint": fingerprint}


def pattern_from_rule(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    """Render supported numeric patterns; a deadline or generic norm is not one.

    A modality and text fingerprint cannot supply a legal admission target.
    Explicit norm rendering remains a diagnostic utility outside this gate.
    """

    if not isinstance(rule, dict):
        return None
    recorded = _minimum_from_records(rule)
    if recorded is not None:
        return recorded
    parts = [str(item) for item in list(rule.get("temporal") or []) + list(rule.get("conditions") or [])]
    blocked_minimum = any(any(token in part for token in _NOT_MINIMUM) for part in parts)
    if not blocked_minimum:
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


def admission_ready(rule: dict[str, Any] | None, *, status: str = "roundtrip_ok") -> dict[str, Any]:
    """Whether a round-tripped rule can be locked for ``lake build Legal``.

    This does not call Lake. ``ready`` is not ``admitted``.
    A within-duration is not a minimum. Generic norms are non-renderable here;
    proving a modality/fingerprint identity cannot make a clause ready.
    A compiled row that has not round-tripped is not ready either.
    """

    if status != "roundtrip_ok":
        return {"ready": False, "reason": "not_roundtrip", "admitted": False, "formalized": False}
    pattern = pattern_from_rule(rule if isinstance(rule, dict) else None)
    if pattern is None:
        return {"ready": False, "reason": "not_renderable", "admitted": False, "formalized": False}
    source = render_lean(pattern)
    if not str(source or "").strip():
        return {"ready": False, "reason": "empty_lean", "admitted": False, "formalized": False}
    locked = lock_statement(source, source)
    if not locked.get("ok"):
        return {
            "ready": False,
            "reason": str(locked.get("error") or "lock_failed"),
            "admitted": False,
            "formalized": False,
        }
    return {
        "ready": True,
        "reason": "",
        "pattern": str(pattern.get("kind") or ""),
        "admitted": False,
        "formalized": False,
    }


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
    if kind == "norm":
        return _render_norm(int(pattern["modality"]), int(pattern["fingerprint"]))
    return ""


def _render_norm(modality: int, fingerprint: int, *, suffix: str = "") -> str:
    """One decidable modality lock. The suffix keeps a batch of norms in one file."""

    return (
        f"def modalityCode{suffix} : Nat := {modality}\n"
        f"def normFingerprint{suffix} : Nat := {fingerprint}\n"
        f"def normLocked{suffix} (m f : Nat) : Bool := decide (m <= 2 /\\ f = normFingerprint{suffix})\n"
        f"theorem normBoundary{suffix} : normLocked{suffix} modalityCode{suffix} normFingerprint{suffix} = true := by\n"
        f"  unfold normLocked{suffix} modalityCode{suffix} normFingerprint{suffix}\n"
        "  decide\n"
    )


def render_norm_batch(patterns: list[dict[str, Any]], *, max_bytes: int = 16_000) -> list[str]:
    """Split norm locks into Lake-sized sources. Empty when nothing is a norm.

    A batch compiling is not an admission of the clauses.
    """

    files: list[str] = []
    chunk: list[str] = []
    size = 0
    index = 0
    for pattern in patterns:
        if not isinstance(pattern, dict) or pattern.get("kind") != "norm":
            continue
        piece = _render_norm(int(pattern["modality"]), int(pattern["fingerprint"]), suffix=str(index))
        encoded = len(piece.encode("utf-8"))
        if chunk and size + encoded > max_bytes:
            files.append("".join(chunk))
            chunk, size = [], 0
        chunk.append(piece)
        size += encoded
        index += 1
    if chunk:
        files.append("".join(chunk))
    return files


def lock_statement(expected: str, reply: str) -> dict[str, Any]:
    """Lock the complete generated source envelope; permit bounded proof edits.

    Retains the legacy result keys. `ok` means ONLY that source admission passed,
    never that Lean ran or that a legal interpretation was verified. The added
    `lock` content hashes bind source bytes, not the external toolchain/context.
    General Lean syntax outside this explicit profile now fails closed.
    """
    def fail(error):
        return {"ok": False, "error": error, "source": ""}

    # Bound input size before regexes, and keep the legacy import error even
    # for alternative whitespace. Do not invoke __str__ on arbitrary objects.
    for value in (expected, reply):
        if type(value) is not str:
            return fail("source_type")
        if len(value) > MAX_SOURCE_BYTES:
            return fail("source_too_large")
        try:
            if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
                return fail("source_too_large")
        except UnicodeError:
            return fail("unsupported_source")
        words = frozenset(_WORD.findall(value))
        if "import" in words:
            return fail("imports_refused")
        if words & {"sorry", "admit", "axiom", "sorryAx"}:
            return fail("sorry_or_axiom")
    try:
        original, raw = _source_text(expected), _source_text(reply)
        package = _package(original)
        if not all(_proof_allowed(slot.body, package.helpers) for slot in package.slots):
            return fail("unsupported_expected_proof")
        if not raw.strip():
            return fail("statement_missing")
        if raw.lstrip().startswith(("def ", "theorem ")):
            candidate = _package(raw)
            if candidate.prefix != package.prefix:
                return fail("definitions_changed")
            if tuple(slot.header for slot in candidate.slots) != tuple(slot.header for slot in package.slots):
                return fail("statement_changed")
        else:
            if len(package.slots) != 1:
                return fail("proof_per_theorem_required")
            # Prefix EVERY line, not only the first: a bare reply must never
            # inject a command at top level. The grammar additionally refuses
            # arbitrary Lean even if it happens to be indented.
            body = "\n" + textwrap.indent(textwrap.dedent(raw).strip(), "  ") + "\n"
            candidate = replace(package, slots=(replace(package.slots[0], body=body),))
        if not all(_proof_allowed(slot.body, package.helpers) for slot in candidate.slots):
            return fail("unsupported_proof")
        source = candidate.source()
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            return fail("source_too_large")
        return {"ok": True, "error": "", "source": source, "lock": _lock_record(package, candidate)}
    except _UnsupportedPackage as exc:
        return fail(str(exc))
