"""Bounded local Leanstral HTTP client. No server, GPU, downloads or fallback.

Restores the Arena docker0 client contract without importing the accelerator.
Model identity is the server's claim, not attestation of its weights. Hosted
Mistral remains a separate adapter; no credentials are sent by this client.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import PurePath
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "http://172.17.0.1:8080/v1"
MODEL = "Leanstral"
MODEL_ALIASES = frozenset({"Leanstral", "leanstral_local"})
MAX_PROMPT_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 2_097_152


class LeanstralError(RuntimeError):
    """Explicit local capability/transport/protocol failure, never a proof result."""

    def __init__(self, message, *, category="protocol", http_status=None):
        super().__init__(message)
        self.category, self.http_status = category, http_status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LeanstralError("local Leanstral redirects are forbidden")


def endpoint(base_url: str) -> str:
    """Only the historical docker0 host or an explicitly selected loopback port."""
    if not isinstance(base_url, str) or any(c.isspace() or ord(c) < 32 for c in base_url):
        raise LeanstralError("invalid local Leanstral endpoint")
    try:
        parsed = urllib.parse.urlsplit(base_url)
        port = parsed.port
    except ValueError:
        raise LeanstralError("invalid local Leanstral endpoint") from None
    if (parsed.scheme != "http" or parsed.hostname not in {"172.17.0.1", "127.0.0.1", "localhost"}
            or port is None or port == 0 or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"/v1", "/v1/chat/completions"}):
        raise LeanstralError("explicit docker0/loopback HTTP /v1 endpoint required")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/v1/chat/completions", "", ""))


def _number(value, low, high) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def health_status(url: str, *, timeout: float = 2) -> tuple[int | None, str]:
    """Read-only local /health probe with the same no-proxy/no-redirect policy."""
    if not isinstance(url, str) or not url.endswith("/health") or not _number(timeout, 0.001, 30):
        raise LeanstralError("bounded local health probe required")
    endpoint(url.removesuffix("/health") + "/v1")  # Validate host/port before any IO.
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise LeanstralError("unexpected local health endpoint")
            return response.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, f"local Leanstral health HTTP {exc.code}"
    except (OSError, LeanstralError) as exc:
        return None, f"local Leanstral health unavailable ({type(exc).__name__})"


def server_profile(base_url: str = BASE_URL, *, timeout: float = 2) -> dict:
    """Read-only, allowlisted server claims. Never infer weights from an alias.

    Optional llama.cpp /props and /v1/models metadata; unsupported endpoints stay
    unknown. No raw server configuration, filesystem paths or templates escape.
    """
    if not _number(timeout, 0.001, 30):
        raise LeanstralError("bounded metadata timeout required")
    url = endpoint(base_url)
    origin = url.removesuffix("/v1/chat/completions")
    result = {"endpoint": url, "server_identity_attested": False, "metadata_errors": []}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    for path in ("/props", "/v1/models"):
        try:
            request = urllib.request.Request(origin + path, headers={"Accept": "application/json"})
            with opener.open(request, timeout=timeout) as response:
                if response.status != 200 or response.geturl() != origin + path:
                    raise LeanstralError("unexpected metadata endpoint/status")
                raw = response.read(65537)
            if len(raw) > 65536:
                raise LeanstralError("metadata byte budget")
            data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(data, dict):
                raise ValueError("metadata object required")
            def count(value):
                return value if type(value) is int and 0 < value <= 2**40 else None
            if path == "/props":
                defaults = data.get("default_generation_settings", {})
                if not isinstance(defaults, dict):
                    raise ValueError("metadata settings object required")
                template, model_path = data.get("chat_template"), data.get("model_path")
                result.update(declared_context_per_slot=count(defaults.get("n_ctx")),
                    declared_slots=count(data.get("total_slots")),
                    server_reported_model_filename=PurePath(model_path).name[:256] if isinstance(model_path, str) else None,
                    chat_template_sha256=hashlib.sha256(template.encode()).hexdigest() if isinstance(template, str) else None)
            else:
                models = data.get("data", [])
                if not isinstance(models, list) or len(models) > 32:
                    raise ValueError("bounded model metadata required")
                result["models"] = []
                for model in models:
                    if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                        raise ValueError("model metadata object required")
                    meta = model.get("meta", {})
                    if not isinstance(meta, dict):
                        raise ValueError("model metadata fields required")
                    result["models"].append({"id": model["id"][:128], "declared_training_context": count(meta.get("n_ctx_train"))})
        except (OSError, ValueError, RecursionError, LeanstralError) as exc:
            result["metadata_errors"].append({"path": path, "error_type": type(exc).__name__})
    return result


def _messages_ok(messages: list, *, tools) -> bool:
    roles = {"system", "user", "assistant", "tool"} if tools is not None else {"system", "user", "assistant"}
    keys = {"role", "content", "tool_call_id", "tool_calls"} if tools is not None else {"role", "content"}
    if any(type(m) is not dict or not set(m) <= keys or not isinstance(m.get("role"), str)
           or m["role"] not in roles for m in messages):
        return False
    if any(m["role"] == "system" for m in messages[1:]):
        return False
    if tools is None:
        return (messages[-1]["role"] == "user"
                and all(isinstance(m.get("content"), str) and m["content"].strip() for m in messages))
    return all(m["role"] != "tool" or isinstance(m.get("content"), str) for m in messages)


def _tools_ok(tools) -> bool:
    if type(tools) is not list or not 1 <= len(tools) <= 8:
        return False
    try:
        encoded = json.dumps(tools, ensure_ascii=False).encode()
    except (TypeError, ValueError):
        return False
    return len(encoded) <= 16384


def _mistral_tool_calls(content: str) -> list[dict]:
    """Mistral's text tool-call markup. This server does not parse it into JSON."""

    import re

    pattern = re.compile(
        r"<\|tool_call_begin\|>function=([A-Za-z0-9_]+)<\|tool_call_arg_begin\|>(.*?)<\|tool_call_arg_end\|>",
        re.S,
    )
    found: list[dict] = []
    for index, (name, raw_args) in enumerate(pattern.findall(content)):
        raw_args = raw_args.strip()
        arguments: dict = {}
        if raw_args.startswith("{"):
            try:
                loaded = json.loads(raw_args)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                arguments = loaded
        else:
            matched = re.match(r'([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$', raw_args, re.S)
            if matched:
                arguments = {matched.group(1): matched.group(2)}
        found.append({"id": f"call_{index}", "name": name, "arguments": arguments})
    return found


