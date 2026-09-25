"""Bounded operational batch; all build writes stay in the existing capped volume."""
import hashlib
import json
from pathlib import Path
import sys
import time

RUNTIME = Path('/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/full15-benchmark-20260923-IrlqY5/runtime')
sys.path.insert(0, str(RUNTIME))
from jevops.arena_prepare import run, validate_volume

ROOT = Path('/home/barberb/.local/state/jevops-arena-provision-Nr5jXM')
WORK = ROOT / 'work'
HERE = Path(__file__).resolve().parent
STATE = Path('/home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake')
config = json.loads((ROOT / 'preparation.json').read_text())
records = [json.loads(line) for line in (RUNTIME / 'inputs/corpus.jsonl').read_text().splitlines()]
projects = json.loads((RUNTIME / 'inputs/projects.json').read_text())
jobs = []
for tag in ('v4.30.0', 'v4.29.0', 'v4.28.0', 'v4.25.0', 'v4.26.0', 'v4.27.0'):
    putnam = tag in ('v4.25.0', 'v4.26.0', 'v4.27.0')
    repository = '' if putnam else 'https://github.com/Verified-zkEVM/ArkLib'
    binding = next(p for p in projects if p['repository'] == repository and p['lean_tag'] == tag)
    name = ('putnam-' if putnam else 'arklib-') + tag
    destination = WORK / 'projects' / name
    targets = sorted({r['file_path'].removesuffix('.lean').replace('/', '.') for r in records
        if r['url'] == repository and any(v.get(tag) == binding['git_commit'] for v in r['version_info'])})
    command = ['/usr/bin/env', 'PATH=' + str(WORK / 'elan/toolchains' / ('leanprover--lean4---' + tag) / 'bin') + ':/usr/bin:/bin',
        '/usr/bin/python3', '-B', str(HERE / 'prepare_exact.py'), '--destination', str(destination),
        '--tag', tag, '--commit', binding['git_commit']]
    if putnam:
        command += ['--putnam']
    else:
        command += ['--repository', repository, '--source', binding['root']]
        for target in targets:
            command += ['--target', target]
    for cache in (WORK / 'projects/cslib-v4.30.0', STATE / 'clones/github.com/Verified-zkEVM/ArkLib'):
        command += ['--cache', str(cache)]
    jobs.append({'name': name, 'binding': {**binding, 'root': str(destination)}, 'command': command,
                 'minimum_free_bytes': 12000000000 if putnam else 3000000000})
plan = {'schema': 'jevops-arena-missing-preparation-plan/v1', 'jobs': jobs, 'allowance_bytes': 50000000000,
    'concurrency': 1, 'stage_timeout_seconds': 1800, 'batch_timeout_seconds': 7200,
    'minimum_free_bytes_before_stage': 3000000000, 'native_calls': 0, 'model_calls': 0,
    'payload_sha256': hashlib.sha256((HERE / 'prepare_exact.py').read_bytes()).hexdigest()}
with (HERE / 'preparation-plan.json').open('x') as stream:
    json.dump(plan, stream, indent=2)
deadline = time.monotonic() + plan['batch_timeout_seconds']
reports = []
for job in jobs:
    mount = validate_volume(config)
    import os
    stat = os.statvfs(mount)
    free = stat.f_bavail * stat.f_frsize
    remaining = int(deadline - time.monotonic())
    if free < job['minimum_free_bytes'] or remaining < 60:
        reports.append({'name': job['name'], 'status': 'NOT_STARTED_RESOURCE_LIMIT', 'free_bytes': free})
        break
    print('START', job['name'], 'free_bytes', free, flush=True)
    report = run(config, job['command'], readonly=(Path('/home/barberb/.elan/toolchains'), STATE / 'clones/github.com/Verified-zkEVM/ArkLib'),
                 network=True, timeout=min(remaining, plan['stage_timeout_seconds']))
    reports.append({'name': job['name'], 'report': report})
    print('END', job['name'], 'exit', report['exit_code'], flush=True)
    # Do not launch further builds after a partial failure or timeout.
    if report['exit_code'] != 0:
        break
with (HERE / 'preparation-results.json').open('x') as stream:
    json.dump({'plan': plan, 'runs': reports, 'proofs_verified': 0}, stream, indent=2)
