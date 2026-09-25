# Coarse Strata tactic profile — 2026-09-25

## Separate run after bounded extraction failure

The [first profiling run](../tactic-profile-strata-2026-09-25/README.md) stopped
after four verified controls and one profile exceeding the 256-event cap.
No partial profile was usable. This is a **new frozen diagnostic run**, with
new controls and a fresh ten-process reservation, not completion of that run.

Only resolution changes: the profiler threshold is **10,000 raw heartbeats**
instead of 100. The **256-event**, **20,000-traversal-node** and depth-256 caps
remain unchanged. Lower-cost recorded nodes may now be absent; their work is
included in parent/residual costs. No candidate generation, score comparison,
training or proof promotion occurs.

The task, sole Lean 4.26.0/Strata commit, original 222-token source and actual
169-token incumbent are unchanged. See the [diagnostic design](../../../../../ARENA_TACTIC_PROFILE.md)
for trust boundaries and counter interpretation. In particular, instrumented
costs are not ordinary Arena heartbeats or a prediction of refactoring gains.

## Frozen schedule and execution

Four uninstrumented whole-proof controls (two repeats in both branch orders),
followed by six instrumented profiles (three original and three incumbent),
exactly as in the first run. Any failed sample stops the new run; there are no
within-run retries, adaptive thresholds or additional candidates.

Plan-only command:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_profile \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json \
  --threshold-raw 10000
```

It emitted ten processes, no score/search eligibility, and plan SHA-256
`822facc1067f09092fc3c4fa98ab53f6cd9fe04e368699550807b08122bb8b79`.

Runtime: `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/tactic-profile-coarse-ytfsx_k4`.
Snapshot: **2,050 files, 53,731,502 bytes**; manifest SHA-256
`a8ff3285b609626eb437a63f7578d2dfc478a1d733869b93dba38d5947c557c4`;
content root `f3a515f2e8f9504cdde1218ae86f545aa6a2cd3a367dac3eb7fa3618af1ea695`.
Storage free before capture: **525,647,872 bytes**, preserving the existing
50 GB cap, serial preparation lock, and 100 MB runtime reserve. No caches are
removed, no dependencies are built/downloaded, and no model/API is invoked.

Actual command, cwd in the snapshot's `source`. The wrapper forwarded only
PATH/HOME/LANG/LC_ALL and set `PYTHONDONTWRITEBYTECODE=1`,
`JEVOPS_REGISTER_LRA_HOOKS=0`, `JEVOPS_USE_EXTERNAL_DEPS=0`,
`JEVOPS_USE_EXTERNAL_ROUTER=0`, with TMPDIR at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys; sys.path.insert(0,sys.argv.pop(1)); from jevops.arena_profile import main; raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/tactic-profile-coarse-ytfsx_k4/source \
  --problem CallElimCorrect.extractedOldExprInVars --incumbent inputs/incumbent.json \
  --threshold-raw 10000 --execute --max-processes 10 \
  --snapshot-manifest-sha256 a8ff3285b609626eb437a63f7578d2dfc478a1d733869b93dba38d5947c557c4 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/tactic-profile-coarse-ytfsx_k4/profiles
```

This local single-process diagnostic is not an OS sandbox, held-out/corpus-wide
evaluation or official Arena scoring. Hashes bind bytes, not independent proof
authority. New runs must not overwrite this snapshot or its evidence.

## Result: shared simplification is the remaining hotspot

The run completed **PROFILED**, with **four verified controls and six complete
profiles**, using all ten processes. Pilot wall time was **225.44 seconds**;
the launcher measured **232.62 seconds** including source/resource checks.
Source binding stayed **UNCHANGED** before and after work. The controls kept
the original axiom set, exactly `propext` and `Quot.sound`.

| Measurement | Original, 222 tokens | Incumbent, 169 tokens |
| --- | ---: | ---: |
| Uninstrumented command, four controls | 2,607,574–2,607,585 | 1,283,749–1,283,762 |
| Instrumented command, three profiles | 2,877,327–2,877,329 | 1,389,929 each |
| Recorded tactic events per profile | 140 | 70 |
| Traversal nodes per profile | 334 | 172 |
| Shared-prefix exclusive recorded cost | 783,808 each | 783,808 each |
| Shared-prefix share of instrumented command | 27.24% | **56.39%** |

