"""Source-bound support nominations remain drafts until native confirmation."""
from pathlib import Path
import inspect
import json
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_simp_pilot as m
import validate_lean_refactor_simp_pilot as v

def record():
    statement='theorem demo (n : Nat) : n + 0 = n'
    return {'statement':statement,'src':statement+' := by\n  simp only [Nat.add_zero, Nat.zero_add]\n'}

def test_actual_support_tools_generate_exact_shorter_edits_and_retain_theorem():
    r=record();drafts=m.proposals(r,r['src'],{'events':[]})
    assert len(drafts)==3
    for draft in drafts:
        edit=m.solver_feedback.SolverEdit(**draft['edit'])
        assert edit.apply(r['src'])==draft['source']
        assert draft['source'].startswith(r['statement'])
        assert m.arena.reference_tokens(draft['source'],r['statement'])<m.arena.reference_tokens(r['src'],r['statement'])

def test_stale_source_cannot_replay_support_deletion():
    r=record();draft=m.proposals(r,r['src'],{'events':[]})[0]
    with pytest.raises(ValueError):m.solver_feedback.SolverEdit(**draft['edit']).apply(r['src']+'\n')

def test_profile_hint_is_only_a_cost_prior_and_never_supplies_offsets():
    r=record();base=m.proposals(r,r['src'],{'events':[]})
    ranked=m.proposals(r,r['src'],{'events':[{'syntax_kind':'Lean.Parser.Tactic.simp',
        'hint':'simp only [Nat.add_zero, Nat.zero_add]','inclusive_raw':1000}]})
    assert [d['source'] for d in ranked]==[d['source'] for d in base]
    assert all(d['cost_prior_raw']==1000 for d in ranked)
    assert [d['edit'] for d in base]==[d['edit'] for d in ranked]

@pytest.mark.parametrize('status',['NO_SHORTER_WINNER','CONFIRMATION_FAILED'])
def test_judged_negative_cannot_complete_ticket(status):
    records=m.c.module(ROOT,'lean_refactor_project_readiness.py').records()
    target=next(r for r in records if r['name']==m.TARGET)
    pin=next(iter(target['version_info'][0].items()))
    with pytest.raises(ValueError,match='not independently confirmed') as caught:
        v.validate(ROOT,{'schema':m.SCHEMA,'target':m.TARGET,'pin':{'lean_tag':pin[0],'git_commit':pin[1]},'status':status})
    assert not isinstance(caught.value,v.c.GateWait)

@pytest.mark.parametrize('status',['SCREEN_TIMEOUT','BLOCKED_INCUMBENT','BLOCKED_NATIVE_PROFILE','RUNNING'])
def test_unjudged_native_result_waits_instead_of_failing_the_proof(status):
    records=m.c.module(ROOT,'lean_refactor_project_readiness.py').records()
    target=next(r for r in records if r['name']==m.TARGET)
    pin=next(iter(target['version_info'][0].items()))
    with pytest.raises(v.c.GateWait,match='unjudged native result: '+status):
        v.validate(ROOT,{'schema':m.SCHEMA,'target':m.TARGET,'pin':{'lean_tag':pin[0],'git_commit':pin[1]},'status':status})

def test_reviewed_extension_keeps_coupled_qualification_and_rejects_proof_edits():
    import copy
    import lean_refactor_compiled_replay_v1 as replay
    stored={'schema':'jevops.lean-refactor.canonical-compiled-frozen.v1','policy':'p','record':{'n':1},
            'drafts':[1],'pins':{'v':'c'},'original_fallback':'src','original_acceptance':'a',
            'baseline_sha256':'b','owned_audit_source_review':{},'physical_runtime_policy':'phys',
            'max_producer_native_processes':24,'max_pin_trial_seconds':780,'protected_pin_seconds':360,
            'profile_sha256':'p'*64,'proof_authority':False,'completion_authority':False,
            'scientific_sources':{'tools/lean_refactor_simp_pilot.py':'old',
                                  'tools/lean_refactor_coupled_pilot.py':'keep','jevops/lean.py':'keep'},
            'active_compiled_scientific_sources':{'tools/lean_refactor_compiled_sources_v1.json':'old'},
            'source_sha256':{'tools/lean_refactor_compiled_sources_v1.json':'old'}}
    current=copy.deepcopy(stored)
    current['scientific_sources']['tools/lean_refactor_simp_pilot.py']='new'
    current['scientific_sources']['tests/test_lean_refactor_simp_pilot.py']='new'
    current['active_compiled_scientific_sources']['tools/lean_refactor_compiled_sources_v1.json']='new'
    current['active_compiled_scientific_sources']['tools/lean_refactor_compiled_replay_v1.py']='new'
    current['source_sha256']['tools/lean_refactor_compiled_sources_v1.json']='new'
    assert replay.reviewed_extension_keeps_qualification(stored, current)
    blocked=copy.deepcopy(current)
    blocked['scientific_sources']['tools/lean_refactor_coupled_pilot.py']='changed'
    assert replay.reviewed_extension_keeps_qualification(stored, blocked) is False
    blocked=copy.deepcopy(current)
    blocked['scientific_sources']['jevops/lean.py']='changed'
    assert replay.reviewed_extension_keeps_qualification(stored, blocked) is False
    moved=copy.deepcopy(current)
    moved['profile_sha256']='q'*64
    assert replay.reviewed_extension_keeps_qualification(stored, moved)
    blocked=copy.deepcopy(moved)
    blocked['max_pin_trial_seconds']=1
    assert replay.reviewed_extension_keeps_qualification(stored, blocked) is False
    blocked=copy.deepcopy(current)
    blocked['scientific_sources']['tools/unreviewed_new.py']='x'
    assert replay.reviewed_extension_keeps_qualification(stored, blocked) is False

