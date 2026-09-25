from dataclasses import FrozenInstanceError, asdict, replace
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys
from types import SimpleNamespace

import pytest

from jevops.arena import (
    ArenaContext, ArenaEvaluator, Outcome, Score, VersionReceipt,
    VerificationRequest, aggregate_scores, calibration_report, content_hash,
    intake_error, proof_suffix, reference_tokens, score_metrics, source_hash,
)
from jevops.lean import VersionPin
from jevops.router_tuning import RouterTuningConfig, RouterTuningLoop

ROOT = Path(__file__).resolve().parents[1]
ARENA = ROOT / "papers/completion/lean_refactor_arena"
STATEMENT = "theorem sample (h : True) : True"
SOURCE = STATEMENT + " := by\n  have redundant : True := h\n  exact redundant"


def context(**changes):
    base = ArenaContext(
        "sample", STATEMENT, SOURCE, reference_tokens(SOURCE, STATEMENT), 100,
        (VersionPin("v1", "commit1"), VersionPin("v2", "commit2")),
        (content_hash({"dependency": 1}), content_hash({"dependency": 2})),
        "test-fixture", "1", "fixture-heartbeats/v1",
    )
    return replace(base, **changes)


def verified(request, **changes):
    return replace(VersionReceipt(
        request.request_id, source_hash(request.source), request.context.problem,
        Outcome.VERIFIED, True, 0,
        f"'{request.context.problem}' does not depend on any axioms", 100,
    ), **changes)


def evaluator(verifier=verified, **kwargs):
    return ArenaEvaluator(context(), verifier, max_calls=kwargs.pop("max_calls", 100),
                          evidence_mode="offline_fixture", **kwargs)


def load_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_calibration_matches_all_published_references_without_claiming_compilation():
    report = calibration_report(load_rows(ARENA / "data/benchmark_data_warmup.jsonl"),
                                load_rows(ARENA / "space/benchmark_heartbeats.jsonl"))
    assert report["reference_token_matches"] == report["problems"] == 15
    assert report["required_version_checks"] == 36
    assert report["completed_version_checks"] == 0
    assert report["worker_metric_parity"] == "UNCONFIRMED"
    assert report["official_score"] is None
    assert all(row["baseline_compiles"] is None for row in report["rows"])


def test_frozen_references_pass_intake_including_parenthesized_cardinality():
    for row in load_rows(ARENA / "data/benchmark_data_warmup.jsonl"):
        assert intake_error(row["src"], row["statement"]) is None, row["name"]
    assert intake_error(STATEMENT + " := by have n := #(Finset.univ); exact h", STATEMENT) is None


@pytest.mark.parametrize("command", ["#check True", "#print sample", "#guard true", "#eval 1"])
def test_cardinality_support_does_not_allow_diagnostic_commands(command):
    assert intake_error(STATEMENT + " := by exact h\n" + command, STATEMENT)


@pytest.mark.parametrize("filename,verified", [("native-baseline-2026-09-22.json", 12),
                                             ("native-baseline-prepared-2026-09-22.json", 17),
                                             ("native-baseline-cslib-rc2-2026-09-22.json", 3)])
def test_saved_native_baseline_is_bound_to_unchanged_frozen_sources_not_a_score(filename, verified):
    """Audit historical report bookkeeping; does not re-execute its proofs."""
    corpus = ARENA / "data/benchmark_data_warmup.jsonl"
    records = {r["name"]: r for r in load_rows(corpus)}
    report = json.loads((ARENA / "evidence" / filename).read_text())
    assert report["corpus_sha256"] == source_hash(corpus.read_text())
    expected = {(r["name"], tag, commit) for r in records.values() for v in r["version_info"] for tag, commit in v.items()}
    assert {(r["name"], r["lean_tag"], r["git_commit"]) for r in report["rows"]} == expected
    assert report["required_version_checks"] == len(report["rows"]) == 36
    measured = [r for r in report["rows"] if r["status"] == "VERIFIED"]
    assert len(measured) == report["completed_version_checks"] == report["processes"] == verified
    assert report["official_score"] is report["local_combined_pct"] is None
    assert report["live_model_calls"] == 0
    for row in measured:
        receipt = row["receipt"]
        if "context" in row:
            context_data = row["context"]
            assert context_data["verifier_id"] == "jevops-native-arena"
            ctx = ArenaContext(**{**context_data,
                "versions": tuple(VersionPin(**p) for p in context_data["versions"]),
                "dependency_digests": tuple(context_data["dependency_digests"]),
                "allowed_axioms": tuple(context_data["allowed_axioms"])})
            assert ctx.context_id == row["context_id"]
            request = VerificationRequest(ctx, records[row["name"]]["src"], ctx.versions[0])
            assert request.request_id == receipt["request_id"]
        else:
            assert report["evidence_mode"] == "local_lean"
        assert receipt["candidate_sha256"] == source_hash(records[row["name"]]["src"])
        assert receipt["target"] == row["name"] and receipt["type_preserved"]
        native = json.loads(receipt["observations_json"])["report"]
        assert native["target_absent_before"] and native["type_preserved"]
        assert native["heartbeats"] == native["raw_heartbeats"] // 1000


