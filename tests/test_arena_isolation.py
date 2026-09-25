"""Offline isolation controls; real Docker/Lean tests require explicit opt-in."""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from jevops import arena_isolation as isolated
from jevops import arena_lean as native
from jevops.arena import Outcome, VerificationRequest, content_hash
from jevops.lean import VersionPin

IMAGE = "sha256:" + "a" * 64
IDENTITY = "b" * 64
OWNER = "c" * 32


@pytest.fixture
def profile(tmp_path):
    client = tmp_path / "docker"
    client.write_text("#!/bin/false\n"); client.chmod(0o700)
    # Linux Unix-socket addresses are limited to 108 bytes; pytest paths under
    # an explicit preparation root can legitimately exceed that length.
    with tempfile.TemporaryDirectory(prefix="jev-iso-", dir="/tmp") as short:
        with socket.socket(socket.AF_UNIX) as channel:
            endpoint = Path(short) / "docker.sock"
            channel.bind(str(endpoint))
            yield isolated.DockerIsolation(endpoint, IMAGE, client)


@pytest.fixture
def inputs(tmp_path):
    lean = tmp_path / "toolchain/bin/lean"
    lean.parent.mkdir(parents=True); lean.write_text("fixture only")
    (lean.parent.parent / "lib").mkdir()
    driver = tmp_path / "Driver.lean"; driver.write_text("fixture only")
    dep = tmp_path / "compiled-imports"; dep.mkdir()
    return lean, (dep,), driver


def created(profile, mounts, owner=OWNER):
    return {"Id": IDENTITY, "Image": IMAGE,
        "Config": {"Labels": {isolated.OWNER_LABEL: owner}, "User": profile.worker_user, "WorkingDir": "/tmp",
            "Entrypoint": ["/toolchain/bin/lean"], "Cmd": ["--run", "/driver/ArenaCheck.lean"],
            "Env": [k + "=" + v for k, v in profile.container_env(mounts).items()]},
        "HostConfig": {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none", "IpcMode": "none",
            "PidMode": "", "UTSMode": "", "CgroupnsMode": "private", "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"], "Memory": profile.memory_bytes, "MemorySwap": profile.memory_bytes,
            "NanoCpus": 1_000_000_000, "PidsLimit": profile.pids, "LogConfig": {"Type": "none"},
            "Tmpfs": {"/tmp": f"rw,nosuid,nodev,noexec,size={profile.tmp_bytes},mode=1777"},
            "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}, {"Name": "nofile", "Soft": 128, "Hard": 128}]},
        "Mounts": [{"Source": src, "Destination": dst, "RW": False, "Type": "bind"} for src, dst in mounts]}


@pytest.mark.parametrize("field,value", [("image_id", "ubuntu:latest"), ("image_id", "sha256:bad"),
    ("image_id", True), ("memory_bytes", 0), ("memory_bytes", True), ("pids", 0), ("pids", 1.5),
    ("tmp_bytes", 0), ("tmp_bytes", 300_000_000), ("mount_owner_user", 1), ("mount_owner_user", "true")])
def test_invalid_or_unbounded_profile_rejected(profile, field, value):
    with pytest.raises(ValueError):
        replace(profile, **{field: value})


def test_no_remote_socket_or_plain_file_socket(profile, tmp_path):
    with pytest.raises((ValueError, OSError)):
        replace(profile, socket=Path("tcp://remote:2375"))
    file = tmp_path / "not-socket"; file.touch()
    with pytest.raises(isolated.IsolationUnavailable):
        replace(profile, socket=file)


