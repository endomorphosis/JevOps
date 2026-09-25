"""Generate a compact pilot receipt from saved measurements, not model prose.

Read-only snapshot/storage checks and optional local journal diagnosis. No
generation, native checks, rescoring, source repair, training or promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tests_summary(path):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    return {"tests": len(cases), **{key: sum(c.find(tag) is not None for c in cases)
            for key, tag in (("errors", "error"), ("failures", "failure"), ("skipped", "skipped"))}}


def arm_summary(arm):
    trials = arm["trials"]
    measured = [t for t in trials if t.get("generation", {}).get("accounted") is True]
    return {key: arm[key] for key in ("strict_format_attempts", "valid_attempts", "shorter_valid_attempts",
            "tokens_reserved", "tokens_observed", "best_valid_tokens")} | {
        "attempts_reserved": len(trials), "measured_generations": len(measured),
        "known_model_tokens": sum(t["generation"]["usage"]["prompt_tokens"] +
                                  t["generation"]["usage"]["completion_tokens"] for t in measured),
        "statuses": dict(Counter(t["status"] for t in trials)),
        "trials": [{"step": t["step"], "status": t["status"], "all_pin_valid": t["all_pin_valid"],
            "intake_error": t.get("intake_error"), "error_category": t.get("generation", {}).get("error_category"),
            "http_status": t.get("generation", {}).get("http_status"),
            "native_outcomes": [c.get("outcome") for c in t.get("checks", [])]} for t in trials]}


def build(bundle, manifest_sha256, *, journal=False):
    bundle = bundle.resolve(strict=True)
    runtime = bundle / "runtime"
    prep_path, report_path = bundle / "preparation.json", bundle / "pilot/report.json"
    prep, report = json.loads(prep_path.read_text()), json.loads(report_path.read_text())
    cfg = json.loads((bundle / "config.json").read_text())
    if digest(bundle / "config.json") != prep["config_sha256"]:
        raise ValueError("pilot configuration changed")
    check = """import json,sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, sys.argv[1])
from jevops.arena_snapshot import verify_snapshot
from jevops.improvement_service import Config, storage_guard
root=Path(sys.argv[1]); bundle=root.parent
snapshot=verify_snapshot(root, sys.argv[2])
cfg=Config.load(bundle/'config.json')
storage_guard(replace(cfg,state=str(bundle/'pilot')))
volume=json.loads(Path(cfg.volume_config).read_text())
assert volume['max_bytes']==50_000_000_000, 'storage cap changed'
print(json.dumps({'snapshot':snapshot,'storage_guard':'passed','storage_cap_bytes':volume['max_bytes']}))
"""
    checks = json.loads(subprocess.run([sys.executable, "-I", "-B", "-c", check, str(runtime), manifest_sha256],
                         capture_output=True, text=True, check=True, timeout=45).stdout)
    status_path = Path(cfg["state"]) / "status.json"
    status = json.loads(status_path.read_text())
    watcher_after = {k: status.get(k) for k in prep["watcher_before"]}
    canary_path = bundle / "canaries/report.json"
    canaries = json.loads(canary_path.read_text())
    result = {"schema": "jevops-frozen-schema-pilot-summary/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(), "bundle": str(bundle),
        **{k: report[k] for k in ("plan_id", "study", "complete", "model_calls", "native_requests",
                                "evidence_mode", "official_score", "promotion", "training")},
        **checks, "watcher_before": prep["watcher_before"], "watcher_after": watcher_after,
        "watcher_unchanged": prep["watcher_before"] == watcher_after, "cache_policy": "retain_all",
        "isolation_canaries": {k: canaries[k] for k in ("passed_gate", "tests", "passed")},
        "offline_tests": {p.parent.name: tests_summary(p) for p in sorted(bundle.glob("offline*/tests.xml"))},
        "cases": [{"problem": c["problem"], "status": c["status"],
            "controls": [{"pin": x["pin"]["lean_tag"], "outcome": x.get("outcome"),
                          "heartbeats": x.get("receipt", {}).get("heartbeats")} for x in c["controls"]],
            "arms": {k: arm_summary(a) for k, a in c["arms"].items()}} for c in report["cases"]],
        "comparison_established": False, "heartbeat_improvement_established": False,
        "note": "Diagnostic development screen, not a policy promotion or official score. "
                "Unknown generation usage stays unknown; reference heartbeats are not compression gains."}
    if journal:
        end = report_path.stat().st_mtime
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log = subprocess.run(["journalctl", "--user-unit", "ipfs-accelerate-leanstral.service",
            "--since", fmt(end - 20), "--until", fmt(end + 10), "--no-pager", "-o", "cat"],
            capture_output=True, text=True, check=True, timeout=10).stdout
        requests = [t["request_id"] for c in report["cases"] for a in c["arms"].values()
                    for t in a["trials"] if t.get("generation", {}).get("http_status") == 400]
        result["server_journal_diagnostic"] = {
            "window_start": fmt(end - 20), "window_end": fmt(end + 10),
            "matching_failed_request_ids": [rid for rid in requests if rid in log],
            "repetition_limit_error_seen": "number of repetitions exceeds sane defaults" in log,
            "expanded_16k_string_rule_seen": "char{1,16384}" in log,
            "raw_journal_sha256": hashlib.sha256(log.encode()).hexdigest()}
    paths = [prep_path, report_path, bundle / "pilot/plan.json", bundle / "pilot/calls.sqlite", canary_path,
             *sorted(bundle.glob("offline*/tests.xml"))]
    result["artifacts"] = [{"path": str(p), "sha256": digest(p)} for p in paths]
    result["generator_sha256"] = digest(Path(__file__))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--journal", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.bundle, args.manifest_sha256, journal=args.journal)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("complete", "model_calls", "native_requests", "watcher_unchanged")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
