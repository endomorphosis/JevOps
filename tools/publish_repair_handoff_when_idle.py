#!/usr/bin/env python3
"""Append a hash-bound operational handoff after dispatcher cleanup, without restarting.

The caller supplies immutable request and exact queue-hold lease files. This is
one bounded invocation, using the registered native repair marker. Persistent
worker/spawn state always defers publication, including a dead worker PID.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import xml.etree.ElementTree as ET

import manage_supervisor_watchdog as manager
import reload_supervisor_when_idle as idle

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'jevops.repair-handoff-publication.v1'
LEASE_SCHEMA = 'jevops.repair-queue-hold-lease.v1'
FLAGS = {'completion_authority': False, 'task_states_changed': False,
         'worker_signals_sent': False, 'provider_calls': 0, 'services_changed': False}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def in_time(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('Publication deadline elapsed')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def path_in(root, relative):
    require(type(relative) is str and relative and '\x00' not in relative
            and not Path(relative).is_absolute() and '..' not in Path(relative).parts,
            'Expected a repository-relative path without traversal')
    result = root / relative
    require(result != root, 'A file path is required')
    for part in [result, *result.parents]:
        if part == root.parent:
            break
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), 'Symlink component refused: ' + str(part))
        if part != result:
            require(stat.S_ISDIR(info.st_mode), 'Ordinary parent directory required')
    require(result.resolve().is_relative_to(root), 'Path escapes repository')
    return result


def read_owned(path, maximum=8 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_nlink == 1 and before.st_size <= maximum,
                'Expected bounded owned ordinary file: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        require(len(raw) <= maximum and identity(before) == identity(after)
                == identity(path.lstat()), 'File changed while reading: ' + str(path))
        return raw, before
    finally:
        os.close(fd)


def referenced(root, reference, maximum=8 * 1024 * 1024):
    require(type(reference) is dict and set(reference) == {'path', 'sha256'}
            and type(reference['sha256']) is str
            and re.fullmatch('[0-9a-f]{64}', reference['sha256']), 'Exact path/SHA256 reference required')
    path = path_in(root, reference['path'])
    raw, info = read_owned(path, maximum)
    require(digest(raw) == reference['sha256'], 'Input SHA256 differs: ' + reference['path'])
    return path, raw, info


def json_object(raw):
    value = json.loads(raw)
    require(type(value) is dict, 'Expected a JSON object')
    return value


def lease_input(root, reference, binding):
    _, raw, _ = referenced(root, reference, 65536)
    lease = json_object(raw)
    require(set(lease) == {'schema', 'path', 'device', 'inode', 'sha256', 'token', 'release_archive'}
            and lease['schema'] == LEASE_SCHEMA
            and type(lease['device']) is int and lease['device'] >= 0
            and type(lease['inode']) is int and lease['inode'] > 0
            and type(lease['sha256']) is str and re.fullmatch('[0-9a-f]{64}', lease['sha256'])
            and type(lease['token']) is str and re.fullmatch('[0-9a-f]{32}', lease['token']),
            'Malformed exact queue-hold lease')
    expected = binding['native_cfg'].state_dir / 'hold'
    require(path_in(root, lease['path']) == expected, 'Only the registered repair queue hold is allowed')
    archive = path_in(root, lease['release_archive'])
    require(archive != expected and not archive.exists(), 'Release archive must be new')
    require(owned_queue_hold(root, lease), 'Queue hold identity/body/token differs')
    return lease


def owned_queue_hold(root, lease):
    try:
        raw, info = read_owned(path_in(root, lease['path']), 65536)
        return ((info.st_dev, info.st_ino) == (lease['device'], lease['inode'])
                and digest(raw) == lease['sha256'] and json_object(raw).get('token') == lease['token'])
    except (OSError, ValueError, RuntimeError):
        return False


def archived_queue_hold(root, lease):
    try:
        raw, info = read_owned(path_in(root, lease['release_archive']), 65536)
        live = path_in(root, lease['path'])
        return ((info.st_dev, info.st_ino) == (lease['device'], lease['inode'])
                and digest(raw) == lease['sha256']
                and (not os.path.lexists(live) or
                     (live.lstat().st_dev, live.lstat().st_ino) != (lease['device'], lease['inode'])))
    except (OSError, ValueError, RuntimeError):
        return False


@contextmanager
def hold_commit():
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def release_queue_hold(root, lease):
    """Never unlink a changed/replaced marker; archive the exact leased inode."""
    if not owned_queue_hold(root, lease):
        return archived_queue_hold(root, lease)
    source, target = path_in(root, lease['path']), path_in(root, lease['release_archive'])
    require(not target.exists(), 'Release archive already exists')
    target.parent.mkdir(parents=True, exist_ok=True)
    require(owned_queue_hold(root, lease), 'Queue hold changed immediately before release')
    # Link without overwriting; verify the archived inode before unlinking the
    # live name. The native marker fences cooperative publishers/dispatchers.
    linked = released = False
    try:
        with hold_commit():
            os.link(source, target, follow_symlinks=False)
            linked = True
            raw = target.read_bytes()
            info = target.lstat()
            require(stat.S_ISREG(info.st_mode)
                    and (info.st_dev, info.st_ino) == (lease['device'], lease['inode'])
                    and digest(raw) == lease['sha256'], 'Release archive identity differs')
            live = source.lstat()
            require((live.st_dev, live.st_ino) == (lease['device'], lease['inode']),
                    'Queue hold replaced before release')
            source.unlink()
            released = True
        return True
    finally:
        # An interrupted link-before-unlink attempt must not leave a second
        # link that prevents a later exact-owned cleanup. Remove only our link.
        if linked and not released:
            try:
                info = target.lstat()
                live = source.lstat()
                if ((info.st_dev, info.st_ino) == (lease['device'], lease['inode'])
                        and (live.st_dev, live.st_ino) == (lease['device'], lease['inode'])):
                    target.unlink()
            except FileNotFoundError:
                pass


def request_input(root, reference, *, external_preserve_root, deadline):
    def checked(reference, maximum=8 * 1024 * 1024, directory=root):
        in_time(deadline)
        result = referenced(directory, reference, maximum)
        in_time(deadline)
        return result
    _, raw, _ = checked(reference, 262144)
    value = json_object(raw)
    require(set(value) == {'schema', 'handoff', 'append', 'verify', 'preserve', 'receipt'}
            and value['schema'] == SCHEMA and type(value['verify']) is list
            and 1 <= len(value['verify']) <= 64, 'Malformed closed publication request')
    _, handoff, _ = checked(value['handoff'])
    json_object(handoff)
    _, block, _ = checked(value['append'], 65536)
    text = block.decode('utf-8')
    require(text.strip() and '\x00' not in text and value['handoff']['path'] in text
            and value['handoff']['sha256'] in text, 'Append must bind the exact handoff path and SHA256')
    kinds = set()
    total = 0
    for row in value['verify']:
        require(type(row) is dict and set(row) == {'kind', 'path', 'sha256'}
                and row['kind'] in {'source', 'test_evidence'}, 'Typed source/test reference required')
        _, data, _ = checked({key: row[key] for key in ['path', 'sha256']})
        kinds.add(row['kind']); total += len(data)
        require(total <= 32 * 1024 * 1024, 'Verification closure exceeds bound')
        if row['kind'] == 'test_evidence':
            tree = ET.fromstring(data)
            cases = list(tree.iter('testcase'))
            require(cases and not any(list(tree.iter(name)) for name in ['failure', 'error', 'skipped']),
                    'Test evidence must contain actual passing cases without failures/errors/skips')
            for element in tree.iter():
                for name in ['failures', 'errors', 'skipped']:
                    if name in element.attrib:
                        counter = element.attrib[name]
                        require(re.fullmatch('[0-9]+', counter) and int(counter) == 0,
                                'JUnit metadata reports failure/error/skip or an invalid counter')
    require(kinds == {'source', 'test_evidence'}, 'Both candidate sources and passing test evidence required')
    _, frozen, _ = checked(value['preserve'])
    frozen = json_object(frozen)
    require(set(frozen) == {'schema', 'files'}
            and frozen['schema'] == 'jevops.repair-publication-preservation.v1'
            and type(frozen['files']) is list and 1 <= len(frozen['files']) <= 1024,
            'Exact caller-supplied source/budget/board preservation baseline required')
    for row in frozen['files']:
        if type(row) is dict and type(row.get('path')) is str and Path(row['path']).is_absolute():
            require(set(row) == {'path', 'sha256'} and '..' not in Path(row['path']).parts,
                    'Exact external preservation reference required')
            absolute = Path(row['path'])
            require(absolute.is_relative_to(external_preserve_root),
                    'External preservation escapes registered accelerator source')
            # Absolute paths are allowed ONLY for read-only preservation pins
            # within the scope-bound accelerator source, never any write/input.
            checked({'path': str(absolute.relative_to(external_preserve_root)),
                     'sha256': row['sha256']}, directory=external_preserve_root)
        else:
            checked(row)
    receipt = path_in(root, value['receipt'])
    require(not receipt.exists(), 'Publication receipt must be new')
    return value, text, receipt


def observation(binding, lease):
    cfg, native = binding['native_cfg'], binding['native']
    state = idle.read_json(cfg.state_dir / 'state.json')
    # Persisted state owns descendant cleanup. Never use a dead PID to bypass it.
    if 'active_worker' in state:
        return {'idle': False, 'reason': 'persisted_active_worker'}
    if 'spawn_intent' in state:
        return {'idle': False, 'reason': 'persisted_spawn_intent'}
    holds = set(native._configured_holds(cfg, binding['manifest']))
    for lane in binding['manifest']['lanes']:
        directory = idle.local(binding['root'], lane['state_dir'])
        holds.update(directory / name for name in ['hold', 'HOLD', 'operator.hold', 'OPERATOR_STOP', 'watchdog.disabled'])
    own = path_in(binding['root'], lease['path'])
    others = sorted(str(p) for p in holds if p != own and os.path.lexists(p))
    return {'idle': not others, 'reason': 'other_hold' if others else 'dispatcher_cleanup_complete',
            'hold_paths': others}


def publish_when_idle(root, request_ref, lease_ref, *, timeout=1200, once=False):
    lease = None
    result = {'schema': SCHEMA, 'published': False, **FLAGS}
    code = 1
    prompt_intent = None
    try:
        require(type(timeout) is int and 1 <= timeout <= 1800, 'Deadline must be 1..1800 seconds')
        deadline = time.monotonic() + timeout
        root = Path(root).resolve(strict=True)
        binding = idle.scope(root)
        helper_inputs = {Path(module.__file__).resolve(): digest(Path(module.__file__).read_bytes())
                         for module in [idle, manager, binding['native']]}
        lease = lease_input(root, lease_ref, binding)
        external_preserve_root = Path(binding['supervisor']['accelerator_source']).resolve(strict=True)
        request, block, receipt = request_input(root, request_ref,
                                               external_preserve_root=external_preserve_root, deadline=deadline)
        native = binding['native']
        while time.monotonic() < deadline:
            idle.unchanged_scope(binding)
            require(all(digest(read_owned(path)[0]) == expected
                        for path, expected in helper_inputs.items()), 'Canonical publisher dependencies changed')
            require(owned_queue_hold(root, lease), 'Own queue hold changed while waiting')
            result['last_observation'] = observation(binding, lease)
            if result['last_observation']['idle']:
                try:
                    with native.repair_lock(binding['native_cfg'].repair_lock_path):
                        fence = idle.owned_presence(binding)
                        result['last_observation'] = observation(binding, lease)
                        if result['last_observation']['idle']:
                            idle.unchanged_scope(binding)
                            request, block, receipt = request_input(root, request_ref,
                                external_preserve_root=external_preserve_root, deadline=deadline)
                            require(all(digest(read_owned(path)[0]) == expected
                                        for path, expected in helper_inputs.items()),
                                    'Canonical publisher dependencies changed before publication')
                            require(time.monotonic() < deadline and owned_queue_hold(root, lease)
                                    and idle.owned_presence(binding) == fence, 'Publication fence/deadline differs')
                            prompt = path_in(root, binding['cfg']['repair_prompt'])
                            before, _ = read_owned(prompt, 2 * 1024 * 1024)
                            before_text = before.decode('utf-8')
                            suffix = '\n' + block.rstrip('\n') + '\n'
                            require(suffix not in before_text, 'Exact append already present')
                            after = before_text + suffix
                            require(len(after.encode()) <= 2 * 1024 * 1024, 'Prompt exceeds publication bound')
                            history = binding['manifest_path'].parent / 'execution-v2/history'
                            archive = path_in(root, str((history / (prompt.name + '.' + digest(before))).relative_to(root)))
                            if archive.exists():
                                require(read_owned(archive, 2 * 1024 * 1024)[0] == before, 'Historical before-image differs')
                            else:
                                manager.atomic(archive, before_text)
                            require(read_owned(prompt, 2 * 1024 * 1024)[0] == before
                                    and idle.owned_presence(binding) == fence
                                    and owned_queue_hold(root, lease), 'Prompt/lease changed before atomic append')
                            in_time(deadline)
                            prompt_intent = {'path': prompt, 'before': digest(before), 'after': digest(after.encode())}
                            manager.atomic(prompt, after)
                            result.update(published=True, before_sha256=digest(before), after_sha256=digest(after.encode()),
                                          handoff=request['handoff'], append=request['append'], verify=request['verify'],
                                          prompt=str(prompt.relative_to(root)), history=str(archive.relative_to(root)),
                                          published_at=time.time())
                            # Durable receipt exists before queue release. A failed write
                            # leaves a visible published:true partial failure, never success.
                            manager.save(receipt, result)
                            require(idle.owned_presence(binding) == fence, 'Publication marker changed before release')
                            result['queue_hold_released'] = release_queue_hold(root, lease)
                            require(result['queue_hold_released'], 'Exact queue hold could not be released')
                            manager.save(receipt, result)
                            code = 0
                            break
                except native.AlreadyRunning:
                    result['last_observation'] = {'idle': False, 'reason': 'native_repair_presence_held'}
            if once:
                break
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        else:
            result['reason'] = 'publication_deadline'
        if not result['published']:
            result.setdefault('reason', 'deferred_until_dispatcher_cleanup')
            code = 75
    except BaseException as error:
        if prompt_intent is not None:
            try:
                current = digest(read_owned(prompt_intent['path'], 2 * 1024 * 1024)[0])
                result.update(before_sha256=prompt_intent['before'], after_sha256=prompt_intent['after'],
                              published=True if current == prompt_intent['after'] else
                                        False if current == prompt_intent['before'] else None,
                              observed_prompt_sha256=current)
            except (OSError, ValueError, RuntimeError):
                result.update(published=None, publication_state_uncertain=True)
        result.update(error_type=type(error).__name__, error=str(error))
        if not isinstance(error, Exception):
            # Preserve the original control exception and actual partial state.
            error.publication_result = result
            raise
        code = 75 if isinstance(error, TimeoutError) else 1
        if isinstance(error, TimeoutError):
            result['reason'] = 'publication_deadline'
    finally:
        if lease is not None and not result.get('queue_hold_released'):
            try:
                result['queue_hold_released'] = release_queue_hold(root, lease)
            except BaseException as error:
                result['queue_hold_release_error'] = type(error).__name__ + ': ' + str(error)
    return result, code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--request', required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--lease', required=True)
    parser.add_argument('--lease-sha256', required=True)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args(argv)
    previous = {}
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt('Publication interrupted')
    try:
        for sig in [signal.SIGINT, signal.SIGTERM]:
            previous[sig] = signal.signal(sig, interrupt)
        try:
            value, code = publish_when_idle(args.repo_root,
                {'path': args.request, 'sha256': args.request_sha256},
                {'path': args.lease, 'sha256': args.lease_sha256}, timeout=args.timeout)
        except BaseException as error:
            value = getattr(error, 'publication_result', {'schema': SCHEMA, 'published': False,
                'error_type': type(error).__name__, 'error': str(error), **FLAGS})
            print(json.dumps(value, sort_keys=True), file=sys.stderr)
            raise
        print(json.dumps(value, sort_keys=True))
        return code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
