#!/usr/bin/env python3
"""Eight-call, single-task prompt pilots; generation never executes drafts.

Explicitly reviewed --triage uses the existing native verifier. Performance
confirmation uses arena_trial. Neither is held-out selection or an Arena score.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "papers/completion/lean_refactor_arena/harness"))

from jevops import leanstral, llm_router
from jevops.arena import content_hash, intake_error, reference_tokens, source_hash
from jevops.arena_lean import CORPUS
from jevops.arena_prepare import exclusive, validate_volume
from jevops.arena_trial import Candidate
from jevops.arena_providers import strict_json
from jevops.lean import VersionPin
from jevops.leanstral_prompt_lab import Arm, Case, EOS, arena_case, parse_response, render
from jevops.proof_slicing import apply_deletion_span, deletion_spans
from jevops.refactor_prompts import RefactorPrompts
import run_warmup

SEED = 43
PROBLEM = "Core.InitsUpdatesComm"


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def make_plan():
    records = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    record = next(r for r in records if r["name"] == PROBLEM)
    evidence = ROOT / "papers/completion/lean_refactor_arena/evidence"
    failed = evidence / "native-controlled-core-2026-09-22.json"
    repaired = evidence / "native-controlled-core-repair-2026-09-22.json"
    retrieval = run_warmup.lra_retrieve.retrieve_record(record, records)
    legacy = run_warmup.render_loop_prompt(record, retrieval)
    arms = {"legacy": {"prompt": legacy, "manifest": {"template": "legacy", "prompt_sha256": source_hash(legacy)}}}
    for name, template, history in (("repair-no-history", "repair", ()),
            ("repair-failures", "repair", (failed,)), ("contrastive-history", "contrastive", (failed, repaired))):
        bundle = RefactorPrompts(template, history_files=history, max_chars=18000,
            max_examples=2, max_observations=2).build(record,
                available_lemmas=tuple(item.name for item in retrieval.src_lemmas))
        arms[name] = {"prompt": bundle.text, "manifest": bundle.manifest}
    rng, schedule = random.Random(SEED), []
    for repetition in range(2):
        names = list(arms); rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + index, "arm": name, "repetition": repetition}
                         for index, name in enumerate(names)])
    paths = [Path(__file__), Path(run_warmup.__file__), *[ROOT / "jevops" / name for name in
        ("refactor_prompts.py", "leanstral.py", "llm_router.py", "leanstral_prompt_lab.py", "arena.py")]]
    plan = {"schema": "jevops-refactor-template-pilot/v1", "record": record, "arms": arms, "schedule": schedule,
        "seed": SEED, "task_split": "exploratory-public-warmup-not-held-out",
        "history_cutoff": {str(p.relative_to(ROOT)): source_hash(p.read_text()) for p in (failed, repaired)},
        "settings": {"provider": "leanstral_local", "model_name": "Leanstral", "base_url": leanstral.BASE_URL,
            "max_new_tokens": 1024, "timeout": 120, "temperature": 0, "stop": ["<|im_end|>"]},
        "max_model_calls": 8, "max_output_tokens_total": 8192,
        "native_protocol": {"runner": "jevops.arena_trial", "all_required_pins": True,
            "both_branch_orders": True, "repetitions": 2, "max_requests": 108,
            "deduplicate_source_bytes": True, "fresh_receipts": True,
            "confirmation": "separate fixed-candidate run if screening finds a dual improvement"},
        "implementation": {str(p.relative_to(ROOT)): source_hash(p.read_text()) for p in paths},
        "automatic_execution": False, "training": False, "promotion": False, "official_score": None}
    return {**plan, "plan_id": content_hash(plan)}


def make_contract_plan():
    """Matched 2x2 roles/output-contract pilot, not a held-out selection."""
    records = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    record = next(r for r in records if r["name"] == PROBLEM)
    retrieval = run_warmup.lra_retrieve.retrieve_record(record, records)
    case = arena_case(record, context="Available premise names (hints, not proof):\n" +
                      "\n".join(item.name for item in retrieval.src_lemmas))
    arms = {}
    for roles in ("user", "system_user"):
        for contract in ("tactic", "json"):
            arm = Arm(roles.replace("_", "-") + "-" + contract, contract=contract,
                      roles=roles, stop=("<|im_end|>",))
            requests = []
            for repetition in range(2):
                messages, request_id = render(case, arm, repetition)
                requests.append({"messages": messages, "request_id": request_id})
            arms[arm.name] = {"arm": asdict(arm), "requests": requests}
    seed, schedule = 53, []
    rng = random.Random(seed)
    for repetition in range(2):
        names = list(arms); rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + index, "arm": name, "repetition": repetition}
                         for index, name in enumerate(names)])
    paths = [Path(__file__), Path(run_warmup.__file__), *[ROOT / "jevops" / name for name in
        ("lean.py", "leanstral.py", "llm_router.py", "leanstral_prompt_lab.py", "refactor_prompts.py",
         "arena.py", "arena_lean.py")]]
    plan = {"schema": "jevops-refactor-contract-pilot/v1", "record": record, "arms": arms,
        "schedule": schedule, "seed": seed, "task_split": "exploratory-public-warmup-not-held-out",
        "case": asdict(case), "history": [], "factors": ["message_roles", "response_contract"],
        "settings": {"provider": "leanstral_local", "model_name": "Leanstral", "base_url": leanstral.BASE_URL,
            "max_new_tokens": 1024, "timeout": 120, "temperature": 0, "stop": ["<|im_end|>"]},
        "max_model_calls": 8, "max_output_tokens_total": 8192,
        "native_protocol": {"review_required": True, "all_required_pins": True,
            "pin_order": sorted(tag for row in record["version_info"] for tag in row),
            "controls_per_pin": 1, "candidate_attempts_per_pin": 1, "branch_order": "reference-first",
            "max_requests": 27, "stop_candidate_after_first_non_verified": True,
            "remaining_pins": "NOT_RUN_AFTER_NON_SUCCESS", "cache_entries": 0,
            "purpose": "validity triage only, not performance selection",
            "confirmation": "fresh arena_trial both orders, two repetitions, if all pins verify and tokens decrease"},
        "implementation": {str(p.relative_to(ROOT)): source_hash(p.read_text()) for p in paths},
        "automatic_execution": False, "training": False, "promotion": False, "official_score": None}
    return {**plan, "plan_id": content_hash(plan)}


def make_output_budget_plan():
    """Cross contract wording with output allowance; same case/roles/parser."""
    plan = make_contract_plan()
    plan.pop("plan_id")
    case = Case(**plan["case"])
    arms = {}
    for style in ("placeholder", "descriptive"):
        for tokens in (1024, 3072):
            arm = Arm(f"{style}-{tokens}", contract="json", roles="system_user",
                      stop=("<|im_end|>",), json_contract_style=style)
            requests = []
            for repetition in range(2):
                messages, request_id = render(case, arm, repetition)
                requests.append({"messages": messages, "request_id": request_id})
            arms[arm.name] = {"arm": asdict(arm), "requests": requests,
                              "settings": {"max_new_tokens": tokens}}
    seed, schedule = 67, []
    rng = random.Random(seed)
    for repetition in range(2):
        names = list(arms); rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + index, "arm": name, "repetition": repetition}
                         for index, name in enumerate(names)])
    plan.update(schema="jevops-refactor-output-budget-pilot/v1", arms=arms, schedule=schedule, seed=seed,
        factors=["json_contract_wording", "output_token_allowance"],
        settings={**plan["settings"], "timeout": 300}, max_output_tokens_total=16384,
        min_declared_context_per_slot=8192,
        analysis_protocol={"primary": "all-pin verified refactors; then fresh performance confirmation",
            "secondary": ["strict format compliance", "intake acceptance", "truncation", "measured token usage"],
            "parser": "unchanged strict JSON request binding; no repair or fence salvage",
            "wording_contrast": "placeholder example versus verbal field specification",
            "equal_request_counts": True, "equal_token_allowances_between_budget_arms": False,
            "independent_samples_claimed": False})
    return {**plan, "plan_id": content_hash(plan)}


def make_local_edit_plan():
    """Whole body versus one existing local deletion, same context and budget."""
    plan = make_contract_plan()
    plan.pop("plan_id")
    record = plan["record"]
    body = record["src"][len(record["statement"] + " := by\n"):]
    spans = deletion_spans(record["src"], record["statement"])
    numbered = [{"line": i, "text": line} for i, line in enumerate(body.splitlines(), 1)]
    case = replace(Case(**plan["case"]), instruction=
        "Shorten the existing Lean proof without changing its statement, dependencies or axioms. "
        "Reduce proof tokens and elaboration heartbeats. Do not move work into helpers or change limits. "
        "Propose one refactoring; the output action and format are specified separately.",
        context=plan["case"]["context"] + "\n" + json.dumps({"body_lines": numbered,
            "allowed_delete_lines_inclusive": spans, "spans_are_unverified_edits_not_redundancy_claims": True},
            ensure_ascii=False))
    arms = {}
    for mode in ("whole-body", "delete-span"):
        arm = Arm(mode, contract="json", roles="system_user", stop=("<|im_end|>",),
                  json_contract_style="descriptive")
        requests = []
        for repetition in range(4):
            messages, request_id = render(case, arm, repetition)
            if mode == "delete-span":
                contract = ('Return ONLY one JSON object with exactly two fields. Set request_id to "' +
                    request_id + '". Set delete_lines to an array of two integers: the first and last '
                    'BODY line to delete, 1-based inclusive. Choose exactly one pair from '
                    'allowed_delete_lines_inclusive. All other proof bytes will remain unchanged. '
                    'No tactic text, fences, explanations or extra fields.')
                messages[0]["content"] = messages[0]["content"].rsplit("\n", 1)[0] + "\n" + contract
            requests.append({"messages": messages, "request_id": request_id})
        arms[mode] = {"arm": asdict(arm), "requests": requests, "action": mode}
    seed, schedule = 79, []
    rng = random.Random(seed)
    for repetition in range(4):
        names = list(arms); rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + i, "arm": name, "repetition": repetition}
                         for i, name in enumerate(names)])
    plan.update(schema="jevops-refactor-local-edit-pilot/v1", arms=arms, schedule=schedule, seed=seed,
        case=asdict(case), factors=["whole_body_vs_source_bound_deletion"],
        settings={**plan["settings"], "timeout": 180}, min_declared_context_per_slot=8192,
        allowed_delete_lines_inclusive=spans, max_output_tokens_total=8192)
    for name in ("proof_slicing.py", "arena_snapshot.py", "arena_providers.py"):
        plan["implementation"]["jevops/" + name] = source_hash((ROOT / "jevops" / name).read_text())
    return {**plan, "plan_id": content_hash(plan)}


def make_deletion_order_plan():
    """Matched presentation order only: never reorder executable Lean tactics.

    The output contract moves within the USER message in every arm; this is
    not an exact rerun of the older system-contract treatment. Request nonces
    are paired across arms for the same immutable task and repetition.
    """
    plan = make_local_edit_plan()
    plan.pop("plan_id")
    baseline = plan["arms"]["delete-span"]
    reference_context, edit_json = plan["case"]["context"].rsplit("\n", 1)
    arms = {}
    for position in ("before", "after"):
        for order in ("forward", "reverse"):
            name = f"{position}-{order}"
            data = json.loads(edit_json)
            if order == "reverse":
                data["allowed_delete_lines_inclusive"].reverse()
            context = reference_context + "\n" + json.dumps(data, ensure_ascii=False)
            requests = []
            for original in baseline["requests"][:2]:
                instruction, contract = original["messages"][0]["content"].rsplit("\n", 1)
                request_id = original["request_id"]
                observed = f"Request: {request_id}\n<context>\n{context}\n</context>"
                blocks = (contract, observed) if position == "before" else (observed, contract)
                requests.append({"request_id": request_id, "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": "\n".join(blocks)}]})
            arms[name] = {"arm": {**baseline["arm"], "name": name}, "requests": requests,
                          "action": "delete-span", "contract_position": position, "span_order": order}
    seed, schedule = 97, []
    rng = random.Random(seed)
    for repetition in range(2):
        names = list(arms)
        rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + i, "arm": name, "repetition": repetition}
                         for i, name in enumerate(names)])
    plan.update(schema="jevops-refactor-deletion-order-pilot/v1", arms=arms, schedule=schedule, seed=seed,
        factors=["user_contract_before_vs_after_context", "allowed_span_forward_vs_reverse"],
        analysis_protocol={"primary": "strict response contract compliance and admitted deletion actions",
            "secondary": ["fresh all-pin verification", "measured token usage", "truncation", "wall time"],
            "fixed": ["source bytes", "numbered proof lines", "allowed span set", "contract wording",
                      "system instructions", "user contract role", "parser", "model settings", "budgets"],
            "history": "no past responses, failures, repairs or winning edits supplied",
            "reference_comparison": "previous system-contract pilot is descriptive only, not a matched control",
            "independent_samples_claimed": False, "semantic_tactic_reordering": False,
            "native_gate": "only reviewed exact sources from admitted actions; no malformed-response salvage",
            "performance_gate": "fresh order-balanced confirmation only after shorter all-pin-valid drafts"})
    return {**plan, "plan_id": content_hash(plan)}


def deletion_catalog(record):
    """Stable numbered actions bound to the entire record, not display position."""
    spans = deletion_spans(record["src"], record["statement"])
    if not spans:
        raise ValueError("no supported deletion actions")
    return {"schema": "jevops-source-bound-deletion-catalog/v1", "record_sha256": content_hash(record),
            "source_sha256": source_hash(record["src"]),
            "entries": [{"edit_id": i, "delete_lines": list(span)} for i, span in enumerate(spans, 1)]}


def make_deletion_id_plan():
    """Contract-last endpoint versus ID selection, matched catalog and actions."""
    plan = make_local_edit_plan()
    plan.pop("plan_id")
    baseline = plan["arms"]["delete-span"]
    reference_context, edit_json = plan["case"]["context"].rsplit("\n", 1)
    data = json.loads(edit_json)
    data.pop("allowed_delete_lines_inclusive")
    catalog = deletion_catalog(plan["record"])
    data["edit_catalog"] = catalog
    canonical_context = reference_context + "\n" + json.dumps(data, ensure_ascii=False)
    case = replace(Case(**plan["case"]), context=canonical_context)
    arms = {}
    for output in ("endpoints", "ids"):
        for order in ("forward", "reverse"):
            name = f"{output}-{order}"
            displayed = json.loads(json.dumps(data))
            if order == "reverse":
                displayed["edit_catalog"]["entries"].reverse()
            context = reference_context + "\n" + json.dumps(displayed, ensure_ascii=False)
            requests = []
            arm = Arm(**{**baseline["arm"], "name": name})
            for repetition in range(2):
                messages, request_id = render(case, arm, repetition)
                instruction = messages[0]["content"].rsplit("\n", 1)[0]
                choice = ('Set delete_lines to the two-integer delete_lines array of exactly one entry '
                          'in edit_catalog.entries. Endpoints are BODY lines, 1-based inclusive.' if output == "endpoints" else
                          'Set edit_id to the integer edit_id of exactly one entry in edit_catalog.entries. '
                          'Use its printed ID, not its display position. Its delete_lines array determines the deletion.')
                contract = ('Return ONLY one JSON object with exactly two fields. Set request_id to "' +
                    request_id + '". ' + choice + ' All other proof bytes will remain unchanged. '
                    'No tactic text, fences, explanations or extra fields.')
                requests.append({"request_id": request_id, "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": f"Request: {request_id}\n<context>\n{context}\n</context>\n{contract}"}]})
            arms[name] = {"arm": asdict(arm), "requests": requests,
                          "action": "delete-span" if output == "endpoints" else "delete-id",
                          "span_order": order, "contract_position": "after",
                          "catalog_sha256": content_hash(catalog)}
    seed, schedule = 109, []
    rng = random.Random(seed)
    for repetition in range(2):
        names = list(arms)
        rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + i, "arm": name, "repetition": repetition}
                         for i, name in enumerate(names)])
    plan.update(schema="jevops-refactor-deletion-id-pilot/v1", arms=arms, schedule=schedule, seed=seed,
        case=asdict(case), edit_catalog=catalog, catalog_sha256=content_hash(catalog),
        factors=["endpoint_array_vs_numbered_edit_id", "catalog_forward_vs_reverse"],
        analysis_protocol={"primary": "strict contract compliance and admitted edit selection",
            "secondary": ["fresh all-pin verification", "measured token usage", "wall time"],
            "fixed": ["reference bytes", "allowed deletions", "catalog contents", "contract-last placement",
                      "system instructions", "model settings", "budgets", "native verification protocol"],
            "matched_context": "identical for endpoint/ID arms within each display order",
            "ids": "stable canonical catalog IDs, independent of displayed order; no best-edit labels",
            "history": "no previous responses, diagnostics or successful edits supplied",
            "grammar_constrained_decoding": False, "independent_samples_claimed": False,
            "native_gate": "fresh exact-source review and verification; no malformed-response salvage",
            "performance_gate": "separate fresh order-balanced confirmation only for shorter all-pin-valid drafts"})
    return {**plan, "plan_id": content_hash(plan)}


def deletion_rejection_feedback(record, previous, native_plan, native):
    """Adapt saved triage to the existing history checker; never admit evidence.

    Reconstruct source/context/request bindings and deduplicate observations.
    Historical dependency identities remain historical, not current cache hits.
    """
    from jevops.refactor_prompts import _examples, _load
    catalog = deletion_catalog(record)
    if (previous.get("schema") != "jevops-refactor-deletion-id-pilot/v1" or
            previous.get("plan_id") != content_hash({k: v for k, v in previous.items() if k != "plan_id"}) or
            content_hash(previous.get("record")) != content_hash(record) or
            previous.get("catalog_sha256") != content_hash(catalog) or
            content_hash(previous.get("edit_catalog")) != content_hash(catalog)):
        raise ValueError("matching historical record/catalog/plan required")
    if (native.get("schema") != "jevops-prompt-validity-triage/v1" or native.get("status") != "COMPLETE" or
            any(doc.get("plan_id") != previous["plan_id"] for doc in (native_plan, native)) or
            any(doc.get("generation_plan_id") != previous["plan_id"] for doc in (native_plan, native)) or
            native_plan.get("protocol") != previous["native_protocol"] or
            native_plan.get("execution") != "trusted-local-private-scratch-not-OS-sandbox"):
        raise ValueError("matching completed native history required")
    candidates, contexts, rows = native_plan.get("candidates"), native.get("contexts"), native.get("rows")
    if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 8 or
            not isinstance(contexts, dict) or not 1 <= len(contexts) <= 16 or
            not isinstance(rows, list) or len(rows) > 64):
        raise ValueError("bounded native history required")
    arms = [asdict(Candidate("control", record["src"], "historical reference control"))]
    for candidate in candidates:
        if (not isinstance(candidate, dict) or set(candidate) != {"name", "label", "source", "provenance"} or
                candidate["name"] != record["name"]):
            raise ValueError("historical candidate target mismatch")
        arms.append(asdict(Candidate(**{k: candidate[k] for k in ("label", "source", "provenance")})))
    if set(native_plan.get("reviewed_source_sha256", [])) != {source_hash(c["source"]) for c in candidates}:
        raise ValueError("historical source review mismatch")
    samples = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("typed historical row required")
        if row.get("status") == "NOT_RUN_AFTER_NON_SUCCESS":
            if row.get("receipt") is not None:
                raise ValueError("unrun history cannot carry a receipt")
            continue
        if row.get("status") == "REJECTED":
            report = _load(row.get("receipt", {}).get("observations_json", "{}")).get("report", {})
            if report.get("outcome") != "REJECTED" or not report.get("diagnostics"):
                raise ValueError("native rejection requires reported rejection diagnostics")
        samples.append({**row, "version": row["pin"],
                        "branch_order": previous["native_protocol"]["branch_order"]})
    # Reuse context, source, pin, request, measurement, diagnostic and duplicate checks.
    examples = _examples({"record": record, "evidence_mode": "local_lean", "arms": arms,
                          "contexts": list(contexts.values()), "samples": samples})
    by_source = {}
    for entry in catalog["entries"]:
        source = apply_deletion_span(record["src"], record["statement"], *entry["delete_lines"],
                                     expected_source_sha256=catalog["source_sha256"])
        by_source.setdefault(source_hash(source), []).append(entry["edit_id"])
    observations = {}
    for example in examples:
        ids = by_source.get(example["source_sha256"])
        if ids is None:
            raise ValueError("historical source is not an exact catalog deletion")
        for observation in example["observations"]:
            if observation["outcome_reported"] != "REJECTED":
                continue  # Infrastructure failures never become semantic negatives.
            item = {"edit_ids": ids, "candidate_sha256": example["source_sha256"],
                    **{k: observation[k] for k in ("outcome_reported", "version", "context_id", "request_id",
                        "dependency_digest", "verifier_id", "verifier_version", "reason")},
                    "diagnostics": [{"message": d["message"][:1000],
                                     "truncated": d["truncated"] or len(d["message"]) > 1000}
                                    for d in observation.get("diagnostics", [])[:1]],
                    "diagnostics_omitted": observation.get("diagnostics_omitted", 0) +
                                           max(0, len(observation.get("diagnostics", [])) - 1)}
            observations[content_hash(item)] = item
    if not 1 <= len(observations) <= 8:
        raise ValueError("one to eight bound semantic rejection observations required")
    return {"schema": "jevops-deletion-rejection-hints/v1", "source_plan_id": previous["plan_id"],
            "catalog_sha256": content_hash(catalog),
            "observations": sorted(observations.values(), key=lambda o: (o["edit_ids"], o["version"]["lean_tag"])),
            "authority": "Internally checked saved observations, not authenticated or current proof evidence. "
                         "Rejection concerns this exact candidate/context, not falsity of the target. Reverify every proposal.",
            "history_authenticated": False, "fresh_verification_required": True, "prune_actions": False}


def load_deletion_feedback(record, directory, manifest_sha256):
    """Read only three explicit, byte-bounded files pinned by an external hash."""
    import hashlib
    from jevops.refactor_prompts import MAX_FILE_BYTES, _load
    def read(name):
        path = directory / name
        if directory.is_symlink() or path.is_symlink():
            raise ValueError("feedback symlinks are not allowed")
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("feedback file byte limit")
        return raw
    raw = read("archive-manifest.json")
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise ValueError("feedback manifest identity mismatch")
    manifest = _load(raw)
    if manifest.get("schema") != "jevops-experiment-evidence-archive/v1":
        raise ValueError("feedback archive schema mismatch")
    documents, bindings = [], {}
    for name in ("plan.json", "native-plan.json", "native-triage.json"):
        raw = read(name)
        expected = manifest["files"][name]
        if hashlib.sha256(raw).hexdigest() != expected["sha256"] or len(raw) != expected["bytes"]:
            raise ValueError("feedback artifact identity mismatch")
        bindings[name] = expected
        documents.append(_load(raw))
    return deletion_rejection_feedback(record, *documents), {
        "manifest_sha256": manifest_sha256, "files": bindings,
        "scope": "only the three named files checked; other archive entries are not consumed"}


def make_deletion_feedback_plan(history_directory, manifest_sha256):
    plan = make_deletion_id_plan()
    plan.pop("plan_id")
    feedback, binding = load_deletion_feedback(plan["record"], history_directory, manifest_sha256)
    canonical = Case(**plan["case"])
    canonical = replace(canonical, instruction=canonical.instruction +
        " Use any supplied historical rejection diagnostics to choose an alternative to an unsuccessful "
        "unchanged edit. These observations are hints, not verification of a new proposal.")
    reference, encoded = canonical.context.rsplit("\n", 1)
    base = json.loads(encoded)
    # Paired nonce includes the feedback identity, even in the no-feedback arm.
    nonce_case = replace(canonical, context=canonical.context + "\n" + json.dumps(feedback, ensure_ascii=False))
    arms = {}
    for supplied in (False, True):
        for order in ("forward", "reverse"):
            name = ("feedback" if supplied else "no-feedback") + "-" + order
            template = plan["arms"]["ids-" + order]
            arm = Arm(**{**template["arm"], "name": name})
            data = json.loads(json.dumps(base))
            if order == "reverse":
                data["edit_catalog"]["entries"].reverse()
            data["historical_rejections"] = {**feedback, "observations": feedback["observations"] if supplied else []}
            context = reference + "\n" + json.dumps(data, ensure_ascii=False)
            requests = []
            for repetition in range(2):
                rendered, request_id = render(nonce_case, arm, repetition)
                prior = template["requests"][repetition]
                contract = prior["messages"][1]["content"].rsplit("\n</context>\n", 1)[1]
                contract = contract.replace(prior["request_id"], request_id)
                requests.append({"request_id": request_id, "messages": [
                    {"role": "system", "content": rendered[0]["content"].rsplit("\n", 1)[0]},
                    {"role": "user", "content": f"Request: {request_id}\n<context>\n{context}\n</context>\n{contract}"}]})
            arms[name] = {**template, "arm": asdict(arm), "requests": requests, "feedback_supplied": supplied}
    seed, schedule = 127, []
    rng = random.Random(seed)
    for repetition in range(2):
        names = list(arms)
        rng.shuffle(names)
        schedule.extend([{"slot": len(schedule) + i, "arm": name, "repetition": repetition}
                         for i, name in enumerate(names)])
    plan.update(schema="jevops-refactor-deletion-feedback-pilot/v1", arms=arms, schedule=schedule, seed=seed,
        feedback=feedback, feedback_binding=binding, case=asdict(nonce_case),
        factors=["historical_rejections_present_vs_absent", "catalog_forward_vs_reverse"],
        analysis_protocol={"primary": "fresh all-pin-valid edits and avoidance of previously rejected exact sources",
            "secondary": ["strict format", "admitted ID selection", "measured token usage", "wall time"],
            "fixed": ["source bytes", "all 64 allowed edits", "stable IDs", "contract-last wording", "model settings", "budgets"],
            "feedback": "historical rejections only, never proof authority or automatic pruning; no winning examples",
            "unequal_prompt_lengths": True, "independent_samples_claimed": False,
            "native_gate": "fresh reviewed checks, including repeated sources; historical receipts not reused",
            "performance_gate": "separate fresh order-balanced confirmation only for shorter all-pin-valid drafts"})
    return {**plan, "plan_id": content_hash(plan)}


def parse_deletion(raw, request_id, finish_reason, record, *, action="delete-span", expected_catalog_sha256=None):
    if action not in ("delete-span", "delete-id"):
        raise ValueError("unknown deletion action")
    if not isinstance(raw, str) or len(raw.encode()) > 65536:
        return {"status": "response_byte_budget", "strict_contract": False}
    if finish_reason == "length":
        return {"status": "output_truncated", "strict_contract": False}
    value, removed = raw.strip(), []
    for _ in range(4):
        marker = next((m for m in EOS if value.endswith(m)), None)
        if marker is None: break
        removed.append(marker)
        value = value[:-len(marker)].rstrip()
    try:
        obj = strict_json(value)
        field = "delete_lines" if action == "delete-span" else "edit_id"
        if type(obj) is not dict or set(obj) != {"request_id", field} or obj["request_id"] != request_id:
            raise ValueError("contract")
        if ((action == "delete-id" and type(obj[field]) is not int) or
                (action == "delete-span" and (type(obj[field]) is not list or len(obj[field]) != 2 or
                                               any(type(n) is not int for n in obj[field])))):
            raise ValueError("contract")
    except (ValueError, TypeError):
        return {"status": "contract_mismatch", "strict_contract": False, "normalizations": removed}
    try:
        if action == "delete-id":
            catalog = deletion_catalog(record)
            if content_hash(catalog) != expected_catalog_sha256:
                raise ValueError("missing or stale deletion catalog identity")
            if not 1 <= obj["edit_id"] <= len(catalog["entries"]):
                raise ValueError("edit ID is outside the declared deletion catalog")
            endpoints = catalog["entries"][obj["edit_id"] - 1]["delete_lines"]
        else:
            endpoints = obj["delete_lines"]
        source = apply_deletion_span(record["src"], record["statement"], *endpoints,
                                     expected_source_sha256=source_hash(record["src"]))
    except ValueError as exc:
        return {"status": "edit_rejected", "strict_contract": not removed,
                "edit": obj, "edit_error": str(exc), "normalizations": removed}
    binding = ({"resolved_delete_lines": endpoints, "catalog_sha256": expected_catalog_sha256}
               if action == "delete-id" else {})
    return {**binding, "status": "eos_artifact" if removed else "parsed", "strict_contract": not removed,
            "edit": obj, "source": source, "normalizations": removed}


def slot_settings(plan, slot):
    overrides = plan["arms"][slot["arm"]].get("settings", {})
    if set(overrides) - {"max_new_tokens"}:
        raise ValueError("only the output allowance may vary per treatment")
    settings = {**plan["settings"], **overrides}
    tokens = settings["max_new_tokens"]
    if type(tokens) is not int or not 1 <= tokens <= 32768:
        raise ValueError("bounded positive integer output allowance required")
    return settings


def generation_row(slot, prompt, record, settings, arm=None, request_id="unused-tactic-contract", action="whole-body",
                   catalog_sha256=None):
    start = time.monotonic()
    row = {**slot, "prompt_sha256": source_hash(prompt if isinstance(prompt, str) else
        json.dumps(prompt, sort_keys=True, ensure_ascii=False, allow_nan=False)),
        "native_verified": None, "official_score": None, "request_settings": settings}
    try:
        raw = (llm_router.generate_text(prompt, **settings) if isinstance(prompt, str) else
               llm_router.generate_text(None, messages=prompt, **settings))
        trace = llm_router.get_last_generation_trace()
        if (trace.get("fixture") is not False or trace.get("fallback_used") is not False or
                trace.get("response_model") not in leanstral.MODEL_ALIASES or
                trace.get("endpoint") != leanstral.endpoint(settings["base_url"])):
            raise ValueError("local route mismatch")
        row.update(raw=raw, raw_sha256=source_hash(raw), trace=trace)
        if action not in ("whole-body", "delete-span", "delete-id"):
            raise ValueError("unknown proposal action")
        parsed = (parse_deletion(raw, request_id, trace.get("finish_reason"), record, action=action,
                                expected_catalog_sha256=catalog_sha256) if action != "whole-body" else
                  parse_response(raw, arm or Arm("pilot"), request_id, trace.get("finish_reason")))
        row.update(parsed)
        source = parsed.get("source")
        if parsed.get("tactic") is not None:
            source = record["statement"] + " := by\n  " + parsed["tactic"].replace("\n", "\n  ")
        if source is not None:
            error = intake_error(source, record["statement"])
            row.update(source=source, source_sha256=source_hash(source), intake_error=error)
            if error:
                row["status"] = "intake_rejected"
            else:
                row["candidate_tokens_unverified"] = reference_tokens(source, record["statement"])
                row["exact_reference_bytes"] = source == record["src"]
    except Exception as exc:
        row.update(status="generation_error", error_type=type(exc).__name__, error=str(exc)[:500])
    row["wall_seconds"] = round(time.monotonic() - start, 4)
    return row


def run(directory, config, plan):
    if plan.get("generation_origin"):
        raise ValueError("verification-only epoch cannot make model calls")
    settings_by_slot = [slot_settings(plan, slot) for slot in plan["schedule"]]
    if (len(settings_by_slot) > plan["max_model_calls"] or
            sum(s["max_new_tokens"] for s in settings_by_slot) > plan["max_output_tokens_total"] or
            [s["slot"] for s in plan["schedule"]] != list(range(len(settings_by_slot)))):
        raise ValueError("invalid schedule or aggregate generation allowance")
    mount = validate_volume(config)
    if not directory.resolve().is_relative_to(mount) or directory.is_symlink():
        raise ValueError("output must be within the existing capped preparation volume")
    directory.mkdir(mode=0o700, exist_ok=True)
    if (directory / "plan.json").exists():
        if content_hash(json.loads((directory / "plan.json").read_text())) != content_hash(plan):
            raise ValueError("plan/code/history changed; use a new output directory")
    else:
        save(directory / "plan.json", plan)
    profile = leanstral.server_profile()
    required_context = plan.get("min_declared_context_per_slot")
    if required_context is not None and (type(profile.get("declared_context_per_slot")) is not int or
                                        profile["declared_context_per_slot"] < required_context):
        raise ValueError("required declared serving context unavailable; no model calls")
    if (directory / "server-profile.json").exists():
        if json.loads((directory / "server-profile.json").read_text()) != profile:
            raise ValueError("visible serving metadata changed")
    else:
        save(directory / "server-profile.json", profile)
    if leanstral.health_status("http://172.17.0.1:8080/health")[0] != 200:
        raise RuntimeError("local model unavailable; no generation, startup or fallback")
    rows = []
    for slot in plan["schedule"]:
        reservation = directory / f"slot-{slot['slot']:02d}-reserved.json"
        result = directory / f"slot-{slot['slot']:02d}-result.json"
        if result.exists():
            rows.append(json.loads(result.read_text())); continue
        if reservation.exists():
            rows.append({**slot, "status": "interrupted_unknown", "native_verified": None}); continue
        validate_volume(config)
        if shutil.disk_usage(directory).free < 64 * 1024**2:
            raise RuntimeError("insufficient capped storage headroom")
        if leanstral.server_profile() != profile:
            raise RuntimeError("visible serving metadata changed before a request")
        settings = settings_by_slot[slot["slot"]]
        save(reservation, {**slot, "plan_id": plan["plan_id"], "attempt_reserved": True,
                           "max_output_tokens_reserved": settings["max_new_tokens"]})
        treatment = plan["arms"][slot["arm"]]
        if "requests" in treatment:
            request = treatment["requests"][slot["repetition"]]
            spec = {**treatment["arm"], "context_layers": tuple(treatment["arm"]["context_layers"]),
                    "stop": tuple(treatment["arm"]["stop"])}
            row = generation_row(slot, request["messages"], plan["record"], settings,
                                 Arm(**spec), request["request_id"], treatment.get("action", "whole-body"),
                                 treatment.get("catalog_sha256"))
        else:
            row = generation_row(slot, treatment["prompt"], plan["record"], settings)
        save(result, row)
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("slot", "arm", "status", "candidate_tokens_unverified", "wall_seconds")}), flush=True)
    # Produce unverified trial artifacts only. No generated Lean executes here.
    seen = {plan["record"]["src"]: "control"}
    candidates = []
    for row in rows:
        source = row.get("source")
        if source is None or row.get("intake_error"):
            continue
        if source in seen:
            row["candidate_label"] = seen[source]
            continue
        label = f"draft-{len(candidates)}"
        seen[source] = label
        row["candidate_label"] = label
        candidate = Candidate(label, source, "unverified live Leanstral prompt pilot " + plan["plan_id"])
        payload = {"name": PROBLEM, **asdict(candidate)}
        path = directory / f"{label}.json"
        if path.exists():
            if json.loads(path.read_text()) != payload:
                raise ValueError("existing draft mismatch")
        else:
            save(path, payload)
        candidates.append(payload)
    report = {"schema": plan["schema"], "plan_id": plan["plan_id"], "rows": rows,
        "candidate_files": [c["label"] + ".json" for c in candidates],
        "requests_reserved": len(list(directory.glob("slot-*-reserved.json"))),
        "native_executions": 0, "paid_api_cost": None, "electricity_cost": None,
        "official_score": None, "policy_selected": False}
    if not (directory / "generation.json").exists():
        save(directory / "generation.json", report)
    print(json.dumps({"output": str(directory), "drafts": report["candidate_files"],
                      "requests_reserved": report["requests_reserved"], "native_executions": 0}), flush=True)


def verification_epoch(origin, directory, config, current_plan):
    """Import unverified proposals into a NEW native epoch, never resume one.

    Keep the original generation bytes/identity. Only implementation hashes may
    differ; changed tasks, settings or protocols need a different experiment.
    No generation or verification happens here. Source review remains required.
    """
    mount = validate_volume(config)
    if any(p.is_symlink() or not p.resolve().is_relative_to(mount) for p in (origin, directory)):
        raise ValueError("both epochs must be inside the capped volume")
    if origin.resolve() == directory.resolve() or (directory.exists() and any(directory.iterdir())):
        raise ValueError("verification epoch requires a new empty directory")
    previous = json.loads((origin / "plan.json").read_text())
    if previous.get("generation_origin") or previous["plan_id"] != content_hash(
            {k: v for k, v in previous.items() if k != "plan_id"}):
        raise ValueError("original generation plan identity required")
    stable = lambda p: {k: v for k, v in p.items() if k not in ("implementation", "plan_id")}
    if content_hash(stable(previous)) != content_hash(stable(current_plan)):
        raise ValueError("only code changes may be rebound; task/protocol/settings changed")
    generation = json.loads((origin / "generation.json").read_text())
    if generation["plan_id"] != previous["plan_id"]:
        raise ValueError("source generation identity mismatch")
    names = generation["candidate_files"]
    if len(names) > previous["max_model_calls"] or names != [f"draft-{i}.json" for i in range(len(names))]:
        raise ValueError("bounded generated candidate filenames required")
    copied = ["generation.json", *names]
    origin_info = {"plan_id": previous["plan_id"], "directory": str(origin.resolve()),
        "plan_sha256": source_hash((origin / "plan.json").read_text()),
        "copied_sha256": {name: source_hash((origin / name).read_text()) for name in copied},
        "verification_only": True, "new_model_calls": 0}
    plan = {k: v for k, v in current_plan.items() if k != "plan_id"}
    plan["generation_origin"] = origin_info
    plan["plan_id"] = content_hash(plan)
    directory.mkdir(mode=0o700, exist_ok=True)
    save(directory / "plan.json", plan)
    shutil.copyfile(origin / "plan.json", directory / "generation-plan.json")
    for name in copied:
        shutil.copyfile(origin / name, directory / name)
    return plan


def triage(directory, config, plan, projects, elan_home, reviewed):
    """Explicitly reviewed drafts only; fresh validity receipts, no score claim.

    No resume: reserving the native plan prevents accidental repeats even after
    interruption. Individual receipts are fsynced immediately for inspection.
    The caller owns the shared preparation lock. This is NOT an OS sandbox.
    """
    from jevops.arena import Outcome, VerificationRequest
    from jevops.arena_lean import NativeLeanVerifier, project_binding
    from jevops.seals import Fingerprinter

    mount = validate_volume(config)
    if not directory.resolve().is_relative_to(mount) or directory.is_symlink():
        raise ValueError("triage output must be within the capped volume")
    if plan["schema"] not in ("jevops-refactor-contract-pilot/v1", "jevops-refactor-output-budget-pilot/v1",
                              "jevops-refactor-local-edit-pilot/v1", "jevops-refactor-deletion-order-pilot/v1",
                              "jevops-refactor-deletion-id-pilot/v1", "jevops-refactor-deletion-feedback-pilot/v1"):
        raise ValueError("fail-fast triage requires the contract pilot protocol")
    # JSON canonicalization also makes tuple/list round trips comparable.
    if content_hash(json.loads((directory / "plan.json").read_text())) != content_hash(plan):
        raise ValueError("generation plan/code changed; do not mix contexts")
    generation = json.loads((directory / "generation.json").read_text())
    origin_info = plan.get("generation_origin")
    expected_generation_id = origin_info["plan_id"] if origin_info else plan["plan_id"]
    if origin_info:
        if source_hash((directory / "generation-plan.json").read_text()) != origin_info["plan_sha256"]:
            raise ValueError("original generation plan changed")
        for name, digest in origin_info["copied_sha256"].items():
            if source_hash((directory / name).read_text()) != digest:
                raise ValueError("imported generation artifact changed")
    if generation["plan_id"] != expected_generation_id:
        raise ValueError("generation plan mismatch")
    rows_by_label = {r.get("candidate_label"): r for r in generation["rows"] if r.get("source")}
    candidates = []
    if len(generation["candidate_files"]) > plan["max_model_calls"]:
        raise ValueError("candidate budget exceeded")
    for index, name in enumerate(generation["candidate_files"]):
        if name != f"draft-{index}.json":
            raise ValueError("unexpected candidate filename")
        draft = json.loads((directory / name).read_text())
        row = rows_by_label.get(draft["label"], {})
        if (draft["name"] != plan["record"]["name"] or row.get("source") != draft["source"] or
                row.get("source_sha256") != source_hash(draft["source"]) or
                intake_error(draft["source"], plan["record"]["statement"])):
            raise ValueError("candidate differs from admitted generation")
        candidates.append(draft)
    if not candidates:
        raise ValueError("no admissible drafts; no native work required")
    if set(reviewed) != {source_hash(c["source"]) for c in candidates}:
        raise ValueError("explicit review of every exact generated source required")
    native_plan = {"plan_id": plan["plan_id"], "protocol": plan["native_protocol"],
        "generation_plan_id": expected_generation_id,
        "candidates": candidates, "reviewed_source_sha256": sorted(reviewed), "projects": projects,
        "elan_home": str(elan_home),
        "execution": "trusted-local-private-scratch-not-OS-sandbox", "resume": False}
    save(directory / "native-plan.json", native_plan)  # At most one triage invocation.
    reader, rows, contexts = Fingerprinter(), [], {}
    stopped, control_failed, requests, processes = set(), False, 0, 0
    for tag in plan["native_protocol"]["pin_order"]:
        validate_volume(config)
        commit = next(row[tag] for row in plan["record"]["version_info"] if tag in row)
        pin = VersionPin(tag, commit)
        selected = {**plan["record"], "version_info": [{tag: commit}]}
        print(json.dumps({"native_setup": tag}), flush=True)
        project = next(p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                       (selected["url"], tag, commit))
        verifier = NativeLeanVerifier({pin: project_binding(selected, pin, project, elan_home)},
            max_processes=1 + len(candidates), timeout=90, fingerprinter=reader)
        ctx = verifier.context(selected)
        contexts[tag] = asdict(ctx)
        for candidate in [{"label": "control", "source": selected["src"]}, *candidates]:
            label = candidate["label"]
            row = {"pin": pin.to_dict(), "label": label, "source_sha256": source_hash(candidate["source"])}
            if control_failed or label in stopped:
                row["status"] = "NOT_RUN_AFTER_NON_SUCCESS"
            else:
                validate_volume(config)
                if requests >= plan["native_protocol"]["max_requests"]:
                    raise ValueError("native request budget exhausted")
                request = VerificationRequest(ctx, candidate["source"], pin)
                start = time.monotonic()
                previous_processes = verifier.processes
                receipt = verifier(request)
                requests += 1
                processes += verifier.processes - previous_processes
                row.update(status=receipt.outcome.value, receipt=asdict(receipt), context_id=ctx.context_id,
                           wall_seconds=round(time.monotonic() - start, 4))
                if receipt.outcome != Outcome.VERIFIED:
                    if label == "control": control_failed = True
                    else: stopped.add(label)
            save(directory / f"native-{tag}-{label}.json", row)
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("pin", "label", "status")}), flush=True)
    report = {"schema": "jevops-prompt-validity-triage/v1", "plan_id": plan["plan_id"],
        "generation_plan_id": expected_generation_id,
        "status": "CONTROL_FAILED" if control_failed else "COMPLETE", "rows": rows, "contexts": contexts,
        "native_requests": requests, "native_processes": processes,
        "all_pin_verified_candidates": [c["label"] for c in candidates if all(
            r["status"] == "VERIFIED" for r in rows if r["label"] == c["label"])],
        "performance_selected": False, "promotion": False, "official_score": None,
        "fingerprint_file_reads": reader.reads, "fingerprint_stat_hits": reader.stat_hits}
    save(directory / "native-triage.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("--generate", action="store_true")
    operations.add_argument("--triage", action="store_true")
    parser.add_argument("--study", choices=("templates", "contracts", "output-budget", "local-edits", "deletion-order", "deletion-ids", "deletion-feedback"), default="templates")
    parser.add_argument("--feedback-history", type=Path, help="explicit previous ID-pilot evidence directory")
    parser.add_argument("--feedback-manifest-sha256", help="externally pinned history archive manifest SHA-256")
    parser.add_argument("--snapshot-manifest-sha256", help="require this read-only source snapshot identity")
    parser.add_argument("--preparation-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--elan-home", type=Path)
    parser.add_argument("--reviewed-source-sha256", action="append", default=[])
    parser.add_argument("--recheck-generation", type=Path,
                        help="triage only: import unchanged drafts into a new empty verification epoch")
    args = parser.parse_args()
    if args.study == "deletion-feedback" and (args.feedback_history is None or not args.feedback_manifest_sha256):
        parser.error("deletion feedback requires explicit history and manifest identity")
    plan = {"templates": make_plan, "contracts": make_contract_plan,
            "output-budget": make_output_budget_plan, "local-edits": make_local_edit_plan,
            "deletion-order": make_deletion_order_plan, "deletion-ids": make_deletion_id_plan,
            "deletion-feedback": lambda: make_deletion_feedback_plan(args.feedback_history, args.feedback_manifest_sha256)}[args.study]()
    if args.snapshot_manifest_sha256:
        from jevops.arena_snapshot import verify_snapshot
        binding = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
        if any(getattr(module, "__file__", None) and not Path(module.__file__).resolve().is_relative_to(ROOT)
               for name, module in sys.modules.items() if name == "jevops" or name.startswith("jevops.")):
            raise ValueError("JevOps import escaped the source snapshot")
        plan.pop("plan_id")
        plan["source_snapshot"] = binding
        plan["plan_id"] = content_hash(plan)
    if args.recheck_generation and not args.triage:
        parser.error("--recheck-generation is only allowed with --triage")
    if not args.generate and not args.triage:
        print(json.dumps(plan, indent=2, ensure_ascii=False)); return 0
    if args.preparation_root is None or args.output is None:
        parser.error("execution requires explicit preparation-root and output")
    if args.study in ("local-edits", "deletion-order", "deletion-ids", "deletion-feedback") and not args.snapshot_manifest_sha256:
        parser.error("local edit execution requires a verified source snapshot")
    if args.triage and (args.projects is None or args.elan_home is None or args.study == "templates"):
        parser.error("triage requires --study contracts/output-budget, projects, and elan-home")
    config = json.loads((args.preparation_root / "preparation.json").read_text())
    with exclusive(args.preparation_root / "single-build.lock"):
        if args.triage:
            if args.recheck_generation:
                plan = verification_epoch(args.recheck_generation, args.output, config, plan)
            triage(args.output, config, plan, json.loads(args.projects.read_text()), args.elan_home,
                   args.reviewed_source_sha256)
        else:
            run(args.output, config, plan)
        if args.snapshot_manifest_sha256:
            result = verify_snapshot(ROOT, args.snapshot_manifest_sha256)
            path = args.output / ("native-snapshot-check.json" if args.triage else "generation-snapshot-check.json")
            if path.exists():
                if json.loads(path.read_text()) != result:
                    raise ValueError("previous snapshot check differs")
            else:
                save(path, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
