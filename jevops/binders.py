#!/usr/bin/env python3
"""Binder-use gates and lake-error repair for MCA drops.

Dropping ``rename_i`` / ``have`` is only safe when the bound names do not
appear later in the proof. Lake ``Unknown identifier`` restores the line
that bound that name. No LLM. Not an Arena ranking. Jev does not write Lean.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

# Unicode letters so CCS ``μ`` counts as a binder.
IDENT = re.compile(r"[^\W\d][\w']*", re.UNICODE)
_UNKNOWN = re.compile(r"Unknown identifier `([^`]+)`")
KEYWORDS = frozenset(
    {
        "have",
        "rename_i",
        "simp",
        "simp_all",
        "rw",
        "exact",
        "apply",
        "intro",
        "intros",
        "induction",
        "case",
        "constructor",
        "refine",
        "exists",
        "by",
        "at",
        "with",
        "only",
        "all_goals",
        "obtain",
        "let",
        "show",
        "fun",
        "if",
        "then",
        "else",
        "match",
        "do",
        "pure",
        "return",
    }
)
def memory_default() -> Path:
    from jevops import hooks

    hooked = hooks.const("memory_default")
    if hooked:
        return Path(hooked)
    return Path("refactor-memory.json")


def skill_analysis_default() -> Path:
    from jevops import hooks

    hooked = hooks.const("skill_analysis_default")
    if hooked:
        return Path(hooked)
    return memory_default().parent / "skill-analysis.json"


MEMORY_DEFAULT = Path("refactor-memory.json")
SKILL_ANALYSIS_DEFAULT = Path("skill-analysis.json")


def binders_from_line(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("rename_i "):
        return [tok for tok in IDENT.findall(stripped[len("rename_i ") :]) if tok not in KEYWORDS]
    if stripped.startswith(("have ", "obtain ", "let ")):
        # ``have ⟨a, b⟩ :=`` / ``obtain ⟨s2', ...⟩`` bind unicode names; never treat as unused.
        if "⟨" in stripped:
            return ["__keep__"]
        rest = stripped.split(" ", 1)[1].lstrip()
        if rest.startswith(":=") or rest.startswith(":"):
            return ["this"]
        left = rest.split(":=", 1)[0]
        # Only the binder name, not identifiers in the type ascription
        # (``have der' : Typing Γ t τ := der`` binds der', not Typing/Γ/t/τ).
        name_part = left.split(":", 1)[0]
        names = [tok for tok in IDENT.findall(name_part) if tok not in KEYWORDS]
        if not names:
            names = ["this"]
        if stripped.startswith("have "):
            names.append("this")
        from jevops.outer import unique_keep

        return unique_keep(names)
    return []


def idents_in(text: str) -> set[str]:
    from jevops.repair import idents_in as _fn

    return _fn(text, pattern=IDENT, stopwords=KEYWORDS)


def binders_used_later(tactics: str, start: int, end: int, original: str) -> list[str]:
    names = binders_from_line(original)
    if "__keep__" in names:
        return ["__keep__"]
    if not names:
        return []
    from jevops.repair import names_used_later

    return names_used_later(tactics, end, names, ident_fn=idents_in)


def _is_prefix_have(tactics: str, start: int) -> bool:
    before = tactics[:start]
    return not re.search(r"(?m)^[ \t]*(induction |cases |case )", before)


def _have_casts_inducted_hyp(tactics: str, end: int, original: str) -> bool:
    """``have der' : T := der`` then ``induction der`` is a motive cast, not dead code.

    Fsub.progress failed with ``Function expected at ih_l rfl`` after dropping it.
    """

    if ":=" not in original:
        return False
    rhs = original.split(":=", 1)[1].strip()
    match = IDENT.match(rhs)
    if not match:
        return False
    hyp = match.group(0)
    rest = tactics[end:]
    return bool(re.search(rf"(?m)^[ \t]*(induction|cases) {re.escape(hyp)}\b", rest))


def safe_to_drop_span(tactics: str, start: int, end: int, original: str) -> bool:
    """True when dropping this span cannot remove a still-referenced binder."""

    stripped = original.strip()
    if stripped.startswith(("rename_i ", "have ", "obtain ", "let ")):
        if binders_used_later(tactics, start, end, original):
            return False
        # Prefix ``have`` before induction/cases is often simp_all fuel even if
        # the name never appears (Hk / Hlen2 on InitsUpdatesComm).
        if stripped.startswith("have ") and _is_prefix_have(tactics, start) and "simp_all" in tactics[end:]:
            return False
        if stripped.startswith("have ") and _have_casts_inducted_hyp(tactics, end, original):
            return False
        return True
    if stripped.startswith("simp at"):
        return True
    return False


def drop_unused_binders(tactics: str, *, kinds: tuple[str, ...] = ("rename_i", "have")) -> str:
    """Delete rename_i/have lines whose binders are not used later."""

    from jevops.mask import filter_keepends

    def _drop(line: str, start: int, end: int) -> bool:
        stripped = line.strip()
        if "rename_i" in kinds and stripped.startswith("rename_i "):
            return safe_to_drop_span(tactics, start, end, line.rstrip("\n"))
        if "have" in kinds and stripped.startswith("have "):
            return safe_to_drop_span(tactics, start, end, line.rstrip("\n"))
        if "obtain" in kinds and stripped.startswith("obtain "):
            return safe_to_drop_span(tactics, start, end, line.rstrip("\n"))
        return False

    return filter_keepends(tactics, _drop)


def unknown_identifiers(errors: Sequence[Mapping[str, Any]]) -> list[str]:
    from jevops.repair import join_errors
    from jevops.repair import unique_findall

    return unique_findall(join_errors(errors), _UNKNOWN)


def insert_missing_line(draft: str, reference: str, missing_line: str) -> str:
    """Put ``missing_line`` back next to a neighbor that still exists in draft."""

    from jevops.repair import insert_missing_line as _fn

    return _fn(draft, reference, missing_line)


def restore_unknown_binders(draft: str, reference: str, errors: Sequence[Mapping[str, Any]]) -> str:
    """If lake says Unknown identifier X, restore the reference line that bound X."""

    from jevops.outer import first_matching_line
    from jevops.repair import restore_bound_lines

    def _bound(ref: str, ident: str) -> Optional[str]:
        return first_matching_line(
            ref,
            lambda line: ident in binders_from_line(line)
            or ident in IDENT.findall(line.split(":=", 1)[0]),
        )

    return restore_bound_lines(draft, reference, unknown_identifiers(errors), bound_fn=_bound)


def error_class(errors: Sequence[Mapping[str, Any]]) -> str:
    from jevops.repair import classify_text
    from jevops.repair import join_errors

    blob = join_errors(errors)
    return classify_text(
        blob,
        (
            ("unknown_identifier", ("unknown identifier",)),
            ("unsolved_goals", ("unsolved goals",)),
            ("type_mismatch", ("type mismatch", "application type mismatch")),
            ("unknown_tactic", ("unknown tactic",)),
            ("placeholder", ("don't know how to synthesize placeholder",)),
        ),
        all_of=(("unsolved_goals", ("tactic", "unsolved")),),
    )


# Draft IDs like pca_search_space_d012 change every round; ban the body, not the slot.
_EPHEMERAL = ("pca_", "sweep_rand_")
# Skills whose implementation was patched after they were banned.
_PATCHED_UNBAN = (
    "port_unused_intros",  # now skips arms whose next tactic is assumption
    "port_intro_x_hin",  # skill removed
    # binder_from_line no longer treats type ascriptions as binders (Fsub der').
    # hammer_repair used to rewrite grind → simp_all (illegal `simp_all only [→`).
    "port_apply_ih_assumption",  # skill removed
    "port_dot_ctor_apply",  # skill removed
    "port_ccs_choiceL_exact",
    "port_ccs_choiceL_hr1",
    "port_ccs_choiceR_exact",
    # ``use``/``exact`` newline folds now preserve the matched line indent;
    # old bans were generated from the over-indented implementation.
    "port_use_exact_reuse",
)


def is_ephemeral_kind(kind: str) -> bool:
    from jevops.memory import is_ephemeral_kind as _fn

    return _fn(kind, prefixes=_EPHEMERAL, markers=("_MCA_",))


def blacklist_key(name: str, kind: str, tactics: str = "") -> str:
    from jevops.memory import blacklist_key as _fn

    return _fn(name, kind, tactics)


def scrub_blacklist(memory: dict[str, Any]) -> dict[str, Any]:
    from jevops.memory import scrub_blacklist as _fn

    return _fn(memory, patched_unban=_PATCHED_UNBAN)


def rehydrate_from_skill_analysis(
    memory: dict[str, Any], *, path: Optional[Path] = None
) -> dict[str, Any]:
    from jevops.memory import rehydrate_from_gaps

    return rehydrate_from_gaps(memory, path=path or skill_analysis_default())


def load_memory(path: Optional[Path] = None) -> dict[str, Any]:
    from jevops.memory import load_memory as _load

    target = path or memory_default()
    rehy = skill_analysis_default() if path is None else None
    return _load(target, rehydrate_path=rehy, patched_unban=_PATCHED_UNBAN)


def save_memory(memory: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    from jevops.memory import save_memory as _save

    return _save(memory, path or memory_default(), patched_unban=_PATCHED_UNBAN)


def remember_research(
    memory: dict[str, Any],
    *,
    name: str,
    residuals: Mapping[str, Any],
    unsafe: Mapping[str, Any],
    help_scores: Mapping[str, Any],
    skill: str,
    compose: str,
) -> None:
    from jevops.memory import remember_research as _fn

    _fn(
        memory,
        name=name,
        residuals=residuals,
        unsafe=unsafe,
        help_scores=help_scores,
        skill=skill,
        compose=compose,
    )


def failed_skill_stems(memory: Mapping[str, Any], name: str) -> set[str]:
    from jevops.memory import failed_skill_stems as _fn

    # A fold implementation can be repaired without deleting its negative
    # history.  Re-open the patched stems for a new Lake probe; only a
    # verified repair receipt removes the active failure permanently.
    return _fn(memory, name, ignore_stems=_PATCHED_UNBAN)


def repair_blacklist(
    memory: dict[str, Any],
    *,
    name: str,
    stem: str,
    receipt: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Re-open a failed port stem only after a caller's compiler receipt."""

    from jevops.memory import repair_blacklist as _fn

    return _fn(memory, name=name, stem=stem, receipt=receipt)


