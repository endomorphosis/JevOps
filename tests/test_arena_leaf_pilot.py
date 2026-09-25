"""Frozen pilot contracts; native results are separately generated artifacts."""
import json

import pytest

from jevops import arena_leaf_pilot as pilot
from jevops.arena import content_hash
from jevops.arena_trial import Candidate, _pins

pytestmark = pytest.mark.no_seal(reason="fresh source-bound pilot planning")


@pytest.fixture
def plan():
    records = [json.loads(line) for line in pilot.CORPUS.read_text().splitlines() if line.strip()]
    record = next(r for r in records if r["name"] == "CallElimCorrect.extractedOldExprInVars")
    path = pilot.ROOT / "papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/historical-seed.json"
    raw = json.loads(path.read_text())
    return pilot.make_plan(record, Candidate(raw["label"], raw["source"], raw["provenance"]))


def test_real_incumbent_frozen_batch_counts_and_confirmation_budget(plan):
    assert plan["drafts"]["reference_tokens"] == 222
    assert plan["drafts"]["base_tokens"] == 185
    assert [a["tokens"] for a in plan["drafts"]["attempts"]] == [184, 176]
    assert plan["max_processes"] == 34
    assert plan["selection"]["screen"]["planned_requests"] == 16
    assert plan["selection"]["confirmation_request_reserve"] == 18
    assert plan["selection"]["selection_objective"] == "strict-dual-v1"
    assert plan["selection"]["heartbeat_noise_floor_raw"] == 100
    assert not plan["training_enabled"] and not plan["drafts"]["proof_verified"]
    assert plan == pilot.make_plan(plan["record"], Candidate(**plan["incumbent"]))


def test_subset_profile_freezes_directions_and_joint_candidate(plan):
    subset = pilot.make_plan(plan["record"], Candidate(**plan["incumbent"]), profile="subset-append")
    assert subset["profile"] == "subset-append" and subset["plan_sha256"] != plan["plan_sha256"]
    assert subset["drafts"]["base_tokens"] == 185 and subset["drafts"]["reference_tokens"] == 222
    assert [a["tokens"] for a in subset["drafts"]["attempts"]] == [183, 183, 181]
    assert subset["max_processes"] == 38
    assert subset["selection"]["screen"]["planned_requests"] == 20
    assert subset["selection"]["confirmation_request_reserve"] == 18
    assert len(subset["drafts"]["drafts"]) == 3
    with pytest.raises(ValueError):
        pilot.make_plan(plan["record"], Candidate(**plan["incumbent"]), profile="custom")


@pytest.fixture
def nested_plan(plan):
    seed = Candidate(**plan["incumbent"])
    # Reconstruct the 177-token nomination using two bounded compositions;
    # neither generated drafts nor archived results confer proof authority.
    for _ in range(2):
        batch = pilot.make_plan(plan["record"], seed, profile="subset-append")
        draft = batch["drafts"]["drafts"][2]
        seed = Candidate(draft["label"], draft["source"], draft["provenance"])
    return pilot.make_plan(plan["record"], seed, profile="subset-append-nested")


def test_nested_profile_freezes_five_distinct_paths_and_full_budget(nested_plan):
    frozen = nested_plan
    assert frozen["drafts"]["reference_tokens"] == 222
    assert frozen["drafts"]["base_tokens"] == 177
    assert [a["tokens"] for a in frozen["drafts"]["attempts"]] == [175, 175, 173, 173, 171]
    assert frozen["drafts"]["paths"] == [
        ["subset_trans_append_left"], ["subset_trans_append_right"],
        ["subset_trans_append_left", "subset_trans_append_right"],
        ["subset_trans_append_left", "subset_trans_append_left"],
        ["subset_trans_append_left", "subset_trans_append_left", "subset_trans_append_right"],
    ]
    assert len({d["source"] for d in frozen["drafts"]["drafts"]}) == 5
    assert frozen["selection"]["incumbent_label"] == "incumbent"
    assert frozen["selection"]["screen"]["planned_requests"] == 28
    assert frozen["selection"]["confirmation_request_reserve"] == 18
    assert frozen["max_processes"] == 46
    assert frozen["selection"]["selection_objective"] == "strict-dual-v1"
    assert frozen["selection"]["heartbeat_noise_floor_raw"] == 100
    assert not frozen["training_enabled"] and not frozen["drafts"]["proof_verified"]
    assert frozen == pilot.make_plan(frozen["record"], Candidate(**frozen["incumbent"]), profile=frozen["profile"])


