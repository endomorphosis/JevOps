from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET

import pytest

from jevops.seals import Fingerprinter, SealStore, digest, seal_status, stable_value

pytestmark = pytest.mark.no_seal(reason="exercise cache behavior and subprocess/locking boundaries fresh")


def test_stat_fast_path_raw_and_ast_merkle_roots(tmp_path):
    source = tmp_path / "module.py"
    source.write_text("answer = 42\n")
    hasher = Fingerprinter()
    first = hasher.snapshot([tmp_path])
    assert hasher.reads == 1
    assert hasher.snapshot([tmp_path]) == first and hasher.stat_hits == 1
    source.write_text("# only a comment\nanswer = 42\n")
    second = hasher.snapshot([tmp_path])
    assert second.root != first.root and second.ast_root == first.ast_root
    source.write_text("answer = 43\n")
    third = hasher.snapshot([tmp_path])
    assert third.root != second.root and third.ast_root != second.ast_root
    assert Fingerprinter(hasher.files, strict=True).snapshot([tmp_path]) == third


def test_restored_mtime_same_size_atomic_replacement_and_membership(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("aaa")
    hasher = Fingerprinter()
    before = hasher.snapshot([tmp_path])
    info = source.stat()
    source.write_text("bbb")
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert hasher.snapshot([tmp_path]).root != before.root
    replacement = tmp_path / "replacement"
    replacement.write_text("ccc")
    os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
    replacement.replace(source)
    replaced = hasher.snapshot([tmp_path])
    extra = tmp_path / "empty"
    extra.mkdir()
    assert hasher.snapshot([tmp_path]).root != replaced.root
    extra.rmdir()
    assert hasher.snapshot([tmp_path]).root == replaced.root
    source.unlink()
    assert hasher.snapshot([tmp_path]).root != replaced.root


def test_persistent_fast_path_strict_hashing_and_missing_paths(tmp_path):
    source = tmp_path / "source.py"
    before = Fingerprinter().snapshot([source])
    source.write_text("x = 1\n")
    first = Fingerprinter()
    after = first.snapshot([source])
    assert after.root != before.root
    warm = Fingerprinter(json.loads(json.dumps(first.files)))
    assert warm.snapshot([source]) == after and warm.reads == 0
    strict = Fingerprinter(warm.files, strict=True)
    assert strict.snapshot([source]) == after and strict.reads == 1


def test_symlink_target_content_and_retargeting_and_cycle(tmp_path):
    a, b, link = (tmp_path / p for p in ("a", "b", "link"))
    a.write_text("a")
    b.write_text("a")
    link.symlink_to(a)
    hasher = Fingerprinter()
    first = hasher.snapshot([link])
    a.write_text("b")
    assert hasher.snapshot([link]).root != first.root
    link.unlink()
    link.symlink_to(b)
    assert hasher.snapshot([link]).root != first.root
    link.unlink()
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="cyclic"):
        hasher.snapshot([tmp_path])


def test_content_race_refuses_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "file.txt"
    source.write_text("before")
    original = Path.open

    def changing_open(path, *args, **kwargs):
        if path == source and args == ("rb",):
            with original(path, "w") as stream:
                stream.write("after")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changing_open)
    with pytest.raises(ValueError, match="changed while hashing"):
        Fingerprinter().snapshot([source])


def test_same_size_edit_with_identical_whole_second_timestamps_rehashes(tmp_path, monkeypatch):
    from jevops import seals
    source = tmp_path / "coarse.olean"
    source.write_bytes(b"one")
    original_signature = seals._signature
    def coarse(info):
        result = original_signature(info)
        # Simulate fuse2fs's second-granularity metadata, including a restored
        # mtime. Same inode, mode, size and timestamps cannot authorize reuse.
        result[4] = result[5] = 1_700_000_000_000_000_000
        return result
    monkeypatch.setattr(seals, "_signature", coarse)
    reader = Fingerprinter()
    first = reader.snapshot([source])
    source.write_bytes(b"two")
    assert reader.snapshot([source]).root != first.root
    assert reader.reads == 2 and reader.stat_hits == 0


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX cache locking")
def test_store_integrity_lock_and_status(tmp_path):
    store = SealStore(tmp_path)
    store.acquire()
    with pytest.raises(OSError):
        SealStore(tmp_path).acquire()
    store.records["test"] = {"outcome": "passed", "fingerprint": "abc"}
    store.save()
    store.close()
    loaded = SealStore(tmp_path)
    loaded.acquire()
    assert seal_status(loaded.records["test"], "abc") == "sealed"
    assert seal_status(loaded.records["test"], "def") == "stale"
    assert seal_status({"outcome": "failed", "fingerprint": "abc"}, "abc") == "failing"
    assert seal_status(None, "abc") == "unsealed"
    loaded.close()
    envelope = json.loads(store.path.read_text())
    envelope["payload"]["records"]["test"]["fingerprint"] = "forged"
    store.path.write_text(json.dumps(envelope))
    corrupt = SealStore(tmp_path)
    corrupt.acquire()
    assert corrupt.records == {} and corrupt.files == {}
    corrupt.close()
    store.path.write_text("{")
    corrupt.acquire()
    assert corrupt.records == {}
    corrupt.close()