def test_mount_owner_is_explicit_distinct_and_never_a_rootful_escape(profile, inputs, monkeypatch):
    # Model a non-root host owner even when offline tests run in a root-owned CI
    # container. Path/socket ownership is tested independently above.
    monkeypatch.setattr(isolated.DockerIsolation, "validate_paths", lambda _: None)
    monkeypatch.setattr(isolated.os, "getuid", lambda: 1000)
    monkeypatch.setattr(isolated.os, "getgid", lambda: 1000)
    owner = replace(profile, mount_owner_user=True)
    assert profile.worker_user == "65534:65534" and profile.policy["profile"] == isolated.PROFILE
    assert owner.worker_user == "0:0" and owner.policy["profile"] == isolated.OWNER_PROFILE
    mounts = owner.mounts(*inputs)
    args = owner.create_args(mounts, OWNER)
    assert "--user=0:0" in args and "--cap-drop=ALL" in args and "--read-only" in args
    assert "--network=none" in args and "--security-opt=no-new-privileges" in args
    owner.verify_created(created(owner, mounts), IDENTITY, OWNER, mounts)
    with pytest.raises(isolated.IsolationError):
        profile.verify_created(created(owner, mounts), IDENTITY, OWNER, mounts)
    with pytest.raises(isolated.IsolationError):
        owner.verify_created(created(profile, mounts), IDENTITY, OWNER, mounts)
    monkeypatch.setattr(isolated.DockerIsolation, "control", lambda *a, **kw: json.dumps({
        "SecurityOptions": ["name=cgroupns", "name=seccomp,profile=builtin"], "CgroupVersion": "2",
        "MemoryLimit": True, "SwapLimit": True, "PidsLimit": True, "CpuCfsQuota": True}))
    with pytest.raises(isolated.IsolationUnavailable, match="rootless"):
        owner.preflight(scratch="/unused", deadline=time.monotonic() + 3)
    monkeypatch.setattr(isolated.os, "getuid", lambda: 0)
    with pytest.raises(isolated.IsolationUnavailable, match="unprivileged"):
        replace(profile, mount_owner_user=True)


def test_resolved_mount_paths_cannot_inject_mount_options(profile, inputs, tmp_path):
    unusual = tmp_path / "has,comma"; unusual.mkdir()
    link = tmp_path / "ordinary-name"; link.symlink_to(unusual, target_is_directory=True)
    with pytest.raises(ValueError, match="unambiguous"):
        profile.mounts(inputs[0], (link,), inputs[2])


def test_command_has_explicit_narrow_readonly_inputs_and_no_ambient_configuration(profile, inputs, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "not-a-real-secret")
    monkeypatch.setenv("DOCKER_HOST", "tcp://wrong-host")
    mounts = profile.mounts(*inputs)
    args = profile.create_args(mounts, OWNER)
    assert args[0] == "create" and "--pull=never" in args
    assert "--read-only" in args and "--network=none" in args and "--user=65534:65534" in args
    assert "--memory-swap=" + str(profile.memory_bytes) in args and "--cpus=1" in args
    assert args[-3:] == [IMAGE, "--run", "/driver/ArenaCheck.lean"]
    assert all(args[i + 1].endswith(",readonly") for i, x in enumerate(args) if x == "--mount")
    assert profile.client[1:] == ["--host", "unix://" + str(profile.socket)]
    assert set(profile.client_env("/private-client")) == {"PATH", "DOCKER_CONFIG", "LANG"}
    assert "wrong-host" not in str(args) and "not-a-real-secret" not in str(args)
    assert {dst for _, dst in mounts} == {"/toolchain/bin/lean", "/toolchain/lib", "/driver/ArenaCheck.lean", "/deps/0"}
    profile.verify_created(created(profile, mounts), IDENTITY, OWNER, mounts)


@pytest.mark.parametrize("field,value", [("ReadonlyRootfs", False), ("Privileged", True),
    ("NetworkMode", "host"), ("IpcMode", "host"), ("PidMode", "host"), ("UTSMode", "host"),
    ("CgroupnsMode", "host"), ("CapDrop", []), ("CapAdd", ["SYS_ADMIN"]), ("SecurityOpt", []),
    ("Memory", 0), ("MemorySwap", -1), ("NanoCpus", 0), ("PidsLimit", -1), ("Tmpfs", {}),
    ("LogConfig", {"Type": "json-file"}), ("Ulimits", []), ("Devices", ["fixture-device"]),
    ("GroupAdd", ["0"]), ("UsernsMode", "host")])
def test_effective_policy_must_match_before_start(profile, inputs, field, value):
    mounts = profile.mounts(*inputs); data = created(profile, mounts)
    data["HostConfig"][field] = value
    with pytest.raises(isolated.IsolationError):
        profile.verify_created(data, IDENTITY, OWNER, mounts)


