"""Diagnostic heartbeat forests are not verification or score receipts."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

from jevops import arena_local as local, arena_lean as native
from jevops.arena import source_hash
from jevops import arena_profile as pilot
from jevops.arena import Outcome, VersionReceipt
from jevops.arena_trial import Candidate
from tests.test_arena_local import guard, PIN, OTHER, RECORD, SOURCE, PREFIX


def stage(binding, payload):
    def row(i, parent, start, stop, hint):
        return dict(id=i, parent=parent, start_raw=start, stop_raw=stop, inclusive_raw=stop-start,
                    syntax_kind='Lean.Parser.Tactic.seq', hint=hint, hint_truncated=False)
    report = dict(schema='jevops-tactic-heartbeat-profile/v1', environment=payload['environment'],
        lean_version=PIN.lean_tag[1:], lean_githash='a'*40, instrumented=True,
        measurement=local.PROFILE_METHOD, projection='builtin-tactic-traces/v1',
        threshold_raw=payload['threshold_raw'], command_raw=200, nodes_visited=20,
        events=[row(0, None, 10, 110, 'parent'), row(1, 0, 20, 50, 'left'),
                row(2, 0, 60, 90, 'right'), row(3, None, 120, 180, 'other')],
        proof_admitted=False, score_eligible=False)
    return dict(schema=local.STAGE_SCHEMA, request_sha256=payload['request_sha256'], target=payload['target'],
                lean_version=report['lean_version'], lean_githash=report['lean_githash'], report=report)


def runtime(guard, **kwargs):
    return local.ArenaLocalRuntime(guard, RECORD, **{'runner': stage, **kwargs})


def test_profile_budget_and_nested_accounting_never_admit_or_score(guard):
    zero = runtime(guard)
    assert zero.profile(PIN)['status'] == 'BUDGET_EXHAUSTED' and zero.attempts == 0
    rt = runtime(guard, max_processes=2)
    first = rt.profile(PIN)
    assert first['status'] == 'FIXTURE_ONLY' and first['evidence_mode'] == 'fixture'
    assert first['ok'] and not first['whole_source_checked'] and not first['proof_admitted']
    p = first['profile']
    assert p['root_ids'] == [0, 3] and p['covered_raw'] == p['exclusive_total_raw'] == 160
    assert p['unattributed_raw'] == 40
    assert [r['exclusive_recorded_raw'] for r in p['events']] == [40, 30, 30, 60]
    assert not p['score_eligible'] and not p['proof_admitted']
    second = rt.profile(PIN)
    assert second['ok'] and rt.attempts == rt.reserved == 2 and guard.processes == 0
    assert rt.profile(PIN)['status'] == 'BUDGET_EXHAUSTED'
    changed_threshold = runtime(guard, max_processes=1).profile(PIN, threshold_raw=0)
    assert changed_threshold['environment'] != first['environment']


@pytest.mark.parametrize('damage', ['authority', 'score', 'method', 'instrumented', 'environment',
    'threshold', 'nan', 'bool', 'negative', 'infinite', 'fractional', 'too_large', 'id', 'parent',
    'cycle', 'escaped_child', 'overlap', 'order', 'counter', 'empty', 'extra', 'hint', 'kind',
    'truncated', 'root_sum', 'node_budget', 'event_budget', 'hash', 'envelope', 'reentered_parent'])
def test_forged_or_malformed_profile_rejected_without_partial_summary(guard, damage):
    def corrupt(binding, payload):
        value = stage(binding, payload)
        r = value['report']; rows = r['events']
        if damage == 'authority': r['proof_admitted'] = True
        elif damage == 'score': r['score_eligible'] = True
        elif damage == 'method': r['measurement'] = native.METHOD
        elif damage == 'instrumented': r['instrumented'] = False
        elif damage == 'environment': r['environment'] = 'old'
        elif damage == 'threshold': r['threshold_raw'] += 1
        elif damage == 'nan': rows[0]['start_raw'] = float('nan')
        elif damage == 'infinite': r['command_raw'] = float('inf')
        elif damage == 'bool': rows[0]['id'] = False
        elif damage == 'negative': rows[0]['start_raw'] = -1
        elif damage == 'fractional': rows[0]['start_raw'] = 10.5
        elif damage == 'too_large': rows[0]['start_raw'] = 2**53
        elif damage == 'id': rows[2]['id'] = 1
        elif damage == 'parent': rows[0]['parent'] = 0
        elif damage == 'cycle': rows[1]['parent'] = 2
        elif damage == 'escaped_child': rows[3]['parent'] = 0
        elif damage == 'overlap': rows[2].update(start_raw=40, stop_raw=70)
        elif damage == 'order': rows[1].update(start_raw=60, stop_raw=90); rows[2].update(start_raw=20, stop_raw=50)
        elif damage == 'counter': rows[0]['inclusive_raw'] += 1
        elif damage == 'empty': r['events'] = []
        elif damage == 'extra': rows[0]['theorem_ok'] = True
        elif damage == 'hint': rows[0]['hint'] = 'x'*513
        elif damage == 'kind': rows[0]['syntax_kind'] = 'Arbitrary.expression'
        elif damage == 'truncated': rows[0]['hint_truncated'] = 1
        elif damage == 'root_sum': r['command_raw'] = 120
        elif damage == 'node_budget': r['nodes_visited'] = 4097
        elif damage == 'event_budget': r['events'] = rows*100
        elif damage == 'hash': r['lean_githash'] = value['lean_githash'] = 'unknown'
        elif damage == 'envelope': value['request_sha256'] = 'old'
        else: rows.append({**rows[2], 'id': 4})
        return value
    rt = runtime(guard, runner=corrupt, max_processes=1)
    result = rt.profile(PIN)
    assert result['status'] == 'ERROR' and not result['ok'] and 'profile' not in result
    assert not result['proof_admitted'] and rt.attempts == rt.reserved == 1


@pytest.mark.parametrize('threshold', [True, None, -1, 1_000_001, 1.5])
def test_bad_threshold_never_launches(guard, threshold):
    rt = runtime(guard, max_processes=1)
    with pytest.raises(ValueError): rt.profile(PIN, threshold_raw=threshold)
    assert rt.reserved == rt.attempts == 0


@pytest.mark.parametrize('damage', ['dependencies', 'implementation', 'source', 'pin'])
def test_stale_profile_context_is_rejected_before_work(guard, monkeypatch, damage):
    rt = runtime(guard, max_processes=1)
    source, pin = SOURCE, PIN
    if damage == 'dependencies': guard.bindings[PIN] = replace(guard.bindings[PIN], prefix=PREFIX+'\n')
    elif damage == 'implementation': monkeypatch.setattr(local, '_identity', lambda: 'changed')
    elif damage == 'source': source = 'theorem alien : True := by trivial'
    else: pin = native.VersionPin('v4.99.0', 'unavailable')
    with pytest.raises(ValueError): rt.profile(pin, source=source)
    assert rt.reserved == rt.attempts == 0


def test_transient_profile_failure_never_becomes_a_counterexample(guard):
    def unavailable(*args): raise TimeoutError('fixture transport timeout')
    rt = runtime(guard, max_processes=1, runner=unavailable)
    r = rt.profile(PIN)
    assert r['status'] == 'ERROR' and not r['ok'] and 'profile' not in r
    assert not r['proof_admitted'] and rt.profile(PIN)['status'] == 'BUDGET_EXHAUSTED'


def plan():
    record = {**RECORD, 'version_info': [{PIN.lean_tag: PIN.git_commit}]}
    return pilot.make_plan(record, Candidate('incumbent', SOURCE, 'offline planning fixture'))


def test_profile_plan_separates_instrumented_and_plain_controls():
    p = plan()
    assert len(p['schedule']) == p['native_process_ceiling'] == 10
    assert [s['kind'] for s in p['schedule']] == ['control']*4 + ['profile']*6
    assert [s['arm'] for s in p['schedule'][4:]] == ['original', 'incumbent', 'incumbent', 'original', 'original', 'incumbent']
    assert p['threshold_raw'] == 100 and p['node_budget'] == 20000 and p['event_budget'] == 256
    assert not p['score_eligible'] and not p['promoted'] and p['official_score'] is None
    with pytest.raises(ValueError, match='exactly one'):
        pilot.make_plan(RECORD, Candidate('inc', SOURCE, 'two-pin fixture'))


def test_profile_threshold_change_requires_separate_frozen_plan():
    p = plan()
    coarse = pilot.make_plan(p['record'], Candidate(**p['incumbent']), threshold_raw=10000)
    assert coarse['threshold_raw'] == 10000 and coarse['plan_sha256'] != p['plan_sha256']
    assert coarse['schedule'] == p['schedule'] and coarse['event_budget'] == p['event_budget'] == 256
    assert coarse['native_process_ceiling'] == p['native_process_ceiling'] == 10
    for bad in (True, -1, 1000001, 1.5):
        with pytest.raises(ValueError): pilot.make_plan(p['record'], Candidate(**p['incumbent']), threshold_raw=bad)


@pytest.mark.parametrize('damage', ['zero', 'partial', 'bool', 'schedule', 'threshold', 'pin', 'storage'])
def test_profile_pilot_refuses_invalid_plan_or_resources_before_output(guard, tmp_path, damage):
    p = plan(); binding = guard.bindings[PIN]; limit = 10
    if damage == 'zero': limit = 0
    elif damage == 'partial': limit = 6
    elif damage == 'bool': limit = True
    elif damage == 'schedule': p['schedule'].pop()
    elif damage == 'threshold': p['threshold_raw'] = 0
    elif damage == 'pin': binding = replace(binding, pin=OTHER)
    def resources():
        if damage == 'storage': raise ValueError('storage reserve')
        pytest.fail('invalid inputs reached resource check')
    with pytest.raises(ValueError):
        pilot.run(p, binding=binding, directory=tmp_path/'run', max_processes=limit, check_resources=resources)
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('failure', [None, 'control', 'axiom', 'profile'])
def test_pilot_wiring_and_stop_without_retry(guard, tmp_path, monkeypatch, failure):
    import json
    def verify(self, request):
        self.processes += 1
        return VersionReceipt(request.request_id, source_hash(request.source),
            request.context.problem, Outcome.REJECTED if failure == 'control' else Outcome.VERIFIED,
            type_preserved=True,
            observations_json=json.dumps(dict(report=dict(axioms=['Classical.choice'] if failure == 'axiom' else [],
                                                          reference_axioms=[]))))
    monkeypatch.setattr(native.NativeLeanVerifier, '__call__', verify)
    def fixture_runtime(*args, **kwargs):
        def runner(binding, payload):
            if failure == 'profile': raise TimeoutError('fixture diagnostic failure')
            return stage(binding, payload)
        return local.ArenaLocalRuntime(*args, runner=runner, **kwargs)
    monkeypatch.setattr(pilot, 'ArenaLocalRuntime', fixture_runtime)
    result = pilot.run(plan(), binding=guard.bindings[PIN], directory=tmp_path/'run',
                       max_processes=10, check_resources=lambda: None)
    assert result['status'] == ('PROFILED' if failure is None else 'INCOMPLETE')
    assert len(result['controls']) == (1 if failure in ('control', 'axiom') else 4)
    assert len(result['profiles']) == (6 if failure is None else 1 if failure == 'profile' else 0)
    assert not result['score_eligible'] and not result['candidate_search'] and result['official_score'] is None
    assert result['native_processes'] == (10 if failure is None else 5 if failure == 'profile' else 1)


@pytest.mark.no_seal(reason='explicit opt-in installed Lean profiler control')
def test_native_profile_is_instrumented_not_a_verification_receipt(tmp_path):
    if os.environ.get('JEVOPS_ARENA_NATIVE_TESTS') != '1':
        pytest.skip('explicit opt-in; already installed toolchain only')
    lean = native.pinned_lean(Path(os.environ.get('ELAN_HOME', str(Path.home()/'.elan'))), PIN.lean_tag)
    statement = 'theorem profiled (a b : Prop) (h : a ∧ b) : b ∧ a'
    record = dict(name='Suite.profiled', statement=statement, src=statement+' := by\n  constructor <;> simp_all',
                  version_info=[{PIN.lean_tag: PIN.git_commit}])
    binding = native.ProjectBinding(PIN, lean, tmp_path, PREFIX, project_backed=False)
    guard = native.NativeLeanVerifier({PIN: binding}, max_processes=0, timeout=90)
    rt = local.ArenaLocalRuntime(guard, record, max_processes=1)
    result = rt.profile(PIN, threshold_raw=0)
    assert result['ok'], result.get('reason', result)
    assert result['status'] == 'OBSERVED' and result['profile']['instrumented']
    assert not result['proof_admitted'] and not result['whole_source_checked']
    assert not result['profile']['score_eligible'] and guard.processes == 0
    assert result['profile']['covered_raw'] == result['profile']['exclusive_total_raw']
    assert any('simp_all' in row['hint'] for row in result['profile']['events'])
