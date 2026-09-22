#!/usr/bin/env python3
"""TypeSafe / fan-out question catalogs. Jev does not write Lean.

Consumers inject Choice/Noul/Score constructors. Lake stays the oracle.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

LIKELY_SHORTER_CRITERIA = (
    "longer or same",
    "modest cut around 10 percent",
    "large cut of 30 percent or more",
)
ELAB_RISK_CRITERIA = (
    "elab likely better or same",
    "elab unclear",
    "elab likely worse",
)
LIKELY_SHORTER_LEGEND = {index: label for index, label in enumerate(LIKELY_SHORTER_CRITERIA)}
ELAB_RISK_LEGEND = {index: label for index, label in enumerate(ELAB_RISK_CRITERIA)}

REWRITE_CRITERIA: dict[str, Any] = {
    "native_hammer": {
        "what": "Goal looks like rfl/decide/omega/simp_all/assumption",
        "not_for": "Long calc, domain-specific lemmas, or large induction",
    },
    "simp_set": {"what": "Unfolding + rewrite lemmas should close or shrink it"},
    "aesop": {"what": "Aesop/auto would likely close"},
    "omega_decide": {"what": "Linear arithmetic or decidable predicates"},
    "calc": {"what": "Keep calc/conv structure; drop noise"},
    "have_chain": {"what": "Merge redundant have/show steps"},
    "custom": {"what": "Needs a model-written tactic script"},
}

ROUTE_QUESTION_SPEC: dict[str, dict[str, Any]] = {
    "rewrite_family": {
        "type": "choice",
        "instructions": "Which rewrite family should code try first on `reference_proof`?",
        "criteria": REWRITE_CRITERIA,
    },
    "hammer_before_llm": {
        "type": "noul",
        "instructions": (
            "Would Lean built-in tactics (rfl, decide, omega, simp_all, aesop if imported) "
            "plausibly close `statement` without a custom script?"
        ),
    },
    "reference_already_tight": {
        "type": "noul",
        "instructions": "Is `reference_proof` already compact relative to `statement`?",
    },
    "likely_shorter": {
        "type": "score",
        "instructions": "How large a source-token cut is plausible versus `problem.proof_length`?",
        "criteria": list(LIKELY_SHORTER_CRITERIA),
    },
    "elab_risk_if_automated": {
        "type": "score",
        "instructions": "If replaced by simp_all/aesop/omega, how likely is elaboration to get worse?",
        "criteria": list(ELAB_RISK_CRITERIA),
    },
    "version_fragile": {
        "type": "noul",
        "instructions": (
            "Does `reference_proof` rely on tactic or API details likely to break "
            "across Lean 4.25 through 4.33?"
        ),
    },
    "putnam_aesop_plausible": {
        "type": "noul",
        "instructions": "Given `header` and `statement`, is a short aesop/simp proof plausible?",
    },
    "calc_structure_worth_keeping": {
        "type": "noul",
        "instructions": "Is `reference_proof` a calc/conv chain whose structure should be kept?",
    },
    "statement_in_proof_duplicated": {
        "type": "noul",
        "instructions": "Does `reference_proof` repeat `statement` or contain a second theorem/lemma?",
    },
    "uses_sorry_or_admit": {
        "type": "noul",
        "instructions": "Does `reference_proof` contain sorry, admit, or an axiom?",
    },
    "neighbor_style_match": {
        "type": "choice",
        "instructions": "Which neighbor's proof style should the generator imitate?",
        "criteria": {"none": "Do not imitate a neighbor"},
    },
    "spend_llm": {
        "type": "noul",
        "instructions": "Should code spend an LLM generation rather than only hammers?",
    },
}

CANDIDATE_QUESTION_SPEC: dict[str, dict[str, Any]] = {
    "candidate_changes_statement": {
        "type": "noul",
        "instructions": "Does the candidate change the theorem statement versus `statement`?",
    },
    "likely_shorter_than_reference": {
        "type": "score",
        "instructions": "How large a source-token cut is this candidate versus the reference?",
        "criteria": list(LIKELY_SHORTER_CRITERIA),
    },
    "likely_compiles": {
        "type": "noul",
        "instructions": "Is the candidate likely to compile on every version_info tag?",
    },
    "likely_worse_elab": {
        "type": "noul",
        "instructions": "Is the candidate likely worse on elaboration effort than the reference?",
    },
    "introduces_sorry": {
        "type": "noul",
        "instructions": "Does the candidate introduce sorry, admit, or a new axiom?",
    },
}

DEFAULT_FIXTURE_ANSWERS: dict[str, Any] = {
    "rewrite_family": "have_chain",
    "hammer_before_llm": 0.31,
    "reference_already_tight": 0.91,
    "likely_shorter": 0.0,
    "elab_risk_if_automated": 1.0,
    "version_fragile": 0.22,
    "putnam_aesop_plausible": 0.18,
    "calc_structure_worth_keeping": 0.12,
    "statement_in_proof_duplicated": 0.05,
    "uses_sorry_or_admit": 0.02,
    "neighbor_style_match": "none",
    "spend_llm": 0.21,
}

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

PICK_QUESTION_SPEC: dict[str, dict[str, Any]] = {
    "family": {
        "type": "choice",
        "instructions": {
            "question": "Which edit family is the best next step on this lake-valid Lean 4 proof?",
            "focus": "Classify the residual, not every tactic present. Do not write Lean.",
        },
    },
    "likely_token_cut": {
        "type": "score",
        "instructions": {
            "question": "How large a token cut if the best family is applied?",
            "note": "Judge expected lake-valid shortening, not the raw string length.",
        },
        "criteria": list(LIKELY_SHORTER_CRITERIA),
    },
    "breaks_pca": {
        "type": "noul",
        "instructions": {
            "question": "Would the best family drop an induction or case arm?",
            "focus": "true means the edit is the wrong bet.",
        },
        "criteria": {
            "true": "Deletes induction/case structure",
            "false": "Keeps the PCA skeleton",
        },
    },
    "will_fail_compile": {
        "type": "noul",
        "instructions": {
            "question": "Will the greedy leaf fail `lake` compile?",
            "focus": "true = P(wrong); escalate away from that leaf (SDE cascade).",
        },
        "criteria": {
            "true": {
                "what": "Unknown identifier, type mismatch, unsolved goals, or dropped case",
                "examples": ["sweep_rand spans", "port_dot_ctor_apply", "exact ih"],
            },
            "false": {
                "what": "Used-binder-safe closed fold that previously laked",
                "examples": ["drop_unused_binders", "collapse_simp_at", "port_intro_x_hin"],
            },
        },
    },
}
PICK_FAIL_CRITERIA = {
    "true": "Likely unknown identifier, type mismatch, or unsolved goals",
    "false": "A binder-safe fold or a kernel that already laked on this problem",
}
PICK_LEAF_FOCUS = "Prefer drop_unused_binders, collapse_simp_at, port_* over sweep_rand spans."
PICK_GOAL = "Keep induction/case. Do not write Lean."

INTENT_QUESTION_SPEC: dict[str, dict[str, Any]] = {
    "intent": {
        "type": "choice",
        "instructions": {
            "question": "Which tactic family should the next denoise step generate drafts for?",
            "focus": "Route to one handler. pca_keep means skip lake. Do not write Lean.",
        },
    },
    "complexity": {
        "type": "score",
        "instructions": "How hard is a safe shorter fold on this script?",
        "criteria": [
            "One-line portable fold (intro/assumption/simp_at)",
            "A few local MCA drops",
            "No remaining lake-valid cut",
        ],
    },
    "already_minimal": {
        "type": "noul",
        "instructions": {
            "question": "Is this script already locally minimal (no lake-valid shorter fold)?",
            "focus": "true = skip lake this round.",
        },
        "criteria": {
            "true": "Every remaining edit drops a used binder or breaks a case arm",
            "false": "A closed fold such as unused intros or exact→assumption remains",
        },
    },
    "compose": {
        "type": "choice",
        "instructions": {
            "question": "Apply one skill, the pipeline, or nest a TypeSafe loop on a child of the skill decision tree?",
            "focus": "nest opens a recursive inner loop on one family/skill. Do not write Lean.",
        },
    },
    "skill": {
        "type": "choice",
        "instructions": {
            "question": "Which named kernel should code invoke next (skill suggestion)?",
            "focus": "keep if none is lake-safe. Do not write Lean.",
        },
    },
}
INTENT_NEST_INSTRUCTIONS = {
    "question": "If compose is nest/spawn, which child of the skill decision tree or named subloop should run?",
    "focus": "A family, named skill, or registered subloop. Do not write Lean.",
}
INTENT_TOOL_INSTRUCTIONS = {
    "question": "If compose is analyze, which static-analysis tool should TypeSafe run?",
    "focus": "Navigate skills; do not write Lean; do not call docker0.",
}

CFG_MASK_CRITERIA: tuple[str, ...] = (
    "2 masks of 1 token; keep PCA induction/dot arms",
    "3 masks of 2 tokens",
    "4 masks of 3 tokens",
    "6 masks of 4 tokens",
    "8 masks of 6 tokens",
)
CFG_SCHEDULES: tuple[dict[str, Any], ...] = (
    {"id": "cfg0", "n_masks": 2, "span": 1, "n_shots": 0, "cfg_scale": 0.0},
    {"id": "cfg1", "n_masks": 3, "span": 2, "n_shots": 2, "cfg_scale": 1.0},
    {"id": "cfg2", "n_masks": 4, "span": 3, "n_shots": 4, "cfg_scale": 1.5},
    {"id": "cfg3", "n_masks": 6, "span": 4, "n_shots": 6, "cfg_scale": 2.0},
    {"id": "cfg4", "n_masks": 8, "span": 6, "n_shots": 8, "cfg_scale": 3.0},
)
ONE_HOLE_SPANS: tuple[int, ...] = (1, 2, 3, 4, 6)
ONE_HOLE_CRITERIA: tuple[str, ...] = (
    "1-token hole (operator / ident)",
    "2-token hole",
    "3-token hole (short phrase)",
    "4-token hole",
    "6-token hole (kernel-sized span)",
)
ONE_HOLE_SCHEDULES: tuple[dict[str, Any], ...] = tuple(
    {"id": f"span{span}", "n_masks": 1, "span": span, "n_shots": 6, "cfg_scale": 1.5}
    for span in ONE_HOLE_SPANS
)

FANOUT_FAMILY_CRITERIA = {
    **FAMILY_BLURB,
    "pca_keep": "Keep the reference; PCA says it is already the dominant style",
    "inits_replay": (
        "Apply the closed Core.InitsUpdatesComm 268→139 kernel sequence. "
        "No LLM. Lake is the oracle."
    ),
    "drop": "Drop a residual binder, named arg, or unused intro",
    "rewrite": "Apply one InitsUpdatesComm shorten kernel (MCA residual)",
    "symbol_diffuse": (
        "Fill a masked Lean operator/symbol from the closed language "
        "($, constructor, intro, all_goals, .update_some) or Leanstral"
    ),
}
PCA_FANOUT_BEST = (
    "Which draft id should lake-compile first as a refactor of the reference? "
    "Prefer MCA-guided dead_code, strength_reduction, or algebraic_simplification "
    "if they preserve every case arm. Do not write Lean."
)
PCA_FANOUT_NOULS = {
    "dead_code_safe": (
        "Is dropping have/obtain/rename_i/simp-at-before-simp_all likely to preserve meaning?"
    ),
    "strength_reduction_safe": "Is replacing simp-at runs with simp_all likely to compile?",
    "loop_invariant_safe": (
        "Are have-facts after induction redundant loop invariants that can be dropped?"
    ),
    "search_space_safe": "Can intros/search tactics shrink without deleting a case arm?",
    "algebraic_simplification_safe": (
        "Can rw/calc/ring/omega chains be replaced by simp or omega without changing the theorem?"
    ),
}
PCA_FANOUT_FAMILY_INSTRUCTIONS = (
    "Which compiler family should lake try first on this AST given PCA/MCA? Do not write Lean."
)
DRAFT_FANOUT_BEST = (
    "Which draft id in `drafts` should code lake-compile first as a refactor of "
    "`reference_head` for `statement`? Pick exactly one id. Do not write Lean."
)
DRAFT_FANOUT_NOULS = {
    "any_draft_likely_compiles": (
        "Is at least one catalog draft likely to compile on the record's version_info tags?"
    ),
    "spend_llm_after_fanout": (
        "After trying the ranked drafts, should code still spend a Leanstral generation?"
    ),
}
SGD_HOLE_INSTRUCTIONS = (
    "Which hole id should we drop next in this stochastic descent? "
    "Prefer strength_reduction simp-at runs, then dead_code rename_i. "
    "Do not write Lean."
)
PRUNE_NEXT_LINE = (
    "Which candidate is the best NEXT tactic line? Do not write Lean. "
    "Fill earliest_unfinished in original order: if its header is missing, pick that "
    "header; if the arm still has next_original, pick exactly that line. Never skip "
    "ahead to a later case. Never pick have/rename or English. STOP only when every "
    "PCA arm has used its original non-MCA tactics."
)
RANK_FILL_BEST = (
    "Which fill id is most likely to lake-compile AND use fewer tokens? "
    "Prefer constructor/$/all_goals/intro/.update_some and catalog "
    "few-shot multi-hole fills over dropping hyps. Do not write Lean."
)
RANK_FILL_CFG = (
    "How aggressively should the next denoise step mask this proof? "
    "Higher = more holes and longer token spans. Never mask induction "
    "or · / case arms. Do not write Lean."
)
RANK_FILL_GOAL = (
    "Rank masked-operator fills, including few-shot Leanstral multi-hole "
    "fills and closed-vocab CFG-schedule fills. Prefer the shortest "
    "candidate that still lake-compiles. Do not write Lean."
)
RANK_FILL_FEW_SHOT = (
    "Is a few-shot multi-hole Leanstral fill more likely to lake-compile "
    "AND cut tokens than the closed-vocab fills? true means the few-shot "
    "fill is the wrong bet."
)
RANK_FANOUT_BEST = (
    "Which draft id should lake-compile first to repair this grok file? "
    "Prefer restoring a truncated case arm from the reference, then dropping a "
    "no-progress simp_all. Never delete a case header. Do not write Lean."
)
RANK_FANOUT_GOAL = "Repair a grok-written tactic file. Keep every case arm. Prefer the shortest lake-valid draft."
CASCADE_FAMILY_INSTRUCTIONS = (
    "Which edit family is the best next step to shorten this lake-valid "
    "Lean 4 proof without breaking compile? Do not write Lean."
)
CFG_ONE_HOLE_GOAL = (
    "Pick a ONE-HOLE span length for discrete text diffusion. "
    "Higher CFG score means a longer masked span. Keep induction and · arms. "
    "Do not write Lean."
)
CFG_MULTI_GOAL = (
    "Pick a mask schedule for discrete text diffusion. Higher CFG score "
    "means more/longer masks. Keep induction and · arms. Do not write Lean."
)
CFG_ONE_HOLE_SCORE = (
    "How long should the single masked span be? Higher = more tokens "
    "in that one hole. Stay off PCA induction/· / case. Do not write Lean."
)
CFG_MULTI_SCORE = (
    "How aggressively should we mask this Lean proof? Higher = more "
    "holes and longer spans. Stay off PCA induction/· / case. Do not write Lean."
)
CFG_ONE_HOLE_CHOICE = (
    "Which one-hole span length should Leanstral / closed-vocab fill next? "
    "Prefer a span that matches a remaining rewrite phrase. Do not write Lean."
)
CFG_MULTI_CHOICE = (
    "Which mask schedule should Leanstral / closed-vocab fill next? "
    "Prefer a schedule whose span length matches remaining rewrite "
    "phrases. Do not write Lean."
)


def default_fixture_answers() -> dict[str, Any]:
    """CI answers: rubric level 0 plus a tight reference. Not live Jev."""

    return dict(DEFAULT_FIXTURE_ANSWERS)


DEFAULT_MODE = "off"
OFFICIAL_TRACK2_MODE = "off"
LOOP_V1_TYPESAFE = "off"
LOOP_V1_TRACK1 = "off"
JEV_GENERATES_LEAN = False
SCORE_IS_RUBRIC_INDEX = True
DEFAULT_GENERATOR = "leanstral"
IS_DEFAULT_WINNING_PATH = False
REQUESTED_PROVIDER = "grok"
REQUESTED_MODEL = "grok-4.6"
MAX_GROK_CALLS = 2
LOOP_VERSION = "v2"
PATH_NAME = "A"
ON_30_SEP_CRITICAL_PATH = False
V1_RUNS_THIS = False
HAMMER_006_LRA_READY = False
USES_SNAPSHOT_GOAL = False

FAIL_CLOSED_GROK_KWARGS: dict[str, Any] = {
    "provider": "grok",
    "model_name": "grok-4.6",
    "temperature": 0.0,
    "allow_local_fallback": False,
    "allow_cross_provider_fallback": False,
    "disable_model_retry": True,
}
FAIL_CLOSED_LEANSTRAL_KWARGS: dict[str, Any] = {
    "provider": "leanstral_local",
    "model_name": "Leanstral",
    "temperature": 0.0,
    "allow_local_fallback": False,
    "allow_cross_provider_fallback": False,
    "disable_model_retry": True,
}

CONFIDENT = 0.55
FIRE_T = 0.7
FIRE_T_RESIDUAL = 0.5
FIRE_T_LEAF = 0.45
BEAM_K = 3
EPSILON = 1e-9
UNCERTAIN = 0.60
NEST_MAX_DEPTH = 3
INNER_MAX_STEPS = 8
MAX_LIVE_TOKENS = 700
HIGH_STAKES = frozenset(
    {
        "Core.InitsUpdatesComm",
        "Cslib.CCS.bisimilarity_congr_choice",
    }
)
RESIDUAL_TO_SKILL: dict[str, tuple[str, ...]] = {
    "intros_x_Hin": ("unused_intros",),
    "intro_then_simp_all": ("drop_intro_before_simp_all",),
    "try_simp_all": ("drop_try_simp_all",),
    "apply_semi_assumption": ("semi_assumption",),
    "use_then_exact": ("use_exact", "use_exact_reuse"),
    "have": (),
    "ctor_lone": ("ctor_pair_exacts",),
    "grind": ("repeat_par_grind", "grind_only_to_grind"),
    "repeated_simp_list": ("hoist_repeated_simp",),
    "inner_simp_subset": ("redundant_inner_simp",),
    "trailing_tuple_comma": ("trailing_tuple_comma",),
}
SOURCE_WEIGHT: dict[str, float] = {
    "jsonld": 1.02,
    "jsonld_duckdb": 0.92,
    "duckdb": 0.9,
    "sidecar_duckdb": 0.88,
    "vector": 0.95,
    "kg": 0.85,
    "ast": 0.7,
    "rg": 0.5,
}
SYMBOLS_SQL = (
    "SELECT qualified_name, path, symbol_kind FROM symbols "
    "WHERE lower(CAST(qualified_name AS VARCHAR)) LIKE ? LIMIT 20"
)
CODE_SYMBOLS_SQL = (
    "SELECT name, path, kind FROM code_symbols "
    "WHERE lower(CAST(name AS VARCHAR)) LIKE ? LIMIT 20"
)
SIDECAR_SYMBOLS_SQL = (
    "SELECT qualified_name, path, symbol_kind FROM symbols "
    "WHERE lower(CAST(qualified_name AS VARCHAR)) LIKE ? LIMIT 20"
)
SIDECAR_CALLS_SQL = "SELECT {column} FROM calls WHERE {match_on} = ? OR {match_on} LIKE ? LIMIT 12"
SIDECAR_EDGES_SQL = "SELECT caller, callee FROM calls LIMIT ?"

DOCKER0_HOST = "172.17.0.1"
DOCKER0_PORT = 8080
DOCKER0_HEALTH_URL = f"http://{DOCKER0_HOST}:{DOCKER0_PORT}/health"
DOCKER0_HEALTH_ALIAS_URL = f"http://127.0.0.1:{DOCKER0_PORT}/health"
DOCKER0_OPENAI_BASE_URL = f"http://{DOCKER0_HOST}:{DOCKER0_PORT}/v1"
UNREACHABLE_DOCKER0_OPENAI_BASE_URL = f"http://{DOCKER0_HOST}:9/v1"
DEFAULT_MAX_NEW_TOKENS = 1400
DEFAULT_TIMEOUT_SECONDS = 300
PUTNAM_MAX_NEW_TOKENS = 4096
PUTNAM_TIMEOUT_SECONDS = 600
HEALTH_TIMEOUT_SECONDS = 2.0
ALLOWED_LEANSTRAL_PROVIDERS = frozenset({"leanstral_local", "llama_cpp"})
FORBIDDEN_LEANSTRAL_FALLBACKS = frozenset(
    {
        "grok",
        "grok_cli",
        "xai",
        "hf_inference_api",
        "huggingface",
        "local_hf",
        "openai",
        "openrouter",
        "codex_cli",
        "gemini_cli",
        "claude_code",
    }
)
CASCADE_BEAM_K = 2
FAIL_NOULS: dict[str, tuple[str, str, str]] = {
    "will_unsolve_refine": (
        "Will this edit leave a refine ⟨rfl, ?_, ?_⟩ subgoal unsolved (refine_2.a / refine_1.a)?",
        "the edit will leave a refine hole unsolved",
        "the refine holes will still close",
    ),
    "will_unify_fail": (
        "Will Lean fail to unify updatedStatesInit or UpdateStateNotDefMonotone' after this edit?",
        "unify will fail",
        "unify will succeed",
    ),
    "will_simp_no_progress": (
        "Will Lean report simp_all made no progress after this edit?",
        "simp_all will make no progress",
        "simp_all will still close or rewrite",
    ),
    "will_invalid_ih_projection": (
        "Will rewriting apply (ih Hinit ?_ ?_).2.2 drop the extra arguments and become an invalid projection on a function?",
        "the ih projection will be invalid",
        "the ih apply will still type-check",
    ),
    "will_and_intro_type_mismatch": (
        "Will deleting apply And.intro make updatedStatesInit have type InitStates when Lean expected an And?",
        "the And.intro drop will cause a type mismatch",
        "the goal still accepts a single InitStates proof",
    ),
}
SEED_FEATURES = (
    ("likely_compiles", "noul", "After this edit the Lean file will still lake-compile."),
    ("likely_shorter", "noul", "This edit uses fewer Lean tokens than the current script."),
    ("drops_pca_glue", "noul", "This edit deletes induction, a case header, or intros/exists."),
    ("drops_prefix_have", "noul", "This edit deletes a prefix have (Hk, Hlen1, or Hlen2) that simp_all uses."),
    ("breaks_refine", "noul", "This edit will leave a refine ⟨rfl, ?_, ?_⟩ subgoal unsolved."),
    ("duplicate_needed", "noul", "A line this edit drops is a load-bearing duplicate exact/simp_all/apply."),
    ("local_one_line", "noul", "The edit changes exactly one tactic line."),
)
MISS_FEATURES = (
    (
        "opens_refine_2a",
        "noul",
        "This edit will leave case refine_2.a or refine_2.a.h unsolved.",
    ),
    (
        "semicolon_apply_longer",
        "noul",
        "This edit joins apply lines with <;> and will use more tokens, not fewer.",
    ),
    (
        "constructor_for_rfl_refine",
        "noul",
        "This edit replaces refine ⟨rfl, ?_, ?_⟩ with constructor and will fail updatedStatesInit.",
    ),
    (
        "drops_second_exact",
        "noul",
        "This edit deletes a second exact InitStatesNotDefined or InitStatesNodup that still has an open refine hole.",
    ),
)
ALL_FEATURES = SEED_FEATURES + MISS_FEATURES
PENALTY = {
    "drops_pca_glue",
    "drops_prefix_have",
    "breaks_refine",
    "duplicate_needed",
    "opens_refine_2a",
    "semicolon_apply_longer",
    "constructor_for_rfl_refine",
    "drops_second_exact",
}

ROOT_GOAL = "LRA-G000"
BLOCKED = frozenset({"LRA-S09", "LRA-S10", "LRA-024", "LRA-025", "LRA-027"})
THEOREM_TASKS: dict[str, str] = {
    "CallElimCorrect.substOldPostSubset": "LRA-017",
    "CallElimCorrect.extractedOldExprInVars": "LRA-017",
    "Core.InitsUpdatesComm": "LRA-019",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress": "LRA-017",
    "Cslib.SKI.parallelReduction_diamond": "LRA-017",
    "Cslib.CCS.bisimilarity_congr_choice": "LRA-019",
}

STRATA_SOURCE = "strata"
PUTNAM_SOURCE = "putnambench"
STRATA_FIRST_TAG = "v4.26.0"
STRATA_FIRST_COMMIT = "451e5f047bafa010d178856db76c00029bfa4d7f"
STRATA_URL = "https://github.com/strata-org/Strata"
SOURCE_ORDER = ("strata", "physlib", "cslib", "arklib", "putnambench")
PUTNAM_TAGS: tuple[str, ...] = ("v4.25.0", "v4.26.0", "v4.27.0")
MATHLIB_GIT = "https://github.com/leanprover-community/mathlib4.git"
AESOP_GIT = "https://github.com/leanprover-community/aesop.git"
PUTNAM_PACKAGE = "putnam_lake"
PUTNAM_LIB = "Putnam"
PUTNAM_MODULE = "Putnam.Candidate"
PUTNAM_CANDIDATE_RELPATH = "Putnam/Candidate.lean"
PUTNAM_ROOT_RELPATH = "Putnam.lean"
FORBIDDEN_PUTNAM_BASENAME = "Tmp.lean"
MEASUREMENT_MAX_HEARTBEATS = 400000
ELAN_TOOLCHAIN_DIRNAME_PREFIX = "leanprover--lean4---"
KERNEL_COMMAND_TEMPLATE = "{lake} env {lean} --json {source_file}"
BAKE_ARGV_TEMPLATE = "{lake} build"
DEFAULT_LAKE_TIMEOUT_SECONDS = 28800
STRATA_FIRST_FILE = "Strata/Transform/CallElimCorrect.lean"
STRATA_EXPAND_FILE = "Strata/Languages/Core/StatementSemanticsProps.lean"
LEAN_NUM_THREADS = 1
WARMUP_TAG_TIMEOUT_SECONDS = 600.0
OFFICIAL_TAG_TIMEOUT_SECONDS = 1200.0
INDEPENDENT_KERNEL_VERIFIER_DEFAULT_TIMEOUT_SECONDS = 30.0
MEASUREMENT_ARGV_TEMPLATE = (
    "{lake} env {lean} -DmaxHeartbeats="
    f"{MEASUREMENT_MAX_HEARTBEATS} --json {{source_file}}"
)
FORBIDDEN_PUTNAM_URL_NEEDLES = (
    "github.com/trishullab/PutnamBench",
    "github.com/trishullab/putnambench",
    "github.com/openai/putnam-bench",
)
NETWORK_DENY_VALUES = frozenset({"deny", "offline", "none", "no", "0", "false", "off"})

ALLOWED_TYPESAFE_MODES = ("off", "distill", "inloop")
TYPESAFE_MODEL_ID = "jev-latest"
HEADER_CHARS = 500
NEIGHBOR_K = 4
REF_HEAD_LINES = 80
REF_TAIL_LINES = 80
CHAR_BUDGET = 150_000
ROUTE_NOUL_KEYS = (
    "hammer_before_llm",
    "reference_already_tight",
    "version_fragile",
    "putnam_aesop_plausible",
    "calc_structure_worth_keeping",
    "statement_in_proof_duplicated",
    "uses_sorry_or_admit",
    "spend_llm",
)
ROUTE_CHOICE_ALIASES = {"rewrite_family": "family", "neighbor_style_match": "neighbor_style_match"}
ROUTE_OPTIONAL_CHOICES = ("neighbor_style_match",)

MISTRAL_PROVIDER = "mistral"
MISTRAL_MODEL = "labs-leanstral-1-5"
MISTRAL_API_HOST = "api.mistral.ai"
MISTRAL_CHAT_URL = f"https://{MISTRAL_API_HOST}/v1/chat/completions"
LABS_RETIRE_DATE = "2026-09-30"
MISTRAL_HARDWARE_CLASS = "mistral_labs_api"
PROTOTYPE_HARDWARE_CLASS = "spark_gb10"
PROTOTYPE_BASE_URL = "http://172.17.0.1:8080/v1"
MISTRAL_MAX_NEW_TOKENS = 256
MISTRAL_TIMEOUT_SECONDS = 180.0
MISTRAL_KEY_ENV_NAMES = (
    "MISTRAL_API_KEY",
    "IPFS_ACCELERATE_MISTRAL_API_KEY",
    "IPFS_ACCELERATE_PY_MISTRAL_API_KEY",
    "ipfs_accelerate_py_MISTRAL_API_KEY",
    "IPFS_DATASETS_PY_MISTRAL_API_KEY",
)
MISTRAL_FORBIDDEN_HOSTS = frozenset({"172.17.0.1", "127.0.0.1", "localhost", "0.0.0.0"})
MISTRAL_FORBIDDEN_PROVIDERS = frozenset(
    {
        "leanstral_local",
        "llama_cpp",
        "grok",
        "grok_cli",
        "xai",
        "hf_inference_api",
        "openai",
        "openrouter",
    }
)
MISTRAL_ALT_MODELS = ("labs-leanstral-1-5", "leanstral-1-5")

FROZEN_WARMUP_SHA256 = "6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804"
WARMUP_N = 15
JSONL_FIELDS = (
    "name",
    "source",
    "statement",
    "src",
    "proof_length",
    "num_lines",
    "header",
    "file_path",
    "url",
    "start_line",
    "end_line",
    "version_info",
)
REQUIRED_JSONL_FIELDS = (
    "name",
    "source",
    "statement",
    "src",
    "proof_length",
    "num_lines",
    "header",
    "file_path",
    "url",
    "version_info",
)
FORBIDDEN_SCORE_NAMES = frozenset(
    {
        "arena_score",
        "arena_score_tokens",
        "arena_score_elab",
        "official_track2_score",
        "token_savings",
        "official_score",
        "relevance_score",
    }
)
FORBIDDEN_IMPORT_CORE = frozenset(
    {
        "fcntl",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
    }
)
SMALL_CANARY_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
    "Core.InitsUpdatesComm",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress",
    "Cslib.SKI.parallelReduction_diamond",
    "Cslib.CCS.bisimilarity_congr_choice",
)
OUTER_ACTIONS = ("run", "nest_inner", "mint", "skip_stem", "install_fold", "stop")
KEEP_WORDS = ("intro", "intros", "constructor", "grind", "induction", "exact", "use")
OUTER_ROUTER_PREAMBLE = (
    "You are the OUTER Grok loop. Do not write Lean. TypeSafe is the INNER loop.\n"
    "Reply with one JSON object only, keys: action, stem, name, old, new, keep, reason.\n"
)
OUTER_ROUTER_EXTRA = (
    "nest_inner: enter the TypeSafe inner loop, which keep-loops and recursively nests skill decision-tree children.\n"
    "run: same as nest_inner (TypeSafe still nests).\n"
    "install_fold: literal old→new substring fold that keeps intro/constructor/grind/exact/use.\n"
    "skip_stem: ban a port_ skill that lake-failed.\n"
    "mint: enable a keep-structure stem already in the harness.\n"
    "stop: no remaining lake-valid cut. If nca.halt or nca.budget_dead is true, action must be stop.\n"
)
ROUTER_MAX_NEW = 256
ROUTER_TIMEOUT = 90.0
GOAL_SNAPSHOT_REQUIRED = False
PATH_B_IMPLEMENTED = False
GENERATOR_IDENTITY = "lake_native"
TACTIC_TIMEOUT_SECONDS = 120.0
UNSOLVED_RELPATH = "Strata/Unsolved.lean"
HAMMER_006_CLAIM = "Do not claim HAMMER-006 is LRA-ready."
CRITICAL_PATH_NOTE = "Not on the 30 Sep critical path."
ALLOWED_GROK_PROVIDERS = frozenset({"grok", "xai", "grok_cli"})
FORBIDDEN_GROK_FALLBACKS = frozenset(
    {
        "leanstral_local",
        "llama_cpp",
        "hf_inference_api",
        "huggingface",
        "local_hf",
        "openai",
        "openrouter",
        "codex_cli",
        "gemini_cli",
        "claude_code",
    }
)
GROK_KEY_ENV_NAMES = (
    "XAI_API_KEY",
    "ipfs_accelerate_py_XAI_API_KEY",
    "IPFS_ACCELERATE_PY_XAI_API_KEY",
    "IPFS_DATASETS_PY_XAI_API_KEY",
)
FORBIDDEN_RECEIPT_PARTS = frozenset(
    {
        "official_track2",
        "official-track-2",
        "track2",
        "track-2",
        "a100_80gb_x4",
    }
)
LOOP_V1_WARMUP_RECEIPT_MARKERS = ("submissions", "warmup")
GROK_TACTICS_FILENAME = "tactics.lean"
GROK_FILE_STUB = "-- REPLACE_THIS_FILE\n"
GROK_FILE_TOOLS = "write_file"
GROK_FILE_DISALLOWED = "run_terminal_cmd,web_search,web_fetch,Agent,read_file,list_dir,grep,search_replace"
ALLOWED_TRACK1_MODES = ("off", "track1")
TRACK1_GENERATOR_ALIASES = (
    "grok",
    "grok-4.6",
    "xai",
    "track1",
    "mistral",
    "mistral_labs",
    "labs-leanstral-1-5",
    "leanstral-1-5",
)
TRACK1_MODE_ALIASES = {"on": "track1", "1": "track1", "true": "track1", "yes": "track1", "grok": "track1"}
DOCKER0_UNREACHABLE_FMT = (
    "docker0 Leanstral is unreachable at {url}; fail closed without Grok/HF fallback "
    "({error}). requested={provider}/{model}"
)
LEANSTRAL_RERAISE_FMT = (
    "Leanstral generate_text failed closed at {base} "
    "({error}). requested={requested_provider}/{requested_model} "
    "resolved={resolved_provider}/{resolved_model}"
)

PROTOCOL = "LRA/v1"
HARDWARE_CLASS_SPARK = "spark_gb10"
HARDWARE_CLASS_GROK = "grok_cli"
AUTOSTART_ENV = "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART"
OWNER_SCRIPT_RELATIVE = "scripts/run_leanstral_ephemeral.py"
OWNER_BIND = "docker0"
OWNER_GPU = "0"
OWNER_LOCK_ID = "gpu-0"
FLOCK_SH = 1
FLOCK_NB = 4
FLOCK_UN = 8
BY_NEWLINE = " := by\n"
TOKEN_WEIGHT = 0.55
ELAB_WEIGHT = 0.45
LOOP_VERSION_V1 = "v1"
GENERATOR_LEANSTRAL = "leanstral"
GATES_OFF = "off"
HAMMERS_OFF = "off"
TYPESAFE_OFF = "off"
TOKENIZER_ID = "lra-local-ws-punct/v1"
MAX_LOOP_CANDIDATES = 8
PROBLEM_SCHEMA = "lra-problem-receipt/v1"
LOOP_SCHEMA = "lra-warmup-loop/v1"
V1_PHASES = (
    "splice",
    "retrieve",
    "generate_or_skip",
    "lexical_admit",
    "lake_compile",
    "keep_best",
)
WARMUP_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
    "Core.InitsUpdatesComm",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress",
    "Cslib.SKI.parallelReduction_diamond",
    "Cslib.CCS.bisimilarity_congr_choice",
    "putnam_1964_a4",
    "putnam_1964_b2",
    "putnam_1995_a3",
    "fundamental_theorem_of_variational_calculus'",
    "Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema",
    "FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time",
    "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius",
    "Binius.BinaryBasefold.fold_advances_evaluation_poly",
    "interleaved_affine_gaps_imply_tensor_gaps",
)
MCA_READY = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
    "Core.InitsUpdatesComm",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress",
    "Cslib.SKI.parallelReduction_diamond",
    "Cslib.CCS.bisimilarity_congr_choice",
    "fundamental_theorem_of_variational_calculus'",
    "Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema",
    "FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time",
    "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius",
    "Binius.BinaryBasefold.fold_advances_evaluation_poly",
    "interleaved_affine_gaps_imply_tensor_gaps",
)
SHOT_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
)
CANARY_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    "Cslib.CCS.bisimilarity_congr_choice",
)
SRC_LEMMA_CAP = 16
PROMPT_HEAD_CHARS = 400
MAX_DRAFTS = 48
MAX_CHOICE_OPTIONS = 255
STATEMENT_CHARS = 480
CASE_REPLACE_CAP = 8
NEIGHBOR_DRAFT_CAP = 3
NEIGHBOR_HEAD_LINES = 8
MAX_GROK_FANOUT = 14
GROK_MAX_NEW_TOKENS = 900
GROK_TIMEOUT_SECONDS = 300.0
MAX_PROPOSALS = 8
MAX_MCMC_JEV = 24
MAX_LEANSTRAL = 4
MCMC_CLOSERS = ("simp_all", "omega", "constructor", "rfl")
MAX_STEPS_DEFAULT = 12
BEAM_DEFAULT = 1
MAX_NEW_TOKENS_LINE = 48
LINE_TIMEOUT = 120.0
MAX_CANDIDATES = 12
MAX_BEAM_JEV_CALLS = 48
MAX_SAMPLES = 4
INSERT_ONLY = True
FILESYSTEM_IS_AUTHORITY = True
IS_CONTROL_PLANE = False
REQUIRES_TODO_DAEMON = False
REQUIRES_DUCKDB = False
NO_NEW_AXIOMS = True
NOT_APPLICABLE = "not-applicable"
DEFAULT_IR = "lean4-proof-body"
DEFAULT_PROPERTY = "statement-preserving-refactor"
DEFAULT_TRANSLATOR = "body-splice-v1"
DEFAULT_BACKEND_ID = "lake-env-lean"
DEFAULT_POLICY = "open_policy_v1"
DEFAULT_RESOURCE = "spark_gb10"
RECEIPT_GENERATOR = "leanstral_local"
MAX_ROW_BYTES = 8192
PROOF_AUTHORITY_DIMENSIONS: tuple[str, ...] = (
    "ir",
    "property",
    "assumptions",
    "premises",
    "translator",
    "solver",
    "toolchain",
    "theorem_registry",
    "policy",
    "resource",
    "tree",
    "backend_id",
    "backend_binary",
    "backend_version",
    "backend_config",
)
PROOF_BODY_KEYS = frozenset({"src", "proof_text", "candidate_source", "body", "lean_source"})
FORBIDDEN_ORACLE_NAMES = frozenset(
    {
        "IndependentKernelVerifier",
        "KernelVerifier",
        "verify_admitted_lean_proof",
        "verify_lean_proof_text",
        "TypeSafeClient",
        "system_one",
        "snapshot_goal",
        "attempt_native_automation",
    }
)
FORBIDDEN_SERVER_BINARIES = frozenset(
    {
        "llama-server",
        "llama_server",
        "ipfs-accelerate-llama-cpp-serve",
    }
)
FORBIDDEN_CORPUS_ATTRS = frozenset(
    {
        "CorpusManifest",
        "TheoremEntry",
        "GoalFeatures",
        "select_premises",
        "select_premises_for_theorem",
        "register_source",
        "ingest",
    }
)
FORBIDDEN_CALLS_CORE = frozenset({"which", "find_executable", "LOCK_EX"})
PROBLEM_BUDGET_USD = Decimal("3.00")
PROBLEM_BUDGET_USD_FLOAT = 3.0
JEV_INPUT_USD_PER_MTOK = Decimal("0.042")
JEV_OUTPUT_USD_PER_MTOK = Decimal("0")
GROK_INPUT_USD_PER_MTOK = Decimal("3.00")
GROK_OUTPUT_USD_PER_MTOK = Decimal("15.00")
MISTRAL_INPUT_USD_PER_MTOK = Decimal("0")
MISTRAL_OUTPUT_USD_PER_MTOK = Decimal("0")
USD_QUANT = Decimal("0.000001")
MAX_JEV_CALLS = 2
MAX_MISTRAL_CALLS = 2
CASCADE_MAX_JEV = 20
WALK_MAX_FILES = 80
MAX_CODEPATH_NEIGHBORS = 12
INSPECT_ONLY_MARKERS = ("generate_text", "docker0", "leanstral_local", "172.17")
DEFAULT_CANARY_SEED = 20260917
DEFAULT_CANARY_K = 3
CANARY_PRIMARY = "CallElimCorrect.substOldPostSubset"
LEANSTRAL_LOCAL_PROVIDER = "leanstral_local"
LEANSTRAL_LOCAL_MODEL = "Leanstral"
GIT_BIN = Path("/usr/bin/git")
PROCESS_SUPERVISOR_ENV = "IPFS_DATASETS_PROCESS_SUPERVISOR_DIR"
STATE_RELATIVE = Path("ipfs_accelerate_py") / "vericodegen-2026" / "lean_refactor_arena"
COMPILE_SCHEMA = "lra-compile-receipt/v1"
BATCH_SCHEMA = "lra-batch-verify/v1"
FREEZE_SCHEMA = "lra-freeze-binding/v1"
SKIP_JSON_NAMES = frozenset(
    {
        "batch.json",
        "freeze_binding.json",
        "problem.json",
        "admission.json",
        "result.json",
    }
)
RESERVED_DIR_NAMES = frozenset({"problems", "validation", "outputs"})
BATCH_GATES = (
    "digest",
    "statement_bind",
    "all_tags",
    "no_sorry",
    "complete",
)
LRA_STATE_ROOT = Path.home() / ".local/state/ipfs_accelerate_py/vericodegen-2026-lra"
DEFAULT_TRACK1_STATE = LRA_STATE_ROOT / "track1-lake"
LRA_LANE = LRA_STATE_ROOT / "lean_refactor_arena"
GROK_FILE_WORK_ROOT = LRA_STATE_ROOT / "grok-file"
TYPESAFE_KEYFILE = Path.home() / ".config/ipfs_accelerate_py/typesafe.env"
ACCEL_ROOT = Path("/home/barberb/lift_coding/external/ipfs_accelerate")
ACCEL_PY = ACCEL_ROOT / "ipfs_accelerate_py"
SELF_CHECK_TAG_TIMEOUT_SECONDS = 60.0
LIVE_SELF_CHECK_MAX_NEW_TOKENS = 32
LIVE_SELF_CHECK_TIMEOUT_SECONDS = 90.0
DRAFT_HEAD_CHARS = 220
DRAFT_REF_HEAD_LINES = 24
SYMBOL_MAX_HITS = 24
RG_TIMEOUT_SECONDS = 4.0
ADDITIVE_NOT_REPLACEMENT = True
TRACK1_INLOOP_ONLY = True
TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DISTILL_POLICY_RELATIVE = "papers/completion/lean_refactor_arena/policy/open_policy_v1.json"
DEFAULT_GROK_CLI_MAX_TURNS = 4
DEFAULT_GROK_FILE_MAX_TURNS = 8
TRACK_LABEL = "track1_closed"
CONTROL_PLANE = "papers/completion/lean_refactor_arena/harness/run_warmup.py"
PROOF_RECEIPT_SCHEMA = "lra-proof-receipt/v1"
RECEIPT_STORE_SCHEMA = "lra-receipt-store/v1"
LAKE_NATIVE_SCHEMA = "lra-lake-native-try/v1"
TRACK1_LEDGER_SCHEMA = "lra-track1-ledger/v1"
DEFAULT_TRACK1_RECEIPTS_RELATIVE = "papers/completion/lean_refactor_arena/submissions/track1"
PROOF_AUTHORITY_DIMENSION_SET = frozenset(PROOF_AUTHORITY_DIMENSIONS)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_SQL_HEAD = re.compile(
    r"^\s*(CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS|INSERT\s+INTO|SELECT)\b",
    re.IGNORECASE | re.DOTALL,
)
FORBIDDEN_SQL = re.compile(
    r"\b(DELETE\s+FROM|DROP\s+TABLE|UPDATE\s+\w+|MERGE\s+INTO|REPLACE\s+INTO|"
    r"INSERT\s+OR\s+REPLACE|INSERT\s+OR\s+IGNORE|TRUNCATE\s+TABLE|"
    r"ALTER\s+TABLE)\b",
    re.IGNORECASE,
)
SQL_STATEMENT_HEAD = re.compile(
    r"^\s*(DELETE\s+FROM|DROP\s+TABLE|UPDATE\s+|MERGE\s+INTO|REPLACE\s+INTO|"
    r"INSERT\s+OR\s+|TRUNCATE\s+TABLE|ALTER\s+TABLE)\b",
    re.IGNORECASE,
)

RECEIPT_DDL = """
CREATE TABLE IF NOT EXISTS lra_proof_receipts (
    key_digest VARCHAR PRIMARY KEY,
    theorem_name VARCHAR NOT NULL,
    lean_tag VARCHAR NOT NULL,
    body_digest VARCHAR NOT NULL,
    candidate_cid VARCHAR NOT NULL,
    verdict VARCHAR NOT NULL,
    token_count INTEGER,
    elab_proxy DOUBLE,
    dimensions_json VARCHAR NOT NULL,
    executable_paths_json VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
)
""".strip()

EDGE_DDL = """
CREATE TABLE IF NOT EXISTS lra_proof_edges (
    parent_digest VARCHAR NOT NULL,
    child_digest VARCHAR NOT NULL,
    edge_kind VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    PRIMARY KEY (parent_digest, child_digest, edge_kind)
)
""".strip()

INSERT_RECEIPT_SQL = """
INSERT INTO lra_proof_receipts (
    key_digest, theorem_name, lean_tag, body_digest, candidate_cid,
    verdict, token_count, elab_proxy, dimensions_json,
    executable_paths_json, payload_json, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""".strip()

INSERT_EDGE_SQL = """
INSERT INTO lra_proof_edges (
    parent_digest, child_digest, edge_kind, created_at
) VALUES (?, ?, ?, ?)
""".strip()

SELECT_RECEIPT_SQL = (
    "SELECT key_digest, theorem_name, lean_tag, body_digest, candidate_cid, "
    "verdict, token_count, elab_proxy, dimensions_json, executable_paths_json, "
    "payload_json, created_at FROM lra_proof_receipts WHERE key_digest = ?"
)
SELECT_NEGATIVE_SQL = (
    "SELECT key_digest, verdict FROM lra_proof_receipts "
    "WHERE theorem_name = ? AND body_digest = ? AND lean_tag = ?"
)
SELECT_EDGE_SQL = (
    "SELECT parent_digest, child_digest, edge_kind, created_at "
    "FROM lra_proof_edges WHERE parent_digest = ?"
)
SELECT_EDGE_ONE_SQL = (
    "SELECT parent_digest, child_digest, edge_kind FROM lra_proof_edges "
    "WHERE parent_digest = ? AND child_digest = ? AND edge_kind = ?"
)
SELECT_COUNT_RECEIPTS_SQL = "SELECT COUNT(*) FROM lra_proof_receipts"
SELECT_COUNT_EDGES_SQL = "SELECT COUNT(*) FROM lra_proof_edges"
