from __future__ import annotations

import copy
import json
import shutil

import pytest

from jevops import proof_replay as replay
from jevops import replay_distillation as rd
from jevops.proof_state import capture_source
from jevops.replay_curriculum import compound_rows
from jevops.replay_router import ReplayRouter, anchor_options, parse_proposals, run_router_experiment
from jevops.router_tuning import _lean_compiler

ENV = "a" * 64


def response(request, candidate="rfl", event_id=None):
    return json.dumps({"request_sha256": request["request_sha256"], "proposals": [{
        "event_id": request["anchors"][0]["event_id"] if event_id is None else event_id,
        "candidate": candidate, "hypothesis": "Replace the entire closing span atomically."}]})


def sample_request():
    return {"request_sha256": "a" * 64, "proposal_limit": 1, "anchors": [{"event_id": 2}]}


@pytest.mark.parametrize("candidate", ["rfl", "exact h", "intro h\nexact h", "first | rfl | assumption"])
def test_bounded_tactic_compositions_are_proposals_only(candidate):
    rows = parse_proposals(response(sample_request(), candidate), sample_request())
    assert rows[0]["candidate"] == candidate and set(rows[0]) == {"event_id", "candidate", "hypothesis"}


@pytest.mark.parametrize("damage", ["foreign", "duplicate", "extra_receipt", "bool_anchor", "unknown_anchor",
    "too_many", "huge", "nonfinite", "metaprogram", "declaration", "sorry", "comments", "blank", "lines"])
def test_router_json_is_strict_bounded_and_request_bound(damage):
    request = sample_request()
    wire = json.loads(response(request))
    if damage == "foreign":
        wire["request_sha256"] = "b" * 64
    elif damage == "extra_receipt":
        wire["proof_admitted"] = True
    elif damage in ("bool_anchor", "unknown_anchor"):
        wire["proposals"][0]["event_id"] = True if damage == "bool_anchor" else 3
    elif damage == "too_many":
        wire["proposals"] *= 2
    elif damage == "nonfinite":
        wire["proposals"][0]["event_id"] = float("nan")
    elif damage not in ("duplicate", "huge"):
        wire["proposals"][0]["candidate"] = {
            "metaprogram": "run_tac Lean.Elab.Tactic.setGoals []", "declaration": "axiom leak : False",
            "sorry": "sorry", "comments": "rfl -- okay", "blank": " ", "lines": "skip\n"*8 + "rfl"}[damage]
    text = json.dumps(wire)
    if damage == "duplicate":
        text = text.replace('"proposals":', '"proposals": [], "proposals":')
    elif damage == "huge":
        text = " " * 32769
    with pytest.raises(ValueError):
        parse_proposals(text, request)


def small_capture():
    # Synthetic anchor projection for parser/budget tests, NOT a native receipt.
    source = "theorem t (x : Nat) : x = x := by\n  let y := x\n  exact Eq.refl y\n"
    start, end = source.encode().index(b"let y"), source.encode().index(b"\n", source.index("exact"))
    event = {"id": "0", "status": "captured", "start": str(start), "end": str(end),
             "before": {"goals": ["g"]}, "after": {"goals": []}}
    return source, {"trace": {"events": [event]}, "trace_sha256": "a" * 64}


def test_router_call_and_prompt_budgets_abstain_without_hidden_retries():
    source, capture = small_capture()
    called = []
    def generate(prompt):
        called.append(prompt)
        return response(json.loads(prompt))
    proposer = ReplayRouter(generate, mode="offline_fixture", max_calls=1)
    assert proposer(source, capture, [], round_index=1, remaining=1)
    assert proposer(source, capture, [], round_index=2, remaining=1) == []
    assert len(called) == proposer.report()["calls_attempted"] == 1
    assert proposer.report()["records"][-1]["reason"] == "router_call_budget"
    small = ReplayRouter(generate, max_prompt_bytes=1024)
    assert small(source, capture, [], round_index=1, remaining=1) == []
    assert small.calls == 0 and len(called) == 1


def test_live_mode_requires_route_attestation_and_provider_errors_are_redacted():
    source, capture = small_capture()
    generate = lambda prompt: response(json.loads(prompt))
    live = ReplayRouter(generate, mode="live_requested")
    assert live(source, capture, [], round_index=1, remaining=1) == []
    assert live.report()["records"][0]["status"] == "rejected_response"
    def broken(prompt):
        raise RuntimeError("sensitive-marker-not-to-be-logged")
    proposer = ReplayRouter(broken)
    assert proposer(source, capture, [], round_index=1, remaining=1) == []
    assert "sensitive-marker" not in json.dumps(proposer.report())
    assert proposer.calls == 1


