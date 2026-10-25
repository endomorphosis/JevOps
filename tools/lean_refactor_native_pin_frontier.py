#!/usr/bin/env python3
"""Supplement missing native pins in a private capped volume, retaining old runs.

This is a preparation substep of JLR-020, never a replacement bootstrap run.
Only frozen corpus commits/toolchains are admitted. No model or service starts.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c

SCHEMA='jevops.lean-refactor.native-pin-frontier.v1'
TARGET='Core.InitsUpdatesComm'
PILOT=c.RUNTIME+'/native-pins-v1'
INDEX=c.RUNTIME+'/native-pin-frontier.json'
MAX_SECONDS=360

def plan(root, record):
    prior=c.read(root/c.RUNTIME/'JLR-017.result.json')
    return [(tag,commit) for version in record['version_info'] for tag,commit in version.items()
            if not any(r['name']==record['name'] and r['lean_tag']==tag and r['git_commit']==commit
                       and r['status']=='VERIFIED' for r in prior['rows'])]

def command(argv,cwd,volume,*,timeout=60,label='command'):
    """Durable sanitized subprocess evidence; timeout signals its owned pidfd."""
    c.require(0<timeout<=360,'bounded frontier command required')
    logs=volume/'logs';logs.mkdir(exist_ok=True)
    # Path.with_suffix treats decimal version components as suffixes. Keep
    # the unique component intact across repeated exact-pin attempts.
    prefix=logs/(label.replace('.','_')+'-'+uuid.uuid4().hex)
    for name in ('home','tmp','cache'):(volume/name).mkdir(exist_ok=True)
    env={'PATH':'/usr/bin:/bin','HOME':str(volume/'home'),'TMPDIR':str(volume/'tmp'),
         'XDG_CACHE_HOME':str(volume/'cache'),'GIT_CONFIG_NOSYSTEM':'1',
         'GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0',
         'GIT_LFS_SKIP_SMUDGE':'1','LEAN_NUM_THREADS':'1','MATHLIB_NO_CACHE_ON_UPDATE':'1'}
    started=time.monotonic();timed_out=False
    with prefix.with_suffix('.stdout').open('xb') as out,prefix.with_suffix('.stderr').open('xb') as err:
        child=subprocess.Popen(list(map(str,argv)),cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err)
        fd=os.pidfd_open(child.pid)
        try:
            try:code=child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;signal.pidfd_send_signal(fd,signal.SIGTERM)
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    signal.pidfd_send_signal(fd,signal.SIGKILL);child.wait(timeout=3)
                code=124
        finally:os.close(fd)
    observation={'argv':list(map(str,argv)),'cwd':str(cwd),'exit_code':code,'timed_out':timed_out,
        'duration_seconds':time.monotonic()-started,
        **{key:str(prefix.with_suffix('.'+key)) for key in ('stdout','stderr')},**c.AUTH}
    for key in ('stdout','stderr'):observation[key+'_sha256']=c.sha(Path(observation[key]))
    c.save(prefix.with_suffix('.json'),observation)
    c.require(code==0,label+' failed; retained observation: '+str(prefix.with_suffix('.json')))
    return prefix.with_suffix('.stdout').read_text(errors='replace').strip()

def validate(root,reference):
    from validate_lean_refactor_native_pin_frontier import validate as protected
    return protected(root,reference)


def effective_inputs(root,reference=None):
    """Overlay independently verified supplemental pins in memory only."""
    prior=c.read(root/c.RUNTIME/'JLR-017.result.json');ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    if reference is None:return prior,ready
    report,supplement=validate(root,reference)
    for row in report['rows']:
        if not row['sample'] or row['sample']['receipt']['outcome']!='VERIFIED':continue
        tag,commit=row['pin']['lean_tag'],row['pin']['git_commit']
        for original in prior['rows']:
            if (original['name'],original['lean_tag'],original['git_commit'])==(TARGET,tag,commit):
                original['status']='VERIFIED'
        project={**row['project'],'elan_home':supplement['elan_home']}
        prior['projects']=[p for p in prior['projects'] if
                           (p['repository'],p['lean_tag'],p['git_commit'])!=
                           (project['repository'],tag,commit)]+[project]
    return prior,ready

def produce(root=ROOT):
    from jevops import arena,arena_lean
    from jevops.lean import VersionPin
    from lean_refactor_metric_audit import resource_snapshot
    started=time.monotonic();deadline=started+MAX_SECONDS
    source_names=('tools/lean_refactor_native_pin_frontier.py','tools/lean_refactor_project_readiness.py',
                  'tools/validate_lean_refactor_native_pin_frontier.py','jevops/arena_lean.py')
    source_binding={name:c.sha(root/name) for name in source_names}
    c.require(not c.held(root) and resource_snapshot(root)['eligible'],'frontier resource/operator gate')
    if (root/INDEX).exists():
        old=c.read(root/INDEX)
        try:
            prior,_=validate(root,old)
            if (all(r['sample'] and r['sample']['receipt']['outcome']=='VERIFIED' for r in prior['rows'])
                    or time.time()-prior['observed_at']<900):return old
        except (OSError,ValueError,KeyError,RuntimeError):pass
    m=c.module(root,'lean_refactor_project_readiness.py');m.command=command
    record=next(r for r in m.records() if r['name']==TARGET);requested=plan(root,record)
    c.require(len(requested)<=2,'new missing-pin frontier requires a new bounded review')
    pilot=(root/PILOT).resolve();pilot.mkdir(parents=True,exist_ok=True)
    with (pilot/'frontier.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        _,volume=m.bootstrap_volume(pilot,m.MAX_BYTES)
        elan_home=volume/'home/.elan'
        directory=pilot/'runs'/uuid.uuid4().hex;directory.mkdir(parents=True)
        errors=[]
        for tag,commit in requested:
            if deadline-time.monotonic()<120:errors.append({'pin':tag,'reason':'bounded preparation deadline'});break
            c.require(not c.held(root) and resource_snapshot(root)['eligible'],'frontier admission gate')
            try:
                try:arena_lean.pinned_lean(elan_home,tag)
                except ValueError:
                    command([Path.home()/'.elan/bin/elan','toolchain','install','leanprover/lean4:'+tag],
                            volume,volume,timeout=min(180,deadline-time.monotonic()-55),label='elan-'+tag)
                args=SimpleNamespace(pilot_root=pilot,output=directory/(tag+'.readiness.json'),elan_home=elan_home,
                    source=record['source'],tag=tag,problem=TARGET,provision=True,build_imports=True,
                    timeout_seconds=max(1,min(100,int(deadline-time.monotonic()-55))),max_bytes=m.MAX_BYTES)
                result=m.produce(args)
                if result['provision_error']:errors.append({'pin':tag,'reason':result['provision_error']})
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
                errors.append({'pin':tag,'reason':str(exc)})
        readiness=directory/'readiness.json'
        ready=m.produce(SimpleNamespace(pilot_root=pilot,output=readiness,elan_home=elan_home,
            source=record['source'],tag=requested[0][0] if requested else 'v4.26.0',problem=TARGET,
            provision=False,build_imports=False,timeout_seconds=1,max_bytes=m.MAX_BYTES))
        report={'schema':SCHEMA,'target':TARGET,'requested_pins':[list(p) for p in requested],
            'observed_at':time.time(),'retry_after_seconds':900,
            'source_sha256':source_binding,
            'record_sha256':arena.content_hash(record),'baseline_sha256':c.sha(root/c.RUNTIME/'JLR-017.result.json'),
            'producer_sha256':c.sha(root/'tools/lean_refactor_native_pin_frontier.py'),
            'readiness_path':str(readiness.relative_to(root)),'readiness_sha256':c.sha(readiness),
            'rows':[],'errors':errors,'model_calls':0,'training_executed':False,'max_native_processes':2,**c.AUTH}
        for tag,commit in requested:
            row=next(r for r in ready['rows'] if r['name']==TARGET and (r['lean_tag'],r['git_commit'])==(tag,commit))
            output={'pin':{'lean_tag':tag,'git_commit':commit},'sample':None,'project':row['project'],
                    'reason':row['capability_gaps']}
            report['rows'].append(output)
            if row['status']!='READY':continue
            if deadline-time.monotonic()<46:
                output['reason']=['native baseline admission deadline'];continue
            pin=VersionPin(tag,commit);binding=arena_lean.project_binding(record,pin,row['project'],elan_home)
            guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=1,timeout=45)
            context=guard.context({**record,'version_info':[{tag:commit}]})
            receipt=guard(arena.VerificationRequest(context,record['src'],pin))
            output.update(sample={'source':record['src'],'branch_order':'reference-first',
                                  'context':asdict(context),'receipt':asdict(receipt)},reason=None)
        report['commands']=[c.read(p) for p in sorted((volume/'logs').glob('*.json'))]
        report['wall_seconds']=time.monotonic()-started
        c.require(source_binding=={name:c.sha(root/name) for name in source_names},
                  'frontier source changed during preparation; logs retained without acceptance')
        path=directory/'frontier.json';c.save(path,report)
        reference={'path':str(path.relative_to(root)),'sha256':c.sha(path)}
        validate(root,reference);c.save(root/INDEX,reference)
        return reference

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True);p.parse_args()
    print(json.dumps(produce(),sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
