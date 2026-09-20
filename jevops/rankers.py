#!/usr/bin/env python3
"""NCA ranking skills: RF, Bayes-time, MCMC, grid SVD, PCA CALL, Thompson, ridge.

These skills rank portable drafts / pipeline stems. They do not write Lean.
Lake remains the oracle. Jev does not generate tactic text. Never docker0.
Not Arena scores. Not Track 2. Proof-style PCA already lives in pca_mca_fanout
(np.linalg.svd); port_pca exposes it. port_svd factors theorem×skill lake wins.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Mapping, Optional, Sequence

PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
BAYES_DECAY = 0.98
RF_TREES = 7
RF_DEPTH = 4
MCMC_STEPS = 8
MCMC_TEMP = 1.0

RANKER_STEMS = (
    "random_forest",
    "bayes_time",
    "mcmc",
    "svd",
    "pca",
    "thompson",
    "ridge",
    "kmeans",
    "knn",
    "logistic",
    "ols",
    "ica",
    "nmf",
    "kalman",
    "autoencoder",
    "vae",
    "lean_ir",
    "gan",
    "sgd",
    "mask",
    "diffuse",
    "markov",
    "hmm",
    "isotonic",
    "platt",
    "adaboost",
    "quantile",
    "pagerank",
    "contrastive",
    "graphrag",
    "graph_traverse",
    "neural_graph",
    "skill_tree",
    "hawkes",
    "crf",
    "submodular",
    "delayed_bandit",
    "tape_conv",
    "tape_fft",
    "turing",
    "tm_step",
    "decision_transformer",
    "tape_splice",
    "tape_mask",
    "tape_pop",
    "tape_crop",
    "tape_keep",
    "got",
    "nca_plan",
    "cache_put",
    "cache_get",
    "cache_lru",
    "cache_arc",
    "negative_ttl",
    "singleflight",
    "context_budget",
    "nca_kernel",
)
RIDGE_L2 = 1.0
SVD_RANK = 3


def residual_feature_scores(
    counts: Mapping[str, Any],
    mean: Sequence[Any],
    std: Sequence[Any],
    components: Sequence[Mapping[str, Any]],
    feature_names: Sequence[str],
    *,
    loadings_key: str = "loadings",
) -> dict[str, float]:
    """Z-score a count row against SVD mean/std, then sum |loading × z| on minor components.

    Pure Python. numpy is not required. Feature names stay with the consumer.
    """

    names = [str(name) for name in feature_names]
    zscore: list[float] = []
    for index, name in enumerate(names):
        scale = float(std[index]) if index < len(std) else 1.0
        center = float(mean[index]) if index < len(mean) else 0.0
        value = float(counts.get(name) or 0.0)
        zscore.append((value - center) / scale if scale else 0.0)
    scores = {name: 0.0 for name in names}
    for component in components or ():
        loadings = (component or {}).get(loadings_key) or {}
        for index, name in enumerate(names):
            scores[name] += abs(float(loadings.get(name) or 0.0) * zscore[index])
    return scores


def rank_present_families(
    counts: Mapping[str, Any],
    scores: Mapping[str, Any],
    family_features: Mapping[str, Sequence[str]],
    *,
    top_k: int = 5,
    score_key: str = "mca_score",
) -> list[dict[str, Any]]:
    """Families whose features are present, ranked by summed scores. No numpy."""

    families: list[dict[str, Any]] = []
    for family, features in dict(family_features or {}).items():
        hit = [name for name in features if float(counts.get(name) or 0) > 0]
        if not hit:
            continue
        families.append(
            {
                "family": family,
                "features": hit,
                score_key: float(sum(float(scores.get(name) or 0.0) for name in hit)),
                "present": {name: counts[name] for name in hit},
            }
        )
    families.sort(key=lambda item: float(item.get(score_key) or 0.0), reverse=True)
    return families[: max(0, int(top_k))]


def update_feature_weights(
    rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    features: Sequence[str],
    penalty: Sequence[str] = (),
    lr: float = 0.3,
    floor: float = 0.05,
    ok_key: str = "ok",
    features_key: str = "features",
) -> dict[str, float]:
    """Nudge weights from ok vs fail feature means. One AutoResearch step."""

    ok = [row for row in rows if row.get(ok_key)]
    bad = [row for row in rows if row.get(ok_key) is False]
    if not ok or not bad:
        return dict(weights)
    banned = set(penalty)
    updated = dict(weights)
    for name in features:
        mean_ok = sum(float((r.get(features_key) or {}).get(name) or 0.0) for r in ok) / len(ok)
        mean_bad = sum(float((r.get(features_key) or {}).get(name) or 0.0) for r in bad) / len(bad)
        gap = (mean_bad - mean_ok) if name in banned else (mean_ok - mean_bad)
        updated[name] = max(float(floor), float(updated.get(name) or 0.5) + float(lr) * gap)
    return updated


def zscore_svd(
    rows: Sequence[Sequence[float]],
    *,
    n_principal: int = 3,
    n_minor: int = 3,
    feature_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Z-score rows then SVD. numpy is imported lazily. Not a lake admit."""

    from jevops.outer import try_import

    np = try_import("numpy")
    if np is None:
        raise RuntimeError("numpy is required for zscore_svd")
    matrix = np.asarray([list(row) for row in rows], dtype=float)
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std == 0] = 1.0
    zscore = (matrix - mean) / std
    _, singular, vt = np.linalg.svd(zscore, full_matrices=False)
    n_comp = int(vt.shape[0])
    n_principal = max(1, min(int(n_principal), n_comp))
    n_minor = max(1, min(int(n_minor), n_comp))
    names = [str(name) for name in feature_names] or [str(i) for i in range(int(matrix.shape[1]))]
    explained = singular ** 2
    total = float(explained.sum())
    explained = explained / total if total else explained
    principal = vt[:n_principal]
    minor = vt[-n_minor:]
    return {
        "n_rows": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "feature_names": names,
        "mean": mean.tolist(),
        "std": std.tolist(),
        "singular_values": singular.tolist(),
        "explained_ratio": explained.tolist(),
        "principal": [
            {
                "index": index,
                "explained": float(explained[index]),
                "loadings": dict(zip(names, component.tolist())),
            }
            for index, component in enumerate(principal)
        ],
        "minor": [
            {
                "index": n_comp - n_minor + index,
                "explained": float(explained[n_comp - n_minor + index]),
                "loadings": dict(zip(names, component.tolist())),
            }
            for index, component in enumerate(minor)
        ],
        "zscore": zscore,
        "vt": vt,
    }


