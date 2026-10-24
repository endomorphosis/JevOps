"""Independent research materialization must survive a queued GPU wait."""
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,json.loads((ROOT/'config/lean_refactor_arena_20261024_supervisor.json').read_text())['accelerator_source'])
from ipfs_accelerate_py.agent_supervisor.rescue.planned_work_watchdog import observe_planned_work

@pytest.mark.parametrize('active',[False,True])
@pytest.mark.parametrize('enabled',[False,True])
def test_independent_frontier_is_observed_without_changing_any_status(tmp_path,active,enabled):
    tasks={'JLR-017':{'status':'completed','depends':[]},
           'JLR-023':{'status':'running' if active else 'pending','depends':[]},
           'JLR-026':{'status':'planned','depends':['JLR-017']}}
    goals={'tasks':[{'id':k,'depends_on':v['depends'],'work_package':{'action':'planned_experiment'}} for k,v in tasks.items()]}
    (tmp_path/'goals.json').write_text(json.dumps(goals))
    before=json.dumps(tasks,sort_keys=True)
    policy={'enabled':True,'goals_path':'goals.json','grace_seconds':1,
            'materialize_independent_frontier':enabled}
    lanes=[{'lane':'gpu','active_task_id':'JLR-023','phase':'resource_wait'}] if active else []
    state={}
    observe_planned_work(policy=policy,repo_root=tmp_path,tasks=tasks,lanes=lanes,state=state,now=10)
    observed=observe_planned_work(policy=policy,repo_root=tmp_path,tasks=tasks,lanes=lanes,state=state,now=12)
    assert observed['materialization_task_ids']==['JLR-026']
    assert observed['state']==('planned_work_unmaterialized' if enabled else 'execution_available')
    assert bool(observed['incidents']) is enabled
    assert observed['completion_authority'] is False
    assert json.dumps(tasks,sort_keys=True)==before

def test_hold_prevents_independent_materialization(tmp_path):
    (tmp_path/'goals.json').write_text(json.dumps({'tasks':[{'id':'JLR-026','depends_on':[]}]}))
    result=observe_planned_work(policy={'enabled':True,'goals_path':'goals.json','materialize_independent_frontier':True},
      repo_root=tmp_path,tasks={'JLR-026':{'status':'planned','depends':[]}},lanes=[],state={},now=10,held=True)
    assert result['state']=='held' and not result['incidents']

@pytest.mark.parametrize('master', ['unbound', 'dead', 'live'])
@pytest.mark.parametrize('terminal_reason', ['resume_duration_elapsed', 'resume_stopped'])
def test_native_watchdog_distinguishes_unbound_master_from_live_owner(tmp_path, monkeypatch, master, terminal_reason):
    import time
    from ipfs_accelerate_py.agent_supervisor.rescue import supervisor_watchdog as w
    state=tmp_path/'lane';state.mkdir()
    (state/'stage_bundle_supervisor.pid').write_text('111\n')
    (state/'stage_status.json').write_text(json.dumps({
        'schema':w.LIFECYCLE_STATUS_SCHEMA,'target_id':'test', 'state':'stopped',
        'phase':'lane_resume_exited','pid':111,'terminal_reason':terminal_reason,
        'heartbeat_at_ms':int((time.time()-1000)*1000)}))
    board=tmp_path/'board.md';board.write_text('## JLR-016 Native prep\n- Status: pending\n- Depends on:\n')
    manifest={'todo_path':str(board),'task_header_prefix':'## JLR-',
              'lanes':[{'bundle_key':'test','state_dir':str(state),'state_prefix':'stage'}]}
    if master!='unbound':
        marker=tmp_path/'master.pid';marker.write_text('222\n');manifest['master_pid_path']=str(marker)
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    monkeypatch.setattr(w,'pid_alive',lambda pid:pid==222 and master=='live')
    calls=[]
    def resume(lane_info, **kwargs):
        calls.append(lane_info)
        return {'restarted':False,'reason':'fixture_scope_no_spawn','completion_authority':False}
    monkeypatch.setattr(w,'resume_stopped_lane',resume)
    actor=w.SupervisorWatchdog(manifest_path=path,repo_root=tmp_path,lane_timeout=30)
    result=actor._check_cycle()
    eligible=master!='live' and terminal_reason=='resume_duration_elapsed'
    assert bool(calls) is eligible
    assert result['reports'][0]['heartbeat_check']['stopped_pending_stall']['stopped_pending_stalled'] is eligible
    assert result['completion_authority'] is False and result['work_complete'] is False
    actor._check_cycle()
    assert len(calls)==int(eligible)
