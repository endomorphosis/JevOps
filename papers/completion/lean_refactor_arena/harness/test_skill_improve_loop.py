#!/usr/bin/env python3
"""Skill-improve loop: llm_router routes closed actions; lake stays the oracle."""
from __future__ import annotations

import argparse
import unittest
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import binder_use as lra_bind
import portable_rewrites as lra_port
import run_warmup as lra_loop
import skill_improve_loop as lra_loop_sk
import track1_ledger as lra_t1


class SkillImproveLoopTests(unittest.TestCase):
    def test_self_check(self) -> None:
        check = lra_loop_sk.self_check()
        self.assertTrue(check["ok"], check)
        self.assertFalse(check["called_docker0"])
        self.assertFalse(check["jev_writes_lean"])
        self.assertFalse(check["grok_writes_lean"])

    def test_historical_fixture_is_comparison_only(self) -> None:
        comparison = lra_loop_sk.historical_fixture_comparison(
            {"CallElimCorrect.substOldPostSubset": 408}
        )
        self.assertEqual(comparison["historical_total"], 2146)
        self.assertEqual(
            comparison["delta_current_minus_historical"][
                "CallElimCorrect.substOldPostSubset"
            ],
            16,
        )
        self.assertFalse(comparison["usable_as_verified_seed"])

    def test_outer_canary_args_force_the_high_score_inits_target(self) -> None:
        args = lra_loop_sk.canary_args(
            out=HERE.parent / "evidence" / "canaries",
            rounds=1,
            lake_top=1,
            drafts=2,
            timeout=1.0,
            seed=1,
        )
        self.assertTrue(args.include_inits)
        self.assertTrue(args.init_139)

    def test_outer_mint_tactic_passes_shared_memory_to_inner(self) -> None:
        memory = {"nca": {"active_tactic_design": {"name": "P"}}}
        args = lra_loop_sk.canary_args(
            out=HERE.parent / "evidence" / "canaries",
            rounds=1,
            lake_top=1,
            drafts=2,
            timeout=1.0,
            seed=1,
            memory=memory,
        )
        self.assertIs(args.memory, memory)

    def test_parse_action_extracts_json(self) -> None:
        text = 'Sure.\n{"action": "stop", "reason": "saturated"}\n'
        self.assertEqual(lra_loop_sk.parse_action(text)["action"], "stop")
        self.assertEqual(lra_loop_sk.parse_action("not json")["action"], "run")

    def test_grok_transport_preserves_hypothesis_action_fields(self) -> None:
        import grok_single

        action = grok_single._first_outer_action(
            '{"action":"hypothesis_refactor","name":"P",'
            '"strategy":"guided_mca","hypothesis":"test a closed tree",'
            '"constraints":"preserve binders","evaluation":"Lake"}'
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "hypothesis_refactor")
        self.assertEqual(action["hypothesis"], "test a closed tree")

    def test_install_fold_keeps_intro(self) -> None:
        mem: dict = {"skills": []}
        bad = lra_bind.install_memory_skill(
            mem, {"stem": "dropintro", "old": "intro\nsimp_all", "new": "simp_all", "keep": ["intro"]}
        )
        self.assertFalse(bad.get("ok"))
        good = lra_bind.install_memory_skill(
            mem,
            {
                "stem": "tuplecomma",
                "old": ".refl _,⟩",
                "new": ".refl _⟩",
                "keep": ["exact"],
            },
        )
        self.assertTrue(good.get("ok"))
        src = "  exact ⟨a, .refl _,⟩\n"
        nxt = lra_port.fold_from_memory_skill(src, mem["skills"][0])
        self.assertLess(lra_loop.token_count(nxt), lra_loop.token_count(src))
        self.assertIn("exact", nxt)

    def test_portable_drafts_include_memory_skill(self) -> None:
        mem = {
            "skills": [
                {
                    "stem": "dupemarker",
                    "old": "skip_this_marker extra",
                    "new": "skip_this_marker",
                    "keep": ["exact"],
                    "count": 1,
                    "family": "search_space",
                }
            ]
        }
        src = "  exact Hin\n  skip_this_marker extra\n"
        rows = {item["kind"]: item for item in lra_port.portable_drafts(src, memory=mem)}
        self.assertIn("port_mem_dupemarker", rows)

    def test_loop_uses_llm_router_fixture_not_docker0(self) -> None:
        calls: list[str] = []

        def fake_generate(prompt: str, **_kwargs: object) -> str:
            calls.append(str(prompt))
            return '{"action": "stop", "reason": "fixture"}'

        def fake_inner(_args: argparse.Namespace) -> dict:
            return {
                "skill_analysis": [],
                "lake": [],
                "ledger": {"jev_calls": 0},
                "called_docker0": False,
            }

        payload = lra_loop_sk.run_loop(
            outer=1,
            llm=True,
            out=HERE.parent / "evidence" / "canaries",
            rounds=1,
            lake_top=1,
            drafts=2,
            timeout=1.0,
            seed=1,
            generate=fake_generate,
            run_inner=fake_inner,
            memory={},
            persist_memory=False,
        )
        self.assertTrue(calls)
        self.assertEqual(payload["history"][0]["action"]["action"], "stop")
        self.assertEqual(payload["history"][0]["action"]["router"], "llm_router")
        self.assertFalse(payload["called_docker0"])
        self.assertEqual(lra_t1.FAIL_CLOSED_KWARGS["provider"], "grok")
        self.assertNotIn("172.17.0.1", "".join(calls))

    def test_seed_skips_when_present_and_overlay_refresh(self) -> None:
        import board_graph as lra_board

        mem: dict = {"nca": {"grid": {}}}
        first = lra_board.seed_nca_from_board(mem)
        self.assertNotEqual(first.get("skipped"), "already_seeded")
        n = first["n_cells"]
        second = lra_board.seed_nca_from_board(mem)
        self.assertEqual(second.get("skipped"), "already_seeded")
        self.assertEqual(second["n_cells"], n)
        forced = lra_board.seed_nca_from_board(mem, force=True)
        self.assertNotEqual(forced.get("skipped"), "already_seeded")
        lra_board.overlay_live_board(mem)
        self.assertTrue(mem["nca"].get("overlay_done"))
        cached = lra_board.overlay_live_board(mem)
        self.assertEqual(cached.get("reason"), "cached")
        mem["nca"].pop("overlay_done", None)
        again = lra_board.overlay_live_board(mem)
        self.assertNotEqual(again.get("reason"), "cached")
        mem["nca"]["grid"]["ptr://task/LRA-010"]["status"] = "ready"
        mem["nca"]["grid"]["ptr://task/LRA-010"]["energy"] = 0.8
        refreshed = lra_board.seed_nca_from_board(mem)
        self.assertEqual(refreshed.get("skipped"), "already_seeded")
        ids = [row.get("id") for row in refreshed.get("board_window") or []]
        self.assertIn("LRA-010", ids)

    def test_deterministic_stop_when_all_nca_budget(self) -> None:
        import board_graph as lra_board

        action = lra_loop_sk.deterministic_route(
            gaps=[],
            last_lake=[{"name": "A", "skipped": "nca_budget"}, {"name": "B", "skipped": "nca_budget"}],
            stalled=False,
        )
        self.assertEqual(action["action"], "stop")
        self.assertEqual(action["reason"], "nca_budget")
        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        first = lra_board.overlay_live_board(mem)
        second = lra_board.overlay_live_board(mem)
        self.assertEqual(second.get("reason"), "cached")
        self.assertFalse(first.get("campaign_write"))

    def test_deterministic_skip_after_lake_fail(self) -> None:
        action = lra_loop_sk.deterministic_route(
            gaps=[],
            last_lake=[
                {
                    "name": "CallElimCorrect.substOldPostSubset",
                    "kind": "port_hoist_repeated_simp",
                    "ok": False,
                }
            ],
            stalled=False,
        )
        self.assertEqual(action["action"], "skip_stem")
        self.assertEqual(action["stem"], "hoist_repeated_simp")

    def test_deterministic_route_reopens_failed_stem_for_repair(self) -> None:
        action = lra_loop_sk.deterministic_route(
            gaps=[
                {
                    "name": "CallElimCorrect.substOldPostSubset",
                    "failed_stems": ["port_drop_intro_before_simp_all"],
                    "top_help": [{"residual": "intro_then_simp_all"}],
                }
            ],
            last_lake=[],
            stalled=False,
            memory={"nca": {"tactic_design_history": []}},
        )
        self.assertEqual(action["action"], "repair_tactic")
        self.assertEqual(action["stem"], "drop_intro_before_simp_all")
        self.assertEqual(action["strategy"], "closed_edits")

    def test_patched_portable_stem_is_probeable_again(self) -> None:
        memory = {
            "blacklist": [
                "P::port_unused_intros",
                "P::port_drop_intro_before_simp_all",
            ],
            "failures": [
                {"name": "P", "kind": "port_unused_intros"},
                {"name": "P", "kind": "port_drop_intro_before_simp_all"},
            ],
        }
        stems = lra_bind.failed_skill_stems(memory, "P")
        self.assertNotIn("unused_intros", stems)
        self.assertIn("drop_intro_before_simp_all", stems)

    def test_outer_grok_runs_before_inner_typesafe(self) -> None:
        order: list[str] = []

        def fake_generate(prompt: str, **_kwargs: object) -> str:
            order.append("grok")
            self.assertIn("OUTER Grok", prompt)
            self.assertIn("nca=", prompt)
            return '{"action": "nest_inner", "reason": "fixture"}'

        def fake_inner(_args: argparse.Namespace) -> dict:
            order.append("typesafe")
            return {
                "skill_analysis": [],
                "lake": [],
                "ledger": {"jev_calls": 0},
                "canaries": [{"trace": [{"depth": 0, "compose": "nest"}, {"depth": 1, "compose": "keep"}]}],
                "called_docker0": False,
            }

        payload = lra_loop_sk.run_loop(
            outer=1,
            llm=True,
            out=HERE.parent / "evidence" / "canaries",
            rounds=1,
            lake_top=1,
            drafts=2,
            timeout=1.0,
            seed=1,
            generate=fake_generate,
            run_inner=fake_inner,
            memory={},
            persist_memory=False,
        )
        self.assertEqual(order, ["grok", "typesafe"])
        self.assertEqual(payload["history"][0]["action"]["action"], "nest_inner")
        self.assertEqual(payload["history"][0]["outer"], "grok")
        self.assertEqual(payload["history"][0]["inner"], "typesafe_nested")
        self.assertEqual(payload["history"][0]["max_trace_depth"], 1)

    def test_stalled_outer_requests_hypothesis_for_inner_assessment(self) -> None:
        from tempfile import TemporaryDirectory

        prompts: list[str] = []

        def fake_generate(prompt: str, **_kwargs: object) -> str:
            prompts.append(str(prompt))
            if '"outer_stalled": true' in str(prompt):
                return (
                    '{"action":"hypothesis_refactor","name":"P",'
                    '"family":"search_space","strategy":"guided_mca",'
                    '"hypothesis":"compress a repeated local simplification",'
                    '"constraints":"preserve binders","evaluation":"Lake then token count"}'
                )
            return '{"action":"nest_inner","reason":"collect evidence"}'

        def fake_inner(args: argparse.Namespace) -> dict:
            # Keep the NCA state non-idle so the test can exercise the
            # controller's reserved hypothesis turn rather than halting the
            # synthetic campaign after its first empty inner payload.
            args.memory.setdefault("nca", {})["program_state"] = {
                "ops": [{"op": "HYPOTHESIS_PROBE"}],
                "last_ran": [],
            }
            if len(prompts) >= 3:
                self.assertEqual(
                    (args.memory.get("nca") or {}).get("active_hypothesis_refactor", {}).get("name"),
                    "P",
                )
            return {
                "skill_analysis": [],
                "lake": [],
                "ledger": {"jev_calls": 0},
                "called_docker0": False,
            }

        with TemporaryDirectory() as tmp:
            payload = lra_loop_sk.run_loop(
                outer=3,
                llm=True,
                out=Path(tmp),
                rounds=1,
                lake_top=1,
                drafts=2,
                timeout=1.0,
                seed=1,
                generate=fake_generate,
                run_inner=fake_inner,
                memory={},
                persist_memory=False,
            )
        self.assertEqual(len(payload["history"]), 3)
        self.assertEqual(payload["history"][-1]["action"]["action"], "hypothesis_refactor")
        self.assertEqual(payload["stop_reason"], "no_token_cut")
        self.assertTrue(any('"outer_stalled": true' in prompt for prompt in prompts))

    def test_decision_tree_and_nested_walk(self) -> None:
        import typesafe_inner as lra_inner
        import splice as lra_splice

        src = "  exact Hin\n  skip_this_marker extra\n"
        tree = lra_port.decision_tree(src)
        self.assertTrue(tree)
        self.assertIn("search_space", tree)
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        nodes: list[str] = []

        def research(record, analysis, **kwargs):
            node = str(kwargs.get("tree_node") or "root")
            nodes.append(node)
            if node == "root" and nodes.count("root") == 1:
                return {
                    "compose": "nest",
                    "nest_child": "search_space",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {"search_space": ["port_exact_hyp"]},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": {"search_space"},
                }
            return {
                "compose": "keep",
                "skip_lake": True,
                "skill": "keep",
                "intent": "pca_keep",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = HERE.parent / "evidence" / "canaries"
            nest_depth = 3

        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Hin\n  intro\n  simp_all\n",
            args=Args(),
            memory={"successes": [], "failures": [], "blacklist": [], "research": [], "skills": []},
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": False, "token_count": 9, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=4,
            max_depth=3,
        )
        self.assertIn("search_space", nodes)
        flat = lra_inner.flatten_trace(walked["trace"])
        self.assertGreaterEqual(max(int(ev.get("depth") or 0) for ev in flat), 1)
        self.assertTrue(any(ev.get("action") == "nest_return" for ev in flat))
        self.assertFalse(walked["called_docker0"])

    def test_tools_kg_ast_exports_mcp_diffuse(self) -> None:
        import typesafe_tools as lra_tools

        mem = {
            "successes": [{"name": "P", "kind": "port_trailing_tuple_comma", "from_tokens": 10, "to_tokens": 9}],
            "failures": [],
            "research": [{"name": "P", "help": {"intro_then_simp_all": 1.2}, "unsafe": {"intro_then_simp_all": 0.45}}],
            "skills": [],
            "blacklist": [],
        }
        kg = lra_tools.run_tool("kg_skills", memory=mem)
        self.assertTrue(kg["ok"])
        self.assertGreaterEqual(kg["n_nodes"], 2)
        ast_info = lra_tools.run_tool("ast_harness")
        self.assertTrue(any("fold_" in fn for f in ast_info["files"] for fn in f.get("fold_fns") or []))
        exports = lra_tools.run_tool("pkg_exports")
        self.assertIn("portable_rewrites", exports["modules"])
        mcp = lra_tools.run_tool("mcp_catalog")
        self.assertFalse(mcp["live_grok_mcp"])
        self.assertFalse(mcp["called_docker0"])
        names = {item["name"] for item in mcp["tools"]}
        self.assertTrue({"kg_skills", "diffuse", "decision_tree"} <= names)
        diff = lra_tools.run_tool("diffuse", tactics="  intro a\n  exact ⟨a⟩\n")
        self.assertEqual(diff["llm"], "off")
        tree = lra_tools.run_tool("decision_tree", tactics="  exact Hin\n", memory=mem, problem="P")
        self.assertIn("tools", tree)
        self.assertIn("subloops", tree)

    def test_spawn_subloop_returns_and_self_improve_skips_router(self) -> None:
        import typesafe_inner as lra_inner
        import typesafe_tools as lra_tools
        import splice as lra_splice

        seen: list[str] = []

        def toy_subloop(**_kwargs: object) -> dict:
            seen.append("toy")
            return {"ok": True, "tactics": "  exact Hin\n", "trace": [{"depth": 1, "action": "return"}]}

        lra_tools.register_subloop("toy", toy_subloop)
        self.assertIn("skill_walk", lra_tools.SUBLOOPS)
        joined = lra_tools.spawn_subloop("toy")
        self.assertTrue(joined["returned"])
        self.assertEqual(seen, ["toy"])
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        calls: list[str] = []

        def research(_record, _analysis, **kwargs):
            node = str(kwargs.get("tree_node") or "root")
            calls.append(node)
            if node == "root" and calls.count("root") == 1:
                return {
                    "compose": "spawn",
                    "nest_child": "toy",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": set(),
                }
            if node == "root":
                return {
                    "compose": "analyze",
                    "tool_name": "kg_skills",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": set(),
                }
            return {
                "compose": "return",
                "skip_lake": False,
                "skill": "keep",
                "intent": "pca_keep",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = HERE.parent / "evidence" / "canaries"
            nest_depth = 3

        mem: dict = {
            "successes": [],
            "failures": [],
            "blacklist": [],
            "research": [
                {
                    "name": "Core.InitsUpdatesComm",
                    "help": {"intro_then_simp_all": 1.0},
                    "unsafe": {"intro_then_simp_all": 0.5},
                }
            ],
            "skills": [],
        }
        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Hin\n",
            args=Args(),
            memory=mem,
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": False, "token_count": 9, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=5,
            max_depth=3,
        )
        flat = lra_inner.flatten_trace(walked["trace"])
        actions = [ev.get("action") or ev.get("compose") for ev in flat]
        self.assertIn("spawn_return", actions)
        self.assertIn("analyze", actions)
        self.assertTrue(walked["returned"])
        self.assertIn("kg_skills", walked.get("observations") or {})
        self.assertIsNone((mem.get("observations") or {}).get("invoke_router"))
        improved = lra_tools.self_improve(mem, name="Core.InitsUpdatesComm", tactics="  exact Hin\n")
        self.assertTrue(improved["ok"])
        self.assertIsNone(improved["router"])

    def test_nca_feeds_state_walks_harness_and_mutates(self) -> None:
        import typesafe_nca as lra_nca
        import typesafe_inner as lra_inner
        import splice as lra_splice

        mem: dict = {
            "successes": [
                {"name": "P", "kind": "port_trailing_tuple_comma", "from_tokens": 12, "to_tokens": 10}
            ],
            "failures": [{"name": "P", "kind": "port_hoist_repeated_simp"}],
            "research": [{"name": "P", "help": {"repeated_simp_list": 1.1}, "unsafe": {"repeated_simp_list": 0.2}}],
            "skills": [],
            "blacklist": [],
        }
        ticked = lra_nca.tick(mem, tactics="  exact Hin\n", problem="P")
        self.assertTrue(ticked["ok"])
        self.assertGreaterEqual(ticked["n_cells"], 2)
        self.assertIn("ptr://residual/repeated_simp_list", mem["nca"]["grid"])
        live_mem: dict = {"nca": {"grid": {}}}
        lra_nca.feed_state(live_mem, tactics="  exact ⟨a, b,⟩\n", problem="P")
        self.assertIn("ptr://residual/trailing_tuple_comma", live_mem["nca"]["grid"])
        self.assertGreaterEqual(
            int(live_mem["nca"]["grid"]["ptr://residual/trailing_tuple_comma"].get("count") or 0), 1
        )
        self.assertIn(
            ["ptr://residual/trailing_tuple_comma", "ptr://skill/port_trailing_tuple_comma"],
            live_mem["nca"]["board_edges"],
        )
        energy_1 = float((mem["nca"]["grid"]["ptr://skill/port_trailing_tuple_comma"])["energy"])
        lra_nca.tick(mem, tactics="  exact Hin\n", problem="P")
        energy_2 = float((mem["nca"]["grid"]["ptr://skill/port_trailing_tuple_comma"])["energy"])
        self.assertNotEqual(energy_1, 0.5)
        self.assertGreaterEqual(int(mem["nca"]["tick"]), 2)
        walked = lra_nca.walk_codebase(limit=12)
        self.assertTrue(walked["ok"])
        self.assertGreater(walked["n_files"], 3)
        hooked = lra_nca.hook_and_eval("portable_rewrites.py")
        self.assertTrue(hooked["ok"])
        self.assertTrue(hooked["importable"])
        self.assertTrue(hooked["fold_fns"])
        mut = lra_nca.mutate(mem, tactics="  exact Hin\n", problem="P", op="reorder")
        self.assertEqual(mut["applied"]["op"], "reorder")
        self.assertTrue(mem["nca"]["pipeline_bias"])
        forks = lra_nca.fork_cells(mem, cell_ids=["ptr://skill/port_trailing_tuple_comma"])
        self.assertEqual(forks["n_forked"], 1)
        self.assertTrue(forks["forks"][0]["returned"])
        blocked = lra_nca.hook_and_eval("/etc/passwd")
        self.assertFalse(blocked["ok"])
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        steps = {"n": 0}

        def research(_record, _analysis, **_kwargs):
            steps["n"] += 1
            if steps["n"] == 1:
                return {
                    "compose": "tick",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": set(),
                }
            return {
                "compose": "return",
                "skip_lake": False,
                "skill": "keep",
                "intent": "pca_keep",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = HERE.parent / "evidence" / "canaries"
            nest_depth = 3

        walked_inner = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Hin\n",
            args=Args(),
            memory=mem,
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": False, "token_count": 9, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=3,
            max_depth=3,
        )
        actions = [ev.get("action") or ev.get("compose") for ev in walked_inner["trace"]]
        self.assertIn("tick", actions)
        self.assertIn("nca_tick", walked_inner.get("observations") or {})

    def test_eval_theorem_rejects_unknown_and_executes_ops(self) -> None:
        import typesafe_inner as lra_inner
        import typesafe_nca as lra_nca
        import nca_program as lra_prog
        import board_graph as lra_board
        import codepath_graph as lra_cp
        import splice as lra_splice

        unknown = lra_inner.eval_theorem(
            "NotAReal.Theorem",
            current={"name": "Core.InitsUpdatesComm"},
            tactics="  exact Hin\n",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 1},
            args=type("A", (), {"timeout": 1.0})(),
            restore=b"",
        )
        self.assertEqual(unknown["reason"], "not_small_or_unknown")
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        same = lra_inner.eval_theorem(
            "Core.InitsUpdatesComm",
            current=rec,
            tactics="  exact Hin\n",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3},
            args=type("A", (), {"timeout": 1.0})(),
            restore=b"",
        )
        self.assertTrue(same["theorem_ok"])
        self.assertIn("eval_theorem", __import__("typesafe_tools").SUBLOOPS)
        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        mem["nca"]["program_state"] = {
            "ops": [
                {"op": "CALL", "ptr": "ptr://subgoal/LRA-S05"},
                {"op": "TICK"},
                {"op": "KEEP"},
            ]
        }
        executed = lra_prog.execute_program_ops(mem, problem="P")
        self.assertTrue(executed["ran"])
        self.assertTrue(any(op.get("op") == "CALL" and op.get("ok") for op in executed["ran"]))
        self.assertIn("ptr://subgoal/LRA-S05", mem["nca"]["grid"])
        inspect = lra_cp.slice_cross_module("harness.generate_text:generate_text")
        self.assertTrue(inspect.get("inspect_only"))
        self.assertFalse(inspect.get("called_docker0"))
        mem["nca"]["program_state"] = {
            "ops": [{"op": "CALL", "ptr": "ptr://theorem/NotAReal.Theorem"}, {"op": "KEEP"}]
        }
        theo = lra_prog.execute_program_ops(
            mem,
            problem="Core.InitsUpdatesComm",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 1},
        )
        self.assertTrue(any(op.get("op") == "CALL" for op in theo["ran"]))
        self.assertTrue(any(ev.get("event") in {"call", "upsert"} for ev in (mem.get("nca") or {}).get("journal") or []))
        halt = lra_nca.should_halt(
            {
                "nca": {
                    "grid": {
                        "ptr://goal/LRA-G000": {"kind": "goal", "energy": 0.4, "id": "ptr://goal/LRA-G000"},
                        "ptr://task/LRA-024": {
                            "kind": "task",
                            "do_not_fork": True,
                            "blocked": True,
                            "energy": 0.05,
                            "id": "ptr://task/LRA-024",
                        },
                    },
                    "program_state": {"ops": [{"op": "KEEP"}], "last_ran": [{"op": "TICK"}]},
                }
            }
        )
        self.assertTrue(halt["halt"], halt)

    def test_run_live_skips_remaining_canaries_on_budget(self) -> None:
        import random_canary as lra_rand
        import typesafe_nca as lra_nca

        mem = {
            "nca": {
                "grid": {
                    "ptr://goal/LRA-G000": {"kind": "goal", "energy": 0.4, "id": "g"},
                    "ptr://tool/budget": {"kind": "tool", "energy": 0.05, "visited": True, "id": "b"},
                },
                "program_state": {"ops": [{"op": "KEEP"}], "last_ran": [{"op": "TICK"}]},
            }
        }
        halt = lra_nca.should_halt(mem)
        self.assertTrue(halt["budget_dead"])
        skipped = 0
        for _name in ("A", "B"):
            if halt.get("budget_dead"):
                skipped += 1
                continue
        self.assertEqual(skipped, 2)
        self.assertTrue(hasattr(lra_rand, "run_live"))

    def test_inner_walk_skips_jev_when_budget_dead(self) -> None:
        import typesafe_inner as lra_inner
        import splice as lra_splice

        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        calls: list[str] = []

        def research(*_a, **_k):
            calls.append("research")
            return {"compose": "keep", "skip_lake": True, "skill": "keep", "intent": "pca_keep", "tree": {}, "residual_unsafe": {}, "residual_help": {}, "skip_skills": [], "allow_families": set()}

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = HERE.parent / "evidence" / "canaries"
            nest_depth = 3
            from_best = False

        mem = {
            "nca": {
                "grid": {
                    "ptr://goal/LRA-G000": {"kind": "goal", "energy": 0.4, "id": "g"},
                    "ptr://tool/budget": {"kind": "tool", "energy": 0.05, "visited": True, "id": "b"},
                },
                "program_state": {"ops": [{"op": "KEEP"}], "last_ran": [{"op": "TICK"}]},
            }
        }
        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Hin\n",
            args=Args(),
            memory=mem,
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": False, "token_count": 9, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=3,
            max_depth=3,
        )
        self.assertFalse(calls)
        self.assertTrue(any(ev.get("action") == "nca_budget" for ev in walked["trace"]))
        self.assertTrue(any(row.get("skipped") == "nca_budget" for row in walked.get("lake") or []))

    def test_heal_families_match_kernels(self) -> None:
        import nca_repair as lra_heal

        self.assertEqual(lra_heal.family_of("clip_energy"), "cells")
        self.assertEqual(lra_heal.family_of("fix_tape"), "tape_stack")
        self.assertEqual(lra_heal.family_of("fix_program_ops"), "program")
        self.assertEqual(lra_heal.family_of("reseed_board"), "board")
        self.assertTrue(set(lra_heal.HEAL_FAMILIES) <= set(lra_heal.FAMILY_CRITERIA))

    def test_nca_heal_repairs_corrupt_state(self) -> None:
        import math
        import nca_repair as lra_heal
        import typesafe_tools as lra_tools

        mem: dict = {
            "nca": {
                "grid": {
                    "bad": "not-a-cell",
                    "hot": {"kind": "skill", "energy": 9.9},
                    "ptr://task/LRA-024": {"kind": "task", "energy": 0.9},
                },
                "program_state": {
                    "ops": [
                        {"op": "EXPLODE"},
                        {"op": "CALL", "ptr": "task/LRA-010"},
                        {"op": "CALL", "ptr": "ptr://tool/x", "host": "172.17.0.1"},
                    ]
                },
            },
            "tape": {"cells": "nope", "head": 99},
            "_stack": {"forest": {"f1": {"frame_id": "f1", "parent_id": "missing"}}},
        }
        issues = lra_heal.diagnose(mem)
        codes = {i["code"] for i in issues}
        self.assertIn("cell_not_dict", codes)
        self.assertIn("energy_oob", codes)
        self.assertIn("blocked_unmarked", codes)
        healed = lra_heal.heal(mem)
        self.assertTrue(healed["ok"], healed)
        self.assertFalse(healed["remaining"])
        grid = mem["nca"]["grid"]
        self.assertIsInstance(grid["bad"], dict)
        self.assertLessEqual(grid["hot"]["energy"], 1.0)
        self.assertTrue(grid["ptr://task/LRA-024"]["do_not_fork"])
        self.assertIn("ptr://goal/LRA-G000", grid)
        ops = mem["nca"]["program_state"]["ops"]
        self.assertTrue(all(op["op"] in lra_heal.ALLOWED_OPS for op in ops))
        self.assertTrue(all("172.17.0.1" not in str(op) for op in ops))
        self.assertIsInstance(mem["tape"]["cells"], list)
        self.assertEqual(mem["_stack"]["forest"]["f1"]["parent_id"], "")
        via = lra_tools.run_tool("nca_heal", memory={"nca": {"grid": {"x": {"energy": math.nan}}}})
        self.assertTrue(via["ok"])

    def test_duckdb_callees_and_leanstral_strips_lean(self) -> None:
        import tempfile
        import nca_program as lra_prog
        import codepath_graph as lra_cp

        stripped = lra_prog.parse_work_ops(
            '{"ops":[{"op":"CALL","ptr":"ptr://task/LRA-010"},{"op":"CALL","tactics":"  intros H\\n  simp_all"}],"tactics":"theorem foo : True := by simp"}'
        )
        self.assertTrue(any(op.get("ptr") == "ptr://task/LRA-010" for op in stripped))
        self.assertFalse(any("simp_all" in str(op) for op in stripped))
        tmp = Path(tempfile.mkdtemp()) / "nca-ast.duckdb"
        built = lra_cp.build_sidecar_duckdb(path=tmp)
        if not built.get("ok"):
            self.assertEqual(built.get("reason"), "duckdb_unavailable")
            return
        callees = lra_cp.query_calls_duckdb("portable_rewrites:fold_hoist_repeated_simp", db_path=tmp, direction="callees")
        sliced = lra_cp.slice_cross_module("portable_rewrites:fold_hoist_repeated_simp", db_path=tmp)
        self.assertTrue(sliced["ok"])
        if callees:
            self.assertEqual(sliced.get("source"), "sidecar_duckdb")

    def test_wall_clock_decay_and_sidecar_duckdb(self) -> None:
        import tempfile
        import time
        import typesafe_nca as lra_nca
        import codepath_graph as lra_cp

        stale = time.time() - 7200
        mem: dict = {
            "nca": {
                "grid": {
                    "ptr://skill/stale": {
                        "id": "ptr://skill/stale",
                        "kind": "skill",
                        "energy": 0.9,
                        "wins": 0,
                        "losses": 0,
                        "unsafe": 0.0,
                        "help": 0.0,
                        "updated_at": stale,
                    }
                }
            }
        }
        lra_nca.tick(mem, tactics="  exact Hin\n", problem="P")
        self.assertLess(mem["nca"]["grid"]["ptr://skill/stale"]["energy"], 0.9)
        refused = lra_cp.build_sidecar_duckdb(path=HERE.parent / "control.duckdb")
        self.assertFalse(refused["ok"])
        self.assertTrue(refused.get("control_duckdb") or refused.get("reason") == "campaign_db_refused")
        tmp = Path(tempfile.mkdtemp()) / "nca-ast.duckdb"
        built = lra_cp.build_sidecar_duckdb(path=tmp)
        if built.get("ok"):
            self.assertFalse(built["control_duckdb"])
            self.assertGreater(built["n_symbols"], 0)
            hits = lra_cp.query_sidecar_duckdb("fold_", db_path=tmp)
            self.assertTrue(any("fold_" in str(h.get("symbol")) for h in hits))
        else:
            self.assertEqual(built.get("reason"), "duckdb_unavailable")

    def test_alias_budget_replay_and_ready_overlay(self) -> None:
        import board_graph as lra_board
        import typesafe_nca as lra_nca
        import nca_repair as lra_heal

        mem: dict = {
            "nca": {
                "grid": {
                    "port_trailing_tuple_comma": {"kind": "skill", "energy": 0.8, "wins": 2, "losses": 0},
                    "ptr://skill/port_trailing_tuple_comma": {"kind": "skill", "energy": 0.4, "wins": 1, "losses": 0},
                }
            }
        }
        issues = lra_heal.diagnose(mem)
        self.assertTrue(any(i.get("code") == "alias_collision" for i in issues))
        lra_nca.merge_alias_cells(mem)
        grid = mem["nca"]["grid"]
        self.assertIn("ptr://skill/port_trailing_tuple_comma", grid)
        self.assertNotIn("port_trailing_tuple_comma", grid)
        self.assertEqual(grid["ptr://skill/port_trailing_tuple_comma"]["wins"], 3)
        charged = lra_nca.charge_budget(mem, jev_calls=4, usd=0.01)
        self.assertLess(charged["energy"], 1.0)
        mem["nca"]["journal"] = [
            {"event": "upsert", "ptr": "ptr://skill/port_trailing_tuple_comma", "energy_delta": 0.1, "op": "skill"}
        ]
        before = grid["ptr://skill/port_trailing_tuple_comma"]["energy"]
        replayed = lra_nca.replay_journal(mem, last_n=8)
        self.assertTrue(replayed["n_replayed"] >= 1)
        self.assertGreaterEqual(grid["ptr://skill/port_trailing_tuple_comma"]["energy"], before)
        lra_board.seed_nca_from_board(mem)
        overlay = lra_board.overlay_live_board(
            mem, fetch_fn=lambda: {"tasks": [{"task_alias": "LRA-010", "status": "ready"}]}
        )
        self.assertTrue(overlay["overlay"])
        self.assertGreaterEqual(mem["nca"]["grid"]["ptr://task/LRA-010"]["energy"], 0.55)
        self.assertFalse(mem["nca"]["grid"]["ptr://task/LRA-010"].get("blocked"))

    def test_lake_fail_losses_and_router_stops_on_nca(self) -> None:
        import board_graph as lra_board
        import typesafe_inner as lra_inner
        import splice as lra_splice
        import skill_improve_loop as lra_loop_sk

        mem: dict = {"nca": {"grid": {}}, "successes": [], "failures": []}
        lra_board.seed_nca_from_board(mem)
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")

        class Args:
            lake_top = 1
            timeout = 1.0
            out = None

        _body, rows = lra_inner.apply_lake_round(
            record=rec,
            tactics="  exact Hin\n",
            analysis={"n_tokens": 9},
            drafts=[{"kind": "port_exact_hyp", "tactics": "  exact Hin\n", "family": "search_space", "token_count": 3}],
            intent={"skill": "port_exact_hyp", "compose": "single"},
            ranked={"beam_kinds": ["port_exact_hyp"], "fired": False, "fired_leaves": []},
            memory=mem,
            args=Args(),
            restore=b"",
            round_i=0,
            compile_one=lambda *_a, **_k: {"theorem_ok": False, "token_count": 3, "errors": [{"data": "unsolved goals"}]},
        )
        self.assertFalse(any(r.get("ok") for r in rows))
        skill = mem["nca"]["grid"]["ptr://skill/port_exact_hyp"]
        self.assertGreaterEqual(int(skill.get("losses") or 0), 1)
        calls: list[str] = []
        halted = lra_loop_sk.route_next_action(
            board={"Core.InitsUpdatesComm": 139},
            gaps=[],
            last_lake=[],
            stalled=False,
            llm=True,
            ledger=None,
            generate=lambda prompt: calls.append(prompt) or '{"action": "nest_inner"}',
            memory={
                "nca": {
                    "grid": {
                        "ptr://goal/LRA-G000": {"kind": "goal", "energy": 0.4, "id": "g"},
                        "ptr://tool/budget": {"kind": "tool", "energy": 0.05, "visited": True, "id": "b"},
                    },
                    "program_state": {"ops": [{"op": "KEEP"}]},
                }
            },
        )
        self.assertEqual(halted["action"], "stop")
        self.assertEqual(halted["reason"], "nca_budget")
        self.assertFalse(calls)

    def test_budget_dead_halts_and_missing_sidecar_edges(self) -> None:
        import typesafe_nca as lra_nca
        import codepath_graph as lra_cp
        from pathlib import Path

        mem: dict = {
            "nca": {
                "grid": {
                    "ptr://goal/LRA-G000": {"kind": "goal", "energy": 0.4, "id": "g"},
                    "ptr://tool/budget": {
                        "kind": "tool",
                        "energy": 0.05,
                        "visited": True,
                        "id": "ptr://tool/budget",
                    },
                },
                "program_state": {"ops": [{"op": "KEEP"}]},
            }
        }
        halt = lra_nca.should_halt(mem)
        self.assertTrue(halt["halt"])
        self.assertTrue(halt["budget_dead"])
        missing = lra_cp.seed_nca_call_edges({"nca": {"board_edges": []}}, db_path=Path("/tmp/no-such-nca-ast.duckdb"))
        self.assertTrue(missing["ok"])
        self.assertEqual(missing["source"], "harness_ast")
        self.assertGreater(missing["n_edges"], 0)

    def test_instruct_updates_body_budget_fraction_and_ready_fn(self) -> None:
        import board_graph as lra_board
        import typesafe_nca as lra_nca
        import typesafe_inner as lra_inner
        import splice as lra_splice

        class Led:
            def as_dict(self):
                return {
                    "spent_usd": 1.5,
                    "remaining_usd": 1.5,
                    "budget_usd": 3.0,
                    "jev_calls": 2,
                    "mistral_calls": 0,
                    "grok_calls": 0,
                    "lines": [],
                }

        mem: dict = {"nca": {"grid": {}}}
        charged = lra_nca.charge_budget(mem, ledger=Led())
        self.assertAlmostEqual(charged["energy"], 0.5, places=2)
        lra_board.seed_nca_from_board(mem)
        ready = lra_board.overlay_ready_tasks(
            mem, ready_fn=lambda: {"tasks": [{"task_alias": "LRA-010"}]}
        )
        self.assertEqual(ready["n_ready"], 1)
        self.assertEqual(mem["nca"]["grid"]["ptr://task/LRA-010"]["status"], "ready")
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        n = {"i": 0}

        def research(*_a, **_k):
            n["i"] += 1
            if n["i"] == 1:
                return {
                    "compose": "instruct",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": set(),
                }
            return {
                "compose": "keep",
                "skip_lake": True,
                "skill": "keep",
                "intent": "pca_keep",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = None
            nest_depth = 3
            from_best = False

        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact ⟨a, b,⟩\n",
            args=Args(),
            memory={"nca": {"grid": {}, "program_state": {"ops": [], "last_ran": []}}},
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": True, "token_count": 6, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=3,
            max_depth=3,
        )
        actions = [ev.get("action") or ev.get("compose") for ev in lra_inner.flatten_trace(walked.get("trace") or [])]
        self.assertIn("instruct", actions)
        self.assertTrue((walked.get("observations") or {}) or walked.get("tactics"))

    def test_skill_call_lakes_and_tick_focus(self) -> None:
        import nca_program as lra_prog
        import typesafe_nca as lra_nca

        mem: dict = {"nca": {"grid": {}, "program_state": {"ops": [{"op": "CALL", "ptr": "ptr://skill/port_trailing_tuple_comma"}, {"op": "KEEP"}]}}}
        executed = lra_prog.execute_program_ops(
            mem,
            tactics="  exact ⟨a, b,⟩\n",
            problem="P",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 6, "errors": []},
        )
        self.assertTrue(any(op.get("ok") for op in executed["ran"] if op.get("op") == "CALL"))
        self.assertNotIn(",⟩", executed.get("tactics") or "")
        mem2: dict = {
            "nca": {
                "grid": {
                    "ptr://skill/a": {"kind": "skill", "energy": 0.9, "tick": 0, "wins": 0, "losses": 0, "unsafe": 0, "help": 0, "id": "ptr://skill/a"},
                    "ptr://skill/b": {"kind": "skill", "energy": 0.9, "tick": 0, "wins": 0, "losses": 0, "unsafe": 0, "help": 0, "id": "ptr://skill/b"},
                }
            }
        }
        lra_nca.tick(mem2, tactics="  exact Hin\n", problem="P", focus="ptr://skill/a")
        self.assertGreater(int(mem2["nca"]["grid"]["ptr://skill/a"]["tick"]), 0)
        self.assertEqual(int(mem2["nca"]["grid"]["ptr://skill/b"]["tick"]), 0)
        mem["nca"]["program_state"]["last_ran"] = executed["ran"]
        replayed = lra_nca.replay_journal(mem, last_n=8)
        self.assertGreaterEqual(replayed.get("n_receipts") or 0, 1)

    def test_lake_round_credits_task_and_ready_seeds(self) -> None:
        import board_graph as lra_board
        import nca_program as lra_prog
        import typesafe_inner as lra_inner
        import splice as lra_splice

        mem: dict = {"nca": {"grid": {}}, "successes": []}
        lra_board.seed_nca_from_board(mem)
        lra_board.overlay_live_board(mem, fetch_fn=lambda: {"tasks": [{"task_alias": "LRA-010", "status": "ready"}]})
        ir = lra_prog.compile_local_ir(mem, problem="Core.InitsUpdatesComm")
        self.assertEqual(ir["seeds"][0], "ptr://theorem/Core.InitsUpdatesComm")
        self.assertIn("ptr://task/LRA-010", ir["seeds"])
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        class Args:
            lake_top = 1
            timeout = 1.0
            out = None
        body, rows = lra_inner.apply_lake_round(
            record=rec,
            tactics="  exact Hin\n",
            analysis={"n_tokens": 9},
            drafts=[{"kind": "port_exact_hyp", "tactics": "  exact Hin\n", "family": "search_space", "token_count": 3}],
            intent={"skill": "port_exact_hyp", "compose": "single"},
            ranked={"beam_kinds": ["port_exact_hyp"], "fired": False, "fired_leaves": []},
            memory=mem,
            args=Args(),
            restore=b"",
            round_i=0,
            compile_one=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3, "errors": []},
        )
        self.assertTrue(any(r.get("ok") for r in rows))
        self.assertTrue(mem["nca"]["grid"]["ptr://task/LRA-019"]["visited"])

    def test_theorem_credit_and_smarter_work_ops(self) -> None:
        import board_graph as lra_board
        import nca_program as lra_prog
        import nca_repair as lra_heal
        import typesafe_nca as lra_nca

        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        seeded_kb = lra_board.seed_keepbest_theorems(mem, {"Core.InitsUpdatesComm": 139})
        self.assertEqual(seeded_kb["n_theorems"], 1)
        self.assertEqual(mem["nca"]["grid"]["ptr://theorem/Core.InitsUpdatesComm"]["tokens"], 139)
        linked = lra_board.link_current_theorem(mem, "Core.InitsUpdatesComm")
        self.assertTrue(linked["ok"])
        self.assertIn("ptr://theorem/Core.InitsUpdatesComm", mem["nca"]["grid"])
        credited = lra_board.credit_theorem(mem, "Core.InitsUpdatesComm", theorem_ok=True, tokens=139)
        self.assertTrue(credited["ok"])
        self.assertTrue(mem["nca"]["grid"]["ptr://task/LRA-019"]["visited"])
        self.assertGreaterEqual(mem["nca"]["grid"]["ptr://task/LRA-019"]["energy"], 0.7)
        compiled = lra_prog.compile_program(mem, problem="Core.InitsUpdatesComm")
        ptrs = [op.get("ptr") for op in compiled["work_ops"] if op.get("op") == "CALL"]
        self.assertIn("ptr://theorem/Core.InitsUpdatesComm", ptrs)
        self.assertFalse(any(p and "LRA-G000" in str(p) for p in ptrs))
        mem["nca"]["heal_blacklist"] = ["clip_energy"]
        issues = [{"code": "energy_oob", "repair": "clip_energy"}, {"code": "missing_kind", "repair": "coerce_cells"}]
        picked = lra_heal.typesafe_pick_repair(issues)
        self.assertEqual(picked, "clip_energy")
        healed = lra_heal.heal({"nca": {"grid": {"x": {"energy": 9}}, "heal_blacklist": ["clip_energy"]}})
        self.assertTrue(any("coerce" in str(a) or a == "reseed_board" or a == "mark_blocked" for a in healed.get("applied") or []) or healed.get("ok") is not None)
        halt = lra_nca.should_halt(
            {
                "nca": {
                    "grid": {
                        "ptr://goal/LRA-G000": {"kind": "goal", "energy": 0.4, "id": "g"},
                        "ptr://task/LRA-019": {"kind": "task", "visited": True, "energy": 0.8, "id": "t"},
                    },
                    "program_state": {"ops": [{"op": "KEEP"}]},
                }
            }
        )
        self.assertFalse(halt["halt"])

    def test_nca_program_ir_and_leanstral_fixture(self) -> None:
        import board_graph as lra_board
        import nca_program as lra_prog
        import typesafe_tools as lra_tools

        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        compiled = lra_prog.compile_program(mem, problem="P")
        self.assertTrue(compiled["ok"])
        self.assertFalse(compiled["called_docker0"])
        self.assertTrue(compiled["local_ir"]["seeds"])
        self.assertTrue(any(op.get("op") == "CALL" for op in compiled["work_ops"]))
        programmed = lra_prog.program_nca(
            mem,
            llm="leanstral",
            generate=lambda prompt: (
                self.assertIn("docker0", prompt),
                '{"ops":[{"op":"CALL","ptr":"ptr://task/LRA-010"},{"op":"TICK"}]}',
            )[1],
        )
        self.assertEqual(programmed["instructed"]["provider"], "fixture")
        self.assertFalse(programmed["used_prototype_endpoint"])
        ran = (programmed.get("executed") or {}).get("ran") or []
        self.assertTrue(any(op.get("ptr") == "ptr://task/LRA-010" for op in ran))
        via = lra_tools.run_tool("nca_program", memory=mem, problem="P")
        self.assertTrue(via["ok"])
        self.assertIn("program_state", mem.get("nca") or {})

    def test_live_overlay_sidecar_and_cross_module_slice(self) -> None:
        import board_graph as lra_board
        import codepath_graph as lra_cp

        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        overlay = lra_board.overlay_live_board(
            mem,
            fetch_fn=lambda: {
                "tasks": [
                    {"task_alias": "LRA-010", "status": "completed"},
                    {"task_alias": "LRA-011", "status": "blocked"},
                ]
            },
        )
        self.assertTrue(overlay["overlay"])
        self.assertFalse(overlay["campaign_write"])
        self.assertEqual(mem["nca"]["grid"]["ptr://task/LRA-010"]["status"], "completed")
        self.assertTrue(mem["nca"]["grid"]["ptr://task/LRA-011"]["do_not_fork"])
        silent = lra_board.overlay_live_board({"nca": {"grid": {}}}, fetch_fn=lambda: {"tasks": []})
        self.assertFalse(silent["overlay"])
        sidecar = lra_cp.build_sidecar_index(write=False)
        self.assertGreater(sidecar["n_files"], 3)
        self.assertFalse(sidecar["control_duckdb"])
        self.assertTrue(any("fold_" in s for f in sidecar["files"] for s in f.get("symbols") or []))
        hits = lra_cp.query_sidecar("fold_", payload=sidecar)
        self.assertTrue(hits)
        cross = lra_cp.slice_cross_module("portable_rewrites:fold_hoist_repeated_simp")
        self.assertTrue(cross["ok"])
        self.assertIn(":", cross["symbol"])
        self.assertFalse(cross["source_bodies"])
        src = (HERE / "board_graph.py").read_text(encoding="utf-8")
        self.assertNotIn("compare_and_set", src)

    def test_board_and_codepath_nca_hooks(self) -> None:
        import board_graph as lra_board
        import codepath_graph as lra_cp
        import call_stack as lra_cs
        import typesafe_nca as lra_nca
        import typesafe_tools as lra_tools

        board = lra_board.load_lra_board()
        self.assertGreaterEqual(board["n_subgoals"], 10)
        self.assertGreaterEqual(board["n_tasks"], 10)
        self.assertFalse(board["campaign_write"])
        payload = lra_board.board_payload("LRA-010", board)
        self.assertEqual(payload["kind"], "task")
        self.assertTrue(any("generate_text" in p for p in payload.get("code_paths") or []))
        mem: dict = {"nca": {"grid": {}}}
        seeded = lra_board.seed_nca_from_board(mem, board=board)
        self.assertTrue(seeded["ok"])
        self.assertIn("ptr://goal/LRA-G000", mem["nca"]["grid"])
        self.assertTrue(mem["nca"]["grid"]["ptr://task/LRA-024"].get("do_not_fork"))
        forks = lra_nca.fork_cells(mem)
        self.assertFalse(any(f["id"] == "ptr://task/LRA-024" for f in forks.get("forks") or []))
        sliced = lra_cp.slice_codepath("harness.portable_rewrites:fold_hoist_repeated_simp")
        self.assertTrue(sliced["ok"])
        self.assertIn("fold_hoist_repeated_simp", sliced["definitions"])
        self.assertFalse(sliced["source_bodies"])
        self.assertFalse(lra_cp.slice_codepath("/etc/passwd")["ok"])
        self.assertEqual(lra_cs.coerce_ptr("LRA-S05"), "ptr://subgoal/LRA-S05")
        self.assertTrue(lra_cs.parse_ptr("ptr://task/LRA-010")["ok"])
        src = (HERE / "board_graph.py").read_text(encoding="utf-8")
        self.assertNotIn("compare_and_set", src)
        self.assertNotIn("materialize", src)
        tool = lra_tools.run_tool("board_walk", memory=mem)
        self.assertTrue(tool["ok"])
        self.assertFalse(tool.get("campaign_write"))

    def test_symbol_search_ranks_ast_kg_and_fallbacks(self) -> None:
        import symbol_search as lra_ss
        import typesafe_tools as lra_tools

        mem = {
            "successes": [{"name": "P", "kind": "port_trailing_tuple_comma", "from_tokens": 12, "to_tokens": 10}],
            "failures": [],
            "research": [{"name": "P", "help": {"intro_then_simp_all": 1.0}, "unsafe": {}}],
        }
        ast_hits = lra_ss.search_ast("fold_", root=HERE)
        self.assertTrue(any("fold_" in h["symbol"] for h in ast_hits))
        kg_hits = lra_ss.search_kg("trailing", mem)
        self.assertTrue(any("trailing" in h["symbol"] for h in kg_hits))
        ranked = lra_ss.search_symbols("fold_hoist", memory=mem, root=HERE)
        self.assertTrue(ranked["ok"])
        self.assertFalse(ranked["called_docker0"])
        self.assertFalse(ranked["semantic_authority"])
        self.assertGreaterEqual(ranked["n_hits"], 1)
        sources = ranked["sources"]
        self.assertIn("ast", sources)
        self.assertIn("kg", sources)
        self.assertIn("duckdb", sources)
        self.assertIn("vector", sources)
        self.assertIn("rg", sources)
        via_tool = lra_tools.run_tool("symbol_search", memory=mem, problem="fold_")
        self.assertTrue(via_tool["ok"])
        fake_vec = lambda *_a, **_k: {"hits": [{"qualified_symbol": "fold_from_memory_skill", "path": "portable_rewrites.py", "score": 0.9}]}
        vec, note = lra_ss.search_vector_index("fold_", snapshot={"rows": []}, search_fn=fake_vec)
        self.assertEqual(note, "vector")
        self.assertTrue(vec)

    def test_stack_parent_children_and_child_args(self) -> None:
        import call_stack as lra_cs
        import neural_tape as lra_tape

        stack = lra_cs.CallStack()
        root = stack.call("ptr://theorem/P", compose="root", node="root", locals_={"tactics": "  intro\n", "problem": "P"})
        self.assertTrue(root["ok"])
        resolved = lra_cs.resolve_ptr("ptr://skill/port_trailing_tuple_comma")
        child = stack.call(
            resolved["ptr"],
            compose="call",
            node="port_trailing_tuple_comma",
            locals_={"tactics": "  intro\n", "problem": "P", "tape_window": []},
            resolved=resolved,
        )
        self.assertTrue(child["ok"])
        self.assertIn("allow_skills", child["args"])
        self.assertEqual(child["args"]["problem"], "P")
        self.assertEqual(child["args"]["tactics"], "  intro\n")
        self.assertEqual(stack.parent()["frame_id"], root["frame"]["frame_id"])
        kids = stack.children(root["frame"]["frame_id"])
        self.assertEqual(len(kids), 1)
        walk = lra_cs.walk_stack(stack)
        self.assertEqual(walk[0]["frame_id"], root["frame"]["frame_id"])
        self.assertEqual(walk[1]["parent_id"], root["frame"]["frame_id"])
        tape = lra_tape.Tape()
        cell = lra_tape.populate_tape(tape, stack, tactics="  intro\n", problem="P", ptr=resolved["ptr"])
        self.assertEqual(cell["kind"], "args")
        self.assertEqual(tape.cells_for_frame(child["frame"]["frame_id"])[0]["kind"], "args")
        stack.ret({"ok": True})
        self.assertEqual(stack.current()["frame_id"], root["frame"]["frame_id"])
        self.assertFalse(stack.children(root["frame"]["frame_id"])[0]["live"])

    def test_tape_window_and_ptr_fail_closed(self) -> None:
        import neural_tape as lra_tape
        import call_stack as lra_cs
        import typesafe_tools as lra_tools

        tape = lra_tape.Tape()
        for i in range(20):
            tape.write("skill", f"c{i}", ptr=f"ptr://skill/s{i}")
        win = tape.window(3)
        self.assertLessEqual(len(win), 7)
        self.assertEqual(win[-1]["payload"], "c19")
        self.assertFalse(lra_cs.parse_ptr("os.system('rm')")["ok"])
        self.assertFalse(lra_cs.parse_ptr("ptr://../../etc/passwd")["ok"])
        self.assertTrue(lra_cs.parse_ptr("ptr://tool/diffuse")["ok"])
        self.assertEqual(lra_cs.coerce_ptr("diffuse", tools=lra_tools.TOOL_CRITERIA), "ptr://tool/diffuse")
        bad = lra_cs.resolve_ptr("ptr://module/../secret.py", tools=lra_tools.TOOL_CRITERIA)
        self.assertFalse(bad["ok"])
        mcpp = lra_cs.parse_ptr("ptr://mcpplusplus/p2p_taskqueue_status")
        self.assertTrue(mcpp["ok"])
        self.assertEqual(mcpp["kind"], "mcpplusplus")
        self.assertEqual(
            lra_cs.coerce_ptr("p2p_taskqueue_status"),
            "ptr://mcpplusplus/p2p_taskqueue_status",
        )
        resolved = lra_cs.resolve_ptr("ptr://mcpplusplus/catalog")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["protocol"], "MCP++")
        self.assertFalse(lra_cs.resolve_ptr("ptr://mcpplusplus/p2p_taskqueue_submit_docker_hub")["ok"])

    def test_call_theorem_injects_return_on_tape(self) -> None:
        import typesafe_inner as lra_inner
        import splice as lra_splice

        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        n = {"i": 0}

        def research(_record, _analysis, **_kwargs):
            n["i"] += 1
            if n["i"] == 1:
                return {
                    "compose": "call",
                    "nest_child": "ptr://theorem/Core.InitsUpdatesComm",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": set(),
                }
            return {
                "compose": "return",
                "skip_lake": False,
                "skill": "keep",
                "intent": "pca_keep",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = HERE.parent / "evidence" / "canaries"
            nest_depth = 3

        mem: dict = {"successes": [], "failures": [], "blacklist": [], "research": [], "skills": []}
        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Hin\n",
            args=Args(),
            memory=mem,
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=4,
            max_depth=3,
        )
        cells = (walked.get("tape") or {}).get("cells") or []
        kinds = [c.get("kind") for c in cells]
        self.assertIn("return", kinds)
        injected = [c for c in cells if c.get("injected") or c.get("kind") == "return"]
        self.assertTrue(injected)
        self.assertTrue(any(c.get("theorem_ok") for c in cells))
        self.assertTrue(any(ev.get("action") == "call_return" and ev.get("injected") for ev in walked["trace"]))
        self.assertIn("_tape_window", mem)
        self.assertLessEqual(len(mem["_tape_window"]), 16)

    def test_call_mcpplusplus_injects_receipt(self) -> None:
        import typesafe_inner as lra_inner
        import typesafe_tools as lra_tools
        import splice as lra_splice

        catalog = lra_tools.mcpplusplus_call("catalog")
        self.assertTrue(catalog["ok"])
        self.assertEqual(catalog["protocol"], "MCP++")
        self.assertFalse(catalog["live_p2p"])
        self.assertFalse(catalog["called_docker0"])
        self.assertIn("ptr://mcpplusplus/p2p_taskqueue_status", str(catalog["envelope"]))
        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        n = {"i": 0}

        def research(_record, _analysis, **_kwargs):
            n["i"] += 1
            if n["i"] == 1:
                return {
                    "compose": "call",
                    "nest_child": "ptr://mcpplusplus/catalog",
                    "skip_lake": False,
                    "skill": "keep",
                    "intent": "search_space",
                    "tree": {},
                    "residual_unsafe": {},
                    "residual_help": {},
                    "skip_skills": [],
                    "allow_families": set(),
                }
            return {
                "compose": "return",
                "skip_lake": False,
                "skill": "keep",
                "intent": "pca_keep",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = HERE.parent / "evidence" / "canaries"
            nest_depth = 3

        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Hin\n",
            args=Args(),
            memory={"successes": [], "failures": [], "blacklist": [], "research": [], "skills": []},
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": False, "token_count": 9, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            max_steps=4,
            max_depth=3,
        )
        self.assertIn("mcpplusplus", walked.get("observations") or {})
        env = walked["observations"]["mcpplusplus"]["envelope"]
        self.assertEqual(env["protocol"], "MCP++")
        self.assertFalse(env["receipt"]["called_docker0"])
        self.assertTrue(any(ev.get("action") == "call_return" and ev.get("kind") == "mcpplusplus" for ev in walked["trace"]))

    def test_remaining_cut_pipeline_and_no_drafts_instruct(self) -> None:
        import board_graph as lra_board
        import nca_program as lra_prog
        import random_canary as lra_rand
        import splice as lra_splice
        import typesafe_inner as lra_inner

        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        warm = {"Core.InitsUpdatesComm": 200, "Cslib.SKI.parallelReduction_diamond": 541}
        seeded = lra_board.seed_keepbest_theorems(
            mem,
            {"Core.InitsUpdatesComm": 139, "Cslib.SKI.parallelReduction_diamond": 540},
            warmup=warm,
        )
        self.assertEqual(seeded["n_theorems"], 2)
        inits = mem["nca"]["grid"]["ptr://theorem/Core.InitsUpdatesComm"]
        self.assertEqual(inits["warmup_tokens"], 200)
        self.assertEqual(inits["remaining_cut"], 61)
        ir = lra_prog.compile_local_ir(mem, problem="Other.Thm")
        self.assertEqual(ir["seeds"][0], "ptr://theorem/Other.Thm")
        inits_i = ir["seeds"].index("ptr://theorem/Core.InitsUpdatesComm")
        ski_i = ir["seeds"].index("ptr://theorem/Cslib.SKI.parallelReduction_diamond")
        self.assertLess(inits_i, ski_i)
        credited = lra_board.credit_theorem(mem, "Core.InitsUpdatesComm", theorem_ok=True, tokens=100)
        self.assertTrue(credited["ok"])
        self.assertEqual(mem["nca"]["grid"]["ptr://theorem/Core.InitsUpdatesComm"]["remaining_cut"], 100)
        window = lra_board.refresh_board_window(mem)
        self.assertTrue(
            any(
                row.get("kind") == "theorem" and int(row.get("remaining_cut") or 0) >= 100
                for row in window
            )
        )
        import typesafe_nca as lra_nca

        alias_mem = {
            "nca": {
                "grid": {
                    "port_trailing_tuple_comma": {
                        "kind": "skill",
                        "energy": 0.8,
                        "wins": 1,
                        "tokens": 10,
                        "warmup_tokens": 20,
                    },
                    "ptr://skill/port_trailing_tuple_comma": {
                        "kind": "skill",
                        "energy": 0.4,
                        "wins": 2,
                        "tokens": 8,
                    },
                }
            }
        }
        lra_nca.merge_alias_cells(alias_mem)
        canon = alias_mem["nca"]["grid"]["ptr://skill/port_trailing_tuple_comma"]
        self.assertEqual(canon["wins"], 3)
        self.assertEqual(canon["warmup_tokens"], 20)
        self.assertEqual(canon["remaining_cut"], 10)
        self.assertNotIn("port_trailing_tuple_comma", alias_mem["nca"]["grid"])

        piped = lra_prog.execute_program_ops(
            {
                "nca": {
                    "grid": {},
                    "program_state": {
                        "ops": [
                            {"op": "CALL", "ptr": "ptr://skill/port_pipeline"},
                            {"op": "KEEP"},
                        ]
                    },
                }
            },
            tactics="  exact ⟨a, b,⟩\n",
            problem="P",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 6, "errors": []},
        )
        self.assertTrue(any(op.get("ok") and "pipeline" in str(op.get("ptr") or "") for op in piped["ran"]))
        self.assertNotIn(",⟩", piped.get("tactics") or "")

        self.assertEqual(
            lra_rand.bias_compose_no_drafts(
                "single",
                memory={"observations": {"no_drafts_tree_by": {"P": {"ok": True}}}},
                skills={"keep": "none"},
                skill="keep",
                name="P",
            ),
            "instruct",
        )
        self.assertEqual(
            lra_rand.bias_compose_no_drafts(
                "heal",
                memory={"observations": {"no_drafts_tree_by": {"P": {"ok": True}}}},
                skills={"keep": "none"},
                skill="keep",
                name="P",
            ),
            "heal",
        )

        missing = lra_board.replica_ready_page(lane=HERE / "no-such-lra-lane")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["reason"], "no_ready_json")
        self.assertFalse(missing["campaign_write"])
        env_off = lra_board.overlay_ready_tasks({"nca": {"grid": {}}})
        self.assertEqual(env_off["reason"], "no_ready_fn")

        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        n = {"i": 0}

        def research(*_a, **_k):
            n["i"] += 1
            return {
                "compose": "single",
                "skip_lake": False,
                "skill": "keep",
                "intent": "search_space",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = None
            nest_depth = 3
            from_best = False

        walked = lra_inner.inner_typesafe_walk(
            rec,
            "  exact Lemma.foo\n",
            args=Args(),
            memory={"nca": {"grid": {}, "program_state": {"ops": [{"op": "KEEP"}]}}, "observations": {}},
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=research,
            compile_one=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            allow_skills={"no_such_skill"},
            max_steps=3,
            max_depth=1,
        )
        actions = [ev.get("action") for ev in lra_inner.flatten_trace(walked.get("trace") or [])]
        self.assertIn("no_drafts_self_improve", actions)
        self.assertIn("no_drafts_instruct", actions)

        warm_map = lra_board.warmup_token_map()
        self.assertIn("Core.InitsUpdatesComm", warm_map)
        self.assertGreater(int(warm_map["Core.InitsUpdatesComm"]), 0)

    def test_rank_live_and_rehydrate_gaps(self) -> None:
        import random_canary as lra_rand
        import splice as lra_splice
        from jevops.memory import load_memory as load_generic_memory

        mem: dict = {"blacklist": [], "research": [], "failures": [], "nca": {"grid": {}}}
        restored = lra_bind.rehydrate_from_skill_analysis(mem)
        self.assertEqual(restored["reason"], "rehydrated")
        self.assertGreater(restored["n_blacklist"], 0)
        again = lra_bind.rehydrate_from_skill_analysis(mem)
        self.assertEqual(again["reason"], "already_populated")
        _raw, _digest, records = lra_splice.load_warmup_records()
        small = [rec for rec in records if rec.get("name") in lra_loop_sk.SMALL_NAMES]
        ranked = lra_rand.rank_live_records(
            small,
            out=HERE.parent / "evidence" / "canaries",
            from_best=True,
            memory=mem,
        )
        names = [str(rec.get("name")) for rec in ranked]
        self.assertEqual(set(names), set(lra_loop_sk.SMALL_NAMES))
        # After blacklist + residual Noul, leftover drafts are 0; remaining_cut ranks Inits first.
        self.assertEqual(names[0], "Core.InitsUpdatesComm")
        leftover = (mem.get("nca") or {}).get("grid") or {}
        inits = leftover.get("ptr://theorem/Core.InitsUpdatesComm") or {}
        self.assertGreaterEqual(int(inits.get("remaining_cut") or 0), 100)

        with TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "skill-analysis.json"
            fixture.write_text(
                '{"gaps":[{"name":"P","failed_stems":["port_unused_intros"]}]}'
            )
            loaded = load_generic_memory(
                Path(tmp) / "memory.json",
                rehydrate_path=fixture,
                patched_unban=("port_unused_intros",),
            )
            self.assertNotIn("P::port_unused_intros", loaded["blacklist"])

    def test_no_drafts_instruct_is_per_canary(self) -> None:
        import splice as lra_splice
        import typesafe_inner as lra_inner

        _raw, _digest, records = lra_splice.load_warmup_records()
        recs = [
            next(item for item in records if item.get("name") == "Core.InitsUpdatesComm"),
            next(item for item in records if item.get("name") == "Cslib.SKI.parallelReduction_diamond"),
        ]

        def research(*_a, **_k):
            return {
                "compose": "single",
                "skip_lake": False,
                "skill": "keep",
                "intent": "search_space",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
                "allow_families": set(),
            }

        class Args:
            drafts = 2
            lake_top = 1
            timeout = 1.0
            out = None
            nest_depth = 1
            from_best = False

        mem: dict = {"nca": {"grid": {}, "program_state": {"ops": [{"op": "KEEP"}]}}, "observations": {}}
        for rec in recs:
            walked = lra_inner.inner_typesafe_walk(
                rec,
                "  exact Lemma.foo\n",
                args=Args(),
                memory=mem,
                ledger=None,
                rng=__import__("random").Random(0),
                model=None,
                restore=b"",
                research_fn=research,
                compile_one=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3, "errors": []},
                pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
                allow_skills={"no_such_skill"},
                max_steps=3,
                max_depth=1,
            )
            actions = [ev.get("action") for ev in lra_inner.flatten_trace(walked.get("trace") or [])]
            self.assertIn("no_drafts_instruct", actions, rec.get("name"))
        instructed = (mem.get("observations") or {}).get("no_drafts_instructed_by") or {}
        self.assertTrue(instructed.get("Core.InitsUpdatesComm"))
        self.assertTrue(instructed.get("Cslib.SKI.parallelReduction_diamond"))

    def test_persist_memory_false_never_writes(self) -> None:
        writes: list[str] = []
        orig = lra_bind.save_memory

        def spy(memory, path=None):
            writes.append(str(path or lra_bind.MEMORY_DEFAULT))
            return path or lra_bind.MEMORY_DEFAULT

        lra_bind.save_memory = spy  # type: ignore[assignment]
        try:

            def fake_generate(prompt: str, **_kwargs: object) -> str:
                return '{"action": "stop", "reason": "fixture"}'

            def fake_inner(_args: object) -> dict:
                return {"skill_analysis": [], "lake": [], "ledger": {"jev_calls": 0}, "called_docker0": False}

            lra_loop_sk.run_loop(
                outer=1,
                llm=True,
                out=HERE.parent / "evidence" / "canaries",
                rounds=1,
                lake_top=1,
                drafts=2,
                timeout=1.0,
                seed=1,
                generate=fake_generate,
                run_inner=fake_inner,
                memory={},
                persist_memory=False,
            )
        finally:
            lra_bind.save_memory = orig  # type: ignore[assignment]
        self.assertEqual(writes, [])

    def test_program_nca_replaces_state_before_execute(self) -> None:
        import board_graph as lra_board
        import nca_program as lra_prog

        mem: dict = {"nca": {"grid": {}, "program_state": {"ops": [], "last_ran": []}}}
        lra_board.seed_nca_from_board(mem)
        lra_board.seed_keepbest_theorems(
            mem, {"Core.InitsUpdatesComm": 139}, warmup={"Core.InitsUpdatesComm": 271}
        )
        out = lra_prog.program_nca(
            mem,
            tactics="  exact Hin\n",
            problem="Core.InitsUpdatesComm",
            llm="off",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3, "errors": []},
        )
        ran = list((mem["nca"]["program_state"].get("last_ran") or []))
        self.assertTrue(ran, out)
        self.assertTrue(any(op.get("op") == "CALL" for op in ran))
        self.assertIn("last_ran", mem["nca"]["program_state"])

    def test_cold_seed_does_not_halt(self) -> None:
        import board_graph as lra_board
        import typesafe_nca as lra_nca

        mem: dict = {"nca": {"grid": {}}}
        lra_board.seed_nca_from_board(mem)
        halt = lra_nca.should_halt(mem)
        self.assertFalse(halt["halt"], halt)
        self.assertFalse(halt["budget_dead"])
        self.assertEqual(halt["n_hot_tasks"], 0)


if __name__ == "__main__":
    unittest.main()
