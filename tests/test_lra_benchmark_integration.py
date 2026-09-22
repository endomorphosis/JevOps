from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess

from jevops.router_tuning import RouterTuningConfig


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "papers" / "completion" / "lean_refactor_arena" / "harness"

import sys

if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import autoencoder_bridge as bridge  # noqa: E402
import codepath_graph  # noqa: E402
import splice  # noqa: E402

# The harness modules are intentionally loaded as an isolated, legacy
# top-level module set.  Do not leave their directory on the process-wide
# import path: JevOps's optional consumer discovery must remain fail-closed
# for the core-kernel tests that run in the same pytest process.
while str(HARNESS) in sys.path:
    sys.path.remove(str(HARNESS))


def test_frozen_lra_records_bind_and_keep_digest() -> None:
    raw, digest, records = bridge.load_records()
    assert len(records) == 15
    assert digest == splice.FROZEN_WARMUP_SHA256
    assert len(raw) == 113826
    assert all(
        splice.split_statement_body(record).reconstructed_src == record["src"]
        for record in records
    )


def test_kernel_refactor_receipt_preserves_statement_and_reproduces_one_token_edit() -> None:
    """Validate a recorded real compile, not a substitute for recompilation."""
    from jevops.logic_refactor import reduction_variants
    from jevops.proof_trust import audit_axioms

    evidence = json.loads((ROOT / "tests/fixtures/kernel_refactor_local_best.json").read_text())
    _, digest, records = bridge.load_records()
    record = next(r for r in records if r["name"] == evidence["name"])
    assert evidence["frozen_sha256"] == digest
    before, after = evidence["previous_best_source"], evidence["best_source"]
    assert before.startswith(record["statement"]) and after.startswith(record["statement"])
    change = evidence["transformation"]
    assert before.count(change["before"]) == 1
    assert before.replace(change["before"], change["after"], 1) == after
    assert hashlib.sha256(after.encode()).hexdigest() == evidence["source_sha256"]
    original_body = bridge._candidate_tactics(record, record["src"])
    old_body = bridge._candidate_tactics(record, before)
    new_body = bridge._candidate_tactics(record, after)
    assert bridge.lra_loop.token_count(original_body) == evidence["source_body_tokens"] == 482
    assert bridge.lra_loop.token_count(old_body) == evidence["historical_seed_tokens_reverified"] == 392
    assert bridge.lra_loop.token_count(new_body) == evidence["best_body_tokens"] == 391
    variants = reduction_variants(old_body, strategy="rewrite_transport", cap=64)
    assert any(kind == "exact_to_assumption" and body.strip() == new_body.strip()
               for kind, body, _ in variants)
    receipt = evidence["fresh_recheck"]
    assert receipt["lake_ok"] and receipt["kernel_only"] and not receipt["sorry_in_theorem"]
    audit = audit_axioms(receipt["axiom_report_stdout_tail"], [evidence["name"]])
    assert audit == receipt["kernel_audit"] and audit["accepted"]
    assert audit["axioms"] == ["Quot.sound", "propext"]
    assert evidence["official_score"] is None and evidence["arena_score"] is None
    assert not evidence["training_enabled"] and not evidence["production_memory_used"]
    assert evidence["model_evaluation"]["body_tokens"] == 482  # Search is not model compression.


def test_experimental_bridge_keeps_verified_target_and_model_loss_separate() -> None:
    _raw, _digest, records = bridge.load_records()
    record = records[0]

    def fake_router(_prompt: str) -> str:
        return json.dumps(
            {
                "strategies": ["drop_unused_haves"],
                "candidates": [{"kind": "short", "tactics": "trivial"}],
            }
        )

    def compile_factory(row):
        statement = str(row["statement"])

        def compile_candidate(source: str, problem: str = ""):
            del problem
            assert source.startswith(statement)
            return {
                "theorem_ok": True,
                "lake_ok": True,
                "token_count": len(source.split()),
                "all_tags_ok": True,
                "sorryAx": False,
            }

        return compile_candidate

    result = bridge.run_benchmark(
        names=[str(record["name"])],
        config=RouterTuningConfig(rounds=1, n_variations=1, max_candidate_pool=8),
        compile_fn_factory=compile_factory,
        router_generate=fake_router,
    )

    assert result["n_selected"] == 1
    assert result["n_verified"] == 1
    assert result["arena_score"] is None
    row = result["results"][0]
    assert row["benchmark"]["statement_prefix_bound"] is True
    assert row["benchmark"]["arena_score"] is None
    training = row["history"][0]["training"]
    assert "loss" in training
    assert "candidate_target_loss" in training
    assert training["loss"]["ir_exact_match"] == 0.0
    assert training["candidate_target_loss"]["ir_exact_match"] == 1.0
    assert row["model_body_tokens_after"] > row["best_body_tokens"]
    assert result["reward_hacking_checks"]["model_loss_is_separate_from_candidate_target"]


