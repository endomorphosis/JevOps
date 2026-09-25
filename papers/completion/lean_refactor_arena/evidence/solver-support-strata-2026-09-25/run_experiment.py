"""Fixed public Strata support-minimization experiment; no promotion or models.

Uses the existing solver search and strict-dual selector. Read-only source copy
and flock protect against accidental interference, not hostile native code.
Requires the existing capped preparation volume; never downloads or builds.
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


RELATIVE = 'papers/completion/lean_refactor_arena/evidence/solver-support-strata-2026-09-25/run_experiment.py'


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def experiment(directory, work):
    """Called only in the captured source, under the parent's preparation lock."""
    from dataclasses import asdict
    from jevops.arena import VerificationRequest, content_hash, reference_tokens, source_hash
    from jevops.arena_lean import CORPUS, NativeLeanVerifier, project_binding
    from jevops.arena_local import ArenaLocalRuntime
    from jevops.arena_pareto import run_selection, selection_plan
    from jevops.arena_prepare import validate_volume
    from jevops.arena_solver import SolverLimits
    from jevops.arena_trial import Candidate, ORDERS, _pins
    from jevops.seals import Fingerprinter

    directory.mkdir()
    seed = json.loads(Path('inputs/seed.json').read_text())
    old = json.loads(Path('inputs/incumbent.json').read_text())
    record, = [json.loads(line) for line in CORPUS.read_text().splitlines()
               if json.loads(line)['name'] == seed['name']]
    if (set(seed) != {'name', 'label', 'source', 'provenance'} or set(old) != set(seed)
            or old['name'] != seed['name']):
        raise ValueError('matching four-field source drafts required')
    incumbent = Candidate('incumbent', old['source'], old['provenance'])
    pins = _pins(record)
    if len(pins) != 1 or pins[0].lean_tag != 'v4.26.0':
        raise ValueError('this fixed 48-check reservation requires the one declared Strata pin')
    projects = json.loads(Path('inputs/projects.json').read_text())
    limits = SolverLimits(max_calls=16, max_states=8, max_depth=3, max_sites=1, max_drafts=1)
    selection = dict(repetitions=2, confirmation_repetitions=3, seed=17,
                     selection_objective='strict-dual-v1', heartbeat_noise_floor_raw=100)
    plan = dict(schema='jevops-fixed-strata-support/v1', record=record,
        seed=seed, incumbent=old, limits=asdict(limits), mode='minimize-v1',
        draft_policy='shortest-v1', selection=selection, control_ceiling=2,
        discovery_ceiling=16, selection_ceiling=30, native_check_ceiling=48,
        nomination='one shortest checked draft; screen only if strictly shorter than incumbent',
        search='existing FIFO support deletions and first-site solver hints; no post-result expansion',
        incumbent_tokens=reference_tokens(incumbent.source, record['statement']),
        task_split='exposed-public-warmup-not-held-out', retries=0, resume=False,
        runner_sha256=source_hash(Path(__file__).read_text()),
        live_model_calls=0, downloads=0, builds=0, promoted=False, official_score=None)
    plan['plan_id'] = content_hash(plan)
    save(directory / 'protocol.json', plan)  # Before any native check.
    guards, started = [], time.monotonic()
    report = dict(plan_id=plan['plan_id'], status='INCOMPLETE', controls=[],
        reservations=dict(controls=2, discovery=16, selection_and_confirmation=30),
        recommended=None, promoted=False, official_score=None, measured_api_cost=None,
        live_model_calls=0, retries=0, proof_receipt_cache_enabled=False)

    def resources():
        config = json.loads((work.parent / 'preparation.json').read_text())
        if validate_volume(config) != work:
            raise ValueError('preparation volume changed')
        st = os.statvfs(work)
        if st.f_bavail * st.f_frsize < 100_000_000:
            raise RuntimeError('less than 100 MB free; stop without more checks')

    def guard_for(bindings, limit, reader, order='reference-first'):
        resources()
        guard = NativeLeanVerifier(bindings, max_processes=limit, timeout=90,
                                   fingerprinter=reader, branch_order=order)
        guards.append(guard)
        return guard

    def finish(status, reason):
        report.update(status=status, reason=reason, native_processes=sum(g.processes for g in guards),
                      wall_seconds=time.monotonic() - started)
        if report['native_processes'] > 48:
            raise RuntimeError('native reservation violated')
        save(directory / 'report.json', report)
        print(json.dumps(report), flush=True)
        return 1 if status == 'INCOMPLETE' else 0

    try:
        bindings = {}
        for pin in pins:
            project, = [p for p in projects if (p['repository'], p['lean_tag'], p['git_commit']) ==
                        (record['url'], pin.lean_tag, pin.git_commit)]
            bindings[pin] = project_binding(record, pin, project, work / 'elan')
        reader = Fingerprinter()
        control = guard_for(bindings, 2, reader)
        context = control.context(record)
        for label, source in [('original', record['src']), ('incumbent', incumbent.source)]:
            receipt = control(VerificationRequest(context, source, pins[0]))
            row = dict(label=label, source_sha256=source_hash(source), receipt=asdict(receipt))
            save(directory / (label + '-control.json'), row)
            report['controls'].append(dict(label=label, outcome=receipt.outcome.value))
            print(json.dumps(dict(phase='control', **report['controls'][-1])), flush=True)
            if receipt.outcome.value != 'VERIFIED':
                return finish('INCOMPLETE', 'original_or_incumbent_control_failed')
        guard = guard_for(bindings, 16, reader)
        discovery = ArenaLocalRuntime(guard, record).discover_solver(pins[0], source=seed['source'],
            mode=plan['mode'], limits=limits, draft_policy=plan['draft_policy'])
        save(directory / 'discovery.json', discovery)
        report['discovery'] = dict(status=discovery['status'], calls=guard.processes,
            tokens=[n['tokens'] for n in discovery['frontier']],
            raw_heartbeats=[n['raw_heartbeats'] for n in discovery['frontier']],
            truncated=discovery['truncated'], omitted=discovery['omitted'])
        print(json.dumps(dict(phase='discovery', **report['discovery'])), flush=True)
        if (not discovery['seed_checked'] or not discovery['context_applicable']
                or discovery['status'] not in ('COMPLETE', 'BUDGET_EXHAUSTED')
                or discovery['plan']['context_id'] != context.context_id):
            return finish('INCOMPLETE', 'discovery_or_context_failed')
        control.validate_request(VerificationRequest(context, incumbent.source, pins[0]))
        resources()
        nominees = [d for d in discovery['drafts']
                    if reference_tokens(d['source'], record['statement']) < plan['incumbent_tokens']]
        if not nominees:
            return finish('NO_CANDIDATE', 'bounded_search_found_no_checked_draft_shorter_than_185_token_incumbent')
        draft, = nominees
        save(directory / 'candidate.json', draft)
        candidates = [Candidate(draft['label'], draft['source'], draft['provenance'])]
        protocol = selection_plan(record, candidates, incumbent=incumbent, **selection)
        if protocol['required_request_budget'] != 30:
            raise ValueError('selection exceeds fixed reservation')
        save(directory / 'selection-plan.json', protocol)

        def factory(phase, limit):
            fresh = Fingerprinter()
            return {(p, order):guard_for({p:bindings[p]}, limit, fresh, order)
                    for p in pins for order in ORDERS}, {}

        selected = run_selection(record, candidates, factory, incumbent=incumbent,
            max_calls=30, progress=True, evidence_mode='local_lean', **selection)
        save(directory / 'selection.json', selected)
        report['recommended'] = selected['recommended']
        resources()
        return finish(selected['status'], selected['reason'])
    except Exception as exc:
        report['recommended'] = None
        return finish('INCOMPLETE', f'{type(exc).__name__}: {str(exc)[:500]}')


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
        parser.error('explicit --execute required: at most 48 native checks')
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
        run = Path(tempfile.mkdtemp(prefix='solver-support-strata-', dir=work / 'tmp'))
        created = snapshot.create_snapshot(repo, run / 'source',
            ['jevops', 'tests', 'papers/completion/lean_refactor_arena',
             'pyproject.toml', 'pytest.ini', 'conftest.py', 'ARENA_SOLVER_SPECIALIZATION.md'],
            {'inputs/projects.json': work / 'projects-prepared-20.json',
             'inputs/seed.json': archive / 'candidate.json', 'inputs/incumbent.json': archive / 'incumbent.json'})
        bound = snapshot.verify_snapshot(run / 'source', created['manifest_sha256'])
        if free() < 100_000_000:
            raise RuntimeError('less than 100 MB free after capture; no trial launched')
        command = [sys.executable, '-I', '-B', '-c',
            'import sys, runpy; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
            'm = runpy.run_path(str(Path(sys.argv[1]) / sys.argv[2])); '
            'raise SystemExit(m["experiment"](Path(sys.argv[3]), Path(sys.argv[4])))',
            str(run / 'source'), RELATIVE, str(run / 'experiment'), str(work)]
        binding = dict(schema='jevops-fixed-strata-support-launch/v1', command=command,
            run_root=str(run), created=created, before=bound, free_bytes_before=before,
            max_bytes=config['max_bytes'], native_check_ceiling=48,
            preparation_lock=str(root / 'single-build.lock'), os_sandbox=False,
            downloads=0, builds=0, live_model_calls=0, promoted=False, official_score=None)
        save(run / 'launch.json', binding)
        print(json.dumps(dict(status='LAUNCHING', run_root=str(run), snapshot=created)), flush=True)
        env = {key:os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL') if key in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1', JEVOPS_REGISTER_LRA_HOOKS='0',
                   JEVOPS_USE_EXTERNAL_DEPS='0', JEVOPS_USE_EXTERNAL_ROUTER='0', TMPDIR=str(work / 'tmp'))
        started = time.monotonic()
        result = subprocess.run(command, cwd=run / 'source', env=env, check=False)
        after = snapshot.verify_snapshot(run / 'source', created['manifest_sha256'])
        prepare.validate_volume(config)
        save(run / 'source-binding.json', dict(binding, after=after, returncode=result.returncode,
             wall_seconds=time.monotonic()-started, free_bytes_after=free()))
        print(json.dumps(dict(status='FINISHED', returncode=result.returncode,
                              run_root=str(run), snapshot_status=after['status'])), flush=True)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
