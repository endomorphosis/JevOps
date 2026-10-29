"""Private real-file/native emergency parser fixtures; no service or process jobs."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

SOURCE = Path('/home/barberb/lift_coding/external/ipfs_accelerate')
sys.path.insert(0, str(SOURCE))
from ipfs_accelerate_py.agent_supervisor.rescue import storage_pressure as storage
from ipfs_accelerate_py.agent_supervisor.rescue import repair_dispatcher as dispatcher

TARGET = Path(os.environ.get('MANAGER_UNDER_TEST', str(Path(__file__).parents[1] / 'tools/manage_supervisor_watchdog.py')))
spec = importlib.util.spec_from_file_location('manager_under_test', TARGET)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class WholePhaseDeadline(BaseException):
    pass


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / 'private campaign'
    root.mkdir()
    proc = tmp_path / 'private proc'
    proc.mkdir()
    (proc / 'uptime').write_text('1000.0 0\n')
    manifest = root / 'runtime/manifest.json'
    cfg = {'runtime_manifest': 'runtime/manifest.json', 'state_root': 'persistent-watchdog',
           'guardian_unit': 'private-guardian.service', 'repair_unit': 'private-repair.service'}
    supervisor = {'accelerator_source': str(SOURCE), 'python_executable': sys.executable}
    write(manifest, {'todo_path': 'board.md'})
    (root / 'board.md').write_text('## JLR-PRIVATE\n\nstatus: planned\n')
    write(manifest.parent / 'router-budget.json', {'new_calls_allowed': False, 'calls': 7})
    state = root / cfg['state_root'] / 'repair-dispatcher'
    write(state / 'state.json', {'active_worker': {'pid': 999, 'start_ticks': 77, 'deadline': 123},
                                'attempt_count': 2, 'incident_count': 4})
    now = time.time()
    ticks = 900 * os.sysconf('SC_CLK_TCK')
    roles = {'guardian': (101, manager.GUARDIAN, manifest.parent / 'watchdog-guardian-status.json'),
             'repair': (102, manager.DISPATCHER, state / 'status.json')}
    for name, (pid, module, path) in roles.items():
        directory = proc / str(pid)
        directory.mkdir()
        argv = [sys.executable, '-B', '-m', module, '--manifest-path', str(manifest),
                '--repo-root', str(root), '--apply']
        if name == 'repair':
            argv += ['--state-dir', str(state), '--repair-lock-path', str(root / cfg['state_root'] / 'fixer.lock')]
        (directory / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in argv) + b'\0')
        (directory / 'stat').write_text(f'{pid} (private fixture) ' + ' '.join(['S'] + ['0'] * 18 + [str(ticks)] + ['0'] * 5))
        (directory / 'exe').symlink_to(Path(sys.executable).resolve())
        (directory / 'cwd').symlink_to(root)
        primary = {'action': 'observing', 'work_complete': False, 'completion_authority': False}
        if name == 'guardian':
            primary.update(guardian_pid=pid, observed_at_ms=int((now - 10) * 1000),
                           manifest_path=str(manifest), repo_root=str(root), apply_enabled=True)
        else:
            primary.update(control_pid=pid, control_start_ticks=ticks, control_heartbeat_at=now - 10,
                           action='worker_running', apply=True)
        write(path, primary)
    runtime = tmp_path / 'private emergency'
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(storage, '_runtime_directory', lambda: runtime)
    def process_identity(pid):
        directory = proc / str(pid)
        if not directory.exists():
            return None
        return os.getuid(), (directory / 'stat').read_text().rsplit(')', 1)[1].split()[19], hashlib.sha256((directory / 'cmdline').read_bytes()).hexdigest()
    monkeypatch.setattr(storage, '_process_identity', process_identity)
    monkeypatch.setattr(manager, '_STATUS_PROC_ROOT', proc, raising=False)
    monkeypatch.setattr(manager, 'profile', lambda ignored: (cfg, supervisor))
    units = {cfg['guardian_unit']: 101, cfg['repair_unit']: 102, manager.RELOAD_UNIT: 0}
    def command(argv, **kwargs):
        assert argv[:3] == ['systemctl', '--user', 'show']
        pid = units[argv[3]]
        return SimpleNamespace(stdout=f'ActiveState={"active" if pid else "inactive"}\nMainPID={pid}\n', stderr='', returncode=0)
    monkeypatch.setattr(manager, 'command', command)
    monkeypatch.setattr(dispatcher, 'probe_process', lambda pid: {'alive': False, 'start_ticks': None})
    def emergency(role='repair', stamp=None, **changes):
        pid, module, primary = roles[role]
        identity = process_identity(pid)
        record = {'schema': storage._SCHEMA, 'canonical_path': str(primary.resolve()),
                  'pid': pid, 'uid': identity[0], 'start_ticks': identity[1], 'command_sha256': identity[2],
                  'observed_at_ms': int((now - 2 if stamp is None else stamp) * 1000), 'errno': errno.ENOSPC,
                  'work_complete': False, 'completion_authority': False,
                  'payload': {'action': 'storage_wait', 'state': 'degraded', 'storage_pressure': True,
                              'work_complete': False, 'completion_authority': False, 'active_worker': None}}
        record.update(changes)
        write(storage._emergency_path(primary), record)
        return record
    before = {str(p): p.read_bytes() for p in (manifest, root / 'board.md', state / 'state.json', manifest.parent / 'router-budget.json')}
    return SimpleNamespace(root=root, proc=proc, roles=roles, now=now, ticks=ticks, cfg=cfg,
                           state=state, emergency=emergency, before=before, units=units)


def assert_unchanged(f):
    assert all(Path(p).read_bytes() == content for p, content in f.before.items())


def test_authenticated_emergency_replaces_stale_disk_and_dead_worker(fixture):
    f = fixture
    f.emergency()
    result = manager.status(f.root)
    assert result['repair']['action'] == 'storage_wait'
    assert result['observations']['repair']['source'] == 'authenticated_emergency'
    assert result['maintenance_worker']['identity_verified'] is False
    assert result['storage_wait'] is True and result['work_state'] == 'storage_wait'
    assert result['completion_authority'] is False and result['full_campaign_complete'] is False
    assert_unchanged(f)


@pytest.mark.parametrize('code', [errno.ENOSPC, errno.EDQUOT])
def test_optional_snapshot_pressure_returns_inspectable_report(fixture, monkeypatch, code):
    f = fixture
    f.emergency()
    error = OSError(code, 'private injected storage pressure')
    monkeypatch.setattr(manager, 'save', lambda *args: (_ for _ in ()).throw(error))
    result = manager.status(f.root)
    assert result['status_snapshot_persisted'] is False
    assert result['persistence_error']['errno'] == code
    assert result['repair']['action'] == 'storage_wait' and result['storage_wait'] is True
    assert result['schema'] == 'jevops.persistent-watchdog-status.v1'
    assert_unchanged(f)


@pytest.mark.parametrize('error', [OSError(errno.EIO, 'I/O'), PermissionError(errno.EACCES, 'permission'),
                                  KeyboardInterrupt('control'), SystemExit(17), WholePhaseDeadline('phase')])
def test_other_snapshot_failures_and_original_controls_propagate(fixture, monkeypatch, error):
    monkeypatch.setattr(manager, 'save', lambda *args: (_ for _ in ()).throw(error))
    with pytest.raises(type(error)) as caught:
        manager.status(fixture.root)
    assert caught.value is error
    assert_unchanged(fixture)


@pytest.mark.parametrize('role', ['repair', 'guardian'])
def test_newer_primary_beats_lingering_emergency(fixture, role):
    f = fixture
    f.emergency(role)
    path = f.roles[role][2]
    primary = json.loads(path.read_text())
    primary['action'] = 'durable_recovered'
    primary['control_heartbeat_at' if role == 'repair' else 'observed_at_ms'] = f.now if role == 'repair' else int(f.now * 1000)
    write(path, primary)
    result = manager.status(f.root)
    assert result[role]['action'] == 'durable_recovered'
    assert result['observations'][role]['source'] == 'disk_snapshot'
    assert result['storage_wait'] is False


@pytest.mark.parametrize('changes', [{'pid': 777}, {'uid': -1}, {'start_ticks': 'wrong'},
    {'command_sha256': '0' * 64}, {'canonical_path': '/private/wrong'},
    {'observed_at_ms': 1}, {'observed_at_ms': 10 ** 15}])
def test_unauthenticated_or_stale_emergency_never_overrides(fixture, changes):
    f = fixture
    f.emergency(**changes)
    result = manager.status(f.root)
    assert result['observations']['repair']['source'] == 'disk_snapshot'
    assert result['repair']['action'] == 'unverified_worker_snapshot'
    assert result['repair']['reported_action'] == 'worker_running'
    assert result['storage_wait'] is False
    assert_unchanged(f)


@pytest.mark.parametrize('mutation', ['script', 'command', 'data_module', 'module', 'cwd', 'exe',
    'manifest', 'root', 'state', 'lock', 'no_apply', 'once', 'birth', 'mainpid', 'inactive'])
def test_emergency_requires_current_exact_service_role(fixture, mutation):
    f = fixture
    directory = f.proc / '102'
    argv = (directory / 'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    mapping = {'manifest': '--manifest-path', 'root': '--repo-root', 'state': '--state-dir', 'lock': '--repair-lock-path'}
    if mutation in mapping:
        argv[argv.index(mapping[mutation]) + 1] = '/private/wrong'
    elif mutation == 'script':
        argv = [sys.executable, '/private/script.py', *argv[2:]]
    elif mutation == 'command':
        argv = [sys.executable, '-c', 'pass', *argv[2:]]
    elif mutation == 'data_module':
        argv = [sys.executable, '/private/script.py', '--data', '-m', manager.DISPATCHER, *argv[4:]]
    elif mutation == 'module':
        argv[3] = 'unrelated.module'
    elif mutation == 'no_apply':
        argv.remove('--apply')
    elif mutation == 'once':
        argv.append('--once')
    elif mutation == 'cwd':
        (directory / 'cwd').unlink()
        (directory / 'cwd').symlink_to(f.proc)
    elif mutation == 'exe':
        alternate = f.proc / 'other-python'
        alternate.write_text('not executed')
        (directory / 'exe').unlink()
        (directory / 'exe').symlink_to(alternate)
    elif mutation == 'mainpid':
        f.units[f.cfg['repair_unit']] = 909
    elif mutation == 'inactive':
        f.units[f.cfg['repair_unit']] = 0
    (directory / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in argv) + b'\0')
    f.emergency()  # Correctly authenticates the mutated process; role gate must still reject it.
    if mutation == 'birth':
        stat_path = directory / 'stat'
        stat_path.write_text(stat_path.read_text().replace(str(f.ticks), str(f.ticks + 1)))
    result = manager.status(f.root)
    assert result['observations']['repair']['source'] == 'disk_snapshot'
    assert result['storage_wait'] is False
    assert_unchanged(f)


def test_valid_guardian_emergency_is_observed(fixture):
    fixture.emergency('guardian')
    result = manager.status(fixture.root)
    assert result['guardian']['action'] == 'storage_wait'
    assert result['observations']['guardian']['source'] == 'authenticated_emergency'


def test_live_worker_requires_matching_kernel_birth(fixture, monkeypatch):
    monkeypatch.setattr(dispatcher, 'probe_process', lambda pid: {'alive': True, 'start_ticks': 77})
    result = manager.status(fixture.root)
    assert result['maintenance_worker']['identity_verified'] is True
    assert result['work_state'] == 'materialization_or_repair_running'
    assert result['repair']['action'] == 'worker_running'
    assert_unchanged(fixture)


def test_successful_snapshot_preserves_status_schema(fixture):
    result = manager.status(fixture.root)
    assert result['status_snapshot_persisted'] is True
    assert json.loads((fixture.root / fixture.cfg['state_root'] / 'status.json').read_text()) == result
    assert result['schema'] == 'jevops.persistent-watchdog-status.v1'
    assert_unchanged(fixture)


@pytest.mark.parametrize('state', ['Z', 'X', 'x'])
def test_dead_service_state_cannot_authorize_emergency(fixture, state):
    f = fixture
    path = f.proc / '102/stat'
    path.write_text(path.read_text().replace(') S ', ') ' + state + ' '))
    f.emergency()
    result = manager.status(f.root)
    assert result['observations']['repair']['source'] == 'disk_snapshot'
    assert result['observations']['repair']['current_service_identity_verified'] is False
    assert result['storage_wait'] is False
    assert_unchanged(f)


@pytest.mark.parametrize('name', ['--manifest-path', '--repo-root', '--state-dir', '--repair-lock-path'])
def test_dangling_duplicate_scope_flag_cannot_authorize_emergency(fixture, name):
    f = fixture
    path = f.proc / '102/cmdline'
    path.write_bytes(path.read_bytes() + name.encode() + b'\0')
    f.emergency()
    result = manager.status(f.root)
    assert result['observations']['repair']['source'] == 'disk_snapshot'
    assert result['observations']['repair']['current_service_identity_verified'] is False
    assert result['storage_wait'] is False
    assert_unchanged(f)


def test_primary_binding_basis_is_explicit_for_each_role(fixture):
    result = manager.status(fixture.root)
    assert result['observations']['repair']['owner_binding_basis'] == 'primary_pid_start_ticks'
    assert result['observations']['guardian']['owner_binding_basis'] == 'primary_pid_scope_and_boot_time_estimate'
