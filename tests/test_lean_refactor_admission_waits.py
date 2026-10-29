"""Artifact-only admission tests; no inference, native compilation or services."""
import copy,importlib.util,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import lean_refactor_execution_v2 as c
import lean_refactor_release_inventory as release
import lean_refactor_iterative_pilot as pilot
import run_lean_refactor_stage_v2 as runner
import check_lean_refactor_stage_v2 as checker

def snapshot(root):return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def loaded(monkeypatch,root,tid,profile=None):
    profile=profile or {'contracts':{tid:c.definitions()[tid]},'source_sha256':{}}
    tasks={tid:{'depends_on':['JLR-017']}};board={tid:{'status':'pending'},'JLR-017':{'status':'completed'}}
    monkeypatch.setattr(c,'load',lambda selected:(profile,{},tasks,board))
    return profile

@pytest.fixture
def future(tmp_path,monkeypatch):
    real=c.module
    monkeypatch.setattr(c,'module',lambda root,name:release if name=='lean_refactor_release_inventory.py' else real(root,name))
    monkeypatch.setattr(runner.time,'time',lambda:release.RELEASE_AT-1)
    return tmp_path

def forbidden(*args,**kwargs):raise AssertionError('known wait reached expensive native/model work')

def test_future_runner_skips_native_dependency_and_binding_preserves_scientific_receipt(future,monkeypatch):
    root=future;loaded(monkeypatch,root,'JLR-035')
    old={c.RUNTIME+'/JLR-035.receipt.json':'old executed scientific receipt\n',c.RUNTIME+'/JLR-035.result.json':'old scientific result\n'}
    for name,raw in old.items():c.atomic(root/name,raw)
    monkeypatch.setattr(c,'binding',forbidden);monkeypatch.setattr(checker,'validate',forbidden)
    monkeypatch.setattr(runner,'process',forbidden)
    result=runner.run(root,'JLR-035')
    assert result['exit_code']==75 and result['reason']=='official_release_not_due'
    assert result['scientific_run_receipt_preserved'] and not result['proof_authority']
    assert c.read(root/result['archive_path'])==result
    assert all((root/n).read_text()==v for n,v in old.items())
    assert not c.read(root/c.RUNTIME/'release-gate.json')['release_due']

def test_future_validator_waits_before_missing_receipt_and_never_writes(future,monkeypatch):
    root=future;loaded(monkeypatch,root,'JLR-035');before=snapshot(root)
    monkeypatch.setattr(checker,'receipt_binding',forbidden)
    with pytest.raises(checker.GateWait,match='official_release_not_due'):checker.validate(root,'JLR-035')
    assert snapshot(root)==before

def test_release_boundary_rearms_normal_protected_path(future,monkeypatch):
    root=future;loaded(monkeypatch,root,'JLR-035');monkeypatch.setattr(runner.time,'time',lambda:release.RELEASE_AT)
    assert runner.release_admission(root,'JLR-035',publish=False) is None
    class ProtectedPath(Exception):pass
    monkeypatch.setattr(c,'binding',lambda *a:(_ for _ in ()).throw(ProtectedPath()))
    with pytest.raises(ProtectedPath):runner.run(root,'JLR-035')

def ledger(root,attempts=2):
    previous={'original_usage':7};c.save(root/'data/lean_refactor_arena_20261024/router-budget.json',previous)
    value={'schema':'jevops.lean-refactor.local-inference-ledger.v1','limits':copy.deepcopy(pilot.LIMITS),
      'bootstrap_usage':previous,'subject':'qualified_frozen_Leanstral','attempts':[{'id':str(i),'status':'RETURNED'} for i in range(attempts)],**c.AUTH}
    c.save(root/pilot.LEDGER,value);return value

def test_spent_validator_is_budget_wait_before_current_unit_and_old_scientific_read(tmp_path,monkeypatch):
    root=tmp_path;ledger(root);loaded(monkeypatch,root,'JLR-024');before=snapshot(root)
    monkeypatch.setattr(checker,'receipt_binding',forbidden)
    with pytest.raises(checker.GateWait,match='phase_already_attempted'):checker.validate(root,'JLR-024')
    assert snapshot(root)==before

