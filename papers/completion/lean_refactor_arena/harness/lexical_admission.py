"""Local, bounded Lean tactic admission fallback for the LRA harness.

This is deliberately only a lexical boundary.  It never claims a proof is
valid; the tag-pinned Lake/Lean compiler remains the only proof oracle.  The
implementation mirrors the important checks from the optional TypeSafe
supervisor adapter so a clean JevOps checkout can still run benchmark
self-checks without installing the full accelerator stack.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureCode(str, Enum):
    NONE = ""
    MALFORMED_RECONSTRUCTION = "malformed_reconstruction"
    FORBIDDEN_IMPORT = "forbidden_import"
    INCOMPLETE_PROOF = "incomplete_proof"
    FORBIDDEN_DECLARATION = "forbidden_declaration"
    SOURCE_COPY = "source_copy"
    THEOREM_SUBSTITUTION = "theorem_substitution"
    STATEMENT_MISMATCH = "statement_mismatch"


@dataclass(frozen=True)
class Admission:
    accepted: bool
    failure_code: FailureCode
    reason: str
    proof_sha256: str = ""
    checked_source_sha256: str = ""
    checked_source: str = ""
    theorem_id: str = ""
    declaration_name: str = ""


_IMPORT = re.compile(r"(?im)(?:^|[\r\n;])\s*(?:prelude\s+)?import\b")
_IMPORT_ANY = re.compile(r"(?i)(?<![A-Za-z0-9_'])import(?![A-Za-z0-9_'])")
_INCOMPLETE = re.compile(r"(?i)(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx)(?![A-Za-z0-9_'])")
_DECLARATION = re.compile(
    r"(?im)(?:^|[\r\n;])\s*(?:"
    r"axiom|constant|theorem|lemma|example|def|opaque|abbrev|instance|"
    r"inductive|structure|class|namespace|section|end|universe|variable|"
    r"include|omit|open|export|attribute|set_option|local|scoped|"
    r"syntax|macro|elab|mutual|prelude|private|protected|noncomputable|"
    r"partial|unsafe|#\w+"
    r")\b"
)
_DECLARATION_ANY = re.compile(r"(?i)\b(?:axiom|theorem|lemma|unsafe\s+(?:def|theorem)|sorryAx)\b")
_SOURCE_MARKER = re.compile(
    r"(?im)^\s*(?:diff --git|index [0-9a-f]+\.\.[0-9a-f]+|"
    r"--- (?:a/|/dev/null)|\+\+\+ (?:b/|/dev/null)|@@ )"
)


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reject(
    code: FailureCode,
    reason: str,
    proof: str,
    theorem_id: str,
    declaration_name: str,
) -> Admission:
    return Admission(
        accepted=False,
        failure_code=code,
        reason=reason,
        proof_sha256=_digest(proof) if proof else "",
        theorem_id=theorem_id,
        declaration_name=declaration_name,
    )


def admit_lean_proof_text(
    proof_text: str,
    native_source: str,
    *,
    theorem_id: str = "",
    declaration_name: str = "",
    model_artifact_id: str = "",
    proof_placeholder: str = "sorry",
    expected_statement: str = "",
    canonical_source: str = "",
    max_proof_bytes: int = 512 * 1024,
) -> Admission:
    del model_artifact_id
    if not isinstance(proof_text, str) or not isinstance(native_source, str):
        raise TypeError("proof_text and native_source must be strings")
    proof = proof_text.strip()
    if not proof:
        return _reject(
            FailureCode.MALFORMED_RECONSTRUCTION,
            "Lean proof text is empty",
            proof,
            theorem_id,
            declaration_name,
        )
    if len(proof.encode("utf-8")) > int(max_proof_bytes):
        return _reject(
            FailureCode.MALFORMED_RECONSTRUCTION,
            "Lean proof text exceeds the admission byte limit",
            proof,
            theorem_id,
            declaration_name,
        )
    if "\x00" in proof or any(ord(char) < 32 and char not in "\r\n\t" for char in proof):
        return _reject(
            FailureCode.MALFORMED_RECONSTRUCTION,
            "Lean proof text contains forbidden control characters",
            proof,
            theorem_id,
            declaration_name,
        )
    if _IMPORT.search(proof) or _IMPORT_ANY.search(proof):
        return _reject(
            FailureCode.FORBIDDEN_IMPORT,
            "Lean proof text cannot add imports",
            proof,
            theorem_id,
            declaration_name,
        )
    if _INCOMPLETE.search(proof):
        return _reject(
            FailureCode.INCOMPLETE_PROOF,
            "Lean proof text contains sorry, admit, or sorryAx",
            proof,
            theorem_id,
            declaration_name,
        )
    if _DECLARATION.search(proof) or _DECLARATION_ANY.search(proof):
        return _reject(
            FailureCode.FORBIDDEN_DECLARATION,
            "Lean proof text contains a declaration or unsafe command",
            proof,
            theorem_id,
            declaration_name,
        )
    if _SOURCE_MARKER.search(proof) or proof_placeholder in proof:
        return _reject(
            FailureCode.SOURCE_COPY,
            "Lean proof text contains source or patch-copy markers",
            proof,
            theorem_id,
            declaration_name,
        )
    for identity in (theorem_id, declaration_name):
        if identity and re.search(
            rf"(?<![A-Za-z0-9_'.]){re.escape(identity)}(?![A-Za-z0-9_'.])",
            proof,
        ):
            return _reject(
                FailureCode.THEOREM_SUBSTITUTION,
                "Lean proof text references the declaration being defined",
                proof,
                theorem_id,
                declaration_name,
            )
    if expected_statement:
        return _reject(
            FailureCode.STATEMENT_MISMATCH,
            "expected_statement is not a valid JSONL prefix binding",
            proof,
            theorem_id,
            declaration_name,
        )
    source_for_copy_check = canonical_source or native_source
    normalized_proof = " ".join(proof.split())
    for line in source_for_copy_check.splitlines():
        normalized_line = " ".join(line.split())
        if len(normalized_line) >= 40 and normalized_line != proof_placeholder:
            if normalized_line in normalized_proof:
                return _reject(
                    FailureCode.SOURCE_COPY,
                    "Lean proof text copied canonical source text",
                    proof,
                    theorem_id,
                    declaration_name,
                )
    if native_source.count(proof_placeholder) != 1:
        return _reject(
            FailureCode.THEOREM_SUBSTITUTION,
            "canonical Lean source must contain exactly one proof placeholder",
            proof,
            theorem_id,
            declaration_name,
        )
    checked_source = native_source.replace(proof_placeholder, proof, 1)
    if checked_source.count(proof) != 1:
        return _reject(
            FailureCode.SOURCE_COPY,
            "proof text must occur exactly once in reconstructed source",
            proof,
            theorem_id,
            declaration_name,
        )
    return Admission(
        accepted=True,
        failure_code=FailureCode.NONE,
        reason="proof text admitted for later tag-pinned Lean checking",
        proof_sha256=_digest(proof),
        checked_source_sha256=_digest(checked_source),
        checked_source=checked_source,
        theorem_id=theorem_id,
        declaration_name=declaration_name,
    )
