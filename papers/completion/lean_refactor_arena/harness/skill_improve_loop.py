#!/usr/bin/env python3
"""Autonomous skill-improve loop.

OUTER: Grok via llm_router.generate_text (closed JSON action).
INNER: TypeSafe keep-loop + recursive skill trees, callable subloops,
static-analysis tools (kg/ast/exports/mcp/diffuse). TypeSafe self-improves
from memory without llm_router; it may optionally invoke the router.

Grok does not write Lean. Jev does not write Lean. Never docker0.
Not Track 2. Not an Arena score.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from pathlib import Path
from typing import Any, Callable, Mapping, Optional

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
PROTOCOL = "LRA/v1"
PR_ID = "PR-9h"
ACTIONS = ("run", "nest_inner", "mint", "skip_stem", "install_fold", "stop")
KEEP_WORDS = ("intro", "intros", "constructor", "grind", "induction", "exact", "use")
_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
ROUTER_MAX_NEW = 256
ROUTER_TIMEOUT = 90.0

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import binder_use as lra_bind  # noqa: E402
import random_canary as lra_rand  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402
import typesafe_inner as lra_inner  # noqa: E402
from jevops.outer import deterministic_route  # noqa: E402
from jevops.outer import nca_status as nca_status_for_router  # noqa: E402
from jevops.outer import parse_action as _parse_action  # noqa: E402
from jevops.outer import route_next as _route_next  # noqa: E402

SMALL_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
    "Core.InitsUpdatesComm",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress",
    "Cslib.SKI.parallelReduction_diamond",
    "Cslib.CCS.bisimilarity_congr_choice",
)


def keep_best_board(out: Path) -> dict[str, int]:
    """Shortest random-best / cascade-best token count per small canary."""

    from jevops.outer import merge_keep_best

    return merge_keep_best(
        out,
        SMALL_NAMES,
        latest_json="random-canary-latest.json",
        extras={"Core.InitsUpdatesComm": ("cascade-best-139.lean", 139)},
    )


def board_total(board: Mapping[str, int]) -> int:
    from jevops.outer import board_total as _fn

    return _fn(board)


def parse_action(text: str) -> dict[str, Any]:
    """First JSON object in grok text; fail closed to action=run."""

    return _parse_action(text, actions=ACTIONS)


def router_prompt(
    board: Mapping[str, int],
    gaps: list[dict[str, Any]],
    last_lake: list[dict[str, Any]],
    *,
    nca_status: Optional[Mapping[str, Any]] = None,
) -> str:
    from jevops.outer import format_prompt

    return format_prompt(
        preamble=(
            "You are the OUTER Grok loop. Do not write Lean. TypeSafe is the INNER loop.\n"
            "Reply with one JSON object only, keys: action, stem, name, old, new, keep, reason.\n"
        ),
        actions=ACTIONS,
        extra=(
            "nest_inner: enter the TypeSafe inner loop, which keep-loops and recursively nests skill decision-tree children.\n"
            "run: same as nest_inner (TypeSafe still nests).\n"
            "install_fold: literal old→new substring fold that keeps intro/constructor/grind/exact/use.\n"
            "skip_stem: ban a port_ skill that lake-failed.\n"
            "mint: enable a keep-structure stem already in the harness.\n"
            "stop: no remaining lake-valid cut. If nca.halt or nca.budget_dead is true, action must be stop.\n"
        ),
        board=board,
        gaps=gaps,
        last_lake=last_lake,
        nca_status=nca_status,
        total=board_total(board),
    )


def route_next_action(
    *,
    board: Mapping[str, int],
    gaps: list[dict[str, Any]],
    last_lake: list[dict[str, Any]],
    stalled: bool,
    llm: bool,
    ledger: Any,
    generate: Optional[Callable[..., str]] = None,
    memory: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """llm_router grok when --llm on; else deterministic AutoResearch route."""

    nca = nca_status_for_router(memory)
    prompt = ""
    generate_fn = None
    if nca.get("budget_dead") or nca.get("halt"):
        llm = False
    if llm:
        prompt = router_prompt(board, gaps, last_lake, nca_status=nca)

        def generate_fn(prompt: str) -> str:
            text, _identity, _line = lra_t1.generate_grok(
                prompt,
                ledger,
                max_new_tokens=ROUTER_MAX_NEW,
                timeout=ROUTER_TIMEOUT,
                generate=generate,
                fixture=generate is not None,
            )
            return text

    return _route_next(
        gaps=gaps,
        last_lake=last_lake,
        stalled=stalled,
        llm=llm,
        memory=memory,
        generate_fn=generate_fn,
        prompt=prompt,
        ledger=ledger,
    )


def apply_action(memory: dict[str, Any], action: Mapping[str, Any]) -> dict[str, Any]:
    """Mutate memory from a closed action. No Python exec."""

    from jevops.outer import apply_action as _apply

    return _apply(memory, action)


def canary_args(
    *,
    out: Path,
    rounds: int,
    lake_top: int,
    drafts: int,
    timeout: float,
    seed: int,
    nest_depth: int = 3,
) -> argparse.Namespace:
    from jevops.outer import namespace

    return namespace(
        live=True,
        all_small=True,
        from_best=True,
        rounds=int(rounds),
        lake_top=int(lake_top),
        drafts=int(drafts),
        timeout=float(timeout),
        init_139=True,
        seed=int(seed),
        k=lra_rand.DEFAULT_K,
        out=out,
        include_inits=False,
        quiet=True,
        nest_depth=int(nest_depth),
    )


def self_check() -> dict[str, Any]:
    parsed = parse_action('noise {"action": "install_fold", "stem": "comma", "old": "a,⟩", "new": "a⟩", "keep": ["exact"]} trailing')
    mem: dict[str, Any] = {"skills": [], "blacklist": []}
    installed = apply_action(mem, parsed)
    fold_ok = bool(mem.get("skills"))
    skip = apply_action(mem, {"action": "skip_stem", "stem": "hoist_repeated_simp", "name": "P"})
    det = deterministic_route(
        gaps=[{"name": "P", "keep_structure": ["trailing_tuple_comma"], "proposed": {"mint": ["trailing_tuple_comma"]}}],
        last_lake=[],
        stalled=False,
    )
    board = {"Core.InitsUpdatesComm": 139}
    budget_stop = deterministic_route(
        gaps=[],
        last_lake=[{"name": "P", "skipped": "nca_budget"}, {"name": "Q", "skipped": "nca_budget"}],
        stalled=False,
    )
    import board_graph as lra_board_chk

    seeded = lra_board_chk.seed_nca_from_board({"nca": {"grid": {}}})
    return {
        "ok": (
            parsed.get("action") == "install_fold"
            and installed.get("ok") is True
            and fold_ok
            and skip.get("ok") is True
            and det.get("action") == "mint"
            and budget_stop.get("action") == "stop"
            and budget_stop.get("reason") == "nca_budget"
            and board_total(board) == 139
            and seeded.get("campaign_write") is False
            and lra_t1.FAIL_CLOSED_KWARGS.get("provider") == "grok"
            and lra_t1.FAIL_CLOSED_KWARGS.get("allow_local_fallback") is False
        ),
        "called_docker0": False,
        "arena_score": None,
        "official_track2": False,
        "router": "ipfs_accelerate_py.llm_router.generate_text",
        "jev_writes_lean": False,
        "grok_writes_lean": False,
    }


def run_loop(
    *,
    outer: int,
    llm: bool,
    out: Path,
    rounds: int,
    lake_top: int,
    drafts: int,
    timeout: float,
    seed: int,
    generate: Optional[Callable[..., str]] = None,
    run_inner: Optional[Callable[[argparse.Namespace], dict[str, Any]]] = None,
    memory: Optional[dict[str, Any]] = None,
    persist_memory: bool = True,
) -> dict[str, Any]:
    """OUTER Grok (llm_router). INNER TypeSafe keep-loop + recursive skill-tree nests."""

    memory = memory if memory is not None else lra_bind.load_memory()
    import board_graph as lra_board_seed
    from jevops.outer import seed_runtime

    seed_runtime(
        memory,
        seed_fn=lra_board_seed.seed_nca_from_board,
        overlay_fn=lra_board_seed.overlay_live_board,
        keepbest_fn=lambda mem: lra_board_seed.seed_keepbest_theorems(
            mem, keep_best_board(out), warmup=lra_board_seed.warmup_token_map()
        ),
    )
    ledger = lra_t1.ProblemLedger(
        name="warmup#skill-improve-loop",
        max_jev_calls=max(8, 6 * int(rounds) * int(outer) * 3 + 2),
        max_grok_calls=max(1, int(outer) if llm else 0),
        max_mistral_calls=0,
    )
    inner = run_inner or lra_rand.run_live
    nest_depth = max(1, int(lra_rand.NEST_MAX_DEPTH))
    from jevops.outer import run_steps

    def _board_fn() -> tuple[dict[str, int], int]:
        board = keep_best_board(out)
        return board, board_total(board)

    def _route_fn(*, board, gaps, last_lake, stalled):
        return route_next_action(
            board=board,
            gaps=gaps,
            last_lake=last_lake,
            stalled=stalled,
            llm=True if llm else False,
            ledger=ledger,
            generate=generate,
            memory=memory,
        )

    def _inner_fn(step: int) -> dict[str, Any]:
        return inner(
            canary_args(
                out=out,
                rounds=rounds,
                lake_top=lake_top,
                drafts=drafts,
                timeout=timeout,
                seed=seed + step,
                nest_depth=nest_depth,
            )
        )

    def _halt(mem: dict[str, Any]) -> dict[str, Any]:
        import typesafe_nca as lra_nca_halt

        return dict(lra_nca_halt.should_halt(mem) or {})

    stepped = run_steps(
        n=int(outer),
        memory=memory,
        llm=bool(llm),
        gaps_fn=lambda: lra_bind.skill_gap_report(memory),
        route_fn=_route_fn,
        apply_fn=apply_action,
        inner_fn=_inner_fn,
        board_fn=_board_fn,
        persist_fn=lra_bind.save_memory if persist_memory else None,
        halt_fn=_halt,
        flatten_fn=lra_inner.flatten_trace,
        hard_stop_fn=lambda: bool(getattr(ledger, "hard_stopped", False)),
        stalled_limit=2,
        on_inner_start=lambda mem: (mem.get("nca") or {}).pop("overlay_done", None),
    )
    from jevops.outer import skill_loop_payload

    mem_path = lra_bind.save_memory(memory) if persist_memory else lra_bind.MEMORY_DEFAULT
    return skill_loop_payload(
        outer=outer,
        llm=llm,
        history=stepped.get("history") or [],
        board=keep_best_board(out),
        total=board_total(keep_best_board(out)),
        best_total=stepped.get("best_total"),
        stop_reason=stepped.get("stop_reason") or "",
        memory_path=mem_path,
        memory_skills=memory.get("skills") or [],
        ledger=ledger,
        protocol=PROTOCOL,
        pr_id=PR_ID,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--llm", choices=("on", "off"), default="on")
    parser.add_argument("--outer", type=int, default=3, help="outer skill-improve rounds")
    parser.add_argument("--rounds", type=int, default=1, help="inner AutoResearch denoise rounds")
    parser.add_argument("--lake-top", type=int, default=3)
    parser.add_argument("--drafts", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--seed", type=int, default=lra_rand.DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(argv)
    if args.self_check or not args.live:
        from jevops.outer import print_ok

        return print_ok(self_check())
    payload = run_loop(
        outer=max(1, int(args.outer)),
        llm=args.llm == "on",
        out=args.out,
        rounds=max(1, int(args.rounds)),
        lake_top=int(args.lake_top),
        drafts=int(args.drafts),
        timeout=float(args.timeout),
        seed=int(args.seed),
    )
    from jevops.outer import write_json_pair

    write_json_pair(
        args.out,
        payload,
        prefix="skill-improve-loop",
        latest="skill-improve-loop-latest.json",
    )
    from jevops.outer import print_json

    print_json(payload, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
