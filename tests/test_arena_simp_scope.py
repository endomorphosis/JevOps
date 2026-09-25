"""Scope nominations and frozen plans; no Lean, models or proof authority."""
import json

import pytest

from jevops.arena import source_hash
from jevops.arena_compositions import draft_batch, narrow_simp_prefix
from jevops import arena_leaf_pilot as pilot
from jevops.arena_trial import Candidate, _pins

STATEMENT = 'theorem scope_fixture (n : Nat) : True → n = n'
SOURCE = STATEMENT + ' := by\n  intros h\n  induction n <;>\n    simp only [Nat.add_zero, Nat.zero_add] at *\n  exact h'


@pytest.mark.parametrize('scope,suffix', [('goal', ''), ('introduced_goal', ' at h ⊢')])
@pytest.mark.parametrize('ending', ['', '\n'])
@pytest.mark.parametrize('intro', ['intro', 'intros'])
def test_only_location_changes_and_unverified_continuation_is_preserved(scope,suffix,ending,intro):
    # This fixture deliberately makes no claim of validity of `exact h`.
    source = SOURCE.replace('intros h', intro + ' h') + ending
    result = narrow_simp_prefix(source, STATEMENT, scope=scope)
    assert result == source.replace(' at *', suffix, 1)
    assert result[:len(STATEMENT)] == STATEMENT
    assert result.split('\n  exact h')[1] == ending
    assert narrow_simp_prefix(result, STATEMENT, scope=scope) is None


@pytest.mark.parametrize('name', ['Hnorm', 'h₁', 'δ', "h'"])
def test_introduced_identifier_is_copied_not_guessed(name):
    source = SOURCE.replace('intros h', 'intros ' + name)
    assert ' at ' + name + ' ⊢' in narrow_simp_prefix(source, STATEMENT, scope='introduced_goal')


@pytest.mark.parametrize('old,new', [
    ('intros h', 'intros h other'), ('intros h', 'intro'), ('intros h', 'intros _'),
    ('intros h', 'intros by'), ('intros h', 'intros «h»'), ('intros h', 'intro (h : True)'),
    ('induction n', 'induction _'), ('induction n', 'induction f n'),
    ('induction n <;>', 'induction n'), ('induction n <;>', 'cases n <;>'),
    ('    simp', '  simp'), ('simp only', 'simp'), ('simp only', 'grind only'),
    (' at *', ' at h'), (' at *', ''), (' at *', ' at * <;>'), (' at *', ' at *; assumption'),
    ('Nat.zero_add', '(Nat.zero_add n)'), ('Nat.zero_add', '\nNat.zero_add'),
    ('Nat.zero_add', 'Nat.zero_add] [Nat.add_zero'), (' at *', ' at * -- comment'),
    ('\n', '\r\n'), ('    simp', '\tsimp'), (' := by', ' := by\n  skip'),
    (' at *', ' at *\n  /- comment -/'), (' at *', ' at *\n  sorry'),
])
def test_unsupported_layouts_and_payloads_abstain(old,new):
    assert narrow_simp_prefix(SOURCE.replace(old,new), STATEMENT, scope='goal') is None


@pytest.mark.parametrize('scope', [None, True, [], 'all', 'goal; sorry'])
def test_scope_is_allowlisted(scope):
    with pytest.raises(ValueError): narrow_simp_prefix(SOURCE, STATEMENT, scope=scope)


def test_bounds_statement_identity_and_support_limit():
    assert narrow_simp_prefix(SOURCE, 'theorem other : True', scope='goal') is None
    assert narrow_simp_prefix(SOURCE + '\n' * 256, STATEMENT, scope='goal') is None
    assert narrow_simp_prefix(SOURCE + ' ' * 32768, STATEMENT, scope='goal') is None
    source = SOURCE.replace('Nat.add_zero, Nat.zero_add', ', '.join(['Nat.zero_add'] * 33))
    assert narrow_simp_prefix(source, STATEMENT, scope='goal') is None


def test_batch_records_source_identity_and_helper_dependencies_without_admission():
    record = dict(name='scope_fixture', statement=STATEMENT, src=SOURCE)
    batch = draft_batch(record, [['simp_prefix_goal'], ['simp_prefix_goal'], ['simp_prefix_introduced_goal']])
    assert [a['status'] for a in batch['attempts']] == ['DRAFT', 'DUPLICATE', 'DRAFT']
    assert all(a['steps'][0]['before_sha256'] == source_hash(SOURCE) for a in batch['attempts'])
    assert {'solver_feedback.py','rewrite_policy.py'} <= batch['rule_sources_sha256'].keys()
    assert not batch['proof_verified'] and batch['native_processes'] == 0


@pytest.fixture
def frozen():
    record, = [json.loads(line) for line in pilot.CORPUS.read_text().splitlines()
               if json.loads(line)['name'] == 'CallElimCorrect.extractedOldExprInVars']
    raw = json.loads((pilot.ROOT / 'papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/solver-0.json').read_text())
    return pilot.make_plan(record, Candidate(raw['label'],raw['source'],raw['provenance']),
                           profile='simp-prefix-scope', selection_objective='aggregate-local-v1')


def test_real_source_trial_freezes_both_drafts_correct_baseline_and_full_budget(frozen):
    assert frozen['drafts']['base_tokens'] == 174 and frozen['drafts']['reference_tokens'] == 222
    assert [a['tokens'] for a in frozen['drafts']['attempts']] == [172, 175]
    assert frozen['selection']['incumbent_label'] == 'incumbent'
    assert frozen['selection']['screen']['planned_requests'] == 16
    assert frozen['selection']['confirmation_request_reserve'] == 18
    assert frozen['max_processes'] == 34
    assert frozen['selection']['selection_objective'] == 'aggregate-local-v1'
    assert not frozen['promoted'] and frozen['official_score'] is None
    for draft in frozen['drafts']['drafts']:
        assert draft['source'].split('  case app ',1)[1] == frozen['incumbent']['source'].split('  case app ',1)[1]
    legacy = pilot.make_plan(frozen['record'],Candidate(**frozen['incumbent']),profile='simp-prefix-scope')
    assert legacy['selection_objective'] == 'strict-dual-v1'


@pytest.mark.parametrize('damage', ['budget','path','objective','source'])
def test_frozen_plan_rejects_mutations_before_verifier_work(frozen,tmp_path,damage):
    budget = 34
    if damage == 'budget': budget = 33
    elif damage == 'path': frozen['drafts']['paths'].reverse()
    elif damage == 'objective': frozen['selection_objective'] = 'strict-dual-v1'
    else: frozen['drafts']['drafts'][0]['source'] += '\n'
    with pytest.raises(ValueError):
        pilot.run(frozen,bindings=dict.fromkeys(_pins(frozen['record'])),directory=tmp_path/'run',
                  max_processes=budget,check_resources=lambda:pytest.fail('invalid preflight'))
    assert not (tmp_path/'run').exists()
