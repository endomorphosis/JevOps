#!/usr/bin/env python3
"""Jev-guided stochastic search over MCA holes with parallel hammers.

This is not neural SGD. Each round TypeSafe scores remaining hole-drops
(surrogate gradient). We sample the top Choice plus one random hole
(stochastic minibatch), apply the drop, then run identity / simp_all /
omega closers in parallel. Lake is the true loss. Leanstral is one
optional restart if no descent. Never docker0. Not official Track 2.
Not an Arena ranking.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import draft_fanout as lra_fan  # noqa: E402
import mca_mask_replace as lra_mask  # noqa: E402
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402
import track1_mistral_leanstral as lra_mistral  # noqa: E402

ROOT_ACCEL = _jevops_path.IPFS_ACCELERATE_ROOT
DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"

PROTOCOL = "LRA/v1"
PR_ID = "PR-9e"
HARDWARE_CLASS = "mistral_labs_api"


def drop_subset(tactics: str, holes: Sequence[lra_mask.Hole], chosen: Sequence[str]) -> str:
    from jevops.tactics import drop_subset as _fn

    return _fn(tactics, holes, chosen)


def hammer_variants(tactics: str, reference: str) -> list[tuple[str, str]]:
    """Parallel tactician branches. Aesop is not a Strata/CSLib dep."""

    import inits_updates_shorten as lra_ius
    import symbol_diffuse as lra_sym
    from jevops.outer import head_seq
    from jevops.tactics import hammer_variants as _fn

    extras: list[tuple[str, str]] = [
        ("inits_replay", lra_ius.replay(reference)),
        ("inits_step", lra_ius.replay(tactics)),
    ]
    extras.extend((str(item["kind"]), str(item["tactics"])) for item in head_seq(lra_ius.propose(tactics), 8))
    extras.extend(
        (str(item["kind"]), str(item["tactics"]))
        for item in lra_sym.closed_candidates(tactics, max_candidates=6)
    )
    return _fn(tactics, reference, extras)


def jev_round(
    record: Mapping[str, Any],
    holes: Sequence[lra_mask.Hole],
    history: Sequence[Mapping[str, Any]],
    keep_tokens: int,
) -> dict[str, Any]:
    lra_pca.pin_typesafe_path()
    from _optional_deps import load_typesafe

    from jevops.jev import (
        choice_questions,
        hole_criteria,
        hole_round_state,
        invoke_system_one,
        pack_choice_round,
        skipped,
    )

    from jevops.jev import complete_choice_round

    typesafe_module, typesafe_reason = load_typesafe()
    if typesafe_module is None:
        return skipped("typesafe_inference_missing", error=typesafe_reason)
    Choice = typesafe_module.Choice
    Noul = typesafe_module.Noul
    Score = typesafe_module.Score
    TypeSafeClient = typesafe_module.TypeSafeClient
    typesafe_configured = typesafe_module.typesafe_configured

    criteria = hole_criteria(holes)
    state = hole_round_state(record, holes, history, keep_tokens)
    questions = choice_questions(
        Choice=Choice,
        Noul=Noul,
        Score=Score,
        criteria=criteria,
        best_key="next_hole",
        best_instructions=(
            "Which hole id should we drop next in this stochastic descent? "
            "Prefer strength_reduction simp-at runs, then dead_code rename_i. "
            "Do not write Lean."
        ),
        nouls={"likely_compiles": "Will dropping that hole still compile?"},
        scores={
            "likely_token_cut": (
                "How large a token cut if that hole is dropped?",
                list(lra_fan.LIKELY_SHORTER_CRITERIA),
            )
        },
    )
    return complete_choice_round(
        configured=bool(typesafe_configured()),
        criteria=criteria,
        invoke_fn=lambda: invoke_system_one(TypeSafeClient(timeout=45.0), state, questions),
        pack_fn=lambda result, wall_ms, **_k: pack_choice_round(
            result,
            choice_key="next_hole",
            noul_key="likely_compiles",
            score_key="likely_token_cut",
            wall_ms=wall_ms,
        ),
        redact_fn=lra_pca.redact,
        skip_fn=lambda reason, **extra: skipped(reason, **extra),
        skip_extra={"choice": None, "probabilities": {}},
    )


def evaluate_tactics(
    record: Mapping[str, Any],
    tactics: str,
    *,
    state_root: Path,
    timeout: float,
    restore: bytes,
    reference: str,
    memory: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    import nca_kernel as lra_kern
    from jevops.search import compile_variant_evals

    def _compile(label: str, body: str) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            return dict(
                lra_kb.compile_tactics(
                    record, body, state_root=state_root, timeout=timeout, restore=restore
                )
            )

        return dict(
            lra_kern.guarded_compile(
                memory,
                name=record.get("name"),
                kind=f"sgd:{label}",
                tactics=body,
                compile_fn=_run,
            )
        )

    variants = hammer_variants(tactics, reference)
    # Lake splices one file; serialize compiles. "Parallel hammers" means
    # four closer variants per minibatch, not concurrent writes.
    return compile_variant_evals(variants, _compile)


def sgd_search(
    name: str,
    *,
    state_root: Path,
    timeout: float,
    rounds: int,
    seed: int,
    use_leanstral: bool,
    memory: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    from jevops.outer import lookup_named

    _raw, digest, records = lra_splice.load_warmup_records()
    record = lookup_named(
        records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
    )
    reference = lra_fan.tactic_block(record)
    holes = lra_mask.find_holes(reference)
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), state_root)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if

    restore = read_bytes_if(dest)
    keep = reference
    keep_tokens = lra_loop.token_count(reference)
    history: list[dict[str, Any]] = []
    dropped: set[str] = set()
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    from jevops.search import boxed_keepbest, coordinate_rounds, minibatch_ids

    box = {"tokens": keep_tokens, "keep": keep}
    jevs: list[dict[str, Any]] = []

    def _choose(remaining: Sequence[Any], _dropped: set[str], _round: int) -> list[str]:
        jev = jev_round(record, remaining, history, box["tokens"])
        jevs.append(jev)
        ranked = sorted(
            (jev.get("probabilities") or {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )
        return minibatch_ids(
            [hole.hole_id for hole in remaining],
            choice=jev.get("choice"),
            ranked=ranked,
            rng=rng,
            k=2,
        )

    walked = coordinate_rounds(
        holes,
        rounds=rounds,
        choose_fn=_choose,
        trial_fn=lambda chosen: drop_subset(reference, holes, chosen),
        eval_fn=lambda trial: evaluate_tactics(
            record,
            trial,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            reference=reference,
            memory=memory,
        ),
        accept_fn=boxed_keepbest(box),
        keep_tokens=keep_tokens,
        keep_body=keep,
        history=history,
    )
    keep = str(walked["keep"])
    keep_tokens = int(walked["keep_tokens"])
    dropped = set(walked["dropped"])
    history = list(walked["history"])
    from jevops.search import attach_jev_rounds, maybe_leanstral_restart, sgd_payload

    rounds_out = attach_jev_rounds(walked["rounds"], jevs, history)

    def _generate() -> tuple[str, Any, Any]:
        lra_mistral.load_keyfiles()
        lra_mistral.pin_paths()
        ledger = lra_t1.ProblemLedger(name=f"{name}#sgd")
        shots = [
            lra_mask.few_shot_example(item)
            for item in records
            if item.get("name") in lra_mask.SHOT_NAMES and item.get("name") != name
        ]
        prompt = lra_mask.few_shot_prompt(record, shots)
        text, identity, _line = lra_mistral.generate_mistral(
            prompt, ledger, max_new_tokens=700, timeout=180.0
        )
        return text, identity, ledger

    keep, keep_tokens, leanstral = maybe_leanstral_restart(
        use=use_leanstral,
        keep=keep,
        keep_tokens=keep_tokens,
        ref_tokens=lra_loop.token_count(reference),
        generate_fn=_generate,
        flatten_fn=lambda text: lra_kb.flatten_overindent(
            reference, lra_kb.match_reference_indent(reference, lra_loop.extract_generated_tactics(text))
        ),
        eval_fn=lambda body: evaluate_tactics(
            record,
            body,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            reference=reference,
            memory=memory,
        ),
        hammer_fn=lambda filled, evals: lra_mask.hammer_repair(
            filled, reference, (evals[0].get("errors") if evals else None) or []
        ),
        ledger_fn=lambda ledger: ledger.as_dict(),
    )

    ref_tokens = lra_loop.token_count(reference)
    return lra_pca.redact(
        sgd_payload(
            name=name,
            digest=digest,
            n_holes=len(holes),
            ref_tokens=ref_tokens,
            keep_tokens=keep_tokens,
            dropped=dropped,
            rounds=rounds_out,
            leanstral=leanstral,
            hardware_class=HARDWARE_CLASS,
            protocol=PROTOCOL,
            pr=PR_ID,
        )
    )


def _accept(evals: Sequence[Mapping[str, Any]], keep_tokens: int) -> Optional[dict[str, Any]]:
    from jevops.search import accept_keepbest

    return accept_keepbest(evals, keep_tokens)


def diffuse_search(
    name: str,
    *,
    state_root: Path,
    timeout: float,
    rounds: int,
    seed: int,
    use_leanstral: bool,
    tau: float = 0.12,
) -> dict[str, Any]:
    """Exploit: drop all high-p holes at once. Explore: random subset + Leanstral noise.

    Denoise: hammer variants. This is bandit/coordinate search with a diffusion
    restart, not neural SGD or a trained denoiser.
    """

    rng = random.Random(seed)
    from jevops.outer import head_chars, lookup_named

    _raw, digest, records = lra_splice.load_warmup_records()
    record = lookup_named(
        records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
    )
    reference = lra_fan.tactic_block(record)
    holes = lra_mask.find_holes(reference)
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), state_root)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if

    restore = read_bytes_if(dest)
    keep = reference
    keep_tokens = lra_loop.token_count(reference)
    dropped: set[str] = set()
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    if use_leanstral:
        lra_mistral.load_keyfiles()
        lra_mistral.pin_paths()
    from jevops.search import apply_keepbest, pack_diffuse, run_diffuse_rounds, strip_tactics

    def consider(label: str, hole_ids: Sequence[str]) -> dict[str, Any]:
        nonlocal keep, keep_tokens, dropped
        trial = drop_subset(reference, holes, list(dict.fromkeys(list(dropped) + list(hole_ids))))
        evals = evaluate_tactics(
            record,
            trial,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            reference=reference,
        )
        hit, keep_tokens, body = apply_keepbest(evals, keep_tokens, trial=trial)
        if hit:
            keep = body
            dropped.update(hole_ids)
        return {
            "label": label,
            "holes": list(hole_ids),
            "accepted": bool(hit),
            "keep_tokens": keep_tokens,
            "evals": strip_tactics(evals),
        }

    def _noise(round_i: int, remaining: Sequence[Any]) -> Any:
        nonlocal keep, keep_tokens
        if not use_leanstral:
            return None
        round_ledger = lra_t1.ProblemLedger(name=f"{name}#diffuse-r{round_i}")
        if remaining:
            hole = rng.choice(list(remaining))
            prompt = lra_mask.one_hole_prompt(record, keep, hole)
            noise_meta = {"hole": hole.hole_id, "mode": "one_hole"}
        else:
            shots = [
                lra_mask.few_shot_example(item)
                for item in records
                if item.get("name") in lra_mask.SHOT_NAMES and item.get("name") != name
            ]
            prompt = (
                f"Current lake-valid keep is {keep_tokens} tokens "
                f"(reference {lra_loop.token_count(reference)}). "
                "Shrink it further. Keep induction and every case arm. "
                "Delete only residual simp-at/rename_i/have/rw. No sorry.\n\n"
                + lra_mask.few_shot_prompt(record, shots)
                + f"\nCURRENT KEEP ({keep_tokens} tokens):\n{head_chars(keep, 1800)}\n"
            )
            noise_meta = {"hole": None, "mode": "shrink_keep"}
        try:
            text, identity, _line = lra_mistral.generate_mistral(
                prompt, round_ledger, max_new_tokens=400, timeout=120.0
            )
        except (lra_t1.Track1LedgerError, lra_mistral.Track1MistralError):
            text, identity = "", {}
        filled = lra_loop.extract_generated_tactics(text) if text else ""
        if not filled:
            return None
        noisy = lra_kb.flatten_overindent(keep, lra_kb.match_reference_indent(keep, filled))
        evals_n = evaluate_tactics(
            record, noisy, state_root=state_root, timeout=timeout, restore=restore, reference=reference
        )
        denoised = lra_mask.hammer_repair(
            noisy, reference, (evals_n[0].get("errors") if evals_n else None) or []
        )
        evals_d = evaluate_tactics(
            record, denoised, state_root=state_root, timeout=timeout, restore=restore, reference=reference
        )
        hit, keep_tokens, body = apply_keepbest(evals_n + evals_d, keep_tokens, trial=denoised)
        if hit:
            keep = body
        return {
            **noise_meta,
            "identity": identity,
            "accepted": bool(hit),
            "noise_evals": strip_tactics(evals_n),
            "denoise_evals": strip_tactics(evals_d),
        }

    walked = run_diffuse_rounds(
        holes,
        rounds=rounds,
        tau=tau,
        rng=rng,
        consider_fn=consider,
        jev_fn=lambda remaining, history, tokens: jev_round(record, remaining, history, tokens),
        noise_fn=_noise,
        keep_tokens=keep_tokens,
        dropped=dropped,
    )
    keep_tokens = int(walked["keep_tokens"])
    dropped = set(walked["dropped"])
    ref_tokens = lra_loop.token_count(reference)
    return lra_pca.redact(
        pack_diffuse(
            name=name,
            digest=digest,
            n_holes=len(holes),
            ref_tokens=ref_tokens,
            keep_tokens=keep_tokens,
            dropped=dropped,
            rounds=walked["rounds"],
            hardware_class=HARDWARE_CLASS,
            protocol=PROTOCOL,
            pr=PR_ID,
        )
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names", default="CallElimCorrect.substOldPostSubset,Core.InitsUpdatesComm")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-leanstral", action="store_true")
    parser.add_argument("--diffuse", action="store_true", help="multi-hole exploit + Leanstral noise/denoise")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    from jevops.outer import pin_env

    pin_env({"IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0"}, overwrite=False)
    from jevops.outer import split_csv

    names = split_csv(args.names)
    started = time.perf_counter()
    reports = [
        (
            diffuse_search if args.diffuse else sgd_search
        )(
            name,
            state_root=args.state_root,
            timeout=args.timeout,
            rounds=args.rounds,
            seed=args.seed,
            use_leanstral=not args.no_leanstral,
        )
        for name in names
    ]
    from jevops.outer import elapsed_ms, utc_stamp, write_json_pair

    payload = {
        "schema": "lra-sgd-fanout-batch/v1",
        "observed_at": utc_stamp(),
        "arena_score": None,
        "called_docker0": False,
        "wall_ms": elapsed_ms(started),
        "problems": reports,
    }
    latest = write_json_pair(
        args.out,
        payload,
        prefix="sgd-fanout",
        latest="sgd-fanout-latest.json",
        refuse="apikey_",
        refuse_msg="refusing to write a receipt that contains a secret",
    )
    from jevops.outer import print_json

    print_json(
        {
            "ok": True,
            "latest": str(latest),
            "results": [
                {
                    "name": item.get("name"),
                    "ref": item.get("ref_tokens"),
                    "keep": item.get("keep_tokens"),
                    "ratio": item.get("ratio"),
                    "dropped": item.get("dropped"),
                }
                for item in reports
            ],
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
