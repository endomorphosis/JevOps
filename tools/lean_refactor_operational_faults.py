#!/usr/bin/env python3
"""Run a closed, fresh operational fault suite using owned private fixtures only.

This qualifies the recorded operational version, never a theorem or an improved
proof. No production daemon, GPU, provider, or campaign status is controlled.
"""
from __future__ import annotations

import argparse
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
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SELF = 'tools/lean_refactor_operational_faults.py'
VALIDATOR = 'tools/validate_lean_refactor_operational_faults.py'
BASE = 'config/lean_refactor_arena_20261024_supervisor.json'
RUNTIME = 'data/lean_refactor_arena_20261024/execution-v2'
SCHEMA = 'jevops.lean-refactor.operational-faults.v1'
TIMEOUT = 480
MAX_SOURCES = 2000
MAX_SOURCE_BYTES = 128*1024**2
AUTH = {'completion_authority': False, 'proof_authority': False,
        'full_campaign_complete': False, 'optimization_success': False,
        'training_executed': False, 'model_calls': 0, 'provider_calls': 0,
        'production_processes_signaled': False, 'production_states_changed': False}
CORE_MODULES = tuple('ipfs_accelerate_py/agent_supervisor/rescue/'+name+'.py'
                     for name in ('lane_resume','gate_recovery','repair_dispatcher',
                                  'supervisor_watchdog','storage_pressure'))

# Exact case names also form the required JUnit coverage. Parameterized cases
# remain independently counted; no cached proof plugin or skipped case qualifies.
POLICY = (
 ('jevops', 'tests/test_watchdog_repair_escalation.py', (
  'test_configured_pending_task_faults_are_classified_from_real_framework_evidence',
  'test_real_exit_zero_worker_runs_once_but_cannot_mark_recovery_or_task_complete',
  'test_persistent_incident_uses_three_real_attempts_across_reload_then_attention',
  'test_only_fresh_independent_progress_can_clear_incident_without_completing_task',
  'test_observational_mode_and_owned_hold_never_launch_even_a_fixture_repair')),
 ('accelerator', 'test/api/test_agent_supervisor_gate_recovery.py', (
  'test_withheld_fingerprint_survives_restarts_and_ignores_clock_and_log_churn',
  'test_semantic_changes_bypass_gate_cooldown',
  'test_withheld_gate_does_not_starve_later_ready_task',
  'test_new_hold_between_gate_probe_and_repair_stops_followup_actions',
  'test_new_hold_during_success_stops_validation_or_completion',
  'test_repair_admission_rejects_contract_drift')),
 ('accelerator', 'test/api/test_agent_supervisor_storage_pressure.py', (
  'test_real_owned_command_keeps_progressing_across_failed_heartbeats_and_recovers',
  'test_a_real_task_producer_is_not_reexecuted_when_completion_commit_temporarily_fails',
  'test_pending_durable_write_honors_real_stop_without_committing',
  'test_emergency_status_rejects_stale_or_mismatched_identity')),
 ('accelerator', 'test/api/test_agent_supervisor_lane_resume_lifecycle.py', (
  'test_command_timeout_kills_descendants_for_either_leader_behavior',
  'test_heartbeat_error_stops_the_owned_command_tree',
  'test_successful_command_keeps_its_exit_code_and_output',
  'test_handoff_descriptor_cannot_steal_or_unlock_another_open_descriptions_fence')),
 ('jevops', 'tests/test_reload_supervisor_when_idle.py', (
  'test_real_native_presence_prevents_restart_and_is_not_removed',
  'test_actual_live_session_worker_defers_without_any_signal',
  'test_queued_reload_waits_for_real_native_presence_release',
  'test_scope_change_at_last_boundary_prevents_restart')),
)


def require(value, message):
    if not value:
        raise ValueError(message)


def raw_file(path, maximum=8*1024**2):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_size <= maximum, 'owned bounded ordinary file required: '+str(path))
    raw = path.read_bytes()
    after = path.lstat()
    require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'file changed while reading')
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(raw_file(path))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def source_version(sources):
    return digest(canonical({name: row['sha256'] for name, row in sources.items()}))


