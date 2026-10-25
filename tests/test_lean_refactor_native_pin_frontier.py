"""Preparation/admission tests. Synthetic fixtures never attest native proofs."""
import copy
import json
from pathlib import Path
import sys
import time
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_execution_v2 as c
import lean_refactor_native_pin_frontier as f
import lean_refactor_iterative_pilot as pilot
import run_lean_refactor_stage_v2 as runner
import validate_lean_refactor_native_pin_frontier as protected

def test_frontier_matches_only_the_two_missing_frozen_target_pins():
    record=next(r for r in c.module(ROOT,'lean_refactor_project_readiness.py').records() if r['name']==f.TARGET)
    assert f.plan(ROOT,record)==[
        ('v4.29.1','384e22374e0872095ad9c6f74c5998c09cfd93a9'),
        ('v4.27.0','4348c65a93a3b57b1a4541991ed2d2fcdd9fa35d')]

def test_supplemental_overlay_never_writes_bootstrap_files(tmp_path,monkeypatch):
    original={'rows':[{'name':f.TARGET,'lean_tag':'v4.27.0','git_commit':'frozen','status':'UNAVAILABLE'}],
              'projects':[{'repository':'public-repo','lean_tag':'v4.27.0','git_commit':'frozen','root':'old'}]}
    c.save(tmp_path/c.RUNTIME/'JLR-017.result.json',original)
    c.save(tmp_path/c.RUNTIME/'JLR-016.result.json',{'elan_home':'original-home'})
    before={p.name:p.read_bytes() for p in (tmp_path/c.RUNTIME).iterdir()}
    project={'repository':'public-repo','lean_tag':'v4.27.0','git_commit':'frozen','root':'private-root'}
    # Only the overlay seam is isolated here; production validate is tested
    # against actual preparation/native artifacts before any stage acceptance.
    report={'rows':[{'pin':{'lean_tag':'v4.27.0','git_commit':'frozen'},'project':project,
                     'sample':{'receipt':{'outcome':'VERIFIED'}}}]}
    monkeypatch.setattr(f,'validate',lambda *args:(report,{'elan_home':'private-home'}))
    effective,ready=f.effective_inputs(tmp_path,{'path':'private-fixture'})
    assert effective['rows'][0]['status']=='VERIFIED'
    assert effective['projects']==[{**project,'elan_home':'private-home'}]
    assert ready['elan_home']=='original-home'
    assert before=={p.name:p.read_bytes() for p in (tmp_path/c.RUNTIME).iterdir()}

@pytest.mark.parametrize('outcome',['REJECTED','TIMEOUT','ERROR'])
def test_infrastructure_or_semantic_failure_cannot_upgrade_a_pin(tmp_path,monkeypatch,outcome):
    c.save(tmp_path/c.RUNTIME/'JLR-017.result.json',{'rows':[],'projects':[]})
    c.save(tmp_path/c.RUNTIME/'JLR-016.result.json',{'elan_home':'original'})
    monkeypatch.setattr(f,'validate',lambda *args:({'rows':[{'sample':{'receipt':{'outcome':outcome}}}]},{}))
    assert f.effective_inputs(tmp_path,{})[0]=={'rows':[],'projects':[]}

def test_frontier_archive_tampering_rejected_before_native_claims(tmp_path):
    path=tmp_path/'frontier.json';c.save(path,{'status':'VERIFIED'})
    with pytest.raises(ValueError,match='archive changed'):
        f.validate(tmp_path,{'path':'frontier.json','sha256':'0'*64})

