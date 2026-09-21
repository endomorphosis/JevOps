#!/usr/bin/env python3
"""Recursive TypeSafe inner loop over the skill decision tree.

Outer Grok (llm_router) decides whether to enter. This module is the inner
TypeSafe walker: keep looping at a tree node, and nest a child loop when
compose=nest. Lake is the oracle. Jev does not write Lean. Never docker0.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import _jevops_path  # noqa: F401
import binder_use as lra_bind
import draft_fanout as lra_fan
import mca_mask_replace as lra_mask
import portable_rewrites as lra_port
import random_canary as lra_rand
import track1_keepbest as lra_kb
import typesafe_tools as lra_tools
from jevops.walk import begin_session
from jevops.walk import flatten_trace
from jevops.walk import inner_loop

HERE = Path(__file__).resolve().parent


def apply_lake_round(
    *,
    record: Mapping[str, Any],
    tactics: str,
    analysis: Mapping[str, Any],
    drafts: list[dict[str, Any]],
    intent: Mapping[str, Any],
    ranked: Mapping[str, Any],
    memory: dict[str, Any],
    args: Any,
    restore: bytes,
    round_i: int,
    compile_one: Callable[..., Mapping[str, Any]],
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Lake up to lake_top drafts. Returns (accepted_body, lake_rows)."""

    from jevops.nca import credit_skill
    from jevops.oracle import apply_round
    from jevops.oracle import lake_budget as _lake_budget
    from jevops.outer import arg_value

    too_big, lake_budget = _lake_budget(
        analysis.get("n_tokens"),
        cap=lra_rand.MAX_LIVE_TOKENS,
        top=arg_value(args, "lake_top", 3, cast=int),
    )
    timeout = arg_value(args, "timeout", 180.0, cast=float)
    out_dir = getattr(args, "out", None)
    tactics_ref = tactics

    def _compile_kind(_kind: str, script: str) -> Mapping[str, Any]:
        return compile_one(
            record,
            script,
            state_root=lra_rand.DEFAULT_STATE,
            timeout=timeout,
            restore=restore,
        )

    def _repair(*, kind: str, tactics: str, compiled: Mapping[str, Any], row: Mapping[str, Any]) -> Optional[str]:
        del kind
        if row.get("error_class") != "unknown_identifier":
            return None
        repaired_body = lra_bind.restore_unknown_binders(tactics, tactics_ref, compiled.get("errors") or [])
        repaired_body = lra_mask.hammer_repair(repaired_body, tactics_ref, compiled.get("errors") or [])
        return repaired_body

    def _on_ok(row: Mapping[str, Any], body: str, draft: Mapping[str, Any], *, better: bool) -> None:
        # Carry teacher provenance into the Lake receipt.  The current
        # compiler result, not the historical filename, is the admission
        # authority; this metadata only makes the path auditable.
        for key in (
            "seed_provenance",
            "seed_commit",
            "seed_path",
            "claimed_tokens",
            "actual_tokens",
            "body_digest",
        ):
            if draft.get(key) is not None:
                row[key] = draft.get(key)
        if draft.get("body_digest"):
            try:
                from historical_seeds import record_seed_outcome

                record_seed_outcome(
                    memory,
                    str(record.get("name") or ""),
                    str(draft.get("body_digest") or ""),
                    lake_ok=True,
                    tokens=int(row.get("tokens") or 0),
                )
            except Exception:
                pass
        lra_bind.remember_success(
            memory,
            name=str(record.get("name") or ""),
            kind=str(row["kind"]),
            family=str(draft.get("family") or ""),
            from_tokens=int(analysis.get("n_tokens") or 0),
            to_tokens=int(row["tokens"] or analysis.get("n_tokens") or 0),
        )
        credit_skill(memory, row["kind"], ok=True, tokens=int(row["tokens"] or 0))
        if not better:
            return
        try:
            import codepath_graph as lra_cp

            if (memory.get("nca") or {}).get("sidecar_built") and lra_cp.SIDECAR_DUCKDB.is_file():
                lra_cp.build_sidecar_duckdb()
        except Exception:
            pass
        try:
            import board_graph as lra_board

            lra_board.credit_theorem(
                memory,
                str(record.get("name") or ""),
                theorem_ok=True,
                tokens=int(row["tokens"] or 0),
            )
        except Exception:
            pass
        if out_dir is not None:
            from jevops.outer import write_best_body

            best_path = write_best_body(out_dir, str(record.get("name") or ""), int(row["tokens"] or 0), body)
            row["best_path"] = str(best_path)

    def _on_fail(
        row: Mapping[str, Any],
        body: str,
        draft: Mapping[str, Any],
        *,
        compiled: Mapping[str, Any],
        kind: str,
    ) -> None:
        if draft.get("body_digest"):
            try:
                from historical_seeds import record_seed_outcome

                record_seed_outcome(
                    memory,
                    str(record.get("name") or ""),
                    str(draft.get("body_digest") or ""),
                    lake_ok=False,
                    tokens=int(row.get("tokens") or 0),
                )
            except Exception:
                pass
        lra_bind.remember_failure(
            memory,
            name=str(record.get("name") or ""),
            kind=str(kind),
            errors=row.get("errors") or compiled.get("errors") or [],
            tactics=body,
        )
        credit_skill(memory, kind, ok=False)

    return apply_round(
        memory=memory,
        name=record.get("name"),
        drafts=drafts,
        intent=intent,
        ranked=ranked,
        round_i=round_i,
        budget=lake_budget,
        compile_fn=_compile_kind,
        repair_fn=_repair,
        error_class_fn=lra_bind.error_class,
        on_ok=_on_ok,
        on_fail=_on_fail,
        from_tokens=int(analysis.get("n_tokens") or 10**9),
        too_big=too_big,
    )


