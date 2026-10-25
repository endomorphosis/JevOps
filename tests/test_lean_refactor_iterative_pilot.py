"""Bounded phase, source intake and refusal tests; fixtures never certify proofs."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_iterative_pilot as m
import validate_lean_refactor_iterative_pilot as v

def record():
    return {'statement':'theorem demo (n : Nat) : n = n',
            'src':'theorem demo (n : Nat) : n = n := by\n  first | rfl | rfl\n'}

def test_native_control_budget_covers_measured_frozen_baseline_inside_same_phase():
    baseline=m.c.read(ROOT/m.c.RUNTIME/'JLR-017.result.json')
    control=next(row for row in baseline['rows'] if row['name']==m.TARGET and row['status']=='VERIFIED')
    measured=json.loads(control['receipt']['observations_json'])['wall_ms']/1000
    assert 45<measured<m.NATIVE_TIMEOUT_SECONDS<=75
    assert m.LIMITS=={'max_calls':2,'max_input_tokens':1024,'max_output_tokens':256,
        'request_timeout_seconds':90,'total_seconds':240,'max_native_processes':4}

def test_candidate_replaces_original_body_and_keeps_exact_statement():
    r=record();source=m.candidate(r,json.dumps({'proof':'by rfl'}))
    assert source==r['statement']+' := by rfl'
    assert m.arena.intake_error(source,r['statement']) is None

@pytest.mark.parametrize('text',['{}','{"proof":"by sorry"}','{"proof":"by rfl","claim":true}',
    '{"proof":"by rfl","proof":"by rfl"}','```lean\nrfl\n```', '{"proof":4}'])
def test_response_cannot_control_validators_or_self_certify(text):
    with pytest.raises((ValueError,TypeError)):m.candidate(record(),text)

def test_phase_ledger_preserves_all_bootstrap_usage_and_failed_reservations(tmp_path):
    previous={'calls':22,'contracts':{'preserved-failure':3}}
    m.c.save(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json',previous)
    ledger=m.budget(tmp_path)
    for _ in range(2):m.reserve(tmp_path,ledger,{'source_sha256':'frozen-source'})
    before=(tmp_path/m.LEDGER).read_bytes()
    with pytest.raises(ValueError,match='exhausted'):m.reserve(tmp_path,ledger,{})
    assert (tmp_path/m.LEDGER).read_bytes()==before
    restored=m.budget(tmp_path)
    assert len(restored['attempts'])==2 and all(e['status']=='RESERVED' for e in restored['attempts'])
    assert restored['bootstrap_usage']==previous
    assert m.c.read(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json')==previous

@pytest.mark.parametrize('damage',['cap','usage','subject'])
def test_existing_phase_cannot_be_silently_expanded_or_repurposed(tmp_path,damage):
    m.c.save(tmp_path/'data/lean_refactor_arena_20261024/router-budget.json',{'calls':22})
    ledger=m.budget(tmp_path)
    if damage=='cap':ledger['limits']={**ledger['limits'],'max_calls':3}
    elif damage=='usage':ledger['bootstrap_usage']={'calls':0}
    else:ledger['subject']='fallback_provider'
    m.c.save(tmp_path/m.LEDGER,ledger)
    with pytest.raises(ValueError,match='never reset'):m.budget(tmp_path)

@pytest.mark.parametrize('size',[0,993,1025])
def test_actual_template_token_admission_prevents_generation(size):
    calls=[]
    def request(path,**kwargs):
        calls.append(path)
        return (200,{'prompt':'actual-template'}) if path=='/apply-template' else (200,{'tokens':[1]*size})
    with pytest.raises(ValueError,match='token budget'):m.token_packet(SimpleNamespace(request=request),[{'role':'user','content':'x'}])
    assert calls==['/apply-template','/tokenize']

def test_actual_template_identity_and_tokens_are_retained():
    def request(path,**kwargs):
        return (200,{'prompt':'exact-template'}) if path=='/apply-template' else (200,{'tokens':[7]*992})
    packet=m.token_packet(SimpleNamespace(request=request),[{'role':'user','content':'x'}])
    assert packet=={'template':'exact-template','token_count':992,'template_sha256':m.arena.source_hash('exact-template')}

def test_validator_rejects_self_report_without_native_population():
    with pytest.raises((ValueError,KeyError)):v.validate(ROOT,{'status':'CONFIRMED','proof_authority':True})

def test_actual_canonical_router_does_not_retry_failed_subject_or_fallback(monkeypatch):
    source=m.c.read(ROOT/m.c.BASE)['accelerator_source'];monkeypatch.syspath_prepend(source)
    from ipfs_accelerate_py import llm_router as router
    calls=[]
    class Subject:
        def chat_completions(self,messages,**kwargs):
            calls.append((messages,kwargs));raise RuntimeError('private synthetic transport failure')
    monkeypatch.setattr(router,'_get_llama_cpp_provider',lambda **kwargs:Subject())
    with pytest.raises(RuntimeError):m.infer(ROOT,[{'role':'user','content':'private unit transport test'}],.1)
    assert len(calls)==1 and calls[0][1]['model_name']=='Leanstral'
    assert calls[0][1]['max_tokens']==256 and calls[0][1]['timeout']==.1
