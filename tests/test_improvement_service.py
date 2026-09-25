"""Offline watcher invariants. Fakes never create native benchmark evidence."""
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from jevops.arena import content_hash
from jevops.improvement_service import (Config, Store, ImprovementHook, Service,
    parse_proposal, can_promote, storage_guard)
from jevops.improvement_lab import edit_sources, random_canaries, measure_checkpoint, checkpoint_gate


@pytest.fixture
def record():
    statement = 'theorem exampleProof (P : Prop) (h : P) : P'
    return {'name': 'exampleProof', 'statement': statement,
            'src': statement + ' := by\n  have a : P := h\n  exact a',
            'version_info': [{'v4.29.0': 'local-stdlib-smoke'}]}


@pytest.fixture
def config(tmp_path):
    return Config(str(tmp_path/'runtime'), 'a'*64, str(tmp_path/'state'), str(tmp_path/'volume.json'),
                  ('exampleProof',), ('privateProof',), str(tmp_path/'elan'), '/run/user/1000/docker.sock', 'sha256:'+'a'*64)


def test_budget_is_durable_and_configuration_cannot_silently_reset_it(tmp_path):
    store = Store(tmp_path, 'fixed')
    assert store.reserve('router_calls', 1, 2)
    store.db.close()
    store = Store(tmp_path, 'fixed')
    assert store.reserve('router_calls', 1, 2)
    assert not store.reserve('router_calls', 1, 2)
    assert store.get('router_calls') == 2
    with pytest.raises(ValueError, match='configuration changed'):
        Store(tmp_path, 'new')
    store.db.close()


def test_leader_lock_and_interrupted_attempts(tmp_path):
    first, second = Store(tmp_path, 'fixed'), Store(tmp_path, 'fixed')
    with first.db:
        first.db.execute("INSERT INTO attempts VALUES ('x','p','RUNNING','{}',NULL)")
    with first.leader():
        assert first.db.execute('SELECT status FROM attempts').fetchone()[0] == 'INTERRUPTED'
        with pytest.raises(BlockingIOError):
            with second.leader():
                pass
    first.db.close()
    second.db.close()


@pytest.mark.parametrize('change', [dict(router_budget=0), dict(native_budget=True), dict(interval_seconds=0),
    dict(development=('privateProof',)), dict(holdouts=()), dict(provider='deterministic'),
    dict(seed_reports=('../private.json',))])
def test_invalid_configuration_fails_closed(config, change):
    with pytest.raises(ValueError):
        replace(config, **change)


def test_outer_observations_are_lossless_hints_and_holdouts_excluded(config, monkeypatch, record):
    monkeypatch.setattr('jevops.improvement_service.storage_guard', lambda _c: None)
    hook = ImprovementHook(config)
    proof = record['src'] + '\n--' + 'x'*9000
    hook.on_step({'last_lake': [{'name': 'exampleProof', 'ok': True, 'source': proof,
                               'tokens': 1, 'maxHeartbeats': 0},
                              {'name': 'privateProof', 'source': 'secret'}]})
    hint = hook.store.recent('exampleProof')[0]
    assert hint['proof'] == proof
    assert hint['reported_raw_heartbeats'] is None  # A limit is not an observation.
    assert not hint['proof_verified'] and not hint['admission_source']
    assert hook.store.recent('privateProof') == []
    assert hook.candidates(record) == []
    hook.close()


def test_proposal_statement_changes_sorry_and_metric_claims_do_not_admit(record):
    raw = {'action': 'candidate', 'source': record['statement'] + ' := by exact h', 'verified': True, 'tokens': 0}
    _, candidate = parse_proposal(json.dumps(raw), record, None)
    assert candidate.source.endswith('exact h')
    for source in (record['src'], record['statement'] + ' := by sorry', 'theorem evil : True := by trivial'):
        with pytest.raises(ValueError):
            parse_proposal(json.dumps({**raw, 'source': source}), record, None)
    assert not can_promote({'status': 'VERIFIED', 'verified': True}, record, candidate, {})


def test_code_replacement_protects_scorer_and_applies_once():
    files = {'jevops/logic_refactor.py': 'def run():\n    return 1\n'}
    change = {'path': 'jevops/logic_refactor.py', 'old': 'return 1', 'new': 'return 2'}
    result = edit_sources(files, [change])
    assert result[change['path']].endswith('return 2\n')
    assert files[change['path']].endswith('return 1\n')
    for path in ('jevops/arena.py', 'jevops/improvement_worker.py', '../x.py', '/tmp/x.py', 'tests/test_gate.py'):
        with pytest.raises(ValueError):
            edit_sources(files, [{**change, 'path': path}])
    with pytest.raises(SyntaxError):
        edit_sources(files, [{**change, 'new': 'return )'}])
    with pytest.raises(ValueError):
        edit_sources(files, [change, change])


