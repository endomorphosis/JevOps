"""Matched context-format/length/position probes and development-only profiling.

Retrieval is not Lean parsing, theorem proving or training evidence. No network,
provider changes, promotion or execution of generated code in this module.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import random
import re

from .arena import content_hash
from .arena_providers import strict_json

PROBE_SCHEMA = "jevops-leanstral-context-probe/v1"
PROFILE_SCHEMA = "jevops-leanstral-context-profile/v1"
POSITIONS = ("head", "middle", "tail")


def profile_cases(*, seed=53, distractors=(16, 128)):
    """Full size x position matrix in EACH split; matched facts across formats.

    Names have no correct-answer prefix/length shortcut. Each split uses fresh
    nonces; positions share a fact set. Repetitions are not independent problems.
    Sizes count irrelevant binders, not bytes or tokenizer-window capacity.
    """
    from .leanstral_prompt_lab import Case, bounded, encoded
    bounded(seed, 0, 2**32 - 1)
    if (type(distractors) is not tuple or not 1 <= len(distractors) <= 2
            or any(type(n) is not int or not 2 <= n <= 512 for n in distractors)
            or tuple(sorted(set(distractors))) != distractors):
        raise ValueError("one or two increasing distractor counts in 2..512 required")
    rng, cases = random.Random(seed), []
    for split in ("development", "confirmation"):
        goal = f"P_{rng.getrandbits(64):016x}"
        names = []
        while len(names) <= max(distractors):
            name = f"h_{rng.getrandbits(64):016x}"
            if name not in names: names.append(name)
        target = {"name": names[0], "type": goal}
        filler = [{"name": name, "type": "Nat"} for name in names[1:]]
        for size in distractors:
            for position in POSITIONS:
                offset = {"head": 0, "middle": size // 2, "tail": size}[position]
                locals_ = [*filler[:offset], target, *filler[offset:size]]
                context = encoded({"schema": PROBE_SCHEMA, "goal": goal, "locals": locals_,
                                   "distractors": size, "position": position})
                cases.append(Case(f"profile.{split}.{size}.{position}", split,
                    "Read the supplied local context, either Lean goal-state text or JSON with propositions, "
                    "locals (name/type pairs), and goal. Return exactly `exact NAME`, replacing NAME with "
                    "the unique hypothesis whose type equals the goal. No other tactic is allowed in this retrieval probe.",
                    context, expected="exact " + target["name"]))
    return tuple(cases)


def probe_data(case):
    if case.record is not None or case.context_blocks:
        raise ValueError("structured retrieval probe required, not an Arena proof")
    value = strict_json(case.context, limit=131072)
    if (type(value) is not dict or set(value) != {"schema", "goal", "locals", "distractors", "position"}
            or value["schema"] != PROBE_SCHEMA or type(value["distractors"]) is not int
            or not 2 <= value["distractors"] <= 512 or value["position"] not in POSITIONS
            or not isinstance(value["goal"], str) or not re.fullmatch(r"P_[0-9a-f]{16}", value["goal"])
            or type(value["locals"]) is not list or len(value["locals"]) != value["distractors"] + 1):
        raise ValueError("bounded structured probe schema required")
    names, matches = set(), []
    for index, local in enumerate(value["locals"]):
        if (type(local) is not dict or set(local) != {"name", "type"}
                or not isinstance(local["name"], str) or not re.fullmatch(r"h_[0-9a-f]{16}", local["name"])
                or local["name"] in names or local["type"] not in (value["goal"], "Nat")):
            raise ValueError("unique typed probe binders required")
        names.add(local["name"])
        if local["type"] == value["goal"]: matches.append(index)
    offset = {"head": 0, "middle": value["distractors"] // 2, "tail": value["distractors"]}[value["position"]]
    if matches != [offset] or case.expected != "exact " + value["locals"][offset]["name"]:
        raise ValueError("probe facts/position must agree with the hidden oracle")
    return value


def render_probe(case, representation):
    from .leanstral_prompt_lab import encoded
    data = probe_data(case)
    if representation == "lean_goal":
        return (data["goal"] + " : Prop\n" + "\n".join(f"{h['name']} : {h['type']}" for h in data["locals"])
                + "\n⊢ " + data["goal"])
    if representation == "json_locals":
        return encoded({"propositions": [data["goal"]], "locals": data["locals"], "goal": data["goal"]})
    raise ValueError("supported probe representation required")


def development_anchor(report):
    """Saved reports supply hypotheses only. Never consume confirmation outputs."""
    from .leanstral_prompt_feedback import _arm, development_digest
    digest = development_digest(report)
    if (not digest["development_complete"] or any(g["unmeasured"] for g in digest["groups"])
            or any(c.get("record") is not None for c in report["plan"]["cases"])):
        raise ValueError("complete measured retrieval development required for an anchor")
    best = max(digest["groups"], key=lambda g: (g["strict_successes"], g["normalized_successes"]))
    if not best["normalized_successes"]:
        raise ValueError("no successful development anchor; inspect failures instead")
    return _arm(next(a for a in report["plan"]["arms"] if a["name"] == best["arm"])), digest


def profile_study(*, seed=53, distractors=(16, 128), anchor=None, parent=None):
    from .leanstral_prompt_feedback import make_study
    from .leanstral_prompt_lab import Arm
    if parent is not None and anchor is not None:
        raise ValueError("explicit anchor OR development report, not both")
    digest = None
    if parent is not None:
        anchor, digest = development_anchor(parent)
        if seed == parent["plan"]["seed"]:
            raise ValueError("fresh probe seed required")
    anchor = anchor or Arm("anchor", roles="system_user")
    if anchor.context_layers != ("reference",):
        raise ValueError("retrieval anchor must use the reference context layer")
    control = replace(anchor, name="context-lean", probe_representation="lean_goal")
    treatment = replace(anchor, name="context-json", probe_representation="json_locals")
    return make_study(profile_cases(seed=seed, distractors=distractors), (control, treatment), seed=seed,
        hypothesis="Compare Lean goal-state text with structured JSON over identical facts; cross distractor count "
                   "and head/middle/tail position in both splits. No context capacity or proof-quality assumption.",
        source_development_sha256=None if digest is None else digest["development_sha256"],
        objective="strict_context_accuracy", confirmation_policy="all_arms")


def development_profile(report):
    """Recompute strata and mismatch symptoms, ignoring saved scores/holdouts.

    All cells are descriptive and small. No significance, maximum window,
    optimal format, causal explanation or automatic deployment is inferred.
    """
    from .leanstral_prompt_feedback import development_digest
    from .leanstral_prompt_lab import Case
    digest = development_digest(report)
    cases = {c["name"]: probe_data(Case(**c)) for c in report["plan"]["cases"] if c["split"] == "development"}
    sizes = sorted({c["distractors"] for c in cases.values()})
    if Counter((c["distractors"], c["position"]) for c in cases.values()) != Counter({
            (n, p): 1 for n in sizes for p in POSITIONS}):
        raise ValueError("complete crossed development design required")
    cells = []
    for arm in report["plan"]["arms"]:
        for size in sizes:
            for position in POSITIONS:
                own = [r for r in digest["observations"] if r["arm"] == arm["name"]
                       and cases[r["case"]]["distractors"] == size and cases[r["case"]]["position"] == position]
                cells.append({"arm": arm["name"], "representation": arm.get("probe_representation", "original"),
                    "distractors": size, "position": position, "attempts": len(own),
                    "unmeasured": sum(r["strict_success"] is None for r in own),
                    "strict_successes": sum(r["strict_success"] is True for r in own),
                    "normalized_successes": sum(r["normalized_success"] is True for r in own),
                    "strict_contract_oracle_mismatches": sum(r["strict_contract"] and r["normalized_success"] is False for r in own),
                    "max_prompt_bytes": max((r["prompt_bytes"] for r in own), default=None),
                    "max_server_reported_prompt_tokens": max((r["server_reported_prompt_tokens"] for r in own
                        if r["server_reported_prompt_tokens"] is not None), default=None),
                    "unavailable_categories": dict(Counter(r["unavailable_category"] for r in own if r["unavailable_category"])),
                    "features": dict(Counter(f for r in own for f in r["features"]))})
    hypotheses = []
    measured = digest["development_complete"] and not any(c["unmeasured"] for c in cells)
    if measured:
        for arm in report["plan"]["arms"]:
            own = [c for c in cells if c["arm"] == arm["name"]]
            if any(c["strict_contract_oracle_mismatches"] for c in own):
                hypotheses.append({"arm": arm["name"], "symptom": "well_formed_output_misses_context_oracle",
                    "followup": "Test reference vs relevant proof-state/premise context on fresh native Arena cases; do not infer a lost-context cause."})
            if any(c["features"].get("output_truncated") for c in own):
                hypotheses.append({"arm": arm["name"], "symptom": "output_truncated",
                    "followup": "Precommit a separate output-budget comparison; do not interpret truncation as context-window capacity."})
    return {"schema": PROFILE_SCHEMA, "source_plan_id": report["plan_id"],
        "source_development_sha256": digest["development_sha256"], "development_complete": digest["development_complete"],
        "fully_measured": measured, "cells": cells, "followup_hypotheses": hypotheses,
        "confirmation_consumed": False, "context_window_limit": None, "native_quality_established": False,
        "promotion": False, "authority": "descriptive unauthenticated development observations only",
        "warning": "Matched nonce retrieval, not unseen theorem families; repeated samples are not independent proofs."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-report", type=Path, help="optional development-only anchor from a saved lab report")
    parser.add_argument("--profile-report", type=Path, help="derive development profile, without generating a study")
    parser.add_argument("--seed", type=int, default=53)
    parser.add_argument("--distractors", type=int, nargs="+", default=[16, 128])
    parser.add_argument("--output", type=Path, required=True, help="NEW generated JSON; no overwrite")
    args = parser.parse_args(argv)
    if args.parent_report and args.profile_report:
        parser.error("anchor selection and profile reporting are separate operations")
    path = args.profile_report or args.parent_report
    if path:
        with path.open("rb") as stream: report = strict_json(stream.read(16_777_217), limit=16_777_216)
    result = (development_profile(report) if args.profile_report else
              profile_study(seed=args.seed, distractors=tuple(args.distractors), parent=report if path else None))
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "sha256": content_hash(result), "model_calls": 0,
                      "promotion": False, "planned_max_calls": result.get("limits", {}).get("max_calls")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
