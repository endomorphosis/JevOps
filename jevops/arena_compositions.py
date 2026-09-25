"""Bounded deterministic draft compositions for fresh Arena selection.

These are source/layout heuristics, not a Lean parser or proof authority.
No measurements, model calls, training or incumbent updates occur here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .arena import TOKENIZER_ID, content_hash, intake_error, reference_tokens, source_hash, _units
from .arena_lean import CORPUS
from .arena_rules import PORTABLE_RULES, portable_proposal
from .arena_trial import Candidate, STRATEGIES, proposals

SCHEMA = "jevops-arena-draft-compositions/v1"
PREFIX_DROP_RULES = tuple(f"simp_prefix_drop_{index}" for index in range(4))
RULES = (*STRATEGIES, "intro_exact_assumption", "intro_simp_grind_first", "intro_simp_grind_all",
         "subset_trans_append_left", "subset_trans_append_right",
         "subset_pair_target_left", "subset_pair_target_right",
         "subset_pair_simp_first", "subset_pair_simp_all",
         "subset_pair_simp_split_first", "subset_pair_simp_split_all",
         "subset_triple_simp", "subset_triple_grind", "subset_triple_simp_grind",
         "subset_triple_simp_normalized", "subset_triple_simp_normalized_compact",
         "subset_triple_term", "subset_triple_term_leaves",
         "subset_triple_left_nested", "simp_prefix_no_append_assoc",
         "simp_prefix_goal", "simp_prefix_introduced_goal", *PREFIX_DROP_RULES, *PORTABLE_RULES)


def _goal_simp_prefix(source: str, statement: str):
    """Recognize the shared bounded prefix; no elaborated scope/type claim."""
    from .rewrite_policy import NAME, RESERVED, supported
    from .solver_feedback import _only_hint
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if not supported(body) or '\r' in body:
        return None
    match = re.match(r" *:= by *\n(?P<indent> +)(?:intro|intros) (?P<hyp>" + NAME + r") *\n"
        r"(?P=indent)induction (?P<target>" + NAME + r") *<;> *\n"
        r"(?P<sindent> +)simp only \[(?P<support>[^\[\]\r\n]*)\] *(?:\n|\Z)", body)
    if (not match or len(match['sindent']) <= len(match['indent'])
            or any(match[key] in RESERVED or match[key] == '_' for key in ('hyp', 'target'))):
        return None
    hint = _only_hint('simp only [' + match['support'] + ']')
    if hint is None or len(hint[1]) > 32:
        return None
    return match, hint[1]


def remove_prefix_append_assoc(source: str, statement: str) -> str | None:
    """Nominate deletion from a goal-only induction prefix, not a valid proof.

    The right-nested continuation can depend on this normalization. A composition
    may repair it, but only whole-source Lean checking can admit either draft.
    Never edit another simp site or silently change the location. Preserve the
    earlier named-entry nomination independently of the four-entry profile.
    """
    from .solver_feedback import SolverEdit
    prefix = _goal_simp_prefix(source, statement)
    if prefix is None:
        return None
    match, entries = prefix
    if entries.count('List.append_assoc') != 1:
        return None
    support = ', '.join(entry for entry in entries if entry != 'List.append_assoc')
    edit = SolverEdit(source_hash(source), len(statement) + match.start('support'),
        len(statement) + match.end('support'), support, 'simp-prefix-no-append-assoc')
    candidate = edit.apply(source)
    return None if intake_error(candidate, statement) else candidate


def remove_prefix_support_entry(source: str, statement: str, *, index: int) -> str | None:
    """Drop one indexed entry from a complete one-to-four-entry prefix.

    Each trial path starts from the same exact seed, not a previously successful
    deletion. Longer/duplicate lists abstain rather than silently truncating the
    tested neighborhood. A failed single deletion is not a global minimality
    certificate: combinations, alternative lemmas or case repair may still help.
    """
    from .solver_feedback import SolverEdit
    if type(index) is not int or not 0 <= index < 4:
        raise ValueError("support index must be an integer from zero through three")
    prefix = _goal_simp_prefix(source, statement)
    if prefix is None:
        return None
    match, entries = prefix
    if not 1 <= len(entries) <= 4 or len(set(entries)) != len(entries) or index >= len(entries):
        return None
    support = ', '.join(entries[:index] + entries[index + 1:])
    edit = SolverEdit(source_hash(source), len(statement) + match.start('support'),
        len(statement) + match.end('support'), support, f'simp-prefix-drop-{index}')
    candidate = edit.apply(source)
    return None if intake_error(candidate, statement) else candidate


def narrow_simp_prefix(source: str, statement: str, *, scope: str) -> str | None:
    """Nominate a smaller location for one explicit-support induction prefix.

    This deliberately narrow layout matcher is not a Lean parser or a scope
    proof. Only `intro h; induction x <;> simp only [...] at *` in multiline
    layout is supported. Copy h from that explicit intro; do not guess hidden
    binder names. Removing hypothesis simplification may break the untouched
    continuation, so both variants require fresh whole-source verification.
    """
    from .rewrite_policy import NAME, RESERVED, supported
    from .solver_feedback import SolverEdit, _only_hint
    if type(scope) is not str or scope not in {"goal", "introduced_goal"}:
        raise ValueError("allowlisted simplification scope required")
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if not supported(body) or '\r' in body:
        return None
    match = re.match(r" *:= by *\n(?P<indent> +)(?:intro|intros) (?P<hyp>" + NAME + r") *\n"
        r"(?P=indent)induction (?P<target>" + NAME + r") *<;> *\n"
        r"(?P<sindent> +)(?P<tactic>simp only \[[^\[\]\r\n]*\])"
        r"(?P<location> at \* *)(?:\n|\Z)", body)
    if (not match or len(match['sindent']) <= len(match['indent'])
            or any(match[key] in RESERVED or match[key] == '_' for key in ('hyp', 'target'))):
        return None
    hint = _only_hint(match['tactic'] + ' at *')
    if hint is None or len(hint[1]) > 32:
        return None
    replacement = '' if scope == 'goal' else ' at ' + match['hyp'] + ' ⊢'
    edit = SolverEdit(source_hash(source), len(statement) + match.start('location'),
        len(statement) + match.end('location'), replacement, 'simp-prefix-' + scope)
    candidate = edit.apply(source)
    return None if intake_error(candidate, statement) else candidate


def intro_exact_assumption(source: str, statement: str) -> str | None:
    """Contract one explicit intro/exact leaf to unfolding intros/assumption.

    Only an exact introduced identifier, adjacent lines with equal indentation,
    and the end of a layout branch are supported. Comments/quotes/tabs and term
    proofs abstain. `repeat intro` unfolds hidden binders; bare `intros` does not.
    Keep `assumption` on a separate line, outside the repeated tactic sequence.
    Whole-proof checking is mandatory even when fewer tokens are proposed.
    """
    if not source.startswith(statement):
        return None
    body = source[len(statement):]
    if (len(body) > 32768 or not re.match(r"\s*:=\s*by\b", body)
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return None
    for index in range(len(lines) - 1):
        intro = re.fullmatch(r"( +)(?:intro|intros) ([^\n]+)\n", lines[index])
        exact = re.fullmatch(r"( +)exact ([^\s]+)\s*", lines[index + 1])
        if not intro or not exact or intro[1] != exact[1]:
            continue
        names = intro[2].split()
        if (exact[2] not in names or len(set(names)) != len(names)
                or any(not re.fullmatch(r"[^\W\d][\w']*", n) or n == "_" for n in names)):
            continue
        following = next((line for line in lines[index + 2:] if line.strip()), None)
        if following is not None and len(following) - len(following.lstrip(" ")) >= len(intro[1]):
            continue
        ending = "\n" if lines[index + 1].endswith("\n") else ""
        replacement = intro[1] + "repeat intro\n" + intro[1] + "assumption" + ending
        return statement + "".join([*lines[:index], replacement, *lines[index + 2:]])
    return None


def intro_simp_grind(source: str, statement: str, *, replace_all: bool = False) -> str | None:
    """Nominate `grind` for adjacent terminal `intro; simp_all` leaves.

    This is a bounded layout heuristic, not an equivalence rule or Lean parser.
    In particular, deleting `intro` alone can leave a hidden binder unsolved.
    `grind` is merely another hypothesis to measure: it may fail or cost more.
    First/all variants are frozen before any native outcomes are inspected.
    """
    if type(replace_all) is not bool:
        raise ValueError("explicit boolean replacement policy required")
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if (len(body) > 32768 or not re.match(r"\s*:=\s*by\b", body)
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return None
    matches = []
    for index in range(len(lines) - 1):
        intro = re.fullmatch(r"( +)intro *\n", lines[index])
        simp = re.fullmatch(r"( +)simp_all *(?:\n)?", lines[index + 1])
        if not intro or not simp or intro[1] != simp[1]:
            continue
        following = next((line for line in lines[index + 2:] if line.strip()), None)
        if following is not None and len(following) - len(following.lstrip(" ")) >= len(intro[1]):
            continue
        matches.append((index, intro[1]))
        if not replace_all:
            break
    if not matches:
        return None
    for index, indent in reversed(matches):
        ending = "\n" if lines[index + 1].endswith("\n") else ""
        lines[index:index + 2] = [indent + "grind" + ending]
    result = statement + "".join(lines)
    if intake_error(result, statement) or reference_tokens(result, statement) >= reference_tokens(source, statement):
        return None
    return result


def subset_trans_append(source: str, statement: str, *, side: str) -> str | None:
    """Nominate one constructive append-lifting lemma for a transitivity block.

    Replace `apply List.Subset.trans; apply h; assumption; intro; simp_all`
    (in supported multiline layout) with the chosen append-lifting application
    and the unchanged hypothesis-discharge lines. Direction is a nomination,
    not inferred from variable names or certified by this text matcher.
    Native unification must establish the actual list arguments and all goals.
    """
    if type(side) is not str or side not in {"left", "right"}:
        raise ValueError("allowlisted append side required")
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if (len(body) > 32768 or not re.match(r"\s*:=\s*by\b", body)
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return None
    for index, line in enumerate(lines):
        head = re.fullmatch(r"( +)([.·] )?apply List\.Subset\.trans *\n", line)
        if not head:
            continue
        indent = head[1] + ("  " if head[2] else "")
        start = index + 1
        if start >= len(lines):
            continue
        hyp = re.fullmatch(re.escape(indent) + r"apply ([^\W\d][\w']*)( *; *assumption)? *\n", lines[start])
        if not hyp or hyp[1] == "_":
            continue
        stop = start + 1
        if not hyp[2]:
            if stop >= len(lines) or lines[stop].rstrip(" \n") != indent + "assumption":
                continue
            stop += 1
        if (stop + 1 >= len(lines) or lines[stop].rstrip(" \n") != indent + "intro"
                or lines[stop + 1].rstrip(" \n") != indent + "simp_all"):
            continue
        following = next((l for l in lines[stop + 2:] if l.strip()), None)
        if following is not None and len(following) - len(following.lstrip(" ")) >= len(indent):
            continue
        ending = "\n" if lines[stop + 1].endswith("\n") else ""
        kept = lines[start:stop]
        kept[-1] = kept[-1].rstrip("\n") + ending
        header = head[1] + (head[2] or "") + f"apply List.subset_append_of_subset_{side}\n"
        result = statement + "".join([*lines[:index], header, *kept, *lines[stop + 2:]])
        if not intake_error(result, statement) and reference_tokens(result, statement) < reference_tokens(source, statement):
            return result
    return None


def subset_pair_target(source: str, statement: str, *, side: str) -> str | None:
    """Nominate a shared target lift before splitting a two-leaf source append.

    `List.Subset.app` keeps the entire target in both children. First lift the
    pair into the nominated outer target side; only then use left/right lifts
    on its two children. Exact bounded layout is required, not inferred goals.
    Neither this text matcher nor the supplied direction certifies the proof.
    """
    if type(side) is not str or side not in {"left", "right"}:
        raise ValueError("allowlisted target side required")
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if (len(body) > 32768 or not re.match(r"\s*:=\s*by\b", body)
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return None

    def leaf(start, indent):
        if start >= len(lines) or not re.fullmatch(
                re.escape(indent) + r"[.·] apply List\.Subset\.trans *\n", lines[start]):
            return None
        discharge_indent = indent + "  "
        if start + 1 >= len(lines):
            return None
        hyp = re.fullmatch(re.escape(discharge_indent) + r"apply ([^\W\d][\w']*)( *; *assumption)? *\n",
                           lines[start + 1])
        if not hyp or hyp[1] == "_":
            return None
        stop = start + 2
        if not hyp[2]:
            if stop >= len(lines) or lines[stop].rstrip(" \n") != discharge_indent + "assumption":
                return None
            stop += 1
        if (stop + 1 >= len(lines) or lines[stop].rstrip(" \n") != discharge_indent + "intro"
                or lines[stop + 1].rstrip(" \n") != discharge_indent + "simp_all"):
            return None
        return stop + 2, lines[start + 1:stop]

    for index, line in enumerate(lines):
        head = re.fullmatch(r"( +)([.·] )?apply List\.Subset\.app *\n", line)
        if not head:
            continue
        indent = head[1] + ("  " if head[2] else "")
        first = leaf(index + 1, indent)
        if first is None:
            continue
        second = leaf(first[0], indent)
        if second is None:
            continue
        following = next((l for l in lines[second[0]:] if l.strip()), None)
        if following is not None and len(following) - len(following.lstrip(" ")) >= len(indent):
            continue
        replacement = [head[1] + (head[2] or "") + f"apply List.subset_append_of_subset_{side}\n",
                       indent + "apply List.Subset.app\n"]
        for start, parsed, child_side in ((index + 1, first, "left"), (first[0], second, "right")):
            stop, discharge = parsed
            discharge[-1] = discharge[-1].rstrip("\n") + ("\n" if lines[stop - 1].endswith("\n") else "")
            replacement.extend([lines[start].replace("List.Subset.trans", f"List.subset_append_of_subset_{child_side}"),
                                *discharge])
        result = statement + "".join([*lines[:index], *replacement, *lines[second[0]:]])
        if not intake_error(result, statement) and reference_tokens(result, statement) < reference_tokens(source, statement):
            return result
    return None


def subset_pair_simp(source: str, statement: str, *, replace_all: bool = False,
                     split_disjunction: bool = False) -> str | None:
    """Nominate simplification for exact, already-lifted append proof pairs.

    Unfolding List.Subset exposes its implicit membership binder. Optionally
    nominate or_imp as well; neither simplifier success nor cost is assumed.
    Match two terminal, adjacent left/right leaves, not arbitrary case bodies.
    The all variant uses non-overlapping matches in the original input only.
    """
    if type(replace_all) is not bool or type(split_disjunction) is not bool:
        raise ValueError("explicit boolean simplification policies required")
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if (len(body) > 32768 or not re.match(r"\s*:=\s*by\b", body)
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return None

    def leaf(start, indent, side):
        if start >= len(lines) or not re.fullmatch(re.escape(indent) +
                rf"[.·] apply List\.subset_append_of_subset_{side} *\n", lines[start]):
            return None
        if start + 1 >= len(lines):
            return None
        discharge_indent = indent + "  "
        hyp = re.fullmatch(re.escape(discharge_indent) + r"apply ([^\W\d][\w']*)( *; *assumption)? *(?:\n)?",
                           lines[start + 1])
        if not hyp or hyp[1] == "_":
            return None
        stop = start + 2
        if not hyp[2]:
            if stop >= len(lines) or lines[stop].rstrip(" \n") != discharge_indent + "assumption":
                return None
            stop += 1
        return stop

    edits, index = [], 0
    while index < len(lines):
        head = re.fullmatch(r"( +)([.·] )?apply List\.Subset\.app *\n", lines[index])
        if head:
            indent = head[1] + ("  " if head[2] else "")
            first = leaf(index + 1, indent, "left")
            stop = leaf(first, indent, "right") if first is not None else None
            if stop is not None:
                following = next((l for l in lines[stop:] if l.strip()), None)
                if following is None or len(following) - len(following.lstrip(" ")) < len(indent):
                    lemmas = "List.Subset, or_imp" if split_disjunction else "List.Subset"
                    ending = "\n" if lines[stop - 1].endswith("\n") else ""
                    replacement = head[1] + (head[2] or "") + f"simp_all [{lemmas}]" + ending
                    edits.append((index, stop, replacement))
                    if not replace_all:
                        break
                    index = stop
                    continue
        index += 1
    if not edits:
        return None
    for start, stop, replacement in reversed(edits):
        lines[start:stop] = [replacement]
    result = statement + "".join(lines)
    if intake_error(result, statement) or reference_tokens(result, statement) >= reference_tokens(source, statement):
        return None
    return result


def subset_triple_reconstruct(source: str, statement: str, *, strategy: str) -> str | None:
    """Resynthesize one exact three-leaf append tree, not arbitrary case code.

    Recognize the already-lifted right-nested proof layout used by the pair
    composition. Keep preceding case/hypothesis setup and later branches intact.
    The alternatives expose subset/membership logic to existing Lean tactics;
    syntax recognition establishes neither solvability nor lower cost. The
    existing whole-source checker must validate every nominated replacement.
    Direct terms retain the captured leaf hypotheses and ask Lean to resolve
    their normalization premises with `‹_›`. They may grow by at most sixteen
    tokens for aggregate-cost experiments. The left-nested tactic tree retains
    the same leaf discharges and allows no token growth; its intended companion
    is removing append normalization. This matcher cannot infer list grouping.
    The older simplifier strategies still require a strict token reduction.
    """
    scripts = {
        "simp": ("simp_all only [List.Subset, List.mem_append, or_imp, forall_and]",),
        "grind": ("grind only [List.Subset, List.mem_append]",),
        "simp_grind": ("simp_all only [List.Subset, List.mem_append]", "grind only []"),
        # Explicit propositional normalization for the exposed membership
        # obligations. No implication that these proposals close the goal,
        # preserve its axiom set, or beat the incumbent's measured costs.
        "simp_normalized": ("simp_all only [List.Subset, List.mem_append, or_imp, forall_and, "
                            "true_implies, true_or, or_true, implies_true, and_self]",),
        "simp_normalized_compact": ("simp_all only [List.Subset, List.mem_append, or_imp, "
                                    "true_implies, true_or, or_true, implies_true, and_self]",),
    }
    term_strategies = {"term", "term_leaves"}
    if type(strategy) is not str or strategy not in scripts.keys() | term_strategies | {"left_nested"}:
        raise ValueError("allowlisted subtree reconstruction required")
    if intake_error(source, statement):
        return None
    body = source[len(statement):]
    if (len(body) > 32768 or not re.match(r"\s*:=\s*by\b", body)
            or any(s in body for s in ('/-', '-/', '--', '"', '`', '«', '»', '\t', '\r'))):
        return None
    lines = body.splitlines(keepends=True)
    if len(lines) > 256:
        return None

    def leaf(start, indent, side):
        if start + 1 >= len(lines) or not re.fullmatch(re.escape(indent) +
                rf"[.·] apply List\.subset_append_of_subset_{side} *\n", lines[start]):
            return None
        child = indent + "  "
        hyp = re.fullmatch(re.escape(child) + r"apply ([^\W\d][\w']*)( *; *assumption)? *(?:\n)?",
                           lines[start + 1])
        if not hyp or hyp[1] == "_":
            return None
        stop = start + 2
        if not hyp[2]:
            if stop >= len(lines) or lines[stop].rstrip(" \n") != child + "assumption":
                return None
            stop += 1
        return stop, hyp[1], bool(hyp[2])

    for index, line in enumerate(lines):
        head = re.fullmatch(r"( +)([.·] )?apply List\.Subset\.app *\n", line)
        if not head:
            continue
        indent = head[1] + ("  " if head[2] else "")
        first = leaf(index + 1, indent, "left")
        if (first is None or first[0] + 1 >= len(lines)
                or lines[first[0]].rstrip(" \n") != indent + "apply List.subset_append_of_subset_right"
                or lines[first[0] + 1].rstrip(" \n") != indent + "apply List.Subset.app"):
            continue
        second = leaf(first[0] + 2, indent, "left")
        third = leaf(second[0], indent, "right") if second is not None else None
        if third is None:
            continue
        stop = third[0]
        following = next((l for l in lines[stop:] if l.strip()), None)
        if following is not None and len(following) - len(following.lstrip(" ")) >= len(indent):
            continue
        if strategy == "left_nested":
            def discharge(entry, padding):
                # Preserve separate-line discharges too; adding semicolons
                # would increase source tokens and change the leaf layout.
                return ((padding + f"apply {entry[1]} ; assumption",) if entry[2] else
                        (padding + f"apply {entry[1]}", padding + "assumption"))
            script = ("apply List.Subset.app",
                      ". apply List.subset_append_of_subset_left",
                      "  apply List.Subset.app",
                      "  . apply List.subset_append_of_subset_left",
                      *discharge(first, "    "),
                      "  . apply List.subset_append_of_subset_right",
                      *discharge(second, "    "),
                      "apply List.subset_append_of_subset_right",
                      *discharge(third, ""))
        elif strategy in term_strategies:
            a, b, c = (entry[1] for entry in (first, second, third))
            left, right = "List.subset_append_of_subset_left", "List.subset_append_of_subset_right"
            if strategy == "term":
                script = ("exact List.Subset.app",
                          f"  ({left} _ ({a} ‹_›))",
                          f"  ({right} _ (List.Subset.app",
                          f"    ({left} _ ({b} ‹_›))",
                          f"    ({right} _ ({c} ‹_›))))")
            else:
                script = ("apply List.Subset.app",
                          f". exact {left} _ ({a} ‹_›)",
                          f"apply {right}", "apply List.Subset.app",
                          f". exact {left} _ ({b} ‹_›)",
                          f". exact {right} _ ({c} ‹_›)")
        else:
            script = scripts[strategy]
        replacement = head[1] + (head[2] or "") + script[0]
        replacement += "".join("\n" + indent + tactic for tactic in script[1:])
        replacement += "\n" if lines[stop - 1].endswith("\n") else ""
        result = statement + "".join([*lines[:index], replacement, *lines[stop:]])
        growth = reference_tokens(result, statement) - reference_tokens(source, statement)
        limit = 16 if strategy in term_strategies else (0 if strategy == "left_nested" else -1)
        if not intake_error(result, statement) and growth <= limit:
            return result
    return None


def draft_batch(record: Mapping, paths: Sequence[Sequence[str]], *, cap: int = 8,
                seed: Candidate | None = None) -> dict:
    if not 0 <= _units(cap, "cap") <= 8:
        raise ValueError("draft cap must be zero to eight")
    if (not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= 8
            or any(not isinstance(path, (list, tuple)) or not 1 <= len(path) <= 3
                   or any(type(rule) is not str or rule not in RULES for rule in path) for path in paths)):
        raise ValueError("one to eight allowlisted paths of one to three rules required")
    source, statement = record["src"], record["statement"]
    Candidate("original", source, "unverified original input")
    if intake_error(source, statement):
        raise ValueError("reference violates fixed intake policy")
    if seed is not None and (not isinstance(seed, Candidate) or intake_error(seed.source, statement)):
        raise ValueError("seed must be a typed draft with the exact statement and valid intake")
    base = seed.source if seed is not None else source
    drafts, attempts, seen = [], [], {source_hash(source), source_hash(base)}
    for path in paths:
        if len(drafts) >= cap:
            break
        current, steps = base, []
        for rule in path:
            if rule == "intro_exact_assumption":
                candidate = intro_exact_assumption(current, statement)
            elif rule in {"intro_simp_grind_first", "intro_simp_grind_all"}:
                candidate = intro_simp_grind(current, statement, replace_all=rule.endswith("_all"))
            elif rule in {"subset_trans_append_left", "subset_trans_append_right"}:
                candidate = subset_trans_append(current, statement, side=rule.rsplit("_", 1)[1])
            elif rule in {"subset_pair_target_left", "subset_pair_target_right"}:
                candidate = subset_pair_target(current, statement, side=rule.rsplit("_", 1)[1])
            elif rule in {"subset_pair_simp_first", "subset_pair_simp_all",
                          "subset_pair_simp_split_first", "subset_pair_simp_split_all"}:
                candidate = subset_pair_simp(current, statement, replace_all=rule.endswith("_all"),
                                             split_disjunction="_split_" in rule)
            elif rule in {"subset_triple_simp", "subset_triple_grind", "subset_triple_simp_grind",
                          "subset_triple_simp_normalized", "subset_triple_simp_normalized_compact",
                          "subset_triple_term", "subset_triple_term_leaves", "subset_triple_left_nested"}:
                candidate = subset_triple_reconstruct(current, statement, strategy=rule.removeprefix("subset_triple_"))
            elif rule == "simp_prefix_no_append_assoc":
                candidate = remove_prefix_append_assoc(current, statement)
            elif rule in PREFIX_DROP_RULES:
                candidate = remove_prefix_support_entry(current, statement, index=PREFIX_DROP_RULES.index(rule))
            elif rule in {"simp_prefix_goal", "simp_prefix_introduced_goal"}:
                candidate = narrow_simp_prefix(current, statement, scope=rule.removeprefix("simp_prefix_"))
            elif rule in PORTABLE_RULES:
                candidate = portable_proposal(current, statement, rule)
            else:
                values = proposals({**record, "src": current}, [rule], cap=1)
                candidate = values[0].source if values else None
            if candidate is None or candidate == current or intake_error(candidate, statement):
                current = None
                break
            steps.append({"rule": rule, "before_sha256": source_hash(current),
                          "after_sha256": source_hash(candidate),
                          "before_tokens": reference_tokens(current, statement),
                          "after_tokens": reference_tokens(candidate, statement)})
            current = candidate
        attempt = {"path": list(path), "steps": steps, "status": "ABSTAINED"}
        if current is not None:
            identity = source_hash(current)
            attempt.update(status="DUPLICATE" if identity in seen else "DRAFT", source_sha256=identity)
            if identity not in seen:
                seen.add(identity)
                draft = Candidate(f"composition-{len(drafts)}", current,
                                  "unverified deterministic composition: " + " -> ".join(path))
                drafts.append({"name": record["name"], **asdict(draft)})
                attempt.update(label=draft.label, tokens=reference_tokens(current, statement))
        attempts.append(attempt)
    return {"schema": SCHEMA, "tokenizer_id": TOKENIZER_ID, "record_sha256": content_hash(dict(record)),
            "reference_source_sha256": source_hash(source), "reference_tokens": reference_tokens(source, statement),
            "seed": asdict(seed) if seed is not None else None,
            "base_source_sha256": source_hash(base), "base_tokens": reference_tokens(base, statement),
            "paths": [list(path) for path in paths], "cap": cap, "attempts": attempts, "drafts": drafts,
            "generator_sha256": source_hash(Path(__file__).read_text()),
            "rule_sources_sha256": {name: source_hash(Path(__file__).with_name(name).read_text())
                                    for name in ("arena_rules.py", "folds.py", "solver_feedback.py", "rewrite_policy.py")},
            "proof_verified": False, "native_processes": 0, "training_enabled": False,
            "promoted": False, "official_score": None}


def _read_json(path: Path) -> object:
    with path.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("proposal input byte limit")
    return json.loads(raw)


def proposal_paths(record: Mapping, proposal: object, *, seed: Candidate | None = None) -> list:
    """Treat model/hammer nominations only as source-bound, finite rule paths.

    No candidate code execution, claimed rewards, verifier flags or authority
    fields are accepted. draft_batch validates the path vocabulary and budgets.
    """
    if (not isinstance(proposal, dict)
            or set(proposal) != {"record_sha256", "base_source_sha256", "paths"}
            or proposal["record_sha256"] != content_hash(dict(record))
            or proposal["base_source_sha256"] != source_hash(seed.source if seed else record["src"])):
        raise ValueError("proposal requires exact record/base hashes and paths only")
    return proposal["paths"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--problem", required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--path", action="append", help="comma-separated allowlisted rules, depth <=3")
    inputs.add_argument("--proposal-file", type=Path, help="untrusted, record/base-hash-bound rule nominations")
    parser.add_argument("--seed", type=Path, help="unverified four-field candidate JSON; never a receipt")
    parser.add_argument("--cap", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.corpus.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("corpus byte limit")
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        matches = [record for record in records if record["name"] == args.problem]
        if len(matches) != 1:
            raise ValueError("exactly one matching problem required")
        record, seed = matches[0], None
        if args.seed:
            data = _read_json(args.seed)
            if (not isinstance(data, dict) or set(data) != {"name", "label", "source", "provenance"}
                    or data["name"] != record["name"]):
                raise ValueError("seed requires matching name, label, source, provenance only")
            seed = Candidate(data["label"], data["source"], data["provenance"])
        paths = (proposal_paths(record, _read_json(args.proposal_file), seed=seed) if args.proposal_file
                 else [path.split(",") for path in args.path])
        batch = draft_batch(record, paths, cap=args.cap, seed=seed)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for draft in batch["drafts"]:
            (args.output_dir / (draft["label"] + ".json")).write_text(json.dumps(draft, indent=2) + "\n")
        (args.output_dir / "manifest.json").write_text(json.dumps(batch, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": "DRAFTS_ONLY", "count": len(batch["drafts"]), "native_processes": 0,
                      "output_dir": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
