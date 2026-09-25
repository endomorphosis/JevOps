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


def choose_minibatch(
    remaining: Sequence[Any],
    jev: Optional[Mapping[str, Any]] = None,
    rng: Any = None,
    *,
    k: int = 2,
    id_fn: Optional[Callable[[Any], str]] = None,
) -> list[str]:
    """Unique hole ids from a Jev round: greedy choice, ranked, then rng."""

    from jevops.outer import ranked_pairs

    ident = id_fn or (lambda hole: str(getattr(hole, "hole_id", hole)))
    packed = dict(jev or {})
    return minibatch_ids(
        [ident(hole) for hole in remaining or ()],
        choice=packed.get("choice"),
        ranked=ranked_pairs(packed.get("probabilities")),
        rng=rng,
        k=k,
    )


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


def drive_ablate(
    record: Mapping[str, Any],
    tactics: str,
    holes: Sequence[Any],
    *,
    compile_fn: Callable[..., Mapping[str, Any]],
    apply_fn: Callable[..., str],
    fill_fn: Callable[[Any], str],
    state_root: Any,
    timeout: float,
    restore: bytes,
) -> list[dict[str, Any]]:
    """Drop one hole at a time, then combine lake-valid drops. ``compile_fn`` owns lake."""

    def _compile(body: str) -> Mapping[str, Any]:
        return compile_fn(record, body, state_root=state_root, timeout=timeout, restore=restore)

    return ablate_then_combine(
        tactics,
        holes,
        apply_fn=lambda text, fills: apply_fn(text, holes, fills),
        fill_fn=fill_fn,
        compile_fn=_compile,
    )


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


def keep_shortest_ok(
    rows: Sequence[Mapping[str, Any]],
    *,
    token_key: str = "token_count",
    kind_key: str = "kind",
    ok_key: str = "theorem_ok",
    prefer_kind: str = "reference",
) -> Optional[Mapping[str, Any]]:
    """Shortest lake-ok row, preferring ``prefer_kind`` on ties. Not an Arena score."""

    valid = [row for row in rows or () if row.get(ok_key)]
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda row: (
            int(row.get(token_key) or 10**9),
            0 if row.get(kind_key) == prefer_kind else 1,
        ),
    )[0]


def kept_view(
    kept: Optional[Mapping[str, Any]],
    keys: Sequence[str] = ("kind", "theorem_ok", "token_count"),
) -> Optional[dict[str, Any]]:
    if kept is None:
        return None
    return {key: kept.get(key) for key in keys}


