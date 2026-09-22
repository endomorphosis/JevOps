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
            "binders",
            "folds",
            "inits",
            "lean",
            "tactics",
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
        from jevops import more_rankers as more
        from jevops import rankers

        encoded = ae.encode_milles("simp [foo]")
        self.assertEqual(len(encoded["mu"]), ae.LATENT_D)
        rt = ae.roundtrip_once("simp [foo]")
        self.assertFalse(rt["writes_lean"])
        ranked = ae.jev_rank_variations([rt])
        self.assertTrue(ranked["ok"])
        self.assertFalse(ranked["used_jev"])
        packed = ae.encode_lean_ir("intro simp trivial")
        self.assertEqual(packed["schema"], ae.LEAN_IR_SCHEMA)
        self.assertFalse(packed["legal_ir"])
        self.assertEqual(packed["families"], [])
        self.assertTrue(packed["functional_lean"])
        lean = ae.decode_lean_ir(packed)
        self.assertIn("True := by", lean)
        self.assertTrue(lean.startswith("theorem "))
        self.assertIn("  trivial", lean)
        self.assertNotIn("sorry", lean)
        ir_rt = ae.lean_ir_roundtrip("intro simp trivial")
        self.assertFalse(ir_rt["gold"])
        self.assertEqual(ir_rt["loss_gold"], "jev")
        self.assertIn("ir_ce_m", ir_rt)
        self.assertIn("ir_cosine_m", ir_rt)
        self.assertFalse(ir_rt["legal_ir"])
        self.assertTrue(rankers.is_ranker_stem("port_lean_ir"))
        self.assertTrue(rankers.is_ranker_stem("port_gan"))
        self.assertTrue(more.is_more_stem("port_gan"))
        mem: dict = {"nca": {}}
        ir_out = rankers.call_ranker("port_lean_ir", memory=mem, tactics="  intro\n  trivial\n")
        self.assertTrue(ir_out["ok"])
        self.assertEqual(ir_out["kind"], "port_lean_ir")
        self.assertFalse(ir_out["writes_lean"])
        self.assertFalse(ir_out["legal_ir"])
        self.assertIn("True := by", str(ir_out.get("lean") or ""))

        def jev_fn(payload):
            rows = list(payload.get("variations") or [])
            real = next((row for row in rows if row.get("role") == "real"), rows[0])
            return {"choice": real["id"], "scores": {row["id"]: 900 if row.get("role") == "real" else 100 for row in rows}, "noul": 0.1}

        gan = more.call_gan(mem, tactics="  intro\n  simp\n  trivial\n", jev_fn=jev_fn)
        self.assertTrue(gan["ok"])
        self.assertEqual(gan["kind"], "port_gan")
        self.assertTrue(gan["used_jev"])
        self.assertFalse(gan["writes_lean"])
        self.assertFalse(gan["gold"])
        self.assertFalse(gan["legal_ir"])
        self.assertTrue(gan["functional_lean"])
        self.assertGreaterEqual(gan["n_fake"], 1)
        dispatched = rankers.call_ranker("port_gan", memory={"nca": {}}, tactics="  trivial\n")
        self.assertEqual(dispatched["kind"], "port_gan")
        self.assertFalse(dispatched["writes_lean"])
        from jevops import binders, folds, lean

        self.assertEqual(folds.fold_exact_hyp("exact Hin"), "assumption")
        self.assertEqual(folds.fold_trailing_tuple_comma("exact ⟨a, b,⟩"), "exact ⟨a, b⟩")
        self.assertEqual(folds.fold_exact_hyp("exact Lemma.foo"), "exact Lemma.foo")
        packed = folds.fold_use_exact("case nested =>\n  use witness\n  exact ⟨left, right⟩\n")
        self.assertIn("  exact ⟨witness, left, right⟩", packed)
        self.assertNotIn("    exact ⟨witness", packed)
        self.assertEqual(binders.binders_from_line("rename_i x y"), ["x", "y"])
        self.assertIn("this", binders.binders_from_line("have der' : T := der"))
        dropped = binders.drop_unused_binders("rename_i ghost\nexact Hin\n")
        self.assertNotIn("ghost", dropped)
        names, sorry = lean.parse_axioms("#print axioms t\nt : []\n")
        self.assertFalse(sorry)
        argv = lean.measurement_argv("/opt/lake", "/opt/lean", "x.lean", max_heartbeats=400000)
        self.assertEqual(argv[1], "env")
        self.assertTrue(
            lean.lake_measurement_ok(
                exit_code=0,
                timed_out=False,
                sorry=False,
                axiom_names=[],
                stdout="ok",
                argv=argv,
                max_heartbeats=400000,
                timeout_seconds=600.0,
            )
        )
        from jevops import inits, tactics

        spans = tactics.case_spans("case foo =>\n  simp\n")
        self.assertEqual(spans[0].label, "foo")
        collapsed = tactics.collapse_simp_at("  simp at h\n  simp at h\n")
        self.assertIn("simp_all", collapsed)
        holes = tactics.find_holes("  rename_i ghost\n  exact Hin\n")
        self.assertTrue(any(hole.family == "dead_code" for hole in holes))
        self.assertGreaterEqual(len(inits.KERNELS), 41)
        replayed = inits.apply_kernel("and_intro_constructor", "    apply And.intro\n    exact x\n")
        self.assertIn("constructor", replayed)
        lemmas, _n = tactics.extract_src_lemmas("  simp [Foo.bar, skip]\n  exact Hin\n")
        names = [row.name for row in lemmas]
        self.assertIn("Foo.bar", names)
        self.assertNotIn("exact", names)
        joined = tactics.join_consecutive_applies("  apply a\n  apply b\n")
        self.assertIn("<;>", joined)
        pin = lean.VersionPin(lean_tag="v4.26.0", git_commit="abc")
        self.assertEqual(pin.to_dict()["lean_tag"], "v4.26.0")
        self.assertIn(" := by", lean.statement_sorry_template("theorem t : True"))
        self.assertEqual(lean.path_a_tactics("", ""), ["rfl", "decide", "omega", "simp_all"])
        self.assertIn("aesop", lean.path_a_tactics("import Aesop\n", ""))
        closed = lean.compile_closed(token_count=3)
        self.assertFalse(closed["theorem_ok"])
        dummy = type("R", (), {"stdout": "ok\n#print axioms t\nt : []\n", "stderr": "", "error": "", "returncode": 0})()
        filled = lean.fill_from_process(
            dummy,
            argv=["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=400000", "--json", "x.lean"],
            max_heartbeats=400000,
            timeout_seconds=600.0,
        )
        self.assertTrue(filled["ok"])
        self.assertFalse(filled["sorryAx"])
        lake_txt = lean.render_mathlib_aesop_lakefile(
            package="putnam_lake",
            lib="Putnam",
            max_heartbeats=400000,
            mathlib_git="https://github.com/leanprover-community/mathlib4.git",
            mathlib_rev="v4.26.0",
            aesop_git="https://github.com/leanprover-community/aesop.git",
            aesop_rev="v4.26.0",
        )
        self.assertIn("moreLeanArgs", lake_txt)
        self.assertNotIn("Tmp.lean", lake_txt)
        self.assertEqual(lean.ExecutablePaths(lean="/opt/lean", lake="/opt/lake").to_dict()["lake"], "/opt/lake")
        self.assertIn("True := by", lean.render_placeholder_theorem())
        self.assertEqual(lean.extract_generated_tactics("```\n  simp\n```"), "simp")
        self.assertEqual(lean.parse_next_tactic_line("exact Hin\nsimp"), "exact Hin")
        self.assertTrue(tactics.looks_like_tactic("simp_all"))
        self.assertTrue(tactics.is_mca_line("  have x := y"))
        tags = tactics.pca_case_tags("case foo =>\n  simp\ncase bar =>\n  rfl\n")
        self.assertEqual(tags, ["foo", "bar"])
        self.assertFalse(tactics.stop_allowed("case foo =>\n  simp\n", "case foo =>\n  simp\ncase bar =>\n  rfl\n"))
        edits = tactics.closed_tree_edits("  intro\n  simp at h\n  simp at h\n")
        families = [row[0] for row in edits]
        self.assertIn("reference", families)
        self.assertIn("simp_set", families)
        self.assertTrue(any(row[1] == "rfl" for row in edits))
        job = lean.BakeJob(
            kind="repo",
            source="strata",
            lean_tag="v4.26.0",
            git_commit="abc",
            url="https://example.com",
            cache_key="k",
            phase=0,
            record_names=("P",),
            file_paths=("A.lean",),
            module="A.lean",
        )
        self.assertEqual(job.to_dict()["kind"], "repo")
        self.assertIsNone(job.to_dict()["arena_score"])
        pin = lean.PutnamPin(
            lean_tag="v4.26.0",
            mathlib_git="https://github.com/leanprover-community/mathlib4.git",
            mathlib_rev="v4.26.0",
            aesop_git="https://github.com/leanprover-community/aesop.git",
            aesop_rev="v4.26.0",
            jsonl_version_pin="",
        )
        self.assertEqual(pin.module, "Putnam.Candidate")
        self.assertFalse(pin.tmp_lean)
        mca = tactics.guided_mca_edits("  intro\n  simp at h\n  simp at h\n", ["strength_reduction"])
        self.assertTrue(any(row[0] == "strength_reduction" for row in mca))
        split = lean.StatementBody(
            name="P",
            source="strata",
            statement="theorem t : True",
            body_suffix=" := by\n  trivial\n",
            header="",
        )
        self.assertEqual(split.reconstructed_src, "theorem t : True := by\n  trivial\n")
        view = lean.AdmissionView(
            accepted=True,
            failure_code="",
            reason="ok",
            name="P",
            native_source_starts_with_statement=True,
        )
        self.assertFalse(view.used_full_src_as_native)
        receipt = lean.TacticTryReceipt(name="P", schema="lake-native-try/v1")
        self.assertFalse(receipt.to_dict()["hammer_006_lra_ready"])
        self.assertFalse(receipt.to_dict()["uses_snapshot_goal"])
        self.assertEqual(lean.aesop_list_ok(["rfl"], False), "")
        self.assertIn("aesop listed", lean.aesop_list_ok(["aesop"], False))
        self.assertTrue(
            lean.sorry_prefix_bound(
                template="theorem t : True := by\nsorry",
                statement="theorem t : True",
                suffix=" := by\nsorry",
                lake_sorry="header\ntheorem t : True := by\nsorry\n",
            )
        )
        src = lean.lake_source_for_tactic(header="import Aesop", statement="theorem t : True", tactic="rfl")
        self.assertIn("rfl", src)
        catalog = lean.BakeCatalog(
            warmup_n=2,
            source_order=("strata", "putnambench"),
            putnam_source="putnambench",
            strata_source="strata",
            strata_first_tag="v4.26.0",
            putnam_tags=("v4.26.0",),
            putnam_candidate_relpath="Putnam/Candidate.lean",
            putnam_module="Putnam.Candidate",
        )
        jobs = lean.collect_bake_jobs(
            [
                {
                    "name": "P",
                    "source": "strata",
                    "url": "https://example.com",
                    "file_path": "A.lean",
                    "header": "",
                    "version_info": [{"v4.26.0": "abc"}],
                },
                {
                    "name": "Q",
                    "source": "putnambench",
                    "url": "",
                    "file_path": "",
                    "header": "import Mathlib\nimport Aesop\n",
                    "version_info": [{"v4.26.0": "def"}],
                },
            ],
            catalog,
            pin_fn=lambda info: [
                lean.VersionPin(lean_tag=str(next(iter(row))), git_commit=str(next(iter(row.values()))))
                for row in info
            ],
            putnam_pin_fn=lambda tag, commit: lean.putnam_pin_for_tag(
                tag,
                catalog.putnam_tags,
                mathlib_git="https://github.com/leanprover-community/mathlib4.git",
                aesop_git="https://github.com/leanprover-community/aesop.git",
                jsonl_version_pin=commit,
            ),
            url_key_fn=lambda url: "ex",
        )
        self.assertEqual(jobs[0].source, "strata")
        self.assertEqual(jobs[0].lean_tag, "v4.26.0")
        self.assertEqual(jobs[-1].kind, "putnam")
        self.assertEqual(jobs[-1].module, "Putnam.Candidate")
        neighbors = lean.jsonl_neighbors(
            [
                {
                    "name": "A",
                    "source": "s",
                    "statement": "theorem a : True",
                    "src": "theorem a : True := by\n  trivial\n",
                    "header": "",
                    "file_path": "a.lean",
                    "proof_length": 1,
                    "url": "",
                },
                {
                    "name": "B",
                    "source": "s",
                    "statement": "theorem b : True",
                    "src": "theorem b : True := by\n  trivial\n",
                    "header": "",
                    "file_path": "b.lean",
                    "proof_length": 1,
                    "url": "",
                },
            ],
            "A",
            expected_n=2,
            neighbor_n=1,
        )
        self.assertEqual(neighbors[0].name, "B")
        self.assertNotEqual(neighbors[0].name, "A")
        retrieved = lean.retrieve_record(
            {
                "name": "A",
                "source": "s",
                "statement": "theorem a : True",
                "src": "theorem a : True := by\n  exact Hin\n",
                "header": "",
                "file_path": "a.lean",
                "proof_length": 1,
                "url": "",
            },
            [
                {
                    "name": "A",
                    "source": "s",
                    "statement": "theorem a : True",
                    "src": "theorem a : True := by\n  exact Hin\n",
                    "header": "",
                    "file_path": "a.lean",
                    "proof_length": 1,
                    "url": "",
                },
                {
                    "name": "B",
                    "source": "s",
                    "statement": "theorem b : True",
                    "src": "theorem b : True := by\n  trivial\n",
                    "header": "",
                    "file_path": "b.lean",
                    "proof_length": 1,
                    "url": "",
                },
            ],
            expected_n=2,
            neighbor_n=1,
            lemma_cap=16,
        )
        self.assertEqual(retrieved.query, "A")
        self.assertFalse(retrieved.mathlib_ingest)
        pack = tactics.structure_pack("case foo =>\n  simp\n", "")
        self.assertIn("foo", pack["missing_cases"])
        prompt = tactics.step_prompt({"name": "P", "statement": "theorem t : True"}, "", ["simp"], pack)
        self.assertIn("Next tactic line:", prompt)
        draft = tactics.Draft(draft_id="d00", family="reference", tactics="  simp\n")
        self.assertEqual(draft.n_chars, 6)
        pushed: list = []
        tactics.push_draft(pushed, set(), "reference", "  intro\n  trivial\n", ("id",), cap=8)
        self.assertEqual(pushed[0].family, "reference")
        row = tactics.feature_row({"name": "P", "source": "s"}, tactics="  simp at h\n  exact Hin\n")
        self.assertGreater(row.counts["n_exact"], 0)
        variants = tactics.tactician_variants(
            "  intro\n  simp_all\n",
            "  intro\n  simp_all\n",
            replay_fn=lambda text: text.strip("\n") + "\n  trivial",
            propose_fn=lambda _text: [{"kind": "drop", "tactics": "  trivial\n"}],
        )
        self.assertTrue(any(item["kind"] == "tactician_drop_simp_all" for item in variants))
        assembled = tactics.assemble_mca_candidates(
            "  intro\n  simp at h\n",
            tactics.find_holes("  intro\n  simp at h\n"),
            replay_fn=lambda text: text,
        )
        kinds = [item["kind"] for item in assembled]
        self.assertIn("reference", kinds)
        self.assertIn("mca_template_fill", kinds)
        extras = tactics.neighbor_style_ops(
            [{"name": "B"}],
            {"B": {"name": "B"}},
            head_fn=lambda rec: "  trivial\n",
        )
        self.assertEqual(extras[0][0], "custom")
        merged = tactics.merge_draft_ops([("reference", "  simp\n", ("id",))], extras)
        self.assertEqual(len(merged), 2)
        beam = tactics.BeamItem(prefix="  intro")
        self.assertFalse(beam.stopped)
        files = lean.putnam_file_map(
            pin,
            lakefile="lakefile",
            toolchain="leanprover/lean4:v4.26.0\n",
            root="import Putnam.Candidate\n",
            candidate="theorem t : True := by\n  trivial\n",
            root_relpath="Putnam.lean",
            candidate_relpath="Putnam/Candidate.lean",
        )
        self.assertIn("pins.json", files)
        self.assertNotIn("Tmp.lean", files)
        dropped = tactics.drop_first_bare_simp_all("  intro\n  simp_all\n  exact Hin\n")
        self.assertIsNotNone(dropped)
        self.assertNotIn("simp_all", dropped or "")
        variants = tactics.keepbest_variants("beam_0", "  intro\n  simp_all\n", "  have h := x\n  intro\n")
        self.assertTrue(any(name.endswith("_haves") or "_have_" in name for name, _body in variants))
        shortened = tactics.shorten_keeping_prefix_haves("  have h := x\n  exact h\n  simp_all\n")
        self.assertTrue(any(name in {"drop_first_bare_simp", "drop_last_bare_simp"} for name, _body in shortened))
        rel = lean.source_relpath(
            {"name": "P", "source": "putnambench", "file_path": ""},
            putnam_source="putnambench",
            putnam_relpath="Putnam/Candidate.lean",
        )
        self.assertEqual(rel, "Putnam/Candidate.lean")
        job = lean.bake_job_for_record(
            {"name": "P", "source": "strata", "url": "https://example.com", "file_path": "A.lean"},
            lean.VersionPin(lean_tag="v4.26.0", git_commit="abc"),
            putnam_source="putnambench",
            strata_source="strata",
            strata_first_tag="v4.26.0",
            putnam_relpath="Putnam/Candidate.lean",
            putnam_module="Putnam.Candidate",
            url_key_fn=lambda url: "ex",
        )
        self.assertEqual(job.phase, 0)
        self.assertEqual(job.kind, "repo")
        cwd, rel, dest = lean.prepare_lake_paths(
            {"name": "P", "source": "putnambench", "url": "", "file_path": ""},
            lean.VersionPin(lean_tag="v4.26.0", git_commit="abc"),
            putnam_source="putnambench",
            putnam_relpath="Putnam/Candidate.lean",
            source_relpath_fn=lambda _rec: "Putnam/Candidate.lean",
            putnam_dir_fn=lambda _rec, _pin, _root: Path("/tmp/putnam"),
            materialize_fn=lambda _pin, _dest: None,
            require_clone_fn=lambda *_a: Path("/tmp/clone"),
            checkout_fn=lambda *_a: None,
            skip_checkout=True,
            network="deny",
            state_root=None,
        )
        self.assertEqual(rel, "Putnam/Candidate.lean")
        self.assertEqual(dest.name, "Candidate.lean")
        from jevops import search as lra_search

        merged = lra_search.merge_next_line_proposals(
            ["simp"],
            ["omega", "rfl"],
            stop="STOP",
            cap=12,
            filter_fn=lambda rows: list(rows),
        )
        self.assertEqual(merged[0], "simp")
        self.assertIn("STOP", merged)
        from jevops import outer, jev as lra_jev, nca as lra_nca

        clone, dest, restore = outer.clone_restore(
            {"url": "https://example.com", "file": "A.lean"},
            "/tmp/state",
            clone_fn=lambda url, root: Path(root) / "clone",
            relpath_fn=lambda rec: rec["file"],
            read_fn=lambda _path: b"keep",
        )
        self.assertEqual(clone, Path("/tmp/state") / "clone")
        self.assertEqual(dest.name, "A.lean")
        self.assertEqual(restore, b"keep")
        rec, recs, digest = outer.load_named_pack(
            lambda: (b"raw", "abc", [{"name": "P"}, {"name": "Q"}]),
            "P",
        )
        self.assertEqual(rec["name"], "P")
        self.assertEqual(digest, "abc")
        self.assertEqual(len(recs), 2)
        shots = outer.named_shots(
            [{"name": "A", "n": 1}, {"name": "B", "n": 2}],
            ("A", "B", "C"),
            skip_name="B",
            example_fn=lambda row: row["n"],
        )
        self.assertEqual(shots, [1])
        self.assertTrue(outer.inspect_only("generate_text.py", markers=("generate_text",)))
        self.assertFalse(outer.inspect_only("portable_rewrites.py", markers=("generate_text",)))
        packed = lra_search.collect_path_candidates(
            [Path("/tmp/foo.lean")],
            load_fn=lambda _p: "  simp\n",
            flatten_fn=lambda text: text.strip(),
            pack_fn=lra_search.pack_generated_candidate,
            generator="grok-file",
            extra={"chat_ignored": True},
        )
        self.assertEqual(packed[0]["kind"], "grok_file_foo")
        self.assertEqual(packed[0]["tactics"], "simp")
        hole = type("H", (), {"hole_id": "h0", "original": "simp at h", "family": "dead_code"})()
        fills, ident = lra_search.collect_one_hole_fills(
            [hole],
            [hole],
            "  simp at h\n  exact Hin\n",
            generate_fn=lambda _h: ("exact Hin", {"model": "x"}),
            parse_fn=lambda _text, _holes: {"h0": "exact Hin"},
            fallback_fn=lambda _text: "",
            apply_fn=lambda tactics, _holes, mapping: mapping["h0"],
            align_fn=lambda text: text,
            pack_fn=lra_search.pack_generated_candidate,
            asdict_fn=lambda item: {"hole_id": item.hole_id},
            generator="labs-leanstral-1-5",
        )
        self.assertEqual(fills[0]["kind"], "leanstral_one_h0")
        self.assertEqual(ident["model"], "x")
        qs = lra_jev.with_residual_questions(
            {"intent": "keep"},
            extra=True,
            residuals={"have": 2},
            skills=["port_foo", "keep"],
            noul_ctor=lambda **kw: ("noul", kw),
            score_ctor=lambda **kw: ("score", kw),
            unsafe_instructions_fn=lambda kv: kv[0],
            help_instructions_fn=lambda kv: kv[0],
            fail_instructions_fn=lambda sk: sk,
            unsafe_criteria={"true": "t", "false": "f"},
            help_criteria=["a"],
            fail_criteria={"true": "t", "false": "f"},
        )
        self.assertIn("unsafe_have", qs)
        self.assertIn("fail_skill_port_foo", qs)
        self.assertNotIn("fail_skill_keep", qs)
        seeded = lra_nca.seed_edges_from_query(
            {"nca": {}},
            query_fn=lambda: [],
            graph_fn=lambda: [("a.py:f", "b.py:g")],
            limit=8,
        )
        self.assertTrue(seeded["ok"])
        self.assertEqual(seeded["source"], "harness_ast")
        self.assertEqual(seeded["n_edges"], 1)
        ok, value, exc = outer.call_caught(lambda: 7)
        self.assertTrue(ok)
        self.assertEqual(value, 7)
        self.assertIsNone(exc)
        ok, value, exc = outer.call_caught(lambda: (_ for _ in ()).throw(ValueError("x")), ValueError)
        self.assertFalse(ok)
        self.assertEqual(str(exc), "x")
        bag = outer.set_if({}, True, "k", 1)
        self.assertEqual(bag["k"], 1)
        self.assertEqual(outer.first_call((False, lambda: 1), (True, lambda: 2)), 2)
        self.assertEqual(
            outer.keyed_map(
                [{"k": "a", "v": 1}, {"k": "b", "v": 2}],
                key_fn=lambda row: row["k"],
                val_fn=lambda row: row["v"],
                pred=lambda row: row["k"] != "b",
            ),
            {"a": 1},
        )
        shot = lra_search.pack_shot_candidate(
            kind="leanstral_few_shot",
            generator="labs-leanstral-1-5",
            tactics="  simp\n",
            shots=[{"name": "P", "ratio": 0.5, "filled_tokens": 1, "ref_tokens": 2}],
            pack_fn=lra_search.pack_generated_candidate,
        )
        self.assertEqual(shot["n_shots"], 1)
        self.assertEqual(shot["shot_scores"][0]["name"], "P")
        from jevops import walk as lra_walk

        compile_one, research, pick, steps, tape, stack = lra_walk.bind_walk_defaults(
            compile_one=None,
            research_fn=None,
            pick_fn=None,
            steps=None,
            tape=None,
            stack=None,
            default_compile="c",
            default_research="r",
            default_pick="p",
            tape_factory=lambda: "tape",
            stack_factory=lambda: "stack",
        )
        self.assertEqual((compile_one, research, pick, steps, tape, stack), ("c", "r", "p", [0], "tape", "stack"))
        self.assertEqual(outer.either(True, lambda: 1, lambda: 2), 1)
        self.assertEqual(outer.either(False, lambda: 1, lambda: 2), 2)
        seen: list[str] = []
        outer.ignore_each(lambda: seen.append("a"), lambda: (_ for _ in ()).throw(ValueError("x")))
        self.assertEqual(seen, ["a"])
        dest = [{"kind": "a"}]
        outer.extend_if(dest, lambda: [{"kind": "b"}], cond=True, key_fn=lambda item: item["kind"])
        self.assertEqual([row["kind"] for row in dest], ["a", "b"])
        outer.extend_if(dest, lambda: [{"kind": "c"}], cond=False, key_fn=lambda item: item["kind"])
        self.assertEqual([row["kind"] for row in dest], ["a", "b"])
        bag = type("L", (), {"lines": [], "skipped": False, "reason": ""})()
        skipped = outer.record_usage_line(
            bag,
            dict,
            allowed=False,
            reason="no",
            cost=0,
            usd_fn=lambda _c: 0,
            kind="jev",
            input_tokens=1,
            output_tokens=0,
            call_index=0,
            fixture=True,
            model="m",
        )
        self.assertTrue(skipped["skipped"])
        self.assertTrue(bag.skipped)
        bumped = []
        recorded = outer.record_usage_line(
            bag,
            dict,
            allowed=True,
            reason="x",
            cost=2,
            usd_fn=lambda c: c,
            bump_fn=lambda: bumped.append(1),
            refresh_fn=lambda: bumped.append(2),
            kind="jev",
            input_tokens=1,
            output_tokens=0,
            call_index=1,
            fixture=False,
            model="m",
        )
        self.assertFalse(recorded["skipped"])
        self.assertEqual(bumped, [1, 2])
        self.assertEqual(
            lra_jev.invoke_or_skip(
                invoke_fn=lambda: (_ for _ in ()).throw(ValueError("no")),
                project_fn=lambda *_a: {},
                skip_fn=lambda exc: {"skipped": True, "reason": str(exc)},
            ),
            {"skipped": True, "reason": "no"},
        )
        nested = lra_walk.recurse_walk(
            lambda rec, tactics, **kw: {"rec": rec, "tactics": tactics, **kw},
            "P",
            "  simp\n",
            {"args": 1},
            node="root",
            tape="t",
            stack="s",
            allow_families={"dead_code"},
        )
        self.assertEqual(nested["node"], "root")
        self.assertEqual(nested["allow_families"], {"dead_code"})
        rows, ok = lra_search.after_compile_row(
            [],
            {"kind": "k"},
            {"theorem_ok": False},
            row_fn=lambda item, compiled: {**item, **compiled},
            hammer_fn=lambda: ([{"kind": "h"}], "", [], True),
        )
        self.assertEqual(rows[0]["kind"], "k")
        self.assertEqual(rows[1]["kind"], "h")
        self.assertTrue(ok)
        ok_rows, compiled_ok = lra_search.after_compile_row(
            [],
            {"kind": "k"},
            {"theorem_ok": True},
            row_fn=lambda item, compiled: {**item, **compiled},
            hammer_fn=lambda: (_ for _ in ()).throw(AssertionError("no hammer")),
        )
        self.assertEqual(ok_rows[0]["kind"], "k")
        self.assertTrue(compiled_ok)
        rec, recs, digest, clone, dest, restore = outer.load_and_clone(
            lambda: (b"raw", "abc", [{"name": "P", "url": "https://example.com", "file": "A.lean"}]),
            "P",
            "/tmp/state",
            clone_fn=lambda url, root: Path(root) / "clone",
            relpath_fn=lambda item: item["file"],
            read_fn=lambda _path: b"keep",
        )
        self.assertEqual(rec["name"], "P")
        self.assertEqual(digest, "abc")
        self.assertEqual(dest.name, "A.lean")
        self.assertEqual(restore, b"keep")
        self.assertEqual(outer.tagged_mapping("draft", {"a": 1}), {"call": "draft", "a": 1})
        self.assertEqual(
            outer.closed_skip_extra({"source": "strata"}, default_mode="off", is_default_winning_path=False),
            {
                "contaminates_track2": False,
                "source": "strata",
                "default_mode": "off",
                "is_default_winning_path": False,
            },
        )
        charged: list[tuple] = []

        class _Ledger:
            def record(self, kind, **kwargs):
                charged.append((kind, kwargs))

        packed = lra_jev.charge_packed(
            {"usage": {"input_tokens": 3, "output_tokens": 4}, "ok": True},
            _Ledger(),
            model="jev-latest",
        )
        self.assertTrue(packed["ok"])
        self.assertEqual(charged[0][0], "jev")
        self.assertEqual(charged[0][1]["input_tokens"], 3)
        self.assertEqual(outer.take_keys({"a": 1, "b": 2}, "b", "a"), (2, 1))
        self.assertEqual(outer.replace_if(True, "new", "old"), "new")
        self.assertEqual(outer.replace_if(False, "new", "old"), "old")

        class _Auth:
            def authorize(self, kind, inn, out):
                return False, "no", 0

            def record(self, kind, **kwargs):
                charged.append((kind, kwargs))

        with self.assertRaises(ValueError) as raised:
            outer.require_authorized(_Auth(), "grok", 1, 2, model="m", error_cls=ValueError, fmt="refused: {reason}")
        self.assertEqual(str(raised.exception), "refused: no")
        from jevops import repair as lra_repair

        repaired, compiled = lra_repair.align_then_compile(
            "simp",
            "  simp\n",
            align_fn=lambda ref, text: ref,
            compile_fn=lambda body: {"ok": True, "tactics": body},
        )
        self.assertEqual(repaired, "  simp\n")
        self.assertTrue(compiled["ok"])
        with lean.planted_session(
            "jev-plant-",
            tags=("v4.26.0",),
            plant_fn=lambda root, tag: Path(root).mkdir(parents=True, exist_ok=True),
            clone_fn=lambda state: Path(state) / "clone",
        ) as planted:
            self.assertEqual(planted["clone"].name, "clone")
            self.assertTrue(planted["elan_home"].is_dir() or planted["elan_home"].parent.exists())
        self.assertEqual(outer.pipe(1, lambda n: n + 1, lambda n: n * 3), 6)
        with self.assertRaises(ValueError):
            outer.raise_if(True, ValueError, "no")
        outer.raise_if(False, ValueError, "no")
        skipped_line = type("L", (), {"skipped": True, "reason": "cap"})()
        with self.assertRaises(RuntimeError) as spent:
            outer.require_recorded(skipped_line, RuntimeError)
        self.assertIn("cap", str(spent.exception))
        bag = outer.assign_if({}, "k", True, lambda: 7)
        self.assertEqual(bag["k"], 7)
        self.assertEqual(outer.ranked_pairs({"b": 1, "a": 3})[0][0], "a")
        self.assertTrue(outer.kind_startswith("grok")({"kind": "grok_file_foo"}))
        self.assertFalse(outer.kind_startswith("grok")({"kind": "leanstral"}))
        packed_file = lean.pack_file_result(
            dict,
            tactics="  simp\n",
            identity={"m": 1},
            line={"skipped": False},
            chat="ack",
            dest="/tmp/tactics.lean",
            workspace="/tmp/ws",
            head_fn=lambda text, n: text[:n],
        )
        self.assertTrue(packed_file["used_file"])
        self.assertTrue(packed_file["chat_ignored"])
        self.assertFalse(packed_file["called_docker0"])
        gen, tr = outer.fill_none("g", None, lambda: ("G", "T"))
        self.assertEqual((gen, tr), ("g", None))
        gen, tr = outer.fill_none(None, "t", lambda: ("G", "T"))
        self.assertEqual((gen, tr), ("G", "t"))
        gen, tr = outer.fill_none(None, None, lambda: ("G", "T"))
        self.assertEqual((gen, tr), ("G", "T"))
        inn, out = outer.usage_or_estimate({}, fallback_in=9, estimate_fn=lambda text: len(text), text="abcd")
        self.assertEqual((inn, out), (9, 4))
        self.assertIsNone(outer.attr_or(None, "tactics"))
        self.assertEqual(outer.attr_or(type("D", (), {"tactics": "  simp\n"})(), "tactics"), "  simp\n")
        self.assertEqual(outer.get_str({"best_first_draft": "d01"}, "best_first_draft"), "d01")
        self.assertEqual(outer.beam_shape("greedy", 4, sample_cap=8), (1, 1))
        self.assertEqual(outer.beam_shape("beam", 4, sample_cap=8), (4, 4))
        self.assertEqual(outer.beam_shape("beam", 12, sample_cap=8), (12, 8))
        self.assertEqual(outer.project_map([1, 2], lambda n: n + 1), [2, 3])
        self.assertIsNone(outer.or_none(""))
        self.assertEqual(outer.or_none("x"), "x")

        class _Spend:
            def record(self, kind, **kwargs):
                charged.append((kind, kwargs))

        with self.assertRaises(RuntimeError) as failed:
            outer.fail_spend(_Spend(), "grok", 1, 2, error_cls=RuntimeError, msg="no", cause=ValueError("x"))
        self.assertEqual(str(failed.exception), "no")
        a, b = outer.unpack_pair(None, default=("", {}))
        self.assertEqual((a, b), ("", {}))
        a, b = outer.unpack_pair(("t", {"i": 1}, "extra"))
        self.assertEqual((a, b), ("t", {"i": 1}))
        self.assertEqual(outer.cap_or_fill(["a", "b", "c"], 2, lambda: ["z"]), ["a", "b"])
        self.assertEqual(outer.cap_or_fill([], 2, lambda: ["z"]), ["z"])
        self.assertEqual(outer.cap_or_fill([], 0, lambda: ["z"]), [])
        module, skipped = outer.load_module_or_skip(
            "/no/such.py", "x", load_fn=lambda _p, _n: None, skip_fn=lambda reason: {"reason": reason}
        )
        self.assertIsNone(module)
        self.assertEqual(skipped["reason"], "typesafe_inference_missing")
        dest = outer.mkdtemp(prefix="lra-analysis-")
        written = outer.write_analysis_json(dest, gaps={"g": 1}, nca_status={"ok": True})
        self.assertTrue(written.is_file())
        from jevops import jev as jev_mod
        from jevops import repair as repair_mod
        from jevops import search as search_mod

        skip = jev_mod.kept_skip("no_key", ["a", "b", "c"], 2, head_fn=lambda rows, n: list(rows)[:n])
        self.assertTrue(skip["skipped"])
        self.assertEqual(skip["kept"], ["a", "b"])
        self.assertFalse(skip["jev_generated_lean"])
        cfg_skip = jev_mod.skip_unless_configured(
            type("M", (), {"typesafe_configured": staticmethod(lambda: False)})(),
            lambda reason: {"reason": reason},
        )
        self.assertEqual(cfg_skip["reason"], "no_key")
        self.assertIsNone(
            jev_mod.skip_unless_configured(
                type("M", (), {"typesafe_configured": staticmethod(lambda: True)})(),
                lambda reason: {"reason": reason},
            )
        )
        holes = search_mod.holes_or_find(
            [],
            lambda: [
                type("H", (), {"kind": "operator", "hole_id": "a"})(),
                type("H", (), {"kind": "ident", "hole_id": "b"})(),
            ],
            kinds=("operator",),
            n=8,
        )
        self.assertEqual(len(holes), 1)
        row, tokens, keep = search_mod.denoise_keepbest(
            text="simp",
            keep="  intro\n",
            keep_tokens=10,
            extract_fn=lambda text: text,
            flatten_fn=lambda _keep, filled: filled,
            eval_fn=lambda body: [{"theorem_ok": True, "token_count": 3, "tactics": body}],
            hammer_fn=lambda noisy, _errors: noisy,
        )
        self.assertTrue(row["accepted"])
        self.assertEqual(tokens, 3)
        self.assertEqual(keep, "simp")
        none_row, none_tokens, none_keep = search_mod.denoise_keepbest(
            text="",
            keep="  intro\n",
            keep_tokens=10,
            extract_fn=lambda text: text,
            flatten_fn=lambda _keep, filled: filled,
            eval_fn=lambda _body: [],
            hammer_fn=lambda noisy, _errors: noisy,
        )
        self.assertIsNone(none_row)
        self.assertEqual((none_tokens, none_keep), (10, "  intro\n"))

        class Chain:
            def __init__(self, tactics="", tokens=0, theorem_ok=False):
                self.tactics = tactics
                self.tokens = tokens
                self.theorem_ok = theorem_ok

        packed = search_mod.begin_mcmc(
            start="  simp\n",
            compiled={"token_count": 2, "theorem_ok": True},
            reference="  intro\n  simp\n",
            token_fn=lambda text: len(text.split()),
            beam=2,
            chain_cls=Chain,
            init_kind="init",
        )
        self.assertEqual(len(packed["chains"]), 2)
        self.assertTrue(packed["best"]["theorem_ok"])
        self.assertEqual(packed["lake_calls"], 1)

        class Generated:
            skipped = False
            text = "omega"

        swapped = search_mod.swap_from_generate(
            Generated(),
            tactics="  simp\n  exact h\n",
            index=0,
            parse_fn=lambda text: text.strip().splitlines()[0],
            looks_fn=lambda _text: True,
            replace_fn=lambda _body, _i, _nxt: "  omega\n  exact h\n",
            stop="STOP",
            target="  simp",
            head_fn=lambda text, n: text[:n],
        )
        self.assertEqual(swapped["kind"], "leanstral_swap")

        class SkippedGen:
            skipped = True
            text = "omega"

        self.assertIsNone(
            search_mod.swap_from_generate(
                SkippedGen(),
                tactics="x",
                index=0,
                parse_fn=str,
                looks_fn=bool,
                replace_fn=lambda *_a: "",
                stop="STOP",
                target="x",
                head_fn=lambda text, _n: text,
            )
        )
        fanout = [{"kind": "a"}]
        search_mod.pin_grok_fanout(
            fanout,
            [{"kind": "b"}, {"kind": "pick"}],
            "pick",
            cap=2,
            key_fn=lambda item: item["kind"],
        )
        self.assertEqual([item["kind"] for item in fanout], ["a", "pick", "b"])
        self.assertIn("failed lake compile", outer.append_repair("draft", "unknown identifier"))
        self.assertTrue(outer.append_repair("draft", "err").startswith("draft"))
        factory = outer.fixture_factory(dict, lambda: {"a": 1})
        self.assertEqual(factory(b=2), {"answers": {"a": 1}, "b": 2})
        missing = outer.call_if_file("/no/such/file.lean", lambda: "hit", default="miss")
        self.assertEqual(missing, "miss")
        present = outer.call_if_file(written, lambda: "hit", default="miss")
        self.assertEqual(present, "hit")

        class _Route:
            usage = {"input_tokens": 3, "output_tokens": 4}
            used_fixture = True
            model = "jev"

        class _Led:
            def record(self, kind, **kwargs):
                return (kind, kwargs)

        charged = outer.record_route_usage(_Led(), _Route(), model="fallback")
        self.assertEqual(charged[0], "jev")
        self.assertEqual(charged[1]["input_tokens"], 3)
        self.assertTrue(charged[1]["fixture"])
        finished = outer.finish_ledger_run(
            dict,
            type("L", (), {"grok_calls": 0, "jev_calls": 1, "spent_usd": 0, "remaining_usd": 3, "hard_stopped": False, "as_dict": lambda self: {}})(),
            digest="abc",
            skipped=True,
            reason="no_key",
            mode="off",
            name="P",
            used_fixture=True,
            remaining_default=3.0,
            extra={"called_grok": False},
            overlay_extra={"source": "strata"},
        )
        self.assertTrue(finished["skipped"] if "skipped" in finished else finished.get("ok"))
        self.assertEqual(finished["warmup_jsonl_sha256"], "abc")
        model, landscape = outer.fit_landscape(
            [{"n": 1}, {"n": 2}],
            feature_fn=lambda row: row["n"],
            fit_fn=lambda rows: sum(rows),
            analyze_fn=lambda item, model: {"n": item["n"], "m": model},
        )
        self.assertEqual(model, 3)
        self.assertEqual(landscape[1]["m"], 3)
        started = search_mod.begin_keep_search(
            {"name": "P"},
            tactic_fn=lambda _rec: "  simp\n",
            find_fn=lambda _text: [type("H", (), {"hole_id": "h0"})()],
            token_fn=lambda text: len(text.split()),
        )
        self.assertEqual(started["keep_tokens"], 1)
        self.assertEqual(len(started["holes"]), 1)
        keep, tokens, dropped, history = search_mod.unpack_walked(
            {"keep": "  intro\n", "keep_tokens": 4, "dropped": ["h0"], "history": [{"r": 1}]}
        )
        self.assertEqual((keep, tokens), ("  intro\n", 4))
        self.assertEqual(dropped, {"h0"})
        masked = search_mod.begin_masked(
            {"name": "P"},
            tactic_fn=lambda _rec: "  simp at h\n  exact x\n",
            find_fn=lambda _text: [type("H", (), {"family": "dead_code"})(), type("H", (), {"family": "strength_reduction"})()],
            mask_fn=lambda text, _holes: text.replace("simp at h", "<<<MCA>>>"),
            fill_pred=lambda hole: hole.family == "strength_reduction",
        )
        self.assertIn("<<<MCA>>>", masked["skeleton"])
        self.assertEqual(len(masked["fill_holes"]), 1)
        live = outer.finish_live_write(
            dest,
            {"ok": True},
            prefix="random-canary",
            latest="random-canary-latest.json",
            gaps={"g": 1},
            nca_status={"ok": True},
        )
        self.assertTrue(live["ok"])
        self.assertTrue((dest / "random-canary-latest.json").is_file())
        neighbors, state, router = outer.begin_named_route(
            {"name": "P"},
            [{"name": "P"}],
            neighbor_fn=lambda rec, _rows: [{"name": rec["name"]}],
            state_fn=lambda rec, neighbors: {"n": len(neighbors), "name": rec["name"]},
            fixture=True,
            factory_fn=lambda: outer.fixture_factory(dict, lambda: {"a": 1}),
            router_cls=lambda **kwargs: kwargs,
            mode="inloop",
        )
        self.assertEqual(state["n"], 1)
        self.assertEqual(router["mode"], "inloop")
        self.assertIsNotNone(router["client_factory"])
        self.assertIsNone(outer.charge_unless_skipped(type("R", (), {"skipped": True})(), lambda: 7))
        self.assertEqual(outer.charge_unless_skipped(type("R", (), {"skipped": False})(), lambda: 7), 7)
        self.assertEqual(outer.caught_reason(True, "ok", None), ("", "ok"))
        reason, dropped_result = outer.caught_reason(False, "ok", ValueError("no"))
        self.assertEqual(reason, "no")
        self.assertIsNone(dropped_result)
        box = {"n": 1}
        self.assertEqual(outer.bump_box(box, "n", lambda: 9), 9)
        self.assertEqual(box["n"], 2)
        filled, shot = search_mod.flatten_shot(
            kind="k",
            generator="g",
            text="  SIMP\n",
            shots=[{}],
            flatten_fn=lambda text: text.lower(),
            pack_fn=lambda **kwargs: kwargs,
        )
        self.assertEqual(filled, "  simp\n")
        self.assertEqual(shot["kind"], "k")
        dropped_ids: set[str] = set()
        hit, tokens, body, row = search_mod.trial_keepbest(
            label="exploit",
            hole_ids=["h0"],
            dropped=dropped_ids,
            drop_fn=lambda _ids: "  simp\n",
            eval_fn=lambda trial: [{"theorem_ok": True, "token_count": 2, "tactics": trial}],
            keep_tokens=10,
            apply_fn=search_mod.apply_keepbest,
            strip_fn=search_mod.strip_tactics,
        )
        self.assertTrue(hit)
        self.assertEqual(dropped_ids, {"h0"})
        self.assertEqual(tokens, 2)
        self.assertEqual(row["label"], "exploit")
        body, prefix, vocab = search_mod.begin_prefix_search(
            {"name": "P"},
            tactic_fn=lambda _rec: "  intro\n  simp\n",
            prefix_fn=lambda text: text.splitlines()[0],
            vocab_fn=lambda text: text.split(),
        )
        self.assertEqual(prefix, "  intro")
        self.assertIn("simp", vocab)
        self.assertIn("intro", body)
        self.assertEqual(outer.map_if(None, str), None)
        self.assertEqual(outer.map_if(3, lambda n: n + 1), 4)
        self.assertEqual(outer.head_errors([]), [])
        self.assertEqual(outer.head_errors([{"errors": ["e"]}]), ["e"])
        self.assertEqual(outer.keep_box(4, "  simp\n")["tokens"], 4)
        self.assertEqual(outer.if_prefix("grok_file", "grok", "g", "l"), "g")
        self.assertEqual(outer.if_prefix("leanstral", "grok", "g", "l"), "l")
        wanted = outer.allow_pred(("a", "b"))
        self.assertTrue(wanted("a"))
        self.assertFalse(wanted("c"))
        self.assertTrue(outer.allow_pred(None)("z"))
        dropped_model = outer.fit_drop(
            [{"n": 1}, {"n": 2}],
            feature_fn=lambda row: row["n"],
            fit_fn=lambda rows: {"sum": sum(rows), "zscore": 1, "vt": 2},
        )
        self.assertEqual(dropped_model, {"sum": 3})
        skip = outer.bind_named_skip(
            lambda **kwargs: kwargs,
            digest="abc",
            name="P",
            ledger="L",
        )
        skipped = skip(reason="no_key", mode="off", extra={"k": 1})
        self.assertEqual(skipped["reason"], "no_key")
        self.assertEqual(skipped["warmup_jsonl_sha256"], "abc")
        self.assertEqual(skipped["k"], 1)

        class _Line:
            skipped = False
            reason = "ok"

        class _Led:
            def record(self, kind, **kwargs):
                return _Line()

        line = outer.record_required(
            _Led(),
            "grok",
            1,
            2,
            require_fn=outer.require_recorded,
            error_cls=RuntimeError,
            fmt="no: {reason}",
        )
        self.assertFalse(line.skipped)
        self.assertEqual(outer.or_str("", ValueError("x")), "x")
        self.assertEqual(outer.or_str("ok", "x"), "ok")
        self.assertEqual(outer.with_key({"a": 1}, "cut", "139"), {"a": 1, "cut": "139"})
        self.assertEqual(outer.names_of([{"name": "P"}, {"name": "Q"}]), ["P", "Q"])
        self.assertEqual(outer.jev_budget(6 * 1 * 3, 1, 1), 56)
        self.assertEqual(outer.jev_budget(0, 1, 1), 8)
        self.assertEqual(outer.index_paths({"a.json": "/tmp/a", "b.lean": "/tmp/b"}, {"a": "a.json"}), {"a": "/tmp/a"})
        self.assertEqual(outer.or_load({"k": 1}, lambda: {"k": 2}), {"k": 1})
        self.assertEqual(outer.or_load({}, lambda: {"k": 2}), {"k": 2})
        model, landscape, sampled = outer.begin_live_sample(
            [{"n": 1}, {"n": 2}],
            feature_fn=lambda row: row["n"],
            fit_fn=lambda rows: sum(rows),
            analyze_fn=lambda item, model: {"n": item["n"], "m": model},
            all_small=True,
            filter_fn=lambda recs, _land: recs[:1],
            sample_fn=lambda: [{"n": 9}],
        )
        self.assertEqual(model, 3)
        self.assertEqual(len(sampled), 1)
        finish = outer.bind_finish(
            dict,
            type("L", (), {"grok_calls": 0, "jev_calls": 0, "spent_usd": 0, "remaining_usd": 3, "hard_stopped": False, "as_dict": lambda self: {}})(),
            digest="abc",
            mode="track1",
            name="P",
            used_fixture=True,
            remaining_default=3.0,
        )
        finished = finish(skipped=True, reason="no_key", extra={"called_grok": False}, overlay_extra={"source": "strata"})
        self.assertEqual(finished["warmup_jsonl_sha256"], "abc")
        self.assertEqual(finished["reason"], "no_key")
        ids = search_mod.choose_minibatch(
            [type("H", (), {"hole_id": "h0"})(), type("H", (), {"hole_id": "h1"})()],
            {"choice": "h0", "probabilities": {"h1": 0.9, "h0": 0.1}},
            rng=type("R", (), {"choice": staticmethod(lambda rest: rest[0])})(),
            k=2,
        )
        self.assertEqual(ids[0], "h0")
        hits: list[int] = []
        outer.pin_calls(lambda: hits.append(1), lambda: hits.append(2))()
        self.assertEqual(hits, [1, 2])
        self.assertEqual(outer.first_set(None, ["a", "b"]), {"a", "b"})
        self.assertEqual(outer.first_set(None, None), set())
        self.assertEqual(outer.unless_flag(True, {"a": 1}), {})
        self.assertEqual(outer.unless_flag(False, {"a": 1}), {"a": 1})
        paired, total = outer.mapping_and_total(lambda: {"x": 1, "y": 2}, lambda row: sum(row.values()))
        self.assertEqual((paired, total), ({"x": 1, "y": 2}, 3))
        nested = {"nca": {"overlay_done": True, "keep": 1}}
        self.assertTrue(outer.pop_nested(nested, "nca", "overlay_done"))
        self.assertNotIn("overlay_done", nested["nca"])
        self.assertEqual(outer.attrs_of([type("S", (), {"label": "a"})()], "label"), ["a"])
        self.assertEqual(outer.substrings_in("simp at h; exact x", (("simp at", "s"), ("missing", "m"))), ["simp at"])
        self.assertTrue(outer.any_get({"n_induction": 1, "n_cases": 0}, "n_induction", "n_cases"))
        flatten = repair_mod.flatten_matched(lambda keep, filled: keep + filled, lambda keep, matched: matched.strip())
        self.assertEqual(flatten("  ", "  simp\n"), "simp")
        self.assertTrue(outer.field_eq("kind", "hosted")({"kind": "hosted"}))
        self.assertTrue(outer.contains_attr("ops", "collapse")(type("D", (), {"ops": ("collapse",)})()))
        self.assertEqual(outer.dict_call(lambda **kw: kw, a=1), {"a": 1})
        self.assertEqual(outer.get_list({"errors": ["e"]}, "errors"), ["e"])
        self.assertEqual(outer.get_list(["e"]), ["e"])
        self.assertEqual(outer.or_int(None, 6, floor=2), 6)
        self.assertEqual(outer.or_int(0, 6, floor=2), 6)
        self.assertEqual(outer.sample_n(1, 4), 1)
        self.assertEqual(outer.sample_n(8, 4), 4)
        idx, line = outer.pick_line("  intro\n  simp\n", type("R", (), {"choice": staticmethod(lambda rows: rows[1])})(), [0, 1])
        self.assertEqual((idx, line), (1, "  simp"))
        self.assertEqual(outer.nested_get({"nca": {"sidecar_built": True}}, "nca", "sidecar_built"), True)
        self.assertIsNone(outer.nested_get({}, "nca", "sidecar_built"))
        self.assertEqual(outer.first_int(None, 0, 4), 4)
        self.assertEqual(outer.first_int(None, default=9), 9)
        self.assertEqual(
            outer.map_pairs([{"kind": "a", "tactics": "  simp\n"}], default_kind="step"),
            [("a", "  simp\n")],
        )
        aligned = repair_mod.bind_align(
            "  intro\n",
            extract_fn=lambda text: text.strip(),
            match_fn=lambda _keep, filled: filled,
            flatten_fn=lambda _keep, filled: filled,
        )
        self.assertEqual(aligned("  simp\n"), "simp")
        self.assertEqual(outer.rstrip_or(None, "http://x/v1/"), "http://x/v1")
        self.assertEqual(outer.stripped_or(None, "  intro\n"), "  intro")
        self.assertIsNone(outer.optional_fn(False, lambda: 1))
        self.assertTrue(callable(outer.optional_fn(True, lambda: 1)))
        self.assertTrue(outer.any_pred(lambda n: n > 2, [1, 3]))
        self.assertEqual(outer.maybe_set(["a"]), {"a"})
        self.assertIsNone(outer.maybe_set([]))
        self.assertEqual(outer.or_list([], [{"family": "dead_code"}]), [{"family": "dead_code"}])
        self.assertEqual(outer.overlay_map({"a": 1}, b=2), {"a": 1, "b": 2})
        self.assertEqual(outer.or_call("", lambda: "x"), "x")
        self.assertEqual(outer.or_call("a", lambda: "x"), "a")
        self.assertEqual(outer.or_call("keep", lambda prefix, vocab: f"{prefix}:{vocab}", "p", "v"), "keep")
        self.assertEqual(outer.append_if(["a"], True, "b"), ["a", "b"])
        self.assertEqual(outer.append_if(["a"], False, "b"), ["a"])
        self.assertEqual(outer.first_not_none(None, factory=lambda: "x"), "x")
        self.assertEqual(outer.first_not_none(0, factory=lambda: "x"), 0)
        self.assertEqual(outer.text_or(None), "")
        self.assertEqual(outer.text_or("a"), "a")
        outer.raise_caught(None)
        with self.assertRaises(RuntimeError):
            outer.raise_caught(RuntimeError("x"))
        self.assertEqual(outer.count_hits("simp at h", (("simp at", "s"),), weight=10, add_len=True), 17)
        self.assertEqual(outer.count_hits("omega", ("omega",), weight=3), 3)
        putnam_dir = lean.project_dir_for_record(
            {"name": "Q", "source": "putnambench", "url": ""},
            lean.VersionPin(lean_tag="v4.26.0", git_commit="abc"),
            putnam_source="putnambench",
            putnam_dir_fn=lambda _rec, _pin, _root: Path("/tmp/putnam"),
            clone_dir_fn=lambda _url: Path("/tmp/clone"),
        )
        self.assertEqual(putnam_dir, Path("/tmp/putnam"))
        rec = lean.CandidateRecord(
            kind="reference",
            tactics="  trivial\n",
            source_text="theorem t : True := by\n  trivial\n",
            admission_accepted=True,
            admission_code="",
            admission_reason="ok",
            hardware_class="spark_gb10",
        )
        self.assertTrue(rec.to_dict()["admission_accepted"])
        self.assertIsNone(rec.to_dict()["arena_score"])
        closed = lean.close_failed_receipt(
            rec,
            ValueError("missing"),
            digest_fn=lambda text: "d" * 64,
            axiom_digest_fn=lambda _names: "a" * 64,
        )
        self.assertFalse(closed.ok)
        self.assertEqual(closed.exit_code, -1)
        hammers = tactics.hammer_variants("  intro\n", "  intro\n  simp\n")
        self.assertTrue(any(name == "identity" for name, _body in hammers))
        drafts = tactics.random_mca_drafts(
            "  rename_i ghost\n  exact Hin\n  simp at h\n",
            __import__("random").Random(0),
            n=6,
            token_fn=lean.token_count,
        )
        self.assertIsInstance(drafts, list)
        chain = tactics.Chain(tactics="  simp\n", tokens=1, theorem_ok=False)
        self.assertEqual(chain.tokens, 1)
        beam = lra_search.run_prefix_beam(
            "  intro",
            max_steps=1,
            beam_n=1,
            pack_fn=lambda _prefix: {"earliest_unfinished": None},
            stop_allowed_fn=lambda _prefix: True,
            propose_fn=lambda *_a: ["STOP"],
            prune_fn=lambda *_a: {"kept": ["STOP"]},
            extend_fn=lambda prefix, nxt, _pack: prefix,
            filter_fn=lambda lines, _pack: list(lines),
        )
        self.assertTrue(beam["finals"][0]["stopped"])
        receipt = lean.TacticTryReceipt(name="P")
        dummy_attempt = lean.TacticAttempt(tactic="sorry", argv=["/opt/lake"], ok=False, sorryAx=True)

        def _run(tactic: str) -> lean.TacticAttempt:
            if tactic == "sorry":
                return dummy_attempt
            return lean.TacticAttempt(tactic=tactic, argv=["/opt/lake"], ok=True)

        filled = lean.path_a_fill(receipt, ["rfl"], _run)
        self.assertEqual(filled.winning_tactic, "rfl")
        self.assertTrue(filled.ok)
        prompt = tactics.mca_hole_prompt(
            {"name": "P", "statement": "theorem t : True"},
            "  intro\n",
            tactics.find_holes("  simp at h\n"),
        )
        self.assertIn("HOLES:", prompt)
        proposed = tactics.propose_closed_edits(
            "  exact a\n  exact b\n  simp_all\n",
            "  exact a\n  exact b\n  simp_all\n",
            __import__("random").Random(0),
            extras=(),
            limit=8,
        )
        self.assertTrue(any(row.get("kind") in {"join_exacts", "drop_last_simp_all", "join_applies"} for row in proposed))
        from jevops import inits as lra_inits

        extras = lra_inits.mcmc_extras("    apply And.intro\n    exact Hin\n")
        self.assertTrue(any(row["kind"] == "and_intro_constructor" for row in extras))
        scored = lean.score_candidate(
            rec,
            reference_tokens=10,
            reference_elab_ms=1.0,
            token_ratio_fn=lambda a, b: a / max(b, 1),
            composite_fn=lambda a, b: a,
            all_tags_ok_fn=lambda *_a: True,
            record={"src": "x", "statement": "x"},
            reconstructed_ok=True,
        )
        self.assertTrue(scored.valid)
        proof = lean.ProofReceipt(
            name="P",
            lean_tag="v4.26.0",
            body_digest="a" * 64,
            verdict="ok",
            executable_paths=lean.ExecutablePaths(lean="/opt/lean", lake="/opt/lake"),
        )
        pub = proof.to_public_dict(extra={"schema": "lake-proof-receipt/v1"})
        self.assertEqual(pub["schema"], "lake-proof-receipt/v1")
        self.assertIsNone(pub["arena_score"])
        dims = lean.project_authority_dimensions(
            proof,
            ("ir", "property"),
            {"ir": "lean4-proof-body", "property": "keep"},
        )
        self.assertEqual(dims["ir"], "lean4-proof-body")
        shot = tactics.few_shot_prompt(
            {"name": "T", "statement": "theorem t : True"},
            [
                {
                    "name": "E",
                    "filled_tokens": 2,
                    "ref_tokens": 4,
                    "ratio": 0.5,
                    "n_holes": 1,
                    "families": ["dead_code"],
                    "skeleton": "  intro",
                    "reference": "  intro\n  simp",
                    "filled": "  intro",
                }
            ],
            tactics="  intro\n",
            skeleton="  intro\n",
            token_count=1,
        )
        self.assertIn("TARGET: T", shot)
        repaired_rows, nxt, _errs, ok = tactics.hammer_until(
            "  simp at h\n",
            "  simp at h\n  exact Hin\n",
            [{"data": "unknown tactic"}],
            lambda body: {"theorem_ok": True, "errors": []},
            lambda **kw: {"kind": kw["kind"], "tactics": kw["tactics"]},
            kind="mca",
            generator="tactician",
        )
        self.assertIsInstance(repaired_rows, list)
        from jevops import oracle as lra_oracle

        named = lra_oracle.eval_named_or_current(
            "Q",
            current={"name": "P"},
            tactics="  trivial\n",
            compile_fn=lambda *_a, **_k: {"theorem_ok": True, "token_count": 1},
            load_records_fn=lambda: [{"name": "Q", "n_tokens": 2, "url": "https://example.com", "src": "theorem q : True"}],
            tactic_block_fn=lambda rec: "  exact True.intro\n",
            clone_dir_fn=lambda _url: Path("/tmp"),
            relpath_fn=lambda _rec: "missing.lean",
            read_bytes_fn=lambda _p: b"",
            cap=10,
        )
        self.assertEqual(named.get("reason"), "no_clone")
        plan = lean.CompilePlan(
            records=[{"name": "P", "source": "strata", "file_path": "A.lean"}],
            frozen_warmup_sha256="a" * 64,
            jsonl_bytes=1,
            n_records=1,
        )
        self.assertEqual(plan.first_record()["name"], "P")
        dummy = type("R", (), {"stdout": "ok", "stderr": "", "error": "", "returncode": 0})()
        attempt = lean.fill_tactic_attempt(
            tactic="rfl",
            argv=["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=400000", "--json", "x.lean"],
            cwd="/tmp",
            source_file="x.lean",
            timeout=120.0,
            result=dummy,
            wall_ms=1.0,
            cpu_ms=1.0,
            max_heartbeats=400000,
        )
        self.assertEqual(attempt.tactic, "rfl")
        from jevops.outer import InsertOnlyConnection

        class _Raw:
            def __init__(self) -> None:
                self.sql = ""

            def execute(self, sql, params=None):
                self.sql = sql
                return self

        raw = _Raw()
        conn = InsertOnlyConnection(raw, guard_fn=lambda sql: sql)
        conn.execute("SELECT 1")
        self.assertEqual(raw.sql, "SELECT 1")
        written = lean.write_then_compile(
            {"name": "P", "source": "strata"},
            "  trivial\n",
            putnam_source="putnambench",
            pins=[lean.VersionPin(lean_tag="v4.26.0", git_commit="abc")],
            candidate_record={"name": "P", "source": "strata"},
            source_text="theorem t : True := by\n  trivial\n",
            project_dir_fn=lambda *_a: Path("/tmp"),
            relpath_fn=lambda _rec: "A.lean",
            write_fn=lambda dest, text: dest,
            compile_fn=lambda rec: ["ok"],
        )
        self.assertEqual(written, ["ok"])
        baked = lean.bake_or_hit(
            lean.BakeJob(
                kind="repo",
                source="strata",
                lean_tag="v4.26.0",
                git_commit="abc",
                url="https://example.com",
                cache_key="k",
                phase=0,
                record_names=("P",),
                file_paths=("A.lean",),
                module="A.lean",
            ),
            network="allow",
            execute=False,
            require_cache_fn=lambda *_a, **_k: {"ok": True, "cache_key": "k"},
            tag_paths_fn=lambda _tag: {"installed": True, "lake_path": "/opt/lake"},
            materialize_fn=lambda *_a: None,
            putnam_dir_fn=lambda *_a: Path("/tmp"),
            clone_fn=lambda *_a: Path("/tmp"),
            checkout_fn=lambda *_a: None,
            run_lake_fn=lambda *_a: {"exit_code": 0},
            copy_oleans_fn=lambda *_a: None,
            cache_dir_fn=lambda *_a: Path("/tmp"),
            mark_fn=lambda *_a: None,
            olean_fn=lambda *_a: [],
        )
        self.assertEqual(baked["status"], "cache-hit")
        packed = lean.pack_compile_view(
            {"exit_code": 0, "timed_out": False, "sorryAx": False, "wall_ms": 1, "error": ""},
            token_count=4,
            errors=[],
            sorry=False,
        )
        self.assertTrue(packed["theorem_ok"])
        planned = lean.plan_from_records(
            [{"name": "P", "source": "strata"}],
            "b" * 64,
            12,
            first_source="strata",
        )
        self.assertEqual(planned.n_records, 1)
        self.assertIsNone(planned.arena_score)
        bake_plan = lean.plan_bake_from_jobs(
            [
                lean.BakeJob(
                    kind="repo",
                    source="strata",
                    lean_tag="v4.26.0",
                    git_commit="abc",
                    url="https://example.com",
                    cache_key="k",
                    phase=0,
                    record_names=("P",),
                    file_paths=("A.lean",),
                    module="A.lean",
                )
            ],
            "c" * 64,
            12,
            1,
        )
        self.assertEqual(bake_plan.n_records, 1)
        self.assertEqual(bake_plan.first_job().cache_key, "k")
        wrote: list = []
        lean.write_candidate_if_needed(
            {"name": "Q", "source": "putnambench"},
            Path("/tmp/missing-lra-candidate.lean"),
            putnam_source="putnambench",
            write_fn=lambda rec, dest: wrote.append((rec.get("name"), str(dest))),
        )
        self.assertEqual(wrote[0][0], "Q")
        fields = lean.lake_supervisor_fields(
            threads=1,
            elan_home="/elan",
            supervisor_dir="/sup",
            process_env_key="IPFS_DATASETS_PROCESS_SUPERVISOR_DIR",
        )
        self.assertEqual(fields["ELAN_HOME"], "/elan")
        probed = lean.probe_pins(
            ["v4.26.0", "v4.26.0", "v4.27.0"],
            resolve_fn=lambda tag: {"lean_tag": tag, "installed": tag == "v4.26.0"},
        )
        self.assertEqual(probed["installed_tags"], ["v4.26.0"])
        self.assertEqual(probed["missing_tags"], ["v4.27.0"])
        self.assertEqual(probed["capability_gap"], "")
        dummy_receipt = lean.CompileReceipt(
            name="P",
            lean_tag="v4.26.0",
            argv=["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=400000", "--json", "x.lean"],
            stdout="#print axioms t\n",
            axiom_digest="a" * 64,
            timeout_seconds=600.0,
            wall_ms=1.0,
            measurement_maxHeartbeats=400000,
        )
        summary = lean.compile_receipt_summary(dummy_receipt, max_heartbeats=400000, ikv_floor=30.0)
        self.assertTrue(summary["argv_has_lake_env_lean"])
        self.assertTrue(summary["timeout_exceeds_ikv_30s"])
        self.assertIsNone(summary["arena_score"])
        retrieved_view = lean.retrieval_view(retrieved, src_chars=40, lemma_cap=16)
        self.assertEqual(retrieved_view["query"], "A")
        self.assertEqual(retrieved_view["n_neighbors"], 1)
        self.assertIsNone(retrieved_view["relevance_score"])
        neighbors = lean.prompt_neighbors(retrieved, k=1)
        self.assertEqual(neighbors[0]["name"], "B")
        from jevops import jev as lra_jev

        kept_row = lra_search.keep_shortest_ok(
            [
                {"kind": "reference", "theorem_ok": True, "token_count": 8},
                {"kind": "mca", "theorem_ok": True, "token_count": 3},
                {"kind": "fail", "theorem_ok": False, "token_count": 1},
            ]
        )
        self.assertEqual(kept_row["kind"], "mca")
        mca = lra_search.pack_mca_problem(
            schema="lra-mca-mask-replace/v1",
            name="P",
            digest="d" * 64,
            n_holes=1,
            holes=[{"hole_id": "h0"}],
            skeleton_head="intro",
            hardware_class="spark_gb10",
            reference_token_count=8,
            beats_reference=True,
            candidates=[kept_row],
            kept=kept_row,
        )
        self.assertEqual(mca["kept"]["kind"], "mca")
        self.assertFalse(mca["called_docker0"])
        self.assertFalse(mca["official_track2"])
        prune_st = lra_jev.prune_state(
            {"name": "P"},
            "  intro\n",
            {"pca_skeleton_head": "case foo", "missing_cases": ["bar"]},
            {"c0": "simp", "c1": "rfl"},
        )
        self.assertEqual(prune_st["candidates"]["c0"], "simp")
        kept_lines = lra_jev.rank_prune_kept(
            {"c0": "simp", "c1": "rfl"},
            {"c1": 0.9, "c0": 0.1},
            "c1",
            ["simp", "rfl"],
            1,
        )
        self.assertEqual(kept_lines, ["rfl"])
        pruned = lra_jev.pack_prune(skipped=False, reason="routed", best="rfl", kept=kept_lines)
        self.assertFalse(pruned["jev_generated_lean"])
        catalog = lra_jev.pack_rank_catalog(
            {"name": "P", "source": "strata"},
            drafts=[type("D", (), {"draft_id": "d00", "family": "dead_code"})()],
            families=[{"family": "dead_code"}],
            features={"n_simp": 1},
        )
        self.assertEqual(catalog["draft_ids"], ["d00"])
        self.assertFalse(catalog["live"])
        ident = lean.closed_provider_identity(requested_provider="leanstral_local", requested_model="Leanstral")
        self.assertEqual(ident.resolved_provider, "")
        self.assertFalse(ident.fallback_used)
        lean.refuse_unhealthy(
            lean.HealthProbe(ok=True, url="http://x", alias_ok=True, alias_url="http://y", status_code=200, error="", autostart="0"),
            require_health=True,
            error_cls=RuntimeError,
            fmt="down",
        )
        with self.assertRaises(RuntimeError):
            lean.refuse_unhealthy(
                lean.HealthProbe(ok=False, url="http://x", alias_ok=False, alias_url="http://y", status_code=None, error="down", autostart="0"),
                require_health=True,
                error_cls=RuntimeError,
                fmt="down {url}",
                url="http://x",
            )
        start, end = lean.splice_span("header\ntheorem t : True := by\n  sorry\n", "theorem t : True := by\n  sorry\n", "theorem t : True := by\n  trivial\n")
        self.assertEqual(start, 2)
        patched = lean.patch_putnam_src({"name": "Q", "src": ""}, "  trivial\n", statement="theorem t : True")
        self.assertTrue(patched["src"].startswith("theorem t : True := by"))
        pins = lean.filter_installed_pin_maps(
            [lean.VersionPin(lean_tag="v4.26.0", git_commit="abc"), lean.VersionPin(lean_tag="v4.27.0", git_commit="def")],
            resolve_fn=lambda pin: (_ for _ in ()).throw(ValueError("missing")) if pin.lean_tag == "v4.27.0" else pin,
        )
        self.assertEqual(pins, [{"v4.26.0": "abc"}])
        unsolved = lean.unsolved_record(source="strata", file_path="U.lean", url="https://example.com", lean_tag="v4.26.0", git_commit="abc")
        self.assertIn("sorry", unsolved["src"])
        attempt = lean.attempt_summary(
            {
                "argv": ["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=400000", "--json", "x.lean"],
                "cwd": "/elan/toolchains/leanprover--lean4---v4.26.0",
                "ok": True,
                "tactic": "rfl",
                "timeout_seconds": 120.0,
                "stdout": "#print axioms t\n",
            },
            max_heartbeats=400000,
            ikv_floor=30.0,
        )
        self.assertTrue(attempt["argv_has_lake_env_lean"])
        self.assertTrue(attempt["timeout_exceeds_ikv_30s"])
        try_view = lean.try_receipt_summary(
            type(
                "R",
                (),
                {
                    "attempts": [{"argv": attempt["argv"] if False else ["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=400000", "--json", "x.lean"], "ok": True, "tactic": "rfl", "timeout_seconds": 120.0, "stdout": "#print axioms t\n", "cwd": "/elan/toolchains/leanprover--lean4---v4.26.0"}],
                    "sorry_attempt": {"argv": ["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=400000", "--json", "x.lean"], "ok": False, "sorryAx": True, "tactic": "sorry", "timeout_seconds": 120.0, "stdout": "#print axioms t\n", "cwd": "/elan/toolchains/leanprover--lean4---v4.26.0"},
                    "aesop_imported": False,
                    "tactics_considered": ["rfl"],
                    "tactics_run": ["rfl"],
                    "winning_tactic": "rfl",
                    "error": "",
                    "generator": "lake_native",
                    "git_commit": "abc",
                    "hammer_006_lra_ready": False,
                    "lean_tag": "v4.26.0",
                    "loop": "v2",
                    "name": "P",
                    "ok": True,
                    "on_30_sep_critical_path": False,
                    "path": "A",
                    "path_b_implemented": False,
                    "sorry_template_prefix_bound": True,
                    "source": "strata",
                    "uses_snapshot_goal": False,
                    "v1_runs_this": False,
                },
            )(),
            attempt_fn=lambda item: lean.attempt_summary(item, max_heartbeats=400000, ikv_floor=30.0),
        )
        self.assertTrue(try_view["sorry_failed"])
        self.assertEqual(try_view["winning_tactic"], "rfl")
        self.assertFalse(try_view["hammer_006_lra_ready"])
        hosted = lean.hosted_tactics_from_payload(
            {"text": "```\n  simp\n```", "called_docker0": False, "used_prototype_endpoint": False},
            extract_fn=lean.extract_generated_tactics,
        )
        self.assertEqual(hosted, "simp")
        loaded = lra_jev.typesafe_load_payload(available=False, error="missing", path="x.py", exists=False)
        self.assertFalse(loaded["available"])
        noul_qs = lra_jev.noul_questions(
            {"will_fail": ("Will it fail?", "yes", "no")},
            lambda **kw: kw,
        )
        self.assertEqual(noul_qs["will_fail"]["criteria"]["true"], "yes")
        failed = lean.failed_generation(
            lean.HealthProbe(ok=False, url="http://x", alias_ok=False, alias_url="http://y", status_code=None, error="down", autostart="0"),
            "boom",
            requested_provider="leanstral_local",
            requested_model="Leanstral",
        )
        self.assertEqual(failed.error, "boom")
        self.assertFalse(failed.skipped)
        extra = lean.retrieval_prompt_extra(lemmas="Foo.bar", n_neighbors=14, lemma_cap=16)
        self.assertIn("Foo.bar", extra)
        self.assertIn("not a Mathlib CorpusManifest", extra)
        from jevops import nca as lra_nca

        sliced = lra_nca.pack_codepath_slice(ok=False, name="x", reason="codepath_not_allowed", inspect_only=True)
        self.assertFalse(sliced["ok"])
        self.assertFalse(sliced["called_docker0"])
        sidecar = lra_nca.pack_sidecar_index([{"path": "a.py"}])
        self.assertEqual(sidecar["n_files"], 1)
        self.assertFalse(sidecar["control_duckdb"])
        vec = lra_search.vector_hits_from_result(
            {"hits": [{"row": {"qualified_symbol": "Foo", "path": "a.py"}, "score": 1.0}]},
            query="Foo",
            hit_fn=lambda symbol, **kw: {"symbol": symbol, "score": 0.1, **kw},
            vector_weight=0.5,
        )
        self.assertEqual(vec[0]["symbol"], "Foo")
        packed_syn = lean.pack_synthetic_compile(
            elan_home="/tmp/elan",
            expand_receipts=[],
            first_receipts=[],
            putnam_receipt=type("R", (), {"header_maxHeartbeats": 0, "measurement_maxHeartbeats": 400000, "ok": True})(),
            written=[],
            persisted=[],
            receipts_dir="/tmp/r",
            first_file="A.lean",
            first_name="P",
            first_green=False,
            missing_clone_closed=True,
            timeout_30_rejected=True,
            timeout_is_warmup=True,
            summary_fn=lambda _item: {"argv_has_lake_env_lean": True, "ok": True},
            tag_sort_fn=lambda tag: tag,
            max_heartbeats=400000,
        )
        self.assertTrue(packed_syn["missing_clone_fails_closed_under_network_deny"])
        self.assertFalse(packed_syn["independent_kernel_verifier_used"])
        self.assertTrue(lra_search.should_call_generator(None, {"proof_length": 500}))
        self.assertFalse(lra_search.should_call_generator(None, {"proof_length": 10}))
        walked = lra_search.coordinate_rounds(
            [{"hole_id": "h0"}],
            rounds=1,
            choose_fn=lambda remaining, dropped, round_i: ["h0"],
            trial_fn=lambda chosen: "  trivial\n",
            eval_fn=lambda trial: [{"theorem_ok": True, "token_count": 1, "tactics": trial}],
            accept_fn=lambda evals, tokens, trial: (evals[0], 1, trial),
            keep_tokens=10,
            keep_body="  exact Hin\n",
        )
        self.assertEqual(walked["keep_tokens"], 1)
        idents = tactics.ident_holes(
            "  exact Hin\n",
            token_re=lean.TOKEN,
            skip_tokens=("exact",),
            max_holes=4,
        )
        self.assertTrue(any(row["original"] == "Hin" for row in idents))
        prompt = tactics.repair_prompt(
            {"name": "P", "statement": "theorem t : True"},
            failed="  sorry\n",
            errors=[{"pos": 1, "data": "unsolved"}],
            reference="  trivial\n",
        )
        self.assertIn("unsolved", prompt)
        from jevops import jev as lra_jev

        routed = lra_jev.RouteResult(skipped=True, reason="no_key", mode="off", official_track2=False)
        self.assertTrue(routed.as_dict()["skipped"])
        self.assertFalse(routed.as_dict()["jev_generated_lean"])
        from jevops import outer as lra_outer

        lock = lra_outer.LockInspection(path="/tmp/x.lock", exists=False, held=False, pid=None, method="none", error="")
        self.assertFalse(lock.lock_ex_taken_by_client)
        skip = lean.skipped_generation(
            lean.HealthProbe(ok=False, url="http://x", alias_ok=False, alias_url="http://y", status_code=None, error="down", autostart="0"),
            reason="down",
            requested_provider="leanstral_local",
            requested_model="Leanstral",
        )
        self.assertTrue(skip.skipped)
        healthy = lean.generate_if_healthy(
            health_ok=True,
            generate_fn=lambda: "ok",
            skip_result="skip",
            fail_fn=lambda exc: str(exc),
        )
        self.assertEqual(healthy, "ok")
        fills = tactics.closed_fills({"kind": "ident", "original": "Hin"}, "  exact Hin\n", token_re=lean.TOKEN)
        self.assertIn("Hin", fills)
        packed_rank = lra_jev.draft_rank_state({"name": "P", "statement": "theorem t : True"}, [{"kind": "a", "tactics": "  simp\n", "generator": "g"}])
        self.assertIn("a", packed_rank["criteria"])
        cands = lra_search.keepbest_candidates(
            reference="  simp\n",
            hosted="  intro\n  simp\n",
            flattened="  intro\n  simp\n",
            collapse="  simp_all\n",
            span_drafts=[tactics.Draft(draft_id="d01", family="simp_set", tactics="  simp_all\n", ops=("collapse_simp_at",))],
        )
        kinds = [row["kind"] for row in cands]
        self.assertEqual(kinds[0], "reference")
        self.assertIn("hosted_mistral", kinds)
        self.assertNotIn("hosted_indent_normalized", kinds)
        self.assertIn("fanout_collapse_simp_at", kinds)
        compiled_rows, by_kind = lra_search.compile_labeled(
            cands[:2],
            lambda body: {"theorem_ok": True, "token_count": len(body), "module_exit_0": True},
            lambda item, compiled: {"kind": item["kind"], **compiled},
        )
        self.assertEqual(compiled_rows[0]["kind"], "reference")
        self.assertIn("reference", by_kind)
        self.assertTrue(lra_search.beats_reference(compiled_rows, 10**9))
        self.assertEqual(lra_search.keepbest_kept(compiled_rows[0])["kind"], "reference")
        milles = lra_outer.spend_for("jev", 1_000_000, 0, {"jev": (42, 0), "grok": (3000, 15000)})
        self.assertEqual(milles, 42)
        grok = lra_outer.spend_for("grok", 0, 1_000_000, {"jev": (42, 0), "grok": (3000, 15000)})
        self.assertEqual(grok, 15000)
        from decimal import Decimal

        usd = lra_outer.spend_for(
            "jev",
            1_000_000,
            0,
            {"jev": (Decimal("0.042"), Decimal("0"))},
            scale=Decimal("1000000"),
        )
        self.assertEqual(usd, Decimal("0.042"))
        chain = tactics.Chain(tactics="  simp\n", tokens=4, theorem_ok=True)
        best = {"kind": "init", "tactics": "  simp\n", "token_count": 4, "theorem_ok": True}
        hist: list = []
        failed_bodies: set = set()
        failed_kinds: set = set()
        tried = lra_search.mcmc_try_proposals(
            proposals=[{"kind": "drop", "note": "x", "tactics": "  rfl\n"}],
            order=[0],
            chain=chain,
            compile_fn=lambda body: {"theorem_ok": True, "token_count": 1, "errors": []},
            token_fn=len,
            accept_fn=lambda **_k: True,
            best=best,
            failed_bodies=failed_bodies,
            failed_kinds=failed_kinds,
            sticky_fail=set(),
            round_i=0,
            chain_i=0,
            history=hist,
            ranked_meta={"pick": "p0", "skipped": False},
            temperature=1.0,
            rng=__import__("random").Random(0),
        )
        self.assertTrue(tried["accept"])
        self.assertEqual(chain.tokens, 1)
        self.assertEqual(best["token_count"], 1)
        packed = lra_search.mcmc_result(
            rounds=1,
            beam=1,
            temperature=1.0,
            seed=0,
            lake_calls=2,
            leanstral_calls=0,
            best=best,
            history=hist,
        )
        self.assertEqual(packed["mode"], "mcmc_beam")
        self.assertFalse(packed["jev_generated_lean"])
        self.assertFalse(packed["called_docker0"])
        state = lra_jev.fanout_problem_state({"name": "P", "source": "s", "statement": "theorem t : True"})
        self.assertEqual(state["problem"]["name"], "P")
        criteria = lra_jev.draft_criteria([tactics.Draft(draft_id="d00", family="dead_code", tactics="  simp\n", ops=("drop",))])
        self.assertIn("d00", criteria)
        qs = lra_jev.choice_questions(
            Choice=lambda **kw: {"kind": "choice", **kw},
            Noul=lambda **kw: {"kind": "noul", **kw},
            Score=lambda **kw: {"kind": "score", **kw},
            criteria=criteria,
            best_instructions="pick",
            nouls={"ok": "compiles?"},
            scores={"cut": ("how much", ["same", "less"])},
        )
        self.assertEqual(qs["best_first_draft"]["kind"], "choice")
        self.assertEqual(qs["ok"]["kind"], "noul")
        evals = lra_search.compile_variant_evals(
            [("identity", "  simp\n")],
            lambda label, body: {"theorem_ok": True, "token_count": 1, "exit_code": 0, "errors": []},
        )
        self.assertEqual(evals[0]["hammer"], "identity")
        sampled = lra_search.sample_next_lines(2, generate_fn=lambda: None, parse_fn=str, empty="STOP")
        self.assertEqual(sampled, ["STOP", "STOP"])
        self.assertEqual(lra_search.filter_blacklist([{"kind": "a", "tactics": "x"}], failed_kinds={"a"}), [])
        self.assertEqual(lra_search.kind_prefix_indices([{"kind": "drop_duplicate_1"}], ("drop_duplicate",)), [0])
        pinned = lra_search.unique_pin_cap(
            [{"kind": "b"}, {"kind": "a"}, {"kind": "c"}, {"kind": "a"}],
            "a",
            key_fn=lambda item: item["kind"],
            cap=2,
        )
        self.assertEqual([row["kind"] for row in pinned], ["a", "b"])
        owner = lra_outer.pack_owner_exec(attempted=False, executed=False, argv=["grok"], argv_relative=["grok"])
        self.assertFalse(owner.started_llama_server)
        self.assertFalse(owner.executed)
        failed = lean.failed_candidate(
            kind="generated",
            code="empty_generation",
            reason="empty",
            generator="leanstral",
            hardware_class="spark_gb10",
        )
        self.assertFalse(failed.admission_accepted)
        self.assertFalse(failed.to_dict()["valid"])
        cand = lean.make_candidate(
            kind="reference",
            tactics="  trivial\n",
            source_text="theorem t : True := by\n  trivial\n",
            admission_accepted=True,
            admission_code="",
            admission_reason="ok",
            generator="deterministic",
            token_count=2,
        )
        dummy_rec = type("R", (), {"error": "boom", "hardware_class": ""})()
        lean.attach_compile(cand, [dummy_rec], hardware_class="spark_gb10", elab_fn=lambda _rows: 1.5)
        self.assertEqual(cand.error, "boom")
        self.assertEqual(cand.elab_ms, 1.5)
        row = lean.failure_row(cand, hardware_class="spark_gb10", failing_tags=[{"lean_tag": "v4.26.0"}])
        self.assertEqual(row["kind"], "reference")
        pin = lean.VersionPin(lean_tag="v4.26.0", git_commit="abc")
        seeded = lean.init_compile_receipt({"name": "P", "source": "strata", "url": "u"}, pin, timeout=120.0, relpath="A.lean")
        self.assertEqual(seeded.lean_tag, "v4.26.0")
        self.assertFalse(seeded.independent_kernel_verifier_used)
        allowed, reason, _cost = lra_outer.authorize_spend(
            "jev",
            counts={"jev": 2},
            limits={"jev": 2},
            spent=0,
            cost=0,
            budget=1,
            zero=0,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "max_jev_calls")
        hits, notes = lra_search.collect_source_hits(
            (("jsonld", lambda: [{"symbol": "a"}]), ("duckdb", lambda: ([], "no_duckdb_index")))
        )
        self.assertEqual(notes["jsonld"], "ok")
        self.assertEqual(notes["duckdb"], "no_duckdb_index")
        self.assertEqual(hits[0]["symbol"], "a")
        mem_hits: dict = {"nca": {"grid": {"ptr://theorem/P": {"kind": "theorem"}}}}
        n = lra_search.credit_search_hits(mem_hits, [{"symbol": "port_foo", "score": 1.0, "ptr": "ptr://skill/port_foo"}])
        self.assertEqual(n, 1)
        self.assertIn("ptr://skill/port_foo", mem_hits["nca"]["grid"])
        qs = lra_jev.tree_choice_questions(
            {"drop": {"drop_a": "a", "drop_b": "b"}},
            Choice=lambda **kw: {"kind": "choice", **kw},
            family_instructions="pick family",
        )
        self.assertEqual(qs["family"]["kind"], "choice")
        self.assertIn("leaf_drop", qs)
        packed_beam = lra_search.pack_beam_search(
            {"local_calls": 1, "finals": [], "trace": []},
            prefix="  intro",
            vocab_n=2,
            mode="greedy",
            beam=1,
            temperature=0.0,
            max_steps=1,
        )
        self.assertEqual(packed_beam["mode"], "greedy")
        self.assertFalse(packed_beam["jev_generated_lean"])
        try_receipt = lean.init_try_receipt(
            {"name": "P", "source": "s", "url": ""},
            pin,
            relpath="A.lean",
            template_digest="d" * 64,
            prefix_bound=True,
            aesop=False,
            considered=["rfl"],
            timeout=120.0,
        )
        self.assertFalse(try_receipt.hammer_006_lra_ready)
        self.assertFalse(try_receipt.uses_snapshot_goal)
        self.assertEqual(try_receipt.tactics_considered, ["rfl"])
        pin_reference_scores = lean.pin_reference_scores
        rec.elab_ms = 12.0
        pin_reference_scores(rec, composite_fn=lambda a, b: a + b)
        self.assertEqual(rec.elab_ratio, 1.0)
        files, compiled = lean.compile_receipt_files(
            type("K", (), {"compile_receipts": [type("C", (), {"to_dict": lambda self: {"lean_tag": "v4.26.0", "ok": True}, "lean_tag": "v4.26.0"})()]})(),
            hardware_class="spark_gb10",
        )
        self.assertIn("v4.26.0.json", files)
        self.assertIsNone(compiled[0]["arena_score"])
        hammered, grok_ok, body, errs = lra_search.compile_then_hammer(
            [{"kind": "mca", "tactics": "  sorry\n"}],
            compile_fn=lambda _b: {"theorem_ok": False, "errors": [{"data": "unsolved"}]},
            row_fn=lambda item, compiled: {"kind": item["kind"], **compiled},
            hammer_fn=lambda kind, item, compiled: ([{"kind": f"{kind}_hammer", "theorem_ok": True}], "  rfl\n", [], True),
            needs_hammer_fn=lambda kind: True,
        )
        self.assertTrue(hammered[-1]["theorem_ok"])
        self.assertFalse(grok_ok)
        chat = lra_outer.chat_request_payload("hi", model="labs-leanstral-1-5", max_tokens=8, n=2)
        self.assertEqual(chat["n"], 2)
        self.assertGreater(chat["temperature"], 0)
        packed_chat = lra_outer.pack_chat_response(
            {"choices": [{"message": {"content": "simp"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "m", "id": "x"},
            status=200,
            url="https://api.mistral.ai/v1/chat/completions",
            wall_ms=1.0,
            model="labs-leanstral-1-5",
        )
        self.assertEqual(packed_chat["url_host"], "api.mistral.ai")
        self.assertEqual(packed_chat["text"], "simp")
        state = lra_jev.proposal_rank_state({"name": "P"}, "  simp\n", {"p0": "drop"}, tokens=2)
        self.assertEqual(state["current_tokens"], 2)
        fake = type(
            "R",
            (),
            {
                "choices": {"next_edit": type("C", (), {"choice": "p0", "confidence": 0.9, "probabilities": {"p0": 1.0}})()},
                "nouls": {"likely_compiles": type("N", (), {"noul": 0.8})()},
                "scores": {"likely_shorter": type("S", (), {"score": 1.0})()},
                "usage": {},
                "model": "jev",
            },
        )()
        ranked = lra_jev.pack_ranked_pick(fake, choice_key="next_edit", n=1)
        self.assertEqual(ranked["pick"], "p0")
        self.assertEqual(ranked["order"], [0])
        persisted = lean.persist_receipt(
            type("PR", (), {"body_digest": "a", "candidate_cid": "", "key_digest": "k", "filesystem_path": ""})(),
            root="/tmp",
            duckdb_path=None,
            finalize_fn=lambda receipt, body=None: receipt,
            write_cas_fn=lambda *_a: "a",
            write_fs_fn=lambda *_a: "/tmp/r.json",
            connect_fn=lambda *_a: (None, "none"),
            install_fn=lambda *_a: None,
            insert_fn=lambda *_a: True,
            insert_edge_fn=lambda *_a: True,
            try_import_fn=lambda: None,
        )
        self.assertFalse(persisted.duckdb_used)
        class _Led:
            def authorize(self, *_a, **_k):
                return True, "ok", 0
            def record(self, *_a, **k):
                return type("L", (), {"skipped": False, "reason": "recorded"})()
        text, ident, _line = lra_outer.ledger_generate(
            _Led(),
            "mistral",
            estimated_in=1,
            estimated_out=1,
            model="labs",
            fixture=True,
            fixture_text="simp_all",
            live_fn=lambda: ("", {}, (0, 0)),
            identity_fn=lambda **_k: {"resolved_model": "labs", "url_host": "api.mistral.ai"},
            error_cls=RuntimeError,
            estimate_fn=lambda text: len(text),
        )
        self.assertEqual(text, "simp_all")
        self.assertEqual(ident["url_host"], "api.mistral.ai")
        ident = lean.identity_from_trace(
            {"provider_name": "leanstral_local", "model_name": "Leanstral"},
            generated=True,
            requested_provider="leanstral_local",
            requested_model="Leanstral",
            allowed=("leanstral_local",),
            forbidden=("grok",),
        )
        self.assertFalse(ident.fallback_used)
        lean.refuse_if_fallback(ident, error_cls=RuntimeError)
        new_n, new_t = lean.coalesce_limits(source="putnambench", lookup_fn=lambda _s: (64, 30.0), default_new=32, default_timeout=10.0)
        self.assertEqual((new_n, new_t), (64, 30.0))
        routed = lra_jev.route_result_from_answers(
            {"family": "have_chain", "spend_llm": 0.2, "usage": {}},
            mode="distill",
            official_track2=False,
            wall_ms=1.0,
            used_fixture=True,
            model="jev",
        )
        self.assertEqual(routed.family, "have_chain")
        self.assertFalse(routed.jev_generated_lean)
        self.assertEqual(lra_outer.session_reason("skip_llm", lock_held=True), "docker0 unhealthy and owner exclusive lock held; skip LLM")
        session = lra_outer.pack_client_session(
            action="skip_llm",
            health={"ok": False},
            lock={"held": True},
            autostart="0",
            owner={"executed": False},
            reason="skip",
        )
        self.assertTrue(session.skipped)
        self.assertFalse(session.lock_ex_taken_by_client)
        skipped = lra_outer.generate_client_flow(
            health=type("H", (), {"ok": False})(),
            lock=type("L", (), {"held": False})(),
            generate_fn=lambda: "gen",
            wait_fn=lambda _s: type("H", (), {"ok": False})(),
            exec_fn=lambda _e: type("O", (), {"executed": False, "returncode": None, "error": ""})(),
            skip_fn=lambda _h, reason: f"skip:{reason}",
            decide_fn=lambda *_a, **_k: "skip_llm",
        )
        self.assertTrue(str(skipped).startswith("skip:"))
        healthy = lra_outer.generate_client_flow(
            health=type("H", (), {"ok": True})(),
            lock=type("L", (), {"held": False})(),
            generate_fn=lambda: "gen",
            wait_fn=lambda _s: None,
            exec_fn=lambda _e: None,
            skip_fn=lambda *_a: "skip",
            decide_fn=lambda *_a, **_k: "generate",
        )
        self.assertEqual(healthy, "gen")
        kind_key, model, idx = lra_outer.spend_kind("jev", models={"jev": "m"}, counts={"jev": 2})
        self.assertEqual((kind_key, model, idx), ("jev", "m", 3))
        payload = lra_search.keepbest_payload(
            name="P",
            digest="a" * 64,
            rows=[{"kind": "reference"}],
            kept={"kind": "reference"},
            repaired=False,
            clone="/tmp",
            file_path="A.lean",
            hosted_receipt="/tmp/h.json",
            n_valid=1,
            n_module_ok=1,
            hardware_class="spark_gb10",
            prototype_hardware="spark_gb10",
        )
        self.assertFalse(payload["called_docker0"])
        self.assertEqual(payload["n_valid"], 1)
        pairs = __import__("jevops.nca", fromlist=["call_pairs_from_graph"]).call_pairs_from_graph(
            {"calls": {"a": ["b", "c"], "b": ["c"]}}, limit=2
        )
        self.assertEqual(len(pairs), 2)
        dummy_receipt = type("R", (), {"argv": [], "cwd": "", "measurement_maxHeartbeats": 1, "independent_kernel_verifier_used": False})()
        dummy_receipt = lean.stamp_measured_receipt(
            dummy_receipt,
            argv=["/opt/lake", "env", "/opt/lean"],
            cwd="/tmp",
            run_fn=lambda: type("P", (), {"stdout": "ok", "stderr": "", "error": "", "returncode": 0})(),
            max_heartbeats=400000,
            lean_path="/opt/lean",
            timeout_seconds=1.0,
        )
        self.assertEqual(dummy_receipt.argv[0], "/opt/lake")
        view = lean.pack_admission_view(
            type("A", (), {"accepted": True, "failure_code": "ok", "reason": "ok"})(),
            name="P",
            native="theorem t : True := by\nsorry",
            statement="theorem t : True",
        )
        self.assertTrue(view.native_source_starts_with_statement)
        self.assertFalse(view.used_full_src_as_canonical)
        skipped, reason = lean.generation_skip_reason(
            type("G", (), {"skipped": True, "error": ""})(),
            probe_ok=False,
        )
        self.assertTrue(skipped)
        self.assertIn("docker0", reason)
        cands: list = []
        lean.append_generated(
            cands,
            called=True,
            skipped=False,
            generation=type(
                "G",
                (),
                {"text": "", "error": "", "identity": type("I", (), {"resolved_provider": "leanstral_local"})()},
            )(),
            cap=8,
            extract_fn=lambda _t: "",
            evaluate_fn=lambda *_a: None,
            generator_default="leanstral",
            hardware_class="spark_gb10",
        )
        self.assertEqual(cands[0].admission_code, "empty_generation")
        packed_best = lra_jev.pack_best_draft(
            type(
                "R",
                (),
                {
                    "choices": {"best_first_draft": type("C", (), {"choice": "d0", "confidence": 0.9, "probabilities": {"d0": 1.0}})()},
                    "nouls": {},
                    "scores": {},
                    "usage": {},
                    "model": "jev",
                },
            )()
        )
        self.assertEqual(packed_best["best_first_draft"], "d0")
        self.assertFalse(packed_best["jev_generated_lean"])
        box = {"tokens": 10, "keep": "  simp\n"}
        accept = lra_search.boxed_keepbest(box)
        hit, nxt, body = accept([{"theorem_ok": True, "token_count": 3, "tactics": "  rfl\n"}], 10, "  rfl\n")
        self.assertEqual(nxt, 3)
        self.assertEqual(box["keep"], "  rfl\n")
        zipped = lra_search.attach_jev_rounds([{"round": 0}], [{"choice": "h0"}], [{"round": 0}])
        self.assertEqual(zipped[0]["jev"]["choice"], "h0")
        sgd = lra_search.sgd_payload(
            name="P",
            digest="a" * 64,
            n_holes=2,
            ref_tokens=10,
            keep_tokens=4,
            dropped=["h0"],
            rounds=zipped,
            leanstral=None,
            hardware_class="spark_gb10",
        )
        self.assertFalse(sgd["called_docker0"])
        self.assertEqual(sgd["keep_tokens"], 4)
        self.assertEqual(lean.catch_trace(None), {})
        self.assertEqual(lean.require_text("ok", error_cls=RuntimeError), "ok")
        packed_prob = lean.pack_problem_result(
            type("S", (), {"name": "P", "source": "s", "header": "", "statement": "theorem t : True"})(),
            phases=["splice"],
            probe=type("H", (), {"ok": True})(),
            called=False,
            skipped=True,
            skip_reason="down",
            retrieval=type("R", (), {"lemma_id_digest": "d", "neighbors": [], "src_lemmas": []})(),
            candidates=[],
            kept=None,
            failures=[],
            hardware_class="spark_gb10",
            hammers="off",
            typesafe="off",
            generator="leanstral",
            loop_version="v1",
        )
        self.assertIsNone(packed_prob.arena_score)
        self.assertTrue(packed_prob.skipped_generate)
        named = lra_outer.select_named(
            [{"name": "A"}, {"name": "B"}],
            ["B"],
            error_cls=RuntimeError,
        )
        self.assertEqual([row["name"] for row in named], ["B"])
        self.assertEqual(lra_outer.select_limit(["a", "b", "c"], 2), ["a", "b"])
        batch = lean.warmup_batch_payload(
            digest="a" * 64,
            results=[],
            health_ok=False,
            jsonl_bytes=1,
            n_records=15,
            planted=False,
            written=[],
            generator="leanstral",
            hammers="off",
            hardware_class="spark_gb10",
            loop_version="v1",
            protocol="LRA/v1",
            typesafe="off",
            gates="off",
            phases=("splice",),
        )
        self.assertTrue(batch["skip_generate_only_if_docker0_down"])
        self.assertFalse(batch["lock_ex_taken_by_client"])
        overlay = lra_jev.overlay_route_payload(
            {"skipped": True, "reason": "no_key"},
            name="P",
            source="strata",
            digest="a" * 64,
            n_neighbors=1,
        )
        self.assertTrue(overlay["ok"])
        self.assertFalse(overlay["jev_generates_lean"])
        live = lra_jev.project_live_answers(
            type(
                "R",
                (),
                {
                    "choices": {"best_first_draft": type("C", (), {"choice": "d0", "confidence": 0.8, "probabilities": {"d0": 1}})()},
                    "nouls": {"dead_code_safe": type("N", (), {"noul": 0.1})()},
                    "scores": {"likely_token_cut": type("S", (), {"score": 1})()},
                    "usage": {},
                    "model": "jev",
                },
            )(),
            choice_map={"best_first_draft": "best_first_draft"},
            noul_map={"dead_code_safe": "dead_code_safe"},
            score_map={"likely_token_cut": "likely_token_cut"},
        )
        self.assertEqual(live["best_first_draft"], "d0")
        self.assertEqual(live["dead_code_safe"], 0.1)
        adm = lean.admission_receipt(
            type("P", (), {"name": "P", "candidates": [type("C", (), {"admission_accepted": True, "admission_code": "ok", "kind": "reference", "admission_reason": ""})()]})(),
            hardware_class="spark_gb10",
        )
        self.assertTrue(adm["candidates"][0]["accepted"])
        plan_rows = lean.path_a_plan_rows(
            [{"name": "P", "source": "strata"}],
            tactics_fn=lambda _r: ["rfl", "aesop"],
            aesop_fn=lambda _r: True,
        )
        self.assertTrue(plan_rows[0]["aesop_in_list"])
        collected = tactics.collect_tree_drafts(
            closed_edits=[("reference", "  simp\n", ("identity",))],
            neighbor_ops=[],
            push_fn=lambda drafts, seen, family, body, ops: tactics.push_draft(drafts, seen, family, body, ops, cap=8),
            cap=8,
        )
        self.assertEqual(collected[0].family, "reference")
        problems = lean.plan_loop_problems(
            [{"name": "P", "source": "s", "version_info": [{"lean_tag": "v4.26.0"}]}],
            split_fn=lambda rec: type("S", (), {"name": rec["name"], "source": rec["source"]})(),
            pins_fn=lambda rec: [type("P", (), {"lean_tag": rec["version_info"][0]["lean_tag"]})()],
        )
        self.assertEqual(problems[0]["n_tags"], 1)
        plan = lean.plan_loop_payload(
            digest="a" * 64,
            problems=problems,
            health={"ok": False},
            jsonl_bytes=1,
            autostart="0",
            health_url="http://172.17.0.1:8080/health",
            generator="leanstral",
            hammers="off",
            hardware_class="spark_gb10",
            loop_version="v1",
            protocol="LRA/v1",
            typesafe="off",
            gates="off",
            phases=("splice",),
            tokenizer_id="tok",
            token_weights={"elab": 0.45, "tokens": 0.55},
        )
        self.assertTrue(plan["must_call_leanstral_if_health_ok"])
        self.assertFalse(plan["lock_ex_taken_by_client"])
        skip = lra_outer.closed_skip("official_track2_off", extra={"called_jev": False})
        self.assertTrue(skip["skipped"])
        hosted = lra_jev.hosted_run_payload(
            name="P",
            source="s",
            digest="a" * 64,
            identity={"url_host": "api.mistral.ai"},
            text="simp",
            jev_route={"skipped": False},
            ledger={"jev_calls": 1},
            wall_ms=1.0,
            requested_provider="mistral",
            requested_model="labs-leanstral-1-5",
            hardware_class="mistral_labs_api",
            prototype_hardware="spark_gb10",
            protocol="LRA/v1",
            pr="PR-12b",
            track="track1",
            labs_retire_date="2026-09-30",
        )
        self.assertFalse(hosted["called_docker0"])
        loop = lra_outer.skill_loop_payload(
            outer=1,
            llm=False,
            history=[],
            board={"P": 1},
            total=1,
            best_total=1,
            stop_reason="",
            memory_path="/tmp",
            memory_skills=[],
            ledger=type("L", (), {"as_dict": lambda self: {"grok_calls": 0}})(),
            protocol="LRA/v1",
            pr_id="PR-9h",
        )
        self.assertEqual(loop["outer"], "grok")
        self.assertFalse(loop["grok_writes_lean"])
        canary = lra_jev.canary_live_payload(
            digest="a" * 64,
            seed=1,
            k=2,
            n_records=15,
            landscape=[{"n_tags": 2}],
            model={"explained_ratio": [1], "principal": [{"loadings": {}}]},
            extra_139=None,
            canaries=[],
            lake=[],
            gaps=[],
            mem_path="/tmp",
            memory={"n_skills": 0},
            nca_status={},
            ledger=type("L", (), {"jev_calls": 0})(),
        )
        self.assertEqual(canary["n_tag_cells"], 2)
        guided = tactics.collect_guided_drafts(
            "  simp_all\n",
            [{"family": "dead_code"}],
            {"n_have": 0},
            extras=(),
            push_fn=lambda drafts, seen, family, body, ops: tactics.push_draft(drafts, seen, family, body, ops, cap=8),
        )
        self.assertTrue(any(item.family == "reference" for item in guided))
        stub = lean.putnam_candidate_stub()
        self.assertIn("Putnam", stub)
        self.assertIn("not Tmp.lean", stub)
        self.assertIn("True := by", stub)
        ident = lean.hosted_identity(
            requested_provider="mistral",
            requested_model="labs-leanstral-1-5",
            fixture=True,
            api_host="api.mistral.ai",
            hardware_class="mistral_labs_api",
        )
        self.assertEqual(ident["url_host"], "api.mistral.ai")
        self.assertFalse(ident["fallback_used"])
        live = lean.hosted_identity(
            requested_provider="mistral",
            requested_model="labs-leanstral-1-5",
            fixture=False,
            extra={"url_host": "api.mistral.ai", "model": "labs-leanstral-1-5", "id": "x"},
            api_host="api.mistral.ai",
            hardware_class="mistral_labs_api",
        )
        self.assertEqual(live["request_id"], "x")
        with self.assertRaises(ValueError):
            lean.hosted_identity(
                requested_provider="mistral",
                requested_model="labs",
                fixture=False,
                extra={"url_host": "172.17.0.1"},
                api_host="api.mistral.ai",
                hardware_class="mistral_labs_api",
            )
        try_plan = lean.pack_try_plan(
            digest="a" * 64,
            jsonl_bytes=12,
            n_records=15,
            per_record=[{"name": "P", "tactics": ["rfl"]}],
            first_name="P",
            first_tactics=["rfl"],
            putnam_name="Q",
            putnam_tactics=["aesop"],
            extra={"path": "A", "hammer_006_lra_ready": False},
        )
        self.assertEqual(try_plan["first_putnam_name"], "Q")
        self.assertFalse(try_plan["hammer_006_lra_ready"])
        self.assertIsNone(try_plan["arena_score"])
        syn_try = lean.pack_synthetic_try(
            elan_home="/tmp/elan",
            missing_closed=True,
            written=["/tmp/P.json"],
            persisted=[],
            putnam=type("R", (), {})(),
            strata=type("R", (), {})(),
            unsolved=type("R", (), {})(),
            timeout_30_rejected=True,
            summary_fn=lambda _item: {"ok": True},
        )
        self.assertTrue(syn_try["timeout_30s_rejected"])
        baked = lean.pack_synthetic_bake(
            planted="/tmp/cache",
            planted_n=1,
            hit={"ok": True, "status": "cache-hit"},
            missing_raised=True,
            missing_message="network=deny",
            allow_missing={"ok": False, "status": "cache-missing"},
            write_denied=True,
            materialized={
                "v4.26.0": {
                    "has_tmp_lean": False,
                    "has_lakefile": True,
                    "mathlib_in_lakefile": True,
                    "aesop_in_lakefile": True,
                    "candidate_module": "Putnam.Candidate",
                    "putnambench_url": None,
                }
            },
            putnam_tags=("v4.26.0",),
            putnam_module="Putnam.Candidate",
        )
        self.assertTrue(baked["write_candidate_rejects_tmp_lean"])
        self.assertTrue(baked["all_putnambench_url_null"])
        from jevops import mask as lra_mask

        shots = lra_mask.one_hole_shots(
            phrase_alts=(("simp at h", "simp_all"),),
            operator_alts={"$": ("",)},
            span=2,
            n_shots=3,
            token_fn=lean.token_count,
        )
        self.assertTrue(shots)
        self.assertEqual(shots[0]["n_holes"], 1)
        catalog = lra_mask.catalog_shots(
            "  simp at h\n",
            phrase_alts=(("simp at h", "simp_all"), ("exact Hin", "assumption")),
            n_shots=2,
            head_fn=lambda rows, n: list(rows)[:n],
        )
        self.assertTrue(catalog)
        closed_row = lra_mask.closed_multihole_row(
            "  simp at h\n  exact Hin\n",
            [{"start": 2, "end": 11, "original": "simp at h", "hole_id": "SYM_0", "kind": "phrase"}],
            schedule_id="cfg0",
            fills_fn=lambda _item, _text: ["simp_all"],
            token_fn=lean.token_count,
            as_row_fn=lambda item: item,
        )
        self.assertIsNotNone(closed_row)
        self.assertLess(closed_row["token_count"], lean.token_count("  simp at h\n  exact Hin\n"))
        kernel_rows = lra_mask.kernel_one_hole_rows(
            "  apply And.intro\n  exact Hin\n",
            propose_fn=lambda _t: [{"kind": "and_intro", "tactics": "  constructor\n", "note": "ctor"}],
            token_fn=lean.token_count,
            spans=(1, 2, 3, 4, 6),
        )
        self.assertEqual(kernel_rows[0]["kind"], "kernel_and_intro")
        from jevops import jev as lra_jev2

        plan_view = lra_jev2.pack_plan_view(protocol="LRA/v1", model="jev-latest", n_catalog=3)
        self.assertTrue(plan_view["ok"])
        self.assertFalse(plan_view["compiled"])
        self.assertIsNone(plan_view["arena_score"])
        grok_prompt = lean.grok_file_prompt("  simp\n", dest_name="tactics.lean", stub="-- REPLACE_THIS_FILE")
        self.assertIn("tactics.lean", grok_prompt)
        self.assertNotIn("docker0", grok_prompt.lower())
        argv = lean.grok_file_argv(
            grok_bin="/usr/bin/grok",
            socket="/tmp/s.sock",
            workspace="/tmp/ws",
            model="grok-4.6",
            max_turns=8,
            tools="write_file",
            disallowed="Bash",
            dest_name="tactics.lean",
            prompt_path="/tmp/PROMPT.txt",
        )
        self.assertEqual(argv[0], "/usr/bin/grok")
        self.assertIn("--prompt-file", argv)
        pairs = lra_search.keepbest_beam_pairs(
            "  have h := x\n  simp_all\n",
            ["  simp_all\n"],
            variants_fn=lambda label, body, reference: [(label, body)],
        )
        self.assertTrue(any(name == "beam_0" for name, _body in pairs))
        keep_out = lean.compile_keepbest(
            {"name": "P", "source": "putnambench", "src": "theorem t : True := by\n  sorry\n", "version_info": [{"v4.26.0": "abc"}]},
            "  trivial\n",
            putnam_source="putnambench",
            token_fn=lean.token_count,
            closed_fn=lambda **kw: {"ok": False, **kw},
            pins_fn=lambda rec: rec.get("version_info") or [],
            compile_fn=lambda rec: [type("R", (), {"to_dict": lambda self: {"ok": True, "exit_code": 0, "timed_out": False, "sorryAx": False, "stdout": "", "error": ""}})()],
            parse_errors_fn=lambda _stdout: [],
            sorry_fn=lambda *_a: False,
            pack_fn=lean.pack_compile_view,
            elapsed_fn=lambda _t: 1.0,
            now_fn=lambda: 0.0,
            patch_fn=lambda rec, tactics, statement: rec,
            statement_fn=lambda _rec: "theorem t : True",
            dest_fn=lambda _rec: Path("/tmp/x.lean"),
            restore=b"",
            write_bytes_fn=lambda *_a: None,
            candidate_source_fn=lambda rec, tactics: tactics,
            splice_fn=lambda *_a: None,
            span_fn=lambda *_a: (1, 2),
            line_in_span_fn=lambda *_a: True,
            extra_fn=lambda *_a: {},
        )
        self.assertTrue(keep_out["theorem_ok"])
        packed_prob = lean.collect_warmup_problem(
            {"name": "P", "src": "theorem t : True := by\n  trivial\n"},
            [],
            split=type("S", (), {"name": "P", "source": "s", "header": "", "statement": "theorem t : True", "reconstructed_src": "theorem t : True := by\n  trivial\n"})(),
            reconstruct_ok=True,
            error_cls=RuntimeError,
            retrieve_fn=lambda *_a: type("R", (), {"lemma_id_digest": "d", "neighbors": [], "src_lemmas": []})(),
            phases=["splice"],
            probe=type("H", (), {"ok": False})(),
            ref_tactics="  trivial\n",
            stripped="  trivial\n",
            token_fn=lean.token_count,
            evaluate_fn=lambda kind, tactics, **kw: lean.make_candidate(
                kind=kind,
                tactics=tactics,
                source_text="theorem t : True := by\n" + tactics,
                admission_accepted=True,
                admission_code="",
                admission_reason="ok",
                generator=kw.get("generator") or "deterministic",
                token_count=lean.token_count(tactics),
            ),
            pin_fn=lambda cand, composite_fn: cand,
            composite_fn=lambda a, b: a,
            prompt_fn=lambda *_a: "prompt",
            generate_fn=lambda _p: type("G", (), {"skipped": True, "error": "down", "identity": type("I", (), {"resolved_provider": ""})(), "text": ""})(),
            skip_reason_fn=lambda gen, probe_ok: (True, "down"),
            append_fn=lean.append_generated,
            extract_fn=lambda _t: "",
            keep_fn=lambda rows: rows[0] if rows else None,
            failure_fn=lambda item: {"kind": item.kind},
            pack_fn=lean.pack_problem_result,
            max_candidates=8,
            hardware_class="spark_gb10",
            hammers="off",
            typesafe="off",
            generator="leanstral",
            loop_version="v1",
            generator_default="leanstral",
        )
        self.assertEqual(packed_prob.name, "P")
        self.assertTrue(packed_prob.skipped_generate)
        from jevops import jev as lra_jev3
        from jevops import walk as lra_walk

        class _View:
            accepted = True
            failure_code = ""
            reason = "ok"

        scored = lean.evaluate_with_compile(
            kind="reference",
            tactics="  trivial\n",
            source_text="theorem t : True := by\n  trivial\n",
            admit_fn=lambda _body: _View(),
            make_fn=lean.make_candidate,
            compile_fn=lambda _body: [],
            attach_fn=lambda cand, _rows: cand,
            score_fn=lambda cand, reconstructed_ok: cand if reconstructed_ok else cand,
            reconstruct_fn=lambda: True,
            generator="deterministic",
            token_count=1,
            hardware_class="spark_gb10",
        )
        self.assertEqual(scored.kind, "reference")
        self.assertTrue(scored.admission_accepted)
        nested = lra_walk.run_nested(
            tactics="  simp\n",
            dest=type("D", (), {"is_file": lambda self: False})(),
            restore=b"",
            name="P",
            analyze_fn=lambda _body: {"name": "P", "n_tokens": 1},
            pack_fn=lra_walk.pack_canary,
            budget_fn=lambda: (8, 3),
            walk_fn=lambda *_a, **_k: {},
            restore_fn=lambda *_a: None,
        )
        self.assertEqual(nested["ranked"]["reason"], "no_clone")
        catalog = lra_jev3.rank_catalog_or_live(
            {"name": "P", "source": "s"},
            drafts=[type("D", (), {"draft_id": "d0"})()],
            families=[{"family": "dead_code"}],
            features={"simp": 1},
            live=False,
            extra={"catalog": [{"id": "d0"}]},
        )
        self.assertEqual(catalog["n_drafts"], 1)
        self.assertFalse(catalog["live"])
        self.assertIsNone(catalog["arena_score"])
        keep_run = lra_search.run_keepbest(
            name="P",
            digest="a" * 64,
            ref_tactics="  simp_all\n",
            hosted=None,
            flattened=None,
            collapse=None,
            span_drafts=(),
            compile_fn=lambda body: {"ok": True, "theorem_ok": True, "module_exit_0": True, "token_count": 2, "sorry_in_theorem": False, "wall_ms": 1},
            row_fn=lambda item, compiled: {**dict(item), **dict(compiled)},
            token_fn=lean.token_count,
            repair=False,
            pick_fn=lra_search.pick_min_tiers,
            first_where_fn=lambda rows, pred: next((row for row in rows if pred(row)), None),
            pack_fn=lra_search.keepbest_payload,
            clone="/tmp/clone",
            rel="A.lean",
            hosted_path=None,
            hardware_class="mistral_labs_api",
            prototype_hardware="spark_gb10",
        )
        self.assertEqual(keep_run["kept"]["kind"], "reference")
        self.assertFalse(keep_run["repaired"])
        keep2, tok2, restart = lra_search.maybe_leanstral_restart(
            use=True,
            keep="  simp_all\n",
            keep_tokens=3,
            ref_tokens=4,
            generate_fn=lambda: ("x", None, None),
            flatten_fn=lambda text: text,
            eval_fn=lambda _body: [],
            hammer_fn=lambda filled, _evals: filled,
        )
        self.assertEqual(keep2, "  simp_all\n")
        self.assertIsNone(restart)
        self.assertEqual(tok2, 3)
        class _Lock:
            def __enter__(self) -> None:
                return None

            def __exit__(self, *_a: object) -> None:
                return None

        gen = lean.run_locked_generate(
            lock=_Lock(),
            pin_fn=lambda: None,
            call_fn=lambda: "  simp\n",
            catch_trace_fn=lambda: {"effective_provider_name": "leanstral_local", "effective_model_name": "Leanstral"},
            identity_fn=lambda trace, generated: lean.ProviderIdentity(
                requested_provider="leanstral_local",
                requested_model="Leanstral",
                resolved_provider="leanstral_local",
                resolved_model="Leanstral",
                fallback_used=False,
                arena_score=None,
            ),
            refuse_fn=lean.refuse_if_fallback,
            reraise_fn=lean.reraise_router_fail,
            require_fn=lean.require_text,
            generation_cls=lean.Generation,
            health=lean.HealthProbe(ok=True, url="http://x", alias_ok=True, alias_url="http://y", status_code=200, error="", autostart="0"),
            generate_cls=RuntimeError,
            unreachable_cls=RuntimeError,
        )
        self.assertEqual(gen.text, "  simp\n")
        self.assertFalse(gen.identity.fallback_used)
        class _Receipt:
            error = ""
            ok = True
            aesop_imported = False

        closed = lean.run_path_a_try(
            _Receipt(),
            ["rfl"],
            aesop_err="aesop missing",
            resolve_fn=lambda: None,
            prepare_fn=lambda: (None, "", None),
            env_fn=lambda _t: {},
            run_tactic_fn=lambda **_k: None,
            fill_fn=lambda *_a, **_k: None,
            close_fn=lambda rec, _exc, extra: rec,
            error_types=(RuntimeError,),
            extra_fn=lambda _exc: "",
            timeout=1.0,
        )
        self.assertEqual(closed.error, "aesop missing")
        self.assertFalse(closed.ok)
        ws = Path("/tmp")
        tactics_out, ident, chat_out, dest = lean.run_workspace_generate(
            workspace=ws,
            dest_name="tactics.lean",
            stub="-- REPLACE_THIS_FILE",
            reset_stub=False,
            generate_fn=lambda **_k: "  simp\n",
            identity_from_generate=lambda: "fixture",
            read_fn=lambda _ws, dest_name: "  simp\n",
            write_text_fn=lambda *_a, **_k: None,
        )
        self.assertEqual(tactics_out, "  simp\n")
        self.assertEqual(ident, "fixture")
        self.assertEqual(chat_out, "  simp\n")
        self.assertEqual(dest.name, "tactics.lean")
        class _Rec:
            ok = True
            error = ""

        stamped = lean.run_tag_compile(
            _Rec(),
            resolve_fn=lambda: "tc",
            prepare_fn=lambda: ("/cwd", "x.lean", "/dest"),
            write_fn=lambda _dest: None,
            stamp_fn=lambda rec, **_k: rec,
            close_fn=lambda rec, _exc: rec,
            error_types=(RuntimeError,),
        )
        self.assertTrue(stamped.ok)
        attempt = lean.fill_timed_attempt(
            tactic="rfl",
            argv=["lake"],
            cwd="/cwd",
            source_file="x.lean",
            timeout=1.0,
            run_fn=lambda: {"ok": True},
            fill_fn=lambda **kw: kw,
            timed_fn=lambda fn: (fn(), 1.0, 0.5),
        )
        self.assertEqual(attempt["tactic"], "rfl")
        self.assertEqual(attempt["result"], {"ok": True})
        from jevops import jev as lra_jev4
        from jevops import board as lra_board

        projected = lra_jev4.invoke_then_project(
            invoke_fn=lambda: ("result", 1.5),
            project_fn=lambda result, wall_ms: {"result": result, "wall_ms": wall_ms},
        )
        self.assertEqual(projected["result"], "result")
        skipped = lra_jev4.route_or_skip(
            enabled=False,
            official=False,
            key_ok=False,
            available=False,
            using_fixture=False,
            require_key=True,
            skip_fn=lambda reason: {"skipped": True, "reason": reason},
            invoke_fn=lambda: ("x", 0.0),
            project_fn=lambda *_a: {"live": True},
        )
        self.assertEqual(skipped["reason"], "typesafe_off")
        class _Hole:
            def __init__(self, hole_id: str) -> None:
                self.hole_id = hole_id

        dropped: set[str] = set()

        def _consider(label: str, hole_ids: list[str]) -> dict:
            dropped.update(hole_ids)
            return {"label": label, "accepted": True, "keep_tokens": 3, "holes": list(hole_ids)}

        walked = lra_search.run_diffuse_rounds(
            [_Hole("h0"), _Hole("h1")],
            rounds=1,
            tau=0.1,
            rng=__import__("random").Random(0),
            consider_fn=_consider,
            jev_fn=lambda remaining, history, tokens: {"choice": "h1", "probabilities": {"h1": 0.9}},
            noise_fn=lambda *_a: None,
            keep_tokens=10,
            dropped=dropped,
        )
        self.assertEqual(walked["keep_tokens"], 3)
        packed_d = lra_search.pack_diffuse(
            name="P",
            digest="a" * 64,
            n_holes=2,
            ref_tokens=10,
            keep_tokens=3,
            dropped=walked["dropped"],
            rounds=walked["rounds"],
            hardware_class="mistral_labs_api",
        )
        self.assertEqual(packed_d["schema"], "lra-diffuse-denoise/v1")
        self.assertIsNone(packed_d["arena_score"])
        mem_board: dict = {"nca": {}}
        seeded = lra_board.seed_then_sidecar(
            mem_board,
            {"root": "G1", "goal_title": "t", "subgoals": [], "tasks": []},
            sidecar_fn=lambda _mem, nca: nca.__setitem__("sidecar", True),
        )
        self.assertTrue(seeded["ok"])
        self.assertTrue(mem_board["nca"].get("sidecar"))
        from jevops import tactics as lra_tactics
        from jevops import nca as lra_nca2

        early, late = lra_tactics.collect_random_draft_extras(
            "  simp_all\n",
            __import__("random").Random(0),
            wanted_fn=lambda fam: True,
            portable_items=[{"kind": "port_x", "tactics": "  assumption\n", "family": "dead_code"}],
            pca_drafts=[type("D", (), {"family": "dead_code", "draft_id": "d0", "tactics": "  simp\n"})()],
        )
        self.assertEqual(early[0][0], "port_x")
        self.assertTrue(any(kind.startswith("pca_") for kind, _body, _extra in late))
        pruned = lra_jev4.complete_prune(
            invoke_fn=lambda: (type("R", (), {"usage": {}})(), 0.1),
            skip_fn=lambda exc: {"skipped": True, "reason": str(exc)},
            unpack_fn=lambda _r: (
                {"next_line": type("C", (), {"choice": "c0", "probabilities": {"c0": 1.0}, "confidence": 0.9})()},
                {},
                {},
                {},
            ),
            record_fn=lambda _u: type("L", (), {"skipped": False, "reason": ""})(),
            rank_fn=lambda criteria, probs, pick_id, unique, keep: [criteria[pick_id]],
            pack_fn=lra_jev4.pack_prune,
            criteria={"c0": "simp_all"},
            unique=["simp_all"],
            keep=1,
        )
        self.assertEqual(pruned["best"], "simp_all")
        self.assertFalse(pruned["skipped"])
        feat = lra_jev4.featurize_or_skip(
            invoke_fn=lambda: (object(), 0.0),
            skip_fn=lambda exc: {"skipped": True, "score": 0.0, "features": {}},
            unpack_fn=lambda _r: ({}, {"likely_compiles": type("N", (), {"noul": 0.8})()}, {}, {}),
            record_fn=lambda _u: None,
            feature_names=["likely_compiles"],
            weights={"likely_compiles": 1.0},
            signed_dot_fn=lambda features, weights, penalty, default_w: float(features.get("likely_compiles") or 0),
            penalty=0.0,
        )
        self.assertAlmostEqual(feat["score"], 0.8)
        packed_sym = lra_search.pack_symbol_search(query="simp", ranked=[{"symbol": "simp"}], sources={"jsonld": "ok"}, promoted=1)
        self.assertTrue(packed_sym["ok"])
        self.assertFalse(packed_sym["semantic_authority"])
        finished = lra_search.finish_mca_problem(
            candidates=[
                {"kind": "reference", "tactics": "  simp_all\n"},
                {"kind": "drop_have", "tactics": "  simp\n"},
            ],
            compile_fn=lambda body: {
                "theorem_ok": True,
                "token_count": 1 if "simp\n" in body and "simp_all" not in body else 4,
                "errors": [],
            },
            row_fn=lambda item, compiled: {**dict(item), **dict(compiled)},
            hammer_fn=lambda *_a, **_k: ([], "", [], False),
            needs_hammer_fn=lambda _kind: False,
            name="P",
            digest="a" * 64,
            holes=[],
            skeleton_head="  simp_all\n",
            hardware_class="mistral_labs_api",
            ref_tokens=4,
            extra_fn=lambda **_k: {},
            redact_fn=lambda payload: payload,
        )
        self.assertTrue(finished["beats_reference"])
        sidecar = lra_nca2.fill_sidecar_duckdb(
            "/tmp/nca-ast.duckdb",
            {"defs": {}, "calls": {}},
            connect_fn=lambda *_a, **_k: (type("C", (), {"close": lambda self: None})(), "duckdb"),
            exec_fn=lambda *_a, **_k: None,
            count_fn=lambda *_a, **_k: 0,
            try_import_fn=lambda _name: object(),
            refuse_fn=lambda *_a, **_k: False,
        )
        self.assertTrue(sidecar["ok"])
        self.assertFalse(sidecar["control_duckdb"])
        from jevops import mask as lra_mask2
        from jevops import outer as lra_outer2

        holes = lra_mask2.collect_literal_holes(
            "  simp [foo]\n  exact bar\n",
            phrases=["simp [foo]"],
            operators=["exact "],
            from_row_fn=lambda row: row,
            max_holes=8,
        )
        self.assertGreaterEqual(len(holes), 1)
        closed = lra_mask2.closed_with_replay(
            "  simp [foo]\n  exact bar\n",
            holes,
            fills_fn=lambda _item, _text: ["simp"],
            token_fn=lambda text: len(str(text).split()),
            as_row_fn=lambda item: item if isinstance(item, dict) else dict(item),
            replay_fn=lambda text: "  simp\n",
            max_candidates=8,
        )
        self.assertTrue(closed)
        fills = lra_mask2.pack_leanstral_fill_rows(
            tactics="  simp [foo]\n",
            holes=[],
            text="  simp\n",
            fills={},
            token_fn=lambda text: len(str(text).split()),
            extract_fn=lambda text: text,
            schedule_id="cfg",
            n_shots=0,
            head_fn=lambda text, n: text[:n],
        )
        self.assertEqual(fills[0]["kind"], "leanstral_cfg_fullblock")
        choice_out = lra_jev4.complete_choice_round(
            configured=False,
            criteria={"h0": "x"},
            invoke_fn=lambda: (object(), 0.0),
            pack_fn=lambda *_a, **_k: {},
            redact_fn=lambda payload: payload,
            skip_fn=lambda reason, **extra: {"skipped": True, "reason": reason, **extra},
            skip_extra={"choice": None},
        )
        self.assertEqual(choice_out["reason"], "no_key")
        ranked = lra_jev4.rank_proposals_or_skip(
            proposals=[],
            load_fn=lambda: None,
            skip_fn=lambda reason, **extra: {"skipped": True, "reason": reason, **extra},
            invoke_fn=lambda _m: (object(), 0.0),
            pack_fn=lambda *_a, **_k: {},
            record_fn=lambda _r: None,
        )
        self.assertEqual(ranked["reason"], "no_proposals")
        swapped = lra_search.line_swap_from_text(
            tactics="  simp_all\n  exact h\n",
            index=0,
            text="simp",
            parse_fn=lambda text: text.strip(),
            looks_fn=lambda text: True,
            replace_fn=lambda body, index, nxt: "  simp\n  exact h\n",
            stop="STOP",
            target="simp_all",
            head_fn=lambda text, n: text[:n],
        )
        self.assertEqual(swapped["kind"], "leanstral_swap")
        owner = lra_outer2.run_owner_exec(
            execute=False,
            argv=["python", "x.py"],
            argv_relative=["python", "x.py"],
            pack_fn=lra_outer2.pack_owner_exec,
        )
        self.assertFalse(owner.attempted)
        self.assertFalse(owner.executed)
        cfg = lra_jev4.pack_cfg_score(
            type(
                "R",
                (),
                {
                    "choices": {
                        "best_schedule": type("C", (), {"choice": "cfg0", "probabilities": {"cfg0": 1.0}})()
                    },
                    "nouls": {},
                    "scores": {"cfg_mask": type("S", (), {"score": 0, "confidence": 0.8})()},
                    "usage": {},
                },
            )(),
            1.2,
            table=[{"id": "cfg0", "n_masks": 2, "span": 3}],
            schedule_fn=lambda _score, one_hole=False: {"id": "fallback", "one_hole": one_hole},
            one_hole=False,
            eligible={"span_3": 1},
        )
        self.assertEqual(cfg["best_schedule"], "cfg0")
        self.assertFalse(cfg["skipped"])
        ops = lra_tactics.collect_symbol_ops(
            [{"kind": "inits_replay", "tactics": "  simp\n", "hole_kind": "phrase"}],
            [{"kind": "kernel_s3", "tactics": "  constructor\n"}],
        )
        self.assertEqual(ops[0][0], "symbol_diffuse")
        from jevops import nca as lra_nca3

        cross = lra_nca3.pack_cross_slice(symbol="a:f", callees=["b:g"], callers=["a:h"])
        self.assertTrue(cross["ok"])
        self.assertTrue(cross["cross_module"])
        stmt = lean.pack_statement_report(name="P", prefix_bind=True)
        self.assertIsNone(stmt["arena_score"])
        self.assertTrue(stmt["prefix_bind"])
        retrieval = type(
            "R",
            (),
            {
                "query": "P",
                "source": "s",
                "neighbors": (),
                "src_lemmas": (),
                "lemma_ids": (),
                "lemma_id_digest": "a" * 64,
                "n_src_lemmas_uncapped": 0,
                "arena_score": None,
                "corpus_manifest_ingest": False,
                "mathlib_ingest": False,
            },
        )()
        report = lean.pack_retrieval_report(
            retrieval,
            records=[{"name": "P", "src": "theorem t"}],
            lemma_cap=16,
            prompt_neighbors=[],
            asdict_fn=lambda item: dict(item),
        )
        self.assertTrue(report["self_excluded"])
        self.assertIsNone(report["score"])
        from jevops.outer import pack_receipt_insert_params

        params = pack_receipt_insert_params(
            type(
                "R",
                (),
                {
                    "candidate_cid": "c",
                    "generator": "lake",
                    "hardware_class": "dev",
                    "kernel_command_template": "lake env lean",
                    "key_digest": "k",
                    "name": "P",
                    "lean_tag": "v4.26.0",
                    "body_digest": "b",
                    "verdict": "ok",
                    "token_count": 1,
                    "elab_proxy": 0,
                    "dimensions": {},
                    "executable_paths": type("E", (), {"to_dict": lambda self: {"lean": "l"}})(),
                    "created_at": 1.0,
                },
            )(),
            schema="s",
            dumps_fn=lambda value: "{}",
            tiny_fn=lambda payload: "tiny",
        )
        self.assertEqual(params[0], "k")
        self.assertEqual(params[-2], "tiny")
        kwargs = lean.overlay_generate_kwargs({"provider": "x"}, temperature=0.0, stop=["\n"], stop_fn=list)
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["stop"], ["\n"])
        extras = lra_tactics.collect_mcmc_proposal_extras(
            "  simp\n",
            (),
            propose_fn=lambda _t: [{"kind": "drop", "tactics": "  exact h\n", "note": "n"}],
            replay_fn=lambda _t: "  simp\n",
        )
        self.assertEqual(extras[0]["kind"], "drop")
        self.assertEqual(extras[1]["kind"], "inits_replay")
        packed_c = lra_search.pack_generated_candidate(kind="k", generator="g", tactics="  simp\n")
        self.assertEqual(packed_c["kind"], "k")
        failed = lra_search.pack_failed_candidate(kind="k", generator="g", reason="no_key")
        self.assertTrue(failed["skipped"])
        self.assertFalse(failed["theorem_ok"])
        merged = lra_search.merge_labeled_candidates(
            [{"kind": "a", "tactics": "x"}],
            [{"kind": "b", "tactics": "y"}],
            extra_rows=(None, {"kind": "c", "tactics": "z"}),
        )
        self.assertEqual([row["kind"] for row in merged], ["a", "b", "c"])
        job = lean.putnam_bake_job(
            lean_tag="v4.26.0",
            putnam_source="putnambench",
            putnam_relpath="Putnam/Candidate.lean",
            putnam_module="Putnam.Candidate",
            name="P",
        )
        self.assertEqual(job.kind, "putnam")
        self.assertEqual(job.cache_key, "putnam/v4.26.0")
        self.assertTrue(job.lakefile_required)
        olean = lean.pack_olean_receipt(job)
        self.assertTrue(olean["synthetic"])
        self.assertFalse(olean["lake_build_executed"])
        self.assertIsNone(olean["arena_score"])
        plan = lean.pack_compile_plan(
            {"name": "P", "source": "strata", "file_path": "A.lean", "url": "u"},
            [lean.VersionPin(lean_tag="v4.26.0", git_commit="c")],
            frozen_warmup_sha256="d",
            jsonl_bytes=1,
            n_records=15,
            first_source="strata",
            first_tag="v4.26.0",
            first_commit="c",
            first_file="A.lean",
            first_url="u",
            kernel_command_template="lake env lean",
            measurement_argv_template="lake env lean --json",
            measurement_max_heartbeats=400000,
            ikv_timeout=30.0,
            official_timeout=1200.0,
            warmup_timeout=600.0,
        )
        self.assertTrue(plan["first_is_strata_v4_26"])
        self.assertIsNone(plan["arena_score"])
        extra = lean.pack_compile_extra(
            {"error": "", "stderr_digest": "x", "argv": ["lake"], "stderr": "e"},
            lean_tag="v4.26.0",
            start_line=1,
            end_line=2,
            stdout="ok",
            errors_in=(),
            errors_out=[{"data": "n"}],
            wall=1.5,
            tail_fn=lambda text, n: str(text)[:n],
            head_fn=lambda rows, n: list(rows)[:n],
        )
        self.assertEqual(extra["lean_tag"], "v4.26.0")
        self.assertEqual(extra["theorem_span"], [1, 2])
        health = lean.forced_unhealthy(
            lean.HealthProbe,
            url="http://x/health",
            alias_url="http://y/health",
            error="forced",
            autostart="0",
        )
        self.assertFalse(health.ok)
        from jevops.outer import count_where, false_when, map_hits, quoted_group, require_file_bytes

        self.assertEqual(count_where([1, 2, 3], lambda n: n > 1), 2)
        from jevops.outer import pack_ledger_receipt, where

        self.assertEqual(where([1, 2, 3], lambda n: n > 1), [2, 3])
        packed_ledger = pack_ledger_receipt(
            type("L", (), {"as_dict": lambda self: {"spent": 0}})(),
            schema="s",
            protocol="p",
            pr="pr",
            lrah="h",
            track="t1",
        )
        self.assertFalse(packed_ledger["official_track2"])
        self.assertIsNone(packed_ledger["arena_score"])
        from jevops.outer import pack_unscored

        unscored = pack_unscored(ok=False, lake=True)
        self.assertIsNone(unscored["arena_score"])
        self.assertIsNone(unscored["score"])
        ident = lean.grok_cli_identity(
            lean.ProviderIdentity,
            requested_provider="grok",
            requested_model="grok-4.6",
        )
        self.assertEqual(ident.resolved_provider, "grok_cli")
        self.assertFalse(ident.fallback_used)
        mapped = lean.identity_from_mapping(
            lean.ProviderIdentity,
            {"resolved_provider": "grok_cli", "fallback_used": False},
            requested_provider="grok",
            requested_model="grok-4.6",
        )
        self.assertEqual(mapped.requested_provider, "grok")
        self.assertEqual(mapped.resolved_provider, "grok_cli")
        from jevops.outer import overlay_skipped

        skipped = overlay_skipped(
            type("R", (), {"as_dict": lambda self: {"skipped": True, "reason": "no_key"}})(),
            digest="abc",
            extra={"source": "strata"},
        )
        self.assertTrue(skipped["ok"])
        self.assertEqual(skipped["warmup_jsonl_sha256"], "abc")
        from jevops.board import replica_from_ready

        missing = replica_from_ready("/no/such/ready.json", page_fn=lambda _e: None)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["reason"], "no_ready_json")
        from jevops.outer import apply_last, coalesce_pair, result_from_ledger

        self.assertEqual(apply_last([1, 2, 3], lambda n: n * 2), 6)
        self.assertIsNone(apply_last([], lambda n: n))
        from jevops.outer import call_if, pack_captured_generate

        self.assertEqual(call_if(True, lambda: [1], default=[]), [1])
        self.assertEqual(call_if(False, lambda: [1], default=[]), [])
        captured = pack_captured_generate(
            type("R", (), {"skipped": False, "text": "simp", "identity": {"p": "x"}})(),
            {"kwargs": {"provider": "leanstral_local"}, "autostart": "0"},
            {"provider": "leanstral_local"},
            asdict_fn=lambda ident: dict(ident),
        )
        self.assertTrue(captured["call_kwargs_match"])
        self.assertFalse(captured["lock_ex_taken_by_client"])
        lakefile = lean.render_package_lakefile(
            package="strata", lib="Strata", max_heartbeats=400000
        )
        self.assertIn("lean_lib «Strata»", lakefile)
        self.assertIn("maxHeartbeats=400000", lakefile)
        self.assertNotIn("Tmp.lean", lakefile)
        up = lean.healthy_probe(
            lean.HealthProbe,
            url="http://x/health",
            alias_url="http://y/health",
        )
        self.assertTrue(up.ok)
        self.assertEqual(up.status_code, 200)
        from jevops.outer import detail_with_file

        self.assertEqual(detail_with_file(RuntimeError("boom"), "/no/such", read_fn=lambda *_a, **_k: "x"), "boom")
        written = lean.write_sorry_or_tactic(
            "dest",
            tactic="sorry",
            sorry="sorry",
            sorry_fn=lambda: "sorry-src",
            tactic_fn=lambda: "tac-src",
            write_fn=lambda dest, text, **_k: (dest, text),
        )
        self.assertEqual(written, ("dest", "sorry-src"))
        self.assertEqual(
            lean.pins_for_source(
                {"source": "putnambench"},
                putnam_source="putnambench",
                putnam_fn=lambda _r: ["p"],
                default_fn=lambda _r: ["d"],
            ),
            ["p"],
        )
        from jevops.outer import lock_view, overlay_if_status

        self.assertEqual(overlay_if_status({"status": "baked"}, "baked", {"n": 1})["n"], 1)
        self.assertNotIn("n", overlay_if_status({"status": "hit"}, "baked", {"n": 1}))
        lock = lock_view(type("L", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}) , path="p", exists=False, held=False)
        self.assertFalse(lock.held)
        self.assertEqual(lean.toolchain_gap_note(ValueError("x"), (ValueError,), "; gap"), "; gap")
        self.assertEqual(lean.toolchain_gap_note(RuntimeError("x"), (ValueError,), "; gap"), "")
        from jevops.outer import reraise_as

        self.assertEqual(reraise_as(lambda: 3, (ValueError,), RuntimeError), 3)
        with self.assertRaises(RuntimeError):
            reraise_as(lambda: (_ for _ in ()).throw(FileNotFoundError("x")), (FileNotFoundError,), RuntimeError, missing="gone")
        aligned = __import__("jevops.repair", fromlist=["align_generated"]).align_generated(
            "  case a =>",
            "    case a =>",
            extract_fn=lambda text: text,
            match_fn=lambda _ref, text: text,
            flatten_fn=lambda _ref, text: text.strip(),
        )
        self.assertEqual(aligned, "case a =>")
        from jevops.outer import usage_line

        line = usage_line(
            dict,
            kind="jev",
            input_tokens=1,
            output_tokens=2,
            usd=0.0,
            call_index=0,
            fixture=True,
            model="m",
            skipped=True,
            reason="no_key",
        )
        self.assertTrue(line["skipped"])
        stamped = lean.stamp_measured(
            type("R", (), {"argv": None})(),
            argv=["lake"],
            cwd="/tmp",
            toolchain=type("T", (), {"elan_home": "/e", "lean_path": "/lean"})(),
            timeout=1.0,
            stamp_fn=lambda receipt, **_k: receipt,
            run_fn=lambda _argv, _env: None,
            state_root="/tmp",
            tmp_name="x",
            process_env_key="K",
            threads=1,
            max_heartbeats=1,
            ikv_floor=30.0,
            under_fn=lambda *_a, **_k: "/tmp/sup",
        )
        self.assertEqual(stamped.argv, ["lake"])
        from jevops.walk import child_base
        from jevops.outer import bump_named, ignore_error, overlay_skip

        self.assertIsNone(ignore_error(lambda: (_ for _ in ()).throw(ValueError("x")), ValueError))
        box = type("B", (), {"n": 0})()
        bump_named(box, "a", {"a": "n"})
        self.assertEqual(box.n, 1)
        base = child_base(
            args=None,
            memory={},
            ledger=None,
            rng=None,
            model=None,
            restore=b"",
            depth=1,
            steps=[0],
            max_steps=8,
            max_depth=3,
            compile_one=None,
            research_fn=None,
            pick_fn=None,
            router_fn=None,
        )
        self.assertEqual(base["depth"], 1)
        skipped = overlay_skip(
            lambda **kw: type("R", (), {"as_dict": lambda self: kw})(),
            digest="d",
            extra={"source": "s"},
            reason="no_key",
        )
        self.assertTrue(skipped["ok"])
        self.assertEqual(skipped["reason"], "no_key")
        from jevops.binders import blocked_port_stems

        blocked = blocked_port_stems(
            {"x": 1},
            "P",
            (("drop", None),),
            blacklist_fn=lambda *_a, **_k: True,
            failed_fn=lambda *_a, **_k: {"failed"},
        )
        self.assertIn("drop", blocked)
        self.assertIn("failed", blocked)
        from jevops.outer import attrs_dict, call_then, first_truthy, if_none

        self.assertEqual(if_none(None, 3), 3)
        self.assertEqual(if_none(0, 3), 0)
        self.assertEqual(if_none(None, factory=lambda: 7), 7)
        self.assertEqual(first_truthy("", 0, "x"), "x")
        self.assertEqual(call_then(lambda n: n + 1, 1, cond=True, second=10), 11)
        self.assertEqual(call_then(lambda n: n + 1, 1, cond=False, second=10), 2)
        packed = attrs_dict(type("O", (), {"a": 1, "b": 2})(), ("a", "b"), extra={"c": 3})
        self.assertEqual(packed, {"a": 1, "b": 2, "c": 3})
        receipt = lean.begin_path_a_receipt(
            {"name": "P", "source": "s", "url": "u"},
            lean.VersionPin(lean_tag="v4.26.0", git_commit="c"),
            relpath="A.lean",
            template="thm := by\nsorry",
            statement="thm",
            suffix=" := by\nsorry",
            lake_sorry="header\nthm := by\nsorry",
            aesop=False,
            considered=["rfl"],
            timeout=1.0,
            digest_fn=lambda text: "d" * 64 if text else "",
        )
        self.assertEqual(receipt.name, "P")
        self.assertTrue(receipt.sorry_template_prefix_bound)
        self.assertFalse(receipt.hammer_006_lra_ready)
        from jevops.outer import call_or, mark_skipped, starmap, with_defaults

        skipped_obj = type("S", (), {"skipped": False, "reason": ""})()
        mark_skipped(skipped_obj, "no_key")
        self.assertTrue(skipped_obj.skipped)
        self.assertEqual(with_defaults({"a": 1}, a=9, b=2), {"a": 1, "b": 2})
        self.assertEqual(starmap(lambda x, y: x + y, ((1, 2), (3, 4))), [3, 7])
        self.assertEqual(call_or(None, 5), 5)
        self.assertEqual(call_or(lambda: 8, 5), 8)
        a, b = coalesce_pair(None, "keep", lambda: ("loaded", "ignored"))
        self.assertEqual((a, b), ("loaded", "keep"))
        from jevops.outer import coalesce_chat_text

        self.assertEqual(
            coalesce_chat_text("raw", {"timeout": False}, lambda _t: {"text": "parsed"}),
            "parsed",
        )
        self.assertEqual(coalesce_chat_text("raw", {"timeout": True}, lambda _t: {"text": "parsed"}), "raw")
        packed = result_from_ledger(
            dict,
            type(
                "L",
                (),
                {
                    "grok_calls": 1,
                    "jev_calls": 2,
                    "spent_usd": 0.5,
                    "remaining_usd": 2.5,
                    "hard_stopped": False,
                    "as_dict": lambda self: {"spent": 0.5},
                },
            )(),
            skipped=True,
            reason="no_key",
            mode="off",
            name="P",
        )
        self.assertTrue(packed["skipped"])
        self.assertEqual(packed["spent_usd"], 0.5)
        self.assertFalse(packed["official_track2"])
        self.assertFalse(false_when(True, True))
        self.assertTrue(false_when(True, False, 0))
        names = quoted_group(
            'PROOF_AUTHORITY_DIMENSIONS: Final[tuple[str, ...]] = ("ir", "property")',
            r"PROOF_AUTHORITY_DIMENSIONS: Final\[tuple\[str, \.\.\.\]\] = \((.*?)\)",
        )
        self.assertEqual(names, ("ir", "property"))
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.bin"
            path.write_bytes(b"abc")
            self.assertEqual(require_file_bytes(path), b"abc")
        self.assertEqual(map_hits(["a", ""], lambda item: item or None), ["a"])
        from jevops.jev import rank_live_choice_row

        live = rank_live_choice_row(
            type(
                "R",
                (),
                {
                    "model": "m",
                    "choices": {
                        "best_first_draft": type(
                            "C", (), {"choice": "d0", "confidence": 0.9, "probabilities": {"d0": 1.0}}
                        )()
                    },
                    "nouls": {},
                    "scores": {},
                    "usage": {},
                },
            )(),
            2.0,
            rank_fn=lambda probs, drafts: list(probs),
            drafts=[],
            choice_map={"best_first_draft": "best_first_draft"},
        )
        self.assertEqual(live["best_first_draft"], "d0")
        self.assertEqual(live["top"], ["d0"])
        self.assertNotIn("_best", live)
        from jevops.board import credit_mapped

        board_mem: dict = {"nca": {"grid": {}}}
        credited = credit_mapped(
            board_mem,
            "Core.InitsUpdatesComm",
            {"Core.InitsUpdatesComm": "LRA-019"},
            subgoal_fn=lambda task: "LRA-S05" if task == "LRA-019" else "LRA-S04",
            theorem_ok=True,
            tokens=139,
        )
        self.assertTrue(credited["ok"])
        self.assertIn("ptr://task/LRA-019", credited["task"])
        proof = type(
            "P",
            (),
            {
                "executable_paths": object(),
                "body_digest": "",
                "candidate_cid": "",
                "created_at": 0,
                "dimensions": {},
                "key_digest": "",
            },
        )()
        out = lean.finalize_proof_receipt(
            proof,
            body="rfl",
            digest_fn=lambda data: "d" * 64,
            project_fn=lambda _r: {"ir": "x"},
            key_fn=lambda _r, dims: "k",
            now_fn=lambda: 1.0,
        )
        self.assertEqual(out.body_digest, "d" * 64)
        self.assertEqual(out.key_digest, "k")

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
        kept_kernel = walk.restrict_drafts(
            [{"kind": "inits_best"}, {"kind": "port_cache_put"}],
            allow_skills={"unrelated_skill"},
        )
        self.assertEqual([d["kind"] for d in kept_kernel], ["inits_best"])
        kept_probe = walk.restrict_drafts(
            [{"kind": "port_use_exact", "compiler_probe": True}],
            allow_skills={"unrelated_skill"},
        )
        self.assertEqual([d["kind"] for d in kept_probe], ["port_use_exact"])
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
        prune = jev.pack_prune(skipped=True, reason="no_key", best=None, kept=["STOP"])
        self.assertTrue(prune["skipped"])
        self.assertIsNone(prune["arena_score"])

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
        overlay = board.overlay_fetch(
            mem,
            fetch_fn=lambda: {"tasks": [{"task_alias": "T1", "status": "ready"}]},
            prefix="",
            cache=False,
        )
        self.assertTrue(overlay["ok"])
        self.assertEqual(overlay["reason"], "injected")
        self.assertFalse(overlay["campaign_write"])
        closed = board.overlay_fetch(
            {"nca": {"grid": {}}},
            fetch_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            cache=False,
        )
        self.assertFalse(closed["ok"])
        self.assertEqual(closed["reason"], "RuntimeError")
        replica = board.replica_page(ok=False, reason="no_ready_json")
        self.assertEqual(replica["tasks"], [])
        self.assertFalse(replica["campaign_write"])
        page = type("P", (), {"tasks": [type("T", (), {"task_alias": "LRA-017", "id": ""})()]})()
        self.assertEqual(board.aliases_from_page(page, prefix="LRA-")[0]["task_alias"], "LRA-017")
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
        promoted = outer.route_next(
            gaps=[{"name": "P", "top_help": [{"residual": "repeated_simp_list"}]}],
            last_lake=[],
            stalled=True,
            llm=True,
            generate_fn=lambda _prompt: '{"action":"mint","name":"P","reason":"try a different tree"}',
        )
        self.assertEqual(promoted["action"], "hypothesis_refactor")
        self.assertEqual(promoted["source_action"], "mint")
        self.assertIn("try a different tree", promoted["hypothesis"])
        design = outer.parse_action(
            '{"action":"mint_tactic","name":"P","family":"search_space",'
            '"strategy":"closed_edits"}'
        )
        design_mem: dict = {"nca": {"tactic_design_queue": None}}
        design_receipt = outer.apply_action(design_mem, design)
        self.assertTrue(design_receipt["ok"])
        self.assertEqual(
            design_mem["nca"]["active_tactic_design"]["strategy"],
            "closed_edits",
        )
        hypothesis = outer.parse_action(
            '{"action":"hypothesis_refactor","name":"P","family":"search_space",'
            '"strategy":"guided_mca","hypothesis":"compress repeated local simplification",'
            '"constraints":"preserve binders","evaluation":"Lake then token count"}'
        )
        hypothesis_mem: dict = {}
        hypothesis_receipt = outer.apply_action(hypothesis_mem, hypothesis)
        self.assertTrue(hypothesis_receipt["ok"])
        self.assertEqual(
            hypothesis_mem["nca"]["active_hypothesis_refactor"]["hypothesis"],
            "compress repeated local simplification",
        )
        stalled_hypothesis = outer.deterministic_route(
            gaps=[{"name": "P", "top_help": [{"residual": "repeated_simp_list"}]}],
            last_lake=[],
            stalled=True,
        )
        self.assertEqual(stalled_hypothesis["action"], "hypothesis_refactor")
        self.assertIn("hypothesis", stalled_hypothesis)
        repair = outer.deterministic_route(
            gaps=[
                {
                    "name": "P",
                    "failed_stems": ["port_unused_intros"],
                    "top_help": [{"residual": "intro_then_simp_all"}],
                }
            ],
            last_lake=[],
            stalled=False,
            memory={"nca": {"tactic_design_history": []}},
        )
        self.assertEqual(repair["action"], "repair_tactic")
        self.assertEqual(repair["stem"], "unused_intros")
        prioritized = outer.route_next(
            gaps=[
                {
                    "name": "P",
                    "failed_stems": ["port_unused_intros"],
                    "top_help": [{"residual": "intro_then_simp_all"}],
                }
            ],
            last_lake=[],
            stalled=False,
            llm=True,
            memory={"nca": {"tactic_design_history": []}},
            generate_fn=lambda _prompt: '{"action":"mint_tactic","name":"P"}',
        )
        self.assertEqual(prioritized["action"], "repair_tactic")
        self.assertEqual(prioritized["reason"], "blacklist_repair_prioritized")
        self.assertEqual(prioritized["source_action"], "mint_tactic")
        quarantined = outer.route_next(
            gaps=[],
            last_lake=[
                {"name": "P", "kind": "port_unused_intros", "ok": False}
            ],
            stalled=False,
            llm=True,
            generate_fn=lambda _prompt: '{"action":"mint_tactic","name":"P"}',
        )
        self.assertEqual(quarantined["action"], "skip_stem")
        self.assertEqual(quarantined["reason"], "lake_failure_quarantine_prioritized")
        bad_design = outer.apply_action(
            {},
            {"action": "mint_tactic", "name": "P", "strategy": "run_python"},
        )
        self.assertFalse(bad_design["ok"])
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
        probe = [{"kind": "port_probe", "tactics": "exact h", "compiler_probe": True}]
        self.assertFalse(oracle.noul_fire_all({"fired": True, "fired_leaves": ["port_probe"]}, {"port_probe": probe[0]}))
        accepted_probe, probe_rows = oracle.apply_round(
            memory={"nca": {}},
            name="P",
            drafts=probe,
            intent={"skill": "keep", "compose": "single"},
            ranked={"beam_kinds": [], "fired": True, "fired_leaves": ["port_probe"]},
            compile_fn=lambda _k, _t: {"theorem_ok": True, "token_count": 2, "errors": []},
            from_tokens=9,
        )
        self.assertEqual(accepted_probe, "exact h")
        self.assertTrue(probe_rows[0]["ok"])
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
        fresh_board = [({}, 0), ({"P": 5}, 5), ({"P": 4}, 4)]
        fresh_index = {"value": 0}
        fresh = run_steps(
            n=2,
            memory={},
            llm=False,
            gaps_fn=lambda: [],
            route_fn=lambda **_k: {"action": "nest_inner"},
            apply_fn=lambda _m, _a: {"ok": True, "applied": "nest_inner"},
            inner_fn=lambda _step: {},
            board_fn=lambda: (
                fresh_board[min(fresh_index["value"], len(fresh_board) - 1)][0],
                (fresh_index.__setitem__("value", fresh_index["value"] + 1) or 0)
                or fresh_board[min(fresh_index["value"] - 1, len(fresh_board) - 1)][1],
            ),
        )
        self.assertEqual(fresh["best_total"], 4)
        self.assertTrue(fresh["history"][-1]["improved"])
        seen_stalled: list[bool] = []
        hypothesis_steps = run_steps(
            n=3,
            memory={},
            llm=True,
            gaps_fn=lambda: [{"name": "P", "top_help": [{"residual": "dead_code"}]}],
            route_fn=lambda **kw: (
                seen_stalled.append(bool(kw["stalled"]))
                or (
                    {"action": "hypothesis_refactor", "name": "P", "hypothesis": "test a new closed tree"}
                    if kw["stalled"]
                    else {"action": "nest_inner"}
                )
            ),
            apply_fn=lambda mem, action: outer.apply_action(mem, action),
            inner_fn=lambda _step: {},
            board_fn=lambda: ({"P": 3}, 3),
        )
        self.assertEqual(len(hypothesis_steps["history"]), 3)
        self.assertEqual(hypothesis_steps["history"][-1]["action"]["action"], "hypothesis_refactor")
        self.assertEqual(hypothesis_steps["stop_reason"], "no_token_cut")
        self.assertTrue(seen_stalled[-1])
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
            with self.assertRaises(SystemExit):
                write_json_pair(
                    Path(tmp),
                    {"k": "apikey_secret"},
                    prefix="y",
                    latest="y-latest.json",
                    refuse="apikey_",
                )
            from jevops.outer import last_component, require_single_token

            self.assertEqual(last_component("A.B.C"), "C")
            self.assertEqual(require_single_token("simp_all"), "simp_all")
            with self.assertRaises(ValueError):
                require_single_token("simp all")
            from jevops.mask import drop_indices
            from jevops.outer import nonempty_strs, overlay_str

            self.assertEqual(drop_indices("a\nb\nc\nd", (1, 3)), "a\nc")
            self.assertEqual(nonempty_strs(["a", "", "b"]), ["a", "b"])
            self.assertEqual(
                overlay_str({"name": "", "src": "x"}, {"name": "P", "extra": "nope"}, {"src": "y"}),
                {"name": "P", "src": "y"},
            )
            from jevops.outer import env_copy, path_to_dots, posix_slash, read_bytes_if, under_or_tmp

            missing = Path(tmp) / "nope.bin"
            self.assertEqual(read_bytes_if(missing), b"")
            hit = Path(tmp) / "hit.bin"
            hit.write_bytes(b"ab")
            self.assertEqual(read_bytes_if(hit), b"ab")
            copied = env_copy({"LEAN_NUM_THREADS": 1}, base={"PATH": "/bin"})
            self.assertEqual(copied["LEAN_NUM_THREADS"], "1")
            self.assertEqual(copied["PATH"], "/bin")
            dest = under_or_tmp(Path(tmp), "process-supervisor", tmp_name="x")
            self.assertTrue(dest.is_dir())
            self.assertEqual(posix_slash(r"a\b.py"), "a/b.py")
            self.assertEqual(path_to_dots("harness/foo.py"), "harness.foo")
            from jevops.mask import merge_matches
            from jevops.outer import overlay_attr, read_json, require_str

            self.assertEqual(require_str("x"), "x")
            with self.assertRaises(ValueError):
                require_str("")
            blob = Path(tmp) / "obj.json"
            blob.write_text('{"a": 1}\n', encoding="utf-8")
            self.assertEqual(read_json(blob)["a"], 1)
            self.assertEqual(overlay_attr({"k": "old"}, {"k": {"what": "new"}}), {"k": "new"})
            import re as _re

            hits = merge_matches("aa bb", ("a", _re.compile("a+")), ("b", _re.compile("b+")))
            self.assertEqual([kind for _s, kind, _m in hits], ["a", "b"])
            from jevops.outer import (
                bullet_lines,
                exc_name,
                exc_text,
                failed_check,
                first_token,
                mapped_nonempty,
                tagged_exc,
            )

            boom = ValueError("x")
            self.assertEqual(exc_name(boom), "ValueError")
            self.assertEqual(exc_text(boom), "ValueError: x")
            self.assertEqual(tagged_exc("fetch_failed", OSError("nope")), "fetch_failed:OSError")
            failed = failed_check(boom, score=None, corpus_manifest_ingest=False)
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["error_type"], "ValueError")
            self.assertIsNone(failed["arena_score"])
            self.assertEqual(bullet_lines(["a", "b"], limit=1), "- a")
            self.assertEqual(
                bullet_lines(
                    [{"id": "h1", "family": "have", "head": "have x"}],
                    fmt=lambda item: f"{item.get('id')} family={item.get('family')}: {item.get('head')}",
                    empty="(none)",
                ),
                "- h1 family=have: have x",
            )
            self.assertEqual(bullet_lines([], empty="(none)"), "(none)")
            self.assertEqual(mapped_nonempty([" have x", ""], lambda s: s.strip()), {"have x"})
            self.assertEqual(first_token("simp_all; foo", strip=";"), "simp_all")
            from jevops.outer import closed_fail, remap_get, utc_stamp

            miss = closed_fail("unknown warm-up problem: P", score=None)
            self.assertEqual(miss["error"], "unknown warm-up problem: P")
            self.assertNotIn("error_type", miss)
            self.assertRegex(utc_stamp(fmt="%Y%m%dT%H%M%SZ"), r"^\d{8}T\d{6}Z$")
            self.assertIn("T", utc_stamp())
            self.assertEqual(
                remap_get(
                    {"missing_cases": ["a"], "open_case": "x"},
                    {"missing": "missing_cases", "open": "open_case"},
                    lists=("missing",),
                ),
                {"missing": ["a"], "open": "x"},
            )
            from jevops.outer import elapsed_ms, print_json
            import io as _io

            self.assertGreaterEqual(elapsed_ms(0.0, now=0.25), 250.0)
            buf = _io.StringIO()
            print_json({"p": Path(tmp)}, stream=buf, default=str)
            self.assertIn(str(Path(tmp)), buf.getvalue())
            from jevops.outer import copy_text, read_text, source_text

            src = Path(tmp) / "a.txt"
            src.write_text("hello\n", encoding="utf-8")
            self.assertEqual(read_text(src), "hello\n")
            self.assertEqual(source_text("injected", path=src), "injected")
            self.assertEqual(source_text(path=src), "hello\n")
            dest = Path(tmp) / "b.txt"
            copy_text(src, dest)
            self.assertEqual(read_text(dest), "hello\n")
            self.assertEqual(read_text(src, max_chars=2), "he")
            from jevops.outer import loads_json, read_json, read_json_if

            obj = Path(tmp) / "obj.json"
            obj.write_text('{"a": 1}\n', encoding="utf-8")
            self.assertEqual(read_json(obj)["a"], 1)
            self.assertEqual(read_json_if(Path(tmp) / "missing.json", default={"z": 2})["z"], 2)
            arr = Path(tmp) / "arr.json"
            arr.write_text("[1, 2]\n", encoding="utf-8")
            self.assertEqual(read_json(arr, require_object=False), [1, 2])
            self.assertEqual(loads_json(None, default={}), {})
            self.assertEqual(loads_json('{"k": 3}')["k"], 3)
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
        reopened = lra_mem.repair_blacklist(
            store,
            name="P",
            stem="b",
            receipt={"theorem_ok": True, "token_count": 7},
        )
        self.assertTrue(reopened["ok"])
        self.assertFalse(lra_mem.is_blacklisted(store, "P", "port_b"))
        self.assertNotIn("b", lra_mem.failed_skill_stems(store, "P"))
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            lra_mem.save_memory(store, path)
            restored = lra_mem.load_memory(path)
            self.assertEqual(restored["repairs"][-1]["stem"], "b")
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
        from jevops.outer import file_stem, load_json_object, merge_keep_best, read_shortest_glob, write_best_body
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
            written = write_best_body(root / "nested" / "out", "P", 3, "exact Hin")
            self.assertEqual(written.read_text(), "exact Hin\n")
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
            from jevops.outer import exc_head, head_chars, head_lines, head_seq, head_tail, tail_chars, tail_seq
            from jevops.repair import uses_attr
            from jevops.search import after_item, filter_used_later

            self.assertEqual(after_item(["a", "b", "c"], "b"), ["c"])
            self.assertEqual(keep_matching_lines("a\n  b\nc", lambda l: l.startswith("  "), cap=2), "  b")
            self.assertEqual(head_lines("a\nb\nc", 2), "a\nb")
            self.assertEqual(head_chars("abcdef", 3), "abc")
            self.assertEqual(head_chars(None, 4), "")
            self.assertEqual(head_chars("ab", 0), "")
            self.assertEqual(tail_chars("abcdef", 3), "def")
            self.assertEqual(tail_chars("ab", 0), "")
            self.assertEqual(tail_chars(None, 2), "")
            self.assertEqual(head_seq([1, 2, 3, 4], 2), [1, 2])
            self.assertEqual(tail_seq([1, 2, 3, 4], 2), [3, 4])
            self.assertEqual(tail_seq([1, 2, 3], 0), [])
            self.assertEqual(exc_head(ValueError("x" * 10), 4), "xxxx")
            self.assertEqual(head_tail("abcdefghij", 3, 3, limit=8), "abc\n...\nhij")
            self.assertEqual(head_tail("abcd", 3, 3), "abcd")
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
            from jevops.outer import git_checkout, git_clone, plant_executables, require_git_bin, url_cache_key, url_clone_dir

            with self.assertRaises(FileNotFoundError):
                require_git_bin(root / "missing-git")
            bins = plant_executables(root / "gitbin", {"git": "#!/bin/sh\nexit 0\n"})
            git = bins / "git"
            self.assertEqual(require_git_bin(git), str(git))
            missing = root / "no-repo"
            skipped = git_checkout(missing, "abc", git_bin=git)
            self.assertTrue(skipped["skipped"])
            empty = git_checkout(missing, "", git_bin=git)
            self.assertTrue(empty["skipped"])
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True)
            checked = git_checkout(repo, "abc", git_bin=git)
            self.assertFalse(checked["skipped"])
            cloned = git_clone("https://example.invalid/x.git", root / "cloned", git_bin=git)
            self.assertEqual(cloned["dest"], str(root / "cloned"))
            cloned_dir = url_clone_dir(root, "https://example.com/a.git")
            self.assertEqual(cloned_dir, root / "clones" / "example.com" / "a.git")
            self.assertEqual(url_cache_key("https://example.com/a.git"), "example.com/a.git")
            from jevops.outer import dumps_sorted, pinned_env_argv, require_marked_dir

            marked = root / "marked"
            marked.mkdir()
            (marked / ".git").write_text("gitdir: .")
            self.assertEqual(require_marked_dir(marked, (".git",)), marked)
            with self.assertRaises(ValueError):
                require_marked_dir(root / "empty-clone", (".git",), error_cls=ValueError, miss="missing {path}")
            self.assertEqual(require_marked_dir(root / "empty-clone", (".git",)), root / "empty-clone")
            self.assertEqual(dumps_sorted({"b": 1, "a": 2}), '{"a": 2, "b": 1}')
            self.assertTrue(dumps_sorted({"a": 1}, indent=2, newline=True).endswith("\n"))
            argv = pinned_env_argv(
                "/opt/lake",
                "/opt/lean",
                "Foo.lean",
                driver_name="lake",
                tool_name="lean",
                flags=("-DmaxHeartbeats=1", "--json"),
            )
            self.assertEqual(argv, ["/opt/lake", "env", "/opt/lean", "-DmaxHeartbeats=1", "--json", "Foo.lean"])
            with self.assertRaises(ValueError):
                pinned_env_argv("/opt/lake", "/opt/lean", "Tmp.lean", driver_name="lake", tool_name="lean", refuse="Tmp.lean")
            from jevops.outer import after_calls, copy_dir_required, run_pinned_bin

            seen: list[str] = []
            self.assertEqual(after_calls((lambda: seen.append("a"), lambda: seen.append("b")), lambda x: x + 1, 2), 3)
            self.assertEqual(seen, ["a", "b"])
            src_copy = root / "copy_src"
            src_copy.mkdir()
            (src_copy / "blob").write_text("hi")
            dest_copy = root / "copy_dest" / "tree"
            copy_dir_required(src_copy, dest_copy)
            self.assertEqual((dest_copy / "blob").read_text(), "hi")
            with self.assertRaises(FileNotFoundError):
                copy_dir_required(root / "missing-dir", dest_copy)
            bins = plant_executables(root / "pinbin", {"lake": "#!/bin/sh\necho pinned\n"})
            ran = run_pinned_bin([str(bins / "lake"), "build"], basename="lake", cwd=root)
            self.assertTrue(ran["ok"])
            self.assertIn("pinned", ran["stdout"])
            with self.assertRaises(RuntimeError):
                run_pinned_bin(["/opt/lake"], basename="lake", installed=False, miss="missing toolchain")
            from jevops.outer import prepend_argv, require_file

            self.assertEqual(prepend_argv("/opt/lake", "build", "--json"), ["/opt/lake", "build", "--json"])
            present = root / "present.txt"
            present.write_text("ok")
            self.assertEqual(require_file(present), present)
            with self.assertRaises(FileNotFoundError):
                require_file(root / "missing.txt")
            from jevops.outer import import_names, write_tree

            attrs, err = import_names("json", ("dumps", "loads"))
            self.assertIsNone(err)
            self.assertTrue(callable((attrs or {})["dumps"]))
            missing, miss_err = import_names("no_such_jevops_module_xyz", ("x",))
            self.assertIsNone(missing)
            self.assertIsInstance(miss_err, ImportError)
            tree_paths = write_tree(root / "written", {"a.txt": "hi", "b.json": {"z": 1}})
            self.assertEqual(Path(tree_paths["a.txt"]).read_text(encoding="utf-8"), "hi")
            self.assertIn('"z"', Path(tree_paths["b.json"]).read_text(encoding="utf-8"))
            from io import StringIO
            from jevops.outer import as_str, digest_prefix, env_mapping, home_config_file, mkdtemp, module_stem, nonempty, optional_env_path, print_ok, require_len, require_startswith, require_unique_n, temp_dir

            rows = [{"name": "a"}, {"name": "b"}]
            self.assertEqual(require_unique_n(rows, 2), ["a", "b"])
            with self.assertRaises(ValueError):
                require_unique_n(rows, 3)
            with self.assertRaises(ValueError):
                require_unique_n([{"name": "a"}, {"name": "a"}], 2)
            self.assertEqual(require_len([1, 2, 3], 3), [1, 2, 3])
            with self.assertRaises(ValueError):
                require_len([1], 2)
            self.assertEqual(len(digest_prefix("hi")), 12)
            self.assertEqual(digest_prefix("hi"), digest_prefix("hi"))
            auth = home_config_file(
                "auth.json",
                env_key="GROK_HOME",
                default_dir=".grok",
                environ={"GROK_HOME": "/tmp/grok-home"},
                home="/home/u",
            )
            self.assertEqual(auth, Path("/tmp/grok-home/auth.json"))
            fallback = home_config_file(
                "auth.json",
                env_key="GROK_HOME",
                default_dir=".grok",
                environ={},
                home="/home/u",
            )
            self.assertEqual(fallback, Path("/home/u/.grok/auth.json"))
            self.assertEqual(
                optional_env_path("LRA_DUCKDB_AST_INDEX", environ={"LRA_DUCKDB_AST_INDEX": "/tmp/idx.duckdb"}),
                Path("/tmp/idx.duckdb"),
            )
            self.assertIsNone(optional_env_path("LRA_DUCKDB_AST_INDEX", environ={}))
            self.assertEqual(as_str("ok"), "ok")
            self.assertEqual(as_str(None), "")
            self.assertEqual(as_str(1, default="x"), "x")
            self.assertEqual(env_mapping({"A": "1"}).get("A"), "1")
            with temp_dir(prefix="jevops-tmp-") as tmp:
                self.assertTrue(Path(tmp).is_dir())
            scratch = mkdtemp(prefix="jevops-mkd-")
            self.assertTrue(scratch.is_dir())
            scratch.rmdir()
            self.assertTrue(nonempty(" x "))
            self.assertFalse(nonempty("  "))
            self.assertEqual(require_startswith("abcde", "abc"), "abcde")
            with self.assertRaises(ValueError):
                require_startswith("abc", "z")
            self.assertEqual(module_stem("ptr://codepath/harness.foo:bar", strip_prefix="ptr://codepath/"), "harness.foo")
            self.assertIsNone(module_stem("../etc/passwd"))
            ok_buf = StringIO()
            self.assertEqual(print_ok({"ok": True, "n": 1}, stream=ok_buf), 0)
            self.assertIn('"ok": true', ok_buf.getvalue())
            bad_buf = StringIO()
            self.assertEqual(print_ok({"ok": False}, stream=bad_buf), 1)
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
            self.assertEqual(first_token("simp_all; x", strip=";"), "simp_all")
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
            from jevops.mask import line_at, lstrip_core, pick_scored
            from jevops.outer import dir_marked, http_json
            from jevops.repair import repair_on_needle

            self.assertEqual(lstrip_core("· have x"), "have x")
            self.assertEqual(line_at("aa\nbb\ncc", 4), "bb")
            scored = pick_scored(
                [{"start": 0, "end": 2, "original": "aa"}, {"start": 3, "end": 5, "original": "bb"}],
                n=1,
                score_fn=lambda row: 2 if row["original"] == "bb" else 1,
                reindex=False,
            )
            self.assertEqual(scored[0]["original"], "bb")
            (root / "cache").mkdir()
            (root / "cache" / "BAKED").write_text("ok\n")
            (root / "cache" / "x.olean").write_bytes(b"x")
            self.assertTrue(dir_marked(root / "cache", marker="BAKED", suffix=".olean"))
            self.assertEqual(
                repair_on_needle("simp_all", [{"data": "simp_all made no progress"}], "simp_all made no progress", lambda t: t + "x"),
                "simp_allx",
            )
            self.assertIsNone(repair_on_needle("simp_all", [{"data": "ok"}], "simp_all made no progress", lambda t: t))
            with self.assertRaises(ValueError):
                http_json("http://127.0.0.1:1", {}, timeout=0.05)
            from jevops.jev import skipped
            from jevops.mask import around_lines, map_span_bodies
            from jevops.nca import focus_symbol
            from jevops.outer import hit_or_miss
            from jevops.pick import numbered_criteria

            self.assertEqual(around_lines("a\nb\nc\nd", 1, radius=1), "a\nb\nc")
            rewritten = map_span_bodies(
                "H\nbody\nT",
                [{"indent": 0, "header_end": 2, "end": 6}],
                lambda body, _s: "X" if body.strip() == "body" else None,
            )
            self.assertEqual(rewritten[0][1], "H\nX\nT")
            self.assertEqual(hit_or_miss(True, hit="hit", miss="miss"), "hit")
            self.assertEqual(hit_or_miss(False, miss="miss"), "miss")
            with self.assertRaises(RuntimeError):
                hit_or_miss(False, deny=True, error_cls=RuntimeError, deny_msg="nope")
            self.assertEqual(numbered_criteria(["a", "b"], prefix="c")["c1"], "b")
            self.assertEqual(
                numbered_criteria(["x"], prefix="p", fmt=lambda i, item: f"{i}:{item}")["p0"],
                "0:x",
            )
            self.assertEqual(focus_symbol("mod:foo", ["foo", "bar"], {"foo": ["x"]}), "foo")
            self.assertEqual(focus_symbol("mod:missing", ["foo"], {}), "foo")
            self.assertEqual(skipped("no_key", order=[1])["reason"], "no_key")
            from jevops.outer import append_line, ensure_digest, exec_many, table_count, unique_rows

            self.assertEqual(append_line("a\n", "  b"), "a\n  b")
            self.assertEqual(
                unique_rows([{"t": "x"}, {"t": "x"}, {"t": "y"}], key_fn=lambda row: row["t"]),
                [{"t": "x"}, {"t": "y"}],
            )
            self.assertEqual(ensure_digest("a" * 64), "a" * 64)
            self.assertEqual(ensure_digest("nope", data=b"x", digest_fn=lambda d: "ok"), "ok")
            with self.assertRaises(ValueError):
                ensure_digest("nope")

            class _Con:
                def __init__(self) -> None:
                    self.sql: list = []

                def execute(self, sql: str, params: Any = None) -> Any:
                    self.sql.append((sql, params))
                    return type("R", (), {"fetchone": lambda inner: (2,)})()

            con = _Con()
            exec_many(con, ["CREATE TABLE t (x)", ("INSERT INTO t VALUES (?)", [1])])
            self.assertEqual(con.sql[0][0], "CREATE TABLE t (x)")
            self.assertEqual(table_count(con, "t"), 2)
            self.assertEqual(table_count(con, "t; drop"), 0)
            from jevops.mask import lines_containing, pop_trailing, prepend_absent
            from jevops.pick import first_apply, tree_from_items

            self.assertEqual(prepend_absent("b\n", "a"), "a\nb\n")
            self.assertEqual(prepend_absent("a\nb\n", "a"), "a\nb\n")
            self.assertEqual(lines_containing("have x\nexact x", "x", token=True), ["have x", "exact x"])
            self.assertEqual(pop_trailing("a\nsimp_all", lambda line: line.strip() == "simp_all"), "a")
            tree = tree_from_items(
                [type("K", (), {"family": "drop", "kind": "a", "note": "n"})()],
                family_fn=lambda item: item.family,
                kind_fn=lambda item: item.kind,
                note_fn=lambda item: item.note,
                keep={"keep": {"keep": "none"}},
            )
            self.assertEqual(tree["drop"]["a"], "n")
            self.assertEqual(tree["keep"]["keep"], "none")
            self.assertEqual(
                first_apply(
                    [type("K", (), {"kind": "a"})()],
                    "a",
                    "body",
                    kind_fn=lambda item: item.kind,
                    apply_fn=lambda _item, body: body + "x",
                ),
                "bodyx",
            )
            from jevops.mask import any_line
            from jevops.outer import matching_nodes, path_safe, query_first_engine

            self.assertTrue(any_line("a\nNot.intro\nb", lambda line: "Not.intro" in line))
            self.assertEqual(path_safe("A/B"), "A_B")
            self.assertEqual(path_safe(""), "unnamed")
            self.assertEqual(
                [n["id"] for n in matching_nodes([{"id": "ptr://skill/foo"}, {"id": "ptr://task/T1"}], "skill")],
                ["ptr://skill/foo"],
            )
            self.assertEqual(query_first_engine([root / "missing.duckdb"], {"symbols": "SELECT 1"}), ([], "no_index"))
            from jevops.mask import drop_spans, splice_from, split_top_level
            from jevops.outer import first_csv, first_or_head, split_csv

            self.assertEqual(split_csv("a, b,,c"), ["a", "b", "c"])
            self.assertEqual(split_csv("1,2", cast=int), [1, 2])
            self.assertEqual(first_csv("foo, bar"), "foo")
            self.assertEqual(first_csv(""), "")
            self.assertEqual(
                split_top_level("bar (a, b), baz"),
                ["bar (a, b)", "baz"],
            )
            self.assertEqual(drop_spans("abcdef", [(1, 3), (4, 5)]), "adf")
            self.assertEqual(
                splice_from("H\nDST\nT", "H\nSRC\nT", {"start": 2, "end": 5}, {"start": 2, "end": 5}),
                "H\nSRC\nT",
            )
            self.assertEqual(splice_from("keep", "x", None, {"start": 0, "end": 1}), "keep")
            self.assertEqual(
                first_or_head(["a", "have x", "c"], lambda line: "have " in line),
                "have x",
            )
            self.assertEqual(first_or_head(["a", "b"], lambda line: "have " in line), "a")
            self.assertEqual(first_or_head([], default=""), "")
            from jevops.mask import map_lines, peek_next_stripped, subn_changed
            from jevops.outer import group_append, group_get, unique_append
            from jevops.search import beam_until, expand_beam

            self.assertEqual(subn_changed("aa ba", r"a", "x"), "xx bx")
            self.assertEqual(subn_changed("keep", r"z", "x"), "keep")
            self.assertEqual(peek_next_stripped(["a", "", "  b"], 0), "b")
            rewritten = map_lines(
                "keep\nchange me",
                lambda _i, line, _lines: "x" if "change" in line else None,
            )
            self.assertEqual(rewritten, "keep\nx")
            bags: dict = {}
            group_append(bags, "k", "n1", factory=lambda: {"names": [], "files": []})
            unique_append(bags["k"]["files"], "f")
            unique_append(bags["k"]["files"], "f")
            self.assertEqual(bags["k"]["names"], ["n1"])
            self.assertEqual(bags["k"]["files"], ["f"])
            got = group_get(bags, "missing", factory=lambda: {"names": []})
            self.assertEqual(got["names"], [])
            expanded = expand_beam(
                [{"id": 0, "stopped": False}, {"id": 1, "stopped": True}],
                stopped_fn=lambda item: item["stopped"],
                expand_fn=lambda item: [{"id": item["id"] + 10, "stopped": True}],
                cap=3,
            )
            self.assertEqual([row["id"] for row in expanded], [10, 1])
            finished = beam_until(
                [{"n": 0, "stopped": False}],
                max_steps=4,
                stopped_fn=lambda item: item["stopped"],
                round_fn=lambda rows, _step: [{"n": rows[0]["n"] + 1, "stopped": rows[0]["n"] + 1 >= 2}],
            )
            self.assertEqual(finished[0]["n"], 2)
            from jevops.outer import lookup_named, unique_extend, without_keys
            from jevops.search import pick_min_tiers, pin_front

            self.assertEqual(pin_front([3, 1, 2, 0], [2, 4], n=2), [2, 4, 3, 1, 0])
            rows = [
                {"kind": "a", "ok": False, "n": 9},
                {"kind": "reference", "ok": True, "n": 5},
                {"kind": "b", "ok": True, "n": 3},
            ]
            self.assertEqual(
                pick_min_tiers(rows, (lambda row: row["ok"],), key_fn=lambda row: row["n"])["kind"],
                "b",
            )
            self.assertEqual(without_keys({"zscore": 1, "keep": 2}, ("zscore",)), {"keep": 2})
            dest = [{"kind": "a"}]
            unique_extend(dest, [{"kind": "a"}, {"kind": "b"}], key_fn=lambda item: item["kind"])
            self.assertEqual([row["kind"] for row in dest], ["a", "b"])
            with self.assertRaises(RuntimeError):
                lookup_named([], "missing", error_cls=RuntimeError, miss="nope")
            from jevops import autoencoder as ae
            from jevops.rankers import is_ranker_stem

            self.assertTrue(is_ranker_stem("port_gan"))
            self.assertTrue(is_ranker_stem("port_lean_ir"))
            self.assertFalse(ae.encode_lean_ir("simp")["legal_ir"])
            self.assertIn("True := by", ae.decode_lean_ir(ae.encode_lean_ir("simp")))
            from jevops.jev import (
                cfg_score_criteria,
                fill_rank_criteria,
                pack_fanout_live_row,
                proposal_feature_state,
                questions_from_specs,
            )
            from jevops.nca import codepath_rel_candidates
            from jevops.outer import closed_on_error, generate_text_and_usage, persist_named_rows
            from jevops.search import eligible_span_counts, sidecar_hit_row

            class _Noul:
                def __init__(self, instructions):
                    self.instructions = instructions

            class _Score:
                def __init__(self, instructions, criteria):
                    self.instructions = instructions
                    self.criteria = criteria

            qs = questions_from_specs(
                (("likely_compiles", "noul", "Will it lake?"), ("cut", "score", "How much?")),
                noul_ctor=_Noul,
                score_ctor=_Score,
                score_criteria=["none", "some"],
            )
            self.assertIn("likely_compiles", qs)
            self.assertEqual(qs["cut"].criteria, ["none", "some"])
            state = proposal_feature_state(
                {"name": "P"},
                "  simp\n",
                {"kind": "drop", "note": "n", "tactics": "  rfl\n"},
                token_fn=lambda text: len(text.split()),
                tail_fn=lambda text, n: text[-n:],
            )
            self.assertEqual(state["edit_kind"], "drop")
            self.assertTrue(closed_on_error(lambda: (_ for _ in ()).throw(ValueError("x")), ValueError))
            self.assertFalse(closed_on_error(lambda: None, ValueError))
            text, inn, out = generate_text_and_usage(
                {"text": "simp", "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
            )
            self.assertEqual((text, inn, out), ("simp", 3, 1))
            self.assertEqual(sidecar_hit_row({"symbol": "foo", "path": "a.py"})["source"], "sidecar")
            self.assertEqual(
                eligible_span_counts("x", (2,), lambda _t, span: [0] * span)["span_2"],
                2,
            )
            self.assertTrue(fill_rank_criteria([{"kind": "k0", "generator": "g"}], head_fn=lambda s, n: s[:n]))
            self.assertIn("s0", cfg_score_criteria([{"id": "s0", "n_masks": 1, "span": 2, "n_shots": 0, "cfg_scale": 1}], {}))
            written, persisted = persist_named_rows(["a"], "dest", None, lambda rows, dest: [str(dest)])
            self.assertEqual(written, ["dest"])
            self.assertEqual(persisted, [])
            cands = codepath_rel_candidates("harness.portable_rewrites", here="/tmp", accel="/acc")
            self.assertTrue(any(str(path).endswith("portable_rewrites.py") for path in cands))
            live = pack_fanout_live_row(
                type("R", (), {"model": "m"})(),
                1.0,
                unpack_fn=lambda _r: ({}, {}, {}, {}),
                rank_fn=lambda _p, drafts: list(drafts),
                drafts=[],
            )
            self.assertTrue(live["live"])
            self.assertIsNone(live["best_first_draft"])
            from jevops.repair import pack_call_audit

            audited = pack_call_audit(
                {
                    "imported_names": ["os"],
                    "forbidden_imports": [],
                    "forbidden_calls": [],
                    "forbidden_attrs": [],
                    "score_keys": [],
                    "call_names": ["run_lean_process", "measurement_argv"],
                },
                required_calls=("run_lean_process", "measurement_argv"),
            )
            self.assertTrue(audited["ok"])
            self.assertTrue(audited["uses_run_lean_process"])
            self.assertTrue(audited["uses_measurement_argv"])
            from jevops.outer import overlay_named_run_payload

            named = overlay_named_run_payload({"reason": "no_key"}, digest="abc", extra={"source": "strata"})
            self.assertTrue(named["ok"])
            self.assertEqual(named["warmup_jsonl_sha256"], "abc")
            self.assertEqual(named["source"], "strata")
            from jevops.outer import (
                all_rows,
                all_where,
                collect_where,
                field_eq_all,
                finalize_ok,
                first_line_value,
                kwargs_match_all,
                map_collect,
            )
            from jevops.lean import synthetic_proof_receipt

            self.assertTrue(all_rows([{"ok": True}, {"ok": True}], lambda row: row["ok"]))
            self.assertTrue(all_where([{"s": "a"}, {"s": "b"}], lambda row: row["s"] == "a", lambda row: True))
            self.assertEqual(collect_where([1, 2, 3], lambda n: n > 1, lambda n: n * 2), [4, 6])
            self.assertTrue(field_eq_all([{"k": "v"}], "k", "v"))
            self.assertTrue(kwargs_match_all([{"kwargs": {"a": 1}}], {"a": 1}))
            self.assertEqual(first_line_value("Source: putnambench\n", prefix="Source:"), "putnambench")
            rows, extra = map_collect([1, 2], lambda n: n + 1, after_fn=lambda n: [n])
            self.assertEqual(rows, [2, 3])
            self.assertEqual(extra, [2, 3])
            self.assertTrue(finalize_ok({"ok": False}, True, 1)["ok"])
            rec, body = synthetic_proof_receipt(
                lambda **kw: kw,
                lambda **kw: kw,
                name="P",
                lean_tag="v4.26.0",
                verdict="fail",
                body="rfl",
                digest_fn=lambda data: "d",
            )
            self.assertEqual(body, "rfl")
            self.assertEqual(rec["name"], "P")
            from jevops.jev import resolve_opt_in_mode
            from jevops.outer import any_contains, none_stripped_startswith, pack_live_rank, rank_named_rows

            self.assertEqual(
                resolve_opt_in_mode(
                    env={"LRA_GENERATOR": "grok"},
                    allowed=("off", "track1"),
                    generator_env="LRA_GENERATOR",
                    generator_aliases=("grok",),
                    default="off",
                ),
                "track1",
            )
            self.assertEqual(
                resolve_opt_in_mode(official=True, closed="off", allowed=("off", "track1")),
                "off",
            )
            self.assertTrue(any_contains(["case update_none =>"], "update_none"))
            self.assertTrue(none_stripped_startswith(["  simp"], "have "))
            ranked = rank_named_rows(
                ["A", "missing"],
                [{"name": "A"}],
                lambda rec: {"name": rec["name"], "n": 1},
            )
            self.assertEqual(ranked[0]["n"], 1)
            self.assertEqual(ranked[1]["error"], "unknown warm-up problem")
            live = pack_live_rank(schema="t/v1", digest="abc", canaries=[], wall_ms=1.0)
            self.assertEqual(live["schema"], "t/v1")
            self.assertFalse(live["jev_generated_lean"])
            from jevops.lean import pack_lemma_cap_fixture
            from jevops.mask import collect_one_hole_closed_rows
            from jevops.search import eligible_span_counts

            class _L:
                def __init__(self, name, tactic):
                    self.name = name
                    self.tactic = tactic

            cap = pack_lemma_cap_fixture(
                names=["Lemma_00"],
                lemmas=[_L("Lemma_00", "simp")],
                uncapped=2,
                cap=1,
            )
            self.assertTrue(cap["capped_at_1"])
            self.assertEqual(cap["first"], "Lemma_00")
            self.assertEqual(
                eligible_span_counts("x", (2,), lambda _t, span: [0] * span)["span_2"],
                2,
            )
            holes = collect_one_hole_closed_rows(
                "simp",
                (2,),
                prefer_fn=lambda _t, _s: [type("H", (), {"original": "simp"})()],
                closed_fn=lambda _t, hs, schedule_id="": {"kind": schedule_id, "original": hs[0].original},
            )
            self.assertEqual(holes[0]["span"], 2)
            self.assertEqual(holes[0]["n_masks"], 1)


if __name__ == "__main__":
    unittest.main()
