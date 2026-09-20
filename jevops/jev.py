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
