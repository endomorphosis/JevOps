# Strata simplifier-scope trial — 2026-09-25

This bounded public-task experiment follows the [confirmed 174-token
candidate](../prefix-reference-strata-2026-09-25/README.md). It asks whether
simplifying fewer hypotheses improves measured cost. The original has 222
tokens; the **current aggregate incumbent is 174 tokens**. The shorter
169-token source is a separate strict-objective baseline, not this trial's
aggregate comparator. Historical receipts are not current proof/cost evidence.

## Confirmed result

**`CONFIRMED_LOCAL_IMPROVEMENT`**, with **all 34 native checks verified** and
the same axiom set (`propext`, `Quot.sound`). The selected goal-only proof has
**172 tokens**, two fewer than the 174-token incumbent, and uses **7.70% fewer
raw heartbeats**. Its matched-local combined-score gain is **+1.29287 points**
over that incumbent. Against the original: **222 → 172 tokens** (22.52% fewer),
**64.33% fewer heartbeats**, and **+28.94985 local score points**. These are
single-task local estimates, not an official Arena score, corpus aggregate,
held-out generalization result, or measured end-to-end runtime speedup.

Fresh confirmation (three checks per arm/order):

| Source | Tokens | Raw heartbeats, reference-first | Raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572 each | 2,607,585–2,607,587 |
| Incumbent | 174 | 1,007,840 each | 1,007,853 each |
| Goal-only winner | 172 | 930,194 each | 930,207 each |

The raw saving over the incumbent is **77,646** in each order. The conservative
descriptive combined gain stays above **+1.29158 points** after the predeclared
noise/range margin; this is not a statistical confidence bound.

Both drafts qualified in screening. The 175-token hypothesis-and-goal variant
used 952,682 / 952,695 raw heartbeats in the two orders and gained about
+0.55495 local points over the incumbent. The 172-token candidate was both
shorter and cheaper, so only it received independent confirmation. Do not
describe the alternative's four screening checks as confirmed performance.

The [172-token source](composition-0.json) is now the aggregate development
candidate; its SHA-256 is
`3a8ac904a52c3c2058333921573ae8e1faffdfe832e5bc845cc46dd7634d5d95`.
The [175-token alternative](composition-1.json) and [174-token input](incumbent.json)
are retained. Reanalysis of these same observations also satisfies strict-dual
against the supplied **174-token** incumbent, but this is **not** a strict-dual
win over the separate **169-token** source, which was not rechecked in this
trial. No production promotion, training or additional search occurred.

Actual use: **34/34 reserved processes** (16 screening + 18 confirmation), no
receipt-cache hits or retries. Launcher wall time was **778.08 seconds**.
Source binding stayed **UNCHANGED**; free capped-volume space afterward was
**339,533,824 bytes**. No caches were deleted. Runtime JSON/summary files were
compared byte-for-byte with this archive, and all three changed code/test files
still matched the frozen source.

The [native report](report.json), [derived analysis](analysis.json),
[plan](plan.json), [source binding](source-binding.json), [launch](launch.json)
and [manifest](source-manifest.json) retain exact source identities and rational
score deltas. The [selector audit](audit/summary.md) reports `CONSISTENT`, with
zero new native checks and no independent proof attestation. Content hashes
identify bytes; they do not establish proof truth.

## Frozen intervention and protocol

Two fixed candidates modify only the initial `simp only [...] at *` location:

| Candidate | Location | Tokens |
| --- | --- | ---: |
| `composition-0` | Goal only (remove `at *`) | 172 |
| `composition-1` | Introduced hypothesis and goal (`at Hnorm ⊢`) | 175 |

The support list and subsequent case proofs remain byte-for-byte unchanged.
The bounded layout matcher copies `Hnorm` from the explicit single-name intro;
it is not a Lean parser or an assertion that the hypothesis remains in scope.
Both source nominations require fresh whole-proof checking. No profile hint,
historical offset or old success flag can admit a draft.

The existing composition and leaf-pilot modules implement the opt-in
`simp-prefix-scope` profile. `aggregate-local-v1` is explicitly selected;
strict-dual remains the default elsewhere. The task is
`CallElimCorrect.extractedOldExprInVars`, with its sole declared Lean 4.26.0
pin and Strata commit `451e5f047bafa010d178856db76c00029bfa4d7f`.

