"""Private synthetic reviewed-port fixtures; no production writes or external jobs."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import contextlib
import sys
from types import SimpleNamespace as N
import pytest

BASE=Path(__file__).parents[1]
REAL=Path('/home/barberb/lift_coding/JevOps')
sys.path.insert(0,str(REAL/'tools'))
import publish_official_release_watch as c
spec=importlib.util.spec_from_file_location('transition_tested',BASE/'tools/release_publisher_transition_v1.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


def put(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    raw=value if type(value)is bytes else t.canonical(value)
    p.write_bytes(raw);p.chmod(0o600)
    return dict(path=name,sha256=t.sha(raw))


@pytest.fixture
def rig(tmp_path,monkeypatch):
    root=tmp_path/'private-repo';root.mkdir();state=root/c.STATE;state.mkdir(parents=True,mode=0o700)
    for name in c.SOURCE_FILES:put(root,name,(REAL/name).read_bytes())
    original={name:t.sha(put(root,name,b'# before\n')and(root/name).read_bytes())for name in t.PATCHES}
    for i in range(248):
        name='original/source-'+str(i)+'.py';ref=put(root,name,('source'+str(i)).encode());original[name]=ref['sha256']
    baseline=dict(schema='fixture-owner',board='fixture-board',contracts={'JLR-035':{'timeout':120}},
        goals_sha256='g'*64,base_profile_sha256='b'*64,continuation_plan={'exact':'unchanged'},
        phase_budget={'calls':24},scientific_route={'route':'closed'},source_sha256=original,previous_profiles={'1'*64:'retained-old-profile.json'})
    baseline_raw=t.canonical(baseline);before_sha=t.sha(baseline_raw);monkeypatch.setattr(t,'BASE_SHA',before_sha)
    history='data/lean_refactor_arena_20261024/execution-v2/history/'+Path(t.PROFILE).name+'.'+before_sha
    before_profile=put(root,history,baseline_raw)
    put(root,t.PROFILE,baseline_raw)
    freeze='config/lean_refactor_arena_20261026_provider_freeze.json';put(root,freeze,{'new_calls_allowed':False})
    oldrows=[dict(path=name,sha256=digest)for name,digest in original.items()]+[dict(path=t.PROFILE,sha256=before_sha)]
    for i in range(12):
        ref=put(root,'control/input-'+str(i),('control'+str(i)).encode());oldrows.append(ref)
    assert len(oldrows)==266
    preserved=put(root,'operator/original-preservation.json',{'schema':'jevops.repair-publication-preservation.v1','files':oldrows})
    tests=put(root,'operator/original-tests.xml',b'<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.original" name="actual-private-fixture"/></testsuite>')
    monkeypatch.setattr(t,'ORIGINAL_JUNIT',tests);monkeypatch.setattr(t,'MIN_ORIGINAL_CASES',1);monkeypatch.setattr(t,'MIN_NEW_CASES',1)
    settings=dict(state_dir=c.STATE,provider_budget_policy=freeze,poll_seconds=900,publish_retry_seconds=120)
    oldpre=put(root,'operator/original-preflight.json',dict(schema='jevops.official-release-watch-preflight.v1',
        settings_sha256=c.digest(c.canonical(settings)),sources=[dict(path=name,sha256=t.sha((root/name).read_bytes()))for name in sorted(c.SOURCE_FILES)],test_evidence=[tests],preservation=preserved))
    put(root,c.CONFIG,dict(schema='jevops.official-release-watch-config.v1',settings=settings,preflight=oldpre))
    load=c.load_contract
    def fixture_load(repo,*,config_relative=c.CONFIG,approved_preservation=None):
        return load(repo,config_relative=config_relative,approved_preservation=preserved if approved_preservation is None else approved_preservation)
    monkeypatch.setattr(c,'load_contract',fixture_load);monkeypatch.setattr(t,'consumer',lambda root:c)
    old=c.load_contract(root)
    actual=json.loads((REAL/c.STATE/'outbox/events'/(t.ORIGINAL_EVENT+'.json')).read_bytes())
    for row in actual['observation']['evidence']:put(root,row['path'],(REAL/row['path']).read_bytes())
    ev=put(root,c.STATE+'/outbox/events/'+t.ORIGINAL_EVENT+'.json',actual)
    put(root,c.STATE+'/outbox/current.json',dict(schema='jevops.official-release-outbox-pointer.v1',
        event=dict(path='outbox/events/'+t.ORIGINAL_EVENT+'.json',sha256=ev['sha256']),fingerprint=actual['fingerprint']))
    for p in state.rglob('*'):
        if p.is_dir():p.chmod(0o700)
    selected=c.read_event(old);_,request=c.build_request(old,selected)
    receiptr=put(root,request['receipt'],dict(schema=request['schema'],published=True,queue_hold_released=True,
        handoff=request['handoff'],append=request['append'],verify=request['verify']))
    c.mark_delivered(old,selected,receiptr)
    marker=state/'outbox/delivered'/(t.ORIGINAL_EVENT+'.json');requestpath=root/request['receipt'];requestpath=requestpath.with_name('request.json')
    custody=dict(event=ev,marker=dict(path=str(marker.relative_to(root)),sha256=t.sha(marker.read_bytes())),
        request=dict(path=str(requestpath.relative_to(root)),sha256=t.sha(requestpath.read_bytes())),receipt=receiptr)
    review=put(root,t.PORT+'/review.py',b'# independently reviewed exact synthetic port fixture\n')
    monkeypatch.setattr(t,'REVIEW_SHA',review['sha256'])
    changes=[];dest={}
    for name in sorted(t.PATCHES):
        before=put(root,t.PORT+'/beforeimages/'+Path(name).name,b'# before\n')
        after=put(root,name,b'# reviewed exact after\n')
        candidate=put(root,t.PORT+'/private/'+name,b'# reviewed exact after\n')
        changes.append(dict(path=name,before_sha256=before['sha256'],after_sha256=after['sha256'],before_image=before))
        dest[name]=dict(candidate=candidate['path'],sha256=after['sha256'],before_sha256=before['sha256'])
    inventory=dict(schema='jevops.lean-refactor.release-canonical-sources.v2',baseline=before_profile,retained={review['path']:review['sha256']})
    for name in t.ADDITIONS:
        raw=t.canonical(inventory)if name.endswith('.json')else b'# reviewed additive fixture\n'
        after=put(root,name,raw);private=put(root,t.PORT+'/private/'+name,raw)
        dest[name]=dict(candidate=private['path'],sha256=after['sha256'],before_sha256=None)
    newtests=put(root,t.PORT+'/focused-v4.xml',b'<testsuite tests="1"><testcase classname="private.tests.new" name="new-reviewed-fixture"/></testsuite>')
    candidate=put(root,t.PORT+'/candidate.json',dict(schema='jevops.lean-refactor.release-port-private-candidate.v2',
        baseline_profile_sha256=before_sha,integration_prepared=False,canonical_changed=False,
        destinations=dest,source_sha256={review['path']:review['sha256']},test_evidence=[dict(**newtests,minimum_cases=1)]))
    monkeypatch.setattr(t,'CANDIDATE_SHA',candidate['sha256'])
    sources={**original,**{name:dest[name]['sha256']for name in t.PATCHES|t.ADDITIONS},review['path']:review['sha256']}
    profile={**baseline,'source_sha256':sources,'previous_profiles':{**baseline['previous_profiles'],before_sha:history}}
    profref=put(root,t.PROFILE,profile);changes.append(dict(path=t.PROFILE,before_sha256=before_sha,after_sha256=profref['sha256'],before_image=before_profile))
    active=put(root,'acceptance/activation.json',dict(profile_sha256=profref['sha256'],quiescent_maintenance_review=True,preflight={'valid':True}))
    mat=put(root,'acceptance/materialization.json',dict(profile_sha256=profref['sha256'],quiescent_maintenance_review=True,preflight={'valid':True},previous_profile_sha256=before_sha,bootstrap_restarted=False))
    tx=put(root,'acceptance/transaction.json',dict(activated=True,owned_hold_released=True,scientific_stage_accepted=False,
        profile_sha256=profref['sha256'],activation_sha256=active['sha256'],materialization_sha256=mat['sha256']))
    junit=put(root,'acceptance/canonical.xml',b'<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase classname="tests.original" name="actual-private-fixture"/><testcase classname="tests.new" name="new-reviewed-fixture"/></testsuite>')
    tr=put(root,'acceptance/test-receipt.json',dict(passed=True,source_sha256=sources,junit_path=junit['path'],junit_sha256=junit['sha256']))
    transitiontests=put(root,'acceptance/transition.xml',b'<testsuite><testcase name="transition-private-fixture"/></testsuite>')
    qualified_source=put(root,'qualification/runtime.py',Path(t.__file__).read_bytes())
    qualified_tests=put(root,'qualification/test_source.py',Path(__file__).read_bytes())
    qualified=put(root,'qualification/actual-execution.json',dict(schema='jevops.release-publisher-transition-qualification.v1',
        runtime_source=qualified_source,test_source=qualified_tests,junit=transitiontests))
    approved=dict(schema='jevops.reviewed-release-publisher-transition.v1',candidate=candidate,review=review,
        changes=changes,profile_after=profref,transaction=tx,activation=active,materialization=mat,
        test_receipt=tr,canonical_junit=junit,transition_junit=transitiontests,
        transition_qualification=qualified,original_delivery=custody)
    ref=put(root,'operator/approved-transition.json',approved)
    return N(root=root,state=state,old=old,ref=ref,approved=approved,selected=selected,
        output=t.OUTPUT_PREFIX+'/explicit-reviewed-v2',oldrows=oldrows,profile=profile,baseline=baseline,
        original_config=(root/c.CONFIG).read_bytes(),c=c)


def test_plan_only_exact_delta_preserves_original_artifacts_and_loads(rig):
    plan=t.prepare(rig.root,rig.ref,rig.output)
    assert plan['installed']is False and plan['services_changed']is False
    assert (rig.root/c.CONFIG).read_bytes()==rig.original_config
    c2,old,current,p=t.load_transition(rig.root,rig.ref,rig.output)
    assert len(current['preservation_rows'])==266
    assert {a['path']for a,b in zip(current['preservation_rows'],rig.oldrows)if a!=b}==t.ALLOWED
    assert len(current['preflight']['sources'])>4
    assert any(row==rig.ref for row in current['preflight']['sources'])
    assert t.prepare(rig.root,rig.ref,rig.output)==plan


def test_exact_original_event_marker_bridges_new_preflight_without_publisher(rig,monkeypatch):
    t.prepare(rig.root,rig.ref,rig.output)
    monkeypatch.setattr(c,'consume',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No repeat publication allowed')))
    before={p:p.read_bytes()for p in rig.state.rglob('*')if p.is_file()}
    result,code=t.consume_transition(rig.root,rig.ref,rig.output)
    assert code==0 and result['reason']=='ALREADY_DELIVERED_ORIGINAL_EPOCH'
    assert {p:p.read_bytes()for p in rig.state.rglob('*')if p.is_file()}==before


def test_original_consumer_reproduces_old_marker_new_preflight_defect_then_bridge_recovers(rig):
    t.prepare(rig.root,rig.ref,rig.output)
    current=t.load_transition(rig.root,rig.ref,rig.output)[2]
    tools=N(publisher=N(idle=N(scope=lambda root:dict(root=root))))
    with pytest.raises(c.ReviewRequired,match='Delivery marker receipt differs'):
        c.consume(rig.root,rig.state,load=lambda root:current,tools=lambda root:tools)
    result,code=t.consume_transition(rig.root,rig.ref,rig.output)
    assert code==0 and result['reason']=='ALREADY_DELIVERED_ORIGINAL_EPOCH'


@pytest.mark.parametrize('target',['marker','request','receipt','event'])
def test_original_custody_mutation_refused_before_publication(rig,target):
    t.prepare(rig.root,rig.ref,rig.output)
    path=rig.root/rig.approved['original_delivery'][target]['path'];path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises((ValueError,c.ReviewRequired)):t.consume_transition(rig.root,rig.ref,rig.output)


def test_new_semantic_event_uses_normal_consumer_and_new_delivery_dedup(rig,monkeypatch):
    t.prepare(rig.root,rig.ref,rig.output)
    selected=copy.deepcopy(rig.selected);selected['event']['event_id']='a'*32
    monkeypatch.setattr(c,'read_event',lambda contract:selected)
    calls=[]
    def consume(root,state,**kwargs):
        loaded=kwargs['load'](root);calls.append(loaded)
        return {'reason':'DELIVERED'if len(calls)==1 else'ALREADY_DELIVERED'},0
    monkeypatch.setattr(c,'consume',consume)
    assert t.consume_transition(rig.root,rig.ref,rig.output)[0]['reason']=='DELIVERED'
    assert t.consume_transition(rig.root,rig.ref,rig.output)[0]['reason']=='ALREADY_DELIVERED'
    assert len(calls)==2 and calls[0]['preservation']!=rig.old['preservation']


def test_new_event_actual_consumer_publishes_then_deduplicates_with_new_preservation(rig):
    t.prepare(rig.root,rig.ref,rig.output)
    event=copy.deepcopy(rig.selected['event']);event['event_id']='b'*32
    ev=put(rig.root,c.STATE+'/outbox/events/'+event['event_id']+'.json',event)
    put(rig.root,c.STATE+'/outbox/current.json',dict(schema='jevops.official-release-outbox-pointer.v1',
        event=dict(path='outbox/events/'+event['event_id']+'.json',sha256=ev['sha256']),fingerprint=event['fingerprint']))
    repair=rig.root/'repair';put(rig.root,'repair/state.json',{})
    binding=dict(root=rig.root,native_cfg=N(state_dir=repair,repair_lock_path=rig.root/'fixer'),
        supervisor=dict(accelerator_source=str(rig.root/'external')))
    calls=[]
    def input_request(root,ref,**kwargs):
        value=c.json_object(c.referenced(root,ref)[1])
        for row in value['verify']:c.referenced(root,dict(path=row['path'],sha256=row['sha256']))
        return value,None,None
    publisher=N(idle=N(scope=lambda root:binding,unchanged_scope=lambda binding:None),
        observation=lambda binding,proof:{'idle':True},request_input=input_request)
    def publish(root,ref,**kwargs):
        request=input_request(root,ref)[0];calls.append(request)
        put(root,request['receipt'],dict(schema=request['schema'],published=True,queue_hold_released=True,
            handoff=request['handoff'],append=request['append'],verify=request['verify']))
        return {'published':True},0
    tools=N(publisher=publisher,publish_with_lease=publish)
    run=lambda argv,timeout:N(stdout='[]')
    first,code=t.consume_transition(rig.root,rig.ref,rig.output,tools=lambda root:tools,run=run)
    assert code==0 and first['reason']=='DELIVERED'and len(calls)==1
    second,code=t.consume_transition(rig.root,rig.ref,rig.output,tools=lambda root:tools,run=run)
    assert code==0 and second['reason']=='ALREADY_DELIVERED'and len(calls)==1
    assert calls[0]['preserve']!=rig.old['preservation']
    assert any(row['path'].endswith('/runtime.py')for row in calls[0]['verify'])


def test_wrong_explicit_approval_sha_refused_without_output(rig):
    with pytest.raises(c.ReviewRequired):t.prepare(rig.root,{**rig.ref,'sha256':'0'*64},rig.output)
    assert not(rig.root/rig.output).exists()


@pytest.mark.parametrize('kind',['missing_change','extra_change','arbitrary_after','missing_original_source','extra_profile_source','changed_contract','changed_prior_history','unreleased_transaction','failed_activation','source_receipt_mismatch','failed_junit'])
def test_closed_transition_guards_refuse_unreviewed_or_unaccepted_inputs(rig,kind):
    v=copy.deepcopy(rig.approved)
    if kind=='missing_change':v['changes'].pop()
    elif kind=='extra_change':v['changes'].append(copy.deepcopy(v['changes'][0]))
    elif kind=='arbitrary_after':
        name=v['changes'][0]['path'];v['changes'][0]['after_sha256']=put(rig.root,name,b'# arbitrary unreviewed\n')['sha256']
    elif kind in {'missing_original_source','extra_profile_source','changed_contract','changed_prior_history'}:
        profile=copy.deepcopy(rig.profile)
        if kind=='missing_original_source':profile['source_sha256'].pop('original/source-1.py')
        elif kind=='extra_profile_source':profile['source_sha256']['unreviewed.py']='0'*64
        elif kind=='changed_contract':profile['contracts']['JLR-035']['timeout']=999
        else:profile['previous_profiles']['1'*64]='rewritten-history.json'
        ref=put(rig.root,t.PROFILE,profile);v['profile_after']=ref
        next(row for row in v['changes']if row['path']==t.PROFILE)['after_sha256']=ref['sha256']
    else:
        field={'unreleased_transaction':'transaction','failed_activation':'activation','source_receipt_mismatch':'test_receipt','failed_junit':'canonical_junit'}[kind]
        if kind=='failed_junit':raw=b'<testsuite failures="1"><testcase><failure/></testcase></testsuite>'
        else:
            raw=json.loads((rig.root/v[field]['path']).read_bytes())
            if kind=='unreleased_transaction':raw['owned_hold_released']=False
            elif kind=='failed_activation':raw['preflight']['valid']=False
            else:raw['source_sha256']={}
        v[field]=put(rig.root,v[field]['path'],raw)
    ref=put(rig.root,rig.ref['path'],v)
    with pytest.raises((ValueError,c.ReviewRequired)):t.prepare(rig.root,ref,rig.output)
    assert not(rig.root/rig.output).exists()


def test_unapproved_unchanged_population_drift_refused(rig):
    (rig.root/'control/input-2').write_bytes(b'unapproved drift')
    with pytest.raises(ValueError,match='Unapproved preserved'):t.prepare(rig.root,rig.ref,rig.output)


def test_plan_tamper_cannot_adopt_new_preflight_or_wrapper(rig):
    t.prepare(rig.root,rig.ref,rig.output)
    path=rig.root/rig.output/'consumer.py';path.write_text('# unreviewed wrapper')
    planpath=rig.root/rig.output/'plan.json';plan=json.loads(planpath.read_bytes());plan['wrapper']['sha256']=t.sha(path.read_bytes());put(rig.root,str(planpath.relative_to(rig.root)),plan)
    with pytest.raises(ValueError,match='deterministic template'):t.load_transition(rig.root,rig.ref,rig.output)


def test_generated_wrapper_compiles_and_executes_verified_raw_only(rig):
    plan=t.prepare(rig.root,rig.ref,rig.output)
    raw=(rig.root/plan['wrapper']['path']).read_bytes();compile(raw,'wrapper','exec')
    assert b'exec(compile(raw,'in raw and b'exec_module'not in raw
    assert '--approval-sha256'in plan['proposed_exec_start'] and rig.ref['sha256']==plan['proposed_exec_start'][-1]


def test_qualification_source_drift_refused_before_plan(rig):
    (rig.root/'qualification/runtime.py').write_bytes(b'# unqualified different runtime')
    with pytest.raises(c.ReviewRequired):t.prepare(rig.root,rig.ref,rig.output)
    assert not(rig.root/rig.output).exists()


def test_one_passing_case_cannot_replace_full_accepted_canonical_population(rig):
    v=copy.deepcopy(rig.approved)
    v['canonical_junit']=put(rig.root,v['canonical_junit']['path'],b'<testsuite tests="1"><testcase classname="tests.original" name="actual-private-fixture"/></testsuite>')
    receipt=json.loads((rig.root/v['test_receipt']['path']).read_bytes());receipt['junit_sha256']=v['canonical_junit']['sha256']
    v['test_receipt']=put(rig.root,v['test_receipt']['path'],receipt)
    ref=put(rig.root,rig.ref['path'],v)
    with pytest.raises(ValueError,match='Full original334'):t.prepare(rig.root,ref,rig.output)
    assert not(rig.root/rig.output).exists()


def test_unknown_output_scope_and_existing_conflict_are_not_overwritten(rig):
    with pytest.raises(ValueError):t.prepare(rig.root,rig.ref,'config/overwrite')
    path=rig.root/rig.output/'runtime.py';path.parent.mkdir(parents=True);path.write_text('owned concurrent edit')
    with pytest.raises(c.ReviewRequired):t.prepare(rig.root,rig.ref,rig.output)
    assert path.read_text()=='owned concurrent edit'
