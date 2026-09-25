# Parser-bound solver repair: native regression controls

These are implementation controls, **not a frozen optimization comparison,
score confirmation, submission or promotion**. They were run serially against
the current checkout, under the exclusive preparation lock, using installed
toolchains and scratch files on the validated 50 GB volume. No model calls,
downloads or dependency builds were enabled. The driver and solver identities
are bound in the native receipts/report; no full immutable source snapshot is
claimed for these tests. Historical JSON checks are not fresh proof checks.

## Observed results

- Lean `v4.26.0`: two stdlib tests passed in 62.80 seconds.
- Lean `v4.32.0`: two stdlib tests passed in 74.09 seconds.
- Each pin tested LF and CRLF source containing UTF-8 identifiers and a
  multiline `simp` under `constructor <;>`. Each case used exactly three
  whole-proof checks: seed, query probe, merged replacement. All 12 checks
  verified. The synthetic control proof shrank from 15 to 12 tokens; this is
  not an Arena task or an aggregate performance result.
- Strata `CallElimCorrect.extractedOldExprInVars`, commit
  `451e5f047bafa010d178856db76c00029bfa4d7f`, Lean `v4.26.0`: one real-project
  regression passed in 78.40 seconds. All **three** whole-proof checks verified.
  The earlier partial-line syntax errors were not reproduced by the new edit.

The Strata replacement merges all nine anchored suggestions (some duplicated)
into one explicit support list, preserving `at *`, the preceding `induction
post <;>` and every following case. Its new support includes both
`List.Subset.empty` and `List.append_assoc`.

| Strata source | Tokens | Observed raw heartbeats |
| --- | ---: | ---: |
| Saved incumbent | 185 | 2,324,399 |
| Checked merged replacement | 190 | 2,049,150 |

This is one reference-first discovery observation per source. It suggests a
useful longer/faster trade-off, but **no comparative score gain is confirmed**.
No balanced-order screening or fresh confirmation was performed. The unchanged
default shortest-draft policy emits no draft; the replacement is retained as a
checked frontier intermediate, not as a promoted incumbent. Its complete source
and receipts are in [strata-span-replay.json](strata-span-replay.json).

The historical 18-check nomination trial remains `NO_CANDIDATE`. This follow-up
does not relabel that result. Native execution ended and released the lock.

## Reproduction and evidence

After explicitly validating/acquiring the existing preparation volume and lock,
set `ELAN_HOME` to its `work/elan` and `TMPDIR` to its `work/tmp`. Tests must use
a fresh `--basetemp` inside that volume, never an existing directory with data.
Keep automatic external hooks/router and pytest plugin loading disabled:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=1 \
  JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  python -B -m pytest -q -s --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_arena_solver_native.py -k multiline_solver_spans
```

Repeat serially with `JEVOPS_SEARCH_LEAN_TAG=v4.32.0`. For the Strata control,
also supply `JEVOPS_STRATA_SPAN_PROJECTS` pointing to the explicit prepared
project-mapping JSON, and select
`tests/test_arena_solver_native.py::test_native_archived_strata_multiline_repair`.
The test validates exact repository/pin/source dependencies; it cannot provision
an unavailable environment. Production endpoint/execution restrictions remain
unchanged. These trusted-local controls do not claim OS sandboxing.

Original runtime outputs:

- `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/solver-span-control-qemp3e66/`
- `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/strata-span-control-3ysn6y3q/`

Copied JUnit records: [4.26](stdlib-v4.26.0.xml), [4.32](stdlib-v4.32.0.xml),
[Strata](strata-native.xml). The JSON report preserves recorded fields; archive
files may have an added final newline. A content hash identifies bytes, not proof
truth. No API cost or official score is inferred from these controls.

## Offline regression after archiving

**632 passed, 8 skipped, 89 deselected in 3.82 seconds**. This is the targeted
Arena/solver regression, not the entire repository. Native integration tests
were disabled in this run; the separate native results above are not inferred
from fixtures. [JUnit record](offline-regression.xml).

Exact command from the repository root:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -B -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  --junitxml=papers/completion/lean_refactor_arena/evidence/solver-span-repair-2026-09-24/offline-regression.xml \
  tests/test_solver_spans.py tests/test_arena_aggregate.py \
  tests/test_arena_report_audit.py tests/test_arena_solver_balanced.py \
  tests/test_arena_solver_pilot.py tests/test_arena.py tests/test_arena_lean.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py tests/test_arena_local.py \
  tests/test_arena_solver.py tests/test_arena_solver_selection.py \
  tests/test_arena_solver_native.py tests/test_solver_feedback.py \
  tests/test_typed_terms.py tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

The archived Strata JSON was compared structurally with the runtime original;
all fields matched. Its recorded solver implementation hashes still matched the
checkout at final validation. `git diff --check` also passed. These are integrity
and bookkeeping checks, not additional native verification events.
