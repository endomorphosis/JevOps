from pathlib import Path
import importlib.util
_spec = importlib.util.spec_from_file_location('_canonical_compiled_registry',
    Path(__file__).with_name('lean_refactor_compiled_registry_v1.py'))
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)
import lean_refactor_execution_v2 as c
ROOT = c.ROOT
runtime = registry.runtime(ROOT)
import json
import shutil
import sys
import tempfile
import time
import uuid
with registry.retained_imports(ROOT):
    from membership_observation import FreshMembership
    from phase_closure import close_bound
protected = registry.peer('validate_lean_refactor_compiled_coupled_v1.py')
m, c, p, v = runtime.m, runtime.c, runtime.p, runtime.v
legacy, compiled = m.stage, m.stage.compiled
base, arena = registry.peer('lean_refactor_compiled_inputs_v1.py'), legacy.arena
PINS, LIMITS = legacy.PINS, legacy.LIMITS
schedule, reserve = legacy.schedule, legacy.reserve


def freeze():
    profile, active = registry.registered(ROOT, c)
    lineage = registry.peer('lean_refactor_compiled_lineage_v1.py')
    lineage.contract(ROOT)
    record = next(row for row in c.module(ROOT,'lean_refactor_project_readiness.py').records()
                  if row['name'] == base.qualifier.nominations.TARGET)
    pins = {tag:commit for version in record['version_info'] for tag,commit in version.items()}
    c.require(pins == base.PINS and len(record['version_info']) == 3, 'original exact cohort required')
    drafts = base.qualifier.nominations.proposals(record)
    for draft in drafts: base.protected.edit_check(record,draft)
    c.require(len(drafts)==2 and [d['arm'] for d in drafts]==['isolated','coupled']
        and drafts[0]['edits'][0]==drafts[1]['edits'][0], 'unchanged fixed matched pair required')
    c.require(arena.reference_tokens(drafts[1]['source'],record['statement'])
        < arena.reference_tokens(record['src'],record['statement']), 'actual shorter nomination required')
    reviewer = base.qualifier.module(legacy.OWNERSHIP_REVIEW,'_canonical_owned_source_review')
    review = reviewer.source_review((ROOT/'jevops/lean/ArenaAuditCheck.lean').read_text(),
                                   legacy.ACTIVE_DRIVER.read_text())
    return {'schema':'jevops.lean-refactor.canonical-compiled-frozen.v1','policy':base.POLICY,
        'record':record,'drafts':drafts,'pins':pins,'source_sha256':active,
        'scientific_sources':profile['source_sha256'],'profile_sha256':c.sha(ROOT/c.PROFILE),
        'baseline_sha256':c.sha(ROOT/c.RUNTIME/'JLR-017.result.json'),
        'original_acceptance':next(t['acceptance'] for t in c.effective_goals(ROOT,profile)['tasks']
                                   if t['id']=='JLR-020'),
        'original_fallback':record['src'],'max_producer_native_processes':24,
        'max_pin_trial_seconds':780,'protected_pin_seconds':360,
        'active_compiled_scientific_sources':active,'owned_audit_source_review':review,
        'physical_runtime_policy':'fresh-owned-physical-inputs-with-final-original-reread/v1',**base.AUTH}


def population(binding, work, record, identity, original_driver):
    ready = c.module(ROOT, 'lean_refactor_project_readiness.py')
    roots = [binding.root, *[pkg.root for pkg in binding.lake.packages]]
    plan = ready.import_plan(binding.root, binding.lake, record, binding.lean)
    def primary():
        return m.previous.streaming.population(ready, roots, binding.lean)
    def extra():
        extra = [*legacy.fresh_fingerprints.inputs(compiled, binding), original_driver, legacy.ACTIVE_DRIVER]
        for item in plan:
            target = Path(item['package']) / '.lake/build/lib/lean' / Path(*item['module'].split('.')).with_suffix('.olean')
            extra.extend(m.import_artifacts(target, binding.pin.to_dict(), binding.lean))
            key = ready.sha(ready.canonical({'module': item, 'input_identity': identity}))
            extra.append(work / 'compile-receipts' / (key + '.json'))
        return sorted(set(extra))
    members = FreshMembership(primary, extra)
    return ready, roots, plan, members


