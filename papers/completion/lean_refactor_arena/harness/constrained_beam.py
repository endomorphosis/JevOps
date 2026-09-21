#!/usr/bin/env python3
"""Greedy / beam tactic-line search on *local* docker0 Leanstral, TypeSafe-pruned.

Hosted Labs Leanstral is not used. Generator is docker0
``172.17.0.1:8080`` via ``generate_text`` (NVFP4 Spark, hardware_class
``spark_gb10``). Not official Track 2. Not an Arena ranking.

A "token" here is one Lean tactic *line*, not a BPE token: llama.cpp chat
does not expose next-token logprobs through this client. After each line,
TypeSafe Choice ranks a closed candidate set (Leanstral proposal + reference
vocab + STOP) so the beam cannot explode into all of Lean.

Never LOCK_EX. Never autostart llama-server. Jev does not write Lean.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
STOP_TOKEN = "STOP"
CLOSERS = ("simp_all", "try simp_all", "omega", "try omega", "constructor", "rfl")
_TACTIC_HEAD = (
    "case ",
    "have ",
    "exact ",
    "apply ",
    "refine ",
    "simp",
    "rw ",
    "omega",
    "constructor",
    "intro",
    "induction ",
    "exists ",
    "· ",
    ". ",
)
HARDWARE_CLASS = "spark_gb10"
PROTOCOL = "LRA/v1"
PR_ID = "PR-9f"
MAX_STEPS_DEFAULT = 12
BEAM_DEFAULT = 1
MAX_NEW_TOKENS_LINE = 48
LINE_TIMEOUT = 120.0
MAX_CANDIDATES = 12
MAX_JEV_CALLS = 48
MAX_SAMPLES = 4

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import docker0_client as lra_d0  # noqa: E402
import draft_fanout as lra_fan  # noqa: E402
import generate_text as lra_gt  # noqa: E402
import mca_mask_replace as lra_mask  # noqa: E402
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256


from jevops.tactics import BeamItem


def have_binder_name(stripped: str) -> str:
    from jevops.tactics import have_binder_name as _fn

    return _fn(stripped)


def identifier_used(name: str, text: str) -> bool:
    from jevops.tactics import identifier_used as _fn

    return _fn(name, text)


def pca_prefix(tactics: str) -> str:
    """Keep PCA glue; keep MCA ``have`` only when a later line still names it."""

    from jevops.tactics import pca_prefix as _fn

    return _fn(tactics)


def reference_vocab(tactics: str) -> list[str]:
    from jevops.tactics import reference_vocab as _fn

    return _fn(tactics, stop=STOP_TOKEN)


def last_open_case(prefix: str) -> Optional[str]:
    from jevops.tactics import last_open_case as _fn

    return _fn(prefix)


def case_header_map(reference: str) -> dict[str, str]:
    from jevops.tactics import case_header_map as _fn

    return _fn(reference)


def case_arm_lines(reference: str, tag: str) -> list[str]:
    from jevops.tactics import case_arm_lines as _fn

    return _fn(reference, tag)


def _status_pack(pack: Mapping[str, Any]) -> dict[str, Any]:
    from jevops.outer import remap_get

    return remap_get(
        pack,
        {
            "missing": "missing_cases",
            "empty": "empty_arms",
            "unfinished": "unfinished_arms",
            "earliest": "earliest_unfinished",
            "open": "open_case",
            "next_original": "next_original",
        },
        lists=("missing", "empty", "unfinished"),
    )


def structure_pack(reference: str, prefix: str) -> dict[str, Any]:
    """PCA skeleton + MCA holes of the *original* proof, plus what the prefix still lacks."""

    from jevops.tactics import structure_pack as _fn

    return _fn(reference, prefix, token_fn=lra_loop.token_count)


def guided_vocab(prefix: str, reference: str, pack: Mapping[str, Any]) -> list[str]:
    """Priority next lines: missing PCA case headers before MCA haves."""

    from jevops.search import guided_next

    headers = case_header_map(reference)
    return guided_next(
        prefix,
        _status_pack(pack),
        header_of=lambda tag: headers.get(str(tag), ""),
        remaining_fn=lambda tag: remaining_arm_lines(prefix, reference, str(tag)),
        arm_lines_fn=lambda tag: case_arm_lines(reference, str(tag)),
        closers=CLOSERS,
    )


def filter_to_earliest(
    lines: Sequence[str],
    pack: Mapping[str, Any],
    reference: str,
) -> list[str]:
    """Drop candidates that skip past the earliest unfinished PCA case."""

    from jevops.search import filter_to_earliest as _fn

    return _fn(
        lines,
        _status_pack(pack),
        header_of=lambda tag: case_header_map(reference).get(str(tag), ""),
        stop=STOP_TOKEN,
        closer_pred=looks_like_closer,
        header_match=lambda stripped, earliest: stripped.startswith("case ") and earliest in stripped.split(),
        tag_token_fn=lambda tag: f"case {tag}",
    )


def looks_like_closer(stripped: str) -> bool:
    from jevops.tactics import looks_like_closer as _fn

    return _fn(stripped, closers=CLOSERS)


def looks_like_tactic(stripped: str) -> bool:
    from jevops.tactics import looks_like_tactic as _fn

    return _fn(stripped, stop=STOP_TOKEN, closers=CLOSERS)


def parse_next_line(text: str) -> str:
    from jevops.lean import parse_next_tactic_line

    return parse_next_tactic_line(text, stop=STOP_TOKEN)


def step_prompt(
    record: Mapping[str, Any],
    prefix: str,
    vocab: Sequence[str],
    pack: Optional[Mapping[str, Any]] = None,
) -> str:
    from jevops.tactics import step_prompt as _fn

    return _fn(record, prefix, vocab, pack)


def pca_case_tags(tactics: str) -> list[str]:
    from jevops.tactics import pca_case_tags as _fn

    return _fn(tactics)


def case_body_lines(prefix: str, tag: str) -> list[str]:
    from jevops.tactics import case_body_lines as _fn

    return _fn(prefix, tag)


def empty_case_arms(prefix: str, reference: str) -> list[str]:
    from jevops.tactics import empty_case_arms as _fn

    return _fn(prefix, reference)


def is_mca_line(stripped: str) -> bool:
    from jevops.tactics import is_mca_line as _fn

    return _fn(stripped)


def arm_keep_lines(reference: str, tag: str) -> list[str]:
    """Original arm tactics; keep MCA ``have`` only when a later line still names it."""

    from jevops.tactics import arm_keep_lines as _fn

    return _fn(reference, tag)


def remaining_arm_lines(prefix: str, reference: str, tag: str) -> list[str]:
    """Original keep-lines not yet copied, counting indent-sensitive occurrences."""

    from jevops.tactics import remaining_arm_lines as _fn

    return _fn(prefix, reference, tag)


def stop_allowed(prefix: str, reference: str) -> bool:
    """Do not STOP while a PCA case header is missing or its original arm is unfinished."""

    from jevops.tactics import stop_allowed as _fn

    return _fn(prefix, reference)


def unused_vocab(prefix: str, vocab: Sequence[str]) -> list[str]:
    from jevops.tactics import unused_vocab as _fn

    return _fn(prefix, vocab, stop=STOP_TOKEN)


def typesafe_prune(
    record: Mapping[str, Any],
    prefix: str,
    candidates: Sequence[str],
    *,
    ledger: lra_t1.ProblemLedger,
    keep: int,
    context: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops.search import unique_cap

    from jevops.jev import skipped
    from jevops.outer import exc_head, head_seq
    from jevops.pick import numbered_criteria

    unique = unique_cap(candidates, cap=MAX_CANDIDATES, empty=STOP_TOKEN)
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    ts_path = _jevops_path.TYPESAFE_INFERENCE_PATH
    if not ts_path.is_file():
        return skipped(
            "typesafe_inference_missing",
            kept=head_seq(unique, keep),
            jev_generated_lean=False,
            arena_score=None,
        )
    from jevops.outer import load_module_from_path

    module = load_module_from_path(ts_path, "lra_typesafe_inference")
    if module is None:
        return skipped(
            "typesafe_inference_spec",
            kept=head_seq(unique, keep),
            jev_generated_lean=False,
            arena_score=None,
        )
    Choice = module.Choice
    TypeSafeClient = module.TypeSafeClient
    typesafe_configured = module.typesafe_configured

    if not typesafe_configured():
        return skipped("no_key", kept=head_seq(unique, keep), jev_generated_lean=False, arena_score=None)
    pack = dict(context or {})
    criteria = numbered_criteria(unique, prefix="c")
    from jevops.jev import pack_prune, prune_state, rank_prune_kept

    state = prune_state(record, prefix, pack, criteria)
    questions = {
        "next_line": Choice(
            instructions=(
                "Which candidate is the best NEXT tactic line? Do not write Lean. "
                "Fill earliest_unfinished in original order: if its header is missing, pick that "
                "header; if the arm still has next_original, pick exactly that line. Never skip "
                "ahead to a later case. Never pick have/rename or English. STOP only when every "
                "PCA arm has used its original non-MCA tactics."
            ),
            criteria=criteria,
        )
    }
    from jevops.jev import complete_prune, invoke_system_one, unpack_response
    from jevops.outer import dumps_compact, usage_tokens

    def _record(usage: Any) -> Any:
        inn, out = usage_tokens(
            usage, fallback_in=lra_t1.estimate_tokens(dumps_compact(state))
        )
        return ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)

    return complete_prune(
        invoke_fn=lambda: invoke_system_one(TypeSafeClient(timeout=45.0), state, questions),
        skip_fn=lambda exc: skipped(
            exc_head(exc),
            kept=head_seq(unique, keep),
            jev_generated_lean=False,
            arena_score=None,
        ),
        unpack_fn=unpack_response,
        record_fn=_record,
        rank_fn=rank_prune_kept,
        pack_fn=pack_prune,
        criteria=criteria,
        unique=unique,
        keep=keep,
    )


def propose_lines(
    record: Mapping[str, Any],
    item: BeamItem,
    vocab: Sequence[str],
    *,
    beam: int,
    temperature: float,
    generate: Optional[Callable[..., str]],
    pack: Optional[Mapping[str, Any]] = None,
    reference: str = "",
) -> list[str]:
    pack = dict(pack or {})
    priority = guided_vocab(item.prefix, reference, pack) if reference else unused_vocab(item.prefix, vocab)
    prompt = step_prompt(record, item.prefix, priority or unused_vocab(item.prefix, vocab), pack)
    n_samples = 1 if beam <= 1 else min(max(int(beam), 1), MAX_SAMPLES)
    from jevops.search import merge_next_line_proposals, sample_next_lines

    def _one() -> Any:
        if generate is not None:
            return generate(prompt, temperature=temperature)
        result = lra_d0.generate_as_client(
            prompt,
            max_new_tokens=MAX_NEW_TOKENS_LINE,
            timeout=LINE_TIMEOUT,
            source=str(record.get("source") or ""),
            allow_owner_exec=False,
            temperature=temperature,
            stop=["\n\n"],
        )
        if result.skipped or not result.text:
            return None
        from jevops.lean import refuse_line_identity

        refuse_line_identity(
            result.identity,
            allowed=lra_gt.ALLOWED_RESOLVED_PROVIDERS,
            forbidden=lra_gt.FORBIDDEN_FALLBACK_PROVIDERS,
            error_cls=lra_gt.LraGenerateError,
        )
        return result.text

    proposals = sample_next_lines(
        n_samples,
        generate_fn=_one,
        parse_fn=parse_next_line,
        empty=STOP_TOKEN,
    )

    return merge_next_line_proposals(
        proposals,
        priority,
        stop=STOP_TOKEN,
        cap=MAX_CANDIDATES,
        filter_fn=lambda rows: filter_to_earliest(rows, pack, reference),
    )


def extend_prefix(prefix: str, nxt: str, *, original: Optional[str] = None) -> str:
    """Append ``nxt``, preferring the original line's leading indent when it matches."""

    from jevops.search import extend_prefix as _fn

    return _fn(prefix, nxt, stop=STOP_TOKEN, original=original, case_token="case ")


