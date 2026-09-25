from __future__ import annotations

import copy
import shutil

import pytest

from jevops import replay_distillation as rd
from jevops.proof_replay import replay_candidate
from jevops.proof_state import capture_source
from jevops.replay_curriculum import compound_regressions, compound_rows, transfer_rows
from jevops.rewrite_policy import body_of, choices, mine_template
from jevops.router_tuning import _lean_compiler

ENV = "a" * 64


def test_compound_protocol_keeps_old_failure_separate_and_has_required_binding_control():
    old = transfer_rows()
    rows = compound_rows()
    assert rows == compound_rows() and rows != compound_rows(7)
    assert len(rows) == len({r["id"] for r in rows}) == len({r["source"] for r in rows}) == 21
    assert {s: sum(r["split"] == s for r in rows) for s in ("train", "validation", "canary", "holdout")} == {
        "train": 5, "validation": 5, "canary": 5, "holdout": 6}
    assert not {r["id"] for r in rows} & {r["id"] for r in old}
    bank = [mine_template(r["source"], body_of(r["target"])[1]) for r in rows if r["split"] == "train"]
    for row in rows:
        candidates = choices(row["source"], bank)
        assert any(c["body"] == body_of(row["target"])[1] for c in candidates)
        if row["family"].startswith("preserve_"):
            assert len(candidates) == 1 and row["target"] == row["source"]
    regression, = compound_regressions()
    previous = next(r for r in old if r["family"] == "local_definition")
    assert regression["source"] == previous["source"]
    assert regression["previous_reference"] == previous["target"] != regression["target"]
    assert regression["split"] == "regression" and regression["previous_split"] == "holdout"
    assert transfer_rows() == old


@pytest.mark.parametrize("seed", [True, -1, 2**32, "1", None])
def test_compound_rejects_invalid_seeds(seed):
    with pytest.raises(ValueError):
        compound_rows(seed)


@pytest.fixture(scope="module")
def compound_run(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    kwargs = dict(project_root=tmp_path_factory.mktemp("compound-replay"), environment_sha256=ENV)
    phase = []

    class Guarded(dict):
        def __getitem__(self, key):
            split = super().__getitem__("split")
            if key in ("source", "target") and split in ("holdout", "regression"):
                assert "checkpoint_frozen" in phase, "evaluation content accessed before freeze"
            if key == "target" and split == "train":
                pytest.fail("training read a prewritten target instead of discovering it")
            return super().__getitem__(key)

    rows = [Guarded(r) for r in compound_rows()]
    train_sources = {r["source"] for r in rows if r["split"] == "train"}

    def capture(source):
        assert source in train_sources and "training" not in phase
        return capture_source(source, **kwargs)

    def replay(source, *args):
        assert source in train_sources and "training" not in phase
        return replay_candidate(source, *args, **kwargs)

    def regressions():
        assert phase[-1] == "known_regression_probes"
        assert phase.index("checkpoint_frozen") < phase.index("final_holdout")
        return [Guarded(r) for r in compound_regressions()]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rd, "compound_rows", lambda seed: rows)
        patch.setattr(rd, "compound_regressions", regressions)
        return rd.run_experiment(curriculum="compound", max_compiles=128,
            capture_fn=capture, replay_fn=replay,
            compile_fn=_lean_compiler(**kwargs, kernel_only=True, export_dags=True),
            environment_sha256=ENV, event=lambda e: phase.append(e["event"]))


def test_native_atomic_teachers_preserve_rejected_partial_edit_and_provenance(compound_run):
    run = compound_run
    assert run["ok"], run.get("gates")
    teachers = run["training_pairs"]
    manifest = {r["id"]: r for r in run["manifest"]}
    assert len(teachers["pairs"]) == len(teachers["selected_proposals"]) == 5
    assert set(teachers["captures"]) == {r["id"] for r in run["manifest"] if r["split"] == "train"}
    for pair in teachers["pairs"]:
        choice = teachers["selected_proposals"][pair["id"]]
        attempt = teachers["attempts"][choice["attempt_index"]]
        assert attempt["id"] == pair["id"] and attempt["status"] == "admitted_candidate"
        assert choice["pair_sha256"] == pair["pair_sha256"]
        assert choice["replay_sha256"] == attempt["replay"]["native_sha256"]
        assert choice["atomic_source_to_target"] and not choice["intermediate_teacher_created"]
        assert pair["teacher_admitted"]
        if manifest[pair["id"]]["family"] == "alias_reflexivity":
            source = manifest[pair["id"]]["source"].encode()
            span = source[int(choice["source_span"]["start"]):int(choice["source_span"]["end"])].decode()
            assert "let " in span and "exact Eq.refl" in span
            assert body_of(pair["target_text"])[1] == "rfl"
            rejected = [a for a in teachers["attempts"] if a["id"] == pair["id"]
                        and a["status"] == "rejected" and a.get("replay", {}).get("ok")]
            assert any("proof_expression_growth" in str(a.get("whole_source_gate")) for a in rejected)


