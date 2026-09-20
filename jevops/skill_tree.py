#!/usr/bin/env python3
"""Hierarchical skill tree searched by the existing random forest.

Families → skills → CALL stems. TypeSafe already nests family→skill
(portable_rewrites.decision_tree). This catalog adds ranker/graph/VAE
branches and lets port_random_forest score the whole tree.

Jev does not write Lean. Lake is the oracle. Never docker0.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

from typing import Any, Mapping, Optional

# Root → family → child stems (port_ prefix omitted).
SKILL_TREE: dict[str, dict[str, tuple[str, ...]]] = {
    "keep_structure": {
        "folds": (
            "trailing_tuple_comma",
            "redundant_inner_simp",
            "hoist_repeated_simp",
            "exact_hyp",
            "use_exact",
        ),
    },
    "search_space": {
        "portable": ("pipeline",),
    },
    "rankers": {
        "forest": ("random_forest", "adaboost"),
        "linear": ("ridge", "ols", "logistic"),
        "bayes": ("bayes_time", "thompson", "kalman"),
        "matrix": ("svd", "pca", "ica", "nmf"),
        "mcmc": ("mcmc",),
        "cluster": ("kmeans", "knn"),
    },
    "sequence": {
        "markov": ("markov", "hmm", "crf"),
        "calibrate": ("isotonic", "platt", "quantile"),
        "time": ("hawkes", "delayed_bandit"),
        "tape": ("tape_conv", "tape_fft"),
        "budget": ("submodular",),
    },
    "graph": {
        "walk": ("graph_traverse", "pagerank"),
        "rag": ("graphrag",),
        "neural": ("neural_graph",),
    },
    "autoencoder": {
        "vae": ("autoencoder", "vae", "contrastive"),
    },
    "wraps": {
        "mca": ("sgd", "mask", "diffuse"),
    },
    "plan": {
        "board": ("nca_plan", "got"),
        "kernel": ("cache_put", "cache_get", "cache_lru", "cache_arc", "negative_ttl", "singleflight", "context_budget"),
    },
    "turing": {
        "tape": ("tm_read", "tm_write", "tm_left", "tm_right", "tm_step", "tm_run"),
        "stack": ("tm_push", "tm_pop"),
        "dt": ("decision_transformer", "dt_context"),
        "edit": (
            "tape_splice",
            "tape_mask",
            "tape_pop",
            "tape_peek",
            "tape_crop",
            "tape_keep",
            "tape_drop",
            "tape_mark",
            "tape_restore",
            "tape_attn",
        ),
    },
}


def skill_tree(*, extra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Nested catalog. Optional extra families from decision_tree(tactics)."""

    tree: dict[str, Any] = {fam: dict(kids) for fam, kids in SKILL_TREE.items()}
    for fam, kids in dict(extra or {}).items():
        branch = tree.setdefault(str(fam), {})
        if isinstance(kids, dict):
            for k, v in kids.items():
                branch[str(k)] = tuple(v) if not isinstance(v, str) else (v,)
        elif isinstance(kids, (list, tuple)):
            branch["live"] = tuple(str(x).replace("port_", "") for x in kids)
    return tree


def flatten_tree(tree: Optional[Mapping[str, Any]] = None) -> list[dict[str, str]]:
    """Leaves with hierarchical path family/group/stem."""

    src = tree if tree is not None else skill_tree()
    rows: list[dict[str, str]] = []
    for fam, groups in src.items():
        if not isinstance(groups, dict):
            continue
        for group, stems in groups.items():
            for stem in stems or ():
                name = str(stem).replace("port_", "")
                rows.append(
                    {
                        "family": str(fam),
                        "group": str(group),
                        "stem": name,
                        "path": f"{fam}/{group}/{name}",
                        "ptr": f"ptr://skill/port_{name}",
                    }
                )
    return rows


def to_jsonld(tree: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    from jevops import jsonld as lra_ld

    rows = flatten_tree(tree)
    graph: list[dict[str, Any]] = [
        {"@id": "ptr://family/skill_tree", "@type": "Node", "kind": "family", "identifier": "skill_tree"}
    ]
    edges: list[list[str]] = []
    seen_fam: set[str] = set()
    seen_grp: set[str] = set()
    for row in rows:
        fam_id = f"ptr://family/{row['family']}"
        grp_id = f"ptr://family/{row['family']}.{row['group']}"
        leaf = row["ptr"]
        if row["family"] not in seen_fam:
            seen_fam.add(row["family"])
            graph.append({"@id": fam_id, "@type": "Node", "kind": "family", "identifier": row["family"]})
            edges.append(["ptr://family/skill_tree", fam_id])
        if grp_id not in seen_grp:
            seen_grp.add(grp_id)
            graph.append({"@id": grp_id, "@type": "Node", "kind": "family", "identifier": row["group"]})
            edges.append([fam_id, grp_id])
        graph.append({"@id": leaf, "@type": "Node", "kind": "skill", "identifier": row["stem"]})
        edges.append([grp_id, leaf])
    doc = lra_ld.document_from_edges(edges)
    # Keep explicit nodes
    ids = {n.get("@id") for n in graph}
    extra = [n for n in doc.get("@graph") or [] if n.get("@id") not in ids]
    doc["@graph"] = graph + extra
    return doc


def search_with_forest(
    memory: dict[str, Any],
    *,
    tactics: str = "",
    problem: str = "",
    rng: Optional[Any] = None,
) -> dict[str, Any]:
    """Train/score the random forest over hierarchical skill leaves."""

    from jevops import hooks
    from jevops import rankers as lra_rank

    tree_fn = hooks.get("decision_tree") or hooks.try_import("portable_rewrites", "decision_tree")
    live = tree_fn(tactics, memory=memory, name=problem) if tactics and tree_fn else {}
    tree = skill_tree(extra=live)
    leaves = flatten_tree(tree)
    trained = lra_rank.train_random_forest(memory, rng=rng)
    leftover = len(leaves)
    scored: list[tuple[float, dict[str, str]]] = []
    for leaf in leaves:
        feat = lra_rank.feature_row(
            kind=f"port_{leaf['stem']}",
            tokens=0,
            memory=memory,
            name=problem,
            leftover=leftover,
        )
        scored.append((-float(lra_rank.score_forest(memory, feat)), leaf))
    scored.sort(key=lambda row: (row[0], row[1].get("path") or ""))
    ranked = [leaf for _s, leaf in scored]
    paths = [leaf["path"] for leaf in ranked]
    bias = [leaf["stem"] for leaf in ranked]
    from jevops.outer import head_seq

    memory.setdefault("nca", {})["skill_tree"] = {
        "n_leaves": len(leaves),
        "ranked_paths": head_seq(paths, 24),
        "n_trees": trained.get("n_trees"),
    }
    if bias:
        memory["nca"]["pipeline_bias"] = head_seq(bias, 16)
    try:
        doc = to_jsonld(tree)
        from jevops import jsonld as lra_ld

        lra_ld.put_jsonld(memory, doc)
    except Exception:
        pass
    return {
        "ok": True,
        "kind": "port_skill_tree",
        "n_leaves": len(leaves),
        "n_trees": trained.get("n_trees") or 0,
        "ranked_paths": head_seq(paths, 24),
        "ranked": head_seq(bias, 16),
        "families": sorted(tree),
        "writes_lean": False,
        "called_docker0": False,
    }


def call_skill_tree(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
    rng: Optional[Any] = None,
) -> dict[str, Any]:
    out = search_with_forest(memory, tactics=tactics, problem=problem, rng=rng)
    if "forest" in str(stem or "").lower():
        out["kind"] = "port_random_forest"
    return out
