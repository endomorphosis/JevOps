"""Whole-source checked exploration; fixtures never claim Lean success."""
from dataclasses import replace
import json

import pytest

from jevops.arena import (ArenaContext, ArenaEvaluator, Outcome, VerificationRequest,
                         VersionReceipt, reference_tokens, source_hash)
from jevops.arena_solver import MODES, SolverLimits, discover_solver_frontier, fixture_comparison
from jevops.lean import VersionPin
from jevops.solver_feedback import diagnostic_edits, query_sites, support_edits

STATEMENT = "theorem solver_control (n : Nat) : n + 0 = n"
ROOT = STATEMENT + " := by\n  simp [Nat.add_zero, Nat.add_zero]\n"
MID = STATEMENT + " := by\n  simp only [Nat.add_zero, Nat.zero_add]\n"
END = STATEMENT + " := by\n  simp only []\n"
PIN = VersionPin("v4.26.0", "a"*40)
CTX = ArenaContext("solver_control", STATEMENT, ROOT, reference_tokens(ROOT, STATEMENT), None,
    (PIN,), ("a"*64,), "fixture", "v1", "fixture-cost/v1",
    verifier_options_json='{"branch_order":"reference-first"}')


def receipt(request, *, raw=10000, messages=(), outcome=Outcome.VERIFIED):
    report = dict(type_preserved=True, target_absent_before=True, axioms=[], reference_axioms=[],
        raw_heartbeats=raw, heartbeats=raw//1000, reference_raw_heartbeats=10000,
        reference_heartbeats=10, diagnostics=list(messages))
    observations = dict(report=report, measurement=CTX.heartbeat_method, dependency_digest="a"*64,
                        lean_version="4.26.0", branch_order="reference-first")
    return VersionReceipt(request.request_id, source_hash(request.source), CTX.problem, outcome,
        True, 0, "'solver_control' depends on axioms: []", raw//1000,
        observations_json=json.dumps(observations))


def message(text, line=2, column=2):
    return dict(severity="information", fileName="ArenaCandidate.lean",
                pos=dict(line=line, column=column), message="Try this: " + text)


def fixture_verifier(request):
    base = request.source.replace("simp?", "simp")
    if base not in (ROOT, MID, END):
        return receipt(request, outcome=Outcome.REJECTED)
    messages = [message("simp only [Nat.add_zero, Nat.zero_add]")] if base == ROOT and "simp?" in request.source else []
    return receipt(request, raw={ROOT:10000, MID:7000, END:4000}[base], messages=messages)


def run(source=ROOT, verifier=fixture_verifier, mode="frontier-v1", validator=lambda _: None, **limits):
    return discover_solver_frontier(CTX, source, PIN, verifier, context_validator=validator,
        evidence_mode="offline_fixture", mode=mode, limits=SolverLimits(**limits))


def test_longer_faster_intermediate_is_explored_but_never_promoted():
    reports = {m: run(mode=m) for m in MODES}
    assert not reports["suggestions-v1"]["drafts"]
    assert not reports["minimize-v1"]["drafts"]
    result = reports["frontier-v1"]
    assert [n['source'] for n in result['frontier']] == [ROOT, MID, END]
    assert result['frontier'][1]['tokens'] > result['frontier'][0]['tokens']
    assert result['frontier'][1]['raw_heartbeats'] < result['frontier'][0]['raw_heartbeats']
    assert result['drafts'][0]['source'] == END
    assert result['incumbent_source'] == ROOT and not result['incumbent_changed']
    assert not result['proof_admitted'] and not result['promoted'] and result['official_score'] is None
    assert result['cache_hits'] == 0 and result['evidence_mode'] == 'offline_fixture'
    assert fixture_comparison()['synthetic_costs_not_Lean_measurements']


@pytest.mark.parametrize('location', ['', ' at *', ' at h h₂ ⊢'])
def test_support_minimization_keeps_required_premise_and_original_continuation(location):
    initial = STATEMENT + ' := by\n  simp only [keep, extra, extra]' + location + '\n  exact marker\n'
    calls = []
    def verify(req):
        calls.append(req.source)
        assert req.source.endswith('  exact marker\n')
        assert req.source.startswith(STATEMENT + ' := by\n')
        return receipt(req, outcome=Outcome.VERIFIED if 'keep' in req.source else Outcome.REJECTED)
    r = run(initial, verify, max_calls=24)
    assert any('simp only [keep]' + location + '\n' in n['source'] for n in r['frontier'])
    assert all('keep' in n['source'] for n in r['frontier'])
    assert len(calls) == len(set(calls)) == r['verifier_calls']
    assert r['omitted']['duplicate'] > 0