def run_search(
    record: Mapping[str, Any],
    *,
    mode: str,
    max_steps: int,
    beam: int,
    temperature: float = 0.0,
    generate: Optional[Callable[..., str]] = None,
    prune: Optional[Callable[..., dict[str, Any]]] = None,
) -> dict[str, Any]:
    tactics = lra_fan.tactic_block(record)
    prefix0 = pca_prefix(tactics)
    vocab = reference_vocab(tactics)
    ledger = lra_t1.ProblemLedger(
        name=f"{record.get('name')}#constrained-beam-local",
        max_jev_calls=MAX_JEV_CALLS,
        max_mistral_calls=0,
        max_grok_calls=0,
    )
    beam_n = 1 if mode == "greedy" else max(1, int(beam))
    temp = float(temperature)
    n_samples = 1 if beam_n <= 1 else min(beam_n, MAX_SAMPLES)
    prune_fn = prune or typesafe_prune
    from jevops.search import pack_beam_search, run_prefix_beam

    def _prune(item: BeamItem, proposals: Sequence[str], pack: Mapping[str, Any]) -> dict[str, Any]:
        if prune is None:
            return typesafe_prune(
                record,
                item.prefix,
                proposals,
                ledger=ledger,
                keep=beam_n,
                context=pack,
            )
        return prune_fn(record, item.prefix, proposals, ledger=ledger, keep=beam_n)

    out = run_prefix_beam(
        prefix0,
        max_steps=max_steps,
        beam_n=beam_n,
        stop_token=STOP_TOKEN,
        pack_fn=lambda prefix: structure_pack(tactics, prefix),
        stop_allowed_fn=lambda prefix: stop_allowed(prefix, tactics),
        propose_fn=lambda item, pack: propose_lines(
            record,
            item,
            vocab,
            beam=beam_n,
            temperature=temp,
            generate=generate,
            pack=pack,
            reference=tactics,
        ),
        prune_fn=_prune,
        extend_fn=lambda prefix, nxt, pack: extend_prefix(
            prefix, nxt, original=str(pack.get("next_original") or "") or None
        ),
        filter_fn=lambda lines, pack: filter_to_earliest(lines, pack, tactics),
        n_samples=n_samples,
        item_cls=BeamItem,
    )
    return pack_beam_search(
        out,
        prefix=prefix0,
        vocab_n=len(vocab),
        mode=mode,
        beam=beam_n,
        temperature=temp,
        max_steps=max_steps,
        extra={
            "pca_mca": structure_pack(tactics, prefix0),
            "ledger": ledger.as_dict(),
            "hardware_class": HARDWARE_CLASS,
            "called_docker0": generate is None,
            "official_track2": False,
        },
    )


