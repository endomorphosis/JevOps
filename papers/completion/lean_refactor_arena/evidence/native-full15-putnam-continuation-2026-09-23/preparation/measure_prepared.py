"""Measure newly built pins with the unchanged frozen native runtime.

Full 36-row matrix per invocation; old environments are intentionally omitted.
No search, candidate selection, model calls, training, or receipt reuse.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/barberb/.local/state/jevops-arena-provision-Nr5jXM')
WORK = ROOT / 'work'
HERE = Path(__file__).resolve().parent
RUNTIME = WORK / 'full15-benchmark-20260923-IrlqY5/runtime'
sys.path.insert(0, str(RUNTIME))
from jevops.arena_prepare import exclusive, validate_volume
from jevops.arena_snapshot import verify_snapshot


def emit(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')


def main():
    parser = __import__('argparse').ArgumentParser()
    parser.add_argument('--only', action='append', default=[])
    parser.add_argument('--build-report', action='append', default=[],
                        help='NAME=preparation report for an explicit successful resume/new build')
    args = parser.parse_args()
    result = json.loads((HERE / 'preparation-results.json').read_text())
    jobs = result['plan']['jobs']
    finished = {row['name'] for row in result['runs'] if row.get('report', {}).get('exit_code') == 0}
    originals = json.loads((RUNTIME / 'inputs/projects.json').read_text())
    cslib = next(p for p in originals if p['repository'] == 'https://github.com/leanprover/cslib'
                 and p['lean_tag'] == 'v4.30.0')
    jobs = [{'name': 'cslib-v4.30.0', 'binding': {**cslib,
        'root': str(WORK / 'projects/cslib-v4.30.0')}}, *jobs]
    cslib_build = json.loads((WORK / 'logs/1790150126535508494.json').read_text())
    assert cslib_build['exit_code'] == 0
    finished.add('cslib-v4.30.0')
    extra_reports = []
    for spec in args.build_report:
        name, path = spec.split('=', 1)
        path = Path(path).resolve(strict=True)
        assert name in {j['name'] for j in jobs}
        assert path.parent == (WORK / 'logs').resolve()
        data = json.loads(path.read_text())
        assert data['schema'] == 'jevops-arena-preparation/v1'
        assert data['exit_code'] == 0 and data['timed_out'] is False
        finished.add(name)
        extra_reports.append({'name': name, 'path': str(path),
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if args.only:
        assert set(args.only) <= finished
        finished &= set(args.only)
    records = [json.loads(line) for line in (RUNTIME / 'inputs/corpus.jsonl').read_text().splitlines()]
    selected = [job for job in jobs if job['name'] in finished]
    plan = {'schema': 'jevops-arena-native-continuation-plan/v1', 'jobs': selected,
        'previous_baseline': str(RUNTIME.parent / 'baseline.json'),
        'snapshot_manifest_sha256': '0dc965d987860cfbae9ff470d52f068fb8ac1f081056f5c89d038d91f23203fc',
        'corpus_sha256': hashlib.sha256((RUNTIME / 'inputs/corpus.jsonl').read_bytes()).hexdigest(),
        'lean_timeout_seconds': 900, 'per_environment_wall_timeout_seconds': 5400,
        'maximum_new_native_processes': sum(1 for r in records for v in r['version_info'] for tag, commit in v.items()
            if any((r['url'], tag, commit) == (j['binding']['repository'], j['binding']['lean_tag'], j['binding']['git_commit']) for j in selected)),
        'live_model_calls': 0, 'training_enabled': False, 'isolation': 'trusted-local',
        'additional_build_reports': extra_reports}
    output = HERE / ('measurements-' + '-'.join(args.only) if args.only else 'measurements')
    output.mkdir()
    emit(output / 'plan.json', plan)
    config = json.loads((ROOT / 'preparation.json').read_text())
    # Serialize fingerprint inventories as well as proof executions with builds.
    with exclusive(ROOT / 'single-build.lock'):
        validate_volume(config)
        check = verify_snapshot(RUNTIME, plan['snapshot_manifest_sha256'])
        emit(output / 'snapshot-before.json', check)
        assert check['status'] == 'UNCHANGED'
        outcomes = []
        for job in selected:
            manifest = output / (job['name'] + '-projects.json')
            emit(manifest, [job['binding']])
            calls = sum(1 for r in records for v in r['version_info'] for tag, commit in v.items()
                if (r['url'], tag, commit) == (job['binding']['repository'], job['binding']['lean_tag'], job['binding']['git_commit']))
            destination = output / (job['name'] + '-baseline.json')
            command = [sys.executable, '-I', '-B', '-c',
                'import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("jevops.arena_lean",run_name="__main__")',
                str(RUNTIME), '--baseline', '--corpus', str(RUNTIME / 'inputs/corpus.jsonl'),
                '--projects', str(manifest), '--elan-home', str(WORK / 'elan'),
                '--max-processes', str(calls), '--timeout', '900', '--isolation', 'trusted-local',
                '--output', str(destination)]
            print('MEASURE', job['name'], 'maximum native calls', calls, flush=True)
            with (output / (job['name'] + '.log')).open('x') as stream:
                process = subprocess.run(command, env={**os.environ, 'TMPDIR': str(WORK / 'tmp')},
                    stdout=stream, stderr=subprocess.STDOUT, timeout=5400)
            if process.returncode != 0:
                raise RuntimeError(f"native CLI failed for {job['name']}; inspect its log")
            report = json.loads(destination.read_text())
            counts = dict(Counter(row['status'] for row in report['rows']))
            outcomes.append({'name': job['name'], 'statuses': counts, 'processes': report['processes'],
                             'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
            print('MEASURED', job['name'], counts, flush=True)
        check = verify_snapshot(RUNTIME, plan['snapshot_manifest_sha256'])
        emit(output / 'snapshot-after.json', check)
        assert check['status'] == 'UNCHANGED'
        emit(output / 'outcomes.json', outcomes)


if __name__ == '__main__':
    main()