def test_nested_candidates_only_edit_the_three_ite_blocks(nested_plan):
    prefix, rest = nested_plan["incumbent"]["source"].split("  case ite ", 1)
    _, suffix = rest.split("  case eq ", 1)
    for draft in nested_plan["drafts"]["drafts"]:
        candidate_prefix, candidate_rest = draft["source"].split("  case ite ", 1)
        _, candidate_suffix = candidate_rest.split("  case eq ", 1)
        assert candidate_prefix == prefix and candidate_suffix == suffix
    joint = nested_plan["drafts"]["drafts"][-1]["source"]
    ite = joint.split("  case ite ", 1)[1].split("  case eq ", 1)[0]
    assert ite.count("List.subset_append_of_subset_left") == 2
    assert ite.count("List.subset_append_of_subset_right") == 1
    assert "List.Subset.trans" not in ite and "simp_all" not in ite


@pytest.mark.parametrize("damage", ["old_budget", "changed_paths"])
def test_nested_plan_refuses_partial_budget_or_changed_paths(nested_plan, tmp_path, monkeypatch, damage):
    limit = nested_plan["max_processes"]
    if damage == "old_budget":
        limit = 38
    else:
        monkeypatch.setitem(pilot.PROFILES, "subset-append-nested", pilot.PROFILES["subset-append"])
    with pytest.raises(ValueError):
        pilot.run(nested_plan, bindings=dict.fromkeys(_pins(nested_plan["record"])), directory=tmp_path / "run",
                  max_processes=limit, check_resources=lambda: pytest.fail("invalid frozen experiment"))
    assert not (tmp_path / "run").exists()


@pytest.fixture
def shared_target_plan(nested_plan):
    draft = nested_plan["drafts"]["drafts"][0]
    seed = Candidate(draft["label"], draft["source"], draft["provenance"])
    return pilot.make_plan(nested_plan["record"], seed, profile="subset-append-shared-target")


def test_shared_target_profile_freezes_directions_and_eq_composition(shared_target_plan):
    frozen = shared_target_plan
    assert frozen["drafts"]["reference_tokens"] == 222 and frozen["drafts"]["base_tokens"] == 175
    assert [a["tokens"] for a in frozen["drafts"]["attempts"]] == [173, 173, 169]
    assert frozen["drafts"]["paths"] == [
        ["subset_pair_target_left"], ["subset_pair_target_right"],
        ["subset_pair_target_right", "subset_trans_append_left", "subset_trans_append_right"],
    ]
    assert [step["after_tokens"] for step in frozen["drafts"]["attempts"][-1]["steps"]] == [173, 171, 169]
    assert frozen["selection"]["screen"]["planned_requests"] == 20
    assert frozen["selection"]["confirmation_request_reserve"] == 18
    assert frozen["max_processes"] == 38
    assert frozen["selection"]["selection_objective"] == "strict-dual-v1"
    assert frozen["selection"]["heartbeat_noise_floor_raw"] == 100
    assert not frozen["training_enabled"] and not frozen["drafts"]["proof_verified"]
    assert frozen == pilot.make_plan(frozen["record"], Candidate(**frozen["incumbent"]), profile=frozen["profile"])


def test_shared_target_candidate_edit_boundaries(shared_target_plan):
    source = shared_target_plan["incumbent"]["source"]
    drafts = shared_target_plan["drafts"]["drafts"]
    for draft in drafts:
        assert draft["source"].split("  case ite ", 1)[0] == source.split("  case ite ", 1)[0]
    for draft in drafts[:2]:
        assert draft["source"].split("  case eq ", 1)[1] == source.split("  case eq ", 1)[1]
    right = drafts[1]["source"]
    assert "    apply List.subset_append_of_subset_right\n    apply List.Subset.app\n" in right
    assert "List.Subset.trans" not in right.split("  case ite ", 1)[1].split("  case eq ", 1)[0]
    assert "List.Subset.trans" not in drafts[2]["source"]


