#!/usr/bin/env python3
"""Protected acceptance for source-bound research; no model or proof self-report."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

GateWait = c.GateWait

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

def validate_runtime_history(root, data):
    """Validate immutable qualification evidence, never current availability.

    The enclosing stage validator verifies the archived execution, source/input
    binding and raw stdout SHA before passing this packet. Expiry does not
    undo that execution. New requests still require a separate live capability.
    """
    q=c.module(root,'lean_refactor_runtime_qualification.py')
    c.require(data.get('schema')=='jevops.lean-refactor.runtime-qualification.v1' and
      data.get('stage023_acceptance_satisfied') is True and data.get('generation_executed') is True,
      'health/model descriptor and actual bounded inference are required')
    observed=data.get('observed_at')
    c.require(type(observed) in (int,float) and 0<=observed<=time.time() and
              math.isfinite(observed),'invalid runtime qualification timestamp')
    c.require(data.get('proof_authority') is False and data.get('completion_authority') is False
              and data.get('training_executed') is False and data.get('weights_officially_attested') is False
              and data.get('conversion_quality_measured') is False, 'qualification cannot grant proof authority')
    packet=data.get('native_smoke')
    c.require(isinstance(packet,dict) and packet.get('max_output_tokens')==16 and
              isinstance(packet.get('actual_response'),dict),'native inference response missing')
    smoke=packet['actual_response'];tokens=smoke.get('usage',{}).get('completion_tokens')
    choices=smoke.get('choices')
    c.require(smoke.get('model')=='Leanstral' and type(tokens) is int and 0<tokens<=16 and
              type(smoke.get('usage',{}).get('prompt_tokens')) is int
              and 0<smoke['usage']['prompt_tokens']<=1024 and
              isinstance(choices,list) and choices and
              isinstance(choices[0],dict) and
              isinstance(choices[0].get('message',{}).get('content'),str) and
              choices[0]['message']['content'],'native inference response missing')
    before=data.get('live',{}).get('owner');after=data.get('live_after_smoke',{}).get('owner')
    c.require(isinstance(before,dict) and before and before==after,
              'runtime actor changed during qualification')
    module,_=q.provisioner(root)
    actual=q.artifacts(module)
    c.require(actual==data['artifacts'],'model custody/runtime bytes changed')
    c.require(type(after.get('supervisor_pid')) is int and after['supervisor_pid']>0
              and type(after.get('server_pid')) is int and after['server_pid']>0
              and isinstance(after.get('server_start_ticks'),str) and after['server_start_ticks'].isdigit()
              and int(after['server_start_ticks'])>0,'captured runtime owner identity missing')
    for key in ('live','live_after_smoke'):
        captured=data[key]
        # These are the REAL unit/resource observations captured before and
        # after the bounded call, not fabricated current process checks.
        q.validate_unit(captured['unit'])
        c.require(captured.get('ready') is True and captured['unit'].get('MainPID')==str(after['supervisor_pid'])
                  and isinstance(captured['unit'].get('ControlGroup'),str) and captured['unit']['ControlGroup']
                  and captured.get('health',{}).get('status')=='ok'
                  and any(row.get('id')=='Leanstral' for row in captured.get('models',{}).get('data',[]))
                  and captured.get('actual_context_tokens')==2048
                  and captured.get('reported_model_basename')==module.MODEL_NAME,
                  'captured unit/model ownership observations differ')
        c.require(type(captured.get('server_rss_bytes')) is int and captured['server_rss_bytes']>0,
                  'captured RSS observation missing')
        module.check_resources(captured['resources'],rss=captured['server_rss_bytes'])
    return {'native_inference_smoke':True,'qualification_scope':'historical',
            'current_runtime_readiness_checked':False,'proofs_verified':0,
            'official_checkpoint_ancestry_attested':False}

def runtime(root, data):
    return validate_runtime_history(root,data)

def current_runtime_capability(root, expected_owner=None):
    """Read-only current actor guard for inference callers; never start/renew."""
    q=c.module(root,'lean_refactor_runtime_qualification.py');module,_=q.provisioner(root)
    live=q.live_readiness(module,q.unit_properties(),root)
    if expected_owner is not None:
        c.require(live['owner']==expected_owner,'qualified current runtime actor changed')
    return live

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

def metric_sample(sample, record, pin, guard):
    """Check native observations against the current exact project and source."""
    from jevops.arena import ArenaContext,VerificationRequest,source_hash
    from jevops import arena_lean
    from jevops.lean import VersionPin
    from jevops.proof_trust import STANDARD_AXIOMS
    raw=sample['context']
    context=ArenaContext(**{**raw,'versions':tuple(VersionPin(**p) for p in raw['versions']),
        'dependency_digests':tuple(raw['dependency_digests']),'allowed_axioms':tuple(raw['allowed_axioms'])})
    c.require(context.reference_source==record['src'] and context.statement==record['statement'] and
              context.problem==record['name'] and context.versions==(pin,), 'metric source/target/pin changed')
    request=VerificationRequest(context,record['src'],pin);guard.validate_request(request)
    receipt=sample['receipt'];obs=json.loads(receipt['observations_json']);report=obs['report']
    c.require(receipt['request_id']==request.request_id and receipt['candidate_sha256']==source_hash(record['src'])
              and receipt['target']==record['name'] and receipt['outcome']=='VERIFIED' and
              receipt['exit_code']==0 and receipt['type_preserved'] is True,'native metric receipt not verified')
    c.require(obs['measurement']==arena_lean.METHOD and obs['branch_order']==sample['branch_order'] and
              obs['lean_version']==pin.lean_tag.removeprefix('v') and
              obs['driver_sha256']==source_hash(arena_lean.DRIVER.read_text()) and
              obs['dependency_digest']==context.dependency_digests[0], 'metric observation identity changed')
    c.require(report['type_preserved'] is True and report['target_absent_before'] is True,
              'metric target/type preservation missing')
    for field in ('raw_heartbeats','reference_raw_heartbeats','heartbeats','reference_heartbeats'):
        c.require(type(report[field]) is int and report[field]>=0,'invalid heartbeat units')
    c.require(report['heartbeats']==report['raw_heartbeats']//1000 and
              report['reference_heartbeats']==report['reference_raw_heartbeats']//1000 and
              receipt['heartbeats']==report['heartbeats'], 'raw heartbeat conversion mismatch')
    c.require(isinstance(report['axioms'],list) and isinstance(report['reference_axioms'],list) and
              set(report['axioms'])<=set(report['reference_axioms'])<=set(STANDARD_AXIOMS),
              'metric control axiom growth')

def metric_audit(root, data):
    from jevops import arena_lean
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    helper=c.module(root,'lean_refactor_metric_audit.py')
    records=c.module(root,'lean_refactor_project_readiness.py').records()
    baseline_path=root/c.RUNTIME/'JLR-017.result.json';prior=c.read(baseline_path)
    expected=helper.token_rows(root,records)
    c.require(data['schema']==helper.SCHEMA and data['token_rows']==expected and len(expected)==15,
              'whole reference tokenizer denominator/source changed')
    c.require(data['tokenizer_source_sha256']==c.sha(root/helper.UTILS) and
              data['worker_manifest_sha256']==c.sha(root/helper.SPACE/'VENDOR_MANIFEST.json') and
              data['baseline_sha256']==c.sha(baseline_path),'metric source/input drift')
    c.require(c.read(root/helper.SPACE/'VENDOR_MANIFEST.json')['evaluation_worker_included'] is False and
              data['worker_metric_parity']=='UNCONFIRMED' and data['official_score'] is None and
              data['worker_blocker']['kind']=='external_worker_interface_unavailable' and
              data['worker_blocker']['evidence']==helper.SPACE+'VENDOR_MANIFEST.json' and
              data['worker_blocker']['retry_condition'],'unearned official worker parity')
    c.require(data['model_calls']==0 and data['training_executed'] is False and
              data['proof_receipt_cache_enabled'] is False and data['native_processes']==12 and
              data['max_native_processes']==12 and data['measurement']==arena_lean.METHOD and
              data['cache_protocol']=='fresh_process_prepared_imports','metric bounds changed')
    for key in ('resources_before','resources_after'):
        resource=data[key]
        c.require(resource['eligible'] is True and resource['host_available_bytes']>=16*1024**3 and
                  resource['disk_free_bytes']>=512*1024**2,'metric resource guard failed')
    record,row=helper.select(prior,records);pin=VersionPin(row['lean_tag'],row['git_commit'])
    c.require(data['target']==record['name'] and data['pin']==pin.to_dict(),'substituted native metric control')
    ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                 (record['url'],pin.lean_tag,pin.git_commit))
    binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    reader=Fingerprinter(strict=True)
    guards={order:arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=60,
              branch_order=order,fingerprinter=reader) for order in set(helper.ORDER_BLOCK)}
    schedule=[(repeat,slot,order) for repeat in range(3) for slot,order in enumerate(helper.ORDER_BLOCK)]
    c.require(len(data['samples'])==len(schedule)==12,'three complete ABBA repeats required')
    c.require(c.read(root/c.RUNTIME/'JLR-018.partial.json')=={'samples':data['samples'],**c.AUTH},
              'durable samples differ from final observations')
    for sample,(repeat,slot,order) in zip(data['samples'],schedule):
        c.require((sample['repetition'],sample['slot'],sample['branch_order'])==(repeat,slot,order) and
                  sample['cache_label']=='fresh_process_prepared_imports','unbalanced or mixed-cache controls')
        metric_sample(sample,record,pin,guards[order])
    return {'reference_token_matches':sum(r['local_tokens']==r['published_tokens'] for r in expected),
            'upstream_token_matches':sum(r['upstream_tokens']==r['published_tokens'] for r in expected),
            'reference_count':15,'native_abba_samples':12,'official_worker_parity':False,
            'official_score':None}

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

def execution_evidence(root, tid, *, loaded=None):
    """Authenticate an actual immutable producer run, without claiming acceptance."""
    loaded=c.load(root) if loaded is None else loaded
    profile,base,tasks,board=loaded
    c.require(tid in profile['contracts'],'unimplemented planned experiment')
    import run_lean_refactor_stage_v2 as runner
    admission=runner.current_admission_wait(root,tid,profile)
    if admission is not None:
        raise GateWait('current admission wait: '+admission['reason']+'; '+admission['retry_condition'])
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
    data=c.stage_result(root/c.RUNTIME/(tid+'.result.json'),tid)
    if tid in ('JLR-017','JLR-018','JLR-019','JLR-020','JLR-021','JLR-024','JLR-026','JLR-033','JLR-034','JLR-035'):
        c.require(c.stage_result(root/executions[-1]['stdout'],tid)==data,'result differs from raw native stdout')
    return data,receipt

def validate(root, tid, *, loaded=None):
    loaded=c.load(root) if loaded is None else loaded
    data,receipt=execution_evidence(root,tid,loaded=loaded)
    checks={'JLR-016':readiness,'JLR-017':baseline,'JLR-018':metric_audit,'JLR-023':runtime,'JLR-026':provenance,
            'JLR-019':lambda r,d:c.module(r,'validate_lean_refactor_simp_pilot.py').validate(r,d),
            'JLR-020':lambda r,d:c.module(r,'validate_lean_refactor_coupled_pilot.py').validate(r,d),
            'JLR-024':lambda r,d:c.module(r,'validate_lean_refactor_iterative_pilot.py').validate(r,d),
            'JLR-021':lambda r,d:c.module(r,'validate_lean_refactor_search_extract.py').validate(r,d),
            'JLR-034':lambda r,d:c.module(r,'validate_lean_refactor_activation_audit.py').validate(r,d),
            'JLR-033':lambda r,d:c.module(r,'validate_lean_refactor_operational_faults.py').validate(r,d),
            'JLR-035':lambda r,d:c.module(r,'validate_lean_refactor_release_inventory.py').validate(r,d)}
    result=checks[tid](root,data)
    return {'valid':True,'task_id':tid,**result,**c.AUTH}

def refresh_wait_probe(root, tid):
    # A failed acceptance probe remains failure. New real guards are exposed to
    # the opt-in native evidence retry; no validator success stands in for work.
    if tid=='JLR-035':
        c.module(root,'lean_refactor_release_inventory.py').probe(root)
        return
    if tid=='JLR-020':
        import run_lean_refactor_stage_v2 as runner
        profile,_,_,_=c.load(root)
        admission=runner.frontier_failure_admission(root,tid,profile,publish=False)
        if admission is not None:
            # A clock tick cannot repair a source-bound software failure.
            # Keep this evidence stable until the reviewed implementation or
            # an actual native input changes; it never grants proof authority.
            c.save(root/c.RUNTIME/'native-pin-gate.json',admission)
        else:c.module(root,'validate_lean_refactor_native_pin_frontier.py').probe(root)
        return
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
