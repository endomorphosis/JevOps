"""Actual private source/admission/transport tests; no canonical activation."""
from pathlib import Path
import ast
import copy
import importlib.util
import json
import os
import sys
import types
import pytest

HERE=Path(__file__).resolve().parents[1]
ROOT=next(parent for parent in (HERE,*HERE.parents) if (parent/'config/lean_refactor_arena_20261024_supervisor.json').is_file())
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('_canonical_v1_test_registry',HERE/'tools/lean_refactor_compiled_registry_v1.py')
registry=importlib.util.module_from_spec(spec);spec.loader.exec_module(registry)
c=__import__('lean_refactor_execution_v2')
admission=registry.peer('lean_refactor_compiled_admission_v1.py')
lineage=registry.peer('lean_refactor_compiled_lineage_v1.py')


def test_every_declared_source_is_fresh_and_source_inventory_is_nonrecursive(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('inventory cannot load a profile or native implementation')
    monkeypatch.setattr(c,'load',forbidden)
    value=registry.sources(ROOT)
    assert len(value)>=170
    assert all(len(sha)==64 for sha in value.values())
    assert all('tools/'+name in value for name in registry.LOCAL)


@pytest.mark.parametrize('name',['../escape.py','not_registered.py','lean_refactor_compiled_sources_v1.json','/tmp/source.py'])
def test_closed_peer_names(name):
    with pytest.raises(ValueError):registry.peer(name)


def test_symlink_peer_is_refused(tmp_path,monkeypatch):
    path=tmp_path/'lean_refactor_compiled_admission_v1.py'
    path.symlink_to(HERE/'tools'/path.name)
    monkeypatch.setattr(registry,'HERE',tmp_path)
    with pytest.raises(ValueError):registry.peer(path.name)


@pytest.mark.parametrize('exception',[False,True])
def test_real_exact_import_overrides_collision_and_restores_import_state(monkeypatch,exception):
    name='membership_observation';poison=types.ModuleType(name)
    poison.__file__='/unreviewed/foreign-module.py'
    monkeypatch.setitem(sys.modules,name,poison)
    old_path,old_meta=sys.path[:],sys.meta_path[:]
    try:
        with registry.retained_imports(ROOT):
            module=__import__(name)
            expected=registry.inventory()['imports'][name]
            assert Path(module.__file__).resolve()==(ROOT/expected).resolve()
            assert module is not poison
            if exception:raise InterruptedError('owned private fixture')
    except InterruptedError:
        assert exception
    assert sys.modules[name] is poison and sys.path==old_path and sys.meta_path==old_meta


def test_unregistered_backend_refuses_without_allocating_a_native_phase(monkeypatch):
    before=set((ROOT/c.RUNTIME/'compiled-coupled-v1').glob('*'))
    monkeypatch.setattr(c,'load',lambda root:({'source_sha256':{}},None,None,None))
    with pytest.raises(ValueError,match='not passed closed registration'):
        registry.registered(ROOT,c)
    assert set((ROOT/c.RUNTIME/'compiled-coupled-v1').glob('*'))==before


@pytest.mark.parametrize('bad',[True,False,None,'900',float('nan'),float('inf'),899.99,-1])
def test_bad_native_lease_cannot_allocate(bad):
    with pytest.raises(ValueError):admission.reserve(bad,900)


def test_native_lease_boundary_and_real_current_process_identity():
    admission.reserve(900,900)
    actor=admission.process(os.getpid())
    assert actor['uid']==os.getuid() and actor['pid']==os.getpid()
    assert actor['exe']==str(Path(sys.executable).resolve())
    assert admission.same_actor(actor,{**actor,'state':'R'})
    assert not admission.same_actor(actor,{**actor,'start_ticks':actor['start_ticks']+1})


@pytest.mark.parametrize('argv',[(),('--repo-root',),('--repo-root','a','--repo-root','b'),
    ('--repo-root=a','--repo-root=b'),('--repo-root','a','--repo-root=b')])
def test_ambiguous_or_missing_scope_option(argv):
    with pytest.raises(ValueError):admission.option(argv,'--repo-root')


def test_scoped_option_forms():
    assert admission.option(('--repo-root','/a'),'--repo-root')=='/a'
    assert admission.option(('--repo-root=/a',),'--repo-root')=='/a'


@pytest.mark.parametrize('change',['uid','cwd','exe','module','repository','todo','bundle','lease'])
def test_native_scope_independently_rejects_wrong_owner(change):
    root=ROOT.resolve();python=sys.executable;status=root/'status.json'
    lane={'bundle_key':'private-native-fixture','max_resume_seconds':14400}
    args=(python,'-m','ipfs_accelerate_py.agent_supervisor.rescue.lane_resume',
        '--repo-root',str(root),'--todo-path',c.BOARD,'--status-path',str(status),
        '--bundle-key',lane['bundle_key'],'--max-seconds','14400','--task-header-prefix','## JLR-')
    actor={'uid':os.getuid(),'state':'S','cwd':str(root),'exe':str(Path(python).resolve()),'argv':args}
    if change in ('uid','cwd','exe'):actor[change]=(-1 if change=='uid' else '/foreign')
    else:
        args=list(args)
        key={'module':'-m','repository':'--repo-root','todo':'--todo-path',
             'bundle':'--bundle-key','lease':'--max-seconds'}[change]
        args[args.index(key)+1]='foreign';actor['argv']=tuple(args)
    with pytest.raises(ValueError):admission.scope(root,actor,{'python_executable':python},lane,status,{})


def test_current_maintenance_process_cannot_impersonate_normal_native_actor():
    with pytest.raises(ValueError):admission.admit(ROOT,'producer')


def proposal():
    value=registry.inventory();before=c.read(ROOT/value['baseline_profile'])
    after=copy.deepcopy(before)
    for name in value['extension_changes']:after['source_sha256'][name]='e'*64
    additions=set(value['retained'])|{'tools/'+name for name in registry.LOCAL}|set(registry.TESTS)
    for name in additions-set(before['source_sha256']):after['source_sha256'][name]='f'*64
    return before,after,value


def test_closed_prospective_review_preserves_contracts_goals_budgets_and_overlay():
    before,after,value=proposal()
    lineage.prospective(before,after,value,registry.LOCAL)


@pytest.mark.parametrize('change',['contracts','goals_sha256','base_profile_sha256','continuation_plan',
    'phase_budget','scientific_route','extra_source','remove_source','omit_change'])
def test_closed_review_refuses_unreviewed_semantics_or_sources(change):
    before,after,value=proposal()
    if change=='extra_source':after['source_sha256']['tools/unreviewed.py']='a'*64
    elif change=='remove_source':after['source_sha256'].pop('jevops/arena_lean.py')
    elif change=='omit_change':after['source_sha256'][value['extension_changes'][0]]=before['source_sha256'][value['extension_changes'][0]]
    else:after[change]={'unreviewed':True}
    with pytest.raises(ValueError):lineage.prospective(before,after,value,registry.LOCAL)


def test_real_historical_profile_and_missing_custody_are_distinct(tmp_path):
    value=registry.inventory();path=ROOT/value['baseline_profile']
    assert lineage.historical(ROOT,value['baseline_profile'],value['baseline_profile_sha256'])==path
    with pytest.raises(ValueError):lineage.historical(tmp_path,'missing.json','0'*64)


def test_original_producer_and_compiled_runtime_contracts_remain_identical():
    before=c.read(ROOT/registry.inventory()['baseline_profile'])
    assert c.definitions()==before['contracts']
    assert c.definitions()['JLR-020']['argv']==['tools/lean_refactor_coupled_pilot.py','--produce']


@pytest.mark.parametrize('damage',['order','type','axiom','timeout','stdout','request','resource'])
def test_genuine_retained_native_transport_rejects_tampering_without_a_child(damage):
    engine=registry.peer('lean_refactor_compiled_coupled_v1.py')
    parent=ROOT/c.RUNTIME/'maintenance-1536-snapshot/complete-stage-serialization-v1/producer'
    data=c.read(parent/'observation.json');row=data['pins']['v4.26.0'];sample=row['rows'][-1]
    raw=parent/'v4.26.0'/sample['raw']
    payload=c.read(raw/'input.json');execution=c.read(raw/'execution.json')
    out,err=(raw/'stdout').read_bytes(),(raw/'stderr').read_bytes()
    record=engine.base.qualifier.nominations
    frozen=c.read(ROOT/c.RUNTIME/'maintenance-1536-snapshot/serialization-prepared.json')['frozen']
    from jevops.lean import VersionPin
    pin=VersionPin('v4.26.0',frozen['pins']['v4.26.0'])
    from types import SimpleNamespace
    binding=SimpleNamespace(prefix=payload['prefix'])
    validate=engine.base.protected.native_sample
    assert validate(frozen['record'],pin,binding,sample['source'],sample['branch_order'],payload,out,err,execution)['outcome']=='VERIFIED'
    if damage=='order':payload['candidate_first']=not payload['candidate_first']
    elif damage=='timeout':execution['timed_out']=True
    elif damage=='stdout':out+=b'changed-byte'
    elif damage=='request':payload['request_id']='0'*32
    elif damage=='resource':execution['max_process_address_space_bytes']+=1
    else:
        lines=out.splitlines();index=next(i for i,x in enumerate(lines) if x.startswith(b'JEVOPS_ARENA:'))
        packet=json.loads(lines[index][len(b'JEVOPS_ARENA:'):])
        if damage=='type':packet['report']['type_preserved']=False
        else:packet['report']['axioms']=['UnauthorizedAxiom']
        lines[index]=b'JEVOPS_ARENA:'+json.dumps(packet).encode();out=b'\n'.join(lines)+b'\n'
        import hashlib
        execution['stdout_sha256']=hashlib.sha256(out).hexdigest()
    with pytest.raises(ValueError):validate(frozen['record'],pin,binding,sample['source'],sample['branch_order'],payload,out,err,execution)


def test_native_engine_has_only_the_reviewed_control_admission_changes():
    original=function(ROOT/c.RUNTIME/'maintenance-1536-snapshot/serialization_stage.py','run')
    candidate=function(HERE/'tools/lean_refactor_compiled_coupled_v1.py','run')
    class Admission(ast.NodeTransformer):
        def visit_Compare(self,node):
            node=self.generic_visit(node)
            if isinstance(node.left,ast.Call) and isinstance(node.left.func,ast.Attribute) and node.left.func.attr=='quiescent_maintenance_fence':
                return ast.Call(func=ast.Name(id='fence',ctx=ast.Load()),args=[],keywords=[])
            return node
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Attribute) and node.func.attr=='require' and len(node.args)==2 and isinstance(node.args[1],ast.Constant) and node.args[1].value=='fresh exact own childless acknowledgement required':
                return ast.parse("c.require(callable(fence) and fence(), 'current registered native actor required')").body[0].value
            return node
        def visit_Constant(self,node):
            if node.value=='jevops.lean-refactor.private-physical-complete-coupled.v1':
                node.value='jevops.lean-refactor.canonical-physical-complete-coupled.v1'
            return node
    assert ast.dump(Admission().visit(original),include_attributes=False)==ast.dump(candidate,include_attributes=False)