@pytest.mark.parametrize("damage", ["partial_budget", "changed_paths"])
def test_shared_target_plan_refuses_mutations_before_work(shared_target_plan, tmp_path, monkeypatch, damage):
    frozen = shared_target_plan
    limit = frozen["max_processes"]
    if damage == "partial_budget":
        limit = frozen["selection"]["screen"]["planned_requests"]
    else:
        monkeypatch.setitem(pilot.PROFILES, frozen["profile"], pilot.PROFILES["subset-append"])
    with pytest.raises(ValueError):
        pilot.run(frozen, bindings=dict.fromkeys(_pins(frozen["record"])), directory=tmp_path / "run",
                  max_processes=limit, check_resources=lambda: pytest.fail("invalid frozen experiment"))
    assert not (tmp_path / "run").exists()


@pytest.fixture
def pair_simp_plan(shared_target_plan):
    draft = shared_target_plan["drafts"]["drafts"][-1]
    seed = Candidate(draft["label"], draft["source"], draft["provenance"])
    return pilot.make_plan(shared_target_plan["record"], seed, profile="subset-append-simp")


def test_pair_simp_profile_freezes_full_two_by_two_ablation(pair_simp_plan):
    frozen = pair_simp_plan
    assert frozen["drafts"]["reference_tokens"] == 222 and frozen["drafts"]["base_tokens"] == 169
    assert [a["tokens"] for a in frozen["drafts"]["attempts"]] == [159, 123, 161, 131]
    assert frozen["drafts"]["paths"] == [["subset_pair_simp_first"], ["subset_pair_simp_all"],
        ["subset_pair_simp_split_first"], ["subset_pair_simp_split_all"]]
    assert len({d["source"] for d in frozen["drafts"]["drafts"]}) == 4
    assert frozen["selection"]["screen"]["planned_requests"] == 24
    assert frozen["selection"]["confirmation_request_reserve"] == 18
    assert frozen["max_processes"] == 42
    assert frozen["selection"]["selection_objective"] == "strict-dual-v1"
    assert frozen["selection"]["heartbeat_noise_floor_raw"] == 100
    assert not frozen["training_enabled"] and not frozen["drafts"]["proof_verified"]


def test_triple_profile_preserves_stronger_incumbent_and_confirmation_reserve(pair_simp_plan, tmp_path):
    seed = Candidate(**pair_simp_plan['incumbent'])
    frozen = pilot.make_plan(pair_simp_plan['record'], seed, profile='subset-triple-reconstruct')
    assert frozen['drafts']['base_tokens'] == 169
    assert len(frozen['drafts']['drafts']) == 3
    assert frozen['selection']['incumbent_label'] == 'incumbent'
    assert frozen['selection']['screen']['planned_requests'] == 20
    assert frozen['selection']['confirmation_request_reserve'] == 18
    assert frozen['max_processes'] == 38
    assert frozen['selection']['selection_objective'] == 'strict-dual-v1'
    assert frozen['selection']['heartbeat_noise_floor_raw'] == 100
    with pytest.raises(ValueError, match='reservation'):
        pilot.run(frozen, bindings=dict.fromkeys(_pins(frozen['record'])), directory=tmp_path/'run',
                  max_processes=20, check_resources=lambda: pytest.fail('partial reservation started work'))
    assert not (tmp_path/'run').exists()
    assert frozen == pilot.make_plan(frozen["record"], Candidate(**frozen["incumbent"]), profile=frozen["profile"])


def test_normalization_profile_has_two_fixed_simp_sets_and_full_reserve(pair_simp_plan, tmp_path):
    seed = Candidate(**pair_simp_plan['incumbent'])
    frozen = pilot.make_plan(pair_simp_plan['record'], seed, profile='subset-triple-normalize')
    assert frozen['drafts']['base_tokens'] == 169
    assert [a['tokens'] for a in frozen['drafts']['attempts']] == [163, 161]
    drafts = frozen['drafts']['drafts']
    assert len(drafts) == 2 and drafts[0]['source'].replace('or_imp, forall_and,', 'or_imp,') == drafts[1]['source']
    for draft in drafts:
        assert set(draft) == {'name', 'label', 'source', 'provenance'}
        assert 'grind' not in draft['source'] and 'Classical.' not in draft['source']
        assert draft['source'].split('  case ite ', 1)[0] == seed.source.split('  case ite ', 1)[0]
        assert draft['source'].split('  case eq ', 1)[1] == seed.source.split('  case eq ', 1)[1]
    assert frozen['selection']['screen']['planned_requests'] == 16
    assert frozen['selection']['confirmation_request_reserve'] == 18
    assert frozen['max_processes'] == 34
    assert frozen['selection']['selection_objective'] == 'strict-dual-v1'
    assert frozen['selection']['heartbeat_noise_floor_raw'] == 100
    assert not frozen['drafts']['proof_verified'] and not frozen['promoted']
    for bad in (0, 16, 33, True):
        with pytest.raises(ValueError, match='reservation'):
            pilot.run(frozen, bindings=dict.fromkeys(_pins(frozen['record'])), directory=tmp_path/'run',
                      max_processes=bad, check_resources=lambda: pytest.fail('insufficient reservation'))
    assert not (tmp_path/'run').exists()
    assert frozen == pilot.make_plan(frozen['record'], seed, profile=frozen['profile'])


