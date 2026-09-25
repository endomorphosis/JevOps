#!/usr/bin/env python3
"""Eval watcher: collect outer-loop lake rows and accept only a real cut."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ImproveWatchTests(unittest.TestCase):
    def test_numpy_not_imported(self) -> None:
        import jevops.improve_watch as watch_mod

        self.assertNotIn("numpy", sys.modules)
        self.assertFalse(watch_mod.shorter({"tokens": 10, "lake_ok": True}, {"tokens": 10, "lake_ok": True}))

    def test_shorter_requires_a_cut_and_no_regression(self) -> None:
        from jevops.improve_watch import shorter

        before = {"tokens": 100, "heartbeats": 50, "lake_ok": True, "sorry": False}
        self.assertTrue(shorter(before, {"tokens": 90, "heartbeats": 50, "lake_ok": True}))
        self.assertTrue(shorter(before, {"tokens": 100, "heartbeats": 40, "lake_ok": True}))
        self.assertFalse(shorter(before, {"tokens": 90, "heartbeats": 60, "lake_ok": True}))
        self.assertFalse(shorter(before, {"tokens": 90, "heartbeats": 40, "lake_ok": False}))
        self.assertFalse(shorter(before, {"tokens": 80, "lake_ok": True, "sorry": True}))

    def test_on_step_records_the_proof(self) -> None:
        from jevops.improve_watch import EvalWatch

        with tempfile.TemporaryDirectory() as tmp:
            watch = EvalWatch(Path(tmp) / "evals.jsonl")
            watch.on_step(
                {
                    "step": 1,
                    "last_lake": [
                        {
                            "name": "Core.InitsUpdatesComm",
                            "ok": True,
                            "tokens": 139,
                            "maxHeartbeats": 200,
                            "tactics": "x" * 500,
                            "sorryAx": False,
                        }
                    ],
                    "payload": {"lake": [{"name": "ignored-duplicate", "ok": True, "tokens": 1}]},
                }
            )
            self.assertEqual(len(watch.rows), 1)
            self.assertEqual(watch.rows[0]["tokens"], 139)
            self.assertEqual(watch.rows[0]["heartbeats"], 200)
            self.assertEqual(watch.rows[0]["proof"], "x" * 500)
            text = Path(tmp, "evals.jsonl").read_text(encoding="utf-8")
            self.assertIn("xxxxx", text)

    def test_improve_keeps_only_a_shorter_reeval_and_rolls_back(self) -> None:
        from jevops.improve_watch import EvalWatch

        watch = EvalWatch(memory={})
        watch.observe(
            {"name": "P", "ok": True, "tokens": 100, "heartbeats": 40, "stem": "comma"},
            source="lake",
        )

        def generate(_prompt: str) -> str:
            return json.dumps({"action": "skip_stem", "stem": "comma", "name": "P", "reason": "losses"})

        def shorter_eval(_action, _memory):
            return {"name": "P", "ok": True, "tokens": 80, "heartbeats": 40}

        kept = watch.improve_round(shorter_eval, generate_fn=generate, llm=True)
        self.assertTrue(kept["accepted"])
        self.assertIn("P::port_comma", watch.memory.get("blacklist", []))

        watch.memory.clear()
        watch.observe(
            {"name": "P", "ok": True, "tokens": 80, "heartbeats": 40, "stem": "comma"},
            source="lake",
        )

        def longer_eval(_action, _memory):
            return {"name": "P", "ok": True, "tokens": 80, "heartbeats": 90}

        rejected = watch.improve_round(longer_eval, generate_fn=generate, llm=True)
        self.assertFalse(rejected["accepted"])
        self.assertNotIn("blacklist", watch.memory)

    def test_refuses_lean_text_and_hooks_run_steps(self) -> None:
        from jevops.improve_watch import EvalWatch
        from jevops.outer import run_steps

        watch = EvalWatch()

        def generate(_prompt: str) -> str:
            return json.dumps({"action": "update_code", "path": "Proof.lean", "old": "a", "new": "b"})

        proposal = watch.propose(generate_fn=generate, llm=True)
        self.assertEqual(proposal["action"], "run")
        self.assertEqual(proposal["reason"], "refusing_lean_path")

        seen: dict[str, str] = {}

        def see_proof(prompt: str) -> str:
            seen["prompt"] = prompt
            return json.dumps({"action": "run", "reason": "read"})

        watch.observe(
            {"name": "P", "ok": True, "tokens": 12, "heartbeats": 3, "tactics": "simp [h]"},
            source="lake",
        )
        watch.propose(generate_fn=see_proof, llm=True)
        self.assertIn("simp [h]", seen["prompt"])

        def inner(_step):
            return {"lake": [{"name": "Q", "ok": True, "tokens": 12, "heartbeats": 3}]}

        run_steps(
            n=1,
            memory={},
            llm=False,
            gaps_fn=lambda: [],
            route_fn=lambda **_k: {"action": "nest_inner"},
            apply_fn=lambda _m, _a: {"ok": True},
            inner_fn=inner,
            board_fn=lambda: ({"Q": 12}, 12),
            on_step=watch.on_step,
        )
        self.assertEqual(watch.summary()["problems"][0]["best_tokens"], 12)
        self.assertEqual(watch.summary()["problems"][0]["best_heartbeats"], 3)

    def test_run_outer_uses_router_on_collected_losses(self) -> None:
        from jevops.improve_watch import EvalWatch

        watch = EvalWatch(memory={})

        def inner(_step):
            return {
                "lake": [
                    {"name": "P", "ok": True, "tokens": 100, "heartbeats": 40, "kind": "keep"},
                    {"name": "P", "ok": False, "tokens": 100, "heartbeats": 40, "kind": "port_comma"},
                ]
            }

        def generate(_prompt: str) -> str:
            return json.dumps({"action": "run", "reason": "no_opinion"})

        def reeval(_action, _memory):
            return {"name": "P", "ok": True, "tokens": 90, "heartbeats": 40, "stem": "keep"}

        result = watch.run_outer(
            n=1,
            inner_fn=inner,
            board_fn=lambda: ({"P": 100}, 100),
            reeval_fn=reeval,
            rounds=1,
            generate_fn=generate,
            llm=True,
        )
        self.assertTrue(result["improve"]["ok"])
        self.assertEqual(result["improve"]["history"][0]["action"]["action"], "skip_stem")
        self.assertIn("P::port_comma", watch.memory.get("blacklist", []))
        self.assertFalse(result["jev_writes_lean"])

    def test_py_harness_edit_kept_only_when_lake_is_shorter(self) -> None:
        from jevops.improve_watch import EvalWatch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "jevops" / "note.py"
            target.parent.mkdir(parents=True)
            target.write_text("LIMIT = 10\n")
            watch = EvalWatch(memory={}, root=root)
            watch.observe(
                {"name": "P", "ok": True, "tokens": 100, "heartbeats": 40, "tactics": "simp [h]"},
                source="lake",
            )

            def generate(_prompt: str) -> str:
                self.assertIn("simp [h]", _prompt)
                return json.dumps(
                    {
                        "action": "update_code",
                        "path": "jevops/note.py",
                        "old": "LIMIT = 10\n",
                        "new": "LIMIT = 8\n",
                        "name": "P",
                        "reason": "lower the cap",
                    }
                )

            def longer(_action, _memory):
                return {"name": "P", "ok": True, "tokens": 100, "heartbeats": 50, "tactics": "simp [h]"}

            rejected = watch.improve_round(longer, generate_fn=generate, llm=True)
            self.assertFalse(rejected["accepted"])
            self.assertEqual(target.read_text(encoding="utf-8"), "LIMIT = 10\n")

            def shorter(_action, _memory):
                return {"name": "P", "ok": True, "tokens": 80, "heartbeats": 40, "tactics": "simp"}

            kept = watch.improve_round(shorter, generate_fn=generate, llm=True)
            self.assertTrue(kept["accepted"])
            self.assertEqual(target.read_text(encoding="utf-8"), "LIMIT = 8\n")
            self.assertFalse(kept["jev_writes_lean"])

    def test_candidate_does_not_lower_the_harness_baseline(self) -> None:
        from jevops.improve_watch import EvalWatch

        watch = EvalWatch(memory={})
        watch.observe(
            {"name": "P", "ok": True, "tokens": 100, "heartbeats": 40, "role": "incumbent"},
            source="lake",
        )
        watch.observe(
            {"name": "P", "ok": True, "tokens": 10, "heartbeats": 40, "role": "candidate", "tactics": "exact h"},
            source="lake",
        )

        def generate(_prompt: str) -> str:
            return json.dumps({"action": "skip_stem", "stem": "comma", "name": "P"})

        def reeval(_action, _memory):
            return {"name": "P", "ok": True, "tokens": 90, "heartbeats": 40}

        kept = watch.improve_round(reeval, generate_fn=generate, llm=True)
        self.assertTrue(kept["accepted"])
        self.assertEqual(kept["before"]["tokens"], 100)

    def test_router_run_keeps_a_shorter_proof_already_in_the_log(self) -> None:
        from jevops.improve_watch import EvalWatch

        long_proof = "have h2 := h\n  exact h2"
        short_proof = "exact h"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "pick.py"
            target.write_text('def tactic() -> str:\n    return """%s"""\n' % long_proof, encoding="utf-8")
            watch = EvalWatch(memory={}, root=root)
            watch.observe(
                {"name": "watchProbe", "ok": True, "tokens": 7, "heartbeats": 40, "tactics": long_proof, "stem": "long_have"},
                source="lake",
            )
            watch.observe(
                {
                    "name": "watchProbe",
                    "ok": True,
                    "tokens": 2,
                    "heartbeats": 40,
                    "tactics": short_proof,
                    "stem": "short_exact",
                    "role": "candidate",
                },
                source="lake",
            )
            asked: list[str] = []

            def generate(prompt: str) -> str:
                asked.append(prompt)
                return json.dumps({"action": "run", "reason": "no external model selected"})

            def reeval(_action, _memory):
                text = target.read_text(encoding="utf-8")
                self.assertIn(short_proof, text)
                self.assertNotIn(long_proof, text)
                return {"name": "watchProbe", "ok": True, "tokens": 2, "heartbeats": 40, "tactics": short_proof}

            kept = watch.improve_round(reeval, generate_fn=generate, llm=True)
            self.assertTrue(asked)
            self.assertIn("have h2 := h", asked[0])
            self.assertIn("exact h", asked[0])
            self.assertEqual(kept["action"]["action"], "update_code")
            self.assertEqual(kept["action"]["reason"], "recorded_lake_ok_proof_is_shorter")
            self.assertEqual(kept["action"]["source_action"], "run")
            self.assertTrue(kept["accepted"])
            self.assertEqual(kept["before"]["tokens"], 7)
            self.assertIn(short_proof, target.read_text(encoding="utf-8"))
            self.assertNotIn("have h2", target.read_text(encoding="utf-8"))
            self.assertFalse(kept["jev_writes_lean"])

            def same(_action, _memory):
                return {"name": "watchProbe", "ok": True, "tokens": 2, "heartbeats": 40, "tactics": short_proof}

            again = watch.improve_round(same, generate_fn=generate, llm=True)
            self.assertFalse(again["accepted"])
            self.assertEqual(again["reason"], "no_harness_change")

    def test_router_run_rolls_back_when_the_reeval_is_not_shorter(self) -> None:
        from jevops.improve_watch import EvalWatch

        long_proof = "have h2 := h\n  exact h2"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "pick.py"
            original = 'def tactic() -> str:\n    return """%s"""\n' % long_proof
            target.write_text(original, encoding="utf-8")
            watch = EvalWatch(memory={}, root=root)
            watch.observe(
                {"name": "watchProbe", "ok": True, "tokens": 7, "tactics": long_proof},
                source="lake",
            )
            watch.observe(
                {"name": "watchProbe", "ok": True, "tokens": 2, "tactics": "exact h", "role": "candidate"},
                source="lake",
            )

            def generate(_prompt: str) -> str:
                return json.dumps({"action": "run"})

            def not_shorter(_action, _memory):
                return {"name": "watchProbe", "ok": True, "tokens": 7, "tactics": long_proof}

            rejected = watch.improve_round(not_shorter, generate_fn=generate, llm=True)
            self.assertFalse(rejected["accepted"])
            self.assertEqual(rejected["reason"], "not_shorter")
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_loss_quarantine_beats_a_recorded_shorter_proof(self) -> None:
        from jevops.improve_watch import EvalWatch

        long_proof = "have h2 := h\n  exact h2"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "pick.py"
            original = 'def tactic() -> str:\n    return """%s"""\n' % long_proof
            target.write_text(original, encoding="utf-8")
            watch = EvalWatch(memory={}, root=root)
            watch.observe(
                {"name": "watchProbe", "ok": True, "tokens": 7, "tactics": long_proof},
                source="lake",
            )
            watch.observe(
                {"name": "watchProbe", "ok": True, "tokens": 2, "tactics": "exact h", "role": "candidate"},
                source="lake",
            )
            watch.observe(
                {"name": "watchProbe", "ok": False, "tokens": 7, "stem": "comma"},
                source="lake",
            )

            def generate(_prompt: str) -> str:
                return json.dumps({"action": "run", "reason": "no_opinion"})

            proposal = watch.propose(generate_fn=generate, llm=True)
            self.assertEqual(proposal["action"], "skip_stem")
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_allow_paths_refuses_every_other_file(self) -> None:
        from jevops.improve_watch import EvalWatch

        long_proof = "have h2 := h\n  exact h2"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kept = root / "keep.py"
            other = root / "other.py"
            original = 'def tactic() -> str:\n    return """%s"""\n' % long_proof
            kept.write_text("LIMIT = 1\n", encoding="utf-8")
            other.write_text(original, encoding="utf-8")
            watch = EvalWatch(memory={}, root=root, allow_paths=("keep.py",))
            watch.observe(
                {"name": "P", "ok": True, "tokens": 7, "tactics": long_proof, "role": "incumbent"},
                source="lake",
            )
            watch.observe(
                {"name": "P", "ok": True, "tokens": 2, "tactics": "exact h", "role": "candidate"},
                source="lake",
            )

            def update_other(_prompt: str) -> str:
                return json.dumps(
                    {"action": "update_code", "path": "other.py", "old": long_proof, "new": "exact h", "name": "P"}
                )

            refused = watch.propose(generate_fn=update_other, llm=True)
            self.assertEqual(refused["action"], "run")
            self.assertEqual(refused["reason"], "path_not_allowed")
            self.assertEqual(other.read_text(encoding="utf-8"), original)

            def run(_prompt: str) -> str:
                self.assertIn("harness_file keep.py", _prompt)
                return json.dumps({"action": "run"})

            stayed = watch.propose(generate_fn=run, llm=True)
            self.assertEqual(stayed["action"], "run")
            self.assertEqual(other.read_text(encoding="utf-8"), original)

            calls = {"n": 0}

            def mint_then_edit(prompt: str) -> str:
                calls["n"] += 1
                if calls["n"] == 1:
                    return json.dumps({"action": "mint", "name": "P", "reason": "shorter proof exists"})
                self.assertIn("update_code", prompt)
                return json.dumps(
                    {
                        "action": "update_code",
                        "path": "keep.py",
                        "old": "LIMIT = 1\n",
                        "new": "LIMIT = 2\n",
                        "name": "P",
                    }
                )

            edited = watch.propose(generate_fn=mint_then_edit, llm=True)
            self.assertEqual(edited["action"], "update_code")
            self.assertEqual(edited["path"], "keep.py")
            self.assertEqual(edited["source_action"], "mint")
            self.assertEqual(kept.read_text(encoding="utf-8"), "LIMIT = 1\n")

    def test_codex_router_can_request_a_read_only_sandbox(self) -> None:
        import jevops.llm_router as router

        seen: dict[str, list[str]] = {}

        def fake_which(_name: str) -> str:
            return "/usr/bin/codex"

        def fake_run(command, **_kwargs):
            seen["command"] = list(command)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        original_which = router.shutil.which
        original_run = router.subprocess.run
        router.shutil.which = fake_which
        router.subprocess.run = fake_run
        try:
            text = router.generate_text("return json", provider="codex_cli", model_name="gpt-6-astra", sandbox="read-only", timeout=5)
        finally:
            router.shutil.which = original_which
            router.subprocess.run = original_run
        self.assertEqual(text, "")
        self.assertIn("--sandbox", seen["command"])
        self.assertIn("read-only", seen["command"])


if __name__ == "__main__":
    unittest.main()
