"""Private real filesystem and fake service/clock tests; no live unit or worker calls."""
import contextlib
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace as N

import pytest

BASE=Path(__file__).parents[1];sys.path.insert(0,str(BASE/'tools'))
import publish_official_release_watch as c
manager_source=Path(os.environ.get('MANAGE_RELEASE_WATCH_SOURCE',BASE/'tools/manage_official_release_watch.py'))
manager_spec=importlib.util.spec_from_file_location('manager_under_test',manager_source)
m=importlib.util.module_from_spec(manager_spec);manager_spec.loader.exec_module(m)


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(c.canonical(value))
    return {'path':str(path),'sha256':c.digest(path.read_bytes())}


@pytest.fixture
def rig(tmp_path):
    root=tmp_path/'repo space';root.mkdir();state=root/c.STATE;state.mkdir(parents=True,mode=0o700)
    validator=b'''def validate_observation(root,state,report,*,now=None):
    assert report['observed_at'] <= now
    return {'status':'WAITING_DATE','reasons':[]}
'''
    collector=b"def semantic_fingerprint(report,validation):\n    return report['fingerprint_fixture']\n"
    sources=[];source_bytes={}
    for name in sorted(c.SOURCE_FILES):
        raw=validator if 'validate_'in name else collector if name=='tools/official_release_watch.py'else b'# reviewed fixture module\n'
        path=root/name;path.parent.mkdir(exist_ok=True);path.write_bytes(raw);sources.append(dict(path=name,sha256=c.digest(raw)));source_bytes[name]=raw
    cfg=root/'config.json';cfg.write_bytes(b'{}');pre=root/'preflight.json';pre.write_bytes(b'{}')
    junit=root/'passing.xml';junit.write_text('<testsuite failures="0" errors="0" skipped="0"><testcase name="private-fixture"/></testsuite>')
    preserve=root/'preserve.json';put(preserve,dict(schema='jevops.repair-publication-preservation.v1',files=[]))
    contract=dict(root=root,state=state,source_bytes=source_bytes,config={'settings':{'provider_budget_policy':'policy.json'}},
        config_ref=dict(path='config.json',sha256=c.digest(cfg.read_bytes())),preflight_ref=dict(path='preflight.json',sha256=c.digest(pre.read_bytes())),
        preflight=dict(sources=sources,test_evidence=[dict(path='passing.xml',sha256=c.digest(junit.read_bytes()))]),
        preservation=dict(path='preserve.json',sha256=c.digest(preserve.read_bytes())))
    fp='b'*64;event_id='a'*32
    report=dict(status='WAITING_DATE',observed_at=time.time()-100,fingerprint_fixture=fp,evidence=[])
    event=dict(schema='jevops.official-release-event.v1',event_id=event_id,fingerprint=fp,observation=report,
               validation=dict(status='WAITING_DATE',reasons=[]),**c.AUTH)
    eventpath=state/'outbox/events'/(event_id+'.json');put(eventpath,event)
    pointer=dict(schema='jevops.official-release-outbox-pointer.v1',fingerprint=fp,event=dict(path=str(eventpath.relative_to(state)),sha256=c.digest(eventpath.read_bytes())))
    put(state/'outbox/current.json',pointer)
    repair=root/'persistent/repair';repair.mkdir(parents=True);put(repair/'state.json',{})
    cfg_native=N(state_dir=repair,repair_lock_path=root/'persistent/fixer')
    binding=dict(root=root,native_cfg=cfg_native,supervisor=dict(accelerator_source=str(root/'external')))
    calls=[];clock={'value':0.0};changes={'during_sleep':None}
    def load(ignored):
        value=dict(contract);value['config_ref']=dict(path='config.json',sha256=c.digest(cfg.read_bytes()))
        value['preflight_ref']=dict(path='preflight.json',sha256=c.digest(pre.read_bytes()))
        return value
    def observation(binding,projection):
        current=json.loads((repair/'state.json').read_text())
        return dict(idle=not any(k in current for k in ('active_worker','spawn_intent'))and not(root/'HOLD').exists())
    def request_input(root,ref,**kwargs):
        request=c.json_object(c.referenced(root,ref)[1])
        for row in request['verify']:c.referenced(root,dict(path=row['path'],sha256=row['sha256']))
        return request,None,None
    publisher=N(idle=N(scope=lambda ignored:binding,unchanged_scope=lambda ignored:None),
                observation=observation,request_input=request_input)
    def publish(root,ref,*,timeout,once):
        assert timeout==60 and once is True
        assert observation(binding,{})['idle']and not cfg_native.repair_lock_path.exists()
        calls.append('timed90')
        request=request_input(root,ref)[0]
        receipt=dict(schema='jevops.repair-handoff-publication.v1',published=True,queue_hold_released=True,
                     handoff=request['handoff'],append=request['append'],verify=request['verify'])
        put(root/request['receipt'],receipt)
        return receipt,0
    timed=N(publisher=publisher,publish_with_lease=publish)
    def run(argv,timeout):
        assert argv[:3]==['systemctl','--user','list-units'];return N(stdout='[]',returncode=0)
    def sleep(seconds):
        clock['value']+=seconds
        if changes['during_sleep']:changes['during_sleep']()
    def consume(timeout=120):return c.consume(root,state,timeout=timeout,load=load,tools=lambda ignored:timed,
                                             clock=lambda:clock['value'],sleep=sleep,run=run)
    return N(root=root,state=state,contract=contract,event=event,eventpath=eventpath,pointer=pointer,cfg=cfg,pre=pre,
             repair=repair,cfg_native=cfg_native,binding=binding,calls=calls,timed=timed,run=run,clock=clock,changes=changes,
             load=load,sleep=sleep,consume=consume)


