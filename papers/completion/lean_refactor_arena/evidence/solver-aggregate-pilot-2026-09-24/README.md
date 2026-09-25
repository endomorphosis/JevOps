# Aggregate-aware Physlib comparison

This is a separately frozen local experiment on an **exposed public-warmup
task**, not a held-out evaluation, submission, production promotion, or claim
to beat the Arena. It compares three already saved complete proofs; it does
not search for new candidates or treat historical receipts as authority.

Task: `Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema`,
Physlib commit `c48433678e8fb6306ebcd48453300c8e16058a62`, Lean `v4.32.0` (the
only declared pin for this task).

## Observed result

**`CONFIRMED_LOCAL_IMPROVEMENT`**: the previously saved longer specialization
won and passed fresh confirmation. All **24 whole-proof native checks** were
`VERIFIED`. The [report](report.json) retains the full bound receipts;
[protocol.json](protocol.json) is the pre-execution design. No source was
promoted, no production memory was updated, and no submission was made.

| Arm | Tokens | Reference-first raw HB | Candidate-first raw HB | Local score gain, reference-first |
| --- | ---: | ---: | ---: | ---: |
| Original | 1372 | 27475681 | 27479265 | 0 |
| Shorter deletion | 1365 | 27554621 | 27558205 | +0.074298 pp |
| Longer specialization | 1377 | 25104564 | 25108148 | +2.755148 pp |

Every screening repetition was identical within its arm/order stratum. The
winner and original reproduced those counts exactly in all three fresh
confirmation repetitions per order. The winner is **five tokens longer
(0.3644%) and 8.6287–8.6299% lower-heartbeat**. Its nominal combined-score
gain is 2.754773–2.755148 percentage points across orders; even after the
predeclared 100-raw-unit margin, its worst-order descriptive gain is
**+2.754651 pp**. These are unrounded, matched-local deltas against the freshly
measured original, **not official Arena scores or a full-corpus result**.

Both proofs retain the same type and observed transitive axioms:
`Classical.choice`, `Quot.sound`, `propext`. The transformation remains:

```diff
-      simp [Time.deriv_eq]
+      simp only [_root_.smul_apply, smul_eq_mul, Time.deriv_eq]
```

The [four-field recommendation](recommended-draft.json) contains the same
saved source, now backed by this local confirmation; future contexts still
require fresh verification. It is not a newly discovered transformation.

[Score analysis](score-analysis.json) also recomputes all three objectives on
the **same recorded screen**, without additional native execution. Both
`pareto-v1` and `strict-dual-v1` select nothing: the deletion is slower and the
specialization is longer. `aggregate-local-v1` considers both positive
normalized-sum trade-offs eligible and selects the specialization. The shorter
draft's small nominal aggregate gain was **not independently confirmed**,
because the protocol confirms only the fixed winner.

Runtime was **1090.60 seconds** (about 18.2 minutes). The source snapshot was
unchanged before/after; the [binding](source-binding.json) records the full
argv and 50 GB resource cap. Observed free storage was 1.831 GB before and
1.632 GB afterward. No model/API calls, downloads or builds were performed by
this run. The process exited and released its preparation lock; no continuing
optimizer/service was started.

The [audit](audit/summary.md) is `CONSISTENT`, with `proof_verified: false` and
zero fresh native processes: it checks recorded bookkeeping, not receipt
authenticity or a new proof. Worker metric parity and stronger process isolation
remain unresolved; identical heartbeat repetitions are not a statistical
generalization claim.

All 11 copied machine-generated evidence files were compared byte-for-byte
with their runtime originals. The working selector/solver files still matched
the frozen copy, and `git diff --check` passed. The historical audit is
reproducible offline with:

```bash
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/solver-aggregate-pilot-2026-09-24/protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/solver-aggregate-pilot-2026-09-24/report.json \
  --output-dir /prepared/new-audit
```

## Frozen design

- Original proof, 1372 reference-compatible proof-source tokens.
- Saved deletion draft, 1365 tokens, from the
  [balanced pilot](../solver-balanced-pilot-2026-09-24/solver-0.json).
- Saved compiler specialization, 1377 tokens, from that pilot's
  [longer intermediate](../solver-balanced-pilot-2026-09-24/followup-longer-intermediate.json).
- `aggregate-local-v1`, 100 raw-unit noise floor, seed 17.
- Screening: three arms × two branch orders × two repetitions = 12 processes.
- Fresh confirmation: selected winner and original × two orders × three
  repetitions = 12 processes, seed 18. No second-place fallback, retries,
  post-result edits or adaptive repetition.
- All 24 requests reserved before work; no cache hits count as verification.
  Exact target/type and no-axiom-growth requirements are unchanged.
- Existing prepared environment only: no models, downloads or dependency
  builds. One process at a time under the preparation lock, within the
  existing validated 50 GB volume. This is not an OS sandbox.