def test_stable_parameters_are_type_safe_and_reject_arbitrary_objects():
    assert stable_value({"a": 1, "b": 2}) == stable_value({"b": 2, "a": 1})
    assert len({digest(stable_value(v)) for v in (True, 1, 1.0, "1", b"1", [1], (1,))}) == 7
    with pytest.raises(ValueError, match="parameter type"):
        stable_value(object())


@pytest.fixture
def project(tmp_path):
    if os.name != "posix":
        pytest.skip("reuse integration tests require POSIX cache locking")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "helper.py").write_text("VALUE = 1\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\ntest_seal_roots = src\n")
    root = Path(__file__).resolve().parents[1]
    # Test the exact plugin implementation in a stable, isolated source tree.
    # Other agents editing unrelated jevops modules must not turn an intended
    # warm-cache assertion into a legitimate source-tree invalidation.
    plugin = tmp_path / "seal_plugin"
    plugin.mkdir()
    (plugin / "__init__.py").write_text("")
    for filename in ("seals.py", "pytest_seals.py"):
        shutil.copyfile(root / "jevops" / filename, plugin / filename)

    class Project:
        def write(self, source, name="test_example.py"):
            (tmp_path / name).write_text(textwrap.dedent(source))

        def run(self, mode=None, *args, env=None, expected=0):
            process_env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                           "PYTHONPATH": str(tmp_path)}
            process_env.pop("PYTEST_CURRENT_TEST", None)
            process_env.pop("PYTEST_ADDOPTS", None)
            process_env.update(env or {})
            result = subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "seal_plugin.pytest_seals",
                "--confcutdir", str(tmp_path), "-q", *([f"--test-seal={mode}"] if mode else []), *args],
                cwd=tmp_path, env=process_env, capture_output=True, text=True, timeout=40)
            assert result.returncode == expected, result.stdout + result.stderr
            return result.stdout

        @property
        def records(self):
            return json.loads((tmp_path / ".pytest_cache/d/test-seals/manifest.json").read_text())["payload"]["records"]

        path = tmp_path

    return Project()


SIMPLE = '''
    import pytest
    from src.helper import VALUE
    @pytest.mark.seal(hermetic=True)
    def test_value():
        assert VALUE == 1
'''


def test_plugin_cold_warm_refresh_status_off_and_junit(project):
    project.write(SIMPLE)
    assert "1 passed" in project.run()
    assert "1 fresh passes sealed" in project.run("refresh")
    assert "1 sealed" in project.run("reuse", "--junitxml=result.xml")
    root = ET.parse(project.path / "result.xml").getroot()
    case = root.find(".//testcase")
    assert case.find("skipped") is not None
    assert case.find("properties/property[@name='test_seal']").attrib["value"] == "reused"
    assert "sealed   test_example.py::test_value" in project.run("status")
    assert "1 passed" in project.run("off")
    assert "1 sealed" in project.run()


def test_plugin_transitive_source_environment_and_parameter_invalidation(project):
    project.write(SIMPLE)
    project.run()
    helper = project.path / "src/helper.py"
    helper.write_text("# same AST, different bytes\nVALUE = 1\n")
    assert "stale" in project.run("status", expected=1)
    assert "1 passed" in project.run()
    assert "1 passed" in project.run(env={"SEALED_INPUT": "changed"})
    assert "1 sealed" in project.run(env={"SEALED_INPUT": "changed"})
    project.write('''
        import os
        import pytest
        @pytest.mark.seal(hermetic=True)
        @pytest.mark.parametrize("x", [int(os.environ.get("PARAM", "1"))], ids=["stable-id"])
        def test_value(x):
            assert x > 0
    ''')
    assert "1 passed" in project.run()
    assert "1 passed" in project.run(env={"PARAM": "2"})
    assert "1 sealed" in project.run(env={"PARAM": "2"})