@pytest.mark.parametrize('attempts',[0,1,2])
def test_actual_ledger_admission_is_readonly_and_never_refunds(tmp_path,attempts):
    ledger(tmp_path,attempts);before=snapshot(tmp_path)
    value=runner.iterative_admission(tmp_path,'JLR-024',publish=False)
    assert (value is None)==(attempts==0)
    if attempts:assert value['reserved_attempts']==attempts and value['max_calls']==2
    assert snapshot(tmp_path)==before

def test_invalid_ledger_is_not_hidden_as_wait(tmp_path,monkeypatch):
    value=ledger(tmp_path);value['limits']['max_calls']=3;c.save(tmp_path/pilot.LEDGER,value)
    with pytest.raises(ValueError,match='phase ledger changed'):runner.iterative_admission(tmp_path,'JLR-024',publish=False)

@pytest.fixture
def negative(tmp_path):
    import lean_refactor_simp_pilot as simp
    root=tmp_path;tid='JLR-019';contract=c.definitions()[tid]
    names=['jevops/lean.py','tools/lean_refactor_simp_pilot.py','tools/validate_lean_refactor_simp_pilot.py']
    for n in names:c.atomic(root/n,'private scientific bytes\n')
    c.atomic(root/simp.SEED,'private frozen seed\n');inp=c.RUNTIME+'/JLR-017.result.json';c.save(root/inp,{'native':'fixture'})
    c.save(root/c.BASE,{'python_executable':sys.executable})
    profile={'contracts':{tid:contract},'source_sha256':{n:c.sha(root/n) for n in names}}
    data={'status':'NO_SHORTER_WINNER','winner':None,'model_calls':0,'promoted':False,'seed_sha256':c.sha(root/simp.SEED)}
    for n in contract['outputs']:c.save(root/n,data)
    out=c.RUNTIME+'/runs/native/stdout.json';err=c.RUNTIME+'/runs/native/stderr.log';c.save(root/out,data);c.atomic(root/err,'')
    receipt={'schema':'jevops.lean-refactor.stage-run.v2','task_id':tid,'exit_code':1,'error':'execution source drift; revalidate before materializing',
      'archive_path':c.RUNTIME+'/runs/native/receipt.json','outputs':{n:c.sha(root/n) for n in contract['outputs']},
      'binding':{'source_sha256':profile['source_sha256'],'inputs':{inp:c.sha(root/inp)}},
      'executions':[{'argv':[sys.executable,*contract['argv']],'exit_code':0,'timed_out':False,
        'stdout':out,'stdout_sha256':c.sha(root/out),'stderr':err,'stderr_sha256':c.sha(root/err)}],**c.AUTH}
    c.save(root/receipt['archive_path'],receipt);c.save(root/c.RUNTIME/(tid+'.receipt.json'),receipt)
    return root,profile,receipt

def test_negative_validator_reports_current_admission_without_relabeling_failed_receipt(negative,monkeypatch):
    root,profile,receipt=negative;loaded(monkeypatch,root,'JLR-019',profile);before=snapshot(root)
    monkeypatch.setattr(checker,'receipt_binding',forbidden)
    with pytest.raises(checker.GateWait,match='unchanged_negative_trial'):checker.validate(root,'JLR-019')
    assert snapshot(root)==before and c.read(root/c.RUNTIME/'JLR-019.receipt.json')['exit_code']==1

@pytest.mark.parametrize('damage',['archive','raw_stdout','result'])
def test_corrupted_retained_trial_refuses_without_inventing_wait(negative,damage):
    root,profile,receipt=negative
    name=receipt['archive_path'] if damage=='archive' else receipt['executions'][0]['stdout'] if damage=='raw_stdout' else c.RUNTIME+'/JLR-019.result.json'
    if damage=='result':
        data=c.read(root/name);data['winner']='fabricated';c.save(root/name,data)
    else:c.atomic(root/name,'{}\n')
    with pytest.raises((ValueError,KeyError)):runner.simp_admission(root,'JLR-019',profile,publish=False)

@pytest.mark.parametrize('change',['scientific_source','input'])
def test_changed_strategy_or_native_input_does_not_keep_old_negative_gate(negative,change):
    root,profile,receipt=negative;profile=copy.deepcopy(profile)
    if change=='scientific_source':profile['source_sha256']['tools/lean_refactor_simp_pilot.py']='b'*64
    else:c.atomic(root/c.RUNTIME/'JLR-017.result.json','changed input\n')
    assert runner.simp_admission(root,'JLR-019',profile,publish=False) is None


