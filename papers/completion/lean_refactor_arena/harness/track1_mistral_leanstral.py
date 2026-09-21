#!/usr/bin/env python3
"""Track 1 scored generator: Mistral Labs hosted Leanstral.

Local docker0 NVFP4 is prototype only. This adapter POSTs to
``https://api.mistral.ai/v1/chat/completions`` with model
``labs-leanstral-1-5``. It never calls ``172.17.0.1:8080``, never
``LOCK_EX``, never starts llama-server, and never falls back to grok or
local GGUF. Official Track 2 stays off. Labs preview pricing is treated
as US$0 and still logged. Jev in-loop cost counts toward the US$3 cap.
Not an Arena ranking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
KEYFILES = (
    Path.home() / ".config/ipfs_accelerate_py/mistral.env",
    Path.home() / ".vibe" / ".env",
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import generate_text as lra_gt  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402
import typesafe_router as lra_ts  # noqa: E402

ROOT_ACCEL = _jevops_path.IPFS_ACCELERATE_ROOT
KEYFILES = (*KEYFILES, _jevops_path.TYPESAFE_KEYFILE)

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
PROTOCOL = "LRA/v1"
PR_ID = "PR-12b"
LRAH_ID = "LRAH-011b"
TRACK_LABEL = "track1_closed"
REQUESTED_PROVIDER = "mistral"
REQUESTED_MODEL = "labs-leanstral-1-5"
ALT_MODELS = ("labs-leanstral-1-5", "leanstral-1-5")
API_HOST = "api.mistral.ai"
CHAT_URL = f"https://{API_HOST}/v1/chat/completions"
LABS_RETIRE_DATE = "2026-09-30"
HARDWARE_CLASS = "mistral_labs_api"
PROTOTYPE_HARDWARE_CLASS = "spark_gb10"
PROTOTYPE_BASE_URL = "http://172.17.0.1:8080/v1"
MAX_NEW_TOKENS_DEFAULT = 256
TIMEOUT_DEFAULT = 180.0
KEY_ENV_NAMES = (
    "MISTRAL_API_KEY",
    "IPFS_ACCELERATE_MISTRAL_API_KEY",
    "IPFS_ACCELERATE_PY_MISTRAL_API_KEY",
    "ipfs_accelerate_py_MISTRAL_API_KEY",
    "IPFS_DATASETS_PY_MISTRAL_API_KEY",
)
FORBIDDEN_HOSTS = frozenset({"172.17.0.1", "127.0.0.1", "localhost", "0.0.0.0"})
FORBIDDEN_PROVIDERS = frozenset(
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
CANARY_NAME = "CallElimCorrect.substOldPostSubset"
FORBIDDEN_IMPORT_NAMES = frozenset({"fcntl", "typesafe_sdk", "LeanstralProofProvider"})


class Track1MistralError(RuntimeError):
    """Fail-closed hosted Leanstral error. Never a local GGUF success."""


def load_keyfiles() -> None:
    from jevops.outer import load_env_file

    for path in KEYFILES:
        load_env_file(path, strip_quotes=True)


def pin_paths() -> None:
    from jevops.outer import pin_sys_path

    pin_sys_path(
        ROOT_ACCEL,
        defaults={
            "IPFS_ACCEL_SKIP_CORE": "1",
            "IPFS_AUTO_INSTALL": "false",
            "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0",
        },
    )
    lra_ts.ACCEL_ROOT = ROOT_ACCEL
    lra_ts.TYPESAFE_INFERENCE_PATH = _jevops_path.TYPESAFE_INFERENCE_PATH


def mistral_key_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    from jevops.jev import any_key

    from jevops.outer import env_mapping

    return any_key(env_mapping(env), KEY_ENV_NAMES)


def resolve_mistral_key(env: Optional[Mapping[str, str]] = None) -> str:
    from jevops.outer import env_mapping, first_nonempty

    value = first_nonempty(env_mapping(env), *KEY_ENV_NAMES)
    if not value:
        raise Track1MistralError("MISTRAL_API_KEY is not set")
    return value


def _redact_text(text: str, secret: str) -> str:
    from jevops.outer import redact_secret

    return redact_secret(text, secret)


def assert_hosted_url(url: str) -> None:
    from jevops.outer import require_host

    require_host(
        url,
        API_HOST,
        forbidden=FORBIDDEN_HOSTS,
        error_cls=Track1MistralError,
        prototype_fmt="refusing prototype host {host!r}; Track 1 must use {expected}",
        mismatch_fmt="refusing non-Labs host {host!r}; expected {expected}",
    )


def chat_completions(
    prompt: str,
    *,
    model: str = REQUESTED_MODEL,
    max_tokens: int = MAX_NEW_TOKENS_DEFAULT,
    timeout: float = TIMEOUT_DEFAULT,
    url: str = CHAT_URL,
    temperature: float = 0.0,
    n: int = 1,
    stop: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """POST chat/completions to Mistral Labs. Never docker0."""

    assert_hosted_url(url)
    key = resolve_mistral_key()
    from jevops.outer import chat_request_payload, elapsed_ms, http_json, pack_chat_response

    payload = chat_request_payload(
        prompt,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        n=n,
        stop=stop,
    )
    started = time.perf_counter()
    status, data, final_url = http_json(
        url,
        payload,
        timeout=float(timeout),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        error_cls=Track1MistralError,
        redact_fn=lambda message: _redact_text(message, key),
        http_fmt="Mistral HTTP {status}: {body}",
        json_fmt="Mistral returned invalid JSON: {exc}",
        not_object="Mistral returned a non-object JSON payload",
    )
    assert_hosted_url(final_url or url)
    return pack_chat_response(
        data,
        status=status,
        url=final_url or url,
        wall_ms=elapsed_ms(started),
        model=model,
        extra={
            "hardware_class": HARDWARE_CLASS,
            "prototype_base_url": PROTOTYPE_BASE_URL,
            "used_prototype_endpoint": False,
        },
    )


def generate_mistral(
    prompt: str,
    ledger: lra_t1.ProblemLedger,
    *,
    max_new_tokens: int = MAX_NEW_TOKENS_DEFAULT,
    timeout: float = TIMEOUT_DEFAULT,
    model: str = REQUESTED_MODEL,
    fixture: bool = False,
    fixture_text: str = "simp_all",
) -> tuple[str, dict[str, Any], lra_t1.UsageLine]:
    from jevops.outer import ledger_generate

    estimated_in = lra_t1.estimate_tokens(prompt)
    estimated_out = int(max_new_tokens)

    def _identity(*, model: str, fixture: bool, extra: Optional[Mapping[str, Any]] = None, text: str = "") -> dict[str, Any]:
        del text
        from jevops.lean import hosted_identity

        return hosted_identity(
            requested_provider=REQUESTED_PROVIDER,
            requested_model=model,
            fixture=fixture,
            extra=extra,
            api_host=API_HOST,
            hardware_class=HARDWARE_CLASS,
            error_cls=Track1MistralError,
            host_fmt="resolved host is not {host}",
        )

    def _live() -> tuple[str, Mapping[str, Any], tuple[int, int]]:
        payload = chat_completions(
            prompt,
            model=model,
            max_tokens=max_new_tokens,
            timeout=timeout,
        )
        inn = int(payload.get("input_tokens") or estimated_in)
        out = int(payload.get("output_tokens") or lra_t1.estimate_tokens(payload["text"]))
        return str(payload["text"]), payload, (inn, out)

    return ledger_generate(
        ledger,
        "mistral",
        estimated_in=estimated_in,
        estimated_out=estimated_out,
        model=model,
        fixture=fixture,
        fixture_text=fixture_text,
        live_fn=_live,
        identity_fn=_identity,
        error_cls=Track1MistralError,
        estimate_fn=lra_t1.estimate_tokens,
        refuse_fmt="mistral call refused: {reason}",
        after_fmt="mistral spend refused after call: {reason}",
    )


def redact(payload: Any) -> Any:
    from jevops.jev import redact as _fn

    return _fn(payload, exact=("authorization", "bearer"), prefixes=("apikey_", "sk-"))


def run_named(
    name: str,
    *,
    max_new_tokens: int = MAX_NEW_TOKENS_DEFAULT,
    timeout: float = TIMEOUT_DEFAULT,
    official_track2: bool = False,
    fixture: bool = False,
    path: Optional[Path] = None,
) -> dict[str, Any]:
    from jevops.outer import env_copy

    pin_paths()
    from jevops.outer import closed_skip

    if official_track2 or lra_ts.official_track2_requested():
        return closed_skip(
            "official_track2_off",
            extra={"called_jev": False, "contaminates_track2": False},
        )
    record, records, digest = lra_t1._load_named_record(name, path)
    ledger = lra_t1.ProblemLedger(name=name, official_track2=False)
    if not fixture and not (mistral_key_configured() and lra_t1.jev_key_configured()):
        return closed_skip(
            "no_key",
            extra={
                "name": name,
                "mistral_key_configured": mistral_key_configured(),
                "jev_key_configured": lra_t1.jev_key_configured(),
            },
        )
    neighbors = lra_t1._neighbors_for(record, records)
    state = lra_ts.problem_state(record, neighbors=neighbors)
    factory = None
    if fixture:
        factory = lambda **kwargs: lra_ts.FixtureClient(answers=lra_ts.default_fixture_answers(), **kwargs)
    router = lra_ts.TypeSafeLraRouter(
        mode="inloop",
        official_track2=False,
        env=env_copy({"LRA_TYPESAFE": "inloop"}),
        client_factory=factory,
        require_key=not fixture,
    )
    from jevops.outer import elapsed_ms

    started = time.perf_counter()
    jev_result = router.route(state, neighbor_names=[item["name"] for item in neighbors])
    ledger.record(
        "jev",
        input_tokens=int((jev_result.usage or {}).get("input_tokens") or 0),
        output_tokens=int((jev_result.usage or {}).get("output_tokens") or 0),
        fixture=fixture or bool(jev_result.used_fixture),
        model=jev_result.model or lra_t1.JEV_MODEL_ID,
    )
    prompt = lra_gt.render_prompt(record)
    text, identity, _line = generate_mistral(
        prompt,
        ledger,
        max_new_tokens=max_new_tokens,
        timeout=timeout,
        fixture=fixture,
    )
    from jevops.jev import hosted_run_payload

    return redact(
        hosted_run_payload(
            name=name,
            source=record.get("source"),
            digest=digest,
            identity=identity,
            text=text,
            jev_route=jev_result.as_dict(),
            ledger=ledger.as_dict(),
            wall_ms=elapsed_ms(started),
            requested_provider=REQUESTED_PROVIDER,
            requested_model=REQUESTED_MODEL,
            hardware_class=HARDWARE_CLASS,
            prototype_hardware=PROTOTYPE_HARDWARE_CLASS,
            protocol=PROTOCOL,
            pr=PR_ID,
            track=TRACK_LABEL,
            labs_retire_date=LABS_RETIRE_DATE,
        )
    )


def audit_source() -> dict[str, Any]:
    from jevops.outer import read_text
    from jevops.repair import audit_source as _audit

    text = read_text(__file__)
    out = _audit(text, forbidden_imports=FORBIDDEN_IMPORT_NAMES)
    imported = set(out["imported_names"])
    return {
        "forbidden_imports": out["forbidden_imports"],
        "uses_lock_ex": out["uses_lock_ex"],
        "mentions_prototype_url": PROTOTYPE_BASE_URL in text,
        "ok": not out["uses_lock_ex"] and "typesafe_sdk" not in imported,
    }


def self_check() -> dict[str, Any]:
    audit = audit_source()
    ledger = lra_t1.ProblemLedger(name="fixture")
    text, identity, line = generate_mistral("ping", ledger, fixture=True, fixture_text="simp")
    refused = False
    try:
        assert_hosted_url("http://172.17.0.1:8080/v1/chat/completions")
    except Track1MistralError:
        refused = True
    mistral_mode = lra_t1.resolve_track1_mode(env={"LRA_GENERATOR": "mistral_labs"})
    track2 = lra_t1.resolve_track1_mode(
        env={"LRA_GENERATOR": "mistral_labs", "LRA_OFFICIAL_TRACK2": "1"}
    )
    zero = lra_t1.usd_for("mistral", 1_000_000, 1_000_000)
    report = {
        "ok": True,
        "audit": audit,
        "fixture_text": text,
        "fixture_host": identity.get("url_host"),
        "fixture_usd": line.usd,
        "refuses_docker0": refused,
        "mistral_opt_in": mistral_mode == "track1",
        "official_track2_stays_off": track2 == "off",
        "labs_priced_zero": float(zero) == 0.0,
        "requested_provider": REQUESTED_PROVIDER,
        "requested_model": REQUESTED_MODEL,
        "hardware_class": HARDWARE_CLASS,
        "prototype_hardware_class": PROTOTYPE_HARDWARE_CLASS,
        "used_prototype_endpoint": False,
        "arena_score": None,
        "jev_generated_lean": False,
    }
    report["ok"] = (
        audit["ok"]
        and refused
        and mistral_mode == "track1"
        and track2 == "off"
        and float(zero) == 0.0
        and text == "simp"
        and identity.get("used_prototype_endpoint") is False
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--probe", action="store_true", help="tiny hosted ping; no warmup compile")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--name", default=CANARY_NAME)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_check or not (args.probe or args.live):
        report = self_check()
        from jevops.outer import print_ok

        return print_ok(report)
    load_keyfiles()
    pin_paths()
    if args.probe:
        ping = chat_completions(
            "Return exactly the token rfl and nothing else.",
            max_tokens=8,
            timeout=60.0,
        )
        from jevops.outer import head_chars

        report = redact(
            {
                "ok": bool(ping.get("text")),
                "probe": True,
                "identity": {
                    "requested_provider": REQUESTED_PROVIDER,
                    "requested_model": REQUESTED_MODEL,
                    "resolved_model": ping.get("model"),
                    "request_id": ping.get("id"),
                    "url_host": ping.get("url_host"),
                    "hardware_class": HARDWARE_CLASS,
                    "used_prototype_endpoint": False,
                },
                "text_head": head_chars(ping.get("text") or "", 120),
                "finish_reason": ping.get("finish_reason"),
                "input_tokens": ping.get("input_tokens"),
                "output_tokens": ping.get("output_tokens"),
                "wall_ms": ping.get("wall_ms"),
                "labs_retire_date": LABS_RETIRE_DATE,
                "arena_score": None,
            }
        )
    else:
        report = run_named(args.name, max_new_tokens=args.max_new_tokens)
    from jevops.outer import write_json_pair

    latest = write_json_pair(
        args.out,
        report,
        prefix="track1-mistral",
        latest="track1-mistral-latest.json",
        refuse=("apikey_", "sk-"),
        refuse_msg="refusing to write a receipt that looks like it contains a secret",
    )
    from jevops.outer import print_json

    print_json({"ok": report.get("ok"), "latest": str(latest), "skipped": report.get("skipped"), "reason": report.get("reason"), "host": (report.get("identity") or {}).get("url_host"), "model": (report.get("identity") or {}).get("resolved_model"), "used_prototype": report.get("used_prototype_endpoint"), "arena_score": None})
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
