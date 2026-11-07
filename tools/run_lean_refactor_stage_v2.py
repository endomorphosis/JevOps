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
    policy_key='JEVOPS_REFACTOR_LLM_BUDGET_POLICY'
    if policy_key in os.environ:
        environment[policy_key]=os.environ[policy_key]
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

def release_admission(root, tid, *, publish=True, now=None):
    """Refuse known future work before native prerequisites; never accept it."""
    if tid != 'JLR-035':return None
    release=c.module(root,'lean_refactor_release_inventory.py')
    now=time.time() if now is None else now
    if now >= release.RELEASE_AT:return None
    gate={'schema':'jevops.lean-refactor.release-admission.v1','task_id':tid,
          'reason':'official_release_not_due','not_before_utc':'2026-11-01T00:00:00Z',
          'retry_condition':'at or after the source-bound official release date',**c.AUTH}
    if not publish:return gate
    release.probe(root,now=now)
    directory=root/c.RUNTIME/'runs'/('JLR-035-admission-'+uuid.uuid4().hex)
    receipt={**gate,'exit_code':75,'observed_at':now,
             'scientific_run_receipt_preserved':True,
             'archive_path':str((directory/'receipt.json').relative_to(root))}
    c.save(directory/'receipt.json',receipt)
    return receipt


def current_admission_wait(root, tid, profile):
    """Pure current guards explain refusal without endorsing older science."""
    gate=release_admission(root,tid,publish=False)
    if gate is not None:return gate
    gate=iterative_admission(root,tid,publish=False)
    if gate is not None:
        result=root/c.RUNTIME/(tid+'.result.json')
        # A genuine successful trial necessarily consumed its phase. Never
        # mask a claimed winner: the full protected validator must assess it.
        if not result.is_file() or c.read(result).get('status')!='CONFIRMED':return gate
    gate=search_admission(root,tid,profile,publish=False)
    if gate is not None:return gate
    gate=frontier_failure_admission(root,tid,profile,publish=False)
    if gate is not None:return gate
    return simp_admission(root,tid,profile,publish=False)


def iterative_admission(root,tid,*,publish=True):
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
    if not publish:return gate
    c.save(root/c.RUNTIME/'iterative-admission-gate.json',gate)
    directory=root/c.RUNTIME/'runs'/('JLR-024-admission-'+uuid.uuid4().hex)
    receipt={**gate,'exit_code':75,'observed_at':time.time(),
             'scientific_run_receipt_preserved':True,
             'archive_path':str((directory/'receipt.json').relative_to(root))}
    c.save(directory/'receipt.json',receipt)
    return receipt

