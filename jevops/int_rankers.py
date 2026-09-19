#!/usr/bin/env python3
"""Integer milles NCA rankers. No float64 in the hot path.

Scores are milles (0..1000). SVD/PCA/OLS/ridge/logistic/k-means/kNN/ICA/NMF/
Kalman/Bayes/MCMC use integer matmul, isqrt, and integer division. Lake is
still the oracle. Jev does not write Lean. Never docker0. Not Arena scores.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import math
import random
from typing import Any, Mapping, Optional, Sequence

MILLE = 1000
INT_STEMS = (
    "svd",
    "pca",
    "ridge",
    "bayes",
    "mcmc",
    "kmeans",
    "knn",
    "logistic",
    "ols",
    "ica",
    "nmf",
    "kalman",
)


def is_int_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    if "forest" in text or "thompson" in text:
        return False
    return any(tag in text for tag in INT_STEMS)


def _clip(value: int, lo: int = 0, hi: int = MILLE) -> int:
    return max(lo, min(hi, int(value)))


def _stem_of(kind: str) -> str:
    text = str(kind or "")
    if text.startswith("port_"):
        text = text[len("port_") :]
    return text.split("_pipeline")[0]


def _isqrt(n: int) -> int:
    return int(math.isqrt(max(0, int(n))))


def _dot(a: Sequence[int], b: Sequence[int]) -> int:
    return sum(int(x) * int(y) for x, y in zip(a, b))


def _norm2(v: Sequence[int]) -> int:
    return sum(int(x) * int(x) for x in v)


def _scale_milles(v: Sequence[int]) -> list[int]:
    n2 = _norm2(v)
    s = _isqrt(n2)
    if s <= 0:
        return [0] * len(v)
    return [int(x) * MILLE // s for x in v]


def _transpose(mat: Sequence[Sequence[int]]) -> list[list[int]]:
    if not mat:
        return []
    return [list(col) for col in zip(*mat)]


def _matvec(mat: Sequence[Sequence[int]], vec: Sequence[int]) -> list[int]:
    return [_dot(row, vec) for row in mat]


def _outer_sub(mat: list[list[int]], u: Sequence[int], s: int, v: Sequence[int]) -> list[list[int]]:
    """mat -= (s * u v^T) / MILLE^2 with u,v in milles."""

    den = MILLE * MILLE
    out = [row[:] for row in mat]
    for i, ui in enumerate(u):
        for j, vj in enumerate(v):
            out[i][j] -= (int(s) * int(ui) * int(vj)) // den
    return out


def power_svd(mat: Sequence[Sequence[int]], *, k: int = 2, iters: int = 16, rng: Optional[random.Random] = None) -> dict[str, Any]:
    """Integer power-iteration SVD. Returns milles U/V and integer singulars."""

    rng = rng or random.Random(0)
    if not mat or not mat[0]:
        return {"ok": False, "reason": "empty", "U": [], "S": [], "Vt": []}
    work = [list(map(int, row)) for row in mat]
    m, n = len(work), len(work[0])
    k = max(1, min(int(k), m, n))
    u_cols: list[list[int]] = []
    s_vals: list[int] = []
    v_rows: list[list[int]] = []
    at = _transpose(work)
    for _ in range(k):
        v = _scale_milles([rng.randrange(1, 11) for _ in range(n)])
        for _it in range(iters):
            u = _matvec(work, v)
            v = _scale_milles(_matvec(at, u) if at else v)
            v = _scale_milles(v)
        u = _matvec(work, v)
        s = _isqrt(_norm2(u))
        u = _scale_milles(u)
        u_cols.append(u)
        s_vals.append(int(s))
        v_rows.append(v)
        work = _outer_sub(work, u, s, v)
        at = _transpose(work)
    return {"ok": True, "U": u_cols, "S": s_vals, "Vt": v_rows, "m": m, "n": n, "k": k}


def _solve(a: list[list[int]], b: list[int]) -> list[int]:
    """Integer Gaussian elimination. Returns milles weights."""

    n = len(b)
    if n == 0:
        return []
    m = [a[i][:] + [int(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(m[row][col]))
        m[col], m[pivot] = m[pivot], m[col]
        pv = m[col][col]
        if pv == 0:
            continue
        for row in range(n):
            if row == col:
                continue
            fac = m[row][col]
            for j in range(col, n + 1):
                m[row][j] = m[row][j] * pv - m[col][j] * fac
    out = [0] * n
    for i in range(n):
        diag = m[i][i]
        out[i] = 0 if diag == 0 else (m[i][n] * MILLE) // diag
    return out


def sigmoid_milles(z: int) -> int:
    """Piecewise integer logistic: 500 + z/4, clipped."""

    if z <= -4000:
        return 0
    if z >= 4000:
        return MILLE
    return _clip(500 + z // 4)


def feature_milles(
    *,
    kind: str = "",
    tokens: int = 0,
    memory: Optional[Mapping[str, Any]] = None,
    name: str = "",
    leftover: int = 0,
    remaining_cut: int = 0,
) -> list[int]:
    from jevops import rankers as lra_rank

    stem = _stem_of(kind)
    post = lra_rank.posterior(dict(memory or {}), stem)
    alpha = int(post.get("alpha") or 1)
    beta = int(post.get("beta") or 1)
    bayes_m = (alpha * MILLE) // max(1, alpha + beta)
    feat = lra_rank.feature_row(
        kind=kind,
        tokens=tokens,
        memory=memory,
        name=name,
        leftover=leftover,
        remaining_cut=remaining_cut,
    )
    return [
        int(tokens),
        int(feat[1]),
        int(feat[2]),
        int(feat[3] * MILLE) if abs(feat[3]) <= 2 else int(feat[3]),
        int(feat[4] * MILLE) if abs(feat[4]) <= 2 else int(feat[4]),
        int(remaining_cut),
        int(leftover),
        bayes_m,
    ]


def labeled_milles(memory: Mapping[str, Any]) -> list[tuple[list[int], int]]:
    rows: list[tuple[list[int], int]] = []
    for lab, bucket in ((MILLE, memory.get("successes") or []), (0, memory.get("failures") or [])):
        for item in bucket:
            kind = str(item.get("kind") or "")
            if not kind:
                continue
            rows.append(
                (
                    feature_milles(
                        kind=kind,
                        tokens=int(item.get("tokens") or item.get("token_count") or 0),
                        memory=memory,
                        name=str(item.get("name") or ""),
                    ),
                    lab,
                )
            )
    return rows


def lake_int_matrix(memory: Mapping[str, Any]) -> tuple[list[str], list[str], list[list[int]]]:
    cells: dict[tuple[str, str], int] = {}
    for sign, bucket in ((1, memory.get("successes") or []), (-1, memory.get("failures") or [])):
        for item in bucket:
            thm = str(item.get("name") or "")
            stem = _stem_of(str(item.get("kind") or ""))
            if not thm or not stem:
                continue
            cells[(thm, stem)] = cells.get((thm, stem), 0) + int(sign)
    theorems = sorted({key[0] for key in cells})
    skills = sorted({key[1] for key in cells})
    matrix = [[cells.get((thm, stem), 0) for stem in skills] for thm in theorems]
    return theorems, skills, matrix


def _bias_from_scores(memory: dict[str, Any], ranked: list[str]) -> dict[str, Any]:
    if ranked:
        memory.setdefault("nca", {})["pipeline_bias"] = ranked
    return {"ok": True, "ranked": ranked, "writes_lean": False, "integer": True}


def call_svd(memory: dict[str, Any], *, problem: str = "", rng: Optional[random.Random] = None) -> dict[str, Any]:
    theorems, skills, matrix = lake_int_matrix(memory)
    if len(theorems) < 2 or len(skills) < 2:
        return {"ok": True, "reason": "too_small", "kind": "port_svd", "ranked": [], "writes_lean": False, "integer": True}
    svd = power_svd(matrix, k=min(3, len(theorems), len(skills)), rng=rng)
    scores = {stem: 0 for stem in skills}
    if problem in theorems:
        i = theorems.index(problem)
        u_row = [col[i] for col in svd["U"]]
    else:
        u_row = [sum(col) // max(1, len(col)) for col in svd["U"]]
    for j, stem in enumerate(skills):
        acc = 0
        for c, s_val, v in zip(u_row, svd["S"], svd["Vt"]):
            acc += int(c) * int(s_val) * int(v[j])
        scores[stem] = acc
    ranked = sorted(scores, key=lambda stem: (-scores[stem], stem))
    memory.setdefault("nca", {})["svd"] = {"theorems": theorems, "skills": skills, "S": svd["S"], "integer": True}
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_svd"
    out["k"] = svd.get("k")
    out["S"] = svd.get("S")
    return out


def call_pca(memory: dict[str, Any], *, tactics: str = "", rng: Optional[random.Random] = None) -> dict[str, Any]:
    try:
        from jevops import hooks

        lra_pca = hooks.try_import("pca_mca_fanout")
        lra_splice = hooks.try_import("splice")
        if lra_pca is None or lra_splice is None:
            raise RuntimeError("pca_impl_unavailable")
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "kind": "port_pca", "writes_lean": False, "integer": True}
    _raw, _digest, records = lra_splice.load_warmup_records()
    names = list(lra_pca.FEATURE_NAMES)
    from jevops import hooks as _h

    lra_fan = _h.try_import("draft_fanout")
    if lra_fan is None:
        return {"ok": False, "reason": "no_draft_fanout", "kind": "port_pca", "writes_lean": False, "integer": True}

    mat = []
    for rec in records:
        counts = lra_pca.count_tactics(lra_fan.tactic_block(rec))
        mat.append([int(counts.get(name, 0)) for name in names])
    if len(mat) < 2:
        return {"ok": True, "reason": "too_small", "kind": "port_pca", "writes_lean": False, "integer": True}
    svd = power_svd(mat, k=min(3, len(mat[0]), len(mat)), rng=rng)
    memory.setdefault("nca", {})["pca"] = {"S": svd["S"], "feature_names": names, "integer": True, "k": svd.get("k")}
    families: list[str] = []
    if tactics:
        try:
            counts = lra_pca.count_tactics(tactics)
            families = [fam for fam, feats in lra_pca.FAMILY_FEATURES.items() if any(int(counts.get(f, 0)) > 0 for f in feats)]
        except Exception:
            families = []
    try:
        from jevops.nca import upsert_from_event

        for fam in families[:6]:
            upsert_from_event(memory, ptr=f"ptr://family/{fam}", kind="family", energy=0.55)
    except Exception:
        pass
    return {
        "ok": True,
        "kind": "port_pca",
        "families": families,
        "S": svd["S"],
        "integer": True,
        "writes_lean": False,
        "duplicate_of": "pca_mca_fanout counts + integer SVD",
    }


def _design(rows: Sequence[tuple[list[int], int]]) -> tuple[list[list[int]], list[int]]:
    x = [[1] + list(feat) for feat, _y in rows]
    y = [int(lab) for _feat, lab in rows]
    return x, y


def _xtx_xty(x: Sequence[Sequence[int]], y: Sequence[int], *, ridge: int = 0) -> tuple[list[list[int]], list[int]]:
    p = len(x[0])
    xtx = [[sum(int(x[r][i]) * int(x[r][j]) for r in range(len(x))) for j in range(p)] for i in range(p)]
    if ridge:
        for i in range(p):
            xtx[i][i] += int(ridge)
    xty = [sum(int(x[r][i]) * int(y[r]) for r in range(len(x))) for i in range(p)]
    return xtx, xty


def call_ols(memory: dict[str, Any], *, ridge: int = 0, kind: str = "port_ols") -> dict[str, Any]:
    rows = labeled_milles(memory)
    if len(rows) < 4:
        return {"ok": True, "reason": "too_few_rows", "n_rows": len(rows), "kind": kind, "writes_lean": False, "integer": True}
    x, y = _design(rows)
    xtx, xty = _xtx_xty(x, y, ridge=ridge)
    weights = _solve(xtx, xty)
    memory.setdefault("nca", {})[kind.replace("port_", "")] = {"weights": weights, "integer": True, "n_rows": len(rows)}
    return {"ok": True, "kind": kind, "n_rows": len(rows), "n_weights": len(weights), "writes_lean": False, "integer": True}


def score_linear(memory: Mapping[str, Any], feat: Sequence[int], *, store: str) -> int:
    weights = ((memory.get("nca") or {}).get(store) or {}).get("weights") or []
    if not weights:
        return 500
    z = int(weights[0])
    for i, value in enumerate(feat):
        if i + 1 >= len(weights):
            break
        z += int(weights[i + 1]) * int(value)
    return sigmoid_milles(z // max(1, MILLE))


def _rank_linear(memory: dict[str, Any], tactics: str, problem: str, *, store: str, kind: str) -> dict[str, Any]:
    trained = call_ols(memory, ridge=(MILLE if store == "ridge" else 0), kind=kind if store != "logistic" else "port_ols")
    if store == "ridge":
        memory.setdefault("nca", {})["ridge"] = memory.get("nca", {}).get("ols") or memory.get("nca", {}).get("ridge")
        if "ols" in (memory.get("nca") or {}) and store == "ridge":
            memory["nca"]["ridge"] = {
                "weights": list((memory["nca"].get("ridge") or {}).get("weights") or (memory["nca"].get("ols") or {}).get("weights") or []),
                "integer": True,
            }
    drafts: list[Mapping[str, Any]] = []
    try:
        from jevops import hooks

        drafts_fn = hooks.resolve("portable_drafts", "portable_rewrites", "portable_drafts")
        drafts = list(drafts_fn(tactics, memory=memory, name=problem)) if drafts_fn else []
    except Exception:
        drafts = []
    scored: list[tuple[int, str]] = []
    leftover = len(drafts)
    for item in drafts:
        feat = feature_milles(
            kind=str(item.get("kind") or ""),
            tokens=int(item.get("token_count") or 0),
            memory=memory,
            name=problem,
            leftover=leftover,
        )
        scored.append((-score_linear(memory, feat, store=store if store != "logistic" else "ols"), str(item.get("kind") or "")))
    scored.sort()
    ranked = [_stem_of(kind) for _s, kind in scored if kind]
    out = _bias_from_scores(memory, ranked)
    out.update(trained)
    out["kind"] = kind
    out["ranked"] = ranked
    return out


def call_logistic(memory: dict[str, Any], *, tactics: str = "", problem: str = "") -> dict[str, Any]:
    """One integer IRLS step: OLS then sigmoid milles."""

    trained = _rank_linear(memory, tactics, problem, store="ols", kind="port_logistic")
    trained["kind"] = "port_logistic"
    return trained


def call_kmeans(memory: dict[str, Any], *, k: int = 2, rng: Optional[random.Random] = None) -> dict[str, Any]:
    rng = rng or random.Random(0)
    rows = labeled_milles(memory)
    if len(rows) < k:
        return {"ok": True, "reason": "too_few_rows", "kind": "port_kmeans", "writes_lean": False, "integer": True}
    points = [feat for feat, _y in rows]
    cents = [list(points[rng.randrange(len(points))]) for _ in range(k)]
    assign = [0] * len(points)
    for _ in range(8):
        for i, p in enumerate(points):
            d = [sum((a - b) * (a - b) for a, b in zip(p, c)) for c in cents]
            assign[i] = min(range(k), key=lambda j: d[j])
        for j in range(k):
            members = [p for p, a in zip(points, assign) if a == j]
            if not members:
                continue
            dim = len(members[0])
            cents[j] = [sum(p[d] for p in members) // len(members) for d in range(dim)]
    cluster_rate = []
    for j in range(k):
        labs = [lab for lab, a in zip((y for _f, y in rows), assign) if a == j]
        cluster_rate.append(sum(labs) // max(1, len(labs)))
    items: list[Mapping[str, Any]] = []
    for bucket in (memory.get("successes") or [], memory.get("failures") or []):
        for item in bucket:
            if item.get("kind"):
                items.append(item)
    stem_score: dict[str, list[int]] = {}
    for item, a in zip(items, assign):
        stem = _stem_of(str(item.get("kind") or ""))
        if not stem:
            continue
        rate = cluster_rate[a] if 0 <= a < len(cluster_rate) else 0
        stem_score.setdefault(stem, []).append(rate)
    ranked = sorted(
        stem_score, key=lambda s: (-(sum(stem_score[s]) // max(1, len(stem_score[s]))), s)
    )
    memory.setdefault("nca", {})["kmeans"] = {"k": k, "integer": True, "centroids": cents}
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_kmeans"
    out["k"] = k
    return out


def call_knn(memory: dict[str, Any], *, k: int = 3, tactics: str = "", problem: str = "") -> dict[str, Any]:
    rows = labeled_milles(memory)
    if not rows:
        return {"ok": True, "reason": "too_few_rows", "kind": "port_knn", "writes_lean": False, "integer": True}
    drafts: list[Mapping[str, Any]] = []
    try:
        from jevops import hooks

        drafts_fn = hooks.resolve("portable_drafts", "portable_rewrites", "portable_drafts")
        drafts = list(drafts_fn(tactics, memory=memory, name=problem)) if drafts_fn else []
    except Exception:
        drafts = []
    leftover = len(drafts)
    scored: list[tuple[int, str]] = []
    kk = max(1, min(int(k), len(rows)))
    for item in drafts or [{"kind": it.get("kind"), "token_count": it.get("tokens")} for it in (memory.get("successes") or [])[:8]]:
        q = feature_milles(
            kind=str(item.get("kind") or ""),
            tokens=int(item.get("token_count") or item.get("tokens") or 0),
            memory=memory,
            name=problem,
            leftover=leftover,
        )
        dist = [(_dot([a - b for a, b in zip(q, feat)], [a - b for a, b in zip(q, feat)]), lab) for feat, lab in rows]
        dist.sort()
        top = dist[:kk]
        score = sum(lab for _d, lab in top) // max(1, len(top))
        scored.append((-score, _stem_of(str(item.get("kind") or ""))))
    scored.sort()
    ranked = [stem for _s, stem in scored if stem]
    memory.setdefault("nca", {})["knn"] = {"k": kk, "integer": True}
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_knn"
    return out


def call_ica(memory: dict[str, Any], *, rng: Optional[random.Random] = None) -> dict[str, Any]:
    """Integer FastICA-style deflation on the theorem×skill matrix."""

    rng = rng or random.Random(0)
    theorems, skills, matrix = lake_int_matrix(memory)
    if len(theorems) < 2 or len(skills) < 2:
        return {"ok": True, "reason": "too_small", "kind": "port_ica", "writes_lean": False, "integer": True}
    svd = power_svd(matrix, k=min(2, len(skills), len(theorems)), rng=rng)
    w = _scale_milles(svd["Vt"][0] if svd["Vt"] else [rng.randrange(1, 11) for _ in skills])
    at = _transpose(matrix)
    for _ in range(8):
        xw = _matvec(matrix, w)
        g = [500 + x // 4 if -4000 < x < 4000 else (MILLE if x >= 0 else 0) for x in xw]
        w = _scale_milles(_matvec(at, g) if at else w)
    scores = {stem: int(w[j]) if j < len(w) else 0 for j, stem in enumerate(skills)}
    ranked = sorted(scores, key=lambda s: (-abs(scores[s]), s))
    memory.setdefault("nca", {})["ica"] = {"integer": True, "w": w}
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_ica"
    return out


def call_nmf(memory: dict[str, Any], *, rank: int = 2) -> dict[str, Any]:
    theorems, skills, matrix = lake_int_matrix(memory)
    v = [[max(0, x) * MILLE for x in row] for row in matrix]
    if len(v) < 2 or not v[0]:
        return {"ok": True, "reason": "too_small", "kind": "port_nmf", "writes_lean": False, "integer": True}
    k = max(1, min(int(rank), len(v), len(v[0])))
    w = [[MILLE // k for _ in range(k)] for _ in v]
    h = [[MILLE // k for _ in v[0]] for _ in range(k)]
    for _ in range(8):
        wt = _transpose(w)
        wtv = [[_dot(wt[c], col) for col in _transpose(v)] for c in range(k)] if wt else []
        wtw = [[_dot(wt[c], wt[d]) for d in range(k)] for c in range(k)] if wt else []
        wtw_h = [_matvec(wtw, h_row) if wtw else list(h_row) for h_row in h] if wtw else h
        for c in range(k):
            for j in range(len(v[0])):
                den = max(1, wtw_h[c][j] if c < len(wtw_h) and j < len(wtw_h[c]) else 1)
                num = wtv[c][j] if c < len(wtv) and j < len(wtv[c]) else 0
                h[c][j] = max(1, h[c][j] * max(0, num) // den)
        ht = _transpose(h)
        vht = [[_dot(v[i], ht_col) for ht_col in ht] for i in range(len(v))] if ht else []
        hht = [[_dot(h[c], h[d]) for d in range(k)] for c in range(k)]
        w_hht = [_matvec(hht, w_row) for w_row in w]
        for i in range(len(v)):
            for c in range(k):
                den = max(1, w_hht[i][c] if c < len(w_hht[i]) else 1)
                num = vht[i][c] if c < len(vht[i]) else 0
                w[i][c] = max(1, w[i][c] * max(0, num) // den)
    skill_score = [sum(h[c][j] for c in range(k)) for j in range(len(skills))]
    ranked = [stem for _s, stem in sorted(((-skill_score[j], skills[j]) for j in range(len(skills))))]
    memory.setdefault("nca", {})["nmf"] = {"integer": True, "k": k}
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_nmf"
    return out


def kalman_observe(memory: dict[str, Any], stem: str, *, ok: bool) -> dict[str, int]:
    store = memory.setdefault("nca", {}).setdefault("kalman", {})
    key = _stem_of(stem)
    row = dict(store.get(key) or {})
    row.setdefault("x", 500)
    row.setdefault("P", 250)
    row.setdefault("Q", 10)
    row.setdefault("R", 80)
    z = MILLE if ok else 0
    p = int(row["P"]) + int(row["Q"])
    k_gain = (p * MILLE) // max(1, p + int(row["R"]))
    x = int(row["x"]) + k_gain * (z - int(row["x"])) // MILLE
    p = ((MILLE - k_gain) * p) // MILLE
    row["x"] = _clip(x)
    row["P"] = max(1, int(p))
    store[key] = row
    return {"x": row["x"], "P": row["P"], "K": k_gain}


def call_kalman(memory: dict[str, Any]) -> dict[str, Any]:
    store = memory.setdefault("nca", {}).setdefault("kalman", {})
    for item in memory.get("failures") or []:
        kalman_observe(memory, str(item.get("kind") or ""), ok=False)
    for item in memory.get("successes") or []:
        kalman_observe(memory, str(item.get("kind") or ""), ok=True)
    ranked = sorted(store, key=lambda s: (-int((store[s] or {}).get("x") or 0), s))
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_kalman"
    out["n"] = len(store)
    return out


def call_bayes_int(memory: dict[str, Any]) -> dict[str, Any]:
    from jevops import rankers as lra_rank

    synced = lra_rank.sync_bayes_from_memory(memory)
    milles: dict[str, int] = {}
    for stem in ((memory.get("nca") or {}).get("bayes") or {}):
        row = memory["nca"]["bayes"][stem]
        alpha = int(row.get("alpha") or 1)
        beta = int(row.get("beta") or 1)
        milles[stem] = (alpha * MILLE) // max(1, alpha + beta)
    ranked = sorted(milles, key=lambda s: (-milles[s], s))
    lra_rank.apply_bayes_to_grid(memory)
    out = _bias_from_scores(memory, ranked)
    out["kind"] = "port_bayes_time"
    out["n"] = synced.get("n")
    out["milles"] = milles
    return out


def call_mcmc_int(memory: dict[str, Any], *, rng: Optional[random.Random] = None, name: str = "") -> dict[str, Any]:
    rng = rng or random.Random(0)
    from jevops import rankers as lra_rank

    stems = lra_rank._pipeline_stems(memory, name=name)
    if len(stems) < 2:
        return {"ok": True, "reason": "too_short", "kind": "port_mcmc", "writes_lean": False, "integer": True}
    bayes = (memory.get("nca") or {}).get("bayes") or {}

    def energy(order: Sequence[str]) -> int:
        total = 0
        for i, stem in enumerate(order):
            row = bayes.get(stem) or {}
            alpha = int(row.get("alpha") or 1)
            beta = int(row.get("beta") or 1)
            mean_m = (alpha * MILLE) // max(1, alpha + beta)
            total += (MILLE - mean_m) + i
        return total

    cur = list(stems)
    cur_e = energy(cur)
    best, best_e = list(cur), cur_e
    n_acc = 0
    for _ in range(8):
        nxt = list(cur)
        i, j = rng.randrange(len(nxt)), rng.randrange(len(nxt))
        nxt[i], nxt[j] = nxt[j], nxt[i]
        nxt_e = energy(nxt)
        delta = nxt_e - cur_e
        if delta <= 0 or rng.randrange(MILLE) < (MILLE // (1 + max(0, delta))):
            cur, cur_e = nxt, nxt_e
            n_acc += 1
            if nxt_e < best_e:
                best, best_e = list(nxt), nxt_e
    memory.setdefault("nca", {})["pipeline_bias"] = best
    return {
        "ok": True,
        "kind": "port_mcmc",
        "stems": best,
        "n_accept": n_acc,
        "best_energy": best_e,
        "writes_lean": False,
        "integer": True,
    }


def call_int_ranker(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    rng = rng or random.Random(0)
    text = str(stem or "").lower()
    if "kalman" in text:
        return call_kalman(memory)
    if "kmeans" in text or "k-means" in text:
        return call_kmeans(memory, rng=rng)
    if "knn" in text:
        return call_knn(memory, tactics=tactics, problem=problem)
    if "logistic" in text:
        return call_logistic(memory, tactics=tactics, problem=problem)
    if "ols" in text:
        return _rank_linear(memory, tactics, problem, store="ols", kind="port_ols")
    if "ica" in text:
        return call_ica(memory, rng=rng)
    if "nmf" in text:
        return call_nmf(memory)
    if "ridge" in text:
        out = _rank_linear(memory, tactics, problem, store="ridge", kind="port_ridge")
        # call_ols with ridge writes port_ols store; copy weights
        ols = ((memory.get("nca") or {}).get("ols") or {})
        if ols.get("weights"):
            memory.setdefault("nca", {})["ridge"] = {"weights": list(ols["weights"]), "integer": True}
        return out
    if "svd" in text:
        return call_svd(memory, problem=problem, rng=rng)
    if "pca" in text:
        return call_pca(memory, tactics=tactics, rng=rng)
    if "bayes" in text:
        return call_bayes_int(memory)
    if "mcmc" in text:
        return call_mcmc_int(memory, rng=rng, name=problem)
    return {"ok": False, "reason": "unknown_int_ranker", "stem": stem, "writes_lean": False, "integer": True}
