"""Freeze and optionally start a bounded user-service improvement run.

Never builds dependencies, removes caches, or edits an existing run. All new
artifacts live inside the already-provisioned capped preparation volume.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .arena_prepare import validate_volume, stage_imports
from .arena_snapshot import create_snapshot, verify_snapshot
from .improvement_service import Config, MAX_REPORT, Store, read_json
from .arena import content_hash


def validate_resume(previous, current, extension=0):
    if type(extension) is not int or not 0 <= extension <= 32:
        raise ValueError('explicit router extension must be 0..32 calls')
    changed = {k for k in asdict(current) if asdict(current)[k] != asdict(previous)[k]}
    if changed - {'runtime', 'snapshot_sha256', 'state', 'router_budget'}:
        raise ValueError('resume must preserve routing, native budget, partitions and execution policy')
    if current.router_budget != previous.router_budget + extension:
        raise ValueError('router budget change requires an exact explicit extension')


def stage_runtime(volume_config, run, snapshot):
    """UID-65534 cannot read owner-only FUSE, even through read-only binds.

    Reuse the preparation runner's charged, read-only staging mechanism within
    its EXISTING external allowance. Do not remount FUSE or relax worker UID.
    """
    stage = stage_imports(volume_config, (run/'runtime',), name=run.name+'-runtime',
                          max_bytes=32_000_000, timeout=120)
    runtime = Path(stage['search_paths'][0])
    verify_snapshot(runtime, snapshot['manifest_sha256'])
    return runtime, stage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--volume-config', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--projects', type=Path, action='append', required=True)
    parser.add_argument('--seed-report', type=Path, action='append', default=[])
    parser.add_argument('--development', action='append', required=True)
    parser.add_argument('--elan-home', required=True)
    parser.add_argument('--docker-socket', default='/run/user/1000/docker.sock')
    parser.add_argument('--docker-image', required=True)
    parser.add_argument('--provider', default='codex_cli')
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--router-budget', type=int, default=8)
    parser.add_argument('--native-budget', type=int, default=200)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--resume-config', type=Path,
        help='explicit stopped-run upgrade; retain ledger, checkpoints, and all spent budgets')
    parser.add_argument('--extend-router-budget', type=int, default=0,
        help='explicit additional calls on resume (0..32); spent counters never reset')
    args = parser.parse_args(argv)
    if args.extend_router_budget and not args.resume_config:
        parser.error('budget extension requires a stopped run to resume')
    previous = Config.load(args.resume_config) if args.resume_config else None
    volume_config = read_json(args.volume_config)
    volume = validate_volume(volume_config)
    stat = os.statvfs(volume)
    if stat.f_bavail * stat.f_frsize < 512_000_000 + 8 * MAX_REPORT:
        parser.error('storage guard: retain all caches; do not create another run')
    records = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
    names = {r['name'] for r in records}
    if not set(args.development) < names or len(args.development) != len(set(args.development)):
        parser.error('unique development names and a nonempty excluded holdout partition required')
    projects = {}
    for path in args.projects:
        for project in read_json(path):
            projects[project['repository'], project['lean_tag'], project['git_commit']] = project
    run = Path(tempfile.mkdtemp(prefix='improvement-watch-', dir=volume))
    manifest = run/'projects.json'
    manifest.write_text(json.dumps(list(projects.values()), indent=2)+'\n')
    inputs = {'inputs/corpus.jsonl': args.corpus, 'inputs/projects.json': manifest}
    for report in args.seed_report:
        name = 'inputs/' + report.name
        if name in inputs:
            parser.error('duplicate seed filename')
        inputs[name] = report
    snapshot = create_snapshot(args.repo, run/'runtime', ['jevops'], inputs)
    runtime, runtime_stage = stage_runtime(volume_config, run, snapshot)
    config = Config(str(runtime), snapshot['manifest_sha256'], str(run/'state'),
        str(args.volume_config.resolve()), tuple(args.development), tuple(sorted(names-set(args.development))),
        args.elan_home, args.docker_socket, args.docker_image,
        provider=args.provider, model=args.model, interval_seconds=args.interval,
        router_budget=(previous.router_budget + args.extend_router_budget if previous else args.router_budget),
        native_budget=args.native_budget,
        seed_reports=tuple(p.name for p in args.seed_report))
    if previous:
        try:
            validate_resume(previous, config, args.extend_router_budget)
        except ValueError as exc:
            parser.error(str(exc))
    config_path = run/'config.json'
    config_path.write_text(json.dumps(asdict(config), indent=2)+'\n')
    config_path.chmod(0o444)
    if args.resume_config:
        old_corpus = Path(previous.runtime)/'inputs/corpus.jsonl'
        if old_corpus.read_bytes() != args.corpus.read_bytes():
            parser.error('resume cannot change the frozen corpus')
        old = Store(Path(previous.state), content_hash(asdict(previous)))
        try:
            with old.leader():
                destination = run/'state'
                destination.mkdir()
                import sqlite3
                copied = sqlite3.connect(destination/'watch.sqlite3')
                try:
                    old.db.backup(copied)
                    with copied:
                        copied.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                            ('config_identity', json.dumps(content_hash(asdict(config)))))
                        copied.execute('INSERT INTO events(kind,payload) VALUES (?,?)',
                            ('runtime_upgrade', json.dumps({'previous_config': str(args.resume_config),
                                'previous_snapshot': previous.snapshot_sha256, 'snapshot': config.snapshot_sha256,
                                'spent_counters_preserved': True, 'native_budget_preserved': True,
                                'router_budget_extension': args.extend_router_budget,
                                'previous_router_budget': previous.router_budget,
                                'router_budget': config.router_budget, 'old_files_retained': True})))
                finally:
                    copied.close()
        finally:
            old.db.close()
    unit = 'jevops-' + run.name.replace('_', '-')
    command = [sys.executable, '-I', '-B', '-c',
        'import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("jevops.improvement_service",run_name="__main__")',
        str(runtime), '--config', str(config_path), '--serve']
    launch = ['systemd-run', '--user', '--unit='+unit,
        '--property=Restart=no', '--property=TimeoutStopSec=45', '--property=KillMode=control-group',
        '--property=MemoryMax=4G', '--property=TasksMax=256', '--property=CPUQuota=200%',
        '--property=WorkingDirectory='+str(runtime),
        '--setenv=TMPDIR='+str(volume/'tmp'), '--setenv=PYTHONDONTWRITEBYTECODE=1',
        '--setenv=JEVOPS_USE_EXTERNAL_ROUTER=0', '--setenv=JEVOPS_USE_EXTERNAL_DEPS=0',
        '--setenv=PATH='+os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), *command]
    metadata = {'schema': 'jevops-improvement-launch/v1', 'unit': unit+'.service',
        'config': str(config_path), 'run': str(run), 'command': command,
        'started': False, 'cache_policy': 'retain_all', 'snapshot': snapshot, 'runtime_stage': runtime_stage}
    if args.start:
        subprocess.run(launch, check=True)
        metadata['started'] = True
    (run/'launch.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps({k: metadata[k] for k in ('unit', 'config', 'run', 'started', 'cache_policy')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
