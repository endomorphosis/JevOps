"""Private and canonical tests of the separately bound compiled checker."""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jevops import arena_compiled as compiled, arena_lean as native
from jevops.arena import Outcome, VerificationRequest, content_hash
from jevops.lean import VersionPin

PIN = VersionPin('v4.26.0', 'a' * 40)
STATEMENT = 'theorem sample (h : True) : True'
RECORD = {'name': 'sample', 'statement': STATEMENT, 'src': STATEMENT + ' := by exact h',
          'version_info': [{PIN.lean_tag: PIN.git_commit}]}


def test_selective_driver_preserves_original_elaboration_and_uses_a_distinct_identity():
    original, derived = native.DRIVER.read_text(), compiled.DRIVER.read_text()
    assert native.DRIVER != compiled.DRIVER
    assert original[:original.index('structure AuditState where')] == derived[:derived.index('structure AuditState where')]
    assert original[original.index('\nunsafe def check '):] == derived[derived.index('\nunsafe def check '):]
    assert 'selective-audit' in compiled.POLICY
    assert compiled.MAX_MEMORY == 4 * 1024**3 and compiled.MAX_BYTES == 128 * 1024**2


class FixtureChecker:
    def __init__(self):
        self.manifest = {'fixture': 'private exact build'}
        self.changed = False

    def validate(self, binding):
        if self.changed:
            raise ValueError('fixture checker was replaced')


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    monkeypatch.setattr(native.ProjectBinding, 'fingerprint', lambda *_: content_hash('prepared fixture dependencies'))
    binding = native.ProjectBinding(PIN, tmp_path / 'bin/lean', tmp_path, '', project_backed=False)
    checker = FixtureChecker()
    return compiled.CompiledNativeLeanVerifier({PIN: binding}, checkers={PIN: checker}, max_processes=4)


def request(adapter, **changes):
    return VerificationRequest(replace(adapter.context(RECORD), **changes), RECORD['src'], PIN)


def report(payload, **changes):
    return {'schema': 'jevops-native-arena/v1', 'request_id': payload['request_id'], 'target': payload['target'],
            'measurement': native.METHOD, 'branch_order': 'candidate-first' if payload['candidate_first'] else 'reference-first',
            'lean_version': '4.26.0', 'lean_githash': 'b' * 40,
            'report': {'outcome': 'VERIFIED', 'reason': '', 'type_preserved': True, 'target_absent_before': True,
                       'raw_heartbeats': 3000, 'heartbeats': 3, 'reference_raw_heartbeats': 6000,
                       'reference_heartbeats': 6, 'axioms': [], 'reference_axioms': [], 'diagnostics': [], **changes}}


def runner(monkeypatch, **changes):
    calls = []
    def run(binding, payload, **kwargs):
        calls.append(payload)
        return report(payload, **changes), 0, {'fixture_execution': True}
    monkeypatch.setattr(compiled, 'run_compiled', run)
    return calls


def test_new_context_is_distinct_and_retains_native_measurements(adapter, monkeypatch):
    calls = runner(monkeypatch)
    base = native.NativeLeanVerifier(adapter.bindings, max_processes=1)
    assert base.context(RECORD).context_id != adapter.context(RECORD).context_id
    receipt = adapter(request(adapter))
    assert receipt.outcome == Outcome.VERIFIED and receipt.heartbeats == 3 and len(calls) == 1
    observation = json.loads(receipt.observations_json)
    assert observation['compiled_backend'] == adapter.checkers[PIN].manifest
    assert observation['report']['raw_heartbeats'] == 3000


@pytest.mark.parametrize('change', [
    {'type_preserved': False}, {'target_absent_before': False}, {'raw_heartbeats': 2999},
    {'heartbeats': True}, {'reference_raw_heartbeats': -1}, {'axioms': 'forged'},
    {'reference_heartbeats': float('nan')},
])
def test_compiled_path_keeps_protected_observation_checks(adapter, monkeypatch, change):
    runner(monkeypatch, **change)
    receipt = adapter(request(adapter))
    assert receipt.outcome == Outcome.ERROR and not receipt.type_preserved


@pytest.mark.parametrize('field,expected', [('axioms', Outcome.REJECTED), ('reference_axioms', Outcome.ERROR)])
def test_axiom_growth_cannot_become_compiled_success(adapter, monkeypatch, field, expected):
    runner(monkeypatch, **{field: ['sorryAx']})
    assert adapter(request(adapter)).outcome == expected


@pytest.mark.parametrize('field,value', [('target', 'other'), ('request_id', 'forged'),
    ('lean_version', '4.34.0'), ('lean_githash', 'unknown'), ('branch_order', 'candidate-first'),
    ('measurement', 'elapsed-milliseconds')])
def test_wrong_native_envelope_refuses(adapter, monkeypatch, field, value):
    def run(binding, payload, **kwargs):
        data = report(payload)
        data[field] = value
        return data, 0, {}
    monkeypatch.setattr(compiled, 'run_compiled', run)
    assert adapter(request(adapter)).outcome == Outcome.ERROR


@pytest.mark.parametrize('mutation', ['before', 'during', 'manifest'])
def test_changed_binary_or_manifest_invalidates_context(adapter, monkeypatch, mutation):
    req = request(adapter)
    calls = runner(monkeypatch)
    if mutation == 'before':
        adapter.checkers[PIN].changed = True
    elif mutation == 'manifest':
        adapter.checkers[PIN].manifest['fixture'] = 'replaced'
    else:
        def changed(binding, payload, **kwargs):
            adapter.checkers[PIN].changed = True
            return report(payload), 0, {}
        monkeypatch.setattr(compiled, 'run_compiled', changed)
    assert adapter(req).outcome == Outcome.ERROR
    if mutation != 'during':
        assert not calls and adapter.processes == 0


