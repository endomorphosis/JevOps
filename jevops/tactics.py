#!/usr/bin/env python3
"""Lean tactic-block analysis: case spans, PCA/MCA drops, MCA holes, hammers.

Jev does not write Lean. Lake is the oracle. Never docker0.
Not Arena scores. Not Track 2.
"""
from __future__ import annotations

import re
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

CASE = re.compile(r"^(?P<indent> *)case (?P<label>.+?) =>[ \t]*$", re.M)
SIMP_AT = re.compile(r"^(?P<indent> *)simp at \S+\s*$")
HAVE_OBTAIN = re.compile(r"^(?P<indent> *)(have |obtain |rename_i )")
CALC = re.compile(r"^\s*calc\b", re.M)
RENAME = re.compile(r"^( *)rename_i ")
HAVE = re.compile(r"^( *)have ")
RW_BRACKET = re.compile(r"^(?P<indent> *)rw \[([^\]]+)\]\s*$")
HAVE_NAME = re.compile(r"have\s+([A-Za-z0-9_']+)")
MCA_HOLE = re.compile(r"<<<MCA_(\d+) family=([a-z_]+)>>>")

FEATURE_NAMES = (
    "n_cases",
    "n_simp_at",
    "n_simp_all",
    "n_have",
    "n_obtain",
    "n_rename_i",
    "n_induction",
    "n_calc",
    "n_exact",
    "n_apply",
    "n_rw",
    "n_intro",
    "n_ring",
    "n_omega",
    "n_linarith",
    "n_tokens",
    "n_lines",
    "max_indent",
    "n_blank",
)
FAMILY_FEATURES = {
    "dead_code": ("n_have", "n_obtain", "n_rename_i", "n_simp_at"),
    "search_space": ("n_apply", "n_intro", "n_cases"),
    "loop_invariant": ("n_have", "n_induction"),
    "strength_reduction": ("n_simp_at", "n_simp_all", "n_rw"),
    "algebraic_simplification": ("n_rw", "n_calc", "n_ring", "n_omega", "n_linarith", "n_simp_all"),
}
SKELETON_PREFIXES = (
    "induction ",
    "case ",
    "exact ",
    "constructor",
    "exists ",
    "refine ",
    "intro ",
    "intros ",
    "ext ",
    "funext",
    "by_cases",
    "rcases ",
    "obtain ",
)
CLOSERS = ("simp_all", "try simp_all", "omega", "try omega", "constructor", "rfl")
TACTIC_HEAD = (
    "case ",
    "have ",
    "exact ",
    "apply ",
    "refine ",
    "simp",
    "rw ",
    "omega",
    "constructor",
    "intro",
    "induction ",
    "exists ",
    "· ",
    ". ",
)
OPERATORS: tuple[str, ...] = ("<;>", "‹_›", "?_", "←", "|>.", "<|", "$")
OPERATOR_ALTS: dict[str, tuple[str, ...]] = {
    "$": ("",),
    "<;>": (";",),
    "?_": ("_",),
    "‹_›": ("this", "trivial", "rfl"),
    "←": ("",),
    "|>.": (".",),
    "<|": ("$", ""),
}
PHRASE_ALTS: tuple[tuple[str, str], ...] = (
    ("apply And.intro", "constructor"),
    ("intros Hin", "intro"),
    ("apply UpdateStates.update_some", "refine .update_some"),
    ("split at this <;> simp_all", "split at this\n          all_goals simp_all"),
    ("<;> simp_all", "\n          all_goals simp_all"),
    ("(by simp_all [isDefined])", "(UpdateStatesDefined Hups)"),
    ("$ by simp_all", "$ UpdateStatesLength Hups"),
    ("simp [isDefined, Option.isSome] at this", "simp_all [isDefined, Option.isSome]"),
    ("exact Hst", "assumption"),
    ("InitStatesSomeMonotone (by assumption)", "InitStatesSomeMonotone ‹_›"),
)
LEAN_TACTICS: tuple[str, ...] = (
    "simp",
    "simp_all",
    "rw",
    "exact",
    "apply",
    "refine",
    "constructor",
    "assumption",
    "intro",
    "intros",
    "split",
    "all_goals",
    "have",
    "exists",
    "rfl",
    "trivial",
    "grind",
    "omega",
    "decide",
)
STRUCTURE = frozenset({"induction", "case", "rename_i", "generalizing"})
PCA_KEEP_PREFIXES = ("induction ", "case ", "exists ", "intros ")
UNKNOWN_TACTICS = frozenset(
    {
        "aesop",
        "exact?",
        "apply?",
        "hint",
        "native_decide",
        "decide+",
        "tauto",
        "linarith",
        "nlinarith",
        "ring_nf",
    }
)


@dataclass(frozen=True)
class CaseSpan:
    label: str
    start: int
    header_end: int
    end: int
    indent: int


@dataclass(frozen=True)
class Hole:
    hole_id: str
    family: str
    start: int
    end: int
    original: str
    indent: str


def case_spans(text: str) -> list[CaseSpan]:
    from jevops.mask import nested_header_spans

    rows = nested_header_spans(
        text,
        list(CASE.finditer(text)),
        indent_of=lambda match: len(match.group("indent")),
        label_of=lambda match: str(match.group("label")),
    )
    return [
        CaseSpan(
            label=str(row["label"]),
            start=int(row["start"]),
            header_end=int(row["header_end"]),
            end=int(row["end"]),
            indent=int(row["indent"]),
        )
        for row in rows
    ]


def replace_case_body(text: str, span: CaseSpan, body: str) -> str:
    from jevops.mask import replace_span

    return replace_span(text, span.header_end, span.end, body, indent=" " * (span.indent + 2))


def collapse_simp_at(text: str) -> str:
    from jevops.mask import collapse_runs

    return collapse_runs(
        text,
        lambda line: bool(SIMP_AT.match(line)),
        min_run=2,
        replacement=lambda indent, _run: f"{indent}simp_all",
    )


def drop_redundant_simp_at(text: str) -> str:
    """Delete a ``simp at`` run when the next tactic is already ``simp_all``."""

    from jevops.mask import rewrite_runs

    return rewrite_runs(
        text,
        lambda line: bool(SIMP_AT.match(line)),
        following_pred=lambda following: following.startswith("simp_all"),
        min_collapse=2,
        replacement=lambda indent, _run: f"{indent}simp_all",
    )


def drop_have_obtain(text: str) -> str:
    from jevops.binders import drop_unused_binders

    return drop_unused_binders(text, kinds=("rename_i", "have", "obtain"))


def first_case_only(text: str) -> str:
    from jevops.outer import cut_prefix

    spans = case_spans(text)
    if not spans:
        return text
    return cut_prefix(text, spans[0].end)


def count_tactics(tactics: str, *, token_fn: Optional[Callable[[str], int]] = None) -> dict[str, float]:
    from jevops.lean import token_count
    from jevops.pick import count_prefix_lines, line_stats

    extra = line_stats(tactics)
    extra["n_cases"] = float(len(case_spans(tactics)))
    extra["n_tokens"] = float((token_fn or token_count)(tactics))
    return count_prefix_lines(
        tactics,
        {
            "n_simp_at": lambda s: s.startswith("simp at "),
            "n_simp_all": lambda s: s.startswith("simp_all") or s == "simp" or s.startswith("simp ["),
            "n_have": lambda s: s.startswith("have "),
            "n_obtain": lambda s: s.startswith("obtain "),
            "n_rename_i": lambda s: s.startswith("rename_i "),
            "n_induction": lambda s: s.startswith("induction ") or s.startswith("induction\n"),
            "n_calc": lambda s: s.startswith("calc"),
            "n_exact": lambda s: s.startswith("exact "),
            "n_apply": lambda s: s.startswith("apply "),
            "n_rw": lambda s: s.startswith("rw ") or s.startswith("rw["),
            "n_intro": lambda s: s.startswith("intro") or s.startswith("intros "),
            "n_ring": lambda s: s == "ring" or s.startswith("ring "),
            "n_omega": lambda s: s == "omega" or s.startswith("omega "),
            "n_linarith": lambda s: s.startswith("linarith") or s.startswith("nlinarith"),
        },
        extra=extra,
    )


def drop_rename_i(text: str) -> str:
    from jevops.binders import drop_unused_binders

    return drop_unused_binders(text, kinds=("rename_i",))


def drop_have_after_induction(text: str) -> str:
    from jevops.binders import safe_to_drop_span
    from jevops.mask import filter_after_flag

    return filter_after_flag(
        text,
        lambda stripped: stripped.startswith("induction "),
        lambda line, start, end: bool(HAVE.match(line.rstrip("\n")))
        and safe_to_drop_span(text, start, end, line.rstrip("\n")),
    )


def collapse_rw_to_simp(text: str) -> str:
    from jevops.mask import collapse_runs, split_top_level

    def _lemmas(run: Sequence[str]) -> list[str]:
        lemmas: list[str] = []
        for line in run:
            nxt = RW_BRACKET.match(line)
            if nxt:
                lemmas.extend(split_top_level(nxt.group(2)))
        return lemmas

    def _replace(indent: str, run: Sequence[str]) -> str:
        lemmas = _lemmas(run)
        if len(lemmas) >= 2:
            return f"{indent}simp [{', '.join(lemmas)}]"
        return f"{indent}rw [{lemmas[0]}]" if lemmas else run[0]

    return collapse_runs(text, lambda line: bool(RW_BRACKET.match(line)), min_run=1, replacement=_replace)


def keep_calc_only(text: str) -> str:
    from jevops.mask import keep_matching_lines

    if not CALC.search(text):
        return text
    return keep_matching_lines(
        text,
        lambda line: line.strip().startswith("calc") or line.startswith("  "),
        cap=40,
    )


def hole_row(item: Hole) -> dict[str, Any]:
    from jevops.outer import object_fields

    row = object_fields(
        item,
        ("hole_id", "family", "start", "end", "original", "indent"),
        extra={"kind": item.family, "n_tokens": 1},
    )
    return row or {}


def mca_marker(item: Mapping[str, Any]) -> str:
    return f"{item.get('indent') or ''}<<<{item.get('hole_id')} family={item.get('family')}>>>"


def find_holes(tactics: str) -> list[Hole]:
    """Residual MCA spans: simp-at runs, rw runs, rename_i, have."""

    from jevops.mask import scan_line_holes

    rows = scan_line_holes(
        tactics,
        (
            {"match": lambda line: bool(SIMP_AT.match(line)), "min_run": 2, "family": "strength_reduction"},
            {"match": lambda line: bool(RW_BRACKET.match(line)), "min_run": 2, "family": "algebraic_simplification"},
            {"match": lambda line: bool(RENAME.match(line)), "min_run": 1, "family": "dead_code"},
            {"match": lambda line: bool(HAVE.match(line)), "min_run": 1, "family": "loop_invariant"},
        ),
    )
    return [
        Hole(
            hole_id=str(row["hole_id"]),
            family=str(row.get("family") or row.get("kind") or ""),
            start=int(row["start"]),
            end=int(row["end"]),
            original=str(row["original"]),
            indent=str(row.get("indent") or ""),
        )
        for row in rows
    ]


