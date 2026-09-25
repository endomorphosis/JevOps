"""Offline lockfile/binding tests. Fake oleans are never offered to Lean."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from jevops import arena_lean as native
from jevops.arena import Outcome, VerificationRequest
from jevops.lean import VersionPin, putnam_pin_for_tag
from jevops.seals import Fingerprinter


def git(root, *args):
    return subprocess.run(["/usr/bin/git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit_fixture(root):
    git(root, "init", "--quiet")
    git(root, "add", "Source.lean", "lean-toolchain")
    git(root, "-c", "user.name=Arena fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "offline dependency fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / "putnam"; root.mkdir()
    tag = "v4.26.0"
    (root / "lean-toolchain").write_text("leanprover/lean4:" + tag + "\n")
    packages = []
    for name, repository, module in (("mathlib", "mathlib4", "Mathlib"), ("aesop", "aesop", "Aesop")):
        path = root / ".lake/packages" / name; path.mkdir(parents=True)
        (path / "Source.lean").write_text("-- offline fixture only\n")
        (path / "lean-toolchain").write_text("leanprover/lean4:" + tag)
        commit = commit_fixture(path)
        lib = path / ".lake/build/lib/lean"; lib.mkdir(parents=True)
        (lib / (module + ".olean")).write_bytes(b"NOT A REAL OLEAN; never executed")
        packages.append({"name": name, "type": "git", "rev": commit, "subDir": None,
                         "url": "https://github.com/leanprover-community/" + repository + ".git"})
    manifest = {"version": "1.1.0", "packagesDir": ".lake/packages", "packages": packages}
    (root / "lake-manifest.json").write_text(json.dumps(manifest))
    pin = VersionPin(tag, packages[0]["rev"])
    record = {"source": "putnambench", "name": "fixture", "url": "", "file_path": "",
              "header": "import Mathlib\nimport Aesop\nset_option maxHeartbeats 0\n",
              "statement": "theorem fixture : True", "src": "theorem fixture : True := by trivial",
              "version_info": [{tag: pin.git_commit}]}
    project = {"kind": "putnam", "root": str(root), "repository": "", "lean_tag": tag,
               "git_commit": pin.git_commit}
    compiler = tmp_path / "toolchain/bin/lean"; compiler.parent.mkdir(parents=True)
    compiler.write_text("fixture executable; do not run")
    lib = compiler.parent.parent / "lib"; lib.mkdir()
    (lib / "Init.olean").write_bytes(b"fixture stdlib")
    monkeypatch.setattr(native, "pinned_lean", lambda *_: compiler)
    return root, pin, record, project, manifest


def bind(prepared):
    root, pin, record, project, _ = prepared
    return native.project_binding(record, pin, project, root)


def rewrite_manifest(prepared):
    root, _, _, _, manifest = prepared
    (root / "lake-manifest.json").write_text(json.dumps(manifest))


def test_putnam_uses_frozen_header_exact_mathlib_and_locked_aesop(prepared):
    root, pin, record, _, _ = prepared
    (root / "Putnam").mkdir()
    (root / "Putnam/Candidate.lean").write_text("-- unrelated stale candidate must not be imported")
    binding = bind(prepared)
    assert binding.prefix == record["header"]
    assert binding.putnam and not binding.project_backed
    assert binding.lake.packages[0].commit == pin.git_commit
    assert all(".lake/packages" in str(p) for p in binding.search_paths)
    inventory = native.readiness([record], [prepared[3]], root)
    assert inventory["rows"][0]["status"] == "UNMEASURED"
    assert inventory["rows"][0]["baseline_compiles"] is None
    assert inventory["rows"][0]["dependencies_verified"] is False


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0"])
def test_supported_lockfile_versions_and_escaped_names(prepared, version):
    root, _, _, _, manifest = prepared
    manifest["version"] = version
    manifest["packages"][1]["name"] = "«aesop»"
    manifest["fixedToolchain"] = True
    rewrite_manifest(prepared)
    assert bind(prepared).lake.packages[1].root == root / ".lake/packages/aesop"


@pytest.mark.parametrize("mutation,reason", [
    ("version", "schema"), ("type", "dependency_type"), ("duplicate", "duplicate"),
    ("floating_revision", "exact_lake_dependency_pin"), ("wrong_head", "dependency_commit_mismatch"),
    ("traversal", "dependency_path"), ("symlink", "escapes_project"),
    ("wrong_repo", "mathlib_repository_mismatch"), ("missing_aesop", "aesop_repository_mismatch"),
    ("dirty", "tracked_changes"), ("missing_olean", "compiled_import_missing"),
    ("root_tag", "toolchain_mismatch"), ("mathlib_tag", "tracked_changes"),
    ("override_search", "lockfile_search_paths"), ("non_putnam", "invalid_putnam"),
    ("empty_header", "bounded_putnam_header"),
])
def test_invalid_dependency_context_fails_closed(prepared, mutation, reason, tmp_path):
    root, _, record, project, manifest = prepared
    package = manifest["packages"][0]
    if mutation == "version": manifest["version"] = "99.0.0"
    elif mutation == "type": package["type"] = "path"
    elif mutation == "duplicate": manifest["packages"].append(dict(package))
    elif mutation == "floating_revision": package["rev"] = "v4.26.0"
    elif mutation == "wrong_head": package["rev"] = "0" * 40
    elif mutation == "traversal": manifest["packagesDir"] = "../outside"
    elif mutation == "symlink":
        outside = tmp_path / "outside"; outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        manifest["packagesDir"] = "escape"
    elif mutation == "wrong_repo": package["url"] = "https://example.invalid/mathlib4"
    elif mutation == "missing_aesop": manifest["packages"].pop()
    elif mutation == "dirty": (root / ".lake/packages/mathlib/Source.lean").write_text("-- changed")
    elif mutation == "missing_olean": (root / ".lake/packages/mathlib/.lake/build/lib/lean/Mathlib.olean").unlink()
    elif mutation == "root_tag": (root / "lean-toolchain").write_text("leanprover/lean4:v4.27.0")
    elif mutation == "mathlib_tag": (root / ".lake/packages/mathlib/lean-toolchain").write_text("other")
    elif mutation == "override_search": project["search_paths"] = []
    elif mutation == "non_putnam": record["source"] = "strata"
    elif mutation == "empty_header": record["header"] = ""
    rewrite_manifest(prepared)
    with pytest.raises(native.CapabilityGap, match=reason):
        bind(prepared)


def test_pins_marker_cannot_override_corpus_mathlib_commit(prepared):
    root, pin, record, project, _ = prepared
    wrong = replace(pin, git_commit="f" * 40)
    (root / "pins.json").write_text(json.dumps({"jsonl_version_pin": wrong.git_commit}))
    with pytest.raises(native.CapabilityGap, match="putnam_mathlib_commit_mismatch"):
        native.project_binding(record, wrong, project, root)


def test_change_after_binding_invalidates_context_and_receipt_cache(prepared, monkeypatch):
    binding = bind(prepared)
    adapter = native.NativeLeanVerifier({binding.pin: binding}, max_processes=0)
    context = adapter.context(prepared[2], reference_heartbeats=1)
    req = VerificationRequest(context, prepared[2]["src"], binding.pin)
    adapter.validate_request(req)
    (prepared[0] / ".lake/packages/aesop/Source.lean").write_text("-- changed")
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("no process on stale context"))
    result = adapter.evaluator(context, max_calls=1).evaluate(req.source)
    assert result.receipts[0].outcome == Outcome.ERROR
    assert adapter.processes == 0


def test_manifest_edit_requires_new_binding_even_without_revision_change(prepared):
    binding = bind(prepared)
    first = binding.fingerprint(Fingerprinter())
    prepared[-1]["note"] = "new context"
    rewrite_manifest(prepared)
    with pytest.raises(native.CapabilityGap, match="manifest_changed"):
        binding.fingerprint(Fingerprinter())
    assert bind(prepared).fingerprint(Fingerprinter()) != first


def test_compiled_artifact_edit_changes_identity(prepared):
    binding = bind(prepared)
    reader = Fingerprinter()
    before = binding.fingerprint(reader)
    (prepared[0] / ".lake/packages/aesop/.lake/build/lib/lean/Aesop.olean").write_bytes(b"changed fake artifact")
    assert binding.fingerprint(reader) != before


def test_wrong_putnam_header_is_not_authorized_by_policy_context(prepared):
    binding = bind(prepared)
    adapter = native.NativeLeanVerifier({binding.pin: binding}, max_processes=0)
    context = replace(adapter.context(prepared[2]), header="import Another\n")
    receipt = adapter(VerificationRequest(context, prepared[2]["src"], binding.pin))
    assert receipt.outcome == Outcome.ERROR and "header/context" in receipt.reason
    assert adapter.processes == 0


def test_injected_hash_cache_does_not_weaken_strict_mode(prepared):
    binding = bind(prepared)
    with pytest.raises(ValueError, match="strict injected"):
        native.NativeLeanVerifier({binding.pin: binding}, max_processes=0,
                                  strict_hashes=True, fingerprinter=Fingerprinter())


def test_discovery_keeps_every_pin_without_mutating_or_selecting_current_head(prepared, tmp_path, monkeypatch):
    _, pin, record, _, _ = prepared
    monkeypatch.setattr(native, "_git", lambda *a: pytest.fail("discovery must not inspect/mutate Git"))
    records = [record, {**record, "name": "second", "version_info": [{"v4.27.0": "c" * 40}]},
               {**record, "source": "strata", "url": "https://github.com/strata-org/Strata",
                "file_path": "Main.lean", "name": "project"}]
    projects = native.discover_projects(records, tmp_path)
    assert len(projects) == 3
    assert projects[0]["git_commit"] == pin.git_commit
    assert projects[1]["root"].endswith("putnam_lake/v4.27.0")
    assert projects[2]["root"].endswith("clones/github.com/strata-org/Strata")
    assert not (tmp_path / "putnam_lake").exists()


@pytest.mark.parametrize("url", ["file:///tmp/project", "https://github.com/../escape",
                                 "https://github.com/user/repo?revision=main", "https://host.invalid/user/repo"])
def test_discovery_only_accepts_explicit_harness_layout(tmp_path, url):
    with pytest.raises(native.CapabilityGap, match="repository_layout"):
        native.discover_projects([{"url": url, "version_info": []}], tmp_path)


def test_regular_project_can_resolve_the_same_checked_lockfile(prepared):
    root, old_pin, record, _, _ = prepared
    (root / "Source.lean").write_text("import Mathlib\nnamespace Example\n" + record["src"])
    pin = replace(old_pin, git_commit=commit_fixture(root))
    record = {**record, "source": "fixture", "url": "fixture://project", "file_path": "Source.lean"}
    project = {"root": str(root), "repository": record["url"], "resolve_lake_manifest": True}
    binding = native.project_binding(record, pin, project, root)
    assert binding.project_backed and not binding.putnam
    assert binding.prefix == "import Mathlib\nnamespace Example\n"
    assert len(binding.lake.packages) == len(binding.search_paths) == 2
    project["search_paths"] = []
    with pytest.raises(native.CapabilityGap, match="ambiguous_search"):
        native.project_binding(record, pin, project, root)


def test_transitive_dependency_git_identity_is_rechecked(prepared):
    binding = bind(prepared)
    package = binding.lake.packages[1]
    git(package.checkout, "-c", "user.name=Arena fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--allow-empty", "--quiet", "-m", "different epoch")
    with pytest.raises(native.CapabilityGap, match="dependency_commit_mismatch"):
        binding.fingerprint(Fingerprinter())


def test_git_inventory_does_not_refresh_the_shared_index(monkeypatch, tmp_path):
    def run(argv, **kwargs):
        assert argv[:3] == ["/usr/bin/git", "-C", str(tmp_path)]
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
    monkeypatch.setattr(native.subprocess, "run", run)
    assert native._git(tmp_path, "status", "--porcelain", "--untracked-files=no") == ""


def test_intake_boundary_revision_changes_dependency_identity(prepared, tmp_path, monkeypatch):
    boundary = tmp_path / "intake.py"; boundary.write_text("old boundary")
    monkeypatch.setattr(native, "BOUNDARY_FILES", (boundary,))
    binding = bind(prepared)
    reader = Fingerprinter()
    first = binding.fingerprint(reader)
    boundary.write_text("new boundary")
    assert binding.fingerprint(reader) != first


def test_old_putnam_renderer_no_longer_discards_explicit_mathlib_pin():
    sha = "a" * 40
    pin = putnam_pin_for_tag("v4.26.0", ["v4.26.0"], mathlib_git="mathlib", aesop_git="aesop",
                             jsonl_version_pin=sha)
    assert pin.mathlib_rev == sha and pin.aesop_rev == "v4.26.0"
    harness = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/harness"
    # Reuse the actual offline renderer, not a copied expected implementation.
    spec = importlib.util.spec_from_file_location("arena_bake_fixture", harness / "bake_oleans.py")
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(harness))
        patch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        files = module.putnam_project_files("v4.26.0", jsonl_version_pin=sha)
        assert '@ "' + sha + '"' in files["lakefile.lean"]
        assert json.loads(files["pins.json"])["mathlib_rev"] == sha
        assert '@ "v4.26.0"' in module.render_lakefile("v4.26.0")  # legacy tag-only API


def test_baseline_zero_budget_and_persistent_report_never_execute(prepared, tmp_path, monkeypatch, capsys):
    _, _, record, project, _ = prepared
    corpus = tmp_path / "corpus.jsonl"; corpus.write_text(json.dumps(record) + "\n")
    manifest = tmp_path / "projects.json"; manifest.write_text(json.dumps([project]))
    output = tmp_path / "baseline.json"
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("zero budget"))
    monkeypatch.setattr(sys, "argv", ["arena", "--baseline", "--corpus", str(corpus),
                                    "--projects", str(manifest), "--output", str(output)])
    assert native.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_text())
    assert report["rows"][0]["status"] == "BUDGET_EXHAUSTED"
    assert report["processes"] == report["live_model_calls"] == 0
    assert report["official_score"] is None
    with pytest.raises(SystemExit) as exc:
        native.main()
    assert exc.value.code == 2  # do not overwrite even an incomplete historical report
