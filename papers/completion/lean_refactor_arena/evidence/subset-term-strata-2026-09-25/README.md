# Strata direct append terms — 2026-09-25

## Hypothesis and frozen objective

The [preceding normalization experiment](../subset-normalize-strata-2026-09-25/README.md)
closed both shorter proofs without axiom growth but increased heartbeats by
about 29–30%. This follow-up retains the actual **169-token incumbent** and
nominates direct applications of the existing append lemmas, avoiding
whole-context simplification in that subtree.

Source inspection/counting showed that direct terms are **longer**, not shorter:
181 and 178 tokens against 169 (original 222). Before any native results, this
batch explicitly froze **`aggregate-local-v1`**, not `strict-dual-v1`. That
separate objective tests whether a heartbeat saving pays for the extra source
tokens. It does not relax the strict objective or replace its incumbent.

Two predetermined candidates, changing only the recognized three-leaf `ite`
subtree after `cases Hnorm`:

```lean
-- composition-0: one complete term, 181 tokens for the whole proof
exact List.Subset.app
  (List.subset_append_of_subset_left _ (cih ‹_›))
  (List.subset_append_of_subset_right _ (List.Subset.app
    (List.subset_append_of_subset_left _ (tih ‹_›))
    (List.subset_append_of_subset_right _ (eih ‹_›))))

-- composition-1: direct leaves, retained outer tactic tree, 178 tokens
apply List.Subset.app
. exact List.subset_append_of_subset_left _ (cih ‹_›)
apply List.subset_append_of_subset_right
apply List.Subset.app
. exact List.subset_append_of_subset_left _ (tih ‹_›)
. exact List.subset_append_of_subset_right _ (eih ‹_›)
```

The renderer captures existing leaf identifiers, not arbitrary expressions;
`‹_›` asks the Lean elaborator to find the required local premise. This is not
an assumed proof, imported receipt, model response or new trusted lemma. No
imports, global helpers, statements or other branches change. Complete native
verification, target/type checking and no-axiom-growth admission remain required.

## Protocol and limits

Task: `CallElimCorrect.extractedOldExprInVars`; Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`; only declared pin `v4.26.0`.
The incumbent source is [the archived 169-token winner](../subset-triple-strata-2026-09-25/incumbent.json),
not the superseded 185-token solver baseline. Saved observations are not fresh
proof or measurement events.

- Screen: original/incumbent/two drafts × two branch orders × two repetitions
  = **16 native checks**.
- Confirmation: original/incumbent/one fixed winner × two orders × three fresh
  repeats = **18 checks reserved**; total ceiling **34**, seeds 17/18.
- No retries, alternate winner, adaptive draft expansion, or reallocation of
  unused confirmation allowance.
- Exact reference-normalized aggregate deltas must beat both original and
  incumbent in each primary-pin branch order after the frozen **100 raw
  heartbeat** margin and observed-range adjustment. All declared pins must
  verify with no axiom growth. Existing selector implementation is unchanged.
- Score delta formula: `100/3 * ((comparator_tokens - candidate_tokens) /
  original_tokens + (comparator_raw - candidate_raw) / original_raw)`.
  Each phase uses its fresh original controls, not published heartbeat fields.
- No production promotion, live model/API calls, training, provisioning or
  builds. Existing 50 GB capped preparation volume and kernel-held serial
  preparation lock are retained. Caches and unsuccessful evidence are kept.

This is one exposed development task, not held-out evaluation, corpus-wide
improvement, a trained policy or official Arena score. Worker metric parity
remains unconfirmed. The read-only source copy protects against accidental
workspace edits, not hostile users or Lean metaprograms; it is not an OS sandbox.

## Observed result: no aggregate improvement

The frozen run completed with **16/16 checks VERIFIED**, all four arms
admissible, and **NO_IMPROVEMENT**. Wall time including snapshot/resource
checks was **377.76 seconds**. All arms retained exactly `propext` and
`Quot.sound`; target/type and no-axiom-growth checks passed.

| Arm | Tokens | Reference-first raw heartbeats | Candidate-first raw heartbeats |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572–2,607,574 | 2,607,585–2,607,585 |
| Incumbent | 169 | 1,283,749–1,283,749 | 1,283,762–1,283,762 |
| Whole term (`composition-0`) | 181 | 1,304,531–1,304,532 | 1,304,544–1,304,544 |
| Leaf terms (`composition-1`) | 178 | 1,307,677–1,307,677 | 1,307,690–1,307,690 |

Compared with the incumbent, whole-term/leaf-term drafts use **1.62% / 1.86%
more raw heartbeats** (means of four matched samples per arm), as well as
12/9 more tokens. The incumbent therefore dominates both measured drafts.
Their nominal local aggregate deltas are **−2.067 / −1.657 percentage points**
versus the incumbent in both branch orders; the conservative deltas are
approximately −2.069 / −1.659 points. Exact per-order rational values remain
in the JSON. These are losses, not an inconclusive noise overlap.

Both drafts beat the original (+22.813 / +23.224 nominal local points), but
that weaker comparison is not a gain over the best known incumbent. It does
not authorize recommendation. No official score or statistical significance
is claimed, and there were **zero confirmation checks**. The unused 18-check
allowance was not reassigned. The 169-token source stays the incumbent.

No retries, model/API calls, downloads, builds, training, automatic promotion
or cache deletion occurred. The source binding is **UNCHANGED** before and
after work. The [consistency audit](audit/summary.md) reports **CONSISTENT**
for all 16 samples and both branch orders. That audit is historical-record
checking, not an independent proof attestation; it makes zero new Lean calls.

Artifacts: [report](report.json), [summary](summary.md),
[accounting](accounting.json), [source binding](source-binding.json),
[screen reservation](screen-reservation.json), [pilot plan](plan.json),
[selection protocol](selection-protocol.json), [launch](launch.json),
[source manifest](source-manifest.json), [targeted JUnit](regression.xml),
and [supplemental JUnit](safety.xml).

Audit command actually run:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/subset-term-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/subset-term-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/subset-term-strata-2026-09-25/audit
```