def mask_mca(tactics: str, holes: Sequence[Hole]) -> str:
    from jevops.mask import mask_skeleton as _fn

    if not holes:
        return tactics
    return _fn(tactics, [hole_row(item) for item in holes], marker_fn=mca_marker)


def template_fill(hole: Hole) -> str:
    if hole.family == "strength_reduction":
        return ""
    if hole.family == "algebraic_simplification":
        from jevops.mask import split_top_level

        lemmas = []
        for line in hole.original.splitlines():
            match = RW_BRACKET.match(line)
            if match:
                lemmas.extend(split_top_level(match.group(2)))
        if lemmas:
            return f"{hole.indent}simp [{', '.join(lemmas)}]"
        if "calc" in hole.original:
            return f"{hole.indent}simp_all"
        return f"{hole.indent}omega"
    if hole.family in {"dead_code", "loop_invariant"}:
        return ""
    return hole.original


def apply_fills(tactics: str, holes: Sequence[Hole], fills: Mapping[str, str]) -> str:
    from jevops.mask import apply_named_fills

    return apply_named_fills(tactics, [hole_row(item) for item in holes], fills, marker_fn=mca_marker)


def case_tag(label: str) -> str:
    from jevops.outer import first_token

    return first_token(label)


def replace_case_from(dst: str, src: str, tag: str) -> str:
    from jevops.mask import splice_from
    from jevops.outer import first_where

    want = case_tag(tag)
    dst_span = first_where(case_spans(dst), lambda span: case_tag(span.label) == want)
    src_span = first_where(case_spans(src), lambda span: case_tag(span.label) == want)
    return splice_from(dst, src, dst_span, src_span)


def drop_first_bare_simp_all(tactics: str) -> Optional[str]:
    from jevops.mask import drop_matching_line

    return drop_matching_line(tactics, lambda line: bool(BARE_SIMP_ALL.match(line)), last=False)


def keepbest_variants(kind: str, body: str, reference: str) -> list[tuple[str, str]]:
    """Have-restore and trailing-simp_all variants of a beam draft. Reference is identity."""

    rows: list[tuple[str, str]] = [(kind, body)]
    if kind == "reference":
        return rows
    haves = prefix_have_lines(reference)
    present = {line.strip() for line in body.splitlines()}
    for have in haves:
        if have.strip() in present:
            continue
        name = have_binder_name(have.strip()) or "have"
        rows.append((f"{kind}_have_{name}", insert_haves_before_induction(body, [have])))
    restored = insert_haves_before_induction(body, haves)
    if restored != body:
        rows.append((f"{kind}_haves", restored))
    current = body
    for pass_i in range(1, 4):
        nxt = drop_last_bare_simp_all(current)
        if not nxt or nxt == current:
            break
        rows.append((f"{kind}_nosimp{pass_i}", nxt))
        current = nxt
    return rows


def shorten_keeping_prefix_haves(
    tactics: str,
    extras: Sequence[tuple[str, str]] = (),
    keep_extras: Sequence[tuple[str, str]] = (),
) -> list[tuple[str, str]]:
    """Compiler shortenings that must keep every original prefix ``have``."""

    from jevops.pick import keep_if_contains

    haves = prefix_have_lines(tactics)
    seen: set[str] = {tactics.strip("\n")}
    out: list[tuple[str, str]] = []

    def keep(name: str, body: Optional[str]) -> None:
        keep_if_contains(seen, out, name, body, required=haves)

    keep("simp_set", drop_redundant_simp_at(tactics))
    keep("drop_first_bare_simp", drop_first_bare_simp_all(tactics))
    keep("drop_last_bare_simp", drop_last_bare_simp_all(tactics))
    keep("join_exacts", join_consecutive_exacts(tactics))
    keep("collapse_defined_simp", collapse_defined_simp(tactics))
    keep("join_exacts_drop_last_simp", drop_last_bare_simp_all(join_consecutive_exacts(tactics)))
    for name, body in extras:
        text = str(body or "").strip("\n")
        if text and text not in seen:
            seen.add(text)
            out.append((str(name), text))
    for name, body in keep_extras:
        keep(str(name), body)
    return out


def drop_bare_simp_all(tactics: str) -> str:
    from jevops.mask import rewrite_matching_lines

    return rewrite_matching_lines(tactics, lambda stripped: stripped == "simp_all", lambda *_a: "")


def try_simp_all(tactics: str) -> str:
    from jevops.mask import rewrite_matching_lines

    return rewrite_matching_lines(
        tactics,
        lambda stripped: stripped == "simp_all",
        lambda indent, _stripped, _line: f"{indent}try simp_all",
    )


def have_binder_name(stripped: str) -> str:
    from jevops.mask import lstrip_core
    from jevops.outer import first_group

    return first_group(lstrip_core(stripped), HAVE_NAME, method="match") or ""


def identifier_used(name: str, text: str) -> bool:
    from jevops.repair import ident_used

    if not name:
        return False
    return ident_used(
        name,
        text,
        pattern=re.compile(r"(?<![A-Za-z0-9_'])" + re.escape(name) + r"(?![A-Za-z0-9_'])"),
    )


def pca_prefix(tactics: str) -> str:
    from jevops.mask import split_before
    from jevops.search import filter_used_later

    pre, rest = split_before(tactics, lambda line: line.strip().startswith("case "))
    kept = filter_used_later(
        pre,
        maybe_drop=lambda stripped: stripped.startswith("have "),
        name_fn=have_binder_name,
        used_fn=identifier_used,
        extra_later=rest,
        always_drop=lambda stripped: stripped.startswith("rename_i ") or stripped.startswith("obtain "),
    )
    return "\n".join(kept).rstrip()


def reference_vocab(tactics: str, *, stop: str = "STOP") -> list[str]:
    from jevops.mask import unique_vocab

    return unique_vocab(tactics, extras=("simp_all", "omega", "constructor", stop))


def is_pca_line(tactics: str, pos: int) -> bool:
    from jevops.mask import line_at, starts_any

    stripped = line_at(tactics, pos).lstrip()
    if starts_any(stripped, PCA_KEEP_PREFIXES):
        return True
    return stripped in {"·", "."}


def hammer_repair(
    draft: str,
    reference: str,
    errors: Sequence[Mapping[str, Any]],
    *,
    extra_fn: Optional[Callable[[str, str, str], str]] = None,
) -> str:
    """Local tactician: restore PCA glue, drop illegal tactics, then simp_all/omega."""

    from jevops.mask import any_line, lines_containing, pop_trailing, prepend_absent, rewrite_matching_lines, subn_changed
    from jevops.outer import append_line, first_matching_line, first_or_head, first_token, first_where
    from jevops.repair import join_errors

    blob = join_errors(errors)
    out = draft
    for ident in re.findall(r"Unknown identifier `([^`]+)`", blob):
        restore_lines = lines_containing(reference, ident, token=True) or lines_containing(reference, ident)
        pick = first_or_head(
            restore_lines,
            lambda line: "have " in line or ":=" in line,
        )
        out = prepend_absent(out, pick)
    for tac in re.findall(r"unknown tactic[:\s]*[`']?([A-Za-z_?][A-Za-z0-9_?]*)", blob, re.I):
        if tac.lower() in {"case", "induction", "simp", "simp_all", "intro", "intros", "exact", "apply"}:
            continue
        out = subn_changed(out, rf"\b{re.escape(tac)}\b", "simp_all")
    for tag in re.findall(r"Case tag `([^`]+)` not found", blob):
        out = subn_changed(out, rf"(?m)^[ \t]*case {re.escape(tag)}\b.*$", "")
    ind = first_matching_line(reference, lambda line: line.strip().startswith("induction "))
    if ind and not any_line(out, lambda line: line.strip().startswith("induction ")):
        out = prepend_absent(out, ind)
    out = rewrite_matching_lines(
        out,
        lambda stripped: bool(stripped)
        and (
            first_token(stripped, strip=";") in UNKNOWN_TACTICS
            or stripped.rstrip(";") in UNKNOWN_TACTICS
        ),
        lambda indent, *_a: f"{indent}simp_all",
    )
    if re.search(r"unknown tactic[:\s]*[`']?grind", blob, re.I):
        out = subn_changed(out, r"\bgrind\b", "simp_all")
    out = subn_changed(out, r"\bexact\?", "simp_all")
    out = subn_changed(out, r"\bapply\?", "simp_all")
    if "unknown tactic" in blob.lower():
        out = rewrite_matching_lines(
            out,
            lambda stripped: bool(stripped) and first_token(stripped, strip=";") in UNKNOWN_TACTICS,
            lambda *_a: None,
        )
    if "simp_all made no progress" in blob:
        out = subn_changed(out, r"(?m)^[ \t]*simp_all(?:\s*;\s*)?$", "", count=1)
    if "Type mismatch" in blob:
        for ident in re.findall(r"`([^`]+)`", blob):
            restore_lines = lines_containing(reference, ident)
            pick = first_where(
                restore_lines,
                lambda line: "have " in line or "rw " in line,
            ) or ""
            out = prepend_absent(out, pick)
        if "InitStatesNotDefined" in blob and "unzip_zip" in reference and "unzip_zip" not in out:
            out = out.replace("exact InitStatesNotDefined Hinit", "rw [List.unzip_zip] <;> simp_all")
        if re.search(r"exact ih\.2\.2", out) and "apply (ih Hinit" in reference:
            out = subn_changed(out, r"exact ih\.2\.2", "apply (ih Hinit ?_ ?_).2.2")
    if "No goals to be solved" in blob:
        out = subn_changed(out, r"(?m)^[ \t]*all_goals try simp_all\s*$", "")
        out = subn_changed(out, r"(?m)^[ \t]*try omega\s*$", "")
        out = pop_trailing(
            out,
            lambda line: line.strip() in {"simp_all", "try omega", "all_goals try simp_all"},
        )
    elif "unsolved goals" in blob.lower() or "unknown tactic" in blob.lower() or "Unknown identifier" in blob:
        if "all_goals try simp_all" not in out:
            out = append_line(append_line(out, "  all_goals try simp_all"), "  try omega")
    if extra_fn is not None:
        out = extra_fn(out, blob, reference)
    return out


