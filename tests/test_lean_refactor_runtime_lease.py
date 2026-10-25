"""Historical smoke + real current lease guards, using owned private artifacts.

No real model, service, provider or GPU action occurs. Existing qualification
fixtures exercise the actual artifact and live-readiness guard implementations.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import check_lean_refactor_stage_v2 as checker
from test_lean_refactor_runtime_qualification import artifact,live,properties,m as q
_spec=importlib.util.spec_from_file_location('historical_actual_resource_guard',ROOT/'tools/provision_leanstral_20261024.py')
resource_guard=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(resource_guard)


@pytest.fixture
def qualified_lease(live,monkeypatch):
    module,processes,responses=live
    module.check_resources=resource_guard.check_resources
    actual_artifacts=q.artifacts(module)
    lease=q.live_readiness(module,properties(),ROOT)
    data={**q.AUTH,'schema':'jevops.lean-refactor.runtime-qualification.v1',
          'observed_at':time.time()-3600,'stage023_acceptance_satisfied':True,'generation_executed':True,
          'artifacts':copy.deepcopy(actual_artifacts),'live':copy.deepcopy(lease),
          'live_after_smoke':copy.deepcopy(lease),'native_smoke':{'max_output_tokens':16,
          'actual_response':{'model':'Leanstral','usage':{'prompt_tokens':39,'completion_tokens':8},
              'choices':[{'message':{'content':'rfl -- private fixture, never executed'}}]},
          'Lean_executed':False,'model_output_is_unverified_draft':True}}
    path=module.ROOT/'historical-qualification.json';path.write_text(json.dumps(data,sort_keys=True))
    monkeypatch.setattr(checker.c,'module',lambda root,name:q)
    monkeypatch.setattr(q,'provisioner',lambda root:(module,{}))
    monkeypatch.setattr(q,'unit_properties',properties)
    generation=Mock(side_effect=AssertionError('read-only service lease cannot generate'))
    monkeypatch.setattr(q,'inference_smoke',generation)
    module.request.reset_mock()
    return module,processes,responses,data,path,generation


def test_old_authentic_smoke_with_same_current_actor_survives_five_minutes(qualified_lease):
    module,_,_,data,path,generation=qualified_lease;old=path.read_bytes();snapshot=copy.deepcopy(data)
    result=checker.runtime(ROOT,data)
    assert result=={'native_inference_smoke':True,'qualification_scope':'historical',
                   'current_runtime_readiness_checked':False,'proofs_verified':0,
                   'official_checkpoint_ancestry_attested':False}
    assert data==snapshot and path.read_bytes()==old
    module.request.assert_not_called()
    generation.assert_not_called();module.digest.assert_not_called()


def test_current_new_actor_cannot_inherit_historical_smoke(qualified_lease):
    module,processes,_,data,path,generation=qualified_lease
    processes[102]['start_ticks']='401'
    owner_path=module.ROOT/'server-owner.json';owner=json.loads(owner_path.read_text())
    owner['server_start_ticks']='401';owner_path.write_text(json.dumps(owner))
    old=path.read_bytes()
    with pytest.raises(ValueError,match='runtime actor changed'):
        checker.current_runtime_capability(ROOT,data['live_after_smoke']['owner'])
    assert path.read_bytes()==old;generation.assert_not_called()


def test_actor_change_during_original_smoke_is_never_adopted(qualified_lease):
    module,_,_,data,_,_=qualified_lease
    data['live']['owner']['server_start_ticks']='prior-actor'
    with pytest.raises(ValueError,match='during qualification'):checker.runtime(ROOT,data)
    module.request.assert_not_called()


@pytest.mark.parametrize('failure',['stale_guard','inactive_unit','changed_model'])
def test_historical_success_never_bypasses_real_current_service_guard(qualified_lease,monkeypatch,failure):
    module,_,responses,data,path,generation=qualified_lease
    if failure=='stale_guard':
        p=module.ROOT/'server-resource-status.json';value=json.loads(p.read_text());value['observed_at']-=120;p.write_text(json.dumps(value))
    elif failure=='inactive_unit':
        value=properties();value['ActiveState']='inactive';monkeypatch.setattr(q,'unit_properties',lambda:value)
    else:responses['/props'][1]['model_path']='/foreign/model.gguf'
    old=path.read_bytes()
    with pytest.raises(RuntimeError):checker.current_runtime_capability(ROOT,data['live_after_smoke']['owner'])
    assert path.read_bytes()==old;generation.assert_not_called()


def test_historical_qualification_artifact_mismatch_refuses_before_live_requests(qualified_lease):
    module,_,_,data,_,_=qualified_lease;data['artifacts']['model_sha256']='0'*64
    with pytest.raises(ValueError,match='custody/runtime bytes changed'):checker.runtime(ROOT,data)
    module.request.assert_not_called()


@pytest.mark.parametrize('damage',['generation','acceptance','packet','response','usage','empty_content','token_bool','token_cap'])
def test_missing_or_unbounded_inference_is_not_replaced_by_current_health(qualified_lease,damage):
    module,_,_,data,_,_=qualified_lease
    if damage=='generation':data['generation_executed']=False
    elif damage=='acceptance':data['stage023_acceptance_satisfied']=False
    elif damage=='packet':data.pop('native_smoke')
    elif damage=='response':data['native_smoke'].pop('actual_response')
    elif damage=='usage':data['native_smoke']['actual_response'].pop('usage')
    elif damage=='empty_content':data['native_smoke']['actual_response']['choices'][0]['message']['content']=''
    elif damage=='token_bool':data['native_smoke']['actual_response']['usage']['completion_tokens']=True
    else:data['native_smoke']['max_output_tokens']=64
    with pytest.raises(ValueError,match='inference'):checker.runtime(ROOT,data)
    module.request.assert_not_called()


@pytest.mark.parametrize('observed',[True,-1,float('nan'),float('inf'),'old',None,10**1000])
def test_qualification_timestamp_must_be_finite_numeric_and_nonnegative(qualified_lease,observed):
    module,_,_,data,_,_=qualified_lease;data['observed_at']=observed
    with pytest.raises(ValueError,match='timestamp'):checker.runtime(ROOT,data)
    module.request.assert_not_called()


def test_future_dated_qualification_is_rejected(qualified_lease):
    module,_,_,data,_,_=qualified_lease;data['observed_at']=time.time()+3600
    with pytest.raises(ValueError,match='timestamp'):checker.runtime(ROOT,data)
    module.request.assert_not_called()


# Historical completion and current inference capability are distinct contracts.
def _load_history_subject(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def history(qualified_lease,monkeypatch):
    module,processes,responses,data,packet,generation=qualified_lease
    data['observed_at']=time.time()-86400
    packet.write_text(json.dumps(data,sort_keys=True))
    (module.ROOT/'arc-aware-preload-attempt.json').write_text('retained original phase')
    (module.ROOT/'arc-aware-preload-attempt-gpu-release-20261024.json').write_text('retained spent phase')
    (module.ROOT/'iterative-v1-ledger.json').write_text('{"attempts":[{"status":"RETURNED"},{"status":"RETURNED"}]}')
    inactive=properties();inactive['ActiveState']='inactive';inactive['MainPID']='0'
    monkeypatch.setattr(q,'unit_properties',lambda:inactive)
    return module,q,processes,responses,data,packet,generation


def test_expired_unit_does_not_erase_historical_qualification_or_mutate_custody(history):
    module,q,_,_,data,packet,generate=history
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in module.ROOT.rglob('*') if p.is_file()}
    snapshot=copy.deepcopy(data)
    result=checker.runtime(ROOT,data)
    assert result['qualification_scope']=='historical'
    assert result['current_runtime_readiness_checked'] is False and result['native_inference_smoke']
    assert result['proofs_verified']==0 and data==snapshot
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in module.ROOT.rglob('*') if p.is_file()}
    module.request.assert_not_called();generate.assert_not_called();module.digest.assert_not_called()


def test_expired_history_never_becomes_current_inference_capability(history):
    module,q,_,_,data,_,generate=history
    assert checker.validate_runtime_history(ROOT,data)['native_inference_smoke']
    with pytest.raises(RuntimeError,match='not running'):
        checker.current_runtime_capability(ROOT,data['live_after_smoke']['owner'])
    module.request.assert_not_called();generate.assert_not_called()


def test_actual_iterative_producer_still_refuses_expired_actor_before_requests(history,monkeypatch):
    module,q,_,_,data,_,generate=history
    pilot=_load_history_subject('unchanged_actual_inference_guard',ROOT/'tools/lean_refactor_iterative_pilot.py')
    infer=Mock(side_effect=AssertionError('expired unit cannot generate'))
    monkeypatch.setattr(pilot,'infer',infer)
    with pytest.raises(RuntimeError,match='not running'):pilot.produce(module.ROOT)
    module.request.assert_not_called();infer.assert_not_called();generate.assert_not_called()


@pytest.mark.parametrize('damage',['actor','main_pid','unit_lifetime','unit_swap','unit_tasks','rss','host_memory','gpu_memory','health','context','basename','models'])
def test_captured_owner_unit_and_resource_tamper_are_rejected(history,damage):
    module,q,_,_,data,_,_=history
    captured=data['live_after_smoke']
    if damage=='actor':captured['owner']['server_start_ticks']='401'
    elif damage=='main_pid':captured['unit']['MainPID']='999'
    elif damage=='unit_lifetime':captured['unit']['RuntimeMaxUSec']='infinity'
    elif damage=='unit_swap':captured['unit']['MemorySwapMax']='infinity'
    elif damage=='unit_tasks':captured['unit']['TasksMax']='infinity'
    elif damage=='rss':captured['server_rss_bytes']=49*1024**3
    elif damage=='host_memory':captured['resources']['mem_available_bytes']=15*1024**3
    elif damage=='gpu_memory':captured['resources']['gpus'][0]['used_mib']=20481
    elif damage=='health':captured['health']['status']='loading'
    elif damage=='context':captured['actual_context_tokens']=8192
    elif damage=='basename':captured['reported_model_basename']='foreign.gguf'
    else:captured['models']={'data':[{'id':'foreign'}]}
    with pytest.raises((ValueError,RuntimeError)):checker.runtime(ROOT,data)
    module.request.assert_not_called()


@pytest.mark.parametrize('damage',['artifact','generation','authority','official','response','tokens','prompt','future'])
def test_history_still_requires_real_bounded_inference_artifacts_and_no_authority(history,damage):
    module,q,_,_,data,_,_=history
    if damage=='artifact':data['artifacts']['model_sha256']='0'*64
    elif damage=='generation':data['generation_executed']=False
    elif damage=='authority':data['proof_authority']=True
    elif damage=='official':data['weights_officially_attested']=True
    elif damage=='response':data['native_smoke']['actual_response']['choices']=[]
    elif damage=='tokens':data['native_smoke']['actual_response']['usage']['completion_tokens']=17
    elif damage=='prompt':data['native_smoke']['actual_response']['usage']['prompt_tokens']=1025
    else:data['observed_at']=time.time()+3600
    with pytest.raises((ValueError,RuntimeError)):checker.runtime(ROOT,data)
    module.request.assert_not_called()
