#!/usr/bin/env python3
"""Bounded official cohort inventory, gated by the announced release date.

Metadata only: never replace the historical corpus, execute downloaded code,
compile proofs, generate proposals, or submit a portfolio.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c

SCHEMA='jevops.lean-refactor.release-inventory.v1'
RELEASE_AT=1793491200  # 2026-11-01T00:00:00Z
API='https://huggingface.co/api/spaces/delta-lab-ai/lean-refactor-arena'
SPACE='https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena'
HISTORICAL='papers/completion/lean_refactor_arena/space/benchmark_data_warmup.jsonl'
FILES=('benchmark_data_full.jsonl','benchmark_data.jsonl')
GATE=c.RUNTIME+'/release-gate.json'

def probe(root=ROOT, *, now=None):
    now=time.time() if now is None else now
    due=now>=RELEASE_AT
    gate={'schema':'jevops.lean-refactor.release-gate.v1','not_before_utc':'2026-11-01T00:00:00Z',
          'release_due':due,'retry_utc_day':dt.datetime.fromtimestamp(now,dt.timezone.utc).date().isoformat() if due else None,
          **c.AUTH}
    c.save(root/GATE,gate)
    return gate

def fetch(url, limit, deadline):
    c.require(deadline>time.monotonic(),'metadata deadline exhausted')
    request=urllib.request.Request(url,headers={'User-Agent':'JevOps-bounded-release-inventory/1'})
    with urllib.request.urlopen(request,timeout=min(10,deadline-time.monotonic())) as response:
        final=urlsplit(response.url)
        c.require(response.status==200 and final.scheme=='https' and final.netloc=='huggingface.co',
                  'official metadata redirect/status changed')
        raw=response.read(limit+1)
    c.require(len(raw)<=limit,'official metadata exceeds byte cap')
    return raw

def produce(root=ROOT, *, now=None, getter=fetch):
    now=time.time() if now is None else now
    c.require(not c.held(root),'operator hold')
    gate=probe(root,now=now)
    report={'schema':SCHEMA,'observed_at':now,'gate':gate,'historical_sha256':c.sha(root/HISTORICAL),
      'baseline_sha256':c.sha(root/c.RUNTIME/'JLR-017.result.json'),'requests':[],
      'status':'WAITING_RELEASE','retry_condition':'At or after 2026-11-01 UTC, official pinned full cohort is available',
      'model_calls':0,'native_processes':0,'training_executed':False,'official_score':None,**c.AUTH}
    if not gate['release_due']:return report
    deadline=time.monotonic()+35
    def get(url,limit,label):
        c.require(len(report['requests'])<3 and not c.held(root),'request/operator limit')
        raw=getter(url,limit,deadline)
        path=root/c.RUNTIME/'release-evidence'/(hashlib.sha256(raw).hexdigest()+'.'+label)
        if not path.exists():
            c.atomic(path,raw.decode('utf-8'))
        c.require(c.sha(path)==hashlib.sha256(raw).hexdigest(),'evidence bytes changed')
        report['requests'].append({'url':url,'path':str(path.relative_to(root)),
          'sha256':c.sha(path),'bytes':len(raw)})
        return raw
    try:
        metadata=json.loads(get(API,256*1024,'metadata.json'))
        revision=metadata['sha'];c.require(re.fullmatch('[0-9a-f]{40}',revision),'official source revision required')
        tree=json.loads(get(API+'/tree/'+revision,256*1024,'tree.json'))
        names={item['path'] for item in tree if item.get('type')=='file'}
        filename=next((name for name in FILES if name in names),None)
        if filename is None:
            report['reason']='official_full_cohort_file_unavailable';return report
        raw=get(SPACE+'/resolve/'+revision+'/'+filename,4*1024**2,'cohort.jsonl')
        records=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        if len(records)!=50:
            report.update(reason='official_full_cohort_denominator_unavailable',observed_problem_count=len(records));return report
        report.update(status='INVENTORIED',revision=revision,filename=filename,
          problem_count=len(records),pin_count=sum(len(v) for r in records for v in r['version_info']))
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
        report['reason']='official_metadata_unavailable';report['error_type']=type(exc).__name__
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',required=True,action='store_true');p.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
