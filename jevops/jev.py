#!/usr/bin/env python3
"""TypeSafe Jev Choice / Score / Noul projectors and question fixtures.

Jev is a gate, not a generator. These helpers never produce Lean.
Implementations own question catalogs and hosted HTTP.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence


class JevError(ValueError):
    """Malformed Choice / Score / Noul payload."""


_KEEP_USAGE = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "completion_tokens",
    "prompt_tokens",
)


def redact(
    payload: Any,
    *,
    substrings: Sequence[str] = ("api_key",),
    exact: Sequence[str] = ("authorization", "token"),
    keep: Sequence[str] = _KEEP_USAGE,
    prefixes: Sequence[str] = ("apikey_",),
) -> Any:
    """Recursively redact secrets. Never a generated proof."""

    if isinstance(payload, Mapping):
        out: dict[Any, Any] = {}
        keep_set = set(keep)
        exact_set = set(exact)
        for key, value in payload.items():
            name = str(key).lower()
            if any(s in name for s in substrings) or (name in exact_set and name not in keep_set):
                out[key] = "[redacted]" if value else value
            else:
                out[key] = redact(value, substrings=substrings, exact=exact, keep=keep, prefixes=prefixes)
        return out
    if isinstance(payload, list):
        return [redact(item, substrings=substrings, exact=exact, keep=keep, prefixes=prefixes) for item in payload]
    if isinstance(payload, str) and any(payload.startswith(p) for p in prefixes):
        return "[redacted]"
    return payload


def usage_tokens(usage: Mapping[str, Any], *, default_in: int = 200) -> tuple[int, int]:
    inn = int(usage.get("input_tokens") or usage.get("prompt_tokens") or default_in)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return inn, out


def record_usage(
    ledger: Any,
    usage: Optional[Mapping[str, Any]] = None,
    *,
    model: str = "",
    default_in: int = 200,
    kind: str = "jev",
) -> tuple[int, int]:
    """Charge a ledger from a TypeSafe usage blob. No HTTP."""

    inn, out = usage_tokens(dict(usage or {}), default_in=default_in)
    if ledger is not None and hasattr(ledger, "record"):
        ledger.record(kind, input_tokens=inn, output_tokens=out, model=model)
    return inn, out


def intent_state(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    residuals: Optional[Mapping[str, Any]] = None,
    memory_view: Optional[Mapping[str, Any]] = None,
    window: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Compact AutoResearch/intent state. Does not generate Lean."""

    from jevops.pick import safe_holes

    state: dict[str, Any] = {
        "problem": {"name": record.get("name"), "source": record.get("source")},
        "n_tokens": analysis.get("n_tokens"),
        "counts": analysis.get("counts"),
        "n_mca_holes": analysis.get("n_mca_holes"),
        "safe_holes": safe_holes(analysis.get("mca_holes") or ()),
        "residuals": dict(residuals or {}),
        "memory": dict(memory_view or {}),
    }
    if window:
        state.update(dict(window))
    if extra:
        state.update(dict(extra))
    return state


