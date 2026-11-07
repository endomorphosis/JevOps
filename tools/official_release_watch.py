#!/usr/bin/env python3
"""Bounded official metadata observation. Never execute upstream Python or tasks.

collect writes immutable evidence and its transport cache only. poll adds an
independent validation, a semantic status, and a local outbox event. It never
invokes a publisher, native process, model, service, or taskboard operation.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import sys
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCHEMA = 'jevops.official-release-observation.v1'
REPO = 'delta-lab-ai/lean-refactor-arena'
API = 'https://huggingface.co/api/spaces/' + REPO
NOT_BEFORE = 1793491200
AUTH = dict(model_calls=0, native_processes=0, training=False,
            proof_authority=False, completion_authority=False,
            scientific_acceptance_authority=False, full_campaign_complete=False,
            task_states_changed=False)
BOUNDS = dict(api=256*1024, head=256*1024, tree=512*1024,
              app=256*1024, loader=256*1024, cohort=4*1024*1024)
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
_FENCES = ContextVar('official_release_owned_directory_fences', default=())


class ReviewRequired(ValueError):
    pass


class TransportUnavailable(Exception):
    def __init__(self, code, retry_after=300):
        super().__init__(code)
        self.code = code
        self.retry_after = max(30, min(86400, int(retry_after)))


class AlreadyPolling(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise ReviewRequired(message)


def control(error):
    return not isinstance(error, Exception) or isinstance(error, InterruptedError)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def json_value(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ReviewRequired('NONFINITE_JSON')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ReviewRequired('MALFORMED_JSON') from error


def ordinary(path, maximum=8*1024*1024):
    check_fences()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_nlink == 1 and not before.st_mode & 0o077
                and 0 <= before.st_size <= maximum,
                'UNSAFE_OR_OVERSIZE_LOCAL_FILE')
        blocks, count = [], 0
        while block := os.read(fd, min(65536, maximum+1-count)):
            count += len(block)
            require(count <= maximum, 'LOCAL_FILE_GREW')
            blocks.append(block)
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
                    info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(count == before.st_size and identity(before) == identity(os.fstat(fd))
                == identity(Path(path).lstat()), 'LOCAL_FILE_CHANGED')
        check_fences()
        return b''.join(blocks)
    finally:
        os.close(fd)


def scope(repo_root, state_dir):
    root = Path(repo_root).absolute()
    require(root == root.resolve(strict=True) and root.is_dir()
            and root.stat().st_uid == os.getuid(), 'OWNED_EXACT_REPOSITORY_REQUIRED')
    value = Path(state_dir)
    require('..' not in value.parts, 'STATE_TRAVERSAL')
    state = value if value.is_absolute() else root/value
    require(state != root and state.is_relative_to(root), 'STATE_OUTSIDE_REPOSITORY')
    relative = state.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if not os.path.lexists(current):
            current.mkdir(mode=0o700)
            sync_directory(current.parent)
        info = current.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and not current.is_symlink(), 'UNSAFE_STATE_ANCESTOR')
    require(not state.stat().st_mode & 0o077, 'PRIVATE_STATE_DIRECTORY_REQUIRED')
    for name in ['evidence', 'history', 'outbox', 'outbox/events']:
        path = state/name
        if not os.path.lexists(path):
            path.mkdir(mode=0o700)
            sync_directory(path.parent)
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and not info.st_mode & 0o077, 'PRIVATE_OWNED_STATE_CHILD_REQUIRED')
    return root, state


def check_fences():
    for path, descriptor, expected in _FENCES.get():
        def identity(info):
            return info.st_dev, info.st_ino, info.st_uid, info.st_mode
        require(identity(path.lstat()) == expected == identity(os.fstat(descriptor)),
                'STATE_DIRECTORY_IDENTITY_CHANGED')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def directory_fence(root, state):
    owned = []
    token = None
    pending = None
    try:
        paths = [root] + list(reversed([p for p in state.parents if p != root and p.is_relative_to(root)])) + [state]
        paths += [state/name for name in ['evidence', 'history', 'outbox', 'outbox/events']]
        for path in paths:
            descriptor = os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(descriptor)
            expected = info.st_dev, info.st_ino, info.st_uid, info.st_mode
            owned.append((path, descriptor, expected))
            require(info.st_uid == os.getuid(), 'FOREIGN_STATE_ANCESTOR')
        token = _FENCES.set(_FENCES.get()+tuple(owned))
        check_fences()
        yield
        check_fences()
    except BaseException as error:
        pending = error
        raise
    finally:
        if token is not None:
            _FENCES.reset(token)
        closing = None
        for _, descriptor, _ in reversed(owned):
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                if closing is None or (not control(closing) and control(cleanup)):
                    closing = cleanup
        if closing is not None and (pending is None or (not control(pending) and control(closing))):
            raise closing


def new_bytes(path, raw):
    """Atomically add immutable content; retain an already committed target."""
    check_fences()
    if os.path.lexists(path):
        require(ordinary(path, max(8*1024*1024, len(raw))) == raw, 'IMMUTABLE_EVIDENCE_DIFFERS')
        return
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    pending = None
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            require(ordinary(path, max(8*1024*1024, len(raw))) == raw, 'IMMUTABLE_EVIDENCE_RACE')
        check_fences()
    except BaseException as error:
        pending = error
        raise
    finally:
        try:
            if os.path.lexists(temporary):
                actual = temporary.lstat()
                if (actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino):
                    temporary.unlink()
        except BaseException as cleanup:
            if pending is None or (not control(pending) and control(cleanup)):
                raise
    sync_directory(path.parent)


def atomic_json(state, path, value):
    check_fences()
    raw = canonical(value)
    if os.path.lexists(path):
        before = ordinary(path)
        new_bytes(state/'history'/(path.name+'.'+digest(before)+'.json'), before)
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    pending = None
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        check_fences()
        sync_directory(path.parent)
    except BaseException as error:
        pending = error
        raise
    finally:
        try:
            if os.path.lexists(temporary):
                actual = temporary.lstat()
                if (actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino):
                    temporary.unlink()
        except BaseException as cleanup:
            if pending is None or (not control(pending) and control(cleanup)):
                raise


def file_name(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_./-]+', value)
            and not value.startswith('/') and all(part not in ('', '.', '..') for part in value.split('/'))
            and str(PurePosixPath(value)) == value, 'UNSUPPORTED_REPOSITORY_FILE_PATH')
    return value


def checked_url(url):
    require(type(url) is str and len(url) <= 2048, 'UNSAFE_URL')
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise ReviewRequired('UNSAFE_URL_PORT') from error
    require(parsed.scheme == 'https' and parsed.hostname == 'huggingface.co'
            and parsed.netloc in {'huggingface.co', 'huggingface.co:443'}
            and port in (None, 443) and not parsed.username and not parsed.password
            and not parsed.fragment, 'UNSAFE_URL_ORIGIN')
    base = '/api/spaces/'+REPO
    if parsed.path == base:
        require(not parsed.query, 'UNSAFE_API_QUERY')
    elif parsed.path.startswith(base+'/tree/'):
        require(HEX40.fullmatch(parsed.path[len(base+'/tree/'):])
                and parsed.query == 'recursive=true', 'UNSAFE_TREE_URL')
    else:
        prefix = '/spaces/'+REPO+'/raw/'
        require(parsed.path.startswith(prefix) and not parsed.query, 'UNSAFE_RAW_URL')
        revision, separator, name = parsed.path[len(prefix):].partition('/')
        require(separator and HEX40.fullmatch(revision), 'UNSAFE_RAW_REVISION')
        file_name(name)
    return url


@dataclass(frozen=True)
class HTTPResult:
    status: int
    headers: dict
    body: bytes
    url: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject BEFORE urllib constructs or sends a redirected request.
        raise ReviewRequired('REDIRECT_REQUIRES_REVIEW')


def get_https(url, *, timeout, max_bytes, deadline):
    checked_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, method='GET', headers={
        'User-Agent': 'JevOps-official-release-observer/1', 'Accept-Encoding': 'identity'})
    response = None
    pending = None
    try:
        try:
            response = opener.open(request, timeout=min(8, timeout, max(.001, deadline-time.monotonic())))
        except urllib.error.HTTPError as error:
            response = error
        require(response.geturl() == url, 'UNEXPECTED_FINAL_URL')
        encoding = response.headers.get('Content-Encoding', 'identity').lower()
        require(encoding in ('identity', ''), 'COMPRESSED_TRANSPORT_REQUIRES_REVIEW')
        length = response.headers.get('Content-Length')
        if length is not None:
            require(length.isdecimal() and int(length) <= max_bytes, 'HTTP_BODY_TOO_LARGE')
        blocks, count = [], 0
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TransportUnavailable('POLL_DEADLINE')
            # A response may drip bytes. Bound every read by the remaining poll.
            sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock is not None:
                sock.settimeout(min(8, remaining))
            require(callable(getattr(response, 'read1', None)), 'UNSUPPORTED_BOUNDED_HTTP_READER')
            block = response.read1(min(65536, max_bytes+1-count))
            if time.monotonic() >= deadline:
                raise TransportUnavailable('POLL_DEADLINE')
            if not block:
                break
            count += len(block)
            require(count <= max_bytes, 'HTTP_BODY_TOO_LARGE')
            blocks.append(block)
        return HTTPResult(response.code, dict(response.headers.items()), b''.join(blocks), response.geturl())
    except BaseException as error:
        pending = error
        if isinstance(error, urllib.error.URLError) and isinstance(error.reason, InterruptedError):
            pending = error.reason
            raise pending
        if isinstance(error, (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError)):
            pending = TransportUnavailable('NETWORK_UNAVAILABLE')
            raise pending from error
        raise
    finally:
        if response is not None:
            try:
                response.close()
            except BaseException as cleanup:
                if pending is None or (not control(pending) and control(cleanup)):
                    raise


def tree_files(raw):
    rows = json_value(raw)
    require(type(rows) is list and 1 <= len(rows) <= 1000, 'UNSUPPORTED_TREE_SCHEMA')
    found = {}
    for row in rows:
        require(type(row) is dict and row.get('type') in ('file', 'directory'), 'UNSUPPORTED_TREE_MEMBER')
        name = file_name(row.get('path'))
        require(name not in found and type(row.get('oid')) is str and HEX40.fullmatch(row['oid'])
                and type(row.get('size')) is int and row['size'] >= 0, 'AMBIGUOUS_TREE_MEMBER')
        found[name] = row
    return found


def metadata(raw):
    value = json_value(raw)
    require(type(value) is dict and value.get('id') == REPO
            and type(value.get('sha')) is str and HEX40.fullmatch(value['sha'])
            and value.get('private', False) is False and value.get('disabled', False) is False,
            'UNSUPPORTED_OFFICIAL_API')
    return value


def selection(app_raw, loader_raw):
    """Only extract static fetch selection; independent validator checks meaning."""
    try:
        app = ast.parse(app_raw)
        loader = ast.parse(loader_raw)
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ReviewRequired('UNSUPPORTED_SOURCE_AST') from error
    def assignments(tree, name):
        return [node.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    counts = assignments(app, 'FULL_BENCH_SIZE')
    dates = assignments(app, 'FULL_BENCH_RELEASE')
    paths = assignments(app, 'BENCHMARK_JSONL_PATH')
    data = assignments(loader, '_DATA_PATH')
    require(len(counts) == len(dates) == len(paths) == len(data) == 1, 'AMBIGUOUS_SOURCE_ASSIGNMENTS')
    require(isinstance(counts[0], ast.Constant) and type(counts[0].value) is int
            and 1 <= counts[0].value <= 128, 'UNSUPPORTED_DECLARED_COUNT')
    require(isinstance(dates[0], ast.Constant) and type(dates[0].value) is str, 'UNSUPPORTED_RELEASE_DATE')
    try:
        release = datetime.strptime(dates[0].value, '%B %d, %Y').replace(tzinfo=timezone.utc).timestamp()
    except ValueError as error:
        raise ReviewRequired('UNSUPPORTED_RELEASE_DATE') from error
    require(isinstance(paths[0], ast.Constant) and type(paths[0].value) is str
            and paths[0].value.startswith('/home/user/app/'), 'UNSUPPORTED_APP_SELECTION')
    selected = file_name(paths[0].value[len('/home/user/app/'):])
    template = ast.parse("Path(__file__).resolve().parent / 'placeholder'").body[0].value
    candidate = data[0]
    require(isinstance(candidate, ast.BinOp) and isinstance(candidate.op, ast.Div)
            and ast.dump(candidate.left) == ast.dump(template.left)
            and isinstance(candidate.right, ast.Constant) and type(candidate.right.value) is str,
            'UNSUPPORTED_LOADER_SELECTION')
    require(file_name(candidate.right.value) == selected and selected.endswith('.jsonl'), 'SELECTION_DISAGREEMENT')
    return counts[0].value, int(release), selected


def evidence_row(root, state, label, url, raw):
    path = state/'evidence'/(digest(raw)+'.raw')
    new_bytes(path, raw)
    return dict(label=label, url=url, path=str(path.relative_to(root)), sha256=digest(raw), bytes=len(raw))


def check_cached(root, state, row):
    require(type(row) is dict and set(row) == {'label', 'url', 'path', 'sha256', 'bytes'}
            and type(row['label']) is str and row['label'] in BOUNDS
            and type(row['sha256']) is str and HEX64.fullmatch(row['sha256'])
            and type(row['bytes']) is int and 0 <= row['bytes'] <= BOUNDS[row['label']], 'INVALID_CACHE_REFERENCE')
    checked_url(row['url'])
    relative = Path(row['path'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'CACHE_PATH_ESCAPE')
    path = root/relative
    require(path.parent == state/'evidence' and path == path.resolve(), 'CACHE_PATH_ESCAPE')
    raw = ordinary(path, BOUNDS[row['label']])
    require(len(raw) == row['bytes'] and digest(raw) == row['sha256'], 'CACHED_EVIDENCE_CHANGED')
    return raw


def valid_cache(root, state, cache):
    require(type(cache) is dict and set(cache) == {'schema', 'revision', 'gate_due', 'fields', 'evidence'}
            and cache['schema'] == 'jevops.official-release-cache.v1'
            and type(cache['revision']) is str and HEX40.fullmatch(cache['revision'])
            and type(cache['gate_due']) is bool and type(cache['fields']) is dict
            and type(cache['evidence']) is list, 'UNSUPPORTED_CACHE_SCHEMA')
    fields = cache['fields']
    expected = {'status', 'declared_problem_count', 'selected_file', 'declared_not_before'}
    require(set(fields) == expected | ({'candidate_payload_present'} if cache['gate_due'] else set())
            and fields['status'] == ('WAITING_RELEASE' if cache['gate_due'] else 'WAITING_DATE')
            and type(fields['declared_problem_count']) is int and 1 <= fields['declared_problem_count'] <= 128
            and fields['declared_not_before'] == NOT_BEFORE
            and (not cache['gate_due'] or fields['candidate_payload_present'] is True), 'INVALID_CACHE_FIELDS')
    file_name(fields['selected_file'])
    labels = [row.get('label') for row in cache['evidence'] if type(row) is dict]
    expected_labels = {'tree', 'app', 'loader', 'head'} | ({'cohort'} if cache['gate_due'] else set())
    require(len(labels) == len(cache['evidence']) == len(expected_labels) and set(labels) == expected_labels,
            'INVALID_CACHE_LABELS')
    bodies = {row['label']: check_cached(root, state, row) for row in cache['evidence']}
    require(metadata(bodies['head'])['sha'] == cache['revision'], 'CACHE_HEAD_DIFFERS')
    files = tree_files(bodies['tree'])
    require(selection(bodies['app'], bodies['loader']) ==
            (fields['declared_problem_count'], fields['declared_not_before'], fields['selected_file']),
            'CACHE_SELECTION_DIFFERS')
    for row in cache['evidence']:
        label = row['label']
        if label == 'head':
            require(row['url'] == API, 'CACHE_HEAD_URL_DIFFERS')
        elif label == 'tree':
            require(row['url'] == API+'/tree/'+cache['revision']+'?recursive=true', 'CACHE_TREE_URL_DIFFERS')
        else:
            name = {'app': 'app.py', 'loader': 'benchmark.py', 'cohort': fields['selected_file']}[label]
            raw = bodies[label]
            entry = files.get(name)
            require(row['url'] == 'https://huggingface.co/spaces/'+REPO+'/raw/'+cache['revision']+'/'+name
                    and entry is not None and entry['type'] == 'file' and entry['size'] == len(raw)
                    and entry['oid'] == hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                    'CACHE_GIT_IDENTITY_DIFFERS')


def retry_seconds(value, now):
    if value is None:
        return 300
    value = str(value).strip()
    if value.isdecimal():
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        require(date.tzinfo is not None, 'UNSUPPORTED_RETRY_AFTER')
        return max(0, math.ceil(date.timestamp()-now))
    except (TypeError, ValueError, OverflowError) as error:
        raise ReviewRequired('UNSUPPORTED_RETRY_AFTER') from error


def cached_backoff(state, now):
    path = state/'transport-backoff.json'
    if not path.exists():
        return None
    raw = ordinary(path, 512*1024)
    try:
        value = json_value(raw)
        require(type(value) is dict and set(value) == {'schema', 'retry_at', 'disabled', 'report'}
                and value['schema'] == 'jevops.official-release-transport-backoff.v1'
                and type(value['disabled']) is bool
                and (value['retry_at'] is None or type(value['retry_at']) in (int, float)
                     and math.isfinite(value['retry_at'])), 'INVALID_TRANSPORT_BACKOFF')
        if not value['disabled'] and value['retry_at'] is not None and value['retry_at'] <= now:
            return None
        report = value['report']
        require(type(report) is dict and report.get('schema') == SCHEMA
                and report.get('status') in ('TRANSPORT_UNAVAILABLE', 'REQUIRES_REVIEW')
                and all(type(report.get(key)) is type(expected) and report[key] == expected
                        for key, expected in AUTH.items()), 'INVALID_BACKOFF_OBSERVATION')
        # Retain the actual transport observation time/evidence; this is not a fresh HTTP head.
        return dict(report, requests_made=0, backoff_cached=True, poll_observed_at=now)
    except (ReviewRequired, KeyError, TypeError, ValueError, RecursionError) as error:
        new_bytes(state/'history'/('invalid-backoff.'+digest(raw)+'.json'), raw)
        return dict(schema=SCHEMA, observed_at=now, not_before=NOT_BEFORE, status='REQUIRES_REVIEW',
            revision=None, declared_problem_count=None, selected_file=None, legacy_contract_problem_count=50,
            evidence=[], reasons=['INVALID_STORED_SERVER_BACKOFF_REQUIRES_REVIEW'],
            cache_diagnostic=str(error), automatic_retry_disabled=True, transport_retry_at=None,
            requests_made=0, backoff_cached=True, **AUTH)


def _collect(repo_root, state_dir, *, now=None, getter=None):
    root, state = scope(repo_root, state_dir)
    stamp = time.time() if now is None else now
    require(type(stamp) in (int, float) and math.isfinite(stamp), 'INVALID_OBSERVATION_CLOCK')
    paused = cached_backoff(state, stamp)
    if paused is not None:
        return paused
    started = time.monotonic()
    deadline = started+45
    get = get_https if getter is None else getter
    report = dict(schema=SCHEMA, observed_at=stamp, not_before=NOT_BEFORE,
                  status='WAITING_DATE' if stamp < NOT_BEFORE else 'WAITING_RELEASE',
                  revision=None, declared_problem_count=None, selected_file=None,
                  legacy_contract_problem_count=50, evidence=[], reasons=[],
                  requests_made=0, cache_reused=False, **AUTH)
    def fetch(label, url):
        checked_url(url)
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TransportUnavailable('POLL_DEADLINE')
        if report['requests_made'] >= 8:
            raise TransportUnavailable('POLL_REQUEST_BOUND')
        report['requests_made'] += 1
        try:
            response = get(url, timeout=min(8, remaining), max_bytes=BOUNDS[label], deadline=deadline)
        except InterruptedError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if isinstance(error, urllib.error.URLError) and isinstance(error.reason, InterruptedError):
                raise error.reason
            raise TransportUnavailable('NETWORK_UNAVAILABLE') from error
        require(isinstance(response, HTTPResult) and response.url == url
                and type(response.status) is int and type(response.body) is bytes,
                'UNSUPPORTED_GETTER_RESPONSE')
        checked_url(response.url)
        if 300 <= response.status < 400:
            raise ReviewRequired('REDIRECT_REQUIRES_REVIEW')
        if response.status != 200:
            value = next((v for key, v in response.headers.items() if key.lower() == 'retry-after'), None)
            try:
                # Retry-After starts when the response is received, not when
                # this poll began. A slow response must never shorten the
                # server's requested wait. Monotonic elapsed time also keeps
                # an injected observation clock deterministic for fixtures.
                retry = retry_seconds(value, stamp+max(0, time.monotonic()-started))
            except ReviewRequired:
                report['automatic_retry_disabled'] = True
                report['transport_retry_at'] = None
                raise
            if retry > 86400:
                report.update(automatic_retry_disabled=True, transport_retry_at=None,
                              requested_retry_after_seconds=retry)
                raise ReviewRequired('SERVER_RETRY_AFTER_EXCEEDS_SUPPORTED_BOUND')
            raise TransportUnavailable('HTTP_'+str(response.status), retry)
        require(len(response.body) <= BOUNDS[label], 'HTTP_BODY_TOO_LARGE')
        if label == 'tree':
            require(not any(key.lower() == 'link' for key in response.headers), 'TREE_PAGINATION_REQUIRES_REVIEW')
        report['evidence'].append(evidence_row(root, state, label, url, response.body))
        return response.body
    try:
        api_raw = fetch('api', API)
        api = metadata(api_raw)
        revision = report['revision'] = api['sha']
        cachepath = state/'collection-cache.json'
        if cachepath.exists():
            cache_raw = ordinary(cachepath, 512*1024)
            try:
                cache = json_value(cache_raw)
                valid_cache(root, state, cache)
            except (ReviewRequired, KeyError, TypeError, ValueError, RecursionError) as error:
                new_bytes(state/'history'/('invalid-cache.'+digest(cache_raw)+'.json'), cache_raw)
                report['cache_diagnostic'] = str(error)
                cache = None
            if cache is not None and cache['revision'] == revision and cache['gate_due'] == (stamp >= NOT_BEFORE):
                report.update(cache['fields'])
                report['evidence'] += cache['evidence']
                report['cache_reused'] = True
                return report
        tree_url = API+'/tree/'+revision+'?recursive=true'
        files = tree_files(fetch('tree', tree_url))
        def source(label, name):
            row = files.get(name)
            require(row is not None and row['type'] == 'file' and row['size'] <= BOUNDS[label]
                    and not row.get('lfs'), 'UNSUPPORTED_SELECTED_TREE_FILE')
            raw = fetch(label, 'https://huggingface.co/spaces/'+REPO+'/raw/'+revision+'/'+name)
            blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            require(len(raw) == row['size'] and blob == row['oid'], 'GIT_BLOB_IDENTITY_DIFFERS')
            return raw
        app = source('app', 'app.py')
        loader = source('loader', 'benchmark.py')
        count, release, selected = selection(app, loader)
        report.update(declared_problem_count=count, declared_not_before=release, selected_file=selected)
        require(release == NOT_BEFORE, 'DECLARED_RELEASE_GATE_CHANGED_REVIEW_REQUIRED')
        if stamp >= NOT_BEFORE:
            source('cohort', selected)
            report['candidate_payload_present'] = True
        head = metadata(fetch('head', API))
        if head['sha'] != revision:
            raise TransportUnavailable('HEAD_CHANGED_DURING_POLL', 30)
        fields = {key: report[key] for key in ['status', 'declared_problem_count', 'selected_file', 'declared_not_before']}
        if report.get('candidate_payload_present'):
            fields['candidate_payload_present'] = True
        atomic_json(state, cachepath, dict(schema='jevops.official-release-cache.v1', revision=revision,
                    gate_due=stamp >= NOT_BEFORE, fields=fields,
                    evidence=[row for row in report['evidence'] if row['label'] != 'api']))
    except ReviewRequired as error:
        report.update(status='REQUIRES_REVIEW', reasons=[str(error)], retry_after_seconds=3600)
    except TransportUnavailable as error:
        report.update(status='TRANSPORT_UNAVAILABLE', reasons=[error.code], retry_after_seconds=error.retry_after,
                      transport_retry_at=stamp+max(0, time.monotonic()-started)+error.retry_after)
    if report['status'] == 'TRANSPORT_UNAVAILABLE' or report.get('automatic_retry_disabled'):
        atomic_json(state, state/'transport-backoff.json', dict(schema='jevops.official-release-transport-backoff.v1',
            retry_at=report.get('transport_retry_at'), disabled=report.get('automatic_retry_disabled', False), report=report))
    return report


def collect(repo_root, state_dir, *, now=None, getter=None):
    root, state = scope(repo_root, state_dir)
    with directory_fence(root, state):
        result = _collect(root, state, now=now, getter=getter)
        backoff = state/'transport-backoff.json'
        if result['status'] not in ('TRANSPORT_UNAVAILABLE', 'REQUIRES_REVIEW') and backoff.exists():
            atomic_json(state, backoff, dict(schema='jevops.official-release-transport-backoff.v1',
                                          retry_at=0, disabled=False, report=None))
        return result


def semantic_fingerprint(observation, validation):
    semantic = validation.get('semantic', {})
    declared = validation.get('declared_problem_count')
    if declared is None:
        declared = observation.get('declared_problem_count')
    payload = dict(status=observation['status'], not_before=observation['not_before'],
        declared_not_before=observation.get('declared_not_before'),
        declared_problem_count=declared,
        observed_problem_count=validation.get('observed_problem_count'), pin_count=validation.get('pin_count'),
        selected_file=observation.get('selected_file'), legacy_contract_problem_count=50,
        validation_status=validation.get('status'), reasons=sorted(set(observation.get('reasons', [])+validation.get('reasons', []))),
        cohort_sha256=next((row['sha256'] for row in observation['evidence'] if row['label'] == 'cohort'), None),
        semantic={key: semantic[key] for key in ['migration_state', 'legacy_count_mismatch', 'candidate_ready',
                  'runtime_coherent', 'schema_supported', 'release_gate_matches'] if key in semantic})
    if observation['status'] == 'REQUIRES_REVIEW':
        payload['unsupported_source_context'] = {row['label']: row['sha256'] for row in observation['evidence']
            if row['label'] in ('app', 'loader', 'cohort')}
    return digest(canonical(payload))


def validator_function():
    path = Path(__file__).with_name('validate_official_release_candidate_v1.py')
    spec = importlib.util.spec_from_file_location('_reviewed_official_release_validator', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_observation


@contextmanager
def poll_lock(state):
    path = state/'poll.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
                'UNSAFE_POLL_LOCK')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AlreadyPolling('Another bounded poll owns this state directory') from error
        yield
    finally:
        os.close(descriptor)


def poll(repo_root, state_dir, *, now=None, getter=None, validator=None):
    root, state = scope(repo_root, state_dir)
    with poll_lock(state), directory_fence(root, state):
        retained = None
        previous_status = state/'status.json'
        if previous_status.exists():
            previous_raw = ordinary(previous_status)
            previous_value = json_value(previous_raw)
            if (previous_value.get('observation') or {}).get('status') in ('WAITING_DATE', 'WAITING_RELEASE', 'CANDIDATE_PRESENT'):
                archived = state/'history'/('verified-status.'+digest(previous_raw)+'.json')
                new_bytes(archived, previous_raw)
                retained = dict(path=str(archived.relative_to(root)), sha256=digest(previous_raw),
                    observed_at=previous_value['observation']['observed_at'],
                    status=previous_value['observation']['status'])
            else:
                retained = previous_value.get('last_verified_status')
        observation = collect(root, state, now=now, getter=getter)
        validate = validator_function() if validator is None else validator
        validation = validate(root, state, observation, now=now)
        require(type(validation) is dict and type(validation.get('status')) is str
                and type(validation.get('reasons')) is list, 'INVALID_INDEPENDENT_VALIDATION')
        require(all(key in validation and type(validation[key]) is type(expected)
                    and validation[key] == expected for key, expected in AUTH.items()),
                'INDEPENDENT_VALIDATOR_GRANTED_AUTHORITY')
        # Network/policy failures remain explicit even when evidence is incomplete.
        if observation['status'] not in ('TRANSPORT_UNAVAILABLE', 'REQUIRES_REVIEW'):
            selected = validation['status']
            observation['status'] = {'READY_FOR_SOURCE_REVIEW': 'CANDIDATE_PRESENT',
                'WAITING_OFFICIAL_FULL_COHORT': 'WAITING_RELEASE',
                'METADATA_UNAVAILABLE': 'TRANSPORT_UNAVAILABLE'}.get(selected, selected)
            require(observation['status'] in ('WAITING_DATE', 'WAITING_RELEASE', 'CANDIDATE_PRESENT',
                    'REQUIRES_REVIEW', 'TRANSPORT_UNAVAILABLE'),
                    'UNSUPPORTED_INDEPENDENT_STATUS')
        fingerprint = semantic_fingerprint(observation, validation)
        pointer_path = state/'outbox/current.json'
        previous = None
        if pointer_path.exists():
            previous = json_value(ordinary(pointer_path, 16384))
            require(type(previous) is dict and previous.get('schema') == 'jevops.official-release-outbox-pointer.v1'
                    and HEX64.fullmatch(previous.get('fingerprint', '')), 'INVALID_CURRENT_OUTBOX_POINTER')
        changed = previous is None or previous['fingerprint'] != fingerprint
        if changed:
            event_id = uuid.uuid4().hex
            event = dict(schema='jevops.official-release-event.v1', event_id=event_id, fingerprint=fingerprint,
                         observation=observation, validation=validation, **AUTH)
            path = state/'outbox/events'/(event_id+'.json')
            raw = canonical(event)
            new_bytes(path, raw)
            previous = dict(schema='jevops.official-release-outbox-pointer.v1',
                event=dict(path=str(path.relative_to(state)), sha256=digest(raw)), fingerprint=fingerprint)
            atomic_json(state, pointer_path, previous)
        result = dict(schema='jevops.official-release-watch-status.v1', observation=observation,
            validation=validation, stable_fingerprint=fingerprint, semantic_changed=changed,
            outbox=previous, last_verified_status=retained, status_snapshot_persisted=True, **AUTH)
        atomic_json(state, state/'status.json', result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--once', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        result = poll(args.repo_root, args.state_dir)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except AlreadyPolling as error:
        print(json.dumps(dict(status='POLL_ALREADY_RUNNING', error=str(error), **AUTH)), file=sys.stderr)
        return 75
    except OSError as error:
        if isinstance(error, InterruptedError):
            raise
        print(json.dumps(dict(status='PERSISTENCE_UNAVAILABLE', errno=error.errno,
                              error_type=type(error).__name__, status_snapshot_persisted=False, **AUTH)), file=sys.stderr)
        return 75
    except (ReviewRequired, ValueError) as error:
        print(json.dumps(dict(status='REQUIRES_REVIEW', error=str(error), **AUTH)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
