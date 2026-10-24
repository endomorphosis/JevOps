#!/usr/bin/env python3
"""Source-bound research registration, separate from immutable bootstrap contracts."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'config/lean_refactor_arena_20261024_execution_v2.json'
BOARD = 'implementation_plan/lean_refactor_arena_20261024.execution-v2.todo.md'
RUNTIME = 'data/lean_refactor_arena_20261024/execution-v2'
BASE = 'config/lean_refactor_arena_20261024_supervisor.json'
GOALS = 'implementation_plan/lean_refactor_arena_20261024.goals.json'
LANES = 'config/lean_refactor_arena_20261024_lanes.json'
AUTH = {'completion_authority': False, 'proof_authority': False, 'full_campaign_complete': False}

def require(ok, message):
    if not ok: raise ValueError(message)

def sha(path):
    require(path.is_file() and not path.is_symlink(), 'ordinary source/evidence file required: '+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def read(path, *, max_bytes=8*1024**2):
    require(path.stat().st_size < max_bytes and not path.is_symlink(), 'bounded ordinary JSON required')
    return json.loads(path.read_text())

def stage_result(path, tid):
    # Native DAGs are repeated in the capture and subprocess observation. Keep
    # metadata at 8 MiB; admit only this registered trace envelope up to 32 MiB.
    return read(path, max_bytes=32*1024**2 if tid in ('JLR-020','JLR-026') else 8*1024**2)

def save(path, value):
    atomic(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')

def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'refuse symlink output')
    temp = path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    with temp.open('x') as stream:
        stream.write(text); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)

def module(root, name):
    spec=importlib.util.spec_from_file_location('_jlr_v2_'+name, root/'tools'/name)
    result=importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result

def held(root):
    paths=[root/'HOLD',root/'OPERATOR_STOP',root/'data/lean_refactor_arena_20261024/HOLD',
           root/'data/lean_refactor_arena_20261024/OPERATOR_STOP',
           root/'data/lean_refactor_arena_20261024/lane/HOLD',
           root/'data/lean_refactor_arena_20261024/lane/OPERATOR_STOP',
           root/'data/lean_refactor_arena_20261024/persistent-watchdog/HOLD',
           root/'data/lean_refactor_arena_20261024/persistent-watchdog/OPERATOR_STOP']
    return [str(p) for p in paths if p.exists()]

def definitions():
    return {
      'JLR-016': {'action':'project_readiness','timeout':900,
        'argv':['tools/lean_refactor_project_readiness.py','--provision','--build-imports',
                '--source','strata','--tag','v4.26.0','--timeout-seconds','720',
                '--output',RUNTIME+'/JLR-016.result.json'],
        'outputs':[RUNTIME+'/JLR-016.result.json',RUNTIME+'/JLR-016.result.projects.json']},
      'JLR-017': {'action':'native_baseline','timeout':900,
        'argv':['-m','jevops.arena_lean','--baseline','--projects',RUNTIME+'/JLR-016.result.projects.json',
                '--max-processes','12','--timeout','60'],
        'outputs':[RUNTIME+'/JLR-017.result.json']},
      'JLR-018': {'action':'metric_audit','timeout':900,
        'argv':['tools/lean_refactor_metric_audit.py','--produce'],
        'outputs':[RUNTIME+'/JLR-018.result.json',RUNTIME+'/JLR-018.partial.json']},
      'JLR-019': {'action':'simp_support_pilot','timeout':900,
        'argv':['tools/lean_refactor_simp_pilot.py','--produce'],
        'outputs':[RUNTIME+'/JLR-019.result.json',RUNTIME+'/JLR-019.partial.json']},
      'JLR-020': {'action':'coupled_deletion_pilot','timeout':900,
        'argv':['tools/lean_refactor_coupled_pilot.py','--produce'],
        'outputs':[RUNTIME+'/JLR-020.result.json',RUNTIME+'/JLR-020.partial.json']},
      'JLR-023': {'action':'runtime_qualification','timeout':600,
        'argv':['tools/lean_refactor_runtime_qualification.py','--qualify','--start-if-needed',
                '--inference-smoke','--wait-seconds','180'],
        'outputs':[RUNTIME+'/JLR-023.result.json']},
      'JLR-026': {'action':'span_provenance','timeout':240,
        'argv':['tools/lean_refactor_span_provenance.py','--produce'],
        'outputs':[RUNTIME+'/JLR-026.result.json']}}

def sources(root):
    names=['tools/lean_refactor_execution_v2.py','tools/run_lean_refactor_stage_v2.py',
      'tools/check_lean_refactor_stage_v2.py','tests/test_lean_refactor_execution_v2.py',
      'tools/lean_refactor_project_readiness.py','tools/lean_refactor_runtime_qualification.py',
      'tests/test_lean_refactor_project_readiness.py','tests/test_lean_refactor_runtime_qualification.py',
      'tests/test_lean_refactor_runtime_lease.py',
      'tests/test_leanstral_provision_20261024.py',
      'tools/provision_leanstral_20261024.py','tools/leanstral-inference-20261024.json',
      'jevops/arena_prepare.py','jevops/arena_lean.py','jevops/arena.py','jevops/arena_isolation.py',
      'jevops/arena_staging.py','jevops/seals.py','jevops/lean.py','jevops/proof_ca.py',
      'jevops/proof_trust.py','jevops/lean/ArenaCheck.lean']
    names += ['tools/lean_refactor_span_provenance.py','tests/test_lean_refactor_span_provenance.py',
              'jevops/arena_local.py','jevops/proof_replay.py','jevops/proof_state.py',
              'jevops/premise_search.py','jevops/lean/ProofState.lean','jevops/lean/ArenaLocal.lean']
    names += ['tools/lean_refactor_metric_audit.py','tests/test_lean_refactor_metric_audit.py',
              'papers/completion/lean_refactor_arena/upstream/lean_refactor/utils.py',
              'papers/completion/lean_refactor_arena/upstream/VENDOR_MANIFEST.json',
              'papers/completion/lean_refactor_arena/space/VENDOR_MANIFEST.json',
              'papers/completion/lean_refactor_arena/space/leaderboard.py',
              'papers/completion/lean_refactor_arena/space/benchmark_data_warmup.jsonl',
              'papers/completion/lean_refactor_arena/space/benchmark_heartbeats.jsonl']
    names += ['tools/lean_refactor_simp_pilot.py','tools/validate_lean_refactor_simp_pilot.py',
              'tests/test_lean_refactor_simp_pilot.py','jevops/solver_feedback.py','jevops/rewrite_policy.py',
              'papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/solver-0.json']
    names += ['tools/lean_refactor_coupled_pilot.py','tools/validate_lean_refactor_coupled_pilot.py',
              'tests/test_lean_refactor_coupled_pilot.py']
    base=read(root/BASE)
    names += ['tests/test_lean_refactor_continuation.py',
              'tests/test_lean_refactor_baseline_context.py',
              'tests/test_lean_refactor_source_refresh.py']
    names += [str(Path(base['accelerator_source'])/'ipfs_accelerate_py/agent_supervisor/rescue'/name)
              for name in ('lane_resume.py','supervisor_watchdog.py','planned_work_watchdog.py')]
    return {p:sha(root/p) for p in names}

def load(root=ROOT):
    profile=read(root/PROFILE)
    require(profile['schema']=='jevops.lean-refactor.execution.v2','execution profile schema')
    require(profile['contracts']==definitions(),'closed producer registration changed')
    require(profile['source_sha256']==sources(root),'execution source drift; revalidate before materializing')
    require(profile['goals_sha256']==sha(root/GOALS),'research goals changed')
    require(profile['base_profile_sha256']==sha(root/BASE),'bootstrap profile changed')
    base=read(root/BASE)
    require(base['provider']=='grok_cli' and base['model']=='grok-4.7' and
            base['allow_local_fallback'] is False and base['allow_cross_provider_fallback'] is False,
            'strict actual llm_router route required')
    require(profile['phase_budget']['max_calls']==0 and profile['phase_budget']['calls']==0,
            'this maintenance phase has no model call allowance')
    sys.path.insert(0,base['accelerator_source'])
    from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
    rows=parse_todo_blocks((root/BOARD).read_text(),task_header_prefix='## JLR-')
    board={row[0]:row[3] for row in rows}
    tasks={t['id']:t for t in read(root/GOALS)['tasks']}
    require(len(board)==len(rows)==len(tasks)==38,'all original dependencies must remain registered')
    for tid,t in tasks.items():
        require(tid in board and [s.strip() for s in board[tid].get('depends_on','').split(',') if s.strip()]==t['depends_on'],
                'dependency link changed: '+tid)
        if tid in profile['contracts']:
            require(board[tid]['deterministic_command']=='python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid,
                    'producer board contract differs')
            require(board[tid]['validation']=='python3 tools/check_lean_refactor_stage_v2.py --validate-task '+tid,
                    'protected validator differs')
            outputs=list(profile['contracts'][tid]['outputs'])
            if tid=='JLR-023':outputs.append(RUNTIME+'/resource-gate.json')
            if tid=='JLR-016':outputs.append(RUNTIME+'/project-gate.json')
            require([s.strip() for s in board[tid]['outputs'].split(',')]==outputs,'declared stage outputs differ')
            require(board[tid].get('provider_role')=='deterministic','research producer role differs')
            require(board[tid].get('implementation_timeout_seconds')==str(profile['contracts'][tid]['timeout']),
                    'stage timeout differs')
        elif int(tid.split('-')[1])>15:
            require(board[tid]['status']=='planned','unimplemented research must stay planned')
    return profile,base,tasks,board

def binding(root, tid, loaded=None, profile_digest=None):
    profile,base,tasks,board=loaded or load(root)
    t=tasks[tid]
    inputs={p:sha(root/p) for p in t['work_package']['inputs'] if (root/p).is_file()}
    # Research inputs are bound to this phase, not to unproduced legacy paths.
    for dep in t['depends_on']:
        if dep in profile['contracts']:
            inputs[RUNTIME+'/'+dep+'.result.json']=sha(root/RUNTIME/(dep+'.result.json'))
        elif int(dep.split('-')[1])<=15:
            bootstrap_validate(root,base,dep)
    return {'profile_sha256':profile_digest or sha(root/PROFILE),'task_sha256':hashlib.sha256(canonical(t)).hexdigest(),
            'inputs':inputs,'source_sha256':profile['source_sha256']}

def bootstrap_validate(root, base, tid):
    # The original receipts deliberately bind the argv spelling `python3`.
    # Run their unmodified checker with that same canonical venv interpreter.
    python3=Path(base['python_executable']).with_name('python3')
    require(python3.resolve()==Path(base['python_executable']).resolve(),'bootstrap interpreter identity differs')
    result=subprocess.run([str(python3),str(root/'tools/check_lean_refactor_plan.py'),'--validate-task',tid],
        cwd=root,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=45,
        env={**os.environ,'PYTHONPATH':base['accelerator_source']+os.pathsep+str(root),'PYTHONDONTWRITEBYTECODE':'1'})
    require(result.returncode==0,'bootstrap prerequisite failed '+tid+': '+result.stderr[-800:])

def preflight(root=ROOT):
    profile,base,tasks,board=load(root)
    original=module(root,'check_lean_refactor_plan.py')
    campaign=original.load_plan(root)
    verified=[]
    for tid in tasks:
        if int(tid.split('-')[1])<=15:
            require(campaign['board'][tid][3]['status']=='completed' and board[tid]['status']=='completed',
                    'bootstrap is not complete')
            bootstrap_validate(root,base,tid);verified.append(tid)
    from ipfs_accelerate_py.agent_supervisor.rescue.lane_resume import parse_deterministic_command
    for tid,fields in board.items():
        for key in ('deterministic_command','validation'):
            require(parse_deterministic_command(fields[key],repo_root=root),'non-native argv: '+tid)
    receipt=read(root/profile['tests_receipt'])
    require(receipt['passed'] is True and receipt['source_sha256']==profile['source_sha256'],
            'focused actual test receipt absent or stale')
    require(sha(root/receipt['junit_path'])==receipt['junit_sha256'],'JUnit changed')
    import xml.etree.ElementTree as ET
    cases=list(ET.parse(root/receipt['junit_path']).getroot().iter('testcase'))
    require(len(cases)>=30 and not any(list(c.iter(t)) for c in cases for t in ('failure','error','skipped')),
            'real executed focused tests required')
    return {'valid':True,'verified_bootstrap':verified,'implemented':list(profile['contracts']),
            'ready':[tid for tid in profile['contracts'] if board[tid]['status'] in ('pending','ready') and
                     all(board[d]['status']=='completed' for d in tasks[tid]['depends_on'])],**AUTH}

def freeze(root, junit):
    require(not held(root),'operator hold')
    require(not (root/PROFILE).exists(),'execution owner already exists; extend it explicitly')
    base=read(root/BASE); ledger=read(root/'data/lean_refactor_arena_20261024/router-budget.json')
    original=module(root,'check_lean_refactor_plan.py')
    campaign=original.load_plan(root)
    for tid in list(campaign['tasks'])[:15]: bootstrap_validate(root,base,tid)
    text=(root/base['taskboard']).read_text()
    for tid,contract in definitions().items():
        pattern=r'(## '+tid+r' .*?)(?=\n## JLR-|\Z)'
        old=re.search(pattern,text,re.S).group(1)
        new=re.sub(r'- Status: planned', '- Status: pending',old,count=1)
        new=re.sub(r'- Deterministic command: .*', '- Deterministic command: python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid,new)
        new=re.sub(r'- Validation: .*','- Validation: python3 tools/check_lean_refactor_stage_v2.py --validate-task '+tid,new)
        new=re.sub(r'- Outputs: .*','- Outputs: '+', '.join(contract['outputs']),new)
        new=re.sub(r'- Predicted files: .*','- Predicted files: '+', '.join(contract['outputs']),new)
        if tid=='JLR-023':
            new += '\n- Retry on changed evidence: true\n- Outputs: '+RUNTIME+'/resource-gate.json\n'
            # Keep one native Outputs field, including the cheap semantic gate.
            new=new.replace('- Outputs: '+contract['outputs'][0]+'\n','- Outputs: '+contract['outputs'][0]+', '+RUNTIME+'/resource-gate.json\n',1)
            new=new.rsplit('\n- Outputs:',1)[0]+'\n'
        text=text.replace(old,new,1)
    text=text.replace('# JevOps Lean Refactor Arena research taskboard', '# JevOps Lean Refactor Arena execution v2 taskboard',1)
    atomic(root/BOARD,text)
    snapshot=sources(root)
    receipt_path=RUNTIME+'/focused-tests.json'
    save(root/receipt_path,{'passed':True,'source_sha256':snapshot,'junit_path':str(junit.relative_to(root)),
                           'junit_sha256':sha(junit),'observed_at':time.time(),**AUTH})
    profile={'schema':'jevops.lean-refactor.execution.v2','board':BOARD,'contracts':definitions(),
             'source_sha256':snapshot,'goals_sha256':sha(root/GOALS),'base_profile_sha256':sha(root/BASE),
             'tests_receipt':receipt_path,'phase_budget':{'max_calls':0,'calls':0,
             'previous_usage':ledger,'previous_usage_path':'data/lean_refactor_arena_20261024/router-budget.json'},
             'scientific_route':{'provider':'grok_cli','model':'grok-4.7','actual_llm_router_required':True,
                                 'allow_local_fallback':False,'allow_cross_provider_fallback':False}}
    save(root/PROFILE,profile)
    report=preflight(root)
    save(root/RUNTIME/'materialization.json',{'observed_at':time.time(),'profile_sha256':sha(root/PROFILE),
          'board_sha256':sha(root/BOARD),'preflight':report,'bootstrap_restarted':False,**AUTH})
    return report

def register(root):
    require(not held(root),'operator hold')
    report=preflight(root)
    cfg=read(root/'config/lean_refactor_arena_20261024_watchdog.json')
    require(cfg['activate_planned_work'] is False and cfg['materialize_planned_work'] is True and
            cfg['planned_work_mode']=='implement_validate_then_activate','materialization authorization differs')
    old=read(root/LANES)
    require(len(old['lanes'])==1,'one existing native owner required')
    require(old.get('execution_profile') in (None,PROFILE),'different execution owner already registered')
    updated={**old,'todo_path':BOARD,'execution_profile':PROFILE}
    state=root/RUNTIME
    previous=state/'pre-registration-manifest.json'
    if not previous.exists(): save(previous,old)
    atomic(root/LANES,json.dumps(updated,indent=2)+'\n')
    # Existing registered units reload this manifest. No detached daemon launch.
    save(root/cfg['runtime_manifest'],updated)
    receipt={'schema':'jevops.lean-refactor.activation.v2','observed_at':time.time(),
       'profile_sha256':sha(root/PROFILE),'board_sha256':sha(root/BOARD),'preflight':report,
       'manifest_sha256':sha(root/cfg['runtime_manifest']),'owner':old['lanes'][0]['bundle_key'],
       'router_calls_added':0,'bootstrap_usage_retained':read(root/'data/lean_refactor_arena_20261024/router-budget.json'),
       'awaiting_independent_dispatcher_observation':True,**AUTH}
    save(state/'activation.json',receipt)
    return receipt

def refresh(root, junit, *, source_only=False):
    """Extend the existing owner after actual tests, retaining every old binding."""
    require(source_only or not held(root),'operator hold')
    old=read(root/PROFILE)
    require(old['schema']=='jevops.lean-refactor.execution.v2','unknown execution owner')
    if source_only:
        require(held(root),'source-only review requires an operator hold')
        require(old['contracts']==definitions(),
                'source-only review cannot register, activate or change producer contracts')
        for lane in read(root/LANES)['lanes']:
            status=read(root/lane['state_dir']/(lane['state_prefix']+'_status.json'))
            require(status.get('state')=='paused' and status.get('phase')=='operator_hold'
                    and not status.get('active_task_id') and status.get('active_lease_count',0)==0
                    and 0<=time.time()-status.get('heartbeat_at_ms',0)/1000<120,
                    'source-only review requires a fresh quiescent lane acknowledgement')
    require(old['base_profile_sha256']==sha(root/BASE) and old['goals_sha256']==sha(root/GOALS),
            'bootstrap or research plan changed')
    require(old['phase_budget']['calls']==old['phase_budget']['max_calls']==0,
            'maintenance call budget cannot change')
    require(old['phase_budget']['previous_usage']==read(root/old['phase_budget']['previous_usage_path']),
            'previous router usage changed; retain and reconcile explicitly')
    import xml.etree.ElementTree as ET
    cases=list(ET.parse(junit).getroot().iter('testcase'))
    require(len(cases)>=30 and not any(list(case.iter(tag)) for case in cases
                                      for tag in ('failure','error','skipped')),'fresh executed tests required')
    for name in ('test_lean_refactor_execution_v2','test_lean_refactor_project_readiness',
                 'test_lean_refactor_runtime_qualification','test_lean_refactor_continuation',
                 'test_lean_refactor_span_provenance', 'test_lean_refactor_baseline_context',
                 'test_lean_refactor_source_refresh', 'test_lean_refactor_metric_audit',
                 'test_lean_refactor_simp_pilot','test_lean_refactor_coupled_pilot'):
        require(any(name in case.get('classname','') for case in cases),'focused suite missing: '+name)
    snapshot=sources(root)
    for relative in (PROFILE,old['tests_receipt'],RUNTIME+'/materialization.json',RUNTIME+'/activation.json'):
        path=root/relative
        if path.exists():
            archived=root/RUNTIME/'history'/(path.name+'.'+sha(path))
            if not archived.exists():atomic(archived,path.read_text())
    text=(root/BOARD).read_text()
    for tid,contract in definitions().items():
        pattern=r'(## '+tid+r' .*?)(?=\n## JLR-|\Z)'
        previous=re.search(pattern,text,re.S).group(1)
        changed=previous
        if tid not in old['contracts']:
            require('- Status: planned' in previous,'new registration must originate in planned work')
            changed=changed.replace('- Status: planned','- Status: pending',1)
            changed=re.sub(r'- Deterministic command: .*','- Deterministic command: python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid,changed)
            changed=re.sub(r'- Validation: .*','- Validation: python3 tools/check_lean_refactor_stage_v2.py --validate-task '+tid,changed)
            changed=re.sub(r'- Implementation timeout seconds: .*','- Implementation timeout seconds: '+str(contract['timeout']),changed)
        if '- Execution inputs:' not in changed:
            changed=changed.rstrip()+'\n- Execution inputs: '+PROFILE+'\n\n'
        if tid=='JLR-020':
            changed=re.sub(r'- Execution inputs: .*','- Execution inputs: '+PROFILE+', '+
                RUNTIME+'/JLR-016.result.json, '+RUNTIME+'/JLR-017.result.json',changed)
        changed=re.sub(r'- Implementation timeout seconds: .*',
                       '- Implementation timeout seconds: '+str(contract['timeout']),changed)
        outputs=list(contract['outputs'])
        if tid=='JLR-016':outputs.append(RUNTIME+'/project-gate.json')
        if tid=='JLR-023':outputs.append(RUNTIME+'/resource-gate.json')
        changed=re.sub(r'- Outputs: .*','- Outputs: '+', '.join(outputs),changed)
        changed=re.sub(r'- Predicted files: .*','- Predicted files: '+', '.join(outputs),changed)
        if tid in ('JLR-016','JLR-020','JLR-023') and '- Retry on changed evidence:' not in changed:
            changed=changed.rstrip()+'\n- Retry on changed evidence: true\n\n'
        text=text.replace(previous,changed,1)
    if not source_only:
        atomic(root/BOARD,text)
    save(root/old['tests_receipt'],{'passed':True,'source_sha256':snapshot,
        'junit_path':str(junit.relative_to(root)),'junit_sha256':sha(junit),'observed_at':time.time(),**AUTH})
    previous_profiles={**old.get('previous_profiles',{}),sha(root/PROFILE):
                       RUNTIME+'/history/'+Path(PROFILE).name+'.'+sha(root/PROFILE)}
    profile={**old,'contracts':definitions(),'source_sha256':snapshot,'previous_profiles':previous_profiles}
    save(root/PROFILE,profile)
    report=preflight(root)
    save(root/RUNTIME/'materialization.json',{'observed_at':time.time(),'profile_sha256':sha(root/PROFILE),
        'board_sha256':sha(root/BOARD),'preflight':report,'previous_profile_sha256':
        hashlib.sha256(canonical(old)).hexdigest(),'bootstrap_restarted':False,
        'source_only_review':source_only,'taskboard_changed':not source_only,**AUTH})
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group()
    group.add_argument('--freeze-tests',type=Path);group.add_argument('--refresh-tests',type=Path)
    group.add_argument('--register',action='store_true')
    p.add_argument('--source-only',action='store_true',
        help='Review source updates while held; preserve the taskboard and all producer contracts')
    args=p.parse_args()
    if args.source_only and not args.refresh_tests:
        p.error('--source-only requires --refresh-tests')
    try:
        with (ROOT/'data/lean_refactor_arena_20261024/execution-v2-registration.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=refresh(ROOT,args.refresh_tests.resolve(),source_only=args.source_only) if args.refresh_tests else freeze(ROOT,args.freeze_tests.resolve()) if args.freeze_tests else register(ROOT) if args.register else preflight(ROOT)
        print(json.dumps(result,sort_keys=True));return 0
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'valid':False,'reason':str(exc),**AUTH}),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
