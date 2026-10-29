"""Private artifact tests for held source review; never refresh a live owner."""
import copy
import json
import os
import re
import shutil
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
        'test_lean_refactor_native_pin_frontier','test_lean_refactor_operational_faults',
        'test_lean_refactor_admission_waits','test_lean_refactor_search_extract','test_lean_refactor_activation_audit')


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
    base={'taskboard':'bootstrap.todo.md','provider':'grok_cli','model':'grok-4.7',
          'accelerator_source':str(root/'external/private-framework')}
    for name in c.CONTROL_MODULES:
        c.atomic(Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/rescue'/name,'# private operational source\n')
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
    # The completed fixture must already carry its actual closed registration;
    # a maintenance extension is forbidden from repairing its historical block.
    first=next(iter(c.definitions()));contract=c.definitions()[first]
    text=board.read_text();block=c.task_blocks(text)[first]
    outputs=[*contract['outputs'],c.RUNTIME+'/project-gate.json']
    amended=block.replace('original-output.json',', '.join(outputs))
    amended += '- Execution inputs: '+c.PROFILE+'\n- Implementation timeout seconds: '+str(contract['timeout'])+'\n- Retry on changed evidence: true\n'
    board.write_text(text.replace(block,amended,1))
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
    accelerator=c.read(ROOT/c.BASE)['accelerator_source']
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


@pytest.fixture
def scientific_registration(tmp_path):
    """Actual closed loader against owned source/board artifacts, no producers."""
    root=tmp_path/'scientific';root.mkdir()
    canonical=ROOT
    base=c.read(canonical/c.BASE);base['accelerator_source']=str(root/'external/framework')
    c.save(root/c.BASE,base);goals=c.read(canonical/c.GOALS);c.save(root/c.GOALS,goals)
    historical=c.read(canonical/c.PROFILE)
    for name in {*historical['source_sha256'], 'tools/lean_refactor_search_extract.py',
                 'tools/validate_lean_refactor_search_extract.py','tests/test_lean_refactor_search_extract.py',
                 'jevops/structural_training.py', 'jevops/arena_compiled.py', 'tests/test_arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean',
                 'tools/lean_refactor_activation_audit.py',
                 'tools/validate_lean_refactor_activation_audit.py','tests/test_lean_refactor_activation_audit.py',
                 'config/lean_refactor_arena_20261026_provider_freeze.json',
                 *[str(Path(c.read(canonical/c.BASE)['accelerator_source'])/name) for name in (
                     'ipfs_accelerate_py/agent_supervisor/todo_daemon/llm.py',
                     'ipfs_accelerate_py/agent_supervisor/todo_daemon/budget_policy.py',
                     'test/api/test_agent_supervisor_llm_budget_policy.py')]}:
        target=Path(name)
        if target.is_absolute():
            target=Path(base['accelerator_source'])/target.relative_to(
                Path(c.read(canonical/c.BASE)['accelerator_source']))
        else:target=root/name
        c.atomic(target,'# owned fixture source '+target.name+'\n')
    for name in ('tools/lean_refactor_operational_faults.py','tools/validate_lean_refactor_operational_faults.py',
                 'tests/test_lean_refactor_operational_faults.py','tests/test_lean_refactor_admission_waits.py'):
        c.atomic(root/name,'# private fault implementation fixture\n')
    # Operational modules are deliberately outside historical scientific source bindings.
    for name in c.CONTROL_MODULES:
        c.atomic(Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/rescue'/name,
                 '# owned current operational fixture source\n')
    # The real loader now executes the closed compiled-source registry. Keep
    # that registry and every declared input genuine inside this owned fixture;
    # relocate only external paths into its private framework tree.
    compiled=c.module(canonical,'lean_refactor_compiled_registry_v1.py')
    inventory=compiled.inventory();relocated={}
    original_framework=Path(c.read(canonical/c.BASE)['accelerator_source'])
    for name,digest in inventory['retained'].items():
        source_path=canonical/name
        relative=Path(name)
        if relative.is_absolute():
            relative=Path(base['accelerator_source'])/relative.relative_to(original_framework)
        else:relative=root/name
        relative.parent.mkdir(parents=True,exist_ok=True)
        assert c.sha(source_path)==digest
        shutil.copyfile(source_path,relative)
        assert c.sha(relative)==digest
        relocated[str(relative) if Path(name).is_absolute() else name]=digest
    for name in (*compiled.LOCAL,*[Path(name).name for name in compiled.TESTS]):
        category='tests' if 'tests/'+name in compiled.TESTS else 'tools'
        destination=root/category/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(canonical/category/name,destination)
    inventory['retained']=relocated
    c.save(root/'tools/lean_refactor_compiled_sources_v1.json',inventory)
    blocks=[]
    for task in goals['tasks']:
        tid=task['id'];contract=c.definitions().get(tid)
        status='completed' if int(tid.split('-')[1])<=15 else 'pending' if contract else 'planned'
        lines=['## '+tid+' '+task['title'],'- Status: '+status,'- Depends on: '+', '.join(task['depends_on'])]
        if contract:
            outputs=list(contract['outputs']);extra={'JLR-023':'resource-gate.json','JLR-016':'project-gate.json',
              'JLR-035':'release-gate.json','JLR-024':'iterative-admission-gate.json','JLR-020':'native-pin-gate.json',
              'JLR-019':'simp-admission-gate.json','JLR-021':'search-admission-gate.json'}.get(tid)
            if extra:outputs.append(c.RUNTIME+'/'+extra)
            lines += ['- Deterministic command: python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid,
              '- Validation: python3 tools/check_lean_refactor_stage_v2.py --validate-task '+tid,
              '- Outputs: '+', '.join(outputs),'- Provider role: deterministic',
              '- Implementation timeout seconds: '+str(contract['timeout'])]
        else:lines += ['- Deterministic command: '+task['deterministic_command'],'- Validation: '+task['validation']]
        blocks.append('\n'.join(lines))
    c.atomic(root/c.BOARD,'\n\n'.join(blocks)+'\n')
    profile={'schema':'jevops.lean-refactor.execution.v2','contracts':c.definitions(),
      'source_sha256':c.sources(root),'goals_sha256':c.sha(root/c.GOALS),
      'base_profile_sha256':c.sha(root/c.BASE),'phase_budget':{'calls':0,'max_calls':0}}
    c.save(root/c.PROFILE,profile)
    assert c.load(root)[0]==profile
    return root,profile,base


@pytest.mark.parametrize('name',('lane_resume.py','supervisor_watchdog.py','planned_work_watchdog.py'))
def test_operational_disk_edit_is_observed_without_invalidating_scientific_source(scientific_registration,name):
    root,profile,base=scientific_registration
    before=c.control_plane_observation(root)
    path=Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/rescue'/name
    c.atomic(path,'# independently changed operational policy\n')
    assert c.load(root)[0]==profile and c.sources(root)==profile['source_sha256']
    after=c.control_plane_observation(root)
    assert before['source_sha256'][str(path)]!=after['source_sha256'][str(path)]
    assert after['scientific_acceptance_authority'] is False
    assert all(not any(p.endswith('/rescue/'+n) for n in c.CONTROL_MODULES) for p in profile['source_sha256'])


@pytest.mark.parametrize('name',('tools/run_lean_refactor_stage_v2.py','tools/check_lean_refactor_stage_v2.py',
    'jevops/arena_lean.py','jevops/arena_compiled.py','tests/test_arena_compiled.py','jevops/lean/ArenaAuditCheck.lean','tests/test_lean_refactor_runtime_lease.py','tools/provision_leanstral_20261024.py',
    'tools/leanstral-inference-20261024.json','tools/lean_refactor_operational_faults.py'))
def test_scientific_native_model_guard_and_tests_remain_strict(scientific_registration,name):
    root,_,_=scientific_registration;c.atomic(root/name,'# unreviewed scientific edit\n')
    with pytest.raises(ValueError,match='execution source drift'):c.load(root)


@pytest.mark.parametrize('kind',['route_code','base_route','goal_acceptance','phase_budget'])
def test_route_target_goal_and_budget_changes_are_not_operational_exceptions(scientific_registration,kind):
    root,profile,base=scientific_registration
    if kind=='route_code':c.atomic(Path(base['accelerator_source'])/'ipfs_accelerate_py/llm_router.py','# changed route\n')
    elif kind=='base_route':base['model']='grok-4.6';c.save(root/c.BASE,base)
    elif kind=='goal_acceptance':
        goals=c.read(root/c.GOALS);goals['tasks'][0]['acceptance']='invented acceptance';c.save(root/c.GOALS,goals)
    else:profile['phase_budget']['max_calls']=1;c.save(root/c.PROFILE,profile)
    with pytest.raises(ValueError):c.load(root)


def test_missing_operational_source_and_broken_native_parser_still_refuse(scientific_registration,monkeypatch):
    root,profile,base=scientific_registration
    path=Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/rescue/lane_resume.py';path.unlink()
    with pytest.raises(ValueError,match='ordinary source'):c.load(root)
    c.atomic(path,'# restored owned operational source\n')
    assert c.load(root)[0]==profile
    from ipfs_accelerate_py.agent_supervisor.rescue import lane_resume
    monkeypatch.setattr(lane_resume,'parse_deterministic_command',lambda *args,**kw:None)
    monkeypatch.setattr(c,'bootstrap_validate',lambda *args:None)
    board={task['id']:(None,None,None,{'status':'completed'}) for task in c.read(root/c.GOALS)['tasks']}
    actual_module=c.module
    monkeypatch.setattr(c,'module',lambda root,name:SimpleNamespace(load_plan=lambda *_:{'board':board})
        if name=='check_lean_refactor_plan.py' else actual_module(root,name))
    with pytest.raises(ValueError,match='non-native argv'):c.preflight(root)


def test_legacy_mixed_source_profile_requires_explicit_review_not_silent_restamp(scientific_registration):
    root,profile,base=scientific_registration
    profile['source_sha256'].update(c.control_plane_observation(root)['source_sha256']);c.save(root/c.PROFILE,profile)
    before=(root/c.PROFILE).read_bytes()
    with pytest.raises(ValueError,match='execution source drift'):c.load(root)
    assert (root/c.PROFILE).read_bytes()==before


@pytest.mark.parametrize('name',('policy', 'adapter', 'guard', 'guard_tests'))
def test_provider_freeze_and_enforcing_sources_cannot_drift_silently(scientific_registration,name):
    root,_,base=scientific_registration
    paths={'policy':root/'config/lean_refactor_arena_20261026_provider_freeze.json',
           'adapter':Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/todo_daemon/llm.py',
           'guard':Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/todo_daemon/budget_policy.py',
           'guard_tests':Path(base['accelerator_source'])/'test/api/test_agent_supervisor_llm_budget_policy.py'}
    retained=c.module(root,'lean_refactor_compiled_registry_v1.py').inventory()['retained']
    expected=('retained active source/evidence changed: '+re.escape(str(paths[name]))
              if str(paths[name]) in retained else 'execution source drift')
    profile_before=(root/c.PROFILE).read_bytes()
    c.atomic(paths[name],'# unreviewed provider budget change\n')
    with pytest.raises(ValueError,match=expected):c.load(root)
    assert (root/c.PROFILE).read_bytes()==profile_before


@pytest.fixture
def overlay_registration(scientific_registration):
    root,profile,base=scientific_registration
    original=c.read(root/c.GOALS);derived=copy.deepcopy(original)
    for task in derived['tasks']:
        if task['id'] in c.CONTINUATION_OVERRIDES:task['depends_on']=c.CONTINUATION_OVERRIDES[task['id']]
    c.save(root/c.CONTINUATION_GOALS,derived)
    reviews={}
    for tid in ('JLR-011','JLR-015'):
        name='implementation_plan/proposals/'+tid+'.review.json';c.save(root/name,{'original_review_fixture':tid})
        reviews[tid]={'path':name,'sha256':c.sha(root/name)}
    overlay={'schema':'jevops.lean-refactor.continuation-plan.v1','original_goals_sha256':c.sha(root/c.GOALS),
      'derived_goals_path':c.CONTINUATION_GOALS,'derived_goals_sha256':c.sha(root/c.CONTINUATION_GOALS),
      'dependency_overrides':copy.deepcopy(c.CONTINUATION_OVERRIDES),'review_receipts':reviews}
    c.save(root/c.CONTINUATION_PLAN,overlay)
    return root,profile,overlay


def test_explicit_overlay_changes_only_two_dependencies_and_default_plan_stays_original(overlay_registration):
    root,profile,_=overlay_registration;original=(root/c.GOALS).read_bytes()
    assert c.effective_goals(root,profile)==c.read(root/c.GOALS)
    metadata=c.continuation_metadata(root,c.CONTINUATION_PLAN,profile['goals_sha256'])
    updated={**profile,'continuation_plan':metadata};effective=c.effective_goals(root,updated)
    original_json=c.read(root/c.GOALS)
    for old,new in zip(original_json['tasks'],effective['tasks']):
        if old['id'] in c.CONTINUATION_OVERRIDES:assert {**new,'depends_on':old['depends_on']}==old
        else:assert new==old
    text=(root/c.BOARD).read_text()
    for tid,deps in c.CONTINUATION_OVERRIDES.items():
        block=c.task_blocks(text)[tid];text=text.replace(block,__import__('re').sub(r'^- Depends on: .*$',
          '- Depends on: '+', '.join(deps),block,flags=__import__('re').M),1)
    assert c.load(root,profile=updated,board_text=text)[2]['JLR-033']['depends_on']==['JLR-015']
    assert (root/c.GOALS).read_bytes()==original


@pytest.mark.parametrize('damage',['title','acceptance','budget','task_id','task_added','policy','work_package','review','override','top_key'])
def test_continuation_cannot_change_meaning_bounds_population_or_review(overlay_registration,damage):
    root,profile,overlay=overlay_registration;derived=c.read(root/c.CONTINUATION_GOALS)
    if damage=='review':overlay['review_receipts']['JLR-015']['sha256']='0'*64
    elif damage=='override':overlay['dependency_overrides']['JLR-021']=['JLR-017']
    elif damage=='top_key':overlay['arbitrary_waiver']=True
    else:
        task=next(t for t in derived['tasks'] if t['id']=='JLR-021')
        if damage=='title':task['title']='changed meaning'
        elif damage=='acceptance':task['acceptance']='automatic success'
        elif damage=='budget':task['bounds']['router_calls']=1
        elif damage=='task_id':task['id']='JLR-099'
        elif damage=='task_added':derived['tasks'].append(copy.deepcopy(task))
        elif damage=='policy':derived['policy']['proof_authority']=True
        else:task['work_package']['experiment']='changed experiment'
        c.save(root/c.CONTINUATION_GOALS,derived);overlay['derived_goals_sha256']=c.sha(root/c.CONTINUATION_GOALS)
    c.save(root/c.CONTINUATION_PLAN,overlay)
    with pytest.raises(ValueError):c.continuation_metadata(root,c.CONTINUATION_PLAN,profile['goals_sha256'])


@pytest.mark.parametrize('tid',['JLR-021','JLR-033'])
@pytest.mark.parametrize('damage',['completed','pending','executed'])
def test_dependency_overlay_requires_unexecuted_currently_planned_task(overlay_registration,tid,damage):
    root,_,_=overlay_registration;text=(root/c.BOARD).read_text()
    for current in c.CONTINUATION_OVERRIDES:
        block=c.task_blocks(text)[current];text=text.replace(block,block.replace('- Status: pending','- Status: planned'),1)
    block=c.task_blocks(text)[tid]
    if damage=='executed':c.save(root/c.RUNTIME/(tid+'.receipt.json'),{'real_prior_execution_fixture':True})
    else:text=text.replace(block,block.replace('- Status: planned','- Status: '+damage),1)
    with pytest.raises(ValueError,match='planned|executed'):c.continuation_board(text,root)


@pytest.mark.parametrize('argv',[['--continuation-plan','x.json'],
    ['--continuation-plan','x.json','--refresh-tests','x.xml'],
    ['--continuation-plan','x.json','--refresh-tests','x.xml','--source-only']])
def test_overlay_cli_requires_explicit_quiescent_refresh(campaign,monkeypatch,argv):
    f=campaign;monkeypatch.setattr(c,'ROOT',f.root);monkeypatch.setattr(sys,'argv',['review.py',*argv]);before=file_snapshot(f.root)
    with pytest.raises(SystemExit) as error:c.main()
    assert error.value.code==2 and file_snapshot(f.root)==before


@pytest.fixture
def continuation_owner(quiescent_owner):
    f=quiescent_owner;root=f.root
    goals=json.loads((ROOT/c.GOALS).read_text());c.save(root/c.GOALS,goals)
    f.old['goals_sha256']=c.sha(root/c.GOALS);f.old['contracts'].pop('JLR-033')
    c.save(root/c.PROFILE,f.old);f.originals[c.PROFILE]=(root/c.PROFILE).read_bytes()
    text=f.board.read_text();block=c.task_blocks(text)['JLR-033'];text=text.replace(block,block.replace('- Status: pending','- Status: planned')+'- Depends on: JLR-015, JLR-022\n',1)
    text += '\n## JLR-021 Original immutable title\n- Status: planned\n- Depends on: JLR-017, JLR-019\n- Acceptance: Original immutable acceptance\n'
    f.board.write_text(text)
    derived=copy.deepcopy(goals)
    for task in derived['tasks']:
        if task['id'] in c.CONTINUATION_OVERRIDES:task['depends_on']=c.CONTINUATION_OVERRIDES[task['id']]
    c.save(root/c.CONTINUATION_GOALS,derived)
    reviews={}
    for tid in ('JLR-011','JLR-015'):
        path='implementation_plan/proposals/'+tid+'.review.json';c.save(root/path,{'actual_private_review':tid})
        reviews[tid]={'path':path,'sha256':c.sha(root/path)}
    overlay={'schema':'jevops.lean-refactor.continuation-plan.v1','original_goals_sha256':c.sha(root/c.GOALS),
      'derived_goals_path':c.CONTINUATION_GOALS,'derived_goals_sha256':c.sha(root/c.CONTINUATION_GOALS),
      'dependency_overrides':copy.deepcopy(c.CONTINUATION_OVERRIDES),'review_receipts':reviews};c.save(root/c.CONTINUATION_PLAN,overlay)
    manifest=c.read(root/c.LANES);manifest['planned_work_policy']={'goals_path':c.CONTINUATION_GOALS}
    c.save(root/c.LANES,manifest);c.save(root/f.cfg['runtime_manifest'],manifest)
    return f


def test_reviewed_continuation_publishes_only_allowed_frontier_and_preserves_completed_block(continuation_owner):
    f=continuation_owner;before=c.task_blocks(f.board.read_text());goal=(f.root/c.GOALS).read_bytes();budget=c.read(f.root/f.budget_path)
    result=c.refresh(f.root,f.junit,quiescent_maintenance=True,continuation_plan=c.CONTINUATION_PLAN)
    assert result['valid'] and f.child.poll() is None and f.hold.exists()
    profile=c.read(f.root/c.PROFILE);after=c.task_blocks(f.board.read_text())
    assert profile['continuation_plan']['sha256']==c.sha(f.root/c.CONTINUATION_PLAN)
    assert after['JLR-016']==before['JLR-016']
    assert '- Status: pending' in after['JLR-033'] and '- Depends on: JLR-015\n' in after['JLR-033']
    assert after['JLR-021']==before['JLR-021'].replace('JLR-017, JLR-019','JLR-017, JLR-011')
    assert (f.root/c.GOALS).read_bytes()==goal and c.read(f.root/f.budget_path)==budget


def test_continuation_late_plan_mutation_refuses_publication_under_same_owned_hold(continuation_owner,monkeypatch):
    f=continuation_owner;profile=(f.root/c.PROFILE).read_bytes();board=f.board.read_bytes();prior=c.preflight
    def changed(root,**kwargs):
        result=prior(root,**kwargs);goals=c.read(root/c.CONTINUATION_GOALS);goals['tasks'][0]['title']='concurrent plan edit';c.save(root/c.CONTINUATION_GOALS,goals);return result
    monkeypatch.setattr(c,'preflight',changed)
    with pytest.raises(ValueError,match='derived continuation goals changed'):c.refresh(f.root,f.junit,quiescent_maintenance=True,continuation_plan=c.CONTINUATION_PLAN)
    assert (f.root/c.PROFILE).read_bytes()==profile and f.board.read_bytes()==board and f.hold.exists()


@pytest.fixture
def closed_review_campaign(tmp_path):
    """Copy strict source/goal/board metadata; no native proof is fabricated."""
    import shutil
    root=tmp_path/'closed-campaign';root.mkdir()
    for name in c.sources(ROOT):
        relative=Path(name)
        if relative.is_absolute():continue  # canonical router is read-only
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/relative,target)
    for name in (c.PROFILE,c.BASE,c.GOALS,c.BOARD,c.CONTINUATION_PLAN,c.CONTINUATION_GOALS):
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    for item in c.read(ROOT/c.CONTINUATION_PLAN)['review_receipts'].values():
        target=root/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/item['path'],target)
    old=c.read(root/c.PROFILE)
    producer=root/'tools/lean_refactor_native_pin_frontier.py'
    producer.write_text(producer.read_text()+'\n# owned private source-extension fixture\n')
    proposed=copy.deepcopy(old);proposed['source_sha256']=c.sources(root)
    text=(root/c.BOARD).read_text()
    loaded=c.load(root,profile=proposed,board_text=text)
    return root,old,proposed,loaded,text


