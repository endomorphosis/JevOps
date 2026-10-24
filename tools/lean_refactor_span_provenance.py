#!/usr/bin/env python3
"""Bounded source/pin provenance with native closing-tactic goal DAGs.

No embeddings, model loading, proposals, fitting or proof promotion. Missing
native captures remain unavailable and cannot become semantic training labels.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c
from jevops import arena_lean, arena_local, proof_replay
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

SCHEMA='jevops.lean-refactor.span-provenance.v1'

def segments(source, ranges=()):
    raw=source.encode();cuts={0,len(raw)}
    for start,end in ranges:
        c.require(type(start) is int and type(end) is int and 0<=start<end<=len(raw),'invalid source span')
        cuts.update((start,end))
    points=sorted(cuts)
    return [{'start_byte':a,'end_byte':b,'text':raw[a:b].decode('utf-8')}
            for a,b in zip(points,points[1:])]

def identity(record, pin, baseline_digest, context=None):
    return {'target':record['name'],'source_sha256':hashlib.sha256(record['src'].encode()).hexdigest(),
        'statement_sha256':hashlib.sha256(record['statement'].encode()).hexdigest(),
        'pin':pin,'baseline_sha256':baseline_digest,'context':context,
        'adapter_sha256':c.sha(Path(__file__)),
        'capture_adapter_sha256':arena_local._identity(),
        'embedding_model':None,'split':'public_warmup_development'}

def check_entry(entry, record, pin, baseline_digest, context=None):
    expected=identity(record,pin,baseline_digest,context)
    c.require(entry['identity']==expected and entry['cache_key']==hashlib.sha256(c.canonical(expected)).hexdigest(),
              'stale source, target, pin or dependency cache entry')
    cursor=0;raw=record['src'].encode()
    for part in entry['segments']:
        c.require(part['start_byte']==cursor and part['end_byte']>cursor and
                  raw[cursor:part['end_byte']]==part['text'].encode(),'source range or bytes changed')
        cursor=part['end_byte']
    c.require(cursor==len(raw),'incomplete source reconstruction')

def produce(root=ROOT):
    ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    baseline_path=root/c.RUNTIME/'JLR-017.result.json'
    baseline=c.read(baseline_path);digest=c.sha(baseline_path)
    producer=c.module(root,'lean_refactor_project_readiness.py')
    records=producer.records();rows=[];calls=0;started=time.monotonic()
    reader=Fingerprinter()
    for observed in baseline['rows']:
        record=next(r for r in records if r['name']==observed['name'])
        pin=VersionPin(observed['lean_tag'],observed['git_commit'])
        context=observed.get('context') if observed['status']=='VERIFIED' else None
        key=identity(record,pin.to_dict(),digest,context)
        row={'name':record['name'],'lean_tag':pin.lean_tag,'git_commit':pin.git_commit,
             'identity':key,'cache_key':hashlib.sha256(c.canonical(key)).hexdigest(),
             'segments':segments(record['src']),'status':'UNAVAILABLE',
             'reason':observed['status'],'capture':None,'native_result':None,
             'training_label':None,'dependency_closure_verified':False}
        if context is not None and calls<3 and time.monotonic()-started<150:
            project=next(p for p in baseline['projects'] if p['repository']==record['url'] and
                         p['lean_tag']==pin.lean_tag and p['git_commit']==pin.git_commit)
            binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
            guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=45,fingerprinter=reader)
            per_pin={**record,'version_info':[{pin.lean_tag:pin.git_commit}]}
            runtime=arena_local.ArenaLocalRuntime(guard,per_pin,max_processes=1,node_budget=4096,event_budget=64)
            result=runtime.capture(pin);calls+=runtime.attempts
            row['native_result']=result
            if result['ok'] and result['status']=='OBSERVED':
                capture=result['capture']
                proof_replay._check_capture(record['src'],capture,runtime.context.context_id)
                ranges=[(int(e['start']),int(e['end'])) for e in capture['trace']['events']
                        if e['status']=='captured' and e['start'] is not None and e['end'] is not None]
                row.update(status='NATIVE_CAPTURE',reason=None,capture=capture,
                           segments=segments(record['src'],ranges))
            else:row.update(status='CAPTURE_FAILED',reason=result.get('reason',result['status']))
        elif context is not None:row.update(status='BUDGET_EXHAUSTED',reason='three captures or 150 second admission bound')
        check_entry(row,record,pin.to_dict(),digest,context)
        rows.append(row)
    return {'schema':SCHEMA,'rows':rows,'required_pin_count':36,'native_capture_calls':calls,
        'native_capture_count':sum(r['status']=='NATIVE_CAPTURE' for r in rows),
        'baseline_sha256':digest,'duration_seconds':time.monotonic()-started,
        'proofs_verified':0,'training_executed':False,'embedding_loads':0,'model_calls':0,**c.AUTH}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True);p.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