def drop_first_bare_simp_all(tactics: str) -> Optional[str]:
    from jevops.tactics import drop_first_bare_simp_all as _fn

    return _fn(tactics)


def drop_last_bare_simp_all(tactics: str) -> Optional[str]:
    """Drop the last standalone ``simp_all`` / ``. simp_all`` line (not ``<;> simp_all``)."""

    from jevops.tactics import drop_last_bare_simp_all as _fn

    return _fn(tactics)


def repair_no_progress_simp_all(tactics: str, errors: Sequence[Mapping[str, Any]]) -> Optional[str]:
    from jevops.repair import repair_on_needle

    return repair_on_needle(
        tactics, errors, "simp_all made no progress", drop_last_bare_simp_all
    )


def join_consecutive_exacts(tactics: str) -> str:
    from jevops.tactics import join_consecutive_exacts as _fn

    return _fn(tactics)


def collapse_defined_simp(tactics: str) -> str:
    from jevops.tactics import collapse_defined_simp as _fn

    return _fn(tactics)


def shorten_keeping_prefix_haves(tactics: str) -> list[tuple[str, str]]:
    """Compiler shortenings that must keep every original prefix ``have`` (simp_all fuel)."""

    import inits_updates_shorten as lra_ius
    from jevops.tactics import shorten_keeping_prefix_haves as _fn

    extras: list[tuple[str, str]] = [("inits_replay", lra_ius.replay(tactics))]
    extras.extend((str(item.get("kind") or "inits_step"), str(item.get("tactics") or "")) for item in lra_ius.propose(tactics))
    keep_extras = [
        (f"span_{draft.family}_{draft.draft_id}", draft.tactics)
        for draft in lra_fan.span_preserving_drafts(tactics)
    ]
    return _fn(tactics, extras, keep_extras)