def simp_admission(root, tid, profile, *, publish=True):
    """Retain an unchanged negative trial without spending its CPU budget again.

    This is only a refusal to repeat work. The protected proof validator still
    requires a shorter confirmed winner before this ticket can complete.
    """
    if tid != 'JLR-019':
        return None
    path = root/c.RUNTIME/(tid+'.receipt.json')
    if not path.exists():
        return None
    receipt = c.read(path)
    # A source change in the control plane can refuse the outer handoff AFTER
    # the real bounded producer returned. Preserve that failure as well; only
    # unchanged scientific inputs and actual producer logs admit this refusal.
    drift_failure = receipt.get('exit_code') == 1 and receipt.get('error') in (
        'execution source drift; revalidate before materializing',
        'inputs or source changed during production')
    if receipt.get('exit_code') != 0 and not drift_failure:
        return None
    data_path = root/c.RUNTIME/(tid+'.result.json')
    data = c.read(data_path)
    if data.get('status') != 'NO_SHORTER_WINNER':
        return None
    # A sealed-call timeout did not judge the draft. Do not freeze that run.
    screens=data.get('screen')
    if type(screens) is list and any(type(sample) is dict and type(sample.get('receipt')) is dict
            and sample['receipt'].get('outcome')=='TIMEOUT' for sample in screens):
        return None
    c.require(receipt.get('schema') == 'jevops.lean-refactor.stage-run.v2'
              and receipt.get('task_id') == tid and (receipt.get('error') is None or drift_failure),
              'retained trial receipt identity differs')
    archived = Path(receipt['archive_path'])
    c.require(not archived.is_absolute() and '..' not in archived.parts
              and c.read(root/archived) == receipt, 'retained trial archive changed')
    c.require(set(receipt['outputs']) == set(profile['contracts'][tid]['outputs']),
              'retained trial output population differs')
    for name, digest in receipt['outputs'].items():
        c.require(c.sha(root/name) == digest, 'retained trial output changed')
    historical = receipt['binding']['source_sha256']
    # The compiled cold-check backend is never called by these spent producers.
    # Closed profile loading still binds it strictly for its own acceptance.
    scientific = [name for name in profile['source_sha256']
                  if (name.startswith('jevops/') and name not in ('jevops/arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean')) or name in (
                      'tools/lean_refactor_simp_pilot.py',
                      'tools/validate_lean_refactor_simp_pilot.py')]
    if any(historical.get(name) != profile['source_sha256'][name] for name in scientific):
        return None
    if any(c.sha(root/name) != digest for name,digest in receipt['binding']['inputs'].items()):
        return None
    import lean_refactor_simp_pilot as pilot
    if data.get('seed_sha256') != c.sha(root/pilot.SEED):
        return None
    execution = receipt['executions'][-1]
    base = c.read(root/c.BASE)
    c.require(execution['argv'] == [base['python_executable'], *profile['contracts'][tid]['argv']]
              and execution['exit_code'] == 0 and execution['timed_out'] is False,
              'retained trial producer invocation differs')
    for field in ('stdout','stderr'):
        c.require(c.sha(root/execution[field]) == execution[field+'_sha256'],
                  'retained trial subprocess log changed')
    c.require(c.read(root/execution['stdout']) == data and data.get('winner') is None
              and data.get('model_calls') == 0 and data.get('promoted') is False,
              'retained negative trial envelope differs')
    gate = {'schema':'jevops.lean-refactor.negative-trial-admission.v1','task_id':tid,
            'reason':'unchanged_negative_trial','retained_run_receipt_sha256':c.sha(path),
            'stage_run_exit_code':receipt['exit_code'],'stage_run_error':receipt.get('error'),
            'result_sha256':c.sha(data_path),'acceptance_satisfied':False,
            'unsatisfied_acceptance':'shorter independently confirmed all-pin-valid proof',
            'retry_condition':'review a changed source-bound strategy or changed native input; retain this trial',
            **c.AUTH}
    if not publish:return gate
    c.save(root/c.RUNTIME/'simp-admission-gate.json', gate)
    directory = root/c.RUNTIME/'runs'/('JLR-019-admission-'+uuid.uuid4().hex)
    refusal = {**gate,'exit_code':75,'observed_at':time.time(),
               'scientific_run_receipt_preserved':True,
               'archive_path':str((directory/'receipt.json').relative_to(root))}
    c.save(directory/'receipt.json', refusal)
    return refusal

