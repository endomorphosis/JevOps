"""Bounded scheduling controls with manufactured costs, NOT Lean evidence."""
from dataclasses import replace

import pytest

from jevops.arena import Outcome, reference_tokens
from jevops.arena_solver import SolverLimits, discover_solver_frontier, fixture_comparison
from jevops.solver_feedback import support_edits
from tests.test_arena_solver import CTX, PIN, STATEMENT, message, receipt


ROOT = STATEMENT + ' := by\n  simp only [a, b, c, d]\n  simp [e]\n'
HINT = ROOT.replace('simp [e]', 'simp only [e, f]')
SHORT = HINT.replace('[a, b, c, d]', '[]')
CONTEXT = replace(CTX, reference_source=ROOT, reference_length=reference_tokens(ROOT, STATEMENT))


def run(mode='balanced-frontier-v1', *, hint_outcome=Outcome.VERIFIED,
        child_outcome=Outcome.VERIFIED, deletion_raw=12000, seed_raw=10000,
        draft_policy='discovery-dual-first-v1', **limits):
    costs = {ROOT:seed_raw, HINT:8000, SHORT:6000}
    costs.update({e.apply(ROOT):deletion_raw for e in support_edits(ROOT)})
    calls = []

    def verifier(req):
        calls.append(req.source)
        base = req.source.replace('simp?', 'simp')
        outcome = Outcome.VERIFIED if base in costs else Outcome.REJECTED
        if req.source == HINT:
            outcome = hint_outcome
        if req.source == SHORT:
            outcome = child_outcome
        hints = []
        if base == ROOT:
            if 'simp? only' in req.source:
                hints = [message('simp only [a, b, c, d]')]
            elif 'simp? [e]' in req.source:
                hints = [message('simp only [e, f]', line=3)]
        return receipt(req, raw=costs.get(base, 10000), messages=hints, outcome=outcome)

    defaults = dict(max_calls=8, max_states=4, max_depth=2, max_sites=2, max_drafts=1)
    defaults.update(limits)
    result = discover_solver_frontier(CONTEXT, ROOT, PIN, verifier,
        context_validator=lambda _:None, evidence_mode='offline_fixture', mode=mode,
        limits=SolverLimits(**defaults), draft_policy=draft_policy)
    return result, calls


def test_equal_budget_reaches_hint_child_before_sibling_slots_fill():
    old, old_calls = run('frontier-v1')
    new, calls = run()
    assert len(old_calls) == len(calls) == 8
    assert len(old['frontier']) == len(new['frontier']) == 4
    assert HINT not in old_calls and SHORT not in old_calls
    assert [n['source'] for n in new['frontier']] == [ROOT, ROOT.replace('[a, b, c, d]', '[]'), HINT, SHORT]
    assert new['frontier'][2]['tokens'] > new['frontier'][0]['tokens']
    assert new['frontier'][3]['parent'] == 2 and new['frontier'][3]['depth'] == 2
    assert new['drafts'][0]['source'] == SHORT
    assert old['drafts'][0]['source'] != SHORT
    assert len(calls) == len(set(calls))  # no second expansion/check on queued hint
    assert new['cache_hits'] == 0 and not new['promoted'] and not new['proof_admitted']
    assert new['plan']['draft_policy'] == old['plan']['draft_policy']
    again, again_calls = run()
    assert calls == again_calls and new['frontier'] == again['frontier']


def test_nomination_cost_is_only_a_heuristic_and_default_still_shortest():
    new, _ = run()
    shortest, _ = run(draft_policy='shortest-v1')
    assert new['frontier'] == shortest['frontier']
    assert new['drafts'][0]['source'] == SHORT
    assert shortest['drafts'][0]['source'] == ROOT.replace('[a, b, c, d]', '[]')
    assert not new['incumbent_changed'] and new['official_score'] is None
    assert set(fixture_comparison()['arms']) == {'suggestions-v1','minimize-v1','frontier-v1'}


