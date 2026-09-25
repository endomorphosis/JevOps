"""Opt-in rootless Docker execution profile for the existing native verifier.

Only pinned local images and a caller-owned Unix socket; no pulls or builds.
Protects host resources, not the honesty of metaprograms sharing a Lean process.
The daemon, image, kernel and explicitly mounted compiler/imports are trusted.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import uuid

PROFILE = "jevops-arena-rootless-docker/v1"
OWNER_PROFILE = "jevops-arena-rootless-mount-owner/v1"
OWNER_LABEL = "jevops.arena-verifier.owner"
CONTROL_LIMIT = 1_048_576


class IsolationUnavailable(RuntimeError):
    """A required execution capability is missing; never a proof rejection."""


class IsolationError(RuntimeError):
    """An execution invariant or ownership-aware cleanup failed."""


def capture_process(command, *, stdin=None, env, cwd=None, timeout: float, output_limit: int):
    """Bound both pipes and reap only the process group we actually launched."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise TimeoutError("native verifier wall-time budget")
    with subprocess.Popen(command, cwd=cwd, env=env, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as proc:
        output, errors, total = bytearray(), bytearray(), 0
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                selector.register(proc.stderr, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("native verifier wall-time budget")
                    for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > output_limit:
                            raise ValueError("native verifier output byte budget")
                        (output if key.fileobj is proc.stdout else errors).extend(chunk)
            code = proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            return bytes(output), bytes(errors), code
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()


def _path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or any(c in str(path) for c in ",\n\r\0"):
        raise ValueError("absolute unambiguous isolation path required")
    resolved = path.resolve(strict=True)
    if any(c in str(resolved) for c in ",\n\r\0"):
        raise ValueError("resolved isolation path must also be unambiguous")
    return resolved


@dataclass(frozen=True)
class DockerIsolation:
    socket: Path
    image_id: str
    executable: Path = Path("/usr/bin/docker")
    memory_bytes: int = 2_147_483_648
    tmp_bytes: int = 67_108_864
    pids: int = 64
    mount_owner_user: bool = False

    def __post_init__(self):
        if type(self.mount_owner_user) is not bool:
            raise ValueError("explicit boolean mount-owner opt-in required")
        if self.mount_owner_user and (os.getuid() == 0 or os.getgid() == 0):
            raise IsolationUnavailable("mount-owner profile requires an unprivileged host UID/GID")
        if not isinstance(self.image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id):
            raise ValueError("explicit local immutable image ID required; tags/pulls are not allowed")
        for name, low, high in (("memory_bytes", 268_435_456, 8_589_934_592),
                                ("tmp_bytes", 1_048_576, 268_435_456), ("pids", 16, 256)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"bounded integer {name} required")
        if self.tmp_bytes > self.memory_bytes // 2:
            raise ValueError("temporary filesystem must fit within memory allowance")
        for name in ("socket", "executable"):
            object.__setattr__(self, name, _path(getattr(self, name)))
        self.validate_paths()

    def validate_paths(self):
        socket = self.socket.stat()
        if not stat.S_ISSOCK(socket.st_mode) or socket.st_uid != os.getuid():
            raise IsolationUnavailable("caller-owned local Docker socket required")
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise IsolationUnavailable("explicit Docker executable missing")

    @property
    def worker_user(self) -> str:
        # Rootless container UID zero maps to the unprivileged daemon owner.
        # This is a distinct opt-in policy, NEVER an automatic import fallback.
        return "0:0" if self.mount_owner_user else "65534:65534"

    @property
    def policy(self) -> dict:
        return {"profile": OWNER_PROFILE if self.mount_owner_user else PROFILE,
                "worker_user": self.worker_user, "socket": str(self.socket), "image_id": self.image_id,
                "executable": str(self.executable), "memory_bytes": self.memory_bytes,
                "tmp_bytes": self.tmp_bytes, "pids": self.pids, "nano_cpus": 1_000_000_000,
                "network": "none", "rootless_required": True, "read_only_inputs": True,
                "separate_proof_checker": False}

    @property
    def client(self) -> list[str]:
        return [str(self.executable), "--host", "unix://" + str(self.socket)]

    @staticmethod
    def client_env(scratch: str) -> dict:
        # No inherited Docker context, daemon/TLS options, proxy or credentials.
        return {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": scratch, "LANG": "C.UTF-8"}

    def control(self, args: list[str], *, scratch: str, deadline: float) -> str:
        output, errors, code = capture_process([*self.client, *args], env=self.client_env(scratch),
            timeout=min(15, deadline - time.monotonic()), output_limit=CONTROL_LIMIT)
        if code:
            # Do not echo arbitrary image metadata/environment into a receipt.
            raise IsolationUnavailable(f"Docker {args[0]} failed (exit {code}): " + errors.decode(errors="replace")[:300])
        return output.decode()

    def preflight(self, *, scratch: str, deadline: float):
        self.validate_paths()
        info = json.loads(self.control(["info", "--format", "{{json .}}"], scratch=scratch, deadline=deadline))
        security = info.get("SecurityOptions") or []
        if ("name=rootless" not in security or "name=cgroupns" not in security
                or not any(s.startswith("name=seccomp,") for s in security)
                or info.get("CgroupVersion") != "2"
                or any(info.get(k) is not True for k in ("MemoryLimit", "SwapLimit", "PidsLimit", "CpuCfsQuota"))):
            raise IsolationUnavailable("rootless Docker, seccomp and cgroup-v2 CPU/memory/swap/PID controls required")
        image = json.loads(self.control(["image", "inspect", self.image_id, "--format", "{{json .}}"],
                                       scratch=scratch, deadline=deadline))
        if image.get("Id") != self.image_id or image.get("Os") != "linux" or image.get("Config", {}).get("Volumes"):
            raise IsolationUnavailable("matching local Linux image without implicit writable volumes required")

    def mounts(self, lean: Path, search_paths: tuple[Path, ...], driver: Path) -> list[tuple[str, str]]:
        lean, driver = _path(lean), _path(driver)
        if lean.name != "lean" or lean.parent.name != "bin" or not lean.is_file() or not driver.is_file():
            raise ValueError("explicit pinned bin/lean and regular driver required")
        library = _path(lean.parent.parent / "lib")
        if not library.is_dir() or len(search_paths) > 64:
            raise ValueError("bounded compiled dependency directories required")
        mounts = [(str(lean), "/toolchain/bin/lean"), (str(library), "/toolchain/lib"),
                  (str(driver), "/driver/ArenaCheck.lean")]
        for i, path in enumerate(search_paths):
            path = _path(path)
            if not path.is_dir() or len(path.parts) < 4 or path == self.socket.parent:
                raise ValueError("narrow explicit compiled-import directory required")
            mounts.append((str(path), f"/deps/{i}"))
        return mounts

    def create_args(self, mounts: list[tuple[str, str]], owner: str) -> list[str]:
        if not re.fullmatch(r"[0-9a-f]{32}", owner):
            raise ValueError("unique execution owner required")
        args = ["create", "--pull=never", "--name", "jevops-check-" + owner,
                "--label", OWNER_LABEL + "=" + owner, "--read-only", "--network=none", "--ipc=none",
                "--cgroupns=private", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--user=" + self.worker_user, "--log-driver=none", "--no-healthcheck", "--interactive",
                "--pids-limit=" + str(self.pids), "--cpus=1", "--memory=" + str(self.memory_bytes),
                "--memory-swap=" + str(self.memory_bytes), "--ulimit=core=0:0", "--ulimit=nofile=128:128",
                "--tmpfs", f"/tmp:rw,nosuid,nodev,noexec,size={self.tmp_bytes},mode=1777",
                "--workdir=/tmp", "--entrypoint=/toolchain/bin/lean"]
        for src, dest in mounts:
            args += ["--mount", f"type=bind,src={src},dst={dest},readonly"]
        for key, value in self.container_env(mounts).items():
            args += ["--env", key + "=" + value]
        return [*args, self.image_id, "--run", "/driver/ArenaCheck.lean"]

    @staticmethod
    def container_env(mounts):
        return {"HOME": "/tmp", "TMPDIR": "/tmp", "PATH": "/toolchain/bin:/usr/bin:/bin",
                "LEAN_PATH": os.pathsep.join(dest for _, dest in mounts if dest.startswith("/deps/")),
                "LEAN_NUM_THREADS": "1", "LANG": "C.UTF-8"}

    def inspect(self, identity: str, *, scratch: str, deadline: float) -> dict:
        return json.loads(self.control(["container", "inspect", identity, "--format", "{{json .}}"],
                                       scratch=scratch, deadline=deadline))

    def verify_created(self, data: dict, identity: str, owner: str, mounts: list[tuple[str, str]]):
        config, host = data["Config"], data["HostConfig"]
        expected = {(src, dest, False) for src, dest in mounts}
        actual = {(m["Source"], m["Destination"], m["RW"]) for m in data["Mounts"] if m["Type"] == "bind"}
        env = dict(item.split("=", 1) for item in config["Env"])
        if (data["Id"] != identity or data["Image"] != self.image_id or config["Labels"].get(OWNER_LABEL) != owner
                or config["User"] != self.worker_user or config["Entrypoint"] != ["/toolchain/bin/lean"]
                or config["Cmd"] != ["--run", "/driver/ArenaCheck.lean"] or config["WorkingDir"] != "/tmp"
                or env != self.container_env(mounts) or len(config["Env"]) != len(env)
                or host["ReadonlyRootfs"] is not True or host["Privileged"] is not False
                or host["NetworkMode"] != "none" or host["IpcMode"] != "none"
                or host["PidMode"] not in ("", "private") or host["UTSMode"] not in ("", "private")
                or host.get("UsernsMode") not in (None, "", "private") or host.get("GroupAdd")
                or host["CgroupnsMode"] != "private" or host["CapDrop"] != ["ALL"]
                or host.get("CapAdd") or host.get("Devices") or host.get("DeviceRequests")
                or host["SecurityOpt"] != ["no-new-privileges"]
                or host["Memory"] != self.memory_bytes or host["MemorySwap"] != self.memory_bytes
                or host["NanoCpus"] != 1_000_000_000 or host["PidsLimit"] != self.pids
                or host["Tmpfs"] != {"/tmp": f"rw,nosuid,nodev,noexec,size={self.tmp_bytes},mode=1777"}
                or host["LogConfig"]["Type"] != "none" or actual != expected
                or len([m for m in data["Mounts"] if m["Type"] == "bind"]) != len(mounts)
                or any(m["Type"] != "bind" and (m["Type"] != "tmpfs" or m["Destination"] != "/tmp")
                       for m in data["Mounts"])
                or {u["Name"]: (u["Soft"], u["Hard"]) for u in host["Ulimits"]}
                   != {"core": (0, 0), "nofile": (128, 128)}):
            raise IsolationError("created container differs from required isolation policy")

    def cleanup(self, identity: str | None, owner: str, *, scratch: str):
        # Fixed additional cleanup allowance; timeout never means leave the worker running.
        deadline = time.monotonic() + 15
        if identity is None:
            # Creation can time out after the daemon committed it. Resolve only
            # our unique name; ownership must still match before removal by ID.
            identity = self.control(["container", "ls", "--all", "--no-trunc", "--filter",
                "name=^/jevops-check-" + owner + "$", "--format", "{{.ID}}"],
                scratch=scratch, deadline=deadline).strip()
            if not identity:
                return
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise IsolationError("ambiguous owned container identity; left untouched")
        data = self.inspect(identity, scratch=scratch, deadline=deadline)
        if data.get("Id") != identity or (data.get("Config", {}).get("Labels") or {}).get(OWNER_LABEL) != owner:
            raise IsolationError("container ownership mismatch; left untouched")
        self.control(["container", "rm", "--force", identity], scratch=scratch, deadline=deadline)

    @contextmanager
    def launch(self, lean: Path, search_paths: tuple[Path, ...], driver: Path, *, scratch: str, deadline: float):
        scratch = str(_path(Path(scratch)))
        self.preflight(scratch=scratch, deadline=deadline)
        mounts, owner = self.mounts(lean, search_paths, driver), uuid.uuid4().hex
        # Override Docker's special /etc mounts with read-only regular files,
        # not writable daemon-managed files outside the bounded tmpfs.
        empty = Path(scratch) / "empty-network-config"
        with empty.open("xb"):
            pass
        empty.chmod(0o444)
        mounts.extend((str(empty), "/etc/" + name) for name in ("hosts", "hostname", "resolv.conf"))
        identity = None
        try:
            created = self.control(self.create_args(mounts, owner), scratch=scratch, deadline=deadline).strip()
            if not re.fullmatch(r"[0-9a-f]{64}", created):
                raise IsolationError("Docker returned no immutable container identity")
            identity = created
            self.verify_created(self.inspect(identity, scratch=scratch, deadline=deadline), identity, owner, mounts)
            yield [*self.client, "start", "--attach", "--interactive", identity], self.client_env(scratch)
        finally:
            try:
                self.cleanup(identity, owner, scratch=scratch)
            except Exception as exc:
                raise IsolationError(f"owned container cleanup failed: jevops-check-{owner} ({identity}): {type(exc).__name__}") from exc
