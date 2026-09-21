#!/usr/bin/env python3
"""TypeSafe Metropolis-Hastings over a constrained beam of Lean tactic scripts.

Each chain starts from the original (lake-valid) proof. A proposal is a
local edit from a closed set (drop a mutable line, swap in a closer, drop
a trailing simp_all). TypeSafe Choice ranks proposals; lake is the accept
oracle. Metropolis may accept a longer still-valid script with
``exp(-Δtokens / T)``. Invalid lake results are rejected.

This is MCMC on the beam, not neural sampling. Prefix ``have``s that
``simp_all`` consumes stay locked (Hk / Hlen1 / Hlen2 on InitsUpdatesComm).
Proposal kernels: closed deletions, ``refine``/``ih`` rewrites, optional
one-line local Leanstral replacements. Not official Track 2. Not an Arena ranking.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
HARDWARE_CLASS = "spark_gb10"
PROTOCOL = "LRA/v1"
PR_ID = "PR-9g"
LOCKED_HEADS = ("intros ", "exists ", "induction ", "case ")
CLOSERS = ("simp_all", "omega", "constructor", "rfl")
MAX_PROPOSALS = 8
MAX_JEV = 24
MAX_LEANSTRAL = 4
IH_APPLY = "apply (ih Hinit ?_ ?_).2.2"
IH_APPLY_SHORT = "apply (ih Hinit).2.2"
IH_EXACT = "exact (ih Hinit ?_ ?_).2.2"
REFINE_RFL = "refine ⟨rfl, ?_, ?_⟩"
HND_BLOCK = (
    "          have Hnd := InitStatesNotDefined Hinit\n"
    "          simp [isNotDefined, isDefined] at *\n"
    "          intros Hin\n"
    "          simp_all"
)
HND_REPLACEMENTS = (
    (
        "hnd_intro_simp",
        "          intros Hin\n"
        "          simp [InitStatesNotDefined Hinit, isNotDefined, isDefined] at *",
        "Hnd block -> intros Hin + combined simp",
    ),
    (
        "hnd_simp_only",
        "          simp [InitStatesNotDefined Hinit, isNotDefined, isDefined]",
        "Hnd block -> one simp of InitStatesNotDefined",
    ),
    (
        "hnd_intro_exact",
        "          intro Hin\n"
        "          simp [isNotDefined, isDefined, InitStatesNotDefined] at *",
        "Hnd block -> intro Hin + InitStatesNotDefined simp",
    ),
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import constrained_beam as lra_cb  # noqa: E402
import draft_fanout as lra_fan  # noqa: E402
import inits_updates_shorten as lra_ius  # noqa: E402
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"
TS_PATH = _jevops_path.TYPESAFE_INFERENCE_PATH


from jevops.tactics import Chain


def locked_have_names(reference: str) -> set[str]:
    from jevops.outer import mapped_nonempty

    return mapped_nonempty(
        lra_cb.prefix_have_lines(reference),
        lambda line: lra_cb.have_binder_name(line.strip()),
    )


def mutable_indices(tactics: str, locked_haves: set[str]) -> list[int]:
    from jevops.tactics import mutable_line_indices

    return mutable_line_indices(tactics, locked_haves, skip_prefix=LOCKED_HEADS)


def apply_drop(tactics: str, index: int) -> str:
    from jevops.mask import drop_index

    return drop_index(tactics, index)


def apply_replace(tactics: str, index: int, nxt: str) -> str:
    from jevops.mask import replace_index

    return replace_index(tactics, index, nxt)


def join_consecutive_applies(tactics: str) -> str:
    from jevops.tactics import join_consecutive_applies as _fn

    return _fn(tactics)


def drop_last_duplicate_lines(tactics: str, locked_haves: set[str]) -> list[tuple[int, str, str]]:
    """Drop the last extra copy of a stripped line that appears more than once."""

    from jevops.tactics import drop_last_duplicate_lines as _fn

    return _fn(tactics, locked_haves)


def collapse_ih_simps(tactics: str) -> Optional[str]:
    """Fold the two simp bullets after ``apply (ih …).2.2`` into ``<;> simp_all``."""

    from jevops.tactics import collapse_ih_simps as _fn

    return _fn(tactics, needle=IH_APPLY)


def propose_edits(
    tactics: str,
    reference: str,
    rng: random.Random,
    extra: Optional[Sequence[dict[str, str]]] = None,
    limit: Optional[int] = MAX_PROPOSALS,
) -> list[dict[str, str]]:
    from jevops.tactics import collect_mcmc_proposal_extras, propose_closed_edits

    extras = collect_mcmc_proposal_extras(
        tactics,
        extra or (),
        propose_fn=lra_ius.propose,
        replay_fn=lra_ius.replay,
        extras_fn=lra_ius.mcmc_extras,
        replay_note="apply the full Core.InitsUpdatesComm 268→139 kernel sequence",
    )
    return propose_closed_edits(
        tactics,
        reference,
        rng,
        extras,
        closers=CLOSERS,
        skip_prefix=LOCKED_HEADS,
        limit=limit,
    )


def load_typesafe():
    from jevops.outer import after_calls, load_configured

    return after_calls(
        (lra_pca.load_keyfile, lra_pca.pin_typesafe_path),
        load_configured,
        TS_PATH,
        "lra_typesafe_inference_mcmc",
    )


def typesafe_rank_proposals(
    record: Mapping[str, Any],
    current: str,
    proposals: Sequence[dict[str, str]],
    *,
    ledger: lra_t1.ProblemLedger,
) -> dict[str, Any]:
    from jevops.jev import choice_questions, invoke_system_one, pack_ranked_pick, proposal_rank_state, rank_proposals_or_skip, skipped
    from jevops.outer import dumps_compact, exc_head, result_usage
    from jevops.pick import numbered_criteria

    def _invoke(module: Any) -> tuple[Any, float]:
        criteria = numbered_criteria(
            proposals,
            prefix="p",
            fmt=lambda _i, item: f"{item['kind']}: {item['note']}; {lra_loop.token_count(item['tactics'])} tok",
        )
        state = proposal_rank_state(record, current, criteria, tokens=lra_loop.token_count(current))
        questions = choice_questions(
            Choice=module.Choice,
            Noul=module.Noul,
            Score=module.Score,
            criteria=criteria,
            best_key="next_edit",
            best_instructions=(
                "Which proposal id should this Metropolis chain try? Prefer a deletion that "
                "keeps every case header and the prefix haves Hk/Hlen1/Hlen2. Do not write Lean."
            ),
            nouls={"likely_compiles": "Will the chosen edit still lake-compile?"},
            scores={
                "likely_shorter": (
                    "How likely is a token cut if it compiles?",
                    list(lra_fan.LIKELY_SHORTER_CRITERIA),
                )
            },
        )
        return invoke_system_one(module.TypeSafeClient(timeout=45.0), state, questions)

    def _skip(reason: Any, **extra: Any) -> dict[str, Any]:
        text = exc_head(reason) if isinstance(reason, BaseException) else str(reason)
        return skipped(text, **extra)

    def _record(result: Any) -> Any:
        inn, out = result_usage(result, fallback_in=lra_t1.estimate_tokens(dumps_compact(record)))
        return ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)

    return rank_proposals_or_skip(
        proposals=proposals,
        load_fn=load_typesafe,
        skip_fn=_skip,
        invoke_fn=_invoke,
        pack_fn=pack_ranked_pick,
        record_fn=_record,
    )


def metropolis_accept(*, old_tok: int, new_tok: int, temperature: float, rng: random.Random) -> bool:
    from jevops.search import metropolis_token_accept

    return metropolis_token_accept(old_tok=old_tok, new_tok=new_tok, temperature=temperature, rng=rng)


def leanstral_line_swap(
    record: Mapping[str, Any],
    tactics: str,
    rng: random.Random,
    locked_haves: set[str],
) -> Optional[dict[str, str]]:
    from jevops.mask import around_lines

    idxs = mutable_indices(tactics, locked_haves)
    if not idxs:
        return None
    index = rng.choice(idxs)
    lines = tactics.splitlines()
    target = lines[index]
    prompt = (
        "Replace ONE Lean 4 tactic line with a shorter equivalent. "
        "Reply with only that line. No sorry. Keep case/induction.\n\n"
        f"Problem: {record.get('name')}\n"
        f"Around:\n" + around_lines(tactics, index, radius=4) + "\n\n"
        f"Replace this line:\n{target}\n\nReplacement:"
    )
    import docker0_client as lra_d0

    result = lra_d0.generate_as_client(
        prompt,
        max_new_tokens=48,
        timeout=90.0,
        source=str(record.get("source") or ""),
        allow_owner_exec=False,
    )
    if result.skipped or not result.text:
        return None
    from jevops.outer import head_chars
    from jevops.search import line_swap_from_text

    return line_swap_from_text(
        tactics=tactics,
        index=index,
        text=result.text,
        parse_fn=lra_cb.parse_next_line,
        looks_fn=lra_cb.looks_like_tactic,
        replace_fn=apply_replace,
        stop=lra_cb.STOP_TOKEN,
        target=target,
        head_fn=head_chars,
    )


def compile_one(
    record: Mapping[str, Any],
    tactics: str,
    *,
    state_root: Path,
    timeout: float,
    restore: bytes,
    memory: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    import nca_kernel as lra_kern

    def _run() -> dict[str, Any]:
        return dict(
            lra_kb.compile_tactics(
                record,
                tactics,
                state_root=state_root,
                timeout=timeout,
                restore=restore,
            )
        )

    return lra_kern.guarded_compile(
        memory,
        name=record.get("name"),
        kind="mcmc",
        tactics=tactics,
        compile_fn=_run,
    )


def run_mcmc(
    record: Mapping[str, Any],
    *,
    rounds: int,
    beam: int,
    temperature: float,
    seed: int,
    state_root: Path,
    timeout: float,
    init_tactics: Optional[str] = None,
    leanstral: bool = False,
    memory: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    reference = lra_fan.tactic_block(record)
    rng = random.Random(int(seed))
    ledger = lra_t1.ProblemLedger(
        name=f"{record.get('name')}#mcmc-beam",
        max_jev_calls=MAX_JEV,
        max_mistral_calls=0,
        max_grok_calls=0,
    )
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), state_root)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if

    restore = read_bytes_if(dest)
    start = (init_tactics or reference).strip("\n")
    start_compiled = compile_one(
        record, start, state_root=state_root, timeout=timeout, restore=restore, memory=memory
    )
    start_tok = int(start_compiled.get("token_count") or lra_loop.token_count(start))
    start_ok = bool(start_compiled.get("theorem_ok"))
    ref_tok = lra_loop.token_count(reference)
    from jevops.search import (
        filter_blacklist,
        init_mcmc_best,
        kind_prefix_indices,
        mcmc_chains,
        mcmc_result,
        mcmc_try_proposals,
        pin_front,
    )

    chains = mcmc_chains(start, start_tok, start_ok, beam, Chain)
    best = init_mcmc_best(
        start=start,
        start_ok=start_ok,
        start_tok=start_tok,
        reference=reference,
        ref_tok=ref_tok,
        kind="init" if init_tactics else "reference",
    )
    history: list[dict[str, Any]] = []
    lake_calls = 1
    leanstral_calls = 0
    locked = locked_have_names(reference)
    failed_bodies: set[str] = set()
    failed_kinds: set[str] = {
        "rewrite_refine_constructor",
        "rewrite_ih_short",
        "rewrite_ih_exact",
        "collapse_ih_simps",
        "drop_orphan_hnd",
        "drop_isnotdefined_simp",
        "drop_orphan_intros_hin",
    }
    sticky_fail = {
        "rewrite_refine_constructor",
        "rewrite_ih_short",
        "rewrite_ih_exact",
        "collapse_ih_simps",
        "drop_orphan_hnd",
        "drop_isnotdefined_simp",
        "drop_orphan_intros_hin",
    }
    from jevops.search import run_mcmc_rounds

    def _compile(body: str) -> dict[str, Any]:
        nonlocal lake_calls
        lake_calls += 1
        return compile_one(
            record,
            body,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            memory=memory,
        )

    leanstral_calls = run_mcmc_rounds(
        rounds=rounds,
        chains=chains,
        ledger=ledger,
        leanstral=leanstral,
        max_leanstral=MAX_LEANSTRAL,
        leanstral_fn=lambda tactics: leanstral_line_swap(record, tactics, rng, locked),
        propose_fn=lambda tactics, extra: propose_edits(tactics, reference, rng, extra=extra),
        filter_fn=filter_blacklist,
        rank_fn=lambda tactics, proposals: typesafe_rank_proposals(
            record, tactics, proposals, ledger=ledger
        ),
        pin_fn=pin_front,
        pin_prefixes=("drop_duplicate", "join_applies", "leanstral_"),
        try_fn=lambda **kwargs: mcmc_try_proposals(
            token_fn=lra_loop.token_count,
            accept_fn=metropolis_accept,
            **kwargs,
        ),
        compile_fn=_compile,
        history=history,
        failed_bodies=failed_bodies,
        failed_kinds=failed_kinds,
        sticky_fail=sticky_fail,
        best=best,
        temperature=temperature,
        rng=rng,
    )
    return mcmc_result(
        rounds=rounds,
        beam=beam,
        temperature=temperature,
        seed=seed,
        lake_calls=lake_calls,
        leanstral_calls=leanstral_calls,
        best=best,
        history=history,
        extra={"ledger": ledger.as_dict(), "hardware_class": HARDWARE_CLASS},
    )


def self_check() -> dict[str, Any]:
    tactics = (
        "  intros H\n"
        "  have Hk := foo\n"
        "  induction H\n"
        "  case a =>\n"
        "    simp_all\n"
        "    exact bar\n"
        "    simp_all\n"
    )
    rng = random.Random(0)
    props = propose_edits(tactics, tactics, rng)
    mh_short = metropolis_accept(old_tok=10, new_tok=8, temperature=2.0, rng=random.Random(1))
    mh_long = metropolis_accept(old_tok=10, new_tok=12, temperature=0.0, rng=random.Random(1))
    stub = (
        "  have Hk := foo\n"
        "  induction H\n"
        "  case a =>\n"
        f"    {REFINE_RFL}\n"
        f"    {IH_APPLY}\n"
        "        . simp_all\n"
        "        . simp_all\n"
    )
    kinds = {item["kind"] for item in propose_edits(stub, stub, rng)}
    return {
        "ok": bool(props)
        and all("have Hk" in item["tactics"] for item in props)
        and all("induction H" in item["tactics"] for item in props)
        and mh_short
        and not mh_long
        and "case a" in props[0]["tactics"]
        and "rewrite_refine_constructor" in kinds
        and "rewrite_ih_short" in kinds
        and "collapse_ih_simps" in kinds,
        "n_proposals": len(props),
        "hardware_class": HARDWARE_CLASS,
        "called_docker0": False,
        "arena_score": None,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--beam", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=3.0, help="Metropolis token temperature")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--init-file", type=Path, default=None, help="start chains from this tactic file instead of the original")
    parser.add_argument("--leanstral", action="store_true", help="add up to 4 local docker0 one-line swap proposals")
    parser.add_argument("--names", default="Core.InitsUpdatesComm")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_check or not args.live:
        from jevops.outer import print_ok

        return print_ok(self_check())
    from jevops.outer import pin_env

    pin_env({"IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0"}, overwrite=False)
    _raw, digest, records = lra_splice.load_warmup_records()
    from jevops.outer import split_csv

    names = split_csv(args.names)
    started = time.perf_counter()
    problems = []
    for name in names:
        from jevops.outer import lookup_named

        record = lookup_named(
            records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
        )
        init_text = None
        if args.init_file:
            from jevops.outer import read_text

            init_text = read_text(args.init_file)
        search = run_mcmc(
            record,
            rounds=args.rounds,
            beam=args.beam,
            temperature=args.temperature,
            seed=args.seed,
            state_root=args.state_root,
            timeout=args.timeout,
            init_tactics=init_text,
            leanstral=bool(args.leanstral),
        )
        reference = lra_fan.tactic_block(record)
        clone = lra_kb.lra_cw.clone_dir(str(record["url"]), args.state_root)
        dest = clone / lra_kb.lra_cw.source_relpath(record)
        from jevops.outer import read_bytes_if

        restore = read_bytes_if(dest)
        rows = []
        for kind, body in (("reference", reference), ("mcmc_best", None)):
            text = reference if kind == "reference" else str(search.get("best_tactics") or reference)
            compiled = compile_one(
                record,
                text,
                state_root=args.state_root,
                timeout=args.timeout,
                restore=restore,
                memory=None,
            )
            rows.append(
                {
                    "kind": kind,
                    "n_chars": len(text),
                    **{
                        k: compiled.get(k)
                        for k in ("ok", "theorem_ok", "module_exit_0", "token_count", "errors", "wall_ms")
                    },
                }
            )
        valid = [row for row in rows if row.get("theorem_ok")]
        kept = None
        if valid:
            kept = sorted(
                valid,
                key=lambda row: (
                    int(row.get("token_count") or 10**9),
                    0 if row.get("kind") == "reference" else 1,
                ),
            )[0]
        ref_tokens = lra_loop.token_count(reference)
        problems.append(
            lra_pca.redact(
                {
                    "name": name,
                    "warmup_jsonl_sha256": digest,
                    "search": search,
                    "candidates": rows,
                    "kept": None
                    if kept is None
                    else {"kind": kept["kind"], "theorem_ok": kept.get("theorem_ok"), "token_count": kept.get("token_count")},
                    "reference_token_count": ref_tokens,
                    "beats_reference": bool(
                        kept is not None
                        and kept.get("kind") != "reference"
                        and kept.get("token_count") is not None
                        and int(kept["token_count"]) < ref_tokens
                    ),
                    "hardware_class": HARDWARE_CLASS,
                    "called_docker0": False,
                    "called_hosted_mistral": False,
                    "official_track2": False,
                    "arena_score": None,
                }
            )
        )
    from jevops.outer import elapsed_ms, utc_stamp, write_json_pair

    payload = {
        "schema": "lra-mcmc-beam/v1",
        "observed_at": utc_stamp(),
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "hardware_class": HARDWARE_CLASS,
        "called_docker0": False,
        "called_hosted_mistral": False,
        "official_track2": False,
        "arena_score": None,
        "wall_ms": elapsed_ms(started),
        "problems": problems,
    }
    latest = write_json_pair(
        args.out,
        payload,
        prefix="mcmc-beam",
        latest="mcmc-beam-latest.json",
        refuse="apikey_",
    )
    from jevops.outer import print_json

    print_json(
        {
            "ok": True,
            "latest": str(latest),
            "kept": [{"name": item.get("name"), "kept": item.get("kept")} for item in problems],
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
