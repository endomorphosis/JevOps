#!/usr/bin/env python3
"""One fixed, profile-guided support-deletion pilot with whole-source checks.

A trailing wildcard ``at *`` may be dropped while the explicit support list
stays. Named locations stay. The incumbent check repeats until it verifies
or the sealed wall can no longer start another 60s call. Every draft gets one
sealed 60s call before a timeout is tried again. A draft already rejected with
candidate_errors for
this incumbent, pin, and dependency digest is kept and is not checked again.
A verified draft and a verified confirmation slot from that same sealed check
are kept. A verified profile is kept only while its binding still matches the
current runtime. A drifted profile is measured again. Those receipts remain
in the run archive when a later incumbent check times out. Timeouts stay unjudged and are tried
on a later run. Running out of the wall returns the calls already finished.
A screen or confirmation slot that still times out is not a negative trial.
Historical source is an unverified incumbent nomination. New instrumentation
only ranks exact source-bound edits. No model, training, cache clearing or
promotion.
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
    for edit in (*solver_feedback.support_edits(source,max_sites=4), *location_edits(source,max_sites=4)):
        candidate=edit.apply(source)
        if candidate in seen or arena.intake_error(candidate,record['statement']):continue
        seen.add(candidate)
        if arena.reference_tokens(candidate,record['statement'])>=arena.reference_tokens(source,record['statement']):continue
        line=source[edit.start:edit.end].strip()
        cost=max((v for hint,v in costs.items() if hint and (hint==line or hint in line)),default=0)
        drafts.append({'source':candidate,'edit':asdict(edit),'cost_prior_raw':cost})
    return sorted(drafts,key=lambda d:(-d['cost_prior_raw'],d['edit']['start'],arena.source_hash(d['source'])))[:10]

def location_edits(source, *, max_sites=4):
    """Drop only a trailing wildcard ``at *``, keeping the explicit support list.

    Named locations stay. This is not support deletion and does not invent a tactic.
    """
    from jevops.rewrite_policy import body_of, supported
    if type(max_sites) is not int or not 0<=max_sites<=32:
        raise ValueError('invalid location site limit')
    prefix, body=body_of(source)
    if not prefix or len(source.encode())>65536 or not supported(body):
        return []
    edits, offset, sites=[], 0, 0
    for line in source.splitlines(keepends=True):
        newline='\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
        text=line[:-len(newline)] if newline else line
        match=solver_feedback._ONLY.fullmatch(text) if offset>=len(prefix) else None
        if match and sites<max_sites and ' '.join(match[4].split())=='at *':
            entries=[part.strip() for part in match[3].split(',')] if match[3].strip() else []
            if len(entries)<=32 and all(re.fullmatch(solver_feedback._PREMISE, entry) for entry in entries):
                sites += 1
                replacement=match[1]+match[2]+' only ['+match[3]+']'+newline
                edits.append(solver_feedback.SolverEdit(solver_feedback.source_digest(source), offset,
                    offset+len(line), replacement, 'location-narrowing'))
        offset += len(line)
    return edits

def timeout_retry_allowed(*, native_processes, seconds_left):
    """Another sealed 60s call fits only inside the process cap and wall budget."""
    return (type(native_processes) is int and type(seconds_left) in (int, float)
            and native_processes < 23 and seconds_left > 60)

def retry_unjudged(measure, allowed):
    """Repeat one sealed call until it is judged or the budget closes.

    ``measure`` returns a sample, or None when the wall or process cap is
    already closed. A timeout is not a judgment. The last finished sample is
    kept when the next call cannot start.
    """
    if not callable(measure) or not callable(allowed):
        raise ValueError('measure and budget required')
    sample=measure()
    while (type(sample) is dict and type(sample.get('receipt')) is dict
           and sample['receipt'].get('outcome')=='TIMEOUT' and allowed()):
        again=measure()
        if again is None:
            break
        if type(again) is not dict or type(again.get('receipt')) is not dict:
            raise ValueError('retry sample required')
        sample=again
    return sample

def _matching_rejections(data, dependency_digest):
    found={}
    if type(data) is not dict:
        return found
    screens=data.get('screen') if type(data.get('screen')) is list else []
    for sample in screens:
        if type(sample) is not dict or type(sample.get('source')) is not str or sample['source'] in found:
            continue
        receipt=sample.get('receipt')
        if type(receipt) is not dict or receipt.get('outcome')!='REJECTED' or receipt.get('reason')!='candidate_errors':
            continue
        raw=receipt.get('observations_json')
        if type(raw) is not str or not raw.strip():
            continue
        try:
            obs=json.loads(raw)
        except json.JSONDecodeError:
            continue
        if type(obs) is not dict or obs.get('dependency_digest')!=dependency_digest:
            continue
        found[sample['source']]=sample
    return found

def carried_rejections(root, *, incumbent, seed_sha256, baseline_sha256, pin, dependency_digest):
    """Keep exact candidate_errors receipts from the same sealed check.

    The live result is not the only copy. A later incumbent timeout replaces
    that file, and the judged receipts stay in the producer run archive.
    Timeouts and verified receipts stay un-reusable. A document whose
    incumbent, pin, seed, baseline, or digest does not match is ignored.
    """
    if (type(incumbent) is not str or type(seed_sha256) is not str or type(baseline_sha256) is not str
            or type(pin) is not dict or type(dependency_digest) is not str or len(dependency_digest)!=64):
        return {}
    paths=[]
    result=root/c.RUNTIME/'JLR-019.result.json'
    if result.is_file() and not result.is_symlink():
        paths.append(result)
    runs=root/c.RUNTIME/'runs'
    archived=[]
    if runs.is_dir() and not runs.is_symlink():
        for path in runs.iterdir():
            if path.is_symlink() or not path.is_dir() or not path.name.startswith('JLR-019-'):
                continue
            if 'admission' in path.name:
                continue
            stdout=path/'producer'/'stdout.json'
            if stdout.is_file() and not stdout.is_symlink():
                archived.append(stdout)
        archived.sort(key=lambda item: item.stat().st_mtime)
        paths.extend(archived[-40:])
    found={}
    for path in paths:
        try:
            data=c.read(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (data.get('schema')!=SCHEMA or data.get('incumbent')!=incumbent or data.get('seed_sha256')!=seed_sha256
                or data.get('baseline_sha256')!=baseline_sha256 or data.get('pin')!=pin):
            continue
        for source, sample in _matching_rejections(data, dependency_digest).items():
            found.setdefault(source, sample)
    return found

def _sample_digest(sample):
    receipt=sample.get('receipt') if type(sample) is dict else None
    raw=receipt.get('observations_json') if type(receipt) is dict else None
    if type(raw) is not str or not raw.strip():
        return None
    try:
        obs=json.loads(raw)
    except json.JSONDecodeError:
        return None
    digest=obs.get('dependency_digest') if type(obs) is dict else None
    return digest if type(digest) is str and len(digest)==64 else None

def _sealed_report_paths(root):
    """Archived producer stdout, oldest first, with the live result last."""
    paths=[]
    runs=root/c.RUNTIME/'runs'
    archived=[]
    if runs.is_dir() and not runs.is_symlink():
        for path in runs.iterdir():
            if path.is_symlink() or not path.is_dir() or not path.name.startswith('JLR-019-'):
                continue
            if 'admission' in path.name:
                continue
            stdout=path/'producer'/'stdout.json'
            if stdout.is_file() and not stdout.is_symlink():
                archived.append(stdout)
        archived.sort(key=lambda item: item.stat().st_mtime)
        paths.extend(archived[-40:])
    result=root/c.RUNTIME/'JLR-019.result.json'
    if result.is_file() and not result.is_symlink():
        paths.append(result)
    return paths

def carried_verified_work(root, *, incumbent, seed_sha256, baseline_sha256, pin, dependency_digest):
    """Keep verified profile, draft, and confirmation receipts for this check.

    A later run still rechecks the incumbent. It returns a verified profile, a
    verified draft, and a verified confirmation slot whose dependency digest
    matches that fresh incumbent. The caller keeps the profile only when its
    binding still matches the current runtime. Timeouts and rejections are
    ignored. The live result wins over an older archive.
    """
    empty={'screens':{},'confirmations':{},'profile':None}
    if (type(incumbent) is not str or type(seed_sha256) is not str or type(baseline_sha256) is not str
            or type(pin) is not dict or type(dependency_digest) is not str or len(dependency_digest)!=64):
        return empty
    screens={};confirmations={};profile=None
    for path in _sealed_report_paths(root):
        try:
            data=c.read(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (data.get('schema')!=SCHEMA or data.get('incumbent')!=incumbent or data.get('seed_sha256')!=seed_sha256
                or data.get('baseline_sha256')!=baseline_sha256 or data.get('pin')!=pin):
            continue
        if _sample_digest(data.get('initial'))!=dependency_digest:
            continue
        remembered=data.get('profile')
        if (type(remembered) is dict and remembered.get('ok') is True and remembered.get('attempted_processes')==1
                and type(remembered.get('profile')) is dict):
            profile=json.loads(json.dumps(remembered))
        for sample in data.get('screen') if type(data.get('screen')) is list else []:
            if type(sample) is not dict or type(sample.get('source')) is not str:
                continue
            if sample.get('carried_rejection') is True or _sample_digest(sample)!=dependency_digest:
                continue
            receipt=sample.get('receipt')
            if type(receipt) is not dict or receipt.get('outcome')!='VERIFIED':
                continue
            screens[sample['source']]=json.loads(json.dumps(sample))
        for sample in data.get('confirmation') if type(data.get('confirmation')) is list else []:
            if type(sample) is not dict or type(sample.get('source')) is not str or _sample_digest(sample)!=dependency_digest:
                continue
            receipt=sample.get('receipt')
            if type(receipt) is not dict or receipt.get('outcome')!='VERIFIED':
                continue
            repetition=sample.get('repetition');slot=sample.get('slot');order=sample.get('branch_order')
            if type(repetition) is not int or type(slot) is not int or type(order) is not str:
                continue
            confirmations[(sample['source'],repetition,slot,order)]=json.loads(json.dumps(sample))
    return {'screens':screens,'confirmations':confirmations,'profile':profile}

def profile_verifier(binding, pin, reader):
    """Build the guard whose identity a profile measurement carries.

    Proof checks keep the sealed 60s cap. The profile measurement uses
    ``PROFILE_TIMEOUT``. That timeout is part of the verifier options, so an
    acceptance check that rebuilds the guard at 60s reports a false
    ``profile source/pin drift``.
    """
    return arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=PROFILE_TIMEOUT,fingerprinter=reader)

def profile_expected_binding(runtime, source, pin):
    """Rebuild the profile binding the acceptance check requires now."""
    return {'source_sha256':arena.source_hash(source),'context_id':runtime.context.context_id,
        'origin':{**runtime._origin(pin),'projection':'builtin-tactic-traces/v1'},'threshold_raw':100,
        'measurement':arena_local.PROFILE_METHOD,'node_budget':20000,'event_budget':256}

def profile_still_bound(profile, expected):
    """A carried profile is reusable only while it still binds this runtime.

    The Lean dependency digest can stay the same after the arena context
    changes. Reusing that profile fails acceptance as profile source/pin drift.
    """
    if type(profile) is not dict or type(expected) is not dict:
        return False
    binding=profile.get('binding');environment=profile.get('environment')
    if type(binding) is not dict or type(environment) is not str:
        return False
    return binding==expected and environment==arena.content_hash(expected)

def fresh_screen_count(screen):
    """Count screen slots that still need their own native call.

    A carried rejection is a previously judged candidate_errors receipt.
    A carried verification is a previously verified receipt for this digest.
    """
    if type(screen) is not list:
        raise ValueError('screen required')
    fresh=0
    for sample in screen:
        if type(sample) is not dict or type(sample.get('receipt')) is not dict:
            raise ValueError('screen receipt required')
        rejected=sample.get('carried_rejection', False)
        verified=sample.get('carried_verification', False)
        if verified is True and rejected is True:
            raise ValueError('carried sample has both flags')
        if verified is True:
            if sample['receipt'].get('outcome')!='VERIFIED':
                raise ValueError('carried sample is not verified')
            continue
        if verified is not False:
            raise ValueError('carried verification flag required')
        if rejected is True:
            if sample['receipt'].get('outcome')!='REJECTED' or sample['receipt'].get('reason')!='candidate_errors':
                raise ValueError('carried sample is not a judged rejection')
            continue
        if rejected is not False:
            raise ValueError('carried rejection flag required')
        fresh+=1
    return fresh

def fill_timeout_retries(screen, measure, allowed, on_update=None):
    """Retry timed-out slots until a pass makes no sealed call.

    ``allowed`` closes the sealed process and wall budget. ``measure`` returns
    None when that budget is already closed. Judged slots are not retried.
    """
    if type(screen) is not list:
        raise ValueError('screen required')
    while True:
        called=False
        for index in range(len(screen)):
            sample=screen[index]
            receipt=sample.get('receipt') if type(sample) is dict else None
            if type(receipt) is not dict or receipt.get('outcome')!='TIMEOUT':
                continue
            if not allowed():
                return screen
            again=measure(sample.get('source'))
            if again is None:
                return screen
            if type(again) is not dict or type(again.get('receipt')) is not dict:
                raise ValueError('retry sample required')
            screen[index]=again
            called=True
            if on_update is not None:
                on_update()
        if not called:
            return screen

def screen_disposition(samples):
    """Return the terminal status when no screened draft verified.

    ``TIMEOUT`` means the sealed call did not finish. That is not a negative
    trial and must not be settled as ``NO_SHORTER_WINNER``.
    """
    if type(samples) is not list:
        raise ValueError('screen required')
    outcomes=[]
    for sample in samples:
        receipt=sample.get('receipt') if type(sample) is dict else None
        if type(receipt) is not dict:
            raise ValueError('screen receipt required')
        outcomes.append(receipt.get('outcome'))
    if 'VERIFIED' in outcomes:
        return None
    if 'TIMEOUT' in outcomes:
        return 'SCREEN_TIMEOUT'
    return 'NO_SHORTER_WINNER'

def screen_status(draft_count, samples):
    """Return the terminal status for a whole draft list.

    A shorter list was not judged. That includes stopping because the sealed
    wall or process cap is closed. ``None`` means every draft was screened and
    a verified draft is ready to confirm.
    """
    if type(draft_count) is not int or draft_count < 0:
        raise ValueError('draft count required')
    disposition=screen_disposition(samples)
    if len(samples) != draft_count:
        return 'SCREEN_TIMEOUT'
    return disposition

def confirmation_status(samples):
    """Return the terminal status of a twelve-slot confirmation schedule.

    A missing slot or a ``TIMEOUT`` is unjudged. A judged rejection is a
    semantic failure. ``None`` means every slot verified.
    """
    if type(samples) is not list:
        raise ValueError('confirmation required')
    if len(samples)!=12:
        return 'SCREEN_TIMEOUT'
    outcomes=[]
    for sample in samples:
        receipt=sample.get('receipt') if type(sample) is dict else None
        if type(receipt) is not dict:
            raise ValueError('confirmation receipt required')
        outcomes.append(receipt.get('outcome'))
    if 'TIMEOUT' in outcomes:
        return 'SCREEN_TIMEOUT'
    if any(outcome!='VERIFIED' for outcome in outcomes):
        return 'CONFIRMATION_FAILED'
    return None

def confirmation_process_bound(screen, confirmation, *, profile_carried):
    """Native calls a confirming run must still perform.

    The incumbent is always rechecked. A carried profile, carried rejection,
    carried verified draft, or carried verified confirmation was already judged
    for this digest and is not counted again. Retries may exceed the bound.
    """
    if type(profile_carried) is not bool:
        raise ValueError('profile carry flag required')
    if type(confirmation) is not list or len(confirmation)!=12:
        raise ValueError('confirmation schedule required')
    carried=0
    for sample in confirmation:
        if type(sample) is not dict or type(sample.get('receipt')) is not dict:
            raise ValueError('confirmation receipt required')
        flag=sample.get('carried_verification', False)
        if flag is True:
            if sample['receipt'].get('outcome')!='VERIFIED':
                raise ValueError('carried confirmation is not verified')
            carried+=1
        elif flag is not False:
            raise ValueError('carried verification flag required')
    return (0 if profile_carried else 1)+1+fresh_screen_count(screen)+(12-carried)

def _screen_timed_out(data):
    screens=data.get('screen') if type(data) is dict else None
    return type(screens) is list and any(type(sample) is dict and type(sample.get('receipt')) is dict
        and sample['receipt'].get('outcome')=='TIMEOUT' for sample in screens)

def retain_negative_trial(root=ROOT):
    result_path=root/c.RUNTIME/'JLR-019.result.json'
    if not result_path.is_file() or result_path.is_symlink():
        return None
    data=c.read(result_path)
    if data.get('schema')!=SCHEMA or data.get('status')!='NO_SHORTER_WINNER' or _screen_timed_out(data):
        return None
    digest=c.sha(result_path)
    dest=root/c.RUNTIME/'retained'/'JLR-019'/digest
    for name in ('JLR-019.result.json','JLR-019.partial.json','JLR-019.receipt.json'):
        src=root/c.RUNTIME/name
        c.require(src.is_file() and not src.is_symlink(), 'negative trial file missing: '+name)
        payload=src.read_text()
        target=dest/name
        if target.exists():
            c.require(not target.is_symlink() and target.read_text()==payload,
                      'retained negative trial differs: '+name)
        else:
            c.atomic(target, payload)
    receipt=c.read(dest/'JLR-019.receipt.json')
    return {'schema':'jevops.lean-refactor.retained-negative-trial.v1',
            'path':str(dest.relative_to(root)),'result_sha256':digest,
            'partial_sha256':c.sha(dest/'JLR-019.partial.json'),
            'receipt_sha256':c.sha(dest/'JLR-019.receipt.json'),
            'stage_run_exit_code':receipt.get('exit_code'),'status':'NO_SHORTER_WINNER'}

def produce(root=ROOT):
    started=time.monotonic();resources=resource_snapshot(root)
    c.require(resources['eligible'] and not c.held(root),'CPU resource or operator gate')
    retained=retain_negative_trial(root)
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
    if retained is not None:
        report['retained_negative_trial']=retained
    runtime=None
    def persist():
        report['native_processes']=sum(g.processes for g in guards.values())+(runtime.attempts if runtime else 0)
        report['wall_seconds']=time.monotonic()-started
        c.save(root/c.RUNTIME/'JLR-019.partial.json',report)
    def measure(source,order):
        c.require(not c.held(root) and resource_snapshot(root)['eligible'],'CPU resource or operator gate')
        # A closed wall or process cap keeps the calls already stored. Raising
        # here used to discard that partial, including drafts that were judged.
        if time.monotonic()-started>=780 or report['native_processes']>=24:
            return None
        guard=guards[order];context=guard.context(record)
        receipt=guard(arena.VerificationRequest(context,source,pin))
        sample={'source':source,'branch_order':order,'context':asdict(context),'receipt':asdict(receipt)}
        report['native_processes']=sum(g.processes for g in guards.values())+(runtime.attempts if runtime else 0)
        return sample
    def seconds_left():
        return 780-(time.monotonic()-started)
    def incumbent_budget():
        return timeout_retry_allowed(native_processes=report['native_processes'], seconds_left=seconds_left())
    initial=retry_unjudged(lambda: measure(incumbent,'reference-first'), incumbent_budget)
    if initial is None:
        report['status']='BLOCKED_INCUMBENT';persist();return report
    report['initial']=initial;persist()
    if report['initial']['receipt']['outcome']!='VERIFIED':
        report['status']='BLOCKED_INCUMBENT';persist();return report
    digest=_sample_digest(report['initial']) or ''
    identity=dict(incumbent=incumbent,seed_sha256=report['seed_sha256'],baseline_sha256=report['baseline_sha256'],
        pin=report['pin'],dependency_digest=digest)
    remembered=carried_verified_work(root,**identity) if digest else {'screens':{},'confirmations':{},'profile':None}
    carried_profile=remembered['profile']
    bound=False
    if carried_profile is not None:
        probe=arena_local.ArenaLocalRuntime(profile_verifier(binding, pin, reader),record,max_processes=0,
            node_budget=20000,event_budget=256)
        bound=profile_still_bound(carried_profile, profile_expected_binding(probe, incumbent, pin))
    if bound:
        report['profile']=carried_profile;report['profile_carried']=True;persist()
    else:
        guard=profile_verifier(binding, pin, reader)
        runtime=arena_local.ArenaLocalRuntime(guard,record,max_processes=1,node_budget=20000,event_budget=256)
        report['profile']=runtime.profile(pin,source=incumbent,threshold_raw=100)
        report['profile_carried']=False;persist()
    if not report['profile']['ok']:
        report['status']='BLOCKED_NATIVE_PROFILE';persist();return report
    report['drafts']=proposals(record,incumbent,report['profile']['profile']);persist()
    carried=carried_rejections(root,**identity) if digest else {}
    for draft in report['drafts']:
        prior=carried.get(draft['source'])
        if type(prior) is dict and prior.get('source')==draft['source']:
            kept=dict(prior);kept['carried_rejection']=True
            report['screen'].append(kept);persist();continue
        verified=remembered['screens'].get(draft['source'])
        if type(verified) is dict and verified.get('source')==draft['source']:
            kept=dict(verified);kept['carried_verification']=True;kept['carried_rejection']=False
            report['screen'].append(kept);persist();continue
        sample=measure(draft['source'],'reference-first')
        if sample is None:
            break
        report['screen'].append(sample);persist()
    # Further sealed calls wait until every draft has been kept or tried once.
    def allowed():
        return timeout_retry_allowed(native_processes=report['native_processes'], seconds_left=seconds_left())
    fill_timeout_retries(report['screen'],lambda source: measure(source,'reference-first'),allowed,persist)
    status=screen_status(len(report['drafts']), report['screen'])
    if status is not None:
        report['status']=status;persist();return report
    valid=[s for s in report['screen'] if s['receipt']['outcome']=='VERIFIED']
    winner=min(valid,key=lambda s:(arena.reference_tokens(s['source'],record['statement']),arena.source_hash(s['source'])))
    report['winner']=winner['source'];persist()  # Frozen before confirmation.
    for repeat in range(3):
        for slot,order in enumerate(ORDER_BLOCK):
            prior=remembered['confirmations'].get((report['winner'],repeat,slot,order))
            if type(prior) is dict and prior.get('source')==report['winner'] and prior.get('branch_order')==order:
                kept=dict(prior);kept['repetition']=repeat;kept['slot']=slot;kept['carried_verification']=True
                report['confirmation'].append(kept);persist();continue
            sample=measure(report['winner'],order)
            if sample is None:
                report['status']='SCREEN_TIMEOUT';persist();return report
            sample.update(repetition=repeat,slot=slot,carried_verification=False)
            report['confirmation'].append(sample);persist()
    for index,sample in enumerate(report['confirmation']):
        receipt=sample.get('receipt') if type(sample) is dict else None
        if type(receipt) is not dict or receipt.get('outcome')!='TIMEOUT' or not allowed():
            continue
        again=measure(report['winner'],sample.get('branch_order'))
        if again is None:
            break
        again.update(repetition=sample['repetition'],slot=sample['slot'],carried_verification=False)
        report['confirmation'][index]=again;persist()
    status=confirmation_status(report['confirmation'])
    report['status']='CONFIRMED' if status is None else status
    persist();return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True);p.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
