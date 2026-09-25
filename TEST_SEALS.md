# Incremental pytest seals

Test seals reuse **previous local test evidence**, never Lean proof authority.
Reuse is **enabled by default**: normal `python -m pytest` seals eligible passing
tests and reuses their evidence on subsequent unchanged runs. Ordinary unmarked
tests are eligible; no `seal` decorator or command-line flag is required.
The repository sets `addopts = --test-seal=on` in `pytest.ini`, and the plugin
also defaults to `on` when loaded elsewhere. Use the standard double-hyphen
pytest option `--test-seal=on` (not `-test-seal=on`). `reuse` remains an exact
backward-compatible alias for `on`, sharing the same fingerprints and cache.

```bash
# Cold run records passing evidence; warm run reports C / SEALED without the body.
python -m pytest --test-seal=on tests/test_ir_dependencies.py

# Opt out globally: execute normally without reading or updating seals.
python -m pytest --test-seal=off

# Inspect sealed / stale / failing / unsealed without running fixtures or bodies.
python -m pytest tests/test_ir_dependencies.py --test-seal=status -q

# Refresh evidence through real execution, including on already sealed tests.
python -m pytest tests/test_ir_dependencies.py --test-seal=refresh

# Re-read every input byte instead of trusting filesystem stat fast paths.
python -m pytest tests/test_ir_dependencies.py --test-seal=on --test-seal-strict
```

`status` still performs pytest collection (which imports Python modules). It exits
zero only if every selected test is sealed; unresolved/stale/failing/opted-out tests
produce a nonzero exit. It does not update evidence. `failing` means the last fresh
attempt failed under the **current** fingerprint; changed inputs make it `stale`.
Unsuccessful executions are never reused. `--test-seal=refresh` executes eligible
tests and refreshes evidence; `off` executes without updating evidence. CI and
proof/benchmark certification should explicitly request fresh execution.

## Opting out

```python
import pytest

@pytest.mark.no_seal(reason="depends on a live service")
def test_live_service():
    ...

# Alternatively place this at module scope to keep the whole module fresh:
pytestmark = pytest.mark.no_seal(reason="integration checks require fresh execution")
```

The marker applies to a test, parametrized case, class, or module, and wins over
`seal` declarations on children. `seal(hermetic=False)` also opts out. Existing
`seal(hermetic=True)` declarations continue to work but are no longer required;
plain `seal()` and `seal(paths=[...])` are valid optional dependency declarations.

Tests using fixture names listed in `test_seal_fresh_fixtures` always execute
fresh, including **transitive** consumers and later consumers of shared fixtures.
The repository lists its known native Lean fixtures here, covering native
replay, expression DAGs, capture, compound/transfer training, router runs,
module visibility/axiom checks, and the `live_profile` shared by Docker and
separate-process replay canaries. Direct portable-rule, hidden-binder, module
audit and provider checks also use `no_seal` markers.
Existing `skipif`-guarded native tests also remain ineligible, even when their
skip condition is false. Boundary socket/timeout probes and seal self-tests
explicitly opt out. These protections are not a general detector of every native
call or network access: new non-hermetic tests must opt out too.

## Dependency injection and the default contract

```python
import pytest

@pytest.fixture
def corpus(seal_dependencies):
    # Register BEFORE reading. Relative paths are relative to pytest's rootdir.
    path = seal_dependencies.path("tests/fixtures/corpus.json")
    return path.read_text()

@pytest.mark.seal(paths=["some/external/input-directory"])
def test_corpus(corpus):
    assert corpus
```

`seal_dependencies.path(path)` binds a file, a missing path, or an entire directory
and returns its absolute `Path`. Directory membership is rescanned, so additions
and deletions invalidate seals. `seal_dependencies.tool("compiler")` binds tool
resolution and executable content, and returns the executable path or `None`.
Static `paths=[...]` and `tools=[...]` marker arguments work before fixture setup.
Runtime registrations are stored and checked **without rerunning the fixture** on
the next invocation. Obsolete runtime registrations are retained conservatively.
The fixture also works with caching off. Avoid registering generated outputs or
per-run temporary directories: these are not stable input dependencies.

Default eligibility assumes the following contract; it is **not** a property the
plugin proves from an AST. Declare additional inputs or opt out when it does not
hold. An explicit `hermetic=True` marker does not strengthen this assumption:

- Test results must depend only on tracked inputs. Tests must be independent of
  execution order, clock time, unseeded randomness, network services, mutable
  databases, and undocumented ambient state.
- Skipping a test and its fixture setup must not remove effects needed by another
  test. Fixtures shared by eligible tests must satisfy the same independence
  contract. Fixture **source** is tracked; arbitrary live fixture values are not.
- Declare data, dynamically imported code outside source roots, external editable
  packages, and native libraries/toolchain trees. Installed distribution versions
  are tracked, but version strings do not attest every installed package byte.
- Do not run cache reuse while editing source in the same process/session. Source
  changes during collection/execution and unstable file reads suppress sealing;
  this is not a transactional filesystem or protection against adversarial races.
- A binary hash alone does not bind its shared libraries, environment-dependent
  launcher target, Lean standard library, Mathlib, `.olean` imports, Lake config,
  or native plugins. Keep native proof/benchmark/canary checks opted out unless
  the complete toolchain and inputs are bound and historical reuse is appropriate.
