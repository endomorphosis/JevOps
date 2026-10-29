#!/usr/bin/env python3
"""Render, install or inspect persistent supervision for this JevOps campaign.

Reuse the framework's guardian and repair dispatcher. Installation migrates
only the exact singleton guardian; its existing healthy watchdog is adopted.
No task, model, training job or planned experiment is started by installation.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = 'config/lean_refactor_arena_20261024_watchdog.json'
GUARDIAN = 'ipfs_accelerate_py.agent_supervisor.rescue.watchdog_guardian'
DISPATCHER = 'ipfs_accelerate_py.agent_supervisor.rescue.repair_dispatcher'
REPAIR_SERVICE_WATCHDOG_SECONDS = 120
PROTECTED_PREFLIGHT_TIMEOUT_SECONDS = 1200


def require_native_lane_environment_guard(source):
    """Require actual observer support before installing the opt-in flag."""
    path = Path(source) / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
    module = ast.parse(path.read_text(), filename=str(path))
    declarations = [node for node in module.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'LANE_ENVIRONMENT_GUARD_VERSION'
                            for target in node.targets)]
    require(len(declarations) == 1 and isinstance(declarations[0].value, ast.Constant)
            and type(declarations[0].value.value) is int and declarations[0].value.value == 1,
            'Native repair dispatcher lacks reviewed lane-environment verification support')


def require_native_worker_storage_admission(source):
    """Require native support before installing a maintenance storage reserve."""
    path = Path(source) / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
    module = ast.parse(path.read_text(), filename=str(path))
    declarations = [node for node in module.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'WORKER_STORAGE_ADMISSION_VERSION'
                            for target in node.targets)]
    require(len(declarations) == 1 and isinstance(declarations[0].value, ast.Constant)
            and type(declarations[0].value.value) is int and declarations[0].value.value == 1,
            'Native repair dispatcher lacks reviewed worker-storage admission support')


def require_native_provider_budget_policy(source):
    """Refuse a provider freeze that the installed adapter cannot enforce."""
    path = Path(source) / 'ipfs_accelerate_py/agent_supervisor/todo_daemon/llm.py'
    module = ast.parse(path.read_text(), filename=str(path))
    declarations = [node for node in module.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'PROVIDER_BUDGET_POLICY_VERSION'
                            for target in node.targets)]
    require(len(declarations) == 1 and isinstance(declarations[0].value, ast.Constant)
            and type(declarations[0].value.value) is int and declarations[0].value.value == 1,
            'Native router adapter lacks reviewed provider-budget freeze support')


def require_native_service_watchdog(source):
    """Do not install a timer against a dispatcher that cannot notify it."""
    path = Path(source) / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
    module = ast.parse(path.read_text(), filename=str(path))
    declarations = [node for node in module.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'SERVICE_WATCHDOG_VERSION'
                            for target in node.targets)]
    supported = (len(declarations) == 1 and isinstance(declarations[0].value, ast.Constant)
                 and type(declarations[0].value.value) is int and declarations[0].value.value == 1)
    require(supported, 'Native repair dispatcher lacks reviewed service-watchdog notification support')
RELOAD_UNIT = 'jevops-agent-supervisor-reload.service'
LEGACY_RELOAD_UNIT_SHA256 = 'e5420fa30d16db2136229cb8357100beebc21270d4b26c3074698cc98ba099a9'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), 'Expected owned ordinary JSON: ' + str(path))
    require(info.st_size < 4 * 1024 * 1024, 'JSON input exceeds bound')
    return json.loads(path.read_text())


def atomic(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'Refuse symlink target: ' + str(path))
    temporary = path.with_name('.' + path.name + '.' + str(os.getpid()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()


def save(path, value):
    atomic(path, json.dumps(value, indent=2, sort_keys=True) + '\n')


def command(argv, *, timeout=30, allowed=(0,)):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=timeout, check=False)
    require(result.returncode in allowed, 'Command failed: ' + str(argv[:5]) + ': ' + result.stderr[-1200:])
    return result


def systemd_arg(value, *, exec_start=False):
    value = str(value)
    require(not any(ord(c) < 32 for c in value), 'Control characters cannot appear in unit arguments')
    if exec_start:
        value = value.replace('$', '$$')
    return json.dumps(value.replace('%', '%%'), ensure_ascii=False)


def systemd_path(value):
    value = str(value)
    require(Path(value).is_absolute() and value == value.strip()
            and '\\' not in value and not any(ord(c) < 32 for c in value),
            'Expected unambiguous absolute unit directory')
    # WorkingDirectory is a single path directive, not an argv list. Quotes
    # become part of its pathname; spaces and dollars remain literal.
    return value.replace('%', '%%')


def profile(root):
    cfg = read_json(root / CONFIG)
    require(cfg['schema'] == 'jevops.persistent-supervisor-watchdog.v1', 'Unknown watchdog configuration')
    reserve = cfg.get('worker_minimum_free_bytes')
    require(type(reserve) is int and 64 * 1024 * 1024 <= reserve <= 8 * 1024 ** 3,
            'Maintenance worker storage reserve must be 64 MiB to 8 GiB')
    for name, ceiling in [('poll_seconds', 60), ('heartbeat_seconds', 600), ('report_seconds', 1800),
                          ('quiet_seconds', 3600), ('startup_grace_seconds', 600),
                          ('worker_timeout_seconds', 1800), ('cooldown_seconds', 3600),
                          ('max_cooldown_seconds', 14400), ('max_repair_attempts', 3)]:
        require(type(cfg[name]) is int and 0 < cfg[name] <= ceiling, 'Invalid bounded ' + name)
    require(cfg['activate_planned_work'] is False and cfg['reset_campaign_budgets'] is False,
            'Monitoring cannot activate experiments by status alone or reset campaign budgets')
    require(type(cfg.get('materialize_planned_work', False)) is bool, 'Explicit materialization policy required')
    if cfg.get('materialize_planned_work'):
        require(cfg.get('planned_work_mode') == 'implement_validate_then_activate',
                'Planned work requires implementation and validation before activation')
    for name in ['supervisor_profile', 'lane_manifest', 'runtime_manifest', 'state_root', 'repair_prompt',
                 'provider_budget_policy']:
        relative = Path(cfg[name])
        require(not relative.is_absolute() and '..' not in relative.parts and
                (root / relative).resolve().is_relative_to(root), 'Unsafe configured path')
    require(read_json(root / cfg['provider_budget_policy']).get('new_calls_allowed') is False,
            'An explicit closed provider freeze is required for the exhausted campaign')
    supervisor = read_json(root / cfg['supervisor_profile'])
    require(supervisor['provider'] == 'grok_cli' and supervisor['model'] == 'grok-4.7'
            and supervisor['allow_local_fallback'] is False
            and supervisor['allow_cross_provider_fallback'] is False, 'Campaign route changed')
    for key in ('guardian_unit', 'repair_unit'):
        require(cfg[key].startswith('jevops-agent-supervisor-') and cfg[key].endswith('.service')
                and '/' not in cfg[key] and '\n' not in cfg[key], 'Unexpected unit scope')
    require(cfg['guardian_unit'] != cfg['repair_unit'], 'Distinct units required')
    require(RELOAD_UNIT not in {cfg['guardian_unit'], cfg['repair_unit']}, 'Reload must be a distinct manual unit')
    return cfg, supervisor


def render(root):
    cfg, supervisor = profile(root)
    python = supervisor['python_executable']
    source = supervisor['accelerator_source']
    require(Path(python).is_file() and (Path(source) / 'ipfs_accelerate_py').is_dir(), 'Actual framework/interpreter missing')
    manifest = root / cfg['runtime_manifest']
    state = root / cfg['state_root']
    lane_manifest = read_json(root / cfg['lane_manifest'])
    require(len(lane_manifest['lanes']) == 1 and lane_manifest.get('allow_bounded_task_implement') is False,
            'Expected isolated deterministic lane')
    if cfg.get('materialize_planned_work'):
        require(lane_manifest.get('planned_work_policy', {}).get('enabled') is True,
                'Planned-work recovery must be enabled in the actual manifest')
    lane = lane_manifest['lanes'][0]
    common = [python, '-m']
    guardian = [*common, GUARDIAN, '--manifest-path', str(manifest), '--repo-root', str(root),
                '--python', python, '--poll-seconds', str(cfg['poll_seconds']), '--restart-cooldown', '120', '--apply']
    repair_argv = [cfg['repair_executable'], 'exec', '-c', 'approval_policy="never"',
                   '--sandbox', 'danger-full-access', '-C', str(root), '--json', '-']
    require(Path(repair_argv[0]).is_file() and (root / cfg['repair_prompt']).is_file(), 'Actual repair worker/prompt missing')
    repair = [*common, DISPATCHER, '--manifest-path', str(manifest), '--repo-root', str(root),
              '--required-lane-env', 'JEVOPS_REFACTOR_LLM_BUDGET_POLICY',
              '--worker-min-free-bytes', str(cfg['worker_minimum_free_bytes']),
              '--state-dir', str(state / 'repair-dispatcher'), '--repair-lock-path', str(state / 'fixer.lock'),
              '--prompt-path', str(root / cfg['repair_prompt']), '--worker-argv-json', json.dumps(repair_argv),
              '--hold-path', str(manifest.parent / 'HOLD'),
              '--hold-path', str(root / lane['state_dir'] / 'HOLD'), '--apply']
    for key, option in [('poll_seconds', 'interval'), ('heartbeat_seconds', 'heartbeat-seconds'),
                        ('report_seconds', 'report-seconds'), ('quiet_seconds', 'quiet-seconds'),
                        ('startup_grace_seconds', 'startup-grace-seconds'),
                        ('worker_timeout_seconds', 'worker-timeout'), ('cooldown_seconds', 'cooldown-seconds'),
                        ('max_cooldown_seconds', 'max-cooldown-seconds'), ('max_repair_attempts', 'max-attempts')]:
        repair.extend(['--' + option, str(cfg[key])])
    for relative in ['rescue/watchdog_guardian.py', 'rescue/supervisor_watchdog.py',
                     'rescue/lane_resume.py', 'rescue/repair_dispatcher.py',
                     'rescue/planned_work_watchdog.py', 'todo_daemon/llm.py', 'todo_daemon/budget_policy.py']:
        repair.extend(['--evidence-path', str(Path(source) / 'ipfs_accelerate_py/agent_supervisor' / relative)])
    for relative in [CONFIG, cfg['repair_prompt'], cfg['provider_budget_policy'], 'tools/run_lean_refactor_router_task.py',
                     'tools/check_lean_refactor_plan.py']:
        repair.extend(['--evidence-path', str(root / relative)])

    def unit(name, argv, description):
        # start_new_session does not escape a systemd cgroup. Preserve native
        # adopted actors across monitor restart; their own PID/lock/deadline
        # recovery controls remain responsible for child lifecycle.
        return '\n'.join([
            '# Managed by JevOps tools/manage_supervisor_watchdog.py', '[Unit]',
            'Description=' + description, 'StartLimitIntervalSec=0', '', '[Service]', 'Type=simple',
            'WorkingDirectory=' + systemd_path(root),
            'Environment=' + systemd_arg('PYTHONPATH=' + source),
            'Environment=PYTHONDONTWRITEBYTECODE=1',
            'Environment=' + systemd_arg('JEVOPS_REFACTOR_LLM_BUDGET_POLICY=' + str(root / cfg['provider_budget_policy'])),
            'Environment=' + systemd_arg('PATH=' + str(Path(python).parent) + ':' + str(Path.home() / '.local/bin') + ':/usr/local/bin:/usr/bin:/bin'),
            'ExecStart=' + ' '.join(systemd_arg(a, exec_start=True) for a in argv),
            'Restart=always', 'RestartSec=15s', 'KillMode=process', 'TimeoutStopSec=30s',
            *(['NotifyAccess=main', 'WatchdogSec=' + str(REPAIR_SERVICE_WATCHDOG_SECONDS) + 's',
               # A watchdog recovery must skip the interrupted Python cleanup:
               # durable worker identity/deadline lets its replacement adopt it.
               'WatchdogSignal=SIGKILL'] if name == cfg['repair_unit'] else []),
            'CPUAccounting=yes', 'MemoryAccounting=yes', 'TasksAccounting=yes',
            'StandardOutput=journal', 'StandardError=journal', 'SyslogIdentifier=' + name[:-8],
            'LogRateLimitIntervalSec=30s', 'LogRateLimitBurst=100', '', '[Install]',
            'WantedBy=default.target', ''])
    units = {cfg['guardian_unit']: unit(cfg['guardian_unit'], guardian, 'JevOps agent supervisor watchdog and guardian'),
             cfg['repair_unit']: unit(cfg['repair_unit'], repair, 'JevOps bounded supervisor stall repair dispatcher')}
    require((root / 'tools/reload_supervisor_when_idle.py').is_file(), 'Reviewed idle reloader missing')
    reload_argv = [python, '-B', str(root / 'tools/reload_supervisor_when_idle.py'),
                   '--repo-root', str(root), '--timeout', '1800']
    # A maintenance worker queues this separate oneshot and exits. It is not
    # a third automatic supervision loop and is never enabled or auto-started.
    units[RELOAD_UNIT] = '\n'.join([
        '# Managed by JevOps tools/manage_supervisor_watchdog.py', '[Unit]',
        'Description=Reload the JevOps repair dispatcher only after its worker exits', '', '[Service]',
        'Type=oneshot', 'WorkingDirectory=' + systemd_path(root),
        'Environment=' + systemd_arg('PYTHONPATH=' + source), 'Environment=PYTHONDONTWRITEBYTECODE=1',
        'Environment=PYTHONUNBUFFERED=1',
        'ExecStart=' + ' '.join(systemd_arg(arg, exec_start=True) for arg in reload_argv),
        'Restart=no', 'SuccessExitStatus=75', 'TimeoutStartSec=1810s', 'KillMode=control-group',
        'MemoryMax=512M', 'TasksMax=32', 'CPUQuota=100%', 'UMask=0077',
        'StandardOutput=journal', 'StandardError=journal', 'SyslogIdentifier=jevops-idle-reload',
        'LogRateLimitIntervalSec=30s', 'LogRateLimitBurst=50', ''])
    return cfg, supervisor, units


def guardian_identity(pid, root, manifest, python, *, proc_root=Path('/proc')):
    directory = proc_root / str(pid)
    try:
        require(directory.stat().st_uid == os.getuid(), 'Guardian UID differs')
        raw = (directory / 'cmdline').read_bytes()
        argv = [part.decode() for part in raw.split(b'\0') if part]
        require(argv[1:3] == ['-m', GUARDIAN], 'Not the native guardian module')
        fields = {}; index = 3
        while index < len(argv):
            key = argv[index]
            require(key not in fields, 'Duplicate guardian option')
            if key == '--apply': fields[key] = True; index += 1
            else:
                require(key in {'--manifest-path', '--repo-root', '--python', '--poll-seconds', '--restart-cooldown'}
                        and index + 1 < len(argv), 'Unexpected guardian options')
                fields[key] = argv[index + 1]; index += 2
        require(Path(fields['--manifest-path']).is_absolute() and Path(fields['--repo-root']).is_absolute(),
                'Guardian scope must use absolute paths')
        require(fields.get('--apply') is True and Path(fields['--manifest-path']).resolve() == manifest.resolve()
                and Path(fields['--repo-root']).resolve() == root.resolve(), 'Guardian scope differs')
        require((directory / 'exe').resolve() == Path(python).resolve(), 'Guardian executable differs')
        require((directory / 'cwd').resolve() == root.resolve(), 'Guardian cwd differs')
        text = (directory / 'stat').read_text(); tail = text[text.rfind(')') + 2:].split()
        require(tail[0] != 'Z', 'Guardian is a zombie')
        return {'pid': pid, 'uid': os.getuid(), 'start_ticks': tail[19], 'argv': argv}
    except (OSError, ValueError, KeyError, IndexError, UnicodeError):
        return None


def migrate_guardian(root, cfg, supervisor):
    manifest = root / cfg['runtime_manifest']
    matches = []
    for item in Path('/proc').iterdir():
        if item.name.isdecimal():
            found = guardian_identity(int(item.name), root, manifest, supervisor['python_executable'])
            if found: matches.append(found)
    require(len(matches) <= 1, 'Duplicate guardians: refuse lifecycle mutation')
    if not matches: return {'migrated_pid': None, 'watchdog_signaled': False}
    identity = matches[0]; pid = identity['pid']
    require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'pidfd required for exact guardian migration')
    fd = os.pidfd_open(pid)
    try:
        require(guardian_identity(pid, root, manifest, supervisor['python_executable']) == identity,
                'Guardian identity changed before migration')
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if guardian_identity(pid, root, manifest, supervisor['python_executable']) is None: break
            time.sleep(.1)
        else: raise ValueError('Old guardian did not exit within the bounded migration deadline')
    finally:
        os.close(fd)
    lock_path = manifest.parent / 'watchdog-guardian.lock'
    with lock_path.open('a+') as handle:
        # /proc identity can disappear just before the kernel releases the
        # exiting process's file locks. Wait for that final handoff as well.
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, 'Old guardian ownership lock did not close before migration deadline')
                time.sleep(.1)
    return {'migrated_pid': pid, 'identity': identity, 'watchdog_signaled': False}


def _install_locked(root):
    cfg, supervisor, units = render(root)
    require_native_service_watchdog(supervisor['accelerator_source'])
    require_native_provider_budget_policy(supervisor['accelerator_source'])
    require_native_lane_environment_guard(supervisor['accelerator_source'])
    require_native_worker_storage_admission(supervisor['accelerator_source'])
    state = root / cfg['state_root']; state.mkdir(parents=True, exist_ok=True)
    command([supervisor['python_executable'], str(root / 'tools/check_lean_refactor_plan.py'), '--check-all'])
    registered = read_json(root / cfg['lane_manifest']).get('execution_profile')
    if registered:
        require(registered == 'config/lean_refactor_arena_20261024_execution_v2.json',
                'Unknown research execution profile')
        command([supervisor['python_executable'], str(root / 'tools/lean_refactor_execution_v2.py')],
                timeout=PROTECTED_PREFLIGHT_TIMEOUT_SECONDS)
    command(['systemctl', '--user', 'show-environment'])  # Never print its environment.
    manifest = root / cfg['runtime_manifest']
    # Only the lane manifest is refreshed; completed task/model contracts retain
    # their separate supervisor profile and source identities.
    atomic(manifest, (root / cfg['lane_manifest']).read_text())
    staged = state / 'rendered'; staged.mkdir(exist_ok=True)
    for name, text in units.items(): atomic(staged / name, text, 0o644)
    verified = command(['systemd-analyze', '--user', 'verify', *[str(staged / name) for name in units]])
    user_units = Path.home() / '.config/systemd/user'; user_units.mkdir(parents=True, exist_ok=True)
    for name, text in units.items():
        destination = user_units / name
        if destination.exists():
            require(not destination.is_symlink() and destination.stat().st_uid == os.getuid(), 'Unexpected unit owner/type')
            old_bytes = destination.read_bytes()
            old = old_bytes.decode('utf-8')
            reviewed_static_reload = (name == RELOAD_UNIT and
                hashlib.sha256(old_bytes).hexdigest() == LEGACY_RELOAD_UNIT_SHA256)
            require(old.startswith('# Managed by JevOps tools/manage_supervisor_watchdog.py')
                    or reviewed_static_reload, 'Refuse replacing an unmanaged unit')
            if old != text:
                backup = state / 'unit-backups' / (name + '.' + hashlib.sha256(old.encode()).hexdigest())
                if not backup.exists(): atomic(backup, old)
        atomic(destination, text, 0o644)
    command(['systemctl', '--user', 'daemon-reload'])
    daemon_units = [cfg['guardian_unit'], cfg['repair_unit']]
    command(['systemctl', '--user', 'enable', *daemon_units])
    active = command(['systemctl', '--user', 'is-active', cfg['guardian_unit']], allowed=(0, 3, 4))
    migration = {'already_managed': True, 'watchdog_signaled': False}
    if active.returncode != 0: migration = migrate_guardian(root, cfg, supervisor)
    command(['systemctl', '--user', 'start', *daemon_units])
    report = {'schema': 'jevops.persistent-watchdog-installation.v1', 'installed_at': time.time(),
              'units': list(units), 'manual_units_not_enabled_or_started': [RELOAD_UNIT],
              'migration': migration, 'systemd_verification_stderr': verified.stderr,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'task_states_changed': False, 'planned_work_activated': False, 'provider_calls': 0}
    save(state / 'installation.json', report)
    return report


def install(root):
    cfg, _ = profile(root)
    state = root / cfg['state_root']; state.mkdir(parents=True, exist_ok=True)
    require(not state.is_symlink() and state.stat().st_uid == os.getuid(), 'Expected owned setup state directory')
    descriptor = os.open(state / 'install.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, 'a+') as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
                'Expected owned ordinary setup lock')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _install_locked(root)



# This inspection never grants controller, worker, or completion authority.
_STATUS_PROC_ROOT = Path('/proc')


def _status_actor(pid, role, root, manifest, cfg, supervisor):
    from ipfs_accelerate_py.agent_supervisor.rescue.watchdog_guardian import _python_entrypoint
    try:
        require(type(pid) is int and pid > 0, 'No current service owner')
        directory = _STATUS_PROC_ROOT / str(pid)
        require(directory.stat().st_uid == os.getuid(), 'Foreign service owner')
        raw = (directory / 'cmdline').read_bytes()
        argv = raw.rstrip(b'\0').decode().split('\0')
        mode, entry, index = _python_entrypoint(argv)
        require(mode == 'module' and entry == role and argv[index] == '-m'
                and all(v in {'-B', '-u', '-E', '-s', '-S', '-I', '-O', '-OO'} for v in argv[1:index]),
                'Different service entrypoint')
        require((directory / 'exe').resolve() == Path(supervisor['python_executable']).resolve()
                and (directory / 'cwd').resolve() == root.resolve(), 'Different executable or repository')
        args = argv[index + 2:]
        require(args.count('--apply') == 1 and '--once' not in args, 'Not a persistent applying service')
        def option(name):
            values = [args[i + 1] if i + 1 < len(args) else None for i, v in enumerate(args) if v == name]
            values += [v[len(name) + 1:] for v in args if v.startswith(name + '=')]
            require(len(values) == 1 and values[0] is not None and Path(values[0]).is_absolute(), 'Ambiguous service scope')
            return Path(values[0]).resolve()
        require(option('--manifest-path') == manifest.resolve() and option('--repo-root') == root.resolve(),
                'Different service scope')
        if role == DISPATCHER:
            require(option('--state-dir') == (root / cfg['state_root'] / 'repair-dispatcher').resolve()
                    and option('--repair-lock-path') == (root / cfg['state_root'] / 'fixer.lock').resolve(),
                    'Different repair custody')
        fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
        require(fields[0] not in {'Z', 'X', 'x'}, 'Exited service owner')
        ticks = int(fields[19])
        uptime = float((_STATUS_PROC_ROOT / 'uptime').read_text().split()[0])
        born = time.time() - uptime + ticks / os.sysconf('SC_CLK_TCK')
        require(math.isfinite(born), 'Invalid process birth')
        require((directory / 'cmdline').read_bytes() == raw
                and (directory / 'stat').read_text().rsplit(')', 1)[1].split()[19] == str(ticks),
                'Service identity changed')
        return {'pid': pid, 'start_ticks': ticks, 'command_sha256': hashlib.sha256(raw).hexdigest(),
                'born_at': born}
    except (OSError, ValueError, IndexError, KeyError, UnicodeError):
        return None


def _status_observation(path, role, unit, root, manifest, cfg, supervisor):
    from ipfs_accelerate_py.agent_supervisor.rescue.storage_pressure import read_emergency_status
    primary = read_json(path) if path.exists() else None
    try:
        pid = int(unit.get('MainPID', '0')) if unit.get('ActiveState') == 'active' else 0
    except (TypeError, ValueError):
        pid = 0
    actor = _status_actor(pid, role, root, manifest, cfg, supervisor)
    emergency = None
    def same_actor(candidate):
        current = _status_actor(candidate, role, root, manifest, cfg, supervisor)
        return current is not None and all(current[key] == actor[key] for key in ('pid', 'start_ticks', 'command_sha256'))
    if actor:
        emergency = read_emergency_status(path, expected_pid=pid,
            identity_check=same_actor)
    current = False
    stamp = None
    if actor and isinstance(primary, dict):
        if role == DISPATCHER:
            bound = primary.get('control_pid') == pid and primary.get('control_start_ticks') == actor['start_ticks']
            stamp = primary.get('control_heartbeat_at')
        else:
            bound = (primary.get('guardian_pid') == pid and primary.get('manifest_path') == str(manifest.resolve())
                     and primary.get('repo_root') == str(root.resolve()))
            value = primary.get('observed_at_ms')
            try:
                stamp = value / 1000 if type(value) in (int, float) else None
            except OverflowError:
                stamp = None
        try:
            stamp = float(stamp) if type(stamp) in (int, float) else None
        except OverflowError:
            stamp = None
        current = (bound and type(stamp) in (int, float) and math.isfinite(stamp)
                   and actor['born_at'] - 5 <= stamp <= time.time() + 5)
    # A lingering emergency record must never override newer durable recovery.
    use_emergency = emergency is not None and (not current or emergency['observed_at_ms'] / 1000 > stamp)
    value = emergency['payload'] if use_emergency else primary
    selected_stamp = emergency['observed_at_ms'] / 1000 if use_emergency else stamp
    age = time.time() - selected_stamp if type(selected_stamp) in (int, float) and math.isfinite(selected_stamp) else None
    return value, {'source': 'authenticated_emergency' if use_emergency else 'disk_snapshot',
                   'current_service_identity_verified': bool(actor),
                   'current_owner_observation': bool(use_emergency or current),
                   'owner_binding_basis': ('native_emergency_pid_start_ticks_command_sha256' if use_emergency
                       else 'primary_pid_start_ticks' if current and role == DISPATCHER
                       else 'primary_pid_scope_and_boot_time_estimate' if current else 'unverified_disk_snapshot'),
                   'observed_at': selected_stamp, 'age_seconds': age,
                   'fresh': bool((use_emergency or current) and age is not None and -5 <= age <= 120),
                   'completion_authority': False}


def status(root):
    cfg, supervisor = profile(root); manifest = root / cfg['runtime_manifest']
    sys.path.insert(0, supervisor['accelerator_source'])
    from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
    rows = parse_todo_blocks((root / read_json(manifest)['todo_path']).read_text(), task_header_prefix='## JLR-')
    completed = [r[0] for r in rows if r[3].get('status') in {'completed', 'done'}]
    planned = [r[0] for r in rows if r[3].get('status') == 'planned']
    completed_set = set(completed)
    pending = [r[0] for r in rows if r[3].get('status') in {'pending', 'todo', 'ready', 'failed', 'blocked', 'in_progress'}]
    ready = [r[0] for r in rows if r[0] in pending and all(d.strip() in completed_set for d in str(r[3].get('depends_on', '')).split(',') if d.strip())]
    units = {}
    for name in [cfg['guardian_unit'], cfg['repair_unit'], RELOAD_UNIT]:
        result = command(['systemctl', '--user', 'show', name, '--property=ActiveState,SubState,MainPID,UnitFileState,KillMode,FragmentPath'], allowed=(0, 1))
        units[name] = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    guardian, guardian_observation = _status_observation(
        manifest.parent / 'watchdog-guardian-status.json', GUARDIAN, units[cfg['guardian_unit']], root, manifest, cfg, supervisor)
    repair, repair_observation = _status_observation(
        root / cfg['state_root'] / 'repair-dispatcher/status.json', DISPATCHER, units[cfg['repair_unit']], root, manifest, cfg, supervisor)
    report = {'schema': 'jevops.persistent-watchdog-status.v1', 'observed_at': time.time(),
              'work_state': 'unfinished_planned_work' if not pending and planned and cfg.get('materialize_planned_work') else 'planned_backlog_not_activated' if not pending and planned else 'eligible_work' if ready else 'dependency_wait' if pending else 'complete',
              'completed_tasks': completed, 'planned_tasks': planned, 'pending_tasks': pending, 'ready_tasks': ready,
              'units': units, 'campaign_budget': read_json(manifest.parent / 'router-budget.json'),
              'guardian': guardian, 'repair': repair,
              'observations': {'guardian': guardian_observation, 'repair': repair_observation},
              'completion_authority': False, 'full_campaign_complete': False}
    report['storage_wait'] = any(isinstance(value, dict) and value.get('storage_pressure') is True
                                 and observation['fresh']
                                 for value, observation in ((guardian, guardian_observation), (repair, repair_observation)))
    ledger = root / cfg['state_root'] / 'repair-dispatcher/state.json'
    if ledger.exists():
        active = read_json(ledger).get('active_worker')
        if isinstance(active, dict) and active.get('pid'):
            from ipfs_accelerate_py.agent_supervisor.rescue.repair_dispatcher import probe_process
            observed = probe_process(int(active['pid']))
            verified = observed.get('alive') is True and observed.get('start_ticks') == active.get('start_ticks')
            report['maintenance_worker'] = {'pid': active['pid'], 'identity_verified': verified,
                                             'deadline': active.get('deadline')}
            if verified:
                report['work_state'] = 'materialization_or_repair_running'
    # A disk action is an observation; only a matching live worker birth is running.
    if isinstance(report['repair'], dict) and report['repair'].get('action') == 'worker_running':
        if not report.get('maintenance_worker', {}).get('identity_verified'):
            report['repair'] = {**report['repair'], 'reported_action': 'worker_running',
                                'action': 'unverified_worker_snapshot'}
    if report['storage_wait']:
        report['work_state'] = 'storage_wait'
    destination = root / cfg['state_root'] / 'status.json'
    report['status_snapshot_persisted'] = True
    try:
        save(destination, report)
    except OSError as error:
        from ipfs_accelerate_py.agent_supervisor.rescue.storage_pressure import is_storage_pressure
        if not is_storage_pressure(error):
            raise
        report['status_snapshot_persisted'] = False
        report['persistence_error'] = {'errno': error.errno, 'path': str(destination), 'message': str(error)}
        report['storage_wait'] = True
        report['work_state'] = 'storage_wait'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args(argv); root = args.repo_root.resolve()
    try:
        if args.install: report = install(root)
        elif args.render:
            cfg, _, units = render(root); directory = root / cfg['state_root'] / 'rendered'
            for name, text in units.items(): atomic(directory / name, text, 0o644)
            report = {'rendered': [str(directory / name) for name in units], 'units_started': False}
        else: report = status(root)
        print(json.dumps(report, sort_keys=True)); return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
