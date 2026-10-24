"""Source-bound support nominations remain drafts until native confirmation."""
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lean_refactor_simp_pilot as m
import validate_lean_refactor_simp_pilot as v

def record():
    statement='theorem demo (n : Nat) : n + 0 = n'
    return {'statement':statement,'src':statement+' := by\n  simp only [Nat.add_zero, Nat.zero_add]\n'}

def test_actual_support_tools_generate_exact_shorter_edits_and_retain_theorem():
    r=record();drafts=m.proposals(r,r['src'],{'events':[]})
    assert len(drafts)==3
    for draft in drafts:
        edit=m.solver_feedback.SolverEdit(**draft['edit'])
        assert edit.apply(r['src'])==draft['source']
        assert draft['source'].startswith(r['statement'])
        assert m.arena.reference_tokens(draft['source'],r['statement'])<m.arena.reference_tokens(r['src'],r['statement'])

def test_stale_source_cannot_replay_support_deletion():
    r=record();draft=m.proposals(r,r['src'],{'events':[]})[0]
    with pytest.raises(ValueError):m.solver_feedback.SolverEdit(**draft['edit']).apply(r['src']+'\n')

def test_profile_hint_is_only_a_cost_prior_and_never_supplies_offsets():
    r=record();base=m.proposals(r,r['src'],{'events':[]})
    ranked=m.proposals(r,r['src'],{'events':[{'syntax_kind':'Lean.Parser.Tactic.simp',
        'hint':'simp only [Nat.add_zero, Nat.zero_add]','inclusive_raw':1000}]})
    assert [d['source'] for d in ranked]==[d['source'] for d in base]
    assert all(d['cost_prior_raw']==1000 for d in ranked)
    assert [d['edit'] for d in base]==[d['edit'] for d in ranked]

@pytest.mark.parametrize('status',['NO_SHORTER_WINNER','BLOCKED_NATIVE_PROFILE','RUNNING','CONFIRMATION_FAILED'])
def test_negative_or_partial_experiment_cannot_complete_ticket(status):
    records=m.c.module(ROOT,'lean_refactor_project_readiness.py').records()
    target=next(r for r in records if r['name']==m.TARGET)
    pin=next(iter(target['version_info'][0].items()))
    with pytest.raises(ValueError,match='not independently confirmed'):
        v.validate(ROOT,{'schema':m.SCHEMA,'target':m.TARGET,'pin':{'lean_tag':pin[0],'git_commit':pin[1]},'status':status})
