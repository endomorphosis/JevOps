"""Closed portable rewrite vocabulary for unverified Arena proposals.

No legacy memory, token hooks, provider, compiler or proof authority is used.
These are bounded textual heuristics; the native selector checks every draft.
"""
from __future__ import annotations

import re

from . import folds
from .arena import intake_error, reference_tokens

_FOLDS = {
    "port_exact_hyp": folds.fold_exact_hyp,
    "port_use_exact": folds.fold_use_exact,
    "port_use_exact_reuse": folds.fold_use_exact_reuse,
    "port_ctor_pair_exacts": folds.fold_ctor_pair_exacts,
    "port_semi_assumption": folds.fold_semi_assumption,
    "port_repeat_par_grind": folds.fold_repeat_par_grind,
    "port_grind_only_to_grind": folds.fold_grind_only_to_grind,
    "port_drop_unfold_before_split": folds.fold_drop_unfold_before_split,
    "port_drop_try_simp_all": folds.fold_drop_try_simp_all,
    "port_drop_intro_before_simp_all": folds.fold_drop_intro_before_simp_all,
    "port_trim_intro_names": folds.fold_trim_intro_names,
    "port_unused_intros": folds.fold_unused_intros,
    "port_trailing_tuple_comma": folds.fold_trailing_tuple_comma,
    "port_redundant_inner_simp": folds.fold_redundant_inner_simp,
    "port_hoist_repeated_simp": folds.fold_hoist_repeated_simp,
}
_COUNTED = {"port_use_exact_reuse", "port_grind_only_to_grind", "port_hoist_repeated_simp"}
_SHORTEN = {"port_shorten_" + name: (old, new) for name, old, new in folds.SHORTEN_IDENTS}
PORTABLE_RULES = (*_FOLDS, *_SHORTEN)


def portable_proposal(source: str, statement: str, rule: str) -> str | None:
    """Apply one allowlisted body edit, with explicit reference-compatible cost.

    Unsupported quoted/comment syntax and large bodies abstain before folds run.
    Length-neutral edits may still matter for heartbeats, but identifier
    abbreviations cannot claim token savings merely by shortening a name.
    """
    if type(rule) is not str or rule not in PORTABLE_RULES:
        raise ValueError("unknown portable Arena rule")
    if intake_error(source, statement):
        return None
    suffix = source[len(statement):]
    marker = re.match(r"\s*:=\s*by\b", suffix)
    if marker is None:
        return None
    prefix, body = statement + suffix[:marker.end()], suffix[marker.end():].lstrip("\n")
    if (len(body) > 32768 or len(body.splitlines()) > 256
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None

    def count(text: str) -> int:
        return reference_tokens(prefix + "\n" + text, statement)

    if rule in _SHORTEN:
        draft = folds.fold_shorten_ident(body, *_SHORTEN[rule], token_fn=count)
    elif rule in _COUNTED:
        draft = _FOLDS[rule](body, token_fn=count)
    else:
        draft = _FOLDS[rule](body)
    if draft == body or not draft.strip():
        return None
    result = prefix + "\n" + draft
    return None if intake_error(result, statement) else result
