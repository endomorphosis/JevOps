"""Explicit opt-in, installed stdlib only. These are controls, not Arena gains."""
import json
import os
from pathlib import Path

import pytest

from jevops import arena_lean as native, arena_local as local
from jevops.arena import reference_tokens
from jevops.arena_solver import SolverLimits
from jevops.lean import VersionPin


@pytest.mark.no_seal(reason='native solver control; no downloads or model calls')
def test_native_solver_suggestions_and_support_minimization(tmp_path):
    if os.environ.get('JEVOPS_ARENA_NATIVE_TESTS') != '1':
        pytest.skip('installed native opt-in only')
    tag = os.environ.get('JEVOPS_SEARCH_LEAN_TAG', 'v4.26.0')
    lean = native.pinned_lean(Path(os.environ.get('ELAN_HOME', str(Path.home()/'.elan'))), tag)
    pin = VersionPin(tag, 'solver-stdlib-control')
    statement = 'theorem solver_control (n : Nat) : 0 + n = n'
    source = statement + ' := by\n  simp only [Nat.zero_add, Nat.add_zero, Nat.mul_one]\n'
    record = dict(name='solver_control', statement=statement, src=source,
                  version_info=[{pin.lean_tag:pin.git_commit}])
    summaries = []
    for mode in ('suggestions-v1', 'minimize-v1', 'frontier-v1'):
        binding = native.ProjectBinding(pin, lean, tmp_path, '', project_backed=False)
        guard = native.NativeLeanVerifier({pin:binding}, max_processes=16, timeout=45)
        rt = local.ArenaLocalRuntime(guard, record)
        report = rt.discover_solver(pin, mode=mode,
            limits=SolverLimits(max_calls=16, max_depth=2, max_sites=1, max_states=8))
        assert report['status'] not in ('ERROR','UNAVAILABLE','TIMEOUT'), report['attempts']
        assert report['seed_checked'] and report['drafts'], report
        assert report['verifier_calls'] == guard.processes <= 16
        assert rt.attempts == rt.reserved == 0  # correct independent budget
        assert not report['promoted'] and not report['incumbent_changed']
        assert all(n['tokens'] == reference_tokens(n['source'], statement) for n in report['frontier'])
        assert all('Nat.zero_add' in n['source'] for n in report['frontier'])
        observations = [json.loads(a['receipt']['observations_json']) for a in report['attempts']]
        anchored = [d for o in observations for d in o.get('report',{}).get('diagnostics',[])
            if d['message'].startswith('Try this:') and d['severity']=='information'
            and d['fileName']=='ArenaCandidate.lean' and d['pos']==dict(line=2,column=2)]
        assert anchored, observations
        if mode == 'suggestions-v1':
            assert any(e['retained'] and e['edit']['kind']=='solver-suggestion' for e in report['edits'])
        else:
            assert any(a['kind']=='support-deletion' and a['receipt']['outcome']=='REJECTED'
                       for a in report['attempts'])  # deleting required support fails
        summaries.append(dict(mode=mode, status=report['status'], calls=guard.processes,
            drafts=len(report['drafts']), tokens=[n['tokens'] for n in report['frontier']],
            raw_heartbeats=[n['raw_heartbeats'] for n in report['frontier']],
            wall_seconds=report['wall_seconds'], truncated=report['truncated']))
    print(json.dumps(dict(pin=tag, stdlib_control=True, official_score=None, arms=summaries)))


