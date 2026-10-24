#!/usr/bin/env python3
"""Execute one reviewed bounded work package, never a model-authored command.

Receipts bind the task, inputs, producer/checker bytes, exact argv, output and
raw logs. They are operational evidence, not proof/completion authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_lean_refactor_plan as check

FROZEN_CORPUS = 'papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl'
COMMANDS = {
    ('python', '-m', 'jevops.arena', '--calibrate'): 'calibration',
    ('python', 'papers/completion/lean_refactor_arena/harness/run_warmup.py', '--offline-self-check'): 'offline_protocol',
    ('python', 'papers/completion/lean_refactor_arena/tools/verify_lra_batch.py', '--schedule'): 'schedule',
}
NATIVE_COMMAND = ['python3', '-m', 'jevops.arena_lean', '--smoke', '--tag', 'v4.31.0', '--max-processes', '4', '--timeout', '60']


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


def write_json(path, value):
    atomic(path, json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')


def run_process(argv, *, root: Path, timeout: float, directory: Path):
    """No shell, private process group, bounded disk logs, own-group cleanup."""
    import resource
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stdout, stderr = directory / 'stdout.log', directory / 'stderr.log'
    started, stamp = time.monotonic(), now()
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART': '0'}
    timed_out, process = False, None
    handlers = {}
    def interrupted(signum, frame):
        raise KeyboardInterrupt('campaign command interrupted by signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGINT):
        handlers[signum] = signal.signal(signum, interrupted)
    with stdout.open('xb') as out, stderr.open('xb') as err:
        try:
            process = subprocess.Popen(argv, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err, shell=False, start_new_session=True,
                                       preexec_fn=limits)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                code = 124
        except BaseException:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            raise
        finally:
            # A successful parent must not leave descendant fixture/compiler processes.
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
    return {'argv': argv, 'exit_code': code, 'timed_out': timed_out, 'started_at': stamp,
            'finished_at': now(), 'duration_seconds': time.monotonic() - started,
            'stdout': stdout, 'stderr': stderr}


def checked_command(command):
    check.strings(command, 'reviewed argv')
    normalized = ['python' if Path(command[0]).name in {'python', 'python3', 'python3.11', 'python3.12'} else command[0], *command[1:]]
    check.require(tuple(normalized) in COMMANDS, 'command is not in the closed reviewed argv registry')
    return [sys.executable, *normalized[1:]], COMMANDS[tuple(normalized)]


def command_semantics(kind, raw):
    value = check.decode(raw)
    check.require(type(value) is dict, 'command output must be actual structured JSON')
    if kind == 'calibration':
        check.require(value.get('schema') == 'jevops-arena-calibration/v1'
                      and value.get('problems') == value.get('reference_token_matches') == 15
                      and value.get('required_version_checks') == 36 and value.get('completed_version_checks') == 0
                      and value.get('official_score') is None
                      and value.get('worker_metric_parity') == 'UNCONFIRMED', 'calibration contract failed')
    elif kind == 'offline_protocol':
        check.require(value.get('ok') is True and value.get('offline_fixtures') is True
                      and value.get('live_health_checked') is False and value.get('arena_score') is None
                      and value.get('failures_retained') is True, 'offline protocol must remain fixture evidence')
    elif kind == 'schedule':
        check.require(value.get('n_scheduled') == 15 and value.get('warmup_jsonl_sha256') ==
                      '6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804', 'frozen schedule mismatch')
    else:
        check.require(value.get('official_score') is None and
                      (value.get('n_problems') == 15 or len(value.get('records', value.get('problems', []))) == 15),
                      'autoencoder plan does not bind full frozen corpus')
    return {'passed': True, 'kind': kind, 'observed': value,
            'evidence_mode': 'offline_fixture' if kind == 'offline_protocol' else 'offline_analysis', **check.AUTH}


def host_inventory(root, directory, timeout, process_runner=run_process):
    tools, executions = {}, []
    for name, arguments in [('lean', ['--version']), ('lake', ['--version']),
                            ('nvidia-smi', ['--query-gpu=index,name,memory.total,memory.used', '--format=csv,noheader'])]:
        path = shutil.which(name)
        if path is None:
            tools[name] = {'available': False, 'path': None, 'reason': 'not_on_PATH'}
            continue
        result = process_runner([path, *arguments], root=root, timeout=min(5, timeout), directory=directory / name)
        executions.append(result)
        tools[name] = {'available': result['exit_code'] == 0, 'path': str(Path(path).resolve()),
                       'exit_code': result['exit_code'], 'timed_out': result['timed_out'],
                       'version_or_devices': check.regular(result['stdout']).decode(errors='replace')[:8192]}
    disk = shutil.disk_usage(root)
    memory = {}
    meminfo = Path('/proc/meminfo')
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            key, value = line.split(':', 1)
            if key in {'MemTotal', 'MemAvailable'}:
                memory[key + '_bytes'] = int(value.split()[0]) * 1024
    source_identity = {relative: check.digest(check.regular(check.safe_path(root, relative)))
                       for relative in (check.PLAN, check.CONFIG, 'tools/check_lean_refactor_plan.py',
                                        'tools/run_lean_refactor_campaign.py')}
    return {'schema': 'jevops.lean-refactor.host-inventory.v1', 'observed_at': now(), 'source_identity': source_identity,
            'hardware': {'machine': platform.machine(), 'cpu_count': os.cpu_count(), **memory},
            'disk': {'total_bytes': disk.total, 'used_bytes': disk.used, 'free_bytes': disk.free},
            'tools': tools, 'proofs_compiled': 0, 'hardware_attestation': False, **check.AUTH}, executions


def scoring_parity(root):
    """Compare real JevOps arithmetic against the pinned organizer scorer."""
    sys.path.insert(0, str(root))
    from jevops.arena import aggregate_scores, score_metrics
    path = root / 'papers/completion/lean_refactor_arena/space/leaderboard.py'
    tree = __import__('ast').parse(check.regular(path))
    cls = next(x for x in tree.body if isinstance(x, __import__('ast').ClassDef) and x.name == 'Leaderboard')
    methods = [x for x in cls.body if isinstance(x, __import__('ast').FunctionDef) and
               x.name in {'problem_axes', 'problem_score', '_compute_user_summary'}]
    check.require(len(methods) == 3, 'pinned official arithmetic API changed')
    ast = __import__('ast')
    namespace = {'benchmark_names': lambda: ['a', 'b', 'c']}
    ast_class = ast.ClassDef(name='Official', bases=[], keywords=[], body=methods, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast_class], type_ignores=[])), str(path), 'exec'), namespace)
    official = namespace['Official']
    rng, count = __import__('random').Random(20261024), 0
    for _ in range(96):
        rows, scores = {}, {}
        for name in ['a', 'b']:
            length, hb = rng.randrange(0, 250), rng.randrange(0, 350)
            passed = rng.randrange(0, 4)
            compiled = rng.choice([True, True, False])
            score = score_metrics(reference_length=100, reference_heartbeats=200,
                                  length=length, heartbeats=hb, passed=passed, total=3, compiled=compiled)
            row = {'compiled': compiled, 'length_reduction_pct': round((100 - length), 2),
                   'heartbeat_reduction_pct': round((200 - hb) / 2, 2),
                   'compat': {str(i): {'passed': i < passed} for i in range(3)}}
            check.require(official.problem_score(row) == score.combined_pct, 'per-problem scorer mismatch')
            rows[name], scores[name] = row, score
            count += 1
        summary = official._compute_user_summary(rows)
        expected = round((summary['avg_len_pct'] + summary['avg_hb_pct'] + summary['survival_rate']) / 3, 2)
        check.require(aggregate_scores(['a', 'b', 'c'], scores)['local_combined_pct'] == expected,
                      'whole-denominator/compatibility rounding parity failed')
        count += 1
    check.require(official.problem_score(None) == official.problem_score({'compiled': False}) == 0,
                  'missing/failure zero policy changed')
    check.require(official.problem_axes({'compiled': True}) == (0.0, 0.0, 100.0), 'default-only compatibility changed')
    check.require(aggregate_scores(['a'], {'a': None})['status'] == 'INCOMPLETE', 'unknown observation became zero')
    return {'schema': 'jevops.lean-refactor.scoring-parity.v1', 'passed': True, 'checks': count + 3,
            'official_source_sha256': check.digest(check.regular(path)),
            'scope': 'pinned vendored scorer arithmetic; live worker parity remains unconfirmed', **check.AUTH}


def native_semantics(root, raw):
    value = check.decode(raw)
    check.require(value.get('schema') == 'jevops-arena-native-smoke/v1' and value.get('evidence_mode') == 'local_lean'
                  and value.get('arena_problem') is False and value.get('official_score') is None
                  and value.get('live_model_calls') == 0 and 2 <= value.get('processes', 0) <= 4,
                  'actual non-Arena native smoke report required')
    sys.path.insert(0, str(root))
    from jevops.proof_trust import audit_axioms
    candidate = value.get('candidate') or {}
    check.require(candidate.get('status') == 'MEASURED' and candidate.get('evidence_mode') == 'local_lean'
                  and len(candidate.get('receipts', [])) == 1, 'native candidate was not actually measured')
    check.require(value['baseline_context']['versions'] == [{'lean_tag': 'v4.31.0', 'git_commit': 'local-stdlib-smoke'}],
                  'native smoke substituted another compiler pin')
    for receipt, source in [(value['baseline'], value['reference_source']),
                            (candidate['receipts'][0], value['candidate_source'])]:
        check.require(receipt.get('outcome') == 'VERIFIED' and receipt.get('exit_code') == 0
                      and receipt.get('type_preserved') is True and receipt.get('target') == 'arena_smoke'
                      and receipt.get('candidate_sha256') == check.digest(source.encode()),
                      'native target/source/type/exit proof missing')
        audit = audit_axioms(receipt.get('axiom_output', ''), ['arena_smoke'], allowed_axioms=())
        check.require(audit['accepted'], 'native smoke axiom audit failed')
        observation = check.decode(receipt.get('observations_json', '{}')).get('report', {})
        check.require(observation.get('target_absent_before') is True and observation.get('type_preserved') is True
                      and observation.get('axioms') == [] and observation.get('reference_axioms') == [],
                      'native target-free/reference axiom evidence missing')
    return {'schema': 'jevops.lean-refactor.native-smoke.v1', 'target': 'arena_smoke',
            'native_compiler_exit': 0, 'axiom_audit_passed': True, 'benchmark_proofs_verified': 0,
            'evidence_mode': 'native_smoke_not_arena', 'observed': value, **check.AUTH}


def native_smoke(root, directory, timeout, command, process_runner=run_process):
    check.require(command == NATIVE_COMMAND, 'only the exact reviewed native-smoke argv is admitted')
    result = process_runner([sys.executable, *command[1:]], root=root, timeout=timeout, directory=directory / 'native')
    check.require(result['exit_code'] == 0 and not result['timed_out'], 'native smoke compiler failed')
    return native_semantics(root, check.regular(result['stdout'])), [result]


def run_task(root: Path, task_id: str, *, campaign=None, process_runner=run_process):
    root = root.resolve(strict=True)
    campaign = campaign or check.load_plan(root)
    check.require(task_id in campaign['tasks'], 'unknown task')
    task = campaign['tasks'][task_id]
    check.require(task['mode'] == 'deterministic', 'router tasks must use reviewed router bridge')
    check.require(campaign['board'][task_id][3]['status'].lower() in {'pending', 'todo', 'ready'},
                  'planned/active/completed tasks cannot be manually executed by this producer')
    check.require(all(campaign['board'][d][3]['status'].lower() in {'completed', 'done'} for d in task['depends_on']),
                  'dependency not completed')
    action, timeout = task['work_package']['action'], task['bounds']['timeout_seconds']
    check.require(action in {'host_inventory', 'command', 'scoring_parity', 'native_smoke'}, 'unknown executable action')
    check.require(len(task['outputs']) == 1 and task['outputs'][0].endswith('.json'), 'one deterministic JSON result required')
    binding = check.task_binding(root, campaign, task)
    receipts = check.safe_path(root, check.RECEIPTS)
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = receipts / (task_id + '.lock')
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_relative = check.RECEIPTS + '/runs/' + task_id + '-' + uuid.uuid4().hex
        directory = check.safe_path(root, run_relative)
        directory.mkdir(parents=True, mode=0o700)
        started, stamp, executions, output, code, timed_out, error = time.monotonic(), now(), [], None, 0, False, None
        try:
            if action == 'host_inventory':
                output, executions = host_inventory(root, directory, timeout, process_runner)
            elif action == 'scoring_parity':
                output = scoring_parity(root)
            elif action == 'native_smoke':
                output, executions = native_smoke(root, directory, timeout, task['work_package'].get('command'), process_runner)
            else:
                command, kind = checked_command(task['work_package'].get('command'))
                result = process_runner(command, root=root, timeout=timeout, directory=directory / 'command')
                executions = [result]
                code, timed_out = result['exit_code'], result['timed_out']
                check.require(code == 0 and not timed_out, 'reviewed subprocess failed or timed out')
                output = command_semantics(kind, check.regular(result['stdout']))
            check.require(check.task_binding(root, campaign, task) == binding, 'input/producer source changed during execution')
            write_json(check.safe_path(root, task['outputs'][0]), output)
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            error, code = str(exc), code or 1
        logs, execution_rows = [], []
        for result in executions:
            row = {k: v for k, v in result.items() if k not in {'stdout', 'stderr'}}
            for key in ('stdout', 'stderr'):
                relative = str(result[key].relative_to(root))
                sha = check.digest(check.regular(result[key]))
                row[key] = {'path': relative, 'sha256': sha}
                logs.append(row[key])
            execution_rows.append(row)
        receipt = {'schema': 'jevops.lean-refactor.task-receipt.v1', 'task_id': task_id,
                   'binding': binding, 'command': task['work_package'].get('command', []),
                   'started_at': stamp, 'finished_at': now(), 'duration_seconds': time.monotonic() - started,
                   'actor': {'pid': os.getpid(), 'uid': os.getuid()}, 'exit_code': code, 'timed_out': timed_out,
                   'error': error, 'executions': execution_rows, 'logs': logs,
                   'outputs': {p: check.digest(check.regular(check.safe_path(root, p))) for p in task['outputs']}
                   if code == 0 else {}, 'archive_path': run_relative + '/receipt.json', **check.AUTH}
        write_json(directory / 'receipt.json', receipt)
        write_json(receipts / (task_id + '.json'), receipt)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', nargs='?')
    parser.add_argument('--task-id')
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if bool(args.task) == bool(args.task_id):
        parser.error('supply exactly one task id')
    try:
        result = run_task(args.repo_root, args.task_id or args.task)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return result['exit_code'] if 0 <= result['exit_code'] <= 255 else 1
    except (OSError, ValueError, KeyError, TypeError, BlockingIOError) as exc:
        print(json.dumps({'failed': True, 'reason': str(exc), **check.AUTH}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