def _normalize_tool_calls(message: dict, content: str) -> list[dict]:
    structured = message.get("tool_calls")
    found: list[dict] = []
    if isinstance(structured, list):
        for index, call in enumerate(structured):
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else call
            name = function.get("name")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if isinstance(name, str) and isinstance(arguments, dict):
                found.append({"id": str(call.get("id") or f"call_{index}"), "name": name, "arguments": arguments})
    if found:
        return found
    mistral = _mistral_tool_calls(content)
    if mistral:
        return mistral
    marker = "<|im_start|>tool_calls"
    if marker not in content:
        return []
    body = content.split(marker, 1)[1].split("<|", 1)[0].strip()
    if not body or body == "[]":
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    for index, call in enumerate(payload):
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else call
        name = function.get("name")
        arguments = function.get("arguments") if isinstance(function.get("arguments"), dict) else {}
        if isinstance(name, str):
            found.append({"id": f"call_{index}", "name": name, "arguments": arguments})
    return found


def tactic_response_format(request_id: str) -> dict:
    """Closed llama.cpp JSON-schema request, NOT a proof/format certificate.

    Deliberately no arbitrary schemas, references or regex grammars. Keep the
    same output instructions in the prompt and validate the returned text.
    Do not expand a 16K string bound into a server-side repetition grammar:
    some local builds reject that grammar before inference. The completion
    token budget, response byte limit and strict tactic parser still bound the
    output; a nonempty schema string is not permission to bypass those checks.
    """
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{16}", request_id):
        raise LeanstralError("16-hex request ID required for tactic schema")
    return {"type": "json_object", "schema": {
        "type": "object", "properties": {
            "request_id": {"type": "string", "enum": [request_id]},
            "tactic": {"type": "string", "minLength": 1}},
        "required": ["request_id", "tactic"], "additionalProperties": False}}


def _checked_response_format(value) -> dict:
    try:
        rid = value["schema"]["properties"]["request_id"]["enum"][0]
        expected = tactic_response_format(rid)
        # Canonical encoding also distinguishes bool from integer bounds.
        if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True):
            raise ValueError("different schema")
    except (KeyError, IndexError, TypeError, ValueError, RecursionError, LeanstralError):
        raise LeanstralError("only the bounded tactic response schema is supported") from None
    return expected


