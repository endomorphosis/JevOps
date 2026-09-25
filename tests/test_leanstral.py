"""Offline migration/protocol checks. Responses and compilers are fixtures."""
import copy
import importlib
import io
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from jevops import leanstral, llm_router
from jevops.outer import make_llm_router_generate

HARNESS = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/harness"


def response(text="simp", model="leanstral_local"):
    return {"id": "offline-fixture", "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 0, "total_tokens": 8}}


@pytest.fixture
def transport(monkeypatch):
    class Transport:
        payload = response()
        error = None
        raw = None
        final_url = None
        calls = []
        handlers = []

        def open(self, request, *, timeout):
            self.calls.append((request, timeout))
            if self.error:
                raise self.error
            stream = io.BytesIO(self.raw if self.raw is not None else json.dumps(self.payload).encode())
            stream.status = 200
            stream.geturl = lambda: self.final_url or request.full_url
            return stream

    fake = Transport()
    def build(*handlers):
        fake.handlers = handlers
        return fake
    monkeypatch.setattr(urllib.request, "build_opener", build)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("ambient/live HTTP forbidden"))
    monkeypatch.delenv("JEVOPS_USE_EXTERNAL_ROUTER", raising=False)
    monkeypatch.delenv("JEVOPS_LLM_MODEL", raising=False)
    monkeypatch.delenv("JEVOPS_LEANSTRAL_BASE_URL", raising=False)
    monkeypatch.delenv("IPFS_ACCELERATE_LLAMA_CPP_BASE_URL", raising=False)
    return fake


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(HARNESS))
    monkeypatch.setenv("JEVOPS_REGISTER_LRA_HOOKS", "0")
    monkeypatch.delenv("JEVOPS_USE_EXTERNAL_DEPS", raising=False)
    monkeypatch.setenv("JEVOPS_CAS_DIR", str(tmp_path / "cas"))
    # In the migrated default path there must be no import of the sibling router.
    original = importlib.import_module
    def guarded(name, *args, **kwargs):
        assert not name.startswith(("ipfs_accelerate_py", "ipfs_datasets_py")), name
        return original(name, *args, **kwargs)
    monkeypatch.setattr(importlib, "import_module", guarded)
    warmup = importlib.import_module("run_warmup")
    monkeypatch.setattr(warmup.lra_d0, "probe_docker0_health", lambda: pytest.fail("unexpected health HTTP"))
    monkeypatch.setattr(warmup.lra_gt, "probe_docker0_health", lambda: pytest.fail("unexpected health HTTP"))
    for key in ("IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART", "IPFS_ACCELERATE_LLAMA_CPP_AUTO_INSTALL",
                "IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL", "IPFS_ACCELERATE_LLAMA_CPP_AUTO_UPDATE",
                "IPFS_ACCELERATE_LLAMA_CPP_BASE_URL", "IPFS_ACCELERATE_LLAMA_CPP_HOST",
                "IPFS_ACCELERATE_LLAMA_CPP_PORT", "IPFS_ACCEL_SKIP_CORE", "IPFS_AUTO_INSTALL",
                "LRA_TYPESAFE", "LRA_GENERATOR", "LRA_HARDWARE", "LRA_LOOP"):
        monkeypatch.setenv(key, os.environ.get(key, ""))  # Restore legacy CLI pinning after this fixture.
    return warmup


@pytest.mark.parametrize("provider", ["leanstral_local", "leanstral", "leanstral-local"])
def test_in_tree_router_and_strict_alias_attestation(transport, monkeypatch, provider):
    monkeypatch.setenv("OPENAI_API_KEY", "never-send-this-fixture-secret")
    monkeypatch.setenv("MISTRAL_API_KEY", "never-send-this-fixture-secret")
    monkeypatch.setenv("HTTP_PROXY", "http://untrusted.invalid:8080")
    generate = make_llm_router_generate(provider=provider, model_name="Leanstral", verify_route=True,
        max_new_tokens=17, timeout=12, stop=["</s>"], allow_cross_provider_fallback=False)
    assert generate("shorten this tactic") == "simp"
    assert generate.last_route_attestation["verified"] is True
    trace = llm_router.get_last_generation_trace()
    assert trace["effective_provider_name"] == "leanstral_local"
    assert trace["effective_model_name"] == "Leanstral" and trace["response_model"] == "leanstral_local"
    assert trace["usage"]["completion_tokens"] == 0
    assert trace["fallback_used"] is False and trace["server_identity_attested"] is False
    request, timeout = transport.calls[0]
    data = json.loads(request.data)
    assert request.full_url == leanstral.BASE_URL + "/chat/completions"
    assert data["max_tokens"] == 17 and data["stop"] == ["</s>"] and timeout == 12
    assert not request.has_header("Authorization") and "never-send" not in str(request.headers)
    assert transport.handlers[0].proxies == {}
    assert isinstance(transport.handlers[1], leanstral._NoRedirect)