def frontier_failure_admission(root,tid,profile,*,publish=True):
    """Do not repeat an authenticated unchanged software budget failure.

    This is a software repair wait, never a scientific negative result or a
    resource qualification. The actual failed run and every pin stay intact.
    A changed reviewed frontier implementation or frozen input rearms it.
    """
    if tid!='JLR-020':return None
    if 'tools/lean_refactor_compiled_coupled_v1.py' in profile['source_sha256']:
        return c.module(root,'lean_refactor_compiled_coupled_v1.py').admission_wait(root,publish=publish)
    path=root/c.RUNTIME/(tid+'.receipt.json')
    if not path.exists():return None
    receipt=c.read(path)
    if receipt.get('exit_code')!=1 or receipt.get('error') is not None:return None
    c.require(receipt.get('schema')=='jevops.lean-refactor.stage-run.v2'
              and receipt.get('task_id')==tid,'frontier failure receipt identity differs')
    archive=Path(receipt['archive_path'])
    c.require(not archive.is_absolute() and '..' not in archive.parts
              and c.read(root/archive)==receipt,'frontier failure archive changed')
    historical=receipt['binding']['source_sha256']
    scientific=[name for name in profile['source_sha256'] if (name.startswith('jevops/') and name not in ('jevops/arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean')) or name in (
        'tools/lean_refactor_coupled_pilot.py','tools/validate_lean_refactor_coupled_pilot.py',
        'tools/lean_refactor_native_pin_frontier.py','tools/validate_lean_refactor_native_pin_frontier.py',
        'tools/lean_refactor_project_readiness.py') or name.endswith('/llm_router.py')]
    if any(historical.get(name)!=profile['source_sha256'][name] for name in scientific):return None
    if any(c.sha(root/name)!=digest for name,digest in receipt['binding']['inputs'].items()):return None
    for name,digest in receipt['outputs'].items():
        c.require(c.sha(root/name)==digest,'frontier failure retained output changed')
    execution=receipt['executions'][-1];base=c.read(root/c.BASE)
    if execution.get('exit_code')!=1 or execution.get('timed_out') is not False:return None
    c.require(execution['argv']==[base['python_executable'],*profile['contracts'][tid]['argv']],
              'frontier failure producer invocation differs')
    for field in ('stdout','stderr'):
        c.require(c.sha(root/execution[field])==execution[field+'_sha256'],
                  'frontier failure subprocess log changed')
    error=(root/execution['stderr']).read_text()
    # Match the observed protected refusal and its actual producer call site.
    # Generic exit 1, timeouts, different crashes or a claimed proof cannot
    # silently become a wait. Their ordinary failure path remains in force.
    if not (error.rstrip().endswith('ValueError: frontier budget/population differs')
            and 'pin_frontier=frontier.produce(root)' in error
            and 'validate(root,reference);c.save(root/INDEX,reference)' in error):return None
    c.require((root/execution['stdout']).read_bytes()==b'',
              'frontier failure unexpectedly claimed a scientific result')
    gate={'schema':'jevops.lean-refactor.frontier-failure-admission.v1','task_id':tid,
          'reason':'unchanged_frontier_software_failure','blocker_kind':'software_budget_overrun',
          'retained_run_receipt_sha256':c.sha(path),'failed_exit_code':1,
          'failed_stderr_sha256':execution['stderr_sha256'],
          'acceptance_satisfied':False,'native_pins_verified_by_this_admission':0,
          'unsatisfied_acceptance':'shorter independently confirmed all-pin-valid coupled proof',
          'retry_condition':'review and measure a changed bounded frontier implementation or changed exact native inputs; preserve this failed run',
          **c.AUTH}
    if not publish:return gate
    c.save(root/c.RUNTIME/'native-pin-gate.json',gate)
    directory=root/c.RUNTIME/'runs'/('JLR-020-admission-'+uuid.uuid4().hex)
    refusal={**gate,'exit_code':75,'observed_at':time.time(),
             'scientific_run_receipt_preserved':True,
             'archive_path':str((directory/'receipt.json').relative_to(root))}
    c.save(directory/'receipt.json',refusal)
    return refusal


