"""Real native context validation over owned artifacts; no proof is compiled.

Synthetic receipt payloads exercise the acceptance guard only. They are never
written to the campaign namespace or represented as native proof evidence.
"""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import check_lean_refactor_stage_v2 as gate
from jevops import arena_lean as native
from jevops.arena import VerificationRequest,source_hash
from jevops.lean import VersionPin


@pytest.fixture
def exact_context(tmp_path,monkeypatch):
    project=tmp_path/'project';project.mkdir()
    source='theorem context_fixture (h : True) : True := by exact h'
    (project/'Target.lean').write_text(source+'\n')
    (project/'lean-toolchain').write_text('leanprover/lean4:v4.26.0\n')
    (project/'lake-manifest.json').write_text('{"version":"1.1.0","packages":[]}\n')
    env={'PATH':'/usr/bin:/bin','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',
         'GIT_TERMINAL_PROMPT':'0','HOME':str(tmp_path)}
    def git(*args):
        return subprocess.run(['/usr/bin/git','-C',str(project),*args],env=env,
            stdin=subprocess.DEVNULL,capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    git('init','-q');git('add','Target.lean','lean-toolchain','lake-manifest.json')
    git('-c','user.name=Context fixture','-c','user.email=context-fixture@invalid.local',
        'commit','-qm','Owned context-only fixture')
    pin=VersionPin('v4.26.0',git('rev-parse','HEAD'))
    elan=tmp_path/'elan';compiler=elan/'toolchains/leanprover--lean4---v4.26.0/bin/lean'
    compiler.parent.mkdir(parents=True);compiler.write_text('context-only compiler identity; never executed\n')
    compiler.chmod(0o700);(compiler.parent.parent/'lib').mkdir()
    record={'name':'context_fixture','statement':'theorem context_fixture (h : True) : True',
            'src':source,'url':'https://github.com/fixture/context-only','file_path':'Target.lean',
            'version_info':[{pin.lean_tag:pin.git_commit}]}
    project_spec={'repository':record['url'],'root':str(project),'lean_tag':pin.lean_tag,
                  'git_commit':pin.git_commit,'resolve_lake_manifest':True}
    binding=native.project_binding(record,pin,project_spec,elan)
    # This is the ACTUAL closed producer argv. argparse's type=float converts
    # the literal "60" to 60.0, and canonical JSON intentionally preserves it.
    producer_argv=gate.c.definitions()['JLR-017']['argv']
    timeout=float(producer_argv[producer_argv.index('--timeout')+1])
    assert type(timeout) is float and timeout==60.0
    producer=native.NativeLeanVerifier({pin:binding},max_processes=12,timeout=timeout,strict_hashes=True)
    context=producer.context(record)
    request=VerificationRequest(context,source,pin)
    extra=[{'name':'unavailable_fixture_'+str(i),'statement':'theorem unavailable : True',
            'src':'theorem unavailable : True := by trivial','url':record['url'],
            'file_path':'Missing.lean','version_info':[{pin.lean_tag:format(i,'040x')}]}
           for i in range(1,36)]
    monkeypatch.setattr(gate.c,'module',lambda *_:SimpleNamespace(records=lambda:[record,*extra],CORPUS_SHA='context-fixture'))
    observations={'report':{'type_preserved':True,'target_absent_before':True,
                  'heartbeats':2,'raw_heartbeats':2000,'reference_heartbeats':2,
                  'reference_raw_heartbeats':2000,'axioms':[],'reference_axioms':[]}}
    from dataclasses import asdict
    row={'name':record['name'],'lean_tag':pin.lean_tag,'git_commit':pin.git_commit,'status':'VERIFIED',
         'context':asdict(context),'context_id':context.context_id,
         'receipt':{'outcome':'VERIFIED','request_id':request.request_id,'candidate_sha256':source_hash(source),
             'target':record['name'],'type_preserved':True,'exit_code':0,
             'observations_json':json.dumps(observations)}}
    unavailable=[{'name':r['name'],'lean_tag':pin.lean_tag,'git_commit':r['version_info'][0][pin.lean_tag],
                  'status':'UNAVAILABLE','capability_gaps':['owned context fixture has no such project'],
                  'baseline_compiles':None} for r in extra]
    data={'corpus_sha256':'context-fixture','required_version_checks':36,'processes':1,
          'live_model_calls':0,'official_score':None,'local_combined_pct':None,
          'worker_metric_parity':'UNCONFIRMED','projects':[project_spec],'rows':[row,*unavailable]}
    gate.c.save(tmp_path/gate.c.RUNTIME/'JLR-016.result.json',
                {'elan_home':str(elan),'rows':[{'name':record['name'],'lean_tag':pin.lean_tag,
                  'git_commit':pin.git_commit,'status':'READY'}]})
    return SimpleNamespace(root=tmp_path,data=data,row=row,producer=producer,binding=binding,
                           pin=pin,context=context,request=request,record=record)


def test_actual_baseline_accepts_argparse_float_timeout_context(exact_context):
    f=exact_context
    assert json.loads(f.context.verifier_options_json)['timeout']==60.0
    assert '"timeout":60.0' in f.context.verifier_options_json
    result=gate.baseline(f.root,f.data)
    assert result=={'verified_pin_checks':1,'required_pin_checks':36,'missing_checks':35,
                   'all_pin_baseline':False,'retained_incumbent':'original_fallback','official_metric_parity':False}
    assert f.producer.processes==0


def test_int_timeout_stays_strictly_different_from_float(exact_context):
    f=exact_context
    previous=native.NativeLeanVerifier({f.pin:f.binding},max_processes=0,timeout=60,strict_hashes=True)
    assert previous.options_json!=f.context.verifier_options_json
    with pytest.raises(ValueError,match='native verifier/context mismatch'):
        previous.validate_request(f.request)


@pytest.mark.parametrize('change',[{'timeout':61.0},{'timeout':60},{'kernel_check':False},
    {'max_heartbeats':2000001},{'branch_order':'candidate-first'},{'os_sandbox':True}])
def test_baseline_still_rejects_different_canonical_options(exact_context,change):
    f=exact_context;options=json.loads(f.row['context']['verifier_options_json']);options.update(change)
    f.row['context']['verifier_options_json']=json.dumps(options,sort_keys=True,separators=(',',':'))
    with pytest.raises(ValueError,match='native verifier/context mismatch'):
        gate.baseline(f.root,f.data)


def test_actual_verifier_rejects_foreign_pin(exact_context):
    f=exact_context
    foreign=VerificationRequest(f.context,f.record['src'],VersionPin('v4.31.0','f'*40))
    with pytest.raises(ValueError,match='native verifier/context mismatch'):
        f.producer.validate_request(foreign)


def test_baseline_still_rejects_candidate_source_substitution(exact_context):
    f=exact_context;f.row['receipt']['candidate_sha256']='0'*64
    with pytest.raises(ValueError,match='target/source/context/request changed'):
        gate.baseline(f.root,f.data)


def test_baseline_still_rejects_untrusted_axioms(exact_context):
    f=exact_context;observation=json.loads(f.row['receipt']['observations_json'])
    observation['report']['axioms']=['sorryAx'];f.row['receipt']['observations_json']=json.dumps(observation)
    with pytest.raises(ValueError,match='native axiom growth'):
        gate.baseline(f.root,f.data)


def test_exact_dependency_source_drift_still_rejected(exact_context):
    f=exact_context;(f.binding.root/'Target.lean').write_text('changed source\n')
    with pytest.raises(ValueError,match='project_has_tracked_changes'):
        f.producer.validate_request(f.request)
