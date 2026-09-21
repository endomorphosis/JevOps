#!/usr/bin/env python3
"""Discrete mask / fill (masked LM, closed-vocab diffusion).

Span windows, CFG score→schedule, skeleton markers, and strictly-shorter
fills. Vocab, tokeniser, and skip-line predicates are injected. No Lean
tables in this module. Jev does not write Lean. Never docker0.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

_WORD = re.compile(r"\S+")


def bracket_inner(text: str, open_end: int, *, open_ch: str = "[", close_ch: str = "]") -> str:
    """Substring of a nested bracket list starting after the opener. Not a parser."""

    blob = str(text or "")
    depth = 1
    index = int(open_end)
    while index < len(blob) and depth:
        char = blob[index]
        if char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
        index += 1
    if depth != 0:
        return blob[int(open_end) :]
    return blob[int(open_end) : index - 1]


def merge_matches(text: str, *named: tuple[str, Any]) -> list[tuple[int, str, Any]]:
    """Collect (start, kind, match) from finditer patterns, sorted by start."""

    events: list[tuple[int, str, Any]] = []
    blob = str(text or "")
    for kind, pattern in named:
        finder = getattr(pattern, "finditer", None)
        if finder is None:
            continue
        for match in finder(blob):
            events.append((match.start(), str(kind), match))
    events.sort(key=lambda item: item[0])
    return events


def word_tokens(text: str) -> list[Any]:
    """Whitespace tokens with .start/.end/.group like re.Match."""

    return list(_WORD.finditer(str(text or "")))


def schedule_for_score(score: Any, table: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map a rubric index (maybe fractional) onto a mask schedule row."""

    rows = list(table or ())
    if not rows:
        return {"id": "empty", "n_masks": 1, "span": 1, "n_shots": 0, "cfg_scale": 0.0}
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    index = int(round(value))
    index = max(0, min(len(rows) - 1, index))
    return dict(rows[index])


def _free(start: int, end: int, occupied: Sequence[tuple[int, int]]) -> bool:
    return all(end <= a or start >= b for a, b in occupied)


