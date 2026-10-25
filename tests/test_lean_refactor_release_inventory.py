"""Private transport fixtures qualify inventory machinery, never native proofs."""
import copy
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_release_inventory as m
import validate_lean_refactor_release_inventory as v

@pytest.fixture
def campaign(tmp_path):
    m.c.atomic(tmp_path/m.HISTORICAL,'historical source bytes\n')
    m.c.save(tmp_path/m.c.RUNTIME/'JLR-017.result.json',{'private_fixture':True})
    return tmp_path

def transport(records=None):
    revision='a'*40
    if records is None:
        records=[{'name':'demo'+str(i),'source':'private-fixture','statement':f'theorem demo{i} : True',
          'src':f'theorem demo{i} : True := by trivial','url':'https://github.com/private/fixture',
          'version_info':[{'v4.26.0':'b'*40}]} for i in range(50)]
    responses=[json.dumps({'sha':revision}).encode(),
      json.dumps([{'type':'file','path':'benchmark_data_full.jsonl'}]).encode(),
      '\n'.join(json.dumps(r) for r in records).encode()]
    calls=[]
    def get(url,limit,deadline):
        calls.append((url,limit));return responses[len(calls)-1]
    return get,calls

def test_pre_release_does_no_network_and_keeps_historical_bytes(campaign,monkeypatch):
    monkeypatch.setattr(v.time,'time',lambda:m.RELEASE_AT-1)
    before=(campaign/m.HISTORICAL).read_bytes()
    def forbidden(*args):raise AssertionError('premature external request')
    data=m.produce(campaign,now=m.RELEASE_AT-1,getter=forbidden)
    assert data['status']=='WAITING_RELEASE' and data['requests']==[]
    with pytest.raises(m.c.GateWait,match='not before'):v.validate(campaign,data)
    assert (campaign/m.HISTORICAL).read_bytes()==before

def test_cheap_gate_changes_at_release_and_next_day_without_network(campaign):
    a=m.probe(campaign,now=m.RELEASE_AT-100)
    assert m.probe(campaign,now=m.RELEASE_AT-1)==a
    b=m.probe(campaign,now=m.RELEASE_AT)
    assert a!=b and b['release_due'] is True
    assert m.probe(campaign,now=m.RELEASE_AT+30)==b
    assert m.probe(campaign,now=m.RELEASE_AT+86400)!=b

def test_pinned_cohort_inventory_reparsed_independently_with_complete_denominators(campaign,monkeypatch):
    monkeypatch.setattr(v.time,'time',lambda:m.RELEASE_AT+10)
    get,calls=transport();data=m.produce(campaign,now=m.RELEASE_AT,getter=get)
    result=v.validate(campaign,data)
    assert result['problem_count']==result['required_pin_checks']==50
    assert result['native_proofs_verified']==0 and result['official_score'] is None
    assert len(calls)==3 and calls[-1][0]==m.SPACE+'/resolve/'+'a'*40+'/benchmark_data_full.jsonl'
    assert [limit for _,limit in calls]==[256*1024,256*1024,4*1024**2]
    assert (campaign/m.HISTORICAL).read_text()=='historical source bytes\n'

@pytest.mark.parametrize('damage',['count','pin','source','duplicate','origin','bytes','early','authority'])
def test_protected_inventory_rejects_claims_and_substituted_source(campaign,monkeypatch,damage):
    monkeypatch.setattr(v.time,'time',lambda:m.RELEASE_AT+10)
    get,_=transport();data=m.produce(campaign,now=m.RELEASE_AT,getter=get)
    if damage=='count':data['problem_count']=49
    elif damage=='pin':data['pin_count']=49
    elif damage=='source':data['historical_sha256']='0'*64
    elif damage=='origin':data['requests'][2]['url']='https://example.org/forged.jsonl'
    elif damage=='bytes':(campaign/data['requests'][2]['path']).write_text('forged')
    elif damage=='early':data['observed_at']=m.RELEASE_AT-1
    elif damage=='authority':data['proof_authority']=True
    else:
        rows=[json.loads(line) for line in (campaign/data['requests'][2]['path']).read_text().splitlines()]
        rows[1]=copy.deepcopy(rows[0]);get,_=transport(rows)
        data=m.produce(campaign,now=m.RELEASE_AT,getter=get)
    with pytest.raises((ValueError,KeyError)):v.validate(campaign,data)

@pytest.mark.parametrize('version',[{'v4.26.0':'main'},{'latest':'b'*40},{'v4.26.0':'b'*40,'v4.27.0':'c'*40}])
def test_moving_or_ambiguous_pins_cannot_accept_full_inventory(campaign,monkeypatch,version):
    monkeypatch.setattr(v.time,'time',lambda:m.RELEASE_AT+10)
    get,_=transport();data=m.produce(campaign,now=m.RELEASE_AT,getter=get)
    rows=[json.loads(line) for line in (campaign/data['requests'][2]['path']).read_text().splitlines()]
    rows[0]['version_info']=[version];get,_=transport(rows)
    data=m.produce(campaign,now=m.RELEASE_AT,getter=get)
    with pytest.raises(ValueError):v.validate(campaign,data)

def test_official_missing_file_is_wait_and_keeps_received_metadata(campaign,monkeypatch):
    monkeypatch.setattr(v.time,'time',lambda:m.RELEASE_AT+10)
    responses=[b'{"sha":"'+b'a'*40+b'"}',b'[]'];calls=[]
    def get(*args):calls.append(args);return responses[len(calls)-1]
    data=m.produce(campaign,now=m.RELEASE_AT,getter=get)
    assert len(data['requests'])==2 and data['status']=='WAITING_RELEASE'
    with pytest.raises(m.c.GateWait,match='next UTC day'):v.validate(campaign,data)

def test_hold_refuses_before_transport(campaign):
    (campaign/'OPERATOR_STOP').touch()
    with pytest.raises(ValueError,match='operator hold'):m.produce(campaign)
