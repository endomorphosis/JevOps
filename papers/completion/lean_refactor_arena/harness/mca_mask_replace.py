#!/usr/bin/env python3
"""Mask MCA residual spans, keep the PCA skeleton, fill holes, lake-check.

Principal structure (induction, ``case`` arms, closing exact/constructor) stays.
Minor residuals (simp-at runs, have/rename_i, rw chains) become holes.

Fills:
- deterministic compiler templates (dead_code / strength_reduction / algebraic)
- one hosted Labs Leanstral pass over the masked skeleton
- optional Track 1 grok-4.6 few-shot + one lake-error repair (max 2 grok calls)

TypeSafe ranks the reassembled candidates. Lake is the oracle.
Never docker0. Never LOCK_EX. Not official Track 2. Not an Arena ranking.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass

from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

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
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402
import track1_mistral_leanstral as lra_mistral  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"

PROTOCOL = "LRA/v1"
PR_ID = "PR-9d"
HARDWARE_CLASS = "mistral_labs_api"
GROK_HARDWARE_CLASS = "grok_cli"
GROK_MAX_NEW_TOKENS = 900
GROK_TIMEOUT_SECONDS = 300.0
_SIMP_AT = lra_fan._SIMP_AT
_RW = lra_pca._RW_BRACKET
_RENAME = lra_pca._RENAME
_HAVE = lra_pca._HAVE
from jevops.tactics import Hole
from jevops.tactics import MCA_HOLE as _HOLE
from jevops.tactics import SKELETON_PREFIXES
from jevops.tactics import apply_fills as _apply_fills
from jevops.tactics import find_holes as _find_holes
from jevops.tactics import hole_row as _as_row
from jevops.tactics import mask_mca
from jevops.tactics import mca_marker as _mca_marker
from jevops.tactics import template_fill as _template_fill


def find_holes(tactics: str) -> list[Hole]:
    """Residual MCA spans: simp-at runs, rw runs, rename_i, have."""

    return _find_holes(tactics)


def mask_skeleton(tactics: str, holes: Sequence[Hole]) -> str:
    """Replace MCA spans with hole markers. PCA skeleton (case/induction) stays."""

    return mask_mca(tactics, holes)


def template_fill(hole: Hole) -> str:
    return _template_fill(hole)


def apply_fills(tactics: str, holes: Sequence[Hole], fills: Mapping[str, str]) -> str:
    return _apply_fills(tactics, holes, fills)


def parse_leanstral_fills(text: str, holes: Sequence[Hole]) -> dict[str, str]:
    """Accept either per-hole blocks or a full tactic block."""

    from jevops.mask import parse_marked_fills

    return parse_marked_fills(
        text,
        holes,
        attr="family",
        fallback_fn=lra_loop.extract_generated_tactics,
    )


def leanstral_prompt(record: Mapping[str, Any], skeleton: str, holes: Sequence[Hole]) -> str:
    from jevops.tactics import mca_hole_prompt as _fn

    return _fn(record, skeleton, holes)


def one_hole_prompt(record: Mapping[str, Any], tactics: str, hole: Hole) -> str:
    from jevops.tactics import mca_one_hole_prompt as _fn

    return _fn(record, tactics, hole)


SHOT_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    "CallElimCorrect.extractedOldExprInVars",
)


def few_shot_example(record: Mapping[str, Any]) -> dict[str, Any]:
    tactics = lra_fan.tactic_block(record)
    holes = find_holes(tactics)
    fills = {hole.hole_id: template_fill(hole) for hole in holes}
    filled = apply_fills(tactics, holes, fills)
    from jevops.pick import shot_stats

    return shot_stats(
        record.get("name"),
        tactics,
        filled,
        token_fn=lra_loop.token_count,
        extra={
            "n_holes": len(holes),
            "families": [hole.family for hole in holes],
            "skeleton": mask_skeleton(tactics, holes),
            "reference": tactics,
            "filled": filled,
        },
    )


def few_shot_prompt(target: Mapping[str, Any], shots: Sequence[Mapping[str, Any]]) -> str:
    from jevops.tactics import few_shot_prompt as _fn

    tactics = lra_fan.tactic_block(target)
    holes = find_holes(tactics)
    skeleton = mask_skeleton(tactics, holes)
    return _fn(
        target,
        shots,
        tactics=tactics,
        skeleton=skeleton,
        token_count=lra_loop.token_count(tactics),
    )


def shot_examples(records: Sequence[Mapping[str, Any]], *, skip_name: str) -> list[dict[str, Any]]:
    from jevops.outer import lookup_named

    shots: list[dict[str, Any]] = []
    for shot_name in SHOT_NAMES:
        if shot_name == skip_name:
            continue
        shot_rec = lookup_named(records, shot_name)
        if shot_rec is not None:
            shots.append(few_shot_example(shot_rec))
    return shots


def _kind_needs_hammer(kind: str) -> bool:
    from jevops.mask import starts_any

    return starts_any(kind, ("leanstral", "grok", "mca_leanstral", "tactician", "hybrid", "pca_"))


def _identity_dict(identity: Any) -> Optional[dict[str, Any]]:
    from jevops.outer import object_fields

    if isinstance(identity, Mapping):
        return dict(identity)
    row = object_fields(
        identity,
        (
            "requested_provider",
            "requested_model",
            "resolved_provider",
            "resolved_model",
            "fallback_used",
        ),
        extra={"arena_score": None},
    )
    if row and "fallback_used" in row:
        row["fallback_used"] = bool(row["fallback_used"])
    return row


def _flatten_tactics(reference: str, text: str) -> str:
    return lra_kb.flatten_overindent(
        reference, lra_kb.match_reference_indent(reference, lra_loop.extract_generated_tactics(text))
    )


def _compile_row(item: Mapping[str, Any], compiled: Mapping[str, Any]) -> dict[str, Any]:
    from jevops.search import compile_head_row

    return compile_head_row(
        str(item["kind"]),
        str(item.get("tactics") or ""),
        compiled,
        extra={
            "generator": item.get("generator"),
            "n_holes": len(item.get("holes") or []),
        },
    )


def _hammer_passes(
    *,
    kind: str,
    tactics_now: str,
    reference: str,
    errors: Sequence[Mapping[str, Any]],
    record: Mapping[str, Any],
    state_root: Path,
    timeout: float,
    restore: bytes,
    generator: str,
) -> tuple[list[dict[str, Any]], str, list[Any], bool]:
    from jevops.tactics import hammer_until

    def _compile(body: str) -> Mapping[str, Any]:
        return lra_kb.compile_tactics(
            record, body, state_root=state_root, timeout=timeout, restore=restore
        )

    def _row(*, kind: str, generator: str, tactics: str, compiled: Mapping[str, Any]) -> Mapping[str, Any]:
        return _compile_row(
            {"kind": kind, "generator": generator, "tactics": tactics, "holes": []},
            compiled,
        )

    return hammer_until(
        tactics_now,
        reference,
        errors,
        _compile,
        _row,
        kind=kind,
        generator=generator,
    )


# Cslib scripts use ``grind`` / ``grind only [→ wf]``. Never rewrite grind
# unless the lake error is specifically "unknown tactic grind" (Strata).
from jevops.tactics import UNKNOWN_TACTICS as _UNKNOWN_TACTICS


def hammer_repair(draft: str, reference: str, errors: Sequence[Mapping[str, Any]]) -> str:
    """Local tactician: restore PCA glue, drop illegal tactics, then simp_all/omega.

    Strata/CSLib lake projects do not depend on Aesop. Portable closers are
    ``simp_all`` and ``omega``. Aesop is only safe on Putnam's Mathlib+Aesop lake.
    """

    from jevops.tactics import hammer_repair as _fn

    return _fn(draft, reference, errors)


def case_tag(label: str) -> str:
    from jevops.tactics import case_tag as _fn

    return _fn(label)


def replace_case_from(dst: str, src: str, tag: str) -> str:
    """Replace one top-level ``case`` arm in ``dst`` with the matching arm from ``src``."""

    from jevops.tactics import replace_case_from as _fn

    return _fn(dst, src, tag)


def drop_bare_simp_all(tactics: str) -> str:
    from jevops.tactics import drop_bare_simp_all as _fn

    return _fn(tactics)


def try_simp_all(tactics: str) -> str:
    from jevops.tactics import try_simp_all as _fn

    return _fn(tactics)


def grok_tactician_variants(grok: str, reference: str) -> list[dict[str, Any]]:
    """Deterministic repairs of a grok file draft. Jev does not write these."""

    import inits_updates_shorten as lra_ius
    from jevops.tactics import tactician_variants as _fn

    return _fn(grok, reference, replay_fn=lra_ius.replay, propose_fn=lra_ius.propose)


MAX_GROK_FANOUT = 14


def assemble_candidates(
    record: Mapping[str, Any],
    tactics: str,
    holes: Sequence[Hole],
    *,
    leanstral_text: Optional[str],
) -> list[dict[str, Any]]:
    del record
    import inits_updates_shorten as lra_ius
    from jevops.tactics import assemble_mca_candidates as _fn

    return _fn(
        tactics,
        holes,
        leanstral_text=leanstral_text,
        replay_fn=lra_ius.replay,
        parse_fills_fn=parse_leanstral_fills if leanstral_text else None,
        indent_fn=lra_kb.match_reference_indent,
        flatten_fn=lra_kb.flatten_overindent,
    )


def prioritize_holes(holes: Sequence[Hole], *, cap: int = 6) -> list[Hole]:
    from jevops.mask import rank_cap

    rank = {"strength_reduction": 0, "algebraic_simplification": 1, "dead_code": 2, "loop_invariant": 3}
    return rank_cap(
        holes,
        key=lambda hole: (rank.get(hole.family, 9), -len(hole.original), hole.hole_id),
        cap=cap,
    )


def ablate_holes(
    record: Mapping[str, Any],
    tactics: str,
    holes: Sequence[Hole],
    *,
    state_root: Path,
    timeout: float,
    restore: bytes,
) -> list[dict[str, Any]]:
    """Drop one MCA hole at a time, then combine lake-valid drops."""

    from jevops.search import ablate_then_combine

    def _compile(body: str) -> Mapping[str, Any]:
        return lra_kb.compile_tactics(
            record, body, state_root=state_root, timeout=timeout, restore=restore
        )

    return ablate_then_combine(
        tactics,
        holes,
        apply_fn=lambda text, fills: apply_fills(text, holes, fills),
        fill_fn=template_fill,
        compile_fn=_compile,
    )


def typesafe_rank_fanout(
    record: Mapping[str, Any],
    drafts: Sequence[dict[str, Any]],
    *,
    ledger: Optional[Any],
) -> dict[str, Any]:
    """One Jev Choice over tactician/PCA drafts. Jev does not write Lean."""

    from jevops.jev import skipped
    from jevops.outer import exc_head, head_chars, head_seq

    if not drafts:
        return skipped("no_drafts", arena_score=None)
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    from _optional_deps import load_typesafe

    typesafe_module, typesafe_reason = load_typesafe()
    if typesafe_module is None:
        return skipped("typesafe_inference_missing", error=typesafe_reason, arena_score=None)
    Choice = typesafe_module.Choice
    TypeSafeClient = typesafe_module.TypeSafeClient
    typesafe_configured = typesafe_module.typesafe_configured

    if not typesafe_configured():
        return skipped("no_key", arena_score=None)
    from jevops.jev import draft_rank_state

    packed = draft_rank_state(
        record,
        drafts,
        goal="Repair a grok-written tactic file. Keep every case arm. Prefer the shortest lake-valid draft.",
    )
    criteria = packed["criteria"]
    state = packed["state"]
    questions = {
        "best_first_draft": Choice(
            instructions=(
                "Which draft id should lake-compile first to repair this grok file? "
                "Prefer restoring a truncated case arm from the reference, then dropping a "
                "no-progress simp_all. Never delete a case header. Do not write Lean."
            ),
            criteria=criteria,
        )
    }
    from jevops.jev import invoke_system_one, invoke_then_project, pack_best_draft
    from jevops.outer import dumps_compact, usage_tokens

    def _project(result: Any, wall_ms: float) -> dict[str, Any]:
        packed = pack_best_draft(result, wall_ms=wall_ms)
        if ledger is not None:
            inn, out = usage_tokens(
                packed.get("usage") or {}, fallback_in=lra_t1.estimate_tokens(dumps_compact(state))
            )
            ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)
        return lra_pca.redact(packed)

    try:
        return invoke_then_project(
            invoke_fn=lambda: invoke_system_one(TypeSafeClient(timeout=60.0), state, questions),
            project_fn=_project,
        )
    except Exception as exc:
        return skipped(exc_head(exc, 400), arena_score=None)


def load_grok_tactics_file(path: Path) -> str:
    from jevops.outer import read_text

    text = read_text(path)
    return lra_loop.extract_generated_tactics(text)


def run_problem(
    name: str,
    *,
    state_root: Path,
    timeout: float,
    call_leanstral: bool,
    ablate: bool = False,
    one_hole: bool = False,
    few_shot: bool = False,
    grok_few_shot: bool = False,
    grok_generate: Optional[Callable[..., str]] = None,
    grok_trace: Optional[Callable[[], Mapping[str, Any]]] = None,
    grok_tactics_paths: Sequence[Path] = (),
    typesafe_fanout: bool = False,
) -> dict[str, Any]:
    from jevops.outer import head_chars, lookup_named

    _raw, digest, records = lra_splice.load_warmup_records()
    record = lookup_named(
        records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
    )
    tactics = lra_fan.tactic_block(record)
    holes = find_holes(tactics)
    skeleton = mask_skeleton(tactics, holes)
    leanstral_text = None
    identity = None
    ledger = None
    grok_skip_reason = ""
    if grok_few_shot:
        # Grok smoke never falls back to hosted Leanstral or docker0.
        call_leanstral = False
    fill_holes = [hole for hole in holes if hole.family in {"strength_reduction", "algebraic_simplification"}]
    one_hole_fills: list[dict[str, Any]] = []
    few_shot_row: Optional[dict[str, Any]] = None
    grok_few_shot_row: Optional[dict[str, Any]] = None
    grok_tactics_current = ""
    grok_errors_current: list[Any] = []
    grok_workspace: Optional[Path] = None
    grok_file_meta: list[dict[str, Any]] = []
    grok_file_rows: list[dict[str, Any]] = []
    typesafe_meta: Optional[dict[str, Any]] = None
    if grok_tactics_paths:
        grok_few_shot = False
        call_leanstral = False
        if ledger is None:
            ledger = lra_t1.ProblemLedger(name=f"{name}#grok-file-fanout")
        for path in grok_tactics_paths:
            loaded = load_grok_tactics_file(path)
            filled = _flatten_tactics(tactics, loaded)
            from jevops.search import pack_generated_candidate

            grok_file_rows.append(
                pack_generated_candidate(
                    kind=f"grok_file_{head_chars(Path(path).stem, 48)}",
                    generator="grok-file",
                    tactics=filled,
                    extra={"source": str(path), "chat_ignored": True},
                )
            )
    if grok_few_shot:
        shots = shot_examples(records, skip_name=name)
        ledger = lra_t1.ProblemLedger(name=f"{name}#grok-few-shot")
        if grok_generate is None and not lra_t1.grok_callable():
            grok_skip_reason = "no_key"
            ledger.skipped = True
            ledger.reason = "no_key"
        else:
            grok_workspace = lra_t1.prepare_grok_workspace()
            prompt = lra_t1.grok_file_prompt(few_shot_prompt(record, shots))
            try:
                grok_result = lra_t1.generate_grok_file(
                    prompt,
                    ledger,
                    workspace=grok_workspace,
                    max_new_tokens=GROK_MAX_NEW_TOKENS,
                    timeout=GROK_TIMEOUT_SECONDS,
                    generate=grok_generate,
                    fixture=grok_generate is not None,
                    reset_stub=True,
                )
            except lra_t1.Track1LedgerError as exc:
                grok_skip_reason = str(exc)
            else:
                identity = grok_result.identity
                filled = _flatten_tactics(tactics, grok_result.tactics)
                grok_file_meta.append({"call": "draft", **grok_result.as_dict()})
                from jevops.search import pack_generated_candidate

                grok_few_shot_row = pack_generated_candidate(
                    kind="grok_few_shot",
                    generator="grok-4.6",
                    tactics=filled,
                    extra={
                        "n_shots": len(shots),
                        "source": "tactics.lean",
                        "tactics_path": grok_result.tactics_path,
                        "chat_ignored": True,
                        "shot_scores": [
                            {
                                "name": shot["name"],
                                "ratio": shot["ratio"],
                                "filled_tokens": shot["filled_tokens"],
                                "ref_tokens": shot["ref_tokens"],
                            }
                            for shot in shots
                        ],
                    },
                )
                grok_tactics_current = filled
    elif few_shot and call_leanstral:
        shots = shot_examples(records, skip_name=name)
        lra_mistral.load_keyfiles()
        lra_mistral.pin_paths()
        ledger = lra_t1.ProblemLedger(name=f"{name}#few-shot")
        prompt = few_shot_prompt(record, shots)
        text, identity, _line = lra_mistral.generate_mistral(
            prompt, ledger, max_new_tokens=900, timeout=180.0
        )
        filled = _flatten_tactics(tactics, text)
        from jevops.search import pack_generated_candidate

        few_shot_row = pack_generated_candidate(
            kind="leanstral_few_shot",
            generator="labs-leanstral-1-5",
            tactics=filled,
            extra={
                "n_shots": len(shots),
                "shot_scores": [
                    {
                        "name": shot["name"],
                        "ratio": shot["ratio"],
                        "filled_tokens": shot["filled_tokens"],
                        "ref_tokens": shot["ref_tokens"],
                    }
                    for shot in shots
                ],
            },
        )
    elif call_leanstral and one_hole:
        targets = prioritize_holes(fill_holes or holes, cap=2)
        if targets:
            lra_mistral.load_keyfiles()
            lra_mistral.pin_paths()
            ledger = lra_t1.ProblemLedger(name=f"{name}#mca-one-hole")
            for hole in targets:
                prompt = one_hole_prompt(record, tactics, hole)
                try:
                    text, identity, _line = lra_mistral.generate_mistral(
                        prompt, ledger, max_new_tokens=256, timeout=120.0
                    )
                except lra_mistral.Track1MistralError:
                    break
                parsed = parse_leanstral_fills(text, [hole])
                fill = parsed.get(hole.hole_id) or parsed.get("__full__") or ""
                if not fill.strip():
                    fill = lra_loop.extract_generated_tactics(text)
                fills = {item.hole_id: (fill if item.hole_id == hole.hole_id else item.original) for item in holes}
                filled = apply_fills(tactics, holes, fills)
                filled = lra_kb.flatten_overindent(tactics, lra_kb.match_reference_indent(tactics, filled))
                from jevops.search import pack_generated_candidate

                one_hole_fills.append(
                    pack_generated_candidate(
                        kind=f"leanstral_one_{hole.hole_id}",
                        generator="labs-leanstral-1-5",
                        tactics=filled,
                        holes=[asdict(hole) | {"fill": head_chars(fill, 400)}],
                    )
                )
    elif call_leanstral and fill_holes:
        lra_mistral.load_keyfiles()
        lra_mistral.pin_paths()
        ledger = lra_t1.ProblemLedger(name=f"{name}#mca-mask")
        prompt = leanstral_prompt(record, mask_skeleton(tactics, fill_holes), fill_holes)
        leanstral_text, identity, _line = lra_mistral.generate_mistral(
            prompt, ledger, max_new_tokens=700, timeout=180.0
        )
        holes_for_leanstral = fill_holes
    else:
        holes_for_leanstral = holes
    from jevops.outer import unique_extend
    from jevops.search import collect_grok_fanout_extras, merge_labeled_candidates, unique_pin_cap

    candidates = assemble_candidates(record, tactics, holes, leanstral_text=None)
    if leanstral_text:
        unique_extend(
            candidates,
            assemble_candidates(record, tactics, holes_for_leanstral, leanstral_text=leanstral_text),
            key_fn=lambda item: item["kind"],
        )
    candidates = merge_labeled_candidates(
        candidates,
        one_hole_fills,
        grok_file_rows,
        extra_rows=(few_shot_row, grok_few_shot_row),
    )
    grok_seeds = [item for item in candidates if str(item.get("kind") or "").startswith("grok")]
    if typesafe_fanout and grok_seeds:
        seed = grok_seeds[0]["tactics"]
        _raw, _digest, warmup_records = lra_splice.load_warmup_records()
        rows_feat = [lra_pca.feature_row(item) for item in warmup_records]
        model = lra_pca.fit_pca_mca(rows_feat)
        from jevops.outer import without_keys

        public_model = without_keys(model, ("zscore", "vt"))
        extras = collect_grok_fanout_extras(
            seed,
            tactics,
            tactician_fn=grok_tactician_variants,
            feature_fn=lra_pca.count_tactics,
            family_fn=lra_pca.amenable_families,
            draft_fn=lra_pca.guided_drafts,
            model=public_model,
        )
        typesafe_meta = typesafe_rank_fanout(record, extras, ledger=ledger)
        pick = str((typesafe_meta or {}).get("best_first_draft") or "")
        candidates.extend(
            unique_pin_cap(extras, pick, key_fn=lambda item: item["kind"], cap=MAX_GROK_FANOUT)
        )
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), state_root)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if
    from jevops.search import finish_mca_problem

    restore = read_bytes_if(dest)

    def _compile(body: str) -> dict[str, Any]:
        return dict(
            lra_kb.compile_tactics(
                record,
                body,
                state_root=state_root,
                timeout=timeout,
                restore=restore,
            )
        )

    def _hammer(kind: str, item: Mapping[str, Any], compiled: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str, list[Any], bool]:
        hammer_gen = "grok+simp_all/omega" if kind.startswith("grok") else "leanstral+simp_all/omega"
        return _hammer_passes(
            kind=kind,
            tactics_now=str(item.get("tactics") or ""),
            reference=tactics,
            errors=compiled.get("errors") or [],
            record=record,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            generator=hammer_gen,
        )

    def _repair(
        rows: list[dict[str, Any]], grok_ok: bool, grok_tactics: str, grok_errors: list[Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        nonlocal identity, grok_skip_reason, grok_file_meta
        if grok_tactics:
            grok_tactics_current = grok_tactics
        else:
            grok_tactics_current = ""
        grok_errors_current = list(grok_errors or [])
        if not (grok_few_shot and grok_few_shot_row is not None and not grok_ok and ledger is not None):
            return rows, grok_ok
        prompt = lra_t1.grok_file_prompt(
            lra_kb.repair_prompt(
                record,
                failed=grok_tactics_current or grok_few_shot_row["tactics"],
                errors=grok_errors_current,
                reference=tactics,
            )
        )
        try:
            grok_result = lra_t1.generate_grok_file(
                prompt,
                ledger,
                workspace=grok_workspace or lra_t1.prepare_grok_workspace(),
                max_new_tokens=GROK_MAX_NEW_TOKENS,
                timeout=GROK_TIMEOUT_SECONDS,
                generate=grok_generate,
                fixture=grok_generate is not None,
                reset_stub=False,
            )
        except lra_t1.Track1LedgerError as exc:
            grok_skip_reason = grok_skip_reason or str(exc)
            rows.append(
                {
                    "kind": "grok_few_shot_repair",
                    "generator": "grok-4.6",
                    "n_chars": 0,
                    "tactics_head": "",
                    "n_holes": 0,
                    "ok": False,
                    "theorem_ok": False,
                    "module_exit_0": False,
                    "exit_code": None,
                    "token_count": None,
                    "errors": [{"pos": None, "data": str(exc)}],
                    "wall_ms": None,
                    "skipped": True,
                    "reason": str(exc),
                    "source": "tactics.lean",
                    "chat_ignored": True,
                }
            )
            return rows, grok_ok
        identity = grok_result.identity
        grok_file_meta.append({"call": "repair", **grok_result.as_dict()})
        repaired_tactics = _flatten_tactics(tactics, grok_result.tactics)
        compiled_r = lra_kb.compile_tactics(
            record,
            repaired_tactics,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
        )
        rows.append(
            _compile_row(
                {
                    "kind": "grok_few_shot_repair",
                    "generator": "grok-4.6",
                    "tactics": repaired_tactics,
                    "holes": [],
                },
                compiled_r,
            )
        )
        if compiled_r.get("theorem_ok"):
            return rows, True
        hammer_rows, _, _, hammer_ok = _hammer_passes(
            kind="grok_few_shot_repair",
            tactics_now=repaired_tactics,
            reference=tactics,
            errors=compiled_r.get("errors") or [],
            record=record,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            generator="grok+simp_all/omega",
        )
        rows.extend(hammer_rows)
        return rows, grok_ok or hammer_ok

    return finish_mca_problem(
        candidates=candidates,
        compile_fn=_compile,
        row_fn=_compile_row,
        hammer_fn=_hammer,
        needs_hammer_fn=_kind_needs_hammer,
        repair_fn=_repair,
        ablate_fn=(
            (
                lambda: ablate_holes(
                    record,
                    tactics,
                    prioritize_holes(holes, cap=6),
                    state_root=state_root,
                    timeout=timeout,
                    restore=restore,
                )
            )
            if ablate and holes
            else None
        ),
        name=name,
        digest=digest,
        holes=[asdict(hole) for hole in holes],
        skeleton_head=head_chars(skeleton, 800),
        hardware_class=GROK_HARDWARE_CLASS if (grok_few_shot or grok_tactics_paths) else HARDWARE_CLASS,
        ref_tokens=lra_loop.token_count(tactics),
        extra_fn=lambda grok_ok, grok_tactics, grok_errors: {
            "leanstral_identity": None if grok_few_shot else identity,
            "grok_identity": _identity_dict(identity) if grok_few_shot else None,
            "grok_few_shot": grok_few_shot,
            "grok_ok": grok_ok,
            "grok_skip_reason": grok_skip_reason or None,
            "grok_used_file": True if grok_few_shot else False,
            "grok_chat_ignored": True if grok_few_shot else False,
            "grok_workspace": None if grok_workspace is None else str(grok_workspace),
            "grok_file_calls": grok_file_meta,
            "typesafe_fanout": typesafe_meta,
            "ledger": None if ledger is None else ledger.as_dict(),
        },
        redact_fn=lra_pca.redact,
    )


def self_check() -> dict[str, Any]:
    tactics = (
        "  induction post <;> simp [substOld]\n"
        "  case fvar =>\n"
        "    intros x Hin\n"
        "    simp at m\n"
        "    simp at name\n"
        "    simp_all\n"
        "  case op =>\n"
        "    rename_i foo\n"
        "    exact h\n"
    )
    holes = find_holes(tactics)
    skeleton = mask_skeleton(tactics, holes)
    fills = {hole.hole_id: template_fill(hole) for hole in holes}
    filled = apply_fills(tactics, holes, fills)
    return {
        "ok": len(holes) >= 2
        and "<<<MCA_0" in skeleton
        and "induction post" in skeleton
        and "case fvar" in skeleton
        and "simp at m" not in filled
        and "rename_i" not in filled,
        "n_holes": len(holes),
        "families": [hole.family for hole in holes],
        "arena_score": None,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--no-leanstral", action="store_true")
    parser.add_argument("--ablate", action="store_true", help="lake-check dropping one MCA hole at a time")
    parser.add_argument("--one-hole", action="store_true", help="hosted Leanstral fills one MCA hole at a time")
    parser.add_argument("--few-shot", action="store_true", help="few-shot Leanstral from scored MCA hole examples")
    parser.add_argument(
        "--grok-few-shot",
        action="store_true",
        help="few-shot grok-4.6 + one lake-error repair (max 2 grok calls, no Leanstral)",
    )
    parser.add_argument(
        "--grok-tactics",
        default="",
        help="comma-separated grok tactics.lean files to repair (no new grok calls)",
    )
    parser.add_argument(
        "--typesafe-fanout",
        action="store_true",
        help="TypeSafe Choice + PCA/MCA/tactician fan-out over grok file drafts",
    )
    parser.add_argument("--names", default=",".join(LAKE_READY))
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.few_shot and args.grok_few_shot:
        raise SystemExit("use either --few-shot (Leanstral) or --grok-few-shot, not both")
    if args.self_check or not args.live:
        from jevops.outer import print_ok

        return print_ok(self_check())
    from jevops.outer import pin_env

    pin_env({"IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0"}, overwrite=False)
    from jevops.outer import split_csv

    names = split_csv(args.names)
    grok_paths = split_csv(args.grok_tactics, cast=Path)
    started = time.perf_counter()
    reports = [
        run_problem(
            name,
            state_root=args.state_root,
            timeout=args.timeout,
            call_leanstral=not args.no_leanstral and not args.grok_few_shot and not grok_paths,
            ablate=args.ablate,
            one_hole=args.one_hole,
            few_shot=args.few_shot,
            grok_few_shot=args.grok_few_shot,
            grok_tactics_paths=grok_paths,
            typesafe_fanout=args.typesafe_fanout,
        )
        for name in names
    ]
    from jevops.outer import elapsed_ms, utc_stamp, write_json_pair

    payload = {
        "schema": "lra-mca-mask-replace-batch/v1",
        "observed_at": utc_stamp(),
        "protocol": PROTOCOL,
        "pr": PR_ID,
        "called_docker0": False,
        "grok_few_shot": bool(args.grok_few_shot),
        "typesafe_fanout": bool(args.typesafe_fanout),
        "arena_score": None,
        "wall_ms": elapsed_ms(started),
        "problems": reports,
    }
    latest = write_json_pair(
        args.out,
        payload,
        prefix="mca-mask",
        latest="mca-mask-latest.json",
        refuse="apikey_",
    )
    stamp = utc_stamp(fmt="%Y%m%dT%H%M%SZ")
    from jevops.outer import copy_text, print_json

    copied = []
    for item in reports:
        for call in item.get("grok_file_calls") or []:
            src = Path(str(call.get("tactics_path") or ""))
            if not src.is_file():
                continue
            dest = args.out / f"grok-{item.get('name')}-{call.get('call')}-{stamp}.lean"
            copy_text(src, dest)
            copied.append(str(dest))

    print_json(
        {
            "ok": True,
            "latest": str(latest),
            "kept": [{"name": item.get("name"), "kept": item.get("kept"), "n_holes": item.get("n_holes")} for item in reports],
            "grok_tactics_files": copied,
            "arena_score": None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
