"""Independent operational acceptance; never treats registration as proof gain."""
from __future__ import annotations
import hashlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

REQUIRED=('JLR-017','JLR-018','JLR-023','JLR-033')
LIMITS={'wall_seconds':60,'model_calls':0,'gpu_jobs':0,'max_tasks':38,'max_bytes':2097152}

def evidence(root,name,digest):
    p=Path(name)
    c.require(not p.is_absolute() and '..' not in p.parts,'audit evidence path escapes campaign')
    path=root/p
    if not path.is_file() or c.sha(path)!=digest:
        path=root/c.RUNTIME/'history'/(p.name+'.'+digest)
    c.require(c.sha(path)==digest,'audit evidence changed: '+name)
    return path

def validate(root,data):
    c.require(data.get('schema')=='jevops.lean-refactor.activation-audit.v1'
              and data.get('task_id')=='JLR-034' and data.get('status')=='AUDITED_REGISTERED_ACTIVATION',
              'activation audit identity differs')
    c.require(all(data.get(k) is False for k in (*c.AUTH,'training_executed','scientific_acceptance_authority'))
              and data['historical_runtime_only'] is True and data['model_calls']==data['gpu_jobs']==0,
              'operational audit cannot assert scientific authority')
    c.require(data['limits']==LIMITS and type(data['wall_seconds']) in (int,float)
              and 0<data['wall_seconds']<=60 and len(c.canonical(data))<=LIMITS['max_bytes'],'audit bounds differ')
    resources=data['resources_before']
    c.require(resources['eligible'] is True and type(resources['host_available_bytes']) is int
              and resources['host_available_bytes']>=16*1024**3
              and type(resources['disk_free_bytes']) is int and resources['disk_free_bytes']>=512*1024**2,
              'activation audit resource admission missing')
    current,base,tasks,live_board=c.load(root)
    refs=data['evidence'];paths={name:evidence(root,name,digest) for name,digest in refs.items()}
    profile=c.read(paths[c.PROFILE]);digest=data['profile_sha256']
    c.require(refs[c.PROFILE]==digest and (c.sha(root/c.PROFILE)==digest
              or current.get('previous_profiles',{}).get(digest)==str(paths[c.PROFILE].relative_to(root))),
              'audit registration was never reviewed')
    c.require(profile['source_sha256']==data['source_sha256'],'audit scientific source snapshot differs')
    # Operational control modules are deliberately outside this science binding.
    for name,value in profile['source_sha256'].items():
        if name.startswith('jevops/') or name in ('tools/lean_refactor_activation_audit.py',
                'tools/validate_lean_refactor_activation_audit.py') or name.endswith('/llm_router.py'):
            c.require(c.sha(root/name)==value,'audited scientific source changed')
    materialized=c.read(paths[c.RUNTIME+'/materialization.json'])
    activated=c.read(paths[c.RUNTIME+'/activation.json'])
    expected=set(profile['contracts'])
    c.require('JLR-034' in expected,'activation audit is not registered')
    for receipt in (materialized,activated):
        pre=receipt['preflight']
        c.require(receipt['profile_sha256']==digest and pre['valid'] is True
                  and set(pre['implemented'])==expected
                  and pre['verified_bootstrap']==['JLR-'+str(i).zfill(3) for i in range(1,16)]
                  and set(REQUIRED)<=set(pre['verified_research'])
                  and all(pre['verified_research'][tid]['valid'] is True for tid in REQUIRED),
                  'protected registration acceptance missing')
    c.require(activated['bootstrap_usage_retained']==profile['phase_budget']['previous_usage'] and activated['router_calls_added']==0
              and activated['owner']==data['owner'] and materialized['bootstrap_restarted'] is False,
              'activation ownership or usage changed')
    tests=c.read(paths[profile['tests_receipt']])
    c.require(tests['passed'] is True and tests['source_sha256']==profile['source_sha256']
              and refs[tests['junit_path']]==tests['junit_sha256'],'audit tests not source-bound')
    cases=list(ET.parse(paths[tests['junit_path']]).getroot().iter('testcase'))
    c.require(len(cases)>=30 and not any(list(case.iter(tag)) for case in cases
              for tag in ('failure','error','skipped')),'genuine executed acceptance tests required')
    text=data['board_text'];c.require(hashlib.sha256(text.encode()).hexdigest()==data['board_sha256'],
                                   'observed board bytes changed')
    from ipfs_accelerate_py.agent_supervisor.task_sources.todo_vector_index import parse_todo_blocks
    rows=parse_todo_blocks(text,task_header_prefix='## JLR-');board={row[0]:row[3] for row in rows}
    c.require(len(board)==len(rows)==len(tasks)==38,'audit task population differs')
    for tid,task in tasks.items():
        c.require([s.strip() for s in board[tid].get('depends_on','').split(',') if s.strip()]==task['depends_on'],
                  'audit dependency changed')
    c.require(all(board[t]['status']=='completed' for t in REQUIRED),'audited prerequisite incomplete')
    inventory={}
    for tid,contract in profile['contracts'].items():
        c.require(current['contracts'].get(tid)==contract,'audit historical producer contract changed')
        c.require(board[tid]['deterministic_command']=='python3 tools/run_lean_refactor_stage_v2.py --task-id '+tid
                  and board[tid]['validation']=='python3 tools/check_lean_refactor_stage_v2.py --validate-task '+tid,
                  'audited command is not registered')
        inventory[tid]={'contract':contract,'depends_on':tasks[tid]['depends_on'],'status':board[tid]['status']}
    unknown=sorted(t for t in tasks if int(t.split('-')[1])>15 and t not in inventory)
    c.require(data['contracts']==inventory and data['unknown_planned']==unknown
              and all(board[t]['status']=='planned' for t in unknown),'unimplemented work became selectable')
    ready=sorted(t for t in inventory if board[t]['status'] in ('pending','ready','in_progress')
                 and all(board[d]['status']=='completed' for d in tasks[t]['depends_on']))
    c.require(data['ready']==ready,'ready inventory changed')
    manifest=data['manifest'];policy=data['materialization_policy']
    config=c.read(paths['config/lean_refactor_arena_20261024_watchdog.json'])
    c.require(c.read(paths[c.LANES])==manifest==c.read(paths[config['runtime_manifest']])
              and policy=={k:config[k] for k in policy},'audited live owner differs')
    c.require(manifest['execution_profile']==c.PROFILE and manifest['todo_path']==c.BOARD
              and len(manifest['lanes'])==1 and manifest['lanes'][0]['bundle_key']==data['owner']
              and policy=={'materialize_planned_work':True,'activate_planned_work':False,
                    'planned_work_mode':'implement_validate_then_activate','reset_campaign_budgets':False},
              'audit owner or authorization differs')
    c.require(data['bootstrap_usage']==profile['phase_budget']['previous_usage']
              ==c.read(paths[profile['phase_budget']['previous_usage_path']])
              and profile['phase_budget']['calls']==profile['phase_budget']['max_calls']==0,
              'bootstrap or maintenance budget changed')
    ledger=c.read(paths[c.RUNTIME+'/iterative-v1-ledger.json'])
    c.require(data['iterative_usage']==ledger and ledger['bootstrap_usage']==data['bootstrap_usage']
              and ledger['limits']['max_calls']==2 and len(ledger['attempts'])<=2,'scientific phase usage changed')
    c.require(refs[c.BASE]==profile['base_profile_sha256'] and refs[c.GOALS]==profile['goals_sha256']
              and all(refs[n]==c.sha(root/n) for n in (c.BASE,c.GOALS,c.CONTINUATION_PLAN,c.CONTINUATION_GOALS,
                    'tools/check_lean_refactor_plan.py','tools/run_lean_refactor_router_task.py')),
              'original pins, proofs or continuation changed')
    # Inspect actual owned fixture execution, including all raw subprocess/JUnit
    # bindings. Existence of a result or the producer's own report is insufficient.
    faults=c.stage_result(root/c.RUNTIME/'JLR-033.result.json','JLR-033')
    qualification=c.module(root,'validate_lean_refactor_operational_faults.py').validate(root,faults)
    return {'registered_contracts':len(inventory),'unknown_remain_planned':unknown,
            'reviewed_bootstrap_tasks':15,'owned_fault_evidence':qualification,
            'model_calls':0,'scientific_acceptance_authority':False,**c.AUTH}
