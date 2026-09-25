#!/usr/bin/env python3
"""Jev beam ranking: family×leaf paths, Noul fire, composite milles-style scores.

Does not write Lean. Lake (or another oracle) still admits.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

EPSILON = 1e-9
BEAM_K = 3
FIRE_T = 0.7
FIRE_T_RESIDUAL = 0.5
FIRE_T_LEAF = 0.45
CONFIDENT = 0.55
UNCERTAIN = 0.60


def hole_rows(
    holes: Sequence[Any],
    *,
    token_fn: Any,
    used_fn: Optional[Any] = None,
    safe_fn: Optional[Any] = None,
    head: int = 80,
) -> list[dict[str, Any]]:
    """Project hole objects into compact rows. token/used/safe fns injected."""

    rows: list[dict[str, Any]] = []
    for hole in holes or ():
        original = getattr(hole, "original", "")
        start = getattr(hole, "start", 0)
        end = getattr(hole, "end", 0)
        row: dict[str, Any] = {
            "id": getattr(hole, "hole_id", None),
            "family": getattr(hole, "family", None),
            "n_tokens": int(token_fn(original)),
            "head": str(original).strip()[: int(head)],
        }
        if used_fn is not None:
            row["used_binders"] = used_fn(start, end, original)
        if safe_fn is not None:
            row["safe_to_drop"] = bool(safe_fn(start, end, original))
        rows.append(row)
    return rows


def drive_analyze_proof(
    record: Mapping[str, Any],
    *,
    tactics: Optional[str],
    model: Optional[Mapping[str, Any]],
    tactic_fn: Callable[[Mapping[str, Any]], str],
    count_fn: Callable[[str], Mapping[str, Any]],
    family_fn: Callable[..., Sequence[Mapping[str, Any]]],
    holes_fn: Callable[[str], Sequence[Any]],
    spans: Sequence[Any],
    windows_fn: Callable[[str, Any], Sequence[Any]],
    phrases: Mapping[str, Sequence[str]],
    cases_fn: Callable[[str], Sequence[Any]],
    token_fn: Callable[[str], int],
    used_fn: Callable[..., bool],
    safe_fn: Callable[..., bool],
    tags_fn: Callable[[Mapping[str, Any]], Sequence[Any]],
) -> dict[str, Any]:
    """Count tactics, holes, and spans. Does not compile and does not call a model."""

    from jevops.outer import any_get, attrs_of, call_if, head_seq, if_none, stripped_or, substrings_in
    from jevops.search import eligible_span_counts

    body = stripped_or(if_none(tactics, factory=lambda: tactic_fn(record)), "")
    counts = count_fn(body)
    families = call_if(model, lambda: family_fn(counts, model), default=[])
    mca_holes = holes_fn(body)
    span_counts = eligible_span_counts(body, spans, windows_fn)
    present = substrings_in(body, phrases)
    cases = attrs_of(cases_fn(body), "label")
    holes = hole_rows(
        mca_holes,
        token_fn=token_fn,
        used_fn=lambda start, end, original: used_fn(body, start, end, original),
        safe_fn=lambda start, end, original: safe_fn(body, start, end, original),
    )
    return analysis_row(
        record,
        n_tokens=token_fn(body),
        counts=counts,
        families=families,
        holes=holes,
        extra={
            "n_tags": len(list(tags_fn(record))),
            "eligible_spans": span_counts,
            "catalog_phrases_present": present,
            "case_labels": head_seq(cases, 12),
            "n_cases": len(cases),
            "pca_keep": any_get(counts, "n_induction", "n_cases"),
        },
    )


def analysis_row(
    record: Mapping[str, Any],
    *,
    n_tokens: int,
    counts: Mapping[str, Any],
    families: Sequence[Any] = (),
    holes: Sequence[Mapping[str, Any]] = (),
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Compact proof analysis for Jev/rankers. No Lean."""

    out: dict[str, Any] = {
        "name": record.get("name"),
        "source": record.get("source"),
        "n_tokens": int(n_tokens),
        "n_lines": int((counts or {}).get("n_lines") or 0),
        "counts": {str(k): int(v) for k, v in dict(counts or {}).items()},
        "families": list(families or []),
        "mca_holes": list(holes or []),
        "n_mca_holes": len(holes or []),
    }
    if extra:
        out.update(dict(extra))
    return out


def count_prefix_lines(
    text: str,
    matchers: Mapping[str, Any],
    *,
    extra: Optional[Mapping[str, float]] = None,
) -> dict[str, float]:
    """Count lines. matchers[name] is a callable(stripped)->bool or prefix tuple."""

    counts = {str(name): 0.0 for name in matchers}
    for line in str(text or "").splitlines():
        stripped = line.strip()
        for name, rule in matchers.items():
            if callable(rule):
                hit = bool(rule(stripped))
            else:
                hit = any(stripped == p or stripped.startswith(p) for p in rule)
            if hit:
                counts[str(name)] += 1.0
    if extra:
        counts.update({str(k): float(v) for k, v in extra.items()})
    return counts


def line_stats(text: str) -> dict[str, float]:
    lines = str(text or "").splitlines()
    return {
        "n_lines": float(len(lines)),
        "n_blank": float(sum(1 for line in lines if not line.strip())),
        "max_indent": float(max((len(line) - len(line.lstrip()) for line in lines), default=0)),
    }


def drive_shot_example(
    record: Mapping[str, Any],
    *,
    tactic_fn: Callable[[Mapping[str, Any]], str],
    holes_fn: Callable[[str], Sequence[Any]],
    fill_one_fn: Callable[[Any], str],
    apply_fn: Callable[..., str],
    skeleton_fn: Callable[..., str],
    token_fn: Callable[[str], int],
    hole_id: str = "hole_id",
    family_attr: str = "family",
) -> dict[str, Any]:
    """Template-fill holes for one few-shot row. Does not call a model."""

    from jevops.outer import get_str

    tactics = tactic_fn(record)
    holes = list(holes_fn(tactics))
    fills = {getattr(hole, hole_id): fill_one_fn(hole) for hole in holes}
    filled = apply_fn(tactics, holes, fills)
    return shot_stats(
        get_str(record, "name"),
        tactics,
        filled,
        token_fn=token_fn,
        extra={
            "n_holes": len(holes),
            "families": [getattr(hole, family_attr) for hole in holes],
            "skeleton": skeleton_fn(tactics, holes),
            "reference": tactics,
            "filled": filled,
        },
    )


