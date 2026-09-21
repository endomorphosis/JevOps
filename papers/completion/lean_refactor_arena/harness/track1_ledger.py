#!/usr/bin/env python3
"""Optional Track 1 US$3 ledger and grok generate_text adapter.

Prepared, not the default winning path. Closed generator is ``grok`` /
``grok-4.6`` through ``ipfs_accelerate_py.llm_router.generate_text``. Jev
in-loop cost is included in the same per-problem cap. Hard stop at
US$3/problem. Skip if keys are missing. Official Track 2 stays off and
Track 1 receipts never mix into Track 2 trees. CI fixtures do not need
live ``XAI_API_KEY`` / ``TYPESAFE_API_KEY``. Additive on Leanstral, not a
replacement. Not a scored Arena run.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
WARMUP_JSONL = PAPER_ROOT / "data" / "benchmark_data_warmup.jsonl"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import generate_text as lra_gt  # noqa: E402
import retrieve as lra_retrieve  # noqa: E402
import splice as lra_splice  # noqa: E402
import typesafe_router as lra_ts  # noqa: E402

ACCEL_ROOT = _jevops_path.IPFS_ACCELERATE_ROOT

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
WARMUP_N = lra_splice.WARMUP_N
PROTOCOL = "LRA/v1"
PR_ID = "PR-12"
LRAH_ID = "LRAH-011"
LOOP_V1_TRACK1 = "off"
DEFAULT_MODE = "off"
DEFAULT_GENERATOR = "leanstral"
ALLOWED_MODES = ("off", "track1")
OFFICIAL_TRACK2_MODE = "off"
REQUESTED_PROVIDER = "grok"
REQUESTED_MODEL = "grok-4.6"
JEV_MODEL_ID = lra_ts.MODEL_ID
ADDITIVE_NOT_REPLACEMENT = True
IS_DEFAULT_WINNING_PATH = False
PROBLEM_BUDGET_USD = Decimal("3.00")
PROBLEM_BUDGET_USD_FLOAT = 3.0
# TypeSafe public pricing, Sep 2026 (design_win_plan.md). Output free.
JEV_INPUT_USD_PER_MTOK = Decimal("0.042")
JEV_OUTPUT_USD_PER_MTOK = Decimal("0")
# Disclosed grok-4.6 family rates used for the hard stop (xAI, 2026).
GROK_INPUT_USD_PER_MTOK = Decimal("3.00")
GROK_OUTPUT_USD_PER_MTOK = Decimal("15.00")
MAX_GROK_CALLS = 2  # 1 draft + 1 Lean-feedback repair, then stop
MAX_JEV_CALLS = 2  # at most two TypeSafe fan-outs per problem
MAX_MISTRAL_CALLS = 2  # hosted Labs Leanstral: 1 draft + 1 repair, then stop
# Labs preview lists hosted Leanstral 1.5 as free (Sep 2026). Still log tokens.
MISTRAL_INPUT_USD_PER_MTOK = Decimal("0")
MISTRAL_OUTPUT_USD_PER_MTOK = Decimal("0")
MISTRAL_MODEL_ID = "labs-leanstral-1-5"
USD_QUANT = Decimal("0.000001")
FAIL_CLOSED_KWARGS: dict[str, Any] = {
    "provider": "grok",
    "model_name": "grok-4.6",
    "temperature": 0.0,
    "allow_local_fallback": False,
    "allow_cross_provider_fallback": False,
    "disable_model_retry": True,
}
# Isolated leader so a nested grok CLI does not attach to this TUI session.
DEFAULT_GROK_LEADER_SOCKET = str(Path.home() / ".grok" / "leader-lra-track1.sock")
DEFAULT_GROK_CLI_MAX_TURNS = 4
DEFAULT_GROK_FILE_MAX_TURNS = 8
GROK_TACTICS_FILENAME = "tactics.lean"
GROK_FILE_STUB = "-- REPLACE_THIS_FILE\n"
GROK_FILE_TOOLS = "write_file"
GROK_FILE_DISALLOWED = "run_terminal_cmd,web_search,web_fetch,Agent,read_file,list_dir,grep,search_replace"
GROK_FILE_WORK_ROOT = _jevops_path.LRA_STATE_ROOT / "grok-file"
DEFAULT_MAX_NEW_TOKENS = lra_gt.DEFAULT_MAX_NEW_TOKENS
DEFAULT_TIMEOUT_SECONDS = lra_gt.DEFAULT_TIMEOUT_SECONDS
PUTNAM_MAX_NEW_TOKENS = lra_gt.PUTNAM_MAX_NEW_TOKENS
PUTNAM_TIMEOUT_SECONDS = lra_gt.PUTNAM_TIMEOUT_SECONDS
ALLOWED_RESOLVED_PROVIDERS = frozenset({"grok", "xai", "grok_cli"})
FORBIDDEN_FALLBACK_PROVIDERS = frozenset(
    {
        "leanstral_local",
        "llama_cpp",
        "hf_inference_api",
        "huggingface",
        "local_hf",
        "openai",
        "openrouter",
        "codex_cli",
        "gemini_cli",
        "claude_code",
    }
)
GROK_KEY_ENV_NAMES = (
    "XAI_API_KEY",
    "ipfs_accelerate_py_XAI_API_KEY",
    "IPFS_ACCELERATE_PY_XAI_API_KEY",
    "IPFS_DATASETS_PY_XAI_API_KEY",
)
JEV_KEY_ENV_NAMES = lra_ts.KEY_ENV_NAMES
DEFAULT_TRACK1_RECEIPTS_RELATIVE = "papers/completion/lean_refactor_arena/submissions/track1"
FORBIDDEN_RECEIPT_PARTS = frozenset(
    {
        "official_track2",
        "official-track-2",
        "track2",
        "track-2",
        "a100_80gb_x4",
    }
)
LOOP_V1_WARMUP_RECEIPT_MARKERS = ("submissions", "warmup")
RECEIPT_SCHEMA = "lra-track1-ledger/v1"
TRACK_LABEL = "track1_closed"
HEADER_CHARS = lra_ts.HEADER_CHARS
NEIGHBOR_K = lra_ts.NEIGHBOR_K
FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "fcntl",
        "LeanstralProofProvider",
        "leanstral_proof_provider",
        "typesafe_sdk",
        "typesafe",
    }
)
FORBIDDEN_CALLS = frozenset(
    {
        "LOCK_EX",
        "urlopen",
        "Popen",
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
    }
)


class Track1LedgerError(RuntimeError):
    """Fail-closed Track 1 ledger/adapter error. Never an Arena success."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(USD_QUANT, rounding=ROUND_HALF_UP)


def usd_float(value: Decimal) -> float:
    return float(_money(value))


def estimate_tokens(text: str) -> int:
    """Conservative char/4 estimate. Used only to pre-authorize spend."""

    from jevops.outer import estimate_tokens_chars

    return estimate_tokens_chars(text)


USD_RATES = {
    "jev": (JEV_INPUT_USD_PER_MTOK, JEV_OUTPUT_USD_PER_MTOK),
    "grok": (GROK_INPUT_USD_PER_MTOK, GROK_OUTPUT_USD_PER_MTOK),
    "mistral": (MISTRAL_INPUT_USD_PER_MTOK, MISTRAL_OUTPUT_USD_PER_MTOK),
}


def usd_for(kind: str, input_tokens: int, output_tokens: int) -> Decimal:
    from jevops.outer import spend_for

    return spend_for(
        kind,
        input_tokens,
        output_tokens,
        USD_RATES,
        scale=Decimal("1000000"),
        money_fn=_money,
        error_cls=Track1LedgerError,
        unknown_fmt="unknown spend kind {kind!r}",
    )


def _env_truthy(value: Optional[str]) -> bool:
    from jevops.jev import env_truthy

    return env_truthy(value)


