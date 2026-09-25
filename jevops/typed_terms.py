"""Elaborated-term proposals via Lean, not textual binder substitution.

`show_term` supplies a term in the original local context. Only a shorter,
single-line `exact` suggestion is considered; replay in the original source
must pass compilation and axiom audit. This is not typed equality saturation.
"""
from __future__ import annotations

import textwrap
import re
from typing import Any, Callable, Mapping

from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .rewrite_policy import body_of, supported
from .solver_feedback import _accepted, source_digest, suggestions


def collect_typed_term(source: str, compile_fn: Callable[[str], Mapping[str, Any]], *, candidate_gate=None) -> dict[str, Any]:
    prefix, body = body_of(source)
    if (not prefix or not supported(body) or len(source) > 65_536 or
            re.search(r"\?|(?<![\w'])_(?![\w'])", prefix)):
        return {"ok": False, "reason": "unsupported_source", "trajectory": []}
    attempts = []
    def check(text):
        try:
            result = dict(compile_fn(text))
        except Exception as exc:
            result = {"theorem_ok": False, "reason": type(exc).__name__}
        attempts.append({"source_sha256": source_digest(text), "compile": result})
        return result

    original = check(source)
    best, best_tokens, trajectory = source, proof_source_tokens(source), []
    reason = "unverified_source" if not _accepted(original) else "no_verified_shorter_term"
    if _accepted(original):
        # Printing width only affects the probe. It never enters the student
        # target or the final theorem. Multiline suggestions still abstain.
        probe = prefix + "\n  set_option format.width 4096 in\n    show_term\n" + textwrap.indent(body, "      ") + "\n"
        site = {"line": prefix.count("\n") + 3, "column": 4}
        receipt = check(probe)
        for draft in suggestions(receipt, probe, site):
            if not draft.startswith("exact "):
                continue
            candidate = prefix + "\n  " + draft + "\n"
            tokens = proof_source_tokens(candidate)
            if tokens >= best_tokens:
                continue
            replay = check(candidate)
            if not _accepted(replay):
                continue
            if candidate_gate is not None and candidate_gate(source, candidate) is not True:
                continue
            best, best_tokens, reason = candidate, tokens, "verified_typed_term"
            trajectory = [{"before_source": source, "after_source": candidate,
                           "before_tokens": proof_source_tokens(source), "after_tokens": tokens,
                           "strategy": "typed_term", "kind": "elaborated_term_replay",
                           "probe_sha256": source_digest(probe), "suggestion": draft, "compile": replay}]
            break
    return {"schema": "jevops-typed-term/v1", "ok": _accepted(original), "reason": reason,
            "tokenizer_id": TOKENIZER_ID, "best_source": best, "best_tokens": best_tokens,
            "source_tokens": proof_source_tokens(source), "source_compile": original,
            "trajectory": trajectory, "compile_attempts": attempts, "minimality_proven": False}
