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


from types import SimpleNamespace

def capacity_evidence(tmp_path, tag='v4.29.1'):
    volume = tmp_path/'volume'
    volume.mkdir()
    archive = volume/'retained.zst'
    archive.write_bytes(b'retained compiler fixture; never a proof')
    s = archive.stat()
    item = {'archive_root': 'lean-'+tag[1:]+'-linux', 'path': str(archive),
            'identity': {'device': s.st_dev, 'inode': s.st_ino, 'bytes': s.st_size,
                         'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns},
            'regular_file_bytes': 2_000_000_000, 'sha256': 'historical-only'}
    path = tmp_path/f.c.RUNTIME/'maintenance-0253-pin-archive-probe.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'archives': [item]}))
    return volume, archive, path, item


def test_prepared_exact_pin_is_considered_before_missing_pin_without_changing_population(tmp_path):
    requested = [('v4.29.1','original-first'), ('v4.27.0','original-second')]
    home = tmp_path/'elan'
    binary = home/'toolchains/leanprover--lean4---v4.27.0/bin/lean'
    binary.parent.mkdir(parents=True)
    binary.write_text('fixture compiler path; not executed')
    binary.chmod(0o755)
    assert f.preparation_order(requested, home) == list(reversed(requested))
    assert requested == [('v4.29.1','original-first'), ('v4.27.0','original-second')]


def test_unprepared_pins_retain_frozen_order(tmp_path):
    frozen = [('v4.29.1','first'), ('v4.27.0','second')]
    assert f.preparation_order(frozen, tmp_path/'absent') == frozen


def test_capacity_refusal_is_cheap_and_cannot_hash_archive_or_contact_network(tmp_path, monkeypatch):
    volume, archive, _, _ = capacity_evidence(tmp_path)
    monkeypatch.setattr(f.os,'statvfs',lambda p:SimpleNamespace(f_bavail=100, f_frsize=1024**2))
    def forbidden(*a,**kw):
        raise AssertionError('admission cannot hash compiler archives or run external commands')
    monkeypatch.setattr(f,'command',forbidden)
    monkeypatch.setattr(f.c,'sha',forbidden)
    blocker = f.retained_archive_capacity(tmp_path, volume, 'v4.29.1')
    assert blocker['reason'] == 'retained archive extraction exceeds capped-volume reserve'
    assert blocker['required_regular_file_bytes'] == 2_000_000_000
    assert 'original 8 GiB cap' in blocker['retry_condition']


def test_sufficient_capacity_does_not_claim_proof_or_start_installer(tmp_path, monkeypatch):
    volume, _, _, _ = capacity_evidence(tmp_path)
    monkeypatch.setattr(f.os,'statvfs',lambda p:SimpleNamespace(f_bavail=4096,f_frsize=1024**2))
    assert f.retained_archive_capacity(tmp_path,volume,'v4.29.1') is None


def test_replaced_archive_requires_authentication(tmp_path):
    volume, archive, _, _ = capacity_evidence(tmp_path)
    archive.write_text('changed archive')
    with pytest.raises(ValueError,match='identity changed'):
        f.retained_archive_capacity(tmp_path,volume,'v4.29.1')


def test_other_pin_cannot_reuse_wrong_archive_capacity(tmp_path):
    volume, _, _, _ = capacity_evidence(tmp_path)
    assert f.retained_archive_capacity(tmp_path,volume,'v4.27.0') is None


def test_missing_diagnostic_has_no_allocation_or_network_effect(tmp_path):
    assert f.retained_archive_capacity(tmp_path,tmp_path,'v4.27.0') is None


def test_ambiguous_archive_fails_closed(tmp_path):
    volume, _, path, item = capacity_evidence(tmp_path)
    path.write_text(json.dumps({'archives':[item,item]}))
    with pytest.raises(ValueError,match='ambiguous'):
        f.retained_archive_capacity(tmp_path,volume,'v4.29.1')


def test_preparation_allocation_keeps_inventory_and_acceptance_inside_original_cap():
    assert f.MAX_SECONDS == 360
    assert f.preparation_timeout(1360, now=1000) > 100
    assert f.preparation_timeout(1360, now=1000) + f.PREPARATION_RESERVE_SECONDS <= 360
    assert f.preparation_timeout(1360, now=1100) == f.preparation_timeout(1360, now=1000) - 100
    assert f.preparation_timeout(1360, now=1361) == 0


@pytest.mark.parametrize('inventory_delay',[60,185])
def test_producer_allocates_import_window_and_records_later_capacity_blocker(tmp_path,monkeypatch,inventory_delay):
    """Exercise orchestration with a controlled clock; fixtures attest no proofs."""
    from jevops import arena_lean
    import lean_refactor_metric_audit as metric
    clock=[1000.0];calls=[]
    monkeypatch.setattr(f.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(f.c,'held',lambda root:[])
    monkeypatch.setattr(metric,'resource_snapshot',lambda root:{'eligible':True})
    monkeypatch.setattr(f.c,'sha',lambda path:'fixture-source-digest')
    requested=[('v4.29.1','frozen-one'),('v4.27.0','frozen-two')]
    record={'name':f.TARGET,'source':'strata','version_info':[{k:v} for k,v in requested]}
    monkeypatch.setattr(f,'plan',lambda *args:requested)
    monkeypatch.setattr(f,'validate',lambda *args:({'rows':[]},{}))
    def pinned(home,tag):
        if tag=='v4.29.1':raise ValueError('missing exact compiler')
        return tmp_path/'exact-compiler'
    monkeypatch.setattr(arena_lean,'pinned_lean',pinned)
    def capacity(root,volume,tag):
        calls.append(('capacity',tag,clock[0]))
        return {'pin':tag,'reason':'retained archive extraction exceeds capped-volume reserve',
                'retry_condition':'authenticate partial tree; never enlarge the cap'}
    monkeypatch.setattr(f,'retained_archive_capacity',capacity)
    def no_installer(*args,**kw):raise AssertionError('capacity-blocked pin cannot invoke installer')
    monkeypatch.setattr(f,'command',no_installer)
    volume=tmp_path/'volume';volume.mkdir();(volume/'logs').mkdir()
    def preparation(m,current,tag,commit,pilot,work,elan,deadline,output):
        calls.append(('prepare',tag,deadline))
        assert current==record and tag=='v4.27.0' and deadline==1180
        clock[0]=deadline
        return {'provision_error':'bounded fixture imports incomplete'}
    monkeypatch.setattr(f,'prepare_exact_pin',preparation)
    def readiness(args):
        calls.append(('produce',args.provision,args.timeout_seconds))
        assert args.provision is False and args.build_imports is False
        clock[0]+=inventory_delay
        result={'provision_error':'bounded fixture imports incomplete','rows':[
            {'name':f.TARGET,'lean_tag':tag,'git_commit':commit,'project':{},
             'status':'UNAVAILABLE','capability_gaps':['fixture imports incomplete']}
            for tag,commit in requested]}
        args.output.write_text(json.dumps(result));return result
    module=SimpleNamespace(records=lambda:[record],MAX_BYTES=8*1024**3,
        bootstrap_volume=lambda *args:({},volume),produce=readiness)
    monkeypatch.setattr(f.c,'module',lambda *args:module)
    if inventory_delay>f.PREPARATION_RESERVE_SECONDS:
        with pytest.raises(f.FrontierDeadline):f.produce(tmp_path)
        assert not (tmp_path/f.INDEX).exists()
        assert list((tmp_path/f.PILOT/'deadline-runs').glob('*/interruption.json'))
        return
    reference=f.produce(tmp_path)
    report=json.loads((tmp_path/reference['path']).read_text())
    assert calls[0]==('prepare','v4.27.0',1180)
    assert calls[1][0:2]==('capacity','v4.29.1')
    assert calls[2]==('produce',False,1)
    assert report['requested_pins']==[list(pair) for pair in requested]
    assert report['errors'][-1]['pin']=='v4.29.1'
    assert report['model_calls']==0 and report['proof_authority'] is False
    assert all(row['sample'] is None for row in report['rows'])
    assert report['wall_seconds']<=f.MAX_SECONDS+15


# Regression cases for the bounded full-inventory reserve.
def setup_pin(tmp_path, monkeypatch, *, group_commit='frozen', clock=None):
    from jevops import arena_lean
    calls=[];clock=[1000.] if clock is None else clock
    monkeypatch.setattr(f.time,'monotonic',lambda:clock[0])
    record={'name':f.TARGET,'source':'strata','url':'https://example.invalid/owned-fixture',
            'version_info':[{'v4.27.0':'frozen'}]}
    def clone(repository,commit,project,volume,deadline):
        calls.append(('clone',repository,commit,deadline))
        project.mkdir(parents=True)
        (project/'lean-toolchain').write_text('leanprover/lean4:v4.27.0\n')
    def dependencies(project,volume,deadline):
        calls.append(('dependencies',deadline));return 'exact fixture dependencies'
    def build(project,environment,current,lean,volume,deadline):
        calls.append(('build',environment,current,deadline));clock[0]+=60
        return {'compile_invocations':1,'proofs_verified':0}
    def forbidden(*args,**kwargs):
        raise AssertionError('per-pin preparation cannot run a full inventory')
    module=SimpleNamespace(records=lambda:[record],
        group_for=lambda *args:{'repository':record['url'],'git_commit':group_commit,'problems':[f.TARGET]},
        clone_exact=clone,dependencies=dependencies,build_imports=build,produce=forbidden,inventory=forbidden)
    monkeypatch.setattr(arena_lean,'pinned_lean',lambda home,tag:tmp_path/'exact-owned-compiler')
    return module,record,calls,clock


def test_exact_preparation_retains_native_recipe_and_absolute_deadline(tmp_path,monkeypatch):
    module,record,calls,clock=setup_pin(tmp_path,monkeypatch)
    report=f.prepare_exact_pin(module,record,'v4.27.0','frozen',tmp_path,tmp_path,tmp_path/'elan',
                               1180,tmp_path/'preparation.json')
    assert [c[0] for c in calls]==['clone','dependencies','build']
    assert all(c[-1]==1180 for c in calls)
    assert calls[-1][2]==record and report['provision_error'] is None
    assert report['proofs_verified']==0 and report['proof_authority'] is False
    assert report['completion_authority'] is False and report['model_calls']==0
    assert json.loads((tmp_path/'preparation.json').read_text())==report


def test_wrong_exact_commit_cannot_start_preparation(tmp_path,monkeypatch):
    module,record,calls,_=setup_pin(tmp_path,monkeypatch,group_commit='changed')
    with pytest.raises(ValueError,match='exact preparation group differs'):
        f.prepare_exact_pin(module,record,'v4.27.0','frozen',tmp_path,tmp_path,tmp_path/'elan',1180,tmp_path/'receipt.json')
    assert not calls and not (tmp_path/'receipt.json').exists()


def test_elapsed_preparation_window_cannot_start_work(tmp_path,monkeypatch):
    module,record,calls,_=setup_pin(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='bounded preparation admission deadline'):
        f.prepare_exact_pin(module,record,'v4.27.0','frozen',tmp_path,tmp_path,tmp_path/'elan',999,tmp_path/'receipt.json')
    assert not calls


def test_native_preparation_failure_is_retained_without_readiness_claim(tmp_path,monkeypatch):
    module,record,calls,_=setup_pin(tmp_path,monkeypatch)
    def fail(*args):raise RuntimeError('actual native compiler exceeded bounded fixture window')
    module.build_imports=fail
    report=f.prepare_exact_pin(module,record,'v4.27.0','frozen',tmp_path,tmp_path,tmp_path/'elan',1180,tmp_path/'receipt.json')
    assert report['provision_error']=='actual native compiler exceeded bounded fixture window'
    assert report['build'] is None and report['proofs_verified']==0
    assert 'rows' not in report and 'ready_pin_count' not in report


@pytest.mark.parametrize('inventory_seconds',[139.67,175.])
def test_frontier_runs_one_full_inventory_inside_unchanged_cap(tmp_path,monkeypatch,inventory_seconds):
    from jevops import arena_lean
    import lean_refactor_metric_audit as metric
    clock=[1000.];calls=[]
    monkeypatch.setattr(f.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(f.c,'held',lambda root:[])
    monkeypatch.setattr(metric,'resource_snapshot',lambda root:{'eligible':True})
    monkeypatch.setattr(f.c,'sha',lambda path:'operational-fixture-source-hash')
    requested=[('v4.29.1','frozen-one'),('v4.27.0','frozen-two')]
    record={'name':f.TARGET,'source':'strata','version_info':[{tag:commit} for tag,commit in requested]}
    monkeypatch.setattr(f,'plan',lambda *args:requested)
    def validate(root,reference):
        report=json.loads((root/reference['path']).read_text())
        assert report['wall_seconds']<=f.MAX_SECONDS+15
        return report,{}
    monkeypatch.setattr(f,'validate',validate)
    monkeypatch.setattr(arena_lean,'pinned_lean',lambda *args:tmp_path/'existing-exact-compiler')
    def prepare(m,rec,tag,commit,pilot,volume,elan,deadline,output):
        calls.append(('prepare',tag,deadline))
        assert deadline==1180 and rec==record
        clock[0]=deadline
        return {'provision_error':'bounded actual preparation window consumed'}
    monkeypatch.setattr(f,'prepare_exact_pin',prepare)
    def inventory(args):
        calls.append(('full_inventory',args.provision))
        assert args.provision is False and args.build_imports is False
        clock[0]+=inventory_seconds
        result={'provision_error':None,'rows':[
            {'name':f.TARGET,'lean_tag':tag,'git_commit':commit,'project':{},
             'status':'UNAVAILABLE','capability_gaps':['bounded fixture imports incomplete']}
            for tag,commit in requested]}
        args.output.write_text(json.dumps(result));return result
    volume=tmp_path/'volume';(volume/'logs').mkdir(parents=True)
    module=SimpleNamespace(records=lambda:[record],MAX_BYTES=8*1024**3,
        bootstrap_volume=lambda *args:({},volume),produce=inventory)
    monkeypatch.setattr(f.c,'module',lambda *args:module)
    reference=f.produce(tmp_path)
    report=json.loads((tmp_path/reference['path']).read_text())
    assert calls==[('prepare','v4.29.1',1180.),('full_inventory',False)]
    assert report['wall_seconds']==pytest.approx(180+inventory_seconds)
    assert report['requested_pins']==[list(p) for p in requested]
    assert report['model_calls']==0 and all(row['sample'] is None for row in report['rows'])
    assert f.MAX_SECONDS==360 and f.PREPARATION_RESERVE_SECONDS==180


# Real process timers qualify interruption/ownership only, never Lean proofs.
import signal
import subprocess
import threading
import os


def deadline_receipt(root):
    paths=list((root/f.PILOT/'deadline-runs').glob('*/interruption.json'))
    assert len(paths)==1
    return c.read(paths[0])


def test_real_whole_frontier_timer_escapes_inner_exception_handlers_without_publishing(tmp_path,monkeypatch):
    old=tmp_path/f.INDEX;c.save(old,{'old':'accepted earlier reference'});raw=old.read_bytes();inode=old.stat().st_ino
    monkeypatch.setattr(f,'MAX_SECONDS',.08)
    caught=[]
    def full_inventory(root,budget):
        budget.phase='real fixture inventory'
        try:time.sleep(10)
        except Exception:caught.append('incorrectly swallowed whole deadline')
        raise AssertionError('deadline returned a fake success')
    monkeypatch.setattr(f,'_produce',full_inventory)
    start=time.monotonic()
    with pytest.raises(f.FrontierDeadline,match='real fixture inventory'):f.produce(tmp_path)
    assert .06<=time.monotonic()-start<1 and not caught
    report=deadline_receipt(tmp_path)
    assert report['actual_wall_seconds']>=report['maximum_seconds']==.08
    assert not report['index_reference_returned'] and report['native_pins_verified_by_this_refusal']==0
    assert old.read_bytes()==raw and old.stat().st_ino==inode


def test_command_interrupted_by_whole_deadline_reaps_own_child_and_retains_actual_raw_logs(tmp_path):
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])
    try:
        with pytest.raises(f.FrontierDeadline):
            with f.whole_frontier_budget(tmp_path,seconds=.2):
                f.command([sys.executable,'-c','import os,time;print(os.getpid(),flush=True);time.sleep(10)'],
                          tmp_path,tmp_path,timeout=10,label='whole-deadline-child')
        observation=c.read(next((tmp_path/'logs').glob('*.json')))
        child=int(Path(observation['stdout']).read_text().strip())
        assert observation['interrupted'] and observation['interruption_type']=='FrontierDeadline'
        assert observation['exit_code']==-signal.SIGKILL and observation['timed_out'] is False
        assert not Path('/proc',str(child)).exists() and sentinel.poll() is None
        for key in ['stdout','stderr']:assert c.sha(Path(observation[key]))==observation[key+'_sha256']
    finally:
        sentinel.terminate();sentinel.wait(timeout=3)


def test_prior_signal_handler_and_empty_timer_are_restored_after_success_and_failure(tmp_path):
    original=signal.getsignal(signal.SIGALRM)
    def previous(*args):raise AssertionError('prior handler unexpectedly fired')
    signal.signal(signal.SIGALRM,previous)
    try:
        with f.whole_frontier_budget(tmp_path,seconds=.2):pass
        assert signal.getsignal(signal.SIGALRM) is previous and signal.getitimer(signal.ITIMER_REAL)==(0.,0.)
        with pytest.raises(RuntimeError):
            with f.whole_frontier_budget(tmp_path,seconds=.2):raise RuntimeError('real semantic fixture rejection')
        assert signal.getsignal(signal.SIGALRM) is previous and signal.getitimer(signal.ITIMER_REAL)==(0.,0.)
    finally:signal.signal(signal.SIGALRM,original)


def test_existing_timer_is_refused_untouched_and_never_extended(tmp_path):
    old=signal.getsignal(signal.SIGALRM);signal.signal(signal.SIGALRM,lambda *_:None)
    signal.setitimer(signal.ITIMER_REAL,2,.5)
    try:
        before=signal.getitimer(signal.ITIMER_REAL)
        with pytest.raises(ValueError,match='existing process real-time timer'):
            with f.whole_frontier_budget(tmp_path,seconds=.2):raise AssertionError('work admitted')
        after=signal.getitimer(signal.ITIMER_REAL)
        assert 1.5<after[0]<=before[0] and after[1]==before[1]==.5
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)


