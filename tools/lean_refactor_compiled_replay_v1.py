"""Single-use protected replay of ONE complete physical-input producer.

Fresh snapshots, checker builds and native requests are mandatory. Historical
contexts and receipts remain read-only. This private qualification cannot
register, activate or complete a campaign task.
"""
from pathlib import Path
import json
import math
import os
import shutil
import signal
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

from contextlib import nullcontext
import importlib.util
_spec=importlib.util.spec_from_file_location('_canonical_replay_registry',
    Path(__file__).with_name('lean_refactor_compiled_registry_v1.py'))
registry=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)
stage=registry.peer('lean_refactor_compiled_coupled_v1.py')
protected=registry.peer('validate_lean_refactor_compiled_replay_v1.py')
c,base,compiled=stage.c,stage.base,stage.compiled
ROOT=c.ROOT
LIMITS = {'seconds': 780, 'admission_seconds': 900, 'stage_seconds': 900,
          'native_children': 6, 'build_children': 6, 'child_seconds': 60,
          'memory_bytes': 4 * 1024**3, 'artifact_bytes': 128 * 1024**2,
          'maximum_workers': 2, 'maximum_submissions': 2}


def allocate(data, kind):
    field = {'native': 'native_processes', 'build': 'build_processes'}.get(kind)
    c.require(field is not None and type(data.get(field)) is int and 0 <= data[field] < 6,
              'protected whole-operation child denominator spent')
    data[field] += 1


def close(data, elapsed, persist):
    c.require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed > 0,
              'actual finite positive cleanup clock required')
    if data['status'] == 'ALL_PIN_REPLAY_VERIFIED' and elapsed > 780:
        data.update(status='REFUSED', reason='protected cleanup exceeded unchanged 780-second clock',
                    refusal_type='TimeoutError', wall_seconds=elapsed)
        persist()
        raise TimeoutError(data['reason'])


_SOURCE_MAPS=('scientific_sources','source_sha256','active_compiled_scientific_sources')
# The inventory records the reviewed extension, and this validator recognizes it.
# Neither file is part of the coupled proof that JLR-020 already qualified.
_ALLOWED_REGISTRATION_FILES=(
    'tools/lean_refactor_compiled_sources_v1.json',
    'tools/lean_refactor_compiled_replay_v1.py',
)
_FORBIDDEN_EXTENSIONS={
    'tools/lean_refactor_coupled_pilot.py',
    'tools/validate_lean_refactor_coupled_pilot.py',
    'tools/lean_refactor_compiled_coupled_v1.py',
    'tools/validate_lean_refactor_compiled_coupled_v1.py',
    'tools/lean_refactor_compiled_inputs_v1.py',
    'tools/lean_refactor_compiled_admission_v1.py',
    'tools/lean_refactor_compiled_lineage_v1.py',
    'tools/lean_refactor_compiled_registry_v1.py',
}


def reviewed_extension_keeps_qualification(stored, current):
    """True when a later reviewed extension leaves the qualified coupled proof intact.

    JevOps sources, the coupled producer, and its compiled proof machinery stay
    bound to the qualified archive. A listed extension may change around them.
    Republishing that extension changes ``profile_sha256``; the archive itself
    does not move.
    """
    if type(stored) is not dict or type(current) is not dict or set(stored)!=set(current):
        return False
    for key, value in stored.items():
        if key in _SOURCE_MAPS or key=='profile_sha256':continue
        if value!=current[key]:return False
    allowed=set(registry.inventory()['extension_changes'])|set(_ALLOWED_REGISTRATION_FILES)
    diffs=set()
    for key in _SOURCE_MAPS:
        left, right=stored.get(key), current.get(key)
        if type(left) is not dict or type(right) is not dict:return False
        diffs.update(name for name in set(left)|set(right) if left.get(name)!=right.get(name))
    if not diffs or not diffs<=allowed:return False
    if any(name.startswith('jevops/') or name in _FORBIDDEN_EXTENSIONS for name in diffs):
        return False
    return True


