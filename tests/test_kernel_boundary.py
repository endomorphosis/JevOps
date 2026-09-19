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
            "tape",
            "stack",
            "jsonld",
            "plan",
            "graph",
            "skill_tree",
            "rankers",
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


if __name__ == "__main__":
    unittest.main()
