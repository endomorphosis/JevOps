#!/usr/bin/env python3
"""Execute the frozen Grok-reviewed local inference experiment, without fallback.

The local checkpoint is the measured experimental subject, never the campaign
orchestration provider. No service is started, weights rehashed, or proof
promoted. The two-request ledger survives source changes and failed runs.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import lean_refactor_execution_v2 as c
from jevops import arena,arena_lean
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter

SCHEMA='jevops.lean-refactor.iterative-pilot.v1'
TARGET='CallElimCorrect.extractedOldExprInVars'
LEDGER=c.RUNTIME+'/iterative-v1-ledger.json'
LIMITS={'max_calls':2,'max_input_tokens':1024,'max_output_tokens':256,
        'request_timeout_seconds':90,'total_seconds':240,'max_native_processes':4}
# The frozen original control measured 63.695 seconds. Keep this per-process
# ceiling inside the unchanged phase deadline; it grants no additional calls.
NATIVE_TIMEOUT_SECONDS=75

def prompt(record, diagnostic):
    return ('Shorten the following Lean proof at its exact native pin. Preserve the theorem and all binders. '
      'Return only a JSON object with one string key "proof", containing the body after :=. '
      'Use existing imports and no sorry, axioms or unsafe commands.\n'+record['src']+
      '\nActual compiler feedback from the previous attempt:\n'+diagnostic[:600])

def candidate(record, text):
    def pairs(items):
        result={}
        for key,value in items:
            c.require(key not in result,'duplicate response key');result[key]=value
        return result
    c.require(isinstance(text,str) and len(text.encode())<=8192,'bounded response required')
    data=json.loads(text,object_pairs_hook=pairs)
    c.require(type(data) is dict and set(data)=={'proof'} and type(data['proof']) is str,'closed proof response schema')
    source=record['statement']+' := '+data['proof']
    c.require(arena.intake_error(source,record['statement']) is None,'untrusted proof envelope')
    c.require(arena.reference_tokens(source,record['statement'])<
              arena.reference_tokens(record['src'],record['statement']),'candidate is not shorter')
    return source

def budget(root):
    previous=c.read(root/'data/lean_refactor_arena_20261024/router-budget.json')
    path=root/LEDGER
    if path.exists():
        ledger=c.read(path)
        c.require(ledger['schema']=='jevops.lean-refactor.local-inference-ledger.v1' and
          ledger['limits']==LIMITS and ledger['bootstrap_usage']==previous and
          ledger['subject']=='qualified_frozen_Leanstral' and len(ledger['attempts'])<=2,
          'phase ledger changed; never reset or silently expand a consumed budget')
        return ledger
    ledger={'schema':'jevops.lean-refactor.local-inference-ledger.v1','limits':LIMITS,
      'bootstrap_usage':previous,'subject':'qualified_frozen_Leanstral',
      'scientific_proposal_route':{'provider':'grok_cli','model':'grok-4.7','actual_llm_router_required':True,
          'fallback':False},'attempts':[],**c.AUTH}
    c.save(path,ledger);return ledger

def reserve(root,ledger,packet):
    c.require(len(ledger['attempts'])<LIMITS['max_calls'],'local inference phase budget exhausted')
    entry={**packet,'id':uuid.uuid4().hex,'reserved_at':time.time(),'status':'RESERVED'}
    ledger['attempts'].append(entry);c.save(root/LEDGER,ledger)
    return entry

def token_packet(module,messages):
    code,template=module.request('/apply-template',payload={'messages':messages,'add_generation_prompt':True})
    c.require(code==200 and type(template.get('prompt')) is str,'actual chat template unavailable')
    code,tokens=module.request('/tokenize',payload={'content':template['prompt'],'add_special':True})
    values=tokens.get('tokens')
    c.require(code==200 and type(values) is list and all(type(t) is int for t in values)
              and 0<len(values)<=LIMITS['max_input_tokens']-32,'exact templated input exceeds token budget')
    return {'template':template['prompt'],'token_count':len(values),'template_sha256':arena.source_hash(template['prompt'])}

def infer(root,messages,timeout):
    """Actual canonical router, explicit qualified experimental subject, no failover."""
    base=c.read(root/c.BASE);sys.path.insert(0,base['accelerator_source'])
    from ipfs_accelerate_py import llm_router as router
    c.require(Path(router.__file__).resolve()==Path(base['accelerator_source'])/'ipfs_accelerate_py/llm_router.py',
              'noncanonical router source')
    overlay={'IPFS_ACCELERATE_LLAMA_CPP_BASE_URL':'http://127.0.0.1:18180/v1',
      'IPFS_ACCELERATE_LLAMA_CPP_MODEL':'Leanstral','IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART':'0',
      'IPFS_ACCELERATE_LLAMA_CPP_AUTO_INSTALL':'0','IPFS_ACCELERATE_LLAMA_CPP_AUTO_UPDATE':'0',
      'IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL':'0','ipfs_accelerate_py_ROUTER_RESPONSE_CACHE':'0'}
    previous={key:os.environ.get(key) for key in overlay};raw={}
    try:
        os.environ.update(overlay)
        provider=router._get_llama_cpp_provider(auto_install=False)
        c.require(provider is not None,'explicit local subject router unavailable')
        class ObservedProvider:
            def generate(self,prompt,**kwargs):
                response=provider.chat_completions(messages,model_name='Leanstral',max_tokens=256,
                    temperature=0,timeout=timeout)
                raw.update(response)
                return response['choices'][0]['message']['content']
        text=router.generate_text(messages[0]['content'],model_name='Leanstral',provider='llama_cpp',
            provider_instance=ObservedProvider(),allow_local_fallback=False,allow_cross_provider_fallback=False,
            disable_model_retry=True,max_new_tokens=256,temperature=0,timeout=timeout)
        trace=router.get_last_generation_trace()
        c.require(trace.get('effective_provider_name')=='llama_cpp' and
                  trace.get('effective_model_name')=='Leanstral' and
                  text==raw['choices'][0]['message']['content'],'actual local inference router trace differs')
        return raw,trace
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value

def produce(root=ROOT):
    started=time.monotonic();deadline=started+LIMITS['total_seconds']-16
    c.require(not c.held(root),'operator hold')
    q=c.module(root,'lean_refactor_runtime_qualification.py');module,_=q.provisioner(root)
    # No generation or full model hash occurs in these ownership/health checks.
    live=q.live_readiness(module,q.unit_properties(),root)
    qualification=c.read(root/c.RUNTIME/'JLR-023.result.json')
    c.require(live['owner']==qualification['live_after_smoke']['owner'],'qualified actor changed')
    c.require(q.ordinary(module.ROOT/module.MODEL_NAME)==qualification['artifacts']['model_identity'],
              'qualified model custody changed')
    record=next(r for r in c.module(root,'lean_refactor_project_readiness.py').records() if r['name']==TARGET)
    pins=[VersionPin(t,v) for version in record['version_info'] for t,v in version.items()]
    c.require(len(pins)==1,'bounded pilot requires every target pin')
    pin=pins[0];prior=c.read(root/c.RUNTIME/'JLR-017.result.json');ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                 (record['url'],pin.lean_tag,pin.git_commit))
    binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    guards={order:arena_lean.NativeLeanVerifier({pin:binding},max_processes=4,timeout=NATIVE_TIMEOUT_SECONDS,
        branch_order=order,fingerprinter=Fingerprinter()) for order in ('reference-first','candidate-first')}
    report={'schema':SCHEMA,'target':TARGET,'pin':pin.to_dict(),'limits':LIMITS,'original_fallback':record['src'],
      'baseline_sha256':c.sha(root/c.RUNTIME/'JLR-017.result.json'),
      'qualification_sha256':c.sha(root/c.RUNTIME/'JLR-023.result.json'),
      'review_sha256':c.sha(root/'implementation_plan/proposals/JLR-013.review.json'),
      'owner':live['owner'],'samples':[],'attempts':[],'winner':None,'confirmation':None,
      'resources_before':live['resources'],'campaign_router_calls_added':0,
      'status':'RUNNING','training_executed':False,'promoted':False,'official_score':None,**c.AUTH}
    def persist():
        report['native_processes']=sum(g.processes for g in guards.values())
        report['wall_seconds']=time.monotonic()-started
        c.save(root/c.RUNTIME/'JLR-024.partial.json',report)
    def measure(source,order):
        c.require(not c.held(root) and sum(g.processes for g in guards.values())<4 and
                  deadline-time.monotonic()>1,'native admission budget exhausted')
        guard=guards[order];guard.timeout=min(NATIVE_TIMEOUT_SECONDS,deadline-time.monotonic())
        context=guard.context(record);receipt=guard(arena.VerificationRequest(context,source,pin))
        sample={'source':source,'context':asdict(context),'branch_order':order,'receipt':asdict(receipt)}
        report['samples'].append(sample);persist();return sample
    with (root/c.RUNTIME/'iterative-v1-ledger.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger=budget(root)
        c.require(not ledger['attempts'],'phase already attempted; inspect retained evidence before any new phase')
        report['initial']=measure(record['src'],'reference-first')
        persist()  # Retain the actual failed control too, before refusing admission.
        c.require(report['initial']['receipt']['outcome']=='VERIFIED','original fallback did not freshly verify')
        diagnostic='No previous attempt; original proof freshly verified.'
        for _ in range(2):
            if c.held(root) or deadline-time.monotonic()<2:break
            before=q.live_readiness(module,q.unit_properties(),root)
            c.require(before['owner']==live['owner'],'runtime actor changed')
            messages=[{'role':'user','content':prompt(record,diagnostic)}]
            packet=token_packet(module,messages)
            entry=reserve(root,ledger,{'messages':messages,'tokenization':packet,'owner':live['owner'],
                'producer_sha256':c.sha(root/'tools/lean_refactor_iterative_pilot.py'),
                'request':{'model':'Leanstral','messages':messages,'temperature':0,'max_tokens':256,'stream':False}})
            report['attempts'].append(entry);persist()
            call_started=time.monotonic()
            try:
                response,trace=infer(root,messages,min(90,max(.001,deadline-time.monotonic())))
                entry.update(status='RETURNED',http_status=200,response=response,router_trace=trace)
            except (OSError,ValueError,RuntimeError) as exc:
                entry.update(status='FAILED',error=type(exc).__name__)
            finally:
                entry['wall_seconds']=time.monotonic()-call_started
                entry['finished_at']=time.time();c.save(root/LEDGER,ledger);persist()
            if entry['status']!='RETURNED':continue
            response=entry['response'];usage=response.get('usage',{})
            try:
                c.require(entry['http_status']==200 and response.get('model')=='Leanstral' and
                    type(usage.get('prompt_tokens')) is int and 0<usage['prompt_tokens']<=1024 and
                    type(usage.get('completion_tokens')) is int and 0<usage['completion_tokens']<=256,'response token/model contract')
                source=candidate(record,response['choices'][0]['message']['content'])
                sample=measure(source,'reference-first');entry['sample_index']=len(report['samples'])-1
                diagnostic=json.dumps(json.loads(sample['receipt']['observations_json']).get('report',{}))[:600]
                if sample['receipt']['outcome']=='VERIFIED':
                    report['winner']=source;persist();break
            except (ValueError,KeyError,TypeError,IndexError) as exc:
                entry['candidate_error']=str(exc)[:250];diagnostic=entry['candidate_error']
            c.save(root/LEDGER,ledger);persist()
        if report['winner']:
            report['confirmation']=measure(report['winner'],'candidate-first')
        report['status']='CONFIRMED' if report['confirmation'] and report['confirmation']['receipt']['outcome']=='VERIFIED' else 'NO_CONFIRMED_WINNER'
        report['owner_after']=q.live_readiness(module,q.unit_properties(),root)['owner']
        report['local_inference_calls']=len(report['attempts'])
        c.save(root/LEDGER,ledger);report['ledger_sha256']=c.sha(root/LEDGER);persist()
        return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--produce',action='store_true',required=True);parser.parse_args()
    print(json.dumps(produce(),sort_keys=True,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
