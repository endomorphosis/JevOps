#!/usr/bin/env python3
"""Coordinate search / keep-best accept / prefix beam helpers.

Lake (or another oracle) still admits. Jev does not write Lean. Never docker0.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


def strip_tactics(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in dict(row).items() if k != "tactics"} for row in rows or ()]


def token_ratio(keep: int, ref: int) -> float:
    return round(int(keep) / max(1, int(ref)), 4)


def high_p_ids(
    probs: Mapping[str, Any],
    *,
    tau: float,
    fallback: Any = None,
) -> list[str]:
    high = [str(hid) for hid, p in dict(probs or {}).items() if float(p) >= float(tau)]
    if not high and fallback:
        high = [str(fallback)]
    return high


def apply_keepbest(
    evals: Sequence[Mapping[str, Any]],
    keep_tokens: int,
    *,
    trial: str = "",
) -> tuple[Optional[dict[str, Any]], int, str]:
    """If a shorter lake-ok eval exists, return (hit, new_tokens, body)."""

    hit = accept_keepbest(evals, keep_tokens)
    if not hit:
        return None, int(keep_tokens), str(trial or "")
    body = str(hit.get("tactics") or trial or "")
    return hit, int(hit.get("token_count") or keep_tokens), body


def pick_min(
    items: Sequence[Any],
    *,
    valid_fn: Any,
    key_fn: Any,
    fallback_fn: Optional[Any] = None,
) -> Optional[Any]:
    """Min valid item by key_fn; else fallback_fn(items) or first item."""

    rows = list(items or ())
    valid = [item for item in rows if valid_fn(item)]
    if valid:
        return sorted(valid, key=key_fn)[0]
    if fallback_fn is not None:
        hit = fallback_fn(rows)
        if hit is not None:
            return hit
    return rows[0] if rows else None


def pick_min_tiers(
    items: Sequence[Any],
    tiers: Sequence[Any],
    *,
    key_fn: Any,
    fallback_fn: Optional[Any] = None,
) -> Optional[Any]:
    """First non-empty pred in tiers, then min by key_fn. Else fallback_fn(items)."""

    rows = list(items or ())
    for pred in tiers or ():
        kept = [item for item in rows if pred(item)]
        if kept:
            return sorted(kept, key=key_fn)[0]
    if fallback_fn is not None:
        return fallback_fn(rows)
    return rows[0] if rows else None


def div_ratio(candidate: float, reference: float) -> float:
    if float(reference) <= 0:
        return 1.0 if float(candidate) <= 0 else float("inf")
    return float(candidate) / float(reference)


def accept_keepbest(
    evals: Sequence[Mapping[str, Any]],
    keep_tokens: int,
    *,
    ok_key: str = "theorem_ok",
    token_key: str = "token_count",
) -> Optional[dict[str, Any]]:
    """Shortest lake-ok eval strictly under keep_tokens. None if none."""

    valid = [dict(row) for row in evals or () if row.get(ok_key)]
    if not valid:
        return None
    best = min(valid, key=lambda row: int(row.get(token_key) or 10**9))
    if int(best.get(token_key) or keep_tokens) < int(keep_tokens):
        return best
    return None


def extend_prefix(
    prefix: str,
    nxt: str,
    *,
    stop: str = "STOP",
    original: Optional[str] = None,
    case_token: str = "case ",
) -> str:
    """Append nxt, preferring original indent when it matches. No Lean tables."""

    if nxt == stop:
        return prefix
    src = nxt
    if original and original.strip() == nxt.strip():
        src = original
    if not str(prefix).strip():
        return src if src[:1] in {" ", "\t"} else f"  {src.strip()}"
    if src[:1] in {" ", "\t"}:
        return prefix.rstrip() + "\n" + src.rstrip()
    stripped = src.strip()
    case_indent = 2
    last = ""
    for line in prefix.splitlines():
        if line.strip().startswith(case_token):
            case_indent = len(line) - len(line.lstrip())
        if line.strip():
            last = line
    if stripped.startswith(case_token):
        return prefix.rstrip() + "\n" + (" " * case_indent) + stripped
    indent = len(last) - len(last.lstrip()) if last else case_indent + 2
    if last.strip().startswith(case_token):
        indent = case_indent + 2
    return prefix.rstrip() + "\n" + (" " * indent) + stripped


def merge_next_line_proposals(
    generated: Sequence[str],
    priority: Sequence[str],
    *,
    stop: str = "STOP",
    cap: int = 12,
    filter_fn: Optional[Callable[[Sequence[str]], Sequence[str]]] = None,
) -> list[str]:
    """Pad generated next-lines with priority extras and STOP. Filter is injected."""

    proposals = list(generated)
    for extra in list(priority)[: max(0, int(cap) - len(proposals) - 1)]:
        proposals.append(extra)
    if filter_fn is not None:
        proposals = list(filter_fn(proposals) or list(priority)[: int(cap)])
    if stop not in proposals:
        proposals.append(stop)
    return proposals


def minibatch_ids(
    remaining: Sequence[str],
    *,
    choice: Any = None,
    ranked: Sequence[Any] = (),
    rng: Any = None,
    k: int = 2,
) -> list[str]:
    """Unique ids: greedy choice, then top ranked, then rng, cap k."""

    allowed = [str(x) for x in remaining]
    allow = set(allowed)
    picked: list[str] = []
    if choice:
        picked.append(str(choice))
    if ranked:
        first = ranked[0]
        hid = str(first[0] if isinstance(first, (tuple, list)) else first)
        picked.append(hid)
    rest = [hid for hid in allowed if hid not in picked]
    if rest and rng is not None:
        picked.append(str(rng.choice(rest)))
    out: list[str] = []
    for hid in picked:
        if hid in allow and hid not in out:
            out.append(hid)
        if len(out) >= max(1, int(k)):
            break
    return out


def metropolis_token_accept(
    *,
    old_tok: int,
    new_tok: int,
    temperature: float,
    rng: random.Random,
) -> bool:
    """Accept shorter always; longer with exp(-Δ / T)."""

    if int(new_tok) < int(old_tok):
        return True
    if float(temperature) <= 0:
        return int(new_tok) == int(old_tok)
    delta = int(new_tok) - int(old_tok)
    return rng.random() < math.exp(-delta / max(float(temperature), 1e-6))


COMPILE_KEYS = ("ok", "theorem_ok", "module_exit_0", "exit_code", "token_count", "errors", "wall_ms")


def should_call_generator(
    answers: Optional[Mapping[str, Any]],
    rec: Mapping[str, Any],
    *,
    long_proof: int = 400,
    longer_proof: int = 800,
    family_conf: float = 0.5,
    tight: float = 0.8,
    shorter: float = 1.0,
    hammer: float = 0.7,
    spend_low: float = 0.4,
    spend: float = 0.45,
    calc_keep: float = 0.6,
    aesop: float = 0.6,
    physlib: str = "physlib",
    putnam: str = "putnambench",
    custom: str = "custom",
) -> bool:
    """Whether a generator should run. Loop v1 still keys off docker0 /health."""

    proof = int(rec.get("proof_length") or 0)
    if answers is None:
        return proof >= int(long_proof)
    if float(answers.get("family_confidence") or 0) < family_conf:
        return proof >= int(longer_proof)
    if float(answers.get("reference_already_tight") or 0) >= tight and float(answers.get("likely_shorter") or 0) < shorter:
        return False
    if float(answers.get("hammer_before_llm") or 0) >= hammer and float(answers.get("spend_llm") or 0) < spend_low:
        return False
    source = str(rec.get("source") or "")
    if source == physlib and float(answers.get("calc_structure_worth_keeping") or 0) >= calc_keep:
        return True
    if source == putnam and float(answers.get("putnam_aesop_plausible") or 0) >= aesop:
        return float(answers.get("spend_llm") or 0) >= spend
    return float(answers.get("spend_llm") or 0) >= spend or answers.get("family") == custom


def coordinate_rounds(
    holes: Sequence[Any],
    *,
    rounds: int,
    choose_fn: Callable[..., Sequence[str]],
    trial_fn: Callable[[Sequence[str]], str],
    eval_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    accept_fn: Callable[[Sequence[Mapping[str, Any]], int, str], tuple[Optional[Mapping[str, Any]], int, str]],
    keep_tokens: int,
    keep_body: str,
    hole_id_fn: Callable[[Any], str] = lambda hole: str(getattr(hole, "hole_id", hole)),
    history: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Jev-guided coordinate descent. choose/trial/eval/accept are injected."""

    dropped: set[str] = set()
    if history is None:
        history = []
    rounds_out: list[dict[str, Any]] = []
    keep = keep_body
    tokens = int(keep_tokens)
    for round_i in range(1, max(1, int(rounds)) + 1):
        remaining = [hole for hole in holes if hole_id_fn(hole) not in dropped]
        if not remaining:
            break
        minibatch = list(choose_fn(remaining, dropped, round_i) or [])
        if not minibatch:
            break
        trial = trial_fn(list(dropped) + minibatch)
        evals = list(eval_fn(trial) or [])
        accepted, tokens, body = accept_fn(evals, tokens, trial)
        if accepted:
            keep = body
            dropped.update(minibatch)
        history.append(
            {
                "round": round_i,
                "minibatch": minibatch,
                "accepted": bool(accepted),
                "keep_tokens": tokens,
            }
        )
        rounds_out.append(
            {
                "round": round_i,
                "minibatch": minibatch,
                "evals": evals,
                "accepted": accepted,
                "keep_tokens": tokens,
            }
        )
    return {
        "keep": keep,
        "keep_tokens": tokens,
        "dropped": sorted(dropped),
        "history": history,
        "rounds": rounds_out,
        "arena_score": None,
    }


