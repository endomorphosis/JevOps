"""Adversarial operational registration checks; no fabricated scientific pass."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import lean_refactor_execution_v2 as c
import lean_refactor_activation_audit as m
import validate_lean_refactor_activation_audit as v

@pytest.fixture
def campaign(tmp_path,monkeypatch):
    root=tmp_path
    tasks={t['id']:t for t in c.read(ROOT/c.CONTINUATION_GOALS)['tasks']}
    contracts=deepcopy(c.definitions());done=set(m.DEPS)|{'JLR-016','JLR-026'}
    board={tid:{'status':'completed' if int(tid[-3:])<=15 or tid in done else
                    'pending' if tid in contracts else 'planned',
                'depends_on':', '.join(t['depends_on'])} for tid,t in tasks.items()}
    text=''
    for tid,t in tasks.items():
        fields=board[tid]
        if tid in contracts:
            fields.update(deterministic_command='python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid,
                          validation='python3 tools/check_lean_refactor_stage_v2.py --validate-task '+tid)
        text+='\n## '+tid+' Private operational fixture\n'+''.join('- '+k.replace('_',' ').title()+': '+val+'\n' for k,val in fields.items())
    c.atomic(root/c.BOARD,text)
    manifest={'execution_profile':c.PROFILE,'todo_path':c.BOARD,'lanes':[{'bundle_key':'private-owner'}]}
    config={'runtime_manifest':'data/live.json','materialize_planned_work':True,'activate_planned_work':False,
            'planned_work_mode':'implement_validate_then_activate','reset_campaign_budgets':False}
    c.save(root/c.LANES,manifest);c.save(root/'data/live.json',manifest)
    c.save(root/'config/lean_refactor_arena_20261024_watchdog.json',config)
    for name in (c.BASE,c.GOALS,c.CONTINUATION_PLAN,c.CONTINUATION_GOALS,
                 'tools/check_lean_refactor_plan.py','tools/run_lean_refactor_router_task.py'):
        c.atomic(root/name,'private preserved original '+name+'\n')
    usage={'calls':22,'contracts':{'preserved-failed-attempt':3}}
    budget='data/lean_refactor_arena_20261024/router-budget.json';c.save(root/budget,usage)
    ledger={'bootstrap_usage':usage,'limits':{'max_calls':2},'attempts':[{'failed':True},{'returned':True}]}
    c.save(root/c.RUNTIME/'iterative-v1-ledger.json',ledger)
    source='tools/lean_refactor_activation_audit.py';c.atomic(root/source,'# private immutable producer\n')
    profile={'contracts':contracts,'source_sha256':{source:c.sha(root/source)},'tests_receipt':c.RUNTIME+'/focused-tests.json',
             'base_profile_sha256':c.sha(root/c.BASE),'goals_sha256':c.sha(root/c.GOALS),
             'phase_budget':{'calls':0,'max_calls':0,'previous_usage':usage,'previous_usage_path':budget}}
    c.save(root/c.PROFILE,profile)
    junit='data/focused.xml';c.atomic(root/junit,'<testsuite>'+''.join('<testcase classname="operational_fixture" name="test'+str(i)+'"/>' for i in range(35))+'</testsuite>')
    c.save(root/profile['tests_receipt'],{'passed':True,'source_sha256':profile['source_sha256'],
               'junit_path':junit,'junit_sha256':c.sha(root/junit)})
    pre={'valid':True,'implemented':list(contracts),'verified_bootstrap':['JLR-'+str(i).zfill(3) for i in range(1,16)],
         'verified_research':{tid:{'valid':True,'fixture_only':True} for tid in done}}
    for name in ('activation','materialization'):
        c.save(root/c.RUNTIME/(name+'.json'),{'profile_sha256':c.sha(root/c.PROFILE),'preflight':pre,
          'bootstrap_usage_retained':usage,'bootstrap_restarted':False,'router_calls_added':0,'owner':'private-owner'})
    c.save(root/c.RUNTIME/'JLR-033.result.json',{'fixture_only':True})
    def module(selected,name):
        assert selected==root and name=='validate_lean_refactor_operational_faults.py'
        return SimpleNamespace(validate=lambda r,d: {'checked_raw_fault_evidence':d['fixture_only']})
    monkeypatch.setattr(c,'module',module)
    monkeypatch.setattr(c,'load',lambda selected:(profile,{},tasks,board))
    monkeypatch.setattr(m,'resource_snapshot',lambda selected:{'eligible':True,'host_available_bytes':32*1024**3,'disk_free_bytes':1024**3})
    return root,profile,board

def snapshot(root):return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def test_producer_and_independent_audit_leave_boards_proofs_and_usage_unchanged(campaign):
    root,profile,board=campaign;before=snapshot(root)
    report=m.produce(root);checked=v.validate(root,report)
    assert checked['registered_contracts']==12 and checked['owned_fault_evidence']['checked_raw_fault_evidence']
    assert 'JLR-034' in report['ready'] and 'JLR-022' in report['unknown_planned']
    assert report['historical_runtime_only'] and not report['scientific_acceptance_authority']
    assert snapshot(root)==before

@pytest.mark.parametrize('damage',['authority','budget','phase','unknown','argv','deps','ready','owner','profile','source','wall','board','resources'])
def test_independent_audit_rejects_invented_authority_budget_contract_or_progress(campaign,damage):
    root,profile,board=campaign;data=deepcopy(m.produce(root))
    if damage=='authority':data['scientific_acceptance_authority']=True
    elif damage=='budget':data['bootstrap_usage']['calls']=0
    elif damage=='phase':data['iterative_usage']['limits']['max_calls']=3
    elif damage=='unknown':data['unknown_planned'].remove('JLR-022')
    elif damage=='argv':data['contracts']['JLR-021']['contract']['argv']=['unreviewed.py']
    elif damage=='deps':data['contracts']['JLR-021']['depends_on']=['JLR-019']
    elif damage=='ready':data['ready'].append('JLR-022')
    elif damage=='owner':data['owner']='second-owner'
    elif damage=='profile':data['profile_sha256']='f'*64
    elif damage=='source':data['source_sha256']['tools/lean_refactor_activation_audit.py']='e'*64
    elif damage=='wall':data['wall_seconds']=61
    elif damage=='resources':data['resources_before']['eligible']=False
    else:data['board_text']+='\nchanged\n'
    with pytest.raises((ValueError,KeyError)):v.validate(root,data)

@pytest.mark.parametrize('damage',['tests','acceptance','receipt','fault','unknown_status','hold','resource'])
def test_file_existence_and_success_flags_cannot_replace_acceptance(campaign,monkeypatch,damage):
    root,profile,board=campaign
    if damage=='unknown_status':
        board['JLR-022']['status']='pending'
        with pytest.raises(ValueError,match='unknown experiment'):m.produce(root)
        return
    if damage=='hold':
        c.atomic(root/'data/lean_refactor_arena_20261024/HOLD','operator\n')
        with pytest.raises(ValueError,match='operator hold'):m.produce(root)
        return
    if damage=='resource':
        monkeypatch.setattr(m,'resource_snapshot',lambda selected:{'eligible':False})
        with pytest.raises(ValueError,match='resource'):m.produce(root)
        return
    name=profile['tests_receipt'] if damage=='tests' else c.RUNTIME+'/activation.json'
    d=c.read(root/name)
    if damage=='tests':d['passed']=False
    elif damage=='acceptance':d['preflight']['verified_research']['JLR-033']['valid']=False
    elif damage=='receipt':d['router_calls_added']=1
    if damage!='fault':c.save(root/name,d)
    data=m.produce(root)
    if damage=='fault':
        def refuse(*args):raise ValueError('real fault evidence missing')
        monkeypatch.setattr(c,'module',lambda *a:SimpleNamespace(validate=refuse))
    with pytest.raises(ValueError):v.validate(root,data)

def test_historical_review_keeps_original_audit_evidence_without_restamping(campaign):
    root,profile,board=campaign;data=m.produce(root)
    old=c.sha(root/c.PROFILE);arch=root/c.RUNTIME/'history'/(Path(c.PROFILE).name+'.'+old)
    c.atomic(arch,(root/c.PROFILE).read_text())
    profile['previous_profiles']={old:str(arch.relative_to(root))};c.save(root/c.PROFILE,profile)
    assert v.validate(root,data)['registered_contracts']==12
