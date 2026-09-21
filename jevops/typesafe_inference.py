"""Small, stdlib-only TypeSafe System One client.

This is the JevOps-owned compatibility surface for the structured TypeSafe
protocol.  It intentionally implements only the DTOs and HTTP operation used
by JevOps; the larger ``ipfs_accelerate_py`` checkout is no longer required
for core imports or offline runs.

The client is an advisor.  Its answers are never proof evidence and callers
must keep the existing verifier/Lake admission boundary.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Union

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 30.0
SYSTEMONE_PATH = "/v1/systemone"
MODELS_PATH = "/v1/models"
PROVIDER_NAME = "typesafe"

API_KEY_ENV_NAMES: tuple[str, ...] = (
    "TYPESAFE_API_KEY",
    "ipfs_accelerate_py_TYPESAFE_API_KEY",
    "IPFS_ACCELERATE_PY_TYPESAFE_API_KEY",
    "IPFS_DATASETS_PY_TYPESAFE_API_KEY",
)
BASE_URL_ENV_NAMES: tuple[str, ...] = (
    "TYPESAFE_BASE_URL",
    "ipfs_accelerate_py_TYPESAFE_BASE_URL",
    "IPFS_ACCELERATE_PY_TYPESAFE_BASE_URL",
)
MODEL_ENV_NAMES: tuple[str, ...] = (
    "TYPESAFE_DEFAULT_MODEL",
    "ipfs_accelerate_py_TYPESAFE_MODEL",
    "IPFS_ACCELERATE_PY_TYPESAFE_MODEL",
)

JsonValue = Union[None, bool, int, float, str, list[Any], dict[str, Any]]
QuestionLike = Union["Noul", "Choice", "Score", Mapping[str, Any]]
_LAST_OBSERVATION = threading.local()


class TypeSafeInferenceError(RuntimeError):
    """HTTP or validation failure without exposing credentials."""

    def __init__(self, message: str, *, status: Optional[int] = None, request_id: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.status_code = status
        self.request_id = str(request_id or "")


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_max: float = 2.0
    timeout: float = DEFAULT_TIMEOUT
    retry_statuses: tuple[int, ...] = (429, 529)


@dataclass
class Noul:
    instructions: JsonValue
    criteria: Optional[Mapping[str, JsonValue]] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "noul", "instructions": self.instructions}
        if self.criteria:
            out["criteria"] = dict(self.criteria)
        return out


def noul_yes_no(
    *,
    true_what: str,
    false_what: str,
    true_examples: Sequence[str] = (),
    false_examples: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "true": {"what": true_what, "examples": list(true_examples)},
        "false": {"what": false_what, "examples": list(false_examples)},
    }


@dataclass
class Choice:
    instructions: JsonValue
    criteria: Mapping[str, Optional[JsonValue]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "choice", "instructions": self.instructions, "criteria": dict(self.criteria)}


@dataclass
class Score:
    instructions: JsonValue
    criteria: Sequence[JsonValue] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "score", "instructions": self.instructions, "criteria": list(self.criteria)}


@dataclass(frozen=True)
class NoulAnswer:
    noul: float
    type: str = "noul"
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: Mapping[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    type: str = "choice"
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    legend: Mapping[str, str] = field(default_factory=dict)
    probabilities: Mapping[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    type: str = "score"
    raw: Mapping[str, Any] = field(default_factory=dict)


Answer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]


@dataclass
class SystemOneResult:
    model: str
    answers: dict[str, dict[str, Any]]
    usage: dict[str, int]
    raw: dict[str, Any] = field(default_factory=dict)
    nouls: dict[str, NoulAnswer] = field(default_factory=dict)
    choices: dict[str, ChoiceAnswer] = field(default_factory=dict)
    scores: dict[str, ScoreAnswer] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "answers": dict(self.answers), "usage": dict(self.usage)}

    def to_json(self) -> str:
        return json.dumps(self.answers, separators=(",", ":"), ensure_ascii=False)


def _env_value(names: Sequence[str], environ: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if environ is None else environ
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def resolve_typesafe_api_key(environ: Optional[Mapping[str, str]] = None) -> str:
    return _env_value(API_KEY_ENV_NAMES, environ)


def resolve_typesafe_base_url(environ: Optional[Mapping[str, str]] = None) -> str:
    return (_env_value(BASE_URL_ENV_NAMES, environ) or DEFAULT_BASE_URL).rstrip("/")


def resolve_typesafe_model(environ: Optional[Mapping[str, str]] = None) -> str:
    return _env_value(MODEL_ENV_NAMES, environ) or DEFAULT_MODEL


def typesafe_configured(environ: Optional[Mapping[str, str]] = None) -> bool:
    return bool(resolve_typesafe_api_key(environ))


def _redact(text: str, secret: str) -> str:
    value = str(text or "")
    if secret:
        value = value.replace(secret, "[redacted]")
    return value.replace("Bearer " + secret, "Bearer [redacted]") if secret else value


def question_to_dict(question: QuestionLike) -> dict[str, Any]:
    if isinstance(question, (Noul, Choice, Score)):
        return question.to_dict()
    if isinstance(question, Mapping):
        payload = dict(question)
        kind = str(payload.get("type") or "").strip().lower()
        if kind not in {"noul", "choice", "score"} or "instructions" not in payload:
            raise TypeSafeInferenceError("question requires type and instructions")
        payload["type"] = kind
        return payload
    to_dict = getattr(question, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeSafeInferenceError("questions must be typed DTOs or mappings")


def serialize_questions(questions: Mapping[str, QuestionLike]) -> dict[str, dict[str, Any]]:
    if not isinstance(questions, Mapping) or not questions:
        raise TypeSafeInferenceError("questions must be a non-empty mapping")
    return {str(key): question_to_dict(value) for key, value in questions.items()}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _parse_answer(payload: Mapping[str, Any]) -> Optional[Answer]:
    kind = str(payload.get("type") or "").strip().lower()
    if kind == "noul":
        return NoulAnswer(noul=_float(payload.get("noul")), raw=dict(payload))
    if kind == "choice":
        raw_probs = payload.get("probabilities")
        probs = raw_probs if isinstance(raw_probs, Mapping) else {}
        return ChoiceAnswer(
            choice=str(payload.get("choice") or ""),
            probabilities={str(k): _float(v) for k, v in probs.items()},
            confidence=_float(payload.get("confidence")),
            raw=dict(payload),
        )
    if kind == "score":
        raw_probs = payload.get("probabilities")
        raw_legend = payload.get("legend")
        probs = raw_probs if isinstance(raw_probs, Mapping) else {}
        legend = raw_legend if isinstance(raw_legend, Mapping) else {}
        return ScoreAnswer(
            score=_float(payload.get("score")),
            legend={str(k): str(v) for k, v in legend.items()},
            probabilities={str(k): _float(v) for k, v in probs.items()},
            confidence=_float(payload.get("confidence")),
            raw=dict(payload),
        )
    return None


def _parse_result(data: Mapping[str, Any]) -> SystemOneResult:
    raw_answers = data.get("answers")
    answers = {
        str(key): dict(value)
        for key, value in (raw_answers.items() if isinstance(raw_answers, Mapping) else ())
        if isinstance(value, Mapping)
    }
    raw_usage = data.get("usage")
    usage_map = raw_usage if isinstance(raw_usage, Mapping) else {}
    usage = {
        "input_tokens": int(usage_map.get("input_tokens") or 0),
        "output_tokens": int(usage_map.get("output_tokens") or 0),
    }
    result = SystemOneResult(
        model=str(data.get("model") or ""),
        answers=answers,
        usage=usage,
        raw=dict(data),
    )
    for key, value in answers.items():
        answer = _parse_answer(value)
        if isinstance(answer, NoulAnswer):
            result.nouls[key] = answer
        elif isinstance(answer, ChoiceAnswer):
            result.choices[key] = answer
        elif isinstance(answer, ScoreAnswer):
            result.scores[key] = answer
    return result


def _request_id(headers: Any) -> str:
    for name in ("x-request-id", "X-Request-Id", "request-id"):
        try:
            value = headers.get(name)
        except Exception:
            value = None
        if value:
            return str(value)
    return ""


def _request_json(
    *,
    url: str,
    api_key: str,
    payload: Optional[Mapping[str, Any]],
    method: str,
    timeout: float,
    retry: RetryPolicy,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    attempts = max(1, int(retry.max_retries) + 1)
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read().decode("utf-8", errors="replace")
                request_id = _request_id(getattr(response, "headers", None))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if int(exc.code) in retry.retry_statuses and attempt + 1 < attempts:
                time.sleep(min(float(retry.backoff_max), 0.2 * (2**attempt)))
                continue
            raise TypeSafeInferenceError(
                _redact(f"TypeSafe HTTP {exc.code}: {detail or exc.reason}", api_key),
                status=int(exc.code),
                request_id=_request_id(getattr(exc, "headers", None)),
            ) from exc
        except Exception as exc:
            if attempt + 1 < attempts:
                time.sleep(min(float(retry.backoff_max), 0.2 * (2**attempt)))
                continue
            raise TypeSafeInferenceError(_redact(f"TypeSafe request failed: {exc}", api_key)) from exc
        try:
            decoded = json.loads(raw)
        except Exception as exc:
            raise TypeSafeInferenceError("TypeSafe returned invalid JSON", status=status, request_id=request_id) from exc
        if not isinstance(decoded, dict):
            raise TypeSafeInferenceError("TypeSafe returned a non-object JSON response", status=status, request_id=request_id)
        decoded.setdefault("_request_id", request_id)
        return decoded
    raise TypeSafeInferenceError("TypeSafe request failed")


def system_one(
    state: JsonValue,
    questions: Mapping[str, QuestionLike],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[float] = None,
    extra_body: Optional[Mapping[str, Any]] = None,
    retry: Optional[RetryPolicy] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> SystemOneResult:
    key = str(api_key or "").strip() or resolve_typesafe_api_key(environ)
    if not key:
        raise TypeSafeInferenceError("TYPESAFE_API_KEY is required for TypeSafe System One inference")
    policy = retry or RetryPolicy()
    model_name = str(model or "").strip() or resolve_typesafe_model(environ)
    payload: dict[str, Any] = {
        "state": state,
        "model": model_name,
        "questions": serialize_questions(questions),
    }
    if extra_body:
        payload.update(dict(extra_body))
    result = _parse_result(
        _request_json(
            url=f"{(str(base_url or '').strip() or resolve_typesafe_base_url(environ)).rstrip('/')}{SYSTEMONE_PATH}",
            api_key=key,
            payload=payload,
            method="POST",
            timeout=float(timeout if timeout is not None else policy.timeout),
            retry=policy,
        )
    )
    _LAST_OBSERVATION.value = {
        "model": result.model or model_name,
        "input_tokens": result.usage["input_tokens"],
        "output_tokens": result.usage["output_tokens"],
        "total_tokens": result.usage["input_tokens"] + result.usage["output_tokens"],
        "provider": PROVIDER_NAME,
    }
    return result


def get_last_typesafe_observation() -> dict[str, Any]:
    value = getattr(_LAST_OBSERVATION, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def list_typesafe_models(
    *,
    live: bool = False,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 4.0,
    environ: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    defaults = (DEFAULT_MODEL, "jev")
    if not live:
        return defaults
    key = str(api_key or "").strip() or resolve_typesafe_api_key(environ)
    if not key:
        return defaults
    try:
        data = _request_json(
            url=f"{(str(base_url or '').strip() or resolve_typesafe_base_url(environ)).rstrip('/')}{MODELS_PATH}",
            api_key=key,
            payload=None,
            method="GET",
            timeout=max(0.5, float(timeout)),
            retry=RetryPolicy(max_retries=0, timeout=timeout),
        )
    except Exception:
        return defaults
    rows = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
    names = []
    for row in rows if isinstance(rows, list) else ():
        if isinstance(row, str) and row.strip():
            names.append(row.strip())
        elif isinstance(row, Mapping):
            name = str(row.get("id") or row.get("name") or "").strip()
            if name:
                names.append(name)
    return tuple(names[:32]) if names else defaults


class TypeSafeClient:
    """Synchronous client matching the subset used by JevOps/LRA."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        retry: Optional[RetryPolicy] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.api_key = str(api_key or "").strip() or resolve_typesafe_api_key(environ)
        self.base_url = str(base_url or "").strip() or resolve_typesafe_base_url(environ)
        self.model = str(model or "").strip() or resolve_typesafe_model(environ)
        self.timeout = float(timeout if timeout is not None else DEFAULT_TIMEOUT)
        self.retry = retry or RetryPolicy(timeout=self.timeout)

    def system_one(
        self,
        state: JsonValue,
        questions: Mapping[str, QuestionLike],
        *,
        model: Optional[str] = None,
        extra_body: Optional[Mapping[str, Any]] = None,
        retry: Optional[RetryPolicy] = None,
        timeout: Optional[float] = None,
    ) -> SystemOneResult:
        return system_one(
            state,
            questions,
            model=model or self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout if timeout is None else float(timeout),
            extra_body=extra_body,
            retry=retry or self.retry,
        )

    def close(self) -> None:
        return None

    def __enter__(self) -> "TypeSafeClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


__all__ = [
    "API_KEY_ENV_NAMES",
    "Choice",
    "ChoiceAnswer",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "Noul",
    "NoulAnswer",
    "Score",
    "ScoreAnswer",
    "RetryPolicy",
    "SystemOneResult",
    "TypeSafeClient",
    "TypeSafeInferenceError",
    "get_last_typesafe_observation",
    "list_typesafe_models",
    "noul_yes_no",
    "question_to_dict",
    "resolve_typesafe_api_key",
    "resolve_typesafe_base_url",
    "resolve_typesafe_model",
    "serialize_questions",
    "system_one",
    "typesafe_configured",
]
