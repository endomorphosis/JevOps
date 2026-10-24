"""Private custody/resource fixtures; never download, allocate CUDA or start a unit."""
import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('runtime_qualification_subject', ROOT / 'tools/lean_refactor_runtime_qualification.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
GIB = 1024**3


def resources():
    return {'observed_at': 1, 'gpu_processes': [], 'resources': {
        'mem_available_bytes': 64 * GIB, 'storage_available_bytes': 64 * GIB,
        'gpus': [{'used_mib': 200, 'free_mib': 24000, 'utilization_percent': 0} for _ in range(2)]}}


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    model = tmp_path / 'model.gguf'; model.write_bytes(b'GGUF-private-artifact')
    runtime = tmp_path / 'runtime'; runtime.mkdir()
    files = {}
    for index in range(55):
        path = runtime / ('llama-server' if index == 0 else f'lib{index}.so')
        path.write_bytes(f'private-runtime-{index}'.encode())
        files[str(path.relative_to(tmp_path))] = m.sha(path)
    module = SimpleNamespace(ROOT=tmp_path, RUNTIME=runtime, MODEL_NAME=model.name,
        MODEL_SHA=m.sha(model), MODEL_BYTES=model.stat().st_size, REVISION='pinned-revision',
        model_header=Mock(return_value={'estimated_cpu_tensor_bytes': 34 * GIB}), digest=Mock(side_effect=m.sha))
    weights = {'sha256': module.MODEL_SHA, 'bytes': module.MODEL_BYTES,
               'repository_revision': module.REVISION, 'identity': m.ordinary(model)}
    receipt = {'tag': 'b11850', 'source_commit': '9ae73e68f5a78933c0d988bbd17bf4647ad6a0b2',
               'server_sha256': files['runtime/llama-server'], 'files': files, 'version': 'private test runtime'}
    for name, value in [('weights-verified.json', weights), ('runtime-verified.json', receipt)]:
        (tmp_path / name).write_text(json.dumps(value))
    monkeypatch.setattr(m, 'WEIGHTS_RECEIPT_SHA', m.sha(tmp_path / 'weights-verified.json'))
    monkeypatch.setattr(m, 'RUNTIME_RECEIPT_SHA', m.sha(tmp_path / 'runtime-verified.json'))
    monkeypatch.setattr(m, 'SERVER_SHA', receipt['server_sha256'])
    return module


def test_unchanged_custody_reuses_genuine_prior_full_sha_without_model_reread(artifact):
    result = m.artifacts(artifact)
    artifact.digest.assert_not_called()
    assert result['weights_verified'] and result['runtime_files_verified'] == 55
    assert result['live_readiness_implied'] is False


def test_replaced_identical_model_requires_explicit_full_rehash(artifact):
    model = artifact.ROOT / artifact.MODEL_NAME
    replacement = model.with_suffix('.replacement'); replacement.write_bytes(model.read_bytes())
    replacement.replace(model)
    with pytest.raises(RuntimeError, match='custody changed'):
        m.artifacts(artifact)
    artifact.digest.assert_not_called()
    result = m.artifacts(artifact, allow_full_rehash=True)
    artifact.digest.assert_called_once_with(model)
    assert result['verification_method'] == 'fresh_complete_sha256'


def test_changed_model_rehash_fails_and_never_relabels_original_receipt(artifact):
    model = artifact.ROOT / artifact.MODEL_NAME
    receipt = artifact.ROOT / 'weights-verified.json'; original = receipt.read_bytes()
    model.write_bytes(b'X' * model.stat().st_size)
    with pytest.raises(RuntimeError, match='SHA mismatch'):
        m.artifacts(artifact, allow_full_rehash=True)
    assert receipt.read_bytes() == original


def test_fabricated_custody_receipt_is_not_a_full_sha_substitute(artifact):
    path = artifact.ROOT / 'weights-verified.json'
    value = json.loads(path.read_text()); value['identity']['inode'] += 1
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match='Pinned receipt changed'):
        m.artifacts(artifact)


def test_model_symlink_and_runtime_artifact_tamper_refused(artifact):
    library = artifact.RUNTIME / 'lib1.so'; library.write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='Runtime artifact changed'):
        m.artifacts(artifact)
    model = artifact.ROOT / artifact.MODEL_NAME
    saved = model.with_suffix('.saved'); model.rename(saved); model.symlink_to(saved)
    with pytest.raises(RuntimeError, match='ordinary file'):
        m.artifacts(artifact)