def test_experimental_bridge_traverses_the_frozen_set_without_an_arena_score() -> None:
    """Exercise every frozen record while keeping synthetic admission explicit."""

    def fake_router(_prompt: str) -> str:
        return json.dumps(
            {
                "strategies": ["drop_unused_haves"],
                "candidates": [{"kind": "short", "tactics": "trivial"}],
            }
        )

    def compile_factory(row):
        statement = str(row["statement"])

        def compile_candidate(source: str, problem: str = ""):
            del problem
            bound = source.startswith(statement)
            return {
                "theorem_ok": bound,
                "lake_ok": bound,
                "token_count": len(source.split()),
                "all_tags_ok": bound,
                "sorryAx": False,
            }

        return compile_candidate

    result = bridge.run_benchmark(
        config=RouterTuningConfig(rounds=1, n_variations=1, max_candidate_pool=8),
        compile_fn_factory=compile_factory,
        router_generate=fake_router,
    )

    assert result["n_selected"] == 15
    assert result["n_verified"] == 15
    assert result["source_body_tokens_total"] > result["best_body_tokens_total"] > 0
    assert result["model_body_tokens_after_total"] > 0
    assert result["mean_model_cross_entropy"] is not None
    assert result["mean_model_cosine_similarity"] is not None
    assert result["reward_hacking_checks"] == {
        "statement_prefix_bound_for_verified": True,
        "model_loss_is_separate_from_candidate_target": True,
        "official_scores_null": True,
    }
    assert result["arena_score"] is None
    assert result["official_score"] is None