def test_actual_event_publication_marker_and_dedup(rig):
    result,code=rig.consume();assert code==0 and result['delivered']and rig.calls==['timed90']
    result,code=rig.consume();assert code==0 and result['reason']=='ALREADY_DELIVERED'and rig.calls==['timed90']
    marker=rig.state/'outbox/delivered'/('a'*32+'.json')
    assert json.loads(marker.read_text())['event']['sha256']==c.digest(rig.eventpath.read_bytes())
    request=list((rig.state/'outbox/requests').rglob('request.json'))[0]
    value=json.loads(request.read_text())
    assert any(row['path'].endswith('outbox/current.json')for row in value['verify'])
    handoff=json.loads((rig.root/value['handoff']['path']).read_text())
    assert handoff['request_state']=='CONTRACT_MIGRATION_REQUIRED'and handoff['candidate_inventory_is_native_acceptance']is False
    assert handoff['task_states_changed']is False and handoff['proof_authority']is False


@pytest.mark.parametrize('key',['active_worker','spawn_intent'])
@pytest.mark.parametrize('value',[None,{},False])
def test_strict_key_presence_defers_without_timed_hold(rig,key,value):
    put(rig.repair/'state.json',{key:value})
    result,code=rig.consume(timeout=2)
    assert code==75 and result['pending']and not rig.calls
    assert json.loads((rig.repair/'state.json').read_text())=={key:value}


@pytest.mark.parametrize('hold',['HOLD','persistent/fixer','persistent/repair/hold'])
def test_unknown_holds_and_fixer_are_preserved_without_publisher(rig,hold):
    path=rig.root/hold;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('manual owned fixture hold')
    before=path.stat();result,code=rig.consume(timeout=2)
    assert code==75 and not rig.calls and path.read_text()=='manual owned fixture hold'and path.stat().st_ino==before.st_ino


@pytest.mark.parametrize('change',['pointer','config','preflight'])
def test_changed_pointer_config_or_preflight_refuses_before_hold(rig,change):
    put(rig.repair/'state.json',{'active_worker':None})
    def mutate():
        if change=='pointer':put(rig.state/'outbox/current.json',{**rig.pointer,'fingerprint':'c'*64})
        else:(rig.cfg if change=='config'else rig.pre).write_text('{"changed":true}')
    rig.changes['during_sleep']=mutate
    with pytest.raises(c.ReviewRequired):rig.consume()
    assert not rig.calls


def test_future_faked_event_refused_before_hold(rig):
    rig.event['observation']['observed_at']=time.time()+86400
    put(rig.eventpath,rig.event);rig.pointer['event']['sha256']=c.digest(rig.eventpath.read_bytes());put(rig.state/'outbox/current.json',rig.pointer)
    with pytest.raises(c.ReviewRequired,match='future'):rig.consume()
    assert not rig.calls


def test_historical_valid_waiting_event_stays_historical(rig):
    result,code=rig.consume();assert code==0
    handoff=list((rig.state/'outbox/requests').rglob('handoff.json'))[0]
    assert json.loads(handoff.read_text())['observation_status']=='WAITING_DATE'