def shot_stats(
    name: Any,
    before: str,
    after: str,
    *,
    token_fn: Any,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops.search import token_ratio

    ref = int(token_fn(before))
    filled = int(token_fn(after))
    out = {
        "name": name,
        "ref_tokens": ref,
        "filled_tokens": filled,
        "ratio": token_ratio(filled, ref),
    }
    if extra:
        out.update(dict(extra))
    return out


def keep_if_contains(
    seen: set[str],
    out: list[tuple[str, str]],
    name: str,
    body: Optional[str],
    required: Sequence[str] = (),
) -> None:
    """Append (name, body) if new, non-empty, and required lines are still present."""

    if not body:
        return
    text = str(body).strip("\n")
    if not text or text in seen:
        return
    present = {line.strip() for line in text.splitlines()}
    if any(str(req).strip() not in present for req in required):
        return
    seen.add(text)
    out.append((str(name), text))


def keep_token(
    name: str,
    *,
    stopwords: Sequence[str] = (),
    min_len: int = 2,
) -> bool:
    text = str(name or "")
    if not text or text == "_" or set(text) <= {"_"}:
        return False
    if len(text) < int(min_len):
        return False
    banned = {str(w).lower() for w in stopwords}
    head = text.split(".", 1)[0]
    if head.lower() in banned or text.lower() in banned:
        return False
    return True


def unique_first(
    items: Sequence[Any],
    *,
    key_fn: Any,
    keep_fn: Optional[Any] = None,
    cap: Optional[int] = None,
) -> tuple[list[Any], int]:
    """First-occurrence unique by key_fn. Returns (capped, uncapped_count)."""

    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        key = key_fn(item)
        if keep_fn is not None and not keep_fn(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    uncapped = len(out)
    if cap is not None:
        out = out[: max(0, int(cap))]
    return out, uncapped


def unique_transforms(
    text: str,
    items: Sequence[Any],
    *,
    apply_fn: Any,
) -> list[tuple[Any, str]]:
    """Apply each item to text; keep first new non-empty results."""

    current = str(text or "").strip("\n")
    seen = {current}
    out: list[tuple[Any, str]] = []
    for item in items:
        nxt = str(apply_fn(item, current) or "").strip("\n")
        if nxt and nxt not in seen:
            seen.add(nxt)
            out.append((item, nxt))
    return out


def keep_shorter(old: str, new: str, *, token_fn: Any) -> str:
    """Return new only if token_fn says it is strictly shorter."""

    nxt = str(new or "")
    prev = str(old or "")
    if not nxt or nxt == prev:
        return prev
    if int(token_fn(nxt)) >= int(token_fn(prev)):
        return prev
    return nxt


def rank_by_prob(
    probabilities: Mapping[str, Any],
    *,
    k: int = 8,
) -> list[tuple[str, float]]:
    """(id, p) sorted desc, cap k."""

    ranked = sorted(
        ((str(key), float(value)) for key, value in dict(probabilities or {}).items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[: max(0, int(k))]


def attach_ranked(
    ranked: Sequence[tuple[str, float]],
    by_id: Mapping[str, Any],
    fields: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Join ranked (id, p) with objects. field values are attr names or callables."""

    rows: list[dict[str, Any]] = []
    for ident, probability in ranked or ():
        item = by_id.get(ident)
        row: dict[str, Any] = {"id": ident, "probability": probability}
        for dest, src in dict(fields).items():
            if item is None:
                row[str(dest)] = None
            elif callable(src):
                row[str(dest)] = src(item)
            else:
                row[str(dest)] = getattr(item, str(src), None)
        rows.append(row)
    return rows


def drive_rank_choice(
    probabilities: Mapping[str, Any],
    drafts: Sequence[Any],
    *,
    k: int,
    id_fn: Callable[[Any], str],
    fields: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Rank by probability, then join draft fields. Not a lake admit."""

    return attach_ranked(
        rank_by_prob(probabilities, k=k),
        {id_fn(item): item for item in drafts},
        fields,
    )


def present_families(
    analysis: Mapping[str, Any],
    *,
    extra: Sequence[str] = ("dead_code", "search_space", "pca_keep"),
) -> set[str]:
    present = {str(item.get("family")) for item in analysis.get("families") or []}
    present.update(str(x) for x in extra)
    present.discard("")
    return present


def safe_holes(holes: Sequence[Mapping[str, Any]] = ()) -> list[Mapping[str, Any]]:
    return [h for h in holes or () if h.get("safe_to_drop")]


def pick_state(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    drafts: Sequence[Mapping[str, Any]] = (),
    memory: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Compact pick/Jev state: drafts, holes, named memory. No Lean."""

    from jevops.memory import named_success_kinds

    name = str(record.get("name") or "")
    state: dict[str, Any] = {
        "problem": {"name": record.get("name"), "source": record.get("source")},
        "n_tokens": analysis.get("n_tokens"),
        "n_mca_holes": analysis.get("n_mca_holes"),
        "counts": analysis.get("counts"),
        "holes": analysis.get("mca_holes"),
        "families": analysis.get("families"),
        "drafts": draft_heads(drafts),
        "memory": {
            "success_kinds": named_success_kinds(memory or {}, name, limit=12),
            "blacklist": named_keys((memory or {}).get("blacklist") or [], name),
        },
    }
    if extra:
        state.update(dict(extra))
    return state


def draft_heads(drafts: Sequence[Mapping[str, Any]], *, limit: int = 16) -> list[dict[str, Any]]:
    """Compact draft rows for Jev state. No Lean."""

    return [
        {"kind": item.get("kind"), "family": item.get("family"), "tokens": item.get("token_count")}
        for item in list(drafts)[: int(limit)]
    ]


def leaf_choice_questions(
    tree: Mapping[str, Any],
    *,
    ctor: Any,
    skip_single: bool = True,
    focus: str = "Prefer closed folds over random spans.",
) -> dict[str, Any]:
    """One Choice per family with more than one leaf."""

    questions: dict[str, Any] = {}
    for fam, kids in dict(tree or {}).items():
        if skip_single and len(kids or {}) == 1:
            continue
        questions[f"leaf_{fam}"] = ctor(
            instructions={
                "question": f"Inside `{fam}`, which leaf is most likely to lake-compile AND cut tokens?",
                "focus": focus,
            },
            criteria=dict(kids),
        )
    return questions


def sample_records(
    records: Sequence[Mapping[str, Any]],
    *,
    k: int,
    seed: int,
    exclude: Sequence[str] = (),
) -> list[Mapping[str, Any]]:
    import random

    pool = [item for item in records if item.get("name") not in set(exclude)]
    rng = random.Random(int(seed))
    if k >= len(pool):
        picked = list(pool)
        rng.shuffle(picked)
        return picked
    return rng.sample(pool, int(k))


def filter_by_tokens(
    records: Sequence[Mapping[str, Any]],
    landscape: Sequence[Mapping[str, Any]],
    *,
    cap: int,
) -> list[Mapping[str, Any]]:
    return [
        rec
        for rec, row in zip(records, landscape)
        if int(row.get("n_tokens") or 0) <= int(cap)
    ]


def ensure_named(
    sampled: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    *,
    name: str,
    k: int,
) -> list[Mapping[str, Any]]:
    hit = next((item for item in records if item.get("name") == name), None)
    if hit is None:
        return list(sampled)
    if all(item.get("name") != hit.get("name") for item in sampled):
        return [hit, *list(sampled)][: max(1, int(k))]
    return list(sampled)


def shorter_bag(
    body: str,
    *,
    token_fn: Any,
    generator: str = "random_canary",
) -> tuple[Any, list[dict[str, Any]]]:
    """Collect strictly shorter drafts. token_fn is injected. No Lean."""

    text = str(body or "").strip("\n")
    base = int(token_fn(text))
    seen: set[str] = {text}
    rows: list[dict[str, Any]] = []

    def push(kind: str, nxt: str, extra: Optional[Mapping[str, Any]] = None) -> None:
        nxt_s = str(nxt or "").strip("\n")
        if not nxt_s or nxt_s in seen:
            return
        tok = int(token_fn(nxt_s))
        if tok >= base:
            return
        seen.add(nxt_s)
        item: dict[str, Any] = {
            "kind": kind,
            "tactics": nxt_s,
            "token_count": tok,
            "generator": generator,
            "llm": "off",
        }
        if extra:
            item.update(dict(extra))
        rows.append(item)

    return push, rows


def pin_prefix(
    rows: Sequence[Mapping[str, Any]],
    *,
    prefix: str = "port_",
    n: int,
    shuffle_fn: Optional[Any] = None,
) -> list[Mapping[str, Any]]:
    portable = [row for row in rows if str(row.get("kind") or "").startswith(prefix)]
    others = [row for row in rows if row not in portable]
    if shuffle_fn is not None:
        shuffle_fn(others)
    pinned = list(portable) + list(others)
    return pinned[: max(int(n), len(portable))]


def draft_tree(
    drafts: Sequence[Mapping[str, Any]],
    *,
    blurbs: Optional[Mapping[str, str]] = None,
    default_family: str = "search_space",
    empty_tree: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict[str, dict[str, str]]:
    names = dict(blurbs or {})
    tree: dict[str, dict[str, str]] = {}
    for item in drafts:
        fam = str(item.get("family") or default_family)
        kind = str(item.get("kind") or "")
        if not kind:
            continue
        blurb = names.get(fam, fam)
        tree.setdefault(fam, {})[kind] = f"{kind}; {item.get('token_count')} tok; {blurb}"
    if not tree:
        return dict(empty_tree or {"keep": {"keep": "No shorter draft"}})
    return tree


def drive_blurb_tree(
    drafts: Sequence[Mapping[str, Any]],
    structured: Mapping[str, Any],
    blurbs: Mapping[str, Any],
    *,
    empty_tree: Mapping[str, Mapping[str, str]],
    attr: str = "what",
) -> dict[str, dict[str, str]]:
    """Overlay structured blurbs, then build the draft tree. Does not write Lean."""

    from jevops.outer import overlay_attr

    return draft_tree(
        drafts,
        blurbs=overlay_attr(blurbs, structured, attr=attr),
        empty_tree=empty_tree,
    )


def leftover_sort_key(
    *,
    n_drafts: int,
    remaining_cut: int,
    rf_score: float,
    name: str,
) -> tuple[int, int, float, str]:
    """Leftover un-blacklisted drafts first, then remaining-cut, then ranker score."""

    return (-int(n_drafts), -int(remaining_cut), -float(rf_score), str(name))


def sort_keyed(rows: Sequence[tuple[Any, ...]]) -> list[Any]:
    """Sort tuples and return the last element of each (the record)."""

    scored = list(rows)
    scored.sort()
    return [row[-1] for row in scored]


def filter_catalog(
    skills: Mapping[str, Any],
    tree: Mapping[str, Any],
    *,
    allow_skills: Optional[set[str]] = None,
    allow_families: Optional[set[str]] = None,
    is_blocked: Optional[Any] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restrict skill/tree catalogs. Keep is never dropped unless empty."""

    out_skills = dict(skills or {})
    out_tree = dict(tree or {})
    if allow_skills:
        out_skills = {
            key: val
            for key, val in out_skills.items()
            if key == "keep" or key in allow_skills or str(key).replace("port_", "") in allow_skills
        }
    if allow_families:
        out_tree = {fam: kids for fam, kids in out_tree.items() if fam in allow_families}
        allowed_kinds = {kid for kids in out_tree.values() for kid in kids}
        out_skills = {key: val for key, val in out_skills.items() if key == "keep" or key in allowed_kinds}
    if is_blocked is not None:
        out_skills = {
            key: val
            for key, val in out_skills.items()
            if key == "keep" or not is_blocked(key)
        }
    if not out_skills:
        out_skills = {"keep": "No remaining un-blacklisted skill"}
    return out_skills, out_tree


def annotate_leftover(
    memory: dict[str, Any],
    *,
    name: str,
    n_drafts: int,
    remaining_cut: int,
    warmup: Optional[int] = None,
    tokens: Optional[int] = None,
) -> None:
    """Write leftover-draft / remaining-cut onto a theorem cell. No Lean."""

    from jevops.nca import upsert_from_event

    cid = f"ptr://theorem/{name}"
    upsert_from_event(memory, ptr=cid, kind="theorem", energy=0.55)
    grid = ((memory.get("nca") or {}).get("grid") or {})
    if not isinstance(grid.get(cid), dict):
        return
    grid[cid]["leftover_drafts"] = int(n_drafts)
    grid[cid]["remaining_cut"] = int(remaining_cut)
    if warmup is not None:
        grid[cid]["warmup_tokens"] = int(warmup)
    if tokens is not None:
        grid[cid]["tokens"] = int(tokens)


def leaf_qs_from_choices(
    tree: Mapping[str, Mapping[str, Any]],
    choices: Mapping[str, Any],
    *,
    family_conf: float = 0.0,
) -> dict[str, dict[str, Any]]:
    """Project Jev Choice answers onto per-family leaf probability maps. No Lean."""

    leaf_qs: dict[str, dict[str, Any]] = {}
    for fam, kids in tree.items():
        if len(kids) == 1:
            only = next(iter(kids))
            leaf_qs[fam] = {
                "choice": only,
                "confidence": 1.0,
                "probabilities": {only: 1.0},
                "family_confidence": float(family_conf),
            }
            continue
        ans = choices.get(f"leaf_{fam}")
        probs = dict(getattr(ans, "probabilities", None) or {})
        leaf_qs[fam] = {
            "choice": getattr(ans, "choice", None),
            "confidence": float(getattr(ans, "confidence", None) or 0.0),
            "probabilities": {k: float(probs.get(k) or 0.0) for k in kids},
            "family_confidence": float(family_conf),
        }
    return leaf_qs


def pack_beam(
    *,
    tree: Mapping[str, Any],
    fam_probs: Mapping[str, float],
    family_conf: float,
    paths: Sequence[Mapping[str, Any]],
    beam_kinds: Sequence[str],
    abstain: bool,
    noul_fail: float,
    noul_pca: float,
    per_leaf_fail: Mapping[str, float],
    fired_leaves: set[str],
    fired: bool,
    cut_score: Any,
    usage: Optional[Mapping[str, Any]] = None,
    wall_ms: float = 0.0,
    greedy_fam: Any = None,
    greedy_leaf: Any = None,
    leaf_qs: Optional[Mapping[str, Any]] = None,
    epsilon: float = EPSILON,
) -> dict[str, Any]:
    """Closed pick payload. Jev did not write Lean."""

    from jevops.outer import head_seq

    top = paths[0]["path_score"] if paths else 0.0
    second = paths[1]["path_score"] if len(paths) > 1 else epsilon
    return {
        "skipped": False,
        "best_family": greedy_fam,
        "family_confidence": family_conf,
        "family_probabilities": {k: float(fam_probs.get(k) or 0.0) for k in tree},
        "best_draft": greedy_leaf,
        "draft_confidence": paths[0]["leaf_confidence"] if paths else None,
        "draft_probabilities": ((leaf_qs or {}).get(str(greedy_fam)) or {}).get("probabilities") or {},
        "likely_token_cut": cut_score,
        "beam_kinds": head_seq(beam_kinds, 8),
        "path_score": top,
        "separation": top / max(second, epsilon),
        "abstain": abstain,
        "noul_fail": noul_fail,
        "noul_pca": noul_pca,
        "per_leaf_fail": dict(per_leaf_fail),
        "fired_leaves": sorted(fired_leaves),
        "fired": fired,
        "usage": dict(usage or {}),
        "wall_ms": wall_ms,
        "jev_generated_lean": False,
        "arena_score": None,
        "composite": (paths[0].get("composite") if paths else None),
    }


def drive_typesafe_pick(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    *,
    ledger: Optional[Any],
    memory: Optional[Mapping[str, Any]],
    setup: Sequence[Callable[[], Any]],
    spec: Mapping[str, Any],
    structured: Mapping[str, Any],
    blurbs: Mapping[str, str],
    fail_criteria: Mapping[str, str],
    leaf_focus: str,
    goal: str,
    failed_stems_fn: Callable[..., Sequence[str]],
    model_id: str,
    beam_k: int,
    fire_t: float,
    fire_t_leaf: float,
    confident: float,
    uncertain: float,
    epsilon: float,
    client_timeout: float = 45.0,
) -> dict[str, Any]:
    """Score drafts and pick a family/leaf. Jev does not write Lean."""

    from jevops.jev import (
        choice_head,
        expand_questions,
        instantiate_questions,
        invoke_system_one,
        invoke_then_project,
        noul_attr,
        record_usage,
        typesafe_session,
        unpack_response,
    )
    from jevops.outer import get_str, head_seq, if_none

    loaded, skip = typesafe_session(setup=tuple(setup), fallback=False)
    if skip is not None:
        return skip
    choice, noul, score, client = loaded["Choice"], loaded["Noul"], loaded["Score"], loaded["TypeSafeClient"]
    tree = draft_tree(drafts)
    criteria = family_criteria(tree, structured=structured, blurbs=blurbs)
    questions = instantiate_questions(
        spec,
        choice=choice,
        noul=noul,
        score=score,
        criteria_overlay={"family": criteria},
    )
    questions.update(
        expand_questions(
            [item for item in drafts if item.get("kind")],
            ctor=noul,
            name_fn=lambda item: f"fail_{item.get('kind')}",
            instructions_fn=lambda item: {
                "question": f"Will draft `{item.get('kind')}` fail lake compile?",
                "inspect": f"`drafts` entry `{item.get('kind')}`",
                "focus": "true = P(wrong) for this field (SDE per-field battery).",
            },
            criteria=fail_criteria,
            limit=6,
        )
    )
    questions.update(leaf_choice_questions(tree, ctor=choice, focus=leaf_focus))
    state = pick_state(record, analysis, drafts=drafts, memory=memory, extra={"goal": goal})

    def _project(_result: Any, wall_ms: float, choices: Any, nouls: Any, scores: Any, usage: Any) -> dict[str, Any]:
        _fam_ans, fam_probs, family_conf, fam_choice = choice_head(choices, "family")
        leaf_qs = leaf_qs_from_choices(tree, choices, family_conf=family_conf)
        cut = scores.get("likely_token_cut")
        return rank_from_answers(
            tree=tree,
            fam_probs=fam_probs,
            family_conf=family_conf,
            leaf_qs=leaf_qs,
            drafts=drafts,
            noul_fail=noul_attr(nouls, "will_fail_compile"),
            noul_pca=noul_attr(nouls, "breaks_pca"),
            per_leaf_fail=noul_map(nouls, [item.get("kind") for item in head_seq(drafts, 6)], prefix="fail_"),
            failed_stems=failed_stems_fn(if_none(memory, default={}), get_str(record, "name")),
            cut_score=getattr(cut, "score", None),
            usage=usage,
            wall_ms=wall_ms,
            greedy_fam_fallback=fam_choice,
            beam_k=beam_k,
            fire_t=fire_t,
            fire_t_leaf=fire_t_leaf,
            confident=confident,
            uncertain=uncertain,
            epsilon=epsilon,
        )

    return invoke_then_project(
        invoke_fn=lambda: invoke_system_one(client(timeout=client_timeout), state, questions),
        record_fn=lambda usage, model: record_usage(ledger, usage, model=model),
        unpack_fn=unpack_response,
        model=model_id,
        project_fn=_project,
    )


def rank_from_answers(
    *,
    tree: Mapping[str, Mapping[str, Any]],
    fam_probs: Mapping[str, float],
    family_conf: float,
    leaf_qs: Mapping[str, Mapping[str, Any]],
    drafts: Sequence[Mapping[str, Any]],
    noul_fail: float,
    noul_pca: float,
    per_leaf_fail: Mapping[str, float],
    failed_stems: Sequence[str] = (),
    cut_score: Any = None,
    usage: Optional[Mapping[str, Any]] = None,
    wall_ms: float = 0.0,
    greedy_fam_fallback: Any = None,
    beam_k: int = BEAM_K,
    fire_t: float = FIRE_T,
    fire_t_leaf: float = FIRE_T_LEAF,
    confident: float = CONFIDENT,
    uncertain: float = UNCERTAIN,
    epsilon: float = EPSILON,
) -> dict[str, Any]:
    """Rank family×leaf paths from Jev answers. Lake still admits."""

    qs = {fam: dict(q) for fam, q in leaf_qs.items()}
    for q in qs.values():
        q["family_confidence"] = float(family_conf)
    paths = rank_paths(tree, fam_probs, qs, beam_k=beam_k)
    greedy_leaf = paths[0]["leaf"] if paths else None
    fired_leaves, fired = fire_leaves(
        noul_fail=noul_fail,
        noul_pca=noul_pca,
        per_leaf=per_leaf_fail,
        failed_stems=failed_stems,
        fire_t=fire_t,
        fire_t_leaf=fire_t_leaf,
    )
    try:
        cut_norm = min(1.0, float(cut_score or 0.0) / 2.0)
    except (TypeError, ValueError):
        cut_norm = 0.0
    paths = composite_rank(paths, per_leaf_fail=per_leaf_fail, noul_fail=noul_fail, cut_norm=cut_norm)
    kinds = beam_kinds(
        paths,
        fired_leaves,
        greedy_leaf=greedy_leaf,
        noul_fail=noul_fail,
        fired=fired,
        fire_t=fire_t,
    )
    leaf_p = float(paths[0]["leaf_p"]) if paths else 0.0
    leaf_conf = float(paths[0]["leaf_confidence"]) if paths else 0.0
    kinds, abstain = abstain_beam(
        kinds,
        drafts,
        family_conf=family_conf,
        leaf_p=leaf_p,
        leaf_conf=leaf_conf,
        confident=confident,
        uncertain=uncertain,
    )
    greedy_fam = paths[0]["family"] if paths else greedy_fam_fallback
    return pack_beam(
        tree=tree,
        fam_probs=fam_probs,
        family_conf=family_conf,
        paths=paths,
        beam_kinds=kinds,
        abstain=abstain,
        noul_fail=noul_fail,
        noul_pca=noul_pca,
        per_leaf_fail=per_leaf_fail,
        fired_leaves=fired_leaves,
        fired=fired,
        cut_score=cut_score,
        usage=usage,
        wall_ms=wall_ms,
        greedy_fam=greedy_fam,
        greedy_leaf=greedy_leaf,
        leaf_qs=qs,
        epsilon=epsilon,
    )


def geo_mean(probs: Sequence[float], *, epsilon: float = EPSILON) -> float:
    live = [max(float(p), float(epsilon)) for p in probs if p is not None]
    if not live:
        return 0.0
    prod = 1.0
    for item in live:
        prod *= item
    return prod ** (1.0 / len(live))


def rank_paths(
    tree: Mapping[str, Mapping[str, Any]],
    fam_probs: Mapping[str, float],
    leaf_qs: Mapping[str, Mapping[str, Any]],
    *,
    beam_k: int = BEAM_K,
) -> list[dict[str, Any]]:
    fam_rank = sorted(tree, key=lambda fam: float(fam_probs.get(fam) or 0.0), reverse=True)
    paths: list[dict[str, Any]] = []
    family_conf = 0.0
    for fam in fam_rank[: max(1, int(beam_k))]:
        leaf_q = leaf_qs.get(fam) or {}
        family_conf = float(leaf_q.get("family_confidence") or family_conf)
        for leaf, _desc in (tree.get(fam) or {}).items():
            score = geo_mean(
                [float(fam_probs.get(fam) or 0.0), float((leaf_q.get("probabilities") or {}).get(leaf) or 0.0)]
            )
            paths.append(
                {
                    "family": fam,
                    "leaf": leaf,
                    "path_score": score,
                    "family_p": float(fam_probs.get(fam) or 0.0),
                    "leaf_p": float((leaf_q.get("probabilities") or {}).get(leaf) or 0.0),
                    "family_confidence": float(leaf_q.get("family_confidence") or 0.0),
                    "leaf_confidence": float(leaf_q.get("confidence") or 0.0),
                }
            )
    paths.sort(key=lambda item: item["path_score"], reverse=True)
    return paths


def fire_leaves(
    *,
    noul_fail: float,
    noul_pca: float,
    per_leaf: Mapping[str, float],
    failed_stems: Sequence[str] = (),
    fire_t: float = FIRE_T,
    fire_t_leaf: float = FIRE_T_LEAF,
) -> tuple[set[str], bool]:
    failed = {str(s) for s in failed_stems}
    fired: set[str] = set()
    for kind, prob in per_leaf.items():
        if float(prob) > fire_t:
            fired.add(str(kind))
        elif float(prob) > fire_t_leaf and (
            kind in failed or str(kind).replace("port_", "") in failed
        ):
            fired.add(str(kind))
    all_fired = noul_fail > fire_t or noul_pca > fire_t or bool(fired)
    return fired, all_fired


def composite_rank(
    paths: list[dict[str, Any]],
    *,
    per_leaf_fail: Mapping[str, float],
    noul_fail: float,
    cut_norm: float,
) -> list[dict[str, Any]]:
    for path in paths:
        noul = float(per_leaf_fail.get(str(path["leaf"]), noul_fail) or 0.0)
        path["composite"] = (
            0.45 * (1.0 - noul)
            + 0.25 * float(path["leaf_p"])
            + 0.20 * float(path["family_p"])
            + 0.10 * float(cut_norm)
        )
    paths.sort(key=lambda item: float(item.get("composite") or 0.0), reverse=True)
    return paths


def beam_kinds(
    paths: Sequence[Mapping[str, Any]],
    fired_leaves: set[str],
    *,
    greedy_leaf: Optional[str] = None,
    noul_fail: float = 0.0,
    fired: bool = False,
    fire_t: float = FIRE_T,
) -> list[str]:
    kinds = [str(item["leaf"]) for item in paths if item.get("leaf") and item["leaf"] not in fired_leaves]
    if not kinds:
        kinds = [str(item["leaf"]) for item in paths if item.get("leaf")]
    if fired and greedy_leaf in kinds and (noul_fail > fire_t or greedy_leaf in fired_leaves):
        kinds = [k for k in kinds if k != greedy_leaf]
    return kinds


def residual_features(
    residuals: Mapping[str, Any],
    nouls: Mapping[str, Any],
    scores: Mapping[str, Any],
    *,
    residual_to_skill: Optional[Mapping[str, Sequence[str]]] = None,
    fire_t_residual: float = FIRE_T_RESIDUAL,
) -> tuple[set[str], dict[str, float], dict[str, float]]:
    """Noul-unsafe residuals → skip-stems. Does not write Lean."""

    skip_skills: set[str] = set()
    residual_unsafe: dict[str, float] = {}
    residual_help: dict[str, float] = {}
    mapping = dict(residual_to_skill or {})
    for residual in residuals:
        unsafe = float(getattr(nouls.get(f"unsafe_{residual}"), "noul", 0.0) or 0.0)
        residual_unsafe[str(residual)] = unsafe
        help_ans = scores.get(f"help_{residual}")
        residual_help[str(residual)] = float(getattr(help_ans, "score", None) or 0.0)
        if unsafe > fire_t_residual:
            skip_skills.update(str(stem) for stem in mapping.get(residual, ()) or ())
    return skip_skills, residual_unsafe, residual_help


def intent_from_answers(
    *,
    choices: Mapping[str, Any],
    scores: Mapping[str, Any],
    nouls: Mapping[str, Any],
    skills: Mapping[str, Any],
    tree: Mapping[str, Any],
    residuals: Mapping[str, Any],
    residual_to_skill: Optional[Mapping[str, Sequence[str]]] = None,
    fire_t_residual: float = FIRE_T_RESIDUAL,
    fire_t: float = FIRE_T,
    fire_t_leaf: float = FIRE_T_LEAF,
    confident: float = CONFIDENT,
    uncertain: float = UNCERTAIN,
    high_stakes: bool = False,
    tree_node: str = "root",
    wall_ms: float = 0.0,
    memory: Optional[Mapping[str, Any]] = None,
    name: str = "",
    criteria: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Project Jev intent/compose/skill/residual answers, then route. No Lean."""

    intent = choices.get("intent")
    picked = str(getattr(intent, "choice", None) or "search_space")
    conf = float(getattr(intent, "confidence", None) or 0.0)
    probs = dict(getattr(intent, "probabilities", None) or {})
    minimal = float(getattr(nouls.get("already_minimal"), "noul", 0.0) or 0.0)
    complexity = float(getattr(scores.get("complexity"), "score", None) or 0.0)
    compose_ans = choices.get("compose")
    compose = str(getattr(compose_ans, "choice", None) or "single")
    skill_ans = choices.get("skill")
    skill = str(getattr(skill_ans, "choice", None) or "keep")
    if compose == "pipeline" and skill == "keep":
        skill = next((key for key in skills if str(key).startswith("port_pipeline")), "keep")
    skill_conf = float(getattr(skill_ans, "confidence", None) or 0.0)
    fail_skill = float(getattr(nouls.get(f"fail_skill_{skill}"), "noul", 0.0) or 0.0)
    nest_ans = choices.get("nest_child")
    nest_child = str(getattr(nest_ans, "choice", None) or "")
    tool_ans = choices.get("tool_name")
    tool_name = str(getattr(tool_ans, "choice", None) or "")
    skip_skills, residual_unsafe, residual_help = residual_features(
        residuals,
        nouls,
        scores,
        residual_to_skill=residual_to_skill,
        fire_t_residual=fire_t_residual,
    )
    routed = route_from_jev(
        picked=picked,
        conf=conf,
        probs=probs,
        minimal=minimal,
        complexity=complexity,
        compose=compose,
        skill=skill,
        skill_conf=skill_conf,
        fail_skill=fail_skill,
        nest_child=nest_child,
        tool_name=tool_name,
        skills=skills,
        tree=tree,
        residuals=residuals,
        residual_unsafe=residual_unsafe,
        residual_help=residual_help,
        skip_skills=sorted(skip_skills),
        fire_t=fire_t,
        fire_t_leaf=fire_t_leaf,
        confident=confident,
        uncertain=uncertain,
        high_stakes=high_stakes,
        tree_node=tree_node,
        wall_ms=wall_ms,
        memory=memory,
        name=name,
    )
    keys = criteria if criteria is not None else probs
    routed["probabilities"] = {k: float(probs.get(k) or 0.0) for k in keys}
    return routed


def route_from_jev(
    *,
    picked: str,
    conf: float,
    probs: Mapping[str, float],
    minimal: float,
    complexity: float,
    compose: str,
    skill: str,
    skill_conf: float,
    fail_skill: float,
    nest_child: str,
    tool_name: str,
    skills: Mapping[str, Any],
    tree: Mapping[str, Any],
    residuals: Mapping[str, Any],
    residual_unsafe: Mapping[str, float],
    residual_help: Mapping[str, float],
    skip_skills: Sequence[str],
    fire_t: float = FIRE_T,
    fire_t_leaf: float = FIRE_T_LEAF,
    confident: float = CONFIDENT,
    uncertain: float = UNCERTAIN,
    high_stakes: bool = False,
    tree_node: str = "root",
    wall_ms: float = 0.0,
    memory: Optional[Mapping[str, Any]] = None,
    name: str = "",
) -> dict[str, Any]:
    """Turn Jev Choice/Score/Noul answers into an inner-walk intent. No Lean."""

    from jevops.walk import CONTROL
    from jevops.walk import bias_compose_no_drafts

    floor = 0.85 if high_stakes else confident
    nxt_skill = skill
    if compose == "pipeline" and nxt_skill == "keep":
        nxt_skill = next((key for key in skills if str(key).startswith("port_pipeline")), "keep")
    skip = bool(minimal > fire_t and conf >= confident)
    if picked == "pca_keep" and len([k for k in skills if k != "keep"]) == 0:
        skip = True
    if nxt_skill == "keep" and skill_conf >= uncertain and minimal > fire_t:
        skip = True
    if fail_skill > fire_t_leaf and nxt_skill != "keep":
        nxt_skill = "keep"
    compose_out = bias_compose_no_drafts(
        compose, memory=dict(memory or {}), skills=skills, skill=nxt_skill, name=name
    )
    nest = nest_child
    if compose_out in CONTROL:
        skip = False
        if not nest:
            nest = picked if picked in tree else (nxt_skill if nxt_skill != "keep" else "")
    allow = {picked}
    if conf < floor:
        allow = {"dead_code", "strength_reduction", "search_space"}
    second = sorted(probs, key=lambda fam: float(probs.get(fam) or 0.0), reverse=True)
    if len(second) > 1 and float(probs.get(second[1]) or 0.0) >= 0.2:
        allow.add(second[1])
    return {
        "skipped": False,
        "intent": picked,
        "confidence": conf,
        "probabilities": {k: float(probs.get(k) or 0.0) for k in probs},
        "already_minimal": minimal,
        "complexity": complexity,
        "allow_families": allow,
        "skip_lake": skip,
        "uncertain": conf < floor,
        "skill": nxt_skill,
        "skill_confidence": skill_conf,
        "compose": compose_out,
        "nest_child": nest,
        "tool_name": tool_name,
        "tree": {fam: list(kids) for fam, kids in tree.items()},
        "tree_node": tree_node,
        "fail_skill": fail_skill,
        "skip_skills": sorted(skip_skills),
        "residual_unsafe": dict(residual_unsafe),
        "residual_help": dict(residual_help),
        "wall_ms": wall_ms,
        "jev_generated_lean": False,
    }


def abstain_beam(
    kinds: list[str],
    drafts: Sequence[Mapping[str, Any]],
    *,
    family_conf: float,
    leaf_p: float,
    leaf_conf: float,
    confident: float = CONFIDENT,
    uncertain: float = UNCERTAIN,
    safe: Sequence[str] = ("drop_unused_binders", "collapse_simp_at"),
) -> tuple[list[str], bool]:
    abstain = family_conf < confident or max(leaf_p, leaf_conf) < uncertain
    if not abstain:
        return kinds, False
    present = [k for k in safe if any(item.get("kind") == k for item in drafts)]
    return present + [k for k in kinds if k not in present], True


def order_pipeline(
    items: Sequence[tuple[str, Any]],
    memory: Optional[Mapping[str, Any]] = None,
    *,
    name: str = "",
    residual_map: Optional[Mapping[str, str]] = None,
    keep_stems: Sequence[str] = (),
    bayes_mean: Optional[Mapping[str, float]] = None,
    extra_kinds: Sequence[str] = ("drop_unused_binders", "collapse_simp_at"),
) -> tuple[tuple[str, Any], ...]:
    """Reorder (stem, payload) by wins, losses, nca bias, bayes, research help, keep."""

    from jevops.memory import research_help
    from jevops.memory import stem_win_loss

    wins, losses = stem_win_loss(memory, extra=extra_kinds)
    bias = list(((memory or {}).get("nca") or {}).get("pipeline_bias") or [])
    means = dict(bayes_mean or {})
    keep = set(keep_stems)
    ranked = sorted(
        list(items),
        key=lambda item: (
            -int(wins.get(item[0], 0)),
            int(losses.get(item[0], 0)),
            bias.index(item[0]) if item[0] in bias else len(bias),
            -float(means.get(item[0], 0.5)),
            -research_help(memory, item[0], name=name, residual_map=residual_map),
            0 if item[0] in keep else 1,
            item[0],
        ),
    )
    return tuple(ranked)


def skills_from_drafts(
    drafts: Sequence[Mapping[str, Any]],
    *,
    keep_spec: Any,
    criteria: Optional[Mapping[str, Any]] = None,
    pipeline_prefix: str = "port_pipeline_",
    pipeline_key: str = "port_pipeline",
) -> dict[str, Any]:
    """Named skills that actually change this script. Keep is always present."""

    skills: dict[str, Any] = {"keep": keep_spec}
    catalog = dict(criteria or {})
    for item in drafts:
        kind = str(item.get("kind") or "")
        if not kind:
            continue
        key = pipeline_key if kind.startswith(pipeline_prefix) else kind
        skills[kind] = catalog.get(
            key,
            {
                "what": f"{item.get('family')}; {item.get('token_count')} tok closed fold",
                "not_for": "A fold that TypeSafe Noul has already fired on this problem",
            },
        )
    return skills


def tree_from_drafts(
    drafts: Sequence[Mapping[str, Any]],
    *,
    default_family: str = "search_space",
) -> dict[str, list[str]]:
    """Family → skill kinds present in drafts."""

    tree: dict[str, list[str]] = {}
    for item in drafts:
        fam = str(item.get("family") or default_family)
        kind = str(item.get("kind") or "")
        if not kind:
            continue
        kids = tree.setdefault(fam, [])
        if kind not in kids:
            kids.append(kind)
    return tree


def family_criteria(
    families: Sequence[Any],
    *,
    structured: Optional[Mapping[str, Any]] = None,
    blurbs: Optional[Mapping[str, str]] = None,
    require_structured: bool = False,
) -> dict[str, Any]:
    """Choice criteria for families. Fallback is structured.what or blurb or name."""

    specs = dict(structured or {})
    names = dict(blurbs or {})
    out: dict[str, Any] = {}
    for fam in families:
        key = str(fam)
        if require_structured and key not in specs:
            continue
        out[key] = specs.get(key, {"what": names.get(key, key)})
    return out


def noul_map(
    nouls: Mapping[str, Any],
    keys: Sequence[Any],
    *,
    prefix: str = "fail_",
) -> dict[str, float]:
    """Project Noul answers ``{prefix}{key}`` onto a float map."""

    out: dict[str, float] = {}
    for raw in keys:
        key = str(raw or "")
        if not key:
            continue
        out[key] = float(getattr(nouls.get(f"{prefix}{key}"), "noul", 0.0) or 0.0)
    return out


def named_keys(keys: Sequence[Any], name: str, *, limit: int = 12) -> list[Any]:
    prefix = str(name or "")
    return [key for key in keys if str(key).startswith(prefix)][: int(limit)]


def filter_unsafe_drafts(
    drafts: Sequence[Mapping[str, Any]],
    *,
    is_blocked: Optional[Any] = None,
    unsafe: Optional[Mapping[str, Any]] = None,
    residual_map: Optional[Mapping[str, str]] = None,
    fire_t: float = FIRE_T_RESIDUAL,
    revalidate_portable: bool = False,
) -> list[Mapping[str, Any]]:
    """Drop blacklisted or Noul-unsafe leftover drafts. No Lean.

    ``revalidate_portable`` keeps an unblacklisted closed-vocabulary fold in
    the compiler queue even when an older TypeSafe/Noul snapshot marked its
    residual unsafe.  Noul is a routing prior, not a proof; this lets a fixed
    fold or a new implementation revision get a fresh Lake verdict while
    ``is_blocked`` still suppresses a candidate with a concrete failure.
    """

    mapping = dict(residual_map or {})
    scores = dict(unsafe or {})
    out: list[Mapping[str, Any]] = []
    for item in drafts:
        kind = str(item.get("kind") or "")
        if is_blocked is not None and is_blocked(kind):
            continue
        stem = kind[len("port_") :] if kind.startswith("port_") else kind
        stems = {stem}
        # A composed fold is named ``port_pipeline_<stem>_<stem>``.  Treat
        # each component as an independent residual gate; otherwise one
        # unsafe component can hide inside a pipeline name and survive the
        # same Noul filter that correctly removes its standalone draft.
        if stem.startswith("pipeline_"):
            encoded = f"_{stem[len('pipeline_') :]}_"
            stems.update(
                candidate
                for candidate in mapping
                if f"_{candidate}_" in encoded
            )
        residuals = {mapping[candidate] for candidate in stems if mapping.get(candidate)}
        if (
            not revalidate_portable or not kind.startswith("port_")
        ) and any(float(scores.get(residual) or 0.0) >= float(fire_t) for residual in residuals):
            continue
        out.append(item)
    return out


def compose_steps(
    body: str,
    items: Sequence[tuple[str, Any]],
    *,
    skip: Optional[set[str]] = None,
    prefix: str = "port_",
) -> tuple[str, list[str]]:
    """Apply ordered (stem, fn) transforms. Skip blocked stems. No Lean."""

    blocked = set(skip or ())
    text = str(body or "").strip("\n")
    applied: list[str] = []
    for stem, fn in items:
        if stem in blocked or f"{prefix}{stem}" in blocked:
            continue
        nxt = str(fn(text) or "").strip("\n")
        if nxt and nxt != text:
            text = nxt
            applied.append(str(stem))
    return text, applied


def drive_rank_live(
    records: Sequence[Mapping[str, Any]],
    *,
    out: Any,
    from_best: bool,
    memory: Optional[Mapping[str, Any]],
    warmup: Optional[Mapping[str, int]],
    keep: Optional[Mapping[str, int]],
    warmup_fn: Callable[[], Mapping[str, int]],
    keep_fn: Callable[[Any], Mapping[str, int]],
    start_fn: Callable[..., str],
    prior_fn: Callable[..., Mapping[str, Any]],
    drafts_fn: Callable[..., Sequence[Mapping[str, Any]]],
    blocked_fn: Callable[..., bool],
    residual_map: Mapping[str, str],
    fire_t: float,
    score_fn: Callable[..., Any],
) -> list[Mapping[str, Any]]:
    """Leftover un-blacklisted drafts, then remaining_cut. Does not compile."""

    from jevops.outer import first_truthy, get_str, ignore_error, or_load, overlay_map

    mem = overlay_map(memory)
    warm = or_load(warmup, lambda: ignore_error(warmup_fn, default={}))
    kept = or_load(keep, lambda: ignore_error(lambda: keep_fn(out), default={}))

    def _drafts(rec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        name = get_str(rec, "name")
        body = start_fn(rec, out=out, from_best=from_best)
        prior = prior_fn(mem, name)
        return filter_unsafe_drafts(
            drafts_fn(body, memory=mem, name=name),
            is_blocked=lambda kind: blocked_fn(mem, name, kind),
            unsafe=overlay_map(prior.get("unsafe")),
            residual_map=residual_map,
            fire_t=fire_t,
        )

    def _rf(drafts: list[Mapping[str, Any]], rec: Mapping[str, Any], cut: int) -> float:
        name = get_str(rec, "name")
        return float(first_truthy(score_fn(drafts, memory=mem, name=name, remaining_cut=cut), default=0.0))

    return rank_leftover(records, drafts_fn=_drafts, rf_fn=_rf, memory=mem, warmup=warm, keep=kept)


def rank_leftover(
    records: Sequence[Mapping[str, Any]],
    *,
    drafts_fn: Any,
    remaining_cut_fn: Optional[Any] = None,
    rf_fn: Optional[Any] = None,
    memory: Optional[dict[str, Any]] = None,
    warmup: Optional[Mapping[str, int]] = None,
    keep: Optional[Mapping[str, int]] = None,
) -> list[Mapping[str, Any]]:
    """Leftover un-blacklisted drafts first, then remaining-cut, then ranker score."""

    warm = dict(warmup or {})
    kept = dict(keep or {})
    scored: list[tuple[Any, ...]] = []
    for rec in records:
        name = str((rec or {}).get("name") or "")
        drafts = list(drafts_fn(rec) or [])
        if remaining_cut_fn is not None:
            cut = int(remaining_cut_fn(rec) or 0)
        else:
            cut = max(0, int(warm.get(name) or 0) - int(kept.get(name) or 0))
        rf_score = 0.0
        if rf_fn is not None:
            try:
                rf_score = float(rf_fn(drafts, rec, cut) or 0.0)
            except Exception:
                rf_score = 0.0
        scored.append(
            (*leftover_sort_key(n_drafts=len(drafts), remaining_cut=cut, rf_score=rf_score, name=name), rec)
        )
        if memory is not None:
            try:
                annotate_leftover(
                    memory,
                    name=name,
                    n_drafts=len(drafts),
                    remaining_cut=cut,
                    warmup=warm.get(name),
                    tokens=kept.get(name),
                )
            except Exception:
                pass
    return sort_keyed(scored)


def live_tree(
    family_tree: Mapping[str, Mapping[str, str]],
    available: Mapping[str, Any],
    *,
    keep_key: str = "keep",
) -> dict[str, dict[str, str]]:
    """Restrict a family→leaf catalog to leaves present in available."""

    tree: dict[str, dict[str, str]] = {}
    for fam, kids in dict(family_tree or {}).items():
        live = {str(leaf): str(desc) for leaf, desc in dict(kids or {}).items() if leaf in available}
        if live:
            tree[str(fam)] = live
    if keep_key not in tree and keep_key in (family_tree or {}):
        tree = {str(keep_key): dict(family_tree[keep_key]), **tree}
    return tree


def classification_from_answers(
    tree: Mapping[str, Mapping[str, Any]],
    choices: Mapping[str, Any],
    *,
    beam_k: int = BEAM_K,
    confident: float = CONFIDENT,
    epsilon: float = EPSILON,
) -> dict[str, Any]:
    """Family Choice + per-family leaf Choices → geo-mean paths. Jev did not write Lean."""

    fam_ans = (choices or {}).get("family")
    fam_probs = {
        str(fam): float(dict(getattr(fam_ans, "probabilities", None) or {}).get(fam) or 0.0)
        for fam in tree
    }
    family_conf = float(getattr(fam_ans, "confidence", None) or 0.0)
    family = {
        "choice": getattr(fam_ans, "choice", None),
        "confidence": family_conf,
        "probabilities": fam_probs,
    }
    leaf_qs = leaf_qs_from_choices(tree, choices or {}, family_conf=family_conf)
    paths = rank_paths(tree, fam_probs, leaf_qs, beam_k=beam_k)
    top = paths[0]["path_score"] if paths else 0.0
    second = paths[1]["path_score"] if len(paths) > 1 else float(epsilon)
    fam_rank = sorted(tree, key=lambda fam: float(fam_probs.get(fam) or 0.0), reverse=True)
    return {
        "family": family,
        "leaves": leaf_qs,
        "paths": paths,
        "beam_fams": fam_rank[: max(1, int(beam_k))],
        "separation": top / max(second, float(epsilon)),
        "abstain": family_conf < float(confident),
    }


def padded_id(index: int, *, prefix: str = "d", width: int = 3) -> str:
    return f"{prefix}{int(index):0{max(1, int(width))}d}"


def unique_capped(cap: int) -> tuple[Any, list[Any]]:
    """push(key, factory(index)) appends unique keys up to cap."""

    seen: set[str] = set()
    rows: list[Any] = []

    def push(key: str, factory: Any) -> bool:
        text = str(key or "")
        if not text or text in seen or len(rows) >= max(0, int(cap)):
            return False
        seen.add(text)
        rows.append(factory(len(rows)))
        return True

    return push, rows


def numbered_criteria(
    items: Sequence[Any],
    *,
    prefix: str = "c",
    fmt: Any = None,
) -> dict[str, Any]:
    """Map items to ``{prefix}{i}`` keys. fmt(index, item) optional."""

    out: dict[str, Any] = {}
    for index, item in enumerate(items or ()):
        key = f"{prefix}{index}"
        out[key] = fmt(index, item) if fmt is not None else item
    return out


def tree_from_items(
    items: Sequence[Any],
    *,
    family_fn: Any,
    kind_fn: Any,
    note_fn: Any,
    keep: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict[str, dict[str, str]]:
    """Build family→{kind: note} from items. ``keep`` seeds empty families."""

    tree: dict[str, dict[str, str]] = {str(key): dict(val) for key, val in dict(keep or {}).items()}
    for item in items or ():
        fam = str(family_fn(item) or "")
        kind = str(kind_fn(item) or "")
        if not fam or not kind:
            continue
        tree.setdefault(fam, {})[kind] = str(note_fn(item) or "")
    return tree


def first_apply(
    items: Sequence[Any],
    kind: str,
    text: str,
    *,
    kind_fn: Any,
    apply_fn: Any,
) -> str:
    """Apply the first item whose kind_fn matches. Else strip the body."""

    want = str(kind or "")
    body = str(text or "").strip("\n")
    for item in items or ():
        if str(kind_fn(item) or "") == want:
            return str(apply_fn(item, body) or "").strip("\n")
    return body


def unique_push(
    items: list[Any],
    seen: set[str],
    key: str,
    factory: Any,
    *,
    cap: int,
) -> bool:
    """Append factory(index, stripped_key) when key is new and under cap."""

    text = str(key or "").strip("\n")
    if not text or text in seen or len(items) >= max(0, int(cap)):
        return False
    seen.add(text)
    items.append(factory(len(items), text))
    return True


def project_items(items: Sequence[Any], fields: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project objects/mappings. values are attr names, mapping keys, or callables."""

    out: list[dict[str, Any]] = []
    for item in items or ():
        row: dict[str, Any] = {}
        for dest, src in dict(fields).items():
            if callable(src):
                row[str(dest)] = src(item)
            elif isinstance(item, Mapping):
                row[str(dest)] = item.get(src)
            else:
                row[str(dest)] = getattr(item, str(src), None)
        out.append(row)
    return out