def test_quiescent_compute_does_not_mean_gpu_memory_is_unowned():
    value = resources()
    value['resources']['gpus'][0].update(used_mib=22328, free_mib=2248)
    value['gpu_processes'] = [{'pid': 123, 'used_mib': 22328}]
    assert set(m.resource_blockers(value)) == {'gpu_memory_ceiling', 'existing_gpu_ownership'}


@pytest.mark.parametrize('field', ['mem_available_bytes', 'storage_available_bytes'])
def test_real_reserves_cannot_be_pooled_or_substituted(field):
    value = resources(); value['resources'][field] = 16 * GIB - 1
    assert m.resource_blockers(value)


def properties():
    return {'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'running', 'MainPID': '101',
            'RuntimeMaxUSec': '4h', 'MemoryHigh': str(48 * GIB), 'MemoryMax': str(64 * GIB),
            'MemorySwapMax': '0', 'CPUQuotaPerSecUSec': '8s', 'TasksMax': '128', 'KillMode': 'control-group',
            'Restart': 'no', 'ControlGroup': '/private/test-unit'}


@pytest.mark.parametrize('key,value', [('RuntimeMaxUSec', 'infinity'), ('RuntimeMaxUSec', '5h'),
    ('MemoryMax', str(65 * GIB)), ('MemorySwapMax', 'infinity'), ('Restart', 'always'),
    ('TasksMax', 'infinity'), ('KillMode', 'process'), ('ActiveState', 'inactive')])
def test_running_unit_requires_exact_reviewed_resource_lifetime_policy(key, value):
    p = properties(); m.validate_unit(p)
    p[key] = value
    with pytest.raises(RuntimeError): m.validate_unit(p)


@pytest.fixture
def live(artifact, monkeypatch):
    module = artifact
    supervisor = {'pid': 101, 'start_ticks': '300', 'ppid': 1, 'exe': str(m.PYTHON.resolve()),
        'argv': [str(m.PYTHON), '-B', str(ROOT / m.PROVISIONER), 'serve'], 'cgroup': '0::/private/test-unit\n'}
    server = {'pid': 102, 'start_ticks': '400', 'ppid': 101, 'exe': str((module.RUNTIME / 'llama-server').resolve()),
              'argv': m.expected_server_command(module), 'cgroup': supervisor['cgroup']}
    processes = {101: supervisor, 102: server}
    owner = {'uid': os.getuid(), 'supervisor_pid': 101, 'server_pid': 102, 'server_start_ticks': '400',
             'command': server['argv'], 'endpoint': 'http://127.0.0.1:18180/v1'}
    status = {'running': True, 'ready': True, 'server_pid': 102, 'observed_at': m.time.time()}
    for name, value in [('server-owner.json', owner), ('server-resource-status.json', status)]:
        (module.ROOT / name).write_text(json.dumps(value))
    module.resources = Mock(return_value=resources()['resources'])
    module.process_rss = Mock(return_value=36 * GIB)
    module.check_resources = Mock()
    responses = {'/health': (200, {'status': 'ok'}), '/v1/models': (200, {'data': [{'id': 'Leanstral'}]}),
        '/props': (200, {'model_path': str(module.ROOT / module.MODEL_NAME), 'default_generation_settings': {'n_ctx': 2048}})}
    module.request = Mock(side_effect=lambda path: responses[path])
    monkeypatch.setattr(m, 'process_identity', lambda pid: copy.deepcopy(processes[pid]))
    return module, processes, responses


def test_live_ready_requires_native_identity_and_actual_metadata_not_old_receipt(live):
    module, _, _ = live
    result = m.live_readiness(module, properties())
    assert result['ready'] and result['actual_context_tokens'] == 2048
    assert module.request.call_count == 3
    assert result['alias_is_not_checkpoint_ancestry_attestation']


@pytest.mark.parametrize('fault', ['start', 'cgroup_prefix', 'wrong_model', 'stale_guard'])
def test_live_readiness_rejects_identity_staleness_and_alias_only_attestation(live, fault):
    module, processes, responses = live
    if fault == 'start': processes[102]['start_ticks'] = 'new-owner'
    elif fault == 'cgroup_prefix': processes[102]['cgroup'] = '0::/private/test-unit-foreign\n'
    elif fault == 'wrong_model': responses['/props'][1]['model_path'] = '/foreign/model.gguf'
    else:
        path = module.ROOT / 'server-resource-status.json'
        value = json.loads(path.read_text()); value['observed_at'] -= 120
        path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError): m.live_readiness(module, properties())


