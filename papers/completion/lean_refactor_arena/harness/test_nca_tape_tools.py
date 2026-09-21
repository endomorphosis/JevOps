#!/usr/bin/env python3
"""Tape context editor: splice, mask, pop, crop, keep, checkpoint."""

from __future__ import annotations

import unittest

import nca_program as lra_prog
import nca_rankers as lra_rank
import nca_tape_tools as lra_tt
import neural_tape as lra_tape


def _filled() -> lra_tape.Tape:
    tape = lra_tape.Tape()
    for name, e in (("a", 0.1), ("b", 0.9), ("c", 0.2), ("d", 0.8), ("e", 0.05)):
        tape.write(name, extra={"symbol": name}, energy=e)
    return tape


class NcaTapeToolsTests(unittest.TestCase):
    def test_pop_splice_mask(self) -> None:
        tape = _filled()
        n0 = len(tape.cells)
        popped = tape.pop()
        self.assertEqual((popped or {}).get("symbol"), "e")
        self.assertEqual(len(tape.cells), n0 - 1)
        tape.splice(kind="splice", payload={"x": 1})
        self.assertEqual(tape.read().get("kind"), "splice")
        n_mask = tape.mask_window(width=1)
        self.assertGreaterEqual(n_mask, 1)
        vis = tape.window_visible(width=1)
        self.assertTrue(all(not c.get("masked") or c is tape.read() for c in vis))

    def test_crop_keep_drop_compress(self) -> None:
        tape = _filled()
        tape.crop(width=1)
        self.assertLessEqual(len(tape.cells), 3)
        tape2 = _filled()
        tape2.keep_k(2)
        self.assertEqual(len(tape2.cells), 2)
        tape3 = _filled()
        dropped = tape3.drop_below(0.15)
        self.assertGreaterEqual(dropped, 1)
        tape4 = lra_tape.Tape()
        tape4.write("blank", extra={"symbol": "_"})
        tape4.write("blank", extra={"symbol": "_"})
        tape4.write("simp", extra={"symbol": "simp"})
        self.assertEqual(tape4.compress_blanks(), 1)

    def test_mark_restore_attn(self) -> None:
        tape = _filled()
        snap = tape.checkpoint()
        tape.pop()
        tape.restore(snap)
        self.assertEqual(len(tape.cells), len(snap["cells"]))
        w = tape.attn_m()
        self.assertTrue(w)
        self.assertTrue(all(isinstance(x, int) for x in w))

    def test_dispatch_not_mca_mask(self) -> None:
        self.assertTrue(lra_tt.is_tape_editor_stem("port_tape_mask"))
        self.assertFalse(lra_tt.is_tape_editor_stem("port_mask"))
        self.assertFalse(lra_tt.is_tape_editor_stem("port_tape_fft"))
        mem = {
            "tape": {
                "cells": [
                    {"kind": "a", "symbol": "a", "energy": 0.4},
                    {"kind": "b", "symbol": "b", "energy": 0.7},
                ],
                "head": 1,
            },
            "nca": {},
        }
        out = lra_rank.call_ranker("port_tape_mask", memory=mem)
        self.assertEqual(out.get("kind"), "port_tape_mask")
        splice = lra_rank.call_ranker("port_tape_splice", memory=mem)
        self.assertEqual(splice.get("kind"), "port_tape_splice")
        pop = lra_rank.call_ranker("port_tape_pop", memory=mem)
        self.assertEqual(pop.get("kind"), "port_tape_pop")

    def test_skill_calls(self) -> None:
        mem = {
            "tape": {
                "cells": [{"kind": "a", "symbol": "a", "energy": 0.5}] * 5,
                "head": 4,
            },
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_tape_splice"},
                        {"op": "CALL", "ptr": "ptr://skill/port_tape_mask"},
                        {"op": "CALL", "ptr": "ptr://skill/port_tape_pop"},
                        {"op": "CALL", "ptr": "ptr://skill/port_tape_crop"},
                        {"op": "KEEP"},
                    ]
                },
            },
        }
        body = "  simp\n"
        executed = lra_prog.execute_program_ops(mem, tactics=body, problem="P")
        self.assertEqual(executed.get("tactics"), body)
        ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        for tag in ("tape_splice", "tape_mask", "tape_pop", "tape_crop"):
            self.assertTrue(any(tag in p for p in ptrs), (tag, executed["ran"]))


if __name__ == "__main__":
    unittest.main()