- Seals are appropriate for deterministic development regression checks. Use
  fresh CI/canary/coverage runs to discover flakiness and validate the contract.

## Fingerprints and dependency coverage

`pytest.ini` declares `jevops`, `tests`, and `papers/completion/lean_refactor_arena`
as `test_seal_roots` (one path per line). The Arena tree covers the harness,
vendored source, manifests, and benchmark data used by otherwise ordinary tests.
Each seal includes these complete trees, plus the specific test and its
statically known fixture source files, pytest/project configuration and common
lockfiles, plugin package source trees, Python executable/version/flags/platform,
installed distribution versions/editable metadata, typed parameter values,
effective test-affecting options, import search path, working directory, and the
process environment. Environment values are stored **only as an aggregate hash**,
not as plaintext. Only pytest's per-test `PYTEST_CURRENT_TEST` is excluded.
This intentionally includes shell variables such as `SHLVL`: launching through
a different shell or pipeline can make a seal stale even when files are unchanged.

This deliberately uses conservative source-tree closure, **not** a claim to infer
every Python dependency from imports. Dynamic imports, reflection, native calls,
and file I/O cannot be completely inferred from a Python AST. A change anywhere
in these roots currently invalidates every seal. Narrowing roots can improve
granularity, but makes the explicit dependency contract more demanding. Outside
this repository the default root is the entire pytest project (`.`).

Each regular file has a SHA-256 content hash and, for parseable Python files up to
4 MiB, a canonical AST hash without source locations. File/directory identities,
permissions, symlink identities/targets, and missing inputs feed deterministic
Merkle-style roots (hashes of child hashes), then each test's final seal.
AST hashes and recorded import names are diagnostics only. Comment, whitespace,
and line-number changes can affect introspection and tools: an unchanged AST
**never** authorizes reuse when raw bytes differ.

The fast path reuses a file digest only when `(device, inode, mode, size, mtime_ns,
ctime_ns)` matches. It catches same-size edits with restored mtime on ordinary
local filesystems. `--test-seal-strict` disables this optimization, including for
tools. File bytes are checked against stat changes during reading. Directory
membership is never cached using directory mtime alone. Generated caches are
excluded from directory scans: `.git`, `.pytest_cache`, `__pycache__`, `.venv`,
`.mypy_cache`, `.ruff_cache`, `.hypothesis`, and `.pyc`/`.pyo` entries. Explicitly
declare excluded files if their contents are actual test inputs.

## Lifecycle, reporting, and persistence

A cached hit is a setup skip with terminal category **SEALED**, letter `C`, and
JUnit properties `test_seal=reused` / `test_seal_root=...`. Pytest still performs
its normal teardown protocol, including pending shared fixture cleanup. JUnit
shows a skip rather than claiming a new pass. An all-sealed reuse invocation exits
zero, but its summary is distinct from a fresh successful test run.

Only full setup/call/teardown passes in a successful session are promoted. Input
changes during execution suppress promotion. Failures, skips, xfails/xpasses,
unknown parameter types, non-Python collectors, generative Hypothesis tests,
and benchmark-fixture tests are not sealed. Existing evidence is revoked before
a fresh attempt, including refresh, so an interrupted attempt cannot preserve an
old pass. A failing session invalidates selected records conservatively, including
previous hits, and records fresh failures where inputs are stable.

The local `.pytest_cache/d/test-seals/manifest.json` uses checksummed JSON and
atomic replacement. A nonblocking POSIX lock prevents simultaneous writers;
unsupported locking, contention, cache I/O errors, coverage, distributed workers,
and rerun/setup-only modes fall back to normal execution. Corrupt/incompatible
manifests are cold misses. **Checksums are not signatures:** a writable cache is
not tamper-proof. Do not share it across trust boundaries or use it as a proof
certificate, benchmark score, or training reward. `pytest --cache-clear` discards
the ordinary pytest cache, including seals.

The plugin is loaded by the repository's root `conftest.py`, with `on` enabled
by default. Elsewhere it can be loaded explicitly with `-p jevops.pytest_seals`;
that also defaults to `on`. Explicit CLI `--test-seal=off` or `refresh` overrides
the repository's `addopts`. Use `--test-seal=off` for an uncached run.
It is tested with Python 3.12 and pytest 9.1.1 on Linux (modern pytest/pluggy
wrapper hooks are required). Cache validation has overhead: it is intended for
expensive deterministic tests, not to accelerate tiny unit-test bodies.
The independent `jevops.seals` module also exposes `Fingerprinter`, `SealStore`,
and `seal_status` for non-pytest callers that provide their own input contract.

Implementation references: [pytest hook/report API](https://docs.pytest.org/en/stable/reference/reference.html),
[pytest fixture dependency model](https://docs.pytest.org/en/stable/explanation/fixtures.html),
and [Python AST parsing/dumping](https://docs.python.org/3/library/ast.html).

The [2026-09-25 current-checkout audit](papers/completion/lean_refactor_arena/evidence/goal-plan-audit-2026-09-25/README.md)
records default cold/warm execution, native freshness exclusions, fresh seal
self-tests and safety regression, with exact commands and JUnit artifacts.
It also reports the hashing overhead; historical hits are not new passes.
