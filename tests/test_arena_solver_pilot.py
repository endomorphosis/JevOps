"""Pilot orchestration uses manufactured native transport, never real Lean."""
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import sys

import pytest

from jevops import arena_solver_pilot as pilot, arena_lean as native
from jevops.arena import content_hash
from jevops.arena_trial import Candidate
from jevops.lean import VersionPin
from tests.test_arena_solver import ROOT, MID, END, PIN, STATEMENT, message

RECORD = dict(name='solver_control', statement=STATEMENT, src=ROOT,
              version_info=[{PIN.lean_tag:PIN.git_commit}])


@pytest.fixture
def transport(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(native.ProjectBinding, 'fingerprint', lambda *_:content_hash('pilot fixture'))
    def runner(binding, payload, **kwargs):
        calls.append(payload)
        base = payload['candidate'].replace('simp?', 'simp')
        outcome = 'VERIFIED' if base in (ROOT,MID,END) else 'REJECTED'
        raw = {ROOT:10000,MID:7000,END:4000}.get(base,10000)
        diagnostics = [message('simp only [Nat.add_zero, Nat.zero_add]')] if base==ROOT and 'simp?' in payload['candidate'] else []
        return dict(schema='jevops-native-arena/v1', request_id=payload['request_id'],
            target=payload['target'], measurement=native.METHOD,
            lean_version=binding.pin.lean_tag[1:], lean_githash='b'*40,
            branch_order='candidate-first' if payload['candidate_first'] else 'reference-first',
            report=dict(outcome=outcome, type_preserved=True,target_absent_before=True,
                axioms=[],reference_axioms=[],raw_heartbeats=raw,heartbeats=raw//1000,
                reference_raw_heartbeats=10000,reference_heartbeats=10,diagnostics=diagnostics)),0
    monkeypatch.setattr(native,'run_native',runner)
    bindings = {PIN:native.ProjectBinding(PIN,tmp_path/'lean',tmp_path,'',project_backed=False)}
    return bindings,calls,runner


def execute(tmp_path, transport, **kwargs):
    bindings, _, _ = transport
    plan = pilot.make_plan(RECORD)
    return pilot.run_pilot(plan,bindings=bindings,directory=tmp_path/'run',max_processes=53,
        check_resources=kwargs.pop('check_resources',lambda:None),evidence_mode='offline_fixture',**kwargs)


def test_plan_matches_full_budget_and_fixed_comparison():
    plan = pilot.make_plan(RECORD)
    assert plan['control_ceiling']==1 and plan['discovery_ceiling']==24
    assert plan['selection_ceiling']==28 and plan['max_processes']==53
    assert plan['limits']['max_calls']==8 and plan['limits']['max_drafts']==1
    assert plan['modes']==['suggestions-v1','minimize-v1','frontier-v1']
    assert plan['selection']['selection_objective']=='strict-dual-v1'
    assert plan['selection']['heartbeat_noise_floor_raw']==100
    assert plan['selection']['repetitions']==2 and plan['selection']['confirmation_repetitions']==3
    assert plan==pilot.make_plan(RECORD)
    changed=pilot.make_plan(RECORD,Candidate('external-label',MID,'untrusted nomination'))
    assert changed['max_processes']==64 and changed['plan_id']!=plan['plan_id']
    assert pilot._incumbent(RECORD,Candidate('solver-0',MID,'seed')).label=='incumbent'
    assert not plan['promoted'] and plan['official_score'] is None


@pytest.mark.parametrize('damage',['zero','partial','bool','plan','missing_pin','foreign_pin','mode'])
def test_invalid_plan_or_budget_never_launches(transport,tmp_path,damage):
    bindings,calls,_=transport
    plan=pilot.make_plan(RECORD);budget=53;mode='offline_fixture'
    if damage=='zero':budget=0
    elif damage=='partial':budget=52
    elif damage=='bool':budget=True
    elif damage=='plan':plan['limits']['max_calls']=9
    elif damage=='missing_pin':bindings={}
    elif damage=='foreign_pin':bindings={VersionPin('v4.27.0','b'*40):next(iter(bindings.values()))}
    else:mode='mock_is_live'
    with pytest.raises(ValueError):
        pilot.run_pilot(plan,bindings=bindings,directory=tmp_path/'run',max_processes=budget,
                        check_resources=lambda:pytest.fail('invalid preflight'),evidence_mode=mode)
    assert not calls and not (tmp_path/'run').exists()


def test_full_fixture_pipeline_preserves_drafts_and_fresh_confirmation(tmp_path,transport):
    r=execute(tmp_path,transport)
    assert r['status']=='FIXTURE_CONFIRMED' and r['recommended'] is None
    assert r['arms']['suggestions-v1']['draft_count']==r['arms']['minimize-v1']['draft_count']==0
    assert r['arms']['frontier-v1']['draft_count']==1 and r['drafts'][0]['source']==END
    selection=json.loads((tmp_path/'run/selection.json').read_text())
    assert selection['status']=='FIXTURE_CONFIRMED' and selection['verifier_invocations']==20
    assert selection['confirmation'] and not selection['confirmation']['receipt_cache_enabled']
    assert r['native_processes']==0 and r['adapter_process_invocations']==len(transport[1])
    assert r['reserved_processes']==sum(c['units'] for c in r['reservations'])==45<=53
    assert not r['promoted'] and r['official_score'] is None
    assert r['models_called']==0 and r['selection']=='selection.json'
    assert set(json.loads((tmp_path/'run/solver-0.json').read_text()))=={'name','label','source','provenance'}
    assert json.loads((tmp_path/'run/report.json').read_text())==r
    before=len(transport[1])
    with pytest.raises(FileExistsError):execute(tmp_path,transport)
    assert len(transport[1])==before


def test_failed_control_stops_every_search_arm(tmp_path,transport,monkeypatch):
    def reject(*a,**kw):
        data,code=transport[2](*a,**kw)
        data['report']['outcome']='REJECTED'
        return data,code
    monkeypatch.setattr(native,'run_native',reject)
    r=execute(tmp_path,transport)
    assert r['status']=='INCOMPLETE' and r['reason']=='reference_or_incumbent_control_failed'
    assert r['adapter_process_invocations']==r['reserved_processes']==1
    assert not r['arms'] and r['selection'] is None


def test_transient_query_failure_is_not_removed_from_denominator(tmp_path,transport,monkeypatch):
    def timeout(binding,payload,**kw):
        data,code=transport[2](binding,payload,**kw)
        if 'simp?' in payload['candidate']:data['report']['outcome']='TIMEOUT'
        return data,code
    monkeypatch.setattr(native,'run_native',timeout)
    r=execute(tmp_path,transport)
    assert r['status']=='INCOMPLETE' and len(r['arms'])==3
    assert all(a['status']=='TIMEOUT' for a in r['arms'].values())
    assert not r['drafts'] and r['selection'] is None and r['recommended'] is None


def test_resource_failure_does_not_borrow_confirmation_reserve(tmp_path,transport):
    checks=0
    def resources():
        nonlocal checks
        checks+=1
        if checks==3:raise RuntimeError('fixture disk reserve')
    r=execute(tmp_path,transport,check_resources=resources)
    assert r['status']=='INCOMPLETE' and 'disk reserve' in r['reason']
    assert r['reserved_processes']==r['adapter_process_invocations']==1


def test_no_draft_uses_no_selection_calls(tmp_path,transport,monkeypatch):
    def no_hint(*a,**kw):
        data,code=transport[2](*a,**kw)
        data['report']['diagnostics']=[]
        return data,code
    monkeypatch.setattr(native,'run_native',no_hint)
    r=execute(tmp_path,transport)
    assert r['status']=='NO_CANDIDATE' and r['selection'] is None
    assert r['reserved_processes']==25 and r['adapter_process_invocations']==7


def test_owned_plan_survives_caller_mutation(tmp_path,transport):
    plan=pilot.make_plan(RECORD)
    def mutate():plan['record']['name']='changed by caller'
    r=pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'run',max_processes=53,
        check_resources=mutate,evidence_mode='offline_fixture')
    assert r['status']=='FIXTURE_CONFIRMED'
    stored=json.loads((tmp_path/'run/plan.json').read_text())
    assert stored['record']['name']=='solver_control'


