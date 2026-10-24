#!/usr/bin/env python3
"""Bounded Grok proposals through the existing LlmRouterInvocation adapter.

The model proposes exact file contents. This worker verifies the closed wire
schema, source preconditions and route evidence. The lane's independent real
Validation command decides acceptance; model output never completes a task.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import sys
import time
import uuid

CONFIG = 'config/lean_refactor_arena_20261024_supervisor.json'
SCHEMA = 'jevops.lean-refactor.file-proposal.v1'
AUTH = {'completion_authority': False, 'work_complete': False}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates)


def regular(path, *, maximum=8 * 1024 * 1024):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
            'Expected singly linked owned regular file: ' + str(path))
    require(info.st_size <= maximum, 'File exceeds bounded read: ' + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        actual = os.fstat(stream.fileno())
        require((actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino), 'File changed before read')
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, 'File grew beyond bounded read')
    return raw


def atomic(path, raw, *, before_replace=None):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists(): tmp.unlink()


def write_json(path, value):
    atomic(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def checked_path(root, relative, *, protected=()):
    require(isinstance(relative, str) and relative and len(relative) <= 512, 'Invalid relative path')
    path = PurePosixPath(relative)
    require(not path.is_absolute() and path.as_posix() == relative and
            not any(part in {'', '.', '..', '.git', '.env', '.ssh', 'node_modules', '.venv'}
                    or part.startswith('.') for part in path.parts), 'Unsafe path: ' + relative)
    require(not any(relative == item or relative.startswith(item + '/') for item in protected),
            'Protected path: ' + relative)
    result = root / relative
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            info = cursor.lstat()
            require(not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid(),
                    'Foreign or symlink path: ' + str(cursor))
    require(result.resolve().is_relative_to(root), 'Path escapes repository')
    return result


def config(root):
    value = decode(regular(root / CONFIG))
    require(value['schema'] == 'jevops.lean-refactor-supervisor.v1' and
            value['profile'] == 'lean-refactor-arena-20261024', 'Unknown supervisor profile')
    require(value['provider'] == 'grok_cli' and value['model'] == 'grok-4.7' and
            value['allow_local_fallback'] is False and value['allow_cross_provider_fallback'] is False,
            'The exact Grok 4.7 router route is mandatory')
    for key, ceiling in [('max_calls', 24), ('max_task_calls_per_contract', 3),
                         ('provider_timeout_seconds', 120), ('max_output_tokens', 4096),
                         ('max_prompt_bytes', 60000), ('max_response_bytes', 65536),
                         ('max_file_bytes', 49152), ('max_files', 8), ('max_owner_seconds', 14400)]:
        require(type(value[key]) is int and 0 < value[key] <= ceiling, 'Invalid bounded ' + key)
    require(value.get('competition_eligible') is False, 'CLI research route cannot claim competition eligibility')
    return value


def split_paths(value):
    if isinstance(value, list):
        return value
    return [item.strip() for item in str(value or '').split(',') if item.strip()]


def semantic_fields(fields):
    return {key: value for key, value in fields.items() if key not in {
        'status', 'completion', 'completion_note', 'resulting_evidence', 'validation_receipts', 'completed_at'}}


def task_packet(root, cfg, task_id, parser, *, allow_completed=False):
    board = regular(checked_path(root, cfg['taskboard']))
    blocks = parser(board.decode(), task_header_prefix=cfg['task_header_prefix'])
    tasks = {item[0]: item for item in blocks}
    require(len(tasks) == len(blocks) and task_id in tasks, 'Missing/duplicate task identity')
    _, title, _, fields = tasks[task_id]
    allowed_status = {'pending', 'todo', 'ready'} | ({'completed', 'done'} if allow_completed else set())
    require(fields.get('status', '').lower() in allowed_status, 'Task is not pending')
    require(fields.get('provider_role') == 'grok-only' and fields.get('model') == 'grok-4.7',
            'Task must declare grok-only and model grok-4.7')
    for dep in split_paths(fields.get('depends_on')):
        require(dep in tasks and tasks[dep][3].get('status', '').lower() in {'completed', 'done'},
                'Dependency is not genuinely completed: ' + dep)
    paths = split_paths(fields.get('predicted_files'))
    require(paths and len(paths) == len(set(paths)) <= cfg['max_files'], 'Explicit unique predicted files required')
    outputs = split_paths(fields.get('outputs'))
    require(set(outputs) == set(paths), 'Bridge outputs must exactly equal predicted files')
    require(fields.get('validation'), 'Independent real Validation is mandatory')
    goals = decode(regular(checked_path(root, cfg['goals'])))
    declared = goals.get('tasks', []) if isinstance(goals, dict) else []
    matching = [row for row in declared if row.get('id', row.get('task_id')) == task_id]
    require(len(matching) == 1, 'Task absent/duplicated in goal DAG')
    row = matching[0]
    require(row.get('mode') == 'router', 'Only declared router tasks use this bridge')
    require(set(split_paths(row.get('predicted_files'))) == set(paths), 'DAG predicted files differ from board')
    require(split_paths(row.get('depends', row.get('depends_on'))) == split_paths(fields.get('depends_on')),
            'DAG dependencies differ from board')
    snapshots = {}
    for relative in paths:
        require(any(relative.startswith(prefix + '/') for prefix in cfg['allowed_output_prefixes']),
                'Model outputs cannot be execution/benchmark evidence or control files')
        path = checked_path(root, relative, protected=cfg['protected_paths'])
        raw = regular(path, maximum=cfg['max_file_bytes']) if path.exists() else None
        require(raw is None or len(raw) <= cfg['max_file_bytes'], 'Existing target exceeds bounded file size')
        snapshots[relative] = {'base_sha256': digest(raw) if raw is not None else None,
                               'content': raw.decode() if raw is not None else None}
    inputs = {}
    for relative in split_paths(fields.get('inputs')):
        path = checked_path(root, relative)
        raw = regular(path, maximum=cfg['max_file_bytes'])
        require(len(raw) <= cfg['max_file_bytes'], 'Input exceeds bounded source size')
        inputs[relative] = {'sha256': digest(raw), 'content': raw.decode()}
    packet = {'task_id': task_id, 'title': title, 'fields': fields,
              'goal_task': row, 'targets': snapshots, 'inputs': inputs}
    prompt = json.dumps({'instruction': 'Return only the exact JSON file proposal schema. No tools, shell, provider calls or completion claims. Preserve executable computations and Lean semantics. Include only allowed target files; base_sha256 must match the observed target. Independent validation runs afterward.',
                         'advisory_content_schema': {'schema': 'jevops.lean-refactor.review.v1', 'task_id': task_id,
                             'risks': ['unverified engineering risk'], 'actions': ['proposed action'],
                             'acceptance_boundaries': ['actual tests and Lean compilation are separate evidence'],
                             'proposal_only': True, 'needs_native_verification': True},
                         'response_schema': {'schema': SCHEMA, 'task_id': task_id,
                                             'files': [{'path': '<allowed path>', 'base_sha256': '<observed SHA or null>', 'content': '<UTF-8 full text>'}],
                                             'summary': '<brief factual change>'}, 'packet': packet}, sort_keys=True)
    require(len(prompt.encode()) <= cfg['max_prompt_bytes'], 'Task source context exceeds bounded prompt')
    contract = digest(json.dumps({'task_id': task_id, 'title': title, 'fields': semantic_fields(fields),
                                  'goal_task': semantic_fields(row),
                                  'inputs': {path: item['sha256'] for path, item in inputs.items() if path not in snapshots},
                                  'worker': digest(Path(__file__).read_bytes()),
                                  'config_sha256': digest(regular(root / CONFIG))}, sort_keys=True).encode())
    return packet, prompt, contract


def validate_proposal(raw, task_id, packet, cfg):
    require(isinstance(raw, str) and len(raw.encode()) <= cfg['max_response_bytes'], 'Response exceeds bound')
    result = decode(raw)
    require(isinstance(result, dict) and set(result) == {'schema', 'task_id', 'files', 'summary'} and
            result['schema'] == SCHEMA and result['task_id'] == task_id, 'Closed proposal schema/task mismatch')
    require(isinstance(result['summary'], str) and len(result['summary']) <= 2000, 'Invalid summary')
    files = result['files']
    require(isinstance(files, list) and 0 < len(files) <= cfg['max_files'], 'Empty or unbounded proposed files')
    seen = set()
    for row in files:
        require(isinstance(row, dict) and set(row) == {'path', 'base_sha256', 'content'}, 'Unexpected proposal fields')
        path = row['path']
        require(isinstance(path, str) and path in packet['targets'] and path not in seen, 'Foreign/duplicate proposed path')
        seen.add(path)
        require(row['base_sha256'] == packet['targets'][path]['base_sha256'], 'Proposal baseline SHA mismatch')
        require(isinstance(row['content'], str) and len(row['content'].encode()) <= cfg['max_file_bytes']
                and '\x00' not in row['content'], 'Unbounded or binary proposed content')
    return result


def effective_call_config(packet, cfg):
    bound = packet['goal_task'].get('bounds', {}).get('max_output_tokens', cfg['max_output_tokens'])
    require(type(bound) is int and bound > 0, 'Task output-token bound must be a positive integer')
    return {**cfg, 'max_output_tokens': min(cfg['max_output_tokens'], bound)}


def invoke(prompt, cfg, directory):
    source = Path(cfg['accelerator_source']).resolve(strict=True)
    sys.path.insert(0, str(source))
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import llm
    require(Path(llm.__file__).resolve().is_relative_to(source), 'Wrong installed router adapter source')
    invocation = llm.LlmRouterInvocation(
        repo_root=directory, provider='grok_cli', model_name='grok-4.7',
        allow_local_fallback=False, allow_cross_provider_fallback=False,
        required_effective_providers=('grok_cli',), timeout_seconds=cfg['provider_timeout_seconds'],
        timeout_grace_seconds=10, max_new_tokens=cfg['max_output_tokens'],
        max_prompt_chars=cfg['max_prompt_bytes'], temperature=0.0,
        python_executable=cfg['python_executable'], trace=True, trace_dir=directory,
        request_id=directory.name, env_prefix='JEVOPS_REFACTOR_LLM',
        backend_env_name='JEVOPS_REFACTOR_LLM_BACKEND')
    denied = 'call_mcp_tool,list_mcp_resources,read_mcp_resource,spawn_subagent,run_terminal_command,workflow,scheduler_create'
    overlay = {'ipfs_accelerate_py_GROK_CLI_CMD': shlex.join([cfg['grok_executable'], '--disallowed-tools', denied]),
               'ipfs_accelerate_py_ROUTER_RESPONSE_CACHE': '0',
               'ipfs_accelerate_py_GROK_CLI_TOOLS': '', 'IPFS_ACCELERATE_PY_GROK_CLI_TOOLS': '',
               'ipfs_accelerate_py_GROK_CLI_MAX_TURNS': '1', 'IPFS_ACCELERATE_PY_GROK_CLI_MAX_TURNS': '1',
               'PYTHONDONTWRITEBYTECODE': '1'}
    original = {key: os.environ.get(key) for key in overlay}
    try:
        os.environ.update(overlay)
        text, receipt = llm.call_llm_router_with_receipt(prompt, invocation)
    finally:
        for key, value in original.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
    require(receipt is not None and receipt.status == 'ok' and receipt.exit_code == 0
            and receipt.effective_provider == 'grok_cli', 'Actual router child provider receipt missing/wrong')
    traces = [decode(line) for line in regular(directory / 'grok_cli_trace.jsonl').decode().splitlines()]
    require(len(traces) == 1 and traces[0].get('provider') == 'grok_cli' and traces[0].get('model') == 'grok-4.7',
            'Actual Grok model/provider trace differs')
    command = traces[0].get('cmd')
    require(isinstance(command, list) and command[0] == cfg['grok_executable'] and
            '--model' in command and command[command.index('--model') + 1] == 'grok-4.7' and
            '--tools' in command and command[command.index('--tools') + 1] == '',
            'Actual router CLI trace must bind exact model and tool-free proposal generation')
    return text, {'child': receipt.to_dict(), 'requested_model': 'grok-4.7',
                  'requested_max_output_tokens': cfg['max_output_tokens'],
                  'actual_trace': traces[0], 'adapter_sha256': digest(regular(Path(llm.__file__))), **AUTH}


def run(root, task_id, *, preflight=False, parser=None, caller=invoke):
    root = root.resolve(strict=True)
    cfg = config(root)
    if parser is None:
        source = Path(cfg['accelerator_source']).resolve(strict=True)
        sys.path.insert(0, str(source))
        from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
        parser = parse_todo_blocks
    packet, prompt, contract = task_packet(root, cfg, task_id, parser)
    call_cfg = effective_call_config(packet, cfg)
    if preflight:
        return {'valid': True, 'task_id': task_id, 'contract': contract, 'provider_calls': 0, **AUTH}
    runtime = checked_path(root, cfg['runtime_root'])
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = runtime / 'router.lock'
    with lock.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget_path = runtime / 'router-budget.json'
        budget = decode(regular(budget_path)) if budget_path.exists() else {'calls': 0, 'contracts': {}}
        require(budget['calls'] < cfg['max_calls'] and budget['contracts'].get(contract, 0) < cfg['max_task_calls_per_contract'],
                'Explicit campaign/source-contract provider budget exhausted')
        budget['calls'] += 1; budget['contracts'][contract] = budget['contracts'].get(contract, 0) + 1
        write_json(budget_path, budget)
        directory = runtime / 'router-calls' / (task_id + '-' + uuid.uuid4().hex)
        directory.mkdir(parents=True, mode=0o700)
        write_json(directory / 'request.json', {'task_id': task_id, 'contract': contract, 'prompt_sha256': digest(prompt.encode()),
                                               'provider': 'grok_cli', 'model': 'grok-4.7', 'attempt': budget['contracts'][contract],
                                               'call_ordinal': budget['calls'], 'max_output_tokens': call_cfg['max_output_tokens'], **AUTH})
        write_json(directory / 'packet.json', packet)
        print(json.dumps({'phase': 'router_request', 'task_id': task_id, 'attempt': budget['contracts'][contract]}), flush=True)
        started = time.monotonic()
        try:
            text, route = caller(prompt, call_cfg, directory)
        except Exception as exc:
            # Keep bounded operational diagnostics even when the adapter's
            # stderr tail is truncated. Never archive credentials/config bodies.
            write_json(directory / 'failure.json', {'task_id': task_id, 'contract': contract,
                'phase': 'router_invocation', 'exception_type': type(exc).__name__,
                'reason_code': 'provider_timeout' if 'timeout' in str(exc).lower() or 'timed out' in str(exc).lower() else 'router_invocation_failed',
                'diagnostic_sha256': digest(str(exc).encode()), 'elapsed_seconds': time.monotonic() - started,
                'requested_model': 'grok-4.7', 'requested_provider': 'grok_cli',
                'max_output_tokens': call_cfg['max_output_tokens'], **AUTH})
            raise
        atomic(directory / 'response.json', text.encode())
        write_json(directory / 'route.json', route)
        proposal = validate_proposal(text, task_id, packet, cfg)
        # Validate every precondition before any target changes. Keep originals
        # and the proposal as an auditable recovery record; no evidence is erased.
        destinations = []
        for row in proposal['files']:
            path = checked_path(root, row['path'], protected=cfg['protected_paths'])
            old = regular(path) if path.exists() else None
            require((digest(old) if old is not None else None) == row['base_sha256'], 'Target changed while model ran')
            identity = (path.stat().st_dev, path.stat().st_ino) if old is not None else None
            destinations.append((row, path, old, identity))
        write_json(directory / 'proposal.json', proposal)
        write_json(directory / 'before.json', {row['path']: old.decode() if old is not None else None for row, _, old, _ in destinations})
        for row, path, old, identity in destinations:
            def recheck():
                checked_path(root, row['path'], protected=cfg['protected_paths'])
                now = regular(path) if path.exists() else None
                now_identity = (path.stat().st_dev, path.stat().st_ino) if now is not None else None
                require(now == old and now_identity == identity, 'Target CAS changed before replace')
            atomic(path, row['content'].encode(), before_replace=recheck)
        result = {'schema': 'jevops.lean-refactor.router-task-result.v1', 'task_id': task_id, 'contract': contract, 'route': route,
                  'max_output_tokens': call_cfg['max_output_tokens'],
                  'files': {row['path']: digest(row['content'].encode()) for row, _, _, _ in destinations},
                  'artifact_sha256': {name: digest(regular(directory / name)) for name in
                                     ('request.json', 'packet.json', 'response.json', 'route.json', 'proposal.json', 'before.json', 'grok_cli_trace.jsonl')
                                     if (directory / name).exists()},
                  'validation': 'pending: the lane runs the real board Validation next',
                  'competition_eligible': False, **AUTH}
        write_json(directory / 'result.json', result)
        return result


def verify_task_receipt(root: Path, task_id: str) -> dict:
    """Read-only validation of the newest matching genuine router attempt."""
    root = root.resolve(strict=True)
    cfg = config(root)
    source = Path(cfg['accelerator_source']).resolve(strict=True)
    sys.path.insert(0, str(source))
    from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
    current_packet, _, contract = task_packet(root, cfg, task_id, parse_todo_blocks, allow_completed=True)
    call_cfg = effective_call_config(current_packet, cfg)
    calls = checked_path(root, cfg['runtime_root']) / 'router-calls'
    candidates = []
    if calls.exists():
        for directory in calls.iterdir():
            require(not directory.is_symlink(), 'Symlink call archive refused')
            if not directory.is_dir() or not directory.name.startswith(task_id + '-'): continue
            request = decode(regular(directory / 'request.json'))
            if request.get('contract') == contract and request.get('task_id') == task_id:
                require(type(request.get('call_ordinal')) is int, 'Missing reserved physical call ordinal')
                candidates.append((request['call_ordinal'], directory, request))
    require(candidates, 'No current source/input-bound router attempt')
    require(len({row[0] for row in candidates}) == len(candidates), 'Duplicate physical call ordinal')
    _, directory, request = max(candidates, key=lambda row: row[0])
    result = decode(regular(directory / 'result.json'))  # A newer failed attempt cannot reuse old success.
    require(result.get('schema') == 'jevops.lean-refactor.router-task-result.v1' and
            result.get('contract') == contract and result.get('task_id') == task_id and
            all(result.get(key) is False for key in AUTH), 'Router result contract/authority differs')
    artifacts = result.get('artifact_sha256', {})
    names = {'request.json', 'packet.json', 'response.json', 'route.json', 'proposal.json', 'before.json', 'grok_cli_trace.jsonl'}
    require(set(artifacts) == names, 'Complete actual router artifact bindings required')
    for name in names:
        require(digest(regular(directory / name)) == artifacts[name], 'Router artifact tampered: ' + name)
    packet = decode(regular(directory / 'packet.json'))
    require(semantic_fields(packet['fields']) == semantic_fields(current_packet['fields']) and
            semantic_fields(packet['goal_task']) == semantic_fields(current_packet['goal_task']), 'Archived task/DAG differs')
    proposal = validate_proposal(regular(directory / 'response.json').decode(), task_id, packet, cfg)
    require(proposal == decode(regular(directory / 'proposal.json')), 'Raw proposal/parsed proposal differs')
    route = decode(regular(directory / 'route.json'))
    child = route.get('child', {})
    trace = route.get('actual_trace', {})
    require(route == result['route'] and child.get('status') == 'ok' and child.get('exit_code') == 0
            and child.get('effective_provider') == 'grok_cli' and route.get('requested_model') == 'grok-4.7'
            and trace.get('provider') == 'grok_cli' and trace.get('model') == 'grok-4.7', 'Actual strict router route differs')
    actual_traces = [decode(line) for line in regular(directory / 'grok_cli_trace.jsonl').decode().splitlines()]
    require(actual_traces == [trace], 'Actual CLI trace archive differs')
    require(request.get('provider') == 'grok_cli' and request.get('model') == 'grok-4.7', 'Requested route differs')
    require(request.get('max_output_tokens') == result.get('max_output_tokens') ==
            route.get('requested_max_output_tokens') == call_cfg['max_output_tokens'], 'Actual requested token bound differs')
    expected_files = {row['path']: digest(row['content'].encode()) for row in proposal['files']}
    require(result.get('files') == expected_files, 'Result output manifest differs')
    for path, sha in expected_files.items():
        require(digest(regular(checked_path(root, path, protected=cfg['protected_paths']))) == sha, 'Actual proposed output changed')
    return {'valid': True, 'task_id': task_id, 'contract': contract, 'result_path': str(directory / 'result.json'),
            'result_sha256': digest(regular(directory / 'result.json')), 'model': 'grok-4.7', 'provider': 'grok_cli', **AUTH}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args(argv)
    require(re.fullmatch(r'JLR-[A-Z0-9-]+', args.task_id), 'Invalid JLR identity')
    try:
        print(json.dumps(run(args.repo_root, args.task_id, preflight=args.preflight), sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'failed': True, 'reason': str(exc), **AUTH}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
