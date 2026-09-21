#!/usr/bin/env python3
"""SGD/mask/diffuse wraps + milles Markov, isotonic, AdaBoost, quantile, PageRank, contrastive."""

from __future__ import annotations

import unittest

import nca_more_rankers as lra_more
import nca_program as lra_prog
import nca_rankers as lra_rank


SIMP = "  simp at h\n  simp at h\n"


class NcaMoreRankerTests(unittest.TestCase):
    def test_mask_and_sgd_find_mca_holes(self) -> None:
        mem: dict = {"nca": {}}
        masked = lra_more.call_mask(mem, tactics=SIMP)
        self.assertTrue(masked["ok"])
        self.assertGreaterEqual(masked["n_holes"], 1)
        sgd = lra_more.call_sgd(mem, tactics=SIMP)
        self.assertEqual(sgd["kind"], "port_sgd")
        self.assertFalse(sgd["called_docker0"])
        self.assertGreaterEqual(sgd["n_holes"], 1)

    def test_markov_next_head(self) -> None:
        mem: dict = {"nca": {}}
        tactics = "  intro\n  simp\n  exact Hin\n"
        out = lra_more.call_markov(mem, tactics=tactics)
        self.assertTrue(out["ok"])
        self.assertTrue(out["integer"])
        self.assertIn("trans_m", mem["nca"]["markov"])

    def test_isotonic_monotone(self) -> None:
        mem = {
            "successes": [{"kind": "port_a", "noul": 0.1}, {"kind": "port_b", "noul": 0.2}],
            "failures": [{"kind": "port_c", "noul": 0.8}, {"kind": "port_d", "noul": 0.9}],
            "nca": {},
        }
        out = lra_more.call_isotonic(mem)
        self.assertTrue(out["ok"])
        table = mem["nca"]["isotonic"]["table"]
        ps = [row["p_m"] for row in table]
        self.assertEqual(ps, sorted(ps))

    def test_adaboost_and_quantile(self) -> None:
        mem = {
            "successes": [{"kind": "port_trailing_tuple_comma", "tokens": 8, "remaining_cut": 40}] * 3,
            "failures": [{"kind": "port_hoist_repeated_simp", "tokens": 40, "remaining_cut": 1}] * 3,
            "nca": {},
        }
        boost = lra_more.call_adaboost(mem, tactics="  exact ⟨a, b,⟩\n", problem="P")
        self.assertTrue(boost["ok"], boost)
        q = lra_more.call_quantile(mem)
        self.assertGreaterEqual(q.get("n_stems") or 0, 1)
        self.assertIn("trailing_tuple_comma", q["ranked"] + list((mem["nca"]["quantile"]["table"] or {})))

    def test_pagerank_from_board(self) -> None:
        import board_graph as lra_board

        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        out = lra_more.call_pagerank(mem)
        self.assertTrue(out["ok"], out)
        self.assertGreaterEqual(out.get("n_nodes") or 0, 2)

    def test_contrastive_is_not_gold(self) -> None:
        mem = {
            "nca": {
                "autoencoder": {
                    "batch": [
                        {"problem": "P", "mu": [1000] + [0] * 15},
                        {"problem": "Q", "mu": [0, 1000] + [0] * 14},
                    ]
                }
            }
        }
        out = lra_more.call_contrastive(mem, tactics="hello", problem="P")
        self.assertTrue(out["ok"])
        self.assertFalse(out["gold"])
        self.assertEqual(out["loss_m"], int(out["loss_m"]))

    def test_skill_calls_more_do_not_write_lean(self) -> None:
        body = SIMP
        mem = {
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_mask"},
                        {"op": "CALL", "ptr": "ptr://skill/port_sgd"},
                        {"op": "CALL", "ptr": "ptr://skill/port_markov"},
                        {"op": "CALL", "ptr": "ptr://skill/port_isotonic"},
                        {"op": "CALL", "ptr": "ptr://skill/port_pagerank"},
                        {"op": "KEEP"},
                    ]
                },
            },
            "successes": [{"kind": "port_a", "noul": 0.1, "tokens": 8}] * 2,
            "failures": [{"kind": "port_b", "noul": 0.9, "tokens": 40}] * 2,
        }
        executed = lra_prog.execute_program_ops(mem, tactics=body, problem="P")
        self.assertEqual(executed.get("tactics"), body)
        ok_ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        for tag in ("mask", "sgd", "markov", "isotonic", "pagerank"):
            self.assertTrue(any(tag in p for p in ok_ptrs), (tag, executed["ran"]))

    def test_isotonic_not_swallowed_by_ica(self) -> None:
        self.assertTrue(lra_more.is_more_stem("port_isotonic"))
        out = lra_rank.call_ranker("port_isotonic", memory={"successes": [{"noul": 0.2}, {"noul": 0.3}], "failures": [{"noul": 0.8}, {"noul": 0.9}], "nca": {}})
        self.assertEqual(out.get("kind"), "port_isotonic")

    def test_gan_discriminator_is_jev_not_gold_ce(self) -> None:
        def jev_fn(payload):
            rows = list(payload.get("variations") or [])
            self.assertTrue(any(row.get("role") == "real" for row in rows))
            self.assertTrue(any(row.get("role") == "fake" for row in rows))
            real = next(row for row in rows if row.get("role") == "real")
            return {
                "choice": real["id"],
                "scores": {row["id"]: 800 if row.get("role") == "real" else 200 for row in rows},
                "noul": 0.15,
            }

        mem: dict = {"nca": {}}
        out = lra_more.call_gan(mem, tactics="  intro\n  simp\n  trivial\n", problem="P", jev_fn=jev_fn)
        self.assertTrue(out["ok"])
        self.assertEqual(out["kind"], "port_gan")
        self.assertTrue(out["used_jev"])
        self.assertFalse(out["gold"])
        self.assertEqual(out["loss_gold"], "jev")
        self.assertFalse(out["writes_lean"])
        self.assertFalse(out["legal_ir"])
        self.assertTrue(out["functional_lean"])
        self.assertGreaterEqual(out["n_fake"], 1)
        self.assertIn("True := by", str(out.get("lean") or ""))
        dispatched = lra_rank.call_ranker("port_gan", memory={"nca": {}}, tactics="  trivial\n", problem="P")
        self.assertEqual(dispatched.get("kind"), "port_gan")
        self.assertFalse(dispatched["writes_lean"])
        body = "  intro\n  trivial\n"
        executed = lra_prog.execute_program_ops(
            {
                "nca": {
                    "grid": {},
                    "program_state": {"ops": [{"op": "CALL", "ptr": "ptr://skill/port_gan"}, {"op": "KEEP"}]},
                }
            },
            tactics=body,
            problem="P",
        )
        self.assertEqual(executed.get("tactics"), body)
        self.assertTrue(any("gan" in str(op.get("ptr") or "") and op.get("ok") for op in executed["ran"]))


if __name__ == "__main__":
    unittest.main()