def historical_coupled_qualification(parent, result):
    """Authenticate the stored all-pin archive without launching another native replay."""
    c.require(result['status']=='QUALIFIED_ALL_PINS'
        and parent==stage.phase_path(ROOT, result['frozen'])
        and parent.is_dir() and not parent.is_symlink(),
        'stored coupled qualification is not the current complete producer')
    envelope=c.read(parent/'observation.json')
    observed=c.read(parent/'producer/observation.json', max_bytes=32*1024**2)
    c.require(c.sha(parent/'observation.json')==result['producer']['envelope_sha256']
        and c.sha(parent/'producer/observation.json')==result['producer']['observation_sha256']
        and envelope['status']==observed['status']=='QUALIFIED_ALL_PINS'
        and envelope['native_actor_verified'] is True
        and envelope['production_sources_unchanged'] is True
        and observed.get('snapshots_removed') is True
        and type(envelope.get('wall_seconds')) in (int, float) and 0<envelope['wall_seconds']<=780
        and result['model_calls']==0
        and result['original_fallback']==result['frozen']['original_fallback']
        and all(result.get(key) is False for key in c.AUTH),
        'historical canonical qualification archive differs')
    return {'schema':'jevops.lean-refactor.historical-coupled-qualification.v1',
        'historical_qualification':True,'all_original_pins':3,
        'path':str(parent.relative_to(ROOT)),'sha256':c.sha(parent/'observation.json'),
        'native_replay':False,'proof_authority':False,'completion_authority':False}


