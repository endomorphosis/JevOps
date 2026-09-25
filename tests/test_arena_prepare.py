"""Offline preparation safety checks; no Docker, downloads or Lean builds."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jevops import arena_prepare as prep


@pytest.mark.parametrize("amount", [0, -1, True, 232_000_000 - 1, 50_000_000_001, 50e9])
def test_invalid_allowance(amount):
    with pytest.raises(ValueError):
        prep.volume_bytes(amount)


def test_decimal_cap_and_headroom():
    size = prep.volume_bytes(50_000_000_000)
    assert size == 49_799_999_488
    assert size % 4096 == 0
    assert size + prep.OVERHEAD_BYTES <= 50_000_000_000


def test_lock_excludes_second_owner_and_releases(tmp_path):
    path = tmp_path / "lock"
    with prep.exclusive(path):
        with pytest.raises(BlockingIOError):
            with prep.exclusive(path):
                pytest.fail("overlapping work")
    with prep.exclusive(path):
        pass


@pytest.fixture
def volume(tmp_path, monkeypatch):
    mount = tmp_path / "work"; mount.mkdir()
    image = tmp_path / "volume.ext4"
    size = prep.volume_bytes(240_000_000)
    with image.open("xb") as stream:
        stream.truncate(size)
    config = {"schema": prep.SCHEMA, "root": str(tmp_path), "mount": str(mount),
              "image": str(image), "image_bytes": size, "image_inode": image.stat().st_ino,
              "max_bytes": 240_000_000}
    monkeypatch.setattr(prep.os.path, "ismount", lambda _: True)
    monkeypatch.setattr(prep.subprocess, "check_output", lambda *a, **k: json.dumps({"filesystems": [
        {"source": str(image), "target": str(mount), "fstype": "fuse.ext4"}]}))
    monkeypatch.setattr(prep.os, "statvfs", lambda _: SimpleNamespace(f_blocks=size // 4096, f_frsize=4096))
    return config


def test_mounted_volume_identity(volume):
    assert prep.validate_volume(volume) == Path(volume["mount"])


@pytest.mark.parametrize("failure", ["unmounted", "schema", "size", "inode", "source", "capacity"])
def test_reject_volume_substitution(volume, monkeypatch, failure):
    if failure == "unmounted": monkeypatch.setattr(prep.os.path, "ismount", lambda _: False)
    elif failure == "schema": volume["schema"] = "wrong"
    elif failure == "size": volume["image_bytes"] += 4096
    elif failure == "inode": volume["image_inode"] += 1
    elif failure == "source":
        monkeypatch.setattr(prep.subprocess, "check_output", lambda *a, **k: '{"filesystems": []}')
    elif failure == "capacity":
        monkeypatch.setattr(prep.os, "statvfs", lambda _: SimpleNamespace(f_blocks=50_000_000_000, f_frsize=4096))
    with pytest.raises(ValueError):
        prep.validate_volume(volume)


def test_container_writes_only_to_capped_volume(volume, monkeypatch):
    monkeypatch.setenv("SECRET_API_TOKEN", "MUST_NOT_PROPAGATE")
    command = ["/bin/true"]
    args = prep.container_args(volume, image="sha256:fixture", rootless=True,
                               cwd=Path(volume["mount"]), readonly=(), network=False, command=command)
    mounts = [args[i + 1] for i, x in enumerate(args) if x == "--mount"]
    assert all("readonly" in m or f"src={volume['mount']}" in m for m in mounts)
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--user") + 1] == "0:0"
    assert "--read-only" in args and "--pull=never" in args and "--log-driver=none" in args
    assert not any("MUST_NOT_PROPAGATE" in a or "SECRET_API_TOKEN" in a for a in args)
    assert args[-2:] == ["sha256:fixture", "/bin/true"]


def test_reject_workdir_escape_and_overlapping_mount(volume):
    options = dict(image="fixture", rootless=False, cwd=Path(volume["mount"]),
                   readonly=(), network=True, command=["true"])
    with pytest.raises(ValueError):
        prep.container_args(volume, **{**options, "cwd": Path("/")})
    for path in (Path(volume["root"]), Path(volume["mount"]), Path("/")):
        with pytest.raises(ValueError):
            prep.container_args(volume, **{**options, "readonly": (path,)})


def test_init_never_overwrites_existing_image(volume):
    with pytest.raises(ValueError, match="overwrite"):
        prep.initialize(Path(volume["root"]), Path("/does/not/exist"))


@pytest.mark.parametrize("timeout", [0, -1, True, 28801])
def test_invalid_wall_limit(volume, timeout):
    with pytest.raises(ValueError):
        prep.run(volume, ["true"], timeout=timeout)


def test_export_preserves_unavailable_pins_and_checks_identity(tmp_path, monkeypatch):
    from jevops import arena_lean as native
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps({"name": "offline fixture"}))
    monkeypatch.setattr(native, "CORPUS", corpus)
    original = [{"repository": "https://github.com/test/project", "git_commit": "a" * 40,
                 "lean_tag": "v4.27.0", "root": "old"}, {"root": "unavailable", "repository": "other"}]
    monkeypatch.setattr(native, "discover_projects", lambda *_: [dict(p) for p in original])
    monkeypatch.setattr(native, "_git", lambda _, *args: "a" * 40 if args[0] == "rev-parse"
                        else "https://github.com/test/project.git")
    checked = []
    monkeypatch.setattr(native, "_check_project", lambda *args: checked.append("project"))
    monkeypatch.setattr(native, "lake_environment", lambda *args: checked.append("dependencies"))
    result = prep.export_projects(tmp_path, [tmp_path])
    assert result[0]["root"] == str(tmp_path)
    assert result[1] == original[1]
    assert checked == ["project", "dependencies"]
    with pytest.raises(ValueError, match="unique"):
        prep.export_projects(tmp_path, [tmp_path, tmp_path])


def test_existing_container_is_not_removed(volume, monkeypatch):
    monkeypatch.setattr(prep, "validate_volume", lambda _: Path(volume["mount"]))
    monkeypatch.setattr(prep.subprocess, "check_output", lambda args, **k:
                        '["name=rootless"]' if args[1] == "info" else "sha256:fixture")
    calls = []
    def inspect(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(prep.subprocess, "run", inspect)
    with pytest.raises(ValueError, match="previous preparation container"):
        prep.run(volume, ["true"])
    assert len(calls) == 1 and calls[0][1:3] == ["container", "inspect"]


@pytest.mark.parametrize("timeout", [False, True])
def test_run_reports_exit_and_cleans_its_container(volume, monkeypatch, timeout):
    import subprocess
    mount = Path(volume["mount"])
    (mount / "logs").mkdir()
    monkeypatch.setattr(prep, "validate_volume", lambda _: mount)
    monkeypatch.setattr(prep.os, "statvfs", lambda _: SimpleNamespace(f_blocks=100, f_frsize=4096, f_bfree=80))
    monkeypatch.setattr(prep.subprocess, "check_output", lambda args, **k:
                        '["name=rootless"]' if args[1] == "info" else "sha256:fixture")
    calls = []
    owner = []
    def call(args, **kwargs):
        calls.append(args)
        if "--format" in args:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"Id": "a" * 64,
                "Config": {"Labels": {"jevops.preparation.owner": owner[0]}}}))
        return SimpleNamespace(returncode=1)
    class Process:
        killed = False
        def wait(self, timeout=None):
            if timeout is not None and timeout_requested:
                raise subprocess.TimeoutExpired("fixture", timeout)
            return 7
        def poll(self): return None if timeout_requested and not self.killed else 7
        def kill(self): self.killed = True
    timeout_requested = timeout
    monkeypatch.setattr(prep.subprocess, "run", call)
    def spawn(args, **kwargs):
        owner.append(args[args.index("--label") + 1].split("=", 1)[1])
        return Process()
    monkeypatch.setattr(prep.subprocess, "Popen", spawn)
    result = prep.run(volume, ["false"], timeout=1)
    assert result["timed_out"] == timeout
    assert result["exit_code"] == (124 if timeout else 7)
    assert calls[-1][1:3] == ["rm", "-f"]
    assert calls[-1][-1] == "a" * 64
    assert json.loads((mount / "logs" / (result["run_id"] + ".json")).read_text()) == result


@pytest.mark.parametrize("command", [[], ["x"] * 257, ["x" * 32769], ["bad\0argument"], [None]])
def test_bounded_command_metadata(volume, command):
    with pytest.raises(ValueError, match="bounded"):
        prep.container_args(volume, image="fixture", rootless=False, cwd=Path(volume["mount"]),
                            readonly=(), network=False, command=command)


def test_cleanup_leaves_foreign_container_untouched(monkeypatch):
    calls = []
    def inspect(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"Id": "b" * 64,
            "Config": {"Labels": {"jevops.preparation.owner": "other-owner"}}}))
    monkeypatch.setattr(prep.subprocess, "run", inspect)
    assert prep.remove_owned_container("shared-name", "our-owner") == "not_owned_left_untouched"
    assert len(calls) == 1 and "rm" not in calls[0]


@pytest.fixture
def staged(volume):
    from jevops.arena_staging import StagedImports
    source = Path(volume["mount"]) / "imports"
    (source / "Nested/Empty").mkdir(parents=True)
    (source / "Nested/Fixture.olean").write_bytes(b"offline fixture; not a real olean")
    report = prep.stage_imports(volume, (source,), name="test", max_bytes=4_000_000)
    stage = StagedImports(Path(report["manifest"]), report["manifest_sha256"], (source,))
    return report, stage, source


def test_stage_is_readonly_exact_independent_and_not_proof(volume, staged):
    import stat
    report, stage, source = staged
    stage.validate()
    original, copy = source / "Nested/Fixture.olean", stage.paths[0] / "Nested/Fixture.olean"
    assert original.read_bytes() == copy.read_bytes()
    assert original.stat().st_ino != copy.stat().st_ino
    assert original.stat().st_mode & stat.S_IWUSR and not copy.stat().st_mode & stat.S_IWUSR
    assert copy.stat().st_nlink == 1 and (stage.paths[0] / "Nested/Empty").is_dir()
    assert report["status"] == "STAGED_INPUTS_ONLY" and report["proofs_verified"] == 0
    assert report["reserved_bytes"] <= report["max_bytes"]
    assert report["preparation_overhead_bytes"] <= prep.OVERHEAD_BYTES - 20_000_000
    assert prep.validate_volume(volume) == Path(volume["mount"])
    with pytest.raises(ValueError, match="overwrite"):
        prep.stage_imports(volume, (source,), name="test", max_bytes=4_000_000)


@pytest.mark.parametrize("budget", [0, 1, True, -1, 128_000_001])
def test_stage_zero_invalid_or_insufficient_budget_writes_nothing(volume, budget):
    source = Path(volume["mount"])
    with pytest.raises(ValueError):
        prep.stage_imports(volume, (source,), name="no", max_bytes=budget)
    assert not (Path(volume["root"]) / "import-stages").exists()


def test_stage_exact_reservation_and_existing_overhead(volume, monkeypatch):
    import time
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    entries = staging.inventory((source,), deadline=time.monotonic() + 2)
    needed = staging.reservation(entries)
    with pytest.raises(ValueError, match="headroom"):
        prep.stage_imports(volume, (source,), name="short", max_bytes=needed - 1)
    real = prep.preparation_overhead
    monkeypatch.setattr(prep, "preparation_overhead", lambda *a: prep.OVERHEAD_BYTES - 20_000_000 - needed + 1)
    with pytest.raises(ValueError, match="headroom"):
        prep.stage_imports(volume, (source,), name="occupied", max_bytes=needed)
    monkeypatch.setattr(prep, "preparation_overhead", real)
    assert prep.stage_imports(volume, (source,), name="exact", max_bytes=needed)["reserved_bytes"] == needed


@pytest.mark.parametrize("damage", ["original", "copy", "manifest", "extra_original", "extra_copy", "writable", "hardlink", "foreign_manifest"])
def test_stage_changed_inputs_cannot_validate(staged, damage, tmp_path):
    from dataclasses import replace
    report, stage, source = staged
    target = stage.paths[0] / "Nested/Fixture.olean"
    if damage == "original":
        (source / "Nested/Fixture.olean").write_bytes(b"different original")
    elif damage in {"copy", "writable"}:
        target.chmod(0o644)
        if damage == "copy":
            target.write_bytes(b"different copy"); target.chmod(0o444)
    elif damage == "manifest":
        stage.manifest.chmod(0o644)
        stage.manifest.write_bytes(b"{}"); stage.manifest.chmod(0o444)
    elif damage == "extra_original": (source / "new.olean").touch()
    elif damage == "extra_copy":
        stage.paths[0].chmod(0o755)
        (stage.paths[0] / "new.olean").touch(); stage.paths[0].chmod(0o555)
    elif damage == "hardlink":
        import os
        os.link(target, tmp_path / "alias")
    else: stage = replace(stage, manifest_sha256="0" * 64)
    with pytest.raises(ValueError): stage.validate()


@pytest.mark.parametrize("unsafe", ["symlink_file", "symlink_dir", "fifo", "relative", "traversal", "duplicate"])
def test_stage_rejects_ambiguous_inputs_before_copy(volume, unsafe):
    import os
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    paths, name = (source,), "safe"
    if unsafe == "symlink_file": (source / "link").symlink_to(Path(volume["image"]))
    elif unsafe == "symlink_dir": (source / "link").symlink_to(source, target_is_directory=True)
    elif unsafe == "fifo": os.mkfifo(source / "pipe")
    elif unsafe == "relative": paths = (Path("inputs"),)
    elif unsafe == "duplicate": paths = (source, source)
    else: name = "../escape"
    with pytest.raises(ValueError): prep.stage_imports(volume, paths, name=name, max_bytes=4_000_000)
    assert not (Path(volume["root"]) / "import-stages").exists()


def test_stage_entry_limit_deadline_and_lock(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    (source / "one").touch()
    monkeypatch.setattr(staging, "MAX_ENTRIES", 1)
    with pytest.raises(ValueError, match="entry budget"):
        prep.stage_imports(volume, (source,), name="limited", max_bytes=4_000_000)
    with prep.exclusive(Path(volume["root"]) / "single-build.lock"):
        with pytest.raises(BlockingIOError):
            prep.stage_imports(volume, (source,), name="locked", max_bytes=4_000_000)
    monkeypatch.setattr(staging.time, "monotonic", lambda: 100)
    with pytest.raises(TimeoutError): staging.inventory((source,), deadline=99)


def test_staged_binding_preserves_trust_context_and_rechecks_originals(volume, staged, monkeypatch):
    from dataclasses import replace
    from jevops import arena_lean as native
    from jevops.lean import VersionPin
    from jevops.seals import Fingerprinter
    report, stage, source = staged
    lean = Path(volume["root"]) / "compiler/bin/lean"
    lean.parent.mkdir(parents=True); lean.write_text("fixture compiler")
    (lean.parent.parent / "lib").mkdir()
    binding = native.ProjectBinding(VersionPin("v4.26.0", "fixture"), lean, source,
                                   "import Fixture", (source,), project_backed=False)
    rebound = binding.with_staged_imports(stage.manifest, stage.manifest_sha256)
    assert rebound.prefix == binding.prefix and rebound.pin == binding.pin
    assert rebound.root == binding.root and rebound.project_backed == binding.project_backed
    assert binding.search_paths == (source,) and rebound.search_paths == stage.paths
    assert rebound.fingerprint(Fingerprinter()) != binding.fingerprint(Fingerprinter())
    with pytest.raises(ValueError, match="already staged"):
        rebound.with_staged_imports(stage.manifest, stage.manifest_sha256)
    with pytest.raises(ValueError, match="path binding"):
        replace(rebound, search_paths=binding.search_paths).fingerprint(Fingerprinter())
    (source / "Nested/Fixture.olean").write_text("changed source")
    with pytest.raises(ValueError, match="original imports changed"):
        rebound.fingerprint(Fingerprinter())


def test_stage_source_mutation_during_copy_never_publishes(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    file = source / "A.olean"; file.write_bytes(b"a")
    original = staging._digest
    def changed(path, size, deadline, output=None):
        result = original(path, size, deadline, output)
        if output is not None: file.write_bytes(b"b")
        return result
    monkeypatch.setattr(staging, "_digest", changed)
    with pytest.raises(ValueError, match="changed during copy"):
        prep.stage_imports(volume, (source,), name="changed", max_bytes=4_000_000)
    assert not (Path(volume["root"]) / "import-stages/changed/manifest.json").exists()


def test_staged_project_manifest_binds_existing_resolver_not_arbitrary_search_paths(volume, staged, monkeypatch):
    from jevops import arena_lean as native
    from jevops.lean import VersionPin
    report, stage, source = staged
    binding = native.ProjectBinding(VersionPin("v4.26.0", "fixture"), source / "lean", source,
                                   "prefix", (source,))
    monkeypatch.setattr(native, "_project_binding", lambda *a: binding)
    project = {"staged_imports_manifest": str(stage.manifest), "staged_imports_sha256": stage.manifest_sha256}
    resolved = native.project_binding({}, binding.pin, project, source)
    assert resolved.project_backed and resolved.staged_imports == stage
    with pytest.raises(native.CapabilityGap):
        native.project_binding({}, binding.pin, {"staged_imports_manifest": str(stage.manifest)}, source)


@pytest.mark.parametrize("damage", ["boolean_root", "boolean_size", "extra", "wrong_source", "duplicate_key"])
def test_stage_malformed_manifest_cannot_pass_even_with_matching_digest(staged, damage):
    from dataclasses import replace
    import hashlib
    from jevops.arena_staging import _encoded
    _, stage, source = staged
    value = json.loads(stage.manifest.read_bytes())
    if damage == "boolean_root": value["entries"][0]["root"] = False
    elif damage == "boolean_size":
        next(e for e in value["entries"] if e["kind"] == "file")["bytes"] = True
    elif damage == "extra": value["verified"] = True
    elif damage == "wrong_source": value["sources"] = [str(source.parent)]
    raw = _encoded(value)
    if damage == "duplicate_key": raw = raw.replace(b'{', b'{"schema":"ignored",', 1)
    stage.manifest.chmod(0o644); stage.manifest.write_bytes(raw); stage.manifest.chmod(0o444)
    forged = replace(stage, manifest_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError): forged.validate()


def test_stage_payload_limit_checked_before_reading_or_copying(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    with (source / "large.olean").open("xb") as stream:
        stream.truncate(staging.MAX_BYTES + 1)  # Sparse fixture; no large allocation/read.
    monkeypatch.setattr(staging, "_digest", lambda *a, **k: pytest.fail("must not hash over-budget file"))
    with pytest.raises(ValueError, match="byte budget"):
        prep.stage_imports(volume, (source,), name="large", max_bytes=staging.MAX_BYTES)
    assert not (Path(volume["root"]) / "import-stages").exists()


def test_cli_stage_requires_mode_and_explicit_budget(volume, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", ["arena_prepare", "--root", volume["root"], "--stage-name", "bad"])
    with pytest.raises(SystemExit): prep.main()
    Path(volume["root"], "preparation.json").write_text(json.dumps(volume))
    monkeypatch.setattr(sys, "argv", ["arena_prepare", "--root", volume["root"], "--stage-imports",
        "--stage-name", "zero", "--import-dir", volume["mount"]])
    with pytest.raises(ValueError, match="budget exhausted"): prep.main()


def test_import_plan_is_metadata_only_and_not_a_reservation(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    (source / "A.olean").write_bytes(b"contents are not inspected")
    (source / "empty").mkdir()
    monkeypatch.setattr(staging, "_digest", lambda *a, **k: pytest.fail("plan must not hash"))
    zero = prep.plan_imports(volume, (source,))
    assert zero["status"] == "DOES_NOT_FIT"
    assert zero["reasons"] == ["requested reservation budget"]
    exact = prep.plan_imports(volume, (source,), max_bytes=zero["required_reservation_bytes"])
    assert exact["status"] == "WOULD_FIT" and exact["entries"] == 3 and exact["files"] == 1
    assert exact["payload_bytes"] == len(b"contents are not inspected")
    assert exact["content_validated"] is False
    assert exact["bytes_reserved"] == exact["proofs_verified"] == 0
    assert not (Path(volume["root"]) / "import-stages").exists()


def test_plan_oversize_counts_without_reading_payload(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    for name in ("A.olean", "B.olean"):
        with (source / name).open("xb") as stream:
            stream.truncate(staging.MAX_BYTES)  # Sparse metadata-only fixtures.
    monkeypatch.setattr(staging, "_digest", lambda *a, **k: pytest.fail("must not hash"))
    plan = prep.plan_imports(volume, (source,), max_bytes=staging.MAX_BYTES)
    assert plan["payload_bytes"] == 2 * staging.MAX_BYTES
    assert plan["status"] == "DOES_NOT_FIT"
    assert plan["reasons"] == ["import byte budget", "requested reservation budget", "reserved preparation headroom"]
    with pytest.raises(ValueError, match="import byte budget"):
        prep.stage_imports(volume, (source,), name="large", max_bytes=staging.MAX_BYTES)
    with pytest.raises(ValueError, match="import byte budget"):
        staging.inventory((source,), deadline=float("inf"))


def test_plan_does_not_admit_changed_or_over_budget_inputs(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    (source / "A.olean").write_bytes(b"a")
    plan = prep.plan_imports(volume, (source,), max_bytes=4_000_000)
    assert plan["status"] == "WOULD_FIT"
    # Reservation can fail even when payload is under MAX_BYTES. No hash/copy.
    monkeypatch.setattr(staging, "_digest", lambda *a, **k: pytest.fail("reject before hashing"))
    with pytest.raises(ValueError, match="requested reservation budget"):
        prep.stage_imports(volume, (source,), name="short", max_bytes=plan["required_reservation_bytes"] - 1)
    (source / "A.olean").unlink()
    (source / "A.olean").symlink_to(source / "missing")
    with pytest.raises(ValueError, match="symlinks"):
        prep.stage_imports(volume, (source,), name="changed", max_bytes=4_000_000)
    assert not (Path(volume["root"]) / "import-stages").exists()


def test_plan_bounded_inventory_never_claims_partial_fit(volume, monkeypatch):
    from jevops import arena_staging as staging
    source = Path(volume["mount"]) / "inputs"; source.mkdir()
    (source / "A.olean").touch()
    with prep.exclusive(Path(volume["root"]) / "single-build.lock"):
        with pytest.raises(BlockingIOError): prep.plan_imports(volume, (source,))
    monkeypatch.setattr(staging, "MAX_ENTRIES", 1)
    with pytest.raises(ValueError, match="entry budget"):
        prep.plan_imports(volume, (source,), max_bytes=4_000_000)
    monkeypatch.setattr(staging, "_check_time", lambda _: (_ for _ in ()).throw(TimeoutError("deadline")))
    with pytest.raises(TimeoutError): prep.plan_imports(volume, (source,))


@pytest.mark.parametrize("options", [{"max_bytes": -1}, {"max_bytes": True},
    {"max_bytes": 128_000_001}, {"timeout": 0}, {"timeout": True}, {"timeout": 3601}])
def test_plan_validates_limits(volume, options):
    with pytest.raises(ValueError): prep.plan_imports(volume, (Path(volume["mount"]),), **options)


def test_cli_plan_reports_fit_and_nonfit_exit_codes(volume, monkeypatch, capsys):
    import sys
    Path(volume["root"], "preparation.json").write_text(json.dumps(volume))
    args = ["arena_prepare", "--root", volume["root"], "--plan-imports", "--import-dir", volume["mount"]]
    monkeypatch.setattr(sys, "argv", args)
    assert prep.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "DOES_NOT_FIT"
    monkeypatch.setattr(sys, "argv", [*args, "--stage-max-bytes", "4000000"])
    assert prep.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "WOULD_FIT"
    monkeypatch.setattr(sys, "argv", [*args, "--stage-name", "not-a-copy"])
    with pytest.raises(SystemExit): prep.main()