def test_location_narrowing_drops_only_a_trailing_wildcard():
    statement='theorem demo (n : Nat) : n + 0 = n'
    source=statement+' := by\n  simp only [Nat.add_zero, Nat.zero_add] at *\n'
    edits=m.location_edits(source)
    assert len(edits)==1 and edits[0].kind=='location-narrowing'
    narrowed=edits[0].apply(source)
    assert narrowed==statement+' := by\n  simp only [Nat.add_zero, Nat.zero_add]\n'
    assert m.arena.reference_tokens(narrowed,statement)<m.arena.reference_tokens(source,statement)
    assert m.arena.intake_error(narrowed,statement) is None
    named=statement+' := by\n  simp only [Nat.add_zero] at h\n'
    assert m.location_edits(named)==[]
    kept=m.solver_feedback.support_edits(source)
    assert kept and all('at *' in edit.replacement for edit in kept)
    assert len(m.proposals({'statement':statement,'src':source},source,{'events':[]}))<=10

def test_timeout_screen_is_not_a_negative_trial(tmp_path):
    assert m.screen_disposition([{'receipt':{'outcome':'TIMEOUT'}},{'receipt':{'outcome':'REJECTED'}}])=='SCREEN_TIMEOUT'
    assert m.screen_disposition([{'receipt':{'outcome':'REJECTED'}}])=='NO_SHORTER_WINNER'
    assert m.screen_disposition([{'receipt':{'outcome':'VERIFIED'}}]) is None
    assert m.screen_status(7, [{'receipt':{'outcome':'REJECTED'}},{'receipt':{'outcome':'TIMEOUT'}}])=='SCREEN_TIMEOUT'
    assert m.screen_status(1, [{'receipt':{'outcome':'REJECTED'}}])=='NO_SHORTER_WINNER'
    assert m.screen_status(1, [{'receipt':{'outcome':'VERIFIED'}}]) is None
    assert m.screen_status(0, [])=='NO_SHORTER_WINNER'
    assert m.timeout_retry_allowed(native_processes=4, seconds_left=120) is True
    assert m.timeout_retry_allowed(native_processes=23, seconds_left=120) is False
    assert m.timeout_retry_allowed(native_processes=4, seconds_left=60) is False
    assert m.timeout_retry_allowed(native_processes=True, seconds_left=120) is False
    runtime=tmp_path/m.c.RUNTIME
    runtime.mkdir(parents=True)
    data={'schema':m.SCHEMA,'status':'NO_SHORTER_WINNER','winner':None,'model_calls':0,'promoted':False,
          'screen':[{'receipt':{'outcome':'TIMEOUT','reason':'native_wall_timeout'}}]}
    m.c.save(runtime/'JLR-019.result.json', data)
    m.c.save(runtime/'JLR-019.receipt.json', {'schema':'jevops.lean-refactor.stage-run.v2','task_id':'JLR-019',
        'exit_code':0,'error':None})
    assert m.retain_negative_trial(tmp_path) is None
    import run_lean_refactor_stage_v2 as runner
    assert runner.simp_admission(tmp_path,'JLR-019',{'contracts':{},'source_sha256':{}},publish=False) is None
    assert not (runtime/'simp-admission-gate.json').exists()
    data['status']='SCREEN_TIMEOUT'
    data['screen']=[{'receipt':{'outcome':'REJECTED','reason':'candidate_errors'}}]
    m.c.save(runtime/'JLR-019.result.json', data)
    assert m.retain_negative_trial(tmp_path) is None
    assert runner.simp_admission(tmp_path,'JLR-019',{'contracts':{},'source_sha256':{}},publish=False) is None
    assert not (runtime/'simp-admission-gate.json').exists()

