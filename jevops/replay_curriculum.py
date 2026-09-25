"""Small, explicit Lean-core transfer controls, never an arena corpus.

Held-out contexts are different proof structures, but share training rewrite
motifs. Preservation controls are not claims that the original is minimal.
"""
from __future__ import annotations

import random


def transfer_rows(seed: int = 20260922):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("invalid curriculum seed")
    rows = []

    def add(split, family, header, body, target, context):
        n = random.Random(f"{seed}:{split}:{family}").randrange(10**8)
        names = {s: f"{s}_{n}" for s in ("p", "q", "h", "hp", "x", "y", "a", "xs")}
        name = f"transfer_{split}_{family}_{n}"
        prefix = f"theorem {name} " + header.format(**names) + " := by\n"
        rows.append({"id": name, "split": split, "family": family, "context": context,
                     "source": prefix + body.format(**names), "target": prefix + target.format(**names)})

    for split in ("train", "validation", "canary"):
        add(split, "hypothesis", "({p} : Prop) ({h} : {p}) : {p}",
            "  exact id {h}\n", "  assumption\n", "root")
        add(split, "reflexivity", "({x} : Nat) : {x} = {x}",
            "  exact Eq.refl {x}\n", "  rfl\n", "root")
        add(split, "truth", ": True", "  exact True.intro\n", "  trivial\n", "root")

    add("holdout", "introduced_hypothesis", "({p} : Prop) : {p} → {p}",
        "  intro {h}\n  exact id {h}\n", "  intro {h}\n  assumption\n", "intro")
    add("holdout", "polymorphic_reflexivity", "({a} : Type) ({xs} : List {a}) : {xs} = {xs}",
        "  exact Eq.refl {xs}\n", "  rfl\n", "polymorphic_list")
    add("holdout", "local_definition", "({x} : Nat) : {x} = {x}",
        "  let {y} := {x}\n  exact Eq.refl {y}\n", "  let {y} := {x}\n  rfl\n", "let")
    add("holdout", "conjunction_branch", "({p} : Prop) ({h} : {p}) : {p} ∧ True",
        "  constructor\n  case left => exact {h}\n  case right =>\n    exact True.intro\n",
        "  constructor\n  case left => exact {h}\n  case right =>\n    trivial\n", "case")
    add("holdout", "preserve_application", "({p} {q} : Prop) ({h} : {p} → {q}) ({hp} : {p}) : {q}",
        "  exact {h} {hp}\n", "  exact {h} {hp}\n", "no_applicable_template")
    add("holdout", "preserve_parenthesized", "({x} : Nat) : {x} = {x}",
        "  exact (Eq.refl {x})\n", "  exact (Eq.refl {x})\n", "no_applicable_template")
    return rows


def compound_rows(seed: int = 20260922):
    """Separate protocol for atomic closing-span edits; shared motifs, not blind math.

    This does not change transfer_rows or reuse its failed holdout as training.
    The inspected failure is exposed separately by compound_regressions().
    """
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("invalid curriculum seed")
    rows = []

    def add(split, family, header, body, target, context="root"):
        n = random.Random(f"compound:{seed}:{split}:{family}").randrange(10**8)
        names = {s: f"{s}_{n}" for s in ("p", "h", "f", "x", "y", "a", "xs")}
        name = f"compound_{split}_{family}_{n}"
        prefix = f"theorem {name} " + header.format(**names) + " := by\n"
        rows.append({"id": name, "split": split, "family": family, "context": context,
                     "source": prefix + body.format(**names), "target": prefix + target.format(**names)})

    for split in ("train", "validation", "canary"):
        add(split, "hypothesis", "({p} : Prop) ({h} : {p}) : {p}", "  exact id {h}\n", "  assumption\n")
        add(split, "reflexivity", "({x} : Nat) : {x} = {x}", "  exact Eq.refl {x}\n", "  rfl\n")
        add(split, "truth", ": True", "  exact True.intro\n", "  trivial\n")
        add(split, "alias_reflexivity", "({x} : Nat) : {x} = {x}",
            "  let {y} := {x}\n  exact Eq.refl {y}\n", "  rfl\n")
        add(split, "unused_alias", "({x} : Nat) : {x} = {x}",
            "  let {y} := {x}\n  rfl\n", "  rfl\n")

    add("holdout", "introduced_alias", "({a} : Type) : ∀ {x} : {a}, {x} = {x}",
        "  intro {x}\n  let {y} := {x}\n  exact Eq.refl {y}\n", "  intro {x}\n  rfl\n", "intro")
    add("holdout", "list_alias", "({a} : Type) ({xs} : List {a}) : {xs} = {xs}",
        "  let {y} := {xs}\n  exact Eq.refl {y}\n", "  rfl\n", "polymorphic_list")
    add("holdout", "branch_alias", "({x} : Nat) : ({x} = {x}) ∧ True",
        "  constructor\n  case left =>\n    let {y} := {x}\n    exact Eq.refl {y}\n  case right => trivial\n",
        "  constructor\n  case left =>\n    rfl\n  case right => trivial\n", "case")
    add("holdout", "list_unused_alias", "({a} : Type) ({xs} : List {a}) : {xs} = {xs}",
        "  let {y} := {xs}\n  rfl\n", "  rfl\n", "polymorphic_list")
    add("holdout", "preserve_application", "({p} : Prop) ({h} : {p}) ({f} : {p} → {p}) : {p}",
        "  exact {f} {h}\n", "  exact {f} {h}\n", "no_applicable_template")
    add("holdout", "preserve_witness", "({x} : Nat) : ∃ {y} : Nat, {y} = {x}",
        "  let {y} := {x}\n  exact ⟨{y}, rfl⟩\n", "  let {y} := {x}\n  exact ⟨{y}, rfl⟩\n", "no_applicable_template")
    return rows


def compound_regressions():
    """Previously inspected holdout, now explicitly a post-freeze regression only."""
    from .rewrite_policy import body_of

    old = next(r for r in transfer_rows() if r["family"] == "local_definition")
    prefix, _ = body_of(old["source"])
    return [{**old, "split": "regression", "target": prefix + "\n  rfl\n",
             "previous_reference": old["target"], "previous_split": "holdout",
             "provenance": "previously_observed_transfer_holdout_not_fresh_evaluation"}]
