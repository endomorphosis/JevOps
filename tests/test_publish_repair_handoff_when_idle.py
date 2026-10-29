"""Real temporary files/native markers; no workers, signals, services or provider calls."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys

import pytest

STAGE = Path(__file__).resolve().parents[1]
CANONICAL = Path('/home/barberb/lift_coding/JevOps')
sys.path.insert(0, str(STAGE / 'tools'))
spec = importlib.util.spec_from_file_location('publisher_subject', STAGE / 'tools/publish_repair_handoff_when_idle.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if type(value) is str else json.dumps(value))


def ref(root, path):
    return {'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path / 'repo'; root.mkdir()
    cfg = json.loads((CANONICAL / m.idle.CONFIG).read_text())
    supervisor = json.loads((CANONICAL / cfg['supervisor_profile']).read_text())
    write(root / m.idle.CONFIG, cfg)
    write(root / cfg['supervisor_profile'], supervisor)
    write(root / cfg['runtime_manifest'], {'lanes': [{'state_dir': 'data/lane'}]})
    binding = m.idle.scope(root)
    state = binding['native_cfg'].state_dir / 'state.json'
    write(state, {'schema': binding['native'].SCHEMA,
                  'attempts': {'unchanged-contract': {'count': 3, 'next_dispatch_at': 123}}})
    prompt = root / cfg['repair_prompt']; write(prompt, 'Latest legitimate frontier remains here.\n')
    base = root / 'data/publication'; base.mkdir()
    handoff = base / 'handoff.json'; write(handoff, {'operational_only': True, 'proof_authority': False})
    source = base / 'candidate.py'; write(source, 'CAPTURE_FIX = True\n')
    junit = base / 'tests.xml'; write(junit, '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase name="a"/><testcase name="b"/></testsuite></testsuites>')
    protected = [root/'science.py', root/'budget.json', root/'board.todo']
    for p, v in zip(protected, ['pinned computation\n', '{"calls":25,"cap":24}', '24 of 38 completed\n']):
        write(p, v)
    baseline = base/'preserve.json'
    write(baseline, {'schema': 'jevops.repair-publication-preservation.v1', 'files': [ref(root,p) for p in protected]})
    append = base/'append.txt'; write(append, 'Operational repair handoff '+str(handoff.relative_to(root))+' SHA256 '+ref(root,handoff)['sha256']+'\n')
    request = base/'request.json'
    write(request, {'schema': m.SCHEMA, 'handoff': ref(root,handoff), 'append': ref(root,append),
                    'verify': [dict(kind='source',**ref(root,source)), dict(kind='test_evidence',**ref(root,junit))],
                    'preserve': ref(root,baseline), 'receipt': str((base/'receipt.json').relative_to(root))})
    hold = binding['native_cfg'].state_dir/'hold'; write(hold, {'token': 'a'*32, 'scope': 'new_dispatch_only'})
    info = hold.stat(); lease = base/'lease.json'
    write(lease, {'schema': m.LEASE_SCHEMA, 'path': str(hold.relative_to(root)), 'device': info.st_dev,
                  'inode': info.st_ino, 'sha256': ref(root,hold)['sha256'], 'token': 'a'*32,
                  'release_archive': str((base/'released.hold').relative_to(root))})
    return dict(root=root, binding=binding, state=state, prompt=prompt, base=base, request=request,
                lease=lease, hold=hold, source=source, junit=junit, append=append, protected=protected)


def run(f, **kwargs):
    return m.publish_when_idle(f['root'], ref(f['root'],f['request']), ref(f['root'],f['lease']), **kwargs)


def unchanged(f):
    assert f['prompt'].read_text() == 'Latest legitimate frontier remains here.\n'
    assert f['protected'][0].read_text() == 'pinned computation\n'
    assert f['protected'][1].read_text() == '{"calls":25,"cap":24}'
    assert f['protected'][2].read_text() == '24 of 38 completed\n'


def assert_released(f):
    assert not f['hold'].exists()
    archive = f['base']/'released.hold'
    lease = json.loads(f['lease'].read_text())
    assert archive.stat().st_ino == lease['inode'] and archive.stat().st_nlink == 1
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == lease['sha256']


def test_additive_publish_uses_real_native_marker_archives_beforeimage_and_preserves_state(campaign, monkeypatch):
    f=campaign; state=f['state'].read_bytes(); before=f['prompt'].read_bytes(); atomic=m.manager.atomic; observed=[]
    def fenced(path, content, mode=0o600):
        if path==f['prompt']:
            marker=json.loads(f['binding']['native_cfg'].repair_lock_path.read_text())
            assert marker['pid']==os.getpid() and marker['token']
            assert f['hold'].exists()
            observed.append(True)
        return atomic(path,content,mode)
    monkeypatch.setattr(m.manager,'atomic',fenced)
    result,code=run(f,once=True)
    assert code==0 and result['published'] and result['queue_hold_released'] and observed==[True]
    assert f['prompt'].read_bytes().startswith(before) and f['append'].read_text().strip() in f['prompt'].read_text()
    assert (f['root']/result['history']).read_bytes()==before
    assert json.loads((f['base']/'receipt.json').read_text())['queue_hold_released'] is True
    assert f['state'].read_bytes()==state and not f['binding']['native_cfg'].repair_lock_path.exists()
    assert_released(f)


@pytest.mark.parametrize('key,value',[('active_worker',{'pid':99999999}),('active_worker',{}),('active_worker',None),('spawn_intent',None),('spawn_intent',{}),('spawn_intent',{'pid':99999999})])
def test_persisted_worker_and_spawn_even_dead_or_empty_defer_until_dispatcher_cleans(campaign,monkeypatch,key,value):
    f=campaign; state=json.loads(f['state'].read_text());state[key]=value;write(f['state'],state);before=f['state'].read_bytes()
    monkeypatch.setattr(f['binding']['native'],'probe_process',lambda *_:pytest.fail('persisted state must not be bypassed by probing PID'))
    result,code=run(f,once=True)
    assert code==75 and result['last_observation']['reason']=='persisted_'+key
    assert f['state'].read_bytes()==before
    unchanged(f);assert_released(f)


def test_foreign_actual_native_presence_survives_and_defers_without_any_signal(campaign):
    f=campaign; native=f['binding']['native'];path=f['binding']['native_cfg'].repair_lock_path
    with native.repair_lock(path):
        before=path.read_bytes(),path.stat().st_ino
        result,code=run(f,once=True)
        assert code==75 and result['last_observation']['reason']=='native_repair_presence_held'
        assert (path.read_bytes(),path.stat().st_ino)==before
    unchanged(f);assert_released(f)


@pytest.mark.parametrize('relative',['HOLD','data/lane/HOLD','data/lane/operator.hold','data/lean_refactor_arena_20261024/operator.hold'])
def test_other_holds_are_never_removed(campaign,relative):
    f=campaign;other=f['root']/relative;write(other,'Another exact owner\n');before=other.read_bytes(),other.stat().st_ino
    result,code=run(f,once=True)
    assert code==75 and result['last_observation']['reason']=='other_hold'
    assert (other.read_bytes(),other.stat().st_ino)==before
    unchanged(f);assert_released(f)


def test_waits_for_persisted_state_to_clear_then_appends_current_latest_frontier(campaign,monkeypatch):
    f=campaign;write(f['state'],{'active_worker':{'pid':99999999}});calls=[]
    def advance(_):
        calls.append(1);write(f['state'],{})
        f['prompt'].write_text('A newer valid frontier was published by exiting worker.\n')
    monkeypatch.setattr(m.time,'sleep',advance)
    result,code=run(f,timeout=5)
    assert code==0 and calls==[1] and f['prompt'].read_text().startswith('A newer valid frontier')
    assert (f['root']/result['history']).read_text()=='A newer valid frontier was published by exiting worker.\n'
    assert_released(f)


def test_original_control_interrupt_is_reraised_after_exact_owned_cleanup(campaign,monkeypatch):
    f=campaign;write(f['state'],{'active_worker':{'pid':99999999}});interruption=KeyboardInterrupt('same object')
    def stop(_):raise interruption
    monkeypatch.setattr(m.time,'sleep',stop)
    with pytest.raises(KeyboardInterrupt) as caught:run(f,timeout=5)
    assert caught.value is interruption
    unchanged(f);assert_released(f)


def test_timeout_releases_queue_hold_without_changing_worker_state(campaign,monkeypatch):
    f=campaign;write(f['state'],{'active_worker':{'pid':99999999}});ticks=iter([0.,0.,2.])
    monkeypatch.setattr(m.time,'monotonic',lambda:next(ticks,2.))
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    result,code=run(f,timeout=1)
    assert code==75 and result['reason']=='publication_deadline'
    unchanged(f);assert_released(f)


@pytest.mark.parametrize('mutation',['source','baseline','request'])
def test_immutable_inputs_changed_during_wait_refuse_and_release(campaign,monkeypatch,mutation):
    f=campaign;write(f['state'],{'active_worker':{'pid':99999999}})
    def change(_):
        write(f['state'],{})
        path={'source':f['source'],'baseline':f['protected'][0],'request':f['request']}[mutation]
        path.write_text(path.read_text()+'\nchanged')
    monkeypatch.setattr(m.time,'sleep',change)
    result,code=run(f,timeout=5)
    assert code==1 and not result['published'] and 'SHA256 differs' in result['error']
    assert f['prompt'].read_text()=='Latest legitimate frontier remains here.\n'
    assert_released(f)


@pytest.mark.parametrize('mutation',['replacement','same_inode_body'])
def test_changed_queue_marker_never_removed(campaign,monkeypatch,mutation):
    f=campaign;write(f['state'],{'active_worker':{'pid':99999999}})
    def change(_):
        if mutation=='replacement':f['hold'].unlink()
        write(f['hold'],{'token':'b'*32,'another_owner':True})
    monkeypatch.setattr(m.time,'sleep',change)
    result,code=run(f,timeout=5)
    assert code==1 and not result['queue_hold_released'] and f['hold'].exists()
    assert json.loads(f['hold'].read_text())['another_owner'] is True
    unchanged(f)


@pytest.mark.parametrize('path',['../outside.py','/etc/passwd','data/link/candidate.py'])
def test_source_path_traversal_absolute_and_parent_symlink_refused(campaign,path):
    f=campaign;value=json.loads(f['request'].read_text());value['verify'][0]['path']=path
    (f['root']/'data/link').symlink_to(f['base'],target_is_directory=True)
    write(f['request'],value)
    result,code=run(f,once=True)
    assert code==1 and not result['published'];unchanged(f);assert_released(f)


def test_source_file_symlink_refused_even_when_content_sha_matches(campaign):
    f=campaign;source=f['source'];raw=source.read_text();source.unlink();other=f['base']/'real.py';write(other,raw);source.symlink_to(other)
    result,code=run(f,once=True)
    assert code==1 and not result['published'];unchanged(f);assert_released(f)


@pytest.mark.parametrize('bad_xml',['<testsuite tests="0"/>','<testsuite><testcase><failure/></testcase></testsuite>',
                                    '<testsuite><testcase><error/></testcase></testsuite>',
                                    '<testsuite><testcase><skipped/></testcase></testsuite>',
                                    '<testsuite errors="1"><testcase/></testsuite>',
                                    '<testsuite failures="1"><testcase/></testsuite>',
                                    '<testsuite skipped="1"><testcase/></testsuite>',
                                    '<testsuite errors="-1"><testcase/></testsuite>',
                                    '<testsuite errors="NaN"><testcase/></testsuite>'])
def test_nonpassing_or_empty_test_evidence_refused(campaign,bad_xml):
    f=campaign;write(f['junit'],bad_xml);v=json.loads(f['request'].read_text());v['verify'][1].update(ref(f['root'],f['junit']));write(f['request'],v)
    result,code=run(f,once=True)
    assert code==1 and not result['published'];unchanged(f);assert_released(f)


def test_prompt_write_failure_preserves_beforeimage_and_releases_exact_queue_hold(campaign,monkeypatch):
    f=campaign;atomic=m.manager.atomic
    def fail(path,*args,**kwargs):
        if path==f['prompt']:raise OSError('injected write refusal')
        return atomic(path,*args,**kwargs)
    monkeypatch.setattr(m.manager,'atomic',fail)
    result,code=run(f,once=True)
    assert code==1 and not result['published'] and 'write refusal' in result['error']
    unchanged(f);assert_released(f)


def test_partial_publish_receipt_failure_reports_actual_append_and_releases(campaign,monkeypatch):
    f=campaign;monkeypatch.setattr(m.manager,'save',lambda *_:(_ for _ in ()).throw(OSError('receipt write failure')))
    result,code=run(f,once=True)
    assert code==1 and result['published'] and 'receipt write failure' in result['error']
    assert f['append'].read_text().strip() in f['prompt'].read_text();assert_released(f)


def test_oversized_source_rejected_before_read(campaign):
    f=campaign
    with f['source'].open('wb') as stream:stream.truncate(8*1024*1024+1)
    v=json.loads(f['request'].read_text());v['verify'][0].update(ref(f['root'],f['source']));write(f['request'],v)
    result,code=run(f,once=True)
    assert code==1 and not result['published'] and 'bounded owned ordinary' in result['error']
    unchanged(f);assert_released(f)


def test_absolute_preservation_pin_under_exact_registered_accelerator_is_read_only(campaign):
    f=campaign;external=Path(f['binding']['supervisor']['accelerator_source']).resolve()/'ipfs_accelerate_py/agent_supervisor/rescue/repair_dispatcher.py'
    before=external.read_bytes();v=json.loads(f['request'].read_text());baseline=f['root']/v['preserve']['path'];frozen=json.loads(baseline.read_text())
    frozen['files'].append({'path':str(external),'sha256':hashlib.sha256(before).hexdigest()});write(baseline,frozen)
    v['preserve']=ref(f['root'],baseline);write(f['request'],v)
    result,code=run(f,once=True)
    assert code==0 and result['published'] and external.read_bytes()==before;assert_released(f)


def test_absolute_preservation_outside_registered_accelerator_is_rejected(campaign):
    f=campaign;v=json.loads(f['request'].read_text());baseline=f['root']/v['preserve']['path'];frozen=json.loads(baseline.read_text())
    frozen['files'].append({'path':'/etc/passwd','sha256':'0'*64});write(baseline,frozen);v['preserve']=ref(f['root'],baseline);write(f['request'],v)
    result,code=run(f,once=True)
    assert code==1 and 'escapes registered accelerator' in result['error'];unchanged(f);assert_released(f)


def test_spawn_appearing_after_lock_acquisition_defers_publication(campaign,monkeypatch):
    from contextlib import contextmanager
    f=campaign;native=f['binding']['native'];actual=native.repair_lock
    @contextmanager
    def late(path):
        with actual(path) as lease:
            write(f['state'],{'spawn_intent':{'pid':99999999}})
            yield lease
    monkeypatch.setattr(native,'repair_lock',late)
    result,code=run(f,once=True)
    assert code==75 and result['last_observation']['reason']=='persisted_spawn_intent'
    unchanged(f);assert_released(f)


def test_link_release_interruption_removes_only_our_archive_link_and_preserves_original_interrupt(campaign,monkeypatch):
    f=campaign;source=f['hold'];original_unlink=Path.unlink;interrupted=[False];interruption=KeyboardInterrupt('release interrupt')
    def stop(path,*args,**kwargs):
        if path==source and not interrupted[0]:
            interrupted[0]=True
            raise interruption
        return original_unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',stop)
    with pytest.raises(KeyboardInterrupt) as caught:run(f,once=True)
    assert caught.value is interruption
    assert_released(f)


def test_unlink_completed_then_interrupt_keeps_archive_and_original_exception(campaign,monkeypatch):
    f=campaign;original=Path.unlink;once=[False];error=KeyboardInterrupt('after actual unlink')
    def remove(path,*args,**kwargs):
        result=original(path,*args,**kwargs)
        if path==f['hold'] and not once[0]:
            once[0]=True
            raise error
        return result
    monkeypatch.setattr(Path,'unlink',remove)
    with pytest.raises(KeyboardInterrupt) as caught:run(f,once=True)
    assert caught.value is error and error.publication_result['published'] is True
    assert error.publication_result['queue_hold_released'] is True
    assert_released(f)


@pytest.mark.parametrize('control',[False,True])
def test_atomic_replace_completed_then_failure_reports_actual_publication(campaign,monkeypatch,control):
    f=campaign;atomic=m.manager.atomic;error=KeyboardInterrupt('post replace') if control else OSError('post replace')
    def replace(path,*args,**kwargs):
        result=atomic(path,*args,**kwargs)
        if path==f['prompt']:raise error
        return result
    monkeypatch.setattr(m.manager,'atomic',replace)
    if control:
        with pytest.raises(KeyboardInterrupt) as caught:run(f,once=True)
        assert caught.value is error
        result=error.publication_result
    else:
        result,code=run(f,once=True)
        assert code==1
    assert result['published'] is True and f['append'].read_text().strip() in f['prompt'].read_text()
    assert result['queue_hold_released'] is True;assert_released(f)


def test_deadline_after_history_write_prevents_prompt_commit(campaign,monkeypatch):
    f=campaign;atomic=m.manager.atomic;expired=[False]
    monkeypatch.setattr(m.time,'monotonic',lambda:2. if expired[0] else 0.)
    def write_history(path,*args,**kwargs):
        result=atomic(path,*args,**kwargs)
        if path!=f['prompt']:expired[0]=True
        return result
    monkeypatch.setattr(m.manager,'atomic',write_history)
    result,code=run(f,timeout=1)
    assert code==75 and not result['published'] and result['reason']=='publication_deadline'
    unchanged(f);assert_released(f)
