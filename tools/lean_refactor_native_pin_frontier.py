#!/usr/bin/env python3
"""Supplement missing native pins in a private capped volume, retaining old runs.

This is a preparation substep of JLR-020, never a replacement bootstrap run.
Only frozen corpus commits/toolchains are admitted. No model or service starts.
"""
from __future__ import annotations
import argparse
import contextlib
from contextvars import ContextVar
import hashlib
import math
import stat
import threading
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
from ipfs_accelerate_py.agent_supervisor.rescue.command_processes import CommandProcessTree

SCHEMA='jevops.lean-refactor.native-pin-frontier.v1'
TARGET='Core.InitsUpdatesComm'
PILOT=c.RUNTIME+'/native-pins-v1'
INDEX=c.RUNTIME+'/native-pin-frontier.json'
MAX_SECONDS=360
# Two full source inventories and one native baseline still run after import
# preparation. Keep their measured cost inside the unchanged frontier cap.
PREPARATION_RESERVE_SECONDS=180
_ACTIVE_FRONTIER_BUDGET=ContextVar('active_frontier_budget',default=None)

class FrontierDeadline(BaseException):
    """Whole-frontier interruption, never a semantic pin failure or a proof."""


class _FrontierBudget:
    def __init__(self, root, seconds):
        self.root=root;self.started=time.monotonic();self.deadline=self.started+seconds
        self.seconds=seconds;self.phase='entry';self.run=None
        self.before_index=None;self.published_index=None;self.lock=None
        self.cleanup_depth=0;self.deadline_pending=False

    def check(self, phase=None):
        if phase is not None:self.phase=phase
        if self.deadline_pending or time.monotonic()>=self.deadline:
            raise FrontierDeadline('whole native frontier deadline exhausted during '+self.phase)

    def artifacts(self):
        if self.run is None:
            self.run=self.root/PILOT/'deadline-runs'/uuid.uuid4().hex
            self.run.mkdir(parents=True,mode=0o700)
        return self.run

    def hold_lock(self):
        """Keep the cooperative writer fence through deadline rollback."""
        if self.lock is not None:return
        path=self.root/PILOT/'frontier.lock';path.parent.mkdir(parents=True,exist_ok=True)
        lock=path.open('a+')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:lock.close();raise
        self.lock=lock

    def index_identity(self):
        path=self.root/INDEX
        try:info=path.lstat()
        except FileNotFoundError:return None
        c.require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_size<=16384,
                  'frontier index must be an owned bounded ordinary file')
        raw=path.read_bytes();after=path.lstat()
        c.require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==
                  (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'frontier index changed while reading')
        return (info.st_dev,info.st_ino,hashlib.sha256(raw).hexdigest())

    def publish(self, reference):
        """Commit only after full semantic checks; retain an inode-fenced undo."""
        self.check('index publication');self.hold_lock()
        target=self.root/INDEX;target.parent.mkdir(parents=True,exist_ok=True)
        self.before_index=self.index_identity()
        if self.before_index is not None:
            os.link(target,self.artifacts()/'index-before.json',follow_symlinks=False)
            c.require(self.index_identity()==self.before_index,'frontier index changed before publication')
        raw=(json.dumps(reference,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
        temporary=target.with_name('.'+target.name+'.'+uuid.uuid4().hex)
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
                info=os.fstat(stream.fileno())
                self.published_index=(info.st_dev,info.st_ino,hashlib.sha256(raw).hexdigest())
            self.check()
            c.require(self.index_identity()==self.before_index,'foreign frontier index changed before publication')
            os.replace(temporary,target)
            self.check()
        finally:temporary.unlink(missing_ok=True)

    def undo_deadline_publication(self):
        """Never replace another writer's index, even during interruption."""
        if self.published_index is None or self.index_identity()!=self.published_index:return False
        target=self.root/INDEX
        if self.before_index is None:target.unlink()
        else:
            backup=self.artifacts()/'index-before.json';info=backup.lstat()
            c.require((info.st_dev,info.st_ino,hashlib.sha256(backup.read_bytes()).hexdigest())==self.before_index,
                      'frontier index before-image changed')
            os.replace(backup,target)
        return True


@contextlib.contextmanager
def _defer_frontier_cleanup_deadline():
    """CPython may dispatch a cross-thread alarm despite our kernel mask."""
    budget=_ACTIVE_FRONTIER_BUDGET.get()
    if budget is not None:budget.cleanup_depth+=1
    prior_mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
    try:yield
    finally:
        try:signal.pthread_sigmask(signal.SIG_SETMASK,prior_mask)
        finally:
            if budget is not None:
                budget.cleanup_depth-=1
                if not budget.cleanup_depth:budget.check()


@contextlib.contextmanager
def whole_frontier_budget(root, *, seconds=None):
    """Bound inventory, hashing, native work and acceptance by one real timer.

    An existing real timer is left untouched and refused, rather than stolen or
    extended. This operational interruption escapes inner Exception handlers.
    """
    seconds=MAX_SECONDS if seconds is None else seconds
    c.require(threading.current_thread() is threading.main_thread(),
              'whole frontier deadline requires the main thread')
    c.require(type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=MAX_SECONDS,
              'whole frontier deadline bound differs')
    prior_timer=signal.getitimer(signal.ITIMER_REAL)
    c.require(prior_timer==(0.0,0.0),'refuse to replace an existing process real-time timer')
    prior_handler=signal.getsignal(signal.SIGALRM);budget=_FrontierBudget(root,seconds)
    def expired(*_):
        budget.deadline_pending=True
        if not budget.cleanup_depth:
            raise FrontierDeadline('whole native frontier deadline exhausted during '+budget.phase)
    active_token=_ACTIVE_FRONTIER_BUDGET.set(budget)
    signal.signal(signal.SIGALRM,expired)
    try:
        signal.setitimer(signal.ITIMER_REAL,seconds)
        yield budget
        budget.check('return')
    except FrontierDeadline as exc:
        signal.setitimer(signal.ITIMER_REAL,0)
        restored=budget.undo_deadline_publication()
        receipt=budget.artifacts()/'interruption.json'
        c.save(receipt,{'schema':'jevops.lean-refactor.frontier-deadline.v1',
          'reason':str(exc),'phase':budget.phase,'maximum_seconds':seconds,
          'actual_wall_seconds':time.monotonic()-budget.started,'index_publication_undone':restored,
          'index_reference_returned':False,'retry_condition':'review bounded implementation or changed native inputs; retain all interrupted artifacts',
          'model_calls':0,'native_pins_verified_by_this_refusal':0,**c.AUTH})
        exc.add_note('retained frontier interruption: '+str(receipt))
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        if budget.lock is not None:budget.lock.close()
        signal.signal(signal.SIGALRM,prior_handler)
        _ACTIVE_FRONTIER_BUDGET.reset(active_token)


def produce(root=ROOT):
    with whole_frontier_budget(root) as budget:
        return _produce(root,budget)


def plan(root, record):
    prior=c.read(root/c.RUNTIME/'JLR-017.result.json')
    return [(tag,commit) for version in record['version_info'] for tag,commit in version.items()
            if not any(r['name']==record['name'] and r['lean_tag']==tag and r['git_commit']==commit
                       and r['status']=='VERIFIED' for r in prior['rows'])]

def preparation_order(requested, elan_home):
    """Prioritize existing exact compilers; this does not attest readiness."""
    from jevops import arena_lean
    def missing(pair):
        try:
            arena_lean.pinned_lean(elan_home,pair[0]);return False
        except ValueError:return True
    return sorted(requested,key=missing)


def preparation_timeout(deadline, *, now=None):
    """Allocate remaining preparation time without consuming acceptance reserve."""
    remaining=deadline-(time.monotonic() if now is None else now)
    return max(0,int(remaining-PREPARATION_RESERVE_SECONDS))


def prepare_exact_pin(m, record, tag, commit, pilot, volume, elan_home, deadline, output):
    """Prepare one exact closure; the full 36-row inventory runs once afterward.

    The readiness producer's provision mode also inventories the full corpus
    after its preparation deadline. Calling it for every pin consumed the
    frontier's acceptance reserve repeatedly. Reuse the same source-bound
    provisioning/build functions here, with the original absolute deadline.
    This preparation receipt has no readiness or proof authority.
    """
    from jevops import arena, arena_lean
    group=m.group_for(m.records(),record['source'],tag)
    c.require(group['repository']==record['url'] and group['git_commit']==commit
              and record['name'] in group['problems'], 'exact preparation group differs')
    c.require(time.monotonic()<deadline, 'bounded preparation admission deadline')
    project=volume/'projects'/f"{record['source']}-{tag}-{commit[:12]}"
    started=time.monotonic();error=None;build=None
    try:
        m.clone_exact(group['repository'],commit,project,volume,deadline)
        c.require((project/'lean-toolchain').read_text().strip()=='leanprover/lean4:'+tag,
                  'project toolchain differs from corpus pin')
        environment=m.dependencies(project,volume,deadline)
        lean=arena_lean.pinned_lean(elan_home,tag)
        build=m.build_imports(project,environment,record,lean,volume,deadline)
    except (OSError,ValueError,RuntimeError) as exc:
        error=str(exc)
    report={'schema':'jevops.lean-refactor.exact-pin-preparation.v1',
            'pin':{'lean_tag':tag,'git_commit':commit},'project':str(project),
            'record_sha256':arena.content_hash(record),'build':build,'provision_error':error,
            'duration_seconds':time.monotonic()-started,'max_concurrent_compilers':1,
            'model_calls':0,'training_executed':False,'proofs_verified':0,**c.AUTH}
    c.save(output,report)
    return report


def retained_archive_capacity(root, volume, tag):
    """Cheap guard against repeating an installer that cannot fit its archive.

    Historical listing sizes only guard allocation; protected acceptance still
    independently checks exact compiler/source/dependency/import bytes.
    """
    evidence=root/c.RUNTIME/'maintenance-0253-pin-archive-probe.json'
    if not evidence.exists():return None
    packet=c.read(evidence)
    expected='lean-'+tag[1:]+'-linux'
    matches=[a for a in packet['archives'] if a['archive_root']==expected]
    c.require(len(matches)<=1,'ambiguous retained compiler archive')
    if not matches:return None
    item=matches[0];path=Path(item['path'])
    c.require(path.resolve().is_relative_to(volume.resolve()) and path.is_file()
              and not path.is_symlink(),'retained compiler archive escapes capped volume')
    info=path.stat();actual={'device':info.st_dev,'inode':info.st_ino,'bytes':info.st_size,
        'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}
    c.require(actual==item['identity'] and info.st_uid==os.getuid(),
              'retained compiler archive identity changed; authenticate before provisioning')
    required=item['regular_file_bytes']
    c.require(type(required) is int and 0<required<=8*1024**3,'invalid archive allocation bound')
    available=os.statvfs(volume).f_bavail*os.statvfs(volume).f_frsize
    reserve=128*1024**2
    if available>=required+reserve:return None
    return {'pin':tag,'reason':'retained archive extraction exceeds capped-volume reserve',
        'required_regular_file_bytes':required,'available_bytes':available,'reserve_bytes':reserve,
        'archive_sha256_historical':item['sha256'],
        'retry_condition':'authenticated partial-tree repair or sufficient free bytes within the original 8 GiB cap'}


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
        child=None;fd=None;tree=None
        try:
            child=subprocess.Popen(list(map(str,argv)),cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                                   stdout=out,stderr=err,start_new_session=True)
            tree=CommandProcessTree(child.pid)
            fd=os.pidfd_open(child.pid)
            deadline=started+timeout
            while True:
                tree.snapshot()
                try:
                    code=child.wait(timeout=min(.05,max(.001,deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic()<deadline:continue
                    timed_out=True;tree.snapshot();signal.pidfd_send_signal(fd,signal.SIGTERM)
                    try:child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        signal.pidfd_send_signal(fd,signal.SIGKILL);child.wait(timeout=3)
                    code=124;break
        except BaseException as interrupted:
            if child is not None and child.poll() is None:
                # Popen has not reaped this birth, so child.kill cannot hit a reused PID.
                try:child.kill()
                except ProcessLookupError:pass
                child.wait(timeout=3)
            observation={'argv':list(map(str,argv)),'cwd':str(cwd),
                'exit_code':child.returncode if child is not None else None,
                'timed_out':False,'interrupted':True,'interruption_type':type(interrupted).__name__,
                'duration_seconds':time.monotonic()-started,
                **{key:str(prefix.with_suffix('.'+key)) for key in ('stdout','stderr')},**c.AUTH}
            out.flush();err.flush()
            for key in ('stdout','stderr'):observation[key+'_sha256']=c.sha(Path(observation[key]))
            c.save(prefix.with_suffix('.json'),observation)
            raise
        finally:
            # A first whole-frontier alarm may arrive while the leader is
            # already gone. Finish birth-owned cleanup before delivering it.
            with _defer_frontier_cleanup_deadline():
                if tree is not None:
                    try:tree.snapshot();tree.send_signal(signal.SIGKILL)
                    finally:tree.close()
                if fd is not None:os.close(fd)
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

def _produce(root,budget):
    from jevops import arena,arena_lean
    from jevops.lean import VersionPin
    from lean_refactor_metric_audit import resource_snapshot
    started=budget.started;deadline=budget.deadline
    source_names=('tools/lean_refactor_native_pin_frontier.py','tools/lean_refactor_project_readiness.py',
                  'tools/validate_lean_refactor_native_pin_frontier.py','jevops/arena_lean.py')
    source_binding={name:c.sha(root/name) for name in source_names}
    c.require(not c.held(root) and resource_snapshot(root)['eligible'],'frontier resource/operator gate')
    budget.check("cached frontier validation")
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
    budget.hold_lock()
    _,volume=m.bootstrap_volume(pilot,m.MAX_BYTES)
    elan_home=volume/'home/.elan'
    directory=pilot/'runs'/uuid.uuid4().hex;directory.mkdir(parents=True)
    errors=[]
    for tag,commit in preparation_order(requested,elan_home):
        c.require(not c.held(root) and resource_snapshot(root)['eligible'],'frontier admission gate')
        try:
            try:arena_lean.pinned_lean(elan_home,tag);installed=True
            except ValueError:
                installed=False
                blocker=retained_archive_capacity(root,volume,tag)
                if blocker is not None:
                    errors.append(blocker);continue
            preparation_seconds=preparation_timeout(deadline)
            if preparation_seconds<1:
                errors.append({'pin':tag,'reason':'bounded preparation deadline; acceptance reserve retained'});continue
            if not installed:
                command([Path.home()/'.elan/bin/elan','toolchain','install','leanprover/lean4:'+tag],
                        volume,volume,timeout=min(180,preparation_seconds),label='elan-'+tag)
            preparation_seconds=preparation_timeout(deadline)
            if preparation_seconds<1:
                errors.append({'pin':tag,'reason':'bounded preparation deadline; acceptance reserve retained'});continue
            result=prepare_exact_pin(m,record,tag,commit,pilot,volume,elan_home,
                deadline-PREPARATION_RESERVE_SECONDS,directory/(tag+'.preparation.json'))
            if result['provision_error']:errors.append({'pin':tag,'reason':result['provision_error']})
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
            errors.append({'pin':tag,'reason':str(exc)})
    budget.check("full readiness inventory")
    readiness=directory/'readiness.json'
    ready=m.produce(SimpleNamespace(pilot_root=pilot,output=readiness,elan_home=elan_home,
        source=record['source'],tag=requested[0][0] if requested else 'v4.26.0',problem=TARGET,
        provision=False,build_imports=False,timeout_seconds=1,max_bytes=m.MAX_BYTES))
    budget.check('readiness inventory completed')
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
        budget.check('native context')
        context=guard.context({**record,'version_info':[{tag:commit}]})
        budget.check('native baseline')
        receipt=guard(arena.VerificationRequest(context,record['src'],pin))
        output.update(sample={'source':record['src'],'branch_order':'reference-first',
                              'context':asdict(context),'receipt':asdict(receipt)},reason=None)
    budget.check('observation inventory')
    report['commands']=[c.read(p) for p in sorted((volume/'logs').glob('*.json'))]
    report['wall_seconds']=time.monotonic()-started
    c.require(source_binding=={name:c.sha(root/name) for name in source_names},
              'frontier source changed during preparation; logs retained without acceptance')
    budget.check('frontier archive')
    path=directory/'frontier.json';c.save(path,report)
    reference={'path':str(path.relative_to(root)),'sha256':c.sha(path)}
    budget.check('protected frontier validation')
    validate(root,reference)
    budget.publish(reference)
    return reference

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--produce',action='store_true',required=True);p.parse_args()
    print(json.dumps(produce(),sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