@pytest.mark.parametrize("damage", ["owner", "image", "rw", "extra_mount", "duplicate_mount", "env", "entrypoint", "user"])
def test_wrong_identity_environment_or_mounts_are_rejected(profile, inputs, damage):
    mounts = profile.mounts(*inputs); data = created(profile, mounts)
    if damage == "owner": data["Config"]["Labels"][isolated.OWNER_LABEL] = "other"
    elif damage == "image": data["Image"] = "sha256:" + "d" * 64
    elif damage == "rw": data["Mounts"][0]["RW"] = True
    elif damage == "extra_mount": data["Mounts"].append({"Type": "volume", "Destination": "/escape"})
    elif damage == "duplicate_mount": data["Mounts"].append(data["Mounts"][0])
    elif damage == "env": data["Config"]["Env"].append("LD_PRELOAD=/some/plugin.so")
    elif damage == "entrypoint": data["Config"]["Entrypoint"] = ["/bin/sh"]
    else: data["Config"]["User"] = "0"
    with pytest.raises(isolated.IsolationError):
        profile.verify_created(data, IDENTITY, OWNER, mounts)


@pytest.mark.parametrize("damage", ["rootful", "seccomp", "cgroup", "memory", "pids", "swap", "cpu", "image", "volume"])
def test_missing_capabilities_never_downgrade(profile, monkeypatch, tmp_path, damage):
    info = {"SecurityOptions": ["name=rootless", "name=cgroupns", "name=seccomp,profile=builtin"],
            "CgroupVersion": "2", "MemoryLimit": True, "SwapLimit": True, "PidsLimit": True, "CpuCfsQuota": True}
    image = {"Id": IMAGE, "Os": "linux", "Config": {}}
    if damage == "rootful": info["SecurityOptions"].remove("name=rootless")
    elif damage == "seccomp": info["SecurityOptions"].pop()
    elif damage == "cgroup": info["CgroupVersion"] = "1"
    elif damage == "image": image["Id"] = "other"
    elif damage == "volume": image["Config"]["Volumes"] = {"/data": {}}
    else: info[{"memory": "MemoryLimit", "pids": "PidsLimit", "swap": "SwapLimit", "cpu": "CpuCfsQuota"}[damage]] = False
    monkeypatch.setattr(isolated.DockerIsolation, "control", lambda self, args, **kw: json.dumps(info if args[0] == "info" else image))
    with pytest.raises(isolated.IsolationUnavailable):
        profile.preflight(scratch=str(tmp_path), deadline=time.monotonic() + 3)


@pytest.mark.parametrize("failure", [None, "body_timeout", "create_timeout", "invalid_policy", "cleanup"])
def test_owned_lifecycle_cleans_up_even_after_create_timeout(profile, inputs, tmp_path, monkeypatch, failure):
    calls, state = [], {}
    monkeypatch.setattr(isolated.DockerIsolation, "preflight", lambda *a, **k: None)
    def control(self, args, **kw):
        calls.append(args)
        if args[0] == "create":
            state["owner"] = args[args.index("--label") + 1].split("=", 1)[1]
            mounts = self.mounts(*inputs)
            mounts += [(str(tmp_path / "empty-network-config"), "/etc/" + name) for name in ("hosts", "hostname", "resolv.conf")]
            state["data"] = created(self, mounts, state["owner"])
            if failure == "invalid_policy": state["data"]["HostConfig"]["NetworkMode"] = "host"
            if failure == "create_timeout": raise TimeoutError("control deadline")
            return IDENTITY
        if args[:2] == ["container", "inspect"]: return json.dumps(state["data"])
        if args[:2] == ["container", "ls"]: return IDENTITY
        if args[:2] == ["container", "rm"]:
            if failure == "cleanup": raise isolated.IsolationUnavailable("daemon disappeared")
            return IDENTITY
        raise AssertionError(args)
    monkeypatch.setattr(isolated.DockerIsolation, "control", control)
    @contextmanager
    def expect():
        if failure is None: yield
        else:
            with pytest.raises(TimeoutError if "timeout" in failure else isolated.IsolationError): yield
    with expect():
        with profile.launch(*inputs, scratch=str(tmp_path), deadline=time.monotonic() + 3) as (cmd, env):
            assert cmd[-4:] == ["start", "--attach", "--interactive", IDENTITY]
            assert "DOCKER_HOST" not in env
            if failure == "body_timeout": raise TimeoutError()
    assert calls[-1] == ["container", "rm", "--force", IDENTITY]
    assert (tmp_path / "empty-network-config").read_bytes() == b""