def test_non_main_thread_refuses_before_work_or_timer_changes(tmp_path):
    failures=[];ran=[]
    def execute():
        try:
            with f.whole_frontier_budget(tmp_path,seconds=.2):ran.append(True)
        except ValueError as error:failures.append(str(error))
    thread=threading.Thread(target=execute);thread.start();thread.join(timeout=1)
    assert not thread.is_alive() and not ran and 'main thread' in failures[0]
    assert signal.getitimer(signal.ITIMER_REAL)==(0.,0.)


@pytest.mark.parametrize('present',[False,True])
def test_deadline_after_pointer_publication_restores_only_own_index_inode(tmp_path,present):
    path=tmp_path/f.INDEX
    if present:c.save(path,{'retained':'exact earlier reference'})
    before=path.read_bytes() if present else None;inode=path.stat().st_ino if present else None
    with pytest.raises(f.FrontierDeadline):
        with f.whole_frontier_budget(tmp_path,seconds=.08) as budget:
            budget.publish({'path':'fully validated private fixture report','sha256':'f'*64})
            time.sleep(1)
    if present:assert path.read_bytes()==before and path.stat().st_ino==inode
    else:assert not path.exists()
    assert deadline_receipt(tmp_path)['index_publication_undone'] is True


def test_deadline_cleanup_never_overwrites_foreign_replacement_pointer(tmp_path):
    path=tmp_path/f.INDEX;c.save(path,{'old':'retained'})
    with pytest.raises(f.FrontierDeadline):
        with f.whole_frontier_budget(tmp_path,seconds=.08) as budget:
            budget.publish({'path':'owned validated fixture','sha256':'a'*64})
            c.save(path,{'foreign':'must remain untouched'});inode=path.stat().st_ino
            time.sleep(1)
    assert c.read(path)=={'foreign':'must remain untouched'} and path.stat().st_ino==inode
    assert deadline_receipt(tmp_path)['index_publication_undone'] is False