def compile_variant_rows(
    pairs: Sequence[tuple[str, str]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    *,
    head_n: int = 240,
    skip_seen: bool = True,
) -> list[dict[str, Any]]:
    """Compile labeled tactic variants. compile_fn is injected. Lake is the oracle."""

    from jevops.outer import head_chars

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, body in pairs:
        key = str(body or "").strip("\n")
        if skip_seen and key in seen and label != "reference":
            continue
        seen.add(key)
        compiled = dict(compile_fn(body) or {})
        rows.append(
            {
                "kind": label,
                "n_chars": len(body),
                "tactics_head": head_chars(body, head_n),
                **{k: compiled.get(k) for k in COMPILE_KEYS},
            }
        )
    return rows


def first_line(
    text: str,
    *,
    stop_pred: Any,
    skip_pred: Optional[Any] = None,
    keep_pred: Optional[Any] = None,
    default: str = "STOP",
) -> str:
    """First kept line, or default. stop/skip/keep predicates on stripped text."""

    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stop_pred(stripped):
            return default
        if skip_pred is not None and skip_pred(stripped):
            continue
        if keep_pred is None or keep_pred(stripped):
            return line.rstrip()
    return default


def after_item(seq: Sequence[Any], sentinel: Any) -> list[Any]:
    """Items after the first occurrence of sentinel (sentinel itself excluded)."""

    out: list[Any] = []
    seen = False
    for item in seq:
        if not seen and item == sentinel:
            seen = True
            continue
        if seen:
            out.append(item)
    return out


def filter_used_later(
    lines: Sequence[str],
    *,
    maybe_drop: Any,
    name_fn: Any,
    used_fn: Any,
    extra_later: Sequence[str] = (),
    always_drop: Optional[Any] = None,
) -> list[str]:
    """Keep lines; drop maybe_drop unless name is used later (plus extra_later)."""

    extra = list(extra_later)
    out: list[str] = []
    rows = list(lines)
    for index, line in enumerate(rows):
        stripped = str(line).strip()
        if always_drop is not None and always_drop(stripped):
            continue
        if maybe_drop(stripped):
            later = "\n".join(list(rows[index + 1 :]) + extra)
            if used_fn(name_fn(stripped), later):
                out.append(str(line))
            continue
        out.append(str(line))
    return out


def missing_occurrences(have_lines: Sequence[str], want_lines: Sequence[str]) -> list[str]:
    """want_lines not yet covered by have_lines, counting indent-sensitive copies."""

    have: dict[str, int] = {}
    for line in have_lines:
        key = str(line).rstrip()
        if not key.strip():
            continue
        have[key] = have.get(key, 0) + 1
    seen: dict[str, int] = {}
    out: list[str] = []
    for line in want_lines:
        key = str(line).rstrip()
        seen[key] = seen.get(key, 0) + 1
        if have.get(key, 0) < seen[key]:
            out.append(str(line))
    return out


def trim_trailing_unused(names: Sequence[str], later: Any) -> list[str]:
    """Drop trailing names not in later."""

    bag = set(later or ())
    trimmed = list(names)
    while trimmed and trimmed[-1] not in bag:
        trimmed.pop()
    return trimmed


def last_header_tag(
    text: str,
    prefix: str,
    *,
    split_on: str = "=>",
) -> Optional[str]:
    """Last header token after ``prefix``, optional split_on (e.g. case … =>)."""

    tag: Optional[str] = None
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix) :]
        if split_on and split_on in rest:
            rest = rest.split(split_on, 1)[0]
        tag = rest.split()[0] if rest.split() else None
    return tag


