"""Native presence locks and owned process fixtures; no user services restart."""
import copy
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('idle_reload_test_subject', ROOT / 'tools/reload_supervisor_when_idle.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path / 'campaign'; (root / 'config').mkdir(parents=True)
    cfg = json.loads((ROOT / m.CONFIG).read_text())
    supervisor = json.loads((ROOT / cfg['supervisor_profile']).read_text())
    for relative, value in [(m.CONFIG, cfg), (cfg['supervisor_profile'], supervisor)]:
        (root / relative).write_text(json.dumps(value))
    manifest = root / cfg['runtime_manifest']; manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'lanes': [{'state_dir': 'data/lane', 'state_prefix': 'private'}]}))
    binding = m.scope(root)
    state_path = binding['native_cfg'].state_dir / 'state.json'; state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({'schema': binding['native'].SCHEMA,
        'attempts': {'immutable-existing-contract': {'count': 2}}, 'last_worker': {'outcome': 'actual_previous_failure'}}))
    board = root / 'private-board.todo'; board.write_text('## Existing history\n- Status: completed\n')
    return root, binding, state_path, board


@pytest.fixture
def worker():
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        yield process
    finally:
        if process.poll() is None: process.terminate()
        process.wait(timeout=3)


def set_worker(binding, path, process, **changes):
    actual = binding['native'].probe_process(process.pid)
    state = json.loads(path.read_text())
    state['active_worker'] = {**actual, 'owned_session': True, **changes}
    path.write_text(json.dumps(state))


def snapshots():
    return [{'properties': {'ActiveState': 'active'}, 'identity': {'pid': 41, 'start_ticks': 1}},
            {'properties': {'ActiveState': 'active'}, 'identity': {'pid': 42, 'start_ticks': 2}}]


def publish_fresh_status(binding):
    path = binding['native_cfg'].state_dir / 'status.json'
    path.write_text(json.dumps({'schema': binding['native'].SCHEMA, 'observed_at': time.time(),
                               'action': 'repair_already_running'}))


def replacement_snapshots(binding):
    values = snapshots(); observations = []
    def inspect(*args, **kwargs):
        if observations:
            # This callback happens after the restart command has returned.
            publish_fresh_status(binding)
        observations.append(1)
        return values[0] if len(observations) == 1 else values[1]
    return inspect


def test_real_native_presence_prevents_restart_and_is_not_removed(campaign):
    root, binding, _, _ = campaign
    run = Mock(side_effect=AssertionError('must not call systemd while another presence is held'))
    path = binding['native_cfg'].repair_lock_path
    with binding['native'].repair_lock(path):
        before = path.read_bytes(); inode = path.stat().st_ino
        result, code = m.reload_when_idle(root, once=True, run=run)
        assert code == 75 and result['last_observation']['reason'] == 'native_repair_presence_held'
        assert path.read_bytes() == before and path.stat().st_ino == inode
    run.assert_not_called()
    assert not path.exists()


def test_actual_live_session_worker_defers_without_any_signal(campaign, worker):
    root, binding, state, board = campaign
    set_worker(binding, state, worker)
    before = state.read_bytes(), board.read_bytes()
    run = Mock(side_effect=AssertionError('active worker must survive'))
    result, code = m.reload_when_idle(root, once=True, run=run)
    assert code == 75 and result['last_observation']['reason'] == 'repair_worker_active'
    assert worker.poll() is None and (state.read_bytes(), board.read_bytes()) == before
    assert result['worker_signals_sent'] is False
    run.assert_not_called()


def test_recycled_or_nonowned_session_worker_identity_is_uncertain_not_idle(campaign, worker):
    root, binding, state, _ = campaign
    set_worker(binding, state, worker, start_ticks=-1)
    result, code = m.reload_when_idle(root, once=True, run=Mock())
    assert code == 75 and result['last_observation']['reason'] == 'worker_identity_uncertain'
    assert worker.poll() is None


