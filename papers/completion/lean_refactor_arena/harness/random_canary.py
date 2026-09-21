#!/usr/bin/env python3
"""Randomize warmup canaries and analyze proofs for MCA refactoring.

Fits PCA/MCA on the frozen 15-problem warmup, samples ``k`` proofs with a
seeded RNG, lists residual holes (simp-at runs, have/rename_i, rw chains,
one-hole spans), asks TypeSafe which family/draft to try, and optionally
lakes a few randomized drops.

Original manuscripts are not rewritten. Lake is the oracle on ``--live``.
Not an Arena ranking. Not official Track 2. Never docker0.
"""
from __future__ import annotations

import argparse
import json
import random
import sys

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import draft_fanout as lra_fan  # noqa: E402
import mca_mask_replace as lra_mask  # noqa: E402
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import symbol_diffuse as lra_sym  # noqa: E402
import binder_use as lra_bind  # noqa: E402
import portable_rewrites as lra_port  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402

# ``CANARY_139`` is a read-only curated fixture; all generated evidence uses
# the configured runtime artifact root by default.
CANARY_139 = PAPER_ROOT / "evidence" / "canaries" / "cascade-best-139.lean"
OUT_DEFAULT = _jevops_path.LRA_CANARY_ROOT

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"

PROTOCOL = "LRA/v1"
PR_ID = "PR-9h"
DEFAULT_SEED = 20260917
DEFAULT_K = 3
MAX_LIVE_TOKENS = 700
# Hierarchical + confidence cookbooks (cascade_edits / docs.typesafe.ai).
CONFIDENT = 0.55
FIRE_T = 0.7
FIRE_T_RESIDUAL = 0.5  # AutoResearch: skip a residual skill before it hits lake twice
FIRE_T_LEAF = 0.45  # ident-shorten Noul was ~0.49 and still laked; skip earlier
BEAM_K = 3
EPSILON = 1e-9
UNCERTAIN = 0.60  # consistency cookbook: max-prob floor before acting
HIGH_STAKES = frozenset(
    {"Core.InitsUpdatesComm", "Cslib.CCS.bisimilarity_congr_choice"}
)
NEST_MAX_DEPTH = 3  # TypeSafe recursive skill-tree nests
INNER_MAX_STEPS = 8  # TypeSafe keep-looping steps per canary (shared with nests)
FAMILY_BLURB = {
    "dead_code": "Drop unused have/obtain/rename_i or simp-at-before-simp_all",
    "search_space": "Shrink intros/apply search; never delete a case arm",
    "loop_invariant": "Drop have-facts after induction",
    "strength_reduction": "Replace simp-at runs with simp_all",
    "algebraic_simplification": "Collapse rw/calc/ring/omega into simp or omega",
    "symbol_diffuse": "Closed Lean operator/phrase fill; keep induction/case",
    "pca_keep": "Do not edit; the current script is already locally minimal",
}
FAMILY_STRUCTURED = {
    "dead_code": {
        "what": "Unused rename_i/have whose binders do not appear later",
        "not_for": "Binders still used (trigger1, Hup, destructuring ⟨s2'⟩)",
        "examples": ["drop_unused_binders", "drop_dead_code_MCA_*"],
    },
    "search_space": {
        "what": "Shorter intro/exact/constructor that keeps every case arm",
        "not_for": "Deleting a case arm or applying constructor to a non-inductive goal",
        "examples": ["port_exact_hin_assumption", "port_ski_double_par"],
    },
    "loop_invariant": {
        "what": "Drop a have after induction that is not simp_all fuel",
        "not_for": "Prefix haves before induction (Hk/Hlen) or have ⟨a,b⟩",
        "examples": ["drop_loop_invariant_MCA_*"],
    },
    "strength_reduction": {
        "what": "simp at hyp immediately before simp_all",
        "not_for": "Rewriting rw/omega chains",
        "examples": ["collapse_simp_at"],
    },
    "algebraic_simplification": {
        "what": "Collapse consecutive rw [lemmas] or pack constructor/exact",
        "not_for": "Blind span masks or dropping binders",
        "examples": ["collapse_rw", "port_ski_double_par"],
    },
    "symbol_diffuse": {
        "what": "A phrase already in this script (constructor, intro, <;> simp_all)",
        "not_for": "Random token windows on Cslib/CallElim",
        "examples": ["inits_replay", "SYM_*_phrase_*"],
    },
    "pca_keep": {
        "what": "Leave the current lake-valid script unchanged",
        "not_for": "Any edit",
        "examples": ["keep"],
    },
}


def _tags(record: Mapping[str, Any]) -> list[Any]:
    from jevops.jev import list_field

    return list_field(record, "version_info")