def scan(row, name, scratch, packet, members, original):
    started = time.monotonic()
    values = v.scan(scratch, packet, members, original=original)
    row['scans'][name] = {'seconds': time.monotonic() - started,
        'logical_digest_map_sha256': arena.content_hash(values)}
    return values


def run(directory, frozen, fence, admission, *, phase_start):
    from lean_refactor_metric_audit import resource_snapshot
    c.require(frozen == freeze() and callable(admission) and not directory.exists()
        and directory.parent.resolve().is_relative_to((ROOT / c.RUNTIME).resolve()),
        'new source-reviewed complete phase and explicit admission required')
    c.require(callable(fence) and fence(), 'current registered native actor required')
    started = phase_start
    original_capture, original_driver = compiled.capture, compiled.DRIVER
    snapshots = {}
    data = {'schema': 'jevops.lean-refactor.canonical-physical-complete-coupled.v1',
        'status': 'RUNNING', 'limits': LIMITS, 'source_sha256': frozen['source_sha256'],
        'scientific_sources': frozen['scientific_sources'], 'frozen_sha256': arena.content_hash(frozen),
        'native_processes': 0, 'build_processes': 0, 'pins': {}, 'started_at': time.time(), **base.AUTH}
    directory.mkdir()
    def persist():
        data['wall_seconds'] = time.monotonic() - started
        c.save(directory / 'observation.json', data)
    persist()
    try:
        with base.bounded(780, started) as deadline, legacy.fresh_fingerprints.scoped(compiled):
            def admit(seconds=65):
                c.require(deadline - time.monotonic() >= seconds
                    and fence()
                    and resource_snapshot(ROOT)['eligible'], 'original shared deadline/fence/resources changed')
                admission(deadline, seconds)
            compiled.DRIVER = legacy.ACTIVE_DRIVER
            for tag in PINS:
                admit(125)
                record, pin, binding, work = base.inputs(tag)
                expected = c.read(m.PRIOR / 'parallel-cpu-v1/observation.json')['pins'][tag]['producer_scan']
                identity = expected['identity']
                ready, roots, plan, members = population(binding, work, record, identity, original_driver)
                primary = m.previous.streaming.population(ready, roots, binding.lean)
                pin_dir = directory / tag; pin_dir.mkdir()
                row = {'schema': 'jevops.lean-refactor.compiled-coupled-pin.v1', 'policy': base.POLICY,
                    'mode': 'producer', 'pin': tag, 'status': 'RUNNING', 'winner': None,
                    'frozen_sha256': arena.content_hash(frozen), 'source_sha256': frozen['source_sha256'],
                    'scientific_sources': frozen['scientific_sources'], 'started_at': time.time(),
                    'max_seconds': 780, 'max_native_processes': 7, 'max_build_processes': 2,
                    'native_processes': 0, 'build_processes': 0, 'candidate_native_trials': 0,
                    'capture_processes_in_input': 1, 'steps': [], 'rows': [], 'scans': {}, **base.AUTH}
                data['pins'][tag] = row
                pin_started = time.monotonic()
                def pin_persist():
                    row['wall_seconds'] = time.monotonic() - pin_started
                    c.save(pin_dir / 'observation.json', row); persist()
                row['memory_admission'] = m.memory_admission()
                scratch = Path(tempfile.mkdtemp(prefix='jevops-complete-input-', dir='/dev/shm'))
                root_identity = p.owned_root(scratch)
                snapshots[tag] = {'root': scratch, 'identity': root_identity, 'row': row,
                    'directory': pin_dir, 'record': record, 'pin': pin, 'binding': binding, 'work': work,
                    'members': members, 'ready': ready, 'roots': roots, 'plan': plan}
                row.update(physical_snapshot_root=str(scratch), snapshot_removed=False)
                pin_persist()
                t = time.monotonic(); packet = p.create(scratch, members)
                row['copy_setup_seconds'] = time.monotonic() - t
                snapshots[tag]['packet'] = packet
                c.save(pin_dir / 'copy-packet.json', packet)
                c.require(ready.sha(ready.canonical({str(path): packet[str(path)]['sha256'] for path in primary})) == identity,
                          'fresh complete original compiler/stdlib/package identity differs')
                c.require(not ready.checked_artifacts(plan, roots, binding.lean, work, identity=identity),
                          'current exact original import receipts differ')
                custody = base.protected.import_custody(record, binding, work, identity)
                c.require(arena.content_hash(custody) == expected['import_custody_sha256'],
                          'exact original serialized import custody differs')
                row.update(import_identity=identity, import_custody=custody,
                    parser_capture=base.capture_input(tag, record, pin, binding, identity, frozen['drafts']))
                context, context_sha = v.explicit_context(scratch, packet, identity, pin.to_dict())
                c.save(pin_dir / 'snapshot-context.json', context)
                row['physical_context_sha256'] = context_sha
                row['physical_search_binding'] = runtime.prepare_search_paths(scratch, packet, binding)
                scan(row, 'producer_snapshot', scratch, packet, members, False); pin_persist()
                def observed(argv, path, env, payload, timeout):
                    admit(); kind = 'native' if payload else 'build'
                    field, cap = ('native_processes', 7) if payload else ('build_processes', 2)
                    c.require(row[field] < cap and timeout == 60, 'original child budget/guard changed')
                    if payload:
                        c.require(env == runtime.environment(scratch, packet, binding, pin_dir),
                                  'explicit source-bound physical environment differs')
                    reserve(data, kind); row[field] += 1
                    if payload and payload.get('candidate') != payload.get('reference'):
                        row['candidate_native_trials'] += 1
                    pin_persist()
                    out, err, code, execution = original_capture(argv, path, env, payload, timeout)
                    raw = pin_dir / ('child-' + str(len(row['steps']))); raw.mkdir()
                    for name in ('input.json', 'stdout', 'stderr'):
                        (raw / name).write_bytes((path / name).read_bytes())
                    c.save(raw / 'execution.json', execution)
                    row['steps'].append({'kind': field, 'archive': raw.name, 'execution': execution,
                                         'environment': env})
                    pin_persist(); return out, err, code, execution
                compiled.capture = observed
                with compiled.prepare_checkers({pin: binding}) as checkers:
                    checker = checkers[pin]; row['compiled_build'] = checker.manifest
                    row['context'] = {'schema': base.POLICY, 'source_sha256': arena.source_hash(record['src']),
                        'statement_sha256': arena.source_hash(record['statement']), 'target': record['name'],
                        'pin': pin.to_dict(), 'prefix_sha256': arena.source_hash(binding.prefix),
                        'import_identity': identity, 'fresh_build_sha256': arena.content_hash(checker.manifest),
                        'import_custody_sha256': arena.content_hash(custody),
                        'scientific_sources': frozen['scientific_sources'], 'producer_sources': frozen['source_sha256'],
                        'historical_arena_context': False, 'proof_cache': False}
                    row['native_environment'] = runtime.environment(scratch, packet, binding, pin_dir)
                    def measure(kind, arm, source, order):
                        admit(); checker.validate(binding)
                        payload = {'request_id': uuid.uuid4().hex, 'target': record['name'],
                            'prefix': binding.prefix, 'reference': record['src'], 'candidate': source,
                            'max_heartbeats': 2_000_000, 'candidate_first': order == 'candidate-first'}
                        out, err, code, execution = compiled.capture([str(checker.executable)],
                            pin_dir / ('native-' + str(row['native_processes'])), row['native_environment'], payload, 60)
                        checker.validate(binding)
                        result = base.protected.native_sample(record, pin, binding, source, order,
                                                              payload, out, err, execution)
                        row['rows'].append({'kind': kind, 'arm': arm, 'source': source, 'branch_order': order,
                                            'raw': row['steps'][-1]['archive'], 'report': result})
                        pin_persist(); return result['outcome']
                    for kind, arm, source, order in schedule(frozen['drafts'], record['src']):
                        outcome = measure(kind, arm, source, order)
                        c.require(kind != 'baseline' or outcome == 'VERIFIED', 'actual original control failed')
                    outcomes = [item['report']['outcome'] for item in row['rows'] if item['arm'] == 'coupled']
                    if outcomes == ['VERIFIED', 'VERIFIED']:
                        row['winner'] = frozen['drafts'][1]['source']; pin_persist()
                        for order in base.ORDERS:
                            c.require(measure('confirmation', 'coupled', row['winner'], order) == 'VERIFIED',
                                      'frozen winner confirmation failed')
                        row['status'] = 'SCREENED_PIN'
                    else:
                        c.require('REJECTED' in outcomes, 'software failure cannot be a semantic negative')
                        row['status'] = 'NO_ALL_PIN_WINNER'
                compiled.capture = original_capture
                # All original/physical bytes are independently reread by
                # the protected validator after the last pin. The initial
                # full copy and producer snapshot scan remain mandatory.
                runtime.validate_search_paths(scratch, binding, row['physical_search_binding'])
                c.require(not ready.checked_artifacts(plan, roots, binding.lean, work, identity=identity)
                    and base.protected.import_custody(record, binding, work, identity) == custody,
                    'final exact original import receipt custody differs')
                pin_persist(); base.protected.validate_archive(pin_dir, row, frozen, record, pin, binding)
            data['status'] = ('QUALIFIED_ALL_PINS' if all(row['status'] == 'SCREENED_PIN'
                for row in data['pins'].values()) else 'NO_ALL_PIN_WINNER')
            persist()
            data['validation'] = protected.validate(directory, data, frozen, snapshots, started)
            c.require(frozen == freeze(), 'scientific source identity changed during complete phase')
            admit(1)
    except BaseException as exc:
        data.update(status='REFUSED', reason=str(exc), refusal_type=type(exc).__name__)
        raise
    finally:
        compiled.capture, compiled.DRIVER = original_capture, original_driver
        for snap in snapshots.values():
            scratch = snap['root']
            c.require(p.owned_root(scratch) == snap['identity'], 'remove only exact newly owned snapshot')
            shutil.rmtree(scratch)
            snap['row']['snapshot_removed'] = not scratch.exists()
            c.save(snap['directory'] / 'observation.json', snap['row'])
        data['snapshots_removed'] = all(row['snapshot_removed'] for row in data['pins'].values())
        data['finished_at'] = time.time(); persist()
        close_bound(data, time.monotonic()-started, persist)
    return data


