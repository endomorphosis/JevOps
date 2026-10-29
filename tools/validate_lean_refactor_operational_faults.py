#!/usr/bin/env python3
"""Protected custody of a historical, actually executed operational fault suite."""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lean_refactor_operational_faults as m


def evidence_path(root, relative, run):
    path = Path(relative)
    m.require(not path.is_absolute() and '..' not in path.parts, 'unsafe fault evidence path')
    full = root/path
    m.require(full.resolve().is_relative_to(run.resolve()), 'fault evidence escapes own run')
    return full


def validate(root, data):
    root = root.resolve(strict=True)
    m.require(data['schema'] == m.SCHEMA and data['task_id'] == 'JLR-033'
              and data['status'] == 'QUALIFIED_OWNED_FIXTURES', 'operational fault identity')
    m.require(all(type(data.get(key)) is type(value) and data[key] == value
                  for key, value in m.AUTH.items()), 'fault fixture authority/scope changed')
    relative = data['run_directory']
    m.require(re.fullmatch(re.escape(m.RUNTIME)+r'/operational-faults/[0-9a-f]{32}', relative),
              'unexpected fault run namespace')
    run = root/relative
    m.require(run.resolve().is_relative_to((root/m.RUNTIME/'operational-faults').resolve()), 'run escapes root')
    m.require(m.sha(root/m.SELF) == data['producer_sha256']
              and m.sha(root/m.VALIDATOR) == data['validator_sha256'], 'fault producer/validator changed')
    sources = data['tested_sources']
    m.require(type(sources) is dict and 1 <= len(sources) <= m.MAX_SOURCES
              and data['tested_operational_version'] == m.source_version(sources), 'tested version changed')
    total = 0
    for name, row in sources.items():
        m.require(name.startswith(('jevops/', 'accelerator/')) and '..' not in Path(name).parts,
                  'tested source namespace')
        path = evidence_path(root, row['archive'], run)
        raw = m.raw_file(path);total += len(raw)
        m.require(m.digest(raw) == row['sha256'] and type(row['bytes']) is int
                  and row['bytes'] == len(raw), 'tested source snapshot changed')
    m.require(total <= m.MAX_SOURCE_BYTES, 'tested source snapshot byte bound')
    for scope, path, _ in m.POLICY:
        m.require(scope+'/'+path in sources, 'required tested fault suite missing')
    m.require(all('accelerator/'+name in sources for name in m.CORE_MODULES)
              and 'jevops/tools/reload_supervisor_when_idle.py' in sources
              and 'jevops/config/lean_refactor_arena_20261024_watchdog.json' in sources,
              'tested operational implementation snapshot missing')
    m.require(sources['jevops/'+m.SELF]['sha256'] == data['producer_sha256']
              and sources['jevops/'+m.VALIDATOR]['sha256'] == data['validator_sha256'], 'tested producer binding')
    expected_evidence = {'actual-tests.xml', 'stdout.log', 'stderr.log', 'execution.json'}
    m.require(set(data['evidence']) == expected_evidence, 'raw fault execution evidence population')
    for name, row in data['evidence'].items():
        path = evidence_path(root, row['path'], run)
        m.require(path == run/name and m.sha(path) == row['sha256'], 'raw fault execution evidence changed')
    execution = json.loads(m.raw_file(run/'execution.json'))
    m.require(execution == data['execution'], 'execution differs from original process observation')
    python, accelerator = m.configuration(root)
    expected = [str(python), '-B', '-m', 'pytest', '-q', '-c', '/dev/null', '--noconftest',
                '-p', 'no:cacheprovider', '--rootdir='+str(root.parent), '--basetemp='+str(run/'private-fixtures'),
                '--junitxml='+str(run/'actual-tests.xml'), *m.selectors(root, accelerator)]
    m.require(execution['argv'] == expected and execution['cwd'] == str(root)
              and type(execution['exit_code']) is int and execution['exit_code'] == 0
              and execution['timed_out'] is False and execution['private_process_group_empty'] is True
              and execution['shell'] is False and execution['timeout_seconds'] == m.TIMEOUT
              and type(execution['pid']) is int and execution['pid'] > 0
              and execution['uid'] == __import__('os').getuid(), 'closed actual fault execution required')
    for key in ('started_at', 'finished_at'):
        m.require(type(execution[key]) in (int, float) and math.isfinite(execution[key]), 'invalid execution timestamp')
    m.require(0 <= execution['finished_at']-execution['started_at'] <= m.TIMEOUT+10
              and type(data['observed_at']) in (int, float) and math.isfinite(data['observed_at'])
              and execution['finished_at'] <= data['observed_at'] <= execution['finished_at']+60
              and data['observed_at'] <= time.time()+5, 'fault timing differs')
    actual = m.parse_junit(run/'actual-tests.xml')
    m.require(actual == data['actual_tests'], 'fresh JUnit differs from declared coverage')
    protected = data['protected_state_before']
    required = {m.BASE, 'implementation_plan/lean_refactor_arena_20261024.goals.json',
                'implementation_plan/lean_refactor_arena_20261024.todo.md',
                'implementation_plan/lean_refactor_arena_20261024.execution-v2.todo.md',
                'config/lean_refactor_arena_20261024_execution_v2.json',
                'data/lean_refactor_arena_20261024/router-budget.json'}
    m.require(required <= set(protected) <= required | {m.RUNTIME+'/iterative-v1-ledger.json'}
              and protected == data['protected_state_after']
              and all(re.fullmatch('[0-9a-f]{64}', value) for value in protected.values()),
              'campaign state not preserved during actual faults')
    m.require(set(data['protected_state_archives']) == set(protected), 'protected state archive population')
    for name, relative in data['protected_state_archives'].items():
        m.require(m.sha(evidence_path(root, relative, run)) == protected[name], 'protected state archive changed')
    original = json.loads(m.raw_file(run/'result.json', 4*1024**2))
    m.require(original == data, 'original fault result changed')
    # Current control bytes are diagnostic only. This is a historical tested
    # operational version, not an evergreen claim about later control changes.
    current = m.source_files(root, accelerator)
    matches = set(current) == set(sources) and all(m.sha(current[k]) == sources[k]['sha256'] for k in current)
    return {'operational_fault_cases': actual['executed_testcases'],
            'tested_operational_version': data['tested_operational_version'],
            'historical_qualification': True, 'current_operational_version_matches': matches,
            'scope': data['scope'], **m.AUTH}