@pytest.mark.parametrize("damage", [None, "missing_trace", "missing_identity", "mismatch", "oversized_identity"])
def test_live_route_attestation_requires_complete_matching_identity(damage):
    source, capture = small_capture()
    generate = lambda prompt: response(json.loads(prompt))
    route = {"verified": True, "trace_available": True, "requested_provider": "fixture_transport",
             "actual_provider": "fixture_transport", "requested_model": "fixture_model", "actual_model": "fixture_model"}
    if damage == "missing_trace":
        route["trace_available"] = False
    elif damage == "missing_identity":
        route.pop("actual_model")
    elif damage == "mismatch":
        route["actual_model"] = "another_model"
    elif damage == "oversized_identity":
        route["requested_model"] = route["actual_model"] = "x" * 129
    generate.last_route_attestation = route
    proposer = ReplayRouter(generate, mode="live_requested")
    # Synthetic metadata validates the adapter protocol, not a hosted-model run.
    assert bool(proposer(source, capture, [], round_index=1, remaining=1)) == (damage is None)


@pytest.mark.parametrize("kwargs", [{"refinement_rounds": True}, {"refinement_rounds": 4},
    {"refinement_rounds": 1}, {"refine_fn": lambda *a: []}, {"max_proposals": 17}])
def test_invalid_refinement_budgets_do_not_capture_or_compile(kwargs):
    def forbidden(*a, **k):
        pytest.fail("bad budget reached native execution")
    with pytest.raises(ValueError):
        replay.collect_replay_pairs([], capture_fn=forbidden, replay_fn=forbidden,
            compile_fn=forbidden, environment_sha256=ENV, **kwargs)


@pytest.fixture(scope="module")
def native_router_run(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    directory = tmp_path_factory.mktemp("router-replay")
    kwargs = dict(project_root=directory, environment_sha256=ENV)
    phase = []

    class Guarded(dict):
        def __getitem__(self, key):
            if key in ("source", "target") and super().__getitem__("split") == "holdout":
                assert "checkpoint_frozen" in phase
            if key == "target" and super().__getitem__("split") == "train":
                pytest.fail("prewritten training label read")
            return super().__getitem__(key)

    rows = [Guarded(r) for r in compound_rows()]
    train_sources = {r["source"] for r in rows if r["split"] == "train"}

    def capture(source):
        assert source in train_sources and "grammar_frozen" not in phase
        return capture_source(source, **kwargs)

    def replay_fn(source, *args):
        assert source in train_sources and "grammar_frozen" not in phase
        return replay.replay_candidate(source, *args, **kwargs)

    def initial(source, captured):
        proposals = replay.closing_proposals(source, captured, candidates=("rfl", "assumption", "trivial"))
        if "compound_train_alias_reflexivity_" in source:
            # Deliberately restrict the baseline to exercise rejection->feedback
            # ->repair. This is not an ablation proving an LLM beats the hammer.
            proposals = [p for p in proposals if p["candidate"] == "rfl" and "let " not in
                source.encode()[int(captured["trace"]["events"][p["event_id"]]["start"]):
                                int(captured["trace"]["events"][p["event_id"]]["end"])].decode()]
            assert len(proposals) == 1
        return proposals

    def offline_generator(prompt):
        request = json.loads(prompt)
        assert request["source"] in train_sources and "grammar_frozen" not in phase
        assert "compound_train_alias_reflexivity_" in request["source"]
        assert all(a["status"] == "rejected" for a in request["feedback"])
        if request["round"] == 1:
            gate = request["feedback"][0]["whole_source_gate"][0]
            assert gate["reason"] == "proof_expression_growth"
            assert gate["source_proof"]["unique_expression_nodes"] == 7
            assert gate["target_proof"]["unique_expression_nodes"] == 8
            return response(request, "skip")
        assert request["round"] == 2
        assert request["feedback"][-1]["proposed"]["status"] == "open_goals"
        return response(request, "rfl")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rd, "compound_rows", lambda seed: rows)
        run = run_router_experiment(router_generate=offline_generator, router_mode="offline_fixture",
            capture_fn=capture, replay_fn=replay_fn,
            compile_fn=_lean_compiler(**kwargs, kernel_only=True, export_dags=True),
            environment_sha256=ENV, curriculum="compound", proposal_fn=initial,
            event=lambda e: phase.append(e["event"]))
    rd.save_run(run, directory / "run")
    print(f"\nNative router-fixture experiment report: {directory / 'run' / 'summary.md'}")
    return run


