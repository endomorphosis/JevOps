"""Restore the exact ProofWidgets release tag; resume without changing pins."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
project = WORK / 'projects/putnam-v4.25.0'

if '--inside' in sys.argv:
    def output(*args, cwd=project):
        return subprocess.check_output(args, cwd=cwd, text=True).strip()
    def run(*args, cwd=project):
        subprocess.run(args, cwd=cwd, check=True)
    manifest_before = (project / 'lake-manifest.json').read_bytes()
    manifest = json.loads(manifest_before)
    entry = next(p for p in manifest['packages'] if p['name'] == 'proofwidgets')
    package = project / '.lake/packages/proofwidgets'
    assert output('git', 'rev-parse', 'HEAD', cwd=package) == entry['rev']
    assert not output('git', 'status', '--porcelain', '--untracked-files=no', cwd=package)
    remote = output('git', 'ls-remote', '--tags', 'origin', cwd=package)
    matches = []
    for line in remote.splitlines():
        revision, ref = line.split()
        if revision == entry['rev']:
            matches.append(ref.removesuffix('^{}'))
    assert matches, 'no upstream release tag for exact locked revision'
    for ref in sorted(set(matches)):
        assert ref.startswith('refs/tags/') and ':' not in ref
        run('git', 'fetch', '--depth=1', 'origin', ref + ':' + ref, cwd=package)
        assert output('git', 'rev-parse', ref + '^{}', cwd=package) == entry['rev']
    run('lake', '--no-cache', 'exe', 'cache', 'get', 'Mathlib', 'Aesop')
    assert (project / 'lake-manifest.json').read_bytes() == manifest_before
    assert output('git', 'rev-parse', 'HEAD', cwd=package) == entry['rev']
    assert not output('git', 'status', '--porcelain', '--untracked-files=no', cwd=package)
    print('PREPARATION_COMPLETED_NOT_PROOF', flush=True)
else:
    sys.path.insert(0, str(WORK / 'full15-benchmark-20260923-IrlqY5/runtime'))
    from jevops.arena_prepare import run
    config = json.loads((WORK.parent / 'preparation.json').read_text())
    command = ['/usr/bin/env', 'PATH=' + str(WORK / 'elan/toolchains/leanprover--lean4---v4.25.0/bin') + ':/usr/bin:/bin',
               '/usr/bin/python3', '-B', str(Path(__file__).resolve()), '--inside']
    with (HERE / 'putnam25-resume-plan.json').open('x') as stream:
        json.dump({'command': command, 'timeout_seconds': 3600,
                   'payload_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'reason': 'Restore upstream release tags pointing to exact locked ProofWidgets revision.',
                   'proofs_verified': 0}, stream, indent=2)
    report = run(config, command, cwd=project, readonly=(Path('/home/barberb/.elan/toolchains'),),
                 network=True, timeout=3600)
    with (HERE / 'putnam25-resume-result.json').open('x') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))
    raise SystemExit(int(report['exit_code'] != 0))
