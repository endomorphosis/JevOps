#!/usr/bin/env python3
"""More NCA CALLs: wrap SGD/mask/diffuse; milles Markov, isotonic, AdaBoost,
quantile, PageRank, contrastive.

Jev does not write Lean. Lake is the oracle. Never docker0. Not Arena scores.
Integer milles in the hot path. ``isotonic`` is dispatched here so it is not
eaten by ``ica in isotonic``.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import random
import re
from typing import Any, Mapping, Optional, Sequence

MILLE = 1000
MORE_STEMS = (
    "sgd",
    "mask",
    "diffuse",
    "markov",
    "hmm",
    "isotonic",
    "platt",
    "adaboost",
    "boost",
    "quantile",
    "pagerank",
    "contrastive",
)
_HEAD = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)")


def is_more_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    return any(tag in text for tag in MORE_STEMS)


def _clip(value: int, lo: int = 0, hi: int = MILLE) -> int:
    return max(lo, min(hi, int(value)))


def _bias(memory: dict[str, Any], ranked: list[str], *, kind: str, **extra: Any) -> dict[str, Any]:
    if ranked:
        memory.setdefault("nca", {})["pipeline_bias"] = ranked
    out = {"ok": True, "kind": kind, "ranked": ranked, "writes_lean": False, "integer": True, "called_docker0": False}
    out.update(extra)
    return out


def call_mask(memory: dict[str, Any], *, tactics: str = "") -> dict[str, Any]:
    from jevops import hooks

    find_holes = hooks.resolve("find_holes", "mca_mask_replace", "find_holes")
    mask_skeleton = hooks.resolve("mask_skeleton", "mca_mask_replace", "mask_skeleton")
    if find_holes is None:
        return {"ok": False, "reason": "no_mask_impl", "kind": "port_mask", "writes_lean": False, "integer": True}
    holes = find_holes(tactics or "")
    skeleton = mask_skeleton(tactics or "", holes) if holes and mask_skeleton else tactics
    memory.setdefault("nca", {})["mask"] = {
        "n_holes": len(holes),
        "families": [h.family for h in holes],
        "integer": True,
    }
    return {
        "ok": True,
        "kind": "port_mask",
        "n_holes": len(holes),
        "families": [h.family for h in holes],
        "skeleton_len": len(skeleton or ""),
        "writes_lean": False,
        "integer": True,
    }


def call_sgd(memory: dict[str, Any], *, tactics: str = "") -> dict[str, Any]:
    """Closed wrap of sgd_fanout's hole minibatch. Does not lake or call docker0."""

    from jevops import hooks

    find_holes = hooks.resolve("find_holes", "mca_mask_replace", "find_holes")
    if find_holes is None:
        return {"ok": False, "reason": "no_mask_impl", "kind": "port_sgd", "writes_lean": False, "integer": True}
    holes = find_holes(tactics or "")
    ranked = sorted(holes, key=lambda hole: -(hole.end - hole.start))
    ids = [hole.hole_id for hole in ranked]
    memory.setdefault("nca", {})["sgd"] = {"minibatch": ids[:2], "n_holes": len(holes), "integer": True}
    return {
        "ok": True,
        "kind": "port_sgd",
        "n_holes": len(holes),
        "minibatch": ids[:2],
        "wraps": "sgd_fanout.jev_round/drop_subset",
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def call_diffuse(memory: dict[str, Any], *, tactics: str = "") -> dict[str, Any]:
    from jevops import hooks

    find_holes = hooks.resolve("find_symbol_holes", "symbol_diffuse", "find_symbol_holes")
    closed = hooks.resolve("closed_candidates", "symbol_diffuse", "closed_candidates")
    if find_holes is None:
        return {"ok": False, "reason": "no_diffuse_impl", "kind": "port_diffuse", "writes_lean": False, "integer": True}
    holes = find_holes(tactics or "")
    cands = closed(tactics or "", max_candidates=16) if tactics and closed else []
    cuts = sorted(cands, key=lambda row: int(row.get("token_count") or 10**9))
    kinds = [str(row.get("kind") or row.get("hole_id") or "") for row in cuts[:8]]
    memory.setdefault("nca", {})["diffuse"] = {"n_holes": len(holes), "n_cands": len(cands), "integer": True}
    return _bias(
        memory,
        [k for k in kinds if k],
        kind="port_diffuse",
        n_holes=len(holes),
        n_cands=len(cands),
        wraps="symbol_diffuse.closed_candidates",
    )


def _line_heads(tactics: str) -> list[str]:
    heads = []
    for line in str(tactics or "").splitlines():
        match = _HEAD.match(line)
        if match:
            heads.append(match.group(1))
    return heads


def call_markov(memory: dict[str, Any], *, tactics: str = "", hmm: bool = False) -> dict[str, Any]:
    """Mille bigrams of tactic heads. HMM adds a start-state milles vector."""

    texts = [tactics]
    for row in memory.get("successes") or []:
        if row.get("tactics"):
            texts.append(str(row.get("tactics")))
    counts: dict[str, dict[str, int]] = {}
    start: dict[str, int] = {}
    for text in texts:
        heads = _line_heads(text)
        if not heads:
            continue
        start[heads[0]] = start.get(heads[0], 0) + 1
        for prev, nxt in zip(heads, heads[1:]):
            counts.setdefault(prev, {})
            counts[prev][nxt] = counts[prev].get(nxt, 0) + 1
    trans_m: dict[str, dict[str, int]] = {}
    for prev, nxts in counts.items():
        tot = sum(nxts.values()) or 1
        trans_m[prev] = {k: (v * MILLE) // tot for k, v in nxts.items()}
    last = _line_heads(tactics)[-1] if _line_heads(tactics) else ""
    nxt = trans_m.get(last) or {}
    ranked = sorted(nxt, key=lambda k: (-nxt[k], k)) if nxt else sorted(start, key=lambda k: (-start[k], k))
    memory.setdefault("nca", {})["markov"] = {"trans_m": trans_m, "start": start, "hmm": hmm, "integer": True}
    return _bias(memory, ranked, kind="port_hmm" if hmm else "port_markov", n_from=len(trans_m), last=last)


def call_isotonic(memory: dict[str, Any]) -> dict[str, Any]:
    """PAVA: monotone milles P(ok | score). Calibrates Noul/unsafe vs lake labels."""

    pairs: list[tuple[int, int]] = []
    for lab, bucket in ((MILLE, memory.get("successes") or []), (0, memory.get("failures") or [])):
        for item in bucket:
            unsafe = item.get("unsafe")
            noul = item.get("noul") or item.get("noul_fail")
            if noul is None and unsafe is None:
                tokens = int(item.get("tokens") or item.get("token_count") or 0)
                score = _clip(tokens)  # longer → later; isotonic still defined
            else:
                raw = float(noul if noul is not None else unsafe or 0.0)
                score = _clip(int(raw * MILLE) if raw <= 2 else int(raw))
            pairs.append((score, lab))
    if len(pairs) < 2:
        return {"ok": True, "reason": "too_few_rows", "kind": "port_isotonic", "writes_lean": False, "integer": True}
    pairs.sort()
    # PAVA on milles labels
    blocks = [[lab, 1, score] for score, lab in pairs]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] * blocks[i + 1][1] > blocks[i + 1][0] * blocks[i][1]:
            n = blocks[i][1] + blocks[i + 1][1]
            s = blocks[i][0] + blocks[i + 1][0]
            blocks[i : i + 2] = [[s, n, blocks[i][2]]]
            i = max(0, i - 1)
        else:
            i += 1
    table = [{"score": b[2], "p_m": b[0] // max(1, b[1])} for b in blocks]
    memory.setdefault("nca", {})["isotonic"] = {"table": table, "integer": True}
    return {"ok": True, "kind": "port_isotonic", "n_blocks": len(table), "writes_lean": False, "integer": True}


def call_adaboost(memory: dict[str, Any], *, tactics: str = "", problem: str = "", rounds: int = 5) -> dict[str, Any]:
    from jevops import int_rankers as lra_int

    rows = lra_int.labeled_milles(memory)
    if len(rows) < 4:
        return {"ok": True, "reason": "too_few_rows", "kind": "port_adaboost", "writes_lean": False, "integer": True}
    n = len(rows)
    w = [MILLE // n] * n
    stumps: list[dict[str, int]] = []
    dim = len(rows[0][0])
    for _ in range(max(1, rounds)):
        best = None
        for d in range(dim):
            vals = sorted({feat[d] for feat, _y in rows})
            for thr in vals[:: max(1, len(vals) // 4)] or [0]:
                err = 0
                for i, (feat, lab) in enumerate(rows):
                    pred = MILLE if feat[d] <= thr else 0
                    if (pred >= 500) != (lab >= 500):
                        err += w[i]
                if best is None or err < best[0]:
                    best = (err, d, thr)
        if best is None:
            break
        err, d, thr = best
        err = min(max(err, 1), n * (MILLE // n) - 1)
        alpha = ((n * (MILLE // n) - err) * MILLE) // max(1, err)
        stumps.append({"d": d, "thr": thr, "alpha": alpha})
        for i, (feat, lab) in enumerate(rows):
            pred = MILLE if feat[d] <= thr else 0
            if (pred >= 500) != (lab >= 500):
                w[i] = w[i] + alpha // 8
        tot = sum(w) or 1
        w = [(x * MILLE) // tot for x in w]
    memory.setdefault("nca", {})["adaboost"] = {"stumps": stumps, "integer": True}

    def score(feat: Sequence[int]) -> int:
        acc = 0
        for stump in stumps:
            acc += stump["alpha"] if feat[stump["d"]] <= stump["thr"] else -stump["alpha"]
        return acc

    drafts: list[Mapping[str, Any]] = []
    try:
        from jevops import hooks

        drafts_fn = hooks.resolve("portable_drafts", "portable_rewrites", "portable_drafts")
        drafts = list(drafts_fn(tactics, memory=memory, name=problem)) if drafts_fn else []
    except Exception:
        drafts = []
    scored = []
    leftover = len(drafts)
    for item in drafts:
        feat = lra_int.feature_milles(
            kind=str(item.get("kind") or ""),
            tokens=int(item.get("token_count") or 0),
            memory=memory,
            name=problem,
            leftover=leftover,
        )
        scored.append((-score(feat), str(item.get("kind") or "")))
    scored.sort()
    ranked = [k.split("port_")[-1] if k.startswith("port_") else k for _s, k in scored if k]
    return _bias(memory, ranked, kind="port_adaboost", n_stumps=len(stumps))


def call_quantile(memory: dict[str, Any]) -> dict[str, Any]:
    """Mille remaining-cut quantiles 25/50/75 per stem from labeled tokens."""

    from jevops import rankers as lra_rank

    by: dict[str, list[int]] = {}
    for item in list(memory.get("successes") or []) + list(memory.get("failures") or []):
        stem = lra_rank._stem_of(str(item.get("kind") or ""))
        if not stem:
            continue
        cut = int(item.get("remaining_cut") or 0)
        if not cut:
            warm = int(item.get("warmup_tokens") or 0)
            keep = int(item.get("tokens") or item.get("token_count") or 0)
            cut = max(0, warm - keep) if warm else keep
        by.setdefault(stem, []).append(cut)
    table: dict[str, dict[str, int]] = {}
    for stem, vals in by.items():
        xs = sorted(vals)
        def q(p: int) -> int:
            if not xs:
                return 0
            return xs[min(len(xs) - 1, (p * (len(xs) - 1)) // 100)]
        table[stem] = {"q25": q(25), "q50": q(50), "q75": q(75), "n": len(xs)}
    ranked = sorted(table, key=lambda s: (-table[s]["q50"], s))
    memory.setdefault("nca", {})["quantile"] = {"table": table, "integer": True}
    return _bias(memory, ranked, kind="port_quantile", n_stems=len(table))


def call_pagerank(memory: dict[str, Any], *, iters: int = 8) -> dict[str, Any]:
    edges = list(((memory.get("nca") or {}).get("board_edges") or []))
    if not edges:
        try:
            from jevops import hooks

            seeder = hooks.resolve("seed_board", "board_graph", "seed_nca_from_board")
            if seeder:
                seeder(memory)
            edges = list(((memory.get("nca") or {}).get("board_edges") or []))
        except Exception:
            edges = []
    nodes: set[str] = set()
    adj: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        a, b = str(edge[0]), str(edge[1])
        nodes.add(a)
        nodes.add(b)
        adj.setdefault(a, []).append(b)
    if not nodes:
        return {"ok": True, "reason": "no_edges", "kind": "port_pagerank", "writes_lean": False, "integer": True}
    n = len(nodes)
    pr = {node: MILLE // n for node in nodes}
    damp = 85  # 0.85
    for _ in range(max(1, iters)):
        nxt = {node: ((100 - damp) * MILLE) // (100 * n) for node in nodes}
        for src, dests in adj.items():
            if not dests:
                continue
            share = (damp * pr[src]) // (100 * len(dests))
            for dst in dests:
                nxt[dst] = nxt.get(dst, 0) + share
        pr = nxt
    ranked = sorted(pr, key=lambda node: (-pr[node], node))
    memory.setdefault("nca", {})["pagerank"] = {"pr": pr, "integer": True}
    return _bias(memory, ranked[:12], kind="port_pagerank", n_nodes=n)


def call_contrastive(memory: dict[str, Any], *, tactics: str = "", problem: str = "") -> dict[str, Any]:
    """Mille (neg − pos + margin) on VAE latents. Diagnostic; Jev stays the loss."""

    from jevops import autoencoder as lra_ae

    batch = list(((memory.get("nca") or {}).get("autoencoder") or {}).get("batch") or [])
    cur = lra_ae.encode_milles(tactics or problem or "")
    pos = 0
    neg = 0
    n_pos = 0
    n_neg = 0
    for row in batch:
        other = list(row.get("mu") or [])
        if not other:
            continue
        sim = lra_ae.cosine_milles(cur["mu"], other)
        if str(row.get("problem") or "") == str(problem or "") and problem:
            pos += sim
            n_pos += 1
        else:
            neg += sim
            n_neg += 1
    pos_m = pos // max(1, n_pos) if n_pos else 0
    neg_m = neg // max(1, n_neg) if n_neg else 0
    margin = 100
    loss_m = _clip(neg_m - pos_m + margin)
    memory.setdefault("nca", {}).setdefault("autoencoder", {})["contrastive_m"] = loss_m
    return {
        "ok": True,
        "kind": "port_contrastive",
        "pos_m": pos_m,
        "neg_m": neg_m,
        "loss_m": loss_m,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "gold": False,
        "writes_lean": False,
        "integer": True,
    }


def call_more(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    _ = rng
    text = str(stem or "").lower()
    if "sgd" in text:
        return call_sgd(memory, tactics=tactics)
    if "mask" in text:
        return call_mask(memory, tactics=tactics)
    if "diffuse" in text:
        return call_diffuse(memory, tactics=tactics)
    if "hmm" in text:
        return call_markov(memory, tactics=tactics, hmm=True)
    if "markov" in text:
        return call_markov(memory, tactics=tactics, hmm=False)
    if "isotonic" in text or "platt" in text:
        return call_isotonic(memory)
    if "adaboost" in text or "boost" in text:
        return call_adaboost(memory, tactics=tactics, problem=problem)
    if "quantile" in text:
        return call_quantile(memory)
    if "pagerank" in text:
        return call_pagerank(memory)
    if "contrastive" in text:
        return call_contrastive(memory, tactics=tactics, problem=problem)
    return {"ok": False, "reason": "unknown_more", "stem": stem, "writes_lean": False}
