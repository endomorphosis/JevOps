"""Explicit live canaries for the alternate rootless profile; no model calls.

Retain all receipts/scratch, use the existing shared lock and storage guard,
and generate reports from pytest observations rather than LLM-written data.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from jevops.arena import source_hash
from jevops.arena_lean import BOUNDARY_FILES
from jevops.improvement_service import Config, storage_guard
from jevops.leanstral_repair_lab import save_new


def watcher_snapshot(config):
    status = json.loads((Path(config.state) / "status.json").read_text())
    return {key: status.get(key) for key in
            ("state", "native_requests_reserved", "router_calls_reserved", "promotions", "official_score")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watcher-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-gib", type=int, choices=(2, 4, 8), default=2)
    args = parser.parse_args()
    config = Config.load(args.watcher_config)
    output = args.output.absolute()
    run_config = replace(config, state=str(output))
    storage_guard(run_config)
    paths = (*BOUNDARY_FILES, Path(__file__).resolve(), REPO / "tests/test_arena_isolation.py")
    hashes = {str(p): source_hash(p.read_text()) for p in paths}

    with (Path(config.volume_config).parent / "single-build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        storage_guard(run_config)
        output.mkdir(mode=0o700)  # Exclusive: pytest may only clear a NEW basetemp.
        old_umask = os.umask(0o077)
        before = watcher_snapshot(config)
        nodes = ["test_live_host_mount_network_environment_and_kernel_limits",
                 "test_live_isolated_proof_boundary", "test_live_running_worker_is_removed_after_timeout",
                 "test_live_worker_is_removed_after_output_limit"]
        options = ["--test-seal=off", "-p", "no:cacheprovider", "-o", "junit_family=xunit1", "-q", "-x",
                   "--basetemp=" + str(output / "pytest"), "--junitxml=" + str(output / "tests.xml"),
                   *[str(REPO / "tests/test_arena_isolation.py") + "::" + node for node in nodes]]
        save_new(output / "plan.json", {"schema": "jevops-mount-owner-canary/v1", "source_hashes": hashes,
            "pytest_args": options, "profile": "jevops-arena-rootless-mount-owner/v1", "driver_calls_max": 9,
            "memory_bytes": args.memory_gib * 1024**3,
            "watcher_before": before, "storage_config": config.volume_config, "model_calls": 0})
        runtime_env = {"JEVOPS_ARENA_DOCKER_TESTS": "1", "JEVOPS_ARENA_MOUNT_OWNER_USER": "1",
            "JEVOPS_ARENA_DOCKER_MEMORY_BYTES": str(args.memory_gib * 1024**3),
            "JEVOPS_ARENA_DOCKER_SOCKET": config.docker_socket, "JEVOPS_ARENA_DOCKER_IMAGE": config.docker_image,
            "ELAN_HOME": config.elan_home, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""}
        previous = {k: os.environ.get(k) for k in runtime_env}
        old_temp = tempfile.tempdir
        try:
            os.environ.update(runtime_env)
            scratch = output / "scratch"
            scratch.mkdir()
            test_scratch = output / "pytest"
            test_scratch.mkdir()
            tempfile.tempdir = str(scratch)
            import pytest
            class Guard:
                @pytest.fixture
                def tmp_path(self, request):
                    # pytest's default numbered tmp_path adds a *current
                    # symlink; keep the existing no-symlink storage guard.
                    return Path(tempfile.mkdtemp(prefix=source_hash(request.node.nodeid)[:12] + "-", dir=test_scratch))

                def pytest_runtest_setup(self, item):
                    storage_guard(run_config)
                    if any(source_hash(Path(p).read_text()) != digest for p, digest in hashes.items()):
                        raise RuntimeError("implementation changed; preserve run")

            code = int(pytest.main(options, plugins=[Guard()]))
        finally:
            tempfile.tempdir = old_temp
            os.umask(old_umask)
            for key, value in previous.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
        guard_error = None
        try:
            storage_guard(run_config)
        except Exception as exc:
            guard_error = type(exc).__name__ + ": " + str(exc)[:300]
        suites = ET.parse(output / "tests.xml").getroot()
        cases = [{"name": case.get("name"), "passed": not any(case.find(k) is not None for k in
                    ("failure", "error", "skipped")), "properties": {p.get("name"): p.get("value")
                    for p in case.findall("properties/property")}} for case in suites.iter("testcase")]
        after = watcher_snapshot(config)
        report = {"schema": "jevops-mount-owner-canary/v1", "pytest_exit_code": code,
            "memory_bytes": args.memory_gib * 1024**3,
            "cases": cases, "passed": sum(c["passed"] for c in cases), "tests": len(cases),
            "implementation_unchanged": all(source_hash(Path(p).read_text()) == d for p, d in hashes.items()),
            "storage_guard_error": guard_error,
            "watcher_before": before, "watcher_after": after, "watcher_unchanged": before == after,
            "model_calls": 0, "training": False, "promotion": False, "official_score": None,
            "evidence": "synthetic isolation/proof-boundary canaries; not an Arena score"}
        report["passed_gate"] = (guard_error is None and code == 0 and len(cases) == 9 and report["passed"] == 9
                                  and report["implementation_unchanged"] and report["watcher_unchanged"])
        save_new(output / "report.json", report)
        print(json.dumps({k: report[k] for k in ("passed_gate", "passed", "tests", "model_calls", "watcher_unchanged")}))
        print("Report: " + str(output / "report.json"))
        return 0 if report["passed_gate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