IDENT = re.compile(
    r"(?:[^\W\d])(?:[\w'])*(?:\.(?:[^\W\d])(?:[\w'])*)*",
    re.UNICODE,
)
SIMP_RW_OPEN = re.compile(
    r"\b(?P<tactic>simp(?:_all|_rw)?(?:\s+only)?|rw!?|erw)\s*\[",
    re.UNICODE,
)
EXACT_APPLY_OPEN = re.compile(
    r"\b(?P<tactic>exact'?|apply'?)\b\s*",
    re.UNICODE,
)
LEMMA_STOPWORDS = frozenset(
    {
        "forall",
        "exists",
        "fun",
        "let",
        "in",
        "if",
        "then",
        "else",
        "do",
        "match",
        "with",
        "end",
        "where",
        "open",
        "import",
        "using",
        "from",
        "as",
        "return",
        "case",
        "of",
        "by",
        "have",
        "show",
        "this",
        "sorry",
        "admit",
        "at",
        "only",
        "all",
        "try",
        "first",
        "focus",
        "repeat",
        "skip",
        "next",
        "intro",
        "intros",
        "cases",
        "constructor",
        "refine",
        "apply",
        "exact",
        "simp",
        "rw",
        "erw",
        "simp_all",
        "simp_rw",
        "true",
        "false",
        "and",
        "or",
        "not",
        "some",
        "none",
        "generalizing",
        "hiding",
        "renaming",
        "calc",
        "suffices",
        "obtain",
        "rcases",
        "rintro",
        "all_goals",
        "any_goals",
    }
)
BARE_SIMP_ALL = re.compile(r"^[ \t]*(?:[·.]\s+)?simp_all\s*$")
IH_APPLY = "apply (ih Hinit ?_ ?_).2.2"
LOCKED_HEADS = ("intros ", "exists ", "induction ", "case ")


@dataclass(frozen=True)
class SrcLemma:
    name: str
    tactic: str
    opener: str
    offset: int


def extract_src_lemmas(
    src: str,
    *,
    cap: int = 16,
    error_cls: type[BaseException] = ValueError,
) -> tuple[tuple[SrcLemma, ...], int]:
    """Regex-extract lemma idents from ``simp [`` / ``rw [`` / ``exact`` / ``apply``."""

    if not isinstance(src, str):
        raise error_cls("src must be a string")
    from jevops.mask import bracket_inner, merge_matches
    from jevops.outer import token_family
    from jevops.pick import keep_token, unique_first

    events = merge_matches(src, ("list", SIMP_RW_OPEN), ("ident", EXACT_APPLY_OPEN))
    lemmas: list[SrcLemma] = []
    for offset, kind, match in events:
        tactic = token_family(
            match.group("tactic"),
            prefixes=("simp", "exact", "apply"),
            aliases={"rw": "rw", "erw": "rw"},
        )
        opener = match.group(0).strip()
        if kind == "list":
            inner = bracket_inner(src, match.end())
            for ident_match in IDENT.finditer(inner):
                lemmas.append(
                    SrcLemma(
                        name=ident_match.group(0),
                        tactic=tactic,
                        opener=opener,
                        offset=offset + ident_match.start(),
                    )
                )
            continue
        ident_match = IDENT.match(src, match.end())
        if ident_match is None:
            continue
        lemmas.append(
            SrcLemma(
                name=ident_match.group(0),
                tactic=tactic,
                opener=opener,
                offset=ident_match.start(),
            )
        )
    if cap < 0:
        raise error_cls("src lemma cap must be non-negative")
    kept, uncapped = unique_first(
        lemmas,
        key_fn=lambda item: item.name,
        keep_fn=lambda name: keep_token(name, stopwords=LEMMA_STOPWORDS, min_len=2),
        cap=cap,
    )
    return tuple(kept), uncapped


def drop_subset(tactics: str, holes: Sequence[Hole], chosen: Sequence[str]) -> str:
    from jevops.mask import fill_subset

    return fill_subset(
        tactics,
        [hole_row(item) for item in holes],
        chosen,
        fill_fn=lambda item: template_fill(
            Hole(
                hole_id=str(item["hole_id"]),
                family=str(item.get("family") or ""),
                start=int(item["start"]),
                end=int(item["end"]),
                original=str(item["original"]),
                indent=str(item.get("indent") or ""),
            )
        ),
        marker_fn=mca_marker,
    )


def join_consecutive_applies(tactics: str) -> str:
    from jevops.mask import join_consecutive_lines

    return join_consecutive_lines(
        tactics,
        lambda line: line.strip().startswith("apply "),
        joiner=lambda indent, a, b: f"{indent}{a.strip()} <;> {b.strip()}",
        same_indent=True,
    )


def join_consecutive_exacts(tactics: str) -> str:
    from jevops.mask import join_consecutive_lines

    return join_consecutive_lines(
        tactics,
        lambda line: line.strip().startswith("exact "),
        joiner=lambda indent, a, b: f"{indent}{a.strip()} <;> {b.strip()}",
    )


def drop_last_bare_simp_all(tactics: str) -> Optional[str]:
    from jevops.mask import drop_matching_line

    return drop_matching_line(tactics, lambda line: bool(BARE_SIMP_ALL.match(line)), last=True)


def prefix_have_lines(reference: str) -> list[str]:
    from jevops.mask import lines_until

    return lines_until(
        reference,
        lambda line: line.strip().startswith("have "),
        lambda line: line.strip().startswith("case "),
    )


def collapse_defined_simp(tactics: str) -> str:
    from jevops.mask import subn_changed

    return subn_changed(
        tactics,
        r"(?m)^(?P<indent>[ \t]*)simp \[isDefined\] at \* <;> simp_all\s*$",
        r"\g<indent>simp_all",
    )


def collapse_ih_simps(tactics: str, *, needle: str = IH_APPLY) -> Optional[str]:
    from jevops.mask import fold_following

    return fold_following(
        tactics,
        lambda line: needle in line,
        lambda stripped: stripped.startswith(". simp"),
        n_follow=2,
        replacement=lambda indent, _line, _following: indent + needle + " <;> simp_all",
    )


def closer_variants(tactics: str) -> list[tuple[str, str]]:
    from jevops.outer import append_line

    return [
        ("identity", tactics),
        ("simp_all", append_line(tactics, "  all_goals try simp_all")),
        ("omega", append_line(tactics, "  try omega")),
    ]


def hammer_variants(
    tactics: str,
    reference: str,
    extras: Sequence[tuple[str, str]] = (),
) -> list[tuple[str, str]]:
    """Parallel tactician branches. Aesop is not a Strata/CSLib dep."""

    rows = list(closer_variants(tactics))
    rows.append(
        (
            "restore+simp",
            hammer_repair(tactics, reference, [{"data": "unsolved goals"}]),
        )
    )
    rows.extend((str(name), str(body)) for name, body in extras)
    return rows


def random_mca_drafts(
    tactics: str,
    rng: Any,
    *,
    n: int = 6,
    token_fn: Callable[[str], int],
    allow_families: Optional[set[str]] = None,
    name: str = "",
    memory: Optional[Mapping[str, Any]] = None,
    safe_drop_fn: Optional[Callable[..., bool]] = None,
    blacklist_fn: Optional[Callable[..., bool]] = None,
    early_extras: Sequence[tuple[str, str, Mapping[str, Any]]] = (),
    late_extras: Sequence[tuple[str, str, Mapping[str, Any]]] = (),
) -> list[dict[str, Any]]:
    """Seeded MCA drops and injected extras. Binder drops are gated. No LLM."""

    from jevops.binders import drop_unused_binders
    from jevops.mask import drop_span
    from jevops.pick import pin_prefix, shorter_bag

    body = str(tactics or "").strip("\n")
    push, rows = shorter_bag(body, token_fn=token_fn)
    allow = set(allow_families) if allow_families else None

    def wanted(fam: str) -> bool:
        return allow is None or fam in allow

    def blocked(kind: str, nxt: str = "") -> bool:
        if memory is None or blacklist_fn is None:
            return False
        return bool(blacklist_fn(memory, name, kind, nxt))

    if wanted("dead_code"):
        push("drop_unused_binders", drop_unused_binders(body), {"family": "dead_code", "n_masks": 1})
    if wanted("strength_reduction"):
        push("collapse_simp_at", drop_redundant_simp_at(body), {"family": "strength_reduction"})
    if wanted("algebraic_simplification"):
        push("collapse_rw", collapse_rw_to_simp(body), {"family": "algebraic_simplification"})
    for kind, nxt, extra in early_extras:
        fam = str((extra or {}).get("family") or "")
        if fam and not wanted(fam):
            continue
        if blocked(kind, nxt):
            continue
        push(kind, nxt, extra)
    holes = list(find_holes(body))
    rng.shuffle(holes)
    for hole in holes:
        if not wanted(hole.family):
            continue
        kind = f"drop_{hole.family}_{hole.hole_id}"
        nxt = drop_span(body, hole.start, hole.end)
        if blocked(kind, nxt):
            continue
        if hole.original.strip().startswith(("rename_i ", "have ")) and safe_drop_fn is not None:
            if not safe_drop_fn(body, hole.start, hole.end, hole.original):
                continue
        push(kind, nxt, {"family": hole.family, "n_masks": 1})
        if len(rows) >= int(n):
            break
    for kind, nxt, extra in late_extras:
        fam = str((extra or {}).get("family") or "")
        if fam and not wanted(fam):
            continue
        if blocked(kind, nxt):
            continue
        push(kind, nxt, extra)
    return pin_prefix(rows, n=n, shuffle_fn=rng.shuffle)


@dataclass
class Chain:
    tactics: str
    tokens: int
    theorem_ok: bool
    trace: list[dict[str, Any]] = field(default_factory=list)


def mca_hole_prompt(
    record: Mapping[str, Any],
    skeleton: str,
    holes: Sequence[Hole],
    *,
    n: int = 6,
) -> str:
    from jevops.outer import head_seq

    hole_docs = [
        f"{hole.hole_id} family={hole.family}\nORIGINAL:\n{hole.original}\n"
        for hole in head_seq(list(holes), n)
    ]
    return (
        "Lean Refactor Arena hole-fill. The skeleton is the PCA principal structure "
        "(induction and case arms). Fill each <<<MCA_i family=...>>> hole only.\n"
        "Keep every case header. Same indentation as ORIGINAL. No sorry, no theorem, no open.\n"
        "Prefer simp_all for strength_reduction holes, drop dead rename_i/have, simp for rw chains.\n\n"
        f"Problem: {record.get('name')}\n"
        f"Statement:\n{record.get('statement')}\n\n"
        f"SKELETON:\n{skeleton}\n\n"
        f"HOLES:\n{''.join(hole_docs)}\n"
        "Reply as:\n<<<MCA_0 family=...>>>\n<tactics>\n<<<MCA_1 family=...>>>\n<tactics>\n"
    )


