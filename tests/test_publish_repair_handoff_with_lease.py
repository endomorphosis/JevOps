"""Private real-file publication fixtures; no service, worker, or provider actions."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
from types import SimpleNamespace
import time

import pytest

BASE=Path(__file__).resolve().parent
SOURCE=BASE.parent/'tools/publish_repair_handoff_with_lease.py'
if not SOURCE.is_file(): SOURCE=BASE/'candidate/publish_repair_handoff_with_lease.py'
sys.path[:0]=[str(SOURCE.parent),'/home/barberb/lift_coding/JevOps/tools']
spec=importlib.util.spec_from_file_location('timed_publisher_subject',SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec=importlib.util.spec_from_file_location('_publication_fixture_source',Path('/home/barberb/lift_coding/JevOps/tests/test_publish_repair_handoff_when_idle.py'))
fixture_source=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_source)


def ref(root,path):return dict(path=str(path.relative_to(root)),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def campaign(tmp_path,monkeypatch):
 f=fixture_source.campaign.__wrapped__(tmp_path)
 f['hold'].unlink();f['lease'].unlink() # These are only the predecessor test fixture's manual artifacts.
 from ipfs_accelerate_py.agent_supervisor.rescue import queue_hold_lease as q
 f['q']=q;f['real_capability']=q.require_live_queue_hold_capability
 monkeypatch.setattr(q,'require_live_queue_hold_capability',lambda *_:dict(version=1,identity_verified=True))
 return f


def run(f,**kwargs):return m.publish_with_lease(f['root'],ref(f['root'],f['request']),timeout=5,**kwargs)


def released(f):
 assert not f['hold'].exists()
 descriptor=json.loads((f['hold'].parent/'hold.lease.json').read_text())
 archive=f['hold'].parent/'expired-queue-holds'/(descriptor['token']+'.hold')
 assert archive.stat().st_ino==descriptor['inode'] and archive.stat().st_nlink==1
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==descriptor['body_sha256']
 return descriptor


def test_success_validates_then_uses_native_timed_lease_and_unchanged_publisher(campaign):
 f=campaign;state=f['state'].read_bytes();value,code=run(f,once=True)
 assert code==0 and value['published'] and value['queue_hold_released']
 lease=released(f);assert lease['expires_at']-lease['created_at']==35
 assert f['state'].read_bytes()==state and f['append'].read_text().strip() in f['prompt'].read_text()
 proof=f['root']/value['lease']['path'];data=json.loads(proof.read_text())
 assert set(data)=={'schema','path','device','inode','sha256','token','release_archive'}
 assert data['token']==lease['token'] and proof.parent==f['request'].parent


@pytest.mark.parametrize('invalid',['request_hash','source','junit','preserve','timeout'])
def test_invalid_request_is_rejected_before_any_lease_creation(campaign,monkeypatch,invalid):
 f=campaign
 if invalid=='request_hash':request=dict(path=str(f['request'].relative_to(f['root'])),sha256='f'*64)
 else:
  request=ref(f['root'],f['request'])
  if invalid=='source':f['source'].write_text('changed source\n')
  elif invalid=='junit':f['junit'].write_text('<testsuite/>')
  elif invalid=='preserve':f['protected'][1].write_text('{"calls":0}')
 monkeypatch.setattr(f['binding']['native'],'register_queue_hold',lambda *_a,**_k:pytest.fail('registration before complete validation'))
 value,code=m.publish_with_lease(f['root'],request,timeout=1771 if invalid=='timeout' else 5,once=True)
 assert code==1 and not value['published'] and not f['hold'].exists()
 assert not (f['hold'].parent/'hold.lease.json').exists()


def test_old_live_capability_refuses_before_marker_or_proof(campaign,monkeypatch):
 f=campaign;monkeypatch.setattr(f['q'],'require_live_queue_hold_capability',f['real_capability'])
 (f['hold'].parent/'status.json').write_text(json.dumps(dict(schema=f['binding']['native'].SCHEMA,queue_hold_lease_version=0)))
 value,code=run(f,once=True)
 assert code==1 and value['registration_incomplete'] and not f['hold'].exists()
 assert not (f['hold'].parent/'hold.lease.json').exists() and not list(f['base'].glob('.repair-queue-proof-*'))


def test_active_worker_defers_and_original_state_is_preserved(campaign):
 f=campaign;state=json.loads(f['state'].read_text());state['active_worker']={'pid':99999999};f['state'].write_text(json.dumps(state));before=f['state'].read_bytes()
 value,code=run(f,once=True)
 assert code==75 and not value['published'] and value['last_observation']['reason']=='persisted_active_worker'
 assert f['state'].read_bytes()==before
 released(f);fixture_source.unchanged(f)


@pytest.mark.parametrize('stage',['projection','proofwrite'])
def test_prepublication_failure_still_releases_exact_returned_custody(campaign,monkeypatch,stage):
 f=campaign
 def fail(*_a,**_k):raise OSError('fixture pre-publication failure')
 if stage=='projection':monkeypatch.setattr(f['binding']['native'],'publisher_queue_hold_proof',fail)
 else:monkeypatch.setattr(m,'write_proof',fail)
 value,code=run(f,once=True)
 assert code==1 and not value['published'] and value['queue_hold_released']
 released(f);fixture_source.unchanged(f)


class WholePhaseDeadline(BaseException):pass


@pytest.mark.parametrize('kind',[WholePhaseDeadline,KeyboardInterrupt,SystemExit,InterruptedError])
def test_original_control_proofwrite_interrupt_releases_and_is_preserved(campaign,monkeypatch,kind):
 f=campaign;original=kind('same control object')
 def fail(*args):raise original
 monkeypatch.setattr(m,'write_proof',fail)
 with pytest.raises(kind) as caught:run(f,once=True)
 assert caught.value is original and original.publication_result['queue_hold_released']
 released(f);fixture_source.unchanged(f)


def test_pending_original_control_survives_cleanup_interrupt_and_native_lease_can_expire(campaign,monkeypatch):
 f=campaign;original=WholePhaseDeadline('original');cleanup=KeyboardInterrupt('cleanup interruption')
 monkeypatch.setattr(m,'write_proof',lambda *_:(_ for _ in ()).throw(original))
 monkeypatch.setattr(m.publisher,'release_queue_hold',lambda *_:(_ for _ in ()).throw(cleanup))
 with pytest.raises(WholePhaseDeadline) as caught:run(f,once=True)
 assert caught.value is original and original.publication_result['automatic_expiry_fallback'] is True
 assert f['hold'].exists()
 lease=json.loads((f['hold'].parent/'hold.lease.json').read_text())
 value=f['q'].expire_queue_hold(f['binding']['native_cfg'],json.loads(f['state'].read_text()),lease['expires_at']+1,apply=True)
 assert value['retirement']=='archived' and not f['hold'].exists()
 fixture_source.unchanged(f)


def test_registration_partial_exception_never_adopts_metadata_but_native_expiry_recovers(campaign,monkeypatch):
 f=campaign;native=f['binding']['native'];real=native.register_queue_hold;original=KeyboardInterrupt('registration did not return')
 def partial(*args,**kwargs):real(*args,**kwargs);raise original
 monkeypatch.setattr(native,'register_queue_hold',partial)
 with pytest.raises(KeyboardInterrupt) as caught:run(f,once=True)
 value=original.publication_result
 assert caught.value is original and value['registration_incomplete'] and value['queue_hold_cleanup_deferred']
 assert value['queue_hold_released'] is None and f['hold'].exists()
 lease=json.loads((f['hold'].parent/'hold.lease.json').read_text())
 f['q'].expire_queue_hold(f['binding']['native_cfg'],json.loads(f['state'].read_text()),lease['expires_at']+1,apply=True)
 assert not f['hold'].exists();fixture_source.unchanged(f)


def test_unknown_replaced_manual_hold_is_preserved_and_no_expiry_is_claimed(campaign,monkeypatch):
 f=campaign
 def replace(*args):
  f['hold'].unlink();f['hold'].write_text('{"token":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","manual":true}')
  raise OSError('fixture changed owner')
 monkeypatch.setattr(m,'write_proof',replace)
 value,code=run(f,once=True)
 assert code==1 and value['queue_hold_released'] is False and value['automatic_expiry_fallback'] is False and value['attention_required'] is True
 assert json.loads(f['hold'].read_text())['manual'] is True
 fixture_source.unchanged(f)


def test_no_remaining_budget_defers_without_reset_and_releases_own_queue(campaign,monkeypatch):
 f=campaign;clock=SimpleNamespace(value=100.0);fake_time=SimpleNamespace(monotonic=lambda:clock.value,time=time.time)
 monkeypatch.setattr(m,'time',fake_time);monkeypatch.setattr(m.publisher,'time',fake_time)
 old=m.write_proof
 def slow(path,value):result=old(path,value);clock.value=105.;return result
 monkeypatch.setattr(m,'write_proof',slow)
 value,code=run(f,once=True)
 assert code==75 and not value['published'] and value['queue_hold_released'];released(f)


def test_delegate_partial_publication_retains_actual_published_flag(campaign,monkeypatch):
 f=campaign;old=m.publisher.manager.save
 def fail_receipt(path,value):
  if path.name=='receipt.json':raise OSError('fixture receipt failed after append')
  return old(path,value)
 monkeypatch.setattr(m.publisher.manager,'save',fail_receipt)
 value,code=run(f,once=True)
 assert code==1 and value['published'] and value['queue_hold_released']
 assert f['append'].read_text().strip() in f['prompt'].read_text();released(f)


def test_existing_manual_queue_hold_is_preserved_without_adoption(campaign):
 f=campaign;f['hold'].write_text('manual prior owner\n');before=f['hold'].read_bytes(),f['hold'].stat().st_ino
 value,code=run(f,once=True)
 assert code==1 and value['registration_incomplete'] and value['queue_hold_released'] is None
 assert (f['hold'].read_bytes(),f['hold'].stat().st_ino)==before
 assert not (f['hold'].parent/'hold.lease.json').exists()
 fixture_source.unchanged(f)


def test_delegate_gets_only_remaining_whole_invocation_budget(campaign,monkeypatch):
 f=campaign;clock=SimpleNamespace(value=100.0);fake_time=SimpleNamespace(monotonic=lambda:clock.value,time=time.time)
 monkeypatch.setattr(m,'time',fake_time);monkeypatch.setattr(m.publisher,'time',fake_time)
 old=m.write_proof;calls=[]
 def spent(path,value):result=old(path,value);clock.value=101.25;return result
 def delegate(*args,**kwargs):calls.append(kwargs);return {'published':False},75
 monkeypatch.setattr(m,'write_proof',spent);monkeypatch.setattr(m.publisher,'publish_when_idle',delegate)
 value,code=run(f,once=True)
 assert code==75 and calls==[{'timeout':3,'once':True}]
 released(f);fixture_source.unchanged(f)


def test_cli_entrypoint_publishes_private_fixture_and_prints_structured_result(campaign,capsys):
 f=campaign;request=ref(f['root'],f['request'])
 code=m.main(['--repo-root',str(f['root']),'--request',request['path'],'--request-sha256',request['sha256'],'--timeout','5'])
 result=json.loads(capsys.readouterr().out)
 assert code==0 and result['published'] and result['queue_hold_released']
 released(f)


def test_ordinary_primary_error_cannot_suppress_cleanup_control_interrupt(campaign,monkeypatch):
 f=campaign;control=KeyboardInterrupt('cleanup cancellation remains authoritative')
 monkeypatch.setattr(m,'write_proof',lambda *_:(_ for _ in ()).throw(ValueError('ordinary proof error')))
 monkeypatch.setattr(m.publisher,'release_queue_hold',lambda *_:(_ for _ in ()).throw(control))
 with pytest.raises(KeyboardInterrupt) as caught:run(f,once=True)
 assert caught.value is control and control.publication_result['error_type']=='ValueError'
 assert control.publication_result['automatic_expiry_fallback'] is True
 lease=json.loads((f['hold'].parent/'hold.lease.json').read_text())
 f['q'].expire_queue_hold(f['binding']['native_cfg'],json.loads(f['state'].read_text()),lease['expires_at']+1,apply=True)
 assert not f['hold'].exists()