def pack_mca_problem(
    *,
    schema: str,
    name: str,
    digest: str,
    n_holes: int,
    holes: Sequence[Any],
    skeleton_head: str,
    hardware_class: str,
    reference_token_count: int,
    beats_reference: bool,
    candidates: Sequence[Mapping[str, Any]],
    kept: Optional[Mapping[str, Any]],
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """MCA/mask-replace payload. Lake is the oracle. Not Track 2."""

    out: dict[str, Any] = {
        "schema": schema,
        "name": name,
        "warmup_jsonl_sha256": digest,
        "n_holes": int(n_holes),
        "holes": list(holes),
        "skeleton_head": skeleton_head,
        "called_docker0": False,
        "used_prototype_endpoint": False,
        "hardware_class": hardware_class,
        "reference_token_count": int(reference_token_count),
        "beats_reference": bool(beats_reference),
        "candidates": list(candidates),
        "kept": kept_view(kept),
        "arena_score": None,
        "official_track2": False,
    }
    if extra:
        out.update(dict(extra))
    out["arena_score"] = None
    out["official_track2"] = False
    out["called_docker0"] = False
    return out


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
        return pack_keep(kind=kind, tactics=start, token_count=start_tok, theorem_ok=True)
    return pack_keep(kind="reference", tactics=reference, token_count=ref_tok, theorem_ok=True)


def pack_keep(
    *,
    kind: str,
    tactics: str,
    token_count: int,
    theorem_ok: bool = True,
) -> dict[str, Any]:
    """Keep-best box. Lake still admits."""

    return {
        "kind": str(kind),
        "tactics": tactics,
        "token_count": int(token_count),
        "theorem_ok": bool(theorem_ok),
    }


def start_keep(
    tactics: str,
    compiled: Mapping[str, Any],
    *,
    token_fn: Callable[[str], int],
    kind: str = "init",
) -> dict[str, Any]:
    """Initial keep-best from a compile row."""

    from jevops.outer import first_int

    return pack_keep(
        kind=kind,
        tactics=tactics,
        token_count=first_int(compiled.get("token_count"), token_fn(tactics)),
        theorem_ok=bool(compiled.get("theorem_ok")),
    )


def keep_beats(
    best: Optional[Mapping[str, Any]],
    ref_tokens: int,
    *,
    ok_key: str = "theorem_ok",
    token_key: str = "token_count",
) -> bool:
    """True when keep is lake-ok and strictly shorter than the reference."""

    from jevops.outer import first_int

    row = best or {}
    return bool(row.get(ok_key)) and first_int(row.get(token_key)) < int(ref_tokens)


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


def drive_mcmc(
    record: Mapping[str, Any],
    *,
    rounds: int,
    beam: int,
    temperature: float,
    seed: int,
    state_root: Any,
    timeout: float,
    init_tactics: Optional[str],
    leanstral: bool,
    memory: Optional[dict[str, Any]],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    rng_cls: Callable[[int], Any],
    ledger_cls: Callable[..., Any],
    max_jev: int,
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[..., str],
    compile_fn: Callable[..., dict[str, Any]],
    token_fn: Callable[[str], int],
    chain_cls: Callable[..., Any],
    locked_fn: Callable[[str], Any],
    failed_kinds: set[str],
    leanstral_swap_fn: Callable[..., str],
    propose_fn: Callable[..., Sequence[Any]],
    rank_fn: Callable[..., Any],
    accept_fn: Callable[..., bool],
    max_leanstral: int,
    pin_prefixes: Sequence[str],
    hardware_class: str,
) -> dict[str, Any]:
    """Metropolis chain over tactic edits. ``compile_fn`` still owns lake."""

    from jevops.outer import bump_box, clone_restore, either, first_int, get_str, stripped_or, take_keys

    reference = tactic_fn(record)
    rng = rng_cls(first_int(seed))
    ledger = ledger_cls(
        name=f"{get_str(record, 'name')}#mcmc-beam",
        max_jev_calls=max_jev,
        max_mistral_calls=0,
        max_grok_calls=0,
    )
    _clone, _dest, restore = clone_restore(record, state_root, clone_fn=clone_fn, relpath_fn=relpath_fn)
    start = stripped_or(init_tactics, reference)
    start_compiled = compile_fn(record, start, state_root=state_root, timeout=timeout, restore=restore, memory=memory)
    packed = begin_mcmc(
        start=start,
        compiled=start_compiled,
        reference=reference,
        token_fn=token_fn,
        beam=beam,
        chain_cls=chain_cls,
        init_kind=either(init_tactics, lambda: "init", lambda: "reference"),
    )
    chains, best, history, leanstral_calls, failed_bodies, lake_calls = take_keys(
        packed, "chains", "best", "history", "leanstral_calls", "failed_bodies", "lake_calls"
    )
    counts = {"lake_calls": lake_calls}
    sticky_fail = set(failed_kinds)

    def _compile(body: str) -> dict[str, Any]:
        return bump_box(
            counts,
            "lake_calls",
            lambda: compile_fn(record, body, state_root=state_root, timeout=timeout, restore=restore, memory=memory),
        )

    leanstral_calls = run_mcmc_rounds(
        rounds=rounds,
        chains=chains,
        ledger=ledger,
        leanstral=leanstral,
        max_leanstral=max_leanstral,
        leanstral_fn=lambda tactics: leanstral_swap_fn(record, tactics, rng, locked_fn(reference)),
        propose_fn=lambda tactics, extra: propose_fn(tactics, reference, rng, extra=extra),
        filter_fn=filter_blacklist,
        rank_fn=lambda tactics, proposals: rank_fn(record, tactics, proposals, ledger=ledger),
        pin_fn=pin_front,
        pin_prefixes=pin_prefixes,
        try_fn=lambda **kwargs: mcmc_try_proposals(token_fn=token_fn, accept_fn=accept_fn, **kwargs),
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
        lake_calls=counts["lake_calls"],
        leanstral_calls=leanstral_calls,
        best=best,
        history=history,
        extra={"ledger": ledger.as_dict(), "hardware_class": hardware_class},
    )


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


def drive_propose_lines(
    record: Mapping[str, Any],
    item: Any,
    vocab: Sequence[str],
    *,
    beam: int,
    temperature: float,
    generate: Optional[Callable[..., str]],
    pack: Optional[Mapping[str, Any]],
    reference: str,
    guided_fn: Callable[..., Sequence[str]],
    unused_fn: Callable[[str, Sequence[str]], Sequence[str]],
    prompt_fn: Callable[..., str],
    docker0_fn: Callable[..., Any],
    refuse_fn: Callable[[Any], Any],
    parse_fn: Callable[[str], str],
    filter_fn: Callable[..., Sequence[str]],
    stop: str,
    sample_cap: int,
    candidate_cap: int,
    error_cls: type[BaseException],
) -> list[str]:
    """Sample next tactic lines, then merge with the guided vocabulary. Does not admit Lean."""

    from jevops.outer import call_if, either, get_str, or_call, overlay_map, sample_n

    pack = overlay_map(pack)
    priority = either(
        bool(reference),
        lambda: guided_fn(item.prefix, reference, pack),
        lambda: unused_fn(item.prefix, vocab),
    )
    prompt = prompt_fn(record, item.prefix, or_call(priority, unused_fn, item.prefix, vocab), pack)
    n_samples = sample_n(beam, sample_cap)

    def _one() -> Any:
        def _docker0() -> Any:
            result = docker0_fn(
                prompt,
                source=get_str(record, "source"),
                allow_owner_exec=False,
                temperature=temperature,
                stop=["\n\n"],
            )

            def _accept() -> Any:
                refuse_fn(result.identity)
                return result.text

            return call_if(not result.skipped and result.text, _accept)

        return either(generate is not None, lambda: generate(prompt, temperature=temperature), _docker0)

    proposals = sample_next_lines(n_samples, generate_fn=_one, parse_fn=parse_fn, empty=stop)
    return merge_next_line_proposals(
        proposals,
        priority,
        stop=stop,
        cap=candidate_cap,
        filter_fn=lambda rows: filter_fn(rows, pack, reference),
    )


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


def drive_symbol_search(
    query: str,
    *,
    memory: Optional[Mapping[str, Any]],
    tactics: str,
    duckdb_path: Optional[Any],
    use_duckdb: bool,
    vector_snapshot: Optional[Mapping[str, Any]],
    vector_search: Optional[Callable[..., Any]],
    root: Optional[Any],
    ident_re: Any,
    jsonld_fn: Callable[[Mapping[str, Any]], Any],
    jsonld_search_fn: Callable[[Any, str], Sequence[Mapping[str, Any]]],
    hit_fn: Callable[..., dict[str, Any]],
    sidecar_query_fn: Callable[..., Sequence[Mapping[str, Any]]],
    sidecar_build_fn: Callable[..., Any],
    sidecar_row_fn: Callable[[Any], dict[str, Any]],
    duckdb_fn: Callable[..., tuple[Sequence[dict[str, Any]], str]],
    vector_fn: Callable[..., tuple[Sequence[dict[str, Any]], str]],
    kg_fn: Callable[..., Sequence[dict[str, Any]]],
    ast_fn: Callable[..., tuple[Sequence[dict[str, Any]], str]],
    rg_fn: Callable[..., Sequence[dict[str, Any]]],
    rank_fn: Callable[..., Sequence[dict[str, Any]]],
) -> dict[str, Any]:
    """Search/rank symbols. JSON-LD, DuckDB, vector, KG, AST, then rg. Does not compile."""

    from jevops.outer import as_dict, call_if, either, or_call, text_or

    q = or_call(text_or(query).strip(), first_ident, tactics, ident_re)
    sources: dict[str, str] = {}
    hits: list[dict[str, Any]] = []
    if q:

        def _jsonld() -> list[dict[str, Any]]:
            from jevops.outer import get_str, if_none

            doc = jsonld_fn(if_none(memory, default={}))
            return [hit_fn(get_str(hit, "symbol"), source="jsonld", query=q) for hit in jsonld_search_fn(doc, q)]

        def _sidecar() -> list[dict[str, Any]]:
            return [
                sidecar_row_fn(row)
                for row in sidecar_query_fn(
                    q, payload=call_if(root is not None, lambda: sidecar_build_fn(root=root, write=False))
                )
            ]

        hits, sources = collect_source_hits(
            (
                ("jsonld", _jsonld),
                (
                    "duckdb",
                    either(
                        use_duckdb,
                        lambda: (lambda: duckdb_fn(q, db_path=duckdb_path)),
                        lambda: (lambda: ([], "skipped_optional")),
                    ),
                ),
                ("vector", lambda: vector_fn(q, snapshot=vector_snapshot, search_fn=vector_search)),
                ("kg", lambda: kg_fn(q, memory)),
                ("ast", lambda: ast_fn(q, root=root)),
                ("sidecar", _sidecar),
                ("rg", lambda: rg_fn(q, root=root)),
            ),
            fail_notes={"sidecar": "sidecar_failed"},
        )
    ranked = rank_fn(hits)
    promoted = credit_search_hits(as_dict(memory), ranked)
    return pack_symbol_search(query=q, ranked=ranked, sources=sources, promoted=promoted)


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


def drive_prefix_search(
    record: Mapping[str, Any],
    *,
    mode: str,
    max_steps: int,
    beam: int,
    temperature: float,
    generate: Optional[Callable[..., str]],
    prune: Optional[Callable[..., dict[str, Any]]],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    prefix_fn: Callable[[str], str],
    vocab_fn: Callable[[str], Sequence[str]],
    ledger_cls: Callable[..., Any],
    max_jev: int,
    sample_cap: int,
    default_prune: Callable[..., dict[str, Any]],
    stop_token: str,
    pack_fn: Callable[[str, str], Mapping[str, Any]],
    stop_allowed_fn: Callable[[str, str], bool],
    propose_fn: Callable[..., Sequence[str]],
    extend_fn: Callable[..., str],
    filter_fn: Callable[..., Sequence[str]],
    item_cls: Callable[..., Any],
    hardware_class: str,
) -> dict[str, Any]:
    """Prefix beam over a reference tactic block. The proposer may call a model. Jev does not write Lean."""

    from jevops.outer import beam_shape, either, get_str, if_none, or_none

    tactics, prefix0, vocab = begin_prefix_search(record, tactic_fn=tactic_fn, prefix_fn=prefix_fn, vocab_fn=vocab_fn)
    ledger = ledger_cls(
        name=f"{get_str(record, 'name')}#constrained-beam-local",
        max_jev_calls=max_jev,
        max_mistral_calls=0,
        max_grok_calls=0,
    )
    beam_n, n_samples = beam_shape(mode, beam, sample_cap=sample_cap)
    temp = float(temperature)
    prune_fn = if_none(prune, default_prune)

    def _prune(item: Any, proposals: Sequence[str], pack: Mapping[str, Any]) -> dict[str, Any]:
        return either(
            prune is None,
            lambda: default_prune(record, item.prefix, proposals, ledger=ledger, keep=beam_n, context=pack),
            lambda: prune_fn(record, item.prefix, proposals, ledger=ledger, keep=beam_n),
        )

    out = run_prefix_beam(
        prefix0,
        max_steps=max_steps,
        beam_n=beam_n,
        stop_token=stop_token,
        pack_fn=lambda prefix: pack_fn(tactics, prefix),
        stop_allowed_fn=lambda prefix: stop_allowed_fn(prefix, tactics),
        propose_fn=lambda item, pack: propose_fn(
            record, item, vocab, beam=beam_n, temperature=temp, generate=generate, pack=pack, reference=tactics
        ),
        prune_fn=_prune,
        extend_fn=lambda prefix, nxt, pack: extend_fn(prefix, nxt, original=or_none(get_str(pack, "next_original"))),
        filter_fn=lambda lines, pack: filter_fn(lines, pack, tactics),
        n_samples=n_samples,
        item_cls=item_cls,
    )
    return pack_beam_search(
        out,
        prefix=prefix0,
        vocab_n=len(list(vocab)),
        mode=mode,
        beam=beam_n,
        temperature=temp,
        max_steps=max_steps,
        extra={
            "pca_mca": pack_fn(tactics, prefix0),
            "ledger": ledger.as_dict(),
            "hardware_class": hardware_class,
            "called_docker0": generate is None,
            "official_track2": False,
        },
    )


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


def drive_keepbest(
    *,
    name: str,
    hosted_path: Optional[Any],
    state_root: Any,
    timeout: float,
    repair: bool,
    load_fn: Callable[[], tuple[Any, str, Sequence[Mapping[str, Any]]]],
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[..., str],
    split_fn: Callable[[Mapping[str, Any]], Any],
    body_fn: Callable[[str], str],
    drafts_fn: Callable[..., Sequence[Any]],
    span_fn: Callable[[str], Sequence[Any]],
    hosted_fn: Callable[[Any], str],
    match_fn: Callable[[str, str], str],
    flatten_fn: Callable[[str, str], str],
    compile_fn: Callable[..., Mapping[str, Any]],
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    token_fn: Callable[[str], int],
    key_fns: Sequence[Callable[[], Any]],
    prompt_fn: Callable[..., str],
    ledger_cls: Callable[..., Any],
    generate_fn: Callable[..., tuple[str, Any, Any]],
    extract_fn: Callable[[str], str],
    hardware_class: str,
    prototype_hardware: str,
) -> dict[str, Any]:
    """Splice hosted and fan-out tactics and lake-compile. ``compile_fn`` owns lake."""

    from jevops.outer import attr_or, call_if_file, contains_attr, field_eq, first_or_required, first_where, get_list, load_and_clone, map_if, pin_calls, replace_if, require_file_bytes
    from jevops.repair import align_generated, align_then_compile

    record, records, digest, clone, dest, restore = load_and_clone(
        load_fn,
        name,
        state_root,
        clone_fn=clone_fn,
        relpath_fn=relpath_fn,
        error_cls=RuntimeError,
        miss=f"unknown warm-up problem: {name}",
        read_fn=lambda path: require_file_bytes(path, error_cls=RuntimeError, miss="{path}: clone/checkout Strata first"),
    )
    del dest
    rel = relpath_fn(record)
    ref_tactics = body_fn(split_fn(record).body_suffix)
    drafts = drafts_fn(record, records)
    collapse = first_where(drafts, contains_attr("ops", "collapse_simp_at"))
    hosted = call_if_file(hosted_path, lambda: match_fn(ref_tactics, hosted_fn(hosted_path)))
    flattened = map_if(hosted, lambda body: flatten_fn(ref_tactics, body))

    def _repair(
        rows: Sequence[Mapping[str, Any]],
        tactics_by_kind: Mapping[str, str],
        hosted_row: Mapping[str, Any],
    ) -> Optional[Mapping[str, Any]]:
        pin_calls(*key_fns)()
        indent_row = first_where(rows, field_eq("kind", "hosted_indent_normalized"))
        failed = first_or_required(tactics_by_kind, "hosted_indent_normalized", "hosted_mistral")
        errors = replace_if(
            indent_row and indent_row.get("module_exit_0"),
            [
                {
                    "pos": None,
                    "data": (
                        "The indent-normalized draft compiles but is not shorter than the "
                        "reference. Return a strictly shorter tactic block that still compiles."
                    ),
                }
            ],
            get_list(hosted_row, "errors"),
        )
        ledger = ledger_cls(name=f"{name}#repair")
        text, repair_identity, _line = generate_fn(
            prompt_fn(record, failed=failed, errors=errors, reference=ref_tactics),
            ledger,
            max_new_tokens=1400,
            timeout=180.0,
        )
        repaired_tactics, compile_row = align_then_compile(
            text,
            ref_tactics,
            align_fn=lambda reference, body: align_generated(
                reference, body, extract_fn=extract_fn, match_fn=match_fn, flatten_fn=flatten_fn
            ),
            compile_fn=lambda body: compile_fn(record, body, state_root=state_root, timeout=timeout, restore=restore),
        )
        return row_fn(
            {
                "kind": "hosted_mistral_repair",
                "generator": "labs-leanstral-1-5",
                "tactics": repaired_tactics,
                "ledger": ledger.as_dict(),
                "repair_identity": repair_identity,
            },
            compile_row,
        )

    return run_keepbest(
        name=name,
        digest=digest,
        ref_tactics=ref_tactics,
        hosted=hosted,
        flattened=flattened,
        collapse=attr_or(collapse, "tactics"),
        span_drafts=span_fn(ref_tactics),
        compile_fn=lambda body: compile_fn(record, body, state_root=state_root, timeout=timeout, restore=restore),
        row_fn=row_fn,
        token_fn=token_fn,
        repair=repair,
        repair_fn=_repair,
        pick_fn=pick_min_tiers,
        first_where_fn=first_where,
        pack_fn=keepbest_payload,
        clone=clone,
        rel=rel,
        hosted_path=hosted_path,
        hardware_class=hardware_class,
        prototype_hardware=prototype_hardware,
    )


def keepbest_payload(
    *,
    name: str,
    digest: str,
    rows: Sequence[Mapping[str, Any]],
    kept: Optional[Mapping[str, Any]],
    repaired: bool,
    clone: Any,
    file_path: str,
    hosted_receipt: Any,
    n_valid: int,
    n_module_ok: int,
    hardware_class: str,
    prototype_hardware: str,
    schema: str = "lra-track1-keepbest/v1",
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops.outer import utc_stamp

    out: dict[str, Any] = {
        "schema": schema,
        "observed_at": utc_stamp(),
        "name": name,
        "warmup_jsonl_sha256": digest,
        "hardware_class": hardware_class,
        "prototype_hardware_class": prototype_hardware,
        "used_prototype_endpoint": False,
        "called_docker0": False,
        "repaired": bool(repaired),
        "official_track2": False,
        "arena_score": None,
        "clone": str(clone),
        "file_path": file_path,
        "hosted_receipt": str(hosted_receipt),
        "candidates": list(rows or ()),
        "kept": kept,
        "n_valid": int(n_valid),
        "n_module_exit_0": int(n_module_ok),
    }
    if extra:
        out.update(dict(extra))
    return out


def vector_hits_from_result(
    result: Any,
    *,
    query: str,
    hit_fn: Callable[..., dict[str, Any]],
    cap: int = 12,
    vector_weight: float = 1.0,
) -> list[dict[str, Any]]:
    """Project vector-index hits. Advisory only. Never writes Lean."""

    from jevops.outer import field_of, head_seq

    hits: list[dict[str, Any]] = []
    rows = getattr(result, "hits", None) or (result.get("hits") if isinstance(result, Mapping) else []) or []
    for item in head_seq(rows, cap):
        row = field_of(item, "row", default=item)
        symbol = str(field_of(row, "qualified_symbol", "symbol") or "")
        path = str(field_of(row, "path") or "")
        score = float(field_of(item, "score", default=0.0) or 0.0)
        if not symbol:
            continue
        hit = hit_fn(symbol, source="vector", query=query, path=path)
        hit["score"] = round(max(float(hit.get("score") or 0.0), score * float(vector_weight)), 4)
        hits.append(hit)
    return hits


def keepbest_beam_pairs(
    reference: str,
    tactics_list: Sequence[str],
    *,
    variants_fn: Callable[[str, str, str], Sequence[tuple[str, str]]],
) -> list[tuple[str, str]]:
    """Reference plus beam drafts, each expanded by keepbest variants. Lake is the oracle."""

    pairs: list[tuple[str, str]] = []
    rows = [("reference", reference), *[(f"beam_{index}", text) for index, text in enumerate(tactics_list)]]
    for kind, body in rows:
        pairs.extend(list(variants_fn(kind, body, reference)))
    return pairs


def boxed_keepbest(box: dict[str, Any]) -> Callable[..., tuple[Optional[Mapping[str, Any]], int, str]]:
    """Keep-best accept that mutates box['tokens'] / box['keep'] in place."""

    def _accept(
        evals: Sequence[Mapping[str, Any]], tokens: int, trial: str
    ) -> tuple[Optional[Mapping[str, Any]], int, str]:
        best, nxt, body = apply_keepbest(evals, tokens, trial=trial)
        if not best:
            return None, nxt, str(box.get("keep") or "")
        box["tokens"] = nxt
        box["keep"] = body
        return strip_tactics([best])[0], nxt, body

    return _accept


def attach_jev_rounds(
    rounds: Sequence[Mapping[str, Any]],
    jevs: Sequence[Mapping[str, Any]],
    history: Optional[Sequence[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row, jev in zip(rounds or (), jevs or ()):
        item = dict(row)
        item["jev"] = jev
        out.append(item)
    if history is not None:
        for row, jev in zip(history, jevs or ()):
            row["jev_choice"] = jev.get("choice")
    return out


def drive_sgd(
    name: str,
    *,
    state_root: Any,
    timeout: float,
    rounds: int,
    seed: int,
    use_leanstral: bool,
    memory: Optional[dict[str, Any]],
    rng_cls: Callable[[int], Any],
    load_fn: Callable[[], tuple[Any, str, Sequence[Mapping[str, Any]]]],
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[..., str],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    holes_fn: Callable[[str], Sequence[Any]],
    token_fn: Callable[[str], int],
    key_fns: Sequence[Callable[[], Any]],
    jev_fn: Callable[..., Mapping[str, Any]],
    drop_fn: Callable[..., str],
    eval_fn: Callable[..., Sequence[Mapping[str, Any]]],
    extract_fn: Callable[[str], str],
    match_fn: Callable[..., str],
    flatten_fn: Callable[..., str],
    ledger_cls: Callable[..., Any],
    shot_names: Sequence[str],
    example_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    prompt_fn: Callable[..., str],
    keyfile_fns: Sequence[Callable[[], Any]],
    generate_fn: Callable[..., tuple[str, Any, Any]],
    hammer_fn: Callable[..., str],
    redact_fn: Callable[[Any], Any],
    hardware_class: str,
    protocol: str,
    pr: str,
) -> dict[str, Any]:
    """Coordinate-descent over holes. ``eval_fn`` still owns lake."""

    from jevops.outer import after_calls, first_int, head_errors, keep_box, load_and_clone, named_shots, pin_calls, take_keys
    from jevops.repair import bind_align

    rng = rng_cls(first_int(seed))
    record, records, digest, _clone, _dest, restore = load_and_clone(
        load_fn,
        name,
        state_root,
        clone_fn=clone_fn,
        relpath_fn=relpath_fn,
        error_cls=RuntimeError,
        miss=f"unknown warm-up problem: {name}",
    )
    started = begin_keep_search(
        record,
        tactic_fn=tactic_fn,
        find_fn=holes_fn,
        token_fn=token_fn,
        pin_fn=pin_calls(*key_fns),
    )
    reference, holes, keep, keep_tokens, history, _dropped, jevs = take_keys(
        started, "reference", "holes", "keep", "keep_tokens", "history", "dropped", "jevs"
    )
    box = keep_box(keep_tokens, keep)

    def _choose(remaining: Sequence[Any], _dropped: set[str], _round: int) -> list[str]:
        jev = jev_fn(record, remaining, history, box["tokens"])
        jevs.append(jev)
        return choose_minibatch(remaining, jev, rng, k=2)

    walked = coordinate_rounds(
        holes,
        rounds=rounds,
        choose_fn=_choose,
        trial_fn=lambda chosen: drop_fn(reference, holes, chosen),
        eval_fn=lambda trial: eval_fn(
            record, trial, state_root=state_root, timeout=timeout, restore=restore, reference=reference, memory=memory
        ),
        accept_fn=boxed_keepbest(box),
        keep_tokens=keep_tokens,
        keep_body=keep,
        history=history,
    )
    keep, keep_tokens, dropped, history = unpack_walked(walked)
    rounds_out = attach_jev_rounds(walked["rounds"], jevs, history)
    align = bind_align(reference, extract_fn=extract_fn, match_fn=match_fn, flatten_fn=flatten_fn)

    def _generate() -> tuple[str, Any, Any]:
        ledger = ledger_cls(name=f"{name}#sgd")
        shots = named_shots(records, shot_names, skip_name=name, example_fn=example_fn)
        text, identity, _line = after_calls(
            tuple(keyfile_fns),
            generate_fn,
            prompt_fn(record, shots),
            ledger,
            max_new_tokens=700,
            timeout=180.0,
        )
        return text, identity, ledger

    keep, keep_tokens, leanstral = maybe_leanstral_restart(
        use=use_leanstral,
        keep=keep,
        keep_tokens=keep_tokens,
        ref_tokens=token_fn(reference),
        generate_fn=_generate,
        flatten_fn=align,
        eval_fn=lambda body: eval_fn(
            record, body, state_root=state_root, timeout=timeout, restore=restore, reference=reference, memory=memory
        ),
        hammer_fn=lambda filled, evals: hammer_fn(filled, reference, head_errors(evals)),
        ledger_fn=lambda ledger: ledger.as_dict(),
    )
    return redact_fn(
        sgd_payload(
            name=name,
            digest=digest,
            n_holes=len(list(holes)),
            ref_tokens=token_fn(reference),
            keep_tokens=keep_tokens,
            dropped=dropped,
            rounds=rounds_out,
            leanstral=leanstral,
            hardware_class=hardware_class,
            protocol=protocol,
            pr=pr,
        )
    )


def sgd_payload(
    *,
    name: str,
    digest: str,
    n_holes: int,
    ref_tokens: int,
    keep_tokens: int,
    dropped: Sequence[str],
    rounds: Sequence[Mapping[str, Any]],
    leanstral: Any,
    hardware_class: str,
    schema: str = "lra-sgd-fanout/v1",
    protocol: str = "LRA/v1",
    pr: str = "",
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": schema,
        "protocol": protocol,
        "pr": pr,
        "name": name,
        "warmup_jsonl_sha256": digest,
        "n_holes": int(n_holes),
        "ref_tokens": int(ref_tokens),
        "keep_tokens": int(keep_tokens),
        "ratio": token_ratio(keep_tokens, ref_tokens),
        "dropped": sorted(dropped),
        "rounds": list(rounds or ()),
        "leanstral": leanstral,
        "hardware_class": hardware_class,
        "called_docker0": False,
        "official_track2": False,
        "arena_score": None,
        "note": "Jev-guided stochastic coordinate descent on MCA holes; not neural SGD.",
    }
    if extra:
        out.update(dict(extra))
    return out


def run_keepbest(
    *,
    name: str,
    digest: str,
    ref_tactics: str,
    hosted: Optional[str],
    flattened: Optional[str],
    collapse: Optional[str],
    span_drafts: Sequence[Any],
    compile_fn: Callable[[str], Mapping[str, Any]],
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    token_fn: Callable[[str], int],
    repair: bool,
    repair_fn: Optional[Callable[..., Optional[Mapping[str, Any]]]] = None,
    pick_fn: Callable[..., Any],
    first_where_fn: Callable[..., Any],
    pack_fn: Callable[..., Mapping[str, Any]],
    clone: Any,
    rel: str,
    hosted_path: Any,
    hardware_class: str,
    prototype_hardware: str,
    hosted_kind: str = "hosted_mistral",
) -> dict[str, Any]:
    """Compile keep-best candidates, optional hosted repair, then pick. Lake is the oracle."""

    candidates = keepbest_candidates(
        reference=ref_tactics,
        hosted=hosted,
        flattened=flattened,
        collapse=collapse,
        span_drafts=span_drafts,
    )
    rows, tactics_by_kind = compile_labeled(candidates, compile_fn, row_fn)
    repaired = False
    hosted_row = next((row for row in rows if row.get("kind") == hosted_kind), None)
    beats = beats_reference(rows, token_fn(ref_tactics))
    if repair and not beats and hosted_row is not None and repair_fn is not None:
        extra = repair_fn(rows, tactics_by_kind, hosted_row)
        if extra is not None:
            rows.append(dict(extra))
            repaired = True

    def _valid(row: Mapping[str, Any]) -> bool:
        return bool(row.get("theorem_ok") or (row.get("ok") and not row.get("sorry_in_theorem")))

    def _module_ok(row: Mapping[str, Any]) -> bool:
        return bool(row.get("module_exit_0") or row.get("theorem_ok"))

    kept = pick_fn(
        rows,
        (_valid, _module_ok),
        key_fn=lambda row: (
            int(row.get("token_count") or 10**9),
            0 if row.get("kind") == "reference" else 1,
            float(row.get("wall_ms") or 0),
        ),
        fallback_fn=lambda items: first_where_fn(items, lambda row: row.get("kind") == "reference"),
    )
    return pack_fn(
        name=name,
        digest=digest,
        rows=rows,
        kept=keepbest_kept(kept),
        repaired=repaired,
        clone=clone,
        file_path=rel,
        hosted_receipt=hosted_path,
        n_valid=sum(1 for row in rows if _valid(row)),
        n_module_ok=sum(1 for row in rows if _module_ok(row)),
        hardware_class=hardware_class,
        prototype_hardware=prototype_hardware,
    )


def maybe_leanstral_restart(
    *,
    use: bool,
    keep: str,
    keep_tokens: int,
    ref_tokens: int,
    generate_fn: Callable[[], tuple[str, Any, Any]],
    flatten_fn: Callable[[str], str],
    eval_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    hammer_fn: Callable[[str, Sequence[Mapping[str, Any]]], str],
    ledger_fn: Callable[[Any], Any] = lambda item: item,
) -> tuple[str, int, Any]:
    """Optional hosted restart when keep is not shorter. Lake still admits."""

    if not use or int(keep_tokens) < int(ref_tokens):
        return keep, int(keep_tokens), None
    text, identity, ledger = generate_fn()
    filled = flatten_fn(text)
    evals = list(eval_fn(filled) or ())
    hammered = hammer_fn(filled, evals)
    evals_h = list(eval_fn(hammered) or ())
    packed = {
        "identity": identity,
        "ledger": ledger_fn(ledger),
        "evals": evals,
        "hammer_evals": evals_h,
    }
    tokens = int(keep_tokens)
    body = keep
    for row in evals + evals_h:
        if row.get("theorem_ok") and int(row.get("token_count") or tokens) < tokens:
            body = hammered if row in evals_h else filled
            tokens = int(row["token_count"])
    return body, tokens, packed


def run_mcmc_rounds(
    *,
    rounds: int,
    chains: Sequence[Any],
    ledger: Any,
    leanstral: bool,
    max_leanstral: int,
    leanstral_fn: Callable[..., Optional[Mapping[str, str]]],
    propose_fn: Callable[..., Sequence[Mapping[str, Any]]],
    filter_fn: Callable[..., Sequence[Mapping[str, Any]]],
    rank_fn: Callable[..., Mapping[str, Any]],
    pin_fn: Callable[..., Sequence[Any]],
    pin_prefixes: Sequence[str],
    try_fn: Callable[..., Any],
    compile_fn: Callable[[str], Mapping[str, Any]],
    history: list[dict[str, Any]],
    failed_bodies: set[str],
    failed_kinds: set[str],
    sticky_fail: set[str],
    best: dict[str, Any],
    temperature: float,
    rng: Any,
) -> int:
    """MCMC round/chain loop. propose/rank/compile/try are injected. Lake is the oracle."""

    leanstral_calls = 0
    hard_stopped = lambda: bool(getattr(ledger, "hard_stopped", False))
    for round_i in range(int(rounds)):
        if hard_stopped():
            break
        for chain_i, chain in enumerate(chains):
            extra: list[dict[str, str]] = []
            if leanstral and leanstral_calls < int(max_leanstral):
                swap = leanstral_fn(chain.tactics)
                leanstral_calls += 1
                if swap:
                    extra.append(dict(swap))
            proposals = list(
                filter_fn(
                    propose_fn(chain.tactics, extra=extra),
                    failed_bodies=failed_bodies,
                    failed_kinds=failed_kinds,
                )
                or ()
            )
            if not proposals:
                history.append({"round": round_i, "chain": chain_i, "reason": "all_blacklisted"})
                continue
            ranked = rank_fn(chain.tactics, proposals)
            ranked_order = ranked.get("order") or list(range(len(proposals)))
            order = pin_fn(
                ranked_order,
                kind_prefix_indices(proposals, pin_prefixes),
                n=2,
            )
            tried = try_fn(
                proposals=proposals,
                order=order,
                chain=chain,
                compile_fn=compile_fn,
                best=best,
                failed_bodies=failed_bodies,
                failed_kinds=failed_kinds,
                sticky_fail=sticky_fail,
                round_i=round_i,
                chain_i=chain_i,
                history=history,
                ranked_meta=ranked,
                temperature=temperature,
                rng=rng,
            )
            if tried is None:
                history.append({"round": round_i, "chain": chain_i, "reason": "no_proposal"})
    return leanstral_calls


def run_cascade_rounds(
    *,
    rounds: int,
    current: str,
    best: dict[str, Any],
    history: list[dict[str, Any]],
    failed_kinds: set[str],
    ledger: Any,
    rng: Any,
    name: str,
    available_fn: Callable[..., Mapping[str, str]],
    live_tree_fn: Callable[[Mapping[str, str]], Mapping[str, Any]],
    classify_fn: Callable[..., Mapping[str, Any]],
    verify_fn: Callable[..., Mapping[str, float]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    token_fn: Callable[[str], int],
    unavailable_fn: Callable[[BaseException], bool],
    sleep_fn: Callable[[float], None],
    confident: float,
    fire_t: float,
    sleep_s: float = 5.0,
    goal: str = "Shorten a lake-valid Lean 4 proof without breaking compile. Do not write Lean.",
) -> tuple[str, dict[str, Any]]:
    """Hierarchical family→leaf cascade. Lake is the oracle. Jev does not write Lean."""

    from jevops.outer import (
        exc_head,
        first_float,
        first_int,
        first_truthy,
        get_str,
        head_seq,
        or_list,
        overlay_map,
        tail_chars,
        text_or,
    )

    del rng
    hard_stopped = lambda: bool(getattr(ledger, "hard_stopped", False))
    for round_i in range(int(rounds)):
        if hard_stopped():
            break
        found = dict(available_fn(current) or {})
        for kind in list(found):
            if kind in failed_kinds and kind != "keep":
                found.pop(kind, None)
        tree = live_tree_fn(found)
        state = {
            "problem": name,
            "current_tokens": best["token_count"],
            "current_tail": tail_chars(current, 400),
            "available_leaves": sorted(k for k in found if k != "keep"),
            "failed_kinds": sorted(failed_kinds),
            "goal": goal,
        }
        try:
            classified = classify_fn(state, tree)
        except Exception as exc:  # noqa: BLE001
            history.append({"round": round_i, "action": "typesafe_error", "error": exc_head(exc)})
            if unavailable_fn(exc):
                sleep_fn(sleep_s)
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
        winning_fam = get_str(classified.get("family"), "choice")
        if winning_fam not in tree:
            winning_fam = text_or(or_list(classified.get("beam_fams"), ["keep"])[0])
        greedy_leaf = None
        if winning_fam and winning_fam != "keep":
            fam_paths = [p for p in classified["paths"] if p.get("family") == winning_fam]
            if fam_paths:
                greedy_leaf = get_str(fam_paths[0], "leaf")
        tried = False
        for top in classified["paths"]:
            leaf = get_str(top, "leaf")
            if first_truthy(leaf == "keep", top["family"] == "keep", leaf in failed_kinds):
                continue
            body = found.get(leaf)
            if not body or body.strip("\n") == current.strip("\n"):
                continue
            tok = token_fn(body)
            leaf_conf = first_float(top.get("leaf_confidence"))
            family_conf = first_float(classified["family"].get("confidence"))
            confident_leaf = leaf_conf >= float(confident)
            greedy_ok = (not confident_leaf) and family_conf >= float(confident) and leaf == greedy_leaf
            if not confident_leaf and not greedy_ok:
                continue
            row["picked"] = top
            row["proposed_tokens"] = tok
            row["greedy_family"] = greedy_ok
            if tok >= first_int(best.get("token_count")):
                failed_kinds.add(leaf)
                continue
            vstate = overlay_map(
                state,
                edit_kind=leaf,
                proposed_tokens=tok,
                proposed_tail=tail_chars(body, 400),
            )
            try:
                flags = verify_fn(vstate)
            except Exception as exc:  # noqa: BLE001
                row["action"] = "verify_error"
                row["error"] = exc_head(exc)
                history.append(row)
                tried = True
                break
            fired = {k: p for k, p in flags.items() if p > float(fire_t)}
            row["verify"] = flags
            row["fired"] = fired
            if fired:
                row["action"] = "skip_lake"
                failed_kinds.add(leaf)
                history.append(row)
                tried = True
                break
            compiled = dict(compile_fn(body) or {})
            ok = bool(compiled.get("theorem_ok"))
            lake_tok = first_int(compiled.get("token_count"), tok)
            row["action"] = "lake"
            row["ok"] = ok
            row["tokens"] = lake_tok
            row["errors"] = head_seq(compiled.get("errors"), 1)
            history.append(row)
            tried = True
            if ok and lake_tok < first_int(best.get("token_count")):
                best = pack_keep(
                    kind=f"cascade_r{round_i}_{leaf}",
                    tactics=body,
                    token_count=lake_tok,
                )
                current = body
            else:
                failed_kinds.add(leaf)
            break
        if not tried:
            row["action"] = "abstain_family"
            history.append(row)
    return current, best


def run_autoresearch_rounds(
    *,
    rounds: int,
    current: str,
    best: dict[str, Any],
    history: list[dict[str, Any]],
    labeled: list[dict[str, Any]],
    weights: Mapping[str, float],
    ledger: Any,
    propose_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    feature_fn: Callable[[str, Mapping[str, Any], Mapping[str, float]], Mapping[str, Any]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    token_fn: Callable[[str], int],
    update_fn: Callable[[list[dict[str, Any]], dict[str, float]], dict[str, float]],
    propose_cap: int = 6,
    lake_cap: int = 2,
) -> tuple[str, dict[str, Any], dict[str, float]]:
    """Score MCMC proposals with injected features, then lake the shorter ones."""

    from jevops.outer import first_float, first_int, first_truthy, get_str, head_seq, overlay_map

    weights_out = dict(weights or {})
    hard_stopped = lambda: bool(getattr(ledger, "hard_stopped", False))
    for round_i in range(int(rounds)):
        if hard_stopped():
            break
        scored: list[dict[str, Any]] = []
        for proposal in head_seq(propose_fn(current), propose_cap):
            feat = feature_fn(current, proposal, weights_out)
            scored.append(overlay_map(proposal, **feat))
            if hard_stopped():
                break
        scored.sort(key=lambda item: first_float(item.get("score")), reverse=True)
        current_tok = token_fn(current)
        shorter = [
            item
            for item in scored
            if token_fn(get_str(item, "tactics")) < current_tok
        ]
        for proposal in head_seq(first_truthy(shorter, scored), lake_cap):
            body = get_str(proposal, "tactics")
            compiled = dict(compile_fn(body) or {})
            ok = bool(compiled.get("theorem_ok"))
            tok = first_int(compiled.get("token_count"), token_fn(body))
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
            if ok and tok < first_int(best.get("token_count")):
                best = pack_keep(
                    kind=f"ar_r{round_i}_{proposal.get('kind')}",
                    tactics=body,
                    token_count=tok,
                )
                current = body
        weights_out = update_fn(labeled, weights_out)
    return current, best, weights_out


def pack_diffuse(
    *,
    name: str,
    digest: str,
    n_holes: int,
    ref_tokens: int,
    keep_tokens: int,
    dropped: Sequence[str],
    rounds: Sequence[Mapping[str, Any]],
    hardware_class: str,
    schema: str = "lra-diffuse-denoise/v1",
    protocol: str = "LRA/v1",
    pr: str = "",
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Diffuse/denoise payload. Lake is the oracle. Not neural SGD."""

    out: dict[str, Any] = {
        "schema": schema,
        "protocol": protocol,
        "pr": pr,
        "name": name,
        "warmup_jsonl_sha256": digest,
        "n_holes": int(n_holes),
        "ref_tokens": int(ref_tokens),
        "keep_tokens": int(keep_tokens),
        "ratio": token_ratio(keep_tokens, ref_tokens),
        "dropped": sorted(dropped),
        "rounds": list(rounds or ()),
        "ledger": None,
        "hardware_class": hardware_class,
        "called_docker0": False,
        "official_track2": False,
        "arena_score": None,
        "note": (
            "Exploit=drop high-p and all MCA holes; explore=random hole; "
            "diffuse=Leanstral one-hole noise; denoise=hammer. Not neural SGD."
        ),
    }
    if extra:
        out.update(dict(extra))
    out["arena_score"] = None
    out["official_track2"] = False
    out["called_docker0"] = False
    return out


def run_diffuse_rounds(
    holes: Sequence[Any],
    *,
    rounds: int,
    tau: float,
    rng: Any,
    hole_id_fn: Callable[[Any], str] = lambda hole: str(getattr(hole, "hole_id", hole)),
    consider_fn: Callable[[str, Sequence[str]], Mapping[str, Any]],
    jev_fn: Callable[[Sequence[Any], Sequence[Mapping[str, Any]], int], Mapping[str, Any]],
    noise_fn: Callable[[int, Sequence[Any]], Any],
    keep_tokens: int,
    dropped: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Exploit high-p + explore random + optional noise. consider/jev/noise are injected."""

    dropped = dropped if dropped is not None else set()
    history: list[dict[str, Any]] = []
    rounds_out: list[dict[str, Any]] = []
    tokens = int(keep_tokens)

    def _consider(label: str, hole_ids: Sequence[str]) -> dict[str, Any]:
        nonlocal tokens
        row = dict(consider_fn(label, hole_ids) or {})
        tokens = int(row.get("keep_tokens") or tokens)
        return row

    full = _consider("exploit_all_holes", [hole_id_fn(hole) for hole in holes])
    rounds_out.append({"round": 0, "phase": "exploit_all", **full})
    for round_i in range(1, max(1, int(rounds)) + 1):
        remaining = [hole for hole in holes if hole_id_fn(hole) not in dropped]
        jev: dict[str, Any] = {"skipped": True, "reason": "no_holes"}
        step_exploit: Optional[dict[str, Any]] = None
        step_explore: Optional[dict[str, Any]] = None
        high: list[str] = []
        explore: list[str] = []
        if remaining:
            jev = dict(jev_fn(remaining, history, tokens) or {})
            high = high_p_ids(jev.get("probabilities") or {}, tau=tau, fallback=jev.get("choice"))
            explore = [hole_id_fn(rng.choice(remaining))]
            step_exploit = _consider("exploit_high_p", high)
            step_explore = _consider("explore_random", explore)
        noise = noise_fn(round_i, remaining)
        history.append(
            {
                "round": round_i,
                "high_p": high,
                "explore": explore,
                "keep_tokens": tokens,
                "jev_choice": jev.get("choice"),
            }
        )
        rounds_out.append(
            {
                "round": round_i,
                "jev": jev,
                "exploit": step_exploit,
                "explore": step_explore,
                "diffuse": noise,
                "keep_tokens": tokens,
            }
        )
    return {
        "keep_tokens": tokens,
        "dropped": sorted(dropped),
        "history": history,
        "rounds": rounds_out,
        "arena_score": None,
    }


def pack_symbol_search(
    *,
    query: str,
    ranked: Sequence[Mapping[str, Any]],
    sources: Mapping[str, str],
    promoted: int,
) -> dict[str, Any]:
    """JSON-LD-first symbol search payload. DuckDB is optional. Never writes Lean."""

    return {
        "ok": True,
        "query": query,
        "n_hits": len(list(ranked or ())),
        "hits": list(ranked or ()),
        "sources": dict(sources or {}),
        "called_docker0": False,
        "semantic_authority": False,
        "n_cells_promoted": int(promoted),
    }


def finish_mca_problem(
    *,
    candidates: Sequence[Mapping[str, Any]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    hammer_fn: Callable[..., tuple[list[dict[str, Any]], str, list[Any], bool]],
    needs_hammer_fn: Callable[[str], bool],
    repair_fn: Optional[Callable[..., tuple[list[dict[str, Any]], bool]]] = None,
    ablate_fn: Optional[Callable[[], Sequence[Mapping[str, Any]]]] = None,
    name: str,
    digest: str,
    holes: Sequence[Any],
    skeleton_head: str,
    hardware_class: str,
    ref_tokens: int,
    extra_fn: Callable[..., Mapping[str, Any]],
    redact_fn: Callable[[Mapping[str, Any]], Any],
    schema: str = "lra-mca-mask-replace/v1",
) -> dict[str, Any]:
    """Compile/hammer/ablate labeled MCA drafts, then pack. Generation stays injected."""

    rows, grok_ok, grok_tactics, grok_errors = compile_then_hammer(
        candidates,
        compile_fn=compile_fn,
        row_fn=row_fn,
        hammer_fn=hammer_fn,
        needs_hammer_fn=needs_hammer_fn,
    )
    if repair_fn is not None:
        rows, grok_ok = repair_fn(list(rows), grok_ok, grok_tactics, grok_errors)
    if ablate_fn is not None:
        rows.extend(list(ablate_fn() or ()))
    kept = keep_shortest_ok(rows)
    beats = beats_reference(
        [kept] if kept is not None else [],
        ref_tokens,
        skip_kind="reference",
        ok_key="theorem_ok",
        token_key="token_count",
    )
    return redact_fn(
        pack_mca_problem(
            schema=schema,
            name=name,
            digest=digest,
            n_holes=len(list(holes or ())),
            holes=list(holes or ()),
            skeleton_head=skeleton_head,
            hardware_class=hardware_class,
            reference_token_count=int(ref_tokens),
            beats_reference=beats,
            candidates=rows,
            kept=kept,
            extra=extra_fn(grok_ok=grok_ok, grok_tactics=grok_tactics, grok_errors=grok_errors),
        )
    )


def dispatch_mca_generation(
    *,
    grok_paths: Sequence[Any] = (),
    grok_few_shot: bool = False,
    few_shot: bool = False,
    call_leanstral: bool = False,
    one_hole: bool = False,
    fill_holes: Sequence[Any] = (),
    holes: Sequence[Any] = (),
    grok_paths_fn: Optional[Callable[[], Mapping[str, Any]]] = None,
    grok_few_shot_fn: Optional[Callable[[], Mapping[str, Any]]] = None,
    few_shot_fn: Optional[Callable[[], Mapping[str, Any]]] = None,
    one_hole_fn: Optional[Callable[[], Mapping[str, Any]]] = None,
    mask_fn: Optional[Callable[[], Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Pick one MCA generation branch. Generation bodies stay injected. Never writes Lean."""

    from jevops.outer import overlay_map

    call_leanstral = bool(call_leanstral)
    grok_few_shot = bool(grok_few_shot)
    if grok_few_shot:
        call_leanstral = False
    if grok_paths:
        grok_few_shot = False
        call_leanstral = False
    out: dict[str, Any] = {
        "call_leanstral": call_leanstral,
        "grok_few_shot": grok_few_shot,
        "leanstral_text": None,
        "identity": None,
        "ledger": None,
        "grok_skip_reason": "",
        "one_hole_fills": [],
        "few_shot_row": None,
        "grok_few_shot_row": None,
        "grok_workspace": None,
        "grok_file_meta": [],
        "grok_file_rows": [],
        "holes_for_leanstral": list(holes or ()),
    }
    if grok_paths and grok_paths_fn is not None:
        out = overlay_map(out, **dict(grok_paths_fn() or {}))
        out["grok_few_shot"] = False
        out["call_leanstral"] = False
        grok_few_shot = False
        call_leanstral = False
    if grok_few_shot and grok_few_shot_fn is not None:
        out = overlay_map(out, **dict(grok_few_shot_fn() or {}))
        out["grok_few_shot"] = True
        out["call_leanstral"] = False
    elif few_shot and call_leanstral and few_shot_fn is not None:
        out = overlay_map(out, **dict(few_shot_fn() or {}))
    elif call_leanstral and one_hole and one_hole_fn is not None:
        out = overlay_map(out, **dict(one_hole_fn() or {}))
    elif call_leanstral and fill_holes and mask_fn is not None:
        out = overlay_map(out, **dict(mask_fn() or {}))
        out["holes_for_leanstral"] = list(fill_holes)
    return out


def drive_mca_problem(
    name: str,
    *,
    state_root: Any,
    timeout: float,
    call_leanstral: bool,
    ablate: bool,
    one_hole: bool,
    few_shot: bool,
    grok_few_shot: bool,
    grok_generate: Optional[Callable[..., str]],
    grok_tactics_paths: Sequence[Any],
    typesafe_fanout: bool,
    load_fn: Callable[[], tuple[Any, str, Sequence[Mapping[str, Any]]]],
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[..., str],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    find_fn: Callable[[str], Sequence[Any]],
    mask_fn: Callable[..., str],
    ledger_cls: Callable[..., Any],
    load_grok_fn: Callable[[Any], str],
    flatten_fn: Callable[[str, str], str],
    shot_fn: Callable[..., Sequence[Mapping[str, Any]]],
    grok_callable_fn: Callable[[], bool],
    workspace_fn: Callable[[], Any],
    grok_prompt_fn: Callable[[str], str],
    grok_file_fn: Callable[..., Any],
    grok_error: type[BaseException],
    grok_max_new: int,
    grok_timeout: float,
    few_prompt_fn: Callable[..., str],
    key_fns: Sequence[Callable[[], Any]],
    generate_mistral_fn: Callable[..., tuple[str, Any, Any]],
    prioritize_fn: Callable[..., Sequence[Any]],
    one_prompt_fn: Callable[..., str],
    parse_fn: Callable[..., Mapping[str, str]],
    extract_fn: Callable[[str], str],
    apply_fn: Callable[..., str],
    match_fn: Callable[..., str],
    flatten_over_fn: Callable[..., str],
    asdict_fn: Callable[[Any], dict[str, Any]],
    mistral_error: type[BaseException],
    lean_prompt_fn: Callable[..., str],
    compile_body_fn: Callable[..., dict[str, Any]],
    compile_row_fn: Callable[..., dict[str, Any]],
    hammer_passes_fn: Callable[..., tuple[list[dict[str, Any]], str, list[Any], bool]],
    needs_hammer_fn: Callable[[str], bool],
    repair_prompt_fn: Callable[..., str],
    assemble_fn: Callable[..., list[dict[str, Any]]],
    ablate_holes_fn: Callable[..., Any],
    tactician_fn: Callable[..., Sequence[Any]],
    feature_fn: Callable[[str], Mapping[str, Any]],
    family_fn: Callable[..., Sequence[Mapping[str, Any]]],
    draft_fn: Callable[..., Sequence[Any]],
    row_feature_fn: Callable[[Mapping[str, Any]], Any],
    fit_fn: Callable[..., Any],
    rank_fn: Callable[..., Mapping[str, Any]],
    identity_fn: Callable[[Any], Any],
    redact_fn: Callable[[Any], Any],
    token_fn: Callable[[str], int],
    fanout_cap: int,
    hardware_class: str,
    grok_hardware_class: str,
) -> dict[str, Any]:
    """Mask, generate, and lake one MCA problem. ``compile_body_fn`` owns lake."""

    from jevops.outer import (
        after_calls,
        call_caught,
        call_if,
        caught_reason,
        dict_call,
        either,
        first_truthy,
        first_where,
        fit_drop,
        get_list,
        get_str,
        head_chars,
        if_none,
        if_prefix,
        kind_startswith,
        load_and_clone,
        mark_skipped,
        optional_fn,
        or_call,
        or_none,
        or_str,
        str_or_none,
        tagged_mapping,
        take_keys,
        text_or,
    )
    from jevops.repair import align_generated

    record, records, digest, _clone, _dest, restore = load_and_clone(
        load_fn,
        name,
        state_root,
        clone_fn=clone_fn,
        relpath_fn=relpath_fn,
        error_cls=RuntimeError,
        miss=f"unknown warm-up problem: {name}",
    )
    masked = begin_masked(
        record,
        tactic_fn=tactic_fn,
        find_fn=find_fn,
        mask_fn=mask_fn,
        fill_pred=lambda hole: getattr(hole, "family", "") in {"strength_reduction", "algebraic_simplification"},
    )
    tactics, holes, skeleton, fill_holes = take_keys(masked, "tactics", "holes", "skeleton", "fill_holes")

    def _grok_paths() -> dict[str, Any]:
        ledger = ledger_cls(name=f"{name}#grok-file-fanout")
        rows = collect_path_candidates(
            grok_tactics_paths,
            load_fn=load_grok_fn,
            flatten_fn=lambda text: flatten_fn(tactics, text),
            pack_fn=pack_generated_candidate,
            generator="grok-file",
            extra={"chat_ignored": True},
            head_fn=head_chars,
        )
        return {"ledger": ledger, "grok_file_rows": rows}

    def _grok_few() -> dict[str, Any]:
        shots = shot_fn(records, skip_name=name)
        ledger = ledger_cls(name=f"{name}#grok-few-shot")
        if grok_generate is None and not grok_callable_fn():
            mark_skipped(ledger, "no_key")
            return {"ledger": ledger, "grok_skip_reason": "no_key"}
        workspace = workspace_fn()
        ok, grok_result, exc = call_caught(
            lambda: grok_file_fn(
                grok_prompt_fn(few_prompt_fn(record, shots)),
                ledger,
                workspace=workspace,
                max_new_tokens=grok_max_new,
                timeout=grok_timeout,
                generate=grok_generate,
                fixture=grok_generate is not None,
                reset_stub=True,
            ),
            grok_error,
        )
        skip_reason, grok_result = caught_reason(ok, grok_result, exc)
        out: dict[str, Any] = {"ledger": ledger, "grok_workspace": workspace, "grok_skip_reason": skip_reason, "grok_file_meta": []}
        if grok_result is not None:
            _body, row = flatten_shot(
                kind="grok_few_shot",
                generator="grok-4.6",
                text=grok_result.tactics,
                shots=shots,
                flatten_fn=lambda text: flatten_fn(tactics, text),
                pack_fn=pack_generated_candidate,
                extra={"source": "tactics.lean", "tactics_path": grok_result.tactics_path, "chat_ignored": True},
            )
            out["identity"] = grok_result.identity
            out["grok_few_shot_row"] = row
            out["grok_file_meta"] = [tagged_mapping("draft", grok_result)]
        return out

    def _few() -> dict[str, Any]:
        shots = shot_fn(records, skip_name=name)
        ledger = ledger_cls(name=f"{name}#few-shot")
        text, identity, _line = after_calls(
            tuple(key_fns),
            generate_mistral_fn,
            few_prompt_fn(record, shots),
            ledger,
            max_new_tokens=900,
            timeout=180.0,
        )
        _filled, row = flatten_shot(
            kind="leanstral_few_shot",
            generator="labs-leanstral-1-5",
            text=text,
            shots=shots,
            flatten_fn=lambda body: flatten_fn(tactics, body),
            pack_fn=pack_generated_candidate,
        )
        return {"ledger": ledger, "identity": identity, "few_shot_row": row}

    def _one() -> dict[str, Any]:
        targets = prioritize_fn(first_truthy(fill_holes, holes), cap=2)
        if not targets:
            return {}
        ledger = ledger_cls(name=f"{name}#mca-one-hole")
        after_calls(tuple(key_fns), lambda: None)
        fills, identity = collect_one_hole_fills(
            targets,
            holes,
            tactics,
            generate_fn=lambda hole: generate_mistral_fn(one_prompt_fn(record, tactics, hole), ledger, max_new_tokens=256, timeout=120.0),
            parse_fn=parse_fn,
            fallback_fn=extract_fn,
            apply_fn=apply_fn,
            align_fn=lambda filled: align_generated(tactics, filled, extract_fn=lambda text: text, match_fn=match_fn, flatten_fn=flatten_over_fn),
            pack_fn=pack_generated_candidate,
            asdict_fn=asdict_fn,
            skip_exc=(mistral_error,),
            generator="labs-leanstral-1-5",
            head_fn=head_chars,
        )
        return {"ledger": ledger, "identity": identity, "one_hole_fills": fills}

    def _mask() -> dict[str, Any]:
        ledger = ledger_cls(name=f"{name}#mca-mask")
        text, identity, _line = after_calls(
            tuple(key_fns),
            generate_mistral_fn,
            lean_prompt_fn(record, mask_fn(tactics, fill_holes), fill_holes),
            ledger,
            max_new_tokens=700,
            timeout=180.0,
        )
        return {"ledger": ledger, "identity": identity, "leanstral_text": text}

    generated = dispatch_mca_generation(
        grok_paths=grok_tactics_paths,
        grok_few_shot=grok_few_shot,
        few_shot=few_shot,
        call_leanstral=call_leanstral,
        one_hole=one_hole,
        fill_holes=fill_holes,
        holes=holes,
        grok_paths_fn=_grok_paths,
        grok_few_shot_fn=_grok_few,
        few_shot_fn=_few,
        one_hole_fn=_one,
        mask_fn=_mask,
    )
    grok_few_shot = bool(generated.get("grok_few_shot"))

    def _compile(body: str) -> dict[str, Any]:
        return dict_call(compile_body_fn, record, body, state_root=state_root, timeout=timeout, restore=restore)

    def _hammer(kind: str, item: Mapping[str, Any], compiled: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str, list[Any], bool]:
        return hammer_passes_fn(
            kind=kind,
            tactics_now=get_str(item, "tactics"),
            reference=tactics,
            errors=get_list(compiled, "errors"),
            record=record,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
            generator=if_prefix(kind, "grok", "grok+simp_all/omega", "leanstral+simp_all/omega"),
        )

    def _repair(rows: list[dict[str, Any]], grok_ok: bool, grok_tactics: str, grok_errors: list[Any]) -> tuple[list[dict[str, Any]], bool]:
        grok_few_shot_row = generated.get("grok_few_shot_row")
        ledger = generated.get("ledger")
        grok_tactics_current = first_truthy(grok_tactics, default="")
        grok_errors_current = get_list(grok_errors)
        if not (grok_few_shot and grok_few_shot_row is not None and not grok_ok and ledger is not None):
            return rows, grok_ok
        ok, grok_result, exc = call_caught(
            lambda: grok_file_fn(
                grok_prompt_fn(
                    repair_prompt_fn(
                        record,
                        failed=or_call(grok_tactics_current, lambda: grok_few_shot_row["tactics"]),
                        errors=grok_errors_current,
                        reference=tactics,
                    )
                ),
                ledger,
                workspace=if_none(generated.get("grok_workspace"), factory=workspace_fn),
                max_new_tokens=grok_max_new,
                timeout=grok_timeout,
                generate=grok_generate,
                fixture=grok_generate is not None,
                reset_stub=False,
            ),
            grok_error,
        )
        if not ok:
            generated["grok_skip_reason"] = or_str(generated.get("grok_skip_reason"), exc)
            rows.append(pack_failed_candidate(kind="grok_few_shot_repair", generator="grok-4.6", reason=text_or(exc), extra={"source": "tactics.lean", "chat_ignored": True}))
            return rows, grok_ok
        generated["identity"] = grok_result.identity
        generated.setdefault("grok_file_meta", []).append(tagged_mapping("repair", grok_result))
        repaired = flatten_fn(tactics, grok_result.tactics)
        compiled_r = compile_body_fn(record, repaired, state_root=state_root, timeout=timeout, restore=restore)
        rows, hammer_ok = after_compile_row(
            rows,
            {"kind": "grok_few_shot_repair", "generator": "grok-4.6", "tactics": repaired, "holes": []},
            compiled_r,
            row_fn=compile_row_fn,
            hammer_fn=lambda: hammer_passes_fn(
                kind="grok_few_shot_repair",
                tactics_now=repaired,
                reference=tactics,
                errors=get_list(compiled_r, "errors"),
                record=record,
                state_root=state_root,
                timeout=timeout,
                restore=restore,
                generator="grok+simp_all/omega",
            ),
        )
        if compiled_r.get("theorem_ok"):
            return rows, True
        return rows, bool(first_truthy(grok_ok, hammer_ok, default=False))

    def _fanout(candidates: list[dict[str, Any]], ledger: Any) -> dict[str, Any]:
        seed_row = first_where(candidates, kind_startswith("grok")) or {"tactics": tactics}
        _raw, _digest, warmup_records = load_fn()
        extras = collect_grok_fanout_extras(
            seed_row["tactics"],
            tactics,
            tactician_fn=tactician_fn,
            feature_fn=feature_fn,
            family_fn=family_fn,
            draft_fn=draft_fn,
            model=fit_drop(warmup_records, row_feature_fn, fit_fn),
        )
        ranked = rank_fn(record, extras, ledger=ledger)
        pin_grok_fanout(candidates, extras, get_str(ranked, "best_first_draft"), cap=fanout_cap, key_fn=lambda item: item["kind"])
        return ranked

    return run_mca_problem(
        generated=generated,
        name=name,
        digest=digest,
        tactics=tactics,
        holes=holes,
        skeleton=skeleton,
        assemble_fn=lambda leanstral_text, hole_rows: assemble_fn(record, tactics, hole_rows, leanstral_text=leanstral_text),
        compile_fn=_compile,
        row_fn=compile_row_fn,
        hammer_fn=_hammer,
        needs_hammer_fn=needs_hammer_fn,
        repair_fn=_repair,
        ablate_fn=optional_fn(ablate and holes, lambda: ablate_holes_fn(record, tactics, prioritize_fn(holes, cap=6), state_root=state_root, timeout=timeout, restore=restore)),
        fanout_fn=_fanout,
        extra_fn=lambda grok_ok, grok_tactics, grok_errors, generated, typesafe_meta: {
            "leanstral_identity": either(generated.get("grok_few_shot"), lambda: None, lambda: generated.get("identity")),
            "grok_identity": call_if(generated.get("grok_few_shot"), lambda: identity_fn(generated.get("identity"))),
            "grok_few_shot": bool(generated.get("grok_few_shot")),
            "grok_ok": grok_ok,
            "grok_skip_reason": or_none(generated.get("grok_skip_reason")),
            "grok_used_file": bool(generated.get("grok_few_shot")),
            "grok_chat_ignored": bool(generated.get("grok_few_shot")),
            "grok_workspace": str_or_none(generated.get("grok_workspace")),
            "grok_file_calls": list(generated.get("grok_file_meta") or ()),
            "typesafe_fanout": typesafe_meta,
            "ledger": call_if(generated.get("ledger"), lambda: generated["ledger"].as_dict()),
        },
        redact_fn=redact_fn,
        token_fn=token_fn,
        head_fn=head_chars,
        asdict_fn=asdict_fn,
        hardware_class=hardware_class,
        grok_hardware_class=grok_hardware_class,
        grok_paths=grok_tactics_paths,
        typesafe_fanout=typesafe_fanout,
    )


def run_mca_problem(
    *,
    generated: Mapping[str, Any],
    name: str,
    digest: str,
    tactics: str,
    holes: Sequence[Any],
    skeleton: str,
    assemble_fn: Callable[..., Sequence[Mapping[str, Any]]],
    compile_fn: Callable[[str], Mapping[str, Any]],
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    hammer_fn: Callable[..., tuple[list[dict[str, Any]], str, list[Any], bool]],
    needs_hammer_fn: Callable[[str], bool],
    repair_fn: Optional[Callable[..., tuple[list[dict[str, Any]], bool]]] = None,
    ablate_fn: Optional[Callable[[], Sequence[Mapping[str, Any]]]] = None,
    fanout_fn: Optional[Callable[[list[dict[str, Any]], Any], Any]] = None,
    extra_fn: Callable[..., Mapping[str, Any]],
    redact_fn: Callable[[Mapping[str, Any]], Any],
    token_fn: Callable[[str], int],
    head_fn: Callable[[str, int], str],
    asdict_fn: Callable[[Any], Mapping[str, Any]],
    hardware_class: str,
    grok_hardware_class: str,
    grok_paths: Sequence[Any] = (),
    typesafe_fanout: bool = False,
    schema: str = "lra-mca-mask-replace/v1",
) -> dict[str, Any]:
    """Assemble/fanout/compile MCA drafts after generation dispatch. Lake still admits."""

    from jevops.outer import call_if, extend_if, first_truthy, first_where, kind_startswith, replace_if

    grok_few_shot = bool(generated.get("grok_few_shot"))
    leanstral_text = generated.get("leanstral_text")
    holes_for = list(generated.get("holes_for_leanstral") or holes)
    candidates = list(assemble_fn(leanstral_text=None, holes=holes) or ())
    extend_if(
        candidates,
        lambda: list(assemble_fn(leanstral_text=leanstral_text, holes=holes_for) or ()),
        cond=bool(leanstral_text),
        key_fn=lambda item: item["kind"],
    )
    candidates = merge_labeled_candidates(
        candidates,
        list(generated.get("one_hole_fills") or ()),
        list(generated.get("grok_file_rows") or ()),
        extra_rows=(generated.get("few_shot_row"), generated.get("grok_few_shot_row")),
    )
    seed_row = first_where(candidates, kind_startswith("grok"))
    typesafe_meta = call_if(
        typesafe_fanout and seed_row is not None and fanout_fn is not None,
        lambda: fanout_fn(candidates, generated.get("ledger")),
    )
    hw = replace_if(first_truthy(grok_few_shot, grok_paths), grok_hardware_class, hardware_class)
    return finish_mca_problem(
        candidates=candidates,
        compile_fn=compile_fn,
        row_fn=row_fn,
        hammer_fn=hammer_fn,
        needs_hammer_fn=needs_hammer_fn,
        repair_fn=repair_fn,
        ablate_fn=ablate_fn,
        name=name,
        digest=digest,
        holes=[dict(asdict_fn(hole)) for hole in holes],
        skeleton_head=head_fn(skeleton, 800),
        hardware_class=hw,
        ref_tokens=token_fn(tactics),
        extra_fn=lambda grok_ok, grok_tactics, grok_errors: extra_fn(
            grok_ok=grok_ok,
            grok_tactics=grok_tactics,
            grok_errors=grok_errors,
            generated=generated,
            typesafe_meta=typesafe_meta,
        ),
        redact_fn=redact_fn,
        schema=schema,
    )


def diffuse_noise_step(
    *,
    use_leanstral: bool,
    remaining: Sequence[Any],
    rng: Any,
    keep: str,
    keep_tokens: int,
    record: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    name: str,
    ledger_fn: Callable[[int], Any],
    one_hole_prompt_fn: Callable[..., str],
    shrink_prompt_fn: Callable[..., str],
    generate_fn: Callable[..., Any],
    extract_fn: Callable[[str], str],
    flatten_fn: Callable[[str, str], str],
    hammer_fn: Callable[..., str],
    eval_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    skip_exc: Any = (),
    round_i: int = 0,
    hole_id_attr: str = "hole_id",
) -> tuple[Any, str, int]:
    """Leanstral noise then hammer denoise. Generation stays injected. Lake still admits."""

    from jevops.outer import ignore_error, overlay_map, unpack_pair

    if not use_leanstral:
        return None, keep, int(keep_tokens)
    ledger = ledger_fn(int(round_i))
    if remaining:
        hole = rng.choice(list(remaining))
        prompt = one_hole_prompt_fn(record, keep, hole)
        noise_meta = {"hole": getattr(hole, hole_id_attr, hole), "mode": "one_hole"}
    else:
        prompt = shrink_prompt_fn(record, keep, int(keep_tokens), records, name)
        noise_meta = {"hole": None, "mode": "shrink_keep"}
    generated = ignore_error(
        lambda: generate_fn(prompt, ledger),
        skip_exc or (),
        default=None,
    )
    text, identity = unpack_pair(generated, default=("", {}))
    row, tokens, keep_out = denoise_keepbest(
        text=text,
        keep=keep,
        keep_tokens=int(keep_tokens),
        extract_fn=extract_fn,
        flatten_fn=flatten_fn,
        eval_fn=eval_fn,
        hammer_fn=hammer_fn,
        extra=overlay_map(noise_meta, identity=identity),
    )
    return row, keep_out, int(tokens)


def drive_diffuse(
    name: str,
    *,
    state_root: Any,
    timeout: float,
    rounds: int,
    seed: int,
    use_leanstral: bool,
    tau: float,
    load_records_fn: Callable[[], tuple[Any, str, Sequence[Mapping[str, Any]]]],
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[..., str],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    holes_fn: Callable[[str], Sequence[Any]],
    token_fn: Callable[[str], int],
    key_fns: Sequence[Callable[[], Any]],
    leanstral_fns: Sequence[Callable[[], Any]],
    drop_fn: Callable[..., str],
    eval_fn: Callable[..., Sequence[Mapping[str, Any]]],
    jev_fn: Callable[..., Mapping[str, Any]],
    ledger_cls: Callable[..., Any],
    one_prompt_fn: Callable[..., str],
    shrink_prompt_fn: Callable[..., str],
    generate_fn: Callable[..., tuple[str, Any, Any]],
    extract_fn: Callable[[str], str],
    match_fn: Callable[..., str],
    flatten_over_fn: Callable[..., str],
    hammer_fn: Callable[..., str],
    skip_exc: tuple[type[BaseException], ...],
    redact_fn: Callable[[Any], Any],
    hardware_class: str,
    protocol: str,
    pr: str,
) -> dict[str, Any]:
    """Exploit high-p holes, then optional Leanstral noise. ``eval_fn`` owns lake."""

    from jevops.outer import either, load_and_clone, pin_calls
    from jevops.repair import flatten_matched

    held: dict[str, Any] = {}

    def _load(problem: str, *, error_cls: Any) -> tuple[Any, Any, str, Any, Any, bytes]:
        packed = load_and_clone(
            load_records_fn,
            problem,
            state_root,
            clone_fn=clone_fn,
            relpath_fn=relpath_fn,
            error_cls=error_cls,
            miss=f"unknown warm-up problem: {problem}",
        )
        held["restore"] = packed[5]
        return packed

    def _eval(record: Mapping[str, Any], body: str) -> list[dict[str, Any]]:
        return eval_fn(
            record,
            body,
            state_root=state_root,
            timeout=timeout,
            restore=held["restore"],
            reference=tactic_fn(record),
        )

    def _noise(
        round_i: int,
        remaining: Sequence[Any],
        keep: str,
        keep_tokens: int,
        record: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
        rng: Any,
    ) -> tuple[Any, str, int]:
        return diffuse_noise_step(
            use_leanstral=use_leanstral,
            remaining=remaining,
            rng=rng,
            keep=keep,
            keep_tokens=keep_tokens,
            record=record,
            records=records,
            name=name,
            ledger_fn=lambda i: ledger_cls(name=f"{name}#diffuse-r{i}"),
            one_hole_prompt_fn=one_prompt_fn,
            shrink_prompt_fn=shrink_prompt_fn,
            generate_fn=generate_fn,
            extract_fn=extract_fn,
            flatten_fn=flatten_matched(match_fn, flatten_over_fn),
            hammer_fn=lambda noisy, errors: hammer_fn(noisy, tactic_fn(record), errors),
            eval_fn=lambda body: _eval(record, body),
            skip_exc=skip_exc,
            round_i=round_i,
        )

    return run_diffuse_search(
        name,
        load_fn=_load,
        tactic_fn=tactic_fn,
        find_fn=holes_fn,
        token_fn=token_fn,
        pin_fn=pin_calls(*key_fns, *either(use_leanstral, lambda: tuple(leanstral_fns), lambda: ())),
        drop_fn=drop_fn,
        eval_fn=_eval,
        jev_fn=jev_fn,
        noise_fn=_noise,
        rounds=rounds,
        seed=seed,
        tau=tau,
        redact_fn=redact_fn,
        hardware_class=hardware_class,
        protocol=protocol,
        pr=pr,
    )


def run_diffuse_search(
    name: str,
    *,
    load_fn: Callable[..., tuple[Any, Sequence[Any], str, Any, Any, bytes]],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    find_fn: Callable[[str], Sequence[Any]],
    token_fn: Callable[[str], int],
    pin_fn: Callable[[], Any],
    drop_fn: Callable[[str, Sequence[Any], Sequence[str]], str],
    eval_fn: Callable[[Mapping[str, Any], str], Sequence[Mapping[str, Any]]],
    jev_fn: Callable[..., Mapping[str, Any]],
    noise_fn: Callable[..., tuple[Any, str, int]],
    rounds: int,
    seed: int,
    tau: float,
    redact_fn: Callable[[Mapping[str, Any]], Any],
    hardware_class: str,
    protocol: str = "LRA/v1",
    pr: str = "",
    error_cls: Any = RuntimeError,
) -> dict[str, Any]:
    """Keep-best diffuse/denoise search. drop/eval/noise stay injected. Lake is the oracle."""

    from jevops.outer import first_int, replace_if, take_keys
    import random

    rng = random.Random(first_int(seed))
    record, records, digest, _clone, _dest, restore = load_fn(name, error_cls=error_cls)
    started = begin_keep_search(
        record,
        tactic_fn=tactic_fn,
        find_fn=find_fn,
        token_fn=token_fn,
        pin_fn=pin_fn,
    )
    reference, holes, keep, keep_tokens, dropped = take_keys(
        started, "reference", "holes", "keep", "keep_tokens", "dropped"
    )

    def consider(label: str, hole_ids: Sequence[str]) -> dict[str, Any]:
        nonlocal keep, keep_tokens, dropped
        hit, keep_tokens, body, row = trial_keepbest(
            label=label,
            hole_ids=hole_ids,
            dropped=dropped,
            drop_fn=lambda ids: drop_fn(reference, holes, ids),
            eval_fn=lambda trial: eval_fn(record, trial),
            keep_tokens=keep_tokens,
            apply_fn=apply_keepbest,
            strip_fn=strip_tactics,
        )
        keep = replace_if(hit, body, keep)
        return row

    def _noise(round_i: int, remaining: Sequence[Any]) -> Any:
        nonlocal keep, keep_tokens
        row, keep, keep_tokens = noise_fn(
            round_i, remaining, keep, keep_tokens, record, records, rng
        )
        return row

    walked = run_diffuse_rounds(
        holes,
        rounds=rounds,
        tau=tau,
        rng=rng,
        consider_fn=consider,
        jev_fn=lambda remaining, history, tokens: jev_fn(record, remaining, history, tokens),
        noise_fn=_noise,
        keep_tokens=keep_tokens,
        dropped=dropped,
    )
    _keep, keep_tokens, dropped, _history = unpack_walked(walked)
    return redact_fn(
        pack_diffuse(
            name=name,
            digest=digest,
            n_holes=len(holes),
            ref_tokens=token_fn(reference),
            keep_tokens=keep_tokens,
            dropped=dropped,
            rounds=walked["rounds"],
            hardware_class=hardware_class,
            protocol=protocol,
            pr=pr,
        )
    )


def line_swap_from_text(
    *,
    tactics: str,
    index: int,
    text: str,
    parse_fn: Callable[[str], str],
    looks_fn: Callable[[str], bool],
    replace_fn: Callable[[str, int, str], str],
    stop: str,
    target: str,
    head_fn: Callable[[str, int], str],
) -> Optional[dict[str, str]]:
    """Swap one tactic line from generated text. Generation stays injected."""

    nxt = str(parse_fn(text) or "")
    if nxt == stop or not looks_fn(nxt):
        return None
    if nxt.strip() == str(target).strip():
        return None
    body = replace_fn(tactics, int(index), nxt)
    return {
        "kind": "leanstral_swap",
        "tactics": body,
        "note": f"leanstral {head_fn(str(target).strip(), 40)} -> {head_fn(nxt.strip(), 40)}",
    }


def pack_failed_candidate(
    *,
    kind: str,
    generator: str,
    reason: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Skipped/failed candidate row. Lake still admits."""

    out: dict[str, Any] = {
        "kind": str(kind),
        "generator": str(generator),
        "n_chars": 0,
        "tactics_head": "",
        "n_holes": 0,
        "ok": False,
        "theorem_ok": False,
        "module_exit_0": False,
        "exit_code": None,
        "token_count": None,
        "errors": [{"pos": None, "data": str(reason)}],
        "wall_ms": None,
        "skipped": True,
        "reason": str(reason),
    }
    if extra:
        out.update(dict(extra))
    return out


def pack_generated_candidate(
    *,
    kind: str,
    generator: str,
    tactics: str,
    holes: Sequence[Any] = (),
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Label a generated tactic candidate. Generation stays in the consumer."""

    out: dict[str, Any] = {
        "kind": str(kind),
        "generator": str(generator),
        "tactics": tactics,
        "holes": list(holes or ()),
    }
    if extra:
        out.update(dict(extra))
    return out


def merge_labeled_candidates(
    base: Sequence[Mapping[str, Any]],
    *groups: Sequence[Mapping[str, Any]],
    extra_rows: Sequence[Optional[Mapping[str, Any]]] = (),
    unique_fn: Optional[Callable[..., Any]] = None,
) -> list[dict[str, Any]]:
    """Concat labeled candidate groups. unique_fn is injected."""

    rows = [dict(item) for item in base or ()]
    for group in groups:
        extra = [dict(item) for item in group or ()]
        if unique_fn is not None and extra:
            unique_fn(rows, extra, key_fn=lambda item: item.get("kind"))
        else:
            rows.extend(extra)
    for item in extra_rows:
        if item is not None:
            rows.append(dict(item))
    return rows


def collect_grok_fanout_extras(
    seed: str,
    reference: str,
    *,
    tactician_fn: Callable[[str, str], Sequence[Mapping[str, Any]]],
    feature_fn: Callable[[str], Mapping[str, Any]],
    family_fn: Callable[..., Sequence[Any]],
    draft_fn: Callable[..., Sequence[Any]],
    model: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Tactician + PCA drafts from a grok seed. Jev does not write Lean."""

    extras = [dict(item) for item in tactician_fn(seed, reference) or ()]
    features = dict(feature_fn(seed) or {})
    families = list(family_fn(features, model) or ())
    for draft in draft_fn(seed, families, features) or ():
        extras.append(
            {
                "kind": f"pca_{getattr(draft, 'draft_id', '')}_{getattr(draft, 'family', '')}",
                "generator": "pca_mca_fanout",
                "tactics": getattr(draft, "tactics", ""),
                "holes": [],
                "ops": list(getattr(draft, "ops", ()) or ()),
                "source": "grok-file+pca_mca",
            }
        )
    return extras


def load_code_symbol_vector_index(*, setup: Sequence[Any] = ()) -> Any:
    """Live ImportFrom of the advisory vector index. Never writes Lean."""

    for item in setup or ():
        item()
    from ipfs_accelerate_py.agent_supervisor.analysis.code_symbol_vector_index import (
        search_code_symbol_vector_index,
    )

    return search_code_symbol_vector_index


def run_vector_search(
    query: str,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    search_fn: Optional[Callable[..., Any]] = None,
    load_fn: Optional[Callable[[], Any]] = None,
    hit_fn: Callable[..., dict[str, Any]],
    cap: int = 12,
    vector_weight: float = 1.0,
) -> tuple[list[dict[str, Any]], str]:
    """Advisory vector-index search. Loader/search stay injected. Never writes Lean."""

    if snapshot is None:
        return [], "no_vector_snapshot"
    fn = search_fn
    if fn is None:
        if load_fn is None:
            return [], "vector_index_unavailable"
        try:
            fn = load_fn()
        except Exception:
            return [], "vector_index_unavailable"
        if fn is None:
            return [], "vector_index_unavailable"
    try:
        result = fn(snapshot, {"query_text": query, "max_results": int(cap)})
    except Exception as exc:
        from jevops.outer import tagged_exc

        return [], tagged_exc("vector_search_failed", exc)
    return (
        vector_hits_from_result(
            result,
            query=query,
            hit_fn=hit_fn,
            cap=cap,
            vector_weight=float(vector_weight),
        ),
        "vector",
    )


def sidecar_hit_row(
    row: Mapping[str, Any],
    *,
    source: str = "sidecar",
    score: float = 0.72,
) -> dict[str, Any]:
    """Project a sidecar symbol row. Advisory only."""

    return {
        "symbol": row.get("symbol"),
        "source": source,
        "path": row.get("path"),
        "score": float(score),
        "ptr": "",
    }


def eligible_span_counts(
    tactics: str,
    spans: Sequence[int],
    window_fn: Callable[[str, int], Sequence[Any]],
) -> dict[str, int]:
    """Count eligible non-PCA windows per span length."""

    return {f"span_{span}": len(list(window_fn(tactics, int(span)) or ())) for span in spans or ()}


def collect_path_candidates(
    paths: Sequence[Any],
    *,
    load_fn: Callable[[Any], str],
    flatten_fn: Callable[[str], str],
    pack_fn: Callable[..., Mapping[str, Any]],
    generator: str,
    extra: Optional[Mapping[str, Any]] = None,
    kind_prefix: str = "grok_file_",
    stem_n: int = 48,
    head_fn: Optional[Callable[[str, int], str]] = None,
) -> list[dict[str, Any]]:
    """Pack labeled candidates from tactic files. Generation stays injected."""

    rows: list[dict[str, Any]] = []
    for path in paths or ():
        filled = flatten_fn(load_fn(path))
        stem = Path(path).stem
        if head_fn is not None:
            stem = head_fn(stem, int(stem_n))
        row = pack_fn(
            kind=f"{kind_prefix}{stem}",
            generator=generator,
            tactics=filled,
            extra={"source": str(path), **dict(extra or {})},
        )
        rows.append(dict(row))
    return rows


def collect_one_hole_fills(
    targets: Sequence[Any],
    holes: Sequence[Any],
    tactics: str,
    *,
    generate_fn: Callable[[Any], Any],
    parse_fn: Callable[[str, Sequence[Any]], Mapping[str, str]],
    fallback_fn: Callable[[str], str],
    apply_fn: Callable[..., str],
    align_fn: Callable[[str], str],
    pack_fn: Callable[..., Mapping[str, Any]],
    asdict_fn: Callable[[Any], Mapping[str, Any]],
    skip_exc: Any = (),
    generator: str = "",
    kind_fmt: str = "leanstral_one_{id}",
    head_fn: Optional[Callable[[str, int], str]] = None,
    fill_head: int = 400,
) -> tuple[list[dict[str, Any]], Any]:
    """Fill one hole at a time. generate_fn stays in the consumer. Lake still admits."""

    rows: list[dict[str, Any]] = []
    identity: Any = None
    errors = skip_exc if skip_exc else ()
    for hole in targets or ():
        try:
            generated = generate_fn(hole)
        except errors:
            break
        if isinstance(generated, tuple):
            text = str(generated[0] or "")
            if len(generated) > 1:
                identity = generated[1]
        else:
            text = str(generated or "")
        hole_id = str(getattr(hole, "hole_id", hole))
        parsed = dict(parse_fn(text, [hole]) or {})
        fill = str(parsed.get(hole_id) or parsed.get("__full__") or "")
        if not fill.strip():
            fill = str(fallback_fn(text) or "")
        fills = {
            str(getattr(item, "hole_id", item)): (
                fill if str(getattr(item, "hole_id", item)) == hole_id else str(getattr(item, "original", ""))
            )
            for item in holes or ()
        }
        filled = align_fn(apply_fn(tactics, holes, fills))
        fill_view = head_fn(fill, int(fill_head)) if head_fn is not None else fill
        rows.append(
            dict(
                pack_fn(
                    kind=str(kind_fmt).format(id=hole_id),
                    generator=generator,
                    tactics=filled,
                    holes=[dict(asdict_fn(hole)) | {"fill": fill_view}],
                )
            )
        )
    return rows, identity


SHOT_SCORE_FIELDS = {
    "name": "name",
    "ratio": "ratio",
    "filled_tokens": "filled_tokens",
    "ref_tokens": "ref_tokens",
}


def pack_shot_candidate(
    *,
    kind: str,
    generator: str,
    tactics: str,
    shots: Sequence[Any],
    pack_fn: Callable[..., Mapping[str, Any]],
    extra: Optional[Mapping[str, Any]] = None,
    fields: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Pack a few-shot generated candidate. shot_scores stay projected."""

    from jevops.pick import project_items

    row_extra: dict[str, Any] = {
        "n_shots": len(list(shots or ())),
        "shot_scores": project_items(shots, dict(fields or SHOT_SCORE_FIELDS)),
    }
    if extra:
        row_extra.update(dict(extra))
    return dict(pack_fn(kind=kind, generator=generator, tactics=tactics, extra=row_extra))


def after_compile_row(
    rows: list[Any],
    item: Mapping[str, Any],
    compiled: Mapping[str, Any],
    *,
    row_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Any],
    ok_key: str = "theorem_ok",
    hammer_fn: Optional[Callable[[], Any]] = None,
) -> tuple[list[Any], bool]:
    """Append a compile row, then optional hammer rows. Lake still admits."""

    rows.append(row_fn(item, compiled))
    if compiled.get(ok_key):
        return rows, True
    if hammer_fn is None:
        return rows, False
    extra = hammer_fn()
    if isinstance(extra, tuple):
        hammer_rows, *rest = extra
        rows.extend(list(hammer_rows or ()))
        return rows, bool(rest[-1] if rest else False)
    rows.extend(list(extra or ()))
    return rows, False


def holes_or_find(
    holes: Sequence[Any],
    find_fn: Callable[[], Sequence[Any]],
    *,
    kinds: Sequence[str] = (),
    n: int = 8,
    head_fn: Optional[Callable[..., Sequence[Any]]] = None,
    kind_attr: str = "kind",
) -> list[Any]:
    """Use holes, else find and filter by kinds, then cap to n."""

    from jevops.outer import head_seq

    cap = head_fn or head_seq
    rows = list(holes or ())
    if not rows:
        found = list(find_fn() or ())
        if kinds:
            allowed = {str(kind) for kind in kinds}

            def _kind(item: Any) -> str:
                if isinstance(item, Mapping):
                    return str(item.get(kind_attr) or "")
                return str(getattr(item, kind_attr, "") or "")

            rows = [item for item in found if _kind(item) in allowed]
        else:
            rows = found
    return list(cap(rows, int(n)))


def denoise_keepbest(
    *,
    text: str,
    keep: str,
    keep_tokens: int,
    extract_fn: Callable[[str], str],
    flatten_fn: Callable[[str, str], str],
    eval_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    hammer_fn: Callable[[str, Sequence[Any]], str],
    extra: Optional[Mapping[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], int, str]:
    """Extract, flatten, eval, hammer, eval, keep-best. Lake still admits."""

    filled = extract_fn(text) if text else ""
    if not filled:
        return None, int(keep_tokens), keep
    noisy = flatten_fn(keep, filled)
    evals_n = list(eval_fn(noisy) or ())
    errors = (evals_n[0].get("errors") if evals_n else None) or []
    denoised = hammer_fn(noisy, errors)
    evals_d = list(eval_fn(denoised) or ())
    hit, tokens, body = apply_keepbest(evals_n + evals_d, int(keep_tokens), trial=denoised)
    keep_out = body if hit else keep
    row = {
        **dict(extra or {}),
        "accepted": bool(hit),
        "noise_evals": strip_tactics(evals_n),
        "denoise_evals": strip_tactics(evals_d),
    }
    return row, int(tokens if hit else keep_tokens), keep_out


def begin_mcmc(
    *,
    start: str,
    compiled: Mapping[str, Any],
    reference: str,
    token_fn: Callable[[str], int],
    beam: int,
    chain_cls: Any,
    init_kind: str,
) -> dict[str, Any]:
    """Pack start compile into chains/best. Does not compile Lean."""

    start_tok = int(compiled.get("token_count") or token_fn(start))
    start_ok = bool(compiled.get("theorem_ok"))
    ref_tok = int(token_fn(reference))
    return {
        "chains": mcmc_chains(start, start_tok, start_ok, beam, chain_cls),
        "best": init_mcmc_best(
            start=start,
            start_ok=start_ok,
            start_tok=start_tok,
            reference=reference,
            ref_tok=ref_tok,
            kind=init_kind,
        ),
        "start_tok": start_tok,
        "start_ok": start_ok,
        "ref_tok": ref_tok,
        "lake_calls": 1,
        "history": [],
        "failed_bodies": set(),
        "leanstral_calls": 0,
    }


def drive_guided_lines(
    prefix: str,
    reference: str,
    pack: Mapping[str, Any],
    *,
    status_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    header_fn: Callable[[str], Mapping[str, str]],
    remaining_fn: Callable[[str, str, str], Any],
    arm_fn: Callable[[str, str], Any],
    closers: Sequence[str],
) -> list[str]:
    """Next lines from case headers. Does not compile."""

    from jevops.outer import text_or

    headers = header_fn(reference)
    return guided_next(
        prefix,
        status_fn(pack),
        header_of=lambda tag: headers.get(text_or(tag), ""),
        remaining_fn=lambda tag: remaining_fn(prefix, reference, text_or(tag)),
        arm_lines_fn=lambda tag: arm_fn(reference, text_or(tag)),
        closers=closers,
    )


def drive_filter_earliest(
    lines: Sequence[str],
    pack: Mapping[str, Any],
    reference: str,
    *,
    status_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    header_fn: Callable[[str], Mapping[str, str]],
    stop: str,
    closer_pred: Callable[[str], bool],
) -> list[str]:
    """Drop lines that skip the earliest unfinished case. Does not compile."""

    from jevops.outer import text_or

    headers = header_fn(reference)
    return filter_to_earliest(
        lines,
        status_fn(pack),
        header_of=lambda tag: headers.get(text_or(tag), ""),
        stop=stop,
        closer_pred=closer_pred,
        header_match=lambda stripped, earliest: stripped.startswith("case ") and earliest in stripped.split(),
        tag_token_fn=lambda tag: f"case {tag}",
    )


def drive_keepbest_rows(
    record: Mapping[str, Any],
    tactics_list: Sequence[str],
    *,
    state_root: Any,
    timeout: float,
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[[Mapping[str, Any]], str],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    variants_fn: Callable[..., Sequence[str]],
    compile_fn: Callable[..., Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compile keep-best variants. The compiler is injected. Not an admit by itself."""

    from jevops.outer import clone_restore

    _clone, _dest, restore = clone_restore(
        record,
        state_root,
        clone_fn=clone_fn,
        relpath_fn=relpath_fn,
    )
    reference = tactic_fn(record)
    pairs = keepbest_beam_pairs(reference, tactics_list, variants_fn=variants_fn)
    return compile_variant_rows(
        pairs,
        lambda body: compile_fn(
            record,
            body,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
        ),
    )


def drive_line_swap(
    record: Mapping[str, Any],
    tactics: str,
    rng: Any,
    locked_haves: Any,
    *,
    mutable_fn: Callable[..., Sequence[int]],
    generate_fn: Callable[..., Any],
    parse_fn: Callable[[str], str],
    looks_fn: Callable[[str], bool],
    replace_fn: Callable[[str, int, str], str],
    stop: str,
    head_fn: Optional[Callable[[str, int], str]] = None,
    radius: int = 4,
    max_new_tokens: int = 48,
    timeout: float = 90.0,
    allow_owner_exec: bool = False,
) -> Optional[dict[str, str]]:
    """One mutable-line replacement. The generator is injected. Not a lake admit."""

    from jevops.mask import around_lines
    from jevops.outer import get_str, head_chars, pick_line

    idxs = list(mutable_fn(tactics, locked_haves) or ())
    if not idxs:
        return None
    index, target = pick_line(tactics, rng, idxs)
    prompt = (
        "Replace ONE Lean 4 tactic line with a shorter equivalent. "
        "Reply with only that line. No sorry. Keep case/induction.\n\n"
        f"Problem: {get_str(record, 'name')}\n"
        f"Around:\n" + around_lines(tactics, index, radius=radius) + "\n\n"
        f"Replace this line:\n{target}\n\nReplacement:"
    )
    result = generate_fn(
        prompt,
        max_new_tokens=max_new_tokens,
        timeout=timeout,
        source=get_str(record, "source"),
        allow_owner_exec=allow_owner_exec,
    )
    return swap_from_generate(
        result,
        tactics=tactics,
        index=index,
        parse_fn=parse_fn,
        looks_fn=looks_fn,
        replace_fn=replace_fn,
        stop=stop,
        target=target,
        head_fn=head_fn or head_chars,
    )


def swap_from_generate(
    result: Any,
    *,
    tactics: str,
    index: int,
    parse_fn: Callable[[str], str],
    looks_fn: Callable[[str], bool],
    replace_fn: Callable[[str, int, str], str],
    stop: str,
    target: str,
    head_fn: Callable[[str, int], str],
    text_attr: str = "text",
    skipped_attr: str = "skipped",
) -> Optional[dict[str, str]]:
    """Skip empty/skipped generate, else line_swap_from_text. Generation stays injected."""

    if getattr(result, skipped_attr, False) or not getattr(result, text_attr, ""):
        return None
    return line_swap_from_text(
        tactics=tactics,
        index=index,
        text=getattr(result, text_attr),
        parse_fn=parse_fn,
        looks_fn=looks_fn,
        replace_fn=replace_fn,
        stop=stop,
        target=target,
        head_fn=head_fn,
    )


def pin_grok_fanout(
    candidates: list[Any],
    extras: Sequence[Mapping[str, Any]],
    pick: Any,
    *,
    cap: int,
    key_fn: Callable[[Any], Any],
) -> list[Any]:
    """Pin TypeSafe pick then unique-cap extras onto candidates. No Lean."""

    candidates.extend(unique_pin_cap(extras, pick, key_fn=key_fn, cap=int(cap)))
    return candidates


def begin_keep_search(
    record: Mapping[str, Any],
    *,
    tactic_fn: Callable[[Mapping[str, Any]], str],
    find_fn: Callable[[str], Sequence[Any]],
    token_fn: Callable[[str], int],
    pin_fn: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """Start a keep-best hole search. Does not compile Lean."""

    if pin_fn is not None:
        pin_fn()
    reference = tactic_fn(record)
    return {
        "reference": reference,
        "holes": list(find_fn(reference) or ()),
        "keep": reference,
        "keep_tokens": int(token_fn(reference)),
        "history": [],
        "dropped": set(),
        "jevs": [],
    }


def unpack_walked(walked: Mapping[str, Any]) -> tuple[str, int, set[Any], list[Any]]:
    """Unpack keep/tokens/dropped/history from a coordinate or diffuse walk."""

    return (
        str(walked.get("keep") or ""),
        int(walked.get("keep_tokens") or 0),
        set(walked.get("dropped") or ()),
        list(walked.get("history") or ()),
    )


def begin_masked(
    record: Mapping[str, Any],
    *,
    tactic_fn: Callable[[Mapping[str, Any]], str],
    find_fn: Callable[[str], Sequence[Any]],
    mask_fn: Callable[[str, Sequence[Any]], str],
    fill_pred: Optional[Callable[[Any], Any]] = None,
) -> dict[str, Any]:
    """Mask residual holes. Fill predicate stays injected. No Lean writes."""

    from jevops.outer import where

    tactics = tactic_fn(record)
    holes = list(find_fn(tactics) or ())
    return {
        "tactics": tactics,
        "holes": holes,
        "skeleton": mask_fn(tactics, holes),
        "fill_holes": where(holes, fill_pred) if fill_pred is not None else holes,
    }


def flatten_shot(
    *,
    kind: str,
    generator: str,
    text: str,
    shots: Sequence[Any],
    flatten_fn: Callable[[str], str],
    pack_fn: Callable[..., Mapping[str, Any]],
    extra: Optional[Mapping[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    """Flatten generated text and pack a few-shot candidate. No Lean writes."""

    filled = flatten_fn(text)
    return filled, pack_shot_candidate(
        kind=kind,
        generator=generator,
        tactics=filled,
        shots=shots,
        pack_fn=pack_fn,
        extra=extra,
    )


def trial_keepbest(
    *,
    label: str,
    hole_ids: Sequence[str],
    dropped: set[str],
    drop_fn: Callable[[Sequence[str]], str],
    eval_fn: Callable[[str], Sequence[Mapping[str, Any]]],
    keep_tokens: int,
    apply_fn: Callable[..., tuple[Optional[Mapping[str, Any]], int, str]],
    strip_fn: Callable[[Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]],
) -> tuple[bool, int, str, dict[str, Any]]:
    """Drop holes, eval, keep-best. Mutates dropped on hit. Lake still admits."""

    trial = drop_fn(list(dict.fromkeys(list(dropped) + list(hole_ids))))
    evals = list(eval_fn(trial) or ())
    hit, tokens, body = apply_fn(evals, keep_tokens, trial=trial)
    if hit:
        dropped.update(hole_ids)
    row = {
        "label": label,
        "holes": list(hole_ids),
        "accepted": bool(hit),
        "keep_tokens": tokens,
        "evals": list(strip_fn(evals)),
    }
    return bool(hit), int(tokens), body, row


def begin_prefix_search(
    record: Mapping[str, Any],
    *,
    tactic_fn: Callable[[Mapping[str, Any]], str],
    prefix_fn: Callable[[str], str],
    vocab_fn: Callable[[str], Sequence[str]],
) -> tuple[str, str, list[str]]:
    """(tactics, prefix, vocab). Does not compile Lean."""

    tactics = tactic_fn(record)
    return tactics, prefix_fn(tactics), list(vocab_fn(tactics) or ())