def test_foreign_pointer_change_during_staging_fsync_refuses_before_rename(tmp_path,monkeypatch):
    path=tmp_path/f.INDEX;c.save(path,{'old':'retained'});real=os.fsync;injected=[]
    def changed(descriptor):
        real(descriptor)
        if not injected:
            injected.append(True);c.save(path,{'foreign':'published during staging'})
    monkeypatch.setattr(f.os,'fsync',changed)
    with pytest.raises(ValueError,match='foreign frontier index changed'):
        with f.whole_frontier_budget(tmp_path,seconds=.3) as budget:
            budget.publish({'path':'fixture','sha256':'a'*64})
    assert c.read(path)=={'foreign':'published during staging'}


def test_successful_budget_keeps_reference_and_never_labels_deadline(tmp_path):
    reference={'path':'all original semantic checks must already have passed','sha256':'a'*64}
    with f.whole_frontier_budget(tmp_path,seconds=.2) as budget:budget.publish(reference)
    assert c.read(tmp_path/f.INDEX)==reference
    assert not list((tmp_path/f.PILOT/'deadline-runs').glob('*/interruption.json'))


def test_interruption_during_pidfd_setup_still_reaps_actual_owned_child(tmp_path,monkeypatch):
    import os, signal, subprocess
    children=[];original=f.subprocess.Popen
    def spawn(*args,**kwargs):
        child=original(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(f.subprocess,'Popen',spawn)
    def interrupted(pid):raise f.FrontierDeadline('actual launch-boundary fixture')
    monkeypatch.setattr(f.os,'pidfd_open',interrupted)
    with pytest.raises(f.FrontierDeadline,match='launch-boundary'):
        f.command([sys.executable,'-c','import time;time.sleep(10)'],tmp_path,tmp_path,timeout=10)
    assert len(children)==1 and children[0].poll()==-signal.SIGKILL
    assert not Path('/proc/'+str(children[0].pid)).exists()
    observation=c.read(next((tmp_path/'logs').glob('*.json')))
    assert observation['interrupted'] is True and observation['interruption_type']=='FrontierDeadline'
    for name in ('stdout','stderr'):assert c.sha(Path(observation[name]))==observation[name+'_sha256']


def _private_process_live(pid):
    try:return Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[0] not in ('Z','X')
    except FileNotFoundError:return False


def test_actual_leader_exit_on_timeout_cleans_observed_detached_descendant(tmp_path):
    import os,subprocess
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])
    child_pid=None
    script=('import subprocess,sys,time;'
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"],start_new_session=True);'
            'print(p.pid,flush=True);time.sleep(10)')
    try:
        with pytest.raises(ValueError,match='retained observation'):
            f.command([sys.executable,'-c',script],tmp_path,tmp_path,timeout=.3)
        raw=next((tmp_path/'logs').glob('*.stdout')).read_text();child_pid=int(raw.strip())
        until=time.monotonic()+1
        while _private_process_live(child_pid) and time.monotonic()<until:time.sleep(.01)
        assert not _private_process_live(child_pid) and sentinel.poll() is None
        receipt=c.read(next((tmp_path/'logs').glob('*.json')))
        assert receipt['timed_out'] is True and receipt['exit_code']==124
    finally:
        sentinel.terminate();sentinel.wait(timeout=3)
        if child_pid is not None and _private_process_live(child_pid):os.kill(child_pid,9)


