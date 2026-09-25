"""Discovery has no authority over the existing fresh all-pin selector."""
import pytest

from jevops import arena_pareto as pareto, arena_local as local
from jevops.arena_solver import SolverLimits
from jevops.arena_trial import Candidate
from tests.test_arena_pareto import factory
from tests.test_arena_local import guard, PIN as LOCAL_PIN, RECORD as LOCAL_RECORD, stage
from tests.test_arena_solver import run, ROOT, STATEMENT, PIN


@pytest.mark.parametrize('case', ['improves', 'slower', 'one_pin_rejects', 'confirm_regresses'])
def test_discovery_drafts_require_fresh_strict_all_pin_selection(factory, case):
    discovery = run()
    draft = discovery['drafts'][0]
    assert set(draft) == {'name', 'label', 'source', 'provenance'}
    record = dict(name='solver_control', statement=STATEMENT, src=ROOT,
        version_info=[{PIN.lean_tag:PIN.git_commit}, {'v4.27.0':'c'*40}])
    def cost(phase, payload, *_):
        if payload['candidate'] == ROOT: return 10000
        return 20000 if case == 'slower' or case == 'confirm_regresses' and phase == 'confirm' else 5000
    def modify(phase, payload, data):
        if case == 'one_pin_rejects' and data['lean_version'] == '4.27.0' and payload['candidate'] != ROOT:
            data['report'].update(outcome='REJECTED', reason='fixture_incompatible_pin')
    create = factory(cost=cost, modify=modify)
    create.two_pins = True
    result = pareto.run_selection(record, [Candidate(draft['label'], draft['source'], draft['provenance'])],
        create, max_calls=40, selection_objective='strict-dual-v1', evidence_mode='offline_fixture')
    if case == 'improves':
        assert result['status'] == 'FIXTURE_CONFIRMED'
        assert len(create.calls) == result['verifier_invocations'] == 40
        assert create.phases == ['screen', 'confirm']
    elif case == 'confirm_regresses':
        assert result['status'] == 'UNCONFIRMED' and create.phases == ['screen', 'confirm']
    else:
        assert result['status'] == 'NO_IMPROVEMENT' and create.phases == ['screen']
    # No cached discovery receipt, no real-model/cost claim, no file promotion.
    assert all(not result[p]['receipt_cache_enabled'] for p in ('screen', 'confirmation') if result[p])
    assert result['native_processes'] == 0 and result['recommended'] is None
    assert result['official_score'] is None and not result['promoted']
    assert discovery['incumbent_source'] == ROOT and not discovery['incumbent_changed']


def test_local_runtime_solver_reuses_guard_not_stage_fixtures(guard):
    rt = local.ArenaLocalRuntime(guard, LOCAL_RECORD, max_processes=8)
    # The guard has zero whole-proof processes; local-stage credit is irrelevant.
    report = rt.discover_solver(LOCAL_PIN, limits=SolverLimits(max_calls=1))
    assert report['status'] == 'BUDGET_EXHAUSTED' and not report['drafts']
    assert report['verifier_calls'] == 1 and guard.processes == rt.attempts == rt.reserved == 0
    fixture = local.ArenaLocalRuntime(guard, LOCAL_RECORD, runner=stage, max_processes=8)
    with pytest.raises(ValueError, match='fixtures'):
        fixture.discover_solver(LOCAL_PIN)
    with pytest.raises(ValueError):
        rt.discover_solver(LOCAL_PIN, source='')
