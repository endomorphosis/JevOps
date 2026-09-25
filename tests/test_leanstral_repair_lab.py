"""Offline protocol fixtures, never actual Leanstral or native proof evidence."""
from dataclasses import replace
import fcntl
import io
import json
import re
import sqlite3
from types import SimpleNamespace
import urllib.request

import pytest

from jevops.arena import ArenaContext, Outcome, VerificationRequest, VersionReceipt, source_hash
from jevops.arena_trial import _pins
from jevops.leanstral_prompt_contracts import bind_response, request_binding
from jevops.leanstral_repair_lab import IsolatedBackend, Limits, LocalTokenCounter, RepairLab, bound_feedback
from tests.test_arena_trial import RECORD


class Backend:
    def __init__(self, *, control_outcome=Outcome.VERIFIED, candidate_outcome=None, corrupt=None):
        self.control_outcome, self.candidate_outcome, self.corrupt = control_outcome, candidate_outcome, corrupt
        self.calls = []

    def prepare(self, record):
        self.contexts = {p: ArenaContext(record["name"], record["statement"], record["src"], 15, None,
            (p,), ("a" * 64,), "fixture-verifier", "1", "fixture-method") for p in _pins(record)}
        return self.contexts

    def check(self, record, source, pin):
        self.calls.append((source, pin))
        outcome = (self.control_outcome if source == record["src"] else self.candidate_outcome or
                   (Outcome.REJECTED if "missing_h" in source else Outcome.VERIFIED))
        request = VerificationRequest(self.contexts[pin], source, pin)
        receipt = VersionReceipt(request.request_id, source_hash(source), record["name"], outcome,
            type_preserved=outcome == Outcome.VERIFIED, exit_code=0,
            axiom_output=f"'{record['name']}' depends on axioms: []",
            observations_json=json.dumps({"report": {"diagnostics": [{"message": "unknown identifier missing_h"}]}}))
        if self.corrupt and source != record["src"]:
            receipt = replace(receipt, **self.corrupt)
        return receipt