def test_global_interrupt_after_leader_exit_has_no_owned_descendant_left(tmp_path,monkeypatch):
    import os,subprocess
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])
    script=('import subprocess,sys,time;'
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"],start_new_session=True);'
            'print(p.pid,flush=True);time.sleep(.2)')
    actual_sha=f.c.sha;child_pid=None
    def delayed_hash(path):
        if str(path).endswith('.stdout'):time.sleep(1)
        return actual_sha(path)
    monkeypatch.setattr(f.c,'sha',delayed_hash)
    try:
        with pytest.raises(f.FrontierDeadline):
            with f.whole_frontier_budget(tmp_path,seconds=.4):
                f.command([sys.executable,'-c',script],tmp_path,tmp_path,timeout=5)
        child_pid=int(next((tmp_path/'logs').glob('*.stdout')).read_text().strip())
        until=time.monotonic()+1
        while _private_process_live(child_pid) and time.monotonic()<until:time.sleep(.01)
        assert not _private_process_live(child_pid) and sentinel.poll() is None
        assert not (tmp_path/f.INDEX).exists()
    finally:
        sentinel.terminate();sentinel.wait(timeout=3)
        if child_pid is not None and _private_process_live(child_pid):os.kill(child_pid,9)


def test_frontier_lock_remains_held_during_deadline_rollback(tmp_path,monkeypatch):
    import subprocess
    before=b'old retained frontier\n';target=tmp_path/f.INDEX;target.parent.mkdir(parents=True);target.write_bytes(before)
    original=f._FrontierBudget.index_identity;attempts=[];deadline_rollback=[False]
    contender=('import fcntl,sys;from pathlib import Path;'
               'p=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);s=p.open("a+");'
               '\ntry:fcntl.flock(s,fcntl.LOCK_EX|fcntl.LOCK_NB)'
               '\nexcept BlockingIOError:sys.exit(75)'
               '\nPath(sys.argv[2]).write_text("foreign acquired writer\\n")')
    old_undo=f._FrontierBudget.undo_deadline_publication
    def undo(self):
        deadline_rollback[0]=True
        return old_undo(self)
    def identity(self):
        observed=original(self)
        if deadline_rollback[0] and self.published_index==observed:
            # Inject a cooperating writer AFTER the identity read, precisely at
            # the previous check->replace gap. It must still lack the fence.
            result=subprocess.run([sys.executable,'-c',contender,str(tmp_path/f.PILOT/'frontier.lock'),str(target)],timeout=3)
            attempts.append(result.returncode)
        return observed
    monkeypatch.setattr(f._FrontierBudget,'undo_deadline_publication',undo)
    monkeypatch.setattr(f._FrontierBudget,'index_identity',identity)
    with pytest.raises(f.FrontierDeadline):
        with f.whole_frontier_budget(tmp_path,seconds=.08) as budget:
            budget.publish({'path':'genuinely-validated-fixture','sha256':'a'*64})
            time.sleep(1)
    assert attempts==[75] and target.read_bytes()==before
    # The same real contender can acquire only AFTER deadline rollback ends.
    result=subprocess.run([sys.executable,'-c',contender,str(tmp_path/f.PILOT/'frontier.lock'),str(target)],timeout=3)
    assert result.returncode==0 and target.read_text()=='foreign acquired writer\n'