@pytest.mark.parametrize('limit', [0, 1, 2, 3, 4, 6])
def test_zero_and_exact_call_budgets_no_free_work(limit):
    calls = []
    def verify(req):
        calls.append(req)
        return fixture_verifier(req)
    r = run(verifier=verify, max_calls=limit)
    assert len(calls) == r['verifier_calls'] <= limit
    if limit < 4:
        assert not r['drafts']
    if limit == 0:
        assert not r['seed_checked'] and not calls and r['status'] == 'BUDGET_EXHAUSTED'


@pytest.mark.parametrize('field,value', [('max_calls',True),('max_calls',65),('max_states',0),
    ('max_depth',5),('max_sites',9),('max_proposals',-1),('max_source_bytes',float('nan')),
    ('max_frontier_bytes',0),('max_drafts',9)])
def test_invalid_limits(field,value):
    with pytest.raises(ValueError):
        SolverLimits(**{field:value})


def test_state_bytes_proposal_and_depth_limits_are_real():
    for limits in [dict(max_states=1),dict(max_frontier_bytes=len(ROOT.encode())),
                   dict(max_proposals=0),dict(max_depth=0)]:
        r = run(**limits)
        assert not r['drafts'] and len(r['frontier']) == 1 and r['truncated']
    with pytest.raises(ValueError):
        run(max_source_bytes=len(ROOT.encode())-1)


@pytest.mark.parametrize('failure', [Outcome.TIMEOUT,Outcome.UNAVAILABLE,Outcome.ERROR,Outcome.BUDGET_EXHAUSTED])
def test_transient_failure_is_explicit_not_retried_or_relabelled(failure):
    r = run(verifier=lambda req: receipt(req,outcome=failure))
    assert r['status'] == failure.value and not r['frontier'] and not r['drafts']
    assert r['verifier_calls'] == 1 and len(r['attempts']) == 1


@pytest.mark.parametrize('damage', ['flag','request','source','target','type','exit','axiom',
    'cost_bool','cost_nan','cost_negative','cost_units','measurement','dependency','version','order',
    'missing','axiom_expansion','diagnostic_overflow'])
def test_forged_or_malformed_evidence_never_enters_frontier(damage):
    def verify(req):
        r = receipt(req)
        if damage == 'flag': return {'theorem_ok':True,'raw_heartbeats':0}
        if damage == 'request': return replace(r,request_id='foreign')
        if damage == 'source': return replace(r,candidate_sha256='b'*64)
        if damage == 'target': return replace(r,target='another')
        if damage == 'type': return replace(r,type_preserved=False)
        if damage == 'exit': return replace(r,exit_code=1)
        if damage == 'axiom': return replace(r,axiom_output="'solver_control' depends on axioms: [sorryAx]")
        o=json.loads(r.observations_json)
        if damage.startswith('cost_'):
            o['report']['raw_heartbeats']={'cost_bool':True,'cost_nan':float('nan'),
                'cost_negative':-1,'cost_units':999}[damage]
        elif damage in ('measurement','dependency','version','order'):
            o[{'measurement':'measurement','dependency':'dependency_digest','version':'lean_version','order':'branch_order'}[damage]]='foreign'
        elif damage == 'missing': del o['report']['raw_heartbeats']
        elif damage == 'axiom_expansion': o['report']['axioms']=['propext']
        else: o['report']['diagnostics']=[{}]*257
        return replace(r,observations_json=json.dumps(o))
    r=run(verifier=verify)
    assert not r['frontier'] and not r['drafts'] and not r['seed_checked']


def test_live_context_invalidation_suppresses_drafts():
    calls=0
    def validator(req):
        nonlocal calls
        calls+=1
        if calls>4: raise ValueError('changed dependency epoch')
    r=run(validator=validator)
    assert r['status']=='ERROR' and not r['drafts'] and not r['context_applicable']


def test_site_and_draft_truncation_are_explicit():
    r=run(max_sites=0)
    assert r['truncated'] and r['omitted']['query_sites']==1
    assert r['verifier_calls']==1 and not r['drafts']
    r=run(MID,max_sites=0)
    assert r['truncated'] and r['omitted']['support_windows']==1
    r=run(max_drafts=0)
    assert r['truncated'] and r['omitted']['draft_limit']==1 and not r['drafts']


