#!/usr/bin/env python3
"""Turing tape/stack tools and decision-transformer context."""

from __future__ import annotations

import unittest

import nca_program as lra_prog
import nca_rankers as lra_rank
import nca_turing as lra_tm
import neural_tape as lra_tape


class NcaTuringTests(unittest.TestCase):
    def test_tape_left_right_poke(self) -> None:
        tape = lra_tape.Tape()
        tape.write("simp", extra={"symbol": "simp"})
        tape.write("exact", extra={"symbol": "exact"})
        self.assertEqual(tape.read_symbol(), "exact")
        tape.left()
        self.assertEqual(tape.read_symbol(), "simp")
        tape.poke("intro")
        self.assertEqual(tape.read_symbol(), "intro")
        tape.right()
        self.assertEqual(tape.read_symbol(), "exact")

    def test_step_and_halt_on_blank(self) -> None:
        mem: dict = {"nca": {}, "tape": {"cells": [], "head": 0}}
        lra_tm.tm_write(mem, symbol="simp")
        stepped = lra_tm.tm_step(mem)
        self.assertTrue(stepped["ok"])
        self.assertIn(stepped.get("action"), {"RIGHT", "STAY", "LEFT", "HALT"})
        blank = {"nca": {}, "tape": {"cells": [{"kind": "blank", "symbol": "_", "energy": 0.0}], "head": 0}}
        halt = lra_tm.tm_step(blank)
        self.assertTrue(halt.get("halted"))

    def test_stack_push_pop(self) -> None:
        mem: dict = {"nca": {}, "tape": {"cells": [{"kind": "simp", "symbol": "simp", "energy": 0.5}], "head": 0}}
        pushed = lra_tm.tm_push(mem)
        self.assertEqual(pushed["depth"], 1)
        popped = lra_tm.tm_pop(mem)
        self.assertEqual(popped["symbol"], "simp")
        self.assertEqual(popped["depth"], 0)

    def test_dt_window_from_history(self) -> None:
        mem: dict = {"nca": {}, "tape": {"cells": [{"kind": "simp", "symbol": "simp", "energy": 0.6}], "head": 0}}
        lra_tm.tm_step(mem)
        lra_tm.tm_step(mem)
        dt = lra_tm.dt_context(mem)
        self.assertTrue(dt["window"])
        self.assertIn("rtg_m", dt["window"][0])
        self.assertTrue(all(isinstance(row["rtg_m"], int) for row in dt["window"]))
        self.assertIn("dt", mem["nca"])

    def test_skill_calls(self) -> None:
        mem = {
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_tm_write"},
                        {"op": "CALL", "ptr": "ptr://skill/port_tm_step"},
                        {"op": "CALL", "ptr": "ptr://skill/port_decision_transformer"},
                        {"op": "KEEP"},
                    ]
                },
            },
            "tape": {"cells": [{"kind": "simp", "symbol": "simp", "energy": 0.5}], "head": 0},
        }
        executed = lra_prog.execute_program_ops(mem, tactics="  simp\n", problem="P")
        self.assertEqual(executed.get("tactics"), "  simp\n")
        ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        self.assertTrue(any("tm_write" in p or "tm_step" in p for p in ptrs), executed["ran"])
        self.assertTrue(any("decision_transformer" in p for p in ptrs))
        out = lra_rank.call_ranker("port_tm_step", memory=mem)
        self.assertTrue(out.get("ok"))
        self.assertFalse(lra_tm.is_tm_stem("port_thompson"))


if __name__ == "__main__":
    unittest.main()
