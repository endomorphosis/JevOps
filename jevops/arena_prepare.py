"""Opt-in, disk-bounded Arena preparation on Linux (fuse2fs + Docker).

This runner never installs into the shared cache. It deliberately does not choose
revisions or promote build success to proof evidence. Commands run sequentially
with only the fixed-size volume writable; source/cache mounts are read-only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SCHEMA = "jevops-arena-preparation/v1"
MAX_BYTES = 50_000_000_000
OVERHEAD_BYTES = 200_000_000


def volume_bytes(max_bytes: int) -> int:
    if type(max_bytes) is not int or not OVERHEAD_BYTES + 32_000_000 <= max_bytes <= MAX_BYTES:
        raise ValueError("disk allowance must exceed 232 MB and not exceed 50 GB")
    return ((max_bytes - OVERHEAD_BYTES) // 4096) * 4096


@contextmanager
def exclusive(path: Path):
    """Kernel-held lock, not check-then-write; released on descriptor close."""
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def initialize(root: Path, fuse2fs: Path, max_bytes: int = MAX_BYTES) -> dict:
    size = volume_bytes(max_bytes)
    root = root.resolve(strict=True)
    image, mount = root / "volume.ext4", root / "work"
    if image.exists() or mount.exists() or (root / "preparation.json").exists():
        raise ValueError("refusing to overwrite a preparation workspace")
    mount.mkdir()
    # mke2fs creates the sparse, fixed-capacity image; no privileged host mount.
    subprocess.run(["/usr/sbin/mke2fs", "-q", "-t", "ext4", "-m", "0", "-b", "4096",
                    "-O", "^has_journal", "-E", f"root_owner={os.getuid()}:{os.getgid()}",
                    str(image), str(size // 4096)], check=True)
    # fakeroot avoids fuse2fs rejecting Git's O_CREAT|O_RDWR with mode 0444.
    # It affects permission checks only inside this private, capped filesystem.
    subprocess.run([str(fuse2fs.resolve(strict=True)), "-o", "rw,nosuid,nodev,fakeroot",
                    str(image), str(mount)], check=True)
    config = {"schema": SCHEMA, "root": str(root), "image": str(image), "mount": str(mount),
              "image_bytes": size, "max_bytes": max_bytes, "overhead_reservation": OVERHEAD_BYTES,
              "fuse2fs": str(fuse2fs.resolve()), "image_inode": image.stat().st_ino}
    validate_volume(config)
    for name in ("home", "tmp", "logs", "projects", "elan", "cache"):
        (mount / name).mkdir()
    with (root / "preparation.json").open("x") as stream:
        json.dump(config, stream, indent=2)
    return config


def validate_volume(config: dict) -> Path:
    """Fail closed when unmounted: never accidentally build into the host dir."""
    if config.get("schema") != SCHEMA or config["image_bytes"] != volume_bytes(config["max_bytes"]):
        raise ValueError("invalid preparation configuration")
    root = Path(config["root"]).resolve(strict=True)
    image, mount = Path(config["image"]), Path(config["mount"])
    if (image != root / "volume.ext4" or mount != root / "work" or image.is_symlink()
            or mount.is_symlink() or image.stat().st_size != config["image_bytes"]
            or image.stat().st_ino != config["image_inode"] or not os.path.ismount(mount)):
        raise ValueError("fixed-size volume missing, changed, or unmounted")
    info = json.loads(subprocess.check_output(
        ["findmnt", "--json", "--target", str(mount), "--output", "SOURCE,TARGET,FSTYPE"], text=True))
    rows = info["filesystems"]
    if len(rows) != 1 or rows[0] != {"source": str(image), "target": str(mount), "fstype": "fuse.ext4"}:
        raise ValueError("unexpected preparation mount")
    stat = os.statvfs(mount)
    if stat.f_blocks * stat.f_frsize > config["image_bytes"]:
        raise ValueError("filesystem capacity exceeds allowance")
    # Bootstrap binaries, package archive and probe images live outside the
    # volume. Keep 20 MB of the reservation unused for container metadata.
    preparation_overhead(root, mount, image)
    return mount


def preparation_overhead(root: Path, mount: Path, image: Path) -> int:
    """Allocated external bytes, including any explicitly staged import copies."""
    overhead = 0
    pending = [root]
    entries = 0
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path in (mount, image):
                continue
            entries += 1
            if entries > 10_000:
                raise ValueError("preparation metadata entry limit")
            overhead += path.lstat().st_blocks * 512
            if overhead > OVERHEAD_BYTES - 20_000_000:
                raise ValueError("preparation overhead allowance exhausted")
            if path.is_dir() and not path.is_symlink():
                pending.append(path)
    return overhead


def _stage_limits(max_bytes: int, timeout: int) -> None:
    from .arena_staging import MAX_BYTES as STAGE_LIMIT
    if type(max_bytes) is not int or not 0 <= max_bytes <= STAGE_LIMIT:
        raise ValueError("bounded integer import staging allowance required")
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("import staging timeout must be 1..3600 seconds")


def _import_plan(config: dict, mount: Path, sources: tuple[Path, ...], *,
                 max_bytes: int, deadline: float, selection=None) -> dict:
    """Caller holds the preparation lock. No payload reads or reservations."""
    from .arena_staging import MAX_BYTES as STAGE_LIMIT, metadata_inventory, selected_metadata, reservation
    entries = (metadata_inventory(sources, deadline=deadline) if selection is None else
               selected_metadata(sources, selection, deadline=deadline))
    payload = sum(e.get("bytes", 0) for e in entries)
    required = reservation(entries)
    overhead = preparation_overhead(Path(config["root"]), mount, Path(config["image"]))
    headroom = OVERHEAD_BYTES - 20_000_000 - overhead
    reasons = []
    if payload > STAGE_LIMIT:
        reasons.append("import byte budget")
    if required > max_bytes:
        reasons.append("requested reservation budget")
    if required > headroom:
        reasons.append("reserved preparation headroom")
    return {"schema": "jevops-arena-import-plan/v1",
            "status": "WOULD_FIT" if not reasons else "DOES_NOT_FIT",
            "source_paths": list(map(str, sources)), "entries": len(entries),
            "files": sum(e["kind"] == "file" for e in entries), "payload_bytes": payload,
            "required_reservation_bytes": required, "max_bytes": max_bytes,
            "preparation_overhead_bytes": overhead, "available_headroom_bytes": headroom,
            "reasons": reasons, "content_validated": False, "bytes_reserved": 0,
            "proofs_verified": 0}


def plan_imports(config: dict, sources: tuple[Path, ...], *, max_bytes: int = 0,
                 timeout: int = 120, selection=None) -> dict:
    """Metadata-only staging feasibility; not a durable reservation or manifest.

    Reaching an entry/path/deadline limit raises instead of reporting a partial
    inventory as complete. stage_imports always checks the current inputs anew.
    """
    _stage_limits(max_bytes, timeout)
    deadline = time.monotonic() + timeout
    root = Path(config["root"]).resolve(strict=True)
    with exclusive(root / "single-build.lock"):
        return _import_plan(config, validate_volume(config), sources,
                            max_bytes=max_bytes, deadline=deadline, selection=selection)


def stage_imports(config: dict, sources: tuple[Path, ...], *, name: str,
                  max_bytes: int = 0, timeout: int = 120, selection=None, scope_sha256=None) -> dict:
    """Copy small import trees into the EXISTING 200 MB overhead reservation.

    Large libraries/toolchains fail closed; this never enlarges the volume,
    enables allow_other, changes source permissions, or allocates a second cap.
    """
    from .arena_staging import inventory, reservation, write_stage
    _stage_limits(max_bytes, timeout)
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("unique bounded import stage name required")
    if max_bytes == 0:
        raise ValueError("import staging budget exhausted")
    if ((selection is None) != (scope_sha256 is None) or
            (scope_sha256 is not None and (not isinstance(scope_sha256, str)
             or not re.fullmatch("[0-9a-f]{64}", scope_sha256)))):
        raise ValueError("selected imports require an original context scope hash")
    deadline = time.monotonic() + timeout
    root = Path(config["root"]).resolve(strict=True)
    if root.stat().st_uid != os.getuid():
        raise ValueError("caller-owned preparation root required for staging")
    with exclusive(root / "single-build.lock"):
        mount = validate_volume(config)
        base = root / "import-stages"
        if base.is_symlink() or (base.exists() and (not base.is_dir() or base.stat().st_uid != os.getuid()
                or base.stat().st_mode & 0o077)):
            raise ValueError("invalid import staging root")
        destination = base / name
        if destination.exists() or destination.is_symlink():
            raise ValueError("refusing to overwrite import stage")
        if any(p.is_relative_to(base) for p in sources):
            raise ValueError("cannot stage existing staged inputs")
        plan = _import_plan(config, mount, sources, max_bytes=max_bytes, deadline=deadline, selection=selection)
        if plan["reasons"]:
            raise ValueError("import staging exceeds reserved preparation headroom: " + "; ".join(plan["reasons"]))
        entries = inventory(sources, deadline=deadline, selection=selection)
        reserved = reservation(entries)
        overhead = preparation_overhead(root, mount, Path(config["image"]))
        if reserved > max_bytes or overhead + reserved > OVERHEAD_BYTES - 20_000_000:
            raise ValueError("import staging exceeds reserved preparation headroom")
        base.mkdir(mode=0o700, exist_ok=True)
        stage = write_stage(destination, sources, entries, deadline=deadline,
                            selection=selection, scope_sha256=scope_sha256)
        validate_volume(config)
        return {"schema": "jevops-arena-import-staging-result/v1", "status": "STAGED_INPUTS_ONLY",
                "manifest": str(stage.manifest), "manifest_sha256": stage.manifest_sha256,
                "source_paths": list(map(str, sources)), "search_paths": list(map(str, stage.paths)),
                "reserved_bytes": reserved, "max_bytes": max_bytes, "proofs_verified": 0,
                "preparation_overhead_bytes": preparation_overhead(root, mount, Path(config["image"]))}


def container_args(config: dict, *, image: str, rootless: bool, cwd: Path,
                   readonly: tuple[Path, ...], network: bool, command: list[str]) -> list[str]:
    mount = Path(config["mount"])
    if (not command or len(command) > 256 or any(not isinstance(a, str) or "\0" in a for a in command)
            or sum(len(a.encode()) for a in command) > 32768):
        raise ValueError("bounded argument vector required")
    if "," in str(mount) or not cwd.resolve(strict=True).is_relative_to(mount):
        raise ValueError("command and working directory inside volume required")
    name = "jevops-arena-" + hashlib.sha256(str(mount).encode()).hexdigest()[:16]
    args = ["docker", "run", "--rm", "--pull=never", "--name", name, "--read-only",
            "--log-driver=none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user", "0:0" if rootless else f"{os.getuid()}:{os.getgid()}",
            "--network", "bridge" if network else "none", "--shm-size=16m",
            "--pids-limit=512", "--cpus=4", "--memory=16g", "--workdir", str(cwd)]
    for src, dest in ((mount, mount), (mount / "tmp", Path("/tmp"))):
        args += ["--mount", f"type=bind,src={src},dst={dest}"]
    for path in (Path("/usr"), Path("/etc/ssl/certs"), *readonly):
        path = path.resolve(strict=True)
        if "," in str(path) or path == Path("/") or path.is_relative_to(mount) or mount.is_relative_to(path):
            raise ValueError("unsafe or overlapping read-only mount")
        args += ["--mount", f"type=bind,src={path},dst={path},readonly"]
    for key, value in {"HOME": str(mount / "home"), "TMPDIR": str(mount / "tmp"),
                       "XDG_CACHE_HOME": str(mount / "cache"), "ELAN_HOME": str(mount / "elan"),
                       "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
                       "LEAN_NUM_THREADS": "4", "LANG": "C.UTF-8"}.items():
        args += ["--env", f"{key}={value}"]
    return [*args, image, *command]


def remove_owned_container(name: str, owner: str) -> str:
    """Never remove a container merely because it acquired our proposed name."""
    try:
        result = subprocess.run(["docker", "container", "inspect", "--format", "{{json .}}", name],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            return "absent_or_daemon_unavailable"
        info = json.loads(result.stdout)
        identity = info.get("Id", "")
        labels = info.get("Config", {}).get("Labels") or {}
        if (labels.get("jevops.preparation.owner") != owner
                or not isinstance(identity, str) or not re.fullmatch("[0-9a-f]{64}", identity)):
            return "not_owned_left_untouched"
        result = subprocess.run(["docker", "rm", "-f", identity], capture_output=True, timeout=30)
        return "removed_owned_container" if result.returncode == 0 else "owned_cleanup_failed"
    except (subprocess.SubprocessError, OSError, ValueError, AttributeError):
        return "cleanup_unavailable"


def run(config: dict, command: list[str], *, cwd: Path | None = None,
        readonly: tuple[Path, ...] = (), network: bool = False, timeout: int = 3600,
        image: str = "ubuntu:24.04") -> dict:
    if type(timeout) is not int or not 1 <= timeout <= 28800:
        raise ValueError("wall timeout must be 1..28800 seconds")
    root = Path(config["root"])
    with exclusive(root / "single-build.lock"):
        mount = validate_volume(config)
        image_id = subprocess.check_output(["docker", "image", "inspect", image,
                                           "--format", "{{.Id}}"], text=True).strip()
        security = json.loads(subprocess.check_output(["docker", "info", "--format",
                                                       "{{json .SecurityOptions}}"], text=True))
        args = container_args(config, image=image_id, rootless="name=rootless" in security,
                              cwd=cwd or mount, readonly=readonly, network=network, command=command)
        # The stable Docker name also rejects overlap after a supervisor crash.
        # Never remove a pre-existing container: it might still own a build.
        name = args[args.index("--name") + 1]
        prior = subprocess.run(["docker", "container", "inspect", name], capture_output=True)
        if prior.returncode == 0:
            raise ValueError("previous preparation container exists; inspect before resuming")
        run_id = str(time.time_ns())
        image_position = len(args) - len(command) - 1
        args[image_position:image_position] = ["--label", "jevops.preparation.owner=" + run_id]
        log = mount / "logs" / (run_id + ".log")
        start = time.monotonic()
        print(f"preparation {run_id}: {log}", file=sys.stderr, flush=True)
        timed_out = False
        with log.open("xb") as stream:
            process = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT)
            try:
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    code, timed_out = 124, True
            finally:
                # Check ownership label, then remove by immutable container ID.
                cleanup = remove_owned_container(name, run_id)
                if process.poll() is None:
                    process.kill()
                process.wait()
        stat = os.statvfs(mount)
        report = {"schema": SCHEMA, "run_id": run_id, "command": command, "exit_code": code,
                  "timed_out": timed_out,
                  "cleanup": cleanup,
                  "wall_seconds": time.monotonic() - start, "log": str(log), "image_id": image_id,
                  "network_allowed": network, "build_concurrency": 1, "official_score": None,
                  "volume_capacity_bytes": stat.f_blocks * stat.f_frsize,
                  "volume_used_bytes": (stat.f_blocks - stat.f_bfree) * stat.f_frsize}
        with (mount / "logs" / (run_id + ".json")).open("x") as stream:
            json.dump(report, stream, indent=2)
        return report


def export_projects(state_root: Path, project_roots: list[Path]) -> list[dict]:
    """Overlay explicitly prepared exact pins on the read-only cache inventory.

    This checks checkout/lockfile identities, NOT proof compilation or scores.
    Unavailable original inventory entries are retained, not quietly dropped.
    """
    from .arena_lean import CORPUS, _check_project, _git, discover_projects, lake_environment
    from .lean import VersionPin
    records = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    projects = discover_projects(records, state_root)
    seen = set()
    for path in project_roots:
        path = path.resolve(strict=True)
        commit = _git(path, "rev-parse", "HEAD")
        repository = _git(path, "remote", "get-url", "origin").removesuffix(".git")
        matches = [p for p in projects if p["repository"] == repository and p["git_commit"] == commit]
        if len(matches) != 1 or (repository, commit) in seen:
            raise ValueError("prepared root must identify one unique corpus pin")
        project = matches[0]
        _check_project(path, VersionPin(project["lean_tag"], commit))
        lake_environment(path)
        project["root"] = str(path)
        seen.add((repository, commit))
    return projects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init", action="store_true")
    mode.add_argument("--export-projects", action="store_true")
    mode.add_argument("--stage-imports", action="store_true")
    mode.add_argument("--plan-imports", action="store_true",
                      help="metadata-only feasibility; no copies, hashes or reservation")
    parser.add_argument("--fuse2fs", type=Path)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--readonly", type=Path, action="append", default=[])
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--allow-downloads", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--project-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--import-dir", type=Path, action="append", default=[])
    parser.add_argument("--stage-name")
    parser.add_argument("--stage-max-bytes", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.plan_imports:
        if not args.import_dir or args.stage_name or args.command or args.output:
            parser.error("--plan-imports requires --import-dir and no stage-name/command/output")
        config = json.loads((args.root / "preparation.json").read_text())
        report = plan_imports(config, tuple(args.import_dir), max_bytes=args.stage_max_bytes,
                              timeout=args.timeout)
    elif args.stage_imports:
        if not args.stage_name or not args.import_dir or args.command or args.output:
            parser.error("--stage-imports requires --stage-name, --import-dir and no command/output")
        config = json.loads((args.root / "preparation.json").read_text())
        report = stage_imports(config, tuple(args.import_dir), name=args.stage_name,
                               max_bytes=args.stage_max_bytes, timeout=args.timeout)
    elif args.import_dir or args.stage_name or args.stage_max_bytes:
        parser.error("import staging options require --stage-imports or --plan-imports")
    elif args.export_projects:
        if not args.state_root or not args.output or args.command:
            parser.error("--export-projects requires --state-root, --output and no command")
        config = json.loads((args.root / "preparation.json").read_text())
        mount = validate_volume(config)
        if not args.output.resolve().is_relative_to(mount):
            parser.error("export output must be inside the capped volume")
        projects = export_projects(args.state_root, args.project_root)
        with args.output.open("x") as stream:
            json.dump(projects, stream, indent=2)
        report = {"projects": len(projects), "output": str(args.output), "proofs_verified": 0}
    elif args.init:
        if not args.fuse2fs or args.command:
            parser.error("--init requires --fuse2fs and no command")
        report = initialize(args.root, args.fuse2fs, args.max_bytes)
    else:
        config = json.loads((args.root / "preparation.json").read_text())
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        report = run(config, command, cwd=args.cwd, readonly=tuple(args.readonly),
                     network=args.allow_downloads, timeout=args.timeout)
    print(json.dumps(report, indent=2))
    return int(report.get("exit_code", 0) != 0 or report.get("status") == "DOES_NOT_FIT")


if __name__ == "__main__":
    raise SystemExit(main())
