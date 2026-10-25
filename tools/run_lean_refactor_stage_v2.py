#!/usr/bin/env python3
"""Execute only frozen, bounded research producers; never complete a board task."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

def local_user_bus(*, runtime_parent=Path('/run/user'), parent_environment=None):
    """Permit only this UID's private local user-manager socket, never remote env."""
    parent_environment=os.environ if parent_environment is None else parent_environment
    runtime=runtime_parent/str(os.getuid());address='unix:path='+str(runtime/'bus')
    c.require(runtime_parent.resolve()==runtime_parent and not runtime.is_symlink(),
              'user runtime parent/path must be canonical')
    info=runtime.lstat();bus=(runtime/'bus').lstat()
    c.require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid()
              and stat.S_IMODE(info.st_mode)==0o700 and stat.S_ISSOCK(bus.st_mode)
              and bus.st_uid==os.getuid(), 'owned private local user bus unavailable')
    c.require(parent_environment.get('XDG_RUNTIME_DIR',str(runtime))==str(runtime)
              and parent_environment.get('DBUS_SESSION_BUS_ADDRESS',address)==address,
              'refuse noncanonical or remote user-bus environment')
    return {'XDG_RUNTIME_DIR':str(runtime),'DBUS_SESSION_BUS_ADDRESS':address}

def process(root, base, argv, directory, timeout):
    directory.mkdir(parents=True,exist_ok=False)
    command=[base['python_executable'],*argv]
    environment={'PATH':str(Path(base['python_executable']).parent)+':/usr/bin:/bin',
      'HOME':str(Path.home()),'PYTHONPATH':base['accelerator_source']+os.pathsep+str(root),
      'PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','IPFS_TEST_PROOF_REUSE_MODE':'off'}
    if argv and (argv[0]=='tools/lean_refactor_iterative_pilot.py' or
                 argv[0]=='tools/lean_refactor_runtime_qualification.py' and '--qualify' in argv):
        environment.update(local_user_bus())
    start=time.monotonic();timed_out=False
    with (directory/'stdout.json').open('xb') as out,(directory/'stderr.log').open('xb') as err:
        child=subprocess.Popen(command,cwd=root,env=environment,stdin=subprocess.DEVNULL,stdout=out,stderr=err)
        fd=os.pidfd_open(child.pid)
        try:
            try: code=child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;signal.pidfd_send_signal(fd,signal.SIGTERM)
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    signal.pidfd_send_signal(fd,signal.SIGKILL);child.wait(timeout=5)
                code=124
        finally:os.close(fd)
    return {'argv':command,'exit_code':code,'timed_out':timed_out,'duration_seconds':time.monotonic()-start,
      'stdout':str((directory/'stdout.json').relative_to(root)),
      'stdout_sha256':c.sha(directory/'stdout.json'),
      'stderr':str((directory/'stderr.log').relative_to(root)),'stderr_sha256':c.sha(directory/'stderr.log')}

def resource_probe(root, base, directory):
    execution=process(root,base,['tools/lean_refactor_runtime_qualification.py','--probe-resources'],directory,30)
    c.require(execution['exit_code']==0,'cheap resource probe failed; inspect preserved stderr')
    probe=c.read(root/'data/lean_refactor_runtime_20261024/resource-probe.json')
    c.require(probe['schema']=='jevops.lean-refactor.resource-probe.v1','resource probe schema')
    summary={'schema':'jevops.lean-refactor.resource-gate.v2',
      'blockers':probe['loading_resource_blockers'],'gpu_owners':probe['gpu_processes'],
      'eligible':probe['eligible_for_guarded_preload'],'proof_authority':False}
    # Only changed guards/ownership alter retry evidence; clocks and byte noise do not.
    c.save(root/c.RUNTIME/'resource-gate.json',summary)
    return probe,execution