def test_cslib_baseline_adds_three_distinct_contexts_without_erasing_previous_coverage():
    """Historical union, not fresh evidence that all twenty environments still apply."""
    reports = [json.loads((ARENA / "evidence" / name).read_text()) for name in
               ("native-baseline-prepared-2026-09-22.json", "native-baseline-cslib-rc2-2026-09-22.json")]
    measured = [{(r["name"], r["lean_tag"], r["git_commit"]) for r in report["rows"]
                 if r["status"] == "VERIFIED"} for report in reports]
    assert measured[0].isdisjoint(measured[1])
    assert len(measured[0] | measured[1]) == 20
    assert {tag for _, tag, _ in measured[1]} == {"v4.33.0-rc2"}


def test_saved_regression_is_recounted_without_relabeling_historical_metrics():
    saved = json.loads((ROOT / "tests/fixtures/kernel_refactor_local_best.json").read_text())
    row = next(r for r in load_rows(ARENA / "data/benchmark_data_warmup.jsonl") if r["name"] == saved["name"])
    assert reference_tokens(row["src"], row["statement"]) == 313
    assert reference_tokens(saved["best_source"], row["statement"]) == 237
    assert (saved["source_body_tokens"], saved["best_body_tokens"]) == (482, 391)
    assert saved["official_score"] is None  # This test does not recompile the proof.


def test_known_boundary_ignores_inner_assignments_and_supports_term_proofs():
    statement = "theorem t (n : Nat := by exact 1) : n = n"
    assert proof_suffix(statement + " := by rfl", statement) == " by rfl"
    assert reference_tokens(statement + " := by rfl", statement) == 2
    assert reference_tokens(statement + " := Eq.refl n", statement) == 2
    with pytest.raises(ValueError, match="prefix"):
        reference_tokens("theorem changed : True := by trivial", statement)
    with pytest.raises(ValueError, match=":="):
        reference_tokens(statement + "extra := by rfl", statement)


def test_unicode_operators_comments_and_strings_have_stable_reference_counts():
    statement = "theorem t : True"
    assert reference_tokens(statement + " := by\n  exact True.intro", statement) == 3
    assert reference_tokens(statement + " := by simp <;> rfl", statement) == 4
    assert reference_tokens(statement + " := by\n/- outer /- sorry -/ -/\n  exact True.intro -- sorry", statement) == 3
    assert reference_tokens(statement + " := by exact α.β'", statement) == 3
    assert proof_suffix(statement + ' := "-- /- literal -/"', statement) == ' "-- /- literal -/"'
    assert proof_suffix(statement + " := «/-name-/»", statement) == " «/-name-/»"
    with pytest.raises(ValueError, match="unterminated"):
        proof_suffix(statement + " := by /- no end", statement)


@pytest.mark.parametrize("body", ["sorry", "native_decide", "run_elab skip", "#eval 1", "IO.println x",
                                  "trivial\ntheorem stolen : False := by sorry", "set_option maxHeartbeats 0 in trivial"])
def test_intake_refuses_shortcuts_before_spending_budget(body):
    ev = evaluator()
    result = ev.evaluate(STATEMENT + " := by\n" + body)
    assert result.status == "REJECTED" and ev.calls == 0
    assert result.score.combined_pct == 0


def test_comment_filter_does_not_confuse_comments_with_executable_source():
    assert intake_error(STATEMENT + " := by trivial -- sorry", STATEMENT) is None
    assert intake_error(STATEMENT + ' := by have s := "/-"; run_cmd x; have t := "-/"; trivial', STATEMENT)


@pytest.mark.parametrize("field", ["length", "reference_length", "heartbeats", "reference_heartbeats", "passed", "total"])
@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 1.5, "2"])
def test_non_integer_or_nonfinite_metrics_fail_closed(field, value):
    args = dict(length=5, reference_length=10, heartbeats=2, reference_heartbeats=4, passed=1, total=2)
    args[field] = value
    with pytest.raises(ValueError):
        score_metrics(**args)


