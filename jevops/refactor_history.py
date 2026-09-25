"""Read explicitly selected experiment archives as untrusted prompt hints.

No recursive discovery, model replies, filesystem paths from payloads, or proof
admission. Only a fixed allowlist of bounded sibling JSON files is read. Archive
hashes check internal consistency, not authenticity. Receipts are revalidated
by the existing controlled-trial history validator, never reused as new proofs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .arena import content_hash, source_hash
from .arena_trial import Candidate, SCHEMA as TRIAL_SCHEMA

ARCHIVES = ("jevops-experiment-archive/v1", "jevops-experiment-evidence-archive/v1")
SWEEP = "jevops-deletion-catalog-sweep/v1"
PILOTS = {f"jevops-refactor-{name}-pilot/v1" for name in
          ("contract", "output-budget", "local-edit", "deletion-order", "deletion-id", "deletion-feedback")}
MAX_BYTES = 2_097_152


def load_archive(path: Path, manifest: dict, *, manifest_sha256: str, decode, validate_trial):
    """Return validated trial chunks, one coverage summary, and provenance."""
    if manifest.get("schema") not in ARCHIVES or not isinstance(manifest.get("files"), dict):
        raise ValueError("supported explicit history archive required")
    files = manifest["files"]
    consumed = {}

    def read(name):
        # Call sites use ONLY literal allowlisted filenames, never manifest paths.
        target = path.parent / name
        entry = files.get(name)
        if (target.is_symlink() or not target.is_file() or not isinstance(entry, dict) or
                type(entry.get("bytes")) is not int or not 0 < entry["bytes"] <= MAX_BYTES):
            raise ValueError("bounded regular archived history file required")
        with target.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != entry["bytes"] or digest != entry.get("sha256"):
            raise ValueError("archived history hash/size mismatch")
        consumed[name] = digest
        result = decode(raw)
        if not isinstance(result, dict):
            raise ValueError("archived history object required")
        return result

    plan = read("plan.json")
    if plan.get("plan_id") != content_hash({k: v for k, v in plan.items() if k != "plan_id"}):
        raise ValueError("historical plan identity mismatch")
    record = plan["record"]
    catalog = None
    if plan.get("schema") == SWEEP:
        report = read("sweep.json")
        if report.get("schema") != SWEEP or report.get("evidence_mode") != "local_lean":
            raise ValueError("native sweep history required")
        candidates = plan["candidates"]
        catalog = plan["catalog"]
        if (catalog.get("schema") != "jevops-source-bound-deletion-catalog/v1" or
                catalog.get("record_sha256") != content_hash(record) or
                catalog.get("source_sha256") != source_hash(record["src"]) or
                content_hash(catalog) != plan.get("catalog_sha256") or
                report.get("catalog_sha256") != plan["catalog_sha256"]):
            raise ValueError("historical catalog binding mismatch")
        # Validate the recorded actions, not today's potentially changed slicer.
        prefix = record["statement"] + " := by\n"
        if not record["src"].startswith(prefix):
            raise ValueError("canonical deletion source required")
        lines = record["src"][len(prefix):].splitlines(keepends=True)
        entries = catalog.get("entries")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise ValueError("bounded historical catalog required")
        sources = {}
        for i, entry in enumerate(entries, 1):
            span = entry.get("delete_lines")
            if (type(entry.get("edit_id")) is not int or entry["edit_id"] != i or
                    not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span) or
                    not 1 <= span[0] <= span[1] <= len(lines)):
                raise ValueError("malformed historical deletion")
            sources[i] = prefix + "".join(lines[:span[0] - 1] + lines[span[1]:])
        ids = []
        for candidate in candidates:
            selected = candidate.get("edit_ids")
            if (not isinstance(selected, list) or not selected or
                    any(type(i) is not int or sources.get(i) != candidate.get("source") for i in selected) or
                    candidate.get("source_sha256") != source_hash(candidate["source"])):
                raise ValueError("catalog candidate/source mismatch")
            ids.extend(selected)
        if sorted(ids) != list(sources):
            raise ValueError("historical catalog coverage mismatch")
    else:
        if plan.get("schema") not in PILOTS:
            raise ValueError("unsupported prompt pilot plan")
        native = read("native-plan.json")
        report = read("native-triage.json")
        if (report.get("schema") != "jevops-prompt-validity-triage/v1" or
                native.get("plan_id") != plan["plan_id"] or native.get("protocol") != plan.get("native_protocol")):
            raise ValueError("prompt pilot native plan mismatch")
        candidates = native["candidates"]
    if report.get("plan_id") != plan["plan_id"]:
        raise ValueError("historical report/plan mismatch")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 64:
        raise ValueError("bounded historical candidates required")
    arms = [Candidate("control", record["src"], "historical reference control")]
    for c in candidates:
        arms.append(Candidate(c["label"], c["source"], "historical archive proposal, not a proof"))
    if len({a.label for a in arms}) != len(arms):
        raise ValueError("duplicate historical label")
    if len({c["source"] for c in candidates}) != len(candidates):
        raise ValueError("archive candidate sources must be deduplicated")
    by_label = {a.label: a for a in arms}
    pins = {(tag, commit) for row in record["version_info"] for tag, commit in row.items()}
    rows = report.get("rows")
    contexts = report.get("contexts")
    if (not isinstance(rows, list) or len(rows) != len(arms) * len(pins) or
            not isinstance(contexts, dict) or not 1 <= len(contexts) <= 8):
        raise ValueError("complete bounded history matrix required")
    seen, samples, outcomes = set(), [], {a.label: [] for a in arms}
    for row in rows:
        label, pin = row["label"], row["pin"]
        identity = (label, pin["lean_tag"], pin["git_commit"])
        if (label not in by_label or identity in seen or identity[1:] not in pins or
                row.get("source_sha256") != source_hash(by_label[label].source)):
            raise ValueError("duplicate or mismatched historical source/pin")
        seen.add(identity)
        status = row["status"]
        outcomes[label].append(status)
        if status == "NOT_RUN_AFTER_NON_SUCCESS":
            if row.get("receipt") is not None:
                raise ValueError("not-run row cannot contain a receipt")
            continue  # Not an observation, proof or counterexample.
        if row.get("receipt") and (type(row.get("native_processes", 1)) is not int or row.get("native_processes", 1) != 1):
            raise ValueError("historical receipt requires a fresh native process")
        samples.append({**row, "version": pin, "branch_order": "reference-first"})
    # Reuse the existing strict validator without broadening its trial limits.
    trials = []
    for start in range(0, len(arms), 8):
        chunk = arms[start:start + 8]
        trial = {"schema": TRIAL_SCHEMA, "record": record, "evidence_mode": "local_lean",
            "arms": [dict(label=a.label, source=a.source, provenance=a.provenance) for a in chunk],
            "contexts": list(contexts.values()),
            "samples": [s for s in samples if s["label"] in {a.label for a in chunk}]}
        validate_trial(trial)
        trials.append(trial)
    counts = {"all_pin_verified": 0, "rejected": 0, "inconclusive": 0}
    for candidate in candidates:
        states = outcomes[candidate["label"]]
        category = ("rejected" if "REJECTED" in states else
                    "all_pin_verified" if all(s == "VERIFIED" for s in states) else "inconclusive")
        counts[category] += 1
    summary = {"record_sha256": content_hash(record), "plan_id": plan["plan_id"],
        "kind": "deletion_catalog" if catalog is not None else "prompt_pilot_validity",
        "candidate_sources": len(candidates), "outcomes_reported": counts,
        "reference_controls_all_verified": all(s == "VERIFIED" for s in outcomes["control"]),
        "required_pin_count": len(pins), "context_ids": sorted({s["context_id"] for s in samples if s.get("receipt")}),
        "not_run_checks": sum(r["status"] == "NOT_RUN_AFTER_NON_SUCCESS" for r in rows),
        "authority": "unauthenticated historical coverage, not current proof or a general impossibility result"}
    if catalog is not None:
        summary.update(catalog_sha256=content_hash(catalog), catalog_actions=len(catalog["entries"]),
            every_catalog_source_rejected=(counts["rejected"] == len(candidates) and summary["reference_controls_all_verified"]))
    return trials, summary, {"manifest_sha256": manifest_sha256,
                             "consumed_files": consumed, "authenticated": False}
