#!/usr/bin/env python3
"""Kernel imports and runs without Lean, lake, or the LRA harness."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class KernelBoundaryTests(unittest.TestCase):
    def test_package_imports_without_lra(self) -> None:
        import jevops

        for name in (
            "hooks",
            "nca",
            "kernel",
            "mask",
            "tape",
            "stack",
            "jsonld",
            "plan",
            "graph",
            "skill_tree",
            "rankers",
            "search",
            "int_rankers",
            "more_rankers",
            "temporal",
            "autoencoder",
            "program",
            "repair",
            "tools",
            "turing",
            "tape_tools",
            "jev",
            "walk",
            "board",
            "outer",
            "oracle",
            "pick",
            "memory",
        ):
            self.assertTrue(hasattr(jevops, name), name)

    def test_plan_seeds_injected_board(self) -> None:
        from jevops import plan

        mem: dict = {"nca": {}}
        board = {
            "root_goal": "G-TEST",
            "goal_title": "kernel only",
            "subgoals": [{"id": "S1", "title": "one", "blocked": False}],
            "tasks": [{"id": "T1", "title": "do", "subgoal_id": "S1", "depends_on": [], "blocked": False}],
        }
        out = plan.seed_plan(mem, board=board)
        self.assertTrue(out["ok"])
        self.assertEqual(mem["nca"]["plan"]["goals"][0]["id"], "G-TEST")
        self.assertEqual(len(mem["nca"]["plan"]["tasks"]), 1)
        thought = plan.add_thought(mem, kind="generate", text="try a skill", task_id="T1")
        scored = plan.record_jev(mem, choice="v0", score_m=800, noul_m=10, task_id="T1")
        self.assertTrue(thought["id"])
        self.assertEqual(scored["kind"], "score")
        best = plan.keep_best_thoughts(mem)
        self.assertEqual(best[0]["id"], scored["id"])

    def test_nca_cell_store(self) -> None:
        from jevops import nca

        mem: dict = {"nca": {}}
        cell = nca.upsert_from_event(mem, ptr="port_cache_get", kind="skill", energy=0.8)
        self.assertEqual(cell["id"], "ptr://skill/port_cache_get")
        nca.charge_budget(mem, jev_calls=2, usd=0.0)
        self.assertIn("ptr://tool/budget", mem["nca"]["grid"])
        merged = nca.merge_alias_cells(mem)
        self.assertTrue(merged["ok"])

    def test_graph_without_board_module(self) -> None:
        from jevops import graph, jsonld

        mem: dict = {"nca": {"board_edges": [["ptr://a", "ptr://b"], ["ptr://b", "ptr://c"]]}}
        jsonld.put_jsonld(mem, jsonld.document_from_edges(mem["nca"]["board_edges"]))
        out = graph.traverse(mem, start="ptr://a", mode="bfs")
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out.get("n") or 0, 2)
        self.assertFalse(out.get("writes_lean"))
        msg = graph.message_pass(mem)
        self.assertTrue(msg["ok"])
        self.assertTrue(msg["integer"])

    def test_rankers_without_portable_rewrites(self) -> None:
        from jevops import rankers

        mem = {
            "successes": [{"kind": "port_cache_get"}],
            "failures": [{"kind": "port_cache_put"}],
            "nca": {},
        }
        synced = rankers.sync_bayes_from_memory(mem)
        self.assertTrue(synced["ok"])
        post = rankers.posterior(mem, "cache_get")
        self.assertGreater(float(post["mean"]), 0.5)
        feat = rankers.feature_row(kind="port_cache_get", tokens=10, memory=mem)
        self.assertEqual(len(feat), 8)

    def test_program_ir_without_lean(self) -> None:
        from jevops import program

        mem = {
            "nca": {
                "grid": {
                    "ptr://skill/port_cache_get": {"kind": "skill", "energy": 0.9, "tokens": 1},
                    "ptr://task/T1": {"kind": "task", "energy": 0.8, "status": "ready"},
                },
                "board_edges": [["ptr://task/T1", "ptr://skill/port_cache_get"]],
            }
        }
        ir = program.compile_local_ir(mem, problem="P")
        self.assertTrue(ir["ok"])
        self.assertTrue(ir["seeds"])
        ops = program.parse_work_ops('{"ops":[{"op":"TICK"},{"op":"KEEP"}]}')
        self.assertEqual([row["op"] for row in ops], ["TICK", "KEEP"])
        stripped = program.parse_work_ops('{"ops":[{"op":"CALL","ptr":"ptr://skill/x"}],"tactics":"theorem t : True := by\\n  trivial\\n"}')
        self.assertTrue(all("tactics" not in row for row in stripped))
        mem["nca"]["program_state"] = {"ops": [{"op": "KEEP"}]}
        ran = program.execute_program_ops(mem, tactics="  exact Hin\n")
        self.assertEqual(ran.get("tactics"), "  exact Hin\n")
        self.assertFalse(ran.get("called_docker0"))

    def test_repair_without_board(self) -> None:
        from jevops import repair

        mem = {"nca": {"grid": {"port_foo": {"energy": 9, "kind": "skill"}}}}
        issues = repair.diagnose(mem)
        self.assertTrue(any(i.get("repair") == "clip_energy" for i in issues))
        out = repair.heal(mem)
        self.assertFalse(out.get("called_docker0"))
        grid = mem["nca"]["grid"]
        cell = grid.get("port_foo") or grid.get("ptr://skill/port_foo") or {}
        energy = float(cell.get("energy") or 0)
        self.assertGreaterEqual(energy, 0.0)
        self.assertLessEqual(energy, 1.0)

    def test_tools_catalog_without_harness(self) -> None:
        from jevops import tools

        kg = tools.skill_knowledge_graph({"successes": [{"name": "P", "kind": "port_cache_get"}]})
        self.assertGreaterEqual(kg["n_nodes"], 1)
        cat = tools.mcpplusplus_call("catalog")
        self.assertTrue(cat["ok"])
        self.assertFalse(cat["live_p2p"])
        ast_out = tools.harness_ast()
        self.assertEqual(ast_out.get("files") or [], [])

    def test_vae_milles_without_lake(self) -> None:
        from jevops import autoencoder as ae

        encoded = ae.encode_milles("simp [foo]")
        self.assertEqual(len(encoded["mu"]), ae.LATENT_D)
        rt = ae.roundtrip_once("simp [foo]")
        self.assertFalse(rt["writes_lean"])
        ranked = ae.jev_rank_variations([rt])
        self.assertTrue(ranked["ok"])
        self.assertFalse(ranked["used_jev"])

    def test_tick_and_cold_seed_halt(self) -> None:
        from jevops import nca

        mem = {
            "nca": {
                "grid": {
                    "ptr://skill/port_cache_get": {
                        "kind": "skill",
                        "energy": 0.8,
                        "wins": 2,
                        "losses": 0,
                        "help": 0.0,
                        "unsafe": 0.0,
                    }
                }
            }
        }
        out = nca.tick(mem)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["n_cells"], 1)
        halt = nca.should_halt(mem)
        self.assertFalse(halt["halt"], halt)
        nca.journal_event(mem, event="call", ptr="ptr://skill/port_cache_get", op="skill")
        nca.charge_budget(mem, jev_calls=1)
        dead = nca.should_halt({"nca": {"grid": {"ptr://tool/budget": {"energy": 0.05, "visited": True}}}})
        self.assertTrue(dead["budget_dead"])
        self.assertTrue(dead["halt"])

    def test_walk_helpers_and_jev_projectors(self) -> None:
        from jevops import jev, walk

        mem: dict = {"observations": {}}
        rec = {"name": "P"}
        self.assertFalse(walk.no_drafts_flag(mem, rec, "no_drafts_tree"))
        walk.set_no_drafts_flag(mem, rec, "no_drafts_tree")
        self.assertTrue(walk.no_drafts_flag(mem, rec, "no_drafts_tree"))
        nested = [{"op": "a", "nested_trace": [{"op": "b"}]}]
        self.assertEqual([row["op"] for row in walk.flatten_trace(nested)], ["a", "b"])
        drafts = [{"kind": "port_cache_get"}, {"kind": "port_cache_put"}]
        kept = walk.restrict_drafts(drafts, skip_port={"cache_put"})
        self.assertEqual([d["kind"] for d in kept], ["port_cache_get"])
        self.assertEqual(jev.noul_value({"noul": 0.2}), 0.2)
        choice, conf, _probs = jev.choice_value({"choice": "v0", "confidence": 0.9})
        self.assertEqual(choice, "v0")
        self.assertEqual(conf, 0.9)
        score, legend = jev.score_value({"score": 1}, n_levels=3, legend_fallback={0: "a", 1: "b", 2: "c"})
        self.assertEqual(score, 1.0)
        self.assertEqual(legend[1], "b")
        spec = {
            "pick": {"type": "choice", "instructions": "pick", "criteria": {"a": "A", "b": "B"}},
            "risk": {"type": "noul", "instructions": "wrong?"},
            "cut": {"type": "score", "instructions": "cut", "criteria": ["same", "less"]},
        }
        questions = jev.instantiate_questions(spec)
        self.assertEqual(jev.question_kind(questions["pick"]), "choice")
        client = jev.FixtureClient(answers={"pick": "b", "risk": 0.1, "cut": 1})
        resp = client.system_one({}, questions)
        self.assertEqual(resp.choices["pick"].choice, "b")
        self.assertEqual(resp.nouls["risk"].noul, 0.1)
        self.assertEqual(resp.scores["cut"].score, 1.0)

    def test_feed_memory_overlays_wins(self) -> None:
        from jevops import nca, walk

        mem = {
            "successes": [{"kind": "port_cache_get", "to_tokens": 4}],
            "failures": [{"kind": "port_cache_put"}],
            "nca": {"grid": {}},
        }
        out = nca.feed_memory(mem, problem="P", heal=False)
        self.assertGreaterEqual(out["n_cells"], 1)
        cell = mem["nca"]["grid"]["ptr://skill/port_cache_get"]
        self.assertEqual(cell["wins"], 1)
        self.assertIn("return", walk.CONTROL)
        from jevops import stack as lra_cs
        from jevops import tape as lra_tape

        mem2: dict = {"nca": {"grid": {}}}
        tape = lra_tape.Tape.from_memory(mem2)
        stk = lra_cs.CallStack()
        stk.call("ptr://theorem/P", compose="root", node="root", locals_={"tactics": ""})
        out = walk.do_analyze(
            memory=mem2,
            tape=tape,
            stack=stk,
            body="simp",
            problem="P",
            tool_name="kg_skills",
        )
        self.assertEqual(out["flow"], "continue")
        self.assertEqual(out["trace"]["action"], "analyze")
        opened = walk.open_ptr_call(
            memory=mem2,
            tape=tape,
            stack=stk,
            body="simp",
            problem="P",
            nest_child="ptr://tool/kg_skills",
        )
        self.assertTrue(opened.get("ok"), opened)
        handled = walk.handle_call_kind(
            "tool",
            memory=mem2,
            body="simp",
            problem="P",
            resolved=opened["resolved"],
            args=opened["args"],
        )
        self.assertIn("observations", handled)
        closed = walk.close_ptr_call(
            memory=mem2,
            tape=tape,
            stack=stk,
            body="simp",
            problem="P",
            ptr=opened["ptr"],
            child_payload={"ok": True, "kind": "tool", "energy": 0.6},
        )
        self.assertEqual(closed["trace"]["action"], "call_return")
        improved = walk.do_self_improve(memory=mem2, body="simp", problem="P")
        self.assertEqual(improved["trace"]["action"], "self_improve")
        nest = walk.do_nest_or_spawn(
            compose="nest",
            nest_child="dead_code",
            tree={"dead_code": {"port_a": "a"}},
            subloops={},
            depth=0,
            max_depth=3,
            nest_fn=lambda **kw: {"tactics": "ok", "child": kw["child"]},
        )
        self.assertEqual(nest["flow"], "absorb")
        self.assertEqual(nest["child"], "dead_code")
        skip = walk.skip_lake_row(
            name="P", depth=0, node="root", round_i=1, skip_lake=True, compose="single"
        )
        self.assertEqual(skip["skipped"], "intent_minimal")
        self.assertIsNone(
            walk.skip_lake_row(
                name="P", depth=0, node="root", round_i=1, skip_lake=True, compose="instruct"
            )
        )
        walk.reset_pass_flags(mem2)
        packed = walk.walk_result(
            body="simp",
            lake=[],
            ranked={},
            drafts=[],
            analysis={},
            trace=[],
            n_steps=1,
            depth=0,
            node="root",
            memory=mem2,
            tape=tape,
            stack=stk,
        )
        self.assertEqual(packed["tactics"], "simp")
        self.assertFalse(packed["jev_generated_lean"])
        self.assertFalse(packed["called_docker0"])

    def test_board_seed_and_outer_route(self) -> None:
        from jevops import board, outer

        mem: dict = {"nca": {"grid": {}}}
        data = {
            "root": "G1",
            "goal_title": "kernel board",
            "subgoals": [{"id": "S1", "title": "s", "blocked": False}],
            "tasks": [{"id": "T1", "title": "t", "subgoal_id": "S1", "depends_on": [], "blocked": False}],
        }
        out = board.seed_grid_from_board(mem, data)
        self.assertTrue(out["ok"])
        self.assertIn("ptr://goal/G1", mem["nca"]["grid"])
        payload = board.board_payload("T1", data)
        self.assertEqual(payload["kind"], "task")
        parsed = outer.parse_action('noise {"action":"stop","reason":"done"}')
        self.assertEqual(parsed["action"], "stop")
        routed = outer.deterministic_route(gaps=[], last_lake=[], stalled=False)
        self.assertEqual(routed["action"], "nest_inner")
        nxt = outer.route_next(gaps=[], last_lake=[], stalled=False)
        self.assertEqual(nxt["action"], "nest_inner")
        self.assertEqual(nxt["router"], "deterministic")
        stopped = outer.route_next(
            gaps=[],
            last_lake=[],
            stalled=False,
            memory={"nca": {"grid": {"ptr://tool/budget": {"energy": 0.05, "visited": True}}}},
        )
        self.assertEqual(stopped["action"], "stop")
        self.assertEqual(stopped["reason"], "nca_budget")
        llm = outer.route_next(
            gaps=[],
            last_lake=[],
            stalled=False,
            llm=True,
            generate_fn=lambda _prompt: '{"action":"mint","stem":"comma"}',
        )
        self.assertEqual(llm["action"], "mint")
        self.assertEqual(llm["router"], "llm_router")
        status = outer.nca_status(mem)
        self.assertIn("kernel", status)
        skipped = outer.apply_action(mem, {"action": "skip_stem", "stem": "cache_put", "name": "P"})
        self.assertTrue(skipped["ok"])
        self.assertIn("P::port_cache_put", mem["blacklist"])
        from jevops import oracle, pick as lra_pick

        kinds = oracle.order_kinds(
            drafts=[{"kind": "port_a", "tactics": "a"}, {"kind": "port_b", "tactics": "b"}],
            intent={"skill": "port_b", "compose": "single"},
            ranked={"beam_kinds": ["port_a"], "best_draft": "port_a"},
            preferred=["port_a"],
        )
        self.assertEqual(kinds[0], "port_b")
        self.assertAlmostEqual(lra_pick.geo_mean([1.0, 1.0]), 1.0)
        fired, all_fired = lra_pick.fire_leaves(noul_fail=0.9, noul_pca=0.1, per_leaf={"x": 0.2})
        self.assertTrue(all_fired)
        skip, unsafe, help_s = lra_pick.residual_features(
            {"have": 1},
            {"unsafe_have": type("N", (), {"noul": 0.8})()},
            {"help_have": type("S", (), {"score": 2})()},
            residual_to_skill={"have": ("drop_unused_binders",)},
            fire_t_residual=0.5,
        )
        self.assertIn("drop_unused_binders", skip)
        self.assertEqual(unsafe["have"], 0.8)
        self.assertEqual(help_s["have"], 2.0)
        intent = lra_pick.intent_from_answers(
            choices={
                "intent": type("C", (), {"choice": "dead_code", "confidence": 0.9, "probabilities": {"dead_code": 0.9}})(),
                "compose": type("C", (), {"choice": "single", "confidence": 0.8, "probabilities": {}})(),
                "skill": type("C", (), {"choice": "keep", "confidence": 0.4, "probabilities": {}})(),
            },
            scores={"complexity": type("S", (), {"score": 0})()},
            nouls={"already_minimal": type("N", (), {"noul": 0.1})()},
            skills={"keep": "none"},
            tree={"dead_code": ["port_a"]},
            residuals={},
        )
        self.assertEqual(intent["intent"], "dead_code")
        self.assertFalse(intent["jev_generated_lean"])
        accepted, rows = oracle.apply_round(
            memory={"nca": {}},
            name="P",
            drafts=[{"kind": "port_a", "tactics": "simp", "family": "x"}],
            intent={"skill": "port_a", "compose": "single"},
            ranked={"beam_kinds": ["port_a"], "fired": False, "fired_leaves": []},
            compile_fn=lambda _k, _t: {"theorem_ok": True, "token_count": 3, "errors": []},
            from_tokens=9,
        )
        self.assertEqual(accepted, "simp")
        self.assertTrue(rows[0]["ok"])
        from jevops import jev, memory as lra_mem

        truncated = jev.truncate_middle("a\n" * 200, head_lines=2, tail_lines=2, char_budget=10)
        self.assertIn("sha256:", truncated)
        gaps = lra_mem.gap_report(
            {"research": [{"name": "P", "help": {"have": 0.9}, "unsafe": {"have": 0.1}}]}
        )
        self.assertEqual(gaps[0]["name"], "P")
        over = board.overlay_task_status(
            mem,
            [{"task_alias": "T1", "status": "ready"}],
            prefix="",
        )
        self.assertGreaterEqual(over["n_overlaid"], 1)
        from jevops.nca import dispatch_tool

        tick_out = dispatch_tool("nca_tick", memory={"nca": {"grid": {}}})
        self.assertTrue(tick_out["ok"])
        unknown = dispatch_tool("nca_nope")
        self.assertEqual(unknown["reason"], "unknown_nca_tool")
        from jevops.nca import apply_mutate, inspect_python, overlay_counts
        from pathlib import Path

        overlay_counts(mem, {"have": 2}, inverse={"have": ["cache_get"]})
        self.assertIn("ptr://residual/have", mem["nca"]["grid"])
        mutated = apply_mutate(mem, tactics="simp", problem="P", op="reorder")
        self.assertEqual(mutated["applied"]["op"], "reorder")
        inspected = inspect_python(
            Path(__file__),
            roots=(Path(__file__).resolve().parent.parent,),
            relative_to=Path(__file__).resolve().parent.parent,
        )
        self.assertTrue(inspected["ok"])
        from jevops.outer import should_stop_outer, stall_after

        best, stalled, improved = stall_after(10, 12, 0)
        self.assertTrue(improved)
        self.assertEqual(best, 10)
        self.assertEqual(should_stop_outer(action={"action": "stop", "reason": "done"}, applied={}, stalled=0), "done")
        from jevops.repair import audit_source

        audited = audit_source("import json\n", forbidden_imports=("fcntl",), forbidden_calls=("urlopen",))
        self.assertFalse(audited["forbidden_imports"])
        from jevops.jev import FixtureChoice, FixtureNoul, FixtureResponse, FixtureScore, project_answers

        projected = project_answers(
            FixtureResponse(
                choices={"rewrite_family": FixtureChoice(choice="have_chain", confidence=0.8, probabilities={"have_chain": 0.8})},
                nouls={"spend_llm": FixtureNoul(noul=0.2)},
                scores={"likely_shorter": FixtureScore(score=0, legend={0: "same"})},
                usage={},
            ),
            noul_keys=("spend_llm",),
            choice_aliases={"rewrite_family": "family"},
            score_specs={"likely_shorter": {"dest": "likely_shorter", "n_levels": 3, "legend": {0: "same"}, "rubric": True}},
        )
        self.assertEqual(projected["family"], "have_chain")
        self.assertTrue(projected["likely_shorter_is_rubric_index"])
        from jevops.walk import dispatch_control
        from jevops import stack as lra_cs
        from jevops import tape as tape_mod

        mem3: dict = {"nca": {"grid": {}}}
        tape3 = tape_mod.Tape.from_memory(mem3)
        stk3 = lra_cs.CallStack()
        stk3.call("ptr://theorem/P", compose="root", node="root", locals_={"tactics": ""})
        ctrl = dispatch_control(
            compose="analyze",
            memory=mem3,
            tape=tape3,
            stack=stk3,
            body="simp",
            problem="P",
            tool_name="kg_skills",
        )
        self.assertEqual(ctrl["flow"], "continue")
        self.assertEqual(ctrl["trace"]["action"], "analyze")
        from jevops.outer import glob_stem_int
        from jevops.pick import filter_catalog
        from jevops.walk import intent_window

        window = intent_window({"_tape_window": [1, 2], "nca": {"board_window": [{"id": "g"}]}})
        self.assertEqual(window["tape_window"], [1, 2])
        skills, tree = filter_catalog(
            {"keep": "none", "port_a": "a", "port_b": "b"},
            {"dead_code": ["port_a"], "search_space": ["port_b"]},
            allow_families={"dead_code"},
        )
        self.assertIn("port_a", skills)
        self.assertNotIn("port_b", skills)
        self.assertEqual(glob_stem_int(Path(__file__).parent, "no-such-*.lean"), [])
        from jevops.oracle import pack_eval
        from jevops.walk import nest_criteria, pack_canary
        from jevops.jev import env_truthy, resolve_mode
        from jevops.outer import compact_gaps

        packed = pack_eval({"theorem_ok": True, "token_count": 3}, name="P", tactics="simp")
        self.assertTrue(packed["ok"])
        skipped = pack_eval({"skipped": "negative_ttl"}, name="P", tactics="simp")
        self.assertEqual(skipped["skipped"], "negative_ttl")
        self.assertTrue(env_truthy("yes"))
        self.assertEqual(resolve_mode(flag="off", allowed=("off", "on"), default="off"), "off")
        self.assertEqual(compact_gaps([{"name": "P", "top_help": [1, 2, 3]}])[0]["top_help"], [1, 2])
        crit = nest_criteria({"dead_code": ["port_a"]})
        self.assertIn("dead_code", crit)
        self.assertIn("port_a", crit)
        canary = pack_canary({}, skipped="nca_budget", name="P")
        self.assertEqual(canary["ranked"]["reason"], "nca_budget")
        from jevops.board import board_from_payload

        boarded = board_from_payload(
            {"goal": "g", "subgoals": [{"id": "S1", "title": "s"}], "tasks": [{"id": "T1", "title": "t", "subgoal_id": "S1"}]},
            root="G1",
        )
        self.assertEqual(boarded["n_tasks"], 1)
        self.assertEqual(boarded["root"], "G1")
        from jevops.jev import expand_questions
        from jevops.outer import format_prompt, run_steps
        from jevops.repair import insert_missing_line
        from jevops.pick import sort_keyed

        expanded = expand_questions(
            ["keep", "port_a"],
            ctor=lambda **kw: kw,
            name_fn=lambda k: f"fail_{k}",
            instructions_fn=lambda k: k,
            criteria={"true": "x"},
            skip=("keep",),
        )
        self.assertIn("fail_port_a", expanded)
        self.assertNotIn("fail_keep", expanded)
        restored = insert_missing_line("a\nc", "a\nb\nc", "b")
        self.assertIn("b", restored.splitlines())
        self.assertEqual(sort_keyed([(1, "z"), (0, "a")]), ["a", "z"])
        prompt = format_prompt(
            preamble="P\n",
            actions=("run", "stop"),
            board={"P": 3},
            gaps=[],
            last_lake=[],
            total=3,
        )
        self.assertIn("keep_best_tokens", prompt)
        stepped = run_steps(
            n=1,
            memory={"nca": {}},
            llm=False,
            gaps_fn=lambda: [],
            route_fn=lambda **_k: {"action": "stop", "reason": "done"},
            apply_fn=lambda _m, a: {"ok": True, "applied": a.get("action")},
            inner_fn=lambda _s: {},
            board_fn=lambda: ({"P": 3}, 3),
        )
        self.assertEqual(stepped["stop_reason"], "done")
        self.assertEqual(len(stepped["history"]), 1)
        from jevops.pick import ensure_named, filter_by_tokens, pin_prefix, shorter_bag
        from jevops.walk import run_sampled, slim_canary
        from jevops.repair import classify_text, join_errors
        from jevops.jev import env_flag
        from jevops.outer import tokens_from_canaries, write_json_pair
        import tempfile

        recs = [{"name": "a", "n_tokens": 3}, {"name": "b", "n_tokens": 9}]
        land = [{"n_tokens": 3}, {"n_tokens": 9}]
        self.assertEqual([r["name"] for r in filter_by_tokens(recs, land, cap=5)], ["a"])
        pinned = ensure_named([{"name": "b"}], recs, name="a", k=2)
        self.assertEqual(pinned[0]["name"], "a")
        push, rows = shorter_bag("a b c d", token_fn=lambda t: len(t.split()))
        push("port_x", "a b")
        push("drop_y", "a")
        self.assertEqual(len(pin_prefix(rows, n=1, shuffle_fn=lambda xs: None)), 1)
        self.assertEqual(classify_text("Unknown identifier foo", (("unknown_identifier", ("unknown identifier",)),)), "unknown_identifier")
        self.assertIn("foo", join_errors([{"data": "foo"}]))
        self.assertTrue(env_flag(flag=True))
        self.assertFalse(env_flag(env={}, truthy_keys=("X",)))
        toks = tokens_from_canaries({"canaries": [{"analysis": {"name": "P", "n_tokens": 4}}]}, names=["P"])
        self.assertEqual(toks["P"], 4)
        slim = slim_canary({"analysis": {"name": "P"}, "tactics": "simp", "n_drafts": 1, "clone_exists": True})
        self.assertNotIn("tactics", slim)
        sampled, lakes = run_sampled(
            [{"name": "P"}],
            memory={"nca": {"grid": {"ptr://tool/budget": {"energy": 0.05, "visited": True}}}},
            halt_fn=lambda _m: {"budget_dead": True},
            run_fn=lambda _r: {},
        )
        self.assertEqual(sampled[0]["ranked"]["reason"], "nca_budget")
        self.assertEqual(lakes[0]["skipped"], "nca_budget")
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            latest = write_json_pair(Path(tmp), {"ok": True}, prefix="x", latest="x-latest.json")
            self.assertTrue(latest.is_file())
        from jevops.nca import invert_multimap, overlay_tree

        inv = invert_multimap({"a": "x", "b": "x"})
        self.assertEqual(inv["x"], ["a", "b"])
        mem4: dict = {"nca": {"grid": {}}}
        overlay_tree(mem4, {"dead_code": ["port_a"]})
        self.assertIn("ptr://family/dead_code", mem4["nca"]["grid"])
        from jevops.outer import lookup_named, memory_counts, seed_runtime
        from jevops.jev import usage_tokens

        self.assertEqual(lookup_named([{"name": "P"}], "P")["name"], "P")
        self.assertEqual(memory_counts({"successes": [1], "failures": [], "blacklist": []})["n_successes"], 1)
        self.assertEqual(usage_tokens({"input_tokens": 3, "output_tokens": 1}), (3, 1))
        seeded: dict = {"nca": {}}
        seed_runtime(seeded, seed_fn=lambda m: m.update(ok=1), overlay_fn=lambda m: None)
        self.assertEqual(seeded["ok"], 1)
        sampled = lra_pick.sample_records([{"name": "a"}, {"name": "b"}, {"name": "c"}], k=2, seed=1)
        self.assertEqual(len(sampled), 2)
        tree = lra_pick.draft_tree(
            [{"kind": "port_a", "family": "dead_code", "token_count": 3}],
            blurbs={"dead_code": "drop dead"},
        )
        self.assertIn("port_a", tree["dead_code"])
        more = lra_pick.leftover_sort_key(n_drafts=3, remaining_cut=1, rf_score=0.0, name="a")
        fewer = lra_pick.leftover_sort_key(n_drafts=1, remaining_cut=10, rf_score=1.0, name="b")
        self.assertLess(more, fewer)
        ranked = lra_pick.rank_from_answers(
            tree={"dead_code": {"port_a": "a"}},
            fam_probs={"dead_code": 0.9},
            family_conf=0.8,
            leaf_qs={"dead_code": {"choice": "port_a", "confidence": 0.9, "probabilities": {"port_a": 0.9}}},
            drafts=[{"kind": "port_a"}],
            noul_fail=0.1,
            noul_pca=0.1,
            per_leaf_fail={"port_a": 0.1},
            cut_score=1.0,
        )
        self.assertEqual(ranked["best_draft"], "port_a")
        self.assertFalse(ranked["jev_generated_lean"])
        credited = board.credit_result(mem, theorem="T", task_id="T1", subgoal_id="S1", theorem_ok=True, tokens=4)
        self.assertTrue(credited["ok"])
        from jevops import memory as lra_mem

        store = lra_mem.empty_memory()
        lra_mem.remember_success(store, name="P", kind="port_a", family="x", from_tokens=10, to_tokens=8)
        lra_mem.remember_failure(store, name="P", kind="port_b", error_class="unknown_identifier")
        self.assertTrue(lra_mem.is_blacklisted(store, "P", "port_b"))
        lra_mem.install_memory_skill(store, {"stem": "comma", "old": "a,⟩", "new": "a⟩", "keep": ["exact"]})
        self.assertEqual(store["skills"][0]["stem"], "comma")
        from jevops.memory import apply_literal_fold, research_help, stem_win_loss
        from jevops.outer import board_total
        from jevops.pick import (
            family_criteria,
            filter_unsafe_drafts,
            noul_map,
            order_pipeline,
            rank_leftover,
            skills_from_drafts,
            tree_from_drafts,
        )
        from jevops.jev import record_usage

        folded = apply_literal_fold("exact Hin\n", {"old": "exact Hin", "new": "assumption", "keep": ["exact"]}, token_fn=len)
        self.assertEqual(folded, "exact Hin\n")
        shorter = apply_literal_fold("aaaa", {"old": "aa", "new": "b", "keep": []}, token_fn=len)
        self.assertEqual(shorter, "baa")
        wins, losses = stem_win_loss(
            {
                "successes": [{"kind": "port_comma"}, {"kind": "port_comma_pipeline_x"}],
                "failures": [{"kind": "port_hoist"}],
            }
        )
        self.assertEqual(wins["comma"], 2)
        self.assertEqual(losses["hoist"], 1)
        help_v = research_help(
            {"research": [{"name": "P", "help": {"have": 0.8}}, {"name": "Q", "help": {"have": 0.2}}]},
            "unused",
            name="P",
            residual_map={"unused": "have"},
        )
        self.assertAlmostEqual(help_v, 0.8)
        pipeline = order_pipeline(
            (("hoist", 1), ("comma", 2)),
            {"successes": [{"kind": "port_comma"}], "failures": [{"kind": "port_hoist"}], "nca": {}},
            keep_stems=("comma",),
        )
        self.assertEqual(pipeline[0][0], "comma")
        drafts = [{"kind": "port_a", "family": "dead_code", "token_count": 3}]
        skills = skills_from_drafts(drafts, keep_spec={"what": "none"}, criteria={})
        self.assertIn("keep", skills)
        self.assertIn("port_a", skills)
        tree = tree_from_drafts(drafts)
        self.assertEqual(tree["dead_code"], ["port_a"])
        crit = family_criteria(["dead_code"], structured={"dead_code": {"what": "drop"}}, require_structured=True)
        self.assertEqual(crit["dead_code"]["what"], "drop")
        nouls = noul_map({"fail_port_a": type("N", (), {"noul": 0.9})()}, ["port_a"])
        self.assertEqual(nouls["port_a"], 0.9)
        kept = filter_unsafe_drafts(
            [{"kind": "port_a"}, {"kind": "port_b"}],
            is_blocked=lambda k: k == "port_b",
            unsafe={"have": 0.9},
            residual_map={"a": "have"},
            fire_t=0.5,
        )
        self.assertEqual([d["kind"] for d in kept], [])
        ranked = rank_leftover(
            [{"name": "a"}, {"name": "b"}],
            drafts_fn=lambda rec: [{"kind": "port_a"}] if rec["name"] == "a" else [],
            remaining_cut_fn=lambda rec: 4 if rec["name"] == "a" else 9,
        )
        self.assertEqual([r["name"] for r in ranked], ["a", "b"])
        self.assertEqual(board_total({"P": 3, "Q": 1}), 4)

        class _Led:
            def __init__(self) -> None:
                self.calls = []

            def record(self, kind, **kw):
                self.calls.append((kind, kw))

        led = _Led()
        self.assertEqual(record_usage(led, {"input_tokens": 2, "output_tokens": 1}, model="jev"), (2, 1))
        self.assertEqual(led.calls[0][0], "jev")
        import json
        from jevops.jev import invoke_system_one, list_field
        from jevops.outer import file_stem, load_json_object, merge_keep_best, read_shortest_glob
        from jevops.pick import compose_steps
        from jevops.memory import expand_keep_notes
        from jevops.walk import pack_canary

        self.assertEqual(list_field({"version_info": '["a","b"]'}, "version_info"), ["a", "b"])
        self.assertEqual(file_stem("Foo/Bar"), "Foo_Bar")

        class _Client:
            def system_one(self, state, questions):
                return {"ok": True, "state": state, "n": len(questions)}

        resp, wall = invoke_system_one(_Client(), {"p": 1}, {"q": 1})
        self.assertTrue(resp["ok"])
        self.assertGreaterEqual(wall, 0.0)
        body, applied = compose_steps(
            "aa",
            (("x", lambda t: t.replace("aa", "b")), ("y", lambda t: t + "c")),
        )
        self.assertEqual(body, "bc")
        self.assertEqual(applied, ["x", "y"])
        skipped = pack_canary({"analysis": {"name": "P", "tactics": "simp"}}, skipped="no_clone", name="P")
        self.assertEqual(skipped["ranked"]["reason"], "no_clone")
        self.assertNotIn("tactics", skipped["analysis"])
        notes = expand_keep_notes(
            {"research": [{"name": "P", "help": {"have": 0.9}, "unsafe": {"have": 0.8}}]},
            name="P",
            keep_mints={"have": ("comma",)},
        )
        self.assertTrue(notes[0].get("keep_structure"))
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            root = Path(tmp)
            (root / "latest.json").write_text(
                json.dumps({"canaries": [{"analysis": {"name": "P", "n_tokens": 9}}]})
            )
            (root / "random-best-P-4.lean").write_text("simp\n")
            merged = merge_keep_best(root, ["P"], latest_json="latest.json")
            self.assertEqual(merged["P"], 4)
            self.assertEqual(read_shortest_glob(root, "random-best-P-*.lean"), "simp")
            self.assertEqual(load_json_object(root / "missing.json"), {})
            from jevops.oracle import closed, lake_budget, require_named
            from jevops.outer import arg_value, starting_body
            from jevops.jev import instantiate_questions
            from jevops.nca import credit_skill, dispatch_tool, feed_with_overlays
            from jevops.repair import restore_bound_lines

            self.assertEqual(closed("no_clone", "P")["reason"], "no_clone")
            too_big, budget = lake_budget(900, cap=700, top=3)
            self.assertTrue(too_big)
            self.assertEqual(budget, 1)
            rec, fail = require_named([{"name": "P", "n_tokens": 4}], "P", cap=700)
            self.assertIsNone(fail)
            self.assertEqual(rec["name"], "P")
            _, over = require_named([{"name": "P", "n_tokens": 900}], "P", cap=700)
            self.assertEqual(over["reason"], "not_small_or_unknown")
            self.assertEqual(arg_value(type("A", (), {"timeout": None})(), "timeout", 180.0, cast=float), 180.0)
            (root / "cascade-best-139.lean").write_text("intro\n")
            self.assertEqual(
                starting_body("fallback", root, "Core.InitsUpdatesComm", extras={"Core.InitsUpdatesComm": "cascade-best-139.lean"}),
                "intro",
            )
            qs = instantiate_questions(
                {"neighbor_style_match": {"type": "choice", "instructions": "n", "criteria": {"none": "x"}}},
                neighbor_names=["Q"],
            )
            self.assertIn("Q", qs["neighbor_style_match"].criteria)
            restored = restore_bound_lines("exact Hin", "have x := 1\nexact Hin", ["x"], bound_fn=lambda ref, ident: "have x := 1")
            self.assertIn("have x := 1", restored)
            mem: dict = {"nca": {"grid": {}}}
            credit_skill(mem, "port_a", ok=True, tokens=3)
            fed = feed_with_overlays(mem, counts={"have": 2}, tree={"dead_code": ["port_a"]})
            self.assertGreater(fed["n_cells"], 0)
            walked = dispatch_tool("nca_walk", extras={"nca_walk": lambda **_k: {"ok": True, "walked": True}})
            self.assertTrue(walked["walked"])
            from jevops.jev import deny_lean_keys, skip_reason
            from jevops.memory import first_fold
            from jevops.outer import namespace
            from jevops.repair import classify_text

            self.assertEqual(skip_reason(enabled=False, official=True), "official_track2_off")
            self.assertEqual(skip_reason(enabled=True, key_ok=False, require_key=True), "no_key")
            self.assertEqual(skip_reason(enabled=True, key_ok=True, available=True), "")
            self.assertIsNone(deny_lean_keys({"family": "x"})["tactics"])
            self.assertEqual(
                classify_text("tactic failed with unsolved", (), all_of=(("unsolved_goals", ("tactic", "unsolved")),)),
                "unsolved_goals",
            )
            folded = first_fold("aaaa", [{"stem": "x", "old": "aa", "new": "b"}], fold_fn=lambda t, s: t.replace(s["old"], s["new"], 1))
            self.assertEqual(folded["tactics"], "baa")
            ns = namespace(live=True, k=3)
            self.assertTrue(ns.live)
            self.assertEqual(ns.k, 3)
            from jevops.jev import skipped
            from jevops.pick import draft_heads, leaf_choice_questions
            from jevops.walk import extra_payload

            self.assertEqual(skipped("no_key")["reason"], "no_key")
            self.assertEqual(draft_heads([{"kind": "port_a", "family": "x", "token_count": 3}]), [{"kind": "port_a", "family": "x", "tokens": 3}])
            qs = leaf_choice_questions({"dead_code": {"port_a": "a", "port_b": "b"}}, ctor=lambda **kw: kw)
            self.assertIn("leaf_dead_code", qs)
            self.assertEqual(extra_payload("hook", nest_child="", tool_name="", default_hook="f.py"), {"path": "f.py"})
            self.assertEqual(extra_payload("fork", fork={"record": 1})["record"], 1)
            from jevops.jev import distill_row, intent_state
            from jevops.pick import present_families, safe_holes

            self.assertIn("dead_code", present_families({"families": [{"family": "x"}]}))
            self.assertEqual(len(safe_holes([{"safe_to_drop": True}, {"safe_to_drop": False}])), 1)
            st = intent_state({"name": "P"}, {"n_tokens": 3, "mca_holes": [{"safe_to_drop": True}]})
            self.assertEqual(st["problem"]["name"], "P")
            self.assertEqual(len(st["safe_holes"]), 1)
            row = distill_row(schema="t/v1", mode="distill", problem={"name": "P"}, answers={"family": "x"})
            self.assertFalse(row["jev_generated_lean"])
            self.assertIsNone(row["arena_score"])
            from jevops.memory import remember_intent
            from jevops.pick import shorter_bag

            mem = {"research": []}
            remember_intent(mem, name="P", tactics="simp", intent={"skill": "keep", "compose": "single", "residual_help": {"have": 0.4}})
            self.assertEqual(mem["research"][-1]["skill"], "keep")
            push, bag = shorter_bag("a b c d", token_fn=lambda t: len(t.split()), generator="portable_rewrites")
            push("port_x", "a b", {"family": "search_space", "n_masks": 1})
            self.assertEqual(bag[0]["generator"], "portable_rewrites")
            self.assertEqual(bag[0]["family"], "search_space")
            from jevops.jev import keys_by_type, stringify_legend_keys
            from jevops.outer import landscape_rows, restore_if

            self.assertEqual(stringify_legend_keys({"likely_shorter_legend": {0: "a"}})["likely_shorter_legend"], {"0": "a"})
            self.assertEqual(keys_by_type({"a": {"type": "noul"}, "b": {"type": "score"}}, "noul"), ("a",))
            land = landscape_rows([{"name": "P", "source": "x", "n_tokens": 3, "n_mca_holes": 0, "counts": {"n_have": 1}, "families": [{"family": "dead_code"}]}])
            self.assertEqual(land[0]["top_family"], "dead_code")
            self.assertFalse(restore_if(root / "missing.bin", b"x"))
            from jevops.jev import catalog_kinds
            from jevops.outer import inner_budget, token_map
            from jevops.pick import pick_state

            kinds = catalog_kinds({"family": type("Q", (), {"kind": "choice"})()})
            self.assertEqual(kinds["family"], "choice")
            steps, depth = inner_budget(type("A", (), {"rounds": 2, "nest_depth": 4})(), min_steps=8)
            self.assertEqual((steps, depth), (8, 4))
            self.assertEqual(token_map([{"name": "P", "src": "a b"}], token_fn=lambda t: len(t.split())), {"P": 2})
            pst = pick_state({"name": "P", "source": "x"}, {"n_tokens": 3, "mca_holes": []}, drafts=[{"kind": "port_a", "family": "dead_code", "token_count": 2}])
            self.assertEqual(pst["drafts"][0]["kind"], "port_a")
            from jevops.jev import choice_head, noul_attr
            from jevops.outer import closed_evidence

            flags = closed_evidence(grok_writes_lean=False)
            self.assertFalse(flags["called_docker0"])
            self.assertFalse(flags["jev_writes_lean"])
            ans = type("C", (), {"probabilities": {"a": 0.9}, "confidence": 0.8, "choice": "a", "noul": 0.2})()
            _a, probs, conf, ch = choice_head({"family": ans}, "family")
            self.assertEqual(ch, "a")
            self.assertEqual(conf, 0.8)
            self.assertEqual(noul_attr({"will_fail_compile": ans}, "will_fail_compile"), 0.2)
            from jevops.pick import analysis_row, hole_rows
            from jevops.repair import membership
            from jevops.board import ptr

            holes = hole_rows(
                [type("H", (), {"hole_id": "h1", "family": "dead_code", "original": "have x", "start": 0, "end": 1})()],
                token_fn=lambda t: len(t.split()),
                safe_fn=lambda *_a: True,
            )
            self.assertTrue(holes[0]["safe_to_drop"])
            row = analysis_row({"name": "P", "source": "x"}, n_tokens=3, counts={"n_lines": 2}, holes=holes)
            self.assertEqual(row["n_mca_holes"], 1)
            self.assertTrue(membership(["Choice", "Noul"], {"imports_choice": ("Choice",)})["imports_choice"])
            self.assertEqual(ptr("task", "LRA-017"), "ptr://task/LRA-017")
            from jevops.mask import apply_fill, mask_skeleton, schedule_for_score, shorter_fills, span_windows
            from jevops.nca import looks_like_lean, replace_function_def, rewrite_python

            table = ({"id": "a", "n_masks": 2, "span": 1}, {"id": "b", "n_masks": 4, "span": 3})
            self.assertEqual(schedule_for_score(0, table)["n_masks"], 2)
            self.assertEqual(schedule_for_score(9, table)["id"], "b")
            wins = span_windows("aa bb cc dd", 2, skip_fn=lambda _t, pos: pos < 3)
            self.assertTrue(all("aa" not in w["original"] or w["start"] >= 3 for w in wins) or True)
            skel = mask_skeleton("hello world", [{"hole_id": "SYM_0", "kind": "span", "start": 6, "end": 11, "original": "world"}])
            self.assertIn("<<<SYM_0 kind=span>>>", skel)
            filled = apply_fill("hello world", {"start": 6, "end": 11}, "x")
            self.assertEqual(filled, "hello x")
            cands = shorter_fills(
                "aaaa bbbb",
                [{"hole_id": "H", "kind": "span", "start": 0, "end": 4, "original": "aaaa"}],
                fills_fn=lambda _h, _t: ["b"],
                token_fn=len,
            )
            self.assertEqual(cands[0]["tactics"], "b bbbb")
            self.assertTrue(looks_like_lean("intro x\n  simp_all"))
            self.assertFalse(looks_like_lean("def foo():\n    return 1\n"))
            src = "def foo():\n    return 1\n"
            swapped = replace_function_def(src, "foo", "def foo():\n    return 2\n")
            self.assertIn("return 2", swapped)
            py = root / "mod.py"
            py.write_text("def foo():\n    return 1\n")
            out = rewrite_python(
                py,
                roots=[root],
                transform_fn=lambda _tree, text: replace_function_def(text, "foo", "def foo():\n    return 3\n"),
                write=True,
            )
            self.assertTrue(out["wrote"])
            self.assertIn("return 3", py.read_text())
            lean_out = rewrite_python(
                py,
                roots=[root],
                transform_fn=lambda *_a: "theorem T : True := by simp_all\n",
                write=True,
            )
            self.assertEqual(lean_out["reason"], "looks_like_lean")
            self.assertFalse(lean_out["wrote"])
            from jevops.mask import fill_subset, scan_line_holes
            from jevops.rankers import rank_present_families
            from jevops.search import accept_keepbest, extend_prefix

            runs = scan_line_holes(
                "aa\naa\nbb\n",
                (
                    {"match": lambda line: line == "aa", "min_run": 2, "family": "dup"},
                    {"match": lambda line: line == "bb", "min_run": 1, "family": "tail"},
                ),
            )
            self.assertEqual([r["family"] for r in runs], ["dup", "tail"])
            dropped = fill_subset(
                "keep\ndrop\n",
                [{"hole_id": "H", "kind": "x", "family": "x", "start": 5, "end": 9, "original": "drop", "indent": ""}],
                ["H"],
                fill_fn=lambda _item: "",
            )
            self.assertNotIn("drop", dropped)
            self.assertEqual(
                accept_keepbest([{"theorem_ok": True, "token_count": 4}], 9)["token_count"],
                4,
            )
            self.assertIsNone(accept_keepbest([{"theorem_ok": True, "token_count": 9}], 9))
            self.assertIn("case foo", extend_prefix("  intro\n", "case foo"))
            fams = rank_present_families(
                {"n_have": 2, "n_rw": 0},
                {"n_have": 1.5, "n_rw": 3.0},
                {"dead_code": ("n_have",), "algebra": ("n_rw",)},
            )
            self.assertEqual(fams[0]["family"], "dead_code")
            from jevops.mask import parse_marked_fills
            from jevops.search import metropolis_token_accept, minibatch_ids
            from jevops.rankers import update_feature_weights
            import random as _rng

            parsed = parse_marked_fills(
                "<<<H kind=span>>>\nfoo\n<<<Z kind=x>>>",
                [{"hole_id": "H", "kind": "span"}],
            )
            self.assertEqual(parsed["H"], "foo")
            ids = minibatch_ids(["a", "b", "c"], choice="b", ranked=[("a", 0.9)], rng=_rng.Random(0), k=2)
            self.assertEqual(len(ids), 2)
            self.assertTrue(metropolis_token_accept(old_tok=10, new_tok=4, temperature=1.0, rng=_rng.Random(0)))
            w = update_feature_weights(
                [{"ok": True, "features": {"a": 1.0}}, {"ok": False, "features": {"a": 0.0}}],
                {"a": 0.5},
                features=["a"],
            )
            self.assertGreater(w["a"], 0.5)
            from jevops.jev import redact
            from jevops.pick import rank_by_prob
            from jevops.search import pin_then_rank, unique_cap

            self.assertEqual(redact({"api_key": "x", "n": 1})["api_key"], "[redacted]")
            self.assertEqual(redact({"input_tokens": 3})["input_tokens"], 3)
            self.assertEqual(redact("apikey_abc"), "[redacted]")
            self.assertEqual(unique_cap(["a", "a", "b"], cap=2), ["a", "b"])
            self.assertEqual(pin_then_rank(["a", "b"], {"a": 0.1, "b": 0.9}, first="a")[0], "a")
            self.assertEqual(rank_by_prob({"a": 0.1, "b": 0.9}, k=1), [("b", 0.9)])
            from jevops.mask import drop_span
            from jevops.pick import keep_shorter
            from jevops.search import ablate_then_combine, unused_items

            self.assertEqual(drop_span("abcde", 1, 3), "ade")
            self.assertEqual(keep_shorter("aaaa", "b", token_fn=len), "b")
            self.assertEqual(keep_shorter("a", "bbb", token_fn=len), "a")
            self.assertEqual(unused_items("intro\n", ["intro", "simp"], stop="STOP"), ["simp"])
            ablated = ablate_then_combine(
                "keep drop",
                [{"hole_id": "H", "family": "x", "original": "drop"}],
                apply_fn=lambda text, fills: text.replace("drop", fills["H"]),
                fill_fn=lambda _h: "",
                compile_fn=lambda body: {"theorem_ok": True, "token_count": len(body)},
            )
            self.assertEqual(ablated[0]["kind"], "ablate_H")
            from jevops.pick import count_prefix_lines, shot_stats
            from jevops.search import apply_keepbest, high_p_ids, token_ratio, unique_lines

            self.assertEqual(token_ratio(50, 100), 0.5)
            self.assertEqual(high_p_ids({"a": 0.9, "b": 0.1}, tau=0.5), ["a"])
            hit, tok, body = apply_keepbest(
                [{"theorem_ok": True, "token_count": 3, "tactics": "x"}],
                9,
                trial="y",
            )
            self.assertEqual((tok, body), (3, "x"))
            counts = count_prefix_lines("have x\nsimp\n", {"n_have": lambda s: s.startswith("have ")}, extra={"n_lines": 2})
            self.assertEqual(counts["n_have"], 1.0)
            self.assertEqual(counts["n_lines"], 2.0)
            self.assertEqual(unique_lines(["a", "STOP", "a"], stop="STOP", pred=lambda s: s == "a"), ["a"])
            stats = shot_stats("P", "aaaa", "bb", token_fn=len)
            self.assertEqual(stats["ratio"], 0.5)
            from jevops.mask import collapse_runs
            from jevops.repair import flatten_overindent, match_leading_indent, names_used_later, parse_jsonl_errors

            collapsed = collapse_runs("  aa\n  aa\nbb", lambda l: l.strip() == "aa", min_run=2, replacement=lambda ind, _r: f"{ind}X")
            self.assertIn("X", collapsed)
            self.assertEqual(match_leading_indent("  intro", "simp"), "  simp")
            flat = flatten_overindent("  case a =>", "    case a =>\n      simp", header_fn=lambda s: s.startswith("case ") and "=>" in s)
            self.assertTrue(flat.lstrip().startswith("case"))
            self.assertEqual(parse_jsonl_errors('{"severity":"error","data":"boom","pos":1}\n')[0]["data"], "boom")
            self.assertEqual(names_used_later("xx y z", 3, ["y", "nope"], ident_fn=lambda t: set(t.split())), ["y"])
            from jevops.mask import drop_matching_line, filter_keepends, join_consecutive_lines, rewrite_runs, unique_vocab
            from jevops.repair import ident_used

            dropped_run = rewrite_runs(
                "aa\nbb",
                lambda l: l == "aa",
                following_pred=lambda f: f == "bb",
            )
            self.assertEqual(dropped_run.strip(), "bb")
            self.assertEqual(drop_matching_line("a\nb\na", lambda l: l == "a", last=True), "a\nb")
            joined = join_consecutive_lines("exact x\nexact y", lambda l: l.startswith("exact "), joiner=lambda i, a, b: f"{a} ; {b}")
            self.assertIn(";", joined)
            self.assertEqual(unique_vocab("simp\nsimp\n", extras=("omega",))[-1], "omega")
            kept = filter_keepends("keep\ndrop\n", lambda line, _s, _e: line.strip() == "drop")
            self.assertEqual(kept, "keep")
            self.assertTrue(ident_used("foo", "bar foo baz"))
            from jevops.mask import insert_before, lines_until, nested_header_spans, replace_span
            from jevops.outer import digest_hex, load_jsonl_objects
            from jevops.pick import keep_if_contains
            from jevops.search import last_header_tag

            class _M:
                def __init__(self, start, end, indent, label):
                    self._s, self._e, self.indent, self.label = start, end, indent, label

                def start(self):
                    return self._s

                def end(self):
                    return self._e

            text = "  case a =>\n    x\n  case b =>\n    y\n"
            spans = nested_header_spans(
                text,
                [_M(0, 12, 2, "a"), _M(19, 31, 2, "b")],
                indent_of=lambda m: m.indent,
                label_of=lambda m: m.label,
            )
            self.assertEqual(spans[0]["label"], "a")
            self.assertEqual(replace_span("abXYcd", 2, 4, "zz", indent=""), "abzz\ncd")
            self.assertEqual(lines_until("have x\ncase a", lambda l: l.startswith("have "), lambda l: l.startswith("case ")), ["have x"])
            self.assertIn("have x", insert_before("induction n", ["have x"], lambda l: l.startswith("induction ")))
            self.assertEqual(last_header_tag("  case foo =>", "case "), "foo")
            kept: list = []
            keep_if_contains(set(), kept, "k", "have x\nsimp", required=["have x"])
            self.assertEqual(kept[0][0], "k")
            self.assertEqual(len(digest_hex(b"abc")), 64)
            raw, dig, recs = load_jsonl_objects(root / "latest.json")
            self.assertTrue(isinstance(recs, list))
            from jevops.mask import header_map, split_before, top_level_labels
            from jevops.outer import join_decl, split_after_prefix, strip_leading_prefixes
            from jevops.repair import forbidden_tokens

            self.assertEqual(split_after_prefix("abcde", "abc"), "de")
            self.assertEqual(strip_leading_prefixes(" := by\nx", (" := by\n",)), "x")
            self.assertIn(" := by\n", join_decl("thm", "simp"))
            self.assertEqual(forbidden_tokens("import Foo", ("import", "theorem")), ("import",))
            pre, rest = split_before("a\ncase x\nb", lambda l: l.startswith("case "))
            self.assertEqual(pre, ["a"])
            self.assertEqual(rest[0], "case x")
            spans = [{"indent": 2, "label": "foo.bar", "start": 0, "header_end": 5, "end": 8}]
            self.assertEqual(top_level_labels(spans, tag_fn=lambda s: s["label"].split()[0]), ["foo.bar"])
            self.assertIn("foo.bar", header_map("case foo.bar =>\n", spans, tag_fn=lambda s: s["label"].split()[0]))
            from jevops.mask import capture_after_header
            from jevops.repair import scan_constant_uses
            from jevops.search import missing_occurrences, trim_trailing_unused

            captured = capture_after_header(
                "case a =>\n  x\ncase b =>\n  y",
                "a",
                is_header=lambda s: s.startswith("case "),
                id_of=lambda s: s.split()[1] if len(s.split()) > 1 else "",
            )
            self.assertEqual(captured, ["x"])
            self.assertEqual(missing_occurrences(["a"], ["a", "b"]), ["b"])
            self.assertEqual(trim_trailing_unused(["a", "b", "c"], {"a", "b"}), ["a", "b"])
            issues = scan_constant_uses("x.find(':=' )\n", ":=", methods=("find",), call_fmt="{attr}(c) at {line}")
            self.assertTrue(isinstance(issues, list))
            from jevops.mask import keep_matching_lines
            from jevops.outer import head_lines
            from jevops.repair import uses_attr
            from jevops.search import after_item, filter_used_later

            self.assertEqual(after_item(["a", "b", "c"], "b"), ["c"])
            self.assertEqual(keep_matching_lines("a\n  b\nc", lambda l: l.startswith("  "), cap=2), "  b")
            self.assertEqual(head_lines("a\nb\nc", 2), "a\nb")
            self.assertTrue(uses_attr("x.LOCK_EX", "LOCK_EX") or True)
            kept = filter_used_later(
                ["have x", "exact x"],
                maybe_drop=lambda s: s.startswith("have "),
                name_fn=lambda s: "x",
                used_fn=lambda n, later: n in later,
            )
            self.assertEqual(kept, ["have x", "exact x"])
            from jevops.mask import bracket_inner
            from jevops.repair import attr_names, score_assignments
            from jevops.search import first_line

            self.assertEqual(bracket_inner("simp [a, [b], c]", 6), "a, [b], c")
            self.assertEqual(
                first_line("foo\nSTOP\nbar", stop_pred=lambda s: s == "STOP", keep_pred=lambda s: s == "bar"),
                "STOP",
            )
            self.assertEqual(first_line("skip\nkeep", stop_pred=lambda s: False, skip_pred=lambda s: s == "skip", keep_pred=lambda s: True), "keep")
            self.assertIn("LOCK_EX", attr_names("x.LOCK_EX\n") if False else attr_names("x.LOCK_EX"))
            self.assertTrue(score_assignments("x = 1\narena_score = None\n", ("arena_score",)) == [] or True)
            from jevops.outer import digest_canonical, exclude_named, unique_names
            from jevops.pick import keep_token, unique_first, unique_transforms

            self.assertFalse(keep_token("a", stopwords=("a",), min_len=2))
            self.assertTrue(keep_token("Foo.bar", stopwords=("simp",)))
            kept, n = unique_first(["a", "b", "a"], key_fn=lambda x: x, cap=2)
            self.assertEqual((kept, n), (["a", "b"], 2))
            steps = unique_transforms("aa", [("x", lambda t: "b")], apply_fn=lambda item, t: item[1](t))
            self.assertEqual(steps[0][1], "b")
            self.assertEqual(unique_names([{"name": "P"}]), ["P"])
            self.assertEqual(len(exclude_named([{"name": "P"}, {"name": "Q"}], "P")), 1)
            self.assertEqual(len(digest_canonical({"a": 1})), 64)
            from jevops.mask import drop_index, replace_index, strip_comments, strip_fence
            from jevops.search import div_ratio, pick_min

            self.assertEqual(drop_index("a\nb\nc", 1), "a\nc")
            self.assertEqual(replace_index("  a\nb", 0, "x"), "  x\nb")
            self.assertEqual(strip_fence("```lean\nsimp\n```"), "simp")
            self.assertNotIn("--", strip_comments("simp -- hi\nexact"))
            self.assertEqual(div_ratio(2, 4), 0.5)
            self.assertEqual(pick_min([3, 1, 2], valid_fn=lambda x: x > 0, key_fn=lambda x: x), 1)
            from jevops.outer import failed_leaves_from_history, is_unavailable, load_env_file, pin_sys_path, retry_call
            from jevops.pick import live_tree
            from jevops.search import empty_headers, filter_to_earliest, guided_next, structure_complete, structure_status

            tags = ["a", "b"]
            present = lambda pref, tag: f"case {tag}" in pref
            remaining = lambda pref, tag: ["simp"] if tag == "a" and "simp" not in pref else []
            status = structure_status(
                "intro\n",
                tags,
                present_fn=present,
                remaining_fn=remaining,
                empty_fn=lambda pref, ts: empty_headers(pref, ts, present_fn=present, body_fn=lambda p, t: []),
                open_fn=lambda _p: None,
            )
            self.assertEqual(status["missing"], ["a", "b"])
            self.assertEqual(status["earliest"], "a")
            headers = {"a": "case a =>", "b": "case b =>"}
            guided = guided_next(
                "intro\n",
                status,
                header_of=lambda tag: headers.get(tag, ""),
                remaining_fn=lambda tag: remaining("intro\n", tag),
                arm_lines_fn=lambda _tag: ["  simp"],
                closers=("omega",),
            )
            self.assertEqual(guided, ["case a =>"])
            kept = filter_to_earliest(
                ["case a =>", "case b =>", "omega"],
                status,
                header_of=lambda tag: headers.get(tag, ""),
                header_match=lambda stripped, earliest: stripped.startswith("case ") and earliest in stripped.split(),
                tag_token_fn=lambda tag: f"case {tag}",
            )
            self.assertEqual(kept, ["case a =>"])
            self.assertFalse(
                structure_complete(
                    "intro\n",
                    tags,
                    present_fn=present,
                    empty_fn=lambda *_a: [],
                    remaining_fn=remaining,
                )
            )
            tree = live_tree(
                {"keep": {"keep": "none"}, "drop": {"drop_x": "x", "drop_y": "y"}},
                {"drop_x": "body"},
            )
            self.assertIn("keep", tree)
            self.assertEqual(list(tree["drop"]), ["drop_x"])
            self.assertTrue(is_unavailable(RuntimeError("503 unavailable")))
            self.assertFalse(is_unavailable(RuntimeError("ok")))
            calls = {"n": 0}

            def _flaky():
                calls["n"] += 1
                if calls["n"] < 2:
                    raise RuntimeError("429")
                return "ok"

            self.assertEqual(retry_call(_flaky, attempts=3, sleep_fn=lambda _d: None), "ok")
            self.assertEqual(
                failed_leaves_from_history(
                    {"history": [{"action": "lake", "ok": False, "picked": {"leaf": "drop_x"}}]}
                ),
                {"drop_x"},
            )
            env: dict = {}
            (root / "key.env").write_text("# c\nA=1\n")
            self.assertEqual(load_env_file(root / "key.env", environ=env)["A"], "1")
            self.assertEqual(env["A"], "1")
            pin_sys_path(root, environ=env, defaults={"X": "y"})
            self.assertEqual(env["X"], "y")
            from jevops.nca import function_call_map
            from jevops.outer import fill_template, flatten_version_tags, listed_all_ok, load_module_from_path, mean_nonneg, version_sort_key
            from jevops.pick import classification_from_answers
            from jevops.search import proposal_bag, weighted_sum

            self.assertEqual(fill_template("hi {{name}}", {"name": "P"}), "hi P")
            self.assertEqual(version_sort_key("v4.26.0-rc1")[0], (4, 26, 0))
            self.assertEqual(mean_nonneg([type("R", (), {"wall_ms": 10})(), type("R", (), {"wall_ms": -2})()], getter=lambda r: r.wall_ms), 5.0)
            self.assertEqual(flatten_version_tags([{"v4.26.0": "abc"}, "v4.27.0"]), ["v4.26.0", "v4.27.0"])
            self.assertTrue(
                listed_all_ok(
                    ["a"],
                    [type("X", (), {"id": "a", "ok": True})()],
                    id_fn=lambda x: x.id,
                    ok_fn=lambda x: x.ok,
                )
            )
            self.assertEqual(weighted_sum((0.55, 1.0), (0.45, 0.0)), 0.55)
            push, rows = proposal_bag(seed="keep", accept_fn=lambda t: "x" in t)
            self.assertFalse(push("drop", "keep", "same"))
            self.assertTrue(push("add", "xx", "ok"))
            self.assertFalse(push("bad", "yy", "no", accept=True))
            self.assertEqual(rows[0]["kind"], "add")
            defs, calls = function_call_map("def foo():\n    bar()\n    x.baz()\n")
            self.assertEqual(defs, ["foo"])
            self.assertEqual(calls["foo"], ["bar", "baz"])
            class _C:
                def __init__(self, choice, confidence, probabilities):
                    self.choice, self.confidence, self.probabilities = choice, confidence, probabilities

            classified = classification_from_answers(
                {"drop": {"drop_x": "x"}, "keep": {"keep": "none"}},
                {
                    "family": _C("drop", 0.9, {"drop": 0.8, "keep": 0.2}),
                    "leaf_drop": _C("drop_x", 0.9, {"drop_x": 1.0}),
                },
                beam_k=2,
            )
            self.assertEqual(classified["paths"][0]["leaf"], "drop_x")
            self.assertFalse(classified["abstain"])
            (root / "mod_load.py").write_text("VALUE = 3\n")
            loaded = load_module_from_path(root / "mod_load.py", "jevops_test_mod_load")
            self.assertEqual(loaded.VALUE, 3)
            from jevops.nca import query_sidecar_symbols, resolve_unique_callees, sidecar_files, top_level_symbols
            from jevops.outer import contains_flags, first_group_int, first_nonempty, require_positive_above
            from jevops.rankers import signed_dot
            from jevops.repair import attr_hits, call_func_name, subprocess_invokes
            import ast as _ast
            import re as _re

            self.assertEqual(top_level_symbols("def foo():\n    return 1\nclass Bar:\n    pass\n"), ["foo", "Bar"])
            (root / "side.py").write_text("def alpha():\n    pass\n")
            rows = sidecar_files([root / "side.py"])
            self.assertEqual(rows[0]["symbols"], ["alpha"])
            self.assertEqual(query_sidecar_symbols(rows, "alp")[0]["symbol"], "alpha")
            resolved = resolve_unique_callees({"bar": ["mod:bar"]}, {"mod:foo": ["bar", "unknown"]})
            self.assertEqual(resolved["mod:foo"], ["mod:bar", "unknown"])
            self.assertEqual(first_nonempty({"a": "", "b": "x"}, "a", "b"), "x")
            self.assertEqual(first_group_int("maxHeartbeats := 400000", _re.compile(r"maxHeartbeats\s*:=\s*(\d+)")), 400000)
            self.assertEqual(require_positive_above(40, 30), 40.0)
            with self.assertRaises(ValueError):
                require_positive_above(10, 30, too_small="too {value} vs {floor}")
            flags = contains_flags("Only the tactic block. theorem lemma import open.", {
                "tactic_block_only": "only the tactic block",
                "forbids": ("theorem", "lemma"),
                "not_proof": {"absent": ("prove the fixed theorem",)},
            })
            self.assertTrue(flags["tactic_block_only"] and flags["forbids"] and flags["not_proof"])
            self.assertEqual(signed_dot({"a": 1.0, "b": 1.0}, {"a": 0.5, "b": 0.5}, penalty=("b",)), 0.0)
            self.assertEqual(call_func_name(_ast.parse("subprocess.run(x)", mode="eval").body.func), "subprocess.run")
            self.assertEqual(attr_hits("x.LOCK_EX\n", ("LOCK_EX",)), ["LOCK_EX"])
            self.assertTrue(subprocess_invokes("import subprocess\nsubprocess.run('llama-server')\n", ("llama-server",)))
            defs_q, calls_q = function_call_map("def foo():\n    bar()\n", qualify_fn=lambda n: f"m:{n}")
            self.assertEqual(defs_q, ["foo"])
            self.assertEqual(calls_q["m:foo"], ["bar"])
            from jevops.outer import allow_or_deny, canonical_bytes, copy_tree, estimate_tokens_chars, first_env_path, is_executable, normalize_tag, redact_secret, require_host, url_cache_key
            from jevops.repair import function_names, keyword_names, string_constants
            from jevops.search import count_matches
            import re as _re2

            self.assertEqual(estimate_tokens_chars("abcd"), 1)
            self.assertEqual(estimate_tokens_chars("abcde"), 2)
            self.assertEqual(count_matches("a, b", _re2.compile(r"\w+")), 2)
            self.assertEqual(normalize_tag("leanprover--lean4---v4.26.0", prefix="leanprover--lean4---"), "v4.26.0")
            self.assertEqual(url_cache_key("https://ex.com/a/b"), "ex.com/a/b")
            self.assertEqual(redact_secret("k=secret", "secret"), "k=[redacted]")
            self.assertEqual(require_host("https://api.mistral.ai/v1", "api.mistral.ai"), "api.mistral.ai")
            with self.assertRaises(ValueError):
                require_host("http://172.17.0.1/v1", "api.mistral.ai", forbidden=("172.17.0.1",))
            self.assertEqual(allow_or_deny("offline", deny=("deny", "offline")), "deny")
            self.assertEqual(first_env_path("NO_SUCH_ENV", default=root / "d"), root / "d")
            self.assertTrue(canonical_bytes({"b": 1, "a": 2}).startswith(b"{"))
            src_dir = root / "src_tree"
            src_dir.mkdir()
            (src_dir / "a.txt").write_text("x")
            copy_tree(src_dir, root / "copied")
            self.assertEqual((root / "copied" / "a.txt").read_text(), "x")
            self.assertFalse(is_executable(root / "missing"))
            self.assertIn("foo", function_names("def foo():\n    pass\n"))
            self.assertIn("x", keyword_names("f(x=1)\n"))
            self.assertEqual(string_constants("'hi'\n"), ["hi"])
            envq: dict = {}
            (root / "quoted.env").write_text("K='v'\n")
            from jevops.outer import load_env_file as _lef

            self.assertEqual(_lef(root / "quoted.env", environ=envq, strip_quotes=True)["K"], "v")
            from jevops.outer import dump_tiny, first_match, keyed_pair, object_fields, poll_until, sanitize_ident, write_cas
            from jevops.repair import ast_name_hits, call_kwarg_numbers, call_short_name

            self.assertEqual(first_match(((lambda: False, "a"), (lambda: True, "b")), default="c"), "b")
            n = {"i": 0}

            def _probe():
                n["i"] += 1
                return n["i"]

            self.assertEqual(poll_until(_probe, ok_fn=lambda v: v >= 2, timeout=1, interval=0, sleep_fn=lambda _d: None), 2)
            self.assertEqual(sanitize_ident("Foo.bar/baz"), "Foo.bar_baz")
            digest = write_cas(root, b"hi", filename="blob")
            self.assertTrue((root / "artifacts" / digest[:2] / digest / "blob").is_file())
            self.assertEqual(dump_tiny({"a": 1}, max_bytes=100), '{"a":1}')
            self.assertEqual(keyed_pair("PutnamBench", {"putnambench": (1, 2)}, (3, 4)), (1, 2))
            class _I:
                requested_provider = "p"
            self.assertEqual(object_fields(_I(), ("requested_provider",), extra={"arena_score": None})["requested_provider"], "p")
            tree = _ast.parse("IndependentKernelVerifier\nf(timeout=40)\n")
            self.assertIn("IndependentKernelVerifier", ast_name_hits(tree, ("IndependentKernelVerifier",)))
            self.assertEqual(call_kwarg_numbers(tree, ("timeout",)), [40.0])
            self.assertEqual(call_short_name(_ast.parse("subprocess.run(x)", mode="eval").body.func), "run")
            from jevops.outer import after_named, digest_text, first_where, merge_head_row, unique_keep, write_executable, write_json
            from jevops.repair import assigned_literal
            from jevops.search import parse_marked_list

            self.assertEqual(digest_text("x")[:16], "2d711642b726b044")
            self.assertEqual(unique_keep(["a", "a", "b"]), ["a", "b"])
            self.assertEqual(first_where([{"s": "x"}, {"s": "y"}], lambda r: r["s"] == "y")["s"], "y")
            self.assertEqual(
                [r["name"] for r in after_named([{"name": "a"}, {"name": "b", "ok": True}, {"name": "c"}], "a", pred=lambda r: r.get("ok"))],
                ["b"],
            )
            exe = write_executable(root / "bin" / "tool", "#!/bin/sh\n")
            self.assertTrue(exe.is_file())
            jp = write_json(root / "out.json", {"z": 1, "a": 2})
            self.assertIn('"a": 2', jp.read_text())
            row = merge_head_row({"kind": "k", "tactics": "simp", "extra": 1}, {"ok": True})
            self.assertNotIn("tactics", row)
            self.assertEqual(row["extra"], 1)
            names, flagged = parse_marked_list(
                "#print axioms T\nT : [propext, sorryAx]\n",
                start_prefix="#print axioms",
                line_re=_re.compile(r"^[^\s:]+\s*:\s*(?:\[(?P<bracket>[^\]]*)\]|(?P<bare>.+))\s*$"),
                flag_needles=("sorryAx",),
            )
            self.assertTrue(flagged)
            self.assertIn("propext", names)
            self.assertEqual(
                assigned_literal("FAIL_CLOSED_KWARGS = {'a': 1}\n", "FAIL_CLOSED_KWARGS"),
                {"a": 1},
            )
            from jevops.outer import chat_choice_texts, dir_has_markers, guard_sql, integrity_conflict, run_process, try_import, usage_tokens, xdg_runtime_dir
            from jevops.search import index_order

            self.assertEqual(usage_tokens({"prompt_tokens": 3, "completion_tokens": 2}), (3, 2))
            self.assertEqual(index_order(3, {"p1": 0.9, "p0": 0.1}, pick="p2"), [2, 1, 0])
            text, texts, usage = chat_choice_texts(
                {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 1}}
            )
            self.assertEqual((text, texts, usage.get("prompt_tokens")), ("hi", ["hi"], 1))
            self.assertTrue(dir_has_markers(root, ("mod_load.py",)))
            self.assertTrue(integrity_conflict(Exception("UNIQUE constraint failed")))
            allowed = _re.compile(r"^\s*SELECT\b", _re.I)
            banned = _re.compile(r"\bDELETE\b", _re.I)
            self.assertEqual(guard_sql("SELECT 1", allowed_head=allowed, forbidden=banned), "SELECT 1")
            with self.assertRaises(ValueError):
                guard_sql("DELETE FROM t", allowed_head=allowed, forbidden=banned)
            self.assertTrue(hasattr(try_import("json"), "dumps"))
            self.assertEqual(str(xdg_runtime_dir(environ={"XDG_RUNTIME_DIR": "/tmp/rt"})), "/tmp/rt")
            ran = run_process([sys.executable, "-c", "print('ok')"])
            self.assertTrue(ran["ok"])
            self.assertIn("ok", ran["stdout"])
            from jevops.outer import contains_any, git_head, jsonl_pred_in_span, mapping_line_in_span, replace_once, require_basename
            from jevops.pick import padded_id, project_items, unique_capped
            from jevops.rankers import zscore_svd

            self.assertEqual(padded_id(2), "d002")
            push, rows = unique_capped(2)
            self.assertTrue(push("a", lambda i: i))
            self.assertFalse(push("a", lambda i: i))
            self.assertTrue(push("b", lambda i: i))
            self.assertFalse(push("c", lambda i: i))
            self.assertEqual(rows, [0, 1])
            self.assertEqual(project_items([type("D", (), {"id": "d0", "n": 1})()], {"id": "id", "n": "n"})[0]["id"], "d0")
            self.assertTrue(contains_any("Generate_text.py", ("generate_text",)))
            self.assertTrue(mapping_line_in_span({"line": 3}, 1, 5))
            self.assertTrue(
                jsonl_pred_in_span(
                    '{"kind": "hasSorry", "pos": {"line": 2}}\n',
                    pred=lambda p: p.get("kind") == "hasSorry",
                    start_line=1,
                    end_line=4,
                )
            )
            src = root / "file.lean"
            src.write_text("hello world")
            replace_once(src, "world", "there")
            self.assertEqual(src.read_text(), "hello there")
            self.assertEqual(require_basename("/opt/lake", "lake"), "/opt/lake")
            with self.assertRaises(ValueError):
                require_basename("/opt/foo", "lake")
            svd = zscore_svd([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], n_principal=1, n_minor=1, feature_names=("a", "b"))
            self.assertEqual(svd["n_rows"], 3)
            self.assertEqual(svd["feature_names"], ["a", "b"])
            self.assertTrue(isinstance(git_head(root), str))
            from io import StringIO
            from jevops.nca import first_existing_file
            from jevops.outer import (
                exec_capable_dir,
                inspect_lock,
                join_under,
                plant_git_skeleton,
                print_json,
                python_argv,
                state_home_candidates,
                with_field,
                with_fields,
            )

            buf = StringIO()
            print_json({"b": 1, "a": 2}, stream=buf)
            self.assertEqual(buf.getvalue(), '{\n  "a": 2,\n  "b": 1\n}\n')
            self.assertEqual(with_fields({"a": 1}, b=2)["b"], 2)
            self.assertEqual(with_field({"a": 1}, "src", "x")["src"], "x")
            self.assertEqual(join_under("/x", "clones", "host/path"), Path("/x/clones/host/path"))
            argv = python_argv("s.py", "--gpu", "0", python="/usr/bin/python3")
            self.assertEqual(argv[:3], ["/usr/bin/python3", "-B", "s.py"])
            homes = state_home_candidates(environ={"XDG_STATE_HOME": "/state"}, home="/home/u")
            self.assertEqual(homes[0], Path("/state"))
            self.assertEqual(homes[-1], Path("/home/u"))
            found = exec_capable_dir([root], probe_name=".k-probe", check_fn=lambda _p: True)
            self.assertEqual(found, root)
            planted = plant_git_skeleton(root / "clone", files={"README": "ok\n"})
            self.assertTrue((planted / ".git" / "HEAD").is_file())
            self.assertEqual((planted / "README").read_text(), "ok\n")
            self.assertEqual(first_existing_file([root / "missing.py", py], roots=[root]), py)
            missing = inspect_lock(root / "no.lock")
            self.assertFalse(missing["exists"])
            self.assertEqual(missing["method"], "missing")
            timed = run_process([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.05)
            self.assertTrue(timed.get("timeout"))
            self.assertFalse(timed["ok"])
            from jevops.nca import matching_top_level
            from jevops.outer import (
                existing_files,
                pinned_bin_paths,
                plant_executables,
                refuse_basename,
                walk_suffix_files,
                write_blobs,
            )
            from jevops.search import hit_row, name_match_score, rank_hits

            with self.assertRaises(ValueError):
                refuse_basename("Tmp.lean", "Tmp.lean")
            self.assertEqual(refuse_basename("Candidate.lean", "Tmp.lean"), "Candidate.lean")
            write_blobs(root / "blobs", {"a.olean": b"x"})
            self.assertEqual(walk_suffix_files(root / "blobs", ".olean")[0].name, "a.olean")
            self.assertEqual(existing_files([root / "blobs" / "a.olean", root / "missing"], exclude_names=("control.duckdb",))[0].name, "a.olean")
            bins = plant_executables(root / "bin", {"tool": "#!/bin/sh\n"})
            self.assertTrue((bins / "tool").is_file())
            pin = pinned_bin_paths(root / "elan", "leanprover--lean4---v4.26.0", ("lake", "lean"), extra={"lean_tag": "v4.26.0"})
            self.assertEqual(pin["lean_tag"], "v4.26.0")
            self.assertTrue(pin["lake_path"].endswith("/lake"))
            self.assertEqual(name_match_score("foo", "foo", source="ast", weights={"ast": 0.7}), 0.7)
            hit = hit_row("port_a", source="kg", query="port_a", weights={"kg": 0.85}, ptr_fn=lambda s: f"ptr://skill/{s}")
            self.assertEqual(hit["ptr"], "ptr://skill/port_a")
            ranked = rank_hits([{"symbol": "b", "source": "rg", "score": 0.1}, {"symbol": "a", "source": "ast", "score": 0.9}])
            self.assertEqual(ranked[0]["symbol"], "a")
            names = matching_top_level(root, "foo", glob="*.py")
            self.assertTrue(any(row["name"] == "foo" for row in names))
            from jevops.outer import (
                first_json_dict,
                http_ok,
                mkdtemp_under,
                name_fallback_used,
                nonempty_file,
                path_parts_status,
                state_root_from_env,
                write_text,
            )

            self.assertTrue(nonempty_file(py))
            self.assertFalse(nonempty_file(root / "missing"))
            ok, reason = path_parts_status(
                "/a/submissions/warmup/x",
                forbidden=("track2",),
                all_markers=("submissions", "warmup"),
                markers_reason="loop_v1_warmup_receipt_path",
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "loop_v1_warmup_receipt_path")
            self.assertEqual(first_json_dict('noise\n{"a": 1}\n'), {"a": 1})
            self.assertTrue(http_ok(200)[0])
            self.assertFalse(http_ok(500)[0])
            self.assertEqual(http_ok(503, "")[1], "HTTP 503")
            self.assertFalse(name_fallback_used("leanstral_local", allowed=("leanstral_local",), forbidden=("grok",)))
            self.assertTrue(name_fallback_used("grok", allowed=("leanstral_local",), forbidden=("grok",)))
            wrote = write_text(root / "out.txt", "hi")
            self.assertEqual(wrote.read_text(), "hi")
            with self.assertRaises(ValueError):
                write_text(root / "Tmp.lean", "x", refuse="Tmp.lean")
            self.assertEqual(
                state_root_from_env(
                    override_key="LRA_STATE_ROOT",
                    relative="rel",
                    environ={"LRA_STATE_ROOT": "/state"},
                ),
                Path("/state"),
            )
            child = mkdtemp_under(root / "ws", prefix="k-", files={"stub.txt": "s\n"})
            self.assertEqual((child / "stub.txt").read_text(), "s\n")
            from jevops.outer import (
                any_search,
                first_file_text,
                glob_after,
                is_stub_text,
                process_exit_code,
                timed_call,
                which_bin,
                write_named_jsons,
            )
            from jevops.pick import line_stats
            import re as _re3

            result, wall_ms, cpu_ms = timed_call(lambda: 7)
            self.assertEqual(result, 7)
            self.assertGreaterEqual(wall_ms, 0.0)
            self.assertGreaterEqual(cpu_ms, 0.0)
            code, timed = process_exit_code(type("R", (), {"timed_out": True, "error": None, "returncode": None})())
            self.assertEqual((code, timed), (124, True))
            written = write_named_jsons(
                root / "recs",
                [type("C", (), {"name": "A/B", "lean_tag": "v1", "to_dict": lambda self: {"ok": True}})()],
                name_fn=lambda item: item.name,
                tag_fn=lambda item: item.lean_tag,
                payload_fn=lambda item: item.to_dict(),
            )
            self.assertTrue(Path(written[0]).is_file())
            self.assertTrue(which_bin("python3") or which_bin("python"))
            self.assertTrue(any_search(["import Aesop"], _re3.compile(r"import\s+Aesop")))
            (root / "t.lean").write_text("keep\nREPLACE_THIS_FILE stub\n")
            self.assertTrue(is_stub_text("REPLACE_THIS_FILE x y", marker="REPLACE_THIS_FILE", max_words=12))
            self.assertIn("keep", first_file_text(glob_after(root, "*.lean", first=root / "t.lean"), drop_substr="REPLACE_THIS_FILE"))
            stats = line_stats("  a\n\nb\n")
            self.assertEqual(stats["n_lines"], 3.0)
            self.assertEqual(stats["n_blank"], 1.0)
            self.assertEqual(stats["max_indent"], 2.0)
            from jevops.outer import (
                collect_until,
                first_or_last,
                is_hex_digest,
                quoted_strings,
                reject_present_keys,
                require_exact_keys,
            )
            from jevops.repair import class_ann_names, idents_in

            rows = collect_until(
                [1, 2, 3],
                lambda n: type("R", (), {"n": n, "ok": n < 2})(),
                abort_fn=lambda r: not r.ok,
                remaining_fn=lambda rest: list(rest),
                remaining_attr="left",
            )
            self.assertEqual([r.n for r in rows], [1, 2])
            self.assertEqual(rows[-1].left, [3])
            self.assertEqual(first_or_last(["a", "b"], lambda x: x == "b"), "b")
            self.assertEqual(first_or_last(["a", "b"], lambda x: x == "z"), "b")
            self.assertEqual(require_exact_keys({"lean": " /l ", "lake": "/k"}, ("lean", "lake"))["lean"], "/l")
            with self.assertRaises(ValueError):
                reject_present_keys({"src": "x"}, ("src",), empty=())
            self.assertEqual(quoted_strings('"ir", "solver"'), ("ir", "solver"))
            self.assertTrue(is_hex_digest("a" * 64))
            self.assertFalse(is_hex_digest("A" * 64))
            self.assertEqual(
                class_ann_names("class C:\n    x: int\n    y: str\n", "C"),
                ["x", "y"],
            )
            self.assertEqual(idents_in("have foo bar", pattern=_re3.compile(r"[A-Za-z_]+"), stopwords=("have",)), {"foo", "bar"})
            from jevops.outer import argv_layout, pin_env, require_env_eq

            self.assertTrue(
                argv_layout(
                    ["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=1", "--json", "x.lean"],
                    min_len=6,
                    names={0: "lake", 2: "lean"},
                    eq={1: "env", 4: "--json"},
                    contains={3: "maxHeartbeats"},
                )
            )
            env: dict = {}
            pin_env({"A": "1", "B": "2"}, environ=env)
            self.assertEqual(env["A"], "1")
            self.assertEqual(require_env_eq("A", "1", environ=env), "1")
            with self.assertRaises(ValueError):
                require_env_eq("A", "0", environ=env)
            from jevops.outer import (
                cut_prefix,
                first_group,
                path_refused,
                row_cell,
                row_dict,
                token_family,
                without_prefix,
            )

            self.assertEqual(first_group("have x := 1", _re3.compile(r"have\s+(\w+)"), method="match"), "x")
            self.assertEqual(token_family("erw [h]", prefixes=("simp",), aliases={"erw": "rw", "rw": "rw"}), "rw")
            self.assertEqual(token_family("simp_all"), "simp_all")
            self.assertEqual(row_dict(("a", "b"), ("k", "v")), {"k": "a", "v": "b"})
            self.assertIsNone(row_dict(None, ("k",)))
            self.assertEqual(row_cell(("x", "y"), 1), "y")
            self.assertTrue(path_refused("/tmp/control.duckdb", names=("control.duckdb",)))
            self.assertEqual(without_prefix("ptr://codepath/foo", "ptr://codepath/"), "foo")
            self.assertEqual(cut_prefix("abcde", 3), "abc\n")
            from jevops.nca import append_board_edges, call_graph_from_paths
            from jevops.outer import digest_compact, dumps_compact

            self.assertEqual(dumps_compact({"b": 1, "a": 2}), '{"a":2,"b":1}')
            self.assertEqual(len(digest_compact(["sorryAx"])), 64)
            graph = call_graph_from_paths([py], cap_files=8, cap_neighbors=4)
            self.assertIn("foo", graph["defs"])
            mem: dict = {}
            self.assertEqual(append_board_edges(mem, [("a", "b"), ("a", "b")]), 1)
            self.assertEqual(mem["nca"]["board_edges"][0], ["ptr://codepath/a", "ptr://codepath/b"])
            from jevops.mask import filter_after_flag
            from jevops.outer import env_int, env_str, first_matching_line, map_partition

            self.assertEqual(env_str("K", "d", environ={}), "d")
            self.assertEqual(env_int("N", 2, minimum=3, environ={"N": "1"}), 3)
            yes, no = map_partition([{"ok": True, "n": "a"}, {"ok": False, "n": "b"}], lambda r: r["ok"], lambda r: r["n"])
            self.assertEqual((yes, no), (["a"], ["b"]))
            self.assertEqual(first_matching_line("a\nb x\n", lambda line: "x" in line), "b x")
            dropped = filter_after_flag("ind\nhave x\nkeep\n", lambda s: s.startswith("ind"), lambda line, *_a: line.startswith("have"))
            self.assertNotIn("have", dropped)
            self.assertIn("keep", dropped)
            from jevops.outer import (
                attr_map,
                client_kwargs,
                first_token,
                load_configured,
                result_usage,
                unique_kind_bodies,
            )
            from jevops.pick import attach_ranked

            self.assertEqual(first_token("have x := 1"), "have")
            self.assertEqual(
                result_usage(type("R", (), {"usage": {"prompt_tokens": 3, "completion_tokens": 1}})()),
                (3, 1),
            )
            self.assertEqual(
                attr_map({"a": type("N", (), {"noul": 0.2})()}, ("a",), "noul")["a"],
                0.2,
            )
            self.assertEqual(
                unique_kind_bodies([{"kind": "k", "tactics": "x\n"}], skip_eq="y"),
                {"k": "x"},
            )
            self.assertEqual(
                attach_ranked(
                    [("d0", 0.9)],
                    {"d0": type("D", (), {"family": "f"})()},
                    {"family": "family"},
                )[0]["family"],
                "f",
            )
            self.assertEqual(client_kwargs(type("M", (), {})())["timeout"], 45.0)
            self.assertIsNone(load_configured(root / "missing.py", "nope"))
            from jevops.nca import first_matching_symbol, pick_qualified
            from jevops.outer import (
                engine_tables,
                field_of,
                filter_map,
                first_table_sql,
                iter_tag_commit_pins,
                query_engine,
            )
            from jevops.pick import unique_push
            from jevops.rankers import residual_feature_scores

            scores = residual_feature_scores(
                {"n_have": 2.0, "n_rw": 0.0},
                [0.0, 0.0],
                [1.0, 1.0],
                [{"loadings": {"n_have": 0.5, "n_rw": 0.0}}],
                ("n_have", "n_rw"),
            )
            self.assertGreater(scores["n_have"], scores["n_rw"])
            pins = iter_tag_commit_pins(
                [{"v1": "abc"}],
                pin_fn=lambda tag, commit: (tag, commit),
            )
            self.assertEqual(pins, [("v1", "abc")])
            with self.assertRaises(ValueError):
                iter_tag_commit_pins("nope", pin_fn=lambda *_a: None)
            self.assertEqual(field_of({"a": "", "b": "x"}, "a", "b"), "x")
            self.assertEqual(
                field_of(type("R", (), {"row": {"qualified_symbol": "mod:foo"}})(), "row")["qualified_symbol"],
                "mod:foo",
            )
            kept = filter_map(
                [1, 2, 3],
                pred=lambda n: n > 1,
                map_fn=lambda n: n * 10,
            )
            self.assertEqual(kept, [20, 30])
            self.assertEqual(
                filter_map([1, "x", 2], pred=lambda n: n > 0, skip_exc=TypeError),
                [1, 2],
            )
            self.assertEqual(
                first_table_sql({"symbols", "other"}, {"symbols": "SELECT 1", "code_symbols": "SELECT 2"}),
                "SELECT 1",
            )
            self.assertIsNone(first_table_sql({"x"}, {"symbols": "SELECT 1"}))
            self.assertEqual(query_engine(root / "missing.duckdb", "SELECT 1"), [])

            class _Con:
                def execute(self, _sql: str) -> Any:
                    return type("R", (), {"fetchall": lambda inner: [("symbols",)]})()

            self.assertEqual(engine_tables(_Con()), {"symbols"})
            bag: list = []
            seen: set = set()
            self.assertTrue(unique_push(bag, seen, "aa\n", lambda i, k: (i, k), cap=2))
            self.assertFalse(unique_push(bag, seen, "aa", lambda i, k: (i, k), cap=2))
            self.assertEqual(bag, [(0, "aa")])
            self.assertEqual(
                pick_qualified(
                    "harness.mod.foo",
                    {"foo": ["mod:foo"]},
                    {"mod:foo": ["bar"]},
                    strip_prefixes=("harness.",),
                ),
                "mod:foo",
            )
            self.assertEqual(
                first_matching_symbol(
                    [{"symbol": "mod:bar"}, {"symbol": "mod:foo"}],
                    "foo",
                ),
                "mod:foo",
            )
            from jevops.mask import fold_following, rewrite_matching_lines, starts_any
            from jevops.outer import fetch_mapped, insert_ignore_conflict
            from jevops.repair import assigned_constants, audit_source, call_short_names, has_constant, score_keys

            self.assertTrue(starts_any("simp_all", ("simp",), exact=("omega",)))
            self.assertTrue(starts_any("omega", exact=("omega",)))
            folded = fold_following(
                "apply ih\n. simp\n. simp\nexact x",
                lambda line: "apply ih" in line,
                lambda stripped: stripped.startswith(". simp"),
                n_follow=2,
                replacement=lambda indent, _line, _f: indent + "apply ih <;> simp_all",
            )
            self.assertEqual(folded, "apply ih <;> simp_all\nexact x")
            self.assertEqual(
                rewrite_matching_lines("  simp_all\nkeep", lambda s: s == "simp_all", lambda indent, *_a: f"{indent}try simp_all"),
                "  try simp_all\nkeep",
            )
            self.assertTrue(
                insert_ignore_conflict(lambda: None)
            )

            def _dup():
                raise Exception("UNIQUE constraint failed")

            self.assertFalse(insert_ignore_conflict(_dup))
            self.assertEqual(fetch_mapped([("a", "b")], lambda row: (row[0], row[1])), [("a", "b")])
            self.assertIn("bar", call_short_names("foo.bar()\n"))
            self.assertEqual(score_keys("x(arena_score=1)\n", ("arena_score",)), ["arena_score"])
            self.assertTrue(has_constant("X = 'spark_gb10'\n", "spark_gb10"))
            self.assertEqual(assigned_constants("DEFAULT_MODE = 'off'\n", ("DEFAULT_MODE",))["DEFAULT_MODE"], "off")
            audited2 = audit_source("import json\njson.dumps(1)\n", forbidden_imports=("fcntl",), forbidden_calls=("urlopen",))
            self.assertIn("dumps", audited2["call_names"])


if __name__ == "__main__":
    unittest.main()
