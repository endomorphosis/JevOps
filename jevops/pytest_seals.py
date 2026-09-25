"""Opt-out pytest seals; see TEST_SEALS.md for the dependency contract."""
from __future__ import annotations

import importlib.metadata
import inspect
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import pytest

from .seals import Fingerprinter, SealStore, digest, seal_status, stable_value

# These options affect selection/reporting, not a cacheable hermetic test.
_PRESENTATION = frozenset({
    "test_seal", "test_seal_strict", "file_or_dir", "keyword", "markexpr",
    "collectonly", "verbose", "no_header", "no_summary", "reportchars",
    "tbstyle", "color", "code_highlight", "durations", "durations_min",
    "xmlpath", "junitprefix", "cacheclear", "lf", "failedfirst", "newfirst",
    "last_failed_no_failures", "maxfail", "fold_skipped", "force_short_summary",
})


def pytest_addoption(parser):
    group = parser.getgroup("test seals")
    group.addoption("--test-seal", choices=("on", "off", "reuse", "refresh", "status"), default="on",
                    help="on (default) reuses sealed passes; reuse is an alias; off disables caching; "
                         "refresh runs fresh; status inspects")
    group.addoption("--test-seal-strict", action="store_true",
                    help="Rehash bytes instead of trusting unchanged stat tuples")
    parser.addini("test_seal_roots", "Source/input trees conservatively bound to every seal", type="linelist",
                  default=["."])
    parser.addini("test_seal_fresh_fixtures", "Fixture names whose consumers must always execute fresh",
                  type="linelist", default=[])


def pytest_configure(config):
    config.addinivalue_line("markers", "seal(hermetic=True, paths=(), tools=()): optional dependency "
                           "declarations; hermetic=False opts out of test-result reuse")
    config.addinivalue_line("markers", "no_seal(reason): always execute this test/class/module fresh")
    plugin = SealPlugin(config)
    config._jevops_seals = plugin
    config.pluginmanager.register(plugin, "jevops-seal-runtime")


@pytest.fixture
def seal_dependencies(request):
    """Register input paths BEFORE reading them; registration is replayed on hits.

    A directory includes its membership and recursive contents. Tools bind the
    resolved executable, NOT its libraries/toolchain; register those separately.
    This fixture remains usable in ordinary, uncached pytest runs.
    """
    plugin = request.config._jevops_seals
    return plugin.dependencies.setdefault(request.node.nodeid, Dependencies(plugin))


class Dependencies:
    def __init__(self, plugin):
        self.plugin = plugin
        self.paths: dict[str, str] = {}
        self.tools: dict[str, str] = {}
        self.error = ""

    def path(self, path: str | Path) -> Path:
        resolved = self.plugin.path(path)
        try:
            self.paths.setdefault(str(resolved), self.plugin.hasher.snapshot([resolved]).root)
        except (OSError, ValueError, RuntimeError) as exc:
            self.error = str(exc)
        return resolved

    def tool(self, name: str) -> str | None:
        executable = shutil.which(name)
        try:
            self.tools.setdefault(name, self.plugin.tool_digest(name))
        except (OSError, ValueError, RuntimeError) as exc:
            self.error = str(exc)
        return executable


