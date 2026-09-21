#!/usr/bin/env python3
"""Hawkes, CRF, submodular, delayed bandit, tape conv/DFT."""

from __future__ import annotations

import unittest

import nca_program as lra_prog
import nca_rankers as lra_rank
import nca_temporal as lra_time


class NcaTemporalTests(unittest.TestCase):
    def test_hawkes_prefers_recent(self) -> None:
        mem = {
            "successes": [{"kind": "port_old", "t": 1}, {"kind": "port_new", "t": 9}],
            "failures": [],
            "nca": {},
        }
        out = lra_time.call_hawkes(mem, now=10)
        self.assertTrue(out["ok"])
        self.assertEqual(out["ranked"][0], "new")

    def test_crf_viterbi_path(self) -> None:
        mem: dict = {"nca": {}}
        out = lra_time.call_crf(mem, tactics="  intro\n  simp\n  exact Hin\n")
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(len(out.get("path") or []), 2)

    def test_submodular_budget(self) -> None:
        mem: dict = {"nca": {}}
        out = lra_time.call_submodular(mem, tactics="  exact ⟨a, b,⟩\n", budget=2)
        self.assertTrue(out["ok"])
        self.assertLessEqual(len(out.get("ranked") or []), 2)

    def test_delayed_bandit_ucb(self) -> None:
        mem = {
            "successes": [{"kind": "port_a"}] * 4,
            "failures": [{"kind": "port_b"}] * 4,
            "nca": {},
        }
        out = lra_time.call_delayed_bandit(mem)
        self.assertTrue(out["ok"])
        self.assertTrue(out["ranked"])
        self.assertGreaterEqual(int((mem["nca"]["delayed_bandit"][out["ranked"][0]].get("pending") or 0)), 1)

    def test_tape_conv_and_fft(self) -> None:
        mem = {
            "tape": {
                "cells": [{"energy": 0.1}, {"energy": 0.9}, {"energy": 0.2}] * 3,
                "head": 8,
            },
            "nca": {},
        }
        conv = lra_time.call_tape_conv(mem, fft=False)
        self.assertEqual(len(conv["conv"]), 7)
        fft = lra_time.call_tape_conv(mem, fft=True)
        self.assertEqual(len(fft["spec"]), 7)
        self.assertTrue(all(isinstance(x, int) for x in fft["spec"]))

    def test_dispatch_and_skill_call(self) -> None:
        mem = {
            "successes": [{"kind": "port_trailing_tuple_comma", "t": 3}],
            "failures": [{"kind": "port_hoist_repeated_simp", "t": 1}],
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_hawkes"},
                        {"op": "CALL", "ptr": "ptr://skill/port_submodular"},
                        {"op": "CALL", "ptr": "ptr://skill/port_tape_fft"},
                        {"op": "KEEP"},
                    ]
                },
            },
            "tape": {"cells": [{"energy": 0.4}] * 7, "head": 6},
        }
        out = lra_rank.call_ranker("port_hawkes", memory=mem)
        self.assertEqual(out.get("kind"), "port_hawkes")
        executed = lra_prog.execute_program_ops(mem, tactics="  exact ⟨a, b,⟩\n", problem="P")
        self.assertEqual(executed.get("tactics"), "  exact ⟨a, b,⟩\n")
        ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        self.assertTrue(any("hawkes" in p for p in ptrs))
        self.assertTrue(any("submodular" in p for p in ptrs))
        self.assertTrue(any("tape_fft" in p for p in ptrs))


if __name__ == "__main__":
    unittest.main()