def test_cleanup_does_not_remove_another_owner(profile, monkeypatch, tmp_path):
    def control(self, args, **kw):
        assert args[:2] == ["container", "inspect"]  # removal must never happen
        return json.dumps({"Id": IDENTITY, "Config": {"Labels": {isolated.OWNER_LABEL: "someone_else"}}})
    monkeypatch.setattr(isolated.DockerIsolation, "control", control)
    with pytest.raises(isolated.IsolationError, match="ownership"):
        profile.cleanup(IDENTITY, OWNER, scratch=str(tmp_path))


def test_missing_isolation_is_unavailable_and_not_cached_or_run_on_host(profile, inputs, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture inputs"))
    pin = VersionPin("v4.26.0", "a" * 40)
    binding = native.ProjectBinding(pin, inputs[0], inputs[0].parent, "", project_backed=False)
    record = {"name": "isolated", "statement": "theorem isolated : True", "src": "theorem isolated : True := by trivial",
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    adapter = native.NativeLeanVerifier({pin: binding}, max_processes=2, isolation=profile)
    context = adapter.context(record, reference_heartbeats=1)
    plain = native.NativeLeanVerifier({pin: binding}, max_processes=2)
    assert plain.context(record, reference_heartbeats=1).context_id != context.context_id
    def unavailable(*a, **k): raise isolated.IsolationUnavailable("network namespace unavailable")
    monkeypatch.setattr(isolated.DockerIsolation, "preflight", unavailable)
    monkeypatch.setattr(native, "capture_process", lambda *a, **k: pytest.fail("must not launch Lean or fallback"))
    evaluator = adapter.evaluator(context, max_calls=2)
    for _ in range(2):
        evaluation = evaluator.evaluate(record["src"])
        assert evaluation.status == "INCOMPLETE" and evaluation.receipts[0].outcome == Outcome.UNAVAILABLE
    assert evaluator.cache_hits == 0 and adapter.processes == 2


def test_zero_budget_does_not_probe_or_launch_docker(profile, inputs, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture inputs"))
    pin = VersionPin("v4.26.0", "a" * 40)
    adapter = native.NativeLeanVerifier({pin: native.ProjectBinding(pin, inputs[0], inputs[0].parent, "", project_backed=False)},
                                       max_processes=0, isolation=profile)
    record = {"name": "t", "statement": "theorem t : True", "src": "theorem t : True := by trivial",
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    monkeypatch.setattr(isolated.DockerIsolation, "preflight", lambda *a, **k: pytest.fail("zero means no execution"))
    assert adapter(VerificationRequest(adapter.context(record), record["src"], pin)).outcome == Outcome.BUDGET_EXHAUSTED


def test_changed_client_invalidates_context_before_work(profile, inputs, monkeypatch):
    monkeypatch.setattr(native.ProjectBinding, "fingerprint", lambda *_: content_hash("fixture inputs"))
    pin = VersionPin("v4.26.0", "a" * 40)
    adapter = native.NativeLeanVerifier({pin: native.ProjectBinding(pin, inputs[0], inputs[0].parent, "", project_backed=False)},
                                       max_processes=1, isolation=profile)
    record = {"name": "t", "statement": "theorem t : True", "src": "theorem t : True := by trivial",
              "version_info": [{pin.lean_tag: pin.git_commit}]}
    req = VerificationRequest(adapter.context(record), record["src"], pin)
    profile.executable.write_text("changed executable")
    receipt = adapter(req)
    assert receipt.outcome == Outcome.ERROR and "execution_environment_changed" in receipt.reason
    assert adapter.processes == 0


@pytest.mark.parametrize("args", [["--isolation", "docker"], ["--docker-image-id", IMAGE],
                                  ["--docker-socket", "/does/not/exist"]])
def test_cli_requires_explicit_complete_configuration(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["arena_lean", "--smoke", *args])
    with pytest.raises(SystemExit) as exc:
        native.main()
    assert exc.value.code == 2


@pytest.fixture
def live_profile():
    if os.environ.get("JEVOPS_ARENA_DOCKER_TESTS") != "1":
        pytest.skip("explicit JEVOPS_ARENA_DOCKER_TESTS=1 and local image/socket required")
    # Opting in with missing/broken infrastructure fails, never silently skips.
    return isolated.DockerIsolation(Path(os.environ["JEVOPS_ARENA_DOCKER_SOCKET"]),
                                   os.environ["JEVOPS_ARENA_DOCKER_IMAGE"],
                                   memory_bytes=int(os.environ.get("JEVOPS_ARENA_DOCKER_MEMORY_BYTES", "2147483648")),
                                   mount_owner_user=os.environ.get("JEVOPS_ARENA_MOUNT_OWNER_USER") == "1")


@pytest.fixture
def live_lean(live_profile):
    return native.pinned_lean(Path(os.environ["ELAN_HOME"]), "v4.26.0")


def assert_container_removed(profile, identity, scratch):
    result = subprocess.run([*profile.client, "container", "inspect", identity],
        env=profile.client_env(str(scratch)), capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and "No such container" in result.stderr, result.stderr


def test_live_host_mount_network_environment_and_kernel_limits(live_profile, live_lean, tmp_path, monkeypatch, record_property):
    """Synthetic canaries only: never attempt to read actual host credentials."""
    dep = tmp_path / "imports"; dep.mkdir(mode=0o755)
    marker = dep / "canary.txt"; marker.write_text("read-only input")
    hidden = tmp_path / "unmounted-canary.txt"; hidden.write_text("host only")
    driver = tmp_path / "Canary.lean"
    monkeypatch.setenv("JEVOPS_ISOLATION_FAKE_SECRET", "synthetic-do-not-inherit")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0)); listener.listen(1)
        port = listener.getsockname()[1]
        code = r'''import Lean
open Lean
def ensure (name : String) (b : Bool) : IO Unit :=
  unless b do throw <| IO.userError s!"isolation canary failed: {name}"
def blockedWrite (path : String) : IO Bool := do
  try
    IO.FS.writeFile path "unexpected write"
    return false
  catch _ => return true
def main : IO Unit := do
  ensure "input readable" ((← IO.FS.readFile "/deps/0/canary.txt") == "read-only input")
  for path in ["/deps/0/canary.txt", "/driver/ArenaCheck.lean", "/toolchain/lib/jevops-canary-write",
               "/etc/hosts", "/etc/resolv.conf", "/etc/hostname"] do
    ensure path (← blockedWrite path)
  ensure "host file hidden" (!(← System.FilePath.pathExists __HOST_FILE__))
  ensure "socket hidden" (!(← System.FilePath.pathExists __SOCKET__))
  ensure "no inherited credential" ((← IO.getEnv "JEVOPS_ISOLATION_FAKE_SECRET").isNone)
  let chmod ← IO.Process.output {cmd := "/bin/chmod", args := #["777", "/deps/0/canary.txt"]}
  ensure "cannot chmod read-only imports" (chmod.exitCode != 0)
  IO.FS.writeFile "/tmp/canary.txt" "scratch works"
  ensure "scratch" ((← IO.FS.readFile "/tmp/canary.txt") == "scratch works")
  let network ← IO.Process.output {cmd := "/usr/bin/readlink", args := #["/proc/self/ns/net"]}
  ensure "private network namespace" (network.exitCode == 0 && network.stdout != __HOST_NET__)
  let probe ← IO.Process.output {cmd := "/bin/bash", args := #["-c", __CONNECT__]}
  ensure "host loopback inaccessible" (probe.exitCode != 0)
  let memory ← IO.FS.readFile "/sys/fs/cgroup/memory.max"
  let swap ← IO.FS.readFile "/sys/fs/cgroup/memory.swap.max"
  let pids ← IO.FS.readFile "/sys/fs/cgroup/pids.max"
  let cpu ← IO.FS.readFile "/sys/fs/cgroup/cpu.max"
  let status ← IO.FS.readFile "/proc/self/status"
  let uidMap ← IO.FS.readFile "/proc/self/uid_map"
  let gidMap ← IO.FS.readFile "/proc/self/gid_map"
  IO.println <| "JEVOPS_ISOLATION_CANARY:" ++ (Json.mkObj [
    ("memory", toJson memory), ("swap", toJson swap), ("pids", toJson pids),
    ("cpu", toJson cpu), ("process_status", toJson status),
    ("uid_map", toJson uidMap), ("gid_map", toJson gidMap)]).compress
'''
        for key, value in {"__HOST_FILE__": str(hidden), "__SOCKET__": str(live_profile.socket),
                "__HOST_NET__": os.readlink("/proc/self/ns/net") + "\n",
                "__CONNECT__": f"exec 3<>/dev/tcp/127.0.0.1/{port}"}.items():
            code = code.replace(key, json.dumps(value))
        driver.write_text(code)
        with live_profile.launch(live_lean, (dep,), driver, scratch=str(tmp_path),
                                 deadline=time.monotonic() + 60) as (command, env):
            identity = command[-1]
            out, err, exit_code = isolated.capture_process(command, env=env, timeout=40, output_limit=65536)
    assert_container_removed(live_profile, identity, tmp_path)
    assert exit_code == 0, (out.decode(), err.decode())
    rows = [s.removeprefix("JEVOPS_ISOLATION_CANARY:") for s in out.decode().splitlines()
            if s.startswith("JEVOPS_ISOLATION_CANARY:")]
    assert len(rows) == 1, out.decode()
    result = json.loads(rows[0])
    record_property("isolation_canary", json.dumps({"policy": live_profile.policy, "observed": result}, sort_keys=True))
    assert int(result["memory"]) == live_profile.memory_bytes
    assert int(result["swap"]) == 0
    assert int(result["pids"]) == live_profile.pids
    quota, period = map(int, result["cpu"].split())
    assert quota == period  # one CPU, regardless of daemon's selected period
    status = dict(line.split(":", 1) for line in result["process_status"].splitlines())
    assert int(status["NoNewPrivs"]) == 1 and int(status["Seccomp"]) == 2
    for field in ("CapEff", "CapPrm", "CapInh", "CapBnd", "CapAmb"):
        assert int(status[field].strip(), 16) == 0
    expected_id = 0 if live_profile.mount_owner_user else 65534
    assert list(map(int, status["Uid"].split())) == [expected_id] * 4
    assert list(map(int, status["Gid"].split())) == [expected_id] * 4
    if live_profile.mount_owner_user:
        for field, host_id in (("uid_map", os.getuid()), ("gid_map", os.getgid())):
            rows = [tuple(map(int, line.split())) for line in result[field].splitlines()]
            assert host_id != 0 and rows[0] == (0, host_id, 1), result
            assert all(outer != 0 for inner, outer, size in rows), result
    assert marker.read_text() == "read-only input" and hidden.read_text() == "host only"
    assert driver.read_text() == code


@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.parametrize("candidate,expected", [
    ("theorem sample (h : True) : True := by exact h", "VERIFIED"),
    ("theorem sample (h : True) : 1 = 1 := by rfl", "REJECTED"),
    ("theorem sample (h : True) : True := by skip", "REJECTED"),
])
def test_live_isolated_proof_boundary(live_profile, live_lean, tmp_path, candidate_first, candidate, expected):
    binding = native.ProjectBinding(VersionPin("v4.26.0", "test"), live_lean, tmp_path, "", project_backed=False)
    payload = {"request_id": "isolated-native-test", "target": "sample", "max_heartbeats": 200000,
        "candidate_first": candidate_first, "prefix": "",
        "reference": "theorem sample (h : True) : True := by have hp := h; exact hp", "candidate": candidate}
    data, code = native.run_native(binding, payload, timeout=60, isolation=live_profile)
    assert code == 0 and data["report"]["outcome"] == expected
    assert data["branch_order"] == ("candidate-first" if candidate_first else "reference-first")
    if expected == "VERIFIED":
        assert data["report"]["target_absent_before"] and data["report"]["type_preserved"]
        assert data["report"]["axioms"] == []


def test_live_running_worker_is_removed_after_timeout(live_profile, live_lean, tmp_path):
    driver = tmp_path / "Sleeper.lean"
    driver.write_text("def main : IO Unit := do\n  IO.sleep 30000\n")
    identity = None
    with pytest.raises(TimeoutError):
        with live_profile.launch(live_lean, (), driver, scratch=str(tmp_path),
                                 deadline=time.monotonic() + 60) as (command, env):
            identity = command[-1]
            isolated.capture_process(command, env=env, timeout=8, output_limit=65536)
    assert identity is not None
    assert_container_removed(live_profile, identity, tmp_path)


def test_live_worker_is_removed_after_output_limit(live_profile, live_lean, tmp_path):
    driver = tmp_path / "Noisy.lean"
    driver.write_text('def main : IO Unit := do\n  for _ in [:1000] do\n    IO.println "canary output"\n')
    with pytest.raises(ValueError, match="output byte budget"):
        with live_profile.launch(live_lean, (), driver, scratch=str(tmp_path),
                                 deadline=time.monotonic() + 60) as (command, env):
            identity = command[-1]
            isolated.capture_process(command, env=env, timeout=20, output_limit=256)
    assert_container_removed(live_profile, identity, tmp_path)


def test_live_prepared_fuse_import_stage(live_profile, live_lean, tmp_path, monkeypatch):
    """One trusted fixture build, one isolated proof check; never an Arena score."""
    from dataclasses import asdict
    from jevops import arena_prepare as prep
    root_value = os.environ.get("JEVOPS_ARENA_PREPARATION_ROOT")
    if not root_value:
        pytest.skip("explicit JEVOPS_ARENA_PREPARATION_ROOT required for bounded FUSE staging")
    root = Path(root_value)
    config = json.loads((root / "preparation.json").read_text())
    mount = prep.validate_volume(config)
    workspace = Path(tempfile.mkdtemp(prefix="import-stage-canary-", dir=mount / "tmp"))
    imports = workspace / "imports"; imports.mkdir()
    source = workspace / "StageFixture.lean"
    source.write_text("theorem stagedIdentity (h : True) : True := h\n")
    monkeypatch.setenv("DOCKER_HOST", "unix://" + str(live_profile.socket))
    # Trusted build uses the existing capped-volume runner, NOT a UID-zero
    # fallback in the untrusted verifier. Compiler/import mounts remain read-only.
    build = prep.run(config, [str(live_lean), "-o", str(imports / "StageFixture.olean"), str(source)],
        cwd=workspace, readonly=(live_lean.parent.parent,), timeout=60, image=live_profile.image_id)
    assert build["exit_code"] == 0 and not build["timed_out"], build
    stage = prep.stage_imports(config, (imports,), name=workspace.name, max_bytes=8_000_000)
    pin = VersionPin("v4.26.0", "staging-synthetic-canary")
    binding = native.ProjectBinding(pin, live_lean, workspace, "import StageFixture\n",
                                   (imports,), project_backed=False)
    rebound = binding.with_staged_imports(Path(stage["manifest"]), stage["manifest_sha256"])
    mounts = live_profile.mounts(rebound.lean, rebound.search_paths, native.DRIVER)
    assert all(not Path(src).is_relative_to(mount) for src, _ in mounts)
    statement = "theorem staged_sample (h : True) : True"
    record = {"name": "staged_sample", "statement": statement,
              "src": statement + " := by exact stagedIdentity h", "version_info": [{pin.lean_tag: pin.git_commit}]}
    with prep.exclusive(root / "single-build.lock"):
        adapter = native.NativeLeanVerifier({pin: rebound}, max_processes=1, isolation=live_profile)
        context = adapter.context(record)
        receipt = adapter(VerificationRequest(context, record["src"], pin))
        assert receipt.outcome == Outcome.VERIFIED, receipt
        assert adapter.processes == 1
        rebound.staged_imports.validate()
    assert prep.validate_volume(config) == mount
    report = {"schema": "jevops-arena-staging-canary/v1", "arena_problem": False,
        "build": build, "stage": stage, "context": asdict(context), "receipt": asdict(receipt),
        "verifier_process_attempts": adapter.processes, "official_score": None,
        "promoted": False, "source_execution_attested": False, "metric_integrity_established": False}
    report_path = mount / "logs" / (workspace.name + ".json")
    with report_path.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print("STAGING_CANARY_REPORT=" + str(report_path))


def test_live_project_original_control(live_profile, tmp_path):
    """One pinned corpus original, not a refactor, repeated trial or full score.

    Uses only already host-readable compiler/import trees. The prepared FUSE
    mount is available to the supervisor, never to the non-root verifier.
    """
    from dataclasses import asdict
    import hashlib
    from jevops import arena_prepare as prep
    root_value = os.environ.get("JEVOPS_ARENA_PREPARATION_ROOT")
    projects_value = os.environ.get("JEVOPS_ARENA_CONTROL_PROJECTS")
    if not root_value or not projects_value:
        pytest.skip("explicit preparation root and JEVOPS_ARENA_CONTROL_PROJECTS required")
    root = Path(root_value)
    config = json.loads((root / "preparation.json").read_text())
    name = os.environ.get("JEVOPS_ARENA_CONTROL_PROBLEM", "Core.InitsUpdatesComm")
    tag = os.environ.get("JEVOPS_ARENA_CONTROL_TAG", "v4.26.0")
    with prep.exclusive(root / "single-build.lock"):
        mount = prep.validate_volume(config)
        corpus_bytes = native.CORPUS.read_bytes()
        records = [json.loads(line) for line in corpus_bytes.splitlines() if line.strip()]
        records_for_name = [r for r in records if r["name"] == name]
        assert len(records_for_name) == 1, "one exact corpus task required"
        record = records_for_name[0]
        pins = [VersionPin(t, commit) for row in record["version_info"] for t, commit in row.items() if t == tag]
        assert len(pins) == 1, "one exact corpus version required"
        pin = pins[0]
        projects = json.loads(Path(projects_value).read_text())
        matching = [p for p in projects if (p["repository"], p["lean_tag"], p["git_commit"]) ==
                    (record["url"], pin.lean_tag, pin.git_commit)]
        assert len(matching) == 1, "one explicit prepared project required"
        binding = native.project_binding(record, pin, matching[0], Path(os.environ["ELAN_HOME"]))
        mounts = live_profile.mounts(binding.lean, binding.search_paths, native.DRIVER)
        assert not any(Path(src).is_relative_to(mount) for src, _ in mounts), "unstaged FUSE inputs"
        assert binding.project_backed and binding.lake is not None
        adapter = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=120,
                                            isolation=live_profile)
        context = adapter.context({**record, "version_info": [{tag: pin.git_commit}]})
        receipt = adapter(VerificationRequest(context, record["src"], pin))
        report = {"schema": "jevops-arena-isolated-original-control/v1", "arena_problem": True,
            "name": name, "pin": asdict(pin), "project": matching[0],
            "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
            "task_required_version_checks": sum(len(row) for row in record["version_info"]),
            "selected_version_checks": 1, "candidate_is_original": True,
            "context": asdict(context), "receipt": asdict(receipt),
            "isolation_policy": live_profile.policy, "mounts": mounts,
            "verifier_process_attempts": adapter.processes, "new_builds": 0,
            "live_model_calls": 0, "official_score": None, "promoted": False,
            "source_execution_attested": False, "metric_integrity_established": False}
        report_path = mount / "logs" / f"isolated-project-control-{time.time_ns()}.json"
        with report_path.open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
        prep.validate_volume(config)
    print("PROJECT_CONTROL_REPORT=" + str(report_path))
    assert receipt.outcome == Outcome.VERIFIED, receipt
    assert adapter.processes == 1
