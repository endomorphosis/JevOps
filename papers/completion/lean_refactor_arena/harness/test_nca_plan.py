#!/usr/bin/env python3
"""Goal/subgoal/task plan and graph-of-thoughts in NCA memory."""

from __future__ import annotations

import unittest

import board_graph as lra_board
import nca_plan as lra_plan
import nca_program as lra_prog
import nca_rankers as lra_rank
import skill_improve_loop as lra_loop


class NcaPlanTests(unittest.TestCase):
    def test_seed_plan_from_board(self) -> None:
        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        plan = mem["nca"]["plan"]
        self.assertTrue(plan["goals"])
        self.assertGreaterEqual(len(plan["subgoals"]), 1)
        self.assertGreaterEqual(len(plan["tasks"]), 1)
        self.assertEqual(plan["goals"][0]["id"], "LRA-G000")

    def test_thoughts_and_jev(self) -> None:
        mem: dict = {"nca": {}}
        lra_plan.seed_plan(mem)
        t0 = lra_plan.add_thought(mem, kind="generate", text="try trailing comma", task_id="LRA-017", skill="trailing_tuple_comma")
        t1 = lra_plan.record_jev(mem, choice="v0", score_m=800, noul_m=100, task_id="LRA-017", skill="autoencoder")
        self.assertTrue(t0["id"])
        self.assertEqual(t1["kind"], "score")
        best = lra_plan.keep_best_thoughts(mem)
        self.assertEqual(best[0]["id"], t1["id"])
        window = lra_plan.plan_window(mem)
        self.assertEqual(window["goal"], "LRA-G000")
        self.assertTrue(window["thoughts"])

    def test_router_sees_plan(self) -> None:
        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        snap = lra_loop.nca_status_for_router(mem)
        self.assertIn("plan", snap)
        self.assertEqual((snap.get("plan") or {}).get("goal"), "LRA-G000")

    def test_skill_calls(self) -> None:
        mem = {
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_nca_plan"},
                        {"op": "CALL", "ptr": "ptr://skill/port_got"},
                        {"op": "KEEP"},
                    ]
                },
            }
        }
        executed = lra_prog.execute_program_ops(mem, tactics="  exact Hin\n", problem="P")
        self.assertEqual(executed.get("tactics"), "  exact Hin\n")
        ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        self.assertTrue(any("nca_plan" in p for p in ptrs), executed["ran"])
        self.assertTrue(any("got" in p for p in ptrs))
        out = lra_rank.call_ranker("port_got", memory=mem, problem="P")
        self.assertEqual(out.get("kind"), "port_got")
        self.assertFalse(out.get("campaign_write"))


if __name__ == "__main__":
    unittest.main()
