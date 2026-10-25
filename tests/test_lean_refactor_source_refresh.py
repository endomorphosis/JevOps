"""Private artifact tests for held source review; never refresh a live owner."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_execution_v2 as c

SUITES=('test_lean_refactor_execution_v2','test_lean_refactor_project_readiness',
        'test_lean_refactor_runtime_qualification','test_lean_refactor_continuation',
        'test_lean_refactor_span_provenance','test_lean_refactor_baseline_context',
        'test_lean_refactor_source_refresh','test_lean_refactor_metric_audit','test_lean_refactor_simp_pilot',
        'test_lean_refactor_coupled_pilot','test_lean_refactor_iterative_pilot','test_lean_refactor_release_inventory',
        'test_lean_refactor_native_pin_frontier')


def junit(path, *, count=35, fault=None, omit=None):
    root=ET.Element('testsuite',tests=str(count))
    names=[name for name in SUITES if name!=omit]
    for i in range(count):
        case=ET.SubElement(root,'testcase',classname=names[i%len(names)],name='private_case_'+str(i))
        if i==0 and fault:ET.SubElement(case,fault).text='private synthetic failed qualification'
    path.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)


def file_snapshot(root):
    return {str(path.relative_to(root)):path.read_bytes() for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def campaign(tmp_path,monkeypatch):
    root=tmp_path/'campaign';root.mkdir()
    base={'taskboard':'bootstrap.todo.md','provider':'grok_cli','model':'grok-4.7'}
    goals={'schema':'private-research-fixture','tasks':[{'id':'JLR-016'}]}
    c.save(root/c.BASE,base);c.save(root/c.GOALS,goals)
    budget_path='data/private-router-usage.json'
    usage={'calls':17,'max_calls':24,'failures_retained':['real-prior-fixture-attempt']}
    c.save(root/budget_path,usage)
    source=root/'tools/private_source.py';source.parent.mkdir(exist_ok=True);source.write_text('# old implementation\n')
    old_source={'tools/private_source.py':c.sha(source)}
    source.write_text('# reviewed implementation change\n')
    monkeypatch.setattr(c,'sources',lambda selected_root:{'tools/private_source.py':c.sha(selected_root/'tools/private_source.py')})
    old_junit=root/'data/old-tests.xml';junit(old_junit)
    test_receipt=c.RUNTIME+'/focused-tests.json'
    old_approval={'passed':True,'source_sha256':old_source,'junit_path':str(old_junit.relative_to(root)),
                  'junit_sha256':c.sha(old_junit),'observed_at':1,**c.AUTH}
    c.save(root/test_receipt,old_approval)
    earlier=root/c.RUNTIME/'history/earlier-profile.json';c.save(earlier,{'schema':'older immutable fixture'})
    old={'schema':'jevops.lean-refactor.execution.v2','board':c.BOARD,
         'contracts':copy.deepcopy(c.definitions()),'source_sha256':old_source,
         'base_profile_sha256':c.sha(root/c.BASE),'goals_sha256':c.sha(root/c.GOALS),
         'tests_receipt':test_receipt,'phase_budget':{'max_calls':0,'calls':0,
             'previous_usage':usage,'previous_usage_path':budget_path},
         'scientific_route':{'provider':'grok_cli','model':'grok-4.7','actual_llm_router_required':True},
         'previous_profiles':{c.sha(earlier):str(earlier.relative_to(root))}}
    c.save(root/c.PROFILE,old)
    blocks=['# Existing scientific history\nProgram decision: NO_GO\n']
    for i,(tid,contract) in enumerate(c.definitions().items()):
        blocks.append(f'## {tid} Existing task title\n- Status: '+('completed' if i==0 else 'pending')+
          '\n- Outputs: original-output.json\n- Predicted files: original-output.json\n'
          '- Completion: Existing natural completion evidence\n- Evidence: original-immutable-receipt.json\n')
    board=root/c.BOARD;board.parent.mkdir(parents=True,exist_ok=True);board.write_text('\n'.join(blocks))
    c.save(root/c.RUNTIME/'materialization.json',{'old_materialization':'immutable'})
    c.save(root/c.RUNTIME/'activation.json',{'old_activation':'immutable'})
    hold=root/'HOLD';hold.write_text('owned private test hold\n')
    lane={'state_dir':'data/private-lane','state_prefix':'fixture'}
    c.save(root/c.LANES,{'lanes':[lane]})
    status=root/lane['state_dir']/'fixture_status.json'
    c.save(status,{'state':'paused','phase':'operator_hold','active_task_id':'',
                   'active_lease_count':0,'active_leases':[],'heartbeat_at_ms':time.time()*1000})
    actual_junit=root/'data/new-reviewed-tests.xml';junit(actual_junit)
    archive_originals={relative:(root/relative).read_bytes() for relative in
        (c.PROFILE,test_receipt,c.RUNTIME+'/materialization.json',c.RUNTIME+'/activation.json')}
    preflights=[]
    def protected_fixture_preflight(selected_root, *, profile=None, board_text=None):
        # This seam replaces bootstrap/native re-execution only AFTER the real
        # refresh implementation has archived and rebound its actual files.
        assert selected_root==root
        for relative,raw in archive_originals.items():
            digest=__import__('hashlib').sha256(raw).hexdigest()
            archive=root/c.RUNTIME/'history'/(Path(relative).name+'.'+digest)
            assert archive.read_bytes()==raw
        # The new owner and board must still be unpublished while acceptance
        # runs. A rejection must never expose executable, unreviewed stages.
        assert (root/c.PROFILE).read_bytes()==archive_originals[c.PROFILE]
        updated=profile;approval=c.read(root/test_receipt)
        assert updated['source_sha256']==c.sources(root)!=old_source
        assert approval['passed'] is True and approval['source_sha256']==updated['source_sha256']
        assert approval['junit_sha256']==c.sha(actual_junit)
        preflights.append(True)
        return {'valid':True,'private_fixture_only':True,**c.AUTH}
    monkeypatch.setattr(c,'preflight',protected_fixture_preflight)
    return SimpleNamespace(root=root,old=old,board=board,hold=hold,status=status,junit=actual_junit,
                           old_approval=old_approval,originals=archive_originals,preflights=preflights,
                           earlier=earlier,budget_path=budget_path)


def test_source_only_preserves_board_bytes_inode_history_and_budget(campaign,monkeypatch):
    f=campaign;before=f.board.read_bytes();info=f.board.stat();writes=[];original_atomic=c.atomic
    def audit_write(path,text):
        writes.append(path)
        return original_atomic(path,text)
    monkeypatch.setattr(c,'atomic',audit_write)
    result=c.refresh(f.root,f.junit,source_only=True)
    assert result['valid'] is True and f.preflights==[True]
    assert f.board.read_bytes()==before and f.board.stat().st_ino==info.st_ino
    assert f.board.stat().st_mtime_ns==info.st_mtime_ns and f.board not in writes
    current=c.read(f.root/c.PROFILE)
    for field in ('contracts','phase_budget','base_profile_sha256','goals_sha256','scientific_route'):
        assert current[field]==f.old[field]
    assert current['previous_profiles'].items()>=f.old['previous_profiles'].items()
    previous_sha=__import__('hashlib').sha256(f.originals[c.PROFILE]).hexdigest()
    archive=f.root/current['previous_profiles'][previous_sha]
    assert archive.read_bytes()==f.originals[c.PROFILE]
    assert f.earlier.exists()
    metadata=c.read(f.root/c.RUNTIME/'materialization.json')
    assert metadata['source_only_review'] is True and metadata['taskboard_changed'] is False
    assert metadata['board_sha256']==c.sha(f.board)
    assert c.read(f.root/f.old['tests_receipt'])['junit_path']==str(f.junit.relative_to(f.root))
    assert c.read(f.root/f.budget_path)==f.old['phase_budget']['previous_usage']


def test_normal_refresh_still_refuses_operator_hold(campaign):
    f=campaign;before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='operator hold'):c.refresh(f.root,f.junit)
    assert file_snapshot(f.root)==before and not f.preflights


def test_source_only_requires_actual_hold(campaign):
    f=campaign;f.hold.unlink();before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='requires an operator hold'):c.refresh(f.root,f.junit,source_only=True)
    assert file_snapshot(f.root)==before and not f.preflights


@pytest.mark.parametrize('mutation',['changed_argv','new_task','removed_task'])
def test_source_review_cannot_change_or_activate_contracts(campaign,monkeypatch,mutation):
    f=campaign;contracts=copy.deepcopy(c.definitions())
    if mutation=='changed_argv':contracts['JLR-017']['argv'].append('--unreviewed')
    elif mutation=='new_task':contracts['JLR-038']=copy.deepcopy(contracts['JLR-017'])
    else:contracts.pop('JLR-026')
    monkeypatch.setattr(c,'definitions',lambda:contracts)
    before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='cannot register, activate or change'):c.refresh(f.root,f.junit,source_only=True)
    assert file_snapshot(f.root)==before and not f.preflights


@pytest.mark.parametrize('mutation',['base','goals','calls','maximum','previous_usage'])
def test_source_review_refuses_bootstrap_goal_or_budget_drift(campaign,mutation):
    f=campaign
    if mutation in ('base','goals'):
        path=f.root/(c.BASE if mutation=='base' else c.GOALS);value=c.read(path);value['drift']='unreviewed';c.save(path,value)
    elif mutation=='previous_usage':
        path=f.root/f.budget_path;value=c.read(path);value['calls']+=1;c.save(path,value)
    else:
        path=f.root/c.PROFILE;value=c.read(path);value['phase_budget']['calls' if mutation=='calls' else 'max_calls']=1;c.save(path,value)
    before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='changed|budget'):c.refresh(f.root,f.junit,source_only=True)
    assert file_snapshot(f.root)==before and not f.preflights


@pytest.mark.parametrize('change',[{'state':'healthy'},{'phase':'deterministic_command'},
    {'active_task_id':'JLR-017'},{'active_lease_count':1},
    {'heartbeat_at_ms':0},{'heartbeat_at_ms':(time.time()+600)*1000}])
def test_source_review_refuses_active_stale_or_future_ack(campaign,change):
    f=campaign;value=c.read(f.status);value.update(change);c.save(f.status,value);before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='fresh quiescent'):c.refresh(f.root,f.junit,source_only=True)
    assert file_snapshot(f.root)==before and not f.preflights


def test_source_review_refuses_missing_ack_without_writing_approvals(campaign):
    f=campaign;f.status.unlink();before=file_snapshot(f.root)
    with pytest.raises(OSError):c.refresh(f.root,f.junit,source_only=True)
    assert file_snapshot(f.root)==before and not f.preflights


@pytest.mark.parametrize('damage',['failure','error','skipped','too_few','missing_suite'])
def test_new_approval_requires_all_executed_passing_focused_suites(campaign,damage):
    f=campaign
    junit(f.junit,count=29 if damage=='too_few' else 35,
          fault=damage if damage in ('failure','error','skipped') else None,
          omit=SUITES[-1] if damage=='missing_suite' else None)
    before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='tests required|suite missing'):c.refresh(f.root,f.junit,source_only=True)
    assert file_snapshot(f.root)==before and not f.preflights


def test_source_only_cli_requires_refresh_mode_before_any_write(campaign,monkeypatch):
    f=campaign;monkeypatch.setattr(c,'ROOT',f.root)
    monkeypatch.setattr(sys,'argv',['lean_refactor_execution_v2.py','--source-only'])
    before=file_snapshot(f.root)
    with pytest.raises(SystemExit) as error:c.main()
    assert error.value.code==2 and file_snapshot(f.root)==before


@pytest.mark.parametrize('source_only',[False,True])
def test_rejected_semantic_preflight_never_publishes_owner_or_taskboard(campaign,monkeypatch,source_only):
    f=campaign
    if not source_only:f.hold.unlink()
    profile=(f.root/c.PROFILE).read_bytes();board=f.board.read_bytes()
    def reject(root,**proposed):
        assert proposed['profile']['source_sha256']==c.sources(root)
        assert (root/c.PROFILE).read_bytes()==profile and f.board.read_bytes()==board
        raise ValueError('current protected native acceptance rejected')
    monkeypatch.setattr(c,'preflight',reject)
    with pytest.raises(ValueError,match='protected native acceptance'):
        c.refresh(f.root,f.junit,source_only=source_only)
    assert (f.root/c.PROFILE).read_bytes()==profile and f.board.read_bytes()==board


def test_refresh_never_overwrites_concurrent_taskboard_edit(campaign,monkeypatch):
    f=campaign;f.hold.unlink();profile=(f.root/c.PROFILE).read_bytes()
    original=c.preflight
    def concurrent_edit(root,**proposed):
        report=original(root,**proposed)
        f.board.write_text(f.board.read_text()+'\nConcurrent operator evidence\n')
        return report
    monkeypatch.setattr(c,'preflight',concurrent_edit)
    with pytest.raises(ValueError,match='concurrent execution owner/taskboard'):
        c.refresh(f.root,f.junit)
    assert (f.root/c.PROFILE).read_bytes()==profile
    assert f.board.read_text().endswith('Concurrent operator evidence\n')


@pytest.fixture
def quiescent_owner(campaign,monkeypatch):
    """Real canonical native owner, in an owned HOLD-only private repository."""
    f=campaign;root=f.root
    accelerator='/home/barberb/lift_coding/external/ipfs_accelerate'
    base=c.read(root/c.BASE);base.update(python_executable=sys.executable,accelerator_source=accelerator)
    c.save(root/c.BASE,base);f.old['base_profile_sha256']=c.sha(root/c.BASE)
    c.save(root/c.PROFILE,f.old);f.originals[c.PROFILE]=(root/c.PROFILE).read_bytes()
    c.save(root/'data/lean_refactor_arena_20261024/router-budget.json',f.old['phase_budget']['previous_usage'])
    manifest={'todo_path':c.BOARD,'task_header_prefix':'## JLR-','execution_profile':c.PROFILE,
              'lanes':[{'bundle_key':'private-quiescent-registration','state_dir':'data/private-lane','state_prefix':'fixture'}]}
    c.save(root/c.LANES,manifest)
    cfg={'schema':'jevops.persistent-supervisor-watchdog.v1','materialize_planned_work':True,
         'activate_planned_work':False,'reset_campaign_budgets':False,
         'planned_work_mode':'implement_validate_then_activate','supervisor_profile':c.BASE,
         'lane_manifest':c.LANES,'runtime_manifest':'data/live-private-lanes.json'}
    c.save(root/'config/lean_refactor_arena_20261024_watchdog.json',cfg)
    c.save(root/cfg['runtime_manifest'],manifest)
    pid_path=f.status.with_name('fixture_bundle_supervisor.pid')
    argv=[sys.executable,'-B','-m','ipfs_accelerate_py.agent_supervisor.rescue.lane_resume',
          '--repo-root',str(root),'--todo-path',c.BOARD,'--task-header-prefix','## JLR-',
          '--status-path',str(f.status),'--pid-path',str(pid_path),'--log-path',str(root/'native.log'),
          '--bundle-key','private-quiescent-registration','--max-seconds','60']
    environment={'PATH':str(Path(sys.executable).parent)+':/usr/bin:/bin','HOME':str(root),
                 'PYTHONPATH':accelerator,'PYTHONDONTWRITEBYTECODE':'1'}
    with (root/'native-output.log').open('wb') as log:
        child=subprocess.Popen(argv,cwd=root,env=environment,stdin=subprocess.DEVNULL,
                               stdout=log,stderr=log,start_new_session=True)
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if child.poll() is not None:raise AssertionError((root/'native-output.log').read_text())
                try:
                    current=c.read(f.status)
                    if current.get('pid')==child.pid and current.get('phase')=='operator_hold':break
                except (OSError,ValueError):pass
                time.sleep(.03)
            else:raise AssertionError('private native fixture did not acknowledge HOLD')
            f.child=child;f.cfg=cfg;f.pid_path=pid_path
            original_preflight=c.preflight
            def proposed(root,**kwargs):
                result=original_preflight(root,**kwargs)
                result['implemented']=list(kwargs['profile']['contracts'])
                return result
            monkeypatch.setattr(c,'preflight',proposed)
            # Domain acceptance above is deliberately fixture-only. This seam
            # checks that actual publication preceded actual activation.
            def published(root):
                profile=c.read(root/c.PROFILE)
                assert profile['source_sha256']==c.sources(root)
                assert profile['contracts']==c.definitions()
                return profile,base,{},{}
            monkeypatch.setattr(c,'load',published)
            yield f
        finally:
            if child.poll() is None:child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)


def test_explicit_quiescent_review_uses_real_paused_owner_and_keeps_hold(quiescent_owner):
    f=quiescent_owner;fence=c.quiescent_maintenance_fence(f.root)
    assert fence['pid']==f.child.pid and fence['start_ticks']
    hold=f.hold.read_bytes();marker=f.hold.stat();prior_manifest=(f.root/c.LANES).read_bytes()
    result=c.refresh(f.root,f.junit,quiescent_maintenance=True)
    assert result['valid'] is True and f.hold.read_bytes()==hold
    assert f.hold.stat().st_ino==marker.st_ino and f.child.poll() is None
    assert (f.root/c.LANES).read_bytes()==prior_manifest
    assert c.read(f.root/f.cfg['runtime_manifest'])==c.read(f.root/c.LANES)
    activation=c.read(f.root/c.RUNTIME/'activation.json')
    assert activation['quiescent_maintenance_review'] and activation['operator_hold_retained']
    assert activation['router_calls_added']==0
    assert c.read(f.root/c.RUNTIME/'materialization.json')['quiescent_maintenance_review']


def test_quiescent_review_can_materialize_a_reviewed_planned_definition_only(quiescent_owner):
    f=quiescent_owner;tid='JLR-035'
    f.old['contracts'].pop(tid);c.save(f.root/c.PROFILE,f.old)
    f.originals[c.PROFILE]=(f.root/c.PROFILE).read_bytes()
    original=f.board.read_text();header='## '+tid+' '
    begin=original.index(header);end=original.find('\n## JLR-',begin)
    if end<0:end=len(original)
    block=original[begin:end].replace('- Status: pending','- Status: planned',1)
    block+='- Deterministic command: planned-producer-not-yet-activated\n'
    block+='- Validation: planned-validator-not-yet-activated\n'
    block+='- Implementation timeout seconds: 1\n'
    f.board.write_text(original[:begin]+block+original[end:])
    previous=f.board.read_bytes();old_profile=(f.root/c.PROFILE).read_bytes()
    c.refresh(f.root,f.junit,quiescent_maintenance=True)
    assert '- Status: pending' in f.board.read_text()[begin:]
    assert 'python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid in f.board.read_text()
    archive=f.root/c.RUNTIME/'history'/(f.board.name+'.'+__import__('hashlib').sha256(previous).hexdigest())
    assert archive.read_bytes()==previous
    assert old_profile in [p.read_bytes() for p in (f.root/c.RUNTIME/'history').iterdir()]
    assert f.hold.exists() and f.child.poll() is None


@pytest.mark.parametrize('fault',['materialize_false','activation_true','budgets_reset','wrong_mode','scope'])
def test_quiescent_review_requires_existing_narrow_user_authorization(campaign,fault):
    f=campaign;path=f.root/'config/lean_refactor_arena_20261024_watchdog.json'
    cfg={'materialize_planned_work':True,'activate_planned_work':False,'reset_campaign_budgets':False,
         'planned_work_mode':'implement_validate_then_activate','supervisor_profile':c.BASE,'lane_manifest':c.LANES}
    if fault=='materialize_false':cfg['materialize_planned_work']=False
    elif fault=='activation_true':cfg['activate_planned_work']=True
    elif fault=='budgets_reset':cfg['reset_campaign_budgets']=True
    elif fault=='wrong_mode':cfg['planned_work_mode']='activate_only'
    else:cfg['lane_manifest']='other.json'
    c.save(path,cfg);before=file_snapshot(f.root)
    with pytest.raises(ValueError,match='authorization'):c.refresh(f.root,f.junit,quiescent_maintenance=True)
    # The real private owner may emit a new heartbeat; protected data stays exact.
    for name in (c.PROFILE,c.BOARD,f.old['tests_receipt']):assert (f.root/name).read_bytes()==before[name]


def test_quiescent_review_rechecks_kernel_children(quiescent_owner,monkeypatch):
    f=quiescent_owner;path=Path('/proc')/str(f.child.pid)/'task'/str(f.child.pid)/'children'
    original=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda self,*a,**kw:'123456\n' if self==path else original(self,*a,**kw))
    with pytest.raises(ValueError,match='still has children'):c.quiescent_maintenance_fence(f.root)


def test_quiescent_review_refuses_recycled_or_foreign_pidfile(quiescent_owner):
    f=quiescent_owner;f.pid_path.write_text(str(os.getpid()))
    with pytest.raises(ValueError,match='PID/status'):c.quiescent_maintenance_fence(f.root)


def test_quiescent_review_refuses_active_stale_missing_or_forged_ack(quiescent_owner,monkeypatch):
    f=quiescent_owner;read=c.read;original=read(f.status)
    for change in ({'active_task_id':'JLR-024'},{'active_lease_count':1},
                   {'active_leases':[{'task_id':'JLR-024'}]},{'heartbeat_at_ms':0},
                   {'active_lease_count':False},{'pid':os.getpid()}):
        value={**original,**change}
        with monkeypatch.context() as local:
            local.setattr(c,'read',lambda path,**kw:value if path==f.status else read(path,**kw))
            with pytest.raises(ValueError):c.quiescent_maintenance_fence(f.root)


def test_quiescent_review_hold_loss_during_acceptance_never_publishes(quiescent_owner,monkeypatch):
    f=quiescent_owner;profile=(f.root/c.PROFILE).read_bytes();board=f.board.read_bytes()
    original=c.preflight
    def lose_hold(root,**kwargs):
        result=original(root,**kwargs);f.hold.unlink();return result
    monkeypatch.setattr(c,'preflight',lose_hold)
    with pytest.raises(ValueError,match='operator hold'):c.refresh(f.root,f.junit,quiescent_maintenance=True)
    assert (f.root/c.PROFILE).read_bytes()==profile and f.board.read_bytes()==board


@pytest.mark.parametrize('argv',[['--quiescent-maintenance'],['--source-only','--quiescent-maintenance','--refresh-tests','x.xml']])
def test_explicit_maintenance_cli_needs_refresh_and_cannot_mix_review_modes(campaign,monkeypatch,argv):
    f=campaign;monkeypatch.setattr(c,'ROOT',f.root);monkeypatch.setattr(sys,'argv',['review.py',*argv]);before=file_snapshot(f.root)
    with pytest.raises(SystemExit) as error:c.main()
    assert error.value.code==2 and file_snapshot(f.root)==before