def test_enospc_after_publication_recovers_exact_receipt_without_republication(rig,monkeypatch):
    original=c.mark_delivered;error=OSError(errno.ENOSPC,'private marker space')
    monkeypatch.setattr(c,'mark_delivered',lambda *args:(_ for _ in()).throw(error))
    with pytest.raises(OSError)as caught:rig.consume()
    assert caught.value is error and rig.calls==['timed90']
    monkeypatch.setattr(c,'mark_delivered',original)
    result,code=rig.consume()
    assert code==0 and result['reason']=='RECOVERED_EXACT_PUBLICATION'and rig.calls==['timed90']


class WholePhaseDeadline(BaseException):pass


@pytest.mark.parametrize('error',[KeyboardInterrupt('control'),SystemExit(13),InterruptedError('control'),WholePhaseDeadline('phase')])
def test_original_publisher_controls_propagate_without_marker(rig,error):
    def fail(*args,**kwargs):raise error
    rig.timed.publish_with_lease=fail
    with pytest.raises(type(error))as caught:rig.consume()
    assert caught.value is error and not list((rig.state/'outbox').glob('delivered/*.json'))


@pytest.mark.parametrize('unit',['jevops-agent-supervisor-continuation-20261029t0126.service','jevops-repair-handoff-20261029-0146.service'])
def test_both_publisher_families_defer_when_pid_active(unit):
    def run(argv,timeout):
        if'list-units'in argv:
            assert 'jevops-repair-handoff-*.service'in argv;return N(stdout=json.dumps([{'unit':unit}]))
        return N(stdout=f'Id={unit}\nLoadState=loaded\nMainPID=123\nActiveState=active\n')
    assert c.quiet_publishers(run)is False


@pytest.mark.parametrize('error',[OSError(errno.ENOSPC,'write'),WholePhaseDeadline('original')])
def test_atomic_marker_first_fsync_failure_never_leaves_partial_live_file(tmp_path,monkeypatch,error):
    path=tmp_path/'marker.json';original=c.os.fsync
    def fail(fd):raise error
    monkeypatch.setattr(c.os,'fsync',fail)
    with pytest.raises(type(error))as caught:c.new_bytes(path,b'complete marker')
    assert caught.value is error and not path.exists()and not list(tmp_path.glob('.*.tmp'))


def test_atomic_marker_postcommit_fsync_failure_is_complete_and_retryable(tmp_path,monkeypatch):
    path=tmp_path/'marker.json';original=c.os.fsync;count=0;records=[]
    def fail_second(fd):
        nonlocal count
        count+=1
        if count==2:raise OSError(errno.ENOSPC,'directory sync')
        return original(fd)
    monkeypatch.setattr(c.os,'fsync',fail_second)
    with pytest.raises(OSError):c.new_bytes(path,b'complete marker',on_commit=records.append)
    assert path.read_bytes()==b'complete marker'and len(records)==1 and path.stat().st_nlink==1
    c.same_or_new(path,b'complete marker')


@pytest.fixture
def units(tmp_path):
    root=tmp_path/'repo with spaces';root.mkdir();directory=tmp_path/'unit files'
    contract=dict(root=root,state=root/c.STATE,config={'settings':{'provider_budget_policy':'policy.json'}},config_ref={'x':'same'},preflight_ref={'x':'same'})
    def arg(value,exec_start=False):return json.dumps(str(value).replace('%','%%').replace('$','$$'if exec_start else'$'))
    manager=N(systemd_arg=arg,systemd_path=lambda value:str(value).replace('%','%%'))
    tools=N(publisher=N(idle=N(scope=lambda ignored:dict(supervisor=dict(python_executable='/usr/bin/python3',accelerator_source='/private/source'))),manager=manager,hold_commit=contextlib.nullcontext))
    commands=[]
    def run(argv,timeout):
        commands.append(argv)
        if'show'in argv:return N(stdout=f'Id={argv[3]}\nLoadState=not-found\nActiveState=inactive\nUnitFileState=\nMainPID=0\nJob=0 /\n',returncode=0)
        return N(stdout='',returncode=0)
    return N(root=root,directory=directory,load=lambda ignored:contract,tools=lambda ignored:tools,run=run,commands=commands)