@pytest.mark.parametrize('protection', ['spawn_intent', 'lane_hold', 'dispatcher_hold', 'operator_stop'])
def test_uncertain_spawn_and_all_holds_defer_without_state_edits(campaign, protection):
    root, binding, state, board = campaign
    if protection == 'spawn_intent':
        value = json.loads(state.read_text()); value['spawn_intent'] = {'signature': 'uncertain-real-spawn'}
        state.write_text(json.dumps(value))
    else:
        marker = {'lane_hold': root/'data/lane/operator.hold',
                  'dispatcher_hold': binding['native_cfg'].manifest_path.parent/'repair-dispatcher.hold',
                  'operator_stop': root/'OPERATOR_STOP'}[protection]
        marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text('owned hold')
    before = state.read_bytes(), board.read_bytes()
    run = Mock(side_effect=AssertionError('protected worker scope cannot restart'))
    result, code = m.reload_when_idle(root, once=True, run=run)
    assert code == 75 and not result['reloaded']
    assert (state.read_bytes(), board.read_bytes()) == before
    run.assert_not_called()


def test_idle_restart_uses_only_registered_unit_under_native_fence(campaign, monkeypatch):
    root, binding, state, board = campaign
    before = state.read_bytes(), board.read_bytes()
    monkeypatch.setattr(m, 'service_snapshot', replacement_snapshots(binding))
    observed = []
    def restart(argv, timeout):
        assert argv == ['systemctl', '--user', 'restart', m.UNIT]
        assert 0 < timeout <= 30
        with pytest.raises(binding['native'].AlreadyRunning):
            with binding['native'].repair_lock(binding['native_cfg'].repair_lock_path): pass
        observed.append(argv)
        return SimpleNamespace(stdout='')
    result, code = m.reload_when_idle(root, once=True, run=restart)
    assert code == 0 and result['reloaded'] and len(observed) == 1
    assert not binding['native_cfg'].repair_lock_path.exists()
    assert (state.read_bytes(), board.read_bytes()) == before
    assert result['completion_authority'] is False and result['worker_signals_sent'] is False


def test_worker_appearing_during_service_inspection_is_rechecked(campaign, worker, monkeypatch):
    root, binding, state, _ = campaign
    def inspect(*args, **kwargs):
        set_worker(binding, state, worker)
        return snapshots()[0]
    monkeypatch.setattr(m, 'service_snapshot', inspect)
    run = Mock(side_effect=AssertionError('late actual worker cannot restart'))
    result, code = m.reload_when_idle(root, once=True, run=run)
    assert code == 75 and result['last_observation']['reason'] == 'repair_worker_active'
    run.assert_not_called(); assert worker.poll() is None


def test_queued_reload_waits_for_real_native_presence_release(campaign, monkeypatch):
    root, binding, state, _ = campaign
    monkeypatch.setattr(m, 'service_snapshot', replacement_snapshots(binding))
    result = []; run = Mock(return_value=SimpleNamespace(stdout=''))
    blocked = threading.Event()
    actual_lock = binding['native'].repair_lock
    @contextmanager
    def observe_contention(path):
        try:
            with actual_lock(path): yield
        except binding['native'].AlreadyRunning:
            blocked.set()
            raise
    with actual_lock(binding['native_cfg'].repair_lock_path):
        monkeypatch.setattr(binding['native'], 'repair_lock', observe_contention)
        thread = threading.Thread(target=lambda: result.append(m.reload_when_idle(root, timeout=5, run=run)))
        thread.start(); assert blocked.wait(2)
        # Actual owner marker remains held, so no subprocess call is possible.
        assert not run.called
    thread.join(timeout=6)
    assert not thread.is_alive() and result[0][1] == 0
    run.assert_called_once()


