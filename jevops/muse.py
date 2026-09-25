"""Meta Muse Spark through the Model API. Text proposals only.

Lake admits Lean. This client does not write a file, compile, or fall back to
Leanstral, Codex, or the deterministic router. The API key is never copied
into the trace.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Optional, Sequence


BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_REASONING = "low"
_AUTH = Path.home() / ".config" / "muse" / "auth.json"


class MuseError(RuntimeError):
    """The selected Muse route could not answer. Not a proof result."""

    def __init__(self, message: str, *, category: str = "protocol", http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        raise MuseError("Muse redirects are refused")


def endpoint(base_url: str) -> str:
    """Only the official Meta Model API chat-completions URL."""

    if not isinstance(base_url, str) or any(char.isspace() or ord(char) < 32 for char in base_url):
        raise MuseError("invalid Muse endpoint")
    try:
        parsed = urllib.parse.urlsplit(base_url.strip())
    except ValueError as exc:
        raise MuseError("invalid Muse endpoint") from exc
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.meta.ai"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or path not in {"", "/v1", "/v1/chat/completions"}
    ):
        raise MuseError("Muse requires https://api.meta.ai/v1")
    return "https://api.meta.ai/v1/chat/completions"


def resolve_api_key(explicit: str = "") -> str:
    """Env first, then the local `muse` login. Empty if neither is present."""

    for name in ("MODEL_API_KEY", "META_API_KEY", "JEVOPS_MUSE_API_KEY"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    given = str(explicit or "").strip()
    if given:
        return given
    if not _AUTH.is_file():
        return ""
    try:
        loaded = json.loads(_AUTH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    meta = loaded.get("providers", {}).get("meta", {}) if isinstance(loaded, dict) else {}
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("api_key") or "").strip()


def chat_completion(
    prompt: str = "",
    *,
    messages: Optional[Sequence[Mapping[str, str]]] = None,
    model: str = DEFAULT_MODEL,
    base_url: str = "",
    api_key: str = "",
    max_new_tokens: int = 2000,
    timeout: float = 120.0,
    reasoning_effort: str = DEFAULT_REASONING,
) -> dict[str, Any]:
    """One chat completion. The returned text is not a Lake admit."""

    key = resolve_api_key(api_key)
    if not key:
        raise MuseError("Muse requires MODEL_API_KEY or a local muse login", category="auth")
    url = endpoint(base_url or _env_base() or BASE_URL)
    payload_messages = _messages(prompt, messages)
    effort = str(reasoning_effort or DEFAULT_REASONING).strip()
    if effort == "none":
        raise MuseError("Muse Spark rejects reasoning_effort none", category="protocol")
    payload = {
        "model": str(model or DEFAULT_MODEL),
        "messages": payload_messages,
        "max_tokens": max(1, int(max_new_tokens)),
        "reasoning_effort": effort,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=float(timeout)) as response:
            if response.geturl() != url:
                raise MuseError("unexpected Muse endpoint")
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except MuseError:
        raise
    except urllib.error.HTTPError as exc:
        raise MuseError(f"Muse HTTP {exc.code}", category="http", http_status=exc.code) from None
    except Exception as exc:
        raise MuseError(f"Muse request failed: {type(exc).__name__}", category="transport") from None
    return _parse(data, key)


def _env_base() -> str:
    return str(os.environ.get("JEVOPS_MUSE_BASE_URL") or "").strip()


def _messages(prompt: str, messages: Optional[Sequence[Mapping[str, str]]]) -> list[dict[str, str]]:
    if messages is not None:
        rows: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, Mapping):
                raise MuseError("Muse messages must be role/content objects")
            role = str(item.get("role") or "")
            content = item.get("content")
            if role not in {"developer", "system", "user", "assistant"} or not isinstance(content, str):
                raise MuseError("Muse message role or content is invalid")
            rows.append({"role": role, "content": content})
        if not rows:
            raise MuseError("Muse messages are empty")
        return rows
    if not str(prompt or "").strip():
        raise MuseError("Muse prompt is empty")
    return [{"role": "user", "content": str(prompt)}]


def _parse(data: Any, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise MuseError("Muse response is not an object")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise MuseError("Muse response has no choices")
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "") if isinstance(part, Mapping) else str(part) for part in content
        )
    text = str(content or "")
    if key and key in text:
        text = text.replace(key, "")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return {
        "text": text,
        "model": str(data.get("model") or ""),
        "finish_reason": str(choices[0].get("finish_reason") or ""),
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
    }