def test_claimed_confirmed_trial_reaches_full_protected_validation_not_budget_wait(tmp_path,monkeypatch):
    root=tmp_path;ledger(root);profile=loaded(monkeypatch,root,'JLR-024')
    c.save(root/c.RUNTIME/'JLR-024.result.json',{'status':'CONFIRMED'})
    c.save(root/c.RUNTIME/'JLR-024.receipt.json',{'schema':'jevops.lean-refactor.stage-run.v2','task_id':'JLR-024'})
    assert runner.current_admission_wait(root,'JLR-024',profile) is None
    class ProtectedPath(Exception):pass
    monkeypatch.setattr(checker,'receipt_binding',lambda *a:(_ for _ in ()).throw(ProtectedPath()))
    with pytest.raises(ProtectedPath):checker.validate(root,'JLR-024')

@pytest.fixture
def negative_search(tmp_path,monkeypatch):
    import validate_lean_refactor_search_extract as protected
    root=tmp_path;tid='JLR-021';contract=c.definitions()[tid]
    # This fixture exercises custody and admission, with an explicit semantic
    # seam below. Construct its complete private run instead of reading the
    # live campaign aliases, which can legitimately become positive, blocked,
    # or bound to a newly reviewed strategy while these tests are running.
    names=['jevops/lean.py','tools/lean_refactor_search_extract.py',
           'tools/validate_lean_refactor_search_extract.py','tests/admission_fixture.py']
    for name in names:c.atomic(root/name,'private admission fixture bytes\n')
    inp=c.RUNTIME+'/JLR-017.result.json';c.save(root/inp,{'native':'unit admission fixture'})
    c.save(root/c.BASE,{'python_executable':sys.executable})
    profile={'contracts':{tid:contract},'source_sha256':{n:c.sha(root/n) for n in names}}
    data={'status':'NO_EXTRACTED_TERM','winner':None,'confirmation':[],
          'model_calls':0,'promoted':False,'fixture_only':True}
    for name in contract['outputs']:c.save(root/name,data)
    out=c.RUNTIME+'/runs/private-search/stdout.json';err=c.RUNTIME+'/runs/private-search/stderr.log'
    c.save(root/out,data);c.atomic(root/err,'')
    receipt={'schema':'jevops.lean-refactor.stage-run.v2','task_id':tid,'exit_code':0,'error':None,
        'archive_path':c.RUNTIME+'/runs/private-search/receipt.json',
        'outputs':{n:c.sha(root/n) for n in contract['outputs']},
        'binding':{'source_sha256':dict(profile['source_sha256']),'inputs':{inp:c.sha(root/inp)}},
        'executions':[{'argv':[sys.executable,*contract['argv']],'exit_code':0,'timed_out':False,
            'stdout':out,'stdout_sha256':c.sha(root/out),'stderr':err,'stderr_sha256':c.sha(root/err)}]}
    c.save(root/receipt['archive_path'],receipt);c.save(root/c.RUNTIME/(tid+'.receipt.json'),receipt)
    # The separate native tests exercise actual negative search semantics.
    monkeypatch.setattr(protected,'validate_negative',lambda r,d:{'acceptance_satisfied':False,
        'unsatisfied_acceptance':'explicit extracted term and cold replay',
        'retry_condition':'changed scientific strategy or native inputs',**c.AUTH})
    def module(selected,name):
        assert selected==root and name=='validate_lean_refactor_search_extract.py','negative admission reached a dependency'
        return protected
    monkeypatch.setattr(c,'module',module)
    return root,profile,receipt

def test_negative_search_admission_retains_real_run_and_skips_all_expensive_dependencies(negative_search,monkeypatch):
    root,profile,receipt=negative_search;before=snapshot(root)
    assert runner.search_admission(root,'JLR-021',profile,publish=False)['acceptance_satisfied'] is False
    assert snapshot(root)==before
    loaded(monkeypatch,root,'JLR-021',profile)
    monkeypatch.setattr(c,'binding',forbidden);monkeypatch.setattr(runner,'process',forbidden)
    refusal=runner.run(root,'JLR-021')
    assert refusal['exit_code']==75 and refusal['reason']=='unchanged_negative_search'
    assert refusal['scientific_run_receipt_preserved']
    assert c.read(root/c.RUNTIME/'JLR-021.receipt.json')==receipt
    assert all((root/n).read_bytes()==raw for n,raw in before.items())