def eval_theorem(
    name: str,
    *,
    current: Mapping[str, Any],
    tactics: str,
    compile_fn: Callable[..., Mapping[str, Any]],
    args: Any,
    restore: bytes,
    memory: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Lake a small warmup theorem. Other names fail closed if not small."""

    import draft_fanout as lra_fan
    import splice as lra_splice
    import track1_keepbest as lra_kb

    from jevops.oracle import eval_named_or_current
    from jevops.outer import arg_value, read_bytes_if

    def _records() -> list:
        _raw, _digest, records = lra_splice.load_warmup_records()
        return records

    return eval_named_or_current(
        name,
        current=current,
        tactics=tactics,
        compile_fn=compile_fn,
        memory=memory,
        timeout=arg_value(args, "timeout", 180.0, cast=float),
        load_records_fn=_records,
        tactic_block_fn=lra_fan.tactic_block,
        clone_dir_fn=lambda url: lra_kb.lra_cw.clone_dir(url, lra_rand.DEFAULT_STATE),
        relpath_fn=lra_kb.lra_cw.source_relpath,
        read_bytes_fn=read_bytes_if,
        cap=lra_rand.MAX_LIVE_TOKENS,
        state_root=lra_rand.DEFAULT_STATE,
        restore=restore,
    )


def inner_typesafe_walk(
    record: Mapping[str, Any],
    tactics: str,
    *,
    args: Any,
    memory: dict[str, Any],
    ledger: Any,
    rng: Any,
    model: Optional[Mapping[str, Any]],
    restore: bytes,
    depth: int = 0,
    node: str = "root",
    allow_families: Optional[set[str]] = None,
    allow_skills: Optional[set[str]] = None,
    steps: Optional[list[int]] = None,
    max_steps: int = lra_rand.INNER_MAX_STEPS,
    max_depth: int = lra_rand.NEST_MAX_DEPTH,
    compile_one: Optional[Callable[..., Mapping[str, Any]]] = None,
    research_fn: Optional[Callable[..., dict[str, Any]]] = None,
    pick_fn: Optional[Callable[..., dict[str, Any]]] = None,
    router_fn: Optional[Callable[..., dict[str, Any]]] = None,
    tape: Optional[Any] = None,
    stack: Optional[Any] = None,
) -> dict[str, Any]:
    """Keep-looping TypeSafe walker. nest/spawn recurse; analyze/self_improve skip grok."""

    import mcmc_beam as lra_mcmc
    import call_stack as lra_cs
    import neural_tape as lra_tape

    raw_compile = compile_one or lra_mcmc.compile_one

    def compile_fn(record: Mapping[str, Any], tactics: str, **kwargs: Any) -> Mapping[str, Any]:
        if compile_one is None:
            kwargs.setdefault("memory", memory)
        return raw_compile(record, tactics, **kwargs)
    research = research_fn or lra_rand.typesafe_autoresearch
    pick = pick_fn or lra_rand.typesafe_pick
    counter = steps if steps is not None else [0]
    body = str(tactics or "").strip("\n")
    tape = tape if tape is not None else lra_tape.Tape.from_memory(memory)
    stack = stack if stack is not None else lra_cs.CallStack()

    def _link(mem: dict[str, Any], problem: str) -> None:
        import board_graph as lra_board

        lra_board.link_current_theorem(mem, problem)

    def _overlay(mem: dict[str, Any]) -> None:
        import board_graph as lra_board

        lra_board.overlay_live_board(mem)

    tape = begin_session(
        memory=memory,
        tape=tape,
        stack=stack,
        problem=str(record.get("name") or ""),
        body=body,
        depth=depth,
        link_fn=_link,
        overlay_fn=_overlay,
    )

    def _analyze(nxt: str) -> dict[str, Any]:
        return lra_rand.analyze_proof(record, tactics=nxt, model=model)

    def _research(analysis: Mapping[str, Any], nxt: str) -> dict[str, Any]:
        return research(
            record,
            analysis,
            tactics=nxt,
            ledger=ledger,
            memory=memory,
            allow_families=allow_families,
            allow_skills=allow_skills,
            tree_node=node,
        )

    def _remember(intent: Mapping[str, Any], nxt: str) -> None:
        from jevops.memory import remember_intent

        remember_intent(
            memory,
            name=str(record.get("name") or ""),
            tactics=nxt,
            intent=intent,
            residual_fn=lra_port.analyze_residuals,
        )

    def _expand(nxt: str) -> None:
        lra_bind.expand_skills_from_memory(memory, name=str(record.get("name") or ""), tactics=nxt)

    def _drafts(nxt: str, analysis: Mapping[str, Any], intent: Mapping[str, Any]) -> list[dict[str, Any]]:
        allow = set(allow_families or intent.get("allow_families") or [])
        return lra_rand.random_drafts(
            nxt,
            rng,
            n=max(2, int(getattr(args, "drafts", 6) or 6)),
            families=analysis.get("families") or [],
            counts=analysis.get("counts"),
            name=str(record.get("name") or ""),
            memory=memory,
            allow_families=allow,
        )

    def _extra(compose: str, nest_child: str, tool_name: str, nxt: str) -> dict[str, Any]:
        from jevops.walk import extra_payload

        return extra_payload(
            compose,
            nest_child=nest_child,
            tool_name=tool_name,
            default_hook="portable_rewrites.py",
            fork={
                "record": record,
                "tactics": nxt,
                "args": args,
                "memory": memory,
                "ledger": ledger,
                "rng": rng,
                "model": model,
                "restore": restore,
                "depth": depth + 1,
                "steps": counter,
                "max_steps": max_steps,
                "max_depth": max_depth,
                "compile_one": compile_fn,
                "research_fn": research,
                "pick_fn": pick,
                "router_fn": router_fn,
                "problem": str(record.get("name") or ""),
            },
        )

    walk_args = args
    walk_allow_families = allow_families
    walk_allow_skills = allow_skills

    def _theorem(name: str, *, tactics: str, resolved: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        del resolved, args
        evaled = eval_theorem(
            name,
            current=record,
            tactics=tactics,
            compile_fn=compile_fn,
            args=walk_args,
            restore=restore,
            memory=memory,
        )
        try:
            import board_graph as lra_board

            lra_board.credit_theorem(
                memory,
                str(evaled.get("name") or record.get("name") or ""),
                theorem_ok=bool(evaled.get("theorem_ok")),
                tokens=int(evaled.get("tokens") or 0),
            )
        except Exception:
            pass
        return evaled

    def _ptr_nest(
        *,
        tactics: str,
        node: str,
        allow_families: Optional[set[str]] = None,
        allow_skills: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        return inner_typesafe_walk(
            record,
            tactics,
            args=args,
            memory=memory,
            ledger=ledger,
            rng=rng,
            model=model,
            restore=restore,
            depth=depth + 1,
            node=node,
            allow_families=allow_families or walk_allow_families,
            allow_skills=allow_skills or walk_allow_skills,
            steps=counter,
            max_steps=max_steps,
            max_depth=max_depth,
            compile_one=compile_fn,
            research_fn=research,
            pick_fn=pick,
            router_fn=router_fn,
            tape=tape,
            stack=stack,
        )

    def _spawn(child: str, tactics: str = "") -> dict[str, Any]:
        return lra_tools.spawn_subloop(
            child,
            record=record,
            tactics=tactics or body,
            args=args,
            memory=memory,
            ledger=ledger,
            rng=rng,
            model=model,
            restore=restore,
            depth=depth + 1,
            node=child,
            steps=counter,
            max_steps=max_steps,
            max_depth=max_depth,
            compile_one=compile_fn,
            research_fn=research,
            pick_fn=pick,
            router_fn=router_fn,
        )

    def _nest(
        *,
        child: str,
        allow_families: Optional[set[str]] = None,
        allow_skills: Optional[set[str]] = None,
        tactics: str = "",
    ) -> dict[str, Any]:
        return inner_typesafe_walk(
            record,
            tactics or body,
            args=args,
            memory=memory,
            ledger=ledger,
            rng=rng,
            model=model,
            restore=restore,
            depth=depth + 1,
            node=child,
            allow_families=allow_families,
            allow_skills=allow_skills,
            steps=counter,
            max_steps=max_steps,
            max_depth=max_depth,
            compile_one=compile_fn,
            research_fn=research,
            pick_fn=pick,
            router_fn=router_fn,
            tape=tape,
            stack=stack,
        )

    return inner_loop(
        memory=memory,
        tape=tape,
        stack=stack,
        record=record,
        body=body,
        depth=depth,
        node=node,
        max_steps=max_steps,
        max_depth=max_depth,
        counter=counter,
        analyze_fn=_analyze,
        research_fn=_research,
        remember_fn=_remember,
        expand_fn=_expand,
        draft_fn=_drafts,
        pick_fn=pick,
        lake_round=apply_lake_round,
        compile_fn=compile_fn,
        ledger=ledger,
        args=args,
        restore=restore,
        spawn_fn=_spawn,
        nest_fn=_nest,
        ptr_nest_fn=_ptr_nest,
        theorem_fn=_theorem,
        subloops=lra_tools.SUBLOOPS,
        extra_fn=_extra,
        router_fn=router_fn,
        allow_families=allow_families,
        allow_skills=allow_skills,
    )


def starting_tactics(record: Mapping[str, Any], *, out: Any = None, from_best: bool = False) -> str:
    """Keep-best body when --from-best, else frozen warmup tactics."""

    from jevops.outer import starting_body

    tactics = lra_fan.tactic_block(record)
    if not from_best:
        return tactics
    selected = starting_body(
        tactics,
        out,
        str(record.get("name") or "canary"),
        extras={"Core.InitsUpdatesComm": "cascade-best-130.lean"},
    )
    if selected == tactics:
        # Before runtime artifacts were isolated, keep-best bodies were often
        # left as untracked files under the curated evidence directory.  A
        # fresh runtime root must be able to migrate those actual proof bodies
        # read-only; the count-only JSON fixture is intentionally not used as
        # a substitute.  Every migrated body still goes through the Lake gate
        # before it can become a new runtime keep-best.
        legacy_root = HERE.parent / "evidence" / "canaries"
        selected = starting_body(
            tactics,
            legacy_root,
            str(record.get("name") or "canary"),
        )
    if selected != tactics or str(record.get("name") or "") != "Core.InitsUpdatesComm":
        return selected
    # A disposable outer-loop --out directory does not contain the curated
    # historical canary. Fall back to that fixture so the live loop actually
    # challenges 139 and can measure the 130 candidate.
    source = HERE.parent / "evidence" / "canaries" / "cascade-best-139.lean"
    if source.is_file():
        return source.read_text(encoding="utf-8").strip("\n")
    return selected


def run_nested_canary(
    record: Mapping[str, Any],
    *,
    args: Any,
    memory: dict[str, Any],
    ledger: Any,
    rng: Any,
    model: Optional[Mapping[str, Any]],
    compile_one: Optional[Callable[..., Mapping[str, Any]]] = None,
    research_fn: Optional[Callable[..., dict[str, Any]]] = None,
    pick_fn: Optional[Callable[..., dict[str, Any]]] = None,
    router_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Load keep-best tactics, walk the TypeSafe tree, restore the clone."""

    tactics = starting_tactics(
        record, out=getattr(args, "out", None), from_best=bool(getattr(args, "from_best", False))
    )
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), lra_rand.DEFAULT_STATE)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import inner_budget, read_bytes_if, restore_if
    from jevops.walk import pack_canary, run_nested

    restore = read_bytes_if(dest)
    return run_nested(
        tactics=tactics,
        dest=dest,
        restore=restore,
        name=record.get("name"),
        analyze_fn=lambda body: lra_rand.analyze_proof(record, tactics=body, model=model),
        pack_fn=pack_canary,
        budget_fn=lambda: inner_budget(
            args, min_steps=lra_rand.INNER_MAX_STEPS, default_depth=lra_rand.NEST_MAX_DEPTH
        ),
        walk_fn=lambda body, restore, max_steps, max_depth: inner_typesafe_walk(
            record,
            body,
            args=args,
            memory=memory,
            ledger=ledger,
            rng=rng,
            model=model,
            restore=restore,
            max_steps=max_steps,
            max_depth=max_depth,
            compile_one=compile_one,
            research_fn=research_fn,
            pick_fn=pick_fn,
            router_fn=router_fn,
        ),
        restore_fn=restore_if,
    )


def _skill_walk_entry(**kwargs: Any) -> dict[str, Any]:
    record = kwargs.pop("record")
    tactics = str(kwargs.pop("tactics", "") or "")
    return inner_typesafe_walk(record, tactics, **kwargs)


lra_tools.register_subloop("skill_walk", _skill_walk_entry)


def _eval_theorem_entry(**kwargs: Any) -> dict[str, Any]:
    record = kwargs.get("record") or {}
    return eval_theorem(
        str(kwargs.get("name") or kwargs.get("theorem") or record.get("name") or ""),
        current=record if isinstance(record, dict) else {},
        tactics=str(kwargs.get("tactics") or ""),
        compile_fn=kwargs.get("compile_one") or kwargs.get("compile_fn"),
        args=kwargs.get("args"),
        restore=kwargs.get("restore") or b"",
        memory=kwargs.get("memory") if isinstance(kwargs.get("memory"), dict) else None,
    )


lra_tools.register_subloop("eval_theorem", _eval_theorem_entry)
