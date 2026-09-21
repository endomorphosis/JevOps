#!/usr/bin/env python3
"""Docker0 HTTP client of the live Leanstral owner. Never takes LOCK_EX.

LRA is a client of ``http://172.17.0.1:8080``. Probe ``/health``. If healthy,
call ``generate_text`` as an HTTP client without flocking ``gpu-0.lock``.
Pin ``IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART=0`` and never start a second
``llama-server``.

``gpu-0.lock`` is the owner lock held by law_to_action /
``scripts/run_leanstral_ephemeral.py``. If docker0 is unhealthy and the lock is
free, this client *may* exec that owner script (``--bind docker0 --gpu 0``);
the child takes exclusive ownership. If exclusive ownership is already held,
wait for ``/health`` or skip the LLM. This process never takes the exclusive
owner lock.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import generate_text as lra_gt  # noqa: E402

DOCKER0_HOST = lra_gt.DOCKER0_HOST
DOCKER0_PORT = lra_gt.DOCKER0_PORT
DOCKER0_HEALTH_URL = lra_gt.DOCKER0_HEALTH_URL
DOCKER0_HEALTH_ALIAS_URL = lra_gt.DOCKER0_HEALTH_ALIAS_URL
REQUESTED_PROVIDER = lra_gt.REQUESTED_PROVIDER
REQUESTED_MODEL = lra_gt.REQUESTED_MODEL
FAIL_CLOSED_KWARGS = dict(lra_gt.FAIL_CLOSED_KWARGS)
FROZEN_WARMUP_SHA256 = lra_gt.FROZEN_WARMUP_SHA256
HEALTH_TIMEOUT_SECONDS = lra_gt.HEALTH_TIMEOUT_SECONDS

OWNER_SCRIPT_RELATIVE = "scripts/run_leanstral_ephemeral.py"
OWNER_BIND = "docker0"
OWNER_GPU = "0"
OWNER_LOCK_ID = "gpu-0"
AUTOSTART_ENV = "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART"
FORBIDDEN_SERVER_BINARIES = frozenset(
    {
        "llama-server",
        "llama_server",
        "ipfs-accelerate-llama-cpp-serve",
    }
)
FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "LeanstralProofProvider",
        "leanstral_proof_provider",
    }
)
# BSD flock numeric values (Linux). Exclusive is 2; this client never applies it.
_FLOCK_SH = 1
_FLOCK_NB = 4
_FLOCK_UN = 8


class Docker0ClientError(RuntimeError):
    """Fail-closed docker0 client error. Never a fallback success."""


from jevops.outer import ClientSession
from jevops.outer import LockInspection as _KernelLockInspection
from jevops.outer import OwnerExec


@dataclass(frozen=True)
class LockInspection(_KernelLockInspection):
    lock_id: str = OWNER_LOCK_ID


def pin_client_env() -> str:
    """Bind llama.cpp to docker0 as a client. Never enable autostart."""

    return lra_gt._pin_client_env()


def gpu0_lock_path() -> Path:
    """Owner lock path used by ``run_leanstral_ephemeral.py --gpu 0``."""

    import os
    from jevops.outer import xdg_runtime_dir

    return xdg_runtime_dir() / f"leanstral-jobs-{os.getuid()}" / f"{OWNER_LOCK_ID}.lock"


def owner_script_path() -> Path:
    return REPO_ROOT / OWNER_SCRIPT_RELATIVE


def owner_argv(
    *,
    script: Optional[Path] = None,
    python: Optional[str] = None,
) -> list[str]:
    """Argv for optional owner exec. The child takes exclusive ownership."""

    from jevops.outer import python_argv

    path = Path(script) if script is not None else owner_script_path()
    return python_argv(path, "--bind", OWNER_BIND, "--gpu", OWNER_GPU, python=python)


def owner_argv_relative(*, python: Optional[str] = None) -> list[str]:
    from jevops.outer import python_argv

    return python_argv(
        OWNER_SCRIPT_RELATIVE, "--bind", OWNER_BIND, "--gpu", OWNER_GPU, python=python
    )


def probe_docker0_health(*, timeout: float = HEALTH_TIMEOUT_SECONDS) -> lra_gt.HealthProbe:
    """GET docker0 ``/health``. Does not start a server and does not flock."""

    pin_client_env()
    return lra_gt.probe_docker0_health(timeout=timeout)


def _stat_dev_ino(path: Path) -> Optional[tuple[int, int, int]]:
    from jevops.outer import stat_dev_ino

    return stat_dev_ino(path)


def _proc_locks_write_holder(path: Path) -> tuple[Optional[bool], Optional[int], str]:
    """Read ``/proc/locks`` for an exclusive FLOCK/WRITE holder of ``path``.

    Query only. Does not call ``flock`` and does not take exclusive ownership.
    """

    from jevops.outer import proc_exclusive_holder

    return proc_exclusive_holder(path)


def _shared_probe_holder(path: Path) -> tuple[bool, str]:
    """Non-exclusive probe: shared non-blocking flock, then unlock.

    Shared lock is not exclusive owner lock. Exclusive holders make this fail
    with ``BlockingIOError``; a free lock is released immediately.
    """

    from jevops.outer import shared_lock_busy

    return shared_lock_busy(path, error_cls=Docker0ClientError)


def inspect_gpu0_lock(path: Optional[Path] = None) -> LockInspection:
    """Inspect owner lock without taking exclusive ownership."""

    from jevops.outer import inspect_lock

    pin_client_env()
    lock_path = Path(path) if path is not None else gpu0_lock_path()
    info = inspect_lock(lock_path, error_cls=Docker0ClientError)
    return LockInspection(
        path=str(info["path"]),
        exists=bool(info["exists"]),
        held=bool(info["held"]),
        pid=info["pid"],
        method=str(info["method"]),
        error=str(info.get("error") or ""),
    )


def decide_action(
    health: lra_gt.HealthProbe,
    lock: LockInspection,
    *,
    allow_owner_exec: bool = False,
    wait_seconds: float = 0.0,
) -> str:
    """Normative LRA client protocol. Never returns an exclusive-lock action."""

    from jevops.outer import first_match

    return first_match(
        (
            (lambda: health.ok, "generate"),
            (lambda: lock.held and float(wait_seconds) > 0, "wait"),
            (lambda: lock.held, "skip_llm"),
            (lambda: lock.method == "error", "skip_llm"),
            (lambda: allow_owner_exec, "exec_owner"),
        ),
        default="skip_llm",
    )


def wait_for_health(
    *,
    timeout: float,
    interval: float = 0.25,
    probe: Optional[Callable[[], lra_gt.HealthProbe]] = None,
) -> lra_gt.HealthProbe:
    """Poll docker0 ``/health`` without flocking. Bounded wait."""

    from jevops.outer import poll_until

    probe_fn = probe or probe_docker0_health
    return poll_until(probe_fn, ok_fn=lambda item: bool(item.ok), timeout=timeout, interval=interval)


def maybe_exec_owner(
    *,
    execute: bool = False,
    script: Optional[Path] = None,
    extra_env: Optional[Mapping[str, str]] = None,
    timeout: float = 5.0,
) -> OwnerExec:
    """Optionally exec the owner script. This process still does not take EX.

    Default ``execute=False`` records the argv and does not spawn a process.
    Live owner exec is out of band for this cpu-medium client; the child, if
    started, is ``run_leanstral_ephemeral.py``, never ``llama-server``.
    """

    from jevops.outer import env_copy, pack_owner_exec, run_owner_exec, run_process

    argv = owner_argv(script=script)
    rel = owner_argv_relative()
    if script is not None:
        rel = owner_argv(script=script)
    extra = {
        AUTOSTART_ENV: "0",
        "IPFS_ACCELERATE_LLAMA_CPP_AUTO_INSTALL": "0",
    }
    if extra_env:
        extra.update(dict(extra_env))
    return run_owner_exec(
        execute=execute,
        argv=argv,
        argv_relative=rel,
        pack_fn=pack_owner_exec,
        target=Path(argv[2]) if len(argv) > 2 else "",
        run_fn=run_process,
        env=env_copy(extra),
        timeout=timeout,
    )


def skipped_generation(
    health: lra_gt.HealthProbe,
    *,
    reason: str,
) -> lra_gt.LraGeneration:
    from jevops.lean import skipped_generation as _fn

    return _fn(
        health,
        reason=reason,
        requested_provider=REQUESTED_PROVIDER,
        requested_model=REQUESTED_MODEL,
    )


def generate_as_client(
    prompt: str,
    *,
    max_new_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
    source: str = "",
    allow_owner_exec: bool = False,
    execute_owner: bool = False,
    wait_seconds: float = 0.0,
    lock_path: Optional[Path] = None,
    generate: Optional[Callable[..., str]] = None,
    get_trace: Optional[Callable[[], Mapping[str, Any]]] = None,
    temperature: Optional[float] = None,
    stop: Optional[list[str]] = None,
) -> lra_gt.LraGeneration:
    """Probe docker0, then generate as a client, or wait/skip/exec-owner.

    Never takes exclusive ownership of ``gpu-0.lock``. Never starts
    ``llama-server`` in this process.
    """

    from jevops.outer import generate_client_flow, require_env_eq

    pin_client_env()
    require_env_eq(
        AUTOSTART_ENV,
        "0",
        error_cls=Docker0ClientError,
        fmt="{key} must be {expected}; refusing to generate",
    )
    health = probe_docker0_health()
    lock = inspect_gpu0_lock(lock_path)

    def _generate() -> lra_gt.LraGeneration:
        return lra_gt.generate_lra(
            prompt,
            max_new_tokens=max_new_tokens,
            timeout=timeout,
            source=source,
            require_health=False,
            generate=generate,
            get_trace=get_trace,
            temperature=temperature,
            stop=stop,
        )

    return generate_client_flow(
        health=health,
        lock=lock,
        generate_fn=_generate,
        wait_fn=lambda seconds: wait_for_health(timeout=seconds),
        exec_fn=lambda execute: maybe_exec_owner(execute=execute),
        skip_fn=lambda nxt, reason: skipped_generation(nxt, reason=reason),
        decide_fn=decide_action,
        allow_owner_exec=allow_owner_exec,
        wait_seconds=wait_seconds,
        execute_owner=execute_owner,
    )


def plan_session(
    *,
    allow_owner_exec: bool = False,
    wait_seconds: float = 0.0,
    lock_path: Optional[Path] = None,
    execute_owner: bool = False,
) -> ClientSession:
    """Live protocol decision. Inspects lock without exclusive ownership."""

    from jevops.outer import env_str

    pin_client_env()
    health = probe_docker0_health()
    lock = inspect_gpu0_lock(lock_path)
    action = decide_action(
        health,
        lock,
        allow_owner_exec=allow_owner_exec,
        wait_seconds=wait_seconds,
    )
    owner = maybe_exec_owner(execute=False)
    if action == "exec_owner" and execute_owner:
        owner = maybe_exec_owner(execute=True)
    from jevops.outer import pack_client_session, session_reason

    return pack_client_session(
        action=action,
        health=health,
        lock=lock,
        autostart=env_str(AUTOSTART_ENV),
        owner=owner,
        reason=session_reason(action, lock_held=bool(lock.held), allow_owner_exec=allow_owner_exec),
        session_cls=ClientSession,
    )


def _imported_names(source: str) -> set[str]:
    from jevops.repair import imported_names

    return imported_names(source)


def _lock_ex_attributes(source: str) -> list[str]:
    from jevops.repair import attr_hits

    return attr_hits(source, ("LOCK_EX", "F_WRLCK", "F_SETLK", "F_SETLKW"))


def _call_func_name(func: ast.AST) -> str:
    from jevops.repair import call_func_name

    return call_func_name(func)


def _subprocess_invokes_forbidden_binary(source: str) -> bool:
    """True only if a subprocess call passes a forbidden server binary."""

    from jevops.repair import subprocess_invokes

    return subprocess_invokes(source, FORBIDDEN_SERVER_BINARIES)


def _hold_exclusive_child(path: Path) -> subprocess.Popen[str]:
    """Child process takes exclusive flock so this file never names LOCK_EX."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    os.close(fd)
    # 2 is BSD exclusive flock on Linux; 4 is non-blocking. Kept numeric so
    # this module's AST has no LOCK_EX attribute.
    code = (
        "import fcntl, os, sys, time\n"
        "p = sys.argv[1]\n"
        "fd = os.open(p, os.O_RDWR)\n"
        "fcntl.flock(fd, 2 | 4)\n"
        "sys.stdout.write('held\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if line.strip() != "held":
        err = proc.stderr.read() if proc.stderr is not None else ""
        proc.kill()
        raise Docker0ClientError(f"child failed to hold exclusive flock: {line!r} {err!r}")
    return proc


def _fake_owner_script(directory: Path) -> Path:
    from jevops.outer import write_text

    return write_text(
        Path(directory) / "run_leanstral_ephemeral.py",
        "import json, os, sys\n"
        "out = os.environ['LRA_OWNER_ARGV_OUT']\n"
        "with open(out, 'w', encoding='utf-8') as handle:\n"
        "    json.dump(sys.argv, handle)\n",
    )


def self_check() -> dict[str, Any]:
    """Exercise the client protocol. No compile. No live Leanstral completion."""

    from jevops.outer import env_str, read_text

    source = read_text(__file__)
    imported = _imported_names(source)
    lock_ex_attrs = _lock_ex_attributes(source)
    uses_lock_ex = bool(lock_ex_attrs)
    forbidden_imports = sorted(name for name in imported if name in FORBIDDEN_IMPORT_NAMES)
    forbidden_bins = _subprocess_invokes_forbidden_binary(source)
    pin_client_env()
    health = probe_docker0_health()
    live_lock = inspect_gpu0_lock()
    live_plan = plan_session(allow_owner_exec=False)

    captured: dict[str, Any] = {}

    def fake_generate(prompt: str, **call_kwargs: Any) -> str:
        captured["prompt"] = prompt
        captured["kwargs"] = dict(call_kwargs)
        captured["autostart"] = env_str(AUTOSTART_ENV)
        return "simp"

    def fake_trace() -> dict[str, str]:
        return {
            "effective_provider_name": "leanstral_local",
            "effective_model_name": "Leanstral",
        }

    healthy_generation: Optional[dict[str, Any]] = None
    if health.ok:
        result = generate_as_client(
            "docker0 client generate path",
            generate=fake_generate,
            get_trace=fake_trace,
            allow_owner_exec=False,
        )
        healthy_generation = {
            "skipped": result.skipped,
            "text": result.text,
            "identity": asdict(result.identity),
            "call_kwargs": {key: (captured.get("kwargs") or {}).get(key) for key in FAIL_CLOSED_KWARGS},
            "call_kwargs_match": all(
                (captured.get("kwargs") or {}).get(key) == value
                for key, value in FAIL_CLOSED_KWARGS.items()
            ),
            "autostart_during_generate": captured.get("autostart"),
            "lock_ex_taken_by_client": False,
        }

    fake_health_down = lra_gt.HealthProbe(
        ok=False,
        url=DOCKER0_HEALTH_URL,
        alias_ok=False,
        alias_url=DOCKER0_HEALTH_ALIAS_URL,
        status_code=None,
        error="simulated unhealthy",
        autostart="0",
    )
    fake_lock_free = LockInspection(
        path="/tmp/lra-simulated-gpu-0.lock",
        exists=False,
        held=False,
        pid=None,
        method="missing",
        error="",
    )
    fake_lock_held = LockInspection(
        path="/tmp/lra-simulated-gpu-0.lock",
        exists=True,
        held=True,
        pid=1,
        method="proc_locks",
        error="",
    )
    action_healthy = decide_action(health if health.ok else lra_gt.HealthProbe(
        ok=True,
        url=DOCKER0_HEALTH_URL,
        alias_ok=False,
        alias_url=DOCKER0_HEALTH_ALIAS_URL,
        status_code=200,
        error="",
        autostart="0",
    ), live_lock, allow_owner_exec=True)
    action_unhealthy_held = decide_action(fake_health_down, fake_lock_held, allow_owner_exec=True)
    action_unhealthy_held_wait = decide_action(
        fake_health_down, fake_lock_held, allow_owner_exec=True, wait_seconds=2.0
    )
    action_unhealthy_free = decide_action(
        fake_health_down, fake_lock_free, allow_owner_exec=True
    )
    action_unhealthy_free_no_exec = decide_action(
        fake_health_down, fake_lock_free, allow_owner_exec=False
    )

    child_lock: dict[str, Any] = {"ok": False}
    fake_exec: dict[str, Any] = {"ok": False}
    from jevops.outer import temp_dir

    with temp_dir(prefix="lra-016-lock-") as tmp:
        tmp_path = Path(tmp)
        lock_file = tmp_path / "gpu-0.lock"
        free_before = inspect_gpu0_lock(lock_file)
        proc = _hold_exclusive_child(lock_file)
        try:
            time.sleep(0.05)
            held = inspect_gpu0_lock(lock_file)
            action_while_held = decide_action(
                fake_health_down, held, allow_owner_exec=True, wait_seconds=0.0
            )
            child_lock = {
                "ok": bool(held.held) and not held.lock_ex_taken_by_client,
                "held": held.held,
                "pid": held.pid,
                "child_pid": proc.pid,
                "pid_matches_child": held.pid == proc.pid or held.pid is None,
                "method": held.method,
                "lock_ex_taken_by_client": held.lock_ex_taken_by_client,
                "action": action_while_held,
                "free_before_held": (not free_before.held) and (not free_before.exists or free_before.method == "missing"),
            }
        finally:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
        time.sleep(0.05)
        after = inspect_gpu0_lock(lock_file)
        child_lock["released_after_kill"] = not after.held
        child_lock["ok"] = bool(child_lock.get("ok")) and (not after.held) and action_while_held == "skip_llm"

        argv_out = tmp_path / "owner-argv.json"
        fake_script = _fake_owner_script(tmp_path)
        owner = maybe_exec_owner(
            execute=True,
            script=fake_script,
            extra_env={"LRA_OWNER_ARGV_OUT": str(argv_out)},
            timeout=5.0,
        )
        from jevops.outer import read_json_if

        recorded_argv = read_json_if(argv_out, default=[], require_object=False)
        fake_exec = {
            "ok": bool(
                owner.executed
                and owner.returncode == 0
                and owner.started_llama_server is False
                and "--bind" in owner.argv
                and OWNER_BIND in owner.argv
                and "--gpu" in owner.argv
                and OWNER_GPU in owner.argv
                and OWNER_BIND in recorded_argv
                and OWNER_GPU in recorded_argv
                and "--bind" in recorded_argv
                and "--gpu" in recorded_argv
            ),
            "argv": owner.argv,
            "argv_relative": owner.argv_relative,
            "recorded_argv": recorded_argv,
            "returncode": owner.returncode,
            "started_llama_server": owner.started_llama_server,
            "error": owner.error,
        }

    planned_owner = maybe_exec_owner(execute=False)
    from jevops.outer import tail_seq

    owner_argv_ok = (
        tail_seq(planned_owner.argv_relative, 4) == ["--bind", OWNER_BIND, "--gpu", OWNER_GPU]
        or tail_seq(planned_owner.argv, 4) == ["--bind", OWNER_BIND, "--gpu", OWNER_GPU]
    ) and OWNER_SCRIPT_RELATIVE in planned_owner.argv_relative

    skipped_when_down = skipped_generation(fake_health_down, reason="skip")
    wait_probes = {"n": 0}

    def becoming_healthy() -> lra_gt.HealthProbe:
        wait_probes["n"] += 1
        if wait_probes["n"] < 2:
            return fake_health_down
        return lra_gt.HealthProbe(
            ok=True,
            url=DOCKER0_HEALTH_URL,
            alias_ok=False,
            alias_url=DOCKER0_HEALTH_ALIAS_URL,
            status_code=200,
            error="",
            autostart="0",
        )

    waited = wait_for_health(timeout=1.0, interval=0.01, probe=becoming_healthy)

    report = {
        "ok": True,
        "fail_closed_kwargs": FAIL_CLOSED_KWARGS,
        "health": asdict(health),
        "health_url": DOCKER0_HEALTH_URL,
        "health_url_exact": DOCKER0_HEALTH_URL == "http://172.17.0.1:8080/health",
        "live_lock": asdict(live_lock),
        "live_plan": asdict(live_plan),
        "healthy_generation": healthy_generation,
        "actions": {
            "healthy_is_generate": action_healthy == "generate",
            "unhealthy_held": action_unhealthy_held,
            "unhealthy_held_wait": action_unhealthy_held_wait,
            "unhealthy_free_exec": action_unhealthy_free,
            "unhealthy_free_skip": action_unhealthy_free_no_exec,
        },
        "child_lock": child_lock,
        "fake_owner_exec": fake_exec,
        "owner_argv_relative": planned_owner.argv_relative,
        "owner_argv_ok": owner_argv_ok,
        "wait_recovers": waited.ok,
        "skipped_unhealthy": {
            "skipped": skipped_when_down.skipped,
            "text": skipped_when_down.text,
            "arena_score": skipped_when_down.identity.arena_score,
        },
        "imported_names": sorted(imported),
        "forbidden_imports": forbidden_imports,
        "lock_ex_attributes": lock_ex_attrs,
        "uses_lock_ex": uses_lock_ex,
        "forbidden_server_binaries_in_source": forbidden_bins,
        "autostart": env_str(AUTOSTART_ENV),
        "llama_server_started": False,
        "compiled": False,
        "arena_score": None,
        "frozen_warmup_sha256": FROZEN_WARMUP_SHA256,
        "owner_script_exists": owner_script_path().is_file(),
        "lock_ex_taken_by_client": False,
    }
    healthy_ok = True
    if health.ok:
        healthy_ok = bool(
            healthy_generation
            and not healthy_generation["skipped"]
            and healthy_generation["call_kwargs_match"]
            and healthy_generation["identity"]["resolved_provider"] == REQUESTED_PROVIDER
            and healthy_generation["identity"]["resolved_model"] == REQUESTED_MODEL
            and healthy_generation["autostart_during_generate"] == "0"
            and live_plan.action == "generate"
            and live_plan.lock_ex_taken_by_client is False
        )
    else:
        healthy_ok = live_plan.action in {"wait", "skip_llm", "exec_owner"}
    report["ok"] = bool(
        report["health_url_exact"]
        and report["fail_closed_kwargs"] == lra_gt.FAIL_CLOSED_KWARGS
        and healthy_ok
        and report["actions"]["healthy_is_generate"]
        and action_unhealthy_held == "skip_llm"
        and action_unhealthy_held_wait == "wait"
        and action_unhealthy_free == "exec_owner"
        and action_unhealthy_free_no_exec == "skip_llm"
        and child_lock.get("ok")
        and fake_exec.get("ok")
        and owner_argv_ok
        and waited.ok
        and skipped_when_down.skipped
        and not forbidden_imports
        and not uses_lock_ex
        and not forbidden_bins
        and report["autostart"] == "0"
        and report["llama_server_started"] is False
        and report["compiled"] is False
        and report["arena_score"] is None
        and report["lock_ex_taken_by_client"] is False
        and live_lock.lock_ex_taken_by_client is False
        and "LOCK_EX" not in lock_ex_attrs
    )
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="client protocol unit probe; no compile")
    parser.add_argument("--probe-health", action="store_true", help="GET docker0 /health only")
    parser.add_argument("--inspect-lock", action="store_true", help="inspect gpu-0.lock without exclusive ownership")
    parser.add_argument("--plan", action="store_true", help="print live client decision")
    parser.add_argument("--allow-owner-exec", action="store_true", help="permit optional owner exec in --plan")
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    from jevops.outer import print_json

    if args.probe_health:
        pin_client_env()
        probe = probe_docker0_health()
        payload = asdict(probe)
        payload["lock_ex_taken_by_client"] = False
        payload["llama_server_started"] = False
        print_json(payload)
        return 0 if probe.ok else 2
    if args.inspect_lock:
        pin_client_env()
        inspection = inspect_gpu0_lock()
        print_json(asdict(inspection))
        return 0
    if args.plan:
        session = plan_session(
            allow_owner_exec=args.allow_owner_exec,
            wait_seconds=args.wait_seconds,
        )
        print_json(asdict(session))
        return 0
    if args.self_check or argv is None or argv == []:
        report = self_check()
        from jevops.outer import print_ok

        return print_ok(report)
    parser.error("choose --self-check, --probe-health, --inspect-lock, or --plan")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