def unused_items(prefix: str, vocab: Sequence[str], *, stop: str = "STOP") -> list[str]:
    """Keep vocab entries not already present as stripped prefix lines."""

    present = {line.strip() for line in str(prefix or "").splitlines() if line.strip()}
    out: list[str] = []
    for item in vocab:
        if str(item).strip() in present and item != stop:
            continue
        out.append(str(item))
    return out


def compile_head_row(
    kind: str,
    body: str,
    compiled: Mapping[str, Any],
    *,
    extra: Optional[Mapping[str, Any]] = None,
    keys: Sequence[str] = COMPILE_KEYS,
) -> dict[str, Any]:
    from jevops.outer import head_chars

    row = {
        "kind": kind,
        "generator": "deterministic",
        "n_chars": len(body),
        "tactics_head": head_chars(body, 240),
        **{k: compiled.get(k) for k in keys},
    }
    if extra:
        row.update(dict(extra))
    return row


def _hole_id(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("hole_id") or "")
    return str(getattr(item, "hole_id", "") or "")


def _hole_family(item: Any) -> Any:
    if isinstance(item, Mapping):
        return item.get("family")
    return getattr(item, "family", None)


def _hole_original(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("original") or "")
    return str(getattr(item, "original", "") or "")


def ablate_then_combine(
    text: str,
    holes: Sequence[Any],
    *,
    apply_fn: Any,
    fill_fn: Any,
    compile_fn: Any,
) -> list[dict[str, Any]]:
    """Drop one hole at a time, then combine lake-ok drops. compile_fn injected."""

    rows: list[dict[str, Any]] = []
    droppable: list[Any] = []
    for hole in holes:
        hid = _hole_id(hole)
        fills = {
            _hole_id(item): (fill_fn(item) if _hole_id(item) == hid else _hole_original(item))
            for item in holes
        }
        body = apply_fn(text, fills)
        compiled = dict(compile_fn(body) or {})
        rows.append(
            compile_head_row(
                f"ablate_{hid}",
                body,
                compiled,
                extra={"hole_id": hid, "family": _hole_family(hole)},
            )
        )
        if compiled.get("theorem_ok"):
            droppable.append(hole)
    if len(droppable) >= 2:
        drop_ids = {_hole_id(item) for item in droppable}
        fills = {
            _hole_id(item): (fill_fn(item) if _hole_id(item) in drop_ids else _hole_original(item))
            for item in holes
        }
        combined = apply_fn(text, fills)
        compiled = dict(compile_fn(combined) or {})
        rows.append(
            compile_head_row(
                "ablate_combine_droppable",
                combined,
                compiled,
                extra={
                    "n_droppable": len(droppable),
                    "droppable_ids": [_hole_id(item) for item in droppable],
                },
            )
        )
    return rows


def unique_cap(
    items: Sequence[Any],
    *,
    cap: int,
    empty: str = "STOP",
) -> list[Any]:
    """Unique stripped items, cap length. Empty strings become ``empty``."""

    unique: list[Any] = []
    seen: set[str] = set()
    for item in items or ():
        key = str(item).strip() or str(empty)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item if str(item).strip() else empty)
        if len(unique) >= int(cap):
            break
    if not unique:
        unique = [empty]
    return unique


def pin_then_rank(
    ids: Sequence[str],
    probs: Mapping[str, Any],
    *,
    first: Any = None,
) -> list[str]:
    """Sort ids by probability desc, then pin ``first`` to the front if present."""

    ranked = sorted((str(x) for x in ids), key=lambda key: float(probs.get(key) or 0.0), reverse=True)
    pick = str(first) if first is not None else ""
    if pick and pick in ranked:
        ranked.remove(pick)
        ranked.insert(0, pick)
    return ranked


def pin_front(order: Sequence[Any], prefer: Sequence[Any], *, n: Optional[int] = None) -> list[Any]:
    """Prefer[:n] first, then the rest of order. Membership is ``not in head``."""

    head = list(prefer) if n is None else list(prefer)[: max(0, int(n))]
    return head + [item for item in order if item not in head]


def unique_lines(
    lines: Sequence[str],
    *,
    stop: str = "STOP",
    pred: Optional[Any] = None,
) -> list[str]:
    kept: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = str(line).strip()
        if not stripped or stripped == stop or stripped in seen:
            continue
        if pred is not None and not pred(stripped):
            continue
        kept.append(str(line))
        seen.add(stripped)
    return kept


def empty_headers(
    prefix: str,
    tags: Sequence[str],
    *,
    present_fn: Any,
    body_fn: Any,
) -> list[str]:
    """Tags present in prefix whose body_fn returns empty."""

    return [str(tag) for tag in tags if present_fn(prefix, tag) and not body_fn(prefix, tag)]