@pytest.mark.parametrize('damage',['archive','stdout','stderr','result','outputs','argv','timed_out'])
def test_negative_search_custody_corruption_is_never_disguised_as_wait(negative_search,damage):
    root,profile,receipt=negative_search
    if damage in ('archive','stdout','stderr','result'):
        name=receipt['archive_path'] if damage=='archive' else c.RUNTIME+'/JLR-021.result.json' if damage=='result' else receipt['executions'][-1][damage]
        c.atomic(root/name,'{}\n')
    else:
        if damage=='outputs':receipt['outputs'].pop(next(iter(receipt['outputs'])))
        elif damage=='argv':receipt['executions'][-1]['argv'].append('--different')
        else:receipt['executions'][-1]['timed_out']=True
        c.save(root/receipt['archive_path'],receipt);c.save(root/c.RUNTIME/'JLR-021.receipt.json',receipt)
    with pytest.raises((ValueError,KeyError)):runner.search_admission(root,'JLR-021',profile,publish=False)

@pytest.mark.parametrize('code,error',[(1,'software crash'),(124,'timeout'),(75,None)])
def test_negative_search_does_not_erase_failed_outer_receipt(negative_search,code,error):
    root,profile,receipt=negative_search;receipt.update(exit_code=code,error=error)
    c.save(root/receipt['archive_path'],receipt);c.save(root/c.RUNTIME/'JLR-021.receipt.json',receipt)
    before=snapshot(root)
    assert runner.search_admission(root,'JLR-021',profile,publish=False) is None
    assert snapshot(root)==before

@pytest.mark.parametrize('change',['strategy','native_input'])
def test_negative_search_retries_only_changed_scientific_evidence(negative_search,change):
    root,profile,receipt=negative_search
    if change=='strategy':profile['source_sha256']['tools/lean_refactor_search_extract.py']='f'*64
    else:c.atomic(root/c.RUNTIME/'JLR-017.result.json','changed native input\n')
    assert runner.search_admission(root,'JLR-021',profile,publish=False) is None

@pytest.mark.parametrize('unrelated', ['tests/admission_fixture.py', 'jevops/arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean'])
def test_unrelated_control_or_test_edit_does_not_rearm_negative_search(negative_search, unrelated):
    root,profile,receipt=negative_search
    profile=copy.deepcopy(profile)
    profile['source_sha256'][unrelated]='e'*64
    before=snapshot(root)
    assert runner.search_admission(root,'JLR-021',profile,publish=False)['reason']=='unchanged_negative_search'
    assert snapshot(root)==before


@pytest.fixture
def frontier_failure(tmp_path):
    root=tmp_path;tid='JLR-020';contract=c.definitions()[tid]
    names=['jevops/arena_lean.py','tools/lean_refactor_native_pin_frontier.py',
           'tools/validate_lean_refactor_native_pin_frontier.py','tools/lean_refactor_coupled_pilot.py',
           'tools/lean_refactor_project_readiness.py']
    for name in names:c.atomic(root/name,'private software failure fixture bytes\n')
    c.save(root/c.BASE,{'python_executable':sys.executable})
    inp=c.RUNTIME+'/JLR-017.result.json';c.save(root/inp,{'native':'fixture input'})
    profile={'contracts':{tid:contract},'source_sha256':{name:c.sha(root/name) for name in names}}
    out=c.RUNTIME+'/runs/failed/stdout.json';err=c.RUNTIME+'/runs/failed/stderr.log'
    c.atomic(root/out,'');c.atomic(root/err,'Traceback (most recent call last):\n'
        '    pin_frontier=frontier.produce(root)\n'
        '    validate(root,reference);c.save(root/INDEX,reference)\n'
        'ValueError: frontier budget/population differs\n')
    receipt={'schema':'jevops.lean-refactor.stage-run.v2','task_id':tid,'exit_code':1,'error':None,
        'outputs':{},'archive_path':c.RUNTIME+'/runs/failed/receipt.json',
        'binding':{'source_sha256':profile['source_sha256'],'inputs':{inp:c.sha(root/inp)}},
        'executions':[{'argv':[sys.executable,*contract['argv']],'exit_code':1,'timed_out':False,
            'stdout':out,'stdout_sha256':c.sha(root/out),'stderr':err,'stderr_sha256':c.sha(root/err)}],**c.AUTH}
    c.save(root/receipt['archive_path'],receipt);c.save(root/c.RUNTIME/(tid+'.receipt.json'),receipt)
    return root,profile,receipt


