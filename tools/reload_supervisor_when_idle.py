#!/usr/bin/env python3
"""Reload only the registered repair daemon after its current worker exits.

Queue this from a separate user-systemd oneshot, never synchronously from a
repair worker. Native presence locking prevents a new dispatch during the
handoff. This utility never signals an actor or rewrites repair/task state.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = 'config/lean_refactor_arena_20261024_watchdog.json'
MODULE = 'ipfs_accelerate_py.agent_supervisor.rescue.repair_dispatcher'
UNIT = 'jevops-agent-supervisor-repair.service'
FLAGS = {'completion_authority': False, 'task_states_changed': False,
         'worker_signals_sent': False, 'provider_calls': 0, 'work_complete': False}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def read_json(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and before.st_size <= 8 * 1024 * 1024, 'Expected bounded owned ordinary JSON: ' + str(path))
    raw = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'Control JSON changed while reading')
    value = json.loads(raw)
    require(type(value) is dict, 'Expected JSON object')
    return value


def local(root, value):
    require(isinstance(value, str) and value and not Path(value).is_absolute()
            and '..' not in Path(value).parts, 'Expected repo-relative scope')
    path = root / value
    require(path.resolve().is_relative_to(root), 'Configured scope escapes repository')
    return path


def scope(root):
    root = root.resolve(strict=True)
    cfg = read_json(root / CONFIG)
    require(cfg['schema'] == 'jevops.persistent-supervisor-watchdog.v1' and cfg['repair_unit'] == UNIT
            and cfg['guardian_unit'] != UNIT, 'Unexpected registered repair unit')
    supervisor = read_json(local(root, cfg['supervisor_profile']))
    manifest_path = local(root, cfg['runtime_manifest'])
    manifest = read_json(manifest_path)
    require(isinstance(manifest.get('lanes'), list) and len(manifest['lanes']) == 1,
            'Expected one isolated registered lane')
    source = Path(supervisor['accelerator_source']).resolve(strict=True)
    expected = source / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
    require(expected.is_file() and Path(supervisor['python_executable']).is_absolute(), 'Native runtime missing')
    sys.path.insert(0, str(source))
    native = importlib.import_module(MODULE)
    require(Path(native.__file__).resolve() == expected.resolve(), 'Wrong native dispatcher import origin')
    state = local(root, cfg['state_root'])
    native_cfg = native.Config(repo_root=root, manifest_path=manifest_path, state_dir=state / 'repair-dispatcher',
        repair_lock_path=state / 'fixer.lock', hold_paths=(manifest_path.parent / 'HOLD',
            local(root, manifest['lanes'][0]['state_dir']) / 'HOLD'))
    control_inputs = [root / CONFIG, local(root, cfg['supervisor_profile']), manifest_path]
    return {'root': root, 'cfg': cfg, 'supervisor': supervisor, 'manifest': manifest,
            'manifest_path': manifest_path, 'state': state, 'native_cfg': native_cfg, 'native': native,
            'control_json': dict(zip(map(str, control_inputs), (cfg, supervisor, manifest))),
            'control_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in control_inputs}}


def unchanged_scope(binding):
    for path, original in binding['control_json'].items():
        require(read_json(Path(path)) == original and hashlib.sha256(Path(path).read_bytes()).hexdigest()
                == binding['control_sha256'][path], 'Registered scope changed while waiting')


def idle_observation(binding):
    native, cfg, manifest = binding['native'], binding['native_cfg'], binding['manifest']
    holds = set(native._configured_holds(cfg, manifest))
    for lane in manifest['lanes']:
        directory = local(binding['root'], lane['state_dir'])
        holds.update(directory / name for name in ('hold', 'HOLD', 'operator.hold', 'OPERATOR_STOP', 'watchdog.disabled'))
    present = sorted(str(path) for path in holds if path.exists())
    if present:
        return {'idle': False, 'reason': 'operator_hold', 'hold_paths': present}
    state_path = cfg.state_dir / 'state.json'
    if not state_path.exists():
        return {'idle': False, 'reason': 'repair_state_unavailable'}
    state = read_json(state_path)
    if state.get('spawn_intent'):
        return {'idle': False, 'reason': 'spawn_intent_requires_triage'}
    worker = state.get('active_worker')
    if worker:
        require(type(worker) is dict and type(worker.get('pid')) is int and worker['pid'] > 0,
                'Malformed active worker state')
        actual = native.probe_process(worker['pid'])
        if actual['alive']:
            exact = (actual.get('start_ticks') == worker.get('start_ticks')
                     and worker.get('owned_session') is True
                     and actual.get('pgid') == worker['pid'] == actual.get('session_id'))
            return {'idle': False, 'reason': 'repair_worker_active' if exact else 'worker_identity_uncertain',
                    'worker_pid': worker['pid'], 'kernel_start_ticks': actual.get('start_ticks')}
        if actual.get('process_state') not in {None, 'Z', 'X'}:
            return {'idle': False, 'reason': 'worker_identity_uncertain', 'worker_pid': worker['pid']}
        if actual.get('process_state') is None:
            try:
                (Path('/proc') / str(worker['pid'])).lstat()
            except FileNotFoundError:
                pass  # Only independently confirmed absence is a dead PID.
            except OSError:
                return {'idle': False, 'reason': 'worker_identity_uncertain', 'worker_pid': worker['pid']}
            else:
                return {'idle': False, 'reason': 'worker_identity_uncertain', 'worker_pid': worker['pid']}
    return {'idle': True, 'reason': 'no_actual_worker_or_spawn_intent',
            'state_sha256': hashlib.sha256(state_path.read_bytes()).hexdigest()}


def command(argv, timeout):
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=timeout, check=True)


def service_snapshot(binding, *, run=command, proc_root=Path('/proc'), timeout=10):
    properties = 'Id,LoadState,ActiveState,MainPID,WorkingDirectory,KillMode,FragmentPath'
    result = run(['systemctl', '--user', 'show', UNIT, '--property=' + properties], timeout)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    root = binding['root']
    require(values.get('Id') == UNIT and values.get('LoadState') == 'loaded'
            and values.get('WorkingDirectory') == str(root) and values.get('KillMode') == 'process',
            'Registered repair service scope/lifecycle differs')
    fragment = Path(values.get('FragmentPath', ''))
    expected = Path.home() / '.config/systemd/user' / UNIT
    require(fragment == expected and not fragment.is_symlink(), 'Unexpected registered service fragment')
    info = fragment.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and fragment.read_text().startswith('# Managed by JevOps tools/manage_supervisor_watchdog.py'),
            'Service is not an owned managed repair unit')
    pid = int(values.get('MainPID', '0'))
    identity = None
    if pid:
        actual = binding['native'].probe_process(pid)
        proc = proc_root / str(pid)
        require(proc.stat().st_uid == os.getuid() and actual['alive']
                and (proc / 'exe').resolve() == Path(binding['supervisor']['python_executable']).resolve(),
                'Registered daemon kernel identity differs')
        argv = actual.get('argv', [])
        mode, module, index = binding['native']._python_entrypoint(argv)
        require(mode == 'module' and module == MODULE
                and all(value in {'-B', '-u', '-E', '-s', '-S', '-I', '-O', '-OO'} for value in argv[1:index])
                and actual.get('cwd') == str(root), 'Registered daemon is not this native repair dispatcher')
        args = argv[index + 2:]
        for name, expected_path in (('--repo-root', root), ('--manifest-path', binding['manifest_path']),
                                    ('--state-dir', binding['native_cfg'].state_dir),
                                    ('--repair-lock-path', binding['native_cfg'].repair_lock_path)):
            require(args.count(name) == 1 and args.index(name) + 1 < len(args)
                    and Path(args[args.index(name) + 1]) == expected_path,
                    'Registered dispatcher argv scope differs: ' + name)
        require(args.count('--apply') == 1, 'Registered dispatcher is not the configured repair owner')
        identity = {'pid': pid, 'start_ticks': actual.get('start_ticks')}
    return {'properties': values, 'identity': identity,
            'fragment_sha256': hashlib.sha256(fragment.read_bytes()).hexdigest()}


def owned_presence(binding):
    path = binding['native_cfg'].repair_lock_path
    marker = read_json(path)
    actual = binding['native'].probe_process(os.getpid())
    require(marker.get('schema') == binding['native'].SCHEMA and marker.get('pid') == os.getpid()
            and marker.get('start_ticks') == actual.get('start_ticks') and marker.get('token'),
            'Native reload presence is not owned')
    info = path.lstat()
    return info.st_dev, info.st_ino, marker['token']


def reload_when_idle(root, *, timeout=1200, once=False, run=command):
    require(type(timeout) is int and 1 <= timeout <= 1800, 'Reload deadline must be 1..1800 seconds')
    deadline = time.monotonic() + timeout
    last = {'idle': False, 'reason': 'not_observed'}
    while time.monotonic() < deadline:
        binding = scope(root)
        native = binding['native']
        try:
            with native.repair_lock(binding['native_cfg'].repair_lock_path):
                fence = owned_presence(binding)
                last = idle_observation(binding)
                if last['idle'] and time.monotonic() < deadline:
                    before = service_snapshot(binding, run=run,
                        timeout=min(10, max(.01, deadline-time.monotonic())))
                    # Close the observation-to-restart race while still holding
                    # the SAME native marker used by every repair dispatch.
                    last = idle_observation(binding)
                    require(owned_presence(binding) == fence, 'Reload presence changed')
                    if last['idle'] and time.monotonic() < deadline:
                        unchanged_scope(binding)
                        run(['systemctl', '--user', 'restart', UNIT], min(30, max(.1, deadline-time.monotonic())))
                        # An old daemon may publish while systemctl waits for
                        # its stop. Only a tick after that wait proves the
                        # replacement has actually entered its observer loop.
                        restart_completed_at = time.time()
                        while time.monotonic() < deadline:
                            after = service_snapshot(binding, run=run,
                                timeout=min(10, max(.01, deadline-time.monotonic())))
                            require(owned_presence(binding) == fence, 'Reload presence changed after restart')
                            if (after['properties'].get('ActiveState') == 'active' and after['identity']
                                    and after['identity'] != before['identity']):
                                status_path = binding['native_cfg'].state_dir / 'status.json'
                                if status_path.exists():
                                    fresh = read_json(status_path)
                                    if (fresh.get('schema') == native.SCHEMA
                                            and type(fresh.get('observed_at')) in {int, float}
                                            and restart_completed_at <= fresh['observed_at'] <= time.time() + 1):
                                        return {'schema': 'jevops.idle-supervisor-reload.v1', 'reloaded': True,
                                                'unit': UNIT, 'before': before, 'after': after,
                                                'fresh_status_action': fresh.get('action'),
                                                'restart_completed_at': restart_completed_at,
                                                'fresh_status_sha256': hashlib.sha256(status_path.read_bytes()).hexdigest(),
                                                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                                'new_pid_is_not_task_completion': True, **FLAGS}, 0
                            time.sleep(min(.25, max(0, deadline-time.monotonic())))
                        return {'reloaded': False, 'restart_requested': True,
                                'reason': 'new_daemon_readiness_deadline', **FLAGS}, 75
        except native.AlreadyRunning:
            last = {'idle': False, 'reason': 'native_repair_presence_held'}
        if once:
            break
        time.sleep(min(2, max(0, deadline-time.monotonic())))
    return {'schema': 'jevops.idle-supervisor-reload.v1', 'reloaded': False,
            'reason': 'deferred_until_idle', 'last_observation': last, **FLAGS}, 75


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--timeout', type=int, default=1200)
    parser.add_argument('--once', action='store_true', help='Defer immediately if work/hold exists')
    args = parser.parse_args(argv)
    try:
        result, code = reload_when_idle(args.repo_root.resolve(strict=True), timeout=args.timeout, once=args.once)
        print(json.dumps(result, sort_keys=True)); return code
    except (OSError, RuntimeError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'reloaded': False, 'error': str(exc), **FLAGS}), file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