def structure_complete(
    prefix: str,
    tags: Sequence[str],
    *,
    present_fn: Any,
    empty_fn: Any,
    remaining_fn: Any,
) -> bool:
    """True when every tag is present, nonempty, and remaining_fn is empty."""

    rows = [str(tag) for tag in tags or ()]
    if not rows:
        return True
    if any(not present_fn(prefix, tag) for tag in rows):
        return False
    if empty_fn(prefix, rows):
        return False
    return not any(remaining_fn(prefix, tag) for tag in rows)


def structure_status(
    prefix: str,
    tags: Sequence[str],
    *,
    present_fn: Any,
    remaining_fn: Any,
    empty_fn: Optional[Any] = None,
    open_fn: Optional[Any] = None,
) -> dict[str, Any]:
    """Missing / empty / unfinished header tags. present/remaining/empty fns injected."""

    rows = [str(tag) for tag in tags or ()]
    missing = [tag for tag in rows if not present_fn(prefix, tag)]
    remaining = {tag: list(remaining_fn(prefix, tag) or []) for tag in rows}
    unfinished = [tag for tag in rows if present_fn(prefix, tag) and remaining.get(tag)]
    empty = list(empty_fn(prefix, rows) if empty_fn is not None else [])
    earliest = next((tag for tag in rows if tag in missing or tag in unfinished or tag in empty), None)
    next_original = None
    if unfinished:
        rem = remaining.get(unfinished[0]) or []
        next_original = rem[0] if rem else None
    return {
        "tags": rows,
        "missing": missing,
        "empty": empty,
        "unfinished": unfinished,
        "remaining": remaining,
        "earliest": earliest,
        "open": open_fn(prefix) if open_fn is not None else None,
        "next_original": next_original,
    }


def guided_next(
    prefix: str,
    pack: Mapping[str, Any],
    *,
    header_of: Any,
    remaining_fn: Any,
    arm_lines_fn: Optional[Any] = None,
    closers: Sequence[str] = (),
) -> list[str]:
    """Priority next lines: missing headers, then unfinished arm, then closers."""

    present = {line.strip() for line in str(prefix or "").splitlines() if line.strip()}
    missing = list(pack.get("missing") or [])
    empty_arms = list(pack.get("empty") or [])
    unfinished = list(pack.get("unfinished") or [])
    out: list[str] = []

    def push(line: str) -> None:
        stripped = str(line).strip()
        if not stripped or stripped in present:
            return
        if line not in out:
            out.append(line)

    earliest = pack.get("earliest")
    if earliest and earliest in missing:
        header = header_of(str(earliest))
        if header:
            push(header)
        return out
    next_original = pack.get("next_original")
    if earliest and (earliest in empty_arms or earliest in unfinished):
        if next_original:
            out.append(str(next_original))
        else:
            rem = list(remaining_fn(str(earliest)) or [])
            if rem:
                out.append(str(rem[0]))
        return out
    if missing:
        open_tag = pack.get("open")
        if open_tag and arm_lines_fn is not None:
            for line in arm_lines_fn(str(open_tag)):
                push(line)
        for tag in missing:
            header = header_of(str(tag))
            if header:
                push(header)
        return out
    if empty_arms:
        tag = empty_arms[0]
        if arm_lines_fn is not None:
            for line in arm_lines_fn(str(tag)):
                push(line)
        return out
    for extra in closers:
        push(extra)
    return out


def filter_to_earliest(
    lines: Sequence[str],
    pack: Mapping[str, Any],
    *,
    header_of: Any,
    stop: str = "STOP",
    closer_pred: Optional[Any] = None,
    header_match: Optional[Any] = None,
    tag_token_fn: Optional[Any] = None,
) -> list[str]:
    """Keep candidates that fill the earliest unfinished header, not later ones."""

    earliest = pack.get("earliest")
    if not earliest:
        return unique_lines(lines, stop=stop, pred=closer_pred)
    missing = set(pack.get("missing") or [])
    empty = set(pack.get("empty") or [])
    unfinished = set(pack.get("unfinished") or [])
    allowed: set[str] = set()
    nxt_raw = str(pack.get("next_original") or "")
    nxt = nxt_raw.strip()
    if earliest in missing:
        header = header_of(str(earliest)) or ""
        if header:
            allowed.add(str(header).strip())
        if tag_token_fn is not None:
            allowed.add(str(tag_token_fn(earliest)))
    elif earliest in empty or earliest in unfinished:
        if nxt:
            allowed.add(nxt)
            allowed.add(nxt_raw.rstrip())
    kept: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = str(line).strip()
        if not stripped or stripped == stop or stripped in seen:
            continue
        ok = False
        if earliest in missing:
            ok = bool(header_match(stripped, earliest)) if header_match is not None else stripped in allowed
        elif allowed:
            ok = stripped in allowed or any(stripped == item or item in stripped for item in allowed)
        if ok:
            kept.append(str(line))
            seen.add(stripped)
    return kept


def weighted_sum(*pairs: tuple[float, float]) -> float:
    """Sum of weight×value pairs."""

    return sum(float(weight) * float(value) for weight, value in pairs)


def count_matches(text: str, pattern: Any) -> int:
    """Number of regex findall hits. Empty/non-str → 0."""

    if not isinstance(text, str) or not text:
        return 0
    return len(pattern.findall(text))


def proposal_bag(
    *,
    seed: str = "",
    accept_fn: Optional[Any] = None,
) -> tuple[Any, list[dict[str, str]]]:
    """Unique shorter-edit bag. accept_fn(text)->bool is optional (e.g. keep locked names)."""

    seen: set[str] = set()
    seed_text = str(seed or "").strip("\n")
    if seed_text:
        seen.add(seed_text)
    rows: list[dict[str, str]] = []

    def push(kind: str, body: str, note: str = "", *, accept: bool = True) -> bool:
        text = str(body or "").strip("\n")
        if not text or text in seen:
            return False
        if accept and accept_fn is not None and not accept_fn(text):
            return False
        seen.add(text)
        rows.append({"kind": str(kind), "tactics": text, "note": str(note)})
        return True

    return push, rows


