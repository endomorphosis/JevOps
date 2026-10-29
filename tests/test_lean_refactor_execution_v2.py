"""Actual subprocess and native lifecycle checks; no campaign proof fixtures."""
import copy
import importlib.util
import json
import os
import socket
from pathlib import Path
import sys
import runpy
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_execution_v2 as c
import run_lean_refactor_stage_v2 as runner
import check_lean_refactor_stage_v2 as validator


@pytest.mark.parametrize('configured',[False,True])
def test_owned_stage_child_preserves_only_the_campaign_provider_freeze(tmp_path,monkeypatch,configured):
    key='JEVOPS_REFACTOR_LLM_BUDGET_POLICY'
    monkeypatch.delenv(key,raising=False)
    policy=str(tmp_path/'owned-policy.json')
    if configured:monkeypatch.setenv(key,policy)
    monkeypatch.setenv('PRIVATE_TEST_SHOULD_NOT_FORWARD','synthetic-owned-fixture')
    script='import json,os; print(json.dumps({"policy":os.environ.get("JEVOPS_REFACTOR_LLM_BUDGET_POLICY"),"other":os.environ.get("PRIVATE_TEST_SHOULD_NOT_FORWARD")}))'
    execution=runner.process(tmp_path,{'python_executable':sys.executable,'accelerator_source':str(tmp_path)},
                             ['-c',script],tmp_path/'actual-child',10)
    assert execution['exit_code']==0 and execution['timed_out'] is False
    assert c.read(tmp_path/execution['stdout'])=={'policy':policy if configured else None,'other':None}

