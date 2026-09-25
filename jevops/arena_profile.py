"""Frozen single-pin diagnostic pilot, reusing ArenaLocalRuntime and its guard.

Plan-only by default. Four uninstrumented whole-proof controls are separate
from six instrumented profiles. No candidate search, selection or promotion.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

from .arena import Outcome, VerificationRequest, content_hash, intake_error, source_hash
from .arena_leaf_pilot import ROOT, save
from .arena_lean import CORPUS, NativeLeanVerifier, project_binding
from .arena_local import ArenaLocalRuntime, _identity, PROFILE_METHOD
from .arena_prepare import exclusive, validate_volume
from .arena_snapshot import verify_snapshot
from .arena_trial import Candidate, ORDERS, _pins
from .premise_search import bounded_int
from .seals import Fingerprinter


def make_plan(record, incumbent, *, threshold_raw=100):
    bounded_int(threshold_raw, 0, 1_000_000)
    if type(incumbent) is not Candidate or intake_error(incumbent.source, record['statement']):
        raise ValueError('typed incumbent with fixed statement required')
    if intake_error(record['src'], record['statement']) or len(_pins(record)) != 1:
        raise ValueError('this bounded profiling pilot requires exactly one declared pin')
    schedule = [dict(kind='control', order=order, repetition=repeat)
                for repeat in range(2) for order in ORDERS]
    schedule += [dict(kind='profile', arm=arm, repetition=repeat)
                 for repeat in range(3) for arm in (('original', 'incumbent') if repeat % 2 == 0
                                                   else ('incumbent', 'original'))]
    plan = dict(schema='jevops-arena-profile-pilot/v1', record=dict(record), incumbent=asdict(incumbent),
        schedule=schedule, native_process_ceiling=10, threshold_raw=threshold_raw, node_budget=20000,
        event_budget=256, measurement=PROFILE_METHOD, retries=0,
        implementation=content_hash(dict(local=_identity(), pilot=source_hash(Path(__file__).read_text()))),
        score_eligible=False, promoted=False, official_score=None)
    return {**plan, 'plan_sha256': content_hash(plan)}


def run(plan, *, binding, directory, max_processes, check_resources):
    if make_plan(plan['record'], Candidate(**plan['incumbent']), threshold_raw=plan['threshold_raw']) != plan:
        raise ValueError('stale or mutated profiling plan')
    if type(max_processes) is not int or max_processes != plan['native_process_ceiling']:
        raise ValueError('exact full process reservation required')
    if binding.pin != _pins(plan['record'])[0]:
        raise ValueError('foreign prepared pin')
    plan = json.loads(json.dumps(plan))
    check_resources()
    directory.mkdir()
    save(directory/'plan.json', plan)
    start = time.monotonic()
    reader = Fingerprinter()
    guards = {order: NativeLeanVerifier({binding.pin: binding}, max_processes=2, timeout=90,
              branch_order=order, fingerprinter=reader) for order in ORDERS}
    local_guard = NativeLeanVerifier({binding.pin: binding}, max_processes=0, timeout=90, fingerprinter=reader)
    runtime = ArenaLocalRuntime(local_guard, plan['record'], max_processes=6,
                               node_budget=plan['node_budget'], event_budget=plan['event_budget'])
    controls, profiles, failure = [], [], ''
    for index, step in enumerate(plan['schedule']):
        check_resources()
        if step['kind'] == 'control':
            guard = guards[step['order']]
            receipt = guard(VerificationRequest(guard.context(plan['record']),
                              plan['incumbent']['source'], binding.pin))
            sample = {**step, 'receipt': asdict(receipt)}
            controls.append(sample)
            report = json.loads(receipt.observations_json).get('report', {})
            accepted = receipt.outcome == Outcome.VERIFIED and receipt.type_preserved and not (
                set(report.get('axioms', ())) - set(report.get('reference_axioms', ())))
            status = receipt.outcome.value
        else:
            source = plan['record']['src'] if step['arm'] == 'original' else plan['incumbent']['source']
            result = runtime.profile(binding.pin, source=source, threshold_raw=plan['threshold_raw'])
            sample = {**step, 'result': result}
            profiles.append(sample)
            accepted, status = result['ok'], result['status']
        save(directory/f'sample-{index:02d}.json', sample)
        print(f"[{index+1}/10] {step['kind']} {step.get('arm', step.get('order'))} "
              f"repeat={step['repetition']} {status}", flush=True)
        if not accepted:
            failure = 'non-success sample; stopped without retry'
            break
    check_resources()
    if make_plan(plan['record'], Candidate(**plan['incumbent']), threshold_raw=plan['threshold_raw']) != plan:
        failure = 'profiling implementation changed during run'
    report = dict(schema='jevops-arena-profile-report/v1', plan=plan,
        status='INCOMPLETE' if failure else 'PROFILED', reason=failure, controls=controls, profiles=profiles,
        native_processes=sum(g.processes for g in guards.values())+runtime.attempts,
        processes_reserved=10, instrumented_processes=runtime.attempts,
        wall_seconds=time.monotonic()-start, model_calls=0, promoted=False, official_score=None,
        score_eligible=False, candidate_search=False, proof_receipt_cache_enabled=False)
    save(directory/'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--problem', required=True)
    parser.add_argument('--incumbent', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-processes', type=int, default=0)
    parser.add_argument('--threshold-raw', type=int, default=100,
                        help='explicit frozen profiling threshold; no adaptive changes within a run')
    parser.add_argument('--snapshot-manifest-sha256')
    parser.add_argument('--preparation-root', type=Path)
    parser.add_argument('--projects', type=Path)
    parser.add_argument('--elan-home', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    records = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    matches = [r for r in records if r['name'] == args.problem]
    if len(matches) != 1 or args.incumbent.stat().st_size > 1_048_576:
        parser.error('one corpus record and bounded incumbent required')
    draft = json.loads(args.incumbent.read_text())
    if set(draft) != {'name', 'label', 'source', 'provenance'} or draft['name'] != args.problem:
        parser.error('matching four-field source draft required')
    record = matches[0]
    plan = make_plan(record, Candidate(draft['label'], draft['source'], draft['provenance']),
                     threshold_raw=args.threshold_raw)
    if not args.execute:
        print(json.dumps(dict(status='PLANNED', native_process_ceiling=10,
                              plan_sha256=plan['plan_sha256'], candidate_search=False, score_eligible=False)))
        return 0
    if not all((args.snapshot_manifest_sha256, args.preparation_root, args.projects, args.elan_home, args.output)):
        parser.error('execution requires a frozen snapshot, prepared projects and new output')
    if args.max_processes != 10:
        parser.error('reserve exactly ten processes before work')
    config = json.loads((args.preparation_root/'preparation.json').read_text())
    with exclusive(args.preparation_root/'single-build.lock'):
        mount = validate_volume(config)
        if args.output.exists() or not args.output.resolve().is_relative_to(mount):
            raise ValueError('new output inside capped volume required')
        if not Path(os.environ.get('TMPDIR', '/tmp')).resolve().is_relative_to(mount):
            raise ValueError('temporary storage must stay inside capped volume')
        if any(not p.resolve().is_relative_to(ROOT/'inputs') for p in (args.incumbent, args.projects)):
            raise ValueError('inputs must belong to snapshot')
        before = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
        if any(getattr(m, '__file__', None) and not Path(m.__file__).resolve().is_relative_to(ROOT)
               for n, m in sys.modules.items() if n == 'jevops' or n.startswith('jevops.')):
            raise ValueError('JevOps import escaped snapshot')
        pin = _pins(record)[0]
        projects = json.loads(args.projects.read_text())
        found = [p for p in projects if (p['repository'], p['lean_tag'], p['git_commit']) ==
                 (record['url'], pin.lean_tag, pin.git_commit)]
        if len(found) != 1:
            raise ValueError('one matching prepared project required')
        binding = project_binding(record, pin, found[0], args.elan_home)
        def resources():
            validate_volume(config)
            s = os.statvfs(mount)
            if s.f_bavail*s.f_frsize < 100_000_000:
                raise ValueError('storage reserve reached; retain all caches')
        report = run(plan, binding=binding, directory=args.output,
                     max_processes=args.max_processes, check_resources=resources)
        save(args.output/'source-binding.json', dict(before=before,
            after=verify_snapshot(ROOT, args.snapshot_manifest_sha256), max_bytes=config['max_bytes']))
    print(json.dumps({k: report[k] for k in ('status', 'native_processes', 'official_score')}))
    return 2 if report['status'] == 'INCOMPLETE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