def parse_marked_list(
    text: str,
    *,
    start_prefix: str,
    line_re: Any,
    flag_needles: Sequence[str] = (),
    extra_if_flagged: Sequence[str] = (),
    skip: Sequence[str] = ("", "[]"),
    groups: Sequence[str] = ("bracket", "bare"),
) -> tuple[list[str], bool]:
    """Unique names from a printed list that starts after ``start_prefix`` lines."""

    blob = str(text or "")
    flagged = any(needle in blob for needle in flag_needles)
    names: list[str] = []
    seen: set[str] = set()
    printed = False
    skip_set = {str(item) for item in skip}
    for raw_line in blob.splitlines():
        line = raw_line.strip()
        if str(start_prefix) and line.startswith(str(start_prefix)):
            printed = True
            continue
        for needle in flag_needles:
            if needle in line and needle not in seen:
                names.append(str(needle))
                seen.add(str(needle))
                flagged = True
        if not printed:
            continue
        match = line_re.match(line)
        if match is None:
            continue
        payload = ""
        for group in groups:
            got = match.group(group)
            if got is not None:
                payload = got
                break
        for item in str(payload).split(","):
            name = item.strip()
            if name in skip_set or name in seen:
                continue
            names.append(name)
            seen.add(name)
    if flagged:
        for extra in extra_if_flagged:
            if extra not in seen:
                names.append(str(extra))
                seen.add(str(extra))
    return names, flagged


def index_order(
    n: int,
    probs: Mapping[str, Any],
    *,
    prefix: str = "p",
    pick: str = "",
) -> list[int]:
    """Sort 0..n-1 by ``{prefix}{i}`` probability desc, then pin ``pick``."""

    count = max(0, int(n))
    order = sorted(range(count), key=lambda i: float(probs.get(f"{prefix}{i}") or 0.0), reverse=True)
    token = str(pick or "")
    if token.startswith(prefix) and token[len(prefix) :].isdigit():
        idx = int(token[len(prefix) :])
        if idx in order:
            order.remove(idx)
            order.insert(0, idx)
    return order


def name_match_score(
    query: str,
    symbol: str,
    *,
    source: str = "",
    weights: Optional[Mapping[str, float]] = None,
    default: float = 0.4,
) -> float:
    q = str(query or "").casefold()
    s = str(symbol or "").casefold()
    if s == q:
        base = 1.0
    elif s.endswith("." + q) or s.endswith("/" + q) or s.rsplit(".", 1)[-1] == q:
        base = 0.9
    elif s.startswith(q):
        base = 0.8
    elif q in s:
        base = 0.55
    else:
        base = 0.15
    weight = float((weights or {}).get(source, default)) if weights is not None else float(default)
    return round(base * weight, 4)


def hit_row(
    symbol: str,
    *,
    source: str,
    query: str,
    path: str = "",
    extra: Optional[Mapping[str, Any]] = None,
    weights: Optional[Mapping[str, float]] = None,
    ptr_fn: Optional[Any] = None,
    default: float = 0.4,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol,
        "source": source,
        "path": path,
        "score": name_match_score(query, symbol, source=source, weights=weights, default=default),
        "ptr": ptr_fn(symbol) if ptr_fn is not None else "",
    }
    if extra:
        row.update(dict(extra))
    return row


def rank_hits(
    hits: Sequence[Mapping[str, Any]],
    *,
    limit: int = 16,
    key_fn: Optional[Any] = None,
) -> list[dict[str, Any]]:
    def _key(row: Mapping[str, Any]) -> tuple[str, str]:
        return (str(row.get("symbol") or ""), str(row.get("source") or ""))

    key = key_fn or _key
    seen: set[Any] = set()
    ranked = sorted(
        list(hits or ()),
        key=lambda row: (-float(row.get("score") or 0.0), str(row.get("symbol") or "")),
    )
    out: list[dict[str, Any]] = []
    for row in ranked:
        item = dict(row)
        token = key(item)
        if token in seen:
            continue
        seen.add(token)
        out.append(item)
        if len(out) >= int(limit):
            break
    return out


def search_rg(
    query: str,
    *,
    root: Any,
    ident_re: Any,
    timeout: float = 4.0,
    cap: int = 24,
    globs: Sequence[str] = ("*.py",),
    hit_fn: Optional[Any] = None,
    rg: Optional[str] = None,
) -> tuple[list[dict[str, Any]], str]:
    import shutil

    from jevops.outer import head_chars, run_process

    binary = rg or shutil.which("rg")
    if not binary:
        return [], "rg_missing"
    match = ident_re.search(query) if ident_re is not None else None
    needle = match.group(0) if match else head_chars(query, 40)
    if not needle:
        return [], "empty_query"
    argv = [str(binary), "-n"]
    for glob in globs:
        argv.extend(["--glob", str(glob)])
    argv.extend(["-e", needle, str(root)])
    try:
        ran = run_process(argv, timeout=float(timeout))
    except OSError:
        return [], "rg_failed"
    if ran.get("timeout"):
        return [], "rg_failed"
    hits: list[dict[str, Any]] = []
    for line in str(ran.get("stdout") or "").splitlines()[: max(0, int(cap))]:
        parts = line.split(":", 2)
        path = Path(parts[0]).name if parts else ""
        snippet = parts[-1].strip() if parts else line
        ident = ident_re.search(snippet) if ident_re is not None else None
        symbol = ident.group(0) if ident else needle
        if hit_fn is not None:
            hits.append(hit_fn(symbol, path=path, snippet=head_chars(snippet, 160)))
        else:
            hits.append({"symbol": symbol, "path": path, "line": head_chars(snippet, 160)})
    return hits, "rg"


def expand_beam(
    items: Sequence[Any],
    *,
    stopped_fn: Any,
    expand_fn: Any,
    cap: int,
) -> list[Any]:
    """Keep stopped items; else extend with expand_fn(item). Cap the next beam."""

    nxt: list[Any] = []
    for item in items or ():
        if stopped_fn(item):
            nxt.append(item)
            continue
        kids = expand_fn(item)
        if kids is None:
            nxt.append(item)
            continue
        nxt.extend(list(kids))
    return nxt[: max(0, int(cap))]