def test_carried_rejection_keeps_only_the_same_sealed_candidate_errors(tmp_path):
    runtime=tmp_path/m.c.RUNTIME
    runtime.mkdir(parents=True)
    digest='a'*64
    pin={'git_commit':'c','lean_tag':'v'}
    rejected={'source':'bad','branch_order':'reference-first','receipt':{
        'outcome':'REJECTED','reason':'candidate_errors',
        'observations_json':json.dumps({'dependency_digest':digest})}}
    data={'schema':m.SCHEMA,'incumbent':'inc','seed_sha256':'s','baseline_sha256':'b','pin':pin,'screen':[
        rejected,
        {'source':'slow','receipt':{'outcome':'TIMEOUT','reason':'native_wall_timeout','observations_json':'{}'}},
        {'source':'good','receipt':{'outcome':'VERIFIED','reason':'',
            'observations_json':json.dumps({'dependency_digest':digest})}}]}
    m.c.save(runtime/'JLR-019.result.json', data)
    kwargs=dict(incumbent='inc', seed_sha256='s', baseline_sha256='b', pin=pin, dependency_digest=digest)
    got=m.carried_rejections(tmp_path, **kwargs)
    assert list(got)==['bad'] and got['bad']['receipt']['outcome']=='REJECTED'
    assert m.carried_rejections(tmp_path, **{**kwargs, 'incumbent':'other'})=={}
    assert m.carried_rejections(tmp_path, **{**kwargs, 'dependency_digest':'b'*64})=={}
    assert m.carried_rejections(tmp_path, **{**kwargs, 'pin':{'git_commit':'c','lean_tag':'other'}})=={}
    assert m.carried_rejections(tmp_path, **{**kwargs, 'seed_sha256':'other'})=={}
    blocked=dict(data); blocked['status']='BLOCKED_INCUMBENT'; blocked['screen']=[]
    m.c.save(runtime/'JLR-019.result.json', blocked)
    assert m.carried_rejections(tmp_path, **kwargs)=={}
    archived=runtime/'runs'/('JLR-019-'+'ab'*16)/'producer'
    archived.mkdir(parents=True)
    m.c.save(archived/'stdout.json', data)
    assert list(m.carried_rejections(tmp_path, **kwargs))==['bad']
    link=runtime/'JLR-019.result.json'
    link.unlink();link.symlink_to(link.name)
    assert list(m.carried_rejections(tmp_path, **kwargs))==['bad']
    stdout=archived/'stdout.json'
    stdout.unlink();stdout.symlink_to(stdout.name)
    assert m.carried_rejections(tmp_path, **kwargs)=={}

def test_timeout_retries_spend_the_remaining_budget_on_unjudged_slots():
    screen=[{'source':'a','receipt':{'outcome':'TIMEOUT'}},
            {'source':'b','receipt':{'outcome':'REJECTED','reason':'candidate_errors'}},
            {'source':'c','receipt':{'outcome':'TIMEOUT'}}]
    calls=[]
    def allowed():
        return len(calls)<3
    def measure(source):
        calls.append(source)
        if source=='a' and calls.count('a')==2:
            return {'source':source,'receipt':{'outcome':'REJECTED','reason':'candidate_errors'}}
        return {'source':source,'receipt':{'outcome':'TIMEOUT','reason':'native_wall_timeout'}}
    updates=[]
    m.fill_timeout_retries(screen, measure, allowed, lambda: updates.append(len(calls)))
    assert calls==['a','c','a'] and screen[0]['receipt']['outcome']=='REJECTED'
    assert screen[2]['receipt']['outcome']=='TIMEOUT' and updates==[1,2,3]
    stopped=[]
    def stop(source):
        stopped.append(source);return None
    m.fill_timeout_retries([{'source':'a','receipt':{'outcome':'TIMEOUT'}}], stop, lambda: True)
    assert stopped==['a']
    assert m.fresh_screen_count([
        {'receipt':{'outcome':'REJECTED','reason':'candidate_errors'},'carried_rejection':True},
        {'receipt':{'outcome':'TIMEOUT'}}])==1
    with pytest.raises(ValueError, match='not a judged rejection'):
        m.fresh_screen_count([{'receipt':{'outcome':'VERIFIED'},'carried_rejection':True}])

