from __future__ import annotations

import json
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
        "typesafe_available": False,
        "typesafe_reason": "accelerator_checkout_missing",
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