def few_shot_prompt(
    target: Mapping[str, Any],
    shots: Sequence[Mapping[str, Any]],
    *,
    tactics: str,
    skeleton: str,
    token_count: int,
) -> str:
    from jevops.outer import head_chars

    blocks = []
    for index, shot in enumerate(shots, 1):
        blocks.append(
            f"EXAMPLE {index}: {shot['name']}\n"
            f"Score: {shot['filled_tokens']}/{shot['ref_tokens']} tokens (ratio {shot['ratio']}), "
            f"holes={shot['n_holes']} families={shot['families']}. Lake-valid after deleting MCA residuals.\n"
            f"PCA skeleton (induction/case kept):\n{head_chars(shot['skeleton'], 900)}\n\n"
            f"BEFORE ({shot['ref_tokens']} tokens):\n{head_chars(shot['reference'], 700)}\n\n"
            f"AFTER ({shot['filled_tokens']} tokens, smallest lake-valid):\n{head_chars(shot['filled'], 700)}\n"
        )
    return (
        "You are refactoring a Lean 4 proof for Lean Refactor Arena. "
        "PCA principal structure = induction and every case arm (keep and connect these). "
        "MCA residuals = simp-at runs, rename_i, have after induction, rw chains (delete or replace with shorter tactics).\n"
        "Goal: the SMALLEST lake-valid tactic block. No sorry, no theorem/lemma/import/open. "
        "Do not drop case headers. Match indentation.\n\n"
        + "\n".join(blocks)
        + f"\nTARGET: {target.get('name')}\n"
        f"Statement:\n{head_chars(target.get('statement') or '', 700)}\n\n"
        f"PCA skeleton with MCA holes marked:\n{head_chars(skeleton, 1800)}\n\n"
        f"CURRENT tactics ({int(token_count)} tokens):\n{head_chars(tactics, 1600)}\n\n"
        "Reply with ONLY the refactored tactic block after := by.\n"
    )


def hammer_until(
    current: str,
    reference: str,
    errors: Sequence[Mapping[str, Any]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    row_fn: Callable[..., Mapping[str, Any]],
    *,
    kind: str,
    generator: str,
    passes: int = 3,
) -> tuple[list[dict[str, Any]], str, list[Any], bool]:
    """Repair/compile loop. compile_fn is injected. Lake is the oracle."""

    rows: list[dict[str, Any]] = []
    tactics_now = current
    current_errors = list(errors)
    ok = False
    for pass_i in range(1, max(1, int(passes)) + 1):
        repaired = hammer_repair(tactics_now, reference, current_errors)
        if repaired == tactics_now:
            break
        compiled = dict(compile_fn(repaired) or {})
        rows.append(dict(row_fn(kind=f"{kind}_hammer{pass_i}", generator=generator, tactics=repaired, compiled=compiled)))
        current_errors = list(compiled.get("errors") or [])
        tactics_now = repaired
        if compiled.get("theorem_ok"):
            ok = True
            break
    return rows, tactics_now, current_errors, ok


def mca_one_hole_prompt(record: Mapping[str, Any], tactics: str, hole: Hole) -> str:
    from jevops.outer import head_chars

    skeleton = mask_mca(tactics, [hole])
    return (
        "Lean Refactor Arena: replace ONE residual span. Keep the PCA skeleton "
        "(induction, every case header, exact/constructor). Fill the hole with "
        "1-4 Lean tactic lines that are STRICTLY SHORTER than ORIGINAL, same indent.\n"
        "Do not emit sorry, theorem, lemma, import, or open. Do not drop case arms.\n"
        "Prefer: simp [lemmas], simp_all, omega, ring, linarith, exact <hyp>.\n\n"
        f"Problem: {record.get('name')}\n"
        f"Statement:\n{head_chars(record.get('statement') or '', 600)}\n\n"
        f"ORIGINAL hole {hole.hole_id} family={hole.family} ({len(hole.original.split())} words):\n"
        f"{hole.original}\n\n"
        f"SKELETON (hole marked <<<{hole.hole_id} family={hole.family}>>>):\n"
        f"{head_chars(skeleton, 2800)}\n\n"
        f"Reply with only the replacement tactics, or:\n<<<{hole.hole_id} family={hole.family}>>>\n<tactics>\n"
    )


def collect_mcmc_proposal_extras(
    tactics: str,
    extra: Sequence[Mapping[str, Any]] = (),
    *,
    propose_fn: Optional[Callable[[str], Sequence[Mapping[str, Any]]]] = None,
    replay_fn: Optional[Callable[[str], str]] = None,
    extras_fn: Optional[Callable[[str], Sequence[Mapping[str, Any]]]] = None,
    replay_note: str = "apply the full kernel sequence",
) -> list[dict[str, Any]]:
    """Assemble MCMC extras. Inits propose/replay stay injected. No LLM."""

    extras: list[dict[str, Any]] = []
    if extra:
        extras.extend(dict(item) for item in extra)
    if propose_fn is not None:
        for item in propose_fn(tactics) or ():
            extras.append(
                {
                    "kind": item["kind"],
                    "tactics": item["tactics"],
                    "note": item.get("note") or "",
                    "lock": False,
                }
            )
    if replay_fn is not None:
        extras.append(
            {
                "kind": "inits_replay",
                "tactics": replay_fn(tactics),
                "note": replay_note,
                "lock": False,
            }
        )
    if extras_fn is not None:
        extras.extend(dict(item) for item in extras_fn(tactics) or ())
    return extras


def propose_closed_edits(
    tactics: str,
    reference: str,
    rng: Any,
    extras: Sequence[Mapping[str, Any]] = (),
    *,
    closers: Sequence[str] = ("simp_all", "omega", "constructor", "rfl"),
    skip_prefix: Sequence[str] = LOCKED_HEADS,
    limit: Optional[int] = 8,
) -> list[dict[str, str]]:
    """Closed local edits. Inits-specific replacements stay extras. Jev does not write Lean."""

    from jevops.mask import drop_index, drop_indices, replace_index
    from jevops.outer import head_chars
    from jevops.search import proposal_bag

    locked = {
        have_binder_name(line.strip())
        for line in prefix_have_lines(reference)
        if have_binder_name(line.strip())
    }
    idxs = mutable_line_indices(tactics, locked, skip_prefix=skip_prefix)

    def _keep_locked(text: str) -> bool:
        present = {have_binder_name(line.strip()) for line in text.splitlines()}
        for have in prefix_have_lines(reference):
            name = have_binder_name(have.strip())
            if name and name not in present:
                return False
        return True

    _push, proposals = proposal_bag(seed=tactics, accept_fn=_keep_locked)

    def push(kind: str, body: str, note: str, *, lock: bool = True) -> None:
        _push(kind, body, note, accept=lock)

    for item in extras:
        push(
            str(item.get("kind") or "extra"),
            str(item.get("tactics") or ""),
            str(item.get("note") or "extra"),
            lock=bool(item.get("lock", True)),
        )
    joined_app = join_consecutive_applies(tactics)
    push("join_applies", joined_app, "join consecutive apply")
    for _index, stripped, body in drop_last_duplicate_lines(tactics, locked):
        push("drop_duplicate", body, f"drop duplicate {head_chars(stripped, 60)}")
    dropped = drop_last_bare_simp_all(tactics)
    if dropped:
        push("drop_last_simp_all", dropped, "drop last bare simp_all")
    if idxs:
        pick = rng.sample(list(idxs), k=min(1, len(idxs)))
        for index in pick:
            line = tactics.splitlines()[index].strip()
            push("drop_line", drop_index(tactics, index), f"drop {head_chars(line, 60)}")
            closer = rng.choice(list(closers))
            push(
                "swap_closer",
                replace_index(tactics, index, closer),
                f"swap {head_chars(line, 40)} -> {closer}",
            )
    push("join_exacts", join_consecutive_exacts(tactics), "join consecutive exacts")
    if len(idxs) >= 2:
        first, second = rng.sample(list(idxs), 2)
        body = drop_indices(tactics, (first, second))
        a = head_chars(tactics.splitlines()[first].strip(), 30)
        b = head_chars(tactics.splitlines()[second].strip(), 30)
        push("drop_two", body, f"drop {a} AND {b}")
    if limit is not None:
        return proposals[: max(0, int(limit))]
    return proposals


STOP_TOKEN = "STOP"


def last_open_case(prefix: str) -> Optional[str]:
    from jevops.search import last_header_tag

    return last_header_tag(prefix, "case ", split_on="=>")


def pca_case_tags(tactics: str) -> list[str]:
    from jevops.mask import top_level_labels

    return top_level_labels(case_spans(tactics), tag_fn=lambda span: case_tag(span.label))


def case_header_map(reference: str) -> dict[str, str]:
    from jevops.mask import header_map

    return header_map(reference, case_spans(reference), tag_fn=lambda span: case_tag(span.label))


def case_arm_lines(reference: str, tag: str) -> list[str]:
    from jevops.mask import span_body_lines

    return span_body_lines(reference, case_spans(reference), tag, tag_fn=lambda span: case_tag(span.label))


def case_body_lines(prefix: str, tag: str) -> list[str]:
    from jevops.mask import capture_after_header
    from jevops.search import last_header_tag

    want = case_tag(str(tag or ""))
    return capture_after_header(
        prefix,
        want,
        is_header=lambda stripped: stripped.startswith("case "),
        id_of=lambda stripped: last_header_tag(stripped, "case ", split_on="=>") or "",
    )


def empty_case_arms(prefix: str, reference: str) -> list[str]:
    from jevops.search import empty_headers

    return empty_headers(
        prefix,
        pca_case_tags(reference),
        present_fn=lambda pref, tag: f"case {tag}" in pref,
        body_fn=lambda pref, tag: case_body_lines(pref, tag),
    )


def looks_like_closer(stripped: str, *, closers: Sequence[str] = CLOSERS) -> bool:
    from jevops.mask import starts_any

    return starts_any(
        stripped,
        ("simp", "exact ", "omega", "constructor", "rfl", "try simp", "try omega"),
        exact=tuple(closers),
    )


def looks_like_tactic(stripped: str, *, stop: str = STOP_TOKEN, closers: Sequence[str] = CLOSERS) -> bool:
    from jevops.mask import starts_any

    key = stripped.strip()
    if key == stop:
        return True
    return starts_any(key, TACTIC_HEAD, exact=tuple(closers))


def is_mca_line(stripped: str) -> bool:
    from jevops.mask import lstrip_core, starts_any

    return starts_any(lstrip_core(stripped), ("have ", "rename_i ", "obtain "))


def insert_haves_before_induction(draft: str, haves: Sequence[str]) -> str:
    from jevops.mask import insert_before

    return insert_before(
        draft,
        haves,
        lambda line: line.strip().startswith("induction "),
        if_missing="prepend",
    )


def arm_keep_lines(reference: str, tag: str) -> list[str]:
    from jevops.search import after_item, filter_used_later

    lines = case_arm_lines(reference, tag)
    later_arms: list[str] = []
    for other in after_item(pca_case_tags(reference), tag):
        later_arms.extend(case_arm_lines(reference, other))
    return filter_used_later(
        lines,
        maybe_drop=lambda stripped: is_mca_line(stripped),
        name_fn=have_binder_name,
        used_fn=identifier_used,
        extra_later=later_arms,
    )


def remaining_arm_lines(prefix: str, reference: str, tag: str) -> list[str]:
    from jevops.search import missing_occurrences

    return missing_occurrences(prefix.splitlines(), arm_keep_lines(reference, tag))


def stop_allowed(prefix: str, reference: str) -> bool:
    from jevops.search import structure_complete

    return structure_complete(
        prefix,
        pca_case_tags(reference),
        present_fn=lambda pref, tag: f"case {tag}" in pref,
        empty_fn=lambda pref, _tags: empty_case_arms(pref, reference),
        remaining_fn=lambda pref, tag: remaining_arm_lines(pref, reference, tag),
    )


def unused_vocab(prefix: str, vocab: Sequence[str], *, stop: str = STOP_TOKEN) -> list[str]:
    from jevops.search import unused_items

    return unused_items(prefix, vocab, stop=stop)


HAMMER_BODIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("native_hammer", "rfl", ("template", "rfl")),
    ("native_hammer", "simp_all", ("template", "simp_all")),
    ("aesop", "aesop", ("template", "aesop")),
    ("omega_decide", "omega", ("template", "omega")),
)