def phase_path(root, frozen):
    return root/c.RUNTIME/'compiled-coupled-v1'/arena.content_hash(frozen)


def produce(root=ROOT):
    """ONE newly allocated canonical operation; no private result promotion."""
    c.require(root.resolve()==ROOT.resolve(), 'closed repository required')
    with registry.retained_imports(ROOT):
        actor=registry.peer('lean_refactor_compiled_admission_v1.py').admit(ROOT,'producer')
        frozen=freeze()
        registry.peer('lean_refactor_compiled_lineage_v1.py').retain_heads(ROOT)
        directory=phase_path(ROOT,frozen)
        c.require(not directory.exists(), 'unchanged compiled trial already spent; review changed inputs/source')
        directory.mkdir(parents=True)
        started=time.monotonic()
        data={'schema':'jevops.lean-refactor.canonical-coupled-workflow.v1',
            'status':'RUNNING','started_at':time.time(),'native_processes':0,'build_processes':0,
            'native_actor_verified':True,'production_sources_unchanged':False,**base.AUTH}
        def persist():
            data['wall_seconds']=time.monotonic()-started
            c.save(directory/'phase-ledger.json',data)
        persist()
        try:
            def admission(deadline,required):
                c.require(deadline==started+780 and deadline-time.monotonic()>=required,
                          'original complete admission clock changed')
                actor['guard'](deadline-time.monotonic()+30)
            result=run(directory/'producer',frozen,actor['guard'],admission,phase_start=started)
            data.update(status=result['status'],native_processes=result['native_processes'],
                build_processes=result['build_processes'],
                actual_observation_sha256=c.sha(directory/'producer/observation.json'))
        except BaseException as exc:
            data.update(status='REFUSED',reason=str(exc),refusal_type=type(exc).__name__)
            raise
        finally:
            nested=directory/'producer/observation.json'
            if nested.exists():
                observed=c.read(nested,max_bytes=32*1024**2)
                data.update(native_processes=observed['native_processes'],build_processes=observed['build_processes'])
            data.update(finished_at=time.time(),production_sources_unchanged=c.sources(ROOT)==frozen['scientific_sources'])
            persist();c.save(directory/'observation.json',data)
            close_bound(data,time.monotonic()-started,lambda:(persist(),c.save(directory/'observation.json',data)))
        report={'schema':'jevops.lean-refactor.canonical-coupled-result.v1','status':data['status'],
            'frozen':frozen,'producer':{'path':str(directory.relative_to(ROOT)),
                'envelope_sha256':c.sha(directory/'observation.json'),
                'observation_sha256':c.sha(directory/'producer/observation.json')},
            'model_calls':0,'original_fallback':frozen['original_fallback'],**c.AUTH}
        c.save(ROOT/c.RUNTIME/'JLR-020.partial.json',report)
        close_bound(data,time.monotonic()-started,lambda:(persist(),c.save(directory/'observation.json',data)))
        return report


