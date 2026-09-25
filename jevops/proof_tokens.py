"""Explicit, import-order-independent proof-length measurement.

Matches the frozen Lean Refactor Arena local ws/punctuation tokenizer. This is
not a model/BPE tokenizer or a measurement of elaborated proof-term size.
"""
from __future__ import annotations

import re

TOKENIZER_ID = "lra-local-ws-punct/v1"
_TOKEN = re.compile(r"[A-Za-z0-9_']+|[^A-Za-z0-9_\s]")
_BODY = re.compile(r":=\s*by\b", re.IGNORECASE)


def proof_source_tokens(source: str) -> int:
    marker = _BODY.search(source)
    return len(_TOKEN.findall(source[marker.end():] if marker else source))