def test_real_training_changes_weights_and_frozen_ce_is_not_teacher_echo(record):
    from jevops.autoencoder import encode_lean_ir
    from jevops.autoencoder_training import LeanIRAutoencoder, coerce_training_example
    pair = {'input': record['src'], 'target': record['statement'] + ' := by exact h'}
    examples = [coerce_training_example({'text': pair['input'], 'target_ir': encode_lean_ir(pair['target'])})]
    model = LeanIRAutoencoder()
    before_state = model.to_dict()
    canaries = random_canaries('v4.29.0', seed='offline')
    before = measure_checkpoint(before_state, [pair], canaries)
    for _ in range(8):
        model.train_batch(examples)
    after = measure_checkpoint(model.to_dict(), [pair], canaries)
    assert before_state != model.to_dict()
    assert after['train']['cross_entropy'] < before['train']['cross_entropy']
    assert after['train']['cross_entropy'] > 0
    assert 0 <= after['canary']['cosine_similarity'] <= 1
    assert not checkpoint_gate(before, {**after, 'canary': {**after['canary'], 'cross_entropy': 1000}})


def test_storage_guard_does_not_delete_caches_when_headroom_low(config, tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    config = replace(config, state=str(tmp_path/'volume/state'))
    Path(config.volume_config).write_text('{}')
    volume = tmp_path/'volume'
    volume.mkdir()
    cache = volume/'keep.cache'
    cache.write_bytes(b'preserve')
    monkeypatch.setattr('jevops.arena_prepare.validate_volume', lambda _c: volume)
    monkeypatch.setattr(os, 'statvfs', lambda _p: SimpleNamespace(f_bavail=1, f_frsize=4096))
    with pytest.raises(RuntimeError, match='STORAGE_LIMIT'):
        storage_guard(config)
    assert cache.read_bytes() == b'preserve'


def test_policy_is_a_proposal_not_a_reused_pass(tmp_path, record):
    store = Store(tmp_path, 'fixed')
    candidate = {'label': 'verified-previously', 'source': record['statement']+' := by exact h', 'provenance': 'history'}
    with store.db:
        store.db.execute('INSERT INTO policy VALUES (?,?,?,?)',
                         (record['name'], content_hash(record), json.dumps(candidate), 'attempt'))
    assert 'fresh verification required' in store.incumbent(record).provenance
    with pytest.raises(ValueError, match='another problem/pin context'):
        store.incumbent({**record, 'src': record['src']+' '})
    store.db.close()


@pytest.fixture
def service(config, record, tmp_path, monkeypatch):
    from jevops.arena_snapshot import create_snapshot
    repo = tmp_path/'repo'
    (repo/'jevops').mkdir(parents=True)
    (repo/'jevops/stub.py').write_text('# offline snapshot fixture\n')
    corpus = tmp_path/'corpus.jsonl'
    private = {**record, 'name': 'privateProof'}
    corpus.write_text(json.dumps(record)+'\n'+json.dumps(private)+'\n')
    manifest = create_snapshot(repo, Path(config.runtime), ['jevops'], {'inputs/corpus.jsonl': corpus})
    config = replace(config, snapshot_sha256=manifest['manifest_sha256'])
    monkeypatch.setattr('jevops.improvement_service.storage_guard', lambda _c: None)
    class Experiments:
        calls = 0
        def ready(self, _record):
            pass
        def evaluate(self, _record, _candidate, _incumbent, _plan):
            self.calls += 1
            return {'status': 'INCOMPLETE', 'native_processes': 0, 'evidence_mode': 'offline_fixture'}
    def generate(_prompt):
        return json.dumps({'action': 'candidate', 'source': record['statement']+' := by exact h'})
    generate.last_route_attestation = {'verified': True, 'fixture': True}
    instance = Service(config, generate=generate, experiments=Experiments())
    monkeypatch.setattr(instance, 'prompt', lambda *_args: 'offline fixture prompt')
    yield instance
    instance.store.db.close()


def test_cycle_never_promotes_an_incomplete_experiment_and_deduplicates(service):
    with service.store.leader():
        assert service.cycle()['state'] == 'INCOMPLETE'
        assert service.cycle()['state'] == 'DUPLICATE_PROPOSAL'
    assert service.experiments.calls == 1
    assert service.store.get('native_requests') == 20
    assert service.store.db.execute('SELECT count(*) FROM policy').fetchone()[0] == 0


def test_live_router_requires_attestation_before_any_native_calls(service):
    service.generate.last_route_attestation = {'verified': False}
    assert service.cycle()['state'] == 'PROPOSAL_REJECTED'
    assert service.experiments.calls == 0


def test_stale_runtime_blocks_model_and_native_calls(service):
    path = Path(service.config.runtime)/'jevops/stub.py'
    path.chmod(0o644)  # Deliberate tampering with this test's own immutable copy.
    path.write_text('# changed\n')
    # verify_snapshot raises rather than returning a false success.
    with pytest.raises(ValueError):
        service.cycle()
    assert service.store.get('router_calls', 0) == 0
    assert service.experiments.calls == 0


def test_budget_exhaustion_prevents_further_model_calls(service):
    service.store.set('router_calls', service.config.router_budget)
    assert service.cycle()['state'] == 'BUDGET_EXHAUSTED'
    assert service.experiments.calls == 0


def test_new_canaries_are_separate_from_teachers():
    first, second = random_canaries('v4.29.0'), random_canaries('v4.29.0')
    assert {r['name'] for r in first}.isdisjoint(r['name'] for r in second)
    assert len(first) == 3


def test_nonfinite_checkpoint_metrics_and_vocabulary_drift_rejected(record):
    from jevops.autoencoder_training import LeanIRAutoencoder
    pair = {'input': record['src'], 'target': record['src']}
    state = LeanIRAutoencoder().to_dict()
    state['vocab'] = ['trivial', '<eos>']
    with pytest.raises(ValueError, match='vocabulary'):
        measure_checkpoint(state, [pair], random_canaries('v4.29.0'))


def test_model_adapter_preserves_exact_statement_including_scoped_open():
    from jevops.improvement_worker import proof_source
    statement = 'open Nat in\ntheorem unchanged (P : Prop) (h : P) : P'
    rendered = 'theorem unrelated_rt : False := by\n  exact h'
    assert proof_source(statement, rendered) == statement + ' := by\n  exact h'
    # Rebinding does not assert that the body proves the immutable statement.
    assert proof_source(statement, 'malformed') == 'malformed'


@pytest.mark.parametrize('genuine_update', [False, True])
def test_lab_uses_frozen_losses_and_keeps_canaries_out_of_training(service, record, monkeypatch, genuine_update):
    from types import SimpleNamespace
    from jevops.autoencoder import encode_lean_ir
    from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example
    from jevops.improvement_lab import Lab, PythonSandbox

    service.experiments.isolation = SimpleNamespace()
    teacher = {'input': record['src'], 'target': record['statement'] + ' := by exact h'}
    service.store.set('historical_teachers', [teacher])
    model = LeanIRAutoencoder(config=AutoencoderConfig(train_rewrite_policy=True))
    example = coerce_training_example({'text': teacher['input'], 'target_ir': encode_lean_ir(teacher['target'])})
    model.prepare_rewrite_training([example])
    if genuine_update:
        for _ in range(8):
            model.train_batch([example])
    requests = []

    def worker(_self, request):
        requests.append(request)
        return {'checkpoint': model.to_dict(),
                'outputs': [{'name': r['name'], 'source': r['src']} for r in request['records']],
                'cross_entropy': 0, 'cosine_similarity': 1, 'gate_passed': True}

    monkeypatch.setattr(PythonSandbox, 'run', worker)
    artifact, candidate = Lab(service).prepare({'action': 'train', 'train_steps': 8}, record)
    metrics = service.store.get('last_training')
    assert metrics['scorer'] == 'frozen_host'
    assert metrics['after']['train']['cross_entropy'] > 0  # Worker claim ignored.
    assert requests[0]['teachers'] == [teacher]
    assert requests[0]['records'] == [record]
    assert service.store.get('deployed_checkpoint') is None
    assert service.store.get('deployed_code') is None
    if genuine_update:
        assert candidate is not None and artifact['status'] == 'LAB_PREPARED'
        assert len(requests) == 3
        assert requests[1]['records'] == requests[2]['records'] == artifact['canaries']
        assert all(r['teachers'] == [] and r['train_steps'] == 0 for r in requests[1:])
        assert all(r['name'] != record['name'] for r in artifact['canaries'])
    else:
        assert candidate is None and artifact['status'] == 'TRAINING_GATE_REJECTED'
        assert len(requests) == 1


def test_generation_deployment_participates_in_policy_transaction(service):
    from types import SimpleNamespace
    from jevops.improvement_lab import Lab

    service.experiments.isolation = SimpleNamespace()
    lab = Lab(service)
    artifact = {'code': {'jevops/tactics.py': '# isolated generation\n'}, 'checkpoint': None}
    with pytest.raises(RuntimeError, match='rollback'):
        with service.store.db:
            lab.deploy(artifact)
            assert service.store.get('deployed_code') == artifact['code']
            raise RuntimeError('rollback')
    assert service.store.get('deployed_code') is None
    # Retain the immutable artifact, but failed transactions cannot activate it.
    generations = list((service.store.directory/'generations').glob('*/jevops/tactics.py'))
    assert len(generations) == 1
    assert generations[0].read_text() == artifact['code']['jevops/tactics.py']
    assert generations[0].stat().st_mode & 0o222 == 0
    with service.store.db:
        lab.deploy(artifact)
    assert service.store.get('deployed_code') == artifact['code']


def test_training_actions_cannot_silently_ignore_rules(record):
    with pytest.raises(ValueError, match='choose one action'):
        parse_proposal(json.dumps({'action': 'train', 'rules': ['port_exact_hyp']}), record, None)


def test_compact_feedback_keeps_the_no_gain_diagnosis():
    from jevops.improvement_analysis import compact_observation
    row = compact_observation({'kind': 'lab_no_gain', 'source': 'x'*20000,
                              'before_tokens': 222, 'after_tokens': 222, 'reason': 'unchanged proof'})
    assert row['before_tokens'] == row['after_tokens'] == 222
    assert row['reason'] == 'unchanged proof' and 'source' not in row
    assert row['source_summary']['full_source_retained_in_ledger']


def test_analysis_menu_is_deduplicated_unverified_and_source_bound(record):
    from jevops.improvement_analysis import proposal_menu, menu_candidate
    menu = proposal_menu(record, None)
    assert menu and len(menu) <= 12
    assert len({r['id'] for r in menu}) == len(menu)
    assert all(r['saved_tokens'] > 0 and r['verified'] is False for r in menu)
    proposal = {'action': 'explore', 'proposal_id': menu[0]['id']}
    assert menu_candidate(proposal, menu).source == menu[0]['source']
    assert all(r['id'] != menu[0]['id'] for r in proposal_menu(record, None, tried=[menu[0]['id']]))
    with pytest.raises(ValueError):
        menu_candidate({**proposal, 'proposal_id': 'a'*64}, menu)


def test_unrepresentable_teacher_does_not_spend_training_work(service, record, monkeypatch):
    from types import SimpleNamespace
    from jevops.improvement_lab import Lab, PythonSandbox
    service.experiments.isolation = SimpleNamespace()
    source = record['statement'] + ' := by\n  have a : P := h\n' + '  skip\n'*12 + '  exact a'
    target = source.replace('  have a : P := h\n', '').replace('exact a', 'exact h')
    service.store.set('historical_teachers', [{'input': source, 'target': target}])
    monkeypatch.setattr(PythonSandbox, 'run', lambda *_: pytest.fail('unsupported grammar must abstain before worker'))
    result, candidate = Lab(service).prepare({'action': 'train'}, record)
    assert result['status'] == 'NO_SUPPORTED_REWRITE_TEACHERS' and candidate is None
    assert result['diagnostics']['supported_teachers'] == 0


def test_learned_editor_changes_a_renamed_proof_without_inference_teacher(record):
    from jevops.improvement_analysis import prepare_editor, teacher_examples, editor_metrics, editor_gate
    from jevops.autoencoder_training import AutoencoderConfig, LeanIRAutoencoder
    from jevops.autoencoder import decode_lean_ir
    pair = {'input': record['src'], 'target': record['statement'] + ' := by\n  exact h'}
    state, support = prepare_editor(None, [pair])
    assert support['supported_teachers'] == 1
    model = LeanIRAutoencoder.from_dict(state, config=AutoencoderConfig(train_rewrite_policy=True))
    before = editor_metrics(model.to_dict(), [pair])
    for _ in range(8):
        model.train_batch(teacher_examples([pair]))
    after = editor_metrics(model.to_dict(), [pair])
    assert editor_gate(before, after)
    unseen = record['src'].replace('exampleProof', 'newProof').replace('(h : P)', '(evidence : P)').replace(':= h', ':= evidence')
    snapshot = model.to_dict()
    predicted = model.predict_ir(unseen)
    assert 'exact evidence' in decode_lean_ir(predicted)
    assert predicted['rewrite_policy']['trace'] and not predicted['rewrite_policy']['teacher_used']
    assert model.to_dict() == snapshot
    assert not editor_gate(before, {**after, 'grammar_sha256': 'different'})
    assert not editor_gate(before, {**after, 'supported_teacher_ids': []})


def test_resume_requires_exact_budget_extension_and_preserves_native_budget(config):
    from jevops.improvement_bootstrap import validate_resume
    updated = replace(config, state=config.state+'-new', router_budget=config.router_budget+8)
    validate_resume(config, updated, 8)
    for extension in (0, 7, True, 33):
        with pytest.raises(ValueError):
            validate_resume(config, updated, extension)
    with pytest.raises(ValueError):
        validate_resume(config, replace(updated, native_budget=config.native_budget+20), 8)


def test_failed_native_samples_never_supply_training_teachers(record, monkeypatch):
    from jevops.improvement_service import collect_teachers
    shorter = record['statement'] + ' := by exact h'
    report = {'evidence_mode': 'local_lean', 'implementation_unchanged': True,
              'screen': {'record': record, 'arms': [{'label': 'control', 'source': record['src']},
                                                  {'label': 'draft', 'source': shorter}]}}
    costs = {'control': {'admissible': True, 'tokens': 12, 'axioms_by_version': {'v': []}},
             'draft': {'admissible': False, 'tokens': 2, 'axioms_by_version': {'v': []}}}
    monkeypatch.setattr('jevops.arena_pareto._costs', lambda _: costs)
    assert collect_teachers(report, record, 'offline', []) == []
    costs['draft']['admissible'] = True
    pairs = collect_teachers(report, record, 'offline', [])
    assert len(pairs) == 1 and pairs[0]['score_claim'] is False
    assert collect_teachers(report, record, 'offline', pairs) == pairs
    costs['draft']['axioms_by_version']['v'] = ['sorryAx']
    assert collect_teachers(report, record, 'offline', []) == []
    assert collect_teachers({**report, 'evidence_mode': 'offline_fixture'}, record, 'offline', []) == []


def test_native_feedback_handles_missing_receipts_and_retains_compiler_errors():
    from jevops.improvement_service import feedback
    report = {'status': 'INCOMPLETE', 'screen': {'samples': [
        {'status': 'UNAVAILABLE', 'reason': 'missing pin', 'receipt': None},
        {'status': 'REJECTED', 'receipt': {'observations_json': json.dumps(
            {'report': {'diagnostics': [{'message': 'unknown identifier h'}]}})}}]}}
    result = feedback(report)
    assert result['failures'][0]['reason'] == 'missing pin'
    assert result['failures'][1]['diagnostics'] == ['unknown identifier h']


def test_native_control_failure_stops_further_paid_proposals(service):
    service.experiments.evaluate = lambda *_: {
        'status': 'INCOMPLETE', 'evidence_mode': 'offline_fixture', 'native_processes': 0,
        'screen': {'samples': [{'label': 'control', 'status': 'ERROR', 'receipt': None, 'reason': 'permission denied'}]}}
    assert service.cycle()['state'] == 'INCOMPLETE'
    spent = service.store.get('router_calls')
    assert service.cycle()['state'] == 'ENVIRONMENT_FAILED'
    assert service.store.get('router_calls') == spent


def test_runtime_staging_uses_existing_reservation_and_verifies_frozen_bytes(tmp_path, monkeypatch):
    from jevops.arena_snapshot import create_snapshot
    from jevops.improvement_bootstrap import stage_runtime
    repo, run = tmp_path/'repo', tmp_path/'run'
    (repo/'jevops').mkdir(parents=True)
    (repo/'jevops/driver.py').write_text('# read-only fixture\n')
    snapshot = create_snapshot(repo, run/'runtime', ['jevops'])
    calls = []
    def stage(config, sources, **kwargs):
        calls.append((config, sources, kwargs))
        return {'search_paths': [str(run/'runtime')]}
    monkeypatch.setattr('jevops.improvement_bootstrap.stage_imports', stage)
    path, _ = stage_runtime({'existing_cap': True}, run, snapshot)
    assert path == run/'runtime'
    assert calls == [({'existing_cap': True}, (run/'runtime',),
                      {'name': 'run-runtime', 'max_bytes': 32_000_000, 'timeout': 120})]
    with pytest.raises(ValueError, match='manifest changed'):
        stage_runtime({}, run, {**snapshot, 'manifest_sha256': '0'*64})