def generate(messages, arm):
    rid = re.search(r"Request: ([0-9a-f]{16})", messages[-1]["content"])[1]
    tactic = "exact h" if "CURRENT_ATTEMPT_DATA" in messages[-1]["content"] else "exact missing_h"
    raw = json.dumps({"request_id": rid, "tactic": tactic})
    return {"text": raw, "finish_reason": "stop", "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "client_binding": bind_response(request_binding(messages, arm), raw)}


@pytest.fixture
def build(tmp_path, monkeypatch):
    # Source mutation has its own real-guard test; avoid repeatedly hashing the
    # full checkout in unrelated offline protocol checks.
    monkeypatch.setattr(RepairLab, "_guard", lambda self: self.guard() if self.guard else None)
    def make(**kwargs):
        return RepairLab(tmp_path / "run", kwargs.pop("cases", [{"record": RECORD, "split": "development"}]),
            backend=kwargs.pop("backend", Backend()), generator=kwargs.pop("generator", generate),
            counter=kwargs.pop("counter", lambda _: 30), **kwargs)
    return make


def test_online_feedback_is_own_chain_and_primary_metric_is_native_validity(build):
    lab = build()
    report = lab.run()
    assert report["complete"] and report["model_calls"] == 6 and report["native_requests"] == 7
    assert report["evidence_mode"] == "offline_fixture" and report["official_score"] is None
    arms = report["cases"][0]["arms"]
    assert arms["independent"]["valid_attempts"] == 0
    assert arms["compiler-feedback"]["valid_attempts"] == 1
    assert not any("CURRENT_ATTEMPT_DATA" in t["messages"][-1]["content"] for t in arms["independent"]["trials"])
    repair = arms["compiler-feedback"]["trials"]
    assert "CURRENT_ATTEMPT_DATA" not in repair[0]["messages"][-1]["content"]
    assert repair[0]["source_sha256"] in repair[1]["messages"][-1]["content"]
    assert "unknown identifier missing_h" in repair[1]["messages"][-1]["content"]
    assert repair[0]["messages"] == arms["independent"]["trials"][0]["messages"]
    assert not report["promotion"] and not report["training"] and not report["performance_confirmation"]
    for arm in arms.values():
        assert arm["tokens_reserved"] == 3 * (30 + 1024) and arm["tokens_observed"] == 90
    assert (lab.directory / "results.md").exists()
    with sqlite3.connect(lab.directory / "calls.sqlite") as db:
        assert db.execute("SELECT count(*) FROM calls").fetchone()[0] == 13
        saved = json.loads(db.execute("SELECT input FROM calls WHERE kind='model' LIMIT 1").fetchone()[0])
        assert "messages" in saved and saved["max_new_tokens"] == 1024


@pytest.mark.parametrize("outcome", list(Outcome)[1:])
def test_no_model_or_tokenizer_calls_if_any_reference_control_fails(build, outcome):
    lab = build(backend=Backend(control_outcome=outcome),
        generator=lambda *_: pytest.fail("no model before all controls"), counter=lambda *_: pytest.fail("no tokenization"))
    report = lab.run()
    assert not report["complete"] and report["model_calls"] == 0
    assert report["native_requests"] == 1 and report["cases"][0]["status"] == "ENVIRONMENT_FAILED"


@pytest.mark.parametrize("outcome", [Outcome.TIMEOUT, Outcome.ERROR, Outcome.UNAVAILABLE, Outcome.BUDGET_EXHAUSTED])
def test_native_resource_failures_are_unknown_stop_further_generation(build, outcome):
    report = build(backend=Backend(candidate_outcome=outcome)).run()
    assert not report["complete"] and report["model_calls"] == 1
    trial = next(iter(report["cases"][0]["arms"].values()))["trials"][0]
    assert trial["all_pin_valid"] is None and trial["status"] == "NATIVE_UNMEASURED"
    assert bound_feedback(trial["source"], trial["checks"]) is None


@pytest.mark.parametrize("corrupt", [{"request_id": "0" * 64}, {"candidate_sha256": "0" * 64},
                                    {"target": "other"}, {"type_preserved": False},
                                    {"axiom_output": "'example' depends on axioms: [sorryAx]"}])
def test_invalid_native_receipt_cannot_be_scored_or_fed_back(build, corrupt):
    report = build(backend=Backend(candidate_outcome=Outcome.VERIFIED, corrupt=corrupt)).run()
    assert not report["complete"] and report["model_calls"] == 1
    assert next(iter(report["cases"][0]["arms"].values()))["valid_attempts"] == 0


@pytest.mark.parametrize("damage", ["missing_usage", "prompt_underquote", "oversized_output", "missing_binding", "wrong_id", "eos", "intake"])
def test_protocol_and_accounting_fail_closed(build, damage):
    def broken(messages, arm):
        result = generate(messages, arm)
        if damage == "missing_usage": result.pop("usage")
        elif damage == "prompt_underquote": result["usage"]["prompt_tokens"] = 31
        elif damage == "oversized_output": result["usage"]["completion_tokens"] = 1025
        elif damage == "missing_binding": result.pop("client_binding")
        else:
            obj = json.loads(result["text"])
            if damage == "wrong_id": obj["request_id"] = "wrong"
            elif damage == "intake": obj["tactic"] = "sorry"
            result["text"] = json.dumps(obj) + ("<|im_end|>" if damage == "eos" else "")
            result["client_binding"] = bind_response(request_binding(messages, arm), result["text"])
        return result
    report = build(generator=broken).run()
    assert report["native_requests"] == 1
    if damage in ("wrong_id", "eos", "intake"):
        assert report["complete"] and report["model_calls"] == 6
        assert all(a["valid_attempts"] == 0 for a in report["cases"][0]["arms"].values())
    else:
        assert not report["complete"] and report["model_calls"] == 1


def test_token_ceiling_refuses_generation_and_does_not_reallocate(build):
    report = build(limits=Limits(total_tokens_per_arm_case=128)).run()
    assert report["model_calls"] == 0 and not report["complete"]
    assert next(iter(report["cases"][0]["arms"].values()))["trials"][0]["status"] == "BUDGET_EXHAUSTED"


@pytest.mark.parametrize("category,status,expected", [
    ("timeout", None, {"error_category": "timeout"}),
    ("http_error", 503, {"error_category": "http_error", "http_status": 503}),
    ("http_error", True, {"error_category": "http_error"}),
    ("http_error", 999, {"error_category": "http_error"}),
    ("unknown_sensitive_category", 503, {}),
])
def test_router_failure_metadata_is_bounded_unknown_and_never_retried(build, category, status, expected):
    from jevops.llm_router import LLMRouterError
    def broken(*_):
        raise LLMRouterError("synthetic-private-server-body", category=category, http_status=status)
    report = build(generator=broken).run()
    assert not report["complete"] and report["model_calls"] == 1 and report["native_requests"] == 1
    trial = next(iter(report["cases"][0]["arms"].values()))["trials"][0]
    assert trial["all_pin_valid"] is None
    assert trial["generation"] == {"status": "UNMEASURED", "error_type": "LLMRouterError", **expected}
    assert "synthetic-private-server-body" not in json.dumps(report)
    assert "unknown_sensitive_category" not in json.dumps(report)


def test_cannot_rerun_or_retry_existing_run(build):
    lab = build()
    report = lab.run()
    before = (lab.directory / "report.json").read_bytes()
    with pytest.raises(FileExistsError): lab.run()
    assert (lab.directory / "report.json").read_bytes() == before
    assert report["model_calls"] == 6


def test_interrupt_reservation_is_durable_and_not_retried(build):
    lab = build(generator=lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt): lab.run()
    with sqlite3.connect(lab.directory / "calls.sqlite") as db:
        assert db.execute("SELECT count(*) FROM calls WHERE kind='model' AND result IS NULL").fetchone()[0] == 1
    with pytest.raises(FileExistsError): lab.run()


def test_all_pins_required_not_just_first_success(build):
    record = {**RECORD, "version_info": [*RECORD["version_info"], {"v4.27.0": "b" * 40}]}
    class OneMissing(Backend):
        def prepare(self, record):
            result = super().prepare(record)
            result.pop(next(reversed(result)))
            return result
    report = build(cases=[{"record": record, "split": "development"}], backend=OneMissing()).run()
    assert not report["complete"] and report["model_calls"] == report["native_requests"] == 0


def test_cross_split_content_overlap_and_implicit_live_fixture_refused(tmp_path):
    copy = {**RECORD, "name": "other"}
    with pytest.raises(ValueError, match="overlap"):
        RepairLab(tmp_path, [{"record": RECORD, "split": "development"}, {"record": copy, "split": "confirmation"}],
                  backend=Backend(), generator=generate, counter=lambda _: 30)
    with pytest.raises(ValueError, match="offline"):
        RepairLab(tmp_path, [{"record": RECORD, "split": "development"}], backend=Backend())


def test_source_guard_rejects_stale_implementation_before_model(tmp_path):
    lab = RepairLab(tmp_path / "run", [{"record": RECORD, "split": "development"}],
                    backend=Backend(), generator=generate, counter=lambda _: 30)
    lab.plan["implementation"]["leanstral_repair_lab.py"] = "0" * 64
    with pytest.raises(ValueError, match="implementation changed"): lab.run()


def test_source_guard_rejects_changed_inventory(tmp_path):
    lab = RepairLab(tmp_path / "run", [{"record": RECORD, "split": "development"}],
                    backend=Backend(), generator=generate, counter=lambda _: 30)
    lab.plan["implementation"].pop("leanstral_repair_lab.py")
    with pytest.raises(ValueError, match="inventory changed"): lab.run()


@pytest.mark.parametrize("memory_gib", [2, 4, 8])
def test_native_adapter_requires_isolation_and_binds_every_pin(tmp_path, monkeypatch, memory_gib):
    from jevops import arena_isolation, leanstral_repair_lab as module
    record = {**RECORD, "url": "https://example.invalid/fixture",
              "version_info": [*RECORD["version_info"], {"v4.27.0": "b" * 40}]}
    (tmp_path / "inputs").mkdir()
    projects = [{"repository": record["url"], **p.to_dict()} for p in _pins(record)]
    (tmp_path / "inputs/projects.json").write_text(json.dumps(projects))
    calls, instances = [], []
    class Isolation:
        def __init__(self, socket, image, **kw):
            assert kw == {"mount_owner_user": False, "memory_bytes": memory_gib * 1024**3}
            self.identity = (str(socket), image)
        def preflight(self, **kw): calls.append(("preflight", kw))
    class Verifier:
        def __init__(self, bindings, **kw):
            self.bindings, self.kw = bindings, kw
            instances.append(self)
        def context(self, one_pin_record):
            assert len(one_pin_record["version_info"]) == 1
            assert set(_pins(one_pin_record)) == set(self.bindings)
            return next(iter(Backend().prepare(one_pin_record).values()))
        def __call__(self, request):
            calls.append(("check", request))
            return "native-receipt-fixture"
    monkeypatch.setattr(arena_isolation, "DockerIsolation", Isolation)
    monkeypatch.setattr(module, "NativeLeanVerifier", Verifier)
    monkeypatch.setattr(module, "project_binding", lambda r, p, project, elan: (p, project, elan))
    cfg = SimpleNamespace(runtime=str(tmp_path), docker_socket="/fixture/socket", docker_image="fixture",
                          state=str(tmp_path), elan_home=str(tmp_path / "elan"), timeout_seconds=30)
    backend = IsolatedBackend(cfg, memory_gib=memory_gib)
    contexts = backend.prepare(record)
    assert set(contexts) == set(_pins(record)) and len(instances) == 2
    assert calls[0][0] == "preflight"
    assert all(v.kw["isolation"] is backend.isolation and v.kw["max_processes"] == 7 for v in instances)
    assert instances[0].kw["fingerprinter"] is instances[1].kw["fingerprinter"]
    assert backend.check(record, record["src"], _pins(record)[0]) == "native-receipt-fixture"
    assert calls[-1][1].context == contexts[_pins(record)[0]]
    backend.projects.pop()
    with pytest.raises(ValueError, match="every pin"): backend.prepare(record)


def test_counter_failure_spends_no_model_budget(build):
    def broken(_): raise ValueError("no server token quote")
    report = build(counter=broken).run()
    assert not report["complete"] and report["model_calls"] == 0
    assert report["cases"][0]["status"] == "SETUP_OR_TRANSPORT_FAILED"


@pytest.mark.parametrize("mount_owner", [False, True])
@pytest.mark.parametrize("memory_gib", [2, 4, 8])
def test_busy_shared_lock_does_not_create_run_or_execute(tmp_path, monkeypatch, capsys, mount_owner, memory_gib):
    from jevops import improvement_service as service, leanstral_repair_lab as module
    from pathlib import Path
    cfg = service.Config(runtime=str(tmp_path), snapshot_sha256="a" * 64, state=str(tmp_path / "state"),
                         volume_config=str(tmp_path / "preparation.json"), development=(RECORD["name"],),
                         holdouts=("heldout",), elan_home=str(tmp_path), docker_socket="/fixture/socket",
                         docker_image="fixture")
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps(RECORD) + "\n")
    monkeypatch.setattr(module, "CORPUS", corpus)
    monkeypatch.setattr(service.Config, "load", lambda _: cfg)
    monkeypatch.setattr(service, "storage_guard", lambda _: None)
    class PreviewBackend:
        def __init__(self, config, **kw):
            assert kw == {"mount_owner_user": mount_owner, "memory_gib": memory_gib}
            self.config, self.projects, self.rounds = config, [], 3
            self.isolation = SimpleNamespace(policy={"profile": "fixture"})
    monkeypatch.setattr(module, "IsolatedBackend", PreviewBackend)
    monkeypatch.setattr(module.RepairLab, "run", lambda _: pytest.fail("must not run"))
    output = tmp_path / "new-run"
    with (Path(cfg.volume_config).parent / "single-build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert module.main(["--watcher-config", "unused", "--output", str(output),
                            "--problem", RECORD["name"], "--run", *(["--mount-owner-user"] if mount_owner else []),
                            *(["--memory-gib", str(memory_gib)] if memory_gib != 2 else [])]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "LOCK_BUSY" and not report["executed"]
    assert report["model_calls"] == report["native_requests"] == 0 and not output.exists()