def test_negative_trial_is_copied_before_a_new_strategy_overwrites_it(tmp_path):
    runtime=tmp_path/m.c.RUNTIME
    runtime.mkdir(parents=True)
    result={'schema':m.SCHEMA,'status':'NO_SHORTER_WINNER'}
    partial={'schema':m.SCHEMA,'status':'NO_SHORTER_WINNER','partial':True}
    receipt={'schema':'jevops.lean-refactor.stage-run.v2','exit_code':0,'task_id':'JLR-019'}
    for name,payload in (('JLR-019.result.json',result),('JLR-019.partial.json',partial),('JLR-019.receipt.json',receipt)):
        m.c.atomic(runtime/name, json.dumps(payload))
    retained=m.retain_negative_trial(tmp_path)
    assert retained['status']=='NO_SHORTER_WINNER' and retained['stage_run_exit_code']==0
    dest=tmp_path/retained['path']
    assert (dest/'JLR-019.result.json').read_text()==(runtime/'JLR-019.result.json').read_text()
    again=m.retain_negative_trial(tmp_path)
    assert again['result_sha256']==retained['result_sha256']
    assert (dest/'JLR-019.receipt.json').read_text()==(runtime/'JLR-019.receipt.json').read_text()

def test_incumbent_timeouts_use_the_remaining_sealed_budget():
    calls=[]
    def measure():
        calls.append(len(calls))
        if len(calls)<3:
            return {'receipt':{'outcome':'TIMEOUT','reason':'native_wall_timeout'}}
        return {'receipt':{'outcome':'VERIFIED'}}
    got=m.retry_unjudged(measure, lambda: len(calls)<5)
    assert [item['receipt']['outcome'] for item in [got]]==['VERIFIED'] and calls==[0,1,2]
    calls.clear()
    def always_timeout():
        calls.append(len(calls))
        return {'receipt':{'outcome':'TIMEOUT'}}
    got=m.retry_unjudged(always_timeout, lambda: len(calls)<3)
    assert calls==[0,1,2] and got['receipt']['outcome']=='TIMEOUT'
    seq=iter([{'receipt':{'outcome':'TIMEOUT'}}, None])
    got=m.retry_unjudged(lambda: next(seq), lambda: True)
    assert got['receipt']['outcome']=='TIMEOUT'
    assert m.retry_unjudged(lambda: None, lambda: True) is None
    with pytest.raises(ValueError, match='retry sample required'):
        m.retry_unjudged(iter([{'receipt':{'outcome':'TIMEOUT'}}, {'receipt':None}]).__next__, lambda: True)

