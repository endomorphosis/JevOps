#!/usr/bin/env python3
"""Qualify the existing owned Leanstral deployment without downloads or training.

Artifact custody can remain valid while live inference is unavailable.  Such a
resource wait is exit 75, never a successful JLR-023 result.  The cheap resource
probe is suitable for a bounded retry observer and never imports CUDA.
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STORE = Path('/storage/hf_cache/jevops-leanstral-20261024')
PYTHON = Path('/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python')
ACCELERATE = Path('/home/barberb/lift_coding/external/ipfs_accelerate')
OUTPUT = 'data/lean_refactor_runtime_20261024'
SELF = 'tools/lean_refactor_runtime_qualification.py'
UNIT = 'jevops-leanstral-20261024.service'
PROVISIONER = 'tools/provision_leanstral_20261024.py'
DESCRIPTOR = 'tools/leanstral-inference-20261024.json'
PINS = {PROVISIONER: '6784c88d332c8dcd4aa213fabc620261c7d624f93800031ac8bfaf6e4ffc95fe',
        DESCRIPTOR: '304700c24a8f4dec1948734c8022b8d8a438230d1c8435e1d5db0c67a3fe3f5e'}
WEIGHTS_RECEIPT_SHA = 'ee7e6983528a112a539ecddcd9f7cea50124b9067fda3a2786ff85d91058f750'
RUNTIME_RECEIPT_SHA = 'd89ff826c7910b4f8a052129d46c17017f94416f6cece6ba14331b7fcab09c81'
SERVER_SHA = '559fa3816e39bd91569a132d58ff43f3ab7ef84686078caa10df5f137c30fc1c'
AUTH = {'completion_authority': False, 'proof_authority': False, 'training_executed': False,
        'generation_executed': False, 'paid_provider_calls': 0,
        'weights_officially_attested': False, 'conversion_quality_measured': False}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
            'Expected an owned single-link ordinary file: ' + str(path))
    return {'device': info.st_dev, 'inode': info.st_ino, 'bytes': info.st_size,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}


def read_json(path, expected_sha=None):
    before = ordinary(path)
    require(before['bytes'] <= 4 * 1024 * 1024, 'Metadata byte bound')
    raw = path.read_bytes()
    require(ordinary(path) == before, 'Metadata changed while reading')
    if expected_sha:
        require(hashlib.sha256(raw).hexdigest() == expected_sha, 'Pinned receipt changed: ' + str(path))
    value = json.loads(raw)
    require(type(value) is dict, 'Expected JSON object')
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(not path.is_symlink(), 'Refuse output symlink')
    temporary = path.with_name('.' + path.name + '.' + str(os.getpid()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        require(not path.is_symlink(), 'Output changed to symlink')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def provisioner(root=ROOT):
    for relative, expected in PINS.items():
        require(sha(root / relative) == expected, 'Provisioner/descriptor source changed: ' + relative)
    descriptor = read_json(root / DESCRIPTOR)
    require(descriptor['storage_root'] == str(STORE) and descriptor['endpoint'] == 'http://127.0.0.1:18180/v1'
            and descriptor['context_tokens'] == 2048 and descriptor['maximum_gpu_used_mib_each'] == 20480
            and descriptor['maximum_server_rss_bytes'] == 48 * 1024**3
            and descriptor['minimum_host_available_bytes'] == 16 * 1024**3,
            'Deployment limits/endpoint changed')
    spec = importlib.util.spec_from_file_location('leanstral_qualified_provisioner', root / PROVISIONER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, descriptor


def gpu_processes():
    result = subprocess.run(['nvidia-smi', '--query-compute-apps=pid,used_memory',
                             '--format=csv,noheader,nounits'], capture_output=True, text=True,
                            timeout=10, check=True)
    rows = []
    for line in result.stdout.splitlines():
        fields = [item.strip() for item in line.split(',')]
        require(len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit(),
                'Unverifiable GPU process inventory')
        rows.append({'pid': int(fields[0]), 'used_mib': int(fields[1])})
    return rows


def resource_snapshot(module):
    observation = module.resources()
    return {'observed_at': time.time(), 'resources': observation, 'gpu_processes': gpu_processes()}


def resource_blockers(snapshot, *, loading=True):
    observation = snapshot['resources']
    reasons = []
    if observation['mem_available_bytes'] < 16 * 1024**3:
        reasons.append('host_memory_reserve')
    if observation['storage_available_bytes'] < 16 * 1024**3:
        reasons.append('storage_reserve')
    cards = observation['gpus']
    if len(cards) != 2 or any(g['used_mib'] > 20480 for g in cards):
        reasons.append('gpu_memory_ceiling')
    if loading and (snapshot['gpu_processes'] or any(
            g['free_mib'] < 22528 or g['utilization_percent'] > 10 for g in cards)):
        reasons.append('existing_gpu_ownership')
    return reasons


def artifacts(module, *, allow_full_rehash=False):
    """Reuse only the source-pinned original full SHA plus exact kernel custody."""
    weights = read_json(module.ROOT / 'weights-verified.json', WEIGHTS_RECEIPT_SHA)
    model = module.ROOT / module.MODEL_NAME
    before = ordinary(model)
    require(weights['sha256'] == module.MODEL_SHA and weights['bytes'] == module.MODEL_BYTES
            and weights['repository_revision'] == module.REVISION, 'Weight identity changed')
    method = 'pinned_prior_full_sha_and_exact_current_kernel_identity'
    if before != weights['identity']:
        require(allow_full_rehash, 'Model custody changed; explicit bounded --rehash-model required')
        require(before['bytes'] == module.MODEL_BYTES, 'Model size changed')
        require(module.digest(model) == module.MODEL_SHA, 'Actual complete model SHA mismatch')
        method = 'fresh_complete_sha256'
    require(before['bytes'] == module.MODEL_BYTES, 'Model byte count changed')
    header = module.model_header(model)
    require(ordinary(model) == before, 'Model changed during qualification')
    runtime = read_json(module.ROOT / 'runtime-verified.json', RUNTIME_RECEIPT_SHA)
    require(runtime['tag'] == 'b11850' and runtime['source_commit'] == '9ae73e68f5a78933c0d988bbd17bf4647ad6a0b2'
            and runtime['server_sha256'] == SERVER_SHA and len(runtime['files']) == 55,
            'Runtime identity/file inventory changed')
    for relative, expected in runtime['files'].items():
        target = module.ROOT / relative
        require(target.resolve().is_relative_to(module.ROOT.resolve()), 'Runtime path escape')
        identity = ordinary(target)
        require(sha(target) == expected and ordinary(target) == identity, 'Runtime artifact changed: ' + relative)
    require(sha(module.RUNTIME / 'llama-server') == SERVER_SHA, 'Actual server hash mismatch')
    return {'weights_verified': True, 'model_sha256': module.MODEL_SHA, 'model_bytes': module.MODEL_BYTES,
            'model_identity': before, 'verification_method': method, 'actual_header': header,
            'weights_receipt_sha256': WEIGHTS_RECEIPT_SHA, 'runtime_receipt_sha256': RUNTIME_RECEIPT_SHA,
            'runtime_files_verified': len(runtime['files']), 'runtime_server_sha256': SERVER_SHA,
            'runtime_commit': runtime['source_commit'], 'historical_runtime_version': runtime['version'],
            'live_readiness_implied': False}


PROPERTIES = ('LoadState', 'ActiveState', 'SubState', 'MainPID', 'RuntimeMaxUSec', 'MemoryHigh',
              'MemoryMax', 'MemorySwapMax', 'CPUQuotaPerSecUSec', 'TasksMax', 'KillMode', 'Restart', 'ControlGroup')


def unit_properties():
    result = subprocess.run(['systemctl', '--user', 'show', UNIT,
                             '--property=' + ','.join(PROPERTIES)], capture_output=True, text=True,
                            timeout=15, check=True)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def validate_unit(properties):
    require(properties.get('LoadState') == 'loaded' and properties.get('ActiveState') == 'active'
            and properties.get('SubState') == 'running', 'Owned inference unit is not running')
    require(properties.get('RuntimeMaxUSec') == '4h' and properties.get('MemoryHigh') == str(48 * 1024**3)
            and properties.get('MemoryMax') == str(64 * 1024**3) and properties.get('MemorySwapMax') == '0'
            and properties.get('CPUQuotaPerSecUSec') == '8s' and properties.get('TasksMax') == '128'
            and properties.get('KillMode') == 'control-group'
            and properties.get('Restart') == 'no', 'Owned inference unit resource/lifetime policy differs')


def process_identity(pid, *, proc_root=Path('/proc')):
    path = proc_root / str(pid)
    require(path.stat().st_uid == os.getuid(), 'Process belongs to another UID')
    fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
    require(fields[0] not in {'Z', 'X'}, 'Owned process is not alive')
    return {'pid': pid, 'start_ticks': fields[19], 'ppid': int(fields[1]),
            'argv': [s.decode() for s in (path / 'cmdline').read_bytes().split(b'\0') if s],
            'exe': str((path / 'exe').resolve()), 'cgroup': (path / 'cgroup').read_text()}


def expected_server_command(module):
    return [str(module.RUNTIME / 'llama-server'), '--model', str(module.ROOT / module.MODEL_NAME),
            '--alias', 'Leanstral', '--host', '127.0.0.1', '--port', '18180', '--ctx-size', '2048',
            '--parallel', '1', '--threads', '8', '--threads-batch', '8', '--batch-size', '64',
            '--ubatch-size', '32', '--n-gpu-layers', '18', '--split-mode', 'layer',
            '--tensor-split', '1,1', '--fit', 'off', '--load-mode', 'dio', '--flash-attn', 'off',
            '--jinja', '--reasoning', 'off', '--no-warmup']


def live_readiness(module, properties, root=ROOT):
    validate_unit(properties)
    owner = read_json(module.ROOT / 'server-owner.json')
    supervisor = process_identity(int(properties['MainPID']))
    server = process_identity(int(owner['server_pid']))
    require(owner['uid'] == os.getuid() and owner['supervisor_pid'] == supervisor['pid']
            and server['start_ticks'] == str(owner['server_start_ticks'])
            and server['ppid'] == supervisor['pid'], 'Server/kernel ownership mismatch')
    require(Path(supervisor['exe']) == PYTHON.resolve()
            and supervisor['argv'] in ([str(PYTHON), '-B', str(root / PROVISIONER), 'serve'],
                                      [str(PYTHON), str(root / PROVISIONER), 'serve']),
            'Unit MainPID is not the pinned provisioner')
    require(server['exe'] == str((module.RUNTIME / 'llama-server').resolve())
            and server['argv'] == owner['command'] == expected_server_command(module)
            and owner['endpoint'] == 'http://127.0.0.1:18180/v1',
            'Actual server identity/endpoint changed')
    require(properties['ControlGroup'] and all(properties['ControlGroup'] in {
            line.split(':', 2)[2] for line in p['cgroup'].splitlines() if line.count(':') >= 2}
            for p in (supervisor, server)), 'Owned processes left the bounded cgroup')
    status = read_json(module.ROOT / 'server-resource-status.json')
    require(status.get('ready') is True and status.get('running') is True
            and status['server_pid'] == server['pid'] and 0 <= time.time() - status['observed_at'] < 30,
            'Stale or unavailable live resource guard')
    observation = module.resources()
    rss = module.process_rss(server['pid'])
    module.check_resources(observation, rss=rss)
    code, health = module.request('/health')
    model_code, models = module.request('/v1/models')
    props_code, props = module.request('/props')
    require(code == model_code == props_code == 200 and health.get('status') == 'ok'
            and any(row.get('id') == 'Leanstral' for row in models.get('data', []))
            and props.get('model_path') == str(module.ROOT / module.MODEL_NAME)
            and props.get('default_generation_settings', {}).get('n_ctx') == 2048,
            'Actual local API/model descriptor differs')
    require(process_identity(server['pid']) == server and process_identity(supervisor['pid']) == supervisor,
            'Owned process changed during HTTP checks')
    return {'ready': True, 'health': health, 'models': models,
            'reported_model_basename': module.MODEL_NAME, 'actual_context_tokens': 2048,
            'owner': {'supervisor_pid': supervisor['pid'], 'server_pid': server['pid'],
                      'server_start_ticks': server['start_ticks']},
            'unit': properties, 'resources': observation, 'server_rss_bytes': rss,
            'alias_is_not_checkpoint_ancestry_attestation': True}


def start_owned(module, artifact, root=ROOT):
    snapshot = resource_snapshot(module)
    require(not resource_blockers(snapshot), 'Current resources are owned/unavailable; refuse launch')
    module.check_resources(snapshot['resources'], loading=True,
                           cpu_weight_bytes=artifact['actual_header']['estimated_cpu_tensor_bytes'])
    # The original one-shot ARC exception is not silently reset by qualification.
    if snapshot['resources']['mem_available_bytes'] < 48 * 1024**3:
        require(not (module.ROOT / 'arc-aware-preload-attempt.json').exists(),
                'Prior one-shot ARC preload attempt already consumed; no automatic repeat')
    args = ['systemd-run', '--user', '--unit=' + UNIT.removesuffix('.service'), '--collect',
            '--property=RuntimeMaxSec=14400', '--property=MemoryHigh=48G', '--property=MemoryMax=64G',
            '--property=MemorySwapMax=0', '--property=CPUQuota=800%', '--property=TasksMax=128',
            '--property=KillMode=control-group', '--property=Restart=no', '--property=Nice=5',
            '--setenv=PYTHONDONTWRITEBYTECODE=1', str(PYTHON), '-B', str(root / PROVISIONER), 'serve']
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    return {'actual_argv': args, 'spawn_is_not_readiness': True}


def inference_smoke(module):
    started = time.monotonic()
    code, result = module.request('/v1/chat/completions', payload={
        'model': 'Leanstral', 'messages': [{'role': 'user', 'content':
            'Reply only with the Lean tactic that proves: theorem local_identity (x : Nat) : x = x := by'}],
        'max_tokens': 16, 'temperature': 0, 'stream': False}, timeout=120)
    require(code == 200 and result.get('model') == 'Leanstral'
            and isinstance(result.get('choices'), list) and result['choices']
            and isinstance(result['choices'][0].get('message', {}).get('content'), str)
            and type(result.get('usage', {}).get('completion_tokens')) is int
            and 0 < result['usage']['completion_tokens'] <= 16,
            'Actual bounded native inference response required')
    return {'actual_response': result, 'max_output_tokens': 16,
            'wall_seconds': time.monotonic() - started, 'Lean_executed': False,
            'model_output_is_unverified_draft': True}


def qualify(*, root=ROOT, start_if_needed=False, wait_seconds=180, rehash_model=False, smoke=False):
    require(type(wait_seconds) is int and 0 <= wait_seconds <= 300, 'Bounded readiness wait required')
    module, _ = provisioner(root)
    result = {'schema': 'jevops.lean-refactor.runtime-qualification.v1', 'observed_at': time.time(),
              'ready': False, 'qualified': False, 'stage023_acceptance_satisfied': False,
              'source_sha256': {k: sha(root / k) for k in (*PINS, SELF)}, **AUTH}
    result['resource_snapshot'] = resource_snapshot(module)
    # No hashing of 67 GiB on ordinary retries: an exact pinned receipt/identity
    # permits custody reuse, and --rehash-model is an explicit separate action.
    result['artifacts'] = artifacts(module, allow_full_rehash=rehash_model)
    properties = unit_properties()
    if properties.get('ActiveState') != 'active':
        reasons = resource_blockers(result['resource_snapshot'])
        if reasons or not start_if_needed:
            result.update(status='resource_blocked' if reasons else 'service_not_running',
                          blockers=reasons or ['explicit_start_not_requested'], retry_after_seconds=120,
                          retry_after_epoch=time.time() + 120)
            return result, 75
        result['launch'] = start_owned(module, result['artifacts'], root)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            result['live'] = live_readiness(module, unit_properties(), root)
            if smoke:
                # Never repeat a POST just because a later liveness check fails.
                result['generation_executed'] = True
                result['native_smoke'] = inference_smoke(module)
                result['live_after_smoke'] = live_readiness(module, unit_properties(), root)
                result['stage023_acceptance_satisfied'] = True
            result.update(status='ready', ready=True, qualified=True, observed_at=time.time())
            return result, 0
        except (OSError, RuntimeError, KeyError, ValueError, subprocess.SubprocessError) as exc:
            result['readiness_failure'] = str(exc)
            if result['generation_executed'] or time.monotonic() >= deadline:
                result.update(status='readiness_unavailable', retry_after_seconds=120,
                              retry_after_epoch=time.time() + 120)
                return result, 75
            time.sleep(min(3, max(0, deadline - time.monotonic())))


def parse_junit(path):
    tree = ET.parse(path).getroot()
    cases = list(tree.iter('testcase'))
    require(cases, 'No executed native fixture tests')
    require(not any(list(case.iter(tag)) for case in cases for tag in ('failure', 'error', 'skipped')),
            'Native fixture failures/errors/skips cannot qualify')
    return {'executed_testcases': len(cases), 'failed': 0, 'skipped': 0,
            'case_names': [case.attrib.get('classname', '') + '.' + case.attrib['name'] for case in cases]}


def fault_suite(directory, root=ROOT):
    """Run only existing offline and owned-kernel fixtures; never production faults."""
    suites = [root / 'tests/test_persistent_supervisor_watchdog.py',
              root / 'tests/test_lean_refactor_router_task.py',
              root / 'tests/test_leanstral_provision_20261024.py',
              ACCELERATE / 'test/api/test_agent_supervisor_watchdog_guardian.py']
    require(not directory.exists(), 'Fault evidence directory must be new')
    directory.mkdir(parents=True, mode=0o700)
    files = [*suites, root / SELF, root / 'tests/test_lean_refactor_runtime_qualification.py',
             root / PROVISIONER, root / 'tools/manage_supervisor_watchdog.py',
             root / 'tools/run_lean_refactor_router_task.py',
             *sorted((ACCELERATE / 'ipfs_accelerate_py/agent_supervisor').rglob('*.py'))]
    before = {str(p): sha(p) for p in files}
    board = root / 'implementation_plan/lean_refactor_arena_20261024.todo.md'
    board_sha = sha(board)
    junit = directory / 'actual-tests.xml'
    argv = [str(PYTHON), '-B', '-m', 'pytest', '--noconftest', '-p', 'no:cacheprovider', '-c', '/dev/null',
            '--basetemp=' + str(directory / 'private-test-fixtures'),
            '--junitxml=' + str(junit), *map(str, suites), '-q']
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
           'PYTHONPATH': str(ACCELERATE), 'IPFS_TEST_PROOF_REUSE_MODE': 'off'}
    started = time.monotonic()
    result = subprocess.run(argv, cwd='/tmp', env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=180)
    (directory / 'stdout.log').write_text(result.stdout)
    (directory / 'stderr.log').write_text(result.stderr)
    require(result.returncode == 0, 'Native fault fixture suite failed; preserve actual logs')
    actual = parse_junit(junit)
    require(before == {str(p): sha(p) for p in files} and sha(board) == board_sha,
            'Sources/board changed during fault qualification')
    return {'schema': 'jevops.lean-refactor.runtime-fault-fixtures.v1', 'qualified': True,
            'observed_at': time.time(), 'source_sha256': before, 'board_sha256': board_sha,
            'command': argv, 'exit_code': result.returncode, 'wall_seconds': time.monotonic() - started,
            'actual_tests': actual, 'evidence': {name: {'path': str(directory / name),
                'sha256': sha(directory / name)} for name in ('actual-tests.xml', 'stdout.log', 'stderr.log')},
            'scope': 'offline fault inputs and actual owned kernel fixtures; no production fault injection',
            'production_processes_signaled': False, 'production_states_changed': False, **AUTH}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--qualify', action='store_true')
    modes.add_argument('--probe-resources', action='store_true')
    modes.add_argument('--fault-suite', action='store_true')
    parser.add_argument('--start-if-needed', action='store_true')
    parser.add_argument('--rehash-model', action='store_true')
    parser.add_argument('--inference-smoke', action='store_true', help='One actual bounded 16-token POST after native readiness')
    parser.add_argument('--wait-seconds', type=int, default=180)
    args = parser.parse_args(argv)
    out = ROOT / OUTPUT
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(out / 'qualification.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(lock_fd, 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.probe_resources:
                require(not args.start_if_needed and not args.rehash_model and not args.inference_smoke,
                        'Probe never launches, hashes model or generates')
                module, _ = provisioner()
                snapshot = resource_snapshot(module)
                reasons = resource_blockers(snapshot)
                result = {'schema': 'jevops.lean-refactor.resource-probe.v1', **snapshot,
                          'loading_resource_blockers': reasons, 'eligible_for_guarded_preload': not reasons,
                          'preload_memory_capacity_not_yet_qualified': True, **AUTH}
                name, code = 'resource-probe.json', 0
            elif args.fault_suite:
                require(not args.start_if_needed and not args.rehash_model and not args.inference_smoke,
                        'Fixtures never launch models or generate')
                directory = out / ('faults-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
                result, code, name = fault_suite(directory), 0, 'fault-suite.json'
            else:
                result, code = qualify(start_if_needed=args.start_if_needed,
                                       wait_seconds=args.wait_seconds, rehash_model=args.rehash_model,
                                       smoke=args.inference_smoke)
                name = 'qualification.json'
            save(out / name, result)
            print(json.dumps({'receipt': str(out / name), 'sha256': sha(out / name), 'exit_code': code,
                              'status': result.get('status'), 'ready': result.get('ready', False), **AUTH,
                              'generation_executed': result.get('generation_executed', False)}))
            return code
    except (OSError, RuntimeError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'qualified': False, 'error': str(exc), **AUTH}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