def distill_row(
    *,
    schema: str,
    mode: str,
    problem: Mapping[str, Any],
    answers: Any,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Log (features, Jev answers). Never includes generated Lean."""

    out = {
        "schema": schema,
        "mode": mode,
        "features": {
            "name": problem.get("name"),
            "source": problem.get("source"),
            "n_toolchains": problem.get("n_toolchains"),
            "proof_length": problem.get("proof_length"),
            "num_lines": problem.get("num_lines"),
            "has_repo": problem.get("has_repo"),
        },
        "answers": answers,
        "jev_generated_lean": False,
        "score_is_rubric_index": True,
        "arena_score": None,
    }
    if extra:
        out.update(dict(extra))
    return out


def skipped(reason: str, **extra: Any) -> dict[str, Any]:
    """Fail-closed Jev skip payload. Never a generated proof."""

    out = {"skipped": True, "reason": str(reason)}
    out.update(extra)
    return out


@dataclass(frozen=True)
class RouteResult:
    skipped: bool
    reason: str
    mode: str
    official_track2: bool
    family: Optional[str] = None
    family_confidence: Optional[float] = None
    family_probs: Optional[dict[str, float]] = None
    hammer_before_llm: Optional[float] = None
    reference_already_tight: Optional[float] = None
    likely_shorter: Optional[float] = None
    likely_shorter_legend: Optional[dict[int, str]] = None
    likely_shorter_is_rubric_index: bool = True
    elab_risk: Optional[float] = None
    elab_risk_legend: Optional[dict[int, str]] = None
    version_fragile: Optional[float] = None
    putnam_aesop_plausible: Optional[float] = None
    calc_structure_worth_keeping: Optional[float] = None
    statement_in_proof_duplicated: Optional[float] = None
    uses_sorry_or_admit: Optional[float] = None
    neighbor_style_match: Optional[str] = None
    spend_llm: Optional[float] = None
    usage: Optional[dict[str, Any]] = None
    wall_ms: Optional[float] = None
    called_typesafe: bool = False
    used_fixture: bool = False
    model: str = ""
    jev_generated_lean: bool = False
    lean_text: None = None
    tactics: None = None
    proof_text: None = None
    arena_score: None = None
    api_key_redacted: bool = True
    score_is_rubric_index: bool = True
    additive_not_replacement: bool = True

    def as_dict(self) -> dict[str, Any]:
        return stringify_legend_keys(asdict(self))


def draft_rank_state(
    record: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    *,
    n: int = 20,
    statement_n: int = 700,
    head_n: int = 220,
    goal: str = "Prefer the shortest lake-valid draft. Do not write Lean.",
) -> dict[str, Any]:
    from jevops.outer import head_chars, head_seq

    rows = list(head_seq(drafts, n))
    criteria = {
        str(item.get("kind") or item.get("id") or index): (
            f"{item.get('generator')}; ops={item.get('ops')}; {len(str(item.get('tactics') or ''))} chars"
        )
        for index, item in enumerate(rows)
    }
    return {
        "criteria": criteria,
        "state": {
            "problem": {"name": record.get("name"), "source": record.get("source")},
            "statement": head_chars(record.get("statement") or "", statement_n),
            "goal": goal,
            "drafts": [
                {
                    "id": item.get("kind") or item.get("id"),
                    "ops": item.get("ops"),
                    "n_chars": len(str(item.get("tactics") or "")),
                    "head": head_chars(item.get("tactics") or "", head_n),
                }
                for item in rows
            ],
        },
    }


def skip_reason(
    *,
    enabled: bool,
    official: bool = False,
    key_ok: bool = True,
    available: bool = True,
    using_fixture: bool = False,
    require_key: bool = True,
) -> str:
    """Why a Jev client should no-op. Empty string means call."""

    if not enabled:
        return "official_track2_off" if official else "typesafe_off"
    if require_key and not key_ok and not using_fixture:
        return "no_key"
    if not using_fixture and not available:
        return "typesafe_inference_missing"
    return ""


def stringify_legend_keys(
    payload: Mapping[str, Any],
    keys: Sequence[str] = ("likely_shorter_legend", "elab_risk_legend"),
) -> dict[str, Any]:
    """JSON-safe legend maps (int keys → str). No Lean."""

    out = dict(payload)
    for key in keys:
        legend = out.get(key)
        if isinstance(legend, dict):
            out[key] = {str(k): v for k, v in legend.items()}
    return out


def catalog_kinds(questions: Mapping[str, Any]) -> dict[str, str]:
    """name → question kind for a catalog/plan view."""

    out: dict[str, str] = {}
    for name, question in dict(questions or {}).items():
        kind = getattr(question, "kind", None)
        if not kind:
            try:
                kind = question_kind(question)
            except Exception:
                kind = ""
        if kind:
            out[str(name)] = str(kind)
    return out


def keys_by_type(spec: Mapping[str, Mapping[str, Any]], kind: str) -> tuple[str, ...]:
    want = str(kind or "")
    return tuple(name for name, item in spec.items() if str((item or {}).get("type") or "") == want)


def deny_lean_keys(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Projectors never emit Lean text or Arena scores."""

    out = dict(payload)
    out.update({"lean_text": None, "tactics": None, "proof_text": None, "arena_score": None})
    return out


def list_field(record: Mapping[str, Any], key: str) -> list[Any]:
    """JSON-or-list record field. Fail closed to []."""

    raw = record.get(key)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return list(raw) if isinstance(raw, list) else []


def invoke_system_one(
    client: Any,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
) -> tuple[Any, float]:
    """Call client.system_one, honoring context managers. Returns (response, wall_ms)."""

    started = time.perf_counter()
    if hasattr(client, "__enter__"):
        with client as opened:
            response = opened.system_one(state, questions)
    else:
        response = client.system_one(state, questions)
    return response, (time.perf_counter() - started) * 1000.0


def env_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def env_flag(
    *,
    flag: bool = False,
    env: Optional[Mapping[str, str]] = None,
    truthy_keys: Sequence[str] = (),
    value_key: str = "",
    values: Sequence[str] = (),
) -> bool:
    """True if flag, a truthy env key, or value_key is in values."""

    if flag:
        return True
    source = env if env is not None else {}
    if any(env_truthy(source.get(key)) for key in truthy_keys):
        return True
    if value_key:
        return str(source.get(value_key) or "").strip().lower() in {str(v).lower() for v in values}
    return False


def any_key(env: Optional[Mapping[str, str]], names: Sequence[str]) -> bool:
    source = env if env is not None else {}
    return any(str(source.get(name) or "").strip() for name in names)


def resolve_mode(
    *,
    flag: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    env_key: str = "",
    default: str = "off",
    allowed: Sequence[str] = ("off",),
    closed: Optional[str] = None,
    closed_if: bool = False,
) -> str:
    """Fail closed to default/closed. Unknown values raise JevError."""

    if closed_if:
        return str(closed if closed is not None else default)
    raw = default if flag is None else flag
    if flag is None and env is not None and env_key:
        raw = env.get(env_key, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    mode = str(raw).strip().lower()
    if mode not in set(allowed):
        raise JevError(f"unknown mode {mode!r}; expected {tuple(allowed)}")
    return mode


def resolve_opt_in_mode(
    *,
    flag: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    official: bool = False,
    closed: str = "off",
    default: str = "off",
    allowed: Sequence[str] = ("off",),
    truthy_env: str = "",
    generator_env: str = "",
    default_generator: str = "",
    generator_aliases: Sequence[str] = (),
    mode_env: str = "",
    aliases: Optional[Mapping[str, str]] = None,
    error_cls: type[BaseException] = JevError,
    error_fmt: str = "unknown mode {mode!r}; expected {allowed}",
) -> str:
    """Opt-in mode: official stays closed; generator aliases map onto allowed modes."""

    from jevops.jev import env_truthy

    source = dict(env or {})
    if official:
        return str(closed)
    if flag is not None:
        raw = flag
    elif truthy_env and env_truthy(source.get(truthy_env)):
        raw = next((item for item in allowed if item != default), default)
    else:
        generator = str(source.get(generator_env, default_generator) or default_generator).strip().lower()
        if generator_env and generator in set(generator_aliases):
            raw = next((item for item in allowed if item != default), default)
        else:
            raw = source.get(mode_env, default) if mode_env else default
    if raw is None or str(raw).strip() == "":
        raw = default
    mode = str(raw).strip().lower()
    mapped = dict(aliases or {})
    mode = str(mapped.get(mode, mode))
    if mode not in set(allowed):
        raise error_cls(error_fmt.format(mode=mode, allowed=tuple(allowed)))
    return mode


def record_state(
    record: Mapping[str, Any],
    *,
    neighbors: Sequence[Mapping[str, Any]] = (),
    candidate: Any = None,
    header_chars: int = 500,
    neighbor_k: int = 4,
    proof_key: str = "src",
    truncate_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Compact problem state for Jev. Proof text is truncated, not generated."""

    header = record.get("header") if isinstance(record.get("header"), str) else ""
    version_info = record.get("version_info") if isinstance(record.get("version_info"), list) else []
    proof = str(record.get(proof_key) or "")
    if truncate_fn is not None:
        proof = truncate_fn(proof)
    return {
        "problem": {
            "name": record.get("name"),
            "source": record.get("source"),
            "n_toolchains": len(version_info),
            "proof_length": record.get("proof_length"),
            "num_lines": record.get("num_lines"),
            "has_repo": bool(record.get("url")),
            "header": header[: int(header_chars)],
        },
        "statement": record.get("statement"),
        "reference_proof": proof,
        "neighbors": list(neighbors)[: int(neighbor_k)],
        "candidate": candidate,
    }


def noul_value(answer: Any) -> float:
    if hasattr(answer, "noul"):
        return float(answer.noul)
    if isinstance(answer, Mapping) and "noul" in answer:
        return float(answer["noul"])
    raise JevError("noul answer missing .noul")


def choice_value(answer: Any) -> tuple[str, float, dict[str, float]]:
    choice = getattr(answer, "choice", None)
    confidence = getattr(answer, "confidence", None)
    probabilities = getattr(answer, "probabilities", None)
    if isinstance(answer, Mapping):
        choice = answer.get("choice") if choice is None else choice
        confidence = answer.get("confidence") if confidence is None else confidence
        probabilities = answer.get("probabilities") if probabilities is None else probabilities
    if choice is None:
        raise JevError("choice answer missing .choice")
    return str(choice), float(confidence or 0.0), dict(probabilities or {})


def score_value(
    answer: Any,
    *,
    n_levels: int,
    legend_fallback: Mapping[int, str],
) -> tuple[float, dict[int, str]]:
    score = getattr(answer, "score", None)
    legend = getattr(answer, "legend", None)
    if isinstance(answer, Mapping):
        score = answer.get("score") if score is None else score
        legend = answer.get("legend") if legend is None else legend
    if score is None:
        raise JevError("score answer missing .score")
    value = float(score)
    if value < 0 or value > max(n_levels - 1, 0):
        raise JevError(f"score rubric index {value} outside [0, {n_levels - 1}]")
    if isinstance(legend, Mapping):
        parsed = {int(key): str(item) for key, item in legend.items()}
    else:
        parsed = dict(legend_fallback)
    return value, parsed


@dataclass(frozen=True)
class CatalogQuestion:
    """Frozen question descriptor. Not an HTTP client."""

    kind: str
    instructions: str
    criteria: Any = None


@dataclass(frozen=True)
class FixtureChoice:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


@dataclass(frozen=True)
class FixtureNoul:
    noul: float


@dataclass(frozen=True)
class FixtureScore:
    score: float
    legend: Mapping[int, str]


@dataclass(frozen=True)
class FixtureResponse:
    choices: Mapping[str, FixtureChoice]
    nouls: Mapping[str, FixtureNoul]
    scores: Mapping[str, FixtureScore]
    usage: Mapping[str, Any]


def question_kind(question: Any) -> str:
    if isinstance(question, CatalogQuestion):
        return question.kind
    kind = getattr(question, "kind", None) or getattr(question, "type", None)
    if isinstance(kind, str) and kind:
        return kind.lower()
    name = type(question).__name__.lower()
    if "choice" in name:
        return "choice"
    if "noul" in name:
        return "noul"
    if "score" in name:
        return "score"
    if isinstance(question, Mapping):
        return str(question.get("type") or question.get("kind") or "")
    raise JevError(f"cannot classify question {type(question).__name__}")


def question_criteria(question: Any) -> Any:
    if isinstance(question, CatalogQuestion):
        return question.criteria
    criteria = getattr(question, "criteria", None)
    if criteria is not None:
        return criteria
    if isinstance(question, Mapping):
        return question.get("criteria")
    return None


def instantiate_questions(
    spec: Mapping[str, Mapping[str, Any]],
    *,
    choice: Optional[Callable[..., Any]] = None,
    noul: Optional[Callable[..., Any]] = None,
    score: Optional[Callable[..., Any]] = None,
    neighbor_names: Sequence[str] = (),
    neighbor_key: str = "neighbor_style_match",
) -> dict[str, Any]:
    """Build a question dict from a type/instructions/criteria spec."""

    packed: dict[str, Mapping[str, Any]] = dict(spec)
    if neighbor_names and neighbor_key in packed:
        neighbor_criteria = {"none": "Do not imitate a neighbor"}
        for neighbor in neighbor_names:
            neighbor_criteria[str(neighbor)] = f"Imitate neighbor {neighbor}"
        packed[neighbor_key] = {**dict(packed[neighbor_key]), "criteria": neighbor_criteria}
    choice_ctor = choice or (lambda **kwargs: CatalogQuestion(kind="choice", **kwargs))
    noul_ctor = noul or (lambda **kwargs: CatalogQuestion(kind="noul", **kwargs))
    score_ctor = score or (lambda **kwargs: CatalogQuestion(kind="score", **kwargs))
    questions: dict[str, Any] = {}
    for name, item in packed.items():
        kind = str(item["type"])
        instructions = str(item["instructions"])
        criteria = item.get("criteria")
        if kind == "choice":
            questions[name] = choice_ctor(instructions=instructions, criteria=criteria)
        elif kind == "noul":
            questions[name] = noul_ctor(instructions=instructions)
        elif kind == "score":
            questions[name] = score_ctor(instructions=instructions, criteria=list(criteria or []))
        else:
            raise JevError(f"unknown question type {kind} for {name}")
    return questions


def expand_questions(
    items: Sequence[Any],
    *,
    ctor: Any,
    name_fn: Any,
    instructions_fn: Any,
    criteria: Any,
    limit: int = 6,
    skip: Sequence[str] = (),
) -> dict[str, Any]:
    """Expand per-key Choice/Score/Noul questions. Does not call HTTP. No Lean."""

    out: dict[str, Any] = {}
    banned = {str(s) for s in skip}
    for item in list(items)[: int(limit)]:
        raw = item[0] if isinstance(item, (tuple, list)) and item else item
        if str(raw) in banned or not str(raw):
            continue
        key = str(name_fn(item))
        if not key:
            continue
        out[key] = ctor(instructions=instructions_fn(item), criteria=criteria)
    return out


def truncate_middle(
    src: str,
    *,
    head_lines: int = 80,
    tail_lines: int = 80,
    char_budget: int = 150_000,
    marker: str = "# truncated middle",
) -> str:
    """Keep head/tail of a long text; hash the dropped middle. No Lean."""

    text = str(src)
    if len(text) <= char_budget:
        return text
    lines = text.splitlines()
    if len(lines) <= head_lines + tail_lines:
        return text[:char_budget]
    head = "\n".join(lines[:head_lines])
    tail = "\n".join(lines[-tail_lines:])
    middle = "\n".join(lines[head_lines:-tail_lines]).encode("utf-8")
    digest = hashlib.sha256(middle).hexdigest()
    skipped = len(lines) - head_lines - tail_lines
    return f"{head}\n\n{marker} sha256:{digest} lines={skipped}\n\n{tail}"


def noul_attr(nouls: Mapping[str, Any], key: str) -> float:
    return float(getattr((nouls or {}).get(key), "noul", 0.0) or 0.0)


def choice_head(choices: Mapping[str, Any], key: str) -> tuple[Any, dict[str, float], float, Any]:
    """(answer, probabilities, confidence, choice). Missing key is empty."""

    ans = (choices or {}).get(key)
    return (
        ans,
        dict(getattr(ans, "probabilities", None) or {}),
        float(getattr(ans, "confidence", None) or 0.0),
        getattr(ans, "choice", None),
    )


def unpack_response(response: Any) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Split a System One payload into choices/nouls/scores/usage."""

    choices = getattr(response, "choices", None) or {}
    nouls = getattr(response, "nouls", None) or {}
    scores = getattr(response, "scores", None) or {}
    usage = dict(getattr(response, "usage", None) or {})
    return choices, nouls, scores, usage


def project_answers(
    response: Any,
    *,
    noul_keys: Sequence[str] = (),
    choice_aliases: Optional[Mapping[str, str]] = None,
    score_specs: Optional[Mapping[str, Mapping[str, Any]]] = None,
    optional_choices: Sequence[str] = (),
) -> dict[str, Any]:
    """Project Choice/Score/Noul answers. Score stays a rubric index. No Lean."""

    choices, nouls, scores, usage = unpack_response(response)
    out: dict[str, Any] = {"usage": usage, "jev_generated_lean": False}
    for src, dest in dict(choice_aliases or {}).items():
        if src not in choices and src in set(optional_choices):
            out[dest] = None
            continue
        choice, conf, probs = choice_value(choices[src])
        out[dest] = choice
        if dest == "family":
            out["family_confidence"] = conf
            out["family_probs"] = probs
    for key in noul_keys:
        out[str(key)] = noul_value(nouls[key])
    for src, spec in dict(score_specs or {}).items():
        dest = str(spec.get("dest") or src)
        value, legend = score_value(
            scores[src],
            n_levels=int(spec.get("n_levels") or 3),
            legend_fallback=spec.get("legend") or {},
        )
        out[dest] = value
        out[f"{dest}_legend"] = legend
        if spec.get("rubric"):
            out[f"{dest}_is_rubric_index"] = True
    return out


@dataclass
class FixtureClient:
    """CI fixture System One stand-in. Never POSTs."""

    model: str = "jev-latest"
    answers: Mapping[str, Any] = field(default_factory=dict)

    def __enter__(self) -> "FixtureClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def system_one(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> FixtureResponse:
        del state
        choices: dict[str, FixtureChoice] = {}
        nouls: dict[str, FixtureNoul] = {}
        scores: dict[str, FixtureScore] = {}
        for name, question in questions.items():
            kind = question_kind(question)
            override = self.answers.get(name)
            if kind == "choice":
                criteria = question_criteria(question)
                keys = list(criteria.keys()) if isinstance(criteria, Mapping) else ["none"]
                picked = str(override if override is not None else (keys[0] if keys else "none"))
                if picked not in keys:
                    picked = keys[0] if keys else "none"
                conf = 0.72 if picked != "none" else 0.64
                mass = (1.0 - conf) / max(len(keys) - 1, 1)
                probs = {key: (conf if key == picked else mass) for key in keys}
                choices[name] = FixtureChoice(choice=picked, confidence=conf, probabilities=probs)
            elif kind == "noul":
                value = 0.25 if override is None else float(override)
                nouls[name] = FixtureNoul(noul=value)
            elif kind == "score":
                criteria = question_criteria(question)
                n_levels = len(criteria) if isinstance(criteria, (list, tuple)) else 3
                legend = (
                    {index: str(item) for index, item in enumerate(criteria)}
                    if isinstance(criteria, (list, tuple))
                    else {0: "0", 1: "1", 2: "2"}
                )
                value = 0.0 if override is None else float(override)
                if value < 0 or value > max(n_levels - 1, 0):
                    raise JevError(f"{name}: rubric index {value} outside [0, {n_levels - 1}]")
                scores[name] = FixtureScore(score=value, legend=legend)
            else:
                raise JevError(f"unknown question kind for {name}")
        return FixtureResponse(
            choices=choices,
            nouls=nouls,
            scores=scores,
            usage={"input_tokens": 0, "output_tokens": 0, "fixture": True, "model": self.model},
        )


def tree_choice_questions(
    tree: Mapping[str, Mapping[str, str]],
    *,
    Choice: Any,
    family_instructions: str,
    leaf_instructions: str = (
        "Inside the {fam} family, which leaf edit is most likely to lake-compile "
        "and use fewer tokens? Do not write Lean."
    ),
) -> dict[str, Any]:
    """Family Choice plus a leaf Choice per sibling set. Does not write Lean."""

    questions: dict[str, Any] = {
        "family": Choice(
            instructions=family_instructions,
            criteria={fam: "Edit family: " + "; ".join(kids) for fam, kids in dict(tree or {}).items()},
        )
    }
    for fam, kids in dict(tree or {}).items():
        if len(kids) <= 1:
            continue
        questions[f"leaf_{fam}"] = Choice(
            instructions=str(leaf_instructions).format(fam=fam),
            criteria=dict(kids),
        )
    return questions


def require_choice_cap(
    n: int,
    cap: int,
    *,
    error_cls: Any = RuntimeError,
    fmt: str = "draft catalog {n} exceeds Choice option cap {cap}",
) -> None:
    if int(n) > int(cap):
        raise error_cls(fmt.format(n=int(n), cap=int(cap)))


def draft_criteria(
    drafts: Sequence[Any],
    *,
    id_attr: str = "draft_id",
) -> dict[str, str]:
    """id → family/ops/chars blurb. Does not write Lean."""

    from jevops.outer import field_of

    out: dict[str, str] = {}
    for item in drafts or ():
        hid = str(field_of(item, id_attr, "id", default="") or "")
        family = str(field_of(item, "family", default="") or "")
        ops = list(field_of(item, "ops", default=()) or ())
        n_chars = field_of(item, "n_chars", default=None)
        if n_chars in (None, ""):
            n_chars = len(str(field_of(item, "tactics", default="") or ""))
        out[hid] = f"{family}; ops={','.join(str(op) for op in ops)}; {n_chars} chars"
    return out


def fanout_problem_state(
    record: Mapping[str, Any],
    *,
    statement_n: int = 480,
    extra: Optional[Mapping[str, Any]] = None,
    problem: Optional[Mapping[str, Any]] = None,
    problem_keys: Sequence[str] = ("name", "source"),
) -> dict[str, Any]:
    """Compact fan-out state. Proof text is truncated, not generated."""

    from jevops.outer import head_chars

    row = dict(problem) if problem is not None else {key: record.get(key) for key in problem_keys}
    state: dict[str, Any] = {
        "problem": row,
        "statement": head_chars(record.get("statement") or "", statement_n),
    }
    if extra:
        state.update(dict(extra))
    return state


def choice_questions(
    *,
    Choice: Any,
    Noul: Any = None,
    Score: Any = None,
    criteria: Optional[Mapping[str, str]] = None,
    best_key: str = "best_first_draft",
    best_instructions: str = "",
    nouls: Optional[Mapping[str, str]] = None,
    scores: Optional[Mapping[str, tuple[str, Sequence[str]]]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build Choice/Noul/Score questions. Does not call HTTP. No Lean."""

    out: dict[str, Any] = {}
    if extra:
        out.update(dict(extra))
    if best_instructions:
        out[best_key] = Choice(instructions=best_instructions, criteria=dict(criteria or {}))
    for name, instructions in dict(nouls or {}).items():
        out[str(name)] = Noul(instructions=instructions)
    for name, packed in dict(scores or {}).items():
        instructions, legend = packed
        out[str(name)] = Score(instructions=instructions, criteria=list(legend or []))
    return out


def hole_criteria(holes: Sequence[Any], *, head_n: int = 80) -> dict[str, str]:
    from jevops.outer import field_of, head_chars

    out: dict[str, str] = {}
    for hole in holes or ():
        hid = str(field_of(hole, "hole_id", "id", default="") or "")
        family = str(field_of(hole, "family", default="") or "")
        original = str(field_of(hole, "original", default="") or "")
        out[hid] = f"{family}; {len(original.split())} words; {head_chars(original.strip(), head_n)}"
    return out


def hole_round_state(
    record: Mapping[str, Any],
    holes: Sequence[Any],
    history: Sequence[Mapping[str, Any]],
    keep_tokens: int,
    *,
    history_n: int = 8,
    goal: str = "Pick the MCA hole whose deletion is most likely to lake-compile AND cut tokens. Do not write Lean.",
) -> dict[str, Any]:
    from jevops.outer import field_of, tail_seq

    return {
        "problem": record.get("name"),
        "keep_tokens": keep_tokens,
        "history": tail_seq(history, history_n),
        "holes": [
            {
                "id": field_of(hole, "hole_id", "id", default=""),
                "family": field_of(hole, "family", default=""),
                "n_words": len(str(field_of(hole, "original", default="") or "").split()),
            }
            for hole in holes or ()
        ],
        "goal": goal,
    }


def pack_choice_round(
    result: Any,
    *,
    choice_key: str,
    noul_key: str = "likely_compiles",
    score_key: str = "likely_token_cut",
    wall_ms: Optional[float] = None,
) -> dict[str, Any]:
    """Project one Choice + optional Noul/Score. Never includes generated Lean."""

    choices, nouls, scores, usage = unpack_response(result)
    choice = choices.get(choice_key)
    out: dict[str, Any] = {
        "skipped": False,
        "choice": getattr(choice, "choice", None),
        "confidence": getattr(choice, "confidence", None),
        "probabilities": dict(getattr(choice, "probabilities", None) or {}),
        "usage": usage,
        "model": getattr(result, "model", None),
        "jev_generated_lean": False,
    }
    if noul_key:
        out[noul_key] = getattr((nouls or {}).get(noul_key), "noul", None)
    if score_key:
        out[score_key] = getattr((scores or {}).get(score_key), "score", None)
    if wall_ms is not None:
        out["wall_ms"] = wall_ms
    return out


def proposal_rank_state(
    record: Mapping[str, Any],
    current: str,
    criteria: Mapping[str, str],
    *,
    tokens: int,
    head_n: int = 400,
    goal: str = "Pick the MCMC proposal most likely to lake-compile AND use fewer tokens. Do not write Lean.",
) -> dict[str, Any]:
    from jevops.outer import head_chars

    return {
        "problem": record.get("name"),
        "current_tokens": int(tokens),
        "current_head": head_chars(current, head_n),
        "goal": goal,
        "proposals": [{"id": key, "desc": val} for key, val in dict(criteria).items()],
    }


def pack_ranked_pick(
    result: Any,
    *,
    choice_key: str,
    n: int,
    prefix: str = "p",
    noul_key: str = "likely_compiles",
    score_key: str = "likely_shorter",
    pick_default: str = "p0",
) -> dict[str, Any]:
    """Project a numbered Choice plus order. Never includes generated Lean."""

    from jevops.search import index_order

    packed = pack_choice_round(result, choice_key=choice_key, noul_key=noul_key, score_key=score_key)
    pick = str(packed.get("choice") or pick_default)
    packed["pick"] = pick
    packed["order"] = index_order(int(n), packed.get("probabilities") or {}, prefix=prefix, pick=pick)
    return packed


def route_result_from_answers(
    extracted: Mapping[str, Any],
    *,
    mode: str,
    official_track2: bool,
    wall_ms: float,
    used_fixture: bool,
    model: str,
    result_cls: Any = None,
) -> Any:
    """Build a RouteResult from projected answers. Never includes generated Lean."""

    cls = result_cls or RouteResult
    return cls(
        skipped=False,
        reason="routed",
        mode=mode,
        official_track2=official_track2,
        family=extracted.get("family"),
        family_confidence=extracted.get("family_confidence"),
        family_probs=extracted.get("family_probs"),
        hammer_before_llm=extracted.get("hammer_before_llm"),
        reference_already_tight=extracted.get("reference_already_tight"),
        likely_shorter=extracted.get("likely_shorter"),
        likely_shorter_legend=extracted.get("likely_shorter_legend"),
        elab_risk=extracted.get("elab_risk"),
        elab_risk_legend=extracted.get("elab_risk_legend"),
        version_fragile=extracted.get("version_fragile"),
        putnam_aesop_plausible=extracted.get("putnam_aesop_plausible"),
        calc_structure_worth_keeping=extracted.get("calc_structure_worth_keeping"),
        statement_in_proof_duplicated=extracted.get("statement_in_proof_duplicated"),
        uses_sorry_or_admit=extracted.get("uses_sorry_or_admit"),
        neighbor_style_match=extracted.get("neighbor_style_match"),
        spend_llm=extracted.get("spend_llm"),
        usage=extracted.get("usage"),
        wall_ms=wall_ms,
        called_typesafe=True,
        used_fixture=used_fixture,
        model=model,
        jev_generated_lean=False,
    )


def pack_best_draft(
    result: Any,
    *,
    choice_key: str = "best_first_draft",
    wall_ms: Optional[float] = None,
) -> dict[str, Any]:
    """Project a best-draft Choice. Never includes generated Lean."""

    packed = pack_choice_round(result, choice_key=choice_key, noul_key="", score_key="", wall_ms=wall_ms)
    packed["best_first_draft"] = packed.get("choice")
    packed["best_confidence"] = packed.get("confidence")
    packed["top"] = list(dict(packed.get("probabilities") or {}))
    packed["reason"] = "routed"
    packed["arena_score"] = None
    return packed


def overlay_route_payload(
    result: Mapping[str, Any],
    *,
    name: str,
    source: Any,
    digest: str,
    n_neighbors: int,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Named-route overlay. Jev still does not generate Lean."""

    out = dict(result or {})
    out.update(
        {
            "ok": True,
            "name": name,
            "source": source,
            "warmup_jsonl_sha256": digest,
            "n_neighbors": int(n_neighbors),
            "imports_typesafe_inference": True,
            "imports_typesafe_sdk": False,
            "jev_generates_lean": False,
            "score_is_rubric_index": True,
            "official_track2_stays_off": True,
        }
    )
    if extra:
        out.update(dict(extra))
    return out


def project_live_answers(
    result: Any,
    *,
    choice_map: Optional[Mapping[str, str]] = None,
    noul_map: Optional[Mapping[str, str]] = None,
    score_map: Optional[Mapping[str, str]] = None,
    best_key: str = "best_first_draft",
) -> dict[str, Any]:
    """Project Choice/Noul/Score answers into a live payload. No Lean."""

    choices, nouls, scores, usage = unpack_response(result)
    out: dict[str, Any] = {
        "live": True,
        "model": getattr(result, "model", None),
        "usage": usage,
        "jev_generated_lean": False,
    }
    for src, dest in dict(choice_map or {}).items():
        ans = choices.get(src)
        out[dest] = getattr(ans, "choice", None)
        if dest == best_key or src == best_key:
            out["best_confidence"] = getattr(ans, "confidence", None)
            out["_best"] = ans
    for src, dest in dict(noul_map or {}).items():
        out[dest] = getattr((nouls or {}).get(src), "noul", None)
    for src, dest in dict(score_map or {}).items():
        out[dest] = getattr((scores or {}).get(src), "score", None)
    return out


def rank_live_choice_row(
    result: Any,
    wall_ms: float,
    *,
    rank_fn: Callable[[Mapping[str, Any], Sequence[Any]], Any],
    drafts: Sequence[Any],
    choice_map: Optional[Mapping[str, str]] = None,
    noul_map: Optional[Mapping[str, str]] = None,
    score_map: Optional[Mapping[str, str]] = None,
    best_key: str = "best_first_draft",
) -> dict[str, Any]:
    """Project a live Choice/Noul/Score round and attach ranked ``top``."""

    live_row = project_live_answers(
        result,
        choice_map=choice_map,
        noul_map=noul_map,
        score_map=score_map,
        best_key=best_key,
    )
    best = live_row.pop("_best", None)
    probabilities = dict(getattr(best, "probabilities", None) or {})
    live_row["wall_ms"] = wall_ms
    live_row["top"] = rank_fn(probabilities, drafts)
    return live_row


def hosted_run_payload(
    *,
    name: str,
    source: Any,
    digest: str,
    identity: Mapping[str, Any],
    text: str,
    jev_route: Mapping[str, Any],
    ledger: Mapping[str, Any],
    wall_ms: float,
    requested_provider: str,
    requested_model: str,
    hardware_class: str,
    prototype_hardware: str,
    protocol: str,
    pr: str,
    track: str,
    labs_retire_date: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops.outer import head_chars

    out: dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "schema": "lra-track1-mistral-leanstral/v1",
        "protocol": protocol,
        "pr": pr,
        "track": track,
        "name": name,
        "source": source,
        "warmup_jsonl_sha256": digest,
        "requested_provider": requested_provider,
        "requested_model": requested_model,
        "identity": dict(identity),
        "hardware_class": hardware_class,
        "prototype_hardware_class": prototype_hardware,
        "used_prototype_endpoint": False,
        "labs_retire_date": labs_retire_date,
        "text": text,
        "text_head": head_chars(text, 400),
        "n_chars": len(text),
        "jev_route": dict(jev_route),
        "ledger": dict(ledger),
        "called_mistral": True,
        "called_jev": True,
        "called_docker0": False,
        "lock_ex": False,
        "llama_server_started": False,
        "official_track2": False,
        "contaminates_track2": False,
        "arena_score": None,
        "api_key_present_in_record": False,
        "wall_ms": wall_ms,
    }
    if extra:
        out.update(dict(extra))
    return out


def canary_live_payload(
    *,
    digest: str,
    seed: int,
    k: int,
    n_records: int,
    landscape: Sequence[Mapping[str, Any]],
    model: Mapping[str, Any],
    extra_139: Any,
    canaries: Sequence[Any],
    lake: Sequence[Any],
    gaps: Any,
    mem_path: Any,
    memory: Any,
    nca_status: Mapping[str, Any],
    ledger: Any,
) -> dict[str, Any]:
    from jevops.outer import closed_evidence, head_seq, landscape_rows, utc_stamp

    return {
        "schema": "lra-random-canary/v1",
        "observed_at": utc_stamp(),
        "seed": int(seed),
        "k": int(k),
        "warmup_jsonl_sha256": digest,
        "n_records": int(n_records),
        "n_tag_cells": sum(int(item.get("n_tags") or 0) for item in landscape or ()),
        "pca": {
            "explained_ratio": head_seq((model or {}).get("explained_ratio"), 6),
            "principal0": ((model or {}).get("principal") or [{}])[0].get("loadings"),
        },
        "landscape": landscape_rows(landscape),
        "inits_139": extra_139,
        "canaries": list(canaries or ()),
        "lake": list(lake or ()),
        "skill_analysis": gaps,
        "memory_path": str(mem_path),
        "memory": memory,
        "nca_status": dict(nca_status or {}),
        **closed_evidence(),
        "ledger": ledger.as_dict() if hasattr(ledger, "as_dict") else {"jev_calls": getattr(ledger, "jev_calls", 0)},
    }


def prune_state(
    record: Mapping[str, Any],
    prefix: str,
    pack: Mapping[str, Any],
    criteria: Mapping[str, str],
    *,
    prefix_n: int = 600,
    skeleton_n: int = 500,
    goal: str = "Pick the next Lean tactic line most likely to yield a shorter lake-valid proof.",
) -> dict[str, Any]:
    """Beam-prune state. Jev still does not write Lean."""

    from jevops.outer import head_chars, tail_chars

    return {
        "problem": {"name": record.get("name")},
        "prefix_tail": tail_chars(prefix, prefix_n),
        "pca_skeleton_head": head_chars(pack.get("pca_skeleton_head") or "", skeleton_n),
        "pca_case_tags": pack.get("pca_case_tags"),
        "missing_cases": pack.get("missing_cases"),
        "empty_arms": pack.get("empty_arms"),
        "unfinished_arms": pack.get("unfinished_arms"),
        "next_original": pack.get("next_original"),
        "earliest_unfinished": pack.get("earliest_unfinished"),
        "open_case": pack.get("open_case"),
        "mca_holes": pack.get("mca_holes"),
        "n_have_original": pack.get("n_have"),
        "goal": goal,
        "candidates": dict(criteria),
    }


def pack_prune(
    *,
    skipped: bool,
    reason: str,
    best: Any,
    kept: Sequence[Any],
    confidence: Any = None,
    usage: Any = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Prune result. Never includes generated Lean. Not an Arena score."""

    out: dict[str, Any] = {
        "skipped": bool(skipped),
        "reason": reason,
        "best": best,
        "kept": list(kept),
        "confidence": confidence,
        "usage": usage,
        "jev_generated_lean": False,
        "arena_score": None,
    }
    if extra:
        out.update(dict(extra))
    return out


def rank_prune_kept(
    criteria: Mapping[str, str],
    probs: Mapping[str, Any],
    pick_id: str,
    unique: Sequence[str],
    keep: int,
) -> list[str]:
    """Pin the Choice, then rank remaining ids. Empty keep falls back to unique[:keep]."""

    from jevops.search import pin_then_rank

    ranked_ids = pin_then_rank(
        list(criteria.keys()),
        dict(probs or {}),
        first=pick_id if pick_id in criteria else None,
    )
    kept = [criteria[key] for key in ranked_ids if key in criteria][: int(keep)]
    if not kept:
        kept = list(unique)[: int(keep)]
    return kept


def pack_rank_catalog(
    record: Mapping[str, Any],
    *,
    drafts: Sequence[Any],
    families: Sequence[Mapping[str, Any]],
    features: Mapping[str, Any],
    live: bool = False,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """PCA/MCA catalog payload. Live TypeSafe answers overlay later. No Lean."""

    draft_ids = [
        getattr(item, "draft_id", None) or (item.get("draft_id") if isinstance(item, Mapping) else None)
        for item in drafts
    ]
    out: dict[str, Any] = {
        "name": record.get("name"),
        "source": record.get("source"),
        "n_drafts": len(list(drafts)),
        "families": [str(item.get("family") or "") for item in families],
        "amenable": list(families),
        "features": dict(features),
        "draft_ids": draft_ids,
        "jev_generated_lean": False,
        "arena_score": None,
        "live": bool(live),
    }
    if extra:
        out.update(dict(extra))
    return out


def typesafe_load_payload(
    *,
    available: bool,
    error: str = "",
    path: str = "",
    exists: bool = False,
    Choice: Any = None,
    Noul: Any = None,
    Score: Any = None,
    TypeSafeClient: Any = None,
    typesafe_configured: Any = None,
) -> dict[str, Any]:
    """In-tree TypeSafe load view. Never typesafe-sdk. Never writes Lean."""

    return {
        "available": bool(available),
        "error": error,
        "path": path,
        "exists": bool(exists),
        "Choice": Choice,
        "Noul": Noul,
        "Score": Score,
        "TypeSafeClient": TypeSafeClient,
        "typesafe_configured": typesafe_configured,
    }


def noul_questions(
    spec: Mapping[str, Sequence[Any]],
    Noul: Any,
) -> dict[str, Any]:
    """Build Noul questions from (instructions, true, false) rows. Catalogs stay in the consumer."""

    return {
        name: Noul(
            instructions=row[0],
            criteria={"true": row[1], "false": row[2]},
        )
        for name, row in dict(spec or {}).items()
    }


def pack_plan_view(**fields: Any) -> dict[str, Any]:
    """TypeSafe plan overlay. Catalog strings stay in the consumer."""

    out = dict(fields)
    out.setdefault("ok", True)
    out["arena_score"] = None
    out["compiled"] = False
    out["llama_server_started"] = False
    return out


def rank_catalog_or_live(
    record: Mapping[str, Any],
    *,
    drafts: Sequence[Any],
    families: Sequence[Mapping[str, Any]],
    features: Mapping[str, Any],
    live: bool,
    extra: Optional[Mapping[str, Any]] = None,
    catalog_fn: Optional[Callable[[], Any]] = None,
    pin_fn: Optional[Callable[[], Any]] = None,
    configured_fn: Optional[Callable[[], bool]] = None,
    invoke_fn: Optional[Callable[[], tuple[Any, float]]] = None,
    project_fn: Optional[Callable[[Any, float], Mapping[str, Any]]] = None,
    redact_fn: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    missing_key: str = "TYPESAFE_API_KEY is not set",
) -> dict[str, Any]:
    """Catalog payload, or live TypeSafe overlay. Jev still does not write Lean."""

    payload = pack_rank_catalog(
        record,
        drafts=drafts,
        families=families,
        features=features,
        live=False,
        extra=extra,
    )
    if not live:
        return payload
    if pin_fn is not None:
        pin_fn()
    if configured_fn is not None and not configured_fn():
        payload["live"] = False
        payload["error"] = missing_key
        if catalog_fn is not None:
            payload["catalog"] = catalog_fn()
        return payload
    if invoke_fn is None or project_fn is None:
        payload["live"] = False
        payload["error"] = "live ranking is not wired"
        return payload
    result, wall_ms = invoke_fn()
    payload.update(dict(project_fn(result, wall_ms) or {}))
    return redact_fn(payload) if redact_fn is not None else payload


def invoke_then_project(
    *,
    invoke_fn: Callable[[], tuple[Any, float]],
    project_fn: Callable[..., Any],
    record_fn: Optional[Callable[..., Any]] = None,
    unpack_fn: Optional[Callable[[Any], tuple[Any, Any, Any, Any]]] = None,
    model: str = "",
) -> Any:
    """Invoke TypeSafe, optionally unpack, then project. Jev still does not write Lean."""

    result, wall_ms = invoke_fn()
    usage = dict(getattr(result, "usage", None) or {})
    if record_fn is not None:
        record_fn(usage, model=model)
    if unpack_fn is None:
        return project_fn(result, wall_ms)
    choices, nouls, scores, unpacked = unpack_fn(result)
    return project_fn(result, wall_ms, choices, nouls, scores, unpacked or usage)


def route_or_skip(
    *,
    enabled: bool,
    official: bool,
    key_ok: bool,
    available: bool,
    using_fixture: bool,
    require_key: bool,
    skip_fn: Callable[[str], Any],
    invoke_fn: Callable[[], tuple[Any, float]],
    project_fn: Callable[[Any, float], Any],
) -> Any:
    """Skip when disabled/no key, else invoke and project. Catalogs stay in the consumer."""

    reason = skip_reason(
        enabled=enabled,
        official=official,
        key_ok=key_ok,
        available=available,
        using_fixture=using_fixture,
        require_key=require_key,
    )
    if reason:
        return skip_fn(reason)
    result, wall_ms = invoke_fn()
    return project_fn(result, wall_ms)


def complete_prune(
    *,
    invoke_fn: Callable[[], tuple[Any, float]],
    skip_fn: Callable[[BaseException], Mapping[str, Any]],
    unpack_fn: Callable[[Any], tuple[Any, Any, Any, Any]],
    record_fn: Callable[[Any], Any],
    rank_fn: Callable[..., Sequence[str]],
    pack_fn: Callable[..., Mapping[str, Any]],
    criteria: Mapping[str, str],
    unique: Sequence[str],
    keep: int,
) -> dict[str, Any]:
    """Invoke prune Choice, charge ledger, rank kept lines. Catalogs stay in the consumer."""

    try:
        result, _wall = invoke_fn()
    except Exception as exc:  # noqa: BLE001 — prune must fail closed to greedy
        return dict(skip_fn(exc))
    choices, _nouls, _scores, usage = unpack_fn(result)
    line = record_fn(usage)
    best = (choices or {}).get("next_line")
    pick_id = str(getattr(best, "choice", None) or "c0")
    probs = dict(getattr(best, "probabilities", None) or {})
    kept = rank_fn(criteria, probs, pick_id, unique, keep)
    skipped = bool(getattr(line, "skipped", False))
    return dict(
        pack_fn(
            skipped=skipped,
            reason=(getattr(line, "reason", None) if skipped else "routed"),
            best=criteria.get(pick_id),
            kept=kept,
            confidence=getattr(best, "confidence", None),
            usage=usage,
        )
    )


def featurize_or_skip(
    *,
    invoke_fn: Callable[[], tuple[Any, float]],
    skip_fn: Callable[[BaseException], Mapping[str, Any]],
    unpack_fn: Callable[[Any], tuple[Any, Any, Any, Any]],
    record_fn: Callable[[Any], Any],
    feature_names: Sequence[str],
    weights: Mapping[str, float],
    signed_dot_fn: Callable[..., float],
    penalty: float,
) -> dict[str, Any]:
    """Score an MCMC edit from TypeSafe Noul features. Jev does not write Lean."""

    try:
        result, _wall = invoke_fn()
    except Exception as exc:  # noqa: BLE001
        return dict(skip_fn(exc))
    _choices, nouls, _scores, usage = unpack_fn(result)
    record_fn(usage)
    features: dict[str, float] = {}
    for name in feature_names:
        got = (nouls or {}).get(name)
        features[str(name)] = float(getattr(got, "noul", 0.0) or 0.0)
    return {
        "skipped": False,
        "score": float(signed_dot_fn(features, weights, penalty=penalty, default_w=0.5)),
        "features": features,
        "jev_generated_lean": False,
    }


def complete_choice_round(
    *,
    configured: bool,
    criteria: Mapping[str, Any],
    invoke_fn: Callable[[], tuple[Any, float]],
    pack_fn: Callable[..., Mapping[str, Any]],
    redact_fn: Callable[[Mapping[str, Any]], Any],
    skip_fn: Callable[..., Mapping[str, Any]],
    empty_reason: str = "no_holes",
    no_key_reason: str = "no_key",
    skip_extra: Optional[Mapping[str, Any]] = None,
    pack_kwargs: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Skip or invoke a Choice round. Question catalogs stay in the consumer."""

    extra = dict(skip_extra or {})
    if not configured:
        return dict(skip_fn(no_key_reason, **extra))
    if not criteria:
        return dict(skip_fn(empty_reason, **extra))
    result, wall_ms = invoke_fn()
    packed = pack_fn(result, wall_ms=wall_ms, **dict(pack_kwargs or {}))
    return redact_fn(packed)


def rank_proposals_or_skip(
    *,
    proposals: Sequence[Any],
    load_fn: Callable[[], Any],
    skip_fn: Callable[..., Mapping[str, Any]],
    invoke_fn: Callable[[Any], tuple[Any, float]],
    pack_fn: Callable[..., Mapping[str, Any]],
    record_fn: Callable[[Any], Any],
    choice_key: str = "next_edit",
    noul_key: str = "likely_compiles",
    score_key: str = "likely_shorter",
) -> dict[str, Any]:
    """Rank MCMC proposals. Catalogs stay in the consumer. Jev does not write Lean."""

    rows = list(proposals or ())
    if not rows:
        return dict(skip_fn("no_proposals", order=[]))
    module = load_fn()
    if module is None:
        return dict(skip_fn("no_key", order=list(range(len(rows)))))
    try:
        result, _wall = invoke_fn(module)
    except Exception as exc:  # noqa: BLE001
        return dict(skip_fn(exc, order=list(range(len(rows)))))
    record_fn(result)
    return dict(
        pack_fn(
            result,
            choice_key=choice_key,
            n=len(rows),
            noul_key=noul_key,
            score_key=score_key,
        )
    )


def pack_fill_rank(
    result: Any,
    wall_ms: float,
    *,
    schedule_fn: Callable[..., Mapping[str, Any]],
    usage: Any = None,
) -> dict[str, Any]:
    """Project a masked-fill Choice plus CFG schedule. Never includes generated Lean."""

    packed = unpack_response(result)
    choices, nouls, scores, unpacked = packed
    usage = usage if usage is not None else unpacked
    best = (choices or {}).get("best_fill")
    cfg_answer = (scores or {}).get("cfg_mask")
    noul_answer = (nouls or {}).get("prefer_few_shot")
    cfg_score = getattr(cfg_answer, "score", None)
    return {
        "skipped": False,
        "best_fill": getattr(best, "choice", None),
        "confidence": getattr(best, "confidence", None),
        "probabilities": dict(getattr(best, "probabilities", None) or {}),
        "cfg_score": cfg_score,
        "cfg_schedule": schedule_fn(cfg_score if cfg_score is not None else 0),
        "prefer_few_shot_noul": getattr(noul_answer, "noul", None),
        "usage": usage,
        "wall_ms": wall_ms,
        "jev_generated_lean": False,
        "arena_score": None,
    }


def pack_cfg_score(
    result: Any,
    wall_ms: float,
    *,
    table: Sequence[Mapping[str, Any]],
    schedule_fn: Callable[..., Mapping[str, Any]],
    one_hole: bool,
    eligible: Any,
    usage: Any = None,
) -> dict[str, Any]:
    """Project CFG Score + schedule Choice. Catalogs stay in the consumer."""

    choices, _nouls, scores, unpacked = unpack_response(result)
    usage = usage if usage is not None else unpacked
    cfg_answer = (scores or {}).get("cfg_mask")
    choice = (choices or {}).get("best_schedule")
    cfg_score = getattr(cfg_answer, "score", None)
    picked = getattr(choice, "choice", None)
    schedule = next((dict(item) for item in table if item.get("id") == picked), None)
    if schedule is None:
        schedule = dict(schedule_fn(cfg_score if cfg_score is not None else 0, one_hole=one_hole) or {})
    return {
        "skipped": False,
        "one_hole": bool(one_hole),
        "cfg_score": cfg_score,
        "cfg_confidence": getattr(cfg_answer, "confidence", None),
        "best_schedule": picked,
        "schedule_probabilities": dict(getattr(choice, "probabilities", None) or {}),
        "cfg_schedule": schedule,
        "eligible_spans": eligible,
        "usage": usage,
        "wall_ms": wall_ms,
        "jev_generated_lean": False,
        "arena_score": None,
    }


def questions_from_specs(
    specs: Sequence[Any],
    *,
    noul_ctor: Callable[..., Any],
    score_ctor: Callable[..., Any],
    score_criteria: Sequence[Any],
) -> dict[str, Any]:
    """Build Noul/Score questions from (name, kind, question) rows. Catalogs stay injected."""

    questions: dict[str, Any] = {}
    for name, kind, question in specs or ():
        if kind == "noul":
            questions[str(name)] = noul_ctor(instructions=question)
        else:
            questions[str(name)] = score_ctor(instructions=question, criteria=list(score_criteria))
    return questions


def proposal_feature_state(
    record: Mapping[str, Any],
    current: str,
    proposal: Mapping[str, Any],
    *,
    token_fn: Callable[[str], int],
    tail_fn: Callable[[str, int], str],
    tail_n: int = 500,
    goal: str = "Judge this MCMC edit of a lake-valid Lean 4 proof. Do not write Lean.",
) -> dict[str, Any]:
    """Compact TypeSafe state for one MCMC edit. Jev does not write Lean."""

    proposed = str(proposal.get("tactics") or "")
    return {
        "problem": record.get("name"),
        "current_tokens": token_fn(current),
        "current_tail": tail_fn(current, int(tail_n)),
        "edit_kind": proposal.get("kind"),
        "edit_note": proposal.get("note"),
        "proposed_tokens": token_fn(proposed),
        "proposed_tail": tail_fn(proposed, int(tail_n)),
        "goal": goal,
    }


def fill_rank_criteria(
    drafts: Sequence[Mapping[str, Any]],
    *,
    head_fn: Callable[[str, int], str],
    cap: int = 16,
) -> dict[str, str]:
    """One criterion string per fill draft id. Catalog wording stays injected via head_fn."""

    from jevops.outer import head_seq

    return {
        str(item.get("kind") or ""): head_fn(
            f"{item.get('generator')}; sched={item.get('schedule_id')}; "
            f"shots={item.get('n_shots')}; masks={item.get('n_masks')}; "
            f"{item.get('original')!s} -> {item.get('fill')!s}; "
            f"{item.get('token_count')} tok",
            180,
        )
        for item in head_seq(drafts, cap)
        if item.get("kind")
    }


def fill_rank_state(
    record: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    *,
    head_fn: Callable[[str, int], str],
    cap: int = 16,
    goal: str = "",
) -> dict[str, Any]:
    """TypeSafe state for ranking masked fills. Goal catalog stays in the consumer."""

    from jevops.outer import head_seq

    return {
        "problem": record.get("name"),
        "goal": goal,
        "drafts": [
            {
                "id": item.get("kind"),
                "head": head_fn(item.get("tactics") or "", 220),
                "tokens": item.get("token_count"),
                "schedule_id": item.get("schedule_id"),
                "n_shots": item.get("n_shots"),
                "n_masks": item.get("n_masks"),
                "few_shot": item.get("few_shot"),
            }
            for item in head_seq(drafts, cap)
        ],
    }


def cfg_score_criteria(table: Sequence[Mapping[str, Any]], eligible: Mapping[str, Any]) -> dict[str, str]:
    """One criterion per CFG schedule id. Table catalog stays in the consumer."""

    return {
        str(item.get("id") or ""): (
            f"{item.get('n_masks')} hole(s) × {item.get('span')} tokens; "
            f"{item.get('n_shots')} few-shot; cfg_scale={item.get('cfg_scale')}; "
            f"eligible_span_{item.get('span')}={eligible.get(f'span_{item.get('span')}', 0)}"
        )
        for item in table or ()
        if item.get("id")
    }


def cfg_score_state(
    record: Mapping[str, Any],
    tactics: str,
    *,
    token_fn: Callable[[str], int],
    eligible: Mapping[str, Any],
    one_hole: bool,
    head_fn: Callable[[str, int], str],
    goal: str,
) -> dict[str, Any]:
    """TypeSafe state for a CFG mask Score. Goal catalog stays in the consumer."""

    return {
        "problem": record.get("name"),
        "tokens": token_fn(tactics),
        "eligible_spans": dict(eligible or {}),
        "one_hole": bool(one_hole),
        "goal": goal,
        "head": head_fn(tactics, 400),
    }


def pack_fanout_live_row(
    result: Any,
    wall_ms: float,
    *,
    unpack_fn: Callable[[Any], tuple[Any, Any, Any, Any]],
    rank_fn: Callable[[Mapping[str, Any], Sequence[Any]], Any],
    drafts: Sequence[Any],
    choice_key: str = "best_first_draft",
    noul_any_key: str = "any_draft_likely_compiles",
    noul_spend_key: str = "spend_llm_after_fanout",
    score_key: str = "likely_token_cut",
) -> dict[str, Any]:
    """Project a live fan-out Choice/Noul/Score round. Jev does not write Lean."""

    choices, nouls, scores, usage = unpack_fn(result)
    best = (choices or {}).get(choice_key)
    noul_any = (nouls or {}).get(noul_any_key)
    spend = (nouls or {}).get(noul_spend_key)
    shorter = (scores or {}).get(score_key)
    probabilities = dict(getattr(best, "probabilities", None) or {})
    return {
        "live": True,
        "model": getattr(result, "model", None),
        "usage": usage,
        "wall_ms": wall_ms,
        "best_first_draft": getattr(best, "choice", None),
        "best_confidence": getattr(best, "confidence", None),
        noul_any_key: getattr(noul_any, "noul", None),
        noul_spend_key: getattr(spend, "noul", None),
        score_key: getattr(shorter, "score", None),
        "top": rank_fn(probabilities, drafts),
    }