def test_compound_trains_edit_ce_cosine_with_frozen_reconstruction_and_one_step(compound_run):
    run = compound_run
    assert run["model_step"] == run["checkpoint"]["rewrite_steps"] == 120
    assert run["grammar"]["template_count"] == 5
    assert run["checkpoint"]["rewrite_templates"] == run["initial_checkpoint"]["rewrite_templates"]
    assert all(run["checkpoint"][k] == run["initial_checkpoint"][k] for k in rd.HEADS)
    for split in ("train", "validation", "canary"):
        before, after = run["before"][split], run["after"][split]
        assert before["cross_entropy"] == after["cross_entropy"]
        assert after["rewrite_cross_entropy"] < before["rewrite_cross_entropy"]
        assert after["rewrite_expected_cosine_loss"] < before["rewrite_expected_cosine_loss"]
    assert run["config"]["rewrite_max_edits"] == 1
    holdout = run["holdout"]["holdout"]
    assert holdout["sample_count"] == holdout["verified"] == holdout["verified_target_count"] == 6
    assert holdout["target_reachable_count"] == holdout["rewrite_sample_count"] == 6
    assert holdout["verified_shortening"] == 4 and holdout["verified_saved_tokens"] == 32
    for row in holdout["rows"]:
        assert row["expression_nonregression"]
        policy = row["rewrite_policy"]
        assert not policy["teacher_used"] and not policy["solver_used"]
        assert len(policy["trace"]) == (1 if row["target_kind"] == "compression" else 0)
        if row["target_kind"] == "preservation":
            assert row["applicable_edits"] == 0 and row["prediction_unchanged"]
    zero = run["holdout_zero_weights"]["holdout"]
    assert zero["verified_saved_tokens"] == zero["verified_shortening"] == 0
    assert run["official_score"] is None and not run["arena_data_used"] and not run["checkpoint_promoted"]
    assert not any(run[k] for k in ("live_llm_used", "nca_trained", "jev_updates_used", "open_state_encoder_trained"))


def test_inspected_failure_is_only_a_known_post_freeze_regression_probe(compound_run):
    run = compound_run
    regression, = run["known_regressions"]["regression"]["rows"]
    assert regression["source_tokens"] == 10 and regression["prediction_tokens"] == 1
    assert regression["verified_shortening"]
    assert regression["check"]["source_proof"]["unique_expression_nodes"] == 7
    assert regression["check"]["candidate_proof"]["unique_expression_nodes"] == 6
    assert regression["check"]["candidate_proof"]["expanded_expression_nodes"] == 7
    previous = regression["previous_reference_check"]
    assert previous["verified"] and not previous["expression_nonregression"]
    assert previous["candidate_proof"]["unique_expression_nodes"] == 8
    assert previous["reason"] == "proof_expression_growth"
    assert regression["id"] not in {r["id"] for r in run["manifest"]}
    assert not run["known_regressions_used_for_training_or_gates"]
    assert run["regression_manifest_sha256"] == rd.digest(run["regression_manifest"])
    events = [e["event"] for e in run["events"]]
    assert events.index("training") < events.index("checkpoint_frozen") < events.index("final_holdout") < events.index("known_regression_probes")
    summary = rd.render_summary(run)
    assert summary == rd.render_summary(run) and len(summary.splitlines()) < 50
    assert "not fresh holdouts or gate inputs" in summary
    corrupted = copy.deepcopy(run)
    corrupted["regression_manifest"][0]["target"] = "forged"
    with pytest.raises(ValueError, match="invalid experiment receipt"):
        rd.render_summary(corrupted)


def test_regression_failure_cannot_influence_current_gates_or_weights(compound_run):
    # Cached native fixtures test isolation, not a second fresh benchmark run.
    original = compound_run
    by_id = {r["id"]: r["source"] for r in original["manifest"]}
    captures = {by_id[k]: v for k, v in original["training_pairs"]["captures"].items()}
    replays = {(by_id[a["id"]], a["proposal"]["event_id"], a["proposal"]["candidate"]): a["replay"]
               for a in original["training_pairs"]["attempts"]}
    receipts = {a["source"]: a["receipt"] for a in original["compile_attempts"]}
    regression_id = original["regression_manifest"][0]["id"]
    run = rd.run_experiment(curriculum="compound",
        capture_fn=lambda s: captures[s], replay_fn=lambda s, c, i, t: replays[s, i, t],
        compile_fn=lambda s: {"theorem_ok": False} if regression_id in s else receipts[s],
        environment_sha256=ENV)
    assert run["known_regressions"]["regression"]["verified"] == 0
    assert run["known_regressions"]["regression"]["verified_saved_tokens"] == 0
    assert run["known_regressions"]["regression"]["loss_sample_count"] == 0
    assert run["max_compiles"] == 128 and run["compile_calls"] < run["max_compiles"]
    assert run["ok"] == original["ok"] and run["gates"] == original["gates"]
    assert run["checkpoint"] == original["checkpoint"]
    assert run["holdout"] == original["holdout"]