def test_zero_heartbeats_and_negative_reductions_are_not_defaulted_or_clipped():
    result = score_metrics(reference_length=10, reference_heartbeats=100, length=20, heartbeats=0, passed=1, total=1)
    assert result == Score(-100, 100, 100, 33.33)
    assert score_metrics(reference_length=0, reference_heartbeats=0, length=5, heartbeats=None, passed=1, total=1) == Score(0, 0, 100, 33.33)
    assert score_metrics(reference_length=10, reference_heartbeats=100, length=2, heartbeats=1,
                         passed=1, total=1, compiled=False) == Score(0, 0, 0, 0)


def test_differential_scoring_matches_vendored_leaderboard_including_aggregate_rounding(monkeypatch, tmp_path):
    rng = random.Random(9022)
    names = [f"p{i}" for i in range(30)]
    lengths = {name: rng.randrange(0, 501) for name in names}
    heartbeats = {name: rng.choice([None, 0, rng.randrange(1, 10000)]) for name in names}
    benchmark = SimpleNamespace(BENCHMARK={}, benchmark_names=lambda: names,
                                original_length=lengths.get, original_heartbeats=heartbeats.get)
    monkeypatch.setitem(sys.modules, "benchmark", benchmark)
    spec = importlib.util.spec_from_file_location("arena_score_reference", ARENA / "space/leaderboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    submitted, scores = {}, {}
    for name in names[:-3]:  # Missing submissions must remain in the denominator.
        total = rng.randrange(1, 5)
        passed = rng.randrange(total + 1)
        compiled = rng.choice([True, True, False])
        length, hb = rng.randrange(501), rng.choice([None, 0, rng.randrange(10000)])
        submitted[name] = {"compiled": compiled, "length": length, "heartbeats": hb,
                           "compat": {str(v): {"passed": v < passed} for v in range(total)}}
        scores[name] = score_metrics(reference_length=lengths[name], reference_heartbeats=heartbeats[name],
                                     length=length, heartbeats=hb, passed=passed, total=total, compiled=compiled)
    official = module.Leaderboard(tmp_path / "leaderboard.json").submit("fixture", submitted)
    ours = aggregate_scores(names, scores)
    assert ours["local_combined_pct"] == official["avg_combined_pct"]
    assert ours["avg_compatibility_pct"] == official["avg_survival_rate"]
    assert ours["avg_length_reduction_pct"] == official["avg_length_reduction_pct"]
    assert ours["avg_heartbeat_reduction_pct"] == official["avg_heartbeat_reduction_pct"]
    assert all(scores[name].combined_pct == official["results"][name]["score"] for name in scores)


def test_missing_submission_is_zero_but_missing_measurements_are_unknown():
    assert aggregate_scores(["a", "b"], {"a": Score(0, 0, 100, 33.33)})["local_combined_pct"] == 16.67
    assert aggregate_scores(["a", "b"], {"a": None})["local_combined_pct"] is None
    for names, results in [([], {}), (["a", "a"], {}), (["a"], {"unknown": None})]:
        with pytest.raises(ValueError):
            aggregate_scores(names, results)


@pytest.mark.parametrize("overrides", [
    {"request_id": "other"}, {"candidate_sha256": "other"}, {"target": "other"},
    {"type_preserved": False}, {"exit_code": 1}, {"axiom_output": ""},
    {"axiom_output": "'sample' depends on axioms: [sorryAx]"},
    {"axiom_output": "'sample' depends on axioms: [Lean.ofReduceBool]"},
])
def test_mismatched_or_forged_admission_cannot_win(overrides):
    ev = evaluator(lambda request: verified(request, **overrides))
    result = ev.evaluate(SOURCE)
    assert result.status != "MEASURED"
    assert not ev.compile_candidate(SOURCE)["theorem_ok"]


def test_legacy_theorem_ok_is_not_a_verifier_receipt():
    ev = evaluator(lambda _: {"theorem_ok": True, "confidence": 1.0, "heartbeats": 0})
    result = ev.evaluate(SOURCE)
    assert result.status == "INCOMPLETE"
    assert all(r.outcome == Outcome.ERROR for r in result.receipts)


def test_absent_optional_verifier_does_not_spend_or_claim_compatibility():
    ev = evaluator(None)
    result = ev.evaluate(SOURCE)
    assert result.score is None and result.status == "INCOMPLETE" and ev.calls == 0
    assert all(r.outcome == Outcome.UNAVAILABLE for r in result.receipts)


def test_verified_default_with_missing_heartbeat_stays_incomplete_and_can_retry():
    ev = evaluator(lambda r: verified(r, heartbeats=None))
    assert ev.evaluate(SOURCE).score is None
    ev.verifier = verified
    assert ev.evaluate(SOURCE).status == "MEASURED"
    assert ev.calls == 3  # Only the missing default measurement is retried.


def test_failed_compatibility_is_measured_but_timeout_is_not_semantic_failure():
    ev = evaluator(lambda r: verified(r, outcome=Outcome.VERIFIED if r.version.lean_tag == "v1" else Outcome.REJECTED))
    result = ev.evaluate(SOURCE)
    assert result.status == "MEASURED" and result.score.compatibility_pct == 50
    ev = evaluator(lambda r: verified(r, outcome=Outcome.VERIFIED if r.version.lean_tag == "v1" else Outcome.TIMEOUT))
    assert ev.evaluate(SOURCE).score is None
    ev.verifier = verified
    assert ev.evaluate(SOURCE).score.compatibility_pct == 100
    assert ev.calls == 3


def test_zero_exact_and_partial_budgets_and_idempotent_terminal_replay():
    zero = evaluator(max_calls=0)
    assert zero.evaluate(SOURCE).score is None and zero.calls == 0
    exact = evaluator(max_calls=2)
    first = exact.evaluate(SOURCE)
    assert first.status == "MEASURED" and exact.calls == 2
    assert exact.evaluate(SOURCE) == first
    assert exact.calls == 2 and exact.cache_hits == 2
    partial = evaluator(max_calls=1)
    result = partial.evaluate(SOURCE)
    assert result.receipts[0].outcome == Outcome.VERIFIED
    assert result.receipts[1].outcome == Outcome.BUDGET_EXHAUSTED
    assert result.score is None and partial.calls == 1


@pytest.mark.parametrize("kwargs", [{"max_cache_entries": 0}, {"max_cache_bytes": 0}, {"max_cache_bytes": 1}])
def test_cache_zero_and_byte_limits_are_real(kwargs):
    ev = evaluator(**kwargs)
    ev.evaluate(SOURCE)
    ev.evaluate(SOURCE)
    assert ev.calls == 4 and ev.cache_hits == 0 and not ev._cache
    assert ev.accounting()["cache_bytes"] == 0


def test_cache_eviction_obeys_both_limits():
    ev = evaluator(max_cache_entries=1, max_cache_bytes=1000)
    ev.evaluate(SOURCE)
    assert len(ev._cache) == 1 and ev.accounting()["cache_bytes"] <= 1000


def test_exception_reserves_once_and_is_not_negatively_cached():
    def broken(_):
        raise TimeoutError("transient")
    ev = evaluator(broken, max_calls=4)
    assert ev.evaluate(SOURCE).status == "INCOMPLETE" and ev.calls == 2
    ev.verifier = verified
    assert ev.evaluate(SOURCE).status == "MEASURED" and ev.calls == 4


def test_context_is_immutable_and_binds_all_verification_dimensions():
    ctx = context()
    with pytest.raises(FrozenInstanceError):
        ctx.header = "changed"
    for changes in [{"header": "import Other"}, {"reference_heartbeats": 200}, {"verifier_version": "2"},
                    {"dependency_digests": ("0" * 64, "1" * 64)}, {"verifier_options_json": '{"option":1}'},
                    {"allowed_axioms": ()}, {"heartbeat_method": "new-scope"}, {"file_path": "other.lean"}]:
        assert replace(ctx, **changes).context_id != ctx.context_id
    with pytest.raises(ValueError):
        replace(ctx, verifier_options_json='{"bad":NaN}')
    ev = evaluator()
    old = verified(VerificationRequest(ctx, SOURCE, ctx.versions[0]))
    changed = ArenaEvaluator(replace(ctx, verifier_version="2"), lambda _: old,
                             max_calls=2, evidence_mode="offline_fixture")
    assert changed.evaluate(SOURCE).score is None
    ev.evaluate(SOURCE)
    ev.unrelated_scheduler_tick = 123
    assert ev.evaluate(SOURCE).status == "MEASURED" and ev.calls == 2


def run_fixture_router(*, objective="arena-v1", changed_statement=None, bad_candidate=False):
    statement = changed_statement or STATEMENT
    source = statement + " := by\n  have redundant : True := h\n  exact redundant"
    ctx = context(statement=statement, reference_source=source, reference_length=reference_tokens(source, statement))
    def verifier(request):
        body = " ".join(proof_suffix(request.source, statement).split())
        if body == "by trivial":
            return verified(request, heartbeats=1000, outcome=Outcome.REJECTED if bad_candidate else Outcome.VERIFIED)
        if body == "by exact id h":
            return verified(request, heartbeats=0)
        return verified(request, heartbeats=100)
    ev = ArenaEvaluator(ctx, verifier, max_calls=200, evidence_mode="offline_fixture")
    kwargs = {"arena_evaluator": ev} if objective == "arena-v1" else {"compile_fn": lambda *_args, **_kw: {"theorem_ok": True}}
    loop = RouterTuningLoop({}, source, problem="sample", **kwargs,
        config=RouterTuningConfig(selection_objective=objective, train=False, rounds=2, max_candidate_pool=8,
                                  n_variations=1, hammer_sweep=False, logic_reductions=False, teacher_replay=False),
        router_generate=lambda _: json.dumps({"candidates": [{"tactics": "trivial", "theorem_ok": True}, {"tactics": "exact id h"}]}))
    return loop, ev


def test_existing_router_selects_longer_faster_candidate_in_opt_in_mode():
    loop, ev = run_fixture_router()
    result = loop.run()
    assert result["ok"] and result["best_source"].rstrip().endswith("exact id h")
    assert result["arena"]["best"]["score"]["heartbeat_reduction_pct"] == 100
    assert result["arena"]["best"]["evidence_mode"] == "offline_fixture"
    assert result["arena"]["official_score"] is None
    assert result["arena"]["accounting"]["verifier_calls"] == ev.calls
    assert all(not row["training"].get("trained") for row in result["history"])
    scores = [row["round_winner"]["arena_evaluation"]["score"]["combined_pct"] for row in result["history"]]
    assert scores == sorted(scores)
    assert "receipts" not in result["history"][0]["round_winner"]["arena_evaluation"]


def test_default_shortest_mode_keeps_legacy_selection():
    loop, _ = run_fixture_router(objective="shortest")
    result = loop.run()
    assert result["best_source"].rstrip().endswith("trivial")
    assert result["arena"] is None


def test_router_uses_frozen_statement_boundary_with_internal_by():
    statement = "theorem sample (n : Nat := by exact 1) (h : True) : True"
    loop, _ = run_fixture_router(changed_statement=statement)
    result = loop.run()
    assert result["best_source"] == statement + " := by\n  exact id h\n"


def test_router_rejects_unchecked_scoring_modes_and_keeps_valid_fallback():
    with pytest.raises(ValueError, match="train=False"):
        RouterTuningConfig(selection_objective="arena-v1")
    with pytest.raises(ValueError, match="ArenaEvaluator"):
        RouterTuningLoop({}, SOURCE, problem="sample", compile_fn=lambda _: {"theorem_ok": True},
                         config=RouterTuningConfig(selection_objective="arena-v1", train=False))
    ev = evaluator(lambda r: verified(r, outcome=Outcome.VERIFIED if r.source == SOURCE else Outcome.REJECTED))
    loop = RouterTuningLoop({}, SOURCE, problem="sample", arena_evaluator=ev,
        config=RouterTuningConfig(selection_objective="arena-v1", train=False, rounds=1, max_candidate_pool=4,
                                  n_variations=1, hammer_sweep=False, logic_reductions=False, teacher_replay=False),
        router_generate=lambda _: '{"candidates":[{"tactics":"trivial","theorem_ok":true}]}')
    result = loop.run()
    assert result["best_source"] == SOURCE and result["ok"]


def test_calibration_cli_is_json_and_makes_no_implicit_compilation_claim():
    run = subprocess.run([sys.executable, "-m", "jevops.arena", "--calibrate"], cwd=ROOT,
                         capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert "RuntimeWarning" not in run.stderr
    assert json.loads(run.stdout)["reference_token_matches"] == 15


def test_exhausted_verification_budget_prevents_provider_work():
    calls = []
    ev = evaluator(max_calls=0)
    result = RouterTuningLoop({}, SOURCE, problem="sample", arena_evaluator=ev,
        config=RouterTuningConfig(selection_objective="arena-v1", train=False),
        router_generate=lambda prompt: calls.append(prompt) or "{}").run()
    assert not calls and not result["ok"] and result["history"] == []
    assert result["arena"]["best"]["status"] == "INCOMPLETE"


def test_runnable_demo_labels_synthetic_results():
    from jevops.arena_demo import run_demo
    report = run_demo()
    assert report["evidence_mode"] == "offline_fixture"
    assert report["live_model_calls"] == report["lean_compilations"] == 0
    assert report["selected_source"].rstrip().endswith("exact id h")
    assert report["official_score"] is None