def test_cli_is_plan_only_without_native_or_provisioning(monkeypatch,capsys):
    name='Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema'
    monkeypatch.setattr(sys,'argv',['pilot','--problem',name])
    monkeypatch.setattr(pilot,'NativeLeanVerifier',lambda *a,**k:pytest.fail('plan cannot run Lean'))
    monkeypatch.setattr(pilot,'exclusive',lambda *a,**k:pytest.fail('plan cannot acquire preparation lock'))
    assert pilot.main()==0
    assert json.loads(capsys.readouterr().out)['max_processes']==53


def test_balanced_profile_has_matched_limits_and_reserved_confirmation(tmp_path,transport):
    plan=pilot.make_plan(RECORD,comparison='balanced-v1')
    assert plan['modes']==['frontier-v1','balanced-frontier-v1']
    assert plan['nomination_policy']=='discovery-dual-first-v1'
    assert plan['control_ceiling']==1 and plan['discovery_ceiling']==16
    assert plan['selection_ceiling']==24 and plan['max_processes']==41
    assert plan['limits']==pilot.make_plan(RECORD)['limits']
    r=pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'balanced',max_processes=41,
        check_resources=lambda:None,evidence_mode='offline_fixture')
    assert r['status']=='FIXTURE_CONFIRMED' and r['recommended'] is None
    assert r['reserved_processes']==37 and len(r['drafts'])==1
    assert list(r['draft_origins'].values())==[plan['modes']]
    for mode in plan['modes']:
        discovery=json.loads((tmp_path/f'balanced/discovery-{mode}.json').read_text())
        assert discovery['plan']['limits']==plan['limits']
        assert discovery['plan']['draft_policy']==plan['nomination_policy']
    assert r['native_processes']==0 and r['adapter_process_invocations']==len(transport[1])
    assert not r['promoted']


