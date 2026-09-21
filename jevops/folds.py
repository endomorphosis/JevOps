#!/usr/bin/env python3
"""Portable, lake-checked tactic skills.

Skills are pattern folds, not one-off strings. TypeSafe Choice picks a skill;
code applies it; lake is the oracle. Jev does not write Lean.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

_EXACT_HYP = re.compile(r"\bexact ([A-Za-z][A-Za-z0-9']{0,6})\b")
_USE_EXACT = re.compile(r"use ([^;\n]+); exact ⟨")
_USE_EXACT_NL = re.compile(
    r"(?m)^(?P<indent>[ \t]*)use (?P<term>[^;\n]+)\n"
    r"(?P=indent)exact ⟨"
)
_INTRO_SIMP = re.compile(
    r"(?m)^(?P<ind>[ \t]*)intro\n(?:[ \t]*\n)*(?P=ind)simp_all$"
)
_USE_EXACT_BLOCK = re.compile(
    r"(?m)^(?P<ind>[ \t]*)use (?P<term>[^;\n]+)\n"
    r"(?P=ind)exact ⟨(?P<body>[^⟩]*)⟩"
)
_CTOR_PAIR = re.compile(
    r"(?m)^(?P<indent>[ \t]*)constructor\n"
    r"(?P=indent)· exact (?P<a>.+)\n"
    r"(?P=indent)· exact (?P<b>.+)$"
)
_REPEAT_PAR = re.compile(
    r"(?m)^(?P<indent>[ \t]*)apply ParallelReduction\.par <;>\n"
    r"(?P=indent)  apply ParallelReduction\.par <;>\n"
    r"(?P=indent)  grind$"
)
_HYP_NAME = re.compile(r"^(H[A-Za-z0-9']*|h[a-z0-9']*|this)$")


def _token_count(text: str) -> int:
    from jevops import hooks
    from jevops.lean import token_count as kernel_count

    count_fn = hooks.get("token_count")
    if count_fn is not None:
        return int(count_fn(text))
    return kernel_count(text)


def fold_exact_hyp(tactics: str) -> str:
    """``exact Hin`` / ``exact H1`` → ``assumption`` when the name looks like a hyp."""

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if "." in name:
            return match.group(0)
        if name.startswith("H") or name.startswith("h") or name == "this":
            return "assumption"
        return match.group(0)

    from jevops.mask import subn_changed

    return subn_changed(tactics, _EXACT_HYP, repl)


def fold_use_exact(tactics: str) -> str:
    """``use t; exact ⟨p, q⟩`` → ``exact ⟨t, p, q⟩`` (Exists.intro packing)."""

    from jevops.mask import subn_changed

    nxt = subn_changed(tactics, _USE_EXACT, r"exact ⟨\1, ")
    # Include the indentation in the match.  The old expression matched from
    # ``use`` onward and then prepended the next line's indentation again,
    # producing invalid over-indented nested case arms.
    return subn_changed(nxt, _USE_EXACT_NL, r"\g<indent>exact ⟨\g<term>, ")


def fold_use_exact_reuse(tactics: str) -> str:
    """``use t`` / ``exact ⟨.refl t, p⟩`` → ``exact ⟨t, .refl _, p⟩`` when t repeats."""

    def repl(match: re.Match[str]) -> str:
        term = match.group("term").strip()
        body = match.group("body")
        ind = match.group("ind")
        if f"({term})" in body:
            body2 = body.replace(f"({term})", "_", 1)
        elif term in body:
            body2 = body.replace(term, "_", 1)
        else:
            return match.group(0)
        return f"{ind}exact ⟨{term}, {body2}⟩"

    from jevops.mask import subn_changed
    from jevops.pick import keep_shorter

    nxt = subn_changed(tactics, _USE_EXACT_BLOCK, repl)
    if nxt == tactics:
        return tactics
    return keep_shorter(tactics, nxt, token_fn=_token_count)


def fold_ctor_pair_exacts(tactics: str) -> str:
    """``constructor / · exact A / · exact B`` → ``exact ⟨A, B⟩``."""

    def repl(match: re.Match[str]) -> str:
        return f"{match.group('indent')}exact ⟨{match.group('a')}, {match.group('b')}⟩"

    from jevops.mask import subn_changed

    return subn_changed(tactics, _CTOR_PAIR, repl)


def fold_semi_assumption(tactics: str) -> str:
    """``<;> assumption`` → ``; assumption`` only when the next tactic is not intros/cases.

    substOldPostSubset needs ``<;>`` because ``apply cih`` leaves extra goals that
    ``intros x Hin`` consumes. extractedOldExprInVars does not.
    """

    from jevops.mask import map_lines, peek_next_stripped
    from jevops.outer import first_token

    def _fn(index: int, line: str, lines: list[str]) -> Optional[str]:
        if "<;> assumption" not in line:
            return None
        nxt = peek_next_stripped(lines, index)
        # substOldPostSubset: both ``intros x Hin`` and bare ``intro`` still need <;>
        # (extra goals from apply cih/eih). Only rewrite when the next tactic is a closer.
        if first_token(nxt) in {"simp_all", "rfl", "constructor", "exact"}:
            return line.replace("<;> assumption", "; assumption", 1)
        return None

    return map_lines(tactics, _fn)


def fold_repeat_par_grind(tactics: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group('indent')}repeat (first | apply ParallelReduction.par | grind)"

    from jevops.mask import subn_changed

    return subn_changed(tactics, _REPEAT_PAR, repl)


# Repeated dotted names on CallElim keep-bests (token analysis). Each is a
# separate skill so lake can ban one without killing the others.
SHORTEN_IDENTS: tuple[tuple[str, str, str], ...] = (
    ("llexpr_getvars", "Lambda.LExpr.LExpr.getVars", "LExpr.getVars"),
    ("list_subset_trans", "List.Subset.trans", "Subset.trans"),
    ("list_subset_app", "List.Subset.app", "Subset.app"),
    ("hasvars_getvars", "Imperative.HasVarsPure.getVars", "HasVarsPure.getVars"),
)

# Bump when a portable fold is repaired or its compiler-probe policy changes.
# Live memories use this marker to revalidate stale fuzzy-prior bans; fixture
# callers without the marker retain the historical filtering behavior.
PORTABLE_PROBE_REVISION = "folds-20260921-indent-probes-v2"


def fold_shorten_ident(tactics: str, old: str, new: str) -> str:
    if old not in tactics:
        return tactics
    from jevops.pick import keep_shorter

    return keep_shorter(tactics, tactics.replace(old, new), token_fn=_token_count)


_GRIND_ONLY = re.compile(r"grind only \[[^\]]+\]")


def fold_grind_only_to_grind(tactics: str) -> str:
    """``grind only [...]`` → ``grind`` (Fsub/SKI). AutoResearch gates this residual."""

    if "grind only [" not in tactics:
        return tactics
    from jevops.mask import subn_changed
    from jevops.pick import keep_shorter

    nxt = subn_changed(tactics, _GRIND_ONLY, "grind")
    if nxt == tactics:
        return tactics
    return keep_shorter(tactics, nxt, token_fn=_token_count)


def fold_drop_unfold_before_split(tactics: str) -> str:
    """``unfold name`` immediately before ``split`` is often redundant."""

    from jevops.mask import subn_changed

    return subn_changed(
        tactics,
        r"(?m)^(?P<ind>[ \t]*)unfold \S+\n(?P=ind)split$",
        r"\g<ind>split",
    )


def fold_drop_try_simp_all(tactics: str) -> str:
    """Drop ``try simp_all`` hanging off ``induction … simp at * ;``.

    extractedOldExprInVars still has that tail. Memory said keep ``intro``;
    this is a different residual (optional simp after a closing ``at *``).
    """

    from jevops.mask import subn_changed

    return subn_changed(
        tactics,
        r"(at \* )\s*;\n([ \t]*)try simp_all",
        r"\1",
        count=1,
    )


def fold_drop_intro_before_simp_all(tactics: str) -> str:
    """``intro`` / ``simp_all`` → ``simp_all`` when they are the whole remaining arm.

    AutoResearch ranked intro_then_simp_all as the highest-help residual on CallElim
    keep-bests (unsafe still under FIRE_T). Lake is the oracle.
    """

    from jevops.mask import subn_changed

    return subn_changed(tactics, _INTRO_SIMP, r"\g<ind>simp_all")


def fold_trim_intro_names(tactics: str) -> str:
    """Drop trailing unused names on ``intro a b c`` (keep constructor / intro).

    CCS: ``intro s1 s2 r μ`` uses only ``r``; μ can drop from the end.
    ``intro h`` unused → nameless ``intro``.
    """

    from jevops import binders as lra_bind
    from jevops.mask import map_lines
    from jevops.search import trim_trailing_unused

    def _fn(index: int, line: str, lines: list[str]) -> Optional[str]:
        stripped = line.strip()
        if not stripped.startswith("intro ") or stripped.startswith("intros"):
            return None
        names = lra_bind.IDENT.findall(stripped[len("intro ") :])
        if not names:
            return None
        later = lra_bind.idents_in("\n".join(lines[index + 1 :]))
        trimmed = trim_trailing_unused(names, later)
        if trimmed == names:
            return None
        indent = line[: len(line) - len(line.lstrip())]
        if not trimmed:
            return f"{indent}intro"
        return f"{indent}intro {' '.join(trimmed)}"

    return map_lines(tactics, _fn)


def fold_unused_intros(tactics: str) -> str:
    """``intros x Hin`` → nameless ``intros`` when Hin is unused in the arm.

    Skip when the next tactic is ``assumption``: that arm needs the named hyps
    (extractedOldExprInVars ``intros x Hin / assumption``). Both binders must
    be absent from the remainder; checking only ``Hin`` can erase ``x`` from
    a later ``exact`` or ``rw`` and create an invalid draft.
    """

    from jevops import binders as lra_bind
    from jevops.mask import map_lines, peek_next_stripped

    def _fn(index: int, line: str, lines: list[str]) -> Optional[str]:
        if line.strip() != "intros x Hin":
            return None
        if peek_next_stripped(lines, index) == "assumption":
            return None
        rest: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].lstrip().startswith("case "):
            rest.append(lines[cursor])
            cursor += 1
        later_ids = lra_bind.idents_in("\n".join(rest))
        if "x" not in later_ids and "Hin" not in later_ids:
            indent = line[: len(line) - len(line.lstrip())]
            return f"{indent}intros"
        return None

    return map_lines(tactics, _fn)


_TRAILING_TUPLE_COMMA = re.compile(r",\s*⟩")
_SIMP_OPEN = re.compile(
    r"(?m)(?:^(?P<ind>[ \t]*)(?:[·.][ \t]+)?|(?P<semi><;>[ \t]*))(?P<head>simp(?:_all)?)[ \t]*\["
)


def _split_lemmas(text: str) -> list[str]:
    from jevops.mask import split_top_level

    return split_top_level(text)


def _simp_spans(tactics: str) -> list[dict[str, Any]]:
    """Locations of ``simp[lemmas]`` / ``simp_all[lemmas]``, including ``<;> simp``."""

    from jevops.mask import bracket_inner, split_top_level

    rows: list[dict[str, Any]] = []
    for match in _SIMP_OPEN.finditer(tactics):
        br_open = match.end() - 1
        inner = bracket_inner(tactics, br_open + 1)
        close_at = br_open + 1 + len(inner)
        if close_at >= len(tactics) or tactics[close_at] != "]":
            continue
        rest = tactics[close_at + 1 :]
        at = re.match(r"[ \t]+at[ \t]+\*", rest)
        end = close_at + 1 + (at.end() if at else 0)
        indent = match.group("ind") or ""
        rows.append(
            {
                "start": match.start(),
                "end": end,
                "ind": indent,
                "head": match.group("head"),
                "lemmas": split_top_level(inner),
                "at_star": bool(at),
                "is_simp_all": match.group("head") == "simp_all",
                "semi": bool(match.group("semi")),
            }
        )
    return rows


def _parent_induction_simp(tactics: str, spans: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    match = re.search(r"(?m)^[ \t]*induction .*<;>", tactics)
    if not match:
        return None
    for span in spans:
        if span["is_simp_all"] or span["start"] < match.start():
            continue
        between = tactics[match.end() : span["start"]]
        if between.strip() == "":
            return span
        return None
    return None


def fold_trailing_tuple_comma(tactics: str) -> str:
    """Drop a trailing comma in ``⟨a, b,⟩`` (keep exact/use/constructor)."""

    from jevops.mask import subn_changed

    return subn_changed(tactics, _TRAILING_TUPLE_COMMA, "⟩")


def fold_redundant_inner_simp(tactics: str) -> str:
    """Drop a case-local ``simp [subset]`` when the induction parent already has those lemmas.

    Keeps intro/constructor. extractedOldExprInVars still has
    ``simp [Lambda.LExpr.LExpr.getVars]`` under a parent that lists getVars.
    """

    spans = _simp_spans(tactics)
    parent = _parent_induction_simp(tactics, spans)
    if not parent:
        return tactics
    parent_set = set(parent["lemmas"])
    if not parent_set:
        return tactics
    drop: list[tuple[int, int]] = []
    for span in spans:
        if span is parent or span["is_simp_all"] or span["semi"]:
            continue
        inner = set(span["lemmas"])
        if inner and inner <= parent_set:
            start = tactics.find("simp", span["start"], span["end"])
            if start < 0:
                start = span["start"]
            end = span["end"]
            if end < len(tactics) and tactics[end] == "\n":
                end += 1
            drop.append((start, end))
    if not drop:
        return tactics
    from jevops.mask import drop_spans, subn_changed

    nxt = drop_spans(tactics, drop)
    nxt = subn_changed(
        nxt,
        r"(?m)^(?P<ind>[ \t]*)(?P<dot>[·.])[ \t]*\n(?P=ind)[ \t]*",
        r"\g<ind>\g<dot> ",
    )
    nxt = subn_changed(
        nxt,
        r"(?m)^(?P<ind>[ \t]*)(?P<dot>[·.])[ \t]+",
        r"\g<ind>\g<dot> ",
    )
    return nxt if nxt.strip() else tactics


def fold_hoist_repeated_simp(tactics: str) -> str:
    """Merge a repeated case-local ``simp [lemmas] at *`` into the induction parent.

    Keeps intro/constructor/qualified names. substOldPostSubset repeats the same
    getVars list six times under ``induction post <;> simp [substOld]``.
    """

    spans = _simp_spans(tactics)
    parent = _parent_induction_simp(tactics, spans)
    if not parent:
        return tactics
    parent_set = set(parent["lemmas"])
    counts: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for span in spans:
        if span is parent or span["is_simp_all"] or span["semi"]:
            continue
        key = tuple(span["lemmas"])
        if not key:
            continue
        counts.setdefault(key, []).append(span)
    best_key = None
    best_rows: list[dict[str, Any]] = []
    for key, rows in counts.items():
        if len(rows) >= 2 and len(rows) > len(best_rows):
            best_key = key
            best_rows = rows
    if not best_key:
        return tactics
    extra = [item for item in best_key if item not in parent_set]
    need_at = any(row["at_star"] for row in best_rows)
    # substOldPostSubset: adding `at *` to `induction … <;> simp [substOld]` closed
    # the intro-only fvar/op arms (lake: Case tag `op` not found). Only hoist when
    # the parent already uses `at *`.
    if need_at and not parent["at_star"]:
        return tactics
    if not extra and (parent["at_star"] or not need_at):
        return tactics
    merged = parent["lemmas"] + extra
    at = " at *" if (parent["at_star"] or need_at) else ""
    new_simp = f"{parent['head']} [{', '.join(merged)}]{at}"
    replace_start = parent["start"]
    if parent["semi"]:
        simp_at = tactics.find("simp", parent["start"], parent["end"])
        if simp_at >= 0:
            replace_start = simp_at
    nxt = tactics[:replace_start] + new_simp + tactics[parent["end"] :]
    shift = len(new_simp) - (parent["end"] - replace_start)
    drop: list[tuple[int, int]] = []
    for span in best_rows:
        start = span["start"] + shift
        end = span["end"] + shift
        if end < len(nxt) and nxt[end] == "\n":
            end += 1
        drop.append((start, end))
    from jevops.mask import drop_spans

    nxt = drop_spans(nxt, drop)
    if _token_count(nxt) >= _token_count(tactics):
        return tactics
    return nxt


# Residual name used by AutoResearch Score/Noul for each pipeline stem.
SKILL_RESIDUAL: dict[str, str] = {
    "unused_intros": "intros_x_Hin",
    "trim_intro_names": "intro_then_simp_all",
    "drop_try_simp_all": "try_simp_all",
    "drop_intro_before_simp_all": "intro_then_simp_all",
    "grind_only_to_grind": "grind",
    "repeat_par_grind": "grind",
    "use_exact": "use_then_exact",
    "use_exact_reuse": "use_then_exact",
    "ctor_pair_exacts": "ctor_lone",
    "semi_assumption": "apply_semi_assumption",
    "hoist_repeated_simp": "repeated_simp_list",
    "redundant_inner_simp": "inner_simp_subset",
    "trailing_tuple_comma": "trailing_tuple_comma",
}

KEEP_STRUCTURE: tuple[str, ...] = (
    "trailing_tuple_comma",
    "redundant_inner_simp",
    "hoist_repeated_simp",
)


PIPELINE: tuple[tuple[str, Any], ...] = (
    ("trailing_tuple_comma", fold_trailing_tuple_comma),
    ("redundant_inner_simp", fold_redundant_inner_simp),
    ("hoist_repeated_simp", fold_hoist_repeated_simp),
    ("exact_hyp", fold_exact_hyp),
    ("unused_intros", fold_unused_intros),
    ("trim_intro_names", fold_trim_intro_names),
    ("drop_try_simp_all", fold_drop_try_simp_all),
    # Context-sensitive: ``split`` may need the definition that ``unfold``
    # exposed.  Keep it available through portable_drafts, where Lake can
    # reject the candidate, but never apply it in the default composition.
    ("grind_only_to_grind", fold_grind_only_to_grind),
    # drop_intro_before_simp_all is not default: AutoResearch help was high but lake
    # failed (simp_all no progress / unsolved subset). Only via portable_drafts if not skipped.
    ("use_exact", fold_use_exact),
    ("use_exact_reuse", fold_use_exact_reuse),
    ("ctor_pair_exacts", fold_ctor_pair_exacts),
    ("repeat_par_grind", fold_repeat_par_grind),
    ("semi_assumption", fold_semi_assumption),
)


def _research_help(memory: Optional[dict[str, Any]], stem: str, *, name: str = "") -> float:
    from jevops.memory import research_help

    return research_help(memory, stem, name=name, residual_map=SKILL_RESIDUAL)


def pipeline_order(
    memory: Optional[dict[str, Any]] = None, *, name: str = ""
) -> tuple[tuple[str, Any], ...]:
    """Reorder PIPELINE by memory: wins, then AutoResearch help, failures last."""

    from jevops.pick import order_pipeline

    bayes_mean: dict[str, float] = {}
    try:
        from jevops import rankers as lra_rank

        for stem, _fn in PIPELINE:
            bayes_mean[stem] = float(lra_rank.posterior(dict(memory or {}), stem).get("mean") or 0.5)
    except Exception:
        bayes_mean = {}
    return order_pipeline(
        PIPELINE,
        memory,
        name=name,
        residual_map=SKILL_RESIDUAL,
        keep_stems=KEEP_STRUCTURE,
        bayes_mean=bayes_mean,
    )


def fold_from_memory_skill(tactics: str, spec: Mapping[str, Any]) -> str:
    """Apply a memory-installed literal fold. Keeps listed tactic words."""

    from jevops.memory import apply_literal_fold

    return apply_literal_fold(tactics, spec, token_fn=_token_count)


def compose_pipeline(
    tactics: str,
    *,
    skip: Optional[set[str]] = None,
    memory: Optional[dict[str, Any]] = None,
    name: str = "",
) -> tuple[str, list[str]]:
    """Apply un-blacklisted skills in memory-weighted order."""

    from jevops.pick import compose_steps

    return compose_steps(tactics, pipeline_order(memory, name=name), skip=skip)


def portable_drafts(
    tactics: str,
    *,
    skip: Optional[set[str]] = None,
    memory: Optional[dict[str, Any]] = None,
    name: str = "",
) -> list[dict[str, object]]:
    """Shorter closed-vocab folds present in this script."""

    from jevops.pick import shorter_bag

    body = tactics.strip("\n")
    _push, rows = shorter_bag(body, token_fn=_token_count, generator="portable_rewrites")

    def push(kind: str, family: str, nxt: str) -> None:
        _push(f"port_{kind}", nxt, {"family": family, "n_masks": 1})

    push("trailing_tuple_comma", "search_space", fold_trailing_tuple_comma(body))
    push("redundant_inner_simp", "strength_reduction", fold_redundant_inner_simp(body))
    push("hoist_repeated_simp", "strength_reduction", fold_hoist_repeated_simp(body))
    push("exact_hyp", "search_space", fold_exact_hyp(body))
    push("use_exact", "search_space", fold_use_exact(body))
    push("use_exact_reuse", "search_space", fold_use_exact_reuse(body))
    push("ctor_pair_exacts", "algebraic_simplification", fold_ctor_pair_exacts(body))
    push("repeat_par_grind", "algebraic_simplification", fold_repeat_par_grind(body))
    push("semi_assumption", "search_space", fold_semi_assumption(body))
    push("unused_intros", "search_space", fold_unused_intros(body))
    push("trim_intro_names", "search_space", fold_trim_intro_names(body))
    push("drop_try_simp_all", "strength_reduction", fold_drop_try_simp_all(body))
    push("drop_unfold_before_split", "search_space", fold_drop_unfold_before_split(body))
    push("grind_only_to_grind", "algebraic_simplification", fold_grind_only_to_grind(body))
    for stem, old, new in SHORTEN_IDENTS:
        push(f"shorten_{stem}", "search_space", fold_shorten_ident(body, old, new))
    push("drop_intro_before_simp_all", "search_space", fold_drop_intro_before_simp_all(body))
    from jevops.mask import subn_changed

    collapsed = subn_changed(body, r"\n{3,}", "\n\n")
    push("collapse_blanks", "dead_code", collapsed)
    blocked = skip or set()
    for spec in (memory or {}).get("skills") or []:
        stem = str(spec.get("stem") or "mem")
        if stem in blocked or f"port_{stem}" in blocked or f"port_mem_{stem}" in blocked:
            continue
        push(
            f"mem_{stem}",
            str(spec.get("family") or "search_space"),
            fold_from_memory_skill(body, spec),
        )
    piped, applied = compose_pipeline(body, skip=skip, memory=memory, name=name)
    if applied:
        push("pipeline_" + "_".join(applied), "search_space", piped)
    return rows


SKILL_CRITERIA: dict[str, dict[str, str]] = {
    "keep": {
        "what": "Leave the current lake-valid script unchanged",
        "not_for": "When a closed fold below is present and unused-binder-safe",
    },
    "port_exact_hyp": {
        "what": "Replace exact H/Hin/H1 with assumption when the name is a local hyp",
        "not_for": "exact Lemma.foo or dotted constructors",
    },
    "port_use_exact": {
        "what": "Pack `use t; exact ⟨p, q⟩` into `exact ⟨t, p, q⟩`",
        "not_for": "use with a following tactic that is not exact ⟨",
    },
    "port_use_exact_reuse": {
        "what": "Pack `use t` / `exact ⟨.refl t, p⟩` into `exact ⟨t, .refl _, p⟩` when t repeats",
        "not_for": "When t is not in the exact tuple (would change the witness)",
    },
    "port_ctor_pair_exacts": {
        "what": "Pack constructor + two · exact into exact ⟨A, B⟩",
        "not_for": "constructor that builds a non-And/Exists type (CCS ChoiceBisim)",
    },
    "port_repeat_par_grind": {
        "what": "Collapse nested apply ParallelReduction.par <;> grind",
        "not_for": "Proofs without ParallelReduction",
    },
    "port_semi_assumption": {
        "what": "Replace <;> assumption with ; assumption when the next tactic is not intros/cases",
        "not_for": "apply cih <;> assumption followed by intros x Hin (multi-goal)",
    },
    "port_grind_only_to_grind": {
        "what": "Replace grind only [lemmas] with grind when extra lemmas are unnecessary",
        "not_for": "When grind without only fails or changes which lemmas fire (Fsub → wf)",
    },
    "port_shorten_llexpr_getvars": {
        "what": "Shorten Lambda.LExpr.LExpr.getVars to LExpr.getVars in simp lists",
        "not_for": "When LExpr.getVars is ambiguous",
    },
    "port_shorten_list_subset_trans": {
        "what": "Shorten List.Subset.trans to Subset.trans",
        "not_for": "When Subset.trans is ambiguous or not in scope",
    },
    "port_shorten_list_subset_app": {
        "what": "Shorten List.Subset.app to Subset.app",
        "not_for": "When Subset.app is ambiguous",
    },
    "port_shorten_hasvars_getvars": {
        "what": "Shorten Imperative.HasVarsPure.getVars to HasVarsPure.getVars",
        "not_for": "When HasVarsPure.getVars is ambiguous",
    },
    "port_drop_unfold_before_split": {
        "what": "Drop unfold name immediately before split",
        "not_for": "When split needs the unfolded definition in the goal",
    },
    "port_drop_try_simp_all": {
        "what": "Drop try simp_all after induction simp at * ;",
        "not_for": "When remaining cases still need the try (unsolved goals)",
    },
    "port_drop_intro_before_simp_all": {
        "what": "Drop a nameless intro immediately before simp_all when that is the rest of the case arm",
        "not_for": "When intro binds a hyp simp_all cannot recover (forall/subset goals)",
    },
    "port_trim_intro_names": {
        "what": "Drop trailing unused intro names; keep intro and constructor",
        "not_for": "Names used later (cases r, exists s1')",
    },
    "port_unused_intros": {
        "what": "Nameless intros when Hin is unused in the case arm",
        "not_for": "Arm whose next tactic is assumption (needs named hyps)",
    },
    "port_collapse_blanks": {
        "what": "Collapse extra blank lines (no token change unless tokens count them)",
        "not_for": "Already tight scripts",
    },
    "port_trailing_tuple_comma": {
        "what": "Drop a trailing comma in ⟨a, b,⟩; keep exact/use/constructor",
        "not_for": "A comma that separates a following field",
    },
    "port_redundant_inner_simp": {
        "what": "Drop a case-local simp [subset] when the induction parent already lists those lemmas; keep intro",
        "not_for": "When split/cases created a goal the parent simp did not close",
    },
    "port_hoist_repeated_simp": {
        "what": "Hoist a repeated case-local simp [lemmas] at * onto induction <;> simp; keep intro/constructor",
        "not_for": "When adding at * to the parent over-simps intro-only arms",
    },
    "port_pipeline": {
        "what": "Compose un-blacklisted skills in memory-weighted order (keep-structure first, then wins)",
        "not_for": "When a step is Noul-fired or binder-unsafe",
    },
    "port_random_forest": {
        "what": "Train a tiny forest on lake successes/failures and rank leftover drafts",
        "not_for": "Writing Lean; fewer than four labeled rows; Arena scores",
    },
    "port_bayes_time": {
        "what": "Beta-Bernoulli skill win-rate with exponential forget; write posterior onto cells",
        "not_for": "Writing Lean; treating posterior mean as a lake admit",
    },
    "port_mcmc": {
        "what": "Metropolis-Hastings over pipeline stem order; energy is 1 - Bayes mean",
        "not_for": "Writing Lean; docker0; replacing lake as the oracle",
    },
    "port_svd": {
        "what": "Truncated SVD on the theorem×skill lake matrix; recommend skills for a theorem",
        "not_for": "Proof-AST PCA (that is port_pca); writing Lean; n_theorems<2",
    },
    "port_pca": {
        "what": "CALL existing pca_mca_fanout SVD: keep principal style, surface MCA families",
        "not_for": "A second SVD ranker of leftover drafts; docker0; Arena scores",
    },
    "port_thompson": {
        "what": "Thompson-sample Beta(α,β) so high-variance stems still get a lake try",
        "not_for": "Treating a draw as a lake admit",
    },
    "port_ridge": {
        "what": "Integer milles ridge P(lake-ok | feature_row); companion to the forest",
        "not_for": "Writing Lean; fewer than four labeled rows",
    },
    "port_ols": {
        "what": "Integer ordinary least squares on milles features",
        "not_for": "Writing Lean; fewer than four labeled rows",
    },
    "port_logistic": {
        "what": "Integer logistic (OLS + milles sigmoid LUT)",
        "not_for": "Writing Lean; treating score as a lake admit",
    },
    "port_kmeans": {
        "what": "Integer k-means on milles feature rows; rank stems by cluster win-rate",
        "not_for": "Writing Lean; k greater than labeled rows",
    },
    "port_knn": {
        "what": "Integer k-NN milles distance to labeled lake rows",
        "not_for": "Writing Lean; empty memory",
    },
    "port_ica": {
        "what": "Integer FastICA-style deflation on the theorem×skill matrix",
        "not_for": "Writing Lean; n_theorems<2",
    },
    "port_nmf": {
        "what": "Integer NMF of nonnegative lake counts; rank skills by H mass",
        "not_for": "Writing Lean; negative-only matrices",
    },
    "port_kalman": {
        "what": "Integer 1-D Kalman on skill win milles (x,P,Q,R all ints)",
        "not_for": "Writing Lean; float covariance",
    },
    "port_autoencoder": {
        "what": "VAE text→Lean round-trip; Jev scores variations vs previous batch; keep shortest lake-ok",
        "not_for": "Treating Jev as a Lean admit; CE/cosine as gold; docker0",
    },
    "port_vae": {
        "what": "Same as port_autoencoder; milles mu/logvar samples scored by Jev then length",
        "not_for": "Writing Lean; CUDA training in the harness",
    },
    "port_sgd": {
        "what": "Closed wrap of sgd_fanout MCA hole minibatch; does not lake",
        "not_for": "Calling docker0; treating hole drop as admitted Lean",
    },
    "port_mask": {
        "what": "MCA mask skeleton (PCA case/induction stays)",
        "not_for": "Writing Lean into the proof",
    },
    "port_diffuse": {
        "what": "Closed-vocab symbol fills ranked by token cut",
        "not_for": "Open generation; docker0",
    },
    "port_markov": {
        "what": "Mille bigrams of tactic heads; P(next|last)",
        "not_for": "Bag-of-skill ranking (that is RF/kNN)",
    },
    "port_hmm": {
        "what": "Markov plus start-state milles",
        "not_for": "Writing Lean",
    },
    "port_isotonic": {
        "what": "PAVA milles P(ok|score); calibrate Noul/unsafe vs lake",
        "not_for": "Treating calibrated p as a lake admit",
    },
    "port_adaboost": {
        "what": "Mille AdaBoost stumps on RF residuals",
        "not_for": "n<4 labeled rows",
    },
    "port_quantile": {
        "what": "Remaining-cut milles q25/q50/q75 per stem",
        "not_for": "Mean-only remaining_cut (that is the IR ranker)",
    },
    "port_pagerank": {
        "what": "Mille PageRank on the board DAG",
        "not_for": "Theorem×skill SVD (that is port_svd)",
    },
    "port_contrastive": {
        "what": "Mille VAE pair loss (neg-pos+margin); diagnostic only",
        "not_for": "Replacing Jev as the VAE loss",
    },
    "port_graph_traverse": {
        "what": "BFS/DFS on board_edges (bounded hops)",
        "not_for": "Writing Lean; unbounded crawl",
    },
    "port_graphrag": {
        "what": "GraphRAG over symbol_search (DuckDB/KG/AST/rg) plus optional datasets GraphRAG",
        "not_for": "docker0; treating a hit as a lake admit",
    },
    "port_neural_graph": {
        "what": "Integer message-passing on DAG energy milles (2-hop GNN-style)",
        "not_for": "CUDA GNNs; writing Lean",
    },
    "port_skill_tree": {
        "what": "Hierarchical family→group→skill catalog scored by random forest",
        "not_for": "Writing Lean; skipping lake",
    },
    "port_hawkes": {
        "what": "Mille Hawkes intensity from event recency (not just Beta counts)",
        "not_for": "Instant-reward Thompson",
    },
    "port_crf": {
        "what": "Linear-chain Viterbi on tactic heads (unary + milles bigrams)",
        "not_for": "Bag-of-skills RF",
    },
    "port_submodular": {
        "what": "Greedy residual set-cover under a CALL budget",
        "not_for": "Single-skill ranking",
    },
    "port_delayed_bandit": {
        "what": "UCB milles with pending lake pulls",
        "not_for": "Thompson with instant reward",
    },
    "port_tape_conv": {
        "what": "Integer conv on the neural-tape window (W=7)",
        "not_for": "Writing Lean",
    },
    "port_tape_fft": {
        "what": "7-point milles DFT of the tape window",
        "not_for": "Float FFT libraries",
    },
    "port_tm_step": {
        "what": "One Turing step on the neural tape (δ, write, move)",
        "not_for": "Writing Lean; unbounded run",
    },
    "port_tm_run": {
        "what": "Bounded TM run (max 32 steps) then halt",
        "not_for": "Unbounded simulation",
    },
    "port_decision_transformer": {
        "what": "Pack TM history as (state, action, rtg_m) window for TypeSafe/Grok",
        "not_for": "Training a CUDA DT; writing Lean",
    },
    "port_tape_splice": {
        "what": "Insert a cell at the tape head (context splice)",
        "not_for": "Writing Lean",
    },
    "port_tape_mask": {
        "what": "Mask the tape window except the head (DT attention)",
        "not_for": "MCA port_mask",
    },
    "port_tape_pop": {
        "what": "Delete the cell under the tape head",
        "not_for": "TM aux-stack pop (that is port_tm_pop)",
    },
    "port_tape_crop": {
        "what": "Keep only the TypeSafe window around the head",
        "not_for": "Unbounded context",
    },
    "port_tape_keep": {
        "what": "Keep the k highest-energy tape cells",
        "not_for": "Writing Lean",
    },
    "port_nca_plan": {
        "what": "Seed/read goal→subgoal→task DAG in nca.plan (supervisor-style)",
        "not_for": "Campaign DuckDB writes; leases",
    },
    "port_got": {
        "what": "Graph of thoughts: Jev-scored nodes linked to tasks",
        "not_for": "Writing Lean; treating thoughts as lake admits",
    },
    "port_cache_put": {
        "what": "CID-put into L1 (and optional L2/L3); never a lake admit",
        "not_for": "Treating a cache hit as theorem_ok",
    },
    "port_cache_get": {
        "what": "CID-get L1 then L2 then optional DuckDB JSON-LD",
        "not_for": "Requiring DuckDB; admitting Lean",
    },
    "port_cache_lru": {
        "what": "Set L1 eviction to LRU (recency list)",
        "not_for": "Admitting Lean from a hot key",
    },
    "port_cache_arc": {
        "what": "Set L1 eviction to ARC (T1/T2 + B1/B2 ghosts, adaptive p)",
        "not_for": "Admitting Lean; requiring floats",
    },
    "port_negative_ttl": {
        "what": "Negative cache with tick TTL (unlike forever blacklist)",
        "not_for": "Skipping a later lake-ok body after expiry",
    },
    "port_singleflight": {
        "what": "One in-flight key per (problem, tactics head)",
        "not_for": "Leases or campaign CAS",
    },
    "port_context_budget": {
        "what": "Apply max_cells keep-k on the neural tape",
        "not_for": "Changing Lean",
    },
}


def analyze_residuals(tactics: str) -> dict[str, int]:
    """Counts of leftover patterns for TypeSafe / AutoResearch features."""

    spans = _simp_spans(tactics)
    parent = _parent_induction_simp(tactics, spans)
    parent_set = set(parent["lemmas"]) if parent else set()
    inner_subset = 0
    repeated = 0
    freq: dict[tuple[str, ...], int] = {}
    for span in spans:
        if parent is not None and span is parent:
            continue
        if span["is_simp_all"]:
            continue
        key = tuple(span["lemmas"])
        freq[key] = freq.get(key, 0) + 1
        if parent_set and set(span["lemmas"]) <= parent_set:
            inner_subset += 1
    repeated = sum(n for n in freq.values() if n >= 2)
    counts = {
        "intros_x_Hin": len(re.findall(r"intros x Hin", tactics)),
        "intro_then_simp_all": len(re.findall(r"intro\n[ \t]*simp_all", tactics)),
        "apply_semi_assumption": len(re.findall(r"<;> assumption", tactics)),
        "apply_seq_assumption": len(re.findall(r"; assumption", tactics)),
        "use_then_exact": len(re.findall(r"use .+\n[ \t]*exact ⟨", tactics)),
        "ctor_lone": len(re.findall(r"(?m)^[ \t]*constructor[ \t]*$", tactics)),
        "grind": tactics.count("grind"),
        "try_simp_all": len(re.findall(r"try simp_all", tactics)),
        "have": len(re.findall(r"(?m)^[ \t]*have ", tactics)),
        "repeated_simp_list": repeated,
        "inner_simp_subset": inner_subset,
        "trailing_tuple_comma": len(_TRAILING_TUPLE_COMMA.findall(tactics)),
    }
    return {key: val for key, val in counts.items() if val}


def available_skills(
    tactics: str, *, memory: Optional[dict[str, Any]] = None, name: str = ""
) -> dict[str, object]:
    """Named skills that actually change this script (skill-suggestion cookbook)."""

    from jevops.pick import skills_from_drafts

    return skills_from_drafts(
        portable_drafts(tactics, memory=memory, name=name),
        keep_spec=SKILL_CRITERIA["keep"],
        criteria=SKILL_CRITERIA,
    )


def decision_tree(
    tactics: str,
    *,
    memory: Optional[dict[str, Any]] = None,
    name: str = "",
    skip: Optional[set[str]] = None,
) -> dict[str, list[str]]:
    """Family → skill kinds TypeSafe can nest into (decision-tree cookbook)."""

    from jevops.pick import tree_from_drafts

    return tree_from_drafts(portable_drafts(tactics, skip=skip, memory=memory, name=name))