def hole(
    *,
    hole_id: str,
    kind: str,
    start: int,
    end: int,
    original: str,
    n_tokens: int = 1,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    row = {
        "hole_id": str(hole_id),
        "kind": str(kind),
        "start": int(start),
        "end": int(end),
        "original": str(original),
        "n_tokens": int(n_tokens),
    }
    if extra:
        row.update(dict(extra))
    return row


def find_literals(
    text: str,
    needles: Sequence[str],
    *,
    kind: str,
    max_holes: int = 24,
    occupied: Optional[list[tuple[int, int]]] = None,
    skip_fn: Optional[Any] = None,
    id_prefix: str = "SYM_",
) -> list[dict[str, Any]]:
    """Non-overlapping literal spans. Longest needles should be passed first."""

    body = str(text or "")
    used = list(occupied or [])
    holes: list[dict[str, Any]] = []
    for needle in needles:
        if not needle or len(holes) >= int(max_holes):
            break
        start = 0
        while True:
            found = body.find(needle, start)
            if found < 0:
                break
            end = found + len(needle)
            if skip_fn is not None and skip_fn(body, found):
                start = found + 1
                continue
            if _free(found, end, used):
                holes.append(
                    hole(
                        hole_id=f"{id_prefix}{len(holes) + len(used)}",
                        kind=kind,
                        start=found,
                        end=end,
                        original=needle,
                    )
                )
                used.append((found, end))
            start = found + 1
            if len(holes) >= int(max_holes):
                break
    return holes


def span_windows(
    text: str,
    span: int,
    *,
    stride: Optional[int] = None,
    tokens: Optional[Sequence[Any]] = None,
    skip_fn: Optional[Any] = None,
    id_prefix: str = "SYM_",
    kind: str = "span",
) -> list[dict[str, Any]]:
    """Token windows of ``span``. Default stride=span (tile). stride=1 overlaps."""

    body = str(text or "")
    span_n = max(1, int(span))
    step = span_n if stride is None else max(1, int(stride))
    toks = list(tokens if tokens is not None else word_tokens(body))
    windows: list[dict[str, Any]] = []
    index = 0
    while index < len(toks):
        tok = toks[index]
        pos = int(tok.start())
        if skip_fn is not None and skip_fn(body, pos):
            index += 1
            continue
        group = []
        cursor = index
        while cursor < len(toks) and len(group) < span_n:
            cur = toks[cursor]
            if skip_fn is not None and skip_fn(body, int(cur.start())):
                break
            group.append(cur)
            cursor += 1
        if len(group) == span_n:
            start, end = int(group[0].start()), int(group[-1].end())
            windows.append(
                hole(
                    hole_id=f"{id_prefix}{len(windows)}",
                    kind=kind,
                    start=start,
                    end=end,
                    original=body[start:end],
                    n_tokens=span_n,
                )
            )
            index += step
        else:
            index += 1
    return windows


def pick_nonoverlapping(
    windows: Sequence[Mapping[str, Any]],
    *,
    n: int,
    reindex: bool = True,
    id_prefix: str = "SYM_",
) -> list[dict[str, Any]]:
    """Evenly sample up to n non-overlapping windows (CFG schedule)."""

    rows = [dict(item) for item in windows or ()]
    want = max(1, int(n))
    if not rows:
        return []
    if len(rows) <= want:
        picked = rows
    else:
        step = len(rows) / float(want)
        picked = []
        occupied: list[tuple[int, int]] = []
        for i in range(want):
            window = rows[min(len(rows) - 1, int(i * step))]
            start, end = int(window["start"]), int(window["end"])
            if any(end > a and start < b for a, b in occupied):
                continue
            occupied.append((start, end))
            picked.append(window)
        if not picked:
            picked = rows[:want]
    if not reindex:
        return picked
    out = []
    for i, item in enumerate(picked):
        row = dict(item)
        row["hole_id"] = f"{id_prefix}{i}"
        out.append(row)
    return out


def default_marker(item: Mapping[str, Any]) -> str:
    return f"<<<{item.get('hole_id')} kind={item.get('kind')}>>>"


def scan_line_holes(
    text: str,
    rules: Sequence[Mapping[str, Any]],
    *,
    id_prefix: str = "MCA_",
) -> list[dict[str, Any]]:
    """Consecutive line runs. Each rule: match(line)->bool, min_run, family."""

    body = str(text or "")
    lines = body.splitlines(keepends=True)
    holes: list[dict[str, Any]] = []
    index = 0
    offset = 0
    while index < len(lines):
        line = lines[index]
        start = offset
        hit = False
        stripped = line.rstrip("\n")
        for rule in rules:
            pred = rule.get("match")
            if pred is None or not pred(stripped):
                continue
            min_run = max(1, int(rule.get("min_run") or 1))
            run = index
            while run < len(lines) and pred(lines[run].rstrip("\n")):
                offset += len(lines[run])
                run += 1
            n = run - index
            if n >= min_run:
                original = "".join(lines[index:run]).rstrip("\n")
                indent_m = re.match(r" *", line)
                family = str(rule.get("family") or "span")
                holes.append(
                    hole(
                        hole_id=f"{id_prefix}{len(holes)}",
                        kind=family,
                        start=start,
                        end=start + len(original),
                        original=original,
                        n_tokens=n,
                        extra={"family": family, "indent": indent_m.group(0) if indent_m else ""},
                    )
                )
            index = run
            hit = True
            break
        if hit:
            continue
        offset += len(line)
        index += 1
    return holes


def mask_skeleton(
    text: str,
    holes: Sequence[Mapping[str, Any]],
    *,
    marker_fn: Optional[Any] = None,
) -> str:
    """Replace holes with markers, right-to-left."""

    mark = marker_fn or default_marker
    out = str(text or "")
    for item in sorted(holes or (), key=lambda row: int(row["start"]), reverse=True):
        out = out[: int(item["start"])] + str(mark(item)) + out[int(item["end"]) :]
    return out


def squeeze_blank_lines(text: str) -> str:
    cleaned: list[str] = []
    blank = 0
    for line in str(text or "").splitlines():
        if not line.strip():
            blank += 1
            if blank <= 1:
                cleaned.append(line)
            continue
        blank = 0
        cleaned.append(line)
    return "\n".join(cleaned).strip("\n")


def apply_named_fills(
    text: str,
    holes: Sequence[Mapping[str, Any]],
    fills: Mapping[str, str],
    *,
    marker_fn: Optional[Any] = None,
) -> str:
    """Mask then substitute fills by hole_id. Squeeze leftover blank lines."""

    mark = marker_fn or default_marker
    out = mask_skeleton(text, holes, marker_fn=mark)
    for item in holes or ():
        fill = fills.get(str(item.get("hole_id")), str(item.get("original") or ""))
        out = out.replace(mark(item), fill, 1)
    return squeeze_blank_lines(out)


def fill_subset(
    text: str,
    holes: Sequence[Mapping[str, Any]],
    chosen: Sequence[str],
    *,
    fill_fn: Any,
    marker_fn: Optional[Any] = None,
) -> str:
    """Apply fill_fn on chosen hole ids; keep original on the rest."""

    want = {str(x) for x in chosen}
    fills = {
        str(item.get("hole_id")): (
            str(fill_fn(item)) if str(item.get("hole_id")) in want else str(item.get("original") or "")
        )
        for item in holes or ()
    }
    return apply_named_fills(text, holes, fills, marker_fn=marker_fn)


def rank_cap(items: Sequence[Any], *, key: Any, cap: int = 6) -> list[Any]:
    return list(sorted(items, key=key))[: max(0, int(cap))]


def apply_fill(text: str, item: Mapping[str, Any], fill: str) -> str:
    return str(text or "")[: int(item["start"])] + str(fill) + str(text or "")[int(item["end"]) :]


def rewrite_runs(
    text: str,
    pred: Any,
    *,
    following_pred: Optional[Any] = None,
    min_collapse: int = 2,
    replacement: Optional[Any] = None,
) -> str:
    """Walk line runs. Drop a run when following_pred matches; else collapse min_collapse."""

    lines = str(text or "").splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        if not pred(lines[index]):
            out.append(lines[index])
            index += 1
            continue
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        run_end = index
        while run_end < len(lines) and pred(lines[run_end]) and lines[run_end].startswith(indent):
            run_end += 1
        skip = run_end
        while skip < len(lines) and not lines[skip].strip():
            skip += 1
        following = lines[skip].strip() if skip < len(lines) else ""
        if following_pred is not None and run_end > index and following_pred(following):
            index = run_end
            continue
        if replacement is not None and run_end - index >= int(min_collapse):
            out.append(str(replacement(indent, lines[index:run_end])))
            index = run_end
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def drop_index(text: str, index: int) -> str:
    lines = str(text or "").splitlines()
    if index < 0 or index >= len(lines):
        return str(text or "")
    del lines[index]
    return "\n".join(lines)


def drop_indices(text: str, indices: Sequence[int]) -> str:
    """Delete line indices from the right. Out-of-range indices are skipped."""

    lines = str(text or "").splitlines()
    for index in sorted({int(i) for i in indices or ()}, reverse=True):
        if 0 <= index < len(lines):
            del lines[index]
    return "\n".join(lines)


def replace_index(text: str, index: int, nxt: str) -> str:
    lines = str(text or "").splitlines()
    if index < 0 or index >= len(lines):
        return str(text or "")
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines[index] = indent + str(nxt).strip()
    return "\n".join(lines)


def mutable_indices(
    text: str,
    *,
    skip_prefix: Sequence[str] = (),
    skip_fn: Optional[Any] = None,
) -> list[int]:
    out: list[int] = []
    for index, line in enumerate(str(text or "").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(head) for head in skip_prefix):
            continue
        if skip_fn is not None and skip_fn(stripped, index):
            continue
        out.append(index)
    return out


def last_duplicate_drops(text: str, *, mutable: Sequence[int]) -> list[tuple[int, str, str]]:
    """Drop the last extra copy of a stripped line that appears more than once."""

    lines = str(text or "").splitlines()
    allowed = set(int(x) for x in mutable)
    counts: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        counts.setdefault(line.strip(), []).append(index)
    out: list[tuple[int, str, str]] = []
    for stripped, idxs in counts.items():
        if len(idxs) < 2 or not stripped:
            continue
        last = idxs[-1]
        if last not in allowed:
            continue
        out.append((last, stripped, drop_index(text, last)))
    return out


def strip_comments(
    text: str,
    *,
    line_mark: str = "--",
    block_open: str = "/-",
    block_close: str = "-/",
) -> str:
    """Strip line comments and nested block comments. Does not search for :=."""

    if not isinstance(text, str) or not text:
        return ""
    out: list[str] = []
    index = 0
    n = len(text)
    block = 0
    line_comment = False
    while index < n:
        if line_comment:
            if text[index] == "\n":
                line_comment = False
                out.append("\n")
            index += 1
            continue
        if block:
            if text.startswith(block_close, index):
                block -= 1
                index += len(block_close)
            elif text.startswith(block_open, index):
                block += 1
                index += len(block_open)
            else:
                index += 1
            continue
        if text.startswith(block_open, index):
            block = 1
            index += len(block_open)
            continue
        if text.startswith(line_mark, index):
            line_comment = True
            index += len(line_mark)
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def strip_fence(text: str, *, fence: str = "```") -> str:
    raw = str(text or "").strip()
    if raw.startswith(fence):
        lines = raw.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith(fence):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        raw = "\n".join(lines).strip()
    return raw


def split_before_markers(text: str, markers: Sequence[str]) -> str:
    raw = str(text or "")
    for marker in markers:
        if marker in raw:
            raw = raw.split(marker, 1)[0].strip()
    return raw


def drop_matching_line(text: str, pred: Any, *, last: bool = False) -> Optional[str]:
    lines = str(text or "").splitlines()
    idxs = range(len(lines) - 1, -1, -1) if last else range(len(lines))
    for index in idxs:
        if pred(lines[index]):
            del lines[index]
            return "\n".join(lines)
    return None


def join_consecutive_lines(text: str, pred: Any, *, joiner: Any, same_indent: bool = False) -> str:
    """Join two consecutive matching lines. joiner(indent, a, b)->str."""

    lines = str(text or "").splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        if pred(lines[index]) and index + 1 < len(lines) and pred(lines[index + 1]):
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            nxt_indent = lines[index + 1][: len(lines[index + 1]) - len(lines[index + 1].lstrip())]
            if same_indent and indent != nxt_indent:
                out.append(lines[index])
                index += 1
                continue
            out.append(str(joiner(indent, lines[index], lines[index + 1])))
            index += 2
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def filter_keepends(text: str, drop_fn: Any) -> str:
    """drop_fn(line, start, end)->bool. Keepends-aware."""

    lines = str(text or "").splitlines(keepends=True)
    offset = 0
    keep: list[str] = []
    for line in lines:
        start, end = offset, offset + len(line)
        if not drop_fn(line, start, end):
            keep.append(line)
        offset = end
    return "".join(keep).strip("\n")


def filter_after_flag(text: str, flag_pred: Any, drop_pred: Any) -> str:
    """After flag_pred(stripped) fires, drop lines where drop_pred(line, start, end)."""

    flagged = False

    def _drop(line: str, start: int, end: int) -> bool:
        nonlocal flagged
        if flag_pred(line.strip()):
            flagged = True
            return False
        return bool(flagged and drop_pred(line, start, end))

    return filter_keepends(text, _drop)


def _span_get(span: Any, key: str) -> Any:
    if isinstance(span, Mapping):
        return span[key]
    return getattr(span, key)


def capture_after_header(
    text: str,
    header_id: str,
    *,
    is_header: Any,
    id_of: Any,
) -> list[str]:
    """Collect non-empty stripped lines after the matching header until the next header."""

    capturing = False
    body: list[str] = []
    want = str(header_id or "")
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if is_header(stripped):
            capturing = str(id_of(stripped)) == want
            continue
        if capturing and stripped:
            body.append(stripped)
    return body


def split_before(text: str, pred: Any) -> tuple[list[str], list[str]]:
    """Split lines into (pre, rest) at the first line matching pred."""

    pre: list[str] = []
    rest: list[str] = []
    hit = False
    for line in str(text or "").splitlines():
        if not hit and pred(line):
            hit = True
        (rest if hit else pre).append(line)
    return pre, rest


def top_level_labels(
    spans: Sequence[Any],
    *,
    tag_fn: Any,
) -> list[str]:
    if not spans:
        return []
    top = min(int(_span_get(span, "indent")) for span in spans)
    tags: list[str] = []
    for span in spans:
        if int(_span_get(span, "indent")) != top:
            continue
        tag = str(tag_fn(span))
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def header_map(
    text: str,
    spans: Sequence[Any],
    *,
    tag_fn: Any,
) -> dict[str, str]:
    if not spans:
        return {}
    top = min(int(_span_get(span, "indent")) for span in spans)
    headers: dict[str, str] = {}
    body = str(text or "")
    for span in spans:
        if int(_span_get(span, "indent")) != top:
            continue
        tag = str(tag_fn(span))
        start = int(_span_get(span, "start"))
        header_end = int(_span_get(span, "header_end"))
        header = body[start:header_end].splitlines()[0].rstrip() if body[start:header_end] else ""
        if tag:
            headers[tag] = header
    return headers


def span_body_lines(text: str, spans: Sequence[Any], tag: str, *, tag_fn: Any) -> list[str]:
    want = str(tag or "").split()[0]
    body = str(text or "")
    for span in spans:
        if str(tag_fn(span)).split()[0] != want:
            continue
        chunk = body[int(_span_get(span, "header_end")) : int(_span_get(span, "end"))]
        return [line.rstrip() for line in chunk.splitlines() if line.strip()]
    return []


def nested_header_spans(
    text: str,
    matches: Sequence[Any],
    *,
    indent_of: Any,
    label_of: Any,
) -> list[dict[str, Any]]:
    """Nested header spans: a header ends at the next header of equal or smaller indent."""

    body = str(text or "")
    spans: list[dict[str, Any]] = []
    rows = list(matches or ())
    for index, match in enumerate(rows):
        indent = int(indent_of(match))
        end = len(body)
        for nxt in rows[index + 1 :]:
            if int(indent_of(nxt)) <= indent:
                end = int(nxt.start())
                break
        header_end = int(match.end())
        if header_end < len(body) and body[header_end] == "\n":
            header_end += 1
        spans.append(
            {
                "label": str(label_of(match)),
                "start": int(match.start()),
                "header_end": header_end,
                "end": end,
                "indent": indent,
            }
        )
    return spans


def replace_span(text: str, header_end: int, end: int, body: str, *, indent: str) -> str:
    replacement = str(indent) + str(body).strip() + "\n"
    return str(text or "")[: int(header_end)] + replacement + str(text or "")[int(end) :]


def lines_until(text: str, collect_pred: Any, stop_pred: Any) -> list[str]:
    out: list[str] = []
    for line in str(text or "").splitlines():
        if stop_pred(line):
            break
        if collect_pred(line):
            out.append(line)
    return out


def insert_before(
    text: str,
    extra_lines: Sequence[str],
    pred: Any,
    *,
    if_missing: str = "prepend",
) -> str:
    """Insert extra_lines before the first line matching pred."""

    present = {line.strip() for line in str(text or "").splitlines()}
    missing = [line for line in extra_lines if str(line).strip() not in present]
    if not missing:
        return str(text or "")
    out: list[str] = []
    inserted = False
    for line in str(text or "").splitlines():
        if not inserted and pred(line):
            out.extend(missing)
            inserted = True
        out.append(line)
    if not inserted:
        out = list(missing) + out if if_missing == "prepend" else out + list(missing)
    return "\n".join(out)


def keep_matching_lines(
    text: str,
    pred: Any,
    *,
    cap: Optional[int] = None,
    fallback: Optional[str] = None,
) -> str:
    """Keep lines matching pred, optional cap. Empty keep returns fallback or original."""

    kept = [line for line in str(text or "").splitlines() if pred(line)]
    if cap is not None:
        kept = kept[: int(cap)]
    if not kept:
        return str(text or "") if fallback is None else fallback
    return "\n".join(kept)


def unique_vocab(text: str, extras: Sequence[str] = ()) -> list[str]:
    seen: set[str] = set()
    vocab: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        vocab.append(line.rstrip())
    for extra in extras:
        if extra not in seen:
            vocab.append(str(extra))
            seen.add(str(extra))
    return vocab


def collapse_runs(
    text: str,
    pred: Any,
    *,
    min_run: int = 2,
    replacement: Any,
) -> str:
    """Replace consecutive same-indent lines matching pred. replacement(indent, run_lines)->str."""

    lines = str(text or "").splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not pred(line):
            out.append(line)
            index += 1
            continue
        indent = line[: len(line) - len(line.lstrip())]
        start = index
        while index < len(lines) and pred(lines[index]) and lines[index].startswith(indent):
            index += 1
        run = lines[start:index]
        if len(run) >= int(min_run):
            out.append(str(replacement(indent, run)))
        else:
            out.extend(run)
    return "\n".join(out)


def drop_span(text: str, start: int, end: int) -> str:
    """Delete [start:end] and strip. No Lean."""

    return (str(text or "")[: int(start)] + str(text or "")[int(end) :]).strip("\n")


def parse_marked_fills(
    text: str,
    holes: Sequence[Any],
    *,
    attr: str = "kind",
    fallback_fn: Optional[Any] = None,
) -> dict[str, str]:
    """Parse <<<id attr=...>>> fill blocks. Optional fallback for a whole-block reply."""

    blob = str(text or "")
    fills: dict[str, str] = {}
    for item in holes or ():
        if isinstance(item, Mapping):
            hid = str(item.get("hole_id") or "")
            val = str(item.get(attr) or item.get("kind") or "")
        else:
            hid = str(getattr(item, "hole_id", "") or "")
            val = str(getattr(item, attr, None) or getattr(item, "kind", "") or "")
        if not hid:
            continue
        pattern = re.compile(
            rf"<<<{re.escape(hid)}(?: {re.escape(attr)}={re.escape(val)})?>>>\s*(.*?)(?=<<<|\Z)",
            re.S,
        )
        match = pattern.search(blob)
        if match:
            body = match.group(1).strip()
            if body:
                fills[hid] = body
    if fills:
        return fills
    if fallback_fn is not None:
        extra = fallback_fn(blob)
        if extra and str(extra).strip():
            fills["__full__"] = str(extra).strip("\n")
    return fills


def unique_fills(fills: Sequence[str], *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for fill in fills:
        if fill not in seen:
            seen.add(fill)
            out.append(str(fill))
        if len(out) >= int(limit):
            break
    return out


def shorter_fills(
    text: str,
    holes: Sequence[Mapping[str, Any]],
    *,
    fills_fn: Any,
    token_fn: Any,
    max_candidates: int = 32,
    generator: str = "closed_vocab",
) -> list[dict[str, Any]]:
    """One-hole closed fills that are strictly shorter. fills_fn/token_fn injected."""

    from jevops.outer import head_chars

    body = str(text or "")
    current = int(token_fn(body))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in holes or ():
        for fill in list(fills_fn(item, body) or ()):
            if fill == item.get("original"):
                continue
            nxt = apply_fill(body, item, fill).strip("\n")
            tok = int(token_fn(nxt))
            if tok >= current or nxt in seen:
                continue
            seen.add(nxt)
            rows.append(
                {
                    "kind": f"{item.get('hole_id')}_{item.get('kind')}_{head_chars(fill, 24) or 'drop'}",
                    "hole_id": item.get("hole_id"),
                    "hole_kind": item.get("kind"),
                    "original": item.get("original"),
                    "fill": fill,
                    "tactics": nxt,
                    "token_count": tok,
                    "generator": generator,
                    "llm": "off",
                }
            )
            if len(rows) >= int(max_candidates):
                return rows
    return rows


def fill_all_shortest(
    text: str,
    holes: Sequence[Mapping[str, Any]],
    *,
    fills_fn: Any,
    token_fn: Any,
    schedule_id: str = "cfg",
) -> Optional[dict[str, Any]]:
    """Apply one shortest closed fill at every hole (right-to-left)."""

    if not holes:
        return None
    body = str(text or "")
    fills: dict[str, str] = {}
    for item in sorted(holes, key=lambda row: int(row["start"]), reverse=True):
        alts = [fill for fill in list(fills_fn(item, text) or ()) if fill != item.get("original")]
        if not alts:
            continue
        fill = min(alts, key=lambda value: (int(token_fn(value)), len(str(value))))
        body = body[: int(item["start"])] + fill + body[int(item["end"]) :]
        fills[str(item.get("hole_id"))] = fill
    body = body.strip("\n")
    tok = int(token_fn(body))
    if not fills or tok >= int(token_fn(text)):
        return None
    return {
        "kind": f"multihole_{schedule_id}",
        "tactics": body,
        "token_count": tok,
        "fills": fills,
        "n_holes": len(fills),
        "generator": "closed_vocab",
        "llm": "off",
        "schedule_id": schedule_id,
    }


def starts_any(
    text: str,
    prefixes: Sequence[str] = (),
    *,
    exact: Sequence[str] = (),
) -> bool:
    """True if stripped text is in exact or startswith any prefix."""

    key = str(text or "").strip()
    if key in {str(item) for item in exact}:
        return True
    return any(key.startswith(str(prefix)) for prefix in prefixes)


def lstrip_core(text: str, chars: str = "·. ") -> str:
    return str(text or "").lstrip(chars).strip()


def line_at(text: str, pos: int) -> str:
    """The line that contains offset ``pos`` (no trailing newline)."""

    blob = str(text or "")
    index = max(0, min(len(blob), int(pos)))
    start = blob.rfind("\n", 0, index) + 1
    end = blob.find("\n", index)
    if end < 0:
        end = len(blob)
    return blob[start:end]


def pick_scored(
    windows: Sequence[Mapping[str, Any]],
    *,
    n: int,
    score_fn: Any,
    reindex: bool = True,
    id_prefix: str = "SYM_",
) -> list[dict[str, Any]]:
    """Highest score_fn first, then start; skip overlapping windows."""

    rows = [dict(item) for item in windows or ()]
    want = max(1, int(n))
    ranked = sorted(
        rows,
        key=lambda row: (-float(score_fn(row)), int(row.get("start") or 0)),
    )
    picked: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for window in ranked:
        start, end = int(window.get("start") or 0), int(window.get("end") or 0)
        if not _free(start, end, occupied):
            continue
        occupied.append((start, end))
        picked.append(window)
        if len(picked) >= want:
            break
    if not reindex:
        return picked
    out: list[dict[str, Any]] = []
    for index, item in enumerate(picked):
        row = dict(item)
        row["hole_id"] = f"{id_prefix}{index}"
        out.append(row)
    return out


def fold_following(
    text: str,
    marker_pred: Any,
    follow_pred: Any,
    *,
    n_follow: int = 2,
    replacement: Any,
) -> Optional[str]:
    """Replace a marker line plus n_follow matching lines. First hit only."""

    lines = str(text or "").splitlines()
    count = max(0, int(n_follow))
    for index, line in enumerate(lines):
        if not marker_pred(line):
            continue
        following: list[str] = []
        ok = True
        for offset in range(1, count + 1):
            if index + offset >= len(lines):
                ok = False
                break
            nxt = lines[index + offset].strip()
            if not follow_pred(nxt):
                ok = False
                break
            following.append(lines[index + offset])
        if not ok:
            continue
        indent = line[: len(line) - len(line.lstrip())]
        folded = replacement(indent, line, following)
        if folded is None:
            continue
        return "\n".join(lines[:index] + [str(folded)] + lines[index + count + 1 :])
    return None


def around_lines(text: str, index: int, *, radius: int = 4) -> str:
    """Lines around ``index`` (inclusive), clipped to the text."""

    lines = str(text or "").splitlines()
    if not lines:
        return ""
    cursor = max(0, min(len(lines) - 1, int(index)))
    start = max(0, cursor - int(radius))
    end = min(len(lines), cursor + int(radius) + 1)
    return "\n".join(lines[start:end])


def map_span_bodies(
    text: str,
    spans: Sequence[Any],
    transform: Any,
    *,
    indent_key: str = "indent",
    header_end_key: str = "header_end",
    end_key: str = "end",
    top_only: bool = True,
) -> list[tuple[Any, str]]:
    """Apply transform(body, span). Returns (span, rewritten_text) when the body changes."""

    blob = str(text or "")
    rows = list(spans or ())
    if not rows:
        return []
    if top_only:
        top = min(int(_span_get(span, indent_key)) for span in rows)
        rows = [span for span in rows if int(_span_get(span, indent_key)) == top]
    out: list[tuple[Any, str]] = []
    for span in rows:
        start = int(_span_get(span, header_end_key))
        end = int(_span_get(span, end_key))
        body = blob[start:end]
        nxt = transform(body, span)
        if nxt is None or nxt == body:
            continue
        out.append((span, blob[:start] + str(nxt) + blob[end:]))
    return out


def prepend_absent(text: str, line: str) -> str:
    """Prepend ``line`` when its stripped form is not already present."""

    pick = str(line or "")
    body = str(text or "")
    if not pick.strip():
        return body
    present = {row.strip() for row in body.splitlines()}
    if pick.strip() in present:
        return body
    return pick + "\n" + body


def lines_containing(text: str, needle: str, *, token: bool = False) -> list[str]:
    """Lines that contain ``needle``, optionally as a whitespace token."""

    want = str(needle or "")
    out: list[str] = []
    for line in str(text or "").splitlines():
        if token:
            if want in line.split():
                out.append(line)
        elif want in line:
            out.append(line)
    return out


def any_line(text: str, pred: Any) -> bool:
    return any(pred(line) for line in str(text or "").splitlines())


def split_top_level(
    text: str,
    *,
    sep: str = ",",
    opens: str = "([{",
    closes: str = ")]}",
) -> list[str]:
    """Split on sep at depth 0. Nested ([{ }]) stay inside a part. Skip empty."""

    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for char in str(text or ""):
        if char in opens:
            depth += 1
            buf.append(char)
        elif char in closes:
            depth = max(0, depth - 1)
            buf.append(char)
        elif char == sep and depth == 0:
            item = "".join(buf).strip()
            if item:
                parts.append(item)
            buf = []
        else:
            buf.append(char)
    item = "".join(buf).strip()
    if item:
        parts.append(item)
    return parts


def drop_spans(text: str, spans: Sequence[Any], *, eat_newline: bool = False) -> str:
    """Delete [start:end] spans from the right. Optional trailing newline after each."""

    blob = str(text or "")
    bounds: list[tuple[int, int]] = []
    for span in spans or ():
        if isinstance(span, Mapping) or hasattr(span, "start"):
            start, end = int(_span_get(span, "start")), int(_span_get(span, "end"))
        else:
            start, end = int(span[0]), int(span[1])
        bounds.append((start, end))
    out = blob
    for start, end in sorted(bounds, reverse=True):
        if eat_newline and end < len(out) and out[end] == "\n":
            end += 1
        out = out[:start] + out[end:]
    return out


def splice_from(dst: str, src: str, dst_span: Any, src_span: Any) -> str:
    """Replace dst[dst_span] with src[src_span]. Missing span → dst unchanged."""

    if dst_span is None or src_span is None:
        return str(dst or "")
    d0, d1 = int(_span_get(dst_span, "start")), int(_span_get(dst_span, "end"))
    s0, s1 = int(_span_get(src_span, "start")), int(_span_get(src_span, "end"))
    return str(dst or "")[:d0] + str(src or "")[s0:s1] + str(dst or "")[d1:]


def pop_trailing(text: str, pred: Any) -> str:
    """Drop trailing lines while pred(line) is true."""

    lines = str(text or "").splitlines()
    while lines and pred(lines[-1]):
        lines.pop()
    return "\n".join(lines)


def rewrite_matching_lines(text: str, pred: Any, replacement: Any) -> str:
    """replacement(indent, stripped, line)->str|None. None drops the line."""

    out: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if pred(stripped):
            indent = line[: len(line) - len(line.lstrip())]
            nxt = replacement(indent, stripped, line)
            if nxt is None:
                continue
            out.append(str(nxt))
            continue
        out.append(line)
    return "\n".join(out)


def subn_changed(text: str, pattern: Any, repl: Any, *, count: int = 0) -> str:
    """re.subn / Pattern.subn. Unchanged text when n==0."""

    blob = str(text or "")
    if hasattr(pattern, "subn"):
        nxt, n = pattern.subn(repl, blob, count)
    else:
        nxt, n = re.subn(pattern, repl, blob, count=count)
    return nxt if n else blob


def peek_next_stripped(lines: Sequence[str], index: int) -> str:
    """Next non-empty stripped line after index, else ''."""

    cursor = int(index) + 1
    while cursor < len(lines) and not str(lines[cursor]).strip():
        cursor += 1
    if cursor >= len(lines):
        return ""
    return str(lines[cursor]).strip()


def map_lines(text: str, fn: Any, *, changed_only: bool = True) -> str:
    """fn(index, line, lines)->Optional[str]. None keeps the original line."""

    blob = str(text or "")
    lines = blob.splitlines()
    out: list[str] = []
    changed = False
    for index, line in enumerate(lines):
        nxt = fn(index, line, lines)
        if nxt is None:
            out.append(line)
            continue
        if nxt != line:
            changed = True
        out.append(str(nxt))
    joined = "\n".join(out)
    return joined if (changed or not changed_only) else blob


def default_token_fills(item: Mapping[str, Any], text: str, *, limit: int = 8) -> list[str]:
    """Generic MLM fills: drop, then other in-document tokens that are not longer."""

    original = str(item.get("original") or "")
    fills = [""]
    seen = {original}
    for tok in word_tokens(text):
        value = tok.group(0)
        if value in seen or len(value) > len(original):
            continue
        seen.add(value)
        fills.append(value)
        if len(fills) >= int(limit):
            break
    return unique_fills(fills, limit=limit)


def reindex_holes(holes: Sequence[Any], *, rehole_fn: Any) -> list[Any]:
    """Rewrite hole ids in start order. rehole_fn(item, index) is injected."""

    rows = list(holes or ())
    rows.sort(key=lambda item: int(getattr(item, "start", None) if hasattr(item, "start") else item["start"]))
    return [rehole_fn(item, index) for index, item in enumerate(rows)]


def one_hole_shots(
    *,
    phrase_alts: Sequence[tuple[str, str]],
    operator_alts: Mapping[str, Sequence[str]],
    span: int,
    n_shots: int,
    token_fn: Any,
) -> list[dict[str, Any]]:
    """Few-shot one-hole fills whose original length is close to ``span``."""

    scored: list[tuple[int, int, str, str]] = []
    for src, dst in phrase_alts or ():
        n_tok = int(token_fn(src))
        scored.append((abs(n_tok - int(span)), n_tok, src, dst))
    scored.sort()
    shots: list[dict[str, Any]] = []
    for _dist, n_tok, src, dst in scored:
        shots.append(
            {
                "note": f"one-hole span~{n_tok}: {src} -> {dst}",
                "skeleton": "    <<<SYM_0 kind=span>>>",
                "fills": {"SYM_0": dst},
                "holes": [{"id": "SYM_0", "kind": "span", "original": src, "fill": dst}],
                "n_holes": 1,
            }
        )
        if len(shots) >= int(n_shots):
            break
    if int(span) <= 2:
        for op, alts in dict(operator_alts or {}).items():
            if len(shots) >= int(n_shots):
                break
            fill = alts[0] if alts else ""
            if fill == op:
                continue
            shown = repr(fill) if fill else "drop"
            shots.append(
                {
                    "note": f"one-hole operator {op!r} -> {shown}",
                    "skeleton": "    <<<SYM_0 kind=operator>>>",
                    "fills": {"SYM_0": fill},
                    "holes": [{"id": "SYM_0", "kind": "operator", "original": op, "fill": fill}],
                    "n_holes": 1,
                }
            )
    return shots[: int(n_shots)]


def catalog_shots(
    tactics: str,
    *,
    phrase_alts: Sequence[tuple[str, str]],
    n_shots: int,
    head_fn: Any,
) -> list[dict[str, Any]]:
    """Few-shot multi-hole fills from cataloged phrase cuts."""

    present = [(src, dst) for src, dst in phrase_alts if src in tactics]
    pool = present or list(phrase_alts)
    shots: list[dict[str, Any]] = []
    if len(pool) >= 2:
        pairs = list(head_fn(pool, 3) or ())
        items: list[tuple[int, int, int, str, str]] = []
        used: list[tuple[int, int]] = []
        for i, (src, dst) in enumerate(pairs):
            found = tactics.find(src) if src in tactics else -1
            if found < 0:
                excerpt = f"    {src}"
                items.append((0, len(excerpt), i, src, dst))
                continue
            end = found + len(src)
            if any(end > a and found < b for a, b in used):
                continue
            used.append((found, end))
            items.append((found, end, i, src, dst))
        in_script = [item for item in items if item[3] in tactics]
        if len(in_script) >= 2:
            skeleton = tactics
            fills: dict[str, str] = {}
            holes: list[dict[str, Any]] = []
            spans = [(start, end) for start, end, _i, _src, _dst in in_script]
            for start, end, i, src, dst in sorted(in_script, key=lambda row: row[0], reverse=True):
                hid = f"SYM_{i}"
                skeleton = skeleton[:start] + f"<<<{hid} kind=phrase>>>" + skeleton[end:]
                fills[hid] = dst
                holes.append({"id": hid, "kind": "phrase", "original": src, "fill": dst})
            lo = max(0, min(span[0] for span in spans) - 80)
            hi = min(len(skeleton), max(span[1] for span in spans) + 80 + 40)
            shots.append(
                {
                    "note": "multi-hole phrase fills from the 268→139 catalog",
                    "skeleton": skeleton[lo:hi],
                    "fills": fills,
                    "holes": list(reversed(holes)),
                    "n_holes": len(holes),
                }
            )
    for src, dst in pool:
        if len(shots) >= int(n_shots):
            break
        shots.append(
            {
                "note": f"{src} -> {dst}",
                "skeleton": "    <<<SYM_0 kind=phrase>>>",
                "fills": {"SYM_0": dst},
                "holes": [{"id": "SYM_0", "kind": "phrase", "original": src, "fill": dst}],
                "n_holes": 1,
            }
        )
    return shots[: int(n_shots)]


def shot_fill_prompt(
    record: Mapping[str, Any],
    skeleton: str,
    holes: Sequence[Any],
    shots: Sequence[Mapping[str, Any]],
    *,
    preamble: str,
    reply: str,
) -> str:
    """Few-shot multi-hole fill prompt. Catalog preamble stays in the consumer."""

    from jevops.outer import head_tail

    blocks: list[str] = []
    for index, shot in enumerate(shots or (), 1):
        fill_lines: list[str] = []
        for hole in shot.get("holes") or []:
            hid = hole.get("id") or hole.get("hole_id")
            kind = hole.get("kind") or "phrase"
            fill_lines.append(f"<<<{hid} kind={kind}>>>\n{hole.get('fill')}\n")
        skel = head_tail(shot.get("skeleton") or "", 600, 400, limit=1200)
        blocks.append(
            f"EXAMPLE {index} ({shot.get('note')}): {shot.get('n_holes')} holes, lake-valid shorter fill.\n"
            f"SKELETON:\n{skel}\n"
            f"FILLS:\n{''.join(fill_lines)}"
        )
    docs: list[str] = []
    for hole in holes or ():
        hole_id = getattr(hole, "hole_id", None)
        kind = getattr(hole, "kind", None)
        n_tokens = getattr(hole, "n_tokens", None)
        original = getattr(hole, "original", None)
        if hole_id is None and isinstance(hole, Mapping):
            hole_id = hole.get("hole_id")
            kind = hole.get("kind")
            n_tokens = hole.get("n_tokens")
            original = hole.get("original")
        docs.append(f"{hole_id} kind={kind} n_tokens={n_tokens} ORIGINAL={original!r}\n")
    return (
        str(preamble or "")
        + "\n".join(blocks)
        + f"\nTARGET: {record.get('name')}\n"
        f"SKELETON:\n{skeleton}\n\n"
        f"HOLES:\n{''.join(docs)}\n"
        + str(reply or "")
    )


def closed_multihole_row(
    text: str,
    holes: Sequence[Any],
    *,
    schedule_id: str,
    fills_fn: Any,
    token_fn: Any,
    as_row_fn: Any,
    generator: str = "closed_lean_vocab",
) -> Optional[dict[str, Any]]:
    """Apply one shorter closed fill at every selected span together."""

    from jevops.outer import head_chars

    rows = [as_row_fn(item) for item in holes or ()]
    packed = fill_all_shortest(
        text, rows, fills_fn=fills_fn, token_fn=token_fn, schedule_id=schedule_id
    )
    if not packed:
        return None
    packed["kind"] = f"sweep_{schedule_id}_closed"
    packed["hole_id"] = schedule_id
    packed["hole_kind"] = "span"
    packed["original"] = ",".join(head_chars(row.get("original"), 24) for row in rows)
    packed["fill"] = ",".join(
        f"{hid}->{head_chars(val, 16) or 'drop'}" for hid, val in dict(packed.get("fills") or {}).items()
    )
    packed["generator"] = generator
    packed["n_masks"] = len(list(holes or ()))
    return packed


def kernel_one_hole_rows(
    tactics: str,
    *,
    propose_fn: Any,
    token_fn: Any,
    spans: Sequence[int],
) -> list[dict[str, Any]]:
    """One catalog kernel per candidate: a single aligned span of varying length."""

    current_tok = int(token_fn(tactics))
    rows: list[dict[str, Any]] = []
    options = list(spans or ())
    for item in list(propose_fn(tactics) or ()):
        body = str(item.get("tactics") or "").strip("\n")
        tok = int(token_fn(body))
        if not body or tok >= current_tok:
            continue
        cut = current_tok - tok
        span = options[-1] if options else 6
        for option in options:
            if cut <= int(option):
                span = option
                break
        rows.append(
            {
                "kind": f"kernel_{item['kind']}",
                "hole_id": str(item["kind"]),
                "hole_kind": "span",
                "original": str(item.get("note") or item["kind"]),
                "fill": str(item["kind"]),
                "tactics": body,
                "token_count": tok,
                "generator": "closed_lean_vocab",
                "llm": "off",
                "n_masks": 1,
                "n_shots": 6,
                "span": span,
                "cfg_scale": 1.5,
                "schedule_id": f"kernel_{item['kind']}",
                "family": item.get("family"),
            }
        )
    return rows