def test_render_contains_exact_bounds_freeze_and_calendar_without_actions(units):
    _,rendered=m.render(units.root,load=units.load,tools=units.tools)
    assert not units.commands and not units.directory.exists()
    assert 'TimeoutStartSec=70'in rendered[m.WATCH]and'--once'in rendered[m.WATCH]
    assert 'TimeoutStartSec=1900'in rendered[m.PUBLISH]and'1800'in rendered[m.PUBLISH]
    for name in(m.WATCH,m.PUBLISH):
        assert 'KillMode=control-group'in rendered[name]and'MemoryMax=256M'in rendered[name]and'TasksMax=16'in rendered[name]
        assert 'JEVOPS_REFACTOR_LLM_BUDGET_POLICY='in rendered[name]and'UMask=0077'in rendered[name]
    assert '*:0/15:00 UTC'in rendered[m.TIMERS[0]]and'*:0/2:00 UTC'in rendered[m.TIMERS[1]]


def test_install_only_new_units_and_timer_activation(units):
    value=m.install(units.root,load=units.load,tools=units.tools,run=units.run,units_dir=units.directory)
    assert value['installed']and len(list(units.directory.glob('*')))==4
    assert all(not any('supervisor-repair.service'in word for word in command)for command in units.commands)
    assert [command[-1]for command in units.commands if'enable'in command]==list(m.TIMERS)


@pytest.mark.parametrize('error',[OSError(errno.ENOSPC,'timer enable'),WholePhaseDeadline('original')])
def test_install_error_rolls_back_own_files_and_activation_preserves_original(units,error):
    def run(argv,timeout):
        if'enable'in argv:raise error
        return units.run(argv,timeout)
    with pytest.raises(type(error))as caught:m.install(units.root,load=units.load,tools=units.tools,run=run,units_dir=units.directory)
    assert caught.value is error and caught.value.installation_result['rollback_complete']
    assert not list(units.directory.glob('*.service'))and not list(units.directory.glob('*.timer'))


def test_unknown_existing_unit_refused_before_any_unit_action(units):
    units.directory.mkdir();path=units.directory/m.WATCH;path.write_text('unmanaged other unit')
    with pytest.raises(c.ReviewRequired):m.install(units.root,load=units.load,tools=units.tools,run=units.run,units_dir=units.directory)
    assert path.read_text()=='unmanaged other unit'and not units.commands


def test_unit_commit_is_recorded_before_directory_enospc_and_rolled_back(units,monkeypatch):
    original=c.os.fsync;count=0
    def fail_second(fd):
        nonlocal count
        count+=1
        if count==2:raise OSError(errno.ENOSPC,'directory sync after commit')
        return original(fd)
    monkeypatch.setattr(c.os,'fsync',fail_second)
    with pytest.raises(OSError)as caught:m.install(units.root,load=units.load,tools=units.tools,run=units.run,units_dir=units.directory)
    assert caught.value.installation_result['rollback_complete']and not list(units.directory.glob('*.service'))


def test_persistent_timer_catchup_keeps_newly_running_bounded_oneshot_unit(units):
    activated=False;error=OSError(errno.ENOSPC,'second timer enable failed')
    def run(argv,timeout):
        nonlocal activated
        if 'enable' in argv:
            if argv[-1]==m.TIMERS[0]:activated=True
            else:raise error
        if 'show' in argv and argv[3]==m.WATCH and activated:
            return N(stdout=f'Id={m.WATCH}\nLoadState=loaded\nActiveState=activating\nMainPID=12345\nJob=17 /private/job\n',returncode=0)
        return units.run(argv,timeout)
    with pytest.raises(OSError)as caught:m.install(units.root,load=units.load,tools=units.tools,run=run,units_dir=units.directory)
    assert caught.value is error
    assert (units.directory/m.WATCH).exists()
    assert caught.value.installation_result['rollback_complete']is False
    assert m.WATCH in caught.value.installation_result['unit_removal_deferred']
    assert not any(command[2]=='stop'and command[-1]in(m.WATCH,m.PUBLISH)for command in units.commands)


def test_preexisting_active_oneshot_is_never_stopped_or_removed(units):
    _,rendered=m.render(units.root,load=units.load,tools=units.tools)
    units.directory.mkdir();(units.directory/m.WATCH).write_text(rendered[m.WATCH])
    def run(argv,timeout):
        if'enable'in argv:raise OSError(errno.ENOSPC,'timer enable')
        if'show'in argv and argv[3]==m.WATCH:
            return N(stdout=f'Id={m.WATCH}\nLoadState=loaded\nActiveState=activating\nMainPID=56789\nJob=0 /\n',returncode=0)
        return units.run(argv,timeout)
    with pytest.raises(OSError):m.install(units.root,load=units.load,tools=units.tools,run=run,units_dir=units.directory)
    assert (units.directory/m.WATCH).read_text()==rendered[m.WATCH]
    assert not any(command[2]=='stop'and command[-1]in(m.WATCH,m.PUBLISH)for command in units.commands)


