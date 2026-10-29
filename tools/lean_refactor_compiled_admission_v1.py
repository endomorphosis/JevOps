"""Read-only admission of a registered native actor; no daemon or signal API."""
import hashlib
import math
import os
from pathlib import Path
import time
import lean_refactor_execution_v2 as c


def process(pid, *, proc_root=Path('/proc')):
    c.require(type(pid) is int and pid > 1, 'ordinary live actor PID required')
    root = proc_root / str(pid)
    before = (root / 'stat').read_text().rsplit(')', 1)[1].split()
    raw = (root / 'cmdline').read_bytes()
    result = {'pid':pid,'uid':root.stat().st_uid,'state':before[0],
        'ppid':int(before[1]),'start_ticks':int(before[19]),
        'argv':tuple(x.decode() for x in raw.split(b'\0') if x),
        'cmdline_sha256':hashlib.sha256(raw).hexdigest(),
        'cwd':str((root/'cwd').resolve()),'exe':str((root/'exe').resolve())}
    after = (root / 'stat').read_text().rsplit(')', 1)[1].split()
    c.require(before[19] == after[19] and before[1] == after[1] and after[0] not in ('Z','X')
        and raw == (root/'cmdline').read_bytes(), 'actor changed during observation')
    return result


def option(argv, name):
    found = [argv[i+1] for i,x in enumerate(argv[:-1]) if x == name]
    found += [x[len(name)+1:] for x in argv if x.startswith(name+'=')]
    c.require(len(found)==1, 'missing or ambiguous native option: '+name)
    return found[0]


def scope(root, actor, base, lane, status_path, manifest):
    argv = actor['argv']
    c.require(actor['uid']==os.getuid() and actor['state'] not in ('Z','X')
        and actor['cwd']==str(root.resolve())
        and actor['exe']==str(Path(base['python_executable']).resolve())
        and argv[1:3]==('-m','ipfs_accelerate_py.agent_supervisor.rescue.lane_resume'),
        'registered interpreter/module/repository/UID differs')
    for name, expected in (('--repo-root',root),('--todo-path',root/c.BOARD),
                           ('--status-path',status_path)):
        c.require((root/option(argv,name)).resolve()==expected.resolve(), 'native path scope differs: '+name)
    c.require(option(argv,'--bundle-key')==lane['bundle_key']
        and option(argv,'--max-seconds')==str(lane['max_resume_seconds'])
        and option(argv,'--task-header-prefix')==manifest.get('task_header_prefix','## JLR-'),
        'native lease/namespace differs')


def chain(root, owner, python, *, pid=None):
    pid = os.getpid() if pid is None else pid
    result=[]
    for _ in range(16):
        actor = process(pid)
        c.require(actor['uid']==os.getuid(), 'foreign actor in native ancestry')
        result.append(actor)
        if pid==owner['pid']:
            c.require(same_actor(actor,owner), 'native start identity changed')
            return result
        pid=actor['ppid']
        c.require(pid>1, 'caller is not a registered native descendant')
    raise ValueError('bounded native ancestry exceeded')


def same_actor(before, after):
    return {k:v for k,v in before.items() if k!='state'} == {k:v for k,v in after.items() if k!='state'}


def entry(root, actor, python, role, task):
    argv=actor['argv']
    if actor['exe']!=str(Path(python).resolve()) or actor['cwd']!=str(root.resolve()) or len(argv)<2:
        return False
    script=(root/argv[1]).resolve()
    choices=[(root/'tools/run_lean_refactor_stage_v2.py',('--task-id',task))]
    if role=='producer':
        choices.append((root/'tools/lean_refactor_coupled_pilot.py',('--produce',)))
    else:
        choices.append((root/'tools/check_lean_refactor_stage_v2.py',('--validate-task','JLR-020')))
    return any(script==path.resolve() and tuple(argv[2:])==args for path,args in choices)


def reserve(seconds, minimum):
    c.require(type(seconds) in (int,float) and math.isfinite(seconds)
        and type(minimum) in (int,float) and math.isfinite(minimum)
        and seconds>=minimum>=0, 'fresh native lease reserve required')


def admit(root, role):
    c.require(role in ('producer','validator'), 'closed compiled actor role required')
    profile,base,tasks,board=c.load(root)
    manifest=c.read(root/c.LANES)
    c.require(manifest['execution_profile']==c.PROFILE and manifest['todo_path']==c.BOARD
        and len(manifest['lanes'])==1, 'existing single registered owner required')
    cfg=c.read(root/'config/lean_refactor_arena_20261024_watchdog.json')
    live=root/cfg['runtime_manifest']
    c.require(live.resolve().is_relative_to(root.resolve()) and c.read(live)==manifest,
              'registered and live lane scope differ')
    # The foreground reviewer may validate a completed task while its own
    # exact hold remains in place. Ordinary native execution cannot use it.
    if role=='validator' and c._PREFLIGHT_VIEW.get() is not None:
        fence=c.quiescent_maintenance_fence(root)
        def held():
            c.require(c.quiescent_maintenance_fence(root)==fence, 'review hold/owner changed')
            return True
        return {'mode':'protected_quiescent_review','fence':fence,'guard':held}
    c.require(not c.held(root), 'operator hold')
    lane=manifest['lanes'][0]
    status_path=root/lane['state_dir']/(lane['state_prefix']+'_status.json')
    status=c.read(status_path);owner=process(status['pid'])
    pid_path=root/lane['state_dir']/(lane['state_prefix']+'_bundle_supervisor.pid')
    c.require(not pid_path.is_symlink() and pid_path.stat().st_uid==os.getuid()
        and pid_path.read_text().strip()==str(owner['pid'])
        and (root/option(owner['argv'],'--pid-path')).resolve()==pid_path.resolve(),
        'native PID file/status/start binding differs')
    scope(root,owner,base,lane,status_path,manifest)
    task=status.get('active_task_id')
    c.require(task in profile['contracts'] and (task=='JLR-020' or
        (role=='validator' and 'JLR-020' in tasks[task]['depends_on'])), 'native active task differs')
    c.require(any(entry(root,actor,base['python_executable'],role,task)
        for actor in chain(root,owner,base['python_executable'])[:-1]), 'registered producer/validator entry required')
    immutable={str(p):c.sha(p) for p in (root/c.BASE,root/c.LANES,root/c.PROFILE,root/c.GOALS,
        root/'config/lean_refactor_arena_20261024_watchdog.json',live)}
    def check(minimum=0):
        now=time.time();current=c.read(status_path)
        c.require(not c.held(root) and same_actor(process(owner['pid']),owner)
            and current.get('target_id')==lane['bundle_key'] and current.get('active_task_id')==task
            and current.get('phase') in ('deterministic_command','validation','dependency_revalidation')
            and type(current.get('heartbeat_at_ms')) in (int,float)
            and 0<=now-current['heartbeat_at_ms']/1000<120,
            'fresh registered actor/heartbeat/hold changed')
        c.require(all(c.sha(Path(name))==sha for name,sha in immutable.items()), 'native registration scope changed')
        uptime=float(Path('/proc/uptime').read_text().split()[0])
        age=uptime-owner['start_ticks']/os.sysconf('SC_CLK_TCK')
        reserve(lane['max_resume_seconds']-age,minimum)
        return True
    check(900)
    return {'mode':'registered_native','owner':owner,'guard':check}