def beam_until(
    items: Sequence[Any],
    *,
    max_steps: int,
    stopped_fn: Any,
    round_fn: Any,
) -> list[Any]:
    """Repeat round_fn(current, step) until every item is stopped or max_steps."""

    current = list(items or ())
    for step in range(max(0, int(max_steps))):
        if all(stopped_fn(item) for item in current):
            break
        current = list(round_fn(current, step) or current)
    return current


def run_prefix_beam(
    prefix0: str,
    *,
    max_steps: int,
    beam_n: int,
    stop_token: str = "STOP",
    pack_fn: Callable[[str], Mapping[str, Any]],
    stop_allowed_fn: Callable[[str], bool],
    propose_fn: Callable[..., Sequence[str]],
    prune_fn: Callable[..., Mapping[str, Any]],
    extend_fn: Callable[..., str],
    filter_fn: Callable[..., Sequence[str]],
    n_samples: int = 1,
    item_cls: Any = None,
) -> dict[str, Any]:
    """PCA-prefix beam. generate/prune/filter are injected. Never docker0 here."""

    from jevops.outer import unique_rows
    from jevops.tactics import BeamItem

    cls = item_cls or BeamItem
    items = [cls(prefix=prefix0)]
    trace: list[dict[str, Any]] = []
    local_calls = 0
    cap = max(1, int(beam_n))

    def _stopped(item: Any) -> bool:
        return bool(getattr(item, "stopped", False))

    def _expand(item: Any, step: int) -> list[Any]:
        nonlocal local_calls
        pack = dict(pack_fn(item.prefix) or {})
        if stop_allowed_fn(item.prefix):
            trace.append(
                {
                    "step": step,
                    "stop_exhausted": True,
                    "earliest_unfinished": pack.get("earliest_unfinished"),
                }
            )
            return [cls(prefix=item.prefix, steps=list(item.steps), stopped=True, score=item.score)]
        proposals = list(propose_fn(item, pack) or [])
        local_calls += max(1, int(n_samples))
        pruned = dict(prune_fn(item, proposals, pack) or {})
        kept_lines = list(pruned.get("kept") or [stop_token])
        filtered = list(filter_fn([line for line in kept_lines if line != stop_token], pack) or [])
        kept_lines = filtered or list(filter_fn(proposals, pack) or [])[:cap] or [stop_token]
        pruned["kept"] = kept_lines
        pruned["stop_blocked"] = True
        trace.append(
            {
                "step": step,
                "prefix_lines": str(item.prefix).count("\n") + 1,
                "missing_cases": pack.get("missing_cases"),
                "empty_arms": pack.get("empty_arms"),
                "earliest_unfinished": pack.get("earliest_unfinished"),
                "next_original": pack.get("next_original"),
                "open_case": pack.get("open_case"),
                "proposals": proposals[:12],
                "typesafe": {k: pruned.get(k) for k in ("skipped", "reason", "best", "kept", "confidence")},
            }
        )
        return [
            cls(
                prefix=extend_fn(item.prefix, nxt, pack),
                steps=list(item.steps) + [nxt],
                stopped=nxt == stop_token,
                score=item.score,
            )
            for nxt in kept_lines
        ]

    def _round(current: list[Any], step: int) -> list[Any]:
        return expand_beam(current, stopped_fn=_stopped, expand_fn=lambda item: _expand(item, step), cap=cap)

    items = beam_until(items, max_steps=max_steps, stopped_fn=_stopped, round_fn=_round)
    finals = unique_rows(
        [{"tactics": item.prefix.strip("\n"), "steps": item.steps, "stopped": item.stopped} for item in items],
        key_fn=lambda row: row["tactics"],
    )
    return {
        "items": items,
        "finals": finals,
        "trace": trace,
        "local_calls": local_calls,
        "pca_prefix": prefix0,
        "beam": cap,
        "max_steps": int(max_steps),
        "arena_score": None,
    }


def keepbest_candidates(
    *,
    reference: str,
    hosted: Optional[str] = None,
    flattened: Optional[str] = None,
    collapse: Optional[str] = None,
    span_drafts: Sequence[Any] = (),
    hosted_kind: str = "hosted_mistral",
    hosted_generator: str = "labs-leanstral-1-5",
    collapse_kind: str = "fanout_collapse_simp_at",
) -> list[dict[str, Any]]:
    """Assemble keep-best candidates. Does not compile. Jev does not write Lean."""

    from jevops.outer import field_of

    candidates: list[dict[str, Any]] = [
        {"kind": "reference", "generator": "deterministic", "tactics": reference},
    ]
    if hosted is not None:
        candidates.append({"kind": hosted_kind, "generator": hosted_generator, "tactics": hosted})
        if flattened is not None and flattened != hosted:
            candidates.append(
                {"kind": "hosted_indent_normalized", "generator": "deterministic", "tactics": flattened}
            )
    if collapse is not None and collapse != reference:
        candidates.append({"kind": collapse_kind, "generator": "deterministic", "tactics": collapse})
    for draft in span_drafts or ():
        tactics = str(field_of(draft, "tactics", default="") or "")
        if tactics == reference:
            continue
        ops = list(field_of(draft, "ops", default=()) or ())
        draft_id = field_of(draft, "draft_id", "id", default="")
        family = field_of(draft, "family", default="")
        candidates.append(
            {
                "kind": f"span_{draft_id}_{ops[-1] if ops else family}",
                "generator": "deterministic",
                "tactics": tactics,
                "ops": ops,
            }
        )
    return candidates


