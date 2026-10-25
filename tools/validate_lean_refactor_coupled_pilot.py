"""Protected source/pin/goal and whole-theorem acceptance for coupled edits."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

def edit_check(record,draft):
    from jevops import arena
    source=record['src'];cursor=0;parts=[]
    c.require(draft['source_sha256']==arena.source_hash(source),'stale coupled source')
    c.require(draft['arm'] in ('isolated','coupled') and
              len(draft['edits'])==(1 if draft['arm']=='isolated' else 2),'coupled edit count differs')
    for edit in draft['edits']:
        a,b=edit['start'],edit['end']
        c.require(type(a) is int and type(b) is int and cursor<=a<b<=len(source) and
                  source[a:b]==edit['original'],'changed/overlapping coupled span')
        parts.extend((source[cursor:a],edit['replacement']));cursor=b
    candidate=''.join([*parts,source[cursor:]])
    c.require(candidate==draft['source'] and arena.intake_error(candidate,record['statement']) is None and
              arena.reference_tokens(candidate,record['statement'])<arena.reference_tokens(source,record['statement']),
              'coupled final source/envelope/token charge differs')
    return candidate

def sample_check(sample,record,pin,guard,expected_source,*,required=False):
    from jevops.arena import ArenaContext,VerificationRequest,source_hash
    from jevops.lean import VersionPin
    from jevops import arena_lean
    from jevops.proof_trust import STANDARD_AXIOMS
    raw=sample['context']
    ctx=ArenaContext(**{**raw,'versions':tuple(VersionPin(**p) for p in raw['versions']),
        'dependency_digests':tuple(raw['dependency_digests']),'allowed_axioms':tuple(raw['allowed_axioms'])})
    c.require(sample['source']==expected_source and raw['reference_source']==record['src'] and
              raw['statement']==record['statement'] and sample['branch_order']==guard.branch_order,
              'candidate/control source changed')
    request=VerificationRequest(ctx,expected_source,pin);guard.validate_request(request)
    receipt=sample['receipt']
    c.require(receipt['request_id']==request.request_id and receipt['candidate_sha256']==source_hash(expected_source)
              and receipt['target']==record['name'],'source/pin native request changed')
    if required:c.require(receipt['outcome']=='VERIFIED','required whole theorem did not verify')
    c.require(receipt['outcome'] in ('VERIFIED','REJECTED','TIMEOUT','ERROR'),'unmeasured native outcome')
    if receipt['outcome']!='VERIFIED':return
    observation=json.loads(receipt['observations_json']);report=observation['report']
    c.require(receipt['type_preserved'] is True and receipt['exit_code']==0 and report['type_preserved'] is True and
              report['target_absent_before'] is True,'whole theorem type/target preservation missing')
    c.require(observation['driver_sha256']==source_hash(arena_lean.DRIVER.read_text()) and
              observation['measurement']==arena_lean.METHOD and observation['branch_order']==guard.branch_order and
              observation['dependency_digest']==ctx.dependency_digests[0] and
              observation['lean_version']==pin.lean_tag.removeprefix('v'),'native measurement identity differs')
    c.require(set(report['axioms'])<=set(report['reference_axioms'])<=set(STANDARD_AXIOMS),'coupled axiom growth')
    for key in ('raw_heartbeats','reference_raw_heartbeats','heartbeats','reference_heartbeats'):
        c.require(type(report[key]) is int and report[key]>=0,'invalid raw heartbeat measurement')
    c.require(report['heartbeats']==report['raw_heartbeats']//1000 and
              report['reference_heartbeats']==report['reference_raw_heartbeats']//1000,'heartbeat units differ')

def validate(root,data):
    from jevops import arena,arena_lean,arena_local,proof_replay
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    from check_lean_refactor_stage_v2 import GateWait
    m=c.module(root,'lean_refactor_coupled_pilot.py')
    record=next(r for r in c.module(root,'lean_refactor_project_readiness.py').records() if r['name']==m.TARGET)
    c.require(data['schema']==m.SCHEMA and data['target']==m.TARGET and
              data['source_sha256']==arena.source_hash(record['src']) and data['original_fallback']==record['src'],
              'coupled theorem identity differs')
    c.require(data['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json') and
              data['readiness_sha256']==c.sha(root/c.RUNTIME/'JLR-016.result.json'),'coupled native inputs changed')
    c.require(data['model_calls']==0 and data['training_executed'] is False and data['promoted'] is False and
              data['official_score'] is None and data['max_native_processes']==24,'coupled budget/authority changed')
    drafts=data['drafts']
    c.require(len(drafts)==2 and [d['arm'] for d in drafts]==['isolated','coupled'] and
              drafts[0]['edits'][0]==drafts[1]['edits'][0] and drafts==m.proposals(record),
              'fixed isolated/coupled population differs')
    for draft in drafts:edit_check(record,draft)
    pins=[VersionPin(t,v) for version in record['version_info'] for t,v in version.items()]
    c.require([r['pin'] for r in data['rows']]==[p.to_dict() for p in pins],'required all-pin denominator differs')
    from lean_refactor_native_pin_frontier import effective_inputs
    prior,ready=effective_inputs(root,data.get('pin_frontier'))
    processes=0;capture_processes=0;waiting=False;reader=Fingerprinter(strict=True)
    for row,pin in zip(data['rows'],pins):
        original=next(r for r in prior['rows'] if (r['name'],r['lean_tag'],r['git_commit'])==
                      (m.TARGET,pin.lean_tag,pin.git_commit))
        if row['status']=='UNAVAILABLE':
            c.require(original['status']!='VERIFIED' and row['reason']==original['status'] and
                      row['initial'] is None and row['capture'] is None and not row['samples'] and
                      not row['confirmation'],'unavailable pin manufactured a native result')
            waiting=True;continue
        c.require(original['status']=='VERIFIED','native attempt lacks baseline')
        project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                     (record['url'],pin.lean_tag,pin.git_commit))
        binding=arena_lean.project_binding(record,pin,project,Path(project.get('elan_home',ready['elan_home'])))
        guards={o:arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=60,
                  branch_order=o,fingerprinter=reader) for o in m.ORDERS}
        sample_check(row['initial'],record,pin,guards[m.ORDERS[0]],record['src'],required=True);processes+=1
        c.require(row['status']=='MEASURED','native capture or baseline blocked')
        rt=arena_local.ArenaLocalRuntime(guards[m.ORDERS[0]],{**record,'version_info':[{pin.lean_tag:pin.git_commit}]},
                    max_processes=0,node_budget=20000,event_budget=256)
        result=row['capture'];capture=result['capture'];capture_processes+=1;processes+=1
        proof_replay._check_capture(record['src'],capture,rt.context.context_id)
        c.require(result['ok'] is True and result['evidence_mode']=='local_lean' and
                  result['status']=='OBSERVED' and result['attempted_processes']==1 and
                  result['stage']['report']==capture['trace'] and capture['origin']==rt._origin(pin),
                  'native parser/goal/dependency capture changed')
        for draft in drafts:
            for edit in draft['edits']:
                a=len(record['src'][:edit['start']].encode());b=len(record['src'][:edit['end']].encode())
                c.require(any(e['status']=='captured' and int(e['start'])<=a<b<=int(e['end'])
                              for e in capture['trace']['events']),'edit outside native parsed proof envelope')
        schedule=[(d,o) for d in drafts for o in m.ORDERS]
        c.require(len(row['samples'])==len(schedule)==4,'unequal isolated/coupled compiler budgets')
        for sample,(draft,order) in zip(row['samples'],schedule):
            c.require(sample['arm']==draft['arm'],'swapped isolated/coupled arm')
            sample_check(sample,record,pin,guards[order],draft['source']);processes+=1
        if data['status']=='CONFIRMED':
            c.require(len(row['confirmation'])==2 and data['winner']==drafts[1]['source'],'frozen winner missing')
            for sample,order in zip(row['confirmation'],m.ORDERS):
                sample_check(sample,record,pin,guards[order],data['winner'],required=True);processes+=1
            c.require(all(s['receipt']['outcome']=='VERIFIED' for s in row['samples'] if s['arm']=='coupled'),
                      'winner failed a screening pin')
    c.require(data['native_processes']==processes<=24 and data['capture_processes']==capture_processes,
              'coupled actual process accounting differs')
    c.require(c.stage_result(root/c.RUNTIME/'JLR-020.partial.json','JLR-020')==data,
              'durable coupled observations differ')
    # These samples have already passed exact source/pin/request validation.
    # Preserve every missing row, but never hide a definite coupled rejection
    # behind a resource-only wait that cannot repair the rejected proof.
    rejected=any(s['arm']=='coupled' and s['receipt']['outcome']=='REJECTED'
                 for row in data['rows'] for s in row['samples'])
    if rejected:
        c.require(data['status']=='NO_ALL_PIN_WINNER' and data['winner'] is None,
                  'known coupled rejection cannot be labeled a missing-pin wait')
        raise ValueError('coupled candidate rejected on a prepared exact pin; semantic repair required; missing pins retained')
    if waiting:
        c.require(data['status']=='WAITING_NATIVE_PINS' and data['winner'] is None,'missing pin became all-pin success')
        raise GateWait('coupled pilot awaits exact native pins; retry after readiness/baseline evidence changes')
    c.require(data['status']=='CONFIRMED','no independently confirmed all-pin coupled winner')
    return {'all_target_pins':len(pins),'native_processes':processes,'coupled_edits':2,'promoted':False}