class SealPlugin:
    def __init__(self, config):
        self.config = config
        selected_mode = config.getoption("test_seal")
        # Keep one internal reuse path. The spelling is presentation-only and
        # must not change the dependency fingerprint or grant fresh evidence.
        self.mode = "reuse" if selected_mode == "on" else selected_mode
        self.hasher = Fingerprinter(strict=config.getoption("test_seal_strict"))
        self.store = None
        self.disabled = ""
        self.paths = []
        self.context = None
        self.baseline = None
        self.plans = {}
        self.dependencies = {}
        self.reports = {}
        self.reused = set()
        self.attempted = set()
        self.counts = {}
        self.promoted = 0

    def path(self, path):
        # Keep symlink identity: resolving it here would lose retargeting evidence.
        return Path(os.path.abspath(self.config.rootpath / path))

    def tool_digest(self, name):
        executable = shutil.which(name)
        return digest([executable, self.hasher.snapshot([executable]).root if executable else None])

    def runtime(self):
        environment = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
        # Values (including credentials) are never stored in the manifest.
        return digest({"environment": environment, "cwd": os.getcwd(), "path": sys.path,
                       "python": sys.version, "executable": sys.executable,
                       "platform": platform.platform(), "flags": tuple(sys.flags),
                       "options": {k: stable_value(v) for k, v in vars(self.config.option).items()
                                   if k not in _PRESENTATION}})

    def disable(self, reason):
        self.disabled = reason
        reporter = self.config.pluginmanager.getplugin("terminalreporter")
        if reporter:
            reporter.write_line(f"test seals disabled; tests execute normally: {reason}")

    def pytest_sessionstart(self, session):
        if self.mode == "off":
            return
        option = self.config.option
        if (getattr(option, "numprocesses", None) or hasattr(self.config, "workerinput")
                or getattr(option, "dist", "no") != "no"):
            self.disable("parallel workers are not supported")
            return
        if (getattr(option, "cov_source", None) or getattr(option, "reruns", 0)
                or option.setuponly or option.setupplan):
            self.disable("coverage, reruns, and setup-only modes require fresh execution")
            return
        if not hasattr(self.config, "cache"):
            self.disable("pytest cache provider is unavailable")
            return
        try:
            self.store = SealStore(self.config.cache.mkdir("test-seals"))
            self.store.acquire()
            self.hasher.files = self.store.files
            self.paths = [self.path(p) for p in self.config.getini("test_seal_roots")]
            self.paths.extend(self.path(p) for p in (
                "conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
                "requirements.txt", "requirements-dev.txt", "uv.lock", "poetry.lock", "lean-toolchain"))
            self.paths.extend([Path(__file__), Path(__file__).with_name("seals.py"), Path(sys.executable)])
            plugins = []
            for name, plugin in self.config.pluginmanager.list_name_plugin():
                source = getattr(plugin, "__file__", None)
                if source:
                    path = Path(source).resolve()
                    # Include plugin helper modules, not just its entrypoint.
                    while (path.parent / "__init__.py").is_file():
                        path = path.parent
                    self.paths.append(path)
                    plugins.append((name, str(path)))
            packages = sorted((d.metadata.get("Name", ""), d.version,
                               digest(d.read_text("direct_url.json")))
                              for d in importlib.metadata.distributions())
            self.context = digest({"plugins": sorted(plugins), "packages": packages})
            self.baseline = self.hasher.snapshot(self.paths)
        except (OSError, ValueError, TypeError, RuntimeError, ImportError) as exc:
            self.disable(str(exc))

    def fingerprint(self, plan, dependencies, *, base=None):
        inputs = self.hasher.snapshot(plan["paths"] + list(dependencies.paths))
        tools = {name: self.tool_digest(name) for name in sorted(set(plan["tools"]) | set(dependencies.tools))}
        if base is None:
            base = self.hasher.snapshot(self.paths)
        root = digest({"base": base.root, "context": self.context, "runtime": self.runtime(),
                       "identity": plan["identity"], "inputs": inputs.root, "tools": tools})
        return root, base, inputs

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        if self.mode == "off" or self.disabled:
            return
        # No tests/fixtures execute in this loop. Share the conservative tree
        # snapshot, then check it again before each test and at session finish.
        try:
            base = self.hasher.snapshot(self.paths)
        except (OSError, ValueError, RuntimeError) as exc:
            self.disable(str(exc))
            return
        fresh_fixtures = set(self.config.getini("test_seal_fresh_fixtures"))
        for item in items:
            marker = item.get_closest_marker("seal")
            plan = {"state": "unsealed", "reason": "", "paths": [], "tools": []}
            self.plans[item.nodeid] = plan
            try:
                opted_out = item.get_closest_marker("no_seal")
                if opted_out is not None:
                    reason = opted_out.kwargs.get("reason") or (opted_out.args[0] if opted_out.args else "no_seal marker")
                    raise ValueError(f"explicit opt-out: {reason}")
                kwargs = marker.kwargs if marker else {}
                if marker and marker.args:
                    raise ValueError("seal accepts keyword arguments only")
                if kwargs.get("hermetic", True) is False:
                    raise ValueError("explicit opt-out: hermetic=False")
                if kwargs.get("hermetic", True) is not True:
                    raise ValueError("hermetic must be a boolean")
                if set(kwargs) - {"hermetic", "paths", "tools"}:
                    raise ValueError("unknown seal marker argument")
                paths, tools = kwargs.get("paths", ()), kwargs.get("tools", ())
                if (not isinstance(paths, (list, tuple)) or not all(isinstance(p, (str, Path)) for p in paths)
                        or not isinstance(tools, (list, tuple)) or not all(isinstance(t, str) for t in tools)):
                    raise ValueError("seal paths/tools must be lists or tuples")
                if not isinstance(item, pytest.Function):
                    raise ValueError("only Python function tests are supported")
                if item.get_closest_marker("xfail") or item.get_closest_marker("skip") or item.get_closest_marker("skipif"):
                    raise ValueError("skip/xfail tests are never sealed")
                if hasattr(item.obj, "hypothesis") or "benchmark" in item.fixturenames:
                    raise ValueError("generative/benchmark tests require fresh execution")
                protected = fresh_fixtures.intersection(item.fixturenames)
                if protected:
                    raise ValueError("fresh execution required by fixture: " + ", ".join(sorted(protected)))
                plan["paths"] = [str(self.path(p)) for p in paths] + [str(item.path)]
                for definitions in item._fixtureinfo.name2fixturedefs.values():
                    for definition in definitions:
                        source = inspect.getsourcefile(definition.func)
                        if source is None:
                            raise ValueError("fixture has no trackable source")
                        plan["paths"].append(source)
                plan["tools"] = list(tools)
                plan["identity"] = digest({"nodeid": item.nodeid,
                    "parameters": stable_value(getattr(getattr(item, "callspec", None), "params", {})),
                    "markers": [(m.name, stable_value(m.args), stable_value(m.kwargs))
                                for m in item.iter_markers() if m.name not in {"seal", "parametrize"}],
                    "declaration": {"paths": sorted(plan["paths"]), "tools": sorted(tools)}})
                deps = Dependencies(self)
                previous = self.store.records.get(item.nodeid, {})
                for path in previous.get("paths", []):
                    deps.path(path)
                for tool in previous.get("tools", []):
                    deps.tool(tool)
                self.dependencies[item.nodeid] = deps
                root, _, _ = self.fingerprint(plan, deps, base=base)
                if base.root != self.baseline.root:
                    raise ValueError("source inputs changed during collection")
                if deps.error:
                    raise ValueError(deps.error)
                plan.update(fingerprint=root, state=seal_status(previous, root))
            except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
                plan["reason"] = str(exc)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session):
        if self.mode != "status":
            return None
        # A status query collects/imports tests but never invokes their fixtures/body.
        reporter = self.config.pluginmanager.getplugin("terminalreporter")
        unresolved = False
        for item in session.items:
            plan = self.plans.get(item.nodeid, {})
            state = plan.get("state", "unsealed") if not self.disabled else "unsealed"
            reason = self.disabled or plan.get("reason", "")
            if reporter:
                reporter.write_line(f"{state:8} {item.nodeid}" + (f" ({reason})" if reason else ""))
            self.counts[state] = self.counts.get(state, 0) + 1
            unresolved |= state != "sealed"
        if unresolved:
            session.testsfailed += 1  # Status is not a fabricated successful test run.
        return True

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item):
        if self.mode not in {"reuse", "refresh"} or self.disabled:
            return
        plan = self.plans.get(item.nodeid)
        if not plan or plan["reason"]:
            return
        try:
            root, base, _ = self.fingerprint(plan, self.dependencies[item.nodeid])
            if base.root != self.baseline.root:
                plan["reason"] = "source inputs changed during session"
                return
            plan["fingerprint"] = root
            if self.mode == "reuse" and seal_status(self.store.records.get(item.nodeid), root) == "sealed":
                self.reused.add(item.nodeid)
                item.user_properties.extend([("test_seal", "reused"), ("test_seal_root", root)])
                pytest.skip(f"sealed pass reused ({root[:12]}); no fresh execution")
            plan["static_before"] = self.fingerprint(plan, Dependencies(self), base=base)[0]
            # Revoke BEFORE execution so interruptions can never leave an old pass.
            if self.store.records.pop(item.nodeid, None) is not None:
                self.store.save()
            self.attempted.add(item.nodeid)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.disable(str(exc))

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self, item, call):
        report = yield
        if self.mode == "off":
            return report
        self.reports.setdefault(item.nodeid, []).append(report)
        if item.nodeid in self.reused and report.when == "setup" and report.skipped:
            report.test_seal_reused = True
        return report

    @pytest.hookimpl(tryfirst=True)
    def pytest_report_teststatus(self, report):
        if getattr(report, "test_seal_reused", False):
            return "sealed", "C", "SEALED"

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        if self.store is None or self.store._lock is None:
            return
        try:
            if self.mode == "status" or self.disabled:
                return
            # Session/module fixture teardown errors invalidate this session's reuse.
            if exitstatus != 0:
                for node in self.plans:
                    self.store.records.pop(node, None)
            # All fixture finalizers have completed; no test executes below.
            base = self.hasher.snapshot(self.paths)
            for node in self.attempted:
                plan, deps = self.plans[node], self.dependencies[node]
                root, _, inputs = self.fingerprint(plan, deps, base=base)
                unchanged = (base.root == self.baseline.root and not deps.error
                             and all(self.hasher.snapshot([p]).root == h for p, h in deps.paths.items())
                             and all(self.tool_digest(n) == h for n, h in deps.tools.items()))
                # Also check inputs declared statically, environment and parameters.
                original_deps = Dependencies(self)
                previous_root, _, _ = self.fingerprint(plan, original_deps, base=base)
                # New injected paths legitimately change the root; static inputs must not.
                static_before = plan["static_before"]
                if not unchanged or previous_root != static_before:
                    continue
                reports = self.reports.get(node, [])
                failed = any(r.failed for r in reports)
                passed = (len(reports) == 3 and {r.when for r in reports} == {"setup", "call", "teardown"}
                          and all(r.passed and not hasattr(r, "wasxfail") for r in reports))
                if not failed and not (passed and exitstatus == 0):
                    continue
                self.store.records[node] = {"outcome": "failed" if failed else "passed",
                    "fingerprint": root, "base_root": base.root, "ast_root": base.ast_root,
                    "inputs_root": inputs.root, "paths": sorted(deps.paths), "tools": sorted(deps.tools),
                    "recorded_at": time.time(), "fresh_execution": True}
                self.promoted += int(not failed)
            self.store.save()
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.disable(str(exc))
        finally:
            self.store.close()

    def pytest_unconfigure(self):
        if self.store is not None:
            self.store.close()

    def pytest_terminal_summary(self, terminalreporter):
        if self.mode == "off":
            return
        if self.disabled:
            terminalreporter.write_line(f"test seals unavailable: {self.disabled}")
        else:
            terminalreporter.write_line(f"test seals: {len(self.reused)} reused; {self.promoted} fresh passes sealed; "
                                       f"{self.hasher.reads} file reads, {self.hasher.stat_hits} stat hits")
