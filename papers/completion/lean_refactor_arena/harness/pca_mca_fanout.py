#!/usr/bin/env python3
"""PCA/MCA-guided TypeSafe fan-out of AST refactor drafts.

Principal components = dominant proof style (keep). Minor components =
residual/idiosyncratic variance (candidates for simplification). Those
directions are labeled as classical compiler families:

- dead_code: unused have/obtain/rename_i, simp-at before simp_all
- search_space: extra search tactics; never drop case arms
- loop_invariant: have-facts after induction
- strength_reduction: simp-at runs → simp_all
- algebraic_simplification: rw/calc/ring/omega chains → simp/omega

TypeSafe ranks the drafts. Lake is the oracle. Jev does not write Lean.
Not official Track 2. Not an Arena ranking. Never LOCK_EX.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
LAKE_READY = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
    "Core.InitsUpdatesComm",
    "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress",
    "Cslib.SKI.parallelReduction_diamond",
    "Cslib.CCS.bisimilarity_congr_choice",
    "putnam_1964_a4",
    "putnam_1964_b2",
    "putnam_1995_a3",
    "fundamental_theorem_of_variational_calculus'",
    "Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema",
    "FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time",
    "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius",
    "Binius.BinaryBasefold.fold_advances_evaluation_poly",
    "interleaved_affine_gaps_imply_tensor_gaps",
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import draft_fanout as lra_fan  # noqa: E402
import run_warmup as lra_loop  # noqa: E402

ROOT_ACCEL = _jevops_path.IPFS_ACCELERATE_ROOT
KEYFILE = _jevops_path.TYPESAFE_KEYFILE
import splice as lra_splice  # noqa: E402

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256
PROTOCOL = "LRA/v1"
PR_ID = "PR-9c"
from jevops.tactics import FAMILY_FEATURES
from jevops.tactics import FEATURE_NAMES
from jevops.tactics import HAVE as _HAVE
from jevops.tactics import RENAME as _RENAME
from jevops.tactics import RW_BRACKET as _RW_BRACKET
FORBIDDEN_IMPORT_NAMES = frozenset({"fcntl", "generate_text", "typesafe_sdk"})


from jevops.tactics import FeatureRow


def load_keyfile() -> None:
    from jevops.outer import load_env_file

    load_env_file(KEYFILE)


def pin_typesafe_path() -> None:
    from jevops.outer import pin_sys_path

    pin_sys_path(
        ROOT_ACCEL,
        defaults={
            "IPFS_ACCEL_SKIP_CORE": "1",
            "IPFS_AUTO_INSTALL": "false",
            "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0",
        },
    )
    lra_fan.pin_typesafe_path()
    lra_fan.ACCEL_ROOT = ROOT_ACCEL
    lra_fan.TYPESAFE_INFERENCE_PATH = _jevops_path.TYPESAFE_INFERENCE_PATH


def count_tactics(tactics: str) -> dict[str, float]:
    from jevops.tactics import count_tactics as _fn

    return _fn(tactics, token_fn=lra_loop.token_count)


def feature_row(record: Mapping[str, Any]) -> FeatureRow:
    from jevops.tactics import feature_row as _fn

    return _fn(
        record,
        tactics=lra_fan.tactic_block(record),
        feature_names=FEATURE_NAMES,
        token_fn=lra_loop.token_count,
    )


def fit_pca_mca(rows: Sequence[FeatureRow], *, n_principal: int = 3, n_minor: int = 3) -> dict[str, Any]:
    from jevops.rankers import zscore_svd

    return zscore_svd(
        [row.vector for row in rows],
        n_principal=n_principal,
        n_minor=n_minor,
        feature_names=FEATURE_NAMES,
    )


def amenable_families(counts: Mapping[str, float], model: Mapping[str, Any], *, top_k: int = 5) -> list[dict[str, Any]]:
    """Features that load on minor components *and* are present in this proof."""

    from jevops.rankers import rank_present_families
    from jevops.rankers import residual_feature_scores

    scores = residual_feature_scores(
        counts,
        model["mean"],
        model["std"],
        model["minor"],
        FEATURE_NAMES,
    )
    return rank_present_families(counts, scores, FAMILY_FEATURES, top_k=top_k)


def drop_rename_i(text: str) -> str:
    """Drop rename_i lines whose binders are not referenced later."""

    from jevops.tactics import drop_rename_i as _fn

    return _fn(text)


def drop_have_after_induction(text: str) -> str:
    from jevops.tactics import drop_have_after_induction as _fn

    return _fn(text)


def collapse_rw_to_simp(text: str) -> str:
    """Strength-reduce consecutive ``rw [lemmas]`` into one ``simp [lemmas]``."""

    from jevops.tactics import collapse_rw_to_simp as _fn

    return _fn(text)


def keep_calc_only(text: str) -> str:
    from jevops.tactics import keep_calc_only as _fn

    return _fn(text)


def guided_drafts(
    tactics: str,
    families: Sequence[Mapping[str, Any]],
    counts: Optional[Mapping[str, float]] = None,
) -> list[lra_fan.Draft]:
    import inits_updates_shorten as lra_ius
    import portable_rewrites as lra_port
    import symbol_diffuse as lra_sym

    portable = [
        (
            str(item.get("family") or "search_space"),
            str(item["tactics"]),
            ("portable", str(item.get("kind") or "")),
        )
        for item in lra_port.portable_drafts(tactics)
    ]
    from jevops.tactics import collect_guided_drafts

    return collect_guided_drafts(
        tactics,
        families,
        counts,
        extras=(portable, lra_ius.pca_mca_ops(tactics), lra_sym.pca_mca_ops(tactics)),
        push_fn=lra_fan._push,
    )


def fanout_state(
    record: Mapping[str, Any],
    *,
    features: Mapping[str, float],
    families: Sequence[Mapping[str, Any]],
    drafts: Sequence[lra_fan.Draft],
    pca: Mapping[str, Any],
) -> dict[str, Any]:
    from jevops.jev import fanout_problem_state
    from jevops.outer import head_seq

    return fanout_problem_state(
        record,
        statement_n=480,
        extra={
            "ast_features": dict(features),
            "pca_principal": head_seq(pca["principal"], 2),
            "mca_minor": pca["minor"],
            "amenable": list(families),
            "drafts": lra_fan.draft_catalog(drafts),
            "compiler_families": list(FAMILY_FEATURES),
        },
    )


def fanout_questions(drafts: Sequence[lra_fan.Draft], *, Choice: Any, Noul: Any, Score: Any) -> dict[str, Any]:
    from jevops.jev import choice_questions, draft_criteria

    family_criteria = {
        "dead_code": "Drop unused have/obtain/rename_i or simp-at-before-simp_all",
        "search_space": "Shrink intros/apply search; never delete a case arm",
        "loop_invariant": "Drop have-facts after induction",
        "strength_reduction": "Replace simp-at runs with simp_all",
        "algebraic_simplification": "Collapse rw/calc/ring/omega into simp or omega",
        "pca_keep": "Keep the reference; PCA says it is already the dominant style",
        "inits_replay": (
            "Apply the closed Core.InitsUpdatesComm 268→139 kernel sequence. "
            "No LLM. Lake is the oracle."
        ),
        "drop": "Drop a residual binder, named arg, or unused intro",
        "rewrite": "Apply one InitsUpdatesComm shorten kernel (MCA residual)",
        "symbol_diffuse": (
            "Fill a masked Lean operator/symbol from the closed language "
            "($, constructor, intro, all_goals, .update_some) or Leanstral"
        ),
    }
    return choice_questions(
        Choice=Choice,
        Noul=Noul,
        Score=Score,
        criteria=draft_criteria(drafts),
        best_instructions=(
            "Which draft id should lake-compile first as a refactor of the reference? "
            "Prefer MCA-guided dead_code, strength_reduction, or algebraic_simplification "
            "if they preserve every case arm. Do not write Lean."
        ),
        nouls={
            "dead_code_safe": (
                "Is dropping have/obtain/rename_i/simp-at-before-simp_all likely to preserve meaning?"
            ),
            "strength_reduction_safe": "Is replacing simp-at runs with simp_all likely to compile?",
            "loop_invariant_safe": (
                "Are have-facts after induction redundant loop invariants that can be dropped?"
            ),
            "search_space_safe": "Can intros/search tactics shrink without deleting a case arm?",
            "algebraic_simplification_safe": (
                "Can rw/calc/ring/omega chains be replaced by simp or omega without changing the theorem?"
            ),
        },
        scores={
            "likely_token_cut": (
                "How large a source-token cut is plausible if the best MCA draft replaces the reference?",
                list(lra_fan.LIKELY_SHORTER_CRITERIA),
            )
        },
        extra={
            "best_compiler_family": Choice(
                instructions=(
                    "Which compiler family should lake try first on this AST given PCA/MCA? "
                    "Do not write Lean."
                ),
                criteria=family_criteria,
            )
        },
    )


def redact(payload: Any) -> Any:
    return lra_fan.redact(payload)


def rank_problem(
    record: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    model: Mapping[str, Any],
    *,
    live: bool,
) -> dict[str, Any]:
    tactics = lra_fan.tactic_block(record)
    features = count_tactics(tactics)
    families = amenable_families(features, model)
    drafts = guided_drafts(tactics, families, features)
    state = fanout_state(record, features=features, families=families, drafts=drafts, pca=model)
    from jevops.jev import invoke_system_one, project_live_answers, rank_catalog_or_live

    def _project(result: Any, wall_ms: float) -> dict[str, Any]:
        live_row = project_live_answers(
            result,
            choice_map={"best_compiler_family": "best_compiler_family", "best_first_draft": "best_first_draft"},
            noul_map={
                "dead_code_safe": "dead_code_safe",
                "strength_reduction_safe": "strength_reduction_safe",
                "loop_invariant_safe": "loop_invariant_safe",
                "search_space_safe": "search_space_safe",
                "algebraic_simplification_safe": "algebraic_simplification_safe",
            },
            score_map={"likely_token_cut": "likely_token_cut"},
        )
        best = live_row.pop("_best", None)
        probabilities = dict(getattr(best, "probabilities", None) or {})
        live_row["wall_ms"] = wall_ms
        live_row["top"] = lra_fan.rank_choice(probabilities, drafts)
        return live_row

    def _invoke() -> tuple[Any, float]:
        from _optional_deps import require_typesafe

        typesafe_module = require_typesafe()
        Choice = typesafe_module.Choice
        Noul = typesafe_module.Noul
        Score = typesafe_module.Score
        TypeSafeClient = typesafe_module.TypeSafeClient

        return invoke_system_one(
            TypeSafeClient(timeout=60.0),
            state,
            fanout_questions(drafts, Choice=Choice, Noul=Noul, Score=Score),
        )

    def _configured() -> bool:
        from _optional_deps import load_typesafe

        typesafe_module, _reason = load_typesafe()
        return bool(typesafe_module and typesafe_module.typesafe_configured())

    return rank_catalog_or_live(
        record,
        drafts=drafts,
        families=families,
        features=features,
        live=live,
        extra={"catalog": lra_fan.draft_catalog(drafts)} if not live else None,
        catalog_fn=lambda: lra_fan.draft_catalog(drafts),
        pin_fn=pin_typesafe_path,
        configured_fn=_configured,
        invoke_fn=_invoke,
        project_fn=_project,
        redact_fn=redact,
    )


def audit_source() -> dict[str, Any]:
    from jevops.outer import read_text
    from jevops.repair import audit_source as _audit

    text = read_text(__file__)
    out = _audit(text, forbidden_imports=FORBIDDEN_IMPORT_NAMES)
    imported = set(out["imported_names"])
    return {
        "forbidden_imports": out["forbidden_imports"],
        "uses_lock_ex": out["uses_lock_ex"],
        "ok": not out["uses_lock_ex"] and "generate_text" not in imported,
    }


def self_check() -> dict[str, Any]:
    from jevops.outer import lookup_named, without_keys

    _raw, digest, records = lra_splice.load_warmup_records()
    rows = [feature_row(record) for record in records]
    model = fit_pca_mca(rows)
    audit = audit_source()
    sample = lookup_named(
        records, LAKE_READY[0], error_cls=RuntimeError, miss=f"unknown warm-up problem: {LAKE_READY[0]}"
    )
    public_model = without_keys(model, ("zscore", "vt"))
    ranked = rank_problem(sample, records, public_model, live=False)
    ok = (
        audit["ok"]
        and digest == FROZEN_WARMUP_SHA256
        and len(rows) == 15
        and ranked["n_drafts"] >= 2
        and "dead_code" in FAMILY_FEATURES
        and "strength_reduction" in FAMILY_FEATURES
        and "algebraic_simplification" in FAMILY_FEATURES
    )
    return {
        "ok": ok,
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "warmup_jsonl_sha256": digest,
        "audit": audit,
        "pca": public_model,
        "sample": ranked,
        "jev_generated_lean": False,
        "arena_score": None,
    }


def live_rank(names: Sequence[str]) -> dict[str, Any]:
    load_keyfile()
    pin_typesafe_path()
    _raw, digest, records = lra_splice.load_warmup_records()
    rows = [feature_row(record) for record in records]
    model = fit_pca_mca(rows)
    from jevops.outer import without_keys

    public_model = without_keys(model, ("zscore", "vt"))
    started = time.perf_counter()
    canaries = []
    from jevops.outer import elapsed_ms, lookup_named, utc_stamp

    for name in names:
        record = lookup_named(records, name)
        if record is None:
            canaries.append({"name": name, "error": "unknown warm-up problem", "arena_score": None})
            continue
        canaries.append(rank_problem(record, records, public_model, live=True))
    return redact(
        {
            "schema": "lra-pca-mca-fanout/v1",
            "observed_at": utc_stamp(),
            "protocol": PROTOCOL,
            "pr": PR_ID,
            "warmup_jsonl_sha256": digest,
            "pca": public_model,
            "jev_generated_lean": False,
            "typesafe_key_in_receipt": False,
            "lock_ex": False,
            "official_track2": False,
            "arena_score": None,
            "wall_ms": elapsed_ms(started),
            "canaries": canaries,
        }
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--lake", action="store_true", help="lake-compile TypeSafe top drafts on baked clones")
    parser.add_argument("--names", default=",".join(LAKE_READY))
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--state-root", type=Path, default=_jevops_path.LRA_STATE_ROOT / "track1-lake")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_check or not args.live:
        report = self_check()
        from jevops.outer import print_ok

        return print_ok(report)
    from jevops.outer import head_seq, lookup_named, split_csv

    names = split_csv(args.names)
    report = live_rank(names)
    if args.lake:
        import track1_keepbest as lra_kb

        _raw, _digest, records = lra_splice.load_warmup_records()
        for row in report.get("canaries") or []:
            if not row.get("live") or row.get("name") not in LAKE_READY:
                continue
            record = lookup_named(
                records,
                row["name"],
                error_cls=RuntimeError,
                miss=f"unknown warm-up problem: {row['name']}",
            )
            tactics = lra_fan.tactic_block(record)
            if str(record.get("source") or "") == "putnambench":
                restore = b""
            else:
                clone = lra_kb.lra_cw.clone_dir(str(record["url"]), args.state_root)
                dest = clone / lra_kb.lra_cw.source_relpath(record)
                if not dest.is_file():
                    row["lake"] = {"error": "missing_clone_file"}
                    continue
                restore = dest.read_bytes()
            catalog = {item["id"]: item for item in (row.get("catalog") or [])}
            # Reconstruct tactics for top picks from guided_drafts.
            families = row.get("amenable") or []
            drafts = guided_drafts(tactics, families, row.get("features") or {})
            by_id = {item.draft_id: item for item in drafts}
            family_pick = row.get("best_compiler_family")
            picks = [row.get("best_first_draft")] + [item.get("id") for item in head_seq(row.get("top"), 3)]
            for draft in drafts:
                if "inits_replay" in draft.ops or draft.family == "inits_replay":
                    picks.insert(0, draft.draft_id)
                if draft.family in {
                    "algebraic_simplification",
                    "strength_reduction",
                    "pca_keep",
                    "reference",
                    "inits_replay",
                    "rewrite",
                    "drop",
                    "symbol_diffuse",
                }:
                    picks.append(draft.draft_id)
                if family_pick and draft.family == family_pick:
                    picks.append(draft.draft_id)
            seen: set[str] = set()
            lake_rows = []
            for draft_id in picks:
                if len(seen) >= 8:
                    break
                if not draft_id or draft_id in seen or draft_id not in by_id:
                    continue
                seen.add(draft_id)
                draft = by_id[draft_id]
                compiled = lra_kb.compile_tactics(
                    record,
                    draft.tactics,
                    state_root=args.state_root,
                    timeout=180.0,
                    restore=restore,
                )
                lake_rows.append(
                    {
                        "id": draft_id,
                        "family": draft.family,
                        "ops": list(draft.ops),
                        "token_count": compiled.get("token_count"),
                        "theorem_ok": compiled.get("theorem_ok"),
                        "exit_code": compiled.get("exit_code"),
                        "errors": compiled.get("errors"),
                    }
                )
            row["lake"] = {"candidates": lake_rows, "arena_score": None}
            del catalog
    from jevops.outer import write_json_pair

    latest = write_json_pair(
        args.out,
        report,
        prefix="pca-mca-fanout",
        latest="pca-mca-fanout-latest.json",
        refuse="apikey_",
    )
    from jevops.outer import print_json

    print_json(
        {
            "ok": all(row.get("live") for row in report.get("canaries") or []),
            "latest": str(latest),
            "picks": [
                {
                    "name": row.get("name"),
                    "best": row.get("best_first_draft"),
                    "families": row.get("families"),
                    "n_drafts": row.get("n_drafts"),
                }
                for row in report.get("canaries") or []
            ],
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
