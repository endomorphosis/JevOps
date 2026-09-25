from __future__ import annotations

import shutil

import pytest

from jevops import replay_distillation as rd
from jevops.proof_replay import replay_candidate
from jevops.proof_replay import closing_proposals, collect_replay_pairs
from jevops.proof_state import capture_source
from jevops.replay_curriculum import transfer_rows
from jevops.rewrite_policy import body_of, choices, mine_template
from jevops.router_tuning import _lean_compiler

ENV = "a" * 64


def test_transfer_curriculum_is_reproducible_with_explicit_preservation_controls():
    rows = transfer_rows()
    assert rows == transfer_rows() and rows != transfer_rows(7)
    assert len(rows) == len({r["id"] for r in rows}) == len({r["source"] for r in rows}) == 15
    assert {s: sum(r["split"] == s for r in rows) for s in ("train", "validation", "canary", "holdout")} == {
        "train": 3, "validation": 3, "canary": 3, "holdout": 6}
    train = [r for r in rows if r["split"] == "train"]
    holdout = [r for r in rows if r["split"] == "holdout"]
    assert {r["context"] for r in train} == {"root"}
    assert all(r["context"] != "root" for r in holdout)
    # Offline grammar-coverage check only; not proof verification or training.
    templates = [mine_template(r["source"], body_of(r["target"])[1]) for r in train]
    for row in holdout:
        candidates = choices(row["source"], templates)
        assert any(c["body"] == body_of(row["target"])[1] for c in candidates)
        if row["context"] == "no_applicable_template":
            assert len(candidates) == 1 and row["target"] == row["source"]


@pytest.mark.parametrize("seed", [True, -1, 2**32, "1", None])
def test_curriculum_rejects_invalid_seeds(seed):
    with pytest.raises(ValueError):
        transfer_rows(seed)


@pytest.fixture(scope="module")
def transfer_run(tmp_path_factory):
    if shutil.which("lean") is None:
        pytest.skip("requires Lean")
    project = tmp_path_factory.mktemp("replay-transfer")
    kwargs = dict(project_root=project, environment_sha256=ENV)
    frozen = False
    class Guarded(dict):
        def __getitem__(self, key):
            if key in ("source", "target") and super().__getitem__("split") == "holdout":
                assert frozen, "holdout content accessed before freeze"
            if key == "target" and super().__getitem__("split") == "train":
                pytest.fail("training read a prewritten label")
            return super().__getitem__(key)
    rows = [Guarded(r) for r in transfer_rows()]
    train_sources = {r["source"] for r in rows if r["split"] == "train"}
    def capture(source):
        assert source in train_sources
        return capture_source(source, **kwargs)
    def replay(source, *args):
        assert source in train_sources
        return replay_candidate(source, *args, **kwargs)
    def event(item):
        nonlocal frozen
        if item["event"] == "checkpoint_frozen":
            frozen = True
    run = rd.run_experiment(rows=rows, curriculum="transfer", max_compiles=96, capture_fn=capture,
        replay_fn=replay, compile_fn=_lean_compiler(**kwargs, kernel_only=True, export_dags=True),
        environment_sha256=ENV, event=event)
    return run


def test_native_three_replay_teachers_transfer_without_holdout_rule_mining(transfer_run):
    run = transfer_run
    assert not run["ok"]  # The scoped-let challenge exposes expression growth.
    assert run["gates"]["validation"]["accepted"] and run["gates"]["canary"]["accepted"]
    assert not run["gates"]["coverage_and_cost"]["accepted"]
    assert run["model_step"] == run["checkpoint"]["rewrite_steps"] == 72
    assert run["grammar"]["template_count"] == 3
    assert run["checkpoint"]["rewrite_templates"] == run["initial_checkpoint"]["rewrite_templates"]
    assert all(run["checkpoint"][k] == run["initial_checkpoint"][k] for k in rd.HEADS)
    assert all(r["teacher_admitted"] for r in run["training_pairs"]["pairs"])
    assert run["training_pairs"]["selection_policy"] == "least_tokens_then_proposal_order"
    assert {rd._ir_body(r["target_ir"]).strip() for r in run["training_pairs"]["pairs"]} == {"assumption", "rfl", "trivial"}
    for split in ("train", "validation", "canary"):
        a, b = run["before"][split], run["after"][split]
        assert a["cross_entropy"] == b["cross_entropy"]
        assert b["rewrite_cross_entropy"] < a["rewrite_cross_entropy"]
        assert b["rewrite_expected_cosine_loss"] < a["rewrite_expected_cosine_loss"]