def test_foreign_presence_change_immediately_before_restart_is_refused(campaign, monkeypatch):
    root, binding, _, _ = campaign
    path = binding['native_cfg'].repair_lock_path
    foreign = {'schema': binding['native'].SCHEMA, 'pid': os.getpid(),
               'start_ticks': binding['native'].probe_process(os.getpid())['start_ticks'], 'token': 'foreign-token'}
    def inspect(*args, **kwargs):
        path.unlink(); path.write_text(json.dumps(foreign))
        return snapshots()[0]
    monkeypatch.setattr(m, 'service_snapshot', inspect)
    run = Mock()
    with pytest.raises(RuntimeError, match='presence changed'):
        m.reload_when_idle(root, once=True, run=run)
    run.assert_not_called()
    assert json.loads(path.read_text()) == foreign


def test_unreadable_existing_worker_is_uncertain_not_a_dead_worker(campaign, monkeypatch):
    root, binding, state, _ = campaign
    value = json.loads(state.read_text()); value['active_worker'] = {'pid': 999999, 'owned_session': True}
    state.write_text(json.dumps(value))
    native_probe = binding['native'].probe_process
    monkeypatch.setattr(binding['native'], 'probe_process', lambda pid:
        {'pid': pid, 'alive': False, 'process_state': 'S'} if pid == 999999 else native_probe(pid))
    run = Mock()
    result, code = m.reload_when_idle(root, once=True, run=run)
    assert code == 75 and result['last_observation']['reason'] == 'worker_identity_uncertain'
    run.assert_not_called()


def test_actual_live_worker_with_probe_failure_before_stat_remains_uncertain(campaign, worker, monkeypatch):
    root, binding, state, _ = campaign
    set_worker(binding, state, worker)
    native_probe = binding['native'].probe_process
    monkeypatch.setattr(binding['native'], 'probe_process', lambda pid:
        {'pid': pid, 'alive': False} if pid == worker.pid else native_probe(pid))
    assert Path('/proc', str(worker.pid)).exists()
    run = Mock(side_effect=AssertionError('unreadable existing worker must survive'))
    result, code = m.reload_when_idle(root, once=True, run=run)
    assert code == 75 and result['last_observation']['reason'] == 'worker_identity_uncertain'
    assert worker.poll() is None
    run.assert_not_called()


def test_scope_change_at_last_boundary_prevents_restart(campaign, monkeypatch):
    root, _, _, _ = campaign
    def inspect(*args, **kwargs):
        path = root / m.CONFIG; value = json.loads(path.read_text()); value['poll_seconds'] += 1
        path.write_text(json.dumps(value))
        return snapshots()[0]
    monkeypatch.setattr(m, 'service_snapshot', inspect)
    run = Mock()
    with pytest.raises(RuntimeError, match='scope changed'):
        m.reload_when_idle(root, once=True, run=run)
    run.assert_not_called()


def test_spawned_new_pid_without_fresh_native_status_never_claims_reload_ready(campaign, monkeypatch):
    root, binding, _, _ = campaign
    states = snapshots(); count = []
    monkeypatch.setattr(m, 'service_snapshot', lambda *a, **kw: states[0] if not count else states[1])
    def restart(*args):
        count.append(1)
        path = binding['native_cfg'].state_dir / 'status.json'
        path.write_text(json.dumps({'schema': binding['native'].SCHEMA, 'observed_at': time.time()-600,
                                    'action': 'healthy'}))
    result, code = m.reload_when_idle(root, timeout=1, once=True, run=restart)
    assert code == 75 and result['restart_requested'] and not result['reloaded']
    assert len(count) == 1


def test_old_final_tick_during_restart_cannot_attest_replacement_readiness(campaign, monkeypatch):
    root, binding, state, _ = campaign
    before = state.read_bytes()
    values = snapshots(); restarted = []
    monkeypatch.setattr(m, 'service_snapshot', lambda *a, **kw: values[1] if restarted else values[0])
    def restart(*args):
        # The old daemon publishes a genuinely current last tick while the
        # service manager is still waiting for it to stop.
        publish_fresh_status(binding)
        time.sleep(.01)
        restarted.append(1)
    result, code = m.reload_when_idle(root, timeout=1, once=True, run=restart)
    assert code == 75 and result['reason'] == 'new_daemon_readiness_deadline'
    assert len(restarted) == 1 and not result['reloaded']
    assert state.read_bytes() == before