The prefix total groups the **nine recorded** `Lean.Parser.Tactic.simp` events
with this exact, untruncated display hint, summing exclusive recorded costs:

```lean
simp [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at *
```

The same prefix total appears in all six profiles. In the incumbent, recorded
case-node **inclusive** costs were also stable across all three repeats:
`app` **188,866**, `quant` **49,140**, `ite` **68,598** and `eq` **44,958**.
The `ite` case therefore represents about **4.94%** of the instrumented command,
far less than the shared prefix. These case nodes identify regions by display
hint; they are not automatic edit anchors. Never add these inclusive values
to their own descendant costs.

Instrumented root coverage was **1,175,166** for the incumbent, with **214,763**
unattributed raw heartbeats. The exclusive-cost sum equals root coverage in
every profile; no nested intervals were counted twice. Threshold omissions,
non-tactic work and instrumentation remain in residuals, so this is not full
fine-grained attribution.

The instrumented incumbent command is about **8.27% higher** than the fresh
uninstrumented control mean; the original's method gap is about **10.34%**.
This comparison includes profiling-path/method differences and must not be
treated as a calibrated overhead subtraction. In particular, **56.39% is not
a forecast optimization saving**, and profiling supplies no new Arena score.

### Next bounded hypothesis

Prioritize specializing the initial shared `simp [...] at *` invocation, then
minimizing its required support, instead of continuing to rewrite the small
`ite` append tree. Use the existing native parser's solver spans for exact
source binding; the profiling hints alone cannot authorize an edit. All
induction cases, including work below this threshold, must still close.
This follow-up has not been run here. It needs a new fixed candidate set,
fresh uninstrumented controls and independent confirmation under the selected
cost objective. The **169-token incumbent is unchanged**.

### Archived evidence and consistency

[Report](report.json), [derived analysis](analysis.json), [plan](plan.json),
[source binding](source-binding.json), [launch](launch.json),
[source manifest](source-manifest.json), [regression JUnit](regression.xml).
All ten individual samples (`sample-00.json` through `sample-09.json`) are also
retained. The analysis revalidates every interval forest with the implemented
validator, checks profile source/environment binding, control outcomes/axioms,
sample counts, plan equality and before/after source identity. It reports
**CONSISTENT**, with zero fresh native calls and no independent proof
attestation. Exact raw numbers remain in JSON; reported percentages are rounded.

Across this implementation pass there were **23 native process attempts**:
eight development invocations (including two fixed driver-compilation failures),
five in the incomplete fine-resolution pilot, and ten in this complete pilot.
Failed evidence and unused reservations remain distinct; no model/API call,
training, candidate selection, production promotion or dependency build occurred.

## Final regression suite

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-profile-coarse-tests-61S5IMw2/cache \
  --junitxml=/tmp/jevops-profile-coarse-tests-61S5IMw2/regression.xml \
  tests/test_arena_profile.py tests/test_arena_local.py tests/test_arena_providers.py \
  tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py tests/test_arena_aggregate.py -q
```

Observed: **315 passed, 8 skipped**, zero reused, **265 fresh passes sealed**,
23.71 seconds. There are now **54 passing offline cases** in the profiler test
file; the additional case freezes explicit threshold changes and rejects
invalid thresholds. Existing plan-mutation tests still reject an in-place
change after freezing.

The unchanged native profiler/capture code had already passed the **three
opt-in native tests** documented in the first archive. Those are not rerun or
counted as new passes here. The first two development smoke failures remain
archived. This is targeted coverage, not a full-repository result.

## Implementation scope

This pass changes `jevops/arena_local.py`, `jevops/lean/ArenaLocal.lean`, adds
the small `jevops/arena_profile.py` CLI and `tests/test_arena_profile.py`, and
updates the README/design/safety notes. It reuses the existing native guards,
prefix elaboration, storage/ownership mechanisms and proof admission boundary.
No default scoring criterion, candidate source or accepted proof changes.

Deferred: exact source-span mapping for trace hints, automatic edit nomination,
multi-pin pilot scheduling, cross-version profiler evaluation and independent
adversarial measurement integrity. Any optimization trial needs fresh,
uninstrumented proof and cost checks under a separately frozen selection plan.
