"""Freeze a fresh pilot's inputs without starting a watcher or running models.

The snapshot lives inside the existing capped volume. Prepared Lean environments
are referenced, not copied. This is a source-identity receipt, not proof evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import fcntl
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from jevops.arena import source_hash
from jevops.arena_snapshot import create_snapshot, verify_snapshot
from jevops.improvement_service import Config, storage_guard
from jevops.leanstral_repair_lab import save_new

ARENA = "papers/completion/lean_refactor_arena"
INCLUDES = ["jevops", "tests", "conftest.py", "pytest.ini", f"{ARENA}/harness",
            f"{ARENA}/data/benchmark_data_warmup.jsonl",
            *[f"{ARENA}/tools/{name}.py" for name in
              ("prepare_frozen_schema_pilot", "run_mount_owner_canary", "audit_repair_lab", "report_frozen_schema_pilot")]]


def pilot_config(original, runtime, manifest_sha256):
    # Keep the watcher's state path only for read-only status comparisons. The
    # existing repair/canary CLIs independently replace state with their output.
    return replace(original, runtime=str(runtime), snapshot_sha256=manifest_sha256)


def prepare(config_path, output):
    original = Config.load(config_path)
    output = output.absolute()
    guarded = replace(original, state=str(output))
    storage_guard(guarded)
    with (Path(original.volume_config).parent / "single-build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        storage_guard(guarded)
        old_umask = os.umask(0o077)
        try:
            output.mkdir(mode=0o700)  # Exclusive; never overwrite an old bundle.
            inputs = {"inputs/projects.json": Path(original.runtime) / "inputs/projects.json",
                      "inputs/original-watcher-config.json": config_path}
            snapshot = create_snapshot(REPO, output / "runtime", INCLUDES, inputs)
            verified = verify_snapshot(output / "runtime", snapshot["manifest_sha256"])
            cfg = pilot_config(original, output / "runtime", snapshot["manifest_sha256"])
            path = output / "config.json"
            save_new(path, asdict(cfg))
            path.chmod(0o444)
            watcher_path = Path(original.state) / "status.json"
            watcher = json.loads(watcher_path.read_text())
            receipt = {"schema": "jevops-frozen-schema-preparation/v1", "snapshot": snapshot,
                "snapshot_check": verified, "config_sha256": source_hash(path.read_text()),
                "watcher_before": {k: watcher.get(k) for k in
                    ("state", "native_requests_reserved", "router_calls_reserved", "promotions", "official_score")},
                "models_started": 0, "native_requests_started": 0, "cache_policy": "retain_all",
                "training": False, "promotion": False, "official_score": None}
            storage_guard(guarded)
            save_new(output / "preparation.json", receipt)
            return receipt
        finally:
            os.umask(old_umask)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watcher-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.watcher_config, args.output)
    except BlockingIOError:
        print(json.dumps({"status": "LOCK_BUSY", "models_started": 0, "native_requests_started": 0}))
        return 2
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