def save_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def configuration(root):
    base = json.loads(raw_file(root/BASE))
    # Preserve the registered venv entrypoint: resolving its final symlink
    # would select the system interpreter and discard the installed pytest.
    python = Path(base['python_executable'])
    accelerator = Path(base['accelerator_source']).resolve(strict=True)
    require(python.is_absolute() and python.is_file() and accelerator.is_dir(), 'registered runtime unavailable')
    return python, accelerator


def selectors(root, accelerator):
    roots = {'jevops': root, 'accelerator': accelerator}
    return [str(roots[scope]/path)+'::'+name
            for scope, path, names in POLICY for name in names]


def source_files(root, accelerator):
    files = {'jevops/'+SELF: root/SELF, 'jevops/'+VALIDATOR: root/VALIDATOR,
             'jevops/tools/reload_supervisor_when_idle.py': root/'tools/reload_supervisor_when_idle.py',
             'jevops/config/lean_refactor_arena_20261024_watchdog.json': root/'config/lean_refactor_arena_20261024_watchdog.json'}
    roots = {'jevops': root, 'accelerator': accelerator}
    for scope, path, _ in POLICY:
        files[scope+'/'+path] = roots[scope]/path
    directory = accelerator/'ipfs_accelerate_py/agent_supervisor'
    require(directory.is_dir(), 'actual registered operational framework missing')
    require(all((accelerator/name).is_file() for name in CORE_MODULES), 'operational core module missing')
    for path in sorted(directory.rglob('*.py')):
        require(path.resolve().is_relative_to(accelerator), 'framework source escapes registered root')
        files['accelerator/'+str(path.relative_to(accelerator))] = path
    require(len(files) <= MAX_SOURCES, 'operational source population bound')
    return files


def protected_files(root):
    paths = [BASE, 'implementation_plan/lean_refactor_arena_20261024.goals.json',
             'implementation_plan/lean_refactor_arena_20261024.todo.md',
             'implementation_plan/lean_refactor_arena_20261024.execution-v2.todo.md',
             'config/lean_refactor_arena_20261024_execution_v2.json',
             'data/lean_refactor_arena_20261024/router-budget.json']
    paths += [name for name in (RUNTIME+'/iterative-v1-ledger.json',) if (root/name).exists()]
    return {name: root/name for name in paths}


def parse_junit(path):
    raw = raw_file(path, 4*1024**2)
    require(b'<!DOCTYPE' not in raw and b'<!ENTITY' not in raw, 'JUnit entities forbidden')
    cases = list(ET.fromstring(raw).iter('testcase'))
    require(cases and not any(list(case.iter(tag)) for case in cases
                             for tag in ('failure', 'error', 'skipped')),
            'every fresh fault case must execute and pass')
    pairs = [(case.attrib.get('classname', '').split('.')[-1],
              case.attrib.get('name', '').split('[', 1)[0]) for case in cases]
    names = [case.attrib.get('classname', '')+'.'+case.attrib.get('name', '') for case in cases]
    require(len(set(names)) == len(names), 'duplicate fault case identity')
    for _, path, required in POLICY:
        module = Path(path).stem
        for name in required:
            require((module, name) in pairs,
                    'missing executed fault coverage: '+module+'.'+name)
    allowed = {(Path(path).stem, name) for _, path, required in POLICY for name in required}
    require(all(pair in allowed for pair in pairs), 'unexpected fault suite case')
    durations = [float(case.get('time', '0')) for case in cases]
    require(all(math.isfinite(t) and 0 <= t <= TIMEOUT for t in durations), 'invalid fault timing')
    return {'executed_testcases': len(cases), 'failed': 0, 'skipped': 0, 'case_names': names}