def test_unpublished_review_uses_closed_candidate_for_nested_load_only(closed_review_campaign):
    root,old,proposed,loaded,text=closed_review_campaign
    before=file_snapshot(root)
    with pytest.raises(ValueError,match='execution source drift'):c.load(root)
    with c._review_profile(root,loaded,text):
        nested=c.load(root)
        assert nested[0]==proposed and nested[2:]==loaded[2:]
        # A caller cannot mutate the context by editing a returned profile.
        nested[0]['phase_budget']['max_calls']=100
        assert c.load(root)[0]['phase_budget']['max_calls']==0
    with pytest.raises(ValueError,match='execution source drift'):c.load(root)
    assert file_snapshot(root)==before


def test_nested_review_still_refuses_new_source_drift(closed_review_campaign):
    root,old,proposed,loaded,text=closed_review_campaign
    with c._review_profile(root,loaded,text):
        source=root/'tools/lean_refactor_native_pin_frontier.py'
        source.write_text(source.read_text()+'\n# later concurrent source change\n')
        with pytest.raises(ValueError,match='execution source drift'):c.load(root)


def test_nested_review_refuses_concurrent_registered_owner_change(closed_review_campaign):
    root,old,proposed,loaded,text=closed_review_campaign
    with c._review_profile(root,loaded,text):
        c.save(root/c.PROFILE,{**old,'unreviewed_concurrent_edit':True})
        with pytest.raises(ValueError,match='registered owner changed'):c.load(root)
    assert c.read(root/c.PROFILE)['unreviewed_concurrent_edit'] is True