The aggregate criterion intentionally differs from the earlier strict-dual
experiment: a longer/faster proof may now win. Old strict-dual results are not
relabeled. The new selector and solver nomination are opt-in, with legacy
defaults unchanged. See the [precise formula and range margin](../../../../../ARENA_PARETO_SELECTION.md#aggregate-local-score-opt-in).

## Reproduction

Runtime parent:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/solver-aggregate-20260924-8GM0mS`.
The successful copy is `source-complete`. Its manifest SHA-256 is
`36266b3347b0956f276e6aa04cf3bdb68c7840eb872d14f541b07bb5920d6a51`,
with 1524 files / 45637444 bytes. The
[manifest](source-manifest.json) identifies content, not proof authority or
the complete external Python/Lean installation.

Run from a separately validated frozen source root, using its copied project
mapping and the exact existing prepared Lean installation. The selector CLI
itself does not acquire the preparation lock. The actual launch used
`python -I -B`, explicitly prepended only this copy to the JevOps import path,
held `arena_prepare.exclusive(preparation / "single-build.lock")`, validated
the mounted 50 GB volume and TMPDIR/output containment, and required at least
100 MB free before launching. `verify_snapshot` ran before and after, with the
externally retained manifest digest. The source-binding artifact records the
complete argv, source checks, resource observations and wall time.

```bash
python -m jevops.arena_pareto --run \
  --problem Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --candidate papers/completion/lean_refactor_arena/evidence/solver-balanced-pilot-2026-09-24/solver-0.json \
  --candidate papers/completion/lean_refactor_arena/evidence/solver-balanced-pilot-2026-09-24/followup-longer-intermediate.json \
  --selection-objective aggregate-local-v1 --heartbeat-noise-floor-raw 100 \
  --repetitions 2 --confirmation-repetitions 3 --seed 17 \
  --max-calls 24 --timeout 90 --progress --output-dir /prepared/new-selection
```

This command needs the wrapping lock/source/resource checks above; it is not a
permission to substitute pins or download/build missing dependencies. Core
tests require no Lean installation or credentials.

## Offline regression and preparation

The [frozen regression](regression.xml) records **580 passed, 5 skipped,
89 deselected**, in 12.60 seconds. This is the targeted suite below, not the
entire repository suite. Fixture heartbeat costs are synthetic, not native
measurements. All native tests remained opt-in and disabled here.

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -B -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  --basetemp=/prepared/new-test-tmp --junitxml=/prepared/regression.xml \
  tests/test_arena_aggregate.py tests/test_arena_report_audit.py \
  tests/test_arena_solver_balanced.py tests/test_arena_solver_pilot.py \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_local.py tests/test_arena_solver.py \
  tests/test_arena_solver_selection.py tests/test_arena_solver_native.py \
  tests/test_solver_feedback.py tests/test_typed_terms.py \
  tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

The initial independent copy passed those tests but failed the pre-run source
check: an automatically loaded pytest-benchmark plugin created a writable empty
`.benchmarks` directory. **No Lean process started from that copy.** It was not
repaired in place. A new independent copy used
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (while still loading the explicit repository
conftest plugin) and retained `PYTHONDONTWRITEBYTECODE=1` in child environments.
Both copies and the [initial test log](preparation-first-regression.xml) were
retained; [preparation.json](preparation.json) records the failed and successful
preparations. No caches were deleted.

After archiving, the same targeted suite passed **583 tests, 5 skipped,
89 deselected in 3.47 seconds**; see
[post-archive-regression.xml](post-archive-regression.xml). It adds explicit
secondary-pin rejection/axiom-growth tests and an archive-consistency regression;
the primary-pin test also checks that reversing declared pins cannot silently
retain the more favorable pin. The archive test does not invoke Lean or turn
historical receipts into fresh authority. The exact post-archive command, from
the repository root, was:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  --junitxml=papers/completion/lean_refactor_arena/evidence/solver-aggregate-pilot-2026-09-24/post-archive-regression.xml \
  tests/test_arena_aggregate.py tests/test_arena_report_audit.py \
  tests/test_arena_solver_balanced.py tests/test_arena_solver_pilot.py \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_local.py tests/test_arena_solver.py \
  tests/test_arena_solver_selection.py tests/test_arena_solver_native.py \
  tests/test_solver_feedback.py tests/test_typed_terms.py \
  tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

## Next bounded experiments

Implementation roles: `jevops/arena_pareto.py` owns the opt-in exact-rational
score criterion and unchanged fresh-confirmation boundary;
`jevops/arena_solver.py` adds the bounded aggregate nomination heuristic.
`tests/test_arena_aggregate.py` covers the new admission/score behavior and
historical archive consistency; `tests/test_arena_solver_balanced.py` covers
longer-proof nomination without admitting a failed composition or exceeding
budgets. README, selector/solver guides and the research plan document the
objective distinction. No new package dependency or agent framework was added.

The selector and discovery nomination are implemented; the old shortest and
strict-dual defaults are unchanged. This pilot validates aggregate-aware
selection on one already exposed task, not general superiority of a search
algorithm. Next compare score-aware discovery against its old nomination
policy under equal budgets on other ready tasks, using freshly checked
incumbents. Keep worker metric parity as a separate requirement before any
official-score claim. Broader provider final-source filters, full-corpus
coverage, learned allocation, production promotion and actual submission
remain deferred.