def test_failed_frontier_refuses_before_compilers_and_keeps_software_failure_distinct(frontier_failure,monkeypatch):
    root,profile,old=frontier_failure;loaded(monkeypatch,root,'JLR-020',profile)
    monkeypatch.setattr(runner,'process',forbidden);monkeypatch.setattr(c,'binding',forbidden)
    before=(root/c.RUNTIME/'JLR-020.receipt.json').read_bytes()
    result=runner.run(root,'JLR-020')
    assert result['exit_code']==75 and result['reason']=='unchanged_frontier_software_failure'
    assert result['blocker_kind']=='software_budget_overrun' and result['failed_exit_code']==1
    assert result['native_pins_verified_by_this_admission']==0 and not result['acceptance_satisfied']
    assert result['scientific_run_receipt_preserved'] and c.read(root/result['archive_path'])==result
    assert (root/c.RUNTIME/'JLR-020.receipt.json').read_bytes()==before
    assert c.read(root/old['archive_path'])==old


def test_frontier_software_wait_never_passes_scientific_validator(frontier_failure,monkeypatch):
    root,profile,_=frontier_failure;loaded(monkeypatch,root,'JLR-020',profile);before=snapshot(root)
    monkeypatch.setattr(checker,'receipt_binding',forbidden)
    with pytest.raises(checker.GateWait,match='unchanged_frontier_software_failure'):
        checker.validate(root,'JLR-020')
    assert snapshot(root)==before


@pytest.mark.parametrize('damage',['archive','stdout','stderr','argv'])
def test_frontier_failure_custody_corruption_is_not_hidden_as_wait(frontier_failure,damage):
    root,profile,old=frontier_failure
    if damage=='archive':c.save(root/old['archive_path'],{})
    elif damage in ('stdout','stderr'):c.atomic(root/old['executions'][0][damage],'changed log\n')
    else:
        old['executions'][0]['argv'].append('--different')
        for name in (old['archive_path'],c.RUNTIME+'/JLR-020.receipt.json'):c.save(root/name,old)
    with pytest.raises(ValueError):runner.frontier_failure_admission(root,'JLR-020',profile,publish=False)


@pytest.mark.parametrize('change',['scientific_source','native_input'])
def test_changed_frontier_implementation_or_native_input_rearms_real_work(frontier_failure,change):
    root,profile,_=frontier_failure;profile=copy.deepcopy(profile)
    if change=='scientific_source':profile['source_sha256']['tools/lean_refactor_native_pin_frontier.py']='f'*64
    else:c.save(root/c.RUNTIME/'JLR-017.result.json',{'changed':'actual input'})
    assert runner.frontier_failure_admission(root,'JLR-020',profile,publish=False) is None


@pytest.mark.parametrize('fault',['other_crash','timeout','claimed_stdout','success','outer_failure'])
def test_other_frontier_failures_cannot_borrow_the_observed_software_wait(frontier_failure,fault):
    root,profile,old=frontier_failure;execution=old['executions'][0]
    if fault=='other_crash':c.atomic(root/execution['stderr'],'ValueError: another crash\n')
    elif fault=='timeout':execution['timed_out']=True
    elif fault=='claimed_stdout':c.save(root/execution['stdout'],{'status':'CONFIRMED'})
    elif fault=='success':old['exit_code']=0
    else:old['error']='different failed outer handoff'
    for field in ('stdout','stderr'):execution[field+'_sha256']=c.sha(root/execution[field])
    for name in (old['archive_path'],c.RUNTIME+'/JLR-020.receipt.json'):c.save(root/name,old)
    if fault=='claimed_stdout':
        with pytest.raises(ValueError,match='claimed a scientific result'):
            runner.frontier_failure_admission(root,'JLR-020',profile,publish=False)
    else:assert runner.frontier_failure_admission(root,'JLR-020',profile,publish=False) is None