def project_probe(root):
    """Cheap concurrent-owner gate; never scans imports or changes preparation."""
    pilot=root/'data/lean_refactor_campaign_20261024/project-pilot'
    busy=False
    if pilot.is_dir():
        with (pilot/'project-readiness.lock').open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:busy=True
    frozen=root/'data/lean_refactor_campaign_20261024/JLR-016.result.json'
    gate={'schema':'jevops.lean-refactor.project-gate.v2','concurrent_preparation':busy,
          'frozen_artifact_sha256':c.sha(frozen) if frozen.is_file() else None,
          'proof_authority':False}
    c.save(root/c.RUNTIME/'project-gate.json',gate)
    return gate

def waiting(root, tid, reason, details=None):
    output={'schema':'jevops.lean-refactor.stage-wait.v2','task_id':tid,'status':'waiting',
      'reason':reason,'retry_condition':details,'observed_at':time.time(),'retry_after_seconds':120,**c.AUTH}
    c.save(root/c.RUNTIME/(tid+'.result.json'),output)
    return output

def qualification_identity(path):
    if not path.exists():return None
    info=path.lstat()
    c.require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
              and info.st_nlink==1,'qualification must be an owned ordinary file')
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,c.sha(path))

def iterative_admission(root,tid):
    """Refuse a consumed phase before expensive prerequisite/custody checks.

    Refusals have their own archive and never replace actual scientific runs.
    """
    if tid!='JLR-024':return None
    import lean_refactor_iterative_pilot as pilot
    path=root/pilot.LEDGER
    if not path.exists():return None
    ledger=pilot.budget(root)
    if not ledger['attempts']:return None
    gate={'schema':'jevops.lean-refactor.phase-admission.v1','task_id':tid,
          'reason':'phase_already_attempted','ledger_sha256':c.sha(path),
          'reserved_attempts':len(ledger['attempts']),'max_calls':pilot.LIMITS['max_calls'],
          'retry_condition':'explicit separately reviewed bounded phase retaining all prior usage',**c.AUTH}
    c.save(root/c.RUNTIME/'iterative-admission-gate.json',gate)
    directory=root/c.RUNTIME/'runs'/('JLR-024-admission-'+uuid.uuid4().hex)
    receipt={**gate,'exit_code':75,'observed_at':time.time(),
             'scientific_run_receipt_preserved':True,
             'archive_path':str((directory/'receipt.json').relative_to(root))}
    c.save(directory/'receipt.json',receipt)
    return receipt

def publish_runtime_result(root, output_path, execution, before, started_at):
    """Only the actual child's freshly published receipt may become stage output."""
    qualification_path=root/'data/lean_refactor_runtime_20261024/qualification.json'
    try:
        c.require(execution['exit_code'] in (0,75),'runtime qualifier failed before an accepted receipt')
        after=qualification_identity(qualification_path)
        c.require(after is not None and after!=before,'runtime qualifier did not publish a new receipt')
        envelope=c.read(root/execution['stdout'])
        qualification=c.read(qualification_path)
        c.require(envelope.get('receipt')==str(qualification_path)
          and envelope.get('sha256')==c.sha(qualification_path)
          and envelope.get('exit_code')==execution['exit_code'], 'actual child receipt envelope differs')
        c.require(qualification.get('schema')=='jevops.lean-refactor.runtime-qualification.v1'
          and type(qualification.get('observed_at')) in (int,float)
          and started_at<=qualification['observed_at']<=time.time()+1
          and qualification.get('source_sha256',{}).get('tools/lean_refactor_runtime_qualification.py')
              ==c.sha(root/'tools/lean_refactor_runtime_qualification.py'), 'runtime qualification is stale or unbound')
        c.require(qualification_identity(qualification_path)==after,'qualification changed during publication')
        c.save(output_path,qualification)
        return execution['exit_code'],None
    except (OSError,ValueError,KeyError,TypeError) as exc:
        error=str(exc)
        c.save(output_path,{'schema':'jevops.lean-refactor.stage-failure.v2','task_id':'JLR-023',
          'status':'failed','reason':error,'qualifier_exit_code':execution['exit_code'],
          'stderr':execution['stderr'],'stderr_sha256':execution['stderr_sha256'],
          'stale_qualification_reused':False,'observed_at':time.time(),**c.AUTH})
        return execution['exit_code'] if execution['exit_code'] not in (0,75) else 1,error