def analyze_proof(
    record: Mapping[str, Any],
    *,
    tactics: Optional[str] = None,
    model: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops.outer import head_seq
    from jevops.pick import analysis_row
    from jevops.pick import hole_rows

    body = (tactics if tactics is not None else lra_fan.tactic_block(record)).strip("\n")
    counts = lra_pca.count_tactics(body)
    families = lra_pca.amenable_families(counts, model) if model else []
    mca_holes = lra_mask.find_holes(body)
    spans = {
        f"span_{span}": len(lra_sym.all_span_windows(body, span, stride=1))
        for span in lra_sym.ONE_HOLE_SPANS
    }
    phrases = [src for src, _dst in lra_sym.PHRASE_ALTS if src in body]
    cases = [span.label for span in lra_fan.case_spans(body)]
    holes = hole_rows(
        mca_holes,
        token_fn=lra_loop.token_count,
        used_fn=lambda start, end, original: lra_bind.binders_used_later(body, start, end, original),
        safe_fn=lambda start, end, original: lra_bind.safe_to_drop_span(body, start, end, original),
    )
    return analysis_row(
        record,
        n_tokens=lra_loop.token_count(body),
        counts=counts,
        families=families,
        holes=holes,
        extra={
            "n_tags": len(_tags(record)),
            "eligible_spans": spans,
            "catalog_phrases_present": phrases,
            "case_labels": head_seq(cases, 12),
            "n_cases": len(cases),
            "pca_keep": bool(counts.get("n_induction") or counts.get("n_cases")),
        },
    )


def random_drafts(
    tactics: str,
    rng: random.Random,
    *,
    n: int = 6,
    families: Sequence[Mapping[str, Any]] = (),
    counts: Optional[Mapping[str, float]] = None,
    name: str = "",
    memory: Optional[Mapping[str, Any]] = None,
    allow_families: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Seeded random MCA drops and one-hole closed fills. No LLM.

    Binder drops are gated: a ``rename_i`` / ``have`` is skipped when its
    names still appear later (the substOldPostSubset ``trigger1`` failure).
    """

    from jevops.tactics import collect_random_draft_extras, random_mca_drafts as _fn

    body = tactics.strip("\n")
    allow = set(allow_families) if allow_families else None
    design = _active_tactic_design(memory or {}) if memory is not None else None
    design_rows: list[tuple[str, str, dict[str, Any]]] = []
    if design and str(design.get("name") or "") == str(name or ""):
        strategy = str(design.get("strategy") or "").strip().lower().replace("-", "_")
        if strategy:
            try:
                from jevops.router_tuning import _strategy_body

                design_rows = [
                    (
                        f"outer_design_{kind}",
                        candidate,
                        {
                            "family": str(design.get("family") or "") or "search_space",
                            "generator": "outer_design_directive",
                            "compiler_probe": True,
                            "directive_action": str(design.get("action") or "mint_tactic"),
                            "hypothesis": str(design.get("hypothesis") or ""),
                        },
                    )
                    for kind, candidate, _origin in _strategy_body(strategy, body, rng)
                    if candidate and candidate != body
                ][:8]
            except Exception:
                design_rows = []

    def wanted(fam: str) -> bool:
        return allow is None or fam in allow

    # Always materialize the closed-vocabulary portfolio.  A recursive
    # TypeSafe branch can select ``loop_invariant`` or another family even
    # when an unrelated portable fold is the only remaining compiler probe;
    # those probes are tagged in ``collect_random_draft_extras`` and remain
    # visible to the bounded Lake queue.
    blocked = {
        key
        for key, _fn in lra_port.PIPELINE
        if memory is not None and lra_bind.is_blacklisted(memory, name, f"port_{key}")
    }
    if memory is not None:
        blocked |= lra_bind.failed_skill_stems(memory, name)
    portable_items = list(
        lra_port.portable_drafts(body, skip=blocked, memory=dict(memory or {}), name=name)
    )
    historical_rows: list[tuple[str, str, dict[str, Any]]] = []
    if memory is not None:
        try:
            from historical_seeds import seed_rows_for

            for index, seed in enumerate(seed_rows_for(memory, name)[:8]):
                seed_body = str(seed.get("body") or "").strip("\n")
                if not seed_body:
                    continue
                # ``port_`` is intentional: pin_prefix keeps historical
                # seeds in the bounded queue, while provenance says they are
                # Git teachers rather than current portable folds.
                historical_rows.append(
                    (
                        f"port_historical_seed_{index}",
                        seed_body,
                        {
                            "family": "historical_seed",
                            "compiler_probe": True,
                            "seed_provenance": str(seed.get("provenance") or "git_history"),
                            "seed_commit": str(seed.get("commit") or ""),
                            "seed_path": str(seed.get("path") or ""),
                            "claimed_tokens": seed.get("claimed_tokens"),
                            "actual_tokens": seed.get("actual_tokens"),
                            "body_digest": str(seed.get("body_digest") or ""),
                        },
                    )
                )
        except Exception:
            historical_rows = []
    early, late = collect_random_draft_extras(
        body,
        rng,
        wanted_fn=wanted,
        portable_items=portable_items,
        symbol_spans=list(lra_sym.ONE_HOLE_SPANS),
        prefer_fn=lra_sym.prefer_one_holes,
        phrase_alts=lra_sym.PHRASE_ALTS,
        operators=lra_sym.OPERATORS,
        closed_fn=lra_sym.closed_multihole,
        pca_drafts=lra_pca.guided_drafts(body, list(families) or [{"family": "dead_code"}], counts),
    )
    early = historical_rows + design_rows + early

    def _blacklist(mem: Mapping[str, Any], problem: str, kind: str, nxt: str = "") -> bool:
        return lra_bind.is_blacklisted(mem, problem, kind, tactics=nxt)

    result = list(
        _fn(
            tactics,
            rng,
            n=n,
            token_fn=lra_loop.token_count,
            allow_families=allow,
            name=name,
            memory=memory,
            safe_drop_fn=lra_bind.safe_to_drop_span,
            blacklist_fn=_blacklist,
            early_extras=early,
            late_extras=late,
        )
    )
    if name == "Core.InitsUpdatesComm":
        # This is a closed, three-pin Lake-verified benchmark kernel. Keep it
        # at the head of the candidate budget even when a nested family gate
        # asks for unrelated residuals; the oracle still decides acceptance.
        from jevops.inits import best_replay

        verified = best_replay(body)
        if verified != body and lra_loop.token_count(verified) < lra_loop.token_count(body):
            result = [
                {
                    "kind": "inits_best",
                    "tactics": verified,
                    "token_count": lra_loop.token_count(verified),
                    "family": "mca",
                    "generator": "verified_benchmark_kernel",
                    "llm": "off",
                },
                *[item for item in result if str(item.get("kind") or "") != "inits_best"],
            ]
            result = result[: max(1, int(n))]
    return result


from jevops.pick import draft_tree as kernel_draft_tree  # noqa: E402
from jevops.pick import geo_mean  # noqa: E402
from jevops.pick import leftover_sort_key  # noqa: E402  # re-export
from jevops.pick import sample_records  # noqa: E402


def draft_tree(drafts: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    from jevops.outer import overlay_attr

    blurbs = overlay_attr(FAMILY_BLURB, FAMILY_STRUCTURED, attr="what")
    return kernel_draft_tree(
        drafts,
        blurbs=blurbs,
        empty_tree={"pca_keep": {"keep": "No shorter draft"}},
    )


def _typesafe_provider_skip(
    exc: Exception, *, families: Optional[Sequence[str]] = None
) -> dict[str, Any]:
    """Turn a transient TypeSafe outage into a recorded, fail-closed skip.

    TypeSafe is a routing aid; it is never allowed to make the Lake benchmark
    disappear.  In particular, ``--llm off`` controls the outer router and
    does not imply that an already-configured TypeSafe endpoint is healthy.
    Keep the exception short and single-line so receipts remain safe to log.
    """

    from jevops.jev import skipped

    detail = " ".join(str(exc).split())[:240]
    return skipped(
        "typesafe_provider_error",
        error=f"{type(exc).__name__}: {detail}",
        families=set(families or FAMILY_BLURB),
        arena_score=None,
    )


def typesafe_pick(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    *,
    ledger: Optional[Any] = None,
    memory: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    from _optional_deps import load_typesafe

    typesafe_module, typesafe_reason = load_typesafe()
    if typesafe_module is None:
        from jevops.jev import skipped

        return skipped("typesafe_inference_missing", error=typesafe_reason)
    Choice = typesafe_module.Choice
    Noul = typesafe_module.Noul
    Score = typesafe_module.Score
    TypeSafeClient = typesafe_module.TypeSafeClient
    typesafe_configured = typesafe_module.typesafe_configured

    if not typesafe_configured():
        from jevops.jev import skipped

        return skipped("no_key")
    tree = draft_tree(drafts)
    from jevops.pick import family_criteria as _family_criteria

    family_criteria = _family_criteria(tree, structured=FAMILY_STRUCTURED, blurbs=FAMILY_BLURB)
    questions: dict[str, Any] = {
        "family": Choice(
            instructions={
                "question": "Which edit family is the best next step on this lake-valid Lean 4 proof?",
                "focus": "Classify the residual, not every tactic present. Do not write Lean.",
            },
            criteria=family_criteria,
        ),
        "likely_token_cut": Score(
            instructions={
                "question": "How large a token cut if the best family is applied?",
                "note": "Judge expected lake-valid shortening, not the raw string length.",
            },
            criteria=list(lra_fan.LIKELY_SHORTER_CRITERIA),
        ),
        "breaks_pca": Noul(
            instructions={
                "question": "Would the best family drop an induction or case arm?",
                "focus": "true means the edit is the wrong bet.",
            },
            criteria={
                "true": "Deletes induction/case structure",
                "false": "Keeps the PCA skeleton",
            },
        ),
        "will_fail_compile": Noul(
            instructions={
                "question": "Will the greedy leaf fail `lake` compile?",
                "focus": "true = P(wrong); escalate away from that leaf (SDE cascade).",
            },
            criteria={
                "true": {
                    "what": "Unknown identifier, type mismatch, unsolved goals, or dropped case",
                    "examples": ["sweep_rand spans", "port_dot_ctor_apply", "exact ih"],
                },
                "false": {
                    "what": "Used-binder-safe closed fold that previously laked",
                    "examples": ["drop_unused_binders", "collapse_simp_at", "port_intro_x_hin"],
                },
            },
        ),
    }
    from jevops.jev import expand_questions

    questions.update(
        expand_questions(
            [item for item in drafts if item.get("kind")],
            ctor=Noul,
            name_fn=lambda item: f"fail_{item.get('kind')}",
            instructions_fn=lambda item: {
                "question": f"Will draft `{item.get('kind')}` fail lake compile?",
                "inspect": f"`drafts` entry `{item.get('kind')}`",
                "focus": "true = P(wrong) for this field (SDE per-field battery).",
            },
            criteria={
                "true": "Likely unknown identifier, type mismatch, or unsolved goals",
                "false": "A binder-safe fold or a kernel that already laked on this problem",
            },
            limit=6,
        )
    )
    from jevops.pick import leaf_choice_questions
    from jevops.pick import pick_state

    questions.update(
        leaf_choice_questions(
            tree,
            ctor=Choice,
            focus="Prefer drop_unused_binders, collapse_simp_at, port_* over sweep_rand spans.",
        )
    )
    state = pick_state(
        record,
        analysis,
        drafts=drafts,
        memory=memory,
        extra={"goal": "Keep induction/case. Do not write Lean."},
    )
    from jevops.jev import choice_head, invoke_system_one, invoke_then_project, noul_attr, record_usage, unpack_response
    from jevops import pick as lra_pick
    from jevops.outer import head_seq

    def _project(_result: Any, wall_ms: float, choices: Any, nouls: Any, scores: Any, usage: Any) -> dict[str, Any]:
        _fam_ans, fam_probs, family_conf, fam_choice = choice_head(choices, "family")
        leaf_qs = lra_pick.leaf_qs_from_choices(tree, choices, family_conf=family_conf)
        cut = scores.get("likely_token_cut")
        return lra_pick.rank_from_answers(
            tree=tree,
            fam_probs=fam_probs,
            family_conf=family_conf,
            leaf_qs=leaf_qs,
            drafts=drafts,
            noul_fail=noul_attr(nouls, "will_fail_compile"),
            noul_pca=noul_attr(nouls, "breaks_pca"),
            per_leaf_fail=lra_pick.noul_map(
                nouls, [item.get("kind") for item in head_seq(drafts, 6)], prefix="fail_"
            ),
            failed_stems=lra_bind.failed_skill_stems(memory or {}, str(record.get("name") or "")),
            cut_score=getattr(cut, "score", None),
            usage=usage,
            wall_ms=wall_ms,
            greedy_fam_fallback=fam_choice,
            beam_k=BEAM_K,
            fire_t=FIRE_T,
            fire_t_leaf=FIRE_T_LEAF,
            confident=CONFIDENT,
            uncertain=UNCERTAIN,
            epsilon=EPSILON,
        )

    try:
        return invoke_then_project(
            invoke_fn=lambda: invoke_system_one(TypeSafeClient(timeout=45.0), state, questions),
            record_fn=lambda usage, model: record_usage(ledger, usage, model=model),
            unpack_fn=unpack_response,
            model=lra_t1.JEV_MODEL_ID,
            project_fn=_project,
        )
    except Exception as exc:
        return _typesafe_provider_skip(exc, families=tuple(tree))


# Residual name -> pipeline skill to skip when Noul says cutting it is unsafe.
RESIDUAL_TO_SKILL: dict[str, tuple[str, ...]] = {
    "intros_x_Hin": ("unused_intros",),
    "intro_then_simp_all": ("drop_intro_before_simp_all",),
    "try_simp_all": ("drop_try_simp_all",),
    "apply_semi_assumption": ("semi_assumption",),
    "use_then_exact": ("use_exact", "use_exact_reuse"),
    "have": (),  # drop_unused_binders is a named skill, not a port_ fold
    "ctor_lone": ("ctor_pair_exacts",),
    "grind": ("repeat_par_grind", "grind_only_to_grind"),
    "repeated_simp_list": ("hoist_repeated_simp",),
    "inner_simp_subset": ("redundant_inner_simp",),
    "trailing_tuple_comma": ("trailing_tuple_comma",),
}


def typesafe_autoresearch(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    tactics: str = "",
    ledger: Optional[Any] = None,
    memory: Optional[Mapping[str, Any]] = None,
    allow_families: Optional[set[str]] = None,
    allow_skills: Optional[set[str]] = None,
    tree_node: str = "root",
) -> dict[str, Any]:
    """Entry point: AutoResearch features (Score+Noul on residuals) then route skills.

    Cookbook: numeric features from TypeSafe answers drive what code generates and
    composes. Jev does not write Lean.
    """

    routed = typesafe_intent(
        record,
        analysis,
        tactics=tactics,
        ledger=ledger,
        memory=memory,
        extra_residual_qs=True,
        allow_families=allow_families,
        allow_skills=allow_skills,
        tree_node=tree_node,
    )
    return routed


from jevops.walk import bias_compose_no_drafts  # noqa: E402


def typesafe_intent(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    tactics: str = "",
    ledger: Optional[Any] = None,
    memory: Optional[Mapping[str, Any]] = None,
    extra_residual_qs: bool = True,
    allow_families: Optional[set[str]] = None,
    allow_skills: Optional[set[str]] = None,
    tree_node: str = "root",
) -> dict[str, Any]:
    """Intent routing + AutoResearch residual features."""

    from jevops.memory import named_success_kinds
    from jevops.memory import port_wins
    from jevops.pick import filter_catalog
    from jevops.walk import COMPOSE_CRITERIA
    from jevops.walk import intent_window

    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    from _optional_deps import load_typesafe

    typesafe_module, typesafe_reason = load_typesafe()
    if typesafe_module is None:
        from jevops.jev import skipped

        return skipped(
            "typesafe_inference_missing",
            error=typesafe_reason,
            families=set(FAMILY_BLURB),
        )
    Choice = typesafe_module.Choice
    Noul = typesafe_module.Noul
    Score = typesafe_module.Score
    TypeSafeClient = typesafe_module.TypeSafeClient
    typesafe_configured = typesafe_module.typesafe_configured

    if not typesafe_configured():
        from jevops.jev import skipped

        return skipped("no_key", families=set(FAMILY_BLURB))
    from jevops.jev import intent_state
    from jevops.outer import head_chars
    from jevops.pick import family_criteria as _family_criteria
    from jevops.pick import present_families

    present = present_families(analysis)
    criteria = _family_criteria(present, structured=FAMILY_STRUCTURED, require_structured=True)
    state = intent_state(
        record,
        analysis,
        residuals=lra_port.analyze_residuals(tactics) if tactics else {},
        memory_view={"success_kinds": named_success_kinds(memory or {}, str(record.get("name") or ""))},
        window=intent_window(memory),
        extra={
            "head": head_chars(analysis.get("case_labels") or [], 200),
            "tree_node": tree_node,
            "allow_families": sorted(allow_families or []),
            "prior_research": lra_bind.prior_research(memory or {}, str(record.get("name") or "")),
            "proposed_skill": lra_bind.propose_skill_from_research(
                memory or {}, str(record.get("name") or "")
            ),
            "memory_wins": port_wins(memory),
        },
    )
    skills = (
        lra_port.available_skills(tactics, memory=dict(memory or {}), name=str(record.get("name") or ""))
        if tactics
        else {"keep": "No tactics"}
    )
    tree = lra_port.decision_tree(
        tactics, memory=dict(memory or {}), name=str(record.get("name") or "")
    ) if tactics else {}
    name = str(record.get("name") or "")
    skills, tree = filter_catalog(
        skills,
        tree,
        allow_skills=allow_skills,
        allow_families=allow_families,
        is_blocked=(lambda kind: lra_bind.is_blacklisted(memory, name, kind)) if memory is not None else None,
    )
    questions: dict[str, Any] = {
            "intent": Choice(
                instructions={
                    "question": "Which tactic family should the next denoise step generate drafts for?",
                    "focus": "Route to one handler. pca_keep means skip lake. Do not write Lean.",
                },
                criteria=criteria,
            ),
            "complexity": Score(
                instructions="How hard is a safe shorter fold on this script?",
                criteria=[
                    "One-line portable fold (intro/assumption/simp_at)",
                    "A few local MCA drops",
                    "No remaining lake-valid cut",
                ],
            ),
            "already_minimal": Noul(
                instructions={
                    "question": "Is this script already locally minimal (no lake-valid shorter fold)?",
                    "focus": "true = skip lake this round.",
                },
                criteria={
                    "true": "Every remaining edit drops a used binder or breaks a case arm",
                    "false": "A closed fold such as unused intros or exact→assumption remains",
                },
            ),
            "compose": Choice(
                instructions={
                    "question": "Apply one skill, the pipeline, or nest a TypeSafe loop on a child of the skill decision tree?",
                    "focus": "nest opens a recursive inner loop on one family/skill. Do not write Lean.",
                },
                criteria=dict(COMPOSE_CRITERIA),
            ),
            "skill": Choice(
                instructions={
                    "question": "Which named kernel should code invoke next (skill suggestion)?",
                    "focus": "keep if none is lake-safe. Do not write Lean.",
                },
                criteria=skills,
            ),
        }
    import typesafe_tools as _lra_tools_tree
    from jevops.walk import nest_criteria as _nest_criteria

    nest_criteria = _nest_criteria(
        tree,
        tools=_lra_tools_tree.TOOL_CRITERIA,
        subloops=_lra_tools_tree.SUBLOOPS,
    )
    if extra_residual_qs and nest_criteria:
        questions["nest_child"] = Choice(
            instructions={
                "question": "If compose is nest/spawn, which child of the skill decision tree or named subloop should run?",
                "focus": "A family, named skill, or registered subloop. Do not write Lean.",
            },
            criteria=nest_criteria,
        )
    import typesafe_tools as lra_tools

    if extra_residual_qs:
        questions["tool_name"] = Choice(
            instructions={
                "question": "If compose is analyze, which static-analysis tool should TypeSafe run?",
                "focus": "Navigate skills; do not write Lean; do not call docker0.",
            },
            criteria=lra_tools.TOOL_CRITERIA,
        )
    residuals = dict(state.get("residuals") or {})
    from jevops.jev import expand_questions

    if extra_residual_qs:
        questions.update(
            expand_questions(
                list(residuals.items()),
                ctor=Noul,
                name_fn=lambda kv: f"unsafe_{kv[0]}",
                instructions_fn=lambda kv: {
                    "question": (
                        f"Is cutting residual `{kv[0]}` (count={kv[1]}) lake-unsafe "
                        "on this script?"
                    ),
                    "focus": "true = P(wrong to cut). AutoResearch presence feature.",
                },
                criteria={
                    "true": "The residual is required (used binder, extra goals, motive cast, Join witness)",
                    "false": "A closed fold of this residual has laked on this or a similar proof",
                },
                limit=6,
            )
        )
        questions.update(
            expand_questions(
                list(residuals.items()),
                ctor=Score,
                name_fn=lambda kv: f"help_{kv[0]}",
                instructions_fn=lambda kv: f"How much would a *safe* cut of `{kv[0]}` help token count?",
                criteria=[
                    "No safe cut",
                    "A few tokens",
                    "A clear local shortening",
                ],
                limit=6,
            )
        )
    questions.update(
        expand_questions(
            list(skills),
            ctor=Noul,
            name_fn=lambda sk: f"fail_skill_{sk}",
            instructions_fn=lambda sk: {
                "question": f"Will skill `{sk}` fail lake compile?",
                "focus": "true = P(wrong). Do not invoke a fired skill.",
            },
            criteria={
                "true": "Type mismatch, unknown identifier, or unsolved goals",
                "false": "A binder-safe fold that already laked on this or a similar proof",
            },
            limit=6,
            skip=("keep",),
        )
    )
    from jevops.jev import invoke_system_one, invoke_then_project, record_usage, unpack_response
    from jevops.pick import intent_from_answers

    try:
        return invoke_then_project(
            invoke_fn=lambda: invoke_system_one(TypeSafeClient(timeout=45.0), state, questions),
            record_fn=lambda usage, model: record_usage(ledger, usage, model=model),
            unpack_fn=unpack_response,
            model=lra_t1.JEV_MODEL_ID,
            project_fn=lambda _result, wall_ms, choices, nouls, scores, _usage: intent_from_answers(
                choices=choices,
                scores=scores,
                nouls=nouls,
                skills=skills,
                tree=tree,
                residuals=residuals,
                residual_to_skill=RESIDUAL_TO_SKILL,
                fire_t_residual=FIRE_T_RESIDUAL,
                fire_t=FIRE_T,
                fire_t_leaf=FIRE_T_LEAF,
                confident=CONFIDENT,
                uncertain=UNCERTAIN,
                high_stakes=record.get("name") in HIGH_STAKES,
                tree_node=tree_node,
                wall_ms=wall_ms,
                memory=memory,
                name=str(record.get("name") or ""),
                criteria=criteria,
            ),
        )
    except Exception as exc:
        return _typesafe_provider_skip(exc, families=tuple(FAMILY_BLURB))


def self_check() -> dict[str, Any]:
    _raw, digest, records = lra_splice.load_warmup_records()
    rows = [lra_pca.feature_row(item) for item in records]
    model = lra_pca.fit_pca_mca(rows)
    sampled = sample_records(records, k=2, seed=1)
    analyses = [analyze_proof(item, model=model) for item in sampled]
    drafts = random_drafts(
        lra_fan.tactic_block(sampled[0]),
        random.Random(1),
        n=4,
        families=analyses[0].get("families") or [],
        counts=analyses[0].get("counts"),
    )
    return {
        "ok": (
            digest == lra_splice.FROZEN_WARMUP_SHA256
            and len(records) == lra_splice.WARMUP_N
            and len(sampled) == 2
            and sample_records(records, k=2, seed=1)[0].get("name") == sampled[0].get("name")
            and all(int(item["n_tokens"]) > 0 for item in analyses)
            and all(isinstance(item.get("families"), list) for item in analyses)
            and abs(geo_mean([0.81, 0.81]) - 0.81) < 1e-9
        ),
        "n_records": len(records),
        "warmup_jsonl_sha256": digest,
        "sample_names": [item.get("name") for item in sampled],
        "n_random_drafts": len(drafts),
        "called_docker0": False,
        "arena_score": None,
        "official_track2": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--lake-top", type=int, default=3)
    parser.add_argument("--drafts", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=1, help="denoise rounds per canary (accept shorter lake-ok, remask)")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--include-inits", action="store_true", help="force Core.InitsUpdatesComm into the sample")
    parser.add_argument("--init-139", action="store_true", help="analyze the 139-token InitsUpdatesComm cut as extra row")
    parser.add_argument(
        "--all-small",
        action="store_true",
        help=f"use every warmup proof with ≤{MAX_LIVE_TOKENS} tokens instead of a random k",
    )
    parser.add_argument(
        "--from-best",
        action="store_true",
        help="start each canary from its shortest random-best-*.lean if present",
    )
    parser.add_argument(
        "--seed-history",
        dest="seed_history",
        action="store_true",
        default=True,
        help="use pinned lift_coding Git proof bodies as untrusted teacher proposals",
    )
    parser.add_argument(
        "--no-seed-history",
        dest="seed_history",
        action="store_false",
        help="disable read-only historical Git teacher seeding",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="write evidence files but do not print the full payload",
    )
    parser.add_argument(
        "--nest-depth",
        type=int,
        default=NEST_MAX_DEPTH,
        help="max TypeSafe recursive skill-tree nest depth",
    )
    args = parser.parse_args(argv)
    if args.self_check or not args.live:
        from jevops.outer import print_ok

        payload = self_check()
        code = print_ok(payload)
        if args.self_check and not args.live:
            return code
        if not args.live:
            return code

    payload = run_live(args)
    if not getattr(args, "quiet", False):
        from jevops.outer import print_json

        print_json(payload, default=str)
    return 0


def rank_live_records(
    records: Sequence[Mapping[str, Any]],
    *,
    out: Path,
    from_best: bool,
    memory: Optional[Mapping[str, Any]] = None,
    warmup: Optional[Mapping[str, int]] = None,
    keep: Optional[Mapping[str, int]] = None,
) -> list[Mapping[str, Any]]:
    """Leftover un-blacklisted drafts first, then remaining_cut (warmup - keep)."""

    import typesafe_inner as lra_inner

    mem = dict(memory or {})
    warm = dict(warmup or {})
    kept = dict(keep or {})
    if not warm:
        try:
            import board_graph as lra_board

            warm = lra_board.warmup_token_map()
        except Exception:
            warm = {}
    if not kept:
        try:
            import skill_improve_loop as lra_sk

            kept = lra_sk.keep_best_board(out)
        except Exception:
            kept = {}
    from jevops.pick import filter_unsafe_drafts
    from jevops.pick import rank_leftover

    def _drafts(rec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        name = str(rec.get("name") or "")
        body = lra_inner.starting_tactics(rec, out=out, from_best=from_best)
        prior = lra_bind.prior_research(mem, name)
        return filter_unsafe_drafts(
            lra_port.portable_drafts(body, memory=mem, name=name),
            is_blocked=lambda kind: lra_bind.is_blacklisted(mem, name, kind),
            unsafe=dict(prior.get("unsafe") or {}),
            residual_map=lra_port.SKILL_RESIDUAL,
            fire_t=FIRE_T_RESIDUAL,
            revalidate_portable=(
                (mem.get("nca") or {}).get("portable_probe_revision")
                == getattr(lra_port, "PORTABLE_PROBE_REVISION", "")
            ),
        )

    def _rf(drafts: list[Mapping[str, Any]], rec: Mapping[str, Any], cut: int) -> float:
        name = str(rec.get("name") or "")
        import nca_rankers as lra_rank

        return float(lra_rank.score_record(drafts, memory=mem, name=name, remaining_cut=cut) or 0.0)

    return rank_leftover(
        records,
        drafts_fn=_drafts,
        rf_fn=_rf,
        memory=mem,
        warmup=warm,
        keep=kept,
    )


def _active_tactic_design(memory: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    row = (memory.get("nca") or {}).get("active_tactic_design")
    if not isinstance(row, Mapping):
        return None
    if str(row.get("status") or "pending") not in {"pending", "retry"}:
        return None
    name = str(row.get("name") or "").strip()
    strategy = str(row.get("strategy") or "closed_edits").strip()
    if not name or not strategy:
        return None
    return dict(row)


def _run_tactic_design(
    record: Mapping[str, Any],
    *,
    body: str,
    directive: Mapping[str, Any],
    memory: dict[str, Any],
    out: Path,
    timeout: float,
) -> dict[str, Any]:
    """Execute one outer-minted design request through the real Lake gate.

    The outer model supplies only a theorem/family/strategy directive. The
    inner router sees the complete theorem and tactic analysis, proposes
    bounded bodies, and the bridge compiles every proposal before a shorter
    body or blacklist repair is recorded.
    """

    import autoencoder_bridge as lra_ae
    from jevops.router_tuning import RouterTuningConfig

    name = str(record.get("name") or "")
    before = int(lra_loop.token_count(body))
    hint = {
        key: str(directive.get(key) or "")
        for key in (
            "action",
            "name",
            "family",
            "strategy",
            "repair_stem",
            "focus",
            "hypothesis",
            "constraints",
            "evaluation",
        )
        if directive.get(key)
    }
    repair_stem = str(directive.get("repair_stem") or "").strip()
    repair_seeds: list[str] = []
    if repair_stem:
        wanted = repair_stem if repair_stem.startswith("port_") else f"port_{repair_stem}"
        try:
            # Reopen only this one old fold for a new compiler probe.  The
            # current memory is intentionally not passed here: its blacklist
            # is the object being repaired, not proof that the implementation
            # remains invalid after a code revision.
            repair_seeds = [
                str(row.get("tactics") or "")
                for row in lra_port.portable_drafts(body, memory={}, name=name)
                if str(row.get("kind") or "") == wanted and row.get("tactics")
            ][:2]
        except Exception:
            repair_seeds = []
    historical_seeds: list[dict[str, Any]] = []
    try:
        from historical_seeds import seed_rows_for

        historical_seeds = seed_rows_for(memory, name)[:8]
    except Exception:
        historical_seeds = []
    config = RouterTuningConfig(
        rounds=2,
        max_router_candidates=8,
        max_candidate_pool=32,
        n_variations=4,
        strategy_cap=6,
        design_hint=hint,
        train=True,
    )
    try:
        result = lra_ae.run_record(
            record,
            memory=memory,
            config=config,
            seed_candidates=[
                {"body": body, "provenance": "current_run", "source": "current_run"},
                *historical_seeds,
                *repair_seeds,
            ],
            compile_timeout=float(timeout),
            state_root=DEFAULT_STATE,
            network="allow",
        )
    except Exception as exc:
        result = {
            "ok": False,
            "admission": "design_exception",
            "error": type(exc).__name__,
            "error_detail": str(exc)[:240],
            "best_body_tokens": before,
            "source_body_tokens": before,
            "history": [],
        }
    best_source = result.get("best_source")
    best_body = lra_ae._candidate_tactics(record, best_source) if isinstance(best_source, str) else None
    after = int(lra_loop.token_count(best_body)) if best_body is not None else before
    history = list(result.get("history") or [])
    candidate_count = sum(int(round_row.get("candidate_count") or 0) for round_row in history)
    lake_verified_count = sum(int(round_row.get("verified_count") or 0) for round_row in history)
    verified_designs = sum(
        1
        for round_row in history
        for candidate in round_row.get("candidates") or ()
        if isinstance(candidate, Mapping)
        and candidate.get("lake_ok")
        and str(candidate.get("origin") or "") not in {"current", "reference", "verified_seed"}
    )
    verified_repairs = sum(
        1
        for round_row in history
        for candidate in round_row.get("candidates") or ()
        if isinstance(candidate, Mapping)
        and candidate.get("lake_ok")
        and str(candidate.get("origin") or "") == "verified_seed"
        and str(candidate.get("kind") or "") == "teacher_refactor"
        and repair_seeds
    )
    accepted = bool(result.get("ok") and best_body is not None and after < before)
    best_path = None
    if accepted:
        from jevops.outer import write_best_body

        best_path = write_best_body(out, name, after, best_body)
        try:
            import board_graph as lra_board

            lra_board.credit_theorem(memory, name, theorem_ok=True, tokens=after)
        except Exception:
            pass
    repair = None
    # A generic newly generated design is not evidence that the blacklisted
    # stem itself was repaired.  Only the exact fresh teacher/refactor seed
    # can reopen a repair target; otherwise the negative result remains active.
    can_reopen_repair = bool(
        repair_stem
        and (
            (str(directive.get("action") or "") == "repair_tactic" and verified_repairs)
            or (
                str(directive.get("action") or "") != "repair_tactic"
                and verified_designs
            )
        )
    )
    if can_reopen_repair:
        repair = lra_bind.repair_blacklist(
            memory,
            name=name,
            stem=repair_stem,
            receipt={
                "verified_designs": verified_designs,
                "verified_repairs": verified_repairs,
                "best_tokens": after,
            },
        )
    receipt = {
        "ok": bool(result.get("ok")),
        "action": str(directive.get("action") or "mint_tactic"),
        "accepted": accepted,
        "name": name,
        "strategy": str(directive.get("strategy") or ""),
        "family": str(directive.get("family") or ""),
        "repair_stem": repair_stem,
        "hypothesis": str(directive.get("hypothesis") or ""),
        "constraints": str(directive.get("constraints") or ""),
        "evaluation": str(directive.get("evaluation") or ""),
        "before_tokens": before,
        "after_tokens": after,
        "verified_designs": verified_designs,
        "verified_repairs": verified_repairs,
        "repair_seed_count": len(repair_seeds),
        "repair_seed_tokens": [lra_loop.token_count(seed) for seed in repair_seeds],
        "historical_seed_count": len(historical_seeds),
        "historical_seed_claims": [
            {
                "path": seed.get("path"),
                "commit": seed.get("commit"),
                "claimed_tokens": seed.get("claimed_tokens"),
                "body_digest": seed.get("body_digest"),
            }
            for seed in historical_seeds
        ],
        "candidate_count": candidate_count,
        "lake_verified_count": lake_verified_count,
        "router_rounds": [
            {
                "strategies": list((round_row.get("router") or {}).get("strategies") or []),
                "focus": (round_row.get("router") or {}).get("focus"),
                "route_attestation": (round_row.get("router") or {}).get("route_attestation"),
            }
            for round_row in history
        ],
        "best_body_tokens": result.get("best_body_tokens"),
        "source_body_tokens": result.get("source_body_tokens"),
        "model_body_tokens_after": result.get("model_body_tokens_after"),
        "model_loss_after": result.get("model_loss_after"),
        "reward_hacking_checks": {
            "statement_prefix_bound": bool(
                (result.get("benchmark") or {}).get("statement_prefix_bound")
            ),
            "official_scores_null": (result.get("benchmark") or {}).get("arena_score") is None
            and (result.get("benchmark") or {}).get("official_score") is None,
            "model_loss_separate": all(
                "candidate_target_loss" in (round_row.get("training") or {})
                and "loss" in (round_row.get("training") or {})
                for round_row in history
                if (round_row.get("training") or {}).get("trained")
            ),
            "hypothesis_assessed": (
                str(directive.get("action") or "") != "hypothesis_refactor"
                or bool(result)
            ),
        },
        "best_path": str(best_path) if best_path else None,
        "repair": repair,
        "error": result.get("error"),
        "error_detail": result.get("error_detail"),
    }
    nca = memory.setdefault("nca", {})
    nca["last_tactic_design"] = dict(receipt)
    history_store = nca.setdefault("tactic_design_history", [])
    if not isinstance(history_store, list):
        history_store = []
        nca["tactic_design_history"] = history_store
    history_store.append(dict(receipt))
    nca["tactic_design_history"] = history_store[-12:]
    nca["active_tactic_design"] = None
    if str(directive.get("action") or "") == "hypothesis_refactor":
        nca["last_hypothesis_refactor"] = dict(receipt)
        hypothesis_history = nca.setdefault("hypothesis_history", [])
        if not isinstance(hypothesis_history, list):
            hypothesis_history = []
            nca["hypothesis_history"] = hypothesis_history
        hypothesis_history.append(dict(receipt))
        nca["hypothesis_history"] = hypothesis_history[-12:]
        nca["active_hypothesis_refactor"] = None
        hypothesis = str(directive.get("hypothesis") or "")
        hypothesis_queue = nca.get("hypothesis_queue")
        if not isinstance(hypothesis_queue, list):
            hypothesis_queue = []
        nca["hypothesis_queue"] = [
            row
            for row in hypothesis_queue
            if not (
                isinstance(row, Mapping)
                and str(row.get("name") or "") == name
                and str(row.get("hypothesis") or "") == hypothesis
            )
        ]
    queue = nca.get("tactic_design_queue")
    if not isinstance(queue, list):
        queue = []
    nca["tactic_design_queue"] = [
        row
        for row in queue
        if not (
            isinstance(row, Mapping)
            and str(row.get("name") or "") == name
            and str(row.get("strategy") or "") == str(directive.get("strategy") or "")
        )
    ]
    return receipt


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    """AutoResearch entry + lake on sampled canaries. Writes evidence; returns payload."""

    _raw, digest, records = lra_splice.load_warmup_records()
    rows = [lra_pca.feature_row(item) for item in records]
    model = lra_pca.fit_pca_mca(rows)
    from jevops.pick import ensure_named
    from jevops.pick import filter_by_tokens

    landscape = [analyze_proof(item, model=model) for item in records]
    if args.all_small:
        sampled = filter_by_tokens(records, landscape, cap=MAX_LIVE_TOKENS)
    else:
        sampled = sample_records(records, k=max(1, int(args.k)), seed=int(args.seed))
    if args.include_inits:
        sampled = ensure_named(sampled, records, name="Core.InitsUpdatesComm", k=max(1, int(args.k)))
    supplied_memory = getattr(args, "memory", None)
    memory = supplied_memory if isinstance(supplied_memory, dict) else lra_bind.load_memory()
    # A live process opts into fresh compiler probes after fold changes.  Unit
    # fixtures and imported historical memories without this marker continue
    # to exercise the conservative stale-prior filtering path.
    memory.setdefault("nca", {})["portable_probe_revision"] = getattr(
        lra_port, "PORTABLE_PROBE_REVISION", ""
    )
    seed_history = bool(getattr(args, "seed_history", True))
    historical_catalog: dict[str, list[dict[str, Any]]] = {}
    if seed_history:
        try:
            from historical_seeds import catalog_manifest, load_historical_catalog

            historical_catalog = load_historical_catalog(
                records,
                token_fn=lra_loop.token_count,
            )
            nca_memory = memory.setdefault("nca", {})
            nca_memory["historical_seed_candidates"] = historical_catalog
            nca_memory["historical_seed_manifest"] = catalog_manifest(historical_catalog)
            nca_memory["historical_seed_commit"] = next(
                (
                    str(row.get("commit") or "")
                    for rows_for_name in historical_catalog.values()
                    for row in rows_for_name
                    if row.get("commit")
                ),
                "",
            )
        except Exception as exc:
            memory.setdefault("nca", {})["historical_seed_error"] = type(exc).__name__
    from jevops.walk import reset_pass_flags
    import typesafe_inner as lra_inner

    reset_pass_flags(memory)
    directive = _active_tactic_design(memory)
    if directive:
        target = str(directive.get("name") or "")
        target_record = next((item for item in records if str(item.get("name") or "") == target), None)
        if target_record is not None:
            sampled = [target_record] + [item for item in sampled if item is not target_record]
        else:
            nca = memory.setdefault("nca", {})
            nca["active_tactic_design"] = None
            nca["active_hypothesis_refactor"] = None
    design_receipt: Optional[dict[str, Any]] = None
    if directive and target_record is not None:
        target_body = lra_inner.starting_tactics(
            target_record,
            out=args.out,
            from_best=bool(getattr(args, "from_best", False)),
        )
        design_receipt = _run_tactic_design(
            target_record,
            body=target_body,
            directive=directive,
            memory=memory,
            out=args.out,
            timeout=float(getattr(args, "timeout", 180.0) or 180.0),
        )
    lra_bind.save_memory(memory)
    sampled = rank_live_records(
        sampled,
        out=args.out,
        from_best=bool(getattr(args, "from_best", False)),
        memory=memory,
    )

    n_rounds = max(1, int(args.rounds))
    ledger = lra_t1.ProblemLedger(
        name="warmup#random-canary",
        max_jev_calls=max(8, len(sampled) * max(n_rounds, INNER_MAX_STEPS) * 3 + 2),
        max_mistral_calls=0,
    )
    rng = random.Random(int(args.seed))
    import typesafe_nca as lra_nca_live
    import board_graph as lra_board_live
    import skill_improve_loop as lra_sk_board
    from jevops.outer import memory_counts as _memory_counts
    from jevops.outer import seed_runtime

    seed_runtime(
        memory,
        seed_fn=lra_board_live.seed_nca_from_board,
        overlay_fn=lra_board_live.overlay_live_board,
        keepbest_fn=lambda mem: lra_board_live.seed_keepbest_theorems(
            mem, lra_sk_board.keep_best_board(args.out), warmup=lra_board_live.warmup_token_map()
        ),
    )

    extra_139 = None
    if args.init_139 and CANARY_139.is_file():
        from jevops.outer import lookup_named, read_text

        inits = lookup_named(
            records,
            "Core.InitsUpdatesComm",
            error_cls=RuntimeError,
            miss="unknown warm-up problem: Core.InitsUpdatesComm",
        )
        extra_139 = analyze_proof(
            inits,
            tactics=read_text(CANARY_139).strip("\n"),
            model=model,
        )
        extra_139["cut"] = "cascade-best-139"

    from jevops.walk import run_sampled

    canaries, lake_rows = run_sampled(
        sampled,
        memory=memory,
        halt_fn=lra_nca_live.should_halt,
        run_fn=lambda rec: lra_inner.run_nested_canary(
            rec,
            args=args,
            memory=memory,
            ledger=ledger,
            rng=rng,
            model=model,
        ),
    )

    args.out.mkdir(parents=True, exist_ok=True)
    mem_path = lra_bind.save_memory(memory)
    gaps = lra_bind.skill_gap_report(memory)
    from jevops.nca import live_status
    from jevops.outer import safe_call
    from jevops.outer import write_json_pair

    nca_status = safe_call(live_status, memory, default={}) or {}
    from jevops.jev import canary_live_payload
    from jevops.outer import write_json

    write_json(
        args.out / "skill-analysis.json",
        {"schema": "lra-skill-analysis/v1", "gaps": gaps, "nca_status": nca_status},
    )
    payload = canary_live_payload(
        digest=digest,
        seed=int(args.seed),
        k=int(args.k),
        n_records=len(records),
        landscape=landscape,
        model=model,
        extra_139=extra_139,
        canaries=canaries,
        lake=lake_rows,
        gaps=gaps,
        mem_path=mem_path,
        memory=_memory_counts(memory),
        nca_status=nca_status,
        ledger=ledger,
    )
    inner_analysis = [
        {
            "name": (row.get("analysis") or {}).get("name"),
            "tokens": (row.get("analysis") or {}).get("n_tokens"),
            "families": [item.get("family") for item in (row.get("analysis") or {}).get("families") or ()],
            "n_mca_holes": (row.get("analysis") or {}).get("n_mca_holes"),
            "n_drafts": row.get("n_drafts"),
            "n_steps": row.get("n_steps"),
            "lake_rows": len(row.get("lake") or ()),
        }
        for row in canaries
    ]
    memory.setdefault("nca", {})["inner_analysis"] = inner_analysis[:12]
    if design_receipt is not None:
        if str(design_receipt.get("action") or "") == "hypothesis_refactor":
            payload["hypothesis_refactor"] = design_receipt
        else:
            payload["tactic_design"] = design_receipt
    payload["inner_analysis_summary"] = inner_analysis[:12]
    payload["historical_fixture_comparison"] = lra_sk_board.historical_fixture_comparison(
        lra_sk_board.keep_best_board(args.out)
    )
    payload["historical_seed_manifest"] = (
        memory.get("nca", {}).get("historical_seed_manifest") or {}
    )
    payload["historical_seed_enabled"] = seed_history
    payload["historical_seeded_theorems"] = sorted(historical_catalog)
    lra_bind.save_memory(memory)
    write_json_pair(args.out, payload, prefix="random-canary", latest="random-canary-latest.json")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
