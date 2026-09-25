"""Exhaustive bounded single deletions, not Lean proofs or cost measurements."""
import json

import pytest

from jevops import arena_compositions as compositions, arena_leaf_pilot as pilot
from jevops.arena import source_hash
from jevops.arena_trial import Candidate, _pins

STATEMENT = 'theorem deletion_fixture (n : Nat) : True → n = n'
SOURCE = STATEMENT + ' := by\n  intros h\n  induction n <;>\n    simp only [a, b, c, d]\n  exact h'


@pytest.mark.parametrize('count,index', [(count, index) for count in range(1,5) for index in range(count)])
@pytest.mark.parametrize('ending', ['', '\n'])
def test_each_entry_is_independently_deleted_without_changing_the_continuation(count,index,ending):
    entries = ['a','b','c','d'][:count]
    source = SOURCE.replace('a, b, c, d', ', '.join(entries)) + ending
    result = compositions.remove_prefix_support_entry(source, STATEMENT, index=index)
    expected = ', '.join(entries[:index] + entries[index+1:])
    assert result == source.replace('[' + ', '.join(entries) + ']', '[' + expected + ']', 1)
    assert compositions.reference_tokens(result, STATEMENT) < compositions.reference_tokens(source, STATEMENT)


@pytest.mark.parametrize('index', [-1,4,32,True,False,1.0,None,'0',float('nan')])
def test_indices_are_strictly_bounded_integers(index):
    with pytest.raises(ValueError):
        compositions.remove_prefix_support_entry(SOURCE, STATEMENT, index=index)


@pytest.mark.parametrize('support', ['', 'a, a', 'a, b, c, d, e', '(f n)', 'a, b,', 'a,\nb'])
def test_unsupported_or_incomplete_neighborhoods_abstain_instead_of_truncating(support):
    source = SOURCE.replace('a, b, c, d', support)
    for index in range(4):
        assert compositions.remove_prefix_support_entry(source, STATEMENT, index=index) is None


@pytest.mark.parametrize('old,new', [
    ('intros h', 'intros _'), ('intros h', 'intros h other'), ('induction n', 'cases n'),
    ('induction n', 'induction _'), ('simp only', 'simp'), (']\n', '] at *\n'),
    (']\n', '] at h ⊢\n'), (']\n', '] <;> assumption\n'), ('    simp', '  simp'),
    (' := by', ' := by\n  skip'), ('\n', '\r\n'), ('    simp', '\tsimp'),
    ('  exact h', '  exact h -- comment'), ('  exact h', '  sorry'),
])
def test_unsupported_scope_or_prefix_cannot_fall_through_to_another_site(old,new):
    source = SOURCE.replace(old,new) + '\n  simp only [a, b]'
    assert compositions.remove_prefix_support_entry(source, STATEMENT, index=0) is None


def test_bounds_absent_index_and_legacy_named_deletion_compatibility():
    assert compositions.remove_prefix_support_entry(SOURCE, 'theorem other : True', index=0) is None
    assert compositions.remove_prefix_support_entry(SOURCE+'\n'*256, STATEMENT, index=0) is None
    assert compositions.remove_prefix_support_entry(SOURCE+' '*32768, STATEMENT, index=0) is None
    assert compositions.remove_prefix_support_entry(SOURCE.replace('a, b, c, d','a'), STATEMENT, index=1) is None
    source = SOURCE.replace('a, b, c, d','a, b, c, d, List.append_assoc')
    assert compositions.remove_prefix_append_assoc(source, STATEMENT) == SOURCE
    assert compositions.remove_prefix_support_entry(source, STATEMENT, index=0) is None


def test_modifier_entries_and_order_are_not_silently_changed():
    source = SOURCE.replace('a, b, c, d', '← Nat.add_zero, _root_.Nat.zero_add, h₁')
    result = compositions.remove_prefix_support_entry(source, STATEMENT, index=1)
    assert result == source.replace(', _root_.Nat.zero_add', '', 1)


def test_batch_caps_deduplication_and_each_path_has_the_same_source():
    record = dict(name='deletion_fixture', statement=STATEMENT, src=SOURCE)
    paths = pilot.PROFILES['simp-prefix-single-deletions']
    result = compositions.draft_batch(record, paths)
    assert len(result['drafts']) == 4
    assert all(a['steps'][0]['before_sha256'] == source_hash(SOURCE) for a in result['attempts'])
    assert not result['proof_verified'] and result['native_processes'] == 0
    assert not compositions.draft_batch(record,paths,cap=0)['drafts']
    assert len(compositions.draft_batch(record,paths,cap=1)['drafts']) == 1
    repeated = compositions.draft_batch(record,[paths[0],paths[0]])
    assert [a['status'] for a in repeated['attempts']] == ['DRAFT','DUPLICATE']


@pytest.fixture
def frozen():
    record, = [json.loads(line) for line in pilot.CORPUS.read_text().splitlines()
               if json.loads(line)['name']=='CallElimCorrect.extractedOldExprInVars']
    raw = json.loads((pilot.ROOT/'papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/composition-1.json').read_text())
    return pilot.make_plan(record,Candidate(raw['label'],raw['source'],raw['provenance']),
        profile='simp-prefix-single-deletions',selection_objective='aggregate-local-v1')