def compile_labeled(
    candidates: Sequence[Mapping[str, Any]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Compile labeled tactic candidates. compile_fn is injected. Lake is the oracle."""

    rows: list[dict[str, Any]] = []
    tactics_by_kind = {str(item["kind"]): str(item.get("tactics") or "") for item in candidates}
    for item in candidates:
        rows.append(dict(row_fn(item, compile_fn(str(item.get("tactics") or "")))))
    return rows, tactics_by_kind


def beats_reference(
    rows: Sequence[Mapping[str, Any]],
    ref_tokens: int,
    *,
    skip_kind: str = "reference",
    ok_key: str = "module_exit_0",
    token_key: str = "token_count",
) -> bool:
    """True when a non-reference row is lake-ok and strictly shorter."""

    limit = int(ref_tokens)
    return any(
        row.get(ok_key) and int(row.get(token_key) or limit) < limit
        for row in rows or ()
        if str(row.get("kind") or "") != skip_kind
    )


def keepbest_kept(kept: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if kept is None:
        return None
    return {
        "kind": kept.get("kind"),
        "ok": kept.get("ok"),
        "theorem_ok": kept.get("theorem_ok"),
        "module_exit_0": kept.get("module_exit_0"),
        "token_count": kept.get("token_count"),
    }


def filter_blacklist(
    proposals: Sequence[Mapping[str, Any]],
    *,
    failed_bodies: Optional[set[str]] = None,
    failed_kinds: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    bodies = failed_bodies or set()
    kinds = failed_kinds or set()
    return [
        dict(item)
        for item in proposals or ()
        if str(item.get("tactics") or "") not in bodies and str(item.get("kind") or "") not in kinds
    ]


def kind_prefix_indices(proposals: Sequence[Mapping[str, Any]], prefixes: Sequence[str]) -> list[int]:
    heads = tuple(str(p) for p in prefixes or ())
    return [
        index
        for index, item in enumerate(proposals or ())
        if str(item.get("kind") or "").startswith(heads)
    ]


def mcmc_chains(start: str, start_tok: int, start_ok: bool, beam: int, cls: Any) -> list[Any]:
    return [cls(tactics=start, tokens=int(start_tok), theorem_ok=bool(start_ok)) for _ in range(max(1, int(beam)))]


def init_mcmc_best(
    *,
    start: str,
    start_ok: bool,
    start_tok: int,
    reference: str,
    ref_tok: int,
    kind: str,
) -> dict[str, Any]:
    if start_ok:
        return {"kind": kind, "tactics": start, "token_count": int(start_tok), "theorem_ok": True}
    return {"kind": "reference", "tactics": reference, "token_count": int(ref_tok), "theorem_ok": True}


def mcmc_try_proposals(
    *,
    proposals: Sequence[Mapping[str, Any]],
    order: Sequence[Any],
    chain: Any,
    compile_fn: Callable[[str], Mapping[str, Any]],
    token_fn: Callable[[str], int],
    accept_fn: Callable[..., bool],
    best: dict[str, Any],
    failed_bodies: set[str],
    failed_kinds: set[str],
    sticky_fail: set[str],
    round_i: int,
    chain_i: int,
    history: list[dict[str, Any]],
    ranked_meta: Mapping[str, Any],
    temperature: float,
    rng: Any,
    n_try: int = 3,
) -> Optional[dict[str, Any]]:
    """Compile up to n_try ranked proposals; MH-accept into chain. Lake is the oracle."""

    from jevops.outer import head_seq

    tried: Optional[dict[str, Any]] = None
    for idx in head_seq(order, n_try):
        if int(idx) >= len(proposals):
            continue
        cand = proposals[int(idx)]
        compiled = dict(compile_fn(str(cand.get("tactics") or "")) or {})
        ok = bool(compiled.get("theorem_ok"))
        tok = int(compiled.get("token_count") or token_fn(str(cand.get("tactics") or "")))
        accept = False
        reason = "reject_invalid"
        if ok:
            accept = bool(
                accept_fn(old_tok=chain.tokens, new_tok=tok, temperature=temperature, rng=rng)
            )
            reason = "accept" if accept else "reject_mh"
            if tok < int(best.get("token_count") or tok + 1):
                best["kind"] = f"mcmc_r{round_i}_c{chain_i}_{cand.get('kind')}"
                best["tactics"] = cand.get("tactics")
                best["token_count"] = tok
                best["theorem_ok"] = True
        tried = {
            "round": round_i,
            "chain": chain_i,
            "kind": cand.get("kind"),
            "note": cand.get("note"),
            "ok": ok,
            "tokens": tok,
            "accept": accept,
            "reason": reason,
            "typesafe": {k: ranked_meta.get(k) for k in ("pick", "likely_compiles", "likely_shorter", "skipped")},
            "errors": head_seq(compiled.get("errors"), 1),
        }
        history.append(tried)
        if not ok:
            failed_bodies.add(str(cand.get("tactics") or ""))
            if str(cand.get("kind") or "") in sticky_fail:
                failed_kinds.add(str(cand.get("kind") or ""))
        if accept and ok:
            chain.tactics = str(cand.get("tactics") or "")
            chain.tokens = tok
            chain.theorem_ok = True
            chain.trace.append(tried)
            break
    return tried


def mcmc_result(
    *,
    rounds: int,
    beam: int,
    temperature: float,
    seed: int,
    lake_calls: int,
    leanstral_calls: int,
    best: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    extra: Optional[Mapping[str, Any]] = None,
    head_n: int = 400,
) -> dict[str, Any]:
    from jevops.outer import head_chars

    out: dict[str, Any] = {
        "mode": "mcmc_beam",
        "rounds": int(rounds),
        "beam": max(1, int(beam)),
        "mh_temperature": float(temperature),
        "seed": int(seed),
        "lake_calls": int(lake_calls),
        "leanstral_calls": int(leanstral_calls),
        "best": {k: best.get(k) for k in ("kind", "token_count", "theorem_ok")},
        "best_tactics": str(best.get("tactics") or ""),
        "best_tactics_head": head_chars(best.get("tactics") or "", head_n),
        "history": list(history or ()),
        "called_docker0": False,
        "called_hosted_mistral": False,
        "official_track2": False,
        "arena_score": None,
        "jev_generated_lean": False,
    }
    if extra:
        out.update(dict(extra))
    return out


def compile_variant_evals(
    pairs: Sequence[tuple[str, str]],
    compile_fn: Callable[[str, str], Mapping[str, Any]],
    *,
    label_key: str = "hammer",
) -> list[dict[str, Any]]:
    """Compile labeled tactic variants into eval rows. compile_fn is injected."""

    rows: list[dict[str, Any]] = []
    for label, body in pairs:
        compiled = dict(compile_fn(str(label), str(body)) or {})
        rows.append(
            {
                label_key: label,
                "tactics": body,
                "token_count": compiled.get("token_count"),
                "theorem_ok": compiled.get("theorem_ok"),
                "exit_code": compiled.get("exit_code"),
                "errors": compiled.get("errors"),
                "n_chars": len(body),
            }
        )
    return rows


def sample_next_lines(
    n_samples: int,
    *,
    generate_fn: Callable[[], Any],
    parse_fn: Callable[[Any], str],
    empty: str,
) -> list[str]:
    """Sample next-line proposals. generate_fn returning None yields ``empty``."""

    proposals: list[str] = []
    for _ in range(max(0, int(n_samples))):
        raw = generate_fn()
        if raw is None:
            proposals.append(empty)
        else:
            proposals.append(parse_fn(raw))
    return proposals


def unique_pin_cap(
    items: Sequence[Any],
    pick: Any,
    *,
    key_fn: Callable[[Any], Any],
    cap: int,
) -> list[Any]:
    """Pin matching pick first, then unique-by-key, then cap. No Lean."""

    from jevops.outer import unique_rows

    rows = list(items or ())
    if pick not in (None, ""):
        prefer = [item for item in rows if key_fn(item) == pick]
        rows = pin_front(rows, prefer, n=1)
    return unique_rows(rows, key_fn=key_fn)[: max(0, int(cap))]


def first_ident(text: str, ident_re: Any) -> str:
    found = ident_re.findall(str(text or "")) if ident_re is not None else []
    return str(found[0]) if found else ""


def collect_source_hits(
    steps: Sequence[tuple[str, Any]],
    *,
    fail_notes: Optional[Mapping[str, str]] = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Run named search steps. Each fn returns hits or (hits, note). JSON-LD first."""

    from jevops.outer import exc_name

    notes = dict(fail_notes or {})
    sources: dict[str, str] = {}
    hits: list[dict[str, Any]] = []
    for name, fn in steps or ():
        try:
            out = fn()
            if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], str):
                rows, note = out
                sources[str(name)] = str(note)
                hits.extend(list(rows or ()))
            else:
                hits.extend(list(out or ()))
                sources[str(name)] = "ok"
        except Exception as exc:  # noqa: BLE001 — search sources fail closed
            sources[str(name)] = str(notes.get(name) or exc_name(exc))
    return hits, sources


