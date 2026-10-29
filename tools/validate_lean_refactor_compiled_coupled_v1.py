from pathlib import Path
import importlib.util
_spec = importlib.util.spec_from_file_location('_canonical_compiled_registry',
    Path(__file__).with_name('lean_refactor_compiled_registry_v1.py'))
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)
import lean_refactor_execution_v2 as c
ROOT = c.ROOT
"""Independent original-source, physical-context and complete native acceptance."""
import json
import time


def complete(data):
    s = registry.peer('lean_refactor_compiled_coupled_v1.py')
    s.c.require(data['schema'] == 'jevops.lean-refactor.canonical-physical-complete-coupled.v1'
        and data['limits'] == s.LIMITS and 0 < data['wall_seconds'] <= 780
        and set(data['pins']) == set(s.PINS), 'complete unchanged pin/time population required')
    s.c.require(data['native_processes'] == sum(row['native_processes'] for row in data['pins'].values()) <= 21
        and data['build_processes'] == sum(row['build_processes'] for row in data['pins'].values()) == 6,
        'complete shared native/build denominator differs')
    s.c.require(all(data[key] is False for key in ('proof_authority', 'completion_authority',
        'scientific_acceptance_authority', 'registered', 'activated', 'promoted',
        'whole_campaign_complete', 'whole_target_all_pins_accepted')) and data['model_calls'] == 0,
        'private phase has no canonical proof or activation authority')
    if data['status'] == 'QUALIFIED_ALL_PINS':
        s.c.require(data['native_processes'] + 3 == 24 and all(row['status'] == 'SCREENED_PIN'
            for row in data['pins'].values()), 'all pins need original/matched controls and both confirmations')
    else:
        s.c.require(data['status'] == 'NO_ALL_PIN_WINNER'
            and all(row['status'] in ('SCREENED_PIN', 'NO_ALL_PIN_WINNER') for row in data['pins'].values())
            and any(row['status'] == 'NO_ALL_PIN_WINNER' for row in data['pins'].values()),
            'software failure or missing pin is not a semantic negative')


def binding(row, frozen):
    s = registry.peer('lean_refactor_compiled_coupled_v1.py')
    s.c.require(row['source_sha256'] == frozen['source_sha256']
        and row['scientific_sources'] == frozen['scientific_sources']
        and row['frozen_sha256'] == s.arena.content_hash(frozen), 'strict active scientific sources differ')


def validate(directory, data, frozen, snapshots, phase_start):
    s = registry.peer('lean_refactor_compiled_coupled_v1.py')
    c, base, p, v = s.c, s.base, s.p, s.v
    complete(data); binding(data, frozen)
    c.require(set(snapshots) == set(s.PINS) and s.compiled.DRIVER == s.legacy.ACTIVE_DRIVER,
              'all distinct currently owned physical contexts and active checker required')
    ids, roots = set(), set()
    timings = {}
    for tag in s.PINS:
        snap, row = snapshots[tag], data['pins'][tag]
        record, pin, current_binding, work = base.inputs(tag)
        binding(row, frozen)
        c.require(current_binding == snap['binding'] and record == snap['record'] and work == snap['work'],
                  'original exact source/pin/path binding changed')
        root, packet, members = snap['root'], snap['packet'], snap['members']
        c.require(str(root) not in roots and p.owned_root(root) == snap['identity'], 'fresh distinct owned snapshot required')
        roots.add(str(root))
        context, digest = v.explicit_context(root, packet, row['import_identity'], pin.to_dict())
        c.require(c.read(snap['directory'] / 'copy-packet.json', max_bytes=64*1024**2) == json.loads(p.canonical(packet))
            and c.read(snap['directory'] / 'snapshot-context.json', max_bytes=64*1024**2) == json.loads(p.canonical(context))
            and digest == row['physical_context_sha256'], 'explicit new physical context/packet differs')
        s.runtime.validate_search_paths(root, current_binding, row['physical_search_binding'])
        env = s.runtime.environment(root, packet, current_binding, snap['directory'])
        c.require(row['native_environment'] == env and all(step['environment'] == env
            for step in row['steps'] if step['kind'] == 'native_processes'), 'actual physical child environment differs')
        for step in row['steps']:
            payload = c.read(snap['directory'] / step['archive'] / 'input.json')
            if payload:
                c.require(payload['request_id'] not in ids, 'native request reused across pins')
                ids.add(payload['request_id'])
        # Fresh originals and snapshots are both reread by the independent
        # implementation, after the complete all-pin native population.
        started = time.monotonic()
        mark = members.mark()
        originals = v.scan(root, packet, members, original=True)
        primary = members.primary_between(mark)
        physical = v.scan(root, packet, members, original=False)
        c.require(originals == physical, 'fresh final original/snapshot bytes differ')
        ready, roots0, plan = snap['ready'], snap['roots'], snap['plan']
        c.require(ready.sha(ready.canonical({str(path): originals[str(path)] for path in primary})) == row['import_identity']
            and not ready.checked_artifacts(plan, roots0, current_binding.lean, work, identity=row['import_identity'])
            and base.protected.import_custody(record, current_binding, work, row['import_identity']) == row['import_custody'],
            'independent current exact identity/serialized-import custody differs')
        c.require(base.capture_input(tag, record, pin, current_binding, row['import_identity'], frozen['drafts']) == row['parser_capture'],
                  'independently validated native parsed/dependency capture differs')
        c.require(c.canonical(c.read(snap['directory'] / 'observation.json')) == c.canonical(row), 'durable complete pin archive differs')
        base.protected.validate_archive(snap['directory'], row, frozen, record, pin, current_binding)
        timings[tag] = time.monotonic() - started
    c.require(time.monotonic() - phase_start < 780, 'unchanged complete phase deadline spent')
    return {'all_original_pins': 3, 'native_samples': data['native_processes'],
        'fresh_final_original_and_physical_checks_seconds': timings,
        'canonical_registration_required': True, 'fresh_protected_replay_required': True,
        'proof_authority': False, 'completion_authority': False}
