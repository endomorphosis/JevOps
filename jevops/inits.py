#!/usr/bin/env python3
"""Closed, LLM-free shortenings for ``Core.InitsUpdatesComm``.

The 268→139 path is a finite list of string kernels. ``replay()`` applies
them in order. ``propose()`` / ``pca_mca_ops()`` expose the same kernels
to TypeSafe Choice, PCA/MCA fan-out, MCMC, hammer, and tactician.
Jev does not write Lean. Lake is the oracle. Never docker0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

TARGET_TOKENS = 139
BEST_TARGET_TOKENS = 130
PROBLEM = "Core.InitsUpdatesComm"


@dataclass(frozen=True)
class Kernel:
    kind: str
    family: str
    note: str
    apply: Callable[[str], str]


def _sub(old: str, new: str, text: str, count: int = 1) -> str:
    from jevops.memory import apply_literal_fold

    return apply_literal_fold(text, {"old": old, "new": new, "count": count})


def _kernel(kind: str, family: str, note: str, old: str, new: str, *, count: int = 1) -> Kernel:
    return Kernel(kind, family, note, lambda text, _o=old, _n=new, _c=count: _sub(_o, _n, text, _c))


# Ordered 268→174 path. Each step is a no-op if its pattern is already gone.
KERNELS: tuple[Kernel, ...] = (
    _kernel(
        "drop_not_intro_specialize",
        "drop",
        "Drop apply Not.intro and specialize Hnd _ Hin; keep intros Hin; simp_all.",
        "          apply Not.intro\n          intros Hin\n          specialize Hnd _ Hin\n          simp_all",
        "          intros Hin\n          simp_all",
    ),
    _kernel(
        "fold_init_exacts",
        "rewrite",
        "refine updatedStatesInit ?_ ?_ plus two exacts -> one exact.",
        "    refine updatedStatesInit Hlen1 ?_ ?_\n"
        "    exact InitStatesNotDefined Hinit\n"
        "    exact InitStatesNodup Hinit",
        "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)",
    ),
    _kernel(
        "and_intro_constructor",
        "rewrite",
        "apply And.intro -> constructor.",
        "    apply And.intro\n",
        "    constructor\n",
    ),
    _kernel(
        "fold_nested_init_term",
        "rewrite",
        "Nested apply updatedStatesInit bullets -> one exact term with Hlen1.",
        "          apply updatedStatesInit\n"
        "          . simp_all\n"
        "          . apply UpdateStateNotDefMonotone' ?_ Hup\n"
        "            apply UpdateStatesNotDefMonotone' ?_ Hups\n"
        "            apply InitStatesNotDefined Hinit\n"
        "          . exact InitStatesNodup Hinit",
        "          exact updatedStatesInit Hlen1\n"
        "            (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "            (InitStatesNodup Hinit)",
    ),
    _kernel(
        "fold_some_init_term",
        "rewrite",
        "update_some apply updatedStatesInit chain -> one exact term.",
        "    . apply updatedStatesInit Hlen1\n"
        "      apply UpdateStateNotDefMonotone' ?_ Hup\n"
        "      apply UpdateStatesNotDefMonotone' ?_ Hups\n"
        "      exact InitStatesNotDefined Hinit\n"
        "      exact InitStatesNodup Hinit",
        "    . exact updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)",
    ),
    _kernel(
        "fold_some_init_term_hole",
        "rewrite",
        "Same fold after one-hole ?_ -> _ denoise.",
        "    . apply updatedStatesInit Hlen1\n"
        "      apply UpdateStateNotDefMonotone' _ Hup\n"
        "      apply UpdateStatesNotDefMonotone' _ Hups\n"
        "      exact InitStatesNotDefined Hinit\n"
        "      exact InitStatesNodup Hinit",
        "    . exact updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)",
    ),
    _kernel(
        "fill_refine_init",
        "rewrite",
        "Put the InitStates term into refine ⟨rfl, ·, ?_⟩; keep the · apply bullet.",
        "    refine ⟨rfl, ?_, ?_⟩\n"
        "    . exact updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)\n"
        "    . apply UpdateStates.update_some",
        "    refine ⟨rfl, (updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)), ?_⟩\n"
        "    . apply UpdateStates.update_some",
    ),
    Kernel(
        "share_init_term",
        "rewrite",
        "have Hst := the duplicated updatedStatesInit term; reuse twice.",
        lambda text: (
            text.replace(
                "    refine ⟨rfl, (updatedStatesInit Hlen1\n"
                "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
                "        (InitStatesNodup Hinit)), ?_⟩\n",
                "    have Hst := updatedStatesInit Hlen1\n"
                "      (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
                "      (InitStatesNodup Hinit)\n"
                "    refine ⟨rfl, Hst, ?_⟩\n",
                1,
            ).replace(
                "          exact updatedStatesInit Hlen1\n"
                "            (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
                "            (InitStatesNodup Hinit)",
                "          exact Hst",
                1,
            )
            if (
                "    refine ⟨rfl, (updatedStatesInit Hlen1\n"
                "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
                "        (InitStatesNodup Hinit)), ?_⟩\n"
                in text
                and "          exact updatedStatesInit Hlen1\n"
                "            (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
                "            (InitStatesNodup Hinit)"
                in text
            )
            else text
        ),
    ),
    _kernel(
        "drop_hk_type",
        "rewrite",
        "Drop the type ascription on have Hk.",
        "  have Hk : (isDefined σ' ks) := UpdateStatesDefined Hup",
        "  have Hk := UpdateStatesDefined Hup",
    ),
    _kernel(
        "drop_named_val",
        "drop",
        "Drop named (v':=val) on updatedStateUpdate.",
        "          apply updatedStateUpdate (v':=val)",
        "          apply updatedStateUpdate",
    ),
    Kernel(
        "lift_hnd",
        "rewrite",
        "Lift have Hnd to the update_some case and reuse it in Hst.",
        lambda text: (
            text.replace(
                "    have Hst :=",
                "    have Hnd := InitStatesNotDefined Hinit\n    have Hst :=",
                1,
            )
            .replace(
                "UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups",
                "UpdateStatesNotDefMonotone' Hnd Hups",
                1,
            )
            .replace("          have Hnd := InitStatesNotDefined Hinit\n", "", 1)
            if (
                "UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups" in text
                and "          have Hnd := InitStatesNotDefined Hinit\n" in text
                and "\n    have Hnd := InitStatesNotDefined Hinit\n" not in ("\n" + text + "\n")
            )
            else text
        ),
    ),
    _kernel(
        "drop_generalizing",
        "drop",
        "Drop induction generalizing σ''.",
        "  induction Hup generalizing σ''",
        "  induction Hup",
    ),
    _kernel(
        "ih_by",
        "rewrite",
        "ih apply plus two simp bullets -> exact (ih by ...).",
        "      . apply (ih Hinit ?_ ?_).2.2\n"
        "        . simp [isDefined] at * <;> simp_all\n"
        "        . simp_all",
        "      . exact (ih Hinit (by simp [isDefined] at *; simp_all) (by simp_all)).2.2",
    ),
    _kernel(
        "fold_update_term",
        "rewrite",
        "updatedStateUpdate + InitStatesSomeMonotone + Hst -> one exact.",
        "          apply updatedStateUpdate\n"
        "          apply InitStatesSomeMonotone heq\n"
        "          exact Hst",
        "          exact updatedStateUpdate (InitStatesSomeMonotone heq Hst)",
    ),
    _kernel(
        "hnd_merge_simp",
        "rewrite",
        "Merge Hnd simp at * into simp_all [isNotDefined, isDefined].",
        "          simp [isNotDefined, isDefined] at *\n"
        "          intros Hin\n"
        "          simp_all",
        "          intros Hin\n          simp_all [isNotDefined, isDefined]",
    ),
    _kernel(
        "ih_simp_all_defined",
        "rewrite",
        "ih first by: simp_all [isDefined].",
        "      . exact (ih Hinit (by simp [isDefined] at *; simp_all) (by simp_all)).2.2",
        "      . exact (ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2",
    ),
    Kernel(
        "anon_hdef",
        "rewrite",
        "Anonymous have for UpdateStateDefined'; simp/split at this.",
        lambda text: (
            text.replace("        . have Hdef := UpdateStateDefined' Hup\n", "        . have := UpdateStateDefined' Hup\n")
            .replace("at Hdef", "at this")
            if "        . have Hdef := UpdateStateDefined' Hup\n" in text
            else text
        ),
    ),
    _kernel(
        "split_assumption",
        "rewrite",
        "Drop next val heq =>; use by assumption.",
        "          split at this <;> simp_all\n"
        "          next val heq =>\n"
        "          exact updatedStateUpdate (InitStatesSomeMonotone heq Hst)",
        "          split at this <;> simp_all\n"
        "          exact updatedStateUpdate (InitStatesSomeMonotone (by assumption) Hst)",
    ),
    Kernel(
        "fill_ih_arg",
        "rewrite",
        "Pass ih as the second argument of update_some.",
        lambda text: (
            text.replace(
                "    . apply UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs')\n",
                "    . refine UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs') ?_ "
                "(ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2\n",
                1,
            ).replace(
                "\n      . exact (ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2",
                "",
                1,
            )
            if (
                "    . apply UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs')\n" in text
                and "      . exact (ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2" in text
            )
            else text
        ),
    ),
    _kernel(
        "double_ctor_hst",
        "rewrite",
        "Two constructors + rfl + exact Hst instead of refine ⟨rfl, Hst, ?_⟩.",
        "    refine ⟨rfl, Hst, ?_⟩\n    . refine UpdateStates.update_some",
        "    constructor\n    rfl\n    constructor\n    exact Hst\n    . refine UpdateStates.update_some",
    ),
    _kernel(
        "assumption_hst",
        "rewrite",
        "exact Hst -> assumption.",
        "    exact Hst\n",
        "    assumption\n",
    ),
    _kernel(
        "monotone_star",
        "rewrite",
        "(by assumption) -> ‹_› on InitStatesSomeMonotone.",
        "InitStatesSomeMonotone (by assumption) Hst",
        "InitStatesSomeMonotone ‹_› Hst",
    ),
    _kernel(
        "anon_hk",
        "rewrite",
        "have Hk := -> have := for UpdateStatesDefined.",
        "  have Hk := UpdateStatesDefined Hup",
        "  have := UpdateStatesDefined Hup",
    ),
    Kernel(
        "anon_hnd",
        "rewrite",
        "Anonymous have for InitStatesNotDefined; use this in Hst.",
        lambda text: (
            text.replace(
                "    have Hnd := InitStatesNotDefined Hinit\n",
                "    have := InitStatesNotDefined Hinit\n",
                1,
            ).replace(
                "UpdateStatesNotDefMonotone' Hnd Hups",
                "UpdateStatesNotDefMonotone' this Hups",
                1,
            )
            if "    have Hnd := InitStatesNotDefined Hinit\n" in text
            else text
        ),
    ),
    _kernel(
        "exists_noparens",
        "rewrite",
        "exists (updatedStates ...) -> exists updatedStates ...",
        "exists (updatedStates σ ks' vs')",
        "exists updatedStates σ ks' vs'",
    ),
    _kernel(
        "dollar_nodup",
        "rewrite",
        "$ InitStatesNodup Hinit (last arg of updatedStatesInit).",
        "(InitStatesNodup Hinit)",
        "$ InitStatesNodup Hinit",
        count=2,
    ),
    _kernel(
        "dollar_update",
        "rewrite",
        "exact updatedStateUpdate $ InitStatesSomeMonotone ...",
        "exact updatedStateUpdate (InitStatesSomeMonotone ‹_› Hst)",
        "exact updatedStateUpdate $ InitStatesSomeMonotone ‹_› Hst",
    ),
    _kernel(
        "simp_all_hdef",
        "rewrite",
        "simp [isDefined, Option.isSome] at this -> simp_all [isDefined, Option.isSome].",
        "simp [isDefined, Option.isSome] at this",
        "simp_all [isDefined, Option.isSome]",
    ),
    _kernel(
        "ih_dollar_snd",
        "rewrite",
        "ih second by-arg: $ by simp_all.",
        "(ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2",
        "(ih Hinit (by simp_all [isDefined]) $ by simp_all).2.2",
    ),
    _kernel(
        "sigma_hole",
        "rewrite",
        "updatedStates σ₀ ks' vs' -> updatedStates _ ks' vs' (σ₀ is two tokens).",
        "(σ':=updatedStates σ₀ ks' vs')",
        "(σ':=updatedStates _ ks' vs')",
    ),
    _kernel(
        "case_drop_unused",
        "drop",
        "Drop unused update_some constructor binders.",
        "  case update_some σ x v σ₀ xs vs σ₁ Hup Hups ih =>",
        "  case update_some Hup Hups ih =>",
    ),
    _kernel(
        "case_none_dot",
        "rewrite",
        "case update_none => -> ·",
        "  case update_none =>\n",
        "  ·\n",
    ),
    _kernel(
        "case_some_rename_i",
        "rewrite",
        "case update_some Hup Hups ih => -> · + rename_i.",
        "  case update_some Hup Hups ih =>\n",
        "  ·\n    rename_i Hup Hups ih\n",
    ),
    _kernel(
        "unzip_simp_all",
        "rewrite",
        "rw [List.unzip_zip] <;> simp_all -> simp_all [List.unzip_zip] (MCA strength_reduction).",
        "        . rw [List.unzip_zip] <;> simp_all",
        "        . simp_all [List.unzip_zip]",
    ),
    _kernel(
        "merge_unzip_nd",
        "rewrite",
        "Fold unzip simp_all into the trailing isNotDefined/isDefined simp_all.",
        "        . simp_all [List.unzip_zip]\n"
        "          intros Hin\n"
        "          simp_all [isNotDefined, isDefined]",
        "        . intros Hin\n"
        "          simp_all [List.unzip_zip, isNotDefined, isDefined]",
    ),
    _kernel(
        "split_all_goals",
        "rewrite",
        "split at this <;> simp_all -> split at this; all_goals simp_all.",
        "          split at this <;> simp_all",
        "          split at this\n          all_goals simp_all",
    ),
    _kernel(
        "dot_update_some",
        "rewrite",
        "UpdateStates.update_some -> .update_some (inductive constructor notation).",
        "refine UpdateStates.update_some",
        "refine .update_some",
    ),
    _kernel(
        "drop_named_sigma",
        "drop",
        "Drop (σ':=updatedStates _ ks' vs'); .update_some infers σ' from the expected type.",
        ". refine .update_some (σ':=updatedStates _ ks' vs') ?_ (ih Hinit (by simp_all [isDefined]) $ by simp_all).2.2",
        ". refine .update_some ?_ (ih Hinit (by simp_all [isDefined]) $ by simp_all).2.2",
    ),
    _kernel(
        "none_simp_ctor",
        "rewrite",
        "update_none: simp_all [InitStatesUpdated Hinit]; constructor (drop exact/simp/constructor).",
        "    simp_all\n"
        "    constructor\n"
        "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) $ InitStatesNodup Hinit\n"
        "    simp [InitStatesUpdated Hinit]\n"
        "    constructor",
        "    simp_all [InitStatesUpdated Hinit]\n    constructor",
    ),
    _kernel(
        "drop_hin",
        "drop",
        "intros Hin -> intro; the binder name is unused (MCA search_space).",
        "        . intros Hin",
        "        . intro",
    ),
    _kernel(
        "ih_defined_hups",
        "rewrite",
        "ih first extra arg: UpdateStatesDefined Hups instead of by simp_all [isDefined].",
        "(ih Hinit (by simp_all [isDefined]) $ by simp_all).2.2",
        "(ih Hinit (UpdateStatesDefined Hups) $ by simp_all).2.2",
    ),
    _kernel(
        "ih_length_hups",
        "rewrite",
        "ih second extra arg: UpdateStatesLength Hups instead of by simp_all.",
        "(ih Hinit (UpdateStatesDefined Hups) $ by simp_all).2.2",
        "(ih Hinit (UpdateStatesDefined Hups) $ UpdateStatesLength Hups).2.2",
    ),
)


def family_tree() -> dict[str, dict[str, str]]:
    from jevops.pick import tree_from_items

    return tree_from_items(
        KERNELS,
        family_fn=lambda item: item.family,
        kind_fn=lambda item: item.kind,
        note_fn=lambda item: item.note,
        keep={
            "keep": {"keep": "Do not edit. The current lake-valid script is already locally minimal."},
            "drop": {},
            "rewrite": {},
            "join": {},
        },
    )


def apply_kernel(kind: str, tactics: str) -> str:
    from jevops.pick import first_apply

    return first_apply(
        KERNELS,
        kind,
        tactics,
        kind_fn=lambda item: item.kind,
        apply_fn=lambda item, body: item.apply(body),
    )


def propose(tactics: str) -> list[dict[str, str]]:
    """One-step proposals for TypeSafe / MCMC / hammer (no lake, no LLM)."""

    from jevops.pick import unique_transforms

    out: list[dict[str, str]] = []
    best = best_replay(tactics)
    if best and best != tactics:
        out.append(
            {
                "kind": "inits_best",
                "tactics": best,
                "note": "verified compound deletion of Hlen2 and UpdateStatesLength Hups",
                "family": "mca",
            }
        )
    for kernel, nxt in unique_transforms(
        tactics,
        KERNELS,
        apply_fn=lambda item, body: item.apply(body),
    ):
        out.append({"kind": kernel.kind, "tactics": nxt, "note": kernel.note, "family": kernel.family})
    return out


def pca_mca_ops(tactics: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """PCA/MCA draft triples: ``(family, tactics, ops)``.

    Full ``inits_replay`` is first so TypeSafe/lake always see the 268→139 cut
    even when ``MAX_DRAFTS`` truncates one-step kernels.
    """

    current = tactics.strip("\n")
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    replayed = replay(current)
    if replayed and replayed != current:
        rows.append(
            (
                "inits_replay",
                replayed,
                ("inits_replay", "mca", "no_llm"),
            )
        )
    best = best_replay(current)
    if best and best != current:
        rows.append(
            (
                "inits_best",
                best,
                ("inits_best", "mca", "verified_compound", "no_llm"),
            )
        )
    for item in propose(current):
        rows.append(
            (
                str(item["family"]),
                str(item["tactics"]),
                (str(item["kind"]), "mca", "kernel"),
            )
        )
    return rows


def replay(tactics: str) -> str:
    """Apply every kernel in order. Original warmup script becomes the 174 cut."""

    from jevops.pick import compose_steps

    text, _applied = compose_steps(
        tactics,
        tuple((kernel.kind, kernel.apply) for kernel in KERNELS),
    )
    return text


def best_replay(tactics: str) -> str:
    """Apply the verified compound shortening after the historical 139 cut.

    The two deletions must be admitted together: removing either ``Hlen2`` or
    the ``UpdateStatesLength Hups`` induction argument in isolation fails in
    Lean, while the compound candidate compiles at the pinned v4.26 checkout.
    """

    body = replay(tactics)
    body = body.replace("  have Hlen2 := UpdateStatesLength Hup\n", "", 1)
    body = body.replace(" $ UpdateStatesLength Hups", "", 1)
    return body


IH_APPLY = "apply (ih Hinit ?_ ?_).2.2"
IH_APPLY_SHORT = "apply (ih Hinit).2.2"
IH_EXACT = "exact (ih Hinit ?_ ?_).2.2"
REFINE_RFL = "refine ⟨rfl, ?_, ?_⟩"
HND_BLOCK = (
    "          have Hnd := InitStatesNotDefined Hinit\n"
    "          simp [isNotDefined, isDefined] at *\n"
    "          intros Hin\n"
    "          simp_all"
)
HND_REPLACEMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "hnd_intro_simp",
        "          intros Hin\n"
        "          simp [InitStatesNotDefined Hinit, isNotDefined, isDefined] at *",
        "Hnd block -> intros Hin + combined simp",
    ),
    (
        "hnd_simp_only",
        "          simp [InitStatesNotDefined Hinit, isNotDefined, isDefined]",
        "Hnd block -> one simp of InitStatesNotDefined",
    ),
    (
        "hnd_intro_exact",
        "          intro Hin\n"
        "          simp [isNotDefined, isDefined, InitStatesNotDefined] at *",
        "Hnd block -> intro Hin + InitStatesNotDefined simp",
    ),
)


def mcmc_extras(tactics: str) -> list[dict[str, Any]]:
    """Inits-specific MCMC replacements. Generic join/drop lives in propose_closed_edits."""

    from jevops.mask import any_line, drop_index
    from jevops.tactics import collapse_ih_simps

    rows: list[dict[str, Any]] = []

    def add(kind: str, body: str, note: str, *, lock: bool = True) -> None:
        rows.append({"kind": str(kind), "tactics": str(body or ""), "note": str(note), "lock": lock})

    best = best_replay(tactics)
    if best and best != tactics:
        add(
            "inits_best",
            best,
            "verified compound deletion of Hlen2 and UpdateStatesLength Hups",
            lock=False,
        )

    if HND_BLOCK in tactics:
        for kind, repl, note in HND_REPLACEMENTS:
            add(kind, tactics.replace(HND_BLOCK, repl, 1), note)
    none_and = "    apply And.intro\n"
    if none_and in tactics:
        add("drop_and_intro", tactics.replace(none_and, "", 1), "drop apply And.intro before refine updatedStatesInit")
    nested = "          . simp_all\n          . apply UpdateStateNotDefMonotone'"
    if nested in tactics:
        add(
            "drop_nested_init_simp",
            tactics.replace(nested, "          . apply UpdateStateNotDefMonotone'", 1),
            "drop nested . simp_all under apply updatedStatesInit",
        )
    if REFINE_RFL in tactics:
        add("rewrite_refine_constructor", tactics.replace(REFINE_RFL, "constructor", 1), "refine ⟨rfl,?_,?_⟩ -> constructor")
    if IH_APPLY in tactics:
        add("rewrite_ih_short", tactics.replace(IH_APPLY, IH_APPLY_SHORT, 1), "ih ?_ ?_ -> ih")
        add("rewrite_ih_exact", tactics.replace(IH_APPLY, IH_EXACT, 1), "apply ih -> exact ih")
        folded = collapse_ih_simps(tactics, needle=IH_APPLY)
        if folded:
            add("collapse_ih_simps", folded, "ih apply <;> simp_all, drop two simp bullets")
    lines = tactics.splitlines()
    has_not_intro = any_line(tactics, lambda line: "Not.intro" in line)
    has_specialize_hnd = any_line(tactics, lambda line: "specialize Hnd" in line)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("intros Hin") and not has_not_intro:
            add("drop_orphan_intros_hin", drop_index(tactics, index), "drop orphan intros Hin")
        if stripped.startswith("have Hnd") and not has_specialize_hnd:
            add("drop_orphan_hnd", drop_index(tactics, index), "drop orphan have Hnd")
        if "isNotDefined" in stripped and not has_specialize_hnd:
            add("drop_isnotdefined_simp", drop_index(tactics, index), "drop isNotDefined simp")
    none_refine = (
        "    refine updatedStatesInit Hlen1 ?_ ?_\n"
        "    exact InitStatesNotDefined Hinit\n"
        "    exact InitStatesNodup Hinit"
    )
    none_folded = "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)"
    if none_refine in tactics:
        add("fold_init_exacts", tactics.replace(none_refine, none_folded, 1), "refine+two exacts -> one exact updatedStatesInit")
    some_apply = (
        "    . apply updatedStatesInit Hlen1\n"
        "      apply UpdateStateNotDefMonotone' ?_ Hup\n"
        "      apply UpdateStatesNotDefMonotone' ?_ Hups\n"
        "      exact InitStatesNotDefined Hinit\n"
        "      exact InitStatesNodup Hinit"
    )
    some_term = (
        "    . exact updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)"
    )
    if some_apply in tactics:
        add("fold_some_init_term", tactics.replace(some_apply, some_term, 1), "update_some apply chain -> term updatedStatesInit")
    nested_apply = (
        "          apply updatedStatesInit\n"
        "          . simp_all\n"
        "          . apply UpdateStateNotDefMonotone' ?_ Hup\n"
        "            apply UpdateStatesNotDefMonotone' ?_ Hups\n"
        "            apply InitStatesNotDefined Hinit\n"
        "          . exact InitStatesNodup Hinit"
    )
    nested_term = (
        "          exact updatedStatesInit Hlen1\n"
        "            (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "            (InitStatesNodup Hinit)"
    )
    if nested_apply in tactics:
        add("fold_nested_init_term", tactics.replace(nested_apply, nested_term, 1), "nested apply updatedStatesInit -> term with Hlen1")
    none_and_block = (
        "    apply And.intro\n"
        "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)\n"
        "    simp [InitStatesUpdated Hinit]\n"
        "    constructor"
    )
    none_and_term = (
        "    exact ⟨updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit),\n"
        "      by simp [InitStatesUpdated Hinit]; constructor⟩"
    )
    if none_and_block in tactics:
        add("fold_none_and", tactics.replace(none_and_block, none_and_term, 1), "And.intro+exact+simp+constructor -> one exact")
    if "    apply And.intro\n" in tactics:
        add(
            "and_intro_constructor",
            tactics.replace("    apply And.intro\n", "    constructor\n", 1),
            "apply And.intro -> constructor",
        )
    some_bullet = (
        "    refine ⟨rfl, ?_, ?_⟩\n"
        "    . exact updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)\n"
        "    . apply UpdateStates.update_some"
    )
    some_filled = (
        "    refine ⟨rfl, (updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)), ?_⟩\n"
        "    . apply UpdateStates.update_some"
    )
    if some_bullet in tactics:
        add("fill_refine_init", tactics.replace(some_bullet, some_filled, 1), "put updatedStatesInit term into refine ⟨rfl, ·, ?_⟩")
    none_ctor = (
        "    constructor\n"
        "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)\n"
        "    simp [InitStatesUpdated Hinit]\n"
        "    constructor"
    )
    none_ctor_term = (
        "    exact ⟨updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit),\n"
        "      by simp [InitStatesUpdated Hinit]; constructor⟩"
    )
    if none_ctor in tactics:
        add("fold_none_ctor", tactics.replace(none_ctor, none_ctor_term, 1), "constructor+exact+simp+constructor -> one exact")
    refine_paren = (
        "    refine ⟨rfl, (updatedStatesInit Hlen1\n"
        "        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "        (InitStatesNodup Hinit)), ?_⟩\n"
    )
    nested_exact = (
        "          exact updatedStatesInit Hlen1\n"
        "            (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
        "            (InitStatesNodup Hinit)"
    )
    if refine_paren in tactics and nested_exact in tactics:
        shared = (
            "    have Hst := updatedStatesInit Hlen1\n"
            "      (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n"
            "      (InitStatesNodup Hinit)\n"
            "    refine ⟨rfl, Hst, ?_⟩\n"
        )
        add(
            "share_init_term",
            tactics.replace(refine_paren, shared, 1).replace(nested_exact, "          exact Hst", 1),
            "have Hst := duplicated updatedStatesInit term; reuse twice",
        )
        add(
            "drop_refine_parens",
            tactics.replace(
                refine_paren,
                "    refine ⟨rfl, updatedStatesInit Hlen1\n        (UpdateStateNotDefMonotone' (UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups) Hup)\n        (InitStatesNodup Hinit), ?_⟩\n",
                1,
            ),
            "drop extra parens around updatedStatesInit in refine",
        )
    hk_typed = "  have Hk : (isDefined σ' ks) := UpdateStatesDefined Hup"
    if hk_typed in tactics:
        add("drop_hk_type", tactics.replace(hk_typed, "  have Hk := UpdateStatesDefined Hup", 1), "drop Hk type ascription")
    named_sigma = "(σ':=updatedStates σ₀ ks' vs')"
    if named_sigma in tactics:
        add("drop_named_sigma", tactics.replace(named_sigma, "", 1), "drop named σ' := updatedStates argument")
        add("positional_update_some", tactics.replace(named_sigma, "(updatedStates σ₀ ks' vs')", 1), "named σ' arg -> positional")
    named_val = "(v':=val)"
    if named_val in tactics:
        add("drop_named_val", tactics.replace(" (v':=val)", "", 1), "drop named v' := val argument")
        add("drop_named_val_space", tactics.replace(named_val, "", 1), "drop named v' := val leaving a space")
    simp_opt = "simp [isDefined, Option.isSome] at Hdef"
    if simp_opt in tactics:
        add("simp_hdef_defined", tactics.replace(simp_opt, "simp [isDefined] at Hdef", 1), "drop Option.isSome from Hdef simp")
        add("simp_hdef_bare", tactics.replace(simp_opt, "simp at Hdef", 1), "bare simp at Hdef")
    simp_upd = "simp [UpdateStateUpdated Hup, updatedStates]"
    if simp_upd in tactics:
        add("simp_upd_only", tactics.replace(simp_upd, "simp [UpdateStateUpdated Hup]", 1), "drop updatedStates from simp")
        add("simp_states_only", tactics.replace(simp_upd, "simp [updatedStates]", 1), "drop UpdateStateUpdated from simp")
        add("simp_upd_no_hup", tactics.replace(simp_upd, "simp [UpdateStateUpdated, updatedStates]", 1), "drop Hup arg from UpdateStateUpdated simp")
    simp_nd = "simp [isNotDefined, isDefined] at *"
    if simp_nd in tactics:
        add("simp_nd_only", tactics.replace(simp_nd, "simp [isNotDefined] at *", 1), "drop isDefined from Hnd simp")
        add("simp_nd_bare", tactics.replace(simp_nd, "simp at *", 1), "bare simp at * in Hnd block")
    defined_chain = "simp [isDefined] at * <;> simp_all"
    if defined_chain in tactics:
        add("collapse_defined_simp", tactics.replace(defined_chain, "simp_all", 1), "simp [isDefined] at * <;> simp_all -> simp_all")
    hst_undef = "UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups"
    inner_hnd = "          have Hnd := InitStatesNotDefined Hinit\n"
    if hst_undef in tactics and inner_hnd in tactics:
        lifted = (
            tactics.replace("    have Hst :=", "    have Hnd := InitStatesNotDefined Hinit\n    have Hst :=", 1)
            .replace(hst_undef, "UpdateStatesNotDefMonotone' Hnd Hups", 1)
            .replace(inner_hnd, "", 1)
        )
        add("lift_hnd", lifted, "lift have Hnd to the update_some case and reuse in Hst")
    none_simp_all = "    simp_all\n    constructor\n"
    if none_simp_all in tactics:
        add("drop_none_simp_all", tactics.replace(none_simp_all, "    constructor\n", 1), "drop leading simp_all in update_none")
    none_upd = "    simp [InitStatesUpdated Hinit]\n"
    if none_upd in tactics:
        add("drop_none_init_simp", tactics.replace(none_upd, "", 1), "drop simp [InitStatesUpdated] in update_none")
        add("none_init_simp_bare", tactics.replace(none_upd, "    simp\n", 1), "bare simp in update_none")
    if " generalizing σ''" in tactics:
        add("drop_generalizing", tactics.replace(" generalizing σ''", "", 1), "drop induction generalizing σ''")
    if "  have Hlen2 := UpdateStatesLength Hup\n" in tactics:
        add("drop_hlen2", tactics.replace("  have Hlen2 := UpdateStatesLength Hup\n", "", 1), "drop Hlen2", lock=False)
    if "  have Hk := UpdateStatesDefined Hup\n" in tactics:
        add("drop_hk", tactics.replace("  have Hk := UpdateStatesDefined Hup\n", "", 1), "drop Hk", lock=False)
        add(
            "anon_hk",
            tactics.replace("  have Hk := UpdateStatesDefined Hup\n", "  have := UpdateStatesDefined Hup\n", 1),
            "anonymous have for Hk",
            lock=False,
        )
    three = (
        "          apply updatedStateUpdate\n"
        "          apply InitStatesSomeMonotone heq\n"
        "          exact Hst"
    )
    if three in tactics:
        add(
            "fold_update_term",
            tactics.replace(three, "          exact updatedStateUpdate (InitStatesSomeMonotone heq Hst)", 1),
            "updatedStateUpdate + monotone + Hst -> one exact",
        )
    if "rw [← updatedStateComm']" in tactics:
        add("rw_comm_fwd", tactics.replace("rw [← updatedStateComm']", "rw [updatedStateComm']", 1), "drop ← on updatedStateComm'")
    ih_block = (
        "      . apply (ih Hinit ?_ ?_).2.2\n"
        "        . simp [isDefined] at * <;> simp_all\n"
        "        . simp_all"
    )
    if ih_block in tactics:
        add(
            "ih_by",
            tactics.replace(ih_block, "      . exact (ih Hinit (by simp [isDefined] at *; simp_all) (by simp_all)).2.2", 1),
            "ih apply + two simp bullets -> exact (ih ... by ...)",
        )
        add(
            "ih_by_simp_all",
            tactics.replace(ih_block, "      . exact (ih Hinit (by simp_all) (by simp_all)).2.2", 1),
            "ih apply + two simp bullets -> exact (ih by simp_all)",
        )
    if "next val heq =>" in tactics:
        add("drop_next_names", tactics.replace("next val heq =>", "next =>", 1), "drop next val heq binders")
        add("next_heq_only", tactics.replace("next val heq =>", "next _ heq =>", 1), "drop unused next val binder")
    hnd_tail = (
        "          simp [isNotDefined, isDefined] at *\n"
        "          intros Hin\n"
        "          simp_all"
    )
    if hnd_tail in tactics:
        add(
            "hnd_merge_simp",
            tactics.replace(hnd_tail, "          intros Hin\n          simp_all [isNotDefined, isDefined]", 1),
            "merge Hnd simp at * into simp_all [isNotDefined, isDefined]",
        )
    case_hnd = "    have Hnd := InitStatesNotDefined Hinit\n"
    if case_hnd in tactics and "  induction Hup\n" in tactics:
        pre = tactics.replace("  induction Hup\n", "  have Hnd := InitStatesNotDefined Hinit\n  induction Hup\n", 1).replace(case_hnd, "", 1)
        pre = pre.replace(
            "exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)",
            "exact updatedStatesInit Hlen1 Hnd (InitStatesNodup Hinit)",
            1,
        )
        add("lift_hnd_pre", pre, "move Hnd before induction; reuse in update_none")
    ih_by_line = "      . exact (ih Hinit (by simp [isDefined] at *; simp_all) (by simp_all)).2.2"
    if ih_by_line in tactics:
        add("ih_simp_all_defined", tactics.replace(ih_by_line, "      . exact (ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2", 1), "ih first by: simp_all [isDefined]")
        add("ih_simp_defined", tactics.replace(ih_by_line, "      . exact (ih Hinit (by simp [isDefined]) (by simp_all)).2.2", 1), "ih first by: simp [isDefined] only")
        add("ih_drop_at_star", tactics.replace(ih_by_line, "      . exact (ih Hinit (by simp [isDefined]; simp_all) (by simp_all)).2.2", 1), "ih first by: drop at *")
    none_pair = (
        "    simp_all\n"
        "    constructor\n"
        "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)\n"
        "    simp [InitStatesUpdated Hinit]\n"
        "    constructor"
    )
    none_merged = (
        "    simp_all [InitStatesUpdated Hinit]\n"
        "    constructor\n"
        "    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)\n"
        "    constructor"
    )
    if none_pair in tactics:
        add("merge_none_simp", tactics.replace(none_pair, none_merged, 1), "fold InitStatesUpdated into leading simp_all")
        add("none_only_simp_all", tactics.replace(none_pair, "    simp_all [InitStatesUpdated Hinit]", 1), "update_none body is just simp_all [InitStatesUpdated]")
        add(
            "none_simp_all_lemmas",
            tactics.replace(none_pair, "    simp_all [updatedStatesInit, InitStatesNotDefined, InitStatesNodup, InitStatesUpdated]", 1),
            "update_none: one simp_all of the four lemmas",
        )
        add(
            "none_drop_last_ctor",
            tactics.replace(
                none_pair,
                "    simp_all\n    constructor\n    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)\n    simp [InitStatesUpdated Hinit]",
                1,
            ),
            "drop trailing constructor in update_none",
        )
        add(
            "none_ctor_simp_all",
            tactics.replace(none_pair, "    constructor <;> simp_all [updatedStatesInit, InitStatesUpdated]", 1),
            "update_none: constructor <;> simp_all lemmas",
        )
        add(
            "none_last_simp_all",
            tactics.replace(
                none_pair,
                "    simp_all\n    constructor\n    exact updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit)\n    simp_all [InitStatesUpdated Hinit]",
                1,
            ),
            "last update_none tactics: simp_all [InitStatesUpdated] without constructor",
        )
        add(
            "none_exact_pair",
            tactics.replace(
                none_pair,
                "    simp_all\n    exact ⟨updatedStatesInit Hlen1 (InitStatesNotDefined Hinit) (InitStatesNodup Hinit), by simp [InitStatesUpdated Hinit]; constructor⟩",
                1,
            ),
            "update_none And as one exact ⟨init, by simp; constructor⟩",
        )
    none_hnd_pair = (
        "    simp_all\n"
        "    constructor\n"
        "    exact updatedStatesInit Hlen1 Hnd (InitStatesNodup Hinit)\n"
        "    simp [InitStatesUpdated Hinit]\n"
        "    constructor"
    )
    none_hnd_merged = (
        "    simp_all [InitStatesUpdated Hinit]\n"
        "    constructor\n"
        "    exact updatedStatesInit Hlen1 Hnd (InitStatesNodup Hinit)\n"
        "    constructor"
    )
    if none_hnd_pair in tactics:
        add("merge_none_simp", tactics.replace(none_hnd_pair, none_hnd_merged, 1), "fold InitStatesUpdated into leading simp_all")
        add("none_only_simp_all", tactics.replace(none_hnd_pair, "    simp_all [InitStatesUpdated Hinit]", 1), "update_none body is just simp_all [InitStatesUpdated]")
    hdef = "        . have Hdef := UpdateStateDefined' Hup\n"
    if hdef in tactics:
        add("anon_hdef", tactics.replace(hdef, "        . have := UpdateStateDefined' Hup\n").replace("at Hdef", "at this"), "anonymous have for UpdateStateDefined'")
    hnd_merged = "          intros Hin\n          simp_all [isNotDefined, isDefined]"
    if hnd_merged in tactics:
        add("hnd_simp_all_only", tactics.replace(hnd_merged, "          intros Hin\n          simp_all", 1), "drop isNotDefined/isDefined args from trailing simp_all")
        add("hnd_intro_simp_all_nd", tactics.replace(hnd_merged, "          intro Hin; simp_all [isNotDefined, isDefined]", 1), "intro Hin; simp_all [..] on one line")
        add("hnd_no_intros", tactics.replace(hnd_merged, "          simp_all [isNotDefined, isDefined]", 1), "drop intros Hin before trailing simp_all")
    refine_hst = "    refine ⟨rfl, Hst, ?_⟩\n    . apply UpdateStates.update_some"
    ctor_hst = "    constructor\n    exact rfl\n    exact Hst\n    apply UpdateStates.update_some"
    if refine_hst in tactics:
        add("ctor_rfl_hst", tactics.replace(refine_hst, ctor_hst, 1), "refine ⟨rfl, Hst, ?_⟩ -> constructor; exact rfl; exact Hst")
    split_next = (
        "          split at this <;> simp_all\n"
        "          next val heq =>\n"
        "          exact updatedStateUpdate (InitStatesSomeMonotone heq Hst)"
    )
    if split_next in tactics:
        add(
            "split_assumption",
            tactics.replace(
                split_next,
                "          split at this <;> simp_all\n          exact updatedStateUpdate (InitStatesSomeMonotone (by assumption) Hst)",
                1,
            ),
            "drop next val heq; use by assumption",
        )
        add(
            "split_exact",
            tactics.replace(
                split_next,
                "          split at this <;> exact updatedStateUpdate (InitStatesSomeMonotone (by simp_all) Hst)",
                1,
            ),
            "split <;> exact updatedStateUpdate",
        )
    unzip = (
        "        . rw [List.unzip_zip] <;> simp_all\n"
        "          intros Hin\n"
        "          simp_all [isNotDefined, isDefined]"
    )
    if unzip in tactics:
        add(
            "unzip_no_first_simp_all",
            tactics.replace(unzip, "        . rw [List.unzip_zip]\n          intros Hin\n          simp_all [isNotDefined, isDefined]", 1),
            "drop <;> simp_all after unzip_zip",
        )
    case_some = "  case update_some σ x v σ₀ xs vs σ₁ Hup Hups ih =>"
    if case_some in tactics:
        add("case_underscores", tactics.replace(case_some, "  case update_some _ x _ σ₀ _ _ _ Hup Hups ih =>", 1), "unused update_some binders -> _")
    case_x = "  case update_some _ x _ σ₀ _ _ _ Hup Hups ih =>"
    if case_x in tactics:
        add("case_underscores_x", tactics.replace(case_x, "  case update_some _ _ _ σ₀ _ _ _ Hup Hups ih =>", 1), "drop unused x binder too")
    refine_hst2 = "    refine ⟨rfl, Hst, ?_⟩\n    . apply UpdateStates.update_some"
    double_ctor = "    constructor\n    rfl\n    constructor\n    exact Hst\n    . apply UpdateStates.update_some"
    if refine_hst2 in tactics:
        add("double_ctor_hst", tactics.replace(refine_hst2, double_ctor, 1), "two constructors + rfl + exact Hst instead of refine")
    refine_hst_fill = "    refine ⟨rfl, Hst, ?_⟩\n    . refine UpdateStates.update_some"
    double_ctor_fill = "    constructor\n    rfl\n    constructor\n    exact Hst\n    . refine UpdateStates.update_some"
    if refine_hst_fill in tactics:
        add("double_ctor_hst", tactics.replace(refine_hst_fill, double_ctor_fill, 1), "two constructors + rfl + exact Hst instead of refine")
    apply_ih = "    . apply UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs')\n"
    ih_line = "      . exact (ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2"
    if apply_ih in tactics and ih_line in tactics:
        filled = tactics.replace(
            apply_ih,
            "    . refine UpdateStates.update_some (σ':=updatedStates σ₀ ks' vs') ?_ (ih Hinit (by simp_all [isDefined]) (by simp_all)).2.2\n",
            1,
        ).replace("\n" + ih_line, "", 1)
        add("fill_ih_arg", filled, "pass ih as the second argument of update_some")
    split_assump = (
        "          split at this <;> simp_all\n"
        "          exact updatedStateUpdate (InitStatesSomeMonotone (by assumption) Hst)"
    )
    if split_assump in tactics:
        add(
            "split_no_simp_all",
            tactics.replace(
                split_assump,
                "          split at this\n          exact updatedStateUpdate (InitStatesSomeMonotone (by assumption) Hst)",
                1,
            ),
            "drop <;> simp_all after split",
        )
        add(
            "split_simp_all_exact",
            tactics.replace(
                split_assump,
                "          split at this <;> simp_all <;> exact updatedStateUpdate (InitStatesSomeMonotone (by assumption) Hst)",
                1,
            ),
            "split <;> simp_all <;> exact on one chain",
        )
    simp_this = "simp [isDefined, Option.isSome] at this"
    if simp_this in tactics:
        add("simp_this_defined", tactics.replace(simp_this, "simp [isDefined] at this", 1), "drop Option.isSome at this")
        add("simp_this_option", tactics.replace(simp_this, "simp [Option.isSome] at this", 1), "drop isDefined at this")
        add("simp_this_bare", tactics.replace(simp_this, "simp at this", 1), "bare simp at this")
    by_assump = "InitStatesSomeMonotone (by assumption) Hst"
    if by_assump in tactics:
        add("monotone_this", tactics.replace(by_assump, "InitStatesSomeMonotone this Hst", 1), "by assumption -> this after split")
        add("monotone_star", tactics.replace(by_assump, "InitStatesSomeMonotone ‹_› Hst", 1), "by assumption -> ‹_›")
    hole = "(σ':=updatedStates σ₀ ks' vs') ?_ (ih"
    if hole in tactics:
        add("underscore_hole", tactics.replace(hole, "(σ':=updatedStates σ₀ ks' vs') _ (ih", 1), "refine hole ?_ -> _")
    if "    exact Hst\n" in tactics:
        add("assumption_hst", tactics.replace("    exact Hst\n", "    assumption\n", 1), "exact Hst -> assumption")
    simp_nd_list = "simp_all [isNotDefined, isDefined]"
    if simp_nd_list in tactics:
        add("simp_all_hnd", tactics.replace(simp_nd_list, "simp_all [Hnd]", 1), "simp_all [Hnd] instead of isNotDefined/isDefined")
        add("simp_all_hnd_def", tactics.replace(simp_nd_list, "simp_all [Hnd, isDefined]", 1), "simp_all [Hnd, isDefined]")
    if "          intros Hin\n" in tactics:
        add("hnd_no_intro", tactics.replace("          intros Hin\n", "", 1), "drop intros Hin")
    if "    constructor\n    rfl\n    constructor\n    exact Hst\n" in tactics:
        add(
            "and_intro_rfl_hst",
            tactics.replace(
                "    constructor\n    rfl\n    constructor\n    exact Hst\n",
                "    refine ⟨rfl, Hst, ?_⟩\n",
                1,
            ),
            "revert double ctor (sanity; likely longer)",
        )
    case_hnd_have = "    have Hnd := InitStatesNotDefined Hinit\n"
    hst_hnd = "UpdateStatesNotDefMonotone' Hnd Hups"
    if case_hnd_have in tactics and hst_hnd in tactics:
        add(
            "inline_hnd",
            tactics.replace(case_hnd_have, "", 1).replace(hst_hnd, "UpdateStatesNotDefMonotone' (InitStatesNotDefined Hinit) Hups", 1),
            "inline Hnd into Hst; drop have Hnd",
        )
    none_last_ctor = "    simp [InitStatesUpdated Hinit]\n    constructor"
    if none_last_ctor in tactics:
        add("none_update_none", tactics.replace(none_last_ctor, "    simp [InitStatesUpdated Hinit]\n    exact UpdateStates.update_none", 1), "last constructor -> exact UpdateStates.update_none")
        add("none_dot_update_none", tactics.replace(none_last_ctor, "    simp [InitStatesUpdated Hinit]\n    exact .update_none", 1), "last constructor -> exact .update_none")
    return rows
