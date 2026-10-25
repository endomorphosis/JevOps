#!/usr/bin/env python3
"""One fixed, profile-guided support-deletion pilot with whole-source checks.

Historical source is an unverified incumbent nomination. New instrumentation
only ranks exact source-bound edits; twelve fresh confirmation processes are
reserved before searching. No model, training, cache clearing or promotion.
"""
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
from lean_refactor_metric_audit import ORDER_BLOCK,resource_snapshot
from jevops import arena,arena_lean,arena_local,solver_feedback
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

SEED='papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/solver-0.json'
TARGET='CallElimCorrect.extractedOldExprInVars'
SCHEMA='jevops.lean-refactor.simp-pilot.v1'
PROFILE_TIMEOUT=180

def proposals(record, source, profile):
    c.require(arena.intake_error(source,record['statement']) is None,'incumbent theorem envelope changed')
    costs={}
    for event in profile['events']:
        # A cost prior only. Hints never supply source positions or replay data.
        if 'simp' in event['syntax_kind']:
            costs[event['hint'].strip()]=max(costs.get(event['hint'].strip(),0),event['inclusive_raw'])
    drafts=[];seen=set()
    for edit in solver_feedback.support_edits(source,max_sites=4):
        candidate=edit.apply(source)
        if candidate in seen or arena.intake_error(candidate,record['statement']):continue
        seen.add(candidate)
        if arena.reference_tokens(candidate,record['statement'])>=arena.reference_tokens(source,record['statement']):continue
        line=source[edit.start:edit.end].strip()
        cost=max((v for hint,v in costs.items() if hint and (hint==line or hint in line)),default=0)
        drafts.append({'source':candidate,'edit':asdict(edit),'cost_prior_raw':cost})
    return sorted(drafts,key=lambda d:(-d['cost_prior_raw'],d['edit']['start'],arena.source_hash(d['source'])))[:10]

def produce(root=ROOT):
    started=time.monotonic();resources=resource_snapshot(root)
    c.require(resources['eligible'] and not c.held(root),'CPU resource or operator gate')
    records=c.module(root,'lean_refactor_project_readiness.py').records()
    record=next(r for r in records if r['name']==TARGET)
    pins=[VersionPin(tag,commit) for version in record['version_info'] for tag,commit in version.items()]
    c.require(len(pins)==1,'this bounded pilot requires the complete one-pin target')
    pin=pins[0];ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    prior=c.read(root/c.RUNTIME/'JLR-017.result.json')
    c.require(any(r['name']==TARGET and r['lean_tag']==pin.lean_tag and r['git_commit']==pin.git_commit and
                  r['status']=='VERIFIED' for r in prior['rows']),'fresh native original baseline required')
    project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                 (record['url'],pin.lean_tag,pin.git_commit))
    binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    incumbent=c.read(root/SEED)['source'];reader=Fingerprinter()
    guards={order:arena_lean.NativeLeanVerifier({pin:binding},max_processes=24,timeout=60,
            branch_order=order,fingerprinter=reader) for order in set(ORDER_BLOCK)}
    report={'schema':SCHEMA,'target':TARGET,'pin':pin.to_dict(),'incumbent':incumbent,
        'seed_sha256':c.sha(root/SEED),'baseline_sha256':c.sha(root/c.RUNTIME/'JLR-017.result.json'),
        'status':'RUNNING','initial':None,'profile':None,'drafts':[],'screen':[],
        'winner':None,'confirmation':[],'native_processes':0,'max_native_processes':24,
        'max_candidates':10,'resources_before':resources,'model_calls':0,'training_executed':False,
        'promoted':False,'official_score':None,'original_fallback':record['src'],**c.AUTH}
    runtime=None
    def persist():
        report['native_processes']=sum(g.processes for g in guards.values())+(runtime.attempts if runtime else 0)
        report['wall_seconds']=time.monotonic()-started
        c.save(root/c.RUNTIME/'JLR-019.partial.json',report)
    def measure(source,order):
        c.require(not c.held(root) and resource_snapshot(root)['eligible'],'CPU resource or operator gate')
        c.require(time.monotonic()-started<780,'bounded pilot wall admission exhausted; partial retained')
        c.require(report['native_processes']<24,'native process cap')
        guard=guards[order];context=guard.context(record)
        receipt=guard(arena.VerificationRequest(context,source,pin))
        sample={'source':source,'branch_order':order,'context':asdict(context),'receipt':asdict(receipt)}
        report['native_processes']=sum(g.processes for g in guards.values())+(runtime.attempts if runtime else 0)
        return sample
    report['initial']=measure(incumbent,'reference-first');persist()
    if report['initial']['receipt']['outcome']!='VERIFIED':
        report['status']='BLOCKED_INCUMBENT';persist();return report
    guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=PROFILE_TIMEOUT,fingerprinter=reader)
    runtime=arena_local.ArenaLocalRuntime(guard,record,max_processes=1,node_budget=20000,event_budget=256)
    report['profile']=runtime.profile(pin,source=incumbent,threshold_raw=100);persist()
    if not report['profile']['ok']:
        report['status']='BLOCKED_NATIVE_PROFILE';persist();return report
    report['drafts']=proposals(record,incumbent,report['profile']['profile']);persist()
    for draft in report['drafts']:
        report['screen'].append(measure(draft['source'],'reference-first'));persist()
    valid=[s for s in report['screen'] if s['receipt']['outcome']=='VERIFIED']
    if not valid:
        report['status']='NO_SHORTER_WINNER';persist();return report
    winner=min(valid,key=lambda s:(arena.reference_tokens(s['source'],record['statement']),arena.source_hash(s['source'])))
    report['winner']=winner['source'];persist()  # Frozen before confirmation.
    for repeat in range(3):
        for slot,order in enumerate(ORDER_BLOCK):
            sample=measure(report['winner'],order)
            sample.update(repetition=repeat,slot=slot)
            report['confirmation'].append(sample);persist()
    report['status']='CONFIRMED' if all(s['receipt']['outcome']=='VERIFIED' for s in report['confirmation']) else 'CONFIRMATION_FAILED'
    persist();return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True);p.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