def test_comparison_and_nomination_are_frozen_before_work(tmp_path,transport):
    with pytest.raises(ValueError):pilot.make_plan(RECORD,comparison='adaptive-after-results')
    plan=pilot.make_plan(RECORD,comparison='balanced-v1')
    plan['nomination_policy']='shortest-v1'
    with pytest.raises(ValueError,match='mutated or stale'):
        pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'mutated',max_processes=41,
            check_resources=lambda:pytest.fail('invalid protocol'),evidence_mode='offline_fixture')
    assert not transport[1]


def test_balanced_cli_is_also_plan_only(monkeypatch,capsys):
    name='Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema'
    monkeypatch.setattr(sys,'argv',['pilot','--problem',name,'--comparison','balanced-v1'])
    monkeypatch.setattr(pilot,'NativeLeanVerifier',lambda *a,**k:pytest.fail('plan cannot run Lean'))
    assert pilot.main()==0
    plan=json.loads(capsys.readouterr().out)
    assert plan['comparison']=='balanced-v1' and plan['max_processes']==41


def test_archived_physlib_result_is_a_tradeoff_not_a_win(monkeypatch):
    """Historical bookkeeping only; cannot supply fresh admission or costs."""
    monkeypatch.setattr(native,'run_native',lambda *a,**kw:pytest.fail('archive is not a native run'))
    base=Path(__file__).resolve().parents[1]/'papers/completion/lean_refactor_arena/evidence/solver-specialization-pilot-2026-09-24'
    plan=json.loads((base/'plan.json').read_text())
    report=json.loads((base/'report.json').read_text())
    selection=json.loads((base/'selection.json').read_text())
    assert plan['plan_id']==report['plan_id']==content_hash({k:v for k,v in plan.items() if k!='plan_id'})
    assert report['status']==selection['status']=='NO_IMPROVEMENT'
    assert report['native_processes']==report['adapter_process_invocations']==28
    assert report['reserved_processes']==sum(r['units'] for r in report['reservations'])==45
    assert report['max_processes']==53 and not report['promoted'] and report['recommended'] is None
    assert selection['native_processes']==8 and selection['confirmation'] is None
    assert selection['retained_incumbent_verified'] and selection['recommended'] is None
    rows=selection['screen_analysis']['rows']
    assert rows['control']['tokens']==1372 and rows['solver-0']['tokens']==1365
    for original,draft in zip(rows['control']['raw_heartbeats_by_stratum'],rows['solver-0']['raw_heartbeats_by_stratum']):
        assert len(original)==len(draft)==2 and max(original)<min(draft)
    assert all(s['status']=='VERIFIED' for s in selection['screen']['samples'])
    assert not (base/'confirm-phase.json').exists()
    audit=json.loads((base/'audit/audit.json').read_text())
    assert audit['status']=='CONSISTENT' and not audit['proof_verified']