def test_plugin_failure_is_recorded_never_reused_then_repaired(project):
    project.write(SIMPLE)
    helper = project.path / "src/helper.py"
    helper.write_text("VALUE = 0\n")
    assert "1 failed" in project.run(expected=1)
    assert "failing" in project.run("status", expected=1)
    assert "1 failed" in project.run(expected=1)
    helper.write_text("VALUE = 1\n")
    assert "stale" in project.run("status", expected=1)
    assert "1 passed" in project.run()
    assert "1 sealed" in project.run()


def test_plugin_injected_file_and_directory_dependencies(project):
    external = project.path / "external"
    external.mkdir()
    (external / "data.txt").write_text("ok")
    project.write('''
        import pytest
        @pytest.fixture
        def data(seal_dependencies):
            return seal_dependencies.path("external/data.txt").read_text()
        @pytest.mark.seal(hermetic=True)
        def test_value(data, seal_dependencies):
            seal_dependencies.path("external")
            assert data == "ok"
    ''')
    assert "1 passed" in project.run()
    assert len(next(iter(project.records.values()))["paths"]) == 2
    assert "1 sealed" in project.run()
    (external / "new.txt").write_text("new")
    assert "1 passed" in project.run()
    assert "1 sealed" in project.run()
    (external / "data.txt").write_text("no")
    assert "1 failed" in project.run(expected=1)


@pytest.mark.parametrize("kind", ["setup", "call", "teardown", "session_teardown", "skip", "xfail", "xpass"])
def test_plugin_never_seals_incomplete_or_unsuccessful_lifecycle(project, kind):
    behavior = {
        "setup": ('raise RuntimeError("setup")', "assert True", "pass"),
        "call": ("pass", "assert False", "pass"),
        "teardown": ("pass", "assert True", 'raise RuntimeError("teardown")'),
        "session_teardown": ("pass", "assert True", 'raise RuntimeError("late teardown")'),
        "skip": ("pass", 'pytest.skip("skip")', "pass"),
        "xfail": ("pass", 'pytest.xfail("xfail")', "pass"),
        "xpass": ("pass", "assert True", "pass"),
    }[kind]
    scope = "session" if kind == "session_teardown" else "function"
    extra = '@pytest.mark.xfail(reason="expected")' if kind == "xpass" else ""
    project.write(f'''
        import pytest
        @pytest.fixture(scope="{scope}", autouse=True)
        def dependency():
            {behavior[0]}
            yield
            {behavior[2]}
        @pytest.mark.seal(hermetic=True)
        {extra}
        def test_value():
            {behavior[1]}
    ''')
    expected = 1 if kind in {"setup", "call", "teardown", "session_teardown"} else 0
    project.run(expected=expected)
    assert not any(r["outcome"] == "passed" for r in project.records.values())
    assert "1 sealed" not in project.run(expected=expected)


def test_dependency_mutation_during_test_refuses_seal(project):
    (project.path / "data.txt").write_text("before")
    project.write('''
        import pytest
        @pytest.mark.seal(hermetic=True)
        def test_value(seal_dependencies):
            path = seal_dependencies.path("data.txt")
            path.write_text("after")
            assert path.read_text() == "after"
    ''')
    project.run()
    assert not project.records


def test_unknown_parameters_execute_fresh_but_unmarked_tests_reuse(project):
    project.write('''
        import pytest
        @pytest.mark.seal(hermetic=True)
        @pytest.mark.parametrize("value", [object()])
        def test_opaque(value):
            assert value is not None
        def test_unmarked():
            assert True
    ''')
    assert "2 passed" in project.run()
    assert "1 passed, 1 sealed" in project.run()
    assert "untracked parameter type" in project.run("status", expected=1)


def test_corrupt_manifest_causes_fresh_execution(project):
    project.write(SIMPLE)
    project.run()
    (project.path / ".pytest_cache/d/test-seals/manifest.json").write_text("broken")
    assert "1 passed" in project.run()
    assert "1 sealed" in project.run()


def test_force_run_revokes_old_pass_before_interruption(project):
    project.write(SIMPLE)
    project.run()
    project.write(SIMPLE.replace("assert VALUE == 1", "raise KeyboardInterrupt()"))
    project.run("refresh", expected=2)
    assert not project.records


