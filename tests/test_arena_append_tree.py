"""Source-bound nominations only; all native cost/proof claims need fresh checks."""
import json

import pytest

from jevops import arena_compositions as compositions, arena_leaf_pilot as pilot
from jevops.arena_trial import Candidate, _pins

STATEMENT = 'theorem append_fixture (n : Nat) : True → n = n'
SOURCE = STATEMENT + ' := by\n  intros h\n  induction n <;>\n    simp only [Nat.add_zero, List.append_assoc]\n  exact h'


@pytest.mark.parametrize('ending', ['', '\n'])
@pytest.mark.parametrize('intro', ['intro', 'intros'])
@pytest.mark.parametrize('support', ['List.append_assoc', 'List.append_assoc, Nat.add_zero',
                                   'Nat.add_zero, List.append_assoc'])
def test_deletion_preserves_scope_continuation_and_statement(ending, intro, support):
    source = SOURCE.replace('intros', intro).replace('Nat.add_zero, List.append_assoc', support) + ending
    result = compositions.remove_prefix_append_assoc(source, STATEMENT)
    expected = ', '.join(s for s in support.split(', ') if s != 'List.append_assoc')
    assert result == source.replace('[' + support + ']', '[' + expected + ']', 1)
    assert compositions.remove_prefix_append_assoc(result, STATEMENT) is None


@pytest.mark.parametrize('old,new', [
    ('List.append_assoc', '← List.append_assoc'), ('List.append_assoc', '_root_.List.append_assoc'),
    ('List.append_assoc', '(List.append_assoc xs)'), ('List.append_assoc', 'List.append_assoc, List.append_assoc'),
    ('List.append_assoc', 'List.append_assoc\n'), ('simp only', 'simp'),
    (']\n', '] at *\n'), (']\n', '] at h ⊢\n'), (']\n', ']; assumption\n'),
    ('intros h', 'intros _'), ('intros h', 'intros h other'), ('intros h', 'intros by'),
    ('induction n', 'induction _'), ('induction n', 'cases n'),
    ('    simp', '  simp'), (' := by', ' := by\n  skip'), ('\n', '\r\n'),
    ('    simp', '\tsimp'), ('  exact h', '  exact h -- comment'),
    ('  exact h', '  sorry'),
])
def test_ambiguous_prefixes_abstain_without_editing_later_sites(old, new):
    source = SOURCE.replace(old, new) + '\n  simp only [List.append_assoc]'
    assert compositions.remove_prefix_append_assoc(source, STATEMENT) is None


def test_bounds_and_identity():
    assert compositions.remove_prefix_append_assoc(SOURCE, 'theorem other : True') is None
    assert compositions.remove_prefix_append_assoc(SOURCE + '\n' * 256, STATEMENT) is None
    assert compositions.remove_prefix_append_assoc(SOURCE + ' ' * 32768, STATEMENT) is None
    source = SOURCE.replace('Nat.add_zero', ', '.join(['Nat.add_zero'] * 32))
    assert compositions.remove_prefix_append_assoc(source, STATEMENT) is None


def test_partial_composition_is_not_emitted_when_tree_repair_abstains():
    record = dict(name='append_fixture', statement=STATEMENT, src=SOURCE)
    result = compositions.draft_batch(record, pilot.PROFILES['simp-prefix-append-tree'])
    assert len(result['drafts']) == 1
    assert [a['status'] for a in result['attempts']] == ['DRAFT', 'ABSTAINED']
    assert len(result['attempts'][1]['steps']) == 1
    assert not result['proof_verified'] and result['native_processes'] == 0


@pytest.fixture
def frozen():
    record, = [json.loads(line) for line in pilot.CORPUS.read_text().splitlines()
               if json.loads(line)['name'] == 'CallElimCorrect.extractedOldExprInVars']
    raw = json.loads((pilot.ROOT / 'papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/composition-0.json').read_text())
    return pilot.make_plan(record, Candidate(raw['label'], raw['source'], raw['provenance']),
        profile='simp-prefix-append-tree', selection_objective='aggregate-local-v1')


def test_real_trial_fixes_comparator_edits_objective_and_budget(frozen):
    assert frozen['drafts']['base_tokens'] == 172 and frozen['drafts']['reference_tokens'] == 222
    assert [a['tokens'] for a in frozen['drafts']['attempts']] == [170, 170]
    control, repair = frozen['drafts']['drafts']
    seed = frozen['incumbent']['source']
    assert control['source'] == seed.replace(', List.append_assoc', '', 1)
    assert repair['source'].split('  case ite ', 1)[0] == control['source'].split('  case ite ', 1)[0]
    assert repair['source'].split('  case eq ', 1)[1] == control['source'].split('  case eq ', 1)[1]
    assert '      apply List.Subset.app\n' in repair['source']
    assert '    apply eih ; assumption' in repair['source']
    assert frozen['selection']['incumbent_label'] == 'incumbent'
    assert frozen['selection']['screen']['planned_requests'] == 16
    assert frozen['selection']['confirmation_request_reserve'] == 18
    assert frozen['max_processes'] == 34
    assert frozen['selection_objective'] == 'aggregate-local-v1'
    assert not frozen['promoted'] and frozen['official_score'] is None


def test_left_tree_copies_identifiers_no_growth_or_native_work(frozen, monkeypatch):
    source = frozen['incumbent']['source'].replace('apply cih ;', "apply h' ;").replace('apply tih ;', 'apply β ;')
    statement = frozen['record']['statement']
    result = compositions.subset_triple_reconstruct(source, statement, strategy='left_nested')
    assert "apply h' ; assumption" in result and 'apply β ; assumption' in result
    assert compositions.reference_tokens(result, statement) == compositions.reference_tokens(source, statement)
    monkeypatch.setattr(compositions, 'reference_tokens', lambda s, t: 100 if s == source else 101)
    assert compositions.subset_triple_reconstruct(source, statement, strategy='left_nested') is None


@pytest.mark.parametrize('damage', ['budget', 'path', 'source', 'objective'])
def test_plan_mutation_rejected_before_work(frozen, tmp_path, damage):
    budget = 34
    if damage == 'budget': budget = 33
    elif damage == 'path': frozen['drafts']['paths'].reverse()
    elif damage == 'source': frozen['drafts']['drafts'][1]['source'] += '\n'
    else: frozen['selection_objective'] = 'strict-dual-v1'
    with pytest.raises(ValueError):
        pilot.run(frozen, bindings=dict.fromkeys(_pins(frozen['record'])), directory=tmp_path/'run',
            max_processes=budget, check_resources=lambda: pytest.fail('must reject before native work'))
    assert not (tmp_path/'run').exists()