def chat_completion(prompt: str | None = None, *, messages=None, model: str = MODEL, base_url: str = "",
                    max_new_tokens: int = 1400, timeout: float = 300,
                    temperature: float = 0, stop=None, tools=None, response_format=None) -> dict:
    """One request; bounded response and timeout; no ambient auth or HTTP proxy.

    stop/text/usage/model metadata are retained. The caller still owns call/spend
    budgets and proof admission. Socket timeout is not a whole-run deadline.
    """
    if messages is None:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > MAX_PROMPT_BYTES:
            raise LeanstralError("nonempty bounded Leanstral prompt required")
        messages = [{"role": "user", "content": prompt}]
    else:
        if (prompt is not None or type(messages) is not list or not 1 <= len(messages) <= 16
                or not _messages_ok(messages, tools=tools)
                or len(json.dumps(messages, ensure_ascii=False).encode()) > MAX_PROMPT_BYTES):
            raise LeanstralError("bounded text messages or prompt required, not both")
    if not isinstance(model, str) or model not in MODEL_ALIASES:
        raise LeanstralError("local Leanstral model must be Leanstral or leanstral_local")
    if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32768:
        raise LeanstralError("Leanstral token budget must be an integer in 1..32768")
    if not _number(timeout, 0.001, 3600) or not _number(temperature, 0, 2):
        raise LeanstralError("invalid Leanstral timeout/temperature")
    if stop is not None and (type(stop) not in (list, tuple) or len(stop) > 16
            or any(not isinstance(s, str) or not s or len(s.encode()) > 256 for s in stop)):
        raise LeanstralError("bounded Leanstral stop strings required")
    url = endpoint(base_url or os.environ.get("JEVOPS_LEANSTRAL_BASE_URL")
                   or os.environ.get("IPFS_ACCELERATE_LLAMA_CPP_BASE_URL") or BASE_URL)
    payload = {"model": model, "messages": messages,
               "max_tokens": max_new_tokens, "temperature": temperature, "stream": False}
    if stop is not None:
        payload["stop"] = list(stop)
    if response_format is not None:
        if tools is not None:
            raise LeanstralError("tactic response schema cannot be combined with tools")
        payload["response_format"] = _checked_response_format(response_format)
    if tools is not None:
        if not _tools_ok(tools):
            raise LeanstralError("bounded Leanstral tool list required")
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    request = urllib.request.Request(url, data=json.dumps(payload, allow_nan=False).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        # Neither a caller's installed opener nor HTTP(S)_PROXY can reroute this.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url or response.status != 200:
                raise LeanstralError("unexpected local Leanstral endpoint/status")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise LeanstralError("Leanstral response byte budget exceeded")
        data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except LeanstralError:
        raise
    except urllib.error.HTTPError as exc:
        # Do not infer a context-window failure from a generic 400/413 response.
        raise LeanstralError(f"local Leanstral HTTP {exc.code}; no retry/fallback",
                            category="http_error", http_status=exc.code) from None
    except (OSError, ValueError, RecursionError) as exc:
        # Never include server bodies, prompts, URL credentials or ambient keys.
        category = ("timeout" if isinstance(exc, TimeoutError) or
                    isinstance(getattr(exc, "reason", None), TimeoutError) else
                    "transport" if isinstance(exc, OSError) else "invalid_json")
        raise LeanstralError(f"local Leanstral request failed ({type(exc).__name__}); no retry/fallback",
                            category=category) from None
    if (not isinstance(data, dict) or not isinstance(data.get("model"), str)
            or data["model"] not in MODEL_ALIASES):
        raise LeanstralError("missing or unexpected Leanstral response model", category="model_mismatch")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise LeanstralError("one Leanstral response choice required")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise LeanstralError("Leanstral message object required")
    if tools is None and (message.get("tool_calls") or message.get("function_call")):
        raise LeanstralError("Leanstral must return text, not executable tool calls", category="unexpected_tool_calls")
    content = message.get("content")
    if isinstance(content, list):
        if any(not isinstance(p, dict) or p.get("type") != "text" or not isinstance(p.get("text"), str)
               for p in content):
            raise LeanstralError("unsupported Leanstral content block")
        content = "".join(p["text"] for p in content)
    if not isinstance(content, str):
        content = ""
    tool_calls = _normalize_tool_calls(message, content) if tools is not None else []
    if (not content.strip()) and not tool_calls:
        category = ("output_truncated" if choice.get("finish_reason") == "length" else
                    "reasoning_without_answer" if message.get("reasoning_content") or message.get("reasoning") else
                    "empty_completion")
        raise LeanstralError("empty Leanstral completion", category=category)
    usage = data.get("usage", {})
    if not isinstance(usage, dict) or any(type(usage[k]) is not int or usage[k] < 0
            for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage):
        raise LeanstralError("invalid Leanstral token usage")
    for value in (data.get("id", ""), choice.get("finish_reason", "")):
        if not isinstance(value, str) or len(value) > 256:
            raise LeanstralError("invalid Leanstral response metadata")
    return {"text": content, "tool_calls": tool_calls, "requested_model": model, "response_model": data["model"],
            "request_id": data.get("id", ""), "finish_reason": choice.get("finish_reason", ""),
            "usage": {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
            "endpoint": url, "wall_ms": (time.monotonic() - started) * 1000,
            "server_identity_attested": False, "fixture": False, "fallback_used": False}
