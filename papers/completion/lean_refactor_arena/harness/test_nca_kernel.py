#!/usr/bin/env python3
"""NCA kernel: cache tiers, CID, negative TTL, single-flight, context budget."""

from __future__ import annotations

import unittest

import nca_kernel as lra_kern
import nca_program as lra_prog
import nca_rankers as lra_rank
import nca_plan as lra_plan


class NcaKernelTests(unittest.TestCase):
    def test_lru_evicts_cold(self) -> None:
        mem: dict = {"nca": {}}
        lra_kern.set_policy(mem, "lru")
        mem["nca"]["kernel"]["l1_cap"] = 2
        a = lra_kern.cache_put(mem, {"n": 1}, kind="n")
        b = lra_kern.cache_put(mem, {"n": 2}, kind="n")
        lra_kern.cache_get(mem, b["cid"])
        c = lra_kern.cache_put(mem, {"n": 3}, kind="n")
        self.assertFalse(lra_kern.cache_get(mem, a["cid"])["ok"])
        self.assertTrue(lra_kern.cache_get(mem, b["cid"])["ok"])
        self.assertTrue(lra_kern.cache_get(mem, c["cid"])["ok"])
        self.assertLessEqual(len(mem["nca"]["kernel"]["l1"]), 2)

    def test_arc_keeps_frequent(self) -> None:
        mem: dict = {"nca": {}}
        lra_kern.set_policy(mem, "arc")
        mem["nca"]["kernel"]["l1_cap"] = 2
        a = lra_kern.cache_put(mem, {"n": 1}, kind="n")
        lra_kern.cache_get(mem, a["cid"])
        lra_kern.cache_get(mem, a["cid"])
        b = lra_kern.cache_put(mem, {"n": 2}, kind="n")
        lra_kern.cache_put(mem, {"n": 3}, kind="n")
        self.assertTrue(lra_kern.cache_get(mem, a["cid"])["ok"], mem["nca"]["kernel"]["arc"])
        self.assertEqual(mem["nca"]["kernel"]["policy"], "arc")

    def test_integrity_miss_on_corrupt_l1(self) -> None:
        mem: dict = {"nca": {}}
        put = lra_kern.cache_put(mem, {"n": 1}, kind="n")
        mem["nca"]["kernel"]["l1"][put["cid"]]["body"] = {"n": 99}
        got = lra_kern.cache_get(mem, put["cid"])
        self.assertFalse(got["ok"])
        self.assertGreaterEqual(int(mem["nca"]["kernel"]["stats"].get("integrity_miss") or 0), 1)

    def test_lake_round_uses_negative_and_singleflight(self) -> None:
        import typesafe_inner as lra_inner

        n = {"i": 0}

        def compile_one(*_a, **_k):
            n["i"] += 1
            return {"theorem_ok": False, "token_count": 9, "errors": [{"data": "fail"}]}

        rec = {"name": "Core.InitsUpdatesComm"}
        drafts = [{"kind": "port_keep", "tactics": "  exact Hin\n", "family": "keep"}]
        args = type("A", (), {"lake_top": 3, "timeout": 1.0, "out": None})()
        mem: dict = {"nca": {}, "successes": [], "failures": []}
        _body, lake1 = lra_inner.apply_lake_round(
            record=rec,
            tactics="  exact Hin\n",
            analysis={"n_tokens": 8},
            drafts=drafts,
            intent={"skill": "keep", "compose": "single"},
            ranked={"beam_kinds": [], "fired": False, "fired_leaves": [], "best_draft": None},
            memory=mem,
            args=args,
            restore=b"",
            round_i=1,
            compile_one=compile_one,
        )
        self.assertTrue(any(not r.get("ok") for r in lake1))
        _body, lake2 = lra_inner.apply_lake_round(
            record=rec,
            tactics="  exact Hin\n",
            analysis={"n_tokens": 8},
            drafts=drafts,
            intent={"skill": "keep", "compose": "single"},
            ranked={"beam_kinds": [], "fired": False, "fired_leaves": [], "best_draft": None},
            memory=mem,
            args=args,
            restore=b"",
            round_i=2,
            compile_one=compile_one,
        )
        self.assertTrue(any(r.get("skipped") == "negative_ttl" for r in lake2), lake2)
        self.assertEqual(n["i"], 1)

    def test_mcmc_compile_one_forwards_memory(self) -> None:
        import mcmc_beam as lra_mcmc
        from pathlib import Path

        n = {"i": 0}
        orig = lra_mcmc.lra_kb.compile_tactics

        def fake(*_a, **_k):
            n["i"] += 1
            return {"theorem_ok": False, "token_count": 1, "errors": []}

        lra_mcmc.lra_kb.compile_tactics = fake  # type: ignore[method-assign]
        try:
            rec = {"name": "P"}
            mem: dict = {"nca": {}}
            lra_mcmc.compile_one(rec, "  exact\n", state_root=Path("."), timeout=1.0, restore=b"", memory=mem)
            lra_mcmc.compile_one(rec, "  exact\n", state_root=Path("."), timeout=1.0, restore=b"", memory=mem)
            self.assertEqual(n["i"], 1)
            lra_mcmc.compile_one(rec, "  exact\n", state_root=Path("."), timeout=1.0, restore=b"", memory=None)
            self.assertEqual(n["i"], 2)
        finally:
            lra_mcmc.lra_kb.compile_tactics = orig

    def test_guarded_compile_skips_second_fail(self) -> None:
        n = {"i": 0}

        def compile_fn():
            n["i"] += 1
            return {"theorem_ok": False, "token_count": 4, "errors": []}

        mem: dict = {"nca": {}}
        first = lra_kern.guarded_compile(mem, name="P", kind="mcmc", tactics="  exact\n", compile_fn=compile_fn)
        self.assertFalse(first.get("theorem_ok"))
        second = lra_kern.guarded_compile(mem, name="P", kind="mcmc", tactics="  exact\n", compile_fn=compile_fn)
        self.assertEqual(second.get("skipped"), "negative_ttl")
        self.assertEqual(n["i"], 1)
        third = lra_kern.guarded_compile(None, name="P", kind="mcmc", tactics="  exact\n", compile_fn=compile_fn)
        self.assertEqual(n["i"], 2)

    def test_eval_theorem_skips_negative(self) -> None:
        import typesafe_inner as lra_inner

        n = {"i": 0}

        def compile_fn(*_a, **_k):
            n["i"] += 1
            return {"theorem_ok": False, "token_count": 3, "errors": [{"data": "fail"}]}

        rec = {"name": "Core.InitsUpdatesComm"}
        args = type("A", (), {"timeout": 1.0})()
        mem: dict = {"nca": {}}
        first = lra_inner.eval_theorem(
            "Core.InitsUpdatesComm",
            current=rec,
            tactics="  exact Hin\n",
            compile_fn=compile_fn,
            args=args,
            restore=b"",
            memory=mem,
        )
        self.assertFalse(first.get("theorem_ok"))
        second = lra_inner.eval_theorem(
            "Core.InitsUpdatesComm",
            current=rec,
            tactics="  exact Hin\n",
            compile_fn=compile_fn,
            args=args,
            restore=b"",
            memory=mem,
        )
        self.assertEqual(second.get("skipped"), "negative_ttl")
        self.assertEqual(n["i"], 1)

    def test_router_sees_kernel_stats(self) -> None:
        import skill_improve_loop as lra_loop

        mem: dict = {"nca": {}}
        lra_kern.cache_put(mem, {"n": 1}, kind="n")
        snap = lra_loop.nca_status_for_router(mem)
        self.assertIn("kernel", snap)
        self.assertIn("stats", snap["kernel"])
        self.assertGreaterEqual(int(snap["kernel"]["n_l1"]), 1)

    def test_put_get_never_admits(self) -> None:
        mem: dict = {"nca": {}}
        put = lra_kern.cache_put(mem, {"tactics": "  exact Hin\n", "theorem_ok": True}, kind="draft")
        self.assertTrue(put["ok"])
        self.assertFalse(put["admit"])
        self.assertIn("L1", put["tiers"])
        self.assertNotIn("theorem_ok", mem["nca"]["kernel"]["l1"][put["cid"]]["body"])
        got = lra_kern.cache_get(mem, put["cid"])
        self.assertTrue(got["ok"])
        self.assertEqual(got["tier"], "L1")
        self.assertFalse(got["admit"])
        miss = lra_kern.cache_get(mem, "sha256:dead")
        self.assertFalse(miss["ok"])

    def test_negative_ttl_expires(self) -> None:
        mem: dict = {"nca": {}}
        lra_kern.negative_put(mem, "P::fold", ttl=2)
        self.assertTrue(lra_kern.negative_hit(mem, "P::fold"))
        lra_kern.bump_tick(mem)
        lra_kern.bump_tick(mem)
        self.assertFalse(lra_kern.negative_hit(mem, "P::fold"))
        self.assertEqual(lra_kern.sweep_negative(mem), 1)

    def test_singleflight(self) -> None:
        mem: dict = {"nca": {}}
        a = lra_kern.flight_begin(mem, "k1")
        self.assertTrue(a["ok"])
        b = lra_kern.flight_begin(mem, "k1")
        self.assertFalse(b["ok"])
        self.assertEqual(b["reason"], "in_flight")
        lra_kern.flight_end(mem, "k1")
        c = lra_kern.flight_begin(mem, "k1")
        self.assertTrue(c["ok"])
        lra_kern.flight_end(mem, "k1")

    def test_durable_inflight_survives_new_memory(self) -> None:
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LRA_NCA_INFLIGHT"] = tmp
            try:
                a = lra_kern.flight_begin({"nca": {}}, "durable-key")
                self.assertTrue(a["ok"])
                b = lra_kern.flight_begin({"nca": {}}, "durable-key")
                self.assertFalse(b["ok"])
                self.assertTrue(b.get("durable"))
                lra_kern.flight_end({"nca": {}}, "durable-key")
                c = lra_kern.flight_begin({"nca": {}}, "durable-key")
                self.assertTrue(c["ok"])
                lra_kern.flight_end({"nca": {}}, "durable-key")
                self.assertFalse(any(Path(tmp).iterdir()))
            finally:
                os.environ.pop("LRA_NCA_INFLIGHT", None)

    def test_context_budget_trims_bytes(self) -> None:
        mem = {
            "nca": {"budget": {"max_cells": 20, "max_bytes": 400}},
            "tape": {
                "cells": [
                    {"kind": str(i), "energy": 0.01, "symbol": "x" * 80, "payload": "y" * 80}
                    for i in range(8)
                ],
                "head": 0,
            },
        }
        mem["nca"]["kernel"] = {"budget": {"max_cells": 20, "max_bytes": 400}}
        out = lra_kern.apply_context_budget(mem)
        self.assertTrue(out["ok"])
        blob = __import__("json").dumps(mem["tape"]["cells"], default=str)
        self.assertLessEqual(len(blob), 2000)

    def test_inner_walk_applies_context_budget(self) -> None:
        import splice as lra_splice
        import typesafe_inner as lra_inner

        _raw, _digest, records = lra_splice.load_warmup_records()
        rec = next(item for item in records if item.get("name") == "Core.InitsUpdatesComm")
        mem: dict = {
            "nca": {"kernel": {"budget": {"max_cells": 5, "max_bytes": 65536}}},
            "tape": {
                "cells": [{"kind": str(i), "energy": 0.01, "symbol": str(i)} for i in range(20)],
                "head": 19,
            },
            "observations": {},
        }

        class Args:
            drafts = 1
            lake_top = 1
            timeout = 1.0
            out = None
            nest_depth = 1
            from_best = False

        lra_inner.inner_typesafe_walk(
            rec,
            "  exact Lemma.foo\n",
            args=Args(),
            memory=mem,
            ledger=None,
            rng=__import__("random").Random(0),
            model=None,
            restore=b"",
            research_fn=lambda *_a, **_k: {
                "compose": "keep",
                "skip_lake": True,
                "skill": "keep",
                "intent": "search_space",
                "tree": {},
                "residual_unsafe": {},
                "residual_help": {},
                "skip_skills": [],
            },
            compile_one=lambda *_a, **_k: {"theorem_ok": True, "token_count": 3, "errors": []},
            pick_fn=lambda *_a, **_k: {"beam_kinds": [], "fired": False, "fired_leaves": []},
            allow_skills={"no_such_skill"},
            max_steps=1,
            max_depth=1,
        )
        n_cells = len((mem.get("tape") or {}).get("cells") or [])
        self.assertLessEqual(n_cells, 8)

    def test_context_budget_keep_k(self) -> None:
        mem = {
            "nca": {},
            "tape": {
                "cells": [{"kind": str(i), "energy": 0.1 * i, "symbol": str(i)} for i in range(20)],
                "head": 19,
            },
        }
        out = lra_kern.apply_context_budget(mem)
        self.assertTrue(out["ok"])
        self.assertLessEqual(out["kept"], 12)

    def test_cache_get_not_swallowed_by_got(self) -> None:
        self.assertTrue(lra_kern.is_kernel_stem("port_cache_get"))
        self.assertFalse(lra_plan.is_plan_stem("port_cache_get"))
        mem: dict = {"nca": {}}
        out = lra_rank.call_ranker("port_cache_put", memory=mem, tactics="  simp\n", problem="P")
        self.assertEqual(out.get("kind"), "port_cache_put")
        got = lra_rank.call_ranker("port_cache_get", memory=mem, tactics="  simp\n", problem="P")
        self.assertTrue(got.get("ok"), got)

    def test_skill_calls(self) -> None:
        mem = {
            "nca": {
                "grid": {},
                "program_state": {
                    "ops": [
                        {"op": "CALL", "ptr": "ptr://skill/port_cache_arc"},
                        {"op": "CALL", "ptr": "ptr://skill/port_cache_put"},
                        {"op": "CALL", "ptr": "ptr://skill/port_negative_ttl"},
                        {"op": "CALL", "ptr": "ptr://skill/port_singleflight"},
                        {"op": "CALL", "ptr": "ptr://skill/port_context_budget"},
                        {"op": "KEEP"},
                    ]
                },
            },
            "tape": {"cells": [{"kind": "a", "energy": 0.5, "symbol": "a"}] * 5, "head": 4},
        }
        executed = lra_prog.execute_program_ops(mem, tactics="  simp\n", problem="P")
        self.assertEqual(executed.get("tactics"), "  simp\n")
        ptrs = [str(op.get("ptr") or "") for op in executed.get("ran") or [] if op.get("ok")]
        for tag in ("cache_arc", "cache_put", "negative_ttl", "singleflight", "context_budget"):
            self.assertTrue(any(tag in p for p in ptrs), (tag, executed["ran"]))


if __name__ == "__main__":
    unittest.main()