def test_lra_optional_repositories_are_configurable_without_host_paths(tmp_path: Path) -> None:
    """Path overrides must reach every adapter without importing a host checkout."""

    accel = tmp_path / "accelerate"
    datasets = tmp_path / "datasets"
    state = tmp_path / "state"
    env = os.environ.copy()
    env.update(
        {
            "LRA_IPFS_ACCELERATE_PATH": str(accel),
            "LRA_IPFS_DATASETS_PATH": str(datasets),
            "LRA_STATE_ROOT": str(state),
        }
    )
    code = f"""
import json
import sys
sys.path.insert(0, {str(HARNESS)!r})
import _jevops_path
import _optional_deps
import generate_text
import receipt_store
import typesafe_router
print(json.dumps({{
    "accel": str(_jevops_path.IPFS_ACCELERATE_ROOT),
    "typesafe": str(typesafe_router.TYPESAFE_INFERENCE_PATH),
    "router": str(_jevops_path.LLM_ROUTER_PATH),
    "datasets": str(receipt_store.DATASETS_ROOT),
    "state": str(_jevops_path.LRA_STATE_ROOT),
    "generate_text_accel": str(generate_text.ACCEL_ROOT),
    "typesafe_available": _optional_deps.load_typesafe()[0] is not None,
    "typesafe_reason": _optional_deps.load_typesafe()[1],
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(completed.stdout)
    assert observed == {
        "accel": str(accel),
        "typesafe": str(accel / "ipfs_accelerate_py" / "typesafe_inference.py"),
        "router": str(accel / "ipfs_accelerate_py" / "llm_router.py"),
        "datasets": str(datasets),
        "state": str(state),
        "generate_text_accel": str(accel),
        "typesafe_available": True,
        "typesafe_reason": "in_tree",
    }


def test_nca_runtime_sidecars_leave_the_arena_source_tree() -> None:
    """NCA runtime state must not turn curated benchmark data into build output."""

    import _jevops_path
    import codepath_graph

    source_canaries = ROOT / "papers" / "completion" / "lean_refactor_arena" / "evidence" / "canaries"
    assert codepath_graph.SIDECAR.parent == _jevops_path.LRA_NCA_ROOT
    assert codepath_graph.SIDECAR_DUCKDB.parent == _jevops_path.LRA_NCA_ROOT
    assert codepath_graph.SIDECAR.parent != source_canaries
    assert _jevops_path.LRA_CAS_ROOT != source_canaries / "nca-cas"


def test_outer_inner_halt_is_terminal_and_preserves_fail_closed_score_fields() -> None:
    from jevops.walk import halt_step

    memory = {
        "nca": {
            "grid": {
                "ptr://goal/LRA-G000": {"kind": "goal", "id": "ptr://goal/LRA-G000", "energy": 0.4},
                "ptr://task/LRA-024": {
                    "kind": "task",
                    "id": "ptr://task/LRA-024",
                    "energy": 0.05,
                    "blocked": True,
                    "do_not_fork": True,
                },
            },
            "program_state": {"ops": [{"op": "KEEP"}], "last_ran": [{"op": "TICK"}]},
        }
    }
    stepped = halt_step(memory, depth=0, name="fixture", round_i=2)
    assert stepped["flow"] == "break"
    assert stepped["trace"]["action"] == "nca_halt"
    assert stepped["lake"]["skipped"] == "nca_halt"
    assert stepped["halt"]["budget_dead"] is False


def test_putnam_bridge_uses_the_generated_project_not_a_nonexistent_clone(monkeypatch, tmp_path: Path) -> None:
    seen = []
    record = {"source": "putnambench", "statement": "theorem test : True"}

    def no_clone(*args, **kwargs):
        raise AssertionError("Putnam records have no Git clone")

    def compile_tactics(rec, tactics, **kwargs):
        seen.append(kwargs)
        return {"theorem_ok": True, "token_count": 1, "all_tags_ok": True}

    monkeypatch.setattr(bridge.lra_keepbest.lra_cw, "clone_dir", no_clone)
    monkeypatch.setattr(bridge.lra_keepbest, "compile_tactics", compile_tactics)
    result = bridge.compiler_for_record(record, state_root=tmp_path, network="deny")(
        "theorem test : True := by\n  trivial")
    assert result["theorem_ok"]
    assert seen[0]["restore"] == b"" and seen[0]["network"] == "deny"


def test_bridge_refuses_to_overwrite_modified_cached_source(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace

    dest = tmp_path / "Source.lean"
    current = b"-- somebody else's edit\ntheorem test : True := by trivial\n"
    dest.write_bytes(current)
    record = {"source": "strata", "statement": "theorem test : True", "url": "https://example.com/repo"}
    monkeypatch.setattr(bridge.lra_keepbest.lra_cw, "clone_dir", lambda *args: tmp_path)
    monkeypatch.setattr(bridge.lra_keepbest.lra_cw, "source_relpath", lambda _: "Source.lean")
    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=b"theorem test : True := by trivial\n"))

    def should_not_compile(*args, **kwargs):
        raise AssertionError("modified source must not be compiled/spliced")

    monkeypatch.setattr(bridge.lra_keepbest, "compile_tactics", should_not_compile)
    result = bridge.compiler_for_record(record, state_root=tmp_path)("theorem test : True := by\n  trivial")
    assert not result["theorem_ok"] and result["reason"] == "cached_source_modified"
    assert dest.read_bytes() == current


def test_isolated_validation_has_no_training_or_model_winner_substitution(monkeypatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("validate_logic_reductions", HARNESS / "validate_logic_reductions.py")
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(HARNESS))
        spec.loader.exec_module(module)
    record = {"name": "test", "source": "fixture", "statement": "theorem test (h : True) : True",
              "version_info": [{"v4.26.0": "a" * 40}],
              "src": "theorem test (h : True) : True := by\n  have hx : True := h\n  exact hx"}
    result = module.evaluate_record(record, rounds=1, pool=8, seed_history=False,
                                    compiler=lambda source, **kw: {"theorem_ok": source.startswith(record["statement"])})
    assert result["model_step"] == 0 and not result["training_enabled"]
    assert result["mode"] == "unseeded_evaluation" and result["nca_memory_discarded"]
    assert result["model_evaluation"]["loss"]["ir_exact_match"] != 1
    assert result["official_score"] is None and result["arena_score"] is None
    assert all(not h["training"]["trained"] for h in result["history"])


def test_checkpoint_benchmark_reports_raw_and_guarded_models_without_training(monkeypatch) -> None:
    import hashlib
    import importlib.util
    import pytest
    from jevops.autoencoder_training import LeanIRAutoencoder

    spec = importlib.util.spec_from_file_location("validate_logic_reductions", HARNESS / "validate_logic_reductions.py")
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(HARNESS))
        spec.loader.exec_module(module)
    record = {"name": "test", "source": "fixture", "statement": "theorem test (h : True) : True",
              "version_info": [{"v4.26.0": "a" * 40}],
              "src": "theorem test (h : True) : True := by\n  have hx : True := h\n  exact hx"}
    model = LeanIRAutoencoder()
    model.state["step"] = 1
    model.state["op_bias"].update(have=-9.0, exact=2.0)
    state = model.to_dict()
    checkpoint = {"state": state, "config": model.config.to_dict(),
                  "state_sha256": hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()}
    result = module.evaluate_record(record, rounds=1, pool=8, seed_history=False, checkpoint=checkpoint,
                                    compiler=lambda s, **kw: {"theorem_ok": "have hx" in s})
    assert result["model_step"] == 1 and result["model_checkpoint"]["evaluation_only"]
    assert result["model_evaluation"]["lake_ok"]
    assert not result["model_evaluation"]["raw_ablation"]["lake_ok"]
    assert result["model_evaluation"]["raw_ablation"]["loss"]["minimality_reward"] == 0.0
    assert result["model_evaluation"]["dependency_guard"]["restored"]
    assert hashlib.sha256(json.dumps(checkpoint["state"], sort_keys=True).encode()).hexdigest() == checkpoint["state_sha256"]
    assert not result["training_enabled"]
    with pytest.raises(ValueError, match="digest"):
        module.evaluate_record(record, checkpoint={**checkpoint, "state_sha256": "wrong"})
