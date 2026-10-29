#!/usr/bin/env python3
"""Bounded prefix-binder deletion with induction argument/goal repair.

Lexical ranges nominate edits. A native InfoTree binds their enclosing proof;
fresh whole-source checks supply every semantic decision. Missing pins remain
external waits. No model calls, training, or automatic proof promotion.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c
from lean_refactor_metric_audit import resource_snapshot
from jevops import arena,arena_lean,arena_local,proof_replay
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

TARGET='Core.InitsUpdatesComm'
SCHEMA='jevops.lean-refactor.coupled-pilot.v1'
ORDERS=('reference-first','candidate-first')

def proposals(record):
    """Conservative grammar; original offsets and all dependent edits retained.

    This first execution contract handles a prefix have and an IH application
    with explicit goal bullets. Binder names are discovered from source; no
    lexical analysis is presented as an elaborated dependency proof.
    """
    source=record['src']
    c.require(arena.intake_error(source,record['statement']) is None,'theorem envelope changed')
    if any(x in source for x in ('--','/-','-/','\t','"','`')):return []
    induction=re.search(r'(?m)^  induction [^\n]+\n',source)
    if induction is None:return []
    declarations=list(re.finditer(r'(?m)^  have ([^\W\d][\w\']*) := ([^\n]+)\n',source[:induction.start()]))
    sites=list(re.finditer(r'(?m)^( +)\. apply \(([^ ()]+) ([^\n()]+) \?_ \?_\)\.2\.2\n'
        r'(\1  \. [^\n]+\n)\1  \. [^\n]+(?:\n|$)',source))
    if len(sites)!=1:return []
    site=sites[0];prefix=source[:site.start()]
    case=re.findall(r'(?m)^  case [^\n]+ =>$',prefix)
    if not case or case[-1].split()[-2]!=site[2]:return []
    drafts=[]
    for declaration in declarations:
        # Only the last prefix binder is nominated. Removing one generalized
        # hypothesis removes one trailing IH argument/goal, not both. Native
        # whole-source checking still decides whether that nomination is sound.
        if declaration!=declarations[-1]:continue
        name=declaration[1]
        # Exact explicit uses disqualify deletion. Implicit context effects
        # remain a native experiment, including simp_all and IH arity.
        if re.search(r'(?<![\w\'])'+re.escape(name)+r'(?![\w\'])',source[declaration.end():]):continue
        first={'start':declaration.start(),'end':declaration.end(),'replacement':'',
               'original':declaration[0]}
        replacement=site[1]+'. apply ('+site[2]+' '+site[3]+' ?_).2.2\n'+site[4]
        repair={'start':site.start(),'end':site.end(),'replacement':replacement,'original':site[0]}
        for arm,edits in (('isolated',[first]),('coupled',[first,repair])):
            candidate=apply_edits(source,edits)
            if arena.reference_tokens(candidate,record['statement'])>=arena.reference_tokens(source,record['statement']):continue
            drafts.append({'arm':arm,'binder':name,'induction_start':induction.start(),
                'ih_binder':site[2],'source_sha256':arena.source_hash(source),
                'edits':edits,'source':candidate,'dependency_claim':'lexical_nomination_requires_native_replay'})
        if len(drafts)==2:break  # One fixed matched pair, never cherry-picked.
    return drafts

def apply_edits(source,edits):
    c.require(1<=len(edits)<=2,'bounded coupled edit count')
    cursor=0
    for edit in edits:
        a,b=edit['start'],edit['end']
        c.require(type(a) is int and type(b) is int and cursor<=a<b<=len(source) and
                  source[a:b]==edit['original'],'stale or overlapping source range')
        cursor=b
    candidate=source
    for edit in reversed(edits):candidate=candidate[:edit['start']]+edit['replacement']+candidate[edit['end']:]
    return candidate

def screening_status(rows):
    # A single exact-pin rejection disproves THIS all-pin candidate, even when
    # other pins are unavailable. Timeouts/errors remain inconclusive; rejection
    # of the isolated negative control does not disprove the coupled candidate.
    if any(s['arm']=='coupled' and s['receipt']['outcome']=='REJECTED'
           for row in rows for s in row['samples']):
        return 'NO_ALL_PIN_WINNER'
    if any(row['status']!='MEASURED' for row in rows):return 'WAITING_NATIVE_PINS'
    coupled=[s for row in rows for s in row['samples'] if s['arm']=='coupled']
    if not all(s['receipt']['outcome']=='VERIFIED' for s in coupled):return 'NO_ALL_PIN_WINNER'
    return 'SCREENED_ALL_PINS'

def produce(root=ROOT):
    if (root/c.PROFILE).is_file():
        profile=c.load(root)[0]
        if 'tools/lean_refactor_compiled_coupled_v1.py' in profile['source_sha256']:
            return c.module(root,'lean_refactor_compiled_coupled_v1.py').produce(root)
    started=time.monotonic();before=resource_snapshot(root)
    c.require(before['eligible'] and not c.held(root),'CPU resource or operator gate')
    record=next(r for r in c.module(root,'lean_refactor_project_readiness.py').records() if r['name']==TARGET)
    drafts=proposals(record);c.require(len(drafts)==2,'no supported matched coupled edit')
    import lean_refactor_native_pin_frontier as frontier
    pin_frontier=frontier.produce(root)
    prior,ready=frontier.effective_inputs(root,pin_frontier)
    report={'schema':SCHEMA,'target':TARGET,'source_sha256':arena.source_hash(record['src']),
        'baseline_sha256':c.sha(root/c.RUNTIME/'JLR-017.result.json'),
        'readiness_sha256':c.sha(root/c.RUNTIME/'JLR-016.result.json'),
        'pin_frontier':pin_frontier,
        'drafts':drafts,'rows':[],'native_processes':0,'capture_processes':0,'max_native_processes':24,
        'status':'RUNNING','winner':None,'original_fallback':record['src'],
        'model_calls':0,'training_executed':False,'promoted':False,'official_score':None,
        'resources_before':before,**c.AUTH}
    guards=[];captures=[]
    def persist():
        report['native_processes']=sum(g.processes for g in guards)+sum(rt.attempts for rt in captures)
        report['capture_processes']=sum(rt.attempts for rt in captures)
        report['wall_seconds']=time.monotonic()-started
        c.save(root/c.RUNTIME/'JLR-020.partial.json',report)
    def measure(guard,pin,source):
        persist()
        c.require(not c.held(root) and resource_snapshot(root)['eligible'],'CPU resource or operator gate')
        c.require(report['native_processes']<24 and time.monotonic()-started<780,'coupled pilot admission cap')
        per_pin={**record,'version_info':[{pin.lean_tag:pin.git_commit}]}
        context=guard.context(per_pin);receipt=guard(arena.VerificationRequest(context,source,pin))
        sample={'source':source,'branch_order':guard.branch_order,'context':asdict(context),'receipt':asdict(receipt)}
        persist();return sample
    reader=Fingerprinter()
    for version in record['version_info']:
        for tag,commit in version.items():
            pin=VersionPin(tag,commit)
            original=next(r for r in prior['rows'] if (r['name'],r['lean_tag'],r['git_commit'])==(TARGET,tag,commit))
            row={'pin':pin.to_dict(),'status':'UNAVAILABLE','reason':original['status'],
                 'initial':None,'capture':None,'samples':[],'confirmation':[]}
            report['rows'].append(row);persist()
            if original['status']!='VERIFIED':continue
            project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                         (record['url'],tag,commit))
            binding=arena_lean.project_binding(record,pin,project,Path(project.get('elan_home',ready['elan_home'])))
            per_order={o:arena_lean.NativeLeanVerifier({pin:binding},max_processes=24,timeout=60,
                       branch_order=o,fingerprinter=reader) for o in ORDERS}
            guards.extend(per_order.values())
            row['initial']=measure(per_order[ORDERS[0]],pin,record['src']);persist()
            if row['initial']['receipt']['outcome']!='VERIFIED':
                row.update(status='BLOCKED_BASELINE',reason='fresh original failed');persist();continue
            local_guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=60,fingerprinter=reader)
            rt=arena_local.ArenaLocalRuntime(local_guard,{**record,'version_info':[{tag:commit}]},
                     max_processes=1,node_budget=20000,event_budget=256)
            captures.append(rt);row['capture']=rt.capture(pin);persist()
            if not row['capture']['ok']:
                row.update(status='BLOCKED_CAPTURE',reason='native parser/goal capture unavailable');persist();continue
            proof_replay._check_capture(record['src'],row['capture']['capture'],rt.context.context_id)
            for draft in drafts:
                for order in ORDERS:
                    sample=measure(per_order[order],pin,draft['source']);sample['arm']=draft['arm']
                    row['samples'].append(sample);persist()
            row.update(status='MEASURED',reason=None);persist()
    screened=screening_status(report['rows'])
    if screened!='SCREENED_ALL_PINS':
        report['status']=screened;persist();return report
    report['winner']=drafts[1]['source'];persist()  # Frozen before fresh confirmation.
    for row in report['rows']:
        pin=VersionPin(**row['pin'])
        project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                     (record['url'],pin.lean_tag,pin.git_commit))
        binding=arena_lean.project_binding(record,pin,project,Path(project.get('elan_home',ready['elan_home'])))
        for order in ORDERS:
            guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=1,timeout=60,
                       branch_order=order,fingerprinter=reader);guards.append(guard)
            row['confirmation'].append(measure(guard,pin,report['winner']));persist()
    report['status']='CONFIRMED' if all(s['receipt']['outcome']=='VERIFIED' for r in report['rows']
                                      for s in r['confirmation']) else 'CONFIRMATION_FAILED'
    persist();return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True);p.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