@pytest.mark.parametrize("memory_gib", [0, 16, True, "4", 4.0])
def test_backend_memory_cap_validation_precedes_preparation(memory_gib):
    with pytest.raises(ValueError, match="memory cap"):
        IsolatedBackend(None, memory_gib=memory_gib)


@pytest.mark.parametrize("change", [{"rounds": 4}, {"rounds": True}, {"max_new_tokens": -1}, {"timeout": 61}])
def test_bounded_limits(change):
    with pytest.raises(ValueError): Limits(**change)


def test_tokenizer_uses_rendered_template_no_proxy_redirect_or_generation(monkeypatch):
    calls, handlers = [], []
    class Transport:
        def open(self, req, timeout):
            calls.append((req.full_url, json.loads(req.data)))
            value = {"prompt": "<bos>fixture"} if req.full_url.endswith("apply-template") else {"tokens": [1, 2, 3]}
            stream = io.BytesIO(json.dumps(value).encode())
            stream.status = 200
            stream.geturl = lambda: req.full_url
            return stream
    def opener(*args):
        handlers.extend(args)
        return Transport()
    monkeypatch.setattr(urllib.request, "build_opener", opener)
    assert LocalTokenCounter()([{"role": "user", "content": "test"}]) == 3
    assert [p.rsplit("/", 1)[1] for p, _ in calls] == ["apply-template", "tokenize"]
    assert calls[1][1] == {"content": "<bos>fixture", "add_special": True, "parse_special": True, "with_pieces": False}
    assert handlers[0].proxies == {}


@pytest.mark.parametrize("payload", [{"tokens": []}, {"tokens": [True]}, {"tokens": [-1]}, {"tokens": "3"}])
def test_unknown_or_bad_token_quote_cannot_fallback_to_character_count(monkeypatch, payload):
    monkeypatch.setattr(LocalTokenCounter, "_post", lambda _, path, body: {"prompt": "fixture"} if path == "/apply-template" else payload)
    with pytest.raises(ValueError): LocalTokenCounter()([{"role": "user", "content": "test"}])