def _protect(root, result):
    from lean_refactor_metric_audit import resource_snapshot
    c.require(root.resolve()==ROOT.resolve(), 'closed repository required')
    profile,active=registry.registered(ROOT,c)
    actor=registry.peer('lean_refactor_compiled_admission_v1.py').admit(ROOT,'validator')
    PARENT=ROOT/result['producer']['path']
    c.require(PARENT.resolve().is_relative_to((ROOT/c.RUNTIME/'compiled-coupled-v1').resolve())
        and not PARENT.is_symlink(), 'canonical producer archive required')
    frozen=stage.freeze()
    if result.get('frozen')!=frozen:
        c.require(result['schema']=='jevops.lean-refactor.canonical-coupled-result.v1'
            and result['status']=='QUALIFIED_ALL_PINS'
            and reviewed_extension_keeps_qualification(result['frozen'], frozen),
            'current complete canonical producer required; private qualifications cannot be promoted')
        return historical_coupled_qualification(PARENT, result)
    c.require(result['schema']=='jevops.lean-refactor.canonical-coupled-result.v1'
        and result['status'] in ('QUALIFIED_ALL_PINS','NO_ALL_PIN_WINNER') and result['frozen']==frozen
        and result['model_calls']==0 and result['original_fallback']==frozen['original_fallback']
        and all(result.get(key) is False for key in c.AUTH)
        and PARENT==stage.phase_path(ROOT,frozen),
        'current complete canonical producer required; private qualifications cannot be promoted')
    if result['status']=='NO_ALL_PIN_WINNER':
        negative(PARENT,result,stage)
        raise c.GateWait('valid bounded coupled trial found no all-pin shorter winner; unchanged phase remains spent')
    prepared={'frozen':frozen,'sources':active,'limits':LIMITS,'parent':result['producer']}
    c.require(resource_snapshot(ROOT)['eligible'], 'fresh CPU resources required')
    directory=ROOT/c.RUNTIME/'acceptance'/('JLR-020-'+uuid.uuid4().hex)
    directory.mkdir(parents=True)
    started = time.monotonic()
    data = {'schema': 'jevops.lean-refactor.canonical-physical-replay.v1', 'status': 'RUNNING',
        'limits': LIMITS, 'prepared_sha256': stage.arena.content_hash(prepared),
        'parent': prepared['parent'], 'source_sha256': prepared['sources'],
        'scientific_sources': prepared['frozen']['scientific_sources'],
        'started_at': time.time(), 'native_processes': 0, 'build_processes': 0, 'pins': {}, **base.AUTH}
    snapshots = {}
    old_capture, old_driver = compiled.capture, compiled.DRIVER
    def persist():
        data['wall_seconds'] = time.monotonic() - started
        c.save(directory / 'observation.json', data)
    def stop(sig, frame):
        raise InterruptedError('protected foreground interruption ' + str(sig))
    handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    persist()
    try:
        with base.bounded(780, started) as deadline, stage.legacy.fresh_fingerprints.scoped(compiled):
            with nullcontext():
                def admit(seconds=65):
                    remaining = deadline - time.monotonic()
                    c.require(remaining >= seconds and actor['guard']()
                        and resource_snapshot(ROOT)['eligible'], 'original replay clock/fence/resources changed')
                    if actor['mode']=='registered_native': actor['guard'](remaining+30)
                compiled.DRIVER = stage.legacy.ACTIVE_DRIVER
                admit(125)
                data['parent_validation'] = protected.validate_parent(PARENT, prepared, stage)
                persist()
                for tag in stage.PINS:
                    admit(125)
                    record, pin, binding, work = base.inputs(tag)
                    parent = c.read(PARENT / 'producer/observation.json')['pins'][tag]
                    identity = parent['import_identity']
                    ready, roots, plan, members = stage.population(binding, work, record, identity, old_driver)
                    pin_dir = directory / tag; pin_dir.mkdir()
                    row = {'pin': pin.to_dict(), 'import_identity': identity, 'steps': [], 'rows': [],
                        'scans': {}, 'snapshot_removed': False}
                    data['pins'][tag] = row; persist()
                    stage.m.memory_admission()
                    scratch = Path(tempfile.mkdtemp(prefix='jevops-protected-input-', dir='/dev/shm'))
                    snap = {'root': scratch, 'identity': stage.p.owned_root(scratch), 'binding': binding,
                        'record': record, 'work': work, 'ready': ready, 'roots': roots, 'plan': plan,
                        'members': members, 'directory': pin_dir}
                    snapshots[tag] = snap
                    row['physical_snapshot_root'] = str(scratch)
                    t = time.monotonic(); packet = stage.p.create(scratch, members)
                    row['copy_setup_seconds'] = time.monotonic() - t; snap['packet'] = packet
                    primary = members.events[-1][1]
                    c.require(ready.sha(ready.canonical({str(path): packet[str(path)]['sha256'] for path in primary})) == identity
                        and not ready.checked_artifacts(plan, roots, binding.lean, work, identity=identity),
                        'fresh complete original source/pin/artifact identity differs')
                    row['import_custody'] = base.protected.import_custody(record, binding, work, identity)
                    c.require(row['import_custody'] == parent['import_custody'], 'current exact serialized imports differ')
                    row['parser_capture'] = base.capture_input(tag, record, pin, binding, identity, prepared['frozen']['drafts'])
                    context, digest = stage.v.explicit_context(scratch, packet, identity, pin.to_dict())
                    row['physical_context_sha256'] = digest
                    c.save(pin_dir / 'copy-packet.json', packet); c.save(pin_dir / 'snapshot-context.json', context)
                    row['physical_search_binding'] = stage.runtime.prepare_search_paths(scratch, packet, binding)
                    stage.scan(row, 'producer_snapshot', scratch, packet, members, False)
                    row['native_environment'] = stage.runtime.environment(scratch, packet, binding, pin_dir)
                    def observed(argv, path, env, payload, timeout):
                        admit(); kind = 'native' if payload else 'build'
                        c.require(timeout == 60, 'unchanged protected child clock required')
                        if payload:
                            c.require(env == row['native_environment'], 'explicit protected physical environment differs')
                        allocate(data, kind); persist()
                        out, err, code, execution = old_capture(argv, path, env, payload, timeout)
                        raw = pin_dir / ('child-' + str(len(row['steps']))); raw.mkdir()
                        for name in ('input.json', 'stdout', 'stderr'):
                            (raw / name).write_bytes((path / name).read_bytes())
                        c.save(raw / 'execution.json', execution)
                        row['steps'].append({'kind': kind, 'archive': raw.name, 'execution': execution, 'environment': env})
                        persist(); return out, err, code, execution
                    compiled.capture = observed
                    with compiled.prepare_checkers({pin: binding}) as checkers:
                        checker = checkers[pin]; row['compiled_build'] = checker.manifest; persist()
                        for order in base.ORDERS:
                            admit(); checker.validate(binding)
                            payload = {'request_id': uuid.uuid4().hex, 'target': record['name'],
                                'prefix': binding.prefix, 'reference': record['src'],
                                'candidate': prepared['frozen']['drafts'][1]['source'],
                                'max_heartbeats': 2_000_000, 'candidate_first': order == 'candidate-first'}
                            out, err, code, execution = compiled.capture([str(checker.executable)],
                                pin_dir / ('native-' + order), row['native_environment'], payload, 60)
                            checker.validate(binding)
                            report = base.protected.native_sample(record, pin, binding, payload['candidate'],
                                order, payload, out, err, execution)
                            c.require(report['outcome'] == 'VERIFIED', 'fresh protected whole-source replay failed')
                            row['rows'].append({'branch_order': order, 'raw': row['steps'][-1]['archive'], 'report': report})
                            persist()
                    compiled.capture = old_capture
                data['status'] = 'ALL_PIN_REPLAY_VERIFIED'; persist()
                data['validation'] = protected.validate(directory, data, prepared, snapshots, stage, started)
                c.require(prepared['frozen']==stage.freeze(), 'source-bound replay or parent changed')
                admit(1)
    except BaseException as exc:
        data.update(status='REFUSED', reason=str(exc), refusal_type=type(exc).__name__)
        raise
    finally:
        compiled.capture, compiled.DRIVER = old_capture, old_driver
        try:
            for tag, snap in snapshots.items():
                c.require(stage.p.owned_root(snap['root']) == snap['identity'], 'remove only exact own fresh snapshot')
                shutil.rmtree(snap['root'])
                data['pins'][tag]['snapshot_removed'] = not snap['root'].exists()
            data.update(finished_at=time.time(), snapshots_removed=all(row['snapshot_removed'] for row in data['pins'].values()),
                native_actor_verified=actor['guard'](),
                production_sources_unchanged=c.sources(ROOT) == prepared['frozen']['scientific_sources'])
            persist(); close(data, time.monotonic() - started, persist)
        except BaseException as exc:
            data.update(status='REFUSED', cleanup_reason=str(exc), cleanup_refusal_type=type(exc).__name__)
            persist()
            raise
        finally:
            for sig, handler in handlers.items(): signal.signal(sig, handler)
    return {'all_original_pins':3,'fresh_protected_native_orders':6,
        'path':str(directory.relative_to(ROOT)),'sha256':c.sha(directory/'observation.json'),
        'proof_authority':False,'completion_authority':False}


