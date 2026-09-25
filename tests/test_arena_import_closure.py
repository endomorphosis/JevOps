"""Offline closure/staging guards. Fixture inventories are NOT Lean evidence."""
from dataclasses import replace
import json
from pathlib import Path
import time

import pytest

from jevops import arena_import_closure as closure
from jevops import arena_prepare as prep
from jevops import arena_staging as staging
from jevops.arena_lean import ProjectBinding
from jevops.lean import VersionPin
from jevops.seals import Fingerprinter
from tests.test_arena_prepare import volume  # shared capped-volume fixture


@pytest.fixture
def binding(volume):
    root = Path(volume["mount"])
    imports = root / "imports"
    (imports / "Pkg").mkdir(parents=True)
    for suffix in staging.MODULE_SUFFIXES:
        (imports / ("Pkg/Used" + suffix)).write_bytes(suffix.encode())
    (imports / "Pkg/Used.ilean").write_bytes(b"editor info")
    (imports / "Pkg/Unused.olean").write_bytes(b"unselected")
    (imports / "OnlyTop.olean").write_bytes(b"root prefix blocker")
    lean = root / "compiler/bin/lean"
    lean.parent.mkdir(parents=True)
    lean.write_text("fixture compiler")
    library = root / "compiler/lib/lean"
    library.mkdir(parents=True)
    (library / "Init.olean").write_bytes(b"fixture standard library")
    return ProjectBinding(VersionPin("v4.27.0", "a" * 40), lean, imports,
                          "import Pkg.Used", (imports,), project_backed=False)


SELECTION = (("Pkg/Used.olean",),)


def entries(binding, selection=SELECTION):
    return staging.selected_metadata(binding.search_paths, selection, deadline=time.monotonic() + 10)


def stage(volume, binding):
    scope = binding.fingerprint(Fingerprinter())
    result = prep.stage_imports(volume, binding.search_paths, name="selected",
        selection=SELECTION, scope_sha256=scope, max_bytes=8_000_000)
    rebound = binding.with_staged_imports(Path(result["manifest"]), result["manifest_sha256"])
    return result, rebound


def native_inventory(binding, request):
    return {"schema": closure.NATIVE_SCHEMA, "request_sha256": request["request_sha256"],
        "lean_version": "4.27.0", "lean_githash": "b" * 40,
        "modules": [{"name": "Pkg.Used", "olean": str(binding.search_paths[0] / "Pkg/Used.olean")},
                    {"name": "Init", "olean": str(binding.lean.parent.parent / "lib/lean/Init.olean")}]}


def test_complete_families_and_empty_root_blockers(binding):
    selected = entries(binding)
    assert {e["path"] for e in selected if e["kind"] == "file"} == {
        "Pkg/Used" + suffix for suffix in staging.MODULE_SUFFIXES}
    assert {e["path"] for e in selected if e["kind"] == "directory"} == {".", "Pkg", "OnlyTop"}
    assert not (binding.search_paths[0] / "OnlyTop").exists()  # synthetic, source untouched


def test_selected_plan_and_stage_are_exact_readonly_and_not_proofs(volume, binding):
    plan = prep.plan_imports(volume, binding.search_paths, selection=SELECTION, max_bytes=8_000_000)
    assert plan["status"] == "WOULD_FIT" and plan["proofs_verified"] == 0
    result, rebound = stage(volume, binding)
    rebound.fingerprint(Fingerprinter())
    assert result["reserved_bytes"] == plan["required_reservation_bytes"]
    assert result["proofs_verified"] == 0
    root = rebound.search_paths[0]
    assert (root / "OnlyTop").is_dir() and not (root / "OnlyTop.olean").exists()
    assert not (root / "Pkg/Used.ilean").exists() and not (root / "Pkg/Unused.olean").exists()
    for suffix in staging.MODULE_SUFFIXES:
        source, copied = binding.search_paths[0] / ("Pkg/Used" + suffix), root / ("Pkg/Used" + suffix)
        assert source.read_bytes() == copied.read_bytes()
        assert source.stat().st_ino != copied.stat().st_ino
        assert copied.stat().st_mode & 0o777 == 0o444
    assert json.loads(rebound.staged_imports.manifest.read_bytes())["schema"] == staging.SELECTED_SCHEMA
    with pytest.raises(ValueError, match="overwrite"):
        prep.stage_imports(volume, binding.search_paths, name="selected", selection=SELECTION,
                          scope_sha256=binding.fingerprint(Fingerprinter()), max_bytes=8_000_000)