@pytest.mark.parametrize('timeout', [0, -1, 1801, True])
def test_deadline_is_bounded_before_any_lifecycle_operation(campaign, timeout):
    with pytest.raises(RuntimeError, match='1..1800'):
        m.reload_when_idle(campaign[0], timeout=timeout, run=Mock())


def test_scope_refuses_other_registered_unit_and_path_escape(campaign):
    root, _, _, _ = campaign
    path = root / m.CONFIG; original = json.loads(path.read_text())
    for change in ({'repair_unit': 'ipfs-vdg-repair-monitor.service'}, {'state_root': '../outside'}):
        path.write_text(json.dumps({**original, **change}))
        with pytest.raises(RuntimeError): m.scope(root)


def test_registered_fragment_and_actual_daemon_scope_are_required(campaign, tmp_path, monkeypatch):
    root, binding, _, _ = campaign
    home = tmp_path / 'private-home'; fragment = home / '.config/systemd/user' / m.UNIT
    fragment.parent.mkdir(parents=True)
    fragment.write_text('# Managed by JevOps tools/manage_supervisor_watchdog.py\n[Service]\n')
    monkeypatch.setattr(m.Path, 'home', lambda: home)
    fields = {'Id': m.UNIT, 'LoadState': 'loaded', 'ActiveState': 'inactive', 'MainPID': '0',
              'WorkingDirectory': str(root), 'KillMode': 'process', 'FragmentPath': str(fragment)}
    def show(*args): return SimpleNamespace(stdout='\n'.join(k+'='+v for k,v in fields.items()))
    assert m.service_snapshot(binding, run=show)['identity'] is None
    fields['WorkingDirectory'] = '/unrelated/repository'
    with pytest.raises(RuntimeError, match='scope/lifecycle'): m.service_snapshot(binding, run=show)
    fields['WorkingDirectory'] = str(root); fields['FragmentPath'] = '/unmanaged/unit.service'
    with pytest.raises(RuntimeError, match='fragment'): m.service_snapshot(binding, run=show)


@pytest.mark.parametrize('fault', ['fake_module_after_c', 'duplicate_scope'])
def test_actual_service_identity_rejects_ambiguous_python_or_scope(campaign, tmp_path, monkeypatch, fault):
    root, binding, _, _ = campaign
    home = tmp_path/'home'; fragment = home/'.config/systemd/user'/m.UNIT
    fragment.parent.mkdir(parents=True)
    fragment.write_text('# Managed by JevOps tools/manage_supervisor_watchdog.py\n')
    monkeypatch.setattr(m.Path, 'home', lambda: home)
    fields = {'Id': m.UNIT, 'LoadState': 'loaded', 'ActiveState': 'active', 'MainPID': '999',
              'WorkingDirectory': str(root), 'KillMode': 'process', 'FragmentPath': str(fragment)}
    argv = [binding['supervisor']['python_executable'], '-m', m.MODULE,
            '--repo-root', str(root), '--manifest-path', str(binding['manifest_path']),
            '--state-dir', str(binding['native_cfg'].state_dir),
            '--repair-lock-path', str(binding['native_cfg'].repair_lock_path), '--apply']
    if fault == 'fake_module_after_c': argv[1:1] = ['-c', 'unrelated executable code']
    else: argv.extend(['--repo-root', str(root)])
    actual = {'pid': 999, 'alive': True, 'start_ticks': 10, 'argv': argv, 'cwd': str(root)}
    monkeypatch.setattr(binding['native'], 'probe_process', lambda pid: actual)
    proc = tmp_path/'private-proc'; (proc/'999').mkdir(parents=True)
    (proc/'999/exe').symlink_to(Path(binding['supervisor']['python_executable']).resolve())
    def show(*args): return SimpleNamespace(stdout='\n'.join(k+'='+v for k,v in fields.items()))
    with pytest.raises(RuntimeError): m.service_snapshot(binding, run=show, proc_root=proc)