def test_default_model_and_text_blocks(transport):
    transport.payload["choices"][0]["message"]["content"] = [{"type": "text", "text": "sim"}, {"type": "text", "text": "p"}]
    assert llm_router.generate_text("tactic", provider="leanstral_local") == "simp"
    assert llm_router.get_last_generation_trace()["effective_model_name"] == "Leanstral"


@pytest.mark.parametrize("url", ["http://172.17.0.1:8080/v1", "http://127.0.0.1:9011/v1/",
                                "http://localhost:8080/v1/chat/completions"])
def test_explicit_local_endpoints_only(transport, url):
    assert leanstral.chat_completion("tactic", base_url=url)["text"] == "simp"
    assert transport.calls[0][0].full_url == leanstral.endpoint(url)


@pytest.mark.parametrize("url", ["https://api.mistral.ai/v1", "http://example.com:8080/v1",
    "http://127.0.0.1:8080/v1?key=hidden", "http://name:pass@127.0.0.1:8080/v1",
    "http://172.17.0.1:8080/v1#fragment", "http://127.0.0.1:0/v1", "http://127.0.0.1/v1",
    "http://127.0.0.1:8080/elsewhere", "http://127.0.0.1:65536/v1", "http://localhost:8080/v1\n"])
def test_endpoint_escape_rejected_before_request(transport, url):
    with pytest.raises(leanstral.LeanstralError): leanstral.chat_completion("tactic", base_url=url)
    assert not transport.calls


@pytest.mark.parametrize("options", [{"max_new_tokens": 0}, {"max_new_tokens": -1}, {"max_new_tokens": True},
    {"max_new_tokens": 32769}, {"timeout": 0}, {"timeout": float("inf")}, {"timeout": True},
    {"temperature": float("nan")}, {"temperature": -1}, {"temperature": 3},
    {"stop": "not-a-list"}, {"stop": [""]}, {"stop": ["x"] * 17}, {"model": "gpt-fixture"}])
def test_zero_and_malformed_limits_do_not_call_model(transport, options):
    with pytest.raises(leanstral.LeanstralError): leanstral.chat_completion("tactic", **options)
    assert not transport.calls


@pytest.mark.parametrize("damage", ["model", "missing_model", "bad_model_type", "no_choices", "two_choices",
    "empty", "null_message", "thinking_only", "tool", "usage_negative", "usage_bool", "usage_float", "id"])
def test_malformed_or_wrong_model_response_fails_closed(transport, damage):
    data = transport.payload = copy.deepcopy(response())
    message = data["choices"][0]["message"]
    if damage == "model": data["model"] = "other-model"
    elif damage == "missing_model": del data["model"]
    elif damage == "bad_model_type": data["model"] = {}
    elif damage == "no_choices": data["choices"] = []
    elif damage == "two_choices": data["choices"] *= 2
    elif damage == "empty": message["content"] = " "
    elif damage == "null_message": data["choices"][0]["message"] = None
    elif damage == "thinking_only": message["content"] = [{"type": "thinking", "text": "not a tactic"}]
    elif damage == "tool": message["tool_calls"] = [{"name": "shell"}]
    elif damage == "usage_negative": data["usage"]["completion_tokens"] = -1
    elif damage == "usage_bool": data["usage"]["completion_tokens"] = False
    elif damage == "usage_float": data["usage"]["completion_tokens"] = 1.5
    else: data["id"] = {}
    with pytest.raises(llm_router.LLMRouterError): llm_router.generate_text("tactic", provider="leanstral_local")
    assert len(transport.calls) == 1 and llm_router.get_last_generation_trace() == {}


@pytest.mark.parametrize("error", [TimeoutError("sensitive body"),
    urllib.error.HTTPError("http://localhost", 503, "sensitive body", {}, io.BytesIO(b"sensitive body")),
    urllib.error.URLError("sensitive body")])
def test_no_retry_fallback_or_stale_success_on_error(transport, error):
    llm_router.generate_text("tactic", provider="leanstral")
    transport.calls.clear(); transport.error = error
    with pytest.raises(llm_router.LLMRouterError) as exc:
        llm_router.generate_text("tactic", provider="leanstral", allow_cross_provider_fallback=True)
    assert "sensitive" not in str(exc.value)
    assert len(transport.calls) == 1 and llm_router.get_last_generation_trace() == {}


def test_bounded_response_nonfinite_json_and_redirects(transport, monkeypatch):
    transport.raw = b"x" * 33
    monkeypatch.setattr(leanstral, "MAX_RESPONSE_BYTES", 32)
    with pytest.raises(leanstral.LeanstralError, match="byte budget"): leanstral.chat_completion("tactic")
    transport.raw = b'{"bad":NaN}'
    with pytest.raises(leanstral.LeanstralError): leanstral.chat_completion("tactic")
    transport.final_url = "http://example.invalid/escape"
    with pytest.raises(leanstral.LeanstralError, match="endpoint"): leanstral.chat_completion("tactic")
    with pytest.raises(leanstral.LeanstralError, match="redirects"):
        leanstral._NoRedirect().redirect_request(None, None, 302, "", {}, "http://elsewhere")


