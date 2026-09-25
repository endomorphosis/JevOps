"""Position-bound Lean suggestions, independently replayed before admission.

Compiler diagnostics are hints, not certificates. The legacy harvester retains
its single-line contract. The opt-in Arena path also nominates bounded
straight-line scripts and support deletions for independent whole-source replay.
No imports/options/headers are edited. No global minimality is claimed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

QUERY = re.compile(r"^([ ]*)(simp_all|simp|simpa|dsimp|grind|linarith|nlinarith)(?=\s|$)")
REPLAY = re.compile(r"^(?:simp_all|simp|simpa|dsimp|grind|linarith|nlinarith|exact|rfl|assumption)(?=\s|$)")


@dataclass(frozen=True)
class SolverEdit:
    """A source-bound syntactic nomination, never a proof or cost receipt."""
    source_sha256: str
    start: int
    end: int
    replacement: str
    kind: str

    def apply(self, source: str) -> str:
        if (source_digest(source) != self.source_sha256 or type(self.start) is not int
                or type(self.end) is not int or not 0 <= self.start < self.end <= len(source)):
            raise ValueError("stale solver edit")
        return source[:self.start] + self.replacement + source[self.end:]


# Deliberately small syntax subset, not an alternate Lean parser. Names and
# common rewrite-direction/pattern modifiers only; nested terms abstain.
_PREMISE = r"(?:(?:←|→|↓|↑|=)\s*)?(?:_root_\.)?[^\W\d][\w']*(?:\.[^\W\d][\w']*)*"
_LOCATION = r"(?:\*|(?:⊢|[^\W\d][\w']*)(?:\s+(?:⊢|[^\W\d][\w']*))*)"
# The deletion path remains single-line. Accept the same bounded location
# grammar as suggestions, but never let whitespace consume a newline here.
_ONLY = re.compile(r"( *)(simp_all|simp|dsimp|grind|linarith|nlinarith) only \[([^\[\]\r\n]*)\]"
                   r"( *(?:at +" + _LOCATION.replace(r"\s+", " +") + r")?) *\Z")
_HINT_ONLY = re.compile(r"(simp_all|simp|dsimp|grind|linarith|nlinarith)\s+only\s*\[([^\[\]]*)\]"
                        r"(?:\s+at\s+(" + _LOCATION + r"))?\s*\Z")


def _only_hint(text):
    """Small explicit-support grammar, not a parser for arbitrary tactic code."""
    match = _HINT_ONLY.fullmatch(text)
    if not match:
        return None
    entries = [s.strip() for s in match[2].split(',')] if match[2].strip() else []
    if len(entries) > 64 or any(not re.fullmatch(_PREMISE, e) for e in entries):
        return None
    return match[1], entries, ' '.join((match[3] or '').split())


def _source_location(site):
    match = re.search(r"\s+at\s+(" + _LOCATION + r")\s*\Z", site['original_line'])
    return ' '.join(match[1].split()) if match else ''


def _bound_site(source, site):
    """Reject stale/forged span metadata before constructing any replacement."""
    start, end = site.get('start'), site.get('end')
    if (site.get('source_sha256') != source_digest(source) or type(start) is not int
            or type(end) is not int or not 0 <= start < end <= len(source)
            or source[start:end] != site.get('original_line')
            or type(site.get('column')) is not int or not 0 <= site['column'] <= 256
            or type(site.get('line')) is not int or type(site.get('tactic')) is not str):
        return False
    line_start = source.rfind('\n', 0, start) + 1
    if start != line_start or type(site.get('indent')) is not str:
        return False
    return (site['indent'] == ' ' * site.get('column', -1)
            and site.get('line') == source.count('\n', 0, start) + 1
            and source[start:].startswith(site['indent'] + site.get('tactic', '') ))


def support_edits(source: str, *, max_sites: int = 4) -> list[SolverEdit]:
    """Try empty support, then each single deletion, with exact source binding.

    Iteration/replay belongs to the caller. This is not minimum-support proof:
    the tactic can still use local hypotheses and built-in reductions. Location
    suffixes (including at *) are preserved; no multiline tactic is guessed.
    """
    from .rewrite_policy import body_of, supported
    if type(max_sites) is not int or not 0 <= max_sites <= 32:
        raise ValueError("invalid support site limit")
    prefix, body = body_of(source)
    if not prefix or len(source.encode()) > 65536 or not supported(body):
        return []
    edits, offset, sites = [], 0, 0
    for line in source.splitlines(keepends=True):
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        text = line[:-len(newline)] if newline else line
        match = _ONLY.fullmatch(text) if offset >= len(prefix) else None
        if match and sites < max_sites:
            entries = [s.strip() for s in match[3].split(",")]
            if (1 <= len(entries) <= 32 and all(re.fullmatch(_PREMISE, e) for e in entries)):
                sites += 1
                subsets = [[], *[entries[:i] + entries[i+1:] for i in range(len(entries))]]
                seen = set()
                for subset in subsets:
                    replacement = match[1] + match[2] + " only [" + ", ".join(subset) + "]" + match[4]
                    replacement += newline
                    if replacement not in seen:
                        seen.add(replacement)
                        edits.append(SolverEdit(source_digest(source), offset, offset + len(line),
                                                replacement, "support-deletion"))
        offset += len(line)
    return edits


def diagnostic_edits(source: str, site: Mapping[str, Any], diagnostics: list) -> list[SolverEdit]:
    """Bounded straight-line suggestions from a checked, exactly anchored probe.

    The caller must validate the probe receipt/context first. Branching scripts,
    nested blocks, strings, metaprograms and commands are intentionally excluded.
    Legacy suggestions() keeps its single-line contract unchanged.
    """
    from .rewrite_policy import supported
    if type(diagnostics) is not list or len(diagnostics) > 256 or not _bound_site(source, site):
        return []
    texts = []
    for row in diagnostics:
        if (type(row) is not dict or row.get("severity") != "information"
                or row.get("fileName") != "ArenaCandidate.lean"
                or row.get("pos") != {"line": site["line"], "column": site["column"]}):
            continue
        message = row.get("message")
        if type(message) is not str or not message.startswith("Try this:"):
            continue
        if len(message.encode()) >= 4096:
            return []  # Never aggregate a clipped/partially observed set of hints.
        text = message[len("Try this:"):].strip()
        if text.startswith("[apply] "):
            text = text[len("[apply] "):]
        if not 1 <= len(text.splitlines()) <= 8 or not supported(text) or "IO." in text:
            return []
        texts.append(text)
    if not texts:
        return []
    # One syntax node may run on many goals under <;>. Suggestions are NOT
    # alternatives: merge every compatible explicit support list, including
    # pretty-printed multiline lists. A union is only a proposal; extra simp
    # rules can change behavior, so complete-source replay is still mandatory.
    hints = [_only_hint(text) for text in texts]
    if all(h is not None for h in hints):
        head, _, location = hints[0]
        if (head != site['tactic'] or location != _source_location(site)
                or any(h[0] != head or h[2] != location for h in hints)):
            return []
        entries = list(dict.fromkeys(e for h in hints for e in h[1]))
        if len(entries) > 64:
            return []
        texts = [head + ' only [' + ', '.join(entries) + ']'
                 + (' at ' + location if location else '')]
    elif len(texts) != 1:
        return []  # Cannot infer branch ownership from message order.
    found = []
    for text in texts:
        lines = text.splitlines()
        # Parser-bound edits are deliberately single-command replacements;
        # multi-command scripts need an explicit branch/goal replay adapter.
        if site.get('span_method') == 'lean-parser/v1' and len(lines) != 1:
            continue
        # Lean's TryThis pretty-printer can indent continuation lines to the
        # source column. Only that alignment (or zero) is accepted here.
        if any(len(l) - len(l.lstrip(" ")) not in (0, site["column"]) for l in lines):
            continue
        lines = [l.strip() for l in lines]
        if any(not REPLAY.match(l) or any(s in l for s in ("?", ";", "=>", "<;>", "|", "·"))
               or re.search(r"\b(?:by|fun|do|let|have|match|run_tac)\b", l) for l in lines):
            continue
        replacement = "\n".join(site["indent"] + l for l in lines)
        replacement += ('\r\n' if site['original_line'].endswith('\r\n') else
                        '\n' if site['original_line'].endswith('\n') else '')
        edit = SolverEdit(source_digest(source), site["start"], site["end"], replacement, "solver-suggestion")
        if edit not in found:
            found.append(edit)
        if len(found) == 4:
            break
    return found


def source_digest(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def compiler_messages(stdout: str, filename: str) -> tuple[list[dict[str, Any]], str]:
    """Parse bounded Lean JSON; never recover diagnostics from truncated tails."""
    if len(stdout) > 1_048_576:
        raise ValueError("compiler diagnostic byte budget")
    rows, plain = [], []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("data"), str):
            raise ValueError("invalid compiler message")
        plain.append(row["data"])
        if row.get("fileName") != filename:
            continue
        if len(rows) >= 256 or len(row["data"]) > 16_384:
            raise ValueError("compiler diagnostic message budget")
        rows.append({k: row.get(k) for k in ("severity", "pos", "endPos", "data")})
    return rows, "\n".join(plain)


def _accepted(receipt):
    return receipt.get("theorem_ok") is True and isinstance(receipt.get("kernel_audit"), Mapping) and receipt["kernel_audit"].get("accepted") is True


def _syntax_query_sites(source, observation):
    """Convert bound native UTF-8 syntax spans to Python character offsets.

    Source comes from the verified request, observations from its typed receipt.
    Unsupported inventories abstain, never fall back to partial line edits.
    """
    encoded = source.encode()
    if (type(observation) is not dict or observation.get('schema') != 'jevops-lean-solver-spans/v1'
            or type(observation.get('source_utf8_bytes')) is not int
            or observation['source_utf8_bytes'] != len(encoded)
            or type(observation.get('spans')) is not list or len(observation['spans']) > 256):
        raise ValueError('invalid solver syntax inventory')
    if observation.get('status') == 'UNSUPPORTED' and not observation['spans']:
        return []
    if observation.get('status') != 'CAPTURED':
        raise ValueError('invalid solver syntax status')
    sites, seen = [], set()
    for row in observation['spans']:
        if type(row) is not dict:
            raise ValueError('invalid solver syntax span')
        a, b = row.get('start_utf8'), row.get('end_utf8')
        if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(encoded)
                or type(row.get('syntax_kind')) is not str or len(row['syntax_kind']) > 256
                or row.get('tactic') not in ('simp', 'simp_all', 'dsimp', 'simpa', 'grind', 'linarith', 'nlinarith')):
            raise ValueError('invalid solver syntax span')
        try:
            a, b = len(encoded[:a].decode()), len(encoded[:b].decode())
        except UnicodeDecodeError as exc:
            raise ValueError('solver span splits UTF-8 character') from exc
        if (a, b) in seen:
            continue
        seen.add((a, b))
        start = source.rfind('\n', 0, a) + 1
        indent = source[start:a]
        tail = source.find('\n', b)
        end = len(source) if tail == -1 else tail + 1
        text = source[a:b]
        # Keep the enclosing combinator and continuation byte-for-byte. Inline
        # tactics, trailing combinators/comments, queries and nested scripts
        # abstain in this slice; parser spans are not a license to edit them.
        if indent != ' ' * len(indent) or source[b:end].strip() or not QUERY.match(text):
            continue
        match = QUERY.match(text)
        if match[2] != row['tactic'] or any(x in text for x in ('?', ';', '=>')):
            continue
        sites.append(dict(line=source.count('\n', 0, start) + 1, column=len(indent),
            start=start, end=end, indent=indent, tactic=row['tactic'], original_line=source[start:end],
            source_sha256=source_digest(source), span_method='lean-parser/v1',
            probe=source[:a+match.end()] + '?' + source[a+match.end():]))
    return sorted(sites, key=lambda s: (s['start'], s['end']))


def query_sites(source: str, syntax_spans=None) -> list[dict[str, Any]]:
    from .rewrite_policy import body_of, supported
    prefix, body = body_of(source)
    if not prefix or len(source.encode()) > 65_536 or not supported(body):
        return []
    if syntax_spans is not None:
        return [s for s in _syntax_query_sites(source, syntax_spans) if s['start'] >= len(prefix)]
    sites, offset = [], 0
    lines = source.splitlines(keepends=True)
    for line_number, line in enumerate(lines, 1):
        match = QUERY.match(line)
        if (offset >= len(prefix) and match and not any(s in line for s in (';', '=>', '?'))):
            # Compatibility path has no native syntax inventory. Only consider
            # closed, standalone physical lines. Never edit an opening line of
            # a multiline command or guess where its continuation ends.
            following = next((s for s in lines[line_number:] if s.strip()), '')
            stack, balanced = [], True
            for char in line:
                if char in '([{':
                    stack.append(char)
                elif char in ')]}':
                    if not stack or stack.pop() != dict(zip(')]}', '([{'))[char]:
                        balanced = False
                        break
            if (not balanced or stack or (following and
                    (len(following) - len(following.lstrip(' ')) > len(match[1])
                     or re.match(r'\s*(?:at|using|only)\b', following)))):
                offset += len(line)
                continue
            query = line[:match.end()] + "?" + line[match.end():]
            sites.append({"line": line_number, "column": len(match[1]), "start": offset,
                          "end": offset+len(line), "indent": match[1], "tactic": match[2],
                          "source_sha256": source_digest(source), "span_method": "single-line-fallback/v1",
                          "original_line": line, "probe": source[:offset] + query + source[offset+len(line):]})
        offset += len(line)
    return sites


def suggestions(receipt: Mapping[str, Any], probe: str, site: Mapping[str, Any]) -> list[str]:
    from .rewrite_policy import supported
    if receipt.get("diagnostics_source_sha256") != source_digest(probe) or not _accepted(receipt):
        return []
    rows = receipt.get("diagnostics")
    if not isinstance(rows, list) or len(rows) > 256:
        return []
    found = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("severity") != "information":
            continue
        pos = row.get("pos")
        if not isinstance(pos, Mapping) or pos.get("line") != site["line"] or pos.get("column") != site["column"]:
            continue
        message = row.get("data")
        if not isinstance(message, str) or not message.startswith("Try this:") or len(message) > 4096:
            continue
        draft = message[len("Try this:"):].strip()
        if draft.startswith("[apply] "):
            draft = draft[len("[apply] "):]
        if ('\n' in draft or '?' in draft or not REPLAY.match(draft) or not supported(draft)):
            continue
        if draft not in found:
            found.append(draft)
        if len(found) == 4:
            break
    return found


def harvest_solver_feedback(source: str, compile_fn: Callable[[str], Mapping[str, Any]], *,
                            max_calls: int = 16, max_sites: int = 4, max_rounds: int = 4,
                            token_fn: Callable[[str], int] | None = None, candidate_gate=None) -> dict[str, Any]:
    from .proof_tokens import proof_source_tokens, TOKENIZER_ID
    from .rewrite_policy import body_of

    if (any(type(n) is not int for n in (max_calls, max_sites, max_rounds)) or
            not 1 <= max_calls <= 64 or not 1 <= max_sites <= 32 or not 1 <= max_rounds <= 8):
        raise ValueError("invalid solver-feedback budget")
    prefix, _ = body_of(source)
    if not prefix:
        raise ValueError("solver feedback requires a theorem envelope")
    measure = token_fn or proof_source_tokens
    cache, attempts, trajectory = {}, [], []
    def compile_one(text):
        key = source_digest(text)
        if key not in cache:
            if len(attempts) == max_calls:
                return {"theorem_ok": False, "reason": "compile_budget"}
            try:
                result = dict(compile_fn(text))
            except Exception as exc:
                result = {"theorem_ok": False, "reason": type(exc).__name__}
            cache[key] = result
            attempts.append({"source_sha256": key, "compile": result})
        return cache[key]

    original = compile_one(source)
    best, cost = source, measure(source)
    reason = "unverified_source" if not _accepted(original) else "no_verified_shorter_suggestion"
    if _accepted(original):
        for round_index in range(max_rounds):
            changed = False
            for site in query_sites(best)[:max_sites]:
                if len(attempts) >= max_calls:
                    break
                receipt = compile_one(site["probe"])
                for text in suggestions(receipt, site["probe"], site):
                    newline = "\n" if site["original_line"].endswith("\n") else ""
                    candidate = best[:site["start"]] + site["indent"] + text + newline + best[site["end"]:]
                    assert body_of(candidate)[0] == prefix
                    new_cost = measure(candidate)
                    if new_cost >= cost:
                        continue
                    replay = compile_one(candidate)
                    if _accepted(replay) and (candidate_gate is None or candidate_gate(best, candidate) is True):
                        trajectory.append({"round": round_index, "before_source": best, "after_source": candidate,
                                           "before_tokens": cost, "after_tokens": new_cost,
                                           "probe_sha256": source_digest(site["probe"]), "line": site["line"],
                                           "tactic": site["tactic"], "suggestion": text, "compile": replay})
                        best, cost, changed, reason = candidate, new_cost, True, "verified_shortening"
                        break
                if changed:
                    break
            if not changed or len(attempts) >= max_calls:
                break
    return {"schema": "jevops-solver-feedback/v1", "ok": _accepted(original), "reason": reason,
            "tokenizer_id": TOKENIZER_ID if token_fn is None else "caller_supplied",
            "best_source": best, "source_tokens": measure(source), "best_tokens": cost,
            "source_compile": original, "trajectory": trajectory, "compile_attempts": attempts,
            "budget_exhausted": len(attempts) >= max_calls, "minimality_proven": False,
            "training_enabled": False, "production_memory_used": False}