def test_typed_single_pin_boundary_rejects_foreign_context_before_work():
    evaluator=ArenaEvaluator(CTX,fixture_verifier,max_calls=3,evidence_mode='offline_fixture')
    for req in [VerificationRequest(replace(CTX,verifier_version='changed'),ROOT,PIN),
                VerificationRequest(CTX,ROOT,VersionPin('v4.27.0','b'*40))]:
        with pytest.raises(ValueError): evaluator.verify_request(req)
    assert evaluator.calls==0
    r=evaluator.verify_request(VerificationRequest(CTX,STATEMENT+' := by sorry',PIN))
    assert r.outcome==Outcome.REJECTED and evaluator.calls==0


def test_support_edits_are_scoped_bounded_and_stale_safe():
    edits=support_edits(MID)
    assert len(edits)==3 and edits[0].apply(MID)==END
    with pytest.raises(ValueError): edits[0].apply(MID+'\n')
    for tactic in ['simp only [(by exact h)]','simp only [f x, h]','simp only [a[0]]',
                   'simp only [a] -- comment','simp only ["a"]','simp only []',
                   'simp only ['+', '.join('a'+str(i) for i in range(33))+']']:
        assert not support_edits(STATEMENT+' := by\n  '+tactic+'\n')
    assert not support_edits(MID,max_sites=0)


@pytest.mark.parametrize('location', ['', ' at *', ' at ⊢', ' at h', ' at h h₂ ⊢', ' at h  h₂'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_support_deletions_preserve_locations_continuation_and_newlines(location, newline):
    prefix = STATEMENT + ' := by' + newline + '  constructor <;>' + newline
    line = '    simp only [a, ← b]' + location + newline
    tail = '  exact h' + newline
    source = prefix + line + tail
    edits = support_edits(source)
    assert len(edits) == 3
    for edit, support in zip(edits, ('[]', '[← b]', '[a]')):
        assert edit.start == len(prefix) and edit.end == len(prefix + line)
        assert edit.apply(source) == prefix + '    simp only ' + support + location + newline + tail
        with pytest.raises(ValueError, match='stale'):
            edit.apply(source + ' ')


@pytest.mark.parametrize('suffix', [' at * h', ' at (h)', ' at h; rfl', ' at * -- comment',
                                  ' at * <;> rfl', ' at', ' at h\th₂'])
def test_support_deletions_abstain_from_unrecognized_location_syntax(suffix):
    source = STATEMENT + ' := by\n  simp only [a, b]' + suffix + '\n'
    assert support_edits(source) == []


def test_archived_strata_support_list_is_not_silently_skipped():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    path = root / 'papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/candidate.json'
    source = json.loads(path.read_text())['source']
    edits = support_edits(source)
    assert len(edits) == 6
    assert all(e.replacement.endswith(' at *\n') for e in edits)
    assert all(e.apply(source).split('  case app', 1)[1] == source.split('  case app', 1)[1] for e in edits)


def test_straight_line_multiline_suggestion_retains_anchor():
    site=query_sites(ROOT)[0]
    edits=diagnostic_edits(ROOT,site,[message('simp only []\n  rfl')])
    assert len(edits)==1
    assert edits[0].apply(ROOT)==STATEMENT+' := by\n  simp only []\n  rfl\n'
    # This nomination might fail after its first line closes the goal; only
    # full replay can accept it. Parsing alone must not call it a proof.


@pytest.mark.parametrize('text', ['simp?','exact sorry','exact (by trivial)','simp; rfl',
    'simp\n    exact h','simp\nset_option maxHeartbeats 0','simp\n· rfl',
    'first | simp','simp\n'*9,'exact IO.println','simp'+' '*4096])
def test_unsupported_diagnostic_scripts_abstain(text):
    assert not diagnostic_edits(ROOT,query_sites(ROOT)[0],[message(text)])


@pytest.mark.parametrize('field,value',[('fileName','other.lean'),('severity','warning'),
                                      ('pos',{'line':3,'column':2})])
def test_foreign_diagnostic_anchor_is_not_an_edit(field,value):
    m=message('simp only []');m[field]=value
    assert not diagnostic_edits(ROOT,query_sites(ROOT)[0],[m])


def test_probe_success_cannot_admit_a_failing_replacement():
    def verify(req):
        r=fixture_verifier(req)
        return replace(r,outcome=Outcome.REJECTED) if req.source==MID else r
    r=run(verifier=verify)
    assert len(r['frontier'])==1 and not r['drafts']
    assert any(a['kind']=='solver-suggestion' for a in r['attempts'])
