#!/usr/bin/env python3
"""One fresh body-wide reference replay, separate from candidate screening.

Run with python -I -B. Requires the completed frozen pilot and prepared projects;
no models, downloads, builds, retries or candidate promotion. Writes new receipts
using the frozen pilot's exclusive-create/fsync helper. Single process maximum.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--preparation-root", type=Path, required=True)
    parser.add_argument("--snapshot-manifest-sha256", required=True)
    args = parser.parse_args()
    root = args.run_root.resolve(strict=True)
    snapshot, run = root / "snapshot", root / "run"
    sys.path.insert(0, str(snapshot))
    sys.path.insert(1, str(snapshot / "papers/completion/lean_refactor_arena/tools"))
    from jevops.arena_snapshot import verify_snapshot
    from jevops.arena_prepare import exclusive, validate_volume
    from jevops.arena_lean import NativeLeanVerifier, project_binding
    from jevops.arena_local import ArenaLocalRuntime
    from jevops.arena_trial import _pins
    from jevops.seals import Fingerprinter
    from run_local_premise_pilot import save

    with exclusive(args.preparation_root / "single-build.lock"):
        config = json.loads((args.preparation_root / "preparation.json").read_text())
        if not root.is_relative_to(validate_volume(config)):
            raise ValueError("run outside capped preparation volume")
        before = verify_snapshot(snapshot, args.snapshot_manifest_sha256)
        if any(getattr(m, "__file__", None) and not Path(m.__file__).resolve().is_relative_to(snapshot)
               for n, m in sys.modules.items() if n == "jevops" or n.startswith("jevops.")):
            raise ValueError("JevOps import escaped snapshot")
        if (run / "reference-replay-reservation.json").exists():
            raise ValueError("fresh one-shot control required")
        started = time.monotonic()
        plan = json.loads((run / "plan.json").read_text())
        record, pins = plan["record"], _pins(plan["record"])
        projects = json.loads((snapshot / "inputs/projects.json").read_text())
        bindings = {}
        for pin in pins:
            matches = [p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                       (record["url"], pin.lean_tag, pin.git_commit)]
            if len(matches) != 1:
                raise ValueError("one prepared project per pin required")
            bindings[pin] = project_binding(record, pin, matches[0], args.preparation_root / "work/elan")
        guard = NativeLeanVerifier(bindings, max_processes=0, timeout=90, fingerprinter=Fingerprinter())
        runtime = ArenaLocalRuntime(guard, record, max_processes=1, event_budget=256)
        capture = json.loads((run / "capture.json").read_text())["capture"]
        event = capture["trace"]["events"][2]
        if event["syntax_kind"] != [["s", s] for s in ("Lean", "Parser", "Tactic", "tacticSeq")]:
            raise ValueError("expected original body-wide tactic sequence")
        # The native baseline always replays the original body syntax. `skip`
        # is an explicit negative candidate, not a putative refactor: it must
        # leave goals open while the original body passes its kernel/axiom audit.
        candidate = "skip"
        save(run / "reference-replay-reservation.json", {"units": 1, "event_id": 2,
            "purpose": "original-body baseline audit plus non-closing skip control, not a refactor candidate",
            "plan_id": plan["plan_id"], "snapshot_manifest_sha256": args.snapshot_manifest_sha256,
            "control_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest()})
        outcome = runtime.replay(pins[0], record["src"], capture, 2, candidate)
        save(run / "reference-replay.json", outcome)
        validate_volume(config)
        after = verify_snapshot(snapshot, args.snapshot_manifest_sha256)
        control = {"before": before, "after": after, "native_processes": runtime.attempts,
            "reserved_processes": runtime.reserved, "whole_proof_processes": guard.processes,
            "wall_seconds": round(time.monotonic() - started, 4), "model_calls": 0,
            "official_score": None, "proof_admitted": False}
        save(run / "reference-replay-source-binding.json", control)
        checked = (outcome["ok"] and outcome.get("native", {}).get("baseline", {}).get("status") ==
                   "closed_kernel_checked" and outcome.get("native", {}).get("proposed", {}).get("status") ==
                   "open_goals" and not outcome["closing_reproduced"])
        print(json.dumps({**control, "ok": outcome["ok"],
            "control_passed": checked,
            "closing_reproduced": outcome["closing_reproduced"],
            "baseline": outcome.get("native", {}).get("baseline"),
            "proposed": outcome.get("native", {}).get("proposed")}))
        return 0 if checked else 2


if __name__ == "__main__":
    raise SystemExit(main())
