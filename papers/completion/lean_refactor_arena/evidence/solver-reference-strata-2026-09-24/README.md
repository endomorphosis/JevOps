# Fixed Strata candidate: original-normalized aggregate selection

This is a fixed-candidate public development trial, not a discovery-policy
ablation, held-out evaluation, official Arena submission or promotion.
The candidate was already known from the
[parser-bound repair control](../solver-span-repair-2026-09-24/README.md).
Only its source text is reused; historical receipts and timings are not
confirmation evidence. All three arms receive fresh whole-proof checks.

## Result

**`CONFIRMED_LOCAL_IMPROVEMENT`: all 30 native checks verified.** The fixed
190-token draft improves the matched-local combined score over the incumbent
by **2.76779 percentage points**, despite five extra tokens, through about
**11.84% fewer raw heartbeats**. Against the original it has 32 fewer tokens
(14.41%), about 21.42% fewer heartbeats and **+11.94326 local score points**.
These approximate deltas describe this problem, not the corpus aggregate or
official leaderboard. Exact unrounded rational deltas in both orders are in
the [native report](report.json); [derived comparison](score-analysis.json).

Confirmation observations (three fresh checks per arm/order):

| Source | Tokens | Raw heartbeats, reference-first | Raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572–2,607,578 | 2,607,585–2,607,589 |
| Incumbent | 185 | 2,324,397 | 2,324,410–2,324,413 |
| Merged `simp only` | 190 | 2,049,150–2,049,154 | 2,049,163–2,049,164 |

The conservative descriptive gain remains above +2.76647 points versus the
incumbent in both orders, after the predeclared 100-raw-unit/range margin.
This margin is **not a statistical confidence bound**. All observations preserve
the exact target/type and report the same axioms (`Quot.sound`, `propext`).
The source edit specializes the complete initial simplification under
`induction post <;>`; it leaves every following case unchanged.

Reanalyzing the same recorded data with either `pareto-v1` or `strict-dual-v1`
selects nothing because the candidate is longer than the incumbent. This is
a selector comparison on saved measurements, not additional Lean checks or
an empirical comparison of discovery policies. The original 18-check
`NO_CANDIDATE` trial is not relabeled.

The [consistency audit](audit/summary.md) is `CONSISTENT` with zero fresh
verification events. The source manifest verified `UNCHANGED` before/after;
the archived report/manifest were compared byte-for-byte with runtime originals.
The preparation lock was released when execution ended. Observed elapsed time
after source capture was 684.12 seconds; free capped-volume space changed from
869,773,312 to 814,252,032 bytes, including the retained source snapshot.
No model calls, downloads, builds, promotion, official score or whole-corpus
performance claim. Worker metric parity remains unconfirmed.

## Precommitted protocol

- Target: `CallElimCorrect.extractedOldExprInVars`, Strata commit
  `451e5f047bafa010d178856db76c00029bfa4d7f`, its sole declared pin `v4.26.0`.
- Three arms: unchanged original (`control`), explicit incumbent
  (`historical-260`, a legacy label, **185 tokens** under the current counter),
  and one fixed [merged `simp only` draft](candidate.json), 190 tokens.
- `aggregate-local-v1`, fresh original denominators, exact unrounded rational
  deltas, predeclared 100-raw-heartbeat floor plus observed-range margin.
  Both original and incumbent comparisons must improve in both branch orders.
  Target/type preservation and no axiom growth remain hard gates.
- Screening: 3 arms × 2 branch orders × 2 repetitions = 12 checks, seed 17.
- Confirmation, only if screening qualifies: the same three fixed arms ×
  2 orders × 3 repetitions = 18 new checks, seed 18, fresh verifier instances.
- Full ceiling 30 reserved before work. No retries, alternative candidate,
  adaptive repetitions, additional search, or post-result changes.
- Native execution is serial under the kernel-held preparation lock. Existing
  prepared toolchain/dependencies only; no downloads, builds or model calls.
  Scratch/output and frozen sources use the validated capped 50 GB volume.
  This is trusted local execution, **not an OS sandbox**.

The new opt-in `discovery-reference-v1` nomination policy is separately tested
offline. It aligns a non-original seed's nomination weights with the original
reference, using the seed request's original raw observation without extra
checks. This fixed-source native trial does **not** show that it outperforms
the earlier nomination policy: it does not run competing discovery methods.
Legacy policies and historical trials are unchanged.

## Reproduction

The [launcher](run_selection.py) creates a new read-only source/input copy,
verifies its manifest before/after, reserves space, holds the exclusive lock,
and invokes the existing selector through an isolated Python import path.
It requires the prepared local project map and installation; it cannot provision
an unavailable environment. Credentials are not forwarded to the child.

Exact executed command from the repository root:

```bash
python -B papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/run_selection.py \
  --repo /home/barberb/lift_coding/JevOps \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --execute
```

Reproduction uses a new snapshot of the supplied checkout and consumes up to
30 fresh checks; saved JSON is not an admission mechanism. The selector's exact
argv and source identities are recorded in `source-binding.json`. Hashes
identify bytes, not proof truth or complete external Python/Lean installations.

This run's source root was
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/solver-reference-strata-02qnhhmz/source`.
The [manifest](source-manifest.json) identifies 1,957 files / 49,299,187 bytes;
its SHA-256 is `b956fab635266949147c141dd6fccd98fabc144ca84b3edfd7019650d72c4e60`.
The solver implementation still matches that frozen copy. Documentation and
four additional offline tests were added afterward, not injected into the run.

Recorded JSON consistency was checked with:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -B -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/audit
```

Use a new audit output directory when rerunning. This checks bookkeeping only.

## Offline regression

Before freezing: **648 passed, 8 skipped, 89 deselected in 3.90 seconds**
([JUnit](offline-regression.xml)). Four additional fixture integration cases
were added after freezing: a nominee must still beat the original, verify
secondary pins and survive fresh confirmation. The post-integration run passed
**652 tests, 8 skipped, 89 deselected in 3.97 seconds**
([JUnit](post-integration-regression.xml)). This targeted suite is not the
entire repository suite. Fixture heartbeat counts are manufactured; native
execution remains explicitly opt-in and was disabled in these test runs.

After archiving, the same command with the JUnit destination changed to
`post-archive-regression.xml` passed **652 tests, 8 skipped, 89 deselected in
3.83 seconds** ([final JUnit](post-archive-regression.xml)).
`git diff --check` passed as well.

Exact post-integration workspace test command:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -B -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  --junitxml=papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/post-integration-regression.xml \
  tests/test_arena_solver_reference.py tests/test_solver_spans.py \
  tests/test_arena_aggregate.py tests/test_arena_report_audit.py \
  tests/test_arena_solver_balanced.py tests/test_arena_solver_pilot.py \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_local.py tests/test_arena_solver.py \
  tests/test_arena_solver_selection.py tests/test_arena_solver_native.py \
  tests/test_solver_feedback.py tests/test_typed_terms.py \
  tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```
