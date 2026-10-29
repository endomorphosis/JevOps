"""Export boundary adversaries and actual pinned native extraction fixtures."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'tools'))
import validate_lean_refactor_search_extract as v
import lean_refactor_search_extract as m

@pytest.fixture(autouse=True)
def private_scoped_open_adapter(monkeypatch):
    # Exercise the staged source, while the canonical package remains intact.
    path=HERE/'jevops/structural_training.py'
    spec=importlib.util.spec_from_file_location('jevops._prepared_structural_training',path)
    prepared=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepared)
    monkeypatch.setattr(m.proof_replay,'_envelope',prepared._envelope)
    return prepared

STATEMENT='theorem sample (p : Prop) (h : p) : p'
SOURCE=STATEMENT+' := by\n  exact (id (id h))\n'

def event(source=SOURCE):
    start=source.encode().index(b'exact ')
    return {'id':'0','start':str(start),'end':str(len(source.encode())-1),
            'status':'captured','before':{'goals':[{}]},'after':{'goals':[]},
            'syntax_kind':[['s','Lean'],['s','Parser'],['s','Tactic'],['s','exact']]}

def envelope():
    return {'ok':True,'evidence_mode':'local_lean','closing_reproduced':True,
            'proof_admitted':False,'whole_source_checked':False,'extracted_candidate':'exact h',
            'search_steps_observed':1,'search_steps_reserved':4,'roundtrip_attempts':1}

def test_emitted_source_is_exact_original_byte_span_replacement():
    exported=m.export_candidate(SOURCE,STATEMENT,event(),envelope())
    assert exported['source']==STATEMENT+' := by\n  exact h\n'
    assert exported['token_growth']<0 and exported['term_bytes']==len(b'exact h')
    assert SOURCE.startswith(STATEMENT) and exported['source'].startswith(STATEMENT)

@pytest.mark.parametrize('field,value',[
    ('ok',False),('evidence_mode','fixture'),('closing_reproduced',False),
    ('proof_admitted',True),('whole_source_checked',True),('extracted_candidate','simp'),
    ('extracted_candidate','exact '+('h '*3000)),('search_steps_observed',5),
    ('search_steps_observed',True),('search_steps_reserved',12),('roundtrip_attempts',0)])
def test_export_rejects_unverified_fixture_or_unbounded_discovery(field,value):
    result=envelope();result[field]=value
    with pytest.raises(ValueError):m.export_candidate(SOURCE,STATEMENT,event(),result)

def test_explicit_term_token_growth_is_bounded_separately_from_discovery():
    result=envelope();result['extracted_candidate']='exact '+' '.join(['id']*100)+' h'
    with pytest.raises(ValueError,match='token growth'):m.export_candidate(SOURCE,STATEMENT,event(),result)

def test_utf8_offsets_and_deterministic_bounded_closing_event_selection():
    source=SOURCE.replace('(p : Prop)','(π : Prop)').replace('(h : p) : p','(h : π) : π')
    e=event(source);events=[deepcopy(e) for _ in range(5)]
    for i,item in enumerate(events):item['id']=str(4-i)
    found=m.closed_events(source,{'trace':{'events':events}})
    assert [x['id'] for x in found]==['0','1','2']
    assert m.export_candidate(source,source.split(' :=')[0],e,envelope())['source'].endswith('exact h\n')
    events[0]['status']='unsupported';events[1]['after']['goals']=[{}]
    assert len(m.closed_events(source,{'trace':{'events':events}}))==3

@pytest.mark.parametrize('status',['RUNNING','NO_EXTRACTED_TERM','BLOCKED_CAPTURE',
                                 'BLOCKED_ORIGINAL','COLD_REPLAY_FAILED'])
def test_partial_negative_and_infrastructure_states_cannot_complete(status):
    with pytest.raises(ValueError,match='confirmed extraction'):
        v.validate(HERE,{'schema':m.SCHEMA,'target':m.TARGET,'status':status})

def test_all_required_pins_are_preserved_before_native_launch(monkeypatch,tmp_path):
    record={'name':m.TARGET,'version_info':[{'v4.26.0':'a'*40},{'v4.27.0':'b'*40}]}
    monkeypatch.setattr(m.c,'module',lambda *args:type('Records',(),{'records':lambda:[record]}))
    with pytest.raises(ValueError,match='complete one-pin'):m.target_inputs(tmp_path)

def test_unchanged_scoped_open_prelude_preserves_header_and_rejects_commands(private_scoped_open_adapter):
    check=private_scoped_open_adapter._envelope
    original='open OldExpressions in\n'+SOURCE
    target=original.replace('exact (id (id h))','exact h')
    assert check(original,target)
    for damaged in (target.replace('OldExpressions','OtherNamespace'),
                    target.replace('open OldExpressions in','attribute [simp] hidden'),
                    target.replace('open OldExpressions in','set_option maxHeartbeats 0'),
                    target.replace('open OldExpressions in','open OldExpressions in\naxiom evil : False'),
                    target.replace('(h : p)','(h : True)'),target+'\naxiom evil : False\n'):
        with pytest.raises(ValueError):check(original,damaged)

def native_setup(tmp_path):
    from jevops import arena_lean as native
    from jevops.lean import VersionPin
    pin=VersionPin('v4.26.0','native-operational-fixture-not-campaign-project')
    lean=native.pinned_lean(Path('/home/barberb/.elan'),pin.lean_tag)
    assert lean.is_file(),'this host must supply the actual pinned Lean; no skip or fake pass'
    record={'name':'Suite.sample','statement':STATEMENT,'src':SOURCE,
            'version_info':[{pin.lean_tag:pin.git_commit}]}
    binding=native.ProjectBinding(pin,lean,tmp_path,'namespace Suite\n',project_backed=False)
    return record,pin,{pin:binding}

def test_actual_native_search_export_and_fresh_whole_theorem_replay(tmp_path):
    from jevops import arena_lean as native,arena_local as local,arena
    record,pin,bindings=native_setup(tmp_path)
    guard=native.NativeLeanVerifier(bindings,max_processes=2,timeout=45)
    runtime=local.ArenaLocalRuntime(guard,record,max_processes=2,
                    node_budget=m.LIMITS['node_budget'],event_budget=m.LIMITS['event_budget'])
    captured=runtime.capture(pin)
    assert captured['ok'] and captured['evidence_mode']=='local_lean',captured
    selected=m.closed_events(SOURCE,captured['capture']);assert selected
    e=selected[0]
    result=runtime.discover_search(pin,SOURCE,captured['capture'],int(e['id']),list(m.PREMISES),
                    max_steps=m.LIMITS['steps_per_event'],max_depth=m.LIMITS['depth'])
    exported=m.export_candidate(SOURCE,STATEMENT,e,result)
    assert runtime.attempts==2 and result['search_steps_observed']<=4
    assert exported['source']!=SOURCE and exported['token_growth']<0
    for order in ('reference-first','candidate-first'):
        verifier=native.NativeLeanVerifier(bindings,max_processes=1,timeout=45,branch_order=order)
        receipt=verifier(arena.VerificationRequest(verifier.context(record),exported['source'],pin))
        assert receipt.outcome.value=='VERIFIED' and receipt.type_preserved
        report=json.loads(receipt.observations_json)['report']
        assert report['type_preserved'] and report['target_absent_before']
        assert set(report['axioms'])<=set(report['reference_axioms'])

def test_invalid_emitted_body_fails_actual_native_acceptance(tmp_path):
    from jevops import arena_lean as native,arena
    record,pin,bindings=native_setup(tmp_path)
    verifier=native.NativeLeanVerifier(bindings,max_processes=1,timeout=45)
    invalid=STATEMENT+' := by\n  exact True.intro\n'
    receipt=verifier(arena.VerificationRequest(verifier.context(record),invalid,pin))
    assert receipt.outcome.value!='VERIFIED'

def test_rejected_native_cold_proof_is_archived_before_refusal(tmp_path):
    record,pin,bindings=native_setup(tmp_path)
    invalid=STATEMENT+' := by\n  exact True.intro\n'
    with pytest.raises(ValueError,match='independent cold whole-source acceptance failed: candidate-first'):
        v.cold_replays(tmp_path,record,bindings,pin,invalid,lambda:None)
    paths=list((tmp_path/m.c.RUNTIME/'acceptance').glob('JLR-021-*/cold-replays.json'))
    assert len(paths)==1
    observed=m.c.read(paths[0]);row=observed['replays'][0]
    assert observed['status']=='REFUSED' and observed['native_processes']==1
    assert row['receipt']['outcome']!='VERIFIED' and row['finished_at']>=row['started_at']
    assert observed['candidate_sha256']==m.arena.source_hash(invalid)
    assert observed['validator_sha256']==m.c.sha(Path(v.__file__))
    assert observed['completion_authority'] is False and observed['proof_authority'] is False
    assert not (tmp_path/m.c.RUNTIME/'JLR-021.receipt.json').exists()

def test_successful_native_replays_keep_both_orders_and_separate_archives(tmp_path):
    record,pin,bindings=native_setup(tmp_path)
    receipts=v.cold_replays(tmp_path,record,bindings,pin,SOURCE,lambda:None)
    assert len(receipts)==2 and all(r['outcome']=='VERIFIED' for r in receipts)
    def held():raise ValueError('operator hold')
    with pytest.raises(ValueError,match='operator hold'):
        v.cold_replays(tmp_path,record,bindings,pin,SOURCE,held)
    paths=list((tmp_path/m.c.RUNTIME/'acceptance').glob('JLR-021-*/cold-replays.json'))
    assert len(paths)==2
    for path in paths:
        observed=m.c.read(path)
        if observed['status']=='REFUSED':
            assert observed['native_processes']==0 and observed['replays']==[]
            continue
        assert observed['status']=='REPLAYED' and observed['native_processes']==2
        assert observed['native_timeout_seconds']==60 and observed['max_native_processes']==2
        assert [r['branch_order'] for r in observed['replays']]==['candidate-first','reference-first']
        assert all(json.loads(r['receipt']['observations_json'])['report']['target_absent_before']
                   for r in observed['replays'])

def test_operator_hold_during_cold_replay_is_retained_as_refusal(tmp_path):
    record,pin,bindings=native_setup(tmp_path)
    def held():raise ValueError('operator hold')
    with pytest.raises(ValueError,match='operator hold'):
        v.cold_replays(tmp_path,record,bindings,pin,SOURCE,held)
    observed=m.c.read(next((tmp_path/m.c.RUNTIME/'acceptance').glob('*/cold-replays.json')))
    assert observed['status']=='REFUSED' and observed['native_processes']==0
    assert observed['replays']==[] and observed['reason']=='operator hold'

def test_actual_full_producer_and_independent_validator_preserve_fixture_state(tmp_path,monkeypatch):
    record,pin,bindings=native_setup(tmp_path)
    monkeypatch.setattr(m,'TARGET',record['name'])
    monkeypatch.setattr(m,'target_inputs',lambda root:(record,[pin],bindings))
    monkeypatch.setattr(v,'producer',lambda:m)
    for name in ('JLR-016.result.json','JLR-017.result.json'):
        m.c.save(tmp_path/m.c.RUNTIME/name,{'fixture_only':True})
    immutable={n:(tmp_path/m.c.RUNTIME/n).read_bytes() for n in ('JLR-016.result.json','JLR-017.result.json')}
    report=m.produce(tmp_path,output_directory=tmp_path/'private-out')
    assert report['status']=='CONFIRMED_EXTRACTION',report
    assert report['native_processes']==5 and len(report['searches'])==1
    checked=v.validate(tmp_path,report)
    assert checked['all_target_pins']==1 and checked['fresh_search_processes']==2
    assert len(checked['independent_cold_replays'])==2
    assert checked['optimization_success'] is False and checked['proof_authority'] is False
    assert all((tmp_path/m.c.RUNTIME/n).read_bytes()==raw for n,raw in immutable.items())
    for damage in ('source','budget','fixture','pin','authority'):
        broken=deepcopy(report)
        if damage=='source':broken['winner']['source']=STATEMENT+' := by sorry\n'
        elif damage=='budget':broken['native_processes']=0
        elif damage=='fixture':broken['searches'][0]['result']['evidence_mode']='fixture'
        elif damage=='pin':broken['pins'][0]['git_commit']='unreviewed'
        else:broken['completion_authority']=True
        with pytest.raises(ValueError):v.validate(tmp_path,broken)

def negative_subprocess(damage=None):
    # Dependency fingerprints bind absolute paths. Load the canonical native
    # modules in a fresh interpreter, then review private candidate code against
    # the unchanged real archived run. This does not mock native context IDs.
    import subprocess,os
    code="""