@pytest.mark.parametrize("mutation", ["selected", "omitted", "new_sidecar", "compiler", "prefix", "pin"])
def test_whole_original_context_invalidates_selected_binding(volume, binding, mutation):
    _, rebound = stage(volume, binding)
    if mutation == "prefix": rebound = replace(rebound, prefix="import Pkg.Other")
    elif mutation == "pin": rebound = replace(rebound, pin=VersionPin("v4.29.1", "a" * 40))
    else:
        path = {"selected": binding.search_paths[0] / "Pkg/Used.olean.private",
                "omitted": binding.search_paths[0] / "Pkg/Unused.olean",
                "new_sidecar": binding.search_paths[0] / "Pkg/Unused.ir",
                "compiler": binding.lean}[mutation]
        path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="original selected-import context"):
        rebound.fingerprint(Fingerprinter())


@pytest.mark.parametrize("mutation", ["extra", "changed", "writable", "scope"])
def test_modified_stage_not_admitted(volume, binding, mutation):
    _, rebound = stage(volume, binding)
    staged = rebound.staged_imports
    file = rebound.search_paths[0] / "Pkg/Used.olean.private"
    if mutation == "scope": staged = replace(staged, scope_sha256="c" * 64)
    elif mutation == "extra":
        file.parent.chmod(0o755)
        (file.parent / "Extra.olean").write_bytes(b"not authorized")
        (file.parent / "Extra.olean").chmod(0o444)
        file.parent.chmod(0o555)
    else:
        file.chmod(0o644)
        if mutation == "changed":
            file.write_bytes(b"changed")
            file.chmod(0o444)
    with pytest.raises(ValueError): staged.validate()


@pytest.mark.parametrize("selection", [[], ((),), (([],),), (("../Used.olean",),),
    (("/Used.olean",),), (("Pkg//Used.olean",),), (("Pkg/./Used.olean",),),
    (("Pkg\\Used.olean",),), (("Pkg/Used.ilean",),), (("Pkg/Used\0.olean",),),
    (("Pkg/Used.olean", "Pkg/Used.olean"),), (("Pkg/Missing.olean",),)])
def test_invalid_selections_fail_closed(binding, selection):
    with pytest.raises(ValueError): entries(binding, selection)


def test_new_split_ir_layout_rejected(binding):
    (binding.search_paths[0] / "Pkg/Used.ir.sig").write_bytes(b"unsupported")
    with pytest.raises(ValueError, match="split IR"): entries(binding)


def test_new_empty_package_blocker_invalidates_stage(volume, binding):
    _, rebound = stage(volume, binding)
    (binding.search_paths[0] / "NewPackage").mkdir()
    with pytest.raises(ValueError, match="original imports changed"):
        rebound.fingerprint(Fingerprinter())


def test_selected_inspection_deadline_and_shared_lock(volume, binding):
    with pytest.raises(TimeoutError):
        staging.selected_metadata(binding.search_paths, SELECTION, deadline=0)
    with prep.exclusive(Path(volume["root"]) / "single-build.lock"):
        with pytest.raises(BlockingIOError):
            prep.plan_imports(volume, binding.search_paths, selection=SELECTION, max_bytes=8_000_000)


def test_non_object_manifest_rejected_before_binding(volume, binding):
    path = Path(volume["mount"]) / "invalid-manifest.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="manifest object"):
        binding.with_staged_imports(path, "a" * 64)


