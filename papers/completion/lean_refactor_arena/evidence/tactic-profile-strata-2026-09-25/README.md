# Strata tactic profiling — 2026-09-25

## Why this run

The [direct-term experiment](../subset-term-strata-2026-09-25/README.md) found
valid but more expensive replacements for the same append subtree. This pass
adds measured diagnostics before choosing another refactor. It does **not**
change the proof, search for candidates, promote an improvement or compute a
new score. The incumbent stays the previously confirmed **169-token** source.

## Result: event cap reached, no usable profile

The run returned **INCOMPLETE** after **five native processes**, in 117.54
seconds including source/resource checks. All four uninstrumented controls
verified. The first instrumented original-source profile exceeded the **256
event** extraction limit and returned an explicit error. No partial profile
was admitted, no remaining sample was attempted, and no cost hotspot or score
gain can be inferred from this run. Its source binding stayed **UNCHANGED**.

The ten-process reservation was not expanded or reused. A separate coarse
profiling plan with a 10,000-raw-heartbeat threshold is the follow-up, keeping
the same event cap and requiring new controls. It is a new diagnostic run,
not completion of this failed run or a refactoring recommendation.

Artifacts: [report](report.json), [plan](plan.json), [source binding](source-binding.json),
[launch](launch.json), [manifest](source-manifest.json),
[offline tests](regression.xml), [native smoke](smoke.xml),
[native regressions](native.xml), and retained [first](smoke-failure-1.xml) /
[second](smoke-failure-2.xml) development failures. Native samples `sample-00`
through `sample-04` are retained beside the report.

Task: `CallElimCorrect.extractedOldExprInVars`, Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`, sole declared pin `v4.26.0`.
The original is 222 tokens. Historical sources are inputs only; no receipt is
reused as fresh verification or measurement.

## Implemented diagnostic and protocol

The [diagnostic design note](../../../../../ARENA_TACTIC_PROFILE.md) describes
the new `ArenaLocalRuntime.profile()` operation. It uses the existing guarded
prefix/runtime, installed Lean trace profiler, and unchanged source. No parallel
agent framework or new proof authority is introduced.

The fixed **ten-process** pilot is:

1. Four fresh uninstrumented whole-proof controls: incumbent vs original,
   both branch orders, two repetitions. Type/target and no-axiom-growth gates
   must pass before profiling starts.
2. Six instrumented native profiles: original/incumbent, incumbent/original,
   original/incumbent, each a fresh process. Threshold **100 raw heartbeats**,
   traversal budget **20,000**, maximum **256** exported tactic events.

The exact schedule, budgets, source hashes and implementation identity are
frozen before work. No retries, budget reuse or adaptive changes occur. One
non-success stops the experiment and retains partial evidence. Both original
and incumbent retain all their existing tactics; no definitions or imports are
added to their proof environment. Profiling options are explicitly different
from ordinary scoring options.

Counts are **instrumented raw heartbeat intervals**, not official Arena costs.
The projection covers builtin tactic trace nodes, not every operation. Parent
and child intervals must not be added together. Exclusive costs exclude only
recorded tactic children; non-tactic work, threshold omissions and profiler
overhead remain in residuals. Hints are bounded pretty-printed text, not exact
source offsets or replay anchors. No observed percentage is automatically a
prediction of an uninstrumented optimization saving.

The source copy prevents accidental checkout edits affecting the run. This
remains trusted-local execution, not an OS sandbox or independent authenticated
metric. Prefix/dependency preparation is outside the per-theorem counters.

## Commands and source binding

Plan-only command, zero native/model calls:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_profile \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json
```

It returned ten processes, no search/score eligibility and plan SHA-256
`7b4bd42dadbfb3478c7dc42de288fd24ce537f7275f889d918f8e4cd80620533`.

Runtime root: `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/tactic-profile-strata-gc0_l1c3`.
Snapshot: **2,034 files, 53,268,088 bytes**; manifest SHA-256
`99e0a02797047f22a3dcdffd35b0663e780a290341b284adb57d5709606ae7c4`.
Content root: `8b3d6294a5ee3b316b10515f244beed85d82bcf93c348d074b0468ddf8b8aa2c`.
Hashes identify content, not proof authority. Capture included the package,
tests, Arena corpus/evidence, pytest/project config, diagnostic design note and
explicit incumbent/project inputs. Later reporting docs are outside that snapshot.

