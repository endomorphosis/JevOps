#!/usr/bin/env python3
"""SDE cascade + hierarchical Choice + confidence abstain for Lean MCMC edits.

Cookbooks:
  https://docs.typesafe.ai/cookbooks/sde_cascade
  https://docs.typesafe.ai/cookbooks/hierarchical_classification
  https://docs.typesafe.ai/cookbooks/classification_using_confidence

1. Hierarchical Choice: pick an edit *family*, then a leaf edit (beam K=2,
   geometric-mean path score).
2. Confidence: if the family Choice is below CONFIDENT, keep the current
   script (coarser answer = do nothing).
3. Cascade verify: per-edit Nouls with true=will-fail-lake; skip lake if any
   P(wrong) > FIRE_T. Lake is the expensive oracle.

Jev does not write Lean. Not Track 2. Not an Arena ranking.
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
PR_ID = "PR-9i"
CONFIDENT = 0.55
FIRE_T = 0.7
BEAM_K = 2
EPSILON = 1e-9
MAX_JEV = 20

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import inits_updates_shorten as lra_ius  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"
TS_PATH = _jevops_path.TYPESAFE_INFERENCE_PATH

FAMILY_TREE: dict[str, dict[str, str]] = lra_ius.family_tree()
FAMILY_TREE.setdefault("rewrite", {})["inits_replay"] = (
    "Apply the full Core.InitsUpdatesComm 268→139 kernel sequence (no LLM)."
)
FAMILY_TREE.setdefault("drop", {}).update(
    {
        "drop_duplicate": "Delete the last extra copy of a repeated exact/simp_all/apply.",
        "drop_and_intro": "Delete apply And.intro before refine updatedStatesInit.",
        "drop_nested_init_simp": "Delete the nested . simp_all under apply updatedStatesInit.",
        "drop_last_simp_all": "Delete the last bare simp_all that does no work.",
        "drop_orphan_intros_hin": "Delete an intros Hin that no later tactic uses.",
        "drop_orphan_hnd": "Delete have Hnd when specialize Hnd is gone.",
        "drop_isnotdefined_simp": "Delete the isNotDefined/isDefined simp at * after Hnd.",
    }
)
FAMILY_TREE.setdefault("join", {}).update(
    {
        "join_applies": "Join consecutive same-indent apply lines with <;> (often longer).",
        "join_exacts": "Join consecutive exact lines with <;>.",
    }
)

FAIL_NOULS = {
    "will_unsolve_refine": (
        "Will this edit leave a refine ⟨rfl, ?_, ?_⟩ subgoal unsolved (refine_2.a / refine_1.a)?",
        "the edit will leave a refine hole unsolved",
        "the refine holes will still close",
    ),
    "will_unify_fail": (
        "Will Lean fail to unify updatedStatesInit or UpdateStateNotDefMonotone' after this edit?",
        "unify will fail",
        "unify will succeed",
    ),
    "will_simp_no_progress": (
        "Will Lean report simp_all made no progress after this edit?",
        "simp_all will make no progress",
        "simp_all will still close or rewrite",
    ),
    "will_invalid_ih_projection": (
        "Will rewriting apply (ih Hinit ?_ ?_).2.2 drop the extra arguments and become an invalid projection on a function?",
        "the ih projection will be invalid",
        "the ih apply will still type-check",
    ),
    "will_and_intro_type_mismatch": (
        "Will deleting apply And.intro make updatedStatesInit have type InitStates when Lean expected an And?",
        "the And.intro drop will cause a type mismatch",
        "the goal still accepts a single InitStates proof",
    ),
}

import mcmc_beam as lra_mcmc  # noqa: E402
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402


def load_typesafe():
    from jevops.outer import after_calls, load_configured

    return after_calls(
        (lra_pca.load_keyfile, lra_pca.pin_typesafe_path),
        load_configured,
        TS_PATH,
        "lra_typesafe_cascade",
    )


def geo_mean(probs: list[float]) -> float:
    from jevops.pick import geo_mean as _fn

    return _fn(probs, epsilon=EPSILON)


def make_client(module):
    from jevops.outer import client_kwargs

    return module.TypeSafeClient(**client_kwargs(module))


def _record_jev(ledger: lra_t1.ProblemLedger, result: Any, fallback: int = 200) -> None:
    from jevops.outer import result_usage

    inn, out = result_usage(result, fallback_in=fallback)
    ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)


def is_unavailable(exc: BaseException) -> bool:
    from jevops.outer import is_unavailable as _fn

    return _fn(exc)


def call_with_retry(fn, *, attempts: int = 4):
    from jevops.outer import retry_call

    return retry_call(fn, attempts=attempts)


def available_tactics(current: str, reference: str, rng: random.Random) -> dict[str, str]:
    from jevops.outer import unique_kind_bodies

    return unique_kind_bodies(
        lra_mcmc.propose_edits(current, reference, rng, limit=None),
        keep={"keep": current},
        skip_eq=current,
    )


def load_failed_kinds(path: Path) -> set[str]:
    from jevops.outer import failed_leaves_from_history
    from jevops.outer import load_json_object

    return failed_leaves_from_history(load_json_object(path))


def live_tree(available: Mapping[str, str]) -> dict[str, dict[str, str]]:
    from jevops.pick import live_tree as _fn

    return _fn(FAMILY_TREE, available)


def classify_tree(
    module,
    state: Mapping[str, Any],
    tree: Mapping[str, Mapping[str, str]],
    *,
    ledger: lra_t1.ProblemLedger,
) -> dict[str, Any]:
    """One System One call: family Choice plus a leaf Choice per sibling set.

    Hierarchical cookbook: path_score = geo_mean of edge probabilities, beam K,
    separation = top / second. Confidence cookbook: if family confidence is
    below CONFIDENT, report the coarser parent (keep / do nothing).
    """
    from jevops.jev import tree_choice_questions

    questions = tree_choice_questions(
        tree,
        Choice=module.Choice,
        family_instructions=(
            "Which edit family is the best next step to shorten this lake-valid "
            "Lean 4 proof without breaking compile? Do not write Lean."
        ),
    )
    from jevops.jev import invoke_system_one

    result = call_with_retry(lambda: invoke_system_one(make_client(module), state, questions)[0])
    _record_jev(ledger, result)
    from jevops.pick import classification_from_answers

    return classification_from_answers(
        tree,
        getattr(result, "choices", None) or {},
        beam_k=BEAM_K,
        confident=CONFIDENT,
        epsilon=EPSILON,
    )


def verify_fail(module, state: Mapping[str, Any], *, ledger: lra_t1.ProblemLedger) -> dict[str, float]:
    from jevops.jev import noul_questions

    questions = noul_questions(FAIL_NOULS, module.Noul)
    from jevops.outer import attr_map

    from jevops.jev import invoke_system_one

    result = call_with_retry(lambda: invoke_system_one(make_client(module), state, questions)[0])
    _record_jev(ledger, result)
    return attr_map(getattr(result, "nouls", None) or {}, FAIL_NOULS, "noul")


def self_check() -> dict[str, Any]:
    dummy = live_tree({"keep": "x", "drop_duplicate": "y", "join_applies": "z"})
    return {
        "ok": (
            abs(geo_mean([0.81, 0.81]) - 0.81) < 1e-9
            and "keep" in FAMILY_TREE
            and "drop" in dummy
            and "join" in dummy
            and CONFIDENT > 0
            and FIRE_T == 0.7
            and BEAM_K == 2
        ),
        "families": list(FAMILY_TREE),
        "confident": CONFIDENT,
        "fire_t": FIRE_T,
        "beam_k": BEAM_K,
        "hardware_class": HARDWARE_CLASS,
        "called_docker0": False,
        "arena_score": None,
        "cookbooks": [
            "https://docs.typesafe.ai/cookbooks/sde_cascade",
            "https://docs.typesafe.ai/cookbooks/hierarchical_classification",
            "https://docs.typesafe.ai/cookbooks/classification_using_confidence",
        ],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--seed", type=int, default=9)
    parser.add_argument("--init-file", type=Path)
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
    import draft_fanout as lra_fan

    reference = lra_fan.tactic_block(record)
    from jevops.outer import read_text

    current = read_text(args.init_file).strip("\n") if args.init_file else reference
    rng = random.Random(int(args.seed))
    ledger = lra_t1.ProblemLedger(name=f"{name}#cascade", max_jev_calls=MAX_JEV, max_mistral_calls=0, max_grok_calls=0)
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
    history: list[dict[str, Any]] = []
    failed_kinds: set[str] = load_failed_kinds(args.out / "cascade-edits-latest.json")
    started = time.perf_counter()
    for round_i in range(int(args.rounds)):
        if ledger.hard_stopped:
            break
        found = available_tactics(current, reference, rng)
        for kind in list(found):
            if kind in failed_kinds and kind != "keep":
                found.pop(kind, None)
        tree = live_tree(found)
        from jevops.outer import exc_head, head_seq, tail_chars

        state = {
            "problem": name,
            "current_tokens": best["token_count"],
            "current_tail": tail_chars(current, 400),
            "available_leaves": sorted(k for k in found if k != "keep"),
            "failed_kinds": sorted(failed_kinds),
            "goal": "Shorten a lake-valid Lean 4 proof without breaking compile. Do not write Lean.",
        }
        try:
            classified = classify_tree(module, state, tree, ledger=ledger)
        except Exception as exc:  # noqa: BLE001
            history.append({"round": round_i, "action": "typesafe_error", "error": exc_head(exc)})
            if is_unavailable(exc):
                time.sleep(5.0)
                continue
            break
        row: dict[str, Any] = {
            "round": round_i,
            "abstain": classified["abstain"],
            "separation": classified["separation"],
            "paths": head_seq(classified["paths"], 6),
            "family": classified["family"],
            "beam_fams": classified["beam_fams"],
        }
        if classified["abstain"]:
            row["action"] = "abstain_keep"
            history.append(row)
            continue
        # Hierarchical beam names one winning leaf. SDE cascade then verifies
        # that extract and escalates to lake at most once per round.
        # If the family is confident but no leaf is, greedy-pick the family's
        # top child (hierarchical greedy under a trusted parent).
        winning_fam = str(classified["family"].get("choice") or "")
        if winning_fam not in tree:
            winning_fam = str((classified.get("beam_fams") or ["keep"])[0])
        greedy_leaf = None
        if winning_fam and winning_fam != "keep":
            fam_paths = [p for p in classified["paths"] if p.get("family") == winning_fam]
            if fam_paths:
                greedy_leaf = str(fam_paths[0].get("leaf") or "")
        tried = False
        for top in classified["paths"]:
            leaf = str(top["leaf"])
            if leaf == "keep" or top["family"] == "keep" or leaf in failed_kinds:
                continue
            body = found.get(leaf)
            if not body or body.strip("\n") == current.strip("\n"):
                continue
            tok = lra_loop.token_count(body)
            leaf_conf = float(top.get("leaf_confidence") or 0.0)
            family_conf = float(classified["family"].get("confidence") or 0.0)
            confident_leaf = leaf_conf >= CONFIDENT
            greedy_ok = (not confident_leaf) and family_conf >= CONFIDENT and leaf == greedy_leaf
            if not confident_leaf and not greedy_ok:
                continue
            row["picked"] = top
            row["proposed_tokens"] = tok
            row["greedy_family"] = greedy_ok
            if tok >= int(best["token_count"]):
                failed_kinds.add(leaf)
                continue
            vstate = {
                **state,
                "edit_kind": leaf,
                "proposed_tokens": tok,
                "proposed_tail": tail_chars(body, 400),
            }
            try:
                flags = verify_fail(module, vstate, ledger=ledger)
            except Exception as exc:  # noqa: BLE001
                row["action"] = "verify_error"
                row["error"] = exc_head(exc)
                history.append(row)
                tried = True
                break
            fired = {k: p for k, p in flags.items() if p > FIRE_T}
            row["verify"] = flags
            row["fired"] = fired
            if fired:
                row["action"] = "skip_lake"
                failed_kinds.add(leaf)
                history.append(row)
                tried = True
                break
            compiled = lra_mcmc.compile_one(
                record, body, state_root=args.state_root, timeout=args.timeout, restore=restore
            )
            ok = bool(compiled.get("theorem_ok"))
            lake_tok = int(compiled.get("token_count") or tok)
            row["action"] = "lake"
            row["ok"] = ok
            row["tokens"] = lake_tok
            row["errors"] = head_seq(compiled.get("errors"), 1)
            history.append(row)
            tried = True
            if ok and lake_tok < int(best["token_count"]):
                best = {
                    "kind": f"cascade_r{round_i}_{leaf}",
                    "tactics": body,
                    "token_count": lake_tok,
                    "theorem_ok": True,
                }
                current = body
            else:
                failed_kinds.add(leaf)
            break
        if not tried:
            row["action"] = "abstain_family"
            history.append(row)
    from jevops.outer import elapsed_ms, utc_stamp, write_json_pair

    payload = {
        "schema": "lra-cascade-edits/v1",
        "observed_at": utc_stamp(),
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "cookbooks": [
            "https://docs.typesafe.ai/cookbooks/sde_cascade",
            "https://docs.typesafe.ai/cookbooks/hierarchical_classification",
            "https://docs.typesafe.ai/cookbooks/classification_using_confidence",
        ],
        "name": name,
        "warmup_jsonl_sha256": digest,
        "confident": CONFIDENT,
        "fire_t": FIRE_T,
        "beam_k": BEAM_K,
        "failed_kinds": sorted(failed_kinds),
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
        prefix="cascade-edits",
        latest="cascade-edits-latest.json",
        refuse="apikey_",
    )
    from jevops.outer import print_json

    print_json(
        {
            "ok": True,
            "latest": str(latest),
            "kept": payload["best"],
            "beats_reference": payload["beats_reference"],
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