This falsifies a cost benefit for these two exact direct-term replacements on
this task, not for all direct proofs. The next investigation should measure
other remaining proof regions, including the shared simplification prefix,
before allocating more trials to the same append subtree. Such profiling and
new candidates are deferred; no claim about their cost or correctness is made.

## Commands and identities

Plan only, zero Lean/model calls:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json \
  --profile subset-triple-term --selection-objective aggregate-local-v1
```

It returned token counts 181/178, required processes 34, plan SHA-256
`0fe248e59689766f284ebc88d120005d3b0bd08833833df5716ae7576c6aaab3`.

Runtime root: `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-term-strata-qbn05df0`.
Snapshot: **2,018 files, 52,645,169 bytes**, manifest SHA-256
`b504f7783de18dee94dad4983ee4225c63319eba666fcec48ad001b26e421f0f`, content root
`0f06f81e10ee117b58151f047c2be85182f1b0e44068e0c0470549d7bd78c1cd`.
Hashes identify content; they are not proof attestations.

The existing `arena_snapshot.create_snapshot` captured `jevops`, `tests`,
`papers/completion/lean_refactor_arena`, `pyproject.toml`, `pytest.ini`,
`conftest.py`, `ARENA_COMPOSITIONS.md`, and explicit `inputs/incumbent.json` and
`inputs/projects.json`, under the preparation lock. Volume free space before
capture was 641,290,240 bytes; runtime checks retain a 100 MB reserve.

Actual command, cwd at the runtime root's `source`. The wrapper forwarded only
PATH/HOME/LANG/LC_ALL, with `PYTHONDONTWRITEBYTECODE=1`,
`JEVOPS_REGISTER_LRA_HOOKS=0`, `JEVOPS_USE_EXTERNAL_DEPS=0`,
`JEVOPS_USE_EXTERNAL_ROUTER=0`, and TMPDIR set to
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys; sys.path.insert(0,sys.argv.pop(1)); from jevops.arena_leaf_pilot import main; raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-term-strata-qbn05df0/source \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent inputs/incumbent.json --profile subset-triple-term \
  --selection-objective aggregate-local-v1 --execute --max-processes 34 \
  --snapshot-manifest-sha256 b504f7783de18dee94dad4983ee4225c63319eba666fcec48ad001b26e421f0f \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-term-strata-qbn05df0/selection
```

Reruns need a new snapshot/output directory; never overwrite archived evidence.

## Fresh regression tests

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-term-tests-ccrGDL0n/cache \
  --junitxml=/tmp/jevops-term-tests-ccrGDL0n/regression.xml \
  tests/test_arena_compositions.py tests/test_arena_leaf_pilot.py \
  tests/test_arena_pareto.py tests/test_arena_aggregate.py -q
```

Observed: **521 passed, 3 skipped**, zero reused, **475 fresh passes sealed**,
36.03 seconds. Thirty-eight additional cases cover both exact renderings,
Unicode/primed hypothesis capture, untouched branches, unsafe name rejection,
16/17-token growth boundary, explicit aggregate opt-in, unchanged strict
defaults, objective/plan tampering, full budget reservation and forwarding to
the existing selector. Existing malformed-layout cases exercise both new rules.

Supplemental rules/provider/audit suite, on a byte-identical read-only host
copy of the captured source (avoids FUSE test traversal overhead):

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -I -B -c \
  'import os,sys; os.chdir(sys.argv[1]); sys.path.insert(0,sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' \
  /tmp/jevops-term-safety-u5g5ZExP/source --test-seal=refresh \
  -o cache_dir=/tmp/jevops-term-safety-u5g5ZExP/cache \
  --junitxml=/tmp/jevops-term-safety-u5g5ZExP/safety.xml \
  tests/test_arena_rules.py tests/test_arena_providers.py tests/test_arena_report_audit.py -q
```

Observed: **139 passed, 3 skipped**, zero reused, **133 fresh passes sealed**,
9.78 seconds. Total **660 passed / 6 skipped**, **608 fresh passes sealed**.
These targeted suites are not a full-repository result; fixtures do not count
as native proof or performance evidence.
The copied snapshot verified `UNCHANGED` after the supplemental run. All four
edited implementation/test files still match the captured/executed bytes;
archived native outputs are byte-identical to the runtime originals. Local
archive links resolve and `git diff --check` passed. Later documentation
updates were not part of the executed source snapshot.

## Changed files and compatibility

- `jevops/arena_compositions.py`: two direct-term rules in the existing bounded
  matcher/renderer, safe hypothesis capture, explicit 16-token growth bound.
  No parallel runtime, general Lean parser or verifier is introduced.
- `jevops/arena_leaf_pilot.py`: fixed two-arm profile and objective parameter/CLI
  flag, default still strict-dual. v4 plans bind the objective before work.
  Old v3 plans are stale execution inputs; replan rather than reinterpret them.
- `tests/test_arena_compositions.py`, `tests/test_arena_leaf_pilot.py`: new
  nomination, growth, freeze and selector-forwarding regressions.
- `ARENA_COMPOSITIONS.md`, root README, safety plan and this archive: protocol,
  trust boundary, actual measurements and limitations.

Python tests enforce proposal shape and planning/resource rules, not semantics.
Native whole-source checks establish acceptance only under their declared
target/type/axiom policy and trusted local dependencies. Neither proof validity
nor lower source token count implies lower measured elaboration cost.
