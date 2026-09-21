#!/usr/bin/env python3
"""TypeSafe autoresearch features to rank MCMC Lean edits.

Follows https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery
at Lean-proof scale: many Noul/Score questions become numeric features;
code combines them (no CatBoost in this tree). Lake is the label.

Jev does not write Lean. Prefix haves stay locked. Not Track 2. Not Arena.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from pathlib import Path
from typing import Any, Mapping, Optional

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
HARDWARE_CLASS = "spark_gb10"
PROTOCOL = "LRA/v1"
PR_ID = "PR-9h"
MAX_JEV = 20

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import mcmc_beam as lra_mcmc  # noqa: E402
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"
TS_PATH = _jevops_path.TYPESAFE_INFERENCE_PATH

SEED_FEATURES = (
    ("likely_compiles", "noul", "After this edit the Lean file will still lake-compile."),
    ("likely_shorter", "noul", "This edit uses fewer Lean tokens than the current script."),
    ("drops_pca_glue", "noul", "This edit deletes induction, a case header, or intros/exists."),
    ("drops_prefix_have", "noul", "This edit deletes a prefix have (Hk, Hlen1, or Hlen2) that simp_all uses."),
    ("breaks_refine", "noul", "This edit will leave a refine ⟨rfl, ?_, ?_⟩ subgoal unsolved."),
    ("duplicate_needed", "noul", "A line this edit drops is a load-bearing duplicate exact/simp_all/apply."),
    ("local_one_line", "noul", "The edit changes exactly one tactic line."),
)
# From lake misses on the 260-token script (autoresearch round 2).
MISS_FEATURES = (
    (
        "opens_refine_2a",
        "noul",
        "This edit will leave case refine_2.a or refine_2.a.h unsolved.",
    ),
    (
        "semicolon_apply_longer",
        "noul",
        "This edit joins apply lines with <;> and will use more tokens, not fewer.",
    ),
    (
        "constructor_for_rfl_refine",
        "noul",
        "This edit replaces refine ⟨rfl, ?_, ?_⟩ with constructor and will fail updatedStatesInit.",
    ),
    (
        "drops_second_exact",
        "noul",
        "This edit deletes a second exact InitStatesNotDefined or InitStatesNodup that still has an open refine hole.",
    ),
)
ALL_FEATURES = SEED_FEATURES + MISS_FEATURES
PENALTY = {
    "drops_pca_glue",
    "drops_prefix_have",
    "breaks_refine",
    "duplicate_needed",
    "opens_refine_2a",
    "semicolon_apply_longer",
    "constructor_for_rfl_refine",
    "drops_second_exact",
}


def load_typesafe():
    from jevops.outer import after_calls, load_module_from_path

    module = after_calls(
        (lra_pca.load_keyfile, lra_pca.pin_typesafe_path),
        load_module_from_path,
        TS_PATH,
        "lra_typesafe_autoresearch",
    )
    if module is None or not module.typesafe_configured():
        return None
    return module


def feature_questions(module) -> dict:
    questions = {}
    for name, kind, question in ALL_FEATURES:
        if kind == "noul":
            questions[name] = module.Noul(instructions=question)
        else:
            questions[name] = module.Score(
                instructions=question,
                criteria=list(__import__("draft_fanout", fromlist=["LIKELY_SHORTER_CRITERIA"]).LIKELY_SHORTER_CRITERIA),
            )
    return questions


def featurize_proposal(
    record: Mapping[str, Any],
    current: str,
    proposal: Mapping[str, str],
    *,
    ledger: lra_t1.ProblemLedger,
    module,
    weights: Mapping[str, float],
) -> dict[str, Any]:
    from jevops.outer import tail_chars

    state = {
        "problem": record.get("name"),
        "current_tokens": lra_loop.token_count(current),
        "current_tail": tail_chars(current, 500),
        "edit_kind": proposal.get("kind"),
        "edit_note": proposal.get("note"),
        "proposed_tokens": lra_loop.token_count(proposal.get("tactics") or ""),
        "proposed_tail": tail_chars(proposal.get("tactics") or "", 500),
        "goal": "Judge this MCMC edit of a lake-valid Lean 4 proof. Do not write Lean.",
    }
    from jevops.jev import featurize_or_skip, invoke_system_one, skipped, unpack_response
    from jevops.outer import dumps_compact, exc_head, usage_tokens
    from jevops.rankers import signed_dot

    def _record(usage: Any) -> Any:
        inn, out = usage_tokens(
            usage, fallback_in=lra_t1.estimate_tokens(dumps_compact(state))
        )
        return ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)

    return featurize_or_skip(
        invoke_fn=lambda: invoke_system_one(
            module.TypeSafeClient(timeout=45.0), state, feature_questions(module)
        ),
        skip_fn=lambda exc: skipped(exc_head(exc), score=0.0, features={}),
        unpack_fn=unpack_response,
        record_fn=_record,
        feature_names=[name for name, _kind, _q in ALL_FEATURES],
        weights=weights,
        signed_dot_fn=signed_dot,
        penalty=PENALTY,
    )


def update_weights(rows: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, float]:
    """One autoresearch step: nudge weights from lake labels (ok vs fail)."""

    from jevops.rankers import update_feature_weights

    return update_feature_weights(
        rows,
        weights,
        features=[name for name, _kind, _q in ALL_FEATURES],
        penalty=PENALTY,
        lr=0.3,
        floor=0.05,
    )


def self_check() -> dict[str, Any]:
    names = [item[0] for item in ALL_FEATURES]
    return {
        "ok": "likely_compiles" in names
        and "opens_refine_2a" in names
        and "drops_second_exact" in names
        and len(ALL_FEATURES) >= 10,
        "n_features": len(ALL_FEATURES),
        "hardware_class": HARDWARE_CLASS,
        "called_docker0": False,
        "arena_score": None,
        "cookbook": "https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery",
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--init-file", type=Path, required=False)
    parser.add_argument("--names", default="Core.InitsUpdatesComm")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_check or not args.live:
        report = self_check()
        from jevops.outer import print_ok

        return print_ok(report)
    from jevops.outer import pin_env

    pin_env({"IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0"}, overwrite=False)
    module = load_typesafe()
    if module is None:
        from jevops.outer import print_json

        print_json({"ok": False, "reason": "no_typesafe", "arena_score": None})
        return 1
    _raw, digest, records = lra_splice.load_warmup_records()
    from jevops.outer import first_csv

    name = first_csv(args.names)
    from jevops.outer import lookup_named

    record = lookup_named(
        records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
    )
    from jevops.outer import read_text

    init = read_text(args.init_file) if args.init_file else None
    import draft_fanout as lra_fan

    reference = lra_fan.tactic_block(record)
    current = (init or reference).strip("\n")
    rng = random.Random(int(args.seed))
    ledger = lra_t1.ProblemLedger(name=f"{name}#autoresearch-mcmc", max_jev_calls=MAX_JEV, max_mistral_calls=0, max_grok_calls=0)
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), args.state_root)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if

    restore = read_bytes_if(dest)
    start = lra_mcmc.compile_one(record, current, state_root=args.state_root, timeout=args.timeout, restore=restore)
    best = {
        "kind": "init",
        "tactics": current,
        "token_count": int(start.get("token_count") or lra_loop.token_count(current)),
        "theorem_ok": bool(start.get("theorem_ok")),
    }
    weights = {name: 0.8 for name, _k, _q in ALL_FEATURES}
    weights.update(
        {
            "likely_compiles": 1.1,
            "likely_shorter": 0.15,
            "local_one_line": 0.2,
            "opens_refine_2a": 1.0,
            "semicolon_apply_longer": 1.0,
            "constructor_for_rfl_refine": 1.0,
            "drops_second_exact": 1.0,
        }
    )
    history: list[dict[str, Any]] = []
    labeled: list[dict[str, Any]] = []
    started = time.perf_counter()
    for round_i in range(int(args.rounds)):
        if ledger.hard_stopped:
            break
        proposals = lra_mcmc.propose_edits(current, reference, rng)
        scored = []
        from jevops.outer import head_seq

        for proposal in head_seq(proposals, 6):
            feat = featurize_proposal(record, current, proposal, ledger=ledger, module=module, weights=weights)
            scored.append({**proposal, **feat})
            if ledger.hard_stopped:
                break
        scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        current_tok = lra_loop.token_count(current)
        shorter = [
            item
            for item in scored
            if lra_loop.token_count(item.get("tactics") or "") < current_tok
        ]
        to_lake = head_seq(shorter or scored, 2)
        for proposal in to_lake:
            compiled = lra_mcmc.compile_one(
                record,
                proposal["tactics"],
                state_root=args.state_root,
                timeout=args.timeout,
                restore=restore,
            )
            ok = bool(compiled.get("theorem_ok"))
            tok = int(compiled.get("token_count") or lra_loop.token_count(proposal["tactics"]))
            row = {
                "round": round_i,
                "kind": proposal.get("kind"),
                "note": proposal.get("note"),
                "score": proposal.get("score"),
                "features": proposal.get("features"),
                "ok": ok,
                "tokens": tok,
                "errors": head_seq(compiled.get("errors"), 1),
            }
            history.append(row)
            labeled.append(row)
            if ok and tok < int(best["token_count"]):
                best = {"kind": f"ar_r{round_i}_{proposal.get('kind')}", "tactics": proposal["tactics"], "token_count": tok, "theorem_ok": True}
                current = proposal["tactics"]
        weights = update_weights(labeled, weights)
    from jevops.outer import elapsed_ms, utc_stamp, write_json_pair

    payload = {
        "schema": "lra-autoresearch-mcmc/v1",
        "observed_at": utc_stamp(),
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "cookbook": "https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery",
        "name": name,
        "warmup_jsonl_sha256": digest,
        "rounds": int(args.rounds),
        "features": [item[0] for item in ALL_FEATURES],
        "miss_features": [item[0] for item in MISS_FEATURES],
        "final_weights": weights,
        "best": {k: best[k] for k in ("kind", "token_count", "theorem_ok")},
        "best_tactics": best.get("tactics"),
        "history": history,
        "ledger": ledger.as_dict(),
        "reference_token_count": lra_loop.token_count(reference),
        "beats_reference": bool(best.get("theorem_ok") and int(best["token_count"]) < lra_loop.token_count(reference)),
        "hardware_class": HARDWARE_CLASS,
        "called_docker0": False,
        "official_track2": False,
        "arena_score": None,
        "jev_generated_lean": False,
        "wall_ms": elapsed_ms(started),
    }
    latest = write_json_pair(
        args.out,
        lra_pca.redact(payload),
        prefix="autoresearch-mcmc",
        latest="autoresearch-mcmc-latest.json",
        refuse="apikey_",
    )
    from jevops.outer import print_json

    print_json(
        {
            "ok": True,
            "latest": str(latest),
            "kept": {"kind": best.get("kind"), "token_count": best.get("token_count"), "theorem_ok": best.get("theorem_ok")},
            "beats_reference": payload["beats_reference"],
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