def search_admission(root,tid,profile,*,publish=True):
    """An intact negative search waits for changed scientific evidence."""
    if tid!='JLR-021':return None
    path=root/c.RUNTIME/(tid+'.receipt.json')
    if not path.exists():return None
    receipt=c.read(path)
    if receipt.get('exit_code')!=0 or receipt.get('error') is not None:return None
    data_path=root/c.RUNTIME/(tid+'.result.json');data=c.read(data_path)
    if data.get('status')!='NO_EXTRACTED_TERM':
        c.require(c.sha(data_path)==receipt['outputs'].get(str(data_path.relative_to(root))),
                  'negative search output changed')
        return None
    c.require(receipt['schema']=='jevops.lean-refactor.stage-run.v2' and receipt['task_id']==tid,
              'negative search receipt identity differs')
    archive=Path(receipt['archive_path'])
    c.require(not archive.is_absolute() and '..' not in archive.parts and c.read(root/archive)==receipt,
              'negative search archive changed')
    c.require(set(receipt['outputs'])==set(profile['contracts'][tid]['outputs']),'negative search output population changed')
    for name,value in receipt['outputs'].items():c.require(c.sha(root/name)==value,'negative search output changed')
    historical=receipt['binding']['source_sha256']
    scientific=[name for name in profile['source_sha256'] if (name.startswith('jevops/') and name not in ('jevops/arena_compiled.py', 'jevops/lean/ArenaAuditCheck.lean'))
                or name=='tools/lean_refactor_search_extract.py' or name.endswith('/llm_router.py')]
    if any(historical.get(name)!=profile['source_sha256'][name] for name in scientific):return None
    if any(c.sha(root/name)!=value for name,value in receipt['binding']['inputs'].items()):return None
    execution=receipt['executions'][-1];base=c.read(root/c.BASE)
    c.require(execution['argv']==[base['python_executable'],*profile['contracts'][tid]['argv']]
              and execution['exit_code']==0 and execution['timed_out'] is False,
              'negative search producer invocation changed')
    for field in ('stdout','stderr'):
        c.require(c.sha(root/execution[field])==execution[field+'_sha256'],'negative search raw log changed')
    c.require(c.read(root/execution['stdout'])==data,'negative search differs from actual stdout')
    negative=c.module(root,'validate_lean_refactor_search_extract.py').validate_negative(root,data)
    gate={'schema':'jevops.lean-refactor.search-admission.v1','task_id':tid,'reason':'unchanged_negative_search',
          'retained_run_receipt_sha256':c.sha(path),'result_sha256':c.sha(data_path),**negative}
    if not publish:return gate
    c.save(root/c.RUNTIME/'search-admission-gate.json',gate)
    directory=root/c.RUNTIME/'runs'/('JLR-021-admission-'+uuid.uuid4().hex)
    refusal={**gate,'exit_code':75,'observed_at':time.time(),'scientific_run_receipt_preserved':True,
             'archive_path':str((directory/'receipt.json').relative_to(root))}
    c.save(directory/'receipt.json',refusal)
    return refusal

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

def retained_search_run(root,tid,loaded):
    """Authenticate a frozen producer; this helper never launches or accepts it."""
    # Repairing a protected validator must not rediscover an already frozen
    # extraction or overwrite the historical producer receipt. The native lane
    # still runs its registered independent validator after this command exits.
    if tid=='JLR-021' and (root/c.RUNTIME/(tid+'.receipt.json')).exists():
        retained=c.read(root/c.RUNTIME/(tid+'.receipt.json'))
        if (retained.get('exit_code')==0 and retained.get('error') is None
                and c.stage_result(root/c.RUNTIME/(tid+'.result.json'),tid).get('status')=='CONFIRMED_EXTRACTION'):
            data,retained=c.module(root,'check_lean_refactor_stage_v2.py').execution_evidence(root,tid,loaded=loaded)
            if data.get('status')=='CONFIRMED_EXTRACTION':return retained
    return None

def run(root, tid):
    loaded=c.load(root);profile,base,tasks,board=loaded
    c.require(not c.held(root),'operator hold')
    c.require(tid in profile['contracts'],'unimplemented experiment remains planned')
    c.require(board[tid]['status'] in ('pending','ready','in_progress'),'stage is not executable')
    c.require(all(board[d]['status']=='completed' for d in tasks[tid]['depends_on']),'dependency not complete')
    retained=retained_search_run(root,tid,loaded)
    if retained is not None:return retained
    refused=release_admission(root,tid)
    if refused is not None:return refused
    refused=iterative_admission(root,tid)
    if refused is not None:return refused
    refused=search_admission(root,tid,profile)
    if refused is not None:return refused
    refused=frontier_failure_admission(root,tid,profile)
    if refused is not None:return refused
    refused=simp_admission(root,tid,profile)
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
