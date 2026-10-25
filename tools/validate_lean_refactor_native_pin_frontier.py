"""Independent protected acceptance of supplemental compiler/project receipts."""
from pathlib import Path
import time
import lean_refactor_execution_v2 as c
from lean_refactor_native_pin_frontier import SCHEMA,TARGET,MAX_SECONDS,plan

def probe(root,*,now=None):
    """Cheap clock/evidence retry gate; no compiler, mount, hash tree or model."""
    now=time.time() if now is None else now
    path=root/c.RUNTIME/'native-pin-frontier.json'
    observed=0;reference=None;missing=[]
    if path.exists():
        reference=c.read(path)
        report=c.read(root/reference['path'])
        observed=report['observed_at']
        missing=[row['pin'] for row in report['rows'] if not row['sample'] or
                 row['sample']['receipt']['outcome']!='VERIFIED']
    gate={'schema':'jevops.lean-refactor.native-pin-gate.v1','frontier':reference,
          'missing_pins':missing,'retry_after_seconds':900,
          'retry_generation':max(0,int((now-observed)//900)) if missing or reference is None else 0,
          **c.AUTH}
    c.save(root/c.RUNTIME/'native-pin-gate.json',gate)
    return gate

def validate(root,reference):
    """Recheck pinned imports and native baseline evidence independently."""
    from jevops import arena,arena_lean,arena_prepare
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    from validate_lean_refactor_coupled_pilot import sample_check
    path=root/reference['path'];c.require(c.sha(path)==reference['sha256'],'frontier archive changed')
    report=c.read(path);m=c.module(root,'lean_refactor_project_readiness.py')
    record=next(r for r in m.records() if r['name']==TARGET)
    c.require(report['schema']==SCHEMA and report['target']==TARGET and
        report['baseline_sha256']==c.sha(root/c.RUNTIME/'JLR-017.result.json') and
        report['record_sha256']==arena.content_hash(record) and
        report['producer_sha256']==c.sha(root/'tools/lean_refactor_native_pin_frontier.py'),
        'frontier source/input binding differs')
    expected_sources=('tools/lean_refactor_native_pin_frontier.py','tools/lean_refactor_project_readiness.py',
                      'tools/validate_lean_refactor_native_pin_frontier.py','jevops/arena_lean.py')
    c.require(report['source_sha256']=={name:c.sha(root/name) for name in expected_sources},
              'supplemental producer/validator/native source drift')
    c.require(report['requested_pins']==[list(p) for p in plan(root,record)] and
              report['model_calls']==0 and report['training_executed'] is False and
              report['proof_authority'] is False and report['completion_authority'] is False and
              report['max_native_processes']==2 and 0<=report['wall_seconds']<=MAX_SECONDS+15,
              'frontier budget/population differs')
    for observed in report['commands']:
        for key in ('stdout','stderr'):
            c.require(c.sha(Path(observed[key]))==observed[key+'_sha256'],'frontier subprocess log changed')
    ready=c.read(root/report['readiness_path'])
    c.require(c.sha(root/report['readiness_path'])==report['readiness_sha256'] and
              ready['schema']==m.SCHEMA and ready['producer_sha256']==c.sha(root/'tools/lean_refactor_project_readiness.py')
              and ready['corpus_sha256']==m.CORPUS_SHA and ready['storage_cap_bytes']==m.MAX_BYTES,
              'supplemental readiness binding differs')
    pilot=Path(ready['pilot_root']);arena_prepare.validate_volume(c.read(pilot/'preparation.json'))
    expected=[{'lean_tag':tag,'git_commit':commit} for tag,commit in plan(root,record)]
    c.require([r['pin'] for r in report['rows']]==expected,'supplemental exact pin denominator differs')
    for row in report['rows']:
        pin=VersionPin(**row['pin'])
        current=next(r for r in ready['rows'] if r['name']==TARGET and
                     (r['lean_tag'],r['git_commit'])==(pin.lean_tag,pin.git_commit))
        if row['sample'] is None:
            c.require(row['reason'] and (current['status']!='READY' or
                      row['reason']==['native baseline admission deadline']),
                      'missing pin manufactured a proof');continue
        c.require(current['status']=='READY' and row['project']==current['project'],'supplemental project changed')
        binding=arena_lean.project_binding(record,pin,row['project'],Path(ready['elan_home']))
        c.require(binding.fingerprint(Fingerprinter(strict=True))==current['binding_sha256'],'supplemental pin drift')
        imports=m.import_plan(binding.root,binding.lake,record,binding.lean)
        c.require(not m.checked_artifacts(imports,[binding.root,*[p.root for p in binding.lake.packages]],
                                         binding.lean,pilot/'work'),'supplemental import custody differs')
        guard=arena_lean.NativeLeanVerifier({pin:binding},max_processes=0,timeout=45,
                                          fingerprinter=Fingerprinter(strict=True))
        sample_check(row['sample'],record,pin,guard,record['src'])
    return report,ready

