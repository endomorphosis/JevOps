"""Actual source edit and protected acceptance checks; no synthetic proof claims."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_coupled_pilot as m
import validate_lean_refactor_coupled_pilot as v
from check_lean_refactor_stage_v2 import GateWait

def record():
    return next(r for r in m.c.module(ROOT,'lean_refactor_project_readiness.py').records() if r['name']==m.TARGET)

def test_real_corpus_has_matched_binder_and_induction_goal_repair():
    r=record();drafts=m.proposals(r)
    assert [d['arm'] for d in drafts]==['isolated','coupled']
    assert all(d['binder']=='Hlen2' and d['ih_binder']=='ih' for d in drafts)
    assert drafts[0]['edits'][0]==drafts[1]['edits'][0]
    assert 'have Hlen2' not in drafts[0]['source'] and '(ih Hinit ?_ ?_)' in drafts[0]['source']
    assert '(ih Hinit).2.2' in drafts[1]['source']
    for draft in drafts:
        assert m.apply_edits(r['src'],draft['edits'])==v.edit_check(r,draft)
        assert m.arena.intake_error(draft['source'],r['statement']) is None

@pytest.mark.parametrize('damage',['source','range','replacement','overlap','theorem'])
def test_independent_edit_acceptance_rejects_source_offset_and_envelope_tampering(damage):
    r=record();draft=copy.deepcopy(m.proposals(r)[1])
    if damage=='source':draft['source_sha256']='0'*64
    elif damage=='range':draft['edits'][0]['start']+=1
    elif damage=='replacement':draft['edits'][0]['replacement']='sorry\n'
    elif damage=='overlap':draft['edits'][1]['start']=draft['edits'][0]['start']
    else:draft['source']=draft['source'].replace('InitsUpdatesComm','ChangedTarget')
    with pytest.raises(ValueError):v.edit_check(r,draft)

def test_binder_names_are_discovered_and_not_hardcoded():
    r=record();r={**r,'src':r['src'].replace('Hlen2','localLength').replace(' ih =>',' smaller =>').replace('(ih Hinit','(smaller Hinit')}
    drafts=m.proposals(r)
    assert len(drafts)==2 and drafts[0]['binder']=='localLength' and drafts[1]['ih_binder']=='smaller'

@pytest.mark.parametrize('opaque',['-- comment\n','/- comment -/\n','\t','"quoted"','`quoted'])
def test_opaque_syntax_abstains(opaque):
    r=record();r={**r,'src':r['src']+'\n'+opaque}
    assert m.proposals(r)==[]

def test_explicitly_used_binder_is_never_nominated_for_deletion():
    r=record();r={**r,'src':r['src'].replace('    simp_all\n','    simp_all [Hlen2]\n',1)}
    assert m.proposals(r)==[]

def test_stale_edit_and_out_of_order_ranges_cannot_replay():
    r=record();edits=m.proposals(r)[1]['edits']
    with pytest.raises(ValueError):m.apply_edits(r['src'].replace('Hlen2','newName'),edits)
    with pytest.raises(ValueError):m.apply_edits(r['src'],list(reversed(edits)))

@pytest.fixture
def unavailable(tmp_path,monkeypatch):
    r=record();c=m.c
    prior={'rows':[{'name':r['name'],'lean_tag':tag,'git_commit':commit,'status':'UNAVAILABLE'}
                   for version in r['version_info'] for tag,commit in version.items()]}
    c.save(tmp_path/c.RUNTIME/'JLR-016.result.json',{'projects':[]})
    c.save(tmp_path/c.RUNTIME/'JLR-017.result.json',prior)
    monkeypatch.setattr(c,'module',lambda root,name: m if name=='lean_refactor_coupled_pilot.py' else SimpleNamespace(records=lambda:[r]))
    data={'schema':m.SCHEMA,'target':m.TARGET,'source_sha256':m.arena.source_hash(r['src']),
        'original_fallback':r['src'],'baseline_sha256':c.sha(tmp_path/c.RUNTIME/'JLR-017.result.json'),
        'readiness_sha256':c.sha(tmp_path/c.RUNTIME/'JLR-016.result.json'),'drafts':m.proposals(r),
        'rows':[{'pin':{'lean_tag':p['lean_tag'],'git_commit':p['git_commit']},'status':'UNAVAILABLE',
                 'reason':'UNAVAILABLE','initial':None,'capture':None,'samples':[],'confirmation':[]} for p in prior['rows']],
        'model_calls':0,'training_executed':False,'promoted':False,'official_score':None,
        'max_native_processes':24,'native_processes':0,'capture_processes':0,'winner':None,'status':'WAITING_NATIVE_PINS'}
    return tmp_path,data

def test_missing_pins_are_waits_and_never_semantic_success(unavailable):
    root,data=unavailable;m.c.save(root/m.c.RUNTIME/'JLR-020.partial.json',data)
    with pytest.raises(GateWait,match='exact native pins'):v.validate(root,data)

@pytest.mark.parametrize('damage',['missing_pin','duplicate_pin','confirmed','fake_sample','process_count','winner','training','arm'])
def test_protected_all_pin_and_resource_gates_reject_fabricated_completion(unavailable,damage):
    root,data=unavailable
    if damage=='missing_pin':data['rows'].pop()
    elif damage=='duplicate_pin':data['rows'][1]=copy.deepcopy(data['rows'][0])
    elif damage=='confirmed':data['status']='CONFIRMED'
    elif damage=='fake_sample':data['rows'][0]['samples']=[{'outcome':'VERIFIED'}]
    elif damage=='process_count':data['native_processes']=1
    elif damage=='winner':data['winner']=data['drafts'][1]['source']
    elif damage=='training':data['training_executed']=True
    else:data['drafts'][1]['arm']='isolated'
    m.c.save(root/m.c.RUNTIME/'JLR-020.partial.json',data)
    with pytest.raises(ValueError) as exc:v.validate(root,data)
    assert not isinstance(exc.value,GateWait)


def test_producer_admits_single_pin_context_without_erasing_required_report_pins(tmp_path,monkeypatch):
    r=record();c=m.c
    pins=[(tag,commit) for version in r['version_info'] for tag,commit in version.items()]
    assert len(pins)==3
    prior={'rows':[{'name':r['name'],'lean_tag':tag,'git_commit':commit,
                    'status':'VERIFIED' if i==0 else 'UNAVAILABLE'} for i,(tag,commit) in enumerate(pins)],
           'projects':[{'repository':r['url'],'lean_tag':pins[0][0],'git_commit':pins[0][1]}]}
    c.save(tmp_path/c.RUNTIME/'JLR-016.result.json',{'elan_home':'/private-fixture/no-compiler'})
    c.save(tmp_path/c.RUNTIME/'JLR-017.result.json',prior)
    monkeypatch.setattr(c,'module',lambda *_:SimpleNamespace(records=lambda:[r]))
    monkeypatch.setattr(m.arena_lean,'project_binding',lambda *a:object())
    class ReachedNativeBoundary(Exception):pass
    class ContextGuard:
        processes=0
        def __init__(self,bindings,**kw):self.pin=next(iter(bindings));self.branch_order=kw['branch_order']
        def context(self,scoped):
            assert scoped['version_info']==[{self.pin.lean_tag:self.pin.git_commit}]
            assert scoped['src']==r['src'] and scoped['statement']==r['statement']
            raise ReachedNativeBoundary
    monkeypatch.setattr(m.arena_lean,'NativeLeanVerifier',ContextGuard)
    with pytest.raises(ReachedNativeBoundary):m.produce(tmp_path)
    partial=c.read(tmp_path/c.RUNTIME/'JLR-020.partial.json')
    assert partial['native_processes']==0 and partial['status']=='RUNNING'
    assert len(r['version_info'])==3 and partial['winner'] is None


# Classification-only fixtures below never execute a scientific producer.
def classification_sample(arm,outcome):return {'arm':arm,'receipt':{'outcome':outcome}}
def classification_rows(coupled):
    return [{'status':'UNAVAILABLE','samples':[]},
            {'status':'MEASURED','samples':[classification_sample('isolated','REJECTED'),classification_sample('coupled',coupled)]}]


def test_definite_coupled_rejection_precedes_missing_pin_wait():
    data=classification_rows('REJECTED');before=copy.deepcopy(data)
    assert m.screening_status(data)=='NO_ALL_PIN_WINNER'
    assert data==before  # Missing and failed evidence is retained verbatim.


@pytest.mark.parametrize('outcome',['TIMEOUT','ERROR','VERIFIED'])
def test_missing_pins_do_not_turn_uncertainty_or_negative_control_into_semantic_failure(outcome):
    assert m.screening_status(classification_rows(outcome))=='WAITING_NATIVE_PINS'


def test_all_measured_coupled_success_only_enters_confirmation():
    data=[{'status':'MEASURED','samples':[classification_sample('isolated','REJECTED'),classification_sample('coupled','VERIFIED')]}]
    assert m.screening_status(data)=='SCREENED_ALL_PINS'


@pytest.fixture
def guarded_report(tmp_path,monkeypatch):
    # Only the already-tested native boundary is stubbed. Every test below is
    # a refusal/wait: no fixture can become accepted scientific evidence.
    record=next(r for r in m.c.module(ROOT,'lean_refactor_project_readiness.py').records() if r['name']==m.TARGET)
    pins=[{'lean_tag':tag,'git_commit':commit} for version in record['version_info'] for tag,commit in version.items()]
    prior={'rows':[{'name':m.TARGET,**pin,'status':'VERIFIED' if i==2 else 'UNAVAILABLE'} for i,pin in enumerate(pins)],
           'projects':[{'repository':record['url'],**pins[2]}]}
    c=m.c;c.save(tmp_path/c.RUNTIME/'JLR-017.result.json',prior)
    c.save(tmp_path/c.RUNTIME/'JLR-016.result.json',{'elan_home':'/not-a-native-execution-fixture'})
    drafts=m.proposals(record);origin={'fixture':'classification-only'}
    trace={'events':[{'status':'captured','start':0,'end':len(record['src'].encode())}]}
    capture={'origin':origin,'trace':trace}
    native_capture={'capture':capture,'ok':True,'evidence_mode':'local_lean','status':'OBSERVED',
                    'attempted_processes':1,'stage':{'report':trace}}
    data={'schema':m.SCHEMA,'target':m.TARGET,'source_sha256':m.arena.source_hash(record['src']),
          'original_fallback':record['src'],'baseline_sha256':c.sha(tmp_path/c.RUNTIME/'JLR-017.result.json'),
          'readiness_sha256':c.sha(tmp_path/c.RUNTIME/'JLR-016.result.json'),'drafts':drafts,
          'model_calls':0,'training_executed':False,'promoted':False,'official_score':None,
          'max_native_processes':24,'native_processes':6,'capture_processes':1,'winner':None,
          'status':'NO_ALL_PIN_WINNER','rows':[]}
    for i,pin in enumerate(pins):
        row={'pin':pin,'status':'UNAVAILABLE','reason':'UNAVAILABLE','initial':None,'capture':None,
             'samples':[],'confirmation':[]}
        if i==2:
            row.update(status='MEASURED',reason=None,initial={'source':record['src'],'receipt':{'outcome':'VERIFIED'}},
                       capture=native_capture,samples=[{'source':draft['source'],'arm':draft['arm'],
                       'branch_order':order,'receipt':{'outcome':'REJECTED'}} for draft in drafts for order in m.ORDERS])
        data['rows'].append(row)
    monkeypatch.setattr(c,'module',lambda _,name:m if name=='lean_refactor_coupled_pilot.py' else SimpleNamespace(records=lambda:[record]))
    monkeypatch.setattr(m.arena_lean,'project_binding',lambda *a:object())
    monkeypatch.setattr(m.arena_lean,'NativeLeanVerifier',lambda *a,**kw:SimpleNamespace(branch_order=kw['branch_order']))
    monkeypatch.setattr(m.arena_local,'ArenaLocalRuntime',lambda *a,**kw:SimpleNamespace(context=SimpleNamespace(context_id='fixture'),_origin=lambda _:origin))
    checked=[]
    monkeypatch.setattr(m.proof_replay,'_check_capture',lambda *a:checked.append('capture'))
    def bound_sample(sample,record,pin,guard,expected,required=False):
        assert sample['source']==expected
        if required:assert sample['receipt']['outcome']=='VERIFIED'
        checked.append('sample')
    monkeypatch.setattr(v,'sample_check',bound_sample)
    def publish():c.save(tmp_path/c.RUNTIME/'JLR-020.partial.json',data)
    publish();return tmp_path,data,publish,checked


def test_protected_validator_surfaces_rejection_after_native_guards_and_preserves_partial(guarded_report):
    root,data,publish,checked=guarded_report;before=(root/m.c.RUNTIME/'JLR-020.partial.json').read_bytes()
    with pytest.raises(ValueError,match='semantic repair required') as result:v.validate(root,data)
    assert not isinstance(result.value,GateWait)
    assert checked.count('sample')==5 and checked.count('capture')==1
    assert (root/m.c.RUNTIME/'JLR-020.partial.json').read_bytes()==before
    assert [row['status'] for row in data['rows']]==['UNAVAILABLE','UNAVAILABLE','MEASURED']


def test_protected_validator_rejects_old_resource_wait_label_for_known_semantic_failure(guarded_report):
    root,data,publish,checked=guarded_report;data['status']='WAITING_NATIVE_PINS';publish()
    with pytest.raises(ValueError,match='cannot be labeled a missing-pin wait') as result:v.validate(root,data)
    assert not isinstance(result.value,GateWait)


@pytest.mark.parametrize('outcome',['TIMEOUT','ERROR','VERIFIED'])
def test_protected_validator_keeps_genuine_missing_pin_waits(guarded_report,outcome):
    root,data,publish,checked=guarded_report;data['status']='WAITING_NATIVE_PINS'
    for row in data['rows']:
        for item in row['samples']:
            if item['arm']=='coupled':item['receipt']['outcome']=outcome
    publish()
    with pytest.raises(GateWait,match='exact native pins'):v.validate(root,data)


def test_semantic_failure_still_cannot_drop_a_required_pin(guarded_report):
    root,data,publish,checked=guarded_report;data['rows'].pop(0);publish()
    with pytest.raises(ValueError,match='all-pin denominator') as result:v.validate(root,data)
    assert not isinstance(result.value,GateWait)
