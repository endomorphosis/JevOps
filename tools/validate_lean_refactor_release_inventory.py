"""Protected independent acceptance of official source bytes and exact pins."""
import hashlib
import json
from pathlib import Path
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

def validate(root,data):
    c.require(data['schema']=='jevops.lean-refactor.release-inventory.v1' and
              type(data['observed_at']) in (int,float) and 0<=data['observed_at']<=time.time(),
              'release observation identity/time changed')
    historical='papers/completion/lean_refactor_arena/space/benchmark_data_warmup.jsonl'
    c.require(data['historical_sha256']==c.sha(root/historical) and
              data['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json'),
              'historical source/baseline drift')
    c.require(data['model_calls']==data['native_processes']==0 and data['training_executed'] is False and
              data['official_score'] is None and data['proof_authority'] is False and
              data['completion_authority'] is False,'metadata exceeded its authority')
    due=data['observed_at']>=1793491200
    c.require(data['gate']['release_due'] is due and data['gate']['not_before_utc']=='2026-11-01T00:00:00Z',
              'release date gate differs')
    requests=data['requests'];c.require(type(requests) is list and len(requests)<=3,'metadata request cap')
    if not due:
        c.require(data['status']=='WAITING_RELEASE' and not requests,'unreleased cohort claim or premature request')
        raise c.GateWait('official release not before 2026-11-01T00:00:00Z; cheap date probe rearms work')
    raw=[]
    for i,packet in enumerate(requests):
        path=root/packet['path']
        c.require(path.resolve().is_relative_to((root/c.RUNTIME/'release-evidence').resolve()) and
                  c.sha(path)==packet['sha256'] and path.stat().st_size==packet['bytes'] and
                  packet['bytes']<=(4*1024**2 if i==2 else 256*1024),'bounded immutable official bytes required')
        raw.append(path.read_bytes())
    api='https://huggingface.co/api/spaces/delta-lab-ai/lean-refactor-arena'
    if requests:c.require(requests[0]['url']==api,'substituted official metadata origin')
    if len(requests)>=2:
        revision=json.loads(raw[0])['sha'];c.require(re.fullmatch('[0-9a-f]{40}',revision),'unpinned release')
        c.require(requests[1]['url']==api+'/tree/'+revision,'tree revision drift')
    if data['status']=='WAITING_RELEASE':
        c.require(data.get('reason') in ('official_full_cohort_file_unavailable',
                  'official_full_cohort_denominator_unavailable','official_metadata_unavailable') and
                  data['retry_condition'],'unevidenced release wait')
        raise c.GateWait('official full cohort unavailable; retry next UTC day with retained metadata')
    c.require(data['status']=='INVENTORIED' and len(raw)==3,'full official source transcript required')
    tree=json.loads(raw[1]);filename=data['filename']
    c.require(filename in ('benchmark_data_full.jsonl','benchmark_data.jsonl') and
              any(item.get('type')=='file' and item.get('path')==filename for item in tree) and
              data['revision']==revision and requests[2]['url']==
              'https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/resolve/'+revision+'/'+filename,
              'official cohort revision/origin differs')
    records=[json.loads(line) for line in raw[2].decode('utf-8').splitlines() if line.strip()]
    c.require(len(records)==data['problem_count']==50 and len({r['name'] for r in records})==50,
              'full unique problem denominator required')
    pins=[]
    from jevops import arena
    for record in records:
        c.require(all(type(record[k]) is str and record[k] for k in ('name','source','statement','src','url')) and
                  record['url'].startswith('https://github.com/') and
                  arena.intake_error(record['src'],record['statement']) is None,
                  'invalid official theorem/source envelope')
        versions=record['version_info'];c.require(type(versions) is list and versions,'missing exact native pins')
        row=[]
        for version in versions:
            c.require(type(version) is dict and len(version)==1,'ambiguous version entry')
            tag,commit=next(iter(version.items()))
            c.require(re.fullmatch(r'v4\.\d+\.\d+',tag) and re.fullmatch('[0-9a-f]{40}',commit),
                      'exact Lean tag and git commit required')
            row.append((tag,commit))
        c.require(len(row)==len(set(row)),'duplicate native pin')
        pins.extend(row)
    c.require(len(pins)==data['pin_count'],'complete pin denominator differs')
    c.require(hashlib.sha256(raw[2]).hexdigest()!=data['historical_sha256'],'historical corpus relabeled as full')
    return {'problem_count':50,'required_pin_checks':len(pins),'native_proofs_verified':0,
            'official_score':None,'historical_corpus_preserved':True}