def test_all_native_build_control_and_confirmation_loop_bytes_are_unchanged():
    old=function(ROOT/c.RUNTIME/'maintenance-1610-protected/replay-private/replay.py','run')
    new=function(HERE/'tools/lean_refactor_compiled_replay_v1.py','_protect')
    def native_loop(node):
        return next(x for x in ast.walk(node) if isinstance(x,ast.For) and isinstance(x.target,ast.Name)
            and x.target.id=='tag' and isinstance(x.iter,ast.Attribute) and x.iter.attr=='PINS')
    assert ast.dump(native_loop(old),include_attributes=False)==ast.dump(native_loop(new),include_attributes=False)


def staged(name):
    path=HERE/'tools'/name
    spec=importlib.util.spec_from_file_location('_private_entry_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_staged_closed_registration_keeps_every_original_contract(monkeypatch):
    module=staged('lean_refactor_execution_v2.py')
    assert module.definitions()==c.definitions()
    ordinary=module.module
    monkeypatch.setattr(module,'module',lambda root,name:registry if name=='lean_refactor_compiled_registry_v1.py'
        else ordinary(root,name))
    actual=module.sources(ROOT)
    assert all(actual[name]==sha for name,sha in registry.sources(ROOT).items())
    assert all(name in actual for name in c.sources(ROOT))


def test_staged_producer_routes_only_after_closed_profile_admission(monkeypatch):
    module=staged('lean_refactor_coupled_pilot.py');calls=[]
    monkeypatch.setattr(module.c,'load',lambda root:({'source_sha256':{'tools/lean_refactor_compiled_coupled_v1.py':'a'*64}},None,None,None))
    monkeypatch.setattr(module.c,'module',lambda root,name:types.SimpleNamespace(produce=lambda selected:calls.append((selected,name)) or {'private':'routed'}))
    assert module.produce(ROOT)=={'private':'routed'}
    assert calls==[(ROOT,'lean_refactor_compiled_coupled_v1.py')]


def test_staged_protected_entry_uses_the_independent_replay(monkeypatch):
    module=staged('validate_lean_refactor_coupled_pilot.py');calls=[]
    monkeypatch.setattr(module.c,'module',lambda root,name:types.SimpleNamespace(protect=lambda r,d:calls.append((r,d,name)) or {'private':'validated route'}))
    data={'schema':'jevops.lean-refactor.canonical-coupled-result.v1'}
    assert module.validate(ROOT,data)=={'private':'validated route'}
    assert calls==[(ROOT,data,'lean_refactor_compiled_replay_v1.py')]


def test_staged_retry_gate_preserves_spent_compiled_phase(monkeypatch):
    module=staged('run_lean_refactor_stage_v2.py');calls=[]
    monkeypatch.setattr(module.c,'module',lambda root,name:types.SimpleNamespace(admission_wait=lambda r,**kw:calls.append((r,name,kw)) or {'exit_code':75}))
    profile={'source_sha256':{'tools/lean_refactor_compiled_coupled_v1.py':'b'*64}}
    assert module.frontier_failure_admission(ROOT,'JLR-020',profile,publish=False)=={'exit_code':75}
    assert calls==[(ROOT,'lean_refactor_compiled_coupled_v1.py',{'publish':False})]


@pytest.mark.parametrize('status',['RUNNING','REFUSED','NO_ALL_PIN_WINNER','QUALIFIED_ALL_PINS'])
def test_spent_gate_does_not_mask_a_successful_producer_from_independent_acceptance(tmp_path,monkeypatch,status):
    engine=registry.peer('lean_refactor_compiled_coupled_v1.py')
    frozen={'private':'source-bound fixture'}
    monkeypatch.setattr(engine,'freeze',lambda:frozen)
    phase=engine.phase_path(tmp_path,frozen);phase.mkdir(parents=True)
    c.save(phase/'phase-ledger.json',{'schema':'jevops.lean-refactor.canonical-coupled-workflow.v1','status':status})
    before=(phase/'phase-ledger.json').read_bytes()
    probe=engine.admission_wait(tmp_path,publish=False)
    assert (probe is None)==(status=='QUALIFIED_ALL_PINS')
    assert engine.admission_wait(tmp_path,publish=True)['exit_code']==75
    assert (phase/'phase-ledger.json').read_bytes()==before


@pytest.mark.parametrize('existing',['absent','genuine','corrupt'])
def test_archival_authenticates_exact_before_images_and_never_replaces_a_destination(tmp_path,monkeypatch,existing):
    source=tmp_path/'original.json';source.write_bytes(b'{"retained_failure":true}\n')
    sha=c.sha(source);path=tmp_path/c.RUNTIME/'history'/('original.json.'+sha)
    path.parent.mkdir(parents=True)
    if existing!='absent':path.write_bytes(source.read_bytes() if existing=='genuine' else b'foreign bytes')
    manifest='private-rebase.json';c.save(tmp_path/manifest,{'protected_current':{'original.json':sha}})
    monkeypatch.setattr(lineage,'REBASE',manifest)
    before=path.read_bytes() if path.exists() else None
    if existing=='corrupt':
        with pytest.raises(ValueError):lineage.retain_heads(tmp_path)
        assert path.read_bytes()==before
    else:
        lineage.retain_heads(tmp_path)
        source.write_bytes(b'{"new_result":true}\n')
        assert lineage.historical(tmp_path,'original.json',sha)==path
        assert c.sha(path)==sha


def test_engine_import_does_not_allocate_a_phase_and_keeps_original_resource_limits():
    engine=registry.peer('lean_refactor_compiled_coupled_v1.py')
    assert engine.LIMITS=={'admission_seconds':780,'stage_seconds':900,'native_children':21,
        'retained_parser_children':3,'complete_producer_denominator':24,'build_children':6,
        'child_seconds':60,'memory_bytes':4*1024**3,'artifact_bytes':128*1024**2}
    assert engine.PINS==('v4.26.0','v4.29.1','v4.27.0')


def function(path,name):
    return next(node for node in ast.parse(path.read_text()).body if isinstance(node,ast.FunctionDef) and node.name==name)


@pytest.mark.parametrize('name',['population','scan'])
def test_exact_fresh_identity_and_scan_functions_are_unchanged(name):
    old=ROOT/c.RUNTIME/'maintenance-1536-snapshot/serialization_stage.py'
    new=HERE/'tools/lean_refactor_compiled_coupled_v1.py'
    assert ast.dump(function(old,name),include_attributes=False)==ast.dump(function(new,name),include_attributes=False)


@pytest.mark.parametrize('name',['build_packets','distinct_build','distinct_request','raw','validate'])
def test_independent_protected_semantics_remain_unchanged(name):
    old=ROOT/c.RUNTIME/'maintenance-1610-protected/replay-private/validate_physical_replay.py'
    new=HERE/'tools/validate_lean_refactor_compiled_replay_v1.py'
    assert ast.dump(function(old,name),include_attributes=False)==ast.dump(function(new,name),include_attributes=False)


@pytest.mark.parametrize('kind',['native','build'])
def test_full_replay_denominator_is_spent_before_launch_and_cannot_reset(kind):
    replay=registry.peer('lean_refactor_compiled_replay_v1.py')
    data={'native_processes':5,'build_processes':5}
    replay.allocate(data,kind)
    with pytest.raises(ValueError):replay.allocate(data,kind)
    assert data[kind+'_processes']==6


@pytest.mark.parametrize('damage',['status','pin','time','children','source_flag','cleanup','validator'])
def test_producer_qualification_is_not_inferred_from_files_exit_or_status(damage):
    validator=registry.peer('validate_lean_refactor_compiled_replay_v1.py')
    root=ROOT/c.RUNTIME/'maintenance-1536-snapshot/complete-stage-serialization-v1'
    envelope=c.read(root/'observation.json');data=c.read(root/'producer/observation.json')
    # Test-memory envelope only; genuine historical files are never rewritten.
    envelope['native_actor_verified']=True
    data['schema']='jevops.lean-refactor.canonical-physical-complete-coupled.v1'
    if damage=='status':data['status']='REFUSED'
    elif damage=='pin':data['pins'].pop('v4.27.0')
    elif damage=='time':data['wall_seconds']=780.001
    elif damage=='children':data['native_processes']=20
    elif damage=='source_flag':envelope['production_sources_unchanged']=False
    elif damage=='cleanup':data['snapshots_removed']=False
    elif damage=='validator':data['validation']={}
    engine=registry.peer('lean_refactor_compiled_coupled_v1.py')
    with pytest.raises(ValueError):validator.parent_shape(envelope,data,engine.PINS,engine.LIMITS)
