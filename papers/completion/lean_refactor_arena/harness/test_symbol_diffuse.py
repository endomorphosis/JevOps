#!/usr/bin/env python3
"""Closed-vocab symbol/operator mask fills (llm=off)."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import inits_updates_shorten as lra_ius
import pca_mca_fanout as lra_pca
import run_warmup as lra_loop
import symbol_diffuse as lra_sym


class SymbolDiffuseTests(unittest.TestCase):
    def test_self_check(self) -> None:
        check = lra_sym.self_check()
        self.assertTrue(check["ok"], check)
        self.assertGreaterEqual(check["n_holes"], 3)
        self.assertEqual(check["llm"], "off")
        self.assertFalse(check["called_docker0"])

    def test_closed_candidates_are_shorter(self) -> None:
        src = lra_ius.original_tactics()
        base = lra_loop.token_count(src)
        cands = lra_sym.closed_candidates(src)
        self.assertGreaterEqual(len(cands), 3)
        for item in cands:
            self.assertLess(item["token_count"], base)
            self.assertEqual(item["llm"], "off")
        self.assertEqual(cands[0]["kind"], "inits_replay")
        self.assertEqual(cands[0]["token_count"], 139)

    def test_139_masks_dollar_and_guillemet(self) -> None:
        src = Path(
            HERE.parent / "evidence" / "canaries" / "cascade-best-139.lean"
        ).read_text(encoding="utf-8").strip("\n")
        holes = lra_sym.find_symbol_holes(src)
        originals = {hole.original for hole in holes}
        self.assertIn("$", originals)
        self.assertIn("‹_›", originals)
        self.assertNotIn(":=", originals)

    def test_cfg_score_maps_schedules(self) -> None:
        self.assertEqual(lra_sym.cfg_schedule_for_score(0)["n_masks"], 2)
        self.assertEqual(lra_sym.cfg_schedule_for_score(0)["n_shots"], 0)
        self.assertEqual(lra_sym.cfg_schedule_for_score(4)["span"], 6)
        self.assertEqual(lra_sym.cfg_schedule_for_score(1.6)["id"], "cfg2")

    def test_schedule_holes_skip_pca_and_honor_span(self) -> None:
        src = lra_ius.original_tactics()
        holes = lra_sym.schedule_holes(src, n_masks=4, span=3)
        self.assertGreaterEqual(len(holes), 1)
        self.assertLessEqual(len(holes), 4)
        for hole in holes:
            self.assertEqual(hole.kind, "span")
            self.assertEqual(hole.n_tokens, 3)
            self.assertFalse(hole.original.lstrip().startswith("induction "))

    def test_few_shot_prompt_has_multihole_catalog(self) -> None:
        src = lra_ius.original_tactics()
        shots = lra_sym.catalog_shots(src, n_shots=4)
        self.assertGreaterEqual(len(shots), 1)
        self.assertTrue(any(int(shot.get("n_holes") or 0) >= 2 for shot in shots), shots)
        holes = lra_sym.schedule_holes(src, n_masks=3, span=2)
        prompt = lra_sym.few_shot_prompt(
            {"name": "Core.InitsUpdatesComm"},
            lra_sym.mask_skeleton(src, holes),
            holes,
            shots,
        )
        self.assertIn("EXAMPLE", prompt)
        self.assertIn("constructor", prompt)
        self.assertIn("<<<SYM_0", prompt)

    def test_closed_multihole_is_shorter(self) -> None:
        src = lra_ius.original_tactics()
        holes = lra_sym.schedule_holes(src, n_masks=4, span=2)
        row = lra_sym.closed_multihole(src, holes, schedule_id="cfg1")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertLess(row["token_count"], lra_loop.token_count(src))
        self.assertEqual(row["llm"], "off")
        self.assertTrue(str(row["kind"]).startswith("sweep_"))

    def test_one_hole_shots_are_single_hole(self) -> None:
        shots = lra_sym.one_hole_shots(span=3, n_shots=6)
        self.assertGreaterEqual(len(shots), 3)
        for shot in shots:
            self.assertEqual(int(shot["n_holes"]), 1)
            self.assertIn("SYM_0", shot["fills"])

    def test_prefer_one_holes_hits_catalog_phrase(self) -> None:
        src = lra_ius.original_tactics()
        windows = []
        for span in (2, 3, 4):
            windows.extend(lra_sym.prefer_one_holes(src, span, max_pos=3))
        originals = [hole.original for hole in windows]
        self.assertTrue(
            any("And.intro" in text or "intros Hin" in text or "update_some" in text for text in originals),
            originals[:8],
        )
        for hole in windows:
            self.assertEqual(hole.hole_id, "SYM_0")
            self.assertEqual(hole.kind, "span")

    def test_kernel_one_hole_rows_from_original_and_263(self) -> None:
        src = lra_ius.original_tactics()
        rows = lra_sym.kernel_one_hole_rows(src)
        kinds = {item["kind"] for item in rows}
        self.assertTrue(
            any(name in kinds for name in ("kernel_and_intro_constructor", "kernel_drop_not_intro_specialize")),
            sorted(kinds)[:12],
        )
        for item in rows:
            self.assertEqual(item["n_masks"], 1)
            self.assertLess(item["token_count"], lra_loop.token_count(src))
        cut263 = Path(
            HERE.parent / "evidence" / "canaries" / "symbol-diffuse-best-263.lean"
        ).read_text(encoding="utf-8").strip("\n")
        later = {item["kind"] for item in lra_sym.kernel_one_hole_rows(cut263)}
        self.assertIn("kernel_drop_not_intro_specialize", later)

    def test_one_hole_closed_rows_vary_span(self) -> None:
        src = lra_ius.original_tactics()
        base = lra_loop.token_count(src)
        rows = lra_sym.one_hole_closed_rows(src, max_pos=1)
        self.assertGreaterEqual(len(rows), 3)
        spans = {int(row["span"]) for row in rows}
        self.assertTrue(spans & {1, 2, 3, 4, 6})
        for row in rows:
            self.assertLess(row["token_count"], base)
            self.assertEqual(row["n_masks"], 1)

    def test_pca_mca_sees_symbol_diffuse(self) -> None:
        src = lra_ius.original_tactics()
        drafts = lra_pca.guided_drafts(
            src,
            [{"family": "strength_reduction"}],
            {"n_have": 4, "n_rw": 1, "n_simp_all": 5, "n_induction": 1},
        )
        self.assertTrue(
            any("symbol_diffuse" in item.ops or item.family == "symbol_diffuse" for item in drafts)
            or any(fam == "symbol_diffuse" for fam, _body, _ops in lra_sym.pca_mca_ops(src)),
            [item.ops for item in drafts[:12]],
        )


if __name__ == "__main__":
    unittest.main()
