"""Private artifact/actual-child tests; fixture success is not campaign authority."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import lean_refactor_operational_faults as m
import validate_lean_refactor_operational_faults as v


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    root = tmp_path/'fixture-campaign';root.mkdir()
    accelerator = tmp_path/'fixture-accelerator'
    rescue = accelerator/'ipfs_accelerate_py/agent_supervisor/rescue/control.py'
    write(rescue, '# private historical operational version\n')
    for name in m.CORE_MODULES:write(accelerator/name, '# private operational source fixture\n')
    write(root/m.BASE, {'python_executable': sys.executable, 'accelerator_source': str(accelerator)})
    write(root/'config/lean_refactor_arena_20261024_watchdog.json', {'fixture_only': True})
    for name in (m.SELF, m.VALIDATOR):
        path = root/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
    write(root/'tools/reload_supervisor_when_idle.py', '# private source fixture\n')
    for name in ('implementation_plan/lean_refactor_arena_20261024.goals.json',
                 'implementation_plan/lean_refactor_arena_20261024.todo.md',
                 'implementation_plan/lean_refactor_arena_20261024.execution-v2.todo.md',
                 'config/lean_refactor_arena_20261024_execution_v2.json',
                 'data/lean_refactor_arena_20261024/router-budget.json'):
        write(root/name, {'immutable_fixture': name, 'calls': 22})
    suite = root/'tests/test_private_fault.py'
    write(suite, 'import os\ndef test_owned_fixture():\n    assert "UNRELATED_SECRET" not in os.environ\n')
    monkeypatch.setattr(m, 'POLICY', (('jevops', 'tests/test_private_fault.py', ('test_owned_fixture',)),))
    return root, accelerator, rescue, suite


def completed(campaign):
    root, *_ = campaign
    report = m.produce(root)
    assert v.validate(root, report)['historical_qualification'] is True
    return root, report


def original(root, report):
    (root/report['run_directory']/'result.json').write_bytes(m.canonical(report))


def change_execution(root, report, **fields):
    report['execution'].update(fields)
    path=root/report['run_directory']/'execution.json';path.write_bytes(m.canonical(report['execution']))
    report['evidence']['execution.json']['sha256']=m.sha(path)
    original(root, report)


def test_actual_closed_child_junit_logs_snapshots_and_campaign_preservation(campaign, monkeypatch):
    root, _, _, _ = campaign
    before = {name: m.sha(path) for name, path in m.protected_files(root).items()}
    monkeypatch.setenv('UNRELATED_SECRET', 'must-not-reach-fixture')
    report=m.produce(root);result=v.validate(root, report)
    assert result['operational_fault_cases']==1 and result['current_operational_version_matches']
    assert report['execution']['exit_code']==0 and report['execution']['private_process_group_empty']
    assert report['protected_state_before']==report['protected_state_after']==before
    assert before=={name:m.sha(path) for name,path in m.protected_files(root).items()}
    assert all(report[key] is False for key in ('proof_authority','completion_authority',
        'optimization_success','production_processes_signaled','production_states_changed'))
    assert report['model_calls']==report['provider_calls']==0
    assert report['execution']['argv'][1:5]==['-B','-m','pytest','-q']


def test_later_operational_core_change_does_not_invalidate_historical_science(campaign):
    root, report=completed(campaign)
    campaign[2].write_text('# changed later operational version\n')
    checked=v.validate(root,report)
    assert checked['historical_qualification'] is True and checked['current_operational_version_matches'] is False


def test_operational_version_is_source_bound_not_archive_location_or_clock(campaign):
    _,report=completed(campaign);sources=copy.deepcopy(report['tested_sources'])
    for row in sources.values():row['archive']='different/fresh/run/'+row['archive']
    assert m.source_version(sources)==report['tested_operational_version']
    sources[next(iter(sources))]['sha256']='0'*64
    assert m.source_version(sources)!=report['tested_operational_version']


def test_omitted_operational_core_cannot_be_hidden_in_rehashed_manifest(campaign):
    root,report=completed(campaign)
    report['tested_sources'].pop('accelerator/'+m.CORE_MODULES[0])
    report['tested_operational_version']=m.source_version(report['tested_sources']);original(root,report)
    with pytest.raises(ValueError,match='implementation snapshot missing'):v.validate(root,report)


@pytest.mark.parametrize('target', ['stdout.log','stderr.log','actual-tests.xml','execution.json'])
def test_raw_execution_artifact_tampering_is_rejected(campaign, target):
    root, report=completed(campaign)
    with (root/report['run_directory']/target).open('ab') as out:out.write(b'changed')
    with pytest.raises(ValueError,match='evidence changed'):v.validate(root,report)


def test_source_snapshot_tampering_is_rejected(campaign):
    root, report=completed(campaign)
    row=next(iter(report['tested_sources'].values()))
    (root/row['archive']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='snapshot changed'):v.validate(root,report)


@pytest.mark.parametrize('fault', ['skip','failure','missing','extra','duplicate'])
def test_junit_coverage_is_verified_independently_of_claimed_counts(campaign,fault):
    root,report=completed(campaign);run=root/report['run_directory']
    case='<testcase classname="test_private_fault" name="test_owned_fixture" time="0.001"{}'
    if fault in ('skip','failure'):body=case.format('>')+'<'+('skipped' if fault=='skip' else 'failure')+'/></testcase>'
    elif fault=='missing':body='<testcase classname="wrong" name="other"/>'
    elif fault=='extra':body=case.format('/>')+'<testcase classname="wrong" name="other"/>'
    else:body=case.format('/>')*2
    (run/'actual-tests.xml').write_text('<testsuite>'+body+'</testsuite>')
    report['evidence']['actual-tests.xml']['sha256']=m.sha(run/'actual-tests.xml');original(root,report)
    with pytest.raises(ValueError):v.validate(root,report)


@pytest.mark.parametrize('field,value', [('exit_code',True),('exit_code',1),('timed_out',True),
    ('private_process_group_empty',False),('shell',True),('timeout_seconds',600),('argv',['sh','-c','true'])])
def test_actual_zero_bounded_closed_execution_cannot_be_replaced(campaign,field,value):
    root,report=completed(campaign);change_execution(root,report,**{field:value})
    with pytest.raises(ValueError):v.validate(root,report)


def test_producer_or_validator_source_change_requires_renewed_acceptance(campaign):
    root,report=completed(campaign)
    with (root/m.SELF).open('ab') as out:out.write(b'\n# source change\n')
    with pytest.raises(ValueError,match='producer/validator changed'):v.validate(root,report)


@pytest.mark.parametrize('authority', ['proof_authority','completion_authority','optimization_success',
                                     'production_processes_signaled'])
def test_fixture_cannot_claim_proof_win_or_production_authority(campaign,authority):
    root,report=completed(campaign);report[authority]=True;original(root,report)
    with pytest.raises(ValueError,match='authority'):v.validate(root,report)


def test_protected_state_archive_and_original_report_cannot_be_rewritten(campaign):
    root,report=completed(campaign)
    row=next(iter(report['protected_state_archives'].values()))
    (root/row).write_bytes(b'changed state')
    with pytest.raises(ValueError,match='state archive'):v.validate(root,report)


def test_outside_or_symlinked_artifacts_are_refused(campaign):
    root,report=completed(campaign);run=root/report['run_directory']
    path=run/'stdout.log';raw=path.read_bytes();path.unlink()
    elsewhere=root/'outside.log';elsewhere.write_bytes(raw);path.symlink_to(elsewhere)
    with pytest.raises(ValueError):v.validate(root,report)


def test_real_failed_and_skipped_fixture_never_qualify(campaign):
    root,_,_,suite=campaign
    suite.write_text('def test_owned_fixture():\n    assert False\n')
    with pytest.raises(ValueError,match='suite failed'):m.produce(root)
    suite.write_text('import pytest\ndef test_owned_fixture():\n    pytest.skip("not executed")\n')
    with pytest.raises(ValueError,match='execute and pass'):m.produce(root)


def test_real_owned_timeout_reaps_the_owned_leader(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'TIMEOUT',0.05)
    result=m.run_owned([sys.executable,'-c','import time;time.sleep(10)'],tmp_path,
                       {'PATH':os.environ.get('PATH','/usr/bin:/bin')},tmp_path)
    assert result['timed_out'] is True and result['exit_code']!=0
    assert result['private_process_group_empty'] is True
    with pytest.raises(ProcessLookupError):os.kill(result['pid'],0)


def test_sources_and_campaign_state_are_rechecked_after_real_fixture(campaign,monkeypatch):
    root,_,source,_=campaign;run=m.run_owned
    def mutate(*args):
        result=run(*args);source.write_text('# concurrent operational edit\n');return result
    monkeypatch.setattr(m,'run_owned',mutate)
    with pytest.raises(ValueError,match='source changed'):m.produce(root)


def test_fixture_cannot_change_campaign_budget(campaign):
    root,_,_,suite=campaign
    budget=root/'data/lean_refactor_arena_20261024/router-budget.json'
    suite.write_text('from pathlib import Path\ndef test_owned_fixture():\n    Path('+repr(str(budget))+').write_text("{}")\n')
    with pytest.raises(ValueError,match='state changed'):m.produce(root)


def test_registered_venv_entrypoint_is_preserved(campaign):
    root,*_=campaign
    python,_=m.configuration(root)
    assert str(python)==sys.executable


def test_historical_timestamp_is_allowed_but_future_and_fabricated_duration_refuse(campaign):
    root,report=completed(campaign)
    report['observed_at']=time.time()+100;original(root,report)
    with pytest.raises(ValueError,match='timing'):v.validate(root,report)
    report['observed_at']=report['execution']['finished_at']
    change_execution(root,report,finished_at=report['execution']['started_at']+m.TIMEOUT+100)
    with pytest.raises(ValueError,match='timing'):v.validate(root,report)
