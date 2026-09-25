"""Same-contract instruction/context ablations. Retrieval evidence, not Lean proofs.

Generate studies and reports without model calls. No fuzzy acceptance, output
repair, prompt promotion, teacher labels or watcher changes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
import statistics

from .arena import content_hash, source_hash
from .arena_providers import strict_json
from .leanstral_context_profile import development_anchor, profile_cases, probe_data
from .leanstral_prompt_contracts import check_binding
from .leanstral_prompt_feedback import _arm, make_study
from .leanstral_prompt_lab import Case, SCHEMA, bounded, parse_response, render

REPORT_SCHEMA = "jevops-leanstral-identifier-check/v1"
CONTEXT_REPORT_SCHEMA = "jevops-leanstral-client-bound-context/v1"


def attention_cases(*, seed, distractors=(16, 128)):
    """Independent nonce material in each cell, paired across arms/repetitions.

    Still one synthetic retrieval task family; repetitions are not independent
    theorems. Reuse the validated representation and unchanged exact oracle.
    """
    templates = profile_cases(seed=seed, distractors=distractors)
    cases = []
    for template in templates:
        cell_seed = int(content_hash({"design": REPORT_SCHEMA, "seed": seed,
                                      "cell": template.name})[:8], 16)
        case = next(c for c in profile_cases(seed=cell_seed, distractors=distractors)
                    if c.name == template.name)
        cases.append(case)
    if len({probe_data(c)["goal"] for c in cases}) != len(cases):
        raise ValueError("nonce collision: choose another precommitted seed")
    return tuple(cases)


def attention_study(parent, *, seed, distractors=(16, 128), experiment="identifier-check"):
    if experiment not in ("identifier-check", "context-format"):
        raise ValueError("explicit supported single-factor experiment required")
    bounded(seed, 0, 2**32 - 1)
    base, digest = development_anchor(parent)
    if seed == parent["plan"]["seed"]:
        raise ValueError("fresh seed required")
    if (base.contract != "json_tactic" or base.probe_representation == "original"
            or base.identifier_check):
        raise ValueError("unchanged client-bound structured retrieval anchor required")
    cases = attention_cases(seed=seed, distractors=distractors)
    if {c.expected for c in cases} & {c.get("expected") for c in parent["plan"]["cases"]}:
        raise ValueError("fresh oracle names required")
    if experiment == "context-format":
        if base.probe_representation != "lean_goal":
            raise ValueError("context comparison requires a measured Lean goal-state baseline")
        control = replace(base, name="context-lean")
        treatment = replace(control, name="context-json", probe_representation="json_locals")
        return make_study(cases, (control, treatment), seed=seed,
            source_development_sha256=digest["development_sha256"], objective="strict_context_accuracy",
            confirmation_policy="all_arms", hypothesis=
            "Test structured JSON locals versus Lean goal-state text under the SAME client-bound tactic-only "
            "JSON output contract. Select the baseline from prior development only. Keep facts, binder order, "
            "goal, instruction, roles, example, temperature, stops and output allowance identical. Fresh nonce "
            "families per size/position/split, paired arms. No identifier-check instruction, context filtering, "
            "oracle hints, name rewriting, output repair or fuzzy acceptance. Compare strict task accuracy, "
            "format compliance and server-reported token costs. No native quality claim or automatic promotion.")
    control = replace(base, name="identifier-control")
    treatment = replace(control, name="identifier-check", identifier_check=True)
    return make_study(cases, (control, treatment), seed=seed,
        source_development_sha256=digest["development_sha256"], objective="strict_context_accuracy",
        confirmation_policy="all_arms", hypothesis=
        "Test a type-match/copy/recheck instruction under the SAME tactic-only JSON contract. "
        "The baseline is selected from development only. This is an operator-proposed hypothesis, not "
        "an inferred cause of previous failures. Fresh nonce families per size/position/split, paired arms, "
        "unchanged oracle, context, temperature, examples, stops and output budget. Report strict task "
        "success separately from envelope compliance and token costs. No fuzzy acceptance, repairs, "
        "Arena proof admission, automatic deployment or training.")


def _one_edit(a, b):
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    return len(b) == len(a) + 1 and any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def tactic_diagnostic(case, tactic):
    """Explanatory labels only. Near matches NEVER pass the exact oracle."""
    data = probe_data(case)
    if tactic is None:
        return "unparsed"
    if tactic == case.expected:
        return "exact_oracle"
    match = re.fullmatch(r"exact ([A-Za-z0-9_]{1,128})", tactic)
    if not match:
        return "other_tactic"
    name = match[1]
    locals_ = {h["name"]: h["type"] for h in data["locals"]}
    if name in locals_:
        return "wrong_hypothesis_type"
    return ("unknown_identifier_one_edit_from_target" if _one_edit(name, case.expected[6:])
            else "unknown_identifier")


def attention_report(report, *, experiment="identifier-check"):
    """Audit frozen slots and bindings, recompute both splits for REPORTING only.

    Saved scores/nomination cannot alter the result. This function deliberately
    reads confirmation; it must not be used by the development selector.
    """
    if experiment not in ("identifier-check", "context-format"):
        raise ValueError("explicit supported single-factor experiment required")
    if (type(report) is not dict or report.get("schema") != SCHEMA
            or type(report.get("plan")) is not dict or report.get("plan_id") != content_hash(report["plan"])):
        raise ValueError("matching frozen plan required")
    plan = report["plan"]
    bounded(plan.get("seed"), 0, 2**32 - 1)
    bounded(plan.get("repetitions"), 2, 4)
    if (type(plan.get("cases")) is not list or not 5 <= len(plan["cases"]) <= 16
            or type(plan.get("arms")) is not list or len(plan["arms"]) != 2
            or type(report.get("rows")) is not list or len(report["rows"]) > 128
            or plan.get("objective") != "strict_context_accuracy"
            or plan.get("confirmation_policy") != "all_arms" or plan.get("max_native_requests") != 0):
        raise ValueError("bounded retrieval-only all-arms design required")
    cases = {c["name"]: Case(**c) for c in plan["cases"]}
    sizes = tuple(sorted({probe_data(c)["distractors"] for c in cases.values()}))
    if tuple(cases.values()) != attention_cases(seed=plan["seed"], distractors=sizes):
        raise ValueError("fresh crossed nonce design required")
    arms = [_arm(a) for a in plan["arms"]]
    a, b = map(asdict, arms)
    factor = "identifier_check" if experiment == "identifier-check" else "probe_representation"
    if (len(cases) != len(plan["cases"]) or len({x.name for x in arms}) != 2
            or {k for k in a if a[k] != b[k]} != {"name", factor}
            or arms[0].identifier_check
            or any(x.contract != "json_tactic" or x.probe_representation == "original" for x in arms)):
        raise ValueError("same contract; only the declared experimental factor may differ")
    if experiment == "identifier-check" and not arms[1].identifier_check:
        raise ValueError("identifier-check intervention required")
    if experiment == "context-format" and ([a.probe_representation for a in arms] != ["lean_goal", "json_locals"]
                                          or arms[1].identifier_check):
        raise ValueError("Lean/JSON contexts without extra checking instruction required")
    arm_map = {a.name: a for a in arms}
    expected_slots = {(c.name, a.name, r) for c in cases.values() for a in arms
                      for r in range(plan["repetitions"])}
    seen, observations = set(), []
    for row in report["rows"]:
        if type(row) is not dict or row.get("case") not in cases or row.get("arm") not in arm_map:
            raise ValueError("known result slot required")
        rep = row.get("repetition")
        bounded(rep, 0, plan["repetitions"] - 1)
        case, arm = cases[row["case"]], arm_map[row["arm"]]
        slot = (case.name, arm.name, rep)
        if slot in seen:
            raise ValueError("duplicate result slot")
        seen.add(slot)
        messages, rid = render(case, arm, rep)
        if (row.get("messages") != messages or row.get("request_id") != rid
                or row.get("prompt_sha256") != content_hash(messages) or row.get("split") != case.split):
            raise ValueError("frozen prompt/slot mismatch")
        raw, meta = row.get("response"), row.get("metadata", {})
        if type(meta) is not dict:
            raise ValueError("response metadata required")
        strict, envelope, diagnostic = None, None, "unmeasured"
        if raw is not None:
            if not isinstance(raw, str) or len(raw.encode()) > 65536 or row.get("response_sha256") != source_hash(raw):
                raise ValueError("matching bounded raw response required")
            check_binding(meta.get("client_binding"), messages, arm, raw)
            parsed = parse_response(raw, arm, rid, meta.get("finish_reason"))
            envelope = parsed["strict_contract"]
            strict = bool(envelope and parsed["tactic"] == case.expected)
            diagnostic = tactic_diagnostic(case, parsed["tactic"])
        usage = meta.get("usage")
        tokens = {k: usage.get(k) if type(usage) is dict else None for k in ("prompt_tokens", "completion_tokens")}
        tokens = {k: v if type(v) is int and 0 <= v <= 2**31 else None for k, v in tokens.items()}
        data = probe_data(case)
        observations.append({"case": case.name, "arm": arm.name, "split": case.split, "repetition": rep,
            "distractors": data["distractors"], "position": data["position"],
            "strict_success": strict, "envelope_compliant": envelope, "diagnostic": diagnostic, **tokens})
    groups, cells = [], []
    for split in ("development", "confirmation"):
        for arm in arms:
            own = [r for r in observations if r["split"] == split and r["arm"] == arm.name]
            summary = {"split": split, "arm": arm.name, "attempts": len(own),
                "unmeasured": sum(r["strict_success"] is None for r in own),
                "strict_successes": sum(r["strict_success"] is True for r in own),
                "envelope_compliant": sum(r["envelope_compliant"] is True for r in own),
                "diagnostics": dict(Counter(r["diagnostic"] for r in own))}
            for key in ("prompt_tokens", "completion_tokens"):
                values = [r[key] for r in own if r[key] is not None]
                summary["median_server_" + key] = statistics.median(values) if values else None
            groups.append(summary)
            for size in sizes:
                for position in ("head", "middle", "tail"):
                    cell = [r for r in own if (r["distractors"], r["position"]) == (size, position)]
                    cells.append({"split": split, "arm": arm.name, "distractors": size, "position": position,
                        "attempts": len(cell), "strict_successes": sum(r["strict_success"] is True for r in cell),
                        "unmeasured": sum(r["strict_success"] is None for r in cell)})
    complete = seen == expected_slots and all(r["strict_success"] is not None for r in observations)
    pairs = {}
    for row in observations:
        if row["split"] == "confirmation":
            pairs.setdefault((row["case"], row["repetition"]), {})[row["arm"]] = row["strict_success"]
    pair_counts = Counter()
    if complete:
        for pair in pairs.values():
            x, y = pair[arms[0].name], pair[arms[1].name]
            pair_counts["treatment_only_success" if y and not x else "control_only_success" if x and not y else "tie"] += 1
    result = {"schema": REPORT_SCHEMA, "source_plan_id": report["plan_id"], "groups": groups, "cells": cells,
        "evidence_mode": plan.get("mode"),
        "rows": observations, "complete": complete, "paired_confirmation": dict(pair_counts),
        "confirmation_consumed_for_reporting": True, "confirmation_used_for_selection": False,
        "same_output_contract": True, "promotion": False, "native_quality_established": False,
        "warning": "Small synthetic retrieval ablation, not proof verification, independent theorems or an optimal prompt. "
                   "Repeated responses within a case are dependent. One-edit matches remain failures. "
                   "Token costs are server-reported generation costs, not Lean proof tokens or heartbeats."}
    if experiment == "context-format":
        result["schema"] = CONTEXT_REPORT_SCHEMA
        result["representations"] = {a.name: a.probe_representation for a in arms}
        result["token_cost_contrasts"] = []
        # Paired differences, not differences of independently computed medians.
        # Missing token telemetry is omitted explicitly, never imputed as zero.
        slots = {(r["case"], r["repetition"], r["arm"]): r for r in observations}
        for split in ("development", "confirmation"):
            for size in sizes:
                for metric in ("prompt_tokens", "completion_tokens"):
                    deltas = []
                    expected_pairs = 0
                    for c in cases.values():
                        if c.split != split or probe_data(c)["distractors"] != size:
                            continue
                        for rep in range(plan["repetitions"]):
                            expected_pairs += 1
                            left = slots.get((c.name, rep, arms[0].name), {}).get(metric)
                            right = slots.get((c.name, rep, arms[1].name), {}).get(metric)
                            if left is not None and right is not None:
                                deltas.append(right - left)
                    result["token_cost_contrasts"].append({"split": split, "distractors": size,
                        "metric": metric, "expected_pairs": expected_pairs, "measured_pairs": len(deltas),
                        "median_json_minus_lean": statistics.median(deltas) if deltas else None})
    return result


def markdown_results(summary):
    title = ("Leanstral same-contract context-format experiment" if summary["schema"] == CONTEXT_REPORT_SCHEMA
             else "Leanstral identifier-check prompt experiment")
    lines = ["# " + title, "",
             "Both arms use the same client-bound tactic-only JSON contract and exact oracle.", "",
             "Evidence mode: " + str(summary["evidence_mode"]), "",
             "| Split | Prompt | Strict successes | Envelope compliant | Measured attempts |",
             "| --- | --- | ---: | ---: | ---: |"]
    for g in summary["groups"]:
        lines.append(f"| {g['split']} | {g['arm']} | {g['strict_successes']} | {g['envelope_compliant']} | {g['attempts'] - g['unmeasured']} |")
    lines += ["", "Complete measured design: " + str(summary["complete"]), "",
              "Paired confirmation: " + json.dumps(summary["paired_confirmation"], sort_keys=True), ""]
    if summary["schema"] == CONTEXT_REPORT_SCHEMA:
        lines += ["## Server-reported token costs", "",
                  "Paired JSON-context minus Lean-context token counts; not Lean proof tokens.", "",
                  "| Split | Distractors | Metric | Measured / expected pairs | Median difference |",
                  "| --- | ---: | --- | ---: | ---: |"]
        for row in summary["token_cost_contrasts"]:
            lines.append(f"| {row['split']} | {row['distractors']} | {row['metric']} | "
                         f"{row['measured_pairs']} / {row['expected_pairs']} | {row['median_json_minus_lean']} |")
        lines.append("")
    lines += [
              summary["warning"], "", "No automatic deployment, proof promotion or training.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--parent-report", type=Path)
    inputs.add_argument("--report", type=Path)
    parser.add_argument("--seed", type=int, default=137)
    parser.add_argument("--experiment", choices=("identifier-check", "context-format"), default="identifier-check")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    if args.markdown and not args.report:
        parser.error("markdown is for completed experiment reporting only")
    if args.output.exists() or (args.markdown and args.markdown.exists()):
        raise FileExistsError("refuse to overwrite retained evidence")
    with (args.parent_report or args.report).open("rb") as stream:
        report = strict_json(stream.read(16_777_217), limit=16_777_216)
    result = (attention_report(report, experiment=args.experiment) if args.report else
              attention_study(report, seed=args.seed, experiment=args.experiment))
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    if args.markdown:
        with args.markdown.open("x") as stream:
            stream.write(markdown_results(result))
    print(json.dumps({"output": str(args.output), "model_calls": 0, "promotion": False,
                      "planned_calls": result.get("limits", {}).get("max_calls")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
