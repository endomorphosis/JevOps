#!/usr/bin/env python3
"""TypeSafe Jev router via in-tree ``ipfs_accelerate_py.typesafe_inference``.

Additive typed Choice / Score / Noul gates on top of Leanstral. Default
``LRA_TYPESAFE=off``. Distill uses ``LRA_TYPESAFE=distill``. Official Track 2
stays off. Score is an ordered rubric index, not a probability. Jev does
not generate Lean and does not choose the next action. CI fixtures do not
need a live ``TYPESAFE_API_KEY``. Not a second ``typesafe-sdk`` client.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import retrieve as lra_retrieve  # noqa: E402
import splice as lra_splice  # noqa: E402

ACCEL_ROOT = _jevops_path.IPFS_ACCELERATE_ROOT
TYPESAFE_INFERENCE_PATH = _jevops_path.TYPESAFE_INFERENCE_PATH

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
PROTOCOL = "LRA/v1"
PR_ID = "PR-9"
LRAH_ID = "LRAH-006"
LOOP_V1_TYPESAFE = "off"
DEFAULT_MODE = "off"
ALLOWED_MODES = ("off", "distill", "inloop")
OFFICIAL_TRACK2_MODE = "off"
MODEL_ID = "jev-latest"
JEV_GENERATES_LEAN = False
SCORE_IS_RUBRIC_INDEX = True
ADDITIVE_NOT_REPLACEMENT = True
TRACK1_INLOOP_ONLY = True
TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DISTILL_POLICY_RELATIVE = "papers/completion/lean_refactor_arena/policy/open_policy_v1.json"
HEADER_CHARS = 500
NEIGHBOR_K = 4
REF_HEAD_LINES = 80
REF_TAIL_LINES = 80
CHAR_BUDGET = 150_000
KEY_ENV_NAMES = (
    "TYPESAFE_API_KEY",
    "ipfs_accelerate_py_TYPESAFE_API_KEY",
    "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
    "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
)
FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "typesafe_sdk",
        "typesafe",
        "fcntl",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "llm_router",
        "generate_text",
        "urllib",
        "requests",
        "http",
        "httpx",
    }
)
FORBIDDEN_CALLS = frozenset(
    {
        "generate_text",
        "urlopen",
        "urlretrieve",
        "request",
        "post",
        "Popen",
        "check_output",
    }
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

from jevops.jev import keys_by_type  # noqa: E402

ROUTE_QUESTION_KEYS = tuple(ROUTE_QUESTION_SPEC.keys())
SCORE_QUESTION_KEYS = keys_by_type(ROUTE_QUESTION_SPEC, "score")
NOUL_QUESTION_KEYS = keys_by_type(ROUTE_QUESTION_SPEC, "noul")
CHOICE_QUESTION_KEYS = keys_by_type(ROUTE_QUESTION_SPEC, "choice")


class TypesafeRouterError(RuntimeError):
    """Fail-closed TypeSafe router error. Never a generated Lean proof."""


from jevops.jev import CatalogQuestion  # noqa: E402
from jevops.jev import FixtureChoice  # noqa: E402
from jevops.jev import FixtureClient  # noqa: E402
from jevops.jev import FixtureNoul  # noqa: E402
from jevops.jev import FixtureResponse  # noqa: E402
from jevops.jev import FixtureScore  # noqa: E402


from jevops.jev import RouteResult as _KernelRouteResult


@dataclass(frozen=True)
class RouteResult(_KernelRouteResult):
    model: str = MODEL_ID


def _ensure_accel_path() -> None:
    _jevops_path.ensure_ipfs_accelerate_path()


def _import_typesafe_inference() -> dict[str, Any]:
    """Load in-tree TypeSafe types. Never imports typesafe-sdk."""

    from _optional_deps import load_typesafe

    module, reason = load_typesafe()
    if module is None:
        try:
            reported = str(TYPESAFE_INFERENCE_PATH.relative_to(REPO_ROOT))
        except ValueError:
            reported = str(TYPESAFE_INFERENCE_PATH)
        from jevops.jev import typesafe_load_payload

        return typesafe_load_payload(
            available=False,
            error=reason,
            path=reported,
            exists=TYPESAFE_INFERENCE_PATH.is_file(),
        )
    from jevops.jev import typesafe_load_payload

    return typesafe_load_payload(
        available=True,
        path=str(TYPESAFE_INFERENCE_PATH),
        exists=True,
        Choice=module.Choice,
        Noul=module.Noul,
        Score=module.Score,
        TypeSafeClient=module.TypeSafeClient,
        typesafe_configured=module.typesafe_configured,
    )


def _env_truthy(value: Optional[str]) -> bool:
    from jevops.jev import env_truthy

    return env_truthy(value)


def official_track2_requested(
    *,
    flag: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    from jevops.jev import env_flag

    from jevops.outer import env_mapping

    source = env_mapping(env)
    return env_flag(
        flag=flag,
        env=source,
        truthy_keys=("LRA_OFFICIAL_TRACK2",),
        value_key="LRA_TRACK",
        values=("official_track2", "official-track-2", "track2_official"),
    )


def resolve_typesafe_mode(
    *,
    flag: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    official_track2: bool = False,
) -> str:
    """Default off. Distill/inloop only when not official Track 2."""

    from jevops.jev import JevError
    from jevops.jev import resolve_mode

    from jevops.outer import env_mapping

    source = env_mapping(env)
    try:
        return resolve_mode(
            flag=flag,
            env=source,
            env_key="LRA_TYPESAFE",
            default=DEFAULT_MODE,
            allowed=ALLOWED_MODES,
            closed=OFFICIAL_TRACK2_MODE,
            closed_if=official_track2_requested(flag=official_track2, env=source),
        )
    except JevError as exc:
        raw = DEFAULT_MODE if flag is None else flag
        if flag is None:
            raw = source.get("LRA_TYPESAFE", DEFAULT_MODE)
        mode = str(raw or DEFAULT_MODE).strip().lower()
        raise TypesafeRouterError(f"unknown LRA_TYPESAFE={mode!r}; expected {ALLOWED_MODES}") from exc


def key_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    from jevops.jev import any_key

    from jevops.outer import env_mapping

    source = env_mapping(env)
    return any_key(source, KEY_ENV_NAMES)


def _question_kind(question: Any) -> str:
    from jevops import jev

    try:
        return jev.question_kind(question)
    except jev.JevError as exc:
        raise TypesafeRouterError(str(exc)) from exc


def _question_criteria(question: Any) -> Any:
    from jevops import jev

    return jev.question_criteria(question)


def instantiate_questions(
    spec: Mapping[str, Mapping[str, Any]],
    *,
    choice: Optional[Callable[..., Any]] = None,
    noul: Optional[Callable[..., Any]] = None,
    score: Optional[Callable[..., Any]] = None,
    neighbor_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the frozen ROUTE_QUESTIONS dict. Uses in-tree types when loaded."""

    from jevops import jev

    try:
        return jev.instantiate_questions(
            spec,
            choice=choice,
            noul=noul,
            score=score,
            neighbor_names=neighbor_names,
        )
    except jev.JevError as exc:
        raise TypesafeRouterError(str(exc)) from exc