@pytest.mark.parametrize('calls', range(9))
def test_zero_exact_budget_and_no_free_admission(calls):
    r, attempted = run(max_calls=calls)
    assert len(attempted) == r['verifier_calls'] <= calls
    for node in r['frontier']:
        assert r['attempts'][node['attempt']]['receipt']['outcome'] == Outcome.VERIFIED
    if calls < 5:
        assert HINT not in [n['source'] for n in r['frontier']]
    if calls < 6:
        assert SHORT not in [n['source'] for n in r['frontier']]


@pytest.mark.parametrize('states', range(1,5))
def test_state_cap_never_borrowed_for_preferred_family(states):
    r, _ = run(max_states=states)
    assert len(r['frontier']) <= states
    assert r['retained_source_bytes'] == sum(len(n['source'].encode()) for n in r['frontier'])


def test_byte_depth_site_and_proposal_limits_also_apply_to_hint_recursion():
    for limits in (dict(max_frontier_bytes=len(ROOT.encode())), dict(max_depth=0),
                   dict(max_sites=0), dict(max_proposals=0)):
        r, _ = run(**limits)
        assert len(r['frontier']) == 1 and not r['drafts'] and r['truncated']
    r, _ = run(max_depth=1)
    assert all(n['depth'] <= 1 for n in r['frontier'])
    assert SHORT not in [n['source'] for n in r['frontier']]


@pytest.mark.parametrize('outcome', [Outcome.REJECTED, Outcome.TIMEOUT, Outcome.UNAVAILABLE, Outcome.ERROR])
def test_verified_probe_does_not_admit_failed_or_unavailable_hint(outcome):
    r, attempted = run(hint_outcome=outcome)
    assert HINT in attempted and SHORT not in attempted
    assert HINT not in [n['source'] for n in r['frontier']]
    if outcome != Outcome.REJECTED:
        assert r['status'] == outcome.value
    else:
        assert len(r['frontier']) > 2  # remaining deletion family still works


def test_finite_budget_tradeoff_not_claimed_uniformly_better():
    # With just four calls, hint probes use resources that first-fit devotes to
    # deletions. The new policy is not a dominance or exhaustive-fairness claim.
    old, _ = run('frontier-v1', max_calls=4)
    new, _ = run(max_calls=4)
    assert len(old['frontier']) == 4 and len(new['frontier']) == 2


def test_independently_valid_edits_do_not_authorize_their_failed_composition():
    r, attempted = run(child_outcome=Outcome.REJECTED)
    sources = [n['source'] for n in r['frontier']]
    deletion = ROOT.replace('[a, b, c, d]', '[]')
    assert HINT in sources and deletion in sources
    assert SHORT in attempted and SHORT not in sources
    assert r['drafts'][0]['source'] == deletion
    assert any(a['kind'] == 'support-deletion' and a['receipt']['outcome'] == Outcome.REJECTED
               for a in r['attempts'])


def test_invalid_nomination_policy_rejected_before_calls():
    with pytest.raises(ValueError, match='draft policy'):
        run(draft_policy='trust-me')


def test_aggregate_nomination_can_rescue_checked_longer_hint_not_failed_composition():
    r, calls = run(child_outcome=Outcome.REJECTED, deletion_raw=20000,
                   draft_policy='discovery-aggregate-v1')
    assert r['drafts'][0]['source'] == HINT
    assert SHORT in calls and SHORT not in [n['source'] for n in r['frontier']]
    assert r['verifier_calls'] == 8 and r['official_score'] is None
    assert not r['proof_admitted'] and not r['promoted']
    legacy, legacy_calls = run(child_outcome=Outcome.REJECTED, deletion_raw=20000)
    assert legacy_calls == calls and legacy['frontier'] == r['frontier']
    assert legacy['drafts'][0]['source'] != HINT


@pytest.mark.parametrize('limit', [0, 1, 4, 5, 8])
def test_aggregate_nomination_keeps_call_caps(limit):
    r, calls = run(draft_policy='discovery-aggregate-v1', max_calls=limit)
    assert r['verifier_calls'] == len(calls) <= limit
    assert all(d['source'] in [n['source'] for n in r['frontier']] for d in r['drafts'])


def test_aggregate_nomination_zero_seed_denominator_abstains():
    r, _ = run(draft_policy='discovery-aggregate-v1', seed_raw=0)
    assert r['frontier'] and not r['drafts']
