"""JevOps-owned, dependency-light text router.

The historical integration imported ``ipfs_accelerate_py.llm_router`` from a
large sibling checkout.  JevOps only needs a narrow ``generate_text``
contract, so this module provides that contract with standard-library
providers:

* ``deterministic``/``fixture``: offline, fail-closed JSON proposals;
* ``codex_cli``: an explicitly selected local Codex CLI;
* ``openai_compatible``: an explicitly configured HTTP endpoint.

This is an advisory proposal channel.  It does not apply code, admit Lean, or
silently switch providers.  The verifier and outer action gate remain the
authority.  The old Endomorphosis router can still be selected by the
deprecated ``JEVOPS_USE_EXTERNAL_ROUTER=1`` compatibility path in
``jevops.outer``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional


class LLMRouterError(RuntimeError):
    """A selected local router provider could not produce a response."""


_TRACE = threading.local()


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return default


def _provider(value: Any) -> str:
    key = str(value or _env("JEVOPS_LLM_PROVIDER", default="deterministic")).strip().lower()
    return {
        "fixture": "deterministic",
        "local": "deterministic",
        "codex": "codex_cli",
        "codex-cli": "codex_cli",
        "openai": "openai_compatible",
        "openai-compatible": "openai_compatible",
        "http": "openai_compatible",
    }.get(key, key or "deterministic")


def _set_trace(**values: Any) -> None:
    _TRACE.value = {
        "router_module": __name__,
        "effective_provider_name": str(values.get("provider") or "deterministic"),
        "effective_model_name": str(values.get("model") or "jevops-deterministic"),
        "fixture": bool(values.get("fixture", False)),
        "external_dependency": False,
        **{str(k): v for k, v in values.items()},
    }


def get_last_generation_trace() -> dict[str, Any]:
    value = getattr(_TRACE, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def _deterministic_response(prompt: str) -> str:
    configured = os.environ.get("JEVOPS_LLM_FIXTURE_RESPONSE")
    if configured is not None:
        return configured
    lower = str(prompt or "").lower()
    if "candidates" in lower or "tactic" in lower or "lean ir" in lower:
        return json.dumps(
            {
                "focus": "in-tree deterministic router",
                "strategies": [],
                "candidates": [],
                "reason": "no external model selected",
            },
            separators=(",", ":"),
        )
    return json.dumps(
        {"action": "run", "reason": "in_tree_deterministic_router"},
        separators=(",", ":"),
    )


def _extract_codex_text(stdout: str, last_message: str) -> str:
    if last_message.strip():
        return last_message.strip()
    result = ""
    for line in str(stdout or "").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, Mapping):
            continue
        candidates = [row]
        item = row.get("item")
        if isinstance(item, Mapping):
            candidates.append(item)
        for candidate in candidates:
            kind = str(candidate.get("type") or "").lower()
            if kind in {"agent_message", "message", "output_text", "text"}:
                value = candidate.get("text") or candidate.get("content") or candidate.get("message")
                if isinstance(value, list):
                    value = "".join(str(part.get("text") or "") if isinstance(part, Mapping) else str(part) for part in value)
                if value:
                    result = str(value)
    return result.strip() or str(stdout or "").strip()


def _codex_generate(prompt: str, *, model: str, timeout: float, reasoning_effort: str = "", **kwargs: Any) -> str:
    executable = shutil.which(_env("JEVOPS_CODEX_BIN", default="codex"))
    if not executable:
        raise LLMRouterError("codex CLI not found on PATH")
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as handle:
        last_message_path = handle.name
    command = [executable, "exec", "--skip-git-repo-check", "-m", model]
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    command.extend(["--output-last-message", last_message_path, "--json", "-"])
    try:
        result = subprocess.run(
            command,
            input=str(prompt),
            text=True,
            capture_output=True,
            check=False,
            timeout=max(1.0, float(timeout)),
        )
        try:
            last_message = open(last_message_path, encoding="utf-8", errors="replace").read()
        except OSError:
            last_message = ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LLMRouterError(f"codex CLI failed: {type(exc).__name__}") from exc
    finally:
        try:
            os.unlink(last_message_path)
        except OSError:
            pass
    text = _extract_codex_text(result.stdout, last_message)
    if result.returncode != 0 and not text:
        raise LLMRouterError((result.stderr or "codex exec failed").strip()[:400])
    return text


def _http_generate(
    prompt: str,
    *,
    model: str,
    timeout: float,
    base_url: str = "",
    api_key: str = "",
    max_new_tokens: int = 1200,
    temperature: float = 0.0,
) -> str:
    root = (base_url or _env("JEVOPS_LLM_BASE_URL", "OPENAI_BASE_URL")).rstrip("/")
    key = api_key or _env("JEVOPS_LLM_API_KEY", "OPENAI_API_KEY")
    if not root or not key:
        raise LLMRouterError("openai-compatible router requires JEVOPS_LLM_BASE_URL and JEVOPS_LLM_API_KEY")
    endpoint = root if root.endswith("/chat/completions") else root + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": str(prompt)}],
        "max_tokens": max(1, int(max_new_tokens)),
        "temperature": float(temperature),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, allow_nan=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise LLMRouterError(f"router HTTP {exc.code}") from exc
    except Exception as exc:
        raise LLMRouterError(f"router request failed: {type(exc).__name__}") from exc
    choices = data.get("choices") if isinstance(data, Mapping) else None
    if not isinstance(choices, list) or not choices:
        raise LLMRouterError("router response has no choices")
    choice = choices[0] if isinstance(choices[0], Mapping) else {}
    message = choice.get("message") if isinstance(choice, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else choice.get("text")
    if isinstance(content, list):
        content = "".join(str(item.get("text") or "") if isinstance(item, Mapping) else str(item) for item in content)
    return str(content or "")


def generate_text(
    prompt: str,
    *,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    timeout: float = 180.0,
    reasoning_effort: Optional[str] = None,
    max_new_tokens: int = 1200,
    temperature: float = 0.0,
    **kwargs: Any,
) -> str:
    """Generate text through one explicitly selected in-tree provider."""

    selected = _provider(provider)
    model = str(model_name or _env("JEVOPS_LLM_MODEL", default="jevops-deterministic"))
    effort = str(reasoning_effort or _env("JEVOPS_CODEX_REASONING_EFFORT", default=""))
    if selected == "deterministic":
        _set_trace(provider=selected, model=model, fixture=True, reason="offline")
        return _deterministic_response(prompt)
    if selected == "codex_cli":
        text = _codex_generate(prompt, model=model, timeout=timeout, reasoning_effort=effort, **kwargs)
    elif selected == "openai_compatible":
        text = _http_generate(
            prompt,
            model=model,
            timeout=timeout,
            base_url=str(kwargs.get("base_url") or ""),
            api_key=str(kwargs.get("api_key") or ""),
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
    else:
        raise LLMRouterError(f"unsupported in-tree router provider: {selected}")
    _set_trace(provider=selected, model=model, fixture=False, reason="generated")
    return text


__all__ = ["LLMRouterError", "generate_text", "get_last_generation_trace"]
