# Planning, seal and upstream-reuse audit — 2026-09-25

This closes the **planning/seal/reuse deliverable**, not the optimizer's
remaining implementation roadmap. No new native Lean check, model call,
download, dependency build, benchmark improvement or promotion occurred.
The [updated plan](../../../../../LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md#current-decision-brief--2026-09-25)
states the strict objective, research priorities, verifier/resource gates,
reuse decisions, experiment design and unimplemented release requirements.

## Requirement-by-requirement evidence

| Requested requirement | Current authoritative evidence | Conclusion and remaining work |
| --- | --- | --- |
| Comprehensive token-and-heartbeat plan | Plan sections 1, 4, 5, 7, 8 and current decision brief; current `arena_solver`, `solver_feedback`, `arena_pareto`, `arena_providers` inspected | Prioritized passes, module destinations, baselines, caps and stop rules specified; bounded search does not guarantee an improvement for every proof |
| Both costs improve while the original task still passes | `strict-dual-v1` implementation and fresh selector tests; exact statement/type/closedness and axiom checks inspected in `arena`/`ArenaCheck.lean` | Strict versus aggregate objectives separated. Latest 190-token Strata result is not a strict win over 185-token incumbent. No new native validity/performance claim |
| Resist reward hacking | Plan sections 5–6 and tickets 1a–1e; fresh adversarial fixture tests for receipts, costs, stale contexts, exports, budgets and axiom policy | Existing checks tested; source execution/metric authenticity, full environment-delta audit and complete production gate remain open. No universal “unhackable” claim |
| Pytest actually uses seals | Current `pytest.ini`, root `conftest.py`, plugin/self-tests; cold/warm runs below and JUnit reused properties | Default seals work, native obligations remain fresh; reused evidence is not a new passing execution or proof |
| Review upstream logic/hammer/tactician reuse | Local upstream revision, reviewed code and exact hashes in [upstream-review.json](upstream-review.json); six read-only probes | Adapt small explicit contracts, not whole package/CEC stack, normalized raw-source cache keys, retargeted proposals or trust flags |

This is a source-based planning audit plus targeted offline tests. It is not a
full repository test run, an upstream test-suite result, a live solver comparison,
proof of all adversarial defenses, or completion of all proposed roadmap phases.

Final bookkeeping checks passed: archived JUnit/manifest hashes match their
recorded identities, the reviewed upstream files are unchanged, and all 13
new local document links resolve. Reanalysis of the historical Strata report
remains `CONSISTENT` and selects nothing under `strict-dual-v1` in either phase.
These checks add no native verification event. `git diff --check` passed.

## Tests actually run

| Run | Fresh passes | Reused | Skipped | Fresh passes sealed | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Seal self-tests, `refresh` | 42 | 0 | 0 | 0 | 38.89 |
| Five-module default cold run, no seal-mode flag | 303 | 0 | 32 | 291 | 21.26 |
| Same default warm run | 12 | 291 | 32 | 0 | 19.18 |
| Additional safety/provider suite, `refresh` | 480 | 0 | 136 | 470 | 30.73 |

No failures/errors. [Self-test JUnit](seal-selftests.xml), [cold](cold.xml),
[warm](warm.xml), [safety](safety.xml), [machine-readable summary](results.json).
Warm JUnit contains 291 `test_seal=reused` properties and corresponding skips;
those are not 291 new passes. Seal self-tests opt out so their cache/locking
checks execute fresh. The other non-sealed passes have unsupported/explicitly
fresh inputs; skips remain non-success coverage, not inferred native passes.

A status-only selection of native solver/replay cases returned the expected
nonzero exit **1**: all **29 native cases were unsealed** (four explicit
`no_seal`, 25 transitive `live_profile` consumers). It also selected three
ordinary fixtures with “native” in their names, which correctly remained sealed.
[Status transcript](native-seal-status.txt). Status collects tests but does not
execute their fixtures/bodies. Native integration opt-ins were disabled.

This selection's warm time is only modestly lower than cold: conservative
whole-tree checks still cost 600,230 stat hits. It is not evidence that seals
speed every workload up. Runtime flags, environment and paths affect reuse.

## Frozen inputs and commands

Runtime root: `/tmp/jevops-goal-audit-20260925-kGQKio`.
The [manifest](source-manifest.json) captures 1,965 files / 50,043,051 bytes,
SHA-256 `09afb94b121dab7185f28612f18dbb42c468cfec1e19c957387cdd0c8418351d`.
Snapshot verification returned `UNCHANGED` after execution; 358 captured
implementation/test/configuration files matched the current checkout byte for
byte afterward. Snapshot copies omit empty directories (the workspace has an
empty `jevops/.benchmarks`); this is not a claim that the entire dirty checkout
equals Git HEAD or the frozen tree. No user changes were reset or discarded.
Hashes identify content, not proof truth or protected attestations.

Exact self-test command (workspace, before documentation/artifact edits):

```bash
env -u PYTEST_ADDOPTS PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -B -m pytest -q --tb=short --test-seal=refresh \
  -o cache_dir=/tmp/jevops-goal-audit-20260925-kGQKio/selftest-cache \
  --basetemp=/tmp/jevops-goal-audit-20260925-kGQKio/selftest-tmp \
  --junitxml=/tmp/jevops-goal-audit-20260925-kGQKio/seal-selftests.xml tests/test_seals.py
```

The snapshot was created with `python -B -m jevops.arena_snapshot create`,
`--repo /home/barberb/lift_coding/JevOps`, `--output-dir` set to the runtime
root's `source`, and `--include` for `jevops`, `tests`,
`papers/completion/lean_refactor_arena`, `conftest.py`, `pytest.ini`,
`pyproject.toml`. External hooks/router were disabled. To reproduce, use a new
runtime directory from `mktemp -d`; pytest may clean its explicit basetemp,
so never point it at unrelated data. New source captures have new identities.

Exact default cold/warm and status runner (no seal override for cold/warm):

```python
import os, subprocess, sys
from pathlib import Path
root = Path('/tmp/jevops-goal-audit-20260925-kGQKio')
source = root / 'source'
env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG') if k in os.environ}
env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1',
    JEVOPS_REGISTER_LRA_HOOKS='0', JEVOPS_USE_EXTERNAL_DEPS='0',
    JEVOPS_USE_EXTERNAL_ROUTER='0', JEVOPS_ARENA_NATIVE_TESTS='0')
base = [sys.executable, '-I', '-B', '-c',
    'import sys; sys.path.insert(0, sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))',
    str(source), '-q', '--tb=short', '-o', f'cache_dir={root}/default-cache',
    f'--basetemp={root}/default-tmp']
tests = ['tests/test_arena_solver_reference.py', 'tests/test_arena_pareto.py',
    'tests/test_arena_providers.py', 'tests/test_arena_replay.py',
    'tests/test_arena_solver_native.py']
for phase in ('cold', 'warm'):
    subprocess.run([*base, f'--junitxml={root}/{phase}.xml', *tests],
                   cwd=source, env=env, check=True)
status = subprocess.run([*base, '--test-seal=status',
    'tests/test_arena_solver_native.py', 'tests/test_arena_replay.py',
    '-k', 'live or native'], cwd=source, env=env)
assert status.returncode == 1
```

Additional fresh suite, executed with cwd at the frozen `source`:

```bash
env -u PYTEST_ADDOPTS PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
  python -I -B -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' \
  /tmp/jevops-goal-audit-20260925-kGQKio/source -q --tb=short --test-seal=refresh \
  -o cache_dir=/tmp/jevops-goal-audit-20260925-kGQKio/safety-cache \
  --basetemp=/tmp/jevops-goal-audit-20260925-kGQKio/safety-tmp \
  --junitxml=/tmp/jevops-goal-audit-20260925-kGQKio/safety.xml \
  tests/test_arena.py tests/test_arena_trial.py tests/test_arena_lean.py \
  tests/test_arena_source.py tests/test_arena_module_audit.py \
  tests/test_arena_premises.py tests/test_premise_search.py tests/test_solver_spans.py \
  tests/test_arena_aggregate.py tests/test_arena_report_audit.py tests/test_arena_isolation.py
```

## Upstream review and reuse decisions

Read-only checkout: `/home/barberb/ipfs_datasets_py`, revision
`7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`. `git status --short` was empty
for the reviewed hammer/tactician/candidate-synthesis/translation paths.
Root license identifies AGPL-3.0; preserve license/revision provenance for
any future code copy. This audit copied no implementation and added no runtime
dependency. `.gitmodules` identifies separate CEC components; hammer/tactician
are ordinary Python modules, not independent Git submodules.

| Upstream paths under `ipfs_datasets_py/logic/` | Reuse decision |
| --- | --- |
| `hammers/premise_selection.py`, `tactician/planner.py` | Existing bounded retrieval/exclusion design is useful; retain case-sensitive names, target-free scope and exact policy digests, not human-readable IDs as verification identity |
| `hammers/learned_selector.py` | Reuse model-digest/fallback accounting after baseline evaluation; default weights are explicitly hand-authored, not trained performance evidence |
| `hammers/proof_cache.py` | Adapt in-process single-flight discovery only with exact raw-source keys, strict serialization, deadlines/cancellation, entry/byte bounds and no confirmation/reward replay |
| `hammers/portfolio.py`, `software_verification/tactician/candidate_synthesis.py` | Use typed per-hole proposals and budgets via injected JevOps ledgers; zero must stop work before callbacks, wrong-hole outputs must be rejected, and callback work must be deadline-bounded |
| `hammers/reconstruction.py`, `hammers/receipts.py` | Treat solver output as hints; materialize alternatives separately, check whole Lean proofs, and distinguish serialized claims from authoritative verifier receipts |
| `translations/planner.py` | Future definition-equivalence contracts can expose assumptions/losses; unknown feature coverage must fail closed, never stand in for a Lean equivalence proof |

Fresh read-only probes compiled **only** `_json_ready`, `canonical_json`,
`content_digest` and `canonicalize_obligation` definitions extracted by Python
AST from the reviewed cache file, with standard-library globals. They did not
import the upstream package or instantiate its cache/providers. All six asserted
checks passed: raw-source normalization merges distinct string-literal inputs;
JevOps exact source hashes differ; upstream serialization conflates integer and
string mapping keys and opaque objects with their strings; JevOps strict
serialization rejects both unsupported inputs. These are normalization/identity
collisions, **not SHA-256 collisions or a claim that every upstream caller is
incorrect**. Actual Lean validity of those example strings was not evaluated.
The key builder explicitly composes this normalizer into `obligation_digest`.

Static inspection also confirmed an unbounded single-flight event wait,
zero-to-default candidate caps, gathering provider results before truncation,
wrong-hole retargeting, and an ambient scheduler fallback. Upstream's
reconstructor uses premise hints plus native fallback tactics, not general ATP
proof-trace translation. These findings constrain adaptation; they are not a
license to import those semantics as proof authority.

## Remaining implementation gates

Source/executed-export correspondence for general tactics, candidate-independent
cost integrity, complete environment-delta/cost-displacement checks, full
prepared-corpus isolated coverage, whole-run deadlines/crash recovery, and
family-heldout dual-cost gains remain open. The plan prioritizes and supplies
acceptance tests for them; this audit does not assert their completion.
Production promotion stays disabled. Native security/measurement canaries must
run fresh in their explicitly supported isolation contexts when those gates are
implemented. The previous 30-check Strata result remains historical evidence,
not a fresh verification event in this audit.