def official_track2_requested(
    *,
    flag: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    return lra_ts.official_track2_requested(flag=flag, env=env)


def grok_key_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    from jevops.jev import any_key

    from jevops.outer import env_mapping

    return any_key(env_mapping(env), GROK_KEY_ENV_NAMES)


def grok_cli_auth_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when ``~/.grok/auth.json`` (or ``$GROK_HOME/auth.json``) exists.

    Track 1 ``generate_grok`` may resolve ``provider=grok`` to ``grok_cli``
    when the CLI is on PATH. OAuth in the CLI store is enough; an xAI API
    key is not required. Does not read the file contents.
    """

    from jevops.outer import env_mapping, home_config_file, nonempty_file

    source = env_mapping(env)
    auth = home_config_file(
        "auth.json",
        env_key="GROK_HOME",
        default_dir=".grok",
        environ=source,
    )
    return nonempty_file(auth)


def grok_callable(env: Optional[Mapping[str, str]] = None) -> bool:
    """Live grok is callable via XAI_API_KEY *or* grok CLI OAuth."""

    return grok_key_configured(env) or grok_cli_auth_configured(env)


def jev_key_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    return lra_ts.key_configured(env)


def keys_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    return grok_key_configured(env) and jev_key_configured(env)


def resolve_track1_mode(
    *,
    flag: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    official_track2: bool = False,
) -> str:
    """Default off. Track 1 is opt-in and never official Track 2."""

    from jevops.outer import env_mapping

    source = env_mapping(env)
    if official_track2_requested(flag=official_track2, env=source):
        return OFFICIAL_TRACK2_MODE
    if flag is not None:
        raw = flag
    else:
        if _env_truthy(source.get("LRA_TRACK1")):
            raw = "track1"
        else:
            generator = str(source.get("LRA_GENERATOR", DEFAULT_GENERATOR) or DEFAULT_GENERATOR)
            generator = generator.strip().lower()
            if generator in {
                "grok",
                "grok-4.6",
                "xai",
                "track1",
                "mistral",
                "mistral_labs",
                "labs-leanstral-1-5",
                "leanstral-1-5",
            }:
                raw = "track1"
            else:
                raw = source.get("LRA_TRACK1_MODE", DEFAULT_MODE)
    if raw is None or str(raw).strip() == "":
        raw = DEFAULT_MODE
    mode = str(raw).strip().lower()
    if mode in {"on", "1", "true", "yes", "grok"}:
        mode = "track1"
    if mode not in ALLOWED_MODES:
        raise Track1LedgerError(f"unknown Track 1 mode {mode!r}; expected {ALLOWED_MODES}")
    return mode


def receipts_path_allowed(path: Path) -> tuple[bool, str]:
    """Track 1 receipts stay out of Track 2 / loop-v1 warmup trees."""

    from jevops.outer import path_parts_status

    return path_parts_status(
        path,
        forbidden=FORBIDDEN_RECEIPT_PARTS,
        all_markers=LOOP_V1_WARMUP_RECEIPT_MARKERS,
        forbidden_reason="track2_receipt_path",
        markers_reason="loop_v1_warmup_receipt_path",
    )


@dataclass(frozen=True)
class UsageLine:
    kind: str
    input_tokens: int
    output_tokens: int
    usd: float
    call_index: int
    fixture: bool
    model: str
    skipped: bool = False
    reason: str = "recorded"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProblemLedger:
    name: str
    budget_usd: float = PROBLEM_BUDGET_USD_FLOAT
    spent_usd: float = 0.0
    remaining_usd: float = PROBLEM_BUDGET_USD_FLOAT
    lines: list[UsageLine] = field(default_factory=list)
    grok_calls: int = 0
    jev_calls: int = 0
    mistral_calls: int = 0
    hard_stopped: bool = False
    skipped: bool = False
    reason: str = ""
    official_track2: bool = False
    contaminates_track2: bool = False
    track: str = TRACK_LABEL
    arena_score: None = None
    max_grok_calls: int = MAX_GROK_CALLS
    max_jev_calls: int = MAX_JEV_CALLS
    max_mistral_calls: int = MAX_MISTRAL_CALLS
    _spent: Decimal = field(default_factory=lambda: Decimal("0"), repr=False)

    def __post_init__(self) -> None:
        self.budget_usd = float(self.budget_usd)
        self._spent = _money(Decimal(str(self.spent_usd)))
        self._refresh()

    def _refresh(self) -> None:
        budget = _money(Decimal(str(self.budget_usd)))
        remaining = budget - self._spent
        if remaining < Decimal("0"):
            remaining = Decimal("0")
        self.spent_usd = usd_float(self._spent)
        self.remaining_usd = usd_float(remaining)

    def authorize(self, kind: str, input_tokens: int, output_tokens: int) -> tuple[bool, str, Decimal]:
        from jevops.outer import authorize_spend

        allowed, reason, zero = authorize_spend(
            kind,
            official=self.official_track2,
            counts={"grok": self.grok_calls, "mistral": self.mistral_calls, "jev": self.jev_calls},
            limits={
                "grok": int(self.max_grok_calls),
                "mistral": int(self.max_mistral_calls),
                "jev": int(self.max_jev_calls),
            },
            spent=0,
            cost=0,
            budget=1,
            zero=Decimal("0"),
        )
        if not allowed:
            if reason != "official_track2_off":
                self.hard_stopped = True
            return False, reason, zero
        cost = usd_for(kind, input_tokens, output_tokens)
        allowed, reason, cost = authorize_spend(
            kind,
            spent=self._spent,
            cost=cost,
            budget=_money(Decimal(str(self.budget_usd))),
            zero=Decimal("0"),
        )
        if not allowed:
            self.hard_stopped = True
        return allowed, reason, cost

    def record(
        self,
        kind: str,
        *,
        input_tokens: int,
        output_tokens: int,
        fixture: bool = False,
        model: str = "",
    ) -> UsageLine:
        allowed, reason, cost = self.authorize(kind, input_tokens, output_tokens)
        from jevops.outer import spend_kind

        kind_key, default_model, call_index = spend_kind(
            kind,
            models={"grok": REQUESTED_MODEL, "mistral": MISTRAL_MODEL_ID, "jev": JEV_MODEL_ID},
            counts={"grok": self.grok_calls, "mistral": self.mistral_calls, "jev": self.jev_calls},
            error_cls=Track1LedgerError,
            unknown_fmt="unknown spend kind {kind!r}",
        )
        if not allowed:
            line = UsageLine(
                kind=kind_key,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                usd=usd_float(cost),
                call_index=call_index,
                fixture=fixture,
                model=model or default_model,
                skipped=True,
                reason=reason,
            )
            self.lines.append(line)
            self.skipped = True
            self.reason = reason
            return line
        self._spent = _money(self._spent + cost)
        if kind_key == "grok":
            self.grok_calls += 1
        elif kind_key == "mistral":
            self.mistral_calls += 1
        elif kind_key == "jev":
            self.jev_calls += 1
        else:
            raise Track1LedgerError(f"unknown spend kind {kind_key!r}")
        self._refresh()
        line = UsageLine(
            kind=kind_key,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            usd=usd_float(cost),
            call_index=call_index,
            fixture=fixture,
            model=model or default_model,
            skipped=False,
            reason="recorded",
        )
        self.lines.append(line)
        return line

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "budget_usd": self.budget_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd,
            "hard_stopped": self.hard_stopped,
            "skipped": self.skipped,
            "reason": self.reason,
            "grok_calls": self.grok_calls,
            "jev_calls": self.jev_calls,
            "mistral_calls": self.mistral_calls,
            "max_grok_calls": int(self.max_grok_calls),
            "max_jev_calls": int(self.max_jev_calls),
            "max_mistral_calls": int(self.max_mistral_calls),
            "official_track2": self.official_track2,
            "contaminates_track2": self.contaminates_track2,
            "track": self.track,
            "arena_score": self.arena_score,
            "includes_jev_and_grok": True,
            "lines": [line.as_dict() for line in self.lines],
        }


from jevops.lean import ProviderIdentity


@dataclass(frozen=True)
class Track1Result:
    skipped: bool
    reason: str
    mode: str
    official_track2: bool
    name: Optional[str] = None
    called_grok: bool = False
    called_jev: bool = False
    used_fixture: bool = False
    grok_calls: int = 0
    jev_calls: int = 0
    spent_usd: float = 0.0
    remaining_usd: float = PROBLEM_BUDGET_USD_FLOAT
    hard_stopped: bool = False
    text: Optional[str] = None
    identity: Optional[dict[str, Any]] = None
    jev_route: Optional[dict[str, Any]] = None
    ledger: Optional[dict[str, Any]] = None
    wall_ms: Optional[float] = None
    contaminates_track2: bool = False
    is_default_winning_path: bool = False
    additive_not_replacement: bool = True
    arena_score: None = None
    api_key_redacted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FixtureGrok:
    """CI grok stand-in. Never POSTs. Not a live xAI client."""

    def __init__(self, text: str = "simp") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def __call__(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, "kwargs": dict(kwargs)})
        return self.text


def fixture_trace(model: str = REQUESTED_MODEL) -> dict[str, str]:
    return {
        "effective_provider_name": "xai",
        "effective_model_name": model,
    }


def _ensure_accel_path() -> None:
    _jevops_path.ensure_ipfs_accelerate_path()


def _load_router():
    _ensure_accel_path()
    from _optional_deps import require_router

    router = require_router()

    return router.generate_text, router.get_last_generation_trace


def _live_grok_kwargs() -> dict[str, Any]:
    """Fail-closed grok kwargs plus an isolated grok CLI leader socket.

    This TUI session already owns ``~/.grok/leader.sock``. A nested
    ``grok --max-turns 1`` that attaches there returns ``max turns reached``
    without generating. Pin a ``leader-lra-*.sock`` and a small CLI turn
    budget (not extra Track 1 generate_grok calls).
    """

    from jevops.outer import env_int, env_str, which_bin

    kwargs = dict(FAIL_CLOSED_KWARGS)
    kwargs["grok_max_turns"] = env_int(
        "LRA_GROK_CLI_MAX_TURNS", DEFAULT_GROK_CLI_MAX_TURNS, minimum=1
    )
    grok_bin = which_bin("grok")
    if grok_bin:
        socket = env_str("LRA_GROK_LEADER_SOCKET", DEFAULT_GROK_LEADER_SOCKET)
        kwargs["grok_cli_cmd"] = [grok_bin, "--leader-socket", socket]
    return kwargs


def grok_file_prompt(body: str, *, dest_name: str = GROK_TACTICS_FILENAME) -> str:
    """Instruct grok CLI to write tactics to a file. Chat is not the deliverable."""

    from jevops.lean import grok_file_prompt as _fn

    return _fn(body, dest_name=dest_name, stub=GROK_FILE_STUB)


def prepare_grok_workspace(*, dest_name: str = GROK_TACTICS_FILENAME) -> Path:
    from jevops.outer import mkdtemp_under

    return mkdtemp_under(GROK_FILE_WORK_ROOT, prefix="ws-", files={dest_name: GROK_FILE_STUB})


def tactics_file_is_stub(text: str) -> bool:
    from jevops.outer import is_stub_text

    return is_stub_text(
        text,
        marker="REPLACE_THIS_FILE",
        max_words=12,
        exact=GROK_FILE_STUB,
    )


def read_grok_tactics_file(
    workspace: Path,
    *,
    dest_name: str = GROK_TACTICS_FILENAME,
) -> str:
    """Return tactics from the workspace file. Chat is never consulted."""

    from jevops.outer import first_file_text, glob_after

    dest = Path(workspace) / dest_name
    return first_file_text(
        glob_after(workspace, "*.lean", first=dest),
        drop_substr="REPLACE_THIS_FILE",
        reject_fn=tactics_file_is_stub,
        error_cls=Track1LedgerError,
        miss=f"grok did not write a tactics file under {workspace}",
    )


def build_grok_file_command(
    workspace: Path,
    prompt_path: Path,
    *,
    dest_name: str = GROK_TACTICS_FILENAME,
) -> list[str]:
    from jevops.outer import env_int, env_str, which_bin

    grok_bin = which_bin("grok")
    if not grok_bin:
        raise Track1LedgerError("grok CLI not found on PATH")
    socket = env_str("LRA_GROK_LEADER_SOCKET", DEFAULT_GROK_LEADER_SOCKET)
    max_turns = env_int("LRA_GROK_CLI_MAX_TURNS", DEFAULT_GROK_FILE_MAX_TURNS, minimum=2)
    from jevops.lean import grok_file_argv

    return grok_file_argv(
        grok_bin=grok_bin,
        socket=socket,
        workspace=workspace,
        model=REQUESTED_MODEL,
        max_turns=max_turns,
        tools=GROK_FILE_TOOLS,
        disallowed=GROK_FILE_DISALLOWED,
        dest_name=dest_name,
        prompt_path=prompt_path,
    )


def _grok_stdout_payload(stdout: str) -> dict[str, Any]:
    from jevops.outer import first_json_dict

    return first_json_dict(stdout)


@dataclass(frozen=True)
class GrokFileResult:
    tactics: str
    identity: ProviderIdentity
    line: UsageLine
    chat_head: str
    tactics_path: str
    workspace: str
    used_file: bool
    chat_ignored: bool
    called_docker0: bool = False
    arena_score: None = None

    def as_dict(self) -> dict[str, Any]:
        from jevops.outer import head_chars

        return {
            "tactics_path": self.tactics_path,
            "workspace": self.workspace,
            "used_file": self.used_file,
            "chat_ignored": self.chat_ignored,
            "chat_head": self.chat_head,
            "n_chars": len(self.tactics),
            "tactics_head": head_chars(self.tactics, 240),
            "called_docker0": self.called_docker0,
            "identity": asdict(self.identity),
            "arena_score": self.arena_score,
        }


def generate_grok_file(
    prompt: str,
    ledger: ProblemLedger,
    *,
    workspace: Path,
    dest_name: str = GROK_TACTICS_FILENAME,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    generate: Optional[Callable[..., str]] = None,
    fixture: bool = False,
    reset_stub: bool = False,
) -> GrokFileResult:
    """Run grok CLI so it writes ``tactics.lean``. Lake reads that file, not chat."""

    estimated_in = estimate_tokens(prompt)
    estimated_out = int(max_new_tokens)
    allowed, reason, _cost = ledger.authorize("grok", estimated_in, estimated_out)
    if not allowed:
        line = ledger.record(
            "grok",
            input_tokens=estimated_in,
            output_tokens=estimated_out,
            fixture=fixture,
            model=REQUESTED_MODEL,
        )
        raise Track1LedgerError(f"grok call refused: {reason}") from None

    from jevops.lean import run_workspace_generate
    from jevops.outer import env_copy, run_process, write_json, write_text

    def _run_cli() -> tuple[str, ProviderIdentity]:
        prompt_path = Path(workspace) / "PROMPT.txt"
        write_text(prompt_path, str(prompt))
        cmd = build_grok_file_command(workspace, prompt_path, dest_name=dest_name)
        write_json(Path(workspace) / "grok.argv.json", cmd)
        try:
            ran = run_process(
                cmd,
                cwd=workspace,
                env=env_copy(),
                timeout=float(timeout),
            )
        except FileNotFoundError as exc:
            raise Track1LedgerError("grok CLI not found on PATH") from exc
        chat_out = str(ran.get("stdout") or "")
        stderr = str(ran.get("stderr") or "")
        code = "timeout" if ran.get("timeout") else str(ran.get("exit_code"))
        write_text(Path(workspace) / "grok.stdout", chat_out)
        write_text(Path(workspace) / "grok.stderr", stderr)
        write_text(Path(workspace) / "grok.returncode", code)
        if not ran.get("timeout"):
            payload = _grok_stdout_payload(chat_out)
            if payload.get("text"):
                chat_out = str(payload.get("text") or chat_out)
        return chat_out, ProviderIdentity(
            requested_provider=REQUESTED_PROVIDER,
            requested_model=REQUESTED_MODEL,
            resolved_provider="grok_cli",
            resolved_model=REQUESTED_MODEL,
            fallback_used=False,
            arena_score=None,
        )

    chat = ""
    identity: Optional[ProviderIdentity] = None
    try:
        tactics, identity, chat, dest = run_workspace_generate(
            workspace=workspace,
            dest_name=dest_name,
            stub=GROK_FILE_STUB,
            reset_stub=reset_stub,
            generate_fn=(lambda **_kw: generate(prompt, **FAIL_CLOSED_KWARGS)) if generate is not None else None,
            identity_from_generate=(lambda: _identity_from_trace(fixture_trace(), generated=True))
            if generate is not None
            else None,
            run_fn=None if generate is not None else _run_cli,
            read_fn=read_grok_tactics_file,
            write_text_fn=write_text,
        )
    except Track1LedgerError as exc:
        line = ledger.record(
            "grok",
            input_tokens=estimated_in,
            output_tokens=estimate_tokens(chat) if chat else 1,
            fixture=fixture,
            model=(getattr(identity, "resolved_model", None) or REQUESTED_MODEL),
        )
        stderr_head = ""
        err_path = Path(workspace) / "grok.stderr"
        if err_path.is_file():
            from jevops.outer import read_text

            stderr_head = read_text(err_path, max_chars=400)
        detail = str(exc)
        if stderr_head:
            detail = f"{detail}; grok.stderr={stderr_head!r}"
        raise Track1LedgerError(detail) from exc

    usage_out = estimate_tokens(tactics)
    line = ledger.record(
        "grok",
        input_tokens=estimated_in,
        output_tokens=usage_out,
        fixture=fixture,
        model=identity.resolved_model or REQUESTED_MODEL,
    )
    if line.skipped:
        raise Track1LedgerError(f"grok spend refused after call: {line.reason}")
    from jevops.outer import head_chars

    return GrokFileResult(
        tactics=tactics,
        identity=identity,
        line=line,
        chat_head=head_chars(chat or "", 240),
        tactics_path=str(dest),
        workspace=str(workspace),
        used_file=True,
        chat_ignored=True,
        called_docker0=False,
        arena_score=None,
    )


def _identity_from_trace(trace: Mapping[str, Any], *, generated: bool) -> ProviderIdentity:
    from jevops.lean import identity_from_trace as _fn

    return _fn(
        trace,
        generated=generated,
        requested_provider=REQUESTED_PROVIDER,
        requested_model=REQUESTED_MODEL,
        allowed=ALLOWED_RESOLVED_PROVIDERS,
        forbidden=FORBIDDEN_FALLBACK_PROVIDERS,
        identity_cls=ProviderIdentity,
    )


def token_limits_for_source(source: str) -> tuple[int, int]:
    return lra_gt.token_limits_for_source(source)


def write_ledger_receipt(ledger: ProblemLedger, path: Path) -> Path:
    """Write a Track 1 ledger receipt. Refuses Track 2 / warmup trees."""

    if ledger.official_track2 or ledger.contaminates_track2:
        raise Track1LedgerError("refusing to write a Track 1 ledger into official Track 2 state")
    allowed, reason = receipts_path_allowed(path)
    if not allowed:
        raise Track1LedgerError(f"refusing receipt path {path}: {reason}")
    from jevops.outer import write_json

    payload = {
        "schema": RECEIPT_SCHEMA,
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "lrah": LRAH_ID,
        "track": TRACK_LABEL,
        "official_track2": False,
        "contaminates_track2": False,
        "is_default_winning_path": False,
        "arena_score": None,
        "ledger": ledger.as_dict(),
        "api_key_present_in_record": False,
    }
    write_json(path, payload)
    return path


def _skip_result(
    *,
    reason: str,
    mode: str,
    official_track2: bool,
    name: Optional[str] = None,
    used_fixture: bool = False,
    ledger: Optional[ProblemLedger] = None,
) -> Track1Result:
    payload = ledger.as_dict() if ledger is not None else None
    return Track1Result(
        skipped=True,
        reason=reason,
        mode=mode,
        official_track2=official_track2,
        name=name,
        used_fixture=used_fixture,
        grok_calls=ledger.grok_calls if ledger is not None else 0,
        jev_calls=ledger.jev_calls if ledger is not None else 0,
        spent_usd=ledger.spent_usd if ledger is not None else 0.0,
        remaining_usd=ledger.remaining_usd if ledger is not None else PROBLEM_BUDGET_USD_FLOAT,
        hard_stopped=bool(ledger.hard_stopped) if ledger is not None else False,
        ledger=payload,
        contaminates_track2=False,
        is_default_winning_path=False,
    )


def generate_grok(
    prompt: str,
    ledger: ProblemLedger,
    *,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    source: str = "",
    generate: Optional[Callable[..., str]] = None,
    get_trace: Optional[Callable[[], Mapping[str, Any]]] = None,
    fixture: bool = False,
) -> tuple[str, ProviderIdentity, UsageLine]:
    """Call grok/grok-4.6 through llm_router.generate_text. No Leanstral fallback."""

    from jevops.lean import coalesce_limits, refuse_if_fallback, require_text
    from jevops.outer import ledger_generate

    max_new_tokens, timeout = coalesce_limits(
        source=source,
        max_new=max_new_tokens,
        timeout=timeout,
        lookup_fn=token_limits_for_source,
        default_new=DEFAULT_MAX_NEW_TOKENS,
        default_timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    estimated_in = estimate_tokens(prompt)
    estimated_out = int(max_new_tokens)

    def _identity(*, model: str, fixture: bool, extra: Optional[Mapping[str, Any]] = None, text: str = "") -> dict[str, Any]:
        ident = _identity_from_trace(dict(extra or {}), generated=True)
        refuse_if_fallback(
            ident,
            error_cls=Track1LedgerError,
            fmt="resolved provider/model is a forbidden Leanstral/HF fallback: {provider}/{model}",
        )
        require_text(text, error_cls=Track1LedgerError, msg="grok returned a non-text payload")
        return asdict(ident)

    def _live() -> tuple[str, Mapping[str, Any], tuple[int, int]]:
        router_generate = generate
        router_trace = get_trace
        if router_generate is None:
            if fixture:
                raise Track1LedgerError("fixture generate callable required")
            loaded_generate, loaded_trace = _load_router()
            router_generate = loaded_generate
            if router_trace is None:
                router_trace = loaded_trace
        call_kwargs = dict(FAIL_CLOSED_KWARGS) if generate is not None else _live_grok_kwargs()
        try:
            text = router_generate(
                prompt,
                max_new_tokens=int(max_new_tokens),
                timeout=float(timeout),
                **call_kwargs,
            )
        except Track1LedgerError:
            raise
        except Exception as exc:
            raise Track1LedgerError(f"grok generate_text failed: {exc}") from exc
        trace = dict(router_trace() or {}) if router_trace is not None else {}
        inn = int(trace.get("input_tokens") or trace.get("prompt_tokens") or estimated_in)
        out = int(trace.get("output_tokens") or trace.get("completion_tokens") or estimate_tokens(text))
        return str(text), trace, (inn, out)

    text, identity_dict, line = ledger_generate(
        ledger,
        "grok",
        estimated_in=estimated_in,
        estimated_out=estimated_out,
        model=REQUESTED_MODEL,
        fixture=False,
        fixture_text="",
        live_fn=_live,
        identity_fn=_identity,
        error_cls=Track1LedgerError,
        estimate_fn=estimate_tokens,
        refuse_fmt="grok call refused: {reason}",
        after_fmt="grok spend refused after call: {reason}",
    )
    return (
        text,
        ProviderIdentity(
            requested_provider=str(identity_dict.get("requested_provider") or REQUESTED_PROVIDER),
            requested_model=str(identity_dict.get("requested_model") or REQUESTED_MODEL),
            resolved_provider=str(identity_dict.get("resolved_provider") or ""),
            resolved_model=str(identity_dict.get("resolved_model") or ""),
            fallback_used=bool(identity_dict.get("fallback_used")),
            arena_score=None,
        ),
        line,
    )


def _charge_jev(ledger: ProblemLedger, route: lra_ts.RouteResult, *, fixture: bool) -> UsageLine:
    usage = dict(route.usage or {})
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    if fixture and input_tokens == 0 and output_tokens == 0:
        input_tokens = 0
        output_tokens = 0
    return ledger.record(
        "jev",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        fixture=fixture or bool(route.used_fixture),
        model=route.model or JEV_MODEL_ID,
    )


def run_named(
    name: str,
    *,
    mode: Optional[str] = None,
    official_track2: bool = False,
    fixture: bool = False,
    repair: bool = False,
    lean_feedback: str = "lake env lean failed: unknown identifier",
    path: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    generate: Optional[Callable[..., str]] = None,
    get_trace: Optional[Callable[[], Mapping[str, Any]]] = None,
    receipts_dir: Optional[Path] = None,
) -> dict[str, Any]:
    from jevops.outer import env_copy

    source_env = env_copy(base=env)
    resolved = resolve_track1_mode(flag=mode, env=source_env, official_track2=official_track2)
    track2 = official_track2_requested(flag=official_track2, env=source_env)
    record, records, digest = _load_named_record(name, path)
    ledger = ProblemLedger(name=name, official_track2=track2)
    if track2 or resolved != "track1":
        reason = "official_track2_off" if track2 else "not_default_winning_path"
        result = _skip_result(
            reason=reason,
            mode="off" if track2 else resolved,
            official_track2=track2,
            name=name,
            used_fixture=fixture,
            ledger=ledger,
        )
        payload = result.as_dict()
        payload["ok"] = True
        payload["warmup_jsonl_sha256"] = digest
        payload["source"] = record.get("source")
        payload["default_mode"] = DEFAULT_MODE
        payload["is_default_winning_path"] = False
        payload["official_track2_stays_off"] = True
        payload["contaminates_track2"] = False
        return payload

    using_fixture = fixture or generate is not None
    if not using_fixture and not keys_configured(source_env):
        result = _skip_result(
            reason="no_key",
            mode=resolved,
            official_track2=False,
            name=name,
            used_fixture=False,
            ledger=ledger,
        )
        payload = result.as_dict()
        payload["ok"] = True
        payload["warmup_jsonl_sha256"] = digest
        payload["source"] = record.get("source")
        payload["grok_key_configured"] = grok_key_configured(source_env)
        payload["jev_key_configured"] = jev_key_configured(source_env)
        payload["keys_configured"] = False
        payload["is_default_winning_path"] = False
        payload["contaminates_track2"] = False
        return payload

    neighbors = _neighbors_for(record, records)
    state = lra_ts.problem_state(record, neighbors=neighbors)
    factory = None
    if using_fixture:
        factory = lambda **kwargs: lra_ts.FixtureClient(answers=lra_ts.default_fixture_answers(), **kwargs)
    router = lra_ts.TypeSafeLraRouter(
        mode="inloop",
        official_track2=False,
        env={"LRA_TYPESAFE": "inloop", **{k: v for k, v in source_env.items() if k not in {"LRA_OFFICIAL_TRACK2", "LRA_TRACK"}}},
        client_factory=factory,
        require_key=not using_fixture,
    )
    from jevops.outer import elapsed_ms

    started = time.perf_counter()
    jev_result = router.route(state, neighbor_names=[item["name"] for item in neighbors])
    if jev_result.skipped and not using_fixture:
        result = _skip_result(
            reason=jev_result.reason or "jev_skipped",
            mode=resolved,
            official_track2=False,
            name=name,
            used_fixture=using_fixture,
            ledger=ledger,
        )
        payload = result.as_dict()
        payload["ok"] = True
        payload["warmup_jsonl_sha256"] = digest
        payload["jev_route"] = jev_result.as_dict()
        payload["contaminates_track2"] = False
        return payload
    if not jev_result.skipped:
        jev_line = _charge_jev(ledger, jev_result, fixture=using_fixture)
        if jev_line.skipped:
            result = _skip_result(
                reason=jev_line.reason,
                mode=resolved,
                official_track2=False,
                name=name,
                used_fixture=using_fixture,
                ledger=ledger,
            )
            payload = result.as_dict()
            payload["ok"] = True
            payload["warmup_jsonl_sha256"] = digest
            payload["jev_route"] = jev_result.as_dict()
            payload["contaminates_track2"] = False
            return payload

    prompt = lra_gt.render_prompt(record)
    grok_factory = generate
    grok_trace = get_trace
    if using_fixture and grok_factory is None:
        grok_factory = FixtureGrok()
        grok_trace = fixture_trace
    max_new, timeout = token_limits_for_source(str(record.get("source") or ""))
    try:
        text, identity, _line = generate_grok(
            prompt,
            ledger,
            max_new_tokens=max_new,
            timeout=timeout,
            source=str(record.get("source") or ""),
            generate=grok_factory,
            get_trace=grok_trace,
            fixture=using_fixture,
        )
        if repair:
            repair_prompt = (
                prompt
                + "\n\nPrevious candidate failed lake compile:\n"
                + str(lean_feedback)
                + "\nReturn only a repaired tactic block after := by.\n"
            )
            text, identity, _line = generate_grok(
                repair_prompt,
                ledger,
                max_new_tokens=max_new,
                timeout=timeout,
                source=str(record.get("source") or ""),
                generate=grok_factory,
                get_trace=grok_trace,
                fixture=using_fixture,
            )
    except Track1LedgerError as exc:
        wall_ms = elapsed_ms(started)
        result = Track1Result(
            skipped=True,
            reason=ledger.reason or str(exc),
            mode=resolved,
            official_track2=False,
            name=name,
            called_grok=ledger.grok_calls > 0,
            called_jev=ledger.jev_calls > 0,
            used_fixture=using_fixture,
            grok_calls=ledger.grok_calls,
            jev_calls=ledger.jev_calls,
            spent_usd=ledger.spent_usd,
            remaining_usd=ledger.remaining_usd,
            hard_stopped=ledger.hard_stopped,
            jev_route=jev_result.as_dict(),
            ledger=ledger.as_dict(),
            wall_ms=wall_ms,
            contaminates_track2=False,
            is_default_winning_path=False,
        )
        payload = result.as_dict()
        payload["ok"] = True
        payload["error"] = str(exc)
        payload["warmup_jsonl_sha256"] = digest
        payload["source"] = record.get("source")
        return payload

    wall_ms = elapsed_ms(started)
    if receipts_dir is not None:
        write_ledger_receipt(ledger, Path(receipts_dir) / name / "track1_ledger.json")
    result = Track1Result(
        skipped=False,
        reason="generated",
        mode=resolved,
        official_track2=False,
        name=name,
        called_grok=True,
        called_jev=not jev_result.skipped,
        used_fixture=using_fixture,
        grok_calls=ledger.grok_calls,
        jev_calls=ledger.jev_calls,
        spent_usd=ledger.spent_usd,
        remaining_usd=ledger.remaining_usd,
        hard_stopped=ledger.hard_stopped,
        text=text,
        identity=asdict(identity),
        jev_route=jev_result.as_dict(),
        ledger=ledger.as_dict(),
        wall_ms=wall_ms,
        contaminates_track2=False,
        is_default_winning_path=False,
    )
    payload = result.as_dict()
    payload["ok"] = True
    payload["warmup_jsonl_sha256"] = digest
    payload["source"] = record.get("source")
    payload["n_neighbors"] = len(neighbors)
    payload["default_mode"] = DEFAULT_MODE
    payload["requested_provider"] = REQUESTED_PROVIDER
    payload["requested_model"] = REQUESTED_MODEL
    payload["budget_usd"] = PROBLEM_BUDGET_USD_FLOAT
    payload["max_grok_calls"] = MAX_GROK_CALLS
    payload["official_track2_stays_off"] = True
    payload["keys_configured"] = keys_configured(source_env)
    return payload


def _load_named_record(name: str, path: Optional[Path] = None) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    from jevops.outer import lookup_named

    raw, digest, records = lra_splice.load_warmup_records(path)
    del raw
    record = lookup_named(
        records, name, error_cls=Track1LedgerError, miss=f"unknown warm-up problem: {name}"
    )
    return record, records, digest


def _neighbors_for(record: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    retrieval = lra_retrieve.retrieve_record(record, records)
    return lra_retrieve.prompt_neighbors(retrieval, k=NEIGHBOR_K)


def plan_view(
    *,
    mode: Optional[str] = None,
    official_track2: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    resolved = resolve_track1_mode(flag=mode, env=env, official_track2=official_track2)
    return {
        "ok": True,
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "lrah": LRAH_ID,
        "default_mode": DEFAULT_MODE,
        "default_generator": DEFAULT_GENERATOR,
        "resolved_mode": resolved,
        "allowed_modes": list(ALLOWED_MODES),
        "official_track2": official_track2_requested(flag=official_track2, env=env),
        "official_track2_stays_off": True,
        "loop_v1_track1": LOOP_V1_TRACK1,
        "is_default_winning_path": IS_DEFAULT_WINNING_PATH,
        "additive_not_replacement": ADDITIVE_NOT_REPLACEMENT,
        "requested_provider": REQUESTED_PROVIDER,
        "requested_model": REQUESTED_MODEL,
        "fail_closed_kwargs": dict(FAIL_CLOSED_KWARGS),
        "budget_usd": PROBLEM_BUDGET_USD_FLOAT,
        "jev_input_usd_per_mtok": float(JEV_INPUT_USD_PER_MTOK),
        "jev_output_usd_per_mtok": float(JEV_OUTPUT_USD_PER_MTOK),
        "grok_input_usd_per_mtok": float(GROK_INPUT_USD_PER_MTOK),
        "grok_output_usd_per_mtok": float(GROK_OUTPUT_USD_PER_MTOK),
        "max_grok_calls": MAX_GROK_CALLS,
        "max_jev_calls": MAX_JEV_CALLS,
        "includes_jev_and_grok": True,
        "skip_if_keys_missing": True,
        "grok_key_env_names": list(GROK_KEY_ENV_NAMES),
        "jev_key_env_names": list(JEV_KEY_ENV_NAMES),
        "grok_key_configured": grok_key_configured(env),
        "jev_key_configured": jev_key_configured(env),
        "keys_configured": keys_configured(env),
        "default_receipts_dir": DEFAULT_TRACK1_RECEIPTS_RELATIVE,
        "forbidden_receipt_parts": sorted(FORBIDDEN_RECEIPT_PARTS),
        "contaminates_track2": False,
        "inloop_is_track1_only": True,
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "arena_score": None,
        "compiled": False,
        "llama_server_started": False,
        "imports_llm_router": True,
        "closed_generator": f"{REQUESTED_PROVIDER}/{REQUESTED_MODEL}",
    }


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _call_func_names(source: str) -> set[str]:
    from jevops.repair import call_func_names

    return call_func_names(source)


def _assigned_constant(tree: ast.AST, name: str) -> Any:
    from jevops.repair import assigned_constant

    return assigned_constant(tree, name)


def _fail_closed_kwargs_from_source(source: str) -> dict[str, Any]:
    from jevops.repair import assigned_literal

    return assigned_literal(
        source,
        "FAIL_CLOSED_KWARGS",
        error_cls=Track1LedgerError,
        miss="FAIL_CLOSED_KWARGS assignment not found",
        not_dict="FAIL_CLOSED_KWARGS must be a dict",
    )


def _numeric_score_assignments(source: str) -> list[str]:
    from jevops.repair import score_assignments

    return score_assignments(source, FORBIDDEN_SCORE_NAMES)


def audit_source(source: Optional[str] = None) -> dict[str, Any]:
    from jevops.outer import source_text
    from jevops.repair import assigned_constants, audit_source as _audit

    text = source_text(source, path=__file__)
    out = _audit(
        text,
        forbidden_imports=FORBIDDEN_IMPORT_NAMES,
        forbidden_calls=FORBIDDEN_CALLS,
        forbidden_scores=FORBIDDEN_SCORE_NAMES,
    )
    imported = set(out["imported_names"])
    calls = set(out["call_func_names"])
    score_issues = out["score_issues"]
    uses_lock_ex = bool(out["uses_lock_ex"])
    kwargs = _fail_closed_kwargs_from_source(text)
    consts = assigned_constants(
        text,
        (
            "DEFAULT_MODE",
            "DEFAULT_GENERATOR",
            "LOOP_V1_TRACK1",
            "OFFICIAL_TRACK2_MODE",
            "IS_DEFAULT_WINNING_PATH",
            "REQUESTED_PROVIDER",
            "REQUESTED_MODEL",
            "MAX_GROK_CALLS",
        ),
    )
    return {
        "imported_names": out["imported_names"],
        "forbidden_imports": out["forbidden_imports"],
        "forbidden_calls": out["forbidden_calls"],
        "numeric_score_assignments": score_issues,
        "imports_llm_router": "ipfs_accelerate_py.llm_router" in imported or "llm_router" in imported,
        "imports_generate_text": "generate_text" in imported,
        "imports_typesafe_sdk": "typesafe_sdk" in imported or "typesafe" in imported,
        "imports_fcntl": "fcntl" in imported,
        "calls_generate_text": "generate_text" in calls or "router_generate_text" in imported,
        "default_mode_constant": consts["DEFAULT_MODE"],
        "default_generator_constant": consts["DEFAULT_GENERATOR"],
        "loop_v1_track1_constant": consts["LOOP_V1_TRACK1"],
        "official_track2_mode_constant": consts["OFFICIAL_TRACK2_MODE"],
        "is_default_winning_path_constant": consts["IS_DEFAULT_WINNING_PATH"],
        "requested_provider_constant": consts["REQUESTED_PROVIDER"],
        "requested_model_constant": consts["REQUESTED_MODEL"],
        "max_grok_calls_constant": consts["MAX_GROK_CALLS"],
        "fail_closed_kwargs": kwargs,
        "uses_lock_ex": uses_lock_ex,
        "ok": (
            ("ipfs_accelerate_py.llm_router" in imported or "llm_router" in imported)
            and "generate_text" in imported
            and "typesafe_sdk" not in imported
            and "typesafe" not in imported
            and "fcntl" not in imported
            and not out["forbidden_imports"]
            and not out["forbidden_calls"]
            and not score_issues
            and not uses_lock_ex
            and consts["DEFAULT_MODE"] == "off"
            and consts["DEFAULT_GENERATOR"] == "leanstral"
            and consts["LOOP_V1_TRACK1"] == "off"
            and consts["OFFICIAL_TRACK2_MODE"] == "off"
            and consts["IS_DEFAULT_WINNING_PATH"] is False
            and consts["REQUESTED_PROVIDER"] == "grok"
            and consts["REQUESTED_MODEL"] == "grok-4.6"
            and consts["MAX_GROK_CALLS"] == 2
            and kwargs.get("provider") == "grok"
            and kwargs.get("model_name") == "grok-4.6"
            and kwargs.get("allow_local_fallback") is False
            and kwargs.get("allow_cross_provider_fallback") is False
            and kwargs.get("disable_model_retry") is True
        ),
    }


def _hard_stop_probe() -> dict[str, Any]:
    """US$3/problem including Jev+grok. Exact $3 is allowed; over is a hard stop."""

    jev_tokens = 20 * 8000
    jev_usd = usd_for("jev", jev_tokens, 0)
    combined = ProblemLedger(name="hard-stop-combined")
    jev_line = combined.record("jev", input_tokens=jev_tokens, output_tokens=0, fixture=True)
    grok_over = combined.record("grok", input_tokens=1_000_000, output_tokens=0, fixture=True)
    exact = ProblemLedger(name="hard-stop-exact")
    exact_line = exact.record("grok", input_tokens=1_000_000, output_tokens=0, fixture=True)
    exact_next = exact.record("grok", input_tokens=1, output_tokens=0, fixture=True)
    max_calls = ProblemLedger(name="max-calls")
    first = max_calls.record("grok", input_tokens=100, output_tokens=10, fixture=True)
    second = max_calls.record("grok", input_tokens=100, output_tokens=10, fixture=True)
    third = max_calls.record("grok", input_tokens=100, output_tokens=10, fixture=True)
    return {
        "budget_usd": PROBLEM_BUDGET_USD_FLOAT,
        "jev_20x8ktok_usd": usd_float(jev_usd),
        "jev_recorded_usd": jev_line.usd,
        "combined_spent_after_jev": combined.spent_usd,
        "combined_grok_million_skipped": grok_over.skipped,
        "combined_grok_reason": grok_over.reason,
        "combined_hard_stopped": combined.hard_stopped,
        "combined_spent_unchanged": combined.spent_usd == jev_line.usd,
        "exact_three_allowed": (not exact_line.skipped) and exact.spent_usd == PROBLEM_BUDGET_USD_FLOAT,
        "exact_next_hard_stop": exact_next.skipped and exact_next.reason == "hard_stop",
        "max_calls_first_ok": not first.skipped,
        "max_calls_second_ok": not second.skipped,
        "max_calls_third_stopped": third.skipped and third.reason == "max_grok_calls",
        "includes_jev_and_grok": True,
        "ok": (
            jev_line.usd > 0
            and grok_over.skipped
            and grok_over.reason == "hard_stop"
            and combined.hard_stopped
            and combined.spent_usd == jev_line.usd
            and combined.spent_usd < PROBLEM_BUDGET_USD_FLOAT
            and (not exact_line.skipped)
            and exact.spent_usd == PROBLEM_BUDGET_USD_FLOAT
            and exact_next.skipped
            and exact_next.reason == "hard_stop"
            and (not first.skipped)
            and (not second.skipped)
            and third.skipped
            and third.reason == "max_grok_calls"
        ),
    }


def _receipt_probe() -> dict[str, Any]:
    ledger = ProblemLedger(name="receipt-probe")
    ledger.record("jev", input_tokens=100, output_tokens=0, fixture=True)
    from jevops.outer import temp_dir

    with temp_dir(prefix="lra-track1-") as tmp:
        root = Path(tmp)
        allowed = root / "track1" / "receipt.json"
        write_ledger_receipt(ledger, allowed)
        from jevops.outer import read_json

        written = read_json(allowed)
        track2_rejected = False
        track2_reason = ""
        try:
            write_ledger_receipt(ledger, root / "official_track2" / "receipt.json")
        except Track1LedgerError as exc:
            track2_rejected = True
            track2_reason = str(exc)
        warmup_rejected = False
        try:
            write_ledger_receipt(
                ledger,
                root / "papers" / "completion" / "lean_refactor_arena" / "submissions" / "warmup" / "receipt.json",
            )
        except Track1LedgerError:
            warmup_rejected = True
        contaminated = ProblemLedger(name="contaminated", official_track2=True)
        contaminated_rejected = False
        try:
            write_ledger_receipt(contaminated, allowed)
        except Track1LedgerError:
            contaminated_rejected = True
        allowed_ok, allowed_reason = receipts_path_allowed(allowed)
        track2_ok, track2_path_reason = receipts_path_allowed(root / "track2" / "x.json")
    return {
        "written_track": written.get("track"),
        "written_official_track2": written.get("official_track2"),
        "written_contaminates_track2": written.get("contaminates_track2"),
        "written_arena_score": written.get("arena_score"),
        "written_is_default_winning_path": written.get("is_default_winning_path"),
        "api_key_present_in_record": written.get("api_key_present_in_record"),
        "track2_path_rejected": track2_rejected,
        "track2_reason": track2_reason,
        "warmup_path_rejected": warmup_rejected,
        "official_track2_ledger_rejected": contaminated_rejected,
        "allowed_path_ok": allowed_ok,
        "track2_component_blocked": (not track2_ok) and track2_path_reason == "track2_receipt_path",
        "ok": (
            written.get("track") == TRACK_LABEL
            and written.get("official_track2") is False
            and written.get("contaminates_track2") is False
            and written.get("arena_score") is None
            and written.get("is_default_winning_path") is False
            and written.get("api_key_present_in_record") is False
            and track2_rejected
            and warmup_rejected
            and contaminated_rejected
            and allowed_ok
            and not track2_ok
        ),
    }


def self_check(path: Optional[Path] = None) -> dict[str, Any]:
    """CI fixtures without a live key. Does not POST and does not compile."""

    from jevops.outer import read_text

    source = read_text(__file__)
    jsonl = Path(path) if path is not None else WARMUP_JSONL
    from jevops.outer import digest_file

    before = digest_file(jsonl)
    raw, digest, records = lra_splice.load_warmup_records(jsonl)
    after = digest_file(jsonl)
    audit = audit_source(source)
    first = records[0]
    empty_env: dict[str, str] = {}
    default_mode = resolve_track1_mode(env=empty_env)
    unset_mode = resolve_track1_mode(env={"LRA_TRACK1": "", "LRA_GENERATOR": ""})
    leanstral_mode = resolve_track1_mode(env={"LRA_GENERATOR": "leanstral"})
    grok_mode = resolve_track1_mode(env={"LRA_GENERATOR": "grok"})
    flag_mode = resolve_track1_mode(env={"LRA_TRACK1": "1"})
    track2_grok = resolve_track1_mode(
        env={"LRA_GENERATOR": "grok", "LRA_OFFICIAL_TRACK2": "1"},
        official_track2=True,
    )
    track2_env = resolve_track1_mode(env={"LRA_TRACK1": "1", "LRA_TRACK": "official_track2"})
    unknown_closed = False
    try:
        resolve_track1_mode(flag="on-fire")
    except Track1LedgerError:
        unknown_closed = True

    off_run = run_named(str(first["name"]), mode="off", env=empty_env, path=jsonl)
    no_key_run = run_named(str(first["name"]), mode="track1", env=empty_env, path=jsonl)
    fixture_client = FixtureGrok()
    fixture_run = run_named(
        str(first["name"]),
        mode="track1",
        env={"LRA_TRACK1": "1"},
        fixture=True,
        generate=fixture_client,
        get_trace=fixture_trace,
        path=jsonl,
    )
    repair_client = FixtureGrok("omega")
    repair_run = run_named(
        str(first["name"]),
        mode="track1",
        fixture=True,
        repair=True,
        generate=repair_client,
        get_trace=fixture_trace,
        path=jsonl,
    )
    official_run = run_named(
        str(first["name"]),
        mode="track1",
        official_track2=True,
        fixture=True,
        generate=FixtureGrok(),
        get_trace=fixture_trace,
        path=jsonl,
    )
    leanstral_closed = False
    leanstral_error = ""
    lean_ledger = ProblemLedger(name="leanstral-fallback")
    try:
        generate_grok(
            "simp",
            lean_ledger,
            generate=lambda prompt, **kwargs: "simp",
            get_trace=lambda: {
                "effective_provider_name": "leanstral_local",
                "effective_model_name": "Leanstral",
            },
            fixture=True,
        )
    except Track1LedgerError as exc:
        leanstral_closed = True
        leanstral_error = str(exc)

    kwargs = audit["fail_closed_kwargs"]
    captured: dict[str, Any] = {}

    def fake_generate(prompt: str, **call_kwargs: Any) -> str:
        captured["prompt"] = prompt
        captured["kwargs"] = dict(call_kwargs)
        return "simp"

    mock_ledger = ProblemLedger(name="mock-kwargs")
    mock_text, mock_identity, mock_line = generate_grok(
        "simp the goal",
        mock_ledger,
        generate=fake_generate,
        get_trace=fixture_trace,
        fixture=True,
    )
    mock_kwargs = captured.get("kwargs") or {}
    expected_kwargs = {
        "provider": "grok",
        "model_name": "grok-4.6",
        "temperature": 0.0,
        "allow_local_fallback": False,
        "allow_cross_provider_fallback": False,
        "disable_model_retry": True,
    }
    mock_kwargs_ok = all(mock_kwargs.get(key) == value for key, value in expected_kwargs.items())
    hard_stop = _hard_stop_probe()
    receipts = _receipt_probe()
    from jevops.outer import dumps_sorted

    serialized = dumps_sorted({"fixture": fixture_run, "repair": repair_run})
    key_leak = any(token in serialized for token in ("BEGIN SECRET", "sk-live-", "sk-prod-", "xai-"))

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
        "modes": {
            "default": default_mode,
            "unset_env": unset_mode,
            "leanstral": leanstral_mode,
            "grok": grok_mode,
            "lra_track1": flag_mode,
            "official_track2_with_grok_flag": track2_grok,
            "official_track2_env": track2_env,
            "unknown_closed": unknown_closed,
        },
        "off_run": off_run,
        "no_key_run": no_key_run,
        "fixture_run": {
            "skipped": fixture_run.get("skipped"),
            "reason": fixture_run.get("reason"),
            "called_grok": fixture_run.get("called_grok"),
            "called_jev": fixture_run.get("called_jev"),
            "used_fixture": fixture_run.get("used_fixture"),
            "grok_calls": fixture_run.get("grok_calls"),
            "jev_calls": fixture_run.get("jev_calls"),
            "spent_usd": fixture_run.get("spent_usd"),
            "hard_stopped": fixture_run.get("hard_stopped"),
            "contaminates_track2": fixture_run.get("contaminates_track2"),
            "arena_score": fixture_run.get("arena_score"),
            "text": fixture_run.get("text"),
            "identity": fixture_run.get("identity"),
        },
        "repair_run": {
            "skipped": repair_run.get("skipped"),
            "reason": repair_run.get("reason"),
            "grok_calls": repair_run.get("grok_calls"),
            "jev_calls": repair_run.get("jev_calls"),
            "text": repair_run.get("text"),
            "spent_usd": repair_run.get("spent_usd"),
        },
        "official_track2_run": official_run,
        "fail_closed_kwargs": kwargs,
        "fail_closed_kwargs_match": kwargs == expected_kwargs,
        "mock_call_kwargs": {key: mock_kwargs.get(key) for key in expected_kwargs},
        "mock_call_kwargs_match": mock_kwargs_ok,
        "mock_resolved": asdict(mock_identity),
        "mock_text": mock_text,
        "mock_line": mock_line.as_dict(),
        "leanstral_fallback_closed": leanstral_closed,
        "leanstral_fallback_error": leanstral_error,
        "hard_stop": hard_stop,
        "receipts": receipts,
        "default_mode_is_off": default_mode == "off" and unset_mode == "off" and leanstral_mode == "off",
        "not_default_winning_path": IS_DEFAULT_WINNING_PATH is False and default_mode == "off",
        "grok_opt_in": grok_mode == "track1" and flag_mode == "track1",
        "official_track2_stays_off": track2_grok == "off" and track2_env == "off",
        "off_skipped": bool(off_run.get("skipped")) and off_run.get("reason") == "not_default_winning_path",
        "no_key_skipped": bool(no_key_run.get("skipped")) and no_key_run.get("reason") == "no_key",
        "fixture_generated": (
            fixture_run.get("skipped") is False
            and fixture_run.get("called_grok") is True
            and fixture_run.get("used_fixture") is True
            and fixture_run.get("text") == "simp"
        ),
        "repair_two_grok_calls": repair_run.get("grok_calls") == 2 and repair_run.get("text") == "omega",
        "official_did_not_call": (
            official_run.get("skipped") is True
            and official_run.get("reason") == "official_track2_off"
            and official_run.get("called_grok") is False
        ),
        "hard_stop_at_3_including_jev_grok": hard_stop["ok"],
        "does_not_contaminate_track2": receipts["ok"] and official_run.get("contaminates_track2") is False,
        "skip_if_keys_missing": True,
        "imports_llm_router": audit["imports_llm_router"],
        "imports_typesafe_sdk": audit["imports_typesafe_sdk"],
        "key_leak": key_leak,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
        "arena_score": None,
        "first_name": first.get("name"),
        "warmup_path": str(jsonl.relative_to(REPO_ROOT)),
        "budget_usd": PROBLEM_BUDGET_USD_FLOAT,
        "max_grok_calls": MAX_GROK_CALLS,
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and audit["ok"]
        and report["default_mode_is_off"]
        and report["not_default_winning_path"]
        and report["grok_opt_in"]
        and report["official_track2_stays_off"]
        and report["off_skipped"]
        and report["no_key_skipped"]
        and report["fixture_generated"]
        and report["repair_two_grok_calls"]
        and report["official_did_not_call"]
        and report["hard_stop_at_3_including_jev_grok"]
        and report["does_not_contaminate_track2"]
        and report["fail_closed_kwargs_match"]
        and report["mock_call_kwargs_match"]
        and mock_identity.resolved_provider == "xai"
        and mock_identity.resolved_model == REQUESTED_MODEL
        and not mock_identity.fallback_used
        and mock_identity.arena_score is None
        and leanstral_closed
        and "leanstral" in leanstral_error.lower()
        and unknown_closed
        and not key_leak
        and report["compiled"] is False
        and report["arena_score"] is None
        and fixture_run.get("arena_score") is None
        and fixture_run.get("contaminates_track2") is False
        and fixture_client.calls
        and fixture_client.calls[0]["kwargs"].get("provider") == "grok"
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="CI fixtures; no live key; no POST")
    parser.add_argument("--plan", action="store_true", help="dump mode resolution and budget constants")
    parser.add_argument("--run", action="store_true", help="run the Track 1 adapter+ledger on --name")
    parser.add_argument("--name", default="", help="JSONL problem name")
    parser.add_argument("--track1", action="store_true", help="opt in to Track 1 (not the default path)")
    parser.add_argument("--official-track2", action="store_true", help="force official Track 2 off")
    parser.add_argument("--fixture", action="store_true", help="use CI fixture grok/Jev; no live key")
    parser.add_argument("--repair", action="store_true", help="1 draft + 1 Lean-feedback repair")
    parser.add_argument("--jsonl", type=Path, default=None, help="warmup JSONL path")
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=None,
        help="optional Track 1 receipts directory (refuses Track 2 paths)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.plan:
        from jevops.outer import print_ok

        return print_ok(plan_view(mode="track1" if args.track1 else None, official_track2=args.official_track2))
    if args.run:
        if not args.name:
            parser.error("--run requires --name")
        from jevops.outer import failed_check, print_json

        try:
            payload = run_named(
                args.name,
                mode="track1" if args.track1 else None,
                official_track2=args.official_track2,
                fixture=args.fixture,
                repair=args.repair,
                path=args.jsonl,
                receipts_dir=args.receipts_dir,
            )
        except (Track1LedgerError, lra_splice.SpliceError, lra_retrieve.RetrieveError) as exc:
            print_json(
                failed_check(
                    exc,
                    contaminates_track2=False,
                    is_default_winning_path=False,
                )
            )
            return 1
        from jevops.outer import print_ok

        return print_ok(payload)
    if args.self_check or argv is None or argv == []:
        from jevops.outer import print_ok

        return print_ok(self_check(args.jsonl))
    parser.error("choose --self-check, --plan, or --run")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
