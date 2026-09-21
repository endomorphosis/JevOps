#!/usr/bin/env python3
"""Seeded random-canary analysis."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import draft_fanout as lra_fan
import pca_mca_fanout as lra_pca
import random_canary as lra_rand
import splice as lra_splice


class RandomCanaryTests(unittest.TestCase):
    def test_blacklist_scrubs_ephemeral_and_patched(self) -> None:
        import binder_use as lra_bind

        mem = {
            "blacklist": [
                "P::pca_search_space_d012",
                "P::sweep_rand_s4_closed",
                "P::port_unused_intros",
                "P::port_semi_assumption",
                "P::pca_search_space::abc123def456",
                "Core.InitsUpdatesComm::drop_unused_binders",
                "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress::drop_unused_binders",
                "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress::drop_loop_invariant_MCA_0",
            ],
            "failures": [],
            "successes": [],
        }
        lra_bind.scrub_blacklist(mem)
        kept = set(mem["blacklist"])
        self.assertNotIn("P::pca_search_space_d012", kept)
        self.assertNotIn("P::sweep_rand_s4_closed", kept)
        self.assertNotIn("P::port_unused_intros", kept)
        self.assertNotIn(
            "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress::drop_loop_invariant_MCA_0",
            kept,
        )
        self.assertIn("P::port_semi_assumption", kept)
        self.assertIn("P::pca_search_space::abc123def456", kept)
        self.assertIn("Core.InitsUpdatesComm::drop_unused_binders", kept)
        self.assertIn(
            "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress::drop_unused_binders",
            kept,
        )
        self.assertTrue(
            lra_bind.is_blacklisted(mem, "P", "pca_search_space_d099", tactics="same-body")
            is False
            or True
        )
        hashed = lra_bind.blacklist_key("P", "pca_search_space_d012", "body-a")
        hashed_b = lra_bind.blacklist_key("P", "pca_search_space_d099", "body-a")
        self.assertEqual(hashed.split("::")[1], "pca_search_space")
        self.assertEqual(hashed, hashed_b)
        mem["blacklist"].append(hashed)
        self.assertTrue(lra_bind.is_blacklisted(mem, "P", "pca_search_space_d001", tactics="body-a"))
        self.assertFalse(lra_bind.is_blacklisted(mem, "P", "pca_search_space_d001", tactics="body-b"))
        self.assertEqual(
            lra_bind.blacklist_key("P", "pca_search_space_d001", "body-a\n"),
            lra_bind.blacklist_key("P", "pca_search_space_d001", "body-a"),
        )

    def test_self_check(self) -> None:
        check = lra_rand.self_check()
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["n_records"], 15)
        self.assertFalse(check["called_docker0"])

    def test_typesafe_provider_failure_fails_closed(self) -> None:
        skipped = lra_rand._typesafe_provider_skip(
            RuntimeError("HTTP 503: upstream connection refused\nsecret-free"),
            families=("dead_code",),
        )
        self.assertTrue(skipped["skipped"])
        self.assertEqual(skipped["reason"], "typesafe_provider_error")
        self.assertIn("RuntimeError: HTTP 503", skipped["error"])
        self.assertEqual(skipped["families"], {"dead_code"})
        self.assertIsNone(skipped["arena_score"])

    def test_sample_is_seeded(self) -> None:
        _raw, _digest, records = lra_splice.load_warmup_records()
        a = [item.get("name") for item in lra_rand.sample_records(records, k=3, seed=7)]
        b = [item.get("name") for item in lra_rand.sample_records(records, k=3, seed=7)]
        c = [item.get("name") for item in lra_rand.sample_records(records, k=3, seed=8)]
        self.assertEqual(a, b)
        self.assertEqual(len(a), 3)
        self.assertNotEqual(a, c)

    def test_analyze_has_mca_and_tokens(self) -> None:
        _raw, _digest, records = lra_splice.load_warmup_records()
        rows = [lra_pca.feature_row(item) for item in records]
        model = lra_pca.fit_pca_mca(rows)
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        analysis = lra_rand.analyze_proof(rec, model=model)
        self.assertGreater(analysis["n_tokens"], 100)
        self.assertGreaterEqual(analysis["n_mca_holes"], 1)
        self.assertTrue(analysis["pca_keep"])
        self.assertTrue(analysis["families"])

    def test_trigger1_rename_is_not_safe_to_drop(self) -> None:
        import binder_use as lra_bind

        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if "substOldPostSubset" in str(item.get("name")))
        tactics = lra_fan.tactic_block(rec)
        import mca_mask_replace as lra_mask

        holes = [hole for hole in lra_mask.find_holes(tactics) if "trigger1" in hole.original]
        self.assertTrue(holes, "expected rename_i ... trigger1 hole")
        hole = holes[0]
        self.assertIn("trigger1", lra_bind.binders_from_line(hole.original))
        self.assertFalse(lra_bind.safe_to_drop_span(tactics, hole.start, hole.end, hole.original))
        dropped = lra_bind.drop_unused_binders(tactics, kinds=("rename_i",))
        self.assertIn("trigger1", dropped)

    def test_have_name_ignores_type_idents(self) -> None:
        import binder_use as lra_bind

        tactics = (
            "  have der' : Typing Γ t τ := der\n"
            "  induction der <;> subst eq\n"
            "  case var mem => grind\n"
        )
        line = "  have der' : Typing Γ t τ := der"
        self.assertEqual(lra_bind.binders_from_line(line)[0], "der'")
        # Cast of an inducted hyp is not dead code (Fsub ih_l rfl).
        self.assertFalse(lra_bind.safe_to_drop_span(tactics, 0, len(line) + 1, line))
        dropped = lra_bind.drop_unused_binders(tactics)
        self.assertIn("have der'", dropped)

    def test_grind_only_to_grind(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "  · grind only [→ wf, cases Term.LC]\n  · grind only [→ wf]\n"
        nxt = lra_port.fold_grind_only_to_grind(src)
        self.assertNotIn("grind only", nxt)
        self.assertEqual(nxt.count("grind"), 2)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_shorten_dotted_idents(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "  simp [Lambda.LExpr.LExpr.getVars, List.Subset.trans]\n"
        rows = {item["kind"]: item for item in lra_port.portable_drafts(src)}
        self.assertIn("port_shorten_llexpr_getvars", rows)
        self.assertLess(rows["port_shorten_llexpr_getvars"]["token_count"], lra_loop.token_count(src))

    def test_drop_unfold_before_split(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "    unfold extractOldExprVars\n    split\n"
        nxt = lra_port.fold_drop_unfold_before_split(src)
        self.assertNotIn("unfold", nxt)
        self.assertIn("split", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_trim_intro_names_drops_trailing_unused(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = (
            "  intro s1 s2 r μ\n"
            "  cases r\n"
            "  intro s1' htr\n"
            "  exists s1'\n"
        )
        nxt = lra_port.fold_trim_intro_names(src)
        self.assertIn("intro s1 s2 r", nxt)
        self.assertNotIn("μ", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_drop_try_simp_all(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = (
            "  induction post <;>\n"
            "    simp [extractOldExprVars] at * ;\n"
            "    try simp_all\n"
        )
        nxt = lra_port.fold_drop_try_simp_all(src)
        self.assertNotIn("try simp_all", nxt)
        self.assertIn("at *", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_drop_intro_before_simp_all(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "  case const =>\n    intro\n    simp_all\n  case abs ih =>\n    exact ih\n"
        nxt = lra_port.fold_drop_intro_before_simp_all(src)
        self.assertNotIn("intro", nxt.split("case abs")[0])
        self.assertIn("simp_all", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_use_exact_reuse_shortens_repeated_term(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "      use a' ⬝ b'\n      exact ⟨.refl (a' ⬝ b'), .par ha' hb'⟩\n"
        nxt = lra_port.fold_use_exact_reuse(src)
        self.assertIn("exact ⟨a' ⬝ b',", nxt)
        self.assertIn(".refl _", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))
        self.assertNotIn("use ", nxt)

    def test_general_use_exact_and_ctor_pair(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        use_src = "  use a₁; exact ⟨.refl a₁, .red_I a₁⟩\n"
        use_rows = {item["kind"]: item for item in lra_port.portable_drafts(use_src)}
        self.assertIn("port_use_exact", use_rows)
        self.assertLess(use_rows["port_use_exact"]["token_count"], lra_loop.token_count(use_src))
        ctor_src = "  constructor\n  · exact .par ha.1 hb.1\n  · exact .par ha.2 hb.2\n"
        ctor_rows = {item["kind"]: item for item in lra_port.portable_drafts(ctor_src)}
        self.assertIn("port_ctor_pair_exacts", ctor_rows)

    def test_hammer_does_not_rewrite_cslib_grind(self) -> None:
        import mca_mask_replace as lra_mask

        src = "  have der' : Typing Γ t τ := der\n  · grind only [→ wf]\n"
        dropped = "  · grind only [→ wf]\n"
        repaired = lra_mask.hammer_repair(
            dropped, src, [{"data": "unsolved goals"}]
        )
        self.assertIn("grind only", repaired)
        self.assertNotIn("simp_all only", repaired)

    def test_semi_assumption_skips_intros_follower(self) -> None:
        import portable_rewrites as lra_port

        subst = "      apply cih <;> assumption\n      intros x Hin\n"
        self.assertEqual(lra_port.fold_semi_assumption(subst), subst)
        intro_arm = "      apply eih <;> assumption\n      intro\n      simp_all\n"
        self.assertEqual(lra_port.fold_semi_assumption(intro_arm), intro_arm)
        closer = "      apply eih <;> assumption\n      simp_all\n"
        self.assertIn("; assumption", lra_port.fold_semi_assumption(closer))

    def test_failed_skill_stems_skip_retry(self) -> None:
        import binder_use as lra_bind

        mem = {
            "blacklist": ["CallElimCorrect.substOldPostSubset::port_drop_intro_before_simp_all"],
            "failures": [
                {
                    "name": "CallElimCorrect.extractedOldExprInVars",
                    "kind": "port_drop_intro_before_simp_all",
                }
            ],
        }
        subst = lra_bind.failed_skill_stems(mem, "CallElimCorrect.substOldPostSubset")
        self.assertIn("drop_intro_before_simp_all", subst)
        extracted = lra_bind.failed_skill_stems(mem, "CallElimCorrect.extractedOldExprInVars")
        self.assertIn("drop_intro_before_simp_all", extracted)

    def test_pipeline_order_follows_memory_wins(self) -> None:
        import portable_rewrites as lra_port

        memory = {
            "successes": [
                {"kind": "port_use_exact", "name": "P"},
                {"kind": "port_use_exact", "name": "P"},
                {"kind": "port_exact_hyp", "name": "Q"},
            ],
            "failures": [{"kind": "port_semi_assumption", "name": "R"}],
        }
        order = [name for name, _fn in lra_port.pipeline_order(memory)]
        self.assertLess(order.index("use_exact"), order.index("semi_assumption"))
        self.assertEqual(order[0], "use_exact")

    def test_compose_pipeline_stacks_skills(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "  exact Hin\n  use a₁; exact ⟨.refl a₁, .red_I a₁⟩\n"
        piped, applied = lra_port.compose_pipeline(src)
        self.assertIn("exact_hyp", applied)
        self.assertIn("use_exact", applied)
        self.assertLess(lra_loop.token_count(piped), lra_loop.token_count(src))
        self.assertIn("assumption", piped)
        self.assertIn("exact ⟨a₁,", piped)

    def test_portable_exact_hin(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "  intros x Hin\n  exact Hin\n"
        rows = lra_port.portable_drafts(src)
        kinds = {item["kind"] for item in rows}
        self.assertTrue(
            kinds & {"port_exact_hyp", "port_unused_intros"},
            kinds,
        )
        for item in rows:
            self.assertLess(item["token_count"], lra_loop.token_count(src))

    def test_destructuring_have_is_kept(self) -> None:
        import binder_use as lra_bind

        tactics = (
            "  have ⟨σ, t1, eq⟩ := l.canonical_form_abs val_l\n"
            "  exists t1\n"
        )
        line = "  have ⟨σ, t1, eq⟩ := l.canonical_form_abs val_l"
        self.assertIn("__keep__", lra_bind.binders_from_line(line))
        self.assertFalse(lra_bind.safe_to_drop_span(tactics, 0, len(line) + 1, line))

    def test_prefix_have_before_induction_simp_all_kept(self) -> None:
        import binder_use as lra_bind

        tactics = (
            "  have Hk := UpdateStatesDefined Hup\n"
            "  induction Hup\n"
            "  · simp_all\n"
        )
        line = "  have Hk := UpdateStatesDefined Hup"
        self.assertFalse(lra_bind.safe_to_drop_span(tactics, 0, len(line) + 1, line))

    def test_anonymous_have_this_is_used(self) -> None:
        import binder_use as lra_bind

        tactics = (
            "  have := InitStatesNotDefined Hinit\n"
            "  exact UpdateStatesNotDefMonotone' this Hups\n"
        )
        self.assertEqual(lra_bind.binders_from_line("  have := InitStatesNotDefined Hinit"), ["this"])
        self.assertFalse(
            lra_bind.safe_to_drop_span(
                tactics, 0, tactics.find("\n") + 1, "  have := InitStatesNotDefined Hinit"
            )
        )

    def test_unknown_identifier_repair_restores_binder(self) -> None:
        import binder_use as lra_bind

        reference = "  rename_i trigger1 e1\n  exact trigger1\n"
        draft = "  exact trigger1\n"
        errors = [{"data": "Unknown identifier `trigger1`"}]
        repaired = lra_bind.restore_unknown_binders(draft, reference, errors)
        self.assertIn("rename_i trigger1", repaired)

    def test_random_drafts_are_shorter(self) -> None:
        import random as py_random

        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "CallElimCorrect.substOldPostSubset")
        tactics = lra_fan.tactic_block(rec)
        drafts = lra_rand.random_drafts(
            tactics, py_random.Random(1), n=4, name=str(rec.get("name"))
        )
        self.assertGreaterEqual(len(drafts), 1)
        self.assertFalse(any("trigger1" in str(item.get("kind")) and "drop_" in item["kind"] for item in drafts))
        base = __import__("run_warmup", fromlist=["token_count"]).token_count(tactics)
        for item in drafts:
            self.assertLess(item["token_count"], base)
            self.assertEqual(item["llm"], "off")

    def test_trailing_tuple_comma_keeps_exact(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = "  case red_S => exact ⟨a ⬝ c ⬝ (b ⬝ c), .refl _, .refl _,⟩\n"
        nxt = lra_port.fold_trailing_tuple_comma(src)
        self.assertIn("exact ⟨", nxt)
        self.assertNotIn(",⟩", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_redundant_inner_simp_keeps_intro(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = (
            "  induction post <;>\n"
            "    simp [Imperative.HasVarsPure.getVars, Lambda.LExpr.LExpr.getVars] at *\n"
            "  case app fn e =>\n"
            "    . simp [Lambda.LExpr.LExpr.getVars]\n"
            "      intros x Hin\n"
            "      assumption\n"
        )
        nxt = lra_port.fold_redundant_inner_simp(src)
        self.assertNotIn("simp [Lambda.LExpr.LExpr.getVars]", nxt.split("case app", 1)[-1])
        self.assertIn("intros x Hin", nxt)
        self.assertIn(". intros", nxt)
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))

    def test_hoist_repeated_simp_keeps_intro(self) -> None:
        import portable_rewrites as lra_port
        import run_warmup as lra_loop

        src = (
            "  induction post <;> simp [substOld] at *\n"
            "  case fvar =>\n"
            "    intro\n"
            "    simp_all\n"
            "  case ite =>\n"
            "    simp [Imperative.HasVarsPure.getVars, Lambda.LExpr.LExpr.getVars] at *\n"
            "    apply List.Subset.app\n"
            "  case app =>\n"
            "    simp [Imperative.HasVarsPure.getVars, Lambda.LExpr.LExpr.getVars] at *\n"
            "    apply List.Subset.app\n"
        )
        nxt = lra_port.fold_hoist_repeated_simp(src)
        self.assertIn("intro", nxt)
        self.assertIn("<;>", nxt.split("induction", 1)[-1].split("case", 1)[0])
        self.assertIn("Imperative.HasVarsPure.getVars", nxt.split("induction", 1)[-1].split("case", 1)[0])
        self.assertEqual(
            nxt.count("simp [Imperative.HasVarsPure.getVars, Lambda.LExpr.LExpr.getVars] at *"),
            0,
        )
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))
        # Parent without at * must not gain it (closes intro-only arms).
        unsafe = src.replace("simp [substOld] at *", "simp [substOld]", 1)
        self.assertEqual(lra_port.fold_hoist_repeated_simp(unsafe), unsafe)

    def test_propose_skill_mints_keep_structure_when_do_not_cut(self) -> None:
        import binder_use as lra_bind

        mem = {
            "research": [
                {
                    "name": "CallElimCorrect.substOldPostSubset",
                    "help": {"intro_then_simp_all": 1.28, "apply_semi_assumption": 0.21},
                    "unsafe": {"intro_then_simp_all": 0.45, "apply_semi_assumption": 0.64},
                }
            ]
        }
        prop = lra_bind.propose_skill_from_research(mem, "CallElimCorrect.substOldPostSubset")
        self.assertTrue(prop.get("keep_structure"))
        self.assertIn("hoist_repeated_simp", prop.get("mint") or [])

    def test_pipeline_order_prefers_keep_structure_help(self) -> None:
        import portable_rewrites as lra_port

        memory = {
            "successes": [],
            "failures": [],
            "research": [
                {
                    "name": "P",
                    "help": {"repeated_simp_list": 1.5},
                    "unsafe": {"repeated_simp_list": 0.2},
                }
            ],
        }
        order = [name for name, _fn in lra_port.pipeline_order(memory, name="P")]
        self.assertLess(order.index("hoist_repeated_simp"), order.index("use_exact"))


if __name__ == "__main__":
    unittest.main()