def test_injected_tool_tracks_resolution_and_binary_content(project):
    tool = project.path / "compiler"
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    project.write('''
        import pytest
        @pytest.mark.seal(hermetic=True)
        def test_value(seal_dependencies):
            assert seal_dependencies.tool("./compiler")
    ''')
    project.run()
    assert "1 sealed" in project.run()
    tool.write_text("#!/bin/sh\nexit 1\n")
    assert "1 passed" in project.run()
    assert "1 sealed" in project.run()


def test_autouse_fixture_code_changes_invalidate_and_module_cleanup_survives_hits(project):
    project.write('''
        import pytest
        from pathlib import Path
        @pytest.fixture(scope="module", autouse=True)
        def shared():
            yield
            Path("cleanup.txt").write_text("done")
        @pytest.mark.no_seal(reason="exercise pending shared fixture teardown")
        def test_fresh():
            assert True
        @pytest.mark.seal(hermetic=True)
        def test_cached():
            assert True
    ''')
    assert "2 passed" in project.run()
    cleanup = project.path / "cleanup.txt"
    cleanup.unlink()
    assert "1 passed, 1 sealed" in project.run()
    assert cleanup.read_text() == "done"
    source = project.path / "test_example.py"
    source.write_text(source.read_text().replace('write_text("done")', 'write_text("again")'))
    assert "2 passed" in project.run()
    assert cleanup.read_text() == "again"


def test_late_session_fixture_error_does_not_promote_earlier_passes(project):
    project.write('''
        import pytest
        @pytest.fixture(scope="session", autouse=True)
        def late():
            yield
            raise RuntimeError("late session teardown")
        @pytest.mark.seal(hermetic=True)
        def test_first():
            assert True
        @pytest.mark.seal(hermetic=True)
        def test_last():
            assert True
    ''')
    project.run(expected=1)
    assert "test_example.py::test_first" not in project.records
    assert all(r["outcome"] == "failed" for r in project.records.values())


def test_static_declared_data_and_hermetic_false_opt_out(project):
    (project.path / "data.txt").write_text("ok")
    project.write('''
        import pytest
        from pathlib import Path
        @pytest.mark.seal(hermetic=True, paths=["data.txt"])
        def test_value():
            assert Path("data.txt").read_text() == "ok"
        @pytest.mark.seal(hermetic=False)
        def test_opted_out():
            assert True
    ''')
    assert "2 passed" in project.run()
    assert "1 passed, 1 sealed" in project.run()
    (project.path / "data.txt").write_text("no")
    assert "1 failed, 1 passed" in project.run(expected=1)


def test_strict_reuse_reads_bytes_and_does_not_store_environment_secrets(project):
    project.write(SIMPLE)
    secret = {"SEAL_PRIVATE_TEST_KEY": "do-not-persist-this-test-secret"}
    project.run(env=secret)
    out = project.run("reuse", "--test-seal-strict", env=secret)
    assert "1 sealed" in out and " 0 file reads" not in out
    manifest = (project.path / ".pytest_cache/d/test-seals/manifest.json").read_text()
    assert secret["SEAL_PRIVATE_TEST_KEY"] not in manifest
    assert "SEAL_PRIVATE_TEST_KEY" not in manifest


def test_cache_lock_contention_falls_back_to_execution(project):
    project.write(SIMPLE)
    project.run()
    store = SealStore(project.path / ".pytest_cache/d/test-seals")
    store.acquire()
    try:
        out = project.run()
        assert "1 passed" in out and "disabled" in out
    finally:
        store.close()


def test_parallel_mode_falls_back_to_execution(project):
    project.write(SIMPLE)
    out = project.run("reuse", "-p", "xdist.plugin", "-n", "1")
    assert "1 passed" in out and "parallel workers are not supported" in out


def test_status_does_not_execute_fixtures_or_body(project):
    project.write('''
        import pytest
        @pytest.fixture(autouse=True)
        def fixture():
            raise AssertionError("fixture executed")
        @pytest.mark.seal(hermetic=True)
        def test_value():
            raise AssertionError("body executed")
    ''')
    out = project.run("status", expected=1)
    assert "unsealed" in out and "no tests ran" in out


def test_changed_global_source_during_test_does_not_seal(project):
    project.write('''
        import pytest
        from pathlib import Path
        @pytest.mark.seal(hermetic=True)
        def test_value():
            Path("src/helper.py").write_text("VALUE = 9")
    ''')
    project.run()
    assert not project.records


def test_default_reuses_unmarked_tests_and_off_refresh_remain_explicit(project):
    project.write('''
        def test_unmarked():
            assert True
    ''')
    assert "1 passed" in project.run()
    assert "1 sealed" in project.run()
    assert "sealed   test_example.py::test_unmarked" in project.run("status")
    assert "1 passed" in project.run("off")
    assert "1 fresh passes sealed" in project.run("refresh")
    assert "1 sealed" in project.run()


