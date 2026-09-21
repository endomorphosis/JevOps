#!/usr/bin/env python3
"""Mask Lean symbols/operators, fill, TypeSafe-rank.

Diffusion here is discrete denoising over tactic tokens, not neural SGD.

- Mask operators (``$``, ``<;>``, ``?_``, ``‹_›``, ``←``) and symbols
  (tactics/lemmas/hyps) while keeping the PCA skeleton (induction / ``·`` arms).
- TypeSafe Score (``cfg_mask``) picks how many holes and how long each span
  is. Higher score = more / longer masks. PCA control-flow stays unmasked.
- ``--sweep`` walks a small (n_masks × span × n_shots) grid. Closed-vocab
  multi-hole fills and optional few-shot Leanstral fills are all passed to
  TypeSafe Choice.
- ``llm=off``: fill from a closed Lean vocab. No model call.
- ``llm=on``: hosted Labs Leanstral few-shot multi-hole fill. Never docker0.
- Lake is the oracle. Jev does not write Lean.

Not official Track 2. Not an Arena ranking.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import pca_mca_fanout as lra_pca  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_kb  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"

PROTOCOL = "LRA/v1"
PR_ID = "PR-9f"
HARDWARE_CLASS = "spark_gb10"
LEANSTRAL_HARDWARE = "mistral_labs_api"
MARKER = re.compile(r"<<<SYM_(\d+)(?: kind=([a-z_]+))?>>>")

# Longest-first so ‹_› / <;> / ?_ mask as one hole.
# Skip := / · — their closed alts are not strictly shorter.
from jevops.tactics import LEAN_TACTICS
from jevops.tactics import OPERATORS
from jevops.tactics import OPERATOR_ALTS
from jevops.tactics import PCA_KEEP_PREFIXES
from jevops.tactics import PHRASE_ALTS
from jevops.tactics import STRUCTURE
# Phrase/operator/tactic vocab lives in jevops.tactics.

# TypeSafe Score rubric: index = CFG aggressiveness. Higher → more/longer masks.
CFG_MASK_CRITERIA: tuple[str, ...] = (
    "2 masks of 1 token; keep PCA induction/dot arms",
    "3 masks of 2 tokens",
    "4 masks of 3 tokens",
    "6 masks of 4 tokens",
    "8 masks of 6 tokens",
)
# cfg_scale is classifier-free guidance: 0 = no few-shot (uncond), >0 = k shots.
CFG_SCHEDULES: tuple[dict[str, Any], ...] = (
    {"id": "cfg0", "n_masks": 2, "span": 1, "n_shots": 0, "cfg_scale": 0.0},
    {"id": "cfg1", "n_masks": 3, "span": 2, "n_shots": 2, "cfg_scale": 1.0},
    {"id": "cfg2", "n_masks": 4, "span": 3, "n_shots": 4, "cfg_scale": 1.5},
    {"id": "cfg3", "n_masks": 6, "span": 4, "n_shots": 6, "cfg_scale": 2.0},
    {"id": "cfg4", "n_masks": 8, "span": 6, "n_shots": 8, "cfg_scale": 3.0},
)
# One hole at a time; vary span; multi-shot fills. Score index = span bucket.
ONE_HOLE_SPANS: tuple[int, ...] = (1, 2, 3, 4, 6)
ONE_HOLE_CRITERIA: tuple[str, ...] = (
    "1-token hole (operator / ident)",
    "2-token hole",
    "3-token hole (short phrase)",
    "4-token hole",
    "6-token hole (kernel-sized span)",
)
ONE_HOLE_SCHEDULES: tuple[dict[str, Any], ...] = tuple(
    {"id": f"span{span}", "n_masks": 1, "span": span, "n_shots": 6, "cfg_scale": 1.5}
    for span in ONE_HOLE_SPANS
)


@dataclass(frozen=True)
class SymbolHole:
    hole_id: str
    kind: str  # operator | ident | phrase | span
    start: int
    end: int
    original: str
    n_tokens: int = 1


def _as_row(item: SymbolHole) -> dict[str, Any]:
    return {
        "hole_id": item.hole_id,
        "kind": item.kind,
        "start": item.start,
        "end": item.end,
        "original": item.original,
        "n_tokens": item.n_tokens,
    }


def _from_row(row: Mapping[str, Any]) -> SymbolHole:
    return SymbolHole(
        hole_id=str(row.get("hole_id") or "SYM_0"),
        kind=str(row.get("kind") or "span"),
        start=int(row["start"]),
        end=int(row["end"]),
        original=str(row.get("original") or ""),
        n_tokens=int(row.get("n_tokens") or 1),
    )


def find_symbol_holes(tactics: str, *, max_holes: int = 24) -> list[SymbolHole]:
    """Mask operators first, then leftover identifiers that are not PCA structure."""

    from jevops.mask import collect_literal_holes
    from jevops.tactics import ident_holes

    return collect_literal_holes(
        tactics,
        phrases=[src for src, _dst in PHRASE_ALTS],
        operators=OPERATORS,
        ident_fn=lambda text, occupied, max_holes, id_prefix: ident_holes(
            text,
            token_re=lra_loop._TOKEN,
            occupied=occupied,
            skip_tokens=tuple(STRUCTURE) + tuple(LEAN_TACTICS),
            pca_prefixes=PCA_KEEP_PREFIXES,
            max_holes=max_holes,
            id_prefix=id_prefix,
        ),
        from_row_fn=_from_row,
        rehole_fn=_rehole,
        max_holes=max_holes,
        id_prefix="SYM_",
    )


def is_pca_line(tactics: str, pos: int) -> bool:
    from jevops.tactics import is_pca_line as _fn

    return _fn(tactics, pos)


def cfg_schedule_for_score(score: Any, *, one_hole: bool = False) -> dict[str, Any]:
    """Map a TypeSafe Score (0..len-1, may be fractional) onto a mask schedule."""

    from jevops.mask import schedule_for_score

    table = ONE_HOLE_SCHEDULES if one_hole else CFG_SCHEDULES
    return schedule_for_score(score, table)


def _rehole(hole: SymbolHole, index: int) -> SymbolHole:
    return SymbolHole(
        hole_id=f"SYM_{index}",
        kind=hole.kind,
        start=hole.start,
        end=hole.end,
        original=hole.original,
        n_tokens=hole.n_tokens,
    )


def all_span_windows(tactics: str, span: int, *, stride: Optional[int] = None) -> list[SymbolHole]:
    """Token windows of ``span``. Default stride=span (tile). stride=1 overlaps."""

    from jevops.mask import span_windows

    rows = span_windows(
        tactics,
        span,
        stride=stride,
        tokens=list(lra_loop._TOKEN.finditer(tactics)),
        skip_fn=is_pca_line,
    )
    return [_from_row(row) for row in rows]


def schedule_holes(tactics: str, *, n_masks: int, span: int) -> list[SymbolHole]:
    """Non-overlapping token windows of ``span``, skipping PCA control-flow lines."""

    from jevops.mask import pick_nonoverlapping

    n_masks = max(1, int(n_masks))
    windows = all_span_windows(tactics, span)
    if not windows:
        fallback = find_symbol_holes(tactics, max_holes=n_masks)
        return [_rehole(hole, i) for i, hole in enumerate(fallback[:n_masks])]
    picked = pick_nonoverlapping([_as_row(item) for item in windows], n=n_masks)
    return [_from_row(row) for row in picked]


def _window_priority(hole: SymbolHole) -> int:
    score = 0
    for src, _dst in PHRASE_ALTS:
        if src in hole.original:
            score += 10 + len(src)
    for op in OPERATORS:
        if op in hole.original:
            score += 3
    return score


def prefer_one_holes(tactics: str, span: int, *, max_pos: int = 2) -> list[SymbolHole]:
    """One hole of ``span`` tokens, preferring phrase/operator-aligned windows."""

    from jevops.mask import pick_scored

    windows = all_span_windows(tactics, span, stride=1)
    if not windows:
        return schedule_holes(tactics, n_masks=1, span=span)
    picked = pick_scored(
        [_as_row(hole) for hole in windows],
        n=max(1, int(max_pos)),
        score_fn=lambda row: _window_priority(_from_row(row)),
        reindex=False,
    )
    return [_rehole(_from_row(row), 0) for row in picked]


def one_hole_shots(*, span: int, n_shots: int = 6) -> list[dict[str, Any]]:
    """Single-hole few-shot fills whose original length is close to ``span``."""

    from jevops.mask import one_hole_shots as _fn

    return _fn(
        phrase_alts=PHRASE_ALTS,
        operator_alts=OPERATOR_ALTS,
        span=span,
        n_shots=n_shots,
        token_fn=lra_loop.token_count,
    )


def one_hole_closed_rows(tactics: str, *, max_pos: int = 2) -> list[dict[str, Any]]:
    """Closed-vocab fill of one hole per span, a few phrase-aligned positions."""

    rows: list[dict[str, Any]] = []
    for span in ONE_HOLE_SPANS:
        for index, hole in enumerate(prefer_one_holes(tactics, span, max_pos=max_pos)):
            row = closed_multihole(tactics, [hole], schedule_id=f"span{span}_p{index}")
            if not row:
                continue
            row["span"] = span
            row["n_masks"] = 1
            row["n_shots"] = 6
            row["cfg_scale"] = 1.5
            row["original"] = hole.original
            rows.append(row)
    return rows


def kernel_one_hole_rows(tactics: str) -> list[dict[str, Any]]:
    """One catalog kernel per candidate: a single aligned span of varying length."""

    try:
        import inits_updates_shorten as lra_ius
    except Exception:
        return []
    from jevops.mask import kernel_one_hole_rows as _fn

    return _fn(
        tactics,
        propose_fn=lra_ius.propose,
        token_fn=lra_loop.token_count,
        spans=ONE_HOLE_SPANS,
    )


def catalog_shots(tactics: str, *, n_shots: int = 4) -> list[dict[str, Any]]:
    """Few-shot multi-hole fills from the cataloged 268→139 phrase cuts."""

    from jevops.mask import catalog_shots as _fn
    from jevops.outer import head_seq

    return _fn(
        tactics,
        phrase_alts=PHRASE_ALTS,
        n_shots=n_shots,
        head_fn=head_seq,
    )


def few_shot_prompt(
    record: Mapping[str, Any],
    skeleton: str,
    holes: Sequence[SymbolHole],
    shots: Sequence[Mapping[str, Any]],
) -> str:
    from jevops.mask import shot_fill_prompt

    return shot_fill_prompt(
        record,
        skeleton,
        holes,
        shots,
        preamble=(
            "Lean 4 tactic multi-hole fill. Each <<<SYM_i kind=...>>> is a masked span. "
            "Fill with a SHORTER Lean operator/symbol/phrase (constructor, intro, .update_some, "
            "all_goals simp_all, UpdateStatesDefined Hups, assumption, or empty to drop). "
            "Keep induction and every · / case arm. No sorry, no theorem, no open.\n\n"
        ),
        reply="Reply as:\n<<<SYM_0 kind=...>>>\n<fill>\n<<<SYM_1 kind=...>>>\n<fill>\n",
    )


def script_idents(tactics: str) -> list[str]:
    from jevops.tactics import script_idents as _fn

    return _fn(tactics, token_re=lra_loop._TOKEN)


def closed_fills(hole: SymbolHole, tactics: str) -> list[str]:
    """Lean-language fills. No model. Prefer strictly shorter replacements."""

    from jevops.tactics import closed_fills as _fn

    return _fn(
        _as_row(hole),
        tactics,
        phrase_alts=PHRASE_ALTS,
        operator_alts=OPERATOR_ALTS,
        token_re=lra_loop._TOKEN,
    )


def mask_skeleton(tactics: str, holes: Sequence[SymbolHole]) -> str:
    from jevops.mask import mask_skeleton as _fn

    return _fn(tactics, [_as_row(item) for item in holes])


def apply_fill(tactics: str, hole: SymbolHole, fill: str) -> str:
    from jevops.mask import apply_fill as _fn

    return _fn(tactics, _as_row(hole), fill)


def closed_candidates(
    tactics: str, *, max_candidates: int = 32, include_replay: bool = True
) -> list[dict[str, Any]]:
    """One-hole closed-vocab edits that are strictly shorter."""

    from jevops.mask import closed_with_replay

    replay_fn = None
    if include_replay:
        try:
            import inits_updates_shorten as lra_ius

            replay_fn = lra_ius.replay
        except Exception:
            replay_fn = None
    return closed_with_replay(
        tactics,
        find_symbol_holes(tactics),
        fills_fn=lambda item, text: closed_fills(_from_row(item), text),
        token_fn=lra_loop.token_count,
        as_row_fn=_as_row,
        replay_fn=replay_fn,
        max_candidates=max_candidates,
        generator="closed_lean_vocab",
    )


def closed_multihole(tactics: str, holes: Sequence[SymbolHole], *, schedule_id: str = "cfg") -> Optional[dict[str, Any]]:
    """Apply one shorter closed fill at every selected span together."""

    from jevops.mask import closed_multihole_row

    return closed_multihole_row(
        tactics,
        holes,
        schedule_id=schedule_id,
        fills_fn=lambda item, text: closed_fills(_from_row(item), text),
        token_fn=lra_loop.token_count,
        as_row_fn=_as_row,
    )


def parse_leanstral_fills(text: str, holes: Sequence[SymbolHole]) -> dict[str, str]:
    from jevops.mask import parse_marked_fills

    return parse_marked_fills(text, holes, attr="kind")


def leanstral_prompt(
    record: Mapping[str, Any],
    skeleton: str,
    holes: Sequence[SymbolHole],
    shots: Sequence[Mapping[str, Any]] = (),
) -> str:
    from jevops.outer import head_seq

    if shots:
        return few_shot_prompt(record, skeleton, holes, shots)
    docs = []
    for hole in head_seq(holes, 8):
        docs.append(f"{hole.hole_id} kind={hole.kind} ORIGINAL={hole.original!r}\n")
    return (
        "Lean 4 tactic hole-fill. Each <<<SYM_i kind=...>>> is one operator or symbol. "
        "Fill with a SHORTER Lean operator/symbol from the language (constructor, simp_all, $, "
        "‹_›, all_goals, intro, .update_some, a hyp already in the proof). "
        "Keep induction and every · / case arm. No sorry, no theorem, no open.\n\n"
        f"Problem: {record.get('name')}\n"
        f"SKELETON:\n{skeleton}\n\n"
        f"HOLES:\n{''.join(docs)}\n"
        "Reply as:\n<<<SYM_0 kind=...>>>\n<fill>\n<<<SYM_1 kind=...>>>\n<fill>\n"
    )


def leanstral_candidates(
    record: Mapping[str, Any],
    tactics: str,
    holes: Sequence[SymbolHole],
    *,
    ledger: Optional[Any] = None,
    shots: Sequence[Mapping[str, Any]] = (),
    schedule_id: str = "leanstral",
    n_shots: int = 0,
) -> list[dict[str, Any]]:
    import track1_mistral_leanstral as lra_mistral
    from jevops.outer import head_chars, head_seq

    lra_mistral.load_keyfiles()
    if not holes:
        holes = head_seq(
            [hole for hole in find_symbol_holes(tactics) if hole.kind in ("operator", "phrase")],
            8,
        )
    holes = head_seq(holes, 8)
    if not holes:
        return []
    use_shots = list(shots)[: max(0, int(n_shots))]
    if not use_shots and n_shots:
        use_shots = catalog_shots(tactics, n_shots=n_shots)
    skeleton = mask_skeleton(tactics, holes)
    prompt = leanstral_prompt(record, skeleton, holes, use_shots)
    raw = lra_mistral.chat_completions(prompt, max_tokens=600, temperature=0.3, n=1)
    text = str(raw.get("text") or "")
    if not text:
        nested = ((raw.get("choices") or [{}])[0] if isinstance(raw.get("choices"), list) else {})
        text = str(((nested.get("message") or {}) if isinstance(nested, dict) else {}).get("content") or "")
    if ledger is not None:
        usage = dict(raw.get("usage") or {})
        inn = int(
            raw.get("input_tokens")
            or usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 200
        )
        out = int(
            raw.get("output_tokens")
            or usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )
        ledger.record(
            "mistral",
            input_tokens=inn,
            output_tokens=out,
            model=str(raw.get("model") or lra_mistral.REQUESTED_MODEL),
        )
    fills = parse_leanstral_fills(text, holes)
    from jevops.mask import pack_leanstral_fill_rows

    return pack_leanstral_fill_rows(
        tactics=tactics,
        holes=holes,
        text=text,
        fills=fills,
        token_fn=lra_loop.token_count,
        extract_fn=lra_loop.extract_generated_tactics,
        schedule_id=schedule_id,
        n_shots=len(use_shots),
        head_fn=head_chars,
    )


def typesafe_rank(
    record: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    from jevops.jev import skipped
    from jevops.outer import head_chars, head_seq

    if not drafts:
        return skipped("no_drafts", arena_score=None)
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    from _optional_deps import load_typesafe

    typesafe_module, typesafe_reason = load_typesafe()
    if typesafe_module is None:
        return skipped("typesafe_inference_missing", error=typesafe_reason, arena_score=None)
    Choice = typesafe_module.Choice
    Noul = typesafe_module.Noul
    Score = typesafe_module.Score
    TypeSafeClient = typesafe_module.TypeSafeClient
    typesafe_configured = typesafe_module.typesafe_configured

    if not typesafe_configured():
        return skipped("no_key", arena_score=None)
    criteria = {
        str(item["kind"]): head_chars(
            f"{item.get('generator')}; sched={item.get('schedule_id')}; "
            f"shots={item.get('n_shots')}; masks={item.get('n_masks')}; "
            f"{item.get('original')!s} -> {item.get('fill')!s}; "
            f"{item.get('token_count')} tok",
            180,
        )
        for item in head_seq(drafts, 16)
    }
    state = {
        "problem": record.get("name"),
        "goal": (
            "Rank masked-operator fills, including few-shot Leanstral multi-hole "
            "fills and closed-vocab CFG-schedule fills. Prefer the shortest "
            "candidate that still lake-compiles. Do not write Lean."
        ),
        "drafts": [
            {
                "id": item["kind"],
                "head": head_chars(item.get("tactics") or "", 220),
                "tokens": item.get("token_count"),
                "schedule_id": item.get("schedule_id"),
                "n_shots": item.get("n_shots"),
                "n_masks": item.get("n_masks"),
                "few_shot": item.get("few_shot"),
            }
            for item in head_seq(drafts, 16)
        ],
    }
    questions: dict[str, Any] = {
        "best_fill": Choice(
            instructions=(
                "Which fill id is most likely to lake-compile AND use fewer tokens? "
                "Prefer constructor/$/all_goals/intro/.update_some and catalog "
                "few-shot multi-hole fills over dropping hyps. Do not write Lean."
            ),
            criteria=criteria,
        ),
        "cfg_mask": Score(
            instructions=(
                "How aggressively should the next denoise step mask this proof? "
                "Higher = more holes and longer token spans. Never mask induction "
                "or · / case arms. Do not write Lean."
            ),
            criteria=list(CFG_MASK_CRITERIA),
        ),
    }
    if any(item.get("llm") == "on" or item.get("few_shot") for item in drafts):
        questions["prefer_few_shot"] = Noul(
            instructions=(
                "Is a few-shot multi-hole Leanstral fill more likely to lake-compile "
                "AND cut tokens than the closed-vocab fills? true means the few-shot "
                "fill is the wrong bet."
            )
        )
    from jevops.jev import invoke_system_one, invoke_then_project, pack_fill_rank
    from jevops.outer import usage_tokens

    def _project(result: Any, wall_ms: float) -> dict[str, Any]:
        packed = pack_fill_rank(result, wall_ms, schedule_fn=cfg_schedule_for_score)
        if ledger is not None:
            inn, out = usage_tokens(packed.get("usage") or {}, fallback_in=200)
            ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)
        return packed

    return invoke_then_project(
        invoke_fn=lambda: invoke_system_one(TypeSafeClient(timeout=45.0), state, questions),
        project_fn=_project,
    )


def typesafe_cfg_score(
    record: Mapping[str, Any],
    tactics: str,
    *,
    ledger: Optional[Any] = None,
    one_hole: bool = False,
) -> dict[str, Any]:
    """Ask TypeSafe Score/Choice how many masks and how long they should be."""

    table = ONE_HOLE_SCHEDULES if one_hole else CFG_SCHEDULES
    rubric = ONE_HOLE_CRITERIA if one_hole else CFG_MASK_CRITERIA
    lra_pca.load_keyfile()
    lra_pca.pin_typesafe_path()
    from _optional_deps import load_typesafe

    typesafe_module, typesafe_reason = load_typesafe()
    if typesafe_module is None:
        return skipped(
            "typesafe_inference_missing",
            error=typesafe_reason,
            cfg_schedule=dict(table[0]),
            one_hole=one_hole,
        )
    Choice = typesafe_module.Choice
    Score = typesafe_module.Score
    TypeSafeClient = typesafe_module.TypeSafeClient
    typesafe_configured = typesafe_module.typesafe_configured

    from jevops.jev import skipped
    from jevops.outer import head_chars

    if not typesafe_configured():
        return skipped("no_key", cfg_schedule=dict(table[0]), one_hole=one_hole)
    eligible = {
        f"span_{span}": len(all_span_windows(tactics, span))
        for span in ONE_HOLE_SPANS
    }
    criteria = {
        str(item["id"]): (
            f"{item['n_masks']} hole(s) × {item['span']} tokens; "
            f"{item['n_shots']} few-shot; cfg_scale={item['cfg_scale']}; "
            f"eligible_span_{item['span']}={eligible.get(f'span_{item['span']}', 0)}"
        )
        for item in table
    }
    state = {
        "problem": record.get("name"),
        "tokens": lra_loop.token_count(tactics),
        "eligible_spans": eligible,
        "one_hole": one_hole,
        "goal": (
            "Pick a ONE-HOLE span length for discrete text diffusion. "
            "Higher CFG score means a longer masked span. Keep induction and · arms. "
            "Do not write Lean."
            if one_hole
            else (
                "Pick a mask schedule for discrete text diffusion. Higher CFG score "
                "means more/longer masks. Keep induction and · arms. Do not write Lean."
            )
        ),
        "head": head_chars(tactics, 400),
    }
    from jevops.jev import invoke_system_one, pack_cfg_score
    from jevops.outer import usage_tokens

    result, wall_ms = invoke_system_one(
        TypeSafeClient(timeout=45.0),
        state,
        {
            "cfg_mask": Score(
                instructions=(
                    "How long should the single masked span be? Higher = more tokens "
                    "in that one hole. Stay off PCA induction/· / case. Do not write Lean."
                    if one_hole
                    else (
                        "How aggressively should we mask this Lean proof? Higher = more "
                        "holes and longer spans. Stay off PCA induction/· / case. Do not write Lean."
                    )
                ),
                criteria=list(rubric),
            ),
            "best_schedule": Choice(
                instructions=(
                    "Which one-hole span length should Leanstral / closed-vocab fill next? "
                    "Prefer a span that matches a remaining rewrite phrase. Do not write Lean."
                    if one_hole
                    else (
                        "Which mask schedule should Leanstral / closed-vocab fill next? "
                        "Prefer a schedule whose span length matches remaining rewrite "
                        "phrases. Do not write Lean."
                    )
                ),
                criteria=criteria,
            ),
        },
    )
    packed = pack_cfg_score(
        result,
        wall_ms,
        table=table,
        schedule_fn=cfg_schedule_for_score,
        one_hole=one_hole,
        eligible=eligible,
    )
    if ledger is not None:
        inn, out = usage_tokens(packed.get("usage") or {}, fallback_in=200)
        ledger.record("jev", input_tokens=inn, output_tokens=out, model=lra_t1.JEV_MODEL_ID)
    return packed


def pca_mca_ops(tactics: str) -> list[tuple[str, str, tuple[str, ...]]]:
    from jevops.tactics import collect_symbol_ops

    return collect_symbol_ops(
        closed_candidates(tactics, max_candidates=8, include_replay=True),
        kernel_one_hole_rows(tactics),
        family="symbol_diffuse",
        kernel_cap=8,
    )


def self_check() -> dict[str, Any]:
    import inits_updates_shorten as lra_ius
    from jevops.outer import head_seq

    src = lra_ius.original_tactics()
    holes = find_symbol_holes(src)
    cands = closed_candidates(src)
    replay = lra_ius.replay(src)
    kinds = {item["kind"] for item in cands}
    has_ctor = any("constructor" in str(item.get("fill") or "") or "And.intro" in str(item.get("original") or "") for item in cands)
    has_dollar = any(item.get("original") == "$" or item.get("fill") == "$" for item in cands)
    shots = catalog_shots(src, n_shots=4)
    span_holes = schedule_holes(src, n_masks=4, span=3)
    multi = closed_multihole(src, span_holes, schedule_id="cfg2")
    oh_shots = one_hole_shots(span=3, n_shots=4)
    oh_windows = prefer_one_holes(src, 4, max_pos=3) + prefer_one_holes(src, 3, max_pos=3)
    oh_rows = one_hole_closed_rows(src, max_pos=1)
    prompt = few_shot_prompt({"name": lra_ius.PROBLEM}, mask_skeleton(src, span_holes), span_holes, shots)
    cfg0 = cfg_schedule_for_score(0)
    cfg4 = cfg_schedule_for_score(4)
    return {
        "ok": (
            len(holes) >= 3
            and len(cands) >= 3
            and lra_loop.token_count(replay) == 139
            and (has_ctor or has_dollar or any("intro" in str(item.get("fill") or "") for item in cands))
            and any(int(shot.get("n_holes") or 0) >= 2 for shot in shots)
            and "EXAMPLE" in prompt
            and "constructor" in prompt
            and len(span_holes) >= 1
            and cfg0["n_masks"] == 2
            and cfg4["span"] == 6
            and (multi is None or int(multi["token_count"]) < lra_loop.token_count(src))
            and oh_shots
            and all(int(shot.get("n_holes") or 0) == 1 for shot in oh_shots)
            and any(
                "And.intro" in hole.original or "intros Hin" in hole.original or ".update_some" in hole.original
                for hole in oh_windows
            )
            and any(int(row["token_count"]) < lra_loop.token_count(src) for row in oh_rows)
            and any(
                item["kind"].startswith("kernel_")
                for item in kernel_one_hole_rows(src)
            )
        ),
        "n_holes": len(holes),
        "n_closed_candidates": len(cands),
        "n_catalog_shots": len(shots),
        "n_span_holes": len(span_holes),
        "multi_hole_tokens": None if multi is None else multi["token_count"],
        "hole_kinds": sorted({hole.kind for hole in holes}),
        "sample_kinds": head_seq(sorted(kinds), 12),
        "llm": "off",
        "called_docker0": False,
        "arena_score": None,
        "replay_tokens": lra_loop.token_count(replay),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--llm", choices=("off", "on"), default="off")
    parser.add_argument("--names", default="Core.InitsUpdatesComm")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--lake-top", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--init-file", type=Path, default=None)
    parser.add_argument("--sweep", action="store_true", help="parameter sweep over CFG mask schedules")
    parser.add_argument("--few-shot", action="store_true", help="force few-shot Leanstral (default on when --llm on)")
    parser.add_argument("--no-few-shot", action="store_true", help="zero-shot Leanstral even if --llm on")
    parser.add_argument("--no-replay", action="store_true", help="omit the 268→139 kernel dump from candidates")
    parser.add_argument("--cfg-schedules", default="cfg0,cfg1,cfg2,cfg3,cfg4")
    parser.add_argument("--leanstral-top", type=int, default=2, help="max hosted Leanstral calls per round")
    parser.add_argument("--one-hole", action="store_true", help="one hole per step; vary span; multi-shot fills")
    parser.add_argument("--one-hole-spans", default="1,2,3,4,6", help="comma-separated token spans for --one-hole")
    args = parser.parse_args(argv)
    few_shot = (args.llm == "on" or args.few_shot) and not args.no_few_shot
    one_hole = bool(args.one_hole)
    from jevops.outer import exc_head, first_csv, head_seq, lookup_named, split_csv

    if one_hole:
        span_wanted = split_csv(args.one_hole_spans, cast=int)
        grid = [dict(item) for item in ONE_HOLE_SCHEDULES if item["span"] in span_wanted] or [
            dict(item) for item in ONE_HOLE_SCHEDULES
        ]
    else:
        wanted_ids = split_csv(args.cfg_schedules)
        grid = [dict(item) for item in CFG_SCHEDULES if item["id"] in wanted_ids] or [dict(item) for item in CFG_SCHEDULES]
    if args.self_check or not args.live:
        from jevops.outer import print_ok

        payload = self_check()
        code = print_ok(payload)
        if args.self_check and not args.live:
            return code
        if not args.live:
            return code
    import inits_updates_shorten as lra_ius

    _raw, digest, records = lra_splice.load_warmup_records()
    name = first_csv(args.names)
    record = lookup_named(
        records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
    )
    import draft_fanout as lra_fan
    import mcmc_beam as lra_mcmc

    from jevops.outer import read_text

    if args.init_file and Path(args.init_file).is_file():
        tactics = read_text(args.init_file).strip("\n")
    elif name == lra_ius.PROBLEM:
        tactics = lra_ius.original_tactics()
    else:
        tactics = lra_fan.tactic_block(record)
    ledger = lra_t1.ProblemLedger(
        name=f"{name}#symbol-diffuse",
        max_jev_calls=max(12, int(args.rounds) * 3 + 4),
        max_mistral_calls=max(6, int(args.rounds) * max(1, int(args.leanstral_top)) + 2),
    )
    clone = lra_kb.lra_cw.clone_dir(str(record["url"]), DEFAULT_STATE)
    dest = clone / lra_kb.lra_cw.source_relpath(record)
    from jevops.outer import read_bytes_if

    restore = read_bytes_if(dest)
    best = {
        "kind": "init",
        "token_count": lra_loop.token_count(tactics),
        "theorem_ok": True,
        "tactics": tactics,
    }
    lake_rows: list[dict[str, Any]] = []
    ranked_rows: list[dict[str, Any]] = []
    cfg_rows: list[dict[str, Any]] = []
    current = tactics
    ranked: dict[str, Any] = {}
    last_closed: list[dict[str, Any]] = []
    for round_i in range(max(1, int(args.rounds))):
        cfg = typesafe_cfg_score(record, current, ledger=ledger, one_hole=one_hole)
        cfg["round"] = round_i
        cfg_rows.append(cfg)
        picked = dict(cfg.get("cfg_schedule") or (grid[0] if grid else CFG_SCHEDULES[0]))
        schedules = list(grid) if (args.sweep or one_hole) else [picked]
        if not any(item["id"] == picked["id"] for item in schedules):
            schedules.insert(0, picked)
        candidates: list[dict[str, Any]] = []
        if not args.no_replay:
            for item in closed_candidates(current, max_candidates=4, include_replay=True):
                if item.get("kind") == "inits_replay":
                    candidates.append(item)
                    break
        phrase_rows = head_seq(closed_candidates(current, max_candidates=8, include_replay=False), 6)
        kernel_rows = kernel_one_hole_rows(current) if one_hole else []
        # Catalog one-step kernels, then phrase one-holes, so lake_top sees
        # drop_not_intro / fold_init / constructor before blind span windows.
        candidates.extend(kernel_rows)
        candidates.extend(phrase_rows)
        if one_hole:
            candidates.extend(one_hole_closed_rows(current, max_pos=2))
        else:
            for sched in schedules:
                span_holes = schedule_holes(current, n_masks=int(sched["n_masks"]), span=int(sched["span"]))
                row = closed_multihole(current, span_holes, schedule_id=str(sched["id"]))
                if row:
                    row["span"] = sched["span"]
                    row["n_shots"] = sched["n_shots"]
                    row["cfg_scale"] = sched["cfg_scale"]
                    candidates.append(row)
        if args.llm == "on":
            if one_hole:
                lean_schedules = [picked]
                for extra in schedules:
                    if extra["id"] == picked["id"]:
                        continue
                    lean_schedules.append(extra)
                    if len(lean_schedules) >= max(1, int(args.leanstral_top)):
                        break
                lean_schedules = lean_schedules[: max(1, int(args.leanstral_top))]
            else:
                lean_schedules = [picked]
                if args.sweep:
                    from jevops.outer import first_where

                    zero = first_where(schedules, lambda item: int(item.get("n_shots") or 0) == 0)
                    if zero is not None and zero["id"] != picked["id"]:
                        lean_schedules.append(zero)
                lean_schedules = lean_schedules[: max(1, int(args.leanstral_top))]
            for sched in lean_schedules:
                span = int(sched["span"])
                if one_hole:
                    span_holes = prefer_one_holes(current, span, max_pos=1)
                    n_shots = int(sched["n_shots"] or 0) if few_shot else 0
                    shots = one_hole_shots(span=span, n_shots=n_shots) if n_shots else []
                else:
                    span_holes = schedule_holes(
                        current, n_masks=int(sched["n_masks"]), span=span
                    )
                    n_shots = int(sched["n_shots"] or 0) if few_shot else 0
                    shots = catalog_shots(current, n_shots=n_shots) if n_shots else []
                try:
                    rows = leanstral_candidates(
                        record,
                        current,
                        span_holes,
                        ledger=ledger,
                        shots=shots,
                        schedule_id=str(sched["id"]),
                        n_shots=n_shots,
                    )
                    candidates = rows + candidates
                except Exception as exc:  # noqa: BLE001
                    ranked_rows.append(
                        {
                            "round": round_i,
                            "leanstral_error": exc_head(exc),
                            "schedule_id": sched["id"],
                        }
                    )
        last_closed = candidates
        if not candidates:
            ranked_rows.append({"round": round_i, "skipped": "no_candidates"})
            break
        ranked = typesafe_rank(record, candidates, ledger=ledger)
        ranked["round"] = round_i
        ranked_rows.append(ranked)
        order = [ranked.get("best_fill")] if ranked.get("best_fill") else []
        if one_hole:
            order.extend(item["kind"] for item in kernel_rows)
            order.extend(item["kind"] for item in phrase_rows)
        order.extend(item["kind"] for item in candidates)
        by_kind = {item["kind"]: item for item in candidates if "tactics" in item}
        accepted = None
        tried = 0
        seen_kind: set[str] = set()
        ok_hits: list[tuple[int, str, str]] = []
        for kind in order:
            if kind in seen_kind or kind not in by_kind:
                continue
            seen_kind.add(str(kind))
            body = str(by_kind[kind]["tactics"])
            compiled = lra_mcmc.compile_one(
                record, body, state_root=DEFAULT_STATE, timeout=args.timeout, restore=restore
            )
            row = {
                "round": round_i,
                "kind": kind,
                "ok": bool(compiled.get("theorem_ok")),
                "tokens": compiled.get("token_count"),
                "schedule_id": by_kind[kind].get("schedule_id"),
                "n_shots": by_kind[kind].get("n_shots"),
                "errors": head_seq(compiled.get("errors"), 1),
            }
            lake_rows.append(row)
            tried += 1
            if row["ok"] and int(row["tokens"] or 999) < int(best["token_count"]):
                ok_hits.append((int(row["tokens"]), str(kind), body))
                if not (args.sweep or one_hole):
                    break
            if tried >= int(args.lake_top):
                break
        if ok_hits:
            ok_hits.sort(key=lambda item: item[0])
            tok, kind, body = ok_hits[0]
            best = {
                "kind": f"r{round_i}_{kind}",
                "token_count": tok,
                "theorem_ok": True,
                "tactics": body,
            }
            accepted = body
        if not accepted:
            ranked_rows.append({"round": round_i, "stopped": "no_shorter_lake_ok"})
            break
        current = accepted
    holes = find_symbol_holes(current)
    args.out.mkdir(parents=True, exist_ok=True)
    from jevops.outer import utc_stamp, write_json_pair

    payload = {
        "schema": "lra-symbol-diffuse/v1",
        "observed_at": utc_stamp(),
        "name": name,
        "llm": args.llm,
        "few_shot": few_shot,
        "one_hole": one_hole,
        "sweep": bool(args.sweep) or one_hole,
        "rounds": int(args.rounds),
        "n_holes": len(holes),
        "n_closed": len([item for item in last_closed if item.get("llm") == "off"]),
        "cfg": cfg_rows,
        "ranked": ranked,
        "ranked_rows": ranked_rows,
        "lake": lake_rows,
        "best": {k: best[k] for k in best if k != "tactics"},
        "source_tokens": lra_loop.token_count(tactics),
        "called_docker0": False,
        "official_track2": False,
        "arena_score": None,
        "warmup_jsonl_sha256": digest,
        "ledger": ledger.as_dict() if hasattr(ledger, "as_dict") else {"jev_calls": getattr(ledger, "jev_calls", 0)},
    }
    if best.get("tactics") and int(best["token_count"]) < lra_loop.token_count(tactics):
        (args.out / f"symbol-diffuse-best-{best['token_count']}.lean").write_text(str(best["tactics"]) + "\n")
    write_json_pair(
        args.out,
        payload,
        prefix="symbol-diffuse",
        latest="symbol-diffuse-latest.json",
    )
    from jevops.outer import print_json

    print_json(payload, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