def test_qualifier_resource_wait_never_launches_or_calls_generation(artifact, monkeypatch):
    snapshot = resources(); snapshot['gpu_processes'] = [{'pid': 121, 'used_mib': 22328}]
    monkeypatch.setattr(m, 'provisioner', lambda root: (artifact, {}))
    monkeypatch.setattr(m, 'resource_snapshot', lambda module: snapshot)
    monkeypatch.setattr(m, 'unit_properties', lambda: {'LoadState': 'not-found', 'ActiveState': 'inactive'})
    launch = Mock(side_effect=AssertionError('occupied GPUs must not launch'))
    monkeypatch.setattr(m, 'start_owned', launch)
    result, code = m.qualify(start_if_needed=True)
    assert code == 75 and result['qualified'] is False and result['ready'] is False
    assert result['status'] == 'resource_blocked' and result['retry_after_seconds'] == 120
    assert result['resource_snapshot']['gpu_processes'][0]['pid'] == 121
    assert result['generation_executed'] is False
    launch.assert_not_called()


def test_native_smoke_is_one_bounded_actual_response_and_never_proof(artifact):
    artifact.request = Mock(return_value=(200, {'model': 'Leanstral',
        'choices': [{'message': {'content': '```lean\nrfl\n```'}}], 'usage': {'completion_tokens': 8}}))
    result = m.inference_smoke(artifact)
    call = artifact.request.call_args
    assert call.args == ('/v1/chat/completions',)
    assert call.kwargs['payload']['max_tokens'] == 16 and call.kwargs['timeout'] == 120
    assert result['Lean_executed'] is False and result['model_output_is_unverified_draft']


def test_smoke_never_retries_generation_after_post_liveness_failure(artifact, monkeypatch):
    monkeypatch.setattr(m, 'provisioner', lambda root: (artifact, {}))
    monkeypatch.setattr(m, 'resource_snapshot', lambda module: resources())
    monkeypatch.setattr(m, 'unit_properties', lambda: properties())
    readiness = Mock(side_effect=[{'ready': True}, RuntimeError('owner lost after one POST')])
    monkeypatch.setattr(m, 'live_readiness', readiness)
    generate = Mock(return_value={'actual_response': 'unverified', 'max_output_tokens': 16})
    monkeypatch.setattr(m, 'inference_smoke', generate)
    result, code = m.qualify(smoke=True, wait_seconds=180)
    assert code == 75 and not result['stage023_acceptance_satisfied']
    assert result['generation_executed'] and generate.call_count == 1
    assert readiness.call_count == 2


def test_cheap_probe_cannot_read_model_or_start_services(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    monkeypatch.setattr(m, 'provisioner', lambda: (SimpleNamespace(), {}))
    monkeypatch.setattr(m, 'resource_snapshot', lambda module: resources())
    forbidden = Mock(side_effect=AssertionError('cheap probe must not qualify/start'))
    monkeypatch.setattr(m, 'artifacts', forbidden)
    monkeypatch.setattr(m, 'start_owned', forbidden)
    assert m.main(['--probe-resources']) == 0
    forbidden.assert_not_called()
    assert json.loads((tmp_path / m.OUTPUT / 'resource-probe.json').read_text())['generation_executed'] is False


def test_explicit_wait_budget_rejects_unbounded_and_boolean():
    for wait in (True, -1, 301):
        with pytest.raises(RuntimeError, match='Bounded'): m.qualify(wait_seconds=wait)


@pytest.mark.parametrize('payload', [
    '<testsuites><testsuite/></testsuites>',
    '<testsuites><testsuite><testcase name="x"><skipped/></testcase></testsuite></testsuites>',
    '<testsuites><testsuite><testcase name="x"><failure/></testcase></testsuite></testsuites>'])
def test_fixture_xml_cannot_promote_skipped_failed_or_unexecuted_work(tmp_path, payload):
    path = tmp_path / 'actual.xml'; path.write_text(payload)
    with pytest.raises(RuntimeError): m.parse_junit(path)


def test_fixture_xml_records_executed_native_cases(tmp_path):
    path = tmp_path / 'actual.xml'
    path.write_text('<testsuites><testsuite><testcase classname="kernel" name="pidfd_recovery"/></testsuite></testsuites>')
    result = m.parse_junit(path)
    assert result['executed_testcases'] == 1 and result['case_names'] == ['kernel.pidfd_recovery']