def test_review_context_resets_on_protected_rejection(closed_review_campaign):
    root,old,proposed,loaded,text=closed_review_campaign
    with pytest.raises(RuntimeError,match='actual protected refusal'):
        with c._review_profile(root,loaded,text):
            assert c.load(root)[0]==proposed
            raise RuntimeError('actual protected refusal')
    with pytest.raises(ValueError,match='execution source drift'):c.load(root)


def test_unpublished_review_does_not_cross_repository_scope(closed_review_campaign,tmp_path):
    root,old,proposed,loaded,text=closed_review_campaign
    other=tmp_path/'other-repository';other.mkdir()
    with c._review_profile(root,loaded,text):
        with pytest.raises(FileNotFoundError):c.load(other)
        assert c.load(root)[0]==proposed


def test_real_preflight_supplies_same_closed_view_to_nested_validators(closed_review_campaign,monkeypatch):
    root,old,proposed,loaded,text=closed_review_campaign
    tested=root/'private-fixture-junit.xml';junit(tested)
    c.save(root/proposed['tests_receipt'],{'passed':True,'source_sha256':proposed['source_sha256'],
        'junit_path':str(tested.relative_to(root)),'junit_sha256':c.sha(tested)})
    calls=[]
    bootstrap={'board':{tid:(None,None,None,{'status':'completed'}) for tid in loaded[2] if int(tid[-3:])<=15}}
    def validate(selected,tid,*,loaded):
        # The fixture replaces scientific re-execution. The real closed loader
        # is retained, including all source, route, budget and 38 DAG checks.
        assert selected==root and c.load(root)==loaded
        assert c.read(root/c.PROFILE)==old
        calls.append(tid)
        return {'valid':True,'private_fixture_only':True}
    actual_module=c.module
    def module(selected,name):
        if name=='check_lean_refactor_plan.py':return SimpleNamespace(load_plan=lambda r:bootstrap)
        if name=='check_lean_refactor_stage_v2.py':return SimpleNamespace(validate=validate)
        return actual_module(selected,name)
    monkeypatch.setattr(c,'module',module)
    monkeypatch.setattr(c,'bootstrap_validate',lambda *args:None)
    report=c.preflight(root,profile=proposed,board_text=text)
    assert report['valid'] and 'JLR-034' in calls
    assert set(calls)=={tid for tid in proposed['contracts'] if loaded[3][tid]['status']=='completed'}
    assert c.read(root/c.PROFILE)==old
    with pytest.raises(ValueError,match='execution source drift'):c.load(root)