def signed_dot(
    features: Mapping[str, float],
    weights: Mapping[str, float],
    *,
    penalty: Sequence[str] = (),
    default_w: float = 0.5,
) -> float:
    """Weighted sum; names in penalty subtract. Missing weight → default_w."""

    banned = {str(name) for name in penalty}
    score = 0.0
    for name, val in dict(features or {}).items():
        weight = float(weights.get(name) or default_w)
        score += (-weight if str(name) in banned else weight) * float(val)
    return score


def is_ranker_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    return any(tag in text for tag in RANKER_STEMS)


def _clip01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number != number:
        return 0.5
    return max(0.0, min(1.0, number))


def _stem_of(kind: str) -> str:
    text = str(kind or "")
    if text.startswith("port_"):
        text = text[len("port_") :]
    return text.split("_pipeline")[0]


def _bayes_store(memory: dict[str, Any]) -> dict[str, Any]:
    return memory.setdefault("nca", {}).setdefault("bayes", {})


def _forest_store(memory: dict[str, Any]) -> dict[str, Any]:
    return memory.setdefault("nca", {}).setdefault("random_forest", {})


def feature_row(
    *,
    kind: str = "",
    tokens: int = 0,
    memory: Optional[Mapping[str, Any]] = None,
    name: str = "",
    leftover: int = 0,
    remaining_cut: int = 0,
) -> list[float]:
    """Closed feature bag for RF. No Lean text."""

    stem = _stem_of(kind)
    mem = dict(memory or {})
    wins = 0
    losses = 0
    for row in mem.get("successes") or []:
        if _stem_of(str(row.get("kind") or "")) == stem:
            wins += 1
    for row in mem.get("failures") or []:
        if _stem_of(str(row.get("kind") or "")) == stem:
            losses += 1
    help_score = 0.0
    unsafe = 0.0
    n_help = 0
    residual = ""
    try:
        from jevops import hooks

        residual_map = hooks.call("skill_residual_map", default=None)
        if residual_map is None:
            port = hooks.try_import("portable_rewrites")
            residual_map = getattr(port, "SKILL_RESIDUAL", {}) if port else {}
        residual = str((residual_map or {}).get(stem) or "")
    except Exception:
        residual = ""
    for row in mem.get("research") or []:
        if name and row.get("name") != name:
            continue
        if residual and residual in (row.get("help") or {}):
            help_score += float((row.get("help") or {}).get(residual) or 0.0)
            unsafe += float((row.get("unsafe") or {}).get(residual) or 0.0)
            n_help += 1
    if n_help:
        help_score /= n_help
        unsafe /= n_help
    bayes = posterior(mem, stem)
    return [
        float(tokens) / 100.0,
        float(wins),
        float(losses),
        help_score,
        unsafe,
        float(remaining_cut) / 100.0,
        float(leftover),
        float(bayes.get("mean") or 0.5),
    ]


