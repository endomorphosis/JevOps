#!/usr/bin/env python3
"""Coordinate search / keep-best accept / prefix beam helpers.

Lake (or another oracle) still admits. Jev does not write Lean. Never docker0.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


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
    row = {
        "kind": kind,
        "generator": "deterministic",
        "n_chars": len(body),
        "tactics_head": body[:240],
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

    from jevops.outer import run_process

    binary = rg or shutil.which("rg")
    if not binary:
        return [], "rg_missing"
    match = ident_re.search(query) if ident_re is not None else None
    needle = match.group(0) if match else str(query)[:40]
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
            hits.append(hit_fn(symbol, path=path, snippet=snippet[:160]))
        else:
            hits.append({"symbol": symbol, "path": path, "line": snippet[:160]})
    return hits, "rg"
