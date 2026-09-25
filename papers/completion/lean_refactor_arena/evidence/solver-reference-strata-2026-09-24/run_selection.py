"""Reproduce this fixed public Strata experiment, not a general experiment service.

Requires the existing prepared, capped volume. No downloads, builds, model calls
or promotion. The child imports only the captured JevOps source. The source copy
and kernel-held preparation lock are not an OS sandbox or proof attestation.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--preparation-root', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('explicit --execute required: at most 30 native checks')
    repo, root = args.repo.resolve(strict=True), args.preparation_root.resolve(strict=True)
    prepare = load(repo / 'jevops/arena_prepare.py', 'prepare')
    snapshot = load(repo / 'jevops/arena_snapshot.py', 'snapshot')
    archive = repo / 'papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24'
    with prepare.exclusive(root / 'single-build.lock'):
        config = json.loads((root / 'preparation.json').read_text())
        work = prepare.validate_volume(config)
        def free():
            st = os.statvfs(work)
            return st.f_bavail * st.f_frsize
        before = free()
        if before < 200_000_000:
            raise RuntimeError('less than 200 MB free; no trial launched')
        run = Path(tempfile.mkdtemp(prefix='solver-reference-strata-', dir=work / 'tmp'))
        created = snapshot.create_snapshot(repo, run / 'source',
            ['jevops', 'tests', 'papers/completion/lean_refactor_arena',
             'pyproject.toml', 'pytest.ini', 'conftest.py', 'ARENA_SOLVER_SPECIALIZATION.md'],
            {'inputs/projects.json': work / 'projects-prepared-20.json',
             'inputs/candidate.json': archive / 'candidate.json',
             'inputs/incumbent.json': archive.parent / 'solver-nomination-strata-2026-09-24/incumbent.json'})
        bound = snapshot.verify_snapshot(run / 'source', created['manifest_sha256'])
        if free() < 100_000_000:
            raise RuntimeError('less than 100 MB free after capture; no trial launched')
        argv = ['--run', '--problem', 'CallElimCorrect.extractedOldExprInVars',
            '--projects', 'inputs/projects.json', '--elan-home', str(work / 'elan'),
            '--candidate', 'inputs/candidate.json', '--incumbent', 'inputs/incumbent.json',
            '--proposal-cap', '0', '--selection-objective', 'aggregate-local-v1',
            '--heartbeat-noise-floor-raw', '100', '--repetitions', '2',
            '--confirmation-repetitions', '3', '--seed', '17', '--max-calls', '30',
            '--timeout', '90', '--progress', '--output-dir', str(run / 'selection')]
        command = [sys.executable, '-I', '-B', '-c',
            'import sys; sys.path.insert(0, sys.argv.pop(1)); '
            'from jevops.arena_pareto import main; raise SystemExit(main())',
            str(run / 'source'), *argv]
        binding = dict(schema='jevops-fixed-strata-selection-launch/v1', argv=argv,
            run_root=str(run), created=created, before=bound, free_bytes_before=before,
            max_bytes=config['max_bytes'], native_check_ceiling=30,
            preparation_lock=str(root / 'single-build.lock'), os_sandbox=False,
            downloads=0, builds=0, live_model_calls=0, promoted=False, official_score=None)
        def emit(name, data):
            with (run / name).open('x') as stream:
                json.dump(data, stream, indent=2, allow_nan=False)
                stream.write('\n')
        emit('launch.json', binding)
        print(json.dumps({'status':'LAUNCHING', 'run_root':str(run), 'snapshot':created}), flush=True)
        # Credentials are not forwarded. No optional router/hook is activated.
        env = {key:os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL') if key in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1', JEVOPS_REGISTER_LRA_HOOKS='0',
                   JEVOPS_USE_EXTERNAL_DEPS='0', JEVOPS_USE_EXTERNAL_ROUTER='0',
                   TMPDIR=str(work / 'tmp'))
        started = time.monotonic()
        result = subprocess.run(command, cwd=run / 'source', env=env, check=False)
        after = snapshot.verify_snapshot(run / 'source', created['manifest_sha256'])
        prepare.validate_volume(config)
        emit('source-binding.json', dict(binding, after=after, returncode=result.returncode,
            wall_seconds=time.monotonic()-started, free_bytes_after=free()))
        print(json.dumps({'status':'FINISHED', 'returncode':result.returncode, 'run_root':str(run),
                          'snapshot_status':after['status']}), flush=True)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
