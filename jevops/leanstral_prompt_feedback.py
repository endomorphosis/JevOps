"""Development-only failure analysis and bounded successor study proposals.

Saved observations are unauthenticated hints, never native verification or
teacher labels. Confirmation responses/scores cannot influence this learner.
No network, model generation, Python execution or promotion occurs here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path

from .arena import content_hash, source_hash
from .arena_providers import strict_json

STUDY_SCHEMA = "jevops-leanstral-prompt-study/v1"
FEEDBACK_SCHEMA = "jevops-leanstral-prompt-feedback/v1"


def output_features(raw, *, contract, request_id, finish_reason, expected=None):
    """Observable symptoms, not guesses about model reasoning or serving causes."""
    if not isinstance(raw, str) or len(raw.encode()) > 65536:
        return ["response_unavailable_or_oversized"]
    features = []
    if finish_reason == "length": features.append("output_truncated")
    if "<|im_start|>" in raw: features.append("chat_role_leakage")
    if "</context>" in raw: features.append("context_delimiter_leakage")
    if "```" in raw: features.append("markdown_fence")
    value = raw.strip()
    for _ in range(4):
        marker = next((m for m in ("<|im_end|>", "</s>", "[eos]") if value.endswith(m)), None)
        if marker is None: break
        if "terminal_eos_marker" not in features: features.append("terminal_eos_marker")
        if "terminal_marker:" + marker not in features: features.append("terminal_marker:" + marker)
        value = value[:-len(marker)].rstrip()
    if contract in ("json", "json_tactic"):
        try:
            obj = strict_json(value)
        except ValueError:
            features.append("invalid_json")
        else:
            if not isinstance(obj, dict):
                features.append("json_not_object")
            else:
                fields = {"request_id", "tactic"} if contract == "json" else {"tactic"}
                field_mismatch = set(obj) != fields
                id_mismatch = contract == "json" and obj.get("request_id") != request_id
                if field_mismatch: features.append("json_field_mismatch")
                if id_mismatch: features.append("request_id_mismatch")
                if not isinstance(obj.get("tactic"), str): features.append("json_tactic_not_string")
                if obj.get("tactic") == "the tactic body without by": features.append("literal_contract_placeholder")
                if expected and obj.get("tactic") == expected and (field_mismatch or id_mismatch):
                    features.append("oracle_tactic_in_invalid_envelope")
    elif expected and value != expected and value.startswith(expected) and (
            len(value) == len(expected) or not (value[len(expected)].isalnum() or value[len(expected)] in "_'")):
        # Correct exact-match prefix plus junk is not a wrong-hypothesis diagnosis.
        features.append("expected_tactic_with_extra_output")
    return sorted(features)


def _arm(value):
    from .leanstral_prompt_lab import Arm
    if not isinstance(value, dict): raise ValueError("arm object required")
    value = dict(value)
    for key in ("context_layers", "stop"):
        if key in value:
            if type(value[key]) not in (list, tuple): raise ValueError("arm sequence required")
            value[key] = tuple(value[key])
    try:
        return Arm(**value)
    except TypeError as exc:
        raise ValueError("unknown arm field") from exc


def development_digest(report):
    """Recompute contract/probe outcomes; ignore reported reward and nomination.

    Check immutable plan membership before reading row payloads, so even a
    confirmation row relabeled 'development' is not an adaptive learning input.
    Hashes detect inconsistent files; they do not authenticate saved model output.
    """
    from .leanstral_prompt_lab import SCHEMA, Case, bounded, encoded, parse_response, render
    if (type(report) is not dict or report.get("schema") != SCHEMA or type(report.get("plan")) is not dict
            or report.get("plan_id") != content_hash(report["plan"])):
        raise ValueError("matching prompt-lab plan hash required")
    plan = report["plan"]
    bounded(plan.get("repetitions"), 2, 4)
    if (not isinstance(plan.get("cases"), list) or not 5 <= len(plan["cases"]) <= 16
            or not isinstance(plan.get("arms"), list) or not 2 <= len(plan["arms"]) <= 8
            or not isinstance(report.get("rows"), list) or len(report["rows"]) > 128):
        raise ValueError("bounded experiment collections required")
    cases = {c["name"]: c for c in plan["cases"]}
    arms = {a["name"]: _arm(a) for a in plan["arms"]}
    if len(cases) != len(plan["cases"]) or len(arms) != len(plan["arms"]):
        raise ValueError("duplicate case/arm identity")
    for case in cases.values(): Case(**case)
    dev = {name: case for name, case in cases.items() if case["split"] == "development"}
    slots, observations = set(), []
    for row in report["rows"]:
        if not isinstance(row, dict) or row.get("case") not in dev:
            continue  # Do not read held-out response/metrics, even if relabeled.
        arm, case = arms.get(row.get("arm")), dev[row["case"]]
        repetition = row.get("repetition")
        bounded(repetition, 0, plan["repetitions"] - 1)
        slot = (row["case"], row.get("arm"), repetition)
        if arm is None or slot in slots: raise ValueError("duplicate or unknown development slot")
        slots.add(slot)
        expected_id = content_hash({"case": case, "repetition": repetition})[:16]
        if (row.get("request_id") != expected_id or row.get("prompt_sha256") != content_hash(row.get("messages"))):
            raise ValueError("development request binding mismatch")
        if row["messages"] != render(Case(**case), arm, repetition)[0]:
            raise ValueError("development prompt differs from the frozen case/arm")
        raw, meta = row.get("response"), row.get("metadata", {})
        if not isinstance(meta, dict): raise ValueError("response metadata object required")
        if raw is not None and (not isinstance(raw, str) or len(raw.encode()) > 65536 or
                                row.get("response_sha256") != source_hash(raw)):
            raise ValueError("response hash/size mismatch")
        if raw is not None and (arm.contract == "json_tactic" or meta.get("client_binding") is not None):
            from .leanstral_prompt_contracts import check_binding
            check_binding(meta.get("client_binding"), row["messages"], arm, raw)
        parsed = parse_response(raw, arm, expected_id, meta.get("finish_reason"))
        oracle = case.get("expected")
        correct = parsed["tactic"] == oracle if oracle is not None and raw is not None else None
        usage = meta.get("usage")
        tokens = usage.get("prompt_tokens") if type(usage) is dict else None
        tokens = tokens if type(tokens) is int and 0 <= tokens <= 2**31 else None
        category = row.get("status") if raw is None else None
        if category not in {"timeout", "transport", "http_error", "protocol", "output_truncated",
                            "reasoning_without_answer", "unexpected_tool_calls", "adapter_error", "client_binding_mismatch"}:
            category = "unknown" if raw is None else None
        observations.append({"case": row["case"], "arm": arm.name, "repetition": repetition,
            "response_sha256": source_hash(raw) if raw is not None else None,
            "normalized_success": correct, "strict_success": bool(correct and parsed["strict_contract"]) if correct is not None else None,
            "features": output_features(raw, contract=arm.contract, request_id=expected_id,
                finish_reason=meta.get("finish_reason"), expected=oracle),
            "parse_status": parsed["status"], "prompt_sha256": row["prompt_sha256"],
            "strict_contract": parsed["strict_contract"], "unavailable_category": category,
            "prompt_bytes": len(encoded(row["messages"]).encode()), "server_reported_prompt_tokens": tokens})
    observations.sort(key=lambda r: (r["case"], r["repetition"], r["arm"]))
    expected_slots = {(name, arm, r) for name in dev for arm in arms for r in range(plan["repetitions"])}
    groups = []
    for name in arms:
        own = [r for r in observations if r["arm"] == name]
        groups.append({"arm": name, "attempts": len(own),
            "unmeasured": sum(r["normalized_success"] is None for r in own),
            "normalized_successes": sum(r["normalized_success"] is True for r in own),
            "strict_successes": sum(r["strict_success"] is True for r in own),
            "features": dict(Counter(f for r in own for f in r["features"]))})
    result = {"schema": FEEDBACK_SCHEMA, "source_plan_id": report["plan_id"],
        "development_complete": slots == expected_slots, "groups": groups, "observations": observations,
        "confirmation_consumed": False, "authority": "saved development observations; unauthenticated hypotheses only",
        "native_quality_established": False, "promotion": False}
    return {**result, "development_sha256": content_hash(result)}


def make_study(cases, arms, *, seed, hypothesis, source_development_sha256=None,
               objective=None, max_native_requests=0, confirmation_policy="nominee"):
    """Freeze a proposed comparison; this function performs no calls or writes."""
    from .leanstral_prompt_lab import bounded
    bounded(seed, 0, 2**32 - 1)
    if not isinstance(hypothesis, str) or not 1 <= len(hypothesis.encode()) <= 4096:
        raise ValueError("bounded hypothesis required")
    if source_development_sha256 is not None and (not isinstance(source_development_sha256, str) or
            len(source_development_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_development_sha256)):
        raise ValueError("development digest required")
    dev = sum(c.split == "development" for c in cases)
    confirmation = sum(c.split == "confirmation" for c in cases)
    study = {"schema": STUDY_SCHEMA, "seed": seed, "arms": [asdict(a) for a in arms],
        "cases": [asdict(c) for c in cases], "hypothesis": hypothesis,
        "source_development_sha256": source_development_sha256,
        "limits": {"max_calls": 2 * (dev * len(arms) + (len(arms) if confirmation_policy == "all_arms" else 2) * confirmation), "max_new_tokens": 128,
                   "max_native_requests": max_native_requests, "timeout": 45, "max_prompt_bytes": 32768,
                   "repetitions": 2, "objective": objective, "confirmation_policy": confirmation_policy}}
    lab_from_study(Path("unused-plan-only"), study)  # Full validation without mkdir/model calls.
    return study


def next_probe_study(report, *, seed):
    """One measured failure -> one proposed treatment, new nonce holdouts.

    Scope deliberately limited to stop-marker, JSON-example and literal-schema hypotheses, not
    a generic LLM prompt optimizer. Missing evidence abstains. Both interventions
    preserve the parser/oracle; no reward is earned by repairing outputs.
    """
    from .leanstral_prompt_lab import Case, context_probes, bounded
    bounded(seed, 0, 2**32 - 1)
    digest = development_digest(report)
    if not digest["development_complete"]:
        raise ValueError("incomplete development; no automatic successor study")
    if any(g["unmeasured"] for g in digest["groups"]):
        raise ValueError("unmeasured development responses; no automatic successor study")
    if any(c.get("record") is not None for c in report["plan"]["cases"]):
        raise ValueError("Arena studies need explicit fresh development/confirmation cases; no synthetic substitution")
    if seed == report["plan"]["seed"]:
        raise ValueError("fresh probe seed required; never recycle the prior confirmation suite")
    groups = digest["groups"]
    anchor = max(groups, key=lambda g: (g["normalized_successes"], g["strict_successes"]))
    if not anchor["normalized_successes"]:
        raise ValueError("no successful development anchor for a supported hypothesis")
    raw_arm = next(a for a in report["plan"]["arms"] if a["name"] == anchor["arm"])
    base = _arm(raw_arm)
    if not base.stop and anchor["features"].get("terminal_eos_marker"):
        baseline = replace(base, name="boundary-control")
        observed_marker = max(("<|im_end|>", "</s>", "[eos]"),
                              key=lambda marker: anchor["features"].get("terminal_marker:" + marker, 0))
        if not anchor["features"].get("terminal_marker:" + observed_marker):
            raise ValueError("no observed terminal marker to test")
        treatment = replace(baseline, name="boundary-stop", stop=(observed_marker,))
        hypothesis = ("An explicit terminal stop string may improve exact output-contract compliance. "
                      "Change only stop handling; do not infer proof-quality improvement or silently strip extra text.")
    elif (base.contract == "json" and base.json_contract_style == "placeholder"
          and anchor["features"].get("literal_contract_placeholder")):
        baseline = replace(base, name="wording-control")
        treatment = replace(baseline, name="wording-descriptive", json_contract_style="descriptive")
        hypothesis = ("Observed literal schema placeholder copying motivates a descriptive contract comparison. "
                      "Change wording only; preserve examples, context, stops, budgets and the exact oracle.")
    elif (base.contract == "json" and not base.contract_example and any(anchor["features"].get(f)
            for f in ("invalid_json", "json_not_object", "json_field_mismatch", "request_id_mismatch"))):
        baseline = replace(base, name="example-control")
        treatment = replace(baseline, name="example-treatment", contract_example=True)
        hypothesis = ("An unrelated JSON output example may improve exact contract compliance. "
                      "Change only the example; keep stopping, context, temperature, budgets and oracle fixed. "
                      "Copied example values must fail. This does not establish improved Lean proof quality.")
    else:
        raise ValueError("no untested supported hypothesis in development data; investigate a different hypothesis")
    # Preserve structured context factors for successor studies; never silently
    # turn a failed context-representation experiment into the older easy probe.
    if base.probe_representation != "original":
        from .leanstral_context_profile import profile_cases, probe_data
        sizes = tuple(sorted({probe_data(Case(**c))["distractors"]
                              for c in report["plan"]["cases"]}))
        cases = profile_cases(seed=seed, distractors=sizes)
    else:
        cases = context_probes(seed)
    return make_study(cases, (baseline, treatment), seed=seed,
        hypothesis=hypothesis,
        source_development_sha256=digest["development_sha256"], objective="strict_context_accuracy")


def context_study(cases, anchor, *, layer, seed=23, max_native_requests=0):
    """Explicit Arena context ablation, no collection/mining of blind holdouts."""
    from .leanstral_prompt_lab import CONTEXT_LAYERS
    if layer not in CONTEXT_LAYERS or any(c.record is None for c in cases):
        raise ValueError("Arena cases and an allowlisted context layer required")
    # For `reference`, compare statement-only to reference; otherwise add exactly
    # one version/source-bound hint block to identical reference context.
    layers = () if layer == "reference" else ("reference",)
    baseline = replace(anchor, name="context-control", context_layers=layers)
    treatment = replace(baseline, name="context-treatment", context_layers=(*layers, layer))
    return make_study(cases, (baseline, treatment), seed=seed,
        hypothesis=f"Adding {layer} context may improve native strict-dual success; requires fresh native evaluation.",
        objective="native_strict_dual_rate", max_native_requests=max_native_requests)


def diagnostic_context(record, trial):
    """Collect bounded, source/pin-bound rejection hints from Arena trial receipts.

    Historical controls must have passed; fixture, unavailable and mismatched
    reports are not compiler feedback. Even checked history is not authenticated
    and cannot establish a new proof, cost, or training label.
    """
    from .arena_trial import SCHEMA as TRIAL_SCHEMA
    from .refactor_prompts import _examples
    from .leanstral_prompt_lab import context_block, encoded
    if (not isinstance(trial, dict) or trial.get("schema") != TRIAL_SCHEMA or
            trial.get("evidence_mode") != "local_lean" or content_hash(trial.get("record")) != content_hash(record)):
        raise ValueError("matching native trial required for diagnostic context")
    examples = _examples(trial)  # Validate receipt/source/dependency/version bindings first.
    controls = [s for s in trial["samples"] if s["label"] == "control"]
    if trial.get("status") != "COMPLETE" or not controls or any(s["status"] != "VERIFIED" for s in controls):
        return None
    rows, omitted = [], 0
    for example in sorted(examples, key=lambda e: e["source_sha256"]):
        for observed in example["observations"]:
            if observed["outcome_reported"] != "REJECTED" or not observed.get("diagnostics"):
                continue
            row = {"candidate_source": example["candidate_source"], "source_sha256": example["source_sha256"],
                   "observation": observed}
            if len(rows) == 4 or len(encoded([*rows, row]).encode()) > 60000:
                omitted += 1
            else:
                rows.append(row)
    if not rows: return None
    return context_block(record, encoded({"historical_rejections_not_proof_labels": rows,
        "observations_omitted": omitted, "trial_sha256": content_hash(trial), "fresh_verification_required": True}),
        origin="historical native diagnostics; binding checked, authenticity not established")


def lab_from_study(directory, study, *, base_url=None, model_revision="unknown", generator=None,
                   judge=None, storage_guard=None):
    from .leanstral import BASE_URL
    from .leanstral_prompt_lab import Case, PromptLab
    if (type(study) is not dict or set(study) != {"schema", "seed", "arms", "cases", "hypothesis", "source_development_sha256", "limits"}
            or study["schema"] != STUDY_SCHEMA or not isinstance(study["arms"], list) or not 2 <= len(study["arms"]) <= 8
            or not isinstance(study["cases"], list) or not 5 <= len(study["cases"]) <= 16
            or type(study["limits"]) is not dict
            or not ({"max_calls", "max_new_tokens", "max_native_requests", "timeout", "max_prompt_bytes", "repetitions", "objective"}
                    <= set(study["limits"]) <= {"max_calls", "max_new_tokens", "max_native_requests", "timeout", "max_prompt_bytes", "repetitions", "objective", "confirmation_policy"})
            or not isinstance(study["hypothesis"], str) or not 1 <= len(study["hypothesis"].encode()) <= 4096):
        raise ValueError("explicit bounded study schema required; no executable or provider fields")
    digest = study["source_development_sha256"]
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("source development digest must be SHA-256 or null")
    try:
        cases = tuple(Case(**c) for c in study["cases"])
    except TypeError as exc:
        raise ValueError("unknown case fields") from exc
    return PromptLab(directory, cases, arms=tuple(_arm(a) for a in study["arms"]), seed=study["seed"],
        base_url=base_url or BASE_URL, model_revision=model_revision, generator=generator, judge=judge,
        storage_guard=storage_guard, study_provenance={"hypothesis": study["hypothesis"],
            "source_development_sha256": study["source_development_sha256"], "study_sha256": content_hash(study)},
        **study["limits"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="NEW study JSON; refuses overwrites")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    with args.report.open("rb") as stream:
        report = strict_json(stream.read(16_777_217), limit=16_777_216)
    study = next_probe_study(report, seed=args.seed)
    # No automatic generation/deployment, no report deletion, no overwrite.
    with args.output.open("x") as stream:
        json.dump(study, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"study_path": str(args.output), "study_sha256": content_hash(study),
                      "max_calls": study["limits"]["max_calls"], "model_calls": 0, "promotion": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