def test_exhaustion_and_timeout_charge_actual_launches(adapter, monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError('actual bounded timeout')
    monkeypatch.setattr(compiled, 'run_compiled', timeout)
    adapter.max_processes = 1
    req = request(adapter)
    assert adapter(req).outcome == Outcome.TIMEOUT
    assert adapter(req).outcome == Outcome.BUDGET_EXHAUSTED and adapter.processes == 1


def test_build_map_and_execution_cap_must_be_explicit(adapter):
    with pytest.raises(ValueError, match='every exact pin'):
        compiled.CompiledNativeLeanVerifier(adapter.bindings, checkers={}, max_processes=1)
    with pytest.raises(ValueError, match='sixty-second'):
        compiled.CompiledNativeLeanVerifier(adapter.bindings, checkers=adapter.checkers, max_processes=1, timeout=61)


def test_owned_capture_enforces_limits_and_does_not_signal_neighbor(tmp_path):
    neighbor = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(20)'])
    fd = os.pidfd_open(neighbor.pid)
    try:
        output, errors, code, observation = compiled.capture(
            [sys.executable, '-c', 'import resource,json;print(json.dumps([resource.getrlimit(resource.RLIMIT_AS)[0],resource.getrlimit(resource.RLIMIT_FSIZE)[0]]))'],
            tmp_path / 'limits', {'PATH': '/usr/bin:/bin'}, {}, 5)
        assert code == 0 and json.loads(output) == [4 * 1024**3, 128 * 1024**2]
        _, _, code, observation = compiled.capture([sys.executable, '-c', 'import time;time.sleep(20)'],
            tmp_path / 'timeout', {'PATH': '/usr/bin:/bin'}, {}, .1)
        assert code == 124 and observation['timed_out'] and observation['process_reaped']
        assert observation['cleanup'] and neighbor.poll() is None
    finally:
        import signal
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        neighbor.wait(timeout=5)
        os.close(fd)


def test_fresh_build_custody_rejects_source_and_executable_mutation(tmp_path, monkeypatch):
    lean = tmp_path / 'toolchain/bin/lean'
    lean.parent.mkdir(parents=True)
    lean.write_text('fixture lean')
    lean.with_name('leanc').write_text('fixture leanc')
    lib = lean.parent.parent / 'lib/lean'
    lib.mkdir(parents=True)
    for name in compiled.LIBRARIES:
        (lib / name).write_text('exact fixture ' + name)
    binding = native.ProjectBinding(PIN, lean, tmp_path, '', project_backed=False)
    calls = []
    def build(argv, directory, env, payload, timeout):
        calls.append(argv)
        directory.mkdir()
        if '-c' in argv:
            Path(argv[argv.index('-c') + 1]).write_text('fresh C')
        else:
            Path(argv[argv.index('-o') + 1]).write_text('fresh executable')
        return b'', b'', 0, {'timed_out': False, 'process_reaped': True}
    monkeypatch.setattr(compiled, 'capture', build)
    with compiled.prepare_checkers({PIN: binding}) as checkers:
        checker = checkers[PIN]
        assert len(calls) == 2 and checker.manifest['proof_cache'] is False
        checker.validate(binding)
        checker.executable.write_text('substituted executable')
        with pytest.raises(ValueError, match='custody'):
            checker.validate(binding)
    with compiled.prepare_checkers({PIN: binding}) as checkers:
        (lib / compiled.LIBRARIES[0]).write_text('changed library')
        with pytest.raises(ValueError, match='custody'):
            checkers[PIN].validate(binding)


def test_actual_pinned_compiled_fixture_and_type_axiom_guards():
    """Genuine fresh v4.26.0 child executions, separate from campaign receipts."""
    lean = native.pinned_lean(Path('/home/barberb/.elan'), 'v4.26.0')
    binding = native.ProjectBinding(PIN, lean, Path.cwd(), 'import Lean\n', project_backed=False)
    record = {**RECORD, 'statement': 'theorem sample : True', 'src': 'theorem sample : True := by trivial'}
    with compiled.prepare_checkers({PIN: binding}) as checkers:
        verifier = compiled.CompiledNativeLeanVerifier({PIN: binding}, checkers=checkers, max_processes=3, timeout=30)
        context = verifier.context(record)
        original = verifier(VerificationRequest(context, record['src'], PIN))
        changed = verifier(VerificationRequest(context, 'theorem sample : 1 = 1 := by rfl', PIN))
        axiom = verifier(VerificationRequest(context, 'theorem sample : True := by sorry', PIN))
        assert original.outcome == Outcome.VERIFIED and original.type_preserved
        assert changed.outcome == Outcome.REJECTED and axiom.outcome == Outcome.REJECTED
        # The public verifier rejects changed headers and sorry before launching.
        assert verifier.processes == 1
        payload = {'request_id': 'raw-fixture', 'target': 'sample', 'prefix': binding.prefix,
                   'reference': record['src'], 'max_heartbeats': 2_000_000, 'candidate_first': False}
        changed_raw, _, _ = compiled.run_compiled(binding, {**payload, 'candidate': 'theorem sample : 1 = 1 := by rfl'},
                                                  timeout=30, checker=checkers[PIN])
        sorry_raw, _, _ = compiled.run_compiled(binding, {**payload, 'candidate': 'theorem sample : True := by sorry'},
                                                timeout=30, checker=checkers[PIN])
        assert changed_raw['report']['outcome'] == 'REJECTED'
        assert 'sorryAx' in sorry_raw['report']['axioms'] and 'sorryAx' not in sorry_raw['report']['reference_axioms']