def test_archived_balanced_pilot_preserves_intermediate_not_a_strict_win(monkeypatch):
    monkeypatch.setattr(native,'run_native',lambda *a,**kw:pytest.fail('historical archive only'))
    base=Path(__file__).resolve().parents[1]/'papers/completion/lean_refactor_arena/evidence/solver-balanced-pilot-2026-09-24'
    plan=json.loads((base/'plan.json').read_text())
    r=json.loads((base/'report.json').read_text())
    balanced=json.loads((base/'discovery-balanced-frontier-v1.json').read_text())
    old=json.loads((base/'discovery-frontier-v1.json').read_text())
    assert plan['plan_id']==r['plan_id']==content_hash({k:v for k,v in plan.items() if k!='plan_id'})
    assert plan['comparison']=='balanced-v1' and plan['max_processes']==41
    assert r['status']=='NO_IMPROVEMENT' and r['native_processes']==25
    assert r['reserved_processes']==sum(x['units'] for x in r['reservations'])==37
    assert not r['promoted'] and r['recommended'] is None
    assert balanced['verifier_calls']==old['verifier_calls']==8
    assert balanced['plan']['draft_policy']==old['plan']['draft_policy']=='discovery-dual-first-v1'
    root, _, hint=balanced['frontier']
    assert (root['tokens'],root['raw_heartbeats'])==(1372,27475681)
    assert (hint['tokens'],hint['raw_heartbeats'])==(1377,25104564)
    assert hint['tokens']>root['tokens'] and hint['raw_heartbeats']<root['raw_heartbeats']
    assert balanced['attempts'][hint['attempt']]['receipt']['outcome']=='VERIFIED'
    assert balanced['attempts'][5]['receipt']['outcome']=='REJECTED'
    assert balanced['attempts'][5]['receipt']['reason']=='candidate_errors'
    assert all(n['attempt']!=5 for n in balanced['frontier'])
    followup=json.loads((base/'followup-longer-intermediate.json').read_text())
    assert followup['source']==hint['source'] and set(followup)=={'name','label','source','provenance'}
    assert balanced['drafts'][0]['source']==old['drafts'][0]['source']!=hint['source']
    selected=json.loads((base/'selection.json').read_text())
    assert selected['status']=='NO_IMPROVEMENT' and selected['native_processes']==8
    assert selected['confirmation'] is None and selected['retained_incumbent_verified']
    assert all(s['status']=='VERIFIED' for s in selected['screen']['samples'])
    binding=json.loads((base/'source-binding.json').read_text())
    assert binding['before']==binding['after'] and binding['before']['status']=='UNCHANGED'
    audit=json.loads((base/'audit/audit.json').read_text())
    assert audit['status']=='CONSISTENT' and not audit['proof_verified']


