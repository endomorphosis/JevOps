"""Generate a read-only ledger audit, including interrupted repair-lab runs.

No compiler/model calls, receipt recovery, retry, admission or rescoring. Source
drift is observed NOW; it does not establish when a file changed during a run.
The exclusive output must be separate from the original runner's artifacts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory, source):
    directory, source = Path(directory).resolve(strict=True), Path(source).resolve(strict=True)
    plan = json.loads((directory / "plan.json").read_text())
    db_path = directory / "calls.sqlite"
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT id,kind,tokens,native,result FROM calls ORDER BY rowid").fetchall()
    calls = []
    for slot, kind, tokens, native, raw in rows:
        result = json.loads(raw) if raw is not None else {}
        calls.append({"slot": slot, "kind": kind, "tokens_reserved": tokens, "native_reserved": native,
            "result_recorded": raw is not None, "recorded_outcome": result.get("outcome"),
            "recorded_status": result.get("status"), "error_type": result.get("error_type"),
            "error_category": result.get("error_category"), "usage": result.get("usage")})
    current = {p.relative_to(source).as_posix(): digest(p) for p in source.rglob("*")
               if p.is_file() and p.suffix in (".py", ".lean")}
    old = plan["implementation"]
    changed = [{"path": name, "planned_sha256": old.get(name), "observed_sha256": current.get(name)}
               for name in sorted(old.keys() | current.keys()) if old.get(name) != current.get(name)]
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    artifacts = [directory / "plan.json", db_path, *sorted(directory.glob("case-*.json"))]
    if report is not None:
        artifacts.append(report_path)
    return {"schema": "jevops-repair-ledger-audit/v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_directory": str(directory), "plan_id": plan["plan_id"], "study": plan.get("study", "repair"),
        "completion_report_present": report is not None,
        "completion_recorded": report.get("complete") if report is not None else None,
        "model_calls_reserved": sum(c["kind"] == "model" for c in calls),
        "native_requests_reserved": sum(c["native_reserved"] for c in calls),
        "unfinished_reservations": sum(not c["result_recorded"] for c in calls),
        "calls": calls, "implementation_drift_at_audit": changed,
        "artifacts": [{"path": str(p), "sha256": digest(p)} for p in artifacts],
        "generator_sha256": digest(Path(__file__)), "official_score": None,
        "recovered_receipts": False, "comparison_established": False,
        "note": "Reporting only. Missing results stay unknown, not failed or verified. "
                "Drift observed at audit time does not date the change. No original artifacts are modified."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="jevops package whose inventory was frozen")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(args.run_directory, args.source)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("completion_recorded", "model_calls_reserved",
                                            "native_requests_reserved", "unfinished_reservations")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