@pytest.mark.parametrize('background_thread',[False,True])
def test_first_global_deadline_during_final_snapshot_finishes_owned_cleanup(tmp_path,monkeypatch,background_thread):
    import os,signal,subprocess,threading
    stop=threading.Event();worker=None
    if background_thread:
        worker=threading.Thread(target=lambda:stop.wait(10),daemon=True);worker.start()
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])
    script=('import subprocess,sys,time;'
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"],start_new_session=True);'
            'print(p.pid,flush=True);time.sleep(.15)')
    original=f.CommandProcessTree.snapshot;delays=[];child_pid=None
    prior_mask=signal.pthread_sigmask(signal.SIG_BLOCK,set())
    def delayed_final_snapshot(self):
        if self._owned and not Path('/proc/'+str(self.pid)).exists() and not delays:
            delays.append(True);time.sleep(.35)
        return original(self)
    monkeypatch.setattr(f.CommandProcessTree,'snapshot',delayed_final_snapshot)
    try:
        with pytest.raises(f.FrontierDeadline):
            with f.whole_frontier_budget(tmp_path,seconds=.3):
                f.command([sys.executable,'-c',script],tmp_path,tmp_path,timeout=5)
        child_pid=int(next((tmp_path/'logs').glob('*.stdout')).read_text().strip())
        until=time.monotonic()+1
        while _private_process_live(child_pid) and time.monotonic()<until:time.sleep(.01)
        assert delays==[True] and not _private_process_live(child_pid)
        assert sentinel.poll() is None and not (tmp_path/f.INDEX).exists()
        assert signal.pthread_sigmask(signal.SIG_BLOCK,set())==prior_mask
        assert f._ACTIVE_FRONTIER_BUDGET.get() is None
        receipt=c.read(next((tmp_path/f.PILOT/'deadline-runs').glob('*/interruption.json')))
        assert receipt['actual_wall_seconds']>=.3 and receipt['index_reference_returned'] is False
    finally:
        stop.set()
        if worker is not None:worker.join(timeout=3)
        sentinel.terminate();sentinel.wait(timeout=3)
        if child_pid is not None and _private_process_live(child_pid):os.kill(child_pid,9)