def test_aggregate_nomination_plan_varies_only_final_policy():
    plan=pilot.make_plan(RECORD,comparison='aggregate-nomination-v1')
    assert plan['modes']==['balanced-frontier-v1']*2
    assert plan['nomination_policy'] is None
    assert plan['discovery_arms']==[
        dict(label='dual-first',mode='balanced-frontier-v1',draft_policy='discovery-dual-first-v1'),
        dict(label='aggregate',mode='balanced-frontier-v1',draft_policy='discovery-aggregate-v1')]
    assert plan['selection']['selection_objective']=='aggregate-local-v1'
    assert plan['max_processes']==41 and plan['discovery_ceiling']==16
    assert plan['limits']==pilot.make_plan(RECORD)['limits']
    incumbent=pilot.make_plan(RECORD,Candidate('seed',MID,'fixture'),comparison='aggregate-nomination-v1')
    assert incumbent['control_ceiling']==2 and incumbent['selection_ceiling']==34
    assert incumbent['max_processes']==52
    assert pilot.make_plan(RECORD)['selection']['selection_objective']=='strict-dual-v1'
    assert pilot.make_plan(RECORD,comparison='balanced-v1')['selection']['selection_objective']=='strict-dual-v1'


def test_aggregate_pilot_can_nominate_longer_proof_without_legacy_nominee(tmp_path,transport,monkeypatch):
    def longer_only(binding,payload,**kw):
        data,code=transport[2](binding,payload,**kw)
        if payload['candidate'].replace('simp?','simp')==END:
            data['report']['outcome']='REJECTED'
        return data,code
    monkeypatch.setattr(native,'run_native',longer_only)
    plan=pilot.make_plan(RECORD,comparison='aggregate-nomination-v1')
    r=pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'aggregate',max_processes=41,
        check_resources=lambda:None,evidence_mode='offline_fixture')
    assert r['status']=='FIXTURE_CONFIRMED' and r['recommended'] is None
    assert r['arms']['dual-first']['draft_count']==0 and r['arms']['aggregate']['draft_count']==1
    assert r['drafts'][0]['source']==MID and list(r['draft_origins'].values())==[['aggregate']]
    old=json.loads((tmp_path/'aggregate/discovery-dual-first.json').read_text())
    new=json.loads((tmp_path/'aggregate/discovery-aggregate.json').read_text())
    assert old['frontier']==new['frontier']
    assert old['verifier_calls']==new['verifier_calls']<=8
    # Fresh receipts may have different wall-time observations. Compare the
    # actual work and semantic outcomes, not full transport metadata.
    def work(rows):
        return [(a['kind'],a['source_sha256'],a['receipt']['request_id'],
                 a['receipt']['outcome'],a['receipt']['heartbeats']) for a in rows]
    assert work(old['attempts'])==work(new['attempts'])
    selection=json.loads((tmp_path/'aggregate/selection.json').read_text())
    assert selection['plan']['selection_objective']=='aggregate-local-v1'
    assert selection['verifier_invocations']==20 and selection['confirmation']
    assert not selection['confirmation']['receipt_cache_enabled']
    assert r['adapter_process_invocations']==len(transport[1])
    assert r['native_processes']==0 and not r['promoted'] and r['official_score'] is None


def test_aggregate_pilot_deduplicates_shared_nominees_and_freshly_checks_incumbent(tmp_path,transport):
    plan=pilot.make_plan(RECORD,Candidate('seed',MID,'fixture seed'),comparison='aggregate-nomination-v1')
    r=pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'incumbent',max_processes=52,
        check_resources=lambda:None,evidence_mode='offline_fixture')
    assert len(r['controls'])==2
    assert r['drafts'][0]['source']==END and len(r['drafts'])==1
    assert list(r['draft_origins'].values())==[['dual-first','aggregate']]
    selected=json.loads((tmp_path/'incumbent/selection.json').read_text())
    assert selected['status']=='FIXTURE_CONFIRMED'
    assert selected['plan']['incumbent_label']=='incumbent'
    assert set(selected['screen_analysis']['rows'])=={'control','incumbent','solver-0'}
    assert selected['verifier_invocations']==30
    assert r['reserved_processes']==48<=52
    assert all(r[p] is None for p in ('recommended','official_score','measured_api_cost'))