def run(root, tid):
    loaded=c.load(root);profile,base,tasks,board=loaded
    c.require(not c.held(root),'operator hold')
    c.require(tid in profile['contracts'],'unimplemented experiment remains planned')
    c.require(board[tid]['status'] in ('pending','ready','in_progress'),'stage is not executable')
    c.require(all(board[d]['status']=='completed' for d in tasks[tid]['depends_on']),'dependency not complete')
    refused=iterative_admission(root,tid)
    if refused is not None:return refused
    # Native completion alone is insufficient for a research prerequisite.
    for dep in tasks[tid]['depends_on']:
        if dep in profile['contracts']:
            c.module(root,'check_lean_refactor_stage_v2.py').validate(root,dep)
    binding=c.binding(root,tid,loaded)
    directory=root/c.RUNTIME/'runs'/(tid+'-'+uuid.uuid4().hex)
    directory.mkdir(parents=True)
    start=time.monotonic();stamp=time.time();executions=[];code=1;reason=None
    output_path=root/c.RUNTIME/(tid+'.result.json')
    contract=profile['contracts'][tid]
    with (root/c.RUNTIME/(tid+'.lock')).open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if tid=='JLR-023':
                probe,execution=resource_probe(root,base,directory/'resource-probe');executions.append(execution)
                if not probe['eligible_for_guarded_preload']:
                    waiting(root,tid,'external_gpu_or_host_resource',probe['loading_resource_blockers']);code=75
                else:
                    before=qualification_identity(root/'data/lean_refactor_runtime_20261024/qualification.json')
                    qualification_started=time.time()
                    execution=process(root,base,contract['argv'],directory/'producer',contract['timeout'])
                    executions.append(execution);code=execution['exit_code']
                    code,reason=publish_runtime_result(root,output_path,execution,before,qualification_started)
            elif tid=='JLR-016':
                gate=project_probe(root)
                if gate['concurrent_preparation']:
                    waiting(root,tid,'concurrent_owned_project_preparation','project-readiness.lock release');code=75
                else:code=0
                if code==0:
                    execution=process(root,base,contract['argv'],directory/'producer',contract['timeout'])
                    executions.append(execution);code=execution['exit_code']
            else:
                execution=process(root,base,contract['argv'],directory/'producer',contract['timeout'])
                executions.append(execution);code=execution['exit_code']
                if code==0:
                    # Preserve the actual native stdout as the result, including every failure/unavailable row.
                    data=c.stage_result(root/execution['stdout'],tid);c.save(output_path,data)
            c.require(c.binding(root,tid)==binding,'inputs or source changed during production')
        except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as exc:
            reason=str(exc);code=code or 1
        outputs={p:c.sha(root/p) for p in contract['outputs'] if (root/p).is_file()}
        receipt={'schema':'jevops.lean-refactor.stage-run.v2','task_id':tid,'binding':binding,
          'started_at':stamp,'finished_at':time.time(),'duration_seconds':time.monotonic()-start,
          'executions':executions,'exit_code':code,'error':reason,'outputs':outputs,
          'archive_path':str((directory/'receipt.json').relative_to(root)),
          'uid':os.getuid(),'actor_pid':os.getpid(),**c.AUTH}
        c.save(directory/'receipt.json',receipt)
        c.save(root/c.RUNTIME/(tid+'.receipt.json'),receipt)
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task-id',required=True);args=p.parse_args()
    try:
        result=run(c.ROOT,args.task_id)
        print(json.dumps({'task_id':args.task_id,'exit_code':result['exit_code'],'receipt':result['archive_path'],**c.AUTH}))
        return result['exit_code']
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        print(json.dumps({'error':str(exc),**c.AUTH}),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