def test_frontier_commands_have_sanitized_environment_and_durable_raw_logs(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIVATE_KEY','private-fixture-never-print')
    output=f.command([sys.executable,'-c','import os,json;print(json.dumps({"secret": "PRIVATE_KEY" in os.environ,"home":os.environ["HOME"]}))'],
                     tmp_path,tmp_path,timeout=3,label='environment')
    assert json.loads(output)=={'secret':False,'home':str(tmp_path/'home')}
    observed=c.read(next((tmp_path/'logs').glob('*.json')))
    assert observed['exit_code']==0 and observed['timed_out'] is False
    for name in ('stdout','stderr'):assert c.sha(Path(observed[name]))==observed[name+'_sha256']

def test_frontier_timeout_retains_real_failure_and_signals_only_pidfd(tmp_path):
    with pytest.raises(ValueError,match='retained observation'):
        f.command([sys.executable,'-c','import time;time.sleep(60)'],tmp_path,tmp_path,timeout=.03)
    receipt=c.read(next((tmp_path/'logs').glob('*.json')))
    assert receipt['exit_code']==124 and receipt['timed_out'] is True

def test_decimal_pin_labels_cannot_overwrite_prior_failure_logs(tmp_path):
    for _ in range(2):
        assert f.command([sys.executable,'-c','print("actual subprocess")'],tmp_path,tmp_path,
                         timeout=3,label='elan-v4.29.1')=='actual subprocess'
    assert len(list((tmp_path/'logs').glob('*.json')))==2

@pytest.mark.parametrize('attempts',[1,2])
def test_consumed_phase_refuses_cheaply_without_overwriting_run_or_calls(tmp_path,monkeypatch,attempts):
    c.save(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json',{'calls':22,'failures':['preserved']})
    ledger=pilot.budget(tmp_path)
    for _ in range(attempts):pilot.reserve(tmp_path,ledger,{'status':'FAILED'})
    scientific=tmp_path/c.RUNTIME/'JLR-024.receipt.json';c.save(scientific,{'real_earlier_run':'retained'})
    old=scientific.read_bytes();usage=(tmp_path/pilot.LEDGER).read_bytes()
    def forbidden(*args,**kwargs):raise AssertionError('consumed phase must never probe models or native prerequisites')
    monkeypatch.setattr(runner,'process',forbidden)
    refusal=runner.iterative_admission(tmp_path,'JLR-024')
    assert refusal['exit_code']==75 and refusal['reserved_attempts']==attempts
    assert refusal['scientific_run_receipt_preserved'] is True
    assert scientific.read_bytes()==old and (tmp_path/pilot.LEDGER).read_bytes()==usage
    gate=(tmp_path/c.RUNTIME/'iterative-admission-gate.json').read_bytes()
    runner.iterative_admission(tmp_path,'JLR-024')
    assert (tmp_path/c.RUNTIME/'iterative-admission-gate.json').read_bytes()==gate

def test_bad_phase_budget_cannot_be_downgraded_to_resource_wait(tmp_path):
    c.save(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json',{'calls':22})
    ledger=copy.deepcopy(pilot.budget(tmp_path));ledger['limits']['max_calls']=99;c.save(tmp_path/pilot.LEDGER,ledger)
    with pytest.raises(ValueError,match='never reset'):runner.iterative_admission(tmp_path,'JLR-024')

def test_unattempted_phase_and_unrelated_stage_have_no_admission_writes(tmp_path):
    assert runner.iterative_admission(tmp_path,'JLR-020') is None
    assert runner.iterative_admission(tmp_path,'JLR-024') is None
    assert not list(tmp_path.iterdir())

def test_run_refuses_consumed_phase_before_any_dependency_validator(tmp_path,monkeypatch):
    c.save(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json',{'calls':22})
    ledger=pilot.budget(tmp_path);pilot.reserve(tmp_path,ledger,{'prior_failure':'retained'})
    loaded=({'contracts':{'JLR-024':{}}},{},{'JLR-024':{'depends_on':['JLR-023']}},
            {'JLR-024':{'status':'pending'},'JLR-023':{'status':'completed'}})
    monkeypatch.setattr(c,'load',lambda root:loaded)
    def forbidden(*args,**kwargs):raise AssertionError('expensive dependency work admitted for consumed phase')
    monkeypatch.setattr(c,'module',forbidden);monkeypatch.setattr(c,'binding',forbidden)
    assert runner.run(tmp_path,'JLR-024')['exit_code']==75

def test_native_pin_retry_is_cheap_stable_and_rearms_after_bounded_wait(tmp_path,monkeypatch):
    c.save(tmp_path/c.RUNTIME/'private-frontier.json',{'observed_at':1000,'rows':[
        {'pin':{'lean_tag':'frozen','git_commit':'pinned'},'sample':None}]})
    c.save(tmp_path/f.INDEX,{'path':c.RUNTIME+'/private-frontier.json','sha256':'retained-private-fixture'})
    def forbidden(*args,**kwargs):raise AssertionError('retry poll must not compile, provision or query models')
    monkeypatch.setattr(f,'produce',forbidden);monkeypatch.setattr(f,'validate',forbidden)
    a=protected.probe(tmp_path,now=1001);b=protected.probe(tmp_path,now=1899)
    assert a==b and a['retry_generation']==0
    assert protected.probe(tmp_path,now=1900)['retry_generation']==1
    assert protected.probe(tmp_path,now=2799)['retry_generation']==1