def observe_bayes(memory: dict[str, Any], stem: str, *, ok: bool, now: float = 0.0) -> dict[str, Any]:
    """One Bernoulli observation. Exponential forget toward the prior."""

    store = _bayes_store(memory)
    key = _stem_of(stem)
    row = dict(store.get(key) or {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA, "n": 0, "t": 0.0})
    row["alpha"] = PRIOR_ALPHA + BAYES_DECAY * max(0.0, float(row.get("alpha") or PRIOR_ALPHA) - PRIOR_ALPHA)
    row["beta"] = PRIOR_BETA + BAYES_DECAY * max(0.0, float(row.get("beta") or PRIOR_BETA) - PRIOR_BETA)
    if ok:
        row["alpha"] = float(row["alpha"]) + 1.0
    else:
        row["beta"] = float(row["beta"]) + 1.0
    row["n"] = int(row.get("n") or 0) + 1
    row["t"] = float(now or row.get("t") or 0.0) + 1.0
    store[key] = row
    return posterior(memory, key)


def posterior(memory: Mapping[str, Any], stem: str) -> dict[str, float]:
    store = ((memory.get("nca") or {}).get("bayes") or {}) if isinstance(memory, dict) else {}
    row = store.get(_stem_of(stem)) or {}
    alpha = float(row.get("alpha") or PRIOR_ALPHA)
    beta = float(row.get("beta") or PRIOR_BETA)
    total = max(alpha + beta, 1e-9)
    mean = alpha / total
    # Beta variance; used as uncertainty over time.
    var = (alpha * beta) / (total * total * (total + 1.0))
    return {
        "alpha": alpha,
        "beta": beta,
        "mean": _clip01(mean),
        "variance": max(0.0, var),
        "n": float(row.get("n") or 0.0),
        "t": float(row.get("t") or 0.0),
    }


