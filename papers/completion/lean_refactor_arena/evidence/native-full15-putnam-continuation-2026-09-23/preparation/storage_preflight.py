"""Report storage headroom for remaining preparations without deleting caches."""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
config = json.loads((WORK.parent / 'preparation.json').read_text())
stat = os.statvfs(WORK)
free = stat.f_bavail * stat.f_frsize
jobs = json.loads((HERE / 'preparation-plan.json').read_text())['jobs']
rows = []
for job in jobs:
    exists = Path(job['binding']['root']).exists()
    rows.append({'name': job['name'], 'root_exists': exists,
        'minimum_free_bytes': job['minimum_free_bytes'],
        'status': 'EXISTING_NOT_RECHECKED' if exists else
                  'PREFLIGHT_PASSES_NOT_PREPARED' if free >= job['minimum_free_bytes'] else
                  'INSUFFICIENT_PREFLIGHT_HEADROOM'})
report = {'schema': 'jevops-arena-storage-preflight/v1',
    'allowance_bytes': config['max_bytes'], 'available_bytes': free,
    'allocated_filesystem_bytes': (stat.f_blocks - stat.f_bfree) * stat.f_frsize,
    'remaining_jobs': rows, 'deleted_paths': [], 'proofs_verified': 0,
    'note': 'A passing preflight is not a build or proof result. Retaining all environments; no cache-rotation approval assumed.'}
with (HERE / 'storage-preflight.json').open('x') as stream:
    json.dump(report, stream, indent=2)
print(json.dumps(report, indent=2))
