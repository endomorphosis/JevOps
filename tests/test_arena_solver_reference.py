"""Manufactured nomination costs; never native Lean or official score evidence."""
from dataclasses import replace
from fractions import Fraction
import json

import pytest

from jevops import arena_solver as solver
from jevops.arena import Outcome, reference_tokens, source_hash
from jevops.lean import VersionPin
from jevops.solver_feedback import SolverEdit
from tests.test_arena_solver import CTX, PIN, STATEMENT, receipt
from tests.test_arena_pareto import factory

POLICY = 'discovery-reference-v1'
PREFIX = STATEMENT + ' := by\n'
ORIGINAL = PREFIX + '  simp only [' + ', '.join(f'p{i}' for i in range(50)) + ']\n'
SEED = PREFIX + '  simp only [a, b, c, d]\n'
SMALL = PREFIX + '  simp only [a, b]\n'
FAST = PREFIX + '  simp only [a, b, c, d, e]\n'


def run(monkeypatch, *, policy=POLICY, reference_raw=10000, seed_raw=8000,
        later_reference_raw=None, max_calls=3, rejected=None, validator=lambda _: None,
        original=ORIGINAL, pin=PIN, context=None):
    context = context or replace(CTX, reference_source=original,
        reference_length=reference_tokens(original, STATEMENT), reference_heartbeats=999999999)
    # Hold checked source exploration fixed to isolate nomination. The injected
    # transport and edits are deterministic fixtures, not claims about Lean.
    monkeypatch.setattr(solver, 'support_edits', lambda source, **kw: [
        SolverEdit(source_hash(SEED), len(PREFIX), len(SEED), text[len(PREFIX):], 'support-deletion')
        for text in (SMALL, FAST)] if source == SEED else [])
    monkeypatch.setattr(solver, 'query_sites', lambda *args: [])
    calls = []
    def verify(req):
        calls.append(req.source)
        result = receipt(req, raw={SEED:seed_raw, SMALL:10000, FAST:6000}[req.source],
                         outcome=Outcome.REJECTED if req.source == rejected else Outcome.VERIFIED)
        data = json.loads(result.observations_json)
        raw = reference_raw if req.source == SEED or later_reference_raw is None else later_reference_raw
        data['report'].update(reference_raw_heartbeats=raw, reference_heartbeats=raw//1000)
        return replace(result, observations_json=json.dumps(data))
    result = solver.discover_solver_frontier(context, SEED, pin, verify,
        context_validator=validator, evidence_mode='offline_fixture', mode='frontier-v1',
        draft_policy=policy, limits=solver.SolverLimits(max_calls=max_calls, max_states=3,
            max_sites=1, max_depth=1, max_drafts=1))
    return result, calls


def test_original_reference_normalization_reverses_seed_relative_ranking(monkeypatch):
    old, old_calls = run(monkeypatch, policy='discovery-aggregate-v1')
    new, new_calls = run(monkeypatch)
    assert old_calls == new_calls == [SEED, SMALL, FAST]
    assert old['frontier'] == new['frontier']
    assert old['drafts'][0]['source'] == SMALL
    assert new['drafts'][0]['source'] == FAST
    assert new['verifier_calls'] == 3 and new['cache_hits'] == 0
    assert not new['promoted'] and new['official_score'] is None
    assert new['plan']['draft_policy'] == POLICY
    nomination = new['nomination']
    assert nomination['reference_tokens'] == reference_tokens(ORIGINAL, STATEMENT)
    assert nomination['reference_raw_heartbeats'] == 10000  # never 999999999 or 8000
    assert nomination['reference_attempt'] == 0
    assert nomination['reference_request_id'] == new['attempts'][0]['receipt']['request_id']
    assert nomination['reference_source_sha256'] == source_hash(ORIGINAL)
    gains = {r['node_id']:Fraction(**r['normalized_sum']) for r in nomination['gains']}
    for node in new['frontier'][1:]:
        expected = (Fraction(reference_tokens(SEED, STATEMENT)-node['tokens'], nomination['reference_tokens'])
                    + Fraction(8000-node['raw_heartbeats'], 10000))
        assert gains[node['id']] == expected
    assert gains[1] < 0 < gains[2]


def test_all_nodes_share_seed_receipts_original_denominator(monkeypatch):
    same, _ = run(monkeypatch)
    varied, _ = run(monkeypatch, later_reference_raw=1000000)
    assert varied['nomination'] == same['nomination']
    assert varied['drafts'][0]['source'] == FAST
    assert varied['frontier'][1]['reference_raw_heartbeats'] == 1000000


@pytest.mark.parametrize('cap', [0, 1, 2, 3])
def test_reference_policy_does_not_add_calls_or_ignore_zero_budget(monkeypatch, cap):
    report, calls = run(monkeypatch, max_calls=cap)
    assert report['verifier_calls'] == len(calls) <= cap
    if cap < 3:
        assert not report['drafts']
    if cap == 0:
        assert report['nomination']['reference_raw_heartbeats'] is None
        assert report['nomination']['reference_request_id'] is None


def test_zero_reference_heartbeats_abstains_without_default(monkeypatch):
    report, calls = run(monkeypatch, reference_raw=0)
    assert len(calls) == 3 and len(report['frontier']) == 3
    assert not report['drafts']
    assert report['nomination']['reference_raw_heartbeats'] == 0
    assert report['nomination']['reason'] == 'missing_or_zero_reference_denominator'


def test_zero_reference_tokens_abstains_without_seed_or_published_fallback(monkeypatch):
    monkeypatch.setattr(solver, 'reference_tokens',
                        lambda src, stmt: 0 if src == ORIGINAL else reference_tokens(src, stmt))
    report, _ = run(monkeypatch)
    assert not report['drafts'] and report['nomination']['reference_tokens'] == 0


@pytest.mark.parametrize('raw', [True, -1, float('nan'), float('inf')])
def test_invalid_reference_cost_cannot_supply_a_denominator(monkeypatch, raw):
    report, calls = run(monkeypatch, reference_raw=raw)
    assert len(calls) == 1 and not report['frontier'] and not report['drafts']
    assert report['status'] == 'ERROR'


def test_rejected_candidate_cannot_win_nomination(monkeypatch):
    report, _ = run(monkeypatch, rejected=FAST)
    assert not report['drafts']
    assert [n['source'] for n in report['frontier']] == [SEED, SMALL]


def test_new_context_invalidates_nomination(monkeypatch):
    n = 0
    def changed(_):
        nonlocal n
        n += 1
        if n > 3:
            raise ValueError('changed dependency')
    report, _ = run(monkeypatch, validator=changed)
    assert not report['context_applicable'] and report['status'] == 'ERROR'
    assert not report['drafts'] and not report['nomination']['gains']


def test_secondary_pin_is_rejected_before_transport(monkeypatch):
    secondary = VersionPin('v4.27.0', 'b'*40)
    ctx = replace(CTX, versions=(PIN, secondary), dependency_digests=('a'*64, 'b'*64))
    with pytest.raises(ValueError, match='primary pin'):
        run(monkeypatch, context=ctx, pin=secondary)


def test_legacy_seed_policy_is_not_reinterpreted(monkeypatch):
    old, _ = run(monkeypatch, policy='discovery-aggregate-v1', reference_raw=0)
    assert old['drafts'][0]['source'] == SMALL and old['nomination'] is None
    assert 'normalization' not in old['plan']


@pytest.mark.parametrize('case', ['improves', 'loses_to_original', 'secondary_rejects', 'confirm_regresses'])
def test_reference_nominee_still_needs_fresh_two_control_all_pin_confirmation(monkeypatch, factory, case):
    from jevops.arena_pareto import run_selection
    from jevops.arena_trial import Candidate

    discovery, calls = run(monkeypatch)
    draft = discovery['drafts'][0]
    assert draft['source'] == FAST and len(calls) == 3
    assert set(draft) == {'name', 'label', 'source', 'provenance'}
    record = dict(name=CTX.problem, statement=STATEMENT, src=ORIGINAL,
        version_info=[{PIN.lean_tag:PIN.git_commit}, {'v4.27.0':'c'*40}])
    def cost(phase, payload, *_):
        source = payload['candidate']
        if source == ORIGINAL:
            return 1000 if case == 'loses_to_original' else 10000
        if source == SEED:
            return 8000
        return 9000 if case == 'confirm_regresses' and phase == 'confirm' else 6000
    def modify(phase, payload, data):
        if case == 'secondary_rejects' and payload['candidate'] == FAST and data['lean_version'] == '4.27.0':
            data['report'].update(outcome='REJECTED', reason='fixture_incompatible_pin')
    create = factory(cost=cost, modify=modify)
    create.two_pins = True
    result = run_selection(record, [Candidate(draft['label'], draft['source'], draft['provenance'])],
        create, incumbent=Candidate('incumbent', SEED, 'fixture'), max_calls=60,
        selection_objective='aggregate-local-v1', evidence_mode='offline_fixture')
    expected = {'improves':'FIXTURE_CONFIRMED', 'loses_to_original':'NO_IMPROVEMENT',
                'secondary_rejects':'NO_IMPROVEMENT', 'confirm_regresses':'UNCONFIRMED'}
    assert result['status'] == expected[case]
    assert len(create.calls) == result['verifier_invocations'] == (60 if case in
        ('improves', 'confirm_regresses') else 24)
    assert all(not result[p]['receipt_cache_enabled'] for p in ('screen', 'confirmation') if result[p])
    assert result['native_processes'] == 0 and result['recommended'] is None
    assert result['official_score'] is None and not result['promoted']