def credit_search_hits(
    memory: Optional[dict[str, Any]],
    ranked: Sequence[Mapping[str, Any]],
    *,
    n: int = 8,
    boost: float = 0.05,
) -> int:
    """Promote ranked hits onto the NCA grid. Cache hits never admit Lean."""

    if not isinstance(memory, dict) or not ranked:
        return 0
    from jevops.outer import head_seq

    grid = memory.setdefault("nca", {}).setdefault("grid", {})
    edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
    promoted = 0
    for hit in head_seq(ranked, n):
        cid = str(hit.get("ptr") or "")
        if not cid.startswith("ptr://"):
            symbol = str(hit.get("symbol") or "hit")
            cid = f"ptr://skill/{symbol}" if symbol.startswith("port_") else f"ptr://codepath/{symbol}"
        cell = grid.setdefault(
            cid,
            {
                "id": cid,
                "kind": "codepath" if "codepath" in cid else "skill",
                "energy": 0.4,
                "wins": 0,
                "losses": 0,
                "tick": 0,
            },
        )
        cell["energy"] = min(1.0, float(cell.get("energy") or 0.4) + float(boost) * float(hit.get("score") or 0.0))
        cell["path"] = hit.get("path")
        owners = [
            key
            for key in grid
            if str(key).startswith("ptr://task/") or str(key).startswith("ptr://theorem/")
        ]
        if owners:
            pair = [str(owners[0]), cid]
            if pair not in edges:
                edges.append(pair)
        promoted += 1
    return promoted


def pack_beam_search(
    out: Mapping[str, Any],
    *,
    prefix: str,
    vocab_n: int,
    mode: str,
    beam: int,
    temperature: float,
    max_steps: int,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    packed: dict[str, Any] = {
        "pca_prefix": prefix,
        "vocab_n": int(vocab_n),
        "mode": mode,
        "beam": int(beam),
        "temperature": float(temperature),
        "max_steps": int(max_steps),
        "local_calls": out.get("local_calls"),
        "finals": out.get("finals"),
        "trace": out.get("trace"),
        "called_hosted_mistral": False,
        "arena_score": None,
        "jev_generated_lean": False,
    }
    if extra:
        packed.update(dict(extra))
    return packed


def compile_then_hammer(
    candidates: Sequence[Mapping[str, Any]],
    *,
    compile_fn: Callable[[str], Mapping[str, Any]],
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    hammer_fn: Callable[..., tuple[list[dict[str, Any]], str, list[Any], bool]],
    needs_hammer_fn: Callable[[str], bool],
    grok_prefix: str = "grok",
) -> tuple[list[dict[str, Any]], bool, str, list[Any]]:
    """Compile labeled drafts, then hammer lake-invalid ones. Lake is the oracle."""

    rows: list[dict[str, Any]] = []
    grok_ok = False
    grok_tactics = ""
    grok_errors: list[Any] = []
    for item in candidates or ():
        compiled = dict(compile_fn(str(item.get("tactics") or "")) or {})
        rows.append(dict(row_fn(item, compiled)))
        kind = str(item.get("kind") or "")
        if kind.startswith(grok_prefix):
            if compiled.get("theorem_ok"):
                grok_ok = True
            else:
                grok_tactics = str(item.get("tactics") or "")
                grok_errors = list(compiled.get("errors") or [])
        if needs_hammer_fn(kind) and not compiled.get("theorem_ok"):
            hammer_rows, current, current_errors, hammer_ok = hammer_fn(kind, item, compiled)
            rows.extend(list(hammer_rows or ()))
            if kind.startswith(grok_prefix):
                grok_tactics = current
                grok_errors = list(current_errors or [])
                grok_ok = grok_ok or bool(hammer_ok)
            elif compiled.get("errors"):
                grok_errors = grok_errors or list(compiled.get("errors") or [])
    return rows, grok_ok, grok_tactics, grok_errors