@pytest.mark.parametrize('damage',['budget','arm_policy','arm_mode','label','objective'])
def test_aggregate_protocol_mutation_or_partial_reserve_fails_before_work(tmp_path,transport,damage):
    plan=pilot.make_plan(RECORD,comparison='aggregate-nomination-v1');budget=41
    if damage=='budget':budget=40
    elif damage=='arm_policy':plan['discovery_arms'][0]['draft_policy']='discovery-aggregate-v1'
    elif damage=='arm_mode':plan['discovery_arms'][1]['mode']='frontier-v1'
    elif damage=='label':plan['discovery_arms'][1]['label']='dual-first'
    else:plan['selection']['selection_objective']='strict-dual-v1'
    with pytest.raises(ValueError):
        pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'mutated-aggregate',max_processes=budget,
            check_resources=lambda:pytest.fail('invalid preflight'),evidence_mode='offline_fixture')
    assert not transport[1]


def test_aggregate_cli_stays_plan_only_and_records_equal_search(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['pilot','--problem','CallElimCorrect.extractedOldExprInVars',
                                 '--comparison','aggregate-nomination-v1'])
    monkeypatch.setattr(pilot,'NativeLeanVerifier',lambda *a,**k:pytest.fail('no native work'))
    monkeypatch.setattr(pilot,'exclusive',lambda *a,**k:pytest.fail('no lock in planning'))
    assert pilot.main()==0
    plan=json.loads(capsys.readouterr().out)
    assert plan['max_processes']==41
    assert plan['selection']['selection_objective']=='aggregate-local-v1'


def test_one_failed_nomination_arm_is_not_dropped_to_claim_a_win(tmp_path,transport,monkeypatch):
    failed=False
    def one_timeout(binding,payload,**kw):
        nonlocal failed
        data,code=transport[2](binding,payload,**kw)
        if not failed and 'simp?' in payload['candidate']:
            failed=True
            data['report']['outcome']='TIMEOUT'
        return data,code
    monkeypatch.setattr(native,'run_native',one_timeout)
    plan=pilot.make_plan(RECORD,comparison='aggregate-nomination-v1')
    r=pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'partial',max_processes=41,
        check_resources=lambda:None,evidence_mode='offline_fixture')
    assert r['status']=='INCOMPLETE' and r['selection'] is None and r['recommended'] is None
    assert r['arms']['dual-first']['status']=='TIMEOUT'
    assert r['arms']['aggregate']['draft_count']==1
    assert not (tmp_path/'partial/selection.json').exists()


def test_aggregate_no_nominee_is_explicit_and_does_not_spend_confirmation(tmp_path,transport,monkeypatch):
    def no_hint(*a,**kw):
        data,code=transport[2](*a,**kw)
        data['report']['diagnostics']=[]
        return data,code
    monkeypatch.setattr(native,'run_native',no_hint)
    plan=pilot.make_plan(RECORD,comparison='aggregate-nomination-v1')
    r=pilot.run_pilot(plan,bindings=transport[0],directory=tmp_path/'empty',max_processes=41,
        check_resources=lambda:None,evidence_mode='offline_fixture')
    assert r['status']=='NO_CANDIDATE' and r['reason']=='bounded_discovery_no_eligible_draft'
    assert r['reserved_processes']==17 and r['selection'] is None
    assert r['drafts']==[] and r['recommended'] is None
    assert not (tmp_path/'empty/selection-plan.json').exists()


