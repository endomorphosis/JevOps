#!/usr/bin/env python3
"""Bounded operational audit of the existing, protected execution registration."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import lean_refactor_execution_v2 as c
from lean_refactor_metric_audit import resource_snapshot
SCHEMA='jevops.lean-refactor.activation-audit.v1'
DEPS=('JLR-017','JLR-018','JLR-023','JLR-033')
LIMITS={'wall_seconds':60,'model_calls':0,'gpu_jobs':0,'max_tasks':38,'max_bytes':2097152}

def produce(root=ROOT):
    started=time.monotonic()
    c.require(not c.held(root),'operator hold')
    resources=resource_snapshot(root);c.require(resources['eligible'],'CPU resource gate')
    profile,base,tasks,board=c.load(root)
    c.require(all(board[t]['status']=='completed' for t in DEPS),'verified prerequisites required')
    config=c.read(root/'config/lean_refactor_arena_20261024_watchdog.json')
    manifest=c.read(root/c.LANES);live=config['runtime_manifest']
    c.require(c.read(root/live)==manifest and manifest['execution_profile']==c.PROFILE
              and manifest['todo_path']==c.BOARD and len(manifest['lanes'])==1,'registered owner differs')
    c.require(config['materialize_planned_work'] is True and config['activate_planned_work'] is False
              and config['planned_work_mode']=='implement_validate_then_activate'
              and config['reset_campaign_budgets'] is False,'materialization authorization differs')
    refs=[c.LANES,live,'config/lean_refactor_arena_20261024_watchdog.json',c.PROFILE,c.RUNTIME+'/activation.json',c.RUNTIME+'/materialization.json',profile['tests_receipt']]
    tests=c.read(root/profile['tests_receipt']);refs.append(tests['junit_path'])
    refs.extend([c.BASE,c.GOALS,c.CONTINUATION_PLAN,c.CONTINUATION_GOALS,
                 'tools/check_lean_refactor_plan.py','tools/run_lean_refactor_router_task.py',
                 profile['phase_budget']['previous_usage_path'],c.RUNTIME+'/iterative-v1-ledger.json'])
    # Preserve the exact observed board, since native status transitions continue.
    text=(root/c.BOARD).read_text()
    contracts={tid:{'contract':contract,'depends_on':tasks[tid]['depends_on'],
                   'status':board[tid]['status']} for tid,contract in profile['contracts'].items()}
    unknown=sorted(t for t in tasks if int(t.split('-')[1])>15 and t not in contracts)
    c.require(all(board[t]['status']=='planned' for t in unknown),'unknown experiment became executable')
    report={'schema':SCHEMA,'task_id':'JLR-034','status':'AUDITED_REGISTERED_ACTIVATION',
      'limits':LIMITS,'observed_at':time.time(),'profile_sha256':c.sha(root/c.PROFILE),
      'source_sha256':profile['source_sha256'],'board_text':text,
      'board_sha256':hashlib.sha256(text.encode()).hexdigest(),
      'owner':manifest['lanes'][0]['bundle_key'],'manifest':manifest,
      'materialization_policy':{k:config[k] for k in ('materialize_planned_work','activate_planned_work',
             'planned_work_mode','reset_campaign_budgets')},
      'evidence':{p:c.sha(root/p) for p in refs},'contracts':contracts,'unknown_planned':unknown,
      'ready':sorted(t for t in contracts if board[t]['status'] in ('pending','ready','in_progress')
                    and all(board[d]['status']=='completed' for d in tasks[t]['depends_on'])),
      'bootstrap_usage':c.read(root/profile['phase_budget']['previous_usage_path']),
      'iterative_usage':c.read(root/c.RUNTIME/'iterative-v1-ledger.json'),
      'resources_before':resources,'model_calls':0,'gpu_jobs':0,'training_executed':False,
      'scientific_acceptance_authority':False,'historical_runtime_only':True,**c.AUTH}
    report['wall_seconds']=time.monotonic()-started
    c.require(report['wall_seconds']<=LIMITS['wall_seconds'] and len(c.canonical(report))<=LIMITS['max_bytes'],
              'bounded activation audit exceeded')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--produce',action='store_true',required=True)
    parser.parse_args();print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0
if __name__=='__main__':raise SystemExit(main())