def _changed(fn: Callable[[str], str]) -> Callable[[str, Any], Optional[str]]:
    def inner(body: str, _span: Any) -> Optional[str]:
        nxt = fn(body)
        return nxt if nxt != body else None

    return inner


def span_preserving_edits(tactics: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """One-case edits that keep every ``case`` arm. Not whole-proof templates."""

    from jevops.mask import map_span_bodies

    rows: list[tuple[str, str, tuple[str, ...]]] = []
    seen: set[str] = set()

    def push(family: str, body: str, ops: tuple[str, ...]) -> None:
        text = str(body or "").strip("\n")
        if not text or text in seen:
            return
        seen.add(text)
        rows.append((family, text, ops))

    spans = case_spans(tactics)
    if not spans:
        push("simp_set", drop_redundant_simp_at(tactics), ("drop_redundant_simp_at", "whole"))
        return rows
    for span, merged in map_span_bodies(tactics, spans, _changed(drop_redundant_simp_at)):
        push("simp_set", merged, ("drop_redundant_simp_at", "case", span.label))
    for span, merged in map_span_bodies(tactics, spans, _changed(drop_have_obtain)):
        push("have_chain", merged, ("drop_have_obtain", "case", span.label))
    push("simp_set", drop_redundant_simp_at(tactics), ("drop_redundant_simp_at", "all_cases"))
    return rows


def closed_tree_edits(tactics: str, *, case_replace_cap: int = 8) -> list[tuple[str, str, tuple[str, ...]]]:
    """Deterministic closed-vocab drafts from a tactic tree. Not a Lean parser."""

    rows: list[tuple[str, str, tuple[str, ...]]] = []
    seen: set[str] = set()

    def push(family: str, body: str, ops: tuple[str, ...]) -> None:
        text = str(body or "").strip("\n")
        if not text or text in seen:
            return
        seen.add(text)
        rows.append((family, text, ops))

    reference = str(tactics or "").strip("\n")
    push("reference", reference, ("identity",))
    for family, body, ops in HAMMER_BODIES:
        push(family, body, ops)
    push("simp_set", collapse_simp_at(reference), ("collapse_simp_at",))
    push("have_chain", drop_have_obtain(reference), ("drop_have_obtain",))
    if CALC.search(reference):
        push("calc", keep_calc_only(reference), ("keep_calc",))
    push("custom", first_case_only(reference), ("first_case_only",))
    for span in case_spans(reference)[: max(0, int(case_replace_cap))]:
        push("simp_set", replace_case_body(reference, span, "simp_all"), ("replace_case", span.label, "simp_all"))
        push("aesop", replace_case_body(reference, span, "aesop"), ("replace_case", span.label, "aesop"))
    return rows


def collect_tree_drafts(
    *,
    closed_edits: Sequence[tuple[Any, ...]] = (),
    neighbor_ops: Sequence[tuple[Any, ...]] = (),
    push_fn: Callable[..., Any],
    cap: int = 48,
) -> list[Any]:
    """Push closed-tree then neighbor-style drafts. Does not write Lean."""

    drafts: list[Any] = []
    seen: set[str] = set()
    for family, body, ops in list(closed_edits or ()) + list(neighbor_ops or ()):
        push_fn(drafts, seen, family, body, ops)
    return drafts[: max(0, int(cap))]


def mutable_line_indices(tactics: str, locked_haves: set[str], *, skip_prefix: Sequence[str] = LOCKED_HEADS) -> list[int]:
    from jevops.mask import mutable_indices as _fn

    return _fn(
        tactics,
        skip_prefix=tuple(skip_prefix),
        skip_fn=lambda stripped, _i: stripped.startswith("have ") and have_binder_name(stripped) in locked_haves,
    )


def drop_last_duplicate_lines(tactics: str, locked_haves: set[str]) -> list[tuple[int, str, str]]:
    from jevops.mask import last_duplicate_drops

    return last_duplicate_drops(tactics, mutable=mutable_line_indices(tactics, locked_haves))


def guided_mca_edits(
    tactics: str,
    families: Sequence[str],
    counts: Optional[Mapping[str, Any]] = None,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Family-gated MCA drafts. Portable/Inits/symbol extras stay in the consumer."""

    from jevops.binders import drop_unused_binders
    from jevops.mask import rewrite_matching_lines
    from jevops.outer import first_group

    names = {str(item) for item in families}
    counts = dict(counts or {})
    if counts.get("n_rw") or counts.get("n_calc") or counts.get("n_omega") or counts.get("n_ring") or counts.get("n_induction"):
        names.add("algebraic_simplification")
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    seen: set[str] = set()

    def push(family: str, body: str, ops: tuple[str, ...]) -> None:
        text = str(body or "").strip("\n")
        if not text or text in seen:
            return
        seen.add(text)
        rows.append((family, text, ops))

    push("reference", tactics, ("identity", "pca_keep"))
    if "strength_reduction" in names or "dead_code" in names:
        push("strength_reduction", drop_redundant_simp_at(tactics), ("drop_redundant_simp_at", "mca"))
        for family, body, ops in span_preserving_edits(tactics):
            push(family, body, ops + ("mca_span",))
    if "dead_code" in names:
        push("dead_code", drop_unused_binders(tactics), ("drop_unused_binders", "mca"))
        push("dead_code", drop_rename_i(tactics), ("drop_rename_i", "mca"))
        push("dead_code", drop_have_obtain(tactics), ("drop_have_obtain", "mca"))
    if "loop_invariant" in names:
        push("loop_invariant", drop_have_after_induction(tactics), ("drop_have_after_induction", "mca"))
    if "search_space" in names:
        stripped_intros = rewrite_matching_lines(
            tactics,
            lambda stripped: stripped.startswith("intros ") and "Hin" in stripped,
            lambda *_a: None,
        )
        push("search_space", stripped_intros, ("drop_intros_hin", "mca"))
    if "algebraic_simplification" in names:
        push("algebraic_simplification", collapse_rw_to_simp(tactics), ("collapse_rw_to_simp", "mca"))
        push("algebraic_simplification", keep_calc_only(tactics), ("keep_calc", "mca"))
        name = first_group(tactics, re.compile(r"induction (\S+)"))
        if name:
            push("algebraic_simplification", f"induction {name} <;> simp", ("induction_simp", "mca"))
    return rows


def collect_guided_drafts(
    tactics: str,
    families: Sequence[Mapping[str, Any]],
    counts: Optional[Mapping[str, Any]] = None,
    *,
    extras: Sequence[Sequence[tuple[str, str, tuple[str, ...]]]] = (),
    push_fn: Callable[..., Any],
) -> list[Any]:
    """Merge MCA + injected extras, then push drafts. Extras stay in the consumer."""

    names = [str(item.get("family") or "") for item in families or ()]
    merged = merge_draft_ops(guided_mca_edits(tactics, names, counts), *list(extras or ()))
    drafts: list[Any] = []
    seen: set[str] = set()
    for family, body, ops in merged:
        push_fn(drafts, seen, family, body, ops)
    return drafts


@dataclass
class Draft:
    draft_id: str
    family: str
    tactics: str
    ops: tuple[str, ...] = ()
    n_chars: int = 0
    head: str = ""
    head_chars: int = 220

    def __post_init__(self) -> None:
        from jevops.outer import head_chars as _fn

        tactics = str(self.tactics).strip("\n")
        self.tactics = tactics
        self.n_chars = len(tactics)
        self.head = _fn(tactics, int(self.head_chars))


@dataclass
class BeamItem:
    prefix: str
    steps: list[str] = field(default_factory=list)
    stopped: bool = False
    score: float = 1.0


@dataclass(frozen=True)
class FeatureRow:
    name: str
    source: str
    vector: tuple[float, ...]
    counts: dict[str, float]


def push_draft(
    drafts: list[Draft],
    seen: set[str],
    family: str,
    tactics: str,
    ops: Sequence[str] = (),
    *,
    cap: int = 48,
    head_chars: int = 220,
) -> bool:
    from jevops.pick import padded_id, unique_push

    return unique_push(
        drafts,
        seen,
        tactics,
        lambda index, body: Draft(
            draft_id=padded_id(index),
            family=family,
            tactics=body,
            ops=tuple(ops),
            head_chars=head_chars,
        ),
        cap=cap,
    )


def feature_row(
    record: Mapping[str, Any],
    *,
    tactics: str,
    feature_names: Sequence[str] = FEATURE_NAMES,
    token_fn: Optional[Callable[[str], int]] = None,
) -> FeatureRow:
    counts = count_tactics(tactics, token_fn=token_fn)
    names = tuple(feature_names) or FEATURE_NAMES
    return FeatureRow(
        name=str(record.get("name") or ""),
        source=str(record.get("source") or ""),
        vector=tuple(float(counts[name]) for name in names),
        counts=counts,
    )


def structure_pack(
    reference: str,
    prefix: str,
    *,
    token_fn: Optional[Callable[[str], int]] = None,
    hole_head: int = 120,
    skeleton_n: int = 900,
) -> dict[str, Any]:
    """PCA skeleton + MCA holes of the original, plus what the prefix still lacks."""

    from jevops.outer import head_chars, head_lines
    from jevops.search import structure_status

    holes = find_holes(reference)
    skeleton = mask_mca(reference, holes)
    tags = pca_case_tags(reference)
    status = structure_status(
        prefix,
        tags,
        present_fn=lambda pref, tag: f"case {tag}" in pref,
        remaining_fn=lambda pref, tag: remaining_arm_lines(pref, reference, tag),
        empty_fn=lambda pref, _tags: empty_case_arms(pref, reference),
        open_fn=last_open_case,
    )
    counts = count_tactics(reference, token_fn=token_fn)
    mca = [
        {
            "id": hole.hole_id,
            "family": hole.family,
            "head": head_chars(head_lines(hole.original.strip(), 1), hole_head),
        }
        for hole in holes
    ]
    return {
        "pca_prefix": pca_prefix(reference),
        "pca_skeleton_head": head_chars(skeleton, skeleton_n),
        "pca_case_tags": tags,
        "missing_cases": status["missing"],
        "empty_arms": status["empty"],
        "unfinished_arms": status["unfinished"],
        "next_original": status["next_original"],
        "earliest_unfinished": status["earliest"],
        "open_case": status["open"],
        "mca_holes": mca,
        "n_have": int(counts.get("n_have") or 0),
        "n_induction": int(counts.get("n_induction") or 0),
        "n_cases": int(counts.get("n_cases") or 0),
        "n_tokens_ref": int(counts.get("n_tokens") or 0),
    }


def step_prompt(
    record: Mapping[str, Any],
    prefix: str,
    vocab: Sequence[str],
    pack: Optional[Mapping[str, Any]] = None,
    *,
    statement_n: int = 700,
    skeleton_n: int = 700,
    vocab_n: int = 24,
    hole_n: int = 12,
) -> str:
    from jevops.outer import bullet_lines, head_chars

    vocab_block = bullet_lines(vocab, limit=vocab_n)
    pack = dict(pack or {})
    missing = pack.get("missing_cases") or []
    holes = pack.get("mca_holes") or []
    hole_block = bullet_lines(
        holes,
        limit=hole_n,
        fmt=lambda item: f"{item.get('id')} family={item.get('family')}: {item.get('head')}",
        empty="(none)",
    )
    skeleton = head_chars(pack.get("pca_skeleton_head") or "", skeleton_n)
    return (
        "Lean 4 tactic completion. Emit ONLY the next tactic line after := by, "
        "or the word STOP if the proof is finished.\n"
        "No theorem/lemma/import/open/sorry/admit. Prefer a shorter lake-valid proof.\n"
        "PCA (principal): keep induction and every case header. Fill missing case headers "
        "before any MCA have/rename_i from the original.\n"
        "MCA (residual): simp-at / have / rw holes may be dropped or filled only inside the "
        "currently open case. Do not splice pre-induction haves after a case arm.\n\n"
        f"Problem: {record.get('name')}\n"
        f"Statement:\n{head_chars(record.get('statement') or '', statement_n)}\n\n"
        f"PCA skeleton of the original (holes marked):\n{skeleton}\n\n"
        f"MCA holes of the original:\n{hole_block}\n\n"
        f"Missing PCA case tags: {missing or 'none'}\n"
        f"Empty PCA case arms: {pack.get('empty_arms') or 'none'}\n"
        f"Fill this PCA case first: {pack.get('earliest_unfinished') or 'none'}\n"
        f"Open case: {pack.get('open_case') or 'none'}\n\n"
        f"Prefix so far:\n{prefix or '(empty)'}\n\n"
        f"Priority next lines:\n{vocab_block}\n\n"
        "Next tactic line:"
    )


def tactician_variants(
    grok: str,
    reference: str,
    *,
    replay_fn: Callable[[str], str],
    propose_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    propose_cap: int = 8,
) -> list[dict[str, Any]]:
    """Deterministic repairs of a grok-file draft. Jev does not write these."""

    from jevops.outer import head_seq
    from jevops.pick import unique_push

    rows: list[dict[str, Any]] = []
    seen: set[str] = {grok.strip("\n")}

    def push(kind: str, body: str, *ops: str) -> None:
        unique_push(
            rows,
            seen,
            body,
            lambda _index, text: {
                "kind": kind,
                "generator": "tactician",
                "tactics": text,
                "holes": [],
                "ops": list(ops),
                "source": "grok-file+tactician",
            },
            cap=256,
        )

    push("tactician_drop_simp_all", drop_bare_simp_all(grok), "drop_bare_simp_all")
    push("tactician_try_simp_all", try_simp_all(grok), "try_simp_all")
    push("tactician_inits_replay_ref", replay_fn(reference), "inits_replay_ref")
    push("tactician_inits_replay", replay_fn(grok), "inits_replay")
    for item in head_seq(list(propose_fn(grok) or []), propose_cap):
        push(f"tactician_{item['kind']}", item["tactics"], item["kind"])
    hammered = hammer_repair(
        grok,
        reference,
        [{"data": "simp_all made no progress"}, {"data": "Type mismatch `InitStatesNotDefined`"}],
    )
    push("tactician_hammer_seed", hammered, "hammer_seed")
    grok_tags = [case_tag(span.label) for span in case_spans(grok)]
    ref_tags = [case_tag(span.label) for span in case_spans(reference)]
    for tag in grok_tags:
        if tag in ref_tags:
            push(f"hybrid_ref_case_{tag}", replace_case_from(grok, reference, tag), "hybrid_ref_case", tag)
            push(f"hybrid_grok_case_{tag}", replace_case_from(reference, grok, tag), "hybrid_grok_case", tag)
    return rows


def assemble_mca_candidates(
    tactics: str,
    holes: Sequence[Hole],
    *,
    leanstral_text: Optional[str] = None,
    replay_fn: Optional[Callable[[str], str]] = None,
    parse_fills_fn: Optional[Callable[[str, Sequence[Hole]], Mapping[str, str]]] = None,
    indent_fn: Optional[Callable[[str, str], str]] = None,
    flatten_fn: Optional[Callable[[str, str], str]] = None,
) -> list[dict[str, Any]]:
    from dataclasses import asdict as _asdict

    template_fills = {hole.hole_id: template_fill(hole) for hole in holes}
    template_tactics = apply_fills(tactics, holes, template_fills)
    replayed = replay_fn(tactics) if replay_fn is not None else tactics
    rows: list[dict[str, Any]] = [
        {"kind": "reference", "generator": "pca_skeleton", "tactics": tactics, "holes": []},
        {
            "kind": "inits_replay",
            "generator": "inits_updates_shorten",
            "tactics": replayed,
            "holes": [],
        },
        {
            "kind": "mca_template_fill",
            "generator": "deterministic",
            "tactics": template_tactics,
            "holes": [_asdict(hole) | {"fill": template_fills[hole.hole_id]} for hole in holes],
        },
    ]
    strength_fills = {
        hole.hole_id: template_fill(hole) if hole.family == "strength_reduction" else hole.original
        for hole in holes
    }
    strength_tactics = apply_fills(tactics, holes, strength_fills)
    if strength_tactics != tactics and strength_tactics != template_tactics:
        rows.append(
            {
                "kind": "mca_template_strength_only",
                "generator": "deterministic",
                "tactics": strength_tactics,
                "holes": [
                    _asdict(hole) | {"fill": strength_fills[hole.hole_id]}
                    for hole in holes
                    if hole.family == "strength_reduction"
                ],
            }
        )
    if leanstral_text and parse_fills_fn is not None:
        fills = dict(parse_fills_fn(leanstral_text, holes) or {})
        if "__full__" in fills and len(fills) == 1:
            filled = fills["__full__"]
            if indent_fn is not None:
                filled = indent_fn(tactics, filled)
            if flatten_fn is not None:
                filled = flatten_fn(tactics, filled)
            rows.append(
                {
                    "kind": "mca_leanstral_full",
                    "generator": "labs-leanstral-1-5",
                    "tactics": filled,
                    "holes": [],
                }
            )
        else:
            merged = {hole.hole_id: fills.get(hole.hole_id, template_fills[hole.hole_id]) for hole in holes}
            filled = apply_fills(tactics, holes, merged)
            if indent_fn is not None:
                filled = indent_fn(tactics, filled)
            if flatten_fn is not None:
                filled = flatten_fn(tactics, filled)
            rows.append(
                {
                    "kind": "mca_leanstral_holes",
                    "generator": "labs-leanstral-1-5",
                    "tactics": filled,
                    "holes": [_asdict(hole) | {"fill": merged[hole.hole_id]} for hole in holes],
                }
            )
    return rows


def repair_prompt(
    record: Mapping[str, Any],
    *,
    failed: str,
    errors: Sequence[Mapping[str, Any]],
    reference: str,
    error_n: int = 4,
    block_n: int = 1200,
) -> str:
    from jevops.outer import head_chars, head_seq

    err_lines = [f"{item.get('pos')}: {item.get('data')}" for item in head_seq(errors, error_n)]
    return (
        "Lean Refactor Arena repair. The previous tactic block failed `lake env lean`.\n"
        "Return ONLY the corrected tactic block after `:= by`.\n"
        "Match reference indentation: top-level tactics and `case` lines use the same indent as the reference.\n"
        "Do not re-introduce explicit binders already in the theorem telescope.\n"
        "Do not repeat the statement. Do not emit sorry, admit, theorem, lemma, import, or open.\n\n"
        f"Problem: {record.get('name')}\n\n"
        f"Statement:\n{record.get('statement')}\n\n"
        f"Reference tactic block (lake exit 0):\n{head_chars(reference, block_n)}\n\n"
        f"Failed tactic block:\n{head_chars(failed, block_n)}\n\n"
        f"Lake errors:\n" + "\n".join(err_lines)
    )


def ident_holes(
    tactics: str,
    *,
    token_re: Any,
    occupied: Sequence[tuple[int, int]] = (),
    skip_tokens: Sequence[str] = (),
    pca_prefixes: Sequence[str] = PCA_KEEP_PREFIXES,
    max_holes: int = 24,
    id_prefix: str = "SYM_",
    kind: str = "ident",
) -> list[dict[str, Any]]:
    """Identifier holes that are not PCA structure. token_re is injected."""

    import re as _re

    taken = list(occupied)
    skip = set(skip_tokens)
    rows: list[dict[str, Any]] = []
    for match in token_re.finditer(tactics):
        if len(rows) >= max(0, int(max_holes)):
            break
        token = match.group(0)
        if not _re.match(r"[A-Za-z][A-Za-z0-9_']*$", token):
            continue
        if token in skip:
            continue
        start, end = match.span()
        line_start = tactics.rfind("\n", 0, start) + 1
        nl = tactics.find("\n", start)
        line = tactics[line_start : len(tactics) if nl < 0 else nl]
        stripped = line.lstrip()
        if any(stripped.startswith(prefix) for prefix in pca_prefixes):
            continue
        if not all(end <= a or start >= b for a, b in taken):
            continue
        rows.append(
            {
                "hole_id": f"{id_prefix}{len(rows)}",
                "kind": kind,
                "start": start,
                "end": end,
                "original": token,
                "n_tokens": 1,
            }
        )
        taken.append((start, end))
    return rows


def script_idents(tactics: str, *, token_re: Any) -> list[str]:
    import re as _re

    found: list[str] = []
    seen: set[str] = set()
    for match in token_re.finditer(tactics):
        token = match.group(0)
        if _re.match(r"[A-Za-z][A-Za-z0-9_']*$", token) and token not in seen:
            seen.add(token)
            found.append(token)
    return found


def closed_fills(
    hole: Mapping[str, Any],
    tactics: str,
    *,
    phrase_alts: Sequence[tuple[str, str]] = PHRASE_ALTS,
    operator_alts: Mapping[str, Sequence[str]] = OPERATOR_ALTS,
    token_re: Optional[Any] = None,
    cap: int = 8,
) -> list[str]:
    """Lean-language fills. No model. Prefer strictly shorter replacements."""

    original = str(hole.get("original") or "")
    kind = str(hole.get("kind") or "")
    fills: list[str] = [original]
    if kind == "phrase":
        for src, dst in phrase_alts:
            if src == original:
                fills.append(dst)
    elif kind == "operator":
        fills.extend(list(operator_alts.get(original, ())))
    elif kind == "span":
        for src, dst in phrase_alts:
            if src == dst:
                continue
            if src in original:
                if src == "apply UpdateStates.update_some" or (
                    src.endswith("update_some") and "apply " in original
                ):
                    fills.append(original.replace(src, "refine .update_some", 1))
                else:
                    fills.append(original.replace(src, dst, 1))
        for op, alts in dict(operator_alts).items():
            if op in original:
                for alt in alts:
                    fills.append(original.replace(op, alt, 1))
        if token_re is not None:
            tokens = list(token_re.finditer(original))
            if len(tokens) >= 2:
                fills.append(original[: tokens[-1].start()].rstrip())
    else:
        fills.extend(["this", "assumption", "trivial", "rfl", "constructor", "simp_all"])
        if token_re is not None:
            for ident in script_idents(tactics, token_re=token_re):
                if ident != original and len(ident) <= len(original):
                    fills.append(ident)
                    if len(fills) >= int(cap):
                        break
    out: list[str] = []
    seen: set[str] = set()
    for fill in fills:
        if fill not in seen:
            seen.add(fill)
            out.append(fill)
    from jevops.outer import head_seq

    return head_seq(out, cap)


def neighbor_style_ops(
    neighbors: Sequence[Mapping[str, Any]],
    records_by_name: Mapping[str, Any],
    *,
    head_fn: Callable[[Mapping[str, Any]], str],
) -> list[tuple[str, str, tuple[str, ...]]]:
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    for neighbor in neighbors:
        name = str(neighbor.get("name") or "")
        source = records_by_name.get(name)
        if not isinstance(source, Mapping):
            continue
        head = head_fn(source)
        if head:
            rows.append(("custom", head, ("neighbor_style", name)))
    return rows


def merge_draft_ops(*groups: Sequence[tuple[str, str, tuple[str, ...]]]) -> list[tuple[str, str, tuple[str, ...]]]:
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for group in groups:
        for family, body, ops in group:
            text = str(body or "").strip("\n")
            if not text or text in seen:
                continue
            seen.add(text)
            rows.append((family, text, tuple(ops)))
    return rows


# The existing Thompson ranker orders pipeline stems.  The tactic below is
# deliberately a little more concrete: it represents an action, records the
# outstanding pull, and requires an explicit reward before updating that
# action.  This keeps selection separate from proof admission and makes the
# state usable by the NCA cell layer.
BANDIT_POLICIES = frozenset({"thompson", "ucb1", "epsilon_greedy"})
_BANDIT_SEED_STEP = 104729


def _bandit_policy(policy: str, current: str = "") -> str:
    text = str(policy or current or "thompson").strip().lower().replace("-", "_")
    aliases = {
        "beta": "thompson",
        "ts": "thompson",
        "ucb": "ucb1",
        "epsilon": "epsilon_greedy",
        "egreedy": "epsilon_greedy",
    }
    text = aliases.get(text, text)
    return text if text in BANDIT_POLICIES else ""


def _bandit_active_arms(arms: Any) -> list[str]:
    if isinstance(arms, str):
        raw = [arms]
    elif isinstance(arms, Mapping):
        raw = list(arms.keys())
    else:
        raw = list(arms or ())
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        arm = str(item or "").strip()
        if not arm or arm in seen:
            continue
        seen.add(arm)
        out.append(arm)
    return sorted(out)


def _bandit_key(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(name or "default").strip())
    return text[:80] or "default"


def _bandit_arm_row() -> dict[str, Any]:
    return {
        "pulls": 0,
        "reward_sum": 0.0,
        "alpha": 1.0,
        "beta": 1.0,
        "pending": 0,
        "last_reward": None,
        "last_selected": 0,
        "last_observed": 0,
    }


def _bandit_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _bandit_reward(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    number = _bandit_number(value, default=float("nan"))
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number


def _bandit_state(memory: dict[str, Any], name: str, policy: str, seed: Any) -> dict[str, Any]:
    nca = memory.setdefault("nca", {})
    stores = nca.setdefault("bandits", {})
    key = _bandit_key(name)
    state = stores.setdefault(key, {})
    if not isinstance(state, dict):
        state = {}
        stores[key] = state
    state.setdefault("arms", {})
    state.setdefault("decisions", 0)
    state.setdefault("pending_arm", "")
    state.setdefault("seed", int(_bandit_number(seed, 0.0)))
    state["policy"] = _bandit_policy(policy, str(state.get("policy") or "")) or "thompson"
    return state


def _bandit_rng(state: Mapping[str, Any], rng: Optional[random.Random]) -> random.Random:
    if rng is not None:
        return rng
    seed = int(_bandit_number(state.get("seed"), 0.0))
    decisions = int(_bandit_number(state.get("decisions"), 0.0))
    # A fresh, decision-indexed generator is JSON-safe and deterministic across
    # process restarts, unlike serializing random.Random.getstate().
    return random.Random(seed + decisions * _BANDIT_SEED_STEP)


def _bandit_arm_ptr(arm: str) -> str:
    from jevops.nca import canonical_cell_id

    return canonical_cell_id(str(arm), kind="skill")


def _bandit_ptr(name: str) -> str:
    return f"ptr://cell/bandit/{_bandit_key(name)}"


def _record_bandit_cell(
    memory: dict[str, Any],
    *,
    name: str,
    arm: str,
    policy: str,
    score: float,
    reward: Optional[float] = None,
    event: str,
) -> None:
    """Reflect one bandit transition into the symbolic NCA graph."""

    try:
        from jevops import nca

        bandit_ptr = _bandit_ptr(name)
        arm_ptr = _bandit_arm_ptr(arm)
        nca.upsert_from_event(
            memory,
            ptr=bandit_ptr,
            kind="cell",
            energy=score,
        )
        theorem_ok = None if reward is None else bool(reward >= 0.5)
        nca.upsert_from_event(
            memory,
            ptr=arm_ptr,
            kind="skill",
            energy=score if reward is None else reward,
            theorem_ok=theorem_ok,
            parent_ptr=bandit_ptr,
        )
        nca.append_board_edges(memory, [[bandit_ptr, arm_ptr]], prefix="")
        nca.journal_event(
            memory,
            event=event,
            ptr=arm_ptr,
            op="BANDIT",
            energy_delta=0.0,
            extra={
                "bandit": _bandit_key(name),
                "arm": arm,
                "policy": policy,
                "reward": reward,
            },
        )
    except Exception:
        # Bandit selection remains usable with a minimal memory mapping; NCA
        # reflection is an enhancement, never an admission dependency.
        pass


def multi_armed_bandit(
    memory: dict[str, Any],
    arms: Sequence[str] | Mapping[str, Any] | str,
    *,
    name: str = "default",
    policy: str = "",
    reward: Any = None,
    arm: Optional[str] = None,
    selected: Optional[str] = None,
    rng: Optional[random.Random] = None,
    epsilon: float = 0.1,
    exploration: float = 1.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Run one explicit multi-armed-bandit tactic step.

    A call without ``reward`` selects one active arm and records one pending
    pull.  The next call should pass that arm's measured reward in ``[0, 1]``;
    a Boolean reward is accepted as ``0``/``1``.  Selection is not proof
    admission: only the caller's explicit observation changes the arm's
    posterior.  ``selected`` can force a known active arm for replay/tests;
    ``arm`` names the arm whose pending result is being observed.

    State is kept in ``memory["nca"]["bandits"][name]``.  Every transition
    is also mirrored into the NCA grid and journal so bandit policy is a
    symbolic, inspectable cell process rather than an opaque side table.
    """

    active = _bandit_active_arms(arms)
    if not active:
        return {
            "ok": False,
            "kind": "tactic_multi_armed_bandit",
            "reason": "no_arms",
            "writes_lean": False,
            "called_docker0": False,
        }
    chosen_policy = _bandit_policy(policy) if str(policy or "").strip() else ""
    if not chosen_policy:
        existing = ((memory.get("nca") or {}).get("bandits") or {}).get(_bandit_key(name)) or {}
        chosen_policy = _bandit_policy("", str(existing.get("policy") or "")) or "thompson"
    try:
        epsilon_value = float(epsilon)
    except (TypeError, ValueError):
        epsilon_value = -1.0
    if not math.isfinite(epsilon_value) or not (0.0 <= epsilon_value <= 1.0):
        return {"ok": False, "kind": "tactic_multi_armed_bandit", "reason": "bad_epsilon", "writes_lean": False}
    try:
        exploration_value = float(exploration)
    except (TypeError, ValueError):
        exploration_value = 0.0
    if exploration_value <= 0.0 or not math.isfinite(exploration_value):
        return {"ok": False, "kind": "tactic_multi_armed_bandit", "reason": "bad_exploration", "writes_lean": False}

    state = _bandit_state(memory, name, chosen_policy, seed)
    rows = state.setdefault("arms", {})
    for active_arm in active:
        row = rows.get(active_arm)
        if not isinstance(row, dict):
            row = _bandit_arm_row()
            rows[active_arm] = row
        defaults = _bandit_arm_row()
        for key, value in defaults.items():
            row.setdefault(key, value)

    observed_arm = ""
    observed_reward: Optional[float] = None
    if reward is not None:
        observed_arm = str(arm or state.get("pending_arm") or "").strip()
        observed_reward = _bandit_reward(reward)
        if observed_reward is None:
            return {
                "ok": False,
                "kind": "tactic_multi_armed_bandit",
                "reason": "reward_out_of_range",
                "expected": "reward in [0, 1]",
                "writes_lean": False,
                "called_docker0": False,
            }
        if not observed_arm:
            return {
                "ok": False,
                "kind": "tactic_multi_armed_bandit",
                "reason": "reward_without_arm",
                "writes_lean": False,
                "called_docker0": False,
            }
        if observed_arm not in rows:
            return {
                "ok": False,
                "kind": "tactic_multi_armed_bandit",
                "reason": "unknown_arm",
                "arm": observed_arm,
                "writes_lean": False,
                "called_docker0": False,
            }
        pending_before = str(state.get("pending_arm") or "")
        if arm is not None and pending_before and observed_arm != pending_before:
            return {
                "ok": False,
                "kind": "tactic_multi_armed_bandit",
                "reason": "pending_arm_mismatch",
                "pending_arm": pending_before,
                "arm": observed_arm,
                "writes_lean": False,
                "called_docker0": False,
            }
        row = rows[observed_arm]
        row["pulls"] = max(0, int(row.get("pulls") or 0)) + 1
        row["reward_sum"] = _bandit_number(row.get("reward_sum"), 0.0) + observed_reward
        row["alpha"] = max(1e-9, _bandit_number(row.get("alpha"), 1.0)) + observed_reward
        row["beta"] = max(1e-9, _bandit_number(row.get("beta"), 1.0)) + (1.0 - observed_reward)
        row["pending"] = max(0, int(row.get("pending") or 0) - 1)
        row["last_reward"] = observed_reward
        row["last_observed"] = int(state.get("decisions") or 0)
        if str(state.get("pending_arm") or "") == observed_arm:
            state["pending_arm"] = ""
        mean = row["reward_sum"] / max(1, int(row["pulls"]))
        _record_bandit_cell(
            memory,
            name=name,
            arm=observed_arm,
            policy=chosen_policy,
            score=mean,
            reward=observed_reward,
            event="bandit_observe",
        )

    pending = str(state.get("pending_arm") or "")
    if pending and not isinstance(rows.get(pending), dict):
        pending = ""
    if pending and reward is None:
        # Do not create a second unmeasured pull when a loop is polled before
        # its oracle/lake result arrives.
        selected_arm = pending
        selected_score = _bandit_number((rows.get(pending) or {}).get("last_score"), 0.5)
        reason = "pending_observation"
        new_selection = False
        scores = {a: _bandit_number((rows.get(a) or {}).get("last_score"), 0.5) for a in active}
        draws: dict[str, float] = {}
    else:
        if selected is not None and str(selected).strip() not in active:
            return {
                "ok": False,
                "kind": "tactic_multi_armed_bandit",
                "reason": "selected_arm_not_active",
                "arm": str(selected),
                "writes_lean": False,
                "called_docker0": False,
            }
        generator = _bandit_rng(state, rng)
        untried = [a for a in active if int((rows[a].get("pulls") or 0)) <= 0]
        scores: dict[str, float] = {}
        draws = {}
        if selected is not None:
            selected_arm = str(selected).strip()
            scores = {
                a: _bandit_number(rows[a].get("reward_sum"), 0.0) / max(1, int(rows[a].get("pulls") or 0))
                for a in active
            }
            reason = "forced"
        elif untried:
            selected_arm = untried[0]
            # Keep the persisted/returned state JSON-safe. All untried arms
            # are tied for coverage priority; ``1.0`` is only a ranking
            # sentinel, not an observed reward.
            scores = {a: (1.0 if a in untried else 0.0) for a in active}
            reason = "initial_exploration"
        elif chosen_policy == "thompson":
            for active_arm in active:
                row = rows[active_arm]
                alpha = max(1e-9, _bandit_number(row.get("alpha"), 1.0))
                beta = max(1e-9, _bandit_number(row.get("beta"), 1.0))
                try:
                    draw = float(generator.betavariate(alpha, beta))
                except (AttributeError, ValueError, ZeroDivisionError):
                    x = generator.gammavariate(alpha, 1.0)
                    y = generator.gammavariate(beta, 1.0)
                    draw = x / (x + y) if x + y else 0.5
                draws[active_arm] = draw
                scores[active_arm] = draw
            selected_arm = min(active, key=lambda a: (-scores[a], a))
            reason = "thompson_sample"
        elif chosen_policy == "ucb1":
            total = max(1, sum(int(rows[a].get("pulls") or 0) for a in active))
            for active_arm in active:
                row = rows[active_arm]
                pulls = max(1, int(row.get("pulls") or 0))
                mean = _bandit_number(row.get("reward_sum"), 0.0) / pulls
                scores[active_arm] = mean + exploration_value * math.sqrt(math.log(total + 1.0) / pulls)
            selected_arm = min(active, key=lambda a: (-scores[a], a))
            reason = "ucb1"
        else:
            means = {
                a: _bandit_number(rows[a].get("reward_sum"), 0.0) / max(1, int(rows[a].get("pulls") or 0))
                for a in active
            }
            scores = dict(means)
            if generator.random() < epsilon_value:
                selected_arm = active[generator.randrange(len(active))]
                reason = "epsilon_explore"
            else:
                selected_arm = min(active, key=lambda a: (-scores[a], a))
                reason = "epsilon_greedy"
        state["decisions"] = int(state.get("decisions") or 0) + 1
        state["pending_arm"] = selected_arm
        rows[selected_arm]["pending"] = int(rows[selected_arm].get("pending") or 0) + 1
        rows[selected_arm]["last_selected"] = int(state["decisions"])
        selected_score = _bandit_number(scores.get(selected_arm), 0.5)
        rows[selected_arm]["last_score"] = selected_score
        _record_bandit_cell(
            memory,
            name=name,
            arm=selected_arm,
            policy=chosen_policy,
            score=selected_score if math.isfinite(selected_score) else 0.5,
            event="bandit_select",
        )
        new_selection = True

    ranked = sorted(active, key=lambda a: (-_bandit_number(scores.get(a), 0.0), a))
    state["active_arms"] = list(active)
    state["last_selected"] = selected_arm
    state["last_reason"] = reason
    state["pipeline_bias"] = list(ranked)
    memory.setdefault("nca", {})["pipeline_bias"] = list(ranked)
    return {
        "ok": True,
        "kind": "tactic_multi_armed_bandit",
        "bandit": _bandit_key(name),
        "policy": chosen_policy,
        "selected_arm": selected_arm,
        "selected_score": selected_score,
        "observed_arm": observed_arm or None,
        "observed_reward": observed_reward,
        "new_selection": new_selection,
        "reason": reason,
        "pending_arm": state.get("pending_arm") or None,
        "decisions": int(state.get("decisions") or 0),
        "ranked": ranked,
        "scores": scores,
        "draws": draws,
        "arms": {a: dict(rows[a]) for a in active},
        "writes_lean": False,
        "called_docker0": False,
    }


def bandit_tactic(
    memory: dict[str, Any],
    arms: Sequence[str] | Mapping[str, Any] | str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Readable alias for :func:`multi_armed_bandit` in tactic catalogs."""

    return multi_armed_bandit(memory, arms, **kwargs)


def collect_random_draft_extras(
    body: str,
    rng: Any,
    *,
    wanted_fn: Callable[[str], bool],
    portable_items: Sequence[Mapping[str, Any]] = (),
    symbol_spans: Sequence[Any] = (),
    prefer_fn: Optional[Callable[..., Sequence[Any]]] = None,
    phrase_alts: Sequence[tuple[str, str]] = (),
    operators: Sequence[str] = (),
    closed_fn: Optional[Callable[..., Any]] = None,
    pca_drafts: Sequence[Any] = (),
) -> tuple[list[tuple[str, str, dict[str, Any]]], list[tuple[str, str, dict[str, Any]]]]:
    """Portable + symbol-diffuse + PCA extras for random drafts. No LLM."""

    early: list[tuple[str, str, dict[str, Any]]] = []
    for item in portable_items or ():
        fam = str(item.get("family") or "search_space")
        early.append(
            (str(item["kind"]), str(item["tactics"]), {"family": fam, "generator": "portable_rewrites"})
        )
    late: list[tuple[str, str, dict[str, Any]]] = []
    spans = list(symbol_spans or ())
    if hasattr(rng, "shuffle"):
        rng.shuffle(spans)
    for span in spans:
        if not wanted_fn("symbol_diffuse"):
            break
        if prefer_fn is None or closed_fn is None:
            continue
        windows = list(prefer_fn(body, span, max_pos=3) or ())
        if not windows:
            continue
        hole = rng.choice(windows)
        original = str(getattr(hole, "original", "") or "")
        if not any(src in original for src, _dst in phrase_alts) and not any(
            op in original for op in operators
        ):
            continue
        row = closed_fn(body, [hole], schedule_id=f"rand_s{span}")
        if row:
            late.append((str(row["kind"]), str(row["tactics"]), {"family": "symbol_diffuse", "span": span}))
    for draft in pca_drafts or ():
        family = str(getattr(draft, "family", None) or (draft.get("family") if isinstance(draft, Mapping) else "") or "")
        draft_id = getattr(draft, "draft_id", None) or (draft.get("draft_id") if isinstance(draft, Mapping) else "")
        tactics = str(
            getattr(draft, "tactics", None) or (draft.get("tactics") if isinstance(draft, Mapping) else "") or ""
        )
        late.append((f"pca_{family}_{draft_id}", tactics, {"family": family}))
    return early, late


def collect_symbol_ops(
    closed_rows: Sequence[Mapping[str, Any]],
    kernel_rows: Sequence[Mapping[str, Any]],
    *,
    family: str = "symbol_diffuse",
    kernel_cap: int = 8,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Phrase/kernel fill ops for PCA/MCA extras. No LLM."""

    from jevops.outer import head_seq

    rows: list[tuple[str, str, tuple[str, ...]]] = []
    for item in closed_rows or ():
        kind = str(item.get("kind") or "")
        if item.get("hole_kind") == "phrase" or kind == "inits_replay":
            rows.append((family, str(item["tactics"]), (family, kind, "closed_vocab")))
    for item in head_seq(kernel_rows, kernel_cap):
        rows.append(
            (
                family,
                str(item.get("tactics") or ""),
                (family, str(item.get("kind") or "kernel"), "one_hole"),
            )
        )
    return rows
