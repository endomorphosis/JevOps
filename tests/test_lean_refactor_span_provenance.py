"""Source/cache adversaries; fixtures have no native proof authority."""
import copy
import hashlib
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import lean_refactor_span_provenance as m

RECORD={'name':'Demo.α','statement':'theorem α : True','src':'theorem α : True := by\n  trivial\n'}
PIN={'lean_tag':'v4.26.0','git_commit':'a'*40}

def entry():
    key=m.identity(RECORD,PIN,'b'*64,{'dependency_digests':['c'*64]})
    return {'identity':key,'cache_key':hashlib.sha256(m.c.canonical(key)).hexdigest(),
            'segments':m.segments(RECORD['src'],[(len('theorem α : True := by\n'.encode()),len(RECORD['src'].encode()))])}

def test_unicode_byte_spans_roundtrip_and_overlap_partition():
    raw=RECORD['src'].encode();out=m.segments(RECORD['src'],[(0,len(raw)),(8,len(raw))])
    assert ''.join(p['text'] for p in out)==RECORD['src']
    m.check_entry(entry(),RECORD,PIN,'b'*64,{'dependency_digests':['c'*64]})

@pytest.mark.parametrize('damage',['source','target','pin','dependencies','baseline','cache_key','gap','overlap','text','truncation'])
def test_stale_cross_version_and_modified_source_entries_are_rejected(damage):
    row=entry();record=copy.deepcopy(RECORD);pin=copy.deepcopy(PIN);baseline='b'*64;context={'dependency_digests':['c'*64]}
    if damage=='source':record['src']+='\n'
    elif damage=='target':record['name']='Other.theorem'
    elif damage=='pin':pin['lean_tag']='v4.27.0'
    elif damage=='dependencies':context['dependency_digests']=['d'*64]
    elif damage=='baseline':baseline='d'*64
    elif damage=='cache_key':row['cache_key']='f'*64
    elif damage=='gap':row['segments'][0]['start_byte']=1
    elif damage=='overlap':row['segments'][1]['start_byte']=0
    elif damage=='text':row['segments'][0]['text']='forged'
    else:row['segments'].pop()
    with pytest.raises(ValueError):m.check_entry(row,record,pin,baseline,context)

@pytest.mark.parametrize('range_',[(True,2),(-1,2),(3,2),(0,99999),(9,10)])
def test_invalid_or_split_utf8_ranges_refused(range_):
    with pytest.raises((ValueError,UnicodeError)):m.segments(RECORD['src'],[range_])
