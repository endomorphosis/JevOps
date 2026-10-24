"""Actual subprocess and native lifecycle checks; no campaign proof fixtures."""
import copy
import importlib.util
import json
import os
import socket
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_execution_v2 as c
import run_lean_refactor_stage_v2 as runner
import check_lean_refactor_stage_v2 as validator

@pytest.fixture(autouse=True)
def canonical_framework_path(monkeypatch):
    # Datasets may prepend its vendored fork during import. Qualify the source
    # configured by this campaign after test collection has imported producers.
    source=c.read(ROOT/c.BASE)['accelerator_source']
    monkeypatch.syspath_prepend(source)

def test_unimplemented_stages_have_no_registered_action():
    assert set(c.definitions())=={'JLR-016','JLR-017','JLR-018','JLR-019','JLR-020','JLR-023','JLR-026'}
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
