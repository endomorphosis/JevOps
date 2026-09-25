"""Bounded adjacent-edit proposals; only the native fitter may admit teachers."""
from __future__ import annotations

import random
import textwrap

from .graph_curriculum import _seed, training_rows as base_training_rows
from .proof_tokens import proof_source_tokens
from .structural_training import _envelope


def _pipeline(s, function="f"):
    f, h = s[function], s["h"]
    intro = f"intro {h}\n"
    alias = (f"have {s['a']} := {h}\nhave {s['b']} := {s['a']}\n"
             f"have {s['c']} := {s['b']}\nexact {s['c']}")
    return [intro + f"apply {f}\n" + alias, intro + f"apply {f}\nexact {h}",
            intro + f"exact {f} {h}", f"exact {f}"]


def _row(seed, split, family, build):
    nonce = random.Random(f"{seed}:{split}:{family}").randrange(10**8)
    s = {k: f"{k}_{nonce}" for k in ("p", "q", "r", "h", "f", "g", "e", "hr", "x", "z", "a", "b", "c", "T")}
    name = f"composition_{split}_{family}_{nonce}"
    header, bodies = build(s)
    prefix = f"theorem {name} {header} := by\n"
    states = [prefix + textwrap.indent(body, "  ") + "\n" for body in bodies]
    return {"id": name, "split": split, "family": family, "source": states[0], "states": states}


def path_states(row):
    """Validate proposed labels, not their proof validity or global optimality."""
    states = row["states"]
    if (not isinstance(states, list) or not 2 <= len(states) <= 9
            or any(not isinstance(s, str) or len(s.encode()) > 65_536 for s in states)
            or states[0] != row["source"]):
        raise ValueError("invalid composition path")
    for a, b in zip(states, states[1:]):
        _envelope(a, b)
        if proof_source_tokens(b) >= proof_source_tokens(a):
            raise ValueError("composition labels must strictly shorten")
    return states


def training_edges(paths):
    """Keep the parent split; reject eval paths before accessing their labels.

    The returned rows are unverified proposals for fit_training, not ready-made
    proof authority. Terminal identities are not invented as optimal-stop labels.
    """
    if (not isinstance(paths, list) or not 1 <= len(paths) <= 16
            or any(not isinstance(r, dict) or r.get("split") != "train" for r in paths)):
        raise ValueError("composition supervision requires training paths only")
    edges, ids = [], set()
    for row in paths:
        if (not isinstance(row.get("id"), str) or not row["id"] or len(row["id"]) > 200 or row["id"] in ids
                or not isinstance(row.get("family"), str) or not row["family"] or len(row["family"]) > 128):
            raise ValueError("invalid composition parent identity")
        ids.add(row["id"])
        for i, (a, b) in enumerate(zip(path_states(row), row["states"][1:])):
            edges.append({"id": f"{row['id']}:step:{i}", "parent_id": row["id"], "split": "train",
                          "family": row["family"], "source": a, "target": b})
    if len(edges) > 16:
        raise ValueError("composition training edge budget")
    return edges


def training_rows(seed=20260926):
    _seed(seed)
    root = _row(seed, "train", "root_pipeline", lambda s: (
        f"({s['p']} {s['q']} : Prop) ({s['f']} : {s['p']} → {s['q']}) : {s['p']} → {s['q']}", _pipeline(s)))
    return base_training_rows(seed) + training_edges([root])


def transfer_rows(seed=20260927):
    """Generate only after freeze; name changes alone do not make fresh tasks.

    Disjoint enclosing types/layouts still share the training rewrite motifs.
    These six teacher paths are not a mathematical benchmark or optimality proof.
    """
    _seed(seed)
    specs = [
        ("validation", "and_left_pipeline", lambda s: (
            f"({s['p']} {s['q']} {s['r']} : Prop) ({s['f']} : {s['p']} → {s['q']}) ({s['hr']} : {s['r']}) : ({s['p']} → {s['q']}) ∧ {s['r']}",
            ["constructor\ncase left =>\n" + textwrap.indent(b, "  ") + f"\ncase right => exact {s['hr']}" for b in _pipeline(s)])),
        ("validation", "and_right_pipeline", lambda s: (
            f"({s['p']} {s['q']} {s['r']} : Prop) ({s['hr']} : {s['r']}) ({s['f']} : {s['p']} → {s['q']}) : {s['r']} ∧ ({s['p']} → {s['q']})",
            [f"constructor\ncase left => exact {s['hr']}\ncase right =>\n" + textwrap.indent(b, "  ") for b in _pipeline(s)])),
        ("canary", "or_left_pipeline", lambda s: (
            f"({s['p']} {s['q']} {s['r']} : Prop) ({s['f']} : {s['p']} → {s['q']}) : ({s['p']} → {s['q']}) ∨ {s['r']}",
            ["apply Or.inl\n" + b for b in _pipeline(s)])),
        ("canary", "implication_prefix_pipeline", lambda s: (
            f"({s['p']} {s['q']} {s['r']} : Prop) ({s['f']} : {s['p']} → {s['q']}) : {s['r']} → {s['p']} → {s['q']}",
            [f"intro {s['z']}\n" + b for b in _pipeline(s)])),
        ("holdout", "iff_forward_pipeline", lambda s: (
            f"({s['p']} {s['q']} : Prop) ({s['e']} : {s['p']} ↔ {s['q']}) : {s['p']} → {s['q']}",
            [f"have {s['f']} := {s['e']}.mp\n" + b for b in _pipeline(s)])),
        ("holdout", "forall_point_pipeline", lambda s: (
            f"({s['T']} : Type) ({s['p']} {s['q']} : {s['T']} → Prop) ({s['f']} : ∀ {s['x']}, {s['p']} {s['x']} → {s['q']} {s['x']}) : ∀ {s['x']}, {s['p']} {s['x']} → {s['q']} {s['x']}",
            [f"intro {s['x']}\nhave {s['g']} := {s['f']} {s['x']}\n" + b for b in _pipeline(s, "g")])),
    ]
    return [_row(seed, split, family, build) for split, family, build in specs]