# Drop residuals that AutoResearch marked do_not_cut mint these keep-structure skills.
KEEP_MINTS: dict[str, tuple[str, ...]] = {
    "intro_then_simp_all": ("hoist_repeated_simp", "redundant_inner_simp"),
    "ctor_lone": (),
    "grind": (),
    "use_then_exact": ("trailing_tuple_comma",),
    "have": (),
    "apply_semi_assumption": (),
    "apply_seq_assumption": (),
    "intros_x_Hin": (),
    "repeated_simp_list": ("hoist_repeated_simp",),
    "inner_simp_subset": ("redundant_inner_simp",),
    "trailing_tuple_comma": ("trailing_tuple_comma",),
}


def skill_gap_report(memory: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-problem next-skill notes from AutoResearch snapshots + bans."""

    from jevops import folds as lra_port
    from jevops.memory import gap_report

    return gap_report(
        memory,
        keep_mints=KEEP_MINTS,
        compose_plan_fn=lambda name: [stem for stem, _fn in lra_port.pipeline_order(dict(memory), name=name)],
        ignore_stems=_PATCHED_UNBAN,
    )


def propose_skill_from_research(memory: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Highest-help residual that is safe to cut; else a keep-structure mint."""

    from jevops.memory import propose_skill_from_research as _fn

    return _fn(memory, name, keep_mints=KEEP_MINTS)


def expand_skills_from_memory(
    memory: dict[str, Any], *, name: str, tactics: str = ""
) -> list[dict[str, Any]]:
    """Record keep-structure mints when AutoResearch says do not cut the residual."""

    from jevops import folds as lra_port
    from jevops.memory import expand_keep_notes

    return expand_keep_notes(
        memory,
        name=name,
        tactics=tactics,
        keep_mints=KEEP_MINTS,
        residual_fn=lra_port.analyze_residuals if tactics else None,
        keep_stems=lra_port.KEEP_STRUCTURE,
        residual_map=lra_port.SKILL_RESIDUAL,
    )


ALLOWED_KEEP = frozenset(
    {
        "intro",
        "intros",
        "constructor",
        "grind",
        "induction",
        "case",
        "exact",
        "use",
        "have",
        "simp_all",
    }
)
_STEM_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")


def install_memory_skill(memory: dict[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    """Store a closed keep-structure fold spec. Does not exec Python or write Lean."""

    from jevops.memory import install_memory_skill as _fn

    return _fn(memory, spec, allowed_keep=set(ALLOWED_KEEP))


def prior_research(memory: Mapping[str, Any], name: str) -> dict[str, Any]:
    from jevops.memory import prior_research as _fn

    return _fn(memory, name)


def remember_success(
    memory: dict[str, Any],
    *,
    name: str,
    kind: str,
    family: str,
    from_tokens: int,
    to_tokens: int,
) -> None:
    from jevops.memory import remember_success as _fn

    _fn(memory, name=name, kind=kind, family=family, from_tokens=from_tokens, to_tokens=to_tokens)


def remember_failure(
    memory: dict[str, Any],
    *,
    name: str,
    kind: str,
    errors: Sequence[Mapping[str, Any]],
    tactics: str = "",
) -> None:
    from jevops.memory import remember_failure as _fn

    _fn(
        memory,
        name=name,
        kind=kind,
        error_class=error_class(errors),
        unknown=unknown_identifiers(errors),
        tactics=tactics,
    )


def is_blacklisted(
    memory: Mapping[str, Any], name: str, kind: str, tactics: str = ""
) -> bool:
    from jevops.memory import is_blacklisted as _fn

    return _fn(memory, name, kind, tactics)


def blocked_port_stems(
    memory: Optional[Mapping[str, Any]],
    name: str,
    pipeline: Sequence[Any],
    *,
    blacklist_fn: Callable[..., bool],
    failed_fn: Callable[[Mapping[str, Any], str], Any],
) -> set[str]:
    """Union of blacklisted port_ stems and failed skill stems. Not a lake admit."""

    blocked: set[str] = set()
    if memory is None:
        return blocked
    for key, _fn in pipeline or ():
        if blacklist_fn(memory, name, f"port_{key}"):
            blocked.add(str(key))
    blocked |= set(failed_fn(memory, name) or ())
    return blocked
