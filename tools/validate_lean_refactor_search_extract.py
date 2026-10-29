"""Protected acceptance: regenerate extraction and cold-check exact final bytes."""
from dataclasses import asdict
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

def producer():
    spec=importlib.util.spec_from_file_location('_protected_search_producer',Path(__file__).with_name('lean_refactor_search_extract.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def cold_replays(root,record,bindings,pin,source,admission):
    """Keep each actual cold outcome before enforcing the unchanged proof gate.

    These observations explain a refusal; they cannot satisfy a task or replace
    its original producer/run receipts. Each invocation has a separate archive.
    """
    from jevops import arena,arena_lean,arena_compiled
    from jevops.proof_trust import STANDARD_AXIOMS
    from jevops.seals import Fingerprinter
    path=root/c.RUNTIME/'acceptance'/('JLR-021-'+uuid.uuid4().hex)/'cold-replays.json'
    report={'schema':'jevops.lean-refactor.search-cold-observation.v1',
            'started_at':time.time(),'target':record['name'],'pin':pin.to_dict(),
            'candidate_sha256':arena.source_hash(source),
            'record_sha256':hashlib.sha256(c.canonical(record)).hexdigest(),
            'validator_sha256':c.sha(Path(__file__)),
            'native_source_sha256':c.sha(Path(arena_lean.__file__)),
            'native_timeout_seconds':60,'max_native_processes':2,
            'native_processes':0,'replays':[],'status':'RUNNING',**c.AUTH}
    c.save(path,report)
    receipts=[]
    try:
        admission()
        with arena_compiled.prepare_checkers(bindings) as checkers:
            report['compiled_builds']=[checker.manifest for checker in checkers.values()]
            c.save(path,report)
            for order in ('candidate-first','reference-first'):
                admission()
                row={'branch_order':order,'started_at':time.time(),'receipt':None}
                report['replays'].append(row);c.save(path,report)
                check=arena_compiled.CompiledNativeLeanVerifier(bindings,checkers=checkers,max_processes=1,timeout=60,
                                    branch_order=order,fingerprinter=Fingerprinter(strict=True))
                context=check.context(record)
                row['context']=asdict(context);c.save(path,report)
                receipt=check(arena.VerificationRequest(context,source,pin))
                row.update(receipt=asdict(receipt),finished_at=time.time())
                report['native_processes']+=check.processes
                c.save(path,report)
                c.require(receipt.outcome.value=='VERIFIED' and receipt.type_preserved and receipt.exit_code==0,
                          'independent cold whole-source acceptance failed: '+order+': '+
                          receipt.outcome.value+': '+receipt.reason+'; observation: '+str(path))
                native=json.loads(receipt.observations_json)['report']
                c.require(set(native['axioms'])<=set(native['reference_axioms'])<=set(STANDARD_AXIOMS),
                          'whole-source axiom growth')
                receipts.append(asdict(receipt))
        report['status']='REPLAYED'
        return receipts
    except Exception as exc:
        report.update(status='REFUSED',reason=str(exc))
        raise
    finally:
        report['finished_at']=time.time();c.save(path,report)

def validate(root,data):
    from jevops import arena,arena_lean,arena_local,proof_replay
    from jevops.proof_trust import STANDARD_AXIOMS
    from jevops.seals import Fingerprinter
    m=producer()
    c.require(data.get('schema')==m.SCHEMA and data.get('target')==m.TARGET
              and data.get('status')=='CONFIRMED_EXTRACTION','independently confirmed extraction required')
    fence=c.quiescent_maintenance_fence(root) if c.held(root) else None
    def admission():
        if fence is None:c.require(not c.held(root),'operator hold')
        else:c.require(c.quiescent_maintenance_fence(root)==fence,'maintenance ownership changed')
    admission()
    record,pins,bindings=m.target_inputs(root);source=record['src'];pin=pins[0]
    c.require(data['pins']==[p.to_dict() for p in pins] and data['original_fallback']==source
              and data['source_sha256']==arena.source_hash(source)
              and data['producer_sha256']==c.sha(Path(m.__file__))
              and data['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json')
              and data['readiness_sha256']==c.sha(root/c.RUNTIME/'JLR-016.result.json'),
              'source, native pins or baseline changed')
    c.require(data['limits']==m.LIMITS and data['model_calls']==0
              and all(data.get(k) is False for k in (*c.AUTH,'training_executed','promoted','optimization_success'))
              and data['official_score'] is None,'bounded deterministic authority required')
    c.require(type(data['native_processes']) is int and data['native_processes']==4+len(data['searches'])<=m.LIMITS['native_processes']
              and 0<data['wall_seconds']<=m.LIMITS['wall_seconds'],'actual process or wall bound')
    c.require(data['resources_before']['eligible'] is True,'CPU admission evidence missing')
    guard=arena_lean.NativeLeanVerifier(bindings,max_processes=0,timeout=120,fingerprinter=Fingerprinter(strict=True))
    runtime=arena_local.ArenaLocalRuntime(guard,record,max_processes=2,
                 node_budget=m.LIMITS['node_budget'],event_budget=m.LIMITS['event_budget'])
    c.require(data['initial']['outcome']=='VERIFIED' and data['initial']['type_preserved'] is True
              and data['initial']['candidate_sha256']==arena.source_hash(source)
              and data['capture']['ok'] is True and data['capture']['evidence_mode']=='local_lean'
              and data['capture']['attempted_processes']==1,'observed native original/capture missing')
    capture=data['capture']['capture'];proof_replay._check_capture(source,capture,runtime.context.context_id)
    events=m.closed_events(source,capture)
    searches=data['searches']
    c.require(0<len(searches)<=len(events)<=m.LIMITS['events'],'fixed closing event population changed')
    exports=[]
    for row,event in zip(searches,events):
        c.require(row['event_id']==int(event['id']) and row['result']['attempted_processes']==1
                  and row['result']['search_steps_reserved']==m.LIMITS['steps_per_event'],
                  'search event order or charged reservation differs')
        if row['export'] is not None:
            exported=m.export_candidate(source,record['statement'],event,row['result'])
            c.require(exported==row['export'],'exported source differs from original span')
            exports.append((row,event))
    c.require(len(exports)==1 and exports[0][0] is searches[-1]
              and data['winner']==searches[-1]['export'],'frozen first bounded extraction required')
    # Regenerate the capture and search with the actual pinned Lean adapter.
    admission();fresh=runtime.capture(pin)
    c.require(fresh.get('ok') is True and fresh['evidence_mode']=='local_lean','fresh native capture required')
    event_id=searches[-1]['event_id'];events_by_id={int(e['id']):e for e in fresh['capture']['trace']['events']}
    c.require(events_by_id[event_id]==exports[0][1],'native extraction anchor changed')
    admission();search=runtime.discover_search(pin,source,fresh['capture'],event_id,list(m.PREMISES),
                max_steps=m.LIMITS['steps_per_event'],max_depth=m.LIMITS['depth'])
    c.require(m.export_candidate(source,record['statement'],events_by_id[event_id],search)==data['winner'],
              'actual repeated extraction differs from emitted source')
    c.require([s['branch_order'] for s in data['confirmation']]==['reference-first','candidate-first']
              and all(s['pin']==pin.to_dict() and s['receipt']['outcome']=='VERIFIED'
                      for s in data['confirmation']),'producer cold replay observations missing')
    receipts=cold_replays(root,record,bindings,pin,data['winner']['source'],admission)
    return {'all_target_pins':len(pins),'fresh_search_processes':runtime.attempts,
            'independent_cold_replays':receipts,'token_growth':data['winner']['token_growth'],
            'optimization_success':False,'model_calls':0,**c.AUTH}

def validate_negative(root,data):
    """Authenticate a bounded negative observation; never satisfy the ticket."""
    from jevops import arena,arena_lean,arena_local,proof_replay
    from jevops.seals import Fingerprinter
    m=producer()
    c.require(data.get('schema')==m.SCHEMA and data.get('target')==m.TARGET
              and data.get('status')=='NO_EXTRACTED_TERM' and data.get('winner') is None
              and data.get('confirmation')==[],'complete negative extraction observation required')
    record,pins,bindings=m.target_inputs(root);source=record['src']
    c.require(data['pins']==[p.to_dict() for p in pins] and data['original_fallback']==source
              and data['source_sha256']==arena.source_hash(source)
              and data['producer_sha256']==c.sha(Path(m.__file__))
              and data['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json')
              and data['readiness_sha256']==c.sha(root/c.RUNTIME/'JLR-016.result.json'),
              'negative extraction source or native input changed')
    c.require(data['limits']==m.LIMITS and data['model_calls']==0
              and all(data.get(k) is False for k in (*c.AUTH,'training_executed','promoted','optimization_success'))
              and data['official_score'] is None and 0<data['wall_seconds']<=m.LIMITS['wall_seconds'],
              'negative extraction budget or authority changed')
    guard=arena_lean.NativeLeanVerifier(bindings,max_processes=0,timeout=120,fingerprinter=Fingerprinter(strict=True))
    runtime=arena_local.ArenaLocalRuntime(guard,record,max_processes=0,
                    node_budget=m.LIMITS['node_budget'],event_budget=m.LIMITS['event_budget'])
    c.require(data['initial']['outcome']=='VERIFIED' and data['initial']['type_preserved'] is True
              and data['initial']['exit_code']==0 and data['initial']['candidate_sha256']==arena.source_hash(source)
              and data['capture']['ok'] is True and data['capture']['evidence_mode']=='local_lean'
              and data['capture']['attempted_processes']==1,'negative trial did not reach native search')
    capture=data['capture']['capture'];proof_replay._check_capture(source,capture,runtime.context.context_id)
    events=m.closed_events(source,capture);rows=data['searches']
    c.require(len(rows)==len(events)>0 and data['native_processes']==2+len(rows)<=m.LIMITS['native_processes'],
              'negative trial has incomplete event population')
    for row,event in zip(rows,events):
        result=row['result'];native=result['search_report'];binding=result['binding']
        c.require(row['event_id']==int(event['id']) and row['export'] is None
                  and result['ok'] is True and result['evidence_mode']=='local_lean'
                  and result['closing_reproduced'] is False and result['extracted_candidate'] is None
                  and result['attempted_processes']==1 and result['roundtrip_attempts']==0
                  and result['proof_admitted'] is False and result['whole_source_checked'] is False,
                  'negative trial hides a failed or positive native search')
        c.require(result['search_steps_reserved']==m.LIMITS['steps_per_event']
                  and result['search_steps_observed']==native['attempted_steps']==m.LIMITS['steps_per_event']
                  and native['step_exhausted'] is True and native['application'] is None
                  and native['path'] is None and native['script'] is None
                  and native['max_steps']==m.LIMITS['steps_per_event'] and native['max_depth']==m.LIMITS['depth']
                  and native['premises']==list(m.PREMISES),'negative search was not a fully charged bounded trial')
        c.require(binding['source_sha256']==data['source_sha256']
                  and binding['event_id']==int(event['id'])
                  and binding['trace_sha256']==capture['trace_sha256']
                  and binding['premises']==list(m.PREMISES),'negative native search binding changed')
    return {'acceptance_satisfied':False,'unsatisfied_acceptance':'explicit extracted term and independent cold whole-source replay',
            'retry_condition':'review a changed source-bound search strategy or changed exact native inputs; retain this trial',**c.AUTH}