from pathlib import Path
import importlib.util,json,sys
root=Path('/home/barberb/lift_coding/JevOps')
sys.path[:0]=[str(root/'tools'),str(root)]
import lean_refactor_execution_v2 as c
from jevops import arena_lean,arena_local,proof_replay
path=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('_private_negative_validator',path)
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
# Review the actual immutable negative with the exact producer that ran it.
# Current producer changes must not relabel or invalidate historical evidence.
receipt_path=root/c.RUNTIME/'runs/JLR-021-9c6aa8e09c754ebe8497a37c07450115/receipt.json'
assert c.sha(receipt_path)=='5c67820b955256199814daa24934acb7318294183f5c87a0a8d75e8cb782f7f9'
receipt=c.read(receipt_path);execution=receipt['executions'][0]
assert c.sha(root/execution['stdout'])==execution['stdout_sha256']
data=c.read(root/execution['stdout'])
historical_source=root/c.RUNTIME/'maintenance-0648-private/tools/lean_refactor_search_extract.py'
assert c.sha(historical_source)==receipt['binding']['source_sha256']['tools/lean_refactor_search_extract.py']
assert c.sha(historical_source)==data['producer_sha256']
prior_spec=importlib.util.spec_from_file_location('_actual_historical_search_producer',historical_source)
prior=importlib.util.module_from_spec(prior_spec);prior_spec.loader.exec_module(prior)
v.producer=lambda:prior
damage=sys.argv[2]
if damage=='winner':data['winner']={'source':'invented'}
elif damage=='missing_event':data['searches'].pop()
elif damage=='failure':data['searches'][0]['result']['ok']=False
elif damage=='incomplete':data['searches'][0]['result']['search_report']['attempted_steps']=1
elif damage=='binding':data['searches'][0]['result']['binding']['trace_sha256']='e'*64
elif damage=='fixture':data['searches'][0]['result']['evidence_mode']='fixture'
elif damage=='authority':data['proof_authority']=True
def forbidden(*a,**k):raise AssertionError('negative review launched a scientific process')
arena_local.ArenaLocalRuntime._run=forbidden
names=[c.RUNTIME+'/'+n for n in ('JLR-021.result.json','JLR-021.partial.json','JLR-021.receipt.json','iterative-v1-ledger.json')]
before={n:(root/n).read_bytes() for n in names}
try:
    result=v.validate_negative(root,data)
