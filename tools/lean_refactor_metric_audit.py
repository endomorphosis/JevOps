#!/usr/bin/env python3
"""Bounded CPU measurement audit; local raw heartbeats never attest a worker.

The original reference is the only arm. Three ABBA order blocks run in fresh
native processes with installed import artifacts; no cache deletion, edits,
provider calls, training or official-score claims occur.
"""
from __future__ import annotations
import argparse
import ast
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import resource
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c
from jevops import arena,arena_lean
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

UTILS='papers/completion/lean_refactor_arena/upstream/lean_refactor/utils.py'
SPACE='papers/completion/lean_refactor_arena/space/'
SCHEMA='jevops.lean-refactor.metric-audit.v1'
ORDER_BLOCK=('reference-first','candidate-first','candidate-first','reference-first')

def upstream_tokenizer(root):
    # Execute only the pinned pure tokenizer and its five local helpers. Never
    # import upstream utils: its module imports scientific providers and agents.
    names={'proof_length','remove_comments','extract_and_remove_attributes',
           '_parse_single_attribute','return_theorem_to_prove_mathlib_style'}
    tree=ast.parse((root/UTILS).read_text())
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    c.require({node.name for node in selected}==names,'pinned tokenizer API changed')
    namespace={'re':re}
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(root/UTILS),'exec'),namespace)
    return namespace['proof_length']

def token_rows(root, records):
    official=upstream_tokenizer(root)
    return [{'name':r['name'],'source_sha256':arena.source_hash(r['src']),
             'published_tokens':r['proof_length'],
             'local_tokens':arena.reference_tokens(r['src'],r['statement']),
             'upstream_tokens':official(r['src'])} for r in records]

def resource_snapshot(root):
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                       if line.startswith('MemAvailable:')))*1024
    free=shutil.disk_usage(root).free
    return {'host_available_bytes':available,'disk_free_bytes':free,
            'eligible':available>=16*1024**3 and free>=512*1024**2}

def select(baseline, records):
    eligible=[(r,p) for r in records for p in baseline['rows']
              if p['name']==r['name'] and p['status']=='VERIFIED']
    c.require(eligible,'no verified native control pin')
    def measured_cost(item):
        wall=json.loads(item[1]['receipt']['observations_json'])['wall_ms']
        c.require(type(wall) in (int,float) and math.isfinite(wall) and wall>0,
                  'positive measured native control cost required')
        return wall,item[0]['name'],item[1]['lean_tag']
    return min(eligible,key=measured_cost)

def produce(root=ROOT):
    start=time.monotonic();before=resource_snapshot(root)
    c.require(before['eligible'],'CPU host/disk resource guard')
    records=c.module(root,'lean_refactor_project_readiness.py').records()
    path=root/c.RUNTIME/'JLR-017.result.json';baseline=c.read(path)
    ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    record,row=select(baseline,records);pin=VersionPin(row['lean_tag'],row['git_commit'])
    project=next(p for p in baseline['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                 (record['url'],pin.lean_tag,pin.git_commit))
    binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    reader=Fingerprinter()
    guards={order:arena_lean.NativeLeanVerifier({pin:binding},max_processes=6,timeout=60,
            branch_order=order,fingerprinter=reader) for order in set(ORDER_BLOCK)}
    per_pin={**record,'version_info':[{pin.lean_tag:pin.git_commit}]}
    samples=[]
    for repeat in range(3):
        for slot,order in enumerate(ORDER_BLOCK):
            c.require(not c.held(root),'operator hold')
            c.require(resource_snapshot(root)['eligible'],'CPU host/disk resource guard')
            guard=guards[order];context=guard.context(per_pin)
            receipt=guard(arena.VerificationRequest(context,record['src'],pin))
            sample={'repetition':repeat,'slot':slot,'branch_order':order,
                    'cache_label':'fresh_process_prepared_imports','context':asdict(context),
                    'receipt':asdict(receipt)}
            samples.append(sample)
            # Preserve partial failure observations if the worker is interrupted.
            c.save(root/c.RUNTIME/'JLR-018.partial.json',{'samples':samples,**c.AUTH})
    manifest=c.read(root/SPACE/'VENDOR_MANIFEST.json')
    c.require(manifest['evaluation_worker_included'] is False,'worker interface requires a new reviewed contract')
    return {'schema':SCHEMA,'baseline_sha256':c.sha(path),'token_rows':token_rows(root,records),
            'tokenizer_source_sha256':c.sha(root/UTILS),'worker_manifest_sha256':c.sha(root/SPACE/'VENDOR_MANIFEST.json'),
            'target':record['name'],'pin':pin.to_dict(),'samples':samples,
            'native_processes':sum(g.processes for g in guards.values()),'max_native_processes':12,
            'measurement':arena_lean.METHOD,'worker_metric_parity':'UNCONFIRMED',
            'worker_blocker':{'kind':'external_worker_interface_unavailable',
                'evidence':SPACE+'VENDOR_MANIFEST.json','observed_at':time.time(),
                'retry_condition':'organizer worker API/measurement specification becomes available'},
            'official_score':None,'model_calls':0,'training_executed':False,
            'proof_receipt_cache_enabled':False,'cache_protocol':'fresh_process_prepared_imports',
            'resources_before':before,'resources_after':resource_snapshot(root),
            'peak_child_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            'wall_seconds':time.monotonic()-start,**c.AUTH}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--produce',action='store_true',required=True);parser.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