def test_prefix_reference_profile_uses_one_bounded_original_normalized_arm(tmp_path,transport):
    seed = Candidate('seed', MID, 'untrusted fixture draft')
    plan = pilot.make_plan(RECORD, seed, comparison='prefix-reference-v1')
    assert plan['control_ceiling'] == 2 and plan['discovery_ceiling'] == 16
    assert plan['selection_ceiling'] == 30 and plan['max_processes'] == 48
    assert plan['limits'] == dict(max_calls=16, max_states=4, max_depth=2, max_sites=1,
        max_proposals=128, max_source_bytes=65536, max_frontier_bytes=262144, max_drafts=1)
    assert plan['nomination_policy'] == 'discovery-reference-v1'
    assert plan['selection']['selection_objective'] == 'aggregate-local-v1'
    assert not plan['matched_discovery_call_ceiling']
    assert len(plan['discovery_arms']) == 1
    r = pilot.run_pilot(plan, bindings=transport[0], directory=tmp_path/'prefix', max_processes=48,
        check_resources=lambda:None, evidence_mode='offline_fixture')
    assert r['status'] == 'FIXTURE_CONFIRMED' and r['recommended'] is None
    assert list(r['arms']) == ['prefix-reference'] and r['drafts'][0]['source'] == END
    d = json.loads((tmp_path/'prefix/discovery-prefix-reference.json').read_text())
    assert d['nomination']['reference_raw_heartbeats'] == 10000
    assert d['plan']['limits']['max_sites'] == 1
    selected = json.loads((tmp_path/'prefix/selection.json').read_text())
    assert selected['verifier_invocations'] == 30 and selected['confirmation']
    assert not selected['confirmation']['receipt_cache_enabled']
    assert set(selected['screen_analysis']['rows']) == {'control', 'incumbent', 'solver-0'}
    assert r['native_processes'] == 0 and r['adapter_process_invocations'] == len(transport[1])
    assert not r['promoted'] and r['official_score'] is None


def test_prefix_reference_can_keep_longer_draft(tmp_path,transport,monkeypatch):
    def longer_only(*a, **kw):
        data, code = transport[2](*a, **kw)
        if a[1]['candidate'].replace('simp?', 'simp') == END:
            data['report']['outcome'] = 'REJECTED'
        return data, code
    monkeypatch.setattr(native, 'run_native', longer_only)
    plan = pilot.make_plan(RECORD, comparison='prefix-reference-v1')
    assert plan['max_processes'] == 37
    r = pilot.run_pilot(plan, bindings=transport[0], directory=tmp_path/'longer', max_processes=37,
        check_resources=lambda:None, evidence_mode='offline_fixture')
    assert r['status'] == 'FIXTURE_CONFIRMED' and r['drafts'][0]['source'] == MID


@pytest.mark.parametrize('damage', ['sites', 'policy', 'objective', 'budget'])
def test_prefix_reference_cannot_expand_after_freezing(tmp_path,transport,damage):
    plan = pilot.make_plan(RECORD, comparison='prefix-reference-v1'); budget = 37
    if damage == 'sites': plan['limits']['max_sites'] = 2
    elif damage == 'policy': plan['discovery_arms'][0]['draft_policy'] = 'discovery-aggregate-v1'
    elif damage == 'objective': plan['selection']['selection_objective'] = 'strict-dual-v1'
    else: budget -= 1
    with pytest.raises(ValueError):
        pilot.run_pilot(plan, bindings=transport[0], directory=tmp_path/'mutated-prefix', max_processes=budget,
            check_resources=lambda:pytest.fail('invalid protocol'), evidence_mode='offline_fixture')
    assert not transport[1]


def test_prefix_reference_cli_only_plans(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['pilot','--problem','CallElimCorrect.extractedOldExprInVars',
                                 '--comparison','prefix-reference-v1'])
    monkeypatch.setattr(pilot,'NativeLeanVerifier',lambda *a,**k:pytest.fail('no native work'))
    monkeypatch.setattr(pilot,'exclusive',lambda *a,**k:pytest.fail('no lock in planning'))
    assert pilot.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['max_processes'] == 37 and plan['limits']['max_sites'] == 1