def prefix_have_lines(reference: str) -> list[str]:
    from jevops.tactics import prefix_have_lines as _fn

    return _fn(reference)


def insert_haves_before_induction(draft: str, haves: Sequence[str]) -> str:
    from jevops.tactics import insert_haves_before_induction as _fn

    return _fn(draft, haves)


def lake_keepbest(
    record: Mapping[str, Any],
    tactics_list: Sequence[str],
    *,
    state_root: Path,
    timeout: float,
) -> list[dict[str, Any]]:
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), state_root)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if

    restore = read_bytes_if(dest)
    reference = lra_fan.tactic_block(record)
    from jevops.search import compile_variant_rows, keepbest_beam_pairs
    from jevops.tactics import keepbest_variants

    pairs = keepbest_beam_pairs(reference, tactics_list, variants_fn=keepbest_variants)
    return compile_variant_rows(
        pairs,
        lambda body: lra_kb.compile_tactics(
            record, body, state_root=state_root, timeout=timeout, restore=restore
        ),
    )


def self_check() -> dict[str, Any]:
    tactics = (
        "  intros Hup Hinit\n"
        "  have Hlen1 := InitStatesLength Hinit\n"
        "  induction Hup generalizing σ''\n"
        "  case update_none =>\n"
        "    simp_all\n"
        "    apply And.intro\n"
        "  case update_some =>\n"
        "    rw [List.unzip_zip]\n"
    )
    prefix = pca_prefix(tactics)
    vocab = reference_vocab(tactics)
    nxt = parse_next_line("```\n  simp_all\n  omega\n```")
    dropped = drop_last_bare_simp_all("    exact foo\n        . simp_all\n")
    indented = extend_prefix("  case update_none =>", "    exact InitStatesNotDefined Hinit")
    dup_ref = (
        "  induction H\n"
        "  case a =>\n"
        "    simp_all\n"
        "    exact foo\n"
        "    simp_all\n"
    )
    dup_pref = pca_prefix(dup_ref) + "\n  case a =>\n    simp_all"
    dup_rem = remaining_arm_lines(dup_pref, dup_ref, "a")
    pack = structure_pack(tactics, prefix)
    guided = guided_vocab(prefix, tactics, pack)
    after_none = structure_pack(tactics, prefix + "\n  case update_none =>\n    simp_all")
    guided_after = guided_vocab(prefix + "\n  case update_none =>\n    simp_all", tactics, after_none)
    return {
        "ok": "have Hlen1" not in prefix
        and "induction Hup" in prefix
        and "case update_none" not in prefix
        and STOP_TOKEN in vocab
        and nxt.strip() == "simp_all"
        and dropped == "    exact foo"
        and "have Hk" in insert_haves_before_induction("  exists x\n  induction H\n", ["  have Hk := foo"])
        and "<;> exact" in join_consecutive_exacts("    exact A\n    exact B\n")
        and indented.endswith("    exact InitStatesNotDefined Hinit")
        and any("exact foo" in item for item in dup_rem)
        and sum(item.strip() == "simp_all" for item in dup_rem) == 1
        and any(
            "exact foo" in item
            for item in guided_vocab(
                dup_pref,
                dup_ref,
                structure_pack(dup_ref, dup_pref),
            )
        )
        and any("case update_none" in item for item in guided)
        and not any("update_some" in item for item in guided)
        and not any(item.strip().startswith("have ") for item in guided)
        and not any(item.strip().startswith("have ") for item in guided_after)
        and any(
            "And.intro" in item
            for item in guided_vocab(
                prefix + "\n  case update_none =>\n    simp_all",
                tactics,
                structure_pack(tactics, prefix + "\n  case update_none =>\n    simp_all"),
            )
        )
        and not any(
            "update_some" in item
            for item in guided_vocab(
                prefix + "\n  case update_none =>\n    simp_all",
                tactics,
                structure_pack(tactics, prefix + "\n  case update_none =>\n    simp_all"),
            )
        )
        and not any(item.strip().startswith("have ") for item in guided_vocab(
            prefix + "\n  case update_none =>\n    simp_all\n  case update_some =>\n    simp_all",
            tactics,
            structure_pack(
                tactics,
                prefix + "\n  case update_none =>\n    simp_all\n  case update_some =>\n    simp_all",
            ),
        ))
        and "172.17.0.1" in lra_gt.DOCKER0_HEALTH_URL,
        "pca_prefix": prefix,
        "vocab_n": len(vocab),
        "hardware_class": HARDWARE_CLASS,
        "called_hosted_mistral": False,
        "arena_score": None,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--repair-latest",
        action="store_true",
        help="lake keep-best + simp_all no-progress repair on constrained-beam-latest.json (no new Leanstral calls)",
    )
    parser.add_argument(
        "--shorten-reference",
        action="store_true",
        help="lake compiler shortenings of the original that keep prefix haves (no Leanstral)",
    )
    parser.add_argument("--mode", choices=("greedy", "beam"), default="greedy")
    parser.add_argument("--beam", type=int, default=BEAM_DEFAULT)
    parser.add_argument("--temperature", type=float, default=0.0, help="llama.cpp sampling temperature; 0 is greedy argmax")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS_DEFAULT)
    parser.add_argument("--names", default="Core.InitsUpdatesComm")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_check or (not args.live and not args.repair_latest and not args.shorten_reference):
        from jevops.outer import print_ok

        return print_ok(self_check())
    from jevops.outer import pin_env

    pin_env({"IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0"}, overwrite=False)
    repair_tactics: dict[str, str] = {}
    if args.repair_latest:
        latest = args.out / "constrained-beam-latest.json"
        from jevops.outer import read_json

        prior = read_json(latest)
        for item in prior.get("problems") or []:
            finals = ((item.get("search") or {}).get("finals") or [])
            if finals and item.get("name"):
                repair_tactics[str(item["name"])] = str(finals[0].get("tactics") or "")
    health = lra_gt.probe_docker0_health()
    if not args.repair_latest and not args.shorten_reference and not health.ok:
        payload = {
            "ok": True,
            "skipped": True,
            "reason": f"docker0_unhealthy: {health.error or health.status_code}",
            "hardware_class": HARDWARE_CLASS,
            "called_hosted_mistral": False,
            "called_docker0": False,
            "official_track2": False,
            "arena_score": None,
        }
        from jevops.outer import print_json

        print_json(payload)
        return 0
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
        if args.repair_latest:
            body = repair_tactics.get(name) or ""
            search = {
                "mode": "repair_latest",
                "called_docker0": False,
                "finals": [{"tactics": body, "steps": [], "stopped": True}],
                "hardware_class": HARDWARE_CLASS,
                "called_hosted_mistral": False,
                "official_track2": False,
                "arena_score": None,
            }
            lake_src = [body] if body.strip() else []
        elif args.shorten_reference:
            orig = lra_fan.tactic_block(record)
            drafts = shorten_keeping_prefix_haves(orig)
            search = {
                "mode": "shorten_reference",
                "called_docker0": False,
                "n_drafts": len(drafts),
                "draft_names": [item[0] for item in drafts],
                "finals": [{"tactics": body, "steps": [name], "stopped": True} for name, body in drafts],
                "hardware_class": HARDWARE_CLASS,
                "called_hosted_mistral": False,
                "official_track2": False,
                "arena_score": None,
            }
            lake_src = [body for _name, body in drafts]
        else:
            search = run_search(
                record,
                mode=args.mode,
                max_steps=args.max_steps,
                beam=args.beam,
                temperature=args.temperature,
            )
            lake_src = [item["tactics"] for item in search.get("finals") or []]
        lake_rows = lake_keepbest(
            record,
            lake_src,
            state_root=args.state_root,
            timeout=args.timeout,
        )
        valid = [row for row in lake_rows if row.get("theorem_ok")]
        kept = None
        if valid:
            kept = sorted(
                valid,
                key=lambda row: (
                    int(row.get("token_count") or 10**9),
                    0 if row.get("kind") == "reference" else 1,
                ),
            )[0]
        ref_tokens = lra_loop.token_count(lra_fan.tactic_block(record))
        problems.append(
            lra_pca.redact(
                {
                    "name": name,
                    "warmup_jsonl_sha256": digest,
                    "search": search,
                    "candidates": lake_rows,
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
                    "called_hosted_mistral": False,
                    "called_docker0": not args.repair_latest and not args.shorten_reference,
                    "official_track2": False,
                    "arena_score": None,
                }
            )
        )
    from jevops.outer import elapsed_ms, utc_stamp, write_json_pair

    payload = {
        "schema": "lra-constrained-beam-local/v1",
        "observed_at": utc_stamp(),
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "hardware_class": HARDWARE_CLASS,
        "called_hosted_mistral": False,
        "called_docker0": not args.repair_latest and not args.shorten_reference,
        "official_track2": False,
        "arena_score": None,
        "wall_ms": elapsed_ms(started),
        "problems": problems,
    }
    latest = write_json_pair(
        args.out,
        payload,
        prefix="constrained-beam",
        latest="constrained-beam-latest.json",
        refuse="apikey_",
    )
    from jevops.outer import print_json

    print_json(
        {
            "ok": True,
            "latest": str(latest),
            "kept": [{"name": item.get("name"), "kept": item.get("kept")} for item in problems],
            "hardware_class": HARDWARE_CLASS,
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