def route_questions(
    neighbor_names: Sequence[str] = (),
    *,
    typesafe: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    loaded = typesafe if typesafe is not None else _import_typesafe_inference()
    return instantiate_questions(
        ROUTE_QUESTION_SPEC,
        choice=loaded.get("Choice"),
        noul=loaded.get("Noul"),
        score=loaded.get("Score"),
        neighbor_names=neighbor_names,
    )


def candidate_questions(*, typesafe: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    loaded = typesafe if typesafe is not None else _import_typesafe_inference()
    return instantiate_questions(
        CANDIDATE_QUESTION_SPEC,
        choice=loaded.get("Choice"),
        noul=loaded.get("Noul"),
        score=loaded.get("Score"),
    )


def truncate_reference_proof(
    src: str,
    *,
    head_lines: int = REF_HEAD_LINES,
    tail_lines: int = REF_TAIL_LINES,
    char_budget: int = CHAR_BUDGET,
) -> str:
    if not isinstance(src, str):
        raise TypesafeRouterError("reference_proof must be a string")
    from jevops.jev import truncate_middle

    return truncate_middle(
        src,
        head_lines=head_lines,
        tail_lines=tail_lines,
        char_budget=char_budget,
        marker="# lra-truncated middle",
    )


def problem_state(
    record: Mapping[str, Any],
    *,
    neighbors: Sequence[Mapping[str, Any]] = (),
    candidate: Any = None,
) -> dict[str, Any]:
    from jevops.jev import record_state

    return record_state(
        record,
        neighbors=neighbors,
        candidate=candidate,
        header_chars=HEADER_CHARS,
        neighbor_k=NEIGHBOR_K,
        truncate_fn=truncate_reference_proof,
    )


def _noul_value(answer: Any) -> float:
    from jevops import jev

    try:
        return jev.noul_value(answer)
    except jev.JevError as exc:
        raise TypesafeRouterError(str(exc)) from exc


def _choice_value(answer: Any) -> tuple[str, float, dict[str, float]]:
    from jevops import jev

    try:
        return jev.choice_value(answer)
    except jev.JevError as exc:
        raise TypesafeRouterError(str(exc)) from exc


def _score_value(answer: Any, *, n_levels: int, legend_fallback: Mapping[int, str]) -> tuple[float, dict[int, str]]:
    from jevops import jev

    try:
        return jev.score_value(answer, n_levels=n_levels, legend_fallback=legend_fallback)
    except jev.JevError as exc:
        raise TypesafeRouterError(str(exc)) from exc


def answers_from_response(response: Any) -> dict[str, Any]:
    """Project System One answers. Score stays a rubric index. No Lean text."""

    from jevops.jev import project_answers

    try:
        out = project_answers(
            response,
            noul_keys=(
                "hammer_before_llm",
                "reference_already_tight",
                "version_fragile",
                "putnam_aesop_plausible",
                "calc_structure_worth_keeping",
                "statement_in_proof_duplicated",
                "uses_sorry_or_admit",
                "spend_llm",
            ),
            choice_aliases={"rewrite_family": "family", "neighbor_style_match": "neighbor_style_match"},
            optional_choices=("neighbor_style_match",),
            score_specs={
                "likely_shorter": {
                    "dest": "likely_shorter",
                    "n_levels": len(LIKELY_SHORTER_CRITERIA),
                    "legend": LIKELY_SHORTER_LEGEND,
                    "rubric": True,
                },
                "elab_risk_if_automated": {
                    "dest": "elab_risk",
                    "n_levels": len(ELAB_RISK_CRITERIA),
                    "legend": ELAB_RISK_LEGEND,
                },
            },
        )
    except Exception as exc:
        raise TypesafeRouterError(str(exc)) from exc
    from jevops.jev import deny_lean_keys

    return deny_lean_keys(out)


def should_call_leanstral(answers: Optional[Mapping[str, Any]], rec: Mapping[str, Any]) -> bool:
    """v2 helper. Loop v1 calls Leanstral whenever docker0 /health is up."""

    from jevops.search import should_call_generator

    return should_call_generator(answers, rec)


def default_fixture_answers() -> dict[str, Any]:
    """CI answers: rubric level 0 plus a tight reference. Not live Jev."""

    return {
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


class TypeSafeLraRouter:
    """In-tree typesafe_inference wrapper. No-op without key. Off on Track 2."""

    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        official_track2: bool = False,
        env: Optional[Mapping[str, str]] = None,
        client_factory: Optional[Callable[..., Any]] = None,
        model: str = MODEL_ID,
        require_key: bool = True,
    ) -> None:
        from jevops.outer import env_copy

        self.env = env_copy(base=env)
        self.official_track2 = official_track2_requested(flag=official_track2, env=self.env)
        self.mode = resolve_typesafe_mode(flag=mode, env=self.env, official_track2=self.official_track2)
        self.client_factory = client_factory
        self.model = model
        self.require_key = require_key and client_factory is None

    @property
    def enabled(self) -> bool:
        return self.mode in {"distill", "inloop"} and not self.official_track2

    def route(
        self,
        state: Mapping[str, Any],
        *,
        neighbor_names: Sequence[str] = (),
    ) -> RouteResult:
        loaded = _import_typesafe_inference() if self.enabled else {"available": False}
        configured = key_configured(self.env)
        using_fixture = self.client_factory is not None
        from jevops.jev import invoke_system_one, route_or_skip, route_result_from_answers

        def _invoke() -> tuple[Any, float]:
            questions = instantiate_questions(
                ROUTE_QUESTION_SPEC,
                choice=loaded.get("Choice") if not using_fixture else None,
                noul=loaded.get("Noul") if not using_fixture else None,
                score=loaded.get("Score") if not using_fixture else None,
                neighbor_names=neighbor_names,
            )
            factory = self.client_factory or loaded["TypeSafeClient"]
            client = factory(model=self.model)
            return invoke_system_one(client, state, questions)

        return route_or_skip(
            enabled=self.enabled,
            official=self.official_track2,
            key_ok=configured,
            available=bool(loaded.get("available")),
            using_fixture=using_fixture,
            require_key=self.require_key,
            skip_fn=lambda reason: RouteResult(
                skipped=True,
                reason=reason,
                mode=self.mode,
                official_track2=self.official_track2,
                model=self.model,
            ),
            invoke_fn=_invoke,
            project_fn=lambda response, wall_ms: route_result_from_answers(
                answers_from_response(response),
                mode=self.mode,
                official_track2=self.official_track2,
                wall_ms=wall_ms,
                used_fixture=using_fixture,
                model=self.model,
                result_cls=RouteResult,
            ),
        )


def distill_record(
    state: Mapping[str, Any],
    result: RouteResult,
    *,
    lean_outcome: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Log (features, Jev answers, Lean outcome). Does not generate Lean."""

    from jevops.jev import distill_row

    problem = state.get("problem") if isinstance(state.get("problem"), Mapping) else {}
    return distill_row(
        schema="lra-typesafe-distill/v1",
        mode="distill",
        problem=problem,
        answers=result.as_dict(),
        extra={
            "lean_outcome": lean_outcome,
            "official_track2": False,
            "api_key_present_in_record": False,
            "policy_path": DISTILL_POLICY_RELATIVE,
            "writes_policy_by_default": False,
        },
    )


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _call_func_names(source: str) -> set[str]:
    from jevops.repair import call_func_names

    return call_func_names(source)


def _assigned_constant(tree: ast.AST, name: str) -> Any:
    from jevops.repair import assigned_constant

    return assigned_constant(tree, name)


def _numeric_score_assignments(source: str) -> list[str]:
    from jevops.repair import numeric_score_assignments

    return numeric_score_assignments(source, FORBIDDEN_SCORE_NAMES)


def audit_source(source: Optional[str] = None) -> dict[str, Any]:
    from jevops.outer import source_text
    from jevops.repair import audit_source as _audit

    text = source_text(source, path=__file__)
    out = _audit(
        text,
        forbidden_imports=FORBIDDEN_IMPORT_NAMES,
        forbidden_calls=FORBIDDEN_CALLS,
        forbidden_scores=FORBIDDEN_SCORE_NAMES,
    )
    from jevops.repair import assigned_constants, membership

    imported = out["imported_names"]
    calls = set(out["call_func_names"])
    consts = assigned_constants(
        text,
        (
            "JEV_GENERATES_LEAN",
            "SCORE_IS_RUBRIC_INDEX",
            "DEFAULT_MODE",
            "LOOP_V1_TYPESAFE",
            "OFFICIAL_TRACK2_MODE",
        ),
    )
    forbidden_imports = out["forbidden_imports"]
    forbidden_calls = out["forbidden_calls"]
    score_issues = out["score_issues"]
    uses_lock_ex = out["uses_lock_ex"]
    uses_optional_loader = "_optional_deps" in imported and "load_typesafe" in imported
    typesafe_import = "ipfs_accelerate_py.typesafe_inference" in imported or uses_optional_loader
    flags = membership(
        imported,
        {
            "imports_typesafe_inference": ("ipfs_accelerate_py.typesafe_inference",),
            "imports_choice": ("Choice",),
            "imports_noul": ("Noul",),
            "imports_score": ("Score",),
            "imports_typesafe_client": ("TypeSafeClient",),
            "imports_typesafe_configured": ("typesafe_configured",),
            "imports_typesafe_sdk": ("typesafe_sdk", "typesafe"),
            "imports_llm_router": ("llm_router",),
            "imports_generate_text": ("generate_text",),
        },
    )
    flags.update(
        membership(
            calls,
            {
                "calls_generate_text": ("generate_text",),
                "calls_system_one": ("system_one",),
            },
        )
    )
    # The adapter is intentionally loaded through the local optional-dependency
    # boundary rather than by a direct third-party import in this module.
    flags["imports_typesafe_inference"] = typesafe_import
    flags["imports_choice"] = flags["imports_choice"] or uses_optional_loader
    flags["imports_noul"] = flags["imports_noul"] or uses_optional_loader
    flags["imports_score"] = flags["imports_score"] or uses_optional_loader
    flags["imports_typesafe_client"] = flags["imports_typesafe_client"] or uses_optional_loader
    flags["imports_typesafe_configured"] = flags["imports_typesafe_configured"] or uses_optional_loader
    return {
        "imported_names": sorted(imported),
        "forbidden_imports": forbidden_imports,
        "forbidden_calls": forbidden_calls,
        "numeric_score_assignments": score_issues,
        **flags,
        "jev_generates_lean_constant": consts["JEV_GENERATES_LEAN"],
        "score_is_rubric_index_constant": consts["SCORE_IS_RUBRIC_INDEX"],
        "default_mode_constant": consts["DEFAULT_MODE"],
        "loop_v1_typesafe_constant": consts["LOOP_V1_TYPESAFE"],
        "official_track2_mode_constant": consts["OFFICIAL_TRACK2_MODE"],
        "uses_lock_ex": uses_lock_ex,
        "uses_optional_typesafe_loader": uses_optional_loader,
        "ok": (
            typesafe_import
            and flags["imports_choice"]
            and flags["imports_typesafe_client"]
            and uses_optional_loader
            and "typesafe_sdk" not in imported
            and "typesafe" not in imported
            and "llm_router" not in imported
            and "generate_text" not in imported
            and "generate_text" not in calls
            and not forbidden_imports
            and not forbidden_calls
            and not score_issues
            and not uses_lock_ex
            and consts["JEV_GENERATES_LEAN"] is False
            and consts["SCORE_IS_RUBRIC_INDEX"] is True
            and consts["DEFAULT_MODE"] == "off"
            and consts["LOOP_V1_TYPESAFE"] == "off"
            and consts["OFFICIAL_TRACK2_MODE"] == "off"
        ),
    }


def _load_named_record(name: str, path: Optional[Path] = None) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    from jevops.outer import lookup_named

    raw, digest, records = lra_splice.load_warmup_records(path)
    del raw
    record = lookup_named(
        records, name, error_cls=TypesafeRouterError, miss=f"unknown warm-up problem: {name}"
    )
    return dict(record), records, digest


def _neighbors_for(record: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    retrieval = lra_retrieve.retrieve_record(record, records)
    return lra_retrieve.prompt_neighbors(retrieval, k=NEIGHBOR_K)


def route_named(
    name: str,
    *,
    mode: Optional[str] = None,
    official_track2: bool = False,
    fixture: bool = False,
    path: Optional[Path] = None,
    lean_outcome: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    record, records, digest = _load_named_record(name, path)
    neighbors = _neighbors_for(record, records)
    state = problem_state(record, neighbors=neighbors)
    factory = None
    if fixture:
        factory = lambda **kwargs: FixtureClient(answers=default_fixture_answers(), **kwargs)
    router = TypeSafeLraRouter(mode=mode, official_track2=official_track2, client_factory=factory)
    result = router.route(state, neighbor_names=[item["name"] for item in neighbors])
    from jevops.jev import overlay_route_payload

    extra: dict[str, Any] = {
        "route_question_keys": list(ROUTE_QUESTION_KEYS),
        "should_call_leanstral_v2": None if result.skipped else should_call_leanstral(result.as_dict(), record),
        "default_mode": DEFAULT_MODE,
    }
    if router.mode == "distill" and not result.skipped:
        extra["distill"] = distill_record(state, result, lean_outcome=lean_outcome)
    return overlay_route_payload(
        result.as_dict(),
        name=name,
        source=record.get("source"),
        digest=digest,
        n_neighbors=len(neighbors),
        extra=extra,
    )


def plan_view(
    *,
    mode: Optional[str] = None,
    official_track2: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    resolved = resolve_typesafe_mode(flag=mode, env=env, official_track2=official_track2)
    loaded = _import_typesafe_inference()
    from jevops.jev import catalog_kinds

    catalog = instantiate_questions(ROUTE_QUESTION_SPEC)
    score_levels = {
        name: list(spec["criteria"])
        for name, spec in ROUTE_QUESTION_SPEC.items()
        if spec["type"] == "score"
    }
    from jevops.jev import pack_plan_view

    return pack_plan_view(
        protocol=PROTOCOL,
        pr=PR_ID,
        lrah=LRAH_ID,
        default_mode=DEFAULT_MODE,
        resolved_mode=resolved,
        allowed_modes=list(ALLOWED_MODES),
        official_track2=official_track2_requested(flag=official_track2, env=env),
        official_track2_stays_off=True,
        loop_v1_typesafe=LOOP_V1_TYPESAFE,
        distill_uses_lra_typesafe_distill=True,
        inloop_is_track1_only=TRACK1_INLOOP_ONLY,
        additive_not_replacement=ADDITIVE_NOT_REPLACEMENT,
        model=MODEL_ID,
        route_question_keys=list(ROUTE_QUESTION_KEYS),
        score_question_keys=list(SCORE_QUESTION_KEYS),
        noul_question_keys=list(NOUL_QUESTION_KEYS),
        choice_question_keys=list(CHOICE_QUESTION_KEYS),
        likely_shorter_criteria=list(LIKELY_SHORTER_CRITERIA),
        likely_shorter_legend={str(key): value for key, value in LIKELY_SHORTER_LEGEND.items()},
        score_is_rubric_index=SCORE_IS_RUBRIC_INDEX,
        score_levels=score_levels,
        jev_generates_lean=JEV_GENERATES_LEAN,
        typesafe_systemone_url=TYPESAFE_SYSTEMONE_URL,
        router_posts_to_typesafe=False,
        imports_typesafe_inference=True,
        imports_typesafe_sdk=False,
        typesafe_inference_available=loaded["available"],
        typesafe_inference_exists=loaded["exists"],
        typesafe_inference_error=loaded["error"],
        typesafe_inference_path=loaded["path"],
        key_configured=key_configured(env),
        key_env_names=list(KEY_ENV_NAMES),
        catalog_kinds=catalog_kinds(catalog),
        n_catalog=len(catalog),
        distill_policy_path=DISTILL_POLICY_RELATIVE,
        writes_policy_by_default=False,
        frozen_warmup_sha256=FROZEN_WARMUP_SHA256,
    )


def self_check(path: Optional[Path] = None) -> dict[str, Any]:
    """CI fixtures without a live key. Does not POST and does not generate Lean."""

    from jevops.outer import read_text

    source = read_text(__file__)
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    from jevops.outer import digest_file

    before = digest_file(jsonl)
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    after = digest_file(jsonl)
    audit = audit_source(source)
    loaded = _import_typesafe_inference()
    first = records[0]
    neighbors = _neighbors_for(first, records)
    state = problem_state(first, neighbors=neighbors)
    neighbor_names = [item["name"] for item in neighbors]

    default_mode = resolve_typesafe_mode(env={})
    unset_mode = resolve_typesafe_mode(env={"LRA_TYPESAFE": ""})
    distill_mode = resolve_typesafe_mode(env={"LRA_TYPESAFE": "distill"})
    inloop_mode = resolve_typesafe_mode(env={"LRA_TYPESAFE": "inloop"})
    track2_distill = resolve_typesafe_mode(
        flag="distill",
        env={"LRA_TYPESAFE": "distill", "LRA_OFFICIAL_TRACK2": "1"},
        official_track2=True,
    )
    track2_env = resolve_typesafe_mode(env={"LRA_TYPESAFE": "inloop", "LRA_TRACK": "official_track2"})

    off_router = TypeSafeLraRouter(mode=None, env={})
    off_result = off_router.route(state, neighbor_names=neighbor_names)

    no_key_router = TypeSafeLraRouter(mode="distill", env={"LRA_TYPESAFE": "distill"})
    no_key_result = no_key_router.route(state, neighbor_names=neighbor_names)

    fixture_client = FixtureClient(answers=default_fixture_answers())
    distill_router = TypeSafeLraRouter(
        mode="distill",
        env={"LRA_TYPESAFE": "distill"},
        client_factory=lambda **kwargs: fixture_client,
    )
    distill_result = distill_router.route(state, neighbor_names=neighbor_names)
    distill_answers = distill_result.as_dict()
    skip_llm = should_call_leanstral(distill_answers, first)
    distill_log = distill_record(state, distill_result, lean_outcome={"compiled": False, "status": "fixture"})

    custom_fixture = FixtureClient(
        answers={
            **default_fixture_answers(),
            "rewrite_family": "custom",
            "reference_already_tight": 0.2,
            "likely_shorter": 2.0,
            "spend_llm": 0.8,
            "hammer_before_llm": 0.1,
        }
    )
    custom_router = TypeSafeLraRouter(
        mode="distill",
        client_factory=lambda **kwargs: custom_fixture,
    )
    custom_result = custom_router.route(state, neighbor_names=neighbor_names)
    spend_llm = should_call_leanstral(custom_result.as_dict(), first)

    official_router = TypeSafeLraRouter(
        mode="distill",
        official_track2=True,
        env={"LRA_TYPESAFE": "distill"},
        client_factory=lambda **kwargs: FixtureClient(answers=default_fixture_answers()),
    )
    official_result = official_router.route(state, neighbor_names=neighbor_names)

    long_src = "\n".join(f"line_{index}" for index in range(200))
    truncated_lines = truncate_reference_proof(long_src, char_budget=40, head_lines=2, tail_lines=2)

    catalog = instantiate_questions(ROUTE_QUESTION_SPEC, neighbor_names=neighbor_names)
    score_questions = [name for name, question in catalog.items() if question.kind == "score"]
    likely_criteria = ROUTE_QUESTION_SPEC["likely_shorter"]["criteria"]

    unknown_closed = False
    try:
        resolve_typesafe_mode(flag="on")
    except TypesafeRouterError:
        unknown_closed = True

    from jevops.outer import dumps_sorted

    serialized = dumps_sorted({"distill": distill_log, "route": distill_result.as_dict()})
    key_leak = any(token in serialized for token in ("BEGIN SECRET", "sk-live-", "sk-prod-"))

    report = {
        "ok": True,
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "lrah": LRAH_ID,
        "n_records": len(records),
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "warmup_jsonl_sha256": digest,
        "jsonl_bytes": len(raw),
        "jsonl_unchanged": before == after == FROZEN_WARMUP_SHA256,
        "audit": audit,
        "typesafe_inference": {
            "available": loaded["available"],
            "exists": loaded["exists"],
            "error": loaded["error"],
            "path": loaded["path"],
        },
        "modes": {
            "default": default_mode,
            "unset_env": unset_mode,
            "distill": distill_mode,
            "inloop": inloop_mode,
            "official_track2_with_distill_flag": track2_distill,
            "official_track2_env_inloop": track2_env,
            "unknown_closed": unknown_closed,
        },
        "off_result": off_result.as_dict(),
        "no_key_result": no_key_result.as_dict(),
        "distill_fixture": distill_answers,
        "custom_fixture": custom_result.as_dict(),
        "official_track2_result": official_result.as_dict(),
        "skip_llm_on_rubric_level_0": skip_llm is False,
        "spend_llm_on_custom_level_2": spend_llm is True,
        "likely_shorter_level_0": distill_result.likely_shorter,
        "likely_shorter_legend_0": (distill_result.likely_shorter_legend or {}).get(0),
        "likely_shorter_is_rubric_index": distill_result.likely_shorter_is_rubric_index,
        "likely_shorter_not_probability": distill_result.likely_shorter == 0.0
        and (distill_result.likely_shorter_legend or {}).get(0) == "longer or same",
        "custom_likely_shorter_level_2": custom_result.likely_shorter,
        "distill_log": distill_log,
        "catalog_keys": list(catalog.keys()),
        "score_questions": score_questions,
        "likely_shorter_criteria": list(likely_criteria),
        "n_score_levels": len(likely_criteria),
        "neighbor_names": neighbor_names,
        "truncated_over_budget": "lra-truncated" in truncated_lines or len(truncated) <= CHAR_BUDGET,
        "jev_generated_lean": False,
        "off_skipped": off_result.skipped and off_result.reason == "typesafe_off",
        "no_key_skipped": no_key_result.skipped and no_key_result.reason in {"no_key", "typesafe_inference_missing"},
        "distill_called": distill_result.called_typesafe and distill_result.used_fixture and not distill_result.skipped,
        "official_stayed_off": official_result.skipped and official_result.reason == "official_track2_off",
        "official_did_not_call": official_result.called_typesafe is False,
        "default_mode_is_off": default_mode == "off" and unset_mode == "off",
        "distill_uses_lra_typesafe_distill": distill_mode == "distill",
        "inloop_uses_lra_typesafe_inloop": inloop_mode == "inloop",
        "official_track2_stays_off": track2_distill == "off" and track2_env == "off",
        "imports_typesafe_inference": audit["imports_typesafe_inference"],
        "imports_typesafe_sdk": audit["imports_typesafe_sdk"],
        "no_second_typesafe_sdk_client": audit["ok"] and not audit["imports_typesafe_sdk"],
        "score_is_rubric_index": SCORE_IS_RUBRIC_INDEX,
        "additive_not_replacement": ADDITIVE_NOT_REPLACEMENT,
        "key_leak": key_leak,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
        "arena_score": None,
        "first_name": first.get("name"),
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and audit["ok"]
        and report["default_mode_is_off"]
        and report["distill_uses_lra_typesafe_distill"]
        and report["inloop_uses_lra_typesafe_inloop"]
        and report["official_track2_stays_off"]
        and report["off_skipped"]
        and report["no_key_skipped"]
        and report["distill_called"]
        and report["official_stayed_off"]
        and report["official_did_not_call"]
        and report["skip_llm_on_rubric_level_0"]
        and report["spend_llm_on_custom_level_2"]
        and report["likely_shorter_not_probability"]
        and report["likely_shorter_level_0"] == 0.0
        and report["custom_likely_shorter_level_2"] == 2.0
        and report["imports_typesafe_inference"]
        and not report["imports_typesafe_sdk"]
        and report["jev_generated_lean"] is False
        and distill_result.jev_generated_lean is False
        and distill_result.lean_text is None
        and distill_result.tactics is None
        and distill_result.proof_text is None
        and distill_result.arena_score is None
        and distill_log["jev_generated_lean"] is False
        and distill_log["api_key_present_in_record"] is False
        and unknown_closed
        and not key_leak
        and report["catalog_keys"] == list(ROUTE_QUESTION_KEYS)
        and report["n_score_levels"] == 3
        and report["compiled"] is False
        and report["arena_score"] is None
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="CI fixtures; no live key; no POST")
    parser.add_argument("--plan", action="store_true", help="dump mode resolution and frozen catalog")
    parser.add_argument("--route", action="store_true", help="route one warm-up problem by --name")
    parser.add_argument("--name", default="", help="JSONL problem name")
    parser.add_argument(
        "--typesafe",
        choices=ALLOWED_MODES,
        default=None,
        help="override LRA_TYPESAFE (default off)",
    )
    parser.add_argument("--official-track2", action="store_true", help="force official Track 2 off")
    parser.add_argument("--fixture", action="store_true", help="use CI fixture client; no live key")
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL path")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.plan:
        from jevops.outer import print_ok

        return print_ok(plan_view(mode=args.typesafe, official_track2=args.official_track2))
    if args.route:
        if not args.name:
            parser.error("--route requires --name")
        from jevops.outer import failed_check, print_json

        try:
            payload = route_named(
                args.name,
                mode=args.typesafe,
                official_track2=args.official_track2,
                fixture=args.fixture,
                path=args.jsonl,
            )
        except (TypesafeRouterError, lra_splice.SpliceError, lra_retrieve.RetrieveError) as exc:
            print_json(failed_check(exc, jev_generated_lean=False))
            return 1
        from jevops.outer import print_ok

        return print_ok(payload)
    if args.self_check or argv is None or argv == []:
        from jevops.outer import print_ok

        return print_ok(self_check(args.jsonl))
    parser.error("choose --self-check, --plan, or --route")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
