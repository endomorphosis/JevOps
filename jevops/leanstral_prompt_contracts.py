"""Experimental response-contract studies, not proof admission or authentication.

The trusted synchronous client binds request/arm/raw response before parsing.
Hashes detect inconsistent or swapped records; a hostile client/server can still
forge them. New contracts are retrieval-only. Old failed receipts stay failed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import re

from .arena import content_hash, source_hash
from .arena_providers import strict_json

BINDING_SCHEMA = "jevops-leanstral-client-binding/v1"
REPORT_SCHEMA = "jevops-leanstral-contract-comparison/v1"


class ClientBindingError(ValueError):
    category = "client_binding_mismatch"


def request_binding(messages, arm, *, response_format=None):
    value = asdict(arm)
    # Preserve the binding of pre-existing receipts when this new intervention
    # is disabled. Enabled interventions are always bound, not silently ignored.
    if value.get("identifier_check") is False:
        value.pop("identifier_check")
    request = {"messages": messages, "arm": value}
    if response_format is not None:
        request["response_format"] = response_format
    return content_hash(request)


def bind_response(request_sha256, raw):
    if (not isinstance(request_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", request_sha256)
            or not isinstance(raw, str) or len(raw.encode()) > 65536):
        raise ClientBindingError("bounded client request and response required")
    return {"schema": BINDING_SCHEMA, "request_sha256": request_sha256, "response_sha256": source_hash(raw)}


def check_binding(binding, messages, arm, raw, *, response_format=None):
    expected = bind_response(request_binding(messages, arm, response_format=response_format), raw)
    if type(binding) is not dict or binding != expected:
        raise ClientBindingError("client response does not match the exact request/arm/raw output")


def request_id_study(report, *, seed):
    """Choose the development arm showing correct tactics with bad echoed IDs.

    Diagnostic counts select a problem to investigate, not a winning proof
    policy. Fresh nonce cases, identical context, both arms in confirmation.
    """
    from .leanstral_context_profile import profile_cases, probe_data
    from .leanstral_prompt_feedback import _arm, development_digest, make_study
    from .leanstral_prompt_lab import Case, bounded
    bounded(seed, 0, 2**32 - 1)
    digest = development_digest(report)
    if not digest["development_complete"] or any(g["unmeasured"] for g in digest["groups"]):
        raise ValueError("complete measured development required")
    if seed == report["plan"]["seed"]:
        raise ValueError("fresh seed required; preserve prior confirmation")
    dev = [Case(**c) for c in report["plan"]["cases"] if c["split"] == "development"]
    sizes = tuple(sorted({probe_data(c)["distractors"] for c in dev}))
    arms = {a["name"]: _arm(a) for a in report["plan"]["arms"]}
    eligible = [g for g in digest["groups"] if arms[g["arm"]].contract == "json"
                and any(r["arm"] == g["arm"] and "request_id_mismatch" in r["features"]
                        and "oracle_tactic_in_invalid_envelope" in r["features"] for r in digest["observations"])]
    if not eligible:
        raise ValueError("no observed correct-tactic/wrong-request-ID development anchor")
    anchor = max(eligible, key=lambda g: sum(r["arm"] == g["arm"] and "request_id_mismatch" in r["features"]
                 and "oracle_tactic_in_invalid_envelope" in r["features"] for r in digest["observations"]))
    base = replace(arms[anchor["arm"]], name="id-echo-control")
    treatment = replace(base, name="client-bound-tactic", contract="json_tactic")
    return make_study(profile_cases(seed=seed, distractors=sizes), (base, treatment), seed=seed,
        source_development_sha256=digest["development_sha256"], objective="strict_context_accuracy",
        confirmation_policy="all_arms", hypothesis=
        "Observed development ID-copying errors motivate testing tactic-only JSON with trusted-client request binding. "
        "This CHANGES the declared output contract; compare fresh complete-workflow success and separately report "
        "exact tactic accuracy. Do not repair old IDs, rescore prior failures, infer better reasoning, or admit Arena proofs.")


def comparison_report(report):
    """Recompute both splits for reporting only, never successor selection.

    A tactic inside the wrong envelope is a diagnostic, NOT an accepted result.
    The strict success column uses each predeclared contract, not a shared schema.
    """
    from .leanstral_prompt_feedback import _arm
    from .leanstral_prompt_lab import Case, SCHEMA, parse_response, render
    if (type(report) is not dict or report.get("schema") != SCHEMA or type(report.get("plan")) is not dict
            or report.get("plan_id") != content_hash(report["plan"])):
        raise ValueError("matching frozen lab plan required")
    plan = report["plan"]
    if (type(plan.get("cases")) is not list or not 5 <= len(plan["cases"]) <= 16
            or type(plan.get("arms")) is not list or len(plan["arms"]) != 2
            or type(report.get("rows")) is not list or len(report["rows"]) > 128
            or type(plan.get("repetitions")) is not int or not 2 <= plan["repetitions"] <= 4):
        raise ValueError("bounded contract comparison required")
    cases = {c["name"]: Case(**c) for c in plan["cases"]}
    arms = {a["name"]: _arm(a) for a in plan["arms"]}
    if (len(cases) != len(plan["cases"]) or len(arms) != 2
            or any(c.record is not None for c in cases.values())
            or {a.contract for a in arms.values()} != {"json", "json_tactic"}
            or plan.get("confirmation_policy") != "all_arms" or plan.get("objective") != "strict_context_accuracy"):
        raise ValueError("retrieval-only predeclared two-contract comparison required")
    first, second = [asdict(a) for a in arms.values()]
    if {k for k in first if first[k] != second[k]} != {"name", "contract"}:
        raise ValueError("contract comparison must change only the declared contract")
    rows, seen = [], set()
    for row in report["rows"]:
        if type(row) is not dict or row.get("case") not in cases or row.get("arm") not in arms:
            raise ValueError("known result slot required")
        case, arm, rep = cases[row["case"]], arms[row["arm"]], row.get("repetition")
        if type(rep) is not int or not 0 <= rep < plan["repetitions"]:
            raise ValueError("bounded repetition required")
        slot = (case.name, arm.name, rep)
        if slot in seen: raise ValueError("duplicate result slot")
        seen.add(slot)
        messages, rid = render(case, arm, rep)
        if (row.get("split") != case.split or row.get("messages") != messages
                or row.get("prompt_sha256") != content_hash(messages) or row.get("request_id") != rid):
            raise ValueError("result differs from frozen prompt/slot")
        raw, meta = row.get("response"), row.get("metadata", {})
        if type(meta) is not dict: raise ValueError("response metadata required")
        observed = {"case": case.name, "arm": arm.name, "split": case.split, "repetition": rep,
                    "strict_success": None, "exact_tactic_diagnostic": None, "client_bound": False,
                    "request_id_mismatch": False}
        if raw is not None:
            if not isinstance(raw, str) or len(raw.encode()) > 65536 or row.get("response_sha256") != source_hash(raw):
                raise ValueError("bounded matching response hash required")
            check_binding(meta.get("client_binding"), messages, arm, raw)  # Both arms for this comparison.
            parsed = parse_response(raw, arm, rid, meta.get("finish_reason"))
            observed.update(client_bound=True, strict_success=bool(parsed["strict_contract"] and parsed["tactic"] == case.expected))
            try: obj = strict_json(raw)
            except ValueError: obj = None
            observed["exact_tactic_diagnostic"] = type(obj) is dict and obj.get("tactic") == case.expected
            observed["request_id_mismatch"] = arm.contract == "json" and type(obj) is dict and obj.get("request_id") != rid
        rows.append(observed)
    expected = {(c, a, r) for c in cases for a in arms for r in range(plan["repetitions"])}
    groups = []
    for split in ("development", "confirmation"):
        for arm in arms.values():
            own = [r for r in rows if r["split"] == split and r["arm"] == arm.name]
            groups.append({"split": split, "arm": arm.name, "declared_contract": arm.contract,
                "attempts": len(own), "unmeasured": sum(r["strict_success"] is None for r in own),
                "client_bound_responses": sum(r["client_bound"] for r in own),
                "strict_successes_under_declared_contract": sum(r["strict_success"] is True for r in own),
                "exact_tactics_ignoring_envelope_diagnostic_only": sum(r["exact_tactic_diagnostic"] is True for r in own),
                "wrong_echoed_request_ids": sum(r["request_id_mismatch"] for r in own) if arm.contract == "json" else None})
    return {"schema": REPORT_SCHEMA, "source_plan_id": report["plan_id"], "groups": groups, "rows": rows,
        "complete": seen == expected and all(r["strict_success"] is not None for r in rows),
        "confirmation_used_for_selection": False, "prior_scores_changed": False, "promotion": False,
        "native_quality_established": False, "client_binding_is_authentication": False,
        "warning": "Different predeclared output contracts: workflow compliance is not a common-schema score or improved proof reasoning. Tactic-field inspection is diagnostic only."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    with args.report.open("rb") as stream: report = strict_json(stream.read(16_777_217), limit=16_777_216)
    study = request_id_study(report, seed=args.seed)
    with args.output.open("x") as stream:
        json.dump(study, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"study": str(args.output), "sha256": content_hash(study),
                      "planned_calls": study["limits"]["max_calls"], "model_calls": 0, "promotion": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