def sync_bayes_from_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Conjugate Beta counts from successes/failures. Live `observe_bayes` adds time decay."""

    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for row in memory.get("successes") or []:
        stem = _stem_of(str(row.get("kind") or ""))
        if stem:
            wins[stem] = wins.get(stem, 0) + 1
    for row in memory.get("failures") or []:
        stem = _stem_of(str(row.get("kind") or ""))
        if stem:
            losses[stem] = losses.get(stem, 0) + 1
    store = memory.setdefault("nca", {}).setdefault("bayes", {})
    store.clear()
    for stem in set(wins) | set(losses):
        w = int(wins.get(stem, 0))
        l = int(losses.get(stem, 0))
        store[stem] = {
            "alpha": PRIOR_ALPHA + float(w),
            "beta": PRIOR_BETA + float(l),
            "n": w + l,
            "t": float(w + l),
        }
    out = {stem: posterior(memory, stem) for stem in store}
    return {"ok": True, "n": len(out), "posteriors": out, "writes_lean": False}


def apply_bayes_to_grid(memory: dict[str, Any]) -> int:
    """Write posterior mean onto matching skill cells as energy."""

    from jevops import hooks

    upsert = hooks.get("upsert_cell")
    if upsert is None:
        from jevops.nca import upsert_from_event as upsert
    n = 0
    for stem in list(_bayes_store(memory)):
        mean = float(posterior(memory, stem)["mean"])
        ptr = f"ptr://skill/port_{_stem_of(stem)}"
        if upsert:
            upsert(memory, ptr=ptr, kind="skill", energy=mean)
        n += 1
    return n


def _gini(labels: Sequence[int]) -> float:
    if not labels:
        return 0.0
    p = sum(labels) / float(len(labels))
    return 2.0 * p * (1.0 - p)


def _fit_tree(
    rows: list[tuple[list[float], int]],
    *,
    depth: int,
    rng: random.Random,
    max_depth: int,
    min_leaf: int = 2,
) -> dict[str, Any]:
    labels = [lab for _feat, lab in rows]
    if depth >= max_depth or len(rows) < 2 * min_leaf or len(set(labels)) <= 1:
        return {"leaf": (sum(labels) / float(len(labels))) if labels else 0.5}
    n_feat = len(rows[0][0])
    n_try = max(1, int(math.sqrt(n_feat)) + 1)
    best: Optional[tuple[float, int, float, list, list]] = None
    for _ in range(n_try * 3):
        col = rng.randrange(n_feat)
        vals = sorted({feat[col] for feat, _lab in rows})
        if len(vals) < 2:
            continue
        thr = vals[rng.randrange(len(vals) - 1)]
        left = [row for row in rows if row[0][col] <= thr]
        right = [row for row in rows if row[0][col] > thr]
        if len(left) < min_leaf or len(right) < min_leaf:
            continue
        g = (
            len(left) * _gini([lab for _f, lab in left])
            + len(right) * _gini([lab for _f, lab in right])
        ) / float(len(rows))
        if best is None or g < best[0]:
            best = (g, col, thr, left, right)
    if best is None:
        return {"leaf": (sum(labels) / float(len(labels))) if labels else 0.5}
    return {
        "col": best[1],
        "thr": best[2],
        "left": _fit_tree(best[3], depth=depth + 1, rng=rng, max_depth=max_depth, min_leaf=min_leaf),
        "right": _fit_tree(best[4], depth=depth + 1, rng=rng, max_depth=max_depth, min_leaf=min_leaf),
    }


def _eval_tree(node: Mapping[str, Any], feat: Sequence[float]) -> float:
    if "leaf" in node:
        return float(node["leaf"])
    if feat[int(node["col"])] <= float(node["thr"]):
        return _eval_tree(node["left"], feat)
    return _eval_tree(node["right"], feat)


def train_random_forest(memory: dict[str, Any], *, rng: Optional[random.Random] = None) -> dict[str, Any]:
    """Bootstrap trees on memory successes (1) / failures (0)."""

    rng = rng or random.Random(0)
    rows: list[tuple[list[float], int]] = []
    for label, bucket in ((1, memory.get("successes") or []), (0, memory.get("failures") or [])):
        for item in bucket:
            kind = str(item.get("kind") or "")
            if not kind:
                continue
            feat = feature_row(
                kind=kind,
                tokens=int(item.get("tokens") or item.get("token_count") or 0),
                memory=memory,
                name=str(item.get("name") or ""),
            )
            rows.append((feat, label))
    if len(rows) < 4:
        _forest_store(memory)["trees"] = []
        _forest_store(memory)["n_rows"] = len(rows)
        return {"ok": True, "n_trees": 0, "n_rows": len(rows), "reason": "too_few_rows", "writes_lean": False}
    trees: list[dict[str, Any]] = []
    for _ in range(RF_TREES):
        bag = [rows[rng.randrange(len(rows))] for _ in rows]
        trees.append(_fit_tree(bag, depth=0, rng=rng, max_depth=RF_DEPTH))
    store = _forest_store(memory)
    store["trees"] = trees
    store["n_rows"] = len(rows)
    return {"ok": True, "n_trees": len(trees), "n_rows": len(rows), "writes_lean": False}


def score_forest(memory: Mapping[str, Any], feat: Sequence[float]) -> float:
    trees = ((memory.get("nca") or {}).get("random_forest") or {}).get("trees") or []
    if not trees:
        return 0.5
    return sum(_eval_tree(tree, feat) for tree in trees) / float(len(trees))


def rank_drafts_forest(
    drafts: Sequence[Mapping[str, Any]],
    *,
    memory: Mapping[str, Any],
    name: str = "",
    remaining_cut: int = 0,
) -> list[Mapping[str, Any]]:
    scored: list[tuple[float, Mapping[str, Any]]] = []
    leftover = len(drafts)
    for item in drafts:
        feat = feature_row(
            kind=str(item.get("kind") or ""),
            tokens=int(item.get("token_count") or 0),
            memory=memory,
            name=name,
            leftover=leftover,
            remaining_cut=remaining_cut,
        )
        scored.append((-score_forest(memory, feat), item))
    scored.sort(key=lambda row: (row[0], str(row[1].get("kind") or "")))
    return [item for _score, item in scored]


def metropolis_hastings(
    state: Any,
    *,
    propose: Callable[[Any, random.Random], Any],
    energy: Callable[[Any], float],
    accept: Optional[Callable[[Any], bool]] = None,
    rng: Optional[random.Random] = None,
    steps: int = MCMC_STEPS,
    temperature: float = MCMC_TEMP,
) -> dict[str, Any]:
    """Generic MH. `accept` is a hard constraint (lake / closed fold). No Lean write."""

    from jevops.outer import head_seq

    rng = rng or random.Random(0)
    current = state
    cur_e = float(energy(current))
    trace: list[dict[str, Any]] = []
    best = current
    best_e = cur_e
    n_acc = 0
    for step in range(max(1, int(steps))):
        nxt = propose(current, rng)
        if nxt is current or nxt == current:
            trace.append({"step": step, "accepted": False, "reason": "noop"})
            continue
        if accept is not None and not accept(nxt):
            trace.append({"step": step, "accepted": False, "reason": "hard_reject"})
            continue
        nxt_e = float(energy(nxt))
        delta = nxt_e - cur_e
        temp = max(1e-6, float(temperature))
        if delta <= 0.0 or rng.random() < math.exp(-delta / temp):
            current = nxt
            cur_e = nxt_e
            n_acc += 1
            if nxt_e < best_e:
                best = nxt
                best_e = nxt_e
            trace.append({"step": step, "accepted": True, "energy": nxt_e, "delta": delta})
        else:
            trace.append({"step": step, "accepted": False, "energy": nxt_e, "delta": delta, "reason": "mh"})
    return {
        "ok": True,
        "state": current,
        "energy": cur_e,
        "best": best,
        "best_energy": best_e,
        "n_accept": n_acc,
        "n_steps": max(1, int(steps)),
        "trace": head_seq(trace, 32),
        "writes_lean": False,
        "called_docker0": False,
    }


def _pipeline_stems(memory: Mapping[str, Any], *, name: str = "") -> list[str]:
    try:
        from jevops import hooks

        order_fn = hooks.resolve("pipeline_order", "portable_rewrites", "pipeline_order")
        if order_fn is None:
            return []
        return [stem for stem, _fn in order_fn(dict(memory), name=name)]
    except Exception:
        return []


def mcmc_pipeline_order(
    memory: dict[str, Any],
    *,
    name: str = "",
    rng: Optional[random.Random] = None,
    steps: int = MCMC_STEPS,
) -> dict[str, Any]:
    """MH over pipeline stem order. Energy = sum of (1 - Bayes mean)."""

    stems = _pipeline_stems(memory, name=name)
    if len(stems) < 2:
        return {"ok": True, "reason": "too_short", "stems": stems, "writes_lean": False}

    def energy(order: Sequence[str]) -> float:
        total = 0.0
        for index, stem in enumerate(order):
            mean = float(posterior(memory, stem).get("mean") or 0.5)
            total += (1.0 - mean) + 0.01 * float(index)
        return total

    def propose(order: Sequence[str], rng_local: random.Random) -> list[str]:
        nxt = list(order)
        i = rng_local.randrange(len(nxt))
        j = rng_local.randrange(len(nxt))
        nxt[i], nxt[j] = nxt[j], nxt[i]
        return nxt

    ran = metropolis_hastings(list(stems), propose=propose, energy=energy, rng=rng, steps=steps)
    best = list(ran.get("best") or stems)
    memory.setdefault("nca", {})["pipeline_bias"] = best
    ran["stems"] = best
    ran["kind"] = "port_mcmc"
    return ran


def _labeled_rows(memory: Mapping[str, Any]) -> list[tuple[list[float], int]]:
    rows: list[tuple[list[float], int]] = []
    for label, bucket in ((1, memory.get("successes") or []), (0, memory.get("failures") or [])):
        for item in bucket:
            kind = str(item.get("kind") or "")
            if not kind:
                continue
            rows.append(
                (
                    feature_row(
                        kind=kind,
                        tokens=int(item.get("tokens") or item.get("token_count") or 0),
                        memory=memory,
                        name=str(item.get("name") or ""),
                    ),
                    label,
                )
            )
    return rows


def lake_win_matrix(memory: Mapping[str, Any]) -> tuple[list[str], list[str], list[list[float]]]:
    """Theorem × skill signed lake counts (win +1, fail −1)."""

    cells: dict[tuple[str, str], float] = {}
    for sign, bucket in ((1.0, memory.get("successes") or []), (-1.0, memory.get("failures") or [])):
        for item in bucket:
            thm = str(item.get("name") or "")
            stem = _stem_of(str(item.get("kind") or ""))
            if not thm or not stem:
                continue
            cells[(thm, stem)] = cells.get((thm, stem), 0.0) + sign
    theorems = sorted({key[0] for key in cells})
    skills = sorted({key[1] for key in cells})
    matrix = [[cells.get((thm, stem), 0.0) for stem in skills] for thm in theorems]
    return theorems, skills, matrix


def fit_grid_svd(memory: dict[str, Any], *, rank: int = SVD_RANK) -> dict[str, Any]:
    """Truncated SVD on the theorem×skill lake matrix. Not proof-AST PCA."""

    theorems, skills, matrix = lake_win_matrix(memory)
    if len(theorems) < 2 or len(skills) < 2:
        memory.setdefault("nca", {})["svd"] = {}
        return {
            "ok": True,
            "reason": "too_small",
            "n_theorems": len(theorems),
            "n_skills": len(skills),
            "writes_lean": False,
            "kind": "port_svd",
        }
    try:
        import numpy as np
    except Exception:
        return {"ok": False, "reason": "no_numpy", "writes_lean": False, "kind": "port_svd"}
    arr = np.asarray(matrix, dtype=float)
    u, singular, vt = np.linalg.svd(arr, full_matrices=False)
    k = max(1, min(int(rank), int(singular.shape[0])))
    recon = (u[:, :k] * singular[:k]) @ vt[:k]
    scores = {
        theorems[i]: {skills[j]: float(recon[i, j]) for j in range(len(skills))}
        for i in range(len(theorems))
    }
    memory.setdefault("nca", {})["svd"] = {
        "theorems": theorems,
        "skills": skills,
        "k": k,
        "singular": [float(x) for x in singular[:k]],
        "scores": scores,
    }
    return {
        "ok": True,
        "n_theorems": len(theorems),
        "n_skills": len(skills),
        "k": k,
        "singular": [float(x) for x in singular[:k]],
        "writes_lean": False,
        "kind": "port_svd",
    }


def recommend_svd(memory: dict[str, Any], *, problem: str = "") -> dict[str, Any]:
    """Rank skills for a theorem from reconstructed SVD scores."""

    fitted = fit_grid_svd(memory)
    blob = ((memory.get("nca") or {}).get("svd") or {})
    scores = dict(blob.get("scores") or {})
    skills = list(blob.get("skills") or [])
    if not scores or not skills:
        fitted["ranked"] = []
        return fitted
    if problem in scores:
        row = dict(scores[problem])
    else:
        row = {stem: 0.0 for stem in skills}
        n = 0
        for other in scores.values():
            n += 1
            for stem, val in other.items():
                row[stem] = row.get(stem, 0.0) + float(val)
        if n:
            row = {stem: val / float(n) for stem, val in row.items()}
    ranked = sorted(row, key=lambda stem: (-float(row[stem]), stem))
    memory.setdefault("nca", {})["pipeline_bias"] = ranked
    fitted["ranked"] = ranked
    fitted["problem"] = problem
    fitted["ok"] = True
    return fitted


def call_pca(
    memory: dict[str, Any],
    *,
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    """Expose pca_mca_fanout.fit_pca_mca (already SVD) as an NCA CALL."""

    try:
        from jevops import hooks

        lra_pca = hooks.try_import("pca_mca_fanout")
        lra_splice = hooks.try_import("splice")
        if lra_pca is None or lra_splice is None:
            raise RuntimeError("pca_impl_unavailable")
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "writes_lean": False, "kind": "port_pca"}
    try:
        _raw, _digest, records = lra_splice.load_warmup_records()
        rows = [lra_pca.feature_row(item) for item in records]
        model = lra_pca.fit_pca_mca(rows)
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "writes_lean": False, "kind": "port_pca"}
    stored = {
        "n_rows": model.get("n_rows"),
        "n_features": model.get("n_features"),
        "feature_names": list(model.get("feature_names") or []),
        "mean": list(model.get("mean") or []),
        "std": list(model.get("std") or []),
        "singular_values": list(model.get("singular_values") or []),
        "explained_ratio": list(model.get("explained_ratio") or []),
        "principal": list(model.get("principal") or []),
        "minor": list(model.get("minor") or []),
    }
    memory.setdefault("nca", {})["pca"] = stored
    families: list[dict[str, Any]] = []
    if tactics:
        try:
            counts = lra_pca.count_tactics(tactics)
            families = lra_pca.amenable_families(counts, stored)
        except Exception:
            families = []
    try:
        from jevops.nca import upsert_from_event
        from jevops.outer import head_seq

        for fam in head_seq(families, 6):
            name = str(fam.get("family") or "")
            if name:
                upsert_from_event(
                    memory,
                    ptr=f"ptr://family/{name}",
                    kind="family",
                    energy=min(0.9, 0.4 + 0.1 * float(fam.get("score") or 0.0)),
                )
    except Exception:
        pass
    return {
        "ok": True,
        "kind": "port_pca",
        "n_rows": stored.get("n_rows"),
        "families": [str(item.get("family")) for item in families],
        "problem": problem,
        "writes_lean": False,
        "duplicate_of": "pca_mca_fanout.fit_pca_mca",
    }


def thompson_rank(
    memory: dict[str, Any],
    *,
    rng: Optional[random.Random] = None,
    name: str = "",
) -> dict[str, Any]:
    """Sample Beta(α,β) per stem so high-variance skills still get a try."""

    rng = rng or random.Random(0)
    if not _bayes_store(memory):
        sync_bayes_from_memory(memory)
    stems = _pipeline_stems(memory, name=name) or list(_bayes_store(memory))
    if not stems:
        return {"ok": True, "reason": "no_stems", "ranked": [], "writes_lean": False, "kind": "port_thompson"}
    scored: list[tuple[float, str]] = []
    draws: dict[str, float] = {}
    for stem in stems:
        post = posterior(memory, stem)
        alpha = max(1e-6, float(post["alpha"]))
        beta = max(1e-6, float(post["beta"]))
        try:
            x = rng.gammavariate(alpha, 1.0)
            y = rng.gammavariate(beta, 1.0)
            draw = x / (x + y) if (x + y) else 0.5
        except ValueError:
            draw = float(post["mean"])
        draws[stem] = draw
        scored.append((-draw, stem))
    scored.sort()
    ranked = [stem for _s, stem in scored]
    memory.setdefault("nca", {})["pipeline_bias"] = ranked
    return {
        "ok": True,
        "kind": "port_thompson",
        "ranked": ranked,
        "draws": draws,
        "writes_lean": False,
    }


def train_ridge(memory: dict[str, Any], *, lam: float = RIDGE_L2) -> dict[str, Any]:
    """Ridge P(lake-ok | feature_row). Complementary to RF on small n."""

    rows = _labeled_rows(memory)
    if len(rows) < 4:
        memory.setdefault("nca", {})["ridge"] = {}
        return {"ok": True, "reason": "too_few_rows", "n_rows": len(rows), "writes_lean": False, "kind": "port_ridge"}
    try:
        import numpy as np
    except Exception:
        return {"ok": False, "reason": "no_numpy", "writes_lean": False, "kind": "port_ridge"}
    x = np.asarray([feat for feat, _y in rows], dtype=float)
    y = np.asarray([float(lab) for _feat, lab in rows], dtype=float)
    ones = np.ones((x.shape[0], 1), dtype=float)
    design = np.concatenate([ones, x], axis=1)
    xtx = design.T @ design + float(lam) * np.eye(design.shape[1])
    try:
        weights = np.linalg.solve(xtx, design.T @ y)
    except np.linalg.LinAlgError:
        return {"ok": False, "reason": "singular", "writes_lean": False, "kind": "port_ridge"}
    memory.setdefault("nca", {})["ridge"] = {"weights": [float(w) for w in weights], "lam": float(lam), "n_rows": len(rows)}
    return {
        "ok": True,
        "kind": "port_ridge",
        "n_rows": len(rows),
        "n_weights": int(weights.shape[0]),
        "writes_lean": False,
    }


def score_ridge(memory: Mapping[str, Any], feat: Sequence[float]) -> float:
    weights = ((memory.get("nca") or {}).get("ridge") or {}).get("weights") or []
    if not weights:
        return 0.5
    total = float(weights[0])
    for index, value in enumerate(feat):
        if index + 1 >= len(weights):
            break
        total += float(weights[index + 1]) * float(value)
    return _clip01(1.0 / (1.0 + math.exp(-total)))


def rank_drafts_ridge(
    drafts: Sequence[Mapping[str, Any]],
    *,
    memory: Mapping[str, Any],
    name: str = "",
    remaining_cut: int = 0,
) -> list[Mapping[str, Any]]:
    leftover = len(drafts)
    scored: list[tuple[float, Mapping[str, Any]]] = []
    for item in drafts:
        feat = feature_row(
            kind=str(item.get("kind") or ""),
            tokens=int(item.get("token_count") or 0),
            memory=memory,
            name=name,
            leftover=leftover,
            remaining_cut=remaining_cut,
        )
        scored.append((-score_ridge(memory, feat), item))
    scored.sort(key=lambda row: (row[0], str(row[1].get("kind") or "")))
    return [item for _s, item in scored]


def call_ranker(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
    rng: Optional[random.Random] = None,
    compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    jev_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Dispatch CALL ptr://skill/port_{random_forest,...,autoencoder,vae,lean_ir,gan}."""

    rng = rng or random.Random(0)
    text = str(stem or "").lower()
    name = str(problem or "")
    try:
        from jevops import kernel as lra_kern

        if lra_kern.is_kernel_stem(stem):
            return lra_kern.call_kernel(stem, memory=memory, tactics=tactics, problem=name)
    except Exception:
        pass
    try:
        from jevops import plan as lra_plan

        if lra_plan.is_plan_stem(stem):
            return lra_plan.call_plan(stem, memory=memory, tactics=tactics, problem=name)
    except Exception:
        pass
    try:
        from jevops import turing as lra_tm

        if lra_tm.is_tm_stem(stem):
            return lra_tm.call_tm(stem, memory=memory, tactics=tactics, problem=name)
    except Exception:
        pass
    if "autoencoder" in text or "vae" in text or "lean_ir" in text:
        from jevops import autoencoder as lra_ae

        return lra_ae.call_autoencoder(
            stem,
            memory=memory,
            tactics=tactics,
            problem=name,
            jev_fn=jev_fn,
            compile_fn=compile_fn,
            rng=rng,
        )
    try:
        from jevops import temporal as lra_time

        if lra_time.is_extra_stem(stem):
            return lra_time.call_extra(stem, memory=memory, tactics=tactics, problem=name)
    except Exception:
        pass
    try:
        from jevops import tape_tools as lra_tt

        if lra_tt.is_tape_editor_stem(stem):
            return lra_tt.call_tape_tool(stem, memory=memory, tactics=tactics, problem=name)
    except Exception:
        pass
    try:
        from jevops import graph as lra_graph

        if lra_graph.is_graph_stem(stem):
            return lra_graph.call_graph(
                stem, memory=memory, tactics=tactics, problem=name, query=name
            )
    except Exception:
        pass
    try:
        from jevops import more_rankers as lra_more

        if lra_more.is_more_stem(stem):
            return lra_more.call_more(
                stem, memory=memory, tactics=tactics, problem=name, rng=rng, jev_fn=jev_fn
            )
    except Exception:
        pass
    try:
        from jevops import int_rankers as lra_int

        if lra_int.is_int_stem(stem):
            return lra_int.call_int_ranker(
                stem, memory=memory, tactics=tactics, problem=name, rng=rng
            )
    except Exception:
        pass
    if "thompson" in text:
        return thompson_rank(memory, rng=rng, name=name)
    if "ridge" in text or "logistic" in text:
        trained = train_ridge(memory)
        drafts: list[Mapping[str, Any]] = []
        try:
            from jevops import hooks

            drafts_fn = hooks.resolve("portable_drafts", "portable_rewrites", "portable_drafts")
            drafts = list(drafts_fn(tactics, memory=memory, name=name)) if drafts_fn else []
        except Exception:
            drafts = []
        ranked = rank_drafts_ridge(drafts, memory=memory, name=name)
        bias = [_stem_of(str(item.get("kind") or "")) for item in ranked if item.get("kind")]
        if bias:
            memory.setdefault("nca", {})["pipeline_bias"] = bias
        trained["ranked"] = [str(item.get("kind")) for item in ranked]
        trained["ok"] = bool(trained.get("ok"))
        trained["writes_lean"] = False
        return trained
    if "svd" in text:
        return recommend_svd(memory, problem=name)
    if text.endswith("pca") or "/pca" in text or "port_pca" in text or text == "pca":
        return call_pca(memory, tactics=tactics, problem=name)
    if "bayes" in text:
        synced = sync_bayes_from_memory(memory)
        synced["n_cells"] = apply_bayes_to_grid(memory)
        synced["kind"] = "port_bayes_time"
        synced["ok"] = True
        synced["writes_lean"] = False
        return synced
    if "skill_tree" in text or "hierarch" in text:
        from jevops import skill_tree as lra_tree

        return lra_tree.search_with_forest(memory, tactics=tactics, problem=name, rng=rng)
    if "forest" in text or "random_forest" in text:
        from jevops import skill_tree as lra_tree

        tree_hit = lra_tree.search_with_forest(memory, tactics=tactics, problem=name, rng=rng)
        trained = train_random_forest(memory, rng=rng)
        drafts = []
        try:
            from jevops import hooks

            drafts_fn = hooks.resolve("portable_drafts", "portable_rewrites", "portable_drafts")
            drafts = list(drafts_fn(tactics, memory=memory, name=name)) if drafts_fn else []
        except Exception:
            drafts = []
        ranked = rank_drafts_forest(drafts, memory=memory, name=name)
        bias = [_stem_of(str(item.get("kind") or "")) for item in ranked if item.get("kind")]
        if not bias:
            bias = list(tree_hit.get("ranked") or [])
        if bias:
            memory.setdefault("nca", {})["pipeline_bias"] = bias
        trained["kind"] = "port_random_forest"
        trained["ranked"] = [str(item.get("kind")) for item in ranked] or list(tree_hit.get("ranked") or [])
        trained["ranked_paths"] = tree_hit.get("ranked_paths")
        trained["n_leaves"] = tree_hit.get("n_leaves")
        trained["ok"] = True
        trained["writes_lean"] = False
        return trained
    if "mcmc" in text:
        return mcmc_pipeline_order(memory, name=name, rng=rng)
    return {"ok": False, "reason": "unknown_ranker", "stem": stem, "writes_lean": False}


def score_record(
    drafts: Sequence[Mapping[str, Any]],
    *,
    memory: Mapping[str, Any],
    name: str = "",
    remaining_cut: int = 0,
) -> float:
    """Mean RF score of leftover drafts (live-rank tertiary key)."""

    if not drafts:
        return 0.0
    if not (((memory.get("nca") or {}).get("random_forest") or {}).get("trees")):
        return 0.0
    ranked = rank_drafts_forest(drafts, memory=memory, name=name, remaining_cut=remaining_cut)
    if not ranked:
        return 0.0
    feat = feature_row(
        kind=str(ranked[0].get("kind") or ""),
        tokens=int(ranked[0].get("token_count") or 0),
        memory=memory,
        name=name,
        leftover=len(drafts),
        remaining_cut=remaining_cut,
    )
    return float(score_forest(memory, feat))
