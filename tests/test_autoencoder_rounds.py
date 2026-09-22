from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from jevops import autoencoder as ae


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "fixtures" / "autoencoder_score_baseline.json"
LEAN = shutil.which("lean")


def _sources() -> list[dict[str, str]]:
    return [
        {
            "id": "ae-intro",
            "text": "theorem ae_intro (h : True) : True := by\n  exact h",
        },
        {
            "id": "ae-rfl",
            "text": "theorem ae_rfl (n : Nat) : n = n := by\n  rfl",
        },
        {
            "id": "ae-simp",
            "text": "theorem ae_simp (n : Nat) : n + 0 = n := by\n  simp",
        },
    ]


def _proxy_score(report: dict[str, object]) -> float:
    """Higher is better for this offline training regression only."""

    return (
        0.65 / (1.0 + float(report["cross_entropy"]))
        + 0.25 * float(report["cosine_similarity"])
        + 0.10 * float(report["verifier_success_rate"] or 0.0)
    )


def _lean_compiler(cache: dict[str, dict[str, object]]):
    assert LEAN is not None

    def compile_one(source: str, problem: str = "") -> dict[str, object]:
        del problem
        key = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if key in cache:
            return dict(cache[key])
        with TemporaryDirectory(prefix="jevops-autoencoder-lean-") as temp:
            path = Path(temp) / "Main.lean"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [LEAN, str(path)],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        row = {
            "theorem_ok": result.returncode == 0,
            "token_count": len(source.split()),
            "stdout_tail": result.stdout[-240:],
            "stderr_tail": result.stderr[-240:],
        }
        cache[key] = row
        return dict(row)

    return compile_one


@pytest.mark.skipif(LEAN is None, reason="requires the elan lean executable")
def test_three_rounds_beat_frozen_local_proxy_without_leaking_oracle_text() -> None:
    rows = _sources()
    examples = [ae.coerce_training_example(row) for row in rows]
    config = ae.AutoencoderConfig(
        seed=37,
        learning_rate=0.08,
        warmup_steps=0,
        validation_fraction=0.0,
        canary_fraction=0.0,
        holdout_fraction=0.0,
    )
    # The historical scalar score was measured with the original vocabulary.
    # Keep that exact softmax support for both baseline and training instead
    # of silently rewriting the frozen score after adding new tactics.
    legacy_vocab = list(ae.LEAN_IR_OPS[:ae.LEAN_IR_OPS.index("decide") + 1]) + ["<eos>"]
    assert len(legacy_vocab) == 49
    model = ae.LeanIRAutoencoder.from_dict({"vocab": legacy_vocab}, config=config)
    compile_cache: dict[str, dict[str, object]] = {}
    compile_fn = _lean_compiler(compile_cache)

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    before = ae.evaluate_model(model, examples, compile_fn=compile_fn)
    assert abs(_proxy_score(before) - float(baseline["score"])) < 1e-12

    class RecordingTypeSafe:
        def __init__(self) -> None:
            self.states: list[dict[str, object]] = []

        def system_one(self, state, questions):
            self.states.append(dict(state))
            assert state["task"] == "lean_ir_fuzzy_theorem_assessment"
            assert "constraints" in state
            assert all("lean" not in row for row in state["candidates"])
            assert set(questions) == {"best", "semantic", "unsafe", "solves_goal"}
            first = state["candidates"][0]["id"]
            return SimpleNamespace(
                choices={"best": SimpleNamespace(choice=first, confidence=0.85)},
                scores={"semantic": SimpleNamespace(score=3.0)},
                nouls={
                    "unsafe": SimpleNamespace(noul=0.05),
                    "solves_goal": SimpleNamespace(noul=0.8),
                },
                model="fixture-typesafe",
            )

    client = RecordingTypeSafe()
    memory: dict[str, object] = {
        "nca": {
            "autoencoder": {"training_state": model.to_dict()},
            "grid": {
                "ptr://skill/port_autoencoder": {
                    "energy": 0.8,
                    "wins": 1,
                    "losses": 0,
                    "help": 1.0,
                    "unsafe": 0.0,
                }
            },
            "board_edges": [],
        }
    }
    rounds: list[dict[str, float | int]] = []
    for round_i in range(3):
        for row in rows:
            result = ae.refactor_smallest(
                memory,
                row["text"],
                problem=row["id"],
                compile_fn=compile_fn,
                typesafe_client=client,
                n_variations=2,
                train=True,
            )
            assert result["admission"] == "verified"
            assert result["lake_ok"] is True
            assert result["training"]["sample_count"] == 1

        model = ae.LeanIRAutoencoder.from_dict(
            memory["nca"]["autoencoder"]["training_state"]
        )
        report = ae.evaluate_model(model, examples, compile_fn=compile_fn, nca_memory=memory)
        rounds.append(
            {
                "round": round_i + 1,
                "step": model.step,
                "score": _proxy_score(report),
                "cross_entropy": float(report["cross_entropy"]),
                "cosine_similarity": float(report["cosine_similarity"]),
                "verifier_success_rate": float(report["verifier_success_rate"] or 0.0),
            }
        )

    assert [row["step"] for row in rounds] == [3, 6, 9]
    assert all(row["verifier_success_rate"] == 1.0 for row in rounds)
    assert rounds[-1]["cross_entropy"] < rounds[0]["cross_entropy"]
    assert rounds[-1]["cosine_similarity"] >= rounds[0]["cosine_similarity"]
    assert rounds[-1]["score"] > float(baseline["score"])
    assert rounds[-1]["score"] > rounds[0]["score"]
    assert len(client.states) == 9
    assert memory["nca"]["autoencoder"]["feedback"]["count"] == 9