def test_warmup_healthy_path_reaches_in_tree_http_client(harness, transport):
    result = harness.maybe_generate("tactic", health=harness._fake_health(True), max_new_tokens=32, timeout=15)
    assert result.text == "simp" and not result.skipped and not result.error
    assert result.identity.resolved_provider == "leanstral_local" and not result.identity.fallback_used
    assert len(transport.calls) == 1
    assert harness.lra_gt._load_router()[0] is llm_router.generate_text


def test_warmup_down_skips_and_transport_failure_is_not_success(harness, transport):
    down = harness.maybe_generate("tactic", health=harness._fake_health(False))
    assert down.skipped and down.text == "" and not transport.calls
    transport.error = TimeoutError()
    failed = harness.maybe_generate("tactic", health=harness._fake_health(True))
    assert not failed.skipped and failed.text == "" and failed.error
    assert len(transport.calls) == 1


@pytest.mark.parametrize("other", ["--run", "--probe-health", "--plan", "--name"])
def test_offline_cli_cannot_select_live_operations(harness, monkeypatch, other):
    monkeypatch.setattr(harness._jevops_path, "activate_lra_hooks", lambda: None)
    with pytest.raises(SystemExit) as exc:
        harness.main(["--offline-self-check", other, *(["name"] if other == "--name" else [])])
    assert exc.value.code == 2


def test_full_warmup_offline_protocol_preserved(harness, transport):
    report = harness.self_check(offline=True)
    assert report["ok"], report
    assert report["offline_fixtures"] and not report["live_health_checked"]
    assert report["arena_score"] is None and report["autostart"] == "0"
    assert report["called_leanstral_when_health_ok"] and report["skip_generate_only_if_docker0_down"]
    assert report["putnam_generated_failed_retained"]
    assert not transport.calls  # Synthetic generator AND synthetic compiler, never a live model.


@pytest.mark.parametrize("text,valid", [("simp", True), ("rfl<|im_end|>", True),
    ("sorry", False), ("theorem fake : True := by trivial", False)])
def test_http_output_still_goes_through_warmup_admission(harness, transport, text, valid):
    transport.payload = response(text)
    result = harness.run_warmup(health=harness._fake_health(True), limit=1, plant_synthetic=True)
    row = result["results"][0]
    generated = next(c for c in row["candidates"] if c["kind"] == "generated")
    assert generated["valid"] is valid
    if not valid:
        assert row["kept_kind"] in {"reference", "reference_stripped"}
    assert row["called_leanstral"] and result["arena_score"] is None
    assert len(transport.calls) == 1


def test_health_probe_is_readonly_and_redacts_errors(transport):
    assert leanstral.health_status("http://127.0.0.1:8080/health") == (200, "")
    assert transport.calls[0][0].get_method() == "GET"
    transport.error = urllib.error.URLError("sensitive server response")
    code, error = leanstral.health_status("http://127.0.0.1:8080/health")
    assert code is None and "sensitive" not in error
    with pytest.raises(leanstral.LeanstralError): leanstral.health_status("http://elsewhere:8080/health")


def test_local_toolchain_does_not_import_external_frontend(harness):
    module = importlib.import_module("lean_toolchain")
    assert module._external_module() is None
    assert module._EXTERNAL is None


def test_alias_health_failure_does_not_report_primary_failure(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    module = importlib.import_module("generate_text")
    monkeypatch.setattr(module, "_pin_client_env", lambda: None)
    monkeypatch.setattr(module, "_http_get", lambda url, **kwargs:
                        (200, "") if url == module.DOCKER0_HEALTH_URL else (None, "alias unavailable"))
    health = module.probe_docker0_health()
    assert health.ok and not health.alias_ok and not health.error


@pytest.mark.parametrize("redirect", [False, True])
def test_real_loopback_http_protocol_without_a_model(harness, monkeypatch, redirect):
    """Real sockets, deterministic fake server; never claims a live model call."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, payload, dict(self.headers)))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/unexpected")
                self.end_headers()
                return
            raw = json.dumps(response()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.delenv("JEVOPS_USE_EXTERNAL_ROUTER", raising=False)
        monkeypatch.setattr(harness.lra_gt, "DOCKER0_OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
        try:
            result = harness.maybe_generate("tactic", health=harness._fake_health(True), timeout=3)
        finally:
            server.shutdown(); thread.join(timeout=3)
    assert len(calls) == 1 and calls[0][0] == "/v1/chat/completions"
    assert "Authorization" not in calls[0][2]
    assert bool(result.error) is redirect
    assert result.text == ("" if redirect else "simp")