@pytest.mark.parametrize("special", ["symlink", "fifo"])
def test_unselected_special_files_rejected(binding, special):
    import os
    file = binding.search_paths[0] / "UnusedSpecial"
    if special == "symlink": file.symlink_to(binding.lean)
    else: os.mkfifo(file)
    with pytest.raises(ValueError, match="regular"): entries(binding)


def test_root_prefix_selection_does_not_fall_through(binding):
    second = binding.root.parent / "second"
    (second / "Pkg").mkdir(parents=True)
    (second / "Pkg/Missing.olean").write_bytes(b"wrong import root")
    binding = replace(binding, search_paths=(*binding.search_paths, second))
    with pytest.raises(ValueError, match="precedence"):
        entries(binding, ((), ("Pkg/Missing.olean",)))
    with pytest.raises(ValueError, match="search order"):
        closure.select_modules(binding, [{"name": "Pkg.Missing", "olean": str(second / "Pkg/Missing.olean")}])


def test_selected_stage_requires_scope_and_budget_before_copy(volume, binding):
    for scope, allowance in ((None, 8_000_000), ("wrong", 8_000_000), ("a" * 64, 1)):
        with pytest.raises(ValueError):
            prep.stage_imports(volume, binding.search_paths, name="not-created", selection=SELECTION,
                              scope_sha256=scope, max_bytes=allowance)
    assert not (Path(volume["root"]) / "import-stages/not-created").exists()


def test_fixture_discovery_is_bounded_metadata_only(binding):
    discovery = closure.ImportClosureDiscovery(binding, max_processes=1,
        runner=lambda request: native_inventory(binding, request))
    report = discovery.discover("Pkg.theoremUnderTest")
    assert report["selection"] == SELECTION and report["selected_modules"] == 1
    assert report["files"] == 4 and report["evidence_mode"] == "fixture"
    assert report["native_processes"] == report["proofs_verified"] == 0 and not report["promotion"]
    with pytest.raises(ValueError, match="budget"): discovery.discover("Pkg.theoremUnderTest")


@pytest.mark.parametrize("mutation", ["request", "version", "schema", "githash", "duplicate", "foreign", "drift"])
def test_failed_discovery_consumes_budget_and_does_not_emit_receipt(binding, mutation):
    def runner(request):
        result = native_inventory(binding, request)
        if mutation in {"request", "version", "schema", "githash"}:
            key = {"request": "request_sha256", "version": "lean_version", "schema": "schema",
                   "githash": "lean_githash"}[mutation]
            result[key] = "wrong"
        elif mutation == "duplicate": result["modules"].append(result["modules"][0])
        elif mutation == "foreign": result["modules"][0]["olean"] = str(binding.lean)
        else: (binding.search_paths[0] / "Pkg/Unused.olean").write_bytes(b"drift")
        return result
    discovery = closure.ImportClosureDiscovery(binding, max_processes=1, runner=runner)
    with pytest.raises(ValueError): discovery.discover("Pkg.target")
    assert discovery.attempts == 1
    with pytest.raises(ValueError, match="budget"): discovery.discover("Pkg.target")


def test_discovery_default_does_not_run(binding):
    with pytest.raises(ValueError, match="budget"):
        closure.ImportClosureDiscovery(binding).discover("Pkg.target")
    with pytest.raises(ValueError, match="artifact layout"):
        closure.ImportClosureDiscovery(replace(binding, pin=VersionPin("v4.34.0", "a" * 40)))


def test_driver_uses_prefix_checks_and_private_audit():
    source = closure.driver_source()
    assert source.count("unsafe def main") == 1
    assert 'JEVOPS_IMPORT_CLOSURE:' in source
    assert "initial.messages.hasErrors" in source and "initial.env.checked.get.find?" in source
    assert "audit.header.moduleNames" in source and "trustLevel := 0" in source