def test_native_feedback_repairs_atomic_teacher_before_training_and_freeze(native_router_run):
    run = native_router_run
    assert run["ok"], run.get("gates", run.get("reason"))
    teachers = run["training_pairs"]
    assert teachers["refinement_calls"] == run["router_refinement"]["calls_attempted"] == 2
    assert run["router_refinement"]["mode"] == "offline_fixture" and run["live_llm_used"] is False
    assert not run["router_refinement"]["production_router_memory_updated"]
    alias = next(r for r in run["manifest"] if r["split"] == "train" and r["family"] == "alias_reflexivity")
    attempts = [a for a in teachers["attempts"] if a["id"] == alias["id"]]
    assert [a["round"] for a in attempts] == [0, 1, 2]
    assert [a["status"] for a in attempts] == ["rejected", "rejected", "admitted_candidate"]
    assert teachers["selected_proposals"][alias["id"]]["round"] == 2
    assert len(teachers["pairs"]) == run["grammar"]["template_count"] == 5
    assert run["model_step"] == 120
    assert all(run["checkpoint"][k] == run["initial_checkpoint"][k] for k in rd.HEADS)
    for metric in ("rewrite_cross_entropy", "rewrite_expected_cosine_loss"):
        assert run["after"]["train"][metric] < run["before"]["train"][metric]
    holdout = run["holdout"]["holdout"]
    assert holdout["verified"] == 6 and holdout["verified_saved_tokens"] == 32
    assert run["holdout_zero_weights"]["holdout"]["verified_saved_tokens"] == 0
    assert run["checkpoint_promoted"] is False and run["official_score"] is None


def cached_training(run):
    sources = {r["id"]: r["source"] for r in run["manifest"]}
    captures = {sources[k]: v for k, v in run["training_pairs"]["captures"].items()}
    replays = {(sources[a["id"]], a["proposal"]["event_id"], a["proposal"]["candidate"]): a["replay"]
               for a in run["training_pairs"]["attempts"] if "replay" in a}
    receipts = {a["source"]: a["receipt"] for a in run["compile_attempts"]}
    return dict(capture_fn=lambda s: captures[s], replay_fn=lambda s,c,i,t: replays[s,i,t],
                compile_fn=lambda s: receipts[s], environment_sha256=ENV)


def test_refinement_budget_is_total_and_duplicate_endpoints_are_not_reexecuted(native_router_run):
    run = native_router_run
    row = next(r for r in run["manifest"] if r["split"] == "train" and r["family"] == "alias_reflexivity")
    proposal = next(a["proposal"] for a in run["training_pairs"]["attempts"] if a["id"] == row["id"])
    callbacks = cached_training(run)
    calls, remaining = [], []
    native = callbacks["replay_fn"]
    def counted(*args):
        calls.append(args[-1])
        return native(*args)
    def duplicate(s,c,feedback, **budget):
        remaining.append(budget["remaining"])
        # Mutation of callback-owned snapshots must not alter saved evidence.
        c.clear()
        feedback[0]["status"] = "admitted_candidate"
        return [proposal, proposal]
    result = replay.collect_replay_pairs([row], **{**callbacks, "replay_fn": counted},
        proposal_fn=lambda *a: [proposal], refine_fn=duplicate, refinement_rounds=3, max_proposals=3)
    assert not result["ok"] and not result["pairs"]
    assert len(result["attempts"]) == 3 and len(calls) == 1 and remaining == [2]
    assert result["attempts"][0]["status"] == "rejected" and result["captures"][row["id"]]
    assert result["attempts"][-1]["reason"] == "duplicate candidate endpoint"


def test_one_token_teachers_skip_router_calls_and_match_the_unguided_run(native_router_run):
    def forbidden(prompt):
        pytest.fail("one-token admitted teacher unnecessarily queried router")
    run = run_router_experiment(router_generate=forbidden, curriculum="compound", **cached_training(native_router_run))
    assert run["ok"] and run["router_refinement"]["calls_attempted"] == 0
    assert run["live_llm_used"] is False
    assert run["checkpoint"] == native_router_run["checkpoint"]
    assert run["gates"] == native_router_run["gates"]