def test_archived_grind_verification_is_not_no_axiom_growth_admission():
    # Saved observations test reporting/admission semantics, not a new Lean run.
    report = json.loads((pilot.ROOT / 'papers/completion/lean_refactor_arena/evidence/'
                        'subset-triple-strata-2026-09-25/report.json').read_text())
    assert report['status'] == 'NO_IMPROVEMENT' and report['recommended'] is None
    assert report['confirmation'] is None
    for label in ('composition-1', 'composition-2'):
        samples = [s for s in report['screen']['samples'] if s['label'] == label]
        assert len(samples) == 4 and all(s['status'] == 'VERIFIED' for s in samples)
        row = report['screen_analysis']['rows'][label]
        assert not row['admissible'] and row['reason'] == 'axiom_expansion_over_reference'
        assert 'Classical.choice' in row['axioms_by_version']['v4.26.0']


def test_term_profile_freezes_explicit_aggregate_tradeoff_and_full_budget(pair_simp_plan, tmp_path):
    seed = Candidate(**pair_simp_plan['incumbent'])
    strict = pilot.make_plan(pair_simp_plan['record'], seed, profile='subset-triple-term')
    aggregate = pilot.make_plan(pair_simp_plan['record'], seed, profile='subset-triple-term',
                                selection_objective='aggregate-local-v1')
    assert strict['selection_objective'] == strict['selection']['selection_objective'] == 'strict-dual-v1'
    assert aggregate['selection_objective'] == aggregate['selection']['selection_objective'] == 'aggregate-local-v1'
    assert strict['plan_sha256'] != aggregate['plan_sha256']
    assert strict['drafts'] == aggregate['drafts']
    assert [a['tokens'] for a in aggregate['drafts']['attempts']] == [181, 178]
    assert aggregate['drafts']['base_tokens'] == 169 and aggregate['drafts']['reference_tokens'] == 222
    for draft in aggregate['drafts']['drafts']:
        assert set(draft) == {'name', 'label', 'source', 'provenance'}
        assert draft['source'].split('  case ite ', 1)[0] == seed.source.split('  case ite ', 1)[0]
        assert draft['source'].split('  case eq ', 1)[1] == seed.source.split('  case eq ', 1)[1]
        assert 'cases Hnorm\n' in draft['source'].split('  case ite ', 1)[1]
        assert 'grind' not in draft['source'] and 'Classical.' not in draft['source']
    assert aggregate['selection']['screen']['planned_requests'] == 16
    assert aggregate['selection']['confirmation_request_reserve'] == 18
    assert aggregate['max_processes'] == 34 and aggregate['selection']['heartbeat_noise_floor_raw'] == 100
    assert not aggregate['drafts']['proof_verified'] and not aggregate['promoted']
    for limit in (0, 16, 33, True):
        with pytest.raises(ValueError, match='reservation'):
            pilot.run(aggregate, bindings=dict.fromkeys(_pins(aggregate['record'])), directory=tmp_path/'run',
                      max_processes=limit, check_resources=lambda: pytest.fail('partial budget'))
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('objective', [None, True, [], 'pareto-v1', 'unchecked'])
def test_invalid_objective_rejected_even_when_no_drafts(plan, objective):
    seed = Candidate('none', plan['record']['statement'] + ' := by assumption', 'fixture')
    with pytest.raises(ValueError, match='objective'):
        pilot.make_plan(plan['record'], seed, selection_objective=objective)


