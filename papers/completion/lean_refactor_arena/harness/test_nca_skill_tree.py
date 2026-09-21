#!/usr/bin/env python3
"""Hierarchical skill tree + random forest search."""

from __future__ import annotations

import unittest

import nca_program as lra_prog
import nca_rankers as lra_rank
import nca_skill_tree as lra_tree


class NcaSkillTreeTests(unittest.TestCase):
    def test_flatten_has_forest_and_graph_leaves(self) -> None:
        leaves = lra_tree.flatten_tree()
        stems = {row["stem"] for row in leaves}
        self.assertIn("random_forest", stems)
        self.assertIn("graphrag", stems)
        self.assertIn("trailing_tuple_comma", stems)
        paths = {row["path"] for row in leaves}
        self.assertTrue(any(p.startswith("rankers/forest/") for p in paths))
        self.assertTrue(any(p.startswith("graph/") for p in paths))

    def test_forest_search_ranks_paths(self) -> None:
        mem = {
            "successes": [{"kind": "port_trailing_tuple_comma", "tokens": 8, "name": "A"}] * 3,
            "failures": [{"kind": "port_hoist_repeated_simp", "tokens": 40, "name": "A"}] * 3,
            "nca": {},
        }
        out = lra_tree.search_with_forest(mem, problem="A")
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["n_leaves"], 10)
        self.assertTrue(out["ranked_paths"])
        self.assertIn("keep_structure", out["families"])
        self.assertTrue((mem.get("nca") or {}).get("jsonld"))

    def test_random_forest_call_includes_tree(self) -> None:
        mem = {
            "successes": [{"kind": "port_trailing_tuple_comma", "tokens": 8}] * 3,
            "failures": [{"kind": "port_hoist_repeated_simp", "tokens": 40}] * 3,
            "nca": {},
        }
        out = lra_rank.call_ranker("port_random_forest", memory=mem, tactics="  exact ⟨a, b,⟩\n")
        self.assertEqual(out.get("kind"), "port_random_forest")
        self.assertGreaterEqual(int(out.get("n_leaves") or 0), 10)

    def test_skill_tree_call_no_lean(self) -> None:
        body = "  exact Hin\n"
        mem = {
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_skill_tree"},
                        {"op": "KEEP"},
                    ]
                },
            },
            "successes": [{"kind": "port_trailing_tuple_comma", "tokens": 8}] * 3,
            "failures": [{"kind": "port_kmeans", "tokens": 20}] * 3,
        }
        executed = lra_prog.execute_program_ops(mem, tactics=body, problem="P")
        self.assertEqual(executed.get("tactics"), body)
        self.assertTrue(any("skill_tree" in str(op.get("ptr") or "") and op.get("ok") for op in executed["ran"]))


if __name__ == "__main__":
    unittest.main()