def test_verified_slots_carry_and_timeouts_stay_unjudged(tmp_path):
    verified={'receipt':{'outcome':'VERIFIED'},'carried_verification':True}
    rejected={'receipt':{'outcome':'REJECTED','reason':'candidate_errors'},'carried_rejection':True}
    assert m.fresh_screen_count([rejected, verified, {'receipt':{'outcome':'TIMEOUT'}}])==1
    with pytest.raises(ValueError, match='not verified'):
        m.fresh_screen_count([{'receipt':{'outcome':'TIMEOUT'},'carried_verification':True}])
    with pytest.raises(ValueError, match='both flags'):
        m.fresh_screen_count([{'receipt':{'outcome':'VERIFIED'},'carried_verification':True,'carried_rejection':True}])
    slots=[{'receipt':{'outcome':'VERIFIED'},'carried_verification':True} for _ in range(10)]
    slots.append({'receipt':{'outcome':'TIMEOUT'}})
    slots.append({'receipt':{'outcome':'VERIFIED'}})
    assert m.confirmation_status(slots)=='SCREEN_TIMEOUT'
    slots[-2]={'receipt':{'outcome':'REJECTED','reason':'candidate_errors'}}
    assert m.confirmation_status(slots)=='CONFIRMATION_FAILED'
    slots[-2]={'receipt':{'outcome':'VERIFIED'}}
    assert m.confirmation_status(slots) is None
    assert m.confirmation_process_bound([rejected, verified], slots, profile_carried=True)==3
    assert m.confirmation_process_bound(
        [{'receipt':{'outcome':'VERIFIED'}}],
        [{'receipt':{'outcome':'VERIFIED'}} for _ in range(12)],
        profile_carried=False)==15
    runtime=tmp_path/m.c.RUNTIME
    runtime.mkdir(parents=True)
    digest='a'*64
    pin={'git_commit':'c','lean_tag':'v'}
    obs=json.dumps({'dependency_digest':digest})
    verified_screen={'source':'short','receipt':{'outcome':'VERIFIED','observations_json':obs}}
    data={'schema':m.SCHEMA,'incumbent':'inc','seed_sha256':'s','baseline_sha256':'b','pin':pin,
        'initial':{'source':'inc','receipt':{'outcome':'VERIFIED','observations_json':obs}},
        'profile':{'ok':True,'attempted_processes':1,'profile':{'events':[]}},
        'screen':[verified_screen, {'source':'bad','receipt':{'outcome':'REJECTED','reason':'candidate_errors','observations_json':obs}}],
        'confirmation':[
            {'source':'short','repetition':0,'slot':0,'branch_order':'reference-first',
             'receipt':{'outcome':'VERIFIED','observations_json':obs}},
            {'source':'short','repetition':0,'slot':1,'branch_order':'candidate-first',
             'receipt':{'outcome':'TIMEOUT','reason':'native_wall_timeout','observations_json':'{}'}}]}
    kwargs=dict(incumbent='inc', seed_sha256='s', baseline_sha256='b', pin=pin, dependency_digest=digest)
    m.c.save(runtime/'JLR-019.result.json', data)
    got=m.carried_verified_work(tmp_path, **kwargs)
    assert list(got['screens'])==['short'] and got['profile']['ok'] is True
    assert list(got['confirmations'])==[('short',0,0,'reference-first')]
    assert m.carried_verified_work(tmp_path, **{**kwargs, 'dependency_digest':'b'*64})['profile'] is None
    older=dict(data); older['screen']=[{'source':'stale','receipt':{'outcome':'VERIFIED','observations_json':obs}}]
    older['profile']={'ok':True,'attempted_processes':1,'profile':{'events':[{'stale':True}]}}
    archived=runtime/'runs'/('JLR-019-'+'cd'*16)/'producer'
    archived.mkdir(parents=True)
    m.c.save(archived/'stdout.json', older)
    got=m.carried_verified_work(tmp_path, **kwargs)
    assert got['screens']['short']['receipt']['outcome']=='VERIFIED'
    assert got['profile']['profile']=={'events':[]}

def test_profile_verifier_uses_the_profile_budget_not_the_proof_cap(monkeypatch):
    seen={}
    def fake(bindings, *, max_processes, timeout, fingerprinter):
        seen.update(timeout=timeout, max_processes=max_processes, fingerprinter=fingerprinter)
        return {"bindings": bindings}
    monkeypatch.setattr(m.arena_lean, "NativeLeanVerifier", fake)
    got=m.profile_verifier("binding", "pin", "reader")
    assert seen["timeout"]==m.PROFILE_TIMEOUT==180
    assert seen["max_processes"]==0 and seen["fingerprinter"]=="reader"
    assert got["bindings"]=={"pin": "binding"}
    assert "m.profile_verifier" in inspect.getsource(v.validate)

def test_stale_profile_binding_is_not_reused():
    class _Runtime:
        class context:
            context_id='b'*64
        def _origin(self, pin):
            return {'context_id':self.context.context_id,'pin':pin}
    expected=m.profile_expected_binding(_Runtime(), 'theorem demo', 'v4.26.0')
    assert expected['context_id']=='b'*64
    assert expected['origin']['projection']=='builtin-tactic-traces/v1'
    assert expected['source_sha256']==m.arena.source_hash('theorem demo')
    assert expected['threshold_raw']==100 and expected['node_budget']==20000 and expected['event_budget']==256
    profile={'ok':True,'binding':json.loads(json.dumps(expected)),'environment':m.arena.content_hash(expected)}
    assert m.profile_still_bound(profile, expected) is True
    drifted=json.loads(json.dumps(profile))
    drifted['binding']['context_id']='c'*64
    drifted['binding']['origin']['context_id']='c'*64
    drifted['environment']=m.arena.content_hash(drifted['binding'])
    assert m.profile_still_bound(drifted, expected) is False
    stale_env=json.loads(json.dumps(profile))
    stale_env['environment']='d'*64
    assert m.profile_still_bound(stale_env, expected) is False
    assert m.profile_still_bound({'binding':expected}, expected) is False
    assert m.profile_still_bound(None, expected) is False
