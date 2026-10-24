"""JLR integration of the real repair dispatcher, using only owned fixtures.

The process probe supplies declared fixture roles. The repair worker itself
is a real bounded private Python child, never Codex, a provider, or a daemon.
No fixture observation can authorize a real task/proof completion.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / 'external/ipfs_accelerate'
sys.path.insert(0, str(SOURCE))
from ipfs_accelerate_py.agent_supervisor.rescue import repair_dispatcher as dispatcher


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    assert Path(dispatcher.__file__).resolve() == (
        SOURCE / 'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
    ).resolve(), 'Tests must exercise the canonical registered framework'
    # Do not scan/adopt any production process: all incident-side actors are
    # deliberately synthetic observations. Real worker-side process ownership
    # still goes through the framework's actual Popen/process-tree code.
    monkeypatch.setattr(dispatcher, 'discover_watchdogs', lambda *_: ([], []))
    declared = json.loads((ROOT / 'config/lean_refactor_arena_20261024_watchdog.json').read_text())
    root = tmp_path / 'fixture-repository'
    lane = root / 'runtime/lane'
    lane.mkdir(parents=True)
    board = root / 'tasks.todo.md'
    board.write_text('## JLR-001 Fixture pending work\n- Status: pending\n- Depends on:\n')
    manifest = root / 'runtime/bundle_lanes.json'
    write_json(manifest, {'todo_path': 'tasks.todo.md', 'task_header_prefix': '## JLR-',
                          'report_path': 'runtime/report.json',
                          'lanes': [{'bundle_key': 'fixture-jlr', 'state_dir': 'runtime/lane',
                                     'state_prefix': 'fixture_jlr', 'log_path': 'runtime/lane/supervisor.log'}]})
    source = root / 'fixture-source.py'
    source.write_text('# Stable fixture evidence, not a production repair.\n')
    prompt = root / 'repair.prompt.txt'
    prompt.write_bytes((ROOT / declared['repair_prompt']).read_bytes())
    now = time.time()
    owner_pid, lane_pid = 700000001, 700000002
    (manifest.parent / 'watchdog.pid').write_text(str(owner_pid))
    pid_path = lane / 'fixture_jlr_bundle_supervisor.pid'
    pid_path.write_text(str(lane_pid))
    status_path = lane / 'fixture_jlr_status.json'
    write_json(status_path, {'pid': lane_pid, 'state': 'healthy', 'phase': 'deterministic_command',
                             'active_task_id': 'JLR-001', 'active_lease_count': 1,
                             'heartbeat_at_ms': now * 1000,
                             'last_task_transition_at_ms': now * 1000})
    log = lane / 'supervisor.log'
    log.write_text('fixture progress\n')
    report = manifest.parent / 'report.json'
    write_json(report, {'status': {'pid': owner_pid, 'state': 'healthy'},
                        'reports': [{'bundle_key': 'fixture-jlr', 'action': 'none'}]})
    counter = root / 'stub-invocations.jsonl'
    stub = root / 'bounded_fixture_worker.py'
    stub.write_text(
        'import json,os,pathlib,sys\n'
        'received=sys.stdin.read()\n'
        'context=json.loads(pathlib.Path(os.environ["REPAIR_DISPATCHER_STATUS_PATH"]).read_text())\n'
        'row={"pid":os.getpid(),"uid":os.getuid(),"prompt_received":bool(received),'
        '"fixture_only":True,"completion_authority":False,"status_action":context["action"],'
        '"incident_kinds":[x["kind"] for x in context["incidents"]]}\n'
        'with pathlib.Path(sys.argv[1]).open("a") as out:out.write(json.dumps(row)+"\\n")\n'
        'print("private fixture worker exited zero; recovery remains unobserved")\n'
    )
    config = dispatcher.Config(
        manifest_path=manifest, repo_root=root, state_dir=root / 'runtime/dispatcher',
        prompt_path=prompt, worker_argv=[sys.executable, str(stub), str(counter)],
        repair_lock_path=root / 'runtime/fixer.lock', evidence_paths=(source,),
        interval=declared['poll_seconds'], heartbeat_seconds=declared['heartbeat_seconds'],
        report_seconds=declared['report_seconds'], quiet_seconds=declared['quiet_seconds'],
        startup_grace_seconds=declared['startup_grace_seconds'], worker_timeout=5,
        cooldown_seconds=declared['cooldown_seconds'], max_cooldown_seconds=declared['max_cooldown_seconds'],
        max_attempts=declared['max_repair_attempts'],
    )
    live = {owner_pid: True, lane_pid: True}
    def probe(pid):
        if pid == owner_pid:
            argv = [sys.executable, '-m', 'ipfs_accelerate_py.agent_supervisor.rescue.supervisor_watchdog',
                    '--manifest-path', str(manifest), '--repo-root', str(root)]
        elif pid == lane_pid:
            argv = [sys.executable, '-m', 'ipfs_accelerate_py.agent_supervisor.rescue.lane_resume',
                    '--repo-root', str(root), '--todo-path', str(board), '--bundle-key', 'fixture-jlr',
                    '--status-path', str(status_path), '--pid-path', str(pid_path)]
        else:
            return {'pid': pid, 'alive': False}
        return {'pid': pid, 'alive': live.get(pid, False), 'age_seconds': 10000,
                'start_ticks': pid * 10, 'argv': argv, 'cwd': str(root)}
    def status(**changes):
        value = json.loads(status_path.read_text()); value.update(changes); write_json(status_path, value)
    def advance_report(clock):
        # Only fixture freshness changes; evidence bytes/task/source identities
        # remain fixed so clock movement cannot manufacture a new incident.
        os.utime(report, (clock, clock))
    return dict(config=config, root=root, lane=lane, board=board, status_path=status_path,
                log=log, report=report, counter=counter, now=now, owner_pid=owner_pid,
                lane_pid=lane_pid, live=live, probe=probe, status=status, fresh_report=advance_report)


def incident_kinds(result):
    return {row['kind'] for row in result['incidents']}


@pytest.mark.parametrize('fault,expected', [
    ('dead', {'owner_dead', 'lane_dead_pending'}),
    ('heartbeat', {'lane_heartbeat_stale'}),
    ('no_progress', {'lane_no_progress'}),
])
def test_configured_pending_task_faults_are_classified_from_real_framework_evidence(rig, fault, expected):
    config, now = rig['config'], rig['now']
    if fault == 'dead':
        rig['live'].update({rig['owner_pid']: False, rig['lane_pid']: False})
    elif fault == 'heartbeat':
        rig['status'](heartbeat_at_ms=(now - config.heartbeat_seconds - 1) * 1000)
    else:
        old = now - config.quiet_seconds - 1
        rig['status'](last_task_transition_at_ms=old * 1000)
        os.utime(rig['log'], (old, old))
    observed = dispatcher.observe(config, {}, now=now, probe=rig['probe'])
    assert incident_kinds(observed) == expected
    assert observed['selectable_task_ids'] == ['JLR-001'] and observed['signature']
    assert observed['completion_authority'] is observed['work_complete'] is False
    assert not rig['counter'].exists(), 'observation cannot start a worker'


def test_real_exit_zero_worker_runs_once_but_cannot_mark_recovery_or_task_complete(rig):
    rig['live'][rig['lane_pid']] = False
    board_before, status_before = rig['board'].read_bytes(), rig['status_path'].read_bytes()
    state = {}
    result = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'], probe=rig['probe'])
    assert result['action'] == 'worker_finished'
    assert result['worker']['exit_code'] == 0
    assert result['worker']['outcome'] == 'awaiting_observation'
    calls = [json.loads(row) for row in rig['counter'].read_text().splitlines()]
    assert len(calls) == 1 and calls[0]['prompt_received'] is True
    assert calls[0]['status_action'] == 'dispatching'
    assert 'lane_dead_pending' in calls[0]['incident_kinds']
    assert calls[0]['fixture_only'] is True and calls[0]['uid'] == os.getuid()
    assert dispatcher.probe_process(calls[0]['pid'])['alive'] is False
    assert state['unresolved_signature'] and 'recovery_observed_at' not in state
    assert result['completion_authority'] is result['work_complete'] is False
    assert rig['board'].read_bytes() == board_before and rig['status_path'].read_bytes() == status_before
    # The same incident inside its real configured cooldown cannot fork again.
    again = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'] + 1, probe=rig['probe'])
    assert again['action'] == 'cooldown'
    assert len(rig['counter'].read_text().splitlines()) == 1


def test_persistent_incident_uses_three_real_attempts_across_reload_then_attention(rig):
    cfg = rig['config']
    assert cfg.max_attempts == 3
    rig['live'][rig['lane_pid']] = False
    before = rig['board'].read_bytes()
    state, now, signature = {}, rig['now'], None
    for attempt in range(1, 4):
        rig['fresh_report'](now)
        result = dispatcher.tick(cfg, state, apply=True, now=now, probe=rig['probe'])
        assert result['action'] == 'worker_finished' and result['worker']['exit_code'] == 0
        assert result['attempt_count'] == attempt
        signature = signature or result['signature']
        assert result['signature'] == signature, 'a clock must not reset the incident budget'
        state = json.loads((cfg.state_dir / 'state.json').read_text())
        assert state['unresolved_signature'] == signature and 'recovery_observed_at' not in state
        now = state['next_dispatch_at'] + .01
    rig['fresh_report'](now)
    capped = dispatcher.tick(cfg, state, apply=True, now=now, probe=rig['probe'])
    assert capped['action'] == 'attention_required' and capped['attempt_count'] == capped['max_attempts'] == 3
    assert capped['signature'] == signature
    calls = [json.loads(row) for row in rig['counter'].read_text().splitlines()]
    assert len(calls) == 3 and all(not dispatcher.probe_process(row['pid'])['alive'] for row in calls)
    assert rig['board'].read_bytes() == before
    assert capped['completion_authority'] is capped['work_complete'] is False


def test_only_fresh_independent_progress_can_clear_incident_without_completing_task(rig):
    rig['live'][rig['lane_pid']] = False
    state = {}
    dispatcher.tick(rig['config'], state, apply=True, now=rig['now'], probe=rig['probe'])
    assert state['unresolved_signature']
    rig['live'][rig['lane_pid']] = True
    rig['status'](heartbeat_at_ms=(rig['now'] + 2) * 1000,
                  last_task_transition_at_ms=(rig['now'] + 2) * 1000)
    result = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'] + 2, probe=rig['probe'])
    assert result['action'] == 'recovery_observed' and not state['unresolved_signature']
    assert 'Status: pending' in rig['board'].read_text()
    assert result['completion_authority'] is result['work_complete'] is False
    assert len(rig['counter'].read_text().splitlines()) == 1


def test_default_disabled_policy_leaves_planned_board_unactivated(rig):
    canonical = (ROOT / 'implementation_plan/lean_refactor_arena_20261024.todo.md').read_bytes()
    assert canonical.count(b'- Status: completed') == 15 and canonical.count(b'- Status: planned') == 23
    rig['board'].write_bytes(canonical)
    rig['live'].update({rig['owner_pid']: False, rig['lane_pid']: False})
    rig['status'](state='stopped', phase='lane_resume_exited', active_task_id='', active_lease_count=0,
                  terminal_reason='resume_duration_elapsed', heartbeat_at_ms=(rig['now'] - 100000) * 1000)
    state = {}
    result = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'], probe=rig['probe'])
    assert result['action'] == 'healthy' and result['incidents'] == []
    assert result['pending_task_ids'] == result['selectable_task_ids'] == []
    assert not state.get('attempts') and not rig['counter'].exists()
    assert rig['board'].read_bytes() == canonical
    assert result['completion_authority'] is result['work_complete'] is False


def test_enabled_campaign_policy_materializes_planned_frontier_with_real_bounded_worker(rig):
    canonical = (ROOT / 'implementation_plan/lean_refactor_arena_20261024.todo.md').read_bytes()
    rig['board'].write_bytes(canonical)
    rig['live'].update({rig['owner_pid']: False, rig['lane_pid']: False})
    rig['status'](state='stopped', phase='lane_resume_exited', active_task_id='', active_lease_count=0,
                  terminal_reason='resume_duration_elapsed')
    (rig['root'] / 'goals.json').write_bytes(
        (ROOT / 'implementation_plan/lean_refactor_arena_20261024.goals.json').read_bytes())
    manifest = json.loads(rig['config'].manifest_path.read_text())
    manifest['planned_work_policy'] = {'enabled': True, 'grace_seconds': 1, 'goals_path': 'goals.json'}
    write_json(rig['config'].manifest_path, manifest)
    state = {}
    first = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'], probe=rig['probe'])
    assert not first['incidents'] and not rig['counter'].exists()
    result = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'] + 2, probe=rig['probe'])
    assert result['action'] == 'worker_finished'
    assert 'planned_work_unmaterialized' in incident_kinds(result)
    assert result['planned_work']['materialization_task_ids'] == ['JLR-016', 'JLR-023']
    assert result['worker']['outcome'] == 'awaiting_observation'
    assert rig['board'].read_bytes() == canonical
    calls = [json.loads(line) for line in rig['counter'].read_text().splitlines()]
    assert len(calls) == 1 and 'planned_work_unmaterialized' in calls[0]['incident_kinds']
    assert result['completion_authority'] is result['work_complete'] is False


def test_observational_mode_and_owned_hold_never_launch_even_a_fixture_repair(rig):
    rig['live'][rig['lane_pid']] = False
    state = {}
    observed = dispatcher.tick(rig['config'], state, apply=False, now=rig['now'], probe=rig['probe'])
    assert observed['action'] == 'would_dispatch' and not rig['counter'].exists()
    hold = rig['config'].state_dir / 'hold'; hold.write_text('private fixture operator hold\n')
    held = dispatcher.tick(rig['config'], state, apply=True, now=rig['now'] + 1, probe=rig['probe'])
    assert held['action'] == 'held' and not rig['counter'].exists()
    assert all(record['count'] == 0 for record in state.get('attempts', {}).values())


def test_registered_configuration_and_prompt_keep_maintenance_separate_from_campaign_models():
    cfg = json.loads((ROOT / 'config/lean_refactor_arena_20261024_watchdog.json').read_text())
    prompt = (ROOT / cfg['repair_prompt']).read_text()
    assert cfg['max_repair_attempts'] == 3 and 0 < cfg['worker_timeout_seconds'] <= 900
    assert cfg['activate_planned_work'] is cfg['reset_campaign_budgets'] is False
    assert cfg['materialize_planned_work'] is True
    assert cfg['planned_work_mode'] == 'implement_validate_then_activate'
    assert cfg['guardian_unit'] != cfg['repair_unit']
    for rule in ('Do not blindly change planned to pending or completed', 'Honor operator HOLD/OPERATOR_STOP markers',
                 'use a pidfd', 'Do not weaken proof tests', 'Exit0 does not establish recovery'):
        assert rule in prompt
    assert 'Preserve concurrent edits and work in other lanes/repositories' in prompt
