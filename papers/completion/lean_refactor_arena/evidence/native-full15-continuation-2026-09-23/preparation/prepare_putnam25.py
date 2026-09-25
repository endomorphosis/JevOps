"""Prioritize the three not-yet-measured Putnam problems, within the same cap."""
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent
RUNTIME = WORK / 'full15-benchmark-20260923-IrlqY5/runtime'
sys.path.insert(0, str(RUNTIME))
from jevops.arena_prepare import run, validate_volume

config = json.loads((ROOT / 'preparation.json').read_text())
validate_volume(config)
stat = os.statvfs(WORK)
free = stat.f_bavail * stat.f_frsize
job = next(j for j in json.loads((HERE / 'preparation-plan.json').read_text())['jobs']
           if j['name'] == 'putnam-v4.25.0')
assert not Path(job['binding']['root']).exists(), 'refusing to overwrite an environment'
assert free >= job['minimum_free_bytes'], 'insufficient storage preflight headroom'
plan = {'job': job, 'timeout_seconds': 3600, 'free_bytes_before': free,
    'minimum_free_bytes': job['minimum_free_bytes'], 'allowance_bytes': 50000000000,
    'payload_sha256': hashlib.sha256((HERE / 'prepare_exact.py').read_bytes()).hexdigest(),
    'reason': 'Prioritize all three previously unmeasured problems before more historical-version coverage.',
    'proofs_verified': 0}
with (HERE / 'putnam25-plan.json').open('x') as stream:
    json.dump(plan, stream, indent=2)
report = run(config, job['command'], readonly=(Path('/home/barberb/.elan/toolchains'),
    Path('/home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake/clones/github.com/Verified-zkEVM/ArkLib')),
    network=True, timeout=plan['timeout_seconds'])
with (HERE / 'putnam25-result.json').open('x') as stream:
    json.dump(report, stream, indent=2)
print(json.dumps(report, indent=2))
raise SystemExit(int(report['exit_code'] != 0))