Before capture the capped volume had **585,179,136 bytes free**. The existing
50 GB cap, single preparation `flock`, and runtime 100 MB reserve are retained.
There are no model calls, downloads, dependency builds, cache deletions or
production changes.

Actual command, cwd at the snapshot's `source`. The launch wrapper forwards
only PATH/HOME/LANG/LC_ALL and sets `PYTHONDONTWRITEBYTECODE=1`,
`JEVOPS_REGISTER_LRA_HOOKS=0`, `JEVOPS_USE_EXTERNAL_DEPS=0`,
`JEVOPS_USE_EXTERNAL_ROUTER=0`, and TMPDIR to
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys; sys.path.insert(0,sys.argv.pop(1)); from jevops.arena_profile import main; raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/tactic-profile-strata-gc0_l1c3/source \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent inputs/incumbent.json --execute --max-processes 10 \
  --snapshot-manifest-sha256 99e0a02797047f22a3dcdffd35b0663e780a290341b284adb57d5709606ae7c4 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/tactic-profile-strata-gc0_l1c3/profiles
```

A rerun requires a new snapshot/output directory and new process reservation.

## Tests actually run

Final targeted offline suite:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-profile-regression-C8dyDzMo/cache \
  --junitxml=/tmp/jevops-profile-regression-C8dyDzMo/regression.xml \
  tests/test_arena_profile.py tests/test_arena_local.py tests/test_arena_providers.py \
  tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py tests/test_arena_aggregate.py -q
```

Observed **314 passed, 8 skipped**, zero reused, **264 fresh passes sealed**,
23.82 seconds. The new test file contributes **53 offline passing cases**.
Coverage includes interval conservation, overlap/parent/preorder rejection,
malformed counters/flags/contexts, process budgets, explicit fixture labeling,
frozen schedules, failure stop rules and unchanged selection behavior.

Native development checks used the installed pin under the same preparation
lock. The initial smoke invocation failed compiling the new reporting code;
a second invocation exposed the full diagnostics. Explicit `MessageData` types,
`decide` for a JSON boolean, Lean 4.26 string handling and parentheses around an
option expression fixed those errors. Both failures are retained, not counted
as passes or candidate rejections.

Successful smoke command:

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_ARENA_DOCKER_TESTS=0 \
ELAN_HOME=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-profile-smoke-wQ3HHIKi/cache \
  --junitxml=/tmp/jevops-profile-smoke-wQ3HHIKi/smoke.xml \
  tests/test_arena_profile.py::test_native_profile_is_instrumented_not_a_verification_receipt -q
```

Observed **1 passed**, 15.26 seconds, no reused/sealed result, one native
process. The two preceding smoke invocations used the same command with
separate output paths; their failures occurred before diagnostic completion.

The same environment/lock also ran:

```bash
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-profile-native-hPXDLXW2/cache \
  --junitxml=/tmp/jevops-profile-native-hPXDLXW2/native.xml \
  'tests/test_arena_local.py::test_native_project_prefix_target_offsets_replay_and_whole_proof[pin0]' \
  'tests/test_arena_local.py::test_native_branch_headers_are_observable_but_not_editable[pin0]' -q
```

Observed **2 passed**, 63.43 seconds, zero reused/sealed, **five native
processes** (capture/replay/two whole-proof checks, then branch-header capture).
Development total: **eight native attempts**, including the two failed driver
compilations; distinct from the ten-process Strata pilot. The offline suite's
skipped native cases are not counted as offline passes. No full-repository
test result is claimed.

## Files changed and remaining limits

- `jevops/lean/ArenaLocal.lean`: opt-in built-in profiler and bounded tactic
  trace extraction, reusing existing prefix/branch elaboration.
- `jevops/arena_local.py`: profile method, explicit identity binding, interval
  validation and non-double-counting summaries; existing guard/budget reused.
- `jevops/arena_profile.py`: frozen diagnostic CLI with separate uninstrumented
  controls, bounded scheduling, snapshot/storage checks and incremental evidence.
- `tests/test_arena_profile.py`: offline hostile-input/planning coverage and
  explicitly opt-in installed-Lean test.
- `ARENA_TACTIC_PROFILE.md`, root README, safety plan and this archive:
  execution commands, trust boundary, results and deferred work.

Exact source-span attribution, automatic candidate nomination, multi-pin pilot
scheduling and adversarial measurement integrity are not implemented here.
Any follow-up edit needs a separate frozen, uninstrumented verification and
cost-selection experiment. A profile is never a score or an accepted fact.
