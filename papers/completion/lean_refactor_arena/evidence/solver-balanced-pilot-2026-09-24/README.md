# Balanced solver frontier: matched native pilot

Outcome: **NO_IMPROVEMENT** under `strict-dual-v1`. The original was retained;
nothing was promoted or used for training. The new scheduling policy reached
a previously excluded, verified **longer, lower-heartbeat intermediate**, but
did not produce a smaller-and-lower-heartbeat proof within the frozen budget.

Task: `Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema`,
Physlib commit `c48433678e8fb6306ebcd48453300c8e16058a62`, Lean `v4.32.0`.
This is the same exposed public-warmup task as the previous pilot, not held-out
evaluation or evidence of corpus-wide improvement.

## Matched discovery

Each arm received eight calls, four retained states, depth two, two sites and
one draft. Both used the same `discovery-dual-first-v1` nomination heuristic;
only their action/expansion ordering differed. The protocol was frozen before
native execution and was not extended after seeing results.

| Arm | Calls | Retained tokens | Raw heartbeats in the same order | Discovery seconds |
| --- | ---: | --- | --- | ---: |
| Support-first `frontier-v1` | 8 | 1372 / 1365 / 1370 / 1370 | 27475681 / 27554621 / 27489632 / 27477568 | 337.92 |
| `balanced-frontier-v1` | 8 | 1372 / 1365 / 1377 | 27475681 / 27554621 / 25104564 | 330.01 |

Both arms reached their call caps. This is one scheduling comparison, not a
statistically established wall-time advantage or exhaustive search. Costs in
this table are real single-pin discovery observations, not fresh confirmation.
The separate [fixture comparison](fixture-comparison.json) has **synthetic**
costs and makes no Lean measurement claim.

The balanced policy independently replayed this compiler suggestion at line 38:

```diff
-      simp [Time.deriv_eq]
+      simp only [_root_.smul_apply, smul_eq_mul, Time.deriv_eq]
```

It verified the entire theorem with unchanged type and no extra axioms:
**1372 → 1377 tokens**, **27475681 → 25104564 raw heartbeats** (8.6299% lower).
That replacement was excluded by the old admission order's state cap.
Its cost is one discovery measurement, not repeated all-order confirmation.
The [four-field follow-up draft](followup-longer-intermediate.json) is explicitly
unpromoted and was **not** a screening candidate because it is longer.

The next attempted child combined that hint with empty support at line 35:

```diff
-      simp only [one_div, mul_inv_rev, FunLike.coe_sub, Pi.sub_apply]
+      simp only []
```

Each edit verified independently on the original, but their combination did
**not**. Attempt 5 in [balanced discovery](discovery-balanced-frontier-v1.json)
records `REJECTED / candidate_errors`, including type mismatches in the following
continuation and unsolved goals. It was not admitted. Broad `simp` and explicit
`simp only` do not necessarily repair the same preceding proof-state changes.
The remaining two calls probed the valid intermediate; their hints were
duplicates. No partial-support alternative was checked after the call cap.

This motivates a future separately frozen trial of context-aware shrinking or
broader site coverage around the valid intermediate. It does not authorize
composition of separately verified edits or treating a rejected child's linter
messages as proof that a change is safe.

## Fresh screening and accounting

Both arms nominated the same 1365-token deletion draft, deduplicated before
fresh selection. Two repetitions in each branch order on the task's sole
declared pin produced eight `VERIFIED` observations, with caches disabled:

| Order | Original raw heartbeats, both repeats | Draft raw heartbeats, both repeats |
| --- | ---: | ---: |
| Reference first | 27475681 | 27554621 |
| Candidate first | 27479265 | 27558205 |

The draft is seven tokens smaller but costs **78940 more raw heartbeats** in
each comparison. It fails the predeclared strict-dual policy and 100-raw-unit
noise floor. No candidate survived, so confirmation was **not run**. The
original remained verified; no recommendation or official Arena score is claimed.

One control + 16 discovery + eight screening = **25 native processes**.
Reservations totaled **37 within the 41-process ceiling**; unused capacity was
not borrowed or spent on post-result alternatives. Pilot wall time was
1132.30 seconds, excluding the preceding 460-second wait for the exclusive
preparation lock. The run stayed serial, made no model/API calls, downloads or
builds, and retained approximately 2.09 GB free inside the validated 50 GB cap.
The process exited and released its lock. No loop or background service remains.

The [audit](audit/summary.md) reports `CONSISTENT`, `proof_verified: false`:
it checks historical bookkeeping, not authenticity or a new native proof.
All 17 copied native/audit files were compared byte-for-byte with the runtime
originals. The source snapshot was unchanged before and after native execution.

## Tests and preparation

The [successful frozen regression](regression.xml) records **481 passed,
5 skipped, 89 deselected**. No live APIs or default native integration tests ran.
The initial copied-source attempt had **23 failures / 458 passes** because the
copy omitted historical test fixtures; subprocess imports also added bytecode,
so the snapshot check rejected it. It launched no Lean processes. We retained
that [failure log](preparation-failed-regression.xml) and [preparation record](preparation-log.json).
A new complete snapshot included the fixtures and inherited
`PYTHONDONTWRITEBYTECODE=1` for child commands, resolving both issues.

The corrected copy has 1477 files / 44247677 bytes. Its manifest SHA-256 is
`4a61d7d1a76941e5f95467068031592a3c849ca13ed594f7761d9a3d356151ab`;
the [manifest](source-manifest.json) and [before/after binding](source-binding.json)
are retained. Hashes identify content, not proofs or an OS sandbox.

After the native result, an additional offline regression checks that two
independently valid edits cannot authorize their rejected composition. An archive
regression checks the accounting and non-promotion without invoking Lean.
Post-archive regression: **483 passed, 5 skipped, 89 deselected** in 2.86 seconds.
The three runtime files still matched their frozen counterparts byte-for-byte;
the snapshot remained unchanged, and `git diff --check` passed. This is the
targeted suite below, not the entire repository's test suite.
The post-archive command is:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  --junitxml papers/completion/lean_refactor_arena/evidence/solver-balanced-pilot-2026-09-24/post-archive-regression.xml \
  tests/test_arena_solver_balanced.py tests/test_arena_solver_pilot.py \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_local.py tests/test_arena_solver.py \
  tests/test_arena_solver_selection.py tests/test_arena_solver_native.py \
  tests/test_solver_feedback.py tests/test_typed_terms.py \
  tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

## Native reproduction

The recorded launch below used the copied module with isolated imports, after
waiting for the lock. **Use a new output directory to rerun**; the recorded one
already exists and is deliberately not overwritable. The runner still acquires
the lock itself; an intervening owner causes it to refuse parallel execution.
No implicit provisioning or resumption is enabled.

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  python -I -B - <<'PY'
import runpy, sys
from pathlib import Path
root = Path('/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/solver-balanced-20260924-YpXh1N/source-complete')
prep = Path('/home/barberb/.local/state/jevops-arena-provision-Nr5jXM')
sys.path.insert(0, str(root))
sys.argv = ['arena_solver_pilot', '--problem',
 'Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema',
 '--comparison', 'balanced-v1', '--execute', '--max-processes', '41',
 '--snapshot-manifest-sha256', '4a61d7d1a76941e5f95467068031592a3c849ca13ed594f7761d9a3d356151ab',
 '--preparation-root', str(prep), '--projects', str(root/'inputs/projects.json'),
 '--elan-home', str(prep/'work/elan'), '--output', str(root.parent/'run')]
runpy.run_module('jevops.arena_solver_pilot', run_name='__main__')
PY
```
