#!/usr/bin/env python3
"""Jev beam ranking: family×leaf paths, Noul fire, composite milles-style scores.

Does not write Lean. Lake (or another oracle) still admits.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

EPSILON = 1e-9
BEAM_K = 3
FIRE_T = 0.7
FIRE_T_RESIDUAL = 0.5
FIRE_T_LEAF = 0.45
CONFIDENT = 0.55
UNCERTAIN = 0.60


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
        "beam_kinds": list(beam_kinds)[:8],
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


def geo_mean(probs: Sequence[float]) -> float:
    live = [max(float(p), EPSILON) for p in probs]
    prod = 1.0
    for item in live:
        prod *= item
    return prod ** (1.0 / max(1, len(live)))


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
) -> list[Mapping[str, Any]]:
    """Drop blacklisted or Noul-unsafe leftover drafts. No Lean."""

    mapping = dict(residual_map or {})
    scores = dict(unsafe or {})
    out: list[Mapping[str, Any]] = []
    for item in drafts:
        kind = str(item.get("kind") or "")
        if is_blocked is not None and is_blocked(kind):
            continue
        stem = kind[len("port_") :] if kind.startswith("port_") else kind
        residual = mapping.get(stem, "")
        if residual and float(scores.get(residual) or 0.0) >= float(fire_t):
            continue
        out.append(item)
    return out


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