@pytest.mark.parametrize('location', ['top', 'nested', 'both'])
def test_objective_cannot_change_after_plan_freezes(plan, tmp_path, location):
    if location in ('top', 'both'): plan['selection_objective'] = 'aggregate-local-v1'
    if location in ('nested', 'both'): plan['selection']['selection_objective'] = 'aggregate-local-v1'
    with pytest.raises(ValueError, match='stale'):
        pilot.run(plan, bindings=dict.fromkeys(_pins(plan['record'])), directory=tmp_path/'run',
                  max_processes=plan['max_processes'], check_resources=lambda: pytest.fail('changed objective'))
    assert not (tmp_path/'run').exists()


def test_pair_simp_keeps_unmatched_cases_and_shared_target_lift(pair_simp_plan):
    source = pair_simp_plan["incumbent"]["source"]
    drafts = pair_simp_plan["drafts"]["drafts"]
    for draft in drafts:
        assert draft["source"].split("      apply List.Subset.app", 1)[0].split("      simp_all", 1)[0] == (
            source.split("      apply List.Subset.app", 1)[0])
        assert "    apply List.subset_append_of_subset_right\n" in draft["source"]
    for draft in (drafts[0], drafts[2]):
        assert draft["source"].split("  case abs ", 1)[1] == source.split("  case abs ", 1)[1]
        assert draft["source"].count("simp_all [") == 1
    for draft in (drafts[1], drafts[3]):
        assert draft["source"].count("simp_all [") == 4
        assert "  case abs ih =>\n    cases Hnorm\n    apply ih ; assumption\n" in draft["source"]
        assert "    apply List.subset_append_of_subset_right\n    simp_all [" in draft["source"]


@pytest.mark.parametrize("damage", ["partial_budget", "changed_paths"])
def test_pair_simp_plan_refuses_mutations_before_work(pair_simp_plan, tmp_path, monkeypatch, damage):
    frozen = pair_simp_plan
    limit = frozen["max_processes"]
    if damage == "partial_budget":
        limit = frozen["selection"]["screen"]["planned_requests"]
    else:
        monkeypatch.setitem(pilot.PROFILES, frozen["profile"], pilot.PROFILES["subset-append"])
    with pytest.raises(ValueError):
        pilot.run(frozen, bindings=dict.fromkeys(_pins(frozen["record"])), directory=tmp_path / "run",
                  max_processes=limit, check_resources=lambda: pytest.fail("invalid frozen experiment"))
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("label", ["composition-0", "composition-1", "composition-2", "control", "incumbent", "x" * 80])
def test_exported_winner_can_seed_next_round_without_label_collision(plan, label):
    first = pilot.make_plan(plan["record"], Candidate(**plan["incumbent"]), profile="subset-append")
    # A generated nomination, not a receipt granting proof authority.
    draft = first["drafts"]["drafts"][2]
    seed = Candidate(label, draft["source"], draft["provenance"])
    following = pilot.make_plan(plan["record"], seed, profile="subset-append")
    assert following["schema"] == "jevops-arena-leaf-pilot/v4"
    assert following["incumbent"] == dict(label=label, source=seed.source, provenance=seed.provenance)
    assert following["selection"]["incumbent_label"] == "incumbent"
    assert following["selection"]["candidate_labels"] == ["composition-0", "composition-1", "composition-2"]
    assert following["drafts"]["reference_tokens"] == 222
    assert following["drafts"]["base_tokens"] == 181
    assert [a["tokens"] for a in following["drafts"]["attempts"]] == [179, 179, 177]
    assert following["max_processes"] == 38
    arms = following["selection"]["screen"]["arms"]
    comparison = next(a for a in arms if a["label"] == "incumbent")
    assert comparison["source"] == seed.source and comparison["provenance"] == seed.provenance
    assert following == pilot.make_plan(following["record"], Candidate(**following["incumbent"]), profile="subset-append")


