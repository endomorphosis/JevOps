"""Real retained organizer AST and immutable-byte fixtures; no network/jobs."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE/'tools/validate_official_release_candidate_v1.py'
spec = importlib.util.spec_from_file_location('independent_release_validator', SOURCE)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
PRIMARY = Path('/storage/hf_cache/jevops-official-release-research-20261029')
APP = (PRIMARY/'app.py.raw').read_bytes()
LOADER = (PRIMARY/'benchmark.py.raw').read_bytes()
REV = 'a'*40
SELECTED = 'benchmark_data_warmup.jsonl'


def rows(count=60):
    return [dict(name='demo'+str(i), source='strata', statement=f'theorem demo{i} : True',
                 src=f'theorem demo{i} : True := by trivial', header='',
                 url='https://github.com/example/repository', file_path='Demo.lean',
                 proof_length=1, num_lines=1, version_info=[{'v4.26.0': 'b'*40}])
            for i in range(count)]


def encoded(records):
    return b'\n'.join(json.dumps(r, sort_keys=True).encode() for r in records) + b'\n'


def blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path/'repo'
    root.mkdir(mode=0o775)
    state = root/'operator-release'
    state.mkdir(mode=0o700)
    (state/'evidence').mkdir(mode=0o700)
    return root, state


def fixture(campaign, *, count=60, records=None, app=APP, loader=LOADER, due=True,
            cohort=True, cohort_raw=None, head_revision=REV, selected=SELECTED):
    root, state = campaign
    records = rows(count) if records is None else records
    cohort_raw = encoded(records) if cohort_raw is None else cohort_raw
    api = dict(id=v.REPO_ID, sha=REV, runtime={'sha': REV, 'stage': 'RUNNING'})
    contents = {'app': app, 'loader': loader, 'cohort': cohort_raw}
    paths = {'app': 'app.py', 'loader': 'benchmark.py', 'cohort': selected}
    tree = [dict(type='file', path=paths[k], oid=blob(raw), size=len(raw))
            for k, raw in contents.items()]
    payloads = {'api': json.dumps(api).encode(), 'tree': json.dumps(tree).encode(),
                'app': app, 'loader': loader,
                'head': json.dumps(dict(api, sha=head_revision)).encode()}
    if cohort:
        payloads['cohort'] = cohort_raw
    urls = dict(api=v.API, head=v.API, tree=v.API+'/tree/'+REV+'?recursive=true',
                app=v.RAW+REV+'/app.py', loader=v.RAW+REV+'/benchmark.py',
                cohort=v.RAW+REV+'/'+selected)
    report = dict(schema=v.SCHEMA, observed_at=v.NOT_BEFORE+1 if due else v.NOT_BEFORE-1,
                  not_before=v.NOT_BEFORE, status='CANDIDATE_PRESENT' if due else 'WAITING_DATE',
                  revision=REV, declared_problem_count=60, selected_file=selected,
                  legacy_contract_problem_count=50, evidence=[], **v.AUTH)
    for label, raw in payloads.items():
        digest = hashlib.sha256(raw).hexdigest()
        p = state/'evidence'/(digest+'.raw')
        p.write_bytes(raw)
        report['evidence'].append(dict(label=label, url=urls[label], path=str(p.relative_to(root)),
                                       sha256=digest, bytes=len(raw)))
    return report


def validate(campaign, report):
    return v.validate_observation(*campaign, report, now=report['observed_at'])


def replace_evidence(campaign, report, label, raw):
    root, state = campaign
    packet = next(x for x in report['evidence'] if x['label'] == label)
    digest = hashlib.sha256(raw).hexdigest()
    p = state/'evidence'/(digest+'.raw')
    p.write_bytes(raw)
    packet.update(path=str(p.relative_to(root)), sha256=digest, bytes=len(raw))


def test_due_sixty_replacement_in_same_warmup_filename_is_only_review_ready(campaign):
    report = fixture(campaign)
    before = copy.deepcopy(report)
    value = validate(campaign, report)
    assert value['status'] == 'READY_FOR_SOURCE_REVIEW'
    assert value['observed_problem_count'] == value['declared_problem_count'] == value['pin_count'] == 60
    assert value['semantic']['selected_file'] == SELECTED
    assert value['semantic']['legacy_count_mismatch'] and value['semantic']['migration_state'] == 'READY_FOR_SOURCE_REVIEW'
    assert value['semantic']['deployment_readiness_claimed'] is False
    assert value['proof_authority'] is value['completion_authority'] is value['task_states_changed'] is False
    assert report == before


@pytest.mark.parametrize('status', ['WAITING_DATE', 'WAITING_RELEASE', 'CANDIDATE_PRESENT', 'REQUIRES_REVIEW'])
def test_revalidation_is_deterministic_after_producer_status_rebasing(campaign, status):
    report = fixture(campaign)
    expected = validate(campaign, report)
    report['status'] = status
    assert validate(campaign, report) == expected


def test_legitimate_uid_owned_0775_ancestors_are_not_chmodded_or_refused(campaign):
    root, _ = campaign
    root.chmod(0o775)
    report = fixture(campaign)
    assert validate(campaign, report)['status'] == 'READY_FOR_SOURCE_REVIEW'
    assert root.stat().st_mode & 0o777 == 0o775


def test_pre_date_allows_metadata_but_never_cohort_request_or_acceptance(campaign):
    report = fixture(campaign, due=False, cohort=False)
    assert validate(campaign, report)['status'] == 'WAITING_DATE'
    forbidden = fixture(campaign, due=False)
    assert validate(campaign, forbidden)['status'] == 'REQUIRES_REVIEW'
    assert validate(campaign, forbidden)['reasons'] == ['premature_cohort_request']


def test_future_full_cohort_event_cannot_claim_release_before_actual_delivery_clock(campaign):
    report = fixture(campaign)
    value = v.validate_observation(*campaign, report, now=v.NOT_BEFORE-100)
    assert value['status'] == 'REQUIRES_REVIEW' and value['reasons'] == ['observation_time_bound']
    assert value['completion_authority'] is False


def test_historical_wait_date_is_not_retimed_into_release_success(campaign):
    report = fixture(campaign, due=False, cohort=False)
    original = validate(campaign, report)
    assert v.validate_observation(*campaign, report, now=v.NOT_BEFORE+86400) == original
    assert original['status'] == 'WAITING_DATE'


@pytest.mark.parametrize('count', [15, 50, 59, 61])
def test_noncomplete_count_cannot_become_full_cohort(campaign, count):
    value = validate(campaign, fixture(campaign, count=count))
    assert value['status'] == 'WAITING_OFFICIAL_FULL_COHORT'
    assert value['observed_problem_count'] == count
    assert value['completion_authority'] is False


def test_empty_string_headers_and_putnam_empty_url_and_rc_pins_are_preserved(campaign):
    records = rows()
    records[0].update(source='putnambench', url='', file_path='',
                      header='import Mathlib\n', version_info=[{'v4.33.0-rc2': 'c'*40}])
    value = validate(campaign, fixture(campaign, records=records))
    assert value['status'] == 'READY_FOR_SOURCE_REVIEW' and value['semantic']['string_headers_preserved']
    expected = hashlib.sha256(json.dumps([[r['name'], r['header']]for r in records],
                                         sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert value['semantic']['header_semantic_sha256'] == expected


def test_new_source_label_with_github_metadata_does_not_invent_native_adoption(campaign):
    records = rows()
    records[0]['source'] = 'new-organizer-project'
    value = validate(campaign, fixture(campaign, records=records))
    assert value['status'] == 'READY_FOR_SOURCE_REVIEW'
    assert value['semantic']['source_counts']['new-organizer-project'] == 1
    assert value['proof_authority'] is value['completion_authority'] is False


@pytest.mark.parametrize('damage', ['duplicate_name', 'missing_header', 'list_header', 'bad_tag',
                                   'moving_pin', 'duplicate_pin', 'ambiguous_pin', 'empty_pin',
                                   'foreign_repo', 'empty_project_url', 'missing_statement'])
def test_independent_cohort_envelope_refusals(campaign, damage):
    records = rows()
    if damage == 'duplicate_name': records[1]['name'] = records[0]['name']
    elif damage == 'missing_header': records[0].pop('header')
    elif damage == 'list_header': records[0]['header'] = []
    elif damage == 'bad_tag': records[0]['version_info'] = [{'latest': 'b'*40}]
    elif damage == 'moving_pin': records[0]['version_info'] = [{'v4.26.0': 'main'}]
    elif damage == 'duplicate_pin': records[0]['version_info'] *= 2
    elif damage == 'ambiguous_pin': records[0]['version_info'] = [{'v4.26.0': 'b'*40, 'v4.27.0': 'c'*40}]
    elif damage == 'empty_pin': records[0]['version_info'] = []
    elif damage == 'foreign_repo': records[0]['url'] = 'https://github.com.evil/example/repo'
    elif damage == 'empty_project_url': records[0]['url'] = ''
    else: records[0].pop('statement')
    assert validate(campaign, fixture(campaign, records=records))['status'] == 'REQUIRES_REVIEW'


@pytest.mark.parametrize('damage', ['count_duplicate', 'date_duplicate', 'count_claim', 'path_claim',
                                   'header_loss', 'async_loader', 'download_selection'])
def test_ast_reconstruction_rejects_ambiguity_and_header_loss(campaign, damage):
    app, loader = APP, LOADER
    if damage == 'count_duplicate': app += b'\nFULL_BENCH_SIZE = 60\n'
    elif damage == 'date_duplicate': app += b'\nFULL_BENCH_RELEASE = "November 1, 2026"\n'
    elif damage == 'header_loss': loader = loader.replace(b'"header": entry.get("header", "")', b'"header": ""')
    elif damage == 'async_loader': loader = loader.replace(b'def _load()', b'async def _load()')
    elif damage == 'download_selection': app = app.replace(b'value=BENCHMARK_JSONL_PATH,', b'value="other.jsonl",')
    report = fixture(campaign, app=app, loader=loader)
    if damage == 'count_claim': report['declared_problem_count'] = 50
    elif damage == 'path_claim': report['selected_file'] = 'benchmark_data_full.jsonl'
    assert validate(campaign, report)['status'] == 'REQUIRES_REVIEW'


@pytest.mark.parametrize('damage', ['foreign_url', 'revision_url', 'blob', 'head', 'duplicate_tree',
                                   'duplicate_evidence', 'outside', 'symlink', 'bytes'])
def test_official_revision_bytes_and_owned_path_binding(campaign, damage):
    report = fixture(campaign)
    packet = next(x for x in report['evidence']if x['label'] == 'app')
    root, state = campaign
    if damage == 'foreign_url': packet['url'] = 'https://evil.invalid/app.py'
    elif damage == 'revision_url': packet['url'] = v.RAW+'c'*40+'/app.py'
    elif damage == 'blob':
        tree_packet = next(x for x in report['evidence']if x['label'] == 'tree')
        tree = json.loads((root/tree_packet['path']).read_text()); tree[0]['oid'] = '0'*40
        replace_evidence(campaign, report, 'tree', json.dumps(tree).encode())
    elif damage == 'head':
        replace_evidence(campaign, report, 'head', json.dumps({'id': v.REPO_ID, 'sha': 'c'*40}).encode())
    elif damage == 'duplicate_tree':
        tree_packet = next(x for x in report['evidence']if x['label'] == 'tree')
        tree = json.loads((root/tree_packet['path']).read_text()); tree.append(tree[0])
        replace_evidence(campaign, report, 'tree', json.dumps(tree).encode())
    elif damage == 'duplicate_evidence': report['evidence'].append(copy.deepcopy(packet))
    elif damage == 'outside': packet['path'] = '../outside.raw'
    elif damage == 'symlink':
        p = root/packet['path']; target = state/'saved-app'; target.write_bytes(p.read_bytes()); p.unlink(); p.symlink_to(target)
    else: (root/packet['path']).write_bytes(b'changed')
    assert validate(campaign, report)['status'] in {'REQUIRES_REVIEW', 'METADATA_UNAVAILABLE'}


@pytest.mark.parametrize('raw', [b'{"name":"x","name":"y"}', b'{"x":NaN}',
                               b'{"x":1e9999}', b'['*12000, b'\xff', b'{}\n' + b'x'*262145])
def test_malformed_deep_nonfinite_and_oversized_rows_fail_closed(campaign, raw):
    assert validate(campaign, fixture(campaign, cohort_raw=raw))['status'] == 'REQUIRES_REVIEW'


@pytest.mark.parametrize('field,value', [('observed_at', float('inf')), ('observed_at', True),
                                       ('not_before', v.NOT_BEFORE-1), ('proof_authority', True),
                                       ('model_calls', 1), ('official_score', 0),
                                       ('native_proofs_verified', 60), ('phase_allocated', True)])
def test_time_and_authority_claims_never_succeed(campaign, field, value):
    report = fixture(campaign); report[field] = value
    result = v.validate_observation(*campaign, report, now=v.NOT_BEFORE+2)
    assert result['status'] == 'REQUIRES_REVIEW'


class PhaseDeadline(BaseException):
    pass


@pytest.mark.parametrize('error', [KeyboardInterrupt('original'), SystemExit('original'),
                                  InterruptedError('original'), PhaseDeadline('original')])
def test_original_reader_controls_propagate(campaign, monkeypatch, error):
    report = fixture(campaign)
    def fail(*a, **k): raise error
    monkeypatch.setattr(v, '_owned_bytes', fail)
    with pytest.raises(type(error))as caught: validate(campaign, report)
    assert caught.value is error


def test_bounded_validator_clock_exhaustion_is_explicit(campaign, monkeypatch):
    report = fixture(campaign)
    ticks = iter([0.0, 100.0])
    monkeypatch.setattr(v.time, 'monotonic', lambda: next(ticks, 100.0))
    result = validate(campaign, report)
    assert result['status'] == 'REQUIRES_REVIEW' and result['reasons'] == ['validation_time_bound']


def test_downloaded_python_is_parsed_but_never_executed(campaign):
    sentinel = campaign[0]/'MUST_NOT_BE_WRITTEN'
    malicious = b'\nopen('+repr(str(sentinel)).encode()+b', "w").write("executed")\n'
    report = fixture(campaign, app=APP+malicious)
    assert validate(campaign, report)['status'] == 'READY_FOR_SOURCE_REVIEW'
    assert not sentinel.exists()


def test_missing_transport_evidence_is_explicit_and_cannot_claim_release(campaign):
    report = fixture(campaign)
    report['status'] = 'TRANSPORT_UNAVAILABLE'
    report['evidence'] = []
    value = validate(campaign, report)
    assert value['status'] == 'METADATA_UNAVAILABLE'


def test_runtime_lag_is_retained_without_deployment_readiness_claim(campaign):
    report = fixture(campaign)
    replace_evidence(campaign, report, 'api', json.dumps({'id': v.REPO_ID, 'sha': REV,
        'runtime': {'sha': 'c'*40, 'stage': 'RUNNING'}}).encode())
    value = validate(campaign, report)
    assert value['status'] == 'READY_FOR_SOURCE_REVIEW'
    assert value['semantic']['runtime_matches_pinned_revision'] is False
    assert value['semantic']['deployment_readiness_claimed'] is False


def test_frozen_legacy_producer_accepts50_but_retains60_denominator_wait(campaign, monkeypatch):
    """Actual unchanged code with bounded fake HTTP, never live external requests."""
    root, _ = campaign
    canonical = Path('/home/barberb/lift_coding/JevOps')
    sys.path.insert(0, str(canonical/'tools'))
    modules = []
    for name in ['lean_refactor_release_inventory', 'validate_lean_refactor_release_inventory']:
        sp = importlib.util.spec_from_file_location('_frozen_'+name, canonical/'tools'/(name+'.py'))
        m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); modules.append(m)
    producer, validator = modules
    monkeypatch.setattr(validator, 'time', SimpleNamespace(time=lambda: v.NOT_BEFORE+20))
    producer.c.atomic(root/producer.HISTORICAL, 'private historical baseline\n')
    producer.c.save(root/producer.c.RUNTIME/'JLR-017.result.json', {'private_fixture': True})
    def produce(count):
        responses = [json.dumps({'sha': REV}).encode(),
                     json.dumps([{'type': 'file', 'path': 'benchmark_data_full.jsonl'}]).encode(),
                     encoded(rows(count))]
        requests = []
        def getter(url, limit, deadline):
            requests.append(url); return responses[len(requests)-1]
        value = producer.produce(root, now=v.NOT_BEFORE+1, getter=getter)
        assert len(requests) == 3
        return value
    old50 = produce(50)
    assert old50['status'] == 'INVENTORIED' and validator.validate(root, old50)['problem_count'] == 50
    new60 = produce(60)
    assert new60['status'] == 'WAITING_RELEASE' and new60['observed_problem_count'] == 60
    with pytest.raises(producer.c.GateWait): validator.validate(root, new60)
    assert validate(campaign, fixture(campaign))['status'] == 'READY_FOR_SOURCE_REVIEW'