**34-process ceiling**, reserved before work: sixteen screening checks
(original, incumbent, two candidates × two repeats × both branch orders),
then eighteen independent confirmation checks for only the frozen winner
(original, incumbent, winner × three repeats × both orders). The noise floor
is 100 raw heartbeats plus observed ranges. Selection must improve against
both original and incumbent. No retry, alternative confirmation winner,
adaptive search expansion or production promotion is permitted.

Plan-only command, requiring no Lean/model invocation:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/solver-0.json \
  --profile simp-prefix-scope --selection-objective aggregate-local-v1
```

Observed: 34 required processes, 172/175-token drafts, plan SHA-256
`1e0dd802b6ba05d2d9892b05735546b73ca6d466958f3259f6bf734b17ba2151`.

## Execution identity

Runtime directory:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/simp-scope-strata-_lw_u2jf`.
Read-only source copy: **2,099 files / 55,813,602 bytes**; manifest SHA-256
`d2e864974859de98a0de5ddce8ae790f1361b3aa9d374a1c9c7832311a97de60`, content root
`ade3aa14ea8b49beac61a1dbfb1a691c10a88dfe845c3353bb5f29c348fadeb0`.
The child uses an isolated Python import path and receives only
PATH/HOME/LANG/LC_ALL plus explicit disabled external hooks/router flags and
capped-volume TMPDIR. Measurements run serially under the preparation lock,
using existing project/toolchain caches, with a 50 GB storage cap and 100 MB
runtime reserve. Trusted-local execution is not an OS sandbox. No downloads,
dependency builds, API/model calls, training or official submission occur.

Actual command, cwd in the snapshot's `source`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys;sys.path.insert(0,sys.argv.pop(1));from jevops.arena_leaf_pilot import main;raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/simp-scope-strata-_lw_u2jf/source \
  --problem CallElimCorrect.extractedOldExprInVars --incumbent inputs/incumbent.json \
  --profile simp-prefix-scope --selection-objective aggregate-local-v1 \
  --execute --max-processes 34 \
  --snapshot-manifest-sha256 d2e864974859de98a0de5ddce8ae790f1361b3aa9d374a1c9c7832311a97de60 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/simp-scope-strata-_lw_u2jf/experiment
```

New executions require new snapshot/output identities; do not overwrite this
evidence or treat saved JSON as fresh native verification.

The recorded-result consistency audit was run with:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/audit
```

Use a new audit output directory for a rerun. This rechecks bookkeeping only.

## Offline regression before freezing

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-simp-scope-tests/cache \
  --junitxml=/tmp/jevops-simp-scope-tests/regression.xml \
  tests/test_arena_simp_scope.py tests/test_arena_compositions.py \
  tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py \
  tests/test_arena_aggregate.py tests/test_solver_spans.py -q
```

**607 passed, three skipped in 43.72 seconds**; zero reused seals, 561 fresh
passes sealed. This is targeted offline regression, not a whole-repository
test run or native proof evidence. The tests exercise source/envelope identity,
unchanged continuation, explicit name copying, limits, unsupported syntax,
non-shortening nominations, deduplication, helper-source fingerprints, correct
baseline/confirmation reservations, and pre-work plan-mutation rejection.

## Implementation and remaining work

- `jevops/arena_compositions.py`: bounded exact-source scope nominations,
  explicit-intro name copying, and transitive helper-source fingerprints.
- `jevops/arena_leaf_pilot.py`: fixed two-path `simp-prefix-scope` profile,
  reusing the existing fresh selector and resource guards.
- `tests/test_arena_simp_scope.py`: offline nomination/plan regression cases.
- `ARENA_SOLVER_SPECIALIZATION.md`, the root README and the safety plan:
  implemented contract, measured result and baseline distinctions.

Next test support removal with dependent case repair against the **172-token
aggregate** candidate. Removing append normalization previously broke the
fixed `ite` continuation; this trial did not attempt such a repair. Broad
task coverage, held-out evaluation, organizer-worker metric parity and
production/security gates remain open. Scope narrowing alone does not establish
global proof minimality or a general speedup across Lean versions/projects.