def test_exact_four_source_preflight_settings_and_xml_closure(rig):
    root=rig.root
    settings=dict(state_dir=c.STATE,provider_budget_policy='config/lean_refactor_arena_20261026_provider_freeze.json',poll_seconds=900,publish_retry_seconds=120)
    put(root/settings['provider_budget_policy'],dict(new_calls_allowed=False))
    rows=[]
    for index in range(266):
        path=root/'preserved'/(str(index)+'.json');put(path,dict(index=index))
        rows.append(dict(path=str(path.relative_to(root)),sha256=c.digest(path.read_bytes())))
    preservation=root/'preservation-v1.json';put(preservation,dict(schema='jevops.repair-publication-preservation.v1',files=rows))
    ref=dict(path=str(preservation.relative_to(root)),sha256=c.digest(preservation.read_bytes()))
    preflight=dict(schema='jevops.official-release-watch-preflight.v1',settings_sha256=c.digest(c.canonical(settings)),
                   sources=rig.contract['preflight']['sources'],test_evidence=rig.contract['preflight']['test_evidence'],preservation=ref)
    put(rig.pre,preflight)
    put(root/c.CONFIG,dict(schema='jevops.official-release-watch-config.v1',settings=settings,
                          preflight=dict(path='preflight.json',sha256=c.digest(rig.pre.read_bytes()))))
    value=c.load_contract(root,approved_preservation=ref)
    assert value['state']==rig.state and len(value['source_bytes'])==4
    (root/'tools/official_release_watch.py').write_text('# source changed without review')
    with pytest.raises(c.ReviewRequired,match='changed'):c.load_contract(root,approved_preservation=ref)
    assert not rig.calls


def test_incomplete_existing_receipt_never_delivers_or_republishes(rig):
    selected=c.read_event(rig.contract);_,request=c.build_request(rig.contract,selected)
    put(rig.root/request['receipt'],dict(schema='jevops.repair-handoff-publication.v1',published=True,queue_hold_released=False))
    with pytest.raises(c.ReviewRequired,match='incomplete'):rig.consume()
    assert not rig.calls and not list((rig.state/'outbox').glob('delivered/*.json'))


def test_pointer_race_is_rechecked_in_publication_verify_before_lease(rig):
    original=rig.timed.publish_with_lease
    def raced(*args,**kwargs):
        put(rig.state/'outbox/current.json',{**rig.pointer,'fingerprint':'c'*64})
        return original(*args,**kwargs)
    rig.timed.publish_with_lease=raced
    with pytest.raises(c.ReviewRequired,match='changed'):rig.consume()
    assert not list((rig.state/'outbox').glob('delivered/*.json'))


def test_original_write_control_survives_close_failure(tmp_path,monkeypatch):
    error=WholePhaseDeadline('original write control');close=c.os.close
    monkeypatch.setattr(c.os,'fsync',lambda fd:(_ for _ in()).throw(error))
    def failed_close(fd):
        close(fd);raise OSError(errno.EIO,'secondary close failure')
    monkeypatch.setattr(c.os,'close',failed_close)
    with pytest.raises(WholePhaseDeadline)as caught:c.new_bytes(tmp_path/'event.json',b'complete')
    assert caught.value is error and not(tmp_path/'event.json').exists()


