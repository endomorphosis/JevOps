#!/usr/bin/env python3
"""LLM-free replay of Core.InitsUpdatesComm 268→139, wired into PCA/MCA loops."""
from __future__ import annotations

import random
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import cascade_edits as lra_cascade
import constrained_beam as lra_cb
import inits_updates_shorten as lra_ius
import mcmc_beam as lra_mcmc
import pca_mca_fanout as lra_pca
import run_warmup as lra_loop
import sgd_fanout as lra_sgd
from jevops.inits import BEST_TARGET_TOKENS
from jevops.inits import best_replay


class InitsUpdatesShortenTests(unittest.TestCase):
    def test_replay_matches_139_canary(self) -> None:
        check = lra_ius.self_check()
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["source_tokens"], 268)
        self.assertEqual(check["replay_tokens"], 139)
        self.assertTrue(check["matches_canary"])
        self.assertFalse(check["called_llm"])
        self.assertGreaterEqual(check["n_kernels"], 41)

    def test_propose_includes_replay_kinds(self) -> None:
        src = lra_ius.original_tactics()
        kinds = {item["kind"] for item in lra_ius.propose(src)}
        self.assertIn("drop_not_intro_specialize", kinds)
        self.assertIn("fold_init_exacts", kinds)
        self.assertIn("unzip_simp_all", kinds)
        self.assertEqual(lra_loop.token_count(lra_ius.replay(src)), 139)

    def test_verified_compound_candidate_beats_historical_replay(self) -> None:
        src = lra_ius.original_tactics()
        best = best_replay(src)
        self.assertEqual(lra_loop.token_count(best), BEST_TARGET_TOKENS)
        self.assertLess(lra_loop.token_count(best), lra_loop.token_count(lra_ius.replay(src)))
        self.assertNotIn("have Hlen2 := UpdateStatesLength Hup", best)
        self.assertNotIn("$ UpdateStatesLength Hups", best)
        kinds = {item["kind"] for item in lra_ius.propose(src)}
        self.assertIn("inits_best", kinds)
        mcmc_kinds = {item["kind"] for item in lra_ius.mcmc_extras(src)}
        self.assertIn("inits_best", mcmc_kinds)

    def test_replay_is_idempotent_on_139(self) -> None:
        src = lra_ius.original_tactics()
        once = lra_ius.replay(src)
        twice = lra_ius.replay(once)
        self.assertEqual(once, twice)

    def test_pca_mca_guided_drafts_include_replay(self) -> None:
        src = lra_ius.original_tactics()
        drafts = lra_pca.guided_drafts(
            src,
            [{"family": "strength_reduction"}, {"family": "loop_invariant"}, {"family": "dead_code"}],
            {"n_have": 4, "n_rw": 1, "n_simp_all": 5, "n_induction": 1},
        )
        replay_drafts = [item for item in drafts if "inits_replay" in item.ops or item.family == "inits_replay"]
        self.assertTrue(replay_drafts, [item.ops for item in drafts[:8]])
        self.assertEqual(lra_loop.token_count(replay_drafts[0].tactics), 139)
        best_drafts = [item for item in drafts if "inits_best" in item.ops or item.family == "inits_best"]
        self.assertTrue(best_drafts, [item.ops for item in drafts[:8]])
        self.assertEqual(lra_loop.token_count(best_drafts[0].tactics), BEST_TARGET_TOKENS)

    def test_hammer_and_mcmc_and_cascade_expose_replay(self) -> None:
        src = lra_ius.original_tactics()
        hammer = dict(lra_sgd.hammer_variants(src, src))
        self.assertIn("inits_replay", hammer)
        self.assertEqual(lra_loop.token_count(hammer["inits_replay"]), 139)
        kinds = {item["kind"] for item in lra_mcmc.propose_edits(src, src, random.Random(0), limit=None)}
        self.assertIn("inits_replay", kinds)
        self.assertIn("inits_replay", lra_cascade.FAMILY_TREE.get("rewrite", {}))
        self.assertIn("ih_defined_hups", lra_cascade.FAMILY_TREE.get("rewrite", {}))
        self.assertIn("drop_named_sigma", lra_cascade.FAMILY_TREE.get("drop", {}))
        beam = lra_cb.shorten_keeping_prefix_haves(src)
        self.assertTrue(any(kind == "inits_replay" for kind, _ in beam))


if __name__ == "__main__":
    unittest.main()
