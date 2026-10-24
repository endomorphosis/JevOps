"""Historical smoke + real current lease guards, using owned private artifacts.

No real model, service, provider or GPU action occurs. Existing qualification
fixtures exercise the actual artifact and live-readiness guard implementations.
"""
import copy
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


@pytest.fixture
def qualified_lease(live,monkeypatch):
    module,processes,responses=live
    actual_artifacts=q.artifacts(module)
    lease=q.live_readiness(module,properties(),ROOT)
    data={'schema':'jevops.lean-refactor.runtime-qualification.v1',
          'observed_at':time.time()-3600,'stage023_acceptance_satisfied':True,'generation_executed':True,
          'artifacts':copy.deepcopy(actual_artifacts),'live':copy.deepcopy(lease),
          'live_after_smoke':copy.deepcopy(lease),'native_smoke':{'max_output_tokens':16,
          'actual_response':{'model':'Leanstral','usage':{'completion_tokens':8},
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
    assert result=={'native_inference_smoke':True,'proofs_verified':0,
                   'official_checkpoint_ancestry_attested':False}
    assert data==snapshot and path.read_bytes()==old
    assert [call.args[0] for call in module.request.call_args_list]==['/health','/v1/models','/props']
    assert all(not call.kwargs for call in module.request.call_args_list)
    generation.assert_not_called();module.digest.assert_not_called()


def test_current_new_actor_cannot_inherit_historical_smoke(qualified_lease):
    module,processes,_,data,path,generation=qualified_lease
    processes[102]['start_ticks']='401'
    owner_path=module.ROOT/'server-owner.json';owner=json.loads(owner_path.read_text())
    owner['server_start_ticks']='401';owner_path.write_text(json.dumps(owner))
    old=path.read_bytes()
    with pytest.raises(ValueError,match='runtime actor changed'):checker.runtime(ROOT,data)
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
    with pytest.raises(RuntimeError):checker.runtime(ROOT,data)
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
