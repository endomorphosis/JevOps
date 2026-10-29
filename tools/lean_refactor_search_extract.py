#!/usr/bin/env python3
"""Bounded native search and explicit-term export; no provider or training calls."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c
from lean_refactor_metric_audit import resource_snapshot
from jevops import arena,arena_lean,arena_local,proof_replay
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

SCHEMA='jevops.lean-refactor.search-extract.v1'
TARGET='CallElimCorrect.extractedOldExprInVars'
PREMISES=('And.intro','Or.inl','Or.inr','True.intro','False.elim','Eq.refl')
LIMITS={'search_branches':12,'events':3,'steps_per_event':4,'depth':3,
        'native_processes':7,'export_bytes':4096,'token_growth':64,
        'node_budget':20000,'event_budget':256,'wall_seconds':780}

def closed_events(source,capture):
    """Deterministic exact UTF8 closing spans; observations never supply edits."""
    raw=source.encode();eligible=[]
    for event in capture['trace']['events']:
        if event.get('status')!='captured' or event.get('after',{}).get('goals')!=[]:continue
        if len(event.get('before',{}).get('goals',[]))!=1:continue
        try:
            a,b=int(event['start']),int(event['end'])
            c.require(0<=a<b<=len(raw),'capture range')
            syntax=raw[a:b].decode()
            if not syntax.strip().startswith(('exact ','apply ','simp','rfl','assumption','trivial')):continue
            proof_replay.replace_event(source,event,'exact True.intro')
        except (ValueError,KeyError,TypeError,UnicodeError):continue
        # Prefer a closing local-context anchor that the bounded search can
        # actually materialize. The previous length-only ranking exhausted all
        # three event slots on simp_all goals outside the four-step grammar.
        # Selection uses frozen original syntax, never a search/model outcome.
        stripped=syntax.strip()
        rank=0 if stripped=='assumption' else 1 if stripped.startswith('exact ') else 2 if stripped=='rfl' else 3
        eligible.append((rank,b-a,a,int(event['id']),event))
    return [row[-1] for row in sorted(eligible,key=lambda r:r[:4])[:LIMITS['events']]]

def export_candidate(source,statement,event,result):
    c.require(result.get('ok') is True and result.get('evidence_mode')=='local_lean'
              and result.get('closing_reproduced') is True
              and result.get('proof_admitted') is False
              and result.get('whole_source_checked') is False,
              'native search and independent term roundtrip required')
    term=result.get('extracted_candidate')
    c.require(type(term) is str and term.startswith('exact ')
              and len(term.encode())<=LIMITS['export_bytes'],'bounded explicit term required')
    c.require(type(result.get('search_steps_observed')) is int
              and 0<result['search_steps_observed']<=LIMITS['steps_per_event']
              and result.get('search_steps_reserved')==LIMITS['steps_per_event']
              and result.get('roundtrip_attempts')==1,'charged bounded search required')
    candidate=proof_replay.replace_event(source,event,term)
    c.require(arena.intake_error(candidate,statement) is None,'original theorem envelope changed')
    growth=arena.reference_tokens(candidate,statement)-arena.reference_tokens(source,statement)
    c.require(growth<=LIMITS['token_growth'],'export token growth exceeded')
    return {'source':candidate,'source_sha256':arena.source_hash(candidate),
            'term':term,'term_bytes':len(term.encode()),'token_growth':growth}

def target_inputs(root):
    record=next(r for r in c.module(root,'lean_refactor_project_readiness.py').records() if r['name']==TARGET)
    pins=[VersionPin(tag,commit) for version in record['version_info'] for tag,commit in version.items()]
    c.require(len(pins)==1,'bounded producer requires the complete one-pin target')
    baseline=c.read(root/c.RUNTIME/'JLR-017.result.json');ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    bindings={}
    for pin in pins:
        c.require(any(r['name']==TARGET and r['lean_tag']==pin.lean_tag and r['git_commit']==pin.git_commit
                      and r['status']=='VERIFIED' for r in baseline['rows']),'verified exact-pin baseline required')
        project=next(p for p in baseline['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                     (record['url'],pin.lean_tag,pin.git_commit))
        bindings[pin]=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    return record,pins,bindings

def produce(root=ROOT,*,output_directory=None):
    started=time.monotonic();directory=output_directory or root/c.RUNTIME
    record,pins,bindings=target_inputs(root);pin=pins[0];source=record['src']
    resources=resource_snapshot(root)
    c.require(resources['eligible'] and not c.held(root),'CPU resource or operator gate')
    reader=Fingerprinter()
    guard=arena_lean.NativeLeanVerifier(bindings,max_processes=3,timeout=60,fingerprinter=reader)
    local_guard=arena_lean.NativeLeanVerifier(bindings,max_processes=0,timeout=120,fingerprinter=reader)
    runtime=arena_local.ArenaLocalRuntime(local_guard,record,max_processes=4,
                    node_budget=LIMITS['node_budget'],event_budget=LIMITS['event_budget'])
    report={'schema':SCHEMA,'target':TARGET,'pins':[p.to_dict() for p in pins],
        'original_fallback':source,'source_sha256':arena.source_hash(source),'limits':LIMITS,
        'baseline_sha256':c.sha(root/c.RUNTIME/'JLR-017.result.json'),
        'readiness_sha256':c.sha(root/c.RUNTIME/'JLR-016.result.json'),
        'producer_sha256':c.sha(Path(__file__)),'resources_before':resources,
        'status':'RUNNING','initial':None,'capture':None,'searches':[],
        'winner':None,'confirmation':[],'model_calls':0,'training_executed':False,
        'promoted':False,'official_score':None,'optimization_success':False,**c.AUTH}
    def persist():
        report['native_processes']=guard.processes+runtime.attempts
        report['wall_seconds']=time.monotonic()-started
        c.save(directory/'JLR-021.partial.json',report)
    def admit():
        c.require(not c.held(root) and resource_snapshot(root)['eligible'],'CPU resource or operator gate')
        c.require(time.monotonic()-started<LIMITS['wall_seconds']-120,'bounded wall admission exhausted')
        c.require(guard.processes+runtime.attempts<LIMITS['native_processes'],'native process cap')
    admit();context=guard.context(record)
    report['initial']=asdict(guard(arena.VerificationRequest(context,source,pin)));persist()
    if report['initial']['outcome']!='VERIFIED':report['status']='BLOCKED_ORIGINAL';persist();return report
    admit();report['capture']=runtime.capture(pin);persist()
    if not report['capture']['ok']:report['status']='BLOCKED_CAPTURE';persist();return report
    capture=report['capture']['capture']
    for event in closed_events(source,capture):
        admit();result=runtime.discover_search(pin,source,capture,int(event['id']),list(PREMISES),
                max_steps=LIMITS['steps_per_event'],max_depth=LIMITS['depth'])
        row={'event_id':int(event['id']),'result':result,'export':None};report['searches'].append(row);persist()
        if not result.get('closing_reproduced'):continue
        try:row['export']=export_candidate(source,record['statement'],event,result)
        except ValueError as exc:row['export_refusal']=str(exc);persist();continue
        report['winner']=row['export'];persist();break
    if report['winner'] is None:report['status']='NO_EXTRACTED_TERM';persist();return report
    # Freeze the exported source before either fresh whole-theorem replay.
    for order in ('reference-first','candidate-first'):
        admit();check=arena_lean.NativeLeanVerifier(bindings,max_processes=1,timeout=60,
                            branch_order=order,fingerprinter=reader)
        receipt=check(arena.VerificationRequest(check.context(record),report['winner']['source'],pin))
        guard.processes+=check.processes
        report['confirmation'].append({'pin':pin.to_dict(),'branch_order':order,'receipt':asdict(receipt)});persist()
    report['status']='CONFIRMED_EXTRACTION' if all(s['receipt']['outcome']=='VERIFIED'
                for s in report['confirmation']) else 'COLD_REPLAY_FAILED'
    persist();return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True)
    p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--output-directory',type=Path);args=p.parse_args()
    print(json.dumps(produce(args.repo.resolve(),output_directory=args.output_directory),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
