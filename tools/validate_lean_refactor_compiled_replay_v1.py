"""Independent parent, transport, physical-context and exact-input checks."""
from pathlib import Path
import hashlib
import json
import math
import re
import time


def require(ok, message):
    if not ok: raise ValueError(message)


def positive_clock(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= 780


def parent_shape(envelope, data, pins, limits):
    require(envelope.get('status') == data.get('status') == 'QUALIFIED_ALL_PINS'
        and data.get('schema') == 'jevops.lean-refactor.canonical-physical-complete-coupled.v1'
        and data.get('limits') == limits and set(data.get('pins', {})) == set(pins),
        'one complete bounded successful producer required')
    require(positive_clock(data.get('wall_seconds')) and positive_clock(envelope.get('wall_seconds'))
        and all(type(item.get(key)) is int and item[key] == count
            for item in (envelope, data) for key, count in (('native_processes', 21), ('build_processes', 6))),
        'complete unchanged producer clock and 24-process denominator required')
    require(envelope.get('native_actor_verified') is envelope.get('production_sources_unchanged') is True
        and data.get('snapshots_removed') is True
        and all(row.get('status') == 'SCREENED_PIN' and row.get('snapshot_removed') is True
            and row.get('native_processes') == 7 and row.get('build_processes') == 2
            for row in data['pins'].values()), 'producer cleanup and every original pin required')
    require(data.get('validation', {}).get('all_original_pins') == 3
        and data['validation'].get('native_samples') == 21
        and set(data['validation'].get('fresh_final_original_and_physical_checks_seconds', {})) == set(pins),
        'producer independent final original/physical acceptance required')
    for item in (envelope, data):
        require(type(item.get('model_calls')) is int and item['model_calls'] == 0
            and all(item.get(key) is False for key in ('proof_authority', 'completion_authority',
                'scientific_acceptance_authority', 'registered', 'activated', 'promoted',
                'whole_campaign_complete', 'whole_target_all_pins_accepted')),
            'private producer cannot spend providers or assert campaign authority')


def shape(data, pins, limits):
    require(data.get('schema') == 'jevops.lean-refactor.canonical-physical-replay.v1'
        and data.get('status') == 'ALL_PIN_REPLAY_VERIFIED' and data.get('limits') == limits
        and positive_clock(data.get('wall_seconds')) and set(data.get('pins', {})) == set(pins),
        'complete successful protected phase within unchanged clock required')
    require(all(type(data.get(key)) is int and data[key] == 6
        for key in ('native_processes', 'build_processes')), 'all six fresh protected orders and builds required')
    require(type(data.get('model_calls')) is int and data['model_calls'] == 0
        and all(data.get(key) is False for key in ('proof_authority', 'completion_authority',
            'scientific_acceptance_authority', 'registered', 'activated', 'promoted',
            'whole_campaign_complete', 'whole_target_all_pins_accepted')),
        'private replay has no provider or campaign acceptance authority')


def raw(directory, name):
    require(type(name) is str and re.fullmatch(r'child-[0-9]+', name) is not None,
            'ordinary single-component child archive required')
    path = directory / name
    require(path.is_dir() and not path.is_symlink() and path.resolve().parent == directory.resolve(),
            'child directory escapes protected archive')
    for leaf in ('input.json', 'stdout', 'stderr', 'execution.json'):
        require((path / leaf).is_file() and not (path / leaf).is_symlink(), 'ordinary raw packet required')
    return path


def validate_parent(parent, prepared, stage):
    c, base = stage.c, stage.base
    require(str(parent.relative_to(stage.ROOT)) == prepared['parent']['path'], 'exact reviewed parent path required')
    envelope, data = c.read(parent / 'observation.json'), c.read(parent / 'producer/observation.json')
    parent_shape(envelope, data, stage.PINS, stage.LIMITS)
    require(c.sha(parent / 'observation.json') == prepared['parent']['envelope_sha256']
        and c.sha(parent / 'producer/observation.json') == prepared['parent']['observation_sha256'],
        'retained complete parent changed')
    ids = set()
    for tag in stage.PINS:
        record, pin, binding, work = base.inputs(tag)
        row = data['pins'][tag]
        stage.protected.binding(row, prepared['frozen'])
        base.protected.validate_archive(parent / 'producer' / tag, row, prepared['frozen'], record, pin, binding)
        build_packets(parent / 'producer' / tag, row, c)
        for sample in row['rows']:
            path = raw(parent / 'producer' / tag, sample['raw'])
            request = c.read(path / 'input.json')['request_id']
            require(request not in ids, 'parent native request duplicated across pins')
            ids.add(request)
    return {'all_original_pins': 3, 'actual_source_bound_native_samples': len(ids),
            'historical_snapshots_reused': False, 'proof_authority': False}


def build_packets(directory, row, c):
    """Bind the build manifest to the actual independent raw launch packets."""
    require(len(row['steps']) >= 2 and len(row['compiled_build']['steps']) == 2,
            'two actual source-bound build packets required')
    for index, kind in enumerate(('compile', 'link')):
        step = row['steps'][index]
        manifest = row['compiled_build']['steps'][index]
        path = raw(directory, step['archive'])
        payload, execution = c.read(path / 'input.json'), c.read(path / 'execution.json')
        stdout, stderr = (path / 'stdout').read_bytes(), (path / 'stderr').read_bytes()
        require(payload == {} and manifest.get('step') == kind
            and execution == step['execution']
            == {key: value for key, value in manifest.items() if key not in ('step', 'stdout', 'stderr')}
            and execution['input_sha256'] == hashlib.sha256(c.canonical(payload)).hexdigest()
            and execution['stdout_sha256'] == hashlib.sha256(stdout).hexdigest()
            and execution['stderr_sha256'] == hashlib.sha256(stderr).hexdigest()
            and manifest['stdout'] == stdout.decode(errors='replace')
            and manifest['stderr'] == stderr.decode(errors='replace'),
            'actual source-bound build transport or manifest differs')


def distinct_build(manifest, old_ids):
    identity = manifest.get('build_id')
    require(type(identity) is str and re.fullmatch('[0-9a-f]{32}', identity) is not None
        and identity not in old_ids, 'independent fresh per-pin build required')
    old_ids.add(identity)


def distinct_request(payload, old_ids):
    request = payload.get('request_id')
    require(type(request) is str and re.fullmatch('[0-9a-f]{32}', request) is not None
        and request not in old_ids, 'independent fresh native request required')
    old_ids.add(request)


def validate(directory, data, prepared, snapshots, stage, phase_start):
    from validate_lean_refactor_compiled_frontier import validate_build
    c, base = stage.c, stage.base
    shape(data, stage.PINS, prepared['limits'])
    require(data['source_sha256'] == prepared['sources']
        and data['scientific_sources'] == prepared['frozen']['scientific_sources']
        and data['parent'] == prepared['parent'] and set(snapshots) == set(stage.PINS)
        and stage.compiled.DRIVER == stage.legacy.ACTIVE_DRIVER, 'active scientific/replay source binding differs')
    parent = stage.ROOT / prepared['parent']['path']
    require(c.sha(parent / 'producer/observation.json') == prepared['parent']['observation_sha256'], 'complete parent changed')
    producer = c.read(parent / 'producer/observation.json')
    ids = {c.read(raw(parent / 'producer' / tag, sample['raw']) / 'input.json')['request_id']
        for tag in stage.PINS for sample in producer['pins'][tag]['rows']}
    builds = {row['compiled_build']['build_id'] for row in producer['pins'].values()}
    roots, timings = set(), {}
    for tag in stage.PINS:
        started = time.monotonic()
        record, pin, binding, work = base.inputs(tag)
        row, snap = data['pins'][tag], snapshots[tag]
        root, packet, members = snap['root'], snap['packet'], snap['members']
        require(binding == snap['binding'] and record == snap['record'] and work == snap['work']
            and row['pin'] == pin.to_dict() and row['import_identity'] == producer['pins'][tag]['import_identity'],
            'exact original source/pin/path binding changed')
        require(str(root) not in roots and stage.p.owned_root(root) == snap['identity'], 'distinct owned physical context required')
        roots.add(str(root))
        context, digest = stage.v.explicit_context(root, packet, row['import_identity'], pin.to_dict())
        require(c.read(snap['directory'] / 'copy-packet.json', max_bytes=64*1024**2) == json.loads(stage.p.canonical(packet))
            and c.read(snap['directory'] / 'snapshot-context.json', max_bytes=64*1024**2) == json.loads(stage.p.canonical(context))
            and digest == row['physical_context_sha256'], 'protected explicit physical input context differs')
        stage.runtime.validate_search_paths(root, binding, row['physical_search_binding'])
        env = stage.runtime.environment(root, packet, binding, snap['directory'])
        require(row['native_environment'] == env and all(step['environment'] == env
            for step in row['steps'] if step['kind'] == 'native'), 'actual protected physical child environment differs')
        mark = members.mark()
        originals = stage.v.scan(root, packet, members, original=True)
        primary = members.primary_between(mark)
        physical = stage.v.scan(root, packet, members, original=False)
        require(originals == physical, 'independent fresh original/snapshot bytes differ')
        ready = snap['ready']; identity = row['import_identity']
        require(ready.sha(ready.canonical({str(path): originals[str(path)] for path in primary})) == identity
            and not ready.checked_artifacts(snap['plan'], snap['roots'], binding.lean, work, identity=identity)
            and base.protected.import_custody(record, binding, work, identity) == row['import_custody']
            == producer['pins'][tag]['import_custody'], 'independent exact source/import/artifact custody differs')
        require(base.capture_input(tag, record, pin, binding, identity, prepared['frozen']['drafts']) == row['parser_capture'],
                'independent native parsed/dependency capture differs')
        validate_build(pin, binding, row['compiled_build'])
        build_packets(directory / tag, row, c)
        distinct_build(row['compiled_build'], builds)
        require([step['kind'] for step in row['steps']] == ['build', 'build', 'native', 'native']
            and len(row['rows']) == 2 and len({step['archive'] for step in row['steps']}) == 4,
            'all actual fresh build and protected children required exactly once')
        for index, order in enumerate(base.ORDERS):
            sample = row['rows'][index]
            require(sample['branch_order'] == order and sample['raw'] == row['steps'][index + 2]['archive'],
                    'both opposed protected orders required')
            path = raw(directory / tag, sample['raw'])
            payload, execution = c.read(path / 'input.json'), c.read(path / 'execution.json')
            distinct_request(payload, ids)
            report = base.protected.native_sample(record, pin, binding, prepared['frozen']['drafts'][1]['source'],
                order, payload, (path / 'stdout').read_bytes(), (path / 'stderr').read_bytes(), execution)
            require(report == sample['report'] and report['outcome'] == 'VERIFIED'
                and execution == row['steps'][index + 2]['execution'], 'fresh source/type/axiom transport differs')
        timings[tag] = time.monotonic() - started
    require(time.monotonic() - phase_start < 780, 'unchanged protected whole-operation deadline spent')
    return {'all_original_pins': 3, 'fresh_protected_native_orders': 6,
        'fresh_original_and_physical_validation_seconds': timings,
        'canonical_registration_required': True, 'proof_authority': False, 'completion_authority': False}