def test_on_and_legacy_reuse_share_the_default_fingerprint(project):
    project.write('''
        from pathlib import Path
        def test_unmarked():
            counter = Path("executions.txt")
            count = int(counter.read_text()) if counter.exists() else 0
            counter.write_text(str(count + 1))
    ''')
    assert "1 fresh passes sealed" in project.run("on")
    for mode in ("on", "reuse", None):
        assert "1 sealed" in project.run(mode)
    assert (project.path / "executions.txt").read_text() == "1"
    assert "1 passed" in project.run("off")
    assert "1 fresh passes sealed" in project.run("refresh")
    assert (project.path / "executions.txt").read_text() == "3"
    assert "1 sealed" in project.run("on")


def test_repository_on_addopts_and_explicit_override(project):
    from configparser import ConfigParser
    config = ConfigParser()
    config.read(Path(__file__).resolve().parents[1] / "pytest.ini")
    assert "--test-seal=on" in config["pytest"]["addopts"].split()
    assert {"module_environment", "live_profile"} <= set(config["pytest"]["test_seal_fresh_fixtures"].split())
    (project.path / "pytest.ini").write_text(
        "[pytest]\ntest_seal_roots = src\naddopts = --test-seal=on\n")
    project.write(SIMPLE)
    assert "1 fresh passes sealed" in project.run()
    assert "1 sealed" in project.run()
    # CLI options follow ini addopts: explicit opt-out still wins.
    assert "1 passed" in project.run("off")
    assert "1 fresh passes sealed" in project.run("refresh")
    assert "sealed   test_example.py::test_value" in project.run("status")
    assert "1 sealed" in project.run("reuse")


def test_default_still_invalidates_changed_code(project):
    project.write(SIMPLE.replace("    @pytest.mark.seal(hermetic=True)\n", ""))
    project.run()
    assert "1 sealed" in project.run()
    (project.path / "src/helper.py").write_text("VALUE = 0\n")
    assert "1 failed" in project.run(expected=1)
    assert "failing" in project.run("status", expected=1)


@pytest.mark.parametrize("scope", ["function", "class", "module", "parameter"])
def test_no_seal_opt_out_inherits_and_cannot_be_overridden_by_seal(project, scope):
    sources = {
        "function": '''
            import pytest
            @pytest.mark.no_seal(reason="live service")
            @pytest.mark.seal(hermetic=True)
            def test_value():
                assert True
        ''',
        "class": '''
            import pytest
            @pytest.mark.no_seal(reason="live service")
            class TestValue:
                @pytest.mark.seal(hermetic=True)
                def test_value(self):
                    assert True
        ''',
        "module": '''
            import pytest
            pytestmark = pytest.mark.no_seal(reason="live service")
            @pytest.mark.seal(hermetic=True)
            def test_value():
                assert True
        ''',
        "parameter": '''
            import pytest
            @pytest.mark.parametrize("value", [pytest.param(1, marks=pytest.mark.no_seal(reason="live service"))])
            def test_value(value):
                assert value == 1
        ''',
    }
    project.write(sources[scope])
    assert "1 passed" in project.run()
    assert "1 passed" in project.run()
    assert not project.records
    assert "explicit opt-out: live service" in project.run("status", expected=1)


def test_fresh_fixture_protection_includes_transitive_shared_consumers(project):
    (project.path / "pytest.ini").write_text(
        "[pytest]\ntest_seal_roots = src\ntest_seal_fresh_fixtures = live_input\n")
    project.write('''
        import pytest
        @pytest.fixture(scope="module")
        def live_input():
            return 1
        @pytest.fixture
        def proxy(live_input):
            return live_input
        def test_direct(live_input):
            assert live_input == 1
        @pytest.mark.seal(hermetic=True)
        def test_transitive(proxy):
            assert proxy == 1
        def test_pure():
            assert True
    ''')
    assert "3 passed" in project.run()
    assert "2 passed, 1 sealed" in project.run()
    assert set(project.records) == {"test_example.py::test_pure"}
    assert "fresh execution required by fixture: live_input" in project.run("status", expected=1)


def test_dependency_marker_no_longer_requires_hermetic_opt_in(project):
    project.write('''
        import pytest
        @pytest.mark.seal()
        def test_value():
            assert True
    ''')
    assert "1 passed" in project.run()
    assert "1 sealed" in project.run()