def test_archived_strata_comparison_is_a_neutral_discovery_result(monkeypatch):
    monkeypatch.setattr(native,'run_native',lambda *a,**kw:pytest.fail('historical data only'))
    base=Path(__file__).resolve().parents[1]/'papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24'
    plan=json.loads((base/'plan.json').read_text())
    r=json.loads((base/'report.json').read_text())
    assert plan['plan_id']==r['plan_id']==content_hash({k:v for k,v in plan.items() if k!='plan_id'})
    assert r['status']=='NO_CANDIDATE' and r['selection'] is None and not r['drafts']
    assert r['native_processes']==r['adapter_process_invocations']==r['reserved_processes']==18
    assert sum(x['units'] for x in r['reservations'])==18 and r['max_processes']==52
    assert len(r['controls'])==2 and all(c['receipt']['outcome']=='VERIFIED' for c in r['controls'])
    assert r['recommended'] is None and r['official_score'] is None and not r['promoted']
    work=[]
    for label in ('dual-first','aggregate'):
        d=json.loads((base/f'discovery-{label}.json').read_text())
        assert d['status']=='BUDGET_EXHAUSTED' and d['verifier_calls']==8 and not d['drafts']
        assert d['cache_hits']==0 and not d['proof_admitted']
        seed,candidate=d['frontier']
        assert (seed['tokens'],candidate['tokens'])==(185,197)
        assert candidate['raw_heartbeats']<seed['raw_heartbeats']
        gain=(Fraction(seed['tokens']-candidate['tokens'],seed['tokens'])
              + Fraction(seed['raw_heartbeats']-candidate['raw_heartbeats'],seed['raw_heartbeats']))
        assert gain<0
        work.append([(a['kind'],a['source_sha256'],a['receipt']['outcome']) for a in d['attempts']])
    assert work[0]==work[1]
    assert not (base/'selection.json').exists() and not (base/'confirm-phase.json').exists()
    binding=json.loads((base/'source-binding.json').read_text())
    assert binding['before']==binding['after'] and binding['before']['status']=='UNCHANGED'


def test_archived_multiline_rejections_reproduce_the_source_span_diagnostic():
    # Reconstruct historical edits only: this records a diagnosed limitation,
    # not a requirement that future query/edit implementations keep that bug.
    from jevops.solver_feedback import SolverEdit, source_digest
    base=Path(__file__).resolve().parents[1]/'papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24'
    d=json.loads((base/'discovery-aggregate.json').read_text())
    source=d['frontier'][0]['source']
    bad=[e['edit'] for e in d['edits'] if e['parent']==0 and not e['retained']
         and e['edit']['kind']=='solver-suggestion']
    assert len(bad)==2
    for entry in bad:
        edit=SolverEdit(**entry)
        assert source[edit.start:edit.end].count('\n')==1
        assert source[edit.start:edit.end].count('[')>source[edit.start:edit.end].count(']')
        candidate=edit.apply(source)
        assert candidate.splitlines()[8]==source.splitlines()[8]  # dangling original continuation
        attempts=[a for a in d['attempts'] if a['source_sha256']==source_digest(candidate)]
        assert len(attempts)==1 and attempts[0]['receipt']['outcome']=='REJECTED'
        diagnostics=json.loads(attempts[0]['receipt']['observations_json'])['report']['diagnostics']
        assert any(x['severity']=='error' and x['pos']['line']==9
                   and 'unexpected identifier' in x['message'] for x in diagnostics)
    attempted={a['source_sha256'] for a in d['attempts']}
    budget_blocked=[e for e in d['edits'] if e['candidate_sha256'] not in attempted]
    assert len(budget_blocked)==1 and budget_blocked[0]['parent']==1
    # A proposed edit blocked by the call cap is not a third native rejection.
    assert d['verifier_calls']==8 and d['status']=='BUDGET_EXHAUSTED'
