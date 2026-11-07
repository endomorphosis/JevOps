"""Independently inspect official release bytes; never grant legacy task authority.

No downloaded module is imported, evaluated or executed. The selected filename
comes from the official loader, including replacement of a warmup-named file.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlsplit

SCHEMA = 'jevops.official-release-observation.v1'
API = 'https://huggingface.co/api/spaces/delta-lab-ai/lean-refactor-arena'
RAW = 'https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/raw/'
REPO_ID = 'delta-lab-ai/lean-refactor-arena'
NOT_BEFORE = 1793491200
APPROVED_DECLARED_COUNT = 60
LEGACY_COUNT = 50
HISTORICAL_WARMUP_SHA256 = '6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804'
LIMITS = dict(api=262144, tree=524288, app=262144, loader=262144,
              cohort=4194304, head=262144)
AUTH = dict(model_calls=0, native_processes=0, training=False, proof_authority=False,
            completion_authority=False, scientific_acceptance_authority=False,
            full_campaign_complete=False, task_states_changed=False)
STATUSES = {'WAITING_DATE', 'WAITING_RELEASE', 'CANDIDATE_PRESENT',
            'REQUIRES_REVIEW', 'TRANSPORT_UNAVAILABLE'}
_HEX40 = re.compile('[0-9a-f]{40}')
_HEX64 = re.compile('[0-9a-f]{64}')
_TAG = re.compile(r'v4\.\d+\.\d+(?:-rc[1-9]\d*)?')


class Invalid(ValueError):
    pass


class Unavailable(ValueError):
    pass


def _require(ok, reason):
    if not ok:
        raise Invalid(reason)


def _control(error):
    return not isinstance(error, Exception) or isinstance(error, InterruptedError)


def _check(deadline):
    _require(time.monotonic() < deadline, 'validation_time_bound')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _relative(value):
    _require(type(value) is str and 0 < len(value) <= 1024 and '\0' not in value,
             'invalid_relative_path')
    pieces = value.split('/')
    _require(all(p not in ('', '.', '..') for p in pieces) and len(pieces) <= 64,
             'invalid_relative_path')
    return Path(*pieces)


def _owned_bytes(path, maximum, deadline):
    """Hold no-follow descriptors; ignore unrelated directory timestamps."""
    path = Path(path).absolute()
    _require('..' not in path.parts and len(path.parts) <= 80, 'invalid_evidence_path')
    handles, links = [], []
    pending, result = None, None
    directory = lambda s: (s.st_dev, s.st_ino, s.st_uid, s.st_mode)
    identity = lambda s: (*directory(s), s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open('/', flags | os.O_DIRECTORY)
        handles.append(fd)
        for name in path.parts[1:-1]:
            _check(deadline)
            child = os.open(name, flags | os.O_DIRECTORY, dir_fd=fd)
            handles.append(child)
            links.append((fd, name, child, directory(os.fstat(child))))
            fd = child
        leaf = os.open(path.name, flags, dir_fd=fd)
        handles.append(leaf)
        before = os.fstat(leaf)
        _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                 and before.st_nlink == 1 and 0 <= before.st_size <= maximum,
                 'unsafe_or_oversized_evidence')
        chunks, size = [], 0
        while True:
            _check(deadline)
            chunk = os.read(leaf, min(1048576, maximum - size + 1))
            if not chunk:
                break
            size += len(chunk)
            _require(size <= maximum, 'evidence_grew_past_bound')
            chunks.append(chunk)
        result = b''.join(chunks)
        os.lseek(leaf, 0, os.SEEK_SET)
        verified = 0
        while True:
            _check(deadline)
            chunk = os.read(leaf, min(1048576, maximum - verified + 1))
            if not chunk:
                break
            _require(result[verified:verified + len(chunk)] == chunk, 'evidence_bytes_changed')
            verified += len(chunk)
            _require(verified <= maximum, 'evidence_grew_past_bound')
        _require(verified == size == before.st_size
                 and identity(before) == identity(os.fstat(leaf))
                 == identity(os.stat(path.name, dir_fd=fd, follow_symlinks=False)),
                 'evidence_identity_changed')
        for parent, name, child, expected in reversed(links):
            _require(directory(os.fstat(child)) == expected
                     == directory(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                     'evidence_ancestor_changed')
    except BaseException as exc:
        pending = exc
    finally:
        for fd in reversed(handles):
            try:
                os.close(fd)
            except BaseException as exc:
                if pending is None or (not _control(pending) and _control(exc)):
                    pending = exc
    if pending is not None:
        raise pending
    return result


def _json(raw, deadline):
    def pairs(items):
        value = {}
        for key, child in items:
            _require(key not in value, 'duplicate_json_key')
            value[key] = child
        return value
    def nonfinite(_):
        raise Invalid('nonfinite_json')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise Invalid('malformed_or_deep_json') from exc
    todo, count = [(value, 0)], 0
    while todo:
        _check(deadline)
        item, depth = todo.pop()
        count += 1
        _require(depth <= 32 and count <= 100000, 'json_structure_bound')
        if type(item) is float:
            _require(math.isfinite(item), 'nonfinite_json')
        elif type(item) is dict:
            todo.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            todo.extend((v, depth + 1) for v in item)
    return value


def _syntax(raw, deadline):
    try:
        tree = ast.parse(raw.decode('utf-8'))
    except (SyntaxError, UnicodeError, RecursionError) as exc:
        raise Invalid('malformed_or_deep_python_ast') from exc
    todo, count = [(tree, 0)], 0
    while todo:
        _check(deadline)
        node, depth = todo.pop()
        count += 1
        _require(count <= 40000 and depth <= 80, 'python_ast_structure_bound')
        todo.extend((x, depth + 1) for x in ast.iter_child_nodes(node))
    return tree


def _assignments(tree, name):
    found = []
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            found.append(node)
    return found


def _literal(tree, name, kind):
    rows = _assignments(tree, name)
    _require(len(rows) == 1 and rows[0] in tree.body
             and isinstance(rows[0].value, ast.Constant)
             and type(rows[0].value.value) is kind, 'ambiguous_literal_' + name)
    return rows[0].value.value


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _expr(source):
    return ast.parse(source, mode='eval').body


def _module_path(value):
    _require(isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)
             and _dump(value.left) == _dump(_expr('Path(__file__).resolve().parent'))
             and isinstance(value.right, ast.Constant) and type(value.right.value) is str,
             'unsupported_static_loader_path')
    name = value.right.value
    _relative(name)
    _require(len(name) <= 256 and re.fullmatch(r'[A-Za-z0-9_./-]+\.jsonl', name),
             'unsupported_selected_filename')
    return name


def _body(function):
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and type(body[0].value.value) is str:
        body = body[1:]
    return ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)


_LOAD = '''def _load():
    out: dict[str, dict] = {}
    if not _DATA_PATH.exists():
        return out
    heartbeats = _load_heartbeats()
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            name = entry.get("name")
            if not name:
                continue
            out[name] = {
                "source": entry.get("source", ""),
                "original_proof_length": int(entry.get("proof_length", 0)),
                "original_heartbeats": heartbeats.get(name),
                "num_lines": int(entry.get("num_lines", 0)),
                "header": entry.get("header", ""),
                "statement": entry.get("statement", ""),
                "src": entry.get("src", ""),
                "file_path": entry.get("file_path", ""),
                "url": entry.get("url", ""),
                "start_line": entry.get("start_line"),
                "end_line": entry.get("end_line"),
                "version_info": entry.get("version_info", []),
            }
    return out
'''


def _metadata(app_raw, loader_raw, deadline):
    app, loader = _syntax(app_raw, deadline), _syntax(loader_raw, deadline)
    declared = _literal(app, 'FULL_BENCH_SIZE', int)
    release = _literal(app, 'FULL_BENCH_RELEASE', str)
    proof_date = _literal(app, 'PROOF_CODE_DEADLINE', str)
    report_date = _literal(app, 'REPORT_DEADLINE', str)
    _require(declared == APPROVED_DECLARED_COUNT, 'official_declared_count_requires_review')
    _require(release == 'November 1, 2026', 'official_release_date_requires_review')
    _require(proof_date == 'November 3, 2026 AoE' and report_date == 'November 8, 2026 AoE',
             'official_deadlines_require_review')
    rows = _assignments(loader, '_DATA_PATH')
    _require(len(rows) == 1 and rows[0] in loader.body, 'ambiguous_loader_selection')
    selected = _module_path(rows[0].value)
    heartbeat = _assignments(loader, '_HEARTBEATS_PATH')
    _require(len(heartbeat) == 1 and heartbeat[0] in loader.body, 'ambiguous_heartbeat_selection')
    heartbeat_file = _module_path(heartbeat[0].value)
    selections = _assignments(app, 'BENCHMARK_JSONL_PATH')
    initial = [n for n in selections if n in app.body]
    _require(len(selections) == 2 and len(initial) == 1
             and isinstance(initial[0].value, ast.Constant)
             and initial[0].value.value == '/home/user/app/' + selected,
             'app_download_selection_differs')
    fallback = ast.parse('if not Path(BENCHMARK_JSONL_PATH).exists():\n'
        '    _local_bench = Path(__file__).resolve().parent / ' + repr(selected) + '\n'
        '    if _local_bench.exists():\n'
        '        BENCHMARK_JSONL_PATH = str(_local_bench)\n').body[0]
    _require(sum(_dump(n) == _dump(fallback) for n in app.body) == 1,
             'unsupported_app_download_fallback')
    downloads = [n for n in ast.walk(app) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'DownloadButton']
    _require(len(downloads) == 1 and sum(k.arg == 'value' and isinstance(k.value, ast.Name)
             and k.value.id == 'BENCHMARK_JSONL_PATH' for k in downloads[0].keywords) == 1,
             'download_button_selection_differs')
    loads = [n for n in ast.walk(loader) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == '_load']
    headers = [n for n in ast.walk(loader) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'benchmark_header']
    expected_header = ast.parse("def benchmark_header(name):\n    entry = BENCHMARK.get(name)\n    return entry['header'] if entry else None\n").body[0]
    _require(len(loads) == len(headers) == 1 and type(loads[0]) is ast.FunctionDef
             and type(headers[0]) is ast.FunctionDef and not loads[0].decorator_list
             and not headers[0].decorator_list and not loads[0].args.args
             and not loads[0].args.posonlyargs and loads[0].args.vararg is None
             and loads[0].args.kwarg is None and not loads[0].args.kwonlyargs
             and len(headers[0].args.args) == 1 and headers[0].args.args[0].arg == 'name'
             and not headers[0].args.posonlyargs and headers[0].args.vararg is None
             and headers[0].args.kwarg is None and not headers[0].args.kwonlyargs
             and not headers[0].args.defaults and not headers[0].args.kw_defaults
             and _body(loads[0]) == _body(ast.parse(_LOAD).body[0])
             and _body(headers[0]) == _body(expected_header), 'unsupported_loader_or_header_handling')
    loaded = _assignments(loader, 'BENCHMARK')
    _require(len(loaded) == 1 and loaded[0] in loader.body
             and _dump(loaded[0].value) == _dump(_expr('_load()')), 'unsupported_benchmark_binding')
    return dict(declared_problem_count=declared, selected_file=selected,
                declared_release='2026-11-01', release_hour_or_timezone_inferred=False,
                proof_code_deadline=proof_date, report_deadline=report_date,
                heartbeat_file=heartbeat_file, string_headers_preserved=True)


def _cohort(raw, deadline):
    names, headers, pins, source_counts = set(), [], [], {}
    count = 0
    for line in raw.splitlines():
        _check(deadline)
        if not line.strip():
            continue
        _require(len(line) <= 262144 and count < 128, 'cohort_line_or_row_bound')
        row = _json(line, deadline)
        _require(type(row) is dict, 'cohort_row_must_be_object')
        for key in ('name', 'source', 'statement', 'src', 'header'):
            _require(type(row.get(key)) is str and '\0' not in row[key], 'missing_or_invalid_' + key)
        name, source = row['name'], row['source']
        _require(name and name.strip() == name and name not in names, 'duplicate_or_empty_record_name')
        _require(source.strip() and len(source.encode('utf-8')) <= 256
                 and row['statement'].strip() and row['src'].strip(), 'invalid_source_or_theorem_envelope')
        url = row.get('url', '')
        _require(type(url) is str, 'invalid_repository_url')
        if url:
            parsed = urlsplit(url)
            _require(parsed.scheme == 'https' and parsed.netloc == 'github.com'
                     and parsed.username is None and parsed.password is None
                     and not parsed.query and not parsed.fragment
                     and len([x for x in parsed.path.split('/') if x]) == 2,
                     'foreign_repository_url')
        else:
            _require(source == 'putnambench', 'missing_project_repository_url')
        versions = row.get('version_info')
        _require(type(versions) is list and 0 < len(versions) <= 32, 'missing_exact_pins')
        tags, row_pins = set(), []
        for version in versions:
            _require(type(version) is dict and len(version) == 1, 'ambiguous_pin_entry')
            tag, commit = next(iter(version.items()))
            _require(type(tag) is str and _TAG.fullmatch(tag) and type(commit) is str
                     and _HEX40.fullmatch(commit) and tag not in tags, 'invalid_or_duplicate_pin')
            tags.add(tag)
            row_pins.append([tag, commit])
        names.add(name)
        count += 1
        headers.append([name, row['header']])
        pins.append([name, row_pins])
        source_counts[source] = source_counts.get(source, 0) + 1
    return dict(observed_problem_count=count, pin_count=sum(len(x[1]) for x in pins),
                header_semantic_sha256=_digest(_canonical(headers)),
                pin_semantic_sha256=_digest(_canonical(pins)), source_counts=source_counts)


def validate_observation(repo_root, state_dir, report, *, now=None):
    """Return only a new candidate-observation decision, never JLR-035 success."""
    deadline = time.monotonic() + 10
    result = dict(status='METADATA_UNAVAILABLE', reasons=[], declared_problem_count=None,
                  observed_problem_count=None, pin_count=None, semantic={}, **AUTH)
    try:
        _require(type(report) is dict and report.get('schema') == SCHEMA, 'observation_schema')
        now = time.time() if now is None else now
        observed = report.get('observed_at')
        _require(type(now) in (int, float) and math.isfinite(now) and type(observed) in (int, float)
                 and math.isfinite(observed) and 0 <= observed <= now, 'observation_time_bound')
        _require(type(report.get('not_before')) is int and report['not_before'] == NOT_BEFORE,
                 'not_before_policy_changed')
        _require(report.get('status') in STATUSES, 'observation_status')
        for key, expected in AUTH.items():
            _require(type(report.get(key)) is type(expected) and report[key] == expected, 'authority_' + key)
        for key in ('stage_accepted', 'phase_allocated', 'full_cohort_activated',
                    'source_profile_approval_granted', 'new_scientific_call_ledger_created',
                    'training_executed'):
            _require(key not in report or report[key] is False, 'forbidden_' + key)
        _require(report.get('official_score') is None, 'forbidden_self_score')
        _require(report.get('score') is None and report.get('self_score') is None,
                 'forbidden_self_score')
        for key in ('native_proofs_verified', 'scientific_calls_added'):
            _require(key not in report or type(report[key]) is int and report[key] == 0,
                     'forbidden_' + key)
        _require(type(report.get('legacy_contract_problem_count')) is int
                 and report['legacy_contract_problem_count'] == LEGACY_COUNT, 'legacy_contract_changed')
        root, state = Path(repo_root).absolute(), Path(state_dir)
        state = state.absolute() if state.is_absolute() else (root / state).absolute()
        _require(state.is_relative_to(root) and '..' not in state.parts, 'state_directory_outside_repo')
        rows = report.get('evidence')
        _require(type(rows) is list and len(rows) <= 6, 'evidence_population_bound')
        evidence, total = {}, 0
        for row in rows:
            _check(deadline)
            _require(type(row) is dict and set(row) == {'label', 'url', 'path', 'sha256', 'bytes'}, 'evidence_row_schema')
            label = row['label']
            _require(type(label) is str and label in LIMITS and label not in evidence, 'duplicate_or_unknown_evidence_label')
            path = root / _relative(row['path'])
            _require(path.is_relative_to(state/'evidence'), 'evidence_outside_owned_state')
            _require(type(row['sha256']) is str and _HEX64.fullmatch(row['sha256'])
                     and type(row['bytes']) is int and 0 <= row['bytes'] <= LIMITS[label], 'evidence_digest_or_byte_bound')
            raw = _owned_bytes(path, LIMITS[label], deadline)
            total += len(raw)
            _require(total <= 6*1024**2 and len(raw) == row['bytes'] and _digest(raw) == row['sha256'], 'evidence_bytes_differ')
            evidence[label] = (row, raw)
        if observed < NOT_BEFORE:
            _require('cohort' not in evidence, 'premature_cohort_request')
        for label in ('api', 'tree', 'app', 'loader'):
            if label not in evidence:
                raise Unavailable('missing_evidence_' + label)
        api = _json(evidence['api'][1], deadline)
        _require(type(api) is dict and api.get('id') == REPO_ID
                 and type(api.get('sha')) is str and _HEX40.fullmatch(api['sha']), 'official_api_identity')
        revision = api['sha']
        _require(report.get('revision') == revision and evidence['api'][0]['url'] == API, 'revision_or_api_url_differs')
        tree_urls = {API+'/tree/'+revision+'?recursive=true', API+'/tree/'+revision+'?recursive=true&expand=false'}
        _require(evidence['tree'][0]['url'] in tree_urls, 'tree_url_differs')
        tree = _json(evidence['tree'][1], deadline)
        _require(type(tree) is list and len(tree) <= 1000, 'tree_population_bound')
        entries = {}
        for item in tree:
            _require(type(item) is dict and item.get('type') in ('file', 'directory'), 'unsupported_tree_entry')
            path = str(_relative(item.get('path')))
            _require(path not in entries and type(item.get('oid')) is str and _HEX40.fullmatch(item['oid'])
                     and type(item.get('size')) is int and item['size'] >= 0, 'duplicate_or_invalid_tree_entry')
            entries[path] = item
        def match(label, name):
            _require(label in evidence and name in entries and entries[name]['type'] == 'file', 'missing_selected_tree_file')
            row, body = evidence[label]
            _require(row['url'] == RAW+revision+'/'+name and entries[name]['size'] == len(body)
                     and entries[name]['oid'] == _git_blob(body), 'official_blob_or_url_differs_' + label)
        match('app', 'app.py')
        match('loader', 'benchmark.py')
        metadata = _metadata(evidence['app'][1], evidence['loader'][1], deadline)
        result['declared_problem_count'] = metadata['declared_problem_count']
        _require(report.get('declared_problem_count') == metadata['declared_problem_count']
                 and report.get('selected_file') == metadata['selected_file'], 'producer_metadata_claim_differs')
        if 'head' in evidence:
            _require(evidence['head'][0]['url'] == API, 'head_url_differs')
            head = _json(evidence['head'][1], deadline)
            _require(type(head) is dict and head.get('id') == REPO_ID and head.get('sha') == revision, 'head_revision_drift')
        elif observed >= NOT_BEFORE:
            raise Unavailable('missing_evidence_head')
        runtime = api.get('runtime') if type(api.get('runtime')) is dict else {}
        semantic = dict(metadata, revision=revision, legacy_contract_problem_count=LEGACY_COUNT,
                        legacy_count_mismatch=LEGACY_COUNT != metadata['declared_problem_count'],
                        migration_state='SOURCE_REVIEW_REQUIRED', runtime_head_sha=runtime.get('sha'),
                        runtime_matches_pinned_revision=runtime.get('sha') == revision,
                        deployment_readiness_claimed=False, historical_corpus_replaced=False,
                        app_sha256=_digest(evidence['app'][1]), loader_sha256=_digest(evidence['loader'][1]))
        result['semantic'] = semantic
        if observed < NOT_BEFORE:
            result.update(status='WAITING_DATE', reasons=['not_before_release_date'])
            return result
        if 'cohort' not in evidence:
            raise Unavailable('missing_evidence_cohort')
        match('cohort', metadata['selected_file'])
        summary = _cohort(evidence['cohort'][1], deadline)
        digest = _digest(evidence['cohort'][1])
        result.update({k: summary[k] for k in ('observed_problem_count', 'pin_count')})
        semantic.update(summary, cohort_sha256=digest, cohort_git_blob_sha1=_git_blob(evidence['cohort'][1]),
                        unchanged_historical_warmup=digest == HISTORICAL_WARMUP_SHA256)
        if summary['observed_problem_count'] != metadata['declared_problem_count'] or digest == HISTORICAL_WARMUP_SHA256:
            result.update(status='WAITING_OFFICIAL_FULL_COHORT', reasons=['selected_asset_not_complete_declared_cohort'])
            return result
        semantic['migration_state'] = 'READY_FOR_SOURCE_REVIEW'
        result.update(status='READY_FOR_SOURCE_REVIEW', reasons=['legacy_50_contract_requires_reviewed_migration'])
        return result
    except InterruptedError:
        raise
    except Unavailable as exc:
        result.update(status='METADATA_UNAVAILABLE', reasons=[str(exc)])
    except Invalid as exc:
        result.update(status='REQUIRES_REVIEW', reasons=[str(exc)])
    except (OSError, UnicodeError) as exc:
        result.update(status='METADATA_UNAVAILABLE', reasons=['evidence_read_unavailable_' + type(exc).__name__])
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        result.update(status='REQUIRES_REVIEW', reasons=['invalid_metadata_' + type(exc).__name__])
    return result
