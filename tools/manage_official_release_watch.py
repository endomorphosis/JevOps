#!/usr/bin/env python3
"""Explicit render/inspect/install of two new bounded release-watch oneshots/timers.

Existing supervisor services, profile, taskboard and native sources are untouched.
An install accepts only absent or byte-identical managed units; it never replaces
an unknown/different unit. Root performs installation after source review.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import stat
import subprocess
import sys

import publish_official_release_watch as outbox

PREFIX='# Managed by JevOps tools/manage_official_release_watch.py'
WATCH='jevops-official-release-watch.service'
PUBLISH='jevops-official-release-publish.service'
TIMERS=('jevops-official-release-watch.timer','jevops-official-release-publish.timer')


def command(argv,timeout=30):
    result=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout,check=False)
    outbox.require(result.returncode in (0,1,3,4),'systemctl command failed: '+str(argv[:4]))
    return result


def render(root,*,load=outbox.load_contract,tools=outbox.load_tools):
    contract=load(root);timed=tools(root);binding=timed.publisher.idle.scope(root)
    manager=timed.publisher.manager;python=binding['supervisor']['python_executable']
    source=binding['supervisor']['accelerator_source'];state=contract['state'];settings=contract['config']['settings']
    environment=['Environment='+manager.systemd_arg('JEVOPS_REFACTOR_LLM_BUDGET_POLICY='+str(root/settings['provider_budget_policy'])),
                 'Environment='+manager.systemd_arg('PYTHONPATH='+str(root/'tools')+':'+str(source)),
                 'Environment='+manager.systemd_arg('PYTHONDONTWRITEBYTECODE=1')]
    def service(description,argv,timeout):
        return '\n'.join([PREFIX,'[Unit]','Description='+description,'','[Service]','Type=oneshot',
            'WorkingDirectory='+manager.systemd_path(root),*environment,
            'ExecStart='+' '.join(manager.systemd_arg(value,exec_start=True)for value in argv),
            'TimeoutStartSec='+str(timeout),'MemoryMax=256M','TasksMax=16','KillMode=control-group','UMask=0077',''])
    def timer(description,unit,calendar):
        return '\n'.join([PREFIX,'[Unit]','Description='+description,'','[Timer]','OnCalendar='+calendar,
                          'Persistent=true','AccuracySec=15s','Unit='+unit,'','[Install]','WantedBy=timers.target',''])
    units={WATCH:service('Observe official Lean Refactor Arena release metadata',
                        [python,'-B',str(root/'tools/official_release_watch.py'),'--repo-root',str(root),
                         '--state-dir',str(state),'--once'],70),
           PUBLISH:service('Deliver validated official release metadata outbox events',
                        [python,'-B',str(root/'tools/publish_official_release_watch.py'),'--repo-root',str(root),
                         '--state-dir',str(state),'--timeout','1800'],1900),
           TIMERS[0]:timer('Poll official release metadata every fifteen minutes UTC',WATCH,'*-*-* *:0/15:00 UTC'),
           TIMERS[1]:timer('Retry pending official release outbox every two minutes UTC',PUBLISH,'*-*-* *:0/2:00 UTC')}
    return contract,units


def snapshot_timer(name,run):
    result=run(['systemctl','--user','show',name,'--property=Id,LoadState,ActiveState,UnitFileState'],10)
    value=dict(line.split('=',1)for line in result.stdout.splitlines()if'='in line)
    outbox.require(value.get('Id')==name and value.get('LoadState')in{'loaded','not-found'}
                   and value.get('ActiveState')in{'active','inactive','failed'}
                   and value.get('UnitFileState','')in{'','enabled','disabled','static','not-found'},'Unknown timer state')
    return value


def snapshot_service(name,run):
    result=run(['systemctl','--user','show',name,'--property=Id,LoadState,ActiveState,MainPID,Job'],10)
    value=dict(line.split('=',1)for line in result.stdout.splitlines()if'='in line)
    outbox.require(value.get('Id')==name and value.get('LoadState')in{'loaded','not-found'}
        and value.get('ActiveState')in{'active','inactive','failed','activating','deactivating'}
        and value.get('MainPID','').isdigit() and type(value.get('Job'))is str
        and (value['Job']=='' or value['Job'].split()and value['Job'].split()[0].isdigit()),
        'Unknown bounded oneshot state')
    value['busy']=(int(value['MainPID'])>0 or bool(value['Job']and int(value['Job'].split()[0])>0)
                   or value['ActiveState']in{'active','activating','deactivating'})
    return value


def inspect(root,*,load=outbox.load_contract,tools=outbox.load_tools,run=command,units_dir=None):
    contract,units=render(root,load=load,tools=tools)
    directory=Path.home()/'.config/systemd/user'if units_dir is None else units_dir
    files={}
    for name,text in units.items():
        path=directory/name
        files[name]={'exists':os.path.lexists(path),'expected_sha256':outbox.digest(text.encode())}
        if path.exists():
            raw,_=outbox.owned(path,65536)
            files[name].update(sha256=outbox.digest(raw),matches=raw==text.encode())
    return dict(schema='jevops.official-release-watch-unit-inspection.v1',units=files,
                timers={name:snapshot_timer(name,run)for name in TIMERS},services_changed=False,**outbox.AUTH)


def install(root,*,load=outbox.load_contract,tools=outbox.load_tools,run=command,units_dir=None):
    contract,units=render(root,load=load,tools=tools)
    timed=tools(root)
    directory=Path.home()/'.config/systemd/user'if units_dir is None else units_dir
    directory.mkdir(parents=True,exist_ok=True)
    outbox.require(not directory.is_symlink() and directory.stat().st_uid==os.getuid(),'Owned ordinary user unit directory required')
    # Validate every existing file BEFORE the first mutation; upgrades require
    # a separate reviewed install rather than replacing a differing unit.
    for name,text in units.items():
        path=directory/name
        if os.path.lexists(path):outbox.require(outbox.owned(path,65536)[0]==text.encode(),'Existing unit differs; review required: '+name)
    previous={name:snapshot_timer(name,run)for name in TIMERS}
    service_before={name:snapshot_service(name,run)for name in(WATCH,PUBLISH)}
    created=[];started=[];pending=None;result=dict(schema='jevops.official-release-watch-installation.v1',installed=False,**outbox.AUTH)
    try:
        for name,text in units.items():
            path=directory/name
            if not path.exists():
                with timed.publisher.hold_commit():
                    outbox.new_bytes(path,text.encode(),on_commit=created.append)
        # Recheck the entire reviewed source/config closure before enabling any timer.
        latest=load(root)
        outbox.require(latest['config_ref']==contract['config_ref'] and latest['preflight_ref']==contract['preflight_ref'],'Watch configuration changed during install')
        response=run(['systemctl','--user','daemon-reload'],30);outbox.require(response.returncode==0,'daemon-reload failed')
        for name in TIMERS:
            started.append(name)  # Intent is recorded before a partial systemctl failure.
            response=run(['systemctl','--user','enable','--now',name],30)
            outbox.require(response.returncode==0,'Timer enable failed')
        result.update(installed=True,units=list(units),timers_enabled=list(TIMERS),existing_supervisor_services_changed=False)
    except BaseException as error:
        pending=error;errors=[]
        for name in reversed(started):
            try:
                path=directory/name
                outbox.require(outbox.owned(path,65536)[0]==units[name].encode(),'Timer unit changed before rollback')
                if previous[name]['ActiveState']!='active':
                    response=run(['systemctl','--user','stop',name],30);outbox.require(response.returncode==0,'Timer stop rollback failed')
                if previous[name].get('UnitFileState')!='enabled':
                    response=run(['systemctl','--user','disable',name],30);outbox.require(response.returncode==0,'Timer disable rollback failed')
            except BaseException as cleanup:
                errors.append(type(cleanup).__name__+': '+str(cleanup))
                if not outbox.control(pending) and outbox.control(cleanup):pending=cleanup
        deferred=[]
        for path,device,inode,sha in reversed(created):
            try:
                if path.name in(WATCH,PUBLISH):
                    current=snapshot_service(path.name,run)
                    if current['busy']:
                        deferred.append(path.name)
                        errors.append('Bounded oneshot still active/queued; owned unit removal deferred: '+path.name)
                        continue
                with timed.publisher.hold_commit():outbox.retire_created((path,device,inode,sha))
            except BaseException as cleanup:
                if path.name in(WATCH,PUBLISH):deferred.append(path.name)
                errors.append(type(cleanup).__name__+': '+str(cleanup))
                if not outbox.control(pending)and outbox.control(cleanup):pending=cleanup
        try:
            response=run(['systemctl','--user','daemon-reload'],30);outbox.require(response.returncode==0,'Rollback daemon-reload failed')
        except BaseException as cleanup:
            errors.append(type(cleanup).__name__+': '+str(cleanup))
            if not outbox.control(pending)and outbox.control(cleanup):pending=cleanup
        result.update(rollback_complete=not errors,rollback_errors=errors,unit_removal_deferred=deferred,services_before=service_before)
    if pending is not None:
        try:pending.installation_result=result
        except BaseException:pass
        raise pending
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--render',action='store_true');modes.add_argument('--inspect',action='store_true');modes.add_argument('--install',action='store_true')
    args=parser.parse_args(argv);root=args.repo_root.resolve(strict=True)
    outbox.require(root==outbox.ROOT,'Only the reviewed repository scope is allowed')
    previous={}
    def interrupt(_sig,_frame):raise KeyboardInterrupt('Release watch installation interrupted')
    try:
        for sig in(signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,interrupt)
        if args.render:
            _,units=render(root);result=dict(schema='jevops.official-release-watch-unit-render.v1',units=units,services_changed=False,**outbox.AUTH)
        elif args.inspect:result=inspect(root)
        else:result=install(root)
        print(json.dumps(result,sort_keys=True));return 0
    except BaseException as error:
        report=dict(error_type=type(error).__name__,error=str(error),**outbox.AUTH)
        partial=getattr(error,'installation_result',None)
        if type(partial)is dict:report['installation']=partial
        try:print(json.dumps(report,sort_keys=True),file=sys.stderr)
        except BaseException:pass
        if outbox.control(error):raise
        return 1
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


if __name__=='__main__':raise SystemExit(main())
