"""Campaign boundaries exercised with private artifacts; no model/native jobs."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import check_lean_refactor_plan as check
import run_lean_refactor_campaign as runner


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if not isinstance(value, str) else value)


def board_for(plan, statuses=None):
    chunks = []
    for row in plan['tasks']:
        fields = {'Status': (statuses or {}).get(row['id'], row.get('initial_status', 'pending')),
                  'Goal id': row['goal_id'], 'Resource class': row['resource_class'], 'Priority': row['priority'],
                  'Depends on': ', '.join(row['depends_on']), 'Outputs': ', '.join(row['outputs']),
                  'Predicted files': ', '.join(row['predicted_files']), 'Deterministic command': row['deterministic_command'],
                  'Validation': row['validation'], 'Acceptance': row['acceptance'],
                  'Implementation timeout seconds': row['bounds']['timeout_seconds'],
                  'Provider role': 'grok-only' if row['mode'] == 'router' else 'deterministic'}
        if row['mode'] == 'router':
            fields['Model'] = 'grok-4.7'
        chunks.append('## ' + row['id'] + ' ' + row['title'] + '\n' +
                      '\n'.join('- ' + key + ': ' + str(value) for key, value in fields.items()))
    return '\n\n'.join(chunks) + '\n'


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    for name in ('check_lean_refactor_plan.py', 'run_lean_refactor_campaign.py'):
        (root / 'tools').mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'tools' / name, root / 'tools' / name)
    cfg = {'schema': 'jevops.lean-refactor-supervisor.v1', 'provider': 'grok_cli', 'model': 'grok-4.7',
           'allow_local_fallback': False, 'allow_cross_provider_fallback': False, 'max_calls': 24,
           'max_task_calls_per_contract': 3, 'provider_timeout_seconds': 120, 'max_output_tokens': 4096,
           'competition_eligible': False, 'accelerator_source': str(tmp_path / 'absent')}
    task = {'id': 'JLR-001', 'title': 'Observe host without proof claims', 'goal_id': 'JLR-G001',
            'initial_status': 'pending', 'depends_on': [], 'mode': 'deterministic', 'resource_class': 'cpu-small',
            'priority': 10, 'outputs': ['data/lean_refactor_campaign_20261024/JLR-001.inventory.json'],
            'predicted_files': ['data/lean_refactor_campaign_20261024/JLR-001.inventory.json'],
            'deterministic_command': 'python tools/run_lean_refactor_campaign.py --task-id JLR-001',
            'validation': 'python tools/check_lean_refactor_plan.py --validate-task JLR-001',
            'acceptance': 'Actual bounded inventory; unavailable tools stay unavailable; zero compiled proofs.',
            'bounds': {'timeout_seconds': 60, 'router_calls': 0, 'max_output_tokens': 0},
            'work_package': {'action': 'host_inventory', 'hypothesis': 'Measure current capabilities.',
                             'inputs': [], 'experiment': 'Bounded tool probes.', 'metrics': ['tool availability'],
                             'stop_rule': 'Finite probe deadlines; no autostart.'}}
    plan = {'schema': check.SCHEMA, 'root_goal_id': 'JLR-G000',
            'policy': {'max_task_attempts': 3, 'max_inflight_gpu': 1, 'automatic_promotion': False,
                       'model_proof_authority': False, 'provider': 'grok_cli', 'model': 'grok-4.7',
                       'strict_provider': True, 'allow_local_fallback': False, 'allow_cross_provider_fallback': False},
            'goals': [{'id': 'JLR-G000', 'parent_goal_id': None, 'title': 'Root', 'objective': 'Correct refactoring', 'acceptance': 'Real proof checks'},
                      {'id': 'JLR-G001', 'parent_goal_id': 'JLR-G000', 'title': 'Baseline', 'objective': 'Observe inputs', 'acceptance': 'No fabricated evidence'}],
            'tasks': [task]}
    write(root, check.CONFIG, cfg)
    write(root, check.PLAN, plan)
    write(root, check.BOARD, board_for(plan))
    return root, plan


def save_plan(root, plan, statuses=None):
    write(root, check.PLAN, plan)
    write(root, check.BOARD, board_for(plan, statuses))


def test_valid_projection_uses_actual_parser_when_injected(campaign):
    root, _ = campaign
    called = []
    def parser(text, **kwargs):
        called.append(kwargs)
        return check.strict_board(text)
    actual = check.load_plan(root, parser=parser)
    assert actual['ready'] == ['JLR-001'] and actual['production_parser_used'] is True
    assert called == [{'task_header_prefix': '## JLR-'}]


@pytest.mark.parametrize('mutation', ['duplicate_task', 'task_cycle', 'unknown_dependency', 'goal_cycle',
                                    'unknown_goal', 'field_drift', 'duplicate_field', 'route_fallback',
                                    'unbounded_timeout', 'model_authority', 'unsafe_output'])
def test_plan_refuses_real_projection_policy_and_graph_errors(campaign, mutation):
    root, plan = campaign
    task = plan['tasks'][0]
    if mutation == 'duplicate_task': plan['tasks'].append(copy.deepcopy(task))
    elif mutation == 'task_cycle': task['depends_on'] = ['JLR-001']
    elif mutation == 'unknown_dependency': task['depends_on'] = ['JLR-999']
    elif mutation == 'goal_cycle': plan['goals'][1]['parent_goal_id'] = 'JLR-G001'
    elif mutation == 'unknown_goal': task['goal_id'] = 'JLR-G999'
    elif mutation == 'unbounded_timeout': task['bounds']['timeout_seconds'] = 999999999
    elif mutation == 'model_authority': plan['policy']['model_proof_authority'] = True
    elif mutation == 'unsafe_output': task['outputs'] = task['predicted_files'] = ['../escaped.json']
    save_plan(root, plan)
    if mutation == 'field_drift':
        path = root / check.BOARD
        path.write_text(path.read_text().replace('- Priority: 10', '- Priority: 11'))
    elif mutation == 'duplicate_field':
        path = root / check.BOARD
        path.write_text(path.read_text() + '- Status: completed\n')
    elif mutation == 'route_fallback':
        cfg = check.decode((root / check.CONFIG).read_bytes())
        cfg['allow_cross_provider_fallback'] = True
        write(root, check.CONFIG, cfg)
    with pytest.raises(ValueError): check.load_plan(root)


def test_ready_write_conflicts_rejected_but_dependency_serialization_valid(campaign):
    root, plan = campaign
    second = copy.deepcopy(plan['tasks'][0]); second['id'] = 'JLR-002'
    second['deterministic_command'] = second['deterministic_command'].replace('001', '002')
    second['validation'] = second['validation'].replace('001', '002')
    plan['tasks'].append(second)
    save_plan(root, plan)
    with pytest.raises(ValueError, match='overlapping'): check.load_plan(root)
    second['depends_on'] = ['JLR-001']
    save_plan(root, plan)
    assert check.load_plan(root)['ready'] == ['JLR-001']


def test_planned_experiments_ingested_but_not_executable_or_selectable(campaign):
    root, plan = campaign
    task = plan['tasks'][0]
    task['initial_status'] = 'planned'; task['work_package']['action'] = 'planned_experiment'
    task['activation_requires'] = ['Exact native reference bindings and reviewed argv']
    save_plan(root, plan)
    loaded = check.load_plan(root)
    assert loaded['ready'] == []
    with pytest.raises(ValueError, match='planned'): runner.run_task(root, 'JLR-001', campaign=loaded)
    save_plan(root, plan, {'JLR-001': 'completed'})
    with pytest.raises(ValueError, match='cannot be activated'): check.load_plan(root)


def test_symlink_outputs_and_duplicate_json_are_not_accepted(campaign, tmp_path):
    root, _ = campaign
    outside = tmp_path / 'outside'; outside.mkdir()
    (root / 'data').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'): check.load_plan(root)
    with pytest.raises(ValueError, match='duplicate'): check.decode('{"schema":1,"schema":2}')


def test_host_inventory_receipt_binding_and_natural_status_progress(campaign, monkeypatch):
    root, plan = campaign
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    loaded = check.load_plan(root)
    receipt = runner.run_task(root, 'JLR-001', campaign=loaded)
    assert receipt['exit_code'] == 0 and receipt['executions'] == []
    inventory = check.decode((root / plan['tasks'][0]['outputs'][0]).read_bytes())
    assert inventory['proofs_compiled'] == 0 and all(not row['available'] for row in inventory['tools'].values())
    assert check.validate_task(root, 'JLR-001')['valid']
    save_plan(root, plan, {'JLR-001': 'completed'})
    assert check.validate_task(root, 'JLR-001')['valid']
    (root / 'tools/run_lean_refactor_campaign.py').write_text('# changed producer\n')
    with pytest.raises(ValueError, match='source/input'): check.validate_task(root, 'JLR-001')


def test_tampered_output_and_failed_latest_receipt_do_not_reuse_old_success(campaign, monkeypatch):
    root, plan = campaign
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    runner.run_task(root, 'JLR-001')
    write(root, plan['tasks'][0]['outputs'][0], {'fake': True})
    with pytest.raises(ValueError, match='output changed'): check.validate_task(root, 'JLR-001')
    runner.run_task(root, 'JLR-001')
    latest = root / check.RECEIPTS / 'JLR-001.json'
    value = check.decode(latest.read_bytes()); value['exit_code'] = 1
    write(root, str(latest.relative_to(root)), value)
    with pytest.raises(ValueError, match='genuinely'): check.validate_task(root, 'JLR-001')


@pytest.mark.parametrize('argv', [['sh', '-c', 'true'], ['python', '-c', 'print(1)'],
                                ['python', '-m', 'jevops.arena', '--calibrate', '--surprise'],
                                ['python', 'tools/unreviewed.py']])
def test_arbitrary_shell_code_or_unreviewed_argv_refused(argv):
    with pytest.raises(ValueError): runner.checked_command(argv)


def test_actual_subprocess_failure_and_timeout_are_preserved(tmp_path):
    failed = runner.run_process([sys.executable, '-c', 'import sys; print("real failure"); sys.exit(7)'],
                                root=tmp_path, timeout=2, directory=tmp_path / 'failure')
    assert failed['exit_code'] == 7 and failed['stdout'].read_text() == 'real failure\n'
    timed = runner.run_process([sys.executable, '-c', 'import time; time.sleep(60)'],
                               root=tmp_path, timeout=.1, directory=tmp_path / 'timeout')
    assert timed['exit_code'] == 124 and timed['timed_out'] is True


LENGTH = '''def select_candidate(rows):
    good = [r for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)
        and type(r.get('tokens')) is int and r['tokens'] >= 1
        and type(r.get('heartbeats')) is int and r['heartbeats'] >= 0
        and r.get('verified') is True and r.get('axioms_preserved') is True]
    return min(good, key=lambda r: (r['tokens'], r['heartbeats'], r['id']))['id'] if good else None
'''
# No model-written lambdas: the reference uses a named pure key as required by the AST boundary.
LENGTH = LENGTH.replace('def select_candidate(rows):', "def ordering(r):\n    return (r['tokens'], r['heartbeats'], r['id'])\ndef select_candidate(rows):").replace("lambda r: (r['tokens'], r['heartbeats'], r['id'])", 'ordering')
CACHE = '''import json
import hashlib
def cache_key(context, source):
    return hashlib.sha256(json.dumps({'context':context,'source':source},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
'''
SAFETY = '''def accept_candidate(row):
    if not isinstance(row, dict):
        return False
    return all(row.get(k) is True for k in ['statement_preserved','type_preserved','all_pins_verified','axioms_subset']) and all(row.get(k) is False for k in ['has_sorry','unsafe'])
'''


@pytest.mark.parametrize('contract,source', [('length_policy_v1', LENGTH), ('cache_identity_v1', CACHE), ('safety_policy_v1', SAFETY)])
def test_real_pure_feature_behavior_and_isolated_worker(tmp_path, contract, source):
    path = tmp_path / 'feature.py'; path.write_text(source)
    check.restricted_module(source.encode())
    namespace = {}; exec(source, namespace)
    result = check.exercise_feature(SimpleNamespace(**namespace), contract)
    assert result['passed'] and result['checks'] >= 40
    actual = __import__('subprocess').run([sys.executable, str(ROOT / 'tools/check_lean_refactor_plan.py'),
                                        '--feature-worker', contract, '--module', str(path)], capture_output=True, timeout=10)
    assert actual.returncode == 0, actual.stderr.decode()


@pytest.mark.parametrize('source', ['import os\ndef x(): return os.getcwd()',
                                  'def x(): return open("secret").read()',
                                  'def x(): return (1).__class__',
                                  'import json\ndef x(): return json.codecs.open("secret")',
                                  'x = print("import side effect")',
                                  'def x(v=print("default side effect")): return v',
                                  'def x():\n while True: pass'])
def test_feature_side_effects_and_escape_constructs_refused(source):
    with pytest.raises(ValueError): check.restricted_module(source.encode())


def test_behavioral_contract_rejects_stub_confidence_and_whitespace_collapsing_cache():
    with pytest.raises(ValueError): check.exercise_feature(SimpleNamespace(select_candidate=lambda _: 'r000'), 'length_policy_v1')
    with pytest.raises(ValueError): check.exercise_feature(SimpleNamespace(accept_candidate=lambda _: True), 'safety_policy_v1')
    with pytest.raises(ValueError):
        check.exercise_feature(SimpleNamespace(cache_key=lambda c, s: check.digest(check.encoded({'context':c,'source':' '.join(s.split())}))), 'cache_identity_v1')


def test_destructive_cache_cannot_weaken_the_oracle_by_erasing_context_before_expected_hash():
    def destructive(context, source):
        context.clear()
        return check.digest(check.encoded({'context': context, 'source': source}))
    with pytest.raises(ValueError, match='functional feature contract failed'):
        check.exercise_feature(SimpleNamespace(cache_key=destructive), 'cache_identity_v1')


def test_pinned_organizer_arithmetic_parity_is_exercised_without_compiler_or_model():
    report = runner.scoring_parity(ROOT)
    assert report['passed'] and report['checks'] == 291 and report['official_score'] is None


def test_native_exit_zero_without_real_target_type_and_axioms_is_rejected():
    value = {'schema':'jevops-arena-native-smoke/v1','evidence_mode':'local_lean', 'arena_problem':False,
             'official_score':None, 'live_model_calls':0, 'processes':2, 'candidate':{'status':'REJECTED'}}
    with pytest.raises(ValueError, match='not actually measured'): runner.native_semantics(ROOT, check.encoded(value))


def test_schedule_and_offline_fixture_semantics_do_not_accept_self_claimed_pass():
    for kind in ['calibration', 'offline_protocol', 'schedule']:
        with pytest.raises(ValueError): runner.command_semantics(kind, b'{"passed":true,"exit_code":0}')


@pytest.mark.parametrize('command', [['python3', '-m', 'jevops.arena', '--calibrate'],
                                   ['python3', 'papers/completion/lean_refactor_arena/tools/verify_lra_batch.py', '--schedule']])
def test_actual_readonly_offline_command_stdout_satisfies_fixed_contract(tmp_path, command):
    argv, kind = runner.checked_command(command)
    execution = runner.run_process(argv, root=ROOT, timeout=15, directory=tmp_path / kind)
    assert execution['exit_code'] == 0 and not execution['timed_out']
    result = runner.command_semantics(kind, execution['stdout'].read_bytes())
    assert result['passed'] and result['proof_authority'] is False and result['official_score'] is None


def test_cli_check_all_alias_and_invalid_task_fail_without_execution(campaign, capsys):
    root, _ = campaign
    assert check.main(['--repo-root', str(root), '--check-all']) == 0
    assert check.main(['--repo-root', str(root), '--validate-task', 'JLR-999']) == 1
    assert not (root / check.RECEIPTS).exists()