except ValueError:
    if damage=='None':raise
else:
    assert damage=='None' and result['acceptance_satisfied'] is False
assert all((root/n).read_bytes()==raw for n,raw in before.items())
"""
    execution=subprocess.run([sys.executable,'-B','-c',code,str(HERE/'tools/validate_lean_refactor_search_extract.py'),str(damage)],
          capture_output=True,text=True,timeout=60,env={**os.environ,'PYTHONPATH':'/home/barberb/lift_coding/external/ipfs_accelerate:/home/barberb/lift_coding/JevOps'})
    assert execution.returncode==0,execution.stderr

def test_actual_retained_campaign_negative_is_authenticated_without_native_or_model_calls():
    negative_subprocess()

@pytest.mark.parametrize('damage',['winner','missing_event','failure','incomplete','binding','fixture','authority'])
def test_negative_search_validation_does_not_hide_crash_partial_or_positive_trials(damage):
    negative_subprocess(damage)


def test_held_replay_requires_fresh_explicit_native_maintenance_ack(monkeypatch):
    monkeypatch.setattr(v,'producer',lambda:m)
    monkeypatch.setattr(m.c,'held',lambda root:['pre-existing operator HOLD'])
    def refuse(*args):raise ValueError('fresh childless maintenance acknowledgement required')
    monkeypatch.setattr(m.c,'quiescent_maintenance_fence',refuse)
    with pytest.raises(ValueError,match='fresh childless'):
        v.validate(HERE,{'schema':m.SCHEMA,'target':m.TARGET,'status':'CONFIRMED_EXTRACTION'})


def test_local_closing_context_precedes_shorter_unsupported_simp_goals():
    source=STATEMENT+' := by\n  simp_all\n  assumption\n  exact h\n  rfl\n'
    chunks=['simp_all','assumption','exact h','rfl'];events=[]
    for i,chunk in enumerate(chunks):
        start=source.index(chunk)
        events.append({'id':str(i+1),'start':str(start),'end':str(start+len(chunk)),'status':'captured',
                       'before':{'goals':['frozen local goal']},'after':{'goals':[]}})
    found=m.closed_events(source,{'trace':{'events':events}})
    assert [int(e['id']) for e in found]==[2,3,4]
    assert [int(e['id']) for e in m.closed_events(source,{'trace':{'events':list(reversed(events))}})]==[2,3,4]
    assert m.LIMITS['events']==3 and m.LIMITS['steps_per_event']==4
    assert m.LIMITS['search_branches']==12 and m.LIMITS['native_processes']==7


def test_nonclosing_local_anchor_cannot_displace_actual_closing_span():
    source=STATEMENT+' := by\n  assumption\n  simp_all\n'
    first=source.index('assumption');second=source.index('simp_all')
    events=[{'id':'1','start':str(first),'end':str(first+10),'status':'captured',
             'before':{'goals':['one']},'after':{'goals':['remaining']}},
            {'id':'2','start':str(second),'end':str(second+8),'status':'captured',
             'before':{'goals':['one']},'after':{'goals':[]}}]
    assert [int(e['id']) for e in m.closed_events(source,{'trace':{'events':events}})]==[2]


def test_retained_campaign_trace_changes_only_anchor_strategy_without_trial():
    # Read-only analysis of an authenticated development capture is not a new
    # native/model trial or a proof result. Historical negatives stay intact.
    # Bind the immutable run, so a later native trial can replace live aliases.
    receipt_path=HERE/m.c.RUNTIME/'runs/JLR-021-9c6aa8e09c754ebe8497a37c07450115/receipt.json'
    assert m.c.sha(receipt_path)=='5c67820b955256199814daa24934acb7318294183f5c87a0a8d75e8cb782f7f9'
    receipt=m.c.read(receipt_path);execution=receipt['executions'][0]
    path=HERE/execution['stdout'];before=path.read_bytes()
    assert m.c.sha(path)==execution['stdout_sha256']
    data=json.loads(before);source=data['original_fallback']
    capture=data['capture']['capture'];events=m.closed_events(source,capture)
    assert len(events)==3 and int(events[0]['id'])==29
    assert source.encode()[int(events[0]['start']):int(events[0]['end'])].decode()=='assumption'
    assert [row['event_id'] for row in data['searches']]==[22,25,35]
    assert data['status']=='NO_EXTRACTED_TERM' and data['winner'] is None
    assert path.read_bytes()==before
