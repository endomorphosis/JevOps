"""Independent protected native acceptance for the one-pin support pilot."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lean_refactor_execution_v2 as c

# These statuses mean a sealed native call did not judge the draft. They must
# not be scored as a failed shorter proof. A judged negative stays a ValueError.
_UNJUDGED_NATIVE={'BLOCKED_INCUMBENT','SCREEN_TIMEOUT','BLOCKED_NATIVE_PROFILE','RUNNING'}

def validate(root,data):
    from jevops import arena,arena_lean,arena_local,solver_feedback
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    from jevops.proof_trust import STANDARD_AXIOMS
    m=c.module(root,'lean_refactor_simp_pilot.py')
    records=c.module(root,'lean_refactor_project_readiness.py').records()
    record=next(r for r in records if r['name']==m.TARGET)
    pins=[VersionPin(tag,commit) for version in record['version_info'] for tag,commit in version.items()]
    c.require(len(pins)==1 and data['pin']==pins[0].to_dict(),'complete target pin set required')
    pin=pins[0]
    if data.get('status') in _UNJUDGED_NATIVE:
        raise c.GateWait('unjudged native result: '+data['status'])
    c.require(data['schema']==m.SCHEMA and data['target']==m.TARGET and data['status']=='CONFIRMED',
              'shorter all-pin winner is not independently confirmed')
    c.require(data['seed_sha256']==c.sha(root/m.SEED) and data['incumbent']==c.read(root/m.SEED)['source'] and
              data['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json') and
              data['original_fallback']==record['src'],'seed/baseline/original source changed')
    c.require(data['model_calls']==0 and data['training_executed'] is False and data['promoted'] is False and
              data['official_score'] is None and data['max_native_processes']==24 and data['max_candidates']==10,
              'pilot budget or authority changed')
    prior=c.read(root/c.RUNTIME/'JLR-017.result.json');ready=c.read(root/c.RUNTIME/'JLR-016.result.json')
    project=next(p for p in prior['projects'] if (p['repository'],p['lean_tag'],p['git_commit'])==
                 (record['url'],pin.lean_tag,pin.git_commit))
    binding=arena_lean.project_binding(record,pin,project,Path(ready['elan_home']))
    reader=Fingerprinter(strict=True)
    guards={order:arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=60,
              branch_order=order,fingerprinter=reader) for order in set(m.ORDER_BLOCK)}
    def sample_check(sample):
        source=sample['source'];context=sample['context']
        c.require(context['reference_source']==record['src'] and context['statement']==record['statement'] and
                  arena.intake_error(source,record['statement']) is None,'source envelope changed')
        # metric_sample binds unchanged controls. Candidate checks use the exact
        # original reference context while independently binding the edited body.
        from jevops.arena import ArenaContext,VerificationRequest
        ctx=ArenaContext(**{**context,'versions':tuple(VersionPin(**p) for p in context['versions']),
            'dependency_digests':tuple(context['dependency_digests']),'allowed_axioms':tuple(context['allowed_axioms'])})
        request=VerificationRequest(ctx,source,pin);guards[sample['branch_order']].validate_request(request)
        r=sample['receipt'];o=json.loads(r['observations_json']);p=o['report']
        c.require(r['request_id']==request.request_id and r['candidate_sha256']==arena.source_hash(source) and
                  r['target']==record['name'] and r['outcome']=='VERIFIED' and r['type_preserved'] is True and
                  r['exit_code']==0 and p['type_preserved'] is True and p['target_absent_before'] is True,
                  'native candidate source/type/target check failed')
        c.require(o['driver_sha256']==arena.source_hash(arena_lean.DRIVER.read_text()) and
                  o['measurement']==arena_lean.METHOD and o['branch_order']==sample['branch_order'] and
                  o['dependency_digest']==ctx.dependency_digests[0] and
                  o['lean_version']==pin.lean_tag.removeprefix('v'),'candidate native observation changed')
        c.require(set(p['axioms'])<=set(p['reference_axioms'])<=set(STANDARD_AXIOMS),'candidate axiom growth')
        c.require(type(p['raw_heartbeats']) is int and p['raw_heartbeats']>=0 and
                  p['heartbeats']==p['raw_heartbeats']//1000,'candidate heartbeat units')
    sample_check(data['initial'])
    c.require(data['initial']['source']==data['incumbent'],'incumbent not freshly rechecked')
    result=data['profile']
    local_guard=m.profile_verifier(binding, pin, reader)
    runtime=arena_local.ArenaLocalRuntime(local_guard,record,max_processes=0,node_budget=20000,event_budget=256)
    expected=m.profile_expected_binding(runtime, data['incumbent'], pin)
    c.require(result['ok'] is True and result['evidence_mode']=='local_lean' and result['attempted_processes']==1 and
              result['binding']==expected and result['environment']==arena.content_hash(expected),'profile source/pin drift')
    summary=arena_local._profile_summary(result['stage']['report'],result['environment'],100,20000,256)
    c.require(result['profile']==summary and data['drafts']==m.proposals(record,data['incumbent'],summary),
              'profile-guided fixed draft population changed')
    c.require(len(data['screen'])==len(data['drafts'])<=10,'candidate budget/population differs')
    for sample,draft in zip(data['screen'],data['drafts']):
        edit=solver_feedback.SolverEdit(**draft['edit'])
        c.require(edit.apply(data['incumbent'])==draft['source']==sample['source'],'edit offsets/source changed')
        if sample['receipt']['outcome']=='VERIFIED':sample_check(sample)
    eligible=[s['source'] for s in data['screen'] if s['receipt']['outcome']=='VERIFIED']
    c.require(eligible,'no verified shorter candidate')
    winner=min(eligible,key=lambda s:(arena.reference_tokens(s,record['statement']),arena.source_hash(s)))
    c.require(data['winner']==winner and arena.reference_tokens(winner,record['statement'])<
              arena.reference_tokens(data['incumbent'],record['statement']),'winner does not beat rechecked incumbent')
    schedule=[(repeat,slot,order) for repeat in range(3) for slot,order in enumerate(m.ORDER_BLOCK)]
    profile_carried=data.get('profile_carried')
    c.require(type(profile_carried) is bool,'profile carry flag required')
    bound=m.confirmation_process_bound(data['screen'],data['confirmation'],profile_carried=profile_carried)
    c.require(len(data['confirmation'])==12 and bound<=data['native_processes']<=24,
              'bounded three-repeat confirmation missing')
    for sample,(repeat,slot,order) in zip(data['confirmation'],schedule):
        c.require((sample['repetition'],sample['slot'],sample['branch_order'])==(repeat,slot,order) and
                  sample['source']==winner,'winner changed after freezing or unbalanced confirmation')
        sample_check(sample)
    c.require(c.read(root/c.RUNTIME/'JLR-019.partial.json')==data,'durable observations differ')
    return {'all_target_pins':1,'confirmed_samples':12,
            'incumbent_tokens':arena.reference_tokens(data['incumbent'],record['statement']),
            'winner_tokens':arena.reference_tokens(winner,record['statement']),'promoted':False}
