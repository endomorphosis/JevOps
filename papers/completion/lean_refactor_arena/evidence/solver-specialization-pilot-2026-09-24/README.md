# Solver specialization: first public-Arena pilot

Outcome: **NO_IMPROVEMENT**. A valid smaller proof was slower, so the unchanged
original was retained. Nothing was promoted or used for training.

Task: `Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema`,
Physlib commit `c48433678e8fb6306ebcd48453300c8e16058a62`, Lean `v4.32.0`.
This public-warmup task was selected because its prepared environment and
explicit simplifier lists exercise the new path. It is not held-out evaluation.

## Discovery under fixed limits

Each arm received eight calls, four retained states, depth two, two sites and
one returned draft. Source-order site selection and first-fit state admission
were fixed before execution. The full process ceiling was 53, including
confirmation capacity; unused arm capacity was not reassigned.

| Arm | Native calls | Retained token counts | Smaller drafts | Search seconds |
| --- | ---: | --- | ---: | ---: |
| Suggestions only | 3 | 1,372 | 0 | 133.46 |
| Support minimization | 8 | 1,372 / 1,365 / 1,370 / 1,370 | 1 | 332.85 |
| Bounded frontier | 8 | 1,372 / 1,365 / 1,370 / 1,370 | 1 | 324.98 |

Both broader arms returned the **same source**, deduplicated before selection.
They reached their call limits; all arms had truncated observation/search
coverage. There is no exhaustive-search or minimality claim.

The selected discovery edit at line 35 was:

```diff
-      simp only [one_div, mul_inv_rev, FunLike.coe_sub, Pi.sub_apply]
+      simp only []
```

Native replay checked the complete 126-line theorem, not merely this line or
the tactic's output. Statement/type identity and the existing axiom policy
were preserved. The returned draft remains an unpromoted trade-off candidate.

## Fresh strict-dual screening

Both sources were checked twice in each branch order on the task's sole
declared pin. All eight observations were `VERIFIED`; receipts were not cached.

| Branch order | Reference raw heartbeats, both repeats | Draft raw heartbeats, both repeats |
| --- | ---: | ---: |
| Reference first | 27,475,681 | 27,554,621 |
| Candidate first | 27,479,265 | 27,558,205 |

Tokens fell **1,372 → 1,365 (0.5102%)**, but raw heartbeats rose by **78,940
(about 0.2873%)** in each order. The 100-raw-unit noise floor and
`strict-dual-v1` policy were set before discovery. No candidate qualified, so
fresh confirmation was **not run**; its reserved capacity remained unused.
No statistical significance, wall-time improvement or official score is claimed.

Accounting: one reference control + 19 discovery calls + eight fresh screening
calls = **28 native processes**. Staged reservations totaled 45 within the
53-process ceiling. The pilot took 1,284.82 seconds, including dependency checks
and setup; per-arm times exclude guard construction. There were no model/API
calls, downloads, dependency builds or cache deletions. About 2.31 GB remained
free inside the validated 50 GB preparation allowance. The native-work lock was
held exclusively and released after completion.

## What this establishes—and what it does not

- The real Arena path replayed support deletions, bound diagnostic hints to
  exact positions, deduplicated nominations and enforced fresh strict-dual
  selection. A smaller passing proof was not misreported as a dual-cost win.
- In this bounded run, the frontier did not outperform minimization. It filled
  its four-state capacity with earlier shorter variants. A compiler suggestion
  at line 38, `simp only [_root_.smul_apply, smul_eq_mul, Time.deriv_eq]`, was
  longer than its original tactic and could not be retained at that capacity.
  Its replacement cost was **not measured**; successful query elaboration is
  not an independently checked or timed replacement.
- This exposes a search-policy limitation: action ordering and state-slot
  allocation can prevent exploration of longer intermediates even when the
  mode permits them. A future separately frozen comparison should test balanced
  slot allocation and site coverage. No policy was changed mid-run, and no
  unused allowance was spent on post-result alternatives.
- The apparent cost of deleting normalization is specific to this proof and
  measurement protocol. It is not a universal claim that smaller support sets
  are slower. No corpus-wide benchmark gain follows from this task.

## Evidence and reproduction

[Plan](plan.json), [pilot report](report.json), [fresh selection report](selection.json),
[consistency audit](audit/summary.md), [snapshot binding](source-binding.json),
[source manifest](source-manifest.json), and [frozen regression log](regression.xml)
are retained alongside complete discovery/control receipts and the unpromoted
four-field draft. The audit reports `CONSISTENT` and `proof_verified: false`:
it checks recorded bookkeeping, not receipt authenticity or a new Lean proof.

Frozen source:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/solver-pilot-20260924-CxSWa4/source`.
Manifest SHA-256:
`4ed44ac017d805b5674eefec0a7fa116c7b5fbc9567aec2d0edd6c954123bc51`.
The 433-file, 8,815,406-byte copy was unchanged before/after tests and execution.
Hashes establish content identity, not proof or an OS sandbox. Native execution
used the existing trusted-local adapter, not a newly added sandbox.

The following is the executed native launch, with only variable names factored
out for readability. **Use a new output directory for a rerun**; the recorded
output already exists and is intentionally not reusable:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  python -I -B - <<'PY'
import runpy, sys
from pathlib import Path
root = Path('/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/solver-pilot-20260924-CxSWa4/source')
sys.path.insert(0, str(root))
sys.argv = ['arena_solver_pilot', '--problem',
 'Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema',
 '--execute', '--max-processes', '53', '--snapshot-manifest-sha256',
 '4ed44ac017d805b5674eefec0a7fa116c7b5fbc9567aec2d0edd6c954123bc51',
 '--preparation-root', '/home/barberb/.local/state/jevops-arena-provision-Nr5jXM',
 '--projects', str(root/'inputs/projects.json'),
 '--elan-home', '/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan',
 '--output', str(root.parent/'run')]
runpy.run_module('jevops.arena_solver_pilot', run_name='__main__')
PY
```

The broad targeted regression had 455 passes, 5 skips and 89 deselections.
The copied-source regression ran `test_arena_solver_pilot.py`,
`test_arena_solver.py`, `test_arena_solver_selection.py` and
`test_solver_feedback.py` with `-k 'not real_'`, seals/cache disabled and capped
temporary storage: **93 passed, 3 deselected**. These are offline orchestration
tests, separate from the 28 real Lean processes above.

After archiving, an additional regression checks that this smaller/slower draft
cannot be described as a win, that confirmation was not run, and that process
counts and the plan identity match. The expanded targeted suite then had
**456 passed, 5 skipped, 89 deselected** (2.73 seconds). Exact command:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_arena_solver_pilot.py tests/test_arena.py tests/test_arena_lean.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py tests/test_arena_local.py \
  tests/test_arena_solver.py tests/test_arena_solver_selection.py \
  tests/test_arena_solver_native.py tests/test_solver_feedback.py \
  tests/test_typed_terms.py tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

All 19 archived native output/audit files match their runtime originals byte
for byte. The pilot runner still matches its frozen protocol content hash.
`git diff --check` and Python compilation checks passed. None of these checks
is a claim that the entire repository test suite passed.