def test_real_plan_is_complete_and_preserves_all_repaired_cases(frozen):
    assert frozen['drafts']['base_tokens']==170 and frozen['drafts']['reference_tokens']==222
    assert [a['tokens'] for a in frozen['drafts']['attempts']]==[168]*4
    for draft in frozen['drafts']['drafts']:
        assert draft['source'].split('  case app ',1)[1]==frozen['incumbent']['source'].split('  case app ',1)[1]
    assert frozen['selection']['incumbent_label']=='incumbent'
    assert frozen['selection']['screen']['planned_requests']==24
    assert frozen['selection']['confirmation_request_reserve']==18
    assert frozen['max_processes']==42 and frozen['selection_objective']=='aggregate-local-v1'
    assert not frozen['promoted'] and frozen['official_score'] is None


@pytest.mark.parametrize('damage',['budget','path','source','objective'])
def test_plan_mutation_is_rejected_before_work(frozen,tmp_path,damage):
    budget = 42
    if damage=='budget': budget = 41
    elif damage=='path': frozen['drafts']['paths'].reverse()
    elif damage=='source': frozen['drafts']['drafts'][0]['source']+='\n'
    else: frozen['selection_objective']='strict-dual-v1'
    with pytest.raises(ValueError):
        pilot.run(frozen,bindings=dict.fromkeys(_pins(frozen['record'])),directory=tmp_path/'run',
            max_processes=budget,check_resources=lambda:pytest.fail('must reject before work'))
    assert not (tmp_path/'run').exists()


@pytest.fixture
def joint(frozen):
    raw = json.loads((pilot.ROOT/'papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/composition-2.json').read_text())
    return pilot.make_plan(frozen['record'],Candidate(raw['label'],raw['source'],raw['provenance']),
        profile='simp-prefix-drop-second',selection_objective='aggregate-local-v1')


@pytest.mark.parametrize('indices', [(2,1), (1,1)])
def test_joint_source_equals_both_deletions_with_correct_index_shifting(frozen,joint,indices):
    source = frozen['incumbent']['source']
    for index in indices:
        source = compositions.remove_prefix_support_entry(source, frozen['record']['statement'], index=index)
    draft, = joint['drafts']['drafts']
    assert draft['source']==source
    assert source==joint['incumbent']['source'].replace(', Imperative.HasVarsPure.getVars', '', 1)
    assert source.split('  case app ',1)[1]==joint['incumbent']['source'].split('  case app ',1)[1]
    assert source.startswith(joint['record']['statement'])
    assert 'simp only [extractOldExprVars, List.Subset.empty]' in source
    assert not joint['drafts']['proof_verified'] and joint['drafts']['native_processes']==0


def test_joint_trial_uses_current_incumbent_and_one_fixed_arm(joint):
    assert joint['drafts']['base_tokens']==168 and joint['drafts']['reference_tokens']==222
    assert joint['drafts']['paths']==[['simp_prefix_drop_1']]
    assert [a['tokens'] for a in joint['drafts']['attempts']]==[166]
    assert joint['selection']['incumbent_label']=='incumbent'
    assert joint['selection']['screen']['planned_requests']==12
    assert joint['selection']['confirmation_request_reserve']==18
    assert joint['max_processes']==30
    assert joint['selection_objective']=='aggregate-local-v1'
    assert not joint['promoted'] and joint['official_score'] is None


@pytest.mark.parametrize('damage',['budget','path','source','objective','incumbent'])
def test_joint_plan_cannot_change_between_planning_and_execution(joint,tmp_path,damage):
    budget = 30
    if damage=='budget': budget = 29
    elif damage=='path': joint['drafts']['paths'][0][0]='simp_prefix_drop_0'
    elif damage=='source': joint['drafts']['drafts'][0]['source']+='\n'
    elif damage=='incumbent': joint['incumbent']['source']+='\n'
    else: joint['selection_objective']='strict-dual-v1'
    with pytest.raises(ValueError):
        pilot.run(joint,bindings=dict.fromkeys(_pins(joint['record'])),directory=tmp_path/'run',
            max_processes=budget,check_resources=lambda:pytest.fail('must reject before work'))
    assert not (tmp_path/'run').exists()


def test_missing_second_entry_is_zero_work_not_a_different_deletion(joint,tmp_path,monkeypatch):
    # This source is an unverified fixture; no compilation result is asserted.
    source = joint['incumbent']['source'].replace(
        '[extractOldExprVars, Imperative.HasVarsPure.getVars, List.Subset.empty]', '[extractOldExprVars]')
    plan = pilot.make_plan(joint['record'],Candidate('fixture',source,'unverified missing-entry fixture'),
        profile='simp-prefix-drop-second')
    assert not plan['drafts']['drafts'] and plan['max_processes']==0
    assert plan['selection'] is None
    monkeypatch.setattr(pilot,'NativeLeanVerifier',lambda *a,**k:pytest.fail('must not invoke Lean'))
    report = pilot.run(plan,bindings=dict.fromkeys(_pins(plan['record'])),directory=tmp_path/'run',
        max_processes=0,check_resources=lambda:None)
    assert report['status']=='NO_CANDIDATE' and report['native_processes']==0