def run_owned(argv, cwd, env, directory):
    """One own process group; timeout cleanup never signals another group."""
    started = time.time();timed_out = False
    with (directory/'stdout.log').open('xb') as out, (directory/'stderr.log').open('xb') as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
        try:
            code = child.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL);child.wait(timeout=2)
            code = child.returncode
        finally:
            # Fixture tests own and reap their children. Refuse a nominal pass
            # if the top-level private group nevertheless leaked live actors.
            try: os.killpg(child.pid, 0); empty = False
            except ProcessLookupError: empty = True
            if not empty:
                os.killpg(child.pid, signal.SIGKILL)
    return {'argv': argv, 'cwd': str(cwd), 'pid': child.pid, 'uid': os.getuid(),
            'started_at': started, 'finished_at': time.time(), 'exit_code': code,
            'timed_out': timed_out, 'private_process_group_empty': empty,
            'shell': False, 'timeout_seconds': TIMEOUT}


def produce(root=ROOT):
    root = root.resolve(strict=True);python, accelerator = configuration(root)
    run = root/RUNTIME/'operational-faults'/uuid.uuid4().hex
    run.mkdir(parents=True, mode=0o700, exist_ok=False)
    before = source_files(root, accelerator)
    sources = {};total = 0
    for label, path in before.items():
        raw = raw_file(path);total += len(raw)
        require(total <= MAX_SOURCE_BYTES, 'operational source snapshot byte bound')
        relative = str((run/'sources'/(digest(raw)+'.bin')).relative_to(root))
        if not (root/relative).exists(): save_new(root/relative, raw)
        sources[label] = {'sha256': digest(raw), 'bytes': len(raw), 'archive': relative}
    protected = {};protected_archives = {}
    for name, path in protected_files(root).items():
        raw = raw_file(path);protected[name] = digest(raw)
        relative = str((run/'state-before'/(digest(raw)+'.bin')).relative_to(root))
        if not (root/relative).exists():save_new(root/relative, raw)
        protected_archives[name] = relative
    home = run/'private-home';home.mkdir(mode=0o700)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(home),
           'PYTHONPATH': str(accelerator)+os.pathsep+str(root),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
           'IPFS_TEST_PROOF_REUSE_MODE': 'off', 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'}
    argv = [str(python), '-B', '-m', 'pytest', '-q', '-c', '/dev/null', '--noconftest',
            '-p', 'no:cacheprovider', '--rootdir='+str(root.parent), '--basetemp='+str(run/'private-fixtures'),
            '--junitxml='+str(run/'actual-tests.xml'), *selectors(root, accelerator)]
    execution = run_owned(argv, root, env, run)
    execution_path = run/'execution.json';save_new(execution_path, canonical(execution))
    require(execution['exit_code'] == 0 and execution['timed_out'] is False
            and execution['private_process_group_empty'] is True, 'fresh owned fault suite failed; inspect retained logs')
    actual = parse_junit(run/'actual-tests.xml')
    require(sources.keys() == source_files(root, accelerator).keys()
            and all(sha(before[name]) == row['sha256'] for name, row in sources.items()),
            'tested operational source changed during execution')
    require(protected == {name: sha(path) for name, path in protected_files(root).items()},
            'campaign/proof/budget state changed during fault fixtures')
    evidence = {name: {'path': str((run/name).relative_to(root)), 'sha256': sha(run/name)}
                for name in ('actual-tests.xml', 'stdout.log', 'stderr.log', 'execution.json')}
    report = {'schema': SCHEMA, 'task_id': 'JLR-033', 'status': 'QUALIFIED_OWNED_FIXTURES',
              'observed_at': time.time(), 'run_directory': str(run.relative_to(root)),
              'producer_sha256': sources['jevops/'+SELF]['sha256'],
              'validator_sha256': sources['jevops/'+VALIDATOR]['sha256'],
              'tested_operational_version': source_version(sources), 'tested_sources': sources,
              'protected_state_before': protected, 'protected_state_after': protected,
              'protected_state_archives': protected_archives,
              'execution': execution, 'actual_tests': actual, 'evidence': evidence,
              'scope': 'fresh offline and owned-fixture faults; no production fault injection', **AUTH}
    save_new(run/'result.json', canonical(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--produce', action='store_true', required=True);parser.parse_args()
    try:print(json.dumps(produce(), sort_keys=True, allow_nan=False));return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'FAILED', 'reason': str(exc), **AUTH}), file=sys.stderr);return 1


if __name__ == '__main__':raise SystemExit(main())