@pytest.mark.skipif(LEAN is None, reason="requires the elan lean executable")
def test_three_rounds_beat_previous_smallest_verified_body_score() -> None:
    rows = [
        {
            "id": "redundant_true",
            "text": "theorem redundant_true (h : True) : True := by\n  have hx : True := h\n  exact hx",
        },
        {
            "id": "redundant_rfl",
            "text": "theorem redundant_rfl (n : Nat) : n = n := by\n  have hn : n = n := rfl\n  exact hn",
        },
        {
            "id": "redundant_simp",
            "text": "theorem redundant_simp (n : Nat) : n + 0 = n := by\n  simp\n  simp",
        },
        {
            "id": "long_true",
            "text": "theorem long_true (h : True) : True := by\n  have h1 : True := h\n  have h2 : True := h1\n  have h3 : True := h2\n  exact h3",
        },
    ]
    baseline = json.loads(
        (ROOT / "fixtures" / "autoencoder_smallest_baseline.json").read_text(encoding="utf-8")
    )
    compile_cache: dict[str, dict[str, object]] = {}
    compile_fn = _lean_compiler(compile_cache)
    memory: dict[str, object] = {"nca": {"grid": {}, "board_edges": []}}
    best: dict[str, int] = {}
    scores: list[float] = []

    for _round in range(3):
        for row in rows:
            result = ae.refactor_smallest(
                memory,
                row["text"],
                problem=row["id"],
                compile_fn=compile_fn,
                n_variations=8,
                train=True,
            )
            assert result["admission"] == "verified"
            assert result["lake_ok"] is True
            body_tokens = int(result["body_tokens"])
            assert body_tokens >= 1
            best[row["id"]] = min(best.get(row["id"], 10**9), body_tokens)
            assert body_tokens <= int(baseline["problems"][row["id"]]["previous_best_body_tokens"])

        scores.append(
            sum(
                1.0
                - best[row["id"]]
                / float(baseline["problems"][row["id"]]["source_body_tokens"])
                for row in rows
            )
            / len(rows)
        )

    assert scores[-1] >= scores[0]
    assert scores[-1] > float(baseline["score"])
    assert all(best[row["id"]] == 1 for row in rows)
    assert memory["nca"]["autoencoder"]["feedback"]["count"] == 12
