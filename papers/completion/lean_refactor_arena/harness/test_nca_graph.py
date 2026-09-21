#!/usr/bin/env python3
"""Board traversal, GraphRAG search, milles neural graph."""

from __future__ import annotations

import unittest

import board_graph as lra_board
import nca_graph as lra_graph
import nca_program as lra_prog
import nca_rankers as lra_rank


class NcaGraphTests(unittest.TestCase):
    def _mem(self) -> dict:
        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        return mem

    def test_bfs_traverse(self) -> None:
        mem = self._mem()
        out = lra_graph.traverse(mem, mode="bfs")
        self.assertTrue(out["ok"], out)
        self.assertGreaterEqual(out.get("n") or 0, 2)
        self.assertFalse(out["writes_lean"])

    def test_message_pass_ranks_nodes(self) -> None:
        mem = self._mem()
        out = lra_graph.message_pass(mem)
        self.assertTrue(out["ok"], out)
        self.assertGreaterEqual(out.get("n_nodes") or 0, 2)
        self.assertTrue(out["integer"])

    def test_graphrag_uses_symbol_search(self) -> None:
        mem = self._mem()
        out = lra_graph.graphrag_search(mem, query="simp", tactics="  simp_all\n")
        self.assertTrue(out["ok"])
        self.assertIn("symbol_search", out.get("sources") or {})
        self.assertFalse(out["called_docker0"])

    def test_skill_calls_do_not_write_lean(self) -> None:
        body = "  exact Hin\n"
        mem = self._mem()
        mem["nca"]["program_state"] = {
            "ops": [
                {"op": "CALL", "ptr": "ptr://skill/port_graph_traverse"},
                {"op": "CALL", "ptr": "ptr://skill/port_neural_graph"},
                {"op": "CALL", "ptr": "ptr://skill/port_graphrag"},
                {"op": "KEEP"},
            ]
        }
        executed = lra_prog.execute_program_ops(mem, tactics=body, problem="P")
        self.assertEqual(executed.get("tactics"), body)
        ok_ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        self.assertTrue(any("traverse" in p or "graph_traverse" in p for p in ok_ptrs), executed["ran"])
        self.assertTrue(any("neural_graph" in p for p in ok_ptrs))
        self.assertTrue(any("graphrag" in p for p in ok_ptrs))

    def test_dispatch(self) -> None:
        mem = self._mem()
        out = lra_rank.call_ranker("port_neural_graph", memory=mem, problem="P")
        self.assertEqual(out.get("kind"), "port_neural_graph")

    def test_jsonld_graph_without_duckdb(self) -> None:
        import nca_jsonld as lra_ld

        doc = lra_ld.document_from_edges(
            [["ptr://goal/LRA-G000", "ptr://task/LRA-017"], ["ptr://task/LRA-017", "ptr://theorem/P"]]
        )
        mem = {"nca": {"jsonld": doc, "grid": {}}}
        out = lra_graph.traverse(mem, start="ptr://goal/LRA-G000", mode="bfs")
        self.assertGreaterEqual(out.get("n") or 0, 2)
        hits = lra_graph.graphrag_search(mem, query="LRA-017")
        self.assertEqual(hits.get("interface"), "json-ld")
        self.assertEqual((hits.get("sources") or {}).get("duckdb"), "skipped_optional")
        self.assertTrue(any("LRA-017" in str(s) for s in hits.get("ranked") or []))

    def test_optional_duckdb_jsonld_adapter(self) -> None:
        import tempfile
        from pathlib import Path

        import nca_jsonld as lra_ld

        doc = lra_ld.document_from_edges([["ptr://goal/LRA-G000", "ptr://subgoal/LRA-S04"]])
        try:
            import duckdb  # noqa: F401
        except Exception:
            self.skipTest("duckdb not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jsonld.duckdb"
            ingested = lra_ld.ingest_duckdb(doc, db_path=path)
            self.assertTrue(ingested.get("ok"), ingested)
            q = lra_ld.query_duckdb("LRA-S04", db_path=path)
            self.assertTrue(q.get("ok"), q)
            self.assertTrue(any("LRA-S04" in str(h.get("symbol")) for h in q.get("hits") or []))


if __name__ == "__main__":
    unittest.main()
