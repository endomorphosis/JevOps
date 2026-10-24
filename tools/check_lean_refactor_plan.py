#!/usr/bin/env python3
"""Validate the reviewed JevOps campaign and source-bound task evidence.

This checker never calls a model, compiles a proof, edits a taskboard, or
promotes a candidate. Its contract workers execute only a restricted pure
Python feature API, with separate process/CPU/memory/output limits.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import re
import shlex
import stat
import subprocess
import sys
from typing import Any

PLAN = 'implementation_plan/lean_refactor_arena_20261024.goals.json'
BOARD = 'implementation_plan/lean_refactor_arena_20261024.todo.md'
CONFIG = 'config/lean_refactor_arena_20261024_supervisor.json'
RECEIPTS = 'data/lean_refactor_campaign_20261024/receipts'
SCHEMA = 'jevops.lean-refactor.campaign.v1'
AUTH = {'completion_authority': False, 'proof_authority': False, 'official_score': None}
STATUSES = {'planned', 'pending', 'todo', 'ready', 'running', 'in_progress', 'completed', 'done', 'blocked', 'failed', 'stuck'}
FEATURE_CONTRACTS = {'length_policy_v1', 'cache_identity_v1', 'safety_policy_v1'}
HEX = re.compile(r'[0-9a-f]{64}')


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def decode(raw: bytes | str) -> Any:
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('non-finite JSON: ' + x)))


def safe_path(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and 0 < len(relative) <= 512, 'bounded relative path required')
    path = PurePosixPath(relative)
    require(not path.is_absolute() and path.as_posix() == relative and
            all(p not in {'.', '..', '.git', '.env', '.ssh', '.venv', 'node_modules'}
                and not p.startswith('.') for p in path.parts), 'unsafe path: ' + relative)
    target = root / relative
    cursor = root
    for part in path.parts:
        cursor /= part
        require(not cursor.is_symlink(), 'symlink path is not an evidence/output boundary: ' + relative)
    require(target.resolve().is_relative_to(root.resolve()), 'path escapes project: ' + relative)
    return target


def regular(path: Path, limit: int = 8 * 1024 * 1024) -> bytes:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'bounded regular file required: ' + str(path))
    return path.read_bytes()


def strings(value: Any, name: str, *, empty: bool = False) -> list[str]:
    require(type(value) is list and (empty or value) and
            all(isinstance(x, str) and x.strip() == x and x for x in value), name + ' must be a string list')
    require(len(value) == len(set(value)), name + ' must be unique')
    return value


def csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(',') if x.strip()]


def strict_board(text: str):
    blocks, current, fields, line = [], None, {}, 0
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.startswith('## JLR-'):
            if current:
                blocks.append((*current, line, fields))
            match = re.fullmatch(r'## (JLR-[A-Z0-9-]+)\s+(.+)', raw)
            require(match is not None, 'malformed task heading')
            current, fields, line = (match[1], match[2]), {}, number
        elif current and raw.strip().startswith('- ') and ':' in raw:
            key, value = raw.strip()[2:].split(':', 1)
            key = re.sub(r'[^a-z0-9]+', '_', key.strip().lower()).strip('_')
            require(key not in fields, 'duplicate board field: ' + key)
            fields[key] = value.strip()
    if current:
        blocks.append((*current, line, fields))
    return blocks


def actual_parser(root: Path):
    """Prefer the production parser; absence is reported, never simulated."""
    cfg_path = root / CONFIG
    if cfg_path.exists():
        source = Path(decode(regular(cfg_path))['accelerator_source']).resolve()
    else:
        source = root.parent / 'external/ipfs_accelerate'
    if not (source / 'ipfs_accelerate_py').is_dir():
        return None
    sys.path.insert(0, str(source))
    try:
        from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
    except ModuleNotFoundError:
        return None
    module = sys.modules[parse_todo_blocks.__module__]
    require(Path(module.__file__).resolve().is_relative_to(source), 'foreign production todo parser')
    return parse_todo_blocks


def _dag(nodes: dict[str, list[str]], name: str):
    state = {}
    def visit(key):
        require(state.get(key) != 1, name + ' contains a cycle at ' + key)
        if state.get(key) == 2:
            return
        state[key] = 1
        for dep in nodes[key]:
            require(dep in nodes, name + ' has unknown dependency: ' + dep)
            visit(dep)
        state[key] = 2
    for key in nodes:
        visit(key)


def _policy(root: Path, plan: dict):
    cfg = decode(regular(root / CONFIG))
    require(cfg.get('schema') == 'jevops.lean-refactor-supervisor.v1', 'unknown supervisor config')
    require(cfg.get('provider') == 'grok_cli' and cfg.get('model') == 'grok-4.7' and
            cfg.get('allow_local_fallback') is False and cfg.get('allow_cross_provider_fallback') is False,
            'strict Grok 4.7 router route without fallback required')
    for name, cap in [('max_calls', 24), ('max_task_calls_per_contract', 3),
                      ('provider_timeout_seconds', 120), ('max_output_tokens', 4096)]:
        require(type(cfg.get(name)) is int and 0 < cfg[name] <= cap, 'invalid router cap: ' + name)
    require(cfg.get('competition_eligible') is False, 'research CLI cannot claim official eligibility')
    policy = plan.get('policy', {})
    require(type(policy) is dict, 'policy must be an object')
    for name, expected in {'provider': 'grok_cli', 'model': 'grok-4.7', 'strict_provider': True,
                           'allow_local_fallback': False, 'allow_cross_provider_fallback': False}.items():
        require(policy.get(name) == expected and type(policy.get(name)) is type(expected),
                'campaign route policy mismatch: ' + name)
    for name in ('automatic_promotion', 'model_proof_authority'):
        require(policy.get(name) is False, name + ' must explicitly be false')
    require(type(policy.get('max_task_attempts')) is int and 0 < policy['max_task_attempts'] <= 3,
            'explicit retry ceiling required')
    require(policy.get('max_inflight_gpu') == 1 and type(policy.get('max_inflight_gpu')) is int,
            'exactly one GPU owner/in-flight job allowed')
    return cfg


def load_plan(root: Path, *, plan_path: str = PLAN, board_path: str = BOARD, parser=None):
    root = root.resolve(strict=True)
    plan = decode(regular(safe_path(root, plan_path)))
    require(type(plan) is dict and plan.get('schema') == SCHEMA, 'unknown campaign schema')
    goals, tasks = plan.get('goals'), plan.get('tasks')
    require(type(goals) is list and goals and type(tasks) is list and tasks, 'nonempty goals/tasks required')
    goal_map, task_map = {}, {}
    for goal in goals:
        require(type(goal) is dict and re.fullmatch(r'JLR-G\d{3,}', str(goal.get('id', ''))), 'invalid goal')
        require(goal['id'] not in goal_map, 'duplicate goal id')
        for key in ('title', 'objective', 'acceptance'):
            require(isinstance(goal.get(key), str) and goal[key].strip(), 'goal missing ' + key)
        goal_map[goal['id']] = goal
    root_goal = plan.get('root_goal_id')
    require(root_goal in goal_map and goal_map[root_goal].get('parent_goal_id') is None, 'root goal must exist and have no parent')
    goal_edges = {}
    for key, goal in goal_map.items():
        parent = goal.get('parent_goal_id')
        require(key == root_goal or parent in goal_map, 'every subgoal needs a known parent')
        goal_edges[key] = [] if parent is None else [parent]
    _dag(goal_edges, 'goal DAG')
    cfg = _policy(root, plan)
    for task in tasks:
        require(type(task) is dict and re.fullmatch(r'JLR-\d{3,}', str(task.get('id', ''))), 'invalid task identity')
        key = task['id']
        require(key not in task_map, 'duplicate task id: ' + key)
        require(task.get('goal_id') in goal_map, 'task goal missing: ' + key)
        require(task.get('mode') in {'router', 'deterministic'}, 'unknown task mode')
        for name in ('title', 'resource_class', 'deterministic_command', 'validation', 'acceptance'):
            require(isinstance(task.get(name), str) and task[name].strip(), key + ' missing ' + name)
        strings(task.get('depends_on'), 'dependencies', empty=True)
        outputs = strings(task.get('outputs'), 'outputs')
        require(strings(task.get('predicted_files'), 'predicted files') == outputs, 'ordered outputs/predicted files differ')
        for path in outputs:
            safe_path(root, path)
            require(path not in {PLAN, BOARD, CONFIG} and not path.startswith(('config/', 'tools/', 'tests/')),
                    'task cannot overwrite execution/validation/control files')
            prefixes = ('jevops/', 'implementation_plan/proposals/') if task['mode'] == 'router' else ('data/', 'implementation_plan/proposals/')
            require(path.startswith(prefixes), 'unsafe task output namespace: ' + path)
        bounds = task.get('bounds')
        require(type(bounds) is dict, 'task bounds missing')
        require(type(bounds.get('timeout_seconds')) is int and 0 < bounds['timeout_seconds'] <= 7200,
                'finite task timeout ceiling required')
        for name, cap in [('router_calls', 3), ('max_output_tokens', 4096)]:
            require(type(bounds.get(name)) is int and 0 <= bounds[name] <= cap, 'invalid task ' + name)
        require((bounds['router_calls'] > 0 and bounds['max_output_tokens'] > 0) == (task['mode'] == 'router'),
                'model budget disagrees with task mode')
        wp = task.get('work_package')
        require(type(wp) is dict, 'executable work package missing')
        for name in ('action', 'hypothesis', 'experiment', 'stop_rule'):
            require(isinstance(wp.get(name), str) and wp[name].strip(), 'work package missing ' + name)
        require(isinstance(wp.get('inputs'), list) and isinstance(wp.get('metrics'), list) and wp['metrics'],
                'explicit work package inputs/metrics required')
        strings(wp['metrics'], 'work package metrics')
        strings(wp['inputs'], 'work package inputs', empty=True)
        if wp['action'] != 'planned_experiment':
            for relative in wp['inputs']:
                safe_path(root, relative)
        if wp['action'] == 'planned_experiment':
            require(task.get('initial_status') == 'planned' and task['mode'] == 'deterministic',
                    'nonexecutable experiment must be explicitly planned')
            gates = task.get('activation_requires', wp.get('activation_requires'))
            strings(gates, 'planned experiment activation requirements')
        else:
            require(wp['action'] in {'host_inventory', 'command', 'scoring_parity', 'native_smoke',
                                     'feature_contract', 'proposal_review'}, 'unknown work package action')
        expected_worker = ('tools/run_lean_refactor_router_task.py' if task['mode'] == 'router'
                           else 'tools/run_lean_refactor_campaign.py')
        producer = shlex.split(task['deterministic_command'])
        validation = shlex.split(task['validation'])
        require(len(producer) == 4 and Path(producer[0]).name.startswith('python')
                and producer[1:] == [expected_worker, '--task-id', key],
                'exact reviewed bounded worker argv required')
        require(len(validation) == 4 and Path(validation[0]).name.startswith('python')
                and validation[1:] == ['tools/check_lean_refactor_plan.py', '--validate-task', key],
                'exact independent source-bound task validation argv required')
        task_map[key] = task
    _dag({key: row['depends_on'] for key, row in task_map.items()}, 'task DAG')
    raw_board = regular(safe_path(root, board_path)).decode()
    blocks = strict_board(raw_board)
    require(len(blocks) == len(task_map) and {b[0] for b in blocks} == set(task_map), 'board/JSON task population differs')
    use_parser = parser if parser is not None else actual_parser(root)
    if use_parser is not None:
        require(use_parser(raw_board, task_header_prefix='## JLR-') == blocks,
                'production todo parser disagrees with strict projection')
    board_map = {item[0]: item for item in blocks}
    for key, row in task_map.items():
        _, title, _, fields = board_map[key]
        require(title == row['title'], 'board/JSON title mismatch: ' + key)
        require(fields.get('status', '').lower() in STATUSES, 'unknown board status: ' + key)
        if row['work_package']['action'] == 'planned_experiment':
            require(fields['status'].lower() == 'planned', 'unreviewed experiment cannot be activated/completed')
        for name in ('goal_id', 'resource_class', 'priority', 'deterministic_command', 'validation', 'acceptance'):
            require(fields.get(name) == str(row.get(name, '')), 'board/JSON field mismatch: ' + key + '/' + name)
        for name in ('depends_on', 'outputs', 'predicted_files'):
            require(csv(fields.get(name, '')) == row[name], 'board/JSON list mismatch: ' + key + '/' + name)
        require(fields.get('implementation_timeout_seconds') == str(row['bounds']['timeout_seconds']), 'board timeout mismatch')
        require(fields.get('provider_role') == ('grok-only' if row['mode'] == 'router' else 'deterministic'), 'board provider role mismatch')
        if row['mode'] == 'router':
            require(fields.get('model') == 'grok-4.7', 'board router model mismatch')
            require(csv(fields.get('inputs', '')) == row['work_package']['inputs'], 'router board/JSON input bindings differ')
    ready = [key for key, row in task_map.items() if board_map[key][3]['status'].lower() in {'pending', 'todo', 'ready'}
             and all(board_map[d][3]['status'].lower() in {'completed', 'done'} for d in row['depends_on'])]
    for index, first in enumerate(ready):
        for second in ready[index + 1:]:
            for a in task_map[first]['predicted_files']:
                for b in task_map[second]['predicted_files']:
                    require(not (a == b or a.startswith(b + '/') or b.startswith(a + '/')),
                            'ready tasks have overlapping write paths: ' + first + '/' + second)
    return {'plan': plan, 'tasks': task_map, 'goals': goal_map, 'board': board_map, 'config': cfg,
            'ready': ready, 'production_parser_used': use_parser is not None}


def task_binding(root: Path, campaign: dict, task: dict) -> dict:
    wp = task['work_package']
    inputs = {}
    for relative in strings(wp['inputs'], 'task inputs', empty=True):
        inputs[relative] = digest(regular(safe_path(root, relative)))
    sources = {path: digest(regular(safe_path(root, path))) for path in
               ('tools/check_lean_refactor_plan.py', 'tools/run_lean_refactor_campaign.py')}
    action = wp['action']
    extra = []
    if action == 'scoring_parity':
        extra = ['jevops/arena.py', 'jevops/proof_trust.py', 'jevops/lean.py',
                 'papers/completion/lean_refactor_arena/space/leaderboard.py']
    elif action == 'native_smoke':
        extra = ['jevops/' + path for path in ('proof_trust.py', 'arena_lean.py', 'arena.py', 'lean.py',
                 'arena_isolation.py', 'arena_staging.py', 'seals.py', 'proof_ca.py', 'lean/ArenaCheck.lean')]
        binary = Path.home() / '.elan/toolchains/leanprover--lean4---v4.31.0/bin/lean'
        require(binary.is_file(), 'exact v4.31.0 native compiler unavailable')
        inputs['native_compiler:' + str(binary.resolve())] = digest(regular(binary.resolve(), 256 * 1024 * 1024))
    elif action == 'command':
        command = wp.get('command', [])
        if len(command) >= 3 and command[1] == '-m' and command[2] == 'jevops.arena':
            extra = ['jevops/arena.py', 'jevops/proof_trust.py', 'jevops/lean.py']
        elif len(command) >= 2 and command[1].startswith('papers/'):
            script = safe_path(root, command[1])
            # These small, reviewed local harnesses have dynamic/lazy imports.
            # Bind their complete Python directory plus JevOps adapters, never runtime caches.
            extra = [str(p.relative_to(root)) for p in sorted(script.parent.glob('*.py'))]
            extra += ['jevops/arena.py', 'jevops/lean.py', 'jevops/proof_trust.py', 'jevops/leanstral.py']
    for relative in extra:
        sources[relative] = digest(regular(safe_path(root, relative)))
    # Bind raw corpus/heartbeat inputs even when command defaults supply their paths.
    if action in {'command', 'scoring_parity'}:
        for relative in ('papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl',
                         'papers/completion/lean_refactor_arena/space/benchmark_heartbeats.jsonl'):
            inputs[relative] = digest(regular(safe_path(root, relative)))
    return {'task_sha256': digest(encoded(task)), 'inputs': inputs, 'sources': sources,
            'config_sha256': digest(regular(safe_path(root, CONFIG))),
            'goal_sha256': digest(encoded(campaign['goals'][task['goal_id']]))}


def restricted_module(raw: bytes) -> ast.Module:
    require(len(raw) <= 49152, 'feature module exceeds limit')
    tree = ast.parse(raw)
    allowed_imports = {'json', 'hashlib', 'math'}
    public_attributes = {'get', 'items', 'keys', 'values', 'copy', 'append', 'extend', 'pop', 'setdefault',
                         'sort', 'count', 'index', 'encode', 'decode', 'strip', 'lstrip', 'rstrip', 'lower',
                         'upper', 'replace', 'split', 'join', 'startswith', 'endswith', 'isdecimal',
                         'dumps', 'loads', 'sha256', 'hexdigest', 'digest', 'isfinite', 'isnan', 'isinf'}
    denied = {'open', 'exec', 'eval', 'compile', 'input', 'globals', 'locals', 'getattr', 'setattr', 'delattr',
              '__import__', 'breakpoint', 'exit', 'quit', 'help', 'license', 'credits', 'copyright',
              'vars', 'object', 'print'}
    for top in tree.body:
        require(isinstance(top, (ast.FunctionDef, ast.Import, ast.ImportFrom)) or
                isinstance(top, ast.Expr) and isinstance(top.value, ast.Constant) and isinstance(top.value.value, str),
                'feature module must contain pure functions/imports only')
        if isinstance(top, ast.FunctionDef):
            require(not top.decorator_list and not top.args.defaults and not top.args.kw_defaults,
                    'feature module cannot execute decorators/default expressions')
    for node in ast.walk(tree):
        require(not isinstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await, ast.With, ast.AsyncWith,
                                      ast.ClassDef, ast.Global, ast.Nonlocal, ast.Delete)),
                'unsupported side-effecting/unbounded feature construct')
        if isinstance(node, ast.Import):
            require(all(x.name in allowed_imports for x in node.names), 'feature import not allowed')
        if isinstance(node, ast.ImportFrom):
            require(node.level == 0 and node.module in allowed_imports and all(x.name in public_attributes for x in node.names),
                    'feature import not allowed')
        if isinstance(node, ast.Name):
            require(node.id not in denied and not node.id.startswith('__'), 'feature escape name refused')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'type':
            require(len(node.args) == 1 and not node.keywords, 'dynamic class construction refused')
        if isinstance(node, ast.Attribute):
            require(node.attr in public_attributes, 'feature attribute/capability escape refused')
    return tree


def exercise_feature(module, contract: str) -> dict:
    """Fixed behavioral oracle; model-supplied tests or assertions are ignored."""
    require(contract in FEATURE_CONTRACTS, 'unknown feature contract')
    rng, checks = random.Random(20261024), 0
    def check(condition):
        nonlocal checks
        require(condition, 'functional feature contract failed: ' + contract)
        checks += 1
    if contract == 'length_policy_v1':
        function = module.select_candidate
        check(function([]) is None)
        for _ in range(80):
            rows = [{'id': f'r{i:03}', 'tokens': rng.randrange(1, 1000), 'heartbeats': rng.randrange(100000),
                     'verified': rng.choice([True, False]), 'axioms_preserved': rng.choice([True, False])}
                    for i in range(rng.randrange(1, 15))]
            good = [r for r in rows if r['verified'] is True and r['axioms_preserved'] is True]
            expected = min(good, key=lambda r: (r['tokens'], r['heartbeats'], r['id']))['id'] if good else None
            snapshot = encoded(rows)
            check(function(rows) == expected)
            check(encoded(rows) == snapshot)
        valid = {'id': 'valid', 'tokens': 10, 'heartbeats': 12, 'verified': True, 'axioms_preserved': True}
        for field, value in [('tokens', True), ('tokens', -1), ('tokens', 1.5), ('heartbeats', '0'),
                             ('verified', 1), ('axioms_preserved', 1)]:
            bad = {**valid, field: value, 'id': 'bad'}
            check(function([bad, valid]) == 'valid')
        check(function([{**valid, 'id': 'bad', 'tokens': 0}, valid]) == 'valid')
        check(function([None, {}, 42, 'row', valid]) == 'valid')
        check(function([{**valid, 'id': 'b'}, {**valid, 'id': 'a'}]) == 'a')
    elif contract == 'cache_identity_v1':
        function = module.cache_key
        base = {'target': 't', 'statement': 'theorem t : True', 'lean': '4.29.1', 'dependencies': ['abc'],
                'verifier': 'v1', 'axiom_policy': []}
        source = 'by\n  have s := "a  b"\n  trivial'
        snapshot = encoded(base)
        expected = digest(encoded({'context': base, 'source': source}))
        check(function(base, source) == expected)
        check(encoded(base) == snapshot)
        check(function(dict(reversed(list(base.items()))), source) == function(base, source))
        for key in base:
            check(function({**base, key: ['different']}, source) != function(base, source))
        for text in (source + ' ', source.replace('a  b', 'a b'), source + '\n', source.replace('trivial', 'rfl')):
            check(function(base, text) != function(base, source))
        for _ in range(80):
            context = {**base, 'nonce': rng.getrandbits(128)}
            text = source + str(rng.getrandbits(128))
            snapshot = encoded(context)
            expected = digest(encoded({'context': context, 'source': text}))
            check(function(context, text) == expected)
            check(encoded(context) == snapshot)
    else:
        function = module.accept_candidate
        base = {key: True for key in ('statement_preserved', 'type_preserved', 'all_pins_verified', 'axioms_subset')}
        base.update(has_sorry=False, unsafe=False)
        snapshot = encoded(base)
        check(function(base) is True)
        check(encoded(base) == snapshot)
        for key in base:
            for value in (not base[key], None, 0, 1, 'true'):
                check(function({**base, key: value}) is False)
            check(function({k: v for k, v in base.items() if k != key}) is False)
        for bad in (None, [], {}, 'verified', True):
            check(function(bad) is False)
    return {'contract': contract, 'checks': checks, 'passed': True, **AUTH}


def validate_router_output(root: Path, task: dict) -> dict:
    spec = importlib.util.spec_from_file_location('_reviewed_jevops_router_bridge', root / 'tools/run_lean_refactor_router_task.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    require(hasattr(bridge, 'verify_task_receipt'), 'router bridge lacks independent source-bound receipt verifier')
    proof = bridge.verify_task_receipt(root, task['id'])
    require(isinstance(proof, dict), 'router receipt verifier returned no evidence')
    contract = task['work_package'].get('contract')
    if contract in FEATURE_CONTRACTS:
        require(len(task['outputs']) == 1 and task['outputs'][0].endswith('.py'), 'one pure feature module required')
        path = safe_path(root, task['outputs'][0])
        restricted_module(regular(path))
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--feature-worker', contract, '--module', str(path)]
        result = subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=8, check=False, env={'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1'})
        require(result.returncode == 0 and len(result.stdout) < 65536 and len(result.stderr) < 65536,
                'isolated functional feature validation failed')
        return {'router_receipt': proof, 'behavior': decode(result.stdout), **AUTH}
    require(contract in {'advisory_review_v1', 'review_v1', 'proposal_review_v1'} and len(task['outputs']) == 1,
            'router artifact needs a fixed reviewed semantic contract')
    value = decode(regular(safe_path(root, task['outputs'][0]), 49152))
    required = {'schema', 'task_id', 'risks', 'actions', 'acceptance_boundaries', 'proposal_only', 'needs_native_verification'}
    require(type(value) is dict and required <= set(value) <= required | {'citations', 'source_paths'}
            and value['schema'] == 'jevops.lean-refactor.review.v1'
            and value['task_id'] == task['id'] and value['proposal_only'] is True
            and value['needs_native_verification'] is True, 'advisory review schema/authority mismatch')
    for key in ('risks', 'actions', 'acceptance_boundaries'):
        strings(value[key], 'advisory ' + key)
        require(len(value[key]) <= 32 and all(len(x) <= 2000 for x in value[key]), 'review exceeds bounds')
    for key in {'citations', 'source_paths'} & set(value):
        strings(value[key], key, empty=True)
    return {'router_receipt': proof, 'advisory_review_valid': True, **AUTH}


def validate_task(root: Path, task_id: str, campaign=None) -> dict:
    campaign = campaign or load_plan(root)
    require(task_id in campaign['tasks'], 'unknown task')
    task = campaign['tasks'][task_id]
    if task['mode'] == 'router':
        return validate_router_output(root, task)
    latest = decode(regular(safe_path(root, RECEIPTS + '/' + task_id + '.json')))
    require(latest.get('schema') == 'jevops.lean-refactor.task-receipt.v1' and latest.get('task_id') == task_id,
            'receipt identity mismatch')
    require(latest.get('binding') == task_binding(root, campaign, task), 'stale task/source/input receipt binding')
    require(latest.get('exit_code') == 0 and type(latest.get('exit_code')) is int and latest.get('timed_out') is False,
            'producer did not genuinely complete successfully')
    require(latest.get('completion_authority') is False and latest.get('proof_authority') is False,
            'receipt cannot self-authorize completion/proofs')
    require(isinstance(latest.get('started_at'), str) and isinstance(latest.get('finished_at'), str)
            and type(latest.get('duration_seconds')) in (int, float) and math.isfinite(latest['duration_seconds'])
            and 0 <= latest['duration_seconds'] <= task['bounds']['timeout_seconds'] + 30,
            'real execution interval missing')
    require(set(latest.get('outputs', {})) == set(task['outputs']), 'receipt output population differs')
    for path, sha in latest['outputs'].items():
        require(digest(regular(safe_path(root, path))) == sha, 'output changed after producer: ' + path)
    for row in latest.get('logs', []):
        require(digest(regular(safe_path(root, row['path']))) == row['sha256'], 'execution log changed')
    run_path = latest.get('archive_path')
    require(isinstance(run_path, str) and decode(regular(safe_path(root, run_path))) == latest, 'original run receipt absent/changed')
    require(latest.get('command') == task['work_package'].get('command', []), 'producer argv differs from reviewed work package')
    action = task['work_package']['action']
    data = decode(regular(safe_path(root, task['outputs'][0])))
    if action == 'host_inventory':
        require(data.get('schema') == 'jevops.lean-refactor.host-inventory.v1' and data.get('proofs_compiled') == 0
                and isinstance(data.get('hardware'), dict) and isinstance(data.get('disk'), dict)
                and set(data.get('tools', {})) == {'lean', 'lake', 'nvidia-smi'}, 'inventory semantic contract failed')
    elif action in {'command', 'scoring_parity'}:
        require(data.get('passed') is True and data.get('proof_authority') is False, 'command semantic validation absent')
        runner_spec = importlib.util.spec_from_file_location('_reviewed_campaign_runner', root / 'tools/run_lean_refactor_campaign.py')
        runner = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(runner)
        if action == 'command':
            require(len(latest.get('executions', [])) == 1, 'one real reviewed subprocess record required')
            execution = latest['executions'][0]
            argv, kind = runner.checked_command(task['work_package']['command'])
            require(execution.get('argv') == argv and execution.get('exit_code') == 0 and
                    execution.get('timed_out') is False, 'actual subprocess argv/exit mismatch')
            recomputed = runner.command_semantics(kind, regular(safe_path(root, execution['stdout']['path'])))
            require(data == recomputed, 'command result differs from authenticated raw stdout')
        else:
            require(data == runner.scoring_parity(root), 'scoring parity behavioral replay failed')
    elif action == 'native_smoke':
        require(data.get('native_compiler_exit') == 0 and data.get('axiom_audit_passed') is True
                and data.get('target') == 'arena_smoke' and data.get('benchmark_proofs_verified') == 0,
                'actual native smoke/axiom check missing')
        runner_spec = importlib.util.spec_from_file_location('_reviewed_campaign_runner', root / 'tools/run_lean_refactor_campaign.py')
        runner = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(runner)
        require(latest['command'] == runner.NATIVE_COMMAND and len(latest.get('executions', [])) == 1,
                'reviewed native subprocess record required')
        execution = latest['executions'][0]
        require(execution.get('argv') == [sys.executable, *runner.NATIVE_COMMAND[1:]] and
                execution.get('exit_code') == 0 and execution.get('timed_out') is False, 'native argv/exit mismatch')
        require(data == runner.native_semantics(root, regular(safe_path(root, execution['stdout']['path']))),
                'native result differs from actual raw stdout')
    else:
        raise ValueError('unsupported deterministic evidence action: ' + action)
    return {'task_id': task_id, 'valid': True, 'receipt_sha256': digest(encoded(latest)), **AUTH}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', '--check-all', action='store_true')
    modes.add_argument('--validate-task')
    modes.add_argument('--feature-worker', choices=sorted(FEATURE_CONTRACTS), help=argparse.SUPPRESS)
    parser.add_argument('--module', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.feature_worker:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
            raw = regular(args.module, 49152)
            tree = restricted_module(raw)
            namespace = {'__name__': '_restricted_feature'}
            exec(compile(tree, str(args.module), 'exec'), namespace)
            from types import SimpleNamespace
            result = exercise_feature(SimpleNamespace(**namespace), args.feature_worker)
        else:
            root = args.repo_root.resolve(strict=True)
            campaign = load_plan(root)
            result = (validate_task(root, args.validate_task, campaign) if args.validate_task else
                      {'valid': True, 'tasks': len(campaign['tasks']), 'goals': len(campaign['goals']),
                       'ready': campaign['ready'], 'production_parser_used': campaign['production_parser_used'], **AUTH})
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'valid': False, 'reason': str(exc), **AUTH}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
