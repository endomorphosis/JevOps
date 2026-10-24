"""Actual pinned tokenizer replay and adversarial native observation contracts."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_execution_v2 as c
import lean_refactor_metric_audit as m
import check_lean_refactor_stage_v2 as v
from jevops.arena import ArenaContext,VerificationRequest,source_hash
from jevops.lean import VersionPin
from jevops import arena_lean

def test_actual_pinned_tokenizers_retain_real_divergence():
    records=c.module(ROOT,'lean_refactor_project_readiness.py').records()
    rows=m.token_rows(ROOT,records)
    assert len(rows)==15
    assert all(r['local_tokens']==r['published_tokens'] for r in rows)
    differences=[r for r in rows if r['upstream_tokens']!=r['published_tokens']]
    assert [(r['name'],r['published_tokens'],r['upstream_tokens']) for r in differences]==[
        ('Binius.BinaryBasefold.fold_advances_evaluation_poly',1906,2219)]

def test_upstream_pure_api_ignores_module_side_effects(tmp_path):
    path=tmp_path/m.UTILS;path.parent.mkdir(parents=True)
    original=(ROOT/m.UTILS).read_text()
    path.write_text('raise RuntimeError("module imports must never execute")\n'+original)
    tokenizer=m.upstream_tokenizer(tmp_path)
    assert tokenizer('theorem example : True := by trivial')==2

def test_registration_has_cpu_bound_and_no_provider_or_training_options():
    contract=c.definitions()['JLR-018']
    assert contract['timeout']==900
    assert contract['argv']==['tools/lean_refactor_metric_audit.py','--produce']
    assert m.ORDER_BLOCK==('reference-first','candidate-first','candidate-first','reference-first')

def test_no_verified_baseline_cannot_select_a_metric_control():
    with pytest.raises(ValueError,match='no verified'):m.select({'rows':[]},[])

def test_cpu_control_uses_measured_native_cost_and_preserves_pin():
    records=[{'name':'slow','src':'short'},{'name':'fast','src':'longer source'}]
    rows=[{'name':name,'status':'VERIFIED','lean_tag':'v4.26.0','git_commit':'a'*40,
           'receipt':{'observations_json':json.dumps({'wall_ms':wall})}}
          for name,wall in [('slow',63000),('fast',25000)]]
    record,row=m.select({'rows':rows},records)
    assert record['name']=='fast' and row['git_commit']=='a'*40
    rows[1]['receipt']['observations_json']=json.dumps({'wall_ms':True})
    with pytest.raises(ValueError,match='measured native control cost'):m.select({'rows':rows},records)

def observation():
    # Explicit synthetic fixture: these objects test refusal branches only and
    # are never published as scientific evidence or passed to stage acceptance.
    pin=VersionPin('v4.26.0','a'*40)
    record={'name':'Demo','statement':'theorem Demo : True','src':'theorem Demo : True := by trivial'}
    ctx=ArenaContext(record['name'],record['statement'],record['src'],2,None,(pin,),('b'*64,),
        'fixture','fixture',arena_lean.METHOD)
    request=VerificationRequest(ctx,record['src'],pin)
    report={'type_preserved':True,'target_absent_before':True,'heartbeats':1,'reference_heartbeats':1,
        'raw_heartbeats':1000,'reference_raw_heartbeats':1000,'axioms':[],'reference_axioms':[]}
    obs={'measurement':arena_lean.METHOD,'branch_order':'reference-first','lean_version':'4.26.0',
        'driver_sha256':source_hash(arena_lean.DRIVER.read_text()),'dependency_digest':'b'*64,'report':report}
    receipt={'request_id':request.request_id,'candidate_sha256':source_hash(record['src']),
        'target':'Demo','outcome':'VERIFIED','exit_code':0,'type_preserved':True,'heartbeats':1,
        'observations_json':json.dumps(obs)}
    sample={'context':asdict(ctx),'receipt':receipt,'branch_order':'reference-first'}
    return sample,record,pin,obs

@pytest.mark.parametrize('damage',['raw','bool','type','target','axiom','source','order','dependency','driver','exit'])
def test_protected_native_metric_check_rejects_forged_observations(damage):
    sample,record,pin,obs=observation()
    if damage=='raw':obs['report']['raw_heartbeats']=3000
    elif damage=='bool':obs['report']['raw_heartbeats']=True
    elif damage=='type':obs['report']['type_preserved']=False
    elif damage=='target':sample['receipt']['target']='Other'
    elif damage=='axiom':obs['report']['axioms']=['sorryAx']
    elif damage=='source':sample['receipt']['candidate_sha256']='c'*64
    elif damage=='order':obs['branch_order']='candidate-first'
    elif damage=='dependency':obs['dependency_digest']='c'*64
    elif damage=='driver':obs['driver_sha256']='c'*64
    elif damage=='exit':sample['receipt']['exit_code']=7
    sample['receipt']['observations_json']=json.dumps(obs)
    with pytest.raises(ValueError):
        v.metric_sample(sample,record,pin,SimpleNamespace(validate_request=lambda req:None))