@pytest.mark.parametrize('objective', ['strict-dual-v1', 'aggregate-local-v1'])
def test_run_uses_same_incumbent_role_as_frozen_plan(plan, tmp_path, monkeypatch, objective):
    seed = Candidate("composition-0", plan["incumbent"]["source"], plan["incumbent"]["provenance"])
    frozen = pilot.make_plan(plan["record"], seed, profile="subset-append", selection_objective=objective)
    class ReachedSelector(Exception): pass
    def inspect(record, candidates, factory, **kwargs):
        incumbent = kwargs["incumbent"]
        assert incumbent == Candidate("incumbent", seed.source, seed.provenance)
        selection_kwargs = {key: kwargs[key] for key in (
            "incumbent", "repetitions", "confirmation_repetitions", "selection_objective", "heartbeat_noise_floor_raw")}
        assert pilot.selection_plan(record, candidates, **selection_kwargs) == frozen["selection"]
        raise ReachedSelector
    monkeypatch.setattr(pilot, "run_selection", inspect)
    monkeypatch.setattr(pilot, "NativeLeanVerifier", lambda *a, **k: pytest.fail("no native calls in contract test"))
    with pytest.raises(ReachedSelector):
        pilot.run(frozen, bindings=dict.fromkeys(_pins(frozen["record"])), directory=tmp_path / "run",
                  max_processes=frozen["max_processes"], check_resources=lambda: None)
    assert json.loads((tmp_path / "run" / "plan.json").read_text()) == frozen


def test_profile_mutation_invalidates_frozen_plan_before_work(plan, tmp_path):
    plan["profile"] = "subset-append"
    with pytest.raises(ValueError, match="stale"):
        pilot.run(plan, bindings=dict.fromkeys(_pins(plan["record"])), directory=tmp_path / "run",
                  max_processes=plan["max_processes"], check_resources=lambda: pytest.fail("mutated plan"))


def test_reference_incumbent_can_share_control(plan):
    # A fixture source with an eligible leaf; the actual Arena reference has
    # intervening tactics and correctly produces no leaf nomination.
    record = {**plan["record"], "src": plan["incumbent"]["source"]}
    frozen = pilot.make_plan(record, Candidate("same", record["src"], "reference incumbent"))
    assert frozen["selection"]["incumbent_label"] == "control"


@pytest.mark.parametrize("damage", ["zero_budget", "bool_budget", "plan", "incumbent", "binding"])
def test_invalid_run_refused_before_resources_or_output(plan, tmp_path, damage):
    bindings = dict.fromkeys(_pins(plan["record"]))
    limit = plan["max_processes"]
    if damage == "zero_budget": limit = 0
    elif damage == "bool_budget": limit = True
    elif damage == "plan": plan["selection"]["heartbeat_noise_floor_raw"] = 0
    elif damage == "incumbent": plan["incumbent"]["source"] += " "
    else: bindings.clear()
    with pytest.raises(ValueError):
        pilot.run(plan, bindings=bindings, directory=tmp_path / "run", max_processes=limit,
                  check_resources=lambda: pytest.fail("invalid inputs must not start work"))
    assert not (tmp_path / "run").exists()


def test_abstention_is_zero_call_without_successful_fallback(plan, tmp_path, monkeypatch):
    incumbent = Candidate("no-leaves", plan["record"]["statement"] + " := by assumption", "test nomination")
    frozen = pilot.make_plan(plan["record"], incumbent)
    monkeypatch.setattr(pilot, "run_selection", lambda *a, **k: pytest.fail("no candidate must not select"))
    report = pilot.run(frozen, bindings=dict.fromkeys(_pins(plan["record"])), directory=tmp_path / "run",
                       max_processes=0, check_resources=lambda: None)
    assert report["status"] == "NO_CANDIDATE" and report["native_processes"] == 0
    assert not report["retained_incumbent_verified"] and report["recommended"] is None


def test_storage_stop_precedes_output_and_native_work(plan, tmp_path, monkeypatch):
    def exhausted(): raise ValueError("storage reserve reached")
    monkeypatch.setattr(pilot, "run_selection", lambda *a, **k: pytest.fail("storage is exhausted"))
    with pytest.raises(ValueError, match="storage reserve"):
        pilot.run(plan, bindings=dict.fromkeys(_pins(plan["record"])), directory=tmp_path / "run",
                  max_processes=plan["max_processes"], check_resources=exhausted)
    assert not (tmp_path / "run").exists()


def test_serialized_plans_and_exclusive_outputs(plan, tmp_path):
    restored = json.loads(json.dumps(plan))
    assert content_hash(restored) == content_hash(plan)
    path = tmp_path / "plan.json"
    pilot.save(path, plan)
    with pytest.raises(FileExistsError): pilot.save(path, {"overwritten": True})
    assert json.loads(path.read_text()) == restored
