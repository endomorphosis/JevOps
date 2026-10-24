#!/usr/bin/env python3
"""Preflight or explicitly start the isolated JevOps deterministic supervisor.

Each model command calls the separate strict LLM-router proposal worker. This
launcher never supplies raw Grok argv, changes another lane, or pushes Git.
"""
from __future__ import annotations
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('jevops_router_bridge', ROOT / 'tools/run_lean_refactor_router_task.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
MANIFEST = 'config/lean_refactor_arena_20261024_lanes.json'


def preflight(root):
    cfg = bridge.config(root)
    source = Path(cfg['accelerator_source']).resolve(strict=True)
    sys.path.insert(0, str(source))
    from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
    from ipfs_accelerate_py.agent_supervisor.rescue.lane_resume import parse_deterministic_command
    from ipfs_accelerate_py.agent_supervisor.rescue.supervisor_watchdog import parse_todo_task_fields
    board = bridge.regular(root / cfg['taskboard']).decode()
    rows = parse_todo_blocks(board, task_header_prefix=cfg['task_header_prefix'])
    bridge.require(rows and len({row[0] for row in rows}) == len(rows), 'Nonempty unique native taskboard required')
    ids = {row[0] for row in rows}
    native = dict(parse_todo_task_fields(board, task_header_prefix=cfg['task_header_prefix']))
    bridge.require(set(native) == ids, 'Native rescue task identities differ')
    dependencies = {}
    for task_id, _, _, fields in rows:
        dependencies[task_id] = bridge.split_paths(fields.get('depends_on'))
        bridge.require(all(item in ids for item in dependencies[task_id]), 'Unknown dependency')
        command = native[task_id].get('deterministic_command')
        bridge.require(parse_deterministic_command(command, repo_root=root) is not None,
                       'Every task needs a genuine supervised command: ' + task_id)
        bridge.require(parse_deterministic_command(fields.get('validation'), repo_root=root) is not None,
                       'Every task needs independent deterministic validation: ' + task_id)
    visiting, visited = set(), set()
    def visit(key):
        bridge.require(key not in visiting, 'Cyclic task graph')
        if key in visited: return
        visiting.add(key)
        for dependency in dependencies[key]: visit(dependency)
        visiting.remove(key); visited.add(key)
    for task_id in ids: visit(task_id)
    manifest = bridge.decode(bridge.regular(root / MANIFEST))
    bridge.require(manifest['todo_path'] == cfg['taskboard'] and manifest['task_header_prefix'] == cfg['task_header_prefix']
                   and manifest.get('allow_bounded_task_implement') is False and len(manifest['lanes']) == 1,
                   'Isolated manifest/task source mismatch')
    validation = subprocess.run([cfg['python_executable'], str(root / 'tools/check_lean_refactor_plan.py'), '--check-all'],
                                cwd=root, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    bridge.require(validation.returncode == 0, 'Actual protected plan validator refused: ' + validation.stderr[-1000:])
    return cfg, manifest, {'valid': True, 'tasks': len(rows), 'provider_calls': 0,
                           'model': cfg['model'], 'provider': cfg['provider'],
                           'plan_validator_exit_code': validation.returncode, **bridge.AUTH}


def start(root):
    cfg, manifest, report = preflight(root)
    source = Path(cfg['accelerator_source']).resolve(strict=True)
    sys.path.insert(0, str(source))
    from ipfs_accelerate_py.agent_supervisor.rescue.lane_resume import resume_stopped_lane
    lane = dict(manifest['lanes'][0])
    bridge.require(Path(sys.executable).resolve() == Path(cfg['python_executable']).resolve(),
                   'Start with the exact configured Python interpreter')
    state = root / lane['state_dir']
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    pid_path = state / (lane['state_prefix'] + '_bundle_supervisor.pid')
    lane['pid_path'] = str(pid_path)
    lifetime_lock = state / (lane['bundle_key'] + '.resume.lock')
    environment = os.environ.copy()
    os.environ['PYTHONPATH'] = str(source)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PATH'] = str(Path(cfg['python_executable']).parent) + os.pathsep + os.environ.get('PATH', '')
    try:
        with lifetime_lock.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = resume_stopped_lane(lane, repo_root=root, manifest=manifest, resume_lock_fd=lock.fileno())
            bridge.require(result.get('restarted') is True and result.get('readiness_verified') is True,
                           'Owned lane readiness refused: ' + str(result))
            # The child inherits the SAME open-file-description flock. Closing
            # our descriptor must not unlock the live child's lifetime fence.
        runtime = root / cfg['runtime_root']
        report.update(owner=result, phase='owner_ready', guardian_readiness='not launched yet')
        bridge.write_json(runtime / 'startup.json', report)
        runtime_manifest = runtime / 'bundle_lanes.json'
        bridge.atomic(runtime_manifest, bridge.regular(root / MANIFEST))
        guardian_log = runtime / 'guardian.log'
        with guardian_log.open('ab', buffering=0) as output:
            guardian = subprocess.Popen([cfg['python_executable'], '-m',
                'ipfs_accelerate_py.agent_supervisor.rescue.watchdog_guardian',
                '--manifest-path', str(runtime_manifest), '--repo-root', str(root), '--apply'],
                cwd=root, env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        report.update(owner=result, guardian_spawned_pid=guardian.pid,
                      guardian_readiness='pending actual fresh guardian/watchdog reports; PID spawn alone is not health')
        bridge.write_json(runtime / 'startup.json', report)
        return report
    finally:
        os.environ.clear(); os.environ.update(environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--start', action='store_true', help='Explicitly launch only after reviewed preflight')
    args = parser.parse_args(argv)
    root = args.repo_root.resolve(strict=True)
    try:
        report = start(root) if args.start else preflight(root)[2]
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'valid': False, 'reason': str(exc), **bridge.AUTH}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