@pytest.mark.no_seal(reason='native parser/span control; installed toolchain only')
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_native_multiline_solver_spans_and_per_goal_hints(tmp_path, newline):
    if os.environ.get('JEVOPS_ARENA_NATIVE_TESTS') != '1':
        pytest.skip('installed native opt-in only')
    tag = os.environ.get('JEVOPS_SEARCH_LEAN_TAG', 'v4.26.0')
    lean = native.pinned_lean(Path(os.environ.get('ELAN_HOME', str(Path.home()/'.elan'))), tag)
    pin = VersionPin(tag, 'solver-span-stdlib-control')
    statement = 'theorem solver_span_control (ν : Nat) : 0 + ν = ν ∧ ν + 0 = ν'
    source = (statement + ' := by\n  constructor <;>\n'
              '    simp [Nat.zero_add,\n'
              '          Nat.add_zero, Nat.mul_one, Nat.one_mul] at *\n').replace('\n', newline)
    record = dict(name='solver_span_control', statement=statement, src=source,
                  version_info=[{pin.lean_tag:pin.git_commit}])
    binding = native.ProjectBinding(pin, lean, tmp_path, '', project_backed=False)
    guard = native.NativeLeanVerifier({pin:binding}, max_processes=3, timeout=45)
    rt = local.ArenaLocalRuntime(guard, record)
    report = rt.discover_solver(pin, mode='suggestions-v1',
        limits=SolverLimits(max_calls=3, max_sites=1, max_depth=1))
    assert report['status'] == 'COMPLETE', report
    assert guard.processes == report['verifier_calls'] == 3
    assert len(report['frontier']) == 2 and report['drafts'], report
    parent, child = report['frontier']
    assert parent['solver_spans']['status'] == 'CAPTURED'
    assert all(a['receipt']['outcome'] == 'VERIFIED' for a in report['attempts'])
    assert 'constructor <;>' + newline in child['source']
    assert child['source'].endswith('] at *' + newline)
    assert child['tokens'] < parent['tokens']
    assert child['source'].count(newline) == source.count(newline) - 1
    assert 'Nat.mul_one' not in child['source'] and 'Nat.one_mul' not in child['source']
    assert not report['promoted'] and report['official_score'] is None
    print(json.dumps(dict(pin=tag, newline=repr(newline), calls=guard.processes,
        stdlib_control=True, official_score=None, source=child['source'],
        tokens=[n['tokens'] for n in report['frontier']],
        raw_heartbeats=[n['raw_heartbeats'] for n in report['frontier']])))


@pytest.mark.no_seal(reason='explicit prepared Strata regression; three checks, no provisioning')
def test_native_archived_strata_multiline_repair(tmp_path):
    projects_file = os.environ.get('JEVOPS_STRATA_SPAN_PROJECTS')
    if os.environ.get('JEVOPS_ARENA_NATIVE_TESTS') != '1' or not projects_file:
        pytest.skip('requires explicit native opt-in and prepared Strata project mapping')
    repo = Path(__file__).resolve().parents[1]
    base = repo/'papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24'
    incumbent = json.loads((base/'incumbent.json').read_text())
    record, = [json.loads(line) for line in native.CORPUS.read_text().splitlines()
               if json.loads(line)['name'] == incumbent['name']]
    pin = VersionPin('v4.26.0', '451e5f047bafa010d178856db76c00029bfa4d7f')
    project, = [p for p in json.loads(Path(projects_file).read_text())
                if (p['repository'], p['lean_tag'], p['git_commit']) ==
                   (record['url'], pin.lean_tag, pin.git_commit)]
    binding = native.project_binding(record, pin, project, Path(os.environ['ELAN_HOME']))
    guard = native.NativeLeanVerifier({pin:binding}, max_processes=3, timeout=90)
    runtime = local.ArenaLocalRuntime(guard, record)
    report = runtime.discover_solver(pin, source=incumbent['source'], mode='frontier-v1',
        limits=SolverLimits(max_calls=3, max_states=2, max_sites=1, max_depth=1))
    (tmp_path/'strata-span-replay.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    assert report['status'] == 'COMPLETE', report
    assert guard.processes == report['verifier_calls'] == 3
    assert all(a['receipt']['outcome'] == 'VERIFIED' for a in report['attempts'])
    assert [a['kind'] for a in report['attempts']] == ['seed', 'suggestion-probe', 'solver-suggestion']
    assert len(report['frontier']) == 2
    edit, = report['edits']
    assert edit['retained'] and 'List.Subset.empty' in edit['edit']['replacement']
    assert 'List.append_assoc' in edit['edit']['replacement']
    assert report['frontier'][1]['source'].splitlines()[8].startswith('  case app')
    assert not report['promoted'] and report['official_score'] is None
    print(json.dumps(dict(problem=record['name'], pin=pin.to_dict(), native_calls=guard.processes,
        outcome='MULTILINE_REPLAY_VERIFIED', score_gain_confirmed=False,
        tokens=[n['tokens'] for n in report['frontier']],
        raw_heartbeats=[n['raw_heartbeats'] for n in report['frontier']],
        report_path=str(tmp_path/'strata-span-replay.json'))))