def protect(root, result):
    with registry.retained_imports(ROOT):
        return _protect(root,result)


def negative(parent,result,stage):
    """Classify actual semantic rejection separately from missing execution."""
    c,base=stage.c,stage.base
    envelope=c.read(parent/'observation.json')
    data=c.read(parent/'producer/observation.json',max_bytes=32*1024**2)
    c.require(c.sha(parent/'observation.json')==result['producer']['envelope_sha256']
        and c.sha(parent/'producer/observation.json')==result['producer']['observation_sha256']
        and envelope['status']==data['status']=='NO_ALL_PIN_WINNER'
        and envelope['native_actor_verified'] is envelope['production_sources_unchanged'] is True
        and data['snapshots_removed'] is True and 0<envelope['wall_seconds']<=780,
        'negative trial needs actual bounded complete canonical execution')
    stage.protected.complete(data);stage.protected.binding(data,result['frozen'])
    for tag in stage.PINS:
        record,pin,binding,work=base.inputs(tag)
        row=data['pins'][tag]
        c.require(row['snapshot_removed'] is True, 'negative trial snapshot cleanup missing')
        base.protected.validate_archive(parent/'producer'/tag,row,result['frozen'],record,pin,binding)
        protected.build_packets(parent/'producer'/tag,row,c)
    return {'status':'VALID_NEGATIVE','unsatisfied_acceptance':'shorter independently verified all-pin winner',
        'rearm_requires_changed_reviewed_strategy_or_mechanical_sources':True,**c.AUTH}