def test_direct_cli_shares_one_review_context_with_imported_validators(tmp_path):
    # Help exercises the genuine direct-entry module alias without running or
    # claiming campaign acceptance. A child cannot inherit a parent ContextVar.
    source=str(Path(c.__file__).resolve())
    code="""import runpy,sys,pathlib
source=sys.argv[1]
sys.argv=[source,'--help']
try:runpy.run_path(source,run_name='__main__')
except SystemExit as exc:
 assert exc.code==0
 import lean_refactor_execution_v2 as imported
 assert pathlib.Path(imported.__file__).resolve()==pathlib.Path(source).resolve()
 assert imported.__name__=='__main__'
 assert imported._PREFLIGHT_VIEW.get() is None
else:raise AssertionError('help must stop before scientific acceptance')
"""
    result=subprocess.run([sys.executable,'-B','-c',code,source],capture_output=True,text=True,
                          timeout=15,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    assert result.returncode==0, result.stderr


@pytest.mark.parametrize('name',(
    'tools/lean_refactor_compiled_registry_v1.py',
    'tools/lean_refactor_compiled_sources_v1.json',
    'tools/lean_refactor_compiled_lineage_v1.py',
    'tools/lean_refactor_compiled_admission_v1.py',
    'tools/lean_refactor_compiled_inputs_v1.py',
    'tools/lean_refactor_compiled_coupled_v1.py',
    'tools/validate_lean_refactor_compiled_coupled_v1.py',
    'tools/lean_refactor_compiled_replay_v1.py',
    'tools/validate_lean_refactor_compiled_replay_v1.py',
    'tests/test_lean_refactor_compiled_canonical_v1.py'))
def test_active_compiled_scientific_sources_cannot_drift(scientific_registration,name):
    root,profile,_=scientific_registration
    path=root/name
    before=path.read_bytes()
    path.write_bytes(before+b'\n# unreviewed active scientific source edit\n')
    with pytest.raises(ValueError):c.load(root)
    assert c.read(root/c.PROFILE)==profile


def test_retained_compiled_native_byte_custody_cannot_drift(scientific_registration):
    root,profile,_=scientific_registration
    registry=c.module(root,'lean_refactor_compiled_registry_v1.py')
    names=[name for name in registry.inventory()['retained']
           if not Path(name).is_absolute() and Path(name).suffix=='.c']
    assert names
    path=root/names[0];path.write_bytes(path.read_bytes()+b'\n/* unreviewed input */\n')
    with pytest.raises(ValueError,match='retained active source/evidence changed'):c.load(root)
    assert c.read(root/c.PROFILE)==profile