def test_clock_ticks_and_control_edits_do_not_rearm_failed_frontier(frontier_failure,monkeypatch):
    root,profile,_=frontier_failure;loaded(monkeypatch,root,'JLR-020',profile)
    before=snapshot(root);first=runner.frontier_failure_admission(root,'JLR-020',profile,publish=False)
    profile['source_sha256']['tests/control_fixture.py']='e'*64
    monkeypatch.setattr(runner.time,'time',lambda:time_after)
    time_after=9_000_000_000
    assert runner.frontier_failure_admission(root,'JLR-020',profile,publish=False)==first
    assert snapshot(root)==before
    monkeypatch.setattr(c,'module',forbidden)
    checker.refresh_wait_probe(root,'JLR-020')
    first_bytes=(root/c.RUNTIME/'native-pin-gate.json').read_bytes()
    time_after+=1800;checker.refresh_wait_probe(root,'JLR-020')
    assert (root/c.RUNTIME/'native-pin-gate.json').read_bytes()==first_bytes


def test_actual_failed_frontier_run_remains_a_failed_source_bound_receipt():
    root=Path('/home/barberb/lift_coding/JevOps')
    # Authenticate the immutable failure, rather than requiring every future
    # source revision to remain gated by the mutable latest-receipt pointer.
    path=root/c.RUNTIME/'runs/JLR-020-9cfd1e73b26e4d65ad081409627edc60/receipt.json'
    assert c.sha(path)=='e81465f82a2151227519f820d83f0fb45be74120a8854ca198604750e73c8151'
    receipt=c.read(path)
    assert receipt['task_id']=='JLR-020' and receipt['exit_code']==1 and receipt['error'] is None
    assert receipt['archive_path']==str(path.relative_to(root))
    execution=receipt['executions'][-1]
    assert execution['exit_code']==1 and execution['timed_out'] is False
    for name in ('stdout','stderr'):
        assert c.sha(root/execution[name])==execution[name+'_sha256']
    assert (root/execution['stdout']).read_bytes()==b''
    assert (root/execution['stderr']).read_text().rstrip().endswith('ValueError: frontier budget/population differs')



@pytest.mark.parametrize('unused', ['jevops/arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean'])
def test_unused_compiled_cold_backend_does_not_repeat_frontier_software_failure(frontier_failure, unused):
    root, profile, receipt = frontier_failure
    profile = copy.deepcopy(profile)
    profile['source_sha256'][unused] = 'a' * 64
    before = snapshot(root)
    result = runner.frontier_failure_admission(root, 'JLR-020', profile, publish=False)
    assert result['reason'] == 'unchanged_frontier_software_failure'
    assert snapshot(root) == before


@pytest.mark.parametrize('unused', ['jevops/arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean'])
def test_unused_compiled_sources_do_not_rearm_retained_negative_simp(negative, unused):
    root, profile, receipt = negative
    profile = copy.deepcopy(profile)
    profile['source_sha256'][unused] = 'b' * 64
    before = snapshot(root)
    value = runner.simp_admission(root, 'JLR-019', profile, publish=False)
    assert value['reason'] == 'unchanged_negative_trial'
    assert value['acceptance_satisfied'] is False
    assert snapshot(root) == before


@pytest.mark.parametrize('kind', ['simp', 'frontier', 'search'])
def test_original_native_checker_remains_scientific_for_spent_admission(negative, frontier_failure, negative_search, kind):
    root, profile, receipt = {'simp': negative, 'frontier': frontier_failure, 'search': negative_search}[kind]
    profile = copy.deepcopy(profile)
    profile['source_sha256']['jevops/lean/ArenaCheck.lean'] = 'c' * 64
    before = snapshot(root)
    call = {'simp': runner.simp_admission, 'frontier': runner.frontier_failure_admission, 'search': runner.search_admission}[kind]
    tid = {'simp': 'JLR-019', 'frontier': 'JLR-020', 'search': 'JLR-021'}[kind]
    assert call(root, tid, profile, publish=False) is None
    assert snapshot(root) == before