def admission_wait(root, *, publish=True):
    """A spent unchanged operation stays spent, including software refusals."""
    frozen=freeze()
    directory=phase_path(root,frozen)
    if not directory.exists():return None
    path=directory/'phase-ledger.json'
    c.require(path.is_file(), 'allocated compiled phase lacks its durable interruption evidence')
    phase=c.read(path)
    c.require(phase['schema']=='jevops.lean-refactor.canonical-coupled-workflow.v1'
        and phase['status'] in ('RUNNING','REFUSED','QUALIFIED_ALL_PINS','NO_ALL_PIN_WINNER'),
        'compiled phase ledger identity differs')
    # A fresh protected validator must inspect a successful producer. Ordinary
    # production still refuses to allocate that same unchanged operation again.
    if phase['status']=='QUALIFIED_ALL_PINS' and not publish:return None
    gate={'schema':'jevops.lean-refactor.compiled-coupled-admission.v1','task_id':'JLR-020',
        'reason':'unchanged_complete_compiled_trial_spent','phase_status':phase['status'],
        'retained_phase_path':str(directory.relative_to(root)),'retained_ledger_sha256':c.sha(path),
        'acceptance_satisfied':False,'model_calls':0,
        'retry_condition':'separately review changed mechanical source/input evidence; never reset this phase',**c.AUTH}
    if not publish:return gate
    c.save(root/c.RUNTIME/'native-pin-gate.json',gate)
    archive=root/c.RUNTIME/'runs'/('JLR-020-admission-'+uuid.uuid4().hex)/'receipt.json'
    receipt={**gate,'exit_code':75,'observed_at':time.time(),
        'archive_path':str(archive.relative_to(root)),'scientific_run_receipt_preserved':True}
    c.save(archive,receipt)
    return receipt