def test_rejected_router_response_never_fabricates_a_teacher_or_reaches_training(native_router_run, monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("rejected response reached replay, compilation or training")
    callbacks = cached_training(native_router_run)
    callbacks.update(replay_fn=forbidden, compile_fn=forbidden)
    monkeypatch.setattr(rd.LeanIRAutoencoder, "train_batch", forbidden)
    run = run_router_experiment(router_generate=lambda _: '{"proof_admitted":true}',
        router_mode="offline_fixture", proposal_fn=lambda *a: [], curriculum="compound", **callbacks)
    assert not run["ok"] and run["reason"] == "replay_teacher_gate"
    assert not run["training_pairs"]["pairs"] and run["model_step"] == 0 and "checkpoint" not in run
    assert run["router_refinement"]["calls_attempted"] == 5
    assert all(r["status"] == "rejected_response" for r in run["router_refinement"]["records"])


def test_valid_but_unreachable_edit_teachers_return_diagnostics_without_updates(native_router_run, monkeypatch):
    monkeypatch.setattr(rd.LeanIRAutoencoder, "rewrite_objective", lambda *a: None)
    def forbidden(*a, **k):
        pytest.fail("missing edit label reached training")
    monkeypatch.setattr(rd.LeanIRAutoencoder, "train_batch", forbidden)
    run = run_router_experiment(router_generate=forbidden, curriculum="compound", **cached_training(native_router_run))
    assert not run["ok"] and run["reason"] == "unreachable_edit_teacher"
    assert len(run["unreachable_train_ids"]) == 5 and run["model_step"] == 0 and "checkpoint" not in run
    assert run["events"][-1]["event"] == "training_teacher_search"


@pytest.mark.parametrize("flags", [[], ["--router-provider", "example"], ["--router-model", "example"]])
def test_cli_requires_explicit_route_before_any_capture(tmp_path, monkeypatch, flags):
    def forbidden(*a, **k):
        pytest.fail("incomplete route reached execution")
    monkeypatch.setattr(rd, "capture_source", forbidden)
    with pytest.raises(SystemExit) as error:
        rd.main(["--environment-sha256", ENV, "--output-dir", str(tmp_path / "run"),
                 "--router-refinement-rounds", "1", *flags])
    assert error.value.code == 2 and not (tmp_path / "run").exists()


def test_router_report_binding_and_no_overwrite(native_router_run, tmp_path):
    run = native_router_run
    assert rd.render_summary(run) == rd.render_summary(run)
    assert "2 provider calls (offline_fixture)" in rd.render_summary(run)
    bad = copy.deepcopy(run)
    bad["router_refinement"]["mode"] = "live_requested"
    with pytest.raises(ValueError, match="invalid experiment receipt"):
        rd.save_run(bad, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
    rd.save_run(run, tmp_path / "run")
    before = (tmp_path / "run" / "run.json").read_bytes()
    assert rd.render_summary(json.loads(before)) == (tmp_path / "run" / "summary.md").read_text()
    with pytest.raises(FileExistsError):
        rd.save_run(run, tmp_path / "run")
    assert (tmp_path / "run" / "run.json").read_bytes() == before


def test_summary_family_order_survives_sorted_json_roundtrip(tmp_path):
    # Formatting fixture only; these are not native verification receipts.
    family = {"verified": 0, "sample_count": 1, "verified_saved_tokens": 0,
              "rows": [{"expression_nonregression": False, "applicable_edits": 0}]}
    group = {"verified_shortening": 0, "sample_count": 2, "cross_entropy": None,
             "rewrite_cross_entropy": None, "rewrite_expected_cosine_loss": None,
             "families": {"z_last": family, "a_first": family}}
    run = {"schema": rd.SCHEMA, "checkpoint": {}, "checkpoint_sha256": rd.digest({}),
           "manifest": [], "manifest_sha256": rd.digest([]), "before": {"train": group},
           "after": {"train": group}, "holdout": {"holdout": group},
           "holdout_zero_weights": {"holdout": group}, "scope": "formatting_fixture_not_verified",
           "model_step": 0, "compile_calls": 0, "gates": {}}
    original = rd.render_summary(run)
    assert original == rd.render_summary(json.loads(json.dumps(run, sort_keys=True)))
    rd.save_run(run, tmp_path / "run")
    assert original == rd.render_summary(json.loads((tmp_path / "run" / "run.json").read_text()))
    assert original == (tmp_path / "run" / "summary.md").read_text()
