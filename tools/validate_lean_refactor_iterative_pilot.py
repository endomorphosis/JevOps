"""Protected exact-pin acceptance for the bounded local checkpoint trial."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

def validate(root,data):
    from jevops import arena,arena_lean
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    from validate_lean_refactor_coupled_pilot import sample_check
    m=c.module(root,'lean_refactor_iterative_pilot.py')
    record=next(r for r in c.module(root,'lean_refactor_project_readiness.py').records() if r['name']==m.TARGET)
    pins=[VersionPin(t,v) for version in record['version_info'] for t,v in version.items()]
    c.require(len(pins)==1 and data['pin']==pins[0].to_dict() and data['target']==m.TARGET and
              data['schema']==m.SCHEMA and data['limits']==m.LIMITS,'whole target pin/budget contract changed')
    pin=pins[0]
    c.require(data['original_fallback']==record['src'] and data['training_executed'] is False and
              data['promoted'] is False and data['official_score'] is None and
              data['proof_authority'] is False and data['completion_authority'] is False and
              0<data['wall_seconds']<=245,'authority, source or wall budget changed')
    c.require(data['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json') and
              data['qualification_sha256']==c.sha(root/c.RUNTIME/'JLR-023.result.json') and
              data['review_sha256']==c.sha(root/'implementation_plan/proposals/JLR-013.review.json'),
              'frozen native inputs or Grok experiment review changed')
    ledger=c.read(root/m.LEDGER)
    c.require(c.sha(root/m.LEDGER)==data['ledger_sha256'] and ledger==m.budget(root) and
              ledger['attempts']==data['attempts'] and 0<len(data['attempts'])<=2 and
              data['local_inference_calls']==len(data['attempts']) and data['campaign_router_calls_added']==0,
              'phase reservations/failures were removed or changed')
    c.require(len({e['id'] for e in data['attempts']})==len(data['attempts']),'duplicate call reservation')
    q=c.module(root,'lean_refactor_runtime_qualification.py');module,_=q.provisioner(root)
    qualification=c.read(root/c.RUNTIME/'JLR-023.result.json')
    c.require(data['owner']==data['owner_after']==qualification['live_after_smoke']['owner']==
              q.live_readiness(module,q.unit_properties(),root)['owner'],'qualified actor changed during inference')
    c.require(q.ordinary(module.ROOT/module.MODEL_NAME)==qualification['artifacts']['model_identity'],
              'frozen checkpoint custody changed')
    prior=c.read(root/c.RUNTIME/'JLR-017.result.json');ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                 (record['url'],pin.lean_tag,pin.git_commit))
    binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    reader=Fingerprinter(strict=True);checked=set()
    def check(index,source,order,required=False):
        c.require(type(index) is int and 0<=index<len(data['samples']) and index not in checked,'sample population differs')
        sample=data['samples'][index];options=json.loads(sample['context']['verifier_options_json'])
        c.require(type(options['timeout']) in (int,float) and 0<options['timeout']<=m.NATIVE_TIMEOUT_SECONDS and
                  sample['branch_order']==order,'native verification budget/order changed')
        guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=options['timeout'],
            branch_order=order,fingerprinter=reader)
        sample_check(sample,record,pin,guard,source,required=required);checked.add(index)
        return sample
    initial=check(0,record['src'],'reference-first',True)
    c.require(data['initial']==initial,'original incumbent was substituted')
    diagnostic='No previous attempt; original proof freshly verified.'
    verified=[]
    for entry in data['attempts']:
        messages=[{'role':'user','content':m.prompt(record,diagnostic)}]
        c.require(entry['messages']==messages and entry['owner']==data['owner'] and
                  entry['producer_sha256']==c.sha(root/'tools/lean_refactor_iterative_pilot.py') and
                  entry['request']=={'model':'Leanstral','messages':messages,'temperature':0,
                    'max_tokens':256,'stream':False} and
                  entry['tokenization']==m.token_packet(module,messages), 'request/source/template changed')
        c.require(entry['status'] in ('RETURNED','FAILED') and
                  0<=entry['wall_seconds']<=91 and entry['reserved_at']<=entry['finished_at'],
                  'unobserved call or request deadline exceeded')
        if entry['status']=='FAILED':
            c.require(entry.get('error') and 'sample_index' not in entry,'failed inference became a candidate');continue
        response=entry['response'];usage=response.get('usage',{})
        c.require(entry['router_trace'].get('effective_provider_name')=='llama_cpp' and
                  entry['router_trace'].get('effective_model_name')=='Leanstral', 'actual experimental subject route changed')
        c.require(entry['http_status']==200 and response.get('model')=='Leanstral' and
                  type(usage.get('prompt_tokens')) is int and 0<usage['prompt_tokens']<=1024 and
                  type(usage.get('completion_tokens')) is int and 0<usage['completion_tokens']<=256,
                  'actual model/token usage missing or over budget')
        try:source=m.candidate(record,response['choices'][0]['message']['content'])
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            c.require(entry.get('candidate_error')==str(exc)[:250] and 'sample_index' not in entry,
                      'invalid response manufactured a verified source')
            diagnostic=entry['candidate_error'];continue
        sample=check(entry['sample_index'],source,'reference-first')
        diagnostic=json.dumps(json.loads(sample['receipt']['observations_json']).get('report',{}))[:600]
        if sample['receipt']['outcome']=='VERIFIED':verified.append(source)
    c.require(data['status']=='CONFIRMED' and len(verified)==1 and data['winner']==verified[0],
              'no independently verified shorter all-pin candidate')
    confirmation=check(len(data['samples'])-1,data['winner'],'candidate-first',True)
    c.require(data['confirmation']==confirmation and len(checked)==len(data['samples'])==data['native_processes']<=4,
              'fresh confirmation/process accounting missing')
    c.require(c.read(root/c.RUNTIME/'JLR-024.partial.json')==data,'durable iterative observations differ')
    return {'all_target_pins':1,'native_processes':len(checked),'local_inference_calls':len(data['attempts']),
      'winner_tokens':arena.reference_tokens(data['winner'],record['statement']),'promoted':False}
