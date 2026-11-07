"""Private fake HTTP and real owned-file fixtures; no network/process/model jobs."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1]/'tools/official_release_watch.py'
spec = importlib.util.spec_from_file_location('official_watch_under_test', SOURCE)
w = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = w
spec.loader.exec_module(w)
RESEARCH = Path('/storage/hf_cache/jevops-official-release-research-20261029')


def no_external_jobs(event, args):
    if event in {'socket.__new__', 'socket.connect', 'subprocess.Popen', 'os.system',
                 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg'}:
        raise AssertionError('No network, processes, or signals in private fixtures: '+event)


sys.addaudithook(no_external_jobs)


def blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def encoded(value):
    return json.dumps(value).encode()


class HTTP:
    def __init__(self, count=15, revision='a'*40):
        self.revision = revision
        self.head = revision
        self.app = (RESEARCH/'app.py.raw').read_bytes()
        self.loader = (RESEARCH/'benchmark.py.raw').read_bytes()
        self.selected = 'benchmark_data_warmup.jsonl'
        self.cohort = b''.join(encoded(dict(name='problem'+str(i), source='putnambench', header='',
            statement='theorem example'+str(i)+' : True := by trivial', src='by trivial',
            version_info=[{'v4.33.0-rc2': 'b'*40}], url='', file_path='', proof_length=1, num_lines=1))+b'\n' for i in range(count))
        self.calls = []
        self.overrides = {}
        self.api_count = 0

    def __call__(self, url, **bounds):
        assert 0 < bounds['timeout'] <= 8
        assert bounds['max_bytes'] <= 4*1024*1024
        assert bounds['deadline'] > 0
        self.calls.append(url)
        if url in self.overrides:
            override = self.overrides[url]
            if isinstance(override, BaseException):
                raise override
            return override
        if url == w.API:
            self.api_count += 1
            revision = self.revision if self.api_count % 2 else self.head
            value = encoded(dict(id=w.REPO, sha=revision, private=False,
                runtime=dict(sha=revision, stage='RUNNING')))
        elif '/tree/' in url:
            value = encoded([dict(type='file', path=name, size=len(raw), oid=blob(raw)) for name, raw in
                             [('app.py', self.app), ('benchmark.py', self.loader), (self.selected, self.cohort)]])
        elif url.endswith('/app.py'):
            value = self.app
        elif url.endswith('/benchmark.py'):
            value = self.loader
        elif url.endswith('/'+self.selected):
            value = self.cohort
        else:
            raise AssertionError('Unreviewed URL requested: '+url)
        return w.HTTPResult(200, {}, value, url)


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path/'repo'
    root.mkdir(mode=0o700)
    state = root/'private-state'
    return root, state


def local_validator(root, state, observation, *, now=None):
    due = observation['observed_at'] >= w.NOT_BEFORE
    row = next((x for x in observation['evidence'] if x['label'] == 'cohort'), None)
    count = None if row is None else len([s for s in (root/row['path']).read_bytes().splitlines() if s.strip()])
    status = 'WAITING_DATE' if not due else 'READY_FOR_SOURCE_REVIEW' if count == 60 else 'WAITING_RELEASE'
    return dict(status=status, reasons=[], declared_problem_count=observation.get('declared_problem_count'),
        observed_problem_count=count, pin_count=count,
        semantic=dict(migration_state='READY_FOR_SOURCE_REVIEW' if count == 60 else 'LEGACY_COUNT_REVIEW',
                      legacy_count_mismatch=True, candidate_ready=count == 60), **w.AUTH)


def test_predate_fetches_coherent_metadata_without_cohort(campaign):
    root, state = campaign
    http = HTTP()
    value = w.collect(root, state, now=w.NOT_BEFORE-1, getter=http)
    assert value['status'] == 'WAITING_DATE' and value['declared_problem_count'] == 60
    assert len(http.calls) == 5
    assert [r['label'] for r in value['evidence']] == ['api', 'tree', 'app', 'loader', 'head']
    assert not any(url.endswith('.jsonl') for url in http.calls)
    assert all(w.ordinary(root/r['path']) for r in value['evidence'])


def test_unchanged_revision_is_one_api_and_gate_crossing_rescans(campaign):
    root, state = campaign
    first = HTTP()
    w.collect(root, state, now=w.NOT_BEFORE-1, getter=first)
    second = HTTP()
    cached = w.collect(root, state, now=w.NOT_BEFORE-1, getter=second)
    assert cached['cache_reused'] and second.calls == [w.API]
    third = HTTP()
    due = w.collect(root, state, now=w.NOT_BEFORE, getter=third)
    assert not due['cache_reused'] and len(third.calls) == 6
    assert any(url.endswith('/benchmark_data_warmup.jsonl') for url in third.calls)
    assert any(r['label'] == 'cohort' for r in due['evidence'])


@pytest.mark.parametrize('count,status', [(15, 'WAITING_RELEASE'), (60, 'CANDIDATE_PRESENT')])
def test_due_actual_same_warmup_filename_classifies_by_independent_count(campaign, count, status):
    root, state = campaign
    value = w.poll(root, state, now=w.NOT_BEFORE, getter=HTTP(count), validator=local_validator)
    assert value['observation']['selected_file'] == 'benchmark_data_warmup.jsonl'
    assert value['observation']['status'] == status
    assert value['validation']['observed_problem_count'] == count
    assert value['completion_authority'] is False and value['task_states_changed'] is False


def test_revised_commit_with_cosmetic_app_change_does_not_rewake(campaign):
    root, state = campaign
    original = w.poll(root, state, now=w.NOT_BEFORE-10, getter=HTTP(), validator=local_validator)
    pointer = state/'outbox/current.json'
    before, inode = pointer.read_bytes(), pointer.stat().st_ino
    revised = HTTP(revision='b'*40)
    revised.app += b'\n# cosmetic official source revision\n'
    newer = w.poll(root, state, now=w.NOT_BEFORE-5, getter=revised, validator=local_validator)
    assert newer['stable_fingerprint'] == original['stable_fingerprint']
    assert newer['semantic_changed'] is False
    assert pointer.read_bytes() == before and pointer.stat().st_ino == inode


def test_repeat_and_return_to_historical_semantic_get_new_transition_id(campaign):
    root, state = campaign
    first = w.poll(root, state, now=w.NOT_BEFORE, getter=HTTP(), validator=local_validator)
    same = w.poll(root, state, now=w.NOT_BEFORE+1, getter=HTTP(), validator=local_validator)
    assert same['outbox'] == first['outbox'] and same['semantic_changed'] is False
    failing = HTTP(); failing.overrides[w.API] = TimeoutError('private network fixture')
    unavailable = w.poll(root, state, now=w.NOT_BEFORE+2, getter=failing, validator=local_validator)
    restored = w.poll(root, state, now=w.NOT_BEFORE+303, getter=HTTP(), validator=local_validator)
    assert unavailable['observation']['status'] == 'TRANSPORT_UNAVAILABLE'
    assert restored['stable_fingerprint'] == first['stable_fingerprint']
    assert restored['outbox']['event']['path'] != first['outbox']['event']['path']
    event = state/restored['outbox']['event']['path']
    assert w.digest(event.read_bytes()) == restored['outbox']['event']['sha256']


def test_moving_head_never_caches_a_mixed_snapshot(campaign):
    root, state = campaign
    http = HTTP(); http.head = 'b'*40
    value = w.collect(root, state, now=w.NOT_BEFORE, getter=http)
    assert value['status'] == 'TRANSPORT_UNAVAILABLE'
    assert value['reasons'] == ['HEAD_CHANGED_DURING_POLL']
    assert not (state/'collection-cache.json').exists()


@pytest.mark.parametrize('mutation', ['wrong_id', 'bad_revision', 'duplicate_tree', 'wrong_blob', 'wrong_size', 'link'])
def test_transport_schema_and_git_binding_refuse_review(campaign, mutation):
    root, state = campaign
    http = HTTP()
    if mutation in ['wrong_id', 'bad_revision']:
        raw = encoded(dict(id='foreign' if mutation == 'wrong_id' else w.REPO,
                           sha='oops' if mutation == 'bad_revision' else 'a'*40))
        http.overrides[w.API] = w.HTTPResult(200, {}, raw, w.API)
    else:
        url = w.API+'/tree/'+http.revision+'?recursive=true'
        rows = [dict(type='file', path=name, size=len(raw), oid=blob(raw)) for name, raw in
                [('app.py', http.app), ('benchmark.py', http.loader), (http.selected, http.cohort)]]
        if mutation == 'duplicate_tree': rows.append(rows[0])
        elif mutation == 'wrong_blob': rows[0]['oid'] = '0'*40
        elif mutation == 'wrong_size': rows[0]['size'] += 1
        else: rows[0]['type'] = 'symlink'
        http.overrides[url] = w.HTTPResult(200, {}, encoded(rows), url)
    value = w.collect(root, state, now=w.NOT_BEFORE, getter=http)
    assert value['status'] == 'REQUIRES_REVIEW'
    assert not any(r['label'] == 'cohort' for r in value['evidence'])


@pytest.mark.parametrize('value', ['http://huggingface.co/api/spaces/'+w.REPO,
    'https://huggingface.co.evil/api/spaces/'+w.REPO,
    'https://user:password@huggingface.co/api/spaces/'+w.REPO,
    'https://huggingface.co:444/api/spaces/'+w.REPO,
    'https://huggingface.co/api/spaces/'+w.REPO+'#fragment',
    'https://huggingface.co/spaces/'+w.REPO+'/raw/'+'a'*40+'/../outside'])
def test_strict_origin_scope_and_traversal(value):
    with pytest.raises(w.ReviewRequired): w.checked_url(value)


def test_redirect_rejected_before_follow_and_fake_redirect_explicit(campaign):
    request = w.urllib.request.Request(w.API)
    with pytest.raises(w.ReviewRequired, match='REDIRECT'):
        w.NoRedirect().redirect_request(request, None, 302, 'redirect', {}, 'https://evil.test/secret')
    root, state = campaign
    http = HTTP(); http.overrides[w.API] = w.HTTPResult(302, {'Location':'https://evil.test'}, b'', w.API)
    value = w.collect(root, state, now=w.NOT_BEFORE, getter=http)
    assert value['status'] == 'REQUIRES_REVIEW' and http.calls == [w.API]


@pytest.mark.parametrize('status', [429, 503, 404])
def test_http_retry_explicit_and_bounded(campaign, status):
    root, state = campaign
    http = HTTP(); http.overrides[w.API] = w.HTTPResult(status, {'Retry-After':'120'}, b'', w.API)
    value = w.collect(root, state, now=w.NOT_BEFORE, getter=http)
    assert value['status'] == 'TRANSPORT_UNAVAILABLE'
    assert value['retry_after_seconds'] == 120 and http.calls == [w.API]


def test_oversize_metadata_body_is_review_required(campaign):
    root, state = campaign
    http = HTTP(); http.overrides[w.API] = w.HTTPResult(200, {}, b'x'*(w.BOUNDS['api']+1), w.API)
    assert w.collect(root, state, now=w.NOT_BEFORE, getter=http)['status'] == 'REQUIRES_REVIEW'


@pytest.mark.parametrize('mutation', ['dynamic_count', 'date_changed', 'loader_changed'])
def test_unsupported_ast_and_changed_gate_never_fetch_cohort(campaign, mutation):
    root, state = campaign
    http = HTTP()
    if mutation == 'dynamic_count':http.app = http.app.replace(b'FULL_BENCH_SIZE = 60', b'FULL_BENCH_SIZE = 30+30')
    elif mutation == 'date_changed':http.app = http.app.replace(b'November 1, 2026', b'November 2, 2026')
    else:http.loader = http.loader.replace(b'Path(__file__).resolve().parent / "benchmark_data_warmup.jsonl"', b'Path("unreviewed.jsonl")')
    value = w.collect(root, state, now=w.NOT_BEFORE, getter=http)
    assert value['status'] == 'REQUIRES_REVIEW'
    assert not any(r['label'] == 'cohort' for r in value['evidence'])


def test_unknown_pagination_never_followed(campaign):
    root, state = campaign
    http = HTTP(); url = w.API+'/tree/'+http.revision+'?recursive=true'
    http.overrides[url] = w.HTTPResult(200, {'Link':'<https://evil.test/page>; rel="next"'}, b'[]', url)
    value = w.collect(root, state, now=w.NOT_BEFORE, getter=http)
    assert value['status'] == 'REQUIRES_REVIEW' and len(http.calls) == 2


def test_scope_and_cache_traversal_are_refused(campaign, tmp_path):
    root, state = campaign
    with pytest.raises(w.ReviewRequired):w.scope(root, tmp_path/'outside')
    outside = tmp_path/'outside';outside.mkdir()
    (root/'alias').symlink_to(outside, target_is_directory=True)
    with pytest.raises(w.ReviewRequired):w.scope(root, root/'alias/state')
    w.collect(root, state, now=w.NOT_BEFORE-1, getter=HTTP())
    cache = state/'collection-cache.json';x=json.loads(cache.read_text());x['evidence'][0]['path']='../outside'
    cache.write_text(json.dumps(x))
    http=HTTP();recovered=w.collect(root,state,now=w.NOT_BEFORE-1,getter=http)
    assert recovered['status']=='WAITING_DATE' and recovered.get('cache_diagnostic')
    assert len(http.calls)==5
    assert list((state/'history').glob('invalid-cache.*.json'))


def test_single_nonblocking_poll_lock_prevents_second_poll(campaign):
    root,state=campaign;w.scope(root,state)
    with w.poll_lock(state):
        with pytest.raises(w.AlreadyPolling):w.poll(root,state,now=w.NOT_BEFORE,getter=lambda *a,**k:pytest.fail('No HTTP under foreign lock'),validator=local_validator)


class PhaseDeadline(BaseException): pass


@pytest.mark.parametrize('control', [KeyboardInterrupt('control'),SystemExit(17),PhaseDeadline('phase'),InterruptedError('signal')])
def test_original_controls_propagate(campaign, control):
    root,state=campaign;http=HTTP();http.overrides[w.API]=control
    with pytest.raises(type(control))as caught:w.poll(root,state,now=w.NOT_BEFORE,getter=http,validator=local_validator)
    assert caught.value is control
    assert not(state/'outbox/current.json').exists()


def test_validator_cannot_grant_authority(campaign):
    root,state=campaign
    def validator(*args,**kwargs):return dict(local_validator(*args,**kwargs),proof_authority=True)
    with pytest.raises(w.ReviewRequired,match='AUTHORITY'):w.poll(root,state,now=w.NOT_BEFORE,getter=HTTP(),validator=validator)
    assert not(state/'outbox/current.json').exists()


def test_enospc_before_replace_preserves_status_bytes(campaign,monkeypatch):
    root,state=campaign;w.scope(root,state);path=state/'status.json';old=b'{"previous":true}\n';path.write_bytes(old);path.chmod(0o600)
    error=OSError(errno.ENOSPC,'private full volume')
    monkeypatch.setattr(w.os,'fsync',lambda fd:(_ for _ in()).throw(error))
    with pytest.raises(OSError)as caught:w.atomic_json(state,path,{'new':True})
    assert caught.value is error and path.read_bytes()==old


def test_postreplace_control_preserves_beforeimage_and_original_control(campaign,monkeypatch):
    root,state=campaign;w.scope(root,state);path=state/'status.json';old=b'{"previous":true}\n';path.write_bytes(old);path.chmod(0o600);control=PhaseDeadline('after commit');original=w.os.replace
    def replace(first,second):original(first,second);raise control
    monkeypatch.setattr(w.os,'replace',replace)
    with pytest.raises(PhaseDeadline)as caught:w.atomic_json(state,path,{'new':True})
    assert caught.value is control
    assert json.loads(path.read_text())=={'new':True}
    assert(state/'history'/('status.json.'+w.digest(old)+'.json')).read_bytes()==old


def test_owned0775_workspace_ancestors_accepted_without_chmod(campaign):
    root,_=campaign;parent=root/'data';parent.mkdir(mode=0o775);parent.chmod(0o775)
    state=parent/'private-watcher';value=w.collect(root,state,now=w.NOT_BEFORE-1,getter=HTTP())
    assert value['status']=='WAITING_DATE'
    assert parent.stat().st_mode & 0o777 == 0o775
    assert state.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('corruption',['fields','labels','malformed_json','wrong_revision_url'])
def test_invalid_optional_cache_refetches_and_retains_bad_bytes(campaign,corruption):
    root,state=campaign;w.collect(root,state,now=w.NOT_BEFORE-1,getter=HTTP());path=state/'collection-cache.json';data=json.loads(path.read_text())
    if corruption=='fields':data['fields']['proof_authority']=True
    elif corruption=='labels':data['evidence'][0]['label']=[]
    elif corruption=='wrong_revision_url':data['evidence'][0]['url']=data['evidence'][0]['url'].replace('a'*40,'b'*40)
    raw=b'{' if corruption=='malformed_json' else encoded(data);path.write_bytes(raw)
    http=HTTP();value=w.collect(root,state,now=w.NOT_BEFORE-1,getter=http)
    assert value['status']=='WAITING_DATE' and value['model_calls']==0 and value['proof_authority']is False
    assert value['cache_reused']is False and len(http.calls)==5
    assert(state/'history'/('invalid-cache.'+w.digest(raw)+'.json')).read_bytes()==raw
    again=HTTP();assert w.collect(root,state,now=w.NOT_BEFORE-1,getter=again)['cache_reused']
    assert again.calls==[w.API]


def test_descriptor_fence_detects_parent_replacement(campaign):
    root,state=campaign;w.scope(root,state)
    with pytest.raises(w.ReviewRequired,match='DIRECTORY_IDENTITY'):
        with w.directory_fence(root,state):
            state.rename(root/'saved-state');state.mkdir(mode=0o700)
            w.new_bytes(state/'escaped.raw',b'must not write')
    assert not(state/'escaped.raw').exists()


class Response:
    code=200
    headers={}
    def __init__(self,body=b'body',error=None,close_error=None,clock=None):
        self.body=body;self.error=error;self.close_error=close_error;self.closed=False;self.requests=[];self.timeouts=[];self.clock=clock
        self.fp=SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=self.timeouts.append)))
    def geturl(self):return w.API
    def read(self,*args):raise AssertionError('Buffered read may internally drip beyond deadline')
    def read1(self,size):
        self.requests.append(size)
        if self.error:raise self.error
        if self.clock is not None:
            timeout=self.timeouts[-1];self.clock[0]+=timeout
            if timeout<8:raise TimeoutError('bounded fake read1 socket deadline')
            return b'x'
        value,self.body=self.body[:size],self.body[size:];return value
    def close(self):
        self.closed=True
        if self.close_error:raise self.close_error


def fake_opener(monkeypatch,response):
    class Opener:
        def open(self,request,timeout):
            assert request.full_url==w.API and timeout<=8
            return response
    monkeypatch.setattr(w.urllib.request,'build_opener',lambda *args:Opener())


def test_default_http_uses_bounded_read1(monkeypatch):
    response=Response(b'correct bytes');fake_opener(monkeypatch,response)
    value=w.get_https(w.API,timeout=8,max_bytes=100,deadline=w.time.monotonic()+45)
    assert value.body==b'correct bytes' and response.closed
    assert all(0<n<=101 for n in response.requests)


def test_default_http_drip_cannot_reset_whole_poll_deadline(monkeypatch):
    clock=[0.0];response=Response(clock=clock);fake_opener(monkeypatch,response)
    monkeypatch.setattr(w.time,'monotonic',lambda:clock[0])
    with pytest.raises(w.TransportUnavailable):w.get_https(w.API,timeout=8,max_bytes=100,deadline=45)
    assert clock[0]<=45 and response.closed and response.timeouts[-1]<=5


@pytest.mark.parametrize('control',[KeyboardInterrupt('original'),SystemExit(29),PhaseDeadline('original'),InterruptedError('original')])
def test_original_http_control_survives_close_failure(monkeypatch,control):
    response=Response(error=control,close_error=OSError(errno.EIO,'close failure'));fake_opener(monkeypatch,response)
    with pytest.raises(type(control))as caught:w.get_https(w.API,timeout=8,max_bytes=100,deadline=w.time.monotonic()+45)
    assert caught.value is control and response.closed


@pytest.mark.parametrize('status,mapped',[('WAITING_OFFICIAL_FULL_COHORT','WAITING_RELEASE'),('METADATA_UNAVAILABLE','TRANSPORT_UNAVAILABLE')])
def test_independent_waiting_status_mapping(campaign,status,mapped):
    root,state=campaign
    def validate(*args,**kwargs):
        out=local_validator(*args,**kwargs);out['status']=status;return out
    result=w.poll(root,state,now=w.NOT_BEFORE,getter=HTTP(),validator=validate)
    assert result['observation']['status']==mapped and result['validation']['status']==status


def review_unknown(root,state,observation,*,now=None):
    return dict(status='REQUIRES_REVIEW',reasons=['unknown_official_source_schema'],
        declared_problem_count=None,observed_problem_count=None,pin_count=None,semantic={},**w.AUTH)


def test_unsupported_declared61_to62_rearms_even_validator_count_unknown(campaign):
    root,state=campaign
    first=HTTP();first.app=first.app.replace(b'FULL_BENCH_SIZE = 60',b'FULL_BENCH_SIZE = 61')
    a=w.poll(root,state,now=w.NOT_BEFORE-1,getter=first,validator=review_unknown)
    second=HTTP(revision='b'*40);second.app=second.app.replace(b'FULL_BENCH_SIZE = 60',b'FULL_BENCH_SIZE = 62')
    b=w.poll(root,state,now=w.NOT_BEFORE-1,getter=second,validator=review_unknown)
    assert a['observation']['declared_problem_count']==61 and b['observation']['declared_problem_count']==62
    assert a['validation']['declared_problem_count']is None
    assert a['stable_fingerprint']!=b['stable_fingerprint'] and b['semantic_changed']


def test_unsupported_loader_bytes_rearm_but_identical_bytes_new_revision_do_not(campaign):
    root,state=campaign
    def bad(revision,name):
        http=HTTP(revision=revision)
        http.loader=http.loader.replace(b'Path(__file__).resolve().parent / "benchmark_data_warmup.jsonl"',('Path('+repr(name)+')').encode())
        return http
    first=w.poll(root,state,now=w.NOT_BEFORE-1,getter=bad('a'*40,'A.jsonl'),validator=review_unknown)
    same=w.poll(root,state,now=w.NOT_BEFORE-1,getter=bad('b'*40,'A.jsonl'),validator=review_unknown)
    changed=w.poll(root,state,now=w.NOT_BEFORE-1,getter=bad('c'*40,'B.jsonl'),validator=review_unknown)
    assert first['observation']['status']=='REQUIRES_REVIEW'
    assert first['stable_fingerprint']==same['stable_fingerprint'] and not same['semantic_changed']
    assert changed['stable_fingerprint']!=first['stable_fingerprint'] and changed['semantic_changed']


def independent_validator():
    source=Path('/storage/hf_cache/jevops-release-validator-20261029/tools/validate_official_release_candidate_v1.py')
    spec=importlib.util.spec_from_file_location('independent_official_release_fixture_validator',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.validate_observation


@pytest.mark.parametrize('now,count,status,decision',[
    (w.NOT_BEFORE-1,15,'WAITING_DATE','WAITING_DATE'),
    (w.NOT_BEFORE,15,'WAITING_RELEASE','WAITING_OFFICIAL_FULL_COHORT'),
    (w.NOT_BEFORE,50,'WAITING_RELEASE','WAITING_OFFICIAL_FULL_COHORT'),
    (w.NOT_BEFORE,60,'CANDIDATE_PRESENT','READY_FOR_SOURCE_REVIEW')])
def test_real_independent_validator_primary_ast_and_same_filename_cohort(campaign,now,count,status,decision):
    root,state=campaign;http=HTTP(count)
    result=w.poll(root,state,now=now,getter=http,validator=independent_validator())
    assert result['observation']['status']==status,result['validation']
    assert result['validation']['status']==decision,result['validation']
    assert result['validation']['declared_problem_count']==60
    assert result['observation']['legacy_contract_problem_count']==50
    assert result['validation']['semantic']['legacy_count_mismatch']is True
    assert result['completion_authority']is False and result['validation']['completion_authority']is False
    if now<w.NOT_BEFORE:assert not any(url.endswith('.jsonl')for url in http.calls)
    else:assert any(url.endswith('benchmark_data_warmup.jsonl')for url in http.calls)
    again=HTTP(count);repeat=w.poll(root,state,now=now,getter=again,validator=independent_validator())
    assert again.calls==[w.API] and repeat['semantic_changed']is False


def test_urllib_wrapped_interrupted_control_preserved(campaign,monkeypatch):
    root,state=campaign;interrupted=InterruptedError('original interrupted syscall')
    http=HTTP();http.overrides[w.API]=w.urllib.error.URLError(interrupted)
    with pytest.raises(InterruptedError)as caught:w.collect(root,state,now=w.NOT_BEFORE,getter=http)
    assert caught.value is interrupted
    response=Response(error=w.urllib.error.URLError(interrupted),close_error=OSError(errno.EIO,'close'))
    fake_opener(monkeypatch,response)
    with pytest.raises(InterruptedError)as caught:w.get_https(w.API,timeout=8,max_bytes=100,deadline=w.time.monotonic()+45)
    assert caught.value is interrupted


@pytest.mark.parametrize('function',['new_bytes','atomic_json'])
def test_cleanup_control_has_priority_over_ordinary_filesystem_failure(campaign,monkeypatch,function):
    root,state=campaign;w.scope(root,state);control=PhaseDeadline('cleanup control');original_unlink=Path.unlink
    def fail_write(fd):raise OSError(errno.EIO,'ordinary write/fsync refusal')
    def unlink(path,*args,**kwargs):
        original_unlink(path,*args,**kwargs)
        if path.name.endswith('.tmp'):raise control
    monkeypatch.setattr(w.os,'fsync',fail_write);monkeypatch.setattr(Path,'unlink',unlink)
    with pytest.raises(PhaseDeadline)as caught:
        if function=='new_bytes':w.new_bytes(state/'evidence/example.raw',b'bytes')
        else:w.atomic_json(state,state/'status.json',{'value':True})
    assert caught.value is control


def test429_backoff_zero_http_pause_then_resume_and_retained_status(campaign):
    root,state=campaign;now=w.NOT_BEFORE-1000
    good=w.poll(root,state,now=now,getter=HTTP(),validator=local_validator)
    failing=HTTP();failing.overrides[w.API]=w.HTTPResult(429,{'Retry-After':'120'},b'',w.API)
    first=w.poll(root,state,now=now+1,getter=failing,validator=local_validator)
    assert now+121 <= first['observation']['transport_retry_at'] < now+122
    retained=first['last_verified_status'];assert w.digest((root/retained['path']).read_bytes())==retained['sha256']
    assert retained['status']=='WAITING_DATE' and retained['observed_at']==now
    paused=w.poll(root,state,now=now+100,getter=lambda *a,**k:pytest.fail('Server backoff forbids HTTP'),validator=local_validator)
    assert paused['observation']['requests_made']==0 and paused['observation']['backoff_cached']
    assert paused['observation']['observed_at']==now+1
    assert paused['observation']['status']=='TRANSPORT_UNAVAILABLE'
    assert paused['semantic_changed']is False and paused['outbox']==first['outbox']
    resumed=HTTP();after=w.poll(root,state,now=now+122,getter=resumed,validator=local_validator)
    assert resumed.calls==[w.API] and after['observation']['status']=='WAITING_DATE'
    assert after['stable_fingerprint']==good['stable_fingerprint']
    assert after['outbox']['event']['path']!=good['outbox']['event']['path']


def test_date_gate_does_not_bypass_server_backoff_then_full_rescan(campaign):
    root,state=campaign;w.poll(root,state,now=w.NOT_BEFORE-100,getter=HTTP(60),validator=independent_validator())
    failing=HTTP();failing.overrides[w.API]=w.HTTPResult(429,{'Retry-After':'300'},b'',w.API)
    first=w.poll(root,state,now=w.NOT_BEFORE-10,getter=failing,validator=independent_validator())
    paused=w.poll(root,state,now=w.NOT_BEFORE+1,getter=lambda *a,**k:pytest.fail('UTC boundary must respectserverbackoff'),validator=independent_validator())
    assert paused['observation']['observed_at']==w.NOT_BEFORE-10 and paused['observation']['requests_made']==0
    http=HTTP(60);due=w.poll(root,state,now=w.NOT_BEFORE+291,getter=http,validator=independent_validator())
    assert len(http.calls)==6 and any(url.endswith('.jsonl')for url in http.calls)
    assert due['observation']['status']=='CANDIDATE_PRESENT'


@pytest.mark.parametrize('seconds',[7200,172800])
def test_long_retry_after_honored_or_requires_explicit_review(campaign,seconds):
    root,state=campaign;now=w.NOT_BEFORE-1;http=HTTP();http.overrides[w.API]=w.HTTPResult(429,{'Retry-After':str(seconds)},b'',w.API)
    first=w.collect(root,state,now=now,getter=http)
    if seconds<=86400:
        assert first['status']=='TRANSPORT_UNAVAILABLE' and now+seconds <= first['transport_retry_at'] < now+seconds+1
        assert first['retry_after_seconds']==seconds
    else:
        assert first['status']=='REQUIRES_REVIEW' and first['automatic_retry_disabled']is True
    paused=w.collect(root,state,now=now+seconds-1,getter=lambda *a,**k:pytest.fail('No earlyretry'))
    assert paused['requests_made']==0


def test_expired_backoff_original_control_preserved_without_rewrite(campaign):
    root,state=campaign;now=w.NOT_BEFORE-1000;http=HTTP();http.overrides[w.API]=w.HTTPResult(429,{'Retry-After':'120'},b'',w.API)
    w.collect(root,state,now=now,getter=http);path=state/'transport-backoff.json';before=path.read_bytes();control=PhaseDeadline('originalphase')
    resumed=HTTP();resumed.overrides[w.API]=control
    with pytest.raises(PhaseDeadline)as caught:w.collect(root,state,now=now+121,getter=resumed)
    assert caught.value is control and path.read_bytes()==before


@pytest.mark.parametrize('use_date', [False, True])
def test_slow_response_does_not_shorten_server_retry_after(campaign, monkeypatch, use_date):
    from email.utils import formatdate
    root, state = campaign
    now = w.NOT_BEFORE-1000
    ticks = [100.0]
    monkeypatch.setattr(w.time, 'monotonic', lambda: ticks[0])
    def slow(url, **bounds):
        ticks[0] = 119.0
        value = formatdate(now+139, usegmt=True) if use_date else '120'
        return w.HTTPResult(429, {'Retry-After': value}, b'', url)
    first = w.collect(root, state, now=now, getter=slow)
    assert first['transport_retry_at'] == now+139
    paused = w.collect(root, state, now=now+121,
        getter=lambda *a, **k: pytest.fail('Response latency must not shorten backoff'))
    assert paused['requests_made'] == 0 and paused['backoff_cached']
    resumed = HTTP()
    after = w.collect(root, state, now=now+140, getter=resumed)
    assert after['status'] == 'WAITING_DATE' and resumed.calls


@pytest.mark.parametrize('number',[errno.ENOSPC,errno.EDQUOT])
def test_cli_reports_inspectable_storage_failure(campaign,monkeypatch,capsys,number):
    root,state=campaign;error=OSError(number,'private storage failure')
    monkeypatch.setattr(w,'poll',lambda *a,**k:(_ for _ in()).throw(error))
    assert w.main(['--repo-root',str(root),'--state-dir',str(state),'--once'])==75
    report=json.loads(capsys.readouterr().err)
    assert report['status']=='PERSISTENCE_UNAVAILABLE' and report['errno']==number
    assert report['status_snapshot_persisted']is False and report['completion_authority']is False