def test_actual_producer_and_validator_event_replayed_without_http_or_upstream_execution(rig):
    producer_path=BASE/'tools/official_release_watch.py'
    if not producer_path.exists():producer_path=Path('/storage/hf_cache/jevops-release-watcher-20261029/tools/official_release_watch.py')
    validator_path=BASE/'tools/validate_official_release_candidate_v1.py'
    if not validator_path.exists():validator_path=Path('/storage/hf_cache/jevops-release-validator-20261029/tools/validate_official_release_candidate_v1.py')
    assert c.digest(producer_path.read_bytes())=='3b439f13b88ef5c5c08e34eb618ba30792194c24f7b4ab0837a760afd493384f'
    assert c.digest(validator_path.read_bytes())=='3617b5e342e68b61671f284893171101e1e4ef34f972ccf0513aea836effb02a'
    producer_spec=importlib.util.spec_from_file_location('joint_producer_fixture',producer_path)
    producer=importlib.util.module_from_spec(producer_spec);sys.modules[producer_spec.name]=producer;producer_spec.loader.exec_module(producer)
    validator_spec=importlib.util.spec_from_file_location('joint_validator_fixture',validator_path)
    validator=importlib.util.module_from_spec(validator_spec);sys.modules[validator_spec.name]=validator;validator_spec.loader.exec_module(validator)
    research=Path('/storage/hf_cache/jevops-official-release-research-20261029')
    app=(research/'app.py.raw').read_bytes();loader=(research/'benchmark.py.raw').read_bytes();revision='d'*40
    blob=lambda raw:hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    calls=[]
    def http(url,**bounds):
        calls.append(url)
        if url==producer.API:raw=json.dumps(dict(id=producer.REPO,sha=revision,private=False,runtime=dict(sha=revision,stage='RUNNING'))).encode()
        elif'/tree/'in url:raw=json.dumps([dict(type='file',path=name,size=len(raw),oid=blob(raw))for name,raw in [('app.py',app),('benchmark.py',loader),('benchmark_data_warmup.jsonl',b'')]]).encode()
        elif url.endswith('/app.py'):raw=app
        elif url.endswith('/benchmark.py'):raw=loader
        else:raise AssertionError('No cohort/network allowed before release date: '+url)
        return producer.HTTPResult(200,{},raw,url)
    for directory in rig.state.rglob('*'):
        if directory.is_dir():directory.chmod(0o700)
        elif directory.is_file():directory.chmod(0o600)
    status=producer.poll(rig.root,rig.state,now=min(time.time()-60,producer.NOT_BEFORE-60),getter=http,validator=validator.validate_observation)
    assert status['observation']['status']=='WAITING_DATE'and status['semantic_changed']
    paths={'tools/official_release_watch.py':producer_path,'tools/validate_official_release_candidate_v1.py':validator_path,
           'tools/publish_official_release_watch.py':BASE/'tools/publish_official_release_watch.py',
           'tools/manage_official_release_watch.py':BASE/'tools/manage_official_release_watch.py'}
    rig.contract['source_bytes']={name:path.read_bytes()for name,path in paths.items()}
    rig.contract['preflight']['sources']=[]
    for name,raw in rig.contract['source_bytes'].items():
        (rig.root/name).write_bytes(raw);rig.contract['preflight']['sources'].append(dict(path=name,sha256=c.digest(raw)))
    selected=c.read_event(rig.contract)
    assert selected['event']['validation']['status']=='WAITING_DATE'
    result,code=rig.consume();assert code==0 and result['delivered']and rig.calls==['timed90']
    assert not any('benchmark_data_warmup.jsonl'in url for url in calls)


@pytest.mark.parametrize('job',['','0','0 /'])
def test_actual_systemd_empty_job_represents_no_pending_oneshot(job):
    def run(argv,timeout):
        return N(stdout=f'Id={m.WATCH}\nLoadState=not-found\nActiveState=inactive\nMainPID=0\nJob={job}\n',returncode=0)
    assert m.snapshot_service(m.WATCH,run)['busy']is False


def test_existing_delivery_marker_schema_and_authority_are_validated(rig):
    rig.consume()
    path=rig.state/'outbox/delivered'/('a'*32+'.json');value=json.loads(path.read_text());value['proof_authority']=True;put(path,value)
    with pytest.raises(c.ReviewRequired,match='schema'):rig.consume()
    assert rig.calls==['timed90']


def test_install_cli_reports_deferred_bounded_service_removal(units,monkeypatch,capsys):
    error=OSError(errno.ENOSPC,'partial timer activation')
    error.installation_result=dict(installed=False,rollback_complete=False,unit_removal_deferred=[m.WATCH])
    def failed(root):raise error
    monkeypatch.setattr(m,'install',failed);monkeypatch.setattr(c,'ROOT',units.root)
    assert m.main(['--repo-root',str(units.root),'--install'])==1
    report=json.loads(capsys.readouterr().err)
    assert report['installation']['rollback_complete']is False and report['installation']['unit_removal_deferred']==[m.WATCH]
    assert report['proof_authority']is False and report['task_states_changed']is False