def test_transfer_report_does_not_count_inapplicability_as_learned_safety(transfer_run):
    holdout = transfer_run["holdout"]["holdout"]
    assert holdout["sample_count"] == 6
    assert holdout["target_reachable_count"] == holdout["loss_sample_count"] == holdout["verified_target_count"] == 5
    assert holdout["verified"] == 6 and holdout["verified_shortening"] == 3
    assert holdout["verified_saved_tokens"] == 9
    assert holdout["compression_sample_count"] == holdout["applicable_edit_sample_count"] == 4
    assert holdout["preservation_sample_count"] == holdout["identity_only_count"] == 2
    for r in holdout["rows"]:
        assert r["check"]["verified"]
        assert r["expression_nonregression"] == (r["family"] != "local_definition")
        if r["target_kind"] == "preservation":
            assert r["applicable_edits"] == 0 and r["prediction_unchanged"]
            assert r["loss"]["minimality_reward"] == 0
    zero = transfer_run["holdout_zero_weights"]["holdout"]
    assert zero["verified_saved_tokens"] == zero["verified_shortening"] == 0
    summary = rd.render_summary(transfer_run)
    assert summary == rd.render_summary(transfer_run)
    assert "4 compression targets; 2 preservation controls; 2 have no applicable edit" in summary
    assert "conjunction_branch" in summary and len(summary.splitlines()) < 50
    assert not transfer_run["semantic_family_decontamination"] and transfer_run["official_score"] is None


def test_locally_shorter_but_larger_proof_is_retained_without_reward_or_supervision(transfer_run):
    row = next(r for r in transfer_run["holdout"]["holdout"]["rows"] if r["family"] == "local_definition")
    assert row["prediction_tokens"] == 6 < row["source_tokens"] == 10
    assert row["check"]["source_proof"]["unique_expression_nodes"] == 7
    assert row["check"]["candidate_proof"]["unique_expression_nodes"] == 8
    assert row["check"]["reason"] == row["teacher_check"]["reason"] == "proof_expression_growth"
    assert row["minimality_reward"] == 0 and not row["verified_shortening"]
    assert row["loss"] is None and row["metric_status"] == "unverified_target"
    assert row["target_reachable"] is None


def saved_callbacks(run):
    """Trusted native fixtures for control-flow regressions, not fresh runs."""
    by_id = {r["id"]: r["source"] for r in run["manifest"]}
    captures = {by_id[k]: v for k, v in run["training_pairs"]["captures"].items()}
    replays = {(by_id[a["id"]], a["proposal"]["event_id"], a["proposal"]["candidate"]): a["replay"]
               for a in run["training_pairs"]["attempts"]}
    receipts = {a["source"]: a["receipt"] for a in run["compile_attempts"]}
    return dict(capture_fn=lambda s: captures[s], replay_fn=lambda s, c, i, t: replays[s, i, t],
                compile_fn=lambda s: receipts.get(s, {"theorem_ok": False}), environment_sha256=ENV)


def test_validation_duplicate_is_rejected_before_any_weight_update(transfer_run, monkeypatch):
    rows = transfer_rows()
    next(r for r in rows if r["split"] == "validation")["source"] = rows[0]["source"]
    def forbidden(*a, **k):
        pytest.fail("leaked development source reached training")
    monkeypatch.setattr(rd.LeanIRAutoencoder, "train_batch", forbidden)
    with pytest.raises(ValueError, match="cross-split source leakage"):
        rd.run_experiment(rows=rows, curriculum="transfer", **saved_callbacks(transfer_run))


def test_equal_token_teacher_priority_is_not_a_theorem_name_hash_order(transfer_run):
    row = transfer_rows()[0]
    for order in (("trivial", "assumption"), ("assumption", "trivial")):
        result = collect_replay_pairs([row], **saved_callbacks(transfer_run),
            proposal_fn=lambda s, c: closing_proposals(s, c, candidates=order))
        assert result["ok"] and result["pairs"][0]["target_tokens"] == 1
        assert body_of(result["pairs"][0]["target_text"])[1] == order[0]


def test_holdout_duplicate_is_checked_lazily_after_freeze(transfer_run):
    rows = transfer_rows()
    next(r for r in rows if r["split"] == "holdout")["source"] = rows[0]["source"]
    events = []
    with pytest.raises(ValueError, match="cross-split source leakage"):
        rd.run_experiment(rows=rows, curriculum="transfer", event=events.append, **saved_callbacks(transfer_run))
    assert events[-2]["event"] == "checkpoint_frozen" and events[-1]["event"] == "final_holdout"


def test_missing_edit_label_coverage_cannot_pass_even_when_predictions_compile(transfer_run, monkeypatch):
    objective = rd.LeanIRAutoencoder.rewrite_objective
    def incomplete(self, ex):
        if "transfer_holdout_polymorphic_reflexivity" in ex.text:
            return None
        return objective(self, ex)
    monkeypatch.setattr(rd.LeanIRAutoencoder, "rewrite_objective", incomplete)
    run = rd.run_experiment(curriculum="transfer", **saved_callbacks(transfer_run))
    assert not run["ok"]
    assert run["holdout"]["holdout"]["verified"] == 6
    assert run["holdout"]["holdout"]["target_reachable_count"] == 4
    assert not run["checkpoint_promoted"]
