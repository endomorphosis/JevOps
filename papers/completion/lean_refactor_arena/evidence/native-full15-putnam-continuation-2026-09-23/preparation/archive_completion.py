"""Generate and archive a cumulative benchmark report; never fabricates receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
PREVIOUS = WORK / 'full15-benchmark-20260923-IrlqY5'
RUNTIME = PREVIOUS / 'runtime'
sys.path.insert(0, str(RUNTIME))
from jevops.arena_snapshot import verify_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--measurement-dir', type=Path, action='append', required=True)
    parser.add_argument('--build-report', type=Path, action='append', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / 'inputs'
    inputs.mkdir()
    index = []
    def copy(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError(f'duplicate archive destination: {destination}')
        shutil.copyfile(source, destination)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest
        index.append({'source': str(source), 'archive': str(destination.relative_to(output)), 'sha256': digest})
        return destination
    corpus = copy(RUNTIME / 'inputs/corpus.jsonl', inputs / 'corpus.jsonl')
    baseline = copy(PREVIOUS / 'baseline.json', inputs / 'previous-baseline.json')
    trials = [copy(PREVIOUS / ('trial-' + name + '.json'), inputs / ('trial-' + name + '.json'))
              for name in ('subst', 'extracted', 'core')]
    continuations = []
    for folder in args.measurement_dir:
        for outcome in json.loads((folder / 'outcomes.json').read_text()):
            path = Path(outcome['path'])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == outcome['sha256']
            continuations.append(copy(path, inputs / path.name))
        for path in folder.iterdir():
            if path.is_file():
                copy(path, output / 'measurements' / folder.name / path.name)
    preparations = []
    for path in args.build_report:
        report = json.loads(path.read_text())
        preparations.append(report)
        copy(path, output / 'preparation' / path.name)
        log = Path(report['log'])
        copy(log, output / 'preparation' / log.name)
    for path in (HERE / 'preparation-plan.json', HERE / 'preparation-results.json',
                 HERE / 'prepare_exact.py', HERE / 'prepare_remaining.py',
                 HERE / 'measure_prepared.py', Path(__file__)):
        copy(path, output / 'preparation' / path.name)
    for name in ('prepare_putnam25.py', 'putnam25-plan.json', 'putnam25-result.json',
                 'resume_putnam25.py', 'putnam25-resume-plan.json', 'putnam25-resume-result.json',
                 'inspect_source_gap.py', 'source-gap-diagnostic.json',
                 'storage_preflight.py', 'storage-preflight.json'):
        path = HERE / name
        if path.exists():
            copy(path, output / 'preparation' / name)
    copy(RUNTIME / 'snapshot.json', output / 'native-runtime.snapshot.json')
    reporter = HERE / 'report-code-v3'
    copy(reporter / 'snapshot.json', output / 'reporter.snapshot.json')
    copy(reporter / 'jevops/arena_benchmark_report.py', output / 'report-generator.py')
    checks = {
        'native_runtime': verify_snapshot(RUNTIME, '0dc965d987860cfbae9ff470d52f068fb8ac1f081056f5c89d038d91f23203fc'),
        'report_generator': verify_snapshot(reporter, '833ab5852a2e7940483a8b0fcb609981ca6f429eaeebb6a485180176afb757c2')}
    (output / 'snapshot-checks.json').write_text(json.dumps(checks, indent=2) + '\n')
    command = [sys.executable, '-I', '-B', '-c',
        'import importlib.util,sys;sys.path.insert(0,sys.argv.pop(1));p=sys.argv.pop(1);'
        's=importlib.util.spec_from_file_location("jevops.arena_benchmark_report",p);'
        'm=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);sys.exit(m.main())',
        str(RUNTIME), str(reporter / 'jevops/arena_benchmark_report.py'),
        '--corpus', str(corpus), '--baseline', str(baseline), '--output-dir', str(output / 'report')]
    for path in continuations:
        command += ['--continuation', str(path)]
    for path in trials:
        command += ['--trial', str(path)]
    subprocess.run(command, check=True)
    (output / 'archive-index.json').write_text(json.dumps(index, indent=2) + '\n')
    rows = ['# Preparation and benchmark continuation', '', '[Benchmark results](report/summary.md)', '',
        'The benchmark combines earlier observations with disjoint new native checks. '
        'Builds and cached unit tests do not establish proof success. No training or model calls.', '',
        '| Preparation run | Exit code | Timed out | Wall seconds |', '| --- | ---: | --- | ---: |']
    for report in preparations:
        rows.append(f"| {report['run_id']} | {report['exit_code']} | {report['timed_out']} | {report['wall_seconds']:.1f} |")
    storage_path = output / 'preparation/storage-preflight.json'
    if storage_path.exists():
        storage = json.loads(storage_path.read_text())
        blocked = [j['name'] for j in storage['remaining_jobs']
                   if j['status'] == 'INSUFFICIENT_PREFLIGHT_HEADROOM']
        rows += ['', '## Preparation limits', '',
                 f"Recorded available space: {storage['available_bytes'] / 1e9:.3f} GB within the "
                 f"{storage['allowance_bytes'] / 1e9:.0f} GB allowance. "
                 'Environments below their free-space preflight: ' + ', '.join(blocked) + '.',
                 'Other unprepared jobs are listed separately in `preparation/storage-preflight.json`; '
                 'a passing storage preflight is not a successful build. No cache deletion is authorized by this report.']
    gap_path = output / 'preparation/source-gap-diagnostic.json'
    if gap_path.exists():
        gap = json.loads(gap_path.read_text())
        rows += ['', '## Source-binding gap', '',
                 f"`{gap['problem']}` / `{gap['lean_tag']}` remains {gap['status']}. "
                 f"Exact reference occurrences: {gap['original_reference_occurrences']}; "
                 f"one-space variant occurrences: {gap['one_internal_space_variant_occurrences']}. "
                 'This is a location diagnostic, not a proof receipt or a change to admission rules.']
    rows += ['', 'Original logs, frozen-source checks, input hashes and per-environment native reports '
             'are archived alongside this generated summary. No official Arena score is inferred.', '']
    (output / 'README.md').write_text('\n'.join(rows))


if __name__ == '__main__':
    main()