@pytest.fixture
def retained_negative_trial(tmp_path):
    import lean_refactor_simp_pilot as pilot
    tid='JLR-019';contract=c.definitions()[tid]
    names=('jevops/lean.py','tools/lean_refactor_simp_pilot.py','tools/validate_lean_refactor_simp_pilot.py')
    for name in names:c.atomic(tmp_path/name,'private scientific source\n')
    c.atomic(tmp_path/pilot.SEED,'private frozen incumbent\n')
    inp=c.RUNTIME+'/JLR-017.result.json';c.save(tmp_path/inp,{'baseline':'native fixture'})
    c.save(tmp_path/c.BASE,{'python_executable':sys.executable})
    profile={'contracts':{tid:contract},'source_sha256':{n:c.sha(tmp_path/n) for n in names}}
    data={'status':'NO_SHORTER_WINNER','winner':None,'model_calls':0,'promoted':False,
          'seed_sha256':c.sha(tmp_path/pilot.SEED)}
    for output in contract['outputs']:c.save(tmp_path/output,data)
    stdout=c.RUNTIME+'/runs/private-native/stdout.json';stderr=c.RUNTIME+'/runs/private-native/stderr.log'
    c.save(tmp_path/stdout,data);c.atomic(tmp_path/stderr,'')
    receipt={'schema':'jevops.lean-refactor.stage-run.v2','task_id':tid,'exit_code':0,'error':None,
             'archive_path':c.RUNTIME+'/runs/private-native/receipt.json',
             'outputs':{o:c.sha(tmp_path/o) for o in contract['outputs']},
             'binding':{'source_sha256':profile['source_sha256'],'inputs':{inp:c.sha(tmp_path/inp)}},
             'executions':[{'argv':[sys.executable,*contract['argv']],'exit_code':0,'timed_out':False,
                'stdout':stdout,'stdout_sha256':c.sha(tmp_path/stdout),
                'stderr':stderr,'stderr_sha256':c.sha(tmp_path/stderr)}],**c.AUTH}
    c.save(tmp_path/receipt['archive_path'],receipt)
    c.save(tmp_path/c.RUNTIME/(tid+'.receipt.json'),receipt)
    originals={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    return tmp_path,profile,receipt,originals

def test_simp_admission_preserves_native_trial_and_stable_gate(retained_negative_trial):
    root,profile,receipt,originals=retained_negative_trial
    first=runner.simp_admission(root,'JLR-019',profile)
    gate=root/c.RUNTIME/'simp-admission-gate.json';before=gate.read_bytes()
    second=runner.simp_admission(root,'JLR-019',profile)
    assert first['exit_code']==second['exit_code']==75
    assert first['acceptance_satisfied'] is False and first['proof_authority'] is False
    assert gate.read_bytes()==before and first['archive_path']!=second['archive_path']
    assert all((root/n).read_bytes()==raw for n,raw in originals.items())

def test_simp_admission_precedes_expensive_prerequisites(retained_negative_trial,monkeypatch):
    root,profile,_,_=retained_negative_trial
    tasks={'JLR-019':{'depends_on':['JLR-017']}}
    board={'JLR-019':{'status':'pending'},'JLR-017':{'status':'completed'}}
    monkeypatch.setattr(c,'load',lambda selected:(profile,{},tasks,board))
    def forbidden(*args,**kwargs):raise AssertionError('unchanged trial must not relaunch native work')
    monkeypatch.setattr(c,'module',forbidden);monkeypatch.setattr(runner,'process',forbidden)
    assert runner.run(root,'JLR-019')['exit_code']==75

def test_simp_admission_retains_failed_outer_handoff_after_real_trial(retained_negative_trial):
    root,profile,receipt,_=retained_negative_trial
    receipt={**receipt,'exit_code':1,'error':'execution source drift; revalidate before materializing'}
    c.save(root/receipt['archive_path'],receipt)
    path=root/c.RUNTIME/'JLR-019.receipt.json';c.save(path,receipt);before=path.read_bytes()
    gate=runner.simp_admission(root,'JLR-019',profile)
    assert gate['exit_code']==75 and gate['stage_run_exit_code']==1
    assert gate['stage_run_error']==receipt['error'] and path.read_bytes()==before
    assert gate['acceptance_satisfied'] is False

def test_simp_admission_does_not_hide_a_producer_crash(retained_negative_trial):
    root,profile,receipt,_=retained_negative_trial
    receipt={**receipt,'exit_code':1,'error':'actual producer crash'}
    c.save(root/receipt['archive_path'],receipt)
    c.save(root/c.RUNTIME/'JLR-019.receipt.json',receipt)
    assert runner.simp_admission(root,'JLR-019',profile) is None
    assert not (root/c.RUNTIME/'simp-admission-gate.json').exists()

@pytest.mark.parametrize('change',['source','baseline','seed'])
def test_simp_admission_allows_changed_scientific_evidence(retained_negative_trial,change):
    import lean_refactor_simp_pilot as pilot
    root,profile,_,_=retained_negative_trial;profile=copy.deepcopy(profile)
    if change=='source':profile['source_sha256']['tools/lean_refactor_simp_pilot.py']='b'*64
    else:c.atomic(root/(pilot.SEED if change=='seed' else c.RUNTIME+'/JLR-017.result.json'),'changed\n')
    assert runner.simp_admission(root,'JLR-019',profile) is None
    assert not (root/c.RUNTIME/'simp-admission-gate.json').exists()

@pytest.mark.parametrize('change',['archive','stdout','result'])
def test_simp_admission_refuses_damaged_evidence_without_relaunch(retained_negative_trial,change):
    root,profile,receipt,_=retained_negative_trial
    name=receipt['archive_path'] if change=='archive' else receipt['executions'][0]['stdout'] if change=='stdout' else c.RUNTIME+'/JLR-019.result.json'
    if change=='result':
        data=c.read(root/name);data['winner']='invented';c.save(root/name,data)
    else:c.atomic(root/name,'{}\n')
    with pytest.raises(ValueError):runner.simp_admission(root,'JLR-019',profile)
    assert not (root/c.RUNTIME/'simp-admission-gate.json').exists()

def test_direct_cli_catches_wait_from_separately_loaded_protected_validator(monkeypatch,capsys):
    # The production subprocess runs as __main__, while the coupled validator
    # imports check_lean_refactor_stage_v2 by name. These must share one class.
    direct=runpy.run_path(str(ROOT/'tools/check_lean_refactor_stage_v2.py'),run_name='_private_cli')
    assert direct['GateWait'] is validator.GateWait is c.GateWait
    monkeypatch.setattr(sys,'argv',['check_lean_refactor_stage_v2.py','--validate-task','JLR-020'])
    def wait(*args):raise validator.GateWait('exact native pins unavailable')
    direct['main'].__globals__['validate']=wait
    direct['main'].__globals__['refresh_wait_probe']=lambda *args:None
    assert direct['main']()==75
    result=json.loads(capsys.readouterr().out)
    assert result['waiting'] is True and result['valid'] is False
    assert result['proof_authority'] is False and result['completion_authority'] is False

def registered_framework(monkeypatch):
    """Import the actual registered control package, including cached modules."""
    import importlib
    source=Path(c.read(ROOT/c.BASE)['accelerator_source']).resolve()
    monkeypatch.syspath_prepend(str(source))
    prefix='ipfs_accelerate_py.agent_supervisor'
    # A prior scientific import can cache a vendored fork even after sys.path
    # is repaired. Evict only foreign control modules and their parent aliases.
    for name in sorted(list(sys.modules),key=lambda key:key.count('.'),reverse=True):
        if name!=prefix and not name.startswith(prefix+'.'):continue
        module=sys.modules.get(name);filename=getattr(module,'__file__',None)
        if filename and not Path(filename).resolve().is_relative_to(source):
            parent,_,leaf=name.rpartition('.')
            if parent in sys.modules and getattr(sys.modules[parent],leaf,None) is module:
                monkeypatch.delattr(sys.modules[parent],leaf)
            monkeypatch.delitem(sys.modules,name)
    root=importlib.import_module('ipfs_accelerate_py')
    monkeypatch.setattr(root,'__path__',[str(source/'ipfs_accelerate_py')])
    for name in (prefix,prefix+'.rescue'):
        package=importlib.import_module(name)
        expected=source/Path(*name.split('.'))
        assert Path(package.__file__).resolve()==expected/'__init__.py'
        monkeypatch.setattr(package,'__path__',[str(expected)])
    actual=importlib.import_module(prefix+'.rescue.lane_resume')
    assert Path(actual.__file__).resolve()==source/'ipfs_accelerate_py/agent_supervisor/rescue/lane_resume.py'
    return actual


@pytest.fixture(autouse=True)
def canonical_framework_path(monkeypatch):
    registered_framework(monkeypatch)


def test_registered_control_origin_replaces_a_previously_cached_vendored_module(tmp_path,monkeypatch):
    import types
    name='ipfs_accelerate_py.agent_supervisor.rescue.lane_resume'
    parent=sys.modules[name.rpartition('.')[0]]
    foreign=types.ModuleType(name);foreign.__file__=str(tmp_path/'vendored/lane_resume.py')
    monkeypatch.setitem(sys.modules,name,foreign);monkeypatch.setattr(parent,'lane_resume',foreign)
    actual=registered_framework(monkeypatch)
    assert actual is not foreign and actual is sys.modules[name]
    assert callable(actual.run_resume_cycle)

def test_unimplemented_stages_have_no_registered_action():
    assert set(c.definitions())=={'JLR-016','JLR-017','JLR-018','JLR-019','JLR-020','JLR-021','JLR-023','JLR-024','JLR-026','JLR-033','JLR-034','JLR-035'}
    assert 'JLR-038' not in c.definitions()

def test_closed_provisioning_is_pinned_bounded_and_separate():
    d=c.definitions()['JLR-016']
    assert d['argv'][d['argv'].index('--tag')+1]=='v4.26.0'
    assert d['timeout']<=900
    assert all(p.startswith(c.RUNTIME+'/') for p in d['outputs'])
    assert '--provision' in d['argv'] and '--build-imports' in d['argv']

def test_runtime_cannot_enable_hash_poll_or_training():
    args=c.definitions()['JLR-023']['argv']
    assert '--inference-smoke' in args and '--start-if-needed' in args
    assert '--rehash-model' not in args and 'train' not in args

def test_iterative_outer_deadline_covers_acceptance_without_expanding_science_budget():
    import lean_refactor_iterative_pilot as pilot
    assert c.definitions()['JLR-024']['timeout']==900
    assert pilot.LIMITS['total_seconds']==240 and pilot.LIMITS['max_calls']==2
    assert pilot.LIMITS['request_timeout_seconds']==90

def test_reviewed_activation_reuses_executed_preflight_across_json_key_order(tmp_path,monkeypatch):
    contracts=c.definitions()
    monkeypatch.setattr(c,'load',lambda root:({'contracts':dict(reversed(list(contracts.items())))},{},{},{}))
    def no_repeat(root):
        raise AssertionError('same actual acceptance must not be needlessly repeated')
    monkeypatch.setattr(c,'preflight',no_repeat)
    c.save(tmp_path/c.PROFILE,{'private_fixture':True})
    c.atomic(tmp_path/c.BOARD,'private fixture board\n')
    c.save(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json',{'calls':22})
    c.save(tmp_path/'config/lean_refactor_arena_20261024_watchdog.json',{
        'activate_planned_work':False,'materialize_planned_work':True,
        'planned_work_mode':'implement_validate_then_activate','runtime_manifest':'data/manifest.json'})
    c.save(tmp_path/c.LANES,{'lanes':[{'bundle_key':'private-fixture-owner'}],
        'execution_profile':c.PROFILE,'todo_path':c.BOARD})
    preflight={'valid':True,'implemented':list(contracts)}
    receipt=c.activate_reviewed(tmp_path,preflight)
    assert receipt['preflight']==preflight and receipt['router_calls_added']==0
    assert receipt['bootstrap_usage_retained']=={'calls':22}
    assert receipt['awaiting_independent_dispatcher_observation'] is True

@pytest.mark.parametrize('marker',['HOLD','OPERATOR_STOP','data/lean_refactor_arena_20261024/lane/HOLD',
    'data/lean_refactor_arena_20261024/lane/OPERATOR_STOP'])
def test_operator_markers(tmp_path,marker):
    p=tmp_path/marker;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
    assert str(p) in c.held(tmp_path)

def test_sha_and_atomic_refuse_symlinks(tmp_path):
    file=tmp_path/'actual';file.write_text('source');link=tmp_path/'link';link.symlink_to(file)
    with pytest.raises(ValueError):c.sha(link)
    with pytest.raises(ValueError):c.atomic(link,'changed')
    assert file.read_text()=='source'

def test_json_cannot_overflow_metadata_bound(tmp_path):
    p=tmp_path/'large';p.write_bytes(b' '*(8*1024**2))
    with pytest.raises(ValueError):c.read(p)

def test_native_trace_envelope_does_not_raise_metadata_or_other_stage_limits(tmp_path):
    p=tmp_path/'trace.json';p.write_text('{"trace":"'+'x'*(9*1024**2)+'"}')
    with pytest.raises(ValueError):c.read(p)
    with pytest.raises(ValueError):c.stage_result(p,'JLR-017')
    assert len(c.stage_result(p,'JLR-026')['trace'])==9*1024**2
    p.write_bytes(b' '*(32*1024**2))
    with pytest.raises(ValueError):c.stage_result(p,'JLR-026')

def test_process_records_actual_exit_and_canonical_path(tmp_path):
    (tmp_path/'worker.py').write_text('import json,os;print(json.dumps({"path":os.environ["PYTHONPATH"]}));raise SystemExit(7)')
    base={'python_executable':sys.executable,'accelerator_source':'/canonical/framework'}
    result=runner.process(tmp_path,base,['worker.py'],tmp_path/'run',10)
    assert result['exit_code']==7 and result['timed_out'] is False
    assert c.read(tmp_path/result['stdout'])['path']=='/canonical/framework:'+str(tmp_path)
    assert c.sha(tmp_path/result['stdout'])==result['stdout_sha256']

def test_process_timeout_is_not_success_and_owned_child_reaped(tmp_path):
    (tmp_path/'worker.py').write_text('import time;time.sleep(60)')
    result=runner.process(tmp_path,{'python_executable':sys.executable,'accelerator_source':str(tmp_path)},
                          ['worker.py'],tmp_path/'run',.05)
    assert result['exit_code']==124 and result['timed_out'] is True

def test_no_ambient_secret_passed_to_deterministic_child(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIVATE_KEY','private-fixture-do-not-print')
    (tmp_path/'worker.py').write_text('import os;print("PRIVATE_KEY" in os.environ)')
    result=runner.process(tmp_path,{'python_executable':sys.executable,'accelerator_source':str(tmp_path)},
                          ['worker.py'],tmp_path/'run',10)
    assert (tmp_path/result['stdout']).read_text().strip()=='False'

@pytest.fixture
def private_user_bus(tmp_path):
    parent=tmp_path/'private-run-user';parent.mkdir()
    runtime=parent/str(os.getuid());runtime.mkdir(mode=0o700)
    bus=socket.socket(socket.AF_UNIX)
    bus.bind(str(runtime/'bus'))
    try:yield parent,runtime
    finally:bus.close()

def test_qualifier_child_receives_only_validated_local_bus_not_ambient_secret(tmp_path,monkeypatch,private_user_bus):
    parent,runtime=private_user_bus
    actual=runner.local_user_bus(runtime_parent=parent,parent_environment={})
    monkeypatch.setattr(runner,'local_user_bus',lambda:actual)
    monkeypatch.setenv('PRIVATE_KEY','fixture-value-never-forward')
    tools=tmp_path/'tools';tools.mkdir()
    (tools/'lean_refactor_runtime_qualification.py').write_text('import os,json\nprint(json.dumps({k:os.environ.get(k) for k in ("XDG_RUNTIME_DIR","DBUS_SESSION_BUS_ADDRESS","PRIVATE_KEY")}))\n')
    result=runner.process(tmp_path,{'python_executable':sys.executable,'accelerator_source':str(tmp_path)},
      ['tools/lean_refactor_runtime_qualification.py','--qualify'],tmp_path/'run',10)
    value=c.read(tmp_path/result['stdout'])
    assert value=={'XDG_RUNTIME_DIR':str(runtime),'DBUS_SESSION_BUS_ADDRESS':'unix:path='+str(runtime/'bus'),'PRIVATE_KEY':None}
    assert result['exit_code']==0

@pytest.mark.parametrize('bad',[{'XDG_RUNTIME_DIR':'/unrelated'},
    {'DBUS_SESSION_BUS_ADDRESS':'tcp:host=unrelated,port=123'},
    {'DBUS_SESSION_BUS_ADDRESS':'unix:path=/unrelated/bus'}])
def test_remote_or_mismatched_bus_environment_is_never_forwarded(private_user_bus,bad):
    with pytest.raises(ValueError,match='noncanonical or remote'):
        runner.local_user_bus(runtime_parent=private_user_bus[0],parent_environment=bad)

@pytest.mark.parametrize('fault',['public_directory','ordinary_file','symlink'])
def test_bus_requires_actual_private_owned_directory_and_socket(private_user_bus,fault):
    parent,runtime=private_user_bus
    if fault=='public_directory':runtime.chmod(0o755)
    elif fault=='ordinary_file':
        (runtime/'bus').unlink();(runtime/'bus').write_text('not a socket')
    else:
        moved=runtime.with_name('real-runtime');runtime.rename(moved);runtime.symlink_to(moved)
    with pytest.raises(ValueError):runner.local_user_bus(runtime_parent=parent,parent_environment={})

def test_failed_actual_qualifier_child_cannot_republish_old_resource_receipt(tmp_path):
    qualification=tmp_path/'data/lean_refactor_runtime_20261024/qualification.json'
    c.save(qualification,{'schema':'jevops.lean-refactor.runtime-qualification.v1','status':'resource_blocked','observed_at':1})
    before=runner.qualification_identity(qualification);old=qualification.read_bytes()
    (tmp_path/'failure.py').write_text('import sys\nsys.stderr.write("actual fixture transport failure\\n")\nraise SystemExit(1)\n')
    started=runner.time.time()
    actual=runner.process(tmp_path,{'python_executable':sys.executable,'accelerator_source':str(tmp_path)},
                          ['failure.py'],tmp_path/'failed-child',10)
    output=tmp_path/'stage-result.json'
    code,error=runner.publish_runtime_result(tmp_path,output,actual,before,started)
    assert code==1 and error and qualification.read_bytes()==old
    result=c.read(output)
    assert result['schema']=='jevops.lean-refactor.stage-failure.v2' and result['stale_qualification_reused'] is False
    assert result['stderr_sha256']==actual['stderr_sha256'] and result['qualifier_exit_code']==1

def test_fresh_actual_child_wait_receipt_is_bound_to_its_stdout_sha(tmp_path,monkeypatch,private_user_bus):
    parent,_=private_user_bus
    bus=runner.local_user_bus(runtime_parent=parent,parent_environment={})
    monkeypatch.setattr(runner,'local_user_bus',lambda:bus)
    tools=tmp_path/'tools';tools.mkdir()
    helper=tools/'lean_refactor_runtime_qualification.py'
    helper.write_text('''import pathlib,json,time,hashlib
p=pathlib.Path.cwd()/'data/lean_refactor_runtime_20261024/qualification.json'
p.parent.mkdir(parents=True,exist_ok=True)
d={'schema':'jevops.lean-refactor.runtime-qualification.v1','observed_at':time.time(),
 'status':'resource_blocked','source_sha256':{'tools/lean_refactor_runtime_qualification.py':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}}
p.write_text(json.dumps(d))
print(json.dumps({'receipt':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'exit_code':75}))
raise SystemExit(75)
''')
    started=runner.time.time()
    actual=runner.process(tmp_path,{'python_executable':sys.executable,'accelerator_source':str(tmp_path)},
                          ['tools/lean_refactor_runtime_qualification.py','--qualify'],tmp_path/'fresh-child',10)
    output=tmp_path/'stage-result.json'
    code,error=runner.publish_runtime_result(tmp_path,output,actual,None,started)
    assert code==75 and error is None and c.read(output)['status']=='resource_blocked'
    assert c.read(output)==c.read(tmp_path/'data/lean_refactor_runtime_20261024/qualification.json')
    envelope=tmp_path/actual['stdout'];value=c.read(envelope);value['sha256']='0'*64;c.save(envelope,value)
    code,error=runner.publish_runtime_result(tmp_path,output,actual,None,started)
    assert code==1 and error and c.read(output)['status']=='failed'

@pytest.mark.parametrize('mutation',['missing','duplicate','tag','commit'])
def test_full_population_rejects_missing_duplicate_or_substituted_pin(mutation):
    rows=[{'name':str(i),'lean_tag':'v1.0.0','git_commit':str(i)} for i in range(36)]
    expected={(r['name'],r['lean_tag'],r['git_commit']) for r in rows}
    if mutation=='missing':rows.pop()
    elif mutation=='duplicate':rows[-1]=rows[0]
    elif mutation=='tag':rows[0]['lean_tag']='v9.0.0'
    else:rows[0]['git_commit']='other'
    with pytest.raises(ValueError):validator.check_matrix(rows,expected)

def test_complete_population_is_not_proof_acceptance():
    rows=[{'name':str(i),'lean_tag':'v1.0.0','git_commit':str(i)} for i in range(36)]
    assert validator.check_matrix(rows,{(r['name'],r['lean_tag'],r['git_commit']) for r in rows}) is None
    with pytest.raises(ValueError):validator.runtime(ROOT,{'schema':'jevops.lean-refactor.runtime-qualification.v1'})

def receipt_fixture(tmp_path,monkeypatch):
    tid='JLR-017';contract=c.definitions()[tid]
    base={'python_executable':sys.executable,'accelerator_source':str(tmp_path)}
    loaded=({'contracts':{tid:contract}},base,{tid:{}},{tid:{}})
    monkeypatch.setattr(c,'load',lambda root:loaded)
    monkeypatch.setattr(c,'binding',lambda *args,**kwargs:{'source':'frozen'})
    out=tmp_path/contract['outputs'][0];c.save(out,{'status':'fixture-only'})
    run=tmp_path/c.RUNTIME/'runs/test';run.mkdir(parents=True)
    c.save(run/'stdout.json',{'status':'fixture-only'});(run/'stderr.log').write_text('')
    execution={'argv':[sys.executable,*contract['argv']],'exit_code':0,'timed_out':False,
               'stdout':str((run/'stdout.json').relative_to(tmp_path)),'stdout_sha256':c.sha(run/'stdout.json'),
               'stderr':str((run/'stderr.log').relative_to(tmp_path)),'stderr_sha256':c.sha(run/'stderr.log')}
    receipt={'schema':'jevops.lean-refactor.stage-run.v2','task_id':tid,'binding':{'source':'frozen'},
      'exit_code':0,'proof_authority':False,'completion_authority':False,'started_at':10,'finished_at':11,
      'outputs':{contract['outputs'][0]:c.sha(out)},'executions':[execution],
      'archive_path':str((run/'receipt.json').relative_to(tmp_path))}
    def publish():
        c.save(run/'receipt.json',receipt);c.save(tmp_path/c.RUNTIME/(tid+'.receipt.json'),receipt)
    publish();return tid,receipt,run,publish

@pytest.mark.parametrize('fault',['exit','binding','argv','interval','authority','stdout','result','archive'])
def test_exit0_and_self_report_cannot_bypass_protected_validation(tmp_path,monkeypatch,fault):
    tid,r,run,publish=receipt_fixture(tmp_path,monkeypatch)
    if fault=='exit':r['exit_code']=1
    elif fault=='binding':r['binding']={'source':'different'}
    elif fault=='argv':r['executions'][0]['argv']=['python3','-c','print("pass")']
    elif fault=='interval':r['finished_at']=100000
    elif fault=='authority':r['proof_authority']=True
    publish()
    if fault=='stdout':(run/'stdout.json').write_text('{"passed":true}')
    elif fault=='result':c.save(tmp_path/c.RUNTIME/(tid+'.result.json'),{'passed':True})
    elif fault=='archive':c.save(run/'receipt.json',{'passed':True})
    with pytest.raises(ValueError):validator.validate(tmp_path,tid)

def test_wait_receipt_is_never_an_acceptance_pass(tmp_path,monkeypatch):
    tid,r,run,publish=receipt_fixture(tmp_path,monkeypatch);r['exit_code']=75;publish()
    with pytest.raises(validator.GateWait):validator.validate(tmp_path,tid)

def test_execution_evidence_authentication_is_not_semantic_acceptance(tmp_path,monkeypatch):
    tid,receipt,run,publish=receipt_fixture(tmp_path,monkeypatch)
    data,checked=validator.execution_evidence(tmp_path,tid)
    assert checked==receipt and data=={'status':'fixture-only'}
    source_module=c.module
    monkeypatch.setattr(c,'module',lambda selected,name:source_module(
        Path('/home/barberb/lift_coding/JevOps'),name))
    with pytest.raises((ValueError,KeyError)):
        validator.validate(tmp_path,tid)

def test_retained_actual_search_producer_is_not_reexecuted_or_relabelled(tmp_path,monkeypatch):
    # Exercise the real archived campaign producer bytes and raw subprocess
    # evidence. Only task selectability is private; acceptance is still pending.
    root=Path('/home/barberb/lift_coding/JevOps')
    # A maintenance test reviews installed candidate bytes in memory before
    # protected registration; it never publishes a profile or acceptance.
    # The actual refresh archives the registered owner before reviewing the
    # extended source snapshot. Keep that historical link in a private fixture
    # so this test also exercises the post-extension receipt path under HOLD.
    historical=tmp_path/'registered-owner.json'
    historical.write_bytes((root/c.PROFILE).read_bytes())
    registered=c.read(root/c.PROFILE)
    proposal={**registered,'source_sha256':c.sources(root),
              'previous_profiles':{**registered.get('previous_profiles',{}),
                                   c.sha(historical):str(historical)}}
    loaded=c.load(root,profile=proposal)
    profile,base,tasks,board=loaded;board=copy.deepcopy(board)
    board['JLR-021']['status']='pending'
    monkeypatch.setattr(c,'load',lambda selected:(profile,base,tasks,board))
    original_module=c.module
    monkeypatch.setattr(c,'module',lambda selected,name:validator if name=='check_lean_refactor_stage_v2.py'
                        else original_module(selected,name))
    def forbidden(*args,**kwargs):raise AssertionError('frozen producer must not run or claim acceptance')
    monkeypatch.setattr(runner,'process',forbidden)
    monkeypatch.setattr(validator,'validate',forbidden)
    names=[c.PROFILE,c.BOARD,'data/lean_refactor_arena_20261024/router-budget.json',
           *[c.RUNTIME+'/'+name for name in ('JLR-021.result.json','JLR-021.partial.json',
                                            'JLR-021.receipt.json','iterative-v1-ledger.json')]]
    before={name:c.sha(root/name) for name in names}
    original=c.read(root/c.RUNTIME/'JLR-021.receipt.json')
    # Authenticate the retained run directly. Calling the production runner
    # from canonical maintenance tests must still refuse the real lane hold.
    actual=runner.retained_search_run(root,'JLR-021',(profile,base,tasks,board))
    assert actual==original and actual['completion_authority'] is False
    assert all(c.sha(root/name)==digest for name,digest in before.items())

def test_operator_hold_precedes_retained_positive_handoff(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'load',lambda selected:({}, {}, {}, {}))
    (tmp_path/'HOLD').write_text('owned fixture marker\n')
    def forbidden(*args,**kwargs):raise AssertionError('a retained producer cannot bypass the operator hold')
    monkeypatch.setattr(runner,'retained_search_run',forbidden)
    monkeypatch.setattr(runner,'process',forbidden)
    with pytest.raises(ValueError,match='operator hold'):
        runner.run(tmp_path,'JLR-021')
    assert (tmp_path/'HOLD').read_text()=='owned fixture marker\n'

@pytest.mark.parametrize('opt_in',[False,True])
def test_native_changed_resource_guard_retries_actual_producer_only_when_registered(tmp_path,opt_in):
    from ipfs_accelerate_py.agent_supervisor.rescue import lane_resume
    c.save(tmp_path/'guard.json',{'available':False})
    (tmp_path/'produce.py').write_text('import json\nfrom pathlib import Path\n'
      'with Path("calls").open("a") as s:s.write("call\\n")\n'
      'if not json.loads(Path("guard.json").read_text())["available"]:raise SystemExit(75)\n'
      'Path("result.json").write_text("verified by independent fixture")\n')
    (tmp_path/'validate.py').write_text('from pathlib import Path\n'
      'if not Path("result.json").exists():raise SystemExit(75)\n'
      'assert Path("result.json").read_text()=="verified by independent fixture"\n')
    (tmp_path/'board.md').write_text('## TEST-001 Resource task\n- Status: pending\n- Depends on:\n'
      '- Deterministic command: python3 produce.py\n- Validation: python3 validate.py\n'
      '- Outputs: result.json, guard.json\n- Acceptance: Independent fixture\n'+
      ('- Retry on changed evidence: true\n' if opt_in else ''))
    def cycle():return lane_resume.run_resume_cycle(repo_root=tmp_path,todo_path=tmp_path/'board.md',
      task_header_prefix='## TEST-',attempt_path=tmp_path/'attempts.json',log_path=tmp_path/'lane.log',
      heartbeat=lambda **kw:None)
    assert cycle()['phase']=='gate_withheld'
    assert len((tmp_path/'calls').read_text().splitlines())==1
    c.save(tmp_path/'guard.json',{'available':True})
    result=cycle()
    if opt_in:
        assert result['phase']=='task_command_passed'
        assert '- Status: completed' in (tmp_path/'board.md').read_text()
        assert len((tmp_path/'calls').read_text().splitlines())==2
    else:
        assert result['phase']=='gate_withheld'
        assert '- Status: pending' in (tmp_path/'board.md').read_text()
        assert len((tmp_path/'calls').read_text().splitlines())==1

def test_native_unchanged_resource_guard_never_repeats_producer(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.rescue import lane_resume
    (tmp_path/'produce.py').write_text('from pathlib import Path\n'
      'with Path("calls").open("a") as s:s.write("call\\n")\nraise SystemExit(75)')
    (tmp_path/'validate.py').write_text('raise SystemExit(75)')
    (tmp_path/'guard.json').write_text('{"available":false}')
    (tmp_path/'board.md').write_text('## TEST-001 Wait\n- Status: pending\n- Depends on:\n'
      '- Deterministic command: python3 produce.py\n- Validation: python3 validate.py\n'
      '- Outputs: guard.json\n- Retry on changed evidence: true\n')
    for _ in range(2):lane_resume.run_resume_cycle(repo_root=tmp_path,todo_path=tmp_path/'board.md',
      task_header_prefix='## TEST-',attempt_path=tmp_path/'attempts.json',log_path=tmp_path/'lane.log',heartbeat=lambda **kw:None)
    assert (tmp_path/'calls').read_text().splitlines()==['call']

def test_project_probe_tracks_real_lock_release_without_reading_project_tree(tmp_path):
    import fcntl
    pilot=tmp_path/'data/lean_refactor_campaign_20261024/project-pilot'
    pilot.mkdir(parents=True)
    with (pilot/'project-readiness.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        first=runner.project_probe(tmp_path)
        assert first['concurrent_preparation'] is True
        assert runner.project_probe(tmp_path)==first
    released=runner.project_probe(tmp_path)
    assert released['concurrent_preparation'] is False and released!=first
    artifact=tmp_path/'data/lean_refactor_campaign_20261024/JLR-016.result.json'
    artifact.write_text('{"preparation_only":true}')
    ready=runner.project_probe(tmp_path)
    assert ready['frozen_artifact_sha256']==c.sha(artifact)
    assert ready['proof_authority'] is False

@pytest.mark.parametrize('damage',['none','archive','producer','scientific_source','input'])
def test_registered_history_retains_native_receipts_and_rejects_drift(tmp_path,monkeypatch,damage):
    producer=tmp_path/'tools/producer.py';producer.parent.mkdir();producer.write_text('original producer')
    scientific=tmp_path/'jevops/kernel.py';scientific.parent.mkdir();scientific.write_text('trusted kernel boundary')
    contract={'argv':['tools/producer.py'],'timeout':60,'outputs':['result.json']}
    old={'contracts':{'JLR-016':contract},'source_sha256':{
        'tools/producer.py':c.sha(producer),'jevops/kernel.py':c.sha(scientific)}}
    path=tmp_path/'history.json';c.save(path,old);digest=c.sha(path)
    loaded=({'contracts':{'JLR-016':contract},'previous_profiles':{digest:'history.json'}},{},{},{})
    historical={'profile_sha256':digest,'inputs':'unchanged'}
    def binding(root,tid,loaded=None,profile_digest=None):
        if profile_digest:return {'profile_sha256':profile_digest,'inputs':'changed' if damage=='input' else 'unchanged'}
        return {'profile_sha256':'current','inputs':'unchanged'}
    monkeypatch.setattr(c,'binding',binding)
    if damage=='archive':path.write_text('{}')
    elif damage=='producer':producer.write_text('changed producer')
    elif damage=='scientific_source':scientific.write_text('changed native boundary')
    if damage=='none':validator.receipt_binding(tmp_path,'JLR-016',{'binding':historical},loaded)
    else:
        with pytest.raises(ValueError):validator.receipt_binding(tmp_path,'JLR-016',{'binding':historical},loaded)
