#!/usr/bin/env python3
"""Protected acceptance for source-bound research; no model or proof self-report."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

class GateWait(ValueError):pass

def population(rows):
    return {(r['name'],tag,commit) for r in rows for version in r['version_info'] for tag,commit in version.items()}

def check_matrix(rows, expected):
    keys=[(r['name'],r['lean_tag'],r['git_commit']) for r in rows]
    c.require(len(rows)==len(set(keys))==36 and set(keys)==expected,'complete exact 36-pin matrix required')

def readiness(root, data):
    from jevops import arena_lean,arena_prepare
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    producer=c.module(root,'lean_refactor_project_readiness.py')
    records=producer.records();check_matrix(data['rows'],population(records))
    c.require(data['schema']==producer.SCHEMA and data['corpus_sha256']==producer.CORPUS_SHA and
       data['producer_sha256']==c.sha(root/'tools/lean_refactor_project_readiness.py'),'readiness source binding')
    c.require(data['storage_cap_bytes']<=8*1024**3 and data['max_concurrent_compilers']==1 and
       data['proofs_verified']==0 and data['proof_authority'] is False,'preparation resource/proof limits')
    pilot=Path(data['pilot_root']);arena_prepare.validate_volume(c.read(pilot/'preparation.json'))
    ready=0
    for row in data['rows']:
        record=next(r for r in records if r['name']==row['name'])
        c.require(row['repository']==record['url'],'repository pin mismatch')
        if row['status']=='UNAVAILABLE':
            c.require(row['capability_gaps'] and row['binding_sha256'] is None,'unavailable is not verified')
            continue
        c.require(row['status']=='READY' and not row['capability_gaps'],'unknown readiness state')
        pin=VersionPin(row['lean_tag'],row['git_commit'])
        b=arena_lean.project_binding(record,pin,row['project'],Path(data['elan_home']))
        c.require(b.fingerprint(Fingerprinter(strict=True))==row['binding_sha256'],'native source/dependency binding drift')
        plan=producer.import_plan(b.root,b.lake,record,b.lean) if not b.putnam else []
        c.require(not producer.checked_artifacts(plan,[b.root,*[p.root for p in b.lake.packages]],b.lean,pilot/'work'),
                  'actual compiled import artifact custody failed')
        ready+=1
    c.require(ready==data['ready_pin_count'] and ready>0,'no genuinely prepared pin')
    projects=c.read(root/c.RUNTIME/'JLR-016.result.projects.json')
    c.require(projects==data['projects'] and projects,'project manifest differs')
    return {'ready_pins':ready,'required_pins':36,'all_pins_ready':ready==36,'proofs_verified':0}

def baseline(root, data):
    from jevops import arena_lean
    from jevops.arena import ArenaContext,VerificationRequest,source_hash
    from jevops.lean import VersionPin
    from jevops.proof_trust import STANDARD_AXIOMS
    producer=c.module(root,'lean_refactor_project_readiness.py')
    records=producer.records();check_matrix(data['rows'],population(records))
    ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    eligible={(r['name'],r['lean_tag'],r['git_commit']) for r in ready['rows'] if r['status']=='READY'}
    c.require(data['corpus_sha256']==producer.CORPUS_SHA and data['required_version_checks']==36,
              'baseline corpus/denominator changed')
    c.require(type(data['processes']) is int and 0<data['processes']<=12 and
              data['live_model_calls']==0 and data['official_score'] is None and
              data['local_combined_pct'] is None and data['worker_metric_parity']=='UNCONFIRMED',
              'baseline budgets or metric authority changed')
    verified=0;attempted=0
    for row in data['rows']:
        key=(row['name'],row['lean_tag'],row['git_commit'])
        c.require(row['status'] in {'UNAVAILABLE','BUDGET_EXHAUSTED','VERIFIED','REJECTED','ERROR','TIMEOUT'},'unmeasured baseline')
        if row['status']=='UNAVAILABLE':
            c.require(row['capability_gaps'] and row['baseline_compiles'] is None,'missing baseline became success')
            continue
        if row['status']=='BUDGET_EXHAUSTED':continue
        c.require(key in eligible,'native attempt on unprepared pin')
        attempted+=1
        if row['status']!='VERIFIED':continue
        receipt=row['receipt'];record=next(r for r in records if r['name']==row['name'])
        pin=VersionPin(row['lean_tag'],row['git_commit'])
        raw=row['context'];raw={**raw,'versions':tuple(VersionPin(**v) for v in raw['versions']),
            'dependency_digests':tuple(raw['dependency_digests']),'allowed_axioms':tuple(raw['allowed_axioms'])}
        context=ArenaContext(**raw);request=VerificationRequest(context,record['src'],pin)
        project=next(p for p in data['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                     (record['url'],pin.lean_tag,pin.git_commit))
        binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
        verifier=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=60.0,strict_hashes=True)
        verifier.validate_request(request)
        c.require(context.context_id==row['context_id'] and receipt['request_id']==request.request_id and
          receipt['candidate_sha256']==source_hash(record['src']) and receipt['target']==record['name'],
          'baseline target/source/context/request changed')
        observation=json.loads(receipt['observations_json']);report=observation['report']
        c.require(receipt['outcome']=='VERIFIED' and receipt['type_preserved'] is True and receipt['exit_code']==0 and
          report['type_preserved'] is True and report['target_absent_before'] is True and
          report['heartbeats']==report['raw_heartbeats']//1000 and
          report['reference_heartbeats']==report['reference_raw_heartbeats']//1000,
          'native target/type/raw heartbeat contract failed')
        for field in ('axioms','reference_axioms'):
            c.require(isinstance(report[field],list) and not set(report[field])-set(STANDARD_AXIOMS) and
                      'sorryAx' not in report[field],'native axiom growth')
        c.require(set(report['axioms'])<=set(report['reference_axioms']),'new candidate axioms')
        verified+=1
    c.require(attempted>0 and verified>0,'no actual native baseline succeeded')
    return {'verified_pin_checks':verified,'required_pin_checks':36,'missing_checks':36-verified,
            'all_pin_baseline':verified==36,'retained_incumbent':'original_fallback',
            'official_metric_parity':False}

def runtime(root, data):
    q=c.module(root,'lean_refactor_runtime_qualification.py')
    c.require(data.get('schema')=='jevops.lean-refactor.runtime-qualification.v1' and
      data.get('stage023_acceptance_satisfied') is True and data.get('generation_executed') is True,
      'health/model descriptor and actual bounded inference are required')
    c.require(0<=time.time()-data['observed_at']<300,'stale runtime qualification')
    module,_=q.provisioner(root)
    actual=q.artifacts(module)
    c.require(actual==data['artifacts'],'model custody/runtime bytes changed')
    live=q.live_readiness(module,q.unit_properties(),root)
    c.require(live['owner']==data['live_after_smoke']['owner'],'runtime actor changed')
    smoke=data['native_smoke']['actual_response']
    c.require(smoke['model']=='Leanstral' and 0<smoke['usage']['completion_tokens']<=16 and
       smoke['choices'][0]['message']['content'],'native inference response missing')
    return {'native_inference_smoke':True,'proofs_verified':0,'official_checkpoint_ancestry_attested':False}

def provenance(root, data):
    import hashlib
    from jevops import arena_lean,arena_local,proof_replay
    from jevops.lean import VersionPin
    producer=c.module(root,'lean_refactor_project_readiness.py')
    records=producer.records();check_matrix(data['rows'],population(records))
    baseline_path=root/c.RUNTIME/'JLR-017.result.json';baseline=c.read(baseline_path)
    ready=c.read(root/c.RUNTIME/'JLR-016.result.json');digest=c.sha(baseline_path)
    c.require(data['schema']=='jevops.lean-refactor.span-provenance.v1' and
        data['baseline_sha256']==digest and 0<data['native_capture_calls']<=3 and
        data['proofs_verified']==data['embedding_loads']==data['model_calls']==0 and
        data['training_executed'] is False,'provenance scope or resource bounds changed')
    captures=0
    for row in data['rows']:
        record=next(r for r in records if r['name']==row['name'])
        pin=VersionPin(row['lean_tag'],row['git_commit'])
        prior=next(r for r in baseline['rows'] if (r['name'],r['lean_tag'],r['git_commit'])==
                   (row['name'],pin.lean_tag,pin.git_commit))
        expected={'target':record['name'],'source_sha256':hashlib.sha256(record['src'].encode()).hexdigest(),
            'statement_sha256':hashlib.sha256(record['statement'].encode()).hexdigest(),'pin':pin.to_dict(),
            'baseline_sha256':digest,'context':prior.get('context') if prior['status']=='VERIFIED' else None,
            'adapter_sha256':c.sha(root/'tools/lean_refactor_span_provenance.py'),
            'capture_adapter_sha256':arena_local._identity(),'embedding_model':None,'split':'public_warmup_development'}
        c.require(row['identity']==expected and row['cache_key']==hashlib.sha256(c.canonical(expected)).hexdigest(),
                  'cross-version/source/context cache substitution')
        cursor=0;raw=record['src'].encode()
        for segment in row['segments']:
            stop=segment['end_byte']
            c.require(type(stop) is int and segment['start_byte']==cursor and cursor<stop<=len(raw) and
                      segment['text'].encode()==raw[cursor:stop],'source reconstruction failed')
            cursor=stop
        c.require(cursor==len(raw) and row['training_label'] is None and row['dependency_closure_verified'] is False,
                  'incomplete source or unearned semantic label')
        if row['status']!='NATIVE_CAPTURE':
            c.require(row['status'] in ('UNAVAILABLE','CAPTURE_FAILED','BUDGET_EXHAUSTED') and row['reason'] and
                      row['capture'] is None,'missing native capture became success')
            continue
        c.require(prior['status']=='VERIFIED','capture lacks a verified baseline')
        project=next(p for p in baseline['projects'] if p['repository']==record['url'] and
                     p['lean_tag']==pin.lean_tag and p['git_commit']==pin.git_commit)
        binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
        guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=45,strict_hashes=True)
        rt=arena_local.ArenaLocalRuntime(guard,{**record,'version_info':[{pin.lean_tag:pin.git_commit}]},max_processes=0)
        capture=row['capture'];proof_replay._check_capture(record['src'],capture,rt.context.context_id)
        c.require(capture['origin']==rt._origin(pin) and capture['trace']['lean_version']==pin.lean_tag[1:],
                  'foreign or fixture native capture')
        result=row['native_result']
        c.require(result['status']=='OBSERVED' and result['evidence_mode']=='local_lean' and
                  result['attempted_processes']==1 and result['capture']==capture and
                  result['stage']['report']==capture['trace'],'native execution missing')
        c.require(any(e['status']=='captured' and e['before']['goals'] and not e['after']['goals']
                      for e in capture['trace']['events']),'no captured native closing span')
        captures+=1
    c.require(captures==data['native_capture_count'] and captures>0,'native adapter has no observed spans')
    return {'roundtrip_pin_records':36,'native_captures':captures,'proofs_verified':0,'training_executed':False}

def receipt_binding(root, tid, receipt, loaded):
    actual=receipt['binding']
    if actual==c.binding(root,tid,loaded):return
    profile,base,tasks,board=loaded
    digest=actual.get('profile_sha256');path=profile.get('previous_profiles',{}).get(digest)
    c.require(path is not None,'unregistered historical execution profile')
    c.require(c.sha(root/path)==digest,'historical profile changed')
    historical=c.read(root/path)
    c.require(historical['contracts'][tid]==profile['contracts'][tid],'historical producer contract changed')
    # Current acceptance is always re-executed. Historical native/producer bytes
    # must still match; infrastructure extensions alone preserve old receipts.
    producer=profile['contracts'][tid]['argv'][0]
    for name,value in historical['source_sha256'].items():
        if name.startswith('jevops/') or name==producer:
            c.require(c.sha(root/name)==value,'historical scientific source changed')
    c.require(actual==c.binding(root,tid,(historical,base,tasks,board),profile_digest=digest),
              'historical input/task/source binding changed')

def validate(root, tid):
    loaded=c.load(root);profile,base,tasks,board=loaded
    c.require(tid in profile['contracts'],'unimplemented planned experiment')
    path=root/c.RUNTIME/(tid+'.receipt.json')
    if not path.exists():raise GateWait('no executed stage receipt')
    receipt=c.read(path)
    c.require(receipt['schema']=='jevops.lean-refactor.stage-run.v2' and receipt['task_id']==tid,'receipt identity')
    receipt_binding(root,tid,receipt,loaded)
    c.require(c.read(root/receipt['archive_path'])==receipt,'original archived run changed')
    if receipt['exit_code']==75:raise GateWait('stage has an evidenced external/concurrent wait')
    c.require(receipt['exit_code']==0 and receipt['proof_authority'] is False and receipt['completion_authority'] is False,
              'successful source-bound execution required')
    c.require(0<=receipt['finished_at']-receipt['started_at']<=profile['contracts'][tid]['timeout']+30,
              'bounded actual execution interval')
    c.require(set(receipt['outputs'])==set(profile['contracts'][tid]['outputs']),'result population mismatch')
    for p,digest in receipt['outputs'].items():c.require(c.sha(root/p)==digest,'output changed after execution')
    expected=[base['python_executable'],*profile['contracts'][tid]['argv']]
    executions=receipt['executions']
    c.require(executions and executions[-1]['argv']==expected and executions[-1]['exit_code']==0 and
              executions[-1]['timed_out'] is False,'closed actual producer argv missing')
    for execution in executions:
        for field in ('stdout','stderr'):
            c.require(c.sha(root/execution[field])==execution[field+'_sha256'],'actual subprocess log changed')
    data=c.read(root/c.RUNTIME/(tid+'.result.json'))
    if tid in ('JLR-017','JLR-026'):c.require(c.read(root/executions[-1]['stdout'])==data,'result differs from raw native stdout')
    result={'JLR-016':readiness,'JLR-017':baseline,'JLR-023':runtime,'JLR-026':provenance}[tid](root,data)
    return {'valid':True,'task_id':tid,**result,**c.AUTH}

def refresh_wait_probe(root, tid):
    # A failed acceptance probe remains failure. New real guards are exposed to
    # the opt-in native evidence retry; no validator success stands in for work.
    if tid not in ('JLR-016','JLR-023'):return
    import run_lean_refactor_stage_v2 as runner
    if tid=='JLR-016':
        runner.project_probe(root)
        return
    _,base,_,_=c.load(root)
    import uuid
    runner.resource_probe(root,base,root/c.RUNTIME/'probes'/uuid.uuid4().hex)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--validate-task',required=True);args=p.parse_args()
    try:
        report=validate(c.ROOT,args.validate_task);print(json.dumps(report,sort_keys=True));return 0
    except GateWait as exc:
        try:refresh_wait_probe(c.ROOT,args.validate_task)
        except (OSError,ValueError,RuntimeError) as probe_error:exc=probe_error
        print(json.dumps({'valid':False,'waiting':True,'reason':str(exc),**c.AUTH}));return 75
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        print(json.dumps({'valid':False,'reason':str(exc),**c.AUTH}),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
