"""Syntax transport fixtures and archived diagnostics; not native proof evidence."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from jevops.arena_solver import SolverLimits, discover_solver_frontier
from jevops.solver_feedback import diagnostic_edits, query_sites, source_digest
from tests.test_arena_solver import CTX, PIN, ROOT, message, receipt


SOURCE = ('theorem span_control (ν : Nat) : 0 + ν = ν ∧ ν + 0 = ν := by\n'
          '  constructor <;>\n'
          '    simp [Nat.zero_add,\n'
          '          Nat.add_zero] at *\n')


def inventory(source, tactic='simp', start=None, end=None):
    """Manufactured parser observation; only native tests establish transport."""
    start = source.index(tactic) if start is None else start
    end = len(source.rstrip()) if end is None else end
    return dict(schema='jevops-lean-solver-spans/v1', status='CAPTURED',
        source_utf8_bytes=len(source.encode()), nodes_visited=30,
        spans=[dict(start_utf8=len(source[:start].encode()), end_utf8=len(source[:end].encode()),
                    tactic=tactic, syntax_kind='Lean.Parser.Tactic.simp')])


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_complete_native_span_preserves_combinator_location_and_utf8(newline):
    source = SOURCE.replace('\n', newline)
    site, = query_sites(source, inventory(source))
    assert site['line'] == 3 and site['column'] == 4
    assert site['span_method'] == 'lean-parser/v1'
    assert site['probe'] == source.replace('simp [', 'simp? [')
    assert site['original_line'].count('\n') == 2
    hints = [message('[apply] simp only [Nat.zero_add,\n    Nat.add_zero] at *', 3, 4),
             message('simp only [Nat.add_zero] at *', 3, 4)]
    edit, = diagnostic_edits(source, site, hints)
    assert edit.apply(source) == (source[:site['start']] +
        '    simp only [Nat.zero_add, Nat.add_zero] at *' + newline)
    with pytest.raises(ValueError, match='stale'):
        edit.apply(source + newline)


@pytest.mark.parametrize('tail', ['Nat.add_zero]\n', '] at *\n', 'Nat.add_zero\n'])
def test_legacy_adapter_never_edits_incomplete_multiline_support(tail):
    source = 'theorem t : True := by\n  simp [Nat.zero_add,\n    ' + tail
    assert query_sites(source) == []


@pytest.mark.parametrize('continuation', ['    at *\n', '  at *\n', '    using h\n'])
def test_fallback_abstains_on_unbound_continuation(continuation):
    assert not query_sites('theorem t : True := by\n  simp\n' + continuation)


@pytest.mark.parametrize('damage', ['hash', 'line', 'column', 'bool_column', 'source', 'start'])
def test_stale_or_forged_site_cannot_nominate_an_edit(damage):
    site, = query_sites(SOURCE, inventory(SOURCE))
    site.update({'hash':dict(source_sha256='f'*64), 'line':dict(line=4),
        'column':dict(column='4'), 'bool_column':dict(column=True),
        'source':dict(original_line='simp\n'), 'start':dict(start=0)}[damage])
    assert not diagnostic_edits(SOURCE, site, [message('simp only [] at *', 3, 4)])


@pytest.mark.parametrize('damage', ['bounds', 'bool', 'utf8', 'schema', 'size', 'kind',
                                  'status', 'row', 'overflow', 'partial'])
def test_malformed_native_inventory_fails_closed(damage):
    obs = inventory(SOURCE)
    if damage == 'bounds': obs['spans'][0]['end_utf8'] = len(SOURCE.encode()) + 1
    if damage == 'bool': obs['spans'][0]['start_utf8'] = True
    if damage == 'utf8': obs['spans'][0]['start_utf8'] = len(SOURCE[:SOURCE.index('ν')].encode()) + 1
    if damage == 'schema': obs['schema'] = 'unknown'
    if damage == 'size': obs['source_utf8_bytes'] -= 1
    if damage == 'kind': obs['spans'][0]['syntax_kind'] = 1
    if damage == 'status': obs['status'] = 'UNKNOWN'
    if damage == 'row': obs['spans'][0] = []
    if damage == 'overflow': obs['spans'] *= 257
    if damage == 'partial': obs['status'] = 'UNSUPPORTED'
    with pytest.raises(ValueError, match='solver'):
        query_sites(SOURCE, obs)


def test_missing_capability_does_not_fall_back_to_unsafe_edits():
    obs = inventory(SOURCE)
    obs.update(status='UNSUPPORTED', spans=[])
    assert not query_sites(SOURCE, obs)
    obs = inventory(SOURCE)
    obs['spans'] *= 2
    assert len(query_sites(SOURCE, obs)) == 1


@pytest.mark.parametrize('hint', ['rfl', 'simp only [a] at h', 'simp only [f x] at *',
                                'simp only [] at *\nexact h', 'simp only [a' + ' '*4096])
def test_multiple_goal_hints_are_not_individual_alternatives(hint):
    site, = query_sites(SOURCE, inventory(SOURCE))
    hints = [message('simp only [Nat.zero_add] at *', 3, 4), message(hint, 3, 4)]
    assert not diagnostic_edits(SOURCE, site, hints)


def test_parser_bound_site_does_not_flatten_multicommand_script():
    site, = query_sites(SOURCE, inventory(SOURCE))
    assert not diagnostic_edits(SOURCE, site, [message('simp\n    rfl', 3, 4)])


def test_union_observes_every_goal_beyond_old_four_suggestion_limit():
    site, = query_sites(SOURCE, inventory(SOURCE))
    hints = [message(f'simp only [h{i}] at *', 3, 4) for i in range(9)]
    edit, = diagnostic_edits(SOURCE, site, hints)
    assert edit.replacement == '    simp only [' + ', '.join(f'h{i}' for i in range(9)) + '] at *\n'
    assert not diagnostic_edits(SOURCE, site, hints * 29)  # no partial overflow


def test_archived_strata_hints_merge_into_one_complete_unverified_proposal():
    base = Path(__file__).resolve().parents[1] / 'papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24'
    archive = json.loads((base/'discovery-aggregate.json').read_text())
    source = archive['frontier'][0]['source']
    start = source.index('simp [')
    end = source.index('\n', source.index('] at *', start))
    obs = inventory(source, start=start, end=end)
    site, = query_sites(source, obs)
    assert site['line'] == 8
    # Transport is synthetic; the messages are historical native observations.
    hints = json.loads(archive['attempts'][1]['receipt']['observations_json'])['report']['diagnostics']
    edit, = diagnostic_edits(source, site, hints)
    candidate = edit.apply(source)
    assert 'List.Subset.empty' in edit.replacement and 'List.append_assoc' in edit.replacement
    assert candidate[:edit.start] == source[:edit.start]
    assert candidate[edit.start+len(edit.replacement):] == source[edit.end:]
    assert candidate.splitlines()[8].startswith('  case app')
    assert not any(s['line'] == 8 for s in query_sites(source))  # no syntax, no partial edit


def test_inventory_is_revalidated_at_receipt_boundary():
    def verify(req):
        r = receipt(req)
        data = json.loads(r.observations_json)
        data['report']['solver_spans'] = inventory(ROOT)
        data['report']['solver_spans']['source_utf8_bytes'] += 1
        return replace(r, observations_json=json.dumps(data))
    report = discover_solver_frontier(CTX, ROOT, PIN, verify, context_validator=lambda _: None,
        evidence_mode='offline_fixture', limits=SolverLimits(max_calls=3))
    assert report['status'] == 'ERROR' and not report['frontier']
    assert report['verifier_calls'] == 1


def test_union_is_only_a_proposal_and_failed_replay_cannot_join_frontier():
    from jevops.arena import Outcome, reference_tokens
    source = SOURCE.replace('span_control', 'solver_control')
    statement = source.split(' := by')[0]
    ctx = replace(CTX, statement=statement, reference_source=source,
                  reference_length=reference_tokens(source, statement))
    def verify(req):
        base = req.source.replace('simp?', 'simp')
        hints = ([message('simp only [Nat.zero_add] at *', 3, 4),
                  message('simp only [Nat.add_zero] at *', 3, 4)]
                 if 'simp?' in req.source else [])
        r = receipt(req, messages=hints,
            outcome=Outcome.VERIFIED if base == source else Outcome.REJECTED)
        if req.source == source:
            data = json.loads(r.observations_json)
            data['report']['solver_spans'] = inventory(source)
            r = replace(r, observations_json=json.dumps(data))
        return r
    report = discover_solver_frontier(ctx, source, PIN, verify, context_validator=lambda _: None,
        evidence_mode='offline_fixture', limits=SolverLimits(max_calls=3, max_depth=1, max_sites=1))
    assert report['seed_checked'] and len(report['frontier']) == 1
    assert not report['drafts'] and report['verifier_calls'] == 3
    assert report['attempts'][-1]['receipt']['outcome'] == 'REJECTED'
    assert report['edits'][-1]['edit']['kind'] == 'solver-suggestion'
    assert not report['edits'][-1]['retained']


def test_archived_native_repair_is_consistent_not_score_confirmation():
    # Historical bookkeeping only; this test never launches Lean or admits a proof.
    base = Path(__file__).resolve().parents[1] / 'papers/completion/lean_refactor_arena/evidence/solver-span-repair-2026-09-24'
    report = json.loads((base/'strata-span-replay.json').read_text())
    assert report['status'] == 'COMPLETE' and report['verifier_calls'] == 3
    parent, child = report['frontier']
    assert (parent['tokens'], child['tokens']) == (185, 190)
    assert child['raw_heartbeats'] < parent['raw_heartbeats']
    assert all(a['receipt']['outcome'] == 'VERIFIED' for a in report['attempts'])
    site = query_sites(parent['source'], parent['solver_spans'])[0]
    diagnostics = json.loads(report['attempts'][1]['receipt']['observations_json'])['report']['diagnostics']
    edit, = diagnostic_edits(parent['source'], site, diagnostics)
    assert edit.apply(parent['source']) == child['source']
    assert not report['drafts'] and not report['promoted'] and report['official_score'] is None
